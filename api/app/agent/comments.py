"""Canvas comments: pin a note anywhere on the canvas and the agent takes it on (spec:
docs/superpowers/specs/2026-10-08-canvas-comments-design.md).

Each comment owns one agent session (kind='comment'). Comments queue per canvas: at most
MAX_PARALLEL run at once, and comments on the same node run one after another, in the order
they were queued. A comment's status follows its session's events:

    queued -> running <-> waiting (a confirmation card is open) -> done | failed -> resolved

Replying to a finished comment queues it again with the reply as the next message.
"""
import asyncio
from collections.abc import Iterable
import json
import logging
import math
from typing import Any
from uuid import uuid4

from ..domain import DomainError
from ..versions import NodeVersions
from .runtime import AgentService

log = logging.getLogger(__name__)

MAX_PARALLEL = 2
ACTIVE = ('running', 'waiting')
OPEN = ('queued', 'running', 'waiting', 'done', 'failed')
MAX_TEXT = 4000


class CommentService:
    def __init__(self, agent: AgentService) -> None:
        self.agent = agent
        self.repository = agent.repository
        self.store = agent.store
        self.database = agent.repository.database
        self.versions = NodeVersions(self.database)
        self.subscribers: dict[str, set[asyncio.Queue]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_text: dict[str, str] = {}  # comment id -> latest assistant reply in its run
        agent.listeners.append(self._on_event)

    # --------------------------------------------------------------- public

    async def create(self, canvas_id: str, anchor: dict[str, Any], text: str) -> dict[str, Any]:
        text = (text or '').strip()
        if not text:
            raise DomainError('INVALID_PAYLOAD', '留言不能为空')
        if len(text) > MAX_TEXT:
            raise DomainError('INVALID_PAYLOAD', f'留言太长了（最多 {MAX_TEXT} 字）')
        self.repository.assert_canvas(canvas_id)
        if not self.agent.config.configured:
            raise DomainError(
                'AGENT_NOT_CONFIGURED',
                '没有配置 Agent 的模型登录：在 .env 里填 ANTHROPIC_API_KEY，然后重启',
            )
        fields = self._validate_anchor(canvas_id, anchor)
        session = self.store.create_session(canvas_id, title=text[:30], kind='comment')
        comment_id = str(uuid4())
        with self.database.transaction() as connection:
            connection.execute(
                '''
                INSERT INTO canvas_comments
                    (id, canvas_id, session_id, anchor_kind, node_id, version, x, y, time, text, status, pending_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
                ''',
                (comment_id, canvas_id, session['id'], fields['kind'], fields.get('node_id'), fields.get('version'),
                 fields.get('x'), fields.get('y'), fields.get('time'), text, text),
            )
        self._publish(comment_id)
        await self.pump(canvas_id)
        return self.get(comment_id)

    def get(self, comment_id: str) -> dict[str, Any]:
        row = self._row(comment_id)
        return self._public(row, self._node_ids(row['canvas_id']))

    def list(self, canvas_id: str, status: str = 'all', node_id: str | None = None) -> list[dict[str, Any]]:
        self.repository.assert_canvas(canvas_id)
        query = 'SELECT * FROM canvas_comments WHERE canvas_id = ?'
        params: list[Any] = [canvas_id]
        if status == 'open':
            query += " AND status != 'resolved'"
        elif status == 'resolved':
            query += " AND status = 'resolved'"
        if node_id:
            query += ' AND node_id = ?'
            params.append(node_id)
        query += ' ORDER BY created_at, rowid'
        with self.database.connection() as connection:
            rows = [dict(row) for row in connection.execute(query, params).fetchall()]
        nodes = self._node_ids(canvas_id)
        return [self._public(row, nodes) for row in rows]

    def for_session(self, session_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute('SELECT * FROM canvas_comments WHERE session_id = ?', (session_id,)).fetchone()
        return dict(row) if row else None

    async def reply(self, comment_id: str, text: str) -> dict[str, Any]:
        """Continue a finished (or resolved) comment: the reply becomes its next message."""
        text = (text or '').strip()
        if not text:
            raise DomainError('INVALID_PAYLOAD', '回复不能为空')
        if len(text) > MAX_TEXT:
            raise DomainError('INVALID_PAYLOAD', f'回复太长了（最多 {MAX_TEXT} 字）')
        row = self._row(comment_id)
        if row['status'] in ('queued', *ACTIVE):
            raise DomainError('COMMENT_BUSY', 'Agent 还在处理这条留言，等它做完再回复')
        self._update(comment_id, status='queued', pending_text=text, resolved_at=None)
        await self.pump(row['canvas_id'])
        return self.get(comment_id)

    def resolve(self, comment_id: str) -> dict[str, Any]:
        row = self._row(comment_id)
        if row['status'] in ACTIVE:
            raise DomainError('COMMENT_BUSY', 'Agent 还在处理这条留言，先等它做完或停止')
        if row['status'] != 'resolved':
            self._update(comment_id, status='resolved', pending_text=None, resolved_at='now')
        return self.get(comment_id)

    def reopen(self, comment_id: str) -> dict[str, Any]:
        row = self._row(comment_id)
        if row['status'] == 'resolved':
            self._update(comment_id, status='done', resolved_at=None)
        return self.get(comment_id)

    def subscribe(self, canvas_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.setdefault(canvas_id, set()).add(queue)
        return queue

    def unsubscribe(self, canvas_id: str, queue: asyncio.Queue) -> None:
        self.subscribers.get(canvas_id, set()).discard(queue)

    async def recover(self) -> None:
        """After a restart: runs that were in flight are gone; queued comments start again."""
        with self.database.connection() as connection:
            stale = [row['id'] for row in connection.execute(
                "SELECT id FROM canvas_comments WHERE status IN ('running', 'waiting')").fetchall()]
            canvases = [row['canvas_id'] for row in connection.execute(
                "SELECT DISTINCT canvas_id FROM canvas_comments WHERE status = 'queued'").fetchall()]
        for comment_id in stale:
            self._update(comment_id, status='failed', outcome='服务重启，这一轮被中断了。回复它可以接着做。')
        for canvas_id in canvases:
            await self.pump(canvas_id)

    # ------------------------------------------------------------ scheduler

    async def pump(self, canvas_id: str) -> None:
        """Start queued comments while there is room (MAX_PARALLEL per canvas, one per node)."""
        lock = self._locks.setdefault(canvas_id, asyncio.Lock())
        async with lock:
            await asyncio.sleep(0)  # let a just-finished run's task complete first
            with self.database.connection() as connection:
                rows = [dict(row) for row in connection.execute(
                    "SELECT * FROM canvas_comments WHERE canvas_id = ? AND status IN ('queued', 'running', 'waiting') "
                    'ORDER BY updated_at, rowid', (canvas_id,)).fetchall()]
            active = [row for row in rows if row['status'] in ACTIVE]
            busy_nodes = {row['node_id'] for row in active if row['node_id']}
            slots = MAX_PARALLEL - len(active)
            nodes = self._node_ids(canvas_id)
            for row in rows:
                if slots <= 0:
                    break
                if row['status'] != 'queued':
                    continue
                if row['node_id'] and row['node_id'] in busy_nodes:
                    continue
                if row['node_id']:
                    busy_nodes.add(row['node_id'])  # later comments on this node wait for this one
                if row['node_id'] and row['node_id'] not in nodes:
                    self._update(row['id'], status='failed', pending_text=None, outcome='节点已经删除了，没法再处理。')
                    continue
                if await self._start(row):
                    slots -= 1

    async def _start(self, row: dict[str, Any]) -> bool:
        text = row['pending_text'] or row['text']
        first = not self._has_runs(row['session_id'])
        self._update(row['id'], status='running', pending_text=None, outcome=None)
        self._last_text.pop(row['id'], None)
        try:
            await self.agent.send_message(
                row['session_id'], text,
                focus_node_ids=[row['node_id']] if row['node_id'] else None,
                context=self.location_context(row) if first else None,
            )
        except DomainError as error:
            self._update(row['id'], status='failed', outcome=error.message)
            return False
        except Exception as error:  # never leave a comment stuck in "running"
            log.exception('starting comment %s failed', row['id'])
            self._update(row['id'], status='failed', outcome=f'没能开始：{error}')
            return False
        return True

    def location_context(self, row: dict[str, Any]) -> str:
        """Text the agent gets with a comment's first message: what it is pinned to."""
        lines = ['[画布留言] 这条消息是用户钉在画布上的一条留言，按它的意思去做；做完用一两句话说明改了什么。']
        kind = row['anchor_kind']
        if kind == 'canvas':
            lines.append(
                f"[留言位置] 画布空白处，坐标 ({row['x']:.0f}, {row['y']:.0f})。"
                '要新建节点的话，以这个坐标为起点摆放。'
            )
            return '\n'.join(lines)
        node = self._node(row['canvas_id'], row['node_id'])
        title = (node or {}).get('data', {}).get('title') or '未命名节点'
        label = {'image': '图片节点', 'video': '视频节点', 'note': '便签'}.get((node or {}).get('nodeType'), '节点')
        if kind == 'node':
            lines.append(f"[留言位置] {label}「{title}」[{row['node_id']}]")
            return '\n'.join(lines)
        where = f"画面内 ({row['x'] * 100:.0f}%, {row['y'] * 100:.0f}%) 处（从左上角量起）"
        at = f"第 {row['time']:.1f} 秒那一帧，" if row['time'] is not None else ''
        lines.append(f"[留言位置] {label}「{title}」[{row['node_id']}] 第 {row['version']} 版，{at}{where}")
        return '\n'.join(lines)

    # --------------------------------------------------------------- events

    def _on_event(self, session_id: str, event: dict) -> None:
        kind = event.get('kind')
        if kind not in ('assistant_text', 'confirm_request', 'confirm_resolved', 'run_finished', 'error'):
            return
        row = self.for_session(session_id)
        if row is None:
            return
        if kind == 'assistant_text':
            self._last_text[row['id']] = str(event.get('text') or '')
        elif kind == 'error':
            self._last_text[row['id']] = str(event.get('message') or '')
        elif kind == 'confirm_request' and row['status'] == 'running':
            self._update(row['id'], status='waiting')
        elif kind == 'confirm_resolved' and row['status'] == 'waiting':
            self._update(row['id'], status='running')
        elif kind == 'run_finished' and row['status'] in ACTIVE:
            status = event.get('status')
            last = ' '.join(self._last_text.pop(row['id'], '').split())[:300]
            if status == 'completed':
                self._update(row['id'], status='done', outcome=last or None)
            else:
                outcome = '已停止。' if status == 'stopped' else (last or 'Agent 出错了。')
                self._update(row['id'], status='failed', outcome=outcome)
            try:
                asyncio.get_running_loop().create_task(self.pump(row['canvas_id']))
            except RuntimeError:  # no loop (sync tests): nothing to schedule
                pass

    # -------------------------------------------------------------- helpers

    def _validate_anchor(self, canvas_id: str, anchor: dict[str, Any]) -> dict[str, Any]:
        kind = anchor.get('kind')
        if kind == 'canvas':
            return {'kind': kind, 'x': _number(anchor, 'x'), 'y': _number(anchor, 'y')}
        if kind not in ('node', 'media'):
            raise DomainError('INVALID_PAYLOAD', 'anchor.kind 只能是 canvas、node 或 media')
        node_id = str(anchor.get('nodeId') or '')
        node = self._node(canvas_id, node_id) if node_id else None
        if node is None:
            raise DomainError('NOT_FOUND', f'Node {node_id} was not found')
        if kind == 'node':
            return {'kind': kind, 'node_id': node_id}
        if node['nodeType'] not in ('image', 'video'):
            raise DomainError('INVALID_PAYLOAD', '只有图片和视频节点能钉在画面上')
        asset_id = node['data'].get('assetId')
        if not asset_id:
            raise DomainError('INVALID_PAYLOAD', '这个节点还没有图片或视频')
        x, y = _number(anchor, 'x'), _number(anchor, 'y')
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise DomainError('INVALID_PAYLOAD', '画面内的位置 x、y 要在 0 到 1 之间')
        time = None
        if node['nodeType'] == 'video':
            time = _number(anchor, 'time')
            if time < 0:
                raise DomainError('INVALID_PAYLOAD', '时间点不能是负数')
        version = self.versions.latest(canvas_id, node_id, asset_id)
        return {'kind': kind, 'node_id': node_id, 'x': x, 'y': y, 'time': time, 'version': version}

    def _node(self, canvas_id: str, node_id: str) -> dict[str, Any] | None:
        try:
            return self.repository.node_snapshot(canvas_id, node_id)
        except DomainError:
            return None

    def _node_ids(self, canvas_id: str) -> set[str]:
        with self.database.connection() as connection:
            return {row['id'] for row in connection.execute(
                'SELECT id FROM canvas_nodes WHERE canvas_id = ?', (canvas_id,)).fetchall()}

    def _has_runs(self, session_id: str) -> bool:
        with self.database.connection() as connection:
            return connection.execute(
                'SELECT 1 FROM agent_runs WHERE session_id = ? LIMIT 1', (session_id,)).fetchone() is not None

    def _row(self, comment_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute('SELECT * FROM canvas_comments WHERE id = ?', (comment_id,)).fetchone()
        if row is None:
            raise DomainError('NOT_FOUND', f'Comment {comment_id} was not found')
        return dict(row)

    def _update(self, comment_id: str, **fields: Any) -> None:
        sets, params = ['updated_at = CURRENT_TIMESTAMP'], []
        for key, value in fields.items():
            if key == 'resolved_at' and value == 'now':
                sets.append('resolved_at = CURRENT_TIMESTAMP')
                continue
            sets.append(f'{key} = ?')
            params.append(value)
        with self.database.transaction() as connection:
            connection.execute(f"UPDATE canvas_comments SET {', '.join(sets)} WHERE id = ?", (*params, comment_id))
        self._publish(comment_id)

    def _publish(self, comment_id: str) -> None:
        row = self._row(comment_id)
        queues: Iterable[asyncio.Queue] = list(self.subscribers.get(row['canvas_id'], ()))
        if not queues:
            return
        comment = self._public(row, self._node_ids(row['canvas_id']))
        for queue in queues:
            queue.put_nowait(comment)

    @staticmethod
    def _public(row: dict[str, Any], node_ids: set[str]) -> dict[str, Any]:
        anchor: dict[str, Any] = {'kind': row['anchor_kind']}
        if row['anchor_kind'] == 'canvas':
            anchor.update(x=row['x'], y=row['y'])
        else:
            anchor['nodeId'] = row['node_id']
        if row['anchor_kind'] == 'media':
            anchor.update(version=row['version'], x=row['x'], y=row['y'], time=row['time'])
        return {
            'id': row['id'],
            'canvasId': row['canvas_id'],
            'sessionId': row['session_id'],
            'anchor': anchor,
            'text': row['text'],
            'status': row['status'],
            'outcome': row['outcome'],
            'pendingReply': row['pending_text'] if row['pending_text'] != row['text'] else None,
            'nodeMissing': bool(row['node_id']) and row['node_id'] not in node_ids,
            'createdAt': row['created_at'],
            'updatedAt': row['updated_at'],
            'resolvedAt': row['resolved_at'],
        }


def _number(anchor: dict[str, Any], key: str) -> float:
    value = anchor.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DomainError('INVALID_PAYLOAD', f'anchor.{key} 要是一个数字')
    return float(value)


def comment_json(comment: dict[str, Any]) -> str:
    return json.dumps(comment, ensure_ascii=False)
