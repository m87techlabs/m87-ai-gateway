import json

from fastapi.testclient import TestClient
import httpx
import pytest

from examples.chat_app.app import Settings, create_app

KEY = "synthetic-sample-application-key"


def client(handler):
    return TestClient(
        create_app(
            Settings(gateway_url="http://gateway.example.invalid", app_key=KEY),
            transport=httpx.MockTransport(handler),
        ),
        base_url="http://127.0.0.1:8790",
    )


def completion(usage=None):
    return {
        "model": "custom_adapter:sample",
        "choices": [{"message": {"content": "Synthetic answer"}}],
        "usage": usage,
    }


def test_sample_keeps_key_on_server_and_forwards_conversation():
    def handler(request):
        if request.url.path == "/health":
            assert "authorization" not in request.headers
            return httpx.Response(200, json={"status": "ok"})
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["messages"] == conversation
        assert body["model"] == "auto"
        assert body["stream"] is False
        return httpx.Response(
            200,
            json=completion({"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13}),
            headers={"X-Request-ID": "sample-request"},
        )

    conversation = [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer"},
        {"role": "user", "content": "Follow-up question"},
    ]
    with client(handler) as browser:
        for path in ("/", "/assets/app.js", "/assets/styles.css", "/api/status"):
            response = browser.get(path)
            assert response.status_code == 200
            assert KEY not in response.text
            assert response.headers["cache-control"] == "no-store"
        assert browser.get("/api/status").json()["gateway_reachable"] is True
        response = browser.post("/api/chat", json={"messages": conversation})
        assert response.status_code == 200
        assert response.json()["content"] == "Synthetic answer"
        assert response.json()["usage"]["total_tokens"] == 13
        assert response.json()["model"] == "custom_adapter:sample"
        assert response.headers["x-request-id"] == "sample-request"
        assert response.json()["latency_ms"] >= 0
        assert KEY not in response.text


@pytest.mark.parametrize("status", [401, 403, 429, 502, 302])
def test_gateway_failures_are_safe_and_correlated(status):
    with client(
        lambda request: httpx.Response(
            status, text=KEY, headers={"X-Request-ID": "failure-request"}
        )
    ) as browser:
        response = browser.post("/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
    assert response.status_code == (502 if status == 302 else status)
    assert response.json()["request_id"] == "failure-request"
    assert KEY not in response.text


@pytest.mark.parametrize("timeout", [False, True])
def test_connection_and_timeout_errors(timeout):
    def handler(request):
        exception = httpx.ReadTimeout if timeout else httpx.ConnectError
        raise exception(KEY, request=request)

    with client(handler) as browser:
        assert browser.get("/api/status").json()["gateway_reachable"] is False
        response = browser.post("/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
        assert response.status_code == (504 if timeout else 502)
        assert KEY not in response.text


def test_unknown_usage_and_malformed_gateway_response():
    with client(lambda request: httpx.Response(200, json=completion())) as browser:
        response = browser.post("/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
        assert response.json()["usage"] == {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }
    with client(lambda request: httpx.Response(200, json={"choices": []})) as browser:
        response = browser.post("/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
        assert response.status_code == 502


def test_cross_origin_and_invalid_conversations_never_reach_gateway():
    def handler(request):
        pytest.fail("Rejected input reached the gateway")

    with client(handler) as browser:
        assert (
            browser.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Hi"}]},
                headers={"Origin": "https://other.example.invalid"},
            ).status_code
            == 403
        )
        assert browser.get("/", headers={"Host": "other.example.invalid"}).status_code == 400
        for messages in (
            [],
            [{"role": "assistant", "content": "Not a question"}],
            [{"role": "user", "content": "x" * 8193}],
            [{"role": "user", "content": "Hi"}] * 32,
        ):
            assert browser.post("/api/chat", json={"messages": messages}).status_code == 422
        assert browser.post("/api/chat", content="x" * (128 * 1024 + 1)).status_code == 413


def test_settings_reject_missing_key_and_credentialed_url():
    with pytest.raises(ValueError):
        Settings().validate()
    with pytest.raises(ValueError):
        Settings(gateway_url="http://secret@gateway.example.invalid", app_key=KEY).validate()
    Settings(app_key=KEY, model="extension:sample").validate()
