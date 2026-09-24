#!/usr/bin/env python3
"""Draft a models/*.json file for a model on Replicate, from the model's own input schema.

    python3 scripts/add_model.py black-forest-labs/flux-kontext-pro
    python3 scripts/add_model.py owner/name --kind video --id my-id --default
    python3 scripts/add_model.py owner/name --schema schema.json    # offline: a saved openapi_schema

Needs REPLICATE_API_TOKEN in .env (unless --schema). The draft is a starting point: the script
lists what it guessed and what it skipped, and whoever runs it (usually an agent) should review
the file — labels, which parameters are worth showing, the description — then run
`python3 scripts/check_model.py <id>`. Models on other providers are written by hand; see
docs/ADDING_MODELS.md.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import ROOT, add_api_to_path, load_env, reexec_in_venv  # noqa: E402

# Replicate fields that are never worth a control on the node.
SKIP_FIELDS = {'seed', 'disable_safety_checker', 'safety_tolerance', 'output_quality', 'go_fast',
               'num_outputs', 'return_images', 'webhook', 'prompt_upsampling', 'enable_safety_checker'}
IMAGE_WORDS = ('image', 'img', 'frame', 'reference', 'photo', 'input')
PREFERRED_IMAGE_FIELDS = ('image_input', 'reference_images', 'input_images', 'images', 'input_image',
                          'image', 'image_url', 'start_image', 'first_frame_image')


def camel(name: str) -> str:
    head, *rest = name.split('_')
    return head + ''.join(part[:1].upper() + part[1:] for part in rest)


def humanize(name: str) -> str:
    text = name.replace('_', ' ').strip()
    return text[:1].upper() + text[1:]


def resolve(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    """Inline `allOf: [{$ref}]` / `$ref` the way Replicate writes enums."""
    merged = dict(schema)
    refs = [item for item in schema.get('allOf', []) if '$ref' in item]
    if '$ref' in schema:
        refs.append({'$ref': schema['$ref']})
    for ref in refs:
        target = components.get(ref['$ref'].rsplit('/', 1)[-1], {})
        merged = {**target, **{k: v for k, v in merged.items() if k not in ('allOf', '$ref')}}
    return merged


def is_uri(prop: dict[str, Any]) -> bool:
    return prop.get('format') == 'uri' or (prop.get('type') == 'array' and prop.get('items', {}).get('format') == 'uri')


def draft_from_openapi(provider_model: str, openapi: dict[str, Any], *, kind: str | None = None,
                       model_id: str | None = None, description: str = '') -> tuple[dict[str, Any], list[str]]:
    """(model file data, notes for the reviewer)."""
    components = openapi.get('components', {}).get('schemas', {})
    input_schema = components.get('Input') or {}
    raw_props = input_schema.get('properties') or {}
    if not raw_props:
        raise ValueError('schema 里没有 Input.properties：确认这是 Replicate 的 openapi_schema')
    props = {name: resolve(prop, components) for name, prop in raw_props.items()}
    order = sorted(props, key=lambda name: props[name].get('x-order', 999))
    notes: list[str] = []

    prompt_field = 'prompt' if 'prompt' in props else next(
        (name for name in order if 'prompt' in name and props[name].get('type') == 'string'), None)
    if not prompt_field:
        raise ValueError('找不到提示词字段（没有 prompt）：这个模型可能不是文生图/视频模型，需要手写')

    name_part = provider_model.split('/')[-1]
    if kind is None:
        output = json.dumps(components.get('Output', {})).lower()
        looks_video = 'video' in name_part.lower() or any(k in props for k in ('duration', 'fps', 'num_frames')) or '.mp4' in output
        kind = 'video' if looks_video else 'image'
        notes.append(f'kind 猜的是 {kind}；不对就用 --kind 重跑')

    uri_fields = [name for name in order if is_uri(props[name])]
    video_fields = [name for name in uri_fields if 'video' in name]
    audio_fields = [name for name in uri_fields if 'audio' in name]
    image_fields = [name for name in uri_fields if name not in video_fields + audio_fields
                    and any(word in name for word in IMAGE_WORDS)]
    inputs: dict[str, Any] = {'prompt': prompt_field}

    def media(name: str) -> dict[str, Any]:
        prop = props[name]
        if prop.get('type') == 'array':
            return {'field': name, 'max': int(prop.get('maxItems') or 4)}
        return {'field': name, 'max': 1, 'single': True}

    if image_fields:
        chosen = next((name for name in PREFERRED_IMAGE_FIELDS if name in image_fields), image_fields[0])
        inputs['images'] = media(chosen)
        if 'maxItems' not in props[chosen] and props[chosen].get('type') == 'array':
            notes.append(f'参考图上限没写在 schema 里，先填了 4：看模型页确认 {chosen} 最多几张')
        others = [name for name in image_fields if name != chosen]
        if others:
            notes.append(f"参考图用的是 {chosen}；另外还有 {', '.join(others)} 没接（画布只接一个图片入口，"
                         '如首尾帧这种需要的话要改代码）')
    if video_fields:
        inputs['videos'] = media(video_fields[0])
        if len(video_fields) > 1:
            notes.append(f"参考视频用的是 {video_fields[0]}；{', '.join(video_fields[1:])} 没接")
    if audio_fields:
        notes.append(f"音频输入 {', '.join(audio_fields)} 画布暂不支持，没接")

    parameters: list[dict[str, Any]] = []
    for name in order:
        prop = props[name]
        if name == prompt_field or is_uri(prop):
            continue
        if name in SKIP_FIELDS:
            notes.append(f'跳过 {name}（一般不需要在节点上调）')
            continue
        label = humanize(prop.get('title') or name)
        param: dict[str, Any] = {'key': camel(name), 'label': label, 'field': name}
        default = prop.get('default')
        if 'enum' in prop:
            values = list(prop['enum'])
            param.update(type='enum', default=default if default in values else values[0],
                         options=[{'value': value, 'label': humanize(value) if isinstance(value, str) and '_' in value else str(value)}
                                  for value in values])
        elif prop.get('type') == 'boolean':
            param.update(type='boolean', default=bool(default))
        elif prop.get('type') in ('integer', 'number'):
            if default is None:
                notes.append(f'跳过 {name}（没有默认值）')
                continue
            param.update(type=prop['type'], default=default)
            if 'minimum' in prop:
                param['min'] = prop['minimum']
            if 'maximum' in prop:
                param['max'] = prop['maximum']
        elif prop.get('type') == 'string':
            if name in ('negative_prompt',) or default:
                param.update(type='string', default=default or '')
            else:
                notes.append(f'跳过 {name}（自由文本，没有默认值）')
                continue
        else:
            notes.append(f"跳过 {name}（类型 {prop.get('type')} 不支持）")
            continue
        parameters.append(param)

    data = {
        'id': model_id or re.sub(r'[^a-z0-9.]+', '-', name_part.lower()).strip('-'),
        'label': humanize(name_part.replace('-', ' ')).title(),
        'kind': kind,
        'provider': 'replicate',
        'providerModel': provider_model,
        'default': False,
        'description': (description or '').strip()[:200],
        'inputs': inputs,
        'parameters': parameters,
    }
    notes.append('description 是模型页原文：改成一两句中文，说清它擅长什么（画布里的 Agent 靠它选模型）')
    notes.append('label 和参数的 label 可以改得更好读；参数太多就删掉不常用的')
    return data, notes


def fetch_replicate(provider_model: str) -> tuple[dict[str, Any], str]:
    token = os.getenv('REPLICATE_API_TOKEN')
    if not token:
        sys.exit('✗ .env 里没有 REPLICATE_API_TOKEN：让用户填上，或者用 --schema 传入保存好的 schema')
    request = Request(f'https://api.replicate.com/v1/models/{provider_model}',
                      headers={'Authorization': f'Bearer {token}'})
    try:
        with urlopen(request, timeout=30) as response:
            model = json.load(response)
    except HTTPError as error:
        hint = {401: '令牌无效', 404: '没有这个模型（检查 owner/name 拼写）'}.get(error.code, '')
        sys.exit(f'✗ Replicate 返回 {error.code} {hint}')
    version = model.get('latest_version') or {}
    schema = version.get('openapi_schema')
    if not schema:
        sys.exit('✗ 这个模型没有公开的输入 schema，只能按模型页手写（见 docs/ADDING_MODELS.md）')
    return schema, model.get('description') or ''


def main() -> None:
    reexec_in_venv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('model', help='Replicate 上的 owner/name')
    parser.add_argument('--kind', choices=('image', 'video'))
    parser.add_argument('--id', dest='model_id')
    parser.add_argument('--default', action='store_true', help='设为这个 kind 的默认模型（会取消原来的默认）')
    parser.add_argument('--schema', type=Path, help='离线：保存好的 openapi_schema JSON')
    parser.add_argument('--force', action='store_true', help='覆盖已有的同名文件')
    args = parser.parse_args()
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', args.model):
        sys.exit('✗ 模型名要写成 owner/name，例如 black-forest-labs/flux-kontext-pro')

    load_env()
    if args.schema:
        schema, description = json.loads(args.schema.read_text(encoding='utf-8')), ''
    else:
        schema, description = fetch_replicate(args.model)
    try:
        data, notes = draft_from_openapi(args.model, schema, kind=args.kind, model_id=args.model_id,
                                         description=description)
    except ValueError as error:
        sys.exit(f'✗ {error}')

    add_api_to_path()
    from app.models_registry import MODELS_DIR, ModelFileError, parse_model, registry
    try:
        parse_model(data, 'draft')
    except ModelFileError as error:
        sys.exit(f'✗ 草稿没通过校验（{error}）：需要手动写，见 docs/ADDING_MODELS.md')
    path = MODELS_DIR / f"{data['id']}.json"
    if path.exists() and not args.force:
        sys.exit(f'✗ {path.relative_to(ROOT)} 已存在：换个 --id，或加 --force 覆盖')
    if args.default:
        data['default'] = True
        for other in registry().all():
            if other.kind == data['kind'] and other.default and other.id != data['id']:
                other_path = ROOT / other.source
                raw = json.loads(other_path.read_text(encoding='utf-8'))
                raw['default'] = False
                other_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                notes.append(f'原默认模型 {other.id} 已改成非默认')
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print(f"✓ 写好了 {path.relative_to(ROOT)}（{data['kind']}，{len(data['parameters'])} 个参数）")
    print('  输入: ' + ', '.join(f'{k}→{v if isinstance(v, str) else v["field"]}' for k, v in data['inputs'].items()))
    print('  参数: ' + (', '.join(p['field'] for p in data['parameters']) or '无'))
    print('需要检查：')
    for note in notes:
        print(f'  - {note}')
    print(f"然后运行: python3 scripts/check_model.py {data['id']}")


if __name__ == '__main__':
    main()
