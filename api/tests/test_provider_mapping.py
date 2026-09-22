from pathlib import Path

from app.providers.replicate import map_seedance_input, map_seedream_input


def seedream_job_with_references(count: int) -> dict:
    return {
        'prompt': 'make a poster',
        'nodeType': 'image',
        'parameters': {
            'size': '2K',
            'aspectRatio': 'match_input_image',
            'outputFormat': 'png',
        },
        'references': [
            {'path': f'/tmp/reference-{index}.png', 'kind': 'image'}
            for index in range(count)
        ],
    }


def test_seedream_maps_prompt_parameters_and_all_reference_images():
    mapped = map_seedream_input(seedream_job_with_references(count=3))
    assert mapped.prompt == 'make a poster'
    assert len(mapped.image_inputs) == 3
    assert mapped.size == '2K'
    assert mapped.aspect_ratio == 'match_input_image'
    assert mapped.output_format == 'png'


def test_seedream_maps_first_ten_references_with_warning():
    mapped = map_seedream_input(seedream_job_with_references(count=12))
    assert len(mapped.image_inputs) == 10
    assert mapped.warnings == [{'code': 'REFERENCE_LIMIT_TRUNCATED', 'omittedCount': 2}]


def test_seedance_maps_image_and_video_references():
    mapped = map_seedance_input(
        {
            'prompt': 'animate this',
            'nodeType': 'video',
            'parameters': {
                'durationSeconds': 5,
                'resolution': '720p',
                'aspectRatio': 'adaptive',
                'generateAudio': True,
            },
            'references': [
                {'path': '/tmp/a.png', 'kind': 'image'},
                {'path': '/tmp/b.png', 'kind': 'image'},
                {'path': '/tmp/c.mp4', 'kind': 'video'},
            ],
        }
    )
    assert len(mapped.reference_images) == 2
    assert len(mapped.reference_videos) == 1
    assert mapped.duration == 5
    assert mapped.resolution == '720p'
    assert mapped.aspect_ratio == 'adaptive'
    assert mapped.generate_audio is True
