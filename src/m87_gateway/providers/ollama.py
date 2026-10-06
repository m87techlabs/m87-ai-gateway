import json
import time
import os
from uuid import uuid4

from m87_gateway.api.errors import GatewayError
from m87_gateway.api.schemas import ChatCompletionRequest
from m87_gateway.providers.base import Provider
from m87_gateway.providers.streaming import lines, invalid_stream, validate_chunk


class OllamaProvider(Provider):
    def __init__(self, config, api_key=None):
        super().__init__(config)
        self.api_key = api_key

    def headers(self):
        key = self.api_key or os.getenv(self.config.api_key_env or "")
        return {"Authorization": f"Bearer {key}"} if key else None

    async def list_models(self) -> list[str]:
        return self.model_names(await self.get("/api/tags", self.headers()), "models", "name")

    def body(self, payload: ChatCompletionRequest, model: str) -> dict:
        options = {}
        if payload.temperature is not None:
            options["temperature"] = payload.temperature
        if payload.max_tokens is not None:
            options["num_predict"] = payload.max_tokens
        for field in ("top_p", "stop", "seed"):
            value = getattr(payload, field)
            if value is not None:
                options[field] = [value] if field == "stop" and isinstance(value, str) else value
        body = {
            "model": model,
            "messages": [message.model_dump() for message in payload.messages],
            "stream": False,
            "options": options,
        }
        if payload.response_format is not None:
            if payload.response_format.type == "json_object":
                body["format"] = "json"
            elif payload.response_format.type == "json_schema":
                body["format"] = payload.response_format.json_schema.schema_value
        return body

    async def chat_completions(self, payload: ChatCompletionRequest, model: str) -> dict:
        data = await self.post("/api/chat", self.body(payload, model), self.headers())
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

    async def stream_chat_completions(self, payload, model):
        body = self.body(payload, model)
        body["stream"] = True
        identity = {
            "id": f"chatcmpl-{uuid4().hex}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": f"ollama:{model}",
        }
        async with self.stream("/api/chat", body, self.headers()) as response:
            async for line in lines(response):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError as exc:
                    raise invalid_stream() from exc
                if (
                    not isinstance(data, dict)
                    or "error" in data
                    or type(data.get("done")) is not bool
                ):
                    raise invalid_stream()
                message = data.get("message")
                if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                    raise invalid_stream()
                if message.get("tool_calls"):
                    raise invalid_stream()
                chunk = {
                    **identity,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": message["content"]},
                            "finish_reason": (data.get("done_reason") or "stop")
                            if data["done"]
                            else None,
                        }
                    ],
                }
                yield validate_chunk(chunk)
                if data["done"]:
                    prompt, completion = data.get("prompt_eval_count"), data.get("eval_count")
                    if (
                        type(prompt) is int
                        and type(completion) is int
                        and min(prompt, completion) >= 0
                    ):
                        yield {
                            **identity,
                            "choices": [],
                            "usage": {
                                "prompt_tokens": prompt,
                                "completion_tokens": completion,
                                "total_tokens": prompt + completion,
                            },
                        }
                    return
        raise invalid_stream()
