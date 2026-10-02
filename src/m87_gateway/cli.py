"""Single-process local launcher. Does not inherit demo configuration."""

import argparse
import os
import secrets
from pathlib import Path

import uvicorn

from m87_gateway.config import GatewaySettings
from m87_gateway.control.store import _prepare_private_file
from m87_gateway.main import create_app


def local_settings(data_dir: Path) -> GatewaySettings:
    data_dir = data_dir.expanduser().resolve()
    return GatewaySettings(
        server={"host": "127.0.0.1"},
        providers={
            "openai": {"enabled": False, "base_url": "https://api.openai.com/v1"},
            "ollama": {"enabled": False, "base_url": "http://localhost:11434"},
            "openai_compatible": {"enabled": False},
        },
        control_plane={
            "enabled": True,
            "database_path": str(data_dir / "control.db"),
            "master_key_path": str(data_dir / "master.key"),
        },
    )


def operator_key(data_dir: Path) -> str:
    key_file = data_dir.expanduser().resolve() / "admin.key"
    _prepare_private_file(key_file)
    key = key_file.read_text().strip()
    if not key:
        key = secrets.token_urlsafe(32)
        key_file.write_text(key + "\n")
    if len(key) < 24 or any(character.isspace() for character in key):
        raise ValueError("Invalid operator key file")
    return key


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the local gateway and included console")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share")) / "m87-gateway",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    try:
        settings = local_settings(args.data_dir)
        key = os.getenv("GATEWAY_ADMIN_API_KEY") or operator_key(args.data_dir)
        if len(key) < 24 or any(character.isspace() for character in key):
            raise ValueError("Invalid operator key")
    except ValueError:
        parser.error("Private data directory or operator key is invalid")
    os.environ[settings.control_plane.admin_api_key_env] = key
    print(f"Console: http://{args.host}:{args.port}/admin", flush=True)
    print(f"Admin key: {key}", flush=True)
    print(
        "Connect a provider in Setup, choose a model, then create an application key.", flush=True
    )
    uvicorn.run(create_app(settings), host=args.host, port=args.port)
