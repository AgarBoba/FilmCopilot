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
                '''
            )
            columns = {
                row['name']
                for row in connection.execute('PRAGMA table_info(generation_jobs)').fetchall()
            }
            if 'output_asset_id' not in columns:
                connection.execute('ALTER TABLE generation_jobs ADD COLUMN output_asset_id TEXT')

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
