import { create } from 'zustand';

import type { ModelInfo } from '../models/modelStore';
import { resolveParameters } from '../models/modelStore';

/** A model's price per generation (from models/*.json "credits"; see api/app/credits.py). */
export interface ModelPrice {
  base: number;
  /** parameter key -> chosen value written as text -> factor */
  multiply: Record<string, Record<string, number>>;
}

export interface CreditEntry {
  id: number;
  delta: number;
  kind: 'welcome' | 'top_up' | 'generation' | 'refund' | 'chat' | string;
  label: string;
  balanceAfter: number;
  /** Agent turns: what the turn really used (delta is the whole credits taken from the balance). */
  used?: number;
  createdAt: string;
}

interface CreditState {
  balance: number | null;
  /** Usage not yet taken from the balance (under 1 credit; taken once it adds up). */
  pending: number;
  entries: CreditEntry[];
  load: () => Promise<void>;
  topUp: (amount: number) => Promise<void>;
  /** A server answer that already says the new balance (agent turn finished, …). */
  setBalance: (balance: number) => void;
}

const base = () => import.meta.env.VITE_API_BASE_URL ?? '/api';
let loading: Promise<void> | null = null;
let again = false;

export const useCreditStore = create<CreditState>((set, get) => ({
  balance: null,
  pending: 0,
  entries: [],
  async load() {
    // Many events can arrive at once (a batch of generations): one request at a time, plus one after.
    if (loading) {
      again = true;
      return loading;
    }
    loading = (async () => {
      try {
        const response = await fetch(`${base()}/credits`);
        if (response.ok) {
          const body = (await response.json()) as { balance: number; pending?: number; entries: CreditEntry[] };
          set({ balance: body.balance, pending: body.pending ?? 0, entries: body.entries ?? [] });
        }
      } catch {
        /* offline: keep what we have */
      } finally {
        loading = null;
        if (again) {
          again = false;
          void get().load();
        }
      }
    })();
    return loading;
  },
  async topUp(amount) {
    const response = await fetch(`${base()}/credits/top-up`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount }),
    });
    if (!response.ok) throw new Error('充值失败');
    const body = (await response.json()) as { balance: number; pending?: number; entries: CreditEntry[] };
    set({ balance: body.balance, pending: body.pending ?? 0, entries: body.entries ?? [] });
  },
  setBalance(balance) {
    set({ balance });
    void get().load();
  },
}));

/** Exact usage for display: up to 2 decimals, "<0.01" for crumbs (2.23, 0.5, 3). */
export function formatUsage(value: number): string {
  if (value > 0 && value < 0.01) return '<0.01';
  return String(Math.round(value * 100) / 100);
}

function valueKey(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

/** Credits one generation costs: base × the factors of the chosen values, rounded up (same as the server). */
export function generationPrice(model: ModelInfo | undefined, parameters?: Record<string, unknown>): number | null {
  if (!model?.credits) return null;
  const values = resolveParameters(model, parameters);
  let amount = model.credits.base;
  for (const [key, table] of Object.entries(model.credits.multiply ?? {})) {
    amount *= table[valueKey(values[key])] ?? 1;
  }
  return Math.max(0, Math.ceil(Math.round(amount * 1e6) / 1e6));
}
