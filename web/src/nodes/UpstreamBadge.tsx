interface UpstreamBadgeProps {
  changes?: string[];
}


/** Small pill above a node: its result was made before something upstream changed. */
export function UpstreamBadge({ changes }: UpstreamBadgeProps) {
  if (!changes?.length) return null;
  return (
    <div
      className="upstream-badge"
      role="note"
      data-tooltip={`生成这个结果之后：\n${changes.map((change) => `· ${change}`).join('\n')}\n重新生成可使用最新内容`}
      data-tooltip-side="top"
    >
      <span className="upstream-dot" aria-hidden="true" />
      上游有更新{changes.length > 1 ? ` · ${changes.length}` : ''}
    </div>
  );
}
