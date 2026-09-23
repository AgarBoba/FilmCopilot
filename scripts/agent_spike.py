"""Task 0 技术验证：在本机检查 Claude Agent SDK 的关键能力。

运行（在项目根目录）：
    uv pip install -p .venv claude-agent-sdk
    .venv/bin/python scripts/agent_spike.py

只会调用几次模型（约几毛钱），不会改动画布或数据库。不会打印 API Key。
"""
import asyncio
import base64
import io
import os
import shutil
import time
import warnings
from pathlib import Path

# 只读工具有意跳过权限回调，这条提醒是预期内的
warnings.filterwarnings('ignore', message='.*can_use_tool will not be invoked.*')

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    env = ROOT / '.env'
    for line in env.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

from PIL import Image, ImageDraw  # noqa: E402
from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)

MODEL = os.environ.get('AGENT_MODEL', 'claude-opus-5-5')
results: list[tuple[str, bool, str]] = []
writes: list[str] = []
permission_asks: list[str] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"  {'✅' if ok else '❌'} {name}：{detail}")


def test_image_jpeg() -> str:
    image = Image.new('RGB', (1600, 1000), (250, 236, 210))
    draw = ImageDraw.Draw(image)
    draw.ellipse((500, 350, 1100, 850), fill=(236, 120, 40))
    draw.rectangle((760, 150, 840, 380), fill=(60, 150, 60))
    image.thumbnail((1024, 1024))
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=85)
    return base64.b64encode(buffer.getvalue()).decode()


@tool('view_asset', '查看节点 n1 的图片', {'node_id': str})
async def view_asset(args):
    return {'content': [{'type': 'image', 'data': test_image_jpeg(), 'mimeType': 'image/jpeg'}]}


@tool('generate', '对节点发起图片生成（花钱）', {'node_id': str, 'prompt': str})
async def generate(args):
    writes.append('generate')
    return {'content': [{'type': 'text', 'text': '已排队'}]}


@tool('create_note', '新建一个便签节点', {'text': str})
async def create_note(args):
    writes.append(f"create_note:{args['text']}")
    await asyncio.sleep(1)
    return {'content': [{'type': 'text', 'text': '便签已创建'}]}


server = create_sdk_mcp_server(name='canvas', version='0.1.0', tools=[view_asset, generate, create_note])


async def can_use_tool(name, tool_input, context):
    """模拟权限钩子：写入类工具都经过这里；generate 模拟「等用户 2 秒后拒绝」。"""
    if name.endswith('generate'):
        permission_asks.append(name)
        await asyncio.sleep(2)
        return PermissionResultDeny(message='用户拒绝了这次生成')
    return PermissionResultAllow()


def options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=MODEL,
        tools=[],                       # 关掉所有自带工具
        mcp_servers={'canvas': server},
        # 只读工具放行；写入工具不列在这里，才会经过 can_use_tool
        allowed_tools=['mcp__canvas__view_asset'],
        can_use_tool=can_use_tool,
        include_partial_messages=True,  # 流式文字
        setting_sources=[],
        cwd=str(ROOT),
    )


async def ask(client, prompt, interrupt_on=None):
    started = time.time()
    deltas, tools, text, result, auth_error = 0, [], '', None, None
    await client.query(prompt)
    async for message in client.receive_response():
        if isinstance(message, StreamEvent):
            event = message.event
            if event.get('type') == 'content_block_delta' and event.get('delta', {}).get('type') == 'text_delta':
                deltas += 1
        elif isinstance(message, SystemMessage) and message.subtype == 'api_retry':
            auth_error = message.data.get('error')
            if message.data.get('error_status') in (401, 403):
                await client.interrupt()
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    tools.append(block.name.split('__')[-1])
                    if interrupt_on and block.name.endswith(interrupt_on) and tools.count(interrupt_on) == 1:
                        await client.interrupt()
                elif isinstance(block, TextBlock):
                    text += block.text
        elif isinstance(message, ResultMessage):
            result = message
    return {'seconds': time.time() - started, 'deltas': deltas, 'tools': tools, 'text': text,
            'result': result, 'auth_error': auth_error}


async def main() -> None:
    print(f'模型：{MODEL}')
    print(f"ANTHROPIC_API_KEY：{'已设置' if os.environ.get('ANTHROPIC_API_KEY') else '未设置'}")
    print(f"ffmpeg：{shutil.which('ffmpeg') or '未安装（视频抽帧需要：brew install ffmpeg）'}\n")
    total_cost = 0.0

    async with ClaudeSDKClient(options=options()) as client:
        print('1. 最小调用 + 自带工具已关闭')
        r = await ask(client, '不要调用任何工具。列出你现在能用的所有工具的名字，每行一个；没有就说「无」。')
        if r['auth_error']:
            record('连接模型', False, f"认证失败（{r['auth_error']}）：检查 API Key 或网络代理")
            return summary(total_cost)
        record('连接模型', r['result'] is not None and not r['result'].is_error, f"{r['seconds']:.1f} 秒")
        listed = r['text']
        builtin = [name for name in ('Bash', 'Read', 'Write', 'Edit', 'WebFetch', 'Glob', 'Grep') if name in listed]
        record('自带工具已关闭', not builtin, '模型只看到画布工具' if not builtin else f'仍可见：{builtin}')
        record('流式文字', r['deltas'] > 1, f"收到 {r['deltas']} 段增量文字")
        total_cost += r['result'].total_cost_usd or 0

        print('\n2. 工具返回图片')
        r = await ask(client, '用 view_asset 看节点 n1，用一句中文说图里是什么、主要颜色。')
        seen = any(word in r['text'] for word in ('橙', '胡萝卜', '橘'))
        record('模型能看图', 'view_asset' in r['tools'] and seen, r['text'][:60].replace('\n', ' '))
        total_cost += r['result'].total_cost_usd or 0

        print('\n3. 权限回调异步等待并拒绝')
        r = await ask(client, '对节点 n1 调用 generate，prompt 写「胡萝卜」。被拒绝就说明原因，不要重试。')
        record('生成前拦截', bool(permission_asks) and 'generate' not in writes,
               f"回调触发 {len(permission_asks)} 次，实际执行 {writes.count('generate')} 次")
        total_cost += r['result'].total_cost_usd or 0

        print('\n4. 中断')
        before = len(writes)
        r = await ask(client, '依次调用 create_note 五次，文本分别是 1、2、3、4、5，一次一个。', interrupt_on='create_note')
        await asyncio.sleep(3)
        made = len(writes) - before
        record('中断后不再写入', made <= 1, f'中断前后共执行 create_note {made} 次（期望 ≤ 1）')
        if r['result']:
            total_cost += r['result'].total_cost_usd or 0

    summary(total_cost)


def summary(cost: float) -> None:
    passed = sum(ok for _, ok, _ in results)
    print(f'\n结果：{passed}/{len(results)} 通过，本次花费约 ${cost:.3f}')


if __name__ == '__main__':
    asyncio.run(main())
