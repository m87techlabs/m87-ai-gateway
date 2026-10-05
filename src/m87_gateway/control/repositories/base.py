"""Shared resources for SQLite repositories, without opening extra databases."""

from pathlib import Path
from typing import TYPE_CHECKING

from m87_gateway.private_storage import protect

if TYPE_CHECKING:
    from m87_gateway.control.store import LocalControlStore


class SQLiteRepository:
    def __init__(self, backend: "LocalControlStore"):
        self.backend = backend

    @property
    def config(self):
        return self.backend.config

    @property
    def database_path(self):
        return self.backend.database_path

    @property
    def _fernet(self):
        return self.backend._fernet

    @property
    def _digest_key(self):
        return self.backend._digest_key

    def _connect(self):
        return self.backend._connect()


def tighten_sqlite_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            protect(candidate)
