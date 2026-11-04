"""OpenID Connect sign-in for the console: Authorization Code with PKCE, off until configured."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from m87_gateway.api.errors import GatewayError
from m87_gateway.config.settings import OidcConfig

from .identity import (
    SESSION_COOKIE,
    Principal,
    Role,
    current_principal,
    issue_session,
    secure_cookie,
    store_of,
)

router = APIRouter()

STATE_COOKIE = "m87_sso_state"
STATE_SECONDS = 600
CALLBACK_PATH = "/admin/auth/callback"
CACHE_SECONDS = 3600
JWKS_REFRESH_SECONDS = 60
LOGIN_CHECK_SECONDS = 15
SIGNING_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384"]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


class OidcConfigError(ValueError):
    """The message is shown to the operator at startup, so it never holds the secret."""


class OidcError(Exception):
    """Sign-in failed. The code selects a fixed message; provider text is never shown."""

    def __init__(self, code: str = "failed") -> None:
        super().__init__(code)
        self.code = code


def _valid_url(value: str, name: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise OidcConfigError(f"{name} must be an HTTP(S) URL without credentials or a query")
    if parsed.scheme == "http" and parsed.hostname not in LOCAL_HOSTS:
        raise OidcConfigError(f"{name} must use HTTPS unless it points at this machine")
    return value.rstrip("/")


def _read_secret(config: OidcConfig) -> str:
    path = os.getenv(f"{config.client_secret_env}_FILE", "")
    try:
        secret = Path(path).read_text().strip() if path else os.getenv(config.client_secret_env, "")
    except OSError:
        raise OidcConfigError(f"Cannot read {config.client_secret_env}_FILE") from None
    if not secret:
        raise OidcConfigError(f"SSO needs a client secret in {config.client_secret_env}")
    return secret


@dataclass
class OidcClient:
    issuer: str
    client_id: str
    client_secret: str = field(repr=False)
    public_url: str
    signing_key: str = field(repr=False)
    scopes: str
    role_claim: tuple[str, ...]
    admin_role: str
    readonly_role: str
    session_seconds: int
    _discovery: dict[str, Any] | None = field(default=None, repr=False)
    _discovered_at: float = 0
    _jwks: dict[str, Any] | None = field(default=None, repr=False)
    _jwks_at: float = 0

    @classmethod
    def create(cls, config: OidcConfig, signing_key: str) -> "OidcClient":
        if not config.client_id or not config.public_url:
            raise OidcConfigError("SSO needs a client ID and the gateway's public URL")
        claim = config.role_claim
        return cls(
            issuer=_valid_url(config.issuer, "SSO issuer"),
            client_id=config.client_id,
            client_secret=_read_secret(config),
            public_url=_valid_url(config.public_url, "Gateway public URL"),
            signing_key=signing_key,
            scopes=config.scopes,
            role_claim=(
                tuple(claim.split(".")) if claim else ("resource_access", config.client_id, "roles")
            ),
            admin_role=config.admin_role,
            readonly_role=config.readonly_role,
            session_seconds=config.session_minutes * 60,
        )

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}{CALLBACK_PATH}"

    def _derive(self, purpose: str, state: str) -> str:
        digest = hmac.new(
            self.signing_key.encode(), f"oidc:{purpose}:{state}".encode(), hashlib.sha256
        ).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def new_state(self) -> str:
        """Nonce and PKCE verifier derive from the state, so no sign-in data is stored."""
        body = f"{int(time.time())}.{secrets.token_urlsafe(32)}"
        return f"{body}.{self._derive('state', body)}"

    def valid_state(self, state: str) -> bool:
        issued, _, rest = state.partition(".")
        random_part, _, signature = rest.partition(".")
        if not issued.isdecimal() or len(issued) > 12 or not random_part or not signature:
            return False
        if not 0 <= time.time() - int(issued) < STATE_SECONDS:
            return False
        expected = self._derive("state", f"{issued}.{random_part}")
        return secrets.compare_digest(signature.encode(), expected.encode())

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError):
            raise OidcError("unavailable") from None
        if not isinstance(document, dict):
            raise OidcError("unavailable")
        return document

    async def discovery(self, max_age: int = CACHE_SECONDS) -> dict[str, Any]:
        if self._discovery and time.time() - self._discovered_at < max_age:
            return self._discovery
        document = await self._get_json(f"{self.issuer}/.well-known/openid-configuration")
        if str(document.get("issuer", "")).rstrip("/") != self.issuer:
            raise OidcError("unavailable")
        for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            try:
                _valid_url(str(document.get(name, "")), name)
            except OidcConfigError:
                raise OidcError("unavailable") from None
        self._discovery, self._discovered_at = document, time.time()
        return document

    async def authorization_url(self, state: str) -> str:
        # Check the provider is up, so an outage gets our message rather than a browser error page.
        document = await self.discovery(max_age=LOGIN_CHECK_SECONDS)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(self._derive("pkce", state).encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        return (
            document["authorization_endpoint"]
            + "?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": self.client_id,
                    "redirect_uri": self.redirect_uri,
                    "scope": self.scopes,
                    "state": state,
                    "nonce": self._derive("nonce", state),
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

    async def logout_url(self) -> str | None:
        endpoint = (await self.discovery()).get("end_session_endpoint")
        if not endpoint:
            return None
        return f"{endpoint}?" + urlencode(
            {"client_id": self.client_id, "post_logout_redirect_uri": f"{self.public_url}/admin"}
        )

    async def _exchange(self, code: str, state: str) -> dict[str, Any]:
        document = await self.discovery()
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": self._derive("pkce", state),
        }
        methods = document.get("token_endpoint_auth_methods_supported", ["client_secret_basic"])
        auth = None
        if "client_secret_basic" in methods:
            auth = (self.client_id, self.client_secret)
        else:
            form |= {"client_id": self.client_id, "client_secret": self.client_secret}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(document["token_endpoint"], data=form, auth=auth)
            response.raise_for_status()
            tokens = response.json()
        except httpx.TransportError:
            raise OidcError("unavailable") from None
        except (httpx.HTTPError, ValueError):
            raise OidcError("failed") from None
        if not isinstance(tokens, dict) or not isinstance(tokens.get("id_token"), str):
            raise OidcError("failed")
        return tokens

    async def _signing_key(self, token: str) -> Any:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.InvalidTokenError:
            raise OidcError("failed") from None
        for attempt in range(2):
            age = time.time() - self._jwks_at
            # A new kid can mean rotation, so refetch, but not on every forged token.
            if (
                self._jwks is None
                or age >= CACHE_SECONDS
                or (attempt and age >= JWKS_REFRESH_SECONDS)
            ):
                self._jwks = await self._get_json((await self.discovery())["jwks_uri"])
                self._jwks_at = time.time()
            keys = [
                item
                for item in self._jwks.get("keys", [])
                if isinstance(item, dict)
                and item.get("use", "sig") == "sig"
                and (kid is None or item.get("kid") == kid)
            ]
            if len(keys) == 1:
                try:
                    return jwt.PyJWK(keys[0]).key
                except jwt.PyJWTError:
                    raise OidcError("failed") from None
        raise OidcError("failed")

    async def _verified_id_token(self, token: str, state: str) -> dict[str, Any]:
        key = await self._signing_key(token)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=SIGNING_ALGORITHMS,
                audience=self.client_id,
                issuer=self.issuer,
                leeway=30,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.InvalidTokenError:
            raise OidcError("failed") from None
        if not secrets.compare_digest(
            str(claims.get("nonce", "")).encode(), self._derive("nonce", state).encode()
        ):
            raise OidcError("failed")
        if "azp" in claims and claims["azp"] != self.client_id:
            raise OidcError("failed")
        return claims

    async def _access_token_claims(self, token: Any) -> dict[str, Any]:
        """Keycloak puts client roles here by default. An opaque token simply holds no roles."""
        if not isinstance(token, str):
            return {}
        try:
            key = await self._signing_key(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=SIGNING_ALGORITHMS,
                issuer=self.issuer,
                leeway=30,
                options={"require": ["exp", "iss"], "verify_aud": False},
            )
        except (OidcError, jwt.InvalidTokenError):
            return {}
        return claims if claims.get("azp") == self.client_id else {}

    def _roles_in(self, claims: dict[str, Any]) -> list[str] | None:
        value: Any = claims
        for part in self.role_claim:
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        if isinstance(value, str):
            return [value]
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return value
        return None

    def role_from(self, roles: list[str] | None) -> Role | None:
        """No recognised role means no access. There is no default role."""
        if not roles:
            return None
        if self.admin_role in roles:
            return "admin"
        return "readonly" if self.readonly_role in roles else None

    async def complete(self, code: str, state: str) -> tuple[str, str, Role | None]:
        """Exchange the code. Returns the actor name, stable subject and role, if any."""
        tokens = await self._exchange(code, state)
        identity = await self._verified_id_token(tokens["id_token"], state)
        roles = self._roles_in(identity)
        if roles is None:
            roles = self._roles_in(await self._access_token_claims(tokens.get("access_token")))
        name = identity.get("preferred_username") or identity.get("email") or identity["sub"]
        actor = re.sub(r"[\x00-\x1f\x7f]", "", str(name))[:128] or str(identity["sub"])[:128]
        return actor, str(identity["sub"])[:255], self.role_from(roles)


def _client(request: Request) -> OidcClient:
    store_of(request)
    client = getattr(request.app.state, "oidc", None)
    if client is None:
        raise GatewayError(404, "not_found", "Requested operation is unavailable")
    return client


def _back_to_console(error: str | None = None) -> RedirectResponse:
    target = "/admin" if error is None else f"/admin?{urlencode({'sign_in_error': error})}"
    response = RedirectResponse(target, status_code=302)
    response.delete_cookie(STATE_COOKIE, path="/admin/auth", httponly=True, samesite="lax")
    return response


@router.get("/admin/api/sign-in-options")
async def sign_in_options(request: Request):
    """Public: the login page must know whether to offer SSO before anyone has signed in."""
    store_of(request)
    return {"sso": getattr(request.app.state, "oidc", None) is not None}


@router.get("/admin/auth/login", include_in_schema=False)
async def login(request: Request):
    client = _client(request)
    state = client.new_state()
    try:
        target = await client.authorization_url(state)
    except OidcError as exc:
        return _back_to_console(exc.code)
    response = RedirectResponse(target, status_code=302)
    # Lax, because the provider sends the browser back from another site.
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=STATE_SECONDS,
        path="/admin/auth",
        httponly=True,
        samesite="lax",
        secure=secure_cookie(request),
    )
    return response


@router.get(CALLBACK_PATH, include_in_schema=False)
async def callback(request: Request):
    client = _client(request)
    store = store_of(request)
    state = request.query_params.get("state", "")
    cookie = request.cookies.get(STATE_COOKIE, "")
    if (
        not cookie
        or not secrets.compare_digest(state.encode(), cookie.encode())
        or not client.valid_state(state)
    ):
        return _back_to_console("expired")
    code = request.query_params.get("code", "")
    if not code or len(code) > 4096 or "error" in request.query_params:
        return _back_to_console("failed")
    try:
        actor, subject, role = await client.complete(code, state)
    except OidcError as exc:
        return _back_to_console(exc.code)
    if role is None:
        current_principal.set(
            Principal(actor=actor, role="readonly", method="sso", subject=subject)
        )
        store.record_access_event("console.sign_in_denied")
        return _back_to_console("no_role")
    principal = Principal(actor=actor, role=role, method="sso", subject=subject)
    current_principal.set(principal)
    store.record_access_event("console.signed_in")
    response = _back_to_console()
    # Strict still works here: the console page loads first, then calls the API from itself.
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(client.signing_key, principal, client.session_seconds),
        max_age=client.session_seconds,
        path="/admin",
        httponly=True,
        samesite="strict",
        secure=secure_cookie(request),
    )
    return response


@router.get("/admin/auth/logout", include_in_schema=False)
async def logout(request: Request):
    """Ends the provider's session too. The console has already cleared its own cookie."""
    client = _client(request)
    try:
        target = await client.logout_url()
    except OidcError:
        target = None
    return RedirectResponse(target or "/admin", status_code=302)
