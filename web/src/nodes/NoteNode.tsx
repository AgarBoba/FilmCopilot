import { NodeResizer, Position } from '@xyflow/react';

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


export function NoteNode({ data }: NoteNodeProps) {
  const { draft, setDraft, flush } = useDebouncedDraft(data.content ?? data.prompt ?? '', data.onChange);
  return (
    <div className="media-node note-node">
      <NodeResizer minWidth={180} minHeight={120} onResizeEnd={(_, params) => data.onResize?.({ width: params.width, height: params.height })} />
      <NodeHandle type="source" position={Position.Right} id="source" />
      <div className="node-heading">
        <span className="node-kind">NOTE</span>
        <NodeTitle title={data.title} fallback="便签" onChange={data.onTitleChange} />
      </div>
      <textarea
        value={draft}
        aria-label="便签内容"
        style={{
          fontFamily: data.fontFamily,
          fontSize: data.fontSize,
        }}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={flush}
        onMouseDown={(event) => event.stopPropagation()}
      />
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
