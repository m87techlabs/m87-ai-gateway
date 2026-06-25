from functools import lru_cache
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "M87 AI Gateway"
    environment: str = "local"
    log_level: str = "INFO"


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8080


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    app_id: str
    api_key: str = Field(validation_alias=AliasChoices("api_key", "key"))
    allowed_models: list[str] = Field(default_factory=list)
    rate_limit_per_minute: int | None = None
    monthly_budget_usd: float | None = None


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_keys: list[AppConfig] = Field(default_factory=list)


class RoutingRuleConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    when_model: str | None = None
    when_task: str | None = None
    route_to: str | None = None
    model: str | None = None


class RoutingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_model: str = Field(default="ollama:llama3", validation_alias=AliasChoices("default_model", "default"))
    rules: list[RoutingRuleConfig] = Field(default_factory=list)


class BlocklistConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    blocked_terms: list[str] = Field(default_factory=list)


class GuardrailsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    blocklist: BlocklistConfig = Field(default_factory=BlocklistConfig)


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    api_key_env: str | None = None
    base_url: str | None = None
    base_url_env: str | None = None


class ProvidersConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    openai: ProviderConfig = Field(default_factory=lambda: ProviderConfig(api_key_env="OPENAI_API_KEY"))
    ollama: ProviderConfig = Field(default_factory=lambda: ProviderConfig(base_url_env="OLLAMA_BASE_URL"))


class ObservabilityConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    json_logs: bool = True
    prometheus_metrics: bool = True


class GatewaySettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    apps: list[AppConfig] = Field(default_factory=list)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    @field_validator("apps", mode="before")
    @classmethod
    def _coerce_apps(cls, value: Any) -> Any:
        return value or []

    @property
    def configured_apps(self) -> list[AppConfig]:
        return [*self.apps, *self.auth.api_keys]

    def app_for_api_key(self, api_key: str) -> AppConfig | None:
        for app in self.configured_apps:
            if app.api_key == api_key:
                return app
        return None


def load_settings(config_path: str | Path | None = None) -> GatewaySettings:
    data = _load_yaml_config(config_path)
    _apply_environment_overrides(data, os.environ)
    return GatewaySettings.model_validate(data)


@lru_cache
def get_settings() -> GatewaySettings:
    return load_settings()


def _load_yaml_config(config_path: str | Path | None) -> dict[str, Any]:
    path = Path(config_path) if config_path else _find_default_config_path()
    if path is None or not path.exists():
        return {}

    with path.open() as config_file:
        loaded = yaml.safe_load(config_file) or {}

    if not isinstance(loaded, dict):
        raise ValueError(f"Gateway config must be a YAML mapping: {path}")

    return loaded


def _find_default_config_path() -> Path | None:
    env_path = os.getenv("M87_GATEWAY_CONFIG") or os.getenv("GATEWAY_CONFIG")
    if env_path:
        return Path(env_path)

    for candidate in (Path.cwd() / "config.yaml", Path.cwd() / "config.example.yaml"):
        if candidate.exists():
            return candidate

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config.example.yaml"
        if candidate.exists():
            return candidate

    return None


def _apply_environment_overrides(data: dict[str, Any], environ: os._Environ[str]) -> None:
    _set_if_present(data, ("gateway", "name"), environ.get("GATEWAY_NAME"))
    _set_if_present(data, ("gateway", "environment"), environ.get("GATEWAY_ENVIRONMENT"))
    _set_if_present(data, ("gateway", "log_level"), environ.get("GATEWAY_LOG_LEVEL"))
    _set_if_present(data, ("server", "host"), environ.get("SERVER_HOST"))
    _set_if_present(data, ("server", "port"), _int_or_none(environ.get("SERVER_PORT")))
    _set_if_present(data, ("routing", "default_model"), environ.get("GATEWAY_DEFAULT_MODEL"))

    app_api_key = environ.get("GATEWAY_APP_API_KEY") or environ.get("M87_GATEWAY_APP_API_KEY")
    app_id = environ.get("GATEWAY_APP_ID") or environ.get("M87_GATEWAY_APP_ID")
    allowed_models = _csv(environ.get("GATEWAY_ALLOWED_MODELS"))
    if app_api_key or app_id or allowed_models:
        auth = data.setdefault("auth", {})
        api_keys = auth.setdefault("api_keys", [])
        if not api_keys:
            api_keys.append({})
        if app_api_key:
            api_keys[0]["key"] = app_api_key
        if app_id:
            api_keys[0]["app_id"] = app_id
        if allowed_models:
            api_keys[0]["allowed_models"] = allowed_models


def _set_if_present(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    if value is None:
        return

    current = data
    for segment in path[:-1]:
        current = current.setdefault(segment, {})
    current[path[-1]] = value


def _int_or_none(value: str | None) -> int | None:
    return int(value) if value else None


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]
