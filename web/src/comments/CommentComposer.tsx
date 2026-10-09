import { useEffect, useRef, useState } from 'react';

import { SendIcon } from '../canvas/icons';
import { MENTION } from './commentApi';

interface CommentComposerProps {
  placeholder: string;
  /** "@Agent" starts ticked (a comment already handed to the agent). */
  defaultAgent?: boolean;
  /** The agent is busy with this comment: only plain replies for now. */
  agentDisabled?: boolean;
  disabled?: boolean;
  autoFocus?: boolean;
  label: string;
  onSubmit: (text: string, toAgent: boolean) => Promise<boolean>;
  onCancel?: () => void;
}

const AGENT_HINT = '勾上会在开头加上 @Agent，交给 Agent 处理；直接打 @Agent 效果一样。不勾就是普通留言，Agent 看得到但不会动手';
const MENTION_ALL = /[@＠]\s*agent(?![a-z])\s?/gi;
const PREFIX = '@Agent ';

/** The text without any "@Agent" in it. */
function withoutMention(text: string): string {
  return text.replace(MENTION_ALL, '').replace(/^\s+/, '');
}

/**
 * The reply box shared by a new comment and a thread: text, an "@Agent 让它处理" tick on
 * the left and a round send button on the right. The tick and "@Agent" in the text are the
 * same thing: ticking puts "@Agent" at the front, unticking takes it out, typing it ticks
 * the box. "@Agent" shows in the accent colour while typing (a mirror behind the textarea).
 */
export function CommentComposer({
  placeholder, defaultAgent = false, agentDisabled = false, disabled = false, autoFocus = false, label, onSubmit, onCancel,
}: CommentComposerProps) {
  const start = defaultAgent && !agentDisabled ? PREFIX : '';
  const [text, setText] = useState(start);
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const mirrorRef = useRef<HTMLDivElement>(null);

  // Opened with "@Agent " already in: type after it.
  useEffect(() => {
    const input = inputRef.current;
    if (autoFocus && input) input.setSelectionRange(input.value.length, input.value.length);
  }, [autoFocus]);

  // A new default (handed off, or the agent got busy / finished): start from it if nothing was typed.
  useEffect(() => {
    setText((current) => (withoutMention(current).trim() ? current : start));
  }, [start]);

  const toAgent = MENTION.test(text) && !agentDisabled;
  const body = withoutMention(text).trim();
  const canSend = Boolean(body) && !sending && !disabled && !(agentDisabled && MENTION.test(text));

  function setAgent(on: boolean) {
    const next = on ? PREFIX + withoutMention(text) : withoutMention(text);
    setText(next);
    const input = inputRef.current;
    if (input) {
      input.focus();
      requestAnimationFrame(() => input.setSelectionRange(next.length, next.length));
    }
  }

  async function send() {
    if (!canSend) return;
    setSending(true);
    const ok = await onSubmit(text.trim(), toAgent);
    setSending(false);
    if (ok) setText(start);
  }

  return (
    <div className={`comment-composer ${toAgent ? 'is-agent' : ''}`}>
      <div className="comment-input">
        <div ref={mirrorRef} className="comment-input-mirror" aria-hidden="true">
          <MentionText text={text} />{'\u200b'}
        </div>
        <textarea
          ref={inputRef}
          autoFocus={autoFocus}
          rows={1}
          value={text}
          aria-label={label}
          disabled={disabled}
          placeholder={placeholder}
          onScroll={(event) => {
            if (mirrorRef.current) mirrorRef.current.scrollTop = event.currentTarget.scrollTop;
          }}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing) return;
            if (event.key === 'Escape' && onCancel) {
              event.preventDefault();
              onCancel();
            } else if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
        />
      </div>
      <div className="comment-composer-foot">
        <label
          className={`comment-agent-tick ${agentDisabled ? 'is-disabled' : ''}`}
          data-tooltip={agentDisabled ? 'Agent 正在处理这条留言，做完再交给它' : AGENT_HINT}
          data-tooltip-side="bottom"
        >
          <input
            type="checkbox"
            checked={toAgent}
            disabled={agentDisabled || disabled}
            onChange={(event) => setAgent(event.target.checked)}
          />
          @Agent 让它处理
        </label>
        <button type="button" className="comment-send" aria-label="发送" disabled={!canSend} onClick={() => void send()}>
          <SendIcon width={14} height={14} />
        </button>
      </div>
    </div>
  );
}

/** The text with "@Agent" picked out in the accent colour. */
export function MentionText({ text }: { text: string }) {
  const parts = text.split(/([@＠]\s*agent(?![a-z]))/i);
  return (
    <>
      {parts.map((part, index) => (index % 2 === 1
        ? <span key={index} className="comment-mention">{part}</span>
        : part))}
    </>
  );
}
