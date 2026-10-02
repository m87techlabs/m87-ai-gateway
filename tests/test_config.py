from m87_gateway.config import load_settings


def test_loads_auth_api_keys_from_yaml(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
auth:
  api_keys:
    - key: "test-key"
      app_id: "test-app"
      allowed_models:
        - "auto"
routing:
  default_model: "ollama:test-model"
""",
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    app = settings.app_for_api_key("test-key")
    assert app is not None
    assert app.app_id == "test-app"
    assert app.allowed_models == ["auto"]
    assert settings.routing.default_model == "ollama:test-model"


def test_environment_overrides_first_app_api_key(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
auth:
  api_keys:
    - key: "old-key"
      app_id: "old-app"
      allowed_models:
        - "auto"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("GATEWAY_APP_API_KEY", "env-key")
    monkeypatch.setenv("GATEWAY_APP_ID", "env-app")
    monkeypatch.setenv("GATEWAY_ALLOWED_MODELS", "auto,openai:gpt-4.1-mini")

    settings = load_settings(config_path)

    assert settings.app_for_api_key("old-key") is None
    app = settings.app_for_api_key("env-key")
    assert app is not None
    assert app.app_id == "env-app"
    assert app.allowed_models == ["auto", "openai:gpt-4.1-mini"]


def test_control_plane_and_content_environment_overrides(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GATEWAY_APP_API_KEY", "local-app-key")
    monkeypatch.setenv("GATEWAY_APP_CAPTURE_CONTENT", "true")
    monkeypatch.setenv("GATEWAY_CAPTURE_CONTENT", "true")
    monkeypatch.setenv("GATEWAY_CONTROL_PLANE_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_CONTROL_PLANE_DATABASE_PATH", "private/control.db")
    monkeypatch.setenv("GATEWAY_CONTROL_PLANE_MASTER_KEY_PATH", "private/master.key")
    monkeypatch.setenv("GATEWAY_CONTROL_PLANE_RETENTION_DAYS", "14")

    settings = load_settings(path)

    assert settings.control_plane.enabled is True
    assert settings.control_plane.database_path == "private/control.db"
    assert settings.control_plane.master_key_path == "private/master.key"
    assert settings.control_plane.retention_days == 14
    assert settings.observability.traffic_log.capture_content is True
    assert settings.configured_apps[0].capture_content is True
