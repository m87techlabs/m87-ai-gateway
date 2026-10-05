"""Compatibility API for backends composed from repository contracts."""

from typing import Any

from .repositories.contracts import (
    ConfigurationRepository,
    IdentityRepository,
    ManagementAuditRepository,
    SecretStore,
    TrafficRepository,
    UsageRepository,
)

from m87_gateway.config import AppConfig


class BackendFacade:
    """Delegate the existing control API to explicitly composed repositories."""

    configuration: ConfigurationRepository
    identities: IdentityRepository
    secrets: SecretStore
    traffic: TrafficRepository
    management_audit: ManagementAuditRepository
    usage_repository: UsageRepository

    def runtime_config(self) -> dict:
        return self.configuration.runtime_config()

    def save_runtime_config(self, value: dict, provider=None, key=None, clear_key=False):
        return self.configuration.save_runtime_config(value, provider, key, clear_key)

    def emit(self, event: dict[str, Any]) -> None:
        return self.traffic.emit(event)

    def update_app_limits(self, app_id, rate_limit_per_minute, max_concurrent_requests):
        return self.identities.update_app_limits(
            app_id, rate_limit_per_minute, max_concurrent_requests
        )

    def delete_events(self, project_id=None) -> int:
        return self.traffic.delete_events(project_id)

    def prune_events(self) -> int:
        return self.traffic.prune_events()

    def overview(self, hours: int = 24, project_id: str | None = None) -> dict[str, Any]:
        return self.usage_repository.overview(hours, project_id)

    def list_events(
        self,
        *,
        limit: int = 100,
        app_id: str | None = None,
        status: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.traffic.list_events(
            limit=limit, app_id=app_id, status=status, project_id=project_id
        )

    def get_event(self, request_id: str) -> dict[str, Any] | None:
        return self.traffic.get_event(request_id)

    def export_events(
        self, limit: int = 1000, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        return self.traffic.export_events(limit, project_id)

    def create_app_key(
        self,
        app_id: str,
        allowed_models: list[str],
        capture_content: bool,
        rate_limit_per_minute: int | None = None,
        project_id: str = "default",
        max_concurrent_requests: int | None = None,
    ) -> tuple[dict[str, Any], str]:
        return self.identities.create_app_key(
            app_id,
            allowed_models,
            capture_content,
            rate_limit_per_minute,
            project_id,
            max_concurrent_requests,
        )

    def authenticate_app_key(self, raw_key: str) -> AppConfig | None:
        return self.identities.authenticate_app_key(raw_key)

    def list_apps(self) -> list[dict[str, Any]]:
        return self.identities.list_apps()

    def ensure_projects(self, identifiers: list[str]) -> None:
        return self.identities.ensure_projects(identifiers)

    def create_project(self, project_id: str, name: str) -> dict:
        return self.identities.create_project(project_id, name)

    def list_projects(self) -> list[dict]:
        return self.identities.list_projects()

    def assign_app_project(self, app_id: str, project_id: str) -> bool:
        return self.identities.assign_app_project(app_id, project_id)

    def usage(self, hours: int = 24, project_id: str | None = None) -> dict:
        return self.usage_repository.usage(hours, project_id)

    def delete_app(self, app_id: str) -> bool:
        return self.identities.delete_app(app_id)

    def update_app_models(self, app_id: str, allowed_models: list[str]) -> bool:
        return self.identities.update_app_models(app_id, allowed_models)

    def put_provider_key(self, provider: str, value: str, alias: str = "default") -> None:
        return self.secrets.put_provider_key(provider, value, alias)

    def get_provider_key(self, provider: str, alias: str = "default") -> str | None:
        return self.secrets.get_provider_key(provider, alias)

    def provider_secret_values(self) -> list[str]:
        # Compatibility hook for local redaction; remote adapters need not enumerate secrets.
        values = getattr(self.secrets, "provider_secret_values", None)
        return values() if callable(values) else []

    def list_provider_keys(self) -> list[dict[str, Any]]:
        return self.secrets.list_provider_keys()

    def delete_provider_key(self, provider: str, alias: str = "default") -> bool:
        return self.secrets.delete_provider_key(provider, alias)

    def issue_app_key(
        self, app_id: str, expires_in_days: int | None = None, revoke_existing: bool = False
    ):
        return self.identities.issue_app_key(app_id, expires_in_days, revoke_existing)

    def list_app_keys(self, app_id: str):
        return self.identities.list_app_keys(app_id)

    def revoke_app_key(self, app_id: str, key_id: str) -> bool:
        return self.identities.revoke_app_key(app_id, key_id)

    def list_management_events(self, limit: int = 100, project_id: str | None = None):
        return self.management_audit.list_management_events(limit, project_id)
