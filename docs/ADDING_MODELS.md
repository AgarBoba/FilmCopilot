# 接入生成模型

画布上的图片和视频节点可以选择 `models/` 里登记的任何模型。每个模型由两部分组成：

| | 位置 | 什么时候要写 |
|---|---|---|
| 模型文件 | `models/<id>.json` | 每加一个模型写一个。纯数据，保存后画布自动刷新，不用重启 |
| provider 对接代码 | `api/app/providers/<name>.py` | 每接一家新的 API 写一次，这一家的所有模型共用。写完要重启 dev.sh |

快速流程（给编码 Agent 看的精简版）见根目录的 [AGENTS.md](../AGENTS.md)。本文是完整参考。

## 1. 模型文件

```json
{
  "id": "flux-kontext-pro",
  "label": "Flux Kontext Pro",
  "kind": "image",
  "provider": "replicate",
  "providerModel": "black-forest-labs/flux-kontext-pro",
  "default": false,
  "description": "擅长按文字改图：换背景、改颜色、保持人物不变地改动作。一次只参考一张图。",
  "inputs": {
    "prompt": "prompt",
    "images": { "field": "input_image", "max": 1, "single": true }
  },
  "parameters": [
    { "key": "aspectRatio", "label": "Aspect ratio", "type": "enum", "field": "aspect_ratio",
      "default": "match_input_image",
      "options": [
        { "value": "match_input_image", "label": "Match input" },
        { "value": "16:9", "label": "16:9" }
      ] },
    { "key": "guidance", "label": "Guidance", "type": "number", "field": "guidance",
      "default": 3.5, "min": 1, "max": 10 }
  ],
  "fixedInputs": { "safety_tolerance": 2 }
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✓ | 唯一，小写，不带空格。节点里存的就是它，不要随便改 |
| `label` | | 节点「Model」菜单里显示的名字 |
| `kind` | ✓ | `image` 或 `video` |
| `provider` | ✓ | 对接代码的名字，对应 `api/app/providers/<provider>.py` |
| `providerModel` | ✓ | 这个模型在 provider 那边的名字，例如 Replicate 的 `owner/name` |
| `default` | | 新节点默认用它。每个 kind 最多一个 |
| `description` | | 一两句中文，写它擅长什么。画布 Agent 靠这段描述挑模型（`list_models` 工具） |
| `inputs.prompt` | ✓ | 提示词发到哪个字段 |
| `family` | | 同一个模型的不同版本 / 接口写同一个名字，例如 `kling-3.0` 和 `kling-3.0-motion-control` 都写 `"kling-3.0"`。Agent 找替代接口时用 |
| `capabilities` | | 这个模型能做什么，只能用 `models/_capabilities.md` 词表里的词，例如 `["omni_reference", "text_to_video"]`。拼错了会出现在 `errors` 里 |
| `checks` | | 节点检查规则，见下面「输入限制的三道关」 |
| `inputs.images` | | 参考图发到哪个字段。`max` 是最多几张，超出的会被截掉，节点上会提示。`single: true` 表示字段只收一张图、不是数组。老式首尾帧接口每张图一个字段，写 `{"fields": ["start_image", "end_image"]}`：按连线顺序，第 1 条连线放首帧 |
| `inputs.videos` | | 参考视频，写法同上 |
| `parameters` | | 节点上显示的参数控件，按顺序排列 |
| `fixedInputs` | | 每次请求都原样带上、用户不用调的字段 |
| `credits` | | 每次生成扣多少积分（模拟），见下 |

### 价格（`credits`）

写一个数字就是固定价；按参数变价写成 `{"base": 基础价, "multiply": {参数key: {取值: 倍数}}}`，价格 = 基础价 × 各参数取值的倍数，向上取整。取值按文字匹配（布尔写 `"true"` / `"false"`，数字写 `"10"`），没列出的取值算 1 倍。不写就按图片 5、视频 30。1 积分大约对应 $0.01 的成本，照模型实际价格估。

```json
"credits": { "base": 30, "multiply": { "duration": { "10": 2 }, "resolution": { "480p": 0.5 } } }
```

### 参数

| 属性 | 说明 |
|---|---|
| `key` | 画布内部的名字（camelCase）。同一个概念在不同模型上尽量用同一个 key（如 `aspectRatio`、`duration`），这样切换模型时能保留取值 |
| `label` | 控件上方的文字 |
| `type` | `enum`（下拉）、`boolean`（开关）、`integer`、`number`、`string` |
| `field` | provider 那边的字段名，默认同 `key` |
| `default` | 必填，必须是合法取值 |
| `options` | enum 用，写成 `[{"value": ..., "label": ...}]`。可以加 `"aliases": ["jpg"]`，让画布 Agent 写 jpg 时也能认成 jpeg |
| `min` / `max` | 数字类型的范围 |

取值不合法（例如画布 Agent 填了模型不支持的比例）时，会回落到 `default`。

### 校验

```bash
python3 scripts/check_model.py <id>          # 免费：校验文件、看发给 provider 的参数
python3 scripts/check_model.py --all         # 校验全部
python3 scripts/check_model.py <id> --run    # 真实生成一次（花钱，先问用户），结果在 data/model-checks/
```

文件写错时，画布不会崩溃，只是不显示这个模型。错误信息出现在 `doctor.py` 和 `GET /api/models` 的 `errors` 字段里。

### Replicate 模型自动起草

```bash
python3 scripts/add_model.py owner/name [--kind video] [--id my-id] [--default]
```

脚本读取 Replicate 上模型的输入 schema，然后：
- 猜出提示词和参考图对应的字段；
- 把枚举、开关、数字转成参数；
- 跳过 `seed` 这类不需要放在节点上的字段；
- 列出需要人工核对的地方。

它起草的只是初稿，下面这些要自己审：
- `description` 写成中文；
- 删掉不常用的参数；
- 核对参考图上限；
- 模型有多个图片入口（比如首帧、尾帧）时，确认它选的入口对不对。

### 说明文档（`models/<id>.md`）

每个模型旁边放一份同名的 Markdown，给画布 Agent 看的「好不好用」：JSON 管程序要的（字段、上限、价格），说明文档管 Agent 计划时要的。`scripts/add_model.py` 会写好骨架。固定这几个小标题（缺了会在 `errors` 里提示）：

```markdown
# 模型名
一两句介绍
## 擅长
## 不擅长
## 输入限制        # 用大白话写：比例、尺寸、数量、时长……写不进 checks 的怪要求也写这里
## 提示词          # 写法；官方有提示词技能时加一行「技能：film-copilot:seedance-prompt」
## 已知问题        # 生成失败后发现的新限制补在这里
```

保存就生效，不用重启。画布左上角积分旁边的「模型」按钮可以直接查看（只读）。

### 输入限制的三道关

1. **说明文档**：Agent 用 `get_model_guide` 读，先按说明安排计划（比如参考图比例不对，先裁剪或换模型）。
2. **节点检查**：JSON 里的 `checks`，每次连线、换模型、改 Prompt 后在节点上跑一遍。结果存在 `node_checks` 表，节点上显示红色标记，Agent 在 `get_canvas` / `get_node` 和工具结果里看到；有错误时生成会被拒绝，不扣积分。
   ```json
   "checks": [
     { "rule": "aspect_range", "min": 0.333, "max": 3 },
     { "rule": "side_multiple", "of": 16 }
   ]
   ```
   可用规则（都可以加 `"target": "videos"` 改查参考视频）：`aspect_range`（宽高比 min～max）、`side_range`（每条边像素 min～max）、`side_multiple`（宽高是 of 的倍数）、`max_pixels`（总像素上限）、`duration_range`（参考视频秒数）、`prompt_length`（Prompt 字数上限）、`requires`（至少要连几个 `images` / `videos`）。真有新类型的规则时，在 `api/app/checks/__init__.py` 加一个函数。
3. **生成失败兜底**：模型服务拒绝时，`api/app/providers/errors.py` 把常见报错翻成一句人话（带原始报错），存进 `model_rejections` 表。Agent 按原因调整一次再试；`get_model_guide` 和「模型」面板会列出最近的拒绝原因，发现是规律就补进说明文档。

## 2. provider 对接代码

`api/app/providers/<name>.py` 需要提供：

```python
ENV_KEYS = ('FAL_KEY',)            # 需要的 .env 设置，doctor 和画布用它提示“还缺什么”
def from_env() -> Adapter: ...     # 从环境变量构造；缺 key 时，在真正调用时抛 ProviderNotConfigured

class Adapter:
    def create_prediction(self, model: ModelSpec, request: GenerationRequest) -> PredictionRef: ...
    def get_prediction(self, prediction_id: str) -> PredictionStatus: ...
    def download_output(self, output, destination: Path) -> Path: ...

def check_key() -> str | None: ...  # 可选：doctor --online 用它验证密钥，返回错误文字或 None
```

- `request.prompt`、`request.images`、`request.videos`（本地文件路径）、`request.parameters`（已按模型校验过、以 key 为键）
- `build_inputs(model, request, attach)` 会按模型文件把这些映射成 provider 的字段。`attach(path)` 由你决定怎么把本地文件交给 API：打开的文件、先上传拿到的 URL、或者 `data:` URI（模板里有 `data_uri()`）
- `PredictionStatus.status` 要映射成 `starting` / `processing` / `succeeded` / `failed` / `canceled`；`outputs` 是结果列表，Worker 取第一个交给 `download_output`
- Worker 每 2 秒查一次，最长等 30 分钟
- API 是同步返回结果的：在 `create_prediction` 里直接拿到结果，存起来，`get_prediction` 直接返回 `succeeded`

从模板开始：

```bash
cp api/app/providers/_template.py api/app/providers/<name>.py
```

然后：
1. 按对方 API 文档填 TODO；
2. 在 `.env.example` 加 key 那一行，附上获取地址；
3. 跑 `python3 scripts/setup.py`，它会把新 key 补进 `.env`；
4. 让用户自己填 key；
5. 重启 dev.sh；
6. 跑 `check_model.py`。

安全要求：
- key 只从环境变量读；
- 不要打印 key，也不要写进异常信息或日志。模板里的 `_raise_for_status` 只带状态码和响应正文；
- 错误信息会显示在节点上，写得短、说清怎么办。

## 3. 画布 Agent 怎么用这些模型

画布里的 Agent 有两个工具：
- `list_models`：每个模型的 `description`、功能、擅长 / 不擅长（从说明文档摘一行）、节点检查规则、参数、参考图上限、provider 能不能用；可以按功能筛选（`capability: "first_last_frame"`）。
- `get_model_guide`：一个模型的完整说明文档、功能词的解释、要加载的提示词技能、最近被拒绝的原因。

选模型时它先找同一家族里支持 `omni_reference` 的模型，用 Prompt 里的 [Image1]、[Video1] 说明每个参考的用途；必须用严格首尾帧时才用老式接口（按连线顺序决定首尾帧）。

创建节点时它可以指定 `model`，不指定就用默认模型。所以 `description` 写得越具体，它选得越准。
