"""Metrics remain private and reflect current logging state without stale gauges."""

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from backend_contracts import exchange
from m87_gateway.cli import local_settings
from m87_gateway.config import GatewaySettings
from m87_gateway.main import create_app
from m87_gateway.metrics import GatewayMetrics
from m87_gateway.metrics.logging import LoggingCollector


ASSETS = Path(__file__).resolve().parents[1] / "deploy/observability"


def samples(text):
    return {
        sample.name: sample.value
        for family in text_string_to_metric_families(text)
        for sample in family.samples
    }


def test_scrape_reports_log_failures_recovery_and_storage_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-operator-key-long-enough")
    with TestClient(create_app(local_settings(tmp_path))) as client:
        store = client.app.state.control_store
        assert "m87_gateway_log_last_write_ok" not in samples(client.get("/metrics").text)
        store.emit(exchange("private-request"))
        recorder = client.app.state.recorder
        recorder._record_health(store, False)
        text = client.get("/metrics").text
        assert samples(text)["m87_gateway_log_last_write_ok"] == 0
        assert samples(text)["m87_gateway_log_export_pending"] == 0
        assert "private-request" not in text and str(tmp_path) not in text
        recorder._record_health(store, True)
        assert samples(client.get("/metrics").text)["m87_gateway_log_last_write_ok"] == 1
        original = store.export_outbox.health

        def unavailable():
            raise OSError("private-endpoint-and-secret")

        monkeypatch.setattr(store.export_outbox, "health", unavailable)
        text = client.get("/metrics").text
        values = samples(text)
        assert values["m87_gateway_log_export_storage_ok"] == 0
        assert "m87_gateway_log_export_pending" not in values
        assert "m87_gateway_log_export_delivered_total" not in values
        assert "private-endpoint-and-secret" not in text
        monkeypatch.setattr(store.export_outbox, "health", original)
        assert samples(client.get("/metrics").text)["m87_gateway_log_export_storage_ok"] == 1


def test_collector_reads_current_worker_and_persistent_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-operator-key-long-enough")
    settings = local_settings(tmp_path)
    for _ in range(2):
        with TestClient(create_app(settings)) as client:
            store = client.app.state.control_store
            with store._connect() as connection:
                connection.execute("UPDATE log_export_counters SET delivered=7, dropped=2")
            values = samples(client.get("/metrics").text)
            assert values["m87_gateway_log_export_delivered_total"] == 7
            assert values["m87_gateway_log_export_dropped_total"] == 2
            assert values["m87_gateway_log_export_enabled"] == 0
            worker = client.app.state.log_export
            original = worker.health
            monkeypatch.setattr(worker, "health", lambda: {**original(), "enabled": True})
            assert samples(client.get("/metrics").text)["m87_gateway_log_export_enabled"] == 1
            monkeypatch.setattr(worker, "health", original)


def test_collector_has_only_fixed_destination_labels():
    class Recorder:
        def health(self):
            return {"items": [{"destination": "https://private.example.com", "failed_writes": 10}]}

    class Worker:
        def health(self):
            return {"enabled": False, "storage_ok": False}

    metrics = GatewayMetrics()
    metrics.registry.register(LoggingCollector(Recorder(), Worker))
    assert "private.example.com" not in metrics.render().decode()


def test_monitoring_preserves_metrics_disabled():
    settings = GatewaySettings()
    settings.observability.prometheus_metrics = False
    with TestClient(create_app(settings)) as client:
        assert client.get("/metrics").status_code == 404


def test_dashboard_queries_reference_real_metric_samples():
    metrics = GatewayMetrics()
    metrics.observe(exchange(latency_ms=100))

    class Recorder:
        def health(self):
            return {
                "items": [
                    {
                        "destination": "control_store",
                        "last_write_ok": True,
                        "successful_writes": 1,
                        "failed_writes": 0,
                    }
                ]
            }

    class Worker:
        def health(self):
            return {
                "enabled": True,
                "storage_ok": True,
                "pending": 1,
                "held_for_other_destination": 0,
                "awaiting_expiry": 0,
                "oldest_pending_at": 1,
                "max_pending": 5000,
                "delivered": 0,
                "failed_attempts": 0,
                "dropped": 0,
                "expired": 0,
            }

    metrics.registry.register(LoggingCollector(Recorder(), Worker))
    # Instantiate bounded-label metrics that have not yet had a synthetic event.
    metrics.streams.labels("ollama", "failed").inc()
    metrics.provider_errors.labels("ollama").inc()
    metrics.cache_requests.labels("miss").inc()
    metrics.rate_limits.labels("sample").inc()
    names = samples(metrics.render().decode())
    overview = json.loads((ASSETS / "grafana/dashboards/gateway-overview.json").read_text())
    for panel in overview["panels"]:
        for target in panel["targets"]:
            for name in re.findall(r"m87_gateway_[a-z_]+", target["expr"]):
                assert name in names, name
    for path in (ASSETS / "grafana/dashboards").glob("*.json"):
        dashboard = json.loads(path.read_text())
        assert len({p["id"] for p in dashboard["panels"]}) == len(dashboard["panels"])
        assert dashboard["schemaVersion"] == 39
        assert "private-request" not in path.read_text()
