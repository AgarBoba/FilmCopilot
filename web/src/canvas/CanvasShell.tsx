import { useEffect, useMemo, useState } from 'react';
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
} from '@xyflow/react';

import { canConnect } from '../domain/connectionRules';
import { api } from '../api/client';
import type { CanvasNodeData, NodeType } from '../domain/types';
import { snapshotToReactFlow, useCanvasStore } from '../state/canvasStore';
import { CanvasToolbar } from './CanvasToolbar';


const nodeTypes = {};


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

  useEffect(() => {
    if (!snapshot) {
      setNodes([]);
      setEdges([]);
      return;
    }
    const flow = snapshotToReactFlow(snapshot);
    setNodes(flow.nodes);
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
      hidden: !showEdges && edge.source !== selectedNodeId && edge.target !== selectedNodeId,
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
        <ReactFlow
          nodes={nodes}
          edges={visibleEdges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onNodeDragStop={onNodeDragStop}
          onConnect={onConnect}
          onSelectionChange={onSelectionChange}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} size={1} />
          <Controls position="bottom-right" />
          <MiniMap position="bottom-left" pannable zoomable />
        </ReactFlow>
      </div>
    </div>
  );
}
