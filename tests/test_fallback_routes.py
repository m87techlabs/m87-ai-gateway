"""Fallback routes: when they fire, when they must not, and how they are recorded."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from m87_gateway.cli import local_settings
from m87_gateway.config.settings import FallbackRuleConfig, RoutingConfig
from m87_gateway.main import create_app
from test_runtime import completion

KEY = "fallback-test-admin-key-long-enough"
ADMIN = {"Authorization": f"Bearer {KEY}"}
PRIMARY = "ollama:primary"
BACKUP = "openai:backup"


def sse(value):
    return f"data: {json.dumps(value)}\n\n".encode()


def chunk(content="", finish=None):
    return {
        "id": "stream",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "upstream",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": finish,
            }
        ],
    }


class Upstreams:
    """The primary is a local Ollama, the backup a cloud provider. Tests decide how each behaves."""

    def __init__(self):
        self.primary = "ok"
        self.backup = "ok"
        self.calls = []

    def answer(self, mode, name, stream):
        if mode == "down":
            raise httpx.ConnectError("connection refused")
        if mode == "slow":
            raise httpx.ReadTimeout("timed out")
        if isinstance(mode, int):
            return httpx.Response(mode, json={"error": {"message": "upstream says no"}})
        if stream:
            body = sse(chunk(f"from {name} ")) + sse(chunk("done", "stop")) + b"data: [DONE]\n\n"
            return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
        usage = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
        return httpx.Response(200, json=completion(f"from {name}", usage))

    def __call__(self, request):
        name = "primary" if request.url.host == "primary.test" else "backup"
        stream = b'"stream":true' in request.content or b'"stream": true' in request.content
        self.calls.append(name)
        return self.answer(self.primary if name == "primary" else self.backup, name, stream)


@pytest.fixture
def upstreams():
    return Upstreams()


@pytest.fixture
def make(tmp_path, monkeypatch, upstreams):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", KEY)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-provider-credential")
    original = httpx.AsyncClient

    def client(**kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(upstreams))
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)

    def build(enabled=True, rules=((PRIMARY, BACKUP),), allowed=(PRIMARY, BACKUP), retries=1):
        settings = local_settings(tmp_path)
        settings.observability.json_logs = False
        settings.providers.ollama.enabled = True
        settings.providers.ollama.base_url = "http://primary.test:11434"
        settings.providers.openai.enabled = True
        settings.providers.openai.base_url = "https://backup.test/v1"
        settings.providers.openai.api_key_env = "OPENAI_API_KEY"
        settings.retry.max_attempts = retries
        settings.routing = RoutingConfig(
            default_model=PRIMARY,
            fallback_enabled=enabled,
            fallbacks=[FallbackRuleConfig(model=m, fallback=f) for m, f in rules],
        )
        browser = TestClient(create_app(settings), base_url="http://localhost")
        browser.__enter__()
        created = browser.post(
            "/admin/api/apps",
            json={"app_id": "horizon", "allowed_models": list(allowed)},
            headers=ADMIN,
        )
        browser.app_headers = {"Authorization": f"Bearer {created.json()['api_key']}"}
        return browser

    clients = []

    def tracked(**kwargs):
        browser = build(**kwargs)
        clients.append(browser)
        return browser

    yield tracked
    for browser in clients:
        browser.__exit__(None, None, None)


def ask(browser, model=PRIMARY, **extra):
    return browser.post(
        "/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": "hello"}], **extra},
        headers=browser.app_headers,
    )


def last_event(browser):
    request_id = browser.get("/admin/api/logs", headers=ADMIN).json()["items"][0]["request_id"]
    return browser.get(f"/admin/api/logs/{request_id}", headers=ADMIN).json()


# ---- When a fallback is used


@pytest.mark.parametrize("failure", ["down", "slow", 500, 502, 503, 429])
def test_falls_back_on_failures_another_provider_could_avoid(make, upstreams, failure):
    browser = make()
    upstreams.primary = failure
    response = ask(browser)
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "from backup"
    assert response.json()["model"] == BACKUP
    assert response.headers["X-Gateway-Fallback"] == PRIMARY
    assert upstreams.calls == ["primary", "backup"]


def test_the_log_says_which_model_answered_and_why(make, upstreams):
    browser = make()
    upstreams.primary = "down"
    ask(browser)
    event = last_event(browser)
    assert event["routed_model"] == BACKUP and event["provider"] == "openai"
    assert event["fallback_from"] == PRIMARY
    assert event["provider_attempts"] == 2
    assert event["status_code"] == 200


def test_usage_is_counted_against_the_model_that_answered(make, upstreams):
    browser = make()
    upstreams.primary = "down"
    ask(browser)
    usage = browser.get("/admin/api/usage", headers=ADMIN).json()
    assert [row["model"] for row in usage["by_model"]] == [BACKUP]


def test_metrics_count_the_fallback_and_blame_the_first_provider(make, upstreams):
    browser = make()
    upstreams.primary = "down"
    ask(browser)
    text = browser.get("/metrics").text
    assert (
        'm87_gateway_fallbacks_total{app_id="horizon",from_provider="ollama",to_provider="openai"} 1.0'
        in text
    )
    assert 'm87_gateway_provider_errors_total{app_id="horizon",provider="ollama"} 1.0' in text


def test_retries_happen_before_falling_back(make, upstreams):
    browser = make(retries=2)
    upstreams.primary = 503
    assert ask(browser).status_code == 200
    assert upstreams.calls == ["primary", "primary", "backup"]
    assert last_event(browser)["provider_attempts"] == 3


def test_fallbacks_are_tried_in_order(make, upstreams):
    browser = make(
        rules=((PRIMARY, "openai:first"), (PRIMARY, BACKUP)),
        allowed=(PRIMARY, "openai:first", BACKUP),
    )
    upstreams.primary = "down"
    upstreams.backup = 503
    response = ask(browser)
    assert response.status_code == 502
    assert upstreams.calls == ["primary", "backup", "backup"]
    assert last_event(browser)["fallback_from"] == PRIMARY


def test_the_primary_is_tried_first_again_once_it_recovers(make, upstreams):
    browser = make()
    upstreams.primary = "down"
    ask(browser)
    upstreams.primary = "ok"
    response = ask(browser)
    assert response.json()["choices"][0]["message"]["content"] == "from primary"
    assert "X-Gateway-Fallback" not in response.headers
    assert upstreams.calls == ["primary", "backup", "primary"]


def test_a_fallback_answer_is_not_cached_as_the_primary(make, upstreams):
    browser = make()
    browser.put(
        "/admin/api/features/response_cache",
        json={"enabled": True},
        headers={
            **ADMIN,
            "If-Match": browser.get("/admin/api/features", headers=ADMIN).headers["etag"],
        },
    )
    upstreams.primary = "down"
    ask(browser)
    upstreams.primary = "ok"
    assert ask(browser).json()["choices"][0]["message"]["content"] == "from primary"


def test_streams_fall_back_before_the_first_token(make, upstreams):
    browser = make()
    upstreams.primary = "down"
    response = ask(browser, stream=True)
    assert response.status_code == 200
    assert "from backup" in response.text and "from primary" not in response.text
    assert all(
        json.loads(line[6:])["model"] == BACKUP
        for line in response.text.splitlines()
        if line.startswith("data: {")
    )
    assert last_event(browser)["fallback_from"] == PRIMARY


def test_auto_falls_back_from_the_model_it_chose(make, upstreams):
    browser = make(allowed=("auto", PRIMARY, BACKUP))
    upstreams.primary = "down"
    response = ask(browser, model="auto")
    assert response.json()["model"] == BACKUP


# ---- When a fallback must not be used


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_never_falls_back_on_a_request_or_key_problem(make, upstreams, status):
    browser = make()
    upstreams.primary = status
    assert ask(browser).status_code == 502
    assert upstreams.calls == ["primary"]
    assert last_event(browser)["fallback_from"] is None


def test_never_falls_back_to_a_model_the_app_may_not_call(make, upstreams):
    browser = make(allowed=(PRIMARY,))
    upstreams.primary = "down"
    assert ask(browser).status_code == 502
    assert upstreams.calls == ["primary"]


def test_does_nothing_while_turned_off(make, upstreams):
    browser = make(enabled=False)
    upstreams.primary = "down"
    assert ask(browser).status_code == 502
    assert upstreams.calls == ["primary"]


def test_only_applies_to_the_model_it_names(make, upstreams):
    browser = make(rules=(("ollama:other", BACKUP),), allowed=(PRIMARY, BACKUP))
    upstreams.primary = "down"
    assert ask(browser).status_code == 502


def test_skips_a_fallback_that_cannot_serve_the_request(make, upstreams, monkeypatch):
    from m87_gateway.api import routes
    from m87_gateway.api.errors import GatewayError

    real = routes.validate_capabilities

    def backup_lacks_it(payload, provider, settings):
        if provider == "openai":
            raise GatewayError(422, "unsupported_parameter", "Not supported")
        return real(payload, provider, settings)

    monkeypatch.setattr(routes, "validate_capabilities", backup_lacks_it)
    browser = make()
    upstreams.primary = "down"
    assert ask(browser).status_code == 502
    assert upstreams.calls == ["primary"]


def test_a_stream_that_has_started_is_not_switched(make, upstreams):
    browser = make()

    def broken(mode, name, stream):
        if name == "primary":
            return httpx.Response(
                200,
                content=sse(chunk("partial ")) + b"data: {not json\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return Upstreams.answer(upstreams, mode, name, stream)

    upstreams.answer = broken
    response = ask(browser, stream=True)
    assert "partial" in response.text and "from backup" not in response.text
    assert upstreams.calls == ["primary"]


def test_embeddings_never_fall_back(make, upstreams):
    browser = make()
    upstreams.primary = "down"
    response = browser.post(
        "/v1/embeddings",
        json={"model": PRIMARY, "input": "hello"},
        headers=browser.app_headers,
    )
    assert response.status_code == 502
    assert upstreams.calls == ["primary"]


# ---- Settings


def test_configuration_is_validated():
    with pytest.raises(ValueError, match="itself"):
        FallbackRuleConfig(model=PRIMARY, fallback=PRIMARY)
    with pytest.raises(ValueError):
        FallbackRuleConfig(model="auto", fallback=BACKUP)
    with pytest.raises(ValueError, match="at most 3"):
        RoutingConfig(
            fallbacks=[FallbackRuleConfig(model=PRIMARY, fallback=f"openai:m{i}") for i in range(4)]
        )
    with pytest.raises(ValueError, match="once"):
        RoutingConfig(fallbacks=[FallbackRuleConfig(model=PRIMARY, fallback=BACKUP)] * 2)


def test_the_console_feature_saves_survives_restart_and_is_audited(make, upstreams, tmp_path):
    browser = make(enabled=False, rules=())
    etag = browser.get("/admin/api/features", headers=ADMIN).headers["etag"]
    saved = browser.put(
        "/admin/api/features/fallback_routes",
        json={"enabled": True, "values": {"routes": [{"model": PRIMARY, "fallback": BACKUP}]}},
        headers={**ADMIN, "If-Match": etag},
    )
    assert saved.status_code == 200, saved.text
    upstreams.primary = "down"
    assert ask(browser).json()["model"] == BACKUP
    item = next(
        entry
        for entry in browser.get("/admin/api/features", headers=ADMIN).json()["items"]
        if entry["id"] == "fallback_routes"
    )
    assert item["enabled"] is True and item["group"] == "reliability"
    assert item["values"]["routes"] == [{"model": PRIMARY, "fallback": BACKUP}]
    actions = {
        e["action"]
        for e in browser.get("/admin/api/management-events", headers=ADMIN).json()["items"]
    }
    assert any(
        "feature" in action or "controls" in action or "updated" in action for action in actions
    )


def test_a_bad_fallback_is_refused_by_the_console(make):
    browser = make(enabled=False, rules=())
    etag = browser.get("/admin/api/features", headers=ADMIN).headers["etag"]
    refused = browser.put(
        "/admin/api/features/fallback_routes",
        json={"values": {"routes": [{"model": PRIMARY, "fallback": PRIMARY}]}},
        headers={**ADMIN, "If-Match": etag},
    )
    assert refused.status_code == 422
