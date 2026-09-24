import { useEffect, useRef, useState } from 'react';

import { ArchiveIcon, ChevronLeftIcon, PencilIcon, PlusIcon, SearchIcon } from '../canvas/icons';
import type { AgentSession } from './agentApi';

interface SessionListProps {
  sessions: AgentSession[];
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
export function SessionList({ sessions, currentId, onOpen, onNew, onBack, onRename, onArchive }: SessionListProps) {
  const [query, setQuery] = useState('');
  const [showArchived, setShowArchived] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const now = new Date();

  useEffect(() => searchRef.current?.focus(), []);

  const needle = query.trim().toLowerCase();
  const matches = (session: AgentSession) => !needle
    || `${session.title ?? ''} ${session.preview ?? ''}`.toLowerCase().includes(needle);
  // Chats nobody wrote in yet are noise, except the one that is open.
  const visible = sessions.filter((s) => (s.message_count ?? 0) > 0 || s.id === currentId).filter(matches);
  const active = visible.filter((s) => !s.archived_at);
  const archived = visible.filter((s) => s.archived_at);

  const groups: { label: string; items: AgentSession[] }[] = [];
  for (const session of active) {
    const label = dayGroup(parseTime(session.last_active_at ?? session.created_at), now);
    const group = groups.find((item) => item.label === label);
    if (group) group.items.push(session);
    else groups.push({ label, items: [session] });
  }

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
      <div className="session-scroll">
        {!active.length && (
          <div className="session-empty">{needle ? '没有找到相关对话' : '这张画布上还没有对话'}</div>
        )}
        {groups.map((group) => (
          <section key={group.label}>
            <h3 className="session-group">{group.label}</h3>
            <ul>{group.items.map(row)}</ul>
          </section>
        ))}
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
