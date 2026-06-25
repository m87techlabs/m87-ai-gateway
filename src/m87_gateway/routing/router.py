def select_model(requested_model: str, app_context: dict) -> str:
    allowed_models = app_context.get("allowed_models", [])
    if requested_model not in allowed_models:
        raise ValueError(f"Model is not allowed for app: {requested_model}")

    if requested_model == "auto":
        return "ollama:llama3"

    return requested_model
