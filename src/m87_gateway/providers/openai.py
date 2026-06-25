import os
import httpx

from m87_gateway.api.schemas import ChatCompletionRequest
from m87_gateway.providers.base import Provider


class OpenAIProvider(Provider):
    async def chat_completions(self, payload: ChatCompletionRequest, model: str) -> dict:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        body = payload.model_dump(exclude_none=True)
        body["model"] = model

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
            )
            response.raise_for_status()
            return response.json()
