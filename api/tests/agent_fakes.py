"""A scripted stand-in for ClaudeSDKClient, so agent tests never call the real model.

A script is a list of steps for one `query()`:
    ('text', '回复文字')              -> streamed deltas + an AssistantMessage
    ('tool', 'create_nodes', {...})   -> goes through can_use_tool (write tools) and the real handler
    ('pause', seconds)                -> lets the test act mid-run (e.g. press stop)
"""
import asyncio
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolPermissionContext,
    ToolUseBlock,
)

from app.agent.mcp_server import READ_ONLY, qualified


class FakeClient:
    def __init__(self, options: Any, handlers: dict[str, Any], scripts: list[list[tuple]]):
        self.options = options
        self.handlers = handlers
        self.scripts = scripts
        self.prompts: list[str] = []
        self.denials: list[str] = []
        self.interrupted = False
        self.connected = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def interrupt(self):
        self.interrupted = True

    async def query(self, prompt: str):
        self.prompts.append(prompt)
        self.interrupted = False

    async def receive_response(self):
        script = self.scripts.pop(0) if self.scripts else []
        yield SystemMessage('init', {'session_id': 'sdk-session-1'})
        for index, step in enumerate(script):
            if self.interrupted:
                break
            kind = step[0]
            if kind == 'text':
                for chunk in (step[1][: len(step[1]) // 2], step[1][len(step[1]) // 2:]):
                    yield StreamEvent('u', 's', {
                        'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': chunk},
                    })
                yield AssistantMessage([TextBlock(step[1])], model='fake')
            elif kind == 'tool':
                name, args = step[1], step[2]
                yield AssistantMessage([ToolUseBlock(f'tool-{index}', qualified(name), args)], model='fake')
                if name not in READ_ONLY:
                    decision = await self.options.can_use_tool(qualified(name), args, ToolPermissionContext())
                    if not isinstance(decision, PermissionResultAllow):
                        self.denials.append(decision.message)
                        continue
                await self.handlers[name](args)
            elif kind == 'pause':
                await asyncio.sleep(step[1])
        yield ResultMessage(
            subtype='success', duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
            session_id='sdk-session-1', total_cost_usd=0.01,
        )


class FakeFactory:
    """Pass as AgentService(client_factory=...). `scripts` is shared by all clients it creates."""

    def __init__(self, *scripts: list[tuple]):
        self.scripts = list(scripts)
        self.clients: list[FakeClient] = []

    def __call__(self, options, handlers):
        client = FakeClient(options, handlers, self.scripts)
        self.clients.append(client)
        return client
