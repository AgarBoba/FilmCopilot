"""Tell the user when a node's result was made from inputs that have since changed upstream.

Results are always attached to their node. When a connected note is edited, an upstream
image is regenerated or a reference is connected / disconnected afterwards, the node gets
a list of short descriptions, shown as an "上游有更新" badge.
The node's own prompt and parameters are not reported: editing them is the user's next step.
"""
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .repositories import CanvasRepository


def upstream_changes(repository: 'CanvasRepository', canvas_id: str) -> dict[str, list[str]]:
    rows = repository._fetchall(
        '''
        SELECT n.id AS node_id, j.request_json
        FROM canvas_nodes n
        JOIN generation_jobs j
          ON j.canvas_id = n.canvas_id AND j.target_node_id = n.id
         AND j.output_asset_id = json_extract(n.data_json, '$.assetId')
        WHERE n.canvas_id = ? AND n.node_type IN ('image', 'video')
        ORDER BY j.created_at, j.id
        ''',
        (canvas_id,),
    )
    used = {row['node_id']: json.loads(row['request_json']) for row in rows}  # latest job wins
    result: dict[str, list[str]] = {}
    for node_id, before in used.items():
        try:
            now = repository.generation_snapshot(canvas_id, node_id)
        except Exception:
            continue
        changes = describe_changes(before, now)
        if changes:
            result[node_id] = changes
    return result


def describe_changes(before: dict[str, Any], now: dict[str, Any]) -> list[str]:
    changes: list[str] = []

    old_notes = {note['nodeId']: note for note in before.get('notePrompts') or []}
    new_notes = {note['nodeId']: note for note in now.get('notePrompts') or []}
    for node_id, note in new_notes.items():
        name = _name(note.get('title'), '便签')
        if node_id not in old_notes:
            changes.append(f'新连接了{name}')
        elif old_notes[node_id].get('text') != note.get('text'):
            changes.append(f'{name}的文字改了')
    for node_id, note in old_notes.items():
        if node_id not in new_notes:
            changes.append(f'{_name(note.get("title"), "便签")}已断开或清空')

    old_refs = before.get('references') or []
    new_refs = now.get('references') or []
    if all('sourceNodeId' in ref for ref in old_refs):
        old_by_node = {ref['sourceNodeId']: ref for ref in old_refs}
        new_by_node = {ref['sourceNodeId']: ref for ref in new_refs}
        for node_id, ref in new_by_node.items():
            name = _name(ref.get('sourceTitle'), '参考素材')
            if node_id not in old_by_node:
                changes.append(f'新连接了{name}')
            elif old_by_node[node_id].get('id') != ref.get('id'):
                changes.append(f'{name}的内容更新了')
        for node_id, ref in old_by_node.items():
            if node_id not in new_by_node:
                changes.append(f'{_name(ref.get("sourceTitle"), "参考素材")}已断开')
    else:
        # Jobs from before references recorded their source node: compare assets only.
        old_ids = {ref.get('id') for ref in old_refs}
        new_ids = {ref.get('id') for ref in new_refs}
        if new_ids - old_ids:
            changes.append(f'参考素材新增或更新了 {len(new_ids - old_ids)} 个')
        if old_ids - new_ids:
            changes.append(f'参考素材少了 {len(old_ids - new_ids)} 个')
    return changes


def _name(title: Any, fallback: str) -> str:
    title = str(title or '').strip()
    return f'「{title}」' if title else fallback
