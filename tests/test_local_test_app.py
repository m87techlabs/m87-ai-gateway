import json

import httpx
from fastapi.testclient import TestClient

from examples.local_test_app.app import LocalTestSettings, create_app

APP_KEY = "synthetic-local-relay-key"
REQUEST_ID = "local-flow-request-id"


def settings() -> LocalTestSettings:
    return LocalTestSettings(
        gateway_url="http://gateway.example.invalid",
        gateway_api_key=APP_KEY,
    )


def test_ui_and_status_keep_gateway_key_server_side():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"status": "ok"})

    app = create_app(settings(), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Gateway Flow Lab" in page.text
        assert APP_KEY not in page.text
        assert "default-src 'self'" in page.headers["content-security-policy"]

        status = client.get("/api/status")
        assert status.status_code == 200
        assert status.json()["gateway"] == "reachable"
        assert APP_KEY not in status.text


def test_chat_forwards_supported_payload_and_correlation():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {APP_KEY}"
        payload = json.loads(request.content)
        assert payload == {
            "model": "auto",
            "messages": [
                {"role": "system", "content": "Answer briefly"},
                {"role": "user", "content": "Synthetic question"},
            ],
            "temperature": 0.3,
            "max_tokens": 64,
            "stream": False,
        }
        return httpx.Response(
            200,
            headers={"X-Request-ID": REQUEST_ID},
            json={
                "model": "ollama:test-model",
                "choices": [{"message": {"role": "assistant", "content": "Synthetic answer"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    app = create_app(settings(), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "prompt": "Synthetic question",
                "system_prompt": "Answer briefly",
                "model": "auto",
                "temperature": 0.3,
                "max_tokens": 64,
            },
        )
    assert response.status_code == 200
    assert response.headers["x-request-id"] == REQUEST_ID
    body = response.json()
    assert body.pop("latency_ms") >= 0
    assert body == {
        "ok": True,
        "content": "Synthetic answer",
        "model": "ollama:test-model",
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        "request_id": REQUEST_ID,
    }
    assert APP_KEY not in response.text


def test_gateway_failure_is_bounded_and_correlated():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            headers={"X-Request-ID": REQUEST_ID},
            json={
                "error": {
                    "message": "Model provider could not complete the request",
                    "type": "gateway_error",
                    "code": "provider_error",
                },
                "request_id": REQUEST_ID,
                "unexpected": "private upstream detail",
            },
        )

    app = create_app(settings(), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"prompt": "Synthetic question"})
    assert response.status_code == 502
    assert response.headers["x-request-id"] == REQUEST_ID
    assert response.json()["error"]["code"] == "provider_error"
    assert "private upstream detail" not in response.text


def test_invalid_request_does_not_echo_input_or_call_gateway():
    sensitive = "synthetic-private-value"

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Gateway must not be called")

    app = create_app(settings(), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"prompt": sensitive, "model": "unsupported-model"},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert sensitive not in response.text


def test_oversized_declared_body_stops_before_gateway():
    app = create_app(
        settings(),
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(AssertionError("Gateway must not be called"))
        ),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            headers={"Content-Length": str(129 * 1024), "Content-Type": "application/json"},
            content=b"{}",
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_large"
