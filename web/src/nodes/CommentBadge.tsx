/** How many open comments a node has, and whether one is waiting for the user. */
export interface NodeCommentSummary {
  count: number;
  waiting: boolean;
}

/**
 * "2 条留言" in the corner of a closed card. Pins are drawn only on the opened (selected)
 * card, so the work itself stays unobstructed; this says there is something to look at.
 */
export function CommentBadge({ summary, onOpen }: { summary?: NodeCommentSummary; onOpen?: () => void }) {
  if (!summary || summary.count === 0) return null;
  return (
    <button
      type="button"
      className={`comment-badge nodrag ${summary.waiting ? 'is-waiting' : ''}`}
      data-tooltip={summary.waiting ? '有留言等你确认，点开看全部' : '查看这个节点的留言'}
      data-tooltip-side="left"
      onClick={(event) => {
        event.stopPropagation();
        onOpen?.();
      }}
    >
      <span className="comment-badge-dot" aria-hidden="true" />
      {summary.count} 条留言
    </button>
  );
}
