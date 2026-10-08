import { useEffect, useRef, useState } from 'react';

import { CloseIcon, SendIcon, UndoIcon } from '../canvas/icons';
import { agentApi, type AgentEvent } from '../agent/agentApi';
import { AgentMessage } from '../agent/AgentMessage';
import { pendingConfirmations, undoableRuns } from '../agent/agentStore';
import { Markdown } from '../agent/Markdown';
import { assetFileUrl, formatMoment, STATUS_LABELS, type CanvasComment } from './commentApi';
import { queuePosition, useCommentStore } from './commentStore';
import { useSessionEvents } from './useSessionEvents';
import { sideOf } from './mediaGeometry';

/** Only what helps at a glance; skills, sources and to-do lists are in the panel. */
const SHOWN = new Set<AgentEvent['kind']>(['user_message', 'assistant_text', 'tool_step', 'confirm_request', 'error', 'run_undone']);

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

const WIDTH = 320;

export function CommentPopover({ comment, at, bounds, where, onClose, onOpenInPanel, onFocusNodes, onSaveToCanvas }: CommentPopoverProps) {
  const { events, streaming } = useSessionEvents(comment.sessionId);
  const comments = useCommentStore((state) => state.comments);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const busy = comment.status === 'queued' || comment.status === 'running' || comment.status === 'waiting';

  useEffect(() => {
    const body = bodyRef.current;
    if (body) body.scrollTop = body.scrollHeight;
  }, [events.length, streaming]);

  const pending = new Set(pendingConfirmations(events).map((event) => event.requestId));
  const shown = events.filter((event) => SHOWN.has(event.kind));
  // Same rule as the panel: the last finished round, if it changed something, can be undone.
  const lastRun = [...events].reverse().find((event) => event.kind === 'run_finished')?.runId ?? null;
  const canUndo = !busy && lastRun !== null && undoableRuns(events).has(lastRun);
  const [undoing, setUndoing] = useState(false);

  async function undo() {
    if (!lastRun || undoing) return;
    setUndoing(true);
    try {
      await agentApi.undo(lastRun); // the "已撤销" note arrives through the stream
    } catch (error) {
      useCommentStore.setState({ error: error instanceof Error ? error.message : '撤销失败' });
    } finally {
      setUndoing(false);
    }
  }
  const anchor = comment.anchor;
  const oldVersion = Boolean(anchor.stale);

  // Beside the pin, kept inside the canvas.
  const left = at ? sideOf(at.x, WIDTH, bounds.width) : Math.max(8, (bounds.width - WIDTH) / 2);
  const top = at ? Math.min(Math.max(8, at.y - 44), Math.max(8, bounds.height - 420)) : 80;

  async function send() {
    const text = draft.trim();
    if (!text || sending || busy) return;
    setSending(true);
    if (await useCommentStore.getState().reply(comment.id, text)) setDraft('');
    setSending(false);
  }

  async function confirm(event: AgentEvent, approved: boolean, note: string) {
    if (!event.runId || !event.requestId) return false;
    try {
      await agentApi.confirm(event.runId, event.requestId, approved, note);
      return true;
    } catch (error) {
      useCommentStore.setState({ error: error instanceof Error ? error.message : '提交失败' });
      return false;
    }
  }

  return (
    <div
      className={`comment-popover comment-ui is-${comment.status}`}
      role="dialog"
      aria-label="留言"
      style={{ left, top, width: WIDTH }}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === 'Escape') onClose();
      }}
    >
      <header className="comment-popover-head">
        <span className="comment-popover-where" title={where}>{where}</span>
        <span className={`comment-status is-${comment.status}`}>
          {comment.status === 'queued' ? `排队中 · 第 ${queuePosition(comments, comment.id)} 个` : STATUS_LABELS[comment.status]}
        </span>
        <button type="button" className="comment-icon" aria-label="关闭" onClick={onClose}>
          <CloseIcon width={14} height={14} />
        </button>
      </header>
      {oldVersion && anchor.assetId && (
        <div className="comment-old-version">
          {anchor.time != null
            ? <video src={assetFileUrl(anchor.assetId)} muted preload="metadata" />
            : <img src={assetFileUrl(anchor.assetId)} alt={`第 ${anchor.version} 版`} />}
          <span>针对第 {anchor.version} 版{anchor.time != null ? ` 的 ${formatMoment(anchor.time)}` : ''}，节点现在是第 {anchor.currentVersion} 版</span>
        </div>
      )}
      {comment.nodeMissing && <div className="comment-note">节点已经删除了，这条留言不能再继续。</div>}
      <div ref={bodyRef} className="comment-thread">
        {/* Before the first run starts, the comment itself stands in for the first message. */}
        {!shown.some((event) => event.kind === 'user_message') && (
          <div className="agent-msg is-user"><div className="agent-bubble">{comment.text}</div></div>
        )}
        {shown.map((event, index) => (
          <AgentMessage
            key={event.id ?? `live-${index}`}
            event={event.kind === 'user_message' ? { ...event, focus: [] } : event}
            focusTitles={{}}
            onFocusNodes={onFocusNodes}
            onSaveToCanvas={onSaveToCanvas}
            onConfirm={(target, approved, note) => confirm(target, approved, note)}
            pending={pending.has(event.requestId)}
          />
        ))}
        {streaming && <div className="agent-msg is-assistant is-streaming"><Markdown text={streaming} /></div>}
        {comment.status === 'running' && !streaming && pending.size === 0 && (
          <div className="agent-thinking" aria-live="polite"><span /><span /><span /></div>
        )}
        {canUndo && (
          <button type="button" className="agent-undo comment-undo" disabled={undoing} onClick={() => void undo()}>
            <UndoIcon width={13} height={13} /> 撤销这一轮的改动
          </button>
        )}
        {comment.pendingReply && <div className="comment-note">你的回复在排队：{comment.pendingReply}</div>}
      </div>
      <footer className="comment-popover-foot">
        <div className="comment-reply">
          <textarea
            rows={1}
            value={draft}
            aria-label="回复留言"
            disabled={busy || comment.nodeMissing}
            placeholder={busy ? 'Agent 正在处理…' : comment.status === 'resolved' ? '回复会重新打开这条留言' : '接着说，Enter 发送'}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.nativeEvent.isComposing) return;
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
          />
          <button type="button" className="comment-send" aria-label="发送回复" disabled={!draft.trim() || busy || sending}
            onClick={() => void send()}>
            <SendIcon width={13} height={13} />
          </button>
        </div>
        <div className="comment-actions">
          <button type="button" className="comment-link" onClick={() => onOpenInPanel(comment)}>在面板中打开</button>
          {comment.status === 'resolved' ? (
            <button type="button" className="comment-button" onClick={() => void useCommentStore.getState().reopen(comment.id)}>
              重新打开
            </button>
          ) : (
            <button type="button" className="comment-button is-primary" disabled={busy}
              data-tooltip={busy ? 'Agent 还在处理，做完再解决' : undefined}
              onClick={() => void useCommentStore.getState().resolve(comment.id)}>
              解决
            </button>
          )}
        </div>
      </footer>
    </div>
  );
}
