from app.commands import CanvasCommandService
from app.domain import DomainError
from app.events import EventStore
from app.repositories import CanvasRepository
from app.schemas import CommandEnvelope

import pytest


def run(service, canvas_id, repository, command, payload, key):
    revision = repository.get_snapshot(canvas_id).revision
    return service.execute(
        canvas_id,
        CommandEnvelope(command=command, baseRevision=revision, idempotencyKey=key, payload=payload),
    ).payload


def setup(repository: CanvasRepository):
    canvas = repository.create_canvas('Dup')
    service = CanvasCommandService(repository, EventStore(repository.database))
    cid = canvas.canvasId
    ref = run(service, cid, repository, 'create_node', {'nodeType': 'image', 'title': '参考'}, 'r')['nodeId']
    note = run(service, cid, repository, 'create_node', {'nodeType': 'note', 'data': {'content': '午后光线'}}, 'n')['nodeId']
    image = run(service, cid, repository, 'create_node', {
        'nodeType': 'image', 'title': '胡萝卜尝试', 'x': 100, 'y': 50,
        'data': {'prompt': '兔子吃胡萝卜', 'assetId': 'asset-1', 'parameters': {'size': '1K'}},
    }, 'i')['nodeId']
    video = run(service, cid, repository, 'create_node', {'nodeType': 'video', 'title': '视频 1'}, 'v')['nodeId']
    for key, (source, target) in enumerate([(ref, image), (note, image), (image, video)]):
        run(service, cid, repository, 'connect_nodes', {'sourceNodeId': source, 'targetNodeId': target}, f'c{key}')
    return service, cid, ref, note, image, video


def test_duplicate_copies_content_and_inputs_but_not_outputs(repository: CanvasRepository):
    service, cid, ref, note, image, video = setup(repository)

    result = run(service, cid, repository, 'duplicate_nodes', {'nodes': [{'sourceNodeId': image, 'x': 500, 'y': 60}]}, 'd')

    copy_id = result['nodes'][0]['nodeId']
    snapshot = repository.get_snapshot(cid)
    copy = next(node for node in snapshot.nodes if node.id == copy_id)
    assert (copy.x, copy.y) == (500, 60)
    assert copy.data['title'] == '胡萝卜尝试 副本'
    assert copy.data['prompt'] == '兔子吃胡萝卜'
    assert copy.data['assetId'] == 'asset-1'
    edges = {(edge.source, edge.target) for edge in snapshot.edges}
    assert (ref, copy_id) in edges and (note, copy_id) in edges
    assert (copy_id, video) not in edges  # outputs are not copied


def test_duplicating_a_connected_pair_rewires_the_internal_edge(repository: CanvasRepository):
    service, cid, ref, note, image, video = setup(repository)

    result = run(service, cid, repository, 'duplicate_nodes', {'nodes': [
        {'sourceNodeId': image, 'x': 0, 'y': 400},
        {'sourceNodeId': video, 'x': 400, 'y': 400},
    ]}, 'd')

    new = {item['sourceNodeId']: item['nodeId'] for item in result['nodes']}
    edges = {(edge.source, edge.target) for edge in repository.get_snapshot(cid).edges}
    assert (new[image], new[video]) in edges
    assert (image, new[video]) not in edges


def test_duplicate_rejects_bad_payloads(repository: CanvasRepository):
    service, cid, *_ = setup(repository)
    with pytest.raises(DomainError):
        run(service, cid, repository, 'duplicate_nodes', {'nodes': []}, 'x')
    with pytest.raises(DomainError):
        run(service, cid, repository, 'duplicate_nodes', {'nodes': [{'sourceNodeId': 'missing'}]}, 'y')
