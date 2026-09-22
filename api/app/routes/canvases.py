from fastapi import APIRouter, Request, status

from ..commands import CanvasCommandService
from ..repositories import CanvasRepository
from ..schemas import CanvasSnapshot, CommandEnvelope, CommandResult, CreateCanvasRequest


router = APIRouter(prefix='/api')


@router.post('/canvases', response_model=CanvasSnapshot, status_code=status.HTTP_201_CREATED)
def create_canvas(request: Request, body: CreateCanvasRequest) -> CanvasSnapshot:
    repository: CanvasRepository = request.app.state.canvas_repository
    return repository.create_canvas(body.name, body.canvasId)


@router.get('/canvases/{canvas_id}/snapshot', response_model=CanvasSnapshot)
def get_snapshot(request: Request, canvas_id: str) -> CanvasSnapshot:
    repository: CanvasRepository = request.app.state.canvas_repository
    return repository.get_snapshot(canvas_id)


@router.post('/canvases/{canvas_id}/commands', response_model=CommandResult)
def execute_command(
    request: Request, canvas_id: str, envelope: CommandEnvelope
) -> CommandResult:
    service: CanvasCommandService = request.app.state.canvas_command_service
    return service.execute(canvas_id, envelope)
