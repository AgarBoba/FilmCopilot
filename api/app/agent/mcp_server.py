"""Expose CanvasTools to the Claude Agent SDK as an in-process MCP server.

Tool names the model sees: mcp__canvas__<name>. Handlers look up the CanvasTools of the
run that is currently active, so one long-lived SDK client can serve many runs.
"""
from collections.abc import Awaitable, Callable
from typing import Any

from claude_agent_sdk import ToolAnnotations, create_sdk_mcp_server, tool

from .canvas_tools import CanvasTools, ToolResult

SERVER_NAME = 'canvas'
READ_ONLY = ('get_canvas', 'get_node', 'view_asset', 'get_node_versions', 'wait_for_generation', 'list_models')
# Memory tools never touch the canvas and never need confirmation (changes show in the chat with undo).
MEMORY_TOOLS = ('remember', 'update_memory', 'forget', 'recall')
MEMORY_CATEGORY_HELP = (
    '项目记忆 category：character 角色 / style 风格 / setting 场景与设定 / decision 已定的决定 / taboo 不要做的 / other；'
    '我的偏好 category：params 常用参数 / aesthetic 审美 / prompt_style 提示词写法 / workflow 做事方式 / communication 沟通 / other'
)

ID_LIST = {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1}
IMAGE_PARAMS = {
    'type': 'object',
    'description': '图片参数：size 1K|2K；aspectRatio match_input_image|1:1|16:9|9:16|4:3；outputFormat png|jpeg',
}
NODE_SPEC = {
    'type': 'object',
    'properties': {
        'type': {'type': 'string', 'enum': ['image', 'video', 'note', 'sticky'],
                 'description': 'note = 文本节点（文字会拼进下游 Prompt）；sticky = 便签（给一片区域写的说明，不能连线、不参与生成）'},
        'title': {'type': 'string', 'description': '节点名称；不填自动编号（便签不用填，第一行就是它的名字）'},
        'prompt': {'type': 'string', 'description': '图片 / 视频节点的 Prompt'},
        'content': {'type': 'string', 'description': '文本节点的文字（会作为下游节点 Prompt 的前缀）；便签的文字（第一行是区域名，会加粗）'},
        'color': {'type': 'string', 'enum': ['yellow', 'pink', 'blue', 'green', 'purple', 'gray'], 'description': '便签颜色，默认 yellow'},
        'textSize': {'type': 'string', 'enum': ['s', 'm', 'l'], 'description': '便签字号，默认 m；当大标题用 l'},
        'model': {'type': 'string', 'description': '图片 / 视频节点用的模型 id（见 list_models）；不填用默认模型'},
        'parameters': {
            'type': 'object',
            'description': '这个模型的参数，只写要改的项；每个模型的参数和可选值见 list_models',
        },
        'x': {'type': 'number'},
        'y': {'type': 'number'},
    },
    'required': ['type'],
}

StepCallback = Callable[[str, dict[str, Any], ToolResult], Awaitable[None]]

TOOL_SPECS: list[tuple[str, str, dict[str, Any]]] = [
    ('list_models',
     '列出可用的图片 / 视频模型：擅长什么、参考图上限、参数和可选值、是否缺少密钥。选模型或设参数前先看。',
     {'type': 'object', 'properties': {'kind': {'type': 'string', 'enum': ['image', 'video']}}}),
    ('get_canvas',
     '读取画布：节点 ID、类型、名称、位置、Prompt 摘要、生成状态、上游；还有用户贴的便签（区域说明），每个节点注明它在哪张便签的区里。传 node_ids 只看这些节点及其上下游。',
     {'type': 'object', 'properties': {'node_ids': {'type': 'array', 'items': {'type': 'string'}}}}),
    ('get_node', '读取一个节点的完整信息：Prompt、参数、内容、上下游、最近一次生成结果或失败原因。',
     {'type': 'object', 'properties': {'node_id': {'type': 'string'}}, 'required': ['node_id']}),
    ('view_asset', '查看节点里的图片（视频为开头 / 中间 / 结尾 3 帧）。用来判断画面效果或参考风格。默认看当前版本，传 version 看以前的某一版。',
     {'type': 'object', 'properties': {'node_id': {'type': 'string'}, 'version': {'type': 'integer'}},
      'required': ['node_id']}),
    ('get_node_versions', '列出图片 / 视频节点的历史版本：第几版、怎么来的（生成 / 上传 / 切回旧版）、当时的 Prompt 和模型。用户说「上一版」「之前那张」时用。',
     {'type': 'object', 'properties': {'node_id': {'type': 'string'}}, 'required': ['node_id']}),
    ('create_nodes', '新建一个或多个节点。不填位置时自动排在画布右侧。',
     {'type': 'object', 'properties': {'nodes': {'type': 'array', 'items': NODE_SPEC, 'minItems': 1}},
      'required': ['nodes']}),
    ('update_node', '修改节点：title、prompt（文本节点用 content）、model（换模型）、parameters（只写要改的项）；便签改 content、color、textSize。生成中的节点不能改。',
     {'type': 'object', 'properties': {
         'node_id': {'type': 'string'},
         'title': {'type': 'string'}, 'prompt': {'type': 'string'}, 'content': {'type': 'string'},
         'color': NODE_SPEC['properties']['color'], 'textSize': NODE_SPEC['properties']['textSize'],
         'model': NODE_SPEC['properties']['model'],
         'parameters': NODE_SPEC['properties']['parameters'],
     }, 'required': ['node_id']}),
    ('connect', '连线：source 作为 target 的参考。图片→图片/视频，视频→视频，文本→图片/视频（文字加到 Prompt 前）。便签不能连线。',
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
    ('generate', '对节点发起生成（会花费额度，可能需要用户确认）。之后用 wait_for_generation 查看结果。'
     '结果会替换节点当前的画面，旧的留作历史版本。reference_current=true：把节点当前的画面也作为参考图一起发'
     '（参考原图重画，用来做局部修改）。',
     {'type': 'object', 'properties': {'node_ids': ID_LIST, 'reference_current': {'type': 'boolean'}},
      'required': ['node_ids']}),
    ('wait_for_generation', '等待这些节点的生成完成，返回结果图片（视频为关键帧）或失败原因。',
     {'type': 'object', 'properties': {'node_ids': ID_LIST}, 'required': ['node_ids']}),
    ('remember',
     '记住用户明确说过、以后还用得上的内容。layer=project：本项目的设定（所有对话共享）；'
     'layer=preference：用户个人的习惯和偏好（所有项目通用）。content 写成一句完整的话。' + MEMORY_CATEGORY_HELP,
     {'type': 'object', 'properties': {
         'layer': {'type': 'string', 'enum': ['project', 'preference']},
         'category': {'type': 'string'},
         'content': {'type': 'string'},
     }, 'required': ['layer', 'content']}),
    ('update_memory', '用户改了某条已记住的内容时用：旧的会保留为历史，新的生效。memory_id 是记忆前面的 # 号数字。',
     {'type': 'object', 'properties': {
         'memory_id': {'type': 'integer'}, 'content': {'type': 'string'}, 'category': {'type': 'string'},
     }, 'required': ['memory_id', 'content']}),
    ('forget', '用户要你忘掉某条记忆时用。',
     {'type': 'object', 'properties': {'memory_id': {'type': 'integer'}}, 'required': ['memory_id']}),
    ('recall',
     '搜记忆和这个项目里以前的对话（对话摘要和原话；包括其他画布、已归档的对话和画布留言，结果里会注明）。'
     '用户提到「之前说的」「上次那个」「另一个对话里」时先用它。',
     {'type': 'object', 'properties': {'query': {'type': 'string', 'description': (
         '几个关键词或短语，用空格分开，如「兔子 耳朵颜色」。中文短语会按片段匹配，不必和原话一字不差；'
         '找不到时换更短、更具体的词再试')}},
      'required': ['query']}),
]


async def call_tool(tools: CanvasTools, name: str, args: dict[str, Any]) -> ToolResult:
    if name == 'list_models':
        return tools.list_models(args.get('kind'))
    if name == 'get_canvas':
        return tools.get_canvas(args.get('node_ids'))
    if name == 'get_node':
        return tools.get_node(args['node_id'])
    if name == 'view_asset':
        return tools.view_asset(args['node_id'], args.get('version'))
    if name == 'get_node_versions':
        return tools.get_node_versions(args['node_id'])
    if name == 'create_nodes':
        return tools.create_nodes(args['nodes'])
    if name == 'update_node':
        changes = {key: args[key] for key in ('title', 'prompt', 'content', 'model', 'parameters', 'color', 'textSize')
                   if key in args}
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
        return tools.generate(args['node_ids'], bool(args.get('reference_current')))
    if name == 'wait_for_generation':
        return await tools.wait_for_generation(args['node_ids'])
    if name in MEMORY_TOOLS:
        memory = tools.memory
        if memory is None:
            return ToolResult('记忆功能暂时不可用。', is_error=True)
        if tools.stopped and name != 'recall':
            return ToolResult('已停止：用户中止了这一轮任务。', is_error=True)
        if name == 'remember':
            return memory.remember(args['layer'], args['content'], args.get('category') or 'other')
        if name == 'update_memory':
            return memory.update_memory(args['memory_id'], args['content'], args.get('category'))
        if name == 'forget':
            return memory.forget(args['memory_id'])
        return memory.recall(args['query'])
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
        annotations = ToolAnnotations(readOnlyHint=True) if name in READ_ONLY or name == 'recall' else None
        sdk_tools.append(tool(name, description, schema, annotations=annotations)(handlers[name]))
    return create_sdk_mcp_server(name=SERVER_NAME, version='1.0.0', tools=sdk_tools)


def qualified(name: str) -> str:
    return f'mcp__{SERVER_NAME}__{name}'
