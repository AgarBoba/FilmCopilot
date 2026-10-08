"""Turn the agent's use of built-in tools (Skill, web, task list) into panel events.

Canvas tools report themselves through our MCP handlers; built-in tools don't, so the run loop
feeds their tool_use / tool_result blocks in here. Kept free of SDK types (plain values in,
event dicts out) so it can be tested without the SDK.

Events (kind -> payload):
    skill_used   {skill, label}                      the agent loaded a skill
    web_search   {query, links: [{title, url}], isError}
    web_fetch    {url, isError}
    tasks        {items: [{id, subject, status}]}    the whole list after each change
"""
import json
import re
from typing import Any

from .skills import find

MAX_LINKS = 8
_TASK_ID = re.compile(r'#\s*(\d+)')
_URL = re.compile(r'https?://[^\s"\'<>\])]+')


def result_text(content: Any) -> str:
    """Tool result content is a string or a list of {type: text, text} blocks."""
    if isinstance(content, str):
        return content
    parts = []
    for item in content or []:
        if isinstance(item, dict) and item.get('type') == 'text':
            parts.append(str(item.get('text') or ''))
    return '\n'.join(parts)


def parse_search_links(text: str) -> list[dict[str, str]]:
    """Links from a WebSearch result. It lists them as `Links: [{"title": .., "url": ..}, ..]`;
    fall back to bare URLs if that format changes."""
    links: list[dict[str, str]] = []
    marker = text.find('Links:')
    if marker != -1:
        start = text.find('[', marker)
        depth, end = 0, -1
        for index in range(start, len(text)) if start != -1 else ():
            if text[index] == '[':
                depth += 1
            elif text[index] == ']':
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end != -1:
            try:
                for item in json.loads(text[start:end]):
                    if isinstance(item, dict) and str(item.get('url', '')).startswith('http'):
                        links.append({'title': str(item.get('title') or item['url'])[:120], 'url': item['url']})
            except (ValueError, TypeError):
                links = []
    if not links:
        seen = set()
        for url in _URL.findall(text):
            if url not in seen:
                seen.add(url)
                links.append({'title': url, 'url': url})
    return links[:MAX_LINKS]


class BuiltinToolTracker:
    """One per run: remembers tool inputs until their results arrive, and the task list."""

    def __init__(self) -> None:
        self.pending: dict[str, tuple[str, dict[str, Any]]] = {}
        self.tasks: dict[str, dict[str, str]] = {}

    def on_tool_use(self, tool_use_id: str, name: str, tool_input: dict[str, Any]) -> list[tuple[str, dict]]:
        if name == 'Skill':
            skill_id = str(tool_input.get('skill') or tool_input.get('name') or tool_input.get('command') or '')
            info = find(skill_id) or find(f'film-copilot:{skill_id}') or find(f'my-skills:{skill_id}')
            return [('skill_used', {'skill': skill_id, 'label': info.label if info else skill_id})]
        if name in ('WebSearch', 'WebFetch', 'TaskCreate', 'TaskUpdate'):
            self.pending[tool_use_id] = (name, dict(tool_input or {}))
        return []

    def on_tool_result(self, tool_use_id: str, content: Any, is_error: bool) -> list[tuple[str, dict]]:
        name, tool_input = self.pending.pop(tool_use_id, ('', {}))
        text = result_text(content)
        if name == 'WebSearch':
            return [('web_search', {
                'query': str(tool_input.get('query') or ''),
                'links': [] if is_error else parse_search_links(text),
                'isError': bool(is_error),
            })]
        if name == 'WebFetch':
            return [('web_fetch', {'url': str(tool_input.get('url') or ''), 'isError': bool(is_error)})]
        if name == 'TaskCreate' and not is_error:
            match = _TASK_ID.search(text)
            task_id = match.group(1) if match else str(len(self.tasks) + 1)
            self.tasks[task_id] = {'id': task_id, 'subject': str(tool_input.get('subject') or '').strip(),
                                   'status': 'pending'}
            return [self._snapshot()]
        if name == 'TaskUpdate' and not is_error:
            task_id = str(tool_input.get('taskId') or '').lstrip('#')
            task = self.tasks.get(task_id)
            if task is None:
                return []
            status = tool_input.get('status')
            if status == 'deleted':
                self.tasks.pop(task_id)
            else:
                if status:
                    task['status'] = str(status)
                if tool_input.get('subject'):
                    task['subject'] = str(tool_input['subject'])
            return [self._snapshot()]
        return []

    def _snapshot(self) -> tuple[str, dict]:
        return 'tasks', {'items': [dict(task) for task in self.tasks.values()]}
