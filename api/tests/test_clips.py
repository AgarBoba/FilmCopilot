"""Frames and joins for long continuous shots (clips.py), the agent tools around them, and the
capability / skill pieces that point the agent at them."""
import shutil
import subprocess

import pytest
from PIL import Image

from app.agent.permissions import RunState, decide, describe_request
from app.agent.skills import discover
from app.domain import DomainError
from app.media_metadata import read_video_metadata
from app.models_registry import registry
from tests.test_canvas_tools import setup, user

pytestmark = pytest.mark.skipif(not shutil.which('ffmpeg'), reason='needs ffmpeg')


def make_video(path, seconds, color, size='320x180', audio=True):
    command = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={color}:s={size}:d={seconds}:r=24']
    if audio:
        command += ['-f', 'lavfi', '-i', f'sine=frequency=440:duration={seconds}', '-shortest']
    command += ['-pix_fmt', 'yuv420p', str(path)]
    subprocess.run(command, check=True)
    return path


def video_node(repository, service, canvas_id, tmp_path, node_id, seconds, color, **kwargs):
    path = make_video(tmp_path / f'{node_id}.mp4', seconds, color, **kwargs)
    meta = read_video_metadata(path)
    repository._execute(
        "INSERT INTO assets (id, canvas_id, kind, path, mime_type, width, height, duration_seconds) "
        "VALUES (?, ?, 'video', ?, 'video/mp4', ?, ?, ?)",
        (f'asset-{node_id}', canvas_id, str(path), meta.width, meta.height, meta.duration_seconds))
    user(service, repository, canvas_id, 'create_node',
         {'nodeId': node_id, 'nodeType': 'video', 'x': 0, 'y': 0, 'title': f'段 {node_id}'}, f'c-{node_id}')
    user(service, repository, canvas_id, 'attach_asset', {'nodeId': node_id, 'assetId': f'asset-{node_id}'}, f'a-{node_id}')


def node(repository, canvas_id, node_id):
    return next(n for n in repository.get_snapshot(canvas_id).nodes if n.id == node_id)


def test_the_last_frame_becomes_a_new_image_node(repository, tmp_path):
    tools, service, canvas_id = setup(repository)
    video_node(repository, service, canvas_id, tmp_path, 'v1', 2, 'red')
    result = user(service, repository, canvas_id, 'extract_frame', {'sourceNodeId': 'v1'}, 'f1')
    frame = node(repository, canvas_id, result['nodeId'])
    assert frame.nodeType == 'image' and frame.data['title'] == '段 v1 · 末帧'
    assert frame.data['frameSource']['nodeId'] == 'v1' and frame.data['frameSource']['position'] == 'last'
    assert (result['width'], result['height']) == (320, 180) and result['at'] == pytest.approx(2, abs=0.1)
    asset = repository.asset_dict(result['assetId'])
    with Image.open(asset['path']) as image:
        r, g, b = image.convert('RGB').getpixel((160, 90))
    assert r > 200 and g < 60  # the red video's colour
    assert frame.x > node(repository, canvas_id, 'v1').x  # to the right of the source

    at_one = user(service, repository, canvas_id, 'extract_frame', {'sourceNodeId': 'v1', 'at': 1}, 'f2')
    assert node(repository, canvas_id, at_one['nodeId']).data['title'] == '段 v1 · 第 1 秒'
    for bad in ('middle', 99, True):
        with pytest.raises(DomainError):
            user(service, repository, canvas_id, 'extract_frame', {'sourceNodeId': 'v1', 'at': bad}, f'bad-{bad}')
    user(service, repository, canvas_id, 'create_node', {'nodeId': 'img', 'nodeType': 'image'}, 'img')
    with pytest.raises(DomainError) as error:
        user(service, repository, canvas_id, 'extract_frame', {'sourceNodeId': 'img'}, 'f3')
    assert error.value.code == 'INVALID_CLIP'


def test_videos_are_joined_in_order_with_trims_and_mixed_audio(repository, tmp_path):
    tools, service, canvas_id = setup(repository)
    video_node(repository, service, canvas_id, tmp_path, 'a', 2, 'red')
    video_node(repository, service, canvas_id, tmp_path, 'b', 3, 'blue', size='640x360', audio=False)
    result = user(service, repository, canvas_id, 'join_videos',
                  {'clips': [{'nodeId': 'a'}, {'nodeId': 'b', 'start': 1}], 'title': '一镜到底'}, 'j1')
    joined = node(repository, canvas_id, result['nodeId'])
    assert joined.nodeType == 'video' and joined.data['title'] == '一镜到底'
    assert [c['nodeId'] for c in joined.data['joinSource']['clips']] == ['a', 'b']
    assert joined.data['joinSource']['clips'][1]['start'] == 1
    assert result['duration'] == pytest.approx(4, abs=0.2)  # 2 s + (3 - 1) s
    assert (result['width'], result['height']) == (320, 180)  # the first clip's size
    path = repository.asset_dict(result['assetId'])['path']
    streams = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', path],
                             capture_output=True, text=True).stdout.split()
    assert sorted(streams) == ['audio', 'video']  # the silent clip got a silent track
    for bad in ([{'nodeId': 'a'}], [{'nodeId': 'a'}, {'nodeId': 'b', 'start': 2, 'end': 1}], [{'nodeId': 'a', 'end': 9}, {'nodeId': 'b'}]):
        with pytest.raises(DomainError):
            user(service, repository, canvas_id, 'join_videos', {'clips': bad}, f'bad-{len(str(bad))}')


def test_the_agent_tools_and_permissions(repository, tmp_path):
    tools, service, canvas_id = setup(repository)
    video_node(repository, service, canvas_id, tmp_path, 's1', 2, 'green')
    video_node(repository, service, canvas_id, tmp_path, 's2', 2, 'yellow')
    frame = tools.extract_frame('s1')
    assert not frame.is_error and '新建图片节点' in frame.text and len(frame.touched) == 2
    assert '截取来源' in tools.get_node(frame.touched[1]).text
    joined = tools.join_videos([{'node_id': 's1'}, {'node_id': 's2', 'start': 0.5}], title='接力')
    assert not joined.is_error and '共 3.5 秒' in joined.text
    assert '拼接来源' in tools.get_node(joined.touched[-1]).text
    assert tools.join_videos([{'node_id': 's1'}]).is_error
    assert tools.extract_frame('nope').is_error

    titles = {'s1': '段 1', 's2': '段 2'}
    for mode, expected in (('confirm_all', 'ask'), ('confirm_generation', 'allow'), ('auto', 'allow')):
        assert decide('mcp__canvas__join_videos', {'clips': []}, mode, RunState())[0] == expected
        assert decide('extract_frame', {'node_id': 's1'}, mode, RunState())[0] == expected
    assert describe_request('extract_frame', {'node_id': 's1'}, titles) == '从「段 1」截取末帧，新建一个图片节点'
    assert describe_request('join_videos', {'clips': [{'node_id': 's1'}, {'node_id': 's2'}]}, titles) \
        == '把 2 段视频按顺序拼成一个新视频：「段 1」、「段 2」'


def test_capabilities_and_skill_point_to_long_takes(repository):
    tools, _, _ = setup(repository)
    vocabulary = registry().capabilities()
    assert {'video_extend', 'video_edit'} <= set(vocabulary)
    assert 'video_extend' in registry().get('seedance-2.5').capabilities
    listed = tools.list_models(capability='video_extend').text
    assert '[seedance-2.5]' in listed and '[seedance-2.0-mini]' not in listed
    assert 'film-copilot:long-take' in registry().get('seedance-2.5').guide.text
    skill = next(s for s in discover() if s.id == 'film-copilot:long-take')
    assert skill.label == '一镜到底长镜头'
    body = skill.path.read_text(encoding='utf-8')
    for word in ('video_extend', 'first_last_frame', 'first_frame', 'extract_frame', 'join_videos'):
        assert word in body
    assert [s.name for s in discover() if s.source == 'builtin'][:2] == ['storyboard', 'long-take']
