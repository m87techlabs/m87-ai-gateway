import json
import os

import pytest
from fastapi.testclient import TestClient

from m87_gateway.config import GatewaySettings
from m87_gateway.logging.audit import AuditRecorder, JsonFileSink
from m87_gateway.main import create_app
from m87_gateway.metrics import GatewayMetrics


def settings(path, global_capture=False, app_capture=False, limit=16384):
    return GatewaySettings.model_validate(
        {
            "apps": [
                {
                    "app_id": "test-app",
                    "api_key": "synthetic-app-secret",
                    "allowed_models": ["auto", "ollama:test"],
                    "capture_content": app_capture,
                }
            ],
            "routing": {"default_model": "ollama:test"},
            "observability": {
                "traffic_log": {
                    "path": str(path),
                    "capture_content": global_capture,
                    "max_content_chars": limit,
                }
            },
        }
    )


@pytest.mark.parametrize(
    "global_capture,app_capture,expected",
    [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, True, True),
    ],
)
def test_content_requires_both_switches_and_stays_out_of_stdout(
    tmp_path,
    monkeypatch,
    capsys,
    global_capture,
    app_capture,
    expected,
):
    from m87_gateway.api import routes

    class FakeProvider:
        async def chat_completions(self, payload, model):
            return {
                "id": "test",
                "created": 1,
                "model": "ollama:test",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "synthetic reply synthetic-app-secret Bearer unknown-credential",
                        },
                    }
                ],
            }

    monkeypatch.setattr(routes, "get_provider", lambda *args: FakeProvider())
    path = tmp_path / "logs" / "traffic.jsonl"
    app = create_app(settings(path, global_capture, app_capture))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": "Bearer synthetic-app-secret",
            },
            json={
                "messages": [{"role": "user", "content": "synthetic prompt synthetic-app-secret"}]
            },
        )
        assert response.status_code == 200
        # Capture must never change what the caller receives.
        assert "synthetic-app-secret" in response.json()["choices"][0]["message"]["content"]
        client.post(
            "/v1/chat/completions", json={"messages": [{"role": "user", "content": "private"}]}
        )
        client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": "Bearer synthetic-app-secret",
            },
            content=b'{"messages": "private-invalid"}',
        )
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 3
    success, failure, invalid = records
    assert success["request_id"] == response.headers["x-request-id"]
    assert success["event"] == "llm_exchange"
    assert success["status_code"] == 200 and failure["status_code"] == 401
    assert success["total_tokens"] is None
    assert ("request_content" in success) is expected
    assert ("response_content" in success) is expected
    assert "request_content" not in failure
    assert invalid["status_code"] == 422 and "request_content" not in invalid
    assert "private-invalid" not in path.read_text()
    if expected:
        assert "synthetic prompt" in success["request_content"]
        assert "synthetic reply" in success["response_content"]
        assert "[REDACTED]" in success["response_content"]
    text = path.read_text()
    assert "synthetic-app-secret" not in text
    assert "unknown-credential" not in text
    assert os.stat(path).st_mode & 0o777 == 0o600
    stdout = capsys.readouterr().out
    assert "synthetic prompt" not in stdout and "synthetic reply" not in stdout
    assert "synthetic-app-secret" not in stdout
    assert all(json.loads(line)["event"] == "llm_exchange" for line in stdout.splitlines())


def test_redaction_precedes_truncation_and_covers_provider_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-provider-secret")
    config = settings(tmp_path / "traffic.jsonl", True, True, limit=12)
    recorder = AuditRecorder(config, GatewayMetrics())
    try:
        content, truncated = recorder.content(["synthetic-provider-secret and more"])
        assert truncated
        assert "synthetic" not in content
        assert "[REDACTED]" in content
    finally:
        recorder.close()


def test_file_sink_failure_does_not_leak_content(tmp_path, capsys):
    metrics = GatewayMetrics()
    recorder = AuditRecorder(settings(tmp_path / "traffic.jsonl", True, True), metrics)

    def fail(event):
        raise OSError("private disk-path detail")

    recorder.sink.emit = fail
    try:
        recorder.record({"request_id": "test", "event": "llm_exchange"}, ["private prompt"])
    finally:
        recorder.close()
    output = capsys.readouterr().out
    assert "traffic_log_write_failed" in output
    assert "private prompt" not in output and "private disk-path" not in output
    assert b"m87_gateway_log_sink_errors_total 1.0" in metrics.render()


def test_rotation_retains_bounded_files_with_private_permissions(tmp_path):
    path = tmp_path / "traffic.jsonl"
    sink = JsonFileSink(str(path), max_bytes=200, backup_count=2)
    for index in range(20):
        sink.emit({"event": "test", "index": index, "content": "x" * 80})
    sink.close()
    paths = list(tmp_path.glob("traffic.jsonl*"))
    assert len(paths) == 3
    for rotated in paths:
        assert rotated.stat().st_mode & 0o777 == 0o600
        assert all(json.loads(line) for line in rotated.read_text().splitlines())


def test_insecure_existing_file_is_rejected(tmp_path):
    path = tmp_path / "traffic.jsonl"
    path.touch(mode=0o644)
    with pytest.raises(ValueError, match="owner-only"):
        JsonFileSink(str(path), 1024, 1)


def test_symlink_traffic_file_is_rejected(tmp_path):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("Platform does not provide no-follow file opens")
    target = tmp_path / "target.jsonl"
    target.touch(mode=0o600)
    link = tmp_path / "traffic.jsonl"
    link.symlink_to(target)
    with pytest.raises(OSError):
        JsonFileSink(str(link), 1024, 1)


def test_metadata_only_without_file(tmp_path, capsys):
    config = GatewaySettings()
    recorder = AuditRecorder(config, GatewayMetrics())
    recorder.record({"event": "llm_exchange", "request_id": "test"}, ["must not reach stdout"])
    recorder.close()
    assert "must not reach stdout" not in capsys.readouterr().out


def test_json_stdout_can_be_disabled(tmp_path, capsys):
    config = GatewaySettings.model_validate({"observability": {"json_logs": False}})
    recorder = AuditRecorder(config, GatewayMetrics())
    recorder.record({"event": "llm_exchange", "request_id": "test"})
    recorder.close()
    assert capsys.readouterr().out == ""
