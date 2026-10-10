import { describe, expect, it } from 'vitest';
import { fitCrop, moveCrop, resizeCrop } from '../nodes/cropGeometry';

describe('pixel crop geometry', () => {
  it('fits a centered square without enlarging', () => {
    expect(fitCrop({ width: 800, height: 600 }, 1)).toEqual({ x: 100, y: 0, width: 600, height: 600 });
  });
  it('clamps movement to image edges', () => {
    expect(moveCrop({ x: 100, y: 50, width: 200, height: 100 }, 900, -900, { width: 800, height: 600 }))
      .toEqual({ x: 600, y: 0, width: 200, height: 100 });
  });
  it('resizes free corners against the opposite corner', () => {
    expect(resizeCrop({ x: 100, y: 50, width: 200, height: 100 }, 'nw', -50, -30, { width: 800, height: 600 }, null))
      .toEqual({ x: 50, y: 20, width: 250, height: 130 });
  });
  it('keeps a locked ratio and stays inside the image', () => {
    const rect = resizeCrop({ x: 100, y: 50, width: 200, height: 200 }, 'se', 1000, 1000, { width: 800, height: 600 }, 1);
    expect(rect).toEqual({ x: 100, y: 50, width: 550, height: 550 });
  });
  it('never collapses to zero or reverses the dragged corner', () => {
    expect(resizeCrop({ x: 100, y: 50, width: 200, height: 100 }, 'e', -1000, 0, { width: 800, height: 600 }, null))
      .toEqual({ x: 100, y: 50, width: 1, height: 100 });
  });
});
