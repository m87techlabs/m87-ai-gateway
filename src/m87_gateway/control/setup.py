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
