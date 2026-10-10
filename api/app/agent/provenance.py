"""Where the picture a node shows came from, and whether the node's settings still match it.

A node's Prompt, model and parameters are its settings for the *next* generation. Once the user
edits them (or switches back to an older version), they no longer describe the picture on
screen, and an agent reading only the settings would misread the picture. node_versions records,
for every picture a node has shown, how it got there (generated / uploaded / copied ...) and, for
generations, which job made it; the job's request has the settings it was made with.

Only differences in the node's *own* settings are reported here; changes upstream (connected
notes and references) are upstream.py's "上游有更新".
"""
import json
from typing import Any

from ..db import Database
from ..models_registry import registry as model_registry

SOURCE_LABELS = {'generated': '生成', 'uploaded': '上传', 'copied': '复制', 'restored': '切回旧版', 'edited': '其他',
                 'cropped': '裁剪'}


def origins(database: Database, canvas_id: str) -> dict[tuple[str, str], dict[str, Any]]:
    """(node id, asset id) -> how that node got that picture. Nodes from before version tracking
    have no rows yet (get_node builds them); they are simply left out."""
    with database.connection() as connection:
        rows = connection.execute(
            '''SELECT v.node_id, v.asset_id, v.version, v.source, v.prompt, v.parameters_json, v.model,
                      j.request_json
               FROM node_versions v LEFT JOIN generation_jobs j ON j.id = v.job_id
               WHERE v.canvas_id = ?''',
            (canvas_id,),
        ).fetchall()
    return {(row['node_id'], row['asset_id']): _origin(dict(row)) for row in rows}


def _origin(row: dict[str, Any]) -> dict[str, Any]:
    try:
        request = json.loads(row.get('request_json') or '{}')
    except ValueError:
        request = {}
    # The version keeps the prompt as sent, with connected notes in front; compare the node's own part.
    if 'nodePrompt' in request:
        node_prompt = request['nodePrompt']
    elif row.get('request_json') and not request.get('notePrompts'):
        node_prompt = request.get('prompt', row.get('prompt'))
    else:
        node_prompt = None  # can't tell which part was the node's own
    try:
        parameters = json.loads(row['parameters_json']) if row.get('parameters_json') else None
    except ValueError:
        parameters = None
    return {
        'version': row.get('version'),
        'source': row.get('source') or 'edited',
        'nodePrompt': node_prompt,
        'model': row.get('model'),
        'parameters': parameters,
    }


def changed_settings(origin: dict[str, Any] | None, node_type: str, data: dict[str, Any]) -> list[str]:
    """Which of the node's settings differ from what its current picture was generated with:
    a subset of ['Prompt', '模型', '参数']. Empty when they match or it can't be told."""
    if not origin or origin['source'] != 'generated':
        return []
    changed: list[str] = []
    if origin['nodePrompt'] is not None and str(origin['nodePrompt']).strip() != str(data.get('prompt') or '').strip():
        changed.append('Prompt')
    spec = model_registry().for_node(node_type, data.get('model'))
    if spec is None or not origin['model']:
        return changed
    if origin['model'] != spec.id:
        changed.append('模型')  # parameters of different models aren't comparable
    elif origin['parameters'] is not None:
        now, _ = spec.resolve_parameters(data.get('parameters'))
        before, _ = spec.resolve_parameters(origin['parameters'])
        if now != before:
            changed.append('参数')
    return changed


def short_hint(origin: dict[str, Any] | None, changed: list[str]) -> str:
    """The few words get_canvas adds to a node's line, or ''."""
    if not origin:
        return ''
    if origin['source'] == 'uploaded':
        return '画面是上传的'
    if changed:
        return f"{'、'.join(changed)}改过，画面还是旧的"
    return ''


def detail_lines(origin: dict[str, Any] | None, changed: list[str], node_type: str) -> list[str]:
    """What get_node says about where the picture came from."""
    if not origin:
        return []
    source = origin['source']
    if source == 'uploaded':
        return ['画面来源：用户上传（Prompt 不是这张画面的描述，要知道画面内容看「画面描述」或用 view_asset）']
    if source == 'copied':
        return ['画面来源：从别的节点复制来的']
    if source != 'generated':
        return []
    lines = ['画面来源：生成']
    if changed:
        then: list[str] = []
        if 'Prompt' in changed:
            then.append(f"Prompt：{origin['nodePrompt'] or '（空）'}")
        if '模型' in changed:
            spec = model_registry().get(origin['model'])
            then.append(f"模型：{spec.label} [{spec.id}]" if spec else f"模型：{origin['model']}（已下线）")
        if '参数' in changed:
            then.append(f"参数：{origin['parameters']}")
        lines.append(
            f"注意：{'、'.join(changed)}改过，画面还是旧的（上面是节点现在的设置，还没重新生成）。"
            '生成这张画面时用的是——' + '；'.join(then)
        )
    return lines
