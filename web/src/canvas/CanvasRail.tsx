import { useEffect, useRef, useState } from 'react';

import type { NodeType } from '../domain/types';
import { ImageIcon, NoteIcon, PlusIcon, UploadIcon, VideoIcon } from './icons';


const NODE_OPTIONS: { type: NodeType; label: string; hint: string; Icon: typeof ImageIcon }[] = [
  { type: 'image', label: '图片', hint: '生成或放置图片', Icon: ImageIcon },
  { type: 'video', label: '视频', hint: '生成或放置视频', Icon: VideoIcon },
  { type: 'note', label: '便签', hint: '记录想法或提示词', Icon: NoteIcon },
];

interface CanvasRailProps {
  onAddNode: (nodeType: NodeType) => void;
  onUpload: () => void;
}


/** Left-side rail: "+" opens the node menu; upload picks the node type from the file. */
export function CanvasRail({ onAddNode, onUpload }: CanvasRailProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const railRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    railRef.current?.querySelector<HTMLButtonElement>('.rail-menu button')?.focus();
    function onPointerDown(event: PointerEvent) {
      if (!railRef.current?.contains(event.target as Node)) setMenuOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setMenuOpen(false);
    }
    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown, true);
    };
  }, [menuOpen]);

  return (
    <div ref={railRef} className="canvas-rail" role="toolbar" aria-orientation="vertical" aria-label="添加内容">
      <button
        type="button"
        className={`rail-button rail-primary ${menuOpen ? 'is-open' : ''}`}
        aria-label="添加节点"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        data-tooltip="添加节点"
        data-tooltip-side="right"
        onClick={() => setMenuOpen((open) => !open)}
      >
        <PlusIcon width={20} height={20} />
      </button>
      <button
        type="button"
        className="rail-button"
        aria-label="上传图片或视频"
        data-tooltip="上传图片或视频，自动创建对应节点"
        data-tooltip-side="right"
        onClick={() => {
          setMenuOpen(false);
          onUpload();
        }}
      >
        <UploadIcon />
      </button>

      {menuOpen && (
        <div className="rail-menu" role="menu" aria-label="选择节点类型">
          {NODE_OPTIONS.map(({ type, label, hint, Icon }) => (
            <button
              key={type}
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                onAddNode(type);
              }}
            >
              <span className="rail-menu-icon"><Icon /></span>
              <span className="rail-menu-text">
                <span className="rail-menu-label">{label}</span>
                <span className="rail-menu-hint">{hint}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
