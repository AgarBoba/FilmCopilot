/**
 * Dragging a block (table, prompt, quote, code, note card) out of an agent reply onto the
 * canvas. Dropped on an image/video node it is appended to the prompt; on a note, to its
 * text; on empty canvas it becomes a new note.
 */
export const AGENT_BLOCK_MIME = 'application/x-film-copilot-block';

export interface DraggedBlock {
  content: string;
  title: string;
  kind: string;
}

export function writeBlock(dataTransfer: DataTransfer, block: DraggedBlock) {
  dataTransfer.setData(AGENT_BLOCK_MIME, JSON.stringify(block));
  dataTransfer.setData('text/plain', block.content);
  dataTransfer.effectAllowed = 'copy';
}

export function carriesBlock(dataTransfer: DataTransfer | null): boolean {
  return !!dataTransfer && Array.from(dataTransfer.types).includes(AGENT_BLOCK_MIME);
}

export function readBlock(dataTransfer: DataTransfer | null): DraggedBlock | null {
  const raw = dataTransfer?.getData(AGENT_BLOCK_MIME);
  if (!raw) return null;
  try {
    const block = JSON.parse(raw) as Partial<DraggedBlock>;
    return typeof block.content === 'string'
      ? { content: block.content, title: String(block.title ?? ''), kind: String(block.kind ?? '') }
      : null;
  } catch {
    return null;
  }
}

/** Keeps what is there and adds the new text after a blank line. */
export function appendText(existing: string | undefined, addition: string): string {
  const before = (existing ?? '').replace(/\s+$/, '');
  const after = addition.trim();
  if (!before) return after;
  if (!after) return before;
  return `${before}\n\n${after}`;
}
