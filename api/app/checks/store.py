"""Node check results, kept in the node_checks table so the canvas and the agent read the same thing.

refresh() re-checks every image / video node of a canvas. It runs inside the transaction of each
canvas command that can change a node's inputs (commands.py) and when a generation lands
(worker.py: a new picture upstream changes what the nodes below it would send).
"""
import json
from typing import TYPE_CHECKING, Any

from . import Problem, check_inputs

if TYPE_CHECKING:
    from ..repositories import CanvasRepository

MEDIA = ('image', 'video')
# canvas id -> the model files' stamp its stored results were computed with. When someone edits a
# rule in models/*.json, the next read re-checks instead of showing stale results.
_checked_with: dict[str, tuple] = {}


def _models_stamp() -> tuple:
    from ..models_registry import registry
    models = registry()
    models.all()
    return models._stamp


def problems_for(repository: 'CanvasRepository', canvas_id: str, node_id: str,
                 overrides: dict[str, Any] | None = None) -> tuple[Any, list[Problem]]:
    """(model, problems) for one node as it is now, or with a generation's overrides applied."""
    from ..models_registry import registry
    snapshot = repository.generation_snapshot(canvas_id, node_id)
    snapshot.update(overrides or {})
    model = registry().for_node(snapshot['nodeType'], snapshot.get('model'))
    if model is None:
        return None, []
    return model, check_inputs(model, snapshot)


def refresh(repository: 'CanvasRepository', canvas_id: str) -> None:
    nodes = repository._fetchall(
        'SELECT id, node_type FROM canvas_nodes WHERE canvas_id = ?', (canvas_id,))
    media = [row['id'] for row in nodes if row['node_type'] in MEDIA]
    placeholders = ','.join('?' * len(media)) or "''"
    repository._execute(
        f'DELETE FROM node_checks WHERE canvas_id = ? AND node_id NOT IN ({placeholders})',
        (canvas_id, *media))
    for node_id in media:
        try:
            model, problems = problems_for(repository, canvas_id, node_id)
        except Exception:  # a check must never break the edit that triggered it
            continue
        repository._execute(
            '''INSERT INTO node_checks (canvas_id, node_id, model_id, problems_json, checked_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT (canvas_id, node_id) DO UPDATE SET
                 model_id = excluded.model_id, problems_json = excluded.problems_json,
                 checked_at = excluded.checked_at''',
            (canvas_id, node_id, model.id if model else None,
             json.dumps([problem.public() for problem in problems], ensure_ascii=False)))
    _checked_with[canvas_id] = _models_stamp()


def load(repository: 'CanvasRepository', canvas_id: str) -> dict[str, list[dict[str, Any]]]:
    """nodeId -> problems, only for nodes that have any."""
    if _checked_with.get(canvas_id) != _models_stamp() and repository.database.active_connection() is None:
        # First read since start, or a model file changed: results may be missing or stale.
        with repository.transaction():
            refresh(repository, canvas_id)
    rows = repository._fetchall(
        'SELECT node_id, problems_json FROM node_checks WHERE canvas_id = ?', (canvas_id,))
    found = {}
    for row in rows:
        problems = json.loads(row['problems_json'] or '[]')
        if problems:
            found[row['node_id']] = problems
    return found


def problem_text(problems: list[dict[str, Any]]) -> str:
    return '；'.join(('⚠ ' if problem.get('severity') == 'warning' else '') + problem['message']
                    for problem in problems)
