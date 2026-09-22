import { Position } from '@xyflow/react';

import { NodeHandle } from './NodeHandles';


export interface NoteNodeData {
  title?: string;
  prompt?: string;
  content?: string;
  fontFamily?: string;
  fontSize?: number;
  onChange?: (content: string) => void;
  onStyleChange?: (changes: { fontFamily?: string; fontSize?: number }) => void;
  [key: string]: unknown;
}


interface NoteNodeProps {
  data: NoteNodeData;
}


export function NoteNode({ data }: NoteNodeProps) {
  return (
    <div className="media-node note-node">
      <NodeHandle type="target" position={Position.Left} id="target" />
      <NodeHandle type="source" position={Position.Right} id="source" />
      <div className="node-heading">
        <span className="node-kind">NOTE</span>
        <strong>{data.title ?? '便签'}</strong>
      </div>
      <textarea
        value={data.content ?? data.prompt ?? ''}
        aria-label="便签内容"
        style={{
          fontFamily: data.fontFamily,
          fontSize: data.fontSize,
        }}
        onChange={(event) => data.onChange?.(event.target.value)}
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
