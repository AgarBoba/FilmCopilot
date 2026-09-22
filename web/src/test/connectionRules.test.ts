import { describe, expect, it } from 'vitest';

import { canConnect, wouldCreateCycle } from '../domain/connectionRules';
import type { CanvasEdge } from '../domain/types';


describe('canvas connection rules', () => {
  it('allows supported media references', () => {
    expect(canConnect('image', 'image')).toBe(true);
    expect(canConnect('image', 'video')).toBe(true);
    expect(canConnect('video', 'video')).toBe(true);
  });

  it('rejects unsupported media and note connections', () => {
    expect(canConnect('video', 'image')).toBe(false);
    expect(canConnect('note', 'image')).toBe(false);
    expect(canConnect('image', 'note')).toBe(false);
  });

  it('detects a cycle in directed reference edges', () => {
    const edges: CanvasEdge[] = [
      { id: 'e1', source: 'image-1', target: 'video-1' },
      { id: 'e2', source: 'video-1', target: 'video-2' },
    ];
    expect(wouldCreateCycle(edges, 'video-2', 'image-1')).toBe(true);
    expect(wouldCreateCycle(edges, 'video-2', 'image-3')).toBe(false);
  });
});
