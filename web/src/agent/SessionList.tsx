import { useEffect, useRef, useState } from 'react';

import { ArchiveIcon, ChevronLeftIcon, PencilIcon, PlusIcon, SearchIcon } from '../canvas/icons';
import type { AgentSession } from './agentApi';
import type { SessionFilter } from './agentStore';
import { assetFileUrl, describeAnchor, STATUS_LABELS, type CanvasComment } from '../comments/commentApi';

interface SessionListProps {
  sessions: AgentSession[];
  /** Canvas comments: each is a chat of its own, listed with its pin's status. */
  comments?: CanvasComment[];
  filter?: SessionFilter;
  onFilterChange?: (filter: SessionFilter) => void;
  /** Only this node's comments (from the comment badge on a node). */
  nodeFilter?: string | null;
  onClearNodeFilter?: () => void;
  nodeTitles?: Record<string, string>;
  onOpenComment?: (comment: CanvasComment) => void;
  currentId: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
  onBack: () => void;
  onRename: (id: string, title: string) => void;
  onArchive: (id: string, archived: boolean) => void;
}

/** SQLite timestamps are UTC without a zone ("2026-09-24 02:50:23"). */
export function parseTime(value?: string | null): Date | null {
  if (!value) return null;
  const date = new Date(`${value.replace(' ', 'T')}${/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? '' : 'Z'}`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function dayGroup(date: Date | null, now: Date): string {
  if (!date) return '更早';
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const time = date.getTime();
  if (time >= start) return '今天';
  if (time >= start - 86_400_000) return '昨天';
  if (time >= start - 6 * 86_400_000) return '最近 7 天';
  return '更早';
}

function shortTime(date: Date | null, now: Date): string {
  if (!date) return '';
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

const STATUS_LABEL = { running: '运行中', waiting: '等你确认', idle: '' } as const;

/**
 * All chats on this canvas: search, grouped by last activity, with live status. Archived
 * chats sit in a collapsed section at the bottom and can be restored.
 */
type Entry =
  | { type: 'chat'; time: string; session: AgentSession }
  | { type: 'comment'; time: string; comment: CanvasComment };

const FILTERS: { value: SessionFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'comment', label: '留言' },
  { value: 'chat', label: '对话' },
];

export function SessionList({
  sessions, comments = [], filter = 'all', onFilterChange, nodeFilter = null, onClearNodeFilter, nodeTitles = {},
  onOpenComment, currentId, onOpen, onNew, onBack, onRename, onArchive,
}: SessionListProps) {
  const [query, setQuery] = useState('');
  const [showArchived, setShowArchived] = useState(false);
  const [showResolved, setShowResolved] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const now = new Date();

  useEffect(() => searchRef.current?.focus(), []);

  const needle = query.trim().toLowerCase();
  const matches = (session: AgentSession) => !needle
    || `${session.title ?? ''} ${session.preview ?? ''}`.toLowerCase().includes(needle);
  const commentMatches = (comment: CanvasComment) => !needle
    || `${comment.text} ${comment.outcome ?? ''}`.toLowerCase().includes(needle);
  const showChats = filter !== 'comment' && !nodeFilter;
  const showComments = filter !== 'chat';
  // Chats nobody wrote in yet are noise, except the one that is open. Comment chats are
  // listed through their comment instead.
  const visible = showChats
    ? sessions.filter((s) => s.kind !== 'comment').filter((s) => (s.message_count ?? 0) > 0 || s.id === currentId).filter(matches)
    : [];
  const listedComments = showComments
    ? comments.filter((c) => !nodeFilter || c.anchor.nodeId === nodeFilter).filter(commentMatches)
    : [];
  const resolved = listedComments.filter((c) => c.status === 'resolved')
    .sort((a, b) => (b.resolvedAt ?? b.updatedAt).localeCompare(a.resolvedAt ?? a.updatedAt));
  const archived = visible.filter((s) => s.archived_at);
  const entries: Entry[] = [
    ...visible.filter((s) => !s.archived_at)
      .map((session): Entry => ({ type: 'chat', time: session.last_active_at ?? session.created_at, session })),
    ...listedComments.filter((c) => c.status !== 'resolved')
      .map((comment): Entry => ({ type: 'comment', time: comment.updatedAt, comment })),
  ].sort((a, b) => (parseTime(b.time)?.getTime() ?? 0) - (parseTime(a.time)?.getTime() ?? 0));

  const groups: { label: string; items: Entry[] }[] = [];
  for (const entry of entries) {
    const label = dayGroup(parseTime(entry.time), now);
    const group = groups.find((item) => item.label === label);
    if (group) group.items.push(entry);
    else groups.push({ label, items: [entry] });
  }
  const openCount = comments.filter((c) => c.status !== 'resolved').length;

  const commentRow = (comment: CanvasComment) => {
    const where = describeAnchor(comment.anchor, nodeTitles);
    const thumb = comment.anchor.kind === 'media' && comment.anchor.assetId && comment.anchor.time == null
      ? assetFileUrl(comment.anchor.assetId) : null;
    return (
      <li key={comment.id} className={`session-item is-comment is-${comment.status} ${comment.sessionId === currentId ? 'is-current' : ''}`}>
        <button type="button" className="session-open" onClick={() => onOpenComment?.(comment)}>
          <span className={`session-pin is-${comment.status}`} aria-hidden="true" />
          <span className="session-main">
            <span className="session-title-row">
              <span className="session-title">{comment.text}</span>
              <span className="session-status">{STATUS_LABELS[comment.status]}</span>
              <span className="session-time">{shortTime(parseTime(comment.updatedAt), now)}</span>
            </span>
            <span className="session-preview">
              {where}{comment.nodeMissing ? '（节点已删除）' : ''}{comment.outcome ? ` · ${comment.outcome}` : ''}
            </span>
          </span>
          {thumb && <img className="session-thumb" src={thumb} alt="" loading="lazy" />}
        </button>
      </li>
    );
  };

  const row = (session: AgentSession) => {
    const status = session.status ?? 'idle';
    const isArchived = !!session.archived_at;
    return (
      <li key={session.id} className={`session-item ${session.id === currentId ? 'is-current' : ''} is-${status}`}>
        {renaming === session.id ? (
          <RenameField
            initial={session.title || ''}
            onDone={(title) => {
              setRenaming(null);
              if (title !== null && title.trim() && title.trim() !== session.title) onRename(session.id, title.trim());
            }}
          />
        ) : (
          <button type="button" className="session-open" onClick={() => onOpen(session.id)}>
            <span className="session-status-dot" aria-hidden="true" />
            <span className="session-main">
              <span className="session-title-row">
                <span className="session-title">{session.title || '新对话'}</span>
                {status !== 'idle' && <span className="session-status">{STATUS_LABEL[status]}</span>}
                <span className="session-time">{shortTime(parseTime(session.last_active_at ?? session.created_at), now)}</span>
              </span>
              {session.preview && <span className="session-preview">{session.preview}</span>}
            </span>
          </button>
        )}
        {renaming !== session.id && (
          <span className="session-actions">
            {isArchived ? (
              <button type="button" className="session-restore" onClick={() => onArchive(session.id, false)}>恢复</button>
            ) : (
              <>
                <button type="button" aria-label="重命名" data-tooltip="重命名" data-tooltip-side="left"
                  onClick={() => setRenaming(session.id)}>
                  <PencilIcon width={14} height={14} />
                </button>
                <button type="button" aria-label="归档" data-tooltip="归档（记录保留，可恢复）" data-tooltip-side="left"
                  disabled={status !== 'idle'} onClick={() => onArchive(session.id, true)}>
                  <ArchiveIcon width={14} height={14} />
                </button>
              </>
            )}
          </span>
        )}
      </li>
    );
  };

  return (
    <div className="session-list">
      <div className="session-list-head">
        <button type="button" className="session-back" onClick={onBack} disabled={!currentId && !sessions.length}>
          <ChevronLeftIcon width={16} height={16} /> 全部对话
        </button>
        <button type="button" className="session-new" onClick={onNew}>
          <PlusIcon width={14} height={14} /> 新对话
        </button>
      </div>
      <label className="session-search">
        <SearchIcon width={14} height={14} />
        <input
          ref={searchRef}
          value={query}
          placeholder="搜索对话"
          aria-label="搜索对话"
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Escape') onBack(); }}
        />
      </label>
      {onFilterChange && (
        <div className="session-filters" role="tablist" aria-label="筛选">
          {FILTERS.map((item) => (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={filter === item.value}
              className={filter === item.value ? 'is-active' : ''}
              onClick={() => onFilterChange(item.value)}
            >
              {item.label}
              {item.value === 'comment' && openCount > 0 && <span className="session-filter-count">{openCount}</span>}
            </button>
          ))}
        </div>
      )}
      {nodeFilter && (
        <div className="session-node-filter">
          只看「{nodeTitles[nodeFilter] || '这个节点'}」的留言
          <button type="button" aria-label="看全部留言" onClick={onClearNodeFilter}>×</button>
        </div>
      )}
      <div className="session-scroll">
        {!entries.length && (
          <div className="session-empty">
            {needle ? '没有找到相关内容'
              : filter === 'comment' || nodeFilter ? '还没有留言。按 C 进入留言模式，在画布上点一下就能留'
                : '这张画布上还没有对话'}
          </div>
        )}
        {groups.map((group) => (
          <section key={group.label}>
            <h3 className="session-group">{group.label}</h3>
            <ul>{group.items.map((entry) => (entry.type === 'chat' ? row(entry.session) : commentRow(entry.comment)))}</ul>
          </section>
        ))}
        {resolved.length > 0 && (
          <section className="session-archived">
            <button type="button" className="session-group session-archived-toggle" onClick={() => setShowResolved(!showResolved)}>
              已解决（{resolved.length}）{showResolved ? '▾' : '▸'}
            </button>
            {showResolved && <ul>{resolved.map(commentRow)}</ul>}
          </section>
        )}
        {archived.length > 0 && (
          <section className="session-archived">
            <button type="button" className="session-group session-archived-toggle" onClick={() => setShowArchived(!showArchived)}>
              已归档（{archived.length}）{showArchived ? '▾' : '▸'}
            </button>
            {showArchived && <ul>{archived.map(row)}</ul>}
          </section>
        )}
      </div>
    </div>
  );
}


function RenameField({ initial, onDone }: { initial: string; onDone: (title: string | null) => void }) {
  const [value, setValue] = useState(initial);
  const ref = useRef<HTMLInputElement>(null);
  const done = useRef(false);
  const finish = (title: string | null) => {
    if (done.current) return; // Enter then blur must not rename twice
    done.current = true;
    onDone(title);
  };
  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);
  return (
    <input
      ref={ref}
      className="session-rename"
      aria-label="对话名称"
      value={value}
      maxLength={60}
      onChange={(event) => setValue(event.target.value)}
      onBlur={() => finish(value)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' && !event.nativeEvent.isComposing) finish(value);
        if (event.key === 'Escape') finish(null);
      }}
    />
  );
}
