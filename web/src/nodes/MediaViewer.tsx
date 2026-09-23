import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

import { CloseIcon, DownloadIcon } from '../canvas/icons';


interface MediaViewerProps {
  kind: 'image' | 'video';
  url: string;
  title: string;
  onDownload: () => void;
  onClose: () => void;
  /** Where to render; defaults to the canvas page so theme colours apply. */
  host?: Element | null;
}


/** Full-window viewer for a node's image or video. Esc or clicking the backdrop closes it. */
export function MediaViewer({ kind, url, title, onDownload, onClose, host }: MediaViewerProps) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      // Keep canvas shortcuts (Delete, V, H, Space…) from acting on the canvas behind.
      event.stopPropagation();
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKeyDown, true);
    return () => {
      window.removeEventListener('keydown', onKeyDown, true);
      previousFocus?.focus?.();
    };
  }, [onClose]);

  return createPortal(
    <div
      className="media-viewer"
      role="dialog"
      aria-modal="true"
      aria-label={`查看：${title}`}
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      onWheel={(event) => event.stopPropagation()}
    >
      <div className="media-viewer-bar">
        <span className="media-viewer-title">{title}</span>
        <button type="button" aria-label="下载" data-tooltip="下载到本地" data-tooltip-side="bottom" onClick={onDownload}>
          <DownloadIcon />
        </button>
        <button ref={closeRef} type="button" aria-label="关闭" data-tooltip="关闭" data-tooltip-shortcut="Esc" data-tooltip-side="bottom" onClick={onClose}>
          <CloseIcon />
        </button>
      </div>
      {kind === 'video' ? (
        <video className="media-viewer-content" src={url} controls autoPlay playsInline />
      ) : (
        <img className="media-viewer-content" src={url} alt={title} />
      )}
    </div>,
    host ?? document.querySelector('.canvas-page') ?? document.body,
  );
}
