# 无限媒体生成画布设计

## 1. 目标与已确认范围

本项目从空工作区开始，构建一个本地运行的单用户无限画布，用节点和连线组织图片、视频、便签和生成任务。

第一版必须满足：

- 画布支持缩放、平移、自由布局、主题切换、小地图和视口持久化。
- 图片、视频、便签和空素材节点都能被保存并恢复。
- 连线表达“参考素材 → 使用参考素材的目标节点”。
- 图片节点只能接受图片上游；视频节点可以接受图片或视频上游。
- 连线不能形成自连接、重复关系或循环关系。
- 图片和视频节点可以通过本地上传获得素材。
- 视频只在鼠标悬停节点时播放，离开后暂停。
- 图片生成和视频生成通过 Replicate 的真实 API 执行。
- 画布和生成任务都通过本地服务持久化。
- 后续 Agent 通过结构化画布命令接入，不直接操作前端 DOM 或数据库。

第一版不包含多人协作、账号权限、评论、复杂富文本、模型自动路由、完整模型参数面板、节点分类颜色和自定义 RGB/HEX 颜色。

## 2. 技术选型

### 前端

- React
- Vite
- TypeScript
- `@xyflow/react`（React Flow）
- Zustand 或等价的轻量前端状态层
- 原生 CSS 变量实现浅色和深色主题

React Flow 负责无限画布的视口、节点拖动、连线、端点、小地图和自定义节点渲染。业务层不把 React Flow 的节点对象当作数据库模型，而是在服务端快照和前端视图模型之间做显式转换。

### 本地服务

- Python
- FastAPI
- Pydantic
- SQLite
- 本地 `data/assets/` 媒体目录

FastAPI 负责画布 API、文件上传、命令校验、生成任务创建和 SSE 事件流。SQLite 是单用户本地运行的持久化源。

### 生成 Worker

使用独立的本地 Python Worker 进程领取 SQLite 中的 `queued` 任务。第一版不引入 Redis、Celery 或其他外部队列。Worker 通过 Replicate Python 客户端调用模型，下载输出并写入本地媒体目录。

### Provider

第一版只实现 Replicate Provider：

- 图片：`bytedance/seedream-5-pro`
- 视频：`bytedance/seedance-2.0-mini`

API Token 只从 `REPLICATE_API_TOKEN` 环境变量读取，不写入 SQLite、画布 JSON 或前端 bundle。

## 3. 运行拓扑与数据流

~~~text
React/Vite 前端
    │ REST：读取快照、提交命令、上传素材
    │ SSE：接收画布和生成任务更新
    ▼
FastAPI 本地服务
    ├── 画布领域服务
    ├── 命令校验与 revision 控制
    ├── SQLite 持久化
    ├── 本地文件服务
    └── 生成任务创建
          ▼
      SQLite generation_jobs
          ▼
独立本地 Worker
    ├── 领取任务
    ├── 调用 Replicate
    ├── 下载结果
    └── 写回 Asset / 节点 / 事件
~~~

前端和未来 Agent 都调用画布领域服务。前端不能绕过领域服务直接决定连线是否合法；Agent 也不能绕过领域服务直接修改 SQLite。

## 4. 领域模型

### Canvas

~~~text
id: string
name: string
theme: "light" | "dark"
viewport: { x: number, y: number, zoom: number }
revision: integer
created_at: timestamp
updated_at: timestamp
~~~

### CanvasNode

~~~text
id: string
canvas_id: string
type: "image" | "video" | "note"
x: number
y: number
width: number
height: number
asset_id: string | null
status: "empty" | "ready" | "generating" | "error"
content_json: object
created_at: timestamp
updated_at: timestamp
~~~

`content_json` 按节点类型保存业务内容：

- 图片：提示词、生成设置和当前错误信息。
- 视频：提示词、生成设置和当前错误信息。
- 便签：纯文本、字体、字号。

便签第一版不参与参考素材连线。它的文本可以在目标节点的生成面板中被手动复制或作为后续 Agent 命令的输入，但不会被当作图片或视频参考素材。

### CanvasEdge

~~~text
id: string
canvas_id: string
source_node_id: string
target_node_id: string
source_handle: string
target_handle: string
created_at: timestamp
~~~

边的语义固定为 `source = 参考素材`、`target = 使用参考素材的节点`。

### Asset

~~~text
id: string
kind: "image" | "video"
local_path: string
mime_type: string
width: integer
height: integer
duration_ms: integer | null
checksum: string
source: "upload" | "generated"
created_at: timestamp
~~~

素材文件存储在本地，数据库只保存相对路径、媒体信息和 checksum。服务端通过受控的 Asset API 提供读取，不把任意本地路径暴露给前端。

### GenerationJob

~~~text
id: string
canvas_id: string
target_node_id: string
kind: "image" | "video"
provider: "replicate"
model: string
prompt: string
input_snapshot_json: object
base_canvas_revision: integer
provider_prediction_id: string | null
status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "completed_unattached"
progress: number | null
output_asset_id: string | null
warning_json: object | null
error: string | null
created_at: timestamp
updated_at: timestamp
~~~

`input_snapshot_json` 保存提交任务时的提示词、上游节点 ID、上游 Asset ID、Asset checksum 以及 Provider 输入。生成期间画布发生变化时，Worker 不会用新状态替换这份快照。

### CanvasEvent 与 CommandLog

服务端保存结构化事件和幂等命令记录：

- `CanvasEvent`：用于 SSE 推送和断线后的 revision 追赶。
- `CommandLog`：以 `canvas_id + idempotency_key` 唯一，保证 Agent 重试不会重复创建节点、边或生成任务。

## 5. 连接规则

领域服务统一执行以下规则：

~~~text
image  → image：允许
image  → video：允许
video  → video：允许
video  → image：拒绝
self-link：拒绝
duplicate edge：拒绝
cycle：拒绝
note 参与参考图关系：拒绝
~~~

产品层不因为 Provider 的参考图数量限制阻止用户建立连线。Provider Adapter 在真正提交生成时负责把画布关系映射为 Provider 输入，并将截断、缺少能力或格式转换写入任务 warning。

## 6. HTTP 和 Agent 命令接口

### 读取画布

~~~text
GET /api/canvases/{canvas_id}/snapshot
~~~

返回画布、节点、边、素材元数据、当前 revision 和未完成生成任务。

### 提交命令

~~~text
POST /api/canvases/{canvas_id}/commands
~~~

请求结构：

~~~json
{
  "command": "connect_nodes",
  "baseRevision": 12,
  "idempotencyKey": "agent-run-abc-001",
  "payload": {
    "sourceNodeId": "image-1",
    "targetNodeId": "video-1"
  }
}
~~~

第一版命令集合：

~~~text
create_node
update_node
delete_node
delete_edge
connect_nodes
disconnect_nodes
update_note
attach_asset
start_generation
~~~

服务端在一个 SQLite 事务中校验并保存命令，返回：

~~~json
{
  "accepted": true,
  "revision": 13,
  "result": {},
  "events": []
}
~~~

如果 `baseRevision` 过期，返回 `REVISION_CONFLICT`，并附带当前 revision。业务校验错误使用稳定错误码，例如 `INVALID_CONNECTION`、`CYCLE_DETECTED`、`NODE_NOT_FOUND` 和 `GENERATION_INPUT_INVALID`。

### 事件流

~~~text
GET /api/canvases/{canvas_id}/events?afterRevision=12
~~~

前端使用 `EventSource` 订阅。事件包含 revision、事件类型和最小变更载荷。断线后先以 `afterRevision` 请求缺失事件；如果事件已超过保留窗口，则重新读取完整 snapshot。

未来接入 Agent 时，MCP tool 或其他 Agent adapter 只包装这些结构化 API，不增加一套绕过领域服务的写入路径。

## 7. 画布交互

### 视口与主题

- React Flow 负责缩放、平移和节点自由布局。
- 视口在拖动或缩放结束后保存。
- 主题由 CSS 变量统一控制画布、节点、工具栏和小地图。
- 小地图固定在左下角。
- 连线可通过工具栏隐藏；选中节点时，选中节点相关连线强制显示。
- 连线使用统一颜色、实心样式和平滑曲线。

### 节点显示

- 所有节点使用统一圆角卡片。
- 悬停显示节点边框和左右连接端点。
- 选中显示更粗高亮边框，不使用浏览器默认蓝色选框作为主要状态。
- 图片素材区域使用固定宽度和图片比例。
- 视频素材区域根据 Asset 的真实宽高比计算高度。
- 视频仅在节点悬停时播放，离开后暂停并回到首帧或封面。
- 空素材节点显示上传和生成入口，但保留完整的连接能力。
- 参考图面板显示直接上游图片的缩略图；删除按钮只移除当前连接。
- 便签支持文字编辑、字体和字号调整，宽度和高度可以独立修改。

### 连接操作

1. 从任意可用端点拖出连接。
2. 拖到合法目标节点时预览有效连接。
3. 松开后保存连接并更新 revision。
4. 松开在空白区域时弹出“创建图片节点 / 创建视频节点”。
5. 选择节点类型后，在终点附近创建节点并自动完成连接。
6. 参考图面板删除按钮只删除当前边，不删除上游节点。

### 上传操作

本地上传图片或视频时：

1. FastAPI 保存文件并读取媒体元数据。
2. 创建 Asset。
3. 创建对应类型的空节点或填充当前待连接节点。
4. 如果上传来自参考图面板，自动建立对应边。
5. 前端收到事件后刷新目标节点和参考图面板。

## 8. Replicate Provider 映射

### Seedream 5 Pro 图片生成

使用模型 `bytedance/seedream-5-pro`，映射字段：

~~~text
prompt
image_input: 参考图片 Asset 的本地文件输入数组
size: "1K" | "2K"
aspect_ratio: "match_input_image" 或产品允许的比例
output_format: "png" | "jpeg"
~~~

第一版默认 `size = "2K"`、`aspect_ratio = "match_input_image"`、`output_format = "png"`。画布可以存在超过 Provider 当前支持数量的连接；Adapter 传入稳定顺序的前 10 张，并把被省略的 Asset ID 写入 warning。Seedream 的图层拆分能力第一版不开放。

Seedream 返回多个图片 URI 时，第一张绑定到目标节点作为主素材，其余结果仍保存为 Asset，并关联到 GenerationJob，后续可扩展为结果变体列表。

### Seedance 2.0 Mini 视频生成

使用模型 `bytedance/seedance-2.0-mini`，映射字段：

~~~text
prompt
reference_images: 上游图片 Asset
reference_videos: 上游视频 Asset
duration: integer
resolution: "480p" | "720p"
aspect_ratio: "adaptive" 或产品指定比例
generate_audio: boolean
~~~

第一版默认 `duration = 5`、`resolution = "720p"`、`aspect_ratio = "adaptive"`、`generate_audio = true`。图片和视频参考按照边的稳定顺序编号，并在发送给 Provider 的提示词中使用 `[Image1]`、`[Video1]` 等引用。

### Provider 文件输入与输出

Worker 使用 Replicate 客户端上传本地文件输入；不能把本地文件路径直接传给远端 API。输入文件大小、MIME 类型和 Provider 拒绝信息都转换为可读的 GenerationJob 错误。

输出文件下载到 `data/assets/` 后，Worker 读取真实宽度、高度、时长和 MIME 类型，计算 checksum，再创建 Asset。输出只在目标节点仍然存在且输入快照对应的节点状态未冲突时自动绑定；否则保留结果并标记 `completed_unattached`。

## 9. 错误处理与恢复

- 网络或 Provider 临时错误：有限次数重试。
- Provider 参数错误：任务失败，不重复创建同一 prediction。
- Worker 重启：从 SQLite 恢复 `queued` 和可恢复的 `running` 任务。
- 下载失败：只重试下载阶段。
- 目标节点被删除：生成结果保留为未绑定 Asset。
- 画布 revision 变化：任务保留原始输入快照，避免覆盖用户新操作。
- SSE 断线：使用 revision 追赶，无法追赶时重新读取 snapshot。

## 10. 验收标准

### 画布

- 可以创建、移动、缩放和删除图片、视频、便签节点。
- 可以上传图片和视频并在节点内展示。
- 图片、视频和便签节点在刷新服务和页面后恢复原位置、尺寸、内容和素材。
- 图片节点只允许图片上游；视频节点允许图片或视频上游。
- 自连接、重复边和环路会被拒绝，并返回稳定错误码。
- 隐藏连线、节点选中、端点悬停、小地图和主题切换可用。
- 视频只在悬停时播放。

### 生成

- 配置 `REPLICATE_API_TOKEN` 后，可以从图片节点发起 Seedream 5 Pro 任务。
- 可以从视频节点发起 Seedance 2.0 Mini 任务。
- 任务状态从 queued 到 succeeded 或 failed 可见。
- 生成结果会下载到本地并绑定到目标节点。
- 服务或 Worker 重启后，任务记录和已完成素材不会丢失。

### Agent

- Agent 可以读取完整 snapshot。
- Agent 可以通过命令创建节点、建立连接、更新便签和发起生成。
- 旧 revision 命令不会覆盖新画布状态。
- 重试同一个 idempotency key 不会重复写入。
- Agent 不需要依赖前端 DOM 或浏览器自动化。

## 11. 设计参考

- [React Flow Overview](https://reactflow.dev/learn/concepts/terms-and-definitions)
- [React Flow Save and Restore](https://reactflow.dev/examples/interaction/save-and-restore)
- [FastAPI Server-Sent Events](https://fastapi.tiangolo.com/tutorial/server-sent-events/)
- [Replicate HTTP API](https://replicate.com/docs/reference/http)
- [Replicate Input Files](https://replicate.com/docs/topics/predictions/input-files)
- [Seedream 5.0 Pro](https://replicate.com/bytedance/seedream-5-pro)
- [Seedance 2.0 Mini](https://replicate.com/bytedance/seedance-2.0-mini)
