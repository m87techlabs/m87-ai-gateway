"""Optional native Linux/WSL monitoring; separate state and no system installation."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import signal
import socket
import subprocess
import tarfile
import sys
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "deploy/observability"
VERSIONS = {
    "grafana": (
        "13.2.4",
        "grafana-13.2.4",
        "https://dl.grafana.com/grafana/release/13.2.4/grafana_13.2.4_38252365904_linux_amd64.tar.gz",
        "c48765988fd88572607e4ea670251af8a8e64ab3e360d0f3cf67a6f3587b92ab",
    ),
    "prometheus": (
        "3.13.4",
        "prometheus-3.13.4.linux-amd64",
        "https://github.com/prometheus/prometheus/releases/download/v3.13.4/prometheus-3.13.4.linux-amd64.tar.gz",
        "87f21a66f96c597a189cef8d640e8921b621fc17a9feff707c332c4f3b3ddd56",
    ),
}


def private_directory(path):
    if path.is_symlink():
        raise ValueError("Monitoring directories cannot be symlinks")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError("Monitoring directories must be owned by you with mode 700")


def private_file(path, text=None):
    if path.is_symlink():
        raise ValueError("Monitoring files cannot be symlinks")
    if path.exists() and (path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077):
        raise ValueError("Monitoring files must be owned by you with mode 600")
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | (os.O_TRUNC if text is not None else 0), 0o600)
    os.close(fd)
    if text is not None:
        path.write_text(text)


def identity(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        if stat[0] == "Z":
            return None
        return [stat[19], hashlib.sha256(Path(f"/proc/{pid}/cmdline").read_bytes()).hexdigest()]
    except (OSError, IndexError):
        return None


def owned(item):
    return (
        isinstance(item.get("pid"), int)
        and item["pid"] > 1
        and identity(item["pid"]) == item.get("identity")
        and item.get("identity") is not None
    )


def available_port(preferred):
    for port in range(preferred, preferred + 100):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                pass
    raise ValueError("No free local monitoring port in the configured range")


def get(url):
    with build_opener(ProxyHandler({})).open(url, timeout=5) as response:
        return json.load(response)


def install(base, name, download):
    version, directory, url, checksum = VERSIONS[name]
    tools = base / "tools"
    private_directory(tools)
    destination = tools / directory
    executable = destination / ("bin/grafana" if name == "grafana" else "prometheus")
    marker = destination / ".verified-m87"
    if executable.is_file() and marker.is_file() and marker.read_text().strip() == checksum:
        return executable
    archive = base / "downloads" / f"{name}.tar.gz"
    private_directory(archive.parent)
    if not archive.exists():
        if not download:
            raise ValueError(f"{name} {version} is missing; run ./monitoring-start.sh --install")
        print(f"Downloading verified {name} {version} (native Linux x86-64)", flush=True)
        private_file(archive)
        try:
            with build_opener().open(url, timeout=60) as response, archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        except Exception:
            archive.unlink(missing_ok=True)
            raise ValueError(f"Could not download {name}; check network and retry") from None
    if hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
        raise ValueError(
            f"{name} download checksum mismatch; remove only its private cached archive and retry"
        )
    if destination.exists():
        raise ValueError(
            "Incomplete tool directory exists; preserve data and remove only that tool directory before retrying"
        )
    with tarfile.open(archive) as package:
        for member in package.getmembers():
            if Path(member.name).parts[0] != directory:
                raise ValueError("Unexpected tool archive layout")
        package.extractall(tools, filter="data")
    private_file(marker, checksum + "\n")
    return executable


def managed_gateway_url():
    runner = Path(os.getenv("GATEWAY_RUN_DIR", str(ROOT / "var/lib/gateway-runner")))
    try:
        pid, ticks, digest, port = (runner / "process.state").read_text().strip().split("\t")
        if int(pid) > 1 and identity(int(pid)) == [ticks, digest] and 1 <= int(port) <= 65535:
            return f"http://127.0.0.1:{int(port)}"
    except (OSError, ValueError):
        pass
    return "http://127.0.0.1:8087"


def configure(base, gateway, ports):
    parsed = urlsplit(gateway)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Use a loopback gateway URL without credentials, path or query")
    if get(gateway.rstrip("/") + "/health").get("service") != "m87-ai-gateway":
        raise ValueError("Gateway is unavailable; start it and pass its URL with --gateway-url")
    get_metrics = build_opener(ProxyHandler({})).open(gateway.rstrip("/") + "/metrics", timeout=5)
    with get_metrics as response:
        if b"m87_gateway_requests" not in response.read(1048576):
            raise ValueError("Gateway metrics are unavailable")
    config = base / "config"
    private_directory(config)
    for folder in ("datasources", "dashboards", "dashboard-json"):
        private_directory(config / folder)
    target = parsed.netloc
    private_file(
        config / "prometheus.json",
        json.dumps(
            {
                "global": {"scrape_interval": "15s", "evaluation_interval": "15s"},
                "rule_files": [str((ASSETS / "prometheus/alerts.yml").resolve())],
                "scrape_configs": [
                    {
                        "job_name": "m87-gateway",
                        "metrics_path": "/metrics",
                        "static_configs": [{"targets": [target]}],
                    }
                ],
            }
        ),
    )
    private_file(
        config / "datasources/m87.yaml",
        json.dumps(
            {
                "apiVersion": 1,
                "datasources": [
                    {
                        "name": "M87 Prometheus",
                        "uid": "m87-prometheus",
                        "type": "prometheus",
                        "access": "proxy",
                        "url": f"http://127.0.0.1:{ports['prometheus']}",
                        "editable": False,
                        "jsonData": {"timeInterval": "15s"},
                    }
                ],
            }
        ),
    )
    private_file(
        config / "dashboards/m87.yaml",
        json.dumps(
            {
                "apiVersion": 1,
                "providers": [
                    {
                        "name": "M87 Gateway",
                        "orgId": 1,
                        "folder": "M87 Gateway",
                        "type": "file",
                        "disableDeletion": True,
                        "allowUiUpdates": False,
                        "updateIntervalSeconds": 30,
                        "options": {"path": str(config / "dashboard-json")},
                    }
                ],
            }
        ),
    )
    # Provision metrics only; a log dashboard without a Loki datasource is misleading.
    private_file(
        config / "dashboard-json/gateway-overview.json",
        (ASSETS / "grafana/dashboards/gateway-overview.json").read_text(),
    )
    password = base / "grafana-admin-password"
    if not password.exists():
        if (base / "grafana-data/grafana.db").exists():
            raise ValueError(
                "Existing Grafana data has no password file; restore that file before restarting"
            )
        private_file(password, secrets.token_urlsafe(36) + "\n")
    else:
        private_file(password)
    private_file(
        config / "grafana.ini",
        f"""[server]
http_addr = 127.0.0.1
http_port = {ports["grafana"]}
[paths]
data = {base / "grafana-data"}
logs = {base / "logs"}
plugins = {base / "grafana-plugins"}
provisioning = {config}
[security]
admin_user = admin
admin_password = $__file{{{password}}}
disable_gravatar = true
[users]
allow_sign_up = false
[auth.anonymous]
enabled = false
[analytics]
reporting_enabled = false
check_for_updates = false
check_for_plugin_updates = false
[log]
mode = console
[plugins]
preinstall_disabled = true
""",
    )


def show(base, state):
    for name, item in state.items():
        print(
            f"{name}: {'running' if owned(item) else 'stopped'} — http://localhost:{item['port']}"
        )
    if state:
        print(f"Grafana user: admin; initial password file: {base / 'grafana-admin-password'}")
        print("Alerts evaluate in Prometheus; notification routing is not configured.")


def stop(state):
    for item in state.values():
        if owned(item):
            os.kill(item["pid"], signal.SIGTERM)
    deadline = time.monotonic() + 30
    while any(owned(item) for item in state.values()) and time.monotonic() < deadline:
        time.sleep(0.1)
    if any(owned(item) for item in state.values()):
        raise ValueError("Monitoring is still finishing writes; retry stop shortly")


def run(args):
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise ValueError("Native monitoring helper currently supports Linux/WSL x86-64")
    if sys.version_info < (3, 11) or not hasattr(tarfile, "data_filter"):
        raise ValueError("Use a current Python 3.11+ with safe tar extraction support")
    import fcntl

    os.umask(0o077)
    candidate = Path(args.data_dir).expanduser()
    if candidate.is_symlink():
        raise ValueError("Monitoring data directory cannot be a symlink")
    base = candidate.resolve()
    private_directory(base)
    lock = base / "lifecycle.lock"
    private_file(lock)
    with lock.open("r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        state_file = base / "processes.json"
        private_file(state_file)
        state = json.loads(state_file.read_text() or "{}")
        if args.action == "status":
            show(base, state)
            return 0 if state and all(owned(item) for item in state.values()) else 3
        if args.action == "stop":
            stop(state)
            private_file(state_file, "{}")
            print("Monitoring stopped; gateway and saved monitoring data were left in place.")
            return 0
        if state and all(owned(item) for item in state.values()):
            show(base, state)
            return 0
        if any(owned(item) for item in state.values()):
            raise ValueError("Monitoring is partially running; stop it before restarting")
        executables = {name: install(base, name, args.install) for name in VERSIONS}
        ports = {"grafana": available_port(3000), "prometheus": available_port(9090)}
        configure(base, args.gateway_url or managed_gateway_url(), ports)
        for folder in ("logs", "grafana-data", "grafana-plugins", "prometheus-data"):
            private_directory(base / folder)
        subprocess.run(
            [
                str(executables["prometheus"].parent / "promtool"),
                "check",
                "config",
                str(base / "config/prometheus.json"),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        commands = {
            "prometheus": [
                str(executables["prometheus"]),
                "--config.file=" + str(base / "config/prometheus.json"),
                "--storage.tsdb.path=" + str(base / "prometheus-data"),
                "--storage.tsdb.retention.time=7d",
                "--web.listen-address=127.0.0.1:" + str(ports["prometheus"]),
            ],
            "grafana": [
                str(executables["grafana"]),
                "server",
                "--homepath",
                str(executables["grafana"].parent.parent),
                "--config",
                str(base / "config/grafana.ini"),
            ],
        }
        started = {}
        try:
            for name, command in commands.items():
                log = base / "logs" / (name + ".log")
                private_file(log)
                with log.open("ab") as output:
                    process = subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=output,
                        start_new_session=True,
                        env={
                            key: value
                            for key, value in os.environ.items()
                            if not key.startswith("GF_")
                        },
                    )
                item = {"pid": process.pid, "identity": identity(process.pid), "port": ports[name]}
                started[name] = item
                private_file(state_file, json.dumps(started))
                endpoint = "/api/health" if name == "grafana" else "/-/ready"
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise ValueError(f"{name} exited; inspect its private monitoring log")
                    try:
                        with build_opener(ProxyHandler({})).open(
                            f"http://127.0.0.1:{ports[name]}{endpoint}", timeout=2
                        ) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.2)
                else:
                    raise ValueError(f"{name} did not become ready; inspect its private log")
            show(base, started)
            return 0
        except BaseException:
            stop(started)
            private_file(state_file, "{}")
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    parser.add_argument(
        "--install", action="store_true", help="Download pinned native tools if absent"
    )
    parser.add_argument("--gateway-url", help="Override the detected managed gateway URL")
    parser.add_argument("--data-dir", default=str(ROOT / "var/lib/monitoring"))
    try:
        raise SystemExit(run(parser.parse_args()))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Monitoring operation failed: {exc}\n")
