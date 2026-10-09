"""The user's plain comments, as the agent sees them: reference, not tasks.

A plain comment (not handed to the agent) is something the user wrote for themselves, like
"这里光线有点冷，回头再调". The agent should know about it when it works on that node, but
must not act on it unless the user asks. get_canvas / get_node show open ones through here.
"""
from typing import Any

from ..db import Database

MAX_TEXT = 80


def open_notes(database: Database, canvas_id: str) -> list[dict[str, Any]]:
    """Open plain comments on the canvas, oldest first, each with its latest reply."""
    with database.connection() as connection:
        rows = connection.execute(
            '''SELECT c.id, c.anchor_kind, c.node_id, c.x, c.y, c.time, c.text,
                      (SELECT COUNT(*) FROM comment_replies r WHERE r.comment_id = c.id) AS reply_count,
                      (SELECT r.text FROM comment_replies r WHERE r.comment_id = c.id ORDER BY r.id DESC LIMIT 1)
                          AS last_reply
               FROM canvas_comments c
               WHERE c.canvas_id = ? AND c.status = 'open' AND c.agent_status IS NULL
               ORDER BY c.created_at, c.rowid''',
            (canvas_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _short(text: str | None) -> str:
    text = ' '.join(str(text or '').split())
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + '…'


def describe(note: dict[str, Any]) -> str:
    """One line: where it is pinned and what it says."""
    if note['anchor_kind'] == 'media':
        where = f"画面 ({note['x'] * 100:.0f}%, {note['y'] * 100:.0f}%)"
        if note['time'] is not None:
            where = f"第 {note['time']:.1f} 秒，{where}"
    elif note['anchor_kind'] == 'node':
        where = '整个节点'
    else:
        where = f"画布 ({note['x']:.0f}, {note['y']:.0f})"
    line = f'{where}：「{_short(note["text"])}」'
    if note['reply_count']:
        line += f"（{note['reply_count']} 条回复，最新：「{_short(note['last_reply'])}」）"
    return line


HINT = '这些是用户写给自己的备注，只作参考：相关时可以考虑进去，但不要因为看到备注就主动去改；用户让你处理时再处理。'
