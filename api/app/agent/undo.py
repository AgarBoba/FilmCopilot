"""Undo everything one agent run changed on the canvas (spec 3.5).

Runs inside the `undo_agent_run` command, so it is atomic, bumps the revision once and
produces one canvas event the UI already knows how to apply.

Rule: a node or edge that changed again after the run finished (by the user, the
generation worker or another run) is left alone and reported as skipped.
"""
from typing import Any

from ..domain import DomainError
from ..repositories import CanvasRepository


def undo_agent_run(repository: CanvasRepository, canvas_id: str, run_id: str) -> dict[str, Any]:
    run = repository._fetchone('SELECT status FROM agent_runs WHERE id = ?', (run_id,))
    if run is None:
        raise DomainError('NOT_FOUND', f'Agent run {run_id} was not found')
    if run['status'] == 'undone':
        raise DomainError('ALREADY_UNDONE', 'This agent run has already been undone')
    if run['status'] in ('running', 'waiting_confirmation'):
        raise DomainError('RUN_ACTIVE', 'Stop the agent run before undoing it')

    changes = [change for change in repository.agent_run_changes(run_id) if change['canvas_id'] == canvas_id]
    first_before: dict[tuple[str, str], Any] = {}
    last_after: dict[tuple[str, str], Any] = {}
    job_ids: list[str] = []
    for change in changes:
        if change['entity_type'] == 'job':
            job_ids.append(change['entity_id'])
            continue
        key = (change['entity_type'], change['entity_id'])
        first_before.setdefault(key, change['before'])
        last_after[key] = change['after']

    run_assets = _output_assets(repository, job_ids)
    current = repository.canvas_state(canvas_id)
    skipped: list[dict[str, str]] = []
    to_restore: dict[tuple[str, str], Any] = {}
    for key, original in first_before.items():
        entity_type, entity_id = key
        now = current[entity_type].get(entity_id)
        expected = last_after[key]
        if entity_type == 'node' and now is not None and expected is not None:
            now = _ignore_run_results(now, expected, run_assets)
        if now != expected:
            skipped.append({'type': entity_type, 'id': entity_id, 'reason': 'changed_after_run'})
            continue
        to_restore[key] = original

    restored = {'deletedNodes': [], 'deletedEdges': [], 'restoredNodes': [], 'restoredEdges': []}

    # 1) Remove what the run created (edges first; node deletes cascade their edges).
    for (entity_type, entity_id), original in to_restore.items():
        if entity_type == 'edge' and original is None and entity_id in current['edge']:
            repository.delete_edge(canvas_id, entity_id)
            restored['deletedEdges'].append(entity_id)
    for (entity_type, entity_id), original in to_restore.items():
        if entity_type == 'node' and original is None and entity_id in current['node']:
            repository.delete_node(canvas_id, entity_id)
            restored['deletedNodes'].append(entity_id)

    # 2) Put back nodes the run changed or deleted, exactly as they were.
    for (entity_type, entity_id), original in to_restore.items():
        if entity_type == 'node' and original is not None:
            repository.replace_node(canvas_id, original)
            restored['restoredNodes'].append(entity_id)

    # 3) Re-create edges the run deleted, if both ends still exist and nothing duplicates them.
    state = repository.canvas_state(canvas_id)
    pairs = {(edge['source'], edge['target']) for edge in state['edge'].values()}
    for (entity_type, entity_id), original in to_restore.items():
        if entity_type != 'edge' or original is None or entity_id in state['edge']:
            continue
        pair = (original['source'], original['target'])
        if original['source'] not in state['node'] or original['target'] not in state['node'] or pair in pairs:
            skipped.append({'type': 'edge', 'id': entity_id, 'reason': 'endpoint_missing'})
            continue
        repository.insert_edge(canvas_id, entity_id, original['source'], original['target'])
        pairs.add(pair)
        restored['restoredEdges'].append(entity_id)

    # Generations that have not started yet are cancelled; money already spent cannot be refunded.
    cancelled = []
    for job_id in job_ids:
        cursor = repository._execute(
            "UPDATE generation_jobs SET status = 'canceled', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'queued'",
            (job_id,),
        )
        if cursor.rowcount:
            cancelled.append(job_id)

    repository._execute(
        "UPDATE agent_runs SET status = 'undone', finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP) "
        'WHERE id = ?',
        (run_id,),
    )
    return {'runId': run_id, **restored, 'cancelledJobs': cancelled, 'skipped': skipped}


def _output_assets(repository: CanvasRepository, job_ids: list[str]) -> set[str]:
    if not job_ids:
        return set()
    placeholders = ','.join('?' for _ in job_ids)
    rows = repository._fetchall(
        f'SELECT output_asset_id FROM generation_jobs WHERE id IN ({placeholders}) AND output_asset_id IS NOT NULL',
        tuple(job_ids),
    )
    return {row['output_asset_id'] for row in rows}


def _ignore_run_results(now: dict, expected: dict, run_assets: set[str]) -> dict:
    """A result from this run's own generation landing on the node is not a user edit."""
    asset_id = now.get('data', {}).get('assetId')
    if asset_id in run_assets:
        data = dict(now['data'])
        if 'assetId' in expected['data']:
            data['assetId'] = expected['data']['assetId']
        else:
            data.pop('assetId', None)
        return {**now, 'data': data}
    return now
