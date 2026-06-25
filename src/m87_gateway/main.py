from fastapi import FastAPI

from m87_gateway.api.routes import router

app = FastAPI(
    title="M87 AI Gateway",
    description="Secure, observable, provider-neutral AI gateway for production apps.",
    version="0.1.0",
)

app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "m87-ai-gateway"}
