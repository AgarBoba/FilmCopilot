"""The helper scripts colleagues' coding agents run: .env parsing and model drafting."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

from _env import parse_env_file  # noqa: E402
from add_model import draft_from_openapi  # noqa: E402
from app.models_registry import parse_model  # noqa: E402

FIXTURES = Path(__file__).parent / 'fixtures'


def test_env_parsing_reports_broken_lines_without_values(tmp_path):
    env = tmp_path / '.env'
    env.write_text('# comment\nA=1\nexport B="two"\nC=\nsk-ant-continued-part\n\nD=x=y\n', encoding='utf-8')
    values, bad = parse_env_file(env)
    assert values == {'A': '1', 'B': 'two', 'C': '', 'D': 'x=y'}
    assert bad == [5]  # a key folded onto a second line


def test_draft_from_replicate_schema_is_a_valid_model():
    schema = json.loads((FIXTURES / 'replicate_schema_image.json').read_text())
    data, notes = draft_from_openapi('black-forest-labs/flux-kontext-pro', schema, description='Edit images')
    spec = parse_model(data, 'draft')
    assert spec.id == 'flux-kontext-pro' and spec.kind == 'image' and spec.provider == 'replicate'
    assert data['inputs']['images'] == {'field': 'input_image', 'max': 1, 'single': True}
    assert [p.field for p in spec.parameters] == ['aspect_ratio', 'output_format', 'guidance']
    assert spec.parameters[0].default == 'match_input_image'
    assert spec.parameters[2].minimum == 1 and spec.parameters[2].maximum == 10
    assert any('seed' in note for note in notes)


def test_draft_guesses_video_and_maps_reference_arrays():
    schema = {'components': {'schemas': {
        'Input': {'properties': {
            'prompt': {'type': 'string', 'x-order': 0},
            'reference_images': {'type': 'array', 'items': {'type': 'string', 'format': 'uri'}, 'maxItems': 9, 'x-order': 1},
            'reference_videos': {'type': 'array', 'items': {'type': 'string', 'format': 'uri'}, 'x-order': 2},
            'audio': {'type': 'string', 'format': 'uri', 'x-order': 3},
            'duration': {'type': 'integer', 'default': 5, 'minimum': 3, 'maximum': 12, 'x-order': 4},
            'generate_audio': {'type': 'boolean', 'default': True, 'x-order': 5},
        }},
        'Output': {'type': 'string', 'format': 'uri'},
    }}}
    data, notes = draft_from_openapi('someone/cool-video-2', schema)
    parse_model(data, 'draft')
    assert data['kind'] == 'video'
    assert data['inputs']['images'] == {'field': 'reference_images', 'max': 9}
    assert data['inputs']['videos'] == {'field': 'reference_videos', 'max': 4}
    assert [p['key'] for p in data['parameters']] == ['duration', 'generateAudio']
    assert any('audio' in note for note in notes)


def test_draft_needs_a_prompt_field():
    schema = {'components': {'schemas': {'Input': {'properties': {'image': {'type': 'string', 'format': 'uri'}}}}}}
    with pytest.raises(ValueError, match='prompt'):
        draft_from_openapi('a/b', schema)
