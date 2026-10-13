"""Local video operations for building long continuous shots: take one frame of a video as a new
image node, and join several video nodes end to end into a new video node.

Both run inside the canvas command transaction with ffmpeg on this machine (no model call, no
credits). The source nodes are never changed; the result is a new node that remembers where it
came from (data.frameSource / data.joinSource), like a crop (crop.py).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import resolve_project_path
from .domain import DomainError
from .media_metadata import read_image_metadata, read_video_metadata
from .models_registry import registry
from .versions import NodeVersions, version_source

FRAME_POSITIONS = ('first', 'last')
MAX_CLIPS = 20


def _ffmpeg() -> None:
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise DomainError('FFMPEG_MISSING', '没有找到 ffmpeg，无法处理视频，请先安装（brew install ffmpeg）')


def _video_source(repository, canvas_id: str, node_id: Any, snapshot) -> tuple[dict, dict, Path]:
    if not isinstance(node_id, str) or not node_id:
        raise DomainError('INVALID_PAYLOAD', '缺少视频节点。')
    node = repository.node_snapshot(canvas_id, node_id)
    title = node['data'].get('title') or '视频节点'
    asset_id = node['data'].get('assetId')
    if node['nodeType'] != 'video' or not asset_id:
        raise DomainError('INVALID_CLIP', f'「{title}」不是有视频的视频节点。')
    if any(job['target_node_id'] == node_id and job['status'] in ('queued', 'running') for job in snapshot.jobs):
        raise DomainError('CLIP_BUSY', f'「{title}」正在生成，完成后再处理。')
    asset = repository.asset_dict(asset_id)
    if asset['kind'] != 'video' or asset.get('canvas_id') not in (None, canvas_id):
        raise DomainError('INVALID_CLIP', f'「{title}」的视频不属于当前画布。')
    path = resolve_project_path(asset['path'])
    if not path.exists():
        raise DomainError('INVALID_CLIP', f'「{title}」的视频文件找不到了。')
    return node, asset, path


def _duration(path: Path) -> float:
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
                            capture_output=True, text=True, check=False)
    try:
        return float(json.loads(result.stdout)['format']['duration'])
    except (ValueError, KeyError, TypeError):
        raise DomainError('INVALID_CLIP', '读不出视频时长，文件可能已损坏。') from None


def _has_audio(path: Path) -> bool:
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index',
                             '-of', 'csv=p=0', str(path)], capture_output=True, text=True, check=False)
    return bool(result.stdout.strip())


def _place(node: dict, snapshot, width: float, height: float, below: bool = False) -> tuple[float, float]:
    """Right of the source (or below it), moved along past anything already there."""
    if below:
        x, y = node['x'], node['y'] + (node.get('height') or 260) + 60
    else:
        x, y = node['x'] + (node.get('width') or 300) + 60, node['y']
    while True:
        overlaps = [n for n in snapshot.nodes if
                    x < n.x + (n.width or 300) + 20 and x + width + 20 > n.x and
                    y < n.y + (n.height or 260) + 20 and y + height + 20 > n.y]
        if not overlaps:
            return x, y
        if below:
            y = max(n.y + (n.height or 260) for n in overlaps) + 60
        else:
            x = max(n.x + (n.width or 300) for n in overlaps) + 60


def _run(command: list[str], what: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or '').strip().splitlines()[-1:] or ['']
        raise DomainError('CLIP_FAILED', f'{what}失败：{detail[0][:200]}')


def _new_node(repository, canvas_id: str, kind: str, x: float, y: float, width: float, height: float,
              data: dict, asset: dict, source: str) -> str:
    model = registry().for_node(kind, None)
    if model:
        data = {**data, 'model': model.id}
        data['parameters'], _ = model.resolve_parameters({})
    repository.insert_asset(asset)
    node_id = str(uuid4())
    with version_source(source):
        repository.insert_node(canvas_id, node_id, kind, x, y, width, height, data)
    return node_id


def extract_frame(repository, canvas_id: str, payload: dict, data_dir: Path) -> dict:
    """payload: sourceNodeId, at = 'last' (default) | 'first' | seconds from the start."""
    _ffmpeg()
    snapshot = repository.get_snapshot(canvas_id)
    node, asset, path = _video_source(repository, canvas_id, payload.get('sourceNodeId'), snapshot)
    title = node['data'].get('title') or '视频节点'
    at = payload.get('at', 'last')
    duration = float(asset.get('duration_seconds') or 0) or _duration(path)
    if at == 'last':
        seconds, label = duration, '末帧'
    elif at == 'first':
        seconds, label = 0.0, '首帧'
    elif isinstance(at, (int, float)) and not isinstance(at, bool) and 0 <= at <= duration + 0.05:
        seconds, label = float(at), f'第 {float(at):g} 秒'
    else:
        raise DomainError('INVALID_PAYLOAD', f'at 要是 first、last，或 0 到 {duration:.1f} 之间的秒数')
    new_asset = str(uuid4())
    destination = data_dir / 'assets' / new_asset / 'frame.png'
    destination.parent.mkdir(parents=True, exist_ok=False)
    try:
        if at == 'last':
            # Decode the last second and keep overwriting: the file ends up holding the very last frame.
            _run(['ffmpeg', '-v', 'error', '-y', '-sseof', '-1', '-i', str(path), '-update', '1', str(destination)],
                 '截取画面')
        else:
            _run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{seconds:.3f}', '-i', str(path), '-frames:v', '1',
                  str(destination)], '截取画面')
        if not destination.exists():
            raise DomainError('CLIP_FAILED', '截取画面失败：没有得到图片')
        meta = read_image_metadata(destination)
        version = NodeVersions(repository.database).current(canvas_id, node['id'], asset['id'])
        origin = {'nodeId': payload['sourceNodeId'], 'title': title, 'assetId': asset['id'], 'version': version,
                  'at': round(seconds, 3), 'position': at if at in FRAME_POSITIONS else 'time'}
        width = 300.0
        height = round(width * meta.height / meta.width) + 60 if meta.width else 260.0
        height = float(max(200, min(height, 520)))
        x, y = _place(node, snapshot, width, height)
        node_id = _new_node(repository, canvas_id, 'image', x, y, width, height,
                            {'title': f'{title} · {label}', 'prompt': '', 'assetId': new_asset, 'frameSource': origin},
                            {'id': new_asset, 'canvas_id': canvas_id, 'kind': 'image', 'path': str(destination),
                             'original_name': 'frame.png', 'mime_type': meta.mime_type, 'width': meta.width,
                             'height': meta.height, 'checksum': sha256(destination.read_bytes()).hexdigest(),
                             'metadata': {'frameSource': origin}},
                            'frame')
    except Exception:
        destination.unlink(missing_ok=True)
        if destination.parent.exists():
            destination.parent.rmdir()
        raise
    return {'nodeId': node_id, 'assetId': new_asset, 'sourceNodeId': payload['sourceNodeId'],
            'at': round(seconds, 3), 'width': meta.width, 'height': meta.height}


def join_videos(repository, canvas_id: str, payload: dict, data_dir: Path) -> dict:
    """payload: clips = [{nodeId, start?, end?}] in playing order (2 or more), title?.
    start / end trim each clip (seconds); the result takes the first clip's size and frame rate."""
    _ffmpeg()
    clips = payload.get('clips')
    if not isinstance(clips, list) or not 2 <= len(clips) <= MAX_CLIPS:
        raise DomainError('INVALID_PAYLOAD', f'要拼接 2 到 {MAX_CLIPS} 段视频')
    snapshot = repository.get_snapshot(canvas_id)
    parts = []
    for clip in clips:
        if not isinstance(clip, dict):
            raise DomainError('INVALID_PAYLOAD', 'clips 里每一项要写成 {nodeId, start?, end?}')
        node, asset, path = _video_source(repository, canvas_id, clip.get('nodeId'), snapshot)
        duration = float(asset.get('duration_seconds') or 0) or _duration(path)
        start, end = clip.get('start', 0) or 0, clip.get('end', duration)
        if end is None:
            end = duration
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (start, end)) \
                or not 0 <= start < end <= duration + 0.05:
            raise DomainError('INVALID_PAYLOAD',
                              f"「{node['data'].get('title', '')}」的 start / end 要在 0 到 {duration:.1f} 秒之间，且 start < end")
        parts.append({'node': node, 'asset': asset, 'path': path, 'start': float(start), 'end': min(float(end), duration),
                      'audio': _has_audio(path)})
    first = parts[0]['asset']
    width, height = int(first.get('width') or 1280), int(first.get('height') or 720)
    width, height = width - width % 2, height - height % 2
    with_audio = any(part['audio'] for part in parts)
    inputs: list[str] = []
    filters: list[str] = []
    for index, part in enumerate(parts):
        length = part['end'] - part['start']
        inputs += ['-ss', f"{part['start']:.3f}", '-t', f'{length:.3f}', '-i', str(part['path'])]
        filters.append(f'[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,'
                       f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,format=yuv420p[v{index}]')
    silence_base = len(parts)
    for index, part in enumerate(parts):
        if not with_audio:
            break
        if part['audio']:
            filters.append(f'[{index}:a]aresample=48000,aformat=channel_layouts=stereo[a{index}]')
        else:  # a silent track of the same length, so every clip has sound for concat
            inputs += ['-f', 'lavfi', '-t', f"{part['end'] - part['start']:.3f}", '-i',
                       'anullsrc=r=48000:cl=stereo']
            filters.append(f'[{silence_base}:a]anull[a{index}]')
            silence_base += 1
    streams = ''.join(f'[v{i}]' + (f'[a{i}]' if with_audio else '') for i in range(len(parts)))
    filters.append(f"{streams}concat=n={len(parts)}:v=1:a={1 if with_audio else 0}[v]" + ('[a]' if with_audio else ''))
    new_asset = str(uuid4())
    destination = data_dir / 'assets' / new_asset / 'joined.mp4'
    destination.parent.mkdir(parents=True, exist_ok=False)
    try:
        command = ['ffmpeg', '-v', 'error', '-y', *inputs, '-filter_complex', ';'.join(filters), '-map', '[v]']
        if with_audio:
            command += ['-map', '[a]', '-c:a', 'aac', '-b:a', '192k']
        command += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-movflags', '+faststart', str(destination)]
        _run(command, '拼接视频')
        meta = read_video_metadata(destination)
        versions = NodeVersions(repository.database)
        origin = {'clips': [{'nodeId': part['node']['id'],
                             'title': part['node']['data'].get('title', ''), 'assetId': part['asset']['id'],
                             'version': versions.current(canvas_id, part['node']['id'], part['asset']['id']),
                             'start': round(part['start'], 3), 'end': round(part['end'], 3)}
                            for part in parts]}
        titles = [part['node']['data'].get('title', '') for part in parts]
        title = str(payload.get('title') or '').strip()[:60] or f'{titles[0]} 等 {len(parts)} 段（拼接）'
        x, y = _place(parts[-1]['node'], snapshot, 300.0, 260.0, below=True)
        node_id = _new_node(repository, canvas_id, 'video', x, y, 300.0, 260.0,
                            {'title': title, 'prompt': '', 'assetId': new_asset, 'joinSource': origin},
                            {'id': new_asset, 'canvas_id': canvas_id, 'kind': 'video', 'path': str(destination),
                             'original_name': 'joined.mp4', 'mime_type': meta.mime_type, 'width': meta.width,
                             'height': meta.height, 'duration_seconds': meta.duration_seconds,
                             'checksum': sha256(destination.read_bytes()).hexdigest(), 'metadata': {'joinSource': origin}},
                            'joined')
    except Exception:
        destination.unlink(missing_ok=True)
        if destination.parent.exists():
            destination.parent.rmdir()
        raise
    return {'nodeId': node_id, 'assetId': new_asset, 'duration': meta.duration_seconds,
            'clips': len(parts), 'width': meta.width, 'height': meta.height}


def describe_clip_source(data: dict) -> str | None:
    """For the agent: where a frame or a joined video came from (not a reference connection)."""
    frame = data.get('frameSource')
    if isinstance(frame, dict):
        where = {'last': '末帧', 'first': '首帧'}.get(frame.get('position'), f"第 {frame.get('at')} 秒")
        return (f"截取来源：「{frame.get('title', '视频节点')}」[{frame.get('nodeId', '')}] 第 {frame.get('version', 1)} 版的{where}"
                f"（{frame.get('at')} 秒处）。这是来源记录，不是参考连线。")
    joined = data.get('joinSource')
    if isinstance(joined, dict):
        items = '、'.join(f"「{c.get('title', '')}」[{c.get('nodeId', '')}] {c.get('start')}–{c.get('end')} 秒"
                         for c in joined.get('clips', []))
        return f'拼接来源（按播放顺序）：{items}。这是来源记录，不是参考连线。'
    return None
