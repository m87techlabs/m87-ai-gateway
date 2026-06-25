import os
import time

import httpx

from m87_gateway.api.schemas import ChatCompletionRequest
from m87_gateway.providers.base import Provider


class OllamaProvider(Provider):
    async def chat_completions(self, payload: ChatCompletionRequest, model: str) -> dict:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        prompt = "\n".join(f"{m.role}: {m.content}" for m in payload.messages)
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            data = response.json()

        return {
            "id": "m87-ollama-response",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"ollama:{model}",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": data.get("response", "")},
                    "finish_reason": "stop",
                }
            ],
            "usage": None,
        }
