#!/usr/bin/env bash
exec "$(dirname -- "${BASH_SOURCE[0]}")/m87-gateway" --open-browser "$@"
