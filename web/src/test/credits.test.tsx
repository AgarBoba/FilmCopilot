import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { turnCredits } from '../agent/turns';
import { CreditsButton } from '../credits/CreditsButton';
import { generationPrice, useCreditStore } from '../credits/creditStore';
import { FALLBACK_MODELS } from '../models/modelStore';
import { PromptComposer } from '../nodes/PromptComposer';

const [image, video] = FALLBACK_MODELS;

function respond(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  useCreditStore.setState({ balance: null, entries: [] });
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

  it('adds up what each agent turn used', () => {
    expect(turnCredits([
      { kind: 'assistant_text', text: 'hi' },
      { kind: 'run_finished', credits: 3 },
      { kind: 'run_finished' },
    ] as never)).toBe(3);
  });
});
