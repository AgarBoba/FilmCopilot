import asyncio

import pytest

from app.agent.permissions import ConfirmationBroker, RunState, decide, describe_request


def run_state(**kwargs):
    return RunState(node_types={'img': 'image', 'img2': 'image', 'vid': 'video', 'note': 'note'}, **kwargs)


@pytest.mark.parametrize('mode', ['confirm_all', 'confirm_generation', 'auto'])
def test_read_only_tools_are_always_allowed(mode):
    for tool in ('get_canvas', 'get_node', 'view_asset', 'wait_for_generation', 'mcp__canvas__get_canvas'):
        assert decide(tool, {}, mode, run_state())[0] == 'allow'


@pytest.mark.parametrize('mode, tool, expected', [
    ('confirm_all', 'update_node', 'ask'),
    ('confirm_all', 'generate', 'ask'),
    ('confirm_generation', 'update_node', 'allow'),
    ('confirm_generation', 'create_nodes', 'allow'),
    ('confirm_generation', 'generate', 'ask'),
    ('confirm_generation', 'delete_nodes', 'ask'),
    ('auto', 'generate', 'allow'),
    ('auto', 'delete_nodes', 'allow'),
])
def test_mode_matrix(mode, tool, expected):
    assert decide(tool, {'node_ids': ['img']}, mode, run_state())[0] == expected


@pytest.mark.parametrize('mode', ['confirm_all', 'confirm_generation', 'auto'])
def test_video_generation_always_asks(mode):
    decision, reason = decide('generate', {'node_ids': ['img', 'vid']}, mode, run_state())
    assert decision == 'ask' and '视频' in reason


def test_generation_cap_forces_confirmation():
    assert decide('generate', {'node_ids': ['img']}, 'auto', run_state(generation_count=3))[0] == 'allow'
    decision, reason = decide('generate', {'node_ids': ['img', 'img2']}, 'auto', run_state(generation_count=3))
    assert decision == 'ask' and '上限' in reason


def test_unknown_tools_are_denied_and_unknown_modes_ask():
    assert decide('Bash', {}, 'auto', run_state())[0] == 'deny'
    assert decide('update_node', {}, 'weird', run_state())[0] == 'ask'


def test_describe_request():
    text = describe_request('generate', {'node_ids': ['a', 'b']}, {'a': '图片 2', 'b': '图片 3'})
    assert text == '生成 2 个节点：「图片 2」、「图片 3」'


def test_broker_resolves_times_out_and_cancels():
    async def scenario():
        broker = ConfirmationBroker(timeout_seconds=0.2)

        approved = broker.open('run', 'generate', 's', '')
        asyncio.get_running_loop().call_later(0.01, broker.resolve, approved.id, True)
        assert await broker.wait(approved) == (True, '')

        timed_out = broker.open('run', 'generate', 's', '')
        assert await broker.wait(timed_out) == (False, '')

        cancelled = broker.open('run', 'generate', 's', '')
        asyncio.get_running_loop().call_later(0.01, broker.cancel_run, 'run')
        assert await broker.wait(cancelled) == (False, '')
        assert broker.pending == {}
        assert broker.resolve(cancelled.id, True) is False  # already gone

    asyncio.run(scenario())
