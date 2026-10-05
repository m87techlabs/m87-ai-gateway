"""Administrative identity changes, without credential values or request content."""

import secrets
import sqlite3
from typing import Any
from datetime import datetime, timedelta, timezone

from .base import SQLiteRepository


class SQLiteManagementAuditRepository(SQLiteRepository):
    @staticmethod
    def migrate(connection: sqlite3.Connection) -> None:
        connection.execute("""CREATE TABLE IF NOT EXISTS management_events (
            event_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
            actor TEXT NOT NULL, action TEXT NOT NULL,
            project_id TEXT, app_id TEXT, key_id TEXT
        )""")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS management_created ON management_events(created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS management_project_created "
            "ON management_events(project_id, created_at DESC)"
        )

    def record(
        self,
        connection: sqlite3.Connection,
        action: str,
        project_id: str | None = None,
        app_id: str | None = None,
        key_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        connection.execute(
            "INSERT INTO management_events VALUES (?, ?, 'operator', ?, ?, ?, ?)",
            (secrets.token_hex(16), now.isoformat(), action, project_id, app_id, key_id),
        )
        cutoff = now - timedelta(days=self.config.management_audit_retention_days)
        connection.execute(
            "DELETE FROM management_events WHERE created_at < ?", (cutoff.isoformat(),)
        )

    def list_management_events(
        self, limit: int = 100, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        where = "WHERE project_id = ?" if project_id is not None else ""
        values = [project_id, limit] if project_id is not None else [limit]
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM management_events {where} ORDER BY created_at DESC, event_id DESC LIMIT ?",
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def prune(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=self.config.management_audit_retention_days
        )
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM management_events WHERE created_at < ?", (cutoff.isoformat(),)
            )
