#!/usr/bin/env python3
"""Is Film Copilot ready to run? Prints a checklist, each problem with how to fix it.

    python3 scripts/doctor.py            # local checks, no network
    python3 scripts/doctor.py --online   # also asks Anthropic / Replicate whether the keys work (free calls)
    python3 scripts/doctor.py --json     # same, machine-readable (for agents)

Exit code: 0 ready, 1 something to fix. Secrets are reported as set / not set, never shown.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import socket
import stat
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import ENV_FILE, MIN_PYTHON, ROOT, VENV, add_api_to_path, load_env, reexec_in_venv  # noqa: E402

reexec_in_venv()

checks: list[dict] = []


def check(name: str, ok: bool, detail: str = '', fix: str = '', required: bool = True) -> bool:
    checks.append({'check': name, 'ok': ok, 'required': required, 'detail': detail, 'fix': '' if ok else fix})
    return ok


def check_python() -> bool:
    in_venv = Path(sys.prefix).resolve() == VENV.resolve()
    version = '.'.join(map(str, sys.version_info[:3]))
    if not check('Python 环境', sys.version_info >= MIN_PYTHON, f'Python {version}' + ('（.venv）' if in_venv else '（不是项目 .venv）'),
                 '运行 python3 scripts/setup.py'):
        return False
    missing = [name for name in ('fastapi', 'uvicorn', 'httpx', 'replicate', 'claude_agent_sdk', 'PIL')
               if importlib.util.find_spec(name) is None]
    return check('API 依赖', not missing, '缺: ' + ', '.join(missing) if missing else '已安装', '运行 python3 scripts/setup.py')


def check_web() -> None:
    check('Web 依赖', (ROOT / 'web' / 'node_modules' / 'vite').exists(), '', '运行 python3 scripts/setup.py')


def check_env_file() -> list[int]:
    if not check('.env 文件', ENV_FILE.exists(), '', '运行 python3 scripts/setup.py（会从 .env.example 创建）'):
        return []
    bad = load_env()
    check('.env 格式', not bad, f"第 {', '.join(map(str, bad))} 行不是 KEY=VALUE" if bad else '',
          '打开 .env 看这些行：常见原因是粘贴的密钥被折成了两行，把它接回 KEY= 那一行的末尾')
    if os.name != 'nt':
        mode = stat.S_IMODE(ENV_FILE.stat().st_mode)
        check('.env 权限', not mode & 0o077, oct(mode), '运行 chmod 600 .env（只让自己能读）', required=False)
    return bad


def check_agent_login() -> None:
    api_key = bool(os.getenv('ANTHROPIC_API_KEY'))
    token = bool(os.getenv('CLAUDE_CODE_OAUTH_TOKEN'))
    auth = (os.getenv('AGENT_AUTH') or '').strip().lower()
    if auth == 'subscription' or (auth not in ('api', 'subscription') and token and not api_key):
        check('画布 Agent 登录', True, 'Claude 订阅（CLAUDE_CODE_OAUTH_TOKEN ' + ('已设置' if token else '未设置，将用本机 claude 登录') + '）')
        return
    check('画布 Agent 登录', api_key, 'ANTHROPIC_API_KEY ' + ('已设置' if api_key else '未设置'),
          '让用户自己打开 .env，把 Anthropic API Key 粘到 ANTHROPIC_API_KEY= 后面（console.anthropic.com → API Keys）')


def check_models() -> list:
    add_api_to_path()
    try:
        from app.models_registry import registry
        from app.providers import has_adapter, missing_env
    except Exception as error:  # dependencies missing: already reported above
        check('模型列表', False, f'读不了: {error}', '先修好上面的问题')
        return []
    models = registry()
    specs = models.all()
    check('模型文件', not models.errors, '; '.join(models.errors) or f'{len(specs)} 个模型',
          '按提示修 models/ 里对应的 JSON（格式见 docs/ADDING_MODELS.md）')
    for kind, label in (('image', '图片'), ('video', '视频')):
        check(f'{label}模型', any(spec.kind == kind for spec in specs), '', f'在 models/ 里加一个 kind 为 {kind} 的模型')
    for spec in specs:
        ready = has_adapter(spec.provider)
        missing = missing_env(spec.provider) if ready else []
        name = f'模型 {spec.id}' + ('（默认）' if spec.default else '')
        if not ready:
            check(name, False, f'provider「{spec.provider}」没有对接代码',
                  f'按 docs/ADDING_MODELS.md 写 api/app/providers/{spec.provider}.py', required=spec.default)
        else:
            check(name, not missing, f'{spec.provider} · ' + ('密钥已设置' if not missing else '缺 ' + ', '.join(missing)),
                  f"让用户自己打开 .env，填上 {', '.join(missing)}", required=spec.default)
    return specs


def _get(url: str, headers: dict[str, str]) -> int:
    try:
        with urlopen(Request(url, headers=headers), timeout=15) as response:
            return response.status
    except HTTPError as error:
        return error.code


def check_online(specs: list) -> None:
    probes = []
    if os.getenv('ANTHROPIC_API_KEY') and (os.getenv('AGENT_AUTH') or 'api').lower() != 'subscription':
        probes.append(('Anthropic API Key 可用', 'https://api.anthropic.com/v1/models?limit=1',
                       {'x-api-key': os.environ['ANTHROPIC_API_KEY'], 'anthropic-version': '2023-06-01'},
                       '密钥无效或已停用：在 console.anthropic.com 重新生成，让用户自己替换 .env 里的 ANTHROPIC_API_KEY'))
    if os.getenv('REPLICATE_API_TOKEN') and any(spec.provider == 'replicate' for spec in specs):
        probes.append(('Replicate Token 可用', 'https://api.replicate.com/v1/account',
                       {'Authorization': f"Bearer {os.environ['REPLICATE_API_TOKEN']}"},
                       '令牌无效：在 replicate.com/account/api-tokens 重新生成，让用户自己替换 .env 里的 REPLICATE_API_TOKEN'))
    for name, url, headers, fix in probes:
        try:
            code = _get(url, headers)
        except (URLError, OSError) as error:
            check(name, False, f'连不上（{getattr(error, "reason", error)}）', '检查网络 / 代理后重试')
            continue
        check(name, code == 200, f'HTTP {code}', fix if code in (401, 403) else '稍后重试；一直失败就看服务状态页')
    # Other providers can offer their own key check: def check_key() -> str | None (error text).
    add_api_to_path()
    from app.providers import adapter_module, missing_env
    for provider in sorted({spec.provider for spec in specs} - {'replicate'}):
        try:
            module = adapter_module(provider)
        except ValueError:
            continue
        if hasattr(module, 'check_key') and not missing_env(provider):
            try:
                error = module.check_key()
            except Exception as exc:  # noqa: BLE001 - report, don't crash the checklist
                error = str(exc)
            check(f'{provider} 密钥可用', not error, error or 'OK', '检查 .env 里这个 provider 的密钥')


def check_running() -> None:
    port = int(os.getenv('API_PORT') or 8000)
    web_port = int(os.getenv('WEB_PORT') or 5173)

    def listening(p: int) -> bool:
        with socket.socket() as sock:
            sock.settimeout(0.5)
            return sock.connect_ex(('127.0.0.1', p)) == 0

    api, web = listening(port), listening(web_port)
    detail = f'API :{port} ' + ('在运行' if api else '未运行') + f'，Web :{web_port} ' + ('在运行' if web else '未运行')
    check('服务', api and web, detail, '启动: ./scripts/dev.sh（长期运行，放后台），然后打开 http://127.0.0.1:' + str(web_port),
          required=False)


def main() -> None:
    as_json = '--json' in sys.argv
    if check_python():
        check_web()
        check_env_file()
        check_agent_login()
        specs = check_models()
        if '--online' in sys.argv:
            check_online(specs)
    check_running()
    ready = all(item['ok'] for item in checks if item['required'])
    if as_json:
        print(json.dumps({'ready': ready, 'checks': checks}, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            mark = '✓' if item['ok'] else ('✗' if item['required'] else '!')
            print(f"{mark} {item['check']}" + (f"  {item['detail']}" if item['detail'] else ''))
            if item['fix']:
                print(f"    → {item['fix']}")
        url = f"http://127.0.0.1:{os.getenv('WEB_PORT') or 5173}"
        running = next((item['ok'] for item in checks if item['check'] == '服务'), False)
        if not ready:
            print('\n还有 ✗ 项要处理（! 是可选项）。')
        else:
            print(f'\n可以用了：{url}' if running else f'\n可以用了：./scripts/dev.sh 启动后打开 {url}')
    sys.exit(0 if ready else 1)


if __name__ == '__main__':
    main()
