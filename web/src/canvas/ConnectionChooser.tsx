import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import type { NodeType } from '../domain/types';


export type ChooserNodeType = Extract<NodeType, 'image' | 'video'>;

const LABELS: Record<ChooserNodeType, string> = {
  image: '图片节点',
  video: '视频节点',
};

interface ConnectionChooserProps {
  /** Screen (client) coordinates where the connection was dropped. */
  position: { x: number; y: number };
  options: ChooserNodeType[];
  onCreate: (nodeType: ChooserNodeType) => void;
  onClose: () => void;
}


export function ConnectionChooser({ position, options, onCreate, onClose }: ConnectionChooserProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState(position);

  // Keep the menu inside the window when the drop point is near an edge.
  useLayoutEffect(() => {
    const menu = menuRef.current;
    if (!menu) return;
    const margin = 8;
    const { width, height } = menu.getBoundingClientRect();
    setPlacement({
      x: Math.max(margin, Math.min(position.x, window.innerWidth - width - margin)),
      y: Math.max(margin, Math.min(position.y, window.innerHeight - height - margin)),
    });
  }, [position.x, position.y]);

  useEffect(() => {
    menuRef.current?.querySelector('button')?.focus();

    function onPointerDown(event: PointerEvent) {
      if (!menuRef.current?.contains(event.target as Node)) onClose();
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
    }
    function onBlur() {
      onClose();
    }
    // Capture phase so React Flow cannot swallow the event before we see it.
    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown, true);
    window.addEventListener('blur', onBlur);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown, true);
      window.removeEventListener('blur', onBlur);
    };
  }, [onClose]);

  return (
    <div
      ref={menuRef}
      className="connection-chooser"
      style={{ left: placement.x, top: placement.y }}
      role="menu"
      aria-label="选择新节点类型"
    >
      {options.map((nodeType) => (
        <button key={nodeType} type="button" role="menuitem" onClick={() => onCreate(nodeType)}>
          {LABELS[nodeType]}
        </button>
      ))}
    </div>
  );
}
