import { useState, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { CheckIcon, NoteAddIcon } from '../canvas/icons';

interface MarkdownProps {
  text: string;
  className?: string;
  /**
   * Agent replies only. Special blocks — tables, code blocks, ```prompt blocks, quotes and
   * ```note cards — get a "存成便签" button that saves just that block.
   */
  onSaveNote?: (content: string, title: string) => void;
}

type BlockKind = 'table' | 'code' | 'prompt' | 'quote' | 'note';

const KIND_FALLBACK: Record<BlockKind, string> = {
  table: '表格', code: '代码', prompt: '提示词', quote: '摘录', note: '便签',
};

// hast nodes carry the source position of the markdown they came from.
interface Positioned { position?: { start: { offset?: number }; end: { offset?: number } } }

function TableFrame({ children }: { children?: ReactNode }) {
  return (
    <div className="markdown-table nowheel">
      <table>{children}</table>
    </div>
  );
}
const tableComponent: Components['table'] = ({ children }) => <TableFrame>{children}</TableFrame>;


/**
 * Renders agent replies and note text: headings, lists, tables (GFM), code, quotes.
 * Raw HTML in the text is shown as text, never executed. Wide tables scroll sideways.
 */
export function Markdown({ text, className, onSaveNote }: MarkdownProps) {
  const labels = onSaveNote ? sectionLabels(text) : [];

  const savable = (kind: BlockKind, node: Positioned | undefined, content: string, body: ReactNode) => {
    if (!onSaveNote) return body;
    const title = titleAt(labels, node?.position?.start.offset ?? 0) || KIND_FALLBACK[kind];
    return <SavableBlock kind={kind} title={title} content={content} onSave={onSaveNote}>{body}</SavableBlock>;
  };
  const source = (node: Positioned | undefined) => {
    const start = node?.position?.start.offset;
    const end = node?.position?.end.offset;
    return start === undefined || end === undefined ? '' : text.slice(start, end);
  };

  const components: Components = {
    table: ({ node, children }) => savable('table', node, source(node).trim(), <TableFrame>{children}</TableFrame>),
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
    ),
    blockquote: ({ node, children }) => savable(
      'quote', node,
      source(node).split('\n').map((line) => line.replace(/^\s*>\s?/, '')).join('\n').trim(),
      <blockquote>{children}</blockquote>,
    ),
    pre: ({ node, children }) => {
      const code = node?.children[0];
      if (code?.type !== 'element') return <pre>{children}</pre>;
      const classes = Array.isArray(code.properties?.className) ? code.properties.className.map(String) : [];
      const language = classes.find((item) => item.startsWith('language-'))?.slice('language-'.length) ?? '';
      const raw = code.children.map((child) => (child.type === 'text' ? child.value : '')).join('').replace(/\n$/, '');
      if (language === 'note') {
        const { title, body } = splitNoteBlock(raw);
        return <NoteCard title={title} body={body} onSave={onSaveNote} />;
      }
      if (language === 'prompt') {
        return savable('prompt', node, raw.trim(), <div className="agent-prompt-block">{raw}</div>);
      }
      // Other code keeps its fence so it still reads as code inside the note.
      return savable('code', node, source(node).trim() || raw, <pre>{children}</pre>);
    },
  };
  return (
    <div className={`markdown ${className ?? ''}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}


function SaveButton({ onSave }: { onSave: () => void }) {
  const [saved, setSaved] = useState(false);
  return (
    <button
      type="button"
      className="agent-note-save"
      data-tooltip="只把这一块存成便签，放到画布上"
      onClick={() => {
        onSave();
        setSaved(true);
        setTimeout(() => setSaved(false), 1800);
      }}
    >
      {saved ? <CheckIcon width={13} height={13} /> : <NoteAddIcon width={13} height={13} />}
      {saved ? '已存' : '存成便签'}
    </button>
  );
}

/** A table / code / prompt / quote with a hover "存成便签" button in its top-right corner. */
function SavableBlock({ kind, title, content, onSave, children }: {
  kind: BlockKind;
  title: string;
  content: string;
  onSave: (content: string, title: string) => void;
  children: ReactNode;
}) {
  return (
    <div className={`savable-block is-${kind}`} data-title={title}>
      {children}
      <div className="savable-block-action">
        <SaveButton onSave={() => onSave(content, title)} />
      </div>
    </div>
  );
}

function NoteCard({ title, body, onSave }: { title: string; body: string; onSave?: (content: string, title: string) => void }) {
  return (
    <div className="agent-note-block">
      <div className="agent-note-block-head">
        <span className="agent-note-block-title">{title}</span>
        {onSave && <SaveButton onSave={() => onSave(body, title)} />}
      </div>
      <div className="markdown agent-note-block-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ table: tableComponent }}>
          {body}
        </ReactMarkdown>
      </div>
    </div>
  );
}


interface SectionLabel { offset: number; level: number; text: string }

/**
 * Headings (# … ######) and bold-only lines (**生图提示词**) with their positions, so a
 * block can be named after the section it sits in.
 */
export function sectionLabels(text: string): SectionLabel[] {
  const labels: SectionLabel[] = [];
  let offset = 0;
  let fenced = false;
  for (const line of text.split('\n')) {
    if (/^\s*(```|~~~)/.test(line)) fenced = !fenced;
    if (!fenced) {
      const heading = /^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
      const bold = /^\s*\*\*([^*]+?)\*\*\s*[:：]?\s*$/.exec(line);
      if (heading) labels.push({ offset, level: heading[1].length, text: cleanLabel(heading[2]) });
      else if (bold) labels.push({ offset, level: 7, text: cleanLabel(bold[1]) });
    }
    offset += line.length + 1;
  }
  return labels;
}

/** "镜头 1 开场 · 生图提示词": the innermost two section labels above `offset`. */
export function titleAt(labels: SectionLabel[], offset: number): string {
  const stack: SectionLabel[] = [];
  for (const label of labels) {
    if (label.offset >= offset) break;
    while (stack.length && stack[stack.length - 1].level >= label.level) stack.pop();
    stack.push(label);
  }
  return stack.slice(-2).map((label) => label.text).join(' · ').slice(0, 40);
}

function cleanLabel(text: string): string {
  return text.replace(/[*_`]/g, '').replace(/\s*[|｜]\s*/g, ' ').replace(/\s+/g, ' ').trim();
}

const NOTE_FENCE = /^(```|~~~)note[^\n]*\n([\s\S]*?)^\1[ \t]*$/gm;

/** The ```note blocks in an agent reply, in order. */
export function noteBlocks(text: string): string[] {
  return [...text.matchAll(NOTE_FENCE)].map((match) => match[2].replace(/\n$/, ''));
}

/**
 * A note block (or any text being saved as a note): a leading "# 标题" line becomes the
 * note's title and is not repeated in the body.
 */
export function splitNoteBlock(source: string, fallback = '便签'): { title: string; body: string } {
  const text = source.replace(/^\s*\n/, '');
  const match = /^#{1,6}\s+(.+?)\s*#*[ \t]*(?:\n|$)/.exec(text);
  if (match) {
    return { title: match[1].slice(0, 30), body: text.slice(match[0].length).replace(/^\s*\n/, '').trimEnd() };
  }
  return { title: titleFromMarkdown(text, fallback), body: text.trimEnd() };
}

/** First heading or first line, trimmed — used as the title when saving text to the canvas. */
export function titleFromMarkdown(text: string, fallback: string): string {
  const line = text
    .split('\n')
    .map((item) => item.replace(/^#+\s*/, '').replace(/[*_`>|]/g, '').trim())
    .find(Boolean);
  return (line ?? fallback).slice(0, 30) || fallback;
}
