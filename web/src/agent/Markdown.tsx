import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface MarkdownProps {
  text: string;
  className?: string;
}


/**
 * Renders agent replies and note text: headings, lists, tables (GFM), code, quotes.
 * Raw HTML in the text is shown as text, never executed. Wide tables scroll sideways.
 */
export function Markdown({ text, className }: MarkdownProps) {
  return (
    <div className={`markdown ${className ?? ''}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children }) => (
            <div className="markdown-table nowheel">
              <table>{children}</table>
            </div>
          ),
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

/** First heading or first line, trimmed — used as the title when saving text to the canvas. */
export function titleFromMarkdown(text: string, fallback: string): string {
  const line = text
    .split('\n')
    .map((item) => item.replace(/^#+\s*/, '').replace(/[*_`>|]/g, '').trim())
    .find(Boolean);
  return (line ?? fallback).slice(0, 30) || fallback;
}
