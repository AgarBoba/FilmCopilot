import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { CloseIcon } from '../canvas/icons';
import { assetFileUrl, commentApi, type NodeVersion } from '../comments/commentApi';
import { useCommentStore } from '../comments/commentStore';
import { parseTime } from '../agent/SessionList';
import { useCanvasStore } from '../state/canvasStore';

const SOURCES: Record<string, string> = {
  cropped: '裁剪', generated: '生成', uploaded: '上传', restored: '切回旧版', copied: '复制自其他节点', edited: '其他',
};

interface VersionHistoryProps {
  nodeId: string;
  kind: 'image' | 'video';
  title: string;
  onClose: () => void;
}

/**
 * Every picture / video this node has had, newest first. Switching back just shows that
 * version again; it adds no new one, and nothing is ever removed.
 */
export function VersionHistory({ nodeId, kind, title, onClose }: VersionHistoryProps) {
  const canvasId = useCanvasStore((state) => state.canvasId);
  const revision = useCanvasStore((state) => state.snapshot?.revision ?? 0);
  const [versions, setVersions] = useState<NodeVersion[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!canvasId) return;
    commentApi.versions(canvasId, nodeId)
      .then((data) => { setVersions(data.versions); setCurrent(data.current); })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '读取版本失败'));
  }, [canvasId, nodeId, revision]);

  useEffect(() => {
    closeRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      event.stopPropagation();
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [onClose]);

  async function restore(version: number) {
    const state = useCanvasStore.getState();
    if (!state.snapshot) return;
    setBusy(true);
    try {
      await state.execute({
        command: 'restore_version',
        baseRevision: state.snapshot.revision,
        idempotencyKey: `restore-version-${crypto.randomUUID()}`,
        payload: { nodeId, version },
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '切换失败');
    } finally {
      setBusy(false);
    }
  }

  const comments = useCommentStore((state) => state.comments);
  const newestFirst = [...(versions ?? [])].reverse();

  return createPortal(
    <div className="version-history-backdrop" onPointerDown={(event) => { if (event.target === event.currentTarget) onClose(); }}
      onWheel={(event) => event.stopPropagation()}>
      <div className="version-history" role="dialog" aria-modal="true" aria-label={`「${title}」的版本历史`}>
        <header>
          <span>「{title}」的版本历史</span>
          <button ref={closeRef} type="button" aria-label="关闭" onClick={onClose}><CloseIcon width={16} height={16} /></button>
        </header>
        {error && <div className="version-error" role="alert">{error}</div>}
        {versions === null && !error && <div className="version-empty">正在读取…</div>}
        {versions?.length === 0 && <div className="version-empty">还没有{kind === 'image' ? '图片' : '视频'}，没有版本。</div>}
        <ul>
          {newestFirst.map((item) => {
            const isCurrent = item.assetId === current;
            const comment = item.commentId ? comments.find((entry) => entry.id === item.commentId) : undefined;
            const time = parseTime(item.createdAt);
            return (
              <li key={item.version} className={isCurrent ? 'is-current' : ''}>
                <span className="version-thumb">
                  {kind === 'video'
                    ? <video src={assetFileUrl(item.assetId)} muted preload="metadata" />
                    : <img src={assetFileUrl(item.assetId)} alt={`第 ${item.version} 版`} loading="lazy" />}
                </span>
                <span className="version-info">
                  <span className="version-title">
                    第 {item.version} 版{isCurrent && <em>当前</em>}
                  </span>
                  <span className="version-meta">
                    {SOURCES[item.source] ?? item.source}
                    {time && ` · ${time.getMonth() + 1}/${time.getDate()} ${String(time.getHours()).padStart(2, '0')}:${String(time.getMinutes()).padStart(2, '0')}`}
                    {item.model && ` · ${item.model}`}
                  </span>
                  {comment && <span className="version-comment">来自留言：{comment.text}</span>}
                  {item.prompt && <span className="version-prompt" title={item.prompt}>{item.prompt}</span>}
                </span>
                {!isCurrent && (
                  <button type="button" className="comment-button" disabled={busy} onClick={() => void restore(item.version)}>
                    切回这一版
                  </button>
                )}
              </li>
            );
          })}
        </ul>
        <footer>切回只是换成显示那一版，不会多出新的版本；只有新生成或上传的才算新版本。</footer>
      </div>
    </div>,
    document.querySelector('.canvas-page') ?? document.body,
  );
}
