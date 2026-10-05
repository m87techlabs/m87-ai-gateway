"""Exercise a bundled gateway against a synthetic local inference service."""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class Inference(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, body):
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        self.reply({"data": [{"id": "synthetic-model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["model"] == "synthetic-model"
        assert self.headers["Authorization"] == "Bearer synthetic-provider-key"
        self.reply(
            {
                "id": "chatcmpl-bundle",
                "object": "chat.completion",
                "created": 1,
                "model": "synthetic-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "synthetic answer"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            }
        )


def exercise(executable):
    with tempfile.TemporaryDirectory(prefix="gateway-bundle-check-") as temporary:
        data_dir = Path(temporary) / "data"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        inference = ThreadingHTTPServer(("127.0.0.1", 0), Inference)
        worker = threading.Thread(target=inference.serve_forever, daemon=True)
        worker.start()
        base_url = f"http://127.0.0.1:{port}"
        environ = dict(os.environ)
        for name in ("GATEWAY_ADMIN_API_KEY", "PYTHONPATH", "PYTHONHOME"):
            environ.pop(name, None)
        process = None

        def call(path, method="GET", body=None, key=None):
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            if body is not None:
                headers["Content-Type"] = "application/json"
            request = Request(
                base_url + path,
                method=method,
                headers=headers,
                data=json.dumps(body).encode() if body is not None else None,
            )
            with urlopen(request, timeout=5) as response:
                payload = response.read()
                return (
                    json.loads(payload)
                    if payload and "json" in response.headers.get("Content-Type", "")
                    else payload
                )

        def launch(output):
            running = subprocess.Popen(
                [
                    str(executable),
                    "--data-dir",
                    str(data_dir),
                    "--port",
                    str(port),
                    "--hide-admin-key",
                ],
                env=environ,
                stdout=output,
                stderr=output,
            )
            for _ in range(100):
                if running.poll() is not None:
                    raise RuntimeError("Standalone gateway exited during startup")
                try:
                    if call("/health")["status"] == "ok":
                        return running
                except (URLError, TimeoutError):
                    time.sleep(0.1)
            running.terminate()
            running.wait(timeout=10)
            raise RuntimeError("Standalone gateway failed to start")

        try:
            with (Path(temporary) / "process.log").open("wb") as output:
                process = launch(output)
                admin = (data_dir / "admin.key").read_text().strip()
                assert admin.encode() not in (Path(temporary) / "process.log").read_bytes()
                assert b"Gateway Console" in call("/admin")
                assert b"loadSetup" in call("/admin/assets/app.js")
                try:
                    call("/admin/api/setup")
                    raise AssertionError("Admin access was not protected")
                except HTTPError as error:
                    assert error.code == 401
                path = "/admin/api/connections/openai_compatible"
                call(
                    path,
                    "PUT",
                    {
                        "config": {"base_url": f"http://127.0.0.1:{inference.server_port}/v1"},
                        "key": "synthetic-provider-key",
                    },
                    admin,
                )
                assert call(
                    path + "/test",
                    "POST",
                    {"config": {"base_url": f"http://127.0.0.1:{inference.server_port}/v1"}},
                    admin,
                )["ok"]
                assert call(path + "/models", key=admin)["items"] == [
                    "openai_compatible:synthetic-model"
                ]
                model = "openai_compatible:synthetic-model"
                call(
                    "/admin/api/projects",
                    "POST",
                    {"project_id": "bundle-project", "name": "Bundle project"},
                    admin,
                )
                call(
                    "/admin/api/setup",
                    "PUT",
                    {"default_model": model, "capture_content": True},
                    admin,
                )
                app = call(
                    "/admin/api/apps",
                    "POST",
                    {
                        "app_id": "bundle-check",
                        "project_id": "bundle-project",
                        "allowed_models": ["auto", "ollama:legacy-model"],
                        "capture_content": False,
                    },
                    admin,
                )
                call(
                    "/admin/api/apps/bundle-check/models",
                    "PATCH",
                    {"allowed_models": ["auto", model]},
                    admin,
                )
                controls = call("/admin/api/controls", key=admin)
                controls["cache"]["enabled"] = True
                controls["limits"]["max_concurrent_requests"] = 8
                controls["retention_days"] = 90
                call("/admin/api/controls", "PUT", controls, admin)
                call(
                    "/admin/api/apps/bundle-check/limits",
                    "PATCH",
                    {
                        "rate_limit_per_minute": 10,
                        "max_concurrent_requests": 2,
                    },
                    admin,
                )
                process.terminate()
                process.wait(timeout=10)
                process = launch(output)
                assert call("/admin/api/controls", key=admin) == controls
                assert call("/ready")["status"] == "ready"
                assert call("/admin/api/diagnostics", key=admin)["ready"]
                response = call(
                    "/v1/chat/completions",
                    "POST",
                    {
                        "model": "auto",
                        "messages": [{"role": "user", "content": "synthetic prompt"}],
                    },
                    app["api_key"],
                )
                assert response["usage"]["total_tokens"] == 6
                events = []
                # The response reaches the client before middleware finishes its audit write.
                for _ in range(50):
                    events = call("/admin/api/logs", key=admin)["items"]
                    if events:
                        break
                    time.sleep(0.1)
                assert events, "Completion audit event was not persisted"
                detail = call("/admin/api/logs/" + events[0]["request_id"], key=admin)
                assert detail["response_content"][0]["message"]["content"] == "synthetic answer"
                assert detail["project_id"] == "bundle-project"
                summary = call("/admin/api/overview?project_id=bundle-project", key=admin)
                assert summary["total_tokens"] == 6
                usage = call("/admin/api/usage?project_id=bundle-project", key=admin)
                assert sum(item["requests"] for item in usage["series"]) == 1
                assert b"synthetic-provider-key" not in (data_dir / "control.db").read_bytes()

                def native(*arguments):
                    result = subprocess.run(
                        [str(executable), "--data-dir", str(data_dir), *arguments],
                        env={**environ, "GATEWAY_BACKUP_PASSWORD": "synthetic-backup-password"},
                        capture_output=True,
                        timeout=40,
                    )
                    assert result.returncode == 0, "Standalone management operation failed"
                    assert admin.encode() not in result.stdout

                native("--status")
                native("--stop")
                process.wait(timeout=10)
                archive = Path(temporary) / "backups" / "gateway.backup"
                native("--backup", str(archive))
                assert b"synthetic-provider-key" not in archive.read_bytes()
                data_dir = Path(temporary) / "restored"
                native("--restore", str(archive))
                process = launch(output)
                assert call("/ready")["status"] == "ready"
                assert call("/admin/api/controls", key=admin) == controls
                response = call(
                    "/v1/chat/completions",
                    "POST",
                    {
                        "model": "auto",
                        "messages": [{"role": "user", "content": "restore check"}],
                    },
                    app["api_key"],
                )
                assert response["usage"]["total_tokens"] == 6
                native("--stop")
                process.wait(timeout=10)
                print(
                    "Standalone setup, controls, lifecycle, encrypted backup/restore and restored inference passed"
                )
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            inference.shutdown()
            inference.server_close()
            worker.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    arguments = parser.parse_args()
    exercise(arguments.executable.resolve())
