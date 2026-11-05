"""Console sessions and the feature list behind its Features page."""

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from m87_gateway.cli import local_settings
from m87_gateway.control import api as control_api
from m87_gateway.main import create_app
from test_runtime import completion

KEY = "synthetic-operator-key-long-enough"
ADMIN = {"Authorization": f"Bearer {KEY}"}
CONSOLE = {"X-Gateway-Console": "1"}


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", KEY)
    original = httpx.AsyncClient
    seen = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(200, json=completion("ok"))

    def client(**kwargs):
        if "transport" not in kwargs:
            kwargs["transport"] = httpx.MockTransport(upstream)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    settings = local_settings(tmp_path)
    settings.observability.json_logs = False
    settings.providers.ollama.enabled = True
    settings.routing.default_model = "ollama:test"
    with TestClient(create_app(settings), base_url="http://localhost") as browser:
        browser.upstream_requests = seen
        yield browser


def test_session_cookie_is_private_and_survives_a_reload(gateway):
    assert gateway.get("/admin/api/session").status_code == 401
    assert gateway.post("/admin/api/session", json={"key": "wrong"}).status_code == 401
    created = gateway.post("/admin/api/session", json={"key": KEY})
    assert created.status_code == 204
    cookie = created.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/admin" in cookie
    assert KEY.lower() not in cookie
    assert gateway.get("/admin/api/session").json() == {
        "authenticated": True,
        "actor": "admin-key",
        "role": "admin",
        "method": "key",
    }
    assert gateway.get("/admin/api/overview").status_code == 200


def test_session_writes_need_the_console_header(gateway):
    gateway.post("/admin/api/session", json={"key": KEY})
    body = {"project_id": "new-project", "name": "New"}
    assert gateway.post("/admin/api/projects", json=body).status_code == 401
    assert gateway.post("/admin/api/projects", json=body, headers=CONSOLE).status_code == 201


def test_ending_a_session_clears_it_and_bearer_keys_still_work(gateway):
    gateway.post("/admin/api/session", json={"key": KEY})
    assert gateway.delete("/admin/api/session").status_code == 204
    assert gateway.get("/admin/api/session").status_code == 401
    assert gateway.get("/admin/api/session", headers=ADMIN).status_code == 200


def test_about_reports_the_running_build_to_operators_only(gateway, monkeypatch):
    from m87_gateway import __version__

    assert gateway.get("/admin/api/about").status_code == 401
    monkeypatch.setenv("M87_GATEWAY_REVISION", "abc123")
    assert gateway.get("/admin/api/about", headers=ADMIN).json() == {
        "version": __version__,
        "revision": "abc123",
    }
    monkeypatch.setenv("M87_GATEWAY_REVISION", "unknown")
    assert gateway.get("/admin/api/about", headers=ADMIN).json()["revision"] is None


def test_every_release_has_notes_and_the_version_agrees():
    from pathlib import Path

    from m87_gateway import __version__

    root = Path(__file__).resolve().parents[1]
    assert (root / "docs" / "releases" / f"{__version__}.md").is_file()
    assert f'version = "{__version__}"' in (root / "pyproject.toml").read_text()
    assert f"## [{__version__}]" in (root / "CHANGELOG.md").read_text()


def test_console_page_explains_itself_when_it_has_not_been_built(gateway, tmp_path, monkeypatch):
    monkeypatch.setattr(control_api, "STATIC_DIR", tmp_path / "missing")
    page = gateway.get("/admin")
    assert page.status_code == 200
    assert "Gateway Console" in page.text and "npm ci" in page.text
    assert KEY not in page.text


def test_console_assets_serve_built_files_only(gateway, tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index-abc.js").write_text("synthetic")
    (tmp_path / "secret.txt").write_text("private")
    monkeypatch.setattr(control_api, "STATIC_DIR", tmp_path)
    assert gateway.get("/admin/assets/index-abc.js").text == "synthetic"
    assert gateway.get("/admin/assets/missing.js").status_code == 404
    assert gateway.get("/admin/assets/..%2Fsecret.txt").status_code == 404


def features(gateway):
    response = gateway.get("/admin/api/features", headers=ADMIN)
    assert response.status_code == 200
    return {item["id"]: item for item in response.json()["items"]}, response.headers["etag"]


def put(gateway, feature, etag=None, **body):
    headers = {**ADMIN, **({"If-Match": etag} if etag else {})}
    return gateway.put(f"/admin/api/features/{feature}", headers=headers, json=body)


def test_feature_list_reflects_settings_and_marks_planned_work(gateway):
    items, _ = features(gateway)
    assert items["response_cache"]["status"] == "off"
    assert items["metrics"]["status"] == "on"
    assert items["concurrency"]["toggleable"] is False
    assert items["budgets"]["status"] == "planned"
    assert {field["name"] for field in items["response_cache"]["fields"]} == {
        "ttl_seconds",
        "max_entries",
    }
    assert put(gateway, "budgets", enabled=True).status_code == 404
    assert put(gateway, "nope", enabled=True).status_code == 404
    assert put(gateway, "concurrency", enabled=False).status_code == 422
    assert put(gateway, "response_cache", values={"bogus": 1}).status_code == 422


@pytest.mark.parametrize(
    "feature,check",
    [
        ("response_cache", lambda s: s.cache.enabled),
        ("retries", lambda s: s.retry.max_attempts == 3),
        ("request_queue", lambda s: s.limits.queue_max_depth == 64),
        ("strict_mode", lambda s: s.compatibility.strict_requests),
        ("content_capture", lambda s: s.observability.traffic_log.capture_content),
    ],
)
def test_turning_a_feature_on_changes_live_settings_and_persists(gateway, feature, check, tmp_path):
    response = put(gateway, feature, enabled=True)
    assert response.status_code == 200 and response.json()["enabled"] is True
    assert check(gateway.app.state.settings)
    assert features(gateway)[0][feature]["enabled"] is True
    assert put(gateway, feature, enabled=False).json()["enabled"] is False
    assert not check(gateway.app.state.settings)


def test_settings_survive_a_restart_including_console_only_ones(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", KEY)
    with TestClient(create_app(local_settings(tmp_path))) as first:
        assert put(
            first, "blocklist", enabled=True, values={"blocked_terms": ["secret"]}
        ).is_success
        assert put(first, "metrics", enabled=False).is_success
        assert put(first, "json_logs", enabled=False).is_success
        assert put(first, "response_cache", enabled=True, values={"ttl_seconds": 60}).is_success
        assert put(first, "log_retention", values={"retention_days": 9}).is_success
        assert put(first, "content_capture", values={"content_retention_days": 7}).is_success
        routes = [{"task": "code", "model": "ollama:coder"}]
        assert put(first, "task_routing", values={"routes": routes}).is_success
    with TestClient(create_app(local_settings(tmp_path))) as second:
        settings = second.app.state.settings
        assert settings.guardrails.blocklist.blocked_terms == ["secret"]
        assert settings.observability.prometheus_metrics is False
        assert settings.observability.json_logs is False
        assert settings.cache.enabled and settings.cache.ttl_seconds == 60
        assert settings.control_plane.retention_days == 9
        assert settings.control_plane.content_retention_days == 7
        assert settings.routing.rules[0].route_to == "ollama:coder"
        assert second.get("/metrics").status_code == 404
        items = {
            i["id"]: i for i in second.get("/admin/api/features", headers=ADMIN).json()["items"]
        }
        assert items["task_routing"]["values"]["routes"] == routes


def test_features_take_effect_on_traffic(gateway):
    created = gateway.post(
        "/admin/api/apps",
        headers=ADMIN,
        json={"app_id": "a", "allowed_models": ["ollama:test", "auto", "ollama:coder"]},
    ).json()
    app = {"Authorization": f"Bearer {created['api_key']}"}

    def chat(**extra):
        body = {"model": "auto", "messages": [{"role": "user", "content": "Tell me a SECRET"}]}
        return gateway.post("/v1/chat/completions", headers=app, json={**body, **extra})

    assert chat().status_code == 200
    put(gateway, "blocklist", enabled=True, values={"blocked_terms": ["secret"]})
    assert chat().json()["error"]["code"] == "blocklist_match"
    put(gateway, "blocklist", enabled=False)
    assert chat().status_code == 200

    put(gateway, "task_routing", values={"routes": [{"task": "code", "model": "ollama:coder"}]})
    assert chat(task="code").json()["model"] == "ollama:coder"

    put(gateway, "strict_mode", enabled=True)
    assert chat(reasoning_effort="none").json()["error"]["code"] == "strict_mode_rejected"
    put(gateway, "strict_mode", enabled=False)
    assert chat(reasoning_effort="none").status_code == 200

    put(gateway, "metrics", enabled=False)
    assert gateway.get("/metrics").status_code == 404
    put(gateway, "metrics", enabled=True)
    assert gateway.get("/metrics").status_code == 200


@pytest.mark.parametrize(
    "feature,body,expected",
    [
        ("response_cache", {"values": {"ttl_seconds": 0}}, "Keep answers for"),
        ("retries", {"values": {"max_attempts": 9}}, "Attempts"),
        ("concurrency", {"values": {"max_concurrent_requests": "many"}}, "Concurrent"),
        ("blocklist", {"values": {"blocked_terms": ["  "]}}, "Blocked phrases"),
        ("task_routing", {"values": {"routes": [{"task": "x", "model": "nope"}]}}, "Check"),
        ("task_routing", {"values": {"routes": [{"task": "x"}]}}, "Check"),
    ],
)
def test_invalid_feature_settings_change_nothing(gateway, feature, body, expected):
    before = gateway.app.state.settings
    response = put(gateway, feature, **body)
    assert response.status_code == 422
    assert expected in response.json()["error"]["message"]
    assert gateway.app.state.settings is before


def test_stale_feature_saves_are_refused_and_changes_reach_history(gateway):
    _, etag = features(gateway)
    assert put(gateway, "response_cache", etag=etag, enabled=True).status_code == 200
    assert put(gateway, "response_cache", etag=etag, enabled=False).status_code == 409
    revisions = gateway.get("/admin/api/configuration/revisions", headers=ADMIN).json()["items"]
    assert revisions[0]["action"] == "feature.response_cache.updated"
    events = gateway.get("/admin/api/management-events", headers=ADMIN).json()["items"]
    assert any(item["action"] == "feature.response_cache.updated" for item in events)


def test_every_feature_belongs_to_a_capability_and_none_is_empty(gateway):
    body = gateway.get("/admin/api/features", headers=ADMIN).json()
    capabilities = {item["id"] for item in body["capabilities"]}
    used = {item["group"] for item in body["items"]}
    assert used == capabilities


def test_features_managed_elsewhere_point_at_a_console_page(gateway):
    items = gateway.get("/admin/api/features", headers=ADMIN).json()["items"]
    links = {item["link"] for item in items if item.get("link")}
    source = (Path(__file__).parents[1] / "console/src/App.tsx").read_text()
    assert links and all(f'case "{link}":' in source for link in links)
