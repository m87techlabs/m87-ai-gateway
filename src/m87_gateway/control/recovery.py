"""Operator configuration review/restore and explicit storage diagnostics."""

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from m87_gateway.api.errors import GatewayError
from .api import AdminStore
from .configuration_service import changed_credentials, persist_configuration
from .setup import activate, apply_overrides

router = APIRouter()


class RevisionRestore(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    expected_revision: int = Field(ge=1, strict=True)
    confirmation: str = Field(pattern=r"^RESTORE$")
    clear_changed_credentials: bool = Field(default=False, strict=True)


@router.get("/admin/api/configuration/revisions")
async def config_revisions(store: AdminStore, limit: int = Query(default=100, ge=1, le=100)):
    items = store.list_config_revisions(limit)
    return {
        "items": items,
        "current_revision": items[0]["revision_id"] if items else None,
        "scope": "Console-managed settings only; credentials and application keys are excluded.",
    }


@router.post("/admin/api/configuration/revisions/{revision_id}/restore")
async def restore_revision(
    revision_id: int, payload: RevisionRestore, request: Request, store: AdminStore
):
    try:
        saved = store.config_revision(revision_id)
    except Exception as exc:
        raise GatewayError(
            503, "revision_unavailable", "Cannot read this revision; check Storage health"
        ) from exc
    if saved is None:
        raise GatewayError(404, "not_found", "Configuration revision was not found")
    try:
        settings = apply_overrides(request.app.state.settings, saved)
    except ValueError as exc:
        raise GatewayError(
            409,
            "revision_incompatible",
            "Revision is incompatible with the current adapters or settings",
        ) from exc
    current = request.app.state.settings
    changed = changed_credentials(current, settings, saved)
    # Do not revive a historical environment binding or reuse a stored credential
    # across endpoints. Explicit confirmation removes every alias for affected providers.
    if changed and not payload.clear_changed_credentials:
        raise GatewayError(
            409,
            "credential_confirmation_required",
            "Provider endpoint or credential binding changes. Confirm removal of credentials for affected providers.",
        )
    for name in changed:
        saved["providers"][name]["api_key_env"] = None
        saved["providers"][name]["base_url_env"] = None
    settings = apply_overrides(current, saved)
    revision = persist_configuration(
        store,
        saved,
        settings,
        action="configuration.restored",
        restored_from=revision_id,
        expected_revision=payload.expected_revision,
        clear_providers=changed,
    )
    activate(request, settings)
    return {
        "revision_id": revision,
        "restored_from": revision_id,
        "cleared_provider_credentials": changed,
    }


@router.get("/admin/api/storage")
async def storage_health(store: AdminStore):
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(store.storage_health)


@router.post("/admin/api/storage/check")
async def verify_storage(store: AdminStore):
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(store.storage_health, verify=True)


@router.get("/admin/api/configuration/revisions/{revision_id}")
async def revision_detail(revision_id: int, request: Request, store: AdminStore):
    try:
        snapshot = store.config_revision(revision_id)
    except Exception as exc:
        raise GatewayError(
            503, "revision_unavailable", "Cannot read this revision; check Storage health"
        ) from exc
    if snapshot is None:
        raise GatewayError(404, "not_found", "Configuration revision was not found")
    try:
        settings = apply_overrides(request.app.state.settings, snapshot)
    except ValueError as exc:
        raise GatewayError(
            409,
            "revision_incompatible",
            "Revision is incompatible with the current adapters or settings",
        ) from exc
    changed = changed_credentials(request.app.state.settings, settings, snapshot)
    return {
        "revision_id": revision_id,
        "settings": snapshot,
        "changed_provider_bindings": changed,
        "scope": "Console-managed settings only. Current credentials are preserved for unchanged bindings. Changed bindings require credential removal.",
    }
