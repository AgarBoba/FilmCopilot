"""Provider adapters, looked up by the "provider" name in a model file.

Each adapter is a module here (e.g. replicate.py) with:
    ENV_KEYS     the .env settings it needs, e.g. ("REPLICATE_API_TOKEN",)
    from_env()   returns a ready adapter (raising ProviderNotConfigured is fine later, on use)
"""
import importlib
import os
import re
from types import ModuleType
from typing import Any

_cache: dict[str, Any] = {}


def adapter_module(name: str) -> ModuleType:
    if not re.fullmatch(r'[a-z][a-z0-9_]*', name or '') or name.startswith('_'):
        raise ValueError(f'provider 名称不合法：{name!r}')
    try:
        return importlib.import_module(f'{__name__}.{name}')
    except ModuleNotFoundError as error:
        raise ValueError(f'没有 provider「{name}」：需要先在 api/app/providers/{name}.py 写对接代码') from error


def get_provider(name: str) -> Any:
    """One adapter instance per provider per process."""
    if name not in _cache:
        _cache[name] = adapter_module(name).from_env()
    return _cache[name]


def has_adapter(name: str) -> bool:
    try:
        adapter_module(name)
    except ValueError:
        return False
    return True


def missing_env(name: str) -> list[str]:
    """Settings this provider needs that are not filled in (names only, never values)."""
    try:
        keys = getattr(adapter_module(name), 'ENV_KEYS', ())
    except ValueError:
        return []
    return [key for key in keys if not os.getenv(key)]
