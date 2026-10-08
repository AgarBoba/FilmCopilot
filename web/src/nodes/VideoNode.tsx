import { useRef } from 'react';
import { Position } from '@xyflow/react';

import type { VideoGenerationParameters } from '../domain/types';
import { NodeHandle } from './NodeHandles';
import { NodeTitle } from './NodeTitle';
import { UpstreamBadge } from './UpstreamBadge';
import { EmptyPreview } from './EmptyPreview';
import { MediaNodeActions } from './MediaNodeActions';
import { ReferenceStrip, normalizeReferences, type NodeReference } from './ReferenceStrip';
import { GenerationOverlay, isGenerationBusy } from './GenerationOverlay';
import { PromptComposer } from './PromptComposer';
import { NodeTag } from './NodeTag';
import { VideoPlayer, type CommentMark } from './VideoPlayer';
import { CommentBadge, type NodeCommentSummary } from './CommentBadge';


export interface VideoNodeData {
  title?: string;
  onTitleChange?: (title: string) => void;
  assetUrl?: string;
  posterUrl?: string;
  play?: () => Promise<void> | void;
  pause?: () => void;
  onUpload?: () => void;
  onDuplicate?: () => void;
  onGenerate?: () => void;
  prompt?: string;
  parameters?: VideoGenerationParameters;
  generationStatus?: string;
  generationError?: string;
  upstreamChanges?: string[];
  references?: Array<NodeReference | string>;
  onRemoveReference?: (reference: NodeReference) => void;
  onPromptChange?: (prompt: string) => void;
  onParametersChange?: (parameters: VideoGenerationParameters) => void;
  onGenerateRequest?: (request: { prompt: string; parameters: VideoGenerationParameters; model?: string }) => void;
  /** Model id from models/*.json; missing means the default video model. */
  model?: string;
  onModelChange?: (model: string, parameters: Record<string, unknown>) => void;
  /** Comments pinned to moments of this video: shown as marks on the progress bar. */
  commentMarks?: CommentMark[];
  onOpenComment?: (commentId: string) => void;
  comments?: NodeCommentSummary;
  onOpenComments?: () => void;
  [key: string]: unknown;
}


interface VideoNodeProps {
  id?: string;
  data: VideoNodeData;
  /** From React Flow: the node's x on the canvas, used to swing the name tag while dragging. */
  positionAbsoluteX?: number;
}


export function VideoNode({ id, data, positionAbsoluteX }: VideoNodeProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const manualRef = useRef(false);
  const busy = isGenerationBusy(data.generationStatus);
  const references = normalizeReferences(data.references);
  const noteCount = references.filter((reference) => reference.kind === 'note' && reference.text?.trim()).length;

  // Hover = silent preview. Skipped once the user is driving playback with the controls.
  async function playPreview() {
    if (manualRef.current) return;
    if (data.play) {
      await data.play();
      return;
    }
    await videoRef.current?.play();
  }

  function pausePreview() {
    const video = videoRef.current;
    if (video?.dataset.held) {
      // Paused on a frame to pin a comment: keep that frame, playback is the user's now.
      delete video.dataset.held;
      manualRef.current = true;
      return;
    }
    if (manualRef.current) {
      // Leave a video the user started playing alone; hand a paused one back to hover preview.
      if (!video || video.paused) manualRef.current = false;
      return;
    }
    if (data.pause) {
      data.pause();
    } else if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.currentTime = 0;
    }
  }

  return (
    <div
      className="media-node video-node"
      data-testid="video-node"
      onMouseEnter={() => { void playPreview().catch(() => undefined); }}
      onMouseLeave={pausePreview}
    >
      {!busy && <UpstreamBadge changes={data.upstreamChanges} />}
      <NodeHandle type="target" position={Position.Left} id="target" />
      <NodeHandle type="source" position={Position.Right} id="source" />
      <NodeTag title={data.title?.trim() || '视频节点'} x={positionAbsoluteX} />
      {/* Name bar: pops up out of the top of the frame when the node is selected. */}
      <div className="node-topbar">
        <div className="node-heading">
          <span className="node-kind">VIDEO</span>
          <NodeTitle title={data.title} fallback="视频节点" onChange={data.onTitleChange} />
          <MediaNodeActions
            kind="video"
            nodeId={id}
            assetUrl={data.assetUrl}
            title={data.title?.trim() || '视频节点'}
            busy={busy}
            onUpload={data.onUpload}
            onDuplicate={data.onDuplicate}
          />
        </div>
      </div>
      <div className="media-preview video-preview">
        <GenerationOverlay status={data.generationStatus} error={data.generationError} />
        <CommentBadge summary={data.comments} onOpen={data.onOpenComments} />
        {data.assetUrl ? (
          <VideoPlayer
            src={data.assetUrl}
            poster={data.posterUrl}
            videoRef={videoRef}
            manualRef={manualRef}
            marks={data.commentMarks}
            onMark={data.onOpenComment}
          />
        ) : (
          <EmptyPreview kind="video" busy={busy} onUpload={data.onUpload} />
        )}
      </div>
      {/* Slides out from under the media when the node is selected (like a slider phone). */}
      <div className="node-drawer">
        <div className="node-drawer-inner">
          <ReferenceStrip references={references} onRemove={busy ? undefined : data.onRemoveReference} />
          <PromptComposer
            kind="video"
            prompt={data.prompt ?? ''}
            parameters={data.parameters}
            onPromptChange={(prompt) => data.onPromptChange?.(prompt)}
            onParametersChange={(parameters) => data.onParametersChange?.(parameters as VideoGenerationParameters)}
            onGenerate={(request) => data.onGenerateRequest?.(request as { prompt: string; parameters: VideoGenerationParameters; model?: string })}
            modelId={data.model}
            onModelChange={(model, parameters) => data.onModelChange?.(model, parameters)}
            disabled={busy}
            noteCount={noteCount}
          />
        </div>
      </div>
    </div>
  );
}
