import type {
  AssetSummary,
  CanvasEvent,
  CanvasSnapshot,
  CommandEnvelope,
  CommandResult,
} from '../domain/types';


const apiBase = import.meta.env.VITE_API_BASE_URL ?? '/api';

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let body: { error?: { code?: string; message?: string } } = {};
    try {
      body = await response.json();
    } catch {
      // Keep the HTTP status as the useful fallback when the server sent no JSON.
    }
    throw new ApiError(
      body.error?.code ?? 'HTTP_ERROR',
      body.error?.message ?? `Request failed with status ${response.status}`,
      response.status,
    );
  }
  return response.json() as Promise<T>;
}

export const api = {
  getSnapshot(canvasId: string): Promise<CanvasSnapshot> {
    return request<CanvasSnapshot>(`/canvases/${encodeURIComponent(canvasId)}/snapshot`);
  },

  createCanvas(name: string, canvasId?: string): Promise<CanvasSnapshot> {
    return request<CanvasSnapshot>('/canvases', {
      method: 'POST',
      body: JSON.stringify({ name, ...(canvasId ? { canvasId } : {}) }),
    });
  },

  executeCommand(
    canvasId: string,
    envelope: CommandEnvelope,
  ): Promise<CommandResult> {
    return request<CommandResult>(`/canvases/${encodeURIComponent(canvasId)}/commands`, {
      method: 'POST',
      body: JSON.stringify(envelope),
    });
  },

  uploadAsset(canvasId: string, file: File): Promise<AssetSummary> {
    const form = new FormData();
    form.set('canvasId', canvasId);
    form.set('file', file);
    return request<AssetSummary>('/assets/upload', {
      method: 'POST',
      body: form,
    });
  },

  subscribeEvents(
    canvasId: string,
    afterRevision: number,
    onEvent: (event: CanvasEvent) => void,
  ): () => void {
    const source = new EventSource(
      `${apiBase}/canvases/${encodeURIComponent(canvasId)}/events?afterRevision=${afterRevision}`,
    );
    const eventTypes = [
      'canvas.create_node',
      'canvas.update_node',
      'canvas.delete_node',
      'canvas.connect_nodes',
      'canvas.disconnect_nodes',
      'canvas.update_note',
      'canvas.attach_asset',
      'canvas.start_generation',
      'generation.running',
      'generation.completed',
      'generation.completed_unattached',
      'generation.failed',
    ];
    const handle = (message: MessageEvent<string>) => {
      try {
        onEvent(JSON.parse(message.data) as CanvasEvent);
      } catch {
        // Ignore malformed events and let the next snapshot repair the state.
      }
    };
    eventTypes.forEach((type) => source.addEventListener(type, handle));
    return () => {
      eventTypes.forEach((type) => source.removeEventListener(type, handle));
      source.close();
    };
  },
};

