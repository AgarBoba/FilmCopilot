import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';

import { CheckIcon, CloseIcon, SparkIcon } from '../canvas/icons';
import { commentApi, describeAnchor, formatMoment, pinState, STATUS_LABELS, type CanvasComment, type CommentAnchor } from './commentApi';

export { describeAnchor };
import { CommentComposer } from './CommentComposer';
import { CommentPopover, POPOVER_WIDTH } from './CommentPopover';
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
  /** Comment mode, pointer over a picture or video: says the pin will carry a spot (and a moment). */
  const [hint, setHint] = useState<{ x: number; y: number; time: number | null } | null>(null);
  const hoverRef = useRef<{ x: number; y: number; target: Element } | null>(null);
  const stateRef = useRef({ comments, mode, hidden, openId, draft, selectedNodeIds });
  stateRef.current = { comments, mode, hidden, openId, draft, selectedNodeIds };

  // Load, then follow changes live.
  useEffect(() => {
    const store = useCommentStore.getState();
    void store.load(canvasId);
    return commentApi.stream(
      canvasId,
      (comment) => useCommentStore.getState().upsert(comment),
      () => void useCommentStore.getState().load(canvasId),
      (id) => useCommentStore.getState().drop(id),
    );
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
      // Read every frame, so a playing video's time in the hint keeps up.
      const hover = state.mode ? hoverRef.current : null;
      const over = hover && !hover.target.closest(UI) ? anchorAt(hover.x, hover.y, hover.target, flow, true) : null;
      const nextHint = over?.kind === 'media'
        ? { x: Math.round(hover!.x - rect.left), y: Math.round(hover!.y - rect.top), time: over.time ?? null }
        : null;
      const key = JSON.stringify([next, usable, rect.height, nextHint]);
      if (key !== last) {
        last = key;
        setPositions(next);
        setBounds({ width: usable, height: rect.height });
        setHint(nextHint);
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
        useCommentStore.getState().setDraft({ anchor });
        // One pin per trip: back to the normal pointer while typing. Shift keeps comment mode on.
        if (!event.shiftKey) useCommentStore.setState({ mode: false });
      }
    };
    const onPointerMove = (event: PointerEvent) => {
      hoverRef.current = { x: event.clientX, y: event.clientY, target: event.target as Element };
    };
    const onPointerLeave = () => { hoverRef.current = null; };
    root.addEventListener('pointermove', onPointerMove, { capture: true, passive: true });
    root.addEventListener('pointerleave', onPointerLeave);
    root.addEventListener('pointerdown', onPointerDown, true);
    const others = ['mousedown', 'click', 'dblclick', 'touchstart'] as const;
    others.forEach((name) => root.addEventListener(name, swallow, true));
    return () => {
      hoverRef.current = null;
      root.removeEventListener('pointermove', onPointerMove, { capture: true });
      root.removeEventListener('pointerleave', onPointerLeave);
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

  async function submit(body: string, toAgent: boolean) {
    if (!draft) return false;
    return Boolean(await useCommentStore.getState().create(draft.anchor, body, toAgent));
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
      {hint && (
        <div className="comment-hover-hint" style={{ left: Math.min(hint.x + 18, Math.max(8, bounds.width - 250)), top: Math.min(hint.y + 20, bounds.height - 56) }} aria-hidden="true">
          <span className="comment-hover-title">
            {hint.time != null ? `钉在 ${formatMoment(hint.time)} 这一帧的这一点` : '钉在画面的这一点'}
          </span>
          <span className="comment-hover-detail">
            {hint.time != null ? 'Agent 会拿到位置和时间，点下时视频暂停' : 'Agent 会拿到具体位置，看到你指的是哪里'}
          </span>
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
            queue={comment.agentStatus === 'queued' ? queuePosition(comments, comment.id) : 0}
            onClick={() => useCommentStore.getState().open(comment.id === openId ? null : comment.id)}
          />
        );
      })}
      {draft && positions.draft && (
        <>
          <span className="comment-pin is-draft comment-ui" style={{ left: positions.draft.x, top: positions.draft.y }} aria-hidden="true" />
          <div
            className="comment-draft comment-ui"
            role="dialog"
            aria-label="新留言"
            style={{
              left: sideOf(positions.draft.x, POPOVER_WIDTH, bounds.width),
              top: Math.min(Math.max(8, positions.draft.y - 32), bounds.height - 150),
              width: POPOVER_WIDTH,
            }}
            onKeyDown={(event) => event.stopPropagation()}
          >
            <div className="comment-msg-head">
              <span className="comment-avatar" aria-hidden="true">我</span>
              <span className="comment-msg-name">新留言</span>
              <span className="comment-msg-time comment-draft-where">{describeAnchor(draft.anchor, nodeTitles)}</span>
              <span className="comment-corner">
                <button type="button" className="comment-icon" aria-label="取消" onClick={() => useCommentStore.getState().setDraft(null)}>
                  <CloseIcon width={15} height={15} />
                </button>
              </span>
            </div>
            <CommentComposer
              autoFocus
              label="留言内容"
              placeholder="写点什么…"
              onSubmit={submit}
              onCancel={() => useCommentStore.getState().setDraft(null)}
            />
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
  const state = pinState(comment);
  const label = state === 'note' ? '留言' : state === 'resolved' ? '已解决' : `Agent · ${STATUS_LABELS[state]}`;
  const count = 1 + comment.replies.length;
  const agent = comment.agentStatus !== null && state !== 'resolved';
  return (
    <button
      type="button"
      className={`comment-pin comment-ui is-${state} ${agent ? 'is-agent' : ''} ${old ? 'is-old' : ''} ${active ? 'is-active' : ''}`}
      style={{ left: at.x, top: at.y }}
      aria-label={`留言：${comment.text}（${label}）`}
      data-tooltip={`${label}${old ? ' · 针对上一版' : ''}：${comment.text.slice(0, 40)}`}
      data-tooltip-side="top"
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
    >
      {(state === 'note' || state === 'resolved') && count > 1 && <span>{count}</span>}
      {state === 'queued' && <><SparkIcon width={11} height={11} />{queue > 0 && <span>{queue}</span>}</>}
      {(state === 'running' || state === 'waiting') && <SparkIcon width={13} height={13} />}
      {state === 'done' && <CheckIcon width={13} height={13} />}
      {state === 'failed' && <span>!</span>}
    </button>
  );
}


/**
 * What a click at this point pins to: a spot in a picture, a node, or the canvas.
 * `peek`: only looking (the hover hint), so a playing video is left alone.
 */
export function anchorAt(
  clientX: number, clientY: number, target: Element, flow: CommentFlow | null, peek = false,
): CommentAnchor | null {
  const nodeElement = target.closest('.react-flow__node');
  const nodeId = nodeElement?.getAttribute('data-id');
  if (nodeElement && nodeId && !nodeId.startsWith('ghost:')) {
    const { element, natural } = nodeMedia(nodeId, nodeElement.parentElement ?? document);
    if (element && target.closest('.media-preview')) {
      const at = screenToMedia(element.getBoundingClientRect(), natural, { x: clientX, y: clientY });
      if (element instanceof HTMLVideoElement) {
        if (!peek) {
          // The pin is for the frame the user is looking at: stop there.
          if (!element.paused) element.pause();
          element.dataset.held = '1';
        }
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
