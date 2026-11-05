from m87_gateway.adapters import adapters
from m87_gateway.config import AppConfig, GatewaySettings


# Failures another attempt or another provider could fix. A bad request or key would fail again.
RETRIABLE_PROVIDER_ERRORS = frozenset(
    {"provider_timeout", "provider_rate_limited", "provider_error"}
)


class ModelNotAllowedError(ValueError):
    pass


def canonical_model(requested_model: str, settings: GatewaySettings) -> str:
    """A bare upstream name such as qwen3:14b belongs to the default model's provider."""
    provider, separator, _ = requested_model.partition(":")
    if requested_model == "auto" or (separator and provider in adapters()):
        return requested_model
    return f"{settings.routing.default_model.split(':', 1)[0]}:{requested_model}"


def reported_model(requested_model: str, selected: str, settings: GatewaySettings) -> str:
    """Answer with the name the caller used, unless it asked the gateway to choose."""
    return (
        selected
        if canonical_model(requested_model, settings) in {"auto", requested_model}
        else requested_model
    )


def select_model(
    requested_model: str,
    app_context: AppConfig,
    settings: GatewaySettings,
    task: str | None = None,
) -> str:
    """Authorize both the client alias and the final target; first matching auto rule wins."""
    allowed = app_context.allowed_models
    canonical = canonical_model(requested_model, settings)
    if canonical not in allowed:
        raise ModelNotAllowedError("Requested model is not allowed")
    selected = canonical
    if canonical == "auto":
        selected = settings.routing.default_model
        for rule in settings.routing.rules:
            if rule.when_task is not None and rule.when_task != task:
                continue
            selected = rule.route_to
            break
    if selected not in allowed:
        raise ModelNotAllowedError("Resolved model is not allowed")
    return selected
