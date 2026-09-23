import asyncio

from PIL import Image

from app.agent.canvas_tools import CanvasTools
from app.agent.config import AgentConfig
from app.agent.store import AgentStore
from app.commands import CanvasCommandService
from app.events import EventStore
from app.repositories import CanvasRepository
from app.schemas import CommandEnvelope


def setup(repository: CanvasRepository, tmp_path=None):
    canvas_id = repository.create_canvas('Tools').canvasId
    store = AgentStore(repository.database)
    run_id = store.create_run(store.create_session(canvas_id)['id'], 'auto')['id']
    service = CanvasCommandService(repository, EventStore(repository.database))
    tools = CanvasTools(repository, service, store, canvas_id, run_id, AgentConfig(poll_seconds=0.01))
    return tools, service, canvas_id


def user(service, repository, canvas_id, command, payload, key):
    revision = repository.get_snapshot(canvas_id).revision
    return service.execute(canvas_id, CommandEnvelope(
        command=command, baseRevision=revision, idempotencyKey=key, payload=payload,
    )).payload


def add_image_asset(repository, canvas_id, node_id, path, asset_id='asset-1'):
    Image.new('RGB', (2000, 1000), (236, 120, 40)).save(path)
    repository._execute(
        "INSERT INTO assets (id, canvas_id, kind, path, mime_type, width, height) "
        "VALUES (?, ?, 'image', ?, 'image/png', 2000, 1000)",
        (asset_id, canvas_id, str(path)),
    )
    repository.update_node(canvas_id, node_id, {'data': {'assetId': asset_id}})


def test_create_nodes_names_positions_and_marks_agent(repository):
    tools, _, canvas_id = setup(repository)
    result = tools.create_nodes([
        {'type': 'note', 'content': '温暖的午后光线'},
        {'type': 'image', 'prompt': '兔子吃胡萝卜', 'parameters': {'aspectRatio': '16:9'}},
    ])
    assert not result.is_error and len(result.touched) == 2
    nodes = {node.id: node for node in repository.get_snapshot(canvas_id).nodes}
    note, image = (nodes[i] for i in result.touched)
    assert note.data['title'] == '便签 1' and note.data['content'] == '温暖的午后光线'
    assert image.data['parameters']['aspectRatio'] == '16:9' and image.data['parameters']['size'] == '2K'
    assert image.y > note.y  # stacked, not on top of each other
    assert repository.agent_run_changes(tools.run_id)  # recorded for undo


def test_invalid_parameters_are_explained(repository):
    tools, _, _ = setup(repository)
    result = tools.create_nodes([{'type': 'image', 'parameters': {'aspectRatio': '21:9'}}])
    assert result.is_error and 'aspectRatio 只能是' in result.text
    result = tools.create_nodes([{'type': 'video', 'parameters': {'generateAudio': 1}}])
    assert result.is_error


def test_connection_errors_are_readable(repository):
    tools, _, _ = setup(repository)
    video, image = tools.create_nodes([{'type': 'video'}, {'type': 'image'}]).touched
    result = tools.connect(video, image)
    assert result.is_error and '不能这样连' in result.text


def test_conflict_rereads_and_reports_user_changes(repository):
    tools, service, canvas_id = setup(repository)
    (node,) = tools.create_nodes([{'type': 'image', 'prompt': 'agent'}]).touched
    user(service, repository, canvas_id, 'update_node', {'nodeId': node, 'data': {'prompt': '我改的'}}, 'u1')

    result = tools.update_node(node, {'prompt': 'agent 覆盖'})

    assert result.is_error and '用户刚刚修改了' in result.text and node in result.text
    assert repository.node_snapshot(canvas_id, node)['data']['prompt'] == '我改的'  # not overwritten
    # After reporting, the tool has caught up; a deliberate retry now works.
    assert not tools.update_node(node, {'prompt': 'agent 看过之后再改'}).is_error


def test_busy_nodes_cannot_be_changed_or_regenerated(repository):
    tools, _, _ = setup(repository)
    (node,) = tools.create_nodes([{'type': 'image', 'prompt': '兔子'}]).touched
    assert not tools.generate([node]).is_error
    for result in (tools.update_node(node, {'prompt': 'x'}), tools.generate([node])):
        assert result.is_error and '正在生成' in result.text


def test_generate_needs_a_prompt_or_note(repository):
    tools, _, _ = setup(repository)
    image, note = tools.create_nodes([{'type': 'image'}, {'type': 'note', 'content': '夜景'}]).touched
    assert '没有 Prompt' in tools.generate([image]).text
    tools.connect(note, image)
    assert not tools.generate([image]).is_error
    assert AgentStore(repository.database).get_run(tools.run_id)['generation_count'] == 1


def test_stop_prevents_further_commands(repository):
    tools, _, canvas_id = setup(repository)
    tools.create_nodes([{'type': 'note'}])
    tools.stopped = True
    result = tools.create_nodes([{'type': 'note'}])
    assert result.is_error and '已停止' in result.text
    assert len(repository.get_snapshot(canvas_id).nodes) == 1


def test_get_canvas_is_compact_and_can_focus(repository):
    tools, _, _ = setup(repository)
    a, b, c = tools.create_nodes([
        {'type': 'note', 'content': '长' * 200}, {'type': 'image'}, {'type': 'image', 'title': '无关'},
    ]).touched
    tools.connect(a, b)
    full = tools.get_canvas().text
    assert '…' in full and '无关' in full
    focused = tools.get_canvas([b]).text
    assert a in focused and '无关' not in focused


def test_view_asset_downscales_images(repository, tmp_path):
    tools, _, canvas_id = setup(repository)
    (node,) = tools.create_nodes([{'type': 'image'}]).touched
    assert tools.view_asset(node).is_error  # no content yet
    add_image_asset(repository, canvas_id, node, tmp_path / 'big.png')
    result = tools.view_asset(node)
    assert not result.is_error and len(result.images) == 1
    import base64, io
    image = Image.open(io.BytesIO(base64.b64decode(result.images[0]['data'])))
    assert max(image.size) == 1024


def test_wait_for_generation_returns_the_result_image(repository, tmp_path):
    tools, _, canvas_id = setup(repository)
    (node,) = tools.create_nodes([{'type': 'image', 'prompt': '兔子'}]).touched
    tools.generate([node])
    job = repository.get_snapshot(canvas_id).jobs[-1]

    async def worker_finishes():
        await asyncio.sleep(0.05)
        add_image_asset(repository, canvas_id, node, tmp_path / 'out.png', 'out')
        repository._execute(
            "UPDATE generation_jobs SET status = 'completed', output_asset_id = 'out' WHERE id = ?", (job['id'],)
        )

    async def scenario():
        result, _ = await asyncio.gather(tools.wait_for_generation([node], timeout_seconds=5), worker_finishes())
        return result

    result = asyncio.run(scenario())
    assert '已完成' in result.text and len(result.images) == 1


def test_wait_reports_failures(repository):
    tools, _, canvas_id = setup(repository)
    (node,) = tools.create_nodes([{'type': 'image', 'prompt': '兔子'}]).touched
    tools.generate([node])
    job = repository.get_snapshot(canvas_id).jobs[-1]
    repository._execute("UPDATE generation_jobs SET status='failed', error='422 bad input' WHERE id=?", (job['id'],))
    result = asyncio.run(tools.wait_for_generation([node], timeout_seconds=1))
    assert '生成失败：422 bad input' in result.text


def test_retrying_the_same_step_is_idempotent(repository):
    tools, _, canvas_id = setup(repository)
    tools.create_nodes([{'type': 'note'}])
    # Same idempotency key replayed (e.g. SDK retry): no second node.
    step = AgentStore(repository.database).get_run(tools.run_id)['step_count']
    envelope = CommandEnvelope(
        command='create_node', baseRevision=0, idempotencyKey=f'agent:{tools.run_id}:{step}',
        payload={'nodeType': 'note'}, actor='agent', agentRunId=tools.run_id,
    )
    tools.service.execute(canvas_id, envelope)
    assert len(repository.get_snapshot(canvas_id).nodes) == 1
