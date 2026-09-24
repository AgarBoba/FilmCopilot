# Agent 第二阶段：项目记忆、用户偏好、对话间共享（轻量）

> 日期：2026-09-24。依据 `docs/superpowers/specs/2026-09-23-film-copilot-agent-design.md` 第 5 节。

## 和用户确认过的决定

- 写入方式：用户明确说出的设定和偏好，Agent **直接记**，不弹确认；对话里显示「记下了…」一行，可撤销。撤销这一轮也会收回这一轮记下 / 改掉 / 忘掉的内容。
- 管理界面：放在 Agent 面板里（标题栏「记忆」图标），分「本项目」「我的偏好」两栏，可添加、编辑、删除；Agent 改掉的旧版本折叠在「旧版本」里。
- 对话间共享（轻量版，提前做）：
  - 项目记忆天然在本项目所有对话里共享；偏好跨项目共享。
  - 每条消息前带上「这张画布上的其他对话」（名称、日期、最后一句）。
  - `recall` 工具可按关键词搜记忆和本项目所有对话的原话。
  - 不做自动摘要（要额外调用模型，留在第三阶段）。

## 做了什么

| 部分 | 文件 |
| --- | --- |
| `memories` 表 | `api/app/db.py` |
| 记忆存取：新增（同内容去重）、更新（旧的标为 superseded）、忘掉（标为 removed，可恢复）、用户编辑（原地改，来源标为「你改过」）、删除、撤销、按轮撤销、中文关键词搜索、上下文块（约 2000 字上限） | `api/app/agent/memory.py` |
| Agent 工具 `remember` / `update_memory` / `forget` / `recall`（不需要确认） | `api/app/agent/memory_tools.py`、`mcp_server.py`、`permissions.py` |
| 每轮上下文：记忆 + 其他对话；记忆变化发 `memory_change` 事件；撤销整轮也撤销记忆 | `api/app/agent/runtime.py`、`prompts.py` |
| 跨对话搜原话 | `api/app/agent/store.py` `search_messages` |
| 接口 `GET/POST /api/memories`、`PATCH/DELETE /api/memories/{id}`、`POST /api/memories/{id}/revert` | `api/app/routes/memories.py` |
| 面板：记忆视图、「记下了…撤销」 | `web/src/agent/MemoryView.tsx`、`AgentMessage.tsx`、`AgentPanel.tsx` |

## 验证

- 后端 105 个测试（新增 `test_memory.py`，以及运行时里「记住 → 另一个对话能看到并搜到 → 撤销整轮收回」的完整测试、接口测试）。
- 前端 60 个测试；浏览器里走过记忆视图的查看、编辑、切换栏目，以及对话里「记下了…撤销」。
- 未验证：真实模型是否按规则主动记 / 不乱记，需要在 Mac 上实跑。

## 留到第三阶段

- 从操作推断偏好（待确认区）、对话结束自动摘要、`last_used_at` 排序、记忆多了之后的按意思检索。
