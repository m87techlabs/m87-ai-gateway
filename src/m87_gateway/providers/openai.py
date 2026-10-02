import os

from m87_gateway.api.errors import GatewayError
from m87_gateway.api.schemas import ChatCompletionRequest
from m87_gateway.providers.base import Provider


class OpenAIProvider(Provider):
    def __init__(self, config, api_key: str | None = None):
        super().__init__(config)
        self.api_key = api_key

    async def chat_completions(self, payload: ChatCompletionRequest, model: str) -> dict:
        api_key = self.api_key or os.getenv(self.config.api_key_env or "")
        if not api_key:
            raise GatewayError(
                503, "provider_not_configured", "Model provider credentials are unavailable"
            )
        body = payload.model_dump(exclude_none=True, exclude={"task"})
        body["model"] = model
        data = await self.post("/chat/completions", body, {"Authorization": f"Bearer {api_key}"})
        data["model"] = f"openai:{model}"
        return data
