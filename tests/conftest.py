import os

import pytest

from m87_gateway.config import get_settings


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("GATEWAY_", "M87_GATEWAY_", "SERVER_")) or name in {
            "OPENAI_API_KEY",
            "OLLAMA_BASE_URL",
        }:
            monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
