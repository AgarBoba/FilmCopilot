"""What every generation provider adapter implements.

An adapter turns a GenerationRequest for a model (see models_registry.ModelSpec) into a call
to one provider's API, and reports back until there is an output file. To add a provider,
copy providers/_template.py; the steps are in docs/ADDING_MODELS.md.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..models_registry import ModelSpec


@dataclass(slots=True)
class GenerationRequest:
    """One generation, independent of provider: text, reference files, parameters by key."""
    prompt: str
    images: list[Path] = field(default_factory=list)
    videos: list[Path] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PredictionRef:
    id: str


@dataclass(slots=True)
class PredictionStatus:
    id: str
    # "starting" / "processing" while running; finished states are
    # "succeeded", "failed" or "canceled" (the worker keys off these).
    status: str
    outputs: list[Any] = field(default_factory=list)
    error: str | None = None


class GenerationProvider(Protocol):
    def create_prediction(self, model: ModelSpec, request: GenerationRequest) -> PredictionRef:
        ...

    def get_prediction(self, prediction_id: str) -> PredictionStatus:
        ...

    def download_output(self, output: Any, destination: Path) -> Path:
        ...


class ProviderNotConfigured(RuntimeError):
    """The provider's key is missing; the message tells the user which setting to fill in."""


def build_inputs(model: ModelSpec, request: GenerationRequest, attach: Any) -> dict[str, Any]:
    """Provider input fields for a request, using the field names in the model file.

    `attach(path)` turns a local file into whatever the provider accepts (an open file,
    an uploaded URL, a data URI...). Parameters must already be resolved by the model.
    """
    inputs: dict[str, Any] = dict(model.fixed_inputs)
    inputs[model.prompt_field] = request.prompt
    for spec, paths in ((model.image_input, request.images), (model.video_input, request.videos)):
        if not spec or not paths:
            continue
        files = [attach(path) for path in paths[: spec['max']]]
        inputs[spec['field']] = files[0] if spec.get('single') else files
    for parameter in model.parameters:
        if parameter.key in request.parameters:
            inputs[parameter.field] = request.parameters[parameter.key]
    return inputs
