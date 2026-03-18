# 煤矿应急救援决策 AI 智能体

基于中国矿业大学袁冠团队研究成果构建的多智能体协同煤矿应急救援决策系统。

## 功能概览

- ⚡ **实时应急决策支持** — 瓦斯爆炸、矿井火灾、突水等事故的协同决策
- 🧠 **四智能体协同** — 知识图谱 / 态势感知 / 决策推理 / 协同指挥
- 📄 **规程知识库** — 上传 PDF / DOCX / TXT 规程文档，智能检索引用
- 📷 **图片识别** — 百度 AI 通用物体识别，辅助现场态势感知
- 🔴 **分级告警** — 自动识别高危 / 警告关键词并切换并行 / 串行执行模式

---

## 本地运行指南

### 环境要求

| 工具 | 最低版本 | 说明 |
|------|---------|------|
| [Node.js](https://nodejs.org/) | 18+ | 前端运行时 |
| npm | 9+ | 随 Node.js 一起安装 |
| [Python](https://www.python.org/downloads/) | 3.9+ | 后端运行时 |
| pip | — | 随 Python 一起安装 |

---

### 第一步：克隆仓库

```bash
git clone https://github.com/Carlos1ks/Graduation-thesis.git
cd Graduation-thesis
```

---

### 第二步：配置 API 密钥

#### 2.1 Longcat AI（聊天核心）

前端使用 Longcat API 驱动对话。密钥已内置在源码中，**无需额外配置**即可直接使用。

如需替换为自己的密钥，编辑 `coal-mine-agent/src/App.jsx` 开头部分：

```js
const LONGCAT_API_KEY = "你的密钥";
const LONGCAT_BASE_URL = "https://api.longcat.chat/anthropic";
const LONGCAT_MODEL = "LongCat-Flash-Thinking-2601";
```

#### 2.2 百度 AI（图片识别，可选）

图片识别功能需要百度 AI 平台凭据。如不使用图片识别功能，可以跳过此步骤。

1. 前往 [百度智能云控制台](https://console.bce.baidu.com/) 创建应用，获取 **API Key** 和 **Secret Key**
2. 在 `coal-mine-agent/server/` 目录下创建 `.env` 文件：

```bash
# coal-mine-agent/server/.env
BAIDU_API_KEY=your_api_key_here
BAIDU_SECRET_KEY=your_secret_key_here
```

或在启动后端时通过环境变量传入：

```bash
# macOS / Linux
BAIDU_API_KEY=xxx BAIDU_SECRET_KEY=yyy python pdf_parser.py

# Windows (PowerShell)
$env:BAIDU_API_KEY="xxx"; $env:BAIDU_SECRET_KEY="yyy"; python pdf_parser.py
```

---

### 第三步：启动后端（可选）

后端用于解析 PDF / DOCX 文件 以及 调用百度图片识别。若只使用文字问答，可跳过此步。

```bash
cd coal-mine-agent/server

# 安装 Python 依赖（首次运行）
pip install -r requirements.txt

# 启动后端服务
python pdf_parser.py
```

后端默认运行在 **http://localhost:5001**

> **提示**：如果遇到 `pip install` 速度慢，可以加速：
> ```bash
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

---

### 第四步：启动前端

**新开一个终端窗口**，然后：

```bash
cd coal-mine-agent

# 安装前端依赖（首次运行）
npm install

# 启动开发服务器
npm run dev
```

前端默认运行在 **http://localhost:5173**

---

### 第五步：打开浏览器

访问 [http://localhost:5173](http://localhost:5173)

---

## 目录结构

```
Graduation-thesis/
├── coal-mine-agent/          # 主项目目录
│   ├── src/
│   │   └── App.jsx           # 前端主界面（React）
│   ├── server/
│   │   ├── pdf_parser.py     # Flask 后端（文件解析 + 图片识别）
│   │   ├── requirements.txt  # Python 依赖列表
│   │   └── .env.example      # 环境变量示例
│   ├── package.json          # 前端依赖配置
│   └── vite.config.js        # Vite 构建配置
├── MULTI_AGENT_ARCHITECTURE.md  # 多智能体架构设计文档
├── QUICK_TEST_GUIDE.md          # 快速测试指南
└── README.md                    # 本文件
```

---

## 常见问题

### ❓ 启动前端后页面空白或报错？

```bash
# 确认 Node.js 版本
node --version   # 需要 18+

# 重新安装依赖
cd coal-mine-agent
rm -rf node_modules
npm install
npm run dev
```

### ❓ 发送消息后没有 AI 回复？

1. 打开浏览器开发者工具（F12 → Network），查看请求是否成功
2. 确认 `App.jsx` 中的 `LONGCAT_API_KEY` 有效
3. 检查是否有网络代理问题（API 地址：`https://api.longcat.chat`）

### ❓ 上传 PDF 后提示"请确保Python后端服务已启动"？

请先按照 [第三步](#第三步启动后端可选) 启动后端服务。

### ❓ 图片识别提示"百度API密钥未配置"？

按照 [第 2.2 节](#22-百度-ai图片识别可选) 配置百度 AI 凭据。

### ❓ pip install 安装失败（PyMuPDF / pymupdf）？

```bash
# 升级 pip 后重试
python -m pip install --upgrade pip
pip install -r requirements.txt
```

---

## 快速参考

| 服务 | 地址 | 启动命令 |
|------|------|---------|
| 前端界面 | http://localhost:5173 | `npm run dev`（在 `coal-mine-agent/` 目录） |
| 后端 API | http://localhost:5001 | `python pdf_parser.py`（在 `coal-mine-agent/server/` 目录） |
