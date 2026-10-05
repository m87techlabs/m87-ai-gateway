"""Single-process local launcher. Does not inherit demo configuration."""

import argparse
import os
import secrets
import json
import getpass
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from m87_gateway import __version__
from m87_gateway.config import GatewaySettings
from m87_gateway.workstation import default_data_dir, instance_lock, manage
from m87_gateway.backup import backup, restore
from m87_gateway.control.store import _prepare_private_file
from m87_gateway.main import create_app
from m87_gateway.local_server import DEFAULT_GATEWAY_PORT, bind_listener


def local_settings(data_dir: Path) -> GatewaySettings:
    data_dir = data_dir.expanduser().resolve()
    return GatewaySettings(
        server={"host": "127.0.0.1", "port": DEFAULT_GATEWAY_PORT},
        providers={
            "openai": {"enabled": False, "base_url": "https://api.openai.com/v1"},
            "ollama": {"enabled": False, "base_url": "http://localhost:11434"},
            "openai_compatible": {"enabled": False},
        },
        control_plane={
            "enabled": True,
            "backend_adapter": os.getenv("GATEWAY_BACKEND_ADAPTER", "sqlite"),
            "management_audit_retention_days": os.getenv(
                "GATEWAY_MANAGEMENT_AUDIT_RETENTION_DAYS", "365"
            ),
            "usage_retention_days": os.getenv("GATEWAY_USAGE_RETENTION_DAYS", "365"),
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
        default=default_data_dir(),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--hide-admin-key", action="store_true", help="Keep the operator key out of startup logs"
    )
    parser.add_argument("--port", type=int, help="Exact port; default tries 8087, 8187, 8287, ...")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--open-browser", action="store_true", help="Open the console after startup"
    )
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument(
        "--stop", action="store_true", help="Gracefully stop this data directory's instance"
    )
    operations.add_argument(
        "--status", action="store_true", help="Check this data directory's instance"
    )
    operations.add_argument("--backup", type=Path, help="Encrypt an offline backup to a new file")
    operations.add_argument("--restore", type=Path, help="Restore into a fresh data directory")
    args = parser.parse_args()
    args.data_dir = args.data_dir.expanduser().resolve()
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    try:
        if args.stop or args.status:
            running = manage(args.data_dir, args.stop)
            print(
                "Shutdown requested"
                if running and args.stop
                else "Gateway running"
                if running
                else "Gateway stopped"
            )
            if not running:
                raise SystemExit(3)
            return
        with instance_lock(args.data_dir):
            if args.backup or args.restore:
                password = os.getenv("GATEWAY_BACKUP_PASSWORD") or getpass.getpass(
                    "Backup password: "
                )
                if args.backup and not os.getenv("GATEWAY_BACKUP_PASSWORD"):
                    if password != getpass.getpass("Confirm password: "):
                        raise ValueError("Passwords do not match")
                if args.backup:
                    backup(args.data_dir, args.backup.expanduser().resolve(), password)
                    print("Encrypted backup created")
                else:
                    restore(args.data_dir, args.restore.expanduser().resolve(), password)
                    print("Backup restored; start the gateway to verify readiness and a completion")
                return
            run_gateway(args)
    except ValueError as exc:
        parser.error(str(exc))
    except OSError:
        parser.error(
            "Operation failed. Check private storage, instance state, backup password and compatibility"
        )


def run_gateway(args):
    settings = local_settings(args.data_dir)
    key = os.getenv("GATEWAY_ADMIN_API_KEY") or operator_key(args.data_dir)
    if len(key) < 24 or any(character.isspace() for character in key):
        raise ValueError("Invalid operator key")
    os.environ[settings.control_plane.admin_api_key_env] = key
    try:
        listener = bind_listener(
            args.host,
            args.port or DEFAULT_GATEWAY_PORT,
            fallback_step=100 if args.port is None else None,
        )
    except OSError:
        raise ValueError(
            "Could not bind gateway listener; requested ports are unavailable"
        ) from None
    port = listener.getsockname()[1]
    settings.server.port = port
    application = create_app(settings)
    identity = secrets.token_hex(16)
    server = uvicorn.Server(uvicorn.Config(application, host=args.host, port=port))
    application.state.instance_id = identity
    application.state.shutdown = lambda: setattr(server, "should_exit", True)
    state_file = args.data_dir / "instance.json"
    _prepare_private_file(state_file)
    state_file.write_text(json.dumps({"port": port, "instance_id": identity}))
    print(f"Listener: http://{args.host}:{port}", flush=True)
    print(f"Console: http://{args.host}:{port}/admin", flush=True)
    if getattr(args, "hide_admin_key", False):
        print("Operator key is stored privately in the data directory.", flush=True)
    else:
        print(f"Admin key: {key}", flush=True)
    print(
        "Connect a provider in Setup, choose a model, then create an application key.", flush=True
    )
    if args.open_browser:

        def open_console():
            for _ in range(100):
                if server.started:
                    webbrowser.open(f"http://127.0.0.1:{port}/admin")
                    return
                if server.should_exit:
                    return
                time.sleep(0.1)

        threading.Thread(target=open_console, daemon=True).start()
    try:
        with listener:
            server.run(sockets=[listener])
    finally:
        state_file.unlink(missing_ok=True)
