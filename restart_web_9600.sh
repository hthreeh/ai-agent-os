#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="0.0.0.0"
PORT="9600"
LOG_FILE="$SCRIPT_DIR/web_9600.log"
PID_FILE="$SCRIPT_DIR/web_9600.pid"

find_python() {
    if [[ -x "$SCRIPT_DIR/venv/bin/python" ]]; then
        echo "$SCRIPT_DIR/venv/bin/python"
    elif [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
        echo "$SCRIPT_DIR/.venv/bin/python"
    else
        command -v python3
    fi
}

kill_by_pidfile() {
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE" 2>/dev/null || true)
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            echo "Stopping existing service (PID $pid)..."
            kill "$pid" 2>/dev/null || true
            sleep 1
            kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
    fi
}

kill_by_port() {
    if command -v ss >/dev/null 2>&1; then
        local pid
        pid=$(ss -ltn 2>/dev/null | grep ":$PORT " | awk 'NR==1 {print $NF}' | grep -o '[0-9]*' | head -1)
        [[ -n "$pid" ]] && [[ "$pid" =~ ^[0-9]+$ ]] && echo "Killing process on port $PORT (PID $pid)..." && kill "$pid" 2>/dev/null || true
    fi
}

PYTHON_BIN="$(find_python)"

echo "=== Restarting OS Agent Web Service ==="
echo ""

kill_by_pidfile
kill_by_port
sleep 1

if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
    echo "ERROR: Port $PORT still in use after cleanup."
    exit 1
fi

nohup "$PYTHON_BIN" -m src.main web --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"

sleep 2

if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "ERROR: Failed to start. Check $LOG_FILE"
    tail -10 "$LOG_FILE"
    exit 1
fi

echo ""
echo "Service restarted."
echo "PID: $(cat "$PID_FILE")"
echo "URL: http://$(hostname -I | awk '{print $1}'):$PORT"
