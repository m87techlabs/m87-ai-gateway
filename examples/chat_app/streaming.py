"""Local sample HTTP boundary and transparent SSE forwarding; no provider keys."""

import asyncio
import json

import httpx
from starlette.requests import Request
from starlette.responses import Response

from m87_gateway.cancellation import monitor_disconnect


class LocalBoundary:
    def __init__(self, app, error_factory):
        self.app = app
        self.error = error_factory

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        headers = {
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                added = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
                message["headers"] = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in {name for name, _ in added}
                ] + added
            await send(message)

        rejected = None
        if request.url.hostname not in {"localhost", "127.0.0.1"}:
            rejected = self.error("Unrecognized application host", 400)
        elif request.method == "POST" and (
            request.headers.get("sec-fetch-site") == "cross-site"
            or (
                request.headers.get("origin")
                and request.headers["origin"] != str(request.base_url).rstrip("/")
            )
        ):
            rejected = self.error("Use the application from its own browser page", 403)
        if rejected is not None:
            return await rejected(scope, receive, secure_send)
        if request.method != "POST":
            return await self.app(scope, receive, secure_send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 128 * 1024:
                return await self.error("Conversation is too large", 413)(
                    scope, receive, secure_send
                )
            if not message.get("more_body", False):
                break
        delivered = False
        disconnected = asyncio.Event()

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        await monitor_disconnect(self.app(scope, replay, secure_send), receive, disconnected)


class GatewayStream(Response):
    def __init__(self, client, url, key, payload, error_factory, request_id_pattern):
        super().__init__()
        self.client, self.url, self.key = client, url, key
        self.payload, self.error, self.pattern = payload, error_factory, request_id_pattern

    async def __call__(self, scope, receive, send):
        started = False
        request_id = None
        try:
            async with self.client.stream(
                "POST", self.url, headers={"Authorization": f"Bearer {self.key}"}, json=self.payload
            ) as upstream:
                candidate = upstream.headers.get("x-request-id", "")
                request_id = candidate if self.pattern.fullmatch(candidate) else None
                if upstream.status_code != 200:
                    return await self.error(
                        "Gateway could not start the stream. Check its logs",
                        upstream.status_code,
                        request_id=request_id,
                    )(scope, receive, send)
                if not upstream.headers.get("content-type", "").startswith("text/event-stream"):
                    return await self.error(
                        "Gateway returned an invalid stream", 502, request_id=request_id
                    )(scope, receive, send)
                headers = [
                    (b"content-type", b"text/event-stream; charset=utf-8"),
                    (b"x-gateway-cache", b"BYPASS"),
                    (b"x-accel-buffering", b"no"),
                ]
                if request_id:
                    headers.append((b"x-request-id", request_id.encode()))
                await send({"type": "http.response.start", "status": 200, "headers": headers})
                started = True
                async for block in upstream.aiter_bytes():
                    await send({"type": "http.response.body", "body": block, "more_body": True})
                await send({"type": "http.response.body", "body": b"", "more_body": False})
        except httpx.HTTPError:
            if not started:
                return await self.error("Gateway is unavailable or timed out", 502)(
                    scope, receive, send
                )
            value = {
                "error": {"message": "Gateway stream interrupted", "code": "gateway_unreachable"},
                "request_id": request_id,
            }
            block = f"event: error\ndata: {json.dumps(value)}\n\n".encode()
            await send({"type": "http.response.body", "body": block, "more_body": False})
