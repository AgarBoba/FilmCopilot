import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, api } from '../api/client';
import type { CanvasSnapshot, CommandEnvelope } from '../domain/types';
import { createCanvasStore } from '../state/canvasStore';


const snapshotAt = (revision: number): CanvasSnapshot => ({
  canvasId: 'canvas-1',
  name: 'Test',
  revision,
  nodes: [{ id: 'image-1', nodeType: 'image', x: 0, y: 0, data: { title: 'Image', prompt: '' } }],
  edges: [],
});

const typing = (prompt: string, baseRevision: number): CommandEnvelope => ({
  command: 'update_node',
  baseRevision,
  idempotencyKey: `type-${prompt}`,
  payload: { nodeId: 'image-1', data: { prompt } },
});

/** Fake server that enforces revisions like the real API. */
function fakeServer(startRevision: number) {
  let revision = startRevision;
  const sent: number[] = [];
  vi.spyOn(api, 'executeCommand').mockImplementation(async (_canvasId, envelope) => {
    sent.push(envelope.baseRevision);
    await new Promise((resolve) => setTimeout(resolve, 5));
    if (envelope.baseRevision !== revision) {
      throw new ApiError('REVISION_CONFLICT', `Expected revision ${envelope.baseRevision}, current revision is ${revision}`, 409);
    }
    revision += 1;
    return { revision, command: envelope.command, payload: {} };
  });
  vi.spyOn(api, 'getSnapshot').mockImplementation(async () => snapshotAt(revision));
  return { sent, bump: () => { revision += 1; } };
}

afterEach(() => vi.restoreAllMocks());


describe('command queue', () => {
  it('saves rapid edits in order without revision conflicts', async () => {
    const server = fakeServer(308);
    const store = createCanvasStore(snapshotAt(308));
    store.setState({ canvasId: 'canvas-1' });

    // Three keystrokes fired before any save returns, all computed from revision 308.
    await Promise.all(['s', 'sh', 'she'].map((text) => store.getState().execute(typing(text, 308))));

    expect(server.sent).toEqual([308, 309, 310]);
    expect(store.getState().error).toBeNull();
    expect(store.getState().snapshot?.revision).toBe(311);
  });

  it('refreshes and retries once when another writer moved the revision', async () => {
    const server = fakeServer(5);
    const store = createCanvasStore(snapshotAt(5));
    store.setState({ canvasId: 'canvas-1' });
    server.bump(); // e.g. the Agent API saved something meanwhile

    await store.getState().execute(typing('x', 5));

    expect(server.sent).toEqual([5, 6]);
    expect(store.getState().error).toBeNull();
  });
});
