"""SQLite configuration repository; shares the local backend transaction boundary."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .base import SQLiteRepository, tighten_sqlite_files


class SQLiteConfigurationRepository(SQLiteRepository):
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
        tighten_sqlite_files(self.database_path)
