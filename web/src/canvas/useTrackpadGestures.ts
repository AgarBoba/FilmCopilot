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
 * - A pinch must never zoom the page itself (the rail, the toolbar and the agent panel
 *   would all grow). Chrome reports a pinch as Ctrl+wheel; when React Flow doesn't take it
 *   (over a comment popover, a pin, a `nowheel` area, the agent panel) the browser would.
 *   So any pinch React Flow left alone is stopped here: over the canvas area it zooms the
 *   canvas, over the agent panel it does nothing.
 * - Safari reports a pinch as `gesture*` events instead; same rule.
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
    let gestureOnCanvas = false;

    /** Over the canvas area (pins, popovers and floating chrome included), not the panel. */
    function overCanvas(target: EventTarget | null) {
      const element = target instanceof Element ? target : null;
      return Boolean(element && container!.contains(element) && !element.closest('.agent-panel'));
    }

    function zoomAround(clientX: number, clientY: number, nextZoom: number) {
      const flow = flowRef.current;
      if (!flow) return;
      const { x, y, zoom } = flow.getViewport();
      const clamped = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, nextZoom));
      const bounds = container!.getBoundingClientRect();
      // Keep the point under the fingers fixed while zooming.
      const px = clientX - bounds.left;
      const py = clientY - bounds.top;
      const ratio = clamped / zoom;
      void flow.setViewport({ x: px - (px - x) * ratio, y: py - (py - y) * ratio, zoom: clamped });
    }

    function onGestureStart(event: Event) {
      event.preventDefault();
      gestureOnCanvas = overCanvas(event.target);
      startZoom = flowRef.current?.getViewport().zoom ?? 1;
    }

    function onGestureChange(event: Event) {
      event.preventDefault();
      if (!gestureOnCanvas) return;
      const gesture = event as SafariGestureEvent;
      zoomAround(gesture.clientX, gesture.clientY, startZoom * gesture.scale);
    }

    function onWheel(event: WheelEvent) {
      if (event.ctrlKey) return; // pinch-zoom always goes to the canvas
      const textarea = (event.target as Element | null)?.closest?.('textarea');
      if (!textarea) return;
      const canScroll = textarea.scrollHeight > textarea.clientHeight + 1;
      if (canScroll) event.stopPropagation(); // let the text scroll; don't pan the canvas
    }

    /** Runs last (window, bubbling): a pinch nobody handled would zoom the whole page. */
    function onUnhandledPinch(event: WheelEvent) {
      if (!event.ctrlKey || event.defaultPrevented) return;
      event.preventDefault();
      if (!overCanvas(event.target)) return;
      const zoom = flowRef.current?.getViewport().zoom ?? 1;
      // Same feel as React Flow's own pinch: proportional to the scroll amount.
      const delta = event.deltaMode === 1 ? event.deltaY * 0.05 : event.deltaMode ? event.deltaY : event.deltaY * 0.002;
      zoomAround(event.clientX, event.clientY, zoom * Math.pow(2, -delta * 10));
    }

    window.addEventListener('gesturestart', onGestureStart);
    window.addEventListener('gesturechange', onGestureChange);
    window.addEventListener('wheel', onUnhandledPinch, { passive: false });
    // Capture phase on the container runs before React Flow's own wheel handler below it.
    container.addEventListener('wheel', onWheel, { capture: true, passive: true });
    return () => {
      window.removeEventListener('gesturestart', onGestureStart);
      window.removeEventListener('gesturechange', onGestureChange);
      window.removeEventListener('wheel', onUnhandledPinch);
      container.removeEventListener('wheel', onWheel, { capture: true });
    };
  }, [containerRef, flowRef]);
}

export const CANVAS_MIN_ZOOM = MIN_ZOOM;
export const CANVAS_MAX_ZOOM = MAX_ZOOM;
