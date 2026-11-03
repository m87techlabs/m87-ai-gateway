"""The drop-in contract: an OpenAI client changes only its base URL and API key."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from m87_gateway.config.settings import load_settings
from m87_gateway.control.store import LocalControlStore
from m87_gateway.config import ControlPlaneConfig
from test_runtime import HEADERS, chat, completion, runtime  # noqa: F401

BARE = "qwen3:14b"
EMBED = "hf.co/CompendiumLabs/bge-base-en-v1.5-gguf:F16"
ALLOWED = ["auto", f"ollama:{BARE}", f"ollama:{EMBED}"]
USAGE = {"prompt_tokens": 19, "completion_tokens": 10, "total_tokens": 29}


def drop_in(runtime, handler, **overrides):  # noqa: F811
    return runtime(
        overrides={
            "apps": [
                {
                    "app_id": "test-app",
                    "api_key": "synthetic-app-credential",
                    "allowed_models": ALLOWED,
                }
            ],
            "routing": {"default_model": f"ollama:{BARE}"},
            **overrides,
        },
        handler=handler,
    )


def test_bare_model_names_resolve_authorize_and_report_as_requested(runtime):  # noqa: F811
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["model"])
        return httpx.Response(200, json=completion("ok", USAGE))

    with TestClient(drop_in(runtime, handler)) as client:
        response = chat(client, model=BARE)
        assert response.status_code == 200
        assert response.json()["model"] == BARE
        assert seen == [BARE]
        assert chat(client, model=f"ollama:{BARE}").json()["model"] == f"ollama:{BARE}"
        assert chat(client, model="auto").json()["model"] == f"ollama:{BARE}"
        assert chat(client, model="not-allowed:1b").status_code == 403
        assert len(seen) == 3


def test_model_list_offers_upstream_names_for_the_default_provider(runtime):  # noqa: F811
    app = drop_in(runtime, lambda request: pytest.fail("Listing must not call the provider"))
    with TestClient(app) as client:
        ids = {item["id"] for item in client.get("/v1/models", headers=HEADERS).json()["data"]}
    assert {BARE, EMBED, f"ollama:{BARE}", "auto"} == ids - {f"ollama:{EMBED}"}


@pytest.mark.parametrize(
    "extra",
    [
        {"reasoning_effort": "none"},
        {"n": 1, "logprobs": False},
        {"max_completion_tokens": 5},
        {
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "lookup", "parameters": {"type": "object"}},
                }
            ],
            "tool_choice": "auto",
        },
        {"messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]},
        {
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": ""},
                {"role": "tool", "tool_call_id": "call", "content": "42"},
            ]
        },
    ],
)
def test_unmodelled_fields_reach_the_provider_unless_strict(runtime, extra):  # noqa: F811
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=completion("ok"))

    with TestClient(drop_in(runtime, handler)) as client:
        assert chat(client, **extra).status_code == 200
    for key, value in extra.items():
        assert bodies[0][key] == value

    strict = drop_in(
        runtime,
        lambda request: pytest.fail("Strict mode must stop this at the gateway"),
        compatibility={"strict_requests": True},
    )
    with TestClient(strict) as client:
        response = chat(client, **extra)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "strict_mode_rejected"


def test_strict_mode_still_serves_plain_requests_and_bare_names(runtime):  # noqa: F811
    app = drop_in(
        runtime,
        lambda request: httpx.Response(200, json=completion("ok")),
        compatibility={"strict_requests": True},
    )
    with TestClient(app) as client:
        assert chat(client, model=BARE, temperature=0.2, max_tokens=5).status_code == 200


def test_tool_call_response_with_null_content_is_returned_intact(runtime):  # noqa: F811
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "c", "type": "function", "function": {"name": "f", "arguments": "{}"}}
        ],
    }

    def handler(request):
        body = completion("x")
        body["choices"][0].update(message=message, finish_reason="tool_calls")
        body["system_fingerprint"] = "fp_upstream"
        return httpx.Response(200, json=body)

    with TestClient(drop_in(runtime, handler)) as client:
        result = chat(client).json()
    assert result["choices"][0]["message"]["tool_calls"] == message["tool_calls"]
    assert result["system_fingerprint"] == "fp_upstream"


def test_stream_forwards_reasoning_and_tool_deltas(runtime):  # noqa: F811
    def event(delta, finish=None, usage=None, choices=True):
        return (
            "data: "
            + json.dumps(
                {
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    # Some servers stamp each chunk with the current second.
                    "created": 1 + len(delta),
                    "model": BARE,
                    "system_fingerprint": "fp_ollama",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]
                    if choices
                    else [],
                    **({"usage": usage} if usage else {}),
                }
            )
            + "\n\n"
        ).encode()

    tool = [{"index": 0, "id": "c", "function": {"name": "f", "arguments": "{}"}}]
    body = (
        event({"role": "assistant", "content": "", "reasoning": "Okay"})
        + event({"content": "answer"})
        + event({"tool_calls": tool}, "tool_calls")
        + event({}, usage={**USAGE, "prompt_tokens_details": {"cached_tokens": 1}}, choices=False)
        + b"data: [DONE]\n\n"
    )
    events = []
    app = drop_in(runtime, lambda request: httpx.Response(200, content=body))
    with TestClient(app) as client:
        recorder = app.state.recorder
        recorder.record = lambda event, *args: events.append(dict(event))
        response = chat(client, model=BARE, stream=True)
    assert response.status_code == 200
    assert response.text.endswith("data: [DONE]\n\n")
    frames = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    assert all(frame["model"] == BARE for frame in frames)
    assert frames[0]["choices"][0]["delta"]["reasoning"] == "Okay"
    assert frames[2]["choices"][0]["delta"]["tool_calls"] == tool
    assert frames[0]["system_fingerprint"] == "fp_ollama"
    assert events[0]["total_tokens"] == 29
    assert "prompt_tokens_details" not in events[0]


def embedding_body(count=2):
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": [0.1, 0.2]}
            for index in range(count)
        ],
        "model": EMBED,
        "usage": {"prompt_tokens": 6, "total_tokens": 6},
    }


def test_embeddings_forward_account_and_report_as_requested(runtime):  # noqa: F811
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=embedding_body())

    events = []
    app = drop_in(runtime, handler)
    with TestClient(app) as client:
        recorder = app.state.recorder
        recorder.record = lambda event, *args: events.append(dict(event))
        response = client.post(
            "/v1/embeddings",
            headers=HEADERS,
            json={"model": EMBED, "input": ["hello", "world"], "dimensions": 2, "user": "person"},
        )
    assert response.status_code == 200
    assert response.json()["model"] == EMBED
    assert [item["embedding"] for item in response.json()["data"]] == [[0.1, 0.2]] * 2
    assert str(requests[0].url) == "http://localhost:11434/v1/embeddings"
    sent = json.loads(requests[0].content)
    assert sent["model"] == EMBED and sent["dimensions"] == 2 and "user" not in sent
    assert events[0]["endpoint"] == "embeddings"
    assert events[0]["prompt_tokens"] == 6 and events[0]["total_tokens"] == 6
    assert events[0]["cache_status"] == "bypass"
    assert events[0]["routed_model"] == f"ollama:{EMBED}"


@pytest.mark.parametrize(
    "payload,status,code",
    [
        ({"model": "auto", "input": "x"}, 422, "model_required"),
        ({"model": "other:1b", "input": "x"}, 403, "model_not_allowed"),
        ({"model": EMBED, "input": []}, 422, "invalid_request"),
        ({"input": "x"}, 422, "model_required"),
    ],
)
def test_embedding_requests_fail_before_the_provider(runtime, payload, status, code):  # noqa: F811
    app = drop_in(runtime, lambda request: pytest.fail("Provider must not be called"))
    with TestClient(app) as client:
        response = client.post("/v1/embeddings", headers=HEADERS, json=payload)
    assert (response.status_code, response.json()["error"]["code"]) == (status, code)


def test_embeddings_require_auth_and_respect_guardrails(runtime):  # noqa: F811
    app = drop_in(
        runtime,
        lambda request: pytest.fail("Provider must not be called"),
        guardrails={"blocklist": {"enabled": True, "blocked_terms": ["forbidden"]}},
    )
    with TestClient(app) as client:
        body = {"model": EMBED, "input": ["fine", "Forbidden text"]}
        assert client.post("/v1/embeddings", json=body).status_code == 401
        blocked = client.post("/v1/embeddings", headers=HEADERS, json=body)
        assert blocked.status_code == 400
        assert blocked.json()["error"]["code"] == "blocklist_match"
        assert "Forbidden" not in blocked.text


def test_malformed_embedding_response_is_a_safe_error(runtime):  # noqa: F811
    app = drop_in(runtime, lambda request: httpx.Response(200, json={"data": [{"index": 0}]}))
    with TestClient(app) as client:
        response = client.post(
            "/v1/embeddings", headers=HEADERS, json={"model": EMBED, "input": "x"}
        )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_provider_response"


def test_upstream_status_is_logged_and_reported_without_its_body(runtime):  # noqa: F811
    events = []
    app = drop_in(
        runtime, lambda request: httpx.Response(404, json={"error": "private upstream detail"})
    )
    with TestClient(app) as client:
        recorder = app.state.recorder
        recorder.record = lambda event, *args: events.append(dict(event))
        response = chat(client)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_rejected"
    assert "HTTP 404" in response.json()["error"]["message"]
    assert "private upstream detail" not in response.text
    assert events[0]["upstream_status"] == 404


def test_capture_keeps_text_but_never_stores_images(runtime, tmp_path):  # noqa: F811
    app = drop_in(
        runtime,
        lambda request: httpx.Response(200, json=completion("ok")),
        observability={
            "traffic_log": {"capture_content": True, "path": str(tmp_path / "traffic.jsonl")},
            "json_logs": False,
        },
    )
    captured = []
    with TestClient(app) as client:
        recorder = app.state.recorder
        recorder.record = lambda event, request_content, *args: captured.append(request_content)
        image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,SECRETPIXELS"}}
        response = chat(
            client,
            messages=[{"role": "user", "content": [{"type": "text", "text": "look"}, image]}],
        )
    assert response.status_code == 200
    assert "SECRETPIXELS" not in json.dumps(captured)
    assert captured[0][0]["content"] == [
        {"type": "text", "text": "look"},
        {"type": "image_url", "omitted": True},
    ]


def test_example_config_and_its_demo_key_are_never_loaded_implicitly(tmp_path, monkeypatch):
    (tmp_path / "config.example.yaml").write_text(
        'auth:\n  api_keys:\n    - {key: "demo-app-key", app_id: "demo", allowed_models: [auto]}\n'
    )
    monkeypatch.chdir(tmp_path)
    assert load_settings().configured_apps == []
    (tmp_path / "config.yaml").write_text(
        'auth:\n  api_keys:\n    - {key: "chosen-key", app_id: "mine", allowed_models: [auto]}\n'
    )
    assert [app.app_id for app in load_settings().configured_apps] == ["mine"]


def test_api_reference_is_not_published(runtime):  # noqa: F811
    with TestClient(runtime()) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404


def test_provider_key_lookup_writes_last_used_only_periodically(tmp_path, monkeypatch):
    store = LocalControlStore(
        ControlPlaneConfig(
            enabled=True,
            database_path=str(tmp_path / "control.db"),
            master_key_path=str(tmp_path / "master.key"),
        )
    )
    store.put_provider_key("openai", "synthetic-provider-key")
    clock = [1000.0]
    monkeypatch.setattr("m87_gateway.control.repositories.secrets.monotonic", lambda: clock[0])

    def last_used():
        return store.list_provider_keys()[0]["last_used_at"]

    assert store.get_provider_key("openai") == "synthetic-provider-key"
    first = last_used()
    assert first is not None
    clock[0] += 30
    assert store.get_provider_key("openai") == "synthetic-provider-key"
    assert last_used() == first
    clock[0] += 31
    store.get_provider_key("openai")
    assert last_used() > first


def test_concurrency_rejection_is_not_labelled_as_immediate(runtime):  # noqa: F811
    import asyncio

    from m87_gateway.controls.runtime import InFlightLimiter

    async def scenario():
        limiter = InFlightLimiter()
        audit = {}
        async with limiter.admit_wait("a", 1, None):
            with pytest.raises(Exception) as rejected:
                async with limiter.admit_wait("a", 1, None, 0, audit=audit):
                    pass
        assert rejected.value.code == "concurrency_limit_exceeded"
        assert audit["queue_outcome"] == "rejected"

    asyncio.run(scenario())
