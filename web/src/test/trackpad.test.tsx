import { render } from '@testing-library/react';
import { useRef } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { useTrackpadGestures } from '../canvas/useTrackpadGestures';


function Harness({ flow }: { flow: { getViewport: () => { x: number; y: number; zoom: number }; setViewport: (v: unknown) => void } }) {
  const ref = useRef<HTMLDivElement>(null);
  const flowRef = useRef(flow as never);
  useTrackpadGestures(ref, flowRef);
  return (
    <div className="canvas-page">
      <div ref={ref} data-testid="canvas">
        <div className="comment-popover" data-testid="popover">小窗</div>
        <div className="react-flow__node"><div className="sticky-text nowheel" data-testid="sticky">便签</div></div>
      </div>
      <aside className="agent-panel" data-testid="panel">面板</aside>
    </div>
  );
}

function pinch(target: Element) {
  const event = new WheelEvent('wheel', { ctrlKey: true, deltaY: -10, clientX: 50, clientY: 50, bubbles: true, cancelable: true });
  target.dispatchEvent(event);
  return event;
}

describe('pinch zoom', () => {
  it('never zooms the page: over a popover it zooms the canvas, over the panel nothing', () => {
    const setViewport = vi.fn();
    const { getByTestId } = render(<Harness flow={{ getViewport: () => ({ x: 0, y: 0, zoom: 1 }), setViewport }} />);

    expect(pinch(getByTestId('popover')).defaultPrevented).toBe(true);
    expect(setViewport).toHaveBeenCalledTimes(1);
    expect(setViewport.mock.calls[0][0].zoom).toBeGreaterThan(1);

    expect(pinch(getByTestId('panel')).defaultPrevented).toBe(true);
    expect(setViewport).toHaveBeenCalledTimes(1);

    // A plain two-finger scroll is left alone.
    const scroll = new WheelEvent('wheel', { deltaY: 10, bubbles: true, cancelable: true });
    getByTestId('panel').dispatchEvent(scroll);
    expect(scroll.defaultPrevented).toBe(false);
  });

  it('over a text node or sticky (nowheel text) a pinch still zooms the canvas, once', () => {
    const setViewport = vi.fn();
    const { getByTestId } = render(<Harness flow={{ getViewport: () => ({ x: 0, y: 0, zoom: 1 }), setViewport }} />);
    // Something below marking it handled (as React Flow does) must not swallow the zoom.
    const swallow = (event: Event) => event.preventDefault();
    getByTestId('sticky').addEventListener('wheel', swallow);
    expect(pinch(getByTestId('sticky')).defaultPrevented).toBe(true);
    expect(setViewport).toHaveBeenCalledTimes(1);
    expect(setViewport.mock.calls[0][0].zoom).toBeGreaterThan(1);
  });
});
