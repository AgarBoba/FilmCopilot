"""The model registry: every image / video model the canvas can use, one JSON file each in
`models/` at the project root.

Adding a model is a data change, not a code change, when its provider already has an
adapter (see `providers/`). The file format is documented in docs/ADDING_MODELS.md and
checked here with messages meant for the agent or person writing the file.

A model file:
    id            unique, lowercase, e.g. "flux-kontext-pro"
    label         shown in the node's model menu
    kind          "image" or "video"
    provider      adapter name, e.g. "replicate" (providers/<name>.py)
    providerModel what that provider calls the model, e.g. "black-forest-labs/flux-kontext-pro"
    default       true for at most one model per kind: used by new nodes
    description   one or two sentences for the agent: what the model is good at
    inputs        prompt: provider field for the prompt text
                  images / videos: {field, max, single?} where reference images / videos go
    parameters    list of {key, label, type, field, default, options?|min?|max?}
                  type: enum | boolean | integer | number | string
    fixedInputs   optional constant provider inputs
"""
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT

MODELS_DIR = PROJECT_ROOT / 'models'
KINDS = ('image', 'video')
PARAM_TYPES = ('enum', 'boolean', 'integer', 'number', 'string')


class ModelFileError(ValueError):
    """A model file is malformed. The message says which file and what to fix."""


@dataclass(frozen=True)
class Parameter:
    key: str
    label: str
    type: str
    field: str
    default: Any
    options: tuple[dict[str, Any], ...] = ()
    minimum: float | None = None
    maximum: float | None = None

    def coerce(self, value: Any) -> tuple[Any, str | None]:
        """(value to use, problem or None). Values that don't fit fall back to the default."""
        if value is None:
            return self.default, None
        if self.type == 'enum':
            allowed = [option['value'] for option in self.options]
            for option in self.options:
                names = [option['value'], *option.get('aliases', [])]
                if any(value == name or str(value).lower() == str(name).lower() for name in names):
                    return option['value'], None
            return self.default, f"{self.key} 只能是 {' / '.join(map(str, allowed))}"
        if self.type == 'boolean':
            if isinstance(value, bool):
                return value, None
            return self.default, f'{self.key} 只能是 true 或 false'
        if self.type in ('integer', 'number'):
            try:
                number = int(value) if self.type == 'integer' else float(value)
            except (TypeError, ValueError):
                return self.default, f'{self.key} 要是数字'
            if isinstance(value, bool) or (self.type == 'integer' and float(value) != int(value)):
                return self.default, f'{self.key} 要是整数'
            if self.minimum is not None and number < self.minimum or self.maximum is not None and number > self.maximum:
                return self.default, f'{self.key} 要在 {self.minimum} 到 {self.maximum} 之间'
            return number, None
        return str(value), None

    def public(self) -> dict[str, Any]:
        data: dict[str, Any] = {'key': self.key, 'label': self.label, 'type': self.type, 'default': self.default}
        if self.options:
            data['options'] = list(self.options)
        if self.minimum is not None:
            data['min'] = self.minimum
        if self.maximum is not None:
            data['max'] = self.maximum
        return data


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    kind: str
    provider: str
    provider_model: str
    description: str
    prompt_field: str
    image_input: dict[str, Any] | None
    video_input: dict[str, Any] | None
    parameters: tuple[Parameter, ...]
    fixed_inputs: dict[str, Any] = field(default_factory=dict)
    default: bool = False
    source: str = ''

    def default_parameters(self) -> dict[str, Any]:
        return {parameter.key: parameter.default for parameter in self.parameters}

    def resolve_parameters(self, values: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
        """Every parameter of this model, filled with defaults; unknown keys are dropped."""
        values = values or {}
        resolved: dict[str, Any] = {}
        problems: list[str] = []
        for parameter in self.parameters:
            value, problem = parameter.coerce(values.get(parameter.key))
            resolved[parameter.key] = value
            if problem:
                problems.append(problem)
        return resolved, problems

    @property
    def max_images(self) -> int:
        return int((self.image_input or {}).get('max') or 0)

    @property
    def max_videos(self) -> int:
        return int((self.video_input or {}).get('max') or 0)

    def public(self) -> dict[str, Any]:
        """What the canvas and the agent see (no provider internals they don't need)."""
        return {
            'id': self.id, 'label': self.label, 'kind': self.kind, 'provider': self.provider,
            'providerModel': self.provider_model, 'description': self.description, 'default': self.default,
            'maxImages': self.max_images, 'maxVideos': self.max_videos,
            'parameters': [parameter.public() for parameter in self.parameters],
        }


def _require(data: dict[str, Any], key: str, kind: type | tuple[type, ...], where: str) -> Any:
    if key not in data:
        raise ModelFileError(f'{where}: 缺少 "{key}"')
    if not isinstance(data[key], kind):
        raise ModelFileError(f'{where}: "{key}" 类型不对')
    return data[key]


def parse_model(data: dict[str, Any], source: str = '<inline>') -> ModelSpec:
    where = source
    model_id = _require(data, 'id', str, where)
    if not model_id or model_id != model_id.strip().lower() or ' ' in model_id:
        raise ModelFileError(f'{where}: "id" 要小写、不带空格，例如 "flux-kontext-pro"')
    kind = _require(data, 'kind', str, where)
    if kind not in KINDS:
        raise ModelFileError(f'{where}: "kind" 只能是 image 或 video')
    inputs = _require(data, 'inputs', dict, where)
    prompt_field = _require(inputs, 'prompt', str, f'{where} inputs')
    media: dict[str, dict[str, Any] | None] = {}
    for name in ('images', 'videos'):
        spec = inputs.get(name)
        if spec is None:
            media[name] = None
            continue
        if not isinstance(spec, dict) or not isinstance(spec.get('field'), str):
            raise ModelFileError(f'{where}: inputs.{name} 要写成 {{"field": "...", "max": N}}')
        if not isinstance(spec.get('max', 1), int) or spec.get('max', 1) < 1:
            raise ModelFileError(f'{where}: inputs.{name}.max 要是正整数')
        media[name] = {'field': spec['field'], 'max': spec.get('max', 1), 'single': bool(spec.get('single'))}
    parameters = []
    seen: set[str] = set()
    for index, raw in enumerate(data.get('parameters') or []):
        at = f'{where} parameters[{index}]'
        key = _require(raw, 'key', str, at)
        if key in seen:
            raise ModelFileError(f'{at}: key "{key}" 重复')
        seen.add(key)
        kind_of = _require(raw, 'type', str, at)
        if kind_of not in PARAM_TYPES:
            raise ModelFileError(f'{at}: type 只能是 {", ".join(PARAM_TYPES)}')
        options = tuple(raw.get('options') or ())
        if kind_of == 'enum':
            if not options or not all(isinstance(o, dict) and 'value' in o for o in options):
                raise ModelFileError(f'{at}: enum 要有 options，写成 [{{"value": ..., "label": ...}}]')
            options = tuple(
                {'value': o['value'], 'label': str(o.get('label', o['value'])),
                 **({'aliases': list(o['aliases'])} if o.get('aliases') else {})}
                for o in options
            )
        if 'default' not in raw:
            raise ModelFileError(f'{at}: 缺少 "default"')
        parameter = Parameter(
            key=key, label=str(raw.get('label') or key), type=kind_of, field=str(raw.get('field') or key),
            default=raw['default'], options=options, minimum=raw.get('min'), maximum=raw.get('max'),
        )
        if parameter.coerce(parameter.default)[1]:
            raise ModelFileError(f'{at}: default 不在允许的取值里')
        parameters.append(parameter)
    return ModelSpec(
        id=model_id,
        label=str(data.get('label') or model_id),
        kind=kind,
        provider=_require(data, 'provider', str, where),
        provider_model=_require(data, 'providerModel', str, where),
        description=str(data.get('description') or ''),
        prompt_field=prompt_field,
        image_input=media['images'],
        video_input=media['videos'],
        parameters=tuple(parameters),
        fixed_inputs=dict(data.get('fixedInputs') or {}),
        default=bool(data.get('default')),
        source=source,
    )


class ModelRegistry:
    """Reads models/*.json, and re-reads when a file changes (no restart after adding one)."""

    def __init__(self, directory: Path = MODELS_DIR) -> None:
        self.directory = directory
        self._stamp: tuple = ()
        self._models: dict[str, ModelSpec] = {}
        self.errors: list[str] = []

    def _current_stamp(self) -> tuple:
        files = sorted(self.directory.glob('*.json')) if self.directory.exists() else []
        return tuple((path.name, path.stat().st_mtime_ns) for path in files)

    def _load(self) -> None:
        stamp = self._current_stamp()
        if stamp == self._stamp:
            return
        models: dict[str, ModelSpec] = {}
        errors: list[str] = []
        for name, _ in stamp:
            path = self.directory / name
            try:
                spec = parse_model(json.loads(path.read_text(encoding='utf-8')), f'models/{name}')
            except json.JSONDecodeError as error:
                errors.append(f'models/{name}: 不是合法的 JSON（第 {error.lineno} 行）')
                continue
            except ModelFileError as error:
                errors.append(str(error))
                continue
            if spec.id in models:
                errors.append(f'models/{name}: id "{spec.id}" 和 {models[spec.id].source} 重复')
                continue
            models[spec.id] = spec
        for kind in KINDS:
            defaults = [spec.id for spec in models.values() if spec.kind == kind and spec.default]
            if len(defaults) > 1:
                errors.append(f'{kind} 有多个 default：{", ".join(defaults)}（只保留一个）')
        self._models, self.errors, self._stamp = models, errors, stamp

    def all(self) -> list[ModelSpec]:
        self._load()
        return sorted(self._models.values(), key=lambda spec: (spec.kind, not spec.default, spec.label.lower()))

    def get(self, model_id: str | None) -> ModelSpec | None:
        self._load()
        return self._models.get(model_id or '')

    def default_for(self, kind: str) -> ModelSpec | None:
        candidates = [spec for spec in self.all() if spec.kind == kind]
        return next((spec for spec in candidates if spec.default), candidates[0] if candidates else None)

    def for_node(self, kind: str, model_id: str | None) -> ModelSpec | None:
        """The model a node uses: its own choice if it still exists and fits, else the default."""
        spec = self.get(model_id)
        if spec is not None and spec.kind == kind:
            return spec
        return self.default_for(kind)


_registry: ModelRegistry | None = None


def registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
