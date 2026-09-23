import { describe, expect, it } from 'vitest';

import {
  createCanvasStore,
  snapshotToReactFlow,
} from '../state/canvasStore';
import { getVisibleEdgeIds } from '../edges/ReferenceEdge';
import type { CanvasEvent, CanvasSnapshot } from '../domain/types';


const snapshotAtRevision = (revision: number): CanvasSnapshot => ({
  canvasId: 'canvas-1',
  name: 'Test canvas',
  revision,
  nodes: [
    {
      id: 'image-1',
      nodeType: 'image',
      x: 100,
      y: 120,
      data: { title: 'Image', prompt: '' },
    },
    {
      id: 'video-1',
      nodeType: 'video',
      x: 420,
      y: 120,
      data: { title: 'Video', prompt: '' },
    },
  ],
  edges: [{ id: 'edge-1', source: 'image-1', target: 'video-1' }],
});


describe('canvas store', () => {
  it('maps a persisted node and edge to React Flow elements', () => {
    const result = snapshotToReactFlow(snapshotAtRevision(1));
    expect(result.nodes).toHaveLength(2);
    expect(result.edges[0].source).toBe('image-1');
    expect(result.edges[0].target).toBe('video-1');
  });

  it('applies an event and advances the revision once', () => {
    const store = createCanvasStore(snapshotAtRevision(1));
    const event: CanvasEvent = {
      id: 1,
      canvasId: 'canvas-1',
      revision: 2,
      eventType: 'canvas.create_node',
      payload: { revision: 2, command: 'create_node', payload: { nodeId: 'note-1' } },
    };
    store.getState().applyEvent(event);
    store.getState().applyEvent(event);
    expect(store.getState().snapshot?.revision).toBe(2);
  });

  it('preserves a multi-selection without redundant notifications', () => {
    const store = createCanvasStore(snapshotAtRevision(1));
    let notifications = 0;
    store.subscribe(() => {
      notifications += 1;
    });

    store.getState().selectNodes(['image-1', 'video-1']);
    store.getState().selectNodes(['video-1', 'image-1']);

    expect(notifications).toBe(1);
    expect(store.getState().selectedNodeIds).toEqual(['image-1', 'video-1']);
  });

  it('keeps edges for every selected node visible when connections are hidden', () => {
    const edges = [
      { id: 'e1', source: 'image-1', target: 'video-1' },
      { id: 'e2', source: 'image-2', target: 'video-2' },
      { id: 'e3', source: 'image-3', target: 'video-3' },
    ];

    expect(getVisibleEdgeIds(edges, ['image-1', 'video-2'], false)).toEqual(new Set(['e1', 'e2']));
  });
});
