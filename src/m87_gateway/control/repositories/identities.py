"""SQLite identities repository; shares the local backend transaction boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

from m87_gateway.config import AppConfig

from .base import SQLiteRepository


class SQLiteIdentityRepository(SQLiteRepository):
    def update_app_limits(self, app_id, rate_limit_per_minute, max_concurrent_requests):
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE app_keys SET rate_limit_per_minute = ?, max_concurrent_requests = ? "
                "WHERE app_id = ? AND enabled = 1",
                (rate_limit_per_minute, max_concurrent_requests, app_id),
            )
        return result.rowcount > 0

    def _digest(self, value: str) -> str:
        return hmac.new(self._digest_key, value.encode(), hashlib.sha256).hexdigest()

    def create_app_key(
        self,
        app_id: str,
        allowed_models: list[str],
        capture_content: bool,
        rate_limit_per_minute: int | None = None,
        project_id: str = "default",
        max_concurrent_requests: int | None = None,
    ) -> tuple[dict[str, Any], str]:
        raw_key = f"m87_{secrets.token_urlsafe(32)}"
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            self._require_project(connection, project_id)
            connection.execute(
                """INSERT INTO app_keys
                   (app_id, key_digest, key_prefix, allowed_models, capture_content,
                    rate_limit_per_minute, created_at, project_id, max_concurrent_requests)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    app_id,
                    self._digest(raw_key),
                    raw_key[:12],
                    json.dumps(allowed_models),
                    capture_content,
                    rate_limit_per_minute,
                    created_at,
                    project_id,
                    max_concurrent_requests,
                ),
            )
        return (
            {
                "app_id": app_id,
                "project_id": project_id,
                "key_prefix": raw_key[:12],
                "allowed_models": allowed_models,
                "capture_content": capture_content,
                "rate_limit_per_minute": rate_limit_per_minute,
                "max_concurrent_requests": max_concurrent_requests,
                "created_at": created_at,
            },
            raw_key,
        )

    def authenticate_app_key(self, raw_key: str) -> AppConfig | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM app_keys WHERE key_digest = ? AND enabled = 1",
                (self._digest(raw_key),),
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
                """SELECT app_id, project_id, key_prefix, allowed_models, capture_content,
                          rate_limit_per_minute, max_concurrent_requests, enabled, created_at
                   FROM app_keys ORDER BY created_at DESC"""
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
        if (
            connection.execute(
                "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            is None
        ):
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
        return {"project_id": project_id, "name": name, "created_at": created_at, "app_count": 0}

    def list_projects(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("""SELECT p.*, COUNT(a.app_id) AS app_count
                FROM projects p LEFT JOIN app_keys a ON a.project_id = p.project_id
                GROUP BY p.project_id ORDER BY p.created_at, p.project_id""").fetchall()
        return [dict(row) for row in rows]

    def assign_app_project(self, app_id: str, project_id: str) -> bool:
        with self._connect() as connection:
            self._require_project(connection, project_id)
            cursor = connection.execute(
                "UPDATE app_keys SET project_id = ? WHERE app_id = ?", (project_id, app_id)
            )
        return cursor.rowcount > 0

    def delete_app(self, app_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM app_keys WHERE app_id = ?", (app_id,))
        return cursor.rowcount > 0

    def update_app_models(self, app_id: str, allowed_models: list[str]) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE app_keys SET allowed_models = ? WHERE app_id = ? AND enabled = 1",
                (json.dumps(allowed_models), app_id),
            )
        return cursor.rowcount > 0
