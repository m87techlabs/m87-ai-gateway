import os
import re
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_PROVIDERS = {"openai", "ollama"}


def validate_model(value: str, allow_auto: bool = True) -> str:
    if allow_auto and value == "auto":
        return value
    provider, separator, model = value.partition(":")
    if (
        not separator
        or provider not in SUPPORTED_PROVIDERS
        or not model
        or len(value) > 200
        or any(character.isspace() for character in value)
    ):
        raise ValueError("Use a supported provider:model identifier")
    return value


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GatewayConfig(ConfigModel):
    name: str = "M87 AI Gateway"
    environment: str = "local"
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def valid_level(cls, value: str) -> str:
        if value.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Unsupported log level")
        return value.upper()


class ServerConfig(ConfigModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)


class AppConfig(ConfigModel):
    app_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    api_key: str = Field(min_length=1, repr=False, validation_alias=AliasChoices("api_key", "key"))
    allowed_models: list[str] = Field(default_factory=list)
    capture_content: bool = False
    rate_limit_per_minute: int | None = Field(default=None, ge=1)
    monthly_budget_usd: float | None = Field(default=None, ge=0)

    @field_validator("allowed_models")
    @classmethod
    def valid_models(cls, values: list[str]) -> list[str]:
        return [validate_model(value) for value in values]

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("App keys must not contain whitespace")
        return value


class AuthConfig(ConfigModel):
    api_keys: list[AppConfig] = Field(default_factory=list)


class RoutingRuleConfig(ConfigModel):
    name: str | None = None
    when_model: str | None = None
    when_task: str | None = Field(default=None, min_length=1)
    route_to: str = Field(validation_alias=AliasChoices("route_to", "model"))

    @model_validator(mode="after")
    def valid_rule(self):
        validate_model(self.route_to, allow_auto=False)
        if self.when_model not in {None, "auto"}:
            raise ValueError("Routing rules apply only to auto requests")
        if self.when_model is None and self.when_task is None:
            raise ValueError("A routing rule needs a selector")
        return self


class RoutingConfig(ConfigModel):
    default_model: str = Field(
        default="ollama:llama3", validation_alias=AliasChoices("default_model", "default")
    )
    rules: list[RoutingRuleConfig] = Field(default_factory=list)

    @field_validator("default_model")
    @classmethod
    def valid_default(cls, value: str) -> str:
        return validate_model(value, allow_auto=False)


class BlocklistConfig(ConfigModel):
    enabled: bool = True
    blocked_terms: list[str] = Field(default_factory=list)

    @field_validator("blocked_terms")
    @classmethod
    def valid_terms(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Blocklist terms must not be empty")
        return values


class GuardrailsConfig(ConfigModel):
    blocklist: BlocklistConfig = Field(default_factory=BlocklistConfig)
    max_message_chars: int = Field(default=65536, ge=1, le=1048576)
    max_request_bytes: int = Field(default=262144, ge=1, le=10485760)


class ProviderConfig(ConfigModel):
    enabled: bool = True
    api_key_env: str | None = None
    base_url: str | None = None
    base_url_env: str | None = None
    timeout_seconds: float = Field(default=60, gt=0, le=600)

    @field_validator("api_key_env", "base_url_env")
    @classmethod
    def valid_env_name(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("Invalid environment variable name")
        return value

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        _ = parsed.port  # Reject malformed port numbers during configuration validation.
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or any(character.isspace() for character in value)
        ):
            raise ValueError("Provider URL must be HTTP(S), without credentials, query or fragment")
        return value.rstrip("/")


class ProvidersConfig(ConfigModel):
    openai: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key_env="OPENAI_API_KEY", base_url="https://api.openai.com/v1"
        )
    )
    ollama: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            base_url="http://localhost:11434", base_url_env="OLLAMA_BASE_URL"
        )
    )


class TrafficLogConfig(ConfigModel):
    path: str | None = Field(default=None, min_length=1)
    capture_content: bool = False
    max_content_chars: int = Field(default=16384, ge=1, le=65536)
    max_bytes: int = Field(default=10485760, ge=1048576)
    backup_count: int = Field(default=3, ge=1, le=20)


class ObservabilityConfig(ConfigModel):
    json_logs: bool = True
    prometheus_metrics: bool = True
    traffic_log: TrafficLogConfig = Field(default_factory=TrafficLogConfig)


class ControlPlaneConfig(ConfigModel):
    enabled: bool = False
    database_path: str = Field(default="var/lib/m87-gateway/control.db", min_length=1)
    master_key_path: str = Field(default="var/lib/m87-gateway/master.key", min_length=1)
    admin_api_key_env: str = "GATEWAY_ADMIN_API_KEY"
    retention_days: int = Field(default=30, ge=1, le=3650)

    @field_validator("admin_api_key_env")
    @classmethod
    def valid_admin_env(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("Invalid admin key environment variable name")
        return value

    @field_validator("database_path", "master_key_path")
    @classmethod
    def valid_local_path(cls, value: str) -> str:
        if "\x00" in value or not value.strip():
            raise ValueError("Control-plane paths must be non-empty local paths")
        return value


class GatewaySettings(ConfigModel):
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    apps: list[AppConfig] = Field(default_factory=list)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    control_plane: ControlPlaneConfig = Field(default_factory=ControlPlaneConfig)

    @field_validator("apps", mode="before")
    @classmethod
    def _coerce_apps(cls, value: Any) -> Any:
        return value or []

    @model_validator(mode="after")
    def unique_apps(self):
        apps = self.configured_apps
        if len({app.app_id for app in apps}) != len(apps):
            raise ValueError("App identifiers must be unique")
        if len({app.api_key for app in apps}) != len(apps):
            raise ValueError("App keys must be unique")
        traffic = self.observability.traffic_log
        if traffic.capture_content and not traffic.path and not self.control_plane.enabled:
            raise ValueError("Content capture requires the local database or traffic log path")
        return self

    @property
    def configured_apps(self) -> list[AppConfig]:
        return [*self.apps, *self.auth.api_keys]

    def app_for_api_key(self, api_key: str) -> AppConfig | None:
        for app in self.configured_apps:
            if secrets.compare_digest(app.api_key.encode(), api_key.encode()):
                return app
        return None


def load_settings(config_path: str | Path | None = None) -> GatewaySettings:
    data = _load_yaml_config(config_path)
    _apply_environment_overrides(data, os.environ)
    # Resolve endpoints once, at startup, so malformed environment overrides fail closed.
    for name, default_url in (
        ("openai", "https://api.openai.com/v1"),
        ("ollama", "http://localhost:11434"),
    ):
        providers = data.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise ValueError("Providers configuration must be a mapping")
        provider = providers.setdefault(name, {})
        if not isinstance(provider, dict):
            raise ValueError("Provider configuration must be a mapping")
        env_name = provider.get("base_url_env", "OLLAMA_BASE_URL" if name == "ollama" else None)
        if env_name is not None and not isinstance(env_name, str):
            raise ValueError("Provider environment names must be strings")
        if env_name and env_name in os.environ:
            provider["base_url"] = os.environ[env_name]
        provider.setdefault("base_url", default_url)
        if name == "openai":
            provider.setdefault("api_key_env", "OPENAI_API_KEY")
    return GatewaySettings.model_validate(data)


@lru_cache
def get_settings() -> GatewaySettings:
    return load_settings()


def _load_yaml_config(config_path: str | Path | None) -> dict[str, Any]:
    path = Path(config_path) if config_path is not None else _find_default_config_path()
    if path is None:
        return {}
    if not path.is_file():
        raise ValueError("Selected gateway configuration file does not exist")
    with path.open() as config_file:
        loaded = yaml.safe_load(config_file)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("Gateway config must be a YAML mapping")
    return loaded


def _find_default_config_path() -> Path | None:
    env_path = os.getenv("M87_GATEWAY_CONFIG") or os.getenv("GATEWAY_CONFIG")
    if env_path:
        return Path(env_path)
    for candidate in (Path.cwd() / "config.yaml", Path.cwd() / "config.example.yaml"):
        if candidate.exists():
            return candidate
    return None


def _apply_environment_overrides(data: dict[str, Any], environ: os._Environ[str]) -> None:
    for variable, path in {
        "GATEWAY_NAME": ("gateway", "name"),
        "GATEWAY_ENVIRONMENT": ("gateway", "environment"),
        "GATEWAY_LOG_LEVEL": ("gateway", "log_level"),
        "SERVER_HOST": ("server", "host"),
        "SERVER_PORT": ("server", "port"),
        "GATEWAY_DEFAULT_MODEL": ("routing", "default_model"),
        "GATEWAY_CONTROL_PLANE_DATABASE_PATH": ("control_plane", "database_path"),
        "GATEWAY_CONTROL_PLANE_MASTER_KEY_PATH": ("control_plane", "master_key_path"),
        "GATEWAY_CONTROL_PLANE_RETENTION_DAYS": ("control_plane", "retention_days"),
    }.items():
        _set_if_present(data, path, environ.get(variable))

    app_key = environ.get("GATEWAY_APP_API_KEY") or environ.get("M87_GATEWAY_APP_API_KEY")
    app_id = environ.get("GATEWAY_APP_ID") or environ.get("M87_GATEWAY_APP_ID")
    allowed = environ.get("GATEWAY_ALLOWED_MODELS")
    capture_content = environ.get("GATEWAY_APP_CAPTURE_CONTENT")
    if any(value is not None for value in (app_key, app_id, allowed, capture_content)):
        apps = data.get("apps")
        if apps:
            if not isinstance(apps, list):
                raise ValueError("Apps configuration must be a list")
        else:
            auth = data.setdefault("auth", {})
            if not isinstance(auth, dict):
                raise ValueError("Auth configuration must be a mapping")
            apps = auth.setdefault("api_keys", [])
            if not isinstance(apps, list):
                raise ValueError("Auth API keys configuration must be a list")
        if not apps:
            apps.append({"app_id": "default-app"})
        first = apps[0]
        if not isinstance(first, dict):
            raise ValueError("App configuration must be a mapping")
        if app_key is not None:
            first.pop("key", None)
            first["api_key"] = app_key
        if app_id is not None:
            first["app_id"] = app_id
        if allowed is not None:
            first["allowed_models"] = [
                value.strip() for value in allowed.split(",") if value.strip()
            ]
        if capture_content is not None:
            first["capture_content"] = _parse_bool("GATEWAY_APP_CAPTURE_CONTENT", capture_content)

    for variable, path in {
        "GATEWAY_CONTROL_PLANE_ENABLED": ("control_plane", "enabled"),
        "GATEWAY_CAPTURE_CONTENT": ("observability", "traffic_log", "capture_content"),
    }.items():
        if variable in environ:
            _set_if_present(data, path, _parse_bool(variable, environ[variable]))


def _parse_bool(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _set_if_present(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    if value is None:
        return
    current = data
    for segment in path[:-1]:
        current = current.setdefault(segment, {})
        if not isinstance(current, dict):
            raise ValueError("Configuration sections must be mappings")
    if path == ("routing", "default_model"):
        current.pop("default", None)
    current[path[-1]] = value
