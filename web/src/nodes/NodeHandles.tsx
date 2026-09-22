import { Handle, Position, useStoreApi } from '@xyflow/react';


interface NodeHandlesProps {
  type: 'source' | 'target';
  position: Position;
  id: string;
}


export function NodeHandle(props: NodeHandlesProps) {
  let hasReactFlowProvider = true;
  try {
    useStoreApi();
  } catch {
    hasReactFlowProvider = false;
  }
  if (!hasReactFlowProvider) {
    return <span className="node-handle fallback-handle" aria-hidden="true" />;
  }
  return <Handle className="node-handle" {...props} />;
}
