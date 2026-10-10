"""Keeping the agent's context lean: nothing the model already saw unchanged is sent again,
and long chats are compacted before the next turn."""
import asyncio
import json

from app.agent.config import AgentConfig
from app.agent.mcp_server import TOOL_SPECS
from tests.agent_fakes import FakeFactory
from tests.test_agent_runtime import finish, make_service
from tests.test_canvas_tools import setup, user


def run_turns(service, session_id, texts):
    async def scenario():
        for text in texts:
            await service.send_message(session_id, text, [])
            await finish(service, session_id)
    asyncio.run(scenario())


def test_get_canvas_sends_only_what_changed_since_the_last_look(repository):
    tools, service, canvas_id = setup(repository)
    ids = tools.create_nodes([{'type': 'image', 'prompt': f'镜头 {i}', 'title': f'镜头 {i}'} for i in range(8)]).touched
    first = tools.get_canvas().text
    assert first.count('- [') == 8  # the first look is the full listing

    assert '完全一样' in tools.get_canvas().text and '- [' not in tools.get_canvas().text

    user(service, repository, canvas_id, 'update_node', {'nodeId': ids[2], 'data': {'prompt': '新的画面'}}, 'u1')
    user(service, repository, canvas_id, 'delete_node', {'nodeId': ids[5]}, 'd1')
    diff = tools.get_canvas().text
    assert diff.splitlines()[0].startswith('画布共 7 个节点')
    assert '[新增或有变化]' in diff and '新的画面' in diff and diff.count('- [') == 1
    assert f'[已删除] [{ids[5]}]' in diff and '其余 6 项没变' in diff

    assert tools.get_canvas(full=True).text.count('- [') == 7  # asked for the whole list
    assert tools.get_canvas([ids[0]]).text.count('- [') == 1  # a partial look is never a diff

    for node_id in ids[:6]:  # most of it changed: the full listing again
        if node_id != ids[5]:
            user(service, repository, canvas_id, 'update_node', {'nodeId': node_id, 'data': {'prompt': 'x'}}, f'm-{node_id}')
    assert tools.get_canvas().text.count('- [') == 7
    assert 'full' in json.dumps([spec for spec in TOOL_SPECS if spec[0] == 'get_canvas'])


def test_turn_context_is_not_repeated_and_the_canvas_view_carries_over(repository):
    factory = FakeFactory(
        [('tool', 'get_canvas', {})], [('tool', 'get_canvas', {})], [('text', '好')],
    )
    service, store, canvas_id, session_id = make_service(repository, factory)
    service.memory.add('project', '统一手绘画风', 'style', project_id='default')
    run_turns(service, session_id, ['看看画布', '再看看', '记得风格吗'])
    client = factory.clients[0]
    assert '统一手绘画风' in client.prompts[0]
    assert '统一手绘画风' not in client.prompts[1] and '[项目记忆] 和你在这个对话里之前看到的一样' in client.prompts[1]
    assert '完全一样' in client.tool_results[1]['content'][0]['text']  # second turn's get_canvas: no repeat

    service.memory.add('project', '镜头偏暖', 'style', project_id='default')  # changed: sent again, in full
    factory.scripts.append([('text', '嗯')])
    run_turns(service, session_id, ['还有呢'])
    assert '镜头偏暖' in client.prompts[-1] and '统一手绘画风' in client.prompts[-1]


def test_a_long_chat_is_compacted_before_the_next_turn(repository):
    factory = FakeFactory([('tool', 'get_canvas', {}), ('text', '一')], [('text', '二')], [('text', '三')])
    config = AgentConfig(api_key_present=True, poll_seconds=0.01, compact_tokens=30_000)  # the fake reports ~32k
    service, store, canvas_id, session_id = make_service(repository, factory, config)
    service.memory.add('project', '统一手绘画风', 'style', project_id='default')
    run_turns(service, session_id, ['第一句', '第二句'])
    client = factory.clients[0]
    assert len(client.compactions) == 1 and '保留' in client.compactions[0]
    # After compacting, everything is sent in full again (the summary replaced it).
    assert '统一手绘画风' in client.prompts[1]
    kinds = [m['content']['kind'] for m in store.list_messages(session_id)]
    assert kinds.count('context_compacted') == 1
    assert kinds.index('context_compacted') > kinds.index('user_message', 1)  # in the second turn
    finished = [m['content'] for m in store.list_messages(session_id) if m['content']['kind'] == 'run_finished']
    assert round(finished[1]['costUsd'], 4) == 0.015  # the compaction is part of that turn's cost

    off = AgentConfig(api_key_present=True, poll_seconds=0.01, compact_tokens=0)
    factory2 = FakeFactory([('text', '一')], [('text', '二')])
    service2, _, _, session2 = make_service(repository, factory2, off)
    run_turns(service2, session2, ['a', 'b'])
    assert factory2.clients[0].compactions == []


def test_each_turn_records_its_token_usage(repository):
    from types import SimpleNamespace
    from app.agent.runtime import UsageTally
    tally = UsageTally()
    request = {'input_tokens': 500, 'cache_read_input_tokens': 91000, 'cache_creation_input_tokens': 3000, 'output_tokens': 400}
    for _ in range(2):  # two content blocks of one request: counted once
        tally.add(SimpleNamespace(usage=request, message_id='msg-1'))
    tally.add(SimpleNamespace(usage={'input_tokens': 10, 'output_tokens': 5}, message_id='msg-2'))
    tally.add(SimpleNamespace(usage=None, message_id='msg-3'))
    assert tally.summary() == {'input': 510, 'cacheRead': 91000, 'cacheWrite': 3000, 'output': 405, 'requests': 2}
    assert UsageTally().summary() is None

    factory = FakeFactory([('text', '好')])
    service, store, canvas_id, session_id = make_service(repository, factory)
    run_turns(service, session_id, ['你好'])
    finished = next(m['content'] for m in store.list_messages(session_id) if m['content']['kind'] == 'run_finished')
    assert finished['usage'] == {'input': 120, 'cacheRead': 30000, 'cacheWrite': 1880, 'output': 40, 'requests': 1}
