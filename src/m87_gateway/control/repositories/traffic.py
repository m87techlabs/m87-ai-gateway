"""SQLite traffic repository; shares the local backend transaction boundary."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .base import SQLiteRepository, tighten_sqlite_files


class SQLiteTrafficRepository(SQLiteRepository):
    @staticmethod
    def migrate(connection):
        connection.execute("""CREATE TABLE IF NOT EXISTS exchange_content (
            request_id TEXT PRIMARY KEY REFERENCES events(request_id) ON DELETE CASCADE,
            created_at TEXT NOT NULL, request_content TEXT, response_content TEXT
        )""")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS exchange_content_created ON exchange_content(created_at)"
        )
        connection.execute("""INSERT OR IGNORE INTO exchange_content
            SELECT request_id, created_at, request_content, response_content FROM events
            WHERE request_content IS NOT NULL OR response_content IS NOT NULL""")
        connection.execute("""UPDATE events SET
            request_content_recorded = MAX(request_content_recorded, request_content IS NOT NULL),
            response_content_recorded = MAX(response_content_recorded, response_content IS NOT NULL),
            request_content = NULL, response_content = NULL
            WHERE request_content IS NOT NULL OR response_content IS NOT NULL""")

    def _content_cutoff(self):
        return (
            datetime.now(timezone.utc) - timedelta(days=self.config.content_retention_days)
        ).isoformat()

    @staticmethod
    def _decode(event):
        for field in ("request_content", "response_content"):
            value = event.get(field)
            if value is not None:
                try:
                    event[field] = json.loads(value)
                except json.JSONDecodeError:
                    pass
            if value is not None:
                partial = field == "response_content" and event.get("response_content_partial")
                truncated = event.get(f"{field}_truncated")
                status = (
                    "partial_truncated"
                    if partial and truncated
                    else "partial"
                    if partial
                    else "truncated"
                    if truncated
                    else "captured"
                )
            elif event.get(f"{field}_recorded"):
                status = "deleted" if event.get("content_deleted") else "expired"
            elif event.get("capture_enabled") == 0:
                status = "disabled"
            elif event.get("capture_enabled") is None:
                status = "unknown"
            else:
                status = "not_captured" if field == "request_content" else "not_produced"
            event[f"{field}_status"] = status
        return event

    def emit(self, event: dict[str, Any]) -> None:
        fields = (
            "request_id",
            "capture_enabled",
            "request_content_recorded",
            "response_content_recorded",
            "content_deleted",
            "streaming",
            "request_outcome",
            "http_status_code",
            "response_content_partial",
            "client_user_hash",
            "queue_wait_ms",
            "queue_outcome",
            "project_id",
            "created_at",
            "app_id",
            "provider",
            "model",
            "routed_model",
            "status_code",
            "latency_ms",
            "guardrail_action",
            "guardrail_reason",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "estimated_cost_usd",
            "error_type",
            "provider_attempted",
            "provider_attempts",
            "provider_retries",
            "cache_status",
            "request_content_truncated",
            "response_content_truncated",
        )
        defaults = {
            "provider_attempts": 0,
            "provider_retries": 0,
            "cache_status": "disabled",
            "streaming": False,
            "response_content_partial": False,
        }
        stored = {
            **event,
            "request_content_recorded": event.get("request_content") is not None,
            "response_content_recorded": event.get("response_content") is not None,
            "content_deleted": False,
        }
        values = [stored.get(name, defaults.get(name)) for name in fields]
        with self._connect() as connection:
            connection.execute(
                f"INSERT OR REPLACE INTO events ({','.join(fields)}) "
                f"VALUES ({','.join('?' for _ in fields)})",
                values,
            )
            if stored["request_content_recorded"] or stored["response_content_recorded"]:
                connection.execute(
                    "INSERT INTO exchange_content VALUES (?, ?, ?, ?)",
                    (
                        event["request_id"],
                        event["created_at"],
                        event.get("request_content"),
                        event.get("response_content"),
                    ),
                )
            self.backend.usage_repository.record(connection, event)
            self.backend.export_outbox.enqueue(connection, event)
        tighten_sqlite_files(self.database_path)
        self.prune_events()
        self.backend.usage_repository.prune_usage()

    def delete_events(self, project_id=None) -> int:
        with self._connect() as connection:
            if project_id is None:
                cursor = connection.execute("DELETE FROM events")
            else:
                cursor = connection.execute(
                    "DELETE FROM events WHERE project_id = ?", (project_id,)
                )
            self.backend.management_audit.record(connection, "logs.deleted", project_id)
        return cursor.rowcount

    def delete_content(self, project_id=None) -> int:
        with self._connect() as connection:
            where = (
                "WHERE request_id IN (SELECT request_id FROM events WHERE project_id = ?)"
                if project_id is not None
                else ""
            )
            values = (project_id,) if project_id is not None else ()
            connection.execute(
                "UPDATE events SET content_deleted = 1 WHERE request_id IN "
                f"(SELECT request_id FROM exchange_content {where})",
                values,
            )
            cursor = connection.execute(f"DELETE FROM exchange_content {where}", values)
            self.backend.management_audit.record(connection, "logs.content_deleted", project_id)
        return cursor.rowcount

    def prune_events(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.retention_days)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM exchange_content WHERE created_at < ?", (self._content_cutoff(),)
            )
            cursor = connection.execute(
                "DELETE FROM events WHERE created_at < ?", (cutoff.isoformat(),)
            )
        return cursor.rowcount

    def list_events(
        self,
        *,
        limit: int = 100,
        app_id: str | None = None,
        status: str | None = None,
        project_id: str | None = None,
        request_id: str | None = None,
        before: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if request_id:
            clauses.append("request_id = ?")
            values.append(request_id)
        if before:
            clauses.append("(created_at, request_id) < (?, ?)")
            values.extend(before)
        if project_id is not None:
            clauses.append("project_id = ?")
            values.append(project_id)
        if app_id:
            clauses.append("app_id = ?")
            values.append(app_id)
        if status == "error":
            clauses.append("status_code >= 400")
        elif status == "success":
            clauses.append("status_code < 400")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT request_id, created_at, project_id, app_id, provider, model, routed_model,
                           status_code, latency_ms, prompt_tokens, completion_tokens,
                           total_tokens, error_type, cache_status, provider_attempts,
                           provider_retries, streaming, request_outcome, http_status_code,
                           response_content_partial, queue_wait_ms, queue_outcome, client_user_hash,
                           capture_enabled, request_content_recorded, response_content_recorded,
                           request_content_truncated, response_content_truncated, content_deleted
                    FROM events {where} ORDER BY created_at DESC, request_id DESC LIMIT ?""",
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_event(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT e.*, c.request_content AS captured_request, c.response_content AS captured_response "
                "FROM events e LEFT JOIN exchange_content c ON c.request_id = e.request_id "
                "AND c.created_at >= ? WHERE e.request_id = ?",
                (self._content_cutoff(), request_id),
            ).fetchone()
        if row is None:
            return None
        event = dict(row)
        event["request_content"] = event.pop("captured_request")
        event["response_content"] = event.pop("captured_response")
        return self._decode(event)

    def export_events(
        self,
        limit: int = 1000,
        project_id: str | None = None,
        *,
        include_content=True,
        app_id=None,
        status=None,
        request_id=None,
    ) -> list[dict[str, Any]]:
        summaries = self.list_events(
            limit=limit, project_id=project_id, app_id=app_id, status=status, request_id=request_id
        )
        if not include_content:
            return summaries
        return [event for row in summaries if (event := self.get_event(row["request_id"]))]
