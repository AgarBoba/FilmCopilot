"""The agent's memory tools: remember, update_memory, forget, recall (spec 5.3).

They never need the user's confirmation. Every change is shown in the chat as
"记下了：…" with an undo, and undoing the whole turn takes it back too.
"""
from typing import Any

from ..domain import DomainError
from .canvas_tools import ToolResult
from .memory import CATEGORIES, MemoryStore
from .store import AgentStore

LAYER_LABELS = {'project': '项目记忆', 'preference': '我的偏好'}


class MemoryTools:
    def __init__(self, memory: MemoryStore, store: AgentStore, *, project_id: str, canvas_id: str,
                 session_id: str, run_id: str) -> None:
        self.memory = memory
        self.store = store
        self.project_id = project_id
        self.canvas_id = canvas_id
        self.session_id = session_id
        self.run_id = run_id

    def remember(self, layer: str, content: str, category: str = 'other') -> ToolResult:
        try:
            item, created = self.memory.add(
                layer, content, category, project_id=self.project_id, source='user_stated',
                canvas_id=self.canvas_id, session_id=self.session_id, run_id=self.run_id,
            )
        except DomainError as error:
            return ToolResult(error.message, is_error=True)
        if not created:
            return ToolResult(f"已经记过了：#{item['id']} {item['content']}", summary='这条已经记过了')
        return ToolResult(
            f"已记入{LAYER_LABELS[item['layer']]}：#{item['id']} {item['content']}",
            summary=f"记下了：{item['content']}",
            memory={'action': 'added', **_brief(item)},
        )

    def update_memory(self, memory_id: int, content: str, category: str | None = None) -> ToolResult:
        try:
            old = self.memory.get(int(memory_id))
            if old['layer'] == 'project' and old['project_id'] != self.project_id:
                return ToolResult('这条记忆不属于当前项目。', is_error=True)
            item = self.memory.supersede(int(memory_id), content, run_id=self.run_id,
                                         session_id=self.session_id, category=category)
        except (DomainError, ValueError) as error:
            return ToolResult(getattr(error, 'message', str(error)), is_error=True)
        return ToolResult(
            f"已把 #{old['id']}「{old['content']}」更新为 #{item['id']}「{item['content']}」。在回复里告诉用户改了什么。",
            summary=f"更新了记忆：{item['content']}",
            memory={'action': 'updated', 'previous': old['content'], **_brief(item)},
        )

    def forget(self, memory_id: int) -> ToolResult:
        try:
            item = self.memory.get(int(memory_id))
            if item['layer'] == 'project' and item['project_id'] != self.project_id:
                return ToolResult('这条记忆不属于当前项目。', is_error=True)
            if item['status'] != 'active':
                return ToolResult(f'#{memory_id} 已经不在生效的记忆里了。', is_error=True)
            self.memory.remove(int(memory_id), run_id=self.run_id)
        except (DomainError, ValueError) as error:
            return ToolResult(getattr(error, 'message', str(error)), is_error=True)
        return ToolResult(
            f"已忘掉 #{item['id']}：{item['content']}",
            summary=f"忘掉了：{item['content']}",
            memory={'action': 'removed', **_brief(item)},
        )

    def recall(self, query: str) -> ToolResult:
        memories = self.memory.search(self.project_id, query)
        messages = self.store.search_messages(self.project_id, query, exclude_session=self.session_id)
        if not memories and not messages:
            return ToolResult(f'没有找到和「{query}」有关的记忆或以前的对话。', summary=f'翻了翻记录：{query}')
        lines: list[str] = []
        if memories:
            lines.append('[记忆]')
            for item in memories:
                state = '' if item['status'] == 'active' else '（旧版本，已被更新）'
                lines.append(f"- #{item['id']} {LAYER_LABELS[item['layer']]} · {item['categoryLabel']}：{item['content']}{state}")
        if messages:
            lines.append('[以前的对话]')
            for hit in messages:
                who = '用户' if hit['role'] == 'user' else '你'
                lines.append(f"- 「{hit['sessionTitle']}」{hit['createdAt'][:10]} {who}说：{hit['snippet']}")
        return ToolResult('\n'.join(lines), summary=f'翻了翻记录：{query}')


def _brief(item: dict[str, Any]) -> dict[str, Any]:
    return {
        'memoryId': item['id'], 'layer': item['layer'], 'content': item['content'],
        'category': item['category'], 'categoryLabel': CATEGORIES[item['layer']].get(item['category'], '其他'),
    }
