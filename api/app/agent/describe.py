"""Short descriptions of pictures and videos the agent has looked at.

The first time view_asset shows an asset, a small model writes one or two sentences about what
is in it, in the background, and the text is kept in assets.metadata_json["description"]. Later
get_canvas shows the start of it and get_node all of it, so later turns and other chats know
roughly what a picture shows without loading it again. Assets never change (a new picture is a
new asset), so a description never goes stale.

Best effort: describing never blocks or fails a tool call; if it fails, nothing is stored and
the next view_asset of that asset tries again. A description is for knowing what is in a
picture, not for judging details; that still needs view_asset.
"""
import asyncio
from collections.abc import Awaitable, Callable
import json
import logging
import os
from typing import Any

from ..db import Database

log = logging.getLogger(__name__)

DESCRIBE_MODEL = 'claude-haiku-5-5'
MAX_DESCRIPTION = 200
PREVIEW = 40
TIMEOUT_SECONDS = 90

# (kind, images) -> raw text. images are {'data', 'mimeType'}; a video comes as 3 frames.
Describer = Callable[[str, list[dict[str, Any]]], Awaitable[str]]

INSTRUCTIONS = """你给创作画布上的一张图片（或一段视频的开头、中间、结尾 3 帧）写画面描述。之后的对话会读这段描述来知道画里有什么，不再看图。

只输出一两句中文，不超过 100 个字，不加引号、标题或解释。依次写：
- 主体：是谁 / 是什么，外观要点（颜色、服装、特征）；
- 动作或姿态、所在场景；
- 景别和构图、光线色调、画风；
- 视频再补一句画面怎么变化（动作、镜头运动）。
只写看得到的，不猜剧情，不评价好坏。画面里有文字就照写。"""


def description_of(asset: dict[str, Any] | None) -> str:
    """The stored description of an asset row (snapshot form with 'metadata', or raw with 'metadata_json')."""
    if not asset:
        return ''
    metadata = asset.get('metadata')
    if metadata is None and asset.get('metadata_json'):
        try:
            metadata = json.loads(asset['metadata_json'])
        except ValueError:
            metadata = None
    return str((metadata or {}).get('description') or '') if isinstance(metadata, dict) else ''


def preview(text: str) -> str:
    return text if len(text) <= PREVIEW else text[:PREVIEW] + '…'


def load(database: Database, asset_id: str) -> str:
    with database.connection() as connection:
        row = connection.execute('SELECT metadata_json FROM assets WHERE id = ?', (asset_id,)).fetchone()
    return description_of(dict(row)) if row else ''


def save(database: Database, asset_id: str, text: str) -> None:
    with database.transaction() as connection:
        row = connection.execute('SELECT metadata_json FROM assets WHERE id = ?', (asset_id,)).fetchone()
        if row is None:
            return
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except ValueError:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata['description'] = text
        metadata['descriptionModel'] = DESCRIBE_MODEL
        connection.execute('UPDATE assets SET metadata_json = ? WHERE id = ?',
                           (json.dumps(metadata, ensure_ascii=False), asset_id))


def clean(raw: str) -> str:
    """One line, without quotes, capped."""
    text = ' '.join(part.strip() for part in str(raw or '').splitlines() if part.strip())
    text = text.strip('"“”「」\'')
    return text[:MAX_DESCRIPTION]


class AssetDescriber:
    """Describes assets in the background, at most once at a time per asset."""

    def __init__(self, database: Database, describer: Describer) -> None:
        self.database = database
        self.describer = describer
        self._tasks: dict[str, asyncio.Task] = {}

    def schedule(self, asset_id: str, kind: str, images: list[dict[str, Any]]) -> None:
        if not images or asset_id in self._tasks:
            return
        try:
            loop = asyncio.get_running_loop()
            if load(self.database, asset_id):
                return
        except RuntimeError:  # no event loop (plain sync caller): skip, the next view tries again
            return
        except Exception:
            log.warning('reading the description of asset %s failed', asset_id, exc_info=True)
            return
        self._tasks[asset_id] = loop.create_task(self._describe(asset_id, kind, images))

    async def _describe(self, asset_id: str, kind: str, images: list[dict[str, Any]]) -> None:
        try:
            text = clean(await asyncio.wait_for(self.describer(kind, images), TIMEOUT_SECONDS))
            if text:
                save(self.database, asset_id, text)
        except asyncio.CancelledError:
            raise
        except Exception:  # a description is a nice-to-have
            log.warning('describing asset %s failed', asset_id, exc_info=True)
        finally:
            self._tasks.pop(asset_id, None)

    async def wait(self) -> None:
        """For tests: let running descriptions finish."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    def close(self) -> None:
        for task in self._tasks.values():
            task.cancel()


def sdk_describer(auth: str) -> Describer:
    """Ask a small model through the Agent SDK, so it works with an API key and with a subscription."""

    async def describe(kind: str, images: list[dict[str, Any]]) -> str:
        from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

        if auth == 'subscription':
            os.environ.pop('ANTHROPIC_API_KEY', None)
        intro = '这是同一段视频的开头、中间、结尾 3 帧。' if kind == 'video' else '这是一张图片。'
        content: list[dict[str, Any]] = [{'type': 'text', 'text': intro}]
        content += [{'type': 'image', 'source': {'type': 'base64', 'media_type': image['mimeType'],
                                                  'data': image['data']}} for image in images]

        async def stream():
            yield {'type': 'user', 'message': {'role': 'user', 'content': content}, 'parent_tool_use_id': None}

        options = ClaudeAgentOptions(
            model=DESCRIBE_MODEL, system_prompt=INSTRUCTIONS, tools=[], allowed_tools=[],
            setting_sources=[], max_turns=1,
        )
        parts: list[str] = []
        async for message in query(prompt=stream(), options=options):
            if isinstance(message, AssistantMessage):
                parts.extend(block.text for block in message.content if isinstance(block, TextBlock))
        return ''.join(parts)

    return describe
