import json
from typing import Any

from .db import Database
from .schemas import CanvasEvent, CommandResult


class EventStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def append(
        self,
        canvas_id: str,
        revision: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> CanvasEvent:
        connection = self.database.active_connection()
        if connection is None:
            with self.database.transaction() as transaction:
                return self._append(transaction, canvas_id, revision, event_type, payload)
        return self._append(connection, canvas_id, revision, event_type, payload)

    def _append(
        self,
        connection,
        canvas_id: str,
        revision: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> CanvasEvent:
        cursor = connection.execute(
            '''
            INSERT INTO canvas_events (canvas_id, revision, event_type, payload_json)
            VALUES (?, ?, ?, ?)
            ''',
            (canvas_id, revision, event_type, json.dumps(payload)),
        )
        return CanvasEvent(
            id=cursor.lastrowid,
            canvasId=canvas_id,
            revision=revision,
            eventType=event_type,
            payload=payload,
        )

    def append_for_result(
        self, canvas_id: str, revision: int, result: CommandResult
    ) -> CanvasEvent:
        return self.append(
            canvas_id,
            revision,
            f'canvas.{result.command}',
            result.model_dump(mode='json'),
        )

    def after_revision(self, canvas_id: str, revision: int) -> list[CanvasEvent]:
        with self.database.connection() as connection:
            rows = connection.execute(
                '''
                SELECT id, canvas_id, revision, event_type, payload_json
                FROM canvas_events
                WHERE canvas_id = ? AND revision > ?
                ORDER BY revision ASC, id ASC
                ''',
                (canvas_id, revision),
            ).fetchall()
        return [
            CanvasEvent(
                id=row['id'],
                canvasId=row['canvas_id'],
                revision=row['revision'],
                eventType=row['event_type'],
                payload=json.loads(row['payload_json']),
            )
            for row in rows
        ]
