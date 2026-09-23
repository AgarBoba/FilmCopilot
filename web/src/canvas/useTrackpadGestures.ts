import { useEffect } from 'react';
import type { RefObject } from 'react';
import type { ReactFlowInstance } from '@xyflow/react';


type ViewportApi = Pick<ReactFlowInstance, 'getViewport' | 'setViewport'>;

interface SafariGestureEvent extends UIEvent {
  scale: number;
  clientX: number;
  clientY: number;
}

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 4;


/**
 * Trackpad support that React Flow does not cover on its own.
 *
 * - Safari reports a pinch as `gesture*` events instead of a Ctrl+wheel, so
 *   without this the whole page zooms. We turn it into a canvas zoom around
 *   the fingers.
 * - Two-finger scrolling over a textarea that can scroll scrolls the text,
 *   instead of panning the canvas underneath it.
 */
export function useTrackpadGestures(
  containerRef: RefObject<HTMLElement | null>,
  flowRef: RefObject<ViewportApi | null>,
) {
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    let startZoom = 1;

    function onGestureStart(event: Event) {
      event.preventDefault();
      startZoom = flowRef.current?.getViewport().zoom ?? 1;
    }

    function onGestureChange(event: Event) {
      event.preventDefault();
      const flow = flowRef.current;
      if (!flow) return;
      const gesture = event as SafariGestureEvent;
      const { x, y, zoom } = flow.getViewport();
      const nextZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, startZoom * gesture.scale));
      const bounds = container!.getBoundingClientRect();
      // Keep the point under the fingers fixed while zooming.
      const px = gesture.clientX - bounds.left;
      const py = gesture.clientY - bounds.top;
      const ratio = nextZoom / zoom;
      void flow.setViewport({ x: px - (px - x) * ratio, y: py - (py - y) * ratio, zoom: nextZoom });
    }

    function onWheel(event: WheelEvent) {
      if (event.ctrlKey) return; // pinch-zoom always goes to the canvas
      const textarea = (event.target as Element | null)?.closest?.('textarea');
      if (!textarea) return;
      const canScroll = textarea.scrollHeight > textarea.clientHeight + 1;
      if (canScroll) event.stopPropagation(); // let the text scroll; don't pan the canvas
    }

    container.addEventListener('gesturestart', onGestureStart);
    container.addEventListener('gesturechange', onGestureChange);
    // Capture phase on the container runs before React Flow's own wheel handler below it.
    container.addEventListener('wheel', onWheel, { capture: true, passive: true });
    return () => {
      container.removeEventListener('gesturestart', onGestureStart);
      container.removeEventListener('gesturechange', onGestureChange);
      container.removeEventListener('wheel', onWheel, { capture: true });
    };
  }, [containerRef, flowRef]);
}

export const CANVAS_MIN_ZOOM = MIN_ZOOM;
export const CANVAS_MAX_ZOOM = MAX_ZOOM;
