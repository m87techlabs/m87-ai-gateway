#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
python_executable=${GATEWAY_PYTHON:-$repo_root/.venv/bin/python}
if [[ ! -x $python_executable ]]; then
    echo "Install the source package in .venv first; see examples/chat_app/README.md." >&2
    exit 1
fi
if [[ -z ${SAMPLE_APP_KEY:-} ]]; then
    read -r -s -p "Gateway application key (from Applications): " SAMPLE_APP_KEY
    printf '\n'
fi
export SAMPLE_APP_KEY
cd -- "$repo_root"
exec "$python_executable" -m examples.chat_app "$@"
