import { useState } from 'react';

import { CheckIcon, CopyIcon } from '../canvas/icons';
import { ApiError } from '../api/client';
import { agentApi, type AgentEvent } from './agentApi';
import { Markdown } from './Markdown';
import { ReferenceStrip, type NodeReference } from '../nodes/ReferenceStrip';

interface AgentMessageProps {
  event: AgentEvent;
  focusTitles: Record<string, string>;
  focusPreviews?: Record<string, NodeReference>;
  onFocusNodes: (nodeIds: string[]) => void;
  onSaveToCanvas: (text: string, title?: string) => void;
  onConfirm: (event: AgentEvent, approved: boolean, note: string) => Promise<boolean> | void;
  pending: boolean;
}


export function AgentMessage({ event, focusTitles, focusPreviews = {}, onFocusNodes, onSaveToCanvas, onConfirm, pending }: AgentMessageProps) {
  switch (event.kind) {
    case 'user_message':
      return (
        <div className="agent-msg is-user">
          {event.focus && event.focus.length > 0 && (
            <div className="agent-focus-line">
              <ReferenceStrip
                compact
                label="这条消息关注的节点"
                references={event.focus.map((id) => focusPreviews[id]
                  ?? { nodeId: id, kind: 'note' as const, title: focusTitles[id] ?? '已删除的节点' })}
              />
            </div>
          )}
          <div className="agent-bubble">{event.text}</div>
        </div>
      );
    case 'assistant_text':
      return <AssistantText text={event.text ?? ''} onSaveToCanvas={onSaveToCanvas} />;
    case 'tool_step': {
      const clickable = (event.touched ?? []).length > 0;
      return (
        <button
          type="button"
          className={`agent-step ${event.isError ? 'is-error' : ''}`}
          disabled={!clickable}
          data-tooltip={event.isError ? event.detail : clickable ? '在画布上定位' : undefined}
          data-tooltip-side="left"
          onClick={() => onFocusNodes(event.touched ?? [])}
        >
          <span className="agent-step-dot" aria-hidden="true" />
          <span>{event.summary}</span>
          {event.isError && <span className="agent-step-flag">未完成</span>}
        </button>
      );
    }
    case 'confirm_request':
      return <ConfirmCard event={event} pending={pending} onConfirm={onConfirm} />;
    case 'confirm_resolved':
      return (
        <div className="agent-note">
          {event.approved ? '已确认' : '已拒绝'}
          {event.note && <span className="agent-note-extra">补充：{event.note}</span>}
        </div>
      );
    case 'error':
      return <div className="agent-note is-error">{event.message}</div>;
    case 'run_finished':
      if (event.status === 'completed') return null;
      return <div className="agent-note">{event.status === 'stopped' ? '已停止' : '这一轮没有完成'}</div>;
    case 'memory_change':
      return <MemoryLine event={event} />;
    case 'run_undone': {
      const skipped = event.skipped ?? [];
      return (
        <div className="agent-note">
          已撤销这一轮的改动
          {(event.memoriesReverted ?? 0) > 0 && `，收回了 ${event.memoriesReverted} 条记忆`}
          {skipped.length > 0 && `；${skipped.length} 处你之后改过，保留了你的版本`}
        </div>
      );
    }
    default:
      return null;
  }
}


/**
 * Confirm or reject, optionally with a note. Rejecting with a note tells the agent what to
 * change; confirming with a note lets the step run as proposed and steers the next steps.
 */
function ConfirmCard({ event, pending, onConfirm }: {
  event: AgentEvent;
  pending: boolean;
  onConfirm: (event: AgentEvent, approved: boolean, note: string) => Promise<boolean> | void;
}) {
  const [note, setNote] = useState('');
  const [sent, setSent] = useState(false);
  const answer = (approved: boolean) => {
    if (sent) return;
    setSent(true);
    void Promise.resolve(onConfirm(event, approved, note.trim())).then((ok) => {
      if (ok === false) setSent(false); // request failed: let the user try again
    });
  };
  const open = pending && !sent;
  return (
    <div className={`agent-confirm ${open ? '' : 'is-done'}`}>
      <div className="agent-confirm-title">需要你确认</div>
      <div className="agent-confirm-summary">{event.summary}</div>
      {event.reason && <div className="agent-confirm-reason">{event.reason}</div>}
      {open && (
        <>
          <textarea
            className="agent-confirm-note"
            aria-label="补充说明"
            rows={1}
            value={note}
            placeholder="补充说明（可选）：拒绝时告诉它怎么改，确认时作为后续要求"
            onChange={(change) => setNote(change.target.value)}
            onKeyDown={(key) => {
              if (key.key === 'Enter' && (key.metaKey || key.ctrlKey) && !key.nativeEvent.isComposing) {
                key.preventDefault();
                answer(true);
              }
            }}
          />
          <div className="agent-confirm-actions">
            <button type="button" className="is-primary" data-tooltip-shortcut="⌘↵" onClick={() => answer(true)}>
              {note.trim() ? '确认并补充' : '确认'}
            </button>
            <button type="button" onClick={() => answer(false)}>
              {note.trim() ? '拒绝并说明' : '拒绝'}
            </button>
          </div>
        </>
      )}
    </div>
  );
}


const LAYER_LABELS = { project: '项目记忆', preference: '我的偏好' } as const;

/** "记下了（项目记忆 · 角色）：主角是…   撤销" — memory changes show in the chat and can be undone. */
function MemoryLine({ event }: { event: AgentEvent }) {
  const [state, setState] = useState<'idle' | 'busy' | 'undone' | 'failed'>('idle');
  const verb = event.action === 'updated' ? '更新了记忆' : event.action === 'removed' ? '忘掉了' : '记下了';
  const where = [event.layer ? LAYER_LABELS[event.layer] : '', event.categoryLabel].filter(Boolean).join(' · ');
  return (
    <div className={`agent-memory-line ${state === 'undone' ? 'is-undone' : ''}`}>
      <span className="agent-memory-icon" aria-hidden="true">✦</span>
      <span className="agent-memory-text">
        {verb}{where && <span className="agent-memory-where">（{where}）</span>}：
        {event.action === 'updated' && event.previous && <s className="agent-memory-previous">{event.previous}</s>}
        {event.action === 'updated' && event.previous && ' → '}
        {event.content}
      </span>
      {event.memoryId !== undefined && state !== 'undone' && (
        <button
          type="button"
          className="agent-memory-undo"
          disabled={state === 'busy'}
          onClick={async () => {
            setState('busy');
            try {
              await agentApi.revertMemory(event.memoryId!);
              setState('undone');
            } catch (error) {
              // Already undone earlier (e.g. before a reload): nothing left to take back.
              setState(error instanceof ApiError && error.status === 404 ? 'undone' : 'failed');
            }
          }}
        >
          {state === 'failed' ? '撤销失败，再试' : '撤销'}
        </button>
      )}
      {state === 'undone' && <span className="agent-memory-undone">已撤销</span>}
    </div>
  );
}


function AssistantText({ text, onSaveToCanvas }: { text: string; onSaveToCanvas: (text: string, title?: string) => void }) {
  const [copied, setCopied] = useState(false);
  // Only special blocks (tables, code, prompts, quotes) can be saved, each on its own.
  return (
    <div className="agent-msg is-assistant">
      <Markdown text={text} onSaveNote={(content, title) => onSaveToCanvas(content, title)} />
      <div className="agent-msg-actions">
        <button
          type="button"
          aria-label="复制"
          data-tooltip={copied ? '已复制' : '复制'}
          onClick={() => {
            void navigator.clipboard?.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? <CheckIcon width={14} height={14} /> : <CopyIcon width={14} height={14} />}
        </button>
      </div>
    </div>
  );
}
