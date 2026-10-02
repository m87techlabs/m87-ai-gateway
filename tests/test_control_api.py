import asyncio
import time

import httpx

from m87_gateway.api import routes
from m87_gateway.config import AppConfig, ControlPlaneConfig, GatewaySettings
from m87_gateway.control.api import STATIC_DIR
from m87_gateway.logging import middleware
from m87_gateway.main import create_app


class FakeProvider:
    async def chat_completions(self, payload, model):
        return {
            "id": "chatcmpl-control-test",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"ollama:{model}",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "gateway response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }


def test_console_manages_keys_and_displays_captured_exchange(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "test-admin-key-with-enough-entropy")
    monkeypatch.setattr(routes, "get_provider", lambda provider, settings, store: FakeProvider())

    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(middleware, "run_in_threadpool", inline)
    settings = GatewaySettings(
        apps=[
            AppConfig(
                app_id="bootstrap",
                api_key="bootstrap-key",
                allowed_models=["auto", "ollama:gemma3:1b"],
            )
        ],
        routing={"default_model": "ollama:gemma3:1b"},
        observability={"traffic_log": {"capture_content": True}},
        control_plane=ControlPlaneConfig(
            enabled=True,
            database_path=str(tmp_path / "control.db"),
            master_key_path=str(tmp_path / "master.key"),
        ),
    )
    application = create_app(settings)

    async def scenario():
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
                unauthorized = await client.get("/admin/api/overview")
                assert unauthorized.status_code == 401
                assert unauthorized.headers["content-security-policy"].startswith("default-src")
                headers = {"Authorization": "Bearer test-admin-key-with-enough-entropy"}
                created = await client.post(
                    "/admin/api/apps",
                    headers=headers,
                    json={
                        "app_id": "prayog",
                        "allowed_models": ["auto", "ollama:gemma3:1b"],
                        "capture_content": True,
                    },
                )
                assert created.status_code == 201
                app_key = created.json()["api_key"]

                completion = await client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": f"Bearer {app_key}"},
                    json={
                        "model": "auto",
                        "messages": [{"role": "user", "content": "synthetic prompt"}],
                    },
                )
                assert completion.status_code == 200
                request_id = completion.headers["x-request-id"]

                detail = await client.get(f"/admin/api/logs/{request_id}", headers=headers)
                assert detail.status_code == 200
                event = detail.json()
                assert event["app_id"] == "prayog"
                assert event["total_tokens"] == 5
                assert event["request_content"][0]["content"] == "synthetic prompt"
                assert event["response_content"][0]["message"]["content"] == "gateway response"

                provider = await client.put(
                    "/admin/api/provider-keys",
                    headers=headers,
                    json={"provider": "openai", "alias": "default", "key": "sk-example-only"},
                )
                assert provider.status_code == 204
                listed = await client.get("/admin/api/provider-keys", headers=headers)
                assert "sk-example-only" not in listed.text

                summary = await client.get("/admin/api/overview", headers=headers)
                assert summary.json()["total_tokens"] == 5

    asyncio.run(scenario())
    dashboard = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "Gateway Console" in dashboard
    assert "test-admin-key-with-enough-entropy" not in dashboard
