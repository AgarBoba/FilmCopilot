from contextlib import ExitStack
from pathlib import Path
import shutil
from typing import Any
from urllib.request import urlopen

from ..config import resolve_project_path
from .base import (
    GenerationProvider,
    ImageGenerationInput,
    PredictionRef,
    PredictionStatus,
    VideoGenerationInput,
)


SEEDREAM_MODEL = 'bytedance/seedream-5-pro'
SEEDANCE_MODEL = 'bytedance/seedance-2.0-mini'


def _parameters(job_snapshot: dict[str, Any]) -> dict[str, Any]:
    return job_snapshot.get('parameters') or job_snapshot.get('params') or {}


def _references(job_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return job_snapshot.get('references') or job_snapshot.get('assets') or []


def _reference_path(reference: dict[str, Any]) -> Path:
    path = reference.get('path') or reference.get('filePath')
    if not path:
        raise ValueError('generation reference is missing a local path')
    return resolve_project_path(path)


def _reference_kind(reference: dict[str, Any]) -> str:
    return reference.get('kind') or reference.get('asset_kind') or ''


def map_seedream_input(job_snapshot: dict[str, Any]) -> ImageGenerationInput:
    references = [reference for reference in _references(job_snapshot) if _reference_kind(reference) == 'image']
    omitted_count = max(0, len(references) - 10)
    parameters = _parameters(job_snapshot)
    warnings = (
        [{'code': 'REFERENCE_LIMIT_TRUNCATED', 'omittedCount': omitted_count}]
        if omitted_count
        else []
    )
    return ImageGenerationInput(
        prompt=job_snapshot.get('prompt', ''),
        image_inputs=[_reference_path(reference) for reference in references[:10]],
        size=parameters.get('size', '2K'),
        aspect_ratio=parameters.get('aspectRatio', parameters.get('aspect_ratio', 'match_input_image')),
        output_format=(
            'jpg'
            if parameters.get('outputFormat', parameters.get('output_format', 'png')) == 'jpeg'
            else parameters.get('outputFormat', parameters.get('output_format', 'png'))
        ),
        warnings=warnings,
    )


def map_seedance_input(job_snapshot: dict[str, Any]) -> VideoGenerationInput:
    references = _references(job_snapshot)
    images = [reference for reference in references if _reference_kind(reference) == 'image']
    videos = [reference for reference in references if _reference_kind(reference) == 'video']
    parameters = _parameters(job_snapshot)
    warnings: list[dict[str, Any]] = []
    if len(images) > 9:
        warnings.append({'code': 'REFERENCE_LIMIT_TRUNCATED', 'omittedImageCount': len(images) - 9})
        images = images[:9]
    if len(videos) > 3:
        warnings.append({'code': 'REFERENCE_LIMIT_TRUNCATED', 'omittedVideoCount': len(videos) - 3})
        videos = videos[:3]
    return VideoGenerationInput(
        prompt=job_snapshot.get('prompt', ''),
        reference_images=[_reference_path(reference) for reference in images],
        reference_videos=[_reference_path(reference) for reference in videos],
        duration=int(parameters.get('durationSeconds', parameters.get('duration', 5))),
        resolution=parameters.get('resolution', '720p'),
        aspect_ratio=parameters.get('aspectRatio', parameters.get('aspect_ratio', 'adaptive')),
        generate_audio=bool(parameters.get('generateAudio', parameters.get('generate_audio', True))),
        warnings=warnings,
    )


class ReplicateProvider(GenerationProvider):
    def __init__(self, api_token: str | None = None, client: Any | None = None) -> None:
        self.api_token = api_token
        self.client = client

    def _get_client(self) -> Any:
        if self.client is None:
            import replicate

            self.client = replicate.Client(api_token=self.api_token)
        return self.client

    def create_prediction(self, input_data: ImageGenerationInput | VideoGenerationInput) -> PredictionRef:
        model = SEEDREAM_MODEL if isinstance(input_data, ImageGenerationInput) else SEEDANCE_MODEL
        with ExitStack() as stack:
            if isinstance(input_data, ImageGenerationInput):
                image_inputs = [stack.enter_context(path.open('rb')) for path in input_data.image_inputs]
                inputs = {
                    'prompt': input_data.prompt,
                    'image_input': image_inputs,
                    'size': input_data.size,
                    'aspect_ratio': input_data.aspect_ratio,
                    'output_format': input_data.output_format,
                }
            else:
                images = [stack.enter_context(path.open('rb')) for path in input_data.reference_images]
                videos = [stack.enter_context(path.open('rb')) for path in input_data.reference_videos]
                inputs = {
                    'prompt': input_data.prompt,
                    'reference_images': images,
                    'reference_videos': videos,
                    'duration': input_data.duration,
                    'resolution': input_data.resolution,
                    'aspect_ratio': input_data.aspect_ratio,
                    'generate_audio': input_data.generate_audio,
                }
            prediction = self._get_client().predictions.create(model=model, input=inputs)
        return PredictionRef(id=str(prediction.id))

    def get_prediction(self, prediction_id: str) -> PredictionStatus:
        prediction = self._get_client().predictions.get(prediction_id)
        output = prediction.output
        outputs = output if isinstance(output, list) else ([] if output is None else [output])
        return PredictionStatus(
            id=str(prediction.id),
            status=str(prediction.status),
            outputs=outputs,
            error=str(prediction.error) if prediction.error else None,
        )

    def download_output(self, output: Any, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(output, (str, Path)) and str(output).startswith(('http://', 'https://')):
            with urlopen(str(output), timeout=120) as response, destination.open('wb') as file:
                shutil.copyfileobj(response, file)
        else:
            source = Path(str(output))
            shutil.copyfile(source, destination)
        return destination
