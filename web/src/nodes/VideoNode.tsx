import { useRef } from 'react';
import { Position } from '@xyflow/react';

import type { VideoGenerationParameters } from '../domain/types';
import { NodeHandle } from './NodeHandles';
import { getDefaultVideoParameters } from './generationParameters';
import { PromptComposer } from './PromptComposer';


export interface VideoNodeData {
  title?: string;
  assetUrl?: string;
  posterUrl?: string;
  play?: () => Promise<void> | void;
  pause?: () => void;
  onUpload?: () => void;
  onGenerate?: () => void;
  prompt?: string;
  parameters?: VideoGenerationParameters;
  generationStatus?: string;
  onPromptChange?: (prompt: string) => void;
  onParametersChange?: (parameters: VideoGenerationParameters) => void;
  onGenerateRequest?: (request: { prompt: string; parameters: VideoGenerationParameters }) => void;
  [key: string]: unknown;
}


interface VideoNodeProps {
  data: VideoNodeData;
}


export function VideoNode({ data }: VideoNodeProps) {
  const videoRef = useRef<HTMLVideoElement>(null);

  async function playPreview() {
    if (data.play) {
      await data.play();
      return;
    }
    await videoRef.current?.play();
  }

  function pausePreview() {
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
      <NodeHandle type="target" position={Position.Left} id="target" />
      <NodeHandle type="source" position={Position.Right} id="source" />
      <div className="node-heading">
        <span className="node-kind">VIDEO</span>
        <strong>{data.title ?? '视频节点'}</strong>
      </div>
      <div className="media-preview video-preview">
        {data.assetUrl ? (
          <video
            ref={videoRef}
            src={data.assetUrl}
            poster={data.posterUrl}
            muted
            playsInline
            preload="metadata"
          />
        ) : (
          <span>上传视频或连接参考素材</span>
        )}
      </div>
      <PromptComposer
        kind="video"
        prompt={data.prompt ?? ''}
        parameters={data.parameters ?? getDefaultVideoParameters()}
        onPromptChange={(prompt) => data.onPromptChange?.(prompt)}
        onParametersChange={(parameters) => data.onParametersChange?.(parameters as VideoGenerationParameters)}
        onGenerate={(request) => data.onGenerateRequest?.(request as { prompt: string; parameters: VideoGenerationParameters })}
        disabled={data.generationStatus === 'queued' || data.generationStatus === 'running'}
      />
      <div className="node-actions">
        <button type="button" onClick={(event) => { event.stopPropagation(); data.onUpload?.(); }}>
          上传
        </button>
      </div>
    </div>
  );
}
