#!/usr/bin/env bash
# Manage only this checkout's single-container Compose deployment.
set -euo pipefail
umask 077

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
action=${1:-}
shift || true
port=${GATEWAY_PORT:-}
port_override=false
[[ -z $port ]] || port_override=true
build=false
fail() { printf '%s\n' "$*" >&2; exit 1; }
usage() {
    echo "Usage: ./docker-start.sh [--port PORT] [--build]"
    echo "       ./docker-stop.sh | ./docker-status.sh"
    echo "Requires Bash, Docker Engine (Linux amd64), and Docker Compose v2 with --wait-timeout."
    echo "Host Python is not required. Default port: 8087; existing deployment ports are reused."
    echo "--build builds from the checkout instead of pulling the private preview image."
}
case "$action" in start|stop|status) ;; *) fail "Unknown Docker lifecycle action." ;; esac
while (($#)); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --build) [[ $action == start ]] || fail "--build is a start option."; build=true; shift ;;
        --port)
            [[ $action == start && $# -ge 2 ]] || fail "Start --port requires a port number."
            port=$2; port_override=true; shift 2 ;;
        *) fail "Unknown option: $1. Use --help." ;;
    esac
done
if [[ -n $port ]]; then
    [[ $port =~ ^[0-9]{1,5}$ ]] && ((10#$port >= 1 && 10#$port <= 65535)) || fail "Port must be between 1 and 65535."
    port=$((10#$port))
fi
command -v docker >/dev/null || fail "Docker CLI is unavailable. Install Docker, or enable Docker Desktop WSL integration for this distribution."
docker --version >/dev/null 2>&1 || fail "Docker CLI is not usable. Start Docker Desktop and enable WSL integration for this distribution, or install Docker Engine."
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is unavailable. Install the Compose plugin or update Docker Desktop."
engine=$(docker info --format '{{.OSType}}/{{.Architecture}}' 2>/dev/null) || fail "Docker Engine is unavailable or inaccessible. Start Docker Desktop/Engine, enable WSL integration if needed, and check Docker access."
case "$engine" in linux/x86_64|linux/amd64) ;; *) fail "This preview requires a Linux amd64 Docker engine. Reported engine: $engine. Select Linux containers in Docker Desktop." ;; esac
[[ -f $repo_root/docker-compose.yml ]] || fail "Required docker-compose.yml is missing from the project root."
compose=(docker compose --project-directory "$repo_root" -p m87-ai-gateway -f "$repo_root/docker-compose.yml")
if [[ $build == true ]]; then
    for required in Dockerfile docker-compose.build.yml pyproject.toml src/m87_gateway; do
        [[ -e $repo_root/$required ]] || fail "Source-build requirement missing: $required. Use a complete checkout."
    done
    compose+=(-f "$repo_root/docker-compose.build.yml")
fi
# Pin the project name so invocation directory and COMPOSE_PROJECT_NAME cannot adopt other services.
existing=$("${compose[@]}" ps --all -q m87-ai-gateway) || fail "Could not inspect the gateway Compose deployment."
[[ $existing != *$'\n'* ]] || fail "Multiple gateway containers found; this helper supports one instance."
if [[ $action == start && -z $port && -n $existing ]]; then
    port=$(docker inspect --format '{{(index (index .HostConfig.PortBindings "8087/tcp") 0).HostPort}}' "$existing") || fail "Cannot read the existing gateway port. Specify --port."
fi
export GATEWAY_PORT=${port:-8087}
"${compose[@]}" config --quiet || fail "Compose configuration is invalid. Check GATEWAY_PORT/GATEWAY_IMAGE and the Compose files."
show_url() {
    local published
    published=$("${compose[@]}" port m87-ai-gateway 8087) || fail "Cannot read the published gateway port. Check ./docker-status.sh."
    printf 'Console: http://%s\n' "$published"
    echo "Retrieve the operator key privately:"
    printf '  docker compose --project-directory %q -p m87-ai-gateway -f %q exec m87-ai-gateway cat /data/gateway/admin.key\n' "$repo_root" "$repo_root/docker-compose.yml"
}
case "$action" in
    start)
        help_text=$(docker compose up --help)
        [[ $help_text == *--wait-timeout* ]] || fail "Update Docker Compose v2: startup requires support for --wait and --wait-timeout."
        if [[ -n $existing && $build == false && $port_override == false ]]; then
            start_help=$(docker compose start --help)
            [[ $start_help == *--wait-timeout* ]] || fail "Update Docker Compose v2: resume requires --wait and --wait-timeout."
            "${compose[@]}" start --wait --wait-timeout 90 m87-ai-gateway || fail "Existing gateway did not become healthy. Inspect ./docker-status.sh and Docker logs."
            echo "Gateway is healthy; its existing image, port and configuration were preserved."
            show_url
            exit 0
        fi
        if [[ $build == true ]]; then
            echo "Building the gateway image from this checkout (no host Python required)."
            "${compose[@]}" build m87-ai-gateway || fail "Image build failed. Check Docker output and network access to base images/dependencies."
        else
            echo "Checking access to the prebuilt gateway image."
            "${compose[@]}" pull m87-ai-gateway || fail "Image pull failed. Check network access and run docker login ghcr.io for private registry access, or use ./docker-start.sh --build."
        fi
        "${compose[@]}" up -d --pull never --wait --wait-timeout 90 m87-ai-gateway || fail "Gateway did not start healthy. If port $GATEWAY_PORT is occupied, use ./docker-start.sh --port 8187 (or another free port). Inspect ./docker-status.sh and Docker logs. Unrelated services and data volumes were preserved."
        echo "Gateway is healthy. Configure inference in Setup; /ready can remain 503 until setup is complete."
        show_url ;;
    stop)
        if [[ -z $existing ]]; then echo "No gateway container exists for this Compose deployment."; exit 0; fi
        "${compose[@]}" stop --timeout 60 m87-ai-gateway || fail "Could not stop the gateway. Check Docker access and container state."
        echo "Gateway stopped. Keys, configuration and logs remain in its volume." ;;
    status)
        if [[ -z $existing ]]; then echo "No gateway container exists for this Compose deployment."; exit 3; fi
        "${compose[@]}" ps --all m87-ai-gateway
        running=$(docker inspect --format '{{.State.Running}}' "$existing")
        if [[ $running != true ]]; then echo "Gateway is stopped."; exit 3; fi
        health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' "$existing")
        printf 'Container health: %s\n' "$health"
        show_url
        [[ $health == healthy ]] || exit 1 ;;
esac
