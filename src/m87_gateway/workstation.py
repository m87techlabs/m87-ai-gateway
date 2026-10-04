"""Portable workstation paths, exclusive instance locks, and safe lifecycle clients."""

from contextlib import contextmanager
import json
import os
import time
from pathlib import Path

import httpx

from m87_gateway.private_storage import check_private, prepare_file


def default_data_dir() -> Path:
    if os.name == "nt":
        return Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData/Local")) / "M87Gateway"
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share")) / "m87-gateway"


@contextmanager
def instance_lock(data_dir: Path):
    path = data_dir / "instance.lock"
    prepare_file(path)
    with path.open("r+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError(
                "Data directory is in use. Stop the gateway before this operation"
            ) from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_UN)


def manage(data_dir: Path, stop: bool = False) -> bool:
    """Check instance identity before sending any credential to a listener."""
    state_file = data_dir / "instance.json"
    if not state_file.is_file():
        return False
    check_private(data_dir)
    check_private(state_file)
    state = json.loads(state_file.read_text())
    port, identity = state["port"], state["instance_id"]
    if (
        type(port) is not int
        or not 1 <= port <= 65535
        or not isinstance(identity, str)
        or len(identity) != 32
    ):
        raise ValueError("Invalid instance record")
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=3, trust_env=False) as client:
        try:
            response = client.get("/instance")
            if response.status_code != 200 or response.json().get("instance_id") != identity:
                return False
        except (httpx.HTTPError, ValueError):
            return False
        if stop:
            key_file = data_dir / "admin.key"
            key = os.getenv("GATEWAY_ADMIN_API_KEY")
            if not key:
                check_private(key_file)
                key = key_file.read_text().strip()
            response = client.post(
                "/admin/api/shutdown",
                headers={"Authorization": f"Bearer {key}"},
                json={"instance_id": identity},
            )
            if response.status_code != 204:
                raise ValueError("Gateway rejected shutdown; use its operator key")
            for _ in range(300):
                try:
                    with instance_lock(data_dir):
                        return True
                except ValueError:
                    time.sleep(0.1)
            raise ValueError("Shutdown requested; gateway is still draining requests. Check status")
        return True
