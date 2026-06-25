from m87_gateway.providers.ollama import OllamaProvider
from m87_gateway.providers.openai import OpenAIProvider


def get_provider(provider_name: str):
    if provider_name == "ollama":
        return OllamaProvider()
    if provider_name == "openai":
        return OpenAIProvider()
    raise ValueError(f"Unsupported provider: {provider_name}")
