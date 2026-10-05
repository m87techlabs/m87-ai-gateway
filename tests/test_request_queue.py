import asyncio

import pytest

from m87_gateway.api.errors import GatewayError
from m87_gateway.controls import InFlightLimiter
from m87_gateway.metrics import GatewayMetrics


async def until_queued(limiter, count):
    for _ in range(100):
        if limiter.snapshot()["queued_requests"] == count:
            return
        await asyncio.sleep(0.001)
    pytest.fail("Queue did not reach expected depth")


def test_queue_fifo_full_metrics_and_release():
    async def scenario():
        metrics = GatewayMetrics()
        limiter = InFlightLimiter(metrics)
        order = []
        audits = [{}, {}]

        async def work(index):
            async with limiter.admit_wait("app", 1, 1, 2, 2, 1, audit=audits[index]):
                order.append(index)

        async with limiter.admit_wait("active", 1, None):
            first = asyncio.create_task(work(0))
            await until_queued(limiter, 1)
            second = asyncio.create_task(work(1))
            await until_queued(limiter, 2)
            with pytest.raises(GatewayError) as failure:
                async with limiter.admit_wait("third", 1, None, 2, 2, 1):
                    pytest.fail("Full queue accepted request")
            assert failure.value.code == "queue_full"
            assert failure.value.headers["Retry-After"] == "1"
            assert "m87_gateway_queue_depth 2.0" in metrics.render().decode()
        await asyncio.gather(first, second)
        assert order == [0, 1]
        assert all(a["queue_outcome"] == "admitted" for a in audits)
        assert limiter.snapshot() == {"active_requests": 0, "queued_requests": 0}
        output = metrics.render().decode()
        assert 'm87_gateway_queue_wait_seconds_count{outcome="admitted"} 2.0' in output
        assert 'm87_gateway_queue_wait_seconds_count{outcome="full"} 1.0' in output

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["timeout", "cancelled", "disconnected"])
def test_waiter_cleanup(outcome):
    async def scenario():
        metrics = GatewayMetrics()
        limiter = InFlightLimiter(metrics)
        audit = {}

        async def disconnected():
            return outcome == "disconnected"

        async def wait():
            async with limiter.admit_wait(
                "waiting", 1, None, 1, 1, 0.02, disconnected=disconnected, audit=audit
            ):
                pytest.fail("Waiter admitted before release")

        async with limiter.admit_wait("active", 1, None):
            task = asyncio.create_task(wait())
            if outcome == "cancelled":
                await until_queued(limiter, 1)
                task.cancel()
            if outcome == "timeout":
                with pytest.raises(GatewayError) as failure:
                    await task
                assert failure.value.code == "queue_timeout"
            else:
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert limiter.snapshot()["queued_requests"] == 0
        expected = "timeout" if outcome == "timeout" else "cancelled"
        assert audit["queue_outcome"] == expected
        assert (
            f'm87_gateway_queue_wait_seconds_count{{outcome="{expected}"}} 1.0'
            in metrics.render().decode()
        )
        assert limiter.snapshot()["active_requests"] == 0

    asyncio.run(scenario())


def test_per_app_bound_and_eligible_fifo():
    async def scenario():
        limiter = InFlightLimiter()
        entered = []

        async def wait():
            async with limiter.admit_wait("one", 2, 1, 4, 1, 1):
                entered.append("one")

        async with limiter.admit_wait("one", 2, 1):
            task = asyncio.create_task(wait())
            await until_queued(limiter, 1)
            with pytest.raises(GatewayError) as failure:
                async with limiter.admit_wait("one", 2, 1, 4, 1, 1):
                    pytest.fail("Per-app queue bound bypassed")
            assert failure.value.code == "queue_full"
            async with limiter.admit_wait("two", 2, 1, 4, 1, 1):
                entered.append("two")
        await task
        assert entered == ["two", "one"]
        with pytest.raises(RuntimeError):
            async with limiter.admit_wait("failure", 1, None):
                raise RuntimeError("synthetic")
        assert limiter.snapshot() == {"active_requests": 0, "queued_requests": 0}

    asyncio.run(scenario())


def test_queued_http_requests_keep_connection_and_cache_snapshot(tmp_path, monkeypatch):
    import hashlib
    import httpx
    from m87_gateway.api import routes
    from m87_gateway.cli import local_settings
    from m87_gateway.main import create_app
    from test_control_api import FakeProvider

    operator_key = "synthetic-snapshot-operator-key"
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", operator_key)
    calls = []
    entered = None
    release = None

    class Provider(FakeProvider):
        def __init__(self, endpoint, credential):
            self.endpoint = endpoint
            self.credential = credential

        async def chat_completions(self, payload, model):
            calls.append((self.endpoint, self.credential))
            if len(calls) == 1:
                entered.set()
                await release.wait()
            return await super().chat_completions(payload, model)

    monkeypatch.setattr(
        routes,
        "get_provider",
        lambda name, settings, store: Provider(
            settings.providers.for_adapter(name).base_url, store.get_provider_key(name)
        ),
    )

    async def scenario():
        nonlocal entered, release
        entered, release = asyncio.Event(), asyncio.Event()
        settings = local_settings(tmp_path)
        settings.observability.json_logs = False
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                operator = {"Authorization": f"Bearer {operator_key}"}

                async def connection(endpoint, key):
                    response = await client.put(
                        "/admin/api/connections/ollama",
                        headers=operator,
                        json={"config": {"enabled": True, "base_url": endpoint}, "key": key},
                    )
                    assert response.status_code == 204, response.text

                await connection("http://old", "synthetic-old-credential")
                controls = (await client.get("/admin/api/controls", headers=operator)).json()
                controls["limits"].update(max_concurrent_requests=1, queue_max_depth=2)
                controls["cache"]["enabled"] = True
                assert (
                    await client.put("/admin/api/controls", headers=operator, json=controls)
                ).status_code == 204
                issued = await client.post(
                    "/admin/api/apps",
                    headers=operator,
                    json={"app_id": "queued-snapshot", "allowed_models": ["ollama:test"]},
                )
                key = issued.json()["api_key"]

                async def chat(prompt):
                    return await client.post(
                        "/v1/chat/completions",
                        headers={"Authorization": f"Bearer {key}"},
                        json={
                            "model": "ollama:test",
                            "messages": [{"role": "user", "content": prompt}],
                            "user": "synthetic-correlation",
                        },
                    )

                first = asyncio.create_task(chat("first"))
                await asyncio.wait_for(entered.wait(), timeout=1)
                waiting = asyncio.create_task(chat("second"))
                try:
                    await until_queued(app.state.inflight_limiter, 1)
                    await connection("http://new", "synthetic-new-credential")
                finally:
                    release.set()
                assert (await first).status_code == 200
                result = await waiting
                assert result.status_code == 200
                event = app.state.control_store.get_event(result.headers["x-request-id"])
                assert event["queue_outcome"] == "admitted"
                assert (
                    event["client_user_hash"]
                    == hashlib.sha256(b"synthetic-correlation").hexdigest()
                )
                assert "synthetic-correlation" not in str(event)
                assert (await chat("second")).status_code == 200
                assert calls == [
                    ("http://old", "synthetic-old-credential"),
                    ("http://old", "synthetic-old-credential"),
                    ("http://new", "synthetic-new-credential"),
                ]
                assert (await chat("second")).headers["x-gateway-cache"] == "HIT"
                assert len(calls) == 3
                assert app.state.inflight_limiter.snapshot() == {
                    "active_requests": 0,
                    "queued_requests": 0,
                }

    asyncio.run(scenario())
