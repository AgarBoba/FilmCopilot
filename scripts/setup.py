#!/usr/bin/env python3
"""One-shot, non-interactive install. Safe to run again at any time (also after `git pull`).

    python3 scripts/setup.py

Does: finds Python 3.11+ (or has uv fetch one), creates .venv, installs the API; installs the
web dependencies; creates .env from .env.example (permissions 600) or adds settings that are
new in .env.example; then runs scripts/doctor.py.
Never asks questions, never prints secrets. Exit code 0 = installed (keys may still be empty).
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import ENV_EXAMPLE, ENV_FILE, MIN_PYTHON, ROOT, VENV, parse_env_file, venv_python  # noqa: E402

MIN_NODE = (20, 19)


def step(ok: bool, text: str) -> None:
    print(f"{'✓' if ok else '✗'} {text}", flush=True)


def fail(text: str, fix: str) -> None:
    step(False, text)
    print(f'  怎么办: {fix}')
    sys.exit(1)


def run(command: list[str], cwd: Path = ROOT) -> None:
    print(f"  $ {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=cwd)
    if result.returncode != 0:
        fail(f"命令失败（退出码 {result.returncode}）: {' '.join(command)}", '看上面的报错；网络问题可以重试一次。')


def python_version(python: str | Path) -> tuple[int, int] | None:
    try:
        out = subprocess.run([str(python), '-c', 'import sys; print(*sys.version_info[:2])'],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    major, minor = out.stdout.split()
    return int(major), int(minor)


def ensure_venv() -> Path:
    python = venv_python()
    if python.exists():
        version = python_version(python)
        if version and version >= MIN_PYTHON:
            step(True, f'.venv 已存在（Python {version[0]}.{version[1]}）')
            return python
        # Broken or too old (e.g. copied from another machine): keep it aside, make a new one.
        aside = ROOT / f'.venv.old-{int(time.time())}'
        VENV.rename(aside)
        step(True, f'原 .venv 不可用，已移到 {aside.name}（确认没用后可以删掉）')
    uv = shutil.which('uv')
    candidates = ['python3.13', 'python3.12', 'python3.11', 'python3', 'python']
    for name in candidates:
        found = shutil.which(name)
        version = python_version(found) if found else None
        if version and version >= MIN_PYTHON:
            if uv:
                run([uv, 'venv', '--python', found, str(VENV)])
            else:
                run([found, '-m', 'venv', str(VENV)])
            step(True, f'创建了 .venv（Python {version[0]}.{version[1]}）')
            return venv_python()
    if uv:
        # uv downloads a standalone Python by itself.
        run([uv, 'venv', '--python', '3.12', str(VENV)])
        step(True, '用 uv 创建了 .venv（Python 3.12）')
        return venv_python()
    fail('找不到 Python 3.11+',
         '装 uv（推荐，会自动带 Python）: curl -LsSf https://astral.sh/uv/install.sh | sh ，'
         '或 macOS 上 brew install python@3.12；装好后重新运行 python3 scripts/setup.py')
    raise AssertionError


def install_api(python: Path) -> None:
    uv = shutil.which('uv')
    if uv:
        run([uv, 'pip', 'install', '--python', str(python), '-e', 'api[dev]'])
    else:
        run([str(python), '-m', 'pip', 'install', '--upgrade', 'pip', '-q'])
        run([str(python), '-m', 'pip', 'install', '-e', 'api[dev]'])
    step(True, 'API 依赖已安装')


def install_web() -> None:
    node = shutil.which('node')
    if not node:
        fail('找不到 Node.js', f'安装 Node.js {MIN_NODE[0]}.{MIN_NODE[1]}+（macOS: brew install node），然后重新运行本脚本')
    raw = subprocess.run([node, '--version'], capture_output=True, text=True).stdout.strip()
    match = re.match(r'v(\d+)\.(\d+)', raw)
    if not match or (int(match[1]), int(match[2])) < MIN_NODE:
        fail(f'Node.js 版本太旧（{raw}）', f'升级到 {MIN_NODE[0]}.{MIN_NODE[1]}+（macOS: brew upgrade node）')
    web = ROOT / 'web'
    if shutil.which('pnpm'):
        run(['pnpm', 'install', '--frozen-lockfile'], cwd=web)
    elif shutil.which('corepack'):
        run(['corepack', 'pnpm', 'install', '--frozen-lockfile'], cwd=web)
    else:
        run(['npm', 'install'], cwd=web)
    step(True, f'Web 依赖已安装（Node {raw}）')


def ensure_env_file() -> None:
    if not ENV_FILE.exists():
        shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
        step(True, '从 .env.example 创建了 .env')
    else:
        # Settings added to .env.example since (e.g. a new provider's key): append them empty.
        current, _ = parse_env_file(ENV_FILE)
        example, _ = parse_env_file(ENV_EXAMPLE)
        missing = [key for key in example if key not in current]
        if missing:
            with ENV_FILE.open('a', encoding='utf-8') as file:
                file.write('\n# 新增的设置（setup.py 补上的）\n')
                for key in missing:
                    file.write(f'{key}={example[key]}\n')
            step(True, f".env 补上了新设置: {', '.join(missing)}")
        else:
            step(True, '.env 已存在')
    if os.name != 'nt':
        ENV_FILE.chmod(0o600)
    (ROOT / 'data').mkdir(exist_ok=True)


def main() -> None:
    print(f'Film Copilot 安装  ({ROOT})')
    python = ensure_venv()
    install_api(python)
    install_web()
    ensure_env_file()
    print('\n安装完成，下面是当前状态：\n', flush=True)
    doctor = subprocess.run([str(python), str(ROOT / 'scripts' / 'doctor.py')], cwd=ROOT)
    # Doctor failing only means keys are still empty; the install itself succeeded.
    sys.exit(0 if doctor.returncode in (0, 1) else doctor.returncode)


if __name__ == '__main__':
    main()
