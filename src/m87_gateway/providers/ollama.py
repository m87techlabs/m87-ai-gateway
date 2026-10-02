import time
import os
from uuid import uuid4

from m87_gateway.api.errors import GatewayError
from m87_gateway.api.schemas import ChatCompletionRequest
from m87_gateway.providers.base import Provider


class OllamaProvider(Provider):
    def __init__(self, config, api_key=None):
        super().__init__(config)
        self.api_key = api_key

    def headers(self):
        key = self.api_key or os.getenv(self.config.api_key_env or "")
        return {"Authorization": f"Bearer {key}"} if key else None

    async def list_models(self) -> list[str]:
        return self.model_names(await self.get("/api/tags", self.headers()), "models", "name")

    async def chat_completions(self, payload: ChatCompletionRequest, model: str) -> dict:
        options = {}
        if payload.temperature is not None:
            options["temperature"] = payload.temperature
        if payload.max_tokens is not None:
            options["num_predict"] = payload.max_tokens
        data = await self.post(
            "/api/chat",
            {
                "model": model,
                "messages": [message.model_dump() for message in payload.messages],
                "stream": False,
                "options": options,
            },
            self.headers(),
        )
        message = data.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise GatewayError(
                502, "invalid_provider_response", "Model provider returned an invalid response"
            )
        prompt = data.get("prompt_eval_count")
        completion = data.get("eval_count")
        usage = None
        if type(prompt) is int and type(completion) is int and min(prompt, completion) >= 0:
            usage = {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
            }
        return {
            "id": f"chatcmpl-{uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"ollama:{model}",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": message["content"]},
                    "finish_reason": data.get("done_reason") or "stop",
                }
            ],
            "usage": usage,
        }
