export type NodeType = 'image' | 'video' | 'note';

export interface CanvasPosition {
  x: number;
  y: number;
}

export interface AssetSummary {
  id: string;
  kind: 'image' | 'video';
  url?: string;
  mimeType: string;
  width?: number;
  height?: number;
  durationSeconds?: number;
}

export interface ImageGenerationParameters {
  size: '1K' | '2K';
  aspectRatio: string;
  outputFormat: 'png' | 'jpeg';
}

export interface VideoGenerationParameters {
  duration: number;
  resolution: '480p' | '720p';
  aspectRatio: string;
  generateAudio: boolean;
}

export type GenerationParameters =
  | ImageGenerationParameters
  | VideoGenerationParameters;

export interface GenerationState {
  status: 'idle' | 'queued' | 'running' | 'succeeded' | 'failed' | 'completed_unattached';
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
  nodeType: NodeType;
  x: number;
  y: number;
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
  canvasId: string;
  name: string;
  revision: number;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  assets?: AssetSummary[];
  jobs?: Record<string, unknown>[];
  /** nodeId -> what changed upstream since the node's current result was generated */
  upstreamChanges?: Record<string, string[]>;
  viewport?: CanvasViewport;
}

export interface CommandEnvelope<TPayload = Record<string, unknown>> {
  baseRevision: number;
  idempotencyKey: string;
  command: string;
  payload: TPayload;
}

export interface CommandResult {
  revision: number;
  command: string;
  payload: Record<string, unknown>;
}

export interface CanvasEvent {
  id: number;
  canvasId: string;
  revision: number;
  eventType: string;
  payload: Record<string, unknown>;
}
