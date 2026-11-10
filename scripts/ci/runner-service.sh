#!/usr/bin/env bash
#
# runner-service.sh: stand-in for systemd on a GitHub-hosted runner.
#
#     scripts/ci/runner-service.sh restart <tool> <port>
#     scripts/ci/runner-service.sh stop    <tool>
#
# Starts the live release of a tool ($DEPLOY_ROOT/<tool>/current) under
# gunicorn on 127.0.0.1:<port>, the way a systemd unit would on a real server.
# On a server, RESTART_CMD is simply `sudo systemctl restart tool-<tool>`.

set -euo pipefail

action=${1:-} tool=${2:-}
[[ $tool =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "invalid tool name: $tool" >&2; exit 64; }
: "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"

dir="$DEPLOY_ROOT/$tool"
pidfile="$dir/service.pid"

stop() {
    if [ -f "$pidfile" ]; then
        pid=$(cat "$pidfile")
        kill "$pid" 2>/dev/null || true
        while kill -0 "$pid" 2>/dev/null; do sleep 0.1; done
        rm -f "$pidfile"
    fi
}

start() {
    local port=$1
    [[ $port =~ ^[0-9]+$ ]] || { echo "invalid port: $port" >&2; exit 64; }
    nohup "$dir/current/.venv/bin/gunicorn" --chdir "$dir/current" \
        --bind "127.0.0.1:$port" --workers 2 app:app >> "$dir/service.log" 2>&1 &
    echo $! > "$pidfile"
}

case $action in
    restart) stop; start "${3:-}" ;;
    stop) stop ;;
    *) echo "usage: runner-service.sh restart <tool> <port> | stop <tool>" >&2; exit 64 ;;
esac
