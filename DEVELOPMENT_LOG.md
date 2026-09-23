# Film Copilot 开发日志

> 项目原名 Infinite Media Canvas，2026-09-23 更名；分支名和早期文档文件名沿用旧名。

> 用途：持续记录产品范围、开发进度、缺陷原因与修复、验证结果和技术参考。新增记录请放在“开发与修复记录”最上方，并注明事实来源；模型生成、部署等未实际验证的内容要明确标记。

## 项目状态

- 最近更新：2026-09-23
- 本地项目目录：`/Users/justingu/Desktop/Agent Demo/.worktrees/infinite-media-canvas`
- 当前分支：`feature/infinite-media-canvas`
- 最近已提交版本：`d80e36d fix: restore persisted viewport on canvas load`
- 9/23 的改动均已提交；仓库当前没有配置 Git remote。
- 本地 Web 地址：<http://127.0.0.1:5173/>
- 产品形态：单用户、本机运行；当前无账号、多用户权限和协作功能。

## 产品范围与已确认决定

- 画布组织图片、视频、便签和生成任务；节点可自由摆放、缩放视口、平移，并以连线表达“参考素材 → 目标节点”。
- 图片节点只接受图片参考；视频节点可接受图片或视频参考。后端校验连接合法性并阻止自连接、重复连接和循环。
- 上传素材和生成结果保存在本地。节点内容、连接关系、视口、生成任务通过本地服务和 SQLite 持久化。
- 模型参数直接放在图片或视频节点的 Prompt 输入区内编辑。
- 图片模型：Replicate `bytedance/seedream-5-pro`。
- 视频模型：Replicate `bytedance/seedance-2.0-mini`。
- 后续 Agent 应调用与前端相同的结构化画布命令 API；不直接操作前端 DOM 或绕过领域服务写数据库。
- 第一版不包含多人协作、权限、评论、模型自动路由和复杂模型参数面板。

## 技术方案

| 部分 | 当前选型与职责 |
| --- | --- |
| 前端 | React 19、TypeScript、Vite 7；实现节点、工具栏、主题和画布交互 |
| 画布 | `@xyflow/react`（React Flow 12）；负责节点、边、视口、拖动、小地图与选择交互 |
| 前端状态 | Zustand；保存当前快照、选择状态并协调本地 API 同步 |
| 本地 API | Python 3.11+、FastAPI、Pydantic；校验画布命令、revision 和连接规则 |
| 持久化 | SQLite；保存画布、节点、边、事件、命令幂等记录及生成任务 |
| 媒体 | 本地 `data/assets/`；上传和生成产物由本地 Asset API 管理 |
| 生成任务 | 独立 Python Worker 从 SQLite 领取任务，调用 Replicate 并写回结果 |
| 后端测试 | pytest、FastAPI TestClient |
| 前端测试与构建 | Vitest、Testing Library、TypeScript、Vite build |

API、Web 和 Worker 的启动方式见 [README.md](README.md) 与 [scripts/dev.sh](scripts/dev.sh)。本地运行不等于已验证真实模型调用；没有 `REPLICATE_API_TOKEN` 时，自动化测试和 fake Provider 测试不能证明线上模型生成成功。

## 开发与修复记录

### 2026-09-23 Agent 和用户同时改画布不再动不动就停 + 画布标记（Task 9）

- 用户现象：Agent 执行中，用户动一下画布它就停；有一次一次生成 4 个节点时报「generate 未完成」，Agent 说「系统提示你也在改画布」但找不到改了哪里。
- 根因（已确认）：Agent 写入时拿整张画布的版本号比对。拖节点、平移画布（视角会存盘），以及 Worker 更新生成任务状态都会让版本号 +1。一次生成多个节点时，第一个任务开始排队/运行就让后面几个的版本号过期，于是报冲突；冲突说明只列用户命令，Worker 的变化不在里面，所以什么也没列出来。
- 改动：
  - 新增 `api/app/agent/conflicts.py`：CanvasTools 维护 `seen`（Agent 看过的画布 + 自己的改动，按字段合并），每次写入前和实时画布对比，按节点和字段（删除 / 位置 / 名字 / Prompt / 参数 / 用户换图 / 连线）判断；只有命中这一步的依赖才拦下，否则用最新版本号直接执行（并发时最多重试 5 次）。生成结果换图不算用户改动。
  - 各工具声明依赖：改节点只看写入的字段；移动看位置；删除看用户是否编辑过；生成看目标的 Prompt/参数/连线和上游的文字、图。
  - 被拦下时的提示改为：先 `get_node` 看最新，不矛盾就继续做完，矛盾才问用户。盲目重试仍会被拦。系统提示词同步。
  - 确认请求事件带 `touched`；前端 `agentMarks.ts` 算出节点标记，画布加虚线外圈和「Agent / 等你确认 / Agent 刚改过」标签，只提示不锁定。
- 验证：后端 97 个、前端 49 个测试通过，`tsc -b` 通过；标记样式用静态页面截图检查过。真实模型下的冲突表现需在 Mac 上实跑。

### 2026-09-23 确认卡片支持补充说明

- 用户需求：Agent 请求确认时（如「生成 4 个节点…」），只有确认/拒绝两个按钮，没法顺带说「镜头 2 改成夜景」这类补充。
- 改动：
  - 前端确认卡片加可选输入框；有内容时按钮文案变为「确认并补充」「拒绝并说明」，⌘↵ 确认；请求失败时卡片恢复可再点。`confirm_resolved` 事件带 `note`，面板显示「补充：…」。
  - `POST /agent/runs/{id}/confirm` 新增 `note`（≤2000 字）；`ConfirmationBroker` 结果改为 `(approved, note)`。
  - 拒绝 + 补充：拒绝消息附「用户补充：…」，并让 Agent 按补充调整后继续（不再是「先问用户」）。
  - 确认 + 补充：这一步照原样执行，补充追加在这次工具结果末尾交给模型，用一次即清空。
- 验证：后端 94 个测试、前端 47 个测试通过，`tsc -b` 通过。真实模型下对补充的遵循度未验证，需在 Mac 上实跑。

### 2026-09-23：Agent 第一阶段 Task 8（对话面板）+ Markdown

- 新依赖：`react-markdown`、`remark-gfm`（需要在 `web/` 里重新安装依赖）。
- `web/src/agent/`：`agentApi`（接口 + 自动重连的 SSE）、`agentStore`（事件归并、流式文字、待确认、可撤销的轮次）、`AgentPanel`、`AgentMessage`、`Markdown`。
- 回复按 Markdown 渲染，表格横向可滑，原始 HTML 不执行；每条回复可复制、可「存到画布」（存成便签，标题取第一行）。
- 便签改为 Markdown：平时显示渲染结果，双击编辑原文。
- 系统提示词：剧本、分镜等长内容优先按场景写进画布便签（从左到右一排），对话里只给概要；用户明确要文字时才整段回复。
- 左侧栏新增 Agent 入口，⌘J 开关；点击工具步骤会选中并定位节点。
- 验证：前端 45 项、后端 93 项测试通过；用假模型在浏览器里走通「写三场剧本 → 画布出现三个便签 → 面板显示表格 → 可撤销」。
- 已知：点步骤定位节点时，缩放没有避开面板，节点可能被面板挡住一部分。

### 2026-09-23：Agent 第一阶段 Task 6–7（运行时、接口）

- `app/agent/mcp_server.py`：把 12 个画布工具包成 SDK 的进程内 MCP 工具（工具说明为中文）；只读工具标 `readOnlyHint`。
- `app/agent/prompts.py`：系统提示词；每条用户消息前附上当前权限档位、本轮可直接生成次数、选中的节点。
- `app/agent/runtime.py`：`AgentService`
  - 每个会话一个长期存在的 SDK 客户端；记下 SDK 的会话 ID（新列 `agent_sessions.sdk_session_id`），后端重启后可以接着聊。
  - 每条消息开启一个 run；同一会话同时只允许一个 run。
  - 权限：`can_use_tool` 调用 `decide()`，需要确认时挂起并推送 `confirm_request`；写入工具不放进 `allowed_tools`。
  - 事件：`user_message`、`text_delta`（只推送不保存）、`assistant_text`、`tool_step`、`confirm_request` / `confirm_resolved`、`error`、`run_finished`、`run_undone`；除 `text_delta` 外都存进 `agent_messages`。
  - 停止：工具层停止标志 + 取消待确认 + SDK `interrupt()`。认证失败（401/403）时直接结束并提示。
- `app/routes/agent.py`：`/api/agent/status`、会话创建 / 列表 / 消息、发送消息、SSE（先订阅再回放，断线可从某条消息之后继续，15 秒心跳）、确认、停止、撤销、项目 Agent 设置。
- `scripts/agent_chat.py`：面板完成前，在终端里和 Agent 对话、确认、停止、撤销。
- 测试：用脚本化的假 SDK 客户端（`tests/agent_fakes.py`）覆盖流式、工具调用、确认同意 / 拒绝、停止、单 run 限制、未配置 Key、撤销、接口流程，以及 Key 不出现在任何接口返回、日志、数据库和 SDK 参数里。后端共 93 项通过。
- 未验证：真实模型下的完整对话（需在用户本机用 `agent_chat.py` 试）。

### 2026-09-23：Agent 第一阶段 Task 4–5（画布工具、权限）

**Task 4：画布工具**（`app/agent/canvas_tools.py`、`app/agent/media.py`）

- 12 个工具：`get_canvas`、`get_node`、`view_asset`、`create_nodes`、`update_node`、`connect`、`disconnect`、`move_nodes`、`duplicate_nodes`、`delete_nodes`、`generate`、`wait_for_generation`。纯 Python 实现，不依赖 SDK。
- 所有写入走画布命令服务，`actor=agent` + 任务 ID，幂等键为「任务 ID + 步骤序号」。
- 版本冲突时不重发，把冲突期间用户改过的节点告诉 Agent，并要求它先看最新内容、有冲突先问用户。
- 生成中的节点拒绝修改、连线变更和重复生成；没有 Prompt 也没连便签的节点拒绝生成。
- 参数只接受界面上有的取值，错误用中文说明，方便 Agent 自己改正。
- 新节点自动命名（图片 N），默认排在现有内容右侧一列。
- 图片发给模型前缩到长边 1024；视频用 ffmpeg 取首、中、尾 3 帧。
- `wait_for_generation` 轮询任务，完成后直接返回结果图 / 关键帧，失败返回原因。

**Task 5：权限**（`app/agent/permissions.py`）

- `decide()`：只读工具放行；三档（每步确认 / 只确认生成和删除 / 全自动）；视频生成、超出本轮生成上限在任何档位都要确认；未知工具拒绝。
- `ConfirmationBroker`：挂起工具调用等用户确认；超时（默认 10 分钟）或任务被停止都按拒绝处理。

**验证**：后端 84 项测试全部通过（含视频抽帧，需要 ffmpeg）。

### 2026-09-23：Agent 第一阶段 Task 1–3（数据表、来源标记、按任务撤销）

**缺陷修复：带便签的生成结果不会显示到节点上（已确认）**

- 现象：加入「便签作为提示词」后，生成完成的结果都被标为 `completed_unattached`，不会挂到节点上。
- 根因：Worker 通过比较「提交时的生成快照」和「当前快照」判断节点是否被改过；提交时快照多了 `nodePrompt` 字段、`prompt` 也被拼上了便签文字，而当前快照没有，所以永远不相等。
- 修复：拼接逻辑移到 `repository.generation_snapshot`（新文件 `app/prompting.py`），两边用同一种方式生成；加了回归测试。

**Task 1：数据表**

- 新表 `projects`（含 `settings_json`，默认项目 `default`）、`agent_sessions`、`agent_runs`、`agent_messages`、`agent_run_changes`；`canvases` 增加 `project_id`，旧库自动迁移。
- `app/agent/store.py`：项目设置（权限档位、生成上限）、会话、任务、消息的读写。

**Task 2：命令来源**

- `CommandEnvelope` / `CommandResult` 增加 `actor`、`agentRunId`；画布事件带上这两项。
- 带 `agentRunId` 的命令在同一事务里对比执行前后的整张画布，记录每个节点、连线的改动前后状态（能捕捉删除节点时级联删掉的连线）；生成任务单独记录。视口变化和撤销本身不记录。

**Task 3：按任务撤销**

- 新命令 `undo_agent_run`（`app/agent/undo.py`），在一个事务里完成：删除本轮新建的、按原样恢复本轮修改或删除的节点和连线、取消还没开始的生成任务。
- 本轮结束后又被改过的节点跳过，结果里列出；本轮自己的生成结果挂到节点上不算「被改过」。
- 运行中的任务不能撤销；同一任务不能撤销两次。

**验证**：后端 50 项测试全部通过。

### 2026-09-23：Agent 第一阶段 Task 0 技术验证

- 脚本：[scripts/agent_spike.py](scripts/agent_spike.py)，在用户 Mac 上运行，6/6 通过，花费约 $0.07。
- 结论：
  - `claude-agent-sdk` 0.2.158 可直接使用，自带运行时，无需另装 Claude Code。
  - `claude-opus-5-5` 首次响应约 3 秒；`include_partial_messages=True` 可拿到流式文字。
  - `tools=[]` 后模型只能看到我们的 MCP 工具。
  - 进程内 MCP 工具返回 `image` 内容块，模型能正确描述图片。
  - `can_use_tool` 回调可以异步等待（模拟等用户确认）后拒绝，工具不会执行。选定 `can_use_tool` 作为权限入口。
  - **注意：** 写入类工具不能放进 `allowed_tools`，否则会跳过 `can_use_tool`（SDK 会给出 `CanUseToolShadowedWarning`）。只读工具可以放行。
  - `interrupt()` 后工具不再执行。
  - 用户 Mac 已安装 ffmpeg（`/opt/homebrew/bin/ffmpeg`）。
- 环境限制：Claude 的远程开发环境会拦截带 Anthropic Key 的请求，真实模型调用只能在用户本机验证；自动化测试一律使用假的 SDK 客户端。
- `.env` / `.env.example` 新增 `ANTHROPIC_API_KEY`、`AGENT_MODEL`；`api/pyproject.toml` 加入 `claude-agent-sdk` 依赖。

### 2026-09-23（下午）：界面重做、便签提示词、节点复制等

**缺陷修复**

- 图片生成 422：前端选 JPEG 时后端把格式改写成 `jpg`，Seedream 5 Pro 只认 `png` / `jpeg`。现在改为按 `jpeg` 发送，并加了测试（已用真实 Replicate 调用确认出图）。
- 输入框打字报 "Expected revision N"：每个字都发一次保存，请求互相冲突。改为输入停顿 0.5 秒后再保存（失焦、点生成时立即保存）；前端命令改为排队依次发送并带最新版本号，遇到外部改动先刷新再重试一次。
- 便签文字、字体、字号从未保存：便签的输入框和下拉框都没有接上保存逻辑。
- 节点状态取的是最早一次生成任务，失败过一次就一直显示失败；改为取最新一次。
- 拖线菜单无法关闭；新节点位置没换算画布坐标；从输入端拖线时方向反了；菜单里会出现连不上的节点类型。
- 端点热区放大后连线起点偏离端点。
- `dev.sh` 在 macOS 自带的 bash 3.2 上无法运行（`wait -n`、全角括号紧跟变量名）。

**新功能与界面**

- 界面：左侧栏（「+」添加节点、上传后按文件类型自动建节点），左下角画布控件，顶部错误提示，统一的气泡提示组件。
- 画布：触控板双指平移、捏合缩放（含 Safari 单独处理），视口停止操作 0.6 秒后保存。
- 节点：可编辑名称并自动编号；「⋯」菜单（上传、下载、全屏查看、复制节点）；生成中遮罩和失败原因显示；空预览区的上传按钮；视频播放控件。
- 参考素材栏：视频节点也显示参考；显示没内容的上游；显示便签卡片；放不下时可横向滑动。
- 便签作为提示词：便签只保留输出端，可连到图片/视频节点；生成时上游便签文字按连线顺序放在节点提示词前面（后端 `compose_prompt`）。
- 复制节点：Option 拖动、⌘/Ctrl+D、菜单；后端新增 `duplicate_nodes` 命令，副本保留输入连线、不复制输出连线。
- 新增设计规范 [docs/DESIGN.md](docs/DESIGN.md)。

**验证结果**

- 后端 pytest 全部通过；前端 vitest 全部通过，`tsc -b` 通过。
- 在隔离环境用浏览器实际操作过上述主要交互；图片生成已在用户本机通过真实 Replicate 调用验证。
- 未验证：Safari 捏合缩放、真实视频生成、浏览器下载文件名（测试浏览器报告不准）。

### 2026-09-23：API 与 Worker 数据目录不一致、Token 存放

**API 和 Worker 读写两个不同的数据库**

- 现象：`scripts/dev.sh` 在 `api/` 目录启动 API，在项目根目录启动 Worker，而 `CANVAS_DATA_DIR=./data` 按当前工作目录解析。API 实际使用 `api/data/canvas.sqlite3`，Worker 使用 `data/canvas.sqlite3`（空库），Worker 领不到 API 创建的生成任务；素材路径 `data/assets/...` 在 Worker 侧也找不到文件。
- 根因（已确认）：相对路径按进程 cwd 解析。两个库都存在且内容不同：`api/data` 有 1 个画布、3 个节点、1 个素材，`data/` 的所有表都为空。
- 修复：`api/app/config.py` 新增 `PROJECT_ROOT` 和 `resolve_project_path`，相对路径统一按项目根目录解析；素材文件读取（`routes/assets.py`）和 Worker 参考素材读取（`providers/replicate.py`）也用它来解析数据库里已有的相对路径。
- 数据迁移：`api/data/canvas.sqlite3` 和 `api/data/assets/` 移到根目录 `data/`；删除原来的空库。
- 新增测试 `api/tests/test_config.py`（3 项）：覆盖不同 cwd 解析到同一个库、绝对路径保持不变。

**Replicate Token**

- Token 从根目录明文 `replicatet_key.txt` 挪到 worktree 的 `.env`（权限 600），原文件已删除。
- 两个 `.gitignore` 增加 `.env`、`.env.*`（保留 `.env.example`）；原 worktree `.gitignore` 没有忽略 `.env`。

**验证结果**

- 后端：Python 3.11 隔离环境 `python -m pytest -q`，25 项通过。
- 未验证：真实 Replicate 生成；本次改动后没有重新跑 `dev.sh` 做端到端验证。

### 2026-09-23：删除复现、工具切换、多选和空画布启动修复

**删除后节点重新出现**

- 现象：删除操作只通过 React Flow 的 `onNodesChange` 更新前端临时状态；后端没有收到删除命令。下一次读取快照或页面刷新时，数据库中的节点又被加载出来。
- 修复：新增事务化 `delete_elements` 命令，一次删除多个节点和边；前端通过 React Flow 的 `onBeforeDelete` 提交命令，等待持久化快照更新后再显示结果。失败时保留节点并显示保存错误。
- 相关文件：[api/app/commands.py](api/app/commands.py)、[api/app/repositories.py](api/app/repositories.py)、[web/src/canvas/CanvasShell.tsx](web/src/canvas/CanvasShell.tsx)。

**鼠标 / 抓手工具与快捷键**

- 增加工具栏“鼠标”和“抓手”按钮。
- `V` 切换到鼠标工具；`H` 切换到抓手工具；在画布上按住空格临时使用抓手。
- 鼠标工具支持节点拖动和空白处框选；抓手工具用于平移画布。
- 相关文件：[web/src/canvas/CanvasToolbar.tsx](web/src/canvas/CanvasToolbar.tsx)、[web/src/canvas/CanvasShell.tsx](web/src/canvas/CanvasShell.tsx)、[web/src/styles.css](web/src/styles.css)。

**多选与成组移动**

- 将单节点选择状态扩展为节点 ID 列表；选中任一节点时仍显示与其相连的边。
- 支持框选和 Shift / Command / Control 点击追加或取消选择；多个节点拖动后通过一个命令保存位置。
- 后端 `move_nodes` 一次事务更新多个节点。
- 手动浏览器验证：隔离测试画布框选两个节点、一起拖动并保存；Shift 点击追加和取消选择。

**首次创建默认画布的并发错误**

- 现象：空数据库首次打开时，React StrictMode 可能触发两次默认画布读取和创建；两个创建请求都先检查“画布不存在”，其中一个随后遇到主键冲突。
- 修复：创建使用 SQLite `INSERT OR IGNORE`，并增加并发创建回归测试。
- 相关文件：[api/app/repositories.py](api/app/repositories.py)、[api/tests/test_repositories.py](api/tests/test_repositories.py)。

**验证结果**

- 后端：`python -m pytest -q`，22 项通过。
- 前端：`vitest run`，12 项通过；`tsc -b` 和 Vite production build 通过。
- 删除持久化回调有组件测试覆盖；并发创建有后端测试覆盖。

### 2026-09-22：已提交开发阶段摘要

以下记录根据本地 Git 提交历史整理：

1. `14dc500`、`e466add`：定义画布架构和实施计划。
2. `0e425cd`：搭建本地全栈应用骨架。
3. `a896b30`：添加参考关系图规则。
4. `5a09731`：添加持久化画布命令 API。
5. `affa5fc`：添加本地素材上传与读取服务。
6. `8579bc2`：添加 Replicate 生成 Worker。
7. `f8af125`、`4c810da`：添加 React Flow 画布、图片/视频/便签节点和参考关系操作。
8. `5d78415`：将模型参数放到节点 Prompt 区域。
9. `dfa8526`：串起本地 Worker 与端到端生成任务流程。
10. `c505cde`：修复视口和节点交互持久化。
11. `fbd938a`：上传视频后按素材比例调整节点。
12. `d80e36d`：修复加载时恢复已保存视口。

## 技术文档与参考

### 仓库内文档

- [产品与架构设计](docs/superpowers/specs/2026-09-22-infinite-media-canvas-design.md)：V1 范围、领域模型、命令 API、Agent 接入边界。
- [实施计划](docs/superpowers/plans/2026-09-22-infinite-media-canvas.md)：任务拆分、目录结构和关键风险检查点。
- [启动与测试说明](README.md)：本地环境、启动、Provider Token 和基础验证命令。

### 官方技术文档

- React：<https://react.dev/learn>
- Vite：<https://vite.dev/guide/>
- React Flow：<https://reactflow.dev/learn>；[ReactFlow 属性参考](https://reactflow.dev/api-reference/react-flow)；[`onBeforeDelete` 参考](https://reactflow.dev/api-reference/types/on-before-delete)
- Zustand：<https://zustand.docs.pmnd.rs/getting-started/introduction>
- FastAPI：<https://fastapi.tiangolo.com/>
- Pydantic：<https://docs.pydantic.dev/latest/>
- SQLite：<https://www.sqlite.org/docs.html>
- Vitest：<https://vitest.dev/guide/>
- Replicate Python 客户端：<https://github.com/replicate/replicate-python>
- Seedream 5 Pro 模型页：<https://replicate.com/bytedance/seedream-5-pro>
- Seedance 2.0 Mini 模型页：<https://replicate.com/bytedance/seedance-2.0-mini>

## 后续追加约定

每次开发或修 bug 后，在“开发与修复记录”顶部新增一条，最少写清：日期、用户可见现象、确认的根因、改动摘要、验证结果和未验证项。若只是猜测根因，标为“待确认”；真实模型调用、发版或外部服务效果没有实际验证时，不要写成已完成。
