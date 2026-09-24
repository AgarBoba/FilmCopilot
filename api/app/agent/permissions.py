"""Permission rules for agent tool calls (spec 4.1).

These are the hard rules. Skills and the system prompt can change how the agent works,
but every write tool call passes through `decide` before it runs, whatever the model
or a skill says.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

Decision = Literal['allow', 'ask', 'deny']

READ_ONLY_TOOLS = {'get_canvas', 'get_node', 'view_asset', 'wait_for_generation'}
WRITE_TOOLS = {
    'create_nodes', 'update_node', 'connect', 'disconnect', 'move_nodes',
    'duplicate_nodes', 'delete_nodes', 'generate',
}
ASK_IN_DEFAULT_MODE = {'generate', 'delete_nodes'}
MEMORY_TOOLS = {'remember', 'update_memory', 'forget', 'recall'}


@dataclass
class RunState:
    """What the permission check needs to know about the current run."""
    generation_count: int = 0
    generation_cap: int = 4
    node_types: dict[str, str] = field(default_factory=dict)  # node id -> image / video / note


def decide(tool_name: str, args: dict[str, Any], mode: str, run: RunState) -> tuple[Decision, str]:
    """(decision, reason). `reason` is shown to the user when confirmation is needed."""
    name = tool_name.split('__')[-1]  # accept "mcp__canvas__generate" as well as "generate"
    if name in READ_ONLY_TOOLS or name in MEMORY_TOOLS:
        return 'allow', ''
    if name not in WRITE_TOOLS:
        return 'deny', f'未知工具 {name}'

    if name == 'generate':
        node_ids = list(args.get('node_ids') or [])
        # Always ask, in every mode: video costs much more than an image.
        if any(run.node_types.get(node_id) == 'video' for node_id in node_ids):
            return 'ask', '包含视频生成（视频生成总是需要确认）'
        if run.generation_count + len(node_ids) > run.generation_cap:
            return 'ask', f'本轮生成次数将超过上限 {run.generation_cap} 次'

    if mode == 'confirm_all':
        return 'ask', ''
    if mode == 'confirm_generation':
        return ('ask', '') if name in ASK_IN_DEFAULT_MODE else ('allow', '')
    if mode == 'auto':
        return 'allow', ''
    return 'ask', ''  # unknown mode: be safe


def describe_request(tool_name: str, args: dict[str, Any], titles: dict[str, str]) -> str:
    """One line for the confirmation card, e.g. 生成 3 张图片：图片 2、图片 3、图片 4."""
    name = tool_name.split('__')[-1]

    def names(ids):
        return '、'.join(f"「{titles.get(node_id, node_id)}」" for node_id in ids)

    if name == 'generate':
        ids = list(args.get('node_ids') or [])
        return f'生成 {len(ids)} 个节点：{names(ids)}'
    if name == 'delete_nodes':
        ids = list(args.get('node_ids') or [])
        return f'删除 {len(ids)} 个节点：{names(ids)}'
    if name == 'create_nodes':
        return f"新建 {len(args.get('nodes') or [])} 个节点"
    if name == 'update_node':
        return f"修改{names([args.get('node_id')])}"
    if name == 'connect':
        return f"连接{names([args.get('source_id')])} → {names([args.get('target_id')])}"
    if name == 'disconnect':
        return f"断开{names([args.get('source_id')])} → {names([args.get('target_id')])}"
    if name == 'move_nodes':
        return f"移动 {len(args.get('positions') or [])} 个节点"
    if name == 'duplicate_nodes':
        return f"复制 {names(args.get('node_ids') or [])}"
    return name


@dataclass
class PendingConfirmation:
    id: str
    run_id: str
    tool_name: str
    summary: str
    reason: str
    future: asyncio.Future


MAX_NOTE_LENGTH = 2000


def request_node_ids(tool_input: dict[str, Any]) -> list[str]:
    """Existing nodes a tool call is about, so the canvas can mark them while it waits."""
    ids: list[str] = []
    for key in ('node_id', 'source_id', 'target_id'):
        if isinstance(tool_input.get(key), str):
            ids.append(tool_input[key])
    ids.extend(item for item in tool_input.get('node_ids') or [] if isinstance(item, str))
    for item in tool_input.get('positions') or []:
        if isinstance(item, dict) and isinstance(item.get('node_id') or item.get('nodeId'), str):
            ids.append(item.get('node_id') or item.get('nodeId'))
    return list(dict.fromkeys(ids))


class ConfirmationBroker:
    """Holds a tool call until the user answers in the agent panel (or it times out)."""

    def __init__(self, timeout_seconds: float = 600) -> None:
        self.timeout_seconds = timeout_seconds
        self.pending: dict[str, PendingConfirmation] = {}

    def open(self, run_id: str, tool_name: str, summary: str, reason: str) -> PendingConfirmation:
        request = PendingConfirmation(
            id=str(uuid4()), run_id=run_id, tool_name=tool_name, summary=summary, reason=reason,
            future=asyncio.get_running_loop().create_future(),
        )
        self.pending[request.id] = request
        return request

    async def wait(self, request: PendingConfirmation) -> tuple[bool, str]:
        """(approved, note). Timing out or the run being stopped counts as a refusal without a note."""
        try:
            return await asyncio.wait_for(asyncio.shield(request.future), self.timeout_seconds)
        except asyncio.TimeoutError:
            return False, ''
        finally:
            self.pending.pop(request.id, None)

    def resolve(self, request_id: str, approved: bool, note: str = '') -> bool:
        request = self.pending.get(request_id)
        if request is None or request.future.done():
            return False
        request.future.set_result((approved, (note or '').strip()[:MAX_NOTE_LENGTH]))
        return True

    def cancel_run(self, run_id: str) -> None:
        for request in list(self.pending.values()):
            if request.run_id == run_id and not request.future.done():
                request.future.set_result((False, ''))
