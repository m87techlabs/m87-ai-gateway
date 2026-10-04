"""Lifecycle preflight and preservation checks without a Docker daemon."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name == "nt", reason="Bash workstation helpers")


@pytest.fixture
def runner(tmp_path):
    executable = tmp_path / "docker"
    log = tmp_path / "calls.jsonl"
    executable.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, sys
args = sys.argv[1:]
with open(os.environ["DOCKER_TEST_LOG"], "a") as output:
    output.write(json.dumps(args) + "\\n")
if args == ["--version"]:
    sys.exit(0)
if args[0] == "info":
    if os.getenv("DOCKER_TEST_OFFLINE"):
        sys.exit(1)
    print("linux/amd64")
elif args[0] == "inspect":
    template = args[2]
    if "HostPort" in template:
        print("8187")
    elif "Running" in template and "Health" in template:
        print("true/healthy")
    elif "Running" in template:
        print("true")
    else:
        print("healthy")
elif args[:2] == ["compose", "version"]:
    print("Docker Compose version v2")
elif args[:2] in (["compose", "up"], ["compose", "start"]):
    print("--wait --wait-timeout")
elif args[0] == "compose":
    for operation in ("config", "ps", "port", "pull", "build", "up", "start", "stop"):
        if operation in args:
            if operation == "ps" and "-q" in args and os.getenv("DOCKER_TEST_EXISTING"):
                print("synthetic-container")
            if operation == "port":
                print("127.0.0.1:" + os.environ.get("GATEWAY_PORT", "8087"))
            if operation == "pull" and os.getenv("DOCKER_TEST_DENIED"):
                sys.exit(1)
            break
else:
    sys.exit(2)
"""
    )
    executable.chmod(0o700)

    def run(action, *options, **overrides):
        environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith(("GATEWAY_", "COMPOSE_", "DOCKER_TEST_"))
        }
        environment.update(
            PATH=str(tmp_path) + os.pathsep + os.environ["PATH"],
            DOCKER_TEST_LOG=str(log),
            **overrides,
        )
        result = subprocess.run(
            ["bash", str(ROOT / f"docker-{action}.sh"), *options],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    return run


def test_engine_unavailable_blocks_mutations(runner):
    result, calls = runner("start", DOCKER_TEST_OFFLINE="1")
    assert result.returncode == 1
    assert "Start Docker Desktop/Engine" in result.stderr
    assert not any("pull" in call or "up" in call or "build" in call for call in calls)


def test_invalid_port_fails_before_docker(runner):
    result, calls = runner("start", "--port", "65536")
    assert result.returncode == 1
    assert "Port must be" in result.stderr
    assert calls == []


def test_private_registry_failure_prevents_start(runner):
    result, calls = runner("start", DOCKER_TEST_DENIED="1")
    assert result.returncode == 1
    assert "docker login ghcr.io" in result.stderr
    assert not any("-d" in call for call in calls)


def test_start_from_any_directory_checks_health_without_printing_key(runner):
    result, calls = runner("start", "--port", "8287")
    assert result.returncode == 0
    assert "http://127.0.0.1:8287" in result.stdout
    assert any("pull" in call for call in calls)
    assert any("up" in call and "--wait-timeout" in call and "90" in call for call in calls)
    assert not any("exec" in call for call in calls)
    assert all("m87-ai-gateway" in call for call in calls if "--project-directory" in call)


def test_resume_preserves_existing_port_and_image(runner):
    result, calls = runner("start", DOCKER_TEST_EXISTING="1")
    assert result.returncode == 0
    assert "http://127.0.0.1:8187" in result.stdout
    assert any("start" in call and "--help" not in call for call in calls)
    assert not any("start" in call and "--wait-timeout" in call for call in calls)
    assert not any("pull" in call or "-d" in call or "build" in call for call in calls)


def test_source_build_avoids_registry_pull(runner):
    result, calls = runner("start", "--build")
    assert result.returncode == 0
    assert any("build" in call for call in calls)
    assert not any("pull" in call for call in calls)
    assert any(str(ROOT / "docker-compose.build.yml") in call for call in calls)


def test_stop_preserves_data_and_only_targets_gateway(runner):
    result, calls = runner("stop", DOCKER_TEST_EXISTING="1")
    assert result.returncode == 0
    assert "logs remain in its volume" in result.stdout
    stop = next(call for call in calls if "stop" in call)
    assert stop[-1] == "m87-ai-gateway"
    assert not any("down" in call or "rm" in call or "--volumes" in call for call in calls)


def test_status_absent_service_returns_stopped(runner):
    result, calls = runner("status")
    assert result.returncode == 3
    assert "No gateway container" in result.stdout
    assert not any("start" in call or "stop" in call for call in calls)
