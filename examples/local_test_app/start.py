"""Start a disposable gateway and local browser relay for Windows/WSL testing."""

from __future__ import annotations

import json
from importlib.util import find_spec
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_RUNTIME_MODULES = ("fastapi", "httpx", "m87_gateway", "uvicorn")


def _missing_runtime_modules() -> list[str]:
    return [name for name in REQUIRED_RUNTIME_MODULES if find_spec(name) is None]


def _valid_ollama_model(value: str) -> bool:
    provider, separator, model = value.partition(":")
    return bool(
        separator
        and provider == "ollama"
        and model
        and len(value) <= 200
        and not any(character.isspace() for character in value)
    )


def _ollama_models(base_url: str) -> list[str]:
    try:
        with urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=3) as response:  # noqa: S310
            payload = json.load(response)
    except (OSError, URLError, ValueError):
        return []
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    return sorted(
        model["name"]
        for model in models
        if isinstance(model, dict) and isinstance(model.get("name"), str)
    )


def _gateway_ready(url: str, process: subprocess.Popen, timeout: float = 15) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urlopen(f"{url}/health", timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return True
        except (OSError, URLError):
            time.sleep(0.2)
    return False


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    missing = _missing_runtime_modules()
    if missing:
        print(f"Missing local flow dependencies: {', '.join(missing)}.", file=sys.stderr)
        print("Install them with: python -m pip install -e '.[dev]'", file=sys.stderr)
        return 2

    environment = os.environ.copy()
    ollama_url = environment.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    models = _ollama_models(ollama_url)
    selected = environment.get("LOCAL_TEST_MODEL")
    if selected is None:
        selected = f"ollama:{models[0]}" if models else "ollama:llama3"
    if not _valid_ollama_model(selected):
        print(
            "LOCAL_TEST_MODEL must select an ollama:<model> route for this flow.",
            file=sys.stderr,
        )
        return 2

    gateway_port = int(environment.get("LOCAL_TEST_GATEWAY_PORT", "8080"))
    gateway_url = f"http://127.0.0.1:{gateway_port}"
    ephemeral_key = secrets.token_urlsafe(32)
    admin_key = secrets.token_urlsafe(32)
    control_directory = ROOT / "var" / "lib" / "m87-gateway"
    environment.update(
        {
            "GATEWAY_APP_API_KEY": ephemeral_key,
            "GATEWAY_APP_ID": "local-flow-lab",
            "GATEWAY_ALLOWED_MODELS": f"auto,{selected}",
            "GATEWAY_DEFAULT_MODEL": selected,
            "GATEWAY_APP_CAPTURE_CONTENT": "true",
            "GATEWAY_CAPTURE_CONTENT": "true",
            "GATEWAY_CONTROL_PLANE_ENABLED": "true",
            "GATEWAY_CONTROL_PLANE_DATABASE_PATH": str(control_directory / "control.db"),
            "GATEWAY_CONTROL_PLANE_MASTER_KEY_PATH": str(control_directory / "master.key"),
            "GATEWAY_ADMIN_API_KEY": admin_key,
            "OLLAMA_BASE_URL": ollama_url,
            "M87_GATEWAY_CONFIG": str(ROOT / "config.example.yaml"),
            "LOCAL_TEST_GATEWAY_API_KEY": ephemeral_key,
            "LOCAL_TEST_GATEWAY_URL": gateway_url,
            "LOCAL_TEST_MODEL": "auto",
            "PYTHONPATH": os.pathsep.join(
                filter(None, (str(ROOT / "src"), environment.get("PYTHONPATH")))
            ),
        }
    )

    print(f"Ollama endpoint: {ollama_url}")
    if models:
        print(f"Detected Ollama models: {', '.join(models)}")
    else:
        print(
            "Ollama is unavailable or has no installed models; "
            "error-path testing remains available."
        )
    print(f"Gateway route: {selected}")

    gateway = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "uvicorn",
            "m87_gateway.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(gateway_port),
        ],
        cwd=ROOT,
        env=environment,
        start_new_session=True,
    )
    relay: subprocess.Popen | None = None
    try:
        if not _gateway_ready(gateway_url, gateway):
            print("Gateway did not become healthy.", file=sys.stderr)
            return 1
        relay = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "examples.local_test_app.app"],
            cwd=ROOT,
            env=environment,
            start_new_session=True,
        )
        app_port = environment.get("LOCAL_TEST_PORT", "8787")
        print(f"Open http://localhost:{app_port} in the Windows browser.")
        print(f"Gateway console: {gateway_url}/admin")
        print(f"Admin key (shown once): {admin_key}")
        print("Press Ctrl+C here to stop both local processes.")
        while gateway.poll() is None and relay.poll() is None:
            time.sleep(0.5)
        return gateway.returncode or relay.returncode or 0
    except KeyboardInterrupt:
        return 0
    finally:
        _stop(relay)
        _stop(gateway)


if __name__ == "__main__":
    raise SystemExit(main())
