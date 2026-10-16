"""Loki push contract and integration through the existing private export controls."""

import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from backend_contracts import exchange
from m87_gateway.config.settings import LogExportConfig
from m87_gateway.config import GatewaySettings
from m87_gateway.cli import local_settings
from m87_gateway.private_storage import prepare_file
from m87_gateway.control import LocalControlStore
from m87_gateway.logging.audit import AuditRecorder
from m87_gateway.logging.exporters import ExportService, LokiExporter
from m87_gateway.main import create_app
from m87_gateway.metrics import GatewayMetrics
from test_export_configuration import (
    ADMIN,
    TOKEN,
    collector,
    config,
    received,
    save,
    wait,
)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-admin-key-long-enough")
    admin_file = tmp_path / "gateway/admin.key"
    prepare_file(admin_file)
    admin_file.write_text("synthetic-admin-key-long-enough")
    return local_settings(tmp_path / "gateway")


@pytest.mark.parametrize("status", [204, 200, 202, 260, 301, 400, 401, 429, 500])
def test_loki_wire_contract_stable_retry_and_strict_acknowledgement(status):
    async def check():
        requests = []
        exporter = LokiExporter(
            LogExportConfig(endpoint="https://collector.example.com/loki/api/v1/push"), TOKEN
        )
        await exporter.client.aclose()

        def respond(request):
            requests.append(request)
            return httpx.Response(status, headers={"Location": "https://elsewhere.example.com"})

        exporter.client = httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
            follow_redirects=False,
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        event = {
            "created_at": "2026-10-16T12:34:56.123456+02:00",
            "request_id": "one",
            "total_tokens": None,
        }
        assert await exporter.send("stable-delivery", event) is (status == 204)
        assert await exporter.send("stable-delivery", event) is (status == 204)
        assert requests[0].content == requests[1].content
        body = json.loads(requests[0].content)
        assert len(body["streams"]) == 1
        stream = body["streams"][0]
        assert stream["stream"] == {"service_name": "m87-ai-gateway", "log_kind": "llm_exchange"}
        timestamp, line = stream["values"][0]
        epoch = datetime(2026, 10, 16, 10, 34, 56, tzinfo=timezone.utc)
        assert timestamp == str(int(epoch.timestamp()) * 1000000000 + 123456000)
        assert json.loads(line) == {**event, "delivery_id": "stable-delivery", "schema_version": 1}
        assert requests[0].headers["authorization"] == f"Bearer {TOKEN}"
        assert requests[0].headers["content-type"] == "application/json"
        await exporter.close()

    asyncio.run(check())


def test_loki_queue_rejection_reopen_retry_and_metadata_privacy(tmp_path):
    store = LocalControlStore(
        __import__("m87_gateway.cli", fromlist=["local_settings"])
        .local_settings(tmp_path)
        .control_plane
    )
    config = LogExportConfig(
        enabled=True,
        adapter="loki",
        endpoint="https://collector.example.com/loki/api/v1/push",
        retry_seconds=0.1,
    )
    recorder = AuditRecorder(
        GatewaySettings(),
        GatewayMetrics(),
        store,
    )
    responses = [260, 204]
    sent = []

    async def deliver(backend):
        service = ExportService(config, backend, recorder)
        await service.exporter.client.aclose()

        def respond(request):
            sent.append(json.loads(request.content))
            return httpx.Response(responses.pop(0))

        service.exporter.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            assert await service.deliver_once()
        finally:
            await service.close()

    store.export_outbox.configure(config, recorder.redact)
    store.emit(
        exchange(
            "loki-retry",
            request_content="private prompt",
            response_content="private output",
            client_user_hash="private attribution",
        )
    )
    asyncio.run(deliver(store))
    assert store.export_outbox.health()["pending"] == 1
    assert store.export_outbox.health()["failed_attempts"] == 1
    reopened = LocalControlStore(store.config)
    # Advance eligibility without a wall-clock sleep; persisted IDs/payload stay unchanged.
    with reopened._connect() as connection:
        connection.execute("UPDATE log_outbox SET next_at=0, lease_until=0")
    asyncio.run(deliver(reopened))
    assert sent[0] == sent[1] and "private" not in json.dumps(sent)
    assert reopened.export_outbox.health()["delivered"] == 1
    assert reopened.export_outbox.health()["pending"] == 0
    recorder.close()


def test_console_loki_probe_binding_and_delivery_survive_restart(settings, tmp_path):
    with collector(tmp_path / "receiver.db") as (server, endpoint):
        with TestClient(create_app(settings)) as client:
            assert "loki" in client.get("/admin/api/log-export", headers=ADMIN).json()["adapters"]
            value = config(client, endpoint)
            assert save(client, value, TOKEN).status_code == 204
            value.update(adapter="loki", endpoint=endpoint.replace("/events", "/loki/api/v1/push"))
            response = client.post(
                "/admin/api/log-export/test", headers=ADMIN, json={"config": value}
            )
            assert response.status_code == 409
            assert received(server) == []  # A saved webhook token must not be silently reused.
            assert client.post(
                "/admin/api/log-export/test", headers=ADMIN, json={"config": value, "key": TOKEN}
            ).json()["ok"]
            assert (
                client.get("/admin/api/log-export", headers=ADMIN).json()["config"]["adapter"]
                == "webhook"
            )
            assert save(client, value, TOKEN).status_code == 204
        with TestClient(create_app(settings)) as client:
            store = client.app.state.control_store
            store.emit(exchange("loki-console", request_content="private prompt"))
            wait(lambda: store.export_outbox.health()["delivered"] == 1)
            record = next(v for v in received(server) if v["event"]["request_id"] == "loki-console")
            assert record["event"]["total_tokens"] == 10
            assert "private" not in json.dumps(record)


@pytest.mark.parametrize("created_at", ["invalid", "2026-10-16T12:00:00"])
def test_loki_rejects_invalid_or_ambiguous_timestamps_before_network(created_at):
    async def check():
        exporter = LokiExporter(LogExportConfig(endpoint="https://collector.example.com"), None)
        try:
            with pytest.raises(ValueError):
                await exporter.send("delivery", {"created_at": created_at})
        finally:
            await exporter.close()

    asyncio.run(check())
