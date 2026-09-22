from pathlib import Path

from app.commands import CanvasCommandService
from app.events import EventStore
from app.providers.base import PredictionRef, PredictionStatus
from app.repositories import CanvasRepository
from app.schemas import CommandEnvelope
from app.worker import Worker


class FakeProvider:
    def __init__(self, output: Path | None = None):
        self.output = output
        self.received_prompt = None
        self.failure = None

    def fail_with(self, message: str):
        self.failure = message

    def create_prediction(self, input_data):
        self.received_prompt = input_data.prompt
        return PredictionRef('prediction-1')

    def get_prediction(self, prediction_id: str):
        if self.failure:
            return PredictionStatus(prediction_id, 'failed', error=self.failure)
        return PredictionStatus(prediction_id, 'succeeded', outputs=[self.output])

    def download_output(self, output, destination: Path):
        destination.write_bytes(Path(output).read_bytes())
        return destination


def create_job(repository: CanvasRepository, prompt: str = 'original') -> str:
    canvas = repository.create_canvas('Worker')
    events = EventStore(repository.database)
    service = CanvasCommandService(repository, events)
    result = service.execute(
        canvas.canvasId,
        CommandEnvelope(
            command='create_node',
            baseRevision=0,
            idempotencyKey='node-1',
            payload={'nodeType': 'image', 'data': {'prompt': prompt}},
        ),
    )
    node_id = result.payload['nodeId']
    result = service.execute(
        canvas.canvasId,
        CommandEnvelope(
            command='start_generation',
            baseRevision=1,
            idempotencyKey='job-1',
            payload={'nodeId': node_id},
        ),
    )
    return result.payload['jobId']


def update_node_prompt(repository: CanvasRepository, job_id: str, prompt: str):
    job = repository.get_generation_job(job_id)
    events = EventStore(repository.database)
    service = CanvasCommandService(repository, events)
    current = repository.get_snapshot(job['canvas_id'])
    service.execute(
        job['canvas_id'],
        CommandEnvelope(
            command='update_node',
            baseRevision=current.revision,
            idempotencyKey='update-prompt',
            payload={'nodeId': job['target_node_id'], 'data': {'prompt': prompt}},
        ),
    )


def test_worker_uses_generation_input_snapshot(repository, tmp_path):
    output = tmp_path / 'output.png'
    output.write_bytes(b'not-a-real-image')
    fake_provider = FakeProvider(output)
    job_id = create_job(repository, prompt='original')
    update_node_prompt(repository, job_id, 'changed-after-submit')
    Worker(repository, fake_provider, tmp_path).run_once()
    assert fake_provider.received_prompt == 'original'


def test_provider_failure_marks_job_failed(repository, tmp_path):
    fake_provider = FakeProvider()
    fake_provider.fail_with('provider rejected input')
    job_id = create_job(repository)
    Worker(repository, fake_provider, tmp_path).run_once()
    job = repository.get_generation_job(job_id)
    assert job['status'] == 'failed'
    assert job['error'] == 'provider rejected input'
