"""Reusable behavioral tests: subclass BackendContract and supply backend_factory."""

from datetime import datetime, timezone


def exchange(request_id="contract-request", **updates):
    event = {
        "request_id": request_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_id": "default",
        "app_id": "contract-app",
        "status_code": 200,
        "provider": "ollama",
        "model": "auto",
        "routed_model": "ollama:small",
        "provider_attempted": True,
        "prompt_tokens": 6,
        "completion_tokens": 4,
        "total_tokens": 10,
        "request_content_truncated": False,
        "response_content_truncated": False,
    }
    event.update(updates)
    return event


class BackendContract:
    """Each factory must reopen the same isolated store, never a live user store."""

    def test_traffic_attribution_and_queue_metadata_survive_reopen(self, backend_factory):
        backend = backend_factory()
        event = exchange(
            "queue-contract",
            client_user_hash="a" * 64,
            queue_wait_ms=12.5,
            queue_outcome="admitted",
        )
        backend.emit(event)
        backend.close()
        reopened = backend_factory()
        try:
            stored = reopened.get_event("queue-contract")
            assert stored["client_user_hash"] == "a" * 64
            assert stored["queue_wait_ms"] == 12.5
            assert stored["queue_outcome"] == "admitted"
        finally:
            reopened.close()

    def test_identity_secrets_and_config_survive_reopen(self, backend_factory):
        backend = backend_factory()
        backend.create_project("testing", "Testing")
        _, key = backend.create_app_key("contract-app", ["auto"], False, project_id="testing")
        backend.save_runtime_config({"default_model": "ollama:small"}, "openai", "synthetic-secret")
        backend.close()
        reopened = backend_factory()
        try:
            assert reopened.authenticate_app_key(key).project_id == "testing"
            assert reopened.runtime_config() == {"default_model": "ollama:small"}
            assert reopened.get_provider_key("openai") == "synthetic-secret"
            assert all("encrypted_value" not in row for row in reopened.list_provider_keys())
            assert reopened.delete_app("contract-app")
            assert reopened.authenticate_app_key(key) is None
            assert reopened.delete_provider_key("openai")
            assert reopened.get_provider_key("openai") is None
        finally:
            reopened.close()

    def test_usage_survives_log_deletion_and_duplicate_delivery(self, backend_factory):
        backend = backend_factory()
        try:
            event = exchange(request_content='[{"role":"user","content":"synthetic input"}]')
            backend.emit(event)
            backend.emit(event)
            assert backend.overview()["requests"] == 1
            assert (
                backend.get_event(event["request_id"])["request_content"][0]["content"]
                == "synthetic input"
            )
            assert backend.delete_events("default") == 1
            assert backend.get_event(event["request_id"]) is None
            assert backend.overview()["total_tokens"] == 10
            backend.emit(event)
            assert backend.overview()["requests"] == 1
            assert backend.usage()["by_app"][0]["total_tokens"] == 10
        finally:
            backend.close()

    def test_cache_unknown_usage_and_project_attribution(self, backend_factory):
        backend = backend_factory()
        try:
            backend.create_project("other", "Other")
            backend.emit(exchange())
            backend.emit(exchange("cached", cache_status="hit", provider_attempted=False))
            backend.emit(
                exchange("unknown", prompt_tokens=None, completion_tokens=None, total_tokens=None)
            )
            backend.emit(exchange("other", project_id="other", total_tokens=50))
            summary = backend.overview(project_id="default")
            assert summary["requests"] == 3
            assert summary["total_tokens"] == 10
            assert summary["cache_hits"] == 1
            assert summary["usage_unknown"] == 1
            assert backend.get_event("unknown")["total_tokens"] is None
            backend.delete_events("other")
            assert backend.overview(project_id="other")["total_tokens"] == 50
            assert backend.overview(project_id="default")["total_tokens"] == 10
        finally:
            backend.close()

    def test_key_overlap_revocation_and_management_audit(self, backend_factory):
        backend = backend_factory()
        try:
            initial, old = backend.create_app_key("contract-app", ["auto"], False)
            replacement, new = backend.issue_app_key("contract-app", expires_in_days=30)
            assert backend.authenticate_app_key(old) and backend.authenticate_app_key(new)
            backend.update_app_models("contract-app", ["ollama:small"])
            assert backend.authenticate_app_key(new).allowed_models == ["ollama:small"]
            assert backend.revoke_app_key("contract-app", initial["key_id"])
            assert backend.authenticate_app_key(old) is None
            assert backend.authenticate_app_key(new)
            metadata = backend.list_app_keys("contract-app")
            assert any(row["key_id"] == replacement["key_id"] and row["active"] for row in metadata)
            events = backend.list_management_events(project_id="default")
            assert any(row["action"] == "application_key.revoked" for row in events)
            assert all(old not in str(row) and new not in str(row) for row in events)
        finally:
            backend.close()
