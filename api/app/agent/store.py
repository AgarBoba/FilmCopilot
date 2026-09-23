"""Persistence for agent sessions, runs and messages (spec 5.6: transcripts are kept forever)."""
import json
from typing import Any
from uuid import uuid4

from ..db import Database
from ..domain import DomainError


PERMISSION_MODES = ('confirm_all', 'confirm_generation', 'auto')
DEFAULT_SETTINGS: dict[str, Any] = {
    'permissionMode': 'confirm_generation',
    'generationCap': 4,
}


class AgentStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    # ---- projects -------------------------------------------------------

    def project_for_canvas(self, canvas_id: str) -> str:
        with self.database.connection() as connection:
            row = connection.execute('SELECT project_id FROM canvases WHERE id = ?', (canvas_id,)).fetchone()
        if row is None:
            raise DomainError('NOT_FOUND', f'Canvas {canvas_id} was not found')
        return row['project_id']

    def get_settings(self, project_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute('SELECT settings_json FROM projects WHERE id = ?', (project_id,)).fetchone()
        if row is None:
            raise DomainError('NOT_FOUND', f'Project {project_id} was not found')
        return {**DEFAULT_SETTINGS, **json.loads(row['settings_json'])}

    def update_settings(self, project_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        settings = self.get_settings(project_id)
        if 'permissionMode' in changes:
            if changes['permissionMode'] not in PERMISSION_MODES:
                raise DomainError('INVALID_PAYLOAD', f"permissionMode must be one of {', '.join(PERMISSION_MODES)}")
            settings['permissionMode'] = changes['permissionMode']
        if 'generationCap' in changes:
            cap = changes['generationCap']
            if type(cap) is not int or not 1 <= cap <= 50:
                raise DomainError('INVALID_PAYLOAD', 'generationCap must be an integer from 1 to 50')
            settings['generationCap'] = cap
        with self.database.transaction() as connection:
            connection.execute(
                'UPDATE projects SET settings_json = ? WHERE id = ?', (json.dumps(settings), project_id)
            )
        return settings

    # ---- sessions -------------------------------------------------------

    def create_session(self, canvas_id: str, title: str | None = None) -> dict[str, Any]:
        project_id = self.project_for_canvas(canvas_id)
        session_id = str(uuid4())
        with self.database.transaction() as connection:
            connection.execute(
                'INSERT INTO agent_sessions (id, project_id, canvas_id, title) VALUES (?, ?, ?, ?)',
                (session_id, project_id, canvas_id, title),
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute('SELECT * FROM agent_sessions WHERE id = ?', (session_id,)).fetchone()
        if row is None:
            raise DomainError('NOT_FOUND', f'Agent session {session_id} was not found')
        return dict(row)

    def list_sessions(self, project_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                'SELECT * FROM agent_sessions WHERE project_id = ? ORDER BY created_at DESC, rowid DESC',
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_session_title(self, session_id: str, title: str) -> None:
        with self.database.transaction() as connection:
            connection.execute('UPDATE agent_sessions SET title = ? WHERE id = ?', (title, session_id))

    def set_sdk_session(self, session_id: str, sdk_session_id: str) -> None:
        """Remember the SDK's own session id so the conversation can resume after a restart."""
        with self.database.transaction() as connection:
            connection.execute(
                'UPDATE agent_sessions SET sdk_session_id = ? WHERE id = ?', (sdk_session_id, session_id)
            )

    # ---- runs -----------------------------------------------------------

    def create_run(self, session_id: str, permission_mode: str) -> dict[str, Any]:
        run_id = str(uuid4())
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO agent_runs (id, session_id, status, permission_mode) VALUES (?, ?, 'running', ?)",
                (run_id, session_id, permission_mode),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute('SELECT * FROM agent_runs WHERE id = ?', (run_id,)).fetchone()
        if row is None:
            raise DomainError('NOT_FOUND', f'Agent run {run_id} was not found')
        return dict(row)

    def set_run_status(self, run_id: str, status: str) -> None:
        finished = status in ('stopped', 'completed', 'failed', 'undone')
        with self.database.transaction() as connection:
            connection.execute(
                'UPDATE agent_runs SET status = ?, '
                'finished_at = CASE WHEN ? THEN COALESCE(finished_at, CURRENT_TIMESTAMP) ELSE finished_at END '
                'WHERE id = ?',
                (status, finished, run_id),
            )

    def next_step(self, run_id: str) -> int:
        """Monotonic step number within a run; used for deterministic idempotency keys."""
        with self.database.transaction() as connection:
            connection.execute('UPDATE agent_runs SET step_count = step_count + 1 WHERE id = ?', (run_id,))
            row = connection.execute('SELECT step_count FROM agent_runs WHERE id = ?', (run_id,)).fetchone()
        return int(row['step_count'])

    def count_generation(self, run_id: str) -> int:
        with self.database.transaction() as connection:
            connection.execute(
                'UPDATE agent_runs SET generation_count = generation_count + 1 WHERE id = ?', (run_id,)
            )
            row = connection.execute('SELECT generation_count FROM agent_runs WHERE id = ?', (run_id,)).fetchone()
        return int(row['generation_count'])

    # ---- messages -------------------------------------------------------

    def add_message(self, session_id: str, role: str, content: dict[str, Any], run_id: str | None = None) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                'INSERT INTO agent_messages (session_id, run_id, role, content_json) VALUES (?, ?, ?, ?)',
                (session_id, run_id, role, json.dumps(content, ensure_ascii=False)),
            )
        return int(cursor.lastrowid)

    def list_messages(self, session_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                'SELECT id, session_id, run_id, role, content_json, created_at FROM agent_messages '
                'WHERE session_id = ? AND id > ? ORDER BY id',
                (session_id, after_id),
            ).fetchall()
        messages = []
        for row in rows:
            item = dict(row)
            item['content'] = json.loads(item.pop('content_json'))
            messages.append(item)
        return messages
