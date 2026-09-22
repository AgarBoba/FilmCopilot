import { Position } from '@xyflow/react';

import type { ImageGenerationParameters } from '../domain/types';
import { NodeHandle } from './NodeHandles';
import { getDefaultImageParameters } from './generationParameters';
import { PromptComposer } from './PromptComposer';


export interface ImageNodeData {
  title?: string;
  prompt?: string;
  assetUrl?: string;
  references?: string[];
  onUpload?: () => void;
  onGenerate?: () => void;
  parameters?: ImageGenerationParameters;
  generationStatus?: string;
  onPromptChange?: (prompt: string) => void;
  onParametersChange?: (parameters: ImageGenerationParameters) => void;
  onGenerateRequest?: (request: { prompt: string; parameters: ImageGenerationParameters }) => void;
  onRemoveReference?: (url: string) => void;
  [key: string]: unknown;
}


interface ImageNodeProps {
  data: ImageNodeData;
}


export function ImageNode({ data }: ImageNodeProps) {
  const references = data.references ?? [];
  return (
    <div className="media-node image-node" data-testid="image-node">
      <NodeHandle type="target" position={Position.Left} id="target" />
      <NodeHandle type="source" position={Position.Right} id="source" />
      <div className="node-heading">
        <span className="node-kind">IMAGE</span>
        <strong>{data.title ?? '图片节点'}</strong>
      </div>
      <div className="media-preview image-preview">
        {data.assetUrl ? (
          <img src={data.assetUrl} alt={data.title ?? 'image'} />
        ) : (
          <span>上传图片或连接参考素材</span>
        )}
      </div>
      {references.length > 0 && (
        <div className="reference-strip" aria-label="参考图片">
          {references.map((reference, index) => (
            <div className="reference-thumb" key={`${reference}-${index}`}>
              <img src={reference} alt={`reference-${index + 1}`} />
              <button
                type="button"
                aria-label={`删除参考图 ${index + 1}`}
                onClick={(event) => {
                  event.stopPropagation();
                  data.onRemoveReference?.(reference);
                }}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      <PromptComposer
        kind="image"
        prompt={data.prompt ?? ''}
        parameters={data.parameters ?? getDefaultImageParameters()}
        onPromptChange={(prompt) => data.onPromptChange?.(prompt)}
        onParametersChange={(parameters) => data.onParametersChange?.(parameters as ImageGenerationParameters)}
        onGenerate={(request) => data.onGenerateRequest?.(request as { prompt: string; parameters: ImageGenerationParameters })}
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
