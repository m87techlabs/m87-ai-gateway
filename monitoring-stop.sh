#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
command -v python3 >/dev/null || { echo 'Python 3.11+ is required for this optional Linux/WSL helper.' >&2; exit 1; }
exec python3 "$repo_root/scripts/monitoring_services.py" stop "$@"
