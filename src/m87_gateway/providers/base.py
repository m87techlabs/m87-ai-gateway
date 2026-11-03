from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from functools import lru_cache

import httpx

from m87_gateway.api.errors import GatewayError
from m87_gateway.api.schemas import ChatCompletionRequest
from m87_gateway.config.settings import ProviderConfig


@lru_cache(maxsize=1)
def _tls_context():
    # Building a TLS context takes milliseconds on the event loop; one is enough per process.
    return httpx.create_ssl_context()


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, verify=_tls_context())


def upstream_error(upstream_status: int) -> GatewayError:
    """Keep the upstream body private, but say which status the provider answered with."""
    if upstream_status == 429:
        code, status = "provider_rate_limited", 503
    elif upstream_status in {408, 409} or upstream_status >= 500:
        code, status = "provider_error", 502
    else:
        code, status = "provider_rejected", 502
    return GatewayError(
        status,
        code,
        f"Model provider could not complete the request (HTTP {upstream_status})",
        upstream_status=upstream_status,
    )


class Provider(ABC):
    def __init__(self, config: ProviderConfig):
        self.config = config

    async def post(self, path: str, body: dict, headers: dict | None = None) -> dict:
        return await self._request("POST", path, headers, body)

    async def get(self, path: str, headers: dict | None = None) -> dict:
        return await self._request("GET", path, headers)

    async def list_models(self) -> list[str]:
        raise GatewayError(400, "discovery_unavailable", "Enter a model identifier manually")

    @staticmethod
    def model_names(data: dict, collection: str, field: str) -> list[str]:
        items = data.get(collection)
        if not isinstance(items, list) or any(
            not isinstance(item, dict) or not isinstance(item.get(field), str) for item in items
        ):
            raise GatewayError(502, "provider_invalid_payload", "Invalid provider model list")
        return sorted({item[field] for item in items if item[field]})

    async def _request(self, method, path, headers=None, body=None) -> dict:
        try:
            async with _client(self.config.timeout_seconds) as client:
                response = await client.request(
                    method,
                    f"{self.config.base_url}{path}",
                    json=body,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected a response object")
            return data
        except httpx.TimeoutException as exc:
            raise GatewayError(504, "provider_timeout", "Model provider timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise upstream_error(exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise GatewayError(
                502, "provider_error", "Model provider could not complete the request"
            ) from exc
        except ValueError as exc:
            raise GatewayError(
                502, "provider_invalid_payload", "Model provider could not complete the request"
            ) from exc

    @asynccontextmanager
    async def stream(self, path, body, headers=None):
        try:
            async with _client(self.config.timeout_seconds) as client:
                async with client.stream(
                    "POST", f"{self.config.base_url}{path}", json=body, headers=headers
                ) as response:
                    response.raise_for_status()
                    yield response
        except httpx.TimeoutException as exc:
            raise GatewayError(504, "provider_timeout", "Model provider timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise upstream_error(exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise GatewayError(
                502, "provider_error", "Model provider could not complete the request"
            ) from exc

    async def stream_chat_completions(self, payload, model):
        raise GatewayError(
            422, "unsupported_streaming", "Selected adapter does not support streaming"
        )
        yield  # Adapter extensions implement an asynchronous iterator of normalized chunks.

    async def embeddings(self, payload, model: str) -> dict:
        raise GatewayError(
            422,
            "unsupported_embeddings",
            "Selected adapter does not support embeddings",
            "invalid_request_error",
        )

    @abstractmethod
    async def chat_completions(self, payload: ChatCompletionRequest, model: str) -> dict:
        """Return a non-streaming chat completion; never fabricate provider usage."""
        raise NotImplementedError
