# Film Copilot Agent 第一阶段 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Agent 能通过和前端相同的画布命令操作画布：对话面板、流式回复、查看生成结果、来源标记与高亮、权限确认、停止、按任务撤销。记忆功能在第二阶段，本阶段只建好项目和会话的表，保存对话记录。

**Spec:** docs/superpowers/specs/2026-09-23-film-copilot-agent-design.md（第 2、3、4、6、7 节，5.6 对话记录）

**Tech Stack（新增）:** claude-agent-sdk（Python），Anthropic API（`claude-opus-5-5`），ffmpeg（视频抽帧），Pillow（已有，图片缩放）。

## Global Constraints

- Agent 的所有画布写入都经过 `CanvasCommandService.execute`，不直接写 SQLite。
- Agent 只能用本项目定义的画布工具；SDK 自带的文件读写、命令行、网页等工具全部关闭（`tools=[]`）。
- 权限规则在代码里判断（第 4.1 节），Skill 和系统提示词都不能绕过。
- `ANTHROPIC_API_KEY` 只从 `.env` 读取，不进数据库、不进前端、不写日志。
- 模型 ID 从 `AGENT_MODEL` 读取，默认 `claude-opus-5-5`。
- 发给模型的图片长边不超过 1024 像素；视频只发 3 张关键帧。
- 完整对话永久保存在本地（`agent_sessions` / `agent_messages`）。
- 现有前端手动操作的行为不变；已有测试全部继续通过。

## Review Focus

- **Agent 不覆盖用户改动：** Agent 写入时版本号冲突，必须重新读取画布并告知 Agent，不能用新版本号直接重发原命令。由 Task 4 `test_conflict_rereads_and_reports_user_changes` 固定。
- **撤销不回滚用户的改动：** 节点在 Agent 改完后被用户改过，撤销时跳过。由 Task 3 `test_undo_skips_nodes_user_changed_later` 固定。
- **权限不能被绕过：** 视频生成在任何档位都要确认；超出生成次数上限要确认。由 Task 5 `test_video_generation_always_asks` 和 `test_generation_cap_forces_confirmation` 固定。
- **停止真的停止：** 点停止后不再发出任何画布命令。由 Task 6 `test_stop_prevents_further_commands` 固定。
- **Key 不泄露：** API Key 不出现在接口返回、SSE、日志和数据库里。由 Task 7 `test_api_key_never_leaves_backend` 固定。

---

## 文件结构

```
api/app/
  agent/
    __init__.py
    config.py          # AGENT_MODEL、ANTHROPIC_API_KEY、上限等配置
    canvas_tools.py    # 画布工具的纯 Python 实现（不依赖 SDK，便于测试）
    media.py           # 图片缩放、视频抽帧
    permissions.py     # 权限档位判断（纯函数）+ 确认请求中转
    mcp_server.py      # 把 canvas_tools 包成 SDK 的 MCP 工具
    runtime.py         # AgentService：会话、SDK 客户端、事件流、停止
    prompts.py         # 系统提示词
    undo.py            # 按任务撤销
    store.py           # agent_sessions / messages / runs / run_changes 读写
  routes/agent.py      # HTTP + SSE 接口
api/tests/
  test_projects.py
  test_command_actor.py
  test_agent_undo.py
  test_canvas_tools.py
  test_agent_media.py
  test_agent_permissions.py
  test_agent_runtime.py
  test_agent_routes.py
.claude/skills/
  plan-first/SKILL.md
  storyboard/SKILL.md
  prompt-craft/SKILL.md
web/src/
  agent/
    agentApi.ts        # 接口与 SSE 客户端
    agentStore.ts      # 会话、消息、待确认、运行状态
    AgentPanel.tsx     # 右侧对话面板
    AgentMessage.tsx   # 单条消息（文字 / 工具步骤 / 图片）
    ConfirmCard.tsx    # 待确认操作卡片
  test/
    agentStore.test.ts
    AgentPanel.test.tsx
```

---

## Task 0: 技术验证（半天以内）

目的：在写正式代码前，确认 SDK 在本机能跑、关键能力符合设计。结论写进 `DEVELOPMENT_LOG.md`。

- [ ] 在 `.venv` 安装 `claude-agent-sdk`，确认它需要的 Claude Code 运行时能在 Mac 上启动（需要 Node，已安装）
- [ ] 用 `ANTHROPIC_API_KEY` + `claude-opus-5-5` 跑通一个最小 `query`
- [ ] 验证进程内 MCP 工具能返回 `image` 内容块，模型能描述图片内容
- [ ] 验证 `tools=[]` 后模型看不到任何自带工具
- [ ] 验证权限回调（`can_use_tool` 或 `PreToolUse` 钩子）能**异步等待**外部确认后再放行或拒绝；选定其中一种
- [ ] 验证 `ClaudeSDKClient` 的流式输出能拿到逐段文字（用于面板流式显示）
- [ ] 验证中断当前任务的方法（`interrupt()`）及中断后工具不再被调用
- [ ] 验证 Skill 从项目 `.claude/skills/` 加载的配置方式
- [ ] 检查 Mac 上是否有 `ffmpeg`；没有则在 README 和 `dev.sh` 前置检查里加上 `brew install ffmpeg`

**完成标准：** 每一项有明确结论；任何一项不成立，停下来调整设计后再继续。

---

## Task 1: 项目表与 Agent 数据表

**Files:** `api/app/db.py`、`api/app/repositories.py`、`api/app/agent/store.py`、`api/tests/test_projects.py`

- [ ] 新表 `projects(id, name, created_at)`；启动时确保存在 `default` 项目
- [ ] `canvases` 增加 `project_id`（默认 `default`），旧库自动迁移，现有画布归入 `default`
- [ ] 新表：
  - `agent_sessions(id, project_id, canvas_id, title, summary, created_at, ended_at)`
  - `agent_messages(id, session_id, run_id, role, content_json, created_at)`：`role` 为 `user` / `assistant` / `tool_call` / `tool_result` / `system_event`
  - `agent_runs(id, session_id, status, permission_mode, generation_count, created_at, finished_at)`：`status` 为 `running` / `waiting_confirmation` / `stopped` / `completed` / `failed` / `undone`
  - `agent_run_changes(id, run_id, seq, entity_type, entity_id, before_json, after_json, revision)`
- [ ] 图片消息只存素材 ID，不存图片数据
- [ ] 测试：新库、旧库迁移后 `default` 项目存在且现有画布归属正确；会话和消息能写入读出

---

## Task 2: 命令来源标记与改动记录

**Files:** `api/app/schemas.py`、`api/app/commands.py`、`api/app/events.py`、`api/app/repositories.py`、`api/tests/test_command_actor.py`

- [ ] `CommandEnvelope` 增加可选字段 `actor`（`user` | `agent`，默认 `user`）和 `agentRunId`
- [ ] 画布事件 payload 带上 `actor` 和 `agentRunId`
- [ ] 当 `agentRunId` 存在时，`execute` 在同一事务里记录受影响节点和连线的改动前 / 改动后状态到 `agent_run_changes`：
  - `create_node` / `duplicate_nodes`：before 为空
  - `update_node` / `move_nodes` / `attach_asset`：before、after 都记
  - `delete_elements` / `delete_node`：记下被删节点和随之删除的连线（级联删除的连线也要记）
  - `connect_nodes` / `disconnect_nodes`：记连线
  - `start_generation`：记任务 ID（撤销时用来解除结果关联）
- [ ] 前端手动操作（没有 `agentRunId`）不记录，性能不受影响
- [ ] 测试：每类命令记录正确；幂等重试不重复记录；事件里有 `actor`

---

## Task 3: 按任务撤销

**Files:** `api/app/agent/undo.py`、`api/tests/test_agent_undo.py`

- [ ] `undo_run(run_id)` 按 `seq` 倒序处理改动：
  - 新建的节点 / 连线 → 删除
  - 修改的节点 → 恢复 before 的值
  - 删除的节点 → 用原 ID 重建，连同原来的连线
  - 生成任务 → 若结果已挂到节点上，移除这个关联
- [ ] **跳过规则：** 节点当前状态和该 run 最后一次记录的 after 不同（说明之后被用户或其他 run 改过），跳过这个节点，记入结果的 `skipped` 列表
- [ ] 撤销本身以 `actor=agent`、新的 idempotency key 通过命令服务执行，所以也会产生事件、前端实时更新
- [ ] run 状态改为 `undone`；同一 run 不能撤销两次
- [ ] 测试：`test_undo_restores_created_updated_deleted`、`test_undo_skips_nodes_user_changed_later`、`test_undo_is_not_repeatable`

---

## Task 4: 画布工具（不依赖 SDK 的纯实现）

**Files:** `api/app/agent/canvas_tools.py`、`api/app/agent/media.py`、`api/tests/test_canvas_tools.py`、`api/tests/test_agent_media.py`

- [ ] `CanvasToolContext`：画布 ID、run ID、最后看到的版本号、命令服务、仓库
- [ ] 实现规格 3.1 的全部工具：`get_canvas`、`get_node`、`view_asset`、`create_nodes`、`update_node`、`connect`、`disconnect`、`move_nodes`、`duplicate_nodes`、`delete_nodes`、`generate`、`wait_for_generation`
- [ ] 所有写入工具用 `actor=agent`、`agentRunId`、确定性的 idempotency key（run ID + 步骤序号），Agent 重试同一步不会重复写
- [ ] `get_canvas` 精简输出：每个节点 ID、类型、标题、位置、Prompt 前 80 字、生成状态、上游节点 ID；可选 `node_ids` 只看指定节点及其上下游
- [ ] **版本冲突处理：** 写入遇到 `REVISION_CONFLICT` 时，不重发，返回错误说明 + 本次冲突期间变化的节点列表（从事件表读取），由 Agent 决定下一步
- [ ] 错误信息改写成中文说明，例如 `INVALID_CONNECTION` →「视频节点不能作为图片节点的参考」
- [ ] `create_nodes` 未给位置时，自动排在当前画布内容右侧，不与现有节点重叠
- [ ] `media.py`：
  - `image_for_model(path)`：长边缩到 1024，转 JPEG，返回 base64
  - `video_frames_for_model(path)`：用 ffmpeg 取首、中、尾 3 帧，同样处理；没有 ffmpeg 时返回明确错误
- [ ] `wait_for_generation`：轮询任务状态，最长等 5 分钟（视频可配置），完成后返回缩小的结果图 / 关键帧，失败返回原因
- [ ] 测试：每个工具的正常与错误路径；`test_conflict_rereads_and_reports_user_changes`；重试同一步幂等；图片缩放尺寸；视频抽帧数量

---

## Task 5: 权限判断与确认中转

**Files:** `api/app/agent/permissions.py`、`api/tests/test_agent_permissions.py`

- [ ] 纯函数 `decide(tool_name, args, mode, run_state) -> allow | ask | deny`：
  - 只读工具永远 `allow`
  - `每步确认`：写入都 `ask`
  - `只确认生成`（默认）：`generate`、`delete_nodes` 为 `ask`，其他 `allow`
  - `全自动`：`allow`
  - 无论档位：视频节点的 `generate` → `ask`；本轮生成次数达到上限（默认 4）→ `ask`
- [ ] `ConfirmationBroker`：`request(run_id, summary) -> awaitable`，`resolve(request_id, approved)`；超时（默认 10 分钟）按拒绝处理
- [ ] 确认请求的摘要由工具参数生成，例如「生成 3 张图片：图片 2、图片 3、图片 4」
- [ ] 权限档位按项目保存在 `projects` 表的设置字段里
- [ ] 测试：`test_video_generation_always_asks`、`test_generation_cap_forces_confirmation`、各档位矩阵、超时按拒绝

---

## Task 6: Agent 运行时

**Files:** `api/app/agent/config.py`、`api/app/agent/prompts.py`、`api/app/agent/mcp_server.py`、`api/app/agent/runtime.py`、`api/tests/test_agent_runtime.py`

- [ ] `mcp_server.py`：用 `@tool` + `create_sdk_mcp_server` 包装 Task 4 的工具；只读工具加 `readOnlyHint`
- [ ] `prompts.py`：系统提示词（中文），包括角色、工具使用规则、看图后给简短评价、冲突时先向用户说明、当前权限档位
- [ ] `AgentService`：
  - 每个会话一个 `ClaudeSDKClient`；`model=AGENT_MODEL`、`tools=[]`、只允许本项目 MCP 工具、加载项目 Skill
  - 权限回调调用 Task 5 的 `decide`，需要确认时通过 broker 等待
  - 用户消息附带选中节点 ID 时，在消息前加一段「当前关注的节点」说明
  - 把 SDK 输出转成统一事件：`text_delta`、`tool_step`（一句话描述 + 涉及节点 ID）、`image`（素材 ID）、`confirm_request`、`run_finished`、`error`
  - 所有事件写入 `agent_messages`，同时推给该会话的订阅者
  - `stop(run_id)`：调用 SDK 中断，并在工具层设置停止标志，之后的写入工具直接返回「已停止」
- [ ] 同一会话同时只允许一个 run；上一个没结束时新消息排队或提示
- [ ] 测试（用假的 SDK 客户端，不调用真实模型）：事件顺序与落库；`test_stop_prevents_further_commands`；确认拒绝后 Agent 收到「用户拒绝」

---

## Task 7: HTTP 与 SSE 接口

**Files:** `api/app/routes/agent.py`、`api/app/main.py`、`api/tests/test_agent_routes.py`

- [ ] 实现规格第 7 节中与本阶段相关的接口：
  - `POST /api/agent/sessions`、`GET /api/agent/sessions`、`GET /api/agent/sessions/{id}/messages`
  - `POST /api/agent/sessions/{id}/messages`
  - `GET /api/agent/sessions/{id}/stream`（SSE，支持断线后从某条消息之后继续）
  - `POST /api/agent/runs/{id}/confirm`、`/stop`、`/undo`
  - `GET/PATCH /api/projects/{id}/agent-settings`（权限档位、生成上限）
- [ ] 没有配置 `ANTHROPIC_API_KEY` 时，接口返回明确提示，画布其他功能照常
- [ ] 测试：接口正常路径；`test_api_key_never_leaves_backend`（接口、SSE、日志、数据库均不含 Key）

---

## Task 8: 前端对话面板

**Files:** `web/src/agent/*`、`web/src/canvas/CanvasShell.tsx`、`web/src/canvas/CanvasRail.tsx`、`web/src/styles.css`、`web/src/test/agentStore.test.ts`、`web/src/test/AgentPanel.test.tsx`

- [ ] `agentApi.ts` + `agentStore.ts`：会话、消息、流式文字拼接、待确认列表、当前 run 状态；SSE 断线自动重连并补齐
- [ ] `AgentPanel`：画布右侧可收起，`⌘J` 开关，左侧栏加一个入口图标（带气泡提示）
  - 输入框：回车发送，Shift+回车换行；有选中节点时显示「关注：图片 2、视频 1」小标签
  - 消息：Agent 文字流式显示；工具步骤显示成一行说明，点击定位到节点；Agent 看过的图以缩略图显示
  - `ConfirmCard`：摘要 + 确认 / 拒绝
  - 运行中显示「停止」；结束后显示「撤销本轮」，撤销结果里有被跳过的节点时列出来
  - 顶部：权限档位切换、历史会话列表
- [ ] 面板打开时画布快捷键（V、H、空格、Delete、⌘D）在输入框里不生效
- [ ] 按 `docs/DESIGN.md` 的颜色、圆角、图标按钮、气泡规范实现
- [ ] 测试：流式文字拼接、确认卡片交互、停止与撤销按钮状态、快捷键不冲突

---

## Task 9: Agent 改动高亮

**Files:** `web/src/state/canvasStore.ts`、`web/src/canvas/CanvasShell.tsx`、`web/src/styles.css`

- [ ] 从画布事件的 `actor` / `agentRunId` 得出「当前 run 改动过的节点」集合
- [ ] 这些节点加一圈强调色描边和「Agent」小标签，悬停显示「Agent 修改」；run 结束 10 秒后淡出，撤销后立即移除
- [ ] 点击面板里的工具步骤时，画布平移到对应节点并短暂闪烁
- [ ] 测试：事件驱动的高亮集合计算

---

## Task 10: Skill 与系统提示词调优

**Files:** `.claude/skills/plan-first/SKILL.md`、`.claude/skills/storyboard/SKILL.md`、`.claude/skills/prompt-craft/SKILL.md`、`api/app/agent/prompts.py`

- [ ] `plan-first`：先用一两句话说计划；改动超过 5 个节点先列方案等同意
- [ ] `storyboard`：把一段剧情拆成分镜（便签写镜头描述 → 图片节点出画面 → 视频节点做动态），从左到右排版
- [ ] `prompt-craft`：Seedream / Seedance 的 Prompt 写法、参考图用法、各参数何时用
- [ ] 用 5 个固定任务人工跑一遍，按结果调整提示词：
  1. 「用这张兔子图做 3 个不同风格的版本」
  2. 「把这三张图做成一段 5 秒的视频」
  3. 「帮我整理一下画布，按流程从左到右排好」
  4. 「看看刚才生成的哪张最好，说说理由」
  5. 生成过程中手动改一个节点，观察 Agent 的冲突处理

---

## Task 11: 验收与文档

- [ ] 规格 8 节第一阶段的完成标准，用真实模型走通
- [ ] 后端、前端全部测试通过；`tsc -b`、`vite build` 通过
- [ ] README：`ANTHROPIC_API_KEY`、`AGENT_MODEL`、ffmpeg 安装说明
- [ ] `docs/DESIGN.md`：对话面板、确认卡片、Agent 高亮的规范
- [ ] `DEVELOPMENT_LOG.md`：本阶段记录（含未验证项）

---

## 顺序与依赖

```
Task 0 ─┬─ Task 1 ─ Task 2 ─┬─ Task 3
        │                   └─ Task 4 ─ Task 5 ─ Task 6 ─ Task 7 ─┬─ Task 8 ─ Task 9
        │                                                          └─ Task 10
        └──────────────────────────────────────────────────────────────── Task 11
```

- Task 0 不通过就不继续。
- Task 3 和 Task 4 可以并行。
- Task 8 可以先用假的 SSE 数据开发，等 Task 7 完成后再接上。

## 风险

| 风险 | 应对 |
| --- | --- |
| SDK 依赖 Claude Code 运行时，启动慢或在本机跑不起来 | Task 0 验证；不行就改用 Anthropic API + 自己写工具调用循环，工具层（Task 4、5）不受影响 |
| Opus 5.5 带图片的调用费用高 | 图片统一缩到 1024；只在生成完成和用户要求时看图；面板显示本轮大致消耗 |
| 长任务中途用户频繁改画布，Agent 反复冲突 | 冲突时把变化告诉 Agent；连续 3 次冲突就暂停并询问用户 |
| 撤销时级联删除的连线漏记 | Task 2 专门测试删除节点时连带删除的连线 |
