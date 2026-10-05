from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet

from m87_gateway.config import ControlPlaneConfig
from .facade import BackendFacade
from .repositories.base import tighten_sqlite_files as _tighten_sqlite_files
from .repositories.configuration import SQLiteConfigurationRepository
from .repositories.identities import SQLiteIdentityRepository
from .repositories.secrets import SQLiteSecretStore
from .repositories.traffic import SQLiteTrafficRepository
from .repositories.usage import SQLiteUsageRepository

from m87_gateway.private_storage import (
    prepare_file as _prepare_private_file,
)

SCHEMA_VERSION = 2


class LocalControlStore(BackendFacade):
    """SQLite-backed event and credential store for one gateway instance."""

    def __init__(self, config: ControlPlaneConfig):
        if config.backend_adapter != "sqlite":
            raise ValueError("LocalControlStore requires the sqlite backend adapter")
        self.config = config
        self.configuration = SQLiteConfigurationRepository(self)
        self.identities = SQLiteIdentityRepository(self)
        self.secrets = SQLiteSecretStore(self)
        self.traffic = SQLiteTrafficRepository(self)
        self.usage_repository = SQLiteUsageRepository(self)
        self.database_path = Path(config.database_path)
        self.master_key_path = Path(config.master_key_path)
        _prepare_private_file(self.database_path)
        key = _load_or_create_key(self.master_key_path)
        self._fernet = Fernet(key)
        self._digest_key = hashlib.sha256(key + b":application-key-digests").digest()
        self._initialize()
        controls = self.runtime_config().get("controls", {})
        self.config = ControlPlaneConfig.model_validate(
            {
                **config.model_dump(),
                "retention_days": controls.get("retention_days", config.retention_days),
            }
        )
        self.prune_events()
        self.usage_repository.prune_usage()

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
            previous_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if previous_version > SCHEMA_VERSION:
                raise ValueError("Database schema is newer than this gateway")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                BEGIN IMMEDIATE;
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
            self.usage_repository.migrate(connection, previous_version)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
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
                "max_concurrent_requests": "INTEGER",
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

    def check_storage(self):
        with self._connect() as connection:
            connection.execute("SELECT COUNT(*) FROM runtime_config").fetchone()


def _load_or_create_key(path: Path) -> bytes:
    existed = path.exists()
    _prepare_private_file(path)
    key = path.read_bytes().strip()
    if not existed:
        key = Fernet.generate_key()
        path.write_bytes(key)
    try:
        Fernet(key)
    except (ValueError, TypeError) as exc:
        raise ValueError("Master key is invalid") from exc
    return key
