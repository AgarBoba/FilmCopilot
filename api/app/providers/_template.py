"""TEMPLATE for a new provider adapter. Copy it, don't import it.

    cp api/app/providers/_template.py api/app/providers/<name>.py

<name> is what model files put in "provider" (lowercase letters, digits, underscores).
Then fill in the TODOs below, add the key names to .env.example, write a models/*.json file
for each model, and check with `python scripts/check_model.py <model-id>`.
Full steps: docs/ADDING_MODELS.md.

Most hosted APIs work like this: submit a job -> get an id -> poll until done -> download a
file URL. If the API instead answers synchronously with the file, do the work in
create_prediction, keep the result in self._done[id], and have get_prediction return it.

Rules:
- Read keys only from the environment (dev.sh loads .env). Never print or log them, and
  never put them into error messages.
- Raise ProviderNotConfigured (with the setting's name) when a key is missing.
- Keep error messages short and useful: they are shown on the node in the canvas.
"""
import base64
import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx

from ..models_registry import ModelSpec
from .base import GenerationRequest, PredictionRef, PredictionStatus, ProviderNotConfigured, build_inputs

# TODO: the .env settings this adapter needs. The canvas and scripts/doctor.py use this
# list to tell the user what's missing (by name only).
ENV_KEYS = ('EXAMPLE_API_KEY',)
BASE_URL = 'https://api.example.com/v1'  # TODO


def from_env() -> 'ExampleProvider':
    return ExampleProvider(os.getenv('EXAMPLE_API_KEY') or None)


def data_uri(path: Path) -> str:
    """A local file as a data: URI, for APIs that accept those instead of uploads."""
    mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    return f'data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode()}'


class ExampleProvider:  # TODO: rename
    name = 'example'  # TODO: same as the file name

    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key

    def _client(self) -> httpx.Client:
        if not self.api_key:
            raise ProviderNotConfigured('没有 EXAMPLE_API_KEY：在 .env 里填写后重启。')  # TODO
        return httpx.Client(
            base_url=BASE_URL,
            headers={'Authorization': f'Bearer {self.api_key}'},  # TODO: the API's auth header
            timeout=120,
        )

    def create_prediction(self, model: ModelSpec, request: GenerationRequest) -> PredictionRef:
        # build_inputs maps prompt / reference files / parameters to the field names in the
        # model file. `attach` turns a local file into what the API accepts: here a data URI;
        # some APIs want an upload first (do it here and return the uploaded URL).
        inputs: dict[str, Any] = build_inputs(model, request, data_uri)
        with self._client() as client:
            # TODO: the submit call. model.provider_model is the model's name on this API.
            response = client.post(f'/models/{model.provider_model}/jobs', json={'input': inputs})
            _raise_for_status(response)
            return PredictionRef(id=str(response.json()['id']))  # TODO: where the job id is

    def get_prediction(self, prediction_id: str) -> PredictionStatus:
        with self._client() as client:
            response = client.get(f'/jobs/{prediction_id}')  # TODO
            _raise_for_status(response)
            data = response.json()
        # TODO: map the API's states to: starting / processing / succeeded / failed / canceled
        status = {'queued': 'starting', 'running': 'processing', 'done': 'succeeded',
                  'error': 'failed'}.get(str(data.get('status')), str(data.get('status')))
        outputs = data.get('output') or []  # TODO: list of result file URLs
        if isinstance(outputs, str):
            outputs = [outputs]
        return PredictionStatus(id=prediction_id, status=status, outputs=outputs, error=data.get('error'))

    def download_output(self, output: Any, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Result URLs are usually public / pre-signed, so no auth header here. If the API
        # needs one, use self._client() instead.
        with httpx.stream('GET', str(output), timeout=300, follow_redirects=True) as response:
            _raise_for_status(response)
            with destination.open('wb') as file:
                for chunk in response.iter_bytes():
                    file.write(chunk)
        return destination


def _raise_for_status(response: httpx.Response) -> None:
    """An error the user can read, without echoing request headers (they hold the key)."""
    if response.is_success:
        return
    try:
        response.read()
        detail = response.text[:300]
    except Exception:  # streaming responses may not have a body
        detail = ''
    raise RuntimeError(f'provider 返回 {response.status_code}: {detail}'.strip())

