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

/**
 * Parameters depend on the node's model (models/*.json), so they are an open record.
 * The named fields are the bundled Seedream / Seedance ones, kept for readability.
 */
export interface ImageGenerationParameters {
  size?: string;
  aspectRatio?: string;
  outputFormat?: string;
  [key: string]: unknown;
}

export interface VideoGenerationParameters {
  duration?: number;
  resolution?: string;
  aspectRatio?: string;
  generateAudio?: boolean;
  [key: string]: unknown;
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
