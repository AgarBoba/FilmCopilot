# 无限媒体生成画布 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个本地运行的单用户无限媒体生成画布，支持图片、视频、便签、参考连线、真实 Replicate 生成任务、持久化和未来 Agent 命令接入。

**Architecture:** 使用 React/Vite/TypeScript 和 React Flow 实现画布 UI，使用 FastAPI/SQLite 实现本地领域服务、命令校验、文件和任务持久化。独立 Python Worker 从 SQLite 领取生成任务，通过 Replicate Provider Adapter 调用 Seedream 5 Pro 与 Seedance 2.0 Mini，并通过 SSE 把事件推送回前端。

**Tech Stack:** React, Vite, TypeScript, @xyflow/react, Zustand, Vitest, FastAPI, Pydantic, Python sqlite3, pytest, Replicate Python client, Pillow, ffprobe.

**Spec:** docs/superpowers/specs/2026-09-22-infinite-media-canvas-design.md

## Global Constraints

- 第一版是本地单用户应用，不加入账号、多人协作、评论或权限系统。
- 图片 Provider 固定为 `bytedance/seedream-5-pro`，视频 Provider 固定为 `bytedance/seedance-2.0-mini`。
- `REPLICATE_API_TOKEN` 只从本地环境变量读取，不写入数据库或前端 bundle。
- 画布关系方向固定为“参考素材 → 使用参考素材的目标节点”。
- 图片节点只接受图片上游；视频节点接受图片或视频上游；便签不参与参考素材连线。
- 自连接、重复边和循环关系必须在后端领域层拒绝。
- Prompt 文本和模型参数必须一起保存在节点内容和 GenerationJob 输入快照中。
- 图片参数必须位于图片节点的 Prompt 输入区：尺寸、宽高比、输出格式。
- 视频参数必须位于视频节点的 Prompt 输入区：时长、分辨率、宽高比、是否生成音频。
- 前端和未来 Agent 必须调用同一套画布命令服务，不能直接修改 SQLite 或 React Flow 内部状态作为持久化源。
- 生成结果必须下载到本地媒体目录，并保存实际媒体元数据和 checksum。
- Provider 参考图数量不限制用户建立画布连线；Provider Adapter 负责稳定映射、警告和结果保存。
- 不引入 Redis、Celery 或其他外部队列；生成任务使用 SQLite 持久化加独立本地 Worker。
- 不实现完整的模型参数面板、模型自动路由、节点分类颜色或自定义 RGB/HEX 颜色。

## Review Focus

- **旧 revision 命令：** 合法命令不能覆盖用户的新画布状态；由 Task 3 的 `test_revision_conflict_rejects_stale_command` 固定。
- **Agent 重试：** 相同 idempotency key 不能重复创建节点、连线或任务；由 Task 3 的 `test_idempotent_command_returns_original_result` 固定。
- **生成期间素材变化：** Worker 必须使用提交时的 Prompt、参数和素材 checksum，不得读取新的节点状态；由 Task 5 的 `test_worker_uses_generation_input_snapshot` 固定。
- **Provider 参考图超限：** 画布关系不被截断删除，Adapter 只稳定选择 Provider 支持的输入并写 warning；由 Task 5 的 `test_seedream_maps_first_ten_references_with_warning` 固定。
- **悬停视频播放：** 鼠标离开节点必须暂停并清理媒体播放状态；由 Task 7 的 `VideoNode.test.tsx` 悬停/离开测试固定。

---

## 文件结构

初始仓库使用以下边界：

~~~text
README.md
.env.example
.gitignore
package.json
api/
  pyproject.toml
  app/
    __init__.py
    config.py
    db.py
    domain.py
    schemas.py
    graph_rules.py
    repositories.py
    commands.py
    events.py
    media_metadata.py
    assets.py
    worker.py
    main.py
    providers/
      __init__.py
      base.py
      replicate.py
    routes/
      __init__.py
      canvases.py
      assets.py
      events.py
  tests/
    conftest.py
    test_health.py
    test_graph_rules.py
    test_commands.py
    test_assets.py
    test_provider_mapping.py
    test_worker.py
web/
  package.json
  tsconfig.json
  vite.config.ts
  index.html
  src/
    main.tsx
    App.tsx
    api/client.ts
    domain/types.ts
    domain/connectionRules.ts
    state/canvasStore.ts
    canvas/CanvasShell.tsx
    canvas/CanvasToolbar.tsx
    canvas/ConnectionChooser.tsx
    edges/ReferenceEdge.tsx
    nodes/ImageNode.tsx
    nodes/VideoNode.tsx
    nodes/NoteNode.tsx
    nodes/PromptComposer.tsx
    nodes/generationParameters.ts
    styles.css
    test/setup.ts
    test/canvasStore.test.ts
    test/connectionRules.test.ts
    test/PromptComposer.test.tsx
    test/VideoNode.test.tsx
scripts/
  dev.sh
data/
  .gitkeep
~~~

文件职责：

- `api/app/domain.py`：后端领域数据类和枚举，不包含 HTTP。
- `api/app/graph_rules.py`：连接类型校验、重复边检查和环路检测。
- `api/app/commands.py`：事务化命令执行、revision、幂等和任务创建。
- `api/app/repositories.py`：SQLite 表读写，不负责业务规则。
- `api/app/providers/base.py`：Provider 输入输出协议。
- `api/app/providers/replicate.py`：两个 Replicate 模型的具体字段映射。
- `api/app/worker.py`：领取任务、调用 Provider、下载结果、写回 Asset。
- `web/src/domain/types.ts`：前端 API 快照和命令类型。
- `web/src/state/canvasStore.ts`：快照、视口、选择状态和 API 同步。
- `web/src/nodes/*.tsx`：三个自定义节点的视觉与交互。
- `web/src/nodes/PromptComposer.tsx`：Prompt 文本和模型参数选择。
- `web/src/canvas/CanvasShell.tsx`：React Flow 装配、事件转命令和 SSE 刷新。

## Task 1: 本地全栈骨架和开发命令

**Files:**
- Create: `README.md`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `package.json`
- Create: `scripts/dev.sh`
- Create: `api/pyproject.toml`
- Create: `api/app/__init__.py`
- Create: `api/app/config.py`
- Create: `api/app/main.py`
- Create: `api/tests/conftest.py`
- Create: `api/tests/test_health.py`
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/vite.config.ts`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/styles.css`
- Create: `data/.gitkeep`

**Interfaces:**

- Produces `api.app.main.create_app() -> FastAPI`.
- Produces `GET /api/health -> { "ok": true }`.
- Produces `web` scripts `npm run dev`, `npm run build`, `npm run test`.
- Produces `scripts/dev.sh` that starts FastAPI and Vite using the repository's local paths.

- [ ] **Step 1: Write the failing backend health test**

在 `api/tests/test_health.py` 写入：

~~~python
from fastapi.testclient import TestClient
from api.app.main import create_app

def test_health_returns_ok():
    response = TestClient(create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
~~~

- [ ] **Step 2: Run the backend test to verify it fails**

Run: `cd api && python -m pytest tests/test_health.py -q`

Expected: FAIL because `api.app.main.create_app` and `/api/health` do not exist.

- [ ] **Step 3: Create the Python project and minimal FastAPI app**

在 `api/pyproject.toml` 固定 FastAPI、Pydantic、uvicorn、pytest、httpx、Pillow 和 Replicate 依赖；在 `api/app/config.py` 提供 `Settings(data_dir: Path, database_path: Path, replicate_api_token: str | None)`；在 `api/app/main.py` 实现：

~~~python
from fastapi import FastAPI

def create_app() -> FastAPI:
    app = FastAPI(title="Infinite Media Canvas")

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    return app
~~~

- [ ] **Step 4: Add the frontend shell and scripts**

在 `web/package.json` 添加 React、React DOM、`@xyflow/react`、Zustand、Vitest、Testing Library 和 Vite；在 `web/src/App.tsx` 渲染一个带应用标题的空状态；在 `web/src/main.tsx` 挂载 React；在 `web/src/styles.css` 定义 `--canvas-bg`、`--node-bg`、`--text-primary` 和 `--accent` 四个主题变量。

- [ ] **Step 5: Add local configuration and the start script**

在 `.env.example` 写入：

~~~text
REPLICATE_API_TOKEN=
CANVAS_DATA_DIR=./data
CANVAS_DATABASE_PATH=./data/canvas.sqlite3
API_PORT=8000
WEB_PORT=5173
~~~

`scripts/dev.sh` 必须启动 API 和 Web 两个进程，并在退出时结束子进程。README 写明 Python 虚拟环境、`pip install -e api`、`npm install --prefix web` 和 `./scripts/dev.sh` 的顺序。

- [ ] **Step 6: Run the scaffold checks**

Run: `cd api && python -m pytest -q`

Expected: PASS.

Run: `npm install --prefix web && npm run build --prefix web`

Expected: PASS and generate `web/dist`.

- [ ] **Step 7: Commit the scaffold**

~~~bash
git add README.md .env.example .gitignore package.json scripts api web data
git commit -m "feat: scaffold local canvas app"
~~~

## Task 2: 领域模型和参考关系校验

**Files:**
- Create: `api/app/domain.py`
- Create: `api/app/graph_rules.py`
- Create: `api/tests/test_graph_rules.py`
- Create: `web/src/domain/types.ts`
- Create: `web/src/domain/connectionRules.ts`
- Create: `web/src/test/connectionRules.test.ts`

**Interfaces:**

- Produces `NodeType = Literal["image", "video", "note"]`.
- Produces `EdgeRecord(source_node_id: str, target_node_id: str)`.
- Produces `validate_connection(source_type, target_type, source_id, target_id, edges) -> None`; invalid input raises `DomainError(code, message)`.
- Produces `would_create_cycle(edges, source_id, target_id) -> bool`.
- Produces frontend `canConnect(source: NodeType, target: NodeType): boolean` and `wouldCreateCycle(edges, sourceId, targetId): boolean`.

- [ ] **Step 1: Write the failing graph rule tests**

在 `api/tests/test_graph_rules.py` 写入：

~~~python
import pytest
from api.app.domain import DomainError, EdgeRecord
from api.app.graph_rules import validate_connection, would_create_cycle

def test_image_to_video_is_valid():
    validate_connection("image", "video", "image-1", "video-1", [])

def test_video_to_image_is_rejected():
    with pytest.raises(DomainError, match="INVALID_CONNECTION"):
        validate_connection("video", "image", "video-1", "image-1", [])

def test_self_link_and_duplicate_are_rejected():
    with pytest.raises(DomainError, match="SELF_LINK"):
        validate_connection("image", "image", "image-1", "image-1", [])
    edges = [EdgeRecord("image-1", "image-2")]
    with pytest.raises(DomainError, match="DUPLICATE_EDGE"):
        validate_connection("image", "image", "image-1", "image-2", edges)

def test_cycle_detection_follows_directed_reference_edges():
    edges = [EdgeRecord("image-1", "video-1"), EdgeRecord("video-1", "video-2")]
    assert would_create_cycle(edges, "video-2", "image-1") is True
~~~

- [ ] **Step 2: Run the graph tests to verify they fail**

Run: `cd api && python -m pytest tests/test_graph_rules.py -q`

Expected: FAIL because the domain types and graph functions are not defined.

- [ ] **Step 3: Implement backend graph rules**

在 `api/app/domain.py` 定义 `NodeType`、`EdgeRecord` 和带 `code` 的 `DomainError`。在 `api/app/graph_rules.py` 使用邻接表深度优先遍历实现环路检测；`validate_connection` 按以下顺序检查节点 ID、self-link、duplicate、node type pair 和 cycle。

- [ ] **Step 4: Add and test the frontend rule mirror**

在 `web/src/domain/types.ts` 定义 `CanvasSnapshot`、`CanvasNode`、`CanvasEdge`、`GenerationParameters` 和 `CommandEnvelope`。在 `web/src/domain/connectionRules.ts` 实现与后端相同的纯函数，前端测试覆盖 image→image、image→video、video→video、video→image 和 note 连接。

- [ ] **Step 5: Run both rule suites**

Run: `cd api && python -m pytest tests/test_graph_rules.py -q`

Expected: PASS.

Run: `npm run test --prefix web -- --run src/test/connectionRules.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit the domain rules**

~~~bash
git add api/app/domain.py api/app/graph_rules.py api/tests/test_graph_rules.py web/src/domain web/src/test/connectionRules.test.ts
git commit -m "feat: add canvas reference graph rules"
~~~

## Task 3: SQLite 持久化、命令服务、revision 和 SSE 事件

**Files:**
- Create: `api/app/db.py`
- Create: `api/app/schemas.py`
- Create: `api/app/repositories.py`
- Create: `api/app/commands.py`
- Create: `api/app/events.py`
- Create: `api/app/routes/canvases.py`
- Create: `api/app/routes/events.py`
- Modify: `api/app/main.py`
- Modify: `api/tests/conftest.py`
- Create: `api/tests/test_commands.py`

**Interfaces:**

- Produces `Database(path: Path)` with `init_schema()` and `transaction()`.
- Produces `CanvasRepository.create_canvas(name) -> CanvasSnapshot`.
- Produces `CanvasRepository.get_snapshot(canvas_id) -> CanvasSnapshot`.
- Produces `CanvasCommandService.execute(canvas_id, envelope: CommandEnvelope) -> CommandResult`.
- Produces `EventStore.append(canvas_id, revision, event_type, payload) -> CanvasEvent`.
- Produces `EventStore.after_revision(canvas_id, revision) -> list[CanvasEvent]`.
- Exposes `POST /api/canvases`, `GET /api/canvases/{canvas_id}/snapshot`, `POST /api/canvases/{canvas_id}/commands`, and `GET /api/canvases/{canvas_id}/events?afterRevision=n`.

- [ ] **Step 1: Write failing command service tests**

在 `api/tests/test_commands.py` 写入四个场景：

~~~python
def test_create_node_increments_revision(client):
    canvas_id = create_canvas(client)
    result = client.post(f"/api/canvases/{canvas_id}/commands", json={
        "command": "create_node",
        "baseRevision": 0,
        "idempotencyKey": "create-image-1",
        "payload": {"nodeType": "image", "x": 100, "y": 120}
    })
    assert result.status_code == 200
    assert result.json()["revision"] == 1

def test_revision_conflict_rejects_stale_command(client):
    canvas_id = create_canvas(client)
    create_node(client, canvas_id, "image", "create-image-1")
    response = client.post(f"/api/canvases/{canvas_id}/commands", json={
        "command": "create_node",
        "baseRevision": 0,
        "idempotencyKey": "create-video-1",
        "payload": {"nodeType": "video", "x": 0, "y": 0}
    })
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REVISION_CONFLICT"

def test_idempotent_command_returns_original_result(client):
    canvas_id = create_canvas(client)
    command = {
        "command": "create_node",
        "baseRevision": 0,
        "idempotencyKey": "same-command",
        "payload": {"nodeType": "image", "x": 0, "y": 0}
    }
    first = client.post(f"/api/canvases/{canvas_id}/commands", json=command)
    second = client.post(f"/api/canvases/{canvas_id}/commands", json=command)
    assert first.json() == second.json()
    assert client.get(f"/api/canvases/{canvas_id}/snapshot").json()["revision"] == 1

def test_connect_command_rejects_cycle(client):
    canvas_id = create_canvas(client)
    image_id = create_node(client, canvas_id, "image", "image")
    video_id = create_node(client, canvas_id, "video", "video")
    connect(client, canvas_id, image_id, video_id, "edge-1", 2)
    response = connect(client, canvas_id, video_id, image_id, "edge-2", 3)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CONNECTION"
~~~

- [ ] **Step 2: Run the command tests to verify they fail**

Run: `cd api && python -m pytest tests/test_commands.py -q`

Expected: FAIL because the database schema and command routes do not exist.

- [ ] **Step 3: Implement the SQLite schema and repositories**

`Database.init_schema()` must create `canvases`, `canvas_nodes`, `canvas_edges`, `assets`, `generation_jobs`, `canvas_events` and `command_log`. Use foreign keys, a unique constraint on `canvas_edges(canvas_id, source_node_id, target_node_id)`, and a unique constraint on `command_log(canvas_id, idempotency_key)`.

`CanvasRepository.get_snapshot` must return canvas metadata, nodes, edges, asset metadata and unfinished jobs in one serializable Pydantic object. Every command transaction increments `canvases.revision` once, appends events with that revision, and inserts the command result into `command_log`.

- [ ] **Step 4: Implement command envelopes and the command service**

在 `api/app/schemas.py` 定义 `CommandEnvelope(command: str, baseRevision: int, idempotencyKey: str, payload: dict)`、`CommandResult` 和 `CanvasSnapshot`。在 `api/app/commands.py` 实现：

~~~python
class CanvasCommandService:
    def execute(self, canvas_id: str, envelope: CommandEnvelope) -> CommandResult:
        cached = self.repository.find_command(canvas_id, envelope.idempotencyKey)
        if cached is not None:
            return cached
        self.repository.assert_revision(canvas_id, envelope.baseRevision)
        with self.repository.transaction():
            result = self._dispatch(canvas_id, envelope)
            revision = self.repository.bump_revision(canvas_id)
            self.events.append_for_result(canvas_id, revision, result)
            self.repository.save_command(canvas_id, envelope.idempotencyKey, result)
        return result
~~~

实现 `create_node`、`update_node`、`delete_node`、`connect_nodes`、`disconnect_nodes`、`update_note` 和 `attach_asset`。`POST /api/canvases` 创建一个 revision 为 0 的空画布。连接命令调用 Task 2 的 `validate_connection`，不能只依赖前端校验。

- [ ] **Step 5: Implement event replay**

`EventStore.after_revision` 按 `revision ASC, id ASC` 返回事件；SSE route 使用 async generator 先发送历史事件，再以 1 秒间隔检查新事件。客户端传入的 `afterRevision` 小于当前保留窗口时返回 `EVENT_REPLAY_UNAVAILABLE`，前端随后重新读取 snapshot。

- [ ] **Step 6: Run the persistence and API tests**

Run: `cd api && python -m pytest tests/test_commands.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the command API**

~~~bash
git add api/app/db.py api/app/schemas.py api/app/repositories.py api/app/commands.py api/app/events.py api/app/routes api/app/main.py api/tests
git commit -m "feat: add persistent canvas command API"
~~~

## Task 4: 本地素材上传和媒体元数据

**Files:**
- Create: `api/app/media_metadata.py`
- Create: `api/app/assets.py`
- Create: `api/app/routes/assets.py`
- Modify: `api/app/main.py`
- Modify: `api/app/schemas.py`
- Create: `api/tests/test_assets.py`

**Interfaces:**

- Produces `read_image_metadata(path: Path) -> MediaMetadata`.
- Produces `read_video_metadata(path: Path, ffprobe_bin: str) -> MediaMetadata`.
- Produces `AssetService.save_upload(canvas_id, filename, content_type, stream) -> AssetRecord`.
- Exposes `POST /api/assets/upload` and `GET /api/assets/{asset_id}/file`.

- [ ] **Step 1: Write failing media tests**

在 `api/tests/test_assets.py` 覆盖：

~~~python
def test_image_upload_saves_asset_and_dimensions(client, tmp_path):
    image = make_png(width=640, height=480)
    response = upload(client, image, "reference.png", "image/png")
    assert response.status_code == 201
    assert response.json()["kind"] == "image"
    assert response.json()["width"] == 640
    assert response.json()["height"] == 480

def test_unsupported_upload_type_is_rejected(client):
    response = upload(client, b"hello", "bad.txt", "text/plain")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
~~~

- [ ] **Step 2: Run the asset tests to verify they fail**

Run: `cd api && python -m pytest tests/test_assets.py -q`

Expected: FAIL because upload routes and metadata readers do not exist.

- [ ] **Step 3: Implement image and video metadata readers**

使用 Pillow 读取图片宽高和格式；使用 `ffprobe -v error -show_entries stream=width,height,duration -of json` 读取视频宽高和时长。ffprobe 不存在或输出无法解析时返回 `MEDIA_METADATA_UNAVAILABLE`，不把未验证的尺寸写入数据库。

- [ ] **Step 4: Implement secure local asset storage**

`AssetService.save_upload` 生成 UUID 文件名，把文件写到 `data/assets/{asset_id}/original.{extension}`，验证 MIME 和扩展名一致，计算 SHA-256 checksum，再写入 `assets` 表。Asset file route 只根据数据库 asset ID 查找文件，不接受用户提交的任意路径。

- [ ] **Step 5: Run the asset tests**

Run: `cd api && python -m pytest tests/test_assets.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the asset service**

~~~bash
git add api/app/media_metadata.py api/app/assets.py api/app/routes/assets.py api/app/main.py api/app/schemas.py api/tests/test_assets.py
git commit -m "feat: add local media asset service"
~~~

## Task 5: Replicate Adapter 和持久化生成 Worker

**Files:**
- Create: `api/app/providers/base.py`
- Create: `api/app/providers/replicate.py`
- Create: `api/app/worker.py`
- Modify: `api/app/commands.py`
- Modify: `api/app/schemas.py`
- Create: `api/tests/test_provider_mapping.py`
- Create: `api/tests/test_worker.py`

**Interfaces:**

- Produces `ImageGenerationInput(prompt: str, image_inputs: list[Path], size: str, aspect_ratio: str, output_format: str, warnings: list[dict])`.
- Produces `VideoGenerationInput(prompt: str, reference_images: list[Path], reference_videos: list[Path], duration: int, resolution: str, aspect_ratio: str, generate_audio: bool, warnings: list[dict])`.
- Produces `map_seedream_input(job_snapshot: dict) -> ImageGenerationInput`.
- Produces `map_seedance_input(job_snapshot: dict) -> VideoGenerationInput`.
- Produces `GenerationProvider.create_prediction(input_data) -> PredictionRef`.
- Produces `GenerationProvider.get_prediction(prediction_id) -> PredictionStatus`.
- Produces `Worker.run_once() -> bool`.
- Produces `start_generation` command that snapshots node Prompt, parameters, input Asset IDs and checksums into GenerationJob.

- [ ] **Step 1: Write failing Provider mapping tests**

~~~python
def test_seedream_maps_prompt_parameters_and_all_reference_images():
    job = seedream_job_with_references(count=3)
    mapped = map_seedream_input(job)
    assert mapped.prompt == "make a poster"
    assert len(mapped.image_inputs) == 3
    assert mapped.size == "2K"
    assert mapped.aspect_ratio == "match_input_image"
    assert mapped.output_format == "png"

def test_seedream_maps_first_ten_references_with_warning():
    job = seedream_job_with_references(count=12)
    mapped = map_seedream_input(job)
    assert len(mapped.image_inputs) == 10
    assert mapped.warnings == [{"code": "REFERENCE_LIMIT_TRUNCATED", "omittedCount": 2}]

def test_seedance_maps_image_and_video_references():
    job = seedance_job(images=2, videos=1)
    mapped = map_seedance_input(job)
    assert len(mapped.reference_images) == 2
    assert len(mapped.reference_videos) == 1
    assert mapped.duration == 5
    assert mapped.resolution == "720p"
    assert mapped.aspect_ratio == "adaptive"
    assert mapped.generate_audio is True
~~~

- [ ] **Step 2: Run Provider tests to verify they fail**

Run: `cd api && python -m pytest tests/test_provider_mapping.py -q`

Expected: FAIL because the Provider input types and mappers do not exist.

- [ ] **Step 3: Implement Provider contracts and pure mappers**

在 `api/app/providers/base.py` 定义 dataclass 输入（包含 `warnings: list[dict]`）、`PredictionRef`、`PredictionStatus` 和 `ProviderOutput`。在 `replicate.py` 实现纯映射函数。Seedream 使用 `prompt`、`image_input`、`size`、`aspect_ratio`、`output_format`；Seedance 使用 `prompt`、`reference_images`、`reference_videos`、`duration`、`resolution`、`aspect_ratio`、`generate_audio`。Provider 限制只生成 warning，不删除画布边。

- [ ] **Step 4: Write the failing worker snapshot test**

~~~python
def test_worker_uses_generation_input_snapshot(fake_provider, repository, tmp_path):
    job_id = create_job_with_prompt_and_asset(repository, prompt="original")
    update_node_prompt(repository, job_id, "changed-after-submit")
    worker = Worker(repository, fake_provider, tmp_path)
    worker.run_once()
    assert fake_provider.received_prompt == "original"
~~~

- [ ] **Step 5: Implement start_generation and Worker lifecycle**

`start_generation` 必须验证目标节点类型，读取当前直接上游节点和 Asset，保存 `parameters_json`、Prompt、Asset checksum 和 `base_canvas_revision`，状态设为 `queued`。

`Worker.run_once()` 领取一条 queued 任务并原子更新为 running，调用 Provider，轮询到 succeeded 后下载输出、读取媒体元数据、创建 Asset，再检查目标节点是否存在且输入 snapshot 没有发生冲突；可以安全绑定时更新节点，否则写入 `completed_unattached`。所有状态变化写入 CanvasEvent。

- [ ] **Step 6: Test retry and failure states**

在 `api/tests/test_worker.py` 添加：

~~~python
def test_provider_failure_marks_job_failed(fake_provider, repository, tmp_path):
    fake_provider.fail_with("provider rejected input")
    job_id = create_job(repository)
    Worker(repository, fake_provider, tmp_path).run_once()
    job = repository.get_generation_job(job_id)
    assert job.status == "failed"
    assert job.error == "provider rejected input"
~~~

Run: `cd api && python -m pytest tests/test_provider_mapping.py tests/test_worker.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Provider and Worker**

~~~bash
git add api/app/providers api/app/worker.py api/app/commands.py api/app/schemas.py api/tests/test_provider_mapping.py api/tests/test_worker.py
git commit -m "feat: add Replicate generation worker"
~~~

## Task 6: 前端 API 客户端、状态层和画布壳

**Files:**
- Create: `web/src/api/client.ts`
- Create: `web/src/state/canvasStore.ts`
- Create: `web/src/canvas/CanvasShell.tsx`
- Create: `web/src/canvas/CanvasToolbar.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/domain/types.ts`
- Create: `web/src/test/canvasStore.test.ts`

**Interfaces:**

- Produces `api.getSnapshot(canvasId) -> Promise<CanvasSnapshot>`.
- Produces `api.executeCommand(canvasId, envelope) -> Promise<CommandResult>`.
- Produces `api.subscribeEvents(canvasId, afterRevision, onEvent) -> () => void`.
- Produces `useCanvasStore.load(canvasId)`, `useCanvasStore.execute(envelope)` and `useCanvasStore.applyEvent(event)`.
- Produces `snapshotToReactFlow(snapshot) -> { nodes: Node[], edges: Edge[] }`.

- [ ] **Step 1: Write failing state mapping tests**

~~~typescript
it('maps a persisted node and edge to React Flow elements', () => {
  const result = snapshotToReactFlow(snapshotWithImageToVideo());
  expect(result.nodes).toHaveLength(2);
  expect(result.edges[0].source).toBe('image-1');
  expect(result.edges[0].target).toBe('video-1');
});

it('applies an event and advances the revision once', () => {
  const store = createTestStore(snapshotAtRevision(1));
  store.getState().applyEvent(nodeCreatedEventAtRevision(2));
  expect(store.getState().snapshot.revision).toBe(2);
});
~~~

- [ ] **Step 2: Run frontend tests to verify they fail**

Run: `npm run test --prefix web -- --run src/test/canvasStore.test.ts`

Expected: FAIL because the API client, store and mapping function do not exist.

- [ ] **Step 3: Implement the typed API client**

`web/src/api/client.ts` 使用 `fetch` 实现 snapshot、commands、upload 和 SSE；所有错误转换成 `ApiError { code: string; message: string; status: number }`。SSE 连接关闭时返回清理函数，不能在组件卸载后继续更新 store。

- [ ] **Step 4: Implement Zustand state and React Flow mapping**

Store 保存 snapshot、selected node ID、showEdges、theme 和 isSaving。命令成功后用服务端返回的 revision 和 event 更新状态；视口变更使用 `update_node` 或 `update_canvas` 命令持久化。不要把浏览器 localStorage 当作服务端持久化源。

- [ ] **Step 5: Implement the canvas shell**

`CanvasShell` 使用 controlled `ReactFlow`、`MiniMap`、`Controls`、`Background` 和自定义 nodeTypes/edgeTypes。工具栏提供主题切换、显示/隐藏连线、新建节点和保存状态。节点选中时 edge 的 visibility predicate 强制显示选中节点相关边。

- [ ] **Step 6: Run the state and build checks**

Run: `npm run test --prefix web -- --run src/test/canvasStore.test.ts`

Expected: PASS.

Run: `npm run build --prefix web`

Expected: PASS.

- [ ] **Step 7: Commit the canvas shell**

~~~bash
git add web/src/api web/src/state web/src/canvas web/src/App.tsx web/src/domain web/src/test
git commit -m "feat: add persistent React Flow canvas shell"
~~~

## Task 7: 图片、视频、便签节点和连线交互

**Files:**
- Create: `web/src/nodes/ImageNode.tsx`
- Create: `web/src/nodes/VideoNode.tsx`
- Create: `web/src/nodes/NoteNode.tsx`
- Create: `web/src/edges/ReferenceEdge.tsx`
- Create: `web/src/canvas/ConnectionChooser.tsx`
- Modify: `web/src/canvas/CanvasShell.tsx`
- Modify: `web/src/styles.css`
- Create: `web/src/test/VideoNode.test.tsx`

**Interfaces:**

- Produces custom node components compatible with React Flow `NodeProps`.
- Produces `ReferenceEdge({ selected, hidden, ...props })\) with a solid smooth path and one consistent color.
- Produces `ConnectionChooser({ position, onCreate })`.
- Produces `getVisibleEdgeIds(edges, selectedNodeId, showEdges) -> Set<string>`.

- [ ] **Step 1: Write the failing node interaction tests**

~~~tsx
it('plays only while the video node is hovered', async () => {
  const play = vi.fn().mockResolvedValue(undefined);
  const pause = vi.fn();
  render(<VideoNode data={{ assetUrl: '/video.mp4', play, pause }} />);
  await userEvent.hover(screen.getByTestId('video-node'));
  expect(play).toHaveBeenCalledOnce();
  await userEvent.unhover(screen.getByTestId('video-node'));
  expect(pause).toHaveBeenCalledOnce();
});

it('renders image thumbnails from direct upstream references', () => {
  render(<ImageNode data={{ assetUrl: '/main.png', references: ['/ref-a.png', '/ref-b.png'] }} />);
  expect(screen.getByAltText('reference-1')).toBeInTheDocument();
  expect(screen.getByAltText('reference-2')).toBeInTheDocument();
});
~~~

- [ ] **Step 2: Run node tests to verify they fail**

Run: `npm run test --prefix web -- --run src/test/VideoNode.test.tsx`

Expected: FAIL because custom nodes and reference panels do not exist.

- [ ] **Step 3: Implement the three node components**

图片节点展示主素材或空状态、参考图缩略图和上传/生成按钮；视频节点使用 `<video muted playsInline preload="metadata">`，hover 时调用 play，leave 时调用 pause 并恢复封面；便签使用 textarea、字体选择、字号选择以及可独立调整的宽度和高度。

所有节点把端点包在 hover 状态中，端点使用 source/target 语义和稳定的 handle ID。内部按钮调用 `stopPropagation()`，避免点击 Prompt、上传或删除连接时拖动节点。

- [ ] **Step 4: Implement connection chooser and edge visibility**

从端点拖出后，合法连接直接提交 `connect_nodes`；空白松开时显示图片/视频选择器，选择后提交 `create_node` 并带上新边。参考图删除提交 `disconnect_nodes`，不能提交 `delete_node`。ReferenceEdge 使用 React Flow 的 smooth step 或 bezier path，实心、统一颜色、默认按 showEdges 隐藏。

- [ ] **Step 5: Add resize and upload event wiring**

图片和视频节点上传按钮调用 `POST /api/assets/upload`，成功后提交 `attach_asset`；视频节点根据 Asset 宽高比更新 node width/height；便签拖动宽高时分别更新 width/height，不能把一次横向调整转换成等比缩放。

- [ ] **Step 6: Run node tests and build**

Run: `npm run test --prefix web -- --run src/test/VideoNode.test.tsx src/test/connectionRules.test.ts`

Expected: PASS.

Run: `npm run build --prefix web`

Expected: PASS.

- [ ] **Step 7: Commit node interactions**

~~~bash
git add web/src/nodes web/src/edges web/src/canvas web/src/styles.css web/src/test
git commit -m "feat: add media nodes and reference interactions"
~~~

## Task 8: Prompt 输入区、参数选择和生成任务 UI

**Files:**
- Create: `web/src/nodes/generationParameters.ts`
- Create: `web/src/nodes/PromptComposer.tsx`
- Modify: `web/src/nodes/ImageNode.tsx`
- Modify: `web/src/nodes/VideoNode.tsx`
- Modify: `web/src/domain/types.ts`
- Modify: `web/src/state/canvasStore.ts`
- Create: `web/src/test/PromptComposer.test.tsx`

**Interfaces:**

- Produces `ImageGenerationParameters { size: '1K' | '2K'; aspectRatio: string; outputFormat: 'png' | 'jpeg' }`.
- Produces `VideoGenerationParameters { duration: number; resolution: '480p' | '720p'; aspectRatio: string; generateAudio: boolean }`.
- Produces `getDefaultImageParameters() -> ImageGenerationParameters`.
- Produces `getDefaultVideoParameters() -> VideoGenerationParameters`.
- Produces `PromptComposer({ kind, prompt, parameters, onPromptChange, onParametersChange, onGenerate })`.
- `onGenerate` submits `start_generation` with the current Prompt and parameter object.

- [ ] **Step 1: Write failing Prompt Composer tests**

~~~tsx
it('keeps Seedream parameters inside the image Prompt input area', async () => {
  const onParametersChange = vi.fn();
  render(<PromptComposer kind="image" prompt="" parameters={getDefaultImageParameters()} onPromptChange={vi.fn()} onParametersChange={onParametersChange} onGenerate={vi.fn()} />);
  expect(screen.getByTestId('prompt-composer-image')).toContainElement(screen.getByLabelText('size'));
  expect(screen.getByTestId('prompt-composer-image')).toContainElement(screen.getByLabelText('aspect-ratio'));
  await userEvent.selectOptions(screen.getByLabelText('size'), '1K');
  expect(onParametersChange).toHaveBeenCalledWith(expect.objectContaining({ size: '1K' }));
});

it('submits the current Seedance Prompt and parameters together', async () => {
  const onGenerate = vi.fn();
  render(<PromptComposer kind="video" prompt="camera move" parameters={getDefaultVideoParameters()} onPromptChange={vi.fn()} onParametersChange={vi.fn()} onGenerate={onGenerate} />);
  await userEvent.click(screen.getByRole('button', { name: '生成' }));
  expect(onGenerate).toHaveBeenCalledWith(expect.objectContaining({
    prompt: 'camera move',
    parameters: expect.objectContaining({ duration: 5, resolution: '720p' })
  }));
});
~~~

- [ ] **Step 2: Run Prompt tests to verify they fail**

Run: `npm run test --prefix web -- --run src/test/PromptComposer.test.tsx`

Expected: FAIL because the composer and parameter helpers do not exist.

- [ ] **Step 3: Implement typed defaults and controls**

`generationParameters.ts` 默认值必须是：

~~~typescript
export const getDefaultImageParameters = () => ({
  size: '2K',
  aspectRatio: 'match_input_image',
  outputFormat: 'png',
} as const);

export const getDefaultVideoParameters = () => ({
  duration: 5,
  resolution: '720p',
  aspectRatio: 'adaptive',
  generateAudio: true,
} as const);
~~~

`PromptComposer` 将自由文本框和同一区域的 select/checkbox/chips 放在一个视觉容器中；图片显示 size、aspect ratio、output format，视频显示 duration、resolution、aspect ratio、generate audio。控件只提供当前 Provider 支持的选项。

- [ ] **Step 4: Persist Prompt changes and parameter changes**

输入变化使用 `update_node` 命令保存 `content_json.prompt` 和 `content_json.generation`；点击生成提交：

~~~typescript
{
  command: 'start_generation',
  baseRevision: snapshot.revision,
  idempotencyKey: crypto.randomUUID(),
  payload: {
    targetNodeId,
    prompt,
    parameters,
  },
}
~~~

服务端不把一次性覆盖值写回节点，GenerationJob 只保存本次任务快照。

- [ ] **Step 5: Add task state UI**

节点显示 queued、running、succeeded、failed 和 completed_unattached 状态；失败时展示后端 error，warning 使用可展开的简短提示。生成按钮在 queued/running 时禁用，同一个节点可在任务完成后再次生成。

- [ ] **Step 6: Run Prompt tests and build**

Run: `npm run test --prefix web -- --run src/test/PromptComposer.test.tsx`

Expected: PASS.

Run: `npm run build --prefix web`

Expected: PASS.

- [ ] **Step 7: Commit Prompt and generation controls**

~~~bash
git add web/src/nodes web/src/domain web/src/state web/src/test
git commit -m "feat: add inline generation parameters"
~~~

## Task 9: Worker 进程、README 和端到端验收

**Files:**
- Modify: `scripts/dev.sh`
- Modify: `README.md`
- Modify: `api/app/main.py`
- Modify: `web/src/App.tsx`
- Create: `api/tests/test_end_to_end.py`

**Interfaces:**

- Produces `python -m api.app.worker` as a long-running local Worker entry point.
- Produces a single documented startup sequence that runs API, Worker and Web.
- Produces an integration test covering create node → upload asset → connect → start generation with a fake Provider.
- Produces a manual live generation checklist requiring `REPLICATE_API_TOKEN`.

- [ ] **Step 1: Write the failing end-to-end test**

~~~python
def test_canvas_upload_connect_and_queue_generation(client, fake_provider):
    canvas_id = create_canvas(client)
    image_id = create_node(client, canvas_id, "image", "image")
    video_id = create_node(client, canvas_id, "video", "video")
    asset_id = upload_test_image(client)
    attach_asset(client, canvas_id, image_id, asset_id, revision=2)
    connect(client, canvas_id, image_id, video_id, "edge-1", revision=3)
    response = start_generation(client, canvas_id, video_id, prompt="animate", revision=4)
    assert response.status_code == 200
    assert response.json()["result"]["status"] == "queued"
    assert fake_provider.received == []
~~~

- [ ] **Step 2: Run the end-to-end test to verify it fails**

Run: `cd api && python -m pytest tests/test_end_to_end.py -q`

Expected: FAIL until Worker entry point, fake Provider injection and all routes are wired together.

- [ ] **Step 3: Wire the Worker and application lifespan**

FastAPI lifespan 初始化数据库、事件存储和目录；`python -m api.app.worker` 循环调用 `Worker.run_once()`，没有任务时等待 1 秒，收到 SIGTERM 时退出。不要在 API 请求线程中同步等待图片或视频生成完成。

- [ ] **Step 4: Finish README and local smoke flow**

README 必须包含：

~~~text
1. 创建 Python 虚拟环境并安装 api 依赖
2. npm install --prefix web
3. cp .env.example .env
4. 填写 REPLICATE_API_TOKEN
5. 启动 API、Worker 和 Web
6. 打开本地 Web 地址
7. 创建图片节点，上传参考图，填写 Prompt，选择参数并生成
8. 创建视频节点，连接图片节点，填写 Prompt，选择参数并生成
~~~

同时写明无 Token 时可以用 fake Provider 运行测试，但不能声称完成真实生成验证。

- [ ] **Step 5: Run all automated checks**

Run: `cd api && python -m pytest -q`

Expected: PASS.

Run: `npm run test --prefix web -- --run`

Expected: PASS.

Run: `npm run build --prefix web`

Expected: PASS.

- [ ] **Step 6: Run the local UI smoke test**

启动 API、Worker 和 Web，确认：

- 画布可打开，标题和空状态可见。
- 节点可以创建、拖动、连接和删除。
- 图片上传后显示缩略图。
- 视频节点只在悬停时播放。
- Prompt 输入区内参数可选择并在刷新后恢复。
- 隐藏连线、主题切换和小地图可用。
- 配置 Token 后，图片任务和视频任务会从 queued 进入 succeeded 或显示明确的 Provider 错误。

- [ ] **Step 7: Commit the integrated local app**

~~~bash
git add scripts/dev.sh README.md api web
git commit -m "feat: complete local media canvas workflow"
~~~

## Implementation Handoff

完成本计划后，最终验证需要同时报告：

- API、Worker、Web 的启动方式和本地地址。
- 自动化测试和构建结果。
- 是否使用真实 Replicate Token 完成了图片和视频生成。
- 未配置 Token 时，哪些结果只由 fake Provider 验证。
- 画布、生成任务和 Agent 命令接口的当前可用范围。
