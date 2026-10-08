import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';

import { CheckIcon, SparkIcon } from '../canvas/icons';
import { commentApi, describeAnchor, type CanvasComment, type CommentAnchor } from './commentApi';

export { describeAnchor };
import { CommentPopover } from './CommentPopover';
import { openComments, queuePosition, useCommentStore } from './commentStore';
import { mediaToScreen, nodeMedia, screenToMedia, sideOf } from './mediaGeometry';

type XY = { x: number; y: number };

export interface CommentFlow {
  screenToFlowPosition: (point: XY) => XY;
  flowToScreenPosition: (point: XY) => XY;
  fitView: (options: { nodes: { id: string }[]; padding?: number; duration?: number; maxZoom?: number }) => Promise<boolean> | boolean | void;
  setCenter: (x: number, y: number, options?: { zoom?: number; duration?: number }) => Promise<boolean> | boolean | void;
  getViewport: () => { zoom: number };
}

interface CommentLayerProps {
  canvasId: string;
  /** Canvas revision: comments are re-read when the canvas changes (versions, deleted nodes). */
  revision: number;
  viewportRef: RefObject<HTMLDivElement | null>;
  flowRef: RefObject<CommentFlow | null>;
  selectedNodeIds: string[];
  nodeTitles: Record<string, string>;
  onOpenInPanel: (comment: CanvasComment) => void;
  onFocusNodes: (nodeIds: string[]) => void;
  onSaveToCanvas: (text: string, title?: string) => void;
}

/** Things the comment layer must not treat as "a click on the canvas". */
const UI = '.comment-ui, .react-flow__panel, .react-flow__minimap, .video-controls, .node-menu, .connection-chooser';
/** A pin on a video shows this long before and after its moment. */
const VIDEO_WINDOW = 0.5;

/**
 * Pins, the new-comment box and the comment popover, drawn over the canvas at a fixed size.
 * Positions are read from the DOM every frame, so pins follow nodes while they move and
 * pictures however they are cropped. In comment mode, clicks drop a pin instead of selecting.
 */
export function CommentLayer({
  canvasId, revision, viewportRef, flowRef, selectedNodeIds, nodeTitles, onOpenInPanel, onFocusNodes, onSaveToCanvas,
}: CommentLayerProps) {
  const { comments, mode, hidden, openId, draft, focusRequest, error } = useCommentStore();
  const [positions, setPositions] = useState<Record<string, XY | null>>({});
  const [bounds, setBounds] = useState({ width: 0, height: 0 });
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const stateRef = useRef({ comments, mode, hidden, openId, draft, selectedNodeIds });
  stateRef.current = { comments, mode, hidden, openId, draft, selectedNodeIds };

  // Load, then follow changes live.
  useEffect(() => {
    const store = useCommentStore.getState();
    void store.load(canvasId);
    return commentApi.stream(canvasId, (comment) => useCommentStore.getState().upsert(comment), () => {
      void useCommentStore.getState().load(canvasId);
    });
  }, [canvasId]);

  // The canvas changed (a new version landed, a node was deleted): refresh what pins show.
  useEffect(() => {
    const timer = setTimeout(() => void useCommentStore.getState().load(canvasId), 400);
    return () => clearTimeout(timer);
  }, [canvasId, revision]);

  // Where every pin is, re-measured each frame (cheap: a few rects).
  useEffect(() => {
    let frame = 0;
    let last = '';
    const tick = () => {
      frame = requestAnimationFrame(tick);
      const root = viewportRef.current;
      const flow = flowRef.current;
      if (!root || !flow) return;
      const rect = root.getBoundingClientRect();
      // The agent panel floats over the right side of the canvas: keep popovers out from under it.
      const panel = document.querySelector('.agent-panel')?.getBoundingClientRect();
      const usable = panel && panel.left > rect.left ? Math.min(rect.width, panel.left - rect.left - 8) : rect.width;
      const state = stateRef.current;
      const next: Record<string, XY | null> = {};
      const perNode = new Map<string, number>();
      const place = (key: string, anchor: CommentAnchor, forced: boolean) => {
        const point = locate(anchor, forced, state, perNode, root, flow);
        next[key] = point ? { x: Math.round(point.x - rect.left), y: Math.round(point.y - rect.top) } : null;
      };
      for (const comment of state.comments) {
        const forced = comment.id === state.openId;
        if (!forced && (comment.status === 'resolved' || state.hidden)) continue;
        place(comment.id, comment.anchor, forced);
      }
      if (state.draft) place('draft', state.draft.anchor, true);
      const key = JSON.stringify([next, usable, rect.height]);
      if (key !== last) {
        last = key;
        setPositions(next);
        setBounds({ width: usable, height: rect.height });
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [viewportRef, flowRef]);

  // Comment mode: a click drops a pin; the canvas doesn't select, drag or pan.
  useEffect(() => {
    const root = viewportRef.current;
    if (!root || !mode) return undefined;
    const qualifies = (event: Event) => {
      const target = event.target as Element | null;
      if (!target || target.closest(UI)) return false;
      return Boolean(target.closest('.react-flow__pane, .react-flow__node, .react-flow__renderer'));
    };
    const swallow = (event: Event) => {
      if (!qualifies(event)) return;
      event.preventDefault();
      event.stopPropagation();
    };
    const onPointerDown = (event: PointerEvent) => {
      if ((event.button ?? 0) > 0 || !qualifies(event)) return; // left button only
      event.preventDefault();
      event.stopPropagation();
      const anchor = anchorAt(event.clientX, event.clientY, event.target as Element, flowRef.current);
      if (anchor) {
        setText('');
        useCommentStore.getState().setDraft({ anchor });
        // One pin per trip: back to the normal pointer while typing. Shift keeps comment mode on.
        if (!event.shiftKey) useCommentStore.setState({ mode: false });
      }
    };
    root.addEventListener('pointerdown', onPointerDown, true);
    const others = ['mousedown', 'click', 'dblclick', 'touchstart'] as const;
    others.forEach((name) => root.addEventListener(name, swallow, true));
    return () => {
      root.removeEventListener('pointerdown', onPointerDown, true);
      others.forEach((name) => root.removeEventListener(name, swallow, true));
    };
  }, [mode, viewportRef, flowRef]);

  // Esc: cancel the new pin, then close the popover, then leave comment mode.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape') return;
      const store = useCommentStore.getState();
      if (store.draft) store.setDraft(null);
      else if (store.openId) store.open(null);
      else if (store.mode) store.setMode(false);
      else return;
      event.stopPropagation();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  // Asked to show a comment (from the panel list): bring its pin into view.
  useEffect(() => {
    if (!focusRequest) return;
    const comment = useCommentStore.getState().comments.find((item) => item.id === focusRequest.id);
    const flow = flowRef.current;
    if (!comment || !flow) return;
    if (comment.anchor.kind === 'canvas') {
      void flow.setCenter(comment.anchor.x ?? 0, comment.anchor.y ?? 0, { zoom: Math.max(flow.getViewport().zoom, 0.8), duration: 400 });
    } else if (comment.anchor.nodeId && !comment.nodeMissing) {
      void flow.fitView({ nodes: [{ id: comment.anchor.nodeId }], padding: 0.5, duration: 400, maxZoom: 1 });
    }
  }, [focusRequest, flowRef]);

  const open = openId ? comments.find((comment) => comment.id === openId) ?? null : null;
  const unresolved = openComments(comments);

  async function submit() {
    const body = text.trim();
    if (!draft || !body || sending) return;
    setSending(true);
    const created = await useCommentStore.getState().create(draft.anchor, body);
    setSending(false);
    if (created) setText('');
  }

  return (
    <div className="comment-layer" aria-hidden={false}>
      {mode && (
        <div className="comment-hint comment-ui" role="status">
          <span className="comment-hint-dot" aria-hidden="true" />
          <span>点一下放图钉留言 · 按住 Shift 可以连续留言</span>
          <button type="button" onClick={() => useCommentStore.getState().setHidden(!hidden)}>
            {hidden ? '显示图钉' : '隐藏图钉'}
          </button>
          <button type="button" onClick={() => useCommentStore.getState().setMode(false)}>退出 <kbd>Esc</kbd></button>
        </div>
      )}
      {!mode && hidden && unresolved.length > 0 && (
        <div className="comment-hint comment-ui is-quiet" role="status">
          <span>图钉已隐藏（{unresolved.length} 条留言）</span>
          <button type="button" onClick={() => useCommentStore.getState().setHidden(false)}>显示</button>
        </div>
      )}
      {comments.map((comment) => {
        const at = positions[comment.id];
        if (!at) return null;
        return (
          <Pin
            key={comment.id}
            comment={comment}
            at={at}
            active={comment.id === openId}
            queue={comment.status === 'queued' ? queuePosition(comments, comment.id) : 0}
            onClick={() => useCommentStore.getState().open(comment.id === openId ? null : comment.id)}
          />
        );
      })}
      {draft && positions.draft && (
        <>
          <span className="comment-pin is-draft comment-ui" style={{ left: positions.draft.x, top: positions.draft.y }} aria-hidden="true" />
          <div
            className="comment-draft comment-ui"
            style={{
              left: sideOf(positions.draft.x, 290, bounds.width),
              top: Math.min(Math.max(8, positions.draft.y - 40), bounds.height - 140),
            }}
            onKeyDown={(event) => event.stopPropagation()}
          >
            <div className="comment-draft-where">{describeAnchor(draft.anchor, nodeTitles)}</div>
            <textarea
              autoFocus
              rows={2}
              value={text}
              aria-label="留言内容"
              placeholder="想让 Agent 改什么？Enter 发送，Esc 取消"
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) return;
                if (event.key === 'Escape') {
                  useCommentStore.getState().setDraft(null);
                } else if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void submit();
                }
              }}
            />
            <div className="comment-draft-foot">
              <button type="button" className="comment-link" onClick={() => useCommentStore.getState().setDraft(null)}>取消</button>
              <button type="button" className="comment-button is-primary" disabled={!text.trim() || sending} onClick={() => void submit()}>
                交给 Agent
              </button>
            </div>
          </div>
        </>
      )}
      {open && (
        <CommentPopover
          comment={open}
          at={positions[open.id] ?? null}
          bounds={bounds}
          where={describeAnchor(open.anchor, nodeTitles)}
          onClose={() => useCommentStore.getState().open(null)}
          onOpenInPanel={onOpenInPanel}
          onFocusNodes={onFocusNodes}
          onSaveToCanvas={onSaveToCanvas}
        />
      )}
      {error && (
        <div className="comment-error comment-ui" role="alert">
          {error}
          <button type="button" aria-label="关闭提示" onClick={() => useCommentStore.setState({ error: null })}>×</button>
        </div>
      )}
    </div>
  );
}


function Pin({ comment, at, active, queue, onClick }: {
  comment: CanvasComment; at: XY; active: boolean; queue: number; onClick: () => void;
}) {
  const old = Boolean(comment.anchor.stale);
  const label = { queued: '排队中', running: 'Agent 处理中', waiting: '等你确认', done: '已完成', failed: '没做完', resolved: '已解决' }[comment.status];
  return (
    <button
      type="button"
      className={`comment-pin comment-ui is-${comment.status} ${old ? 'is-old' : ''} ${active ? 'is-active' : ''}`}
      style={{ left: at.x, top: at.y }}
      aria-label={`留言：${comment.text}（${label}）`}
      data-tooltip={`${label}${old ? ' · 针对上一版' : ''}：${comment.text.slice(0, 40)}`}
      data-tooltip-side="top"
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
    >
      {comment.status === 'queued' && <span>{queue || ''}</span>}
      {comment.status === 'running' && <SparkIcon width={13} height={13} />}
      {comment.status === 'waiting' && <span>!</span>}
      {(comment.status === 'done' || comment.status === 'resolved') && <CheckIcon width={13} height={13} />}
      {comment.status === 'failed' && <span>×</span>}
    </button>
  );
}


/** What a click at this point pins to: a spot in a picture, a node, or the canvas. */
export function anchorAt(clientX: number, clientY: number, target: Element, flow: CommentFlow | null): CommentAnchor | null {
  const nodeElement = target.closest('.react-flow__node');
  const nodeId = nodeElement?.getAttribute('data-id');
  if (nodeElement && nodeId && !nodeId.startsWith('ghost:')) {
    const { element, natural } = nodeMedia(nodeId, nodeElement.parentElement ?? document);
    if (element && target.closest('.media-preview')) {
      const at = screenToMedia(element.getBoundingClientRect(), natural, { x: clientX, y: clientY });
      if (element instanceof HTMLVideoElement) {
        // The pin is for the frame the user is looking at: stop there.
        if (!element.paused) element.pause();
        element.dataset.held = '1';
        return { kind: 'media', nodeId, x: round(at.x), y: round(at.y), time: Math.round(element.currentTime * 100) / 100 };
      }
      return { kind: 'media', nodeId, x: round(at.x), y: round(at.y) };
    }
    return { kind: 'node', nodeId };
  }
  if (!flow) return null;
  const point = flow.screenToFlowPosition({ x: clientX, y: clientY });
  return { kind: 'canvas', x: Math.round(point.x), y: Math.round(point.y) };
}

function round(value: number) {
  return Math.round(value * 10000) / 10000;
}


/** Screen position of a pin's tip, or null when it should not be drawn right now. */
function locate(
  anchor: CommentAnchor,
  forced: boolean,
  state: { mode: boolean; selectedNodeIds: string[] },
  perNode: Map<string, number>,
  root: HTMLElement,
  flow: CommentFlow,
): XY | null {
  if (anchor.kind === 'canvas') {
    return flow.flowToScreenPosition({ x: anchor.x ?? 0, y: anchor.y ?? 0 });
  }
  const nodeId = anchor.nodeId;
  if (!nodeId) return null;
  // On a closed (unselected) card the node shows a count badge instead of pins.
  if (!forced && !state.mode && !state.selectedNodeIds.includes(nodeId)) return null;
  const { node, element, natural } = nodeMedia(nodeId, root);
  if (!node) return null;
  if (anchor.kind === 'node' || !element) {
    const rect = node.getBoundingClientRect();
    const index = perNode.get(nodeId) ?? 0;
    perNode.set(nodeId, index + 1);
    return { x: rect.right - 44 - index * 26, y: rect.top + 48 };
  }
  if (element instanceof HTMLVideoElement && anchor.time != null && !forced
    && Math.abs(element.currentTime - anchor.time) > VIDEO_WINDOW) {
    return null;
  }
  const point = mediaToScreen(element.getBoundingClientRect(), natural, { x: anchor.x ?? 0.5, y: anchor.y ?? 0.5 });
  return point.visible || forced ? point : null;
}
