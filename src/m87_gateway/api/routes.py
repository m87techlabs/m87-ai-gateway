from fastapi import APIRouter, Depends, HTTPException, Request

from m87_gateway.auth.api_key import authenticate_app
from m87_gateway.config import AppConfig, GatewaySettings, get_settings
from m87_gateway.guardrails.blocklist import check_blocklist
from m87_gateway.routing.router import ModelNotAllowedError, select_model
from m87_gateway.providers.factory import get_provider
from m87_gateway.logging.audit import audit_log
from m87_gateway.api.schemas import ChatCompletionRequest, ChatCompletionResponse

router = APIRouter()


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    payload: ChatCompletionRequest,
    request: Request,
    app_context: AppConfig = Depends(authenticate_app),
    settings: GatewaySettings = Depends(get_settings),
):
    guardrail_result = check_blocklist(payload.messages)
    if not guardrail_result["allowed"]:
        audit_log(
            event="guardrail_block",
            app_id=app_context.app_id,
            model=payload.model,
            reason=guardrail_result["reason"],
        )
        raise HTTPException(status_code=400, detail=guardrail_result["reason"])

    try:
        selected_model = select_model(payload.model, app_context, settings)
    except ModelNotAllowedError as exc:
        raise HTTPException(status_code=403, detail="Model is not allowed for app") from exc

    provider_name, provider_model = selected_model.split(":", 1)
    provider = get_provider(provider_name)

    audit_log(
        event="request_received",
        app_id=app_context.app_id,
        requested_model=payload.model,
        selected_model=selected_model,
        client_host=request.client.host if request.client else None,
    )

    return await provider.chat_completions(payload, provider_model)
