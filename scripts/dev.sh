#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"

cleanup() {
  kill "${API_PID:-}" "${WEB_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(
  cd "$ROOT_DIR/api"
  exec python -m uvicorn app.main:app --reload --host 127.0.0.1 --port "$API_PORT"
) &
API_PID=$!

(
  cd "$ROOT_DIR/web"
  exec npm run dev -- --host 127.0.0.1 --port "$WEB_PORT"
) &
WEB_PID=$!

wait -n "$API_PID" "$WEB_PID"
