"""Expose CanvasTools to the Claude Agent SDK as an in-process MCP server.

Tool names the model sees: mcp__canvas__<name>. Handlers look up the CanvasTools of the
run that is currently active, so one long-lived SDK client can serve many runs.
"""
from collections.abc import Awaitable, Callable
from typing import Any

from claude_agent_sdk import ToolAnnotations, create_sdk_mcp_server, tool

from .canvas_tools import CanvasTools, ToolResult

SERVER_NAME = 'canvas'
READ_ONLY = ('get_canvas', 'get_node', 'view_asset', 'wait_for_generation')

ID_LIST = {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1}
IMAGE_PARAMS = {
    'type': 'object',
    'description': '图片参数：size 1K|2K；aspectRatio match_input_image|1:1|16:9|9:16|4:3；outputFormat png|jpeg',
}
NODE_SPEC = {
    'type': 'object',
    'properties': {
        'type': {'type': 'string', 'enum': ['image', 'video', 'note']},
        'title': {'type': 'string', 'description': '节点名称；不填自动编号'},
        'prompt': {'type': 'string', 'description': '图片 / 视频节点的 Prompt'},
        'content': {'type': 'string', 'description': '便签文字（会作为下游节点 Prompt 的前缀）'},
        'parameters': {
            'type': 'object',
            'description': (
                '图片：size 1K|2K，aspectRatio match_input_image|1:1|16:9|9:16|4:3，outputFormat png|jpeg；'
                '视频：duration 5|10，resolution 480p|720p，aspectRatio adaptive|16:9|9:16|1:1，generateAudio true|false'
            ),
        },
        'x': {'type': 'number'},
        'y': {'type': 'number'},
    },
    'required': ['type'],
}

StepCallback = Callable[[str, dict[str, Any], ToolResult], Awaitable[None]]

TOOL_SPECS: list[tuple[str, str, dict[str, Any]]] = [
    ('get_canvas',
     '读取画布：节点 ID、类型、名称、位置、Prompt 摘要、生成状态、上游。传 node_ids 只看这些节点及其上下游。',
     {'type': 'object', 'properties': {'node_ids': {'type': 'array', 'items': {'type': 'string'}}}}),
    ('get_node', '读取一个节点的完整信息：Prompt、参数、内容、上下游、最近一次生成结果或失败原因。',
     {'type': 'object', 'properties': {'node_id': {'type': 'string'}}, 'required': ['node_id']}),
    ('view_asset', '查看节点里的图片（视频为开头 / 中间 / 结尾 3 帧）。用来判断画面效果或参考风格。',
     {'type': 'object', 'properties': {'node_id': {'type': 'string'}}, 'required': ['node_id']}),
    ('create_nodes', '新建一个或多个节点。不填位置时自动排在画布右侧。',
     {'type': 'object', 'properties': {'nodes': {'type': 'array', 'items': NODE_SPEC, 'minItems': 1}},
      'required': ['nodes']}),
    ('update_node', '修改节点：title、prompt（便签用 content）、parameters（只写要改的项）。生成中的节点不能改。',
     {'type': 'object', 'properties': {
         'node_id': {'type': 'string'},
         'title': {'type': 'string'}, 'prompt': {'type': 'string'}, 'content': {'type': 'string'},
         'parameters': NODE_SPEC['properties']['parameters'],
     }, 'required': ['node_id']}),
    ('connect', '连线：source 作为 target 的参考。图片→图片/视频，视频→视频，便签→图片/视频（文字加到 Prompt 前）。',
     {'type': 'object', 'properties': {'source_id': {'type': 'string'}, 'target_id': {'type': 'string'}},
      'required': ['source_id', 'target_id']}),
    ('disconnect', '断开 source → target 的连线。',
     {'type': 'object', 'properties': {'source_id': {'type': 'string'}, 'target_id': {'type': 'string'}},
      'required': ['source_id', 'target_id']}),
    ('move_nodes', '移动节点，用于整理排版。',
     {'type': 'object', 'properties': {'positions': {'type': 'array', 'minItems': 1, 'items': {
         'type': 'object', 'properties': {'node_id': {'type': 'string'}, 'x': {'type': 'number'}, 'y': {'type': 'number'}},
         'required': ['node_id', 'x', 'y']}}}, 'required': ['positions']}),
    ('duplicate_nodes', '复制节点（带内容、Prompt、参数和上游连线），用于做多个版本对比。',
     {'type': 'object', 'properties': {'node_ids': ID_LIST}, 'required': ['node_ids']}),
    ('delete_nodes', '删除节点（连带其连线）。',
     {'type': 'object', 'properties': {'node_ids': ID_LIST}, 'required': ['node_ids']}),
    ('generate', '对节点发起生成（会花费额度，可能需要用户确认）。之后用 wait_for_generation 查看结果。',
     {'type': 'object', 'properties': {'node_ids': ID_LIST}, 'required': ['node_ids']}),
    ('wait_for_generation', '等待这些节点的生成完成，返回结果图片（视频为关键帧）或失败原因。',
     {'type': 'object', 'properties': {'node_ids': ID_LIST}, 'required': ['node_ids']}),
]


async def call_tool(tools: CanvasTools, name: str, args: dict[str, Any]) -> ToolResult:
    if name == 'get_canvas':
        return tools.get_canvas(args.get('node_ids'))
    if name == 'get_node':
        return tools.get_node(args['node_id'])
    if name == 'view_asset':
        return tools.view_asset(args['node_id'])
    if name == 'create_nodes':
        return tools.create_nodes(args['nodes'])
    if name == 'update_node':
        changes = {key: args[key] for key in ('title', 'prompt', 'content', 'parameters') if key in args}
        return tools.update_node(args['node_id'], changes)
    if name == 'connect':
        return tools.connect(args['source_id'], args['target_id'])
    if name == 'disconnect':
        return tools.disconnect(args['source_id'], args['target_id'])
    if name == 'move_nodes':
        return tools.move_nodes(args['positions'])
    if name == 'duplicate_nodes':
        return tools.duplicate_nodes(args['node_ids'])
    if name == 'delete_nodes':
        return tools.delete_nodes(args['node_ids'])
    if name == 'generate':
        return tools.generate(args['node_ids'])
    if name == 'wait_for_generation':
        return await tools.wait_for_generation(args['node_ids'])
    return ToolResult(f'未知工具 {name}', is_error=True)


def to_mcp_result(result: ToolResult) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{'type': 'text', 'text': result.text}]
    content.extend({'type': 'image', 'data': image['data'], 'mimeType': image['mimeType']} for image in result.images)
    return {'content': content, 'is_error': result.is_error}


def build_handlers(
    get_tools: Callable[[], CanvasTools | None], on_step: StepCallback
) -> dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]]:
    """name -> async handler(args) returning an MCP result. Shared by the SDK server and tests."""

    def make(name: str):
        async def handler(args: dict[str, Any]) -> dict[str, Any]:
            tools = get_tools()
            if tools is None:
                result = ToolResult('当前没有进行中的任务。', is_error=True)
            else:
                try:
                    result = await call_tool(tools, name, args or {})
                except KeyError as missing:
                    result = ToolResult(f'缺少参数 {missing}', is_error=True)
                except Exception as error:  # never let one tool crash the run
                    result = ToolResult(f'工具出错：{error}', is_error=True)
            if tools is not None and tools.confirmation_notes:
                notes = '；'.join(tools.confirmation_notes)
                tools.confirmation_notes.clear()
                result.text = (
                    f'{result.text}\n\n[用户确认时的补充] {notes}\n'
                    '这一步已按原计划执行。接下来的步骤照这条补充来；如果补充要求改动刚做的内容，先说明再改。'
                )
            await on_step(name, args or {}, result)
            return to_mcp_result(result)

        return handler

    return {name: make(name) for name, _, _ in TOOL_SPECS}


def build_server(handlers: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]]):
    sdk_tools = []
    for name, description, schema in TOOL_SPECS:
        annotations = ToolAnnotations(readOnlyHint=True) if name in READ_ONLY else None
        sdk_tools.append(tool(name, description, schema, annotations=annotations)(handlers[name]))
    return create_sdk_mcp_server(name=SERVER_NAME, version='1.0.0', tools=sdk_tools)


def qualified(name: str) -> str:
    return f'mcp__{SERVER_NAME}__{name}'
