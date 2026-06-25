from m87_gateway.config import AppConfig, GatewaySettings


class ModelNotAllowedError(ValueError):
    pass


def select_model(requested_model: str, app_context: AppConfig, settings: GatewaySettings) -> str:
    allowed_models = app_context.allowed_models
    if requested_model not in allowed_models:
        raise ModelNotAllowedError(f"Model is not allowed for app: {requested_model}")

    if requested_model == "auto":
        return settings.routing.default_model

    return requested_model
