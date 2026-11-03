from m87_gateway.providers.openai import OpenAIProvider


class OllamaProvider(OpenAIProvider):
    """Ollama's OpenAI-compatible API, so tools, images and reasoning controls pass through."""

    prefix = "ollama"
    requires_key = False
    api_prefix = "/v1"
