# Film Copilot 交接文档（给新开的编码 session）

> 写于 2026-10-10。读者是接手改进这个项目的编码 Agent（Claude Code / Codex 等），可能同时有好几个 session 在并行改。
> 先读完这一页，再按「先读什么」去看细节。这份文档过期了就顺手更新它。

## 1. 项目是什么

Film Copilot：本机运行的无限画布，用来生成图片和视频，画布里还有一个能动手改画布的 Agent。
- 后端：FastAPI + SQLite（`api/`），外加一个领生成任务的 Worker。
- 前端：React + React Flow（`web/`）。
- 画布 Agent：Claude Agent SDK，跑在后端进程里，通过进程内 MCP server 调画布工具。
- 生成模型：`models/*.json` 登记，provider 代码在 `api/app/providers/`（默认 Replicate 的 Seedream 5 Pro / Seedance 2.0 Mini）。
- 用户（Justin）是 AI 产品经理，不一定看代码。跟他说话用中文、简洁、讲结果。

## 2. 当前状态

| 项 | 值 |
| --- | --- |
| 仓库 | `/Users/justingu/Desktop/Agent Demo`，远端 `origin` = github.com/AgarBoba/FilmCopilot |
| 主干 | **`main`**（10/10 起；GitHub 上的 `main` 是唯一正式版本）。主工作目录 `/Users/justingu/Desktop/Agent Demo/.worktrees/infinite-media-canvas` 检出的就是 `main` |
| 旧分支 | `feature/infinite-media-canvas` 停在 `409c953`，不再使用 |
| 仓库根目录 | `Agent Demo/` 本身是一份没人用的旧检出（HEAD 已分离），别在那里开发或启动 |
| 测试 | 后端 pytest 177 通过；前端 vitest 91 通过，`tsc -b` 干净 |
| 最近做完 | 留言改成真正的评论（普通留言 / @Agent）、Agent 面板左右聊天版式和新输入栏、上下文圆环、对话摘要和 recall 改进、模型换成 Opus / Sonnet / Haiku 5.5 |

最近的进展和每次改动的原因都在 `DEVELOPMENT_LOG.md` 顶部，按日期倒序。

## 3. 先读什么

1. `AGENTS.md`：安装、启动、排错、接入模型、密钥铁律。`CLAUDE.md` 只是引用它。
2. `docs/DESIGN.md`：界面和交互规范。改任何界面之前先读对应小节，改完同步更新。
3. `DEVELOPMENT_LOG.md` 顶部几条：最近改了什么、哪些还没验证。
4. 方案文档在 `docs/superpowers/specs/`：
   - 画布总体：`2026-09-22-infinite-media-canvas-design.md`
   - Agent：`2026-09-23-film-copilot-agent-design.md`
   - 留言：`2026-10-08-canvas-comments-design.md`
   - 留言后来又改成了「普通留言 / @Agent」两种，以 DESIGN.md 和开发日志为准。
5. Justin 手上有两份讲 Agent 的网页文档（claude.ai artifact）：架构总览，和上下文是怎么拼起来的。想要就找他要链接。它们是 10/09 的快照，和代码对不上时以代码为准。

## 4. 跑起来、跑测试

```bash
python3 scripts/setup.py          # 首次、或拉了新代码之后
./scripts/dev.sh                  # API :8000、Web :5173、Worker，一起起
python3 scripts/doctor.py         # 只报告密钥填没填，不显示值

cd api && ../.venv/bin/python -m pytest -q
cd web && pnpm test -- --run && pnpm exec tsc -b
```

- 端口被占：多半是上次的 dev.sh 没关。`lsof -ti tcp:8000,5173 | xargs kill -9; pkill -f api.app.worker` 后再起。
- 改了 `api/` 的 Python 要重启 dev.sh，因为 Worker 不会自动重载。
- 全量 pytest 结束时 stderr 会有几条 `BaseSubprocessTransport.__del__` / `Event loop is closed` 噪音，不影响结果（看 `N passed` 那行）。

## 5. 代码地图

### 后端 `api/app/`

| 文件 | 管什么 |
| --- | --- |
| `commands.py` | 画布的所有写操作都走 `CanvasCommandService`：revision、幂等、Agent 改动记录（用来撤销）。前端和 Agent 共用。 |
| `db.py` | 建表和迁移（如 `_migrate_comments`）。加表或加列都在这里，旧库要能自动升级。 |
| `repositories.py` / `versions.py` / `upstream.py` | 读画布；节点的版本历史；「上游有更新」。 |
| `worker.py` / `providers/` / `models_registry.py` | 生成任务和模型登记。 |
| `credits.py` | 模拟积分：流水表 `credit_ledger`、生成价格（模型文件的 `credits`）、扣费和退回。生成在 `commands._start_generation` 扣，失败在 worker 退，删节点在 `repositories.delete_node` 退；Agent 每轮在 `runtime._charge_turn` 扣。 |
| `routes/` | HTTP 接口：`agent.py`、`comments.py`、`canvases.py` 等。 |

### 画布 Agent `api/app/agent/`

| 文件 | 管什么 |
| --- | --- |
| `runtime.py` | `AgentService`：一轮对话的完整流程，事件流（`_emit`），停止 / 撤销，对话摘要的调度，`run_finished` 里带 `contextTokens` / `contextWindow`。 |
| `prompts.py` | system prompt 和每轮的前缀（画布概况、其他对话摘要等）。 |
| `mcp_server.py` + `canvas_tools.py` + `memory_tools.py` | 给 Agent 的 18 个画布 / 记忆工具，工具描述也在这里。 |
| `permissions.py` / `conflicts.py` / `undo.py` | 审核方式（每步确认 / 只确认生成和删除 / 全自动），和用户同时改同一节点时的冲突，撤销一轮。 |
| `memory.py` / `store.py` / `summary.py` | 两层记忆（项目设定、用户偏好）和 recall 搜索；会话和消息存储；用 Haiku 5.5 写对话摘要。 |
| `comments.py` / `notes.py` | 留言：普通留言 vs 交给 Agent（`agent_status`），回复表 `comment_replies`，排队 pump；`notes.py` 让 get_canvas / get_node 带上用户备注。 |
| `config.py` | 可选模型列表 `MODELS`、旧模型 ID 自动换新 `current_model`、API Key / 订阅两种登录。 |

### 前端 `web/src/`

| 目录 / 文件 | 管什么 |
| --- | --- |
| `canvas/CanvasShell.tsx` | 画布主体，什么都往这里接。改动容易冲突，见第 7 节。 |
| `nodes/` | 图片 / 视频 / 文本节点、便签、Prompt 输入区、视频播放、版本历史。 |
| `agent/AgentPanel.tsx` | 面板：左右聊天（`turns.ts` 把消息分段）、输入栏（模型胶囊、技能 ✦、审核盾牌、上下文圆环）。 |
| `agent/AgentMessage.tsx`、`Markdown.tsx`、`SessionList.tsx`、`MemoryView.tsx` | 单条消息、Markdown 和「存到画布」、对话列表、记忆页。 |
| `credits/` | 左上角积分胶囊和弹层（`CreditsButton`）、余额和价格公式（`creditStore.ts`，和后端同一个公式）。 |
| `comments/` | 图钉和新留言（`CommentLayer`）、讨论小窗（`CommentPopover`）、回复框（`CommentComposer`，勾选框和 @Agent 是同一件事）、时间线合并（`thread.ts`）。 |
| `styles.css` | 全部样式，一个文件。颜色用 DESIGN.md 里的变量。 |

## 6. 铁律（别破）

- **密钥**：只在各工作目录的 `.env` 里（gitignored，权限 600）。
  - 不要读、不要打印、不要 `cat .env`，只能检查有没有设置。
  - 密钥不能出现在日志、数据库和 API 返回里。
  - 要填密钥，就打开 `.env` 让 Justin 自己粘贴。
- **同事**只用 Anthropic API Key。用订阅额度登录（`AGENT_AUTH=subscription`）只给 Justin 自己用，订阅不能用来给别人的产品供能。
- **画布 Agent** 不能有读写文件或跑命令的工具，只能用画布 / 记忆工具、技能、联网搜索、任务清单。
- **`data/`** 是 Justin 的画布、素材和对话，不要删，不要重置。
- **`git push`**：Justin 没说就不推。推的时候给他命令让他自己跑：
  `cd "<工作目录>" && git push origin <分支>`
- 界面文案用中文、全角标点；没有文字的按钮必须有悬停气泡（`data-tooltip`）。
- 每次改完都要：
  - 跑后端 + 前端测试。
  - 在 `DEVELOPMENT_LOG.md` 顶部记一条：现象、根因、改动、验证、未验证项。
  - 改了界面就同步 `docs/DESIGN.md`。
- 提交信息末尾带上当前 session 给的署名行（Co-Authored-By 等）。

## 7. 多个 session 并行：怎么不打架

**每个 session 一个 git worktree + 一个分支**，从最新的 `main` 切出来，不要几个 session 挤在同一个工作目录里。开工前先 `git pull origin main`。

```bash
cd "/Users/justingu/Desktop/Agent Demo"
git worktree add .worktrees/<短名> -b feat/<短名> main
cd .worktrees/<短名>
cp ../infinite-media-canvas/.env .env && chmod 600 .env   # 直接复制，不打开、不读内容
python3 scripts/setup.py                                  # 各自的 .venv 和 node_modules
```

然后只改新 `.env` 里的这几行，密钥那几行不要碰：

| session | `API_PORT` | `WEB_PORT` |
| --- | --- | --- |
| 第 2 个 | 8100 | 5273 |
| 第 3 个 | 8200 | 5373 |

- dev.sh 启动时会读 `.env`，并且 `.env` 里的值会盖掉命令行上设的环境变量，所以端口只能写在 `.env` 里。
- `CANVAS_DATA_DIR=./data` 是相对当前工作目录的，所以每个工作目录天然有一份独立的数据，互不干扰。
- 想用 Justin 现有的画布数据测试，就把主工作目录的 `data/` 复制一份过去。**不要两个 dev.sh 同时用同一个 `data/canvas.sqlite3`**：两个 Worker 会抢同一批生成任务，也会互相锁库。

**分工**：按区域分，尽量别同时改同一批文件。容易冲突的热点：

| 文件 | 原因 | 建议 |
| --- | --- | --- |
| `web/src/styles.css` | 所有样式都在这一个文件 | 新样式加在自己功能那一节的末尾 |
| `web/src/canvas/CanvasShell.tsx` | 什么都往这里接 | 逻辑写进自己的模块，这里只接一两行 |
| `web/src/agent/AgentPanel.tsx` | 面板改动都落在这 | 能拆出子组件就拆 |
| `api/app/agent/runtime.py` | 每轮对话的主流程 | 改动尽量小 |
| `api/app/agent/prompts.py` | 改 prompt 会影响所有功能的 Agent 行为 | 同一时间只让一个 session 改 |
| `api/app/db.py` | 迁移 | 两个 session 同时加表很容易冲突，先说好谁加 |
| `DEVELOPMENT_LOG.md`、`docs/DESIGN.md` | 大家都会往里写 | 冲突好解决，合并时两条都保留，按日期排 |

**合并回去**：做完一块，在主工作目录（检出的是 `main`）里合并，跑一遍全量测试再交给 Justin：

```bash
cd "/Users/justingu/Desktop/Agent Demo/.worktrees/infinite-media-canvas"
git pull origin main          # 先拿到别人已经合进去的
git merge feat/<短名>
```

- 推到 GitHub 由 Justin 来：`git push origin main`。
- 还在做的分支，定期把新的 `main` 合进来（`git merge main`），越早冲突越小。
- 用 Codex 云端任务的：它从 GitHub 上的 `main` 开始做、以 PR 交回；派活前先确保本地改动已推上去，PR 合并后在本地 `git pull`。
- 不用的 worktree 用 `git worktree remove` 清掉。

## 8. 云端 session 连 Justin 电脑时的坑（本机 session 可跳过）

- 电脑上的 git 要带这几个环境变量才能用：
  `GIT_DIR="$HOME/mnt/Agent Demo/.git/worktrees/<worktree名>" GIT_WORK_TREE="$PWD" GIT_COMMON_DIR="$HOME/mnt/Agent Demo/.git"`
  提交时用 `-c user.name/-c user.email`，值照抄上一个提交的作者。
- 那边默认不允许删文件，所以 git 会留下 `HEAD.lock`、`objects/maintenance.lock`。用 `mv` 挪到 `.git/stale-*`，不要删。
- 那台 VM 里看 `git worktree list` 会显示 `prunable`，因为路径不一样，是正常的。**千万别在那里跑 `git worktree prune`。**
- 那台 VM 没有 pytest，测试在云端容器里跑。改好的文件每次放进一个**新的** `/mnt/user-data/outputs/<目录>` 再写回电脑；复用旧目录写回过会悄悄失败。

## 9. 还没做 / 没验证 / 想法池

**没验证（容器里只有假密钥）**
- 真实模型下的：Agent 每轮实际扣多少积分、对话摘要的效果、上下文圆环的数字、Sonnet / Haiku 5.5 的实际调用、Agent 处理留言的完整流程。

**已知的小尾巴**
- 新留言写到一半，点外面不会关（故意的，怕丢字）。要不要改，问 Justin。
- 对话列表还没显示对话摘要。
- recall 只做了关键词匹配，没有语义（向量）搜索。
- 审核方式的盾牌图标（实心 / 半实心 / 空心）是我定的，Justin 还没明确确认。

**积分（模拟）的后续**
- 现在没有账号，全机共用一个钱包，充值是手动加。生图 / 生视频排队扣费已在短事务里串行检查并处理 SQLite 锁冲突；Agent 对话和充值的并发记账保护仍待完善。上线还要做：用户账号、按用户记账、真实支付、后台写摘要的模型调用也计费。

**已定的方向**
- 面板里的 `@` 留给以后的「角色库」（@某个角色）。不做 @节点，关注节点靠在画布上选中。

**数据模型备忘**
- 留言：
  - `status` 是 open / resolved。
  - `agent_status` 为 NULL 表示普通留言，否则是 queued / running / waiting / done / failed。
  - 回复存在 `comment_replies` 表，带 `to_agent` 和 `seen_by_agent` 两个标记。
  - 交给 Agent 时，把它还没看过的内容按时间顺序合成一条消息给它。
- 事件流：前端靠 SSE 收事件，类型有 `user_message`、`assistant_text`、`tool_step`、`confirm_request`、`run_finished` 等。新加一种事件，要同时改 `agentApi.ts` 的 kinds 列表。
