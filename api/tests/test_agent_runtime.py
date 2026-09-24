import asyncio
import os

import pytest

from app.agent.config import AgentConfig
from app.agent.runtime import AgentService
from app.agent.store import AgentStore
from app.commands import CanvasCommandService
from app.domain import DomainError
from app.events import EventStore
from tests.agent_fakes import FakeFactory

CONFIG = AgentConfig(api_key_present=True, poll_seconds=0.01)


def make_service(repository, factory, config=CONFIG):
    store = AgentStore(repository.database)
    service = AgentService(
        repository, CanvasCommandService(repository, EventStore(repository.database)), store, config, factory
    )
    canvas_id = repository.create_canvas('Agent').canvasId
    session = store.create_session(canvas_id)
    return service, store, canvas_id, session['id']


async def finish(service, session_id):
    runtime = service.sessions[session_id]
    await asyncio.wait_for(runtime.task, 5)


def kinds(store, session_id):
    return [message['content']['kind'] for message in store.list_messages(session_id)]


def test_a_run_streams_text_uses_tools_and_is_recorded(repository):
    factory = FakeFactory([
        ('text', '好的，我先建一个便签。'),
        ('tool', 'create_nodes', {'nodes': [{'type': 'note', 'content': '午后光线'}]}),
        ('text', '建好了。'),
    ])
    service, store, canvas_id, session_id = make_service(repository, factory)

    async def scenario():
        queue = service.subscribe(session_id)
        run = await service.send_message(session_id, '帮我建个便签', [])
        await finish(service, session_id)
        live = []
        while not queue.empty():
            live.append(queue.get_nowait()['kind'])
        return run, live

    run, live = asyncio.run(scenario())
    assert kinds(store, session_id) == ['user_message', 'assistant_text', 'tool_step',
                                        'assistant_text', 'run_finished']
    assert 'text_delta' in live  # streamed, but not persisted
    assert store.get_run(run['id'])['status'] == 'completed'
    assert store.get_session(session_id)['title'] == '帮我建个便签'
    assert store.get_session(session_id)['sdk_session_id'] == 'sdk-session-1'
    (node,) = repository.get_snapshot(canvas_id).nodes
    assert node.data['content'] == '午后光线'
    assert repository.agent_run_changes(run['id'])  # undoable


def test_options_lock_down_tools_and_permissions(repository):
    factory = FakeFactory([('text', 'hi')])
    service, _, _, session_id = make_service(repository, factory)

    async def scenario():
        await service.send_message(session_id, 'hi')
        await finish(service, session_id)

    asyncio.run(scenario())
    options = factory.clients[0].options
    assert options.tools == [] and options.model == 'claude-opus-5-5'
    memory_tools = ('remember', 'update_memory', 'forget', 'recall')
    assert all('get_' in name or 'view_' in name or 'wait_' in name or 'list_' in name or name.endswith(memory_tools)
               for name in options.allowed_tools)
    assert not any(name.endswith(('generate', 'update_node', 'delete_nodes')) for name in options.allowed_tools)
    assert '[权限档位]' in factory.clients[0].prompts[0]


def test_generation_waits_for_confirmation(repository):
    factory = FakeFactory(
        [('tool', 'create_nodes', {'nodes': [{'type': 'image', 'prompt': '兔子'}]})],
        [('tool', 'generate', {'node_ids': ['PLACEHOLDER']})],
    )
    service, store, canvas_id, session_id = make_service(repository, factory)

    async def scenario(approve: bool):
        queue = service.subscribe(session_id)
        await service.send_message(session_id, 'go')
        while True:
            event = await asyncio.wait_for(queue.get(), 5)
            if event['kind'] == 'confirm_request':
                assert event['summary'].startswith('生成 1 个节点')
                assert event["touched"] == [repository.get_snapshot(canvas_id).nodes[0].id]
                assert store.get_run(event['runId'])['status'] == 'waiting_confirmation'
                service.confirm(event['requestId'], approve)
                break
        await finish(service, session_id)

    async def run_all():
        await service.send_message(session_id, '建节点')
        await finish(service, session_id)
        node_id = repository.get_snapshot(canvas_id).nodes[0].id
        factory.scripts[0][0][2]['node_ids'][0] = node_id
        factory.scripts.append([('tool', 'generate', {'node_ids': [node_id]})])
        await scenario(False)
        assert repository.get_snapshot(canvas_id).jobs == []
        assert '用户拒绝了' in factory.clients[0].denials[-1]
        await scenario(True)
        assert len(repository.get_snapshot(canvas_id).jobs) == 1

    asyncio.run(run_all())


def test_stop_prevents_further_commands(repository):
    factory = FakeFactory([
        ('tool', 'create_nodes', {'nodes': [{'type': 'note'}]}),
        ('pause', 0.2),
        ('tool', 'create_nodes', {'nodes': [{'type': 'note'}]}),
        ('tool', 'create_nodes', {'nodes': [{'type': 'note'}]}),
    ])
    service, store, canvas_id, session_id = make_service(repository, factory)

    async def scenario():
        run = await service.send_message(session_id, 'many notes')
        await asyncio.sleep(0.05)
        await service.stop(run['id'])
        await finish(service, session_id)
        return run

    run = asyncio.run(scenario())
    assert len(repository.get_snapshot(canvas_id).nodes) == 1
    assert store.get_run(run['id'])['status'] == 'stopped'


def test_one_run_at_a_time_and_needs_a_key(repository):
    factory = FakeFactory([('pause', 0.2)])
    service, _, _, session_id = make_service(repository, factory)

    async def scenario():
        await service.send_message(session_id, 'first')
        with pytest.raises(DomainError, match='还在处理'):
            await service.send_message(session_id, 'second')
        await finish(service, session_id)

    asyncio.run(scenario())

    service_without_key, _, _, other = make_service(repository, FakeFactory(), AgentConfig(api_key_present=False))
    with pytest.raises(DomainError) as error:
        asyncio.run(service_without_key.send_message(other, 'hi'))
    assert error.value.code == 'AGENT_NOT_CONFIGURED'


def test_undo_after_a_run(repository):
    factory = FakeFactory([('tool', 'create_nodes', {'nodes': [{'type': 'note'}, {'type': 'image'}]})])
    service, store, canvas_id, session_id = make_service(repository, factory)

    async def scenario():
        run = await service.send_message(session_id, 'make two')
        await finish(service, session_id)
        return run

    run = asyncio.run(scenario())
    assert len(repository.get_snapshot(canvas_id).nodes) == 2
    result = service.undo(run['id'])
    assert len(result['deletedNodes']) == 2 and repository.get_snapshot(canvas_id).nodes == []
    assert kinds(store, session_id)[-1] == 'run_undone'


def test_confirmation_notes_reach_the_model(repository):
    factory = FakeFactory([('tool', 'create_nodes', {'nodes': [{'type': 'image', 'prompt': '兔子'}]})])
    service, store, canvas_id, session_id = make_service(repository, factory)
    store.update_settings('default', {'permissionMode': 'confirm_all'})

    async def answer(approve: bool, note: str):
        queue = service.subscribe(session_id)
        await service.send_message(session_id, 'go')
        resolved = None
        while resolved is None:
            event = await asyncio.wait_for(queue.get(), 5)
            if event['kind'] == 'confirm_request':
                service.confirm(event['requestId'], approve, note)
            elif event['kind'] == 'confirm_resolved':
                resolved = event
        await finish(service, session_id)
        return resolved

    async def run_all():
        event = await answer(False, '  改成狐狸  ')
        assert event['approved'] is False and event['note'] == '改成狐狸'
        assert '用户补充：改成狐狸' in factory.clients[0].denials[-1]
        assert '不要重试' not in factory.clients[0].denials[-1]
        assert repository.get_snapshot(canvas_id).nodes == []

        factory.scripts.append([('tool', 'create_nodes', {'nodes': [{'type': 'image', 'prompt': '兔子'}]})])
        event = await answer(True, '后面都用暖色调')
        assert event['approved'] is True and event['note'] == '后面都用暖色调'
        text = factory.clients[0].tool_results[-1]['content'][0]['text']
        assert '[用户确认时的补充] 后面都用暖色调' in text
        assert len(repository.get_snapshot(canvas_id).nodes) == 1

    asyncio.run(run_all())


def test_memory_is_shared_across_chats_and_undone_with_the_turn(repository):
    factory = FakeFactory(
        [('tool', 'remember', {'layer': 'project', 'category': 'character', 'content': '主角是一只米白色的垂耳兔'}),
         ('tool', 'remember', {'layer': 'preference', 'category': 'params', 'content': '图片默认用 16:9'}),
         ('text', '记好了')],
        [('tool', 'recall', {'query': '菜板 广告'}), ('text', '找到了')],
    )
    service, store, canvas_id, first = make_service(repository, factory)

    async def scenario():
        queue = service.subscribe(first)
        run = await service.send_message(first, '我们在做一个菜板广告，主角是米白色垂耳兔，图片都用 16:9')
        await finish(service, first)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        changes = [event for event in events if event['kind'] == 'memory_change']
        assert [c['content'] for c in changes] == ['主角是一只米白色的垂耳兔', '图片默认用 16:9']
        assert all(c['action'] == 'added' and c['memoryId'] for c in changes)
        assert not [e for e in events if e['kind'] == 'tool_step']  # memory writes are not canvas steps

        # A second chat on the same canvas sees the memory and the first chat, and can search it.
        second = store.create_session(canvas_id)['id']
        await service.send_message(second, '之前那个广告的主角是什么来着？')
        await finish(service, second)
        prompt = factory.clients[-1].prompts[-1]
        assert '主角是一只米白色的垂耳兔' in prompt and '图片默认用 16:9' in prompt
        assert '[这张画布上的其他对话]' in prompt and '我们在做一个菜板广告' in prompt
        recalled = factory.clients[-1].tool_results[-1]['content'][0]['text']
        assert '菜板广告' in recalled

        # Undoing the first turn takes its memories back.
        undone = service.undo(run['id'])
        assert undone['memoriesReverted'] == 2
        assert service.memory.context_block('default') == ''

    asyncio.run(scenario())


def test_switching_models_keeps_the_conversation(repository, monkeypatch):
    factory = FakeFactory([('text', '一')], [('text', '二')], [('text', '三')])
    service, store, _, session_id = make_service(repository, factory)

    async def scenario():
        queue = service.subscribe(session_id)
        await service.send_message(session_id, 'a')
        await finish(service, session_id)
        store.update_settings('default', {'model': 'claude-sonnet-5'})
        await service.send_message(session_id, 'b')
        await finish(service, session_id)
        await service.send_message(session_id, 'c')
        await finish(service, session_id)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        return events

    events = asyncio.run(scenario())
    assert len(factory.clients) == 1  # same client, same conversation
    assert factory.clients[0].options.model == 'claude-opus-5-5'
    assert factory.clients[0].models == ['claude-sonnet-5']  # switched once, before the 2nd message
    replies = [e['model'] for e in events if e['kind'] == 'assistant_text']
    assert replies == ['claude-opus-5-5', 'claude-sonnet-5', 'claude-sonnet-5']


def test_subscription_mode_keeps_the_api_key_away_from_the_agent(repository, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-should-not-be-used')
    factory = FakeFactory([('text', 'hi')])
    config = AgentConfig(auth='subscription', poll_seconds=0.01)
    service, _, _, session_id = make_service(repository, factory, config)

    async def scenario():
        await service.send_message(session_id, 'hi')
        await finish(service, session_id)

    asyncio.run(scenario())
    assert 'ANTHROPIC_API_KEY' not in os.environ
