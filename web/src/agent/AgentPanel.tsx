import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { ChatsIcon, CloseIcon, PlusIcon, SendIcon, StopIcon, UndoIcon } from '../canvas/icons';
import { agentApi, type AgentEvent, type PermissionMode } from './agentApi';
import { AgentMessage } from './AgentMessage';
import { pendingConfirmations, undoableRuns, useAgentStore } from './agentStore';
import { Markdown } from './Markdown';
import { SessionList } from './SessionList';

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
  onSaveToCanvas: (text: string, title?: string) => void;
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
  /** 'list' shows every chat on this canvas; 'chat' the open one. */
  const [view, setView] = useState<'chat' | 'list'>('chat');
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
        const recent = list.find((item) => !item.archived_at && (item.message_count ?? 0) > 0);
        if (!useAgentStore.getState().sessionId && recent) await openSession(recent.id);
      } catch (error) {
        useAgentStore.setState({ error: error instanceof Error ? error.message : '无法连接 Agent' });
      }
    })();
    inputRef.current?.focus();
    return () => {
      cancelled = true;
    };
  }, [canvasId, projectId]);

  // Other chats may be running in the background: keep their status fresh.
  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const list = await agentApi.listSessions(canvasId);
        if (!cancelled) useAgentStore.setState({ sessions: list });
      } catch {
        /* offline for a moment: keep the last list */
      }
    };
    const timer = setInterval(() => void refresh(), view === 'list' ? 2000 : 5000);
    if (view === 'list') void refresh();
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [canvasId, view]);

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
    setView('chat');
    if (id === useAgentStore.getState().sessionId) return;
    const history = await agentApi.messages(id);
    useAgentStore.getState().reset(id, history);
    const listed = useAgentStore.getState().sessions.find((item) => item.id === id);
    if (listed?.activeRunId) useAgentStore.setState({ activeRunId: listed.activeRunId });
  }

  /** A new chat is only created on the server when its first message is sent. */
  function newSession() {
    useAgentStore.getState().reset(null);
    setView('chat');
    setTimeout(() => inputRef.current?.focus(), 0);
  }

  async function renameSession(id: string, title: string) {
    try {
      const updated = await agentApi.updateSession(id, { title });
      useAgentStore.setState({
        sessions: useAgentStore.getState().sessions.map((item) => (item.id === id ? { ...item, ...updated, title: updated.title ?? item.title } : item)),
      });
    } catch (error) {
      useAgentStore.setState({ error: error instanceof Error ? error.message : '改名失败' });
    }
  }

  async function archiveSession(id: string, archived: boolean) {
    try {
      const updated = await agentApi.updateSession(id, { archived });
      useAgentStore.setState({
        sessions: useAgentStore.getState().sessions.map((item) => (item.id === id ? { ...item, ...updated, title: updated.title ?? item.title } : item)),
      });
      if (archived && id === useAgentStore.getState().sessionId) useAgentStore.getState().reset(null);
    } catch (error) {
      useAgentStore.setState({ error: error instanceof Error ? error.message : '归档失败' });
    }
  }

  async function send() {
    const text = draft.trim();
    if (!text || sending || activeRunId) return;
    setSending(true);
    try {
      let id = sessionId;
      if (!id) {
        const session = await agentApi.createSession(canvasId);
        useAgentStore.setState({
          sessions: [{ ...session, title: text.slice(0, 30), message_count: 1, status: 'running' }, ...sessions],
        });
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

  async function confirm(event: AgentEvent, approved: boolean, note: string): Promise<boolean> {
    if (!event.runId || !event.requestId) return false;
    try {
      await agentApi.confirm(event.runId, event.requestId, approved, note);
      return true;
    } catch (error) {
      useAgentStore.setState({ error: error instanceof Error ? error.message : '提交失败' });
      return false;
    }
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
  const currentTitle = sessions.find((item) => item.id === sessionId)?.title || '新对话';
  // Another chat on this canvas needs attention (waiting beats running).
  const others = sessions.filter((item) => item.id !== sessionId && !item.archived_at);
  const backgroundBusy = others.some((item) => item.status === 'waiting') ? 'waiting'
    : others.some((item) => item.status === 'running') ? 'running' : null;

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
        <button
          type="button"
          className={`agent-icon agent-chats ${view === 'list' ? 'is-active' : ''}`}
          aria-label="全部对话"
          data-tooltip="全部对话"
          data-tooltip-side="bottom"
          onClick={() => setView(view === 'list' ? 'chat' : 'list')}
        >
          <ChatsIcon width={16} height={16} />
          {backgroundBusy && <span className={`agent-chats-badge is-${backgroundBusy}`} aria-hidden="true" />}
        </button>
        <button type="button" className="agent-title" onClick={() => setView('list')} data-tooltip="切换对话" data-tooltip-side="bottom">
          <span className="agent-title-text">{currentTitle}</span>
          {store.model && <span className="agent-model">{store.model}</span>}
        </button>
        <button type="button" className="agent-icon" aria-label="新对话" data-tooltip="新对话" data-tooltip-side="bottom"
          onClick={newSession}>
          <PlusIcon width={16} height={16} />
        </button>
        <button type="button" className="agent-icon" aria-label="关闭" data-tooltip="关闭" data-tooltip-shortcut="⌘J"
          data-tooltip-side="bottom" onClick={onClose}>
          <CloseIcon width={16} height={16} />
        </button>
      </header>

      {view === 'list' ? (
        <SessionList
          sessions={sessions}
          currentId={sessionId}
          onOpen={(id) => void openSession(id)}
          onNew={newSession}
          onBack={() => setView('chat')}
          onRename={(id, title) => void renameSession(id, title)}
          onArchive={(id, archived) => void archiveSession(id, archived)}
        />
      ) : (
      <>
      <div className="agent-toolbar">
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
            onConfirm={(target, approved, note) => confirm(target, approved, note)}
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
      </>
      )}
    </aside>
  );
}
