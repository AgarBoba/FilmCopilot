#!/usr/bin/env bash
# Log the agent in with your Claude subscription (Pro / Max / Team / Enterprise).
# Runs `claude setup-token`: a browser window opens, you sign in, and a long-lived token is
# printed. Paste it into .env as CLAUDE_CODE_OAUTH_TOKEN=... and set AGENT_AUTH=subscription.
# Uses an installed `claude` if there is one, otherwise the copy bundled with the Agent SDK.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if command -v claude >/dev/null 2>&1; then
  CLAUDE="claude"
else
  CLAUDE="$(ls "$ROOT_DIR"/.venv/lib/python*/site-packages/claude_agent_sdk/_bundled/claude 2>/dev/null | head -1 || true)"
fi
[[ -n "${CLAUDE}" ]] || { echo "找不到 claude：先按 README 装好 .venv（pip install -e 'api[dev]'）" >&2; exit 1; }

echo "接下来会打开浏览器，用你的 Claude 账号登录。完成后终端里会显示一串令牌（sk-ant-oat…）。"
echo
"$CLAUDE" setup-token
echo
echo "把上面的令牌填进 .env："
echo "  CLAUDE_CODE_OAUTH_TOKEN=<令牌>"
echo "  AGENT_AUTH=subscription"
echo "可以用 open -e \"$ROOT_DIR/.env\" 打开编辑，保存后重启 ./scripts/dev.sh。"
