from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(..., examples=["user"])
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="auto")
    messages: list[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None
    task: str | None = None
