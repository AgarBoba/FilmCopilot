import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ReactFlowProvider } from '@xyflow/react';

import type { AgentEvent } from '../agent/agentApi';
import { AgentMessage } from '../agent/AgentMessage';
import { Markdown, titleFromMarkdown } from '../agent/Markdown';
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

  it('picks a title from the first line', () => {
    expect(titleFromMarkdown('# 兔子短片剧本\n\n正文', 'x')).toBe('兔子短片剧本');
    expect(titleFromMarkdown('   ', 'Agent 笔记')).toBe('Agent 笔记');
  });
});

describe('agent messages', () => {
  it('assistant replies can be saved to the canvas', () => {
    const onSave = vi.fn();
    render(
      <AgentMessage
        event={event({ kind: 'assistant_text', text: '# 剧本' })}
        focusTitles={{}}
        onFocusNodes={vi.fn()}
        onSaveToCanvas={onSave}
        onConfirm={vi.fn()}
        pending={false}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '存到画布' }));
    expect(onSave).toHaveBeenCalledWith('# 剧本');
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
