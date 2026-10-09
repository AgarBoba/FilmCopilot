import type { AgentEvent } from '../agent/agentApi';
import type { CanvasComment } from './commentApi';

/** One message in a comment thread: something the user wrote, or one round of the agent's work. */
export type ThreadItem =
  | { type: 'user'; key: string; text: string; time: string; toAgent: boolean }
  | {
    type: 'agent';
    key: string;
    runId: string;
    time: string;
    /** The latest thing the agent said in this round (streaming text included while live). */
    text: string;
    /** A confirmation still waiting for the user. */
    confirm: AgentEvent | null;
    /** Tool steps taken, for "看过程（N 步）". */
    steps: number;
    /** While working and silent: the step it is on. */
    current: string | null;
    live: boolean;
    finished: AgentEvent['status'] | null;
    errors: string[];
    undone: boolean;
  };

/**
 * The thread as the user sees it: the comment and its replies (from the comment itself), and
 * one message per agent round (from its conversation). The conversation's own user messages
 * are skipped: they repeat the replies, composed for the agent.
 */
export function buildThread(
  comment: Pick<CanvasComment, 'id' | 'text' | 'createdAt' | 'replies'>,
  events: AgentEvent[],
  streaming = '',
  pendingIds: Set<string | undefined> = new Set(),
): ThreadItem[] {
  const items: ThreadItem[] = [
    { type: 'user', key: `c-${comment.id}`, text: comment.text, time: comment.createdAt, toAgent: false },
    ...comment.replies.map((reply): ThreadItem => ({
      type: 'user', key: `r-${reply.id}`, text: reply.text, time: reply.createdAt, toAgent: reply.toAgent,
    })),
  ];
  const runs = new Map<string, Extract<ThreadItem, { type: 'agent' }>>();
  const undone = new Set<string>();
  let lastRun: string | null = null;
  for (const event of events) {
    if (event.kind === 'run_undone') {
      if (event.runId) undone.add(event.runId);
      continue;
    }
    if (!event.runId) continue;
    let run = runs.get(event.runId);
    if (!run) {
      run = {
        type: 'agent', key: `a-${event.runId}`, runId: event.runId, time: event.createdAt ?? '', text: '', confirm: null,
        steps: 0, current: null, live: true, finished: null, errors: [], undone: false,
      };
      runs.set(event.runId, run);
    }
    lastRun = event.runId;
    if (event.kind === 'user_message') continue;
    // The round starts after the message that started it.
    if (event.createdAt && run.time < event.createdAt && run.steps === 0 && !run.text) run.time = event.createdAt;
    switch (event.kind) {
      case 'assistant_text':
        run.text = event.text ?? '';
        break;
      case 'tool_step':
        run.steps += 1;
        run.current = event.summary ?? null;
        break;
      case 'confirm_request':
        if (pendingIds.has(event.requestId)) run.confirm = event;
        break;
      case 'error':
        if (event.message) run.errors.push(event.message);
        break;
      case 'run_finished':
        run.live = false;
        run.finished = event.status ?? 'completed';
        run.current = null;
        break;
      default:
        break;
    }
  }
  for (const run of runs.values()) {
    run.undone = undone.has(run.runId);
    if (run.runId === lastRun && run.live && streaming) run.text = streaming;
    items.push(run);
  }
  // Stable by time; the user's message goes first when a round starts the same second.
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => (a.item.time === b.item.time ? a.index - b.index : a.item.time < b.item.time ? -1 : 1))
    .map(({ item }) => item);
}

/** "刚刚", "5 分钟前", "3 小时前", "10/8". */
export function timeAgo(value: string | null | undefined, now = new Date()): string {
  if (!value) return '';
  const date = new Date(`${value.replace(' ', 'T')}${/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? '' : 'Z'}`);
  if (Number.isNaN(date.getTime())) return '';
  const seconds = (now.getTime() - date.getTime()) / 1000;
  if (seconds < 60) return '刚刚';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${date.getMonth() + 1}/${date.getDate()}`;
}
