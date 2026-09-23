"""AgentService: runs Claude Agent SDK sessions against the canvas (spec 3, 4, 6.1).

One SDK client per agent session (kept alive between messages, resumable after a restart
through the SDK session id). Each user message starts a run. Everything the panel shows is
emitted as events: persisted ones get a message id so a reconnecting panel can catch up;
streaming text deltas are live-only.
"""
import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import logging
from typing import Any

from ..commands import CanvasCommandService
from ..config import PROJECT_ROOT
from ..domain import DomainError
from ..repositories import CanvasRepository
from ..schemas import CommandEnvelope
from .canvas_tools import CanvasTools, ToolResult
from .config import AgentConfig
from .mcp_server import READ_ONLY, build_handlers, build_server, qualified
from .permissions import ConfirmationBroker, RunState, decide, describe_request, request_node_ids
from .prompts import SYSTEM_PROMPT, build_user_message
from .store import AgentStore

log = logging.getLogger(__name__)

# Built lazily so importing this module (and the test suite) never needs the SDK CLI.
ClientFactory = Callable[[Any, dict[str, Any]], Any]


def sdk_client_factory(options: Any, handlers: dict[str, Any]) -> Any:
    from claude_agent_sdk import ClaudeSDKClient
    return ClaudeSDKClient(options=options)


@dataclass
class SessionRuntime:
    session_id: str
    canvas_id: str
    project_id: str
    sdk_session_id: str | None = None
    client: Any = None
    tools: CanvasTools | None = None
    run_id: str | None = None
    task: asyncio.Task | None = None
    handlers: dict[str, Any] = field(default_factory=dict)


class AgentService:
    def __init__(
        self,
        repository: CanvasRepository,
        command_service: CanvasCommandService,
        store: AgentStore,
        config: AgentConfig | None = None,
        client_factory: ClientFactory = sdk_client_factory,
    ) -> None:
        self.repository = repository
        self.command_service = command_service
        self.store = store
        self.config = config or AgentConfig.from_env()
        self.client_factory = client_factory
        self.broker = ConfirmationBroker(self.config.confirmation_timeout_seconds)
        self.sessions: dict[str, SessionRuntime] = {}
        self.subscribers: dict[str, set[asyncio.Queue]] = {}

    # --------------------------------------------------------------- public

    async def send_message(self, session_id: str, text: str, focus_node_ids: list[str] | None = None) -> dict:
        text = (text or '').strip()
        if not text:
            raise DomainError('INVALID_PAYLOAD', '消息不能为空')
        if not self.config.api_key_present:
            raise DomainError('AGENT_NOT_CONFIGURED', '没有配置 ANTHROPIC_API_KEY，请在 .env 里填写后重启')
        runtime = self._runtime(session_id)
        if runtime.task is not None and not runtime.task.done():
            raise DomainError('RUN_ACTIVE', 'Agent 还在处理上一条消息，等它结束或先停止')

        session = self.store.get_session(session_id)
        if not session.get('title'):
            self.store.set_session_title(session_id, text[:30])
        settings = self.store.get_settings(runtime.project_id)
        run = self.store.create_run(session_id, settings['permissionMode'])
        runtime.run_id = run['id']
        runtime.tools = CanvasTools(
            self.repository, self.command_service, self.store, runtime.canvas_id, run['id'], self.config
        )

        snapshot = self.repository.get_snapshot(runtime.canvas_id)
        titles = {node.id: node.data.get('title', '') for node in snapshot.nodes}
        focus = [(node_id, titles[node_id]) for node_id in (focus_node_ids or []) if node_id in titles]
        self._emit(session_id, run['id'], 'user_message', {'text': text, 'focus': [i for i, _ in focus]}, role='user')
        prompt = build_user_message(text, settings['permissionMode'], focus, settings['generationCap'])
        runtime.task = asyncio.create_task(self._run(runtime, run['id'], prompt))
        return run

    async def stop(self, run_id: str) -> None:
        runtime = self._runtime_for_run(run_id)
        if runtime is None or runtime.tools is None:
            return
        runtime.tools.stopped = True
        self.broker.cancel_run(run_id)
        if runtime.client is not None:
            try:
                await runtime.client.interrupt()
            except Exception:  # client may already be idle
                log.debug('interrupt failed', exc_info=True)

    def confirm(self, request_id: str, approved: bool, note: str = '') -> bool:
        return self.broker.resolve(request_id, approved, note)

    def undo(self, run_id: str) -> dict:
        run = self.store.get_run(run_id)
        if run['status'] == 'undone':
            raise DomainError('ALREADY_UNDONE', '这一轮已经撤销过了')
        session = self.store.get_session(run['session_id'])
        canvas_id = session['canvas_id']
        revision = self.repository.get_snapshot(canvas_id).revision
        result = self.command_service.execute(canvas_id, CommandEnvelope(
            command='undo_agent_run', baseRevision=revision, idempotencyKey=f'undo:{run_id}',
            payload={'runId': run_id}, actor='agent',
        ))
        self._emit(session['id'], run_id, 'run_undone', result.payload, role='system_event')
        return result.payload

    def subscribe(self, session_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.setdefault(session_id, set()).add(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        self.subscribers.get(session_id, set()).discard(queue)

    def active_run(self, session_id: str) -> str | None:
        runtime = self.sessions.get(session_id)
        if runtime and runtime.task and not runtime.task.done():
            return runtime.run_id
        return None

    async def close(self) -> None:
        for runtime in self.sessions.values():
            if runtime.tools:
                runtime.tools.stopped = True
            if runtime.task and not runtime.task.done():
                runtime.task.cancel()
            if runtime.client is not None:
                try:
                    await runtime.client.disconnect()
                except Exception:
                    log.debug('disconnect failed', exc_info=True)

    # ------------------------------------------------------------- internals

    def _runtime(self, session_id: str) -> SessionRuntime:
        runtime = self.sessions.get(session_id)
        if runtime is None:
            session = self.store.get_session(session_id)
            runtime = SessionRuntime(
                session_id=session_id,
                canvas_id=session['canvas_id'],
                project_id=session['project_id'],
                sdk_session_id=session.get('sdk_session_id'),
            )
            self.sessions[session_id] = runtime
        return runtime

    def _runtime_for_run(self, run_id: str) -> SessionRuntime | None:
        return next((item for item in self.sessions.values() if item.run_id == run_id), None)

    async def _client(self, runtime: SessionRuntime) -> Any:
        if runtime.client is not None:
            return runtime.client
        from claude_agent_sdk import ClaudeAgentOptions

        async def on_step(name: str, args: dict[str, Any], result: ToolResult) -> None:
            self._emit(runtime.session_id, runtime.run_id, 'tool_step', {
                'tool': name,
                'summary': result.summary or name,
                'touched': result.touched,
                'isError': result.is_error,
                'detail': result.text[:1000],
                'imageCount': len(result.images),
            }, role='tool_call')

        runtime.handlers = build_handlers(lambda: runtime.tools, on_step)

        async def can_use_tool(name: str, tool_input: dict[str, Any], context: Any):
            return await self._permission(runtime, name, tool_input)

        options = ClaudeAgentOptions(
            model=self.config.model,
            system_prompt=SYSTEM_PROMPT,
            tools=[],  # no built-in file / shell / web tools
            mcp_servers={'canvas': build_server(runtime.handlers)},
            # Read-only tools run freely; write tools must NOT be listed here, or they would
            # skip can_use_tool (see Task 0 notes).
            allowed_tools=[qualified(name) for name in READ_ONLY],
            can_use_tool=can_use_tool,
            include_partial_messages=True,
            setting_sources=[],
            cwd=str(PROJECT_ROOT),
            resume=runtime.sdk_session_id,
        )
        client = self.client_factory(options, runtime.handlers)
        await client.connect()
        runtime.client = client
        return client

    async def _permission(self, runtime: SessionRuntime, name: str, tool_input: dict[str, Any]):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        run_id = runtime.run_id
        if runtime.tools is None or run_id is None or runtime.tools.stopped:
            return PermissionResultDeny(message='用户已停止这一轮任务。')
        settings = self.store.get_settings(runtime.project_id)
        run = self.store.get_run(run_id)
        snapshot = self.repository.get_snapshot(runtime.canvas_id)
        state = RunState(
            generation_count=run['generation_count'],
            generation_cap=settings['generationCap'],
            node_types={node.id: node.nodeType for node in snapshot.nodes},
        )
        decision, reason = decide(name, tool_input, run['permission_mode'], state)
        if decision == 'allow':
            return PermissionResultAllow()
        if decision == 'deny':
            return PermissionResultDeny(message=reason or '这个工具不能用。')

        titles = {node.id: node.data.get('title', '') for node in snapshot.nodes}
        summary = describe_request(name, tool_input, titles)
        request = self.broker.open(run_id, name, summary, reason)
        self.store.set_run_status(run_id, 'waiting_confirmation')
        self._emit(runtime.session_id, run_id, 'confirm_request', {
            'requestId': request.id, 'summary': summary, 'reason': reason,
            'touched': [i for i in request_node_ids(tool_input) if i in titles],
        }, role='system_event')
        approved, note = await self.broker.wait(request)
        if self.store.get_run(run_id)['status'] == 'waiting_confirmation':
            self.store.set_run_status(run_id, 'running')
        self._emit(runtime.session_id, run_id, 'confirm_resolved', {
            'requestId': request.id, 'approved': approved, 'note': note,
        }, role='system_event')
        if approved:
            if note:
                # The call runs as proposed; the note rides back on this tool's result.
                runtime.tools.confirmation_notes.append(note)
            return PermissionResultAllow()
        if runtime.tools.stopped:
            return PermissionResultDeny(message='用户已停止这一轮任务。', interrupt=True)
        if note:
            return PermissionResultDeny(message=(
                f'用户拒绝了：{summary}。用户补充：{note}\n'
                '按用户的补充调整后再继续；如果补充里的意思不清楚，先问用户。'
            ))
        return PermissionResultDeny(message=f'用户拒绝了：{summary}。不要重试或换个方式再做，先问用户想怎么调整。')

    async def _run(self, runtime: SessionRuntime, run_id: str, prompt: str) -> None:
        from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, SystemMessage, TextBlock

        status, cost, error_text = 'completed', None, None
        try:
            client = await self._client(runtime)
            await client.query(prompt)
            async for message in client.receive_response():
                if isinstance(message, StreamEvent):
                    event = message.event or {}
                    delta = event.get('delta') or {}
                    if event.get('type') == 'content_block_delta' and delta.get('type') == 'text_delta':
                        self._emit(runtime.session_id, run_id, 'text_delta', {'text': delta.get('text', '')})
                elif isinstance(message, SystemMessage):
                    if message.subtype == 'init' and message.data.get('session_id'):
                        self._remember_sdk_session(runtime, message.data['session_id'])
                    elif message.subtype == 'api_retry' and message.data.get('error_status') in (401, 403):
                        error_text = 'Anthropic API 认证失败：检查 .env 里的 ANTHROPIC_API_KEY 和网络代理。'
                        await client.interrupt()
                elif isinstance(message, AssistantMessage):
                    if message.error:
                        error_text = f'模型调用出错：{message.error}'
                    text = ''.join(block.text for block in message.content if isinstance(block, TextBlock))
                    if text.strip():
                        self._emit(runtime.session_id, run_id, 'assistant_text', {'text': text}, role='assistant')
                elif isinstance(message, ResultMessage):
                    cost = message.total_cost_usd
                    if message.session_id:
                        self._remember_sdk_session(runtime, message.session_id)
                    if message.is_error and not error_text:
                        error_text = '; '.join(message.errors or []) or message.result or '模型返回错误'
        except asyncio.CancelledError:
            status = 'stopped'
            raise
        except Exception as error:  # surface to the panel instead of dying silently
            log.exception('agent run failed')
            error_text = error_text or f'Agent 出错：{error}'
            runtime.client = None  # rebuild the client next time
        finally:
            if runtime.tools is not None and runtime.tools.stopped:
                status = 'stopped'
            elif error_text:
                status = 'failed'
            if error_text and status != 'stopped':
                self._emit(runtime.session_id, run_id, 'error', {'message': error_text}, role='system_event')
            self.broker.cancel_run(run_id)
            self.store.set_run_status(run_id, status)
            self._emit(runtime.session_id, run_id, 'run_finished', {
                'status': status, 'costUsd': cost,
            }, role='system_event')
            runtime.tools = None
            runtime.run_id = None

    def _remember_sdk_session(self, runtime: SessionRuntime, sdk_session_id: str) -> None:
        if runtime.sdk_session_id != sdk_session_id:
            runtime.sdk_session_id = sdk_session_id
            self.store.set_sdk_session(runtime.session_id, sdk_session_id)

    def _emit(self, session_id: str, run_id: str | None, kind: str, payload: dict, role: str | None = None) -> dict:
        """Persist (when `role` is given) and push to every open panel of this session."""
        body = {'kind': kind, **payload}
        message_id = self.store.add_message(session_id, role, body, run_id) if role else None
        event = {'id': message_id, 'runId': run_id, **body}
        for queue in list(self.subscribers.get(session_id, ())):
            queue.put_nowait(event)
        return event
