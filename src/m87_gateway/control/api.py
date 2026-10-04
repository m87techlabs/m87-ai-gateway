from __future__ import annotations

import json
import os
import secrets
import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from m87_gateway.api.errors import GatewayError
from m87_gateway.config import validate_model
from m87_gateway.config.settings import CacheConfig, LimitsConfig, ProviderConfig, RetryConfig
from m87_gateway.adapters import adapters
from m87_gateway.providers.factory import get_provider
from m87_gateway.control.setup import activate, apply_overrides
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
ProjectIdentifier = Annotated[
    str, Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
]
ProjectFilter = Annotated[
    str | None, Query(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    project_id: ProjectIdentifier
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("Enter a project name without control characters")
        return value


class ProjectAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: ProjectIdentifier


class AppModelAccess(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_models: list[str] = Field(min_length=1)

    @field_validator("allowed_models")
    @classmethod
    def valid_models(cls, values: list[str]) -> list[str]:
        return [validate_model(value) for value in values]


class AppKeyCreate(AppModelAccess):
    app_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    project_id: ProjectIdentifier = "default"
    capture_content: bool = Field(
        default=False,
        description="Legacy compatibility field; gateway settings control content capture",
    )
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100000)
    max_concurrent_requests: int | None = Field(default=None, ge=1, le=10000)


class AppLimitsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate_limit_per_minute: int | None = Field(ge=1, le=100000)
    max_concurrent_requests: int | None = Field(ge=1, le=10000)


class ControlsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    cache: CacheConfig
    retry: RetryConfig
    limits: LimitsConfig
    max_message_chars: int = Field(ge=1, le=1048576)
    max_request_bytes: int = Field(ge=1, le=10485760)
    retention_days: int = Field(ge=1, le=3650)
    max_content_chars: int = Field(ge=1, le=65536)

    def overrides(self):
        values = self.model_dump()
        values["guardrails"] = {
            "max_message_chars": values.pop("max_message_chars"),
            "max_request_bytes": values.pop("max_request_bytes"),
        }
        return values


class LogDeletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str = Field(pattern=r"^DELETE$")
    project_id: ProjectIdentifier | None = None


@router.get("/admin/api/controls")
async def controls(request: Request, store: AdminStore):
    settings = request.app.state.settings
    return ControlsWrite(
        cache=settings.cache,
        retry=settings.retry,
        limits=settings.limits,
        max_message_chars=settings.guardrails.max_message_chars,
        max_request_bytes=settings.guardrails.max_request_bytes,
        retention_days=settings.control_plane.retention_days,
        max_content_chars=settings.observability.traffic_log.max_content_chars,
    )


@router.put("/admin/api/controls", status_code=204)
async def save_controls(payload: ControlsWrite, request: Request, store: AdminStore):
    saved = store.runtime_config()
    saved["controls"] = payload.overrides()
    settings = apply_overrides(request.app.state.settings, saved)
    store.save_runtime_config(saved)
    activate(request, settings)
    store.prune_events()
    return Response(status_code=204)


@router.post("/admin/api/cache/clear", status_code=204)
async def clear_cache(request: Request, store: AdminStore):
    request.app.state.response_cache.clear()
    return Response(status_code=204)


@router.get("/admin/api/diagnostics")
async def gateway_diagnostics(request: Request, store: AdminStore):
    from m87_gateway.control.diagnostics import diagnostics

    return diagnostics(request.app.state)


@router.delete("/admin/api/logs")
async def remove_logs(payload: LogDeletion, store: AdminStore):
    return {"deleted": store.delete_events(payload.project_id)}


class ProviderKeyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    alias: str = Field(default="default", pattern=r"^[a-zA-Z0-9_.-]{1,64}$")
    key: str = Field(min_length=8, max_length=4096)

    @field_validator("provider")
    @classmethod
    def valid_provider(cls, value):
        if value not in adapters():
            raise ValueError("Unsupported provider")
        return value

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("Provider keys cannot contain whitespace")
        return value


@router.get("/", include_in_schema=False)
async def console_home(request: Request):
    _store(request)
    return RedirectResponse("/admin", status_code=302)


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
async def overview(
    store: AdminStore,
    hours: int = Query(default=24, ge=1, le=2160),
    project_id: ProjectFilter = None,
):
    return store.overview(hours, project_id)


@router.get("/admin/api/usage")
async def usage(
    store: AdminStore,
    hours: int = Query(default=24, ge=1, le=2160),
    project_id: ProjectFilter = None,
):
    return store.usage(hours, project_id)


@router.get("/admin/api/projects")
async def projects(store: AdminStore):
    return {"items": store.list_projects()}


@router.post("/admin/api/projects", status_code=201)
async def create_project(payload: ProjectCreate, store: AdminStore):
    try:
        return store.create_project(payload.project_id, payload.name)
    except sqlite3.IntegrityError as exc:
        raise GatewayError(409, "project_exists", "Project identifier already exists") from exc


@router.get("/admin/api/logs")
async def logs(
    store: AdminStore,
    limit: int = Query(default=100, ge=1, le=1000),
    app_id: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, pattern=r"^(success|error)$"),
    project_id: ProjectFilter = None,
):
    return {
        "items": store.list_events(limit=limit, app_id=app_id, status=status, project_id=project_id)
    }


@router.get("/admin/api/logs/export")
async def export_logs(
    store: AdminStore,
    limit: int = Query(default=1000, ge=1, le=10000),
    project_id: ProjectFilter = None,
):
    body = json.dumps(store.export_events(limit=limit, project_id=project_id), indent=2)
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
            payload.project_id,
            payload.max_concurrent_requests,
        )
    except sqlite3.IntegrityError as exc:
        raise GatewayError(409, "app_exists", "Application identifier already exists") from exc
    except ValueError as exc:
        raise GatewayError(422, "unknown_project", "Create the selected project first") from exc
    return {**app, "api_key": raw_key}


@router.patch("/admin/api/apps/{app_id}/project", status_code=204)
async def assign_project(app_id: str, payload: ProjectAssignment, store: AdminStore):
    try:
        found = store.assign_app_project(app_id, payload.project_id)
    except ValueError as exc:
        raise GatewayError(422, "unknown_project", "Create the selected project first") from exc
    if not found:
        raise GatewayError(404, "not_found", "Application was not found")
    return Response(status_code=204)


@router.patch("/admin/api/apps/{app_id}/models", status_code=204)
async def update_app_models(app_id: str, payload: AppModelAccess, store: AdminStore):
    if not store.update_app_models(app_id, payload.allowed_models):
        raise GatewayError(404, "not_found", "Application was not found")
    return Response(status_code=204)


@router.patch("/admin/api/apps/{app_id}/limits", status_code=204)
async def update_app_limits(app_id: str, payload: AppLimitsWrite, store: AdminStore):
    if not store.update_app_limits(
        app_id, payload.rate_limit_per_minute, payload.max_concurrent_requests
    ):
        raise GatewayError(404, "not_found", "Application was not found")
    return Response(status_code=204)


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
    if provider not in adapters() or not store.delete_provider_key(provider, alias):
        raise GatewayError(404, "not_found", "Provider key was not found")
    return Response(status_code=204)


class ConnectionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    config: ProviderConfig
    key: SecretStr | None = Field(default=None)
    clear_key: bool = False

    @field_validator("key")
    @classmethod
    def valid_key(cls, value):
        raw = value.get_secret_value() if value else ""
        if value and (not 8 <= len(raw) <= 4096 or any(character.isspace() for character in raw)):
            raise ValueError("Provider keys cannot contain whitespace")
        return value


class SetupWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    default_model: str
    capture_content: bool = False

    @field_validator("default_model")
    @classmethod
    def valid_model(cls, value):
        return validate_model(value, allow_auto=False)


@router.get("/admin/api/setup")
async def setup(request: Request, store: AdminStore):
    settings = request.app.state.settings
    keys = {item["provider"] for item in store.list_provider_keys() if item["alias"] == "default"}
    saved = store.runtime_config()
    return {
        "default_model": settings.routing.default_model,
        "capture_content": settings.observability.traffic_log.capture_content,
        "connections": [
            {
                "provider": name,
                "label": adapter.label,
                "requires_key": adapter.requires_key,
                "capabilities": ["text_chat", "non_streaming"],
                "model_discovery": adapter.model_discovery,
                "configured": name in saved.get("providers", {}),
                "has_stored_key": name in keys,
                "config": settings.providers.for_adapter(name).model_dump(),
            }
            for name, adapter in adapters().items()
        ],
    }


@router.put("/admin/api/connections/{provider}", status_code=204)
async def save_connection(
    provider: str, payload: ConnectionWrite, request: Request, store: AdminStore
):
    if provider not in adapters():
        raise GatewayError(400, "unsupported_provider", "Unsupported model provider")
    current = request.app.state.settings.providers.for_adapter(provider)
    config = payload.config.model_copy(update={"api_key_env": None, "base_url_env": None})
    if not config.base_url:
        raise GatewayError(422, "missing_endpoint", "Enter the provider endpoint URL")
    endpoint_changed = current.base_url != config.base_url
    has_key = bool(store.get_provider_key(provider)) or bool(
        current.api_key_env and os.getenv(current.api_key_env)
    )
    if endpoint_changed and has_key and not (payload.key or payload.clear_key):
        raise GatewayError(
            409,
            "credential_confirmation_required",
            "Changing the endpoint requires a new key or explicit key removal",
        )
    if not endpoint_changed and not (payload.key or payload.clear_key):
        config = config.model_copy(update={"api_key_env": current.api_key_env})
    saved = store.runtime_config()
    saved.setdefault("providers", {})[provider] = config.model_dump()
    settings = apply_overrides(request.app.state.settings, saved)
    key = payload.key.get_secret_value() if payload.key else None
    store.save_runtime_config(saved, provider, key, payload.clear_key or endpoint_changed)
    if key:
        request.app.state.recorder.add_secret(key)
    activate(request, settings)
    return Response(status_code=204)


@router.get("/admin/api/connections/{provider}/models")
async def connection_models(provider: str, request: Request, store: AdminStore):
    adapter = get_provider(provider, request.app.state.settings, store)
    names = await adapter.list_models()
    # Validate discovered names before offering them as routes or app allowlists.
    items = []
    for name in names:
        try:
            items.append(validate_model(f"{provider}:{name}", allow_auto=False))
        except ValueError:
            continue
    return {"items": items}


@router.put("/admin/api/setup", status_code=204)
async def save_setup(payload: SetupWrite, request: Request, store: AdminStore):
    saved = store.runtime_config()
    saved.update(payload.model_dump())
    settings = apply_overrides(request.app.state.settings, saved)
    provider = payload.default_model.split(":", 1)[0]
    config = settings.providers.for_adapter(provider)
    if not config.enabled or not (config.base_url or adapters()[provider].default_url):
        raise GatewayError(422, "provider_not_configured", "Connect the selected provider first")
    store.save_runtime_config(saved)
    activate(request, settings)
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


class ShutdownWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: str = Field(pattern=r"^[a-f0-9]{32}$")


@router.post("/admin/api/shutdown", status_code=204)
async def shutdown(payload: ShutdownWrite, request: Request, store: AdminStore):
    callback = getattr(request.app.state, "shutdown", None)
    if not callback or payload.instance_id != getattr(request.app.state, "instance_id", None):
        raise GatewayError(409, "not_managed", "Managed instance did not match")
    callback()
    return Response(status_code=204)
