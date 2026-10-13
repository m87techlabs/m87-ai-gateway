"""Console export management: bound encrypted secrets, draft tests and live activation."""

import json
import sqlite3
import threading
import time
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from cryptography.fernet import InvalidToken

from backend_contracts import exchange
from examples.log_receiver.start import make_server
from m87_gateway.cli import local_settings
from m87_gateway.control import LocalControlStore
from m87_gateway.logging.outbox import destination_binding
from m87_gateway.main import create_app
from m87_gateway.backup import backup, restore, validate_database
from m87_gateway.config.settings import LogExportConfig
from m87_gateway.private_storage import prepare_file
from m87_gateway.workstation import instance_lock

ADMIN = {"Authorization": "Bearer synthetic-admin-key-long-enough"}
TOKEN = "synthetic-receiver-token"


@contextmanager
def collector(path, token=TOKEN):
    server = make_server(path, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}/events"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-admin-key-long-enough")
    key_file = tmp_path / "gateway/admin.key"
    prepare_file(key_file)
    key_file.write_text("synthetic-admin-key-long-enough")
    return local_settings(tmp_path / "gateway")


def config(client, endpoint=None):
    value = client.get("/admin/api/log-export", headers=ADMIN).json()["config"]
    value.update(
        enabled=True,
        use_stored_key=True,
        endpoint=endpoint or value["endpoint"],
        api_key_env=None,
        poll_seconds=0.1,
        retry_seconds=0.1,
    )
    return value


def save(client, value, key=None, **options):
    etag = client.get("/admin/api/log-export", headers=ADMIN).headers["etag"]
    return client.put(
        "/admin/api/log-export",
        headers={**ADMIN, "If-Match": etag},
        json={"config": value, **({"key": key} if key is not None else {}), **options},
    )


def wait(operation):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if operation():
            return
        time.sleep(0.02)
    pytest.fail("Export operation did not complete")


def received(server):
    with sqlite3.connect(server.database) as db:
        return [json.loads(row[0]) for row in db.execute("SELECT payload FROM deliveries")]


def test_saved_encrypted_key_live_disable_enable_restart_and_backup(settings, tmp_path):
    with collector(tmp_path / "receiver.db") as (server, endpoint):
        with TestClient(create_app(settings)) as client:
            value = config(client, endpoint)
            assert save(client, value, TOKEN).status_code == 204
            store = client.app.state.control_store
            report = client.get("/admin/api/log-export", headers=ADMIN).json()
            assert report["has_stored_key"] and report["config"]["use_stored_key"]
            assert TOKEN not in json.dumps(report)
            assert (
                store.secrets.get_export_key(
                    destination_binding(client.app.state.settings.observability.log_export)
                )
                == TOKEN
            )
            with sqlite3.connect(store.database_path) as db:
                encrypted = db.execute(
                    "SELECT encrypted_value FROM log_export_credentials"
                ).fetchone()[0]
            assert TOKEN.encode() not in encrypted
            assert TOKEN not in json.dumps(store.runtime_config())
            for revision in store.list_config_revisions():
                assert TOKEN not in json.dumps(store.config_revision(revision["revision_id"]))
            store.emit(exchange("first"))
            wait(lambda: store.export_outbox.health()["delivered"] == 1)
            assert received(server)[0]["event"]["request_id"] == "first"
            value["enabled"] = False
            assert save(client, value).status_code == 204
            assert client.app.state.log_export.task is None
            store.emit(exchange("disabled"))
            assert store.export_outbox.health()["pending"] == 0
            assert store.get_event("disabled")
            value["enabled"] = True
            assert save(client, value).status_code == 204
            store.emit(exchange("reenabled"))
            wait(lambda: store.export_outbox.health()["delivered"] == 2)
            audit = store.list_management_events()
            assert TOKEN not in json.dumps(audit)
            assert {"log_export.updated", "log_export_key.saved"} <= {
                item["action"] for item in audit
            }
            assert client.post("/admin/api/storage/check", headers=ADMIN).json()["ok"]
        # Saved console config takes precedence over startup defaults and survives encrypted recovery.
        archive = tmp_path / "backup/gateway.backup"
        backup(tmp_path / "gateway", archive, "synthetic-backup-password")
        assert TOKEN.encode() not in archive.read_bytes()
        restored = tmp_path / "recovered"
        with instance_lock(restored):
            restore(restored, archive, "synthetic-backup-password")
        with TestClient(create_app(local_settings(restored))) as client:
            assert client.get("/admin/api/log-export", headers=ADMIN).json()["has_stored_key"]
            store = client.app.state.control_store
            store.emit(exchange("restored"))
            wait(lambda: store.export_outbox.health()["delivered"] == 3)


def test_draft_probe_unsaved_key_binding_and_safe_remote_failures(settings, tmp_path):
    with (
        collector(tmp_path / "one.db") as (server, endpoint),
        collector(tmp_path / "two.db", "new-synthetic-token") as (other, other_endpoint),
    ):
        with TestClient(create_app(settings)) as client:
            value = config(client, endpoint)
            response = client.post(
                "/admin/api/log-export/test", headers=ADMIN, json={"config": value, "key": TOKEN}
            )
            assert response.json()["ok"]
            store = client.app.state.control_store
            assert not store.runtime_config() and store.secrets.export_key_binding() is None
            assert received(server)[0]["event"]["event"] == "connection_test"
            assert store.export_outbox.health()["delivered"] == 0
            assert save(client, value, TOKEN).status_code == 204
            revision = store.list_config_revisions()[0]["revision_id"]
            current_worker = client.app.state.log_export
            for method, path in (
                ("post", "/admin/api/log-export/test"),
                ("put", "/admin/api/log-export"),
            ):
                changed = {**value, "endpoint": other_endpoint}
                response = getattr(client, method)(path, headers=ADMIN, json={"config": changed})
                assert response.status_code == 409
                assert not received(other)
            assert client.app.state.log_export is current_worker
            assert store.list_config_revisions()[0]["revision_id"] == revision
            # A fresh draft token is allowed for another receiver, without changing saved state.
            response = client.post(
                "/admin/api/log-export/test",
                headers=ADMIN,
                json={"config": changed, "key": "new-synthetic-token"},
            )
            assert response.json()["ok"] and received(other)
            assert store.runtime_config()["log_export"]["endpoint"] == endpoint
            failed = client.post(
                "/admin/api/log-export/test",
                headers=ADMIN,
                json={"config": value, "key": "wrong-token"},
            )
            assert not failed.json()["ok"] and "wrong-token" not in failed.text
            assert (
                save(
                    client, {**changed, "use_stored_key": False, "enabled": False}, clear_key=True
                ).status_code
                == 204
            )
            assert store.secrets.export_key_binding() is None


def test_stale_save_and_audit_failure_preserve_active_worker_and_secret(
    settings, tmp_path, monkeypatch
):
    with collector(tmp_path / "one.db") as (_, endpoint):
        with TestClient(create_app(settings)) as client:
            value = config(client, endpoint)
            stale = client.get("/admin/api/log-export", headers=ADMIN).headers["etag"]
            assert save(client, value, TOKEN).status_code == 204
            worker = client.app.state.log_export
            store = client.app.state.control_store
            revision = store.list_config_revisions()[0]["revision_id"]
            response = client.put(
                "/admin/api/log-export",
                headers={**ADMIN, "If-Match": stale},
                json={"config": {**value, "enabled": False}},
            )
            assert response.status_code == 409
            assert (
                client.app.state.log_export is worker
                and store.list_config_revisions()[0]["revision_id"] == revision
            )
            original = store.management_audit.record
            monkeypatch.setattr(
                store.management_audit,
                "record",
                lambda *a, **k: (_ for _ in ()).throw(
                    sqlite3.OperationalError("private audit error")
                ),
            )
            assert save(client, value, "replacement-synthetic-token").status_code == 503
            assert client.app.state.log_export is worker
            assert store.secrets.get_export_key(destination_binding(worker.config)) == TOKEN
            assert store.list_config_revisions()[0]["revision_id"] == revision
            monkeypatch.setattr(store.management_audit, "record", original)
            store.emit(exchange("still-working"))
            wait(lambda: store.export_outbox.health()["delivered"] == 1)


def test_history_restore_changed_export_clears_key_and_disables_delivery(settings, tmp_path):
    with (
        collector(tmp_path / "one.db") as (_, endpoint),
        collector(tmp_path / "two.db", "new-synthetic-token") as (_, other_endpoint),
    ):
        with TestClient(create_app(settings)) as client:
            value = config(client, endpoint)
            assert save(client, value, TOKEN).status_code == 204
            store = client.app.state.control_store
            target = store.list_config_revisions()[0]["revision_id"]
            assert (
                save(
                    client, {**value, "endpoint": other_endpoint}, "new-synthetic-token"
                ).status_code
                == 204
            )
            current = store.list_config_revisions()[0]["revision_id"]
            detail = client.get(
                f"/admin/api/configuration/revisions/{target}", headers=ADMIN
            ).json()
            assert detail["changed_export_binding"]
            payload = {"confirmation": "RESTORE", "expected_revision": current}
            path = f"/admin/api/configuration/revisions/{target}/restore"
            assert client.post(path, headers=ADMIN, json=payload).status_code == 409
            result = client.post(
                path, headers=ADMIN, json={**payload, "clear_changed_credentials": True}
            )
            assert result.status_code == 200 and result.json()["cleared_export_credential"]
            report = client.get("/admin/api/log-export", headers=ADMIN).json()
            assert report["config"]["endpoint"] == endpoint and not report["config"]["enabled"]
            assert not report["has_any_stored_key"] and client.app.state.log_export.task is None


def test_older_history_without_export_preserves_current_settings(settings, tmp_path):
    with collector(tmp_path / "one.db") as (_, endpoint):
        with TestClient(create_app(settings)) as client:
            store = client.app.state.control_store
            old = store.config_revision(1)
            old.pop("log_export")
            with store._connect() as db:
                db.execute(
                    "UPDATE configuration_revisions SET encrypted_snapshot=? WHERE revision_id=1",
                    (store._fernet.encrypt(json.dumps(old).encode()),),
                )
            value = config(client, endpoint)
            assert save(client, value, TOKEN).status_code == 204
            current = store.list_config_revisions()[0]["revision_id"]
            assert (
                client.post(
                    "/admin/api/configuration/revisions/1/restore",
                    headers=ADMIN,
                    json={"confirmation": "RESTORE", "expected_revision": current},
                ).status_code
                == 200
            )
            assert store.runtime_config()["log_export"] == value
            assert client.app.state.log_export.config.enabled


@pytest.mark.parametrize(
    "payload",
    [
        {"config": {"enabled": True}},
        {"config": {"endpoint": "http://user:secret@receiver.test/events"}},
        {"config": {"use_stored_key": True, "api_key_env": "EXPORT_TOKEN"}},
        {"config": {}, "key": "bad\r\ntoken"},
        {"config": {}, "clear_key": "yes"},
    ],
)
def test_invalid_payloads_and_operator_auth(settings, payload):
    with TestClient(create_app(settings)) as client:
        assert client.get("/admin/api/log-export").status_code == 401
        for path in ("/admin/api/log-export", "/admin/api/log-export/test"):
            method = client.put if path.endswith("log-export") else client.post
            assert method(path, json={"config": {}}).status_code == 401
            result = method(path, headers=ADMIN, json=payload)
            assert result.status_code == 422 and "bad\\r\\ntoken" not in result.text


def test_schema_eight_migration_preserves_pending_metadata_and_keys(settings):
    store = LocalControlStore(settings.control_plane)
    app, key = store.create_app_key("sample", ["auto"], False)
    store.export_outbox.configure(
        LogExportConfig(enabled=True, endpoint="http://127.0.0.1:9087/events"), lambda value: value
    )
    store.emit(exchange("before-upgrade"))
    with store._connect() as connection:
        connection.execute("DROP TABLE log_export_credentials")
        connection.execute("PRAGMA user_version=8")
    reopened = LocalControlStore(settings.control_plane)
    assert reopened.authenticate_app_key(key).app_id == app["app_id"]
    assert reopened.get_event("before-upgrade")
    assert reopened.export_outbox.health()["pending"] == 1
    assert reopened.secrets.export_key_binding() is None


@pytest.mark.parametrize("tampering", ["binding", "ciphertext", "missing_table"])
def test_backup_rejects_invalid_export_credentials(settings, tmp_path, tampering):
    with collector(tmp_path / "one.db") as (_, endpoint):
        with TestClient(create_app(settings)) as client:
            assert save(client, config(client, endpoint), TOKEN).status_code == 204
            store = client.app.state.control_store
        with store._connect() as db:
            if tampering == "binding":
                db.execute("UPDATE log_export_credentials SET binding='wrong'")
            elif tampering == "ciphertext":
                db.execute("UPDATE log_export_credentials SET encrypted_value='corrupt'")
            else:
                db.execute("DROP TABLE log_export_credentials")
        with pytest.raises((ValueError, InvalidToken)):
            validate_database(store.database_path, store.master_key_path.read_bytes())
