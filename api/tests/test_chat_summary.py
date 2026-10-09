"""Chat summaries for other chats on the canvas, and recall that copes with Chinese phrases."""
import asyncio

from app.agent.config import AgentConfig
from app.agent.memory import MemoryStore, match_score, search_terms
from app.agent.memory_tools import MemoryTools
from app.agent.runtime import AgentService
from app.agent.store import AgentStore
from app.agent.summary import build_input, clean
from app.commands import CanvasCommandService
from app.events import EventStore
from tests.agent_fakes import FakeFactory

CONFIG = AgentConfig(api_key_present=True, poll_seconds=0.01)


class FakeSummarizer:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.inputs: list[str] = []

    async def __call__(self, text):
        self.inputs.append(text)
        answer = self.answers.pop(0) if self.answers else '摘要'
        if isinstance(answer, Exception):
            raise answer
        return answer


def make(repository, factory, summarizer):
    store = AgentStore(repository.database)
    service = AgentService(repository, CanvasCommandService(repository, EventStore(repository.database)),
                           store, CONFIG, factory, summarizer=summarizer)
    canvas_id = repository.create_canvas('Agent').canvasId
    return service, store, canvas_id


async def settle(service, session_id):
    await asyncio.wait_for(service.sessions[session_id].task, 5)
    task = service._summary_tasks.get(session_id)
    if task:
        await asyncio.wait_for(task, 5)


def test_phrases_match_by_pieces():
    terms = search_terms('米白色兔子 Seedream')
    assert terms[0][1][:2] == ['米白', '白色'] and terms[1] == ('seedream', [])
    assert match_score('主角是一只米白色的垂耳兔', search_terms('垂耳兔主角')) > 0
    assert match_score('主角是一只米白色的垂耳兔', search_terms('火箭发射场')) == 0
    assert match_score('用 Seedream 5 Pro', search_terms('seedream')) == 1


def test_memory_search_finds_a_reworded_phrase(repository):
    memory = MemoryStore(repository.database)
    memory.add('project', '主角是一只米白色的垂耳兔', 'character', project_id='p1')
    memory.add('project', '背景是乡村厨房', 'setting', project_id='p1')
    found = memory.search('p1', '米白色兔子')
    assert [m['content'] for m in found] == ['主角是一只米白色的垂耳兔']


def test_summary_replaces_the_last_sentence_and_follows_each_turn(repository):
    summarizer = FakeSummarizer('在给「图片 1」做开场画面，已定晨光色调，等用户挑一张', '用户在问另一个对话的进展',
                                '开场画面已撤销，回到只有构思的状态')
    factory = FakeFactory(
        [('tool', 'create_nodes', {'nodes': [{'type': 'note', 'content': '开场：晨光里的厨房'}]}), ('text', '好的，已经建好便签。')],
        [('text', '在。')],
    )
    service, store, canvas_id = make(repository, factory, summarizer)
    first = store.create_session(canvas_id)['id']
    second = store.create_session(canvas_id)['id']

    async def scenario():
        run = await service.send_message(first, '帮我做开场画面，晨光色调')
        await settle(service, first)
        assert store.get_session(first)['summary'].startswith('在给「图片 1」做开场画面')
        sent = summarizer.inputs[0]
        assert '用户：帮我做开场画面，晨光色调' in sent and '（操作）新建 1 个节点' in sent and '之前的摘要：（还没有）' in sent

        await service.send_message(second, '另一个对话在做什么？')
        await settle(service, second)
        prompt = factory.clients[-1].prompts[-1]
        assert '[这张画布上的其他对话]（摘要；' in prompt
        assert '在给「图片 1」做开场画面，已定晨光色调' in prompt and '最后一句' not in prompt

        service.undo(run['id'])
        await asyncio.wait_for(service._summary_tasks[first], 5)
        assert '（用户撤销了这一轮的改动）' in summarizer.inputs[-1]
        assert '之前的摘要：在给「图片 1」' in summarizer.inputs[-1]
        assert store.get_session(first)['summary'] == '开场画面已撤销，回到只有构思的状态'

    asyncio.run(scenario())


def test_without_a_summary_or_when_it_fails_the_last_sentence_stays(repository):
    summarizer = FakeSummarizer(RuntimeError('model down'))
    factory = FakeFactory([('text', '开场可以从窗边的晨光切入。')], [('text', '好')])
    service, store, canvas_id = make(repository, factory, summarizer)
    first = store.create_session(canvas_id)['id']
    second = store.create_session(canvas_id)['id']

    async def scenario():
        await service.send_message(first, '想个开场')
        await settle(service, first)
        assert store.get_session(first)['summary'] is None
        await service.send_message(second, '你好')
        await settle(service, second)
        assert '最后一句：开场可以从窗边的晨光切入。' in factory.clients[-1].prompts[-1]

    asyncio.run(scenario())


def test_comment_chats_are_not_summarised(repository):
    summarizer = FakeSummarizer()
    factory = FakeFactory([('text', '改好了')])
    service, store, canvas_id = make(repository, factory, summarizer)
    session = store.create_session(canvas_id, kind='comment')['id']

    async def scenario():
        await service.send_message(session, '把杯子换成抹茶')
        await settle(service, session)

    asyncio.run(scenario())
    assert summarizer.inputs == []


def test_recall_labels_where_a_chat_lives_and_searches_summaries(repository):
    store = AgentStore(repository.database)
    memory = MemoryStore(repository.database)
    here = repository.create_canvas('这里').canvasId
    there = repository.create_canvas('那里').canvasId
    current = store.create_session(here)['id']
    other = store.create_session(there, title='菜板广告')['id']
    store.add_message(other, 'user', {'kind': 'user_message', 'text': '主角是米白色的垂耳兔'})
    store.set_summary(other, '在做菜板广告的分镜，主角定为米白色垂耳兔')
    note = store.create_session(here, title='改杯子', kind='comment')['id']
    store.add_message(note, 'assistant', {'kind': 'assistant_text', 'text': '杯子里换成了抹茶拿铁'})
    store.update_session(note, archived=True)

    tools = MemoryTools(memory, store, project_id='default', canvas_id=here, session_id=current, run_id='r')
    text = tools.recall('垂耳兔主角 抹茶').text
    assert '[相关的对话]（对话摘要）' in text and '「菜板广告」（另一张画布）：在做菜板广告的分镜' in text
    assert '「改杯子」（画布留言、已归档）' in text and '你说：杯子里换成了抹茶拿铁' in text
    assert '换几个更短的关键词' in tools.recall('火箭发射场').text


def test_summary_input_and_cleanup():
    text = build_input('旧摘要', '开场', [
        {'kind': 'user_message', 'text': '换个色调'},
        {'kind': 'tool_step', 'summary': '修改「图片 1」'},
        {'kind': 'tool_step', 'summary': '失败的步骤', 'isError': True},
        {'kind': 'confirm_resolved', 'approved': False, 'note': '先别生成'},
    ])
    assert '之前的摘要：旧摘要' in text and '（操作）修改「图片 1」' in text and '失败的步骤' not in text
    assert '（用户拒绝了一步操作）：先别生成' in text
    assert clean('\n「在做开场」\n多余的第二行') == '在做开场'
    assert len(clean('长' * 500)) == 120
