"""Operator-managed metadata export, encrypted credentials and safe draft probes."""

import asyncio
import os
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from m87_gateway.api.errors import GatewayError
from m87_gateway.config.settings import LogExportConfig
from m87_gateway.logging.exporters import ExportService, activate_export, exporter_adapters
from m87_gateway.logging.outbox import DeliveryOutbox, destination_binding
from .api import AdminStore
from .configuration_service import parse_revision, persist_configuration, revision_etag
from .setup import apply_overrides

router = APIRouter()


class ExportWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    config: LogExportConfig
    key: SecretStr | None = None
    clear_key: bool = Field(default=False, strict=True)

    @field_validator("key")
    @classmethod
    def valid_key(cls, value):
        if value is not None:
            raw = value.get_secret_value()
            if not 1 <= len(raw) <= 4096 or any(not 33 <= ord(c) <= 126 for c in raw):
                raise ValueError(
                    "Use a non-empty export token without whitespace or control characters"
                )
        return value


def require_management(store):
    if not isinstance(getattr(store, "export_outbox", None), DeliveryOutbox) or not all(
        callable(getattr(store.secrets, name, None))
        for name in ("get_export_key", "export_key_binding")
    ):
        raise GatewayError(
            409,
            "export_management_unsupported",
            "Backend does not support console export management",
        )


def credential_binding(config):
    return (config.adapter, config.endpoint, config.api_key_env, config.use_stored_key)


def prepare_export(request, store, payload, *, probe=False):
    require_management(store)
    current = request.app.state.settings.observability.log_export
    config = payload.config
    if config.adapter not in exporter_adapters():
        raise GatewayError(422, "unsupported_exporter", "Log exporter adapter is not registered")
    key = payload.key.get_secret_value() if payload.key is not None else None
    if key is not None and not config.use_stored_key:
        raise GatewayError(
            422, "invalid_export_credential", "Select stored credential before entering a token"
        )
    try:
        has_key = bool(store.secrets.export_key_binding()) or bool(
            current.api_key_env and os.getenv(current.api_key_env)
        )
    except Exception as exc:
        raise GatewayError(
            503,
            "export_storage_unavailable",
            "Cannot read export credentials; check Storage health",
        ) from exc
    if (
        credential_binding(current) != credential_binding(config)
        and has_key
        and key is None
        and not payload.clear_key
    ):
        raise GatewayError(
            409,
            "credential_confirmation_required",
            "Destination or credential binding changed. Supply a new token or confirm removal of the saved credential.",
        )
    if probe:
        try:
            config = LogExportConfig.model_validate({**config.model_dump(), "enabled": True})
        except ValueError as exc:
            raise GatewayError(
                422, "missing_export_endpoint", "Enter a valid export endpoint before testing"
            ) from exc
    try:
        service = ExportService(
            config,
            store,
            request.app.state.recorder,
            token_override=key if key is not None else "" if payload.clear_key else None,
            configure_outbox=False,
        )
    except ValueError as exc:
        raise GatewayError(
            422,
            "export_configuration_invalid",
            "Check export endpoint, credential selection and token availability",
        ) from exc
    except Exception as exc:
        raise GatewayError(
            503, "export_storage_unavailable", "Cannot prepare export; check Storage health"
        ) from exc
    return config, key, service


@router.get("/admin/api/log-export")
async def export_settings(request: Request, store: AdminStore, response: Response):
    require_management(store)
    response.headers["ETag"] = revision_etag(store)
    config = request.app.state.settings.observability.log_export
    try:
        binding = store.secrets.export_key_binding()
    except Exception as exc:
        raise GatewayError(
            503, "export_storage_unavailable", "Cannot read export settings; check Storage health"
        ) from exc
    return {
        "config": config.model_dump(),
        "adapters": exporter_adapters(),
        "has_stored_key": binding == destination_binding(config),
        "has_any_stored_key": binding is not None,
        "health": request.app.state.log_export.health(),
        "scope": "Gateway-wide metadata export. Saved credentials are never returned. Test sends one synthetic event without saving.",
    }


@router.put("/admin/api/log-export", status_code=204)
async def save_export(
    payload: ExportWrite,
    request: Request,
    store: AdminStore,
    if_match: Annotated[str | None, Header()] = None,
):
    revision = parse_revision(if_match)
    config, key, service = prepare_export(request, store, payload)
    saved = store.runtime_config()
    saved["log_export"] = config.model_dump()
    settings = apply_overrides(request.app.state.settings, saved)
    try:
        persist_configuration(
            store,
            saved,
            settings,
            action="log_export.updated",
            expected_revision=revision,
            export_key=key,
            export_binding=destination_binding(config),
            clear_export_key=payload.clear_key or key is not None,
        )
    except Exception:
        await service.close()
        raise
    if key is not None:
        request.app.state.recorder.add_secret(key)
    await activate_export(request, settings, service)
    return Response(status_code=204)


@router.post("/admin/api/log-export/test")
async def test_export(payload: ExportWrite, request: Request, store: AdminStore):
    config, _, service = prepare_export(request, store, payload, probe=True)
    delivery_id = uuid4().hex
    try:
        async with asyncio.timeout(config.timeout_seconds):
            ok = await service.exporter.send(
                delivery_id,
                {
                    "event": "connection_test",
                    "request_id": delivery_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "project_id": None,
                    "app_id": None,
                    "total_tokens": None,
                },
            )
        return {
            "ok": bool(ok),
            "message": "Receiver accepted the synthetic test event."
            if ok
            else "Receiver rejected the test. Check authentication and endpoint.",
        }
    except Exception:
        return {
            "ok": False,
            "message": "Could not reach the receiver within the configured timeout.",
        }
    finally:
        await service.close()
