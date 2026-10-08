import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SessionList } from '../agent/SessionList';
import type { AgentSession } from '../agent/agentApi';
import { anchorAt } from '../comments/CommentLayer';
import { describeAnchor, type CanvasComment } from '../comments/commentApi';
import { queuePosition, useCommentStore } from '../comments/commentStore';
import { mediaToScreen, screenToMedia, sideOf } from '../comments/mediaGeometry';
import { CommentBadge } from '../nodes/CommentBadge';
import { VideoPlayer } from '../nodes/VideoPlayer';


function comment(overrides: Partial<CanvasComment> & { id: string }): CanvasComment {
  return {
    canvasId: 'c', sessionId: `s-${overrides.id}`, anchor: { kind: 'canvas', x: 0, y: 0 }, text: '留言', status: 'done',
    outcome: null, pendingReply: null, nodeMissing: false, createdAt: '2026-10-08 06:00:00',
    updatedAt: '2026-10-08 06:00:00', resolvedAt: null, ...overrides,
  };
}

afterEach(() => useCommentStore.setState({ comments: [], draft: null, openId: null, mode: false }));


describe('picture coordinates', () => {
  // A 400x100 picture shown in a 200x200 box with object-fit: cover: scaled to 800x200,
  // so 300 px are cropped on each side.
  const box = { left: 0, top: 0, width: 200, height: 200 };
  const natural = { width: 400, height: 100 };

  it('maps clicks into the picture and back, through the crop', () => {
    expect(screenToMedia(box, natural, { x: 100, y: 50 })).toEqual({ x: 0.5, y: 0.25 });
    const back = mediaToScreen(box, natural, { x: 0.5, y: 0.25 });
    expect(back).toEqual({ x: 100, y: 50, visible: true });
    // A spot in the cropped-off part of the picture is not drawn.
    expect(mediaToScreen(box, natural, { x: 0.05, y: 0.5 }).visible).toBe(false);
  });

  it('puts popovers beside the pin, flipping left near the edge', () => {
    expect(sideOf(100, 300, 1000)).toBe(138);
    expect(sideOf(900, 300, 1000)).toBe(588);
  });
});


describe('placing a pin', () => {
  it('pins to a spot in the picture, the node, or the canvas', () => {
    document.body.innerHTML = `
      <div class="react-flow__node" data-id="n1">
        <div class="node-topbar"><span id="bar">图片 1</span></div>
        <div class="media-preview"><img id="pic" /></div>
      </div>
      <div class="react-flow__pane" id="pane"></div>`;
    const picture = document.getElementById('pic')!;
    picture.getBoundingClientRect = () => ({ left: 100, top: 100, width: 200, height: 100, right: 300, bottom: 200, x: 100, y: 100, toJSON: () => ({}) });
    expect(anchorAt(150, 175, picture, null)).toEqual({ kind: 'media', nodeId: 'n1', x: 0.25, y: 0.75 });
    expect(anchorAt(10, 10, document.getElementById('bar')!, null)).toEqual({ kind: 'node', nodeId: 'n1' });
    const flow = {
      screenToFlowPosition: ({ x, y }: { x: number; y: number }) => ({ x: x * 2, y: y * 2 }),
      flowToScreenPosition: (point: { x: number; y: number }) => point,
      fitView: () => undefined, setCenter: () => undefined, getViewport: () => ({ zoom: 1 }),
    };
    expect(anchorAt(40, 30.4, document.getElementById('pane')!, flow)).toEqual({ kind: 'canvas', x: 80, y: 61 });
  });

  it('stops a playing video on the frame being pinned', () => {
    document.body.innerHTML = `<div class="react-flow__node" data-id="v1"><div class="media-preview"><video id="v"></video></div></div>`;
    const video = document.getElementById('v') as HTMLVideoElement;
    Object.defineProperty(video, 'paused', { value: false, configurable: true });
    Object.defineProperty(video, 'currentTime', { value: 2.345, configurable: true });
    video.pause = vi.fn();
    video.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100, right: 100, bottom: 100, x: 0, y: 0, toJSON: () => ({}) });
    expect(anchorAt(50, 50, video, null)).toEqual({ kind: 'media', nodeId: 'v1', x: 0.5, y: 0.5, time: 2.35 });
    expect(video.pause).toHaveBeenCalled();
    expect(video.dataset.held).toBe('1'); // hover preview must not rewind it
  });

  it('describes where a comment is pinned', () => {
    const titles = { n1: '图片 3' };
    expect(describeAnchor({ kind: 'canvas', x: 1, y: 2 }, titles)).toBe('画布空白处');
    expect(describeAnchor({ kind: 'media', nodeId: 'n1', version: 2, x: 0, y: 0, time: 3.24 }, titles)).toBe('「图片 3」 第 2 版 · 0:03.2');
    expect(describeAnchor({ kind: 'node', nodeId: 'gone' }, titles)).toBe('已删除的节点');
  });
});


describe('comment store', () => {
  it('keeps the newer copy and numbers the queue', () => {
    const store = useCommentStore.getState();
    store.upsert(comment({ id: 'a', status: 'running', updatedAt: '2026-10-08 06:00:05' }));
    store.upsert(comment({ id: 'a', status: 'queued', updatedAt: '2026-10-08 06:00:01' }));
    expect(useCommentStore.getState().comments[0].status).toBe('running');
    store.upsert(comment({ id: 'b', status: 'queued', updatedAt: '2026-10-08 06:00:03' }));
    store.upsert(comment({ id: 'c', status: 'queued', updatedAt: '2026-10-08 06:00:02' }));
    expect(queuePosition(useCommentStore.getState().comments, 'b')).toBe(2);
    expect(queuePosition(useCommentStore.getState().comments, 'c')).toBe(1);
  });
});


describe('panel list', () => {
  const sessions: AgentSession[] = [
    { id: 'chat1', project_id: 'p', canvas_id: 'c', title: '主对话', created_at: '2026-10-08 05:00:00', message_count: 3, last_active_at: '2026-10-08 05:00:00' },
    { id: 's-w', project_id: 'p', canvas_id: 'c', title: '把天空换成黄昏', created_at: '2026-10-08 05:00:00', message_count: 2, kind: 'comment' },
  ];
  const comments = [
    comment({ id: 'w', text: '把天空换成黄昏', status: 'waiting', anchor: { kind: 'media', nodeId: 'n1', version: 1, x: 0.5, y: 0.5 } }),
    comment({ id: 'r', text: '已经改好的那条', status: 'resolved', resolvedAt: '2026-10-08 06:10:00', anchor: { kind: 'node', nodeId: 'n2' } }),
  ];

  it('mixes chats and comments, filters them and folds resolved ones away', async () => {
    const onOpenComment = vi.fn();
    const onFilterChange = vi.fn();
    const { rerender } = render(
      <SessionList sessions={sessions} comments={comments} filter="all" onFilterChange={onFilterChange}
        nodeTitles={{ n1: '图片 1', n2: '图片 2' }} onOpenComment={onOpenComment} currentId={null}
        onOpen={vi.fn()} onNew={vi.fn()} onBack={vi.fn()} onRename={vi.fn()} onArchive={vi.fn()} />,
    );
    expect(screen.getByText('主对话')).toBeInTheDocument();
    // The comment's own chat is listed once, as the comment.
    expect(screen.getAllByText('把天空换成黄昏')).toHaveLength(1);
    expect(screen.getByText('等你确认')).toBeInTheDocument();
    expect(screen.queryByText('已经改好的那条')).not.toBeInTheDocument();
    await userEvent.click(screen.getByText(/已解决（1）/));
    expect(screen.getByText('已经改好的那条')).toBeInTheDocument();
    await userEvent.click(screen.getByText('把天空换成黄昏'));
    expect(onOpenComment).toHaveBeenCalledWith(comments[0]);
    await userEvent.click(screen.getByRole('tab', { name: /对话/ }));
    expect(onFilterChange).toHaveBeenCalledWith('chat');

    rerender(
      <SessionList sessions={sessions} comments={comments} filter="comment" onFilterChange={onFilterChange}
        nodeFilter="n2" nodeTitles={{ n1: '图片 1', n2: '图片 2' }} currentId={null}
        onOpen={vi.fn()} onNew={vi.fn()} onBack={vi.fn()} onRename={vi.fn()} onArchive={vi.fn()} />,
    );
    expect(screen.getByText('只看「图片 2」的留言')).toBeInTheDocument();
    expect(screen.queryByText('主对话')).not.toBeInTheDocument();
    expect(screen.queryByText('把天空换成黄昏')).not.toBeInTheDocument();
  });
});


describe('on the nodes', () => {
  it('shows a count badge that opens the node comments', async () => {
    const onOpen = vi.fn();
    const { container, rerender } = render(<CommentBadge summary={{ count: 2, waiting: true }} onOpen={onOpen} />);
    await userEvent.click(screen.getByText('2 条留言'));
    expect(onOpen).toHaveBeenCalled();
    expect(container.querySelector('.comment-badge.is-waiting')).not.toBeNull();
    rerender(<CommentBadge summary={{ count: 0, waiting: false }} />);
    expect(screen.queryByText(/条留言/)).not.toBeInTheDocument();
  });

  it('marks comment moments on the video progress bar; a mark jumps there and pauses', () => {
    const videoRef = createRef<HTMLVideoElement>();
    const manualRef = { current: false };
    const onMark = vi.fn();
    const duration = vi.spyOn(HTMLMediaElement.prototype, 'duration', 'get').mockReturnValue(10);
    const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined);
    render(<VideoPlayer src="/v.mp4" videoRef={videoRef} manualRef={manualRef}
      marks={[{ id: 'm1', time: 2.5, status: 'waiting', text: '这里手抖了' }]} onMark={onMark} />);
    fireEvent(videoRef.current!, new Event('loadedmetadata'));
    const mark = screen.getByRole('button', { name: /留言 0:02：这里手抖了/ });
    expect(mark).toHaveStyle({ left: '25%' });
    fireEvent.click(mark);
    expect(pause).toHaveBeenCalled();
    expect(videoRef.current!.currentTime).toBe(2.5);
    expect(onMark).toHaveBeenCalledWith('m1');
    duration.mockRestore();
    pause.mockRestore();
  });
});
