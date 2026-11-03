"""An application key identifies its traffic everywhere the gateway reports on it."""

import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from m87_gateway.cli import local_settings
from m87_gateway.control.store import SCHEMA_VERSION
from m87_gateway.main import create_app
from test_runtime import completion

ADMIN = {"Authorization": "Bearer synthetic-operator-key-long-enough"}
USAGE = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-operator-key-long-enough")
    original = httpx.AsyncClient
    status = {"value": 200}

    def upstream(request):
        return httpx.Response(status["value"], json=completion("ok", USAGE))

    def client(**kwargs):
        if "transport" not in kwargs:
            kwargs["transport"] = httpx.MockTransport(upstream)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    settings = local_settings(tmp_path)
    settings.observability.json_logs = False
    settings.providers.ollama.enabled = True
    settings.routing.default_model = "ollama:test"
    with TestClient(create_app(settings)) as browser:
        browser.upstream_status = status
        yield browser


def create(browser, app_id):
    response = browser.post(
        "/admin/api/apps",
        headers=ADMIN,
        json={"app_id": app_id, "allowed_models": ["ollama:test"]},
    )
    assert response.status_code == 201
    return response.json()["api_key"]


def send(browser, key, count=1):
    for _ in range(count):
        response = browser.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "test", "messages": [{"role": "user", "content": "hello"}]},
        )
    return response


def admin(browser, path):
    response = browser.get(f"/admin/api/{path}", headers=ADMIN)
    assert response.status_code == 200
    return response.json()


def test_dashboard_usage_and_logs_filter_by_application(gateway):
    first, second = create(gateway, "first"), create(gateway, "second")
    assert send(gateway, first, 2).status_code == 200
    assert send(gateway, second).status_code == 200

    assert admin(gateway, "overview")["requests"] == 3
    assert admin(gateway, "overview?app_id=first")["requests"] == 2
    assert admin(gateway, "overview?app_id=first")["total_tokens"] == 10
    assert admin(gateway, "overview?app_id=second")["total_tokens"] == 5
    assert admin(gateway, "overview?app_id=unknown")["requests"] == 0

    usage = admin(gateway, "usage?app_id=first")
    assert [item["app_id"] for item in usage["by_app"]] == ["first"]
    assert usage["by_model"][0]["requests"] == 2
    assert usage["by_endpoint"][0]["requests"] == 2
    assert sum(item["requests"] for item in usage["series"]) == 2
    assert admin(gateway, "usage?app_id=unknown")["by_app"] == []

    logs = admin(gateway, "logs?app_id=second")["items"]
    assert [item["app_id"] for item in logs] == ["second"]
    exported = admin(gateway, "logs/export?app_id=first")
    assert {item["app_id"] for item in exported} == {"first"}


def test_application_filter_can_combine_with_project(gateway):
    key = create(gateway, "first")
    send(gateway, key)
    assert admin(gateway, "overview?app_id=first&project_id=default")["requests"] == 1
    assert admin(gateway, "overview?app_id=first&project_id=other")["requests"] == 0


@pytest.mark.parametrize("value", ["", "has space", "a" * 101])
def test_application_filter_is_validated(gateway, value):
    response = gateway.get("/admin/api/usage", params={"app_id": value}, headers=ADMIN)
    assert response.status_code == 422


def test_application_names_keep_deleted_apps_with_history(gateway):
    key = create(gateway, "retired")
    create(gateway, "unused")
    send(gateway, key)
    assert gateway.delete("/admin/api/apps/retired", headers=ADMIN).status_code == 204
    assert admin(gateway, "app-names")["items"] == ["retired", "unused"]
    assert admin(gateway, "overview?app_id=retired")["requests"] == 1


def test_requests_record_their_key_and_keys_report_last_use(gateway):
    old = create(gateway, "rotating")
    keys = admin(gateway, "apps/rotating/keys")["items"]
    old_id = keys[0]["key_id"]
    assert keys[0]["last_used_at"] is None

    send(gateway, old)
    issued = gateway.post(
        "/admin/api/apps/rotating/keys", headers=ADMIN, json={"revoke_existing": False}
    ).json()
    new_id, new = issued["key_id"], issued["api_key"]

    def state():
        return {item["key_id"]: item for item in admin(gateway, "apps/rotating/keys")["items"]}

    assert state()[old_id]["last_used_at"] is not None
    assert state()[new_id]["last_used_at"] is None
    previous = state()[old_id]["last_used_at"]

    send(gateway, new)
    assert state()[new_id]["last_used_at"] is not None
    assert state()[old_id]["last_used_at"] == previous

    events = admin(gateway, "logs?app_id=rotating")["items"]
    assert sorted(item["key_id"] for item in events) == sorted([new_id, old_id])
    assert admin(gateway, f"logs/{events[0]['request_id']}")["key_id"] == events[0]["key_id"]


def test_key_id_never_exposes_the_key_or_its_digest(gateway):
    key = create(gateway, "private")
    response = send(gateway, key)
    event = admin(gateway, f"logs/{response.headers['x-request-id']}")
    assert key not in str(event)
    with gateway.app.state.control_store._connect() as connection:
        digest = connection.execute("SELECT key_digest FROM app_keys").fetchone()[0]
    assert digest not in str(event) and event["key_id"] != digest


def test_failed_logins_have_no_application_or_key(gateway):
    create(gateway, "real")
    response = send(gateway, "not-a-real-key")
    assert response.status_code == 401
    event = admin(gateway, f"logs/{response.headers['x-request-id']}")
    assert event["app_id"] is None and event["key_id"] is None
    assert [item["app_id"] for item in admin(gateway, "usage")["by_app"]] == [None]


def test_metrics_separate_tokens_latency_and_failures_by_application(gateway):
    first, second = create(gateway, "first"), create(gateway, "second")
    send(gateway, first, 2)
    send(gateway, second)
    gateway.upstream_status["value"] = 500
    send(gateway, second)
    metrics = gateway.get("/metrics").text
    assert 'm87_gateway_tokens_total{app_id="first",kind="prompt",provider="ollama"} 6.0' in metrics
    assert (
        'm87_gateway_tokens_total{app_id="second",kind="prompt",provider="ollama"} 3.0' in metrics
    )
    assert (
        'm87_gateway_request_latency_seconds_count{app_id="first",provider="ollama"} 2.0' in metrics
    )
    assert 'm87_gateway_provider_errors_total{app_id="second",provider="ollama"} 1.0' in metrics
    assert 'm87_gateway_provider_errors_total{app_id="first"' not in metrics


def test_schema_ten_store_upgrades_and_keeps_keys_working(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-operator-key-long-enough")
    settings = local_settings(tmp_path)
    with TestClient(create_app(settings)) as browser:
        key = create(browser, "kept")
    database = tmp_path / "control.db"
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE app_keys DROP COLUMN last_used_at")
        connection.execute("ALTER TABLE events DROP COLUMN key_id")
        connection.execute("PRAGMA user_version = 10")
    with TestClient(create_app(local_settings(tmp_path))) as browser:
        store = browser.app.state.control_store
        with store._connect() as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert store.authenticate_app_key(key).app_id == "kept"
        assert admin(browser, "apps/kept/keys")["items"][0]["last_used_at"] is None
