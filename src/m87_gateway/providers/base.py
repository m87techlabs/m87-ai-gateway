from abc import ABC, abstractmethod

from m87_gateway.api.schemas import ChatCompletionRequest, ChatCompletionResponse


class Provider(ABC):
    @abstractmethod
    async def chat_completions(self, payload: ChatCompletionRequest, model: str) -> ChatCompletionResponse | dict:
        raise NotImplementedError
