from app.agent.store import AgentStore
from app.commands import CanvasCommandService
from app.domain import DomainError
from app.events import EventStore
from app.repositories import CanvasRepository
from app.schemas import CommandEnvelope

import pytest


class Harness:
    def __init__(self, repository: CanvasRepository):
        self.repository = repository
        self.service = CanvasCommandService(repository, EventStore(repository.database))
        self.canvas_id = repository.create_canvas('T').canvasId
        store = AgentStore(repository.database)
        self.run_id = store.create_run(store.create_session(self.canvas_id)['id'], 'auto')['id']
        self.keys = 0

    def run(self, command, payload, *, agent=True, key=None):
        self.keys += 1
        revision = self.repository.get_snapshot(self.canvas_id).revision
        return self.service.execute(self.canvas_id, CommandEnvelope(
            command=command, baseRevision=revision, idempotencyKey=key or f'k{self.keys}', payload=payload,
            actor='agent' if agent else 'user', agentRunId=self.run_id if agent else None,
        ))

    def changes(self):
        return [(c['entity_type'], c['entity_id'], c['before'] is None, c['after'] is None)
                for c in self.repository.agent_run_changes(self.run_id)]


def test_agent_commands_are_marked_and_recorded(repository):
    h = Harness(repository)
    result = h.run('create_node', {'nodeType': 'image', 'nodeId': 'a'})
    assert result.actor == 'agent' and result.agentRunId == h.run_id
    event = EventStore(repository.database).after_revision(h.canvas_id, 0)[-1]
    assert event.payload['actor'] == 'agent' and event.payload['agentRunId'] == h.run_id
    assert h.changes() == [('node', 'a', True, False)]


def test_update_records_before_and_after(repository):
    h = Harness(repository)
    h.run('create_node', {'nodeType': 'image', 'nodeId': 'a', 'x': 0, 'y': 0}, agent=False)
    h.run('update_node', {'nodeId': 'a', 'x': 50, 'data': {'prompt': '兔子'}})
    change = repository.agent_run_changes(h.run_id)[0]
    assert change['before']['x'] == 0 and change['after']['x'] == 50
    assert change['after']['data']['prompt'] == '兔子'


def test_deleting_a_node_records_cascaded_edges(repository):
    h = Harness(repository)
    h.run('create_node', {'nodeType': 'image', 'nodeId': 'a'}, agent=False)
    h.run('create_node', {'nodeType': 'video', 'nodeId': 'b'}, agent=False)
    h.run('connect_nodes', {'edgeId': 'e', 'sourceNodeId': 'a', 'targetNodeId': 'b'}, agent=False)
    h.run('delete_elements', {'nodeIds': ['a']})
    assert set(h.changes()) == {('node', 'a', False, True), ('edge', 'e', False, True)}


def test_generation_job_is_recorded(repository):
    h = Harness(repository)
    h.run('create_node', {'nodeType': 'image', 'nodeId': 'a'}, agent=False)
    result = h.run('start_generation', {'targetNodeId': 'a', 'prompt': 'x'})
    assert ('job', result.payload['jobId'], True, False) in h.changes()


def test_user_commands_and_retries_are_not_recorded_twice(repository):
    h = Harness(repository)
    h.run('create_node', {'nodeType': 'image', 'nodeId': 'u'}, agent=False)
    h.run('create_node', {'nodeType': 'image', 'nodeId': 'a'}, key='same')
    h.run('create_node', {'nodeType': 'image', 'nodeId': 'a'}, key='same')  # idempotent retry
    assert h.changes() == [('node', 'a', True, False)]


def test_viewport_changes_are_not_recorded(repository):
    h = Harness(repository)
    h.run('update_canvas', {'viewport': {'x': 1, 'y': 2, 'zoom': 1}})
    assert h.changes() == []


def test_user_commands_cannot_claim_an_agent_run(repository):
    h = Harness(repository)
    with pytest.raises(DomainError):
        repository.get_snapshot(h.canvas_id)
        h.service.execute(h.canvas_id, CommandEnvelope(
            command='create_node', baseRevision=0, idempotencyKey='x',
            payload={'nodeType': 'image'}, actor='user', agentRunId=h.run_id,
        ))
