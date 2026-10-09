import { ApiError } from '../api/client';

const apiBase = import.meta.env.VITE_API_BASE_URL ?? '/api';

/** open / resolved, like any comment thread. */
export type CommentStatus = 'open' | 'resolved';
/** null: a plain note. Otherwise the agent's progress on it. */
export type AgentProgress = 'queued' | 'running' | 'waiting' | 'done' | 'failed';
/** What a pin shows: the comment's state in one word. */
export type PinState = 'note' | AgentProgress | 'resolved';

/**
 * Where a comment is pinned. canvas: x, y in canvas coordinates. node: the node itself.
 * media: x, y from 0 to 1 inside the picture (from the top left), time in seconds for videos.
 */
export interface CommentAnchor {
  kind: 'canvas' | 'node' | 'media';
  x?: number;
  y?: number;
  nodeId?: string;
  time?: number | null;
  /** media: the version it was pinned on, the asset of that version, and the node's version now. */
  version?: number | null;
  assetId?: string | null;
  currentVersion?: number | null;
  /** media: the node now shows a different picture than the one pinned. */
  stale?: boolean;
}

export interface CommentReply {
  id: number;
  text: string;
  author: string;
  /** This reply was handed to the agent. */
  toAgent: boolean;
  createdAt: string;
}

export interface CanvasComment {
  id: string;
  canvasId: string;
  /** The agent conversation behind it; null until the comment is first handed to the agent. */
  sessionId: string | null;
  anchor: CommentAnchor;
  text: string;
  author: string;
  status: CommentStatus;
  agentStatus: AgentProgress | null;
  /** The agent's last reply when it finished, or why it failed. */
  outcome: string | null;
  replies: CommentReply[];
  nodeMissing: boolean;
  createdAt: string;
  updatedAt: string;
  resolvedAt: string | null;
}

export interface NodeVersion {
  version: number;
  assetId: string;
  source: 'generated' | 'uploaded' | 'restored' | 'copied' | 'edited' | string;
  jobId: string | null;
  prompt: string | null;
  parameters: Record<string, unknown> | null;
  model: string | null;
  commentId: string | null;
  createdAt: string;
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

const post = (body?: unknown): RequestInit => ({ method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });

export const commentApi = {
  list: (canvasId: string) =>
    call<{ comments: CanvasComment[] }>(`/canvases/${encodeURIComponent(canvasId)}/comments`),
  create: (canvasId: string, anchor: CommentAnchor, text: string, toAgent = false) =>
    call<CanvasComment>(`/canvases/${encodeURIComponent(canvasId)}/comments`, post({ anchor, text, toAgent })),
  reply: (id: string, text: string, toAgent = false) => call<CanvasComment>(`/comments/${id}/reply`, post({ text, toAgent })),
  handOff: (id: string) => call<CanvasComment>(`/comments/${id}/agent`, post()),
  remove: (id: string) => call<void>(`/comments/${id}`, { method: 'DELETE' }),
  resolve: (id: string) => call<CanvasComment>(`/comments/${id}/resolve`, post()),
  reopen: (id: string) => call<CanvasComment>(`/comments/${id}/reopen`, post()),
  versions: (canvasId: string, nodeId: string) =>
    call<{ versions: NodeVersion[]; current: string | null }>(
      `/canvases/${encodeURIComponent(canvasId)}/nodes/${encodeURIComponent(nodeId)}/versions`,
    ),

  /** Every change to a comment on this canvas; reconnects on its own. */
  stream(
    canvasId: string,
    onComment: (comment: CanvasComment) => void,
    onReconnect?: () => void,
    onDeleted?: (id: string) => void,
  ): () => void {
    let source: EventSource | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const open = () => {
      if (closed || typeof EventSource === 'undefined') return;
      source = new EventSource(`${apiBase}/canvases/${encodeURIComponent(canvasId)}/comments/stream`);
      source.addEventListener('comment', ((message: MessageEvent<string>) => {
        try {
          const data = JSON.parse(message.data) as CanvasComment & { deleted?: boolean };
          if (data.deleted) onDeleted?.(data.id);
          else onComment(data);
        } catch {
          // ignore a malformed event; the next list refresh repairs it
        }
      }) as EventListener);
      source.onerror = () => {
        source?.close();
        if (!closed) {
          retry = setTimeout(() => {
            onReconnect?.(); // changes made while disconnected come with a fresh list
            open();
          }, 1500);
        }
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

export const assetFileUrl = (assetId: string) => `${apiBase}/assets/${encodeURIComponent(assetId)}/file`;

export const STATUS_LABELS: Record<PinState, string> = {
  note: '留言',
  queued: '排队中',
  running: '处理中',
  waiting: '等你确认',
  done: '已完成',
  failed: '没做完',
  resolved: '已解决',
};

/** The comment's state in one word: resolved wins, then the agent's progress, else a plain note. */
export function pinState(comment: Pick<CanvasComment, 'status' | 'agentStatus'>): PinState {
  if (comment.status === 'resolved') return 'resolved';
  return comment.agentStatus ?? 'note';
}

/** Handed to the agent and not finished yet. */
export function agentBusy(comment: Pick<CanvasComment, 'agentStatus'>): boolean {
  return comment.agentStatus === 'queued' || comment.agentStatus === 'running' || comment.agentStatus === 'waiting';
}

/** "@Agent" in the text hands it to the agent (same rule as the server). */
export const MENTION = /[@＠]\s*agent(?![a-z])/i;

/** "0:03" for a video moment. */
export function formatMoment(seconds: number): string {
  const whole = Math.max(0, seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole - minutes * 60;
  return `${minutes}:${rest < 10 ? '0' : ''}${rest.toFixed(1).replace(/\.0$/, '')}`;
}


/** "图片 3 第 2 版 · 0:02.4" — where a comment is pinned, in words. */
export function describeAnchor(anchor: CommentAnchor, titles: Record<string, string>): string {
  if (anchor.kind === 'canvas') return '画布空白处';
  const title = anchor.nodeId ? titles[anchor.nodeId] : undefined;
  const name = title ? `「${title}」` : '已删除的节点';
  if (anchor.kind === 'node') return name;
  const version = anchor.version ? ` 第 ${anchor.version} 版` : ' 画面上';
  const moment = anchor.time != null ? ` · ${formatMoment(anchor.time)}` : '';
  return `${name}${version}${moment}`;
}
