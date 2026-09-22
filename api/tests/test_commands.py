from fastapi.testclient import TestClient


def create_canvas(client: TestClient) -> str:
    response = client.post('/api/canvases', json={'name': 'Test canvas'})
    assert response.status_code == 201
    return response.json()['canvasId']


def create_node(client: TestClient, canvas_id: str, node_type: str, key: str) -> str:
    response = client.post(
        f'/api/canvases/{canvas_id}/commands',
        json={
            'command': 'create_node',
            'baseRevision': client.get(f'/api/canvases/{canvas_id}/snapshot').json()['revision'],
            'idempotencyKey': key,
            'payload': {'nodeType': node_type, 'x': 0, 'y': 0},
        },
    )
    assert response.status_code == 200
    return response.json()['payload']['nodeId']


def connect(
    client: TestClient,
    canvas_id: str,
    source_id: str,
    target_id: str,
    edge_id: str,
    base_revision: int,
):
    return client.post(
        f'/api/canvases/{canvas_id}/commands',
        json={
            'command': 'connect_nodes',
            'baseRevision': base_revision,
            'idempotencyKey': edge_id,
            'payload': {
                'edgeId': edge_id,
                'sourceNodeId': source_id,
                'targetNodeId': target_id,
            },
        },
    )


def test_create_node_increments_revision(client: TestClient):
    canvas_id = create_canvas(client)
    result = client.post(
        f'/api/canvases/{canvas_id}/commands',
        json={
            'command': 'create_node',
            'baseRevision': 0,
            'idempotencyKey': 'create-image-1',
            'payload': {'nodeType': 'image', 'x': 100, 'y': 120},
        },
    )
    assert result.status_code == 200
    assert result.json()['revision'] == 1


def test_revision_conflict_rejects_stale_command(client: TestClient):
    canvas_id = create_canvas(client)
    create_node(client, canvas_id, 'image', 'create-image-1')
    response = client.post(
        f'/api/canvases/{canvas_id}/commands',
        json={
            'command': 'create_node',
            'baseRevision': 0,
            'idempotencyKey': 'create-video-1',
            'payload': {'nodeType': 'video', 'x': 0, 'y': 0},
        },
    )
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'


def test_idempotent_command_returns_original_result(client: TestClient):
    canvas_id = create_canvas(client)
    command = {
        'command': 'create_node',
        'baseRevision': 0,
        'idempotencyKey': 'same-command',
        'payload': {'nodeType': 'image', 'x': 0, 'y': 0},
    }
    first = client.post(f'/api/canvases/{canvas_id}/commands', json=command)
    second = client.post(f'/api/canvases/{canvas_id}/commands', json=command)
    assert first.json() == second.json()
    assert client.get(f'/api/canvases/{canvas_id}/snapshot').json()['revision'] == 1


def test_connect_command_rejects_cycle(client: TestClient):
    canvas_id = create_canvas(client)
    image_id = create_node(client, canvas_id, 'image', 'image')
    video_id = create_node(client, canvas_id, 'video', 'video')
    connect(client, canvas_id, image_id, video_id, 'edge-1', 2)
    response = connect(client, canvas_id, video_id, image_id, 'edge-2', 3)
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_CONNECTION'
