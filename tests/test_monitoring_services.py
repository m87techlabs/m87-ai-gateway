"""Native helper ownership, private state and repeatable local configuration."""

import argparse
import json
import os
import platform
import subprocess
import sys

import pytest

from scripts import monitoring_services as services

pytestmark = pytest.mark.skipif(platform.system() != "Linux", reason="Linux/WSL helper")


@pytest.fixture(autouse=True)
def restore_umask():
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


def test_stop_preserves_unrelated_process_with_reused_or_stale_pid():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        state = {"grafana": {"pid": process.pid, "identity": ["stale", "digest"], "port": 3000}}
        assert not services.owned(state["grafana"])
        services.stop(state)
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_stop_targets_only_owned_process():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        item = {"pid": process.pid, "identity": services.identity(process.pid), "port": 3000}
        assert services.owned(item)
        services.stop({"grafana": item})
        assert process.wait(timeout=5) < 0
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)


def test_private_directory_file_and_symlink_rejection(tmp_path):
    base = tmp_path / "private"
    services.private_directory(base)
    secret = base / "password"
    services.private_file(secret, "synthetic-secret")
    assert secret.stat().st_mode & 0o077 == 0
    alias = base / "alias"
    alias.symlink_to(secret)
    with pytest.raises(ValueError, match="symlinks"):
        services.private_file(alias, "changed")
    assert secret.read_text() == "synthetic-secret"
    secret.chmod(0o644)
    with pytest.raises(ValueError, match="600"):
        services.private_file(secret)


def test_install_rejects_checksum_mismatch_without_extracting(tmp_path):
    services.private_directory(tmp_path / "downloads")
    (tmp_path / "downloads/grafana.tar.gz").write_bytes(b"invalid")
    with pytest.raises(ValueError, match="checksum mismatch"):
        services.install(tmp_path, "grafana", False)
    assert not (tmp_path / "tools/grafana-13.2.4").exists()


def test_missing_tools_do_not_trigger_download_without_install(tmp_path):
    with pytest.raises(ValueError, match="--install"):
        services.install(tmp_path, "grafana", False)
    assert not (tmp_path / "downloads/grafana.tar.gz").exists()


def test_configuration_is_loopback_only_private_and_preserves_password(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "get", lambda url: {"service": "m87-ai-gateway"})

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return b"# m87_gateway_requests_total"

    class Opener:
        def open(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(services, "build_opener", lambda *args: Opener())
    ports = {"grafana": 3001, "prometheus": 9091}
    services.configure(tmp_path, "http://127.0.0.1:8187", ports)
    password = (tmp_path / "grafana-admin-password").read_text()
    services.configure(tmp_path, "http://127.0.0.1:8187", ports)
    assert (tmp_path / "grafana-admin-password").read_text() == password
    assert password.strip() not in (tmp_path / "config/grafana.ini").read_text()
    config = json.loads((tmp_path / "config/prometheus.json").read_text())
    assert config["scrape_configs"][0]["static_configs"][0]["targets"] == ["127.0.0.1:8187"]
    datasources = json.loads((tmp_path / "config/datasources/m87.yaml").read_text())
    assert datasources["datasources"][0]["url"] == "http://127.0.0.1:9091"
    assert not (tmp_path / "config/dashboard-json/gateway-logs.json").exists()
    assert "http_addr = 127.0.0.1" in (tmp_path / "config/grafana.ini").read_text()
    with pytest.raises(ValueError, match="loopback"):
        services.configure(tmp_path, "http://secret@remote.example.com", ports)


def test_status_does_not_adopt_process_or_alter_state(tmp_path, capsys):
    services.private_file(tmp_path / "processes.json", "{}")
    args = argparse.Namespace(action="status", data_dir=str(tmp_path))
    assert services.run(args) == 3
    assert (tmp_path / "processes.json").read_text() == "{}"


def test_managed_gateway_fallback_port_requires_matching_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_RUN_DIR", str(tmp_path))
    ticks, digest = services.identity(os.getpid())
    state = tmp_path / "process.state"
    state.write_text(f"{os.getpid()}\t{ticks}\t{digest}\t8187\n")
    assert services.managed_gateway_url() == "http://127.0.0.1:8187"
    state.write_text(f"{os.getpid()}\tstale\t{digest}\t8187\n")
    assert services.managed_gateway_url() == "http://127.0.0.1:8087"
