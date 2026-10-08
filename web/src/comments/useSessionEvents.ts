import { useEffect, useRef, useState } from 'react';

import { agentApi, type AgentEvent } from '../agent/agentApi';

/**
 * One agent conversation, read live: its history, then every new event. The comment
 * popover uses this while the panel may show the same conversation through its own
 * stream; both read the same server session, so they stay in step.
 */
export function useSessionEvents(sessionId: string | null) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [streaming, setStreaming] = useState('');
  const lastId = useRef(0);

  useEffect(() => {
    setEvents([]);
    setStreaming('');
    lastId.current = 0;
    if (!sessionId) return undefined;
    let cancelled = false;
    let stop: (() => void) | null = null;
    const apply = (event: AgentEvent) => {
      if (event.kind === 'text_delta') {
        setStreaming((text) => text + (event.text ?? ''));
        return;
      }
      if (event.id !== null) {
        if (event.id <= lastId.current) return;
        lastId.current = event.id;
      }
      if (event.kind === 'assistant_text' || event.kind === 'run_finished') setStreaming('');
      setEvents((current) => [...current, event]);
    };
    void agentApi.messages(sessionId).then((history) => {
      if (cancelled) return;
      history.forEach(apply);
      stop = agentApi.stream(sessionId, () => lastId.current, apply);
    }).catch(() => undefined);
    return () => {
      cancelled = true;
      stop?.();
    };
  }, [sessionId]);

  return { events, streaming };
}
