from m87_gateway.api.errors import GatewayError
from m87_gateway.config import GatewaySettings
from m87_gateway.providers.base import Provider
from m87_gateway.providers.ollama import OllamaProvider
from m87_gateway.providers.openai import OpenAIProvider


def get_provider(provider_name: str, settings: GatewaySettings) -> Provider:
    providers = {"ollama": OllamaProvider, "openai": OpenAIProvider}
    if provider_name not in providers:
        raise GatewayError(400, "unsupported_provider", "Unsupported model provider")
    config = getattr(settings.providers, provider_name)
    if not config.enabled:
        raise GatewayError(503, "provider_disabled", "Requested model provider is disabled")
    if config.base_url is None:
        default = (
            "http://localhost:11434" if provider_name == "ollama" else "https://api.openai.com/v1"
        )
        config = config.model_copy(update={"base_url": default})
    return providers[provider_name](config)
