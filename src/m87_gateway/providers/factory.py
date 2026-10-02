from m87_gateway.api.errors import GatewayError
from m87_gateway.config import GatewaySettings
from m87_gateway.config.settings import ProviderConfig
from m87_gateway.providers.base import Provider
from m87_gateway.adapters import adapters


def get_provider(provider_name: str, settings: GatewaySettings, control_store=None) -> Provider:
    providers = adapters()
    if provider_name not in providers:
        raise GatewayError(400, "unsupported_provider", "Unsupported model provider")
    config = settings.providers.for_adapter(provider_name)
    if not config.enabled:
        raise GatewayError(503, "provider_disabled", "Requested model provider is disabled")
    if config.base_url is None:
        config = ProviderConfig.model_validate(
            {**config.model_dump(), "base_url": providers[provider_name].default_url}
        )
    if not config.base_url:
        raise GatewayError(503, "provider_not_configured", "Model provider endpoint is unavailable")
    stored_key = control_store.get_provider_key(provider_name) if control_store else None
    return providers[provider_name].factory(config, stored_key)
