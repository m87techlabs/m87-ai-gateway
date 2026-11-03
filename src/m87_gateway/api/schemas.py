import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from m87_gateway.adapters import adapters

PLAIN_ROLES = {"system", "developer", "user", "assistant"}
USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


def validate_request_model(value: str) -> str:
    """Accept auto, provider:model or a bare upstream name such as qwen3:14b."""
    provider, separator, model = value.partition(":")
    if (
        not value
        or len(value) > 200
        or any(character.isspace() for character in value)
        or (separator and provider in adapters() and not model)
    ):
        raise ValueError("Use auto, a provider:model identifier or an upstream model name")
    return value


class ChatMessage(BaseModel):
    """Forwarded as received, so tools, images and vendor fields reach the provider."""

    model_config = ConfigDict(extra="allow")
    role: str = Field(min_length=1, max_length=64)
    content: str | list[dict[str, JsonValue]] | None = None

    def text(self) -> str:
        """The readable text of this message, for policy checks and size limits."""
        if isinstance(self.content, str):
            return self.content
        return "\n".join(
            part["text"]
            for part in self.content or []
            if part.get("type") == "text" and isinstance(part.get("text"), str)
        )

    def is_plain(self) -> bool:
        return (
            self.role in PLAIN_ROLES
            and isinstance(self.content, str)
            and bool(self.content)
            and not self.model_extra
        )


class TextFormat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text"]


class JsonObjectFormat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["json_object"]


class JsonSchemaDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=1024)
    strict: bool | None = Field(default=None, strict=True)
    schema_value: dict[str, JsonValue] = Field(alias="schema", min_length=1)

    @field_validator("schema_value")
    @classmethod
    def bounded_schema(cls, value):
        if len(json.dumps(value, allow_nan=False)) > 65536:
            raise ValueError("JSON schema exceeds the gateway limit")
        return value


class JsonSchemaFormat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["json_schema"]
    json_schema: JsonSchemaDefinition


StopSequence = Annotated[str, Field(min_length=1, max_length=1024, strict=True)]
StopSequences = Annotated[list[StopSequence], Field(min_length=1, max_length=4)]
ResponseFormat = Annotated[
    TextFormat | JsonObjectFormat | JsonSchemaFormat, Field(discriminator="type")
]


class StreamOptions(BaseModel):
    model_config = ConfigDict(extra="allow")
    include_usage: bool = Field(default=False, strict=True)


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = "auto"
    messages: list[ChatMessage] = Field(min_length=1, max_length=2048)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    top_p: float | None = Field(default=None, ge=0, le=1, strict=True)
    stop: StopSequence | StopSequences | None = None
    seed: int | None = Field(default=None, ge=-(2**63), le=2**63 - 1, strict=True)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2, strict=True)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2, strict=True)
    response_format: ResponseFormat | None = None
    user: str | None = Field(default=None, min_length=1, max_length=200, strict=True)
    task: str | None = Field(default=None, min_length=1, max_length=100)
    stream: bool = Field(default=False, strict=True)
    stream_options: StreamOptions | None = None

    @model_validator(mode="after")
    def streaming_options(self):
        if self.stream_options is not None and not self.stream:
            raise ValueError("stream_options requires stream true")
        return self

    @field_validator("model")
    @classmethod
    def valid_model(cls, value: str) -> str:
        return validate_request_model(value)

    def is_plain(self) -> bool:
        """True when every field is one the gateway models itself; strict mode requires it."""
        return (
            not self.model_extra
            and all(message.is_plain() for message in self.messages)
            and not (self.stream_options and self.stream_options.model_extra)
        )


class EmbeddingRequest(BaseModel):
    """Forwarded as received; extra fields such as dimensions reach the provider."""

    model_config = ConfigDict(extra="allow")
    model: str = "auto"
    input: str | list[str] | list[int] | list[list[int]] = Field(min_length=1, max_length=2048)
    user: str | None = Field(default=None, min_length=1, max_length=200, strict=True)

    @field_validator("model")
    @classmethod
    def valid_model(cls, value: str) -> str:
        return validate_request_model(value)

    def texts(self) -> list[str]:
        """Text inputs only; pre-tokenized inputs carry no readable content."""
        if isinstance(self.input, str):
            return [self.input]
        return [item for item in self.input if isinstance(item, str)]


class ChatCompletionResponseMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: Literal["assistant"]
    content: str | None = None


class ChatCompletionChoice(BaseModel):
    model_config = ConfigDict(extra="allow")
    index: int
    message: ChatCompletionResponseMessage
    finish_reason: str | None = None


class ChatCompletionUsage(BaseModel):
    model_config = ConfigDict(extra="allow")
    prompt_tokens: int = Field(ge=0, strict=True)
    completion_tokens: int = Field(ge=0, strict=True)
    total_tokens: int = Field(ge=0, strict=True)


class ChatCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice] = Field(min_length=1)
    usage: ChatCompletionUsage | None = None
