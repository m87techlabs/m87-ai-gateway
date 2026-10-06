"""Local log showcase: content lifecycle, search, privacy and recording failures."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend_contracts import exchange
from m87_gateway.cli import local_settings
from m87_gateway.control import LocalControlStore
from m87_gateway.logging.audit import AuditRecorder
from m87_gateway.main import create_app
from m87_gateway.metrics import GatewayMetrics


@pytest.fixture
def store(tmp_path):
    return LocalControlStore(local_settings(tmp_path).control_plane)


def captured(request_id="captured", **options):
    return exchange(
        request_id,
        capture_enabled=True,
        request_content='[{"role":"user","content":"synthetic input"}]',
        response_content='[{"message":{"role":"assistant","content":"synthetic output"}}]',
        **options,
    )


def test_content_separation_and_atomic_failure(store, monkeypatch):
    event = captured()
    store.emit(event)
    with sqlite3.connect(store.database_path) as db:
        assert db.execute("SELECT request_content, response_content FROM events").fetchone() == (
            None,
            None,
        )
        assert (
            db.execute("SELECT request_content FROM exchange_content").fetchone()[0]
            == event["request_content"]
        )
    assert store.get_event("captured")["request_content_status"] == "captured"

    def fail(*args):
        raise sqlite3.OperationalError("synthetic usage failure")

    monkeypatch.setattr(store.usage_repository, "record", fail)
    with pytest.raises(sqlite3.OperationalError):
        store.emit(captured("failure"))
    assert store.get_event("failure") is None
    with sqlite3.connect(store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM exchange_content").fetchone()[0] == 1


def test_content_retention_hides_expired_payload_before_pruning_and_preserves_usage(store):
    store.config = store.config.model_copy(update={"content_retention_days": 1})
    store.emit(captured())
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with sqlite3.connect(store.database_path) as db:
        db.execute("UPDATE exchange_content SET created_at = ?", (old,))
    detail = store.get_event("captured")
    assert detail["request_content"] is None and detail["response_content"] is None
    assert detail["request_content_status"] == "expired"
    assert detail["response_content_status"] == "expired"
    assert store.export_events()[0]["request_content"] is None
    assert store.overview()["total_tokens"] == 10
    store.prune_events()
    assert store.list_events()[0]["request_id"] == "captured"
    with sqlite3.connect(store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM exchange_content").fetchone()[0] == 0


def test_project_content_deletion_and_metadata_cascade(store):
    store.emit(captured("alpha", project_id="alpha"))
    store.emit(captured("beta", project_id="beta"))
    assert store.delete_content("alpha") == 1
    assert store.get_event("alpha")["request_content_status"] == "deleted"
    assert store.get_event("beta")["request_content_status"] == "captured"
    assert store.overview(project_id="alpha")["total_tokens"] == 10
    assert store.delete_events("beta") == 1
    assert store.get_event("beta") is None
    with sqlite3.connect(store.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM exchange_content").fetchone()[0] == 0
    assert store.overview(project_id="beta")["total_tokens"] == 10
    assert {row["action"] for row in store.list_management_events()} == {
        "logs.deleted",
        "logs.content_deleted",
    }


def test_deletion_audit_failure_preserves_payloads(store, monkeypatch):
    store.emit(captured())

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic audit failure")

    monkeypatch.setattr(store.management_audit, "record", fail)
    for operation in (store.delete_content, store.delete_events):
        with pytest.raises(sqlite3.OperationalError):
            operation()
        assert store.get_event("captured")["request_content_status"] == "captured"


@pytest.mark.parametrize(
    "enabled,status,content,partial,truncated,expected",
    [
        (False, 200, None, False, False, "disabled"),
        (True, 503, None, False, False, "not_produced"),
        (None, 200, None, False, False, "unknown"),
        (True, 200, "[]", False, False, "captured"),
        (True, 499, "[]", True, False, "partial"),
        (True, 200, "synthetic prefix", False, True, "truncated"),
        (True, 499, "synthetic prefix", True, True, "partial_truncated"),
    ],
)
def test_capture_statuses(store, enabled, status, content, partial, truncated, expected):
    store.emit(
        exchange(
            "status",
            capture_enabled=enabled,
            status_code=status,
            response_content=content,
            response_content_partial=partial,
            response_content_truncated=truncated,
        )
    )
    assert store.get_event("status")["response_content_status"] == expected


def test_schema_six_migration_preserves_captured_text_keys_usage_and_audit(store):
    _, key = store.create_app_key("sample", ["auto"], False)
    store.put_provider_key("openai", "synthetic-provider-secret")
    event = captured()
    store.emit(event)
    audit = store.list_management_events()
    with sqlite3.connect(store.database_path) as db:
        db.execute(
            "UPDATE events SET request_content = ?, response_content = ?",
            (event["request_content"], event["response_content"]),
        )
        db.execute("DROP TABLE exchange_content")
        for name in (
            "capture_enabled",
            "request_content_recorded",
            "response_content_recorded",
            "content_deleted",
        ):
            db.execute(f"ALTER TABLE events DROP COLUMN {name}")
        db.execute("PRAGMA user_version = 6")
    upgraded = LocalControlStore(store.config)
    assert upgraded.authenticate_app_key(key)
    assert upgraded.get_provider_key("openai") == "synthetic-provider-secret"
    assert upgraded.overview()["total_tokens"] == 10
    assert upgraded.list_management_events() == audit
    detail = upgraded.get_event("captured")
    assert detail["request_content"][0]["content"] == "synthetic input"
    assert detail["request_content_status"] == "captured"
    assert LocalControlStore(store.config).get_event("captured") == detail
    with sqlite3.connect(store.database_path) as db:
        assert db.execute("SELECT request_content FROM events").fetchone()[0] is None


def test_recording_health_reports_failure_and_recovery_without_disclosing_errors(tmp_path, capsys):
    settings = local_settings(tmp_path)
    settings.observability.json_logs = False
    settings.observability.prometheus_metrics = False

    class Sink:
        failing = True

        def emit(self, event):
            if self.failing:
                raise OSError("synthetic-private-path-and-secret")

        def close(self):
            pass

    sink = Sink()
    recorder = AuditRecorder(settings, GatewayMetrics(), sink)
    assert recorder.health()["items"][0]["last_write_ok"] is None
    recorder.record(exchange(), ["private prompt"])
    report = recorder.health()
    assert not report["ok"] and report["items"][0]["failed_writes"] == 1
    assert "synthetic-private" not in json.dumps(report) + capsys.readouterr().out
    sink.failing = False
    recorder.record(exchange())
    report = recorder.health()
    assert report["ok"] and report["items"][0]["successful_writes"] == 1
    assert report["items"][0]["failed_writes"] == 1
    recorder.close()


def test_capture_limit_snapshot_redacts_before_truncation(tmp_path):
    settings = local_settings(tmp_path)
    settings.observability.json_logs = False
    values = []

    class Sink:
        def emit(self, event):
            values.append(event)

        def close(self):
            pass

    recorder = AuditRecorder(settings, GatewayMetrics(), Sink())
    recorder.add_secret("synthetic-known-secret")
    recorder.record(exchange(), ["synthetic-known-secret and longer synthetic text"], None, 24)
    assert len(values[0]["request_content"]) == 24
    assert "[REDACTED]" in values[0]["request_content"]
    assert "synthetic-known-secret" not in values[0]["request_content"]
    assert values[0]["request_content_truncated"]
    recorder.close()


def test_log_api_paging_search_export_and_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "synthetic-logging-admin-key-long-enough")
    with TestClient(create_app(local_settings(tmp_path))) as client:
        assert client.get("/admin/api/logging-health").status_code == 401
        client.headers["Authorization"] = "Bearer synthetic-logging-admin-key-long-enough"
        store = client.app.state.control_store
        created = datetime.now(timezone.utc).isoformat()
        for number in range(6):
            store.emit(
                captured(
                    f"row-{number}",
                    created_at=created,
                    project_id="alpha",
                    app_id="sample",
                    status_code=503 if number == 2 else 200,
                )
            )
        store.emit(captured("other", project_id="beta"))
        rows = []
        cursor = None
        while True:
            params = {"limit": 2, "project_id": "alpha", "app_id": "sample"}
            if cursor:
                params["cursor"] = cursor
            response = client.get("/admin/api/logs", params=params)
            assert response.status_code == 200
            rows.extend(item["request_id"] for item in response.json()["items"])
            cursor = response.json()["next_cursor"]
            if cursor is None:
                break
        assert rows == [f"row-{number}" for number in reversed(range(6))]
        assert len(set(rows)) == 6
        assert (
            client.get(
                "/admin/api/logs",
                params={"request_id": "row-2", "status": "error", "project_id": "alpha"},
            ).json()["items"][0]["request_id"]
            == "row-2"
        )
        assert not client.get(
            "/admin/api/logs", params={"request_id": "row-2", "project_id": "beta"}
        ).json()["items"]
        for cursor in ("bad cursor", "WzFd", "e30=", "bnVsbA=="):
            assert client.get("/admin/api/logs", params={"cursor": cursor}).status_code == 422
        metadata = client.get("/admin/api/logs/export", params={"request_id": "row-2"})
        assert len(metadata.json()) == 1 and "synthetic input" not in metadata.text
        payloads = client.get(
            "/admin/api/logs/export", params={"request_id": "row-2", "include_content": True}
        )
        assert "synthetic input" in payloads.text and "synthetic output" in payloads.text
        assert (
            client.request(
                "DELETE", "/admin/api/logs/content", json={"confirmation": "bad"}
            ).status_code
            == 422
        )
        assert (
            client.request(
                "DELETE",
                "/admin/api/logs/content",
                json={"confirmation": "DELETE", "project_id": "alpha"},
            ).json()["deleted"]
            == 6
        )
        assert client.get("/admin/api/logs/row-2").json()["request_content_status"] == "deleted"
        assert client.get("/admin/api/logs/other").json()["request_content_status"] == "captured"
        _, key = store.create_app_key("client", ["auto"], False)
        client.headers["Authorization"] = "Bearer " + key
        for path in ("logs", "logs/export", "logs/other", "logging-health"):
            assert client.get("/admin/api/" + path).status_code == 401
        assert (
            client.request(
                "DELETE", "/admin/api/logs/content", json={"confirmation": "DELETE"}
            ).status_code
            == 401
        )
