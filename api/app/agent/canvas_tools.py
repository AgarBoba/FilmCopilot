"""Canvas tools the agent uses (spec 3.1), written as plain Python so they can be tested
without the SDK. `mcp_server.py` wraps them as MCP tools.

Every write goes through `CanvasCommandService.execute` with actor='agent' and the run id,
so it follows the same rules as the UI, shows up in the UI in real time and can be undone.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..commands import CanvasCommandService
from ..config import resolve_project_path
from ..domain import DomainError
from ..events import EventStore
from ..repositories import CanvasRepository
from ..schemas import CommandEnvelope
from . import conflicts, media
from .config import AgentConfig
from .store import AgentStore

BUSY = ('queued', 'running')
KIND_LABELS = {'image': '图片', 'video': '视频', 'note': '便签'}
PROMPT_PREVIEW = 80
NODE_WIDTH, NODE_HEIGHT, GAP = 300, 440, 40

IMAGE_PARAMETERS = {
    'size': ('1K', '2K'),
    'aspectRatio': ('match_input_image', '1:1', '16:9', '9:16', '4:3'),
    'outputFormat': ('png', 'jpeg'),
}
VIDEO_PARAMETERS = {
    'duration': (5, 10),
    'resolution': ('480p', '720p'),
    'aspectRatio': ('adaptive', '16:9', '9:16', '1:1'),
    'generateAudio': (True, False),
}
DEFAULT_PARAMETERS = {
    'image': {'size': '2K', 'aspectRatio': 'match_input_image', 'outputFormat': 'png'},
    'video': {'duration': 5, 'resolution': '720p', 'aspectRatio': 'adaptive', 'generateAudio': True},
}

# Readable explanations for domain errors, so the model can correct itself.
ERROR_TEXT = {
    'INVALID_CONNECTION': '这两种节点不能这样连：图片节点只接收图片或便签；视频节点接收图片、视频或便签；便签不接收任何连线。',
    'CYCLE': '这样连会形成循环（A 参考 B，B 又参考 A），请换一个方向。',
    'DUPLICATE_EDGE': '这两个节点之间已经有这条连线了。',
    'SELF_LINK': '节点不能连到自己。',
    'NOT_FOUND': '找不到这个节点或连线，可能已被删除。先用 get_canvas 看一下最新画布。',
}


def note_size(content: str) -> dict[str, float]:
    """Tall enough to show a note's text without scrolling (width fixed so storyboard rows stay aligned)."""
    per_line = 17  # CJK characters per rendered line at the default width and size
    rows = sum(max(1, -(-len(line) // per_line)) for line in content.split('\n'))
    return {'width': 300.0, 'height': float(max(180, min(440, 110 + rows * 30)))}


@dataclass
class ToolResult:
    text: str
    images: list[dict] = field(default_factory=list)  # {'data', 'mimeType'}
    is_error: bool = False
    touched: list[str] = field(default_factory=list)  # node ids, for UI highlight / step list
    summary: str = ''  # one-line step description shown in the agent panel
    memory: dict | None = None  # set by memory tools: what changed, for the "记下了…" line


class CanvasTools:
    def __init__(
        self,
        repository: CanvasRepository,
        service: CanvasCommandService,
        store: AgentStore,
        canvas_id: str,
        run_id: str,
        config: AgentConfig | None = None,
    ) -> None:
        self.repository = repository
        self.service = service
        self.store = store
        self.events = EventStore(repository.database)
        self.canvas_id = canvas_id
        self.run_id = run_id
        self.config = config or AgentConfig()
        self.stopped = False
        # Notes the user typed when approving a call; attached to that call's result.
        self.confirmation_notes: list[str] = []
        # Memory tools for this run (set by AgentService; tests may leave it empty).
        self.memory: Any = None
        self.last_seen_revision = repository.get_snapshot(canvas_id).revision
        # The canvas as the agent knows it: what it last looked at plus its own changes.
        self.seen = repository.canvas_state(canvas_id)

    # ------------------------------------------------------------------ reads

    def get_canvas(self, node_ids: list[str] | None = None) -> ToolResult:
        snapshot = self.repository.get_snapshot(self.canvas_id)
        self.last_seen_revision = snapshot.revision
        upstream: dict[str, list[str]] = {node.id: [] for node in snapshot.nodes}
        downstream: dict[str, list[str]] = {node.id: [] for node in snapshot.nodes}
        for edge in snapshot.edges:
            upstream[edge.target].append(edge.source)
            downstream[edge.source].append(edge.target)
        wanted = set(node_ids or [])
        if wanted:
            missing = wanted - upstream.keys()
            if missing:
                return self._error(f"找不到节点：{', '.join(sorted(missing))}")
            for node_id in list(wanted):
                wanted.update(upstream[node_id])
                wanted.update(downstream[node_id])
        conflicts.refresh(self.seen, self.repository.canvas_state(self.canvas_id), set(wanted) if wanted else None)
        lines = [f'画布共 {len(snapshot.nodes)} 个节点、{len(snapshot.edges)} 条连线。']
        for node in snapshot.nodes:
            if wanted and node.id not in wanted:
                continue
            data = node.data
            text = data.get('content') if node.nodeType == 'note' else data.get('prompt')
            text = str(text or '').replace('\n', ' ')
            if len(text) > PROMPT_PREVIEW:
                text = text[:PROMPT_PREVIEW] + '…'
            parts = [
                f"- [{node.id}] {KIND_LABELS[node.nodeType]}「{data.get('title', '')}」",
                f'位置 ({round(node.x)}, {round(node.y)})',
            ]
            if node.nodeType != 'note':
                parts.append('有内容' if data.get('assetId') else '无内容')
                job = self._latest_job(snapshot, node.id)
                if job:
                    parts.append(f"最近生成：{job['status']}")
            if text:
                parts.append(('文字' if node.nodeType == 'note' else 'Prompt') + f'：{text}')
            if upstream[node.id]:
                parts.append(f"上游：{', '.join(upstream[node.id])}")
            if node.id in snapshot.upstreamChanges:
                parts.append('上游有更新')
            lines.append('；'.join(parts))
        return ToolResult('\n'.join(lines), summary='查看画布')

    def get_node(self, node_id: str) -> ToolResult:
        snapshot = self.repository.get_snapshot(self.canvas_id)
        self.last_seen_revision = snapshot.revision
        conflicts.refresh(self.seen, self.repository.canvas_state(self.canvas_id), {node_id})
        node = next((item for item in snapshot.nodes if item.id == node_id), None)
        if node is None:
            return self._error(ERROR_TEXT['NOT_FOUND'])
        data = node.data
        titles = {item.id: item.data.get('title', '') for item in snapshot.nodes}
        kinds = {item.id: item.nodeType for item in snapshot.nodes}
        lines = [f"{KIND_LABELS[node.nodeType]}节点「{data.get('title', '')}」[{node.id}]"]
        if node.nodeType == 'note':
            lines.append(f"文字：{data.get('content') or data.get('prompt') or '（空）'}")
        else:
            lines.append(f"Prompt：{data.get('prompt') or '（空）'}")
            parameters = {**DEFAULT_PARAMETERS[node.nodeType], **(data.get('parameters') or {})}
            lines.append(f'参数：{parameters}')
            asset = next((item for item in snapshot.assets if item['id'] == data.get('assetId')), None)
            if asset:
                size = f"{asset.get('width')}×{asset.get('height')}"
                duration = f"，{asset['duration_seconds']:.1f} 秒" if asset.get('duration_seconds') else ''
                lines.append(f"内容：{KIND_LABELS[asset['kind']]} {size}{duration}（可用 view_asset 查看）")
            else:
                lines.append('内容：无')
            job = self._latest_job(snapshot, node.id)
            if job:
                error = f"，原因：{str(job['error'])[:200]}" if job.get('error') else ''
                lines.append(f"最近一次生成：{job['status']}{error}")
        refs = [edge.source for edge in snapshot.edges if edge.target == node.id]
        if refs:
            lines.append('上游：' + '、'.join(f"{KIND_LABELS[kinds[ref]]}「{titles[ref]}」[{ref}]" for ref in refs))
        outs = [edge.target for edge in snapshot.edges if edge.source == node.id]
        if outs:
            lines.append('下游：' + '、'.join(f"{KIND_LABELS[kinds[out]]}「{titles[out]}」[{out}]" for out in outs))
        if node.id in snapshot.upstreamChanges:
            lines.append('上游有更新：' + '；'.join(snapshot.upstreamChanges[node.id]))
        return ToolResult('\n'.join(lines), summary=f"查看「{data.get('title', '')}」", touched=[node.id])

    def view_asset(self, node_id: str) -> ToolResult:
        node = self._node_or_none(node_id)
        if node is None:
            return self._error(ERROR_TEXT['NOT_FOUND'])
        asset_id = node['data'].get('assetId')
        if not asset_id:
            return self._error('这个节点还没有图片或视频。')
        asset = self.repository.asset_dict(asset_id)
        path = resolve_project_path(asset['path'])
        title = node['data'].get('title', '')
        try:
            if asset['kind'] == 'image':
                image = media.image_for_model(path, self.config.image_max_side)
                return ToolResult(
                    f"「{title}」的图片（原图 {asset.get('width')}×{asset.get('height')}）：",
                    images=[{'data': image['data'], 'mimeType': image['mimeType']}],
                    summary=f'查看「{title}」', touched=[node_id],
                )
            duration, frames = media.video_frames_for_model(path, max_side=self.config.image_max_side)
        except DomainError as error:
            return self._error(error.message)
        except Exception as error:  # unreadable file, ffmpeg failure
            return self._error(f'读取媒体文件失败：{error}')
        return ToolResult(
            f"「{title}」的视频，时长 {duration:.1f} 秒，以下是开头、中间、结尾 3 帧"
            f"（{', '.join(str(frame['at']) + 's' for frame in frames)}）：",
            images=[{'data': frame['data'], 'mimeType': frame['mimeType']} for frame in frames],
            summary=f'查看「{title}」', touched=[node_id],
        )

    # ----------------------------------------------------------------- writes

    def create_nodes(self, nodes: list[dict[str, Any]]) -> ToolResult:
        if not nodes:
            return self._error('至少要新建一个节点。')
        positions = self._free_positions(len(nodes))
        created: list[str] = []
        for index, spec in enumerate(nodes):
            node_type = spec.get('type')
            if node_type not in KIND_LABELS:
                return self._partial(created, f'第 {index + 1} 个节点类型不对，只能是 image、video 或 note。')
            data: dict[str, Any] = {}
            if node_type == 'note':
                data['content'] = str(spec.get('content') or spec.get('prompt') or '')
            else:
                data['prompt'] = str(spec.get('prompt') or '')
                problem = self._check_parameters(node_type, spec.get('parameters'))
                if problem:
                    return self._partial(created, problem)
                data['parameters'] = {**DEFAULT_PARAMETERS[node_type], **(spec.get('parameters') or {})}
            x, y = spec.get('x'), spec.get('y')
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                x, y = positions[index]
            title = str(spec.get('title') or '').strip()[:60] or self._next_title(node_type)
            payload = {'nodeType': node_type, 'title': title, 'x': float(x), 'y': float(y), 'data': data}
            if node_type == 'note':
                payload.update(note_size(data['content']))
            result = self._command('create_node', payload)
            if isinstance(result, ToolResult):
                return self._partial(created, result.text)
            created.append(result['nodeId'])
        titles = self._titles(created)
        return ToolResult(
            '已新建：' + '、'.join(f'「{titles[i]}」[{i}]' for i in created),
            touched=created, summary=f'新建 {len(created)} 个节点',
        )

    def update_node(self, node_id: str, changes: dict[str, Any]) -> ToolResult:
        node = self._node_or_none(node_id)
        if node is None:
            return self._error(ERROR_TEXT['NOT_FOUND'])
        if (busy := self._busy_error([node_id])):
            return busy
        data: dict[str, Any] = {}
        if 'title' in changes:
            title = str(changes['title'] or '').strip()
            if not title:
                return self._error('标题不能为空。')
            data['title'] = title[:60]
        if node['nodeType'] == 'note':
            if 'content' in changes or 'prompt' in changes:
                data['content'] = str(changes.get('content', changes.get('prompt')) or '')
            if 'parameters' in changes:
                return self._error('便签没有生成参数。')
        else:
            if 'prompt' in changes:
                data['prompt'] = str(changes['prompt'] or '')
            if 'parameters' in changes:
                problem = self._check_parameters(node['nodeType'], changes['parameters'])
                if problem:
                    return self._error(problem)
                data['parameters'] = {
                    **DEFAULT_PARAMETERS[node['nodeType']],
                    **(node['data'].get('parameters') or {}),
                    **changes['parameters'],
                }
        if not data:
            return self._error('没有要修改的内容（可改 title、prompt / content、parameters）。')
        aspects = {'gone'} | {conflicts.DATA_ASPECTS[key] for key in data}
        result = self._command('update_node', {'nodeId': node_id, 'data': data}, {node_id: aspects})
        if isinstance(result, ToolResult):
            return result
        title = data.get('title') or node['data'].get('title', '')
        return ToolResult(f"已更新「{title}」：{'、'.join(data)}", touched=[node_id], summary=f'修改「{title}」')

    def connect(self, source_id: str, target_id: str) -> ToolResult:
        if (busy := self._busy_error([target_id])):
            return busy
        result = self._command(
            'connect_nodes', {'sourceNodeId': source_id, 'targetNodeId': target_id},
            {source_id: {'gone'}, target_id: {'gone'}},
        )
        if isinstance(result, ToolResult):
            return result
        titles = self._titles([source_id, target_id])
        label = f'「{titles[source_id]}」→「{titles[target_id]}」'
        return ToolResult(f'已连接{label}', touched=[source_id, target_id], summary=f'连接{label}')

    def disconnect(self, source_id: str, target_id: str) -> ToolResult:
        if (busy := self._busy_error([target_id])):
            return busy
        edge = next(
            (edge for edge in self.repository.get_snapshot(self.canvas_id).edges
             if edge.source == source_id and edge.target == target_id),
            None,
        )
        if edge is None:
            return self._error('这两个节点之间没有连线。')
        result = self._command('disconnect_nodes', {'edgeId': edge.id}, {source_id: {'gone'}, target_id: {'gone'}})
        if isinstance(result, ToolResult):
            return result
        titles = self._titles([source_id, target_id])
        label = f'「{titles[source_id]}」→「{titles[target_id]}」'
        return ToolResult(f'已断开{label}', touched=[source_id, target_id], summary=f'断开{label}')

    def move_nodes(self, positions: list[dict[str, Any]]) -> ToolResult:
        payload = [
            {'nodeId': item.get('node_id') or item.get('nodeId'), 'x': item.get('x'), 'y': item.get('y')}
            for item in positions or []
        ]
        result = self._command(
            'move_nodes', {'positions': payload},
            {item['nodeId']: {'gone', 'layout'} for item in payload if isinstance(item['nodeId'], str)},
        )
        if isinstance(result, ToolResult):
            return result
        return ToolResult(
            f'已移动 {len(payload)} 个节点', touched=result['nodeIds'], summary=f'移动 {len(payload)} 个节点'
        )

    def duplicate_nodes(self, node_ids: list[str], offset: float = 40) -> ToolResult:
        nodes = {node.id: node for node in self.repository.get_snapshot(self.canvas_id).nodes}
        if not node_ids or any(node_id not in nodes for node_id in node_ids):
            return self._error(ERROR_TEXT['NOT_FOUND'])
        result = self._command('duplicate_nodes', {'nodes': [
            {'sourceNodeId': node_id, 'x': nodes[node_id].x + offset, 'y': nodes[node_id].y + offset}
            for node_id in node_ids
        ]}, {node_id: {'gone'} for node_id in node_ids})
        if isinstance(result, ToolResult):
            return result
        created = [item['nodeId'] for item in result['nodes']]
        titles = self._titles(created)
        return ToolResult(
            '已复制：' + '、'.join(f'「{titles[i]}」[{i}]' for i in created),
            touched=created, summary=f'复制 {len(created)} 个节点',
        )

    def delete_nodes(self, node_ids: list[str]) -> ToolResult:
        if not node_ids:
            return self._error('没有指定要删除的节点。')
        titles = self._titles(node_ids)
        # Don't throw away something the user has just been working on.
        edited = {'gone', 'title', 'prompt', 'parameters', 'media', 'inputs'}
        result = self._command('delete_elements', {'nodeIds': node_ids}, {node_id: edited for node_id in node_ids})
        if isinstance(result, ToolResult):
            return result
        return ToolResult(
            '已删除：' + '、'.join(f'「{titles.get(i, i)}」' for i in node_ids),
            summary=f'删除 {len(node_ids)} 个节点',
        )

    def generate(self, node_ids: list[str]) -> ToolResult:
        if not node_ids:
            return self._error('没有指定要生成的节点。')
        snapshot = self.repository.get_snapshot(self.canvas_id)
        nodes = {node.id: node for node in snapshot.nodes}
        for node_id in node_ids:
            node = nodes.get(node_id)
            if node is None:
                return self._error(ERROR_TEXT['NOT_FOUND'])
            title = node.data.get('title', '')
            if node.nodeType == 'note':
                return self._error(f'「{title}」是便签，不能生成。')
            has_notes = any(
                edge.target == node_id and nodes[edge.source].nodeType == 'note' for edge in snapshot.edges
            )
            if not str(node.data.get('prompt') or '').strip() and not has_notes:
                return self._error(f'「{title}」没有 Prompt，也没有连接便签，先写 Prompt。')
        if (busy := self._busy_error(node_ids)):
            return busy
        started: list[str] = []
        for node_id in node_ids:
            # What gets generated: the node's own prompt/parameters/inputs and its upstream content.
            deps = {node_id: {'gone', 'prompt', 'parameters', 'inputs'}}
            for edge in snapshot.edges:
                if edge.target == node_id:
                    deps[edge.source] = {'gone', 'prompt', 'media'}
            result = self._command('start_generation', {'targetNodeId': node_id}, deps)
            if isinstance(result, ToolResult):
                prefix = f'已开始 {len(started)} 个生成，之后出错：' if started else ''
                return ToolResult(prefix + result.text, is_error=True, touched=started)
            self.store.count_generation(self.run_id)
            started.append(node_id)
        titles = self._titles(node_ids)
        return ToolResult(
            '已开始生成：' + '、'.join(f'「{titles[i]}」' for i in node_ids)
            + '。用 wait_for_generation 等待并查看结果。',
            touched=node_ids, summary=f'生成 {len(node_ids)} 个节点',
        )

    async def wait_for_generation(self, node_ids: list[str], timeout_seconds: float | None = None) -> ToolResult:
        snapshot = self.repository.get_snapshot(self.canvas_id)
        kinds = {node.id: node.nodeType for node in snapshot.nodes}
        limit = timeout_seconds or (
            self.config.video_wait_seconds if any(kinds.get(i) == 'video' for i in node_ids)
            else self.config.image_wait_seconds
        )
        waited = 0.0
        while True:
            snapshot = self.repository.get_snapshot(self.canvas_id)
            busy = [i for i in node_ids if (self._latest_job(snapshot, i) or {}).get('status') in BUSY]
            if not busy or self.stopped or waited >= limit:
                break
            await asyncio.sleep(self.config.poll_seconds)
            waited += self.config.poll_seconds
        self.last_seen_revision = snapshot.revision

        titles = self._titles(node_ids)
        lines: list[str] = []
        images: list[dict] = []
        for node_id in node_ids:
            job = self._latest_job(snapshot, node_id) or {}
            status = job.get('status')
            name = f'「{titles.get(node_id, node_id)}」'
            if status in BUSY:
                lines.append(f"{name}还在生成（{'已停止等待' if self.stopped else f'已等 {int(waited)} 秒'}）")
            elif status == 'failed':
                lines.append(f"{name}生成失败：{str(job.get('error') or '')[:300]}")
            elif status in ('completed', 'completed_unattached'):
                viewed = self.view_asset(node_id)
                if viewed.is_error:
                    lines.append(f'{name}已完成，但无法查看：{viewed.text}')
                else:
                    lines.append(f'{name}已完成。{viewed.text}')
                    images.extend(viewed.images)
            else:
                lines.append(f'{name}没有进行中的生成任务')
        return ToolResult('\n'.join(lines), images=images, touched=list(node_ids), summary='查看生成结果')

    # ---------------------------------------------------------------- helpers

    def _command(
        self, command: str, payload: dict[str, Any], deps: dict[str, set[str]] | None = None,
    ) -> dict[str, Any] | ToolResult:
        """Run one canvas command for the agent.

        The user may be working on the canvas at the same time. Only edits to what this step
        depends on (`deps`: node id -> aspects, see conflicts.py) stop it; anything else, such
        as moving other nodes or a generation finishing, is merged in and the step goes ahead.
        """
        if self.stopped:
            return self._error('已停止：用户中止了这一轮任务，不要再修改画布。')
        step = self.store.next_step(self.run_id)
        for _ in range(5):
            before = self.repository.canvas_state(self.canvas_id)
            changes = conflicts.node_changes(self.seen, before, self.repository.generated_asset_ids(self.canvas_id))
            hits = conflicts.blocking(changes, deps or {})
            if hits:
                return self._conflict(hits)
            envelope = CommandEnvelope(
                command=command,
                baseRevision=self.repository.canvas_revision(self.canvas_id),
                idempotencyKey=f'agent:{self.run_id}:{step}',
                payload=payload,
                actor='agent',
                agentRunId=self.run_id,
            )
            try:
                result = self.service.execute(self.canvas_id, envelope)
            except DomainError as error:
                if error.code == 'REVISION_CONFLICT':
                    continue  # something changed in between; check again
                return self._error(ERROR_TEXT.get(error.code, error.message))
            conflicts.apply_changes(self.seen, before, self.repository.canvas_state(self.canvas_id))
            self.last_seen_revision = result.revision
            return result.payload
        return self._error('画布正在频繁变化，这一步没有执行。稍等几秒再试。')

    def _conflict(self, hits: dict[str, set[str]]) -> ToolResult:
        """The user changed something this step depends on: don't overwrite it, tell the model."""
        titles = {node_id: (node.get('data') or {}).get('title', '') for node_id, node in self.seen['node'].items()}
        titles.update(self._titles(list(hits)))
        return ToolResult(
            f'这一步没有执行：用户刚刚{conflicts.describe(hits, titles)}。'
            '先用 get_node 看这些节点的最新内容。如果用户的改动和你的计划不矛盾，就在最新内容的基础上继续做完，'
            '不用停下来问；只有改动和计划矛盾时（比如删了你要用的节点、改了你正要改的同一处），才向用户说明并询问。'
            '不要覆盖用户的改动。',
            is_error=True, touched=list(hits), summary='用户改了相关节点，这一步先没执行',
        )

    def _busy_error(self, node_ids: list[str]) -> ToolResult | None:
        snapshot = self.repository.get_snapshot(self.canvas_id)
        busy = [i for i in node_ids if (self._latest_job(snapshot, i) or {}).get('status') in BUSY]
        if not busy:
            return None
        titles = self._titles(busy)
        names = '、'.join(f'「{titles.get(i, i)}」' for i in busy)
        return self._error(f'{names}正在生成，完成后再改。可以用 wait_for_generation 等待。')

    @staticmethod
    def _latest_job(snapshot, node_id: str) -> dict | None:
        jobs = [job for job in snapshot.jobs if job.get('target_node_id') == node_id]
        return jobs[-1] if jobs else None

    def _node_or_none(self, node_id: str) -> dict | None:
        try:
            return self.repository.node_snapshot(self.canvas_id, node_id)
        except DomainError:
            return None

    def _titles(self, node_ids: list[str]) -> dict[str, str]:
        titles = {node.id: node.data.get('title', '') for node in self.repository.get_snapshot(self.canvas_id).nodes}
        return {node_id: titles[node_id] for node_id in node_ids if node_id in titles}

    def _next_title(self, node_type: str) -> str:
        label = KIND_LABELS[node_type]
        used = [0]
        for node in self.repository.get_snapshot(self.canvas_id).nodes:
            title = str(node.data.get('title', ''))
            suffix = title[len(label) + 1:]
            if node.nodeType == node_type and title.startswith(label + ' ') and suffix.isdigit():
                used.append(int(suffix))
        return f'{label} {max(used) + 1}'

    def _free_positions(self, count: int) -> list[tuple[float, float]]:
        """A column to the right of everything already on the canvas."""
        nodes = self.repository.get_snapshot(self.canvas_id).nodes
        if not nodes:
            return [(0.0, index * (NODE_HEIGHT + GAP)) for index in range(count)]
        right = max(node.x + (node.width or NODE_WIDTH) for node in nodes) + GAP * 2
        top = min(node.y for node in nodes)
        return [(right, top + index * (NODE_HEIGHT + GAP)) for index in range(count)]

    @staticmethod
    def _check_parameters(node_type: str, parameters: Any) -> str | None:
        if parameters is None:
            return None
        if not isinstance(parameters, dict):
            return 'parameters 必须是对象。'
        allowed = IMAGE_PARAMETERS if node_type == 'image' else VIDEO_PARAMETERS
        for key, value in parameters.items():
            if key not in allowed:
                return f"{KIND_LABELS[node_type]}节点没有参数 {key}，可用：{', '.join(allowed)}。"
            if value not in allowed[key] or isinstance(value, bool) != isinstance(allowed[key][0], bool):
                return f"{key} 只能是：{', '.join(str(item) for item in allowed[key])}。"
        return None

    @staticmethod
    def _partial(created: list[str], message: str) -> ToolResult:
        prefix = f"已新建 {len(created)} 个（{', '.join(created)}），之后出错：" if created else ''
        return ToolResult(prefix + message, is_error=True, touched=created)

    @staticmethod
    def _error(message: str) -> ToolResult:
        return ToolResult(message, is_error=True)
