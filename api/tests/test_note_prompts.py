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


def test_unchanged_node_still_accepts_its_generation_result(repository: CanvasRepository):
    """Regression: composing note text into the prompt made every result 'completed_unattached'."""
    from app.worker import Worker
    canvas = repository.create_canvas('Attach')
    service = CanvasCommandService(repository, EventStore(repository.database))
    cid = canvas.canvasId
    note = run(service, cid, repository, 'create_node', {'nodeType': 'note', 'data': {'content': '午后光线'}}, 'n')['nodeId']
    image = run(service, cid, repository, 'create_node', {'nodeType': 'image', 'data': {'prompt': '兔子'}}, 'i')['nodeId']
    run(service, cid, repository, 'connect_nodes', {'sourceNodeId': note, 'targetNodeId': image}, 'c')
    for key, payload in (('g1', {'targetNodeId': image}), ('g2', {'targetNodeId': image, 'prompt': '兔子'})):
        job_id = run(service, cid, repository, 'start_generation', payload, key)['jobId']
        job = repository.get_generation_job(job_id)
        worker = Worker(repository, provider=None, data_dir=None)
        assert worker._can_attach(job, json.loads(job['request_json'])) is True

    run(service, cid, repository, 'update_node', {'nodeId': image, 'data': {'prompt': '改了'}}, 'u')
    assert worker._can_attach(job, json.loads(job['request_json'])) is False
