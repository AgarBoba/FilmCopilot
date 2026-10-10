export interface ImageSize { width: number; height: number }
export interface CropRect extends ImageSize { x: number; y: number }
export type CropHandle = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

export function fitCrop(size: ImageSize, ratio: number | null): CropRect {
  const width = ratio ? Math.max(1, Math.min(size.width, Math.round(size.height * ratio))) : size.width;
  const height = ratio ? Math.max(1, Math.min(size.height, Math.round(width / ratio))) : size.height;
  return { x: Math.floor((size.width - width) / 2), y: Math.floor((size.height - height) / 2), width, height };
}
export function moveCrop(rect: CropRect, dx: number, dy: number, size: ImageSize): CropRect {
  return { ...rect, x: clamp(Math.round(rect.x + dx), 0, size.width - rect.width),
    y: clamp(Math.round(rect.y + dy), 0, size.height - rect.height) };
}
export function resizeCrop(rect: CropRect, handle: CropHandle, dx: number, dy: number, size: ImageSize, ratio: number | null): CropRect {
  const west = handle.includes('w'), north = handle.includes('n');
  const horizontal = west || handle.includes('e'), vertical = north || handle.includes('s');
  const right = rect.x + rect.width, bottom = rect.y + rect.height;
  if (!ratio) {
    const left = west ? clamp(Math.round(rect.x + dx), 0, right - 1) : rect.x;
    const top = north ? clamp(Math.round(rect.y + dy), 0, bottom - 1) : rect.y;
    const endX = handle.includes('e') ? clamp(Math.round(right + dx), left + 1, size.width) : right;
    const endY = handle.includes('s') ? clamp(Math.round(bottom + dy), top + 1, size.height) : bottom;
    return { x: left, y: top, width: endX - left, height: endY - top };
  }
  // Keep the opposite corner fixed; for side handles center the other axis.
  const ax = horizontal ? (west ? right : rect.x) : rect.x + rect.width / 2;
  const ay = vertical ? (north ? bottom : rect.y) : rect.y + rect.height / 2;
  const maxWidth = horizontal ? (west ? ax : size.width - ax) : 2 * Math.min(ax, size.width - ax);
  const maxHeight = vertical ? (north ? ay : size.height - ay) : 2 * Math.min(ay, size.height - ay);
  let desired = rect.width + (west ? -dx : dx);
  if (!horizontal || (vertical && Math.abs(dy * ratio) > Math.abs(dx))) desired = (rect.height + (north ? -dy : dy)) * ratio;
  const width = Math.max(1, Math.round(clamp(desired, Math.max(1, ratio), Math.min(maxWidth, maxHeight * ratio))));
  const height = Math.max(1, Math.min(Math.floor(maxHeight), Math.round(width / ratio)));
  return { x: Math.round(horizontal ? (west ? ax - width : ax) : ax - width / 2),
    y: Math.round(vertical ? (north ? ay - height : ay) : ay - height / 2), width, height };
}
