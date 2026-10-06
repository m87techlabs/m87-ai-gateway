"""Bounded opaque cursors for deterministic traffic metadata pagination."""

import base64
import json
from datetime import datetime

from m87_gateway.api.errors import GatewayError


def decode_cursor(value):
    if value is None:
        return None
    try:
        items = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if not isinstance(items, list) or len(items) != 2:
            raise ValueError
        created, request_id = items
        if (
            not isinstance(created, str)
            or len(created) > 64
            or not isinstance(request_id, str)
            or not 1 <= len(request_id) <= 128
        ):
            raise ValueError
        if datetime.fromisoformat(created).tzinfo is None:
            raise ValueError
        return created, request_id
    except (ValueError, TypeError, UnicodeError) as exc:
        raise GatewayError(
            422, "invalid_cursor", "Log cursor is invalid; refresh the results"
        ) from exc


def encode_cursor(item):
    return base64.urlsafe_b64encode(
        json.dumps([item["created_at"], item["request_id"]]).encode()
    ).decode()
