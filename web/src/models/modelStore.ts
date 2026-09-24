import { create } from 'zustand';

/** One model from models/*.json, as served by GET /api/models. */
export interface ModelParameter {
  key: string;
  label: string;
  type: 'enum' | 'boolean' | 'integer' | 'number' | 'string';
  default: unknown;
  options?: { value: string | number | boolean; label: string }[];
  min?: number;
  max?: number;
}

export interface ModelInfo {
  id: string;
  label: string;
  kind: 'image' | 'video';
  provider: string;
  description: string;
  default: boolean;
  maxImages: number;
  maxVideos: number;
  parameters: ModelParameter[];
  /** Settings its provider needs that aren't filled in (names only). */
  missingEnv: string[];
  /** False when there is no adapter for its provider yet (api/app/providers/<provider>.py). */
  providerReady?: boolean;
}

/**
 * Used until /api/models answers (and in tests): the two bundled models. The server's
 * list always wins once loaded, so models added later need no frontend change.
 */
export const FALLBACK_MODELS: ModelInfo[] = [
  {
    id: 'seedream-5-pro', label: 'Seedream 5 Pro', kind: 'image', provider: 'replicate', description: '',
    default: true, maxImages: 10, maxVideos: 0, missingEnv: [],
    parameters: [
      { key: 'size', label: 'Size', type: 'enum', default: '2K', options: [{ value: '1K', label: '1K' }, { value: '2K', label: '2K' }] },
      { key: 'aspectRatio', label: 'Aspect ratio', type: 'enum', default: 'match_input_image', options: [
        { value: 'match_input_image', label: 'Match input' }, { value: '1:1', label: '1:1' }, { value: '16:9', label: '16:9' },
        { value: '9:16', label: '9:16' }, { value: '4:3', label: '4:3' },
      ] },
      { key: 'outputFormat', label: 'Format', type: 'enum', default: 'png', options: [{ value: 'png', label: 'PNG' }, { value: 'jpeg', label: 'JPEG' }] },
    ],
  },
  {
    id: 'seedance-2.0-mini', label: 'Seedance 2.0 Mini', kind: 'video', provider: 'replicate', description: '',
    default: true, maxImages: 9, maxVideos: 3, missingEnv: [],
    parameters: [
      { key: 'duration', label: 'Duration', type: 'enum', default: 5, options: [{ value: 5, label: '5s' }, { value: 10, label: '10s' }] },
      { key: 'resolution', label: 'Resolution', type: 'enum', default: '720p', options: [{ value: '480p', label: '480p' }, { value: '720p', label: '720p' }] },
      { key: 'aspectRatio', label: 'Aspect ratio', type: 'enum', default: 'adaptive', options: [
        { value: 'adaptive', label: 'Adaptive' }, { value: '16:9', label: '16:9' }, { value: '9:16', label: '9:16' }, { value: '1:1', label: '1:1' },
      ] },
      { key: 'generateAudio', label: 'Audio', type: 'boolean', default: true },
    ],
  },
];

interface ModelState {
  models: ModelInfo[];
  errors: string[];
  loaded: boolean;
  load: () => Promise<void>;
}

export const useModelStore = create<ModelState>((set) => ({
  models: FALLBACK_MODELS,
  errors: [],
  loaded: false,
  load: async () => {
    try {
      const response = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? '/api'}/models`);
      if (!response.ok) return;
      const body = (await response.json()) as { models: ModelInfo[]; errors: string[] };
      if (Array.isArray(body.models) && body.models.length) set({ models: body.models, errors: body.errors ?? [], loaded: true });
    } catch {
      /* offline: keep what we have */
    }
  },
}));

export function modelsOfKind(models: ModelInfo[], kind: 'image' | 'video'): ModelInfo[] {
  return models.filter((model) => model.kind === kind);
}

/** The node's chosen model if it still exists and fits, otherwise the default for its kind. */
export function modelForNode(models: ModelInfo[], kind: 'image' | 'video', modelId?: string | null): ModelInfo | undefined {
  const ofKind = modelsOfKind(models, kind);
  return ofKind.find((model) => model.id === modelId) ?? ofKind.find((model) => model.default) ?? ofKind[0];
}

/** Every parameter of the model, keeping values that are valid and filling the rest with defaults. */
export function resolveParameters(model: ModelInfo | undefined, values: Record<string, unknown> | undefined): Record<string, unknown> {
  if (!model) return { ...(values ?? {}) };
  const resolved: Record<string, unknown> = {};
  for (const parameter of model.parameters) {
    const value = values?.[parameter.key];
    resolved[parameter.key] = isValid(parameter, value) ? value : parameter.default;
  }
  return resolved;
}

function isValid(parameter: ModelParameter, value: unknown): boolean {
  if (value === undefined || value === null) return false;
  switch (parameter.type) {
    case 'enum': return (parameter.options ?? []).some((option) => option.value === value);
    case 'boolean': return typeof value === 'boolean';
    case 'integer':
    case 'number': {
      if (typeof value !== 'number' || Number.isNaN(value)) return false;
      if (parameter.type === 'integer' && !Number.isInteger(value)) return false;
      return (parameter.min === undefined || value >= parameter.min) && (parameter.max === undefined || value <= parameter.max);
    }
    default: return typeof value === 'string';
  }
}

/** kebab-case key used as the control's accessible name, e.g. aspectRatio → aspect-ratio. */
export function parameterLabelId(key: string): string {
  return key.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase();
}
