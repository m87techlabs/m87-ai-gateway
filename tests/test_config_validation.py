import pytest
from fastapi.testclient import TestClient

from m87_gateway.config import GatewaySettings, load_settings
from m87_gateway.main import create_app


@pytest.mark.parametrize(
    "yaml_text",
    [
        "[]",
        "server: {port: 0}",
        "routing: {default_model: auto}",
        "routing: {default_model: unknown:model}",
        "unknown_option: true",
        "guardrails: {blocklist: {blocked_terms: ['']}}",
        "providers: {ollama: {base_url: 'file:///private'}}",
        "providers: {ollama: {base_url: 'http://user:secret@host'}}",
        "providers: {ollama: {base_url: 'http://host:invalid'}}",
        "providers: {ollama: {timeout_seconds: 0}}",
        "providers: {openai: {api_key_env: 'invalid env'}}",
        "providers: []",
        "routing: {rules: [{when_task: code, route_to: auto}]}",
        "routing: {rules: [{route_to: 'ollama:test'}]}",
        "observability: {traffic_log: {capture_content: true}}",
        "apps: [{app_id: test, api_key: 'has whitespace'}]",
        "apps: [{app_id: test, api_key: first}, {app_id: test, api_key: second}]",
        "apps: [{app_id: one, api_key: same}, {app_id: two, api_key: same}]",
    ],
)
def test_invalid_configuration_fails_closed(tmp_path, yaml_text):
    path = tmp_path / "config.yaml"
    path.write_text(yaml_text)
    with pytest.raises(ValueError):
        load_settings(path)


@pytest.mark.parametrize("layout", ["apps", "auth-key", "auth-api-key"])
def test_app_override_removes_old_key_in_every_supported_layout(tmp_path, monkeypatch, layout):
    import yaml

    record = {"app_id": "test", "allowed_models": ["auto", "ollama:test"]}
    record["key" if layout == "auth-key" else "api_key"] = "old-test-secret"
    data = {"apps": [record]} if layout == "apps" else {"auth": {"api_keys": [record]}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setenv("GATEWAY_APP_API_KEY", "new-test-secret")
    monkeypatch.setenv("GATEWAY_ALLOWED_MODELS", "")
    settings = load_settings(path)
    assert settings.app_for_api_key("old-test-secret") is None
    assert settings.app_for_api_key("new-test-secret").allowed_models == []


def test_explicit_missing_config_fails(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        load_settings(tmp_path / "missing.yaml")


def test_no_implicit_ancestor_demo_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_settings().configured_apps == []


def test_provider_endpoint_environment_override_validated(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("providers: {ollama: {base_url_env: CUSTOM_MODEL_URL}}")
    monkeypatch.setenv("CUSTOM_MODEL_URL", "http://provider.example.invalid:11434/")
    assert load_settings(path).providers.ollama.base_url == "http://provider.example.invalid:11434"
    monkeypatch.setenv("CUSTOM_MODEL_URL", "not-a-url")
    with pytest.raises(ValueError):
        load_settings(path)


def test_legacy_routing_alias_can_be_overridden(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("routing: {default: 'ollama:old'}")
    monkeypatch.setenv("GATEWAY_DEFAULT_MODEL", "ollama:new")
    assert load_settings(path).routing.default_model == "ollama:new"


def test_startup_error_does_not_expose_config_inputs(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(
        "apps: [{app_id: test, api_key: 'synthetic-private-secret', unexpected: sensitive}]"
    )
    monkeypatch.setenv("M87_GATEWAY_CONFIG", str(path))
    with pytest.raises(RuntimeError) as failure:
        with TestClient(create_app()):
            pass
    assert "synthetic-private-secret" not in str(failure.value)


def test_app_secret_is_excluded_from_repr():
    settings = GatewaySettings.model_validate(
        {"apps": [{"app_id": "test", "api_key": "private-test-key"}]}
    )
    assert "private-test-key" not in repr(settings)


@pytest.mark.parametrize(
    "yaml_text",
    [
        "apps: {bad: shape}",
        "auth: []",
        "auth: {api_keys: {bad: shape}}",
        "auth: {api_keys: [bad-shape]}",
    ],
)
def test_app_environment_override_rejects_malformed_collections(tmp_path, monkeypatch, yaml_text):
    path = tmp_path / "config.yaml"
    path.write_text(yaml_text)
    monkeypatch.setenv("GATEWAY_APP_API_KEY", "new-test-secret")
    with pytest.raises(ValueError):
        load_settings(path)
