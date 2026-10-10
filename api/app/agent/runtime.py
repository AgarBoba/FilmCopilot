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
import os
from typing import Any

from ..commands import CanvasCommandService
from ..config import PROJECT_ROOT
from ..credits import Credits, chat_price
from ..domain import DomainError
from ..repositories import CanvasRepository
from ..schemas import CommandEnvelope
from .canvas_tools import CanvasTools, ToolResult
from .config import MODELS, AgentConfig, explain_error
from .mcp_server import MEMORY_TOOLS, READ_ONLY, build_handlers, build_server, qualified
from .memory import MemoryStore
from .memory_tools import MemoryTools
from .permissions import ConfirmationBroker, RunState, decide, describe_request, request_node_ids
from .prompts import SYSTEM_PROMPT, build_user_message
from .store import AgentStore
from .builtin_events import BuiltinToolTracker
from .skills import BUILTIN_TOOLS, discover, find as find_skill, plugin_dirs
from .summary import Summarizer, build_input, clean as clean_summary, sdk_summarizer

log = logging.getLogger(__name__)

PREFIX_LABELS = {'memory': '项目记忆', 'other_chats': '其他对话摘要', 'task_log': '画布任务记录'}
# /compact with what this kind of chat needs kept (the canvas itself can always be read again).
COMPACT_COMMAND = (
    '/compact 这是影视创作画布上的助手对话。摘要里保留：用户的目标、偏好和已定的设定 / 风格；'
    '正在做和还没做完的事；提到过的节点名称和 ID；用户拒绝或撤销过的操作和原因。'
    '画布上每个节点的具体内容不用逐条保留，需要时会重新用工具读取。'
)

# Built lazily so importing this module (and the test suite) never needs the SDK CLI.
ClientFactory = Callable[[Any, dict[str, Any]], Any]


def user_input(text: str, images: list[dict[str, Any]]):
    """A user message with pictures, in the SDK's streaming-input form."""
    content: list[dict[str, Any]] = [{'type': 'text', 'text': text}]
    for image in images:
        if image.get('caption'):
            content.append({'type': 'text', 'text': image['caption']})
        content.append({'type': 'image', 'source': {
            'type': 'base64', 'media_type': image['mimeType'], 'data': image['data'],
        }})

    async def stream():
        yield {'type': 'user', 'message': {'role': 'user', 'content': content}, 'parent_tool_use_id': None}

    return stream()


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
    model: str | None = None  # model the live client is using
    skill_ids: tuple[str, ...] = ()  # skills the live client was started with
    # The SDK reports a running total cost for the conversation, and a resumed conversation
    # (new client after a restart, model or skill change) starts from the saved total, not 0.
    # A turn costs the difference from the last total we saw. None = look it up (last_cost_total).
    cost_total: float | None = None
    # What the model has already seen in this chat, so it isn't sent again unchanged:
    # 'prefix' -> the per-turn blocks (memory, other chats, task log); 'canvas' -> get_canvas lines.
    # Cleared when the chat is compacted, a turn fails, or the process restarts (sent in full then).
    seen_context: dict[str, Any] = field(default_factory=dict)
    context_tokens: int | None = None  # what the model saw on the chat's last request


class AgentService:
    def __init__(
        self,
        repository: CanvasRepository,
        command_service: CanvasCommandService,
        store: AgentStore,
        config: AgentConfig | None = None,
        client_factory: ClientFactory = sdk_client_factory,
        summarizer: Summarizer | None = None,
    ) -> None:
        self.repository = repository
        self.command_service = command_service
        self.store = store
        self.config = config or AgentConfig.from_env()
        self.client_factory = client_factory
        self.broker = ConfirmationBroker(self.config.confirmation_timeout_seconds)
        self.sessions: dict[str, SessionRuntime] = {}
        self.subscribers: dict[str, set[asyncio.Queue]] = {}
        self.memory = MemoryStore(repository.database)
        # Called with (session_id, event) for every emitted event (the comment scheduler
        # follows its sessions this way). Must not raise or block.
        self.listeners: list[Callable[[str, dict], None]] = []
        # Chat summaries (summary.py). Off when the client is faked (tests) unless one is given.
        if summarizer is None and client_factory is sdk_client_factory:
            summarizer = sdk_summarizer(self.config.auth)
        self.summarizer = summarizer
        self._summary_runs: dict[str, list[str]] = {}  # session id -> runs waiting to be summarised
        self._summary_tasks: dict[str, asyncio.Task] = {}

    # --------------------------------------------------------------- public

    async def send_message(
        self, session_id: str, text: str, focus_node_ids: list[str] | None = None, skill: str | None = None,
        context: str | None = None, images: list[dict[str, Any]] | None = None, comment_id: str | None = None,
    ) -> dict:
        """Start a run. `context` and `images` are for the model only (a comment's location:
        text before the user's words, pictures after them); the panel shows just the words.
        `comment_id` ties what this run generates to that comment (version history)."""
        text = (text or '').strip()
        chosen = find_skill(skill) if skill else None
        if skill and chosen is None:
            raise DomainError('UNKNOWN_SKILL', f'没有这个技能：{skill}')
        if not text and chosen is not None:
            text = f'用「{chosen.label}」'
        if not text:
            raise DomainError('INVALID_PAYLOAD', '消息不能为空')
        if not self.config.configured:
            raise DomainError(
                'AGENT_NOT_CONFIGURED',
                '没有配置 Agent 的模型登录：在 .env 里填 ANTHROPIC_API_KEY，或设 AGENT_AUTH=subscription 用 Claude 订阅，然后重启',
            )
        runtime = self._runtime(session_id)
        if runtime.task is not None and not runtime.task.done():
            raise DomainError('RUN_ACTIVE', 'Agent 还在处理上一条消息，等它结束或先停止')
        Credits(self.repository.database).require(0, '和 Agent 对话')

        session = self.store.get_session(session_id)
        if not session.get('title'):
            self.store.set_session_title(session_id, text[:30])
        settings = self.store.get_settings(runtime.project_id)
        run = self.store.create_run(session_id, settings['permissionMode'])
        runtime.run_id = run['id']
        runtime.tools = CanvasTools(
            self.repository, self.command_service, self.store, runtime.canvas_id, run['id'], self.config
        )
        runtime.tools.memory = MemoryTools(
            self.memory, self.store, project_id=runtime.project_id, canvas_id=runtime.canvas_id,
            session_id=session_id, run_id=run['id'],
        )
        runtime.tools.comment_id = comment_id
        compact = self._should_compact(runtime)
        if compact:
            runtime.seen_context.clear()  # the summary replaces what was sent: send it all again
        runtime.tools.shared = runtime.seen_context

        snapshot = self.repository.get_snapshot(runtime.canvas_id)
        titles = {node.id: node.data.get('title', '') for node in snapshot.nodes}
        focus = [(node_id, titles[node_id]) for node_id in (focus_node_ids or []) if node_id in titles]
        user_event = {'text': text, 'focus': [i for i, _ in focus]}
        if chosen is not None:
            user_event['skill'] = {'id': chosen.id, 'label': chosen.label}
        self._emit(session_id, run['id'], 'user_message', user_event, role='user')
        blocks = {
            'memory': self.memory.context_block(runtime.project_id),
            'other_chats': tuple(self._other_chats(runtime)),
            'task_log': tuple(self.task_log(runtime.canvas_id)),
        }
        sent = runtime.seen_context.setdefault('prefix', {})
        fresh = {key: value for key, value in blocks.items() if sent.get(key) != value}
        unchanged = [PREFIX_LABELS[key] for key, value in blocks.items() if value and key not in fresh]
        sent.update(blocks)
        prompt = build_user_message(
            text, settings['permissionMode'], focus, settings['generationCap'],
            memory=fresh.get('memory', ''),
            other_chats=list(fresh.get('other_chats') or []),
            task_log=list(fresh.get('task_log') or []),
            skill=(chosen.id, chosen.label) if chosen else None,
            context=context,
            unchanged=unchanged,
        )
        model = settings.get('model') or self.config.model
        runtime.task = asyncio.create_task(self._run(runtime, run['id'], prompt, model, images, compact))
        return run

    def task_log(self, canvas_id: str, limit: int = 10) -> list[str]:
        """Latest comment outcomes on this canvas, oldest first (spec 5)."""
        with self.repository.database.connection() as connection:
            rows = connection.execute(
                'SELECT text FROM canvas_task_log WHERE canvas_id = ? ORDER BY updated_at DESC, id DESC LIMIT ?',
                (canvas_id, limit),
            ).fetchall()
        return [row['text'] for row in reversed(rows)]

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
        payload = {**result.payload, 'memoriesReverted': self.memory.undo_run(run_id)}
        self._emit(session['id'], run_id, 'run_undone', payload, role='system_event')
        self.schedule_summary(session['id'], run_id)
        return payload

    def _other_chats(self, runtime: SessionRuntime, limit: int = 5) -> list[str]:
        """Other chats on this canvas, newest first, one line each (shared context between chats)."""
        lines = []
        for chat in self.store.list_sessions(runtime.project_id, runtime.canvas_id):
            if chat['id'] == runtime.session_id or chat.get('archived_at') or not chat.get('message_count'):
                continue
            if chat.get('kind') == 'comment':
                continue  # comments reach other chats through the canvas task log instead
            name = f"「{chat.get('title') or '未命名对话'}」{str(chat.get('last_active_at') or '')[:10]}"
            if chat.get('summary'):
                lines.append(f"{name}：{chat['summary']}")
            else:  # not summarised yet: the start of its last message
                lines.append(f"{name}，最后一句：{(chat.get('preview') or '')[:60]}")
            if len(lines) >= limit:
                break
        return lines

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
        for task in self._summary_tasks.values():
            task.cancel()
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

    async def _client(self, runtime: SessionRuntime, model: str) -> Any:
        skill_ids = tuple(skill.id for skill in discover())
        if runtime.client is not None and runtime.skill_ids != skill_ids:
            # Skills are read when a client starts: reconnect (same conversation, via resume)
            # so a skill added or changed since is picked up.
            try:
                await runtime.client.disconnect()
            except Exception:
                log.debug('disconnect for skill reload failed', exc_info=True)
            runtime.client = None
        if runtime.client is not None:
            if runtime.model != model:
                # Switching models keeps the conversation; it applies from this message on.
                await runtime.client.set_model(model)
                runtime.model = model
            return runtime.client
        from claude_agent_sdk import ClaudeAgentOptions

        if self.config.auth == 'subscription':
            # An API key in the environment would win over the subscription login.
            os.environ.pop('ANTHROPIC_API_KEY', None)

        async def on_step(name: str, args: dict[str, Any], result: ToolResult) -> None:
            if result.memory and not result.is_error:
                # Shown as "记下了：…  撤销" in the chat rather than as a canvas step.
                self._emit(runtime.session_id, runtime.run_id, 'memory_change', result.memory, role='system_event')
                return
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
            model=model,
            system_prompt=SYSTEM_PROMPT,
            # Built-ins: skills, web search / reading, the to-do list. No file or shell tools.
            tools=list(BUILTIN_TOOLS),
            # Skills come from two local plugin folders, not from setting_sources (see skills.py).
            plugins=[{'type': 'local', 'path': str(path)} for path in plugin_dirs()],
            skills=list(skill_ids),
            mcp_servers={'canvas': build_server(runtime.handlers)},
            # Read-only tools run freely; write tools must NOT be listed here, or they would
            # skip can_use_tool (see Task 0 notes).
            allowed_tools=[qualified(name) for name in (*READ_ONLY, *MEMORY_TOOLS)],
            can_use_tool=can_use_tool,
            include_partial_messages=True,
            setting_sources=[],
            cwd=str(PROJECT_ROOT),
            resume=runtime.sdk_session_id,
        )
        client = self.client_factory(options, runtime.handlers)
        await client.connect()
        runtime.client = client
        runtime.model = model
        runtime.skill_ids = skill_ids
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

    def _should_compact(self, runtime: SessionRuntime) -> bool:
        """Compress the older part of a long chat before this turn (see AgentConfig.compact_tokens)."""
        if not self.config.compact_tokens or not runtime.sdk_session_id:
            return False
        tokens = runtime.context_tokens
        if tokens is None:  # after a restart: the last turn's number from the transcript
            for message in reversed(self.store.list_messages(runtime.session_id)):
                if message['content'].get('kind') == 'run_finished':
                    tokens = message['content'].get('contextTokens')
                    break
        return bool(tokens and tokens > self.config.compact_tokens)

    async def _compact(self, runtime: SessionRuntime, run_id: str, client: Any) -> float | None:
        """Ask the CLI to summarise the chat so far (/compact). Returns its running cost total."""
        from claude_agent_sdk import ResultMessage, SystemMessage
        before, total, done = runtime.context_tokens, None, False
        await client.query(COMPACT_COMMAND)
        async for message in client.receive_response():
            if isinstance(message, SystemMessage) and message.subtype == 'compact_boundary':
                done = True
            elif isinstance(message, ResultMessage):
                total = message.total_cost_usd
        if done:
            runtime.context_tokens = None
            self._emit(runtime.session_id, run_id, 'context_compacted', {'tokens': before}, role='system_event')
        return total

    async def _run(
        self, runtime: SessionRuntime, run_id: str, prompt: str, model: str | None = None,
        images: list[dict[str, Any]] | None = None, compact: bool = False,
    ) -> None:
        model = model or self.config.model
        auth = self.config.auth
        from claude_agent_sdk import (
            AssistantMessage, ResultMessage, StreamEvent, SystemMessage, TextBlock, ToolResultBlock, ToolUseBlock,
            UserMessage,
        )
        tracker = BuiltinToolTracker()

        def emit_builtin(events: list[tuple[str, dict]]) -> None:
            for kind, payload in events:
                self._emit(runtime.session_id, run_id, kind, payload, role='tool_call')

        status, cost, error_text = 'completed', None, None
        context_tokens, context_window = None, None
        try:
            client = await self._client(runtime, model)
            if compact:
                try:
                    cost = await self._compact(runtime, run_id, client)
                except Exception:  # the turn still runs on the full chat
                    log.warning('compacting chat %s failed', runtime.session_id, exc_info=True)
            await client.query(user_input(prompt, images) if images else prompt)
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
                        error_text = explain_error('401 authentication', auth)
                        await client.interrupt()
                elif isinstance(message, AssistantMessage):
                    if message.usage and not message.parent_tool_use_id:
                        context_tokens = context_size(message.usage) or context_tokens
                    if message.error:
                        error_text = explain_error(f'模型调用出错：{message.error}', auth)
                    text = ''.join(block.text for block in message.content if isinstance(block, TextBlock))
                    if text.strip():
                        self._emit(runtime.session_id, run_id, 'assistant_text', {'text': text, 'model': model}, role='assistant')
                    for block in message.content:
                        if isinstance(block, ToolUseBlock) and not block.name.startswith('mcp__'):
                            emit_builtin(tracker.on_tool_use(block.id, block.name, block.input or {}))
                elif isinstance(message, UserMessage) and isinstance(message.content, list):
                    for block in message.content:
                        if isinstance(block, ToolResultBlock):
                            emit_builtin(tracker.on_tool_result(block.tool_use_id, block.content, bool(block.is_error)))
                elif isinstance(message, ResultMessage):
                    cost = message.total_cost_usd
                    context_window = context_limit(message.model_usage) or context_window
                    if message.session_id:
                        self._remember_sdk_session(runtime, message.session_id)
                    if message.is_error and not error_text:
                        error_text = explain_error('; '.join(message.errors or []) or message.result or '模型返回错误', auth)
        except asyncio.CancelledError:
            status = 'stopped'
            raise
        except Exception as error:  # surface to the panel instead of dying silently
            log.exception('agent run failed')
            error_text = error_text or explain_error(f'Agent 出错：{error}', auth)
            runtime.client = None  # rebuild the client next time
        finally:
            if runtime.tools is not None and runtime.tools.stopped:
                status = 'stopped'
            elif error_text:
                status = 'failed'
            if error_text and status != 'stopped':
                self._emit(runtime.session_id, run_id, 'error', {'message': error_text}, role='system_event')
            if status != 'completed':
                runtime.seen_context.clear()  # unsure what reached the model: send everything next time
            if context_tokens:
                runtime.context_tokens = context_tokens
            self.broker.cancel_run(run_id)
            self.store.set_run_status(run_id, status)
            run_cost, charged, balance = self._charge_turn(runtime, run_id, model, cost)
            self._emit(runtime.session_id, run_id, 'run_finished', {
                'status': status, 'costUsd': run_cost, 'model': model, 'auth': auth,
                'credits': charged, 'balance': balance, 'costTotal': cost,
                # How full the model's context was on its last request (for the panel's ring).
                'contextTokens': context_tokens, 'contextWindow': context_window or DEFAULT_CONTEXT_WINDOW,
            }, role='system_event')
            runtime.tools = None
            runtime.run_id = None
            if status in ('completed', 'stopped'):
                self.schedule_summary(runtime.session_id, run_id)

    def last_cost_total(self, session_id: str, exclude_run: str | None = None) -> float:
        """The SDK's running total at this chat's last finished turn (0 if none). Turns from before
        credits existed have no costTotal; their costUsd was that running total."""
        for message in reversed(self.store.list_messages(session_id)):
            content = message['content']
            if content.get('kind') != 'run_finished' or message.get('run_id') == exclude_run:
                continue
            total = content.get('costTotal') if 'credits' in content else content.get('costUsd')
            if isinstance(total, (int, float)):
                return float(total)
        return 0.0

    def _charge_turn(
        self, runtime: SessionRuntime, run_id: str, model: str, total_cost: float | None,
    ) -> tuple[float | None, int, int | None]:
        """(this turn's cost in USD, credits charged, balance after). Never fails the turn."""
        if total_cost is None:
            return None, 0, None
        before = runtime.cost_total if runtime.cost_total is not None else self.last_cost_total(runtime.session_id, run_id)
        # Lower than before: the total started over (a fresh conversation), so all of it is this turn's.
        run_cost = total_cost - before if total_cost >= before else total_cost
        runtime.cost_total = total_cost
        amount = chat_price(run_cost)
        if not amount:
            return run_cost, 0, None
        label = dict(MODELS).get(model, model)
        try:
            balance = Credits(self.repository.database).charge(
                amount, 'chat', f'Agent 对话 · {label}', ref=f'run:{run_id}', allow_negative=True)
        except Exception:
            log.exception('charging agent turn %s failed', run_id)
            return run_cost, 0, None
        return run_cost, amount, balance

    # ------------------------------------------------------------ summaries

    def schedule_summary(self, session_id: str, run_id: str) -> None:
        """Update this chat's summary in the background (panel chats only; comments have the task log)."""
        if self.summarizer is None:
            return
        try:
            if self.store.get_session(session_id).get('kind') != 'chat':
                return
            loop = asyncio.get_running_loop()
        except (DomainError, RuntimeError):
            return
        self._summary_runs.setdefault(session_id, []).append(run_id)
        task = self._summary_tasks.get(session_id)
        if task is None or task.done():
            self._summary_tasks[session_id] = loop.create_task(self._summarize(session_id))

    async def _summarize(self, session_id: str) -> None:
        """One at a time per chat, in order, so each summary builds on the one before."""
        pending = self._summary_runs.get(session_id, [])
        while pending:
            run_id = pending.pop(0)
            try:
                session = self.store.get_session(session_id)
                text = build_input(session.get('summary'), session.get('title'), self.store.run_transcript(run_id))
                summary = clean_summary(await asyncio.wait_for(self.summarizer(text), 90))
                if summary:
                    self.store.set_summary(session_id, summary)
            except asyncio.CancelledError:
                raise
            except Exception:  # a summary is a nice-to-have: keep the old one
                log.warning('summarising chat %s failed', session_id, exc_info=True)

    def _remember_sdk_session(self, runtime: SessionRuntime, sdk_session_id: str) -> None:
        if runtime.sdk_session_id != sdk_session_id:
            if runtime.sdk_session_id is not None and sdk_session_id != runtime.sdk_session_id:
                runtime.seen_context.clear()  # not the conversation we resumed: it saw nothing yet
            runtime.sdk_session_id = sdk_session_id
            self.store.set_sdk_session(runtime.session_id, sdk_session_id)

    def _emit(self, session_id: str, run_id: str | None, kind: str, payload: dict, role: str | None = None) -> dict:
        """Persist (when `role` is given) and push to every open panel of this session."""
        body = {'kind': kind, **payload}
        message_id = self.store.add_message(session_id, role, body, run_id) if role else None
        event = {'id': message_id, 'runId': run_id, **body}
        for queue in list(self.subscribers.get(session_id, ())):
            queue.put_nowait(event)
        for listener in list(self.listeners):
            try:
                listener(session_id, event)
            except Exception:
                log.exception('agent event listener failed')
        return event


DEFAULT_CONTEXT_WINDOW = 1_000_000  # Opus / Sonnet / Haiku 5.5; the CLI's own figure wins when it reports one


def context_size(usage: dict[str, Any]) -> int | None:
    """Tokens the model saw on one request: everything sent (cached or not) plus what it wrote."""
    keys = ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens')
    total = sum(int(usage.get(key) or 0) for key in keys)
    return total or None


def context_limit(model_usage: dict[str, Any] | None) -> int | None:
    """The main model's context window, as the CLI reports it."""
    windows = [int(item.get('contextWindow') or 0) for item in (model_usage or {}).values() if isinstance(item, dict)]
    return max(windows, default=0) or None
