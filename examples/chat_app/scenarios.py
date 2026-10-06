"""Isolated HTTP acceptance scenarios: sample application -> gateway -> test inference."""

import json
import os
import secrets
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import uvicorn

from examples.chat_app.app import Settings, create_app as sample_app
from m87_gateway.cli import local_settings
from m87_gateway.local_server import bind_listener
from m87_gateway.main import create_app


class InferenceState:
    def __init__(self):
        self.mode = "healthy"
        self.failures = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.calls = 0


class Inference(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Timeout exercises deliberately disconnect the gateway client.

    def do_GET(self):
        self.reply(200, {"data": [{"id": "scenario-model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["model"] == "scenario-model"
        state = self.server.scenario_state
        with state.lock:
            state.calls += 1
            fail = state.failures > 0
            state.failures = max(0, state.failures - 1)
            mode = state.mode
        if fail or mode == "outage":
            self.reply(503, {"error": "synthetic outage"})
            return
        if mode == "slow":
            time.sleep(0.2)
        if mode == "hold":
            state.entered.set()
            state.release.wait(timeout=5)
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            base = {
                "id": "chatcmpl-scenario",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "scenario-model",
            }
            for content, reason in [("synthetic ", None), ("answer", "stop")]:
                value = {
                    **base,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": content},
                            "finish_reason": reason,
                        }
                    ],
                }
                self.wfile.write(f"data: {json.dumps(value)}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.02)
            value = {
                **base,
                "choices": [],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            }
            self.wfile.write(f"data: {json.dumps(value)}\n\ndata: [DONE]\n\n".encode())
            self.wfile.flush()
            return
        self.reply(
            200,
            {
                "id": "chatcmpl-scenario",
                "object": "chat.completion",
                "created": 1,
                "model": "scenario-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "synthetic answer"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            },
        )


@contextmanager
def serving(app):
    listener = bind_listener("127.0.0.1", 0)
    base = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        for _ in range(100):
            if server.started:
                break
            if not worker.is_alive():
                raise RuntimeError("Scenario server failed to start")
            time.sleep(0.05)
        else:
            raise RuntimeError("Scenario server startup timed out")
        yield base
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
        if worker.is_alive():
            raise RuntimeError("Scenario server failed to stop")


def exercise():
    results = []
    state = InferenceState()
    inference = ThreadingHTTPServer(("127.0.0.1", 0), Inference)
    inference.scenario_state = state
    worker = threading.Thread(target=inference.serve_forever, daemon=True)
    worker.start()
    variable = "M87_SCENARIO_OPERATOR_KEY"
    previous = os.environ.get(variable)
    os.environ[variable] = secrets.token_urlsafe(32)
    model = "openai_compatible:scenario-model"
    try:
        with tempfile.TemporaryDirectory(prefix="m87-controls-") as temporary:
            settings = local_settings(Path(temporary))
            settings.control_plane.admin_api_key_env = variable
            settings.observability.json_logs = False
            gateway = create_app(settings)
            with (
                serving(gateway) as gateway_url,
                httpx.Client(
                    base_url=gateway_url,
                    timeout=10,
                    trust_env=False,
                    headers={"Authorization": f"Bearer {os.environ[variable]}"},
                ) as operator,
            ):

                def save(path, body, method="PUT"):
                    response = operator.request(method, "/admin/api/" + path, json=body)
                    response.raise_for_status()
                    return response.json() if response.content else None

                endpoint = f"http://127.0.0.1:{inference.server_port}/v1"

                def connection(enabled=True, timeout=2):
                    save(
                        "connections/openai_compatible",
                        {
                            "config": {
                                "base_url": endpoint,
                                "timeout_seconds": timeout,
                                "enabled": enabled,
                            }
                        },
                    )

                assert operator.get("/ready").status_code == 503
                connection()
                save("setup", {"default_model": model, "capture_content": True})
                assert operator.get("/ready").status_code == 200
                assert operator.get("/admin/api/connections/openai_compatible/models").json()[
                    "items"
                ] == [model]
                app_key = save(
                    "apps", {"app_id": "scenario-app", "allowed_models": ["auto", model]}, "POST"
                )["api_key"]
                with httpx.Client(base_url=gateway_url, trust_env=False) as caller:
                    models = caller.get(
                        "/v1/models", headers={"Authorization": f"Bearer {app_key}"}
                    )
                    assert [item["id"] for item in models.json()["data"]] == ["auto", model]
                    parameters = caller.post(
                        "/v1/chat/completions",
                        headers={"Authorization": f"Bearer {app_key}"},
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": "Synthetic parameter test"}],
                            "top_p": 0.7,
                            "stop": ["END"],
                            "seed": 1,
                            "presence_penalty": 0.1,
                            "frequency_penalty": 0.1,
                            "response_format": {"type": "text"},
                            "user": "synthetic-user",
                        },
                    )
                    assert parameters.status_code == 200
                results.append(
                    {
                        "scenario": "Application model catalog and generation parameters",
                        "passed": True,
                    }
                )
                controls = operator.get("/admin/api/controls").json()

                def configure(**updates):
                    controls.update(updates)
                    save("controls", controls)
                    controls.update(operator.get("/admin/api/controls").json())

                def limits(rpm=None, concurrent=None):
                    save(
                        "apps/scenario-app/limits",
                        {"rate_limit_per_minute": rpm, "max_concurrent_requests": concurrent},
                        "PATCH",
                    )

                with serving(sample_app(Settings(gateway_url=gateway_url, app_key=app_key))) as url:
                    with httpx.Client(base_url=url, timeout=10, trust_env=False) as browser:

                        def chat(prompt="Synthetic scenario question"):
                            return browser.post(
                                "/api/chat",
                                json={"messages": [{"role": "user", "content": prompt}]},
                            )

                        def detail(response):
                            request_id = response.json()["request_id"]
                            for _ in range(100):
                                record = operator.get("/admin/api/logs/" + request_id)
                                if record.status_code == 200:
                                    return record.json()
                                time.sleep(0.01)
                            raise AssertionError("Request audit event was not stored")

                        first = chat()
                        assert first.status_code == 200
                        event = detail(first)
                        assert event["request_content"] and event["response_content"]
                        assert event["total_tokens"] == 6
                        results.append(
                            {
                                "scenario": "Successful completion and input/output logs",
                                "passed": True,
                            }
                        )

                        with browser.stream(
                            "POST",
                            "/api/chat/stream",
                            json={
                                "messages": [
                                    {"role": "user", "content": "Synthetic streaming question"}
                                ]
                            },
                        ) as streamed:
                            assert streamed.status_code == 200
                            request_id = streamed.headers["x-request-id"]
                            frames = [
                                json.loads(line[6:])
                                for line in streamed.iter_lines()
                                if line.startswith("data: ") and line != "data: [DONE]"
                            ]
                            assert (
                                "".join(
                                    choice["delta"].get("content", "")
                                    for frame in frames
                                    for choice in frame["choices"]
                                )
                                == "synthetic answer"
                            )
                            assert frames[-1]["usage"]["total_tokens"] == 6
                        for _ in range(100):
                            record = operator.get("/admin/api/logs/" + request_id)
                            if record.status_code == 200:
                                break
                            time.sleep(0.01)
                        record.raise_for_status()
                        assert record.json()["request_outcome"] == "completed"
                        assert (
                            record.json()["streaming"]
                            and not record.json()["response_content_partial"]
                        )
                        assert record.json()["response_content"]
                        results.append(
                            {
                                "scenario": "Sample streaming, final usage and captured output",
                                "passed": True,
                            }
                        )

                        configure(cache={"enabled": True, "ttl_seconds": 300, "max_entries": 10})
                        calls = state.calls
                        miss, hit = chat(), chat()
                        assert miss.json()["cache_status"] == "MISS"
                        assert hit.json()["cache_status"] == "HIT" and state.calls == calls + 1
                        assert detail(hit)["provider_attempts"] == 0
                        tokens = operator.get("/admin/api/overview").json()["total_tokens"]
                        assert (
                            tokens == 24
                        )  # Parameter test, complete/streamed replies and one cache miss.
                        operator.post("/admin/api/cache/clear").raise_for_status()
                        assert chat().json()["cache_status"] == "MISS"
                        results.append(
                            {
                                "scenario": "Cache hits, clear and provider token accounting",
                                "passed": True,
                            }
                        )

                        configure(cache={"enabled": False, "ttl_seconds": 300, "max_entries": 10})
                        limits(rpm=1)
                        assert chat().status_code == 200
                        rejected = chat()
                        assert rejected.status_code == 429 and rejected.json()["retry_after"] >= 1
                        assert detail(rejected)["error_type"] == "rate_limit_exceeded"
                        limits()
                        assert chat().status_code == 200
                        results.append(
                            {
                                "scenario": "Rate rejection and recovery without replacing the key",
                                "passed": True,
                            }
                        )

                        limits(concurrent=1)
                        state.mode = "hold"
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            pending = pool.submit(chat)
                            try:
                                assert state.entered.wait(timeout=3)
                                rejected = chat("Concurrent request")
                                assert rejected.status_code == 429
                                assert (
                                    detail(rejected)["error_type"] == "concurrency_limit_exceeded"
                                )
                            finally:
                                state.release.set()
                            assert pending.result(timeout=5).status_code == 200
                        state.mode = "healthy"
                        limits()
                        assert chat().status_code == 200
                        results.append(
                            {
                                "scenario": "Concurrent request rejection and slot recovery",
                                "passed": True,
                            }
                        )

                        configure(
                            limits={
                                "max_concurrent_requests": 1,
                                "queue_max_depth": 1,
                                "queue_max_depth_per_app": 1,
                                "queue_wait_timeout_seconds": 2,
                            }
                        )
                        state.entered.clear()
                        state.release.clear()
                        state.mode = "hold"
                        with ThreadPoolExecutor(max_workers=2) as pool:
                            active = pool.submit(chat, "Active request")
                            waiting = None
                            try:
                                assert state.entered.wait(timeout=3)
                                waiting = pool.submit(chat, "Queued request")
                                for _ in range(100):
                                    if (
                                        operator.get("/admin/api/diagnostics").json()[
                                            "queued_requests"
                                        ]
                                        == 1
                                    ):
                                        break
                                    time.sleep(0.01)
                                else:
                                    raise AssertionError("Request did not enter queue")
                                rejected = chat("Full queue request")
                                assert rejected.status_code == 429
                                assert detail(rejected)["error_type"] == "queue_full"
                            finally:
                                state.release.set()
                            assert active.result(timeout=5).status_code == 200
                            queued = waiting.result(timeout=5)
                            assert queued.status_code == 200
                            record = detail(queued)
                            assert record["queue_outcome"] == "admitted"
                            assert record["queue_wait_ms"] > 0
                        state.mode = "healthy"
                        configure(limits={"max_concurrent_requests": 64, "queue_max_depth": 0})
                        assert operator.get("/admin/api/diagnostics").json()["queued_requests"] == 0
                        results.append(
                            {
                                "scenario": "Bounded queue, overflow and slot recovery",
                                "passed": True,
                            }
                        )

                        configure(retry={"max_attempts": 2, "backoff_ms": 0})
                        state.failures = 1
                        assert detail(chat())["provider_attempts"] == 2
                        state.mode = "outage"
                        failed = chat()
                        assert (
                            failed.status_code == 502 and detail(failed)["provider_attempts"] == 2
                        )
                        state.mode = "healthy"
                        assert chat().status_code == 200
                        results.append(
                            {
                                "scenario": "Transient retry, exhausted outage and recovery",
                                "passed": True,
                            }
                        )

                        configure(retry={"max_attempts": 1, "backoff_ms": 0})
                        connection(timeout=0.05)
                        state.mode = "slow"
                        timed_out = chat()
                        assert timed_out.status_code == 504
                        assert detail(timed_out)["error_type"] == "provider_timeout"
                        state.mode = "healthy"
                        connection()
                        assert chat().status_code == 200
                        results.append(
                            {"scenario": "Provider timeout and recovery", "passed": True}
                        )

                        connection(enabled=False)
                        assert operator.get("/health").status_code == 200
                        assert operator.get("/ready").status_code == 503
                        assert detail(chat())["error_type"] == "provider_disabled"
                        connection()
                        assert operator.get("/ready").status_code == 200
                        results.append(
                            {
                                "scenario": "Disabled connection, readiness diagnostics and recovery",
                                "passed": True,
                            }
                        )

                        configure(max_message_chars=8)
                        blocked = chat()
                        assert (
                            blocked.status_code == 400 and not detail(blocked)["provider_attempted"]
                        )
                        configure(max_message_chars=65536, max_request_bytes=64)
                        blocked = chat()
                        assert blocked.status_code == 413 and not detail(blocked)["request_content"]
                        configure(max_request_bytes=262144, max_content_chars=16)
                        truncated = detail(chat())
                        assert (
                            truncated["request_content_truncated"]
                            and truncated["response_content_truncated"]
                        )
                        results.append(
                            {"scenario": "Request bounds and capture truncation", "passed": True}
                        )

                # Restart uses the same private database but a new listener.
            restarted = create_app(settings)
            with (
                serving(restarted) as url,
                httpx.Client(
                    base_url=url,
                    trust_env=False,
                    timeout=5,
                    headers={"Authorization": f"Bearer {os.environ[variable]}"},
                ) as operator,
            ):
                assert operator.get("/admin/api/controls").json() == controls
                assert operator.get("/ready").status_code == 200
                assert restarted.state.control_store.authenticate_app_key(app_key)
                assert operator.get("/admin/api/logs").json()["items"]
                usage_before = operator.get("/admin/api/overview").json()
                response = operator.request(
                    "DELETE", "/admin/api/logs", json={"confirmation": "DELETE"}
                )
                assert response.json()["deleted"] > 0
                assert operator.get("/admin/api/logs").json()["items"] == []
                usage_after = operator.get("/admin/api/overview").json()
                for field in ("requests", "total_tokens", "cache_hits", "usage_unknown"):
                    assert usage_after[field] == usage_before[field]
                assert restarted.state.control_store.authenticate_app_key(app_key)
                results.append(
                    {
                        "scenario": "Restart persistence and log deletion preserving keys",
                        "passed": True,
                    }
                )
                revisions = operator.get("/admin/api/configuration/revisions").json()
                target = revisions["current_revision"]
                changed_controls = {**controls, "max_content_chars": 64}
                operator.put("/admin/api/controls", json=changed_controls).raise_for_status()
                current = operator.get("/admin/api/configuration/revisions").json()[
                    "current_revision"
                ]
                restored = operator.post(
                    f"/admin/api/configuration/revisions/{target}/restore",
                    json={"expected_revision": current, "confirmation": "RESTORE"},
                )
                restored.raise_for_status()
                assert operator.get("/admin/api/controls").json() == controls
                assert (
                    operator.post(
                        f"/admin/api/configuration/revisions/{target}/restore",
                        json={"expected_revision": current, "confirmation": "RESTORE"},
                    ).status_code
                    == 409
                )
                with serving(sample_app(Settings(gateway_url=url, app_key=app_key))) as sample_url:
                    with httpx.Client(base_url=sample_url, timeout=10, trust_env=False) as browser:
                        response = browser.post(
                            "/api/chat",
                            json={
                                "messages": [
                                    {"role": "user", "content": "Synthetic restored configuration"}
                                ]
                            },
                        )
                        assert response.status_code == 200
                        assert response.json()["usage"]["total_tokens"] == 6
                events = operator.get("/admin/api/management-events").json()["items"]
                assert any(
                    event["action"] == "configuration.restored" and event["restored_from"] == target
                    for event in events
                )
                assert app_key not in json.dumps(events)
                results.append(
                    {
                        "scenario": "Configuration restore, stale revision rejection and sample recovery",
                        "passed": True,
                    }
                )
                usage_before = operator.get("/admin/api/overview").json()
                events_before = operator.get("/admin/api/management-events").json()
                storage = operator.post("/admin/api/storage/check").json()
                assert storage["ok"] and storage["verified"]
                assert operator.get("/admin/api/overview").json() == usage_before
                assert operator.get("/admin/api/management-events").json() == events_before
                assert restarted.state.control_store.authenticate_app_key(app_key)
                results.append(
                    {
                        "scenario": "Storage verification preserves keys, usage and management audit",
                        "passed": True,
                    }
                )
                path = "/admin/api/apps/scenario-app/keys"
                existing = operator.get(path).json()["items"][0]
                issued = operator.post(path, json={"expires_in_days": 30})
                issued.raise_for_status()
                replacement = issued.json()
                assert restarted.state.control_store.authenticate_app_key(app_key)
                with serving(
                    sample_app(Settings(gateway_url=url, app_key=replacement["api_key"]))
                ) as sample_url:
                    with httpx.Client(base_url=sample_url, timeout=10, trust_env=False) as browser:
                        payload = {"messages": [{"role": "user", "content": "rotation"}]}
                        assert browser.post("/api/chat", json=payload).status_code == 200
                        revoked = operator.delete(path + "/" + existing["key_id"])
                        assert revoked.status_code == 204
                        assert restarted.state.control_store.authenticate_app_key(app_key) is None
                        assert browser.post("/api/chat", json=payload).status_code == 200
                events = operator.get("/admin/api/management-events").json()["items"]
                assert any(
                    e["action"] == "application_key.revoked" and e["key_id"] == existing["key_id"]
                    for e in events
                )
                results.append(
                    {"scenario": "Sample replacement key, overlap and revocation", "passed": True}
                )
        return results
    finally:
        state.release.set()
        inference.shutdown()
        inference.server_close()
        worker.join(timeout=5)
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous


def main():
    for result in exercise():
        print(f"PASS: {result['scenario']}")
    print("Temporary gateway, sample, inference and data cleaned up.")


if __name__ == "__main__":
    main()
