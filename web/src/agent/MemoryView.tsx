import { useCallback, useEffect, useRef, useState } from 'react';

import { PencilIcon, PlusIcon } from '../canvas/icons';
import { agentApi, type Memory, type MemoryLayer, type MemoryList } from './agentApi';
import { parseTime } from './SessionList';

interface MemoryViewProps {
  projectId: string;
  /** Changes whenever the agent remembers something, so the view reloads. */
  version: number;
  onBack: () => void;
}

const TABS: { layer: MemoryLayer; label: string; hint: string }[] = [
  { layer: 'project', label: '本项目', hint: '这个项目里所有对话都会用到：角色、风格、设定、已定的决定。' },
  { layer: 'preference', label: '我的偏好', hint: '你个人的习惯，所有项目通用：常用参数、审美、提示词写法。' },
];
const SOURCE_LABELS: Record<Memory['source'], string> = {
  user_stated: '你说的', user_edited: '你改过', agent_inferred: 'Agent 推断',
};

function when(value: string): string {
  const date = parseTime(value);
  if (!date) return '';
  return `${date.getMonth() + 1}/${date.getDate()}`;
}


/**
 * What the agent remembers, in the agent panel. Two tabs (project / my preferences), grouped
 * by category. Everything can be edited or deleted; older versions the agent replaced are
 * folded away under each tab.
 */
export function MemoryView({ projectId, version, onBack }: MemoryViewProps) {
  const [data, setData] = useState<MemoryList | null>(null);
  const [layer, setLayer] = useState<MemoryLayer>('project');
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await agentApi.listMemories(projectId));
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取记忆失败');
    }
  }, [projectId]);

  useEffect(() => { void load(); }, [load, version]);

  const act = async (work: () => Promise<unknown>) => {
    try {
      await work();
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '操作失败');
    }
  };

  const items = data?.[layer] ?? [];
  const active = items.filter((item) => item.status === 'active');
  const history = items.filter((item) => item.status === 'superseded');
  const categories = data?.categories[layer] ?? {};
  const groups = Object.entries(categories)
    .map(([key, label]) => ({ key, label, items: active.filter((item) => item.category === key) }))
    .filter((group) => group.items.length);
  const tab = TABS.find((item) => item.layer === layer)!;

  return (
    <div className="memory-view">
      <div className="session-list-head">
        <button type="button" className="session-back" onClick={onBack}>
          ‹ 记忆
        </button>
        <button type="button" className="session-new" onClick={() => setAdding(true)}>
          <PlusIcon width={14} height={14} /> 添加
        </button>
      </div>
      <div className="memory-tabs" role="tablist">
        {TABS.map((item) => (
          <button
            key={item.layer}
            type="button"
            role="tab"
            aria-selected={layer === item.layer}
            className={layer === item.layer ? 'is-active' : ''}
            onClick={() => { setLayer(item.layer); setAdding(false); setShowHistory(false); }}
          >
            {item.label}
            <span className="memory-count">{(data?.[item.layer] ?? []).filter((m) => m.status === 'active').length}</span>
          </button>
        ))}
      </div>
      <p className="memory-hint">{tab.hint}</p>
      {error && <div className="memory-error" role="alert">{error}</div>}

      <div className="session-scroll">
        {adding && (
          <MemoryEditor
            categories={categories}
            initialCategory={Object.keys(categories)[0] ?? 'other'}
            submitLabel="添加"
            onCancel={() => setAdding(false)}
            onSubmit={(content, category) => act(async () => {
              await agentApi.addMemory(projectId, layer, content, category);
              setAdding(false);
            })}
          />
        )}
        {!active.length && !adding && (
          <div className="session-empty">
            还没有{tab.label === '本项目' ? '项目记忆' : '偏好'}。在对话里告诉 Agent，比如「主角是一只米白色的垂耳兔」，它会记下来；也可以点右上角「添加」。
          </div>
        )}
        {groups.map((group) => (
          <section key={group.key}>
            <h3 className="session-group">{group.label}</h3>
            <ul className="memory-list">
              {group.items.map((item) => (
                <MemoryItem
                  key={item.id}
                  item={item}
                  categories={categories}
                  onSave={(content, category) => act(() => agentApi.editMemory(item.id, { content, category }))}
                  onDelete={() => act(() => agentApi.deleteMemory(item.id))}
                />
              ))}
            </ul>
          </section>
        ))}
        {history.length > 0 && (
          <section className="memory-history">
            <button type="button" className="session-group session-archived-toggle" onClick={() => setShowHistory(!showHistory)}>
              旧版本（{history.length}）{showHistory ? '▾' : '▸'}
            </button>
            {showHistory && (
              <ul className="memory-list">
                {history.map((item) => (
                  <li key={item.id} className="memory-item is-history">
                    <span className="memory-content">{item.content}</span>
                    <span className="memory-meta">{item.categoryLabel} · 已被更新 · {when(item.updated_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>
    </div>
  );
}


function MemoryItem({ item, categories, onSave, onDelete }: {
  item: Memory;
  categories: Record<string, string>;
  onSave: (content: string, category: string) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  if (editing) {
    return (
      <li className="memory-item is-editing">
        <MemoryEditor
          categories={categories}
          initialCategory={item.category}
          initialContent={item.content}
          submitLabel="保存"
          onCancel={() => setEditing(false)}
          onSubmit={async (content, category) => { await onSave(content, category); setEditing(false); }}
        />
      </li>
    );
  }
  return (
    <li className="memory-item">
      <span className="memory-content">{item.content}</span>
      <span className="memory-meta">{SOURCE_LABELS[item.source]} · {when(item.updated_at)}</span>
      <span className="session-actions memory-actions">
        {confirming ? (
          <>
            <button type="button" className="memory-confirm-delete" onClick={() => void onDelete()}>确认删除</button>
            <button type="button" className="session-restore" onClick={() => setConfirming(false)}>取消</button>
          </>
        ) : (
          <>
            <button type="button" aria-label="编辑" data-tooltip="编辑" data-tooltip-side="left" onClick={() => setEditing(true)}>
              <PencilIcon width={14} height={14} />
            </button>
            <button type="button" aria-label="删除" data-tooltip="删除这条记忆" data-tooltip-side="left" onClick={() => setConfirming(true)}>
              ×
            </button>
          </>
        )}
      </span>
    </li>
  );
}


function MemoryEditor({ categories, initialCategory, initialContent = '', submitLabel, onSubmit, onCancel }: {
  categories: Record<string, string>;
  initialCategory: string;
  initialContent?: string;
  submitLabel: string;
  onSubmit: (content: string, category: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [content, setContent] = useState(initialContent);
  const [category, setCategory] = useState(initialCategory);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  const submit = () => { if (content.trim()) void onSubmit(content.trim(), category); };
  return (
    <div className="memory-editor">
      <textarea
        ref={ref}
        aria-label="记忆内容"
        value={content}
        rows={2}
        maxLength={300}
        placeholder="一句话写清楚，例如：主角是一只米白色的垂耳兔"
        onChange={(event) => setContent(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); }
          if (event.key === 'Escape') onCancel();
        }}
      />
      <div className="memory-editor-row">
        <select aria-label="分类" value={category} onChange={(event) => setCategory(event.target.value)}>
          {Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <span className="memory-editor-spacer" />
        <button type="button" className="session-restore" onClick={onCancel}>取消</button>
        <button type="button" className="memory-submit" disabled={!content.trim()} onClick={submit}>{submitLabel}</button>
      </div>
    </div>
  );
}
