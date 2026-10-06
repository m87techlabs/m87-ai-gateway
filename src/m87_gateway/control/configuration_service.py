"""Configuration transaction errors and revision preconditions shared by operator APIs."""

import sqlite3

from m87_gateway.api.errors import GatewayError
from .repositories.configuration import RevisionConflict
from .setup import managed_snapshot


def persist_configuration(store, saved, settings, **options):
    try:
        return store.save_runtime_config(saved, snapshot=managed_snapshot(settings), **options)
    except RevisionConflict as exc:
        raise GatewayError(
            409, "revision_conflict", "Configuration changed; refresh history"
        ) from exc
    except (sqlite3.Error, OSError) as exc:
        raise GatewayError(
            503,
            "configuration_storage_unavailable",
            "Settings were not activated. Check Storage health and retry.",
        ) from exc


def changed_credentials(current, target, snapshot):
    return [
        name
        for name in snapshot.get("providers", {})
        if (
            current.providers.for_adapter(name).base_url,
            current.providers.for_adapter(name).api_key_env,
        )
        != (
            target.providers.for_adapter(name).base_url,
            target.providers.for_adapter(name).api_key_env,
        )
    ]


def revision_etag(store):
    items = store.list_config_revisions(1)
    return f'"{items[0]["revision_id"]}"' if items else '"0"'


def parse_revision(value):
    if value is None:
        return None
    raw = value.removeprefix('"').removesuffix('"')
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 18 or int(raw) < 1:
        raise GatewayError(
            422, "invalid_revision", "If-Match must contain a positive configuration revision"
        )
    return int(raw)
