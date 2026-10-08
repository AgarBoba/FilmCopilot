import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { ChatsIcon, CloseIcon, MemoryIcon, PlusIcon, SendIcon, SparkIcon, StopIcon, UndoIcon } from '../canvas/icons';
import { agentApi, type AgentEvent, type AgentSkill, type PermissionMode } from './agentApi';
import { AgentMessage } from './AgentMessage';
import { pendingConfirmations, undoableRuns, useAgentStore, type SessionFilter } from './agentStore';
import { useCommentStore } from '../comments/commentStore';
import { describeAnchor, STATUS_LABELS, type CanvasComment } from '../comments/commentApi';
import { Markdown } from './Markdown';
import { SessionList } from './SessionList';
import { MemoryView } from './MemoryView';
import { ReferenceStrip, type NodeReference } from '../nodes/ReferenceStrip';

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
  /** Thumbnail data per node, for the focus strip above the input. */
  nodePreviews?: Record<string, NodeReference>;
  /** Drop a node from the focus (deselects it on the canvas). */
  onUnfocus?: (nodeId: string) => void;
  onFocusNodes: (nodeIds: string[]) => void;
  onSaveToCanvas: (text: string, title?: string) => void;
  onClose: () => void;
}


export function AgentPanel({
  canvasId,
  projectId = 'default',
  selectedNodeIds,
  nodeTitles,
  nodePreviews = {},
  onUnfocus,
  onFocusNodes,
  onSaveToCanvas,
  onClose,
}: AgentPanelProps) {
  const store = useAgentStore();
  const { sessionId, events, streaming, activeRunId, settings, configured, sessions } = store;
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  /** Skills for the / menu, and the one picked for the next message. */
  const [skills, setSkills] = useState<AgentSkill[]>([]);
  const [skill, setSkill] = useState<AgentSkill | null>(null);
  const [menuIndex, setMenuIndex] = useState(0);
  const slash = /^\/(\S*)$/.exec(draft);
  const menuSkills = slash ? matchSkills(skills, slash[1]) : [];
  const menuOpen = Boolean(slash) && menuSkills.length > 0;

  function loadSkills() {
    agentApi.listSkills().then((data) => setSkills(data.skills)).catch(() => undefined);
  }
  useEffect(loadSkills, []);

  function pickSkill(next: AgentSkill) {
    setSkill(next);
    setDraft('');
    setMenuIndex(0);
    inputRef.current?.focus();
  }
  const [width, setWidth] = useState(readPanelWidth);
  // The canvas keeps its minimap clear of the panel through this variable.
  useLayoutEffect(() => {
    document.documentElement.style.setProperty('--agent-panel-width', `${width}px`);
  }, [width]);

  function startResize(event: React.PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = width;
    const onMove = (move: PointerEvent) => setWidth(clampPanelWidth(startWidth + (startX - move.clientX)));
    const onUp = (up: PointerEvent) => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      document.body.classList.remove('is-resizing-panel');
      savePanelWidth(clampPanelWidth(startWidth + (startX - up.clientX)));
    };
    document.body.classList.add('is-resizing-panel');
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }

  /** 'list' shows every chat on this canvas; 'chat' the open one. */
  const [view, setView] = useState<'chat' | 'list' | 'memory'>('chat');
  const [listFilter, setListFilter] = useState<SessionFilter>('all');
  const [nodeFilter, setNodeFilter] = useState<string | null>(null);
  const comments = useCommentStore((state) => state.comments);
  /** The open chat belongs to a canvas comment: replies go through the comment's queue. */
  const currentComment = comments.find((comment) => comment.sessionId === sessionId) ?? null;
  const commentBusy = currentComment ? ['queued', 'running', 'waiting'].includes(currentComment.status) : false;
  const listRequest = useAgentStore((state) => state.listRequest);
  /** Set once the canvas asked for a list or a chat: the panel then doesn't jump to the last chat. */
  const requestedRef = useRef(false);
  const sessionRequest = useAgentStore((state) => state.sessionRequest);

  // The canvas asked for the comment list (a node's badge) or a comment's chat.
  useEffect(() => {
    if (!listRequest) return;
    requestedRef.current = true;
    setListFilter(listRequest.filter);
    setNodeFilter(listRequest.nodeId ?? null);
    setView('list');
    useAgentStore.setState({ listRequest: null });
  }, [listRequest]);
  useEffect(() => {
    if (!sessionRequest) return;
    requestedRef.current = true;
    useAgentStore.setState({ sessionRequest: null });
    void agentApi.listSessions(canvasId).then((list) => useAgentStore.setState({ sessions: list })).catch(() => undefined);
    void openSession(sessionRequest.id);
  }, [sessionRequest]);

  function openComment(comment: CanvasComment) {
    useCommentStore.getState().focus(comment.id);
    void openSession(comment.sessionId);
  }
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
          configured: status.configured, model: status.model, auth: status.auth, models: status.models,
          settings: projectSettings, sessions: list,
        });
        // Reopen the latest panel chat, unless the canvas already asked for something else.
        const recent = list.find((item) => !item.archived_at && item.kind !== 'comment' && (item.message_count ?? 0) > 0);
        if (!useAgentStore.getState().sessionId && !requestedRef.current && recent) await openSession(recent.id);
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
    if ((!text && !skill) || sending || activeRunId) return;
    if (currentComment) {
      // A comment's chat continues through the comment, so its pin and queue stay right.
      if (!text || commentBusy) return;
      setSending(true);
      if (await useCommentStore.getState().reply(currentComment.id, text)) {
        setDraft('');
        stickToBottom.current = true;
      } else {
        useAgentStore.setState({ error: useCommentStore.getState().error ?? '回复没发出去' });
      }
      setSending(false);
      return;
    }
    setSending(true);
    try {
      let id = sessionId;
      if (!id) {
        const session = await agentApi.createSession(canvasId);
        useAgentStore.setState({
          sessions: [{ ...session, title: (text || skill?.label || '').slice(0, 30), message_count: 1, status: 'running' }, ...sessions],
        });
        useAgentStore.getState().reset(session.id);
        id = session.id;
      }
      const { runId } = await agentApi.send(id, text, selectedNodeIds, skill?.id);
      useAgentStore.setState({ activeRunId: runId, error: null });
      setDraft('');
      setSkill(null);
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

  /** Takes effect from the next message; the conversation so far is kept. */
  async function changeModel(model: string) {
    try {
      const next = await agentApi.updateSettings(projectId, { model });
      useAgentStore.setState({ settings: next });
    } catch (error) {
      useAgentStore.setState({ error: error instanceof Error ? error.message : '切换模型失败' });
    }
  }

  async function changeMode(mode: PermissionMode) {
    const next = await agentApi.updateSettings(projectId, { permissionMode: mode });
    useAgentStore.setState({ settings: next });
  }

  const pending = new Set(pendingConfirmations(events).map((event) => event.requestId));
  // The agent's to-do list is re-sent after every change: show only its latest version per run.
  const lastTasks = new Map<string | null, number>();
  events.forEach((event, index) => { if (event.kind === 'tasks') lastTasks.set(event.runId, index); });
  const undoable = undoableRuns(events);
  const lastFinishedRun = [...events].reverse().find((event) => event.kind === 'run_finished')?.runId ?? null;
  const focusTitles = { ...nodeTitles };
  const currentModel = settings?.model || store.model;
  const modelLabel = store.models.find((item) => item.id === currentModel)?.label ?? currentModel;
  const memoryVersion = events.filter((event) => event.kind === 'memory_change' || event.kind === 'run_undone').length;
  const currentTitle = sessions.find((item) => item.id === sessionId)?.title || '新对话';
  // Another chat on this canvas needs attention (waiting beats running).
  const others = sessions.filter((item) => item.id !== sessionId && !item.archived_at);
  const backgroundBusy = others.some((item) => item.status === 'waiting') ? 'waiting'
    : others.some((item) => item.status === 'running') ? 'running' : null;

  return (
    <aside className="agent-panel nowheel" aria-label="Agent 对话" style={{ width: `min(${width}px, calc(100vw - 32px))` }} onKeyDown={(event) => {
      // Keep canvas shortcuts (Delete, V, H, Space…) out of the panel; ⌘J still closes it.
      event.stopPropagation();
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'j') {
        event.preventDefault();
        onClose();
      }
    }}>
      <div
        className="agent-resize"
        role="separator"
        aria-orientation="vertical"
        aria-label="拖动调整面板宽度"
        onPointerDown={startResize}
        onDoubleClick={() => { setWidth(DEFAULT_PANEL_WIDTH); savePanelWidth(DEFAULT_PANEL_WIDTH); }}
      />
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
          {modelLabel && (
            <span className="agent-model">
              {modelLabel}{store.auth && <> · {store.auth === 'subscription' ? '订阅额度' : 'API'}</>}
            </span>
          )}
        </button>
        <button
          type="button"
          className={`agent-icon ${view === 'memory' ? 'is-active' : ''}`}
          aria-label="记忆"
          data-tooltip="Agent 记住的设定和你的偏好"
          data-tooltip-side="bottom"
          onClick={() => setView(view === 'memory' ? 'chat' : 'memory')}
        >
          <MemoryIcon width={16} height={16} />
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

      {view === 'memory' ? (
        <MemoryView projectId={projectId} version={memoryVersion} onBack={() => setView('chat')} />
      ) : view === 'list' ? (
        <SessionList
          sessions={sessions}
          comments={comments}
          filter={listFilter}
          onFilterChange={(next) => { setListFilter(next); setNodeFilter(null); }}
          nodeFilter={nodeFilter}
          onClearNodeFilter={() => setNodeFilter(null)}
          nodeTitles={nodeTitles}
          onOpenComment={openComment}
          currentId={sessionId}
          onOpen={(id) => void openSession(id)}
          onNew={newSession}
          onBack={() => setView('chat')}
          onRename={(id, title) => void renameSession(id, title)}
          onArchive={(id, archived) => void archiveSession(id, archived)}
        />
      ) : (
      <>
      {currentComment && (
        <div className={`agent-comment-bar is-${currentComment.status}`}>
          <span className={`session-pin is-${currentComment.status}`} aria-hidden="true" />
          <span className="agent-comment-where">留言 · {describeAnchor(currentComment.anchor, nodeTitles)}</span>
          <span className="agent-comment-status">{STATUS_LABELS[currentComment.status]}</span>
          <button type="button" onClick={() => useCommentStore.getState().focus(currentComment.id)}>在画布上看</button>
          {currentComment.status === 'resolved' ? (
            <button type="button" onClick={() => void useCommentStore.getState().reopen(currentComment.id)}>重新打开</button>
          ) : (
            <button type="button" disabled={commentBusy} onClick={() => void useCommentStore.getState().resolve(currentComment.id)}>解决</button>
          )}
        </div>
      )}
      <div
        ref={listRef}
        className="agent-messages"
        onScroll={(event) => {
          const el = event.currentTarget;
          stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
      >
        {configured === false && (
          <div className="agent-empty">
            Agent 还没配置：在项目的 .env 里填上 ANTHROPIC_API_KEY，然后重启 dev.sh。可以让你的编码 Agent 按项目里的
            AGENTS.md 帮你弄好。
          </div>
        )}
        {configured !== false && events.length === 0 && (
          <div className="agent-empty">
            告诉 Agent 你想做什么，比如「用这张兔子图做 3 个不同风格的版本」。先在画布上选中节点，它会围绕这些节点工作。
          </div>
        )}
        {events.map((event, index) => event.kind === 'tasks' && lastTasks.get(event.runId) !== index ? null : (
          <AgentMessage
            key={event.id ?? `live-${index}`}
            event={event}
            focusTitles={focusTitles}
            focusPreviews={nodePreviews}
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
          <div className="agent-focus">
            <div className="agent-focus-label">关注 {selectedNodeIds.length} 个节点 · 在画布上选中的会随消息一起发给 Agent</div>
            <ReferenceStrip
              label="关注的节点"
              references={selectedNodeIds.map((id) => nodePreviews[id] ?? { nodeId: id, kind: 'note', title: nodeTitles[id] ?? id })}
              removeTooltip="不关注这个（在画布上取消选中）"
              onRemove={onUnfocus ? (reference) => reference.nodeId && onUnfocus(reference.nodeId) : undefined}
            />
          </div>
        )}
        {menuOpen && (
          <div className="agent-skill-menu" role="listbox" aria-label="技能">
            <div className="agent-skill-menu-head">技能 · 让 Agent 按这套方法做</div>
            {menuSkills.map((item, index) => (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={index === menuIndex}
                className={index === menuIndex ? 'is-active' : ''}
                onMouseEnter={() => setMenuIndex(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => pickSkill(item)}
              >
                <span className="agent-skill-name">
                  {item.label}
                  {item.source === 'user' && <span className="agent-skill-tag">我的</span>}
                </span>
                <span className="agent-skill-desc">{item.description}</span>
              </button>
            ))}
          </div>
        )}
        <div className="agent-input-row">
          {skill && (
            <span className="agent-skill-chip" data-tooltip={skill.description} data-tooltip-side="top">
              <SparkIcon width={12} height={12} />{skill.label}
              <button type="button" aria-label="不用这个技能" onClick={() => setSkill(null)}>×</button>
            </span>
          )}
          <textarea
            ref={inputRef}
            value={draft}
            rows={1}
            aria-label="消息"
            placeholder={activeRunId || commentBusy ? 'Agent 正在处理…'
              : currentComment ? '回复这条留言，Enter 发送'
                : skill ? `补充要求（可以不写），Enter 发送` : '想让 Agent 做什么？输入 / 选技能，Enter 发送'}
            onFocus={() => { if (!skills.length) loadSkills(); }}
            onChange={(event) => {
              setDraft(event.target.value);
              setMenuIndex(0);
              if (event.target.value === '/') loadSkills(); // pick up skills added since
            }}
            onKeyDown={(event) => {
              if (event.nativeEvent.isComposing) return;
              if (menuOpen) {
                if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                  event.preventDefault();
                  const step = event.key === 'ArrowDown' ? 1 : -1;
                  setMenuIndex((index) => (index + step + menuSkills.length) % menuSkills.length);
                  return;
                }
                if (event.key === 'Enter' || event.key === 'Tab') {
                  event.preventDefault();
                  pickSkill(menuSkills[Math.min(menuIndex, menuSkills.length - 1)]);
                  return;
                }
                if (event.key === 'Escape') {
                  event.preventDefault();
                  setDraft('');
                  return;
                }
              }
              if (event.key === 'Backspace' && !draft && skill) {
                setSkill(null);
                return;
              }
              if (event.key === 'Enter' && !event.shiftKey) {
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
              disabled={(!draft.trim() && !skill) || sending || commentBusy || configured === false} onClick={() => void send()}>
              <SendIcon width={15} height={15} />
            </button>
          )}
        </div>
        {/* Quiet setting under the input: what the agent must ask before doing. */}
        <div className="agent-composer-meta">
          {store.models.length > 0 && (
            <label className="agent-mode">
              <select
                aria-label="模型"
                value={currentModel}
                onChange={(event) => void changeModel(event.target.value)}
              >
                {store.models.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
              </select>
              <span className="agent-mode-caret" aria-hidden="true">▾</span>
            </label>
          )}
          <label className="agent-mode">
            <select
              aria-label="审核设置"
              value={settings?.permissionMode ?? 'confirm_generation'}
              onChange={(event) => void changeMode(event.target.value as PermissionMode)}
            >
              {MODE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            <span className="agent-mode-caret" aria-hidden="true">▾</span>
          </label>
        </div>
      </footer>
      </>
      )}
    </aside>
  );
}


const DEFAULT_PANEL_WIDTH = 480;
const PANEL_WIDTH_KEY = 'film-copilot.agent-panel-width';

function clampPanelWidth(value: number): number {
  const max = Math.max(360, Math.min(820, window.innerWidth - 160));
  return Math.round(Math.min(max, Math.max(360, value)));
}

/** Remembered per browser; falls back to the default when storage is unavailable. */
function readPanelWidth(): number {
  try {
    const saved = Number(window.localStorage.getItem(PANEL_WIDTH_KEY));
    return saved ? clampPanelWidth(saved) : DEFAULT_PANEL_WIDTH;
  } catch {
    return DEFAULT_PANEL_WIDTH;
  }
}

function savePanelWidth(value: number) {
  try {
    window.localStorage.setItem(PANEL_WIDTH_KEY, String(value));
  } catch {
    /* private mode: width just isn't remembered */
  }
}


/** Skills whose label, name or description contains what was typed after "/". */
function matchSkills(skills: AgentSkill[], query: string): AgentSkill[] {
  const q = query.trim().toLowerCase();
  if (!q) return skills;
  return skills.filter((item) => [item.label, item.name, item.description].some((text) => text.toLowerCase().includes(q)));
}
