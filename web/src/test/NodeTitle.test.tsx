import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { NodeTitle } from '../nodes/NodeTitle';


describe('NodeTitle', () => {
  it('saves a new name on Enter', () => {
    const onChange = vi.fn();
    render(<NodeTitle title="图片 1" fallback="图片节点" onChange={onChange} />);
    const input = screen.getByRole('textbox', { name: '节点名称' });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: '  胡萝卜主图  ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledOnce();
    expect(onChange).toHaveBeenCalledWith('胡萝卜主图');
  });

  it('reverts on Escape without saving', () => {
    const onChange = vi.fn();
    render(<NodeTitle title="图片 1" fallback="图片节点" onChange={onChange} />);
    const input = screen.getByRole('textbox', { name: '节点名称' }) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '改一半' } });
    fireEvent.keyDown(input, { key: 'Escape' });
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
    expect(input.value).toBe('图片 1');
  });

  it('keeps the old name when cleared', () => {
    const onChange = vi.fn();
    render(<NodeTitle title="视频 2" fallback="视频节点" onChange={onChange} />);
    const input = screen.getByRole('textbox', { name: '节点名称' }) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
    expect(input.value).toBe('视频 2');
  });
});
