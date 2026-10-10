import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { turnCredits, turnUsage, usageText } from '../agent/turns';
import { CreditsButton } from '../credits/CreditsButton';
import { formatUsage, generationPrice, useCreditStore } from '../credits/creditStore';
import { FALLBACK_MODELS } from '../models/modelStore';
import { PromptComposer } from '../nodes/PromptComposer';

const [image, video] = FALLBACK_MODELS;

function respond(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  useCreditStore.setState({ balance: null, pending: 0, entries: [] });
});

describe('credits (积分)', () => {
  it('prices a generation like the server does', () => {
    expect(generationPrice(image)).toBe(4);
    expect(generationPrice(image, { size: '1K' })).toBe(3);
    expect(generationPrice(video, { duration: 10 })).toBe(60);
    expect(generationPrice(video, { duration: 10, resolution: '480p', generateAudio: false })).toBe(24);
    expect(generationPrice({ ...image, credits: undefined })).toBeNull();
  });

  it('shows the balance, tops up by hand and lists what used credits', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/credits/top-up')) {
        expect(JSON.parse(String(init?.body))).toEqual({ amount: 500 });
        return respond({ balance: 980, entries: [
          { id: 3, delta: 500, kind: 'top_up', label: '手动充值', balanceAfter: 980, createdAt: '2026-10-10 03:00:00' },
          { id: 2, delta: -20, kind: 'generation', label: 'Seedance 2.0 Mini · 镜头 1', balanceAfter: 480, createdAt: '2026-10-10 02:00:00' },
        ] });
      }
      return respond({ balance: 480, entries: [
        { id: 2, delta: -20, kind: 'generation', label: 'Seedance 2.0 Mini · 镜头 1', balanceAfter: 480, createdAt: '2026-10-10 02:00:00' },
      ] });
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<CreditsButton />);
    const pill = await screen.findByRole('button', { name: '积分：480' });
    await userEvent.click(pill);
    const dialog = screen.getByRole('dialog', { name: '积分' });
    await waitFor(() => expect(dialog).toHaveTextContent('Seedance 2.0 Mini · 镜头 1'));
    expect(dialog).toHaveTextContent('−20');
    await userEvent.click(screen.getByRole('button', { name: '+500' }));
    await screen.findByRole('button', { name: '积分：980' });
    expect(dialog).toHaveTextContent('+500');

    await userEvent.type(screen.getByLabelText('充值数量'), '0');
    await userEvent.click(screen.getByRole('button', { name: '充值' }));
    expect(screen.getByRole('alert')).toHaveTextContent('1 到 100000');
  });

  it('the generate button says what it costs and warns when there is not enough', () => {
    useCreditStore.setState({ balance: 50 });
    const props = { prompt: 'x', onPromptChange: vi.fn(), onParametersChange: vi.fn(), onGenerate: vi.fn() };
    const { rerender } = render(<PromptComposer kind="video" parameters={{ duration: 10 }} {...props} />);
    const button = screen.getByRole('button', { name: '生成' });
    expect(button).toHaveTextContent('60');
    expect(button).toHaveClass('is-short');
    expect(button).toHaveAttribute('data-tooltip', '要 60 积分，只剩 50');
    rerender(<PromptComposer kind="video" parameters={{ duration: 5 }} {...props} />);
    expect(button).not.toHaveClass('is-short');
    expect(button).toHaveAttribute('data-tooltip', '消耗 30 积分');
  });

  it('adds up what each agent turn really used, shown to two decimals', () => {
    expect(turnCredits([
      { kind: 'assistant_text', text: 'hi' },
      { kind: 'run_finished', credits: 2.234, charged: 2 },
      { kind: 'run_finished', credits: 0.5, charged: 0 },
      { kind: 'run_finished' },
    ] as never)).toBeCloseTo(2.734);
    expect([formatUsage(2.734), formatUsage(0.5), formatUsage(3), formatUsage(0.004)]).toEqual(['2.73', '0.5', '3', '<0.01']);
  });

  it('agent usage is listed exactly, with the carried fraction under the balance', async () => {
    vi.stubGlobal('fetch', vi.fn(() => respond({ balance: 497, pending: 0.13, entries: [
      { id: 4, delta: -1, used: 0.4, kind: 'chat', label: 'Agent 对话 · Haiku 5.5', balanceAfter: 497, createdAt: '2026-10-10 03:00:00' },
      { id: 3, delta: 0, used: 0.5, kind: 'chat', label: 'Agent 对话 · Haiku 5.5', balanceAfter: 498, createdAt: '2026-10-10 02:59:00' },
    ] })));
    render(<CreditsButton />);
    await userEvent.click(await screen.findByRole('button', { name: '积分：497' }));
    const dialog = screen.getByRole('dialog', { name: '积分' });
    await waitFor(() => expect(dialog).toHaveTextContent('另有 0.13 待扣'));
    expect(dialog).toHaveTextContent('−0.4');
    expect(dialog).toHaveTextContent('−0.5');
    expect(dialog.querySelector('.credits-row-delta')).toHaveAttribute('data-tooltip', '实际用量 0.4，这次从余额扣 1');
  });

  it('breaks a turn down into cache reads, cache writes, fresh input and output', () => {
    const usage = turnUsage([
      { kind: 'run_finished', usage: { input: 300, cacheRead: 61000, cacheWrite: 3000, output: 250, requests: 3 } },
      { kind: 'run_finished', usage: { input: 200, cacheRead: 30000, cacheWrite: 0, output: 150, requests: 1 } },
      { kind: 'run_finished' },
    ] as never);
    expect(usage).toEqual({ input: 500, cacheRead: 91000, cacheWrite: 3000, output: 400, requests: 4 });
    expect(usageText(usage!)).toBe('缓存命中 96%\n读缓存 9.1万 · 写缓存 3千 · 新输入 500 · 输出 400 · 调用 4 次');
    expect(turnUsage([{ kind: 'run_finished' }] as never)).toBeNull();
  });
});
