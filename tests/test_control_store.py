import json
import sqlite3
import stat

from m87_gateway.config import ControlPlaneConfig
from m87_gateway.control import LocalControlStore


def store(tmp_path):
    return LocalControlStore(
        ControlPlaneConfig(
            enabled=True,
            database_path=str(tmp_path / "control.db"),
            master_key_path=str(tmp_path / "master.key"),
        )
    )


def event(**updates):
    value = {
        "request_id": "request-1",
        "created_at": "2026-10-02T12:00:00+00:00",
        "app_id": "flow-lab",
        "provider": "ollama",
        "model": "auto",
        "routed_model": "ollama:gemma3:1b",
        "status_code": 200,
        "latency_ms": 125.5,
        "guardrail_action": "allow",
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
        "provider_attempted": True,
        "request_content": json.dumps([{"role": "user", "content": "hello"}]),
        "response_content": json.dumps([{"message": {"content": "hi"}}]),
    }
    value.update(updates)
    return value


def test_events_include_usage_and_opted_in_content(tmp_path):
    control = store(tmp_path)
    control.emit(event())

    detail = control.get_event("request-1")
    assert detail["total_tokens"] == 20
    assert detail["request_content"][0]["content"] == "hello"
    assert detail["response_content"][0]["message"]["content"] == "hi"
    assert control.list_events()[0]["routed_model"] == "ollama:gemma3:1b"


def test_application_key_is_hashed_and_revocable(tmp_path):
    control = store(tmp_path)
    metadata, raw_key = control.create_app_key("prayog", ["auto"], True)

    assert metadata["key_prefix"] == raw_key[:12]
    assert control.authenticate_app_key(raw_key).app_id == "prayog"
    assert raw_key.encode() not in (tmp_path / "control.db").read_bytes()
    assert control.delete_app("prayog")
    assert control.authenticate_app_key(raw_key) is None


def test_provider_key_is_encrypted_and_never_listed(tmp_path):
    control = store(tmp_path)
    secret = "sk-test-provider-secret"
    control.put_provider_key("openai", secret)

    assert control.get_provider_key("openai") == secret
    assert secret.encode() not in (tmp_path / "control.db").read_bytes()
    assert "encrypted_value" not in control.list_provider_keys()[0]
    assert control.delete_provider_key("openai")
    assert control.get_provider_key("openai") is None


def test_control_files_are_owner_only(tmp_path):
    control = store(tmp_path)
    control.emit(event())

    assert stat.S_IMODE((tmp_path / "control.db").stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "master.key").stat().st_mode) == 0o600


def test_existing_broad_master_key_permissions_fail_closed(tmp_path):
    key = tmp_path / "master.key"
    key.write_text("not-a-key", encoding="utf-8")
    key.chmod(0o644)
    config = ControlPlaneConfig(
        enabled=True,
        database_path=str(tmp_path / "control.db"),
        master_key_path=str(key),
    )

    try:
        LocalControlStore(config)
    except ValueError as exc:
        assert "owner-only" in str(exc)
    else:
        raise AssertionError("broad master key permissions were accepted")


def test_provider_ciphertext_is_not_plaintext_in_sqlite(tmp_path):
    control = store(tmp_path)
    control.put_provider_key("openai", "sk-another-secret")
    with sqlite3.connect(tmp_path / "control.db") as connection:
        stored = connection.execute("SELECT encrypted_value FROM provider_keys").fetchone()[0]
    assert b"sk-another-secret" not in stored


def test_existing_database_upgrades_without_losing_keys(tmp_path):
    control = store(tmp_path)
    _, key = control.create_app_key("existing", ["auto"], False)
    with sqlite3.connect(tmp_path / "control.db") as connection:
        connection.execute("ALTER TABLE app_keys DROP COLUMN rate_limit_per_minute")
        for name in ("provider_attempts", "provider_retries", "cache_status"):
            connection.execute(f"ALTER TABLE events DROP COLUMN {name}")
    upgraded = store(tmp_path)
    assert upgraded.authenticate_app_key(key).app_id == "existing"
    upgraded.emit(event(cache_status="hit", provider_attempts=0))
    assert upgraded.get_event("request-1")["cache_status"] == "hit"
