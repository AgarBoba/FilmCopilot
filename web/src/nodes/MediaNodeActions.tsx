import { useCallback, useState } from 'react';

import { DownloadIcon, DuplicateIcon, ExpandIcon, HistoryIcon, UploadIcon } from '../canvas/icons';
import { useCanvasStore } from '../state/canvasStore';
import { downloadAsset } from './downloadAsset';
import { MediaViewer } from './MediaViewer';
import { NodeMenu } from './NodeMenu';
import { VersionHistory } from './VersionHistory';
import { ImageCropDialog } from './ImageCropDialog';


const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
const KIND_LABELS = { image: '图片', video: '视频' } as const;

interface MediaNodeActionsProps {
  kind: 'image' | 'video';
  /** Needed for the version history. */
  nodeId?: string;
  assetUrl?: string;
  title: string;
  busy: boolean;
  onUpload?: () => void;
  onDuplicate?: () => void;
}


/** The "⋯" menu for image/video nodes: upload, download, view full screen. */
export function MediaNodeActions({ kind, nodeId, assetUrl, title, busy, onUpload, onDuplicate }: MediaNodeActionsProps) {
  const [viewing, setViewing] = useState(false);
  const [cropping, setCropping] = useState(false);
  const closeCrop = useCallback(() => setCropping(false), []);
  const [history, setHistory] = useState(false);
  const closeHistory = useCallback(() => setHistory(false), []);
  const label = KIND_LABELS[kind];
  const noContent = `还没有${label}`;

  const download = useCallback(() => {
    if (!assetUrl) return;
    downloadAsset(assetUrl, title).catch((error: unknown) => {
      useCanvasStore.setState({ error: error instanceof Error ? error.message : '下载失败' });
    });
  }, [assetUrl, title]);
  const closeViewer = useCallback(() => setViewing(false), []);

  return (
    <>
      <NodeMenu
        items={[
          {
            key: 'upload',
            label: `上传${label}`,
            icon: <UploadIcon width={16} height={16} />,
            onSelect: () => onUpload?.(),
            disabledReason: busy ? '生成中，暂时不能上传' : undefined,
          },
          ...(kind === 'image' && nodeId ? [{
            key: 'crop', label: '裁剪',
            icon: <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}><path d="M6 3v13a2 2 0 0 0 2 2h13M3 6h13a2 2 0 0 1 2 2v13" /></svg>,
            onSelect: () => setCropping(true),
            disabledReason: busy ? '生成中，暂时不能裁剪' : assetUrl ? undefined : '还没有图片，无法裁剪',
          }] : []),
          {
            key: 'download',
            label: '下载',
            icon: <DownloadIcon width={16} height={16} />,
            onSelect: download,
            disabledReason: assetUrl ? undefined : `${noContent}，无法下载`,
          },
          {
            key: 'view',
            label: '全屏查看',
            icon: <ExpandIcon width={16} height={16} />,
            onSelect: () => setViewing(true),
            disabledReason: assetUrl ? undefined : `${noContent}，无法查看`,
          },
          ...(nodeId ? [{
            key: 'history',
            label: '版本历史',
            icon: <HistoryIcon width={16} height={16} />,
            onSelect: () => setHistory(true),
            disabledReason: assetUrl ? undefined : `${noContent}，没有版本`,
          }] : []),
          {
            key: 'duplicate',
            label: '复制节点',
            icon: <DuplicateIcon width={16} height={16} />,
            onSelect: () => onDuplicate?.(),
            shortcut: IS_MAC ? '⌘D' : 'Ctrl+D',
          },
        ]}
      />
      {cropping && nodeId && <ImageCropDialog nodeId={nodeId} title={title} onClose={closeCrop} />}
      {history && nodeId && <VersionHistory nodeId={nodeId} kind={kind} title={title} onClose={closeHistory} />}
      {viewing && assetUrl && (
        <MediaViewer kind={kind} url={assetUrl} title={title} onDownload={download} onClose={closeViewer} />
      )}
    </>
  );
}
