# 煤矿应急救援决策 AI 智能体

本项目是一个面向煤矿安全应急场景的多源知识问答与辅助决策系统。系统采用前后端分离架构，前端提供登录、资料库管理、智能问答和知识图谱可视化界面，后端负责文档解析、向量检索、知识图谱构建、视觉证据分析、传感器数据融合和多智能体协同推理。

## 核心功能

- **用户与个人知识库**：支持注册、登录、退出和登录态恢复。每个用户拥有独立的 `library_session_id`，文档、图片、视频、传感器数据和聊天记录按用户隔离。
- **文档知识库**：支持上传 PDF、DOCX、TXT 文档，后端自动提取文本、按条文和语义切块，并建立会话级向量检索索引。
- **RAG 增强问答**：问答前会综合向量相似度、关键词命中、风险画像和知识图谱信号召回文档片段。
- **知识图谱**：支持基于文档片段构建煤矿应急知识图谱，也支持导入外部三元组 JSON，并在前端进行查询、展开和可视化。
- **图片与视频证据**：支持上传图片和视频。图片会调用 OpenAI 兼容视觉接口进行风险识别；视频会抽帧分析并把命中帧转为问答证据。
- **传感器数据接入**：支持上传或推送传感器 JSON 数据，数据会进入风险融合链路并参与多智能体问答。
- **多智能体协同**：系统包含态势感知、知识检索、决策推理、协同指挥四类智能体。后端会根据问题和证据自动路由角色，并聚合最终答复。
- **持久化存储**：用户、Token、文档、图片、视频、传感器记录和聊天记录存储在本地 SQLite 和上传目录中。

## 技术栈

前端：

- React 19
- Vite
- react-force-graph-2d

后端：

- Flask
- Flask-CORS
- LangChain
- langchain-openai
- FAISS
- sentence-transformers
- PyMuPDF
- python-docx
- OpenCV
- Neo4j Python Driver
- SQLite

大模型接口：

- 文本智能体默认使用 LongCat OpenAI 兼容接口。
- 图片和视频帧分析使用 OpenAI 兼容视觉接口。

## 目录结构

```text
coal-mine-agent/
├─ README.md
├─ package.json
├─ vite.config.js
├─ run_project.ps1
├─ run_project.cmd
├─ index.html
├─ public/
├─ src/
│  ├─ App.jsx
│  ├─ index.css
│  └─ main.jsx
├─ server/
│  ├─ app.py
│  ├─ agent.py
│  ├─ config.py
│  ├─ domain_schema.py
│  ├─ knowledge_graph.py
│  ├─ persistence.py
│  ├─ retrieval.py
│  ├─ risk_fusion.py
│  ├─ sensor_store.py
│  └─ requirements.txt
├─ tools/
│  ├─ benchmark_retrieval_strategies.py
│  ├─ benchmark_retrieval_regulation_top10.py
│  ├─ extract_regulation_triples.py
│  └─ test_oneais_vision.py
└─ docs/
   ├─ sample-sensor-upload.json
   ├─ sample-triples.json
   ├─ coal-mine-safety-2025-triples.json
   └─ figures/
```

## 环境要求

建议环境：

- Node.js 18 或更高版本
- Python 3.10 或更高版本
- Windows PowerShell
- 可选：Neo4j 5.x

首次运行前安装依赖：

```powershell
cd C:\self\Draft_py\coal-mine-agent
npm install

cd server
pip install -r requirements.txt
```

说明：

- `sentence-transformers` 首次加载模型时可能需要下载模型文件。
- 如果暂不使用 Neo4j，可在环境变量中设置 `NEO4J_ENABLED=0`。
- 如果启用 Neo4j，需要保证 Neo4j 服务已启动并配置好连接参数。

## 环境变量

后端会自动读取项目根目录或 `server/` 目录下的 `.env.local` 文件，也可以直接在系统环境变量中配置。

常用配置：

| 变量名 | 说明 | 默认值 |
| --- | --- | --- |
| `LONGCAT_API_KEY` | LongCat 文本模型 API Key | 必填 |
| `LONGCAT_BASE_URL` | LongCat OpenAI 兼容接口地址 | `https://api.longcat.chat/openai` |
| `LONGCAT_CHAT_PROXY_URL` | LongCat 代理聊天接口 | `https://api.longcat.chat/anthropic/v1/messages` |
| `LONGCAT_MODEL` | 文本模型名称 | `LongCat-Flash-Chat` |
| `VISION_API_KEY` / `ONEAIS_API_KEY` | 视觉模型 API Key | 图片/视频分析必填 |
| `VISION_BASE_URL` | OpenAI 兼容视觉接口地址 | `https://api.openai.com/v1` |
| `VISION_MODEL` | 视觉模型名称 | `gpt-5.4` |
| `SERVER_PORT` | Flask 后端端口 | `5001` |
| `CORS_ORIGINS` | 允许跨域访问的前端地址，逗号分隔 | `http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173` |
| `RAG_ENABLED` | 是否启用文档检索增强 | `1` |
| `RAG_TOP_K` | 每次问答召回的文档片段数 | `4` |
| `RAG_EMBEDDING_MODEL` | 向量模型 | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| `KG_ENABLED` | 是否启用知识图谱摘要 | `1` |
| `NEO4J_ENABLED` | 是否启用 Neo4j 图数据库 | `1` |
| `NEO4J_URI` | Neo4j 地址 | `neo4j://127.0.0.1:7687` |
| `NEO4J_USERNAME` | Neo4j 用户名 | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j 密码 | 空 |
| `VIDEO_MAX_FRAMES` | 单个视频最多抽帧数量 | `8` |
| `VIDEO_SAMPLE_SECONDS` | 视频抽帧间隔秒数 | `1.5` |

前端需要配置后端地址：

```powershell
$env:VITE_API_BASE_URL="http://127.0.0.1:5001"
```

也可以写入项目根目录的 `.env.local`：

```env
VITE_API_BASE_URL=http://127.0.0.1:5001
LONGCAT_API_KEY=你的文本模型Key
VISION_API_KEY=你的视觉模型Key
NEO4J_ENABLED=0
```

## 启动方式

### 一键启动

项目提供了 Windows 启动脚本，会自动启动后端和前端，并把日志写入 `.runlogs/`。

```powershell
cd C:\self\Draft_py\coal-mine-agent
.\run_project.ps1 -OpenBrowser
```

也可以双击或执行：

```powershell
.\run_project.cmd
```

启动成功后访问：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:5001`

### 手动启动

启动后端：

```powershell
cd C:\self\Draft_py\coal-mine-agent\server
python app.py
```

启动前端：

```powershell
cd C:\self\Draft_py\coal-mine-agent
$env:VITE_API_BASE_URL="http://127.0.0.1:5001"
npm run dev -- --host 127.0.0.1 --port 5173
```

构建前端生产包：

```powershell
npm run build
```

预览构建结果：

```powershell
npm run preview
```

## 使用流程

1. 打开前端页面，注册或登录账号。
2. 进入文档库，上传煤矿规程、预案或操作说明文档。
3. 如需图谱能力，进入知识图谱库，点击生成知识图谱，或上传 `docs/sample-triples.json` 这类三元组文件。
4. 可选上传现场图片、视频，或在传感器库中接入传感器 JSON。
5. 回到问答窗口，输入应急问题，例如“瓦斯浓度超限如何处置？”。
6. 后端会结合文档片段、图谱关系、图片/视频证据、传感器数据和历史对话，返回多智能体协同结论。

## 后端接口概览

除旧版兼容接口外，大多数业务接口需要在请求头中携带登录 Token：

```http
Authorization: Bearer <token>
```

### 认证与消息

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/auth/register` | 注册用户 |
| `POST` | `/api/auth/login` | 登录并返回 Token |
| `GET` | `/api/auth/me` | 获取当前登录用户 |
| `POST` | `/api/auth/logout` | 退出登录 |
| `GET` | `/api/messages/list` | 获取聊天记录 |
| `POST` | `/api/messages/clear` | 清空聊天记录 |

### 文档库

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/documents/upload` | 上传 PDF、DOCX、TXT，并建立检索索引 |
| `GET` | `/api/documents/list` | 获取当前用户文档列表 |
| `POST` | `/api/documents/remove` | 删除指定文档及其检索片段 |

### 知识图谱

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/knowledge-graph` | 获取当前会话知识图谱 |
| `POST` | `/api/knowledge-graph/query` | 按关键词查询局部图谱 |
| `POST` | `/api/knowledge-graph/rebuild` | 基于当前文档重新构建图谱 |
| `GET` | `/api/knowledge-graph/status` | 获取图谱构建状态 |
| `POST` | `/api/knowledge-graph/expand` | 展开指定图谱节点邻居 |
| `POST` | `/api/knowledge-graph/triples/upload` | 上传外部三元组 JSON |

### 传感器

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/sensors/push` | 推送传感器记录 |
| `GET` | `/api/sensors/latest` | 获取最新传感器状态 |
| `POST` | `/api/sensors/clear` | 清空传感器数据 |
| `POST` | `/api/sensors/remove` | 删除指定传感器 |

### 图片与视频

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/images/upload` | 上传图片、调用视觉模型分析并持久化 |
| `GET` | `/api/images/list` | 获取图片库列表 |
| `POST` | `/api/images/remove` | 删除图片 |
| `POST` | `/api/videos/upload` | 上传视频、抽帧分析并持久化 |
| `GET` | `/api/videos/list` | 获取视频库列表 |
| `POST` | `/api/videos/remove` | 删除视频 |
| `POST` | `/api/image-analyze` | 旧版单图 base64 分析接口 |
| `POST` | `/api/video-analyze` | 旧版单视频分析接口 |

### 问答

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/agent-chat` | 多智能体问答主接口 |
| `POST` | `/api/chat` | LongCat 普通聊天代理接口 |

`/api/agent-chat` 支持的典型请求结构：

```json
{
  "query": "瓦斯浓度超限如何处置？",
  "session_id": "user-xxxx",
  "history": [
    { "role": "user", "content": "刚才上传了煤矿安全规程。" }
  ],
  "selected_document_ids": [],
  "evidence": {
    "documents": [],
    "images": [],
    "sensors": []
  },
  "options": {
    "use_retrieval_evidence": true,
    "use_sensor_evidence": true,
    "use_session_memory": true
  }
}
```

## 数据持久化

后端运行后会在 `server/.persist/` 下生成本地持久化数据：

```text
server/.persist/
├─ app_state.db
└─ uploads/
   ├─ documents/
   ├─ images/
   └─ videos/
```

其中：

- `app_state.db` 保存用户、Token、聊天记录、传感器记录和文件元数据。
- `uploads/documents/` 保存上传文档原始文件。
- `uploads/images/` 保存上传图片。
- `uploads/videos/` 保存上传视频。
- 文档向量索引、传感器缓存和智能体会话记忆会在服务进程内维护，用户重新登录后会从持久化数据恢复文档和传感器状态。

## 核心模块说明

- `src/App.jsx`：前端主组件，包含认证、问答、文档库、图片库、视频库、传感器库和知识图谱库页面。
- `server/app.py`：Flask 后端入口，定义所有 HTTP 接口，串联上传、检索、图谱、视觉分析、传感器和多智能体问答。
- `server/agent.py`：多智能体编排层，负责角色路由、证据组织、角色调用、超时兜底和最终聚合。
- `server/retrieval.py`：RAG 检索层，负责文档切块、向量索引、混合评分召回和索引恢复。
- `server/knowledge_graph.py`：知识图谱层，负责三元组抽取、实体归一、Neo4j 存储、图谱查询和图谱摘要。
- `server/risk_fusion.py`：风险融合层，综合问题、历史、文档、图片和传感器数据生成风险画像。
- `server/persistence.py`：本地持久化层，负责 SQLite 表结构、用户认证、文件保存和记录管理。
- `server/sensor_store.py`：传感器数据标准化与会话级缓存。
- `server/config.py`：集中管理模型、RAG、图谱、视频、CORS 等运行配置。

## 示例数据

项目内置了一些测试数据和图谱文件：

- `docs/sample-sensor-upload.json`：传感器上传示例。
- `docs/sample-triples.json`：三元组导入示例。
- `docs/coal-mine-safety-2025-triples.json`：煤矿安全相关三元组数据。
- `docs/figures/`：架构图、流程图和检索实验结果图。

## 常见问题

### 前端请求地址变成 `undefined/api/...`

说明前端没有读到 `VITE_API_BASE_URL`。请在启动前设置：

```powershell
$env:VITE_API_BASE_URL="http://127.0.0.1:5001"
```

或使用项目自带的 `run_project.ps1`。

### 后端提示未配置 `LONGCAT_API_KEY`

请在 `.env.local` 或系统环境变量中配置：

```env
LONGCAT_API_KEY=你的文本模型Key
```

### 图片或视频分析失败

请检查视觉模型配置：

```env
VISION_API_KEY=你的视觉模型Key
VISION_BASE_URL=https://api.openai.com/v1
VISION_MODEL=你的视觉模型名称
```

### 知识图谱构建失败

如果没有 Neo4j 环境，可以先关闭 Neo4j：

```env
NEO4J_ENABLED=0
```

如果需要完整图谱存储和查询，请启动 Neo4j，并配置：

```env
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=你的密码
```

### 端口被占用

`run_project.ps1` 会尝试停止 `5001` 和 `5173` 端口上的旧进程。如果手动启动，请确认端口未被占用，或修改 `SERVER_PORT` 与 Vite 端口。

## 开发命令

```powershell
# 前端开发
npm run dev

# 前端构建
npm run build

# 前端代码检查
npm run lint

# 后端启动
cd server
python app.py
```

## 安全说明

本项目用于煤矿应急救援知识问答和辅助决策演示。模型输出不能替代现场规程、调度命令、专业人员研判或法定应急流程。实际生产环境中应结合矿方制度、实时监测、人员定位、通信状态和现场指挥要求进行复核。
