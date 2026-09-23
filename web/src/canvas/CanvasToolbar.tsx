import type { NodeType } from '../domain/types';

export type CanvasTool = 'select' | 'hand';


interface CanvasToolbarProps {
  tool: CanvasTool;
  theme: 'light' | 'dark';
  showEdges: boolean;
  isSaving: boolean;
  error: string | null;
  onToolChange: (tool: CanvasTool) => void;
  onThemeChange: (theme: 'light' | 'dark') => void;
  onEdgesChange: (showEdges: boolean) => void;
  onAddNode: (nodeType: NodeType) => void;
}


export function CanvasToolbar({
  tool,
  theme,
  showEdges,
  isSaving,
  error,
  onToolChange,
  onThemeChange,
  onEdgesChange,
  onAddNode,
}: CanvasToolbarProps) {
  return (
    <div className="canvas-toolbar" role="toolbar" aria-label="画布工具栏">
      <div className="toolbar-group">
        <button
          type="button"
          className={`tool-button ${tool === 'select' ? 'is-active' : ''}`}
          aria-pressed={tool === 'select'}
          title="鼠标工具 · V · 拖动空白处框选"
          onClick={() => onToolChange('select')}
        >
          鼠标 <kbd>V</kbd>
        </button>
        <button
          type="button"
          className={`tool-button ${tool === 'hand' ? 'is-active' : ''}`}
          aria-pressed={tool === 'hand'}
          title="抓手工具 · H · 按住空格可临时切换"
          onClick={() => onToolChange('hand')}
        >
          抓手 <kbd>H</kbd>
        </button>
        <span className="toolbar-divider" aria-hidden="true" />
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
        <span className={`save-state ${error ? 'save-error' : ''}`} role="status">
          {error ? `保存失败：${error}` : isSaving ? '保存中…' : '已保存'}
        </span>
      </div>
    </div>
  );
}
