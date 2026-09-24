import { ApiError } from '../api/client';

const apiBase = import.meta.env.VITE_API_BASE_URL ?? '/api';

export type PermissionMode = 'confirm_all' | 'confirm_generation' | 'auto';

export interface AgentSettings {
  permissionMode: PermissionMode;
  generationCap: number;
  /** Chosen model id; missing / null means the server default. */
  model?: string | null;
}

export type AgentAuth = 'api' | 'subscription';

export interface AgentStatus {
  configured: boolean;
  /** Default model id. */
  model: string;
  auth: AgentAuth;
  models: { id: string; label: string }[];
}

export interface AgentSession {
  id: string;
  project_id: string;
  canvas_id: string;
  title: string | null;
  created_at: string;
  activeRunId?: string | null;
  /** Filled by the list endpoint. */
  preview?: string;
  message_count?: number;
  last_active_at?: string;
  status?: 'idle' | 'running' | 'waiting';
  archived_at?: string | null;
}

export type MemoryLayer = 'project' | 'preference';

export interface Memory {
  id: number;
  layer: MemoryLayer;
  project_id: string | null;
  category: string;
  categoryLabel: string;
  content: string;
  source: 'user_stated' | 'agent_inferred' | 'user_edited';
  status: 'active' | 'pending' | 'superseded' | 'rejected' | 'removed';
  superseded_by: number | null;
  session_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryList {
  project: Memory[];
  preference: Memory[];
  categories: Record<MemoryLayer, Record<string, string>>;
}

/** One entry of the agent stream. Persisted entries have an `id`; text deltas do not. */
export interface AgentEvent {
  id: number | null;
  runId: string | null;
  kind:
    | 'user_message'
    | 'text_delta'
    | 'assistant_text'
    | 'tool_step'
    | 'confirm_request'
    | 'confirm_resolved'
    | 'error'
    | 'run_finished'
    | 'run_undone'
    | 'memory_change';
  createdAt?: string;
  text?: string;
  focus?: string[];
  tool?: string;
  summary?: string;
  touched?: string[];
  isError?: boolean;
  detail?: string;
  imageCount?: number;
  requestId?: string;
  reason?: string;
  approved?: boolean;
  note?: string;
  message?: string;
  status?: 'completed' | 'stopped' | 'failed';
  costUsd?: number | null;
  skipped?: { type: string; id: string; reason: string }[];
  deletedNodes?: string[];
  restoredNodes?: string[];
  memoriesReverted?: number;
  /** assistant_text / run_finished: which model answered. */
  model?: string;
  /** memory_change */
  memoryId?: number;
  action?: 'added' | 'updated' | 'removed';
  content?: string;
  previous?: string;
  layer?: MemoryLayer;
  categoryLabel?: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    let body: { error?: { code?: string; message?: string } } = {};
    try {
      body = await response.json();
    } catch {
      // no JSON body
    }
    throw new ApiError(
      body.error?.code ?? 'HTTP_ERROR',
      body.error?.message ?? `Request failed with status ${response.status}`,
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const agentApi = {
  status: () => call<AgentStatus>('/agent/status'),
  createSession: (canvasId: string) =>
    call<AgentSession>('/agent/sessions', { method: 'POST', body: JSON.stringify({ canvasId }) }),
  listSessions: (canvasId: string) =>
    call<AgentSession[]>(`/agent/sessions?canvasId=${encodeURIComponent(canvasId)}`),
  updateSession: (sessionId: string, changes: { title?: string; archived?: boolean }) =>
    call<AgentSession>(`/agent/sessions/${sessionId}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  messages: (sessionId: string, after = 0) =>
    call<AgentEvent[]>(`/agent/sessions/${sessionId}/messages?after=${after}`),
  send: (sessionId: string, text: string, focusNodeIds: string[]) =>
    call<{ runId: string }>(`/agent/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text, focusNodeIds }),
    }),
  confirm: (runId: string, requestId: string, approved: boolean, note = '') =>
    call<{ resolved: boolean }>(`/agent/runs/${runId}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ requestId, approved, note }),
    }),
  stop: (runId: string) => call<{ stopping: boolean }>(`/agent/runs/${runId}/stop`, { method: 'POST' }),
  undo: (runId: string) => call<AgentEvent>(`/agent/runs/${runId}/undo`, { method: 'POST' }),
  listMemories: (projectId: string) => call<MemoryList>(`/memories?projectId=${encodeURIComponent(projectId)}`),
  addMemory: (projectId: string, layer: MemoryLayer, content: string, category: string) =>
    call<Memory>('/memories', { method: 'POST', body: JSON.stringify({ projectId, layer, content, category }) }),
  editMemory: (id: number, changes: { content?: string; category?: string }) =>
    call<Memory>(`/memories/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  deleteMemory: (id: number) => call<void>(`/memories/${id}`, { method: 'DELETE' }),
  revertMemory: (id: number) => call<{ action: string }>(`/memories/${id}/revert`, { method: 'POST' }),
  getSettings: (projectId: string) => call<AgentSettings>(`/projects/${projectId}/agent-settings`),
  updateSettings: (projectId: string, changes: Partial<AgentSettings>) =>
    call<AgentSettings>(`/projects/${projectId}/agent-settings`, {
      method: 'PATCH',
      body: JSON.stringify(changes),
    }),

  /** Live stream; reconnects on its own and resumes after the last persisted event. */
  stream(sessionId: string, after: () => number, onEvent: (event: AgentEvent) => void): () => void {
    let source: EventSource | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const kinds: AgentEvent['kind'][] = [
      'user_message', 'text_delta', 'assistant_text', 'tool_step', 'confirm_request',
      'confirm_resolved', 'error', 'run_finished', 'run_undone', 'memory_change',
    ];
    const open = () => {
      if (closed) return;
      source = new EventSource(`${apiBase}/agent/sessions/${sessionId}/stream?after=${after()}`);
      const handle = (message: MessageEvent) => {
        // The browser's own connection-error event is also named "error" and carries no data.
        if (typeof message.data !== 'string' || !message.data) return;
        onEvent(JSON.parse(message.data) as AgentEvent);
      };
      kinds.forEach((kind) => source?.addEventListener(kind, handle as EventListener));
      source.onerror = () => {
        source?.close();
        if (!closed) retry = setTimeout(open, 1500);
      };
    };
    open();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      source?.close();
    };
  },
};
