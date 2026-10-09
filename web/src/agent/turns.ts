import type { AgentEvent } from './agentApi';

export interface Turn {
  key: string;
  speaker: 'user' | 'agent';
  /** When the turn started. */
  time: string | null;
  /** agent: the model that answered, if the turn says. */
  model: string | null;
  items: { event: AgentEvent; index: number }[];
}

/**
 * The chat as alternating turns: each user message on its own (right side), and everything
 * the agent did in between (left side, under one avatar).
 */
export function groupTurns(events: AgentEvent[]): Turn[] {
  const turns: Turn[] = [];
  events.forEach((event, index) => {
    const speaker = event.kind === 'user_message' ? 'user' : 'agent';
    const last = turns[turns.length - 1];
    if (last && last.speaker === speaker && speaker === 'agent') {
      last.items.push({ event, index });
      last.model ??= event.model ?? null;
      return;
    }
    turns.push({
      key: `${speaker}-${event.id ?? `live-${index}`}`,
      speaker,
      time: event.createdAt ?? null,
      model: speaker === 'agent' ? event.model ?? null : null,
      items: [{ event, index }],
    });
  });
  return turns;
}

/** "10:32" today, "10/8" before. */
export function clock(value: string | null | undefined, now = new Date()): string {
  if (!value) return '';
  const date = new Date(`${value.replace(' ', 'T')}${/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? '' : 'Z'}`);
  if (Number.isNaN(date.getTime())) return '';
  if (date.toDateString() !== now.toDateString()) return `${date.getMonth() + 1}/${date.getDate()}`;
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

/** How full the context was on the last finished round, if the server said. */
export function contextUsage(events: AgentEvent[]): { used: number; limit: number } | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.kind === 'run_finished' && event.contextTokens) {
      return { used: event.contextTokens, limit: event.contextWindow || 200_000 };
    }
  }
  return null;
}
