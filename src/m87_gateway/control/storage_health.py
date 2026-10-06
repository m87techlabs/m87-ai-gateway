"""Safe operator diagnostics; integrity/write probes are explicit and reversible."""

import hashlib
import secrets
import shutil
import sqlite3
from pathlib import Path

from m87_gateway.private_storage import check_private


def sqlite_storage_health(backend, *, verify=False):
    checks = []
    sizes = {}

    def run(name, operation, message):
        try:
            operation()
        except Exception as exc:
            code = "storage_unavailable"
            if isinstance(exc, sqlite3.OperationalError) and getattr(
                exc, "sqlite_errorcode", None
            ) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                code = "storage_busy"
            checks.append({"name": name, "ok": False, "code": code, "message": message})
        else:
            checks.append({"name": name, "ok": True, "code": "ok", "message": "OK"})

    def private_files():
        for path in (
            backend.database_path,
            backend.master_key_path,
            Path(f"{backend.database_path}-wal"),
            Path(f"{backend.database_path}-shm"),
        ):
            if path.exists():
                check_private(path)
        # Missing database/key must fail rather than create an empty replacement.
        backend.database_path.stat()
        backend.master_key_path.stat()

    def key_health():
        key = backend.master_key_path.read_bytes().strip()
        if not secrets.compare_digest(
            hashlib.sha256(key + b":application-key-digests").digest(), backend._digest_key
        ):
            raise ValueError("Key changed")
        with backend._connect() as connection:
            for row in connection.execute("SELECT encrypted_value FROM provider_keys"):
                backend._fernet.decrypt(row[0])

    def metadata():
        backend.check_storage()
        with backend._connect() as connection:
            sizes["schema_version"] = connection.execute("PRAGMA user_version").fetchone()[0]
            sizes["journal_mode"] = connection.execute("PRAGMA journal_mode").fetchone()[0]
        sizes["database_bytes"] = backend.database_path.stat().st_size
        wal = Path(f"{backend.database_path}-wal")
        sizes["wal_bytes"] = wal.stat().st_size if wal.exists() else 0
        sizes["free_disk_bytes"] = shutil.disk_usage(backend.database_path.parent).free

    def integrity():
        with backend._connect() as connection:
            if [row[0] for row in connection.execute("PRAGMA quick_check")] != ["ok"]:
                raise ValueError("Integrity failure")
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Foreign key failure")
            for row in connection.execute("SELECT encrypted_snapshot FROM configuration_revisions"):
                backend._fernet.decrypt(row[0])

    def writable():
        with backend._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO storage_probe(id) VALUES (1)")
            connection.rollback()

    run(
        "Private files",
        private_files,
        "Check owner-only database, key and SQLite sidecar permissions. Do not replace the key.",
    )
    if checks[-1]["ok"]:
        run(
            "Database access",
            metadata,
            "Check the database location, available disk space and competing writers.",
        )
        run(
            "Credential encryption",
            key_health,
            "Restore the matching database and key from an encrypted backup. Do not create a replacement key.",
        )
        if verify:
            run(
                "Database integrity",
                integrity,
                "Stop the gateway, take a backup and restore a known-good snapshot into a fresh directory.",
            )
            run(
                "Database write",
                writable,
                "Check free disk space, filesystem permissions and competing writers; retry when available.",
            )
    return {
        "backend": "sqlite",
        "ok": all(item["ok"] for item in checks),
        "verified": bool(verify),
        "checks": checks,
        **sizes,
        "warnings": ["Less than 10 MiB of disk space remains."]
        if sizes.get("free_disk_bytes", 10 * 1024 * 1024) < 10 * 1024 * 1024
        else [],
        "scope": "Local storage only. Integrity and reversible write probes run only on explicit verification.",
    }
