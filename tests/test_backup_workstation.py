"""Backup safety, schema compatibility, and platform storage boundaries."""

from datetime import datetime, timezone
import os
import sqlite3
import subprocess

import pytest

from m87_gateway.backup import backup, restore
from m87_gateway.cli import local_settings, operator_key
from m87_gateway.control.store import LocalControlStore, SCHEMA_VERSION
from m87_gateway.private_storage import check_private, prepare_directory, prepare_file
from m87_gateway.workstation import instance_lock

PASSWORD = "synthetic-backup-password"


def fixture_data(path):
    admin = operator_key(path)
    store = LocalControlStore(local_settings(path).control_plane)
    _, app_key = store.create_app_key("test-app", ["auto"], False)
    store.put_provider_key("openai", "synthetic-provider-secret")
    store.emit(
        {
            "request_id": "backup-event",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status_code": 200,
            "provider_attempted": True,
            "request_content": '[{"content":"synthetic prompt"}]',
            "request_content_truncated": False,
            "response_content_truncated": False,
        }
    )
    store.save_runtime_config({"controls": {"retention_days": 90}})
    return store, app_key, admin


def test_encrypted_backup_roundtrip_preserves_identity_config_and_logs(tmp_path):
    original = tmp_path / "original"
    store, app_key, admin = fixture_data(original)
    archive = tmp_path / "backups" / "gateway.backup"
    with instance_lock(original):
        backup(original, archive, PASSWORD)
    contents = archive.read_bytes()
    for secret in (app_key, admin, "synthetic-provider-secret", "synthetic prompt"):
        assert secret.encode() not in contents
    check_private(archive)
    recovered = tmp_path / "recovered"
    with instance_lock(recovered):
        restore(recovered, archive, PASSWORD)
    restored = LocalControlStore(local_settings(recovered).control_plane)
    assert restored.authenticate_app_key(app_key).app_id == "test-app"
    assert restored.get_provider_key("openai") == "synthetic-provider-secret"
    assert restored.get_event("backup-event")["request_content"]
    assert restored.runtime_config() == store.runtime_config()
    assert restored.overview() == store.overview()
    assert operator_key(recovered) == admin


@pytest.mark.parametrize("mode", ["password", "tamper", "nonempty", "future"])
def test_restore_rejects_invalid_input_without_overwriting_data(tmp_path, mode):
    original = tmp_path / "original"
    fixture_data(original)
    archive = tmp_path / "backups" / "gateway.backup"
    backup(original, archive, PASSWORD)
    recovered = tmp_path / "recovered"
    password = PASSWORD
    if mode == "password":
        password = "wrong-password-long-enough"
    if mode == "tamper":
        data = bytearray(archive.read_bytes())
        data[-10] ^= 1
        archive.write_bytes(data)
    if mode == "future":
        from m87_gateway.backup import MAGIC, cipher
        import json

        data = archive.read_bytes()
        salt = data[len(MAGIC) : len(MAGIC) + 16]
        document = json.loads(cipher(PASSWORD, salt).decrypt(data[len(MAGIC) + 16 :]))
        document["schema_version"] = SCHEMA_VERSION + 1
        archive.write_bytes(
            MAGIC + salt + cipher(PASSWORD, salt).encrypt(json.dumps(document).encode())
        )
    with instance_lock(recovered):
        if mode == "nonempty":
            (recovered / "unrelated.txt").write_text("keep")
        with pytest.raises(ValueError):
            restore(recovered, archive, password)
        assert not (recovered / "control.db").exists()
        if mode == "nonempty":
            assert (recovered / "unrelated.txt").read_text() == "keep"


def test_backup_wont_overwrite_and_active_directory_is_exclusive(tmp_path):
    original = tmp_path / "original"
    fixture_data(original)
    archive = tmp_path / "backups" / "gateway.backup"
    backup(original, archive, PASSWORD)
    previous = archive.read_bytes()
    with pytest.raises(ValueError):
        backup(original, archive, PASSWORD)
    assert archive.read_bytes() == previous
    with instance_lock(original):
        with pytest.raises(ValueError, match="in use"):
            with instance_lock(original):
                pytest.fail("Exclusive lock bypassed")


def test_future_schema_fails_before_migration(tmp_path):
    directory = tmp_path / "data"
    fixture_data(directory)
    with sqlite3.connect(directory / "control.db") as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(ValueError, match="newer"):
        LocalControlStore(local_settings(directory).control_plane)
    with sqlite3.connect(directory / "control.db") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION + 1


def test_private_storage_rejects_broad_access(tmp_path):
    directory = tmp_path / "private"
    prepare_directory(directory)
    path = directory / "key"
    prepare_file(path)
    check_private(path)
    if os.name == "nt":
        subprocess.run(
            ["icacls", str(path), "/grant", "*S-1-1-0:(R)"], check=True, capture_output=True
        )
    else:
        path.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        check_private(path)


def test_private_storage_rejects_symlink(tmp_path):
    if os.name == "nt":
        pytest.skip("Symlink creation needs Windows developer privileges")
    target = tmp_path / "target"
    target.write_text("keep")
    link = tmp_path / "private"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        prepare_file(link)
    assert target.read_text() == "keep"


def test_lifecycle_identity_probe_never_sends_key_to_foreign_listener(tmp_path, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import json
    from m87_gateway.workstation import manage

    seen = []

    class Foreign(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            body = json.dumps({"instance_id": "b" * 32}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            pytest.fail("Foreign service must never receive a shutdown")

    directory = tmp_path / "data"
    prepare_directory(directory)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Foreign)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        marker = directory / "instance.json"
        prepare_file(marker)
        marker.write_text(json.dumps({"port": server.server_port, "instance_id": "a" * 32}))
        monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-operator-secret")
        assert not manage(directory, stop=True)
        assert seen == [None]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_shutdown_requires_admin_and_matching_instance(tmp_path, monkeypatch):
    import asyncio
    import httpx
    from m87_gateway.main import create_app

    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-operator-secret-long-enough")
    app = create_app(local_settings(tmp_path / "data"))
    calls = []
    app.state.instance_id = "a" * 32
    app.state.shutdown = lambda: calls.append(True)

    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client:
                assert (
                    await client.post("/admin/api/shutdown", json={"instance_id": "a" * 32})
                ).status_code == 401
                client.headers["Authorization"] = "Bearer synthetic-operator-secret-long-enough"
                assert (
                    await client.post("/admin/api/shutdown", json={"instance_id": "b" * 32})
                ).status_code == 409
                assert not calls
                assert (
                    await client.post("/admin/api/shutdown", json={"instance_id": "a" * 32})
                ).status_code == 204
                assert calls == [True]

    asyncio.run(scenario())


def test_empty_existing_master_key_fails_without_regeneration(tmp_path):
    directory = tmp_path / "data"
    fixture_data(directory)
    master = directory / "master.key"
    master.write_bytes(b"")
    with pytest.raises(ValueError, match="invalid"):
        LocalControlStore(local_settings(directory).control_plane)
    assert master.read_bytes() == b""
