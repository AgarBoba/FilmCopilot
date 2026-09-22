import type { NodeType } from '../domain/types';


interface CanvasToolbarProps {
  theme: 'light' | 'dark';
  showEdges: boolean;
  isSaving: boolean;
  onThemeChange: (theme: 'light' | 'dark') => void;
  onEdgesChange: (showEdges: boolean) => void;
  onAddNode: (nodeType: NodeType) => void;
}


export function CanvasToolbar({
  theme,
  showEdges,
  isSaving,
  onThemeChange,
  onEdgesChange,
  onAddNode,
}: CanvasToolbarProps) {
  return (
    <div className="canvas-toolbar" role="toolbar" aria-label="画布工具栏">
      <div className="toolbar-group">
        <button type="button" onClick={() => onAddNode('image')}>+ 图片</button>
        <button type="button" onClick={() => onAddNode('video')}>+ 视频</button>
        <button type="button" onClick={() => onAddNode('note')}>+ 便签</button>
      </div>
      <div className="toolbar-group toolbar-secondary">
        <button type="button" onClick={() => onEdgesChange(!showEdges)}>
          {showEdges ? '隐藏连线' : '显示连线'}
        </button>
        <button type="button" onClick={() => onThemeChange(theme === 'dark' ? 'light' : 'dark')}>
          {theme === 'dark' ? '浅色' : '深色'}
        </button>
        <span className="save-state">{isSaving ? '保存中…' : '已保存'}</span>
      </div>
    </div>
  );
}
