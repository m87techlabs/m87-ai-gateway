"""Transactional settings history; snapshots exclude credential values."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .base import SQLiteRepository, tighten_sqlite_files

HISTORY_LIMIT = 100


class RevisionConflict(ValueError):
    """Another configuration was activated after the operator loaded history."""


class SQLiteConfigurationRepository(SQLiteRepository):
    @staticmethod
    def migrate(connection: sqlite3.Connection) -> None:
        connection.execute("""CREATE TABLE IF NOT EXISTS configuration_revisions (
            revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL, action TEXT NOT NULL,
            restored_from INTEGER, encrypted_snapshot BLOB NOT NULL
        )""")

    def runtime_config(self) -> dict:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM runtime_config WHERE id = 1").fetchone()
        return json.loads(row["value"]) if row else {}

    def initialize_history(self, snapshot: dict) -> None:
        """Capture the effective initial settings without changing file overrides."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM configuration_revisions LIMIT 1").fetchone():
                self._revision(connection, snapshot, "configuration.baseline", None)
        tighten_sqlite_files(self.database_path)

    def _revision(self, connection, snapshot, action, restored_from):
        encrypted = self._fernet.encrypt(json.dumps(snapshot, sort_keys=True).encode())
        cursor = connection.execute(
            "INSERT INTO configuration_revisions(created_at, action, restored_from, "
            "encrypted_snapshot) VALUES (?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), action, restored_from, encrypted),
        )
        revision = cursor.lastrowid
        connection.execute(
            "DELETE FROM configuration_revisions WHERE revision_id NOT IN "
            "(SELECT revision_id FROM configuration_revisions ORDER BY revision_id DESC LIMIT ?)",
            (HISTORY_LIMIT,),
        )
        return revision

    def list_config_revisions(self, limit: int = 100) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT revision_id, created_at, action, restored_from FROM configuration_revisions "
                "ORDER BY revision_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def config_revision(self, revision_id: int) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT encrypted_snapshot FROM configuration_revisions WHERE revision_id = ?",
                (revision_id,),
            ).fetchone()
        return json.loads(self._fernet.decrypt(row[0])) if row else None

    def save_runtime_config(
        self,
        value: dict,
        provider=None,
        key=None,
        clear_key=False,
        *,
        snapshot=None,
        action="configuration.updated",
        restored_from=None,
        expected_revision=None,
        clear_providers=(),
    ):
        """Commit settings, credential changes, revision and audit together."""
        serialized = json.dumps(value)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT MAX(revision_id) FROM configuration_revisions"
            ).fetchone()[0]
            if expected_revision is not None and expected_revision != current:
                raise RevisionConflict("Configuration changed; reload history")
            revision = self._revision(
                connection, snapshot if snapshot is not None else value, action, restored_from
            )
            audit = self.backend.management_audit
            for name in clear_providers:
                aliases = connection.execute(
                    "SELECT alias FROM provider_keys WHERE provider = ?", (name,)
                ).fetchall()
                connection.execute("DELETE FROM provider_keys WHERE provider = ?", (name,))
                for row in aliases:
                    audit.record(
                        connection,
                        "provider_key.deleted",
                        provider=name,
                        alias=row[0],
                        revision_id=revision,
                    )
            if provider and clear_key:
                aliases = connection.execute(
                    "SELECT alias FROM provider_keys WHERE provider = ?", (provider,)
                ).fetchall()
                connection.execute("DELETE FROM provider_keys WHERE provider = ?", (provider,))
                for row in aliases:
                    audit.record(
                        connection,
                        "provider_key.deleted",
                        provider=provider,
                        alias=row[0],
                        revision_id=revision,
                    )
            if provider and key:
                now = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    "INSERT INTO provider_keys(provider, alias, encrypted_value, created_at, "
                    "updated_at) VALUES (?, 'default', ?, ?, ?) ON CONFLICT(provider, alias) "
                    "DO UPDATE SET encrypted_value=excluded.encrypted_value, "
                    "updated_at=excluded.updated_at, last_used_at=NULL",
                    (provider, self._fernet.encrypt(key.encode()), now, now),
                )
                audit.record(
                    connection,
                    "provider_key.saved",
                    provider=provider,
                    alias="default",
                    revision_id=revision,
                )
            connection.execute(
                "INSERT INTO runtime_config(id, value) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                (serialized,),
            )
            audit.record(
                connection,
                action,
                provider=provider,
                revision_id=revision,
                restored_from=restored_from,
            )
        tighten_sqlite_files(self.database_path)
        return revision
