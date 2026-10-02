import asyncio

from fastapi import APIRouter, Depends, Request, Response
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
    http_response: Response,
    app_context: AppConfig = Depends(authenticate_app),
    settings: GatewaySettings = Depends(get_settings),
):
    audit = request.state.audit
    audit["model"] = payload.model
    retry_after = request.app.state.rate_limiter.check(
        app_context.app_id, app_context.rate_limit_per_minute
    )
    if retry_after is not None:
        raise GatewayError(
            429,
            "rate_limit_exceeded",
            "Application request rate limit exceeded",
            "rate_limit_error",
            headers={"Retry-After": str(retry_after)},
        )
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
    capture = settings.observability.traffic_log.capture_content
    if capture:
        request.state.request_content = [message.model_dump() for message in payload.messages]
    provider = (
        get_provider(provider_name, settings, control_store)
        if control_store is not None
        else get_provider(provider_name, settings)
    )
    cache = request.app.state.response_cache
    cache_key = cache.key(
        app_context.app_id,
        selected,
        payload.model_dump(exclude={"model", "task"}, exclude_none=True, mode="json"),
    )
    cached = cache.get(cache_key)
    if cached is not None:
        audit["cache_status"] = "hit"
        http_response.headers["X-Gateway-Cache"] = "HIT"
        completion = ChatCompletionResponse.model_validate(cached)
        if completion.usage:
            audit.update(completion.usage.model_dump())
        if capture:
            request.state.response_content = [choice.model_dump() for choice in completion.choices]
        return completion

    audit["cache_status"] = "miss" if cache.enabled else "disabled"
    http_response.headers["X-Gateway-Cache"] = "MISS" if cache.enabled else "DISABLED"
    audit["provider_attempted"] = True
    result = None
    retriable = {"provider_timeout", "provider_rate_limited", "provider_error"}
    for attempt in range(settings.retry.max_attempts):
        audit["provider_attempts"] = attempt + 1
        try:
            result = await provider.chat_completions(payload, model)
            break
        except GatewayError as exc:
            if exc.code not in retriable or attempt + 1 >= settings.retry.max_attempts:
                raise
            audit["provider_retries"] += 1
            delay = settings.retry.backoff_ms * (2**attempt) / 1000
            if delay:
                await asyncio.sleep(delay)
    if result is None:
        raise GatewayError(502, "provider_error", "Model provider could not complete the request")
    try:
        completion = ChatCompletionResponse.model_validate(result)
    except ValidationError as exc:
        raise GatewayError(
            502, "invalid_provider_response", "Model provider returned an invalid response"
        ) from exc
    if completion.usage:
        audit.update(completion.usage.model_dump())
    if capture:
        request.state.response_content = [choice.model_dump() for choice in completion.choices]
    cache.put(cache_key, completion.model_dump(mode="json"))
    return completion
