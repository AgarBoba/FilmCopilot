import sqlite3

from app.agent.store import AgentStore
from app.db import Database
from app.domain import DomainError
from app.repositories import CanvasRepository

import pytest


def test_new_database_has_default_project_and_canvases_join_it(tmp_path):
    database = Database(tmp_path / 'a.sqlite3')
    database.init_schema()
    repository = CanvasRepository(database)
    canvas = repository.create_canvas('C')
    store = AgentStore(database)
    assert store.project_for_canvas(canvas.canvasId) == 'default'
    assert store.get_settings('default')['permissionMode'] == 'confirm_generation'


def test_old_database_is_migrated(tmp_path):
    path = tmp_path / 'old.sqlite3'
    connection = sqlite3.connect(path)
    connection.executescript(
        '''
        CREATE TABLE canvases (id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0);
        INSERT INTO canvases (id, name) VALUES ('old', 'Old canvas');
        '''
    )
    connection.commit()
    connection.close()

    database = Database(path)
    database.init_schema()
    database.init_schema()  # running twice is harmless

    assert AgentStore(database).project_for_canvas('old') == 'default'


def test_sessions_runs_and_messages_round_trip(tmp_path):
    database = Database(tmp_path / 'a.sqlite3')
    database.init_schema()
    canvas = CanvasRepository(database).create_canvas('C')
    store = AgentStore(database)

    session = store.create_session(canvas.canvasId)
    run = store.create_run(session['id'], 'confirm_generation')
    first = store.add_message(session['id'], 'user', {'text': '做三个版本'}, run['id'])
    store.add_message(session['id'], 'assistant', {'text': '好的', 'assetIds': ['a1']}, run['id'])

    assert [m['role'] for m in store.list_messages(session['id'])] == ['user', 'assistant']
    assert store.list_messages(session['id'], after_id=first)[0]['content']['assetIds'] == ['a1']
    assert store.next_step(run['id']) == 1 and store.next_step(run['id']) == 2
    store.set_run_status(run['id'], 'completed')
    assert store.get_run(run['id'])['finished_at'] is not None
    assert store.list_sessions('default')[0]['id'] == session['id']


def test_settings_validation(tmp_path):
    database = Database(tmp_path / 'a.sqlite3')
    database.init_schema()
    store = AgentStore(database)
    assert store.update_settings('default', {'permissionMode': 'auto', 'generationCap': 6})['generationCap'] == 6
    with pytest.raises(DomainError):
        store.update_settings('default', {'permissionMode': 'yolo'})
    with pytest.raises(DomainError):
        store.update_settings('default', {'generationCap': 0})
