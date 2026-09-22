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
