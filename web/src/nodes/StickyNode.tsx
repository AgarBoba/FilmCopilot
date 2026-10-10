import { useEffect, useRef, useState } from 'react';
import { NodeResizeControl, NodeToolbar, Position } from '@xyflow/react';

import { MoreIcon } from '../canvas/icons';
import { CommentBadge, type NodeCommentSummary } from './CommentBadge';
import { useDebouncedDraft } from './useDebouncedDraft';

export const STICKY_COLORS = [
  { id: 'yellow', label: '黄', hex: '#F6D86B' },
  { id: 'pink', label: '粉', hex: '#F2B8C6' },
  { id: 'blue', label: '蓝', hex: '#A9CDF2' },
  { id: 'green', label: '绿', hex: '#B5DDA8' },
  { id: 'purple', label: '紫', hex: '#CDBFF4' },
  { id: 'gray', label: '灰', hex: '#D6D8DE' },
] as const;
export type StickyColor = (typeof STICKY_COLORS)[number]['id'];

const SIZES = [
  { id: 's', label: '小' },
  { id: 'm', label: '中' },
  { id: 'l', label: '大' },
] as const;
export type StickyTextSize = (typeof SIZES)[number]['id'];

export const STICKY_MIN = 120;
const COLOR_KEY = 'film-copilot.sticky-color';

/** The colour a new sticky gets: the one picked last (yellow the first time). */
export function lastStickyColor(): StickyColor {
  try {
    const saved = window.localStorage.getItem(COLOR_KEY);
    if (STICKY_COLORS.some((color) => color.id === saved)) return saved as StickyColor;
  } catch {
    // storage unavailable: the default is fine
  }
  return 'yellow';
}

function rememberColor(color: StickyColor) {
  try {
    window.localStorage.setItem(COLOR_KEY, color);
  } catch {
    // not remembered; harmless
  }
}

/** A new sticky opens straight into typing; the canvas asks for it by id before the node exists. */
let editOnMount: string | null = null;
export function editStickyWhenItAppears(nodeId: string) {
  editOnMount = nodeId;
}

/** A sticky's name is its first non-empty line (shown bold). */
export function stickyTitle(text: string): string {
  return text.split('\n').map((line) => line.trim()).find(Boolean)?.slice(0, 40) || '便签';
}

export interface StickyNodeData {
  content?: string;
  color?: StickyColor;
  textSize?: StickyTextSize;
  comments?: NodeCommentSummary;
  onOpenComments?: () => void;
  onChange?: (content: string) => void;
  onStickyChange?: (changes: { content?: string; title?: string; color?: StickyColor; textSize?: StickyTextSize }) => void;
  onResize?: (size: { width: number; height: number }) => void;
  onDuplicate?: () => void;
  onDelete?: () => void;
  [key: string]: unknown;
}

interface StickyNodeProps {
  id: string;
  data: StickyNodeData;
  selected?: boolean;
}

/**
 * 便签: a coloured paper label for an area of the canvas. No ports, no title bar, never part
 * of a generation. Double-click to type; the first line is the bold name. Selected, a small
 * toolbar above it changes the colour and text size; the four corners resize it.
 */
export function StickyNode({ id, data, selected = false }: StickyNodeProps) {
  const save = (content: string) => data.onStickyChange?.({ content, title: stickyTitle(content) });
  const { draft, setDraft, flush } = useDebouncedDraft(data.content ?? '', save);
  const [editing, setEditing] = useState(false);
  const [menu, setMenu] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const color = STICKY_COLORS.find((item) => item.id === data.color) ?? STICKY_COLORS[0];
  const size = SIZES.some((item) => item.id === data.textSize) ? data.textSize! : 'm';

  useEffect(() => {
    if (editOnMount === id) {
      editOnMount = null;
      setEditing(true);
    }
  }, [id]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!editing || !textarea) return;
    textarea.focus({ preventScroll: true });
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  }, [editing]);

  useEffect(() => {
    if (!selected) setMenu(false);
  }, [selected]);

  const [first, ...rest] = draft.replace(/^(\s*\n)+/, '').split('\n');
  const corners = ['top-left', 'top-right', 'bottom-left', 'bottom-right'] as const;

  return (
    <div className={`sticky-node is-${size} ${editing ? 'is-editing' : ''}`} style={{ background: color.hex }}>
      {corners.map((corner) => (
        <NodeResizeControl
          key={corner}
          className={`sticky-resize is-${corner} nodrag`}
          position={corner}
          minWidth={STICKY_MIN}
          minHeight={STICKY_MIN}
          onResizeEnd={(_, params) => data.onResize?.({ width: params.width, height: params.height })}
        />
      ))}
      <NodeToolbar isVisible={selected && !editing} position={Position.Top} offset={12} className="sticky-toolbar nodrag">
        <div className="sticky-swatches" role="radiogroup" aria-label="颜色">
          {STICKY_COLORS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={item.id === color.id}
              aria-label={`颜色：${item.label}`}
              data-tooltip={item.label}
              className={`sticky-swatch ${item.id === color.id ? 'is-current' : ''}`}
              style={{ background: item.hex }}
              onClick={() => {
                rememberColor(item.id);
                data.onStickyChange?.({ color: item.id });
              }}
            />
          ))}
        </div>
        <span className="sticky-toolbar-divider" aria-hidden="true" />
        <div className="sticky-sizes" role="radiogroup" aria-label="字号">
          {SIZES.map((item) => (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={item.id === size}
              aria-label={`字号：${item.label}`}
              className={`sticky-size ${item.id === size ? 'is-current' : ''}`}
              onClick={() => data.onStickyChange?.({ textSize: item.id })}
            >
              {item.label}
            </button>
          ))}
        </div>
        <span className="sticky-toolbar-divider" aria-hidden="true" />
        <span className="sticky-more">
          <button type="button" className="sticky-tool" aria-label="更多" aria-expanded={menu} data-tooltip="更多"
            onClick={() => setMenu(!menu)}>
            <MoreIcon width={16} height={16} />
          </button>
          {menu && (
            <span className="sticky-menu" role="menu">
              <button type="button" role="menuitem" onClick={() => { setMenu(false); data.onDuplicate?.(); }}>
                复制<kbd>⌘D</kbd>
              </button>
              <button type="button" role="menuitem" className="is-danger" onClick={() => { setMenu(false); data.onDelete?.(); }}>
                删除<kbd>⌫</kbd>
              </button>
            </span>
          )}
        </span>
      </NodeToolbar>
      <CommentBadge summary={data.comments} onOpen={data.onOpenComments} />
      {editing ? (
        <textarea
          ref={textareaRef}
          className="sticky-input nodrag nowheel"
          value={draft}
          aria-label="便签内容"
          placeholder="第一行是区域名"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => {
            flush();
            setEditing(false);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') event.currentTarget.blur();
            event.stopPropagation();
          }}
          onMouseDown={(event) => event.stopPropagation()}
        />
      ) : (
        <div
          className={`sticky-text nowheel ${draft.trim() ? '' : 'is-empty'}`}
          role="button"
          tabIndex={0}
          aria-label="便签内容，双击编辑"
          onDoubleClick={() => setEditing(true)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              setEditing(true);
            }
          }}
        >
          {draft.trim() ? (
            <>
              <span className="sticky-title">{first}</span>
              {rest.length > 0 && <span className="sticky-body">{rest.join('\n')}</span>}
            </>
          ) : '双击写字'}
        </div>
      )}
    </div>
  );
}
