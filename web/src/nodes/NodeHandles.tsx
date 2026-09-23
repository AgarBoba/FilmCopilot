import { Handle, Position, useStoreApi } from '@xyflow/react';


interface NodeHandlesProps {
  type: 'source' | 'target';
  position: Position;
  id: string;
}


const HANDLE_TOOLTIPS = {
  target: { text: '输入端：把其他节点连到这里作为参考', side: 'left' },
  source: { text: '输出端：拖出连线，连到下游节点或新建节点', side: 'right' },
} as const;


export function NodeHandle(props: NodeHandlesProps) {
  const tooltip = HANDLE_TOOLTIPS[props.type];
  let hasReactFlowProvider = true;
  try {
    useStoreApi();
  } catch {
    hasReactFlowProvider = false;
  }
  if (!hasReactFlowProvider) {
    return <span className="node-handle fallback-handle" aria-hidden="true" />;
  }
  return (
    <Handle
      className="node-handle"
      data-tooltip={tooltip.text}
      data-tooltip-side={tooltip.side}
      {...props}
    />
  );
}
