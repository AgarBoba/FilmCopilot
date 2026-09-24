"""Replicate adapter: runs any model on replicate.com described by a models/*.json file.

Needs REPLICATE_API_TOKEN. Reference files are sent as open files (the client uploads them).
"""
from contextlib import ExitStack
from pathlib import Path
import shutil
from typing import Any
from urllib.request import urlopen

from ..models_registry import ModelSpec
from .base import GenerationRequest, PredictionRef, PredictionStatus, ProviderNotConfigured, build_inputs

ENV_KEYS = ('REPLICATE_API_TOKEN',)


def from_env() -> 'ReplicateProvider':
    import os
    return ReplicateProvider(os.getenv('REPLICATE_API_TOKEN') or None)


class ReplicateProvider:
    name = 'replicate'

    def __init__(self, api_token: str | None = None, client: Any | None = None) -> None:
        self.api_token = api_token
        self.client = client

    def _get_client(self) -> Any:
        if self.client is None:
            if not self.api_token:
                raise ProviderNotConfigured('没有 REPLICATE_API_TOKEN：在 .env 里填写后重启。')
            import replicate

            self.client = replicate.Client(api_token=self.api_token)
        return self.client

    def create_prediction(self, model: ModelSpec, request: GenerationRequest) -> PredictionRef:
        with ExitStack() as stack:
            inputs = build_inputs(model, request, lambda path: stack.enter_context(Path(path).open('rb')))
            prediction = self._get_client().predictions.create(model=model.provider_model, input=inputs)
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
            shutil.copyfile(Path(str(output)), destination)
        return destination
