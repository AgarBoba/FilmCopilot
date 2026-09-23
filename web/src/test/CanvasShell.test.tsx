import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Edge, Node } from '@xyflow/react';

import { api } from '../api/client';
import { CanvasShell } from '../canvas/CanvasShell';
import type { CanvasSnapshot } from '../domain/types';
import { useCanvasStore } from '../state/canvasStore';


let deleteSelection: ((selection: { nodes: Node[]; edges: Edge[] }) => Promise<boolean>) | undefined;
type ConnectEnd = (event: MouseEvent, state: Record<string, unknown>) => void;
let connectEnd: ConnectEnd | undefined;

vi.mock('@xyflow/react', async (importOriginal) => {
  const original = await importOriginal<typeof import('@xyflow/react')>();
  return {
    ...original,
    ReactFlow: ({ onBeforeDelete, onConnectEnd }: { onBeforeDelete: typeof deleteSelection; onConnectEnd: ConnectEnd }) => {
      deleteSelection = onBeforeDelete;
      connectEnd = onConnectEnd;
      return <div data-testid="mock-flow" />;
    },
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
  };
});

const originalState = useCanvasStore.getState();

afterEach(() => {
  vi.restoreAllMocks();
  useCanvasStore.setState(originalState, true);
  deleteSelection = undefined;
  connectEnd = undefined;
});

describe('canvas deletion', () => {
  it('persists a node deletion before React Flow removes anything locally', async () => {
    const original: CanvasSnapshot = {
      canvasId: 'canvas-1',
      name: 'Test',
      revision: 1,
      viewport: { x: 0, y: 0, zoom: 1 },
      nodes: [{ id: 'image-1', nodeType: 'image', x: 0, y: 0, data: { title: 'Image', prompt: '' } }],
      edges: [],
    };
    const saved: CanvasSnapshot = { ...original, revision: 2, nodes: [] };
    useCanvasStore.setState({ canvasId: 'canvas-1', snapshot: original, selectedNodeIds: ['image-1'] });
    vi.spyOn(api, 'subscribeEvents').mockReturnValue(() => {});
    const command = vi.spyOn(api, 'executeCommand').mockResolvedValue({
      revision: 2,
      command: 'delete_elements',
      payload: { nodeIds: ['image-1'], edgeIds: [] },
    });
    vi.spyOn(api, 'getSnapshot').mockResolvedValue(saved);

    render(<CanvasShell />);
    let localDeletionAllowed: boolean | undefined;
    await act(async () => {
      localDeletionAllowed = await deleteSelection?.({ nodes: [{ id: 'image-1' } as Node], edges: [] });
    });

    expect(localDeletionAllowed).toBe(false);
    expect(command).toHaveBeenCalledWith('canvas-1', expect.objectContaining({
      command: 'delete_elements',
      baseRevision: 1,
      payload: { nodeIds: ['image-1'], edgeIds: [] },
    }));
    expect(useCanvasStore.getState().snapshot?.nodes).toEqual([]);
    expect(useCanvasStore.getState().selectedNodeIds).toEqual([]);
  });
});


describe('connection chooser', () => {
  const snapshot: CanvasSnapshot = {
    canvasId: 'canvas-1',
    name: 'Test',
    revision: 1,
    viewport: { x: 0, y: 0, zoom: 1 },
    nodes: [
      { id: 'image-1', nodeType: 'image', x: 0, y: 0, data: { title: 'Image', prompt: '' } },
      { id: 'video-1', nodeType: 'video', x: 400, y: 0, data: { title: 'Video', prompt: '' } },
    ],
    edges: [],
  };

  function setup() {
    useCanvasStore.setState({ canvasId: 'canvas-1', snapshot, selectedNodeIds: [] });
    vi.spyOn(api, 'subscribeEvents').mockReturnValue(() => {});
    vi.spyOn(api, 'getSnapshot').mockResolvedValue(snapshot);
    render(<CanvasShell />);
  }

  function dropInEmptySpace(fromNodeId: string, handleType: 'source' | 'target', isValid = false) {
    act(() => {
      connectEnd?.(
        new MouseEvent('mouseup', { clientX: 300, clientY: 200 }),
        { fromNode: { id: fromNodeId }, fromHandle: { type: handleType }, isValid, toNode: null },
      );
    });
  }

  it('closes when clicking outside the menu', () => {
    setup();
    dropInEmptySpace('image-1', 'source');
    expect(screen.getByRole('menu')).toBeTruthy();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('closes on Escape', () => {
    setup();
    dropInEmptySpace('image-1', 'source');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('does not open when the drop snapped to a valid port', () => {
    setup();
    dropInEmptySpace('image-1', 'source', true);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('only offers node types that can connect in the dragged direction', () => {
    setup();
    // Out of a video node's output: only video accepts video references.
    dropInEmptySpace('video-1', 'source');
    expect(screen.getAllByRole('menuitem').map((item) => item.textContent)).toEqual(['视频节点']);
  });

  it('creates an upstream node when dragged out of an input port', async () => {
    setup();
    const command = vi.spyOn(api, 'executeCommand')
      .mockResolvedValueOnce({ revision: 2, command: 'create_node', payload: { nodeId: 'new-image' } })
      .mockResolvedValueOnce({ revision: 3, command: 'connect_nodes', payload: {} });
    dropInEmptySpace('video-1', 'target');
    await act(async () => {
      fireEvent.click(screen.getByRole('menuitem', { name: '图片节点' }));
    });
    expect(screen.queryByRole('menu')).toBeNull();
    const connect = command.mock.calls.find(([, body]) => body.command === 'connect_nodes')?.[1];
    expect(connect?.payload).toMatchObject({ sourceNodeId: 'new-image', targetNodeId: 'video-1' });
  });
});
