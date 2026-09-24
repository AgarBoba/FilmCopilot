import json
from pathlib import Path
import signal
import time
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from .db import Database
from .events import EventStore
from .media_metadata import read_image_metadata, read_video_metadata
from .models_registry import ModelRegistry, ModelSpec, registry as default_registry
from .providers.base import GenerationProvider, GenerationRequest, PredictionStatus
from .repositories import CanvasRepository
from .config import resolve_project_path


class Worker:
    def __init__(
        self,
        repository: CanvasRepository,
        provider: GenerationProvider | None,
        data_dir: Path,
        events: EventStore | None = None,
        poll_interval: float = 0.2,
        max_polls: int = 300,
        models: ModelRegistry | None = None,
    ) -> None:
        """`provider`: one adapter for every model (tests), or None to pick each model's
        own adapter by its "provider" name (providers.get_provider)."""
        self.repository = repository
        self.provider = provider
        self.models = models or default_registry()
        self.data_dir = data_dir
        self.events = events or EventStore(repository.database)
        self.poll_interval = poll_interval
        self.max_polls = max_polls

    def run_once(self) -> bool:
        job = self.repository.claim_next_generation_job()
        if job is None:
            return False
        self._transition(job, 'running')
        try:
            snapshot = json.loads(job['request_json'])
            model = self.models.for_node(snapshot['nodeType'], snapshot.get('model'))
            if model is None:
                raise RuntimeError(f"没有可用的{'图片' if snapshot['nodeType'] == 'image' else '视频'}模型：检查 models/ 目录")
            provider = self._provider_for(model)
            prediction = provider.create_prediction(model, build_request(model, snapshot))
            status = self._wait_for_prediction(prediction.id, provider)
            if status.status.lower() in {'failed', 'canceled', 'cancelled'}:
                raise RuntimeError(status.error or f'provider returned {status.status}')
            if not status.outputs:
                raise RuntimeError('provider returned no output')
            output_path = self._download_output(
                status.outputs[0],
                job['id'],
                snapshot['nodeType'],
                provider,
            )
            asset = self._save_generated_asset(job, output_path, snapshot['nodeType'])
            # Results always go onto their node; later upstream edits are shown as an
            # "上游有更新" badge instead (see upstream.py). Only a deleted node can't take it.
            can_attach = self._target_exists(job)
            target_status = 'completed' if can_attach else 'completed_unattached'
            self._complete(job, target_status, asset['id'] if can_attach else None, asset)
        except Exception as error:
            self._transition(job, 'failed', error=str(error))
        return True

    def _provider_for(self, model: ModelSpec) -> GenerationProvider:
        if self.provider is not None:
            return self.provider
        from .providers import get_provider
        return get_provider(model.provider)

    def _wait_for_prediction(self, prediction_id: str, provider: GenerationProvider | None = None) -> PredictionStatus:
        provider = provider or self.provider
        for attempt in range(self.max_polls):
            status = provider.get_prediction(prediction_id)
            if status.status.lower() in {'succeeded', 'failed', 'canceled', 'cancelled'}:
                return status
            if attempt + 1 < self.max_polls:
                time.sleep(self.poll_interval)
        return PredictionStatus(
            id=prediction_id,
            status='failed',
            error='provider polling timed out',
        )

    def _download_output(self, output: Any, job_id: str, node_type: str, provider: Any = None) -> Path:
        suffix = Path(urlparse(str(output)).path).suffix or ('.png' if node_type == 'image' else '.mp4')
        destination = self.data_dir / 'assets' / 'worker' / f'{job_id}{suffix}'
        downloader = getattr(provider or self.provider, 'download_output', None)
        if callable(downloader):
            return downloader(output, destination)
        if isinstance(output, Path):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(output.read_bytes())
            return destination
        raise RuntimeError('generation provider does not support downloading output')

    def _save_generated_asset(self, job: dict[str, Any], path: Path, node_type: str) -> dict[str, Any]:
        import hashlib

        metadata = (
            read_image_metadata(path)
            if node_type == 'image'
            else read_video_metadata(path)
        )
        asset = {
            'id': str(uuid4()),
            'canvas_id': job['canvas_id'],
            'kind': node_type,
            'path': str(path),
            'original_name': path.name,
            'mime_type': metadata.mime_type,
            'width': metadata.width,
            'height': metadata.height,
            'duration_seconds': metadata.duration_seconds,
            'checksum': hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        with self.repository.transaction():
            self.repository.insert_asset(asset)
        return asset

    def _target_exists(self, job: dict[str, Any]) -> bool:
        try:
            self.repository.node_snapshot(job['canvas_id'], job['target_node_id'])
        except Exception:
            return False
        return True

    def _complete(
        self,
        job: dict[str, Any],
        status: str,
        output_asset_id: str | None,
        asset: dict[str, Any],
    ) -> None:
        with self.repository.transaction():
            if status == 'completed':
                node = self.repository.node_snapshot(job['canvas_id'], job['target_node_id'])
                self.repository.update_node(
                    job['canvas_id'],
                    job['target_node_id'],
                    {'data': {**node['data'], 'assetId': asset['id']}},
                )
            self.repository.update_generation_job(job['id'], status, output_asset_id=output_asset_id)
            revision = self.repository.bump_revision(job['canvas_id'])
            self.events.append(
                job['canvas_id'],
                revision,
                f'generation.{status}',
                {'jobId': job['id'], 'assetId': asset['id']},
            )

    def _transition(self, job: dict[str, Any], status: str, error: str | None = None) -> None:
        with self.repository.transaction():
            self.repository.update_generation_job(job['id'], status, error=error)
            revision = self.repository.bump_revision(job['canvas_id'])
            payload = {'jobId': job['id'], 'status': status}
            if error:
                payload['error'] = error
            self.events.append(job['canvas_id'], revision, f'generation.{status}', payload)


def build_request(model: ModelSpec, snapshot: dict[str, Any]) -> GenerationRequest:
    """Generation snapshot -> provider-neutral request for this model (refs trimmed to its limits)."""
    references = snapshot.get('references') or []
    images = [ref for ref in references if (ref.get('kind') or ref.get('asset_kind')) == 'image']
    videos = [ref for ref in references if (ref.get('kind') or ref.get('asset_kind')) == 'video']
    warnings: list[dict[str, Any]] = []
    for name, items, limit in (('image', images, model.max_images), ('video', videos, model.max_videos)):
        if len(items) > limit:
            warnings.append({'code': 'REFERENCE_LIMIT_TRUNCATED', 'kind': name, 'omittedCount': len(items) - limit})
    parameters, _ = model.resolve_parameters(snapshot.get('parameters'))

    def path_of(reference: dict[str, Any]) -> Path:
        value = reference.get('path') or reference.get('filePath')
        if not value:
            raise ValueError('generation reference is missing a local path')
        return resolve_project_path(value)

    return GenerationRequest(
        prompt=snapshot.get('prompt', ''),
        images=[path_of(ref) for ref in images[:model.max_images]],
        videos=[path_of(ref) for ref in videos[:model.max_videos]],
        parameters=parameters,
        warnings=warnings,
    )


def main() -> None:
    from .config import Settings
    from .db import Database

    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    database = Database(settings.database_path)
    database.init_schema()
    repository = CanvasRepository(database)
    # Each model picks its own provider. Poll every 2 s for up to 30 min: video models often
    # take several minutes (the 0.2 s x 300 defaults are for tests and would give up after 60 s).
    worker = Worker(repository, None, settings.data_dir, poll_interval=2.0, max_polls=900)
    running = True

    def stop(*_args: Any) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while running:
        if not worker.run_once():
            time.sleep(1)


if __name__ == '__main__':
    main()
