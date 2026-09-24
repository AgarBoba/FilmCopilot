"""Memory view endpoints: list, add, edit, delete, and undo an agent change."""
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..agent.memory import CATEGORIES, MemoryStore

router = APIRouter(prefix='/api')


class AddMemoryRequest(BaseModel):
    layer: Literal['project', 'preference']
    content: str = Field(max_length=1000)
    category: str = 'other'
    projectId: str = 'default'


class EditMemoryRequest(BaseModel):
    content: str | None = Field(default=None, max_length=1000)
    category: str | None = None


def _memory(request: Request) -> MemoryStore:
    return request.app.state.agent_service.memory


@router.get('/memories')
def list_memories(request: Request, projectId: str = 'default') -> dict:
    return {**_memory(request).list_all(projectId), 'categories': CATEGORIES}


@router.post('/memories', status_code=201)
def add_memory(request: Request, body: AddMemoryRequest) -> dict:
    """Added by hand in the memory view: counts as something the user said."""
    item, _ = _memory(request).add(body.layer, body.content, body.category, project_id=body.projectId)
    return item


@router.patch('/memories/{memory_id}')
def edit_memory(request: Request, memory_id: int, body: EditMemoryRequest) -> dict:
    return _memory(request).edit(memory_id, body.content, body.category)


@router.delete('/memories/{memory_id}', status_code=204)
def delete_memory(request: Request, memory_id: int) -> None:
    _memory(request).delete(memory_id)


@router.post('/memories/{memory_id}/revert')
def revert_memory(request: Request, memory_id: int) -> dict:
    """"撤销" next to "记下了…" in the chat."""
    return _memory(request).revert(memory_id)
