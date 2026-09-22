from copy import copy
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
from .providers.base import GenerationProvider, PredictionStatus
from .providers.replicate import map_seedance_input, map_seedream_input
from .repositories import CanvasRepository


class Worker:
    def __init__(
        self,
        repository: CanvasRepository,
        provider: GenerationProvider,
        data_dir: Path,
        events: EventStore | None = None,
        poll_interval: float = 0.2,
        max_polls: int = 300,
    ) -> None:
        self.repository = repository
        self.provider = provider
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
            input_data = (
                map_seedream_input(snapshot)
                if snapshot['nodeType'] == 'image'
                else map_seedance_input(snapshot)
            )
            prediction = self.provider.create_prediction(input_data)
            status = self._wait_for_prediction(prediction.id)
            if status.status.lower() in {'failed', 'canceled', 'cancelled'}:
                raise RuntimeError(status.error or f'provider returned {status.status}')
            if not status.outputs:
                raise RuntimeError('provider returned no output')
            output_path = self._download_output(
                status.outputs[0],
                job['id'],
                snapshot['nodeType'],
            )
            asset = self._save_generated_asset(job, output_path, snapshot['nodeType'])
            can_attach = self._can_attach(job, snapshot)
            target_status = 'completed' if can_attach else 'completed_unattached'
            self._complete(job, target_status, asset['id'] if can_attach else None, asset)
        except Exception as error:
            self._transition(job, 'failed', error=str(error))
        return True

    def _wait_for_prediction(self, prediction_id: str) -> PredictionStatus:
        for attempt in range(self.max_polls):
            status = self.provider.get_prediction(prediction_id)
            if status.status.lower() in {'succeeded', 'failed', 'canceled', 'cancelled'}:
                return status
            if attempt + 1 < self.max_polls:
                time.sleep(self.poll_interval)
        return PredictionStatus(
            id=prediction_id,
            status='failed',
            error='provider polling timed out',
        )

    def _download_output(self, output: Any, job_id: str, node_type: str) -> Path:
        suffix = Path(urlparse(str(output)).path).suffix or ('.png' if node_type == 'image' else '.mp4')
        destination = self.data_dir / 'assets' / 'worker' / f'{job_id}{suffix}'
        downloader = getattr(self.provider, 'download_output', None)
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

    def _can_attach(self, job: dict[str, Any], snapshot: dict[str, Any]) -> bool:
        try:
            current = self.repository.generation_snapshot(job['canvas_id'], job['target_node_id'])
        except Exception:
            return False
        return self._stable_snapshot(current) == self._stable_snapshot(snapshot)

    @staticmethod
    def _stable_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
        result = copy(snapshot)
        result.pop('baseCanvasRevision', None)
        return result

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


def main() -> None:
    from .config import Settings
    from .db import Database
    from .providers.replicate import ReplicateProvider

    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    database = Database(settings.database_path)
    database.init_schema()
    repository = CanvasRepository(database)
    worker = Worker(
        repository,
        ReplicateProvider(settings.replicate_api_token),
        settings.data_dir,
    )
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
