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

from PIL import Image, ImageDraw

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


def _encode(image: Image.Image, max_side: int = MAX_SIDE) -> dict:
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


def video_frame(path: Path, at: float) -> Image.Image:
    """One frame of a video as a PIL image (clamped into the video's length)."""
    if not shutil.which('ffmpeg'):
        raise DomainError('FFMPEG_MISSING', '没有找到 ffmpeg，无法查看视频内容，请先安装（brew install ffmpeg）')
    png = subprocess.run(
        ['ffmpeg', '-v', 'error', '-ss', f'{max(at, 0):.3f}', '-i', str(path), '-frames:v', '1',
         '-f', 'image2pipe', '-vcodec', 'png', '-'],
        capture_output=True, check=True, timeout=60,
    ).stdout
    if not png:
        raise DomainError('FRAME_MISSING', f'取不到第 {at:.1f} 秒的画面')
    with Image.open(io.BytesIO(png)) as image:
        return image.convert('RGB')


def mark_point(image: Image.Image, x: float, y: float, max_side: int = MAX_SIDE) -> tuple[dict, dict]:
    """(whole picture with a ring and cross at (x, y), zoomed-in crop around that point).

    x, y are 0-1 from the top left. A drawn mark is more reliable than coordinates: the model
    can see where it is, but is poor at turning numbers into a place in the picture.
    """
    whole = image.convert('RGB')
    whole.thumbnail((max_side, max_side))
    width, height = whole.size
    px, py = x * width, y * height
    marked = whole.copy()
    _draw_mark(marked, px, py, max(14, round(max(width, height) * 0.035)))

    # Zoom: about a third of the picture, centred on the point (shifted to stay inside).
    crop_w, crop_h = max(width // 3, 1), max(height // 3, 1)
    left = min(max(px - crop_w / 2, 0), width - crop_w)
    top = min(max(py - crop_h / 2, 0), height - crop_h)
    crop = whole.crop((round(left), round(top), round(left) + crop_w, round(top) + crop_h))
    scale = min(768 / max(crop.size), 4.0)
    if scale > 1:
        crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.LANCZOS)
    else:
        scale = 1.0
    _draw_mark(crop, (px - round(left)) * scale, (py - round(top)) * scale,
               max(18, round(max(crop.size) * 0.05)), cross=False)
    return _encode(marked, max_side), _encode(crop, max_side)


def _draw_mark(image: Image.Image, px: float, py: float, radius: int, cross: bool = True) -> None:
    draw = ImageDraw.Draw(image)
    width = max(2, radius // 5)
    box = (px - radius, py - radius, px + radius, py + radius)
    # White halo under a red ring, so the mark shows on dark and light pictures alike.
    draw.ellipse(box, outline=(255, 255, 255), width=width + 2)
    draw.ellipse((box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1), outline=(255, 40, 40), width=width)
    if cross:
        arm = radius // 2
        for a, b in (((px - arm, py), (px + arm, py)), ((px, py - arm), (px, py + arm))):
            draw.line((a, b), fill=(255, 255, 255), width=width + 2)
            draw.line((a, b), fill=(255, 40, 40), width=max(1, width - 1))


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
