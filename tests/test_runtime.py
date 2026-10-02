import json

import httpx
import pytest
from fastapi.testclient import TestClient

from m87_gateway.config import load_settings
from m87_gateway.main import create_app

APP_KEY = "synthetic-app-credential"
HEADERS = {"Authorization": f"Bearer {APP_KEY}"}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    import yaml

    def build(overrides=None, handler=None):
        data = {
            "apps": [
                {
                    "app_id": "test-app",
                    "api_key": APP_KEY,
                    "allowed_models": ["auto", "ollama:test", "openai:test"],
                }
            ],
            "routing": {"default_model": "ollama:test"},
            "guardrails": {"blocklist": {"blocked_terms": ["restricted phrase"]}},
        }
        if overrides:
            data.update(overrides)
        path = tmp_path / "settings.yaml"
        path.write_text(yaml.safe_dump(data))
        settings = load_settings(path)
        if handler is None:

            def handler(request):
                return httpx.Response(
                    200,
                    json={
                        "message": {"role": "assistant", "content": "synthetic response"},
                        "prompt_eval_count": 3,
                        "eval_count": 2,
                    },
                )

        original = httpx.AsyncClient
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: original(
                transport=httpx.MockTransport(handler),
                **kwargs,
            ),
        )
        return create_app(settings)

    return build


def chat(client, **kwargs):
    payload = {"model": "auto", "messages": [{"role": "user", "content": "synthetic prompt"}]}
    payload.update(kwargs)
    return client.post("/v1/chat/completions", headers=HEADERS, json=payload)


def test_ollama_preserves_messages_options_and_real_usage(runtime):
    def handler(request):
        assert str(request.url) == "http://localhost:11434/api/chat"
        body = json.loads(request.content)
        assert body["messages"] == [
            {"role": "system", "content": "system instructions"},
            {"role": "user", "content": "question"},
        ]
        assert body["options"] == {"temperature": 0.2, "num_predict": 12}
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={
                "message": {"content": "answer"},
                "prompt_eval_count": 7,
                "eval_count": 3,
            },
        )

    with TestClient(runtime(handler=handler)) as client:
        response = chat(
            client,
            messages=[
                {"role": "system", "content": "system instructions"},
                {"role": "user", "content": "question"},
            ],
            temperature=0.2,
            max_tokens=12,
        )
        assert response.status_code == 200
        assert response.json()["usage"]["total_tokens"] == 10
        assert response.json()["model"] == "ollama:test"
        assert response.headers["x-request-id"]
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert 'm87_gateway_tokens_total{kind="prompt",provider="ollama"} 7.0' in metrics.text
        assert response.headers["x-request-id"] not in metrics.text
        assert "question" not in metrics.text


def test_auto_requires_resolved_target_permission(runtime):
    app = runtime(
        {
            "apps": [
                {
                    "app_id": "test-app",
                    "api_key": APP_KEY,
                    "allowed_models": ["auto"],
                }
            ]
        },
        handler=lambda request: pytest.fail("Provider must not be called"),
    )
    with TestClient(app) as client:
        response = chat(client)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "model_not_allowed"


def test_task_rule_requires_target_permission(runtime):
    app = runtime(
        {
            "apps": [
                {
                    "app_id": "test-app",
                    "api_key": APP_KEY,
                    "allowed_models": ["auto", "ollama:test"],
                }
            ],
            "routing": {
                "default_model": "ollama:test",
                "rules": [{"when_task": "code", "route_to": "openai:test"}],
            },
        },
        handler=lambda request: pytest.fail("Provider must not be called"),
    )
    with TestClient(app) as client:
        assert chat(client, task="code").status_code == 403


def test_rule_and_custom_openai_config(runtime, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_PROVIDER_KEY", "synthetic-provider-credential")

    def handler(request):
        assert str(request.url) == "https://provider.example.invalid/custom/chat/completions"
        assert request.headers["authorization"] == "Bearer synthetic-provider-credential"
        body = json.loads(request.content)
        assert body["model"] == "test"
        assert "task" not in body
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "created": 1,
                "model": "test",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "answer"}}],
            },
        )

    app = runtime(
        {
            "routing": {
                "default_model": "ollama:test",
                "rules": [{"when_task": "code", "model": "openai:test"}],
            },
            "providers": {
                "openai": {
                    "base_url": "https://provider.example.invalid/custom",
                    "api_key_env": "SYNTHETIC_PROVIDER_KEY",
                }
            },
        },
        handler,
    )
    with TestClient(app) as client:
        response = chat(client, task="code")
        assert response.status_code == 200
        assert response.json()["model"] == "openai:test"
        assert response.json()["usage"] is None


def test_disabled_provider_never_called(runtime):
    app = runtime(
        {"providers": {"ollama": {"enabled": False}}},
        handler=lambda request: pytest.fail("Provider must not be called"),
    )
    with TestClient(app) as client:
        response = chat(client)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_disabled"


def test_blocklist_is_configured_case_insensitive_and_does_not_echo(runtime, capsys):
    app = runtime(handler=lambda request: pytest.fail("Provider must not be called"))
    with TestClient(app) as client:
        response = chat(client, messages=[{"role": "user", "content": "RESTRICTED PHRASE"}])
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "blocklist_match"
        assert "restricted phrase" not in response.text.lower()
        metrics = client.get("/metrics").text
        assert 'm87_gateway_guardrail_blocks_total{reason="blocklist_match"} 1.0' in metrics
    assert "RESTRICTED PHRASE" not in capsys.readouterr().out


def test_blocklist_can_be_disabled(runtime):
    app = runtime(
        {
            "guardrails": {
                "blocklist": {
                    "enabled": False,
                    "blocked_terms": ["synthetic prompt"],
                }
            }
        }
    )
    with TestClient(app) as client:
        assert chat(client).status_code == 200


def test_message_size_and_body_size_limits(runtime):
    app = runtime({"guardrails": {"max_message_chars": 4, "max_request_bytes": 256}})
    with TestClient(app) as client:
        response = chat(client)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "message_too_large"
        response = client.post(
            "/v1/chat/completions",
            headers=HEADERS,
            content=b"x" * 257,
        )
        assert response.status_code == 413
        assert response.json()["request_id"] == response.headers["x-request-id"]


@pytest.mark.parametrize(
    "payload",
    [
        {"stream": True},
        {"tools": []},
        {"model": "not-a-model"},
        {"messages": []},
        {"messages": [{"role": "tool", "content": "unsupported"}]},
    ],
)
def test_unsupported_and_invalid_requests_are_safe(runtime, payload):
    app = runtime(handler=lambda request: pytest.fail("Provider must not be called"))
    with TestClient(app) as client:
        response = chat(client, **payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize(
    "failure,status,code",
    [
        ("timeout", 504, "provider_timeout"),
        ("network", 502, "provider_error"),
        ("throttle", 503, "provider_rate_limited"),
        ("upstream", 502, "provider_rejected"),
        ("malformed", 502, "provider_invalid_payload"),
        ("shape", 502, "invalid_provider_response"),
    ],
)
def test_provider_failures_are_safe_and_observable(runtime, failure, status, code, capsys):
    sensitive = "private upstream exception synthetic-credential"

    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout(sensitive, request=request)
        if failure == "network":
            raise httpx.ConnectError(sensitive, request=request)
        if failure == "throttle":
            return httpx.Response(429, text=sensitive)
        if failure == "upstream":
            return httpx.Response(401, text=sensitive)
        if failure == "malformed":
            return httpx.Response(200, text=sensitive)
        return httpx.Response(200, json={"message": sensitive})

    with TestClient(runtime(handler=handler)) as client:
        response = chat(client)
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert sensitive not in response.text
        assert (
            'm87_gateway_provider_errors_total{provider="ollama"} 1.0'
            in client.get("/metrics").text
        )
    assert sensitive not in capsys.readouterr().out


def test_missing_provider_key_is_safe(runtime):
    with TestClient(runtime()) as client:
        response = chat(client, model="openai:test")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_not_configured"


def test_metrics_can_be_disabled(runtime):
    app = runtime({"observability": {"prometheus_metrics": False}})
    with TestClient(app) as client:
        assert chat(client).status_code == 200
        assert client.get("/metrics").status_code == 404


def test_missing_usage_stays_null_and_response_ids_are_unique(runtime):
    app = runtime(
        handler=lambda request: httpx.Response(
            200,
            json={
                "message": {"content": "answer"},
            },
        )
    )
    with TestClient(app) as client:
        first, second = chat(client).json(), chat(client).json()
        assert first["usage"] is None
        assert first["id"] != second["id"]


def test_caller_cannot_choose_the_request_id(runtime):
    with TestClient(runtime()) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={**HEADERS, "X-Request-ID": "caller-controlled"},
            json={"model": "auto", "messages": [{"role": "user", "content": "synthetic"}]},
        )
        assert response.status_code == 200
        assert response.headers["x-request-id"] != "caller-controlled"


def test_unexpected_failure_does_not_leak(runtime, monkeypatch, capsys):
    from m87_gateway.api import routes

    app = runtime()

    def broken(*args):
        raise RuntimeError("synthetic-private-internal-details")

    monkeypatch.setattr(routes, "get_provider", broken)
    with TestClient(app) as client:
        response = chat(client)
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert "synthetic-private" not in response.text
    assert "synthetic-private" not in capsys.readouterr().out
