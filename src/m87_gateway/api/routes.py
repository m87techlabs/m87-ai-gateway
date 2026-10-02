from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from m87_gateway.api.errors import GatewayError
from m87_gateway.api.schemas import ChatCompletionRequest, ChatCompletionResponse
from m87_gateway.auth.api_key import authenticate_app
from m87_gateway.config import AppConfig, GatewaySettings, get_settings
from m87_gateway.guardrails.blocklist import check_blocklist
from m87_gateway.providers.factory import get_provider
from m87_gateway.routing.router import ModelNotAllowedError, select_model

router = APIRouter()


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    payload: ChatCompletionRequest,
    request: Request,
    app_context: AppConfig = Depends(authenticate_app),
    settings: GatewaySettings = Depends(get_settings),
):
    audit = request.state.audit
    audit["model"] = payload.model
    try:
        selected = select_model(payload.model, app_context, settings, payload.task)
    except ModelNotAllowedError as exc:
        raise GatewayError(
            403, "model_not_allowed", "Model is not allowed for app", "authorization_error"
        ) from exc

    provider_name, model = selected.split(":", 1)
    audit.update(provider=provider_name, routed_model=selected)
    guardrail = check_blocklist(payload.messages, settings.guardrails)
    audit.update(
        guardrail_action="allow" if guardrail["allowed"] else "block",
        guardrail_reason=guardrail["reason"],
    )
    if not guardrail["allowed"]:
        raise GatewayError(
            400, guardrail["reason"], "Request blocked by gateway policy", "policy_error"
        )

    control_store = getattr(request.app.state, "control_store", None)
    provider = (
        get_provider(provider_name, settings, control_store)
        if control_store is not None
        else get_provider(provider_name, settings)
    )
    capture = settings.observability.traffic_log.capture_content and app_context.capture_content
    if capture:
        request.state.request_content = [message.model_dump() for message in payload.messages]
    audit["provider_attempted"] = True
    result = await provider.chat_completions(payload, model)
    try:
        response = ChatCompletionResponse.model_validate(result)
    except ValidationError as exc:
        raise GatewayError(
            502, "invalid_provider_response", "Model provider returned an invalid response"
        ) from exc
    if response.usage:
        audit.update(response.usage.model_dump())
    if capture:
        request.state.response_content = [choice.model_dump() for choice in response.choices]
    return response
