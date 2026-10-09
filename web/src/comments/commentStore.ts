import { create } from 'zustand';

import { commentApi, type CanvasComment, type CommentAnchor } from './commentApi';

/** A pin being placed: where it goes and where on screen to show the input. */
export interface CommentDraft {
  anchor: CommentAnchor;
}

export interface CommentState {
  canvasId: string | null;
  comments: CanvasComment[];
  /** Comment mode: clicks on the canvas drop a pin instead of selecting. */
  mode: boolean;
  /** Pins are hidden on the canvas (the list in the panel still shows everything). */
  hidden: boolean;
  /** The comment whose popover is open. */
  openId: string | null;
  draft: CommentDraft | null;
  /** Bumped to ask the canvas to bring a comment's pin into view. */
  focusRequest: { id: string; seq: number } | null;
  error: string | null;
  load: (canvasId: string) => Promise<void>;
  upsert: (comment: CanvasComment) => void;
  setMode: (mode: boolean) => void;
  setHidden: (hidden: boolean) => void;
  open: (id: string | null) => void;
  focus: (id: string) => void;
  setDraft: (draft: CommentDraft | null) => void;
  create: (anchor: CommentAnchor, text: string, toAgent?: boolean) => Promise<CanvasComment | null>;
  reply: (id: string, text: string, toAgent?: boolean) => Promise<boolean>;
  handOff: (id: string) => Promise<void>;
  remove: (id: string) => Promise<boolean>;
  drop: (id: string) => void;
  resolve: (id: string) => Promise<void>;
  reopen: (id: string) => Promise<void>;
}

function message(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export const useCommentStore = create<CommentState>((set, get) => ({
  canvasId: null,
  comments: [],
  mode: false,
  hidden: false,
  openId: null,
  draft: null,
  focusRequest: null,
  error: null,

  async load(canvasId) {
    try {
      const { comments } = await commentApi.list(canvasId);
      set({ canvasId, comments });
    } catch (error) {
      set({ canvasId, error: message(error, '读取留言失败') });
    }
  },

  upsert(comment) {
    const comments = get().comments;
    const index = comments.findIndex((item) => item.id === comment.id);
    if (index === -1) {
      set({ comments: [...comments, comment] });
      return;
    }
    // Events can arrive out of order with a list refresh: keep the newer one.
    if (comments[index].updatedAt > comment.updatedAt) return;
    const next = comments.slice();
    next[index] = comment;
    set({ comments: next });
  },

  setMode(mode) {
    set(mode ? { mode } : { mode, draft: null });
  },
  setHidden: (hidden) => set({ hidden }),
  open: (id) => set({ openId: id, draft: null }),
  focus: (id) => set({ openId: id, draft: null, focusRequest: { id, seq: (get().focusRequest?.seq ?? 0) + 1 } }),
  setDraft: (draft) => set({ draft, openId: null }),

  async create(anchor, text, toAgent = false) {
    const canvasId = get().canvasId;
    if (!canvasId) return null;
    try {
      const comment = await commentApi.create(canvasId, anchor, text, toAgent);
      get().upsert(comment);
      set({ draft: null, openId: comment.id, error: null });
      return comment;
    } catch (error) {
      set({ error: message(error, '留言没发出去') });
      return null;
    }
  },

  async reply(id, text, toAgent = false) {
    try {
      get().upsert(await commentApi.reply(id, text, toAgent));
      set({ error: null });
      return true;
    } catch (error) {
      set({ error: message(error, '回复没发出去') });
      return false;
    }
  },

  async resolve(id) {
    try {
      get().upsert(await commentApi.resolve(id));
      if (get().openId === id) set({ openId: null });
    } catch (error) {
      set({ error: message(error, '操作失败') });
    }
  },

  async handOff(id) {
    try {
      get().upsert(await commentApi.handOff(id));
      set({ error: null });
    } catch (error) {
      set({ error: message(error, '没交给 Agent') });
    }
  },

  async remove(id) {
    try {
      await commentApi.remove(id);
      get().drop(id);
      return true;
    } catch (error) {
      set({ error: message(error, '删除失败') });
      return false;
    }
  },

  drop(id) {
    set((state) => ({
      comments: state.comments.filter((comment) => comment.id !== id),
      openId: state.openId === id ? null : state.openId,
    }));
  },

  async reopen(id) {
    try {
      get().upsert(await commentApi.reopen(id));
    } catch (error) {
      set({ error: message(error, '操作失败') });
    }
  },
}));

/** Not resolved yet: shown as pins and counted on the rail. */
export function openComments(comments: CanvasComment[]): CanvasComment[] {
  return comments.filter((comment) => comment.status !== 'resolved');
}

/** Place in the queue (1 = next), for queued comments. */
export function queuePosition(comments: CanvasComment[], id: string): number {
  const queued = comments
    .filter((comment) => comment.agentStatus === 'queued')
    .sort((a, b) => (a.updatedAt === b.updatedAt ? a.createdAt.localeCompare(b.createdAt) : a.updatedAt.localeCompare(b.updatedAt)));
  return queued.findIndex((comment) => comment.id === id) + 1;
}
