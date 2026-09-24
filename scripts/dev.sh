#!/usr/bin/env bash
# Starts API, Worker and Web together. Works with macOS's default bash 3.2.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  source "$ROOT_DIR/.env"
  set +a
fi
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"

# Prefer the project virtualenv so a plain `./scripts/dev.sh` works without activating it.
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

fail() { echo "dev.sh: $*" >&2; exit 1; }

command -v "$PYTHON" >/dev/null 2>&1 || fail "找不到 Python。先运行：python3 scripts/setup.py"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "需要 Python 3.11+，当前是 $("$PYTHON" --version 2>&1)。先运行：python3 scripts/setup.py"
"$PYTHON" -c 'import fastapi, uvicorn, replicate' 2>/dev/null \
  || fail "API 依赖没装。先运行：python3 scripts/setup.py"
command -v node >/dev/null 2>&1 || fail "找不到 Node.js。请先安装（例如 brew install node）。"
[[ -d "$ROOT_DIR/web/node_modules" ]] || fail "Web 依赖没装。先运行：python3 scripts/setup.py"
# Fail early if a port is taken (usually a previous dev.sh still running).
for port in "$API_PORT" "$WEB_PORT"; do
  if command -v lsof >/dev/null 2>&1; then
    holder="$(lsof -nP -iTCP:"${port}" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
    if [[ -n "${holder}" ]]; then
      fail "端口 ${port} 已被进程 ${holder}（$(ps -p "${holder}" -o comm= 2>/dev/null || echo 未知)）占用。可能是之前启动的服务还没关，运行 kill ${holder} 后再试。"
    fi
  fi
done
[[ -n "${REPLICATE_API_TOKEN:-}" ]] || echo "dev.sh: 警告：没有 REPLICATE_API_TOKEN，默认模型生成会失败（python3 scripts/doctor.py 看完整检查）。" >&2
# Agent login: API key or Claude subscription (never print the values).
if [[ "${AGENT_AUTH:-}" == "subscription" ]]; then
  [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]] || echo "dev.sh: 提示：AGENT_AUTH=subscription 但没有 CLAUDE_CODE_OAUTH_TOKEN，将尝试已有的 claude 登录；不行就运行 ./scripts/claude-login.sh。" >&2
  echo "dev.sh: Agent 使用 Claude 订阅额度。" >&2
elif [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  echo "dev.sh: 警告：没有 ANTHROPIC_API_KEY，画布 Agent 对话会失败（填在 .env 里）。" >&2
fi

PIDS=()
cleanup() {
  trap - EXIT INT TERM
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(
  cd "$ROOT_DIR/api"
  exec "$PYTHON" -m uvicorn app.main:app --reload --host 127.0.0.1 --port "$API_PORT"
) &
PIDS+=($!)

(
  cd "$ROOT_DIR"
  exec "$PYTHON" -m api.app.worker
) &
PIDS+=($!)

(
  cd "$ROOT_DIR/web"
  exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port "$WEB_PORT"
) &
PIDS+=($!)

echo "dev.sh: API http://127.0.0.1:$API_PORT  Web http://127.0.0.1:$WEB_PORT  (Ctrl+C 退出)"

# `wait -n` needs bash 4.3+; macOS ships bash 3.2, so poll instead.
# Stop everything as soon as any one process exits.
while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid" 2>/dev/null && status=0 || status=$?
      echo "dev.sh: 进程 ${pid} 已退出（状态 ${status}），正在关闭其余进程。" >&2
      exit "$status"
    fi
  done
  sleep 1
done
