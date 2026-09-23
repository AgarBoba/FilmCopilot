import pytest

from app.agent.store import AgentStore
from app.domain import DomainError
from tests.test_command_actor import Harness


def undo(h, key='undo'):
    return h.run('undo_agent_run', {'runId': h.run_id}, key=key).payload


def finish(h):
    AgentStore(h.repository.database).set_run_status(h.run_id, 'completed')


def state(h):
    return h.repository.canvas_state(h.canvas_id)


def test_undo_restores_created_updated_deleted(repository):
    h = Harness(repository)
    h.run('create_node', {'nodeType': 'image', 'nodeId': 'keep', 'x': 0, 'y': 0, 'data': {'prompt': '原来'}}, agent=False)
    h.run('create_node', {'nodeType': 'video', 'nodeId': 'gone', 'x': 300, 'y': 0}, agent=False)
    h.run('connect_nodes', {'edgeId': 'e1', 'sourceNodeId': 'keep', 'targetNodeId': 'gone'}, agent=False)
    before = state(h)

    h.run('create_node', {'nodeType': 'image', 'nodeId': 'new'})
    h.run('connect_nodes', {'edgeId': 'e2', 'sourceNodeId': 'new', 'targetNodeId': 'gone'})
    h.run('update_node', {'nodeId': 'keep', 'x': 99, 'data': {'prompt': '改过', 'extra': 1}})
    h.run('delete_elements', {'nodeIds': ['gone']})
    finish(h)

    result = undo(h)
    assert state(h) == before  # exact restore, including removing the added 'extra' key
    assert result['skipped'] == []
    assert AgentStore(repository.database).get_run(h.run_id)['status'] == 'undone'


def test_undo_skips_nodes_user_changed_later(repository):
    h = Harness(repository)
    h.run('create_node', {'nodeType': 'image', 'nodeId': 'a', 'data': {'prompt': '原来'}}, agent=False)
    h.run('update_node', {'nodeId': 'a', 'data': {'prompt': 'Agent 写的'}})
    h.run('create_node', {'nodeType': 'image', 'nodeId': 'b'})
    finish(h)
    h.run('update_node', {'nodeId': 'a', 'data': {'prompt': '我又改了'}}, agent=False)

    result = undo(h)
    assert state(h)['node']['a']['data']['prompt'] == '我又改了'
    assert 'b' not in state(h)['node']
    assert result['skipped'] == [{'type': 'node', 'id': 'a', 'reason': 'changed_after_run'}]


def test_generation_result_from_the_run_does_not_block_undo(repository):
    h = Harness(repository)
    h.run('create_node', {'nodeType': 'image', 'nodeId': 'a', 'data': {'prompt': '原来'}}, agent=False)
    h.run('update_node', {'nodeId': 'a', 'data': {'prompt': '新'}})
    job_id = h.run('start_generation', {'targetNodeId': 'a'}).payload['jobId']
    finish(h)
    # the worker attaches the result outside any command
    repository._execute("INSERT INTO assets (id, canvas_id, kind, path, mime_type) VALUES ('out', ?, 'image', 'x', 'image/png')", (h.canvas_id,))
    repository._execute("UPDATE generation_jobs SET status='completed', output_asset_id='out' WHERE id=?", (job_id,))
    repository.update_node(h.canvas_id, 'a', {'data': {'assetId': 'out'}})

    result = undo(h)
    assert result['skipped'] == []
    assert state(h)['node']['a']['data'] == {'title': 'Untitled image', 'prompt': '原来'}


def test_undo_cancels_generations_that_have_not_started(repository):
    h = Harness(repository)
    h.run('create_node', {'nodeType': 'image', 'nodeId': 'a'}, agent=False)
    job_id = h.run('start_generation', {'targetNodeId': 'a'}).payload['jobId']
    finish(h)
    assert undo(h)['cancelledJobs'] == [job_id]
    assert repository.get_generation_job(job_id)['status'] == 'canceled'


def test_undo_is_not_repeatable_and_not_while_running(repository):
    h = Harness(repository)
    h.run('create_node', {'nodeType': 'image', 'nodeId': 'a'})
    with pytest.raises(DomainError, match='Stop the agent run'):
        undo(h, key='early')
    finish(h)
    undo(h, key='first')
    with pytest.raises(DomainError, match='already been undone'):
        undo(h, key='second')


def test_undo_itself_is_not_recorded_as_a_change(repository):
    h = Harness(repository)
    h.run('create_node', {'nodeType': 'image', 'nodeId': 'a'})
    finish(h)
    count = len(repository.agent_run_changes(h.run_id))
    undo(h)
    assert len(repository.agent_run_changes(h.run_id)) == count
