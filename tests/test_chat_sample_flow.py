"""Real app/gateway HTTP boundary with a synthetic inference server and private storage."""

from http.server import ThreadingHTTPServer
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import httpx
import pytest

from scripts.smoke_standalone import Inference

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux/WSL sample launcher")


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_ready(client, path, process):
    for _ in range(100):
        assert process.poll() is None, "Temporary server exited during startup"
        try:
            if client.get(path).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    raise AssertionError("Temporary server did not become ready")


def test_sample_gateway_inference_and_project_logs(tmp_path):
    inference = ThreadingHTTPServer(("127.0.0.1", 0), Inference)
    thread = threading.Thread(target=inference.serve_forever, daemon=True)
    thread.start()
    processes = []
    gateway_port, sample_port = free_port(), free_port()
    data = tmp_path / "data"
    log = tmp_path / "process.log"
    log.touch(mode=0o600)
    environment = {**os.environ}
    environment.pop("GATEWAY_ADMIN_API_KEY", None)
    environment.pop("SAMPLE_GATEWAY_URL", None)
    try:
        with log.open("wb") as output:
            gateway = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "m87_gateway",
                    "--port",
                    str(gateway_port),
                    "--data-dir",
                    str(data),
                ],
                cwd=ROOT,
                env=environment,
                stdout=output,
                stderr=output,
            )
            processes.append(gateway)
            with httpx.Client(base_url=f"http://127.0.0.1:{gateway_port}", timeout=5) as operator:
                wait_ready(operator, "/health", gateway)
                runtime = tmp_path / "runtime"
                runtime.mkdir(mode=0o700)
                process = Path(f"/proc/{gateway.pid}")
                ticks = (process / "stat").read_text().rsplit(") ", 1)[1].split()[19]
                digest = hashlib.sha256((process / "cmdline").read_bytes()).hexdigest()
                state = runtime / "process.state"
                state.write_text(f"{gateway.pid}\t{ticks}\t{digest}\t{gateway_port}\n")
                state.chmod(0o600)
                operator.headers["Authorization"] = (
                    f"Bearer {(data / 'admin.key').read_text().strip()}"
                )

                def save(path, body, method="POST"):
                    response = operator.request(method, "/admin/api/" + path, json=body)
                    response.raise_for_status()
                    return response.json() if response.content else None

                save("projects", {"project_id": "sample-chat", "name": "Sample chat"})
                save(
                    "connections/openai_compatible",
                    {
                        "config": {"base_url": f"http://127.0.0.1:{inference.server_port}/v1"},
                        "key": "synthetic-provider-key",
                    },
                    "PUT",
                )
                model = "openai_compatible:synthetic-model"
                save("setup", {"default_model": model, "capture_content": True}, "PUT")
                app_key = save(
                    "apps",
                    {
                        "app_id": "sample-chat",
                        "project_id": "sample-chat",
                        "allowed_models": ["auto", model],
                        "capture_content": True,
                    },
                )["api_key"]
                sample = subprocess.Popen(
                    [
                        str(ROOT / "examples/chat_app/start.sh"),
                        "--port",
                        str(sample_port),
                    ],
                    cwd=tmp_path,
                    env={
                        **environment,
                        "SAMPLE_APP_KEY": app_key,
                        "GATEWAY_PYTHON": sys.executable,
                        "GATEWAY_RUN_DIR": str(runtime),
                    },
                    stdout=output,
                    stderr=output,
                )
                processes.append(sample)
                with httpx.Client(base_url=f"http://127.0.0.1:{sample_port}", timeout=5) as browser:
                    wait_ready(browser, "/api/status", sample)
                    assert browser.get("/api/status").json()["gateway_reachable"]
                    assert browser.get("/api/status").json()["gateway_url"] == (
                        f"http://127.0.0.1:{gateway_port}"
                    )
                    assert app_key not in browser.get("/").text
                    result = browser.post(
                        "/api/chat",
                        json={"messages": [{"role": "user", "content": "Synthetic question"}]},
                    )
                    assert result.status_code == 200
                    body = result.json()
                    assert body["content"] == "synthetic answer"
                    assert body["usage"]["total_tokens"] == 6
                    request_id = body["request_id"]
                    for _ in range(50):
                        events = operator.get("/admin/api/logs?project_id=sample-chat").json()[
                            "items"
                        ]
                        if any(event["request_id"] == request_id for event in events):
                            break
                        time.sleep(0.02)
                    detail = operator.get(f"/admin/api/logs/{request_id}").json()
                    assert detail["project_id"] == "sample-chat"
                    assert detail["app_id"] == "sample-chat"
                    assert detail["total_tokens"] == 6
                    assert "Synthetic question" in str(detail)
                    assert "synthetic answer" in str(detail)
    finally:
        for process in reversed(processes):
            process.terminate()
            process.wait(timeout=10)
        inference.shutdown()
        inference.server_close()
        thread.join(timeout=5)
