import asyncio

import httpx
import pytest

from m87_gateway.api import routes
from m87_gateway.api.errors import GatewayError
from m87_gateway.config import GatewaySettings
from m87_gateway.controls import ExactResponseCache, SlidingWindowRateLimiter
from m87_gateway.logging import middleware
from m87_gateway.main import create_app


def test_rate_limit_window_and_app_isolation():
    now = [0.0]
    limiter = SlidingWindowRateLimiter(clock=lambda: now[0])
    assert limiter.check("one", 1) is None
    assert limiter.check("one", 1) == 60
    assert limiter.check("two", 1) is None
    now[0] = 60
    assert limiter.check("one", 1) is None


def test_cache_ttl_eviction_and_copy_isolation():
    now = [0.0]
    cache = ExactResponseCache(True, 5, 1, clock=lambda: now[0])
    cache.put("one", {"text": "original"})
    cached = cache.get("one")
    cached["text"] = "changed"
    assert cache.get("one")["text"] == "original"
    cache.put("two", {"text": "second"})
    assert cache.get("one") is None
    now[0] = 5
    assert cache.get("two") is None
    assert cache.key("one", "ollama:test", {}) != cache.key("two", "ollama:test", {})


@pytest.mark.parametrize("failure", [None, "provider_timeout", "provider_rejected", "exhausted"])
def test_chat_controls_enforce_limits_cache_and_retry(monkeypatch, failure):
    calls = []
    events = []

    class Provider:
        async def chat_completions(self, payload, model):
            calls.append(model)
            if failure == "exhausted" or (failure and len(calls) == 1):
                code = "provider_timeout" if failure == "exhausted" else failure
                raise GatewayError(502, code, "Safe provider failure")
            return {
                "id": "test",
                "created": 1,
                "model": "ollama:test",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }

    monkeypatch.setattr(routes, "get_provider", lambda *args: Provider())

    async def inline(function, *args):
        return function(*args)

    monkeypatch.setattr(middleware, "run_in_threadpool", inline)
    settings = GatewaySettings(
        apps=[
            {
                "app_id": "test",
                "api_key": "test-key",
                "allowed_models": ["auto", "ollama:test"],
                "rate_limit_per_minute": 2,
            }
        ],
        routing={"default_model": "ollama:test"},
        cache={"enabled": True},
        retry={"max_attempts": 2, "backoff_ms": 0},
    )
    app = create_app(settings)

    async def scenario():
        async with app.router.lifespan_context(app):
            app.state.recorder.record = lambda event, *args: events.append(dict(event))
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:

                async def chat():
                    return await client.post(
                        "/v1/chat/completions",
                        headers={"Authorization": "Bearer test-key"},
                        json={"model": "auto", "messages": [{"role": "user", "content": "hello"}]},
                    )

                first = await chat()
                if failure in {"provider_rejected", "exhausted"}:
                    assert first.status_code == 502
                    assert len(calls) == (2 if failure == "exhausted" else 1)
                    return
                assert first.status_code == 200
                assert first.headers["x-gateway-cache"] == "MISS"
                second = await chat()
                assert second.status_code == 200
                assert second.headers["x-gateway-cache"] == "HIT"
                assert first.headers["x-request-id"] != second.headers["x-request-id"]
                assert len(calls) == (2 if failure else 1)
                rejected = await chat()
                assert rejected.status_code == 429
                assert int(rejected.headers["retry-after"]) >= 1
                assert events[1]["cache_status"] == "hit"
                assert events[1]["provider_attempts"] == 0
                assert events[0]["provider_retries"] == (1 if failure else 0)
                metrics = app.state.metrics.render().decode()
                assert 'm87_gateway_tokens_total{kind="prompt",provider="ollama"} 3.0' in metrics

    asyncio.run(scenario())
