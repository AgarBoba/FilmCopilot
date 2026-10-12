"""A model's input rules, in three layers: the guide the agent reads (models/<id>.md), the node
checks (checks/), and the provider's refusal after a failed generation (providers/errors.py)."""
import json

from PIL import Image

from app.checks import check_inputs, validate_checks
from app.credits import Credits
from app.events import EventStore
from app.model_guides import parse_capabilities, parse_guide
from app.models_registry import ModelRegistry, parse_model, registry
from app.providers import errors as provider_errors
from app.providers.base import GenerationRequest, build_inputs
from app.schemas import CommandEnvelope
from app.worker import Worker
from tests.test_canvas_tools import setup, user
from tests.test_worker import FakeProvider

GUIDE = """# Fake Image

一个测试用的模型。

## 擅长
- 画猫
- 画狗

## 不擅长
- 画字

## 输入限制
- 参考图的边长要是 16 的倍数

## 提示词
技能：film-copilot:prompt-craft
- 写清楚主体

## 已知问题
- 暂无
"""


def fake_model(**extra):
    data = {
        'id': 'fake-image', 'label': 'Fake Image', 'kind': 'image', 'provider': 'replicate',
        'providerModel': 'x/fake', 'inputs': {'prompt': 'prompt', 'images': {'field': 'image_input', 'max': 2}},
        'parameters': [],
    }
    data.update(extra)
    return parse_model(data)


def ref(width, height, title='图片 1', kind='image', node='n1', seconds=None):
    return {'kind': kind, 'width': width, 'height': height, 'sourceTitle': title, 'sourceNodeId': node,
            'duration_seconds': seconds}


def add_asset(repository, canvas_id, node_id, path, asset_id, size):
    Image.new('RGB', size, (200, 120, 40)).save(path)
    repository._execute(
        "INSERT INTO assets (id, canvas_id, kind, path, mime_type, width, height) VALUES (?, ?, 'image', ?, 'image/png', ?, ?)",
        (asset_id, canvas_id, str(path), *size))
    repository.update_node(canvas_id, node_id, {'data': {'assetId': asset_id}})


# ------------------------------------------------------------ layer 1: the guide

def test_guide_sections_skill_and_one_line_summary():
    guide = parse_guide(GUIDE)
    assert guide.intro == '一个测试用的模型。'
    assert guide.skill == 'film-copilot:prompt-craft'
    assert guide.missing == ()
    assert guide.summary('擅长') == '画猫；画狗'
    assert '技能' not in guide.summary('提示词')
    assert parse_guide('# X\n## 擅长\n- a\n').missing == ('不擅长', '输入限制', '提示词', '已知问题')


def test_capability_table_rows():
    found = parse_capabilities('| 功能 | 意思 | 使用要点 |\n|---|---|---|\n| omni_reference | 全能参考 | 用 [Image1] |\n')
    assert list(found) == ['omni_reference']
    assert found['omni_reference'].tips == '用 [Image1]'


def test_registry_reads_guides_and_flags_unknown_capabilities(tmp_path):
    (tmp_path / '_capabilities.md').write_text('| 功能 | 意思 | 使用要点 |\n|---|---|---|\n| text_to_image | 文生图 | |\n')
    model = {'id': 'fake-image', 'kind': 'image', 'provider': 'replicate', 'providerModel': 'x/y',
             'inputs': {'prompt': 'prompt'}, 'capabilities': ['text_to_image', 'teleport']}
    (tmp_path / 'fake-image.json').write_text(json.dumps(model))
    (tmp_path / 'fake-image.md').write_text(GUIDE)
    models = ModelRegistry(tmp_path)
    spec = models.get('fake-image')
    assert spec.capabilities == ('text_to_image',)
    assert spec.guide.skill == 'film-copilot:prompt-craft'
    assert any('teleport' in error for error in models.errors)
    assert spec.public()['hasGuide'] is True
    # Editing the guide is picked up without a restart.
    (tmp_path / 'fake-image.md').write_text(GUIDE.replace('画猫', '画鸟'))
    import os
    os.utime(tmp_path / 'fake-image.md', ns=(1, 10**18))
    assert '画鸟' in models.get('fake-image').guide.section('擅长')


def test_shipped_models_have_complete_guides_and_known_capabilities():
    models = registry()
    assert models.errors == []
    for spec in models.all():
        assert spec.guide is not None and spec.guide.missing == (), spec.id
        assert spec.capabilities, spec.id
    assert 'omni_reference' in models.get('seedance-2.0-mini').capabilities


# ------------------------------------------------------------ layer 2: node checks

def test_check_settings_are_validated_with_fix_it_messages():
    assert validate_checks([{'rule': 'side_multiple', 'of': 16}], 'm') == ({'rule': 'side_multiple', 'of': 16},)
    for bad, words in (
        ([{'rule': 'nope'}], '可用的有'),
        ([{'rule': 'side_multiple'}], '缺少 of'),
        ([{'rule': 'aspect_range', 'min': 1, 'colour': 2}], '不认识 colour'),
        ([{'rule': 'aspect_range', 'min': 1, 'target': 'audio'}], 'target'),
    ):
        try:
            validate_checks(bad, 'm')
        except ValueError as error:
            assert words in str(error)
        else:
            raise AssertionError(bad)


def test_an_odd_rule_is_one_line_of_json():
    """「边长要是 16 的倍数」(the gpt-image kind of rule): no new code, just a check entry."""
    model = fake_model(checks=[{'rule': 'side_multiple', 'of': 16}])
    assert check_inputs(model, {'references': [ref(1024, 768)]}) == []
    (problem,) = check_inputs(model, {'references': [ref(1000, 768, '老街')]})
    assert problem.code == 'side_multiple' and problem.severity == 'error'
    assert '「老街」' in problem.message and '16 的倍数' in problem.message
    assert problem.source_node_id == 'n1'


def test_aspect_size_duration_prompt_and_requires_rules():
    model = parse_model({
        'id': 'fake-video', 'kind': 'video', 'provider': 'replicate', 'providerModel': 'x/v',
        'inputs': {'prompt': 'prompt', 'images': {'field': 'images', 'max': 3}, 'videos': {'field': 'videos', 'max': 1}},
        'checks': [
            {'rule': 'aspect_range', 'min': 0.333, 'max': 3},
            {'rule': 'side_range', 'min': 300},
            {'rule': 'duration_range', 'max': 15},
            {'rule': 'prompt_length', 'max': 10},
            {'rule': 'requires', 'images': 1},
        ],
    })
    codes = lambda snapshot: sorted(problem.code for problem in check_inputs(model, snapshot))
    assert codes({'prompt': '短', 'references': [ref(1000, 1000)]}) == []
    assert codes({'prompt': '短', 'references': [ref(400, 2000)]}) == ['aspect_range']
    assert codes({'prompt': '短', 'references': [ref(200, 200)]}) == ['side_range']
    assert codes({'prompt': '短', 'references': [ref(800, 800), ref(640, 360, kind='video', seconds=20)]}) == ['duration_range']
    assert codes({'prompt': '这一句话肯定超过了十个字', 'references': [ref(800, 800)]}) == ['prompt_length']
    assert codes({'prompt': '短', 'references': []}) == ['requires']


def test_built_in_checks_warn_about_extra_references_and_refuse_unsupported_ones():
    model = fake_model()
    problems = check_inputs(model, {'references': [ref(64, 64, f'图 {i}', node=f'n{i}') for i in range(3)]})
    (too_many,) = problems
    assert too_many.severity == 'warning' and '「图 2」' in too_many.message
    no_video = parse_model({'id': 'v', 'kind': 'video', 'provider': 'replicate', 'providerModel': 'x/v',
                            'inputs': {'prompt': 'prompt'}})
    (problem,) = check_inputs(no_video, {'references': [ref(64, 64, kind='video')]})
    assert problem.code == 'unsupported_input' and problem.severity == 'error'


def test_connecting_a_misfit_reference_marks_the_node_and_generation_is_refused_free(repository, tmp_path):
    tools, service, canvas_id = setup(repository)
    source, target = tools.create_nodes([{'type': 'image', 'title': '长条图'}, {'type': 'image', 'prompt': '一只猫'}]).touched
    add_asset(repository, canvas_id, source, tmp_path / 'tall.png', 'tall', (100, 400))  # 1:4, Seedream wants 1:3–3:1

    result = tools.connect(source, target)
    assert '模型检查没通过' in result.text and '「长条图」' in result.text and '1:4' in result.text

    checks = repository.get_snapshot(canvas_id).nodeChecks
    assert checks[target][0]['code'] == 'aspect_range'
    assert '模型检查' in tools.get_canvas(full=True).text
    assert '模型检查没通过' in tools.get_node(target).text

    balance = Credits(repository.database).balance()
    refused = tools.generate([target])
    assert refused.is_error and '没有扣积分' in refused.text
    assert Credits(repository.database).balance() == balance
    assert not [job for job in repository.get_snapshot(canvas_id).jobs if job['target_node_id'] == target]

    tools.disconnect(source, target)
    assert target not in repository.get_snapshot(canvas_id).nodeChecks


def test_checks_rerun_after_a_user_edit_and_on_a_new_picture(repository, tmp_path):
    tools, service, canvas_id = setup(repository)
    source, target = tools.create_nodes([{'type': 'image'}, {'type': 'image', 'prompt': '猫'}]).touched
    tools.connect(source, target)
    assert target not in repository.get_snapshot(canvas_id).nodeChecks
    # A picture lands upstream after the connection was made (like a finished generation).
    add_asset(repository, canvas_id, source, tmp_path / 'wide.png', 'wide', (2000, 400))
    user(service, repository, canvas_id, 'update_node', {'nodeId': target, 'data': {'prompt': '狗'}}, 'u1')
    assert repository.get_snapshot(canvas_id).nodeChecks[target][0]['code'] == 'aspect_range'


def test_get_node_numbers_references_for_omni_models(repository, tmp_path):
    tools, _, canvas_id = setup(repository)
    a, b, video = tools.create_nodes([
        {'type': 'image', 'title': '角色'}, {'type': 'image', 'title': '场景'},
        {'type': 'video', 'prompt': '走路', 'model': 'seedance-2.0-mini'},
    ]).touched
    add_asset(repository, canvas_id, a, tmp_path / 'a.png', 'a', (800, 800))
    add_asset(repository, canvas_id, b, tmp_path / 'b.png', 'b', (1280, 720))
    tools.connect(a, video)
    tools.connect(b, video)
    assert '[Image1]「角色」、[Image2]「场景」' in tools.get_node(video).text


def test_older_endpoints_take_one_field_per_reference_in_connection_order():
    model = parse_model({
        'id': 'old-video', 'kind': 'video', 'provider': 'replicate', 'providerModel': 'x/old',
        'capabilities': ['first_last_frame'],
        'inputs': {'prompt': 'prompt', 'images': {'fields': ['start_image', 'end_image']}},
    })
    assert model.max_images == 2 and model.reference_slots('image') == ['start_image', 'end_image']
    inputs = build_inputs(model, GenerationRequest('p', images=['first.png', 'last.png']), lambda path: f'url:{path}')
    assert inputs['start_image'] == 'url:first.png' and inputs['end_image'] == 'url:last.png'


# ------------------------------------------------------------ the agent's view

def test_list_models_filters_by_capability_and_points_to_the_guide(repository):
    tools, _, _ = setup(repository)
    text = tools.list_models(capability='omni_reference').text
    assert 'seedance-2.0-mini' in text and 'seedream-5-pro' not in text
    assert 'get_model_guide' in text and '擅长：' in text and '节点检查：' in text
    assert tools.list_models(capability='teleport').is_error
    assert '做不了' in tools.list_models(kind='image', capability='first_last_frame').text


def test_model_guide_has_the_doc_capabilities_skill_and_rejections(repository):
    tools, _, canvas_id = setup(repository)
    provider_errors.record(repository.database, 'seedream-5-pro', {'canvas_id': canvas_id},
                           provider_errors.translate('Image width must be divisible by 16'))
    text = tools.get_model_guide('seedream-5-pro').text
    assert '## 输入限制' in text and 'text_to_image：' in text
    assert '先用 Skill 工具加载 film-copilot:prompt-craft' in text
    assert '[最近被模型拒绝]' in text and 'divisible by 16' in text
    assert 'film-copilot:seedance-prompt' in tools.get_model_guide('seedance-2.0-mini').text
    assert tools.get_model_guide('nope').is_error


# ------------------------------------------------------------ layer 3: the provider says no

def test_provider_errors_are_translated():
    assert provider_errors.translate('Input image aspect ratio must be between 0.33 and 3').kind == 'aspect_ratio'
    assert provider_errors.translate('width must be divisible by 16').kind == 'dimension_multiple'
    assert provider_errors.translate('NSFW content detected').kind == 'content_policy'
    other = provider_errors.translate('something odd')
    assert other.kind == 'other' and other.text() == 'something odd'
    assert '原始报错：Input image aspect' in provider_errors.translate('Input image aspect ratio bad').text()


def test_a_refused_generation_is_explained_recorded_and_refunded(repository, tmp_path):
    canvas_id = repository.create_canvas('Worker').canvasId
    service = __import__('app.commands', fromlist=['CanvasCommandService']).CanvasCommandService(
        repository, EventStore(repository.database))
    node = service.execute(canvas_id, CommandEnvelope(
        command='create_node', baseRevision=0, idempotencyKey='n', payload={'nodeType': 'image', 'data': {'prompt': 'x'}},
    )).payload['nodeId']
    balance = Credits(repository.database).balance()
    service.execute(canvas_id, CommandEnvelope(
        command='start_generation', baseRevision=1, idempotencyKey='g', payload={'nodeId': node}))
    provider = FakeProvider()
    provider.fail_with('Image width must be divisible by 16')
    Worker(repository, provider, tmp_path).run_once()
    job = repository.get_snapshot(canvas_id).jobs[-1]
    assert job['status'] == 'failed' and job['error'].startswith('参考图的宽或高不是模型要求的倍数')
    assert Credits(repository.database).balance() == balance
    (rejection,) = provider_errors.recent(repository.database, 'seedream-5-pro')
    assert rejection['kind'] == 'dimension_multiple'


def test_model_guide_api(client):
    guide = client.get('/api/models/seedance-2.0-mini/guide').json()
    assert guide['markdown'].startswith('# Seedance 2.0 Mini')
    assert {'name': 'omni_reference'} .items() <= guide['capabilities'][0].items()
    assert guide['skill'] == 'film-copilot:seedance-prompt' and guide['checks']
    assert client.get('/api/models/nope/guide').status_code == 404
    words = [item['name'] for item in client.get('/api/models/capabilities').json()['capabilities']]
    assert 'omni_reference' in words and 'first_last_frame' in words
    assert client.get('/api/models').json()['models'][0]['capabilities']
