from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image


def make_png() -> bytes:
    output = BytesIO()
    Image.new('RGB', (320, 240), color=(90, 100, 120)).save(output, format='PNG')
    return output.getvalue()


def command(client: TestClient, canvas_id: str, name: str, revision: int, payload: dict):
    return client.post(
        f'/api/canvases/{canvas_id}/commands',
        json={
            'command': name,
            'baseRevision': revision,
            'idempotencyKey': f'{name}-{revision}-{payload.get("nodeId", payload.get("targetNodeId", ""))}',
            'payload': payload,
        },
    )


def test_canvas_upload_connect_and_queue_generation(client: TestClient):
    canvas_id = client.post('/api/canvases', json={'name': 'E2E'}).json()['canvasId']
    image_result = command(client, canvas_id, 'create_node', 0, {'nodeType': 'image', 'x': 0, 'y': 0})
    image_id = image_result.json()['payload']['nodeId']
    video_result = command(client, canvas_id, 'create_node', 1, {'nodeType': 'video', 'x': 360, 'y': 0})
    video_id = video_result.json()['payload']['nodeId']

    upload = client.post(
        '/api/assets/upload',
        data={'canvasId': canvas_id},
        files={'file': ('reference.png', make_png(), 'image/png')},
    )
    assert upload.status_code == 201
    asset_id = upload.json()['id']

    attached = command(client, canvas_id, 'attach_asset', 2, {'nodeId': image_id, 'assetId': asset_id})
    assert attached.status_code == 200
    connected = command(
        client,
        canvas_id,
        'connect_nodes',
        3,
        {'edgeId': 'edge-1', 'sourceNodeId': image_id, 'targetNodeId': video_id},
    )
    assert connected.status_code == 200
    queued = command(
        client,
        canvas_id,
        'start_generation',
        4,
        {
            'targetNodeId': video_id,
            'prompt': 'animate the reference',
            'parameters': {
                'duration': 5,
                'resolution': '720p',
                'aspectRatio': 'adaptive',
                'generateAudio': True,
            },
        },
    )
    assert queued.status_code == 200
    assert queued.json()['payload']['status'] == 'queued'
    assert client.get(f'/api/canvases/{canvas_id}/snapshot').json()['jobs'][0]['status'] == 'queued'
