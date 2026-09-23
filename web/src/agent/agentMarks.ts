import type { AgentEvent } from './agentApi';

/**
 * How a node relates to the agent right now:
 * - pending: a step on it is waiting for your confirmation
 * - working: the running turn has looked at or changed it
 * - recent:  the turn that just ended touched it (shown briefly, then fades)
 */
export type AgentMark = 'pending' | 'working' | 'recent';

export function agentNodeMarks(
  events: AgentEvent[],
  activeRunId: string | null,
  recentRunId: string | null,
): Map<string, AgentMark> {
  const marks = new Map<string, AgentMark>();
  const resolved = new Set(events.filter((e) => e.kind === 'confirm_resolved').map((e) => e.requestId));
  for (const event of events) {
    if (event.kind !== 'tool_step' || event.isError) continue;
    if (event.runId && event.runId === activeRunId) {
      (event.touched ?? []).forEach((id) => marks.set(id, 'working'));
    } else if (event.runId && event.runId === recentRunId) {
      (event.touched ?? []).forEach((id) => marks.set(id, 'recent'));
    }
  }
  for (const event of events) {
    if (event.kind === 'confirm_request' && event.runId === activeRunId && !resolved.has(event.requestId)) {
      (event.touched ?? []).forEach((id) => marks.set(id, 'pending'));
    }
  }
  return marks;
}
