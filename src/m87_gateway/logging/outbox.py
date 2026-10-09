"""Bounded SQLite metadata delivery queue, independent of traffic retention."""

import hashlib
import json
import time
from typing import Protocol, runtime_checkable
from uuid import uuid4

from m87_gateway.control.repositories.base import SQLiteRepository

# An allowlist prevents new captured fields from silently entering remote deliveries.
EXPORT_FIELDS = (
    "request_id",
    "created_at",
    "project_id",
    "app_id",
    "provider",
    "model",
    "routed_model",
    "status_code",
    "http_status_code",
    "request_outcome",
    "streaming",
    "latency_ms",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "estimated_cost_usd",
    "error_type",
    "guardrail_action",
    "guardrail_reason",
    "provider_attempted",
    "provider_attempts",
    "provider_retries",
    "cache_status",
    "queue_wait_ms",
    "queue_outcome",
)


@runtime_checkable
class DeliveryOutbox(Protocol):
    """Optional backend contract; enqueue must share the traffic write transaction."""

    def configure(self, config, redact) -> None: ...
    def enqueue(self, transaction, event, *, now=None) -> None: ...
    def claim(self, *, now=None) -> dict | None: ...
    def complete(self, item, *, success: bool, now=None) -> None: ...
    def health(self) -> dict: ...


class SQLiteDeliveryOutbox(SQLiteRepository):
    config_export = None
    binding = None

    @staticmethod
    def migrate(connection):
        connection.execute("""CREATE TABLE IF NOT EXISTS log_outbox (
            delivery_id TEXT PRIMARY KEY, request_id TEXT NOT NULL,
            binding TEXT NOT NULL, payload TEXT NOT NULL,
            created_at REAL NOT NULL, expires_at REAL NOT NULL, next_at REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
            lease_token TEXT, UNIQUE(binding, request_id)
        )""")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS log_outbox_ready ON log_outbox(binding, next_at)"
        )
        connection.execute("""CREATE TABLE IF NOT EXISTS log_export_counters (
            id INTEGER PRIMARY KEY CHECK(id=1), delivered INTEGER NOT NULL DEFAULT 0,
            failed_attempts INTEGER NOT NULL DEFAULT 0, dropped INTEGER NOT NULL DEFAULT 0,
            expired INTEGER NOT NULL DEFAULT 0, last_success_at REAL, last_failure_at REAL
        )""")
        connection.execute("INSERT OR IGNORE INTO log_export_counters(id) VALUES (1)")

    def configure(self, config, redact):
        self.config_export = config
        self.binding = (
            hashlib.sha256(
                json.dumps([config.adapter, config.endpoint], separators=(",", ":")).encode()
            ).hexdigest()
            if config.enabled
            else None
        )
        self.redact = redact

    @staticmethod
    def _prune(connection, now):
        result = connection.execute("DELETE FROM log_outbox WHERE expires_at <= ?", (now,))
        connection.execute(
            "UPDATE log_export_counters SET expired = expired + ? WHERE id=1", (result.rowcount,)
        )

    def enqueue(self, connection, event, *, now=None):
        if not self.binding:
            return
        now = time.time() if now is None else now
        self._prune(connection, now)
        if connection.execute(
            "SELECT 1 FROM log_outbox WHERE binding=? AND request_id=?",
            (self.binding, event["request_id"]),
        ).fetchone():
            return
        metadata = {name: event.get(name) for name in EXPORT_FIELDS}
        payload = json.dumps(self.redact(metadata), ensure_ascii=True, separators=(",", ":"))
        count = connection.execute("SELECT COUNT(*) FROM log_outbox").fetchone()[0]
        if count >= self.config_export.max_pending or len(payload.encode()) > 16384:
            connection.execute("UPDATE log_export_counters SET dropped=dropped+1 WHERE id=1")
            return
        connection.execute(
            """INSERT INTO log_outbox
            (delivery_id, request_id, binding, payload, created_at, expires_at, next_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                uuid4().hex,
                event["request_id"],
                self.binding,
                payload,
                now,
                now + self.config_export.retention_hours * 3600,
                now,
            ),
        )

    def claim(self, *, now=None):
        if not self.binding:
            return None
        now = time.time() if now is None else now
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._prune(connection, now)
            row = connection.execute(
                """SELECT * FROM log_outbox
                WHERE binding=? AND next_at <= ? AND lease_until <= ?
                ORDER BY created_at, delivery_id LIMIT 1""",
                (self.binding, now, now),
            ).fetchone()
            if row is None:
                return None
            item = dict(row)
            item["lease_token"] = uuid4().hex
            item["attempts"] += 1
            # One total HTTP deadline, plus a grace period for transaction completion.
            connection.execute(
                """UPDATE log_outbox SET lease_token=?, lease_until=?, attempts=?
                WHERE delivery_id=?""",
                (
                    item["lease_token"],
                    now + self.config_export.timeout_seconds + 30,
                    item["attempts"],
                    item["delivery_id"],
                ),
            )
        return item

    def complete(self, item, *, success, now=None):
        now = time.time() if now is None else now
        with self._connect() as connection:
            match = (item["delivery_id"], item["lease_token"])
            if not connection.execute(
                "SELECT 1 FROM log_outbox WHERE delivery_id=? AND lease_token=?", match
            ).fetchone():
                return
            if success:
                connection.execute(
                    "DELETE FROM log_outbox WHERE delivery_id=? AND lease_token=?", match
                )
                connection.execute(
                    "UPDATE log_export_counters SET delivered=delivered+1, last_success_at=? WHERE id=1",
                    (now,),
                )
            else:
                delay = min(
                    self.config_export.max_retry_seconds,
                    self.config_export.retry_seconds * 2 ** min(item["attempts"] - 1, 20),
                )
                connection.execute(
                    "UPDATE log_outbox SET lease_token=NULL, lease_until=0, next_at=? WHERE delivery_id=? AND lease_token=?",
                    (now + delay, *match),
                )
                connection.execute(
                    "UPDATE log_export_counters SET failed_attempts=failed_attempts+1, last_failure_at=? WHERE id=1",
                    (now,),
                )

    def health(self):
        with self._connect() as connection:
            counters = dict(
                connection.execute("SELECT * FROM log_export_counters WHERE id=1").fetchone()
            )
            counters.pop("id")
            row = connection.execute(
                """SELECT COUNT(*) AS pending,
                COALESCE(SUM(binding IS NOT ?), 0) AS held_for_other_destination,
                COALESCE(SUM(expires_at <= ?), 0) AS awaiting_expiry,
                MIN(created_at) AS oldest_pending_at FROM log_outbox""",
                (self.binding, time.time()),
            ).fetchone()
        return {**counters, **dict(row)}
