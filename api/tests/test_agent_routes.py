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
        status = client.get('/api/agent/status').json()
        assert status['configured'] is True and status['model'] == 'claude-opus-5-5' and status['auth'] == 'api'
        assert [m['label'] for m in status['models']] == ['Opus 5.5', 'Sonnet 5', 'Haiku 4.5']
        assert SECRET not in str(status)

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
        assert client.patch('/api/projects/default/agent-settings', json={'model': 'claude-sonnet-5'}).json()['model'] == 'claude-sonnet-5'
        assert client.patch('/api/projects/default/agent-settings', json={'model': 'gpt-5'}).status_code == 422


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


def test_sessions_are_per_canvas_with_preview_status_rename_and_archive(tmp_path, monkeypatch):
    factory = FakeFactory([('text', '## 分镜表\n\n| 镜头 | 画面 |\n| --- | --- |')])
    app = make_client(tmp_path, monkeypatch, factory)
    with TestClient(app) as client:
        client.post('/api/canvases', json={'name': 'A', 'canvasId': 'c1'})
        client.post('/api/canvases', json={'name': 'B', 'canvasId': 'c2'})
        first = client.post('/api/agent/sessions', json={'canvasId': 'c1'}).json()
        other_canvas = client.post('/api/agent/sessions', json={'canvasId': 'c2'}).json()
        client.post(f"/api/agent/sessions/{first['id']}/messages", json={'text': '做个分镜'})
        wait_for(client, first['id'], 'run_finished')

        listed = client.get('/api/agent/sessions', params={'canvasId': 'c1'}).json()
        assert [s['id'] for s in listed] == [first['id']]  # other canvas's chat is not here
        assert listed[0]['preview'] == '分镜表 镜头 画面 --- ---'
        assert listed[0]['message_count'] >= 2 and listed[0]['status'] == 'idle'
        assert other_canvas['id'] in [s['id'] for s in client.get('/api/agent/sessions', params={'canvasId': 'c2'}).json()]

        renamed = client.patch(f"/api/agent/sessions/{first['id']}", json={'title': '  菜板   分镜 '}).json()
        assert renamed['title'] == '菜板 分镜'
        assert client.patch(f"/api/agent/sessions/{first['id']}", json={'title': '   '}).status_code in (400, 422)

        assert client.patch(f"/api/agent/sessions/{first['id']}", json={'archived': True}).json()['archived_at']
        # archived chats are still listed (the panel shows them under 已归档) and keep their messages
        assert client.get('/api/agent/sessions', params={'canvasId': 'c1'}).json()[0]['archived_at']
        assert client.get(f"/api/agent/sessions/{first['id']}/messages").json()
        assert client.patch(f"/api/agent/sessions/{first['id']}", json={'archived': False}).json()['archived_at'] is None


def test_memory_endpoints(tmp_path, monkeypatch):
    app = make_client(tmp_path, monkeypatch, FakeFactory())
    with TestClient(app) as client:
        added = client.post('/api/memories', json={'layer': 'project', 'category': 'style', 'content': '暖色调，电影感'})
        assert added.status_code == 201 and added.json()['source'] == 'user_stated'
        memory_id = added.json()['id']
        client.post('/api/memories', json={'layer': 'preference', 'content': '图片默认 16:9', 'category': 'params'})
        listed = client.get('/api/memories').json()
        assert [m['content'] for m in listed['project']] == ['暖色调，电影感']
        assert listed['preference'][0]['categoryLabel'] == '常用参数'
        assert listed['categories']['project']['style'] == '风格'

        edited = client.patch(f'/api/memories/{memory_id}', json={'content': '暖色调，胶片感'}).json()
        assert edited['content'] == '暖色调，胶片感' and edited['source'] == 'user_edited'
        assert client.post('/api/memories', json={'layer': 'project', 'content': '  '}).status_code in (400, 422)
        assert client.delete(f'/api/memories/{memory_id}').status_code == 204
        assert client.get('/api/memories').json()['project'] == []
        assert client.patch(f'/api/memories/{memory_id}', json={'content': 'x'}).status_code == 404


def test_models_endpoint_lists_models_and_missing_keys(tmp_path, monkeypatch):
    monkeypatch.delenv('REPLICATE_API_TOKEN', raising=False)
    app = make_client(tmp_path, monkeypatch, FakeFactory())
    with TestClient(app) as client:
        body = client.get('/api/models').json()
        ids = [m['id'] for m in body['models']]
        assert 'seedream-5-pro' in ids and 'seedance-2.0-mini' in ids and body['errors'] == []
        seedream = next(m for m in body['models'] if m['id'] == 'seedream-5-pro')
        assert seedream['missingEnv'] == ['REPLICATE_API_TOKEN'] and seedream['maxImages'] == 10
        assert [p['key'] for p in seedream['parameters']] == ['size', 'aspectRatio', 'outputFormat']
