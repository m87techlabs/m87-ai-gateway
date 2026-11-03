from m87_gateway.api.schemas import ChatMessage
from m87_gateway.config.settings import GuardrailsConfig


def check_blocklist(messages: list[ChatMessage], settings: GuardrailsConfig) -> dict:
    return check_texts([message.text() for message in messages], settings)


def check_texts(texts: list[str], settings: GuardrailsConfig) -> dict:
    if any(len(text) > settings.max_message_chars for text in texts):
        return {"allowed": False, "reason": "message_too_large"}
    if settings.blocklist.enabled:
        joined = "\n".join(text.casefold() for text in texts)
        if any(term.casefold() in joined for term in settings.blocklist.blocked_terms):
            return {"allowed": False, "reason": "blocklist_match"}
    return {"allowed": True, "reason": None}
