# Film Copilot

Film Copilot 是一个本地运行的单用户图片/视频生成无限画布。

## 本地启动

1. 创建 Python 虚拟环境并安装 API 依赖：

   ~~~bash
   python -m venv .venv
   source .venv/bin/activate
   python -m pip install -e 'api[dev]'
   ~~~

2. 安装 Web 依赖：

   ~~~bash
   npm install --prefix web
   ~~~

3. 创建本地配置：

   ~~~bash
   cp .env.example .env
   ~~~

4. 填写 `REPLICATE_API_TOKEN`。图片节点使用 `bytedance/seedream-5-pro`，视频节点使用 `bytedance/seedance-2.0-mini`。

5. 启动 API、Worker 和 Web：

   ~~~bash
   ./scripts/dev.sh
   ~~~

6. 打开本地 Web 地址：`http://127.0.0.1:5173`。

7. 创建图片节点，上传参考图，在节点 Prompt 区域填写提示词并选择参数后生成。

8. 创建视频节点，连接图片节点，在视频节点 Prompt 区域填写提示词并选择参数后生成。

API 默认运行在 `http://127.0.0.1:8000`，Web 默认运行在 `http://127.0.0.1:5173`。Worker 会从 SQLite 中领取 queued 任务，生成结果写入 `data/assets`。

没有 `REPLICATE_API_TOKEN` 时，可以运行自动化测试和 fake Provider 测试；这不代表已完成真实模型生成验证。

## 验证命令

~~~bash
cd api && python -m pytest -q
cd ../web && npm run test -- --run
cd ../web && npm run build
~~~
