import { Position } from '@xyflow/react';

import type { ImageGenerationParameters } from '../domain/types';
import { NodeHandle } from './NodeHandles';
import { NodeTitle } from './NodeTitle';
import { EmptyPreview } from './EmptyPreview';
import { MediaNodeActions } from './MediaNodeActions';
import { ReferenceStrip, normalizeReferences, type NodeReference } from './ReferenceStrip';
import { GenerationOverlay, isGenerationBusy } from './GenerationOverlay';
import { getDefaultImageParameters } from './generationParameters';
import { PromptComposer } from './PromptComposer';


export interface ImageNodeData {
  title?: string;
  onTitleChange?: (title: string) => void;
  prompt?: string;
  assetUrl?: string;
  references?: Array<NodeReference | string>;
  onUpload?: () => void;
  onDuplicate?: () => void;
  onGenerate?: () => void;
  parameters?: ImageGenerationParameters;
  generationStatus?: string;
  generationError?: string;
  onPromptChange?: (prompt: string) => void;
  onParametersChange?: (parameters: ImageGenerationParameters) => void;
  onGenerateRequest?: (request: { prompt: string; parameters: ImageGenerationParameters }) => void;
  onRemoveReference?: (reference: NodeReference) => void;
  [key: string]: unknown;
}


interface ImageNodeProps {
  data: ImageNodeData;
}


export function ImageNode({ data }: ImageNodeProps) {
  const references = normalizeReferences(data.references);
  const busy = isGenerationBusy(data.generationStatus);
  const noteCount = references.filter((reference) => reference.kind === 'note' && reference.text?.trim()).length;
  return (
    <div className="media-node image-node" data-testid="image-node">
      <NodeHandle type="target" position={Position.Left} id="target" />
      <NodeHandle type="source" position={Position.Right} id="source" />
      <div className="node-heading">
        <span className="node-kind">IMAGE</span>
        <NodeTitle title={data.title} fallback="图片节点" onChange={data.onTitleChange} />
        <MediaNodeActions
          kind="image"
          assetUrl={data.assetUrl}
          title={data.title?.trim() || '图片节点'}
          busy={busy}
          onUpload={data.onUpload}
          onDuplicate={data.onDuplicate}
        />
      </div>
      <div className="media-preview image-preview">
        <GenerationOverlay status={data.generationStatus} error={data.generationError} />
        {data.assetUrl ? (
          <img src={data.assetUrl} alt={data.title ?? 'image'} />
        ) : (
          <EmptyPreview kind="image" busy={busy} onUpload={data.onUpload} />
        )}
      </div>
      <ReferenceStrip references={references} onRemove={busy ? undefined : data.onRemoveReference} />
      <PromptComposer
        kind="image"
        prompt={data.prompt ?? ''}
        parameters={data.parameters ?? getDefaultImageParameters()}
        onPromptChange={(prompt) => data.onPromptChange?.(prompt)}
        onParametersChange={(parameters) => data.onParametersChange?.(parameters as ImageGenerationParameters)}
        onGenerate={(request) => data.onGenerateRequest?.(request as { prompt: string; parameters: ImageGenerationParameters })}
        disabled={busy}
        noteCount={noteCount}
      />
    </div>
  );
}
