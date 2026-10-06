"""Adapter stream contracts and gateway SSE semantics with synthetic byte streams."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from test_runtime import runtime, chat  # noqa: F401


class Bytes(httpx.AsyncByteStream):
    def __init__(self, parts):
        self.parts = parts
        self.closed = False

    async def __aiter__(self):
        for part in self.parts:
            yield part

    async def aclose(self):
        self.closed = True


def chunk(content="", finish=None, usage=None):
    return {
        "id": "synthetic-stream",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "test",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": finish,
            }
        ],
        "usage": usage,
    }


def sse(value):
    return f"data: {json.dumps(value)}\n\n".encode()


def frames(text):
    return [
        json.loads(line[6:])
        for line in text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


@pytest.mark.parametrize("name", ["ollama", "openai", "openai_compatible"])
@pytest.mark.parametrize("include_usage", [False, True])
def test_stream_contract_usage_and_cache_bypass(runtime, monkeypatch, name, include_usage):  # noqa: F811
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-provider-credential")
    usage = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    if name == "ollama":
        data = (
            b"\n".join(
                json.dumps(value).encode()
                for value in [
                    {"message": {"content": "Hello "}, "done": False},
                    {
                        "message": {"content": "world"},
                        "done": True,
                        "prompt_eval_count": 3,
                        "eval_count": 2,
                    },
                ]
            )
            + b"\n"
        )
    else:
        data = sse(chunk("Hello ")) + sse(chunk("world", "stop"))
        data += sse({**chunk(), "choices": [], "usage": usage}) + b"data: [DONE]\n\n"
    streams = []

    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] is True
        assert "user" not in body
        if name != "ollama":
            assert body["stream_options"] == {"include_usage": True}
        stream = Bytes([data[:3], data[3:19], data[19:]])
        streams.append(stream)
        return httpx.Response(200, stream=stream)

    app = runtime(
        overrides={
            "apps": [
                {
                    "app_id": "stream-test",
                    "api_key": "synthetic-app-credential",
                    "allowed_models": [f"{name}:test"],
                }
            ],
            "providers": {name: {"enabled": True, "base_url": "http://synthetic"}},
            "cache": {"enabled": True},
            "observability": {"json_logs": False},
        },
        handler=handler,
    )
    events = []
    with TestClient(app) as client:
        app.state.recorder.record = lambda event, *args: events.append(dict(event))
        for _ in range(2):
            response = chat(
                client,
                model=f"{name}:test",
                stream=True,
                stream_options={"include_usage": include_usage},
            )
            assert response.status_code == 200, response.text
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["x-gateway-cache"] == "BYPASS"
            assert response.text.endswith("data: [DONE]\n\n")
            values = frames(response.text)
            assert (
                "".join(
                    choice["delta"].get("content", "")
                    for value in values
                    for choice in value["choices"]
                )
                == "Hello world"
            )
            assert all(value["model"] == f"{name}:test" for value in values)
            if include_usage:
                assert values[-1]["choices"] == [] and values[-1]["usage"] == usage
            else:
                assert all("usage" not in value for value in values)
            assert app.state.inflight_limiter.snapshot()["active_requests"] == 0
        assert len(events) == 2 and len(streams) == 2
        assert all(stream.closed for stream in streams)
        assert all(e["request_outcome"] == "completed" and e["total_tokens"] == 5 for e in events)
        assert (
            'm87_gateway_tokens_total{kind="prompt",provider="' + name + '"} 6.0'
            in app.state.metrics.render().decode()
        )


@pytest.mark.parametrize(
    "mode", ["http", "initial", "midstream", "truncated", "oversized", "identity"]
)
def test_stream_safe_failures_and_slot_release(runtime, mode):  # noqa: F811
    private = "private-provider-error-content"
    first = sse(chunk("hello"))
    data = {
        "initial": sse({"error": {"message": private}}),
        "midstream": first + sse({"error": {"message": private}}),
        "truncated": first,
        "oversized": first + b"data: " + b"x" * 65537,
        "identity": first + sse({**chunk("world", "stop"), "id": "other"}) + b"data: [DONE]\n\n",
    }.get(mode, b"")
    stream = Bytes([data])

    def handler(request):
        return httpx.Response(401 if mode == "http" else 200, stream=stream)

    app = runtime(
        overrides={
            "apps": [
                {
                    "app_id": "stream-test",
                    "api_key": "synthetic-app-credential",
                    "allowed_models": ["openai_compatible:test"],
                }
            ],
            "providers": {"openai_compatible": {"base_url": "http://synthetic"}},
            "retry": {"max_attempts": 3},
        },
        handler=handler,
    )
    events = []
    with TestClient(app) as client:
        app.state.recorder.record = lambda event, *args: events.append(dict(event))
        response = chat(client, model="openai_compatible:test", stream=True)
        assert response.status_code == (502 if mode in {"http", "initial"} else 200)
        assert private not in response.text
        if mode not in {"http", "initial"}:
            assert "event: error" in response.text
            assert "data: [DONE]" not in response.text
        assert len(events) == 1
        assert events[0]["request_outcome"] == "failed"
        assert events[0]["status_code"] == 502
        assert events[0]["http_status_code"] == response.status_code
        assert events[0]["provider_attempts"] == 1
        assert events[0]["total_tokens"] is None
        assert stream.closed
        assert app.state.inflight_limiter.snapshot()["active_requests"] == 0


def test_actual_sdk_streams_through_local_gateway():
    import threading
    from http.server import ThreadingHTTPServer
    from examples.chat_app.scenarios import Inference, InferenceState, serving
    from m87_gateway.config import GatewaySettings
    from m87_gateway.main import create_app

    sdk = pytest.importorskip("openai")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Inference)
    server.scenario_state = InferenceState()
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        app = create_app(
            GatewaySettings.model_validate(
                {
                    "apps": [
                        {
                            "app_id": "stream-sdk",
                            "api_key": "synthetic-sdk-credential",
                            "allowed_models": ["openai_compatible:scenario-model"],
                        }
                    ],
                    "providers": {
                        "openai_compatible": {
                            "base_url": f"http://127.0.0.1:{server.server_port}/v1"
                        }
                    },
                    "observability": {"json_logs": False},
                }
            )
        )
        with serving(app) as url:
            with sdk.OpenAI(
                base_url=url + "/v1", api_key="synthetic-sdk-credential", max_retries=0
            ) as client:
                with client.chat.completions.create(
                    model="openai_compatible:scenario-model",
                    messages=[{"role": "user", "content": "Synthetic SDK stream"}],
                    stream=True,
                    stream_options={"include_usage": True},
                ) as response:
                    values = list(response)
                assert (
                    "".join(
                        choice.delta.content or "" for value in values for choice in value.choices
                    )
                    == "synthetic answer"
                )
                assert values[-1].usage.total_tokens == 6
                assert values[-1].model == "openai_compatible:scenario-model"
                assert app.state.inflight_limiter.snapshot()["active_requests"] == 0
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


@pytest.mark.parametrize("fail", [False, True])
def test_stream_capture_redacts_across_chunks_and_marks_truncation(
    tmp_path, monkeypatch, capsys, fail
):
    from m87_gateway.api import routes
    from m87_gateway.main import create_app
    from test_traffic_logging import settings

    path = tmp_path / "private" / "traffic.jsonl"

    class Provider:
        async def stream_chat_completions(self, payload, model):
            yield chunk("synthetic-app-")
            yield chunk("secret Bearer unknown-credential ")
            yield chunk("private-output " * 100, None if fail else "length")
            if fail:
                from m87_gateway.api.errors import GatewayError

                raise GatewayError(502, "provider_error", "Safe provider failure")

    monkeypatch.setattr(routes, "get_provider", lambda *args: Provider())
    with TestClient(create_app(settings(path, global_capture=True, limit=180))) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer synthetic-app-secret"},
            json={
                "model": "auto",
                "stream": True,
                "messages": [{"role": "user", "content": "capture test"}],
            },
        )
        assert response.status_code == 200
    event = json.loads(path.read_text().splitlines()[0])
    assert "synthetic-app-secret" not in path.read_text()
    assert "unknown-credential" not in path.read_text()
    assert "[REDACTED]" in event["response_content"]
    assert len(event["response_content"]) <= 180
    assert event["response_content_truncated"]
    assert event["response_content_partial"] is fail
    assert event["request_outcome"] == ("failed" if fail else "completed")
    assert "private-output" not in capsys.readouterr().out


@pytest.mark.parametrize("name", ["ollama", "openai_compatible"])
def test_missing_stream_usage_remains_unknown(runtime, name):  # noqa: F811
    data = (
        json.dumps({"message": {"content": "text"}, "done": True}).encode() + b"\n"
        if name == "ollama"
        else sse(chunk("text", "stop")) + b"data: [DONE]\n\n"
    )
    app = runtime(
        overrides={
            "apps": [
                {
                    "app_id": "unknown",
                    "api_key": "synthetic-app-credential",
                    "allowed_models": [f"{name}:test"],
                }
            ],
            "providers": {name: {"base_url": "http://synthetic"}},
        },
        handler=lambda request: httpx.Response(200, stream=Bytes([data])),
    )
    events = []
    with TestClient(app) as client:
        app.state.recorder.record = lambda event, *args: events.append(dict(event))
        response = chat(
            client, model=f"{name}:test", stream=True, stream_options={"include_usage": True}
        )
        assert frames(response.text)[-1]["usage"] is None
        assert events[0]["total_tokens"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"stream": "true"},
        {"stream": True, "stream_options": {"include_usage": 1}},
        {"stream": False, "stream_options": {"include_usage": False}},
        {"stream": True, "stream_options": {"unknown": True}},
    ],
)
def test_stream_options_are_strict(runtime, payload):  # noqa: F811
    with TestClient(
        runtime(handler=lambda request: pytest.fail("Invalid options reached provider"))
    ) as client:
        assert chat(client, **payload).status_code == 422


@pytest.mark.parametrize("after_chunk", [False, True])
def test_stream_timeout_status_and_safe_terminal_error(runtime, after_chunk):  # noqa: F811
    class Timeout(Bytes):
        async def __aiter__(self):
            if after_chunk:
                yield sse(chunk("partial"))
            raise httpx.ReadTimeout("private-timeout-details")

    stream = Timeout([])
    app = runtime(
        overrides={
            "apps": [
                {
                    "app_id": "timeout",
                    "api_key": "synthetic-app-credential",
                    "allowed_models": ["openai_compatible:test"],
                }
            ],
            "providers": {"openai_compatible": {"base_url": "http://synthetic"}},
        },
        handler=lambda request: httpx.Response(200, stream=stream),
    )
    events = []
    with TestClient(app) as client:
        app.state.recorder.record = lambda event, *args: events.append(dict(event))
        response = chat(client, model="openai_compatible:test", stream=True)
        assert response.status_code == (200 if after_chunk else 504)
        assert "private-timeout-details" not in response.text
        assert events[0]["error_type"] == "provider_timeout"
        assert events[0]["status_code"] == 504
        assert stream.closed
        assert app.state.inflight_limiter.snapshot()["active_requests"] == 0


def test_adapter_without_streaming_rejects_before_provider(runtime, monkeypatch):  # noqa: F811
    from dataclasses import replace
    from m87_gateway import adapters as registry
    from m87_gateway.adapters import adapters

    old = adapters()["ollama"]
    monkeypatch.setitem(
        registry._registry,
        "ollama",
        replace(old, capabilities=replace(old.capabilities, streaming=False)),
    )
    with TestClient(
        runtime(handler=lambda request: pytest.fail("Unsupported streaming reached provider"))
    ) as client:
        response = chat(client, stream=True)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "unsupported_streaming"
