# 煤矿应急救援智能体项目说明

本项目为前后端分离应用：
1. 前端使用 React + Vite 提供交互界面。
2. 后端使用 Flask 提供文档解析、图片识别和大模型代理接口。

## 运行方式

### 前端

在项目根目录执行：

```bash
npm install
npm run dev
```

### 后端

在 server 目录执行：

```bash
pip install -r requirements.txt
python pdf_parser.py
```

## 目录结构

```text
coal-mine-agent/
├─ .gitignore
├─ eslint.config.js
├─ index.html
├─ package-lock.json
├─ package.json
├─ README.md
├─ vite.config.js
├─ public/
│  └─ favicon.svg
├─ src/
│  ├─ App.jsx
│  ├─ index.css
│  └─ main.jsx
└─ server/
	├─ config.py
	├─ pdf_parser.py
	└─ requirements.txt
```

## 每个文件的作用

### 根目录文件

1. .gitignore
作用：定义 Git 忽略规则，避免提交缓存、构建产物和本地环境文件。

2. eslint.config.js
作用：前端代码检查规则配置，用于统一 JavaScript/React 代码风格。

3. index.html
作用：Vite 前端入口 HTML，挂载 React 根节点。

4. package.json
作用：前端依赖和脚本定义（如 dev、build）。

5. package-lock.json
作用：锁定 npm 依赖版本，保证不同机器安装结果一致。

6. vite.config.js
作用：Vite 构建与开发服务器配置。

7. README.md
作用：项目说明文档（当前文件）。

### public 目录

1. public/favicon.svg
作用：浏览器标签页图标资源。

### src 目录（前端）

1. src/main.jsx
作用：前端入口脚本，创建并挂载 React 应用。

2. src/App.jsx
作用：核心页面与业务逻辑，包含：
1. 聊天交互。
2. 文档上传与解析调用。
3. 图片上传与识别调用。
4. 调用后端聊天接口获取大模型回复。

3. src/index.css
作用：全局样式定义。

### server 目录（后端）

1. server/pdf_parser.py
作用：Flask 主服务入口，提供 API 路由，包含：
1. 文档解析接口（PDF、DOCX、TXT）。
2. 图片识别接口（百度图像识别）。
3. 聊天代理接口（后端转发 LongCat 请求）。

2. server/config.py
作用：统一管理后端配置项（端口、API Key、模型参数、超时等）。

3. server/requirements.txt
作用：后端 Python 依赖列表。

## 对外接口说明（简版）

1. POST /api/parse-pdf
作用：解析上传 PDF 文本。

2. POST /api/parse-docx
作用：解析上传 DOCX 文本。

3. POST /api/parse-text
作用：解析上传 TXT 文本。

4. POST /api/image-analyze
作用：识别上传图片内容并返回关键词。

5. POST /api/chat
作用：后端代理大模型请求，返回聊天回复。
