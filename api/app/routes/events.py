import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..domain import DomainError
from ..events import EventStore
from ..repositories import CanvasRepository


router = APIRouter(prefix='/api')


def _format_event(event) -> str:
    return (
        f'id: {event.id}\n'
        f'event: {event.eventType}\n'
        f'data: {json.dumps(event.model_dump(mode="json"))}\n\n'
    )


@router.get('/canvases/{canvas_id}/events')
async def stream_events(
    request: Request,
    canvas_id: str,
    afterRevision: int = Query(default=0, ge=0),
) -> StreamingResponse:
    repository: CanvasRepository = request.app.state.canvas_repository
    repository.assert_canvas(canvas_id)
    events: EventStore = request.app.state.event_store

    async def event_stream() -> AsyncIterator[str]:
        revision = afterRevision
        while True:
            for event in events.after_revision(canvas_id, revision):
                revision = max(revision, event.revision)
                yield _format_event(event)
            if await request.is_disconnected():
                return
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type='text/event-stream')
