import { create } from 'zustand';

import type { AgentEvent, AgentSession, AgentSettings } from './agentApi';

export const RECENT_MARK_MS = 4000;

/** What the panel renders: persisted events plus the text currently streaming in. */
export interface AgentState {
  open: boolean;
  configured: boolean | null;
  model: string;
  sessions: AgentSession[];
  sessionId: string | null;
  events: AgentEvent[];
  /** Text of the assistant message still streaming, per run. */
  streaming: Record<string, string>;
  activeRunId: string | null;
  /** The run that just finished while we watched; its nodes stay marked for a moment. */
  recentRunId: string | null;
  settings: AgentSettings | null;
  lastEventId: number;
  error: string | null;
  setOpen: (open: boolean) => void;
  reset: (sessionId: string | null, events?: AgentEvent[]) => void;
  apply: (event: AgentEvent) => void;
}

export const useAgentStore = create<AgentState>((set, get) => ({
  open: false,
  configured: null,
  model: '',
  sessions: [],
  sessionId: null,
  events: [],
  streaming: {},
  activeRunId: null,
  recentRunId: null,
  settings: null,
  lastEventId: 0,
  error: null,

  setOpen: (open) => set({ open }),

  reset: (sessionId, events = []) => {
    set({ sessionId, events: [], streaming: {}, activeRunId: null, recentRunId: null, lastEventId: 0, error: null });
    events.forEach((event) => get().apply(event));
    set({ recentRunId: null }); // history, not something that just happened
  },

  apply: (event) => {
    const state = get();
    if (event.id !== null && event.id <= state.lastEventId) return; // replayed after reconnect
    const runId = event.runId ?? '';
    const streaming = { ...state.streaming };
    let activeRunId = state.activeRunId;
    let recentRunId = state.recentRunId;

    switch (event.kind) {
      case 'text_delta':
        streaming[runId] = (streaming[runId] ?? '') + (event.text ?? '');
        set({ streaming, activeRunId: runId || activeRunId });
        return;
      case 'user_message':
        activeRunId = event.runId;
        break;
      case 'assistant_text':
        delete streaming[runId]; // the full message replaces what streamed in
        break;
      case 'run_finished':
        delete streaming[runId];
        if (activeRunId === event.runId) {
          activeRunId = null;
          recentRunId = event.runId;
          setTimeout(() => {
            if (get().recentRunId === event.runId) set({ recentRunId: null });
          }, RECENT_MARK_MS);
        }
        break;
      default:
        break;
    }
    set({
      events: [...state.events, event],
      streaming,
      activeRunId,
      recentRunId,
      lastEventId: event.id ?? state.lastEventId,
    });
  },
}));

/** Confirmation requests that have not been answered yet. */
export function pendingConfirmations(events: AgentEvent[]): AgentEvent[] {
  const resolved = new Set(
    events.filter((event) => event.kind === 'confirm_resolved').map((event) => event.requestId),
  );
  const finished = new Set(events.filter((event) => event.kind === 'run_finished').map((event) => event.runId));
  return events.filter(
    (event) => event.kind === 'confirm_request' && !resolved.has(event.requestId) && !finished.has(event.runId),
  );
}

/** Runs that finished, made changes and have not been undone: they can still be undone. */
export function undoableRuns(events: AgentEvent[]): Set<string> {
  const changed = new Set(
    events
      .filter((event) => event.kind === 'memory_change' || (event.kind === 'tool_step' && !event.isError
        && (event.tool ?? '') !== ''
        && !['get_canvas', 'get_node', 'view_asset', 'wait_for_generation', 'recall'].includes(event.tool ?? '')))
      .map((event) => event.runId),
  );
  const undone = new Set(events.filter((event) => event.kind === 'run_undone').map((event) => event.runId));
  const finished = events.filter((event) => event.kind === 'run_finished').map((event) => event.runId);
  return new Set(finished.filter((runId): runId is string => !!runId && changed.has(runId) && !undone.has(runId)));
}
