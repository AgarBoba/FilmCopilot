const BUSY_LABELS: Record<string, string> = {
  queued: '排队中…',
  running: '生成中…',
};

export function isGenerationBusy(status?: string) {
  return status === 'queued' || status === 'running';
}

interface GenerationOverlayProps {
  status?: string;
  error?: string;
}


/** Sits over the node's preview area: a spinner while generating, a notice if it failed. */
export function GenerationOverlay({ status, error }: GenerationOverlayProps) {
  if (isGenerationBusy(status)) {
    return (
      <div className="generation-overlay is-busy" role="status" aria-live="polite">
        <span className="generation-spinner" aria-hidden="true" />
        <span>{BUSY_LABELS[status as string]}</span>
      </div>
    );
  }
  if (status === 'failed') {
    return (
      <div className="generation-overlay is-failed" role="alert" data-tooltip={error}>
        <strong>生成失败</strong>
        {error && <span className="generation-error">{summarizeError(error)}</span>}
      </div>
    );
  }
  return null;
}

/** Provider errors are long multi-line dumps; show the most useful line. */
function summarizeError(error: string) {
  const lines = error.split('\n').map((line) => line.trim()).filter(Boolean);
  const detail = lines.find((line) => line.startsWith('detail:') || line.startsWith('- '));
  return (detail ?? lines[0] ?? error).replace(/^detail:\s*/, '').replace(/^-\s*/, '');
}
