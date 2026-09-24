# AGENTS.md：给编码 Agent 的说明

读这份文件的是 Claude Code、Codex 这类编码 Agent，你在帮用户安装、运行、排错 Film Copilot，或者帮他接入新的生成模型。
用户不一定是开发者，也可能从不打开终端：命令都由你来跑，跟用户说话用他的语言，讲结果，别贴命令日志。

Film Copilot 是一个在本机运行的无限画布，用来生成图片和视频。它由三部分组成：FastAPI 后端、一个 Worker、React 前端。
- 画布里另有一个 Agent，它基于 Claude Agent SDK，用 Anthropic API Key。它和你没有关系，你不需要操作它。
- 图片和视频由 `models/*.json` 里登记的模型生成。默认模型是 Replicate 上的 Seedream 5 Pro（图片）和 Seedance 2.0 Mini（视频）。

## 铁律：密钥

1. **不要让用户把密钥发到对话里。** 要填密钥时，替用户打开 `.env`，告诉他填在哪一行，让他自己粘贴并保存。
   - macOS：`open -e .env`
   - Windows：`notepad .env`
   - Linux：`xdg-open .env`
2. **不要读出或打印密钥。**
   - 不要 `cat .env`，不要 `env` 或 `printenv`，不要 `echo $XXX_KEY`，不要对 dev.sh 开 `set -x`。
   - 想知道密钥填没填、能不能用，就跑 `scripts/doctor.py`。它只报告“已设置/未设置/可用”。
3. **不要提交 `.env`。** `.gitignore` 已经排除了它。不要改这条规则，也不要 `git add -f`。
4. 用户如果已经把密钥贴进了对话：不要在回复里复述它。用一条不回显的命令把它写进 `.env` 对应的行，比如用 Python 替换 `KEY=` 那一行。然后提醒用户：密钥进过聊天记录，在意的话可以去服务商那里重新生成一个。

需要的密钥：
- `ANTHROPIC_API_KEY`：画布 Agent 用。在 <https://console.anthropic.com> 的 API Keys 页面获取。
- `REPLICATE_API_TOKEN`：默认的生成模型用。在 <https://replicate.com/account/api-tokens> 获取。
- 接入了别家模型的话，还要加上对应的 key，见 `.env.example`。

## 安装（首次安装和每次 `git pull` 之后）

```bash
python3 scripts/setup.py
```

这个脚本不问问题，重复运行也安全。它会做这些事：
- 找到 Python 3.11+（有 uv 的话缺了会自动下载）。
- 创建 `.venv`，装后端依赖。
- 装前端依赖（优先 pnpm）。
- 从 `.env.example` 生成 `.env`，权限设为 600。
- 以后 `.env.example` 新增了设置，会补进已有的 `.env`，不动已有的值。
- 最后跑一遍 doctor。

它要联网下载依赖。如果你的沙箱默认禁止联网（例如 Codex），请用户允许这一步联网。

它失败时，按输出里“怎么办”那一行处理。常见情况：
- 没有 Python 3.11+：装 uv 或 Python 3.12。
- Node 版本低于 20.19：`brew install node` 或 `brew upgrade node`。

装完以后：让用户填密钥（见上面的铁律），然后跑 `python3 scripts/doctor.py --online` 确认密钥可用，再启动。dev.sh 只在启动时读 `.env`，已经在运行的话，改完 `.env` 要重启它。

## 启动和停止

```bash
./scripts/dev.sh
```

- 它会一直运行，所以放到后台跑（用你的后台/长任务方式）。
- 看到 `dev.sh: API http://127.0.0.1:8000  Web http://127.0.0.1:5173` 就说明起来了，替用户打开 <http://127.0.0.1:5173>。macOS 上可以用 `open http://127.0.0.1:5173`。
- 停止：结束你启动的那个进程。它会顺带关掉 API、Worker 和 Web。
- 提示“端口已被占用”：多半是上次启动的还没关。按提示里的 pid 结束掉，再启动。
- 需要 bash。Windows 上请在 WSL 或 Git Bash 里运行。
- 改了 `api/` 下的 Python 代码（包括新写的 provider）之后，要重启 dev.sh，因为 Worker 不会自动重载。
- 只改 `models/*.json` 不用重启。画布在窗口重新获得焦点时会刷新模型列表。

## 检查和排错

```bash
python3 scripts/doctor.py            # 本地检查，不联网
python3 scripts/doctor.py --online   # 再用免费接口验证 Anthropic 和 Replicate 的密钥
python3 scripts/doctor.py --json     # 机器可读，ready=true 表示可以用了
```

- 每个 ✗ 下面都有 → 修复方法。`!` 是可选项。
- 常见问题：
  - `.env 第 N 行不是 KEY=VALUE`：粘贴的密钥被折成了两行。让用户打开 `.env`，把那一段接回 `KEY=` 那行末尾。
  - 节点上显示“还缺 XXX_KEY”：`.env` 里没填这个 key。填好后重启 dev.sh。
  - 节点上显示“还没有 X 的对接代码”：有模型文件写了 `"provider": "X"`，但 `api/app/providers/X.py` 不存在。按下面“接入新模型”处理。
  - 生成失败：错误信息显示在节点上。可以用 `python3 scripts/check_model.py <模型id>` 看实际发给 provider 的参数。
  - 画布 Agent 报认证失败：检查 `ANTHROPIC_API_KEY`（`doctor.py --online`）。

## 接入新模型

两层概念：

- **模型文件** `models/<id>.json`：一个模型一个文件。里面写它是图片还是视频、用哪个 provider、提示词和参考图对应 provider 的哪个字段、节点上显示哪些参数。这是纯数据，不用改代码。
- **provider 对接代码** `api/app/providers/<name>.py`：把请求发给某一家 API。同一家的所有模型共用一份。目前有 `replicate`。

完整格式和写法见 [docs/ADDING_MODELS.md](docs/ADDING_MODELS.md)。常见流程如下。

### A. Replicate 上的模型（最常见）

用户说“加一个 Flux Kontext”这类需求时：
1. 在 replicate.com 上确认模型的 `owner/name`，可以用网页搜索。
2. `python3 scripts/add_model.py owner/name`：读取模型的输入 schema，生成 `models/<id>.json` 草稿，并列出需要检查的地方。
   - 视频模型加 `--kind video`。
   - 想设为默认模型加 `--default`。
3. 按提示审一遍草稿：
   - 把 `description` 改成一两句中文，写清它擅长什么。画布 Agent 靠这段描述选模型。
   - label 改得好读一些。
   - 删掉没必要放在节点上的参数。
   - 核对参考图的上限。
4. `python3 scripts/check_model.py <id>`：免费，校验文件并展示会发给 Replicate 的参数。
5. **先问用户同意（会花钱）**，再跑 `python3 scripts/check_model.py <id> --run`，真实生成一次。结果存在 `data/model-checks/`，可以打开给用户看。
6. 告诉用户：回到画布，在节点的「Model」菜单里就能选到新模型。

### B. 别家的模型（fal、OpenAI、Google、Runway、自建服务……）

1. 看 `api/app/providers/` 里有没有这一家。已经有的话，只需要按 A 的第 3 到 6 步手写模型文件。
2. 没有的话，新建对接代码：
   - `cp api/app/providers/_template.py api/app/providers/<name>.py`
   - 按那家 API 的文档填好文件里的 TODO：提交任务、查询状态、下载结果、`ENV_KEYS`。
   - 优先用已经装好的 `httpx`。确实需要对方的 SDK 时，加到 `api/pyproject.toml` 的 dependencies，再跑 `python3 scripts/setup.py`。
3. 在 `.env.example` 里加上新 key 的一行，附上获取地址的注释。然后跑 `python3 scripts/setup.py`，它会把这一行补进用户的 `.env`，再让用户自己填值。
4. 写模型文件，`"provider": "<name>"`。
5. 重启 dev.sh。跑 `check_model.py`，得到用户同意后再加 `--run`。
6. 建议在 `api/tests/` 里加一个测试：用假的 HTTP 响应覆盖状态映射。可以参考 `api/tests/test_worker.py`。

### 其他

- **换默认模型**：把 `"default": true` 移到另一个同 kind 的模型文件上。每个 kind 只能有一个默认。
- **下线模型**：删掉它的 json。已经选了它的节点会自动回落到默认模型。

## 不要动

- `data/`：用户的画布、素材和对话记录。不要删，不要重置。
- `.env` 里的值：只由用户自己改。唯一的例外见铁律第 4 条。
- 没有用户明确要求时，不要 `git push`，不要改 git 远端。同事一般只需要拉取更新（`git pull`）。
- `scripts/claude-login.sh` 和 `AGENT_AUTH=subscription` 是维护者个人用 Claude 订阅的方式。同事一律用 `ANTHROPIC_API_KEY`，因为订阅额度不能给别人的产品用。

## 目录速览

```
models/                 生成模型登记（一模型一 JSON）
api/app/providers/      provider 对接代码（replicate.py、_template.py）
api/app/models_registry.py  模型文件的读取与校验
api/app/worker.py       领取生成任务，调 provider，下载结果
api/app/agent/          画布里的 Agent（Claude Agent SDK）
web/src/                React 前端（React Flow 画布）
scripts/                setup / doctor / add_model / check_model / dev.sh
docs/ADDING_MODELS.md   模型文件和 provider 的完整说明
```

## 改了代码以后

```bash
cd api && ../.venv/bin/python -m pytest -q
cd web && pnpm test -- --run && pnpm exec tsc -b
```

然后在 `DEVELOPMENT_LOG.md` 顶部按“后续追加约定”记一条。
