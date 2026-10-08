"""Canvas comments and node version history (spec: 2026-10-08-canvas-comments-design.md)."""
import asyncio
from collections.abc import AsyncIterator
import json
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agent.comments import CommentService
from ..repositories import CanvasRepository
from ..versions import NodeVersions

router = APIRouter(prefix='/api')
HEARTBEAT_SECONDS = 15


class CreateCommentRequest(BaseModel):
    # {"kind": "canvas", "x", "y"} | {"kind": "node", "nodeId"} |
    # {"kind": "media", "nodeId", "x", "y" (0-1 inside the picture), "time" (videos)}
    anchor: dict[str, Any]
    text: str = Field(max_length=4000)


class ReplyRequest(BaseModel):
    text: str = Field(max_length=4000)


def _comments(request: Request) -> CommentService:
    return request.app.state.comment_service


@router.post('/canvases/{canvas_id}/comments')
async def create_comment(request: Request, canvas_id: str, body: CreateCommentRequest) -> dict:
    return await _comments(request).create(canvas_id, body.anchor, body.text)


@router.get('/canvases/{canvas_id}/comments')
def list_comments(
    request: Request, canvas_id: str,
    status: Literal['all', 'open', 'resolved'] = 'all', nodeId: str | None = None,
) -> dict:
    return {'comments': _comments(request).list(canvas_id, status, nodeId)}


@router.get('/canvases/{canvas_id}/comments/stream')
async def stream_comments(request: Request, canvas_id: str) -> StreamingResponse:
    """Every change to a comment on this canvas, as the full comment (event: comment)."""
    service = _comments(request)
    request.app.state.canvas_repository.assert_canvas(canvas_id)

    async def events() -> AsyncIterator[str]:
        queue = service.subscribe(canvas_id)
        try:
            yield ': connected\n\n'
            while True:
                if await request.is_disconnected():
                    return
                try:
                    comment = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ': keep-alive\n\n'
                    continue
                yield f'event: comment\ndata: {json.dumps(comment, ensure_ascii=False)}\n\n'
        finally:
            service.unsubscribe(canvas_id, queue)

    return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache'})


@router.get('/comments/{comment_id}')
def get_comment(request: Request, comment_id: str) -> dict:
    return _comments(request).get(comment_id)


@router.post('/comments/{comment_id}/reply')
async def reply_comment(request: Request, comment_id: str, body: ReplyRequest) -> dict:
    return await _comments(request).reply(comment_id, body.text)


@router.post('/comments/{comment_id}/resolve')
def resolve_comment(request: Request, comment_id: str) -> dict:
    return _comments(request).resolve(comment_id)


@router.post('/comments/{comment_id}/reopen')
def reopen_comment(request: Request, comment_id: str) -> dict:
    return _comments(request).reopen(comment_id)


@router.get('/canvases/{canvas_id}/nodes/{node_id}/versions')
def node_versions(request: Request, canvas_id: str, node_id: str) -> dict:
    """Oldest first. Switching back is the canvas command restore_version."""
    repository: CanvasRepository = request.app.state.canvas_repository
    node = repository.node_snapshot(canvas_id, node_id)
    current = node['data'].get('assetId')
    versions = NodeVersions(repository.database).list(canvas_id, node_id, current)
    return {'versions': versions, 'current': current}
