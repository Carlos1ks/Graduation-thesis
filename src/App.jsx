// 前端主入口文件。
// 这个文件主要包含四类内容：
// 1. 与后端通信的接口封装；
// 2. 文档/图片/视频/传感器/图谱等会话资源的状态管理；
// 3. 图谱展示相关的辅助函数；
// 4. 整个页面的主 React 组件。
import { useState, useRef, useEffect, useMemo } from "react";
import ForceGraph2D from "react-force-graph-2d";

// 前端统一维护的后端接口地址。
// 这样查某个按钮或某个功能走的是哪个后端接口时，会更直观。
const BACKEND_BASE_URL = import.meta.env.VITE_API_BASE_URL;
const AUTH_LOGIN_API_URL = `${BACKEND_BASE_URL}/api/auth/login`;
const AUTH_REGISTER_API_URL = `${BACKEND_BASE_URL}/api/auth/register`;
const AUTH_ME_API_URL = `${BACKEND_BASE_URL}/api/auth/me`;
const AUTH_LOGOUT_API_URL = `${BACKEND_BASE_URL}/api/auth/logout`;
const CHAT_API_URL = `${BACKEND_BASE_URL}/api/agent-chat`;
const MESSAGE_LIST_API_URL = `${BACKEND_BASE_URL}/api/messages/list`;
const DOCUMENT_LIST_API_URL = `${BACKEND_BASE_URL}/api/documents/list`;
const DOCUMENT_UPLOAD_API_URL = `${BACKEND_BASE_URL}/api/documents/upload`;
const DOCUMENT_REMOVE_API_URL = `${BACKEND_BASE_URL}/api/documents/remove`;
const IMAGE_UPLOAD_API_URL = `${BACKEND_BASE_URL}/api/images/upload`;
const IMAGE_LIST_API_URL = `${BACKEND_BASE_URL}/api/images/list`;
const IMAGE_REMOVE_API_URL = `${BACKEND_BASE_URL}/api/images/remove`;
const TRIPLES_UPLOAD_API_URL = `${BACKEND_BASE_URL}/api/knowledge-graph/triples/upload`;
const VIDEO_UPLOAD_API_URL = `${BACKEND_BASE_URL}/api/videos/upload`;
const VIDEO_LIST_API_URL = `${BACKEND_BASE_URL}/api/videos/list`;
const VIDEO_REMOVE_API_URL = `${BACKEND_BASE_URL}/api/videos/remove`;
const SENSOR_PUSH_API_URL = `${BACKEND_BASE_URL}/api/sensors/push`;
const SENSOR_LATEST_API_URL = `${BACKEND_BASE_URL}/api/sensors/latest`;
const SENSOR_CLEAR_API_URL = `${BACKEND_BASE_URL}/api/sensors/clear`;
const SENSOR_REMOVE_API_URL = `${BACKEND_BASE_URL}/api/sensors/remove`;
const KNOWLEDGE_GRAPH_QUERY_API_URL = `${BACKEND_BASE_URL}/api/knowledge-graph/query`;
const KNOWLEDGE_GRAPH_STATUS_API_URL = `${BACKEND_BASE_URL}/api/knowledge-graph/status`;
const KNOWLEDGE_GRAPH_REBUILD_API_URL = `${BACKEND_BASE_URL}/api/knowledge-graph/rebuild`;
const MAX_HISTORY_MESSAGES = 6;
const AUTH_TOKEN_STORAGE_KEY = "coal-mine-agent-auth-token";
const SESSION_STORAGE_KEY = "coal-mine-agent-session-id";
const APP_VIEW_CHAT = "chat";
const APP_VIEW_DOCUMENTS = "documents";
const APP_VIEW_IMAGES = "images";
const APP_VIEW_VIDEOS = "videos";
const APP_VIEW_SENSORS = "sensors";
const APP_VIEW_GRAPH = "graph";
const LIBRARY_VIEW_SET = new Set([
  APP_VIEW_CHAT,
  APP_VIEW_DOCUMENTS,
  APP_VIEW_IMAGES,
  APP_VIEW_VIDEOS,
  APP_VIEW_SENSORS,
  APP_VIEW_GRAPH,
]);

function createSessionId() {
  // 为当前浏览器标签页生成一个临时 session_id。
  // 后端的文档库、图谱、传感器和聊天记忆都是按这个会话号隔离的。
  return `session-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function getInitialSessionId() {
  // 当前实现采用“每次刷新页面都开新会话”的策略，
  // 所以这里会主动丢掉旧 session_id，避免把上次上传的知识混进来。
  const next = createSessionId();
  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
    } catch {}
  }
  return next;
}

function getStoredAuthToken() {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function setStoredAuthToken(token) {
  if (typeof window === "undefined") return;
  try {
    if (token) {
      window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
    } else {
      window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    }
  } catch {}
}

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getStoredAuthToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(url, {
    ...options,
    headers,
  });
}

// 快捷问题：主要用于演示和快速切换典型应急场景。
const QUICK_QUESTIONS = [
  { icon: "💨", text: "瓦斯浓度超标如何处置？" },
  { icon: "🔥", text: "井下火灾应急预案流程" },
  { icon: "💧", text: "矿井突水事故救援步骤" },
  { icon: "📋", text: "应急救援队伍如何协同调度？" },
  { icon: "⚠️", text: "煤尘爆炸预防措施有哪些？" },
  { icon: "🛤️", text: "灾后逃生通道如何规划？" },
];

// 前端展示用的多智能体角色标签。
const AGENTS = [
  { id: "knowledge", name: "知识图谱智能体", icon: "🧠", color: "#4ade80" },
  { id: "perception", name: "态势感知智能体", icon: "📡", color: "#60a5fa" },
  { id: "decision", name: "决策推理智能体", icon: "⚡", color: "#f59e0b" },
  { id: "coordination", name: "协同指挥智能体", icon: "🎯", color: "#f472b6" },
];

// 左侧知识库导航项。这里的“库”都是当前会话私有的。
const LIBRARY_NAV_ITEMS = [
  { id: APP_VIEW_CHAT, label: "问答窗口", icon: "💬", color: "#4ade80" },
  { id: APP_VIEW_DOCUMENTS, label: "文档库", icon: "📄", color: "#22d3ee" },
  { id: APP_VIEW_IMAGES, label: "图片库", icon: "📸", color: "#60a5fa" },
  { id: APP_VIEW_VIDEOS, label: "视频库", icon: "🎬", color: "#f59e0b" },
  { id: APP_VIEW_SENSORS, label: "传感器数据库", icon: "📡", color: "#c084fc" },
  { id: APP_VIEW_GRAPH, label: "知识图谱库", icon: "🧠", color: "#67e8f9" },
];

// 统一的界面视觉变量。因为本项目大量使用内联样式，
// 所以把常用颜色/阴影集中在这里便于统一调整。
const UI = {
  appBg: "linear-gradient(180deg,#f9fbff 0%,#f1f5f9 52%,#e2e8f0 100%)",
  headerBg: "rgba(255,255,255,0.96)",
  sidebarBg: "rgba(248,250,252,0.98)",
  cardBg: "rgba(255,255,255,0.98)",
  softBg: "rgba(248,250,252,0.98)",
  mutedBg: "rgba(241,245,249,0.96)",
  border: "rgba(15,23,42,0.14)",
  borderStrong: "rgba(14,165,233,0.34)",
  text: "#111827",
  muted: "#334155",
  subtle: "#475569",
  shadow: "0 14px 36px rgba(15,23,42,0.09)",
  overlay: "rgba(15,23,42,0.12)",
  graphBg: "radial-gradient(circle at center, rgba(125,211,252,0.20), rgba(255,255,255,0.99) 54%, rgba(241,245,249,0.98))",
};

function hashForView(view) {
  // 把当前页面视图同步到 URL hash，方便刷新后恢复当前位置。
  if (view === APP_VIEW_CHAT) {
    return "#/chat";
  }
  return `#/library/${view}`;
}

function parseViewFromHash(hash) {
  // 从 URL hash 解析出当前应该显示的页面。
  const normalized = String(hash || "").replace(/^#\/?/, "").trim().toLowerCase();
  if (!normalized || normalized === "chat") {
    return APP_VIEW_CHAT;
  }
  const candidate = normalized.startsWith("library/") ? normalized.slice("library/".length) : normalized;
  return LIBRARY_VIEW_SET.has(candidate) ? candidate : APP_VIEW_CHAT;
}

async function uploadDocumentToBackend(file, sessionId) {
  // 文档上传：
  // 把 PDF/DOCX/TXT 交给后端入库，后端会完成解析、切块和向量索引。
  const formData = new FormData();
  formData.append("file", file);
  formData.append("session_id", sessionId);

  const response = await apiFetch(DOCUMENT_UPLOAD_API_URL, {
    method: "POST",
    body: formData,
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `文档上传失败：${response.status}`);
  }
  return result;
}

async function removeDocumentFromBackend(documentId, sessionId) {
  // 从当前会话文档库里删除一个文档，
  // 同时后端会把对应的检索索引一起更新掉。
  const response = await apiFetch(DOCUMENT_REMOVE_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_id: documentId,
      session_id: sessionId,
    }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `文档移除失败：${response.status}`);
  }
}

async function fetchDocumentsFromBackend(sessionId) {
  // 获取当前会话下已经上传并入库的文档列表。
  const params = new URLSearchParams({ session_id: sessionId });
  const response = await apiFetch(`${DOCUMENT_LIST_API_URL}?${params.toString()}`);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `文档列表获取失败：${response.status}`);
  }
  return result;
}

async function uploadTriplesToBackend(file, sessionId) {
  // 上传外部三元组 JSON，直接写入当前会话的知识图谱。
  const formData = new FormData();
  formData.append("file", file);
  formData.append("session_id", sessionId);

  const response = await apiFetch(TRIPLES_UPLOAD_API_URL, {
    method: "POST",
    body: formData,
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `三元组上传失败：${response.status}`);
  }
  return result;
}

async function uploadVideoToBackend(file, sessionId) {
  // 视频上传：
  // 后端会抽帧、识别命中帧，再把结果转成可以参与问答的图像证据。
  const formData = new FormData();
  formData.append("file", file);
  formData.append("session_id", sessionId);

  const response = await apiFetch(VIDEO_UPLOAD_API_URL, {
    method: "POST",
    body: formData,
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `视频分析失败：${response.status}`);
  }
  return result;
}

async function pushSensorsToBackend(records, sessionId) {
  // 批量推送传感器记录到当前会话，
  // 让风险识别和问答链路都能使用这些实时数据。
  const response = await apiFetch(SENSOR_PUSH_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      records,
    }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `传感器接入失败：${response.status}`);
  }
  return result;
}

async function fetchSensorsFromBackend(sessionId) {
  // 拉取当前会话最新的传感器状态。
  const params = new URLSearchParams({ session_id: sessionId });
  const response = await apiFetch(`${SENSOR_LATEST_API_URL}?${params.toString()}`);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `传感器列表获取失败：${response.status}`);
  }
  return result;
}

async function clearSensorsFromBackend(sessionId) {
  // 清空当前会话缓存的传感器数据。
  const response = await apiFetch(SENSOR_CLEAR_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `传感器清空失败：${response.status}`);
  }
  return result;
}

async function removeSensorFromBackend(sensorId, sessionId) {
  const response = await apiFetch(SENSOR_REMOVE_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sensor_id: sensorId,
      session_id: sessionId,
    }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `传感器移除失败：${response.status}`);
  }
  return result;
}

async function fetchKnowledgeGraph(sessionId, keyword = "", options = {}) {
  const text = keyword.trim();
  if (!text) {
    const params = new URLSearchParams({ session_id: sessionId, limit: "1000" });
    const response = await apiFetch(`${BACKEND_BASE_URL}/api/knowledge-graph?${params.toString()}`, {
      signal: options.signal,
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.success) {
      throw new Error(result.error || `知识图谱加载失败：${response.status}`);
    }
    return result;
  }

  const response = await apiFetch(KNOWLEDGE_GRAPH_QUERY_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      keyword: text,
      limit: 160,
      depth: 1,
    }),
    signal: options.signal,
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `知识图谱加载失败：${response.status}`);
  }
  return result;
}

async function fetchKnowledgeGraphStatus(sessionId) {
  const params = new URLSearchParams({ session_id: sessionId });
  const response = await apiFetch(`${KNOWLEDGE_GRAPH_STATUS_API_URL}?${params.toString()}`);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `图谱状态获取失败：${response.status}`);
  }
  return result;
}

async function rebuildKnowledgeGraph(sessionId) {
  // 触发后端重新为当前会话构建知识图谱。
  const response = await apiFetch(KNOWLEDGE_GRAPH_REBUILD_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `图谱生成失败：${response.status}`);
  }
  return result;
}

async function loginToBackend(username, password) {
  const response = await apiFetch(AUTH_LOGIN_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `登录失败：${response.status}`);
  }
  return result;
}

async function registerToBackend(username, password) {
  const response = await apiFetch(AUTH_REGISTER_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `注册失败：${response.status}`);
  }
  return result;
}

async function fetchCurrentUserFromBackend() {
  const response = await apiFetch(AUTH_ME_API_URL);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `获取登录态失败：${response.status}`);
  }
  return result;
}

async function logoutFromBackend() {
  const response = await apiFetch(AUTH_LOGOUT_API_URL, { method: "POST" });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `退出登录失败：${response.status}`);
  }
  return result;
}

async function fetchMessagesFromBackend(sessionId) {
  const params = new URLSearchParams({ session_id: sessionId });
  const response = await apiFetch(`${MESSAGE_LIST_API_URL}?${params.toString()}`);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `获取聊天记录失败：${response.status}`);
  }
  return result;
}

async function uploadImageToBackend(file, sessionId) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("session_id", sessionId);
  const response = await apiFetch(IMAGE_UPLOAD_API_URL, {
    method: "POST",
    body: formData,
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `图片上传失败：${response.status}`);
  }
  return result;
}

async function fetchImagesFromBackend(sessionId) {
  const params = new URLSearchParams({ session_id: sessionId });
  const response = await apiFetch(`${IMAGE_LIST_API_URL}?${params.toString()}`);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `图片列表获取失败：${response.status}`);
  }
  return result;
}

async function removeImageFromBackend(imageId, sessionId) {
  const response = await apiFetch(IMAGE_REMOVE_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image_id: imageId, session_id: sessionId }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `图片删除失败：${response.status}`);
  }
  return result;
}

async function fetchVideosFromBackend(sessionId) {
  const params = new URLSearchParams({ session_id: sessionId });
  const response = await apiFetch(`${VIDEO_LIST_API_URL}?${params.toString()}`);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `视频列表获取失败：${response.status}`);
  }
  return result;
}

async function removeVideoFromBackend(videoId, sessionId) {
  const response = await apiFetch(VIDEO_REMOVE_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_id: videoId, session_id: sessionId }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `视频删除失败：${response.status}`);
  }
  return result;
}

function compactKnowledgeGraphForView(nodes, links) {
  // 图谱接口返回的数据里，节点和边有时会带冗余引用。
  // 这里先整理成“前端画图真正需要的最小结构”。
  const visibleNodes = Array.isArray(nodes) ? nodes : [];
  const visibleUids = new Set(visibleNodes.map(node => node.uid));
  const visibleLinks = (Array.isArray(links) ? links : []).filter(link => {
    const source = typeof link.source === "string" ? link.source : link.source?.id || link.source?.uid;
    const target = typeof link.target === "string" ? link.target : link.target?.id || link.target?.uid;
    return visibleUids.has(source) && visibleUids.has(target);
  });
  return { nodes: visibleNodes, links: visibleLinks };
}

function emptyGraphData() {
  // 图谱页的空状态对象，避免组件里到处写判空逻辑。
  return { nodes: [], links: [], stats: {}, centerUid: "", matchedUids: [] };
}

function graphNodeDisplayLabel(node) {
  // 节点展示时优先用中文标签；没有中文时再退回 id / name。
  const candidates = [
    node?.label,
    ...(Array.isArray(node?.aliases) ? node.aliases : []),
  ];
  const readable = candidates
    .map(value => String(value || "").trim())
    .find(value => /[\u4e00-\u9fa5]/.test(value));
  return readable || String(node?.label || node?.name || node?.id || "").trim();
}

function graphLinkEndpointUid(endpoint) {
  return typeof endpoint === "string" ? endpoint : endpoint?.uid || endpoint?.id || "";
}

function normalizeGraphSearchText(value) {
  return String(value || "").trim().toLowerCase();
}

function stripGraphFocusNode(node) {
  const rest = { ...(node || {}) };
  delete rest.isCenter;
  delete rest.isMatched;
  delete rest.fx;
  delete rest.fy;
  return rest;
}

function graphNodeMatchScore(node, keyword) {
  // 给本地图谱搜索做一个很轻量的匹配打分：
  // 完全相等 > 前缀命中 > 包含命中。
  const text = normalizeGraphSearchText(keyword);
  if (!text) return 99;
  const fields = [
    graphNodeDisplayLabel(node),
    node?.label,
    node?.id,
    ...(Array.isArray(node?.aliases) ? node.aliases : []),
  ].map(value => normalizeGraphSearchText(value)).filter(Boolean);
  if (fields.some(field => field === text)) return 0;
  if (fields.some(field => field.startsWith(text))) return 1;
  if (fields.some(field => field.includes(text))) return 2;
  return 99;
}

function clearGraphFocus(data) {
  // 取消图谱局部聚焦，恢复完整视图。
  const nodes = (Array.isArray(data?.nodes) ? data.nodes : []).map(node => ({
    ...stripGraphFocusNode(node),
    isCenter: false,
    isMatched: false,
  }));
  const links = Array.isArray(data?.links) ? data.links : [];
  return {
    ...data,
    nodes,
    links,
    centerUid: "",
    matchedUids: [],
    query: "",
    localFocus: false,
    stats: {
      ...(data?.stats || {}),
      view_node_count: nodes.length,
      view_relation_count: links.length,
    },
  };
}

function focusGraphLocally(data, keyword, layoutByUid = new Map()) {
  // 在已经加载到前端的图谱上做“本地聚焦搜索”。
  // 目的有两个：
  // 1. 减少频繁请求后端；
  // 2. 让搜索框输入后的反馈更及时。
  const text = normalizeGraphSearchText(keyword);
  if (!text) {
    return data?.nodes?.length ? clearGraphFocus(data) : null;
  }
  const nodes = Array.isArray(data?.nodes) ? data.nodes : [];
  const links = Array.isArray(data?.links) ? data.links : [];
  if (!nodes.length) return null;

  const nodeScores = nodes
    .map(node => ({ uid: String(node.uid || ""), score: graphNodeMatchScore(node, text) }))
    .filter(item => item.uid && item.score < 99)
    .sort((a, b) => a.score - b.score || a.uid.localeCompare(b.uid));
  const degreeByUid = new Map();
  for (const link of links) {
    const source = graphLinkEndpointUid(link.source);
    const target = graphLinkEndpointUid(link.target);
    if (source) degreeByUid.set(source, (degreeByUid.get(source) || 0) + 1);
    if (target) degreeByUid.set(target, (degreeByUid.get(target) || 0) + 1);
  }
  const centerUid = (
    nodeScores
      .map(item => ({ ...item, degree: degreeByUid.get(item.uid) || 0 }))
      .sort((a, b) => b.degree - a.degree || a.score - b.score || a.uid.localeCompare(b.uid))[0]
      ?.uid
  ) || "";
  if (!centerUid) return null;

  const matchedUids = new Set([centerUid]);
  const relatedUids = new Set([centerUid]);
  for (const link of links) {
    const source = graphLinkEndpointUid(link.source);
    const target = graphLinkEndpointUid(link.target);
    if (source === centerUid || target === centerUid) {
      if (source) relatedUids.add(source);
      if (target) relatedUids.add(target);
    }
  }
  const focusedLinks = links.filter(link => {
    const source = graphLinkEndpointUid(link.source);
    const target = graphLinkEndpointUid(link.target);
    return source === centerUid || target === centerUid;
  });

  return {
    ...data,
    nodes: nodes
      .filter(node => relatedUids.has(String(node.uid || "")))
      .map(node => {
        const clean = stripGraphFocusNode(node);
        const uid = String(node.uid || "");
        const layout = layoutByUid.get(uid) || {};
        return {
          ...clean,
          ...(Number.isFinite(layout.x) ? { x: layout.x } : {}),
          ...(Number.isFinite(layout.y) ? { y: layout.y } : {}),
          ...(Number.isFinite(layout.vx) ? { vx: layout.vx } : {}),
          ...(Number.isFinite(layout.vy) ? { vy: layout.vy } : {}),
          isCenter: uid === centerUid,
          isMatched: uid === centerUid,
        };
      }),
    links: focusedLinks,
    centerUid,
    matchedUids: [centerUid],
    query: keyword,
    localFocus: true,
    stats: {
      ...(data?.stats || {}),
      view_node_count: relatedUids.size,
      view_relation_count: focusedLinks.length,
    },
  };
}

function graphFocusPoint(graphData) {
  // 计算当前匹配节点的大致中心点，方便图谱视角自动移动过去。
  const nodes = Array.isArray(graphData?.nodes) ? graphData.nodes : [];
  if (!nodes.length) return null;
  const matched = new Set([
    ...(Array.isArray(graphData?.matchedUids) ? graphData.matchedUids : []),
    graphData?.centerUid,
  ].filter(Boolean));
  if (!matched.size) return null;
  const matchedNodes = nodes.filter(node => matched.has(node.uid) && Number.isFinite(node.x) && Number.isFinite(node.y));
  if (!matchedNodes.length) return null;
  const centerNode = matchedNodes.find(node => node.uid === graphData.centerUid) || matchedNodes[0];
  if (matchedNodes.length === 1) {
    return { x: centerNode.x, y: centerNode.y };
  }
  const sum = matchedNodes.reduce((acc, node) => {
    acc.x += node.x;
    acc.y += node.y;
    return acc;
  }, { x: 0, y: 0 });
  return {
    x: sum.x / matchedNodes.length,
    y: sum.y / matchedNodes.length,
  };
}

function graphPayloadForView(data, extra = {}) {
  // 把后端图谱结果转换成前端 ForceGraph 更容易消费的结构。
  const compactGraph = compactKnowledgeGraphForView(data?.nodes, data?.links || data?.relations);
  const centerUid = data?.center_uid || extra.centerUid || "";
  const matchedUids = new Set([...(Array.isArray(data?.matched_uids) ? data.matched_uids : []), centerUid].filter(Boolean));
  const matchedList = compactGraph.nodes.filter(node => matchedUids.has(node.uid));
  const matchedIndexByUid = new Map(matchedList.map((node, index) => [node.uid, index]));
  const centerRadius = matchedList.length <= 1 ? 0 : Math.min(86, 30 + matchedList.length * 8);
  return {
    nodes: compactGraph.nodes.map(node => {
      const matchedIndex = matchedIndexByUid.get(node.uid);
      const isMatched = matchedIndex !== undefined;
      const angle = matchedList.length <= 1 ? 0 : (Math.PI * 2 * matchedIndex) / matchedList.length;
      return {
        ...node,
        ...(isMatched ? {
          fx: matchedList.length <= 1 ? 0 : Math.cos(angle) * centerRadius,
          fy: matchedList.length <= 1 ? 0 : Math.sin(angle) * centerRadius,
        } : {}),
        isCenter: node.uid === centerUid,
        isMatched,
      };
    }),
    links: compactGraph.links,
    stats: {
      ...(data?.stats || {}),
      view_node_count: data?.view_stats?.node_count ?? compactGraph.nodes.length,
      view_relation_count: data?.view_stats?.relation_count ?? compactGraph.links.length,
    },
    centerUid,
    matchedUids: Array.from(matchedUids),
    fromCache: Boolean(data?.from_cache),
    scope: extra.scope || (data?.query ? "query" : "full"),
    query: data?.query || "",
    localFocus: false,
  };
}

function dedupeGraphLinks(links) {
  // 有些关系在视图里可能重复出现，这里去重并统计重复次数。
  const grouped = new Map();
  for (const link of Array.isArray(links) ? links : []) {
    if (!link?.source || !link?.target || !link?.relation) continue;
    const key = `${link.source}|${link.target}|${link.relation}|${link.condition || ""}`;
    const existing = grouped.get(key);
    if (!existing) {
      grouped.set(key, { ...link, duplicateCount: 1 });
    } else {
      existing.duplicateCount += 1;
    }
  }
  return Array.from(grouped.values());
}

function getVideoSummaryPreview(summaryText) {
  // 从后端的视频分析摘要里提取“适合卡片展示的前几行概览”。
  return String(summaryText || "")
    .split("\n")
    .map(line => line.trim())
    .filter(line => line && line !== "关键片段：" && !line.startsWith("- "))
    .slice(0, 3);
}

function getVideoKeyClips(video) {
  // 优先从结构化 evidence 中提取关键片段；
  // 如果 evidence 不存在，再从 summary_text 的项目符号行兜底解析。
  if (Array.isArray(video?.evidence) && video.evidence.length > 0) {
    return video.evidence
      .slice(0, 6)
      .map((item, index) => ({
        id: `${video.name || "video"}-clip-${index}`,
        label: item.timestamp_s != null ? `${Number(item.timestamp_s).toFixed(1)}s` : `片段 ${index + 1}`,
        summary: String(item.summary || "").trim() || "未识别到明显异常",
      }));
  }

  return String(video?.summary_text || "")
    .split("\n")
    .map(line => line.trim())
    .filter(line => line.startsWith("- "))
    .slice(0, 6)
    .map((line, index) => ({
      id: `${video?.name || "video"}-summary-clip-${index}`,
      label: `片段 ${index + 1}`,
      summary: line.replace(/^-+\s*/, "").trim(),
    }));
}

function countSelectedItems(ids, items, getId) {
  const selectedSet = new Set(ids);
  return items.reduce((count, item, index) => (
    selectedSet.has(String(getId(item, index) || "")) ? count + 1 : count
  ), 0);
}

export default function CoalMineAgent() {
  // 整个前端应用的根组件。
  // 这里集中管理聊天记录、知识库资源、图谱状态以及各类弹窗/上传流程。
  const [messages, setMessages] = useState([{
    role: "assistant",
    content: "您好！我是**煤矿应急救援决策知识问答AI智能体**，由中国矿业大学研发。\n\n可为您提供：\n- ⚡ **实时应急决策支持**\n- 🔍 **灾害风险智能识别**\n- 📋 **救援策略精准生成**\n- 🤝 **跨部门协同指挥建议**",
    timestamp: new Date(),
  }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [authLoading, setAuthLoading] = useState(true);
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const [authMode, setAuthMode] = useState("login");
  const [authError, setAuthError] = useState("");
  const [authForm, setAuthForm] = useState({ username: "", password: "", confirmPassword: "" });
  const [currentUser, setCurrentUser] = useState(null);
  const [activeAgents, setActiveAgents] = useState([]);
  const [alertLevel, setAlertLevel] = useState(null);
  const [currentView, setCurrentView] = useState(() => (
    typeof window === "undefined" ? APP_VIEW_CHAT : parseViewFromHash(window.location.hash)
  ));
  const [docs, setDocs] = useState([]);
  const [images, setImages] = useState([]);
  const [videos, setVideos] = useState([]);
  const [sensors, setSensors] = useState([]);
  const [selectedDocIds, setSelectedDocIds] = useState([]);
  const [selectedImageIds, setSelectedImageIds] = useState([]);
  const [selectedVideoIds, setSelectedVideoIds] = useState([]);
  const [selectedSensorIds, setSelectedSensorIds] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [imageUploading, setImageUploading] = useState(false);
  const [videoUploading, setVideoUploading] = useState(false);
  const [graphGenerating, setGraphGenerating] = useState(false);
  const [sensorDialogOpen, setSensorDialogOpen] = useState(false);
  const [sensorInput, setSensorInput] = useState('[\n  {\n    "sensor_id": "gas-01",\n    "name": "瓦斯浓度传感器",\n    "value": 1.7,\n    "unit": "%",\n    "threshold": 1.5,\n    "location": "掘进工作面",\n    "status": "报警"\n  }\n]');
  const [graphOpen, setGraphOpen] = useState(false);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphData, setGraphData] = useState(emptyGraphData);
  const [graphKeyword, setGraphKeyword] = useState("");
  const [selectedGraphNode, setSelectedGraphNode] = useState(null);
  const [graphError, setGraphError] = useState("");
  const [graphBuildStatus, setGraphBuildStatus] = useState({ state: "idle", message: "" });
  const [graphFocusedKey, setGraphFocusedKey] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const messagesEndRef = useRef(null);
  const graphViewportRef = useRef(null);
  const forceGraphRef = useRef(null);
  const graphQueryCacheRef = useRef(new Map());
  const graphLayoutReadyRef = useRef(false);
  const graphLoadedSessionRef = useRef("");
  const graphAbortControllerRef = useRef(null);
  const graphPreviousViewRef = useRef(null);
  const graphLoadingStoppedRef = useRef(false);
  const fileInputRef = useRef(null);
  const triplesInputRef = useRef(null);
  const imageInputRef = useRef(null);
  const videoInputRef = useRef(null);
  const sensorFileInputRef = useRef(null);
  const sessionIdRef = useRef("");
  const [graphViewportSize, setGraphViewportSize] = useState({ width: 880, height: 620 });
  const graphViewActive = currentView === APP_VIEW_GRAPH;

  const selectedDocumentCount = useMemo(
    () => countSelectedItems(selectedDocIds, docs, (doc) => doc.document_id),
    [selectedDocIds, docs]
  );
  const selectedImageCount = useMemo(
    () => countSelectedItems(selectedImageIds, images, (img) => img.image_id),
    [selectedImageIds, images]
  );
  const selectedVideoCount = useMemo(
    () => countSelectedItems(selectedVideoIds, videos, (video) => video.video_id),
    [selectedVideoIds, videos]
  );
  const selectedSensorCount = useMemo(
    () => countSelectedItems(selectedSensorIds, sensors, (sensor) => sensor.sensor_id),
    [selectedSensorIds, sensors]
  );

  const selectedSummaryText = useMemo(() => {
    const parts = [];
    if (selectedDocumentCount > 0) parts.push(`文档 ${selectedDocumentCount} 份`);
    if (selectedImageCount > 0) parts.push(`图片 ${selectedImageCount} 张`);
    if (selectedVideoCount > 0) parts.push(`视频 ${selectedVideoCount} 段`);
    if (selectedSensorCount > 0) parts.push(`传感器 ${selectedSensorCount} 条`);
    return parts.length > 0 ? `本次已选择：${parts.join("，")}` : "本次未选择任何资料，问答将仅基于当前问题与历史对话。";
  }, [selectedDocumentCount, selectedImageCount, selectedVideoCount, selectedSensorCount]);

  const syncSelectedIds = (nextItems, setSelectedIds, getId) => {
    setSelectedIds((prev) => {
      const available = new Set(nextItems.map((item, index) => String(getId(item, index) || "")));
      return prev.filter((id) => available.has(String(id)));
    });
  };

  const toggleSelection = (id, setSelectedIds) => {
    const normalizedId = String(id || "");
    setSelectedIds((prev) => (
      prev.includes(normalizedId)
        ? prev.filter((item) => item !== normalizedId)
        : [...prev, normalizedId]
    ));
  };

  const selectAllForView = (viewId) => {
    if (viewId === APP_VIEW_DOCUMENTS) {
      setSelectedDocIds(docs.map((doc) => String(doc.document_id || "")));
      return;
    }
    if (viewId === APP_VIEW_IMAGES) {
      setSelectedImageIds(images.map((img) => String(img.image_id || "")));
      return;
    }
    if (viewId === APP_VIEW_VIDEOS) {
      setSelectedVideoIds(videos.map((video) => String(video.video_id || "")));
      return;
    }
    if (viewId === APP_VIEW_SENSORS) {
      setSelectedSensorIds(sensors.map((sensor) => String(sensor.sensor_id || "")));
    }
  };

  const clearSelectionForView = (viewId) => {
    if (viewId === APP_VIEW_DOCUMENTS) {
      setSelectedDocIds([]);
      return;
    }
    if (viewId === APP_VIEW_IMAGES) {
      setSelectedImageIds([]);
      return;
    }
    if (viewId === APP_VIEW_VIDEOS) {
      setSelectedVideoIds([]);
      return;
    }
    if (viewId === APP_VIEW_SENSORS) {
      setSelectedSensorIds([]);
    }
  };

  const buildLibrarySelectionActions = (viewId) => (
    <>
      <button
        onClick={() => selectAllForView(viewId)}
        disabled={
          (viewId === APP_VIEW_DOCUMENTS && docs.length === 0) ||
          (viewId === APP_VIEW_IMAGES && images.length === 0) ||
          (viewId === APP_VIEW_VIDEOS && videos.length === 0) ||
          (viewId === APP_VIEW_SENSORS && sensors.length === 0)
        }
        style={{ padding: "0.55rem 0.95rem", borderRadius: "10px", border: `1px solid ${UI.border}`, background: "#ffffff", color: UI.text, cursor: "pointer", fontWeight: 700, fontSize: "0.72rem" }}
      >
        全选
      </button>
      <button
        onClick={() => clearSelectionForView(viewId)}
        style={{ padding: "0.55rem 0.95rem", borderRadius: "10px", border: `1px solid ${UI.border}`, background: UI.softBg, color: UI.text, cursor: "pointer", fontWeight: 700, fontSize: "0.72rem" }}
      >
        清空选择
      </button>
    </>
  );

  const navigateToView = (nextView) => {
    // 切换左侧导航页时，同时更新 URL hash 和 React 状态。
    const normalized = LIBRARY_VIEW_SET.has(nextView) ? nextView : APP_VIEW_CHAT;
    const nextHash = hashForView(normalized);
    if (typeof window !== "undefined" && window.location.hash !== nextHash) {
      window.location.hash = nextHash;
    }
    setCurrentView(normalized);
  };

  const loadUserLibraries = async (sessionId) => {
    const [docResult, imageResult, videoResult, sensorResult, graphStatusResult, messageResult] = await Promise.all([
      fetchDocumentsFromBackend(sessionId).catch(() => ({ documents: [] })),
      fetchImagesFromBackend(sessionId).catch(() => ({ images: [] })),
      fetchVideosFromBackend(sessionId).catch(() => ({ videos: [] })),
      fetchSensorsFromBackend(sessionId).catch(() => ({ records: [] })),
      fetchKnowledgeGraphStatus(sessionId).catch(() => ({ build_status: { state: "idle", message: "" } })),
      fetchMessagesFromBackend(sessionId).catch(() => ({ messages: [] })),
    ]);

    const nextDocs = (docResult.documents || []).map((item) => ({
      document_id: item.document_id,
      name: item.file_name,
      charCount: item.char_count || 0,
      chunkCount: item.chunk_count || 0,
      sizeMB: item.size_bytes ? (Number(item.size_bytes) / 1024 / 1024).toFixed(2) : "--",
      graphNodeCount: 0,
      graphRelationCount: 0,
    }));
    const nextImages = Array.isArray(imageResult.images) ? imageResult.images : [];
    const nextVideos = Array.isArray(videoResult.videos) ? videoResult.videos : [];
    const nextSensors = Array.isArray(sensorResult.records) ? sensorResult.records : [];
    setDocs(nextDocs);
    setImages(nextImages);
    setVideos(nextVideos);
    setSensors(nextSensors);
    setGraphBuildStatus(graphStatusResult.build_status || { state: "idle", message: "" });
    syncSelectedIds(nextDocs, setSelectedDocIds, (doc) => doc.document_id);
    syncSelectedIds(nextImages, setSelectedImageIds, (img) => img.image_id);
    syncSelectedIds(nextVideos, setSelectedVideoIds, (video) => video.video_id);
    syncSelectedIds(nextSensors, setSelectedSensorIds, (sensor) => sensor.sensor_id);

    const persistedMessages = Array.isArray(messageResult.messages) ? messageResult.messages : [];
    if (persistedMessages.length > 0) {
      setMessages(persistedMessages.map((item) => ({
        role: item.role,
        content: item.content,
        timestamp: item.timestamp ? new Date(item.timestamp) : new Date(),
      })));
    } else {
      setMessages([{
        role: "assistant",
    content: "您好！我是**煤矿应急救援决策知识问答AI智能体**，由中国矿业大学研发。\n\n可为您提供：\n- ⚡ **实时应急决策支持**\n- 🔍 **灾害风险智能识别**\n- 📋 **救援策略精准生成**\n- 🤝 **跨部门协同指挥建议**",
        timestamp: new Date(),
      }]);
    }
  };

  useEffect(() => {
    // 每次消息变化后，把聊天窗口滚动到底部。
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    // 监听浏览器 hash 变化，让刷新和前进后退也能同步页面视图。
    if (typeof window === "undefined") return undefined;
    const syncViewFromHash = () => {
      setCurrentView(parseViewFromHash(window.location.hash));
    };
    syncViewFromHash();
    window.addEventListener("hashchange", syncViewFromHash);
    return () => window.removeEventListener("hashchange", syncViewFromHash);
  }, []);

  useEffect(() => {
    // 页面初始化时，如果本地有 token，就尝试恢复登录态和历史资源。
    let active = true;
    const restore = async () => {
      const token = getStoredAuthToken();
      if (!token) {
        if (active) setAuthLoading(false);
        return;
      }
      try {
        const result = await fetchCurrentUserFromBackend();
        if (!active) return;
        setCurrentUser(result.user);
        sessionIdRef.current = result.user.session_id;
        await loadUserLibraries(result.user.session_id);
      } catch (err) {
        if (!active) return;
        setStoredAuthToken("");
        setCurrentUser(null);
        sessionIdRef.current = "";
      } finally {
        if (active) setAuthLoading(false);
      }
    };
    restore();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    setGraphOpen(graphViewActive);
    if (!graphViewActive) {
      setSelectedGraphNode(null);
    }
  }, [graphViewActive]);

  useEffect(() => {
    if (!graphOpen || !graphViewportRef.current) return undefined;
    const el = graphViewportRef.current;
    const updateSize = () => {
      const rect = el.getBoundingClientRect();
      setGraphViewportSize({
        width: Math.max(320, Math.floor(rect.width || 880)),
        height: Math.max(320, Math.floor(rect.height || 620)),
      });
    };
    updateSize();
    const observer = new ResizeObserver(() => updateSize());
    observer.observe(el);
    return () => observer.disconnect();
  }, [graphOpen]);

  useEffect(() => {
    // 图谱构建进行中时，定时轮询构建状态。
    if (!["running", "queued"].includes(graphBuildStatus.state)) return undefined;
    const timer = setInterval(async () => {
      try {
        const result = await fetchKnowledgeGraphStatus(sessionIdRef.current);
        if (!result.build_status) return;
        setGraphBuildStatus(result.build_status);
        if (result.build_status.state === "failed") {
          clearInterval(timer);
          setGraphGenerating(false);
          setGraphLoading(false);
          setGraphError(result.build_status.error || "知识图谱构建失败");
        }
        if (result.build_status.state === "completed") {
          clearInterval(timer);
          setGraphGenerating(false);
          graphQueryCacheRef.current.clear();
          graphLayoutReadyRef.current = false;
          graphLoadedSessionRef.current = "";
          if (!graphLoadingStoppedRef.current) {
            setGraphData(emptyGraphData());
          }
          setGraphLoading(false);
          setGraphFocusedKey(v => v + 1);
        }
      } catch (err) {
        clearInterval(timer);
        setGraphGenerating(false);
        setGraphLoading(false);
        setGraphError(err.message);
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [graphBuildStatus.state]);

  useEffect(() => {
    // 进入文档库页时，再同步一次文档列表。
    if (currentView !== APP_VIEW_DOCUMENTS) return;
    let active = true;
    fetchDocumentsFromBackend(sessionIdRef.current)
      .then((result) => {
        if (!active) return;
        setDocs((prev) => {
          const byId = new Map(prev.map((item) => [item.document_id, item]));
          const nextDocs = (result.documents || []).map((item) => {
            const existing = byId.get(item.document_id) || {};
            return {
              ...existing,
              document_id: item.document_id,
              name: item.file_name,
              charCount: item.char_count || 0,
              chunkCount: item.chunk_count || 0,
              sizeMB: existing.sizeMB || "--",
              graphNodeCount: existing.graphNodeCount || 0,
              graphRelationCount: existing.graphRelationCount || 0,
            };
          });
          syncSelectedIds(nextDocs, setSelectedDocIds, (doc) => doc.document_id);
          return nextDocs;
        });
      })
      .catch(() => {});
    return () => { active = false; };
  }, [currentView]);

  useEffect(() => {
    // 进入传感器页时，再同步一次最新传感器状态。
    if (currentView !== APP_VIEW_SENSORS) return;
    let active = true;
    fetchSensorsFromBackend(sessionIdRef.current)
      .then((result) => {
        if (!active) return;
        const nextSensors = Array.isArray(result.records) ? result.records : [];
        setSensors(nextSensors);
        syncSelectedIds(nextSensors, setSelectedSensorIds, (sensor) => sensor.sensor_id);
      })
      .catch(() => {});
    return () => { active = false; };
  }, [currentView]);

  useEffect(() => {
    // 图谱页第一次打开且图谱已构建完成时，自动加载图谱数据。
    if (!graphViewActive) return;
    if (graphBuildStatus.state !== "completed") return;
    if (graphLoading) return;
    if (graphData.nodes.length > 0 || graphData.links.length > 0) return;
    const load = async () => {
      await loadKnowledgeGraph(graphKeyword);
    };
    load();
  }, [graphViewActive, graphBuildStatus.state, graphKeyword, graphLoading, graphData.nodes.length, graphData.links.length]);

  const detectAlertLevel = (text) => {
    if (["爆炸", "火灾", "突水", "被困", "伤亡", "紧急", "危急"].some(w => text.includes(w))) return "red";
    if (["超标", "异常", "警告", "预警", "风险"].some(w => text.includes(w))) return "orange";
    return null;
  };

  const simulateAgents = () => {
    [["knowledge"], ["knowledge","perception"], ["knowledge","perception","decision"],
     ["knowledge","perception","decision","coordination"], ["decision","coordination"], ["coordination"], []
    ].forEach((a, i) => setTimeout(() => setActiveAgents(a), i * 600));
  };

  const handleUpload = async (e) => {
    // 处理规程文档上传。
    // 上传成功后会同步更新文档库列表和聊天区提示消息。
    const files = Array.from(e.target.files);
    if (!files.length) return;
    setUploading(true);
    for (const file of files) {
      try {
        const sizeMB = (file.size / 1024 / 1024).toFixed(2);
        const result = await uploadDocumentToBackend(file, sessionIdRef.current);

        setDocs(prev => [...prev.filter(d => d.document_id !== result.document_id && d.name !== file.name), {
          document_id: result.document_id,
          name: result.file_name || file.name,
          sizeMB,
          charCount: result.char_count || 0,
          chunkCount: result.chunk_count || 0,
          graphNodeCount: result.knowledge_graph?.node_count || 0,
          graphRelationCount: result.knowledge_graph?.relation_count || 0,
        }]);
        setSelectedDocIds(prev => (prev.includes(result.document_id) ? prev : [...prev, result.document_id]));
        if (result.knowledge_graph?.build_status) {
          graphQueryCacheRef.current.clear();
          graphLayoutReadyRef.current = false;
          graphLoadedSessionRef.current = "";
          setGraphData(emptyGraphData());
          setSelectedGraphNode(null);
          setGraphError("");
          setGraphBuildStatus(result.knowledge_graph.build_status);
          const latest = await fetchKnowledgeGraphStatus(sessionIdRef.current).catch(() => null);
          if (latest?.build_status) {
            setGraphBuildStatus(latest.build_status);
          }
        }
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `📄 已上传《**${result.file_name || file.name}**》（${sizeMB} MB · ${(result.char_count || 0).toLocaleString()} 字符 · ${result.chunk_count || 0} 个向量检索块）\n\n文档已入库。若需要图谱，请前往知识图谱库点击“生成知识图谱”。`,
          timestamp: new Date(),
        }]);
      } catch (err) {
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `⚠️ 文档《${file.name}》上传失败：${err.message}`,
          timestamp: new Date(),
        }]);
      }
    }
    setUploading(false);
    e.target.value = "";
  };

  // 处理图片上传
  const handleTriplesUpload = async (e) => {
    // 处理三元组 JSON 上传，直接补充知识图谱。
    const files = Array.from(e.target.files);
    if (!files.length) return;
    setUploading(true);
    for (const file of files) {
      try {
        const result = await uploadTriplesToBackend(file, sessionIdRef.current);
        graphQueryCacheRef.current.clear();
        graphLayoutReadyRef.current = false;
        graphLoadedSessionRef.current = "";
        setGraphData(emptyGraphData());
        setSelectedGraphNode(null);
        setGraphError("");
        setGraphBuildStatus(result.knowledge_graph?.build_status || {
          state: "completed",
          progress_percent: 100,
          node_count: result.node_count || 0,
          relation_count: result.relation_count || 0,
        });
        setGraphOpen(true);
        const data = await fetchKnowledgeGraph(sessionIdRef.current, "");
        const nextGraphData = graphPayloadForView(data, { scope: "full" });
        setGraphData(nextGraphData);
        graphQueryCacheRef.current.set(`${sessionIdRef.current}::`, nextGraphData);
        graphLoadedSessionRef.current = sessionIdRef.current;
        setGraphFocusedKey(v => v + 1);
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `已导入三元组文件 **${result.file_name || file.name}**，写入 ${result.node_count || 0} 个节点、${result.relation_count || 0} 条关系。`,
          timestamp: new Date(),
        }]);
      } catch (err) {
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `三元组文件 **${file.name}** 导入失败：${err.message}`,
          timestamp: new Date(),
        }]);
      }
    }
    setUploading(false);
    e.target.value = "";
  };

  const handleGenerateKnowledgeGraph = async () => {
    // 手动触发知识图谱重建。真正的构建过程在后端异步完成。
    if (docs.length === 0 || graphGenerating || ["running", "queued"].includes(graphBuildStatus.state)) {
      return;
    }
    setGraphGenerating(true);
    setGraphOpen(true);
    setGraphError("");
    setGraphLoading(true);
    graphQueryCacheRef.current.clear();
    graphLayoutReadyRef.current = false;
    graphLoadedSessionRef.current = "";
    setGraphData(emptyGraphData());
    setSelectedGraphNode(null);
    try {
      const result = await rebuildKnowledgeGraph(sessionIdRef.current);
      if (result.build_status) {
        setGraphBuildStatus(result.build_status);
      }
      setMessages(prev => [...prev, {
        role: "assistant",
        content: "🧠 已提交知识图谱生成任务，可在知识图谱库查看构建进度。",
        timestamp: new Date(),
      }]);
    } catch (err) {
      setGraphLoading(false);
      setGraphError(err.message);
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `⚠️ 知识图谱生成失败：${err.message}`,
        timestamp: new Date(),
      }]);
    } finally {
      setGraphGenerating(false);
    }
  };

  const handleImageUpload = async (e) => {
    const files = Array.from(e.target.files);
    if (!files.length) return;
    setImageUploading(true);
    
    for (const file of files) {
      try {
        if (!file.type.startsWith("image/")) {
          throw new Error("仅支持图片格式");
        }
        const result = await uploadImageToBackend(file, sessionIdRef.current);
        setImages(prev => [
          ...prev.filter(img => img.image_id !== result.image_id && img.name !== result.name),
          result,
        ]);
        setSelectedImageIds(prev => (prev.includes(result.image_id) ? prev : [...prev, result.image_id]));
        setMessages(prev => [...prev, {
          role: "assistant",
          content: result.summary_text
            ? `📸 已上传并分析图片《**${result.name}**》（${result.sizeMB} MB）\n\n${result.summary_text}`
            : `📸 已上传图片《**${result.name}**》（${result.sizeMB} MB）`,
          timestamp: new Date(),
        }]);
      } catch (err) {
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `⚠️ 图片《${file.name}》上传失败：${err.message}` ,
          timestamp: new Date(),
        }]);
      }
    }
    setImageUploading(false);
    e.target.value = "";
  };

  // 处理视频上传并自动分析
  const handleVideoUpload = async (e) => {
    const files = Array.from(e.target.files);
    if (!files.length) return;
    setVideoUploading(true);

    for (const file of files) {
      try {
        if (!file.type.startsWith("video/")) {
          throw new Error("仅支持视频格式");
        }
        const result = await uploadVideoToBackend(file, sessionIdRef.current);
        setVideos(prev => [
          ...prev.filter(v => v.video_id !== result.video_id && v.name !== result.name),
          result,
        ]);
        setSelectedVideoIds(prev => (prev.includes(result.video_id) ? prev : [...prev, result.video_id]));
        setMessages(prev => [...prev, {
          role: "assistant",
          content: result.summary_text || `🎬 已分析视频《**${result.name}**》`,
          timestamp: new Date(),
        }]);
      } catch (err) {
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `⚠️ 视频《${file.name}》分析失败：${err.message}`,
          timestamp: new Date(),
        }]);
      }
    }

    setVideoUploading(false);
    e.target.value = "";
  };
  const applySensorRecords = async (records) => {
    // 把传感器记录推到后端，并用后端返回的最新状态覆盖前端本地缓存。
    const result = await pushSensorsToBackend(records, sessionIdRef.current);
    const latestRecords = Array.isArray(result.latest_records) ? result.latest_records : [];
    setSensors(latestRecords);
    setSelectedSensorIds((prev) => {
      const previousSet = new Set(prev);
      const nextIds = latestRecords.map((item) => String(item.sensor_id || ""));
      const keptIds = nextIds.filter((id) => previousSet.has(id));
      const addedIds = nextIds.filter((id) => !previousSet.has(id));
      return [...keptIds, ...addedIds];
    });
    setMessages(prev => [...prev, {
      role: "assistant",
      content: `📡 已接入 ${latestRecords.length} 条传感器数据。\n\n${latestRecords.slice(0, 4).map(item => `- ${item.name || item.sensor_id}：${item.value_text || item.value || "未知"}${item.unit || ""}（${item.status || "状态未知"}）`).join("\n")}`,
      timestamp: new Date(),
    }]);
    return latestRecords;
  };

  const handleSensorSubmit = async () => {
    // 处理手工粘贴 JSON 的传感器录入。
    try {
      const records = JSON.parse(sensorInput);
      if (!Array.isArray(records) || records.length === 0) {
        throw new Error("请提供非空的传感器数组");
      }
      await applySensorRecords(records);
      setSensorDialogOpen(false);
    } catch (err) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `⚠️ 传感器数据接入失败：${err.message}`,
        timestamp: new Date(),
      }]);
    }
  };

  const handleSensorFileUpload = async (e) => {
    // 处理传感器 JSON 文件导入。
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    for (const file of files) {
      try {
        const text = await file.text();
        const records = JSON.parse(text);
        if (!Array.isArray(records) || records.length === 0) {
          throw new Error("传感器 JSON 文件必须是非空数组");
        }
        await applySensorRecords(records);
      } catch (err) {
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `⚠️ 传感器文件《${file.name}》导入失败：${err.message}`,
          timestamp: new Date(),
        }]);
      }
    }
    e.target.value = "";
  };

  const handleSensorClear = async () => {
    // 清空当前会话中的传感器数据。
    try {
      await clearSensorsFromBackend(sessionIdRef.current);
      setSensors([]);
      setSelectedSensorIds([]);
      setMessages(prev => [...prev, {
        role: "assistant",
        content: "📡 当前会话的传感器数据已清空。",
        timestamp: new Date(),
      }]);
    } catch (err) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `⚠️ 传感器数据清空失败：${err.message}`,
        timestamp: new Date(),
      }]);
    }
  };

  // 汇总图片识别结果，优先复用上传阶段已缓存的摘要
  const analyzeImageEvidence = async () => {
    // 汇总当前会话所有图片证据。
    // 如果上传阶段已经分析过，就优先复用缓存，避免重复请求。
    if (images.length === 0) return { summaryText: "", evidence: [], usedCached: false };

    try {
      const cachedSummaries = images
        .map((img) => String(img.summary_text || "").trim())
        .filter(Boolean);
      const cachedEvidence = images.flatMap((img) => Array.isArray(img.evidence) ? img.evidence : []);
      if (cachedSummaries.length > 0 || cachedEvidence.length > 0) {
        return {
          summaryText: cachedSummaries.length > 0 ? `📸 现场图片识别：\n${cachedSummaries.join("\n")}` : "",
          evidence: cachedEvidence,
          usedCached: true,
        };
      }

      let lines = [];
      let evidence = [];
      for (const img of images.slice(0, 6)) {
        try {
          const resp = await fetch(`${BACKEND_BASE_URL}/api/image-analyze`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              image_base64: img.base64,
              image_name: img.name
            })
          });

          if (resp.ok) {
            const data = await resp.json();
            if (data.result && data.result.length > 0) {
              const summary = String(data.summary_text || "").trim();
              const keywords = Array.isArray(data.keywords)
                ? data.keywords.filter(Boolean)
                : data.result.slice(0, 3).map(r => r.keyword || r.class_name).filter(Boolean);
              const line = summary || `【${img.name}】识别结果：${keywords.join("、")}`;
              lines.push(line);
              evidence.push({
                image_name: img.name,
                summary: summary || keywords.join("、"),
                source_type: "image_analysis"
              });
            }
          }
        } catch (err) {
          console.warn(`图片${img.name}识别失败:`, err);
        }
      }
      return {
        summaryText: lines.length > 0 ? `📸 现场图片识别：\n${lines.join("\n")}` : "",
        evidence,
        usedCached: false,
      };
    } catch (err) {
      console.warn("图片识别调用失败:", err);
      return { summaryText: "", evidence: [], usedCached: false };
    }
  };

  const analyzeSelectedImageEvidence = async (selectedImages) => {
    if (selectedImages.length === 0) return { summaryText: "", evidence: [], usedCached: true };

    try {
      const cachedSummaries = selectedImages
        .map((img) => String(img.summary_text || "").trim())
        .filter(Boolean);
      const cachedEvidence = selectedImages.flatMap((img) => Array.isArray(img.evidence) ? img.evidence : []);
      if (cachedSummaries.length > 0 || cachedEvidence.length > 0) {
        return {
          summaryText: cachedSummaries.length > 0 ? `📸 现场图片识别：\n${cachedSummaries.join("\n")}` : "",
          evidence: cachedEvidence,
          usedCached: true,
        };
      }

      let lines = [];
      let evidence = [];
      for (const img of selectedImages.slice(0, 6)) {
        try {
          const resp = await fetch(`${BACKEND_BASE_URL}/api/image-analyze`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              image_base64: img.base64,
              image_name: img.name,
            })
          });

          if (resp.ok) {
            const data = await resp.json();
            if (data.result && data.result.length > 0) {
              const summary = String(data.summary_text || "").trim();
              const keywords = Array.isArray(data.keywords)
                ? data.keywords.filter(Boolean)
                : data.result.slice(0, 3).map(r => r.keyword || r.class_name).filter(Boolean);
              const line = summary || `【${img.name}】识别结果：${keywords.join("、")}`;
              lines.push(line);
              evidence.push({
                image_name: img.name,
                summary: summary || keywords.join("、"),
                source_type: "image_analysis"
              });
            }
          }
        } catch (err) {
          console.warn(`图片${img.name}识别失败:`, err);
        }
      }
      return {
        summaryText: lines.length > 0 ? `📸 现场图片识别：\n${lines.join("\n")}` : "",
        evidence,
        usedCached: false,
      };
    } catch (err) {
      console.warn("图片识别调用失败:", err);
      return { summaryText: "", evidence: [], usedCached: false };
    }
  };

  const handleAuthSubmit = async (e) => {
    e?.preventDefault?.();
    setAuthSubmitting(true);
    setAuthError("");
    try {
      const username = String(authForm.username || "").trim();
      const password = String(authForm.password || "");
      if (!username || !password) {
        throw new Error("请输入用户名和密码。");
      }
      if (authMode === "register" && password !== authForm.confirmPassword) {
        throw new Error("两次输入的密码不一致。");
      }
      const result = authMode === "register"
        ? await registerToBackend(username, password)
        : await loginToBackend(username, password);
      setStoredAuthToken(result.token || "");
      setCurrentUser(result.user || null);
      sessionIdRef.current = result.user?.session_id || "";
      await loadUserLibraries(sessionIdRef.current);
      setAuthForm({ username: "", password: "", confirmPassword: "" });
      navigateToView(APP_VIEW_CHAT);
    } catch (err) {
      setAuthError(err.message || "登录失败");
    } finally {
      setAuthSubmitting(false);
      setAuthLoading(false);
    }
  };

  const handleLogout = async () => {
    try {
      await logoutFromBackend();
    } catch {}
    setStoredAuthToken("");
    setCurrentUser(null);
    sessionIdRef.current = "";
    setDocs([]);
    setImages([]);
    setVideos([]);
    setSensors([]);
    setSelectedDocIds([]);
    setSelectedImageIds([]);
    setSelectedVideoIds([]);
    setSelectedSensorIds([]);
    setGraphData(emptyGraphData());
    setGraphBuildStatus({ state: "idle", message: "" });
    setMessages([{
      role: "assistant",
      content: "请先登录后再查看历史知识库。",
      timestamp: new Date(),
    }]);
  };

  const removeUploadedImage = async (image) => {
    try {
      await removeImageFromBackend(image.image_id, sessionIdRef.current);
      setImages(prev => prev.filter(item => item.image_id !== image.image_id));
      setSelectedImageIds(prev => prev.filter(id => id !== image.image_id));
    } catch (err) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `⚠️ 图片《${image.name}》删除失败：${err.message}`,
        timestamp: new Date(),
      }]);
    }
  };

  const removeUploadedVideo = async (video) => {
    try {
      await removeVideoFromBackend(video.video_id, sessionIdRef.current);
      setVideos(prev => prev.filter(item => item.video_id !== video.video_id));
      setSelectedVideoIds(prev => prev.filter(id => id !== video.video_id));
    } catch (err) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `⚠️ 视频《${video.name}》删除失败：${err.message}`,
        timestamp: new Date(),
      }]);
    }
  };

  const removeUploadedSensor = async (sensor) => {
    try {
      const result = await removeSensorFromBackend(sensor.sensor_id, sessionIdRef.current);
      const nextSensors = Array.isArray(result.records) ? result.records : [];
      setSensors(nextSensors);
      setSelectedSensorIds(prev => prev.filter(id => id !== sensor.sensor_id));
    } catch (err) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `⚠️ 传感器《${sensor.name || sensor.sensor_id}》删除失败：${err.message}`,
        timestamp: new Date(),
      }]);
    }
  };

  const clearCurrentConversation = () => {
    setMessages([{
      role: "assistant",
      content: "您好！我是**煤矿应急救援决策知识问答AI智能体**，由中国矿业大学研发。\n\n可为您提供：\n- ⚡ **实时应急决策支持**\n- 🔍 **灾害风险智能识别**\n- 📋 **救援策略精准生成**\n- 🤝 **跨部门协同指挥建议**",
      timestamp: new Date(),
    }]);
    setInput("");
    setActiveAgents([]);
    setAlertLevel(null);
  };
  const buildConversationHistory = (messageList) => {
    // 从消息列表里提取真正需要发给后端的历史对话，
    // 过滤掉上传提示、分析提示这类不适合当上下文的系统消息。
    return messageList
      .filter(m => ["user", "assistant"].includes(m.role))
      .filter(m => {
        const content = String(m.content || "");
        return !content.startsWith("📄 已加载") && !content.startsWith("📄 已上传") && !content.startsWith("🗑️ 已移除") && !content.startsWith("📸 正在分析") && !content.startsWith("📸 已上传") && !content.startsWith("🎬 正在分析") && !content.startsWith("🎬 已分析") && !content.startsWith("🎬 视频") && !content.startsWith("📡 已接入");
      })
      .slice(-MAX_HISTORY_MESSAGES)
      .map(m => ({ role: m.role, content: String(m.content || "").replace(/\*\*/g, "") }));
  };

  const sendMessage = async (text) => {
    // 前端问答主链路：
    // 1. 先写入用户消息；
    // 2. 再整理图片/视频/传感器/文档等证据；
    // 3. 组装请求发给后端；
    // 4. 最后把回答和解释信息渲染出来。
    const userText = text || input.trim();
    if (!userText || loading) return;
    const level = detectAlertLevel(userText);
    setAlertLevel(level);
    if (level) setTimeout(() => setAlertLevel(null), 5000);

    const newMessages = [...messages, { role: "user", content: userText, timestamp: new Date() }];
    setMessages(newMessages);
    setInput("");
    setLoading(true);
    simulateAgents();

    const selectedDocIdSet = new Set(selectedDocIds.map((id) => String(id)));
    const selectedImageIdSet = new Set(selectedImageIds.map((id) => String(id)));
    const selectedVideoIdSet = new Set(selectedVideoIds.map((id) => String(id)));
    const selectedSensorIdSet = new Set(selectedSensorIds.map((id) => String(id)));
    const selectedImages = images.filter((img) => selectedImageIdSet.has(String(img.image_id || "")));
    const selectedVideos = videos.filter((video) => selectedVideoIdSet.has(String(video.video_id || "")));
    const selectedSensors = sensors.filter((sensor) => selectedSensorIdSet.has(String(sensor.sensor_id || "")));

    // 如果有图片，先汇总已缓存的识别结果
    let imageSummaryText = "";
    let imageEvidence = [];
    if (selectedImages.length > 0) {
      const imageAnalysis = await analyzeSelectedImageEvidence(selectedImages);
      imageSummaryText = imageAnalysis.summaryText || "";
      imageEvidence = imageAnalysis.evidence || [];
      if (!imageAnalysis.usedCached) {
        setMessages(prev => [...prev, {
          role: "assistant",
          content: "📸 正在分析本次勾选的图片...",
          timestamp: new Date(),
        }]);
      }
      if (imageSummaryText && !imageAnalysis.usedCached) {
        setMessages(prev => [...prev, {
          role: "assistant",
          content: imageSummaryText,
          timestamp: new Date(),
        }]);
      }
    }

    const videoEvidence = selectedVideos.flatMap(v => Array.isArray(v.evidence) ? v.evidence : []);

    const history = buildConversationHistory(newMessages);

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 180000);

      const res = await apiFetch(CHAT_API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: userText,
          session_id: sessionIdRef.current,
          history,
          selected_document_ids: docs
            .filter((doc) => selectedDocIdSet.has(String(doc.document_id || "")))
            .map((doc) => doc.document_id),
          evidence: {
            images: [...imageEvidence, ...videoEvidence],
            sensors: selectedSensors,
          },
          options: {
            use_session_memory: true,
            use_retrieval_evidence: selectedDocIdSet.size > 0,
            use_sensor_evidence: selectedSensors.length > 0,
          },
        }),
        signal: controller.signal
      });

      clearTimeout(timeoutId);

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.error || `API错误 ${res.status}: ${res.statusText}`);
      }

      const reply = data.reply || "无响应";
      const selected = Array.isArray(data.selected_agents) ? data.selected_agents : [];
      setActiveAgents(selected);

      setMessages(prev => [...prev, {
        role: "assistant",
        content: reply,
        timestamp: new Date(),
        meta: {
          selected_agents: selected,
          route_mode: data.route_mode,
          route_reason: data.route_reason,
          memory_used: data.memory_used,
          evidence_used: data.evidence_used,
          risk_assessment: data.risk_assessment,
          kg_used: data.kg_used,
          source_fusion: data.source_fusion,
        }
      }]);
    } catch (error) {
      let msg = "连接错误";
      if (error.name === "AbortError") msg = "请求超时（180秒）";
      else msg = `错误: ${error.message}`;
      setActiveAgents([]);

      setMessages(prev => [...prev, { role: "assistant", content: msg, timestamp: new Date() }]);
    }
    setLoading(false);
  };

  const removeUploadedDocument = async (doc) => {
    try {
      await removeDocumentFromBackend(doc.document_id, sessionIdRef.current);
      graphQueryCacheRef.current.clear();
      graphLayoutReadyRef.current = false;
      graphLoadedSessionRef.current = "";
      setGraphData(emptyGraphData());
      setDocs(prev => prev.filter(item => item.document_id !== doc.document_id));
      setSelectedDocIds(prev => prev.filter(id => id !== doc.document_id));
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `🗑️ 已移除文档《**${doc.name}**》及其后端向量索引。`,
        timestamp: new Date(),
      }]);
    } catch (err) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `⚠️ 文档《${doc.name}》移除失败：${err.message}`,
        timestamp: new Date(),
      }]);
    }
  };

  const mergeGraphData = (base, incoming) => {
    const nodeMap = new Map();
    for (const node of Array.isArray(base?.nodes) ? base.nodes : []) {
      if (node?.uid) nodeMap.set(node.uid, node);
    }
    for (const node of Array.isArray(incoming?.nodes) ? incoming.nodes : []) {
      if (!node?.uid) continue;
      const previous = nodeMap.get(node.uid) || {};
      nodeMap.set(node.uid, {
        ...previous,
        ...stripGraphFocusNode(node),
        x: previous.x,
        y: previous.y,
        vx: previous.vx,
        vy: previous.vy,
      });
    }

    const linkMap = new Map();
    for (const link of Array.isArray(base?.links) ? base.links : []) {
      const source = graphLinkEndpointUid(link.source);
      const target = graphLinkEndpointUid(link.target);
      const key = link.id || `${source}|${target}|${link.relation || ""}|${link.condition || ""}`;
      if (key) linkMap.set(key, { ...link, source, target });
    }
    for (const link of Array.isArray(incoming?.links) ? incoming.links : []) {
      const source = graphLinkEndpointUid(link.source);
      const target = graphLinkEndpointUid(link.target);
      const key = link.id || `${source}|${target}|${link.relation || ""}|${link.condition || ""}`;
      if (key) linkMap.set(key, { ...link, source, target });
    }

    return {
      ...base,
      ...incoming,
      nodes: Array.from(nodeMap.values()),
      links: Array.from(linkMap.values()),
      stats: {
        ...(base?.stats || {}),
        ...(incoming?.stats || {}),
      },
    };
  };

  const currentGraphLayout = () => {
    const layout = new Map();
    const graph = forceGraphRef.current?.graphData?.();
    for (const node of Array.isArray(graph?.nodes) ? graph.nodes : []) {
      if (!node?.uid) continue;
      layout.set(node.uid, {
        x: node.x,
        y: node.y,
        vx: node.vx,
        vy: node.vy,
      });
    }
    return layout;
  };

  const loadKnowledgeGraph = async (keyword = graphKeyword) => {
    graphLoadingStoppedRef.current = false;
    const normalizedKeyword = keyword.trim();
    const cacheKey = `${sessionIdRef.current}::${normalizedKeyword}`;
    const fullCacheKey = `${sessionIdRef.current}::`;
    const layoutByUid = currentGraphLayout();
    const cachedFull = graphQueryCacheRef.current.get(fullCacheKey);
    const focusBaseGraph = (
      cachedFull
      || ((!graphData.localFocus && graphData.nodes.length > 0 && graphLoadedSessionRef.current === sessionIdRef.current) ? graphData : null)
    );
    if (normalizedKeyword && focusBaseGraph) {
      const localView = focusGraphLocally(focusBaseGraph, normalizedKeyword, layoutByUid);
      if (localView) {
        const nextGraphData = {
          ...localView,
          stats: {
            ...(localView.stats || {}),
            view_node_count: localView.nodes.length,
            view_relation_count: localView.links.length,
          },
        };
        setGraphData(nextGraphData);
        graphQueryCacheRef.current.set(cacheKey, nextGraphData);
        setSelectedGraphNode(null);
        setGraphLoading(false);
        setGraphError("");
        setGraphFocusedKey(v => v + 1);
        return;
      }
    }

    const cached = graphQueryCacheRef.current.get(cacheKey);
    const cachedIsEmpty = cached && (cached.nodes?.length || 0) === 0 && (cached.links?.length || 0) === 0;
    const completedWithResults = graphBuildStatus.state === "completed" && (
      Number(graphBuildStatus.node_count || 0) > 0 || Number(graphBuildStatus.relation_count || 0) > 0
    );
    if (cached && !(cachedIsEmpty && completedWithResults)) {
      setGraphData(cached);
      setSelectedGraphNode(null);
      setGraphLoading(false);
      setGraphError("");
      setGraphFocusedKey(v => v + 1);
      return;
    }

    if (!normalizedKeyword) {
      if (cachedFull) {
        setGraphData(cachedFull);
        setSelectedGraphNode(null);
        setGraphLoading(false);
        setGraphError("");
        setGraphFocusedKey(v => v + 1);
        return;
      }
    }
    graphPreviousViewRef.current = {
      graphData,
      graphKeyword,
      selectedGraphNode,
      graphError,
    };
    graphAbortControllerRef.current?.abort?.();
    const controller = new AbortController();
    graphAbortControllerRef.current = controller;
    setGraphLoading(true);
    setGraphError("");
    try {
      const data = await fetchKnowledgeGraph(sessionIdRef.current, normalizedKeyword, { signal: controller.signal });
      const fetchedGraphData = graphPayloadForView(data, { scope: normalizedKeyword ? "query" : "full" });
      let nextGraphData = fetchedGraphData;
      if (normalizedKeyword && focusBaseGraph) {
        const merged = mergeGraphData(focusBaseGraph, fetchedGraphData);
        nextGraphData = focusGraphLocally(merged, normalizedKeyword, layoutByUid) || fetchedGraphData;
      } else if (!normalizedKeyword) {
        graphLoadedSessionRef.current = sessionIdRef.current;
        graphQueryCacheRef.current.set(fullCacheKey, fetchedGraphData);
      }
      setGraphData(nextGraphData);
      graphQueryCacheRef.current.set(cacheKey, nextGraphData);
      setSelectedGraphNode(null);
      setGraphFocusedKey(v => v + 1);
    } catch (err) {
      if (err?.name === "AbortError") {
        return;
      }
      setGraphData(emptyGraphData());
      setSelectedGraphNode(null);
      setGraphError(err.message);
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `⚠️ 知识图谱加载失败：${err.message}`,
        timestamp: new Date(),
      }]);
    } finally {
      if (graphAbortControllerRef.current === controller) {
        graphAbortControllerRef.current = null;
      }
      setGraphLoading(false);
    }
  };

  const openKnowledgeGraph = async () => {
    graphLoadingStoppedRef.current = false;
    navigateToView(APP_VIEW_GRAPH);
    if (graphData.nodes.length > 0 || graphData.links.length > 0 || graphError) {
      return;
    }
    const statusResult = await fetchKnowledgeGraphStatus(sessionIdRef.current).catch(() => null);
    if (statusResult?.build_status) {
      setGraphBuildStatus(statusResult.build_status);
      if (["queued", "running"].includes(statusResult.build_status.state)) {
        setGraphLoading(true);
        return;
      }
      if (statusResult.build_status.state === "completed") {
        graphLoadedSessionRef.current = graphLoadedSessionRef.current || sessionIdRef.current;
      }
    }
    await loadKnowledgeGraph(graphKeyword);
  };

  const resetKnowledgeGraphView = async () => {
    graphLoadingStoppedRef.current = false;
    setGraphKeyword("");
    await loadKnowledgeGraph("");
  };

  const stopKnowledgeGraphLoading = () => {
    graphLoadingStoppedRef.current = true;
    graphAbortControllerRef.current?.abort?.();
    graphAbortControllerRef.current = null;
    const previous = graphPreviousViewRef.current;
    if (previous) {
      setGraphData(previous.graphData || emptyGraphData());
      setGraphKeyword(previous.graphKeyword || "");
      setSelectedGraphNode(previous.selectedGraphNode || null);
      setGraphError(previous.graphError || "");
      setGraphFocusedKey(v => v + 1);
    }
    setGraphLoading(false);
  };

  const closeKnowledgeGraph = () => {
    graphAbortControllerRef.current?.abort?.();
    graphAbortControllerRef.current = null;
    navigateToView(APP_VIEW_CHAT);
    setGraphLoading(false);
    setSelectedGraphNode(null);
    setGraphError("");
  };

  useEffect(() => {
    if (!graphViewActive) return;
    if (graphLoadingStoppedRef.current) return;
    if (graphLoading) return;
    if (graphData.nodes.length > 0 || graphData.links.length > 0 || graphError) return;
    openKnowledgeGraph().catch(() => {});
  }, [graphViewActive]);

  const handleGraphNodeClick = (node) => {
    setSelectedGraphNode(node);
  };

  const fmt = (text) => {
    return text.split(/(\*\*[^*]+\*\*)/).map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i} style={{ color: "#fbbf24" }}>{part.slice(2, -2)}</strong>;
      }
      return part.split("\n").map((line, j, arr) => (
        <span key={`${i}-${j}`}>
          {line.startsWith("- ") ? (
            <span style={{ display: "block", paddingLeft: "1rem", position: "relative" }}>
              <span style={{ position: "absolute", left: 0, color: "#4ade80" }}>▸</span>{line.slice(2)}
            </span>
          ) : line}
          {j < arr.length - 1 && <br />}
        </span>
      ));
    });
  };

  const fileIcon = (name) => name.endsWith(".pdf") ? "📕" : name.endsWith(".docx") ? "📘" : "📄";

  const nodeColor = (type) => ({
    document: "#22d3ee",
    clause: "#94a3b8",
    document_type: "#38bdf8",
    regulation: "#94a3b8",
    article: "#64748b",
    chapter: "#38bdf8",
    hazard: "#f97316",
    condition: "#fbbf24",
    step: "#4ade80",
    role: "#60a5fa",
    risk: "#ef4444",
    symptom: "#14b8a6",
    parameter: "#fbbf24",
    sensor: "#38bdf8",
    action: "#4ade80",
    department: "#60a5fa",
    location: "#a78bfa",
    equipment: "#fb7185",
    stage: "#fb7185",
  }[type] || "#cbd5e1");

  const buildGraphData = (nodes, links) => {
    const safeNodes = Array.isArray(nodes) ? nodes : [];
    const visibleUids = new Set(safeNodes.map(node => node.uid));
    const safeLinks = dedupeGraphLinks((Array.isArray(links) ? links : []).filter(link => (
      visibleUids.has(link.source) && visibleUids.has(link.target)
    )));
    if (safeNodes.length === 0) {
      return { nodes: [], links: [] };
    }

    const graphNodes = safeNodes.map(node => ({
      ...node,
      id: node.uid,
      displayLabel: graphNodeDisplayLabel(node),
      color: node.isCenter ? "#ef4444" : node.isMatched ? "#f59e0b" : nodeColor(node.type),
      val: selectedGraphNode?.uid === node.uid ? 18 : node.isCenter ? 20 : node.isMatched ? 15 : node.type === "hazard" ? 13 : 9,
    }));
    const graphLinks = safeLinks.map(link => ({
      ...link,
      source: link.source,
      target: link.target,
    }));
    return { nodes: graphNodes, links: graphLinks };
  };

  const renderedGraph = useMemo(
    () => buildGraphData(graphData.nodes, graphData.links),
    [graphData.nodes, graphData.links, selectedGraphNode?.uid]
  );

  useEffect(() => {
    if (!graphOpen) return;
    if (!forceGraphRef.current) return;
    if (!graphData.nodes.length) return;
    if (graphData.localFocus && graphLayoutReadyRef.current) return;
    try {
      forceGraphRef.current.d3Force("charge")?.strength?.(-360);
      forceGraphRef.current.d3Force("link")?.distance?.(graphData.nodes.length > 90 ? 190 : 150);
      forceGraphRef.current.d3Force("center")?.strength?.(0.05);
      forceGraphRef.current.d3Alpha(graphLayoutReadyRef.current ? 0.22 : 0.55).d3ReheatSimulation();
      graphLayoutReadyRef.current = true;
    } catch (err) {
      console.warn("知识图谱布局初始化失败:", err);
    }
  }, [graphOpen, graphData.nodes.length, graphData.links.length, graphData.localFocus]);

  useEffect(() => {
    if (!graphOpen || !forceGraphRef.current || !graphData.nodes.length) return undefined;
    const timer = setTimeout(() => {
      try {
        const focusPoint = graphFocusPoint(graphData);
        if (focusPoint) {
          forceGraphRef.current.centerAt(focusPoint.x || 0, focusPoint.y || 0, 420);
          forceGraphRef.current.zoom(1.55, 420);
        } else {
          forceGraphRef.current.zoomToFit(520, 70);
        }
      } catch (err) {
        console.warn("知识图谱视角定位失败:", err);
      }
    }, 220);
    return () => clearTimeout(timer);
  }, [graphOpen, graphFocusedKey, graphData.centerUid, graphData.matchedUids]);

  const renderGraphDialog = (embedded = false) => {
    if (!embedded && !graphOpen) return null;
    const graph = renderedGraph;
    const stats = graphData.stats || {};
    const centerNode = graph.nodes.find(node => node.uid === graphData.centerUid);
    const centerLabel = centerNode ? graphNodeDisplayLabel(centerNode) : "";
    const selectedRelations = selectedGraphNode
      ? graph.links.filter(link => {
          const sourceId = typeof link.source === "string" ? link.source : link.source?.id;
          const targetId = typeof link.target === "string" ? link.target : link.target?.id;
          return sourceId === selectedGraphNode.uid || targetId === selectedGraphNode.uid;
        })
      : [];

    return (
      <div style={embedded ? { flex: 1, minHeight: 0, height: "100%", display: "flex", width: "100%" } : { position: "fixed", inset: 0, background: UI.overlay, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 320 }}>
        <div style={embedded ? { flex: 1, minHeight: 0, height: "100%", background: UI.cardBg, border: `1px solid ${UI.borderStrong}`, borderRadius: "16px", boxShadow: UI.shadow, display: "flex", flexDirection: "column", overflow: "hidden" } : { width: "min(1180px, 94vw)", height: "min(760px, 92vh)", background: UI.cardBg, border: `1px solid ${UI.borderStrong}`, borderRadius: "12px", boxShadow: UI.shadow, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ padding: "0.8rem 1rem", borderBottom: `1px solid ${UI.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.8rem", flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: "0.95rem", fontWeight: 800, color: UI.text }}>
                {graphKeyword.trim() ? `知识图谱检索：${graphKeyword.trim()}` : "完整知识图谱"}
              </div>
              <div style={{ fontSize: "0.65rem", color: UI.muted, marginTop: "0.15rem" }}>
                展示节点 {stats.view_node_count ?? graphData.nodes.length ?? 0} 个 · 展示关系 {stats.view_relation_count ?? graphData.links.length ?? 0} 条
                {centerLabel ? ` · 中心节点 ${centerLabel}` : ""}
                {(stats.node_count || stats.relation_count) ? `（后端保留溯源节点 ${stats.node_count || 0} 个、关系 ${stats.relation_count || 0} 条）` : ""}
              </div>
            </div>
            <div style={{ display: "flex", gap: "0.45rem", alignItems: "center", flex: "0 1 520px" }}>
              <input
                value={graphKeyword}
                onChange={e => setGraphKeyword(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") loadKnowledgeGraph(graphKeyword); }}
                placeholder="搜索节点或关键词，例如 瓦斯 / 透水 / 救护队"
                style={{ flex: 1, minWidth: 180, background: "#ffffff", border: `1px solid ${UI.border}`, borderRadius: "8px", color: UI.text, padding: "0.48rem 0.65rem", outline: "none", fontSize: "0.75rem" }}
              />
              <button onClick={() => loadKnowledgeGraph(graphKeyword)} disabled={graphLoading} style={{ minWidth: 62, padding: "0.48rem 0.78rem", borderRadius: "8px", border: `1px solid ${UI.borderStrong}`, background: "rgba(14,165,233,0.12)", color: UI.text, cursor: graphLoading ? "not-allowed" : "pointer", fontWeight: 700, fontSize: "0.72rem", whiteSpace: "nowrap", lineHeight: 1.1, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>{graphLoading ? "加载中" : "检索"}</button>
              <button onClick={stopKnowledgeGraphLoading} disabled={!graphLoading} style={{ minWidth: 84, padding: "0.48rem 0.78rem", borderRadius: "8px", border: `1px solid ${UI.border}`, background: graphLoading ? "#fff7ed" : "#ffffff", color: graphLoading ? "#9a3412" : UI.subtle, cursor: graphLoading ? "pointer" : "not-allowed", fontWeight: 700, fontSize: "0.72rem", whiteSpace: "nowrap", lineHeight: 1.1, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>停止加载</button>
              <button onClick={() => resetKnowledgeGraphView()} disabled={graphLoading || (!graphKeyword.trim() && !graphData.localFocus)} style={{ minWidth: 84, padding: "0.48rem 0.78rem", borderRadius: "8px", border: `1px solid ${UI.border}`, background: "#ffffff", color: (graphLoading || (!graphKeyword.trim() && !graphData.localFocus)) ? UI.subtle : UI.text, cursor: (graphLoading || (!graphKeyword.trim() && !graphData.localFocus)) ? "not-allowed" : "pointer", fontWeight: 700, fontSize: "0.72rem", whiteSpace: "nowrap", lineHeight: 1.1, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>返回全图</button>
              {!embedded ? (
                <button onClick={closeKnowledgeGraph} style={{ background: "none", border: "none", color: UI.subtle, cursor: "pointer", fontSize: "1.2rem", lineHeight: 1 }}>×</button>
              ) : null}
            </div>
          </div>

          <div style={{ padding: "0.55rem 1rem", borderBottom: `1px solid ${UI.border}`, display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ fontSize: "0.68rem", color: UI.muted }}>
              搜索框为空时展示完整图谱；输入关键词后只展示中心节点及其一跳邻居，点击节点只查看详情。
            </div>
          </div>

          <div style={{ flex: 1, display: "grid", gridTemplateColumns: "minmax(0, 1fr) 300px", minHeight: 0 }}>
            <div ref={graphViewportRef} style={{ position: "relative", overflow: "hidden", background: UI.graphBg }}>
              {graphLoading ? (
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: UI.subtle, fontSize: "0.82rem", textAlign: "center", lineHeight: 1.8 }}>
                  {graphBuildStatus.state === "queued" ? (
                    <div style={{ width: "min(420px, 82%)" }}>
                      <div style={{ marginBottom: "0.7rem", color: UI.text }}>图谱构建任务排队中…</div>
                      <div style={{ height: 10, background: "rgba(15,23,42,0.08)", borderRadius: 999, overflow: "hidden" }}>
                        <div style={{ width: "8%", height: "100%", background: "linear-gradient(90deg,#64748b,#22d3ee)", transition: "width 260ms ease" }} />
                      </div>
                      <div style={{ marginTop: "0.55rem", fontSize: "0.72rem", color: UI.subtle }}>
                        当前队列繁忙，稍后自动开始
                      </div>
                    </div>
                  ) : graphBuildStatus.state === "running" ? (
                    <div style={{ width: "min(420px, 82%)" }}>
                      <div style={{ marginBottom: "0.7rem", color: UI.text }}>正在用大模型抽取三元组并写入 Neo4j…</div>
                      <div style={{ height: 10, background: "rgba(15,23,42,0.08)", borderRadius: 999, overflow: "hidden" }}>
                        <div style={{ width: `${graphBuildStatus.progress_percent || 0}%`, height: "100%", background: "linear-gradient(90deg,#22d3ee,#4ade80)", transition: "width 260ms ease" }} />
                      </div>
                      <div style={{ marginTop: "0.55rem", fontSize: "0.72rem", color: UI.text }}>
                        {graphBuildStatus.current || 0}/{graphBuildStatus.total || 0} · {graphBuildStatus.progress_percent || 0}%
                      </div>
                    </div>
                  ) : <span style={{ color: UI.text }}>正在从 Neo4j 加载知识图谱…</span>}
                </div>
              ) : graphError ? (
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#b91c1c", fontSize: "0.8rem", textAlign: "center", lineHeight: 1.8, padding: "0 1.5rem" }}>
                  图谱加载失败
                  <br />
                  {graphError}
                </div>
              ) : graph.nodes.length === 0 ? (
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: UI.subtle, fontSize: "0.82rem", textAlign: "center", lineHeight: 1.8 }}>
                  当前没有可展示的图谱结果
                  <br />
                  先上传规程文档，或换一个关键词再检索
                </div>
              ) : (
                <ForceGraph2D
                  ref={forceGraphRef}
                  width={graphViewportSize.width}
                  height={graphViewportSize.height}
                  graphData={graph}
                  backgroundColor="transparent"
                  cooldownTicks={140}
                  nodeRelSize={6}
                  d3AlphaDecay={0.03}
                  d3VelocityDecay={0.22}
                  linkColor={() => "rgba(148,163,184,0.34)"}
                  linkWidth={(link) => link.duplicateCount > 1 ? 1.6 : 1}
                  nodeColor={(node) => node.color}
                  nodeVal={(node) => node.val}
                  nodeLabel={(node) => `${node.displayLabel || graphNodeDisplayLabel(node)}${node.type ? ` (${node.type})` : ""}`}
                  linkLabel={(link) => [link.relation_label, link.condition].filter(Boolean).join(" | ")}
                  nodeCanvasObjectMode={() => "after"}
                  nodeCanvasObject={(node, ctx, globalScale) => {
                    const label = String(node.displayLabel || graphNodeDisplayLabel(node) || "");
                    const radius = Math.sqrt(Math.max(node.val || 8, 1)) * 3.1;
                    if (node.isCenter || selectedGraphNode?.uid === node.uid) {
                      ctx.beginPath();
                      ctx.arc(node.x, node.y, radius + (node.isCenter ? 7 : 4), 0, 2 * Math.PI, false);
                      ctx.strokeStyle = node.isCenter ? "#ef4444" : "#0ea5e9";
                      ctx.lineWidth = node.isCenter ? 2.5 : 1.6;
                      ctx.stroke();
                    }
                    const fontSize = Math.max(8, 10 / globalScale);
                    ctx.font = `${node.isCenter ? "700 " : ""}${fontSize}px sans-serif`;
                    ctx.textAlign = "left";
                    ctx.textBaseline = "middle";
                    ctx.fillStyle = UI.text;
                    ctx.fillText(label.slice(0, node.isCenter ? 24 : 18), node.x + 8, node.y);
                  }}
                  linkCanvasObjectMode={() => "after"}
                  linkCanvasObject={(link, ctx, globalScale) => {
                    const start = link.source;
                    const end = link.target;
                    if (!start?.x || !end?.x) return;
                    const dx = end.x - start.x;
                    const dy = end.y - start.y;
                    const distance = Math.sqrt(dx * dx + dy * dy);
                    if (distance < 42 || graph.links.length > 180) return;
                    const midX = (start.x + end.x) / 2;
                    const midY = (start.y + end.y) / 2;
                    const label = String(link.relation_label || link.relation || "").slice(0, 10);
                    if (label) {
                      ctx.font = `${Math.max(7, 9 / globalScale)}px sans-serif`;
                      ctx.fillStyle = UI.text;
                      ctx.textAlign = "center";
                      ctx.fillText(label, midX, midY + 8);
                    }
                    if (link.condition && distance > 95 && graph.links.length <= 120) {
                      ctx.font = `${Math.max(7, 8 / globalScale)}px sans-serif`;
                      ctx.fillStyle = UI.text;
                      ctx.textAlign = "center";
                      ctx.fillText(String(link.condition).slice(0, 16), midX, midY - 7);
                    }
                  }}
                  onNodeClick={handleGraphNodeClick}
                />
              )}
            </div>

            <div style={{ borderLeft: `1px solid ${UI.border}`, padding: "0.8rem", overflowY: "auto", background: UI.softBg }}>
              <div style={{ fontSize: "0.75rem", color: UI.text, fontWeight: 800, marginBottom: "0.55rem" }}>图谱详情</div>
              {selectedGraphNode ? (
                <div style={{ display: "grid", gap: "0.45rem", fontSize: "0.68rem", color: UI.text, lineHeight: 1.6 }}>
                  <div style={{ fontSize: "0.86rem", color: selectedGraphNode.isCenter ? "#991b1b" : UI.text, fontWeight: 800 }}>{graphNodeDisplayLabel(selectedGraphNode)}</div>
                  <div><span style={{ color: UI.muted }}>类型：</span>{selectedGraphNode.type_label || selectedGraphNode.type}</div>
                  {selectedGraphNode.isCenter && <div style={{ color: "#991b1b" }}>当前搜索中心节点</div>}
                  {selectedGraphNode.text_excerpt && <div style={{ color: UI.muted, whiteSpace: "pre-wrap" }}>{selectedGraphNode.text_excerpt}</div>}
                  {Array.isArray(selectedGraphNode.sources) && selectedGraphNode.sources.length > 0 && (
                    <div>
                      <span style={{ color: UI.muted }}>来源：</span>
                      <div style={{ marginTop: "0.25rem", display: "grid", gap: "0.25rem" }}>
                        {selectedGraphNode.sources.slice(0, 5).map((source, idx) => (
                          <div key={`${source}-${idx}`} style={{ padding: "0.28rem 0.4rem", borderRadius: "6px", background: "#ffffff", border: `1px solid ${UI.border}`, color: UI.text }}>{source}</div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div style={{ marginTop: "0.4rem", color: UI.text, fontWeight: 800 }}>相邻关系</div>
                  {selectedRelations.length === 0 ? (
                    <div style={{ color: UI.subtle }}>暂无相邻关系</div>
                  ) : selectedRelations.slice(0, 10).map((rel, idx) => (
                    <div key={`${rel.id || idx}`} style={{ padding: "0.42rem 0.48rem", borderRadius: "7px", background: "#ffffff", border: `1px solid ${UI.border}` }}>
                      <span style={{ color: "#92400e" }}>{rel.head_label}</span>
                      <span style={{ color: UI.muted }}> → {rel.relation_label} → </span>
                      <span style={{ color: "#1e40af" }}>{rel.tail_label}</span>
                      {rel.source_ref && <div style={{ color: UI.subtle, marginTop: "0.15rem" }}>{rel.source_ref}</div>}
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ color: UI.subtle, fontSize: "0.7rem", lineHeight: 1.8 }}>
                  图谱已改为稳定视图：节点点击只用于查看来源和相邻关系，不再动态展开。
                  <div style={{ marginTop: "0.8rem", display: "flex", gap: "0.28rem", flexWrap: "wrap" }}>
                    {Object.entries({
                      hazard: "灾害",
                      condition: "条件",
                      step: "步骤",
                      role: "主体",
                      risk: "风险",
                      equipment: "设备",
                    }).map(([type, label]) => (
                      <span key={type} style={{ padding: "0.12rem 0.38rem", borderRadius: "999px", background: `${nodeColor(type)}22`, border: `1px solid ${nodeColor(type)}66`, color: nodeColor(type) }}>{label}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  };

  const renderMetaPanel = (meta) => {
    if (!meta) return null;
    const selectedAgents = Array.isArray(meta.selected_agents) ? meta.selected_agents : [];
    const risk = meta.risk_assessment || {};
    const evidence = meta.evidence_used || {};
    const memory = meta.memory_used || {};
    const kgUsed = meta.kg_used || {};
    const sourceFusion = meta.source_fusion || {};
    const matchedRelations = Array.isArray(kgUsed.matched_relations) ? kgUsed.matched_relations : [];
    const matchedNodes = Array.isArray(kgUsed.matched_nodes) ? kgUsed.matched_nodes : [];
    const riskSignals = Array.isArray(risk.signals_detected) ? risk.signals_detected : [];
    const docEvidence = Array.isArray(evidence.documents) ? evidence.documents : [];
    const imageEvidence = Array.isArray(evidence.images) ? evidence.images : [];
    const videoEvidenceCount = imageEvidence.filter(item => String(item.source_type || "").includes("video")).length;
    const stillImageEvidenceCount = imageEvidence.length - videoEvidenceCount;

    return (
      <details style={{ marginTop: "0.55rem", background: "rgba(255,255,255,0.72)", border: "1px solid rgba(15,23,42,0.10)", borderRadius: "8px", padding: "0.45rem 0.6rem" }}>
        <summary style={{ cursor: "pointer", color: "#0f172a", fontSize: "0.68rem", fontWeight: 700 }}>本次推理说明</summary>
        <div style={{ marginTop: "0.45rem", display: "grid", gap: "0.35rem", fontSize: "0.65rem", color: "#334155", lineHeight: 1.6 }}>
          <div><span style={{ color: "#0f172a" }}>路由方式：</span>{meta.route_mode || "未知"}</div>
          <div><span style={{ color: "#0f172a" }}>路由原因：</span>{meta.route_reason || "无"}</div>
          <div>
            <span style={{ color: "#0f172a" }}>激活角色：</span>
            {selectedAgents.length > 0 ? selectedAgents.join("、") : "无"}
          </div>
          <div>
            <span style={{ color: "#0f172a" }}>风险识别：</span>
            {risk.risk_level ? `${risk.risk_level}风险` : "未识别"}
            {Array.isArray(risk.risk_type_labels) && risk.risk_type_labels.length > 0 ? `（${risk.risk_type_labels.join("、")}）` : ""}
          </div>
          <div>
            <span style={{ color: "#0f172a" }}>证据使用：</span>
            文档 {docEvidence.length} 条，图片 {stillImageEvidenceCount} 条，视频 {videoEvidenceCount} 帧
          </div>
          <div>
            <span style={{ color: "#0f172a" }}>会话记忆：</span>
            {memory.history_messages || 0} 条历史消息，最终会话 {memory.session_history_messages || 0} 条
          </div>
          <div>
            <span style={{ color: "#0f172a" }}>图谱命中：</span>
            节点 {kgUsed.node_count || 0} 个，关系 {kgUsed.relation_count || 0} 条，相关关系 {matchedRelations.length} 条
          </div>
          <div>
            <span style={{ color: "#0f172a" }}>多源融合：</span>
            {sourceFusion.history_used ? "使用历史" : "未使用历史"}，文档 {sourceFusion.document_count || 0} 份，图像/视频证据 {sourceFusion.image_count || 0} 条
          </div>

          {docEvidence.length > 0 && (
            <div>
              <span style={{ color: "#0f172a" }}>文档证据：</span>
              <div style={{ marginTop: "0.18rem", display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                {docEvidence.map((doc, idx) => (
                  <span key={`${doc.doc_name || "doc"}-${idx}`} style={{ padding: "0.08rem 0.38rem", borderRadius: "999px", background: "#ecfdf5", border: "1px solid rgba(22,163,74,0.22)", color: "#0f172a" }}>
                    {(doc.doc_name || "未知文档")}{doc.chunk_id ? ` · ${doc.chunk_id}` : ""}
                  </span>
                ))}
              </div>
            </div>
          )}

          {imageEvidence.length > 0 && (
            <div>
              <span style={{ color: "#0f172a" }}>图片证据：</span>
              <div style={{ marginTop: "0.18rem", display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                {imageEvidence.map((img, idx) => (
                  <span key={`${img.image_name || "img"}-${idx}`} style={{ padding: "0.08rem 0.38rem", borderRadius: "999px", background: "#eff6ff", border: "1px solid rgba(59,130,246,0.22)", color: "#0f172a" }}>
                    {img.image_name || "未知图片"}{String(img.source_type || "") === "video_analysis" ? "（视频帧）" : ""}
                  </span>
                ))}
              </div>
            </div>
          )}

          {riskSignals.length > 0 && (
            <div>
              <span style={{ color: "#0f172a" }}>风险触发信号：</span>
              <div style={{ marginTop: "0.18rem", display: "grid", gap: "0.2rem" }}>
                {riskSignals.slice(0, 6).map((signal, idx) => (
                  <div key={`${signal.signal_id || "signal"}-${idx}`} style={{ color: "#475569" }}>
                    - {signal.signal_label || signal.signal_id || "未知信号"}
                    {signal.source ? `（来源：${signal.source}` : ""}
                    {signal.keywords ? `；命中：${signal.keywords}` : ""}
                    {signal.source ? "）" : ""}
                  </div>
                ))}
              </div>
            </div>
          )}

          {matchedNodes.length > 0 && (
            <div>
              <span style={{ color: "#0f172a" }}>命中实体：</span>
              <div style={{ marginTop: "0.18rem", display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                {matchedNodes.slice(0, 8).map((node) => (
                  <span key={node.id} style={{ padding: "0.08rem 0.38rem", borderRadius: "999px", background: "#faf5ff", border: "1px solid rgba(168,85,247,0.22)", color: "#0f172a" }}>
                    {node.label}{node.type ? ` · ${node.type}` : ""}
                  </span>
                ))}
              </div>
            </div>
          )}

          {matchedRelations.length > 0 && (
            <div>
              <span style={{ color: "#0f172a" }}>命中关系链：</span>
              <div style={{ marginTop: "0.18rem", display: "grid", gap: "0.2rem" }}>
                {matchedRelations.slice(0, 6).map((rel, idx) => (
                  <div key={`${rel.head_id || "h"}-${rel.tail_id || "t"}-${idx}`} style={{ color: "#334155", background: "#ffffff", border: "1px solid rgba(15,23,42,0.08)", borderRadius: "6px", padding: "0.28rem 0.42rem" }}>
                    <span style={{ color: "#92400e" }}>{rel.head_label || rel.head_id}</span>
                    <span style={{ color: "#475569" }}> → {rel.relation_label || rel.relation} → </span>
                    <span style={{ color: "#1e40af" }}>{rel.tail_label || rel.tail_id}</span>
                    {rel.source ? <span style={{ color: "#64748b" }}>（{rel.source}）</span> : null}
                  </div>
                ))}
              </div>
            </div>
          )}

          {risk.summary && (
            <div style={{ whiteSpace: "pre-wrap", color: "#475569" }}>
              <span style={{ color: "#0f172a" }}>风险摘要：</span>{risk.summary}
            </div>
          )}
          {kgUsed.summary && (
            <div style={{ whiteSpace: "pre-wrap", color: "#475569" }}>
              <span style={{ color: "#0f172a" }}>图谱摘要：</span>{kgUsed.summary}
            </div>
          )}
        </div>
      </details>
    );
  };

  const renderLibraryEmpty = (title, hint, actionLabel, onAction, disabled = false) => (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "2rem" }}>
      <div style={{ width: "min(560px, 100%)", borderRadius: "18px", border: `1px solid ${UI.border}`, background: UI.cardBg, padding: "2rem", textAlign: "center", boxShadow: UI.shadow }}>
        <div style={{ fontSize: "1rem", fontWeight: 800, color: UI.text }}>{title}</div>
        <div style={{ marginTop: "0.55rem", fontSize: "0.78rem", lineHeight: 1.9, color: UI.subtle }}>{hint}</div>
        {onAction ? (
          <button
            onClick={onAction}
            disabled={disabled}
            style={{ marginTop: "1rem", padding: "0.65rem 1rem", borderRadius: "10px", border: `1px dashed ${UI.borderStrong}`, background: "rgba(56,189,248,0.10)", color: disabled ? "#94a3b8" : UI.text, cursor: disabled ? "not-allowed" : "pointer", fontWeight: 700 }}
          >
            {actionLabel}
          </button>
        ) : null}
      </div>
    </div>
  );

  const renderChatPage = () => (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ flex: 1, overflowY: "auto", padding: "1.1rem 1.25rem", display: "flex", flexDirection: "column", gap: "0.9rem" }}>
        {messages.map((msg, i) => (
          <div key={i} style={{ display: "flex", justifyContent: msg.role === "user" ? "flex-end" : "flex-start", animation: "fadeUp 0.3s ease" }}>
            {msg.role === "assistant" && (
              <div style={{ width: 32, height: 32, borderRadius: "8px", flexShrink: 0, background: "linear-gradient(135deg,#4ade80,#22d3ee)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.9rem", marginRight: "0.6rem", marginTop: "0.2rem", boxShadow: "0 0 10px rgba(74,222,128,0.3)" }}>⛏</div>
            )}
            <div style={{ maxWidth: "76%", background: msg.role === "user" ? "linear-gradient(135deg,#3b82f6,#2563eb)" : UI.cardBg, border: msg.role === "user" ? "1px solid rgba(59,130,246,0.35)" : `1px solid ${UI.border}`, borderRadius: msg.role === "user" ? "14px 4px 14px 14px" : "4px 14px 14px 14px", padding: "0.75rem 0.95rem", fontSize: "0.85rem", lineHeight: "1.7", backdropFilter: "blur(10px)", textAlign: "left", color: msg.role === "user" ? "#ffffff" : UI.text, boxShadow: msg.role === "user" ? "none" : UI.shadow }}>
              {fmt(msg.content)}
              {msg.role === "assistant" && renderMetaPanel(msg.meta)}
              <div style={{ fontSize: "0.6rem", color: "#475569", marginTop: "0.3rem", textAlign: "right" }}>
                {msg.timestamp.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
              </div>
            </div>
          </div>
        ))}

        {loading && (
          <div style={{ display: "flex", alignItems: "flex-start", gap: "0.6rem", animation: "fadeUp 0.3s ease" }}>
            <div style={{ width: 32, height: 32, borderRadius: "8px", background: "linear-gradient(135deg,#4ade80,#22d3ee)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.9rem", boxShadow: "0 0 10px rgba(74,222,128,0.3)" }}>⛏</div>
            <div style={{ padding: "0.75rem 0.95rem", background: UI.cardBg, border: `1px solid ${UI.border}`, borderRadius: "4px 14px 14px 14px", fontSize: "0.82rem", color: UI.subtle, boxShadow: UI.shadow }}>
              <span>多智能体协同推理中</span><span className="dots">...</span>
              {selectedDocumentCount > 0 && <div style={{ fontSize: "0.63rem", color: "#4ade80", marginTop: "0.2rem" }}>📄 正在检索本次勾选的 {selectedDocumentCount} 份规程文档</div>}
              <div style={{ marginTop: "0.35rem", display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                {AGENTS.filter(a => activeAgents.includes(a.id)).map(a => (
                  <span key={a.id} style={{ fontSize: "0.6rem", padding: "0.1rem 0.4rem", background: `${a.color}20`, border: `1px solid ${a.color}`, borderRadius: "4px", color: a.color }}>{a.icon} {a.name}</span>
                ))}
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div style={{ padding: "0 1.25rem 0.55rem" }}>
        <div style={{ display: "flex", gap: "0.38rem", flexWrap: "wrap" }}>
          {QUICK_QUESTIONS.map((q, i) => (
            <button key={i} onClick={() => sendMessage(q.text)} disabled={loading}
              style={{ padding: "0.32rem 0.75rem", background: UI.cardBg, border: `1px solid ${UI.border}`, borderRadius: "20px", color: UI.subtle, fontSize: "0.7rem", cursor: "pointer", transition: "all 0.2s" }}
              onMouseEnter={e => { e.currentTarget.style.background = "#e0f2fe"; e.currentTarget.style.borderColor = "rgba(56,189,248,0.55)"; e.currentTarget.style.color = UI.text; }}
              onMouseLeave={e => { e.currentTarget.style.background = UI.cardBg; e.currentTarget.style.borderColor = UI.border; e.currentTarget.style.color = UI.subtle; }}
            >{q.icon} {q.text}</button>
          ))}
        </div>
      </div>

      <div style={{ padding: "0 1.25rem 1.1rem" }}>
        {(docs.length > 0 || images.length > 0 || videos.length > 0 || sensors.length > 0) && (
          <div style={{ marginBottom: "0.45rem" }}>
            <div style={{ padding: "0.36rem 0.72rem", background: "rgba(15,23,42,0.04)", border: `1px solid ${UI.border}`, borderRadius: "8px", fontSize: "0.66rem", color: UI.text, display: "flex", alignItems: "center", gap: "0.35rem", flexWrap: "wrap" }}>
              <span style={{ color: UI.subtle }}>参考范围提示：</span>
              <span>{selectedSummaryText}</span>
            </div>
          </div>
        )}
        <div style={{ display: "flex", gap: "0.6rem", background: UI.cardBg, border: `1px solid ${UI.border}`, borderRadius: "13px", padding: "0.4rem 0.4rem 0.4rem 0.85rem", backdropFilter: "blur(20px)", boxShadow: UI.shadow }}>
          <button onClick={() => navigateToView(APP_VIEW_DOCUMENTS)} title="打开文档库" style={{ width: 34, height: 34, borderRadius: "7px", flexShrink: 0, alignSelf: "flex-end", background: "rgba(74,222,128,0.1)", border: "1px solid rgba(74,222,128,0.3)", color: "#4ade80", cursor: "pointer", fontSize: "0.95rem", display: "flex", alignItems: "center", justifyContent: "center" }}>📎</button>
          <button onClick={() => navigateToView(APP_VIEW_IMAGES)} title="打开图片库" style={{ width: 34, height: 34, borderRadius: "7px", flexShrink: 0, alignSelf: "flex-end", background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.3)", color: "#60a5fa", cursor: "pointer", fontSize: "0.95rem", display: "flex", alignItems: "center", justifyContent: "center" }}>📸</button>
          <button onClick={() => navigateToView(APP_VIEW_VIDEOS)} title="打开视频库" style={{ width: 34, height: 34, borderRadius: "7px", flexShrink: 0, alignSelf: "flex-end", background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.3)", color: "#f59e0b", cursor: "pointer", fontSize: "0.95rem", display: "flex", alignItems: "center", justifyContent: "center" }}>🎬</button>
          <button onClick={() => navigateToView(APP_VIEW_SENSORS)} title="打开传感器库" style={{ width: 34, height: 34, borderRadius: "7px", flexShrink: 0, alignSelf: "flex-end", background: "rgba(168,85,247,0.1)", border: "1px solid rgba(168,85,247,0.3)", color: "#c084fc", cursor: "pointer", fontSize: "0.95rem", display: "flex", alignItems: "center", justifyContent: "center" }}>📡</button>
          <textarea value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
            placeholder="描述灾害情况或输入应急问题（Shift+Enter换行）..." rows={2}
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: UI.text, fontSize: "0.85rem", lineHeight: "1.6", resize: "none", fontFamily: "inherit" }} />
          <button onClick={clearCurrentConversation} style={{ padding: "0.5rem 0.9rem", background: "rgba(148,163,184,0.12)", border: "1px solid rgba(148,163,184,0.24)", borderRadius: "9px", color: UI.text, fontWeight: 700, fontSize: "0.76rem", cursor: "pointer", flexShrink: 0, alignSelf: "flex-end" }}>清空对话</button>
          <button onClick={() => sendMessage()} disabled={loading || !input.trim()}
            style={{ padding: "0.5rem 1.1rem", background: loading || !input.trim() ? "rgba(74,222,128,0.12)" : "linear-gradient(135deg,#4ade80,#22d3ee)", border: "none", borderRadius: "9px", color: loading || !input.trim() ? "#4ade8044" : "#0a0f1e", fontWeight: 700, fontSize: "0.8rem", cursor: loading || !input.trim() ? "not-allowed" : "pointer", transition: "all 0.2s", flexShrink: 0, alignSelf: "flex-end", boxShadow: !loading && input.trim() ? "0 0 16px rgba(74,222,128,0.4)" : "none" }}>
            {loading ? "推理中" : "发送 ↑"}
          </button>
        </div>
        <div style={{ textAlign: "center", marginTop: "0.35rem", fontSize: "0.6rem", color: "#374151" }}>
          本系统为辅助决策工具，紧急情况请同时启动线下应急预案 · 课题编号：方向20
        </div>
      </div>
    </div>
  );

  const renderPageShell = (title, subtitle, actions, content) => (
    <div style={{ flex: 1, minHeight: 0, height: "100%", display: "flex", flexDirection: "column", padding: "1.1rem 1.25rem", gap: "0.9rem" }}>
      <div style={{ textAlign: "center" }}>
        <div>
          <div style={{ fontSize: "1rem", fontWeight: 800, color: UI.text }}>{title}</div>
          <div style={{ marginTop: "0.18rem", fontSize: "0.72rem", lineHeight: 1.7, color: UI.subtle }}>{subtitle}</div>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center", justifyContent: "center", marginTop: "0.75rem" }}>
          {actions}
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, height: 0, display: "flex", flexDirection: "column" }}>
        {content}
      </div>
    </div>
  );

  const renderDocumentsPage = () => renderPageShell(
    "文档库",
    "这里存放当前会话已入库的规程文档。上传后会进入向量检索，并参与知识图谱构建；只有勾选的文档才会参与本次问答。",
    <>
      <button onClick={() => fileInputRef.current?.click()} disabled={uploading} style={{ padding: "0.55rem 0.95rem", borderRadius: "10px", border: `1px dashed ${UI.borderStrong}`, background: "rgba(56,189,248,0.10)", color: uploading ? UI.subtle : UI.text, cursor: uploading ? "not-allowed" : "pointer", fontWeight: 700, fontSize: "0.72rem" }}>{uploading ? "解析中..." : "上传规程文档"}</button>
      {buildLibrarySelectionActions(APP_VIEW_DOCUMENTS)}
    </>,
    docs.length === 0
      ? renderLibraryEmpty("当前文档库为空", "上传 PDF、DOCX 或 TXT 后，问答智能体会优先参考这些规程内容。", uploading ? "文档解析中..." : "上传规程文档", () => fileInputRef.current?.click(), uploading)
      : (
        <div style={{ display: "grid", gap: "0.65rem", overflowY: "auto", paddingRight: "0.2rem" }}>
          {docs.map((doc) => (
            <div key={doc.document_id || doc.name} style={{ position: "relative", padding: "0.9rem 1rem", paddingRight: "5.8rem", background: UI.cardBg, border: `1px solid ${UI.border}`, borderRadius: "14px", display: "flex", alignItems: "flex-start", gap: "0.7rem", boxShadow: UI.shadow }}>
              <input
                type="checkbox"
                checked={selectedDocIds.includes(String(doc.document_id || ""))}
                onChange={() => toggleSelection(doc.document_id, setSelectedDocIds)}
                style={{ position: "absolute", top: 12, right: 80, width: 16, height: 16, accentColor: "#0ea5e9", cursor: "pointer" }}
              />
              <div style={{ width: 44, height: 44, borderRadius: "12px", background: "#ecfeff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "1.1rem", flexShrink: 0 }}>{fileIcon(doc.name || "")}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: "0.88rem", fontWeight: 800, color: UI.text, wordBreak: "break-all" }}>{doc.name}</div>
                <div style={{ marginTop: "0.28rem", fontSize: "0.7rem", color: UI.subtle }}>{doc.sizeMB} MB · {(doc.charCount || 0).toLocaleString()} 字符 · {doc.chunkCount || 0} 个检索块</div>
                {(doc.graphNodeCount || doc.graphRelationCount) ? (
                  <div style={{ marginTop: "0.25rem", fontSize: "0.68rem", color: "#67e8f9" }}>图谱节点 {doc.graphNodeCount || 0} · 关系 {doc.graphRelationCount || 0}</div>
                ) : null}
              </div>
              <button onClick={() => removeUploadedDocument(doc)} style={{ position: "absolute", top: 10, right: 12, padding: "0.45rem 0.7rem", borderRadius: "8px", border: "1px solid rgba(248,113,113,0.24)", background: "#fff1f2", color: "#b91c1c", cursor: "pointer", fontSize: "0.72rem" }}>移除</button>
            </div>
          ))}
        </div>
      )
  );

  const renderImagesPage = () => renderPageShell(
    "图片库",
    "这里保存当前会话上传的现场图片。上传后会立即完成识别，并把摘要结果作为可参与问答的图像证据；只有勾选的图片会参与本次问答。",
    <>
      <button onClick={() => imageInputRef.current?.click()} disabled={imageUploading} style={{ padding: "0.55rem 0.95rem", borderRadius: "10px", border: `1px dashed ${UI.borderStrong}`, background: "#eff6ff", color: imageUploading ? UI.subtle : UI.text, cursor: imageUploading ? "not-allowed" : "pointer", fontWeight: 700, fontSize: "0.72rem" }}>{imageUploading ? "上传中..." : "上传现场图片"}</button>
      {buildLibrarySelectionActions(APP_VIEW_IMAGES)}
    </>,
    images.length === 0
      ? renderLibraryEmpty("当前图片库为空", "上传 JPG、PNG 或 WEBP 后，问答链路会在发送前自动补充图片识别结果。", imageUploading ? "上传中..." : "上传现场图片", () => imageInputRef.current?.click(), imageUploading)
      : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(220px,1fr))", gap: "0.75rem", overflowY: "auto", paddingRight: "0.2rem" }}>
          {images.map((img) => (
            <div key={img.image_id || img.name} style={{ position: "relative", padding: "0.75rem", paddingTop: "2.5rem", background: UI.cardBg, border: `1px solid ${UI.border}`, borderRadius: "16px", boxShadow: UI.shadow }}>
              <input
                type="checkbox"
                checked={selectedImageIds.includes(String(img.image_id || ""))}
                onChange={() => toggleSelection(img.image_id, setSelectedImageIds)}
                style={{ position: "absolute", top: 12, right: 12, width: 16, height: 16, accentColor: "#2563eb", cursor: "pointer", zIndex: 1 }}
              />
              <div style={{ height: 150, borderRadius: "12px", background: "#e2e8f0", overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <img src={img.dataUrl} alt={img.name} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              </div>
              <div style={{ marginTop: "0.6rem", fontSize: "0.8rem", fontWeight: 700, color: UI.text, wordBreak: "break-all" }}>{img.name}</div>
              <div style={{ marginTop: "0.2rem", fontSize: "0.68rem", color: UI.subtle }}>{img.sizeMB} MB</div>
              {img.summary_text ? (
                <div style={{ marginTop: "0.35rem", fontSize: "0.68rem", lineHeight: 1.7, color: UI.text, whiteSpace: "pre-wrap" }}>
                  {img.summary_text.split("\n").slice(0, 4).join("\n")}
                </div>
              ) : null}
              <button onClick={() => removeUploadedImage(img)} style={{ marginTop: "0.55rem", width: "100%", padding: "0.45rem 0.7rem", borderRadius: "8px", border: `1px solid ${UI.border}`, background: UI.softBg, color: UI.text, cursor: "pointer", fontSize: "0.72rem" }}>移出图片库</button>
            </div>
          ))}
        </div>
      )
  );

  const renderVideosPage = () => renderPageShell(
    "视频库",
    "这里展示当前会话上传的视频及抽帧分析结果。上传后会自动完成抽帧、识别与摘要生成；只有勾选的视频会参与本次问答。",
    <>
      <button onClick={() => videoInputRef.current?.click()} disabled={videoUploading} style={{ padding: "0.55rem 0.95rem", borderRadius: "10px", border: "1px dashed rgba(245,158,11,0.45)", background: "linear-gradient(135deg,rgba(245,158,11,0.15),rgba(249,115,22,0.08))", color: videoUploading ? "#f59e0b60" : "#f59e0b", cursor: videoUploading ? "not-allowed" : "pointer", fontWeight: 700, fontSize: "0.72rem" }}>{videoUploading ? "分析中..." : "上传现场视频"}</button>
      {buildLibrarySelectionActions(APP_VIEW_VIDEOS)}
    </>,
    videos.length === 0
      ? renderLibraryEmpty("当前视频库为空", "上传 MP4、MOV 或 WEBM 后，系统会自动抽帧分析，并把命中帧作为图像证据参与问答。", videoUploading ? "分析中..." : "上传现场视频", () => videoInputRef.current?.click(), videoUploading)
      : (
        <div style={{ display: "grid", gap: "0.75rem", overflowY: "auto", paddingRight: "0.2rem" }}>
          {videos.map((video) => (
            <div key={video.video_id || video.name} style={{ position: "relative", padding: "0.9rem 1rem", paddingRight: "8rem", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.18)", borderRadius: "16px", display: "flex", gap: "0.8rem" }}>
              <input
                type="checkbox"
                checked={selectedVideoIds.includes(String(video.video_id || ""))}
                onChange={() => toggleSelection(video.video_id, setSelectedVideoIds)}
                style={{ position: "absolute", top: 12, right: 106, width: 16, height: 16, accentColor: "#d97706", cursor: "pointer" }}
              />
              <div style={{ width: 64, height: 64, borderRadius: "14px", background: "rgba(15,23,42,0.12)", overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center", color: "#fbbf24", fontSize: "1.2rem", flexShrink: 0 }}>
                {video.posterDataUrl ? (
                  <img src={video.posterDataUrl} alt={video.name} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                ) : (
                  <span>🎞</span>
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: "0.86rem", fontWeight: 800, color: "#fde68a", wordBreak: "break-all" }}>{video.name}</div>
                <div style={{ marginTop: "0.24rem", fontSize: "0.7rem", color: "#94a3b8" }}>{video.sizeMB} MB · {video.frames_extracted || 0} 帧抽取 · {video.frames_matched || 0} 帧命中</div>
                {video.issue_keywords?.length ? (
                  <div style={{ marginTop: "0.35rem", display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                    {video.issue_keywords.slice(0, 6).map((kw, idx) => (
                      <span key={`${kw}-${idx}`} style={{ padding: "0.08rem 0.38rem", borderRadius: "999px", background: "rgba(245,158,11,0.12)", border: "1px solid rgba(245,158,11,0.22)", color: "#fde68a", fontSize: "0.62rem" }}>{kw}</span>
                    ))}
                  </div>
                ) : null}
                {(() => {
                  const summaryPreview = getVideoSummaryPreview(video.summary_text);
                  const keyClips = getVideoKeyClips(video);
                  return (
                    <>
                      {summaryPreview.length ? (
                        <div style={{ marginTop: "0.38rem", fontSize: "0.68rem", lineHeight: 1.7, color: "#cbd5e1", whiteSpace: "pre-wrap" }}>{summaryPreview.join("\n")}</div>
                      ) : null}
                      {keyClips.length ? (
                        <div style={{ marginTop: "0.48rem", display: "grid", gap: "0.35rem" }}>
                          <div style={{ fontSize: "0.65rem", fontWeight: 700, color: "#fcd34d" }}>关键片段</div>
                          {keyClips.map((clip) => (
                            <div key={clip.id} style={{ padding: "0.45rem 0.55rem", borderRadius: "10px", background: "rgba(15,23,42,0.34)", border: "1px solid rgba(245,158,11,0.14)", display: "grid", gap: "0.16rem" }}>
                              <div style={{ fontSize: "0.62rem", color: "#fbbf24", fontWeight: 700 }}>{clip.label}</div>
                              <div style={{ fontSize: "0.66rem", color: "#e2e8f0", lineHeight: 1.55 }}>{clip.summary}</div>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </>
                  );
                })()}
              </div>
              <button onClick={() => removeUploadedVideo(video)} style={{ position: "absolute", top: 10, right: 12, padding: "0.45rem 0.7rem", borderRadius: "8px", border: "1px solid rgba(148,163,184,0.16)", background: "rgba(255,255,255,0.04)", color: "#cbd5e1", cursor: "pointer", fontSize: "0.72rem", alignSelf: "flex-start" }}>移出视频库</button>
            </div>
          ))}
        </div>
      )
  );

  const renderSensorsPage = () => renderPageShell(
    "传感器数据库",
    "这里管理当前会话的实时传感器数据。支持导入 JSON 文件，也支持继续粘贴数组进行手动接入；只有勾选的传感器会参与本次问答。",
    <>
      <button onClick={() => sensorFileInputRef.current?.click()} style={{ padding: "0.55rem 0.95rem", borderRadius: "10px", border: "1px dashed rgba(168,85,247,0.45)", background: "linear-gradient(135deg,rgba(168,85,247,0.15),rgba(99,102,241,0.08))", color: "#d8b4fe", cursor: "pointer", fontWeight: 700, fontSize: "0.72rem" }}>导入传感器 JSON</button>
      <button onClick={() => setSensorDialogOpen(true)} style={{ padding: "0.55rem 0.95rem", borderRadius: "10px", border: "1px solid rgba(168,85,247,0.26)", background: "rgba(168,85,247,0.08)", color: "#c084fc", cursor: "pointer", fontWeight: 700, fontSize: "0.72rem" }}>手动录入数据</button>
      <button onClick={handleSensorClear} disabled={sensors.length === 0} style={{ padding: "0.55rem 0.95rem", borderRadius: "10px", border: "1px solid rgba(248,113,113,0.18)", background: sensors.length === 0 ? "rgba(239,68,68,0.04)" : "rgba(239,68,68,0.08)", color: sensors.length === 0 ? "#fca5a560" : "#fca5a5", cursor: sensors.length === 0 ? "not-allowed" : "pointer", fontWeight: 700, fontSize: "0.72rem" }}>清空数据</button>
      {buildLibrarySelectionActions(APP_VIEW_SENSORS)}
    </>,
    sensors.length === 0
      ? renderLibraryEmpty("当前传感器数据库为空", "导入监测 JSON 后，传感器数据会自动参与风险识别、角色路由和问答推理。", "导入传感器 JSON", () => sensorFileInputRef.current?.click())
      : (
        <div style={{ display: "grid", gap: "0.65rem", overflowY: "auto", paddingRight: "0.2rem" }}>
          {sensors.map((sensor, idx) => (
            <div key={`${sensor.sensor_id || sensor.name}-${idx}`} style={{ position: "relative", padding: "0.85rem 0.95rem", paddingRight: "8rem", background: "rgba(168,85,247,0.08)", border: "1px solid rgba(168,85,247,0.18)", borderRadius: "15px", display: "grid", gap: "0.18rem" }}>
              <input
                type="checkbox"
                checked={selectedSensorIds.includes(String(sensor.sensor_id || ""))}
                onChange={() => toggleSelection(sensor.sensor_id, setSelectedSensorIds)}
                style={{ position: "absolute", top: 12, right: 80, width: 16, height: 16, accentColor: "#9333ea", cursor: "pointer" }}
              />
              <div style={{ fontSize: "0.84rem", fontWeight: 800, color: "#e9d5ff" }}>{sensor.name || sensor.sensor_id}</div>
              <div style={{ fontSize: "0.7rem", color: "#cbd5e1" }}>{(sensor.value_text || sensor.value || "未知")}{sensor.unit || ""} · 阈值 {sensor.threshold ?? "未知"} · {sensor.status || "状态未知"}</div>
              <div style={{ fontSize: "0.66rem", color: "#94a3b8" }}>{sensor.location || "未知位置"} · {sensor.timestamp || "无时间戳"} · 编号 {sensor.sensor_id || "未知"}</div>
              <button onClick={() => removeUploadedSensor(sensor)} style={{ position: "absolute", top: 10, right: 12, padding: "0.45rem 0.7rem", borderRadius: "8px", border: "1px solid rgba(248,113,113,0.18)", background: "rgba(255,241,242,0.92)", color: "#9f1239", cursor: "pointer", fontSize: "0.72rem" }}>移除</button>
            </div>
          ))}
        </div>
      )
  );

  const renderGraphPage = () => renderPageShell(
    "知识图谱库",
    "当前知识图谱按 session 合并构建。这里可以手动生成文档库对应图谱、上传三元组测试文件，并直接检索当前会话的图谱结果。",
    <>
      <button onClick={handleGenerateKnowledgeGraph} disabled={docs.length === 0 || graphGenerating || graphBuildStatus.state === "running" || graphBuildStatus.state === "queued"} style={{ padding: "0.55rem 0.95rem", borderRadius: "10px", border: `1px dashed ${UI.borderStrong}`, background: "#ecfeff", color: (docs.length === 0 || graphGenerating || graphBuildStatus.state === "running" || graphBuildStatus.state === "queued") ? UI.subtle : UI.text, cursor: (docs.length === 0 || graphGenerating || graphBuildStatus.state === "running" || graphBuildStatus.state === "queued") ? "not-allowed" : "pointer", fontWeight: 700, fontSize: "0.72rem" }}>{graphGenerating ? "提交中..." : "生成知识图谱"}</button>
      <button onClick={() => triplesInputRef.current?.click()} disabled={uploading} style={{ padding: "0.55rem 0.95rem", borderRadius: "10px", border: `1px dashed ${UI.borderStrong}`, background: "#f8fafc", color: uploading ? UI.subtle : UI.text, cursor: uploading ? "not-allowed" : "pointer", fontWeight: 700, fontSize: "0.72rem" }}>{uploading ? "导入中..." : "上传三元组 JSON"}</button>
      <button onClick={() => loadKnowledgeGraph(graphKeyword)} disabled={graphLoading} style={{ padding: "0.55rem 0.95rem", borderRadius: "10px", border: `1px solid ${UI.borderStrong}`, background: "#ffffff", color: graphLoading ? UI.subtle : UI.text, cursor: graphLoading ? "not-allowed" : "pointer", fontWeight: 700, fontSize: "0.72rem" }}>{graphLoading ? "加载中..." : "刷新图谱"}</button>
    </>,
    <div style={{ flex: 1, minHeight: 0, height: "100%", display: "flex", flexDirection: "column", gap: "0.8rem" }}>
      <div style={{ display: "flex", gap: "0.55rem", flexWrap: "wrap", alignItems: "flex-start", alignContent: "flex-start" }}>
        <span style={{ display: "inline-flex", alignItems: "center", whiteSpace: "nowrap", lineHeight: 1.2, padding: "0.18rem 0.5rem", borderRadius: "999px", background: "#eef2ff", border: "1px solid rgba(99,102,241,0.22)", color: UI.text, fontSize: "0.66rem", fontWeight: 700 }}>状态：{graphBuildStatus.state || "idle"}</span>
        <span style={{ display: "inline-flex", alignItems: "center", whiteSpace: "nowrap", lineHeight: 1.2, padding: "0.18rem 0.5rem", borderRadius: "999px", background: "#f0fdf4", border: "1px solid rgba(22,163,74,0.22)", color: UI.text, fontSize: "0.66rem", fontWeight: 700 }}>节点：{graphBuildStatus.node_count || graphData.stats?.node_count || 0}</span>
        <span style={{ display: "inline-flex", alignItems: "center", whiteSpace: "nowrap", lineHeight: 1.2, padding: "0.18rem 0.5rem", borderRadius: "999px", background: "#fff7ed", border: "1px solid rgba(217,119,6,0.22)", color: UI.text, fontSize: "0.66rem", fontWeight: 700 }}>关系：{graphBuildStatus.relation_count || graphData.stats?.relation_count || 0}</span>
        <span style={{ display: "inline-flex", alignItems: "center", whiteSpace: "nowrap", lineHeight: 1.2, padding: "0.18rem 0.5rem", borderRadius: "999px", background: "#f8fafc", border: "1px solid rgba(100,116,139,0.22)", color: UI.text, fontSize: "0.66rem", fontWeight: 700 }}>来源文档：{docs.length}</span>
      </div>
      {docs.length > 0 ? (
        <div style={{ display: "flex", gap: "0.32rem", flexWrap: "wrap", alignItems: "flex-start", alignContent: "flex-start" }}>
          {docs.map((doc) => (
            <span key={doc.document_id || doc.name} style={{ display: "inline-flex", alignItems: "center", whiteSpace: "nowrap", lineHeight: 1.2, padding: "0.18rem 0.45rem", borderRadius: "999px", background: "#ffffff", border: `1px solid ${UI.border}`, color: UI.text, fontSize: "0.64rem" }}>{doc.name}</span>
          ))}
        </div>
      ) : null}
      <div style={{ flex: 1, minHeight: 0, height: 0, display: "flex" }}>
        {renderGraphDialog(true)}
      </div>
    </div>
  );

  const renderCurrentPage = () => {
    switch (currentView) {
      case APP_VIEW_DOCUMENTS:
        return renderDocumentsPage();
      case APP_VIEW_IMAGES:
        return renderImagesPage();
      case APP_VIEW_VIDEOS:
        return renderVideosPage();
      case APP_VIEW_SENSORS:
        return renderSensorsPage();
      case APP_VIEW_GRAPH:
        return renderGraphPage();
      case APP_VIEW_CHAT:
      default:
        return renderChatPage();
    }
  };

  if (authLoading) {
    return (
      <div className="light-theme-app" style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: UI.appBg, color: UI.text }}>
        <div style={{ padding: "1.2rem 1.6rem", borderRadius: "14px", background: UI.cardBg, border: `1px solid ${UI.border}`, boxShadow: UI.shadow, fontSize: "0.9rem" }}>
          正在恢复登录状态...
        </div>
      </div>
    );
  }

  if (!currentUser) {
    return (
      <div className="light-theme-app" style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: UI.appBg, color: UI.text, padding: "1rem" }}>
        <div style={{ width: "min(420px, 92vw)", background: UI.cardBg, border: `1px solid ${UI.border}`, borderRadius: "18px", boxShadow: UI.shadow, padding: "1.3rem", textAlign: "center" }}>
          <div style={{ fontSize: "1.05rem", fontWeight: 800 }}>煤矿应急救援知识问答系统</div>
          <div style={{ marginTop: "0.35rem", fontSize: "0.74rem", color: UI.subtle }}>
            登录并进入个人煤矿知识库空间。
          </div>
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}>
            <button onClick={() => setAuthMode("login")} style={{ flex: 1, padding: "0.6rem 0.8rem", borderRadius: "10px", border: authMode === "login" ? "1px solid #22c55e" : `1px solid ${UI.border}`, background: authMode === "login" ? "rgba(34,197,94,0.12)" : "#fff", cursor: "pointer", fontWeight: 700 }}>登录</button>
            <button onClick={() => setAuthMode("register")} style={{ flex: 1, padding: "0.6rem 0.8rem", borderRadius: "10px", border: authMode === "register" ? "1px solid #0ea5e9" : `1px solid ${UI.border}`, background: authMode === "register" ? "rgba(14,165,233,0.12)" : "#fff", cursor: "pointer", fontWeight: 700 }}>注册</button>
          </div>
          <form onSubmit={handleAuthSubmit} style={{ display: "grid", gap: "0.75rem", marginTop: "1rem" }}>
            <input
              value={authForm.username}
              onChange={(e) => setAuthForm(prev => ({ ...prev, username: e.target.value }))}
              placeholder="用户名"
              style={{ padding: "0.72rem 0.82rem", borderRadius: "10px", border: `1px solid ${UI.border}`, fontSize: "0.8rem" }}
            />
            <input
              type="password"
              value={authForm.password}
              onChange={(e) => setAuthForm(prev => ({ ...prev, password: e.target.value }))}
              placeholder="密码"
              style={{ padding: "0.72rem 0.82rem", borderRadius: "10px", border: `1px solid ${UI.border}`, fontSize: "0.8rem" }}
            />
            {authMode === "register" ? (
              <input
                type="password"
                value={authForm.confirmPassword}
                onChange={(e) => setAuthForm(prev => ({ ...prev, confirmPassword: e.target.value }))}
                placeholder="再次输入密码"
                style={{ padding: "0.72rem 0.82rem", borderRadius: "10px", border: `1px solid ${UI.border}`, fontSize: "0.8rem" }}
              />
            ) : null}
            {authError ? <div style={{ color: "#dc2626", fontSize: "0.74rem" }}>{authError}</div> : null}
            <button type="submit" disabled={authSubmitting} style={{ padding: "0.75rem 0.9rem", borderRadius: "10px", border: "none", background: "linear-gradient(135deg,#22c55e,#0ea5e9)", color: "#fff", fontWeight: 800, cursor: authSubmitting ? "not-allowed" : "pointer" }}>
              {authSubmitting ? "提交中..." : authMode === "login" ? "登录" : "注册并创建账号"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="light-theme-app" style={{ height: "100vh", background: UI.appBg, fontFamily: "'Noto Sans SC','PingFang SC',sans-serif", color: UI.text, display: "flex", flexDirection: "column" }}>

      {/* Alert */}
      {alertLevel && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, zIndex: 200, background: alertLevel === "red" ? "rgba(239,68,68,0.96)" : "rgba(245,158,11,0.96)", padding: "0.7rem 2rem", textAlign: "center", fontWeight: 700, fontSize: "0.9rem", animation: "slideDown 0.3s ease" }}>
          {alertLevel === "red" ? "🚨 检测到高危情况 — 多智能体紧急协同启动" : "⚠️ 检测到风险信号 — 态势感知智能体已激活"}
        </div>
      )}

      {/* Header */}
      <div style={{ background: UI.headerBg, backdropFilter: "blur(20px)", borderBottom: `1px solid ${UI.border}`, padding: "0.8rem 1.25rem", display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0, gap: "1rem", flexWrap: "wrap", boxShadow: "0 2px 12px rgba(15,23,42,0.04)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.8rem" }}>
          <div style={{ width: 40, height: 40, background: "linear-gradient(135deg,#4ade80,#22d3ee)", borderRadius: "9px", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "1.2rem", boxShadow: "0 0 18px rgba(74,222,128,0.4)", flexShrink: 0 }}>⛏</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: "0.95rem" }}>煤矿应急救援决策 AI 智能体</div>
            <div style={{ fontSize: "0.68rem", color: UI.subtle, marginTop: "0.1rem" }}>中国矿业大学 · 煤炭无人化开采数智技术全国重点实验室</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", alignItems: "center", justifyContent: "flex-end" }}>
          {AGENTS.map(a => (
            <div key={a.id} style={{ display: "flex", alignItems: "center", gap: "0.25rem", padding: "0.22rem 0.5rem", background: activeAgents.includes(a.id) ? `${a.color}20` : UI.cardBg, border: `1px solid ${activeAgents.includes(a.id) ? a.color : UI.border}`, borderRadius: "5px", fontSize: "0.65rem", transition: "all 0.3s", boxShadow: activeAgents.includes(a.id) ? `0 0 8px ${a.color}22` : "none" }}>
              <span style={{ width: 5, height: 5, borderRadius: "50%", background: activeAgents.includes(a.id) ? a.color : "#374151", animation: activeAgents.includes(a.id) ? "pulse 1s infinite" : "none", flexShrink: 0 }} />
              <span style={{ color: UI.text }}>{a.icon} {a.name}</span>
            </div>
          ))}
          <div style={{ padding: "0.26rem 0.6rem", borderRadius: "999px", background: "#ffffff", border: `1px solid ${UI.border}`, fontSize: "0.68rem", color: UI.text }}>
            当前用户：{currentUser?.username || "未登录"}
          </div>
          <button onClick={handleLogout} style={{ padding: "0.38rem 0.78rem", borderRadius: "8px", border: `1px solid ${UI.border}`, background: "#fff7ed", color: "#9a3412", cursor: "pointer", fontSize: "0.72rem", fontWeight: 700 }}>
            退出登录
          </button>
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        <input ref={fileInputRef} type="file" accept=".txt,.docx,.pdf" multiple onChange={handleUpload} style={{ display: "none" }} />
        <input ref={triplesInputRef} type="file" accept=".json,application/json" onChange={handleTriplesUpload} style={{ display: "none" }} />
        <input ref={imageInputRef} type="file" accept="image/*" multiple onChange={handleImageUpload} style={{ display: "none" }} />
        <input ref={videoInputRef} type="file" accept="video/*" multiple onChange={handleVideoUpload} style={{ display: "none" }} />
        <input ref={sensorFileInputRef} type="file" accept=".json,application/json" multiple onChange={handleSensorFileUpload} style={{ display: "none" }} />

        <div style={{ width: sidebarOpen ? 248 : 62, flexShrink: 0, background: UI.sidebarBg, borderRight: `1px solid ${UI.border}`, display: "flex", flexDirection: "column", transition: "width 0.3s ease", overflow: "hidden" }}>
          <div style={{ padding: "0.75rem 0.7rem", borderBottom: `1px solid ${UI.border}`, display: "flex", alignItems: "center", gap: "0.55rem" }}>
            <button onClick={() => setSidebarOpen(v => !v)} title="知识库导航" style={{ width: 38, height: 38, borderRadius: "10px", flexShrink: 0, background: sidebarOpen ? "rgba(56,189,248,0.12)" : UI.cardBg, border: `1px solid ${UI.border}`, color: UI.text, cursor: "pointer", fontSize: "1rem", display: "flex", alignItems: "center", justifyContent: "center" }}>📚</button>
            {sidebarOpen && (
              <div>
                <div style={{ fontSize: "0.78rem", fontWeight: 800, color: UI.text }}>知识库导航</div>
                <div style={{ fontSize: "0.64rem", color: UI.subtle, marginTop: "0.12rem" }}>问答页为主页面，库页负责查看与上传</div>
              </div>
            )}
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: "0.6rem" }}>
            {LIBRARY_NAV_ITEMS.map((item) => {
              const count = item.id === APP_VIEW_DOCUMENTS
                ? docs.length
                : item.id === APP_VIEW_IMAGES
                  ? images.length
                  : item.id === APP_VIEW_VIDEOS
                    ? videos.length
                    : item.id === APP_VIEW_SENSORS
                      ? sensors.length
                      : item.id === APP_VIEW_GRAPH
                        ? (graphBuildStatus.node_count || graphData.stats?.node_count || 0)
                        : 0;
              const active = currentView === item.id;
              const clickHandler = item.id === APP_VIEW_GRAPH ? openKnowledgeGraph : () => navigateToView(item.id);
              return (
                <button
                  key={item.id}
                  onClick={clickHandler}
                  style={{ width: "100%", marginBottom: "0.45rem", padding: sidebarOpen ? "0.72rem 0.78rem" : "0.72rem 0.4rem", borderRadius: "12px", background: active ? `${item.color}18` : UI.cardBg, border: `1px solid ${active ? item.color : UI.border}`, color: UI.text, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: sidebarOpen ? "space-between" : "center", gap: "0.55rem", textAlign: "left", boxShadow: active ? "0 8px 20px rgba(56,189,248,0.10)" : "none" }}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: "0.55rem", minWidth: 0 }}>
                    <span style={{ fontSize: "1rem", flexShrink: 0 }}>{item.icon}</span>
                    {sidebarOpen && <span style={{ fontSize: "0.74rem", fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.label}</span>}
                  </span>
                  {sidebarOpen && item.id !== APP_VIEW_CHAT && count > 0 ? (
                    <span style={{ padding: "0.08rem 0.38rem", borderRadius: "999px", background: "#ffffff", border: `1px solid ${item.color}55`, fontSize: "0.62rem", color: UI.text, flexShrink: 0 }}>{count}</span>
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>

        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {renderCurrentPage()}
        </div>
      </div>

      {sensorDialogOpen && (
        <div style={{ position: "fixed", inset: 0, background: UI.overlay, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 300 }}>
          <div style={{ width: "min(720px, 92vw)", background: UI.cardBg, border: `1px solid ${UI.border}`, borderRadius: "12px", boxShadow: UI.shadow, padding: "1rem" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.8rem" }}>
              <div style={{ fontSize: "0.9rem", fontWeight: 800, color: "#d8b4fe" }}>传感器数据接入</div>
              <button onClick={() => setSensorDialogOpen(false)} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontSize: "1rem" }}>×</button>
            </div>
              <div style={{ fontSize: "0.68rem", color: UI.subtle, lineHeight: 1.7, marginBottom: "0.6rem" }}>
              在这里粘贴传感器 JSON 数组，提交后会进入当前会话，并参与风险识别和多智能体问答。
            </div>
            <textarea
              value={sensorInput}
              onChange={e => setSensorInput(e.target.value)}
              rows={14}
              style={{ width: "100%", background: "#ffffff", border: `1px solid ${UI.border}`, borderRadius: "10px", color: UI.text, fontSize: "0.75rem", lineHeight: 1.6, padding: "0.8rem", resize: "vertical", fontFamily: "Consolas, 'Courier New', monospace", outline: "none" }}
            />
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.6rem", marginTop: "0.8rem" }}>
              <button onClick={() => setSensorDialogOpen(false)} style={{ padding: "0.45rem 0.9rem", borderRadius: "8px", border: `1px solid ${UI.border}`, background: UI.softBg, color: UI.text, cursor: "pointer" }}>取消</button>
              <button onClick={handleSensorSubmit} style={{ padding: "0.45rem 0.9rem", borderRadius: "8px", border: "none", background: "linear-gradient(135deg,#a855f7,#6366f1)", color: "#f8fafc", fontWeight: 700, cursor: "pointer" }}>接入数据</button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.6;transform:scale(1.4)} }
        @keyframes fadeUp { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
        @keyframes slideDown { from{transform:translateY(-100%)} to{transform:translateY(0)} }
        .dots { display:inline-block; animation: dotAnim 1.4s infinite; }
        @keyframes dotAnim { 0%{opacity:.3} 50%{opacity:1} 100%{opacity:.3} }
        ::-webkit-scrollbar{width:3px} ::-webkit-scrollbar-track{background:transparent}
        ::-webkit-scrollbar-thumb{background:rgba(74,222,128,.22);border-radius:2px}
        textarea::placeholder{color:#475569}
      `}</style>
    </div>
  );
}



