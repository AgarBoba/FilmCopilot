import { useEffect, useRef, useState } from 'react';
import { NodeResizeControl, Position } from '@xyflow/react';

import { Markdown } from '../agent/Markdown';
import { NodeHandle } from './NodeHandles';
import { NodeTitle } from './NodeTitle';
import { useDebouncedDraft } from './useDebouncedDraft';


export interface NoteNodeData {
  title?: string;
  onTitleChange?: (title: string) => void;
  prompt?: string;
  content?: string;
  fontFamily?: string;
  fontSize?: number;
  onChange?: (content: string) => void;
  onStyleChange?: (changes: { fontFamily?: string; fontSize?: number }) => void;
  onResize?: (size: { width: number; height: number }) => void;
  [key: string]: unknown;
}


interface NoteNodeProps {
  data: NoteNodeData;
}


/**
 * Note text is Markdown. Not editing: rendered (headings, lists, tables). Double-click the
 * text (or press Enter when the note is focused) to edit the source; click outside to finish.
 */
export function NoteNode({ data }: NoteNodeProps) {
  const { draft, setDraft, flush } = useDebouncedDraft(data.content ?? data.prompt ?? '', data.onChange);
  const [editing, setEditing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef(0);

  // Switching to the editor keeps the text where it was: same box, same scroll position.
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!editing || !textarea) return;
    textarea.focus({ preventScroll: true });
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    textarea.scrollTop = scrollRef.current;
  }, [editing]);

  function startEditing() {
    scrollRef.current = previewRef.current?.scrollTop ?? 0;
    setEditing(true);
  }

  const style = { fontFamily: data.fontFamily, fontSize: data.fontSize };

  return (
    <div className="media-node note-node">
      {/* Resize from the bottom-right corner only; the grip shows on hover or when selected. */}
      <NodeResizeControl
        className="note-resize nodrag"
        position="bottom-right"
        minWidth={240}
        minHeight={180}
        onResizeEnd={(_, params) => data.onResize?.({ width: params.width, height: params.height })}
      >
        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
          <path d="M13 4v4.5A4.5 4.5 0 0 1 8.5 13H4" />
        </svg>
      </NodeResizeControl>
      <NodeHandle type="source" position={Position.Right} id="source" />
      <div className="node-heading">
        <span className="node-kind">NOTE</span>
        <NodeTitle title={data.title} fallback="便签" onChange={data.onTitleChange} />
      </div>
      {editing ? (
        <textarea
          ref={textareaRef}
          className="nodrag nowheel"
          value={draft}
          aria-label="便签内容"
          placeholder="支持 Markdown：# 标题、- 列表、| 表格 |"
          style={style}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => {
            flush();
            setEditing(false);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') event.currentTarget.blur();
          }}
          onMouseDown={(event) => event.stopPropagation()}
        />
      ) : (
        <div
          ref={previewRef}
          className={`note-preview nowheel ${draft.trim() ? '' : 'is-empty'}`}
          style={style}
          role="button"
          tabIndex={0}
          aria-label="便签内容，双击编辑"
          data-tooltip={draft.trim() ? '双击编辑' : undefined}
          onDoubleClick={startEditing}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              startEditing();
            }
          }}
        >
          {draft.trim() ? <Markdown text={draft} /> : '双击输入文字'}
        </div>
      )}
      <div className="note-controls">
        <select
          aria-label="字体"
          value={data.fontFamily ?? 'Inter'}
          onChange={(event) => data.onStyleChange?.({ fontFamily: event.target.value })}
        >
          <option>Inter</option>
          <option>Georgia</option>
          <option>Menlo</option>
        </select>
        <select
          aria-label="字号"
          value={String(data.fontSize ?? 16)}
          onChange={(event) => data.onStyleChange?.({ fontSize: Number(event.target.value) })}
        >
          <option value="14">14</option>
          <option value="16">16</option>
          <option value="20">20</option>
          <option value="28">28</option>
        </select>
      </div>
    </div>
  );
}
