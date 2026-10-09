import { useEffect, useRef, useState } from 'react';

import { CloseIcon, MoreIcon, ReopenIcon, ResolveIcon } from '../canvas/icons';
import { agentApi, type AgentEvent } from '../agent/agentApi';
import { AgentAvatar, type AgentMood } from '../agent/AgentAvatar';
import { AgentMessage } from '../agent/AgentMessage';
import { pendingConfirmations, undoableRuns } from '../agent/agentStore';
import { Markdown } from '../agent/Markdown';
import { agentBusy, formatMoment, type CanvasComment } from './commentApi';
import { CommentComposer, MentionText } from './CommentComposer';
import { queuePosition, useCommentStore } from './commentStore';
import { sideOf } from './mediaGeometry';
import { buildThread, timeAgo, type ThreadItem } from './thread';
import { useSessionEvents } from './useSessionEvents';

interface CommentPopoverProps {
  comment: CanvasComment;
  /** Pin tip, in the canvas viewport's coordinates (null: centred). */
  at: { x: number; y: number } | null;
  bounds: { width: number; height: number };
  where: string;
  onClose: () => void;
  onOpenInPanel: (comment: CanvasComment) => void;
  onFocusNodes: (nodeIds: string[]) => void;
  onSaveToCanvas: (text: string, title?: string) => void;
}

export const POPOVER_WIDTH = 292;

type MenuEntry = { label: string; onClick: () => void; danger?: boolean };

/**
 * A comment as a thread, like any comment box: who said what, when. A plain note is just
 * that; ticking "@Agent" hands it (with everything it hasn't seen) to the agent, whose
 * rounds show up as its replies. Resolve, the menu and close sit in the top corner.
 */
export function CommentPopover({ comment, at, bounds, where, onClose, onOpenInPanel, onFocusNodes, onSaveToCanvas }: CommentPopoverProps) {
  const { events, streaming } = useSessionEvents(comment.sessionId);
  const comments = useCommentStore((state) => state.comments);
  const [menu, setMenu] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [undoing, setUndoing] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const busy = agentBusy(comment);
  const resolved = comment.status === 'resolved';

  const pending = new Set(pendingConfirmations(events).map((event) => event.requestId));
  const thread = buildThread(comment, events, streaming, pending);

  useEffect(() => {
    const body = bodyRef.current;
    if (body) body.scrollTop = body.scrollHeight;
  }, [thread.length, events.length, streaming]);

  useEffect(() => {
    setMenu(false);
    setConfirmDelete(false);
  }, [comment.id]);

  // Same rule as the panel: the last finished round, if it changed something, can be undone.
  const lastRun = [...events].reverse().find((event) => event.kind === 'run_finished')?.runId ?? null;
  const canUndo = !busy && lastRun !== null && undoableRuns(events).has(lastRun);
  const activeRun = busy ? [...events].reverse().find((event) => event.runId)?.runId ?? null : null;
  const runFinished = (runId: string | null) => events.some((event) => event.runId === runId && event.kind === 'run_finished');

  const store = useCommentStore.getState;
  const fail = (error: unknown, fallback: string) =>
    useCommentStore.setState({ error: error instanceof Error ? error.message : fallback });

  async function undo(runId: string) {
    if (undoing) return;
    setUndoing(true);
    try {
      await agentApi.undo(runId); // the "已撤销" note arrives through the stream
    } catch (error) {
      fail(error, '撤销失败');
    } finally {
      setUndoing(false);
    }
  }

  async function confirm(event: AgentEvent, approved: boolean, note: string) {
    if (!event.runId || !event.requestId) return false;
    try {
      await agentApi.confirm(event.runId, event.requestId, approved, note);
      return true;
    } catch (error) {
      fail(error, '提交失败');
      return false;
    }
  }

  async function stop() {
    setMenu(false);
    if (!activeRun || runFinished(activeRun)) return;
    try {
      await agentApi.stop(activeRun);
    } catch (error) {
      fail(error, '停止失败');
    }
  }

  async function remove() {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setMenu(false);
    if (await store().remove(comment.id)) onClose();
  }

  // Beside the pin, kept inside the canvas.
  const left = at ? sideOf(at.x, POPOVER_WIDTH, bounds.width) : Math.max(8, (bounds.width - POPOVER_WIDTH) / 2);
  const top = at ? Math.min(Math.max(8, at.y - 32), Math.max(8, bounds.height - 420)) : 80;

  const mood: AgentMood = comment.agentStatus === 'waiting' ? 'waiting'
    : comment.agentStatus === 'running' ? 'working' : 'idle';
  const lastAgent = [...thread].reverse().find((item) => item.type === 'agent');
  const handedOff = comment.agentStatus !== null;
  const anchor = comment.anchor;
  const note = agentNote(comment, queuePosition(comments, comment.id));
  // Queued for a new round: a placeholder message until the round starts.
  const waitingRound = comment.agentStatus === 'queued' && (!lastAgent || lastAgent.type !== 'agent' || !lastAgent.live);

  const openInPanel: MenuEntry = { label: '在面板中打开', onClick: () => { setMenu(false); onOpenInPanel(comment); } };
  const menuItems: MenuEntry[] = [];
  if (resolved) {
    menuItems.push({ label: '重新打开', onClick: () => { setMenu(false); void store().reopen(comment.id); } });
  } else if (busy) {
    if (comment.sessionId) menuItems.push(openInPanel);
    if (activeRun && !runFinished(activeRun)) menuItems.push({ label: '停止', onClick: () => void stop() });
  } else {
    if (handedOff && comment.sessionId) menuItems.push(openInPanel);
    else if (!comment.nodeMissing) {
      menuItems.push({ label: '让 Agent 处理', onClick: () => { setMenu(false); void store().handOff(comment.id); } });
    }
    menuItems.push({
      label: '复制文字',
      onClick: () => {
        setMenu(false);
        void navigator.clipboard?.writeText(comment.text).catch(() => undefined);
      },
    });
  }
  if (!busy) menuItems.push({ label: confirmDelete ? '确认删除？' : '删除', onClick: () => void remove(), danger: true });

  const corner = (
    <span className="comment-corner">
      {resolved ? (
        <button type="button" className="comment-icon" aria-label="重新打开" data-tooltip="重新打开"
          onClick={() => void store().reopen(comment.id)}>
          <ReopenIcon width={16} height={16} />
        </button>
      ) : (
        <button type="button" className="comment-icon" aria-label="解决" disabled={busy}
          data-tooltip={busy ? 'Agent 还在处理，做完再解决' : '解决'}
          onClick={() => void store().resolve(comment.id)}>
          <ResolveIcon width={17} height={17} />
        </button>
      )}
      <button type="button" className={`comment-icon ${menu ? 'is-open' : ''}`} aria-label="更多" aria-expanded={menu}
        onClick={() => { setMenu(!menu); setConfirmDelete(false); }}>
        <MoreIcon width={17} height={17} />
      </button>
      <button type="button" className="comment-icon" aria-label="关闭" onClick={onClose}>
        <CloseIcon width={15} height={15} />
      </button>
      {menu && (
        <div className="comment-menu" role="menu">
          {menuItems.map((entry) => (
            <button key={entry.label} type="button" role="menuitem" className={entry.danger ? 'is-danger' : ''} onClick={entry.onClick}>
              {entry.label}
            </button>
          ))}
        </div>
      )}
    </span>
  );

  return (
    <div
      className={`comment-popover comment-ui ${resolved ? 'is-resolved' : ''}`}
      role="dialog"
      aria-label={`留言 · ${where}`}
      style={{ left, top, width: POPOVER_WIDTH }}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === 'Escape') {
          if (menu) setMenu(false);
          else onClose();
        }
      }}
    >
      <div ref={bodyRef} className="comment-thread">
        {thread.map((item, index) => (
          <ThreadMessage
            key={item.key}
            item={item}
            mood={item === lastAgent && !waitingRound ? mood : 'idle'}
            note={item === lastAgent && !waitingRound ? note : null}
            oldVersion={index === 0 && anchor.stale && anchor.version ? anchor : null}
            controls={index === 0 ? corner : null}
          >
            {item.type === 'agent' && item.confirm && (
              <AgentMessage
                event={item.confirm}
                focusTitles={{}}
                onFocusNodes={onFocusNodes}
                onSaveToCanvas={onSaveToCanvas}
                onConfirm={(target, approved, text) => confirm(target, approved, text)}
                pending
              />
            )}
            {item.type === 'agent' && !item.live && (item.steps > 0 || (canUndo && item.runId === lastRun && !item.undone)) && (
              <span className="comment-agent-links">
                {canUndo && item.runId === lastRun && !item.undone && (
                  <button type="button" disabled={undoing} onClick={() => void undo(item.runId)}>撤销</button>
                )}
                {item.steps > 0 && (
                  <button type="button" onClick={() => onOpenInPanel(comment)}>看过程（{item.steps} 步）</button>
                )}
              </span>
            )}
          </ThreadMessage>
        ))}
        {waitingRound && (
          <ThreadMessage
            item={{ type: 'agent', key: 'queued', runId: '', time: '', text: '', confirm: null, steps: 0, current: null, live: true, finished: null, errors: [], undone: false }}
            mood="idle"
            note={note}
            oldVersion={null}
            controls={null}
          />
        )}
        {comment.nodeMissing && <div className="comment-note">节点已经删除了，这条留言不能再交给 Agent。</div>}
      </div>
      <div className="comment-popover-foot">
        <CommentComposer
          key={comment.id}
          label="回复留言"
          placeholder={busy ? 'Agent 处理中，可以先写普通回复' : resolved ? '回复会重新打开这条留言' : '回复…'}
          defaultAgent={handedOff && !comment.nodeMissing}
          agentDisabled={busy || comment.nodeMissing}
          onSubmit={(text, toAgent) => store().reply(comment.id, text, toAgent)}
        />
      </div>
    </div>
  );
}

/** "· 等你确认" next to the agent's name, for its latest round. */
function agentNote(comment: CanvasComment, queue: number): { text: string; tone: string } | null {
  switch (comment.agentStatus) {
    case 'queued': return { text: queue > 0 ? `排队第 ${queue} 个` : '排队中', tone: 'muted' };
    case 'running': return { text: '处理中', tone: 'accent' };
    case 'waiting': return { text: '等你确认', tone: 'waiting' };
    case 'failed': return { text: '没做完', tone: 'failed' };
    default: return null;
  }
}

function ThreadMessage({ item, mood, note, oldVersion, controls, children }: {
  item: ThreadItem;
  mood: AgentMood;
  note: { text: string; tone: string } | null;
  oldVersion: CanvasComment['anchor'] | null;
  controls: React.ReactNode;
  children?: React.ReactNode;
}) {
  const agent = item.type === 'agent';
  return (
    <div className={`comment-msg ${agent ? 'is-agent' : 'is-user'}`}>
      <div className="comment-msg-head">
        {agent ? <AgentAvatar size={24} mood={mood} /> : <span className="comment-avatar" aria-hidden="true">我</span>}
        <span className="comment-msg-name">{agent ? 'Agent' : '我'}</span>
        <span className="comment-msg-time">{timeAgo(item.time)}</span>
        {note && <span className={`comment-msg-note is-${note.tone}`}>· {note.text}</span>}
        {oldVersion && (
          <span className="comment-version-chip"
            data-tooltip={`节点现在是第 ${oldVersion.currentVersion} 版${oldVersion.time != null ? ` · 钉在 ${formatMoment(oldVersion.time)}` : ''}`}>
            针对第 {oldVersion.version} 版
          </span>
        )}
        {controls}
      </div>
      <div className="comment-msg-body">
        {item.type === 'user' && <div className="comment-msg-text"><MentionText text={item.text} /></div>}
        {item.type === 'agent' && (
          <>
            {item.text && <div className="comment-msg-text"><Markdown text={item.text} /></div>}
            {!item.text && item.live && !item.confirm && item.runId && (
              <div className="comment-msg-working">
                <span className="agent-thinking" aria-hidden="true"><span /><span /><span /></span>
                {item.current && <span>{item.current}</span>}
              </div>
            )}
            {item.errors.map((error) => <div key={error} className="comment-msg-error">{error}</div>)}
            {item.finished === 'stopped' && <div className="comment-msg-quiet">已停止</div>}
            {item.finished === 'failed' && !item.errors.length && <div className="comment-msg-quiet">这一轮没有完成</div>}
            {item.undone && <div className="comment-msg-quiet">已撤销这一轮的改动</div>}
          </>
        )}
        {children}
      </div>
    </div>
  );
}
