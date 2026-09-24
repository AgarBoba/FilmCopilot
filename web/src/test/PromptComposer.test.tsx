import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import {
  getDefaultImageParameters,
  getDefaultVideoParameters,
} from '../nodes/generationParameters';
import { PromptComposer } from '../nodes/PromptComposer';


describe('PromptComposer', () => {
  it('keeps Seedream parameters inside the image Prompt input area', async () => {
    const onParametersChange = vi.fn();
    render(
      <PromptComposer
        kind="image"
        prompt=""
        parameters={getDefaultImageParameters()}
        onPromptChange={vi.fn()}
        onParametersChange={onParametersChange}
        onGenerate={vi.fn()}
      />,
    );
    expect(screen.getByTestId('prompt-composer-image')).toContainElement(screen.getByLabelText('size'));
    expect(screen.getByTestId('prompt-composer-image')).toContainElement(screen.getByLabelText('aspect-ratio'));
    await userEvent.selectOptions(screen.getByLabelText('size'), '1K');
    expect(onParametersChange).toHaveBeenCalledWith(expect.objectContaining({ size: '1K' }));
  });

  it('submits the current Seedance Prompt and parameters together', async () => {
    const onGenerate = vi.fn();
    render(
      <PromptComposer
        kind="video"
        prompt="camera move"
        parameters={getDefaultVideoParameters()}
        onPromptChange={vi.fn()}
        onParametersChange={vi.fn()}
        onGenerate={onGenerate}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '生成' }));
    expect(onGenerate).toHaveBeenCalledWith(expect.objectContaining({
      prompt: 'camera move',
      parameters: expect.objectContaining({ duration: 5, resolution: '720p' }),
    }));
  });
});

describe('PromptComposer with a model registry', () => {
  it('builds controls from the model file, switches models and warns about missing keys', async () => {
    const { useModelStore, FALLBACK_MODELS } = await import('../models/modelStore');
    useModelStore.setState({
      models: [
        ...FALLBACK_MODELS,
        {
          id: 'flux-dev', label: 'Flux Dev', kind: 'image', provider: 'fal', description: '', default: false,
          maxImages: 1, maxVideos: 0, missingEnv: ['FAL_KEY'],
          parameters: [
            { key: 'steps', label: 'Steps', type: 'integer', default: 28, min: 1, max: 50 },
            { key: 'aspectRatio', label: 'Aspect ratio', type: 'enum', default: '1:1', options: [{ value: '1:1', label: '1:1' }, { value: '16:9', label: '16:9' }] },
            { key: 'safety', label: 'Safety', type: 'boolean', default: true },
          ],
        },
      ],
    });
    const onModelChange = vi.fn();
    const onGenerate = vi.fn();
    const { rerender } = render(
      <PromptComposer kind="image" prompt="兔子" parameters={{ size: '1K', aspectRatio: '16:9' }}
        onPromptChange={vi.fn()} onParametersChange={vi.fn()} onModelChange={onModelChange} onGenerate={onGenerate} />,
    );
    await userEvent.selectOptions(screen.getByLabelText('model'), 'flux-dev');
    // 16:9 exists in both models so it is kept; the rest take Flux defaults.
    expect(onModelChange).toHaveBeenCalledWith('flux-dev', { steps: 28, aspectRatio: '16:9', safety: true });

    rerender(
      <PromptComposer kind="image" prompt="兔子" modelId="flux-dev" parameters={{ steps: 40, aspectRatio: '16:9', safety: false }}
        onPromptChange={vi.fn()} onParametersChange={vi.fn()} onModelChange={onModelChange} onGenerate={onGenerate} />,
    );
    expect(screen.getByLabelText('steps')).toHaveValue(40);
    expect(screen.getByLabelText('safety')).not.toBeChecked();
    expect(screen.getByText(/还缺 FAL_KEY/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '生成' }));
    expect(onGenerate).toHaveBeenCalledWith({ prompt: '兔子', model: 'flux-dev', parameters: { steps: 40, aspectRatio: '16:9', safety: false } });
    useModelStore.setState({ models: FALLBACK_MODELS });
  });
});
