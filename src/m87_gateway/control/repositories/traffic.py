"""SQLite traffic repository; shares the local backend transaction boundary."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .base import SQLiteRepository, tighten_sqlite_files


class SQLiteTrafficRepository(SQLiteRepository):
    def emit(self, event: dict[str, Any]) -> None:
        fields = (
            "request_id",
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
            "request_content",
            "request_content_truncated",
            "response_content",
            "response_content_truncated",
        )
        defaults = {
            "provider_attempts": 0,
            "provider_retries": 0,
            "cache_status": "disabled",
            "streaming": False,
            "response_content_partial": False,
        }
        values = [event.get(name, defaults.get(name)) for name in fields]
        with self._connect() as connection:
            connection.execute(
                f"INSERT OR REPLACE INTO events ({','.join(fields)}) "
                f"VALUES ({','.join('?' for _ in fields)})",
                values,
            )
            self.backend.usage_repository.record(connection, event)
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
        return cursor.rowcount

    def prune_events(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.retention_days)
        with self._connect() as connection:
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
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
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
                           response_content_partial, queue_wait_ms, queue_outcome, client_user_hash
                    FROM events {where} ORDER BY created_at DESC LIMIT ?""",
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_event(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM events WHERE request_id = ?", (request_id,)
            ).fetchone()
        if row is None:
            return None
        event = dict(row)
        for name in ("request_content", "response_content"):
            if event[name] is not None:
                try:
                    event[name] = json.loads(event[name])
                except json.JSONDecodeError:
                    pass
        return event

    def export_events(
        self, limit: int = 1000, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        summaries = self.list_events(limit=limit, project_id=project_id)
        return [event for row in summaries if (event := self.get_event(row["request_id"]))]
