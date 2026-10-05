import asyncio
import json

import httpx
import pytest
import m87_gateway.adapters as registry

from m87_gateway.adapters import Adapter, register_adapter
from m87_gateway.cli import local_settings, operator_key
from m87_gateway.config import load_settings
from m87_gateway.config.settings import ProviderConfig
from m87_gateway.main import create_app
from m87_gateway.providers.factory import get_provider
from m87_gateway.providers.openai import OpenAICompatibleProvider


def test_local_launcher_has_no_demo_access_and_persists_private_operator_key(tmp_path):
    settings = local_settings(tmp_path)
    assert not settings.configured_apps
    assert settings.server.host == "127.0.0.1"
    assert settings.control_plane.enabled
    assert not settings.providers.ollama.enabled
    key = operator_key(tmp_path)
    assert len(key) >= 24
    assert operator_key(tmp_path) == key
    assert (tmp_path / "admin.key").stat().st_mode & 0o077 == 0


def test_source_adapter_registration_config_and_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "_registry", registry.adapters())
    register_adapter(Adapter("extension_test", "Example", lambda config, key: (config, key)))
    with pytest.raises(ValueError, match="already registered"):
        register_adapter(Adapter("extension_test", "Duplicate", lambda *args: None))
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""providers:
  custom:
    extension_test:
      base_url_env: EXTENSION_TEST_URL
routing:
  default_model: extension_test:small
""")
    monkeypatch.setenv("EXTENSION_TEST_URL", "http://localhost:9000/v1")
    settings = load_settings(config_path)
    config, key = get_provider("extension_test", settings)
    assert config.base_url == "http://localhost:9000/v1"
    assert key is None


def test_compatible_adapter_preserves_usage_and_optional_auth(monkeypatch):
    original = httpx.AsyncClient
    requests = []

    def upstream(request):
        requests.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "small"}]})
        assert json.loads(request.content)["model"] == "small"
        return httpx.Response(200, json={"model": "small", "usage": None})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(upstream), **kw)
    )
    from m87_gateway.api.schemas import ChatCompletionRequest

    async def scenario():
        provider = OpenAICompatibleProvider(ProviderConfig(base_url="http://localhost:9000/v1"))
        assert await provider.list_models() == ["small"]
        data = await provider.chat_completions(
            ChatCompletionRequest(
                model="openai_compatible:small", messages=[{"role": "user", "content": "test"}]
            ),
            "small",
        )
        assert data["model"] == "openai_compatible:small"
        assert data["usage"] is None
        assert all("authorization" not in request.headers for request in requests)
        provider.api_key = "synthetic-provider-key"
        await provider.list_models()
        assert requests[-1].headers["authorization"] == "Bearer synthetic-provider-key"

    asyncio.run(scenario())


def test_setup_persists_connection_route_and_credentials_and_enforces_safety(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-operator-key-long-enough")
    settings = local_settings(tmp_path)
    headers = {"Authorization": "Bearer synthetic-operator-key-long-enough"}
    original = httpx.AsyncClient
    upstream_requests = []

    def upstream(request):
        upstream_requests.append(request)
        assert request.headers["authorization"] == "Bearer synthetic-provider-key"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "small"}]})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-setup",
                "object": "chat.completion",
                "created": 1,
                "model": "small",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "synthetic output"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            },
        )

    def client(**kwargs):
        if "transport" not in kwargs:
            kwargs["transport"] = httpx.MockTransport(upstream)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)

    async def scenario():
        application = create_app(settings)
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://gateway"
            ) as client:
                payload = {
                    "config": {"base_url": "http://localhost:9000/v1"},
                    "key": "synthetic-provider-key",
                }
                path = "/admin/api/connections/openai_compatible"
                assert (await client.put(path, json=payload)).status_code == 401
                assert (await client.put(path, headers=headers, json=payload)).status_code == 204
                assert (
                    await client.put(
                        path, headers=headers, json={"config": payload["config"], "key": "tiny"}
                    )
                ).status_code == 422
                assert (
                    await client.put(path, headers=headers, json={"config": payload["config"]})
                ).status_code == 204
                assert (
                    application.state.control_store.get_provider_key("openai_compatible")
                    == "synthetic-provider-key"
                )
                setup = await client.get("/admin/api/setup", headers=headers)
                assert "synthetic-provider-key" not in setup.text
                models = await client.get(path + "/models", headers=headers)
                assert models.json() == {"items": ["openai_compatible:small"]}
                assert (
                    await client.put(
                        "/admin/api/setup",
                        headers=headers,
                        json={"default_model": "openai_compatible:small", "capture_content": True},
                    )
                ).status_code == 204
                app = await client.post(
                    "/admin/api/apps",
                    headers=headers,
                    json={
                        "app_id": "test-app",
                        "allowed_models": ["auto", "openai_compatible:small"],
                        "capture_content": True,
                        "rate_limit_per_minute": 1,
                    },
                )
                key = app.json()["api_key"]
                body = {"model": "auto", "messages": [{"role": "user", "content": "test"}]}
                result = await client.post(
                    "/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}
                )
                assert result.status_code == 200
                assert result.json()["usage"]["total_tokens"] == 6
                detail = await client.get(
                    "/admin/api/logs/" + result.headers["x-request-id"], headers=headers
                )
                assert (
                    detail.json()["response_content"][0]["message"]["content"] == "synthetic output"
                )
                result = await client.post(
                    "/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}
                )
                assert result.status_code == 429
                unsafe = {"config": {"base_url": "http://localhost:9001/v1"}}
                assert (await client.put(path, headers=headers, json=unsafe)).status_code == 409
                assert application.state.settings.providers.openai_compatible.base_url.endswith(
                    "9000/v1"
                )
                unsafe["clear_key"] = True
                assert (await client.put(path, headers=headers, json=unsafe)).status_code == 204
                assert application.state.control_store.get_provider_key("openai_compatible") is None
        restarted = create_app(settings)
        async with restarted.router.lifespan_context(restarted):
            active = restarted.state.settings
            assert active.routing.default_model == "openai_compatible:small"
            assert active.providers.openai_compatible.base_url.endswith("9001/v1")
            assert active.observability.traffic_log.capture_content
            assert restarted.state.control_store.authenticate_app_key(key).app_id == "test-app"

    asyncio.run(scenario())
    assert b"synthetic-provider-key" not in (tmp_path / "control.db").read_bytes()
    assert len(upstream_requests) == 2


@pytest.mark.parametrize("outcome", ["models", "empty", "network", "timeout", "auth", "invalid"])
def test_draft_connection_probe_reports_outcome_without_saving(tmp_path, monkeypatch, outcome):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-operator-key-long-enough")
    original = httpx.AsyncClient
    requests = []

    def upstream(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/api/tags"
        assert request.headers["authorization"] == "Bearer synthetic-draft-secret"
        if outcome == "network":
            raise httpx.ConnectError("private upstream information", request=request)
        if outcome == "timeout":
            raise httpx.ReadTimeout("private upstream information", request=request)
        if outcome == "auth":
            return httpx.Response(401, text="private upstream information")
        if outcome == "invalid":
            return httpx.Response(200, json={"private": "private upstream information"})
        return httpx.Response(
            200, json={"models": [{"name": "small"}] if outcome == "models" else []}
        )

    def client(**kwargs):
        if "transport" not in kwargs:
            assert kwargs["timeout"] == 10
            kwargs["transport"] = httpx.MockTransport(upstream)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)

    async def scenario():
        application = create_app(local_settings(tmp_path))
        async with application.router.lifespan_context(application):
            store = application.state.control_store
            before = store.runtime_config()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://gateway"
            ) as browser:
                payload = {
                    "config": {"base_url": "http://inference.invalid:11434", "enabled": False},
                    "key": "synthetic-draft-secret",
                }
                path = "/admin/api/connections/ollama/test"
                assert (await browser.post(path, json=payload)).status_code == 401
                assert not requests
                response = await browser.post(
                    path,
                    json=payload,
                    headers={"Authorization": "Bearer synthetic-operator-key-long-enough"},
                )
                assert response.status_code == 200
                result = response.json()
                assert result["ok"] == (outcome in {"models", "empty"})
                assert result["latency_ms"] >= 0
                if result["ok"]:
                    assert result["model_count"] == (1 if outcome == "models" else 0)
                assert "private upstream information" not in response.text
                assert "synthetic-draft-secret" not in response.text
                assert store.runtime_config() == before
                assert not application.state.settings.providers.ollama.enabled
                assert store.get_provider_key("ollama") is None
                assert len(requests) == 1

    asyncio.run(scenario())


def test_probe_reuses_keys_only_at_saved_endpoint_and_never_replaces_them(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-operator-key-long-enough")
    original = httpx.AsyncClient
    requests = []

    def upstream(request):
        requests.append(request)
        return httpx.Response(200, json={"models": []})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(upstream), **kwargs),
    )
    headers = {"Authorization": "Bearer synthetic-operator-key-long-enough"}
    with TestClient(create_app(local_settings(tmp_path))) as browser:
        path = "/admin/api/connections/ollama"
        payload = {
            "config": {"base_url": "http://saved.invalid:11434"},
            "key": "synthetic-stored-key",
        }
        assert browser.put(path, json=payload, headers=headers).status_code == 204
        store = browser.app.state.control_store
        before = store.runtime_config()
        same = {"config": payload["config"]}
        assert browser.post(path + "/test", json=same, headers=headers).json()["ok"]
        assert requests[-1].headers["authorization"] == "Bearer synthetic-stored-key"
        changed = {"config": {"base_url": "http://other.invalid:11434"}}
        assert browser.post(path + "/test", json=changed, headers=headers).status_code == 409
        assert len(requests) == 1
        changed["clear_key"] = True
        assert browser.post(path + "/test", json=changed, headers=headers).json()["ok"]
        assert "authorization" not in requests[-1].headers
        changed["key"] = "synthetic-new-key"
        assert browser.post(path + "/test", json=changed, headers=headers).json()["ok"]
        assert requests[-1].headers["authorization"] == "Bearer synthetic-new-key"
        assert store.get_provider_key("ollama") == "synthetic-stored-key"
        assert store.runtime_config() == before
        assert (
            browser.post(
                "/admin/api/connections/unknown/test", json=same, headers=headers
            ).status_code
            == 400
        )
        assert (
            browser.post(
                "/admin/api/connections/openai/test",
                json={"config": {"base_url": "https://api.openai.com/v1"}},
                headers=headers,
            ).status_code
            == 422
        )
        assert len(requests) == 3
