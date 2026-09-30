from m87_gateway.config import AppConfig, GatewaySettings


class ModelNotAllowedError(ValueError):
    pass


def select_model(
    requested_model: str,
    app_context: AppConfig,
    settings: GatewaySettings,
    task: str | None = None,
) -> str:
    """Authorize both the client alias and the final target; first matching auto rule wins."""
    allowed = app_context.allowed_models
    if requested_model not in allowed:
        raise ModelNotAllowedError("Requested model is not allowed")
    selected = requested_model
    if requested_model == "auto":
        selected = settings.routing.default_model
        for rule in settings.routing.rules:
            if rule.when_task is not None and rule.when_task != task:
                continue
            selected = rule.route_to
            break
    if selected not in allowed:
        raise ModelNotAllowedError("Resolved model is not allowed")
    return selected
