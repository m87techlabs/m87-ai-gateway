from fastapi import Header, HTTPException

# MVP static config. Replace with YAML-backed config loader in v0.1 implementation.
DEMO_KEYS = {
    "demo-app-key": {
        "app_id": "demo-app",
        "allowed_models": ["auto", "openai:gpt-4.1-mini", "ollama:llama3"],
    }
}


async def authenticate_app(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    app_context = DEMO_KEYS.get(token)
    if not app_context:
        raise HTTPException(status_code=403, detail="Invalid API key")

    return app_context
