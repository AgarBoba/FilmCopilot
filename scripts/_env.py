"""Shared helpers for the scripts in this folder. Standard library only, so any python3 can
import it before the project's .venv exists.

Secrets: .env values are loaded into os.environ for the process, and only ever reported as
"set" / "not set". Nothing here prints a value.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / '.env'
ENV_EXAMPLE = ROOT / '.env.example'
VENV = ROOT / '.venv'
MIN_PYTHON = (3, 11)


def venv_python() -> Path:
    windows = VENV / 'Scripts' / 'python.exe'
    return windows if windows.exists() else VENV / 'bin' / 'python'


def reexec_in_venv() -> None:
    """Run the calling script with the project's .venv python (where the API code and its
    dependencies are installed), unless it already is. No-op when there is no .venv yet."""
    python = venv_python()
    if not python.exists() or Path(sys.prefix).resolve() == VENV.resolve():
        return
    try:
        os.execv(str(python), [str(python), *sys.argv])
    except OSError:
        pass  # .venv made on another machine / broken: carry on; doctor will say so


def parse_env_file(path: Path = ENV_FILE) -> tuple[dict[str, str], list[int]]:
    """(settings, numbers of lines that are not KEY=VALUE). Never prints anything."""
    values: dict[str, str] = {}
    bad_lines: list[int] = []
    if not path.exists():
        return values, bad_lines
    for number, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].strip()
        key, sep, value = line.partition('=')
        key = key.strip()
        if not sep or not key.replace('_', '').isalnum() or not (key[0].isalpha() or key[0] == '_'):
            bad_lines.append(number)
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        values[key] = value
    return values, bad_lines


def load_env() -> list[int]:
    """Put .env settings into os.environ, overriding the shell like dev.sh does.
    Returns the numbers of malformed lines."""
    values, bad_lines = parse_env_file()
    os.environ.update(values)
    return bad_lines


def add_api_to_path() -> None:
    api = str(ROOT / 'api')
    if api not in sys.path:
        sys.path.insert(0, api)
