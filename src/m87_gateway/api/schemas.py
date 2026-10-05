import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from m87_gateway.config.settings import validate_model


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "developer", "user", "assistant"]
    content: str = Field(min_length=1)


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


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = "auto"
    messages: list[ChatMessage] = Field(min_length=1, max_length=128)
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
    stream: Literal[False] = False

    @field_validator("model")
    @classmethod
    def valid_model(cls, value: str) -> str:
        return validate_model(value)


class ChatCompletionResponseMessage(BaseModel):
    role: Literal["assistant"]
    content: str


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatCompletionResponseMessage
    finish_reason: str | None = None


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int = Field(ge=0, strict=True)
    completion_tokens: int = Field(ge=0, strict=True)
    total_tokens: int = Field(ge=0, strict=True)


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice] = Field(min_length=1)
    usage: ChatCompletionUsage | None = None
