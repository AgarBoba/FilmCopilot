"""One-line summaries of chats, so other chats on the canvas know what each one is about.

After every finished turn of a panel chat, a small model rewrites that chat's summary from the
previous summary and what this turn said and did. The summary goes into `agent_sessions.summary`
and is what the "[这张画布上的其他对话]" lines show (instead of the first words of the last
message), and recall searches it.

Runs in the background and never blocks or fails a turn: if summarising fails, the old summary
(or the last-message fallback) stays.
"""
from collections.abc import Awaitable, Callable
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

SUMMARY_MODEL = 'claude-haiku-4-5-20251001'
MAX_SUMMARY = 120
MAX_INPUT = 6000

Summarizer = Callable[[str], Awaitable[str]]

INSTRUCTIONS = """你给一个创作对话写摘要，供同一张画布上的其他对话参考。

只输出一句中文，不超过 80 个字，不加引号、标题或解释。写清楚：
- 这个对话在做什么（对象用画布上的名字，比如「图片 2」「开场分镜」）；
- 做到哪了、定了什么；
- 还没定或在等用户的事（如果有）。
已经过时的内容不要保留；用户撤销的改动不算已完成。"""


def build_input(previous: str | None, title: str | None, transcript: list[dict[str, Any]]) -> str:
    """The text the summariser reads: the old summary, then this turn in order."""
    lines = [f"对话名称：{title or '未命名对话'}", f"之前的摘要：{previous or '（还没有）'}", '', '这一轮：']
    for event in transcript:
        kind = event.get('kind')
        if kind == 'user_message':
            lines.append(f"用户：{event.get('text', '')}")
        elif kind == 'assistant_text':
            lines.append(f"助手：{event.get('text', '')}")
        elif kind == 'tool_step' and not event.get('isError'):
            lines.append(f"（操作）{event.get('summary', '')}")
        elif kind == 'memory_change':
            lines.append(f"（记下）{event.get('content', '')}")
        elif kind == 'confirm_resolved' and not event.get('approved'):
            lines.append('（用户拒绝了一步操作）' + (f"：{event['note']}" if event.get('note') else ''))
        elif kind == 'run_undone':
            lines.append('（用户撤销了这一轮的改动）')
        elif kind == 'error':
            lines.append(f"（出错）{event.get('message', '')}")
    text = '\n'.join(lines)
    if len(text) > MAX_INPUT:
        # Keep the start (old summary, the request) and the end (where it got to).
        text = text[: MAX_INPUT // 2] + '\n……\n' + text[-MAX_INPUT // 2:]
    return text


def clean(raw: str) -> str:
    """First non-empty line, without quotes, capped."""
    line = next((part.strip() for part in str(raw or '').splitlines() if part.strip()), '')
    line = line.strip('"“”「」\'')
    return line[:MAX_SUMMARY]


def sdk_summarizer(auth: str) -> Summarizer:
    """Ask a small model through the Agent SDK, so it works with an API key and with a subscription."""

    async def summarize(text: str) -> str:
        from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

        if auth == 'subscription':
            os.environ.pop('ANTHROPIC_API_KEY', None)
        options = ClaudeAgentOptions(
            model=SUMMARY_MODEL, system_prompt=INSTRUCTIONS, tools=[], allowed_tools=[],
            setting_sources=[], max_turns=1,
        )
        parts: list[str] = []
        async for message in query(prompt=text, options=options):
            if isinstance(message, AssistantMessage):
                parts.extend(block.text for block in message.content if isinstance(block, TextBlock))
        return ''.join(parts)

    return summarize
