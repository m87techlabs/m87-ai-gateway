"""Revision, credential-boundary and storage checks against isolated SQLite stores."""

import json
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from backend_contracts import exchange
from m87_gateway.cli import local_settings
from m87_gateway.control import LocalControlStore
from m87_gateway.control.repositories.configuration import HISTORY_LIMIT, RevisionConflict
from m87_gateway.control.setup import managed_snapshot
from m87_gateway.control.store import SCHEMA_VERSION
from m87_gateway.main import create_app


@pytest.fixture
def store(tmp_path):
    return LocalControlStore(local_settings(tmp_path).control_plane)


@contextmanager
def running(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-history-operator-key-long-enough")
    app = create_app(local_settings(tmp_path))
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer synthetic-history-operator-key-long-enough"
        yield client, app.state


def history(client):
    response = client.get("/admin/api/configuration/revisions")
    assert response.status_code == 200
    return response.json()


def restore(client, target, current, **options):
    return client.post(
        f"/admin/api/configuration/revisions/{target}/restore",
        json={
            "expected_revision": current,
            "confirmation": "RESTORE",
            **options,
        },
    )


def test_snapshots_are_encrypted_bounded_and_reopen(store):
    store.initialize_history({"default_model": "ollama:initial"})
    store.initialize_history({"default_model": "ollama:ignored"})
    assert len(store.list_config_revisions()) == 1
    for number in range(HISTORY_LIMIT + 2):
        store.save_runtime_config({"default_model": f"ollama:revision-{number}"})
    items = store.list_config_revisions()
    assert len(items) == HISTORY_LIMIT
    assert store.config_revision(1) is None
    latest = items[0]["revision_id"]
    reopened = LocalControlStore(store.config)
    assert reopened.config_revision(latest) == {"default_model": "ollama:revision-101"}
    with sqlite3.connect(store.database_path) as db:
        rows = db.execute("SELECT encrypted_snapshot FROM configuration_revisions").fetchall()
        assert all(b"ollama:revision" not in row[0] for row in rows)
    assert "encrypted_snapshot" not in json.dumps(items)


def test_audit_failure_rolls_back_configuration_credentials_and_revision(store, monkeypatch):
    store.save_runtime_config({"default_model": "ollama:original"}, "openai", "original-secret")
    before = store.list_config_revisions()
    audit = store.list_management_events()

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic-secret-private-path")

    monkeypatch.setattr(store.management_audit, "record", fail)
    with pytest.raises(sqlite3.OperationalError):
        store.save_runtime_config({"default_model": "ollama:new"}, "openai", "new-secret")
    assert store.runtime_config() == {"default_model": "ollama:original"}
    assert store.get_provider_key("openai") == "original-secret"
    assert store.list_config_revisions() == before
    assert store.list_management_events() == audit


@pytest.mark.parametrize("operation", ["save", "delete"])
def test_provider_key_audit_failure_is_transactional(store, monkeypatch, operation):
    store.put_provider_key("openai", "original-secret")
    before = store.list_management_events()

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic audit failure")

    monkeypatch.setattr(store.management_audit, "record", fail)
    with pytest.raises(sqlite3.OperationalError):
        if operation == "save":
            store.put_provider_key("openai", "replacement-secret")
        else:
            store.delete_provider_key("openai")
    assert store.get_provider_key("openai") == "original-secret"
    assert store.list_management_events() == before


def test_revision_compare_and_swap_preserves_state(store):
    first = store.save_runtime_config({"default_model": "ollama:first"})
    store.save_runtime_config({"default_model": "ollama:second"})
    before = store.list_config_revisions()
    with pytest.raises(RevisionConflict):
        store.save_runtime_config({"default_model": "ollama:stale"}, expected_revision=first)
    assert store.runtime_config()["default_model"] == "ollama:second"
    assert store.list_config_revisions() == before


def test_restore_controls_capture_clears_cache_and_survives_restart(tmp_path, monkeypatch):
    with running(tmp_path, monkeypatch) as (client, state):
        first = history(client)["current_revision"]
        original = client.get("/admin/api/controls").json()
        changed = {**original, "retention_days": 7, "max_content_chars": 90}
        changed["cache"] = {**original["cache"], "enabled": True}
        assert client.put("/admin/api/controls", json=changed).status_code == 204
        assert (
            client.put(
                "/admin/api/setup",
                json={"default_model": "ollama:changed", "capture_content": True},
            ).status_code
            == 422
        )
        current = history(client)["current_revision"]
        cache = state.response_cache
        response = restore(client, first, current)
        assert response.status_code == 200
        assert state.response_cache is not cache
        assert client.get("/admin/api/controls").json() == original
        assert history(client)["items"][0]["restored_from"] == first
        assert restore(client, first, current).status_code == 409
    with running(tmp_path, monkeypatch) as (client, state):
        assert client.get("/admin/api/controls").json() == original
        assert len(history(client)["items"]) == 3


def test_restore_keeps_current_keys_for_same_endpoint(tmp_path, monkeypatch):
    with running(tmp_path, monkeypatch) as (client, state):
        endpoint = "http://127.0.0.1:9999/v1"
        path = "/admin/api/connections/openai"
        assert (
            client.put(
                path, json={"config": {"base_url": endpoint}, "key": "original-provider-secret"}
            ).status_code
            == 204
        )
        first = history(client)["current_revision"]
        assert (
            client.put(
                path,
                json={
                    "config": {"base_url": endpoint, "timeout_seconds": 12},
                    "key": "new-provider-secret",
                },
            ).status_code
            == 204
        )
        current = history(client)["current_revision"]
        assert restore(client, first, current).status_code == 200
        assert state.control_store.get_provider_key("openai") == "new-provider-secret"
        assert state.settings.providers.openai.timeout_seconds == 60
        detail = client.get(f"/admin/api/configuration/revisions/{first}").text
        audit = client.get("/admin/api/management-events").text
        assert "original-provider-secret" not in detail + audit
        assert "new-provider-secret" not in detail + audit


def test_changed_endpoint_restore_requires_confirmation_clears_all_aliases_and_env(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-env-secret")
    with running(tmp_path, monkeypatch) as (client, state):
        path = "/admin/api/connections/openai"
        assert (
            client.put(
                path,
                json={
                    "config": {"base_url": "http://localhost:9998/v1"},
                    "key": "first-provider-secret",
                },
            ).status_code
            == 204
        )
        target = history(client)["current_revision"]
        assert (
            client.put(
                path,
                json={
                    "config": {"base_url": "http://localhost:9999/v1"},
                    "key": "second-provider-secret",
                },
            ).status_code
            == 204
        )
        state.control_store.put_provider_key("openai", "alternate-secret", "secondary")
        current = history(client)["current_revision"]
        preview = client.get(f"/admin/api/configuration/revisions/{target}").json()
        assert preview["changed_provider_bindings"] == ["openai"]
        before = state.control_store.list_management_events()
        assert restore(client, target, current).status_code == 409
        assert state.control_store.list_management_events() == before
        assert state.control_store.get_provider_key("openai") == "second-provider-secret"
        result = restore(client, target, current, clear_changed_credentials=True)
        assert result.status_code == 200
        assert result.json()["cleared_provider_credentials"] == ["openai"]
        assert not state.control_store.list_provider_keys()
        assert state.settings.providers.openai.api_key_env is None
        assert state.settings.providers.openai.base_url == "http://localhost:9998/v1"
        assert {
            row["alias"]
            for row in state.control_store.list_management_events()
            if row["action"] == "provider_key.deleted"
        } == {"default", "secondary"}


def test_environment_binding_is_not_resurrected(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-env-secret")
    settings = local_settings(tmp_path)
    # Explicitly configure an environment credential at the original endpoint.
    settings.providers.openai.api_key_env = "OPENAI_API_KEY"
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-history-operator-key-long-enough")
    with TestClient(create_app(settings)) as client:
        client.headers["Authorization"] = "Bearer synthetic-history-operator-key-long-enough"
        initial = history(client)["current_revision"]
        assert (
            client.put(
                "/admin/api/connections/openai",
                json={"config": {"base_url": "http://localhost:9998/v1"}, "clear_key": True},
            ).status_code
            == 204
        )
        current = history(client)["current_revision"]
        assert restore(client, initial, current).status_code == 409
        assert restore(client, initial, current, clear_changed_credentials=True).status_code == 200
        assert (
            client.get("/admin/api/setup").json()["connections"][0]["config"]["api_key_env"] is None
        )


def test_failed_activation_retains_runtime_and_safe_error(tmp_path, monkeypatch):
    with running(tmp_path, monkeypatch) as (client, state):
        original = client.get("/admin/api/controls").json()
        revisions = history(client)
        cache = state.response_cache

        def fail(*args, **kwargs):
            raise sqlite3.OperationalError("synthetic-sensitive-secret-and-path")

        monkeypatch.setattr(state.control_store.management_audit, "record", fail)
        response = client.put("/admin/api/controls", json={**original, "retention_days": 7})
        assert response.status_code == 503
        assert "synthetic-sensitive" not in response.text
        assert client.get("/admin/api/controls").json() == original
        assert history(client) == revisions
        assert state.response_cache is cache


@pytest.mark.parametrize(
    "path,method",
    [
        ("/configuration/revisions", "GET"),
        ("/configuration/revisions/1", "GET"),
        ("/configuration/revisions/1/restore", "POST"),
        ("/storage", "GET"),
        ("/storage/check", "POST"),
    ],
)
def test_operator_only_endpoints(tmp_path, monkeypatch, path, method):
    with running(tmp_path, monkeypatch) as (client, state):
        client.headers.clear()
        assert client.request(method, "/admin/api" + path).status_code == 401
        _, key = state.control_store.create_app_key("sample", ["auto"], False)
        client.headers["Authorization"] = "Bearer " + key
        assert client.request(method, "/admin/api" + path).status_code == 401


def test_storage_checks_do_not_change_data_or_audit(store):
    _, key = store.create_app_key("sample", ["auto"], False)
    store.put_provider_key("openai", "synthetic-provider-secret")
    store.save_runtime_config({"default_model": "ollama:small"})
    store.emit(exchange())
    before = store.list_management_events()
    assert store.storage_health()["ok"]
    report = store.storage_health(verify=True)
    assert report["ok"] and report["verified"]
    assert {item["name"] for item in report["checks"]} == {
        "Private files",
        "Database access",
        "Credential encryption",
        "Database integrity",
        "Database write",
    }
    assert str(store.database_path) not in json.dumps(report)
    assert store.list_management_events() == before
    assert store.authenticate_app_key(key)
    assert store.overview()["total_tokens"] == 10
    with sqlite3.connect(store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM storage_probe").fetchone()[0] == 0


@pytest.mark.parametrize(
    "failure", ["key_missing", "key_changed", "ciphertext", "database_missing", "permissions"]
)
def test_storage_failures_are_safe(store, failure):
    store.put_provider_key("openai", "synthetic-provider-secret")
    if failure == "key_missing":
        store.master_key_path.unlink()
    elif failure == "key_changed":
        store.master_key_path.write_text("synthetic-sensitive-broken-key")
    elif failure == "ciphertext":
        with sqlite3.connect(store.database_path) as db:
            db.execute("UPDATE provider_keys SET encrypted_value = 'synthetic-secret'")
    elif failure == "database_missing":
        store.database_path.unlink()
    else:
        import os

        if os.name == "nt":
            pytest.skip("POSIX mode check; Windows ACL safety is covered separately")
        store.master_key_path.chmod(0o644)
    report = store.storage_health(verify=True)
    assert not report["ok"]
    serialized = json.dumps(report)
    assert "synthetic-secret" not in serialized and "synthetic-sensitive" not in serialized
    assert str(store.database_path) not in serialized
    if failure == "database_missing":
        assert not store.database_path.exists()


def test_schema_five_migration_preserves_data_and_old_audit(store):
    _, key = store.create_app_key("sample", ["auto"], False)
    store.put_provider_key("openai", "synthetic-provider-secret")
    store.emit(exchange())
    audit = store.list_management_events()
    with sqlite3.connect(store.database_path) as db:
        db.execute("DROP TABLE configuration_revisions")
        db.execute("DROP TABLE storage_probe")
        for column in ("provider", "alias", "revision_id", "restored_from"):
            db.execute(f"ALTER TABLE management_events DROP COLUMN {column}")
        db.execute("PRAGMA user_version = 5")
    reopened = LocalControlStore(store.config)
    assert reopened.authenticate_app_key(key)
    assert reopened.get_provider_key("openai") == "synthetic-provider-secret"
    assert reopened.overview()["total_tokens"] == 10
    assert reopened.get_event("contract-request")
    assert [e["event_id"] for e in reopened.list_management_events()] == [
        e["event_id"] for e in audit
    ]
    assert reopened.list_config_revisions() == []
    assert reopened.storage_health()["schema_version"] == SCHEMA_VERSION


def test_baseline_snapshot_excludes_keys_apps_and_paths(tmp_path):
    settings = local_settings(tmp_path)
    data = managed_snapshot(settings)
    assert set(data) == {"providers", "default_model", "capture_content", "controls"}
    assert str(tmp_path) not in json.dumps(data)


@pytest.mark.parametrize("path", ["controls", "setup", "connections/ollama"])
def test_stale_configuration_save_does_not_activate(tmp_path, monkeypatch, path):
    with running(tmp_path, monkeypatch) as (client, state):
        etag = client.get("/admin/api/controls").headers["ETag"]
        controls = client.get("/admin/api/controls").json()
        assert (
            client.put(
                "/admin/api/connections/ollama",
                json={"config": {"base_url": "http://localhost:11434"}},
            ).status_code
            == 204
        )
        before = history(client)
        active = state.settings
        bodies = {
            "controls": controls,
            "setup": {"default_model": "ollama:small", "capture_content": True},
            "connections/ollama": {"config": {"base_url": "http://localhost:11435"}},
        }
        response = client.put("/admin/api/" + path, json=bodies[path], headers={"If-Match": etag})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "revision_conflict"
        assert state.settings is active
        assert history(client) == before


@pytest.mark.parametrize("etag", ["abc", "0", "-1", "9999999999999999999999999999999999"])
def test_invalid_revision_header_is_safe(tmp_path, monkeypatch, etag):
    with running(tmp_path, monkeypatch) as (client, state):
        controls = client.get("/admin/api/controls").json()
        assert (
            client.put("/admin/api/controls", json=controls, headers={"If-Match": etag}).status_code
            == 422
        )
        assert len(history(client)["items"]) == 1


def test_storage_write_probe_reports_busy_and_recovers(store):
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        report = store.storage_health(verify=True)
        assert not report["ok"]
        write = next(item for item in report["checks"] if item["name"] == "Database write")
        assert write["code"] == "storage_busy"
        connection.rollback()
    assert store.storage_health(verify=True)["ok"]


def test_revision_missing_or_corrupt_does_not_activate(tmp_path, monkeypatch):
    with running(tmp_path, monkeypatch) as (client, state):
        current = history(client)["current_revision"]
        assert restore(client, 99999, current).status_code == 404
        active = state.settings
        with sqlite3.connect(state.control_store.database_path) as connection:
            connection.execute(
                "UPDATE configuration_revisions SET encrypted_snapshot = 'synthetic-sensitive-text'"
            )
        for path in (
            f"/admin/api/configuration/revisions/{current}",
            f"/admin/api/configuration/revisions/{current}/restore",
        ):
            response = (
                client.get(path)
                if not path.endswith("restore")
                else restore(client, current, current)
            )
            assert response.status_code == 503
            assert "synthetic-sensitive" not in response.text
        assert state.settings is active
        assert not state.control_store.storage_health(verify=True)["ok"]


def test_capture_and_default_restore_preserves_application_and_usage(tmp_path, monkeypatch):
    with running(tmp_path, monkeypatch) as (client, state):
        assert (
            client.put(
                "/admin/api/connections/ollama",
                json={"config": {"base_url": "http://localhost:11434"}},
            ).status_code
            == 204
        )
        assert (
            client.put(
                "/admin/api/setup", json={"default_model": "ollama:first", "capture_content": True}
            ).status_code
            == 204
        )
        target = history(client)["current_revision"]
        _, key = state.control_store.create_app_key("sample", ["ollama:first"], False)
        state.control_store.emit(exchange())
        assert (
            client.put(
                "/admin/api/setup",
                json={"default_model": "ollama:second", "capture_content": False},
            ).status_code
            == 204
        )
        current = history(client)["current_revision"]
        assert restore(client, target, current).status_code == 200
        setup = client.get("/admin/api/setup").json()
        assert setup["default_model"] == "ollama:first" and setup["capture_content"]
        assert state.control_store.authenticate_app_key(key).allowed_models == ["ollama:first"]
        assert state.control_store.overview()["total_tokens"] == 10


def test_restore_credential_removal_rolls_back_on_audit_failure(store, monkeypatch):
    store.save_runtime_config({"default_model": "ollama:current"})
    store.put_provider_key("openai", "default-secret")
    store.put_provider_key("openai", "alternate-secret", "secondary")
    before = store.list_management_events()
    revisions = store.list_config_revisions()
    record = store.management_audit.record

    def fail_after_first(connection, action, **options):
        record(connection, action, **options)
        if options.get("alias") == "secondary":
            raise sqlite3.OperationalError("synthetic audit failure")

    monkeypatch.setattr(store.management_audit, "record", fail_after_first)
    with pytest.raises(sqlite3.OperationalError):
        store.save_runtime_config(
            {"default_model": "ollama:restored"},
            clear_providers=["openai"],
            action="configuration.restored",
        )
    assert store.get_provider_key("openai") == "default-secret"
    assert store.get_provider_key("openai", "secondary") == "alternate-secret"
    assert store.runtime_config()["default_model"] == "ollama:current"
    assert store.list_management_events() == before
    assert store.list_config_revisions() == revisions
