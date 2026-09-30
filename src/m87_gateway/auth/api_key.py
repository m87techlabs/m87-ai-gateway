from fastapi import Depends, Header, Request

from m87_gateway.api.errors import GatewayError
from m87_gateway.config import AppConfig, GatewaySettings, get_settings


async def authenticate_app(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: GatewaySettings = Depends(get_settings),
) -> AppConfig:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise GatewayError(
            401, "invalid_api_key", "Missing or invalid API key", "authentication_error"
        )
    app_context = settings.app_for_api_key(token.strip())
    if app_context is None:
        raise GatewayError(
            401, "invalid_api_key", "Missing or invalid API key", "authentication_error"
        )
    request.state.audit["app_id"] = app_context.app_id
    return app_context
