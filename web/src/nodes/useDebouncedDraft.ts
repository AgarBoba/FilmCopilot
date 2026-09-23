import { useCallback, useEffect, useRef, useState } from 'react';


/**
 * Local text state for an input that saves to the server.
 *
 * Typing updates the draft immediately; the save runs `delay` ms after the last
 * keystroke (or right away on `flush`, e.g. on blur). This keeps each keystroke
 * from becoming its own save request.
 */
export function useDebouncedDraft(
  value: string,
  onCommit: ((next: string) => void) | undefined,
  delay = 500,
) {
  const [draft, setDraftState] = useState(value);
  const draftRef = useRef(value);
  const committedRef = useRef(value);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onCommitRef = useRef(onCommit);
  const editingRef = useRef(false);
  onCommitRef.current = onCommit;

  const flush = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    editingRef.current = false;
    if (draftRef.current !== committedRef.current) {
      committedRef.current = draftRef.current;
      onCommitRef.current?.(draftRef.current);
    }
  }, []);

  const setDraft = useCallback((next: string) => {
    editingRef.current = true;
    draftRef.current = next;
    setDraftState(next);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(flush, delay);
  }, [delay, flush]);

  // Take server-side changes, but never overwrite text the user is still typing.
  useEffect(() => {
    if (editingRef.current) return;
    committedRef.current = value;
    draftRef.current = value;
    setDraftState(value);
  }, [value]);

  // Save anything pending if the node unmounts (deleted, canvas switched).
  useEffect(() => flush, [flush]);

  return { draft, setDraft, flush };
}
