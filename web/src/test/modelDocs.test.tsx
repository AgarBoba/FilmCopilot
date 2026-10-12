import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { FALLBACK_MODELS, useModelStore } from '../models/modelStore';
import { ModelDocsButton } from '../models/ModelDocsButton';
import { CheckBadge } from '../nodes/CheckBadge';

function respond(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }));
}

const guide = (id: string, label: string) => ({
  id, label, kind: 'image', family: id, siblings: [],
  capabilities: [{ name: 'image_edit', meaning: '改图' }],
  checks: ['参考图宽高比 1:3～3:1'],
  markdown: `# ${label}\n\n## 擅长\n\n- 多图参考\n`,
  skill: 'film-copilot:prompt-craft',
  files: { json: `models/${id}.json`, guide: `models/${id}.md` },
  errors: [],
  rejections: [{ kind: 'aspect_ratio', message: '参考图的宽高比不符合', raw_error: 'aspect ratio must be', created_at: '2026-10-10 02:00:00' }],
});

afterEach(() => {
  vi.unstubAllGlobals();
  useModelStore.setState({ models: FALLBACK_MODELS, errors: [], loaded: false });
});

describe('model docs (模型说明)', () => {
  it('lists the models and shows a guide read-only, with capabilities, checks and refusals', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.endsWith('/models')) return respond({ models: FALLBACK_MODELS, errors: [] });
      if (url.endsWith('/models/capabilities')) return respond({ markdown: '| 功能 | 意思 |\n|---|---|\n| omni_reference | 全能参考 |\n', capabilities: [] });
      const id = decodeURIComponent(url.split('/models/')[1].replace('/guide', ''));
      const model = FALLBACK_MODELS.find((item) => item.id === id)!;
      return respond(guide(model.id, model.label));
    }));
    render(<ModelDocsButton />);
    await userEvent.click(screen.getByRole('button', { name: '模型说明' }));
    const dialog = screen.getByRole('dialog', { name: '模型说明' });
    await waitFor(() => expect(dialog).toHaveTextContent('多图参考'));
    expect(dialog).toHaveTextContent('image_edit');
    expect(dialog).toHaveTextContent('参考图宽高比 1:3～3:1');
    expect(dialog).toHaveTextContent('film-copilot:prompt-craft');
    expect(dialog).toHaveTextContent('最近被模型拒绝');
    expect(dialog.querySelector('textarea, input')).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: /Seedance 2.0 Mini/ }));
    await waitFor(() => expect(dialog).toHaveTextContent('models/seedance-2.0-mini.md'));
    await userEvent.click(screen.getByRole('button', { name: '功能词表' }));
    await waitFor(() => expect(dialog).toHaveTextContent('omni_reference'));
  });

  it('marks a node whose inputs do not fit its model', () => {
    const { rerender } = render(<CheckBadge problems={[
      { code: 'aspect_range', message: '「长条图」的宽高比是 1:4', severity: 'error' },
      { code: 'too_many', message: '多出来的不会发', severity: 'warning' },
    ]} />);
    const badge = screen.getByRole('alert');
    expect(badge).toHaveTextContent('不符合模型要求 · 2');
    expect(badge.getAttribute('data-tooltip')).toContain('1:4');
    rerender(<CheckBadge problems={[{ code: 'too_many', message: 'x', severity: 'warning' }]} />);
    expect(screen.getByRole('alert')).toHaveTextContent('注意');
    rerender(<CheckBadge problems={[]} />);
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
