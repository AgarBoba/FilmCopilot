import { useCallback, useEffect, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { createPortal } from 'react-dom';
import { CloseIcon } from '../canvas/icons';
import { assetFileUrl } from '../comments/commentApi';
import { useCanvasStore } from '../state/canvasStore';
import { fitCrop, moveCrop, resizeCrop } from './cropGeometry';
import type { CropHandle, CropRect, ImageSize } from './cropGeometry';

const HANDLES: CropHandle[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];
const HANDLE_NAMES = { nw: '左上', n: '上', ne: '右上', e: '右', se: '右下', s: '下', sw: '左下', w: '左' };
interface Drag { handle: CropHandle | 'move'; rect: CropRect; x: number; y: number; pointerId: number }

export function ImageCropDialog({ nodeId, title, onClose }: { nodeId: string; title: string; onClose: () => void }) {
  const source = useCanvasStore(state => state.snapshot?.nodes.find(n => n.id === nodeId));
  const jobs = useCanvasStore(state => state.snapshot?.jobs);
  const [sourceAssetId] = useState(() => String(source?.data.assetId ?? ''));
  const [size, setSize] = useState<ImageSize | null>(null);
  const [rect, setRect] = useState<CropRect | null>(null);
  const [ratioKey, setRatioKey] = useState('free');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const dialogRef = useRef<HTMLDivElement>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const [available, setAvailable] = useState({ width: 800, height: 400 });
  const stageRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const drag = useRef<Drag | null>(null);
  const requestKey = useRef<string | null>(null);
  const changed = source?.data.assetId !== sourceAssetId;
  const generating = jobs?.some(job => job.target_node_id === nodeId && ['queued', 'running'].includes(String(job.status)));
  const ratio = ratioKey === 'free' ? null : ratioKey === 'original' ? (size ? size.width / size.height : null)
    : Number(ratioKey.split(':')[0]) / Number(ratioKey.split(':')[1]);
  const unchanged = !size || !rect || (rect.x === 0 && rect.y === 0 && rect.width === size.width && rect.height === size.height);
  const canSave = !busy && !changed && !generating && !unchanged;
  const close = useCallback(() => { if (!busy) onClose(); }, [busy, onClose]);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    function keydown(event: KeyboardEvent) {
      event.stopPropagation();
      if (event.key === 'Escape') { event.preventDefault(); close(); }
      if (event.key === 'Tab') {
        const elements = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled), [tabindex="0"]') ?? []);
        const index = elements.indexOf(document.activeElement as HTMLElement);
        if (elements.length && ((event.shiftKey && index <= 0) || (!event.shiftKey && index === elements.length - 1))) {
          event.preventDefault(); elements[event.shiftKey ? elements.length - 1 : 0].focus();
        }
      }
    }
    window.addEventListener('keydown', keydown, true);
    return () => { window.removeEventListener('keydown', keydown, true); previous?.focus?.(); };
  }, [close]);

  useEffect(() => {
    const workspace = workspaceRef.current;
    if (!workspace) return;
    const measure = () => {
      const box = workspace.getBoundingClientRect();
      if (box.width && box.height) setAvailable({ width: Math.max(1, box.width - 48), height: Math.max(1, box.height - 32) });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(workspace);
    return () => observer.disconnect();
  }, []);

  function loadImage() {
    const image = imageRef.current;
    if (!image?.naturalWidth || !image.naturalHeight) return;
    const dimensions = { width: image.naturalWidth, height: image.naturalHeight };
    setSize(dimensions); setRect(fitCrop(dimensions, null)); setError('');
  }
  useEffect(() => { if (imageRef.current?.complete) loadImage(); }, []);

  function start(event: ReactPointerEvent, handle: Drag['handle']) {
    if (!rect || !size || busy || changed || generating || event.button !== 0) return;
    event.preventDefault(); event.stopPropagation();
    requestKey.current = null;
    drag.current = { handle, rect, x: event.clientX, y: event.clientY, pointerId: event.pointerId };
    stageRef.current?.setPointerCapture(event.pointerId);
  }
  function move(event: ReactPointerEvent) {
    const active = drag.current, stage = stageRef.current?.getBoundingClientRect();
    if (!active || active.pointerId !== event.pointerId || !size || !stage?.width || !stage.height) return;
    const dx = (event.clientX - active.x) * size.width / stage.width;
    const dy = (event.clientY - active.y) * size.height / stage.height;
    setRect(active.handle === 'move' ? moveCrop(active.rect, dx, dy, size) : resizeCrop(active.rect, active.handle, dx, dy, size, ratio));
  }
  function stop() { drag.current = null; }
  function chooseRatio(value: string) {
    setRatioKey(value); requestKey.current = null;
    const r = value === 'free' ? null : value === 'original' ? size!.width / size!.height
      : Number(value.split(':')[0]) / Number(value.split(':')[1]);
    if (size) setRect(fitCrop(size, r));
  }
  async function save() {
    if (!canSave || !rect) return;
    const state = useCanvasStore.getState();
    if (!state.snapshot) return;
    setBusy(true); setError('');
    requestKey.current ??= `crop-${crypto.randomUUID()}`;
    try {
      const result = await state.execute({ command: 'crop_image', baseRevision: state.snapshot.revision,
        idempotencyKey: requestKey.current, payload: { sourceNodeId: nodeId, sourceAssetId, rect } });
      if (!result) throw new Error('画布不可用，请重新打开。');
      useCanvasStore.getState().selectNodes([String(result.payload.nodeId)]);
      onClose();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '裁剪失败，请重试。'); }
    finally { setBusy(false); }
  }

  return createPortal(
    <div className="image-crop-backdrop" onWheel={event => event.stopPropagation()} onPointerDown={event => event.stopPropagation()}>
      <div ref={dialogRef} className="image-crop-dialog" role="dialog" aria-modal="true" aria-label={`裁剪：${title}`}>
        <header><div><strong>裁剪图片</strong><span>{title}</span></div>
          <button ref={closeRef} type="button" aria-label="关闭裁剪" data-tooltip="关闭裁剪" disabled={busy} onClick={close}><CloseIcon width={18} height={18} /></button>
        </header>
        <div ref={workspaceRef} className="image-crop-workspace">
          <div ref={stageRef} className="image-crop-stage" style={size ? { width: size.width * Math.min(available.width / size.width, available.height / size.height), height: size.height * Math.min(available.width / size.width, available.height / size.height) } : undefined}
            onPointerMove={move} onPointerUp={stop} onPointerCancel={stop} onLostPointerCapture={stop}>
            <img ref={imageRef} src={assetFileUrl(sourceAssetId)} alt="裁剪预览" draggable={false} onLoad={loadImage} onError={() => setError('图片加载失败，请重新打开。')} />
            {size && rect && <div className="image-crop-selection" role="group" aria-label="裁剪范围"
              onPointerDown={event => start(event, 'move')}
              style={{ left: `${rect.x / size.width * 100}%`, top: `${rect.y / size.height * 100}%`, width: `${rect.width / size.width * 100}%`, height: `${rect.height / size.height * 100}%` }}>
              <div className="image-crop-grid" />
              {HANDLES.map(handle => <span key={handle} className={`image-crop-handle crop-${handle}`} aria-hidden="true" title={`调整${HANDLE_NAMES[handle]}边缘`} onPointerDown={event => start(event, handle)} />)}
            </div>}
          </div>
        </div>
        <div className="image-crop-options"><label>比例 <select aria-label="裁剪比例" value={ratioKey} disabled={!size || busy || changed || generating} onChange={event => chooseRatio(event.target.value)}>
          <option value="free">自由</option><option value="original">原图比例</option>
          {['1:1', '4:3', '3:4', '16:9', '9:16'].map(value => <option key={value} value={value}>{value}</option>)}
        </select></label><span>{rect ? `${rect.width} × ${rect.height} 像素` : '正在加载图片…'}</span></div>
        <p className="image-crop-hint">拖动选框移动，拖动边缘调整。裁剪后新建图片节点，原图保持不变。</p>
        {(changed || generating || error) && <p className="image-crop-error" role="alert">{changed ? '原图片已变化，请关闭并重新打开裁剪。' : generating ? '图片正在生成，请完成后再裁剪。' : error}</p>}
        <footer><button type="button" disabled={!size || busy} onClick={() => { setRatioKey('free'); setRect(fitCrop(size!, null)); requestKey.current = null; }}>重置</button>
          <div><button type="button" disabled={busy} onClick={close}>取消</button><button type="button" className="image-crop-apply" disabled={!canSave} onClick={() => void save()}>{busy ? '正在保存…' : '裁剪为新节点'}</button></div>
        </footer>
      </div>
    </div>, document.querySelector('.canvas-page') ?? document.body,
  );
}
