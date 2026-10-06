import asyncio
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4
from m87_gateway.cancellation import monitor_disconnect

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from m87_gateway.api.errors import GatewayError, error_response


class TrafficMiddleware:
    """Bound chat bodies before JSON parsing and record one outcome for every chat attempt."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid4().hex
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        state["audit"] = {
            "schema_version": 1,
            "event": "llm_exchange",
            "request_id": request_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "app_id": None,
            "project_id": None,
            "provider": None,
            "model": None,
            "routed_model": None,
            "guardrail_action": "not_evaluated",
            "guardrail_reason": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "estimated_cost_usd": None,
            "error_type": None,
            "provider_attempted": False,
            "provider_attempts": 0,
            "provider_retries": 0,
            "cache_status": "disabled",
            "streaming": False,
            "request_outcome": None,
            "response_content_partial": False,
        }
        audit = state["audit"]
        started = perf_counter()
        status = 500
        response_started = False
        wire_status = None
        is_chat = scope["path"] == "/v1/chat/completions" and scope["method"] == "POST"
        runtime = scope["app"].state
        settings = runtime.settings

        async def tracked_send(message):
            nonlocal status, response_started, wire_status
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                wire_status = status
                message = dict(message)
                message["headers"] = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower()
                    not in {
                        b"x-request-id",
                        b"x-content-type-options",
                        b"x-frame-options",
                        b"referrer-policy",
                    }
                ] + [
                    (b"x-request-id", request_id.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                ]
                if scope["path"].startswith("/admin"):
                    message["headers"] += [
                        (b"cache-control", b"no-store"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; style-src 'self'; script-src 'self'; "
                            b"connect-src 'self'; img-src 'self' data:",
                        ),
                    ]
            await send(message)

        async def reject(error):
            response = error_response(Request(scope), error)
            await response(scope, receive, tracked_send)

        try:
            downstream_receive = receive
            if is_chat:
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        status = 499
                        audit.update(error_type="client_disconnected", request_outcome="cancelled")
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > settings.guardrails.max_request_bytes:
                        audit.update(guardrail_action="block", guardrail_reason="request_too_large")
                        await reject(
                            GatewayError(413, "request_too_large", "Request body is too large")
                        )
                        return
                    if not message.get("more_body", False):
                        break
                delivered = False
                disconnected = asyncio.Event()

                async def is_disconnected():
                    return disconnected.is_set()

                state["is_disconnected"] = is_disconnected

                async def replay():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    await disconnected.wait()
                    return {"type": "http.disconnect"}

                downstream_receive = replay
            if not is_chat:
                await self.app(scope, downstream_receive, tracked_send)
            else:
                if await monitor_disconnect(
                    self.app(scope, downstream_receive, tracked_send), receive, disconnected
                ):
                    status = 499
                    audit.update(error_type="client_disconnected", request_outcome="cancelled")
        except asyncio.CancelledError:
            status = 499
            audit.update(error_type="client_disconnected", request_outcome="cancelled")
            raise
        except Exception:
            audit.update(
                error_type="internal_error", request_outcome="failed", outcome_status_code=500
            )
            if not response_started:
                await reject(
                    GatewayError(500, "internal_error", "Gateway could not complete the request")
                )
            else:
                raise
        finally:
            if is_chat:
                audit["http_status_code"] = wire_status
                audit["status_code"] = (
                    499
                    if audit.get("request_outcome") == "cancelled"
                    else audit.get("outcome_status_code", status)
                )
                audit["request_outcome"] = audit.get("request_outcome") or (
                    "completed" if status < 400 else "failed"
                )
                audit["latency_ms"] = round((perf_counter() - started) * 1000, 3)
                if settings.observability.prometheus_metrics:
                    runtime.metrics.observe(audit)
                await run_in_threadpool(
                    runtime.recorder.record,
                    audit,
                    state.get("request_content"),
                    state.get("response_content"),
                )
