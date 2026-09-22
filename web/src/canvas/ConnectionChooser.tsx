import type { NodeType } from '../domain/types';


interface ConnectionChooserProps {
  position: { x: number; y: number };
  onCreate: (nodeType: Extract<NodeType, 'image' | 'video'>) => void;
}


export function ConnectionChooser({ position, onCreate }: ConnectionChooserProps) {
  return (
    <div
      className="connection-chooser"
      style={{ left: position.x, top: position.y }}
      role="menu"
      aria-label="选择新节点类型"
    >
      <button type="button" onClick={() => onCreate('image')}>图片节点</button>
      <button type="button" onClick={() => onCreate('video')}>视频节点</button>
    </div>
  );
}
