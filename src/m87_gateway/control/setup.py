"""Validated, persistent runtime settings for the included configuration UI."""

from m87_gateway.config import GatewaySettings
from m87_gateway.controls import ExactResponseCache


def apply_overrides(settings: GatewaySettings, saved: dict) -> GatewaySettings:
    data = settings.model_dump()
    for name, provider in saved.get("providers", {}).items():
        if name in {"openai", "ollama", "openai_compatible"}:
            data["providers"][name] = provider
        else:
            data["providers"]["custom"][name] = provider
    if "default_model" in saved:
        data["routing"]["default_model"] = saved["default_model"]
    if "capture_content" in saved:
        data["observability"]["traffic_log"]["capture_content"] = saved["capture_content"]
    controls = saved.get("controls", {})
    for section in ("cache", "retry", "limits", "guardrails"):
        if section in controls:
            data[section].update(controls[section])
    if "retention_days" in controls:
        data["control_plane"]["retention_days"] = controls["retention_days"]
    if "content_retention_days" in controls:
        data["control_plane"]["content_retention_days"] = controls["content_retention_days"]
    if "max_content_chars" in controls:
        data["observability"]["traffic_log"]["max_content_chars"] = controls["max_content_chars"]
    return GatewaySettings.model_validate(data)


def activate(request, settings):
    state = request.app.state
    state.model_catalog.clear()
    state.settings = settings
    state.recorder.settings = settings
    state.control_store.config = settings.control_plane
    # Cached completions from an old endpoint must never survive a connection change.
    state.response_cache = ExactResponseCache(
        settings.cache.enabled, settings.cache.ttl_seconds, settings.cache.max_entries
    )


def managed_snapshot(settings: GatewaySettings) -> dict:
    """Only console-managed fields; no application keys, paths or provider secrets."""
    from m87_gateway.adapters import adapters

    return {
        "providers": {
            name: settings.providers.for_adapter(name).model_dump() for name in adapters()
        },
        "default_model": settings.routing.default_model,
        "capture_content": settings.observability.traffic_log.capture_content,
        "controls": {
            "cache": settings.cache.model_dump(),
            "retry": settings.retry.model_dump(),
            "limits": settings.limits.model_dump(),
            "guardrails": {
                "max_request_bytes": settings.guardrails.max_request_bytes,
                "max_message_chars": settings.guardrails.max_message_chars,
            },
            "retention_days": settings.control_plane.retention_days,
            "content_retention_days": settings.control_plane.content_retention_days,
            "max_content_chars": settings.observability.traffic_log.max_content_chars,
        },
    }
