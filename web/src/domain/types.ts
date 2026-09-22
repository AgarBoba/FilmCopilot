export type NodeType = 'image' | 'video' | 'note';

export interface CanvasPosition {
  x: number;
  y: number;
}

export interface AssetSummary {
  id: string;
  kind: 'image' | 'video';
  url: string;
  mimeType: string;
  width?: number;
  height?: number;
  durationSeconds?: number;
}

export interface ImageGenerationParameters {
  kind: 'image';
  size: '1K' | '2K';
  aspectRatio: string;
  outputFormat: 'jpg' | 'png' | 'webp';
}

export interface VideoGenerationParameters {
  kind: 'video';
  durationSeconds: number;
  resolution: '480p' | '720p';
  aspectRatio: string;
  generateAudio: boolean;
}

export type GenerationParameters =
  | ImageGenerationParameters
  | VideoGenerationParameters;

export interface GenerationState {
  status: 'idle' | 'queued' | 'running' | 'completed' | 'failed';
  jobId?: string;
  error?: string;
}

export interface CanvasNodeData {
  title: string;
  prompt: string;
  asset?: AssetSummary | null;
  parameters?: GenerationParameters | null;
  generation?: GenerationState | null;
  [key: string]: unknown;
}

export interface CanvasNode {
  id: string;
  type: NodeType;
  position: CanvasPosition;
  width?: number;
  height?: number;
  data: CanvasNodeData;
}

export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
}

export interface CanvasViewport {
  x: number;
  y: number;
  zoom: number;
}

export interface CanvasSnapshot {
  revision: number;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  viewport: CanvasViewport;
}

export interface CommandEnvelope<TPayload = Record<string, unknown>> {
  baseRevision: number;
  idempotencyKey: string;
  command: {
    type: string;
    payload: TPayload;
  };
}
