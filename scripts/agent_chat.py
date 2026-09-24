"""Talk to the Film Copilot agent from the terminal (until the chat panel exists).

Start the app first (./scripts/dev.sh), open the canvas in the browser to watch, then:
    .venv/bin/python scripts/agent_chat.py

Type a message and press Enter. Generation / delete confirmations are asked here as y/n.
Commands: /stop  /undo  /mode confirm_all|confirm_generation|auto  /quit
"""
import json
import os
import sys
import threading

import httpx

API = f"http://127.0.0.1:{os.environ.get('API_PORT', '8000')}/api"
CANVAS = os.environ.get('CANVAS_ID', 'default')


def main() -> None:
    client = httpx.Client(timeout=30)
    status = client.get(f'{API}/agent/status').json()
    if not status['configured']:
        sys.exit('Agent 还没配置模型登录：在 .env 里设 AGENT_AUTH=subscription（先运行 ./scripts/claude-login.sh）或填 ANTHROPIC_API_KEY，然后重启 dev.sh')
    session = client.post(f'{API}/agent/sessions', json={'canvasId': CANVAS}).json()
    print(f"已连接 {status['model']}，会话 {session['id'][:8]}。在浏览器里看画布，这里打字。/quit 退出\n")

    state = {'run': None, 'pending': None}
    threading.Thread(target=listen, args=(session['id'], state), daemon=True).start()

    while True:
        try:
            line = input('> ').strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if state['pending'] and line.lower() in ('y', 'n', 'yes', 'no', '是', '否'):
            approved = line.lower() in ('y', 'yes', '是')
            client.post(f"{API}/agent/runs/{state['run']}/confirm",
                        json={'requestId': state['pending'], 'approved': approved})
            state['pending'] = None
            continue
        if line == '/quit':
            break
        if line == '/stop' and state['run']:
            client.post(f"{API}/agent/runs/{state['run']}/stop")
            continue
        if line == '/undo' and state['run']:
            result = client.post(f"{API}/agent/runs/{state['run']}/undo").json()
            print(f'撤销结果：{json.dumps(result, ensure_ascii=False)}')
            continue
        if line.startswith('/mode '):
            mode = line.split(maxsplit=1)[1]
            print(client.patch(f'{API}/projects/default/agent-settings', json={'permissionMode': mode}).json())
            continue
        response = client.post(f"{API}/agent/sessions/{session['id']}/messages", json={'text': line})
        if response.status_code >= 400:
            print('发送失败：', response.json().get('error', {}).get('message'))
            continue
        state['run'] = response.json()['runId']


def listen(session_id: str, state: dict) -> None:
    with httpx.stream('GET', f'{API}/agent/sessions/{session_id}/stream', timeout=None) as response:
        for line in response.iter_lines():
            if not line.startswith('data: '):
                continue
            event = json.loads(line[6:])
            kind = event['kind']
            if kind == 'text_delta':
                print(event['text'], end='', flush=True)
            elif kind == 'assistant_text':
                print()
            elif kind == 'tool_step':
                mark = '✗' if event['isError'] else '·'
                print(f"\n  {mark} {event['summary']}" + (f"：{event['detail'][:120]}" if event['isError'] else ''))
            elif kind == 'confirm_request':
                state['pending'] = event['requestId']
                reason = f"（{event['reason']}）" if event.get('reason') else ''
                print(f"\n  ⚠️ 需要确认：{event['summary']}{reason}  输入 y / n")
            elif kind == 'error':
                print(f"\n  出错：{event['message']}")
            elif kind == 'run_finished':
                cost = f"，约 ${event['costUsd']:.3f}" if event.get('costUsd') else ''
                print(f"\n  [本轮结束：{event['status']}{cost}]  /undo 可撤销\n> ", end='', flush=True)


if __name__ == '__main__':
    main()
