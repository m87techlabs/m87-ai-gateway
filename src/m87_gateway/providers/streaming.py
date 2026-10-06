"""Bounded upstream text stream parsing and a shared chunk contract."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from m87_gateway.api.errors import GatewayError
from m87_gateway.api.schemas import ChatCompletionUsage

MAX_EVENT_BYTES = 65536


def invalid_stream():
    return GatewayError(
        502, "provider_invalid_payload", "Model provider returned an invalid stream"
    )


class Delta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["assistant"] | None = None
    content: str | None = None
    refusal: str | None = None
    tool_calls: None = None
    function_call: None = None
    audio: None = None


class ChunkChoice(BaseModel):
    index: Literal[0]
    delta: Delta
    finish_reason: str | None = None


class Chunk(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    object: Literal["chat.completion.chunk"]
    created: int = Field(ge=0, strict=True)
    model: str
    choices: list[ChunkChoice] = Field(max_length=1)
    usage: ChatCompletionUsage | None = None


def validate_chunk(data):
    try:
        return Chunk.model_validate(data).model_dump(exclude_none=True)
    except (ValidationError, TypeError) as exc:
        raise invalid_stream() from exc


async def lines(response):
    """Decode bounded UTF-8 lines without waiting for a fixed-size transport buffer."""
    buffer = bytearray()
    async for block in response.aiter_bytes():
        for part in block.splitlines(keepends=True):
            buffer.extend(part)
            if len(buffer) > MAX_EVENT_BYTES:
                raise invalid_stream()
            # Only LF is a wire delimiter; a CR can straddle transport blocks.
            if buffer.endswith(b"\n"):
                try:
                    yield bytes(buffer).decode("utf-8").rstrip("\r\n")
                except UnicodeError as exc:
                    raise invalid_stream() from exc
                buffer.clear()
    if buffer:
        try:
            yield bytes(buffer).decode("utf-8").rstrip("\r")
        except UnicodeError as exc:
            raise invalid_stream() from exc


async def sse_objects(response):
    parts = []
    size = 0
    async for line in lines(response):
        if not line:
            if parts:
                value = "\n".join(parts)
                parts.clear()
                size = 0
                if value == "[DONE]":
                    yield None
                    return
                try:
                    data = json.loads(value)
                except ValueError as exc:
                    raise invalid_stream() from exc
                if not isinstance(data, dict) or "error" in data:
                    raise invalid_stream()
                yield data
        elif line.startswith("data:"):
            value = line[5:].removeprefix(" ")
            size += len(value.encode("utf-8"))
            if size > MAX_EVENT_BYTES:
                raise invalid_stream()
            parts.append(value)
    raise invalid_stream()  # Missing terminal sentinel / interrupted event.
