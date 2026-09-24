import { useCallback, useEffect, useRef, useState } from 'react';

import { ChevronLeftIcon, ChevronRightIcon } from '../canvas/icons';

export interface NodeReference {
  /** Edge that brings this reference in; used to disconnect it. */
  edgeId?: string;
  /** The node itself, when the strip lists nodes rather than connections (agent focus). */
  nodeId?: string;
  /** Asset URL, or undefined when the upstream node has no content yet. */
  url?: string;
  kind: 'image' | 'video' | 'note';
  /** Note text (kind 'note' only); added to the prompt when generating. */
  text?: string;
  /** Upstream node name, for the tooltip. */
  title?: string;
}

/** Accepts the old string-only form (image URLs) as well as full reference objects. */
export function normalizeReferences(references: ReadonlyArray<NodeReference | string> | undefined): NodeReference[] {
  return (references ?? []).map((reference) => (
    typeof reference === 'string' ? { url: reference, kind: 'image' } : reference
  ));
}

interface ReferenceStripProps {
  references: NodeReference[];
  onRemove?: (reference: NodeReference) => void;
  /** Tooltip on the × button; the default suits references wired into a node. */
  removeTooltip?: string;
  /** Accessible name of the strip. */
  label?: string;
  compact?: boolean;
}

const KIND_LABELS = { image: '图片', video: '视频', note: '便签' } as const;
const SNIPPET_LENGTH = 24;


/** Thumbnails of the upstream nodes connected into this one. */
export function ReferenceStrip({ references, onRemove, removeTooltip, label = '参考素材', compact = false }: ReferenceStripProps) {
  const { scrollRef, canLeft, canRight, scrollByPage } = useHorizontalScroll(references.length);
  if (!references.length) return null;
  return (
    <div className={`reference-strip-frame ${compact ? 'is-compact' : ''} ${canLeft ? 'can-left' : ''} ${canRight ? 'can-right' : ''}`}>
      {canLeft && (
        <button
          type="button"
          className="reference-scroll-button is-left nodrag"
          aria-label="向左查看参考素材"
          data-tooltip="向左查看"
          onClick={(event) => { event.stopPropagation(); scrollByPage(-1); }}
        >
          <ChevronLeftIcon width={14} height={14} />
        </button>
      )}
      {canRight && (
        <button
          type="button"
          className="reference-scroll-button is-right nodrag"
          aria-label="向右查看参考素材"
          data-tooltip={`向右查看（共 ${references.length} 个）`}
          onClick={(event) => { event.stopPropagation(); scrollByPage(1); }}
        >
          <ChevronRightIcon width={14} height={14} />
        </button>
      )}
    <div ref={scrollRef} className="reference-strip nowheel" aria-label={label}>
      {references.map((reference, index) => {
        if (reference.kind === 'note') {
          return (
            <NoteChip key={reference.edgeId ?? reference.nodeId ?? `note-${index}`} reference={reference} index={index}
              onRemove={onRemove} removeTooltip={removeTooltip} />
          );
        }
        const name = reference.title ?? `参考${KIND_LABELS[reference.kind]} ${index + 1}`;
        const tooltip = reference.url
          ? `参考${KIND_LABELS[reference.kind]}：${name}`
          : `「${name}」还没有内容，生成时会跳过它`;
        return (
          <div
            className={`reference-thumb ${reference.url ? '' : 'is-empty'}`}
            key={reference.edgeId ?? reference.nodeId ?? `${reference.url}-${index}`}
            data-tooltip={tooltip}
            data-tooltip-side="bottom"
          >
            {reference.url && reference.kind === 'video' && (
              <video src={reference.url} muted playsInline preload="metadata" aria-label={`reference-${index + 1}`} />
            )}
            {reference.url && reference.kind === 'image' && (
              <img src={reference.url} alt={`reference-${index + 1}`} />
            )}
            {!reference.url && <span className="reference-empty">空</span>}
            {reference.kind === 'video' && reference.url && <span className="reference-badge">视频</span>}
            {onRemove && (
              <button
                type="button"
                className="nodrag"
                aria-label={`删除参考素材 ${index + 1}`}
                data-tooltip={removeTooltip ?? '移除这个参考（会断开连线）'}
                onClick={(event) => {
                  event.stopPropagation();
                  onRemove(reference);
                }}
              >
                ×
              </button>
            )}
          </div>
        );
      })}
    </div>
    </div>
  );
}


/**
 * Horizontal scrolling for the reference strip:
 * - trackpad side-swipe scrolls it natively; a plain vertical wheel is turned sideways
 * - `nowheel` keeps React Flow from panning the canvas while the pointer is over it
 * - reports whether there is more to either side, for the fades and arrow buttons
 */
function useHorizontalScroll(itemCount: number) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [canLeft, setCanLeft] = useState(false);
  const [canRight, setCanRight] = useState(false);

  const update = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setCanLeft(el.scrollLeft > 1);
    setCanRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 1);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;
    update();
    function onWheel(event: WheelEvent) {
      if (event.ctrlKey) return; // pinch zoom still goes to the canvas
      if (el!.scrollWidth <= el!.clientWidth) return;
      if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
        event.preventDefault();
        el!.scrollLeft += event.deltaY;
      }
    }
    el.addEventListener('scroll', update, { passive: true });
    el.addEventListener('wheel', onWheel, { passive: false });
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(update) : null;
    observer?.observe(el);
    return () => {
      el.removeEventListener('scroll', update);
      el.removeEventListener('wheel', onWheel);
      observer?.disconnect();
    };
  }, [update, itemCount]);

  const scrollByPage = useCallback((direction: 1 | -1) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollBy({ left: direction * el.clientWidth * 0.8, behavior: 'smooth' });
  }, []);

  return { scrollRef, canLeft, canRight, scrollByPage };
}


interface NoteChipProps {
  reference: NodeReference;
  index: number;
  onRemove?: (reference: NodeReference) => void;
  removeTooltip?: string;
}


/** A connected note: its name and the start of its text. The full text is in the tooltip. */
function NoteChip({ reference, index, onRemove, removeTooltip }: NoteChipProps) {
  const text = reference.text?.trim() ?? '';
  const name = reference.title?.trim() || `便签 ${index + 1}`;
  const snippet = text.length > SNIPPET_LENGTH ? `${text.slice(0, SNIPPET_LENGTH)}…` : text;
  return (
    <div
      className={`reference-note ${text ? '' : 'is-empty'}`}
      data-tooltip={text ? `会加入提示词：\n${text}` : `「${name}」还没有文字，生成时会跳过它`}
      data-tooltip-side="bottom"
    >
      <span className="reference-note-name">{name}</span>
      <span className="reference-note-text">{snippet || '空便签'}</span>
      {onRemove && (
        <button
          type="button"
          className="nodrag"
          aria-label={`删除参考便签 ${index + 1}`}
          data-tooltip={removeTooltip ?? '移除这个便签（会断开连线）'}
          onClick={(event) => {
            event.stopPropagation();
            onRemove(reference);
          }}
        >
          ×
        </button>
      )}
    </div>
  );
}
