import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { CloseIcon, PlusIcon, SendIcon, StopIcon, UndoIcon } from '../canvas/icons';
import { agentApi, type AgentEvent, type PermissionMode } from './agentApi';
import { AgentMessage } from './AgentMessage';
import { pendingConfirmations, undoableRuns, useAgentStore } from './agentStore';
import { Markdown } from './Markdown';

const MODE_OPTIONS: { value: PermissionMode; label: string }[] = [
  { value: 'confirm_all', label: '每步确认' },
  { value: 'confirm_generation', label: '只确认生成和删除' },
  { value: 'auto', label: '全自动' },
];

interface AgentPanelProps {
  canvasId: string;
  projectId?: string;
  selectedNodeIds: string[];
  nodeTitles: Record<string, string>;
  onFocusNodes: (nodeIds: string[]) => void;
  onSaveToCanvas: (text: string) => void;
  onClose: () => void;
}


export function AgentPanel({
  canvasId,
  projectId = 'default',
  selectedNodeIds,
  nodeTitles,
  onFocusNodes,
  onSaveToCanvas,
  onClose,
}: AgentPanelProps) {
  const store = useAgentStore();
  const { sessionId, events, streaming, activeRunId, settings, configured, sessions } = store;
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // First open: status, settings, most recent session.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [status, projectSettings, list] = await Promise.all([
          agentApi.status(), agentApi.getSettings(projectId), agentApi.listSessions(canvasId),
        ]);
        if (cancelled) return;
        useAgentStore.setState({
          configured: status.configured, model: status.model, settings: projectSettings, sessions: list,
        });
        if (!useAgentStore.getState().sessionId && list.length) await openSession(list[0].id);
      } catch (error) {
        useAgentStore.setState({ error: error instanceof Error ? error.message : '无法连接 Agent' });
      }
    })();
    inputRef.current?.focus();
    return () => {
      cancelled = true;
    };
  }, [canvasId, projectId]);

  // Live stream for the open session.
  useEffect(() => {
    if (!sessionId) return undefined;
    return agentApi.stream(sessionId, () => useAgentStore.getState().lastEventId, (event) => {
      useAgentStore.getState().apply(event);
    });
  }, [sessionId]);

  // A finished run may have named a new session: refresh the history list.
  const finishedCount = events.filter((event) => event.kind === 'run_finished').length;
  useEffect(() => {
    if (!finishedCount) return;
    void agentApi.listSessions(canvasId).then((list) => useAgentStore.setState({ sessions: list })).catch(() => undefined);
  }, [finishedCount, canvasId]);

  // Keep the newest message in view unless the user scrolled up to read.
  useLayoutEffect(() => {
    const list = listRef.current;
    if (list && stickToBottom.current) list.scrollTop = list.scrollHeight;
  }, [events, streaming]);

  async function openSession(id: string) {
    const history = await agentApi.messages(id);
    useAgentStore.getState().reset(id, history);
    const listed = useAgentStore.getState().sessions.find((item) => item.id === id);
    if (listed?.activeRunId) useAgentStore.setState({ activeRunId: listed.activeRunId });
  }

  async function newSession() {
    const session = await agentApi.createSession(canvasId);
    useAgentStore.setState({ sessions: [session, ...useAgentStore.getState().sessions] });
    useAgentStore.getState().reset(session.id);
    inputRef.current?.focus();
  }

  async function send() {
    const text = draft.trim();
    if (!text || sending || activeRunId) return;
    setSending(true);
    try {
      let id = sessionId;
      if (!id) {
        const session = await agentApi.createSession(canvasId);
        useAgentStore.setState({ sessions: [session, ...sessions] });
        useAgentStore.getState().reset(session.id);
        id = session.id;
      }
      const { runId } = await agentApi.send(id, text, selectedNodeIds);
      useAgentStore.setState({ activeRunId: runId, error: null });
      setDraft('');
      stickToBottom.current = true;
    } catch (error) {
      useAgentStore.setState({ error: error instanceof Error ? error.message : '发送失败' });
    } finally {
      setSending(false);
    }
  }

  async function confirm(event: AgentEvent, approved: boolean) {
    if (event.runId && event.requestId) await agentApi.confirm(event.runId, event.requestId, approved);
  }

  async function undo(runId: string) {
    try {
      await agentApi.undo(runId);
    } catch (error) {
      useAgentStore.setState({ error: error instanceof Error ? error.message : '撤销失败' });
    }
  }

  async function changeMode(mode: PermissionMode) {
    const next = await agentApi.updateSettings(projectId, { permissionMode: mode });
    useAgentStore.setState({ settings: next });
  }

  const pending = new Set(pendingConfirmations(events).map((event) => event.requestId));
  const undoable = undoableRuns(events);
  const lastFinishedRun = [...events].reverse().find((event) => event.kind === 'run_finished')?.runId ?? null;
  const focusTitles = { ...nodeTitles };

  return (
    <aside className="agent-panel nowheel" aria-label="Agent 对话" onKeyDown={(event) => {
      // Keep canvas shortcuts (Delete, V, H, Space…) out of the panel; ⌘J still closes it.
      event.stopPropagation();
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'j') {
        event.preventDefault();
        onClose();
      }
    }}>
      <header className="agent-header">
        <div className="agent-title">
          <span>Agent</span>
          {store.model && <span className="agent-model">{store.model}</span>}
        </div>
        <button type="button" className="agent-icon" aria-label="新对话" data-tooltip="新对话" data-tooltip-side="bottom"
          onClick={() => void newSession()}>
          <PlusIcon width={16} height={16} />
        </button>
        <button type="button" className="agent-icon" aria-label="关闭" data-tooltip="关闭" data-tooltip-shortcut="⌘J"
          data-tooltip-side="bottom" onClick={onClose}>
          <CloseIcon width={16} height={16} />
        </button>
      </header>

      <div className="agent-toolbar">
        <select
          aria-label="历史对话"
          value={sessionId ?? ''}
          onChange={(event) => void openSession(event.target.value)}
          disabled={!sessions.length}
        >
          {!sessionId && <option value="">新对话</option>}
          {sessions.map((session) => (
            <option key={session.id} value={session.id}>
              {session.title || '未命名对话'}
            </option>
          ))}
        </select>
        <select
          aria-label="权限档位"
          value={settings?.permissionMode ?? 'confirm_generation'}
          onChange={(event) => void changeMode(event.target.value as PermissionMode)}
          data-tooltip="Agent 做哪些操作前要先问你（视频生成总是会问）"
        >
          {MODE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </div>

      <div
        ref={listRef}
        className="agent-messages"
        onScroll={(event) => {
          const el = event.currentTarget;
          stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
      >
        {configured === false && (
          <div className="agent-empty">后端没有读到 ANTHROPIC_API_KEY。在 .env 里填好后重启 dev.sh。</div>
        )}
        {configured !== false && events.length === 0 && (
          <div className="agent-empty">
            告诉 Agent 你想做什么，比如「用这张兔子图做 3 个不同风格的版本」。先在画布上选中节点，它会围绕这些节点工作。
          </div>
        )}
        {events.map((event, index) => (
          <AgentMessage
            key={event.id ?? `live-${index}`}
            event={event}
            focusTitles={focusTitles}
            onFocusNodes={onFocusNodes}
            onSaveToCanvas={onSaveToCanvas}
            onConfirm={(target, approved) => void confirm(target, approved)}
            pending={pending.has(event.requestId)}
          />
        ))}
        {Object.entries(streaming).map(([runId, text]) => (
          <div key={`stream-${runId}`} className="agent-msg is-assistant is-streaming">
            <Markdown text={text} />
          </div>
        ))}
        {activeRunId && !streaming[activeRunId] && pending.size === 0 && (
          <div className="agent-thinking" aria-live="polite"><span /><span /><span /></div>
        )}
        {!activeRunId && lastFinishedRun && undoable.has(lastFinishedRun) && (
          <button type="button" className="agent-undo" onClick={() => void undo(lastFinishedRun)}>
            <UndoIcon width={14} height={14} /> 撤销这一轮的改动
          </button>
        )}
      </div>

      {store.error && (
        <div className="agent-error" role="alert">
          {store.error}
          <button type="button" aria-label="关闭提示" onClick={() => useAgentStore.setState({ error: null })}>×</button>
        </div>
      )}

      <footer className="agent-composer">
        {selectedNodeIds.length > 0 && (
          <div className="agent-focus-chips" aria-label="选中的节点">
            关注：{selectedNodeIds.map((id) => nodeTitles[id] ?? id).join('、')}
          </div>
        )}
        <div className="agent-input-row">
          <textarea
            ref={inputRef}
            value={draft}
            rows={1}
            placeholder={activeRunId ? 'Agent 正在处理…' : '想让 Agent 做什么？Enter 发送，Shift+Enter 换行'}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void send();
              }
            }}
          />
          {activeRunId ? (
            <button type="button" className="agent-send is-stop" aria-label="停止" data-tooltip="停止这一轮"
              onClick={() => void agentApi.stop(activeRunId)}>
              <StopIcon width={14} height={14} />
            </button>
          ) : (
            <button type="button" className="agent-send" aria-label="发送" data-tooltip="发送"
              disabled={!draft.trim() || sending || configured === false} onClick={() => void send()}>
              <SendIcon width={15} height={15} />
            </button>
          )}
        </div>
      </footer>
    </aside>
  );
}
