"""Exercise real launcher processes with isolated storage, never a user's instance."""

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux/WSL lifecycle scripts")


@pytest.fixture
def runner(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {
        **os.environ,
        "GATEWAY_PYTHON": sys.executable,
        "GATEWAY_PORT": str(port),
        "GATEWAY_RUN_DIR": str(tmp_path / "runtime"),
        "GATEWAY_DATA_DIR": str(tmp_path / "data"),
    }
    env.pop("GATEWAY_ADMIN_API_KEY", None)

    def invoke(action, *args, root=ROOT):
        return subprocess.run(
            [str(root / f"{action}.sh"), *args],
            cwd=tmp_path,
            env=env,
            text=True,
            capture_output=True,
            timeout=40,
        )

    yield invoke, env
    invoke("stop")


def test_start_duplicate_stop_restart_preserves_storage(runner):
    invoke, env = runner
    started = invoke("start")
    assert started.returncode == 0, started.stderr
    assert f"localhost:{env['GATEWAY_PORT']}/admin" in started.stdout
    data = Path(env["GATEWAY_DATA_DIR"])
    key = (data / "admin.key").read_text()
    runtime = Path(env["GATEWAY_RUN_DIR"])
    state = (runtime / "process.state").read_text()
    assert (runtime / "gateway.log").stat().st_mode & 0o777 == 0o600
    assert runtime.stat().st_mode & 0o777 == 0o700
    assert key.strip() in started.stdout
    assert key.strip() not in state
    assert invoke("start").returncode == 0
    assert (runtime / "process.state").read_text() == state
    status = invoke("status")
    assert status.returncode == 0
    assert key.strip() not in status.stdout
    assert invoke("stop").returncode == 0
    assert invoke("status").returncode == 3
    assert invoke("stop").returncode == 0
    assert (data / "control.db").exists()
    assert invoke("start").returncode == 0
    assert (data / "admin.key").read_text() == key


def test_occupied_port_never_adopts_other_service(runner):
    invoke, env = runner
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", int(env["GATEWAY_PORT"])))
        listener.listen()
        started = invoke("start")
        assert started.returncode == 1
        assert "did not start" in started.stderr
        assert not (Path(env["GATEWAY_RUN_DIR"]) / "process.state").exists()
        assert invoke("stop").returncode == 0
        # The unrelated listener remains usable after both actions.
        with socket.create_connection(listener.getsockname(), timeout=1):
            pass


def test_stale_state_never_kills_foreign_process(runner):
    invoke, env = runner
    assert invoke("stop").returncode == 0
    state = Path(env["GATEWAY_RUN_DIR"]) / "process.state"
    with subprocess.Popen(["sleep", "60"]) as foreign:
        try:
            ticks = Path(f"/proc/{foreign.pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]
            state.write_text(f"{foreign.pid}\t{ticks}\t{'0' * 64}\t8080\n")
            state.chmod(0o600)
            assert invoke("stop").returncode == 0
            assert foreign.poll() is None
            assert not state.exists()
        finally:
            foreign.terminate()


def test_rejects_unsafe_runtime_files(runner, tmp_path):
    invoke, env = runner
    assert invoke("stop").returncode == 0
    target = tmp_path / "keep.txt"
    target.write_text("preserve this file")
    (Path(env["GATEWAY_RUN_DIR"]) / "gateway.log").symlink_to(target)
    result = invoke("start")
    assert result.returncode == 1
    assert "private regular files" in result.stderr
    assert target.read_text() == "preserve this file"
    (Path(env["GATEWAY_RUN_DIR"]) / "gateway.log").unlink()


def test_port_validation_and_help(runner):
    invoke, _ = runner
    assert invoke("start", "--port", "0").returncode == 1
    assert invoke("start", "--port", "65536").returncode == 1
    assert invoke("start", "--help").returncode == 0


def test_default_gateway_sequence_skips_first_two_busy_ports(runner):
    invoke, env = runner
    env.pop("GATEWAY_PORT")
    listeners = []
    try:
        for port in (8087, 8187):
            listener = socket.socket()
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("127.0.0.1", port))
                listener.listen()
            except OSError:
                listener.close()
                continue  # An existing service already occupies this candidate.
            listeners.append(listener)
        started = invoke("start")
        assert started.returncode == 0, started.stderr
        state = Path(env["GATEWAY_RUN_DIR"]) / "process.state"
        selected = int(state.read_text().strip().split("\t")[-1])
        assert selected >= 8287 and (selected - 8087) % 100 == 0
    finally:
        invoke("stop")
        for listener in listeners:
            listener.close()


def test_standalone_fallback(runner, tmp_path):
    bundle = ROOT / "dist" / "m87-gateway"
    if not bundle.exists():
        pytest.skip("Experimental Linux bundle has not been built")
    invoke, env = runner
    checkout = tmp_path / "bundle-checkout"
    (checkout / "scripts").mkdir(parents=True)
    (checkout / "dist").mkdir()
    for name in ("start.sh", "stop.sh", "status.sh", "scripts/gateway-lifecycle.sh"):
        shutil.copy2(ROOT / name, checkout / name)
    (checkout / "dist" / "m87-gateway").symlink_to(bundle)
    env.pop("GATEWAY_PYTHON")
    try:
        started = invoke("start", root=checkout)
        assert started.returncode == 0, started.stderr
        assert invoke("status", root=checkout).returncode == 0
    finally:
        assert invoke("stop", root=checkout).returncode == 0
