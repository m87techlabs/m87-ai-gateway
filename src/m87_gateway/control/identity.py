"""Who is calling the admin API: signed console sessions, roles and the audit actor."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, Header, Request

from m87_gateway.api.errors import GatewayError
from m87_gateway.control.backends import Backend

SESSION_COOKIE = "m87_console_session"
SESSION_SECONDS = 12 * 3600
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_SESSION_CHARS = 2048

Role = Literal["admin", "readonly"]


@dataclass(frozen=True)
class Principal:
    actor: str
    role: Role
    method: Literal["key", "sso"]
    subject: str | None = None


ADMIN_KEY_PRINCIPAL = Principal(actor="admin-key", role="admin", method="key")
SYSTEM_PRINCIPAL = Principal(actor="system", role="admin", method="key")

# Repositories read this when they write an audit event, so no call site can forget the actor.
current_principal: ContextVar[Principal] = ContextVar("current_principal", default=SYSTEM_PRINCIPAL)


def _sign(signing_key: str, body: str) -> str:
    return hmac.new(
        signing_key.encode(), f"console-session:{body}".encode(), hashlib.sha256
    ).hexdigest()


def issue_session(signing_key: str, principal: Principal, seconds: int = SESSION_SECONDS) -> str:
    now = int(time.time())
    claims = {
        "iat": now,
        "exp": now + seconds,
        "actor": principal.actor,
        "role": principal.role,
        "method": principal.method,
        "sub": principal.subject,
    }
    body = base64.urlsafe_b64encode(json.dumps(claims, separators=(",", ":")).encode()).decode()
    return f"{body}.{_sign(signing_key, body)}"


def read_session(token: str | None, signing_key: str) -> Principal | None:
    """Signed with the admin key, so changing that key ends every console session."""
    if not token or len(token) > MAX_SESSION_CHARS:
        return None
    body, separator, signature = token.partition(".")
    if not separator or not secrets.compare_digest(
        signature.encode(), _sign(signing_key, body).encode()
    ):
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(body))
        if not int(claims["iat"]) <= time.time() < int(claims["exp"]):
            return None
        if claims["role"] not in {"admin", "readonly"} or claims["method"] not in {"key", "sso"}:
            return None
        return Principal(
            actor=str(claims["actor"]),
            role=claims["role"],
            method=claims["method"],
            subject=claims.get("sub"),
        )
    except (ValueError, KeyError, TypeError):
        return None


def secure_cookie(request: Request) -> bool:
    """A TLS proxy hides the scheme, so a request for the configured HTTPS address counts too."""
    if request.url.scheme == "https":
        return True
    oidc = getattr(request.app.state, "oidc", None)
    if oidc is None:
        return False
    public = urlsplit(oidc.public_url)
    return public.scheme == "https" and request.headers.get("host") == public.netloc


def store_of(request: Request) -> Backend:
    store = getattr(request.app.state, "control_store", None)
    if store is None:
        raise GatewayError(404, "control_plane_disabled", "Control plane is disabled")
    return store


def _authenticate(request: Request, authorization: str | None) -> Principal | None:
    scheme, _, token = (authorization or "").partition(" ")
    expected = getattr(request.app.state, "admin_api_key", "")
    if not expected:
        return None
    if (
        scheme.lower() == "bearer"
        and token
        and secrets.compare_digest(token.encode(), expected.encode())
    ):
        return ADMIN_KEY_PRINCIPAL
    # Browsers cannot add this header cross-site without CORS, on top of SameSite=Strict.
    if request.method in SAFE_METHODS or "x-gateway-console" in request.headers:
        return read_session(request.cookies.get(SESSION_COOKIE), expected)
    return None


async def require_reader(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> Backend:
    principal = _authenticate(request, authorization)
    if principal is None:
        raise GatewayError(
            401, "invalid_admin_key", "Missing or invalid admin key", "authentication_error"
        )
    request.state.principal = principal
    current_principal.set(principal)
    return store_of(request)


async def require_admin(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> Backend:
    store = await require_reader(request, authorization)
    if request.state.principal.role != "admin":
        raise GatewayError(
            403,
            "insufficient_role",
            "Your role is read-only. Ask an admin to make this change.",
            "permission_error",
        )
    return store


# Routes are admin-only unless they deliberately ask for ReaderStore, so a new route starts closed.
AdminStore = Annotated[Backend, Depends(require_admin)]
ReaderStore = Annotated[Backend, Depends(require_reader)]
