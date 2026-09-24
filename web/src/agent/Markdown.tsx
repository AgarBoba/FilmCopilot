import { useState } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { CheckIcon, NoteAddIcon } from '../canvas/icons';

interface MarkdownProps {
  text: string;
  className?: string;
  /**
   * Agent replies only. ```note blocks are the parts worth keeping (a revised prompt, a
   * storyboard table): they render as cards, each with its own "存到画布" button.
   */
  onSaveNote?: (content: string, title: string) => void;
}

const tableComponent: Components['table'] = ({ children }) => (
  <div className="markdown-table nowheel">
    <table>{children}</table>
  </div>
);


/**
 * Renders agent replies and note text: headings, lists, tables (GFM), code, quotes.
 * Raw HTML in the text is shown as text, never executed. Wide tables scroll sideways.
 */
export function Markdown({ text, className, onSaveNote }: MarkdownProps) {
  const components: Components = {
    table: tableComponent,
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
    ),
    pre: ({ node, children }) => {
      const code = node?.children[0];
      if (code?.type === 'element') {
        const classes = code.properties?.className;
        if (Array.isArray(classes) && classes.includes('language-note')) {
          const source = code.children.map((child) => (child.type === 'text' ? child.value : '')).join('');
          return <NoteBlock source={source} onSave={onSaveNote} />;
        }
      }
      return <pre>{children}</pre>;
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


function NoteBlock({ source, onSave }: { source: string; onSave?: (content: string, title: string) => void }) {
  const [saved, setSaved] = useState(false);
  const { title, body } = splitNoteBlock(source);
  return (
    <div className="agent-note-block">
      <div className="agent-note-block-head">
        <span className="agent-note-block-title">{title}</span>
        {onSave && (
          <button
            type="button"
            className="agent-note-save"
            data-tooltip="存成便签放到画布上"
            onClick={() => {
              onSave(body, title);
              setSaved(true);
              setTimeout(() => setSaved(false), 1800);
            }}
          >
            {saved ? <CheckIcon width={13} height={13} /> : <NoteAddIcon width={13} height={13} />}
            {saved ? '已存' : '存到画布'}
          </button>
        )}
      </div>
      <div className="markdown agent-note-block-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ table: tableComponent }}>
          {body}
        </ReactMarkdown>
      </div>
    </div>
  );
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
