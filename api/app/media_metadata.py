from dataclasses import dataclass
import json
from pathlib import Path
import subprocess

from PIL import Image, UnidentifiedImageError

from .domain import DomainError


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    kind: str
    mime_type: str
    width: int
    height: int
    duration_seconds: float | None = None
    format: str | None = None


def read_image_metadata(path: Path) -> MediaMetadata:
    try:
        with Image.open(path) as image:
            image.load()
            image_format = (image.format or '').lower()
            mime_type = Image.MIME.get(image.format or '', '')
            if not mime_type:
                raise ValueError('image format is unavailable')
            return MediaMetadata(
                kind='image',
                mime_type=mime_type,
                width=image.width,
                height=image.height,
                format=image_format,
            )
    except (OSError, UnidentifiedImageError, ValueError) as error:
        raise DomainError('MEDIA_METADATA_UNAVAILABLE', str(error)) from error


def read_video_metadata(path: Path, ffprobe_bin: str = 'ffprobe') -> MediaMetadata:
    command = [
        ffprobe_bin,
        '-v',
        'error',
        '-show_entries',
        'stream=width,height,duration:format=duration',
        '-of',
        'json',
        str(path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)
        stream = next(
            stream
            for stream in payload.get('streams', [])
            if stream.get('width') and stream.get('height')
        )
        duration = stream.get('duration') or payload.get('format', {}).get('duration')
        return MediaMetadata(
            kind='video',
            mime_type='video/mp4',
            width=int(stream['width']),
            height=int(stream['height']),
            duration_seconds=float(duration) if duration is not None else None,
        )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration, json.JSONDecodeError) as error:
        raise DomainError('MEDIA_METADATA_UNAVAILABLE', str(error)) from error
