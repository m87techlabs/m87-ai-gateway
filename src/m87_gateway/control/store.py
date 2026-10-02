from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import stat
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
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

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

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
                CREATE TABLE IF NOT EXISTS runtime_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1), value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_columns(connection)
            connection.execute(
                "INSERT OR IGNORE INTO projects VALUES ('default', 'Default project', ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )
        _tighten_sqlite_files(self.database_path)

    @staticmethod
    def _ensure_columns(connection: sqlite3.Connection) -> None:
        migrations = {
            "events": {
                "provider_attempts": "INTEGER NOT NULL DEFAULT 0",
                "provider_retries": "INTEGER NOT NULL DEFAULT 0",
                "cache_status": "TEXT NOT NULL DEFAULT 'disabled'",
                "project_id": "TEXT",
            },
            "app_keys": {
                "rate_limit_per_minute": "INTEGER",
                "project_id": "TEXT NOT NULL DEFAULT 'default'",
            },
        }
        for table, additions in migrations.items():
            existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            for name, definition in additions.items():
                if name not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                    if table == "events" and name == "project_id":
                        connection.execute(
                            "UPDATE events SET project_id = 'default' WHERE app_id IS NOT NULL"
                        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS events_project_created ON events(project_id, created_at DESC)"
        )

    def close(self) -> None:
        return None

    def runtime_config(self) -> dict:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM runtime_config WHERE id = 1").fetchone()
        return json.loads(row["value"]) if row else {}

    def save_runtime_config(self, value: dict, provider=None, key=None, clear_key=False):
        """Persist configuration and a connection credential in one transaction."""
        with self._connect() as connection:
            if provider and clear_key:
                connection.execute("DELETE FROM provider_keys WHERE provider = ?", (provider,))
            if provider and key:
                now = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    "INSERT INTO provider_keys(provider, alias, encrypted_value, created_at, "
                    "updated_at) VALUES (?, 'default', ?, ?, ?) ON CONFLICT(provider, alias) "
                    "DO UPDATE SET encrypted_value=excluded.encrypted_value, "
                    "updated_at=excluded.updated_at, last_used_at=NULL",
                    (provider, self._fernet.encrypt(key.encode()), now, now),
                )
            connection.execute(
                "INSERT INTO runtime_config(id, value) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                (json.dumps(value),),
            )
        _tighten_sqlite_files(self.database_path)

    def emit(self, event: dict[str, Any]) -> None:
        fields = (
            "request_id",
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
                   FROM events WHERE {where}""",
                values,
            ).fetchone()
        result = dict(row)
        result["hours"] = hours
        result["average_latency_ms"] = round(result["average_latency_ms"], 2)
        return result

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

    def export_events(
        self, limit: int = 1000, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        summaries = self.list_events(limit=limit, project_id=project_id)
        return [event for row in summaries if (event := self.get_event(row["request_id"]))]

    def _digest(self, value: str) -> str:
        return hmac.new(self._digest_key, value.encode(), hashlib.sha256).hexdigest()

    def create_app_key(
        self,
        app_id: str,
        allowed_models: list[str],
        capture_content: bool,
        rate_limit_per_minute: int | None = None,
        project_id: str = "default",
    ) -> tuple[dict[str, Any], str]:
        raw_key = f"m87_{secrets.token_urlsafe(32)}"
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            self._require_project(connection, project_id)
            connection.execute(
                """INSERT INTO app_keys
                   (app_id, key_digest, key_prefix, allowed_models, capture_content,
                    rate_limit_per_minute, created_at, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    app_id,
                    self._digest(raw_key),
                    raw_key[:12],
                    json.dumps(allowed_models),
                    capture_content,
                    rate_limit_per_minute,
                    created_at,
                    project_id,
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
        )

    def list_apps(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT app_id, project_id, key_prefix, allowed_models, capture_content,
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

    def usage(self, hours: int = 24, project_id: str | None = None) -> dict:
        """Retained event aggregates; cached responses do not add provider token usage."""
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
                {aggregate} FROM events WHERE {where} GROUP BY bucket ORDER BY bucket""",
                values,
            ).fetchall()
            by_app = connection.execute(
                f"""SELECT app_id, {aggregate} FROM events WHERE {where}
                GROUP BY app_id ORDER BY total_tokens DESC, app_id LIMIT 100""",
                values,
            ).fetchall()
            by_model = connection.execute(
                f"""SELECT routed_model AS model, {aggregate} FROM events
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
