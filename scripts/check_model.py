#!/usr/bin/env python3
"""Check a model from models/: is the file valid, is its provider wired up, what will be sent.

    python3 scripts/check_model.py <model-id>             # free: validate + show the request
    python3 scripts/check_model.py <model-id> --run       # real generation (costs money: ask the user first)
        [--prompt "..."] [--image ref.png ...] [--video ref.mp4 ...] [--param key=value ...]
    python3 scripts/check_model.py --all                  # validate every model (free)

--run saves the result under data/model-checks/ and prints the path.
Keys are only reported as set / not set.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import ROOT, add_api_to_path, load_env, reexec_in_venv  # noqa: E402


def parse_value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def describe(spec, providers) -> bool:
    ready = providers.has_adapter(spec.provider)
    missing = providers.missing_env(spec.provider) if ready else []
    print(f'模型 {spec.id} · {spec.label} · {spec.kind}' + (' · 默认' if spec.default else ''))
    print(f'  provider: {spec.provider} → {spec.provider_model}')
    if not ready:
        print(f'  ✗ 没有 api/app/providers/{spec.provider}.py：按 docs/ADDING_MODELS.md 从 _template.py 复制一份来写')
    elif missing:
        print(f"  ✗ .env 缺 {', '.join(missing)}（让用户自己填，不要在对话里要）")
    else:
        print('  ✓ provider 对接代码和密钥都在')
    return ready and not missing


def main() -> None:
    reexec_in_venv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('model', nargs='?')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--run', action='store_true', help='真的生成一次（会花钱）')
    parser.add_argument('--prompt', default='a small red cube on a wooden table, soft daylight')
    parser.add_argument('--image', action='append', default=[], type=Path)
    parser.add_argument('--video', action='append', default=[], type=Path)
    parser.add_argument('--param', action='append', default=[], metavar='KEY=VALUE')
    args = parser.parse_args()

    load_env()
    add_api_to_path()
    from app import providers
    from app.models_registry import registry
    from app.providers.base import GenerationRequest, build_inputs

    models = registry()
    for error in models.errors:
        print(f'✗ {error}')
    if args.all or not args.model:
        ok = not models.errors
        for spec in models.all():
            ok = describe(spec, providers) and ok
        sys.exit(0 if ok else 1)

    spec = models.get(args.model)
    if spec is None:
        known = ', '.join(s.id for s in models.all())
        sys.exit(f'✗ 没有模型 {args.model!r}（现有: {known}）')
    ready = describe(spec, providers)

    values = {}
    for item in args.param:
        key, _, value = item.partition('=')
        values[key] = parse_value(value)
    parameters, problems = spec.resolve_parameters(values)
    unknown = sorted(set(values) - {p.key for p in spec.parameters})
    for problem in problems:
        print(f'  ! {problem}（用了默认值）')
    if unknown:
        print(f"  ! 这个模型没有参数 {', '.join(unknown)}（可用: {', '.join(p.key for p in spec.parameters)}）")
    for path in [*args.image, *args.video]:
        if not path.exists():
            sys.exit(f'✗ 找不到文件 {path}')
    request = GenerationRequest(prompt=args.prompt, images=args.image, videos=args.video, parameters=parameters)
    preview = build_inputs(spec, request, lambda path: f'<file {Path(path).name}>')
    print('  会发给 provider 的输入:')
    print('    ' + json.dumps(preview, ensure_ascii=False, indent=2).replace('\n', '\n    '))
    if not args.run:
        print('没有真的生成。确认用户同意花钱后，加 --run 跑一次真实生成。')
        sys.exit(0 if ready and not models.errors else 1)
    if not ready:
        sys.exit('✗ 先解决上面的 ✗ 再 --run')

    provider = providers.get_provider(spec.provider)
    started = time.time()
    prediction = provider.create_prediction(spec, request)
    print(f'  已提交，任务 {prediction.id}，等待结果…', flush=True)
    while True:
        status = provider.get_prediction(prediction.id)
        state = status.status.lower()
        if state in ('succeeded', 'failed', 'canceled', 'cancelled'):
            break
        if time.time() - started > 1800:
            sys.exit('✗ 30 分钟还没好，放弃等待')
        time.sleep(3)
    if state != 'succeeded':
        sys.exit(f'✗ 生成失败: {status.error or state}')
    if not status.outputs:
        sys.exit('✗ provider 说成功了但没有输出：检查 get_prediction 里 outputs 取的字段')
    output = status.outputs[0]
    suffix = Path(str(output).split('?')[0]).suffix or ('.mp4' if spec.kind == 'video' else '.png')
    destination = ROOT / 'data' / 'model-checks' / f'{spec.id}-{int(started)}{suffix}'
    provider.download_output(output, destination)
    print(f'✓ 生成成功，用时 {time.time() - started:.0f} 秒 → {destination.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
