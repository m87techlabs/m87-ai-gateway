"""SQLite runs the reusable contracts without network services or containers."""

import sqlite3

from legacy_backend import schema_two_identities
from datetime import datetime, timedelta, timezone

import pytest

from backend_contracts import BackendContract, exchange
from m87_gateway.config import ControlPlaneConfig, GatewaySettings, load_settings
from m87_gateway.control import LocalControlStore
from m87_gateway.control.backends import backend_adapters, create_backend, register_backend
from m87_gateway.control.store import SCHEMA_VERSION


@pytest.fixture
def backend_config(tmp_path):
    return ControlPlaneConfig(
        enabled=True,
        database_path=str(tmp_path / "control.db"),
        master_key_path=str(tmp_path / "master.key"),
    )


@pytest.fixture
def backend_factory(backend_config):
    return lambda: create_backend(backend_config)


class TestSQLiteBackend(BackendContract):
    pass


def test_schema_one_backfills_only_existing_evidence_and_preserves_keys(backend_config):
    store = create_backend(backend_config)
    _, key = store.create_app_key("existing", ["auto"], False)
    store.put_provider_key("openai", "synthetic-secret")
    store.emit(exchange())
    with sqlite3.connect(backend_config.database_path) as db:
        schema_two_identities(db)
        db.execute("DROP TABLE usage_records")
        db.execute("PRAGMA user_version = 1")
    upgraded = create_backend(backend_config)
    assert upgraded.authenticate_app_key(key).app_id == "existing"
    assert upgraded.get_provider_key("openai") == "synthetic-secret"
    assert upgraded.overview()["total_tokens"] == 10
    upgraded.delete_events()
    assert create_backend(backend_config).overview()["total_tokens"] == 10
    with sqlite3.connect(backend_config.database_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        columns = {row[1] for row in db.execute("PRAGMA table_info(usage_records)")}
        assert "request_content" not in columns and "response_content" not in columns


def test_independent_retention_and_idempotent_usage(backend_config):
    store = create_backend(
        backend_config.model_copy(update={"retention_days": 1, "usage_retention_days": 7})
    )
    now = datetime.now(timezone.utc)
    store.emit(exchange("old", created_at=(now - timedelta(days=2)).isoformat()))
    assert store.get_event("old") is None
    assert store.overview(hours=72)["requests"] == 1
    store.emit(exchange("expired", created_at=(now - timedelta(days=8)).isoformat()))
    assert store.overview(hours=240)["requests"] == 1
    # A later duplicate may update traffic, but it must not rewrite usage/project attribution.
    store.emit(exchange("old", total_tokens=99, project_id="different"))
    assert store.overview(hours=72)["total_tokens"] == 10
    assert store.overview(hours=72, project_id="different")["requests"] == 0


def test_event_and_usage_write_roll_back_together(backend_config, monkeypatch):
    store = create_backend(backend_config)

    def failure(connection, event):
        raise sqlite3.OperationalError("synthetic write failure")

    monkeypatch.setattr(store.usage_repository, "record", failure)
    with pytest.raises(sqlite3.OperationalError):
        store.emit(exchange())
    assert store.get_event("contract-request") is None
    assert store.overview()["requests"] == 0


def test_configuration_and_secret_write_roll_back_together(backend_config):
    store = create_backend(backend_config)
    store.save_runtime_config({"existing": True}, "openai", "original-secret")
    with pytest.raises(TypeError):
        store.save_runtime_config({"invalid": object()}, "openai", "replacement-secret")
    assert store.runtime_config() == {"existing": True}
    assert store.get_provider_key("openai") == "original-secret"


def test_registry_selection_and_rejection(backend_config, monkeypatch):
    from m87_gateway.control import backends

    monkeypatch.setattr(backends, "_FACTORIES", {})
    calls = []

    def factory(config):
        calls.append(config.backend_adapter)
        return LocalControlStore(config.model_copy(update={"backend_adapter": "sqlite"}))

    register_backend("contract_sqlite", factory)
    assert backend_adapters() == ("contract_sqlite", "sqlite")
    assert create_backend(backend_config.model_copy(update={"backend_adapter": "contract_sqlite"}))
    assert calls == ["contract_sqlite"]
    with pytest.raises(ValueError, match="already registered"):
        register_backend("contract_sqlite", factory)
    with pytest.raises(ValueError, match="already registered"):
        register_backend("sqlite", factory)
    with pytest.raises(ValueError, match="Invalid"):
        register_backend("module:factory", factory)
    register_backend("broken", lambda config: object())
    with pytest.raises(ValueError, match="repository contracts"):
        create_backend(backend_config.model_copy(update={"backend_adapter": "broken"}))


def test_unknown_adapter_never_creates_local_files(backend_config, tmp_path):
    config = backend_config.model_copy(update={"backend_adapter": "not_installed"})
    with pytest.raises(ValueError, match="not registered"):
        create_backend(config)
    with pytest.raises(ValueError, match="requires the sqlite"):
        LocalControlStore(config)
    assert not list(tmp_path.iterdir())


def test_backend_bootstrap_environment_and_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_BACKEND_ADAPTER", "sqlite")
    monkeypatch.setenv("GATEWAY_USAGE_RETENTION_DAYS", "90")
    config = tmp_path / "gateway.yaml"
    config.write_text("control_plane:\n  backend_adapter: sqlite\n  usage_retention_days: 365\n")
    settings = load_settings(config)
    assert settings.control_plane.backend_adapter == "sqlite"
    assert settings.control_plane.usage_retention_days == 90
    with pytest.raises(ValueError):
        GatewaySettings(control_plane={"backend_adapter": "arbitrary.module:factory"})
    with pytest.raises(ValueError):
        GatewaySettings(control_plane={"usage_retention_days": 0})


def test_failed_migration_rolls_back_schema_and_version(backend_config, monkeypatch):
    from m87_gateway.control.repositories.usage import SQLiteUsageRepository

    store = create_backend(backend_config)
    _, key = store.create_app_key("existing", ["auto"], False)
    store.emit(exchange())
    with sqlite3.connect(backend_config.database_path) as db:
        schema_two_identities(db)
        db.execute("DROP TABLE usage_records")
        db.execute("PRAGMA user_version = 1")
    migrate = SQLiteUsageRepository.migrate

    def fail(connection, previous_version):
        migrate(connection, previous_version)
        raise sqlite3.OperationalError("synthetic migration failure")

    with monkeypatch.context() as patch:
        patch.setattr(SQLiteUsageRepository, "migrate", staticmethod(fail))
        with pytest.raises(sqlite3.OperationalError):
            create_backend(backend_config)
    with sqlite3.connect(backend_config.database_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='usage_records'"
        ).fetchone()
    upgraded = create_backend(backend_config)
    assert upgraded.authenticate_app_key(key)
    assert upgraded.overview()["total_tokens"] == 10


def test_registered_backend_used_by_gateway_startup(backend_config, monkeypatch):
    import asyncio

    from m87_gateway.control import backends
    from m87_gateway.main import create_app

    monkeypatch.setattr(backends, "_FACTORIES", {})
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-operator-key-with-enough-entropy")
    calls = []

    def factory(config):
        calls.append(config.backend_adapter)
        return LocalControlStore(config.model_copy(update={"backend_adapter": "sqlite"}))

    register_backend("startup_contract", factory)
    settings = GatewaySettings(
        control_plane=backend_config.model_copy(update={"backend_adapter": "startup_contract"})
    )
    app = create_app(settings)

    async def exercise():
        async with app.router.lifespan_context(app):
            app.state.control_store.emit(exchange())
            assert app.state.control_store.overview()["total_tokens"] == 10

    asyncio.run(exercise())
    assert calls == ["startup_contract"]


def test_local_launcher_applies_backend_and_usage_bootstrap(tmp_path, monkeypatch):
    from m87_gateway.cli import local_settings

    monkeypatch.setenv("GATEWAY_USAGE_RETENTION_DAYS", "90")
    monkeypatch.setenv("GATEWAY_BACKEND_ADAPTER", "not_installed")
    config = local_settings(tmp_path).control_plane
    assert config.usage_retention_days == 90
    assert config.backend_adapter == "not_installed"
    with pytest.raises(ValueError, match="not registered"):
        create_backend(config)
    assert not list(tmp_path.iterdir())
    monkeypatch.setenv("GATEWAY_USAGE_RETENTION_DAYS", "0")
    with pytest.raises(ValueError):
        local_settings(tmp_path)
