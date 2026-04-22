#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="0.0.0.0"
PORT="9600"
LOG_FILE="$SCRIPT_DIR/web_9600.log"
PID_FILE="$SCRIPT_DIR/web_9600.pid"

if [[ -x "$SCRIPT_DIR/venv/bin/python" ]]; then
  PYTHON_BIN="$SCRIPT_DIR/venv/bin/python"
elif [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    echo "Web service is already running on PID $EXISTING_PID"
    echo "URL: http://$(hostname -I | awk '{print $1}'):$PORT"
    exit 0
  fi
fi

if command -v ss >/dev/null 2>&1 && ss -ltn | grep -q ":$PORT "; then
  echo "Port $PORT is already in use. Please free it before starting the web service."
  exit 1
fi

nohup "$PYTHON_BIN" -m src.main web --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
WEB_PID=$!
echo "$WEB_PID" >"$PID_FILE"

sleep 2

if ! kill -0 "$WEB_PID" 2>/dev/null; then
  echo "Failed to start web service. Check $LOG_FILE for details."
  exit 1
fi

SERVER_IP="$(hostname -I | awk '{print $1}')"
echo "Web service started."
echo "PID: $WEB_PID"
echo "Log: $LOG_FILE"
echo "URL: http://$SERVER_IP:$PORT"
