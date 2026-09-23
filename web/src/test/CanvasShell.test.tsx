import { act, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Edge, Node } from '@xyflow/react';

import { api } from '../api/client';
import { CanvasShell } from '../canvas/CanvasShell';
import type { CanvasSnapshot } from '../domain/types';
import { useCanvasStore } from '../state/canvasStore';


let deleteSelection: ((selection: { nodes: Node[]; edges: Edge[] }) => Promise<boolean>) | undefined;

vi.mock('@xyflow/react', async (importOriginal) => {
  const original = await importOriginal<typeof import('@xyflow/react')>();
  return {
    ...original,
    ReactFlow: ({ onBeforeDelete }: { onBeforeDelete: typeof deleteSelection }) => {
      deleteSelection = onBeforeDelete;
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
