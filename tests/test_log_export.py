"""Persistent metadata export, privacy, failure recovery and real HTTP delivery."""

import asyncio
import json
import sqlite3
import subprocess
import sys
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend_contracts import exchange
from examples.log_receiver.start import make_server
from m87_gateway.cli import local_settings
from m87_gateway.config import GatewaySettings, load_settings
from m87_gateway.config.settings import LogExportConfig
from m87_gateway.control import LocalControlStore
from m87_gateway.logging.audit import AuditRecorder
from m87_gateway.logging.exporters import ExportService, WebhookExporter, register_log_exporter
from m87_gateway.main import create_app
from m87_gateway.metrics import GatewayMetrics
from m87_gateway.api import routes
from test_control_api import FakeProvider


@pytest.fixture
def queue(tmp_path):
    store = LocalControlStore(local_settings(tmp_path).control_plane)
    store.export_outbox.configure(
        LogExportConfig(enabled=True, endpoint="http://127.0.0.1:9087/events"), lambda value: value
    )
    return store


def enqueue(store, request_id="one", **extra):
    store.emit(
        exchange(
            request_id,
            request_content='"private prompt"',
            response_content='"private answer"',
            **extra,
        )
    )


def rows(store):
    with sqlite3.connect(store.database_path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM log_outbox")]


def test_queue_is_metadata_only_atomic_and_independent_of_traffic(queue, monkeypatch):
    enqueue(queue, unknown_field="private unknown", client_user_hash="private correlation")
    payload = rows(queue)[0]["payload"]
    assert "private" not in payload
    assert json.loads(payload)["request_id"] == "one"
    assert queue.export_outbox.health()["pending"] == 1
    queue.delete_events()
    assert queue.get_event("one") is None
    assert queue.export_outbox.health()["pending"] == 1
    assert queue.overview()["requests"] == 1

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic disk failure")

    monkeypatch.setattr(queue.export_outbox, "enqueue", fail)
    with pytest.raises(sqlite3.OperationalError):
        enqueue(queue, "rollback")
    assert queue.get_event("rollback") is None
    assert queue.overview()["requests"] == 1


def test_capacity_and_payload_bound_preserve_local_record(queue):
    queue.export_outbox.config_export = queue.export_outbox.config_export.model_copy(
        update={"max_pending": 1}
    )
    enqueue(queue)
    enqueue(queue)  # Pending duplicate must not consume capacity or count as a drop.
    enqueue(queue, "two")
    assert len(rows(queue)) == 1
    assert queue.export_outbox.health()["dropped"] == 1
    assert queue.get_event("two")
    item = queue.export_outbox.claim()
    queue.export_outbox.complete(item, success=True)
    enqueue(queue, "large", model="x" * 20000)
    assert not rows(queue)
    assert queue.export_outbox.health()["dropped"] == 2
    assert queue.get_event("large")


def test_retry_lease_expiry_restart_and_destination_binding(queue):
    enqueue(queue)
    now = time.time()
    first = queue.export_outbox.claim(now=now)
    assert queue.export_outbox.claim(now=now) is None
    queue.export_outbox.complete(first, success=False, now=now)
    assert queue.export_outbox.claim(now=now + 1) is None
    second = queue.export_outbox.claim(now=now + 2)
    assert second["delivery_id"] == first["delivery_id"] and second["attempts"] == 2
    reopened = LocalControlStore(queue.config)
    config = queue.export_outbox.config_export
    reopened.export_outbox.configure(
        config.model_copy(update={"endpoint": "http://127.0.0.1:9187/events"}), lambda value: value
    )
    assert reopened.export_outbox.claim(now=now + 100) is None
    assert reopened.export_outbox.health()["held_for_other_destination"] == 1
    reopened.export_outbox.configure(config, lambda value: value)
    # Crash after sending but before acknowledgement: lease expires, stable delivery ID retries.
    third = reopened.export_outbox.claim(now=now + 100)
    assert third["delivery_id"] == first["delivery_id"]
    queue.export_outbox.complete(second, success=True)  # Stale lease cannot acknowledge new claim.
    assert rows(queue)
    reopened.export_outbox.complete(third, success=True)
    assert not rows(queue)
    assert reopened.export_outbox.health()["delivered"] == 1
    assert reopened.export_outbox.health()["failed_attempts"] == 1
    enqueue(reopened, "expires")
    assert reopened.export_outbox.claim(now=now + 168 * 3600 + 1000) is None
    assert reopened.export_outbox.health()["expired"] == 1


def test_schema_seven_upgrade_and_committed_queue_survive_process_exit(tmp_path):
    settings = local_settings(tmp_path)
    store = LocalControlStore(settings.control_plane)
    store.create_app_key("sample", ["auto"], False)
    enqueue(store)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TABLE log_outbox")
        connection.execute("DROP TABLE log_export_counters")
        connection.execute("PRAGMA user_version=7")
    reopened = LocalControlStore(settings.control_plane)
    assert reopened.get_event("one")["request_content"] == "private prompt"
    assert reopened.list_apps()[0]["app_id"] == "sample"
    script = """import os, sys
from pathlib import Path
from m87_gateway.cli import local_settings
from m87_gateway.control import LocalControlStore
from m87_gateway.config.settings import LogExportConfig
store=LocalControlStore(local_settings(Path(sys.argv[1])).control_plane)
store.export_outbox.configure(LogExportConfig(enabled=True, endpoint="http://127.0.0.1:9087/events"), lambda v: v)
store.emit({"request_id":"process-exit", "created_at":"2026-10-09T00:00:00+00:00", "status_code":200})
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", script, str(tmp_path)], check=True, timeout=15)
    after = LocalControlStore(settings.control_plane)
    assert rows(after)[0]["request_id"] == "process-exit"


@pytest.mark.parametrize(
    "options",
    [
        {"enabled": True},
        {"endpoint": "https://user:secret@example.test/events"},
        {"endpoint": "https://@example.test/events"},
        {"endpoint": "https://example.test/events?secret=value"},
        {"endpoint": "ftp://example.test/events"},
        {"api_key_env": "BAD NAME"},
        {"max_pending": 0},
        {"retry_seconds": 3, "max_retry_seconds": 2},
    ],
)
def test_export_config_rejects_unsafe_or_unbounded_settings(options):
    with pytest.raises(ValidationError):
        LogExportConfig(**options)


def test_environment_overrides_and_required_backend(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("control_plane:\n  enabled: true\n")
    monkeypatch.setenv("GATEWAY_LOG_EXPORT_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_LOG_EXPORT_ENDPOINT", "http://127.0.0.1:9087/events")
    monkeypatch.setenv("GATEWAY_LOG_EXPORT_API_KEY_ENV", "EXAMPLE_EXPORT_TOKEN")
    assert load_settings(path).observability.log_export.enabled
    assert local_settings(tmp_path).observability.log_export.api_key_env == "EXAMPLE_EXPORT_TOKEN"
    with pytest.raises(ValidationError):
        GatewaySettings(
            observability={
                "log_export": {"enabled": True, "endpoint": "http://127.0.0.1:9087/events"}
            }
        )


def test_adapter_validation_missing_credentials_and_disabled_default(queue, monkeypatch):
    recorder = AuditRecorder(GatewaySettings(), GatewayMetrics(), queue)
    config = queue.export_outbox.config_export
    for bad in (
        config.model_copy(update={"adapter": "unregistered"}),
        config.model_copy(update={"api_key_env": "EXAMPLE_EXPORT_TOKEN"}),
    ):
        with pytest.raises(ValueError):
            ExportService(bad, queue, recorder)
    with pytest.raises(ValueError):
        ExportService(config, object(), recorder)
    for token in ("bad token", "bad\r\ntoken", "bad\x7ftoken"):
        monkeypatch.setenv("EXAMPLE_EXPORT_TOKEN", token)
        with pytest.raises(ValueError):
            ExportService(
                config.model_copy(update={"api_key_env": "EXAMPLE_EXPORT_TOKEN"}), queue, recorder
            )
    assert LogExportConfig(endpoint="https://receiver.test/events/").endpoint.endswith("/events/")
    for name in ("webhook", "bad name"):
        with pytest.raises(ValueError):
            register_log_exporter(name, lambda *args: None)
    disabled = ExportService(LogExportConfig(), queue, recorder)
    assert not disabled.health()["enabled"]
    enqueue(queue)
    assert not rows(queue)
    recorder.close()


def test_webhook_redirect_is_not_followed_and_response_is_not_loaded():
    async def check():
        config = LogExportConfig(enabled=True, endpoint="https://receiver.test/events")
        exporter = WebhookExporter(config, "synthetic-export-token")
        await exporter.client.aclose()
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(302, headers={"Location": "https://other.test/events"})

        exporter.client = httpx.AsyncClient(
            transport=httpx.MockTransport(respond), follow_redirects=False
        )
        assert not await exporter.send("delivery", {"request_id": "one"})
        assert len(requests) == 1
        assert requests[0].headers["idempotency-key"] == "delivery"
        await exporter.close()

    asyncio.run(check())


def test_worker_timeout_storage_failure_and_shutdown_recover(queue, monkeypatch):
    from m87_gateway.logging import exporters

    entered = asyncio.Event()

    class SlowExporter:
        closed = False

        def __init__(self, *args):
            pass

        async def send(self, *args):
            entered.set()
            await asyncio.sleep(10)

        async def close(self):
            self.closed = True

    monkeypatch.setattr(exporters, "_EXPORTERS", dict(exporters._EXPORTERS))
    register_log_exporter("synthetic", SlowExporter)
    recorder = AuditRecorder(GatewaySettings(), GatewayMetrics(), queue)
    config = queue.export_outbox.config_export.model_copy(
        update={"adapter": "synthetic", "timeout_seconds": 0.05, "poll_seconds": 0.1}
    )

    async def check():
        service = ExportService(config, queue, recorder)
        enqueue(queue)
        assert await service.deliver_once()
        assert queue.export_outbox.health()["failed_attempts"] == 1
        # Simulate temporarily unavailable storage; worker survives and later recovers.
        original = queue.export_outbox.claim
        monkeypatch.setattr(
            queue.export_outbox,
            "claim",
            lambda: (_ for _ in ()).throw(sqlite3.OperationalError("private storage path")),
        )
        service.start()
        await asyncio.sleep(0.15)
        assert not service.health()["storage_ok"]
        monkeypatch.setattr(queue.export_outbox, "claim", original)
        await asyncio.sleep(0.15)
        assert service.health()["storage_ok"]
        enqueue(queue, "shutdown")
        entered.clear()
        await asyncio.wait_for(entered.wait(), timeout=1)
        await service.close()
        assert service.exporter.closed and queue.export_outbox.health()["pending"] == 2

    asyncio.run(check())
    recorder.close()


def test_real_webhook_outage_restart_dedup_and_gateway_health(tmp_path, monkeypatch):
    token = "synthetic-export-token"
    receiver = make_server(tmp_path / "receiver/data.db", token)
    thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{receiver.server_port}/events"
    settings = local_settings(tmp_path / "gateway")
    settings.observability.log_export = LogExportConfig(
        enabled=True,
        endpoint=endpoint,
        api_key_env="EXAMPLE_EXPORT_TOKEN",
        poll_seconds=0.1,
        retry_seconds=0.1,
    )
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-admin-key-long-enough")
    monkeypatch.setenv("EXAMPLE_EXPORT_TOKEN", "wrong-token")
    monkeypatch.setattr(routes, "get_provider", lambda *args: FakeProvider())
    admin = {"Authorization": "Bearer synthetic-admin-key-long-enough"}

    def until(operation):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            if operation():
                return
            time.sleep(0.02)
        pytest.fail("Export operation did not finish")

    try:
        with TestClient(create_app(settings)) as client:
            store = client.app.state.control_store
            enqueue(store, error_type="wrong-token")
            until(lambda: store.export_outbox.health()["failed_attempts"] >= 1)
            health = client.get("/admin/api/logging-health", headers=admin).json()["export"]
            assert health["enabled"] and health["pending"] == 1
            assert endpoint not in json.dumps(health) and "wrong-token" not in json.dumps(health)
            assert client.get("/admin/api/logging-health").status_code == 401
            assert store.get_event("one")
        monkeypatch.setenv("EXAMPLE_EXPORT_TOKEN", token)
        with TestClient(create_app(settings)) as client:
            store = client.app.state.control_store
            until(lambda: store.export_outbox.health()["delivered"] == 1)
            health = client.get("/admin/api/logging-health", headers=admin).json()["export"]
            assert health["pending"] == 0 and health["failed_attempts"] >= 1
            with sqlite3.connect(receiver.database) as connection:
                body = json.loads(
                    connection.execute("SELECT payload FROM deliveries").fetchone()[0]
                )
            assert "private" not in json.dumps(body)
            assert body["event"]["request_id"] == "one"
            assert body["event"]["error_type"] == "[REDACTED]"
            for _ in range(2):
                response = httpx.post(
                    endpoint,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Idempotency-Key": body["delivery_id"],
                    },
                )
                assert response.status_code == 204
            with sqlite3.connect(receiver.database) as connection:
                assert connection.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 1
            service = client.app.state.log_export
            original = service.outbox.health
            monkeypatch.setattr(
                service.outbox,
                "health",
                lambda: (_ for _ in ()).throw(sqlite3.OperationalError("private path")),
            )
            report = client.get("/admin/api/logging-health", headers=admin).json()["export"]
            assert not report["storage_ok"] and "private path" not in json.dumps(report)
            monkeypatch.setattr(service.outbox, "health", original)
            # Actual application -> gateway -> provider -> receiver flow.
            app = client.post(
                "/admin/api/apps",
                headers=admin,
                json={
                    "app_id": "export-demo",
                    "allowed_models": ["auto", settings.routing.default_model],
                },
            ).json()
            result = client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {app['api_key']}"},
                json={
                    "model": "auto",
                    "messages": [{"role": "user", "content": "private synthetic showcase"}],
                },
            )
            assert result.status_code == 200
            until(lambda: store.export_outbox.health()["delivered"] == 2)
            with sqlite3.connect(receiver.database) as connection:
                values = [
                    json.loads(row[0])
                    for row in connection.execute("SELECT payload FROM deliveries")
                ]
            record = next(
                v for v in values if v["event"]["request_id"] == result.headers["x-request-id"]
            )
            assert record["event"]["total_tokens"] == 5
            assert record["event"]["app_id"] == "export-demo"
            assert "private synthetic showcase" not in json.dumps(record)
    finally:
        receiver.shutdown()
        receiver.server_close()
        thread.join(timeout=2)
