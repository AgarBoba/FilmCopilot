import json

from app.versions import NodeVersions, version_source
from tests.test_commands import create_canvas, create_node


def command(client, canvas_id, name, payload, key):
    revision = client.get(f'/api/canvases/{canvas_id}/snapshot').json()['revision']
    return client.post(f'/api/canvases/{canvas_id}/commands', json={
        'command': name, 'baseRevision': revision, 'idempotencyKey': key, 'payload': payload,
    })


def versions(client, canvas_id, node_id):
    response = client.get(f'/api/canvases/{canvas_id}/nodes/{node_id}/versions')
    assert response.status_code == 200
    return response.json()


def test_every_new_asset_is_a_new_version_and_restoring_adds_one(client):
    canvas_id = create_canvas(client)
    node_id = create_node(client, canvas_id, 'image', 'n1')
    assert versions(client, canvas_id, node_id) == {'versions': [], 'current': None}

    command(client, canvas_id, 'attach_asset', {'nodeId': node_id, 'assetId': 'a1'}, 'k1')
    command(client, canvas_id, 'attach_asset', {'nodeId': node_id, 'assetId': 'a2'}, 'k2')
    # Writes that don't change the asset add nothing.
    command(client, canvas_id, 'update_node', {'nodeId': node_id, 'data': {'title': '兔子'}}, 'k3')
    listed = versions(client, canvas_id, node_id)
    assert [(v['version'], v['assetId'], v['source']) for v in listed['versions']] == [
        (1, 'a1', 'uploaded'), (2, 'a2', 'uploaded')]
    assert listed['current'] == 'a2'

    response = command(client, canvas_id, 'restore_version', {'nodeId': node_id, 'version': 1}, 'k4')
    assert response.status_code == 200, response.text
    listed = versions(client, canvas_id, node_id)
    assert [(v['version'], v['assetId'], v['source']) for v in listed['versions']][-1] == (3, 'a1', 'restored')
    assert listed['current'] == 'a1'

    missing = command(client, canvas_id, 'restore_version', {'nodeId': node_id, 'version': 9}, 'k5')
    assert missing.status_code == 404


def test_duplicates_start_their_own_history(client):
    canvas_id = create_canvas(client)
    node_id = create_node(client, canvas_id, 'image', 'n1')
    command(client, canvas_id, 'attach_asset', {'nodeId': node_id, 'assetId': 'a1'}, 'k1')
    copy = command(client, canvas_id, 'duplicate_nodes', {'nodes': [{'sourceNodeId': node_id}]}, 'k2')
    copy_id = copy.json()['payload']['nodes'][0]['nodeId']
    (only,) = versions(client, canvas_id, copy_id)['versions']
    assert (only['assetId'], only['source']) == ('a1', 'copied')


def test_generated_versions_carry_prompt_and_old_nodes_are_backfilled(repository):
    canvas_id = repository.create_canvas('V').canvasId
    repository.insert_node(canvas_id, 'n', 'image', 0, 0, 300, 260, {'title': 'x'})
    with repository.transaction() as connection:
        for index, asset in enumerate(('g1', 'g2')):
            connection.execute(
                "INSERT INTO generation_jobs (id, canvas_id, target_node_id, status, provider, request_json, "
                "input_snapshot_json, output_asset_id, created_at) VALUES (?, ?, 'n', 'completed', 'p', ?, '{}', ?, ?)",
                (f'job{index}', canvas_id, json.dumps({'prompt': f'p{index}', 'model': 'm', 'parameters': {'a': index}}),
                 asset, f'2026-01-0{index + 1}'),
            )
        # A node from before version tracking: it shows g2, but there is no history yet.
        connection.execute(
            "UPDATE canvas_nodes SET data_json = ? WHERE id = 'n'", (json.dumps({'title': 'x', 'assetId': 'g2'}),))

    history = NodeVersions(repository.database).list(canvas_id, 'n', 'g2')
    assert [(v['version'], v['assetId'], v['source'], v['prompt']) for v in history] == [
        (1, 'g1', 'generated', 'p0'), (2, 'g2', 'generated', 'p1')]

    with version_source('generated', job_id='job9', prompt='新的', parameters={'b': 1}, model='m2', comment_id='c1'):
        repository.update_node(canvas_id, 'n', {'data': {'assetId': 'g3'}})
    latest = NodeVersions(repository.database).list(canvas_id, 'n')[-1]

    # An uploaded picture on an untracked node is kept as version 1 when it gets replaced.
    repository.insert_node(canvas_id, 'u', 'image', 0, 0, 300, 260, {'title': 'u'})
    with repository.transaction() as connection:
        connection.execute(
            "UPDATE canvas_nodes SET data_json = ? WHERE id = 'u'", (json.dumps({'title': 'u', 'assetId': 'up'}),))
    repository.update_node(canvas_id, 'u', {'data': {'assetId': 'new'}})
    assert [(v['assetId'], v['source']) for v in NodeVersions(repository.database).list(canvas_id, 'u')] == [
        ('up', 'edited'), ('new', 'edited')]
    assert latest == {**latest, 'version': 3, 'assetId': 'g3', 'source': 'generated', 'jobId': 'job9',
                      'prompt': '新的', 'parameters': {'b': 1}, 'model': 'm2', 'commentId': 'c1'}
