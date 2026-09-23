import base64
import io
import shutil
import subprocess

import pytest
from PIL import Image

from app.agent import media


def test_image_is_downscaled_to_1024(tmp_path):
    path = tmp_path / 'wide.png'
    Image.new('RGB', (3000, 1500), (10, 20, 30)).save(path)
    result = media.image_for_model(path)
    image = Image.open(io.BytesIO(base64.b64decode(result['data'])))
    assert image.size == (1024, 512) and result['mimeType'] == 'image/jpeg'


def test_small_images_are_not_upscaled(tmp_path):
    path = tmp_path / 'small.png'
    Image.new('RGBA', (300, 200)).save(path)
    assert media.image_for_model(path)['width'] == 300


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg not installed')
def test_video_gives_three_frames(tmp_path):
    path = tmp_path / 'clip.mp4'
    subprocess.run(
        ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=1920x1080:rate=10', '-t', '3',
         '-pix_fmt', 'yuv420p', str(path)],
        check=True,
    )
    duration, frames = media.video_frames_for_model(path)
    assert 2.5 < duration < 3.5
    assert len(frames) == 3 and frames[0]['at'] == 0
    image = Image.open(io.BytesIO(base64.b64decode(frames[1]['data'])))
    assert max(image.size) == 1024
