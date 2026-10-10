import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MediaNodeActions } from '../nodes/MediaNodeActions';
import { useCanvasStore } from '../state/canvasStore';

beforeEach(() => { vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} }); });
const initial = useCanvasStore.getState();
afterEach(() => { cleanup(); useCanvasStore.setState(initial, true); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function setup(busy = false) {
  useCanvasStore.setState({ canvasId: 'canvas', snapshot: {
    canvasId: 'canvas', name: 'Crop', revision: 1, viewport: { x: 0, y: 0, zoom: 1 },
    nodes: [{ id: 'image', nodeType: 'image', x: 0, y: 0, data: { title: '角色', prompt: '原提示词', assetId: 'asset' } }],
    edges: [], assets: [], jobs: [],
  } });
  render(<MediaNodeActions kind="image" nodeId="image" assetUrl="/api/assets/asset/file" title="角色" busy={busy} />);
  fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
}

describe('manual crop entry', () => {
  it('opens crop, chooses a ratio, resets and cancels without saving', () => {
    setup();
    fireEvent.click(screen.getByRole('menuitem', { name: '裁剪' }));
    const image = screen.getByAltText('裁剪预览');
    Object.defineProperty(image, 'naturalWidth', { value: 800 });
    Object.defineProperty(image, 'naturalHeight', { value: 600 });
    fireEvent.load(image);
    expect(screen.getByRole('button', { name: '裁剪为新节点' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('裁剪比例'), { target: { value: '1:1' } });
    expect(screen.getByText('600 × 600 像素')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '裁剪为新节点' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: '重置' }));
    expect(screen.getByText('800 × 600 像素')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(useCanvasStore.getState().snapshot?.nodes).toHaveLength(1);
  });
  it('saves the selected pixels through the canvas command and selects the new node', async () => {
    setup();
    const before = useCanvasStore.getState().snapshot!;
    const requests: Record<string, unknown>[] = [];
    vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/commands')) {
        requests.push(JSON.parse(String(init?.body)));
        return new Response(JSON.stringify({ revision: 2, command: 'crop_image', payload: { nodeId: 'cropped' } }));
      }
      return new Response(JSON.stringify({ ...before, revision: 2, nodes: [...before.nodes, { id: 'cropped', nodeType: 'image', x: 340, y: 0, data: { title: '角色 · 裁剪', prompt: '', assetId: 'new-asset' } }] }));
    });
    fireEvent.click(screen.getByRole('menuitem', { name: '裁剪' }));
    const image = screen.getByAltText('裁剪预览');
    Object.defineProperty(image, 'naturalWidth', { value: 800 });
    Object.defineProperty(image, 'naturalHeight', { value: 600 });
    fireEvent.load(image);
    fireEvent.change(screen.getByLabelText('裁剪比例'), { target: { value: '1:1' } });
    fireEvent.click(screen.getByRole('button', { name: '裁剪为新节点' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(requests[0]).toMatchObject({ command: 'crop_image', payload: { sourceNodeId: 'image', sourceAssetId: 'asset', rect: { x: 100, y: 0, width: 600, height: 600 } } });
    expect(useCanvasStore.getState().snapshot?.nodes).toHaveLength(2);
    expect(useCanvasStore.getState().selectedNodeIds).toEqual(['cropped']);
    expect(useCanvasStore.getState().snapshot?.nodes[0].data.prompt).toBe('原提示词');
  });
  it('disables crop while generating', () => {
    setup(true);
    expect(screen.getByRole('menuitem', { name: '裁剪' })).toHaveAttribute('aria-disabled', 'true');
  });
  it('prevents saving when the source image changes', () => {
    setup();
    fireEvent.click(screen.getByRole('menuitem', { name: '裁剪' }));
    const image = screen.getByAltText('裁剪预览');
    Object.defineProperty(image, 'naturalWidth', { value: 800 });
    Object.defineProperty(image, 'naturalHeight', { value: 600 });
    fireEvent.load(image);
    fireEvent.change(screen.getByLabelText('裁剪比例'), { target: { value: '1:1' } });
    const snapshot = useCanvasStore.getState().snapshot!;
    act(() => useCanvasStore.setState({ snapshot: { ...snapshot, nodes: snapshot.nodes.map(n => ({ ...n, data: { ...n.data, assetId: 'changed' } })) } }));
    expect(screen.getByRole('button', { name: '裁剪为新节点' })).toBeDisabled();
  });
});
