import { create } from 'zustand';
import type { Edge, Node } from '@xyflow/react';

import { api } from '../api/client';
import type {
  CanvasEvent,
  CanvasNodeData,
  CanvasSnapshot,
  CommandEnvelope,
  CommandResult,
} from '../domain/types';


export interface CanvasState {
  canvasId: string | null;
  snapshot: CanvasSnapshot | null;
  selectedNodeIds: string[];
  showEdges: boolean;
  theme: 'light' | 'dark';
  isSaving: boolean;
  error: string | null;
  load: (canvasId: string) => Promise<void>;
  execute: (envelope: CommandEnvelope) => Promise<CommandResult | null>;
  applyEvent: (event: CanvasEvent) => void;
  selectNodes: (nodeIds: string[]) => void;
  setShowEdges: (showEdges: boolean) => void;
  setTheme: (theme: 'light' | 'dark') => void;
}


export function snapshotToReactFlow(snapshot: CanvasSnapshot): {
  nodes: Node<CanvasNodeData>[];
  edges: Edge[];
} {
  return {
    nodes: snapshot.nodes.map((node) => ({
      id: node.id,
      type: node.nodeType,
      position: { x: node.x, y: node.y },
      width: node.width,
      height: node.height,
      data: { ...node.data, nodeType: node.nodeType },
    })),
    edges: snapshot.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'reference',
    })),
  };
}


export function createCanvasStore(initialSnapshot: CanvasSnapshot | null = null) {
  return create<CanvasState>((set, get) => ({
    canvasId: initialSnapshot?.canvasId ?? null,
    snapshot: initialSnapshot,
    selectedNodeIds: [],
    showEdges: true,
    theme: 'dark',
    isSaving: false,
    error: null,

    async load(canvasId) {
      set({ isSaving: true, error: null });
      try {
        const snapshot = await api.getSnapshot(canvasId);
        set({
          canvasId,
          snapshot,
          selectedNodeIds: get().selectedNodeIds.filter((id) => snapshot.nodes.some((node) => node.id === id)),
          isSaving: false,
        });
      } catch (error) {
        set({ isSaving: false, error: error instanceof Error ? error.message : 'Failed to load canvas' });
        throw error;
      }
    },

    async execute(envelope) {
      const canvasId = get().canvasId;
      if (!canvasId || !get().snapshot) {
        return null;
      }
      set({ isSaving: true, error: null });
      try {
        const result = await api.executeCommand(canvasId, envelope);
        const snapshot = await api.getSnapshot(canvasId);
        set({
          snapshot,
          selectedNodeIds: get().selectedNodeIds.filter((id) => snapshot.nodes.some((node) => node.id === id)),
          isSaving: false,
        });
        return result;
      } catch (error) {
        set({ isSaving: false, error: error instanceof Error ? error.message : 'Command failed' });
        throw error;
      }
    },

    applyEvent(event) {
      const snapshot = get().snapshot;
      if (!snapshot || event.canvasId !== snapshot.canvasId || event.revision <= snapshot.revision) {
        return;
      }
      set({ snapshot: { ...snapshot, revision: event.revision } });
      void api.getSnapshot(snapshot.canvasId).then((freshSnapshot) => {
        const current = get().snapshot;
        if (current && freshSnapshot.revision >= current.revision) {
          set({
            snapshot: freshSnapshot,
            selectedNodeIds: get().selectedNodeIds.filter((id) => freshSnapshot.nodes.some((node) => node.id === id)),
          });
        }
      }).catch(() => {
        // The next SSE event or manual reload can repair a transient refresh failure.
      });
    },

    selectNodes(nodeIds) {
      const nextIds = [...new Set(nodeIds)];
      const currentIds = get().selectedNodeIds;
      if (nextIds.length !== currentIds.length || nextIds.some((id) => !currentIds.includes(id))) {
        set({ selectedNodeIds: nextIds });
      }
    },

    setShowEdges(showEdges) {
      set({ showEdges });
    },

    setTheme(theme) {
      set({ theme });
    },
  }));
}


export const useCanvasStore = createCanvasStore();
