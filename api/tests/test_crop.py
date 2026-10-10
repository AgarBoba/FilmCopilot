from io import BytesIO

import pytest
from PIL import Image
from app.agent.canvas_tools import CanvasTools
from app.agent.config import AgentConfig


def command(client, canvas, kind, payload, key=None):
    revision = client.get(f'/api/canvases/{canvas}/snapshot').json()['revision']
    return client.post(f'/api/canvases/{canvas}/commands', json={
        'command': kind, 'payload': payload, 'baseRevision': revision,
        'idempotencyKey': key or f'{kind}-{revision}',
    })


def source(client):
    canvas = client.post('/api/canvases', json={'name': 'Crop'}).json()['canvasId']
    image = Image.new('RGBA', (8, 6), (10, 20, 30, 0))
    image.putpixel((2, 1), (200, 100, 50, 120))
    stream = BytesIO()
    image.save(stream, format='PNG')
    asset = client.post('/api/assets/upload', data={'canvasId': canvas},
        files={'file': ('source.png', stream.getvalue(), 'image/png')}).json()['id']
    node = command(client, canvas, 'create_node', {
        'nodeType': 'image', 'x': 10, 'y': 20, 'width': 300, 'height': 260,
        'data': {'title': '角色', 'prompt': '原提示词', 'assetId': asset,
                 'model': 'old-model', 'parameters': {'size': '1K'}},
    }).json()['payload']['nodeId']
    return canvas, node, asset


def crop(client, canvas, node, asset, rect=None, key=None):
    return command(client, canvas, 'crop_image', {'sourceNodeId': node, 'sourceAssetId': asset,
        'rect': rect if rect is not None else {'x': 2, 'y': 1, 'width': 3, 'height': 4}}, key)


def test_crop_new_node_pixels_provenance_and_retry(client):
    canvas, node, asset = source(client)
    note = command(client, canvas, 'create_node', {'nodeType': 'note'}).json()['payload']['nodeId']
    command(client, canvas, 'connect_nodes', {'sourceNodeId': note, 'targetNodeId': node})
    before = client.get(f'/api/canvases/{canvas}/snapshot').json()
    result = crop(client, canvas, node, asset, key='same-crop')
    assert result.status_code == 200, result.text
    new_id = result.json()['payload']['nodeId']
    snapshot = client.get(f'/api/canvases/{canvas}/snapshot').json()
    new = next(n for n in snapshot['nodes'] if n['id'] == new_id)
    assert next(n for n in snapshot['nodes'] if n['id'] == node) == next(n for n in before['nodes'] if n['id'] == node)
    assert snapshot['edges'] == before['edges']
    assert new['data']['prompt'] == '' and new['data']['model'] == 'seedream-5-pro'
    assert new['data']['parameters']['size'] == '2K'
    assert new['x'] >= 350 and new['data']['title'] == '角色 · 裁剪'
    origin = new['data']['cropSource']
    assert origin['nodeId'] == node and origin['assetId'] == asset
    assert origin['version'] == 1 and origin['title'] == '角色'
    assert origin['rect'] == {'x': 2, 'y': 1, 'width': 3, 'height': 4}
    with Image.open(BytesIO(client.get(f"/api/assets/{new['data']['assetId']}/file").content)) as image:
        assert image.size == (3, 4)
        assert image.getpixel((0, 0)) == (200, 100, 50, 120)
        assert image.getpixel((1, 0))[3] == 0
    assert crop(client, canvas, node, asset, key='same-crop').json() == result.json()
    assert len(client.get(f'/api/canvases/{canvas}/snapshot').json()['nodes']) == 3
    command(client, canvas, 'delete_node', {'nodeId': node})
    app = client.app
    store = app.state.agent_store
    run = store.create_run(store.create_session(canvas)['id'], 'auto')['id']
    tools = CanvasTools(app.state.canvas_repository, app.state.canvas_command_service, store, canvas, run, AgentConfig())
    for text in (tools.get_canvas().text, tools.get_node(new_id).text):
        assert '裁剪来源' in text and '角色' in text and node in text and '第 1 版' in text


@pytest.mark.parametrize('rect', [
    {'x': -1, 'y': 0, 'width': 2, 'height': 2},
    {'x': 7, 'y': 0, 'width': 2, 'height': 2},
    {'x': 0, 'y': 0, 'width': 0, 'height': 2},
    {'x': 0.5, 'y': 0, 'width': 2, 'height': 2},
    {'x': True, 'y': 0, 'width': 2, 'height': 2},
    {'x': 0, 'y': 0, 'width': 8, 'height': 6}, {'x': 0},
])
def test_invalid_crop_leaves_canvas_unchanged(client, rect):
    canvas, node, asset = source(client)
    before = client.get(f'/api/canvases/{canvas}/snapshot').json()
    response = crop(client, canvas, node, asset, rect)
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_CROP'
    assert client.get(f'/api/canvases/{canvas}/snapshot').json() == before


def test_stale_image_and_busy_source_rejected(client):
    canvas, node, asset = source(client)
    response = crop(client, canvas, node, 'stale-asset')
    assert response.json()['error']['code'] == 'CROP_SOURCE_CHANGED'
    repository = client.app.state.canvas_repository
    repository.create_generation_job(canvas, node, 'replicate', repository.generation_snapshot(canvas, node), {})
    assert crop(client, canvas, node, asset).json()['error']['code'] == 'CROP_BUSY'
    assert len(repository.get_snapshot(canvas).nodes) == 1


def test_multiple_crops_avoid_existing_nodes(client):
    canvas, node, asset = source(client)
    first = crop(client, canvas, node, asset).json()['payload']['nodeId']
    second = crop(client, canvas, node, asset).json()['payload']['nodeId']
    nodes = {n.id: n for n in client.app.state.canvas_repository.get_snapshot(canvas).nodes}
    assert nodes[first].x + nodes[first].width <= nodes[second].x or nodes[first].y != nodes[second].y


def test_crop_uses_display_orientation_for_phone_photos(client):
    canvas, node, _ = source(client)
    image = Image.new('RGB', (8, 6))
    exif = image.getexif()
    exif[274] = 6
    stream = BytesIO()
    image.save(stream, format='JPEG', exif=exif)
    asset = client.post('/api/assets/upload', data={'canvasId': canvas},
        files={'file': ('phone.jpg', stream.getvalue(), 'image/jpeg')}).json()['id']
    command(client, canvas, 'attach_asset', {'nodeId': node, 'assetId': asset})
    result = crop(client, canvas, node, asset, {'x': 1, 'y': 6, 'width': 3, 'height': 2})
    assert result.status_code == 200, result.text
    new = client.app.state.canvas_repository.node_snapshot(canvas, result.json()['payload']['nodeId'])
    assert new['data']['cropSource']['sourceSize'] == {'width': 6, 'height': 8}
    assert new['data']['cropSource']['version'] == 2
    with Image.open(BytesIO(client.get(f"/api/assets/{new['data']['assetId']}/file").content)) as output:
        assert output.size == (3, 2)
        assert output.getexif().get(274) is None
    inputs = client.app.state.canvas_repository.generation_snapshot(canvas, new['id'])
    assert inputs['prompt'] == '' and inputs['references'] == []
