"""Skills, built-in tools (web, task list) and how they show up in the panel."""
import asyncio

import pytest

from app.agent import skills
from app.agent.builtin_events import BuiltinToolTracker, parse_search_links
from app.agent.permissions import RunState, decide
from app.domain import DomainError

from tests.agent_fakes import FakeFactory
from tests.test_agent_runtime import finish, make_service


def test_builtin_skills_are_found_with_labels():
    found = {skill.id: skill for skill in skills.discover()}
    for name, label in [('storyboard', '分镜拆解'), ('prompt-craft', '写生成提示词'),
                        ('canvas-layout', '整理画布'), ('review', '点评作品')]:
        skill = found[f'film-copilot:{name}']
        assert skill.label == label and skill.source == 'builtin' and skill.description


def test_user_skills_folder_is_a_plugin_and_its_skills_are_listed():
    folder = skills.user_dir()
    skills.plugin_dirs()  # creates the skeleton
    assert (folder / '.claude-plugin' / 'plugin.json').exists()
    (folder / 'skills' / 'opening-shot').mkdir(parents=True)
    (folder / 'skills' / 'opening-shot' / 'SKILL.md').write_text(
        '---\nname: opening-shot\ndescription: 开场镜头\n---\n# 我的开场\n做法\n', encoding='utf-8')
    (folder / 'skills' / 'Bad Name').mkdir()
    (folder / 'skills' / 'Bad Name' / 'SKILL.md').write_text('---\nname: Bad Name\n---\n', encoding='utf-8')
    mine = [skill for skill in skills.discover() if skill.source == 'user']
    assert [(skill.id, skill.label) for skill in mine] == [('my-skills:opening-shot', '我的开场')]


@pytest.mark.parametrize('url, ok', [
    ('https://www.example.com/a', True),
    ('http://8.8.8.8/x', True),
    ('http://localhost:8000/api/memories', False),
    ('http://127.0.0.1:8000/', False),
    ('http://192.168.1.5/', False),
    ('http://[::1]/', False),
    ('http://printer.local/', False),
    ('file:///Users/me/.env', False),
    ('ftp://example.com/', False),
])
def test_web_fetch_reads_public_pages_only(url, ok):
    assert skills.url_allowed(url)[0] is ok
    assert decide('WebFetch', {'url': url}, 'confirm_all', RunState())[0] == ('allow' if ok else 'deny')


def test_safe_builtins_never_need_confirmation_and_others_are_denied():
    for name in ('Skill', 'WebSearch', 'TaskCreate', 'TaskUpdate', 'TaskList', 'TaskGet'):
        assert decide(name, {}, 'confirm_all', RunState())[0] == 'allow'
    for name in ('Bash', 'Read', 'Write', 'Task', 'TaskStop'):
        assert decide(name, {}, 'auto', RunState())[0] == 'deny'


def test_search_links_are_parsed_from_the_result():
    text = ('Web search results for query: "王家卫 色调"\n\nLinks: [{"title": "王家卫电影的色彩", '
            '"url": "https://a.example/1"}, {"title": "Ashes", "url": "https://b.example/2"}]\n\nSummary...')
    assert parse_search_links(text) == [
        {'title': '王家卫电影的色彩', 'url': 'https://a.example/1'},
        {'title': 'Ashes', 'url': 'https://b.example/2'},
    ]
    assert parse_search_links('see https://c.example/x and https://c.example/x') == [
        {'title': 'https://c.example/x', 'url': 'https://c.example/x'}]


def test_task_list_is_tracked_across_create_and_update():
    tracker = BuiltinToolTracker()
    tracker.on_tool_use('t1', 'TaskCreate', {'subject': '写分镜表'})
    tracker.on_tool_result('t1', 'Task #1 created successfully: 写分镜表', False)
    tracker.on_tool_use('t2', 'TaskCreate', {'subject': '建节点'})
    tracker.on_tool_result('t2', [{'type': 'text', 'text': 'Task #2 created successfully'}], False)
    tracker.on_tool_use('t3', 'TaskUpdate', {'taskId': '1', 'status': 'completed'})
    ((kind, payload),) = tracker.on_tool_result('t3', 'Updated task #1 status', False)
    assert kind == 'tasks'
    assert payload['items'] == [{'id': '1', 'subject': '写分镜表', 'status': 'completed'},
                                {'id': '2', 'subject': '建节点', 'status': 'pending'}]


def test_a_run_shows_skill_search_and_tasks_in_the_panel(repository):
    factory = FakeFactory([
        ('builtin', 'Skill', {'skill': 'film-copilot:storyboard'}, 'Launching skill: film-copilot:storyboard'),
        ('builtin', 'WebSearch', {'query': '王家卫 色调'},
         'Links: [{"title": "色彩分析", "url": "https://a.example/1"}]'),
        ('builtin', 'WebFetch', {'url': 'http://localhost:8000/api/memories'}, 'should not run'),
        ('builtin', 'TaskCreate', {'subject': '写分镜表'}, 'Task #1 created successfully: 写分镜表'),
        ('text', '好了'),
    ])
    service, store, _, session_id = make_service(repository, factory)

    async def scenario():
        await service.send_message(session_id, '拆个分镜')
        await finish(service, session_id)

    asyncio.run(scenario())
    events = {m['content']['kind']: m['content'] for m in store.list_messages(session_id)}
    assert events['skill_used'] == {'kind': 'skill_used', 'skill': 'film-copilot:storyboard', 'label': '分镜拆解'}
    assert events['web_search']['links'] == [{'title': '色彩分析', 'url': 'https://a.example/1'}]
    assert events['web_fetch']['isError'] is True
    assert events['tasks']['items'] == [{'id': '1', 'subject': '写分镜表', 'status': 'pending'}]
    assert any('本机或局域网' in denial for denial in factory.clients[0].denials)


def test_picking_a_skill_tells_the_agent_to_use_it(repository):
    factory = FakeFactory([('text', '好')])
    service, store, _, session_id = make_service(repository, factory)

    async def scenario():
        await service.send_message(session_id, '', skill='film-copilot:review')
        await finish(service, session_id)

    asyncio.run(scenario())
    prompt = factory.clients[0].prompts[0]
    assert '[用户指定的技能]' in prompt and 'film-copilot:review' in prompt
    (user,) = [m['content'] for m in store.list_messages(session_id) if m['content']['kind'] == 'user_message']
    assert user['skill'] == {'id': 'film-copilot:review', 'label': '点评作品'} and user['text'] == '用「点评作品」'

    with pytest.raises(DomainError):
        asyncio.run(service.send_message(session_id, 'x', skill='film-copilot:nope'))


def test_a_new_skill_reconnects_the_client_keeping_the_conversation(repository):
    factory = FakeFactory([('text', '一')], [('text', '二')])
    service, _, _, session_id = make_service(repository, factory)

    async def turn(text):
        await service.send_message(session_id, text)
        await finish(service, session_id)

    asyncio.run(turn('a'))
    folder = skills.user_dir() / 'skills' / 'x-shot'
    folder.mkdir(parents=True)
    (folder / 'SKILL.md').write_text('---\nname: x-shot\ndescription: d\n---\n# X\n', encoding='utf-8')
    asyncio.run(turn('b'))
    assert len(factory.clients) == 2
    assert 'my-skills:x-shot' in factory.clients[1].options.skills
    assert factory.clients[1].options.resume == 'sdk-session-1'


def test_skills_endpoint_lists_skills(client):
    data = client.get('/api/agent/skills').json()
    assert [s['id'] for s in data['skills']][:1] == ['film-copilot:storyboard']
    assert {'id', 'name', 'label', 'description', 'source'} <= set(data['skills'][0])
