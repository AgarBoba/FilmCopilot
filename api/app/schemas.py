from typing import Any, Literal

from pydantic import BaseModel, Field

from .domain import NodeType


class CanvasNodeSchema(BaseModel):
    id: str
    nodeType: NodeType
    x: float
    y: float
    width: float | None = None
    height: float | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class CanvasEdgeSchema(BaseModel):
    id: str
    source: str
    target: str


class CanvasViewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = 1


class CanvasSnapshot(BaseModel):
    canvasId: str
    name: str
    revision: int
    nodes: list[CanvasNodeSchema] = Field(default_factory=list)
    edges: list[CanvasEdgeSchema] = Field(default_factory=list)
    viewport: CanvasViewport = Field(default_factory=CanvasViewport)
    assets: list[dict[str, Any]] = Field(default_factory=list)
    jobs: list[dict[str, Any]] = Field(default_factory=list)


class CommandEnvelope(BaseModel):
    command: str
    baseRevision: int
    idempotencyKey: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CommandResult(BaseModel):
    revision: int
    command: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CanvasEvent(BaseModel):
    id: int
    canvasId: str
    revision: int
    eventType: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AssetRecord(BaseModel):
    id: str
    canvasId: str | None = None
    kind: Literal['image', 'video']
    path: str
    originalName: str
    mimeType: str
    width: int | None = None
    height: int | None = None
    durationSeconds: float | None = None
    checksum: str


class CreateCanvasRequest(BaseModel):
    name: str = 'Untitled canvas'
    canvasId: str | None = None
