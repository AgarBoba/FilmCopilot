import { useEffect, useRef, useState } from 'react';

import { Markdown } from '../agent/Markdown';
import { BookIcon } from '../canvas/icons';
import { useModelStore } from './modelStore';

const apiBase = import.meta.env.VITE_API_BASE_URL ?? '/api';
const VOCABULARY = '_capabilities';

/** GET /api/models/{id}/guide */
export interface ModelGuide {
  id: string;
  label: string;
  kind: 'image' | 'video';
  family: string;
  siblings: string[];
  capabilities: { name: string; meaning: string }[];
  checks: string[];
  markdown: string | null;
  skill: string | null;
  files: { json: string; guide: string };
  errors: string[];
  rejections: { kind: string; message: string; raw_error: string; created_at: string }[];
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`);
  if (!response.ok) throw new Error(String(response.status));
  return (await response.json()) as T;
}

/**
 * 模型说明, next to the credits pill: read what models/<id>.md says about each model (what the
 * canvas agent reads before using it), its capabilities, the rules nodes check, and what the
 * provider refused lately. Read-only: the files are edited in the repo, and changes show here
 * without a restart.
 */
export function ModelDocsButton() {
  const models = useModelStore((state) => state.models);
  const errors = useModelStore((state) => state.errors);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [guide, setGuide] = useState<ModelGuide | null>(null);
  const [vocabulary, setVocabulary] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const current = selected ?? models[0]?.id ?? null;

  useEffect(() => {
    if (!open) return;
    void useModelStore.getState().load();
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer, true);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer, true);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  useEffect(() => {
    if (!open || !current) return;
    let alive = true;
    setFailed(false);
    if (current === VOCABULARY) {
      getJson<{ markdown: string }>('/models/capabilities')
        .then((body) => { if (alive) setVocabulary(body.markdown); })
        .catch(() => { if (alive) setFailed(true); });
    } else {
      getJson<ModelGuide>(`/models/${encodeURIComponent(current)}/guide`)
        .then((body) => { if (alive) setGuide(body); })
        .catch(() => { if (alive) setFailed(true); });
    }
    return () => { alive = false; };
  }, [open, current]);

  const shown = guide && guide.id === current ? guide : null;
  const groups: { label: string; kind: 'image' | 'video' }[] = [
    { label: '图片', kind: 'image' }, { label: '视频', kind: 'video' },
  ];

  return (
    <div className="model-docs" ref={rootRef}>
      <button
        type="button"
        className={`credits-pill model-docs-pill ${open ? 'is-open' : ''}`}
        aria-label="模型说明"
        aria-expanded={open}
        data-tooltip={open ? undefined : '模型说明（Agent 用模型前读的文档）'}
        data-tooltip-side="bottom"
        onClick={() => setOpen(!open)}
      >
        <BookIcon width={16} height={16} />
        <span>模型</span>
        {errors.length > 0 && <span className="model-docs-alert" aria-label={`${errors.length} 个问题`} />}
      </button>
      {open && (
        <div className="model-docs-panel nowheel" role="dialog" aria-label="模型说明">
          <nav className="model-docs-nav">
            {groups.map((group) => {
              const items = models.filter((model) => model.kind === group.kind);
              if (!items.length) return null;
              return (
                <div key={group.kind}>
                  <div className="model-docs-group">{group.label}</div>
                  {items.map((model) => (
                    <button
                      key={model.id}
                      type="button"
                      className={`model-docs-item ${model.id === current ? 'is-active' : ''}`}
                      onClick={() => setSelected(model.id)}
                    >
                      <span className="model-docs-item-label">{model.label}</span>
                      {model.default && <span className="model-docs-default">默认</span>}
                      {model.hasGuide === false && <span className="model-docs-missing" data-tooltip="还没有说明文档" />}
                    </button>
                  ))}
                </div>
              );
            })}
            <div className="model-docs-group">参考</div>
            <button
              type="button"
              className={`model-docs-item ${current === VOCABULARY ? 'is-active' : ''}`}
              onClick={() => setSelected(VOCABULARY)}
            >
              <span className="model-docs-item-label">功能词表</span>
            </button>
          </nav>
          <article className="model-docs-body">
            {failed && <p className="model-docs-note">读不到说明，检查本地 API 是否在运行。</p>}
            {!failed && current === VOCABULARY && vocabulary !== null && (
              <>
                <div className="model-docs-file">models/_capabilities.md</div>
                <Markdown className="model-docs-markdown" text={vocabulary} />
              </>
            )}
            {!failed && current !== VOCABULARY && shown && <GuideView guide={shown} />}
            {errors.length > 0 && current === VOCABULARY && (
              <ul className="model-docs-errors">{errors.map((error) => <li key={error}>{error}</li>)}</ul>
            )}
          </article>
        </div>
      )}
    </div>
  );
}

function GuideView({ guide }: { guide: ModelGuide }) {
  return (
    <>
      <div className="model-docs-file">
        {guide.files.guide} · 只读，改文件后这里自动更新
      </div>
      <div className="model-docs-meta">
        <span className="model-docs-meta-label">功能</span>
        <span className="model-docs-chips">
          {guide.capabilities.length === 0 && <span className="model-docs-muted">没写</span>}
          {guide.capabilities.map((item) => (
            <span key={item.name} className="model-docs-chip" data-tooltip={item.meaning} data-tooltip-side="bottom">{item.name}</span>
          ))}
        </span>
        <span className="model-docs-meta-label">家族</span>
        <span>
          {guide.family}
          {guide.siblings.length > 0 && <span className="model-docs-muted">（还有 {guide.siblings.join('、')}）</span>}
        </span>
        {guide.skill && (
          <>
            <span className="model-docs-meta-label">提示词技能</span>
            <span><code>{guide.skill}</code></span>
          </>
        )}
        <span className="model-docs-meta-label">节点检查</span>
        <span>
          {guide.checks.length === 0
            ? <span className="model-docs-muted">没有（{guide.files.json} 的 checks）</span>
            : guide.checks.join('；')}
        </span>
      </div>
      {guide.errors.length > 0 && (
        <ul className="model-docs-errors">{guide.errors.map((error) => <li key={error}>{error}</li>)}</ul>
      )}
      {guide.markdown
        ? <Markdown className="model-docs-markdown" text={guide.markdown} />
        : <p className="model-docs-note">还没有说明文档。在 {guide.files.guide} 写一份，Agent 用这个模型前会先读它。</p>}
      {guide.rejections.length > 0 && (
        <section className="model-docs-rejections">
          <div className="model-docs-section">最近被模型拒绝</div>
          <p className="model-docs-muted">说明里没写的限制可能藏在这里，确认是规律就补进「输入限制」。</p>
          <ul>
            {guide.rejections.map((item) => (
              <li key={`${item.created_at}-${item.raw_error}`}>
                <span>{item.message}</span>
                <span className="model-docs-raw">{item.raw_error}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
