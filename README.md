# Infinite Media Canvas

本项目是一个本地运行的单用户图片/视频生成无限画布。

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

4. 填写 `REPLICATE_API_TOKEN` 后启动：

   ~~~bash
   ./scripts/dev.sh
   ~~~

API 默认运行在 `http://127.0.0.1:8000`，Web 默认运行在 `http://127.0.0.1:5173`。
