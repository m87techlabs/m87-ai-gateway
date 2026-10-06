import asyncio
import hashlib

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError

from m87_gateway.adapters import adapters
from m87_gateway.api.streaming import ChatStreamResponse
from m87_gateway.api.errors import GatewayError
from m87_gateway.api.schemas import ChatCompletionRequest, ChatCompletionResponse
from m87_gateway.auth.api_key import authenticate_app
from m87_gateway.config import AppConfig, GatewaySettings, get_settings
from m87_gateway.guardrails.blocklist import check_blocklist
from m87_gateway.providers.factory import get_provider
from m87_gateway.routing.router import ModelNotAllowedError, select_model

router = APIRouter()


@router.get("/v1/models")
async def models(
    request: Request,
    response: Response,
    app_context: AppConfig = Depends(authenticate_app),
    settings: GatewaySettings = Depends(get_settings),
):
    registrations = adapters()
    approved = set(app_context.allowed_models)
    known = set(approved)
    for name, adapter in registrations.items():
        config = settings.providers.for_adapter(name)
        known.update(
            request.app.state.model_catalog.models(
                name, config.base_url or adapter.default_url or ""
            )
        )
    permitted = []
    for model in sorted(known & approved):
        provider = model.partition(":")[0]
        if model != "auto" and not settings.providers.for_adapter(provider).enabled:
            continue
        permitted.append(
            {
                "id": model,
                "object": "model",
                "created": 0,
                "owned_by": "gateway" if model == "auto" else provider,
            }
        )
    response.headers["Cache-Control"] = "no-store"
    return {"object": "list", "data": permitted}


def validate_capabilities(payload: ChatCompletionRequest, provider_name: str) -> None:
    capability = adapters()[provider_name].capabilities
    if payload.stream and not capability.streaming:
        raise GatewayError(
            422,
            "unsupported_streaming",
            "Selected adapter does not support streaming",
            "invalid_request_error",
        )
    for field in (
        "temperature",
        "max_tokens",
        "top_p",
        "stop",
        "seed",
        "presence_penalty",
        "frequency_penalty",
    ):
        if getattr(payload, field) is not None and field not in capability.generation_parameters:
            raise GatewayError(
                422,
                "unsupported_parameter",
                f"Selected adapter does not support {field}",
                "invalid_request_error",
            )
    if payload.response_format is not None:
        if payload.response_format.type not in capability.response_formats:
            raise GatewayError(
                422,
                "unsupported_parameter",
                "Selected adapter does not support this response format",
                "invalid_request_error",
            )
        if (
            payload.response_format.type == "json_schema"
            and payload.response_format.json_schema.strict is not None
            and not capability.strict_json_schema
        ):
            raise GatewayError(
                422,
                "unsupported_parameter",
                "Selected adapter does not support the JSON schema strict flag",
                "invalid_request_error",
            )


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
    if payload.user is not None:
        audit["client_user_hash"] = hashlib.sha256(payload.user.encode()).hexdigest()
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
    prepared = prepare(payload, request, app_context, settings)
    if payload.stream:
        return ChatStreamResponse(request, payload, app_context, settings, prepared)
    async with request.app.state.inflight_limiter.admit_wait(
        app_context.app_id,
        settings.limits.max_concurrent_requests,
        app_context.max_concurrent_requests,
        settings.limits.queue_max_depth,
        settings.limits.queue_max_depth_per_app,
        settings.limits.queue_wait_timeout_seconds,
        disconnected=request.state.is_disconnected,
        audit=audit,
    ):
        return await complete(payload, request, http_response, app_context, settings, prepared)


def prepare(
    payload: ChatCompletionRequest,
    request: Request,
    app_context: AppConfig,
    settings: GatewaySettings,
):
    """Validate and snapshot the connection and cache before a possible queue wait."""
    audit = request.state.audit
    audit["capture_enabled"] = settings.observability.traffic_log.capture_content
    request.state.capture_limit = settings.observability.traffic_log.max_content_chars
    try:
        selected = select_model(payload.model, app_context, settings, payload.task)
    except ModelNotAllowedError as exc:
        raise GatewayError(
            403, "model_not_allowed", "Model is not allowed for app", "authorization_error"
        ) from exc

    provider_name, model = selected.split(":", 1)
    audit.update(provider=provider_name, routed_model=selected)
    validate_capabilities(payload, provider_name)
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
    provider_key = getattr(provider, "api_key", None)
    if isinstance(provider_key, str) and provider_key:
        request.app.state.recorder.add_secret(provider_key)
    return provider, selected, request.app.state.response_cache


async def complete(
    payload: ChatCompletionRequest,
    request: Request,
    http_response: Response,
    app_context: AppConfig,
    settings: GatewaySettings,
    prepared,
) -> ChatCompletionResponse:
    """Run inference with the arrival snapshot while holding concurrency capacity."""
    provider, selected, cache = prepared
    model = selected.split(":", 1)[1]
    audit = request.state.audit
    capture = settings.observability.traffic_log.capture_content
    cache_key = cache.key(
        app_context.app_id,
        selected,
        payload.model_dump(
            exclude={"model", "task"}, exclude_none=True, mode="json", by_alias=True
        ),
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
