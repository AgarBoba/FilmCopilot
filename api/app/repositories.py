from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from .db import Database
from .domain import DomainError, EdgeRecord, NodeType
from .schemas import (
    CanvasEdgeSchema,
    CanvasNodeSchema,
    CanvasSnapshot,
    CanvasViewport,
    CommandResult,
)


class CanvasRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.database.transaction() as connection:
            yield connection

    def create_canvas(self, name: str, canvas_id: str | None = None) -> CanvasSnapshot:
        canvas_id = canvas_id or str(uuid4())
        if self._fetchone('SELECT id FROM canvases WHERE id = ?', (canvas_id,)) is not None:
            return self.get_snapshot(canvas_id)
        with self.transaction() as connection:
            connection.execute(
                'INSERT INTO canvases (id, name, revision) VALUES (?, ?, 0)',
                (canvas_id, name.strip() or 'Untitled canvas'),
            )
        return self.get_snapshot(canvas_id)

    def get_snapshot(self, canvas_id: str) -> CanvasSnapshot:
        with self.database.connection() as connection:
            canvas = connection.execute(
                'SELECT id, name, revision, viewport_json FROM canvases WHERE id = ?',
                (canvas_id,),
            ).fetchone()
            if canvas is None:
                raise DomainError('NOT_FOUND', f'Canvas {canvas_id} was not found')

            nodes = connection.execute(
                '''
                SELECT id, node_type, x, y, width, height, data_json
                FROM canvas_nodes WHERE canvas_id = ? ORDER BY rowid
                ''',
                (canvas_id,),
            ).fetchall()
            edges = connection.execute(
                '''
                SELECT id, source_node_id, target_node_id
                FROM canvas_edges WHERE canvas_id = ? ORDER BY rowid
                ''',
                (canvas_id,),
            ).fetchall()
            assets = connection.execute(
                '''
                SELECT id, kind, path, original_name, mime_type, width, height,
                       duration_seconds, checksum, metadata_json
                FROM assets WHERE canvas_id = ? ORDER BY created_at, id
                ''',
                (canvas_id,),
            ).fetchall()
            jobs = connection.execute(
                '''
                SELECT id, target_node_id, status, provider, request_json,
                       input_snapshot_json, error, created_at, updated_at
                FROM generation_jobs WHERE canvas_id = ? ORDER BY created_at, id
                ''',
                (canvas_id,),
            ).fetchall()

        return CanvasSnapshot(
            canvasId=canvas['id'],
            name=canvas['name'],
            revision=canvas['revision'],
            nodes=[self._node_schema(row) for row in nodes],
            edges=[
                CanvasEdgeSchema(
                    id=row['id'], source=row['source_node_id'], target=row['target_node_id']
                )
                for row in edges
            ],
            viewport=CanvasViewport(**json.loads(canvas['viewport_json'])),
            assets=[self._json_row(row, ('metadata_json',)) for row in assets],
            jobs=[self._json_row(row, ('request_json', 'input_snapshot_json')) for row in jobs],
        )

    def _node_schema(self, row: sqlite3.Row) -> CanvasNodeSchema:
        data = json.loads(row['data_json'])
        return CanvasNodeSchema(
            id=row['id'],
            nodeType=row['node_type'],
            x=row['x'],
            y=row['y'],
            width=row['width'],
            height=row['height'],
            data=data,
        )

    @staticmethod
    def _json_row(row: sqlite3.Row, json_columns: tuple[str, ...]) -> dict[str, Any]:
        result = dict(row)
        for column in json_columns:
            if result.get(column) is not None:
                result[column.removesuffix('_json')] = json.loads(result.pop(column))
        return result

    def find_command(self, canvas_id: str, idempotency_key: str) -> CommandResult | None:
        with self.database.connection() as connection:
            row = connection.execute(
                'SELECT result_json FROM command_log WHERE canvas_id = ? AND idempotency_key = ?',
                (canvas_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        return CommandResult.model_validate(json.loads(row['result_json']))

    def save_command(self, canvas_id: str, idempotency_key: str, result: CommandResult) -> None:
        self._execute(
            'INSERT INTO command_log (canvas_id, idempotency_key, result_json) VALUES (?, ?, ?)',
            (canvas_id, idempotency_key, result.model_dump_json()),
        )

    def assert_canvas(self, canvas_id: str) -> sqlite3.Row:
        row = self._fetchone(
            'SELECT id, name, revision FROM canvases WHERE id = ?', (canvas_id,)
        )
        if row is None:
            raise DomainError('NOT_FOUND', f'Canvas {canvas_id} was not found')
        return row

    def assert_revision(self, canvas_id: str, expected: int) -> None:
        canvas = self.assert_canvas(canvas_id)
        if canvas['revision'] != expected:
            raise DomainError(
                'REVISION_CONFLICT',
                f'Expected revision {expected}, current revision is {canvas["revision"]}',
            )

    def bump_revision(self, canvas_id: str) -> int:
        self._execute('UPDATE canvases SET revision = revision + 1 WHERE id = ?', (canvas_id,))
        return self._fetchone('SELECT revision FROM canvases WHERE id = ?', (canvas_id,))['revision']

    def update_viewport(self, canvas_id: str, viewport: dict[str, Any]) -> None:
        self._execute(
            'UPDATE canvases SET viewport_json = ? WHERE id = ?',
            (json.dumps(viewport), canvas_id),
        )

    def node_type(self, canvas_id: str, node_id: str) -> NodeType:
        row = self._fetchone(
            'SELECT node_type FROM canvas_nodes WHERE canvas_id = ? AND id = ?',
            (canvas_id, node_id),
        )
        if row is None:
            raise DomainError('NOT_FOUND', f'Node {node_id} was not found')
        return row['node_type']

    def node_snapshot(self, canvas_id: str, node_id: str) -> dict[str, Any]:
        row = self._fetchone(
            '''
            SELECT id, node_type, x, y, width, height, data_json
            FROM canvas_nodes WHERE canvas_id = ? AND id = ?
            ''',
            (canvas_id, node_id),
        )
        if row is None:
            raise DomainError('NOT_FOUND', f'Node {node_id} was not found')
        return {
            'id': row['id'],
            'nodeType': row['node_type'],
            'x': row['x'],
            'y': row['y'],
            'width': row['width'],
            'height': row['height'],
            'data': json.loads(row['data_json']),
        }

    def canvas_revision(self, canvas_id: str) -> int:
        return self.assert_canvas(canvas_id)['revision']

    def generation_snapshot(self, canvas_id: str, node_id: str) -> dict[str, Any]:
        node = self.node_snapshot(canvas_id, node_id)
        references = []
        for edge in self._fetchall(
            'SELECT source_node_id FROM canvas_edges WHERE canvas_id = ? AND target_node_id = ?',
            (canvas_id, node_id),
        ):
            source = self.node_snapshot(canvas_id, edge['source_node_id'])
            asset_id = source['data'].get('assetId')
            if asset_id:
                asset = self.asset_dict(asset_id)
                references.append(asset)
        return {
            'targetNodeId': node_id,
            'nodeType': node['nodeType'],
            'prompt': node['data'].get('prompt', ''),
            'parameters': node['data'].get('parameters', {}),
            'references': references,
            'baseCanvasRevision': self.canvas_revision(canvas_id),
        }

    def node_edges(self, canvas_id: str) -> list[EdgeRecord]:
        rows = self._fetchall(
            'SELECT source_node_id, target_node_id FROM canvas_edges WHERE canvas_id = ?',
            (canvas_id,),
        )
        return [EdgeRecord(row['source_node_id'], row['target_node_id']) for row in rows]

    def insert_node(
        self,
        canvas_id: str,
        node_id: str,
        node_type: NodeType,
        x: float,
        y: float,
        width: float | None,
        height: float | None,
        data: dict[str, Any],
    ) -> None:
        self._execute(
            '''
            INSERT INTO canvas_nodes (canvas_id, id, node_type, x, y, width, height, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (canvas_id, node_id, node_type, x, y, width, height, json.dumps(data)),
        )

    def update_node(self, canvas_id: str, node_id: str, payload: dict[str, Any]) -> None:
        current = self._fetchone(
            '''
            SELECT x, y, width, height, data_json FROM canvas_nodes
            WHERE canvas_id = ? AND id = ?
            ''',
            (canvas_id, node_id),
        )
        if current is None:
            raise DomainError('NOT_FOUND', f'Node {node_id} was not found')
        data = json.loads(current['data_json'])
        data.update(payload.get('data', {}))
        values = (
            payload.get('x', current['x']),
            payload.get('y', current['y']),
            payload.get('width', current['width']),
            payload.get('height', current['height']),
            json.dumps(data),
            canvas_id,
            node_id,
        )
        self._execute(
            '''
            UPDATE canvas_nodes SET x = ?, y = ?, width = ?, height = ?, data_json = ?
            WHERE canvas_id = ? AND id = ?
            ''',
            values,
        )

    def delete_node(self, canvas_id: str, node_id: str) -> None:
        cursor = self._execute(
            'DELETE FROM canvas_nodes WHERE canvas_id = ? AND id = ?', (canvas_id, node_id)
        )
        if cursor.rowcount == 0:
            raise DomainError('NOT_FOUND', f'Node {node_id} was not found')

    def insert_edge(
        self, canvas_id: str, edge_id: str, source_node_id: str, target_node_id: str
    ) -> None:
        self._execute(
            '''
            INSERT INTO canvas_edges (canvas_id, id, source_node_id, target_node_id)
            VALUES (?, ?, ?, ?)
            ''',
            (canvas_id, edge_id, source_node_id, target_node_id),
        )

    def delete_edge(self, canvas_id: str, edge_id: str) -> None:
        cursor = self._execute(
            'DELETE FROM canvas_edges WHERE canvas_id = ? AND id = ?', (canvas_id, edge_id)
        )
        if cursor.rowcount == 0:
            raise DomainError('NOT_FOUND', f'Edge {edge_id} was not found')

    def asset_dict(self, asset_id: str) -> dict[str, Any]:
        row = self._fetchone(
            '''
            SELECT id, canvas_id, kind, path, original_name, mime_type, width, height,
                   duration_seconds, checksum
            FROM assets WHERE id = ?
            ''',
            (asset_id,),
        )
        if row is None:
            raise DomainError('NOT_FOUND', f'Asset {asset_id} was not found')
        return dict(row)

    def create_generation_job(
        self,
        canvas_id: str,
        target_node_id: str,
        provider: str,
        request_snapshot: dict[str, Any],
        input_snapshot: dict[str, Any],
    ) -> str:
        job_id = str(uuid4())
        self._execute(
            '''
            INSERT INTO generation_jobs (
                id, canvas_id, target_node_id, status, provider, request_json, input_snapshot_json
            ) VALUES (?, ?, ?, 'queued', ?, ?, ?)
            ''',
            (
                job_id,
                canvas_id,
                target_node_id,
                provider,
                json.dumps(request_snapshot),
                json.dumps(input_snapshot),
            ),
        )
        return job_id

    def claim_next_generation_job(self) -> dict[str, Any] | None:
        with self.transaction() as connection:
            row = connection.execute(
                '''
                SELECT id, canvas_id, target_node_id, status, provider, request_json,
                       input_snapshot_json, output_asset_id, error
                FROM generation_jobs WHERE status = 'queued'
                ORDER BY created_at, id LIMIT 1
                '''
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE generation_jobs SET status = 'running', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row['id'],),
            )
            result = dict(row)
            result['status'] = 'running'
            return result

    def update_generation_job(
        self,
        job_id: str,
        status: str,
        error: str | None = None,
        output_asset_id: str | None = None,
    ) -> dict[str, Any]:
        self._execute(
            '''
            UPDATE generation_jobs
            SET status = ?, error = ?, output_asset_id = COALESCE(?, output_asset_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (status, error, output_asset_id, job_id),
        )
        row = self._fetchone(
            '''
            SELECT id, canvas_id, target_node_id, status, provider, request_json,
                   input_snapshot_json, output_asset_id, error
            FROM generation_jobs WHERE id = ?
            ''',
            (job_id,),
        )
        if row is None:
            raise DomainError('NOT_FOUND', f'Generation job {job_id} was not found')
        return dict(row)

    def get_generation_job(self, job_id: str) -> dict[str, Any]:
        row = self._fetchone(
            '''
            SELECT id, canvas_id, target_node_id, status, provider, request_json,
                   input_snapshot_json, output_asset_id, error
            FROM generation_jobs WHERE id = ?
            ''',
            (job_id,),
        )
        if row is None:
            raise DomainError('NOT_FOUND', f'Generation job {job_id} was not found')
        return dict(row)

    def insert_asset(self, record: dict[str, Any]) -> None:
        self._execute(
            '''
            INSERT INTO assets (
                id, canvas_id, kind, path, original_name, mime_type, width, height,
                duration_seconds, checksum, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                record['id'], record.get('canvas_id'), record['kind'], record['path'],
                record.get('original_name'), record['mime_type'], record.get('width'),
                record.get('height'), record.get('duration_seconds'), record.get('checksum'),
                json.dumps(record.get('metadata', {})),
            ),
        )

    def _fetchone(self, query: str, params: tuple[Any, ...]) -> sqlite3.Row | None:
        with self.database.connection() as connection:
            return connection.execute(query, params).fetchone()

    def _fetchall(self, query: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
        with self.database.connection() as connection:
            return connection.execute(query, params).fetchall()

    def _execute(self, query: str, params: tuple[Any, ...]) -> sqlite3.Cursor:
        active = self.database.active_connection()
        if active is not None:
            return active.execute(query, params)
        with self.database.connection() as connection:
            cursor = connection.execute(query, params)
            connection.commit()
            return cursor
