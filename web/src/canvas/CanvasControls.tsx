import { useReactFlow, useViewport } from '@xyflow/react';

import {
  EdgesIcon,
  EdgesOffIcon,
  HandIcon,
  MinusIcon,
  MoonIcon,
  PlusIcon,
  PointerIcon,
  SunIcon,
} from './icons';

export type CanvasTool = 'select' | 'hand';

interface CanvasControlsProps {
  tool: CanvasTool;
  theme: 'light' | 'dark';
  showEdges: boolean;
  isSaving: boolean;
  error: string | null;
  onToolChange: (tool: CanvasTool) => void;
  onThemeChange: (theme: 'light' | 'dark') => void;
  onEdgesChange: (showEdges: boolean) => void;
}

const ZOOM_DURATION = 200;


/** Bottom-left canvas controls. Must render inside <ReactFlow> (uses its viewport hooks). */
export function CanvasControls({
  tool,
  theme,
  showEdges,
  isSaving,
  error,
  onToolChange,
  onThemeChange,
  onEdgesChange,
}: CanvasControlsProps) {
  const { zoomIn, zoomOut, zoomTo, fitView } = useReactFlow();
  const { zoom } = useViewport();
  const saveLabel = error ? `保存失败：${error}` : isSaving ? '保存中…' : '已保存';

  return (
    <div className="canvas-controls" role="toolbar" aria-label="画布控件">
      <button
        type="button"
        className={`control-button ${tool === 'select' ? 'is-active' : ''}`}
        aria-label="鼠标工具"
        aria-pressed={tool === 'select'}
        data-tooltip="鼠标：选择和拖动节点，拖动空白处可框选"
        data-tooltip-shortcut="V"
        onClick={() => onToolChange('select')}
      >
        <PointerIcon />
      </button>
      <button
        type="button"
        className={`control-button ${tool === 'hand' ? 'is-active' : ''}`}
        aria-label="抓手工具"
        aria-pressed={tool === 'hand'}
        data-tooltip="抓手：拖动画布（按住空格可临时切换）"
        data-tooltip-shortcut="H"
        onClick={() => onToolChange('hand')}
      >
        <HandIcon />
      </button>

      <span className="control-divider" aria-hidden="true" />

      <button
        type="button"
        className="control-button"
        aria-label="缩小"
        data-tooltip="缩小"
        onClick={() => void zoomOut({ duration: ZOOM_DURATION })}
      >
        <MinusIcon />
      </button>
      <button
        type="button"
        className="control-zoom"
        aria-label={`当前缩放 ${Math.round(zoom * 100)}%，点击恢复 100%`}
        data-tooltip="恢复到 100%"
        onClick={() => void zoomTo(1, { duration: ZOOM_DURATION })}
      >
        {Math.round(zoom * 100)}%
      </button>
      <button
        type="button"
        className="control-button"
        aria-label="放大"
        data-tooltip="放大"
        onClick={() => void zoomIn({ duration: ZOOM_DURATION })}
      >
        <PlusIcon />
      </button>
      <button
        type="button"
        className="control-text"
        aria-label="显示全部节点"
        data-tooltip="缩放到能看到全部节点"
        onClick={() => void fitView({ padding: 0.2, duration: 300 })}
      >
        Fit
      </button>

      <span className="control-divider" aria-hidden="true" />

      <button
        type="button"
        className={`control-button ${showEdges ? '' : 'is-active'}`}
        aria-label={showEdges ? '隐藏连线' : '显示连线'}
        aria-pressed={!showEdges}
        data-tooltip={showEdges ? '隐藏连线' : '显示连线'}
        onClick={() => onEdgesChange(!showEdges)}
      >
        {showEdges ? <EdgesIcon /> : <EdgesOffIcon />}
      </button>
      <button
        type="button"
        className="control-button"
        aria-label={theme === 'dark' ? '切换到浅色' : '切换到深色'}
        data-tooltip={theme === 'dark' ? '切换到浅色模式' : '切换到深色模式'}
        onClick={() => onThemeChange(theme === 'dark' ? 'light' : 'dark')}
      >
        {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
      </button>
      <span
        className={`save-dot ${error ? 'is-error' : isSaving ? 'is-saving' : ''}`}
        role="status"
        aria-label={saveLabel}
        data-tooltip={saveLabel}
      />
    </div>
  );
}
