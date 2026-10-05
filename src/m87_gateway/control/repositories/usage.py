"""SQLite usage repository; shares the local backend transaction boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import sqlite3

from .base import SQLiteRepository


class SQLiteUsageRepository(SQLiteRepository):
    def overview(self, hours: int = 24, project_id: str | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)
        where = "created_at >= ? AND created_at <= ?"
        values = [cutoff.isoformat(), now.isoformat()]
        if project_id is not None:
            where += " AND project_id = ?"
            values.append(project_id)
        with self._connect() as connection:
            row = connection.execute(
                f"""SELECT COUNT(*) AS requests,
                          COALESCE(SUM(CASE WHEN cache_status != 'hit' THEN prompt_tokens END), 0) AS prompt_tokens,
                          COALESCE(SUM(CASE WHEN cache_status != 'hit' THEN completion_tokens END), 0) AS completion_tokens,
                          COALESCE(SUM(CASE WHEN cache_status != 'hit' THEN total_tokens END), 0) AS total_tokens,
                          COALESCE(SUM(CASE WHEN cache_status = 'hit' THEN 1 ELSE 0 END), 0) AS cache_hits,
                          COALESCE(SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END), 0) AS errors,
                          COALESCE(SUM(CASE WHEN provider_attempted = 1 AND total_tokens IS NULL
                            AND cache_status != 'hit' THEN 1 ELSE 0 END), 0) AS usage_unknown,
                          COALESCE(AVG(latency_ms), 0) AS average_latency_ms
                   FROM usage_records WHERE {where}""",
                values,
            ).fetchone()
        result = dict(row)
        result["hours"] = hours
        result["average_latency_ms"] = round(result["average_latency_ms"], 2)
        return result

    def usage(self, hours: int = 24, project_id: str | None = None) -> dict:
        """Independent usage aggregates; cached responses do not add provider token usage."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)
        where = "created_at >= ? AND created_at <= ?"
        values = [cutoff.isoformat(), now.isoformat()]
        if project_id is not None:
            where += " AND project_id = ?"
            values.append(project_id)
        aggregate = """COUNT(*) AS requests,
            COALESCE(SUM(CASE WHEN cache_status != 'hit' THEN prompt_tokens END), 0) AS prompt_tokens,
            COALESCE(SUM(CASE WHEN cache_status != 'hit' THEN completion_tokens END), 0) AS completion_tokens,
            COALESCE(SUM(CASE WHEN cache_status != 'hit' THEN total_tokens END), 0) AS total_tokens,
            SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS errors,
            SUM(CASE WHEN cache_status = 'hit' THEN 1 ELSE 0 END) AS cache_hits"""
        with self._connect() as connection:
            series = connection.execute(
                f"""SELECT strftime('%Y-%m-%dT%H:00:00Z', created_at) AS bucket,
                {aggregate} FROM usage_records WHERE {where} GROUP BY bucket ORDER BY bucket""",
                values,
            ).fetchall()
            by_app = connection.execute(
                f"""SELECT app_id, {aggregate} FROM usage_records WHERE {where}
                GROUP BY app_id ORDER BY total_tokens DESC, app_id LIMIT 100""",
                values,
            ).fetchall()
            by_model = connection.execute(
                f"""SELECT routed_model AS model, {aggregate} FROM usage_records
                WHERE {where} GROUP BY routed_model ORDER BY total_tokens DESC, routed_model
                LIMIT 100""",
                values,
            ).fetchall()
        buckets = {row["bucket"]: dict(row) for row in series}
        # Include the partial first/current UTC hours; the window itself is exact.
        start = cutoff.replace(minute=0, second=0, microsecond=0)
        timeline = []
        while start <= now:
            bucket = start.strftime("%Y-%m-%dT%H:00:00Z")
            timeline.append(
                buckets.get(
                    bucket,
                    {
                        "bucket": bucket,
                        "requests": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "errors": 0,
                        "cache_hits": 0,
                    },
                )
            )
            start += timedelta(hours=1)
        return {
            "hours": hours,
            "project_id": project_id,
            "series": timeline,
            "by_app": [dict(row) for row in by_app],
            "by_model": [dict(row) for row in by_model],
        }

    @staticmethod
    def migrate(connection: sqlite3.Connection, previous_version: int) -> None:
        connection.execute("""CREATE TABLE IF NOT EXISTS usage_records (
            request_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
            project_id TEXT, app_id TEXT, provider TEXT, model TEXT, routed_model TEXT,
            status_code INTEGER NOT NULL, latency_ms REAL,
            prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,
            provider_attempted INTEGER NOT NULL DEFAULT 0,
            provider_attempts INTEGER NOT NULL DEFAULT 0,
            provider_retries INTEGER NOT NULL DEFAULT 0,
            cache_status TEXT NOT NULL DEFAULT 'disabled'
        )""")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS usage_created ON usage_records(created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS usage_project_created "
            "ON usage_records(project_id, created_at DESC)"
        )
        if previous_version < 2:
            fields = ",".join(USAGE_FIELDS)
            connection.execute(
                f"INSERT OR IGNORE INTO usage_records ({fields}) SELECT {fields} FROM events"
            )

    @staticmethod
    def record(connection: sqlite3.Connection, event: dict[str, Any]) -> None:
        """First write wins for a request ID; duplicate delivery never adds usage."""
        defaults = {"provider_attempts": 0, "provider_retries": 0, "cache_status": "disabled"}
        connection.execute(
            f"INSERT OR IGNORE INTO usage_records ({','.join(USAGE_FIELDS)}) "
            f"VALUES ({','.join('?' for _ in USAGE_FIELDS)})",
            [event.get(name, defaults.get(name)) for name in USAGE_FIELDS],
        )

    def prune_usage(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.usage_retention_days)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM usage_records WHERE created_at < ?", (cutoff.isoformat(),)
            )
        return cursor.rowcount


USAGE_FIELDS = (
    "request_id",
    "created_at",
    "project_id",
    "app_id",
    "provider",
    "model",
    "routed_model",
    "status_code",
    "latency_ms",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "provider_attempted",
    "provider_attempts",
    "provider_retries",
    "cache_status",
)
