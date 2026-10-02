#!/usr/bin/env bash
# Local Linux/WSL process management; never adopts a process started elsewhere.
set -euo pipefail
umask 077

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
action=${1:-}
shift || true
profile=gateway
if [[ $action == sample-* ]]; then profile=sample; action=${action#sample-}; fi
service=Gateway
ui_path=/admin
health_path=/health
runtime_name=gateway-runner
port=${GATEWAY_PORT:-}
min_port=1
extra_args=()
if [[ $profile == sample ]]; then
    service="Sample app"; ui_path=; health_path=/api/status; runtime_name=chat-app-runner
    port=${SAMPLE_PORT:-}
    min_port=0
fi
data_dir=${GATEWAY_DATA_DIR:-}
while (($#)); do
    case "$1" in
        --port|--data-dir)
            [[ $1 != --data-dir || $profile == gateway ]] || { echo "--data-dir is a gateway option." >&2; exit 1; }
            (($# >= 2)) || { echo "Missing value for $1." >&2; exit 1; }
            if [[ $1 == --port ]]; then port=$2; else data_dir=$2; fi
            shift 2 ;;
        --gateway-url|--model)
            [[ $profile == sample && $# -ge 2 ]] || { echo "Invalid sample option: $1" >&2; exit 1; }
            extra_args+=("$1" "$2"); shift 2 ;;
        -h|--help)
            if [[ $profile == sample ]]; then
                echo "Usage: ./examples/chat_app/start.sh [--port PORT] [--gateway-url URL] [--model MODEL]"
                echo "       ./examples/chat_app/stop.sh | ./examples/chat_app/status.sh"
            else
                echo "Usage: ./start.sh [--port PORT] [--data-dir DIRECTORY]"
                echo "       ./stop.sh | ./status.sh"
            fi
            echo "Gateway default: 8087, 8187, 8287, ...; --port selects an exact port."
            echo "Sample: examples/chat_app/{start,stop,status}.sh; automatic available port."
            exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done
if [[ -n $port ]] && { ! [[ $port =~ ^[0-9]{1,5}$ ]] || ! ((10#$port >= min_port && 10#$port <= 65535)); }; then
    echo "Port must be between 1 and 65535." >&2; exit 1
fi
[[ -z $port ]] || port=$((10#$port))
for tool in flock sha256sum stat curl; do
    command -v "$tool" >/dev/null || { echo "Required Linux/WSL tool missing: $tool" >&2; exit 1; }
done
[[ -d /proc/self ]] || { echo "These scripts require Linux/WSL." >&2; exit 1; }
cd -- "$repo_root"
run_dir=${GATEWAY_RUN_DIR:-$repo_root/var/lib/$runtime_name}
if [[ $profile == sample ]]; then run_dir=${SAMPLE_RUN_DIR:-$repo_root/var/lib/$runtime_name}; fi
mkdir -p -- "$run_dir"
[[ ! -L $run_dir && -O $run_dir && $(stat -c %a -- "$run_dir") == 700 ]] || {
    echo "Runtime directory must be owned by you, private (chmod 700), and not a symlink." >&2
    exit 1
}
run_dir=$(cd -- "$run_dir" && pwd)
state_file=$run_dir/process.state
log_file=$run_dir/$profile.log
lock_file=$run_dir/lock
for file in "$state_file" "$log_file" "$lock_file"; do
    if [[ -e $file || -L $file ]]; then
        [[ ! -L $file && -f $file && -O $file && $(stat -c %a -- "$file") == 600 ]] || {
            echo "Runtime files must be private regular files owned by you." >&2; exit 1;
        }
    fi
done
exec 9>>"$lock_file"
flock -x 9

# Linux start ticks and command digest protect against stale/reused PIDs.
process_identity() {
    local process_stat remainder
    process_stat=$(cat "/proc/$1/stat" 2>/dev/null) || return 1
    remainder=${process_stat##*) }
    read -r -a fields <<< "$remainder"
    [[ ${fields[0]} != Z ]] || return 1
    process_ticks=${fields[19]}
    process_digest=$(sha256sum "/proc/$1/cmdline" 2>/dev/null) || return 1
    process_digest=${process_digest%% *}
}

owned_process() {
    [[ -f $state_file ]] || return 1
    IFS=$'\t' read -r pid saved_ticks saved_digest saved_port < "$state_file" || return 1
    [[ $pid =~ ^[0-9]+$ && $saved_ticks =~ ^[0-9]+$ && $saved_digest =~ ^[a-f0-9]{64}$ && $saved_port =~ ^[0-9]{1,5}$ ]] || return 1
    ((pid > 1)) || return 1
    if [[ $profile == sample ]]; then
        grep -zFxq 'examples.chat_app' "/proc/$pid/cmdline" 2>/dev/null || return 1
    else
        if ! grep -zFxq 'm87_gateway' "/proc/$pid/cmdline" 2>/dev/null; then
            IFS= read -r -d '' executable < "/proc/$pid/cmdline" || return 1
            [[ ${executable##*/} == m87-gateway ]] || return 1
        fi
    fi
    process_identity "$pid" || return 1
    [[ $process_ticks == "$saved_ticks" && $process_digest == "$saved_digest" ]]
}

show_running() {
    echo "$service running (PID $pid). URL: http://localhost:$saved_port$ui_path"
    echo "Private startup log: $log_file"
}

case "$action" in
    status)
        if owned_process; then show_running; else echo "$service is stopped (no matching managed process)."; exit 3; fi ;;
    stop)
        if ! owned_process; then
            rm -f -- "$state_file"
            echo "No matching managed $service; nothing stopped."
            exit 0
        fi
        kill -TERM "$pid"
        for ((attempt=0; attempt<150; attempt++)); do
            if ! owned_process; then
                rm -f -- "$state_file"
                echo "$service stopped. Saved configuration, keys, and request logs are preserved."
                exit 0
            fi
            sleep 0.2
        done
        echo "Shutdown requested; $service is still finishing work. Retry its stop script shortly." >&2
        exit 1 ;;
    start)
        if owned_process; then show_running; exit 0; fi
        rm -f -- "$state_file"
        if [[ -n ${GATEWAY_PYTHON:-} ]]; then
            launcher=("$GATEWAY_PYTHON" -m m87_gateway)
        elif [[ -x $repo_root/.venv/bin/python ]]; then
            launcher=("$repo_root/.venv/bin/python" -m m87_gateway)
        elif [[ $profile == gateway && -x $repo_root/dist/m87-gateway ]]; then
            launcher=("$repo_root/dist/m87-gateway")
        else
            echo "Install the source package in .venv or build dist/m87-gateway first." >&2
            echo "See docs/runbooks/guided-setup.md. No virtual environment activation is needed." >&2
            exit 1
        fi
        args=(--host 127.0.0.1)
        if [[ $profile == sample ]]; then
            launcher=("${launcher[0]}" -m examples.chat_app)
            args=("${extra_args[@]}")
            if [[ -z ${SAMPLE_APP_KEY:-} ]]; then
                read -r -s -p "Gateway application key (from Applications): " SAMPLE_APP_KEY
                printf '\n'
            fi
            export SAMPLE_APP_KEY
        else
            [[ -z $data_dir ]] || args+=(--data-dir "$data_dir")
        fi
        [[ -z $port ]] || args+=(--port "$port")
        # CLI prints the operator key; keep its entire startup log owner-only.
        : > "$log_file"
        nohup "${launcher[@]}" "${args[@]}" </dev/null >"$log_file" 2>&1 9>&- &
        launched_pid=$!
        launched_ticks=
        if process_identity "$launched_pid"; then launched_ticks=$process_ticks; fi
        trap 'if process_identity "$launched_pid" && [[ $process_ticks == "$launched_ticks" ]]; then kill -TERM "$launched_pid" 2>/dev/null || true; fi' EXIT
        trap 'exit 1' INT TERM
        for ((attempt=0; attempt<100; attempt++)); do
            kill -0 "$launched_pid" 2>/dev/null || break
            bound_port=
            while IFS= read -r line; do
                if [[ $line == 'Listener: http://127.0.0.1:'* ]]; then bound_port=${line##*:}; break; fi
            done < "$log_file"
            # The CLI reserves its listener before printing the selected port.
            if [[ $bound_port =~ ^[0-9]+$ ]] && grep -Fq "Application startup complete." "$log_file" &&
                curl --silent --fail --max-time 4 "http://127.0.0.1:$bound_port$health_path" >/dev/null &&
                process_identity "$launched_pid"; then
                printf '%s\t%s\t%s\t%s\n' "$launched_pid" "$process_ticks" "$process_digest" "$bound_port" > "$state_file"
                trap - EXIT INT TERM
                pid=$launched_pid
                saved_port=$bound_port
                show_running
                while IFS= read -r line; do
                    if [[ $line == 'Admin key: '* ]]; then echo "$line"; break; fi
                done < "$log_file"
                if [[ $profile == sample ]]; then
                    echo "Stop: ./examples/chat_app/stop.sh | Status: ./examples/chat_app/status.sh"
                else
                    echo "Stop: ./stop.sh | Status: ./status.sh"
                fi
                exit 0
            fi
            sleep 0.2
        done
        echo "$service did not start. Check the private startup log: $log_file" >&2
        echo "An explicit port must be free. Existing services were left running." >&2
        exit 1 ;;
    *) echo "Expected start, stop, or status." >&2; exit 1 ;;
esac
