import asyncio
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

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
        }
        audit = state["audit"]
        started = perf_counter()
        status = 500
        response_started = False
        is_chat = scope["path"] == "/v1/chat/completions" and scope["method"] == "POST"
        runtime = scope["app"].state
        settings = runtime.settings

        async def tracked_send(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                message = dict(message)
                message["headers"] = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ] + [(b"x-request-id", request_id.encode())]
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
                        audit["error_type"] = "client_disconnected"
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

                async def replay():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                downstream_receive = replay
            await self.app(scope, downstream_receive, tracked_send)
        except asyncio.CancelledError:
            status = 499
            audit["error_type"] = "client_disconnected"
            raise
        except Exception:
            audit["error_type"] = "internal_error"
            if not response_started:
                await reject(
                    GatewayError(500, "internal_error", "Gateway could not complete the request")
                )
            else:
                raise
        finally:
            if is_chat:
                audit["status_code"] = status
                audit["latency_ms"] = round((perf_counter() - started) * 1000, 3)
                if settings.observability.prometheus_metrics:
                    runtime.metrics.observe(audit)
                await run_in_threadpool(
                    runtime.recorder.record,
                    audit,
                    state.get("request_content"),
                    state.get("response_content"),
                )
