import type { CanvasEdge, NodeType } from './types';

const allowedConnections = new Set<string>([
  'image:image',
  'image:video',
  'video:video',
  // A note's text is added to the downstream node's prompt. Notes have no input port.
  'note:image',
  'note:video',
]);

export function canConnect(source: NodeType, target: NodeType): boolean {
  return allowedConnections.has(`${source}:${target}`);
}

export function wouldCreateCycle(
  edges: readonly CanvasEdge[],
  sourceId: string,
  targetId: string,
): boolean {
  if (sourceId === targetId) {
    return true;
  }

  const adjacency = new Map<string, string[]>();
  for (const edge of edges) {
    const targets = adjacency.get(edge.source) ?? [];
    targets.push(edge.target);
    adjacency.set(edge.source, targets);
  }

  const pending = [targetId];
  const visited = new Set<string>();
  while (pending.length > 0) {
    const nodeId = pending.shift();
    if (!nodeId) {
      continue;
    }
    if (nodeId === sourceId) {
      return true;
    }
    if (visited.has(nodeId)) {
      continue;
    }
    visited.add(nodeId);
    pending.push(...(adjacency.get(nodeId) ?? []));
  }

  return false;
}
