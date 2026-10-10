import type { AgentEvent, TokenUsage } from './agentApi';

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

/** Credits the agent's turns used for talking (generations are charged separately). */
export function turnCredits(events: AgentEvent[]): number {
  return events.reduce((sum, event) => sum + (event.kind === 'run_finished' ? event.credits ?? 0 : 0), 0);
}

/** Token usage summed over the turn's runs (null when none was reported). */
export function turnUsage(events: AgentEvent[]): TokenUsage | null {
  let total: TokenUsage | null = null;
  for (const event of events) {
    if (event.kind !== 'run_finished' || !event.usage) continue;
    total ??= { input: 0, cacheRead: 0, cacheWrite: 0, output: 0, requests: 0 };
    for (const key of ['input', 'cacheRead', 'cacheWrite', 'output', 'requests'] as const) total[key] += event.usage[key] ?? 0;
  }
  return total;
}

/** 91234 → "9.1万", 3000 → "3千", 512 → "512". */
function tokens(value: number): string {
  if (value >= 10_000) return `${Math.round(value / 1000) / 10}万`;
  if (value >= 1000) return `${Math.round(value / 100) / 10}千`;
  return String(value);
}

/** The cost breakdown under a turn's credits, e.g. "缓存命中 92%\n读缓存 9.1万 · 写缓存 3千 · 新输入 500 · 输出 400 · 调用 4 次". */
export function usageText(usage: TokenUsage): string {
  const read = usage.input + usage.cacheRead + usage.cacheWrite;
  const hit = read ? Math.round((usage.cacheRead / read) * 100) : 0;
  return `缓存命中 ${hit}%\n读缓存 ${tokens(usage.cacheRead)} · 写缓存 ${tokens(usage.cacheWrite)} · `
    + `新输入 ${tokens(usage.input)} · 输出 ${tokens(usage.output)} · 调用 ${usage.requests} 次`;
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
      return { used: event.contextTokens, limit: event.contextWindow || 1_000_000 };
    }
  }
  return null;
}
