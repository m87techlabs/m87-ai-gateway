"""Real TCP disconnects cancel upstream HTTP work and release gateway admission."""

import asyncio
import json
import socket
import threading
import time
from urllib.parse import urlsplit
from contextlib import ExitStack
from examples.chat_app.app import Settings, create_app as sample_app

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from examples.chat_app.scenarios import serving
from m87_gateway.cli import local_settings
from m87_gateway.config import GatewaySettings
from m87_gateway.main import create_app


@pytest.mark.parametrize("use_sample", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
def test_real_disconnect_cancels_backend_and_records_one_outcome(
    tmp_path, monkeypatch, streaming, use_sample
):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-disconnect-operator-key")
    entered, closed = threading.Event(), threading.Event()
    backend = FastAPI()

    @backend.post("/api/chat")
    async def inference(request: Request):
        body = await request.json()
        entered.set()
        if body["stream"]:

            async def generate():
                try:
                    yield (
                        json.dumps({"message": {"content": "synthetic fragment"}, "done": False})
                        + "\n"
                    )
                    await asyncio.sleep(20)
                finally:
                    closed.set()

            return StreamingResponse(generate(), media_type="application/x-ndjson")
        for _ in range(1000):
            if await request.is_disconnected():
                closed.set()
                return JSONResponse({"message": {"content": "cancelled"}})
            await asyncio.sleep(0.01)
        raise AssertionError("Upstream connection did not close")

    with serving(backend) as backend_url:
        settings = local_settings(tmp_path)
        settings = GatewaySettings.model_validate(
            {
                **settings.model_dump(),
                "apps": [
                    {
                        "app_id": "disconnect-test",
                        "api_key": "synthetic-disconnect-key",
                        "allowed_models": ["ollama:test"],
                    }
                ],
                "routing": {"default_model": "ollama:test"},
                "providers": {"ollama": {"base_url": backend_url, "timeout_seconds": 30}},
                "observability": {"json_logs": False, "traffic_log": {"capture_content": True}},
                "limits": {"max_concurrent_requests": 1},
            }
        )
        gateway = create_app(settings)
        with ExitStack() as servers:
            gateway_url = servers.enter_context(serving(gateway))
            url = (
                servers.enter_context(
                    serving(
                        sample_app(
                            Settings(
                                gateway_url=gateway_url,
                                app_key="synthetic-disconnect-key",
                                model="ollama:test",
                            )
                        )
                    )
                )
                if use_sample
                else gateway_url
            )
            path = (
                ("/api/chat/stream" if streaming else "/api/chat")
                if use_sample
                else "/v1/chat/completions"
            )
            payload = {
                "model": "ollama:test",
                "messages": [{"role": "user", "content": "synthetic prompt"}],
                "stream": streaming,
            }
            if use_sample:
                payload = {"messages": payload["messages"]}
            if streaming:
                with httpx.Client(timeout=5, trust_env=False) as client:
                    with client.stream(
                        "POST",
                        url + path,
                        json=payload,
                        headers={"Authorization": "Bearer synthetic-disconnect-key"},
                    ) as response:
                        assert response.status_code == 200
                        request_id = response.headers["x-request-id"]
                        line = next(
                            line for line in response.iter_lines() if line.startswith("data:")
                        )
                        assert "synthetic fragment" in line
                        assert gateway.state.inflight_limiter.snapshot()["active_requests"] == 1
            else:
                target = urlsplit(url)
                body = json.dumps(payload).encode()
                with socket.create_connection(
                    (target.hostname, target.port), timeout=5
                ) as connection:
                    headers = (
                        f"POST {path} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer synthetic-disconnect-key\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
                    ).encode()
                    connection.sendall(headers + body)
                    assert entered.wait(timeout=3)
                    assert gateway.state.inflight_limiter.snapshot()["active_requests"] == 1
            assert closed.wait(timeout=3), "Gateway did not close the upstream HTTP request"
            for _ in range(200):
                events = gateway.state.control_store.list_events()
                if events and gateway.state.inflight_limiter.snapshot()["active_requests"] == 0:
                    break
                time.sleep(0.01)
            else:
                pytest.fail("Disconnect cleanup or event recording did not finish")
            assert len(events) == 1
            event = gateway.state.control_store.get_event(events[0]["request_id"])
            assert event["status_code"] == 499
            assert event["error_type"] == "client_disconnected"
            assert event["request_outcome"] == "cancelled"
            assert event["total_tokens"] is None
            metrics = gateway.state.metrics.render().decode()
            assert 'm87_gateway_cancellations_total{provider="ollama"} 1.0' in metrics
            assert 'm87_gateway_provider_errors_total{provider="ollama"}' not in metrics
            assert bool(event["streaming"]) is streaming
            assert event["http_status_code"] == (200 if streaming else None)
            if streaming:
                assert event["request_id"] == request_id
                assert event["response_content_partial"]
                assert "synthetic fragment" in str(event["response_content"])
            assert gateway.state.inflight_limiter.snapshot() == {
                "active_requests": 0,
                "queued_requests": 0,
            }
