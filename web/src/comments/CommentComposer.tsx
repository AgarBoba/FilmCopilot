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

const AGENT_HINT = '勾上后交给 Agent 处理；直接打 @Agent 也会自动勾上。不勾就是普通留言，Agent 看得到但不会动手';

/**
 * The reply box shared by a new comment and a thread: text, an "@Agent 让它处理" tick on
 * the left and a round send button on the right. Ticked, the text goes out with "@Agent"
 * in front, so the thread shows who it was for.
 */
export function CommentComposer({
  placeholder, defaultAgent = false, agentDisabled = false, disabled = false, autoFocus = false, label, onSubmit, onCancel,
}: CommentComposerProps) {
  const [text, setText] = useState('');
  const [agent, setAgent] = useState(defaultAgent);
  const [sending, setSending] = useState(false);
  const mentioned = useRef(false);

  useEffect(() => setAgent(defaultAgent), [defaultAgent]);

  const toAgent = agent && !agentDisabled;
  const canSend = Boolean(text.trim()) && !sending && !disabled && !(agentDisabled && MENTION.test(text));

  async function send() {
    if (!canSend) return;
    let body = text.trim();
    if (toAgent && !MENTION.test(body)) body = `@Agent ${body}`;
    setSending(true);
    const ok = await onSubmit(body, toAgent);
    setSending(false);
    if (ok) {
      setText('');
      mentioned.current = false;
    }
  }

  return (
    <div className={`comment-composer ${toAgent ? 'is-agent' : ''}`}>
      <textarea
        autoFocus={autoFocus}
        rows={2}
        value={text}
        aria-label={label}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(event) => {
          const value = event.target.value;
          setText(value);
          // Typing "@Agent" ticks the box (once; unticking afterwards is respected).
          const has = MENTION.test(value);
          if (has && !mentioned.current && !agentDisabled) setAgent(true);
          mentioned.current = has;
        }}
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
