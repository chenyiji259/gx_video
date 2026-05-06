#!/usr/bin/env bash
set -euo pipefail

APP_HOME="${APP_HOME:-/app}"
BACKEND_PORT="${BACKEND_PORT:-8005}"
FRONTEND_PORT="${FRONTEND_PORT:-3005}"

cd "$APP_HOME"

if [ ! -f "$APP_HOME/backend/run.py" ]; then
  echo "backend/run.py not found under $APP_HOME. Mount the project root to /app." >&2
  exit 1
fi

if [ ! -f "$APP_HOME/ui_dev/package.json" ]; then
  echo "ui_dev/package.json not found under $APP_HOME. Mount the full project root, including ui_dev, to /app." >&2
  exit 1
fi

mkdir -p "$APP_HOME/logs" "$APP_HOME/data" "$APP_HOME/ui_dev"

# The project source is mounted at /app. Keep Linux node_modules outside the
# mount so a Windows-uploaded ui_dev/node_modules never shadows container deps.
if [ ! -e "$APP_HOME/ui_dev/node_modules" ]; then
  ln -s /opt/vidmuse/ui_dev/node_modules "$APP_HOME/ui_dev/node_modules"
fi

echo "Starting VidMuse backend on 0.0.0.0:${BACKEND_PORT}"
python "$APP_HOME/backend/run.py" --host 0.0.0.0 --port "$BACKEND_PORT" &
backend_pid="$!"

echo "Starting VidMuse frontend on 0.0.0.0:${FRONTEND_PORT}"
(
  cd "$APP_HOME/ui_dev"
  npm run dev -- --host=0.0.0.0 --port="$FRONTEND_PORT"
) &
frontend_pid="$!"

terminate() {
  kill "$backend_pid" "$frontend_pid" 2>/dev/null || true
  wait "$backend_pid" "$frontend_pid" 2>/dev/null || true
}

trap terminate INT TERM

set +e
wait -n "$backend_pid" "$frontend_pid"
exit_code="$?"
terminate
exit "$exit_code"
