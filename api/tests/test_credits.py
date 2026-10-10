"""Credits (积分, simulated): generations and agent turns cost credits; failures give them back."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import sqlite3
from threading import Timer

import pytest

from app.agent.runtime import AgentService
from app.agent.undo import undo_agent_run
from app.credits import Credits, chat_price, generation_price
from app.domain import DomainError
from app.models_registry import ModelFileError, parse_model, registry
from app.worker import Worker
from tests.agent_fakes import FakeFactory
from tests.test_agent_runtime import finish, make_service
from tests.test_canvas_tools import setup, user
from tests.test_worker import FakeProvider


def drain(credits: Credits, keep: int = 0) -> None:
    credits._add(keep - credits.balance(), 'test', '', None)


def test_a_new_install_starts_with_welcome_credits_and_can_top_up(repository):
    credits = Credits(repository.database)
    assert credits.balance() == 500
    assert credits.top_up(120) == 620
    entries = credits.history()
    assert [(e['kind'], e['delta'], e['balanceAfter']) for e in entries] == [('top_up', 120, 620), ('welcome', 500, 500)]
    for bad in (0, -5, 1.5, True, 10**9):
        with pytest.raises(DomainError):
            credits.top_up(bad)
    repository.database.init_schema()  # restarting doesn't give the welcome credits again
    assert credits.balance() == 620


def test_prices_follow_the_model_file():
    image, video = registry().get('seedream-5-pro'), registry().get('seedance-2.0-mini')
    assert generation_price(image) == 4 and generation_price(image, {'size': '1K'}) == 3
    assert generation_price(video) == 30
    assert generation_price(video, {'duration': 10}) == 60
    assert generation_price(video, {'duration': 10, 'resolution': '480p', 'generateAudio': False}) == 24
    assert chat_price(None) == 0 and chat_price(0.0001) == 0.01 and chat_price(0.153) == 15.3
    base = {'id': 'm', 'kind': 'image', 'provider': 'replicate', 'providerModel': 'x/m', 'inputs': {'prompt': 'prompt'}}
    assert parse_model(base).price() == {'base': 5, 'multiply': {}}  # no price: the kind's default
    assert parse_model({**base, 'credits': 7}).price() == {'base': 7, 'multiply': {}}
    for bad in ('free', {'base': -1}, {'base': 3, 'multiply': {'size': {'1K': 'cheap'}}}, {'base': 3, 'multiply': {'size': {}}}):
        with pytest.raises(ModelFileError):
            parse_model({**base, 'credits': bad})


def test_a_generation_is_charged_when_queued_and_refunded_if_it_fails(repository, tmp_path):
    tools, service, canvas_id = setup(repository)
    credits = Credits(repository.database)
    node = user(service, repository, canvas_id, 'create_node',
                {'nodeType': 'video', 'data': {'prompt': '海浪', 'parameters': {'duration': 10}}}, 'k1')['nodeId']
    result = user(service, repository, canvas_id, 'start_generation', {'targetNodeId': node}, 'g1')
    assert result['credits'] == 60 and result['balance'] == 440 and credits.balance() == 440
    assert credits.history()[0]['label'].startswith('Seedance 2.0 Mini')

    provider = FakeProvider()
    provider.fail_with('provider rejected input')
    Worker(repository, provider, tmp_path).run_once()
    assert credits.balance() == 500
    assert credits.history()[0]['kind'] == 'refund'
    assert credits.refund_job(result['jobId'], 'again') == 500  # only once

    again = user(service, repository, canvas_id, 'start_generation', {'targetNodeId': node}, 'g0')
    assert credits.balance() == 440
    user(service, repository, canvas_id, 'delete_node', {'nodeId': node}, 'd0')  # deleted before it started
    assert credits.balance() == 500 and credits.history()[0]['label'].startswith('删除节点')
    assert again['jobId']
    node = user(service, repository, canvas_id, 'create_node',
                {'nodeType': 'video', 'data': {'prompt': '海浪', 'parameters': {'duration': 10}}}, 'k2')['nodeId']

    drain(credits, 59)
    with pytest.raises(DomainError) as error:
        user(service, repository, canvas_id, 'start_generation', {'targetNodeId': node}, 'g2')
    assert error.value.code == 'INSUFFICIENT_CREDITS' and '需要 60' in error.value.message
    assert credits.balance() == 59
    assert not [j for j in repository.get_snapshot(canvas_id).jobs if j['target_node_id'] == node]  # nothing queued


def test_generation_retries_a_transient_database_lock_and_charges_once(repository, monkeypatch):
    tools, service, canvas_id = setup(repository)
    node = user(service, repository, canvas_id, 'create_node',
                {'nodeType': 'image', 'data': {'prompt': '灯塔'}}, 'create-for-lock-retry')['nodeId']

    transaction = repository.transaction
    attempts = 0

    @contextmanager
    def count_transactions(**kwargs):
        nonlocal attempts
        attempts += 1
        with transaction(**kwargs) as connection:
            yield connection

    monkeypatch.setattr(repository, 'transaction', count_transactions)
    monkeypatch.setattr('app.commands.GENERATION_LOCK_BUSY_TIMEOUT_MS', 40, raising=False)

    lock = repository.database._connect()
    lock.execute('BEGIN IMMEDIATE')
    release_errors = []

    def release_lock():
        try:
            lock.commit()
        except Exception as error:  # surface timer-thread failures in the test
            release_errors.append(error)

    releaser = Timer(0.12, release_lock)
    releaser.start()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(
                user, service, repository, canvas_id, 'start_generation',
                {'targetNodeId': node}, 'generation-after-lock',
            ).result(timeout=3)
    finally:
        releaser.join(timeout=1)
        if lock.in_transaction:
            lock.rollback()
        lock.close()

    assert not release_errors
    assert attempts >= 2
    assert result['credits'] == 4 and result['balance'] == 496
    assert Credits(repository.database).balance() == 496
    assert len([entry for entry in Credits(repository.database).history() if entry['kind'] == 'generation']) == 1
    assert len(repository.get_snapshot(canvas_id).jobs) == 1


def test_generation_reports_a_friendly_error_after_lock_retries_are_exhausted(repository, monkeypatch):
    tools, service, canvas_id = setup(repository)
    node = user(service, repository, canvas_id, 'create_node',
                {'nodeType': 'image', 'data': {'prompt': '灯塔'}}, 'create-for-lock-exhaustion')['nodeId']
    attempts = 0

    @contextmanager
    def always_locked(**kwargs):
        nonlocal attempts
        attempts += 1
        raise sqlite3.OperationalError('database is locked')
        yield  # make this a context manager without opening a transaction

    monkeypatch.setattr(repository, 'transaction', always_locked)
    monkeypatch.setattr('app.commands.GENERATION_LOCK_MAX_ATTEMPTS', 3, raising=False)
    monkeypatch.setattr('app.commands.time.sleep', lambda _: None, raising=False)

    with pytest.raises(DomainError) as error:
        user(service, repository, canvas_id, 'start_generation', {'targetNodeId': node}, 'generation-lock-exhausted')

    assert attempts == 3
    assert error.value.code == 'DATABASE_BUSY'
    assert '稍后重试' in error.value.message
    assert Credits(repository.database).balance() == 500
    assert not repository.get_snapshot(canvas_id).jobs


def test_the_agent_sees_prices_and_undo_gives_queued_generations_back(repository):
    tools, service, canvas_id = setup(repository)
    credits = Credits(repository.database)
    assert '默认参数每次 4 积分' in tools.list_models('image').text
    shot = tools.create_nodes([{'type': 'image', 'prompt': '厨房', 'title': '镜头 1'}]).touched[0]
    started = tools.generate([shot])
    assert '扣了 4 积分，还剩 496' in started.text
    tools.store.set_run_status(tools.run_id, 'completed')
    undo_agent_run(repository, canvas_id, tools.run_id)
    assert credits.balance() == 500

    drain(credits, 3)
    tools, service, canvas_id = setup(repository)
    shot2 = tools.create_nodes([{'type': 'image', 'prompt': '窗外'}]).touched[0]
    failed = tools.generate([shot2])
    assert failed.is_error and '积分不够' in failed.text


def test_agent_turns_cost_what_the_model_calls_cost(repository):
    factory = FakeFactory([('text', '好')], [('text', '好的')])
    service, store, canvas_id, session_id = make_service(repository, factory)
    credits = Credits(repository.database)

    async def two_turns():
        for text in ('第一句', '第二句'):
            await service.send_message(session_id, text, [])
            await finish(service, session_id)

    asyncio.run(two_turns())
    finished = [m['content'] for m in store.list_messages(session_id) if m['content']['kind'] == 'run_finished']
    # The fake reports a running total (0.01, then 0.02) like the real CLI: each turn is charged its own share.
    assert [(f['credits'], f['balance'], round(f['costUsd'], 4)) for f in finished] == [(1, 499, 0.01), (1, 498, 0.01)]
    assert [e['kind'] for e in credits.history()[:2]] == ['chat', 'chat']

    # After a restart the CLI resumes the chat with its saved running total (0.02): only the new part counts.
    for restored in (0.02, 0.0):  # and if it starts over from 0, the whole total is this turn's
        restarted = AgentService(repository, service.command_service, store, service.config, FakeFactory([('text', '在')], restored_cost=restored))
        asyncio.run(_one(restarted, session_id))
    finished = [m['content'] for m in store.list_messages(session_id) if m['content']['kind'] == 'run_finished']
    assert [f['credits'] for f in finished] == [1, 1, 1, 1]
    assert credits.balance() == 496

    drain(credits, 0)
    with pytest.raises(DomainError) as error:
        asyncio.run(service.send_message(session_id, '还在吗', []))
    assert error.value.code == 'INSUFFICIENT_CREDITS'


async def _one(service, session_id):
    await service.send_message(session_id, '还在吗', [])
    await finish(service, session_id)


def test_routes(client):
    body = client.get('/api/credits').json()
    assert body['balance'] == 500 and body['usdPerCredit'] == 0.01 and body['entries'][0]['kind'] == 'welcome'
    assert client.post('/api/credits/top-up', json={'amount': 300}).json()['balance'] == 800
    assert client.post('/api/credits/top-up', json={'amount': 0}).status_code == 422
    models = client.get('/api/models').json()['models']
    assert next(m for m in models if m['id'] == 'seedream-5-pro')['credits']['base'] == 4


def test_agent_usage_is_shown_exactly_and_charged_in_whole_credits(repository):
    """No rounding up per turn: the fraction is carried until it makes a whole credit."""
    credits = Credits(repository.database)
    assert credits.charge_usage(2.23, 'chat', 'Agent 对话', 'run:a') == (2, 498)
    assert credits.pending() == 0.23
    assert credits.charge_usage(0.5, 'chat', 'Agent 对话', 'run:b') == (0, 498)
    assert credits.charge_usage(0.4, 'chat', 'Agent 对话', 'run:c') == (1, 497)
    assert credits.pending() == 0.13
    assert credits.charge_usage(0.4, 'chat', 'Agent 对话', 'run:c') == (0, 497)  # same turn twice: once
    history = credits.history()
    assert [(e['used'], e['delta']) for e in history[:3]] == [(0.4, -1), (0.5, 0), (2.23, -2)]
    assert 'used' not in history[-1]  # the welcome credits are not usage
    assert credits.summary()['pending'] == 0.13
