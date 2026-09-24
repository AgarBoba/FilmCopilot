# Film Copilot

一个在本机运行的无限画布，用来生成图片和视频：
- 画布上放图片、视频、便签节点，用连线把参考图传给下游节点；
- 右侧的 Agent 能帮你拆分镜、写提示词、批量出图。

默认用 Replicate 上的 Seedream 5 Pro 出图、Seedance 2.0 Mini 出视频，也可以接入别家的模型。

## 让你的编码 Agent 帮你装（推荐）

如果你在用 Claude Code、Codex 这类编码 Agent，把下面这段话发给它就行，不用自己碰终端：

> 帮我装好 Film Copilot：把 https://github.com/AgarBoba/FilmCopilot 克隆到本地，然后按仓库里 AGENTS.md 的说明安装、检查并启动。

之后同样用一句话就能：
- 启动：「启动 Film Copilot」
- 排错：「Film Copilot 生成失败了，帮我看看」
- 更新：「更新 Film Copilot」
- 加模型：「帮 Film Copilot 加上 Replicate 上的 Flux Kontext Pro」「帮我接入 fal 的某某视频模型」

你需要准备：
- **Anthropic API Key**：画布里的 Agent 用。在 <https://console.anthropic.com> 获取。
- **Replicate API Token**：默认的生成模型用。在 <https://replicate.com/account/api-tokens> 获取。接了别家模型的话，换成那一家的 key。

密钥只填在项目里的 `.env` 文件中。它不会被提交到 git。

## 手动安装

需要 Python 3.11+（或者 [uv](https://docs.astral.sh/uv/)）和 Node.js 20.19+。

~~~bash
python3 scripts/setup.py      # 装依赖、生成 .env，最后给出检查结果
open -e .env                  # 填 ANTHROPIC_API_KEY 和 REPLICATE_API_TOKEN（macOS；其他系统用任意编辑器）
python3 scripts/doctor.py --online   # 确认密钥可用
./scripts/dev.sh              # 启动，然后打开 http://127.0.0.1:5173
~~~

- 更新：`git pull && python3 scripts/setup.py`。
- 加模型：见 [docs/ADDING_MODELS.md](docs/ADDING_MODELS.md)。

## 开发

~~~bash
cd api && ../.venv/bin/python -m pytest -q
cd web && pnpm test -- --run && pnpm run build
~~~

- 开发记录见 [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md)，界面规范见 [docs/DESIGN.md](docs/DESIGN.md)。
- 维护者个人可以用 Claude 订阅代替 API Key：运行 `./scripts/claude-login.sh`。这种方式仅限自己使用，订阅额度不能给别人的产品用。
