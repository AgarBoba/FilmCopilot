import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SessionList } from '../agent/SessionList';
import type { AgentSession } from '../agent/agentApi';
import { anchorAt } from '../comments/CommentLayer';
import { describeAnchor, pinState, type CanvasComment } from '../comments/commentApi';
import { buildThread, timeAgo } from '../comments/thread';
import { queuePosition, useCommentStore } from '../comments/commentStore';
import { mediaToScreen, screenToMedia, sideOf } from '../comments/mediaGeometry';
import { CommentBadge } from '../nodes/CommentBadge';
import { VideoPlayer } from '../nodes/VideoPlayer';


function comment(overrides: Partial<CanvasComment> & { id: string }): CanvasComment {
  return {
    canvasId: 'c', sessionId: `s-${overrides.id}`, anchor: { kind: 'canvas', x: 0, y: 0 }, text: '留言', author: 'user',
    status: 'open', agentStatus: 'done', outcome: null, replies: [], nodeMissing: false, createdAt: '2026-10-08 06:00:00',
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
    // Only looking (the hover hint) leaves a playing video alone.
    const fresh = document.createElement('video');
    document.querySelector('.media-preview')!.replaceChildren(fresh);
    Object.defineProperty(fresh, 'paused', { value: false, configurable: true });
    fresh.pause = vi.fn();
    fresh.getBoundingClientRect = video.getBoundingClientRect;
    expect(anchorAt(50, 50, fresh, null, true)).toMatchObject({ kind: 'media', time: 0 });
    expect(fresh.pause).not.toHaveBeenCalled();
    expect(fresh.dataset.held).toBeUndefined();
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
    store.upsert(comment({ id: 'a', agentStatus: 'running', updatedAt: '2026-10-08 06:00:05' }));
    store.upsert(comment({ id: 'a', agentStatus: 'queued', updatedAt: '2026-10-08 06:00:01' }));
    expect(useCommentStore.getState().comments[0].agentStatus).toBe('running');
    store.upsert(comment({ id: 'b', agentStatus: 'queued', updatedAt: '2026-10-08 06:00:03' }));
    store.upsert(comment({ id: 'c', agentStatus: 'queued', updatedAt: '2026-10-08 06:00:02' }));
    expect(queuePosition(useCommentStore.getState().comments, 'b')).toBe(2);
    expect(queuePosition(useCommentStore.getState().comments, 'c')).toBe(1);
    store.drop('b');
    expect(useCommentStore.getState().comments.map((item) => item.id)).toEqual(['a', 'c']);
  });

  it('says what a pin shows: note, agent progress, or resolved', () => {
    expect(pinState(comment({ id: 'n', agentStatus: null }))).toBe('note');
    expect(pinState(comment({ id: 'w', agentStatus: 'waiting' }))).toBe('waiting');
    expect(pinState(comment({ id: 'r', agentStatus: 'done', status: 'resolved' }))).toBe('resolved');
  });
});


describe('panel list', () => {
  const sessions: AgentSession[] = [
    { id: 'chat1', project_id: 'p', canvas_id: 'c', title: '主对话', created_at: '2026-10-08 05:00:00', message_count: 3, last_active_at: '2026-10-08 05:00:00' },
    { id: 's-w', project_id: 'p', canvas_id: 'c', title: '把天空换成黄昏', created_at: '2026-10-08 05:00:00', message_count: 2, kind: 'comment' },
  ];
  const comments = [
    comment({ id: 'w', text: '把天空换成黄昏', agentStatus: 'waiting', anchor: { kind: 'media', nodeId: 'n1', version: 1, x: 0.5, y: 0.5 } }),
    comment({ id: 'r', text: '已经改好的那条', status: 'resolved', agentStatus: null, resolvedAt: '2026-10-08 06:10:00', anchor: { kind: 'node', nodeId: 'n2' } }),
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


describe('comment mode', () => {
  it('drops back to the normal pointer after one pin, unless Shift is held', async () => {
    const { CommentLayer } = await import('../comments/CommentLayer');
    const viewport = document.createElement('div');
    viewport.innerHTML = '<div class="react-flow__pane" id="pane"></div>';
    document.body.appendChild(viewport);
    const flow = {
      screenToFlowPosition: (point: { x: number; y: number }) => point,
      flowToScreenPosition: (point: { x: number; y: number }) => point,
      fitView: () => undefined, setCenter: () => undefined, getViewport: () => ({ zoom: 1 }),
    };
    vi.stubGlobal('EventSource', undefined);
    vi.stubGlobal('PointerEvent', MouseEvent); // jsdom has none; MouseEvent carries button and shiftKey
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ comments: [] }))));
    render(<CommentLayer canvasId="c" revision={0} viewportRef={{ current: viewport }} flowRef={{ current: flow }}
      selectedNodeIds={[]} nodeTitles={{}} onOpenInPanel={vi.fn()} onFocusNodes={vi.fn()} onSaveToCanvas={vi.fn()} />);
    const pane = document.getElementById('pane')!;

    act(() => useCommentStore.getState().setMode(true));
    fireEvent.pointerDown(pane, { button: 0, clientX: 10, clientY: 20, shiftKey: true });
    expect(useCommentStore.getState().mode).toBe(true);
    expect(useCommentStore.getState().draft?.anchor).toEqual({ kind: 'canvas', x: 10, y: 20 });

    fireEvent.pointerDown(pane, { button: 0, clientX: 30, clientY: 40 });
    expect(useCommentStore.getState().mode).toBe(false);
    expect(useCommentStore.getState().draft?.anchor).toEqual({ kind: 'canvas', x: 30, y: 40 }); // still typing
    vi.unstubAllGlobals();
    viewport.remove();
  });
});


describe('comment popover', () => {
  it('offers to undo the round that just finished', async () => {
    const { CommentPopover } = await import('../comments/CommentPopover');
    const { agentApi } = await import('../agent/agentApi');
    const history = [
      { id: 1, runId: 'r1', kind: 'user_message' as const, text: '加个便签' },
      { id: 2, runId: 'r1', kind: 'tool_step' as const, tool: 'create_nodes', summary: '新建 1 个节点', touched: ['n'] },
      { id: 3, runId: 'r1', kind: 'run_finished' as const, status: 'completed' as const },
    ];
    vi.spyOn(agentApi, 'messages').mockResolvedValue(history);
    vi.spyOn(agentApi, 'stream').mockReturnValue(() => undefined);
    const undo = vi.spyOn(agentApi, 'undo').mockResolvedValue({ id: 4, runId: 'r1', kind: 'run_undone' });
    render(<CommentPopover comment={comment({ id: 'c1' })} at={{ x: 10, y: 10 }} bounds={{ width: 1000, height: 800 }}
      where="画布空白处" onClose={vi.fn()} onOpenInPanel={vi.fn()} onFocusNodes={vi.fn()} onSaveToCanvas={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: '撤销' }));
    expect(undo).toHaveBeenCalledWith('r1');
    expect(screen.getByRole('button', { name: '看过程（1 步）' })).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  function popover(target: CanvasComment) {
    return import('../comments/CommentPopover').then(({ CommentPopover }) => render(
      <CommentPopover comment={target} at={{ x: 10, y: 10 }} bounds={{ width: 1000, height: 800 }}
        where="画布空白处" onClose={vi.fn()} onOpenInPanel={vi.fn()} onFocusNodes={vi.fn()} onSaveToCanvas={vi.fn()} />,
    ));
  }

  it('a plain note is a thread: replies stay notes unless @Agent is ticked or typed', async () => {
    const note = comment({ id: 'n1', sessionId: null, agentStatus: null, text: '光线有点冷',
      replies: [{ id: 1, text: '暖一点', author: 'user', toAgent: false, createdAt: '2026-10-08 06:01:00' }] });
    useCommentStore.setState({ comments: [note] });
    const reply = vi.spyOn(useCommentStore.getState(), 'reply').mockResolvedValue(true);
    await popover(note);
    expect(screen.getByText('光线有点冷')).toBeInTheDocument();
    expect(screen.getByText('暖一点')).toBeInTheDocument();
    const box = screen.getByRole('textbox', { name: '回复留言' });
    const tick = screen.getByRole('checkbox', { name: /@Agent 让它处理/ });
    expect(tick).not.toBeChecked();
    await userEvent.type(box, '回头再说{Enter}');
    expect(reply).toHaveBeenLastCalledWith('n1', '回头再说', false);
    // Ticked by hand: "@Agent" goes in front.
    await userEvent.click(tick);
    await userEvent.type(box, '再亮一点{Enter}');
    expect(reply).toHaveBeenLastCalledWith('n1', '@Agent 再亮一点', true);
    await userEvent.click(tick);
    expect(tick).not.toBeChecked();
    // Typing "@Agent" ticks the box; the text goes as typed.
    await userEvent.type(box, '@Agent 换成暖色');
    expect(tick).toBeChecked();
    await userEvent.keyboard('{Enter}');
    expect(reply).toHaveBeenLastCalledWith('n1', '@Agent 换成暖色', true);
    vi.restoreAllMocks();
  });

  it('the menu hands a note to the agent, and deletes only on the second click', async () => {
    const note = comment({ id: 'n2', sessionId: null, agentStatus: null });
    useCommentStore.setState({ comments: [note] });
    const handOff = vi.spyOn(useCommentStore.getState(), 'handOff').mockResolvedValue();
    const remove = vi.spyOn(useCommentStore.getState(), 'remove').mockResolvedValue(true);
    await popover(note);
    await userEvent.click(screen.getByRole('button', { name: '更多' }));
    await userEvent.click(screen.getByRole('menuitem', { name: '让 Agent 处理' }));
    expect(handOff).toHaveBeenCalledWith('n2');
    await userEvent.click(screen.getByRole('button', { name: '更多' }));
    await userEvent.click(screen.getByRole('menuitem', { name: '删除' }));
    expect(remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('menuitem', { name: '确认删除？' }));
    expect(remove).toHaveBeenCalledWith('n2');
    vi.restoreAllMocks();
  });

  it('while the agent works: no resolve, the tick is off, plain replies still go', async () => {
    const { agentApi } = await import('../agent/agentApi');
    vi.spyOn(agentApi, 'messages').mockResolvedValue([
      { id: 1, runId: 'r1', kind: 'user_message', text: '换成抹茶', createdAt: '2026-10-08 06:00:01' },
      { id: 2, runId: 'r1', kind: 'confirm_request', requestId: 'q1', summary: '生成 1 张', createdAt: '2026-10-08 06:00:03' },
    ]);
    vi.spyOn(agentApi, 'stream').mockReturnValue(() => undefined);
    const busy = comment({ id: 'b1', agentStatus: 'waiting', text: '@Agent 换成抹茶' });
    useCommentStore.setState({ comments: [busy] });
    await popover(busy);
    expect(await screen.findByText('· 等你确认')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '解决' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: /@Agent 让它处理/ })).toBeDisabled();
    // The conversation's own copy of the user's message is not shown twice.
    expect(screen.getAllByText(/换成抹茶/)).toHaveLength(1);
    vi.restoreAllMocks();
  });
});


describe('comment thread', () => {
  it('merges replies and agent rounds by time, skipping the agent copy of user messages', () => {
    const items = buildThread(
      { id: 'c', text: '@Agent 换成抹茶', createdAt: '2026-10-08 06:00:00',
        replies: [{ id: 1, text: '谢谢', author: 'user', toAgent: false, createdAt: '2026-10-08 06:05:00' }] },
      [
        { id: 1, runId: 'r1', kind: 'user_message', text: '@Agent 换成抹茶', createdAt: '2026-10-08 06:00:01' },
        { id: 2, runId: 'r1', kind: 'tool_step', summary: '重画「咖啡杯」', createdAt: '2026-10-08 06:00:04' },
        { id: 3, runId: 'r1', kind: 'assistant_text', text: '换好了', createdAt: '2026-10-08 06:01:00' },
        { id: 4, runId: 'r1', kind: 'run_finished', status: 'completed', createdAt: '2026-10-08 06:01:00' },
      ],
    );
    expect(items.map((item) => item.type)).toEqual(['user', 'agent', 'user']);
    const round = items[1];
    expect(round.type === 'agent' && [round.text, round.steps, round.live]).toEqual(['换好了', 1, false]);
  });

  it('says how long ago', () => {
    const now = new Date('2026-10-08T06:10:00Z');
    expect(timeAgo('2026-10-08 06:09:30', now)).toBe('刚刚');
    expect(timeAgo('2026-10-08 06:00:00', now)).toBe('10 分钟前');
    expect(timeAgo('2026-10-08 03:00:00', now)).toBe('3 小时前');
  });
});
