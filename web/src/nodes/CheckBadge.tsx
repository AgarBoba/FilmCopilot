import type { NodeCheckProblem } from '../domain/types';

interface CheckBadgeProps {
  problems?: NodeCheckProblem[];
}

/**
 * Small pill above a node, on the right: what's connected to it doesn't fit its model
 * (the node checks, api/app/checks). Red when generating would be refused, amber for warnings.
 */
export function CheckBadge({ problems }: CheckBadgeProps) {
  if (!problems?.length) return null;
  const errors = problems.filter((problem) => problem.severity === 'error');
  const blocking = errors.length > 0;
  return (
    <div
      className={`check-badge ${blocking ? 'is-error' : 'is-warning'}`}
      role="alert"
      data-tooltip={problems.map((problem) => `· ${problem.message}`).join('\n')}
      data-tooltip-side="top"
    >
      <span className="check-dot" aria-hidden="true" />
      {blocking ? '不符合模型要求' : '注意'}
      {problems.length > 1 ? ` · ${problems.length}` : ''}
    </div>
  );
}
