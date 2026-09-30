from m87_gateway.api.schemas import ChatMessage
from m87_gateway.config.settings import GuardrailsConfig


def check_blocklist(messages: list[ChatMessage], settings: GuardrailsConfig) -> dict:
    if any(len(message.content) > settings.max_message_chars for message in messages):
        return {"allowed": False, "reason": "message_too_large"}
    if settings.blocklist.enabled:
        joined = "\n".join(message.content.casefold() for message in messages)
        if any(term.casefold() in joined for term in settings.blocklist.blocked_terms):
            return {"allowed": False, "reason": "blocklist_match"}
    return {"allowed": True, "reason": None}
