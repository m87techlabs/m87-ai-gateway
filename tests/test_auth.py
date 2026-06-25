import time

from fastapi.testclient import TestClient
import pytest

from m87_gateway.config import get_settings
from m87_gateway.api import routes
from m87_gateway.main import app


class FakeProvider:
    async def chat_completions(self, payload, model):
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"ollama:{model}",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


@pytest.fixture
def client(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
auth:
  api_keys:
    - key: "demo-app-key"
      app_id: "demo-app"
      allowed_models:
        - "auto"
        - "ollama:llama3"
routing:
  default_model: "ollama:llama3"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("M87_GATEWAY_CONFIG", str(config_path))
    monkeypatch.setattr(routes, "get_provider", lambda provider_name: FakeProvider())
    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


def chat_payload(model: str = "auto") -> dict:
    return {"model": model, "messages": [{"role": "user", "content": "hello"}]}


def test_missing_auth_rejected(client):
    response = client.post("/v1/chat/completions", json=chat_payload())
    assert response.status_code == 401


def test_invalid_api_key_rejected(client):
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer nope"},
        json=chat_payload(),
    )
    assert response.status_code == 401


def test_valid_api_key_succeeds_for_allowed_model(client):
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer demo-app-key"},
        json=chat_payload("ollama:llama3"),
    )
    assert response.status_code == 200
    assert response.json()["model"] == "ollama:llama3"


def test_disallowed_model_rejected(client):
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer demo-app-key"},
        json=chat_payload("openai:gpt-4.1-mini"),
    )
    assert response.status_code == 403


def test_auto_model_resolves_to_configured_default(client):
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer demo-app-key"},
        json=chat_payload("auto"),
    )
    assert response.status_code == 200
    assert response.json()["model"] == "ollama:llama3"
