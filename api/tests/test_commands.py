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


def test_update_canvas_persists_viewport(client: TestClient):
    canvas_id = create_canvas(client)
    response = client.post(
        f'/api/canvases/{canvas_id}/commands',
        json={
            'command': 'update_canvas',
            'baseRevision': 0,
            'idempotencyKey': 'viewport-1',
            'payload': {'viewport': {'x': 120, 'y': -80, 'zoom': 0.8}},
        },
    )
    assert response.status_code == 200
    assert client.get(f'/api/canvases/{canvas_id}/snapshot').json()['viewport'] == {
        'x': 120,
        'y': -80,
        'zoom': 0.8,
    }


def test_delete_elements_persists_multiple_nodes_and_connected_edge(client: TestClient):
    canvas_id = create_canvas(client)
    image_id = create_node(client, canvas_id, 'image', 'image')
    video_id = create_node(client, canvas_id, 'video', 'video')
    note_id = create_node(client, canvas_id, 'note', 'note')
    assert connect(client, canvas_id, image_id, video_id, 'edge-1', 3).status_code == 200

    response = client.post(
        f'/api/canvases/{canvas_id}/commands',
        json={
            'command': 'delete_elements',
            'baseRevision': 4,
            'idempotencyKey': 'delete-selection',
            'payload': {'nodeIds': [image_id, video_id], 'edgeIds': ['edge-1']},
        },
    )

    assert response.status_code == 200
    assert response.json()['revision'] == 5
    snapshot = client.get(f'/api/canvases/{canvas_id}/snapshot').json()
    assert [node['id'] for node in snapshot['nodes']] == [note_id]
    assert snapshot['edges'] == []


def test_delete_elements_rolls_back_when_a_node_is_missing(client: TestClient):
    canvas_id = create_canvas(client)
    image_id = create_node(client, canvas_id, 'image', 'image')

    response = client.post(
        f'/api/canvases/{canvas_id}/commands',
        json={
            'command': 'delete_elements',
            'baseRevision': 1,
            'idempotencyKey': 'delete-invalid-selection',
            'payload': {'nodeIds': [image_id, 'missing-node'], 'edgeIds': []},
        },
    )

    assert response.status_code == 404
    snapshot = client.get(f'/api/canvases/{canvas_id}/snapshot').json()
    assert snapshot['revision'] == 1
    assert [node['id'] for node in snapshot['nodes']] == [image_id]


def test_move_nodes_persists_a_selected_group_in_one_revision(client: TestClient):
    canvas_id = create_canvas(client)
    image_id = create_node(client, canvas_id, 'image', 'image')
    video_id = create_node(client, canvas_id, 'video', 'video')

    response = client.post(
        f'/api/canvases/{canvas_id}/commands',
        json={
            'command': 'move_nodes',
            'baseRevision': 2,
            'idempotencyKey': 'move-selection',
            'payload': {
                'positions': [
                    {'nodeId': image_id, 'x': 210, 'y': 220},
                    {'nodeId': video_id, 'x': 510, 'y': 220},
                ],
            },
        },
    )

    assert response.status_code == 200
    assert response.json()['revision'] == 3
    nodes = client.get(f'/api/canvases/{canvas_id}/snapshot').json()['nodes']
    assert {node['id']: (node['x'], node['y']) for node in nodes} == {
        image_id: (210, 220),
        video_id: (510, 220),
    }
