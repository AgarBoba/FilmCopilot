import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { TooltipLayer } from '../canvas/TooltipLayer';


afterEach(() => vi.useRealTimers());

describe('TooltipLayer', () => {
  it('shows the data-tooltip text and shortcut after a short hover, hides on leave', () => {
    vi.useFakeTimers();
    render(
      <>
        <button type="button" aria-label="抓手工具" data-tooltip="抓手：拖动画布" data-tooltip-shortcut="H">✋</button>
        <TooltipLayer />
      </>,
    );
    const button = screen.getByRole('button', { name: '抓手工具' });
    fireEvent.pointerOver(button);
    expect(screen.queryByRole('tooltip')).toBeNull();
    act(() => { vi.advanceTimersByTime(400); });
    expect(screen.getByRole('tooltip').textContent).toBe('抓手：拖动画布H');
    fireEvent.pointerOut(button, { relatedTarget: document.body });
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('hides as soon as the user clicks', () => {
    vi.useFakeTimers();
    render(
      <>
        <button type="button" data-tooltip="放大">+</button>
        <TooltipLayer />
      </>,
    );
    fireEvent.pointerOver(screen.getByRole('button'));
    act(() => { vi.advanceTimersByTime(400); });
    expect(screen.getByRole('tooltip')).toBeTruthy();
    fireEvent.pointerDown(screen.getByRole('button'));
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
});
