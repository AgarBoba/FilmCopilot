/**
 * Pictures on the canvas are shown with `object-fit: cover`: scaled to fill their box and
 * cropped at the edges. Comments store positions inside the picture itself (0-1 from the
 * top left), so clicks and pins go through this mapping.
 */
export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface Natural {
  width: number;
  height: number;
}

function cover(box: Box, natural: Natural) {
  const scale = Math.max(box.width / natural.width, box.height / natural.height);
  const width = natural.width * scale;
  const height = natural.height * scale;
  return { width, height, left: box.left + (box.width - width) / 2, top: box.top + (box.height - height) / 2 };
}

/** Screen point -> position inside the picture (0-1). */
export function screenToMedia(box: Box, natural: Natural, point: { x: number; y: number }) {
  if (!natural.width || !natural.height) {
    return { x: clamp01((point.x - box.left) / box.width), y: clamp01((point.y - box.top) / box.height) };
  }
  const shown = cover(box, natural);
  return { x: clamp01((point.x - shown.left) / shown.width), y: clamp01((point.y - shown.top) / shown.height) };
}

/** Position inside the picture -> screen point, and whether it is inside the visible part. */
export function mediaToScreen(box: Box, natural: Natural, at: { x: number; y: number }) {
  const shown = natural.width && natural.height ? cover(box, natural) : box;
  const x = shown.left + at.x * shown.width;
  const y = shown.top + at.y * shown.height;
  const visible = x >= box.left - 1 && x <= box.left + box.width + 1 && y >= box.top - 1 && y <= box.top + box.height + 1;
  return { x, y, visible };
}

function clamp01(value: number) {
  return Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0));
}

/** The picture element of a node on the canvas, with its natural size (0 until loaded). */
export function nodeMedia(nodeId: string, root: ParentNode = document) {
  const node = root.querySelector(`.react-flow__node[data-id="${CSS.escape(nodeId)}"]`);
  const element = node?.querySelector<HTMLImageElement | HTMLVideoElement>('.media-preview img, .media-preview video') ?? null;
  if (!node || !element) return { node, element: null, natural: { width: 0, height: 0 } };
  const natural = element instanceof HTMLVideoElement
    ? { width: element.videoWidth, height: element.videoHeight }
    : { width: element.naturalWidth, height: element.naturalHeight };
  return { node, element, natural };
}

/** Right of the pin when there is room, otherwise to its left. */
export function sideOf(pinX: number, width: number, available: number): number {
  if (pinX + 38 + width <= available - 8) return pinX + 38;
  return Math.max(8, Math.min(pinX - width - 12, available - width - 8));
}
