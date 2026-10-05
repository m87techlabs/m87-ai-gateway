from legacy_backend import schema_two_identities
import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from m87_gateway.api import routes
from m87_gateway.config import ControlPlaneConfig, GatewaySettings
from m87_gateway.control import LocalControlStore
from m87_gateway.main import create_app
from m87_gateway.logging.audit import AuditRecorder
from m87_gateway.metrics import GatewayMetrics


def control(tmp_path):
    return LocalControlStore(
        ControlPlaneConfig(
            enabled=True,
            database_path=str(tmp_path / "control.db"),
            master_key_path=str(tmp_path / "master.key"),
        )
    )


def exchange(identifier, project="default", **updates):
    item = {
        "request_id": identifier,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project,
        "app_id": "sample-app",
        "routed_model": "ollama:small",
        "provider": "ollama",
        "status_code": 200,
        "latency_ms": 25,
        "prompt_tokens": 6,
        "completion_tokens": 4,
        "total_tokens": 10,
        "provider_attempted": True,
        "provider_attempts": 1,
    }
    item.update(updates)
    return item


def test_project_usage_excludes_cache_duplicates_and_respects_window(tmp_path):
    store = control(tmp_path)
    store.create_project("alpha", "Alpha")
    store.create_project("beta", "Beta")
    store.emit(exchange("alpha-live", "alpha"))
    store.emit(
        exchange(
            "alpha-cache",
            "alpha",
            cache_status="hit",
            provider_attempted=False,
            provider_attempts=0,
        )
    )
    store.emit(
        exchange(
            "alpha-unknown", "alpha", prompt_tokens=None, completion_tokens=None, total_tokens=None
        )
    )
    store.emit(
        exchange(
            "alpha-rejected",
            "alpha",
            status_code=429,
            provider_attempted=False,
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
        )
    )
    store.emit(exchange("beta-live", "beta", total_tokens=100))
    store.emit(
        exchange(
            "old-alpha",
            "alpha",
            created_at=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
        )
    )
    store.emit(
        exchange(
            "future-alpha",
            "alpha",
            created_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        )
    )
    summary = store.overview(project_id="alpha")
    assert summary["requests"] == 4
    assert summary["total_tokens"] == 10
    assert summary["prompt_tokens"] == 6
    assert summary["completion_tokens"] == 4
    assert summary["cache_hits"] == 1
    assert summary["errors"] == 1
    assert summary["usage_unknown"] == 1
    usage = store.usage(project_id="alpha")
    assert len(usage["series"]) == 25
    assert sum(row["total_tokens"] for row in usage["series"]) == 10
    assert sum(row["requests"] for row in usage["series"]) == 4
    assert usage["by_app"][0]["total_tokens"] == 10
    assert usage["by_model"][0]["model"] == "ollama:small"
    assert {row["project_id"] for row in store.export_events(project_id="beta")} == {"beta"}
    assert store.overview(project_id="missing")["requests"] == 0


def test_project_movement_does_not_rewrite_historical_usage(tmp_path):
    store = control(tmp_path)
    store.create_project("alpha", "Alpha")
    _, key = store.create_app_key("sample-app", ["auto"], False)
    store.emit(exchange("before"))
    assert store.assign_app_project("sample-app", "alpha")
    assert store.authenticate_app_key(key).project_id == "alpha"
    assert store.get_event("before")["project_id"] == "default"
    assert store.list_projects()[1]["app_count"] == 1
    with pytest.raises(ValueError, match="Project does not exist"):
        store.assign_app_project("sample-app", "unknown")
    assert store.authenticate_app_key(key).project_id == "alpha"
    with pytest.raises(ValueError, match="Project does not exist"):
        store.create_app_key("unknown-app", ["auto"], False, project_id="unknown")
    assert len(store.list_apps()) == 1
    assert not store.assign_app_project("missing-app", "alpha")


def test_legacy_migration_preserves_keys_and_attributes_only_authenticated_events(tmp_path):
    store = control(tmp_path)
    _, key = store.create_app_key("sample-app", ["auto"], False)
    store.put_provider_key("openai", "synthetic-provider-secret")
    store.emit(exchange("legacy-authenticated"))
    store.emit(exchange("legacy-anonymous", app_id=None, project_id=None, status_code=401))
    with sqlite3.connect(tmp_path / "control.db") as connection:
        schema_two_identities(connection)
        connection.execute("DROP INDEX events_project_created")
        connection.execute("ALTER TABLE events DROP COLUMN project_id")
        connection.execute("ALTER TABLE app_keys DROP COLUMN project_id")
        connection.execute("DROP TABLE projects")
    upgraded = control(tmp_path)
    assert upgraded.authenticate_app_key(key).project_id == "default"
    assert upgraded.get_provider_key("openai") == "synthetic-provider-secret"
    assert upgraded.get_event("legacy-authenticated")["project_id"] == "default"
    assert upgraded.get_event("legacy-anonymous")["project_id"] is None
    assert upgraded.overview(project_id="default")["requests"] == 1


class FakeProvider:
    async def chat_completions(self, payload, model):
        return {
            "id": "chatcmpl-project",
            "object": "chat.completion",
            "created": 1,
            "model": f"ollama:{model}",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "synthetic answer"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
        }


def test_project_apis_use_key_attribution_and_filter_usage_logs_and_export(tmp_path, monkeypatch):
    admin = "synthetic-operator-key-with-enough-entropy"
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", admin)
    monkeypatch.setattr(routes, "get_provider", lambda *args: FakeProvider())
    settings = GatewaySettings(
        routing={"default_model": "ollama:small"},
        cache={"enabled": True},
        control_plane={
            "enabled": True,
            "database_path": str(tmp_path / "control.db"),
            "master_key_path": str(tmp_path / "master.key"),
        },
    )
    application = create_app(settings)

    async def scenario():
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://gateway"
            ) as client:
                headers = {"Authorization": f"Bearer {admin}"}
                assert (await client.get("/admin/api/projects")).status_code == 401
                assert (await client.get("/admin/api/usage")).status_code == 401
                for project in ("alpha", "beta"):
                    payload = {"project_id": project, "name": project.title()}
                    assert (
                        await client.post("/admin/api/projects", json=payload)
                    ).status_code == 401
                    assert (
                        await client.post("/admin/api/projects", json=payload, headers=headers)
                    ).status_code == 201
                assert (
                    await client.post(
                        "/admin/api/projects",
                        headers=headers,
                        json={"project_id": "alpha", "name": "Duplicate"},
                    )
                ).status_code == 409
                assert (
                    await client.post(
                        "/admin/api/projects",
                        headers=headers,
                        json={"project_id": "invalid id", "name": "Bad"},
                    )
                ).status_code == 422
                assert (
                    await client.post(
                        "/admin/api/projects",
                        headers=headers,
                        json={"project_id": "empty", "name": " "},
                    )
                ).status_code == 422
                unknown_app = {
                    "app_id": "unknown",
                    "allowed_models": ["auto"],
                    "project_id": "missing",
                }
                assert (
                    await client.post("/admin/api/apps", headers=headers, json=unknown_app)
                ).status_code == 422
                created = await client.post(
                    "/admin/api/apps",
                    headers=headers,
                    json={
                        "app_id": "sample-app",
                        "allowed_models": ["auto", "ollama:small"],
                        "project_id": "alpha",
                    },
                )
                key = created.json()["api_key"]
                body = {"model": "auto", "messages": [{"role": "user", "content": "test"}]}
                app_headers = {"Authorization": f"Bearer {key}", "X-Project-ID": "beta"}
                first = await client.post("/v1/chat/completions", headers=app_headers, json=body)
                assert first.status_code == 200
                request_id = first.headers["x-request-id"]
                detail = await client.get("/admin/api/logs/" + request_id, headers=headers)
                assert detail.json()["project_id"] == "alpha"
                path = "/admin/api/apps/sample-app/project"
                assert (await client.patch(path, json={"project_id": "beta"})).status_code == 401
                assert (
                    await client.patch(path, json={"project_id": "missing"}, headers=headers)
                ).status_code == 422
                assert (
                    await client.patch(path, json={"project_id": "beta"}, headers=headers)
                ).status_code == 204
                second = await client.post("/v1/chat/completions", headers=app_headers, json=body)
                assert second.headers["x-gateway-cache"] == "HIT"
                summary = (
                    await client.get("/admin/api/overview?project_id=beta", headers=headers)
                ).json()
                assert summary["requests"] == 1
                assert summary["total_tokens"] == 0
                assert summary["cache_hits"] == 1
                for endpoint in ("/logs", "/logs/export"):
                    response = await client.get(
                        "/admin/api" + endpoint + "?project_id=alpha", headers=headers
                    )
                    items = response.json()["items"] if endpoint == "/logs" else response.json()
                    assert len(items) == 1
                    assert items[0]["request_id"] == request_id
                usage = (
                    await client.get("/admin/api/usage?project_id=alpha", headers=headers)
                ).json()
                assert usage["by_app"][0]["total_tokens"] == 10
                assert (
                    await client.get("/admin/api/usage?project_id=invalid%20id", headers=headers)
                ).status_code == 422
        restarted = create_app(settings)
        async with restarted.router.lifespan_context(restarted):
            assert restarted.state.control_store.authenticate_app_key(key).project_id == "beta"
            assert restarted.state.control_store.get_event(request_id)["project_id"] == "alpha"

    asyncio.run(scenario())


def test_yaml_project_is_available_in_console_and_authentication(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-operator-key-with-enough-entropy")
    settings = GatewaySettings(
        apps=[
            {
                "app_id": "configured",
                "api_key": "synthetic-app-key",
                "project_id": "research",
                "allowed_models": ["auto"],
            }
        ],
        control_plane={
            "enabled": True,
            "database_path": str(tmp_path / "control.db"),
            "master_key_path": str(tmp_path / "master.key"),
        },
    )
    application = create_app(settings)

    async def scenario():
        async with application.router.lifespan_context(application):
            assert any(
                project["project_id"] == "research"
                for project in application.state.control_store.list_projects()
            )
            assert settings.app_for_api_key("synthetic-app-key").project_id == "research"

    asyncio.run(scenario())


def test_public_project_identity_survives_key_pattern_redaction(tmp_path):
    store = control(tmp_path)
    settings = GatewaySettings(observability={"json_logs": False})
    recorder = AuditRecorder(settings, GatewayMetrics(), store)
    try:
        recorder.record(
            exchange("public-id", "m87_public_project", app_id="m87_public_application"),
            request_content=[{"role": "user", "content": "m87_unknown_secret_value"}],
        )
        event = store.get_event("public-id")
        assert event["project_id"] == "m87_public_project"
        assert event["app_id"] == "m87_public_application"
        assert event["request_content"][0]["content"] == "[REDACTED]"
        recorder.add_secret("m87_known_secret_value")
        recorder.record(exchange("known-secret-id", "m87_known_secret_value"))
        assert store.get_event("known-secret-id")["project_id"] == "[REDACTED]"
    finally:
        recorder.close()
