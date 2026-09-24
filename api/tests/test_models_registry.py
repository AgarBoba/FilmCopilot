import json
from pathlib import Path

import pytest

from app.models_registry import ModelFileError, ModelRegistry, parse_model, registry
from app.providers.base import GenerationRequest, build_inputs
from app.worker import build_request


def test_bundled_models_load_without_errors():
    models = registry()
    assert models.errors == []
    assert models.default_for('image').id == 'seedream-5-pro'
    assert models.default_for('video').id == 'seedance-2.0-mini'


def test_seedream_request_maps_fields_limits_and_aliases():
    model = registry().get('seedream-5-pro')
    snapshot = {
        'prompt': 'make a poster',
        'parameters': {'size': '1K', 'outputFormat': 'jpg', 'unknown': 1},
        'references': [{'path': f'/tmp/r{i}.png', 'kind': 'image'} for i in range(12)],
    }
    request = build_request(model, snapshot)
    assert len(request.images) == 10
    assert request.warnings == [{'code': 'REFERENCE_LIMIT_TRUNCATED', 'kind': 'image', 'omittedCount': 2}]
    # "jpg" is an alias of "jpeg" (Replicate rejects "jpg" with a 422); defaults fill the rest.
    assert request.parameters == {'size': '1K', 'aspectRatio': 'match_input_image', 'outputFormat': 'jpeg'}
    inputs = build_inputs(model, request, lambda path: f'file:{Path(path).name}')
    assert inputs['prompt'] == 'make a poster'
    assert inputs['image_input'][0] == 'file:r0.png' and len(inputs['image_input']) == 10
    assert inputs['output_format'] == 'jpeg' and inputs['aspect_ratio'] == 'match_input_image'


def test_seedance_request_maps_images_videos_and_types():
    model = registry().get('seedance-2.0-mini')
    request = build_request(model, {
        'prompt': 'animate this',
        'parameters': {'duration': '10', 'generateAudio': False},
        'references': [{'path': '/tmp/a.png', 'kind': 'image'}, {'path': '/tmp/c.mp4', 'kind': 'video'}],
    })
    inputs = build_inputs(model, request, lambda path: str(path))
    assert inputs['duration'] == 10 and inputs['generate_audio'] is False
    assert len(inputs['reference_images']) == 1 and len(inputs['reference_videos']) == 1
    assert model.resolve_parameters({'duration': 7})[1] == ['duration 只能是 5 / 10']


def base_model(**changes):
    data = {
        'id': 'test-model', 'label': 'Test', 'kind': 'image', 'provider': 'replicate',
        'providerModel': 'owner/test', 'inputs': {'prompt': 'prompt', 'images': {'field': 'image', 'max': 1, 'single': True}},
        'parameters': [{'key': 'steps', 'type': 'integer', 'field': 'num_steps', 'default': 20, 'min': 1, 'max': 50}],
        'fixedInputs': {'safety_tolerance': 2},
    }
    data.update(changes)
    return data


def test_single_image_fields_fixed_inputs_and_number_ranges():
    model = parse_model(base_model())
    request = GenerationRequest('x', images=[Path('/a.png'), Path('/b.png')], parameters=model.resolve_parameters({'steps': 30})[0])
    inputs = build_inputs(model, request, lambda path: path.name)
    assert inputs == {'safety_tolerance': 2, 'prompt': 'x', 'image': 'a.png', 'num_steps': 30}
    assert model.resolve_parameters({'steps': 99}) == ({'steps': 20}, ['steps 要在 1 到 50 之间'])
    assert model.resolve_parameters({'steps': 2.5})[1] == ['steps 要是整数']


@pytest.mark.parametrize('changes, message', [
    ({'id': 'Has Space'}, '小写'),
    ({'kind': 'audio'}, 'image 或 video'),
    ({'inputs': {}}, '"prompt"'),
    ({'parameters': [{'key': 'a', 'type': 'enum', 'default': 'x'}]}, 'options'),
    ({'parameters': [{'key': 'a', 'type': 'enum', 'default': 'z', 'options': [{'value': 'x'}]}]}, 'default'),
    ({'parameters': [{'key': 'a', 'type': 'slider', 'default': 1}]}, 'type 只能是'),
])
def test_bad_model_files_explain_what_to_fix(changes, message):
    with pytest.raises(ModelFileError, match=message):
        parse_model(base_model(**changes), 'models/test.json')


def test_registry_reloads_and_reports_errors_per_file(tmp_path):
    models = ModelRegistry(tmp_path)
    (tmp_path / 'a.json').write_text(json.dumps(base_model(default=True)))
    assert models.default_for('image').id == 'test-model'
    (tmp_path / 'b.json').write_text('{ not json')
    (tmp_path / 'c.json').write_text(json.dumps(base_model(id='other', default=True)))
    models.all()
    assert any('b.json' in error and 'JSON' in error for error in models.errors)
    assert any('多个 default' in error for error in models.errors)
    assert models.for_node('image', 'missing').id in ('test-model', 'other')  # unknown id falls back
    assert models.for_node('video', 'test-model') is None  # wrong kind and no video model
