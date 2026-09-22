import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import {
  addEdge,
  applyNodeChanges,
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  type OnSelectionChangeParams,
  type Viewport,
} from '@xyflow/react';

import { canConnect } from '../domain/connectionRules';
import { api } from '../api/client';
import type {
  CanvasNodeData,
  ImageGenerationParameters,
  NodeType,
  VideoGenerationParameters,
} from '../domain/types';
import { ImageNode } from '../nodes/ImageNode';
import { NoteNode } from '../nodes/NoteNode';
import { VideoNode } from '../nodes/VideoNode';
import { ReferenceEdge, getVisibleEdgeIds } from '../edges/ReferenceEdge';
import { snapshotToReactFlow, useCanvasStore } from '../state/canvasStore';
import { CanvasToolbar } from './CanvasToolbar';
import { ConnectionChooser } from './ConnectionChooser';


const nodeTypes = { image: ImageNode, video: VideoNode, note: NoteNode };
const edgeTypes = { reference: ReferenceEdge };


function commandKey(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}


export function CanvasShell() {
  const {
    snapshot,
    canvasId,
    selectedNodeId,
    showEdges,
    theme,
    isSaving,
    selectNode,
    setShowEdges,
    setTheme,
    execute,
    applyEvent,
  } = useCanvasStore();
  const [nodes, setNodes] = useState<Node<CanvasNodeData>[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [connectionStart, setConnectionStart] = useState<string | null>(null);
  const [chooserPosition, setChooserPosition] = useState<{ x: number; y: number } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadTargetRef = useRef<string | null>(null);

  useEffect(() => {
    if (!snapshot) {
      setNodes([]);
      setEdges([]);
      return;
    }
    const flow = snapshotToReactFlow(snapshot);
    const assetUrl = (nodeId: string) => {
      const assetId = snapshot.nodes.find((node) => node.id === nodeId)?.data.assetId;
      return typeof assetId === 'string' ? `/api/assets/${encodeURIComponent(assetId)}/file` : undefined;
    };
    const referencesFor = (nodeId: string) => snapshot.edges
      .filter((edge) => edge.target === nodeId)
      .map((edge) => assetUrl(edge.source))
      .filter((url): url is string => Boolean(url));
    const generationFor = (nodeId: string) => snapshot.jobs?.find((job) => (
      job.targetNodeId === nodeId || job.target_node_id === nodeId
    ));
    setNodes(flow.nodes.map((node) => ({
      ...node,
      selected: node.id === selectedNodeId,
      data: {
        ...node.data,
        assetUrl: assetUrl(node.id),
        references: referencesFor(node.id),
        generationStatus: generationFor(node.id)?.status,
        onUpload: () => {
          uploadTargetRef.current = node.id;
          fileInputRef.current?.click();
        },
        onPromptChange: (prompt: string) => {
          void persistNodeData(node.id, { prompt });
        },
        onParametersChange: (parameters: ImageGenerationParameters | VideoGenerationParameters) => {
          void persistNodeData(node.id, { parameters });
        },
        onGenerateRequest: (request: {
          prompt: string;
          parameters: ImageGenerationParameters | VideoGenerationParameters;
        }) => {
          void startGeneration(node.id, request);
        },
        onRemoveReference: (url: string) => {
          const edge = snapshot.edges.find((candidate) => (
            candidate.target === node.id && assetUrl(candidate.source) === url
          ));
          if (edge) {
            void execute({
              command: 'disconnect_nodes',
              baseRevision: useCanvasStore.getState().snapshot?.revision ?? snapshot.revision,
              idempotencyKey: commandKey('disconnect-edge'),
              payload: { edgeId: edge.id },
            });
          }
        },
        onResize: (size: { width: number; height: number }) => {
          void persistNodeSize(node.id, size);
        },
      },
    })));
    setEdges(flow.edges);
  }, [snapshot]);

  useEffect(() => {
    if (!canvasId || !snapshot) {
      return;
    }
    return api.subscribeEvents(canvasId, snapshot.revision, applyEvent);
  }, [canvasId, applyEvent]);

  const visibleEdges = useMemo(
    () => edges.map((edge) => ({
      ...edge,
      hidden: !getVisibleEdgeIds(edges, selectedNodeId, showEdges).has(edge.id),
    })),
    [edges, selectedNodeId, showEdges],
  );

  async function addNode(nodeType: NodeType) {
    if (!snapshot) return;
    const offset = 140 + snapshot.nodes.length * 24;
    await execute({
      command: 'create_node',
      baseRevision: snapshot.revision,
      idempotencyKey: commandKey('create-node'),
      payload: { nodeType, x: offset, y: offset },
    });
  }

  async function persistNodeData(nodeId: string, data: Record<string, unknown>) {
    const current = useCanvasStore.getState().snapshot;
    if (!current) return;
    await execute({
      command: 'update_node',
      baseRevision: current.revision,
      idempotencyKey: commandKey('update-node-data'),
      payload: { nodeId, data },
    });
  }

  async function persistNodeSize(nodeId: string, size: { width: number; height: number }) {
    const current = useCanvasStore.getState().snapshot;
    if (!current) return;
    await execute({
      command: 'update_node',
      baseRevision: current.revision,
      idempotencyKey: commandKey('resize-node'),
      payload: { nodeId, width: size.width, height: size.height },
    });
  }

  async function startGeneration(
    nodeId: string,
    request: {
      prompt: string;
      parameters: ImageGenerationParameters | VideoGenerationParameters;
    },
  ) {
    const current = useCanvasStore.getState().snapshot;
    if (!current) return;
    await execute({
      command: 'start_generation',
      baseRevision: current.revision,
      idempotencyKey: commandKey('start-generation'),
      payload: { targetNodeId: nodeId, prompt: request.prompt, parameters: request.parameters },
    });
  }

  async function onMoveEnd(_: MouseEvent | TouchEvent | null, viewport: Viewport) {
    const current = useCanvasStore.getState().snapshot;
    if (!current) return;
    await execute({
      command: 'update_canvas',
      baseRevision: current.revision,
      idempotencyKey: commandKey('update-viewport'),
      payload: { viewport },
    });
  }

  function onNodesChange(changes: NodeChange[]) {
    setNodes((current) => applyNodeChanges(changes, current) as Node<CanvasNodeData>[]);
  }

  async function onNodeDragStop(_: MouseEvent | TouchEvent, node: Node) {
    if (!snapshot) return;
    await execute({
      command: 'update_node',
      baseRevision: useCanvasStore.getState().snapshot?.revision ?? snapshot.revision,
      idempotencyKey: commandKey('move-node'),
      payload: { nodeId: node.id, x: node.position.x, y: node.position.y },
    });
  }

  async function onConnect(connection: Connection) {
    if (!snapshot || !connection.source || !connection.target) return;
    const source = snapshot.nodes.find((node) => node.id === connection.source);
    const target = snapshot.nodes.find((node) => node.id === connection.target);
    if (!source || !target || !canConnect(source.nodeType, target.nodeType)) return;
    const edgeId = commandKey('edge');
    const result = await execute({
      command: 'connect_nodes',
      baseRevision: useCanvasStore.getState().snapshot?.revision ?? snapshot.revision,
      idempotencyKey: edgeId,
      payload: { edgeId, sourceNodeId: source.id, targetNodeId: target.id },
    });
    if (result) {
      setEdges((current) => addEdge({ id: edgeId, source: source.id, target: target.id, type: 'reference' }, current));
    }
    setConnectionStart(null);
  }

  function onConnectStart(_: MouseEvent | TouchEvent, params: { nodeId: string | null }) {
    setConnectionStart(params.nodeId);
  }

  function onConnectEnd(event: MouseEvent | TouchEvent) {
    if (!connectionStart) return;
    const target = event.target as Element | null;
    if (target?.closest('.react-flow__node')) {
      setConnectionStart(null);
      return;
    }
    const point = 'clientX' in event
      ? { x: event.clientX, y: event.clientY }
      : { x: event.changedTouches[0]?.clientX ?? 0, y: event.changedTouches[0]?.clientY ?? 0 };
    setChooserPosition(point);
  }

  async function createNodeFromChooser(nodeType: Extract<NodeType, 'image' | 'video'>) {
    if (!snapshot || !connectionStart || !chooserPosition) return;
    const nodeResult = await execute({
      command: 'create_node',
      baseRevision: useCanvasStore.getState().snapshot?.revision ?? snapshot.revision,
      idempotencyKey: commandKey('chooser-node'),
      payload: { nodeType, x: chooserPosition.x, y: chooserPosition.y },
    });
    const nodeId = nodeResult?.payload.nodeId;
    if (typeof nodeId !== 'string') return;
    const edgeId = commandKey('chooser-edge');
    await execute({
      command: 'connect_nodes',
      baseRevision: useCanvasStore.getState().snapshot?.revision ?? snapshot.revision,
      idempotencyKey: edgeId,
      payload: { edgeId, sourceNodeId: connectionStart, targetNodeId: nodeId },
    });
    setConnectionStart(null);
    setChooserPosition(null);
  }

  async function onFileSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    const nodeId = uploadTargetRef.current;
    if (!file || !nodeId || !canvasId) return;
    const asset = await api.uploadAsset(canvasId, file);
    await execute({
      command: 'attach_asset',
      baseRevision: useCanvasStore.getState().snapshot?.revision ?? snapshot?.revision ?? 0,
      idempotencyKey: commandKey('attach-asset'),
      payload: { nodeId, assetId: asset.id },
    });
    const latest = useCanvasStore.getState().snapshot;
    const target = latest?.nodes.find((node) => node.id === nodeId);
    if (target?.nodeType === 'video' && asset.width && asset.height) {
      const width = target.width ?? 360;
      await execute({
        command: 'update_node',
        baseRevision: useCanvasStore.getState().snapshot?.revision ?? latest?.revision ?? 0,
        idempotencyKey: commandKey('fit-video-ratio'),
        payload: { nodeId, width, height: Math.round(width * asset.height / asset.width) },
      });
    }
    event.target.value = '';
  }

  function onSelectionChange(selection: OnSelectionChangeParams) {
    selectNode(selection.nodes[0]?.id ?? null);
  }

  return (
    <div className={`canvas-page theme-${theme}`}>
      <CanvasToolbar
        theme={theme}
        showEdges={showEdges}
        isSaving={isSaving}
        onThemeChange={setTheme}
        onEdgesChange={setShowEdges}
        onAddNode={addNode}
      />
      <div className="canvas-viewport" data-testid="canvas-shell">
        <input ref={fileInputRef} type="file" hidden onChange={(event) => void onFileSelected(event)} />
        <ReactFlow
          nodes={nodes}
          edges={visibleEdges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          defaultViewport={snapshot?.viewport ?? { x: 0, y: 0, zoom: 1 }}
          onNodesChange={onNodesChange}
          onNodeDragStop={onNodeDragStop}
          onConnect={onConnect}
          onConnectStart={onConnectStart}
          onConnectEnd={onConnectEnd}
          onSelectionChange={onSelectionChange}
          onMoveEnd={onMoveEnd}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} size={1} />
          <Controls position="bottom-right" />
          <MiniMap position="bottom-left" pannable zoomable />
        </ReactFlow>
        {chooserPosition && (
          <ConnectionChooser position={chooserPosition} onCreate={(type) => void createNodeFromChooser(type)} />
        )}
      </div>
    </div>
  );
}
