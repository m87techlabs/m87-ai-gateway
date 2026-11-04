"""Configuration readiness; live model discovery is a separate explicit probe."""

import os

from m87_gateway.adapters import adapters


def diagnostics(state):
    settings = state.settings
    name = settings.routing.default_model.split(":", 1)[0]
    adapter = adapters()[name]
    config = settings.providers.for_adapter(name)
    store = state.control_store
    checks = []

    def check(label, ok, message):
        checks.append({"name": label, "ok": bool(ok), "message": message})

    check("Default provider", config.enabled, "Enable the default provider in Providers.")
    check(
        "Endpoint",
        config.base_url or adapter.default_url,
        "Set the provider's endpoint in Providers.",
    )
    try:
        if store:
            store.check_storage()
        check("Local storage", True, "Local storage is accessible.")
        if adapter.requires_key:
            has_key = (store and store.get_provider_key(name)) or (
                config.api_key_env and os.getenv(config.api_key_env)
            )
            check("Provider credential", has_key, "Add a provider key in Providers.")
    except Exception:
        check("Local storage", False, "Check storage availability and permissions.")
    return {
        "ready": all(item["ok"] for item in checks),
        "default_model": settings.routing.default_model,
        "checks": checks,
        **state.inflight_limiter.snapshot(),
        "scope": "Configuration and local storage. Use Test connection in Providers to check connectivity; "
        "send a completion to verify inference.",
    }
