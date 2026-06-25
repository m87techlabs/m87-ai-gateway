from fastapi import Depends, Header, HTTPException

from m87_gateway.config import AppConfig, GatewaySettings, get_settings


async def authenticate_app(
    authorization: str | None = Header(default=None),
    settings: GatewaySettings = Depends(get_settings),
) -> AppConfig:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    app_context = settings.app_for_api_key(token)
    if not app_context:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return app_context
