from typing import Any
from uuid import uuid4

from .domain import DomainError
from .events import EventStore
from .graph_rules import validate_connection
from .repositories import CanvasRepository
from .schemas import CommandEnvelope, CommandResult


_NODE_TYPES = {'image', 'video', 'note'}


class CanvasCommandService:
    def __init__(self, repository: CanvasRepository, events: EventStore) -> None:
        self.repository = repository
        self.events = events

    def execute(self, canvas_id: str, envelope: CommandEnvelope) -> CommandResult:
        cached = self.repository.find_command(canvas_id, envelope.idempotencyKey)
        if cached is not None:
            return cached

        with self.repository.transaction():
            self.repository.assert_revision(canvas_id, envelope.baseRevision)
            payload = self._dispatch(canvas_id, envelope)
            revision = self.repository.bump_revision(canvas_id)
            result = CommandResult(
                revision=revision,
                command=envelope.command,
                payload=payload,
            )
            self.events.append_for_result(canvas_id, revision, result)
            self.repository.save_command(canvas_id, envelope.idempotencyKey, result)
        return result

    def _dispatch(self, canvas_id: str, envelope: CommandEnvelope) -> dict[str, Any]:
        handlers = {
            'create_node': self._create_node,
            'update_node': self._update_node,
            'delete_node': self._delete_node,
            'connect_nodes': self._connect_nodes,
            'disconnect_nodes': self._disconnect_nodes,
            'update_note': self._update_note,
            'attach_asset': self._attach_asset,
            'start_generation': self._start_generation,
            'update_canvas': self._update_canvas,
        }
        handler = handlers.get(envelope.command)
        if handler is None:
            raise DomainError('UNKNOWN_COMMAND', f'Unknown canvas command {envelope.command}')
        return handler(canvas_id, envelope.payload)

    def _create_node(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        node_type = payload.get('nodeType')
        if node_type not in _NODE_TYPES:
            raise DomainError('INVALID_NODE_TYPE', f'Unsupported node type: {node_type}')
        node_id = str(payload.get('nodeId') or uuid4())
        default_width = 300 if node_type != 'note' else 280
        default_height = 260 if node_type != 'note' else 180
        data = {
            'title': payload.get('title') or f'Untitled {node_type}',
            'prompt': payload.get('prompt', ''),
            **payload.get('data', {}),
        }
        self.repository.insert_node(
            canvas_id,
            node_id,
            node_type,
            float(payload.get('x', 0)),
            float(payload.get('y', 0)),
            float(payload.get('width', default_width)),
            float(payload.get('height', default_height)),
            data,
        )
        return {'nodeId': node_id, 'nodeType': node_type}

    def _update_node(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        node_id = self._required(payload, 'nodeId')
        self.repository.update_node(canvas_id, node_id, payload)
        return {'nodeId': node_id}

    def _delete_node(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        node_id = self._required(payload, 'nodeId')
        self.repository.delete_node(canvas_id, node_id)
        return {'nodeId': node_id}

    def _connect_nodes(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        edge_id = str(payload.get('edgeId') or uuid4())
        source_id = self._required(payload, 'sourceNodeId')
        target_id = self._required(payload, 'targetNodeId')
        source_type = self.repository.node_type(canvas_id, source_id)
        target_type = self.repository.node_type(canvas_id, target_id)
        try:
            validate_connection(
                source_type,
                target_type,
                source_id,
                target_id,
                self.repository.node_edges(canvas_id),
            )
        except DomainError as error:
            raise error
        self.repository.insert_edge(canvas_id, edge_id, source_id, target_id)
        return {
            'edgeId': edge_id,
            'sourceNodeId': source_id,
            'targetNodeId': target_id,
        }

    def _disconnect_nodes(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        edge_id = self._required(payload, 'edgeId')
        self.repository.delete_edge(canvas_id, edge_id)
        return {'edgeId': edge_id}

    def _update_note(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        node_id = self._required(payload, 'nodeId')
        if self.repository.node_type(canvas_id, node_id) != 'note':
            raise DomainError('INVALID_NODE_TYPE', 'Only note nodes accept update_note')
        self.repository.update_node(canvas_id, node_id, {'data': payload.get('data', payload)})
        return {'nodeId': node_id}

    def _attach_asset(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        node_id = self._required(payload, 'nodeId')
        asset_id = self._required(payload, 'assetId')
        self.repository.update_node(canvas_id, node_id, {'data': {'assetId': asset_id}})
        return {'nodeId': node_id, 'assetId': asset_id}

    def _start_generation(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        node_id = str(payload.get('nodeId') or payload.get('targetNodeId') or '')
        if not node_id:
            raise DomainError('INVALID_PAYLOAD', 'Missing payload field: targetNodeId')
        node_type = self.repository.node_type(canvas_id, node_id)
        if node_type not in {'image', 'video'}:
            raise DomainError('INVALID_NODE_TYPE', 'Only image and video nodes can generate media')
        snapshot = self.repository.generation_snapshot(canvas_id, node_id)
        if 'prompt' in payload:
            snapshot['prompt'] = payload['prompt']
        if 'parameters' in payload:
            snapshot['parameters'] = payload['parameters']
        provider = (
            'bytedance/seedream-5-pro'
            if node_type == 'image'
            else 'bytedance/seedance-2.0-mini'
        )
        job_id = self.repository.create_generation_job(
            canvas_id,
            node_id,
            provider,
            snapshot,
            {
                'targetNodeId': node_id,
                'baseCanvasRevision': snapshot['baseCanvasRevision'],
                'references': snapshot['references'],
            },
        )
        return {'jobId': job_id, 'status': 'queued', 'provider': provider}

    def _update_canvas(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        viewport = payload.get('viewport')
        if not isinstance(viewport, dict) or not all(
            isinstance(viewport.get(key), (int, float)) for key in ('x', 'y', 'zoom')
        ) or viewport['zoom'] <= 0:
            raise DomainError('INVALID_PAYLOAD', 'Viewport must contain numeric x, y and positive zoom')
        normalized = {
            'x': float(viewport['x']),
            'y': float(viewport['y']),
            'zoom': float(viewport['zoom']),
        }
        self.repository.update_viewport(canvas_id, normalized)
        return {'viewport': normalized}

    @staticmethod
    def _required(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not value:
            raise DomainError('INVALID_PAYLOAD', f'Missing payload field: {key}')
        return str(value)
