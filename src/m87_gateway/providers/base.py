from abc import ABC, abstractmethod

import httpx

from m87_gateway.api.errors import GatewayError
from m87_gateway.api.schemas import ChatCompletionRequest
from m87_gateway.config.settings import ProviderConfig


class Provider(ABC):
    def __init__(self, config: ProviderConfig):
        self.config = config

    async def post(self, path: str, body: dict, headers: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(
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
            upstream_status = exc.response.status_code
            if upstream_status == 429:
                code, status = "provider_rate_limited", 503
            elif upstream_status in {408, 409} or upstream_status >= 500:
                code, status = "provider_error", 502
            else:
                code, status = "provider_rejected", 502
            raise GatewayError(
                status, code, "Model provider could not complete the request"
            ) from exc
        except httpx.RequestError as exc:
            raise GatewayError(
                502, "provider_error", "Model provider could not complete the request"
            ) from exc
        except ValueError as exc:
            raise GatewayError(
                502, "provider_invalid_payload", "Model provider could not complete the request"
            ) from exc

    @abstractmethod
    async def chat_completions(self, payload: ChatCompletionRequest, model: str) -> dict:
        """Return a non-streaming chat completion; never fabricate provider usage."""
        raise NotImplementedError
