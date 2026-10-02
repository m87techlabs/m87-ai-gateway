"""Adapter registration shared by configuration, routing and the control plane."""

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Adapter:
    name: str
    label: str
    factory: Callable
    default_url: str | None = None
    requires_key: bool = False
    model_discovery: bool = False


_registry: dict[str, Adapter] = {}


def register_adapter(adapter: Adapter) -> None:
    """Register before loading settings; factories receive (config, stored_key)."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", adapter.name):
        raise ValueError("Invalid adapter identifier")
    if adapter.name in _registry:
        raise ValueError("Adapter is already registered")
    _registry[adapter.name] = adapter


def adapters() -> dict[str, Adapter]:
    return dict(_registry)


def _openai(config, key):
    from m87_gateway.providers.openai import OpenAIProvider

    return OpenAIProvider(config, api_key=key)


def _ollama(config, key):
    from m87_gateway.providers.ollama import OllamaProvider

    return OllamaProvider(config, api_key=key)


def _compatible(config, key):
    from m87_gateway.providers.openai import OpenAICompatibleProvider

    return OpenAICompatibleProvider(config, api_key=key)


register_adapter(Adapter("openai", "OpenAI", _openai, "https://api.openai.com/v1", True, True))
register_adapter(
    Adapter("ollama", "Ollama", _ollama, "http://localhost:11434", model_discovery=True)
)
register_adapter(
    Adapter("openai_compatible", "OpenAI-compatible server", _compatible, model_discovery=True)
)
