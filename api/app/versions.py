"""Version history of image / video nodes.

A node shows one asset at a time (data.assetId). Whenever that changes - a generation lands,
the user uploads, an agent run is undone, the user switches back to an older version - a new
version is appended; nothing is ever removed. Reading the canvas only shows the current
version; history is read on demand (get_node_versions tool, the node's version menu).

Where the change comes from is passed through a context variable, so the repository can
record versions on every write path without each caller threading the details through:

    with version_source('generated', job_id=..., prompt=..., model=...):
        repository.update_node(...)
"""
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import json
from typing import Any

from .db import Database

SOURCES = ('generated', 'uploaded', 'restored', 'copied', 'edited')

_source: ContextVar[dict[str, Any] | None] = ContextVar('node_version_source', default=None)


@contextmanager
def version_source(source: str, **details: Any) -> Iterator[None]:
    """Label the versions recorded inside this block (generated / uploaded / restored / copied)."""
    token = _source.set({'source': source, **details})
    try:
        yield
    finally:
        _source.reset(token)


def current_source() -> dict[str, Any]:
    return _source.get() or {'source': 'edited'}


class NodeVersions:
    def __init__(self, database: Database) -> None:
        self.database = database

    def _execute(self, query: str, params: tuple) -> None:
        connection = self.database.active_connection()
        if connection is not None:
            connection.execute(query, params)
            return
        with self.database.transaction() as transaction:
            transaction.execute(query, params)

    def _rows(self, query: str, params: tuple) -> list[dict[str, Any]]:
        connection = self.database.active_connection()
        if connection is not None:
            return [dict(row) for row in connection.execute(query, params).fetchall()]
        with self.database.connection() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def track(self, canvas_id: str, node_id: str, asset_id: str | None, previous: str | None = None) -> int | None:
        """Called on every node write: append a version if the node now shows a different
        asset than its latest version. `previous` is the asset it showed before this write,
        so a node from before version tracking keeps what it showed. Returns the new
        version number, or None."""
        if not asset_id:
            return None
        latest = self._latest(canvas_id, node_id)
        if latest is None and previous != asset_id:
            self._ensure_history(canvas_id, node_id, previous)
            latest = self._latest(canvas_id, node_id)
        if latest is not None and latest['asset_id'] == asset_id:
            return None
        version = (latest['version'] if latest else 0) + 1
        self._insert(canvas_id, node_id, version, asset_id, current_source())
        return version

    def _latest(self, canvas_id: str, node_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            'SELECT version, asset_id FROM node_versions WHERE canvas_id = ? AND node_id = ? '
            'ORDER BY version DESC LIMIT 1', (canvas_id, node_id))
        return rows[0] if rows else None

    def _ensure_history(self, canvas_id: str, node_id: str, current: str | None) -> None:
        """First time a node is seen: rebuild history from its finished generations up to the
        asset it shows now, then record that asset if no generation produced it (an upload)."""
        self._backfill(canvas_id, node_id, upto_asset=current)
        latest = self._latest(canvas_id, node_id)
        if current and (latest is None or latest['asset_id'] != current):
            self._insert(canvas_id, node_id, (latest['version'] if latest else 0) + 1, current, {'source': 'edited'})

    def _insert(self, canvas_id: str, node_id: str, version: int, asset_id: str, details: dict[str, Any]) -> None:
        parameters = details.get('parameters')
        self._execute(
            '''
            INSERT INTO node_versions
                (canvas_id, node_id, version, asset_id, source, job_id, prompt, parameters_json, model, comment_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (canvas_id, node_id, version, asset_id, details.get('source', 'edited'), details.get('job_id'),
             details.get('prompt'), json.dumps(parameters) if parameters is not None else None,
             details.get('model'), details.get('comment_id')),
        )

    def _backfill(self, canvas_id: str, node_id: str, upto_asset: str | None = None) -> None:
        """Nodes from before version tracking: rebuild their history from finished generations
        (oldest first). Uploads before that time can't be recovered, only the current one."""
        jobs = self._rows(
            '''
            SELECT id, output_asset_id, request_json FROM generation_jobs
            WHERE canvas_id = ? AND target_node_id = ? AND output_asset_id IS NOT NULL
              AND status IN ('completed', 'completed_unattached')
            ORDER BY created_at, rowid
            ''', (canvas_id, node_id))
        version = 0
        for job in jobs:
            try:
                request = json.loads(job['request_json'] or '{}')
            except ValueError:
                request = {}
            version += 1
            self._insert(canvas_id, node_id, version, job['output_asset_id'], {
                'source': 'generated', 'job_id': job['id'], 'prompt': request.get('prompt'),
                'parameters': request.get('parameters'), 'model': request.get('model'),
                'comment_id': request.get('commentId'),
            })
            if job['output_asset_id'] == upto_asset:
                break

    def list(self, canvas_id: str, node_id: str, current_asset: str | None = None) -> list[dict[str, Any]]:
        """Oldest first. Builds the history the first time for nodes from before tracking."""
        rows = self._rows('SELECT 1 FROM node_versions WHERE canvas_id = ? AND node_id = ? LIMIT 1',
                          (canvas_id, node_id))
        if not rows:
            self._ensure_history(canvas_id, node_id, current_asset)
        return [self._public(row) for row in self._rows(
            'SELECT * FROM node_versions WHERE canvas_id = ? AND node_id = ? ORDER BY version',
            (canvas_id, node_id))]

    def latest(self, canvas_id: str, node_id: str, current_asset: str | None = None) -> int | None:
        versions = self.list(canvas_id, node_id, current_asset)
        return versions[-1]['version'] if versions else None

    def get(self, canvas_id: str, node_id: str, version: int) -> dict[str, Any] | None:
        rows = self._rows('SELECT * FROM node_versions WHERE canvas_id = ? AND node_id = ? AND version = ?',
                          (canvas_id, node_id, version))
        return self._public(rows[0]) if rows else None

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            'version': row['version'],
            'assetId': row['asset_id'],
            'source': row['source'],
            'jobId': row['job_id'],
            'prompt': row['prompt'],
            'parameters': json.loads(row['parameters_json']) if row['parameters_json'] else None,
            'model': row['model'],
            'commentId': row['comment_id'],
            'createdAt': row['created_at'],
        }
