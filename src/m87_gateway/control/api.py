from __future__ import annotations

import json
import secrets
import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from m87_gateway.api.errors import GatewayError
from m87_gateway.config import validate_model
from m87_gateway.control.store import LocalControlStore

STATIC_DIR = Path(__file__).with_name("static")
router = APIRouter()


def _store(request: Request) -> LocalControlStore:
    store = getattr(request.app.state, "control_store", None)
    if store is None:
        raise GatewayError(404, "control_plane_disabled", "Control plane is disabled")
    return store


async def require_admin(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> LocalControlStore:
    scheme, _, token = (authorization or "").partition(" ")
    expected = getattr(request.app.state, "admin_api_key", "")
    if (
        scheme.lower() != "bearer"
        or not token
        or not expected
        or not secrets.compare_digest(token.encode(), expected.encode())
    ):
        raise GatewayError(
            401, "invalid_admin_key", "Missing or invalid admin key", "authentication_error"
        )
    return _store(request)


AdminStore = Annotated[LocalControlStore, Depends(require_admin)]


class AppKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    allowed_models: list[str] = Field(min_length=1)
    capture_content: bool = False
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100000)

    @field_validator("allowed_models")
    @classmethod
    def valid_models(cls, values: list[str]) -> list[str]:
        return [validate_model(value) for value in values]


class ProviderKeyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(pattern=r"^openai$")
    alias: str = Field(default="default", pattern=r"^[a-zA-Z0-9_.-]{1,64}$")
    key: str = Field(min_length=8, max_length=4096)

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("Provider keys cannot contain whitespace")
        return value


@router.get("/admin", include_in_schema=False)
async def dashboard(request: Request):
    _store(request)
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/admin/assets/{filename}", include_in_schema=False)
async def dashboard_asset(request: Request, filename: str):
    _store(request)
    if filename not in {"app.js", "styles.css"}:
        raise GatewayError(404, "not_found", "Requested operation is unavailable")
    return FileResponse(STATIC_DIR / filename, headers={"Cache-Control": "no-store"})


@router.get("/admin/api/overview")
async def overview(store: AdminStore, hours: int = Query(default=24, ge=1, le=2160)):
    return store.overview(hours)


@router.get("/admin/api/logs")
async def logs(
    store: AdminStore,
    limit: int = Query(default=100, ge=1, le=1000),
    app_id: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, pattern=r"^(success|error)$"),
):
    return {"items": store.list_events(limit=limit, app_id=app_id, status=status)}


@router.get("/admin/api/logs/export")
async def export_logs(store: AdminStore, limit: int = Query(default=1000, ge=1, le=10000)):
    body = json.dumps(store.export_events(limit=limit), indent=2)
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="gateway-events.json"'},
    )


@router.get("/admin/api/logs/{request_id}")
async def log_detail(request_id: str, store: AdminStore):
    if len(request_id) > 128:
        raise GatewayError(404, "not_found", "Log event was not found")
    event = store.get_event(request_id)
    if event is None:
        raise GatewayError(404, "not_found", "Log event was not found")
    return event


@router.get("/admin/api/apps")
async def apps(store: AdminStore):
    return {"items": store.list_apps()}


@router.post("/admin/api/apps", status_code=201)
async def create_app(payload: AppKeyCreate, store: AdminStore):
    try:
        app, raw_key = store.create_app_key(
            payload.app_id,
            payload.allowed_models,
            payload.capture_content,
            payload.rate_limit_per_minute,
        )
    except sqlite3.IntegrityError as exc:
        raise GatewayError(409, "app_exists", "Application identifier already exists") from exc
    return {**app, "api_key": raw_key}


@router.delete("/admin/api/apps/{app_id}", status_code=204)
async def delete_app(app_id: str, store: AdminStore):
    if not store.delete_app(app_id):
        raise GatewayError(404, "not_found", "Application was not found")
    return Response(status_code=204)


@router.get("/admin/api/provider-keys")
async def provider_keys(store: AdminStore):
    return {"items": store.list_provider_keys()}


@router.put("/admin/api/provider-keys", status_code=204)
async def put_provider_key(payload: ProviderKeyWrite, request: Request, store: AdminStore):
    store.put_provider_key(payload.provider, payload.key, payload.alias)
    request.app.state.recorder.add_secret(payload.key)
    return Response(status_code=204)


@router.delete("/admin/api/provider-keys/{provider}/{alias}", status_code=204)
async def delete_provider_key(provider: str, alias: str, store: AdminStore):
    if provider != "openai" or not store.delete_provider_key(provider, alias):
        raise GatewayError(404, "not_found", "Provider key was not found")
    return Response(status_code=204)


@router.get("/admin/api/destinations")
async def destinations(request: Request, store: AdminStore):
    settings = request.app.state.settings
    traffic = settings.observability.traffic_log
    return {
        "items": [
            {
                "name": "Local SQLite",
                "type": "events and encrypted keys",
                "enabled": True,
                "target": str(store.database_path),
            },
            {
                "name": "Structured stdout",
                "type": "sanitized metadata",
                "enabled": settings.observability.json_logs,
                "target": "stdout",
            },
            {
                "name": "Private JSONL",
                "type": "events and optional content",
                "enabled": bool(traffic.path),
                "target": traffic.path,
            },
            {
                "name": "Prometheus",
                "type": "metrics",
                "enabled": settings.observability.prometheus_metrics,
                "target": "/metrics",
            },
        ]
    }
