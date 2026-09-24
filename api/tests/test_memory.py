import pytest

from app.agent.memory import CONTEXT_BUDGET, MemoryStore, keywords
from app.domain import DomainError


def make(repository):
    return MemoryStore(repository.database)


def test_add_dedupes_and_scopes_project_vs_preference(repository):
    memory = make(repository)
    first, created = memory.add('project', '主角是一只米白色的垂耳兔', 'character', project_id='p1')
    again, created_again = memory.add('project', '  主角是一只米白色的垂耳兔 ', 'character', project_id='p1')
    assert created and not created_again and again['id'] == first['id']
    memory.add('project', '另一个项目的设定', project_id='p2')
    memory.add('preference', '图片默认用 16:9', 'params', project_id='p1')
    listed = memory.list_all('p1')
    assert [m['content'] for m in listed['project']] == ['主角是一只米白色的垂耳兔']
    assert listed['preference'][0]['project_id'] is None  # preferences follow the user everywhere
    assert memory.list_all('p2')['preference'][0]['content'] == '图片默认用 16:9'
    assert memory.add('project', 'x', 'nonsense', project_id='p1')[0]['category'] == 'other'
    with pytest.raises(DomainError):
        memory.add('project', '   ', project_id='p1')


def test_update_keeps_history_and_revert_restores_it(repository):
    memory = make(repository)
    old, _ = memory.add('project', '主角是白兔', 'character', project_id='p1')
    new = memory.supersede(old['id'], '主角是米白色垂耳兔', run_id='r1')
    assert memory.get(old['id'])['status'] == 'superseded' and memory.get(old['id'])['superseded_by'] == new['id']
    assert '#%d' % new['id'] in memory.context_block('p1') and '白兔' not in memory.context_block('p1').replace('垂耳兔', '')
    memory.revert(new['id'])
    assert memory.get(old['id'])['status'] == 'active'
    with pytest.raises(DomainError):
        memory.get(new['id'])


def test_remove_revert_and_undo_run(repository):
    memory = make(repository)
    kept, _ = memory.add('project', '不要出现文字', 'taboo', project_id='p1')
    memory.remove(kept['id'], run_id='r2')
    assert memory.context_block('p1') == ''
    added, _ = memory.add('project', '背景是乡村厨房', 'setting', project_id='p1', run_id='r2')
    assert memory.undo_run('r2') == 2
    block = memory.context_block('p1')
    assert '不要出现文字' in block and '乡村厨房' not in block


def test_user_edit_in_place_and_delete(repository):
    memory = make(repository)
    item, _ = memory.add('preference', '提示词用英文', 'prompt_style')
    edited = memory.edit(item['id'], '提示词用中文')
    assert edited['content'] == '提示词用中文' and edited['source'] == 'user_edited'
    memory.delete(item['id'])
    assert memory.list_all('p1')['preference'] == []


def test_search_works_for_chinese_and_context_stays_within_budget(repository):
    memory = make(repository)
    memory.add('project', '主角是一只米白色的垂耳兔', 'character', project_id='p1')
    memory.add('project', '菜板是深棕色做旧实木', 'setting', project_id='p1')
    assert [m['content'] for m in memory.search('p1', '兔子 垂耳兔')] == ['主角是一只米白色的垂耳兔']
    assert memory.search('p1', '菜板')[0]['category'] == 'setting'
    assert keywords('菜板，广告 兔子') == ['菜板', '广告', '兔子']
    for index in range(80):
        memory.add('project', f'第 {index} 条很长的设定' + '细节' * 20, project_id='p1')
    block = memory.context_block('p1')
    assert len(block) < CONTEXT_BUDGET + 300 and '还有更多' in block
