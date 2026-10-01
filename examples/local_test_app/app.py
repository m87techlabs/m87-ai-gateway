"""Local browser relay for exercising the gateway without Docker."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

STATIC_DIR = Path(__file__).with_name("static")
MAX_REQUEST_BYTES = 128 * 1024
REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


@dataclass(frozen=True)
class LocalTestSettings:
    """Configuration kept in the WSL relay process, never in browser code."""

    gateway_url: str = "http://127.0.0.1:8080"
    gateway_api_key: str = field(default="", repr=False)
    default_model: str = "auto"
    timeout_seconds: float = 70.0
    host: str = "127.0.0.1"
    port: int = 8787

    @classmethod
    def from_environment(cls) -> LocalTestSettings:
        settings = cls(
            gateway_url=os.getenv("LOCAL_TEST_GATEWAY_URL", "http://127.0.0.1:8080"),
            gateway_api_key=os.getenv("LOCAL_TEST_GATEWAY_API_KEY", ""),
            default_model=os.getenv("LOCAL_TEST_MODEL", "auto"),
            timeout_seconds=_float_environment("LOCAL_TEST_TIMEOUT_SECONDS", 70.0),
            host=os.getenv("LOCAL_TEST_HOST", "127.0.0.1"),
            port=_int_environment("LOCAL_TEST_PORT", 8787),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        parsed = urlsplit(self.gateway_url)
        _ = parsed.port
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("LOCAL_TEST_GATEWAY_URL must be an HTTP(S) URL without credentials")
        if not self.gateway_api_key or any(char.isspace() for char in self.gateway_api_key):
            raise ValueError("LOCAL_TEST_GATEWAY_API_KEY must be set without whitespace")
        if self.host not in {"127.0.0.1", "0.0.0.0"}:
            raise ValueError("LOCAL_TEST_HOST must be 127.0.0.1 or 0.0.0.0")
        if not 1 <= self.port <= 65535:
            raise ValueError("LOCAL_TEST_PORT must be a valid port")
        if not 1 <= self.timeout_seconds <= 600:
            raise ValueError("LOCAL_TEST_TIMEOUT_SECONDS must be between 1 and 600")
        _validate_model(self.default_model)


class LocalChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=65536)
    system_prompt: str | None = Field(default=None, max_length=4096)
    model: str = "auto"
    temperature: float | None = Field(default=0.2, ge=0, le=2)
    max_tokens: int | None = Field(default=256, ge=1, le=32768)

    @field_validator("model")
    @classmethod
    def valid_model(cls, value: str) -> str:
        _validate_model(value)
        return value


def _validate_model(value: str) -> None:
    if value == "auto":
        return
    provider, separator, model = value.partition(":")
    if (
        not separator
        or provider not in {"ollama", "openai"}
        or not model
        or len(value) > 200
        or any(char.isspace() for char in value)
    ):
        raise ValueError("Use auto or a supported provider:model identifier")


def _float_environment(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _int_environment(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _safe_request_id(response: httpx.Response) -> str | None:
    candidate = response.headers.get("x-request-id")
    return candidate if candidate and REQUEST_ID.fullmatch(candidate) else None


def _relay_headers(request_id: str | None = None) -> dict[str, str]:
    headers = {"Cache-Control": "no-store"}
    if request_id:
        headers["X-Request-ID"] = request_id
    return headers


def _safe_gateway_error(payload: Any) -> dict[str, str]:
    fallback = {
        "message": "Gateway could not complete the request",
        "type": "gateway_error",
        "code": "gateway_error",
    }
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return fallback
    error = payload["error"]
    safe = {}
    for name in ("message", "type", "code"):
        value = error.get(name)
        if not isinstance(value, str) or not 1 <= len(value) <= 200:
            return fallback
        safe[name] = value
    return safe


def create_app(
    settings: LocalTestSettings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Create the same-origin UI and server-side gateway relay."""

    settings.validate()
    application = FastAPI(
        title="Gateway Flow Lab",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "error": {
                    "message": "Request does not match the local chat form",
                    "type": "validation_error",
                    "code": "invalid_request",
                },
                "request_id": None,
            },
            headers=_relay_headers(),
        )

    @application.middleware("http")
    async def local_security(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                too_large = int(content_length) > MAX_REQUEST_BYTES
            except ValueError:
                too_large = True
            if too_large:
                return JSONResponse(
                    status_code=413,
                    content={"error": {"message": "Request is too large", "code": "too_large"}},
                    headers=_relay_headers(),
                )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; img-src 'self' data:"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @application.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/api/status", include_in_schema=False)
    async def status() -> JSONResponse:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                base_url=settings.gateway_url,
                timeout=min(settings.timeout_seconds, 5.0),
                transport=transport,
            ) as client:
                response = await client.get("/health")
            reachable = response.status_code == 200
            status_code = response.status_code
        except (httpx.TimeoutException, httpx.NetworkError):
            reachable = False
            status_code = None
        return JSONResponse(
            content={
                "gateway": "reachable" if reachable else "unreachable",
                "gateway_status": status_code,
                "model": settings.default_model,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            },
            headers=_relay_headers(),
        )

    @application.post("/api/chat", include_in_schema=False)
    async def chat(payload: LocalChatRequest) -> JSONResponse:
        messages = []
        if payload.system_prompt:
            messages.append({"role": "system", "content": payload.system_prompt})
        messages.append({"role": "user", "content": payload.prompt})
        gateway_payload = {
            "model": payload.model,
            "messages": messages,
            "temperature": payload.temperature,
            "max_tokens": payload.max_tokens,
            "stream": False,
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                base_url=settings.gateway_url,
                timeout=settings.timeout_seconds,
                transport=transport,
            ) as client:
                response = await client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.gateway_api_key}"},
                    json=gateway_payload,
                )
        except httpx.TimeoutException:
            return _relay_failure(504, "Gateway timed out", "gateway_timeout", started)
        except httpx.NetworkError:
            return _relay_failure(502, "Gateway is unavailable", "gateway_unavailable", started)

        request_id = _safe_request_id(response)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.is_error:
            status_code = response.status_code if 400 <= response.status_code <= 599 else 502
            return JSONResponse(
                status_code=status_code,
                content={
                    "ok": False,
                    "error": _safe_gateway_error(body),
                    "request_id": request_id,
                    "latency_ms": latency_ms,
                },
                headers=_relay_headers(request_id),
            )

        completion = _completion_fields(body)
        if completion is None:
            return _relay_failure(
                502,
                "Gateway returned an invalid response",
                "invalid_gateway_response",
                started,
                request_id,
            )
        return JSONResponse(
            content={
                "ok": True,
                **completion,
                "request_id": request_id,
                "latency_ms": latency_ms,
            },
            headers=_relay_headers(request_id),
        )

    return application


def _completion_fields(body: Any) -> dict[str, Any] | None:
    if not isinstance(body, dict) or not isinstance(body.get("choices"), list):
        return None
    if not body["choices"] or not isinstance(body["choices"][0], dict):
        return None
    message = body["choices"][0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        return None
    model = body.get("model")
    usage = body.get("usage")
    return {
        "content": message["content"],
        "model": model if isinstance(model, str) else None,
        "usage": usage if isinstance(usage, dict) else None,
    }


def _relay_failure(
    status_code: int,
    message: str,
    code: str,
    started: float,
    request_id: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "error": {"message": message, "type": "relay_error", "code": code},
            "request_id": request_id,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        },
        headers=_relay_headers(request_id),
    )


def main() -> None:
    settings = LocalTestSettings.from_environment()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        access_log=True,
    )


if __name__ == "__main__":
    main()
