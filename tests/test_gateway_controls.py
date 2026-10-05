"""Operator authorization, persistent controls, isolation and admission failure cases."""

import asyncio
from datetime import datetime, timedelta, timezone
import sqlite3

import httpx
import pytest

from examples.chat_app.scenarios import exercise
from m87_gateway.api import routes
from m87_gateway.cli import local_settings
from m87_gateway.controls import InFlightLimiter
from m87_gateway.api.errors import GatewayError
from m87_gateway.main import create_app


def test_sample_control_scenarios_over_real_http():
    results = exercise()
    assert len(results) == 12
    assert all(result["passed"] for result in results)


def test_admission_app_isolation_global_limit_and_exception_release():
    limiter = InFlightLimiter()
    with limiter.admit("one", 2, 1):
        with pytest.raises(GatewayError) as failure:
            with limiter.admit("one", 2, 1):
                pytest.fail("Per-app limit bypassed")
        assert failure.value.code == "concurrency_limit_exceeded"
        with limiter.admit("two", 2, None):
            with pytest.raises(GatewayError):
                with limiter.admit("three", 2, None):
                    pytest.fail("Global limit bypassed")
    assert limiter.snapshot()["active_requests"] == 0
    with pytest.raises(RuntimeError):
        with limiter.admit("one", 1, None):
            raise RuntimeError("Synthetic failure")
    with limiter.admit("one", 1, None):
        assert limiter.snapshot()["active_requests"] == 1


def test_operator_controls_authorization_validation_and_restart(tmp_path, monkeypatch):
    admin = "synthetic-operator-key-long-enough"
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", admin)
    settings = local_settings(tmp_path)
    settings.observability.json_logs = False

    async def scenario():
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client:
                for method, path, body in [
                    ("GET", "/controls", None),
                    ("PUT", "/controls", {}),
                    ("GET", "/diagnostics", None),
                    ("POST", "/cache/clear", None),
                    ("DELETE", "/logs", {"confirmation": "DELETE"}),
                    (
                        "PATCH",
                        "/apps/missing/limits",
                        {"rate_limit_per_minute": 1, "max_concurrent_requests": 1},
                    ),
                ]:
                    response = await client.request(method, "/admin/api" + path, json=body)
                    assert response.status_code == 401
                client.headers["Authorization"] = f"Bearer {admin}"
                controls = (await client.get("/admin/api/controls")).json()
                invalid = {**controls, "retention_days": 0}
                assert (await client.put("/admin/api/controls", json=invalid)).status_code == 422
                invalid = {**controls, "retry": {"max_attempts": 6}}
                assert (await client.put("/admin/api/controls", json=invalid)).status_code == 422
                assert (await client.get("/admin/api/controls")).json() == controls
                controls.update(
                    cache={"enabled": True, "ttl_seconds": 7, "max_entries": 2},
                    retention_days=90,
                    limits={
                        "max_concurrent_requests": 2,
                        "queue_max_depth": 3,
                        "queue_max_depth_per_app": 1,
                        "queue_wait_timeout_seconds": 0.5,
                    },
                )
                assert (await client.put("/admin/api/controls", json=controls)).status_code == 204
                assert app.state.response_cache.enabled
                assert app.state.control_store.config.retention_days == 90
                # A saved longer retention must take effect before startup pruning.
                with sqlite3.connect(tmp_path / "control.db") as database:
                    database.execute(
                        "INSERT INTO events(request_id, created_at, status_code, project_id) VALUES (?, ?, ?, ?)",
                        (
                            "old",
                            (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
                            200,
                            "default",
                        ),
                    )
                assert (await client.get("/ready")).status_code == 503
                assert (await client.get("/health")).status_code == 200
        restarted = create_app(settings)
        async with restarted.router.lifespan_context(restarted):
            assert restarted.state.settings.limits.queue_max_depth == 3
            assert restarted.state.settings.limits.queue_wait_timeout_seconds == 0.5
            assert restarted.state.response_cache.enabled
            assert restarted.state.response_cache.ttl_seconds == 7
            assert restarted.state.control_store.get_event("old")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=restarted),
                base_url="http://gateway",
                headers={"Authorization": f"Bearer {admin}"},
            ) as client:
                response = await client.post(
                    "/admin/api/apps", json={"app_id": "one", "allowed_models": ["auto"]}
                )
                key = response.json()["api_key"]
                response = await client.patch(
                    "/admin/api/apps/one/limits",
                    json={"rate_limit_per_minute": 2, "max_concurrent_requests": 1},
                )
                assert response.status_code == 204
                context = restarted.state.control_store.authenticate_app_key(key)
                assert context.rate_limit_per_minute == 2 and context.max_concurrent_requests == 1
                assert (
                    await client.patch(
                        "/admin/api/apps/one/limits",
                        json={"rate_limit_per_minute": 0, "max_concurrent_requests": None},
                    )
                ).status_code == 422
                assert (
                    await client.patch(
                        "/admin/api/apps/missing/limits",
                        json={"rate_limit_per_minute": None, "max_concurrent_requests": None},
                    )
                ).status_code == 404
                assert (
                    await client.request("DELETE", "/admin/api/logs", json={"confirmation": "NO"})
                ).status_code == 422
                assert (
                    await client.request(
                        "DELETE",
                        "/admin/api/logs",
                        json={"confirmation": "DELETE", "project_id": "other"},
                    )
                ).json()["deleted"] == 0
                controls["retention_days"] = 1
                assert (await client.put("/admin/api/controls", json=controls)).status_code == 204
                assert restarted.state.control_store.get_event("old") is None

    asyncio.run(scenario())


def test_inflight_slot_released_when_request_is_cancelled(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-operator-key-long-enough")
    settings = local_settings(tmp_path)
    settings.apps = []
    from m87_gateway.config import AppConfig

    settings.apps.append(
        AppConfig(
            app_id="cancel", api_key="synthetic-app-key", allowed_models=["auto", "ollama:llama3"]
        )
    )
    settings.limits.max_concurrent_requests = 1
    settings.observability.json_logs = False
    entered = asyncio.Event()
    release = asyncio.Event()

    class Provider:
        async def chat_completions(self, payload, model):
            entered.set()
            await release.wait()
            return {
                "id": "test",
                "created": 1,
                "model": "ollama:llama3",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
            }

    monkeypatch.setattr(routes, "get_provider", lambda *args: Provider())

    async def scenario():
        application = create_app(settings)
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://gateway"
            ) as client:
                body = {"model": "auto", "messages": [{"role": "user", "content": "synthetic"}]}
                headers = {"Authorization": "Bearer synthetic-app-key"}
                pending = asyncio.create_task(
                    client.post("/v1/chat/completions", json=body, headers=headers)
                )
                await asyncio.wait_for(entered.wait(), timeout=2)
                assert (
                    await client.post("/v1/chat/completions", json=body, headers=headers)
                ).status_code == 429
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
                assert application.state.inflight_limiter.snapshot()["active_requests"] == 0
                release.set()
                assert (
                    await client.post("/v1/chat/completions", json=body, headers=headers)
                ).status_code == 200

    asyncio.run(scenario())


def test_diagnostics_credential_and_storage_failures_are_safe(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from m87_gateway.control.diagnostics import diagnostics
    from m87_gateway.config import GatewaySettings

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = GatewaySettings(routing={"default_model": "openai:test"})
    state = SimpleNamespace(
        settings=settings, control_store=None, inflight_limiter=InFlightLimiter()
    )
    report = diagnostics(state)
    assert not report["ready"]
    assert any(
        item["name"] == "Provider credential" and not item["ok"] for item in report["checks"]
    )
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret-provider-key")
    assert diagnostics(state)["ready"]
    assert "synthetic-secret-provider-key" not in str(diagnostics(state))

    class BrokenStore:
        def check_storage(self):
            raise OSError("sensitive-path-and-secret")

    state.control_store = BrokenStore()
    report = diagnostics(state)
    assert not report["ready"]
    assert "sensitive-path-and-secret" not in str(report)


def test_project_log_deletion_and_event_write_retention(tmp_path):
    from m87_gateway.control.store import LocalControlStore

    store = LocalControlStore(local_settings(tmp_path).control_plane)
    now = datetime.now(timezone.utc)

    def event(request_id, project_id, created_at):
        return {
            "request_id": request_id,
            "project_id": project_id,
            "created_at": created_at.isoformat(),
            "status_code": 200,
            "provider_attempted": False,
            "request_content_truncated": False,
            "response_content_truncated": False,
        }

    store.emit(event("one", "one", now))
    store.emit(event("two", "two", now))
    assert store.delete_events("one") == 1
    assert store.get_event("one") is None and store.get_event("two")
    # Old history arriving on a write is pruned without waiting for a restart.
    store.emit(event("expired", "two", now - timedelta(days=31)))
    assert store.get_event("expired") is None
    assert store.get_event("two")
