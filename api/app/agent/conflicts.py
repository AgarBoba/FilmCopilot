"""Which of the user's concurrent edits actually get in the way of an agent step.

The agent keeps `seen`: the canvas as it last looked at it, plus its own changes. Before each
write we diff `seen` against the live canvas and only stop when the user changed something
that step depends on. Moving other nodes, panning, editing unrelated nodes, or generation
jobs finishing never block the agent.

Change aspects per node:
    gone        node was deleted
    layout      moved or resized
    title       renamed
    prompt      prompt (image/video) or text (note) changed
    parameters  generation parameters changed
    media       image/video replaced by the user (generation results don't count)
    inputs      an incoming connection was added or removed
"""
from typing import Any

CanvasState = dict[str, dict[str, dict[str, Any]]]

ASPECT_LABELS = {
    'gone': '删除了', 'layout': '移动了', 'title': '改了名字', 'prompt': '改了文字/Prompt',
    'parameters': '改了参数', 'media': '换了图片/视频', 'inputs': '改了连线',
}
DATA_ASPECTS = {'title': 'title', 'prompt': 'prompt', 'content': 'prompt', 'parameters': 'parameters', 'model': 'parameters', 'assetId': 'media'}


def node_changes(seen: CanvasState, current: CanvasState, generated_assets: set[str]) -> dict[str, set[str]]:
    """node id -> aspects changed since `seen`. New nodes are left out: nothing depends on them yet."""
    changes: dict[str, set[str]] = {}
    old_nodes, new_nodes = seen['node'], current['node']
    for node_id, before in old_nodes.items():
        after = new_nodes.get(node_id)
        if after is None:
            changes.setdefault(node_id, set()).add('gone')
            continue
        if any(before.get(key) != after.get(key) for key in ('x', 'y', 'width', 'height')):
            changes.setdefault(node_id, set()).add('layout')
        old_data, new_data = before.get('data') or {}, after.get('data') or {}
        for key, aspect in DATA_ASPECTS.items():
            if old_data.get(key) == new_data.get(key):
                continue
            if key == 'assetId' and new_data.get(key) in generated_assets:
                continue  # a generation finished; not something the user edited
            changes.setdefault(node_id, set()).add(aspect)
    old_edges, new_edges = seen['edge'], current['edge']
    for edge_id in old_edges.keys() ^ new_edges.keys():
        edge = old_edges.get(edge_id) or new_edges[edge_id]
        if edge['target'] in old_nodes:
            changes.setdefault(edge['target'], set()).add('inputs')
    return changes


def blocking(changes: dict[str, set[str]], deps: dict[str, set[str]]) -> dict[str, set[str]]:
    """The part of `changes` this step depends on."""
    hits = {node_id: changes.get(node_id, set()) & aspects for node_id, aspects in deps.items()}
    return {node_id: aspects for node_id, aspects in hits.items() if aspects}


def apply_changes(seen: CanvasState, before: CanvasState, after: CanvasState) -> None:
    """Fold the agent's own change (before -> after) into `seen`, leaving other drift alone."""
    for kind in ('node', 'edge'):
        for entity_id in before[kind].keys() | after[kind].keys():
            old, new = before[kind].get(entity_id), after[kind].get(entity_id)
            if old == new:
                continue
            known = seen[kind].get(entity_id)
            if new is None:
                seen[kind].pop(entity_id, None)
            elif kind == 'node' and old is not None and known is not None:
                # Only the fields this step changed; a concurrent user move stays "unseen".
                merged = {**known, **{key: value for key, value in new.items() if key != 'data' and old.get(key) != value}}
                old_data, new_data = old.get('data') or {}, new.get('data') or {}
                data = dict(known.get('data') or {})
                for key in old_data.keys() | new_data.keys():
                    if old_data.get(key) != new_data.get(key):
                        if key in new_data:
                            data[key] = new_data[key]
                        else:
                            data.pop(key, None)
                merged['data'] = data
                seen[kind][entity_id] = merged
            else:
                seen[kind][entity_id] = new


def refresh(seen: CanvasState, current: CanvasState, node_ids: set[str] | None = None) -> None:
    """The agent just looked at these nodes (all when None): take their live state, with their edges."""
    if node_ids is None:
        seen['node'] = dict(current['node'])
        seen['edge'] = dict(current['edge'])
        return
    for node_id in node_ids:
        if node_id in current['node']:
            seen['node'][node_id] = current['node'][node_id]
        else:
            seen['node'].pop(node_id, None)
    for edges in (seen['edge'], current['edge']):
        for edge_id, edge in list(edges.items()):
            if edge['source'] in node_ids or edge['target'] in node_ids:
                if edge_id in current['edge']:
                    seen['edge'][edge_id] = current['edge'][edge_id]
                else:
                    seen['edge'].pop(edge_id, None)


def describe(hits: dict[str, set[str]], titles: dict[str, str]) -> str:
    order = list(ASPECT_LABELS)
    parts = []
    for node_id, aspects in hits.items():
        what = '、'.join(ASPECT_LABELS[a] for a in sorted(aspects, key=order.index))
        parts.append(f"「{titles.get(node_id) or '已删除的节点'}」[{node_id}]（{what}）")
    return '；'.join(parts)
