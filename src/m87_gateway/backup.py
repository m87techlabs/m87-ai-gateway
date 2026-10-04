"""Encrypted, versioned backups restored only into an unused data directory."""

import base64
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from m87_gateway import __version__
from m87_gateway.control.store import SCHEMA_VERSION
from m87_gateway.private_storage import check_private, prepare_directory, prepare_file

MAGIC = b"M87BACKUP\x01"
MAX_BYTES = 256 * 1024 * 1024


def cipher(password: str, salt: bytes) -> Fernet:
    if len(password) < 12:
        raise ValueError("Backup password must contain at least 12 characters")
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000).derive(
        password.encode()
    )
    return Fernet(base64.urlsafe_b64encode(key))


def validate_database(path: Path, master: bytes):
    decoder = Fernet(master.strip())
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Backup database is invalid")
        if connection.execute("PRAGMA user_version").fetchone()[0] > SCHEMA_VERSION:
            raise ValueError("Backup requires a newer gateway version")
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not {"events", "projects", "app_keys", "provider_keys", "runtime_config"} <= tables:
            raise ValueError("Backup database is incomplete")
        for row in connection.execute("SELECT encrypted_value FROM provider_keys"):
            decoder.decrypt(row[0])
        # Configuration must be valid before installing the backup.
        from m87_gateway.cli import local_settings
        from m87_gateway.control.setup import apply_overrides

        row = connection.execute("SELECT value FROM runtime_config WHERE id = 1").fetchone()
        apply_overrides(local_settings(path.parent), json.loads(row[0]) if row else {})


def backup(data_dir: Path, output: Path, password: str):
    if output.exists() or output.is_symlink():
        raise ValueError("Backup output already exists")
    for name in ("control.db", "master.key", "admin.key"):
        check_private(data_dir / name)
    prepare_directory(output.parent)
    with tempfile.TemporaryDirectory(prefix="snapshot-", dir=data_dir) as temporary:
        snapshot = Path(temporary) / "control.db"
        prepare_file(snapshot)
        with sqlite3.connect((data_dir / "control.db").as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(snapshot) as destination:
                source.backup(destination)
        master = (data_dir / "master.key").read_bytes()
        validate_database(snapshot, master)
        if snapshot.stat().st_size > MAX_BYTES // 2:
            raise ValueError("Local backup exceeds the supported size limit")
        document = {
            "format": 1,
            "gateway_version": __version__,
            "schema_version": SCHEMA_VERSION,
            "database": base64.b64encode(snapshot.read_bytes()).decode(),
            "master_key": master.decode(),
            "admin_key": (data_dir / "admin.key").read_text().strip(),
        }
        salt = os.urandom(16)
        encoded = MAGIC + salt + cipher(password, salt).encrypt(json.dumps(document).encode())
        if len(encoded) > MAX_BYTES:
            raise ValueError("Local backup exceeds the supported size limit")
        # Create exclusively, protect the empty file before writing sensitive ciphertext.
        descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            prepare_file(output)
            output.write_bytes(encoded)
        except Exception:
            output.unlink(missing_ok=True)
            raise


def restore(data_dir: Path, source: Path, password: str):
    if any(item.name != "instance.lock" for item in data_dir.iterdir()):
        raise ValueError("Restore needs a fresh, empty data directory")
    if source.stat().st_size > MAX_BYTES or source.is_symlink():
        raise ValueError("Backup input is invalid or too large")
    encoded = source.read_bytes()
    if not encoded.startswith(MAGIC) or len(encoded) < len(MAGIC) + 16:
        raise ValueError("Unsupported backup format")
    salt = encoded[len(MAGIC) : len(MAGIC) + 16]
    try:
        document = json.loads(cipher(password, salt).decrypt(encoded[len(MAGIC) + 16 :]))
        if document["format"] != 1 or document["schema_version"] > SCHEMA_VERSION:
            raise ValueError("Unsupported backup schema")
        database = base64.b64decode(document["database"], validate=True)
        master = document["master_key"].encode()
        admin = document["admin_key"]
        if not isinstance(admin, str) or len(admin) < 24 or any(c.isspace() for c in admin):
            raise ValueError("Invalid operator key")
        with tempfile.TemporaryDirectory(prefix="restore-", dir=data_dir) as temporary:
            directory = Path(temporary)
            path = directory / "control.db"
            prepare_file(path)
            path.write_bytes(database)
            validate_database(path, master)
            created = []
            try:
                for name, value in (
                    ("control.db", database),
                    ("master.key", master),
                    ("admin.key", (admin + "\n").encode()),
                ):
                    target = data_dir / name
                    prepare_file(target)
                    created.append(target)
                    target.write_bytes(value)
            except Exception:
                for target in created:
                    target.unlink(missing_ok=True)
                raise
    except (InvalidToken, ValueError, KeyError, TypeError, UnicodeError, sqlite3.Error):
        raise ValueError("Backup password, contents or compatibility check failed") from None
