"""Prepare canvas media for the model: downscale images, pull key frames from videos.

Images are billed by pixel, so everything sent to the model is capped at 1024 px on the
long side (spec 3.2). Videos are summarised as three frames: start, middle, end.
"""
import base64
import io
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image

from ..domain import DomainError

MAX_SIDE = 1024


def image_for_model(path: Path, max_side: int = MAX_SIDE) -> dict:
    """{'data': base64 JPEG, 'mimeType', 'width', 'height'} with the long side <= max_side."""
    with Image.open(path) as image:
        image = image.convert('RGB')
        image.thumbnail((max_side, max_side))
        buffer = io.BytesIO()
        image.save(buffer, 'JPEG', quality=85)
        return {
            'data': base64.b64encode(buffer.getvalue()).decode('ascii'),
            'mimeType': 'image/jpeg',
            'width': image.width,
            'height': image.height,
        }


def video_duration(path: Path) -> float:
    if not shutil.which('ffprobe'):
        raise DomainError('FFMPEG_MISSING', '没有找到 ffprobe，请先安装 ffmpeg（brew install ffmpeg）')
    output = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout
    return float(json.loads(output)['format']['duration'])


def video_frames_for_model(path: Path, count: int = 3, max_side: int = MAX_SIDE) -> tuple[float, list[dict]]:
    """(duration_seconds, frames) — frames taken at the start, middle and end of the video."""
    if not shutil.which('ffmpeg'):
        raise DomainError('FFMPEG_MISSING', '没有找到 ffmpeg，无法查看视频内容，请先安装（brew install ffmpeg）')
    duration = video_duration(path)
    last = max(duration - 0.1, 0)
    times = [0.0] if count == 1 else [last * index / (count - 1) for index in range(count)]
    frames = []
    for at in times:
        png = subprocess.run(
            ['ffmpeg', '-v', 'error', '-ss', f'{at:.3f}', '-i', str(path), '-frames:v', '1',
             '-f', 'image2pipe', '-vcodec', 'png', '-'],
            capture_output=True, check=True, timeout=60,
        ).stdout
        with Image.open(io.BytesIO(png)) as image:
            image = image.convert('RGB')
            image.thumbnail((max_side, max_side))
            buffer = io.BytesIO()
            image.save(buffer, 'JPEG', quality=85)
        frames.append({
            'data': base64.b64encode(buffer.getvalue()).decode('ascii'),
            'mimeType': 'image/jpeg',
            'at': round(at, 2),
        })
    return duration, frames
