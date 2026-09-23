import time

from fastapi.testclient import TestClient

from app.agent.config import AgentConfig
from app.config import Settings
from app.main import create_app
from tests.agent_fakes import FakeFactory

SECRET = 'sk-ant-TEST-SECRET-should-never-leak'


def make_client(tmp_path, monkeypatch, factory, configured=True):
    if configured:
        monkeypatch.setenv('ANTHROPIC_API_KEY', SECRET)
    else:
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    settings = Settings(data_dir=tmp_path, database_path=tmp_path / 'canvas.sqlite3')
    app = create_app(settings, AgentConfig.from_env())
    app.state.agent_service.client_factory = factory
    app.state.agent_service.config = AgentConfig(api_key_present=configured, poll_seconds=0.01)
    return app


def wait_for(client, session_id, kind, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        messages = client.get(f'/api/agent/sessions/{session_id}/messages').json()
        if any(message['kind'] == kind for message in messages):
            return messages
        time.sleep(0.05)
    raise AssertionError(f'no {kind} event')


def test_session_message_undo_and_settings_flow(tmp_path, monkeypatch):
    factory = FakeFactory([
        ('text', '好'),
        ('tool', 'create_nodes', {'nodes': [{'type': 'note', 'content': 'hi'}]}),
    ])
    app = make_client(tmp_path, monkeypatch, factory)
    with TestClient(app) as client:
        canvas = client.post('/api/canvases', json={'name': 'A', 'canvasId': 'c1'}).json()
        assert client.get('/api/agent/status').json() == {'configured': True, 'model': 'claude-opus-5-5'}

        session = client.post('/api/agent/sessions', json={'canvasId': canvas['canvasId']}).json()
        sent = client.post(f"/api/agent/sessions/{session['id']}/messages", json={'text': '建便签'})
        assert sent.status_code == 202
        messages = wait_for(client, session['id'], 'run_finished')
        assert [m['kind'] for m in messages][:2] == ['user_message', 'assistant_text']
        assert client.get('/api/agent/sessions', params={'canvasId': 'c1'}).json()[0]['title'] == '建便签'

        undone = client.post(f"/api/agent/runs/{sent.json()['runId']}/undo").json()
        assert len(undone['deletedNodes']) == 1
        assert client.post(f"/api/agent/runs/{sent.json()['runId']}/undo").status_code == 409

        assert client.patch('/api/projects/default/agent-settings', json={'permissionMode': 'auto'}).json()['permissionMode'] == 'auto'
        assert client.patch('/api/projects/default/agent-settings', json={'permissionMode': 'x'}).status_code == 422


def test_not_configured_returns_a_clear_error(tmp_path, monkeypatch):
    app = make_client(tmp_path, monkeypatch, FakeFactory(), configured=False)
    with TestClient(app) as client:
        client.post('/api/canvases', json={'name': 'A', 'canvasId': 'c1'})
        session = client.post('/api/agent/sessions', json={'canvasId': 'c1'}).json()
        response = client.post(f"/api/agent/sessions/{session['id']}/messages", json={'text': 'hi'})
        assert response.status_code == 503
        assert 'ANTHROPIC_API_KEY' in response.json()['error']['message']


def test_api_key_never_leaves_backend(tmp_path, monkeypatch, caplog):
    factory = FakeFactory([('text', '好'), ('tool', 'get_canvas', {})])
    app = make_client(tmp_path, monkeypatch, factory)
    bodies = []
    with TestClient(app) as client:
        client.post('/api/canvases', json={'name': 'A', 'canvasId': 'c1'})
        session = client.post('/api/agent/sessions', json={'canvasId': 'c1'}).json()
        bodies.append(client.post(f"/api/agent/sessions/{session['id']}/messages", json={'text': 'hi'}).text)
        wait_for(client, session['id'], 'run_finished')
        for path in ('/api/agent/status', f"/api/agent/sessions/{session['id']}/messages",
                     '/api/agent/sessions', '/api/projects/default/agent-settings', '/api/canvases/c1/snapshot'):
            bodies.append(client.get(path, params={'canvasId': 'c1'} if path == '/api/agent/sessions' else None).text)
    assert not any(SECRET in body for body in bodies)
    assert SECRET not in caplog.text
    assert SECRET.encode() not in (tmp_path / 'canvas.sqlite3').read_bytes()
    assert SECRET not in repr(factory.clients[0].options)
