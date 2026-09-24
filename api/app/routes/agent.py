"""HTTP + SSE endpoints for the agent panel (spec 7)."""
import asyncio
from collections.abc import AsyncIterator
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agent.runtime import AgentService
from ..agent.store import AgentStore
from ..repositories import CanvasRepository

router = APIRouter(prefix='/api')
HEARTBEAT_SECONDS = 15


class CreateSessionRequest(BaseModel):
    canvasId: str


class UpdateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    archived: bool | None = None


class SendMessageRequest(BaseModel):
    text: str
    focusNodeIds: list[str] = Field(default_factory=list)


class ConfirmRequest(BaseModel):
    requestId: str
    approved: bool
    note: str = Field(default='', max_length=2000)


def _service(request: Request) -> AgentService:
    return request.app.state.agent_service


def _store(request: Request) -> AgentStore:
    return request.app.state.agent_store


def _event_from_message(message: dict) -> dict:
    return {'id': message['id'], 'runId': message['run_id'], 'createdAt': message['created_at'], **message['content']}


@router.get('/agent/status')
def agent_status(request: Request) -> dict:
    config = _service(request).config
    return {'configured': config.api_key_present, 'model': config.model}


@router.post('/agent/sessions', status_code=201)
def create_session(request: Request, body: CreateSessionRequest) -> dict:
    repository: CanvasRepository = request.app.state.canvas_repository
    repository.assert_canvas(body.canvasId)
    return _store(request).create_session(body.canvasId)


@router.get('/agent/sessions')
def list_sessions(request: Request, canvasId: str | None = None, projectId: str | None = None) -> list[dict]:
    store = _store(request)
    project = projectId or (store.project_for_canvas(canvasId) if canvasId else 'default')
    sessions = store.list_sessions(project, canvasId)
    service = _service(request)
    result = []
    for session in sessions:
        run_id = service.active_run(session['id'])
        status = 'idle'
        if run_id:
            status = 'waiting' if store.get_run(run_id)['status'] == 'waiting_confirmation' else 'running'
        result.append({**session, 'activeRunId': run_id, 'status': status})
    return result


@router.patch('/agent/sessions/{session_id}')
def update_session(request: Request, session_id: str, body: UpdateSessionRequest) -> dict:
    """Rename or archive / restore a chat. Chats are never deleted."""
    return _store(request).update_session(session_id, body.title, body.archived)


@router.get('/agent/sessions/{session_id}/messages')
def list_messages(request: Request, session_id: str, after: int = Query(default=0, ge=0)) -> list[dict]:
    store = _store(request)
    store.get_session(session_id)
    return [_event_from_message(message) for message in store.list_messages(session_id, after)]


@router.post('/agent/sessions/{session_id}/messages', status_code=202)
async def send_message(request: Request, session_id: str, body: SendMessageRequest) -> dict:
    run = await _service(request).send_message(session_id, body.text, body.focusNodeIds)
    return {'runId': run['id']}


@router.get('/agent/sessions/{session_id}/stream')
async def stream(request: Request, session_id: str, after: int = Query(default=0, ge=0)) -> StreamingResponse:
    store = _store(request)
    store.get_session(session_id)
    service = _service(request)

    async def events() -> AsyncIterator[str]:
        queue = service.subscribe(session_id)  # subscribe before replay so nothing falls in between
        last_id = after
        try:
            for message in store.list_messages(session_id, after):
                last_id = message['id']
                yield _format(_event_from_message(message))
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ': keep-alive\n\n'
                    continue
                if event.get('id') is not None:
                    if event['id'] <= last_id:
                        continue  # already sent during replay
                    last_id = event['id']
                yield _format(event)
        finally:
            service.unsubscribe(session_id, queue)

    return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache'})


def _format(event: dict) -> str:
    prefix = f"id: {event['id']}\n" if event.get('id') is not None else ''
    return f"{prefix}event: {event['kind']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post('/agent/runs/{run_id}/confirm')
def confirm(request: Request, run_id: str, body: ConfirmRequest) -> dict:
    _store(request).get_run(run_id)
    return {'resolved': _service(request).confirm(body.requestId, body.approved, body.note)}


@router.post('/agent/runs/{run_id}/stop')
async def stop(request: Request, run_id: str) -> dict:
    _store(request).get_run(run_id)
    await _service(request).stop(run_id)
    return {'stopping': True}


@router.post('/agent/runs/{run_id}/undo')
def undo(request: Request, run_id: str) -> dict:
    return _service(request).undo(run_id)


@router.get('/projects/{project_id}/agent-settings')
def get_settings(request: Request, project_id: str) -> dict:
    return _store(request).get_settings(project_id)


@router.patch('/projects/{project_id}/agent-settings')
def update_settings(request: Request, project_id: str, body: dict) -> dict:
    return _store(request).update_settings(project_id, body)
