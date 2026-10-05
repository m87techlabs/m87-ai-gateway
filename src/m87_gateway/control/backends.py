"""Explicit backend registration. Configuration never imports arbitrary modules."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from m87_gateway.config import ControlPlaneConfig
from .repositories.contracts import (
    ConfigurationRepository,
    IdentityRepository,
    ManagementAuditRepository,
    SecretStore,
    TrafficRepository,
    UsageRepository,
)


@runtime_checkable
class Backend(
    ConfigurationRepository,
    IdentityRepository,
    SecretStore,
    TrafficRepository,
    UsageRepository,
    ManagementAuditRepository,
    Protocol,
):
    config: ControlPlaneConfig
    configuration: ConfigurationRepository
    identities: IdentityRepository
    secrets: SecretStore
    traffic: TrafficRepository
    management_audit: ManagementAuditRepository
    usage_repository: UsageRepository

    def check_storage(self) -> None: ...
    def close(self) -> None: ...


_FACTORIES: dict[str, Callable[[ControlPlaneConfig], Backend]] = {}


def register_backend(name: str, factory: Callable[[ControlPlaneConfig], Backend]) -> None:
    """Register trusted source extensions before creating the gateway application."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
        raise ValueError("Invalid backend adapter identifier")
    if name == "sqlite" or name in _FACTORIES:
        raise ValueError("Backend adapter is already registered")
    if not callable(factory):
        raise ValueError("Backend adapter factory must be callable")
    _FACTORIES[name] = factory


def backend_adapters() -> tuple[str, ...]:
    return tuple(sorted({"sqlite", *_FACTORIES}))


def create_backend(config: ControlPlaneConfig) -> Backend:
    if config.backend_adapter == "sqlite":
        from .store import LocalControlStore

        return LocalControlStore(config)
    factory = _FACTORIES.get(config.backend_adapter)
    if factory is None:
        raise ValueError("Selected backend adapter is not registered")
    backend = factory(config)
    contracts = (
        ("management_audit", ManagementAuditRepository),
        ("configuration", ConfigurationRepository),
        ("identities", IdentityRepository),
        ("secrets", SecretStore),
        ("traffic", TrafficRepository),
        ("usage_repository", UsageRepository),
    )
    if not isinstance(backend, Backend) or any(
        not isinstance(getattr(backend, name, None), contract) for name, contract in contracts
    ):
        close = getattr(backend, "close", None)
        if callable(close):
            close()
        raise ValueError("Backend adapter does not implement the repository contracts")
    return backend
