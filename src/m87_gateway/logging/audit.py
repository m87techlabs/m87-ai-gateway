import json
import logging

logger = logging.getLogger("m87_gateway.audit")
logging.basicConfig(level=logging.INFO)

REDACTED_KEYS = {"authorization", "api_key", "token", "password", "secret"}


def _redact(data: dict) -> dict:
    redacted = {}
    for key, value in data.items():
        if key.lower() in REDACTED_KEYS:
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted


def audit_log(event: str, **fields) -> None:
    payload = {"event": event, **_redact(fields)}
    logger.info(json.dumps(payload, default=str))
