# 煤矿应急救援智能体项目说明

本项目为前后端分离应用：
1. 前端使用 React + Vite 提供交互界面。
2. 后端使用 Flask 提供文档解析、图片识别、检索增强和多智能体问答接口。

## 运行方式

### 前端

在项目根目录执行：

```bash
npm install
npm run dev
```

前端默认从环境变量 `VITE_API_BASE_URL` 读取后端地址，例如：

```bash
VITE_API_BASE_URL=http://127.0.0.1:5001 npm run dev
```

### 后端

在 server 目录执行：

```bash
pip install -r requirements.txt
python pdf_parser.py
```

运行前需要配置以下环境变量：

```bash
export LONGCAT_API_KEY="..."
export BAIDU_API_KEY="..."
export BAIDU_SECRET_KEY="..."
```

可选环境变量：

- `LONGCAT_BASE_URL`：默认 `https://api.longcat.chat/openai`
- `LONGCAT_CHAT_PROXY_URL`：默认 `https://api.longcat.chat/anthropic/v1/messages`
- `SERVER_PORT`：默认 `5001`
- `CORS_ORIGINS`：逗号分隔的允许来源列表

## 目录结构

```text
coal-mine-agent/
├─ README.md
├─ package.json
├─ vite.config.js
├─ src/
│  ├─ App.jsx
│  ├─ index.css
│  └─ main.jsx
├─ server/
│  ├─ agent.py
│  ├─ config.py
│  ├─ domain_schema.py
│  ├─ knowledge_graph.py
│  ├─ pdf_parser.py
│  ├─ requirements.txt
│  ├─ retrieval.py
│  └─ risk_fusion.py
├─ tools/
│  └─ benchmark_agent.py
└─ test_agent.py
```

## 核心模块说明

- `src/App.jsx`：前端主界面，负责聊天、文档上传、图片上传和结果展示。
- `server/pdf_parser.py`：Flask 主服务入口，提供文档上传、图片分析、聊天代理和多智能体接口。
- `server/retrieval.py`：文档切块、向量索引和会话级检索。
- `server/risk_fusion.py`：多源风险识别与风险等级生成。
- `server/knowledge_graph.py`：轻量知识图谱抽取与摘要。
- `server/agent.py`：多智能体路由、角色调用和结果聚合。
- `tools/benchmark_agent.py`：实验评测脚本。
- `test_agent.py`：后端回归验证脚本。

## 对外接口说明

1. `POST /api/documents/upload`
   - 上传 PDF/DOCX/TXT 文档并建立后端向量索引。

2. `POST /api/documents/remove`
   - 移除当前会话中的已上传文档及索引。

3. `POST /api/agent-chat`
   - 多智能体问答主接口，支持结构化历史与证据输入。

4. `POST /api/image-analyze`
   - 调用百度图像识别分析图片内容。

5. `POST /api/chat`
   - 后端代理 LongCat 聊天请求。

6. `POST /api/parse-pdf`
7. `POST /api/parse-docx`
8. `POST /api/parse-text`
   - 兼容保留的单文件解析接口。
