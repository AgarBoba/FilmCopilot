import { useEffect, useLayoutEffect, useRef, useState } from 'react';


/**
 * One shared tooltip for the whole canvas.
 *
 * Any element with `data-tooltip="说明"` gets a bubble on hover (after a short
 * delay) or keyboard focus. Optional attributes:
 *   data-tooltip-shortcut="V"            shows a key hint
 *   data-tooltip-side="top|bottom|left|right"   preferred side (default top)
 *
 * Mounted once inside `.canvas-page` so it inherits the theme colours.
 * See docs/DESIGN.md → Tooltip.
 */

type Side = 'top' | 'bottom' | 'left' | 'right';

interface TooltipState {
  text: string;
  shortcut?: string;
  side: Side;
  anchor: DOMRect;
}

const SHOW_DELAY = 350;
/** After one tooltip has shown, neighbours show instantly for this long. */
const WARM_WINDOW = 600;
const GAP = 8;
const MARGIN = 8;
const SIDES: Side[] = ['top', 'bottom', 'left', 'right'];

function readTooltip(element: Element): Omit<TooltipState, 'anchor'> | null {
  const text = element.getAttribute('data-tooltip');
  if (!text) return null;
  const side = element.getAttribute('data-tooltip-side') as Side | null;
  return {
    text,
    shortcut: element.getAttribute('data-tooltip-shortcut') ?? undefined,
    side: side && SIDES.includes(side) ? side : 'top',
  };
}

function place(anchor: DOMRect, size: { width: number; height: number }, side: Side) {
  const positions: Record<Side, { x: number; y: number }> = {
    top: { x: anchor.left + anchor.width / 2 - size.width / 2, y: anchor.top - GAP - size.height },
    bottom: { x: anchor.left + anchor.width / 2 - size.width / 2, y: anchor.bottom + GAP },
    left: { x: anchor.left - GAP - size.width, y: anchor.top + anchor.height / 2 - size.height / 2 },
    right: { x: anchor.right + GAP, y: anchor.top + anchor.height / 2 - size.height / 2 },
  };
  const opposite: Record<Side, Side> = { top: 'bottom', bottom: 'top', left: 'right', right: 'left' };
  const fits = (point: { x: number; y: number }) => (
    point.x >= MARGIN && point.y >= MARGIN
    && point.x + size.width <= window.innerWidth - MARGIN
    && point.y + size.height <= window.innerHeight - MARGIN
  );
  const chosen = fits(positions[side]) ? side : fits(positions[opposite[side]]) ? opposite[side] : side;
  const point = positions[chosen];
  return {
    side: chosen,
    x: Math.min(Math.max(point.x, MARGIN), window.innerWidth - size.width - MARGIN),
    y: Math.min(Math.max(point.y, MARGIN), window.innerHeight - size.height - MARGIN),
  };
}


export function TooltipLayer() {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const [position, setPosition] = useState<{ x: number; y: number; side: Side } | null>(null);
  const bubbleRef = useRef<HTMLDivElement>(null);
  const targetRef = useRef<Element | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastHiddenRef = useRef(0);

  useEffect(() => {
    function clearTimer() {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    function hide() {
      clearTimer();
      if (targetRef.current) lastHiddenRef.current = Date.now();
      targetRef.current = null;
      setTooltip(null);
      setPosition(null);
    }
    function show(element: Element, immediate: boolean) {
      const content = readTooltip(element);
      if (!content) return;
      clearTimer();
      targetRef.current = element;
      const open = () => {
        if (targetRef.current !== element || !element.isConnected) return;
        setTooltip({ ...content, anchor: element.getBoundingClientRect() });
      };
      const warm = Date.now() - lastHiddenRef.current < WARM_WINDOW;
      if (immediate || warm) open();
      else timerRef.current = setTimeout(open, SHOW_DELAY);
    }

    function onPointerOver(event: PointerEvent) {
      if (event.pointerType === 'touch' || event.buttons) return;
      const element = (event.target as Element | null)?.closest?.('[data-tooltip]');
      if (!element) {
        if (targetRef.current) hide();
        return;
      }
      if (element !== targetRef.current) show(element, false);
    }
    function onPointerOut(event: PointerEvent) {
      const current = targetRef.current;
      if (!current) return;
      const next = event.relatedTarget as Node | null;
      if (!next || !current.contains(next)) hide();
    }
    function onFocusIn(event: FocusEvent) {
      const target = event.target as Element | null;
      if (!target?.matches?.(':focus-visible')) return;
      const element = target.closest('[data-tooltip]');
      if (element) show(element, true);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') hide();
    }

    document.addEventListener('pointerover', onPointerOver);
    document.addEventListener('pointerout', onPointerOut);
    document.addEventListener('focusin', onFocusIn);
    document.addEventListener('focusout', hide);
    // Anything that moves or changes the canvas makes a tooltip stale.
    document.addEventListener('pointerdown', hide, true);
    document.addEventListener('wheel', hide, { capture: true, passive: true });
    document.addEventListener('keydown', onKeyDown, true);
    window.addEventListener('blur', hide);
    window.addEventListener('resize', hide);
    return () => {
      clearTimer();
      document.removeEventListener('pointerover', onPointerOver);
      document.removeEventListener('pointerout', onPointerOut);
      document.removeEventListener('focusin', onFocusIn);
      document.removeEventListener('focusout', hide);
      document.removeEventListener('pointerdown', hide, true);
      document.removeEventListener('wheel', hide, { capture: true });
      document.removeEventListener('keydown', onKeyDown, true);
      window.removeEventListener('blur', hide);
      window.removeEventListener('resize', hide);
    };
  }, []);

  useLayoutEffect(() => {
    const bubble = bubbleRef.current;
    if (!tooltip || !bubble) return;
    const { width, height } = bubble.getBoundingClientRect();
    setPosition(place(tooltip.anchor, { width, height }, tooltip.side));
  }, [tooltip]);

  if (!tooltip) return null;
  return (
    <div
      ref={bubbleRef}
      className={`canvas-tooltip side-${position?.side ?? tooltip.side}`}
      role="tooltip"
      style={{
        left: position?.x ?? -9999,
        top: position?.y ?? -9999,
        visibility: position ? 'visible' : 'hidden',
      }}
    >
      <span>{tooltip.text}</span>
      {tooltip.shortcut && <kbd>{tooltip.shortcut}</kbd>}
    </div>
  );
}
