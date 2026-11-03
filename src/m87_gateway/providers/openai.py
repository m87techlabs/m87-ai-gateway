import os

from m87_gateway.api.errors import GatewayError
from m87_gateway.api.schemas import ChatCompletionRequest
from m87_gateway.providers.base import Provider
from m87_gateway.providers.streaming import sse_objects, validate_chunk, invalid_stream


class OpenAIProvider(Provider):
    prefix = "openai"
    requires_key = True
    api_prefix = ""

    def __init__(self, config, api_key: str | None = None):
        super().__init__(config)
        self.api_key = api_key

    def auth_headers(self) -> dict | None:
        api_key = self.api_key or os.getenv(self.config.api_key_env or "")
        if not api_key and self.requires_key:
            raise GatewayError(
                503, "provider_not_configured", "Model provider credentials are unavailable"
            )
        return {"Authorization": f"Bearer {api_key}"} if api_key else None

    async def chat_completions(self, payload: ChatCompletionRequest, model: str) -> dict:
        headers = self.auth_headers()
        body = payload.model_dump(exclude_none=True, exclude={"task", "user"}, by_alias=True)
        body["model"] = model
        data = await self.post(f"{self.api_prefix}/chat/completions", body, headers)
        data["model"] = f"{self.prefix}:{model}"
        return data

    async def stream_chat_completions(self, payload, model):
        headers = self.auth_headers()
        body = payload.model_dump(exclude_none=True, exclude={"task", "user"}, by_alias=True)
        body.update(model=model, stream=True, stream_options={"include_usage": True})
        finished = False
        identity = None
        async with self.stream(f"{self.api_prefix}/chat/completions", body, headers) as response:
            async for data in sse_objects(response):
                if data is None:
                    if not finished:
                        raise invalid_stream()
                    return
                data["model"] = f"{self.prefix}:{model}"
                chunk = validate_chunk(data)
                if identity is not None and chunk["id"] != identity:
                    raise invalid_stream()
                identity = chunk["id"]
                finished = finished or any(
                    choice.get("finish_reason") is not None for choice in chunk["choices"]
                )
                yield chunk

    async def embeddings(self, payload, model: str) -> dict:
        headers = self.auth_headers()
        body = payload.model_dump(exclude_none=True, exclude={"user"}, by_alias=True)
        body["model"] = model
        return await self.post(f"{self.api_prefix}/embeddings", body, headers)

    async def list_models(self) -> list[str]:
        data = await self.get(f"{self.api_prefix}/models", self.auth_headers())
        return self.model_names(data, "data", "id")


class OpenAICompatibleProvider(OpenAIProvider):
    """Adapter for compatible endpoints, including vLLM."""

    prefix = "openai_compatible"
    requires_key = False
