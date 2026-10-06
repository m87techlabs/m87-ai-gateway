"""SSE response lifecycle: admission, backpressure, bounded capture and safe errors."""

import asyncio
import json
from contextlib import aclosing

from starlette.responses import Response

from m87_gateway.api.errors import GatewayError, error_response
from m87_gateway.providers.streaming import validate_chunk, invalid_stream


def event(value):
    return f"data: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()


class ChatStreamResponse(Response):
    media_type = "text/event-stream"

    def __init__(self, request, payload, app_context, settings, prepared):
        super().__init__(
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
                "X-Gateway-Cache": "BYPASS",
            }
        )
        del self.headers["content-length"]
        self.request = request
        self.payload = payload
        self.app_context = app_context
        self.settings = settings
        self.prepared = prepared

    async def __call__(self, scope, receive, send):
        # Fetch before sending headers so initial provider/admission errors retain JSON status.
        async with aclosing(self.generate()) as body:
            try:
                first = await anext(body)
            except GatewayError as exc:
                await error_response(self.request, exc)(scope, receive, send)
                return
            await send({"type": "http.response.start", "status": 200, "headers": self.raw_headers})
            await send({"type": "http.response.body", "body": first, "more_body": True})
            async for block in body:
                await send({"type": "http.response.body", "body": block, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def generate(self):
        request, payload, settings = self.request, self.payload, self.settings
        audit = request.state.audit
        audit.update(streaming=True, cache_status="bypass", request_outcome="failed")
        provider, selected, _ = self.prepared
        limiter = request.app.state.inflight_limiter
        include_usage = payload.stream_options is not None and payload.stream_options.include_usage
        capture = settings.observability.traffic_log.capture_content
        # Keep a bounded raw prefix plus redaction lookahead. Redact before final truncation.
        secrets = request.app.state.recorder.secrets
        limit = settings.observability.traffic_log.max_content_chars
        prefix_limit = limit + max((len(secret) for secret in secrets), default=0) + 256
        text = ""
        truncated = False
        started = False
        completed = False
        identity = None
        finished = False
        finish_reason = None
        usage = None
        try:
            async with limiter.admit_wait(
                self.app_context.app_id,
                settings.limits.max_concurrent_requests,
                self.app_context.max_concurrent_requests,
                settings.limits.queue_max_depth,
                settings.limits.queue_max_depth_per_app,
                settings.limits.queue_wait_timeout_seconds,
                disconnected=request.state.is_disconnected,
                audit=audit,
            ):
                audit.update(provider_attempted=True, provider_attempts=1)
                async with aclosing(
                    provider.stream_chat_completions(payload, selected.split(":", 1)[1])
                ) as upstream:
                    async for value in upstream:
                        chunk = validate_chunk(value)
                        current = (chunk["id"], chunk["created"])
                        if identity is not None and current != (
                            identity["id"],
                            identity["created"],
                        ):
                            raise invalid_stream()
                        identity = {key: chunk[key] for key in ("id", "object", "created", "model")}
                        chunk["model"] = selected
                        if chunk["choices"]:
                            if finished:
                                raise invalid_stream()
                            choice = chunk["choices"][0]
                            finish_reason = choice.get("finish_reason")
                            finished = finish_reason is not None
                            content = (
                                choice["delta"].get("content")
                                or choice["delta"].get("refusal")
                                or ""
                            )
                            if capture:
                                remaining = prefix_limit - len(text)
                                text += content[:remaining]
                                truncated = truncated or len(content) > remaining
                            if chunk.get("usage") is not None:
                                usage = chunk["usage"]
                            chunk.pop("usage", None)
                            if include_usage:
                                chunk["usage"] = None
                            started = True
                            yield event(chunk)
                        else:
                            if not finished:
                                raise invalid_stream()
                            if chunk.get("usage") is not None:
                                usage = chunk["usage"]
                    if not finished or identity is None:
                        raise invalid_stream()
                    if usage is not None:
                        audit.update(usage)
                    if include_usage:
                        yield event({**identity, "model": selected, "choices": [], "usage": usage})
                    yield b"data: [DONE]\n\n"
                    completed = True
                    audit["request_outcome"] = "completed"
        except asyncio.CancelledError:
            audit.update(request_outcome="cancelled", error_type="client_disconnected")
            raise
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, GatewayError)
                else GatewayError(500, "internal_error", "Gateway could not complete the request")
            )
            audit.update(
                request_outcome="failed",
                error_type=error.code,
                outcome_status_code=error.status,
            )
            if not started:
                raise error from exc
            # The HTTP status is already committed. Terminate with a safe error event.
            yield b"event: error\n" + event(
                {
                    "error": {
                        "message": error.message,
                        "type": error.kind,
                        "code": error.code,
                    },
                    "request_id": audit["request_id"],
                }
            )
        finally:
            if usage is not None:
                audit.update(usage)
            if capture:
                request.state.response_content = [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": finish_reason if completed else None,
                    }
                ]
                audit["response_content_partial"] = not completed
                audit["response_content_truncated"] = truncated
