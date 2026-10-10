"""What the agent knows about a node's picture without looking at it: a description written the
first time it looked (describe.py), and where the picture came from (provenance.py)."""
import asyncio

from PIL import Image

from app.agent import describe
from app.agent.describe import AssetDescriber
from app.versions import version_source
from tests.test_canvas_tools import setup, user


def add_asset(repository, canvas_id, path, asset_id):
    Image.new('RGB', (64, 32), (236, 120, 40)).save(path)
    repository._execute(
        "INSERT INTO assets (id, canvas_id, kind, path, mime_type, width, height) "
        "VALUES (?, ?, 'image', ?, 'image/png', 64, 32)",
        (asset_id, canvas_id, str(path)),
    )


def generate(repository, canvas_id, node_id, asset_id, node_prompt, notes=(), model='seedream-5-pro',
             parameters=None, status='completed'):
    """What a finished generation leaves behind: a job with its request, and a version pointing at it."""
    prompt = '\n\n'.join([*notes, node_prompt])
    request = {
        'targetNodeId': node_id, 'nodePrompt': node_prompt, 'prompt': prompt, 'model': model,
        'notePrompts': [{'nodeId': f'note{i}', 'title': '', 'text': text} for i, text in enumerate(notes)],
        'parameters': parameters or {'size': '2K', 'aspectRatio': 'match_input_image', 'outputFormat': 'png'},
        'references': [],
    }
    job_id = repository.create_generation_job(canvas_id, node_id, 'replicate:x', request, {})
    repository.update_generation_job(job_id, status, output_asset_id=asset_id if status == 'completed' else None)
    if status == 'completed':
        with version_source('generated', job_id=job_id, prompt=prompt, parameters=request['parameters'], model=model):
            repository.update_node(canvas_id, node_id, {'data': {'assetId': asset_id}})
    return job_id


def image_node(tools, prompt):
    (node,) = tools.create_nodes([{'type': 'image', 'prompt': prompt}]).touched
    return node


def line_of(text, node_id):
    return next(line for line in text.splitlines() if f'[{node_id}]' in line)


# ------------------------------------------------------------ descriptions

def test_first_view_describes_in_background_and_later_reads_show_it(repository, tmp_path):
    tools, _, canvas_id = setup(repository)
    node = image_node(tools, '一只兔子')
    add_asset(repository, canvas_id, tmp_path / 'a.png', 'a1')
    generate(repository, canvas_id, node, 'a1', '一只兔子')
    calls = []

    async def fake(kind, images):
        calls.append((kind, len(images)))
        return '「雪地里一只白兔子侧身蹲着，冷色调，背景虚化，远处有一排松树和一座木屋，傍晚的天光把雪照成淡蓝色」'

    tools.describer = AssetDescriber(repository.database, fake)
    other = image_node(tools, '一只猫')
    tools.get_canvas()  # the agent's first look, before the description exists

    async def run():
        assert not tools.view_asset(node).is_error
        tools.view_asset(node)  # a second look while the first description runs: not described twice
        await tools.describer.wait()
        tools.view_asset(node)  # already described: not again
        await tools.describer.wait()

    asyncio.run(run())
    assert calls == [('image', 1)]
    stored = describe.load(repository.database, 'a1')
    assert stored.startswith('雪地里一只白兔子') and '「' not in stored

    again = tools.get_canvas().text  # later looks only list what changed: the new description counts
    assert '[新增或有变化]' in again and f'[{other}]' not in again
    canvas_line = line_of(again, node)
    assert '画面：雪地里一只白兔子' in canvas_line and canvas_line.count('…') == 1  # preview only
    assert f'画面描述：{stored}' in tools.get_node(node).text  # in full


def test_failed_description_stores_nothing_and_the_next_view_retries(repository, tmp_path):
    tools, _, canvas_id = setup(repository)
    node = image_node(tools, '一只兔子')
    add_asset(repository, canvas_id, tmp_path / 'a.png', 'a1')
    generate(repository, canvas_id, node, 'a1', '一只兔子')
    answers = [RuntimeError('overloaded'), '一只白兔子']

    async def flaky(kind, images):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    tools.describer = AssetDescriber(repository.database, flaky)

    async def run():
        assert not tools.view_asset(node).is_error  # the tool call itself never fails
        await tools.describer.wait()
        assert describe.load(repository.database, 'a1') == ''
        tools.view_asset(node)
        await tools.describer.wait()

    asyncio.run(run())
    assert describe.load(repository.database, 'a1') == '一只白兔子'
    assert '画面描述' not in tools.get_node(image_node(tools, '空的')).text


# --------------------------------------------------------------- provenance

def test_settings_matching_the_picture_add_no_hint(repository, tmp_path):
    tools, _, canvas_id = setup(repository)
    node = image_node(tools, '一只兔子')
    add_asset(repository, canvas_id, tmp_path / 'a.png', 'a1')
    # Connected notes go in front of the prompt that was sent; only the node's own part counts.
    generate(repository, canvas_id, node, 'a1', '一只兔子', notes=['水彩风格'])
    assert '画面还是旧的' not in tools.get_canvas().text
    detail = tools.get_node(node).text
    assert '画面来源：生成' in detail and '注意' not in detail


def test_edited_prompt_after_generating_is_flagged_with_what_the_picture_was_made_from(repository, tmp_path):
    tools, service, canvas_id = setup(repository)
    node = image_node(tools, '一只兔子')
    add_asset(repository, canvas_id, tmp_path / 'a.png', 'a1')
    generate(repository, canvas_id, node, 'a1', '一只兔子')
    user(service, repository, canvas_id, 'update_node', {'nodeId': node, 'data': {'prompt': '一只狐狸'}}, 'u1')

    assert 'Prompt改过，画面还是旧的' in line_of(tools.get_canvas().text, node)
    detail = tools.get_node(node).text
    assert 'Prompt：一只狐狸' in detail  # the setting now
    assert '注意：Prompt改过，画面还是旧的' in detail and '生成这张画面时用的是——Prompt：一只兔子' in detail


def test_changed_parameters_and_models_are_flagged(repository, tmp_path):
    tools, service, canvas_id = setup(repository)
    node = image_node(tools, '一只兔子')
    add_asset(repository, canvas_id, tmp_path / 'a.png', 'a1')
    generate(repository, canvas_id, node, 'a1', '一只兔子')
    user(service, repository, canvas_id, 'update_node',
         {'nodeId': node, 'data': {'parameters': {'aspectRatio': '16:9'}}}, 'u1')
    assert '参数改过，画面还是旧的' in line_of(tools.get_canvas().text, node)
    assert "参数：{'size': '2K', 'aspectRatio': 'match_input_image'" in tools.get_node(node).text

    other = image_node(tools, '一只猫')
    add_asset(repository, canvas_id, tmp_path / 'b.png', 'b1')
    generate(repository, canvas_id, other, 'b1', '一只猫', model='retired-model')
    assert '模型改过，画面还是旧的' in line_of(tools.get_canvas().text, other)
    assert '模型：retired-model（已下线）' in tools.get_node(other).text


def test_uploaded_pictures_say_so_and_running_generations_are_not_flagged(repository, tmp_path):
    tools, service, canvas_id = setup(repository)
    node = image_node(tools, '改成水彩风格')
    user(service, repository, canvas_id, 'attach_asset', {'nodeId': node, 'assetId': 'up1'}, 'u1')
    assert '画面是上传的' in line_of(tools.get_canvas().text, node)

    busy = image_node(tools, '一只兔子')
    add_asset(repository, canvas_id, tmp_path / 'a.png', 'a1')
    generate(repository, canvas_id, busy, 'a1', '一只兔子')
    user(service, repository, canvas_id, 'update_node', {'nodeId': busy, 'data': {'prompt': '一只狐狸'}}, 'u2')
    running = generate(repository, canvas_id, busy, None, '一只狐狸', status='running')  # the new picture is on its way
    repository._execute("UPDATE generation_jobs SET created_at = '2999-01-01' WHERE id = ?", (running,))  # newest
    assert '画面还是旧的' not in line_of(tools.get_canvas().text, busy)
    assert '注意' not in tools.get_node(busy).text
