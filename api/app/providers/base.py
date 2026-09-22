from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(slots=True)
class ImageGenerationInput:
    prompt: str
    image_inputs: list[Path]
    size: str
    aspect_ratio: str
    output_format: str
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class VideoGenerationInput:
    prompt: str
    reference_images: list[Path]
    reference_videos: list[Path]
    duration: int
    resolution: str
    aspect_ratio: str
    generate_audio: bool
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PredictionRef:
    id: str


@dataclass(slots=True)
class PredictionStatus:
    id: str
    status: str
    outputs: list[Any] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderOutput:
    location: str


class GenerationProvider(Protocol):
    def create_prediction(self, input_data: ImageGenerationInput | VideoGenerationInput) -> PredictionRef:
        ...

    def get_prediction(self, prediction_id: str) -> PredictionStatus:
        ...

    def download_output(self, output: Any, destination: Path) -> Path:
        ...
