import {
  BaseEdge,
  getBezierPath,
  type EdgeProps,
  type Edge as ReactFlowEdge,
} from '@xyflow/react';


export function ReferenceEdge({ selected, ...props }: EdgeProps<ReactFlowEdge>) {
  const [path] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
  });
  return (
    <BaseEdge
      id={props.id}
      path={path}
      style={{
        stroke: selected ? '#a78bfa' : '#7c8496',
        strokeWidth: selected ? 3 : 2,
        strokeLinecap: 'round',
      }}
    />
  );
}


export function getVisibleEdgeIds(
  edges: Pick<ReactFlowEdge, 'id' | 'source' | 'target'>[],
  selectedNodeId: string | null,
  showEdges: boolean,
): Set<string> {
  if (showEdges) {
    return new Set(edges.map((edge) => edge.id));
  }
  return new Set(
    edges
      .filter((edge) => edge.source === selectedNodeId || edge.target === selectedNodeId)
      .map((edge) => edge.id),
  );
}
