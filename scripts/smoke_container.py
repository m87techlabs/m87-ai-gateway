"""Check the real image through run and Compose, using isolated synthetic inference."""

import argparse
import json
import os
import subprocess
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from smoke_standalone import Inference

ROOT = Path(__file__).resolve().parents[1]


def exercise(image):
    identity = "gateway-check-" + uuid.uuid4().hex[:12]
    volume, container = identity + "-data", identity + "-run"
    backend = ThreadingHTTPServer(("0.0.0.0", 0), Inference)
    worker = threading.Thread(target=backend.serve_forever, daemon=True)
    worker.start()
    environment = {**os.environ, "GATEWAY_IMAGE": image, "GATEWAY_PORT": "0"}
    compose = ["docker", "compose", "-p", identity, "-f", str(ROOT / "docker-compose.yml")]
    base = ""

    def docker(*arguments):
        return subprocess.check_output(["docker", *arguments], text=True, timeout=90).strip()

    def composition(*arguments):
        return subprocess.check_output(
            [*compose, *arguments], env=environment, text=True, timeout=90
        ).strip()

    def call(path, method="GET", body=None, key=None):
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            base + path,
            method=method,
            headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        with urlopen(request, timeout=10) as response:
            payload = response.read()
            return (
                json.loads(payload)
                if "json" in response.headers.get("Content-Type", "")
                else payload
            )

    def wait():
        for _ in range(100):
            try:
                if call("/health")["status"] == "ok":
                    return
            except (URLError, TimeoutError):
                time.sleep(0.2)
        raise AssertionError("Container did not become healthy")

    def publish_port(name):
        return "http://" + docker("port", name, "8087/tcp").splitlines()[0]

    def check_fresh():
        assert b"Gateway Console" in call("/")
        try:
            call("/ready")
            raise AssertionError("Unconfigured gateway reported ready")
        except HTTPError as error:
            assert error.code == 503
        try:
            call("/admin/api/setup")
            raise AssertionError("Admin access was unprotected")
        except HTTPError as error:
            assert error.code == 401
        try:
            call(
                "/v1/chat/completions",
                "POST",
                {"model": "auto", "messages": [{"role": "user", "content": "hello"}]},
            )
            raise AssertionError("Application authentication was unprotected")
        except HTTPError as error:
            assert error.code == 401

    try:
        docker("volume", "create", volume)
        docker(
            "run",
            "-d",
            "--name",
            container,
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--add-host=host.docker.internal:host-gateway",
            "-p",
            "127.0.0.1::8087",
            "--mount",
            f"source={volume},target=/data",
            image,
        )
        base = publish_port(container)
        wait()
        check_fresh()
        assert docker("exec", container, "id", "-u") == "10001"
        assert docker("exec", container, "stat", "-c", "%a", "/data/gateway") == "700"
        admin = docker("exec", container, "cat", "/data/gateway/admin.key")
        model = "openai_compatible:synthetic-model"
        path = "/admin/api/connections/openai_compatible"
        call(
            path,
            "PUT",
            {
                "config": {"base_url": f"http://host.docker.internal:{backend.server_port}/v1"},
                "key": "synthetic-provider-key",
            },
            admin,
        )
        assert call(path + "/models", key=admin)["items"] == [model]
        call("/admin/api/setup", "PUT", {"default_model": model, "capture_content": True}, admin)
        app = call(
            "/admin/api/apps",
            "POST",
            {"app_id": "container-check", "allowed_models": ["auto", model]},
            admin,
        )
        request = {"model": "auto", "messages": [{"role": "user", "content": "synthetic prompt"}]}
        assert (
            call("/v1/chat/completions", "POST", request, app["api_key"])["usage"]["total_tokens"]
            == 6
        )
        for _ in range(50):
            events = call("/admin/api/logs", key=admin)["items"]
            if events:
                break
            time.sleep(0.1)
        assert events
        detail = call("/admin/api/logs/" + events[0]["request_id"], key=admin)
        assert "synthetic prompt" in json.dumps(detail["request_content"])
        assert "synthetic answer" in json.dumps(detail["response_content"])
        for secret in (
            admin,
            app["api_key"],
            "synthetic-provider-key",
            "synthetic prompt",
            "synthetic answer",
        ):
            assert secret not in docker("logs", container)
        for _ in range(100):
            status = docker("inspect", "--format", "{{.State.Health.Status}}", container)
            if status == "healthy":
                break
            time.sleep(0.2)
        assert status == "healthy"
        docker("stop", "--time", "60", container)
        assert docker("inspect", "--format", "{{.State.ExitCode}}", container) == "0"
        docker("rm", container)
        # Recreate, rather than merely restart, to prove the volume preserves credentials and logs.
        docker(
            "run",
            "-d",
            "--name",
            container,
            "--add-host=host.docker.internal:host-gateway",
            "-p",
            "127.0.0.1::8087",
            "--mount",
            f"source={volume},target=/data",
            image,
        )
        base = publish_port(container)
        wait()
        assert docker("exec", container, "cat", "/data/gateway/admin.key") == admin
        assert call("/ready")["status"] == "ready"
        assert call("/admin/api/logs", key=admin)["items"]
        assert (
            call("/v1/chat/completions", "POST", request, app["api_key"])["usage"]["total_tokens"]
            == 6
        )
        composition("config", "--quiet")
        composition("up", "-d", "--pull", "never")
        service = composition("ps", "-q", "m87-ai-gateway")
        base = publish_port(service)
        wait()
        check_fresh()
        compose_admin = docker("exec", service, "cat", "/data/gateway/admin.key")
        composition("down", "--timeout", "60")
        composition("up", "-d", "--pull", "never")
        service = composition("ps", "-q", "m87-ai-gateway")
        base = publish_port(service)
        wait()
        assert docker("exec", service, "cat", "/data/gateway/admin.key") == compose_admin
        print("Container run/Compose, host inference, logs, tokens, recreation and shutdown passed")
    finally:
        subprocess.run(
            [*compose, "down", "--volumes", "--timeout", "60"], env=environment, timeout=90
        )
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30)
        subprocess.run(["docker", "volume", "rm", volume], capture_output=True, timeout=30)
        backend.shutdown()
        backend.server_close()
        worker.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    exercise(parser.parse_args().image)
