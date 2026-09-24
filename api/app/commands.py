from math import isfinite
from typing import Any
from uuid import uuid4

from .domain import DomainError
from .events import EventStore
from .graph_rules import validate_connection
from .prompting import compose_prompt
from .repositories import CanvasRepository
from .schemas import CommandEnvelope, CommandResult


_NODE_TYPES = {'image', 'video', 'note'}




# Viewport changes are not canvas content; undo runs are never themselves undone.
_UNTRACKED_COMMANDS = {'update_canvas', 'undo_agent_run'}


def diff_canvas_state(before: dict, after: dict) -> list[tuple[str, str, Any, Any]]:
    """(entity_type, id, before, after) for every node/edge that was created, changed or removed.

    Comparing whole-canvas state catches side effects such as edges removed by a node
    delete cascade, which the command payload alone would miss.
    """
    changes: list[tuple[str, str, Any, Any]] = []
    for entity_type in ('node', 'edge'):
        old, new = before[entity_type], after[entity_type]
        for entity_id in sorted(old.keys() | new.keys()):
            if old.get(entity_id) != new.get(entity_id):
                changes.append((entity_type, entity_id, old.get(entity_id), new.get(entity_id)))
    return changes


class CanvasCommandService:
    def __init__(self, repository: CanvasRepository, events: EventStore) -> None:
        self.repository = repository
        self.events = events

    def execute(self, canvas_id: str, envelope: CommandEnvelope) -> CommandResult:
        cached = self.repository.find_command(canvas_id, envelope.idempotencyKey)
        if cached is not None:
            return cached

        if envelope.agentRunId and envelope.actor != 'agent':
            raise DomainError('INVALID_PAYLOAD', 'agentRunId is only valid for agent commands')

        with self.repository.transaction():
            self.repository.assert_revision(canvas_id, envelope.baseRevision)
            track = bool(envelope.agentRunId) and envelope.command not in _UNTRACKED_COMMANDS
            before = self.repository.canvas_state(canvas_id) if track else None
            payload = self._dispatch(canvas_id, envelope)
            revision = self.repository.bump_revision(canvas_id)
            result = CommandResult(
                revision=revision,
                command=envelope.command,
                payload=payload,
                actor=envelope.actor,
                agentRunId=envelope.agentRunId,
            )
            if track:
                changes = diff_canvas_state(before, self.repository.canvas_state(canvas_id))
                if envelope.command == 'start_generation' and payload.get('jobId'):
                    changes.append(('job', payload['jobId'], None, {'targetNodeId': payload.get('targetNodeId')}))
                self.repository.record_agent_changes(envelope.agentRunId, canvas_id, revision, changes)
            self.events.append_for_result(canvas_id, revision, result)
            self.repository.save_command(canvas_id, envelope.idempotencyKey, result)
        return result

    def _dispatch(self, canvas_id: str, envelope: CommandEnvelope) -> dict[str, Any]:
        handlers = {
            'create_node': self._create_node,
            'update_node': self._update_node,
            'move_nodes': self._move_nodes,
            'delete_node': self._delete_node,
            'delete_elements': self._delete_elements,
            'connect_nodes': self._connect_nodes,
            'duplicate_nodes': self._duplicate_nodes,
            'disconnect_nodes': self._disconnect_nodes,
            'update_note': self._update_note,
            'attach_asset': self._attach_asset,
            'start_generation': self._start_generation,
            'update_canvas': self._update_canvas,
            'undo_agent_run': self._undo_agent_run,
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

    def _move_nodes(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        positions = payload.get('positions')
        if not isinstance(positions, list) or not positions:
            raise DomainError('INVALID_PAYLOAD', 'Expected a non-empty positions list')
        node_ids: list[str] = []
        for position in positions:
            if not isinstance(position, dict):
                raise DomainError('INVALID_PAYLOAD', 'Each position must name a node and coordinates')
            node_id = position.get('nodeId')
            x = position.get('x')
            y = position.get('y')
            if (
                not isinstance(node_id, str)
                or not node_id
                or type(x) not in (int, float)
                or type(y) not in (int, float)
                or not isfinite(x)
                or not isfinite(y)
                or node_id in node_ids
            ):
                raise DomainError('INVALID_PAYLOAD', 'Each node needs unique finite coordinates')
            node_ids.append(node_id)
            self.repository.update_node(canvas_id, node_id, {'x': float(x), 'y': float(y)})
        return {'nodeIds': node_ids}

    def _delete_node(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        node_id = self._required(payload, 'nodeId')
        self.repository.delete_node(canvas_id, node_id)
        return {'nodeId': node_id}

    def _delete_elements(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        node_ids = payload.get('nodeIds', [])
        edge_ids = payload.get('edgeIds', [])
        if (
            not isinstance(node_ids, list)
            or not isinstance(edge_ids, list)
            or not all(isinstance(item, str) and item for item in node_ids + edge_ids)
            or not (node_ids or edge_ids)
        ):
            raise DomainError('INVALID_PAYLOAD', 'Expected non-empty nodeIds or edgeIds lists')

        node_ids = list(dict.fromkeys(node_ids))
        edge_ids = list(dict.fromkeys(edge_ids))
        for edge_id in edge_ids:
            self.repository.delete_edge(canvas_id, edge_id)
        for node_id in node_ids:
            self.repository.delete_node(canvas_id, node_id)
        return {'nodeIds': node_ids, 'edgeIds': edge_ids}

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

    def _duplicate_nodes(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Copy nodes (content, prompt, parameters, size) to new positions.

        Payload: {"nodes": [{"sourceNodeId", "x", "y", "nodeId"?}], "titleSuffix"?}.
        The copies keep their inputs: edges coming into a copied node are copied too
        (from the same upstream node, or from its copy when that was duplicated as well),
        so a duplicate can be regenerated with the same references. Outgoing edges to
        nodes that were not duplicated are not copied.
        """
        items = payload.get('nodes')
        if not isinstance(items, list) or not items:
            raise DomainError('INVALID_PAYLOAD', 'Expected a non-empty nodes list')
        suffix = str(payload.get('titleSuffix', ' 副本'))
        id_map: dict[str, str] = {}
        created = []
        for item in items:
            if not isinstance(item, dict):
                raise DomainError('INVALID_PAYLOAD', 'Each node entry must be an object')
            source_id = self._required(item, 'sourceNodeId')
            if source_id in id_map:
                raise DomainError('INVALID_PAYLOAD', f'Node {source_id} is listed twice')
            source = self.repository.node_snapshot(canvas_id, source_id)
            new_id = str(item.get('nodeId') or uuid4())
            data = dict(source['data'])
            title = str(data.get('title') or '').strip()
            if title:
                data['title'] = f'{title}{suffix}'
            self.repository.insert_node(
                canvas_id,
                new_id,
                source['nodeType'],
                float(item.get('x', source['x'] + 40)),
                float(item.get('y', source['y'] + 40)),
                source['width'],
                source['height'],
                data,
            )
            id_map[source_id] = new_id
            created.append({'sourceNodeId': source_id, 'nodeId': new_id})

        edge_ids = []
        for edge in self.repository.node_edges(canvas_id):
            if edge.target_node_id not in id_map:
                continue
            source_id = id_map.get(edge.source_node_id, edge.source_node_id)
            edge_id = str(uuid4())
            self.repository.insert_edge(canvas_id, edge_id, source_id, id_map[edge.target_node_id])
            edge_ids.append(edge_id)
        return {'nodes': created, 'edgeIds': edge_ids}

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
            snapshot['nodePrompt'] = payload['prompt']
            snapshot['prompt'] = compose_prompt(
                [note['text'] for note in snapshot.get('notePrompts', [])],
                payload['prompt'],
            )
        if 'parameters' in payload:
            snapshot['parameters'] = payload['parameters']
        if 'model' in payload:
            snapshot['model'] = payload['model']
        from .models_registry import registry
        model = registry().for_node(node_type, snapshot.get('model'))
        if model is None:
            raise DomainError('NO_MODEL', f"没有可用的{'图片' if node_type == 'image' else '视频'}模型：检查 models/ 目录")
        snapshot['model'] = model.id
        snapshot['parameters'], _ = model.resolve_parameters(snapshot.get('parameters'))
        provider = f'{model.provider}:{model.provider_model}'
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
        return {'jobId': job_id, 'status': 'queued', 'provider': provider, 'targetNodeId': node_id}

    def _undo_agent_run(self, canvas_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from .agent.undo import undo_agent_run
        return undo_agent_run(self.repository, canvas_id, self._required(payload, 'runId'))

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
