from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST
from starlette.exceptions import HTTPException

from m87_gateway.api.errors import GatewayError, error_response
from m87_gateway.api.routes import router
from m87_gateway.config import GatewaySettings, get_settings
from m87_gateway.logging.audit import AuditRecorder
from m87_gateway.logging.middleware import TrafficMiddleware
from m87_gateway.metrics import GatewayMetrics


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            active = settings if settings is not None else get_settings()
            application.state.settings = active
            application.state.metrics = GatewayMetrics()
            application.state.recorder = AuditRecorder(active, application.state.metrics)
        except Exception:
            raise RuntimeError(
                "Gateway configuration or traffic log initialization failed"
            ) from None
        application.dependency_overrides[get_settings] = lambda: active
        try:
            yield
        finally:
            application.state.recorder.close()

    application = FastAPI(
        title="M87 AI Gateway",
        description="A lightweight, self-hostable AI gateway.",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(TrafficMiddleware)
    application.include_router(router)

    @application.exception_handler(GatewayError)
    async def gateway_error(request: Request, exc: GatewayError):
        return error_response(request, exc)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return error_response(
            request,
            GatewayError(
                422,
                "invalid_request",
                "Request does not match the supported chat API",
                "invalid_request_error",
            ),
        )

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(
            request,
            GatewayError(
                exc.status_code,
                "http_error",
                "Requested operation is unavailable",
            ),
        )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "m87-ai-gateway"}

    @application.get("/metrics", include_in_schema=False)
    def metrics(request: Request):
        if not request.app.state.settings.observability.prometheus_metrics:
            raise GatewayError(404, "not_found", "Requested operation is unavailable")
        return Response(
            content=request.app.state.metrics.render(),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )

    return application


app = create_app()
