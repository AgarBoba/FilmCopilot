import { useEffect, useRef, useState } from 'react';


interface NodeTitleProps {
  title?: string;
  /** Shown as placeholder, and restored if the title is cleared. */
  fallback: string;
  onChange?: (title: string) => void;
}

const MAX_TITLE_LENGTH = 60;


/**
 * Inline-editable node name. Saves on Enter or blur, Esc reverts.
 * `nodrag` / `nopan` stop React Flow from dragging the node while you select text.
 */
export function NodeTitle({ title, fallback, onChange }: NodeTitleProps) {
  const saved = title?.trim() || fallback;
  const [draft, setDraft] = useState(saved);
  const inputRef = useRef<HTMLInputElement>(null);
  const cancelledRef = useRef(false);

  // Follow updates from elsewhere (e.g. another tab or the Agent API) unless the user is typing.
  useEffect(() => {
    if (document.activeElement !== inputRef.current) setDraft(saved);
  }, [saved]);

  function commit() {
    if (cancelledRef.current) {
      cancelledRef.current = false;
      setDraft(saved);
      return;
    }
    const next = draft.trim().slice(0, MAX_TITLE_LENGTH);
    if (!next) {
      setDraft(saved);
      return;
    }
    setDraft(next);
    if (next !== saved) onChange?.(next);
  }

  return (
    <input
      ref={inputRef}
      className="node-title nodrag nopan"
      value={draft}
      placeholder={fallback}
      maxLength={MAX_TITLE_LENGTH}
      aria-label="节点名称"
      spellCheck={false}
      onChange={(event) => setDraft(event.target.value)}
      onFocus={(event) => event.currentTarget.select()}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          event.currentTarget.blur();
        } else if (event.key === 'Escape') {
          event.preventDefault();
          cancelledRef.current = true;
          event.currentTarget.blur();
        }
      }}
    />
  );
}
