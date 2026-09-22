from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image


def make_png(width: int, height: int) -> bytes:
    output = BytesIO()
    Image.new('RGB', (width, height), color=(20, 30, 40)).save(output, format='PNG')
    return output.getvalue()


def upload(client: TestClient, content: bytes, filename: str, content_type: str):
    canvas_id = client.post('/api/canvases', json={'name': 'Assets'}).json()['canvasId']
    return client.post(
        '/api/assets/upload',
        data={'canvasId': canvas_id},
        files={'file': (filename, content, content_type)},
    )


def test_image_upload_saves_asset_and_dimensions(client: TestClient):
    image = make_png(width=640, height=480)
    response = upload(client, image, 'reference.png', 'image/png')
    assert response.status_code == 201
    assert response.json()['kind'] == 'image'
    assert response.json()['width'] == 640
    assert response.json()['height'] == 480


def test_unsupported_upload_type_is_rejected(client: TestClient):
    response = upload(client, b'hello', 'bad.txt', 'text/plain')
    assert response.status_code == 415
    assert response.json()['error']['code'] == 'UNSUPPORTED_MEDIA_TYPE'
