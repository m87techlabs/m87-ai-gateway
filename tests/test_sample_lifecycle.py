import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux/WSL lifecycle")


def test_sample_background_lifecycle_and_private_key(tmp_path):
    key = "synthetic-sample-lifecycle-key"
    env = {
        **os.environ,
        "SAMPLE_APP_KEY": key,
        "SAMPLE_RUN_DIR": str(tmp_path / "sample"),
        "GATEWAY_RUN_DIR": str(tmp_path / "gateway"),
        "GATEWAY_DATA_DIR": str(tmp_path / "data"),
        "GATEWAY_PYTHON": sys.executable,
        "SAMPLE_GATEWAY_URL": "http://127.0.0.1:1",
    }
    env.pop("SAMPLE_PORT", None)
    env.pop("GATEWAY_PORT", None)

    def call(action):
        return subprocess.run(
            [str(ROOT / "examples/chat_app" / f"{action}.sh")],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=40,
        )

    try:
        start = call("start")
        assert start.returncode == 0, start.stderr
        state = Path(env["SAMPLE_RUN_DIR"]) / "process.state"
        record = state.read_text()
        port = int(record.strip().split("\t")[-1])
        assert 1 <= port <= 65535
        assert f"localhost:{port}" in start.stdout
        assert key not in start.stdout and key not in record
        assert state.stat().st_mode & 0o777 == 0o600
        assert not Path(env["GATEWAY_RUN_DIR"]).exists()
        with httpx.Client(trust_env=False) as client:
            assert client.get(f"http://127.0.0.1:{port}/").status_code == 200
        env.pop("SAMPLE_APP_KEY")
        assert call("start").returncode == 0  # No second prompt or process.
        assert state.read_text() == record
        assert call("status").returncode == 0
        assert call("stop").returncode == 0
        assert call("stop").returncode == 0
        assert call("status").returncode == 3
    finally:
        call("stop")


@pytest.mark.parametrize("key", ["", "Bearer synthetic-private-key", "synthetic\nprivate-key"])
def test_invalid_key_fails_before_launch_with_clear_private_message(tmp_path, key):
    env = {
        **os.environ,
        "SAMPLE_APP_KEY": key,
        "SAMPLE_RUN_DIR": str(tmp_path / "sample"),
        "GATEWAY_PYTHON": sys.executable,
    }
    result = subprocess.run(
        [str(ROOT / "examples/chat_app/start.sh")],
        env=env,
        input="\n",
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 1
    assert "empty or contains whitespace" in result.stderr
    assert "port" not in result.stderr.lower()
    assert "synthetic-private-key" not in result.stderr
    assert not (tmp_path / "sample/process.state").exists()


def test_missing_key_input_reports_how_to_supply_it(tmp_path):
    env = {
        **os.environ,
        "SAMPLE_RUN_DIR": str(tmp_path / "sample"),
        "GATEWAY_PYTHON": sys.executable,
    }
    env.pop("SAMPLE_APP_KEY", None)
    result = subprocess.run(
        [str(ROOT / "examples/chat_app/start.sh")],
        env=env,
        input="",
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 1
    assert "input was unavailable" in result.stderr
    assert not (tmp_path / "sample/process.state").exists()
