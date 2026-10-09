from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import sqlite3
from collections.abc import Iterator


_active_connection: ContextVar[sqlite3.Connection | None] = ContextVar(
    'active_database_connection', default=None
)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        return connection

    def init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                '''
                CREATE TABLE IF NOT EXISTS canvases (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    viewport_json TEXT NOT NULL DEFAULT '{"x": 0, "y": 0, "zoom": 1}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS canvas_nodes (
                    canvas_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    node_type TEXT NOT NULL CHECK (node_type IN ('image', 'video', 'note')),
                    x REAL NOT NULL DEFAULT 0,
                    y REAL NOT NULL DEFAULT 0,
                    width REAL,
                    height REAL,
                    data_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (canvas_id, id),
                    FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS canvas_edges (
                    canvas_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    source_node_id TEXT NOT NULL,
                    target_node_id TEXT NOT NULL,
                    PRIMARY KEY (canvas_id, id),
                    UNIQUE (canvas_id, source_node_id, target_node_id),
                    FOREIGN KEY (canvas_id, source_node_id) REFERENCES canvas_nodes(canvas_id, id) ON DELETE CASCADE,
                    FOREIGN KEY (canvas_id, target_node_id) REFERENCES canvas_nodes(canvas_id, id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY,
                    canvas_id TEXT,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    original_name TEXT,
                    mime_type TEXT NOT NULL,
                    width INTEGER,
                    height INTEGER,
                    duration_seconds REAL,
                    checksum TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS generation_jobs (
                    id TEXT PRIMARY KEY,
                    canvas_id TEXT NOT NULL,
                    target_node_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    input_snapshot_json TEXT NOT NULL,
                    output_asset_id TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE,
                    FOREIGN KEY (canvas_id, target_node_id) REFERENCES canvas_nodes(canvas_id, id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS canvas_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canvas_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS command_log (
                    canvas_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (canvas_id, idempotency_key),
                    FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT OR IGNORE INTO projects (id, name) VALUES ('default', '默认项目');

                CREATE TABLE IF NOT EXISTS agent_sessions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    canvas_id TEXT,
                    title TEXT,
                    summary TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    ended_at TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN (
                        'running', 'waiting_confirmation', 'stopped', 'completed', 'failed', 'undone'
                    )),
                    permission_mode TEXT NOT NULL,
                    generation_count INTEGER NOT NULL DEFAULT 0,
                    step_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT,
                    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS agent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    run_id TEXT,
                    role TEXT NOT NULL CHECK (role IN (
                        'user', 'assistant', 'tool_call', 'tool_result', 'system_event'
                    )),
                    content_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS agent_run_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    canvas_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    entity_type TEXT NOT NULL CHECK (entity_type IN ('node', 'edge', 'job')),
                    entity_id TEXT NOT NULL,
                    before_json TEXT,
                    after_json TEXT,
                    revision INTEGER NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS agent_run_changes_run ON agent_run_changes (run_id, seq);

                -- Layered memory (agent/memory.py).
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    layer TEXT NOT NULL CHECK (layer IN ('project', 'preference', 'episode')),
                    project_id TEXT,
                    canvas_id TEXT,
                    session_id TEXT,
                    run_id TEXT,
                    category TEXT NOT NULL DEFAULT 'other',
                    content TEXT NOT NULL,
                    source TEXT NOT NULL CHECK (source IN ('user_stated', 'agent_inferred', 'user_edited')),
                    status TEXT NOT NULL CHECK (status IN ('active', 'pending', 'superseded', 'rejected', 'removed')),
                    evidence_json TEXT,
                    superseded_by INTEGER,
                    removed_run_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TEXT
                );
                CREATE INDEX IF NOT EXISTS memories_scope ON memories (layer, project_id, status);

                -- Every image / video a node has shown, oldest first (versions.py).
                CREATE TABLE IF NOT EXISTS node_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canvas_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    asset_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    job_id TEXT,
                    prompt TEXT,
                    parameters_json TEXT,
                    model TEXT,
                    comment_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (canvas_id, node_id, version)
                );

                -- Comments pinned on the canvas (comments.py). A comment is a thread the user writes
                -- for themselves; handed to the agent, it gets its own agent session.
                CREATE TABLE IF NOT EXISTS canvas_comments (
                    id TEXT PRIMARY KEY,
                    canvas_id TEXT NOT NULL,
                    session_id TEXT,
                    anchor_kind TEXT NOT NULL CHECK (anchor_kind IN ('canvas', 'node', 'media')),
                    node_id TEXT,
                    version INTEGER,
                    x REAL,
                    y REAL,
                    time REAL,
                    text TEXT NOT NULL,
                    author TEXT NOT NULL DEFAULT 'me',
                    status TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
                    agent_status TEXT CHECK (agent_status IN ('queued', 'running', 'waiting', 'done', 'failed')),
                    text_seen_by_agent INTEGER NOT NULL DEFAULT 0,
                    outcome TEXT,
                    pending_text TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TEXT
                );
                CREATE INDEX IF NOT EXISTS canvas_comments_canvas ON canvas_comments (canvas_id, status);
                -- What people wrote under a comment after its first message (the agent's side lives
                -- in its session). seen_by_agent: already passed to the agent.
                CREATE TABLE IF NOT EXISTS comment_replies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    comment_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    author TEXT NOT NULL DEFAULT 'me',
                    to_agent INTEGER NOT NULL DEFAULT 0,
                    seen_by_agent INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS comment_replies_comment ON comment_replies (comment_id, id);
                CREATE TABLE IF NOT EXISTS canvas_task_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canvas_id TEXT NOT NULL,
                    comment_id TEXT NOT NULL UNIQUE,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                '''
            )
            columns = {
                row['name']
                for row in connection.execute('PRAGMA table_info(generation_jobs)').fetchall()
            }
            if 'output_asset_id' not in columns:
                connection.execute('ALTER TABLE generation_jobs ADD COLUMN output_asset_id TEXT')
            canvas_columns = {
                row['name']
                for row in connection.execute('PRAGMA table_info(canvases)').fetchall()
            }
            session_columns = {
                row['name'] for row in connection.execute('PRAGMA table_info(agent_sessions)').fetchall()
            }
            if 'sdk_session_id' not in session_columns:
                connection.execute('ALTER TABLE agent_sessions ADD COLUMN sdk_session_id TEXT')
            if 'kind' not in session_columns:
                # 'chat' (opened in the panel) or 'comment' (started by a comment on the canvas).
                connection.execute("ALTER TABLE agent_sessions ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'")
            if 'archived_at' not in session_columns:
                # Archived chats leave the list but keep their transcript (never deleted).
                connection.execute('ALTER TABLE agent_sessions ADD COLUMN archived_at TEXT')
            if 'project_id' not in canvas_columns:
                # Existing canvases belong to the default project.
                connection.execute(
                    "ALTER TABLE canvases ADD COLUMN project_id TEXT NOT NULL DEFAULT 'default'"
                )
            if 'viewport_json' not in canvas_columns:
                connection.execute(
                    "ALTER TABLE canvases ADD COLUMN viewport_json TEXT NOT NULL DEFAULT '{\"x\": 0, \"y\": 0, \"zoom\": 1}'"
                )
            self._migrate_comments(connection)

    @staticmethod
    def _migrate_comments(connection: sqlite3.Connection) -> None:
        """Comments used to be agent tasks only (status was the agent's status). Now a comment is
        open / resolved and the agent's status is separate; old comments were all agent tasks."""
        columns = {row['name'] for row in connection.execute('PRAGMA table_info(canvas_comments)').fetchall()}
        if 'agent_status' in columns:
            return
        connection.execute('ALTER TABLE canvas_comments RENAME TO canvas_comments_old')
        connection.execute('''CREATE TABLE canvas_comments (
                    id TEXT PRIMARY KEY,
                    canvas_id TEXT NOT NULL,
                    session_id TEXT,
                    anchor_kind TEXT NOT NULL CHECK (anchor_kind IN ('canvas', 'node', 'media')),
                    node_id TEXT,
                    version INTEGER,
                    x REAL,
                    y REAL,
                    time REAL,
                    text TEXT NOT NULL,
                    author TEXT NOT NULL DEFAULT 'me',
                    status TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
                    agent_status TEXT CHECK (agent_status IN ('queued', 'running', 'waiting', 'done', 'failed')),
                    text_seen_by_agent INTEGER NOT NULL DEFAULT 0,
                    outcome TEXT,
                    pending_text TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TEXT
        )''')
        pending = 'pending_text' if 'pending_text' in columns else 'NULL'  # very early tables lack it
        connection.execute(f'''
            INSERT INTO canvas_comments
                (id, canvas_id, session_id, anchor_kind, node_id, version, x, y, time, text, author, status,
                 agent_status, text_seen_by_agent, outcome, pending_text, created_at, updated_at, resolved_at)
            SELECT id, canvas_id, session_id, anchor_kind, node_id, version, x, y, time, text, 'me',
                   CASE WHEN status = 'resolved' THEN 'resolved' ELSE 'open' END,
                   CASE WHEN status = 'resolved' THEN 'done' ELSE status END,
                   CASE WHEN status = 'queued' AND {pending} = text THEN 0 ELSE 1 END,
                   outcome, {pending}, created_at, updated_at, resolved_at
            FROM canvas_comments_old''')
        connection.execute('DROP TABLE canvas_comments_old')
        connection.execute('CREATE INDEX IF NOT EXISTS canvas_comments_canvas ON canvas_comments (canvas_id, status)')

    def active_connection(self) -> sqlite3.Connection | None:
        return _active_connection.get()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        token = _active_connection.set(connection)
        try:
            connection.execute('BEGIN')
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            _active_connection.reset(token)
            connection.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        active = _active_connection.get()
        if active is not None:
            yield active
            return
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()
