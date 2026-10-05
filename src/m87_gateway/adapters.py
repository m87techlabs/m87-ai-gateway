"""Adapter registration shared by configuration, routing and the control plane."""

import re
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Capabilities:
    """Gateway-supported protocol features; model-specific support may be narrower."""

    streaming: bool = False
    tools: bool = False
    embeddings: bool = False
    images: bool = False
    multiple_choices: bool = False
    generation_parameters: frozenset[str] = frozenset({"temperature", "max_tokens"})
    response_formats: frozenset[str] = frozenset({"text"})
    strict_json_schema: bool = False

    def as_dict(self) -> dict:
        return {
            "text_chat": True,
            "streaming": self.streaming,
            "tools": self.tools,
            "embeddings": self.embeddings,
            "images": self.images,
            "multiple_choices": self.multiple_choices,
            "seed": "seed" in self.generation_parameters,
            "generation_parameters": sorted(self.generation_parameters),
            "response_formats": sorted(self.response_formats),
            "strict_json_schema": self.strict_json_schema,
        }


@dataclass(frozen=True)
class Adapter:
    name: str
    label: str
    factory: Callable
    default_url: str | None = None
    requires_key: bool = False
    model_discovery: bool = False
    capabilities: Capabilities = field(default_factory=Capabilities)


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


_COMPATIBLE_CAPABILITIES = Capabilities(
    generation_parameters=frozenset(
        {
            "temperature",
            "max_tokens",
            "top_p",
            "stop",
            "seed",
            "presence_penalty",
            "frequency_penalty",
        }
    ),
    response_formats=frozenset({"text", "json_object", "json_schema"}),
    strict_json_schema=True,
)
register_adapter(
    Adapter(
        "openai",
        "OpenAI",
        _openai,
        "https://api.openai.com/v1",
        True,
        True,
        capabilities=_COMPATIBLE_CAPABILITIES,
    )
)
register_adapter(
    Adapter(
        "ollama",
        "Ollama",
        _ollama,
        "http://localhost:11434",
        model_discovery=True,
        capabilities=Capabilities(
            generation_parameters=frozenset({"temperature", "max_tokens", "top_p", "stop", "seed"}),
            response_formats=frozenset({"text", "json_object", "json_schema"}),
        ),
    )
)
register_adapter(
    Adapter(
        "openai_compatible",
        "OpenAI-compatible server",
        _compatible,
        model_discovery=True,
        capabilities=_COMPATIBLE_CAPABILITIES,
    )
)
