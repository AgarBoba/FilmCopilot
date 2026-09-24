import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ReactFlowProvider } from '@xyflow/react';

import type { AgentEvent } from '../agent/agentApi';
import { AgentMessage } from '../agent/AgentMessage';
import { Markdown, noteBlocks, splitNoteBlock, titleFromMarkdown } from '../agent/Markdown';
import { pendingConfirmations, undoableRuns, useAgentStore } from '../agent/agentStore';
import { NoteNode } from '../nodes/NoteNode';

const event = (fields: Partial<AgentEvent>): AgentEvent => ({ id: null, runId: 'r1', kind: 'error', ...fields });

beforeEach(() => useAgentStore.getState().reset(null));

describe('agent store', () => {
  it('streams text, then replaces it with the full message', () => {
    const { apply } = useAgentStore.getState();
    apply(event({ id: 1, kind: 'user_message', text: '做三个版本' }));
    apply(event({ kind: 'text_delta', text: '好的，' }));
    apply(event({ kind: 'text_delta', text: '我先看看画布' }));
    expect(useAgentStore.getState().streaming.r1).toBe('好的，我先看看画布');
    expect(useAgentStore.getState().activeRunId).toBe('r1');
    apply(event({ id: 2, kind: 'assistant_text', text: '好的，我先看看画布' }));
    expect(useAgentStore.getState().streaming.r1).toBeUndefined();
    apply(event({ id: 3, kind: 'run_finished', status: 'completed' }));
    expect(useAgentStore.getState().activeRunId).toBeNull();
  });

  it('ignores events replayed after a reconnect', () => {
    const { apply } = useAgentStore.getState();
    apply(event({ id: 5, kind: 'assistant_text', text: 'a' }));
    apply(event({ id: 5, kind: 'assistant_text', text: 'a' }));
    apply(event({ id: 4, kind: 'assistant_text', text: 'old' }));
    expect(useAgentStore.getState().events).toHaveLength(1);
  });

  it('knows which confirmations are open and which runs can be undone', () => {
    const events = [
      event({ id: 1, kind: 'tool_step', tool: 'create_nodes', summary: '新建 1 个节点' }),
      event({ id: 2, kind: 'confirm_request', requestId: 'q1', summary: '生成 1 个节点' }),
      event({ id: 3, kind: 'confirm_request', requestId: 'q2', summary: '生成 1 个节点' }),
      event({ id: 4, kind: 'confirm_resolved', requestId: 'q1', approved: true }),
    ];
    expect(pendingConfirmations(events).map((item) => item.requestId)).toEqual(['q2']);
    expect(undoableRuns(events).size).toBe(0); // not finished yet
    const finished = [...events, event({ id: 5, kind: 'run_finished', status: 'completed' })];
    expect(pendingConfirmations(finished)).toEqual([]);
    expect([...undoableRuns(finished)]).toEqual(['r1']);
    expect(undoableRuns([...finished, event({ id: 6, kind: 'run_undone' })]).size).toBe(0);
    // a run that only looked at the canvas has nothing to undo
    expect(undoableRuns([
      event({ id: 1, kind: 'tool_step', tool: 'get_canvas' }),
      event({ id: 2, kind: 'run_finished', status: 'completed' }),
    ]).size).toBe(0);
  });
});

describe('markdown', () => {
  it('renders tables and does not run raw html', () => {
    const { container } = render(
      <Markdown text={'## 第一场\n\n| 镜号 | 画面 |\n| --- | --- |\n| 1 | 兔子醒来 |\n\n<img src=x onerror=alert(1)>'} />,
    );
    expect(screen.getByRole('heading', { name: '第一场' })).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByText('兔子醒来')).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
  });

  it('finds note blocks and splits their title', () => {
    const text = 'a\n```note\n# 分镜表\n| 镜头 | 画面 |\n| --- | --- |\n| 1 | 兔子 |\n```\nb\n~~~note\n只有正文\n~~~\n```js\nx\n```';
    expect(noteBlocks(text)).toHaveLength(2);
    expect(splitNoteBlock(noteBlocks(text)[0])).toEqual({ title: '分镜表', body: '| 镜头 | 画面 |\n| --- | --- |\n| 1 | 兔子 |' });
    expect(splitNoteBlock('只有正文', 'x')).toEqual({ title: '只有正文', body: '只有正文' });
  });

  it('picks a title from the first line', () => {
    expect(titleFromMarkdown('# 兔子短片剧本\n\n正文', 'x')).toBe('兔子短片剧本');
    expect(titleFromMarkdown('   ', 'Agent 笔记')).toBe('Agent 笔记');
  });
});

describe('agent messages', () => {
  it('only special blocks can be saved, each named after its section', () => {
    const onSave = vi.fn();
    const text = [
      '分镜表如下，每条提示词都写成完整的一段。',
      '',
      '## 实木菜板广告分镜表',
      '',
      '| 镜号 | 画面 |',
      '| --- | --- |',
      '| 1 | 兔子啃胡萝卜 |',
      '',
      '### 镜头 1 | 开场',
      '',
      '**生图提示词**',
      '',
      '```prompt',
      '商业广告摄影，一只奶油色的小兔子蹲在菜板上',
      '```',
      '',
      '**生视频提示词**',
      '',
      '> 兔子低头啃着胡萝卜，镜头慢慢往后拉远',
      '',
      '要我直接生成吗？',
    ].join('\n');
    render(
      <AgentMessage event={event({ kind: 'assistant_text', text })} focusTitles={{}} onFocusNodes={vi.fn()}
        onSaveToCanvas={onSave} onConfirm={vi.fn()} pending={false} />,
    );
    const buttons = screen.getAllByRole('button', { name: '存成便签' });
    expect(buttons).toHaveLength(3); // table, prompt, quote — plain text has none
    fireEvent.click(buttons[0]);
    expect(onSave).toHaveBeenLastCalledWith('| 镜号 | 画面 |\n| --- | --- |\n| 1 | 兔子啃胡萝卜 |', '实木菜板广告分镜表');
    fireEvent.click(buttons[1]);
    expect(onSave).toHaveBeenLastCalledWith('商业广告摄影，一只奶油色的小兔子蹲在菜板上', '镜头 1 开场 · 生图提示词');
    fireEvent.click(buttons[2]);
    expect(onSave).toHaveBeenLastCalledWith('兔子低头啃着胡萝卜，镜头慢慢往后拉远', '镜头 1 开场 · 生视频提示词');
    expect(screen.queryByRole('button', { name: '存到画布' })).toBeNull(); // no whole-message save
  });

  it('confirmation card answers once', () => {
    const onConfirm = vi.fn();
    const request = event({ kind: 'confirm_request', requestId: 'q1', summary: '生成 2 个节点', reason: '包含视频生成' });
    const { rerender } = render(
      <AgentMessage event={request} focusTitles={{}} onFocusNodes={vi.fn()} onSaveToCanvas={vi.fn()} onConfirm={onConfirm} pending />,
    );
    expect(screen.getByText('包含视频生成')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认' }));
    expect(onConfirm).toHaveBeenCalledWith(request, true, '');
    rerender(
      <AgentMessage event={request} focusTitles={{}} onFocusNodes={vi.fn()} onSaveToCanvas={vi.fn()} onConfirm={onConfirm} pending={false} />,
    );
    expect(screen.queryByRole('button', { name: '确认' })).toBeNull();
  });

  it('confirmation card sends an optional note with the answer', () => {
    const onConfirm = vi.fn();
    const request = event({ kind: 'confirm_request', requestId: 'q1', summary: '生成 4 个节点' });
    render(
      <AgentMessage event={request} focusTitles={{}} onFocusNodes={vi.fn()} onSaveToCanvas={vi.fn()} onConfirm={onConfirm} pending />,
    );
    fireEvent.change(screen.getByLabelText('补充说明'), { target: { value: '  镜头2 改成夜景 ' } });
    fireEvent.click(screen.getByRole('button', { name: '拒绝并说明' }));
    expect(onConfirm).toHaveBeenCalledWith(request, false, '镜头2 改成夜景');
    expect(screen.queryByLabelText('补充说明')).toBeNull();
  });

  it('resolved note shows what the user added', () => {
    render(
      <AgentMessage event={event({ kind: 'confirm_resolved', requestId: 'q1', approved: true, note: '后面都用暖色调' })}
        focusTitles={{}} onFocusNodes={vi.fn()} onSaveToCanvas={vi.fn()} onConfirm={vi.fn()} pending={false} />,
    );
    expect(screen.getByText('已确认')).toBeInTheDocument();
    expect(screen.getByText('补充：后面都用暖色调')).toBeInTheDocument();
  });

  it('note cards save their body with the heading as title', () => {
    const onSave = vi.fn();
    const text = '改好了：\n\n```note\n# 镜头 2 Prompt\n\n低角度微距，暖光扫过木纹\n```';
    render(
      <AgentMessage event={event({ kind: 'assistant_text', text })} focusTitles={{}} onFocusNodes={vi.fn()}
        onSaveToCanvas={onSave} onConfirm={vi.fn()} pending={false} />,
    );
    fireEvent.click(screen.getByRole('button', { name: '存成便签' }));
    expect(onSave).toHaveBeenCalledWith('低角度微距，暖光扫过木纹', '镜头 2 Prompt');
  });

  it('tool steps locate their nodes', () => {
    const onFocus = vi.fn();
    render(
      <AgentMessage
        event={event({ kind: 'tool_step', tool: 'create_nodes', summary: '新建 2 个节点', touched: ['a', 'b'] })}
        focusTitles={{}} onFocusNodes={onFocus} onSaveToCanvas={vi.fn()} onConfirm={vi.fn()} pending={false}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /新建 2 个节点/ }));
    expect(onFocus).toHaveBeenCalledWith(['a', 'b']);
  });
});

describe('note markdown', () => {
  it('shows rendered markdown and edits the source on double click', () => {
    const onChange = vi.fn();
    render(<ReactFlowProvider><NoteNode data={{ content: '# 设定\n\n- 米白色垂耳兔', onChange }} /></ReactFlowProvider>);
    expect(screen.getByRole('heading', { name: '设定' })).toBeInTheDocument();
    fireEvent.doubleClick(screen.getByRole('button', { name: /便签内容/ }));
    const textarea = screen.getByLabelText('便签内容') as HTMLTextAreaElement;
    expect(textarea.value).toBe('# 设定\n\n- 米白色垂耳兔');
    fireEvent.change(textarea, { target: { value: '# 设定\n\n- 狐狸' } });
    fireEvent.blur(textarea);
    expect(onChange).toHaveBeenCalledWith('# 设定\n\n- 狐狸');
    expect(screen.getByText('狐狸')).toBeInTheDocument();
  });
});

describe('agent node marks', () => {
  it('marks what the running turn touched, pending confirmations and the turn that just ended', async () => {
    const { agentNodeMarks } = await import('../agent/agentMarks');
    const events = [
      event({ id: 1, runId: 'old', kind: 'tool_step', tool: 'create_nodes', touched: ['x'] }),
      event({ id: 2, runId: 'r1', kind: 'tool_step', tool: 'create_nodes', touched: ['a', 'b'] }),
      event({ id: 3, runId: 'r1', kind: 'tool_step', tool: 'update_node', touched: ['c'], isError: true }),
      event({ id: 4, runId: 'r1', kind: 'confirm_request', requestId: 'q1', touched: ['b'] }),
    ];
    const marks = agentNodeMarks(events, 'r1', null);
    expect(Object.fromEntries(marks)).toEqual({ a: 'working', b: 'pending' });
    const after = [...events, event({ id: 5, runId: 'r1', kind: 'confirm_resolved', requestId: 'q1', approved: true })];
    expect(agentNodeMarks(after, null, 'r1').get('b')).toBe('recent');
    expect(agentNodeMarks(after, null, null).size).toBe(0);
  });

  it('keeps a finished turn as recent only when it ended live', () => {
    vi.useFakeTimers();
    const { apply, reset } = useAgentStore.getState();
    apply(event({ id: 1, kind: 'user_message', text: 'go' }));
    apply(event({ id: 2, kind: 'run_finished', status: 'completed' }));
    expect(useAgentStore.getState().recentRunId).toBe('r1');
    vi.advanceTimersByTime(4000);
    expect(useAgentStore.getState().recentRunId).toBeNull();
    reset('s', [event({ id: 1, kind: 'user_message' }), event({ id: 2, kind: 'run_finished', status: 'completed' })]);
    expect(useAgentStore.getState().recentRunId).toBeNull();
    vi.useRealTimers();
  });
});

describe('dragging reply blocks', () => {
  it('appends after a blank line and never duplicates whitespace', async () => {
    const { appendText } = await import('../agent/blockDrag');
    expect(appendText('', '  兔子  ')).toBe('兔子');
    expect(appendText(undefined, '兔子')).toBe('兔子');
    expect(appendText('原来的提示词\n\n', '新加的')).toBe('原来的提示词\n\n新加的');
    expect(appendText('原来的', '   ')).toBe('原来的');
  });

  it('the drag handle carries the block content and title', async () => {
    const { AGENT_BLOCK_MIME, readBlock } = await import('../agent/blockDrag');
    const text = '### 镜头 2\n\n**生图提示词**\n\n```prompt\n微距，暖光扫过木纹\n```';
    render(
      <AgentMessage event={event({ kind: 'assistant_text', text })} focusTitles={{}} onFocusNodes={vi.fn()}
        onSaveToCanvas={vi.fn()} onConfirm={vi.fn()} pending={false} />,
    );
    const store = new Map<string, string>();
    const dataTransfer = {
      setData: (type: string, value: string) => store.set(type, value),
      getData: (type: string) => store.get(type) ?? '',
      get types() { return [...store.keys()]; },
      setDragImage: vi.fn(),
      effectAllowed: 'none',
    };
    fireEvent.dragStart(screen.getByRole('button', { name: '拖到画布' }), { dataTransfer });
    expect(store.has(AGENT_BLOCK_MIME)).toBe(true);
    expect(readBlock(dataTransfer as unknown as DataTransfer)).toEqual({
      content: '微距，暖光扫过木纹', title: '镜头 2 · 生图提示词', kind: 'prompt',
    });
  });
});

describe('chat list', () => {
  const base = { project_id: 'default', canvas_id: 'c1', created_at: '2026-09-01 01:00:00' };
  const today = new Date();
  const utc = (date: Date) => date.toISOString().slice(0, 19).replace('T', ' ');
  const sessions = [
    { ...base, id: 'a', title: '菜板广告分镜', preview: '新建 9 个节点', message_count: 6, status: 'running' as const, last_active_at: utc(today) },
    { ...base, id: 'b', title: '兔子三种风格', preview: '生成 3 个节点？', message_count: 4, status: 'waiting' as const, last_active_at: utc(today) },
    { ...base, id: 'c', title: '广告思路讨论', preview: '可以从菜板的质感入手', message_count: 8, status: 'idle' as const, last_active_at: '2026-01-02 03:00:00' },
    { ...base, id: 'd', title: '旧的', preview: '', message_count: 2, status: 'idle' as const, archived_at: '2026-09-02 00:00:00' },
    { ...base, id: 'e', title: null, preview: '', message_count: 0, status: 'idle' as const },
  ];

  it('groups by day, shows status, searches, and hides empty chats', async () => {
    const { SessionList } = await import('../agent/SessionList');
    const onOpen = vi.fn();
    render(<SessionList sessions={sessions} currentId="c" onOpen={onOpen} onNew={vi.fn()} onBack={vi.fn()}
      onRename={vi.fn()} onArchive={vi.fn()} />);
    expect(screen.getByText('今天')).toBeInTheDocument();
    expect(screen.getByText('更早')).toBeInTheDocument();
    expect(screen.getByText('运行中')).toBeInTheDocument();
    expect(screen.getByText('等你确认')).toBeInTheDocument();
    expect(screen.queryByText('新对话', { selector: '.session-title' })).toBeNull(); // empty chat hidden
    expect(screen.queryByText('旧的')).toBeNull(); // archived collapsed
    fireEvent.change(screen.getByLabelText('搜索对话'), { target: { value: '质感' } });
    expect(screen.getByText('广告思路讨论')).toBeInTheDocument();
    expect(screen.queryByText('菜板广告分镜')).toBeNull();
    fireEvent.click(screen.getByText('广告思路讨论'));
    expect(onOpen).toHaveBeenCalledWith('c');
  });

  it('renames once, archives idle chats only, and restores archived ones', async () => {
    const { SessionList } = await import('../agent/SessionList');
    const onRename = vi.fn();
    const onArchive = vi.fn();
    render(<SessionList sessions={sessions} currentId={null} onOpen={vi.fn()} onNew={vi.fn()} onBack={vi.fn()}
      onRename={onRename} onArchive={onArchive} />);
    const archiveButtons = screen.getAllByRole('button', { name: '归档' });
    expect(archiveButtons[0]).toBeDisabled(); // running
    fireEvent.click(archiveButtons[2]);
    expect(onArchive).toHaveBeenCalledWith('c', true);
    fireEvent.click(screen.getAllByRole('button', { name: '重命名' })[2]);
    const input = screen.getByLabelText('对话名称');
    fireEvent.change(input, { target: { value: '  菜板思路  ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    fireEvent.blur(input);
    expect(onRename).toHaveBeenCalledTimes(1);
    expect(onRename).toHaveBeenCalledWith('c', '菜板思路');
    fireEvent.click(screen.getByText(/已归档/));
    fireEvent.click(screen.getByRole('button', { name: '恢复' }));
    expect(onArchive).toHaveBeenCalledWith('d', false);
  });
});

describe('focus thumbnails', () => {
  it('sent messages show the focused nodes as small thumbnails', () => {
    render(
      <AgentMessage
        event={event({ kind: 'user_message', text: '看看这两个', focus: ['img', 'gone'] })}
        focusTitles={{ img: '一个兔子' }}
        focusPreviews={{ img: { nodeId: 'img', kind: 'image', title: '一个兔子', url: '/api/assets/a/file' } }}
        onFocusNodes={vi.fn()} onSaveToCanvas={vi.fn()} onConfirm={vi.fn()} pending={false}
      />,
    );
    const strip = screen.getByLabelText('这条消息关注的节点');
    expect(strip.querySelector('img')?.getAttribute('src')).toBe('/api/assets/a/file');
    expect(screen.getByText('已删除的节点')).toBeInTheDocument();
  });
});
