"""SQLite secrets repository; shares the local backend transaction boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import InvalidToken

from .base import SQLiteRepository


class SQLiteSecretStore(SQLiteRepository):
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
