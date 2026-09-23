import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  MiniMap,
  Panel,
  PanOnScrollMode,
  ReactFlow,
  SelectionMode,
  type Connection,
  type Edge,
  type EdgeChange,
  type FinalConnectionState,
  type HandleType,
  type Node,
  type NodeChange,
  type OnConnectStartParams,
  type OnSelectionChangeParams,
  type ReactFlowInstance,
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
import type { NodeReference } from '../nodes/ReferenceStrip';
import { VideoNode } from '../nodes/VideoNode';
import { ReferenceEdge, getVisibleEdgeIds } from '../edges/ReferenceEdge';
import { snapshotToReactFlow, useCanvasStore } from '../state/canvasStore';
import { CanvasControls, type CanvasTool } from './CanvasControls';
import { CanvasRail } from './CanvasRail';
import { TooltipLayer } from './TooltipLayer';
import { CANVAS_MAX_ZOOM, CANVAS_MIN_ZOOM, useTrackpadGestures } from './useTrackpadGestures';
import { ConnectionChooser, type ChooserNodeType } from './ConnectionChooser';


const nodeTypes = { image: ImageNode, video: VideoNode, note: NoteNode };
const edgeTypes = { reference: ReferenceEdge };
const CHOOSER_NODE_TYPES: ChooserNodeType[] = ['image', 'video'];
// Rough node width, used to place a new upstream node so it ends at the drop point.
const NEW_NODE_WIDTH = 280;
const NEW_NODE_HEIGHT = 440;
const NODE_GAP = 40;
const DUPLICATE_OFFSET = 40;
const GHOST_PREFIX = 'ghost:';
const NODE_TYPE_LABELS: Record<NodeType, string> = { image: '图片', video: '视频', note: '便签' };

/** Default name for a new node: "图片 3" = one more than the highest number already used. */
function defaultNodeTitle(nodeType: NodeType): string {
  const label = NODE_TYPE_LABELS[nodeType];
  const pattern = new RegExp(`^${label} (\\d+)$`);
  const used = (useCanvasStore.getState().snapshot?.nodes ?? [])
    .filter((node) => node.nodeType === nodeType)
    .map((node) => Number(pattern.exec(String(node.data?.title ?? ''))?.[1] ?? 0));
  return `${label} ${Math.max(0, ...used) + 1}`;
}

interface PendingConnection {
  /** Node the connection was dragged out of. */
  nodeId: string;
  /** Which port it came from: 'source' (right) means the new node is downstream. */
  handleType: HandleType;
  /** Drop point in screen coordinates, for the menu. */
  screen: { x: number; y: number };
  /** Drop point in canvas coordinates, for the new node. */
  flow: { x: number; y: number };
  options: ChooserNodeType[];
}


function commandKey(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}


export function CanvasShell() {
  const {
    snapshot,
    canvasId,
    selectedNodeIds,
    showEdges,
    theme,
    isSaving,
    error,
    selectNodes,
    setShowEdges,
    setTheme,
    execute,
    applyEvent,
  } = useCanvasStore();
  const [nodes, setNodes] = useState<Node<CanvasNodeData>[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [pendingConnection, setPendingConnection] = useState<PendingConnection | null>(null);
  const flowRef = useRef<Pick<ReactFlowInstance, 'screenToFlowPosition' | 'getNodes' | 'getViewport' | 'setViewport'> | null>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const viewportSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useTrackpadGestures(viewportRef, flowRef);
  const closeChooser = useCallback(() => setPendingConnection(null), []);
  const [tool, setTool] = useState<CanvasTool>('select');
  const [spaceHeld, setSpaceHeld] = useState(false);
  const [altHeld, setAltHeld] = useState(false);
  /** Set while an Option/Alt-drag is making copies: where the originals started. */
  const altDragRef = useRef<Map<string, { x: number; y: number }> | null>(null);
  const duplicateRef = useRef<(nodeIds: string[]) => void>(() => undefined);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadTargetRef = useRef<string | null>(null);
  const deletionPendingRef = useRef(false);
  const selectionBeforePointerRef = useRef<string[]>([]);
  const activeTool = spaceHeld ? 'hand' : tool;

  // Switching to the hand tool (H / Space) closes the chooser.
  useEffect(() => {
    if (activeTool !== 'select') setPendingConnection(null);
  }, [activeTool]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Alt') setAltHeld(true);
      const target = event.target;
      if (
        target instanceof Element
        && target.closest('input, textarea, select, [contenteditable="true"]')
      ) return;
      // Cmd/Ctrl + D duplicates the selected nodes (and stops the browser's bookmark shortcut).
      if ((event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === 'd') {
        event.preventDefault();
        duplicateRef.current(useCanvasStore.getState().selectedNodeIds);
        return;
      }
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (event.code === 'Space') {
        if (target instanceof Element && target.closest('button')) return;
        event.preventDefault();
        setSpaceHeld(true);
      } else if (event.key.toLowerCase() === 'v') {
        setTool('select');
      } else if (event.key.toLowerCase() === 'h') {
        setTool('hand');
      }
    }
    function onKeyUp(event: KeyboardEvent) {
      if (event.code === 'Space') setSpaceHeld(false);
      if (event.key === 'Alt') setAltHeld(false);
    }
    function onWindowBlur() {
      setSpaceHeld(false);
      setAltHeld(false);
    }
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', onWindowBlur);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      window.removeEventListener('blur', onWindowBlur);
    };
  }, []);

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
    // Every upstream image/video node, including ones with no content yet (shown as empty).
    const referencesFor = (nodeId: string): NodeReference[] => snapshot.edges
      .filter((edge) => edge.target === nodeId)
      .flatMap((edge): NodeReference[] => {
        const source = snapshot.nodes.find((candidate) => candidate.id === edge.source);
        if (!source) return [];
        if (source.nodeType === 'note') {
          const text = source.data?.content ?? source.data?.prompt;
          return [{
            edgeId: edge.id,
            kind: 'note' as const,
            text: typeof text === 'string' ? text : '',
            title: typeof source.data?.title === 'string' ? source.data.title : undefined,
          }];
        }
        if (source.nodeType !== 'image' && source.nodeType !== 'video') return [];
        return [{
          edgeId: edge.id,
          url: assetUrl(source.id),
          kind: source.nodeType,
          title: typeof source.data?.title === 'string' ? source.data.title : undefined,
        }];
      });
    // Jobs come oldest first; a node shows its most recent one.
    const generationFor = (nodeId: string) => snapshot.jobs?.filter((job) => (
      job.targetNodeId === nodeId || job.target_node_id === nodeId
    )).at(-1);
    setNodes(flow.nodes.map((node) => ({
      ...node,
      // Read the latest selection: a duplicate selects its copies before they arrive.
      selected: useCanvasStore.getState().selectedNodeIds.includes(node.id),
      data: {
        ...node.data,
        assetUrl: assetUrl(node.id),
        references: referencesFor(node.id),
        generationStatus: generationFor(node.id)?.status as string | undefined,
        generationError: generationFor(node.id)?.error as string | undefined,
        onUpload: () => {
          uploadTargetRef.current = node.id;
          fileInputRef.current?.click();
        },
        onDuplicate: () => duplicateRef.current([node.id]),
        onTitleChange: (title: string) => {
          void persistNodeData(node.id, { title });
        },
        onChange: (content: string) => {
          void persistNodeData(node.id, { content });
        },
        onStyleChange: (changes: { fontFamily?: string; fontSize?: number }) => {
          void persistNodeData(node.id, changes);
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
        onRemoveReference: (reference: NodeReference) => {
          if (!reference.edgeId) return;
          void execute({
            command: 'disconnect_nodes',
            baseRevision: useCanvasStore.getState().snapshot?.revision ?? snapshot.revision,
            idempotencyKey: commandKey('disconnect-edge'),
            payload: { edgeId: reference.edgeId },
          });
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

  const visibleEdges = useMemo(() => {
    const visibleIds = getVisibleEdgeIds(edges, selectedNodeIds, showEdges);
    return edges.map((edge) => ({ ...edge, hidden: !visibleIds.has(edge.id) }));
  }, [edges, selectedNodeIds, showEdges]);

  /**
   * Where a new node should go: centred in the visible canvas; if that spot is taken,
   * step right (then down) until it no longer overlaps an existing node.
   */
  function nextNodePosition() {
    const viewport = viewportRef.current?.getBoundingClientRect();
    const screenCenter = viewport
      ? { x: viewport.left + viewport.width / 2, y: viewport.top + viewport.height / 2 }
      : { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    const center = flowRef.current?.screenToFlowPosition(screenCenter) ?? { x: 140, y: 140 };
    const size = { width: NEW_NODE_WIDTH, height: NEW_NODE_HEIGHT };
    const origin = { x: center.x - size.width / 2, y: center.y - size.height / 2 };
    const boxes = (flowRef.current?.getNodes() ?? []).map((node) => ({
      x: node.position.x,
      y: node.position.y,
      width: node.measured?.width ?? node.width ?? NEW_NODE_WIDTH,
      height: node.measured?.height ?? node.height ?? NEW_NODE_HEIGHT,
    }));
    const overlaps = (x: number, y: number) => boxes.some((box) => (
      x < box.x + box.width + NODE_GAP && x + size.width + NODE_GAP > box.x
      && y < box.y + box.height + NODE_GAP && y + size.height + NODE_GAP > box.y
    ));
    // Scan right in small steps so the new node lands right next to its neighbour.
    for (let row = 0; row < 6; row += 1) {
      const y = origin.y + row * (size.height + NODE_GAP);
      for (let x = origin.x; x < origin.x + 40 * size.width; x += NODE_GAP / 2) {
        if (!overlaps(x, y)) return { x: Math.round(x), y: Math.round(y) };
      }
    }
    return { x: Math.round(origin.x), y: Math.round(origin.y) };
  }

  async function addNode(nodeType: NodeType) {
    const current = useCanvasStore.getState().snapshot;
    if (!current) return undefined;
    const result = await execute({
      command: 'create_node',
      baseRevision: current.revision,
      idempotencyKey: commandKey('create-node'),
      payload: { nodeType, title: defaultNodeTitle(nodeType), ...nextNodePosition() },
    });
    const nodeId = result?.payload.nodeId;
    return typeof nodeId === 'string' ? nodeId : undefined;
  }

  /** Upload from the left rail: no target node yet, the file type decides image vs video. */
  function requestUploadAsNewNode() {
    uploadTargetRef.current = null;
    fileInputRef.current?.click();
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

  // Trackpad panning ends many small moves in a row; save the viewport once it settles.
  function onMoveEnd(_: MouseEvent | TouchEvent | null, viewport: Viewport) {
    if (viewportSaveTimerRef.current) clearTimeout(viewportSaveTimerRef.current);
    viewportSaveTimerRef.current = setTimeout(() => {
      const current = useCanvasStore.getState().snapshot;
      if (!current) return;
      void execute({
        command: 'update_canvas',
        baseRevision: current.revision,
        idempotencyKey: commandKey('update-viewport'),
        payload: { viewport },
      }).catch(() => undefined);
    }, 600);
  }

  function onNodesChange(changes: NodeChange[]) {
    setNodes((current) => applyNodeChanges(changes, current) as Node<CanvasNodeData>[]);
  }

  function onEdgesChange(changes: EdgeChange[]) {
    setEdges((current) => applyEdgeChanges(changes, current));
  }

  async function onBeforeDelete({ nodes: deletingNodes, edges: deletingEdges }: {
    nodes: Node[];
    edges: Edge[];
  }): Promise<boolean> {
    const current = useCanvasStore.getState().snapshot;
    if (!current || deletionPendingRef.current || (!deletingNodes.length && !deletingEdges.length)) {
      return false;
    }
    deletionPendingRef.current = true;
    try {
      await execute({
        command: 'delete_elements',
        baseRevision: current.revision,
        idempotencyKey: commandKey('delete-elements'),
        payload: {
          nodeIds: deletingNodes.map((node) => node.id),
          edgeIds: deletingEdges.map((edge) => edge.id),
        },
      });
    } catch {
      // The store exposes the save error and the nodes stay in place.
    } finally {
      deletionPendingRef.current = false;
    }
    return false;
  }

  /** Copy nodes to the given positions, then select the copies. */
  async function duplicateNodes(items: { sourceNodeId: string; x: number; y: number }[]) {
    const current = useCanvasStore.getState().snapshot;
    if (!current || !items.length) return;
    // Ids are made here so the copies can be selected the moment they appear.
    const nodes = items.map((item) => ({
      ...item,
      nodeId: crypto.randomUUID(),
      x: Math.round(item.x),
      y: Math.round(item.y),
    }));
    const previousSelection = useCanvasStore.getState().selectedNodeIds;
    selectNodes(nodes.map((item) => item.nodeId));
    const result = await execute({
      command: 'duplicate_nodes',
      baseRevision: current.revision,
      idempotencyKey: commandKey('duplicate-nodes'),
      payload: { nodes },
    }).catch(() => null);
    if (!result) selectNodes(previousSelection);
  }

  /** Cmd/Ctrl + D and the node menu: copies land slightly down and to the right. */
  duplicateRef.current = (nodeIds: string[]) => {
    const current = useCanvasStore.getState().snapshot;
    if (!current) return;
    const items = nodeIds.flatMap((id) => {
      const node = current.nodes.find((candidate) => candidate.id === id);
      return node ? [{ sourceNodeId: id, x: node.x + DUPLICATE_OFFSET, y: node.y + DUPLICATE_OFFSET }] : [];
    });
    void duplicateNodes(items);
  };

  /**
   * Option/Alt + drag: the dragged node becomes the copy. A see-through "ghost" stays
   * where the original was, and on drop the original snaps back and a copy is saved there.
   */
  function onNodeDragStart(event: React.MouseEvent | MouseEvent | TouchEvent, node: Node<CanvasNodeData>, draggedNodes: Node<CanvasNodeData>[]) {
    if (!('altKey' in event) || !event.altKey || activeTool !== 'select') return;
    const dragged = draggedNodes.length ? draggedNodes : [node];
    altDragRef.current = new Map(dragged.map((item) => [item.id, { ...item.position }]));
    const ghosts = dragged.map((item): Node<CanvasNodeData> => ({
      ...item,
      id: `${GHOST_PREFIX}${item.id}`,
      selected: false,
      dragging: false,
      draggable: false,
      selectable: false,
      connectable: false,
      deletable: false,
      focusable: false,
      className: 'is-duplicate-ghost',
    }));
    setNodes((current) => [...ghosts, ...current]);
  }

  async function onNodeDragStop(_: MouseEvent | TouchEvent, node: Node, draggedNodes: Node[]) {
    const current = useCanvasStore.getState().snapshot;
    if (!current) return;
    const moved = draggedNodes.length ? draggedNodes : [node];
    const origins = altDragRef.current;
    if (origins) {
      altDragRef.current = null;
      // Put the originals back and drop the ghosts; the copies arrive with the saved snapshot.
      setNodes((items) => items
        .filter((item) => !item.id.startsWith(GHOST_PREFIX))
        .map((item) => (origins.has(item.id) ? { ...item, position: origins.get(item.id)! } : item)));
      await duplicateNodes(moved.map((item) => ({ sourceNodeId: item.id, x: item.position.x, y: item.position.y })));
      return;
    }
    await execute({
      command: moved.length > 1 ? 'move_nodes' : 'update_node',
      baseRevision: current.revision,
      idempotencyKey: commandKey('move-node'),
      payload: moved.length > 1
        ? { positions: moved.map((item) => ({ nodeId: item.id, x: item.position.x, y: item.position.y })) }
        : { nodeId: node.id, x: node.position.x, y: node.position.y },
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
  }

  function onConnectStart(_: MouseEvent | TouchEvent, _params: OnConnectStartParams) {
    setPendingConnection(null);
  }

  function onConnectEnd(event: MouseEvent | TouchEvent, state: FinalConnectionState) {
    const fromNodeId = state.fromNode?.id;
    const handleType = state.fromHandle?.type;
    if (!fromNodeId || !handleType) return;
    // Snapped to a port (valid or not), or dropped on a node: onConnect handles it, no menu.
    if (state.isValid || state.toNode) return;
    const target = event.target as Element | null;
    if (target?.closest('.react-flow__node')) return;

    const fromNode = useCanvasStore.getState().snapshot?.nodes.find((node) => node.id === fromNodeId);
    if (!fromNode) return;
    const options = CHOOSER_NODE_TYPES.filter((nodeType) => (
      handleType === 'source'
        ? canConnect(fromNode.nodeType, nodeType)
        : canConnect(nodeType, fromNode.nodeType)
    ));
    if (!options.length) return;

    const screen = 'clientX' in event
      ? { x: event.clientX, y: event.clientY }
      : { x: event.changedTouches[0]?.clientX ?? 0, y: event.changedTouches[0]?.clientY ?? 0 };
    const flow = flowRef.current?.screenToFlowPosition(screen) ?? screen;
    setPendingConnection({ nodeId: fromNodeId, handleType, screen, flow, options });
  }

  async function createNodeFromChooser(nodeType: ChooserNodeType) {
    const pending = pendingConnection;
    if (!snapshot || !pending) return;
    // Close right away so a slow or failed save never leaves the menu stuck open.
    setPendingConnection(null);
    const x = pending.handleType === 'source' ? pending.flow.x : pending.flow.x - NEW_NODE_WIDTH;
    const nodeResult = await execute({
      command: 'create_node',
      baseRevision: useCanvasStore.getState().snapshot?.revision ?? snapshot.revision,
      idempotencyKey: commandKey('chooser-node'),
      payload: { nodeType, title: defaultNodeTitle(nodeType), x, y: pending.flow.y },
    });
    const nodeId = nodeResult?.payload.nodeId;
    if (typeof nodeId !== 'string') return;
    const edgeId = commandKey('chooser-edge');
    const [sourceNodeId, targetNodeId] = pending.handleType === 'source'
      ? [pending.nodeId, nodeId]
      : [nodeId, pending.nodeId];
    await execute({
      command: 'connect_nodes',
      baseRevision: useCanvasStore.getState().snapshot?.revision ?? snapshot.revision,
      idempotencyKey: edgeId,
      payload: { edgeId, sourceNodeId, targetNodeId },
    });
  }

  async function onFileSelected(event: ChangeEvent<HTMLInputElement>) {
    const input = event.target;
    const file = input.files?.[0];
    // Reset now so picking the same file again still fires onChange.
    input.value = '';
    if (!file || !canvasId) return;
    try {
      const asset = await api.uploadAsset(canvasId, file);
      // From the rail there is no target node: create one matching what was uploaded.
      const nodeId = uploadTargetRef.current ?? await addNode(asset.kind);
      if (!nodeId) return;
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
    } catch (uploadError) {
      useCanvasStore.setState({
        error: uploadError instanceof Error ? `上传失败：${uploadError.message}` : '上传失败',
      });
    } finally {
      uploadTargetRef.current = null;
    }
  }

  function onSelectionChange(selection: OnSelectionChangeParams) {
    selectNodes(selection.nodes.map((node) => node.id));
  }

  function onNodeClick(event: React.MouseEvent, node: Node) {
    if (activeTool !== 'select') return;
    if (!event.shiftKey && !event.metaKey && !event.ctrlKey) return;
    const previous = selectionBeforePointerRef.current;
    const next = previous.includes(node.id)
      ? previous.filter((id) => id !== node.id)
      : [...previous, node.id];
    setNodes((current) => current.map((item) => ({ ...item, selected: next.includes(item.id) })));
    selectNodes(next);
  }

  return (
    <div className={`canvas-page theme-${theme} mode-${activeTool} ${altHeld ? 'is-alt-held' : ''}`}>
      <div
        ref={viewportRef}
        className="canvas-viewport"
        data-testid="canvas-shell"
        onPointerDownCapture={(event) => {
          if ((event.target as Element).closest('.react-flow__node')) {
            selectionBeforePointerRef.current = useCanvasStore.getState().selectedNodeIds;
          }
        }}
      >
        <input ref={fileInputRef} type="file" accept="image/*,video/*" hidden onChange={(event) => void onFileSelected(event)} />
        <ReactFlow
          nodes={nodes}
          edges={visibleEdges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          defaultViewport={snapshot?.viewport ?? { x: 0, y: 0, zoom: 1 }}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onBeforeDelete={onBeforeDelete}
          onNodeDragStart={onNodeDragStart}
          onNodeDragStop={onNodeDragStop}
          onNodeClick={onNodeClick}
          onConnect={onConnect}
          onConnectStart={onConnectStart}
          onConnectEnd={onConnectEnd}
          onInit={(instance) => { flowRef.current = instance; }}
          onMoveStart={closeChooser}
          connectionRadius={40}
          onSelectionChange={onSelectionChange}
          onMoveEnd={onMoveEnd}
          panOnDrag={activeTool === 'hand' ? true : [1]}
          // Trackpad: two-finger scroll pans, pinch zooms. Mouse: wheel pans, Cmd/Ctrl + wheel zooms.
          panOnScroll
          panOnScrollMode={PanOnScrollMode.Free}
          zoomOnScroll={false}
          zoomOnPinch
          zoomActivationKeyCode={['Meta', 'Control']}
          zoomOnDoubleClick={false}
          minZoom={CANVAS_MIN_ZOOM}
          maxZoom={CANVAS_MAX_ZOOM}
          selectionOnDrag={activeTool === 'select'}
          selectionKeyCode={null}
          selectionMode={SelectionMode.Partial}
          nodesDraggable={activeTool === 'select'}
          nodesConnectable={activeTool === 'select'}
          elementsSelectable={activeTool === 'select'}
          multiSelectionKeyCode={['Shift', 'Meta', 'Control']}
          panActivationKeyCode={null}
          deleteKeyCode={['Backspace', 'Delete']}
          colorMode={theme}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} size={1} />
          <MiniMap position="bottom-right" pannable zoomable />
          <Panel position="center-left" className="canvas-panel">
            <CanvasRail onAddNode={(type) => void addNode(type)} onUpload={requestUploadAsNewNode} />
          </Panel>
          <Panel position="bottom-left" className="canvas-panel">
            <CanvasControls
              tool={activeTool}
              theme={theme}
              showEdges={showEdges}
              isSaving={isSaving}
              error={error}
              onToolChange={setTool}
              onThemeChange={setTheme}
              onEdgesChange={setShowEdges}
            />
          </Panel>
          {error && (
            <Panel position="top-center" className="canvas-panel">
              <div className="canvas-toast" role="alert">
                <span>{error}</span>
                <button type="button" aria-label="关闭提示" data-tooltip="关闭提示" data-tooltip-side="bottom" onClick={() => useCanvasStore.setState({ error: null })}>×</button>
              </div>
            </Panel>
          )}
        </ReactFlow>
        {pendingConnection && (
          <ConnectionChooser
            position={pendingConnection.screen}
            options={pendingConnection.options}
            onCreate={(type) => void createNodeFromChooser(type)}
            onClose={closeChooser}
          />
        )}
      </div>
      <TooltipLayer />
    </div>
  );
}
