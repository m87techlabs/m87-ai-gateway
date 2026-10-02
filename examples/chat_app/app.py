"""Local chat application: browser -> application server -> gateway -> inference."""

import argparse
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import time
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
import uvicorn

STATIC = Path(__file__).with_name("static")
REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def managed_gateway_url(run_dir: Path) -> str | None:
    """Read only a private launcher record matching a live process; ignore stale PIDs."""
    state = run_dir / "process.state"
    try:
        if (
            not Path("/proc").is_dir()
            or not run_dir.is_dir()
            or not state.is_file()
            or run_dir.is_symlink()
            or state.is_symlink()
        ):
            return None
        if (
            run_dir.stat().st_uid != os.getuid()
            or run_dir.stat().st_mode & 0o777 != 0o700
            or state.stat().st_uid != os.getuid()
            or state.stat().st_mode & 0o777 != 0o600
        ):
            return None
        pid, ticks, digest, port = state.read_text().strip().split("\t")
        if (
            not pid.isdecimal()
            or int(pid) <= 1
            or not port.isdecimal()
            or not 1 <= int(port) <= 65535
        ):
            return None
        process = Path("/proc") / pid
        fields = (process / "stat").read_text().rsplit(") ", 1)[1].split()
        if fields[0] == "Z" or fields[19] != ticks:
            return None
        if hashlib.sha256((process / "cmdline").read_bytes()).hexdigest() != digest:
            return None
        return f"http://127.0.0.1:{int(port)}"
    except (OSError, ValueError, IndexError):
        return None


def default_gateway_url() -> str:
    run_dir = Path(os.getenv("GATEWAY_RUN_DIR", str(STATIC.parents[2] / "var/lib/gateway-runner")))
    return (
        os.getenv("SAMPLE_GATEWAY_URL") or managed_gateway_url(run_dir) or "http://127.0.0.1:8080"
    )


@dataclass(frozen=True)
class Settings:
    gateway_url: str = "http://127.0.0.1:8080"
    app_key: str = field(default="", repr=False)
    model: str = "auto"
    port: int = 8790

    def validate(self):
        url = urlsplit(self.gateway_url)
        _ = url.port
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("Gateway URL must be HTTP(S), without credentials, query, or fragment")
        if not self.app_key or any(char.isspace() for char in self.app_key):
            raise ValueError("SAMPLE_APP_KEY must contain a gateway application key")
        if not self.model or len(self.model) > 200 or any(char.isspace() for char in self.model):
            raise ValueError("Model must be auto or a gateway model identifier")
        if not 1 <= self.port <= 65535:
            raise ValueError("Sample port must be between 1 and 65535")


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8192)


class Chat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[Message] = Field(min_length=1, max_length=31)

    @model_validator(mode="after")
    def conversation(self):
        if sum(len(message.content) for message in self.messages) > 32768:
            raise ValueError("Conversation is too long")
        if self.messages[-1].role != "user":
            raise ValueError("Conversation must end with a user message")
        return self


def error(message, status, request_id=None):
    return JSONResponse(
        {"error": message, "request_id": request_id},
        status_code=status,
        headers={"X-Request-ID": request_id} if request_id else {},
    )


def create_app(settings: Settings, *, transport=None):
    settings.validate()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            timeout=70, transport=transport, trust_env=False, follow_redirects=False
        ) as client:
            app.state.gateway = client
            yield

    app = FastAPI(title="Gateway Chat Sample", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.mount("/assets", StaticFiles(directory=STATIC), name="assets")
    base = settings.gateway_url.rstrip("/")

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        # This app has no end-user login. Keep access on the local workstation.
        allowed_hosts = {"localhost", "127.0.0.1"}
        if request.url.hostname not in allowed_hosts:
            response = error("Unrecognized application host", 400)
        elif request.method == "POST" and (
            request.headers.get("sec-fetch-site") == "cross-site"
            or (
                request.headers.get("origin")
                and request.headers["origin"] != str(request.base_url).rstrip("/")
            )
        ):
            response = error("Use the application from its own browser page", 403)
        elif request.method == "POST" and len(await request.body()) > 128 * 1024:
            response = error("Conversation is too large", 413)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        return error("Use 1–31 messages ending with a question; keep the conversation short", 422)

    @app.get("/")
    async def page():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    async def status():
        try:
            response = await app.state.gateway.get(f"{base}/health", timeout=3)
            reachable = response.status_code == 200 and response.json().get("status") == "ok"
        except (httpx.HTTPError, ValueError, AttributeError):
            reachable = False
        return {
            "gateway_reachable": reachable,
            "gateway_url": settings.gateway_url,
            "model": settings.model,
        }

    @app.post("/api/chat")
    async def chat(body: Chat):
        started = time.perf_counter()
        try:
            response = await app.state.gateway.post(
                f"{base}/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.app_key}"},
                json={
                    "model": settings.model,
                    "messages": [message.model_dump() for message in body.messages],
                    "max_tokens": 512,
                    "stream": False,
                },
            )
        except httpx.TimeoutException:
            return error("Gateway timed out. Check its logs before retrying", 504)
        except httpx.HTTPError:
            return error("Gateway is unreachable. Start it and check the configured URL", 502)
        candidate = response.headers.get("x-request-id", "")
        request_id = candidate if REQUEST_ID.fullmatch(candidate) else None
        if response.status_code != 200:
            provider_messages = {
                "provider_disabled": "Selected provider is disabled. Enable it in the gateway Setup page",
                "provider_timeout": "Model provider timed out. Check its readiness and gateway timeout setting",
                "provider_rejected": "Model provider rejected the request. Check the installed model and provider credentials",
                "provider_rate_limited": "Model provider rate limit reached. Wait before retrying",
            }
            try:
                code = response.json().get("error", {}).get("code")
            except (ValueError, AttributeError):
                code = None
            messages = {
                400: "Gateway rejected the request. Check its policies and selected model",
                401: "Application key rejected. Check the gateway URL and use a key from its Applications page",
                403: "Application is not allowed to use this model",
                429: "Application rate limit reached. Wait before retrying",
            }
            return error(
                provider_messages.get(
                    code,
                    messages.get(response.status_code, "Gateway could not complete the request"),
                )
                if isinstance(code, str)
                else messages.get(response.status_code, "Gateway could not complete the request"),
                response.status_code if 400 <= response.status_code < 600 else 502,
                request_id,
            )
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Expected text")
            usage = payload.get("usage") or {}
            counts = {
                name: value if type(value) is int and value >= 0 else None
                for name in ("prompt_tokens", "completion_tokens", "total_tokens")
                for value in (usage.get(name),)
            }
            model = payload.get("model")
            if not isinstance(model, str):
                model = settings.model
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            return error("Gateway returned an unexpected chat response", 502, request_id)
        return JSONResponse(
            {
                "content": content,
                "model": model,
                "usage": counts,
                "request_id": request_id,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            },
            headers={"X-Request-ID": request_id} if request_id else {},
        )

    return app


def main():
    parser = argparse.ArgumentParser(description="Chat with an already-running AI gateway")
    parser.add_argument("--gateway-url", default=default_gateway_url())
    parser.add_argument("--model", default=os.getenv("SAMPLE_MODEL", "auto"))
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    try:
        settings = Settings(
            args.gateway_url, os.getenv("SAMPLE_APP_KEY", ""), args.model, args.port
        )
        application = create_app(settings)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Chat sample: http://localhost:{settings.port} (Ctrl+C to stop)", flush=True)
    print(f"Gateway: {settings.gateway_url}", flush=True)
    uvicorn.run(application, host="127.0.0.1", port=settings.port)
