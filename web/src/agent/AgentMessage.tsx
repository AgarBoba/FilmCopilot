import { useState } from 'react';

import { CheckIcon, CopyIcon, NoteAddIcon } from '../canvas/icons';
import type { AgentEvent } from './agentApi';
import { Markdown } from './Markdown';

interface AgentMessageProps {
  event: AgentEvent;
  focusTitles: Record<string, string>;
  onFocusNodes: (nodeIds: string[]) => void;
  onSaveToCanvas: (text: string) => void;
  onConfirm: (event: AgentEvent, approved: boolean) => void;
  pending: boolean;
}


export function AgentMessage({ event, focusTitles, onFocusNodes, onSaveToCanvas, onConfirm, pending }: AgentMessageProps) {
  switch (event.kind) {
    case 'user_message':
      return (
        <div className="agent-msg is-user">
          {event.focus && event.focus.length > 0 && (
            <div className="agent-focus-line">
              关注：{event.focus.map((id) => focusTitles[id] ?? '已删除的节点').join('、')}
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
      return (
        <div className={`agent-confirm ${pending ? '' : 'is-done'}`}>
          <div className="agent-confirm-title">需要你确认</div>
          <div className="agent-confirm-summary">{event.summary}</div>
          {event.reason && <div className="agent-confirm-reason">{event.reason}</div>}
          {pending && (
            <div className="agent-confirm-actions">
              <button type="button" className="is-primary" onClick={() => onConfirm(event, true)}>确认</button>
              <button type="button" onClick={() => onConfirm(event, false)}>拒绝</button>
            </div>
          )}
        </div>
      );
    case 'confirm_resolved':
      return <div className="agent-note">{event.approved ? '已确认' : '已拒绝'}</div>;
    case 'error':
      return <div className="agent-note is-error">{event.message}</div>;
    case 'run_finished':
      if (event.status === 'completed') return null;
      return <div className="agent-note">{event.status === 'stopped' ? '已停止' : '这一轮没有完成'}</div>;
    case 'run_undone': {
      const skipped = event.skipped ?? [];
      return (
        <div className="agent-note">
          已撤销这一轮的改动
          {skipped.length > 0 && `；${skipped.length} 处你之后改过，保留了你的版本`}
        </div>
      );
    }
    default:
      return null;
  }
}


function AssistantText({ text, onSaveToCanvas }: { text: string; onSaveToCanvas: (text: string) => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="agent-msg is-assistant">
      <Markdown text={text} />
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
        <button
          type="button"
          aria-label="存到画布"
          data-tooltip="存成便签放到画布上"
          onClick={() => onSaveToCanvas(text)}
        >
          <NoteAddIcon width={14} height={14} />
        </button>
      </div>
    </div>
  );
}
