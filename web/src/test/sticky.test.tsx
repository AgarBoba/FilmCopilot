import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReactFlowProvider } from '@xyflow/react';
import { describe, expect, it, vi } from 'vitest';

import { CanvasRail } from '../canvas/CanvasRail';
import { editStickyWhenItAppears, StickyNode, stickyTitle } from '../nodes/StickyNode';

describe('sticky (便签)', () => {
  it('shows the first line bold and saves text with its first line as the name', () => {
    const onStickyChange = vi.fn();
    const { container } = render(
      <ReactFlowProvider>
        <StickyNode id="s1" data={{ content: '开场\n清晨厨房，暖光', color: 'blue', textSize: 'l', onStickyChange }} />
      </ReactFlowProvider>,
    );
    expect(container.querySelector('.sticky-title')).toHaveTextContent('开场');
    expect(container.querySelector('.sticky-body')).toHaveTextContent('清晨厨房，暖光');
    expect(container.querySelector('.sticky-node')).toHaveClass('is-l');
    expect(container.querySelector('.sticky-node')).toHaveStyle({ background: '#A9CDF2' });
    expect(container.querySelector('.react-flow__handle')).toBeNull(); // no ports

    fireEvent.doubleClick(screen.getByRole('button', { name: /便签内容/ }));
    const textarea = screen.getByLabelText('便签内容');
    fireEvent.change(textarea, { target: { value: '\n质感特写\n木纹' } });
    fireEvent.blur(textarea);
    expect(onStickyChange).toHaveBeenCalledWith({ content: '\n质感特写\n木纹', title: '质感特写' });
  });

  it('a new sticky opens straight into typing', () => {
    editStickyWhenItAppears('s2');
    render(<ReactFlowProvider><StickyNode id="s2" data={{ content: '' }} /></ReactFlowProvider>);
    expect(screen.getByLabelText('便签内容')).toHaveFocus();
  });

  it('names come from the first non-empty line', () => {
    expect(stickyTitle('  \n 开场 \n说明')).toBe('开场');
    expect(stickyTitle('')).toBe('便签');
  });

  it('the + menu is icon and name only, with 便签 and its S key', async () => {
    const onAddNode = vi.fn();
    render(<CanvasRail onAddNode={onAddNode} onUpload={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: '添加节点' }));
    const items = screen.getAllByRole('menuitem');
    expect(items.map((item) => item.textContent)).toEqual(['图片', '视频', '文本', '便签S']);
    expect(items[3]).toHaveAttribute('data-tooltip', '区域说明，不参与生成');
    await userEvent.click(items[3]);
    expect(onAddNode).toHaveBeenCalledWith('sticky');
  });
});
