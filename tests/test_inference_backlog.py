"""Synthetic SDK and adapter acceptance tests; no cloud credentials required."""

import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from examples.chat_app.scenarios import serving
from m87_gateway.adapters import Capabilities, adapters
from m87_gateway.api.routes import validate_capabilities
from m87_gateway.api.schemas import ChatCompletionRequest
from m87_gateway.config import GatewaySettings
from m87_gateway.main import create_app
from m87_gateway.model_catalog import ModelCatalog
from test_runtime import HEADERS, chat, runtime  # noqa: F401


def test_catalog_expiry_endpoint_binding_and_clear():
    now = [0.0]
    catalog = ModelCatalog(clock=lambda: now[0])
    catalog.replace("ollama", "http://one", ["ollama:b", "ollama:a", "ollama:a"])
    assert catalog.models("ollama", "http://one") == ("ollama:a", "ollama:b")
    assert catalog.models("ollama", "http://two") == ()
    now[0] = 901
    assert catalog.models("ollama", "http://one") == ()
    catalog.replace("ollama", "http://one", ["ollama:a"])
    catalog.clear()
    assert catalog.models("ollama", "http://one") == ()


def test_sdk_lists_authorized_models_over_real_local_http():
    sdk = pytest.importorskip("openai")
    settings = GatewaySettings(
        apps=[
            {
                "app_id": "sdk-test",
                "api_key": "synthetic-sdk-key",
                "allowed_models": ["auto", "ollama:test"],
            }
        ]
    )
    settings.observability.json_logs = False
    app = create_app(settings)
    with serving(app) as url:
        app.state.model_catalog.replace("ollama", "http://localhost:11434", ["ollama:secret"])
        with sdk.OpenAI(api_key="synthetic-sdk-key", base_url=url + "/v1", max_retries=0) as client:
            assert [model.id for model in client.models.list()] == ["auto", "ollama:test"]
        with httpx.Client(base_url=url, trust_env=False) as client:
            assert client.get("/v1/models").status_code == 401
            response = client.get(
                "/v1/models", headers={"Authorization": "Bearer synthetic-sdk-key"}
            )
            assert response.headers["cache-control"] == "no-store"
            assert "localhost:11434" not in response.text
        assert app.state.inflight_limiter.snapshot()["active_requests"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("top_p", -0.1),
        ("top_p", 1.1),
        ("stop", []),
        ("stop", ["x"] * 5),
        ("seed", True),
        ("seed", 2**63),
        ("presence_penalty", 2.1),
        ("frequency_penalty", -2.1),
        ("user", ""),
        ("response_format", {"type": "unknown"}),
        ("response_format", {"type": "json_schema", "json_schema": {"name": "x", "schema": {}}}),
    ],
)
def test_parameter_bounds(field, value):
    with pytest.raises(ValidationError):
        ChatCompletionRequest(
            model="auto", messages=[{"role": "user", "content": "test"}], **{field: value}
        )


@pytest.mark.parametrize("name", ["openai", "openai_compatible", "ollama"])
@pytest.mark.parametrize("format_type", ["text", "json_object", "json_schema"])
def test_builtin_parameter_mapping(runtime, monkeypatch, name, format_type):  # noqa: F811
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-provider-key")
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    response_format = {"type": format_type}
    if format_type == "json_schema":
        response_format["json_schema"] = {"name": "answer", "schema": schema}
    options = {
        "top_p": 0.7,
        "stop": "END",
        "seed": 42,
        "response_format": response_format,
        "user": "synthetic-client-user",
    }
    if name != "ollama":
        options.update(presence_penalty=0.2, frequency_penalty=-0.2)

    def handler(request):
        body = json.loads(request.content)
        assert "user" not in body
        if name == "ollama":
            assert body["options"] == {"top_p": 0.7, "stop": ["END"], "seed": 42}
            assert (
                body.get("format")
                == {"text": None, "json_object": "json", "json_schema": schema}[format_type]
            )
            return httpx.Response(200, json={"message": {"content": "synthetic"}})
        assert body["response_format"] == response_format
        for field in ("top_p", "stop", "seed", "presence_penalty", "frequency_penalty"):
            assert body[field] == options[field]
        return httpx.Response(
            200,
            json={
                "id": "test",
                "created": 1,
                "model": "test",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "synthetic"}}],
            },
        )

    app = runtime(
        overrides={
            "apps": [
                {
                    "app_id": "test",
                    "api_key": "synthetic-app-credential",
                    "allowed_models": [f"{name}:test"],
                }
            ],
            "providers": {name: {"enabled": True, "base_url": "http://synthetic/v1"}},
        },
        handler=handler,
    )
    events = []
    with TestClient(app) as client:
        app.state.recorder.record = lambda event, *args: events.append(dict(event))
        response = chat(client, model=f"{name}:test", **options)
        assert response.status_code == 200, response.text
    assert events[0]["client_user_hash"] == hashlib.sha256(b"synthetic-client-user").hexdigest()
    assert "synthetic-client-user" not in json.dumps(events)


@pytest.mark.parametrize(
    "options",
    [
        {"presence_penalty": 0},
        {"frequency_penalty": 0},
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "x", "schema": {"type": "object"}, "strict": False},
            }
        },
    ],
)
def test_unsupported_ollama_options_never_reach_provider(runtime, options):  # noqa: F811
    def handler(request):
        pytest.fail("Unsupported options reached provider")

    with TestClient(runtime(handler=handler)) as client:
        response = chat(client, **options)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "unsupported_parameter"


def test_capability_declarations_match_gateway_protocol():
    for name, adapter in adapters().items():
        matrix = adapter.capabilities.as_dict()
        assert matrix["text_chat"]
        assert not any(
            matrix[field]
            for field in ("streaming", "tools", "images", "embeddings", "multiple_choices")
        )
        for parameter in adapter.capabilities.generation_parameters:
            value = "end" if parameter == "stop" else 1
            payload = ChatCompletionRequest(
                model=f"{name}:test",
                messages=[{"role": "user", "content": "x"}],
                **{parameter: value},
            )
            validate_capabilities(payload, name)
    assert Capabilities().response_formats == frozenset({"text"})


def test_schema_three_migration_preserves_keys_usage_and_audit(tmp_path):
    import sqlite3
    from backend_contracts import exchange
    from m87_gateway.cli import local_settings
    from m87_gateway.control import LocalControlStore

    config = local_settings(tmp_path).control_plane
    store = LocalControlStore(config)
    _, key = store.create_app_key("migration-app", ["auto"], False)
    event = exchange("migration-event", app_id="migration-app")
    store.emit(event)
    before = store.overview()
    audit = store.list_management_events()
    store.close()
    with sqlite3.connect(config.database_path) as database:
        for column in ("client_user_hash", "queue_wait_ms", "queue_outcome"):
            database.execute(f"ALTER TABLE events DROP COLUMN {column}")
        database.execute("PRAGMA user_version = 3")
    upgraded = LocalControlStore(config)
    assert upgraded.authenticate_app_key(key).app_id == "migration-app"
    assert upgraded.overview() == before
    assert upgraded.list_management_events() == audit
    assert upgraded.get_event("migration-event")["queue_wait_ms"] is None
    with sqlite3.connect(config.database_path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 4
    upgraded.close()


@pytest.mark.parametrize(
    "options",
    [
        {"top_p": 0.8},
        {"stop": "END"},
        {"seed": 1},
        {"presence_penalty": 0.2},
        {"frequency_penalty": 0.2},
        {"response_format": {"type": "json_object"}},
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "x", "schema": {"type": "object"}},
            }
        },
    ],
)
def test_conservative_adapter_rejects_unmapped_fields(runtime, monkeypatch, options):  # noqa: F811
    from dataclasses import replace
    from m87_gateway import adapters as registry

    monkeypatch.setitem(
        registry._registry, "ollama", replace(adapters()["ollama"], capabilities=Capabilities())
    )

    def handler(request):
        pytest.fail("Unmapped field reached provider")

    with TestClient(runtime(handler=handler)) as client:
        response = chat(client, **options)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "unsupported_parameter"


def test_model_catalog_filters_disabled_providers_and_app_allowlists(runtime):  # noqa: F811
    app = runtime(overrides={"providers": {"openai": {"enabled": False}}})
    with TestClient(app) as client:
        response = client.get("/v1/models", headers=HEADERS)
        assert [item["id"] for item in response.json()["data"]] == ["auto", "ollama:test"]
