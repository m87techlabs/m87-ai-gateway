from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from m87_gateway.config import AppConfig, ControlPlaneConfig


class LocalControlStore:
    """SQLite-backed event and credential store for one gateway instance."""

    def __init__(self, config: ControlPlaneConfig):
        self.config = config
        self.database_path = Path(config.database_path)
        self.master_key_path = Path(config.master_key_path)
        _prepare_private_file(self.database_path)
        key = _load_or_create_key(self.master_key_path)
        self._fernet = Fernet(key)
        self._digest_key = hashlib.sha256(key + b":application-key-digests").digest()
        self._initialize()
        self.prune_events()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    request_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    app_id TEXT, provider TEXT, model TEXT, routed_model TEXT,
                    status_code INTEGER NOT NULL, latency_ms REAL,
                    guardrail_action TEXT, guardrail_reason TEXT,
                    prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,
                    estimated_cost_usd REAL, error_type TEXT,
                    provider_attempted INTEGER NOT NULL DEFAULT 0,
                    provider_attempts INTEGER NOT NULL DEFAULT 0,
                    provider_retries INTEGER NOT NULL DEFAULT 0,
                    cache_status TEXT NOT NULL DEFAULT 'disabled',
                    request_content TEXT, request_content_truncated INTEGER NOT NULL DEFAULT 0,
                    response_content TEXT, response_content_truncated INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS events_created_at ON events(created_at DESC);
                CREATE INDEX IF NOT EXISTS events_app_id ON events(app_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS app_keys (
                    app_id TEXT PRIMARY KEY, key_digest TEXT NOT NULL UNIQUE,
                    key_prefix TEXT NOT NULL, allowed_models TEXT NOT NULL,
                    capture_content INTEGER NOT NULL DEFAULT 0,
                    rate_limit_per_minute INTEGER,
                    enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provider_keys (
                    provider TEXT NOT NULL, alias TEXT NOT NULL,
                    encrypted_value BLOB NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, last_used_at TEXT,
                    PRIMARY KEY(provider, alias)
                );
                """
            )
            self._ensure_columns(connection)
        _tighten_sqlite_files(self.database_path)

    @staticmethod
    def _ensure_columns(connection: sqlite3.Connection) -> None:
        migrations = {
            "events": {
                "provider_attempts": "INTEGER NOT NULL DEFAULT 0",
                "provider_retries": "INTEGER NOT NULL DEFAULT 0",
                "cache_status": "TEXT NOT NULL DEFAULT 'disabled'",
            },
            "app_keys": {"rate_limit_per_minute": "INTEGER"},
        }
        for table, additions in migrations.items():
            existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            for name, definition in additions.items():
                if name not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def close(self) -> None:
        return None

    def emit(self, event: dict[str, Any]) -> None:
        fields = (
            "request_id",
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
        defaults = {"provider_attempts": 0, "provider_retries": 0, "cache_status": "disabled"}
        values = [event.get(name, defaults.get(name)) for name in fields]
        with self._connect() as connection:
            connection.execute(
                f"INSERT OR REPLACE INTO events ({','.join(fields)}) "
                f"VALUES ({','.join('?' for _ in fields)})",
                values,
            )
        _tighten_sqlite_files(self.database_path)

    def prune_events(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.retention_days)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM events WHERE created_at < ?", (cutoff.isoformat(),)
            )
        return cursor.rowcount

    def overview(self, hours: int = 24) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        with self._connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS requests,
                          COALESCE(SUM(CASE WHEN cache_status != 'hit' THEN prompt_tokens END), 0) AS prompt_tokens,
                          COALESCE(SUM(CASE WHEN cache_status != 'hit' THEN completion_tokens END), 0) AS completion_tokens,
                          COALESCE(SUM(CASE WHEN cache_status != 'hit' THEN total_tokens END), 0) AS total_tokens,
                          COALESCE(SUM(CASE WHEN cache_status = 'hit' THEN 1 ELSE 0 END), 0) AS cache_hits,
                          COALESCE(SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END), 0) AS errors,
                          COALESCE(AVG(latency_ms), 0) AS average_latency_ms
                   FROM events WHERE created_at >= ?""",
                (cutoff.isoformat(),),
            ).fetchone()
        result = dict(row)
        result["hours"] = hours
        result["average_latency_ms"] = round(result["average_latency_ms"], 2)
        return result

    def list_events(
        self, *, limit: int = 100, app_id: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
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
                f"""SELECT request_id, created_at, app_id, provider, model, routed_model,
                           status_code, latency_ms, prompt_tokens, completion_tokens,
                           total_tokens, error_type, cache_status, provider_attempts,
                           provider_retries
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

    def export_events(self, limit: int = 1000) -> list[dict[str, Any]]:
        summaries = self.list_events(limit=limit)
        return [event for row in summaries if (event := self.get_event(row["request_id"]))]

    def _digest(self, value: str) -> str:
        return hmac.new(self._digest_key, value.encode(), hashlib.sha256).hexdigest()

    def create_app_key(
        self,
        app_id: str,
        allowed_models: list[str],
        capture_content: bool,
        rate_limit_per_minute: int | None = None,
    ) -> tuple[dict[str, Any], str]:
        raw_key = f"m87_{secrets.token_urlsafe(32)}"
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO app_keys
                   (app_id, key_digest, key_prefix, allowed_models, capture_content,
                    rate_limit_per_minute, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    app_id,
                    self._digest(raw_key),
                    raw_key[:12],
                    json.dumps(allowed_models),
                    capture_content,
                    rate_limit_per_minute,
                    created_at,
                ),
            )
        return (
            {
                "app_id": app_id,
                "key_prefix": raw_key[:12],
                "allowed_models": allowed_models,
                "capture_content": capture_content,
                "rate_limit_per_minute": rate_limit_per_minute,
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
            api_key=raw_key,
            allowed_models=json.loads(row["allowed_models"]),
            capture_content=bool(row["capture_content"]),
            rate_limit_per_minute=row["rate_limit_per_minute"],
        )

    def list_apps(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT app_id, key_prefix, allowed_models, capture_content,
                          rate_limit_per_minute, enabled, created_at
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

    def delete_app(self, app_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM app_keys WHERE app_id = ?", (app_id,))
        return cursor.rowcount > 0

    def put_provider_key(self, provider: str, value: str, alias: str = "default") -> None:
        now = datetime.now(timezone.utc).isoformat()
        encrypted = self._fernet.encrypt(value.encode())
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO provider_keys
                   (provider, alias, encrypted_value, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(provider, alias) DO UPDATE SET
                     encrypted_value = excluded.encrypted_value,
                     updated_at = excluded.updated_at""",
                (provider, alias, encrypted, now, now),
            )

    def get_provider_key(self, provider: str, alias: str = "default") -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT encrypted_value FROM provider_keys WHERE provider = ? AND alias = ?",
                (provider, alias),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE provider_keys SET last_used_at = ? WHERE provider = ? AND alias = ?",
                (datetime.now(timezone.utc).isoformat(), provider, alias),
            )
        try:
            return self._fernet.decrypt(row["encrypted_value"]).decode()
        except InvalidToken as exc:
            raise ValueError("Stored provider key cannot be decrypted") from exc

    def provider_secret_values(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT encrypted_value FROM provider_keys").fetchall()
        values = []
        for row in rows:
            try:
                values.append(self._fernet.decrypt(row["encrypted_value"]).decode())
            except InvalidToken:
                continue
        return values

    def list_provider_keys(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT provider, alias, created_at, updated_at, last_used_at
                   FROM provider_keys ORDER BY provider, alias"""
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_provider_key(self, provider: str, alias: str = "default") -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM provider_keys WHERE provider = ? AND alias = ?", (provider, alias)
            )
        return cursor.rowcount > 0


def _prepare_private_directory(path: Path) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise ValueError(f"Private storage directory is unsafe: {path}")
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError(f"Private storage directory must be owner-only: {path}")
        return
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)


def _prepare_private_file(path: Path) -> None:
    _prepare_private_directory(path.parent)
    if path.is_symlink():
        raise ValueError(f"Private storage file cannot be a symlink: {path}")
    if path.exists():
        if not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError(f"Private storage file must be owner-only: {path}")
        return
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)


def _load_or_create_key(path: Path) -> bytes:
    _prepare_private_directory(path.parent)
    if path.is_symlink():
        raise ValueError(f"Master key cannot be a symlink: {path}")
    if not path.exists():
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, Fernet.generate_key())
        finally:
            os.close(descriptor)
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("Master key must have owner-only permissions")
    key = path.read_bytes().strip()
    try:
        Fernet(key)
    except (ValueError, TypeError) as exc:
        raise ValueError("Master key is invalid") from exc
    return key


def _tighten_sqlite_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            candidate.chmod(0o600)
