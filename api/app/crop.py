"""Local pixel cropping. Called inside the canvas command transaction, never a model call."""
from pathlib import Path
from hashlib import sha256
from uuid import uuid4

from PIL import Image, ImageOps

from .config import resolve_project_path
from .domain import DomainError
from .models_registry import registry
from .versions import NodeVersions, version_source


def crop_image(repository, canvas_id: str, payload: dict, data_dir: Path) -> dict:
    node_id = payload.get('sourceNodeId')
    if not isinstance(node_id, str) or not node_id:
        raise DomainError('INVALID_CROP', '缺少来源图片节点。')
    node = repository.node_snapshot(canvas_id, node_id)
    asset_id = node['data'].get('assetId')
    if node['nodeType'] != 'image' or not asset_id:
        raise DomainError('INVALID_CROP', '只能裁剪有图片的图片节点。')
    if payload.get('sourceAssetId') != asset_id:
        raise DomainError('CROP_SOURCE_CHANGED', '原图片已变化，请关闭并重新打开裁剪。')
    snapshot = repository.get_snapshot(canvas_id)
    if any(job['target_node_id'] == node_id and job['status'] in ('queued', 'running') for job in snapshot.jobs):
        raise DomainError('CROP_BUSY', '图片正在生成，请完成后再裁剪。')
    asset = repository.asset_dict(asset_id)
    if asset['kind'] != 'image' or asset['canvas_id'] != canvas_id:
        raise DomainError('INVALID_CROP', '来源图片不属于当前画布。')
    rect = payload.get('rect')
    if not isinstance(rect, dict) or any(type(rect.get(k)) is not int for k in ('x', 'y', 'width', 'height')):
        raise DomainError('INVALID_CROP', '裁剪范围必须是整数像素。')
    x, y, w, h = (rect[k] for k in ('x', 'y', 'width', 'height'))
    with Image.open(resolve_project_path(asset['path'])) as original:
        image = ImageOps.exif_transpose(original)
        size = image.size
        if x < 0 or y < 0 or w < 1 or h < 1 or x + w > size[0] or y + h > size[1]:
            raise DomainError('INVALID_CROP', '裁剪范围超出了图片，或尺寸为空。')
        if (x, y, w, h) == (0, 0, *size):
            raise DomainError('INVALID_CROP', '请先调整裁剪范围。')
        output = image.crop((x, y, x + w, y + h)).convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
    version = NodeVersions(repository.database).current(canvas_id, node_id, asset_id)
    origin = {'nodeId': node_id, 'title': node['data'].get('title') or '图片节点',
              'assetId': asset_id, 'version': version, 'rect': {k: rect[k] for k in ('x', 'y', 'width', 'height')},
              'sourceSize': {'width': size[0], 'height': size[1]}}
    new_id, new_asset = str(uuid4()), str(uuid4())
    destination = data_dir / 'assets' / new_asset / 'crop.png'
    width, height = node.get('width') or 300, node.get('height') or 260
    nx, ny = node['x'] + width + 40, node['y']
    # Move right past every occupied rectangle, including earlier crops.
    while True:
        overlaps = [n for n in snapshot.nodes if
                    nx < n.x + (n.width or 300) + 20 and nx + width + 20 > n.x and
                    ny < n.y + (n.height or 260) + 20 and ny + height + 20 > n.y]
        if not overlaps:
            break
        nx = max(n.x + (n.width or 300) + 40 for n in overlaps)
    model = registry().for_node('image', None)
    data = {'title': origin['title'] + ' · 裁剪', 'prompt': '', 'assetId': new_asset, 'cropSource': origin}
    if model:
        data['model'] = model.id
        data['parameters'], _ = model.resolve_parameters({})
    try:
        destination.parent.mkdir(parents=True, exist_ok=False)
        output.save(destination, format='PNG')
        repository.insert_asset({'id': new_asset, 'canvas_id': canvas_id, 'kind': 'image',
            'path': str(destination), 'original_name': 'crop.png', 'mime_type': 'image/png',
            'width': w, 'height': h, 'checksum': sha256(destination.read_bytes()).hexdigest(),
            'metadata': {'cropSource': origin}})
        with version_source('cropped'):
            repository.insert_node(canvas_id, new_id, 'image', nx, ny, width, height, data)
    except Exception:
        destination.unlink(missing_ok=True)
        if destination.parent.exists():
            destination.parent.rmdir()
        raise
    return {'nodeId': new_id, 'assetId': new_asset, 'sourceNodeId': node_id}


def describe_source(data: dict) -> str | None:
    origin = data.get('cropSource')
    if not isinstance(origin, dict):
        return None
    rect = origin.get('rect', {})
    return (f"裁剪来源：「{origin.get('title', '图片节点')}」[{origin.get('nodeId', '')}] "
            f"第 {origin.get('version', 1)} 版；来源素材 [{origin.get('assetId', '')}]；"
            f"范围（左 {rect.get('x')}，上 {rect.get('y')}，宽 {rect.get('width')}，高 {rect.get('height')} 像素）。"
            '这是来源记录，不是参考连线，也不自动加入 Prompt。')
