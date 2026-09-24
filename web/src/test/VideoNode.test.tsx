import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ImageNode } from '../nodes/ImageNode';
import { VideoNode } from '../nodes/VideoNode';


describe('media nodes', () => {
  it('plays only while the video node is hovered', async () => {
    const play = vi.fn().mockResolvedValue(undefined);
    const pause = vi.fn();
    render(<VideoNode data={{ assetUrl: '/video.mp4', play, pause }} />);
    await userEvent.hover(screen.getByTestId('video-node'));
    expect(play).toHaveBeenCalledOnce();
    await userEvent.unhover(screen.getByTestId('video-node'));
    expect(pause).toHaveBeenCalledOnce();
  });

  it('renders image thumbnails from direct upstream references', () => {
    render(
      <ImageNode
        data={{ assetUrl: '/main.png', references: ['/ref-a.png', '/ref-b.png'] }}
      />,
    );
    expect(screen.getByAltText('reference-1')).toBeInTheDocument();
    expect(screen.getByAltText('reference-2')).toBeInTheDocument();
  });
});

describe('generation state', () => {
  it('shows progress in the preview and disables upload and generate while running', () => {
    render(<VideoNode data={{ title: '视频 1', generationStatus: 'running', onUpload: () => undefined }} />);
    expect(screen.getByRole('status').textContent).toContain('生成中');
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    expect(screen.getByRole('menuitem', { name: '上传视频' }).getAttribute('aria-disabled')).toBe('true');
    expect((screen.getByRole('button', { name: '生成' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows the useful line of a provider error', () => {
    render(<VideoNode data={{
      generationStatus: 'failed',
      generationError: 'ReplicateError Details:\ntitle: Input validation failed\nstatus: 422\ndetail: - input.output_format: must be png or jpeg\n',
    }} />);
    expect(screen.getByRole('alert').textContent).toContain('生成失败');
    expect(screen.getByRole('alert').textContent).toContain('input.output_format: must be png or jpeg');
  });
});

describe('video node references', () => {
  it('shows image and video references, and empty upstream nodes', () => {
    const onRemove = vi.fn();
    render(
      <VideoNode
        data={{
          references: [
            { edgeId: 'e1', url: '/rabbit.png', kind: 'image', title: '胡萝卜尝试' },
            { edgeId: 'e2', url: '/clip.mp4', kind: 'video', title: '视频 2' },
            { edgeId: 'e3', kind: 'image', title: '图片 3' },
          ],
          onRemoveReference: onRemove,
        }}
      />,
    );
    expect(screen.getByAltText('reference-1')).toBeInTheDocument();
    expect(screen.getByLabelText('reference-2').tagName).toBe('VIDEO');
    expect(screen.getByText('空')).toBeInTheDocument();
    screen.getByRole('button', { name: '删除参考素材 2' }).click();
    expect(onRemove).toHaveBeenCalledWith(expect.objectContaining({ edgeId: 'e2' }));
  });
});


describe('node menu', () => {
  it('disables download and full screen until the node has content', () => {
    render(<ImageNode data={{ title: '图片 1' }} />);
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    expect(screen.getByRole('menuitem', { name: '下载' }).getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByRole('menuitem', { name: '全屏查看' }).getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByRole('menuitem', { name: '上传图片' }).getAttribute('aria-disabled')).toBe('false');
  });

  it('opens the full-screen viewer and closes it with Escape', () => {
    render(<ImageNode data={{ title: '胡萝卜尝试', assetUrl: '/rabbit.png' }} />);
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '全屏查看' }));
    expect(screen.getByRole('dialog', { name: '查看：胡萝卜尝试' })).toBeInTheDocument();
    expect(screen.queryByRole('menu')).toBeNull();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('video player controls', () => {
  it('a click on the picture reaches the node (selection); double-click plays', () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    const onNodeClick = vi.fn();
    const { container } = render(
      <div onClick={onNodeClick}><VideoNode data={{ assetUrl: '/video.mp4' }} /></div>,
    );
    const video = container.querySelector('.video-player video')!;
    fireEvent.click(video);
    expect(onNodeClick).toHaveBeenCalledOnce();
    expect(play).not.toHaveBeenCalled();
    fireEvent.doubleClick(video);
    expect(play).toHaveBeenCalledOnce();
    play.mockRestore();
  });

  it('play button takes over from hover preview', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined);
    render(<VideoNode data={{ assetUrl: '/video.mp4' }} />);
    fireEvent.click(screen.getByRole('button', { name: '播放' }));
    expect(play).toHaveBeenCalledOnce();
    // Pointer leaving must not stop a video the user started.
    fireEvent.mouseLeave(screen.getByTestId('video-node'));
    expect(pause).not.toHaveBeenCalled();
    expect(screen.getByLabelText('播放进度')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '打开声音' })).toBeInTheDocument();
    play.mockRestore();
    pause.mockRestore();
  });
});

describe('empty preview', () => {
  it('offers an upload button when the node has no content', () => {
    const onUpload = vi.fn();
    render(<ImageNode data={{ onUpload }} />);
    fireEvent.click(screen.getByRole('button', { name: '上传图片' }));
    expect(onUpload).toHaveBeenCalledOnce();
  });

  it('blocks upload while generating', () => {
    const onUpload = vi.fn();
    render(<VideoNode data={{ onUpload, generationStatus: 'running' }} />);
    fireEvent.click(screen.getByRole('button', { name: '上传视频' }));
    expect(onUpload).not.toHaveBeenCalled();
  });
});

describe('note references', () => {
  it('shows connected notes in the reference strip and says they join the prompt', () => {
    const onRemove = vi.fn();
    render(
      <ImageNode
        data={{
          references: [
            { edgeId: 'n1', kind: 'note', title: '风格', text: '温暖的午后光线，胶片质感' },
            { edgeId: 'n2', kind: 'note', title: '空的', text: '  ' },
          ],
          onRemoveReference: onRemove,
        }}
      />,
    );
    expect(screen.getByText('风格')).toBeInTheDocument();
    expect(screen.getByText('温暖的午后光线，胶片质感')).toBeInTheDocument();
    expect(screen.getByText('空便签')).toBeInTheDocument();
    // Only notes with text count.
    expect(screen.getByText(/上游 1 条便签的文字/)).toBeInTheDocument();
    expect(screen.getByLabelText('Prompt').getAttribute('placeholder')).toContain('可以留空');
    fireEvent.click(screen.getByRole('button', { name: '删除参考便签 1' }));
    expect(onRemove).toHaveBeenCalledWith(expect.objectContaining({ edgeId: 'n1' }));
  });
});

describe('locked while generating', () => {
  it('locks prompt, parameters and reference removal', () => {
    const onPromptChange = vi.fn();
    render(
      <ImageNode
        data={{
          generationStatus: 'running',
          prompt: '兔子',
          onPromptChange,
          references: [{ edgeId: 'e1', url: '/a.png', kind: 'image' }],
          onRemoveReference: vi.fn(),
        }}
      />,
    );
    const prompt = screen.getByLabelText('Prompt') as HTMLTextAreaElement;
    expect(prompt.readOnly).toBe(true);
    for (const select of screen.getAllByRole('combobox')) expect((select as HTMLSelectElement).disabled).toBe(true);
    expect(screen.queryByRole('button', { name: /删除参考素材/ })).toBeNull();
    expect(screen.getByText(/生成中，完成后才能修改/)).toBeInTheDocument();
  });
});

describe('upstream badge', () => {
  it('shows when upstream changed after the result, hidden while generating', () => {
    const { unmount } = render(<ImageNode data={{ upstreamChanges: ['「风格」的文字改了', '「参考图」的内容更新了'] }} />);
    const badge = screen.getByRole('note');
    expect(badge.textContent).toContain('上游有更新 · 2');
    expect(badge.getAttribute('data-tooltip')).toContain('「风格」的文字改了');
    unmount();
    render(<ImageNode data={{ upstreamChanges: ['x'], generationStatus: 'running' }} />);
    expect(screen.queryByRole('note')).toBeNull();
  });
});
