import { UploadIcon } from '../canvas/icons';


interface EmptyPreviewProps {
  kind: 'image' | 'video';
  busy: boolean;
  onUpload?: () => void;
}

const LABELS = { image: '图片', video: '视频' } as const;


/** Empty preview area: a hint plus an upload button in the lower part. */
export function EmptyPreview({ kind, busy, onUpload }: EmptyPreviewProps) {
  const label = LABELS[kind];
  return (
    <div className="empty-preview">
      <span className="empty-preview-hint">上传{label}或连接参考素材</span>
      <button
        type="button"
        className="empty-preview-upload nodrag"
        aria-disabled={busy}
        data-tooltip={busy ? '生成中，暂时不能上传' : undefined}
        onClick={(event) => {
          event.stopPropagation();
          if (!busy) onUpload?.();
        }}
      >
        <UploadIcon width={15} height={15} />
        上传{label}
      </button>
    </div>
  );
}
