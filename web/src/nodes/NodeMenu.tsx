import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { MoreIcon } from '../canvas/icons';


export interface NodeMenuItem {
  key: string;
  label: string;
  icon: ReactNode;
  onSelect: () => void;
  /** When set, the item is greyed out and this explains why (shown as a tooltip). */
  disabledReason?: string;
  /** Keyboard hint shown on the right, e.g. "⌘D". */
  shortcut?: string;
}

interface NodeMenuProps {
  items: NodeMenuItem[];
}


/**
 * "⋯" button in a node's title bar with a small dropdown of node actions.
 * The dropdown is rendered into `.canvas-page` (not inside the node), so it keeps
 * a fixed size at any zoom level and is never covered by neighbouring nodes.
 */
export function NodeMenu({ items }: NodeMenuProps) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; right: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    setPosition({ top: rect.bottom + 6, right: Math.max(8, window.innerWidth - rect.right) });
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    menuRef.current?.querySelector<HTMLButtonElement>('button:not([aria-disabled="true"])')?.focus();
    function close() {
      setOpen(false);
    }
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (!menuRef.current?.contains(target) && !buttonRef.current?.contains(target)) close();
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation();
        close();
        buttonRef.current?.focus();
      }
    }
    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown, true);
    // The menu is pinned to the screen, so any pan/zoom of the canvas closes it.
    document.addEventListener('wheel', close, { capture: true, passive: true });
    window.addEventListener('resize', close);
    window.addEventListener('blur', close);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown, true);
      document.removeEventListener('wheel', close, { capture: true });
      window.removeEventListener('resize', close);
      window.removeEventListener('blur', close);
    };
  }, [open]);

  const host = buttonRef.current?.closest('.canvas-page') ?? document.body;

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={`node-icon-button nodrag ${open ? 'is-open' : ''}`}
        aria-label="更多操作"
        aria-haspopup="menu"
        aria-expanded={open}
        data-tooltip={open ? undefined : '更多操作'}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((value) => !value);
        }}
      >
        <MoreIcon width={16} height={16} />
      </button>
      {open && createPortal(
        <div
          ref={menuRef}
          className="node-menu"
          role="menu"
          aria-label="节点操作"
          style={{ top: position?.top ?? -9999, right: position?.right ?? 0 }}
        >
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              aria-disabled={Boolean(item.disabledReason)}
              data-tooltip={item.disabledReason}
              data-tooltip-side="left"
              onClick={(event) => {
                event.stopPropagation();
                if (item.disabledReason) return;
                setOpen(false);
                item.onSelect();
              }}
            >
              <span className="node-menu-icon">{item.icon}</span>
              <span className="node-menu-label">{item.label}</span>
              {item.shortcut && <kbd className="node-menu-shortcut">{item.shortcut}</kbd>}
            </button>
          ))}
        </div>,
        host,
      )}
    </>
  );
}
