from fastapi import Request
from fastapi.responses import JSONResponse


class GatewayError(Exception):
    """A client-safe error. Never put upstream bodies or credentials in its fields."""

    def __init__(self, status: int, code: str, message: str, kind: str = "gateway_error"):
        self.status = status
        self.code = code
        self.message = message
        self.kind = kind


def error_response(request: Request, error: GatewayError) -> JSONResponse:
    request.state.audit["error_type"] = error.code
    return JSONResponse(
        status_code=error.status,
        content={
            "error": {"message": error.message, "type": error.kind, "code": error.code},
            "request_id": request.state.request_id,
        },
    )
