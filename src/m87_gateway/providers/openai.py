import os

from m87_gateway.api.errors import GatewayError
from m87_gateway.api.schemas import ChatCompletionRequest
from m87_gateway.providers.base import Provider
from m87_gateway.providers.streaming import sse_objects, validate_chunk, invalid_stream


class OpenAIProvider(Provider):
    prefix = "openai"
    requires_key = True

    def __init__(self, config, api_key: str | None = None):
        super().__init__(config)
        self.api_key = api_key

    async def chat_completions(self, payload: ChatCompletionRequest, model: str) -> dict:
        api_key = self.api_key or os.getenv(self.config.api_key_env or "")
        if not api_key and self.requires_key:
            raise GatewayError(
                503, "provider_not_configured", "Model provider credentials are unavailable"
            )
        body = payload.model_dump(exclude_none=True, exclude={"task", "user"}, by_alias=True)
        body["model"] = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        data = await self.post("/chat/completions", body, headers)
        data["model"] = f"{self.prefix}:{model}"
        return data

    async def stream_chat_completions(self, payload, model):
        key = self.api_key or os.getenv(self.config.api_key_env or "")
        if not key and self.requires_key:
            raise GatewayError(
                503, "provider_not_configured", "Model provider credentials are unavailable"
            )
        body = payload.model_dump(exclude_none=True, exclude={"task", "user"}, by_alias=True)
        body.update(model=model, stream=True, stream_options={"include_usage": True})
        finished = False
        identity = None
        async with self.stream(
            "/chat/completions", body, {"Authorization": f"Bearer {key}"} if key else None
        ) as response:
            async for data in sse_objects(response):
                if data is None:
                    if not finished:
                        raise invalid_stream()
                    return
                data["model"] = f"{self.prefix}:{model}"
                chunk = validate_chunk(data)
                current = (chunk["id"], chunk["created"])
                if identity is not None and current != identity:
                    raise invalid_stream()
                identity = current
                choices = chunk["choices"]
                if choices:
                    if finished:
                        raise invalid_stream()
                    finished = choices[0].get("finish_reason") is not None
                elif not finished:
                    raise invalid_stream()
                yield chunk

    async def list_models(self) -> list[str]:
        api_key = self.api_key or os.getenv(self.config.api_key_env or "")
        if self.requires_key and not api_key:
            raise GatewayError(
                503, "provider_not_configured", "Model provider credentials are unavailable"
            )
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        data = await self.get("/models", headers)
        return self.model_names(data, "data", "id")


class OpenAICompatibleProvider(OpenAIProvider):
    """Text chat adapter for compatible endpoints, including vLLM."""

    prefix = "openai_compatible"
    requires_key = False
