"""Managed-key overlap, expiry, migration, audit and HTTP enforcement."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend_contracts import exchange
from legacy_backend import schema_two_identities
from m87_gateway.api import routes
from m87_gateway.cli import local_settings
from m87_gateway.control import LocalControlStore
from m87_gateway.control.repositories.identities import KeyLimitError
from m87_gateway.main import create_app
from test_control_api import FakeProvider


@pytest.fixture
def store(tmp_path):
    return LocalControlStore(local_settings(tmp_path).control_plane)


def test_overlap_revocation_expiry_and_permissions_survive_restart(store):
    app, old = store.create_app_key("sample", ["auto"], False, rate_limit_per_minute=5)
    replacement, new = store.issue_app_key("sample", expires_in_days=2)
    assert old != new
    assert store.authenticate_app_key(old).app_id == store.authenticate_app_key(new).app_id
    store.update_app_models("sample", ["ollama:small"])
    store.update_app_limits("sample", 7, 2)
    restarted = LocalControlStore(store.config)
    for key in (old, new):
        context = restarted.authenticate_app_key(key)
        assert context.allowed_models == ["ollama:small"]
        assert context.rate_limit_per_minute == 7 and context.max_concurrent_requests == 2
    assert restarted.revoke_app_key("sample", app["key_id"])
    assert restarted.revoke_app_key("sample", app["key_id"])  # Idempotent retry.
    assert restarted.authenticate_app_key(old) is None
    assert restarted.authenticate_app_key(new)
    with sqlite3.connect(store.database_path) as db:
        db.execute(
            "UPDATE app_keys SET expires_at = ? WHERE key_id = ?",
            (
                (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                replacement["key_id"],
            ),
        )
    assert restarted.authenticate_app_key(new) is None
    assert restarted.list_apps()[0]["active_key_count"] == 0
    assert not any(item["active"] for item in restarted.list_app_keys("sample"))
    assert not restarted.revoke_app_key("other", replacement["key_id"])


def test_immediate_rotation_and_audit_are_atomic_and_secret_free(store, monkeypatch):
    initial, old = store.create_app_key("sample", ["auto"], False)
    before = store.list_management_events()

    def failure(*args):
        raise sqlite3.OperationalError("synthetic audit failure")

    with monkeypatch.context() as patch:
        patch.setattr(store.management_audit, "record", failure)
        with pytest.raises(sqlite3.OperationalError):
            store.issue_app_key("sample", revoke_existing=True)
    assert store.authenticate_app_key(old)
    assert len(store.list_app_keys("sample")) == 1
    assert store.list_management_events() == before
    replacement, new = store.issue_app_key("sample", revoke_existing=True)
    assert store.authenticate_app_key(old) is None and store.authenticate_app_key(new)
    events = store.list_management_events()
    assert {e["action"] for e in events} == {
        "application.created",
        "application_key.issued",
        "application_key.revoked",
    }
    assert [e for e in events if e["action"] == "application_key.revoked"][0]["key_id"] == initial[
        "key_id"
    ]
    assert any(e["key_id"] == replacement["key_id"] for e in events)
    assert old not in json.dumps(events) and new not in json.dumps(events)
    assert all(e["actor"] == "operator" for e in events)
    assert store.delete_app("sample")
    assert store.authenticate_app_key(new) is None
    assert store.list_app_keys("sample") is None
    assert store.list_management_events()[0]["action"] == "application.deleted"


def test_concurrent_issuance_enforces_active_key_bound(store):
    store.create_app_key("sample", ["auto"], False)

    def issue(_):
        try:
            return store.issue_app_key("sample")
        except KeyLimitError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(issue, range(12)))
    assert sum(result is not None for result in results) == 9
    assert store.list_apps()[0]["active_key_count"] == 10
    replacement, key = store.issue_app_key("sample", revoke_existing=True)
    assert store.list_apps()[0]["active_key_count"] == 1
    assert store.authenticate_app_key(key)
    assert replacement["revoked_at"] is None
    for value in (0, 3651, True, 1.2):
        with pytest.raises(ValueError):
            store.issue_app_key("sample", expires_in_days=value)
    assert store.list_apps()[0]["active_key_count"] == 1


def test_schema_two_migration_preserves_identity_usage_and_credentials(store):
    store.create_project("testing", "Testing")
    _, key = store.create_app_key("sample", ["auto"], True, 7, "testing", 2)
    store.put_provider_key("openai", "synthetic-secret")
    store.emit(exchange(project_id="testing", app_id="sample"))
    with sqlite3.connect(store.database_path) as db:
        schema_two_identities(db)
    upgraded = LocalControlStore(store.config)
    identity = upgraded.authenticate_app_key(key)
    assert identity.project_id == "testing" and identity.capture_content
    assert identity.rate_limit_per_minute == 7 and identity.max_concurrent_requests == 2
    assert upgraded.get_provider_key("openai") == "synthetic-secret"
    assert upgraded.overview(project_id="testing")["total_tokens"] == 10
    assert upgraded.list_app_keys("sample")[0]["expires_at"] is None
    assert (
        upgraded.list_management_events() == []
    )  # Migration doesn't invent historical operator actions.
    metadata, replacement = upgraded.issue_app_key("sample")
    assert upgraded.authenticate_app_key(replacement)
    assert metadata["key_id"] != upgraded.list_app_keys("sample")[1]["key_id"]


def test_management_audit_retention_and_project_filter(store):
    store.create_project("other", "Other")
    store.create_app_key("sample", ["auto"], False)
    store.assign_app_project("sample", "other")
    events = store.list_management_events(project_id="other")
    assert {e["action"] for e in events} == {"project.created", "application.project_changed"}
    with sqlite3.connect(store.database_path) as db:
        db.execute(
            "UPDATE management_events SET created_at = ?",
            ((datetime.now(timezone.utc) - timedelta(days=366)).isoformat(),),
        )
    assert LocalControlStore(store.config).list_management_events() == []


def test_rotation_http_auth_shared_limits_and_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-operator-key-with-enough-entropy")
    monkeypatch.setattr(routes, "get_provider", lambda *args: FakeProvider())
    settings = local_settings(tmp_path)
    settings.providers.ollama.enabled = True
    admin = {"Authorization": "Bearer synthetic-operator-key-with-enough-entropy"}
    body = {"model": "auto", "messages": [{"role": "user", "content": "synthetic question"}]}
    with TestClient(create_app(settings)) as client:
        initial = client.post(
            "/admin/api/apps",
            headers=admin,
            json={
                "app_id": "sample",
                "allowed_models": ["auto", "ollama:llama3"],
                "rate_limit_per_minute": 1,
            },
        ).json()
        path = "/admin/api/apps/sample/keys"
        assert client.get(path).status_code == 401
        assert client.post(path, json={}).status_code == 401
        assert client.get("/admin/api/management-events").status_code == 401
        for payload in (
            {"expires_in_days": 0},
            {"expires_in_days": True},
            {"revoke_existing": "yes"},
            {"extra": "unexpected"},
        ):
            assert client.post(path, headers=admin, json=payload).status_code == 422
        response = client.post(path, headers=admin, json={"expires_in_days": 30})
        assert response.status_code == 201 and response.headers["cache-control"] == "no-store"
        replacement = response.json()
        old_headers = {"Authorization": f"Bearer {initial['api_key']}"}
        new_headers = {"Authorization": f"Bearer {replacement['api_key']}"}
        assert (
            client.post("/v1/chat/completions", headers=old_headers, json=body).status_code == 200
        )
        assert (
            client.post("/v1/chat/completions", headers=new_headers, json=body).status_code == 429
        )
        revoke = path + "/" + initial["key_id"]
        assert client.delete(revoke).status_code == 401
        assert client.delete(revoke, headers=admin).status_code == 204
        assert client.delete(revoke, headers=admin).status_code == 204
        assert (
            client.post("/v1/chat/completions", headers=old_headers, json=body).status_code == 401
        )
        assert (
            client.post("/v1/chat/completions", headers=new_headers, json=body).status_code == 429
        )
        assert client.get(path, headers=admin).json()["items"][0]["active"]
        assert (
            client.delete(
                "/admin/api/apps/missing/keys/" + replacement["key_id"], headers=admin
            ).status_code
            == 404
        )
        assert (
            client.post("/admin/api/apps/missing/keys", headers=admin, json={}).status_code == 404
        )
        serialized = client.get("/admin/api/management-events", headers=admin).text
        assert initial["api_key"] not in serialized and replacement["api_key"] not in serialized
        assert "key_digest" not in client.get(path, headers=admin).text
        totals = client.get("/admin/api/overview", headers=admin).json()
        assert client.delete("/admin/api/apps/sample", headers=admin).status_code == 204
        assert (
            client.post("/v1/chat/completions", headers=new_headers, json=body).status_code == 401
        )
        assert (
            client.get("/admin/api/overview", headers=admin).json()["total_tokens"]
            == totals["total_tokens"]
        )


def test_encrypted_backup_preserves_rotated_keys_and_audit(store, tmp_path):
    from m87_gateway.backup import backup, restore
    from m87_gateway.cli import operator_key
    from m87_gateway.workstation import instance_lock

    operator_key(store.database_path.parent)
    initial, old = store.create_app_key("sample", ["auto"], False)
    metadata, new = store.issue_app_key("sample", expires_in_days=30)
    store.revoke_app_key("sample", initial["key_id"])
    archive = tmp_path / "archives" / "gateway.backup"
    with instance_lock(store.database_path.parent):
        backup(store.database_path.parent, archive, "synthetic-backup-passphrase")
    recovered = tmp_path / "recovered"
    with instance_lock(recovered):
        restore(recovered, archive, "synthetic-backup-passphrase")
    reopened = LocalControlStore(local_settings(recovered).control_plane)
    assert reopened.authenticate_app_key(old) is None
    assert reopened.authenticate_app_key(new)
    assert reopened.list_app_keys("sample")[0]["expires_at"] == metadata["expires_at"]
    assert reopened.list_management_events() == store.list_management_events()


def test_migration_does_not_reactivate_disabled_legacy_keys(store):
    _, key = store.create_app_key("disabled", ["auto"], False)
    with sqlite3.connect(store.database_path) as db:
        schema_two_identities(db)
        db.execute("UPDATE app_keys SET enabled = 0")
    reopened = LocalControlStore(store.config)
    assert reopened.authenticate_app_key(key) is None
    assert not reopened.list_apps()[0]["enabled"]
    assert reopened.list_app_keys("disabled")[0]["revoked_at"]
    with pytest.raises(ValueError, match="Application does not exist"):
        reopened.issue_app_key("disabled")
