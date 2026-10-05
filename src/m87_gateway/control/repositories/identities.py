"""Application policies and independently revocable credential digests."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from m87_gateway.config import AppConfig
from .base import SQLiteRepository


class KeyLimitError(ValueError):
    """Bound the number of simultaneously active credentials per application."""


class SQLiteIdentityRepository(SQLiteRepository):
    @staticmethod
    def migrate(connection: sqlite3.Connection, previous_version: int) -> None:
        if previous_version >= 3:
            return
        connection.execute("ALTER TABLE app_keys RENAME TO legacy_app_keys")
        connection.execute("""CREATE TABLE applications (
            app_id TEXT PRIMARY KEY, project_id TEXT NOT NULL DEFAULT 'default',
            allowed_models TEXT NOT NULL, capture_content INTEGER NOT NULL DEFAULT 0,
            rate_limit_per_minute INTEGER, max_concurrent_requests INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE app_keys (
            key_id TEXT PRIMARY KEY, app_id TEXT NOT NULL REFERENCES applications(app_id) ON DELETE CASCADE,
            key_digest TEXT NOT NULL UNIQUE, key_prefix TEXT NOT NULL,
            created_at TEXT NOT NULL, expires_at TEXT, revoked_at TEXT
        )""")
        connection.execute("CREATE INDEX app_keys_application ON app_keys(app_id, created_at DESC)")
        connection.execute("""INSERT INTO applications
            SELECT app_id, project_id, allowed_models, capture_content, rate_limit_per_minute,
                max_concurrent_requests, enabled, created_at FROM legacy_app_keys""")
        connection.execute("""INSERT INTO app_keys
            SELECT lower(hex(randomblob(16))), app_id, key_digest, key_prefix, created_at,
                NULL, CASE WHEN enabled = 0 THEN created_at ELSE NULL END FROM legacy_app_keys""")
        connection.execute("DROP TABLE legacy_app_keys")

    def _digest(self, value: str) -> str:
        return hmac.new(self._digest_key, value.encode(), hashlib.sha256).hexdigest()

    def _issue(
        self, connection: sqlite3.Connection, app_id: str, expires_in_days: int | None = None
    ) -> tuple[dict[str, Any], str]:
        if expires_in_days is not None and (
            isinstance(expires_in_days, bool)
            or not isinstance(expires_in_days, int)
            or not 1 <= expires_in_days <= 3650
        ):
            raise ValueError("Key expiry must be between 1 and 3650 days")
        raw_key = f"m87_{secrets.token_urlsafe(32)}"
        now = datetime.now(timezone.utc)
        metadata = {
            "key_id": secrets.token_hex(16),
            "app_id": app_id,
            "key_prefix": raw_key[:12],
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(days=expires_in_days)).isoformat()
            if expires_in_days
            else None,
            "revoked_at": None,
        }
        connection.execute(
            "INSERT INTO app_keys VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (
                metadata["key_id"],
                app_id,
                self._digest(raw_key),
                metadata["key_prefix"],
                metadata["created_at"],
                metadata["expires_at"],
            ),
        )
        return metadata, raw_key

    def create_app_key(
        self,
        app_id: str,
        allowed_models: list[str],
        capture_content: bool,
        rate_limit_per_minute: int | None = None,
        project_id: str = "default",
        max_concurrent_requests: int | None = None,
    ) -> tuple[dict[str, Any], str]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            self._require_project(connection, project_id)
            connection.execute(
                "INSERT INTO applications VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (
                    app_id,
                    project_id,
                    json.dumps(allowed_models),
                    capture_content,
                    rate_limit_per_minute,
                    max_concurrent_requests,
                    now,
                ),
            )
            metadata, key = self._issue(connection, app_id)
            self.backend.management_audit.record(
                connection, "application.created", project_id, app_id, metadata["key_id"]
            )
        return {
            **metadata,
            "project_id": project_id,
            "allowed_models": allowed_models,
            "capture_content": capture_content,
            "rate_limit_per_minute": rate_limit_per_minute,
            "max_concurrent_requests": max_concurrent_requests,
        }, key

    def issue_app_key(
        self, app_id: str, expires_in_days: int | None = None, revoke_existing: bool = False
    ) -> tuple[dict[str, Any], str]:
        with self._connect() as connection:
            # Serialize concurrent issuances and revocations before checking the active-key bound.
            connection.execute("BEGIN IMMEDIATE")
            app = connection.execute(
                "SELECT project_id FROM applications WHERE app_id = ? AND enabled = 1", (app_id,)
            ).fetchone()
            if app is None:
                raise ValueError("Application does not exist")
            now = datetime.now(timezone.utc).isoformat()
            active = connection.execute(
                "SELECT key_id FROM app_keys WHERE app_id = ? AND revoked_at IS NULL "
                "AND (expires_at IS NULL OR expires_at > ?)",
                (app_id, now),
            ).fetchall()
            if not revoke_existing and len(active) >= 10:
                raise KeyLimitError("Application has ten active keys")
            metadata, key = self._issue(connection, app_id, expires_in_days)
            if revoke_existing:
                for row in active:
                    connection.execute(
                        "UPDATE app_keys SET revoked_at = ? WHERE key_id = ?", (now, row["key_id"])
                    )
                    self.backend.management_audit.record(
                        connection,
                        "application_key.revoked",
                        app["project_id"],
                        app_id,
                        row["key_id"],
                    )
            self.backend.management_audit.record(
                connection, "application_key.issued", app["project_id"], app_id, metadata["key_id"]
            )
        return metadata, key

    def list_app_keys(self, app_id: str) -> list[dict[str, Any]] | None:
        with self._connect() as connection:
            if not connection.execute(
                "SELECT 1 FROM applications WHERE app_id = ?", (app_id,)
            ).fetchone():
                return None
            rows = connection.execute(
                "SELECT key_id, app_id, key_prefix, created_at, expires_at, revoked_at "
                "FROM app_keys WHERE app_id = ? ORDER BY created_at DESC, key_id DESC",
                (app_id,),
            ).fetchall()
        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                **dict(row),
                "active": row["revoked_at"] is None
                and (row["expires_at"] is None or row["expires_at"] > now),
            }
            for row in rows
        ]

    def revoke_app_key(self, app_id: str, key_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT a.project_id, k.revoked_at FROM app_keys k JOIN applications a USING(app_id) "
                "WHERE k.app_id = ? AND k.key_id = ?",
                (app_id, key_id),
            ).fetchone()
            if row is None:
                return False
            if row["revoked_at"] is None:
                connection.execute(
                    "UPDATE app_keys SET revoked_at = ? WHERE key_id = ?",
                    (datetime.now(timezone.utc).isoformat(), key_id),
                )
                self.backend.management_audit.record(
                    connection, "application_key.revoked", row["project_id"], app_id, key_id
                )
        return True

    def authenticate_app_key(self, raw_key: str) -> AppConfig | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT a.* FROM app_keys k JOIN applications a USING(app_id) "
                "WHERE k.key_digest = ? AND a.enabled = 1 AND k.revoked_at IS NULL "
                "AND (k.expires_at IS NULL OR k.expires_at > ?)",
                (self._digest(raw_key), datetime.now(timezone.utc).isoformat()),
            ).fetchone()
        if row is None:
            return None
        return AppConfig(
            app_id=row["app_id"],
            project_id=row["project_id"],
            api_key=raw_key,
            allowed_models=json.loads(row["allowed_models"]),
            capture_content=bool(row["capture_content"]),
            rate_limit_per_minute=row["rate_limit_per_minute"],
            max_concurrent_requests=row["max_concurrent_requests"],
        )

    def list_apps(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT a.*, COALESCE((SELECT key_prefix FROM app_keys k
                WHERE k.app_id = a.app_id AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY created_at DESC, key_id DESC LIMIT 1), '') AS key_prefix,
                (SELECT COUNT(*) FROM app_keys k WHERE k.app_id = a.app_id AND revoked_at IS NULL
                    AND (expires_at IS NULL OR expires_at > ?)) AS active_key_count
                FROM applications a ORDER BY a.created_at DESC""",
                (datetime.now(timezone.utc).isoformat(),) * 2,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["allowed_models"] = json.loads(item["allowed_models"])
            item["capture_content"] = bool(item["capture_content"])
            item["enabled"] = bool(item["enabled"])
            result.append(item)
        return result

    @staticmethod
    def _require_project(connection: sqlite3.Connection, project_id: str) -> None:
        if not connection.execute(
            "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone():
            raise ValueError("Project does not exist")

    def ensure_projects(self, identifiers: list[str]) -> None:
        with self._connect() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO projects VALUES (?, ?, ?)",
                [
                    (identifier, identifier, datetime.now(timezone.utc).isoformat())
                    for identifier in set(identifiers)
                ],
            )

    def create_project(self, project_id: str, name: str) -> dict:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO projects VALUES (?, ?, ?)", (project_id, name, created_at)
            )
            self.backend.management_audit.record(connection, "project.created", project_id)
        return {"project_id": project_id, "name": name, "created_at": created_at, "app_count": 0}

    def list_projects(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("""SELECT p.*, COUNT(a.app_id) AS app_count
                FROM projects p LEFT JOIN applications a ON a.project_id = p.project_id
                GROUP BY p.project_id ORDER BY p.created_at, p.project_id""").fetchall()
        return [dict(row) for row in rows]

    def _update_app(self, app_id: str, fields: dict[str, Any], action: str) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT project_id FROM applications WHERE app_id = ? AND enabled = 1", (app_id,)
            ).fetchone()
            if row is None:
                return False
            if "project_id" in fields:
                self._require_project(connection, fields["project_id"])
            assignments = ", ".join(f"{name} = ?" for name in fields)
            connection.execute(
                f"UPDATE applications SET {assignments} WHERE app_id = ?",
                (*fields.values(), app_id),
            )
            self.backend.management_audit.record(
                connection, action, fields.get("project_id", row["project_id"]), app_id
            )
        return True

    def assign_app_project(self, app_id: str, project_id: str) -> bool:
        return self._update_app(app_id, {"project_id": project_id}, "application.project_changed")

    def update_app_limits(self, app_id, rate_limit_per_minute, max_concurrent_requests):
        return self._update_app(
            app_id,
            {
                "rate_limit_per_minute": rate_limit_per_minute,
                "max_concurrent_requests": max_concurrent_requests,
            },
            "application.limits_changed",
        )

    def update_app_models(self, app_id: str, allowed_models: list[str]) -> bool:
        return self._update_app(
            app_id, {"allowed_models": json.dumps(allowed_models)}, "application.models_changed"
        )

    def delete_app(self, app_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT project_id FROM applications WHERE app_id = ?", (app_id,)
            ).fetchone()
            if row is None:
                return False
            connection.execute("DELETE FROM applications WHERE app_id = ?", (app_id,))
            self.backend.management_audit.record(
                connection, "application.deleted", row["project_id"], app_id
            )
        return True
