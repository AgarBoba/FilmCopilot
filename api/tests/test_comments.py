import asyncio

import pytest

from app.agent.comments import CommentService
from app.agent.config import AgentConfig
from app.domain import DomainError
from tests.agent_fakes import FakeFactory
from tests.test_agent_runtime import CONFIG, make_service


def setup(repository, *scripts, config=CONFIG):
    factory = FakeFactory(*scripts)
    service, store, canvas_id, _ = make_service(repository, factory, config)
    return CommentService(service), service, store, canvas_id, factory


def add_image(repository, canvas_id, node_id='img', asset='a1', node_type='image'):
    repository.insert_node(canvas_id, node_id, node_type, 0, 0, 300, 260,
                           {'title': f'图片 {node_id}', **({'assetId': asset} if asset else {})})


async def settle(service, comments, *, until=None, timeout=5.0):
    """Wait until no comment run is active (and `until()` holds, if given)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        busy = any(runtime.task and not runtime.task.done() for runtime in service.sessions.values())
        if not busy and (until is None or until()):
            await asyncio.sleep(0.02)
            if not any(runtime.task and not runtime.task.done() for runtime in service.sessions.values()):
                return
        await asyncio.sleep(0.01)
    raise AssertionError('comments did not settle')


def test_a_comment_on_a_picture_starts_a_run_with_its_location(repository):
    comments, service, store, canvas_id, factory = setup(repository, [('text', '把天空改成黄昏了。')])
    add_image(repository, canvas_id)

    async def scenario():
        comment = await comments.create(
            canvas_id, {'kind': 'media', 'nodeId': 'img', 'x': 0.62, 'y': 0.3}, '这里的天空换成黄昏', to_agent=True)
        assert (comment['status'], comment['agentStatus']) == ('open', 'running')
        await settle(service, comments)
        return comment

    comment = asyncio.run(scenario())
    assert comment['anchor'] == {'kind': 'media', 'nodeId': 'img', 'version': 1, 'x': 0.62, 'y': 0.3, 'time': None,
                                 'assetId': 'a1', 'currentVersion': 1, 'stale': False}
    prompt = factory.clients[0].prompts[0]
    assert '[留言位置] 图片节点「图片 img」[img] 第 1 版，画面内 (62%, 30%) 处' in prompt
    assert prompt.endswith('这里的天空换成黄昏')
    session = store.get_session(comment['sessionId'])
    assert session['kind'] == 'comment' and session['title'] == '这里的天空换成黄昏'
    # The panel shows the words only, not the location block.
    first = store.list_messages(comment['sessionId'])[0]['content']
    assert first['text'] == '这里的天空换成黄昏' and first['focus'] == ['img']
    done = comments.get(comment['id'])
    assert (done['agentStatus'], done['outcome']) == ('done', '把天空改成黄昏了。')


def test_queue_runs_two_at_a_time_and_one_per_node(repository):
    slow = [('pause', 0.15), ('text', 'ok')]
    comments, service, _, canvas_id, _ = setup(repository, slow, slow, slow, slow)
    add_image(repository, canvas_id, 'a')
    add_image(repository, canvas_id, 'b')

    async def scenario():
        first = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'a'}, '一', to_agent=True)
        same_node = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'a'}, '二', to_agent=True)
        other = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'b'}, '三', to_agent=True)
        blank = await comments.create(canvas_id, {'kind': 'canvas', 'x': 10, 'y': 20}, '四', to_agent=True)
        started = [comments.get(c['id'])['agentStatus'] for c in (first, same_node, other, blank)]
        await settle(service, comments, until=lambda: all(
            comments.get(c['id'])['agentStatus'] == 'done' for c in (first, same_node, other, blank)))
        return started

    # "二" waits for "一" (same node) even though a slot is free; "四" waits for a slot.
    assert asyncio.run(scenario()) == ['running', 'queued', 'running', 'queued']


def test_confirmation_shows_as_waiting(repository):
    comments, service, _, canvas_id, _ = setup(
        repository, [('tool', 'generate', {'node_ids': ['img']}), ('text', '生成好了')])
    add_image(repository, canvas_id)

    async def scenario():
        updates = comments.subscribe(canvas_id)
        comment = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '重画一张', to_agent=True)
        session_queue = service.subscribe(comment['sessionId'])
        while True:
            event = await asyncio.wait_for(session_queue.get(), 5)
            if event['kind'] == 'confirm_request':
                service.confirm(event['requestId'], True)
                break
        await settle(service, comments)
        statuses = []
        while not updates.empty():
            status = updates.get_nowait()['agentStatus']
            if not statuses or statuses[-1] != status:
                statuses.append(status)
        return statuses

    assert asyncio.run(scenario()) == ['queued', 'running', 'waiting', 'running', 'done']


def test_reply_resolve_and_reopen(repository):
    comments, service, _, canvas_id, factory = setup(
        repository, [('pause', 0.1), ('text', '改好了')], [('text', '又改了一下')])
    add_image(repository, canvas_id)

    async def scenario():
        comment = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '暗一点', to_agent=True)
        with pytest.raises(DomainError) as busy:
            await comments.reply(comment['id'], '再暗一点', to_agent=True)
        assert busy.value.code == 'COMMENT_BUSY'
        with pytest.raises(DomainError):
            comments.resolve(comment['id'])
        # A plain reply is fine while the agent works.
        noted = await comments.reply(comment['id'], '（备忘：暗部别糊）')
        assert [r['text'] for r in noted['replies']] == ['（备忘：暗部别糊）'] and noted['agentStatus'] == 'running'
        await settle(service, comments)
        assert comments.resolve(comment['id'])['status'] == 'resolved'
        assert comments.list(canvas_id, 'open') == []
        assert comments.reopen(comment['id'])['status'] == 'open'
        comments.resolve(comment['id'])
        # Replying to the agent on a resolved comment reopens it and continues the same chat,
        # with the plain reply it hasn't seen yet.
        replied = await comments.reply(comment['id'], '再暗一点', to_agent=True)
        assert (replied['status'], replied['agentStatus'], replied['resolvedAt']) == ('open', 'running', None)
        await settle(service, comments)
        return comments.get(comment['id'])

    final = asyncio.run(scenario())
    assert (final['agentStatus'], final['outcome']) == ('done', '又改了一下')
    assert [(r['text'], r['toAgent']) for r in final['replies']] == [('（备忘：暗部别糊）', False), ('再暗一点', True)]
    second_prompt = factory.clients[0].prompts[1]
    assert '[留言位置]' not in second_prompt
    assert second_prompt.endswith('- （备忘：暗部别糊）\n- 再暗一点') and '最后一条最新' in second_prompt


def test_anchor_validation(repository):
    comments, _, _, canvas_id, _ = setup(repository)
    add_image(repository, canvas_id)
    add_image(repository, canvas_id, 'empty', asset=None)
    add_image(repository, canvas_id, 'vid', asset='v1', node_type='video')
    add_image(repository, canvas_id, 'note', asset=None, node_type='note')

    async def attempt(anchor):
        with pytest.raises(DomainError) as error:
            await comments.create(canvas_id, anchor, '看这里', to_agent=True)
        return error.value.code

    async def scenario():
        return [
            await attempt({'kind': 'media', 'nodeId': 'img', 'x': 1.2, 'y': 0.5}),
            await attempt({'kind': 'media', 'nodeId': 'empty', 'x': 0.5, 'y': 0.5}),
            await attempt({'kind': 'media', 'nodeId': 'note', 'x': 0.5, 'y': 0.5}),
            await attempt({'kind': 'media', 'nodeId': 'vid', 'x': 0.5, 'y': 0.5}),  # needs a time
            await attempt({'kind': 'node', 'nodeId': 'nope'}),
            await attempt({'kind': 'canvas', 'x': 'a', 'y': 0}),
            await attempt({'kind': 'region'}),
        ]

    assert asyncio.run(scenario()) == ['INVALID_PAYLOAD'] * 4 + ['NOT_FOUND'] + ['INVALID_PAYLOAD'] * 2
    assert comments.list(canvas_id) == []


def test_video_comment_records_the_moment(repository):
    comments, service, _, canvas_id, factory = setup(repository, [('text', 'ok')])
    add_image(repository, canvas_id, 'vid', asset='v1', node_type='video')

    async def scenario():
        comment = await comments.create(
            canvas_id, {'kind': 'media', 'nodeId': 'vid', 'x': 0.5, 'y': 0.25, 'time': 3.24}, '这里手抖了', to_agent=True)
        await settle(service, comments)
        return comment

    assert asyncio.run(scenario())['anchor']['time'] == 3.24
    assert '视频节点「图片 vid」[vid] 第 1 版，第 3.2 秒那一帧，画面内 (50%, 25%) 处' in factory.clients[0].prompts[0]


def test_queued_comment_on_a_deleted_node_fails(repository):
    comments, service, _, canvas_id, _ = setup(repository, [('pause', 0.1), ('text', 'ok')])
    add_image(repository, canvas_id)

    async def scenario():
        await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '一', to_agent=True)
        waiting = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '二', to_agent=True)
        repository.delete_node(canvas_id, 'img')
        await settle(service, comments, until=lambda: comments.get(waiting['id'])['agentStatus'] == 'failed')
        return comments.get(waiting['id'])

    failed = asyncio.run(scenario())
    assert failed['nodeMissing'] and '删除' in failed['outcome']


def test_needs_a_configured_agent_and_stays_out_of_other_chats(repository):
    comments, service, store, canvas_id, factory = setup(
        repository, config=AgentConfig(api_key_present=False))

    async def unconfigured():
        with pytest.raises(DomainError) as error:
            await comments.create(canvas_id, {'kind': 'canvas', 'x': 0, 'y': 0}, '加一个镜头', to_agent=True)
        return error.value.code

    assert asyncio.run(unconfigured()) == 'AGENT_NOT_CONFIGURED'
    assert comments.list(canvas_id) == []
    # A plain comment needs no agent at all.
    plain = asyncio.run(comments.create(canvas_id, {'kind': 'canvas', 'x': 0, 'y': 0}, '这里留个镜头位'))
    assert (plain['status'], plain['agentStatus'], plain['sessionId']) == ('open', None, None)

    comments, service, store, canvas_id, factory = setup(repository, [('text', '加好了')], [('text', 'hi')])

    async def scenario():
        await comments.create(canvas_id, {'kind': 'canvas', 'x': 0, 'y': 0}, '加一个镜头', to_agent=True)
        await settle(service, comments)
        chat = store.create_session(canvas_id)
        await service.send_message(chat['id'], '你好')
        await settle(service, comments)

    asyncio.run(scenario())
    prompt = factory.clients[-1].prompts[0]
    # Not listed as another chat; it reaches the main chat as a task-log line instead.
    assert '[这张画布上的其他对话]' not in prompt
    assert '[画布任务记录]' in prompt and '- 画布：加一个镜头 → 加好了，等用户查看' in prompt


def test_restart_marks_interrupted_runs_failed(repository):
    comments, service, _, canvas_id, _ = setup(repository)
    add_image(repository, canvas_id)
    with repository.transaction() as connection:
        connection.execute(
            "INSERT INTO canvas_comments (id, canvas_id, session_id, anchor_kind, node_id, text, status, agent_status) "
            "VALUES ('c1', ?, 's', 'node', 'img', '一', 'open', 'running')", (canvas_id,))
    asyncio.run(comments.recover())
    assert comments.get('c1')['agentStatus'] == 'failed'


def test_comment_routes(client):
    canvas_id = client.post('/api/canvases', json={'name': 'C'}).json()['canvasId']
    assert client.get(f'/api/canvases/{canvas_id}/comments').json() == {'comments': []}
    assert client.post('/api/comments/nope/resolve').status_code == 404
    response = client.post(f'/api/canvases/{canvas_id}/comments',
                           json={'anchor': {'kind': 'canvas', 'x': 0, 'y': 0}, 'text': '加一个镜头'})
    assert response.status_code in (201, 200, 503)


# --------------------------------------------------------------- step 2: what the agent gets

import base64
import io
import shutil
import subprocess

from PIL import Image

from app.agent import media
from app.worker import build_request
from tests.test_canvas_tools import add_image_asset


def decode(image):
    return Image.open(io.BytesIO(base64.b64decode(image['data'])))


def test_mark_point_rings_the_spot_and_zooms_in():
    picture = Image.new('RGB', (2000, 1000), (20, 20, 20))
    marked, zoom = media.mark_point(picture, 0.25, 0.5)
    whole = decode(marked)
    assert whole.size == (1024, 512)
    # The ring is red around the point, the picture elsewhere is untouched.
    ring = [whole.getpixel((256 + dx, 256)) for dx in range(-40, 41)]
    assert any(r > 200 and g < 120 for r, g, _ in ring)
    assert whole.getpixel((900, 100))[0] < 60
    close = decode(zoom)
    assert max(close.size) == 768 and close.size[0] > close.size[1]


def test_a_picture_comment_sends_the_marked_spot(repository, tmp_path):
    comments, service, store, canvas_id, factory = setup(repository, [('text', 'ok')])
    add_image(repository, canvas_id, asset=None)
    add_image_asset(repository, canvas_id, 'img', tmp_path / 'p.png', 'p1')

    async def scenario():
        await comments.create(canvas_id, {'kind': 'media', 'nodeId': 'img', 'x': 0.1, 'y': 0.9}, '这块太亮', to_agent=True)
        await settle(service, comments)

    asyncio.run(scenario())
    images = factory.clients[0].prompt_images[0]
    assert [image['caption'] for image in images] == ['留言位置（红圈）：', '红圈处放大：']
    assert all(image['media_type'] == 'image/jpeg' and image['type'] == 'base64' for image in images)
    assert '见附图里的红圈' in factory.clients[0].prompts[0]
    # The panel's copy of the message carries no pictures.
    assert store.list_messages(comments.list(canvas_id)[0]['sessionId'])[0]['content']['text'] == '这块太亮'


def test_missing_file_still_sends_the_text(repository, tmp_path):
    comments, service, _, canvas_id, factory = setup(repository, [('text', 'ok')])
    add_image(repository, canvas_id, asset=None)
    add_image_asset(repository, canvas_id, 'img', tmp_path / 'p.png', 'p1')
    (tmp_path / 'p.png').unlink()

    async def scenario():
        await comments.create(canvas_id, {'kind': 'media', 'nodeId': 'img', 'x': 0.5, 'y': 0.5}, '这里', to_agent=True)
        await settle(service, comments)

    asyncio.run(scenario())
    assert factory.clients[0].prompt_images[0] == []
    assert '位置截图没做出来' in factory.clients[0].prompts[0]


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg not installed')
def test_a_video_comment_sends_the_frame_and_its_neighbours(repository, tmp_path):
    comments, service, _, canvas_id, factory = setup(repository, [('text', 'ok')])
    path = tmp_path / 'clip.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=640x360:rate=10', '-t', '3',
                    '-pix_fmt', 'yuv420p', str(path)], check=True)
    add_image(repository, canvas_id, 'vid', asset=None, node_type='video')
    repository._execute("INSERT INTO assets (id, canvas_id, kind, path, mime_type) VALUES ('v1', ?, 'video', ?, 'video/mp4')",
                        (canvas_id, str(path)))
    repository.update_node(canvas_id, 'vid', {'data': {'assetId': 'v1'}})

    async def scenario():
        await comments.create(canvas_id, {'kind': 'media', 'nodeId': 'vid', 'x': 0.5, 'y': 0.5, 'time': 1.0}, '手抖', to_agent=True)
        await settle(service, comments)

    asyncio.run(scenario())
    captions = [image['caption'] for image in factory.clients[0].prompt_images[0]]
    assert captions[0].startswith('第 1.0 秒的画面') and captions[1] == '红圈处放大：'
    assert captions[2].startswith('前 0.5 秒（第 0.5 秒）') and captions[3].startswith('后 0.5 秒（第 1.5 秒）')
    assert '视频总长 3.0 秒' in factory.clients[0].prompts[0]


def test_redraw_from_a_comment_is_tagged_and_logged(repository, tmp_path):
    comments, service, store, canvas_id, factory = setup(repository)
    add_image(repository, canvas_id, asset=None)
    add_image_asset(repository, canvas_id, 'img', tmp_path / 'p.png', 'p1')
    repository.update_node(canvas_id, 'img', {'data': {'prompt': '窗边的猫'}})
    factory.scripts.append([
        ('tool', 'generate', {'node_ids': ['img'], 'reference_current': True}),
        ('text', '天空换成黄昏了，这是整张重画。'),
    ])
    store.update_settings(store.project_for_canvas(canvas_id), {'permissionMode': 'auto'})

    async def scenario():
        comment = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '天空换成黄昏', to_agent=True)
        await settle(service, comments)
        return comment

    comment = asyncio.run(scenario())
    (job,) = repository.get_snapshot(canvas_id).jobs
    request = __import__('json').loads(repository.get_generation_job(job['id'])['request_json'])
    assert request['commentId'] == comment['id']
    assert request['selfReference']['id'] == 'p1' and request['references'] == []

    # The worker lands the result: a new version tied to the comment, the original kept.
    from app.versions import version_source
    with version_source('generated', job_id=job['id'], comment_id=request['commentId']):
        repository.update_node(canvas_id, 'img', {'data': {'assetId': 'p2'}})
    comments._log(comment['id'])
    comments.resolve(comment['id'])
    assert service.task_log(canvas_id) == ['「图片 img」：天空换成黄昏 → 天空换成黄昏了，这是整张重画（第 2 版），用户已解决']


def test_build_request_puts_the_picture_being_redrawn_first(tmp_path):
    from app.models_registry import registry
    model = registry().for_node('image', None)
    snapshot = {'prompt': 'p', 'parameters': {}, 'references': [{'kind': 'image', 'path': str(tmp_path / 'ref.png')}],
                'selfReference': {'kind': 'image', 'path': str(tmp_path / 'self.png')}}
    request = build_request(model, snapshot)
    assert [path.name for path in request.images] == ['self.png', 'ref.png']


def test_version_tools(repository, tmp_path):
    from tests.test_canvas_tools import setup as tools_setup
    tools, _, canvas_id = tools_setup(repository)
    add_image(repository, canvas_id, asset=None)
    add_image_asset(repository, canvas_id, 'img', tmp_path / 'one.png', 'one')
    Image.new('RGB', (400, 400), (0, 0, 255)).save(tmp_path / 'two.png')
    repository._execute("INSERT INTO assets (id, canvas_id, kind, path, mime_type, width, height) "
                        "VALUES ('two', ?, 'image', ?, 'image/png', 400, 400)", (canvas_id, str(tmp_path / 'two.png')))
    repository.update_node(canvas_id, 'img', {'data': {'assetId': 'two'}})

    listed = tools.get_node_versions('img')
    assert '共 2 版' in listed.text and '第 2 版（当前）' in listed.text
    assert '现在显示第 2 版，共 2 版' in tools.get_node('img').text
    old = tools.view_asset('img', 1)
    assert old.text.startswith('「图片 img」第 1 版的图片') and decode(old.images[0]).getpixel((5, 5))[2] < 100
    assert tools.view_asset('img', 7).is_error
    assert decode(tools.view_asset('img').images[0]).getpixel((5, 5))[2] > 200


def test_undoing_a_comment_round_restores_the_canvas_and_says_so(repository):
    comments, service, store, canvas_id, _ = setup(
        repository, [('tool', 'create_nodes', {'nodes': [{'type': 'note', 'content': '分镜'}]}), ('text', '加了一个便签。')])

    async def scenario():
        comment = await comments.create(canvas_id, {'kind': 'canvas', 'x': 0, 'y': 0}, '加个便签写分镜', to_agent=True)
        await settle(service, comments)
        assert len(repository.get_snapshot(canvas_id).nodes) == 1
        run_id = store.list_messages(comment['sessionId'])[0]['run_id']
        service.undo(run_id)
        return comment

    comment = asyncio.run(scenario())
    assert repository.get_snapshot(canvas_id).nodes == []
    undone = comments.get(comment['id'])
    assert undone['agentStatus'] == 'done' and undone['outcome'].startswith('已撤销')
    assert service.task_log(canvas_id) == ['画布：加个便签写分镜 → 已撤销这一轮的改动，画布回到了留言前的样子，等用户查看']


# --------------------------------------------------------------- plain comments (2026-10-09)

def test_a_plain_comment_is_just_a_thread(repository):
    comments, service, store, canvas_id, factory = setup(repository)
    add_image(repository, canvas_id)

    async def scenario():
        updates = comments.subscribe(canvas_id)
        comment = await comments.create(canvas_id, {'kind': 'media', 'nodeId': 'img', 'x': 0.2, 'y': 0.4}, '这里光线有点冷')
        assert (comment['status'], comment['agentStatus'], comment['sessionId']) == ('open', None, None)
        await comments.reply(comment['id'], '回头统一调成暖色')
        resolved = comments.resolve(comment['id'])
        reopened = comments.reopen(comment['id'])
        seen = []
        while not updates.empty():
            seen.append(updates.get_nowait())
        return comment, resolved, reopened, seen

    comment, resolved, reopened, seen = asyncio.run(scenario())
    assert resolved['status'] == 'resolved' and reopened['status'] == 'open'
    assert [r['text'] for r in reopened['replies']] == ['回头统一调成暖色']
    assert len(seen) == 4 and all(update['id'] == comment['id'] for update in seen)
    assert factory.clients == [] and not [s for s in store.list_sessions('default', canvas_id) if s['kind'] == 'comment']
    assert service.task_log(canvas_id) == []  # plain comments are not agent tasks
    assert [c['id'] for c in comments.list(canvas_id, kind='note')] == [comment['id']]
    assert comments.list(canvas_id, kind='agent') == []


def test_at_agent_hands_it_over(repository):
    comments, service, _, canvas_id, factory = setup(repository, [('text', '好')], [('text', '好')])
    add_image(repository, canvas_id)

    async def scenario():
        first = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '@Agent 把背景换成黄昏')
        await settle(service, comments)
        plain = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '发邮件给 agentur@x.com')
        return comments.get(first['id']), plain

    first, plain = asyncio.run(scenario())
    assert first['agentStatus'] == 'done' and factory.clients[0].prompts[0].endswith('@Agent 把背景换成黄昏')
    assert plain['agentStatus'] is None  # "agentur" is not a mention


def test_handing_off_later_sends_the_thread_with_its_location(repository):
    comments, service, store, canvas_id, factory = setup(repository, [('text', '改成暖色了。')])
    add_image(repository, canvas_id)

    async def scenario():
        comment = await comments.create(canvas_id, {'kind': 'media', 'nodeId': 'img', 'x': 0.5, 'y': 0.5}, '光线有点冷')
        await comments.reply(comment['id'], '再加点晨雾')
        handed = await comments.hand_off(comment['id'])
        assert handed['agentStatus'] == 'running' and handed['sessionId']
        await settle(service, comments)
        return comments.get(comment['id'])

    done = asyncio.run(scenario())
    prompt = factory.clients[0].prompts[0]
    assert '[留言位置] 图片节点「图片 img」[img] 第 1 版' in prompt
    assert prompt.endswith('（按时间顺序，最后一条最新）：\n- 光线有点冷\n- 再加点晨雾')
    assert store.get_session(done['sessionId'])['kind'] == 'comment'
    assert done['agentStatus'] == 'done' and done['status'] == 'open'
    assert [c['id'] for c in comments.list(canvas_id, kind='agent')] == [done['id']]
    with pytest.raises(DomainError):
        asyncio.run(comments.hand_off('nope'))


def test_delete_removes_the_thread_and_archives_its_chat(repository):
    comments, service, store, canvas_id, _ = setup(repository, [('pause', 0.1), ('text', 'ok')])
    add_image(repository, canvas_id)

    async def scenario():
        updates = comments.subscribe(canvas_id)
        plain = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '备注')
        await comments.reply(plain['id'], '再补一句')
        comments.delete(plain['id'])
        task = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '改', to_agent=True)
        with pytest.raises(DomainError) as busy:
            comments.delete(task['id'])
        assert busy.value.code == 'COMMENT_BUSY'
        await settle(service, comments)
        comments.delete(task['id'])
        removed = []
        while not updates.empty():
            update = updates.get_nowait()
            if update.get('deleted'):
                removed.append(update['id'])
        return plain, task, removed

    plain, task, removed = asyncio.run(scenario())
    assert removed == [plain['id'], task['id']] and comments.list(canvas_id) == []
    assert store.get_session(task['sessionId'])['archived_at'] is not None
    with repository.database.connection() as connection:
        assert connection.execute('SELECT COUNT(*) FROM comment_replies').fetchone()[0] == 0


def test_the_agent_sees_open_notes_as_reference(repository):
    from tests.test_canvas_tools import setup as tools_setup
    tools, _, canvas_id = tools_setup(repository)
    comments = CommentService(make_service(repository, FakeFactory())[0])
    add_image(repository, canvas_id)

    async def scenario():
        note = await comments.create(canvas_id, {'kind': 'media', 'nodeId': 'img', 'x': 0.25, 'y': 0.5}, '这里光线有点冷')
        await comments.reply(note['id'], '整体暖一点')
        await comments.create(canvas_id, {'kind': 'canvas', 'x': 100, 'y': 40}, '这里放第二场')
        done = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '已经处理的')
        comments.resolve(done['id'])

    asyncio.run(scenario())
    node = tools.get_node('img').text
    assert '用户备注（1 条未解决）' in node and '不要因为看到备注就主动去改' in node
    assert '- 画面 (25%, 50%)：「这里光线有点冷」（1 条回复，最新：「整体暖一点」）' in node
    assert '已经处理的' not in node
    canvas = tools.get_canvas().text
    assert '用户备注 1 条' in canvas and '[画布空白处的用户备注]' in canvas and '- 画布 (100, 40)：「这里放第二场」' in canvas


def test_old_comment_tables_are_migrated(tmp_path):
    import sqlite3
    from app.db import Database
    path = tmp_path / 'old.sqlite3'
    connection = sqlite3.connect(path)
    connection.execute('''CREATE TABLE canvas_comments (id TEXT PRIMARY KEY, canvas_id TEXT NOT NULL, session_id TEXT NOT NULL,
        anchor_kind TEXT NOT NULL, node_id TEXT, version INTEGER, x REAL, y REAL, time REAL, text TEXT NOT NULL,
        status TEXT NOT NULL, outcome TEXT, pending_text TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, resolved_at TEXT)''')
    connection.executemany(
        "INSERT INTO canvas_comments (id, canvas_id, session_id, anchor_kind, text, status, pending_text) VALUES (?, 'c', 's', 'node', ?, ?, ?)",
        [('a', '一', 'done', None), ('b', '二', 'resolved', None), ('q', '三', 'queued', '三')])
    connection.commit()
    connection.close()
    database = Database(path)
    database.init_schema()
    database.init_schema()  # running again changes nothing
    with database.connection() as connection:
        rows = {row['id']: dict(row) for row in connection.execute('SELECT * FROM canvas_comments')}
    assert (rows['a']['status'], rows['a']['agent_status'], rows['a']['text_seen_by_agent']) == ('open', 'done', 1)
    assert (rows['b']['status'], rows['b']['agent_status']) == ('resolved', 'done')
    assert (rows['q']['status'], rows['q']['agent_status'], rows['q']['text_seen_by_agent']) == ('open', 'queued', 0)


def test_plain_and_agent_comment_routes(client):
    canvas_id = client.post('/api/canvases', json={'name': 'C'}).json()['canvasId']
    created = client.post(f'/api/canvases/{canvas_id}/comments',
                          json={'anchor': {'kind': 'canvas', 'x': 0, 'y': 0}, 'text': '这里放第二场'})
    assert created.status_code == 200 and created.json()['agentStatus'] is None
    comment_id = created.json()['id']
    replied = client.post(f'/api/comments/{comment_id}/reply', json={'text': '要夜景'}).json()
    assert [r['text'] for r in replied['replies']] == ['要夜景']
    assert client.get(f'/api/canvases/{canvas_id}/comments?kind=note').json()['comments'][0]['id'] == comment_id
    assert client.get(f'/api/canvases/{canvas_id}/comments?kind=agent').json() == {'comments': []}
    assert client.delete(f'/api/comments/{comment_id}').status_code == 204
    assert client.get(f'/api/comments/{comment_id}').status_code == 404
