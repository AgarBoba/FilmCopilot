"""Node checks: does what's connected to a node fit the node's model?

Second of three layers that keep a generation from failing on a model's input rules:
  1. the model guide (models/<id>.md) the agent reads before planning, in plain words;
  2. these checks, run on the node every time its inputs change; problems are stored
     (store.py) so the canvas shows them on the node and the agent sees them in get_canvas;
  3. the provider's own error after a failed generation, translated (providers/errors.py).

A check is a small rule named in the model JSON:
    "checks": [{"rule": "aspect_range", "min": 0.333, "max": 3}]
Every rule is a function in RULES below. A model's odd new requirement (say "sides must be
a multiple of 16") is usually one line in the JSON with an existing rule; a truly new kind of
rule is one function here. Rules nobody wrote yet are what layer 3 is for.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

TARGETS = ('images', 'videos')
KIND_OF_TARGET = {'images': 'image', 'videos': 'video'}
TARGET_LABEL = {'images': '参考图', 'videos': '参考视频'}


@dataclass(frozen=True)
class Problem:
    code: str
    message: str
    severity: str = 'error'  # error: generation is refused (no charge); warning: it runs anyway
    source_node_id: str | None = None

    def public(self) -> dict[str, Any]:
        data = {'code': self.code, 'message': self.message, 'severity': self.severity}
        if self.source_node_id:
            data['sourceNodeId'] = self.source_node_id
        return data


@dataclass(frozen=True)
class Rule:
    keys: dict[str, type | tuple[type, ...]]  # allowed settings and their types
    required: tuple[str, ...]
    run: Callable[[dict[str, Any], 'Inputs'], list[Problem]]
    describe: Callable[[dict[str, Any]], str]  # one line for people and the agent


@dataclass
class Inputs:
    """What a generation would send, in check-friendly form."""
    model_label: str
    prompt: str
    references: list[dict[str, Any]]  # asset dicts + sourceNodeId / sourceTitle, in connection order

    def of(self, target: str) -> list[dict[str, Any]]:
        kind = KIND_OF_TARGET[target]
        return [ref for ref in self.references if (ref.get('kind') or ref.get('asset_kind')) == kind]


def _name(ref: dict[str, Any]) -> str:
    title = ref.get('sourceTitle') or ''
    return f'「{title}」' if title else '一个参考'


def _number(value: float) -> str:
    return f'{value:g}'


def _ratio_text(value: float) -> str:
    if value >= 1:
        return f'{_number(round(value, 2))}:1'
    return f'1:{_number(round(1 / value, 2))}'


def _range_text(low: Any, high: Any, unit: str = '') -> str:
    if low is not None and high is not None:
        return f' {_number(low)}～{_number(high)}{unit}'
    if low is not None:
        return f'不小于 {_number(low)}{unit}'
    return f'不大于 {_number(high)}{unit}'


def _target(settings: dict[str, Any], default: str = 'images') -> str:
    return settings.get('target') or default


def _sized(inputs: Inputs, settings: dict[str, Any]) -> list[tuple[dict[str, Any], int, int]]:
    out = []
    for ref in inputs.of(_target(settings)):
        width, height = ref.get('width'), ref.get('height')
        if width and height:
            out.append((ref, int(width), int(height)))
    return out


def _aspect_range(settings: dict[str, Any], inputs: Inputs) -> list[Problem]:
    low, high = settings.get('min'), settings.get('max')
    problems = []
    for ref, width, height in _sized(inputs, settings):
        ratio = width / height
        if (low is not None and ratio < low - 1e-6) or (high is not None and ratio > high + 1e-6):
            problems.append(Problem(
                'aspect_range',
                f'{_name(ref)}的宽高比是 {_ratio_text(ratio)}（{width}×{height}），'
                f'{inputs.model_label} 要求{TARGET_LABEL[_target(settings)]}宽高比在 '
                f'{_ratio_text(low) if low else "…"}～{_ratio_text(high) if high else "…"} 之间。先裁剪再用，或换一个模型。',
                source_node_id=ref.get('sourceNodeId'),
            ))
    return problems


def _side_range(settings: dict[str, Any], inputs: Inputs) -> list[Problem]:
    low, high = settings.get('min'), settings.get('max')
    problems = []
    for ref, width, height in _sized(inputs, settings):
        short, long = min(width, height), max(width, height)
        if (low is not None and short < low) or (high is not None and long > high):
            problems.append(Problem(
                'side_range',
                f'{_name(ref)}是 {width}×{height}，{inputs.model_label} 要求{TARGET_LABEL[_target(settings)]}'
                f'每条边{_range_text(low, high, " 像素")}。',
                source_node_id=ref.get('sourceNodeId'),
            ))
    return problems


def _side_multiple(settings: dict[str, Any], inputs: Inputs) -> list[Problem]:
    step = int(settings['of'])
    problems = []
    for ref, width, height in _sized(inputs, settings):
        if width % step or height % step:
            problems.append(Problem(
                'side_multiple',
                f'{_name(ref)}是 {width}×{height}，{inputs.model_label} 要求{TARGET_LABEL[_target(settings)]}'
                f'的宽和高都是 {step} 的倍数。先裁剪成合适的尺寸再用。',
                source_node_id=ref.get('sourceNodeId'),
            ))
    return problems


def _max_pixels(settings: dict[str, Any], inputs: Inputs) -> list[Problem]:
    limit = settings['max']
    problems = []
    for ref, width, height in _sized(inputs, settings):
        if width * height > limit:
            problems.append(Problem(
                'max_pixels',
                f'{_name(ref)}有 {width * height:,} 像素，{inputs.model_label} 最多接受 {int(limit):,} 像素。',
                source_node_id=ref.get('sourceNodeId'),
            ))
    return problems


def _duration_range(settings: dict[str, Any], inputs: Inputs) -> list[Problem]:
    low, high = settings.get('min'), settings.get('max')
    problems = []
    for ref in inputs.of(_target(settings, 'videos')):
        seconds = ref.get('duration_seconds')
        if seconds is None:
            continue
        if (low is not None and seconds < low) or (high is not None and seconds > high):
            problems.append(Problem(
                'duration_range',
                f'{_name(ref)}长 {seconds:.1f} 秒，{inputs.model_label} 要求参考视频时长{_range_text(low, high, " 秒")}。',
                source_node_id=ref.get('sourceNodeId'),
            ))
    return problems


def _prompt_length(settings: dict[str, Any], inputs: Inputs) -> list[Problem]:
    limit = int(settings['max'])
    length = len(inputs.prompt or '')
    if length <= limit:
        return []
    return [Problem('prompt_length', f'Prompt（连同连进来的文本节点）有 {length} 个字，'
                                     f'{inputs.model_label} 最多 {limit} 个字。删减一些再生成。')]


def _requires(settings: dict[str, Any], inputs: Inputs) -> list[Problem]:
    problems = []
    for target in TARGETS:
        need = settings.get(target)
        have = len(inputs.of(target))
        if need and have < need:
            problems.append(Problem(
                'requires',
                f'{inputs.model_label} 至少要连 {need} 个{TARGET_LABEL[target]}，现在有 {have} 个。'))
    return problems


NUMBER = (int, float)
RULES: dict[str, Rule] = {
    'aspect_range': Rule(
        {'min': NUMBER, 'max': NUMBER, 'target': str}, (), _aspect_range,
        lambda s: f"{TARGET_LABEL[_target(s)]}宽高比 {_ratio_text(s['min']) if s.get('min') else '…'}～"
                  f"{_ratio_text(s['max']) if s.get('max') else '…'}"),
    'side_range': Rule(
        {'min': NUMBER, 'max': NUMBER, 'target': str}, (), _side_range,
        lambda s: f"{TARGET_LABEL[_target(s)]}每条边{_range_text(s.get('min'), s.get('max'), ' 像素')}"),
    'side_multiple': Rule(
        {'of': int, 'target': str}, ('of',), _side_multiple,
        lambda s: f"{TARGET_LABEL[_target(s)]}宽和高都是 {s['of']} 的倍数"),
    'max_pixels': Rule(
        {'max': NUMBER, 'target': str}, ('max',), _max_pixels,
        lambda s: f"{TARGET_LABEL[_target(s)]}最多 {int(s['max']):,} 像素"),
    'duration_range': Rule(
        {'min': NUMBER, 'max': NUMBER, 'target': str}, (), _duration_range,
        lambda s: f"参考视频时长{_range_text(s.get('min'), s.get('max'), ' 秒')}"),
    'prompt_length': Rule(
        {'max': int}, ('max',), _prompt_length,
        lambda s: f"Prompt 最多 {s['max']} 个字"),
    'requires': Rule(
        {'images': int, 'videos': int}, (), _requires,
        lambda s: '至少要连 ' + '、'.join(f"{s[t]} 个{TARGET_LABEL[t]}" for t in TARGETS if s.get(t))),
}


def validate_checks(raw: Any, where: str) -> tuple[dict[str, Any], ...]:
    """The `checks` list of a model file, validated. Raises ValueError with a fix-it message."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f'{where}: "checks" 要写成列表，例如 [{{"rule": "aspect_range", "min": 0.333, "max": 3}}]')
    checks = []
    for index, item in enumerate(raw):
        at = f'{where} checks[{index}]'
        if not isinstance(item, dict) or not isinstance(item.get('rule'), str):
            raise ValueError(f'{at}: 每条要有 "rule"')
        rule = RULES.get(item['rule'])
        if rule is None:
            raise ValueError(f'{at}: 没有叫 "{item["rule"]}" 的检查，可用的有：{", ".join(RULES)}'
                             '（真的需要新规则时，在 api/app/checks/__init__.py 里加一个函数）')
        settings = {key: value for key, value in item.items() if key != 'rule'}
        unknown = [key for key in settings if key not in rule.keys]
        if unknown:
            raise ValueError(f'{at}: {item["rule"]} 不认识 {", ".join(unknown)}，只能写 {", ".join(rule.keys)}')
        missing = [key for key in rule.required if key not in settings]
        if missing:
            raise ValueError(f'{at}: {item["rule"]} 缺少 {", ".join(missing)}')
        for key, value in settings.items():
            if isinstance(value, bool) or not isinstance(value, rule.keys[key]):
                raise ValueError(f'{at}: {key} 类型不对')
        if 'target' in settings and settings['target'] not in TARGETS:
            raise ValueError(f'{at}: target 只能是 images 或 videos')
        if not settings and item['rule'] in ('aspect_range', 'side_range', 'duration_range', 'requires'):
            raise ValueError(f'{at}: {item["rule"]} 至少要写一个范围')
        checks.append({'rule': item['rule'], **settings})
    return tuple(checks)


def describe_check(check: dict[str, Any]) -> str:
    return RULES[check['rule']].describe(check)


def check_inputs(model: Any, snapshot: dict[str, Any]) -> list[Problem]:
    """Everything wrong with sending this generation snapshot to this model."""
    references = list(snapshot.get('references') or [])
    if snapshot.get('selfReference'):
        references = [snapshot['selfReference'], *references]
    inputs = Inputs(model.label, str(snapshot.get('prompt') or ''), references)
    problems: list[Problem] = []
    for target, spec in (('images', model.image_input), ('videos', model.video_input)):
        items = inputs.of(target)
        if not items:
            continue
        if spec is None:
            problems.append(Problem(
                'unsupported_input',
                f'{model.label} 不接受{TARGET_LABEL[target]}，连着的 {len(items)} 个不会发给模型。'
                '换一个接受它的模型，或断开这些连线。'))
            continue
        if len(items) > spec['max']:
            dropped = '、'.join(_name(ref) for ref in items[spec['max']:])
            problems.append(Problem(
                'too_many',
                f'{model.label} 最多 {spec["max"]} 个{TARGET_LABEL[target]}，现在连了 {len(items)} 个，'
                f'按连线顺序多出来的 {dropped} 不会发给模型。', severity='warning'))
    _, parameter_problems = model.resolve_parameters(snapshot.get('parameters'))
    problems.extend(Problem('parameter', f'参数 {text}，生成时会用默认值', severity='warning')
                    for text in parameter_problems)
    for check in model.checks:
        settings = {key: value for key, value in check.items() if key != 'rule'}
        problems.extend(RULES[check['rule']].run(settings, inputs))
    return problems


def blocking(problems: list[Problem]) -> list[Problem]:
    return [problem for problem in problems if problem.severity == 'error']
