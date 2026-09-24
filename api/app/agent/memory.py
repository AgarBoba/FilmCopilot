"""Layered memory (spec 5): what the agent should know across chats.

- project:    the project's bible — characters, style, decisions, don'ts. Shared by every chat
              on every canvas of the project.
- preference: how this user likes to work, across projects (params, taste, prompt style).

The agent writes what the user states directly (status 'active', source 'user_stated').
Changing a memory never overwrites it: the old row is kept as 'superseded' so the history
can be shown and an update can be reverted. Removing marks it 'removed' for the same reason.
Search is plain substring matching, which works for Chinese without a tokenizer.
"""
import json
import re
from typing import Any

from ..db import Database
from ..domain import DomainError

LAYERS = ('project', 'preference')
CATEGORIES = {
    'project': {
        'character': '角色', 'style': '风格', 'setting': '场景与设定', 'decision': '已定的决定',
        'taboo': '不要做的', 'other': '其他',
    },
    'preference': {
        'params': '常用参数', 'aesthetic': '审美', 'prompt_style': '提示词写法',
        'workflow': '做事方式', 'communication': '沟通', 'other': '其他',
    },
}
MAX_CONTENT = 300
CONTEXT_BUDGET = 2000  # characters of memory put in front of each message

# Table: `memories` (created in db.py).



def _clean(content: str) -> str:
    text = ' '.join(str(content or '').split())
    if not text:
        raise DomainError('INVALID_PAYLOAD', '记忆内容不能为空')
    return text[:MAX_CONTENT]


def keywords(query: str) -> list[str]:
    """Words to look for: split on spaces and punctuation; long Chinese runs are kept whole."""
    parts = re.split(r'[\s,，。、；;：:！!？?「」“”"\'()（）]+', query or '')
    return [part for part in dict.fromkeys(p.strip().lower() for p in parts) if part][:8]


class MemoryStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    # ------------------------------------------------------------ reading

    def get(self, memory_id: int) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute('SELECT * FROM memories WHERE id = ?', (memory_id,)).fetchone()
        if row is None:
            raise DomainError('NOT_FOUND', f'找不到记忆 #{memory_id}')
        return self._row(row)

    def list_all(self, project_id: str, include_history: bool = True) -> dict[str, list[dict[str, Any]]]:
        """Everything the memory view shows: this project's memories and the user's preferences."""
        statuses = ('active', 'pending', 'superseded') if include_history else ('active',)
        marks = ','.join('?' * len(statuses))
        with self.database.connection() as connection:
            rows = connection.execute(
                f'''SELECT * FROM memories
                    WHERE status IN ({marks})
                      AND ((layer = 'project' AND project_id = ?) OR layer = 'preference')
                    ORDER BY updated_at DESC, id DESC''',
                (*statuses, project_id),
            ).fetchall()
        result: dict[str, list[dict[str, Any]]] = {'project': [], 'preference': []}
        for row in rows:
            item = self._row(row)
            result.setdefault(item['layer'], []).append(item)
        return result

    def context_block(self, project_id: str) -> str:
        """Active memories, grouped, within CONTEXT_BUDGET. Most recently touched first."""
        memories = self.list_all(project_id, include_history=False)
        sections = [('项目记忆（本项目所有对话共享）', 'project'), ('我的偏好（所有项目通用）', 'preference')]
        lines: list[str] = []
        used = 0
        for heading, layer in sections:
            items = memories.get(layer) or []
            if not items:
                continue
            lines.append(f'[{heading}]')
            for item in items:
                label = CATEGORIES[layer].get(item['category'], item['category'])
                line = f"- #{item['id']} {label}：{item['content']}"
                if used + len(line) > CONTEXT_BUDGET:
                    lines.append('- （还有更多，需要时用 recall 搜索）')
                    break
                lines.append(line)
                used += len(line)
        return '\n'.join(lines)

    def search(self, project_id: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
        words = keywords(query)
        if not words:
            return []
        memories = self.list_all(project_id)
        scored = []
        for item in memories['project'] + memories['preference']:
            text = f"{item['content']} {item['category']}".lower()
            score = sum(1 for word in words if word in text)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1]['status'] != 'active'))
        return [item for _, item in scored[:limit]]

    # ------------------------------------------------------------ writing

    def add(
        self, layer: str, content: str, category: str = 'other', *, project_id: str | None = None,
        source: str = 'user_stated', canvas_id: str | None = None, session_id: str | None = None,
        run_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """(memory, created). Saying the same thing twice returns the existing memory."""
        if layer not in LAYERS:
            raise DomainError('INVALID_PAYLOAD', 'layer 只能是 project 或 preference')
        text = _clean(content)
        category = category if category in CATEGORIES[layer] else 'other'
        scope = project_id if layer == 'project' else None
        with self.database.transaction() as connection:
            existing = connection.execute(
                '''SELECT * FROM memories WHERE layer = ? AND status = 'active' AND content = ?
                   AND (project_id IS ? OR project_id = ?)''',
                (layer, text, scope, scope),
            ).fetchone()
            if existing is not None:
                return self._row(existing), False
            cursor = connection.execute(
                '''INSERT INTO memories (layer, project_id, canvas_id, session_id, run_id, category, content,
                                         source, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')''',
                (layer, scope, canvas_id, session_id, run_id, category, text, source),
            )
            memory_id = int(cursor.lastrowid)
        return self.get(memory_id), True

    def supersede(self, memory_id: int, content: str, *, run_id: str | None = None,
                  session_id: str | None = None, category: str | None = None) -> dict[str, Any]:
        """The agent changes a memory: a new row replaces the old one, which is kept as history."""
        old = self.get(memory_id)
        if old['status'] != 'active':
            raise DomainError('INVALID_PAYLOAD', f'记忆 #{memory_id} 已经不是生效状态')
        text = _clean(content)
        new_category = category if category in CATEGORIES[old['layer']] else old['category']
        with self.database.transaction() as connection:
            cursor = connection.execute(
                '''INSERT INTO memories (layer, project_id, canvas_id, session_id, run_id, category, content,
                                         source, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'user_stated', 'active')''',
                (old['layer'], old['project_id'], old['canvas_id'], session_id, run_id, new_category, text),
            )
            new_id = int(cursor.lastrowid)
            connection.execute(
                "UPDATE memories SET status = 'superseded', superseded_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_id, memory_id),
            )
        return self.get(new_id)

    def remove(self, memory_id: int, *, run_id: str | None = None) -> dict[str, Any]:
        """Forget: hidden from the agent and the list, but kept so it can be restored."""
        self.get(memory_id)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE memories SET status = 'removed', removed_run_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (run_id, memory_id),
            )
        return self.get(memory_id)

    def edit(self, memory_id: int, content: str | None = None, category: str | None = None) -> dict[str, Any]:
        """The user edits a memory in the memory view: changed in place, marked as edited by them."""
        memory = self.get(memory_id)
        text = _clean(content) if content is not None else memory['content']
        new_category = category if category in CATEGORIES[memory['layer']] else memory['category']
        with self.database.transaction() as connection:
            connection.execute(
                '''UPDATE memories SET content = ?, category = ?, source = 'user_edited',
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
                (text, new_category, memory_id),
            )
        return self.get(memory_id)

    def delete(self, memory_id: int) -> None:
        """Deleting from the memory view is final (the user asked for it)."""
        self.get(memory_id)
        with self.database.transaction() as connection:
            connection.execute('UPDATE memories SET superseded_by = NULL WHERE superseded_by = ?', (memory_id,))
            connection.execute('DELETE FROM memories WHERE id = ?', (memory_id,))

    def revert(self, memory_id: int) -> dict[str, Any]:
        """Undo the agent's last change to this memory ("撤销" next to "记下了…")."""
        memory = self.get(memory_id)
        with self.database.transaction() as connection:
            if memory['status'] == 'removed':
                connection.execute(
                    "UPDATE memories SET status = 'active', removed_run_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (memory_id,),
                )
                return {'action': 'restored', 'memoryId': memory_id}
            previous = connection.execute(
                "SELECT id FROM memories WHERE superseded_by = ? AND status = 'superseded'", (memory_id,),
            ).fetchone()
            if previous is not None:
                connection.execute(
                    "UPDATE memories SET status = 'active', superseded_by = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (previous['id'],),
                )
            connection.execute('DELETE FROM memories WHERE id = ?', (memory_id,))
        return {'action': 'reverted', 'memoryId': memory_id, 'restoredId': previous['id'] if previous else None}

    def undo_run(self, run_id: str) -> int:
        """Undoing an agent turn also takes back what it remembered or forgot in that turn."""
        with self.database.connection() as connection:
            added = [row['id'] for row in connection.execute(
                'SELECT id FROM memories WHERE run_id = ? ORDER BY id DESC', (run_id,),
            ).fetchall()]
            removed = [row['id'] for row in connection.execute(
                "SELECT id FROM memories WHERE removed_run_id = ? AND status = 'removed'", (run_id,),
            ).fetchall()]
        for memory_id in removed:
            self.revert(memory_id)
        for memory_id in added:
            try:
                if self.get(memory_id)['status'] in ('active', 'removed'):
                    self.revert(memory_id)
            except DomainError:
                continue
        return len(added) + len(removed)

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        item = dict(row)
        item['evidence'] = json.loads(item.pop('evidence_json') or 'null')
        item['categoryLabel'] = CATEGORIES.get(item['layer'], {}).get(item['category'], item['category'])
        return item
