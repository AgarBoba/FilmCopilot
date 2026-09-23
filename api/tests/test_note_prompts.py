import json

from app.commands import CanvasCommandService, compose_prompt
from app.events import EventStore
from app.repositories import CanvasRepository
from app.schemas import CommandEnvelope


def run(service, canvas_id, repository, command, payload, key):
    revision = repository.get_snapshot(canvas_id).revision
    return service.execute(
        canvas_id,
        CommandEnvelope(command=command, baseRevision=revision, idempotencyKey=key, payload=payload),
    ).payload


def test_compose_prompt_puts_notes_first_and_skips_blanks():
    assert compose_prompt(['  温暖的午后光线 ', '', '胶片质感'], '兔子吃胡萝卜') == '温暖的午后光线\n\n胶片质感\n\n兔子吃胡萝卜'
    assert compose_prompt(['只有便签'], '   ') == '只有便签'
    assert compose_prompt([], '只有自己') == '只有自己'


def test_connected_note_text_is_sent_as_prompt(repository: CanvasRepository):
    canvas = repository.create_canvas('Notes')
    service = CanvasCommandService(repository, EventStore(repository.database))
    cid = canvas.canvasId
    note = run(service, cid, repository, 'create_node', {'nodeType': 'note', 'data': {'title': '风格', 'content': '温暖的午后光线'}}, 'n')['nodeId']
    empty = run(service, cid, repository, 'create_node', {'nodeType': 'note', 'data': {'content': '  '}}, 'e')['nodeId']
    image = run(service, cid, repository, 'create_node', {'nodeType': 'image'}, 'i')['nodeId']
    run(service, cid, repository, 'connect_nodes', {'edgeId': 'e1', 'sourceNodeId': note, 'targetNodeId': image}, 'c1')
    run(service, cid, repository, 'connect_nodes', {'edgeId': 'e2', 'sourceNodeId': empty, 'targetNodeId': image}, 'c2')

    job_id = run(service, cid, repository, 'start_generation', {'targetNodeId': image, 'prompt': '兔子吃胡萝卜'}, 'g')['jobId']

    snapshot = json.loads(repository.get_generation_job(job_id)['request_json'])
    assert snapshot['prompt'] == '温暖的午后光线\n\n兔子吃胡萝卜'
    assert snapshot['nodePrompt'] == '兔子吃胡萝卜'
    assert [note['title'] for note in snapshot['notePrompts']] == ['风格']
    assert snapshot['references'] == []



def attach_result(repository, cid, node_id, job_id, asset_id):
    repository._execute(
        "INSERT INTO assets (id, canvas_id, kind, path, mime_type) VALUES (?, ?, 'image', 'x', 'image/png')",
        (asset_id, cid),
    )
    repository._execute(
        "UPDATE generation_jobs SET status = 'completed', output_asset_id = ? WHERE id = ?", (asset_id, job_id)
    )
    repository.update_node(cid, node_id, {'data': {'assetId': asset_id}})


def test_upstream_changes_are_reported_after_the_result(repository: CanvasRepository):
    canvas = repository.create_canvas('Upstream')
    service = CanvasCommandService(repository, EventStore(repository.database))
    cid = canvas.canvasId
    note = run(service, cid, repository, 'create_node', {'nodeType': 'note', 'title': '风格', 'data': {'content': '午后光线'}}, 'n')['nodeId']
    ref = run(service, cid, repository, 'create_node', {'nodeType': 'image', 'title': '参考图'}, 'r')['nodeId']
    image = run(service, cid, repository, 'create_node', {'nodeType': 'image', 'data': {'prompt': '兔子'}}, 'i')['nodeId']
    attach_result(repository, cid, ref, run(service, cid, repository, 'start_generation', {'targetNodeId': ref}, 'g0')['jobId'], 'ref-v1')
    run(service, cid, repository, 'connect_nodes', {'sourceNodeId': note, 'targetNodeId': image}, 'c1')
    run(service, cid, repository, 'connect_nodes', {'sourceNodeId': ref, 'targetNodeId': image}, 'c2')
    job = run(service, cid, repository, 'start_generation', {'targetNodeId': image}, 'g1')['jobId']
    attach_result(repository, cid, image, job, 'out-1')
    assert image not in repository.get_snapshot(cid).upstreamChanges

    # Editing the node's own prompt is not an upstream change.
    run(service, cid, repository, 'update_node', {'nodeId': image, 'data': {'prompt': '猫'}}, 'u0')
    assert image not in repository.get_snapshot(cid).upstreamChanges

    run(service, cid, repository, 'update_node', {'nodeId': note, 'data': {'content': '夜景霓虹'}}, 'u1')
    repository.update_node(cid, ref, {'data': {'assetId': 'ref-v2'}})
    repository._execute("INSERT INTO assets (id, canvas_id, kind, path, mime_type) VALUES ('ref-v2', ?, 'image', 'x', 'image/png')", (cid,))
    assert repository.get_snapshot(cid).upstreamChanges[image] == ['「风格」的文字改了', '「参考图」的内容更新了']


def test_results_attach_even_if_the_node_changed(repository: CanvasRepository):
    from app.worker import Worker
    canvas = repository.create_canvas('Attach')
    service = CanvasCommandService(repository, EventStore(repository.database))
    cid = canvas.canvasId
    image = run(service, cid, repository, 'create_node', {'nodeType': 'image', 'data': {'prompt': '兔子'}}, 'i')['nodeId']
    job_id = run(service, cid, repository, 'start_generation', {'targetNodeId': image}, 'g')['jobId']
    run(service, cid, repository, 'update_node', {'nodeId': image, 'data': {'prompt': '改了'}}, 'u')
    worker = Worker(repository, provider=None, data_dir=None)
    job = repository.get_generation_job(job_id)
    assert worker._target_exists(job) is True
    run(service, cid, repository, 'delete_elements', {'nodeIds': [image]}, 'd')
    assert worker._target_exists(job) is False
