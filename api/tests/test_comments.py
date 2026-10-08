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
            canvas_id, {'kind': 'media', 'nodeId': 'img', 'x': 0.62, 'y': 0.3}, '这里的天空换成黄昏')
        assert comment['status'] == 'running'
        await settle(service, comments)
        return comment

    comment = asyncio.run(scenario())
    assert comment['anchor'] == {'kind': 'media', 'nodeId': 'img', 'version': 1, 'x': 0.62, 'y': 0.3, 'time': None}
    prompt = factory.clients[0].prompts[0]
    assert '[留言位置] 图片节点「图片 img」[img] 第 1 版，画面内 (62%, 30%) 处' in prompt
    assert prompt.endswith('这里的天空换成黄昏')
    session = store.get_session(comment['sessionId'])
    assert session['kind'] == 'comment' and session['title'] == '这里的天空换成黄昏'
    # The panel shows the words only, not the location block.
    first = store.list_messages(comment['sessionId'])[0]['content']
    assert first['text'] == '这里的天空换成黄昏' and first['focus'] == ['img']
    done = comments.get(comment['id'])
    assert (done['status'], done['outcome']) == ('done', '把天空改成黄昏了。')


def test_queue_runs_two_at_a_time_and_one_per_node(repository):
    slow = [('pause', 0.15), ('text', 'ok')]
    comments, service, _, canvas_id, _ = setup(repository, slow, slow, slow, slow)
    add_image(repository, canvas_id, 'a')
    add_image(repository, canvas_id, 'b')

    async def scenario():
        first = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'a'}, '一')
        same_node = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'a'}, '二')
        other = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'b'}, '三')
        blank = await comments.create(canvas_id, {'kind': 'canvas', 'x': 10, 'y': 20}, '四')
        started = [comments.get(c['id'])['status'] for c in (first, same_node, other, blank)]
        await settle(service, comments, until=lambda: all(
            comments.get(c['id'])['status'] == 'done' for c in (first, same_node, other, blank)))
        return started

    # "二" waits for "一" (same node) even though a slot is free; "四" waits for a slot.
    assert asyncio.run(scenario()) == ['running', 'queued', 'running', 'queued']


def test_confirmation_shows_as_waiting(repository):
    comments, service, _, canvas_id, _ = setup(
        repository, [('tool', 'generate', {'node_ids': ['img']}), ('text', '生成好了')])
    add_image(repository, canvas_id)

    async def scenario():
        updates = comments.subscribe(canvas_id)
        comment = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '重画一张')
        session_queue = service.subscribe(comment['sessionId'])
        while True:
            event = await asyncio.wait_for(session_queue.get(), 5)
            if event['kind'] == 'confirm_request':
                service.confirm(event['requestId'], True)
                break
        await settle(service, comments)
        statuses = []
        while not updates.empty():
            status = updates.get_nowait()['status']
            if not statuses or statuses[-1] != status:
                statuses.append(status)
        return statuses

    assert asyncio.run(scenario()) == ['queued', 'running', 'waiting', 'running', 'done']


def test_reply_resolve_and_reopen(repository):
    comments, service, _, canvas_id, factory = setup(
        repository, [('pause', 0.1), ('text', '改好了')], [('text', '又改了一下')])
    add_image(repository, canvas_id)

    async def scenario():
        comment = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '暗一点')
        with pytest.raises(DomainError) as busy:
            await comments.reply(comment['id'], '再暗一点')
        assert busy.value.code == 'COMMENT_BUSY'
        with pytest.raises(DomainError):
            comments.resolve(comment['id'])
        await settle(service, comments)
        assert comments.resolve(comment['id'])['status'] == 'resolved'
        assert comments.list(canvas_id, 'open') == []
        assert comments.reopen(comment['id'])['status'] == 'done'
        comments.resolve(comment['id'])
        # Replying to a resolved comment brings it back and continues the same chat.
        replied = await comments.reply(comment['id'], '再暗一点')
        assert replied['status'] == 'running' and replied['resolvedAt'] is None
        await settle(service, comments)
        return comments.get(comment['id'])

    final = asyncio.run(scenario())
    assert (final['status'], final['outcome']) == ('done', '又改了一下')
    second_prompt = factory.clients[0].prompts[1]
    assert '[留言位置]' not in second_prompt and second_prompt.endswith('再暗一点')


def test_anchor_validation(repository):
    comments, _, _, canvas_id, _ = setup(repository)
    add_image(repository, canvas_id)
    add_image(repository, canvas_id, 'empty', asset=None)
    add_image(repository, canvas_id, 'vid', asset='v1', node_type='video')
    add_image(repository, canvas_id, 'note', asset=None, node_type='note')

    async def attempt(anchor):
        with pytest.raises(DomainError) as error:
            await comments.create(canvas_id, anchor, '看这里')
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
            canvas_id, {'kind': 'media', 'nodeId': 'vid', 'x': 0.5, 'y': 0.25, 'time': 3.24}, '这里手抖了')
        await settle(service, comments)
        return comment

    assert asyncio.run(scenario())['anchor']['time'] == 3.24
    assert '视频节点「图片 vid」[vid] 第 1 版，第 3.2 秒那一帧，画面内 (50%, 25%) 处' in factory.clients[0].prompts[0]


def test_queued_comment_on_a_deleted_node_fails(repository):
    comments, service, _, canvas_id, _ = setup(repository, [('pause', 0.1), ('text', 'ok')])
    add_image(repository, canvas_id)

    async def scenario():
        await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '一')
        waiting = await comments.create(canvas_id, {'kind': 'node', 'nodeId': 'img'}, '二')
        repository.delete_node(canvas_id, 'img')
        await settle(service, comments, until=lambda: comments.get(waiting['id'])['status'] == 'failed')
        return comments.get(waiting['id'])

    failed = asyncio.run(scenario())
    assert failed['nodeMissing'] and '删除' in failed['outcome']


def test_needs_a_configured_agent_and_stays_out_of_other_chats(repository):
    comments, service, store, canvas_id, factory = setup(
        repository, config=AgentConfig(api_key_present=False))

    async def unconfigured():
        with pytest.raises(DomainError) as error:
            await comments.create(canvas_id, {'kind': 'canvas', 'x': 0, 'y': 0}, '加一个镜头')
        return error.value.code

    assert asyncio.run(unconfigured()) == 'AGENT_NOT_CONFIGURED'
    assert comments.list(canvas_id) == []

    comments, service, store, canvas_id, factory = setup(repository, [('text', '加好了')], [('text', 'hi')])

    async def scenario():
        await comments.create(canvas_id, {'kind': 'canvas', 'x': 0, 'y': 0}, '加一个镜头')
        await settle(service, comments)
        chat = store.create_session(canvas_id)
        await service.send_message(chat['id'], '你好')
        await settle(service, comments)

    asyncio.run(scenario())
    assert '加一个镜头' not in factory.clients[-1].prompts[0]


def test_restart_marks_interrupted_runs_failed(repository):
    comments, service, _, canvas_id, _ = setup(repository)
    add_image(repository, canvas_id)
    with repository.transaction() as connection:
        connection.execute(
            "INSERT INTO canvas_comments (id, canvas_id, session_id, anchor_kind, node_id, text, status) "
            "VALUES ('c1', ?, 's', 'node', 'img', '一', 'running')", (canvas_id,))
    asyncio.run(comments.recover())
    assert comments.get('c1')['status'] == 'failed'


def test_comment_routes(client):
    canvas_id = client.post('/api/canvases', json={'name': 'C'}).json()['canvasId']
    assert client.get(f'/api/canvases/{canvas_id}/comments').json() == {'comments': []}
    assert client.post('/api/comments/nope/resolve').status_code == 404
    response = client.post(f'/api/canvases/{canvas_id}/comments',
                           json={'anchor': {'kind': 'canvas', 'x': 0, 'y': 0}, 'text': '加一个镜头'})
    assert response.status_code in (201, 200, 503)
