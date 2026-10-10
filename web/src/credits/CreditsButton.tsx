import { useEffect, useRef, useState } from 'react';

import { CoinIcon } from '../canvas/icons';
import { formatUsage, useCreditStore, type CreditEntry } from './creditStore';

const QUICK = [100, 500, 2000];
const LOW = 50;

export function formatCredits(value: number): string {
  return value.toLocaleString('en-US');
}

/** SQLite's CURRENT_TIMESTAMP is UTC without a zone. Today: 14:05; otherwise 10月3日. */
function when(createdAt: string, now = new Date()): string {
  const date = new Date(`${createdAt.replace(' ', 'T')}Z`);
  if (Number.isNaN(date.getTime())) return '';
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
  }
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

/**
 * 积分 (simulated credits), top-left of the canvas: the balance, and a popover to add credits by
 * hand and see what used them. Generations and agent turns are charged on the server.
 */
export function CreditsButton() {
  const balance = useCreditStore((state) => state.balance);
  const entries = useCreditStore((state) => state.entries);
  const pending = useCreditStore((state) => state.pending);
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void useCreditStore.getState().load();
  }, []);

  useEffect(() => {
    if (!open) return;
    void useCreditStore.getState().load();
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

  async function topUp(amount: number) {
    if (!Number.isInteger(amount) || amount < 1 || amount > 100_000) {
      setError('填 1 到 100000 的整数');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await useCreditStore.getState().topUp(amount);
      setCustom('');
    } catch {
      setError('充值失败，检查本地 API 是否在运行');
    } finally {
      setBusy(false);
    }
  }

  const state = balance === null ? '' : balance <= 0 ? 'is-empty' : balance < LOW ? 'is-low' : '';
  const shown = balance === null ? '—' : formatCredits(balance);

  return (
    <div className="credits" ref={rootRef}>
      <button
        type="button"
        className={`credits-pill ${state} ${open ? 'is-open' : ''}`}
        aria-label={`积分：${shown}`}
        aria-expanded={open}
        data-tooltip={open ? undefined : balance !== null && balance <= 0 ? '积分用完了，点这里充值' : '积分（模拟）'}
        data-tooltip-side="bottom"
        onClick={() => setOpen(!open)}
      >
        <CoinIcon width={16} height={16} />
        <span className="credits-amount">{shown}</span>
      </button>
      {open && (
        <div className="credits-popover nowheel" role="dialog" aria-label="积分">
          <div className="credits-head">
            <span className="credits-title">积分</span>
            <span className="credits-tag">模拟</span>
          </div>
          <div className={`credits-balance ${state}`}>{shown}</div>
          {pending > 0 && (
            <div className="credits-pending" data-tooltip="Agent 对话按实际用量记账，余额只扣整数，零头攒够 1 再扣">
              另有 {formatUsage(pending)} 待扣
            </div>
          )}
          <p className="credits-hint">生成图片、视频按模型和参数扣；和 Agent 对话按实际用量扣（1 积分 ≈ $0.01）。失败或撤销的生成会退回。</p>

          <div className="credits-section-label">充值</div>
          <div className="credits-topup">
            {QUICK.map((amount) => (
              <button key={amount} type="button" className="credits-chip" disabled={busy} onClick={() => void topUp(amount)}>
                +{formatCredits(amount)}
              </button>
            ))}
          </div>
          <form
            className="credits-custom"
            onSubmit={(event) => {
              event.preventDefault();
              void topUp(Number(custom));
            }}
          >
            <input
              type="number"
              inputMode="numeric"
              placeholder="自定义数量"
              aria-label="充值数量"
              value={custom}
              onChange={(event) => setCustom(event.target.value)}
            />
            <button type="submit" disabled={busy || !custom}>充值</button>
          </form>
          {error && <div className="credits-error" role="alert">{error}</div>}

          <div className="credits-section-label">最近</div>
          <ul className="credits-history">
            {entries.length === 0 && <li className="credits-empty">还没有记录</li>}
            {entries.slice(0, 20).map((entry) => <HistoryRow key={entry.id} entry={entry} />)}
          </ul>
        </div>
      )}
    </div>
  );
}

function HistoryRow({ entry }: { entry: CreditEntry }) {
  return (
    <li className="credits-row">
      <span className="credits-row-label" title={entry.label}>{entry.label}</span>
      <span className="credits-row-time">{when(entry.createdAt)}</span>
      <span
        className={`credits-row-delta ${entry.delta > 0 ? 'is-plus' : ''}`}
        data-tooltip={entry.used !== undefined ? `实际用量 ${formatUsage(entry.used)}，这次从余额扣 ${Math.abs(entry.delta)}` : undefined}
        data-tooltip-side="left"
      >
        {entry.used !== undefined ? `−${formatUsage(entry.used)}` : `${entry.delta > 0 ? '+' : '−'}${formatCredits(Math.abs(entry.delta))}`}
      </span>
    </li>
  );
}
