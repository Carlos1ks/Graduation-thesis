import { useState, useRef, useEffect } from "react";
import ForceGraph2D from "react-force-graph-2d";

const BACKEND_BASE_URL = import.meta.env.VITE_API_BASE_URL;
const CHAT_API_URL = `${BACKEND_BASE_URL}/api/agent-chat`;
const DOCUMENT_UPLOAD_API_URL = `${BACKEND_BASE_URL}/api/documents/upload`;
const DOCUMENT_REMOVE_API_URL = `${BACKEND_BASE_URL}/api/documents/remove`;
const VIDEO_ANALYZE_API_URL = `${BACKEND_BASE_URL}/api/video-analyze`;
const SENSOR_PUSH_API_URL = `${BACKEND_BASE_URL}/api/sensors/push`;
const KNOWLEDGE_GRAPH_API_URL = `${BACKEND_BASE_URL}/api/knowledge-graph`;
const KNOWLEDGE_GRAPH_EXPAND_API_URL = `${BACKEND_BASE_URL}/api/knowledge-graph/expand`;
const KNOWLEDGE_GRAPH_STATUS_API_URL = `${BACKEND_BASE_URL}/api/knowledge-graph/status`;
const MAX_HISTORY_MESSAGES = 6;

const QUICK_QUESTIONS = [
  { icon: "💨", text: "瓦斯浓度超标如何处置？" },
  { icon: "🔥", text: "井下火灾应急预案流程" },
  { icon: "💧", text: "矿井突水事故救援步骤" },
  { icon: "📋", text: "应急救援队伍如何协同调度？" },
  { icon: "⚠️", text: "煤尘爆炸预防措施有哪些？" },
  { icon: "🛤️", text: "灾后逃生通道如何规划？" },
];

const AGENTS = [
  { id: "knowledge", name: "知识图谱智能体", icon: "🧠", color: "#4ade80" },
  { id: "perception", name: "态势感知智能体", icon: "📡", color: "#60a5fa" },
  { id: "decision", name: "决策推理智能体", icon: "⚡", color: "#f59e0b" },
  { id: "coordination", name: "协同指挥智能体", icon: "🎯", color: "#f472b6" },
];

async function uploadDocumentToBackend(file, sessionId) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("session_id", sessionId);

  const response = await fetch(DOCUMENT_UPLOAD_API_URL, {
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
  const response = await fetch(DOCUMENT_REMOVE_API_URL, {
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

async function uploadVideoToBackend(file, sessionId) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("session_id", sessionId);

  const response = await fetch(VIDEO_ANALYZE_API_URL, {
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
  const response = await fetch(SENSOR_PUSH_API_URL, {
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

async function fetchKnowledgeGraph(sessionId, keyword = "") {
  const params = new URLSearchParams({
    session_id: sessionId,
    limit: keyword.trim() ? "70" : "140",
  });
  if (keyword.trim()) {
    params.set("keyword", keyword.trim());
  }
  const response = await fetch(`${KNOWLEDGE_GRAPH_API_URL}?${params.toString()}`);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `知识图谱加载失败：${response.status}`);
  }
  return result;
}

async function expandKnowledgeGraph(sessionId, nodeUid, limit = 60) {
  const response = await fetch(KNOWLEDGE_GRAPH_EXPAND_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      node_uid: nodeUid,
      limit,
    }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `图谱展开失败：${response.status}`);
  }
  return result;
}

async function fetchKnowledgeGraphStatus(sessionId) {
  const params = new URLSearchParams({ session_id: sessionId });
  const response = await fetch(`${KNOWLEDGE_GRAPH_STATUS_API_URL}?${params.toString()}`);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.success) {
    throw new Error(result.error || `图谱状态获取失败：${response.status}`);
  }
  return result;
}

function compactKnowledgeGraphForView(nodes, links) {
  const hiddenTypes = new Set(["document", "document_type", "clause"]);
  const abstractLabels = new Set([
    "处置阶段",
    "预警阶段",
    "初期处置阶段",
    "救援处置阶段",
    "恢复阶段",
  ]);
  const visibleNodes = (Array.isArray(nodes) ? nodes : []).filter(node => (
    !hiddenTypes.has(node.type) && !abstractLabels.has(String(node.label || ""))
  ));
  const visibleUids = new Set(visibleNodes.map(node => node.uid));
  const visibleLinks = (Array.isArray(links) ? links : []).filter(link => (
    visibleUids.has(link.source) && visibleUids.has(link.target)
  ));
  return { nodes: visibleNodes, links: visibleLinks };
}

function mergeGraphData(currentGraph, incomingGraph) {
  const nodeMap = new Map((currentGraph.nodes || []).map(node => [node.uid, node]));
  for (const node of incomingGraph.nodes || []) {
    if (!node?.uid) continue;
    nodeMap.set(node.uid, { ...(nodeMap.get(node.uid) || {}), ...node });
  }

  const linkMap = new Map((currentGraph.links || []).map(link => [link.id || `${link.source}-${link.target}-${link.relation}`, link]));
  for (const link of incomingGraph.links || []) {
    if (!link) continue;
    const key = link.id || `${link.source}-${link.target}-${link.relation}`;
    linkMap.set(key, { ...(linkMap.get(key) || {}), ...link });
  }

  return {
    nodes: Array.from(nodeMap.values()),
    links: Array.from(linkMap.values()),
    stats: incomingGraph.stats || currentGraph.stats || {},
  };
}

function dedupeGraphLinks(links) {
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

export default function CoalMineAgent() {
  const [messages, setMessages] = useState([{
    role: "assistant",
    content: "您好！我是**煤矿应急救援决策知识问答AI智能体**，由中国矿业大学研发。\n\n可为您提供：\n- ⚡ **实时应急决策支持**\n- 🔍 **灾害风险智能识别**\n- 📋 **救援策略精准生成**\n- 🤝 **跨部门协同指挥建议**\n\n💡 点击左侧 📂 上传您矿井的专属规程、应急预案，智能体将优先基于这些文档为您作答。",
    timestamp: new Date(),
  }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeAgents, setActiveAgents] = useState([]);
  const [alertLevel, setAlertLevel] = useState(null);
  const [docs, setDocs] = useState([]);
  const [images, setImages] = useState([]);
  const [videos, setVideos] = useState([]);
  const [sensors, setSensors] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [imageUploading, setImageUploading] = useState(false);
  const [videoUploading, setVideoUploading] = useState(false);
  const [sensorDialogOpen, setSensorDialogOpen] = useState(false);
  const [sensorInput, setSensorInput] = useState('[\n  {\n    "sensor_id": "gas-01",\n    "name": "瓦斯浓度传感器",\n    "value": 1.7,\n    "unit": "%",\n    "threshold": 1.5,\n    "location": "掘进工作面",\n    "status": "报警"\n  }\n]');
  const [graphOpen, setGraphOpen] = useState(false);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphData, setGraphData] = useState({ nodes: [], links: [], stats: {} });
  const [graphKeyword, setGraphKeyword] = useState("");
  const [selectedGraphNode, setSelectedGraphNode] = useState(null);
  const [graphError, setGraphError] = useState("");
  const [graphBuildStatus, setGraphBuildStatus] = useState({ state: "idle", message: "" });
  const [graphExpanding, setGraphExpanding] = useState(false);
  const [graphExpandedNodes, setGraphExpandedNodes] = useState([]);
  const [graphTypeFilter, setGraphTypeFilter] = useState("all");
  const [graphRelationFilter, setGraphRelationFilter] = useState("all");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const messagesEndRef = useRef(null);
  const graphViewportRef = useRef(null);
  const forceGraphRef = useRef(null);
  const fileInputRef = useRef(null);
  const imageInputRef = useRef(null);
  const videoInputRef = useRef(null);
  const sessionIdRef = useRef(`session-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`);
  const [graphViewportSize, setGraphViewportSize] = useState({ width: 880, height: 620 });

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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
    if (!["running", "queued"].includes(graphBuildStatus.state)) return undefined;
    const timer = setInterval(async () => {
      try {
        const result = await fetchKnowledgeGraphStatus(sessionIdRef.current);
        if (!result.build_status) return;
        setGraphBuildStatus(result.build_status);
        if (result.build_status.state === "failed") {
          clearInterval(timer);
          setGraphLoading(false);
          setGraphError(result.build_status.error || "知识图谱构建失败");
        }
        if (result.build_status.state === "completed") {
          clearInterval(timer);
          setGraphLoading(false);
        }
      } catch (err) {
        clearInterval(timer);
        setGraphLoading(false);
        setGraphError(err.message);
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [graphBuildStatus.state]);

  useEffect(() => {
    if (!graphOpen) return;
    if (graphBuildStatus.state !== "completed") return;
    if (graphLoading) return;
    if (graphData.nodes.length > 0 || graphData.links.length > 0) return;
    const load = async () => {
      await loadKnowledgeGraph(graphKeyword);
    };
    load();
  }, [graphOpen, graphBuildStatus.state, graphKeyword, graphLoading, graphData.nodes.length, graphData.links.length]);

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
        if (result.knowledge_graph?.build_status) {
          setGraphBuildStatus(result.knowledge_graph.build_status);
          const latest = await fetchKnowledgeGraphStatus(sessionIdRef.current).catch(() => null);
          if (latest?.build_status) {
            setGraphBuildStatus(latest.build_status);
          }
        }
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `📄 已上传《**${result.file_name || file.name}**》（${sizeMB} MB · ${(result.char_count || 0).toLocaleString()} 字符 · ${result.chunk_count || 0} 个向量检索块）\n\n文档已入库，知识图谱正在后台构建。`,
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
  const handleImageUpload = async (e) => {
    const files = Array.from(e.target.files);
    if (!files.length) return;
    setImageUploading(true);
    
    for (const file of files) {
      try {
        if (!file.type.startsWith("image/")) {
          throw new Error("仅支持图片格式");
        }
        const sizeMB = (file.size / 1024 / 1024).toFixed(2);
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = (ev) => resolve(ev.target.result);
          reader.onerror = () => reject(new Error("图片读取失败"));
          reader.readAsDataURL(file);
        });
        
        const [, base64] = String(dataUrl).split(",");
        setImages(prev => [
          ...prev.filter(img => img.name !== file.name),
          { name: file.name, dataUrl, base64, sizeMB }
        ]);
        
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `📸 已上传图片《**${file.name}**》（${sizeMB} MB）\n\n该图片将用于现场态势识别，发送问题时会自动调用百度API进行识别。`,
          timestamp: new Date(),
        }]);
      } catch (err) {
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `⚠️ 图片《${file.name}》加载失败：${err.message}`,
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

        const sizeMB = (file.size / 1024 / 1024).toFixed(2);
        const result = await uploadVideoToBackend(file, sessionIdRef.current);
        const summaryText = result.summary_text || "";
        const evidence = Array.isArray(result.evidence) ? result.evidence : [];

        setVideos(prev => [
          ...prev.filter(v => v.name !== file.name),
          {
            name: result.video_name || file.name,
            sizeMB,
            duration_s: result.duration_s || 0,
            frames_extracted: result.frames_extracted || 0,
            frames_matched: result.frames_matched || 0,
            issue_keywords: Array.isArray(result.issue_keywords) ? result.issue_keywords : [],
            summary_text: summaryText,
            evidence,
          }
        ]);

        setMessages(prev => [...prev, {
          role: "assistant",
          content: summaryText || `🎬 已分析视频《**${result.video_name || file.name}**》`,
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

  const handleSensorSubmit = async () => {
    try {
      const records = JSON.parse(sensorInput);
      if (!Array.isArray(records) || records.length === 0) {
        throw new Error("请提供非空的传感器数组");
      }
      const result = await pushSensorsToBackend(records, sessionIdRef.current);
      const latestRecords = Array.isArray(result.latest_records) ? result.latest_records : [];
      setSensors(latestRecords);
      setSensorDialogOpen(false);
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `📡 已接入 ${latestRecords.length} 条传感器数据。\n\n${latestRecords.slice(0, 4).map(item => `- ${item.name || item.sensor_id}：${item.value_text || item.value || "未知"}${item.unit || ""}（${item.status || "状态未知"}）`).join("\n")}`,
        timestamp: new Date(),
      }]);
    } catch (err) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `⚠️ 传感器数据接入失败：${err.message}`,
        timestamp: new Date(),
      }]);
    }
  };

  // 调用百度API识别图片
  const analyzeImagesWithBaidu = async () => {
    if (images.length === 0) return { summaryText: "", evidence: [] };

    try {
      let lines = [];
      let evidence = [];
      for (const img of images.slice(0, 2)) {
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
              const keywords = data.result.slice(0, 3).map(r => r.keyword || r.class_name).join("、");
              lines.push(`【${img.name}】识别结果：${keywords}`);
              evidence.push({
                image_name: img.name,
                summary: keywords,
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
      };
    } catch (err) {
      console.warn("百度API调用失败:", err);
      return { summaryText: "", evidence: [] };
    }
  };

  const buildConversationHistory = (messageList) => {
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

    // 如果有图片，先调用百度API进行识别
    let imageSummaryText = "";
    let imageEvidence = [];
    if (images.length > 0) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: "📸 正在分析上传的图片...",
        timestamp: new Date(),
      }]);
      const imageAnalysis = await analyzeImagesWithBaidu();
      imageSummaryText = imageAnalysis.summaryText || "";
      imageEvidence = imageAnalysis.evidence || [];
      if (imageSummaryText) {
        setMessages(prev => [...prev, {
          role: "assistant",
          content: imageSummaryText,
          timestamp: new Date(),
        }]);
      }
    }

    const videoEvidence = videos.flatMap(v => Array.isArray(v.evidence) ? v.evidence : []);

    const history = buildConversationHistory(newMessages);

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 180000);

      const res = await fetch(CHAT_API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: userText,
          session_id: sessionIdRef.current,
          history,
          evidence: {
            images: [...imageEvidence, ...videoEvidence],
            sensors,
          },
          options: {
            use_session_memory: true,
            use_retrieval_evidence: true,
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
      setDocs(prev => prev.filter(item => item.document_id !== doc.document_id));
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

  const loadKnowledgeGraph = async (keyword = graphKeyword) => {
    setGraphLoading(true);
    setGraphError("");
    try {
      const data = await fetchKnowledgeGraph(sessionIdRef.current, keyword);
      const compactGraph = compactKnowledgeGraphForView(data.nodes, data.links);
      setGraphData({
        nodes: compactGraph.nodes,
        links: compactGraph.links,
        stats: {
          ...(data.stats || {}),
          view_node_count: data.view_stats?.node_count ?? compactGraph.nodes.length,
          view_relation_count: data.view_stats?.relation_count ?? compactGraph.links.length,
        },
      });
      setSelectedGraphNode(null);
      setGraphExpandedNodes([]);
    } catch (err) {
      setGraphData({ nodes: [], links: [], stats: {} });
      setSelectedGraphNode(null);
      setGraphError(err.message);
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `⚠️ 知识图谱加载失败：${err.message}`,
        timestamp: new Date(),
      }]);
    } finally {
      setGraphLoading(false);
    }
  };

  const openKnowledgeGraph = async () => {
    setGraphOpen(true);
    if (graphData.nodes.length > 0 || graphData.links.length > 0 || graphError) {
      return;
    }
    const statusResult = await fetchKnowledgeGraphStatus(sessionIdRef.current).catch(() => null);
    if (statusResult?.build_status) {
      setGraphBuildStatus(statusResult.build_status);
      if (statusResult.build_status.state === "running") {
        setGraphLoading(true);
        return;
      }
    }
    await loadKnowledgeGraph(graphKeyword);
  };

  const closeKnowledgeGraph = () => {
    setGraphOpen(false);
    setGraphLoading(false);
    setGraphExpanding(false);
    setSelectedGraphNode(null);
    setGraphError("");
  };

  const handleGraphNodeClick = async (node) => {
    setSelectedGraphNode(node);
    if (!node?.uid || graphExpandedNodes.includes(node.uid)) {
      return;
    }
    setGraphExpanding(true);
    try {
      const data = await expandKnowledgeGraph(sessionIdRef.current, node.uid, 60);
      const compactGraph = compactKnowledgeGraphForView(data.nodes, data.links);
      setGraphData(prev => mergeGraphData(prev, compactGraph));
      setGraphExpandedNodes(prev => [...prev, node.uid]);
    } catch (err) {
      setGraphError(err.message);
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `⚠️ 图谱邻居展开失败：${err.message}`,
        timestamp: new Date(),
      }]);
    } finally {
      setGraphExpanding(false);
    }
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
    hazard: "#f97316",
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
    const safeNodes = (Array.isArray(nodes) ? nodes : []).filter(node => graphTypeFilter === "all" || node.type === graphTypeFilter);
    const visibleUids = new Set(safeNodes.map(node => node.uid));
    const safeLinks = dedupeGraphLinks((Array.isArray(links) ? links : []).filter(link => (
      visibleUids.has(link.source) &&
      visibleUids.has(link.target) &&
      (graphRelationFilter === "all" || link.relation === graphRelationFilter)
    )));
    if (safeNodes.length === 0) {
      return { nodes: [], links: [] };
    }

    const graphNodes = safeNodes.map(node => ({
      ...node,
      id: node.uid,
      color: nodeColor(node.type),
      val: selectedGraphNode?.uid === node.uid ? 18 : node.type === "hazard" ? 13 : 9,
    }));
    const graphLinks = safeLinks.map(link => ({
      ...link,
      source: link.source,
      target: link.target,
    }));
    return { nodes: graphNodes, links: graphLinks };
  };

  useEffect(() => {
    if (!graphOpen) return;
    if (!forceGraphRef.current) return;
    if (!graphData.nodes.length) return;
    const timer = setTimeout(() => {
      try {
        forceGraphRef.current.zoomToFit(600, 60);
      } catch {}
    }, 180);
    return () => clearTimeout(timer);
  }, [graphOpen, graphData.nodes.length, graphData.links.length, graphTypeFilter, graphRelationFilter]);

  const renderGraphDialog = () => {
    if (!graphOpen) return null;
    const graph = buildGraphData(graphData.nodes, graphData.links);
    const stats = graphData.stats || {};
    const selectedRelations = selectedGraphNode
      ? graph.links.filter(link => {
          const sourceId = typeof link.source === "string" ? link.source : link.source?.id;
          const targetId = typeof link.target === "string" ? link.target : link.target?.id;
          return sourceId === selectedGraphNode.uid || targetId === selectedGraphNode.uid;
        })
      : [];

    return (
      <div style={{ position: "fixed", inset: 0, background: "rgba(2,6,23,0.78)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 320 }}>
        <div style={{ width: "min(1180px, 94vw)", height: "min(760px, 92vh)", background: "#08111f", border: "1px solid rgba(34,211,238,0.25)", borderRadius: "12px", boxShadow: "0 22px 70px rgba(0,0,0,0.5)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ padding: "0.8rem 1rem", borderBottom: "1px solid rgba(34,211,238,0.16)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.8rem", flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: "0.95rem", fontWeight: 800, color: "#67e8f9" }}>
                {graphKeyword.trim() ? `知识图谱检索：${graphKeyword.trim()}` : "完整知识图谱"}
              </div>
              <div style={{ fontSize: "0.65rem", color: "#64748b", marginTop: "0.15rem" }}>
                展示节点 {stats.view_node_count ?? graphData.nodes.length ?? 0} 个 · 展示关系 {stats.view_relation_count ?? graphData.links.length ?? 0} 条
                {(stats.node_count || stats.relation_count) ? `（后端保留溯源节点 ${stats.node_count || 0} 个、关系 ${stats.relation_count || 0} 条）` : ""}
              </div>
            </div>
            <div style={{ display: "flex", gap: "0.45rem", alignItems: "center", flex: "0 1 440px" }}>
              <input
                value={graphKeyword}
                onChange={e => setGraphKeyword(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") loadKnowledgeGraph(graphKeyword); }}
                placeholder="搜索节点或关键词，例如 瓦斯 / 透水 / 救护队"
                style={{ flex: 1, minWidth: 180, background: "rgba(15,23,42,0.9)", border: "1px solid rgba(34,211,238,0.22)", borderRadius: "8px", color: "#e2e8f0", padding: "0.48rem 0.65rem", outline: "none", fontSize: "0.75rem" }}
              />
              <button onClick={() => loadKnowledgeGraph(graphKeyword)} disabled={graphLoading} style={{ padding: "0.48rem 0.78rem", borderRadius: "8px", border: "1px solid rgba(34,211,238,0.28)", background: "rgba(34,211,238,0.12)", color: "#67e8f9", cursor: graphLoading ? "not-allowed" : "pointer", fontWeight: 700, fontSize: "0.72rem" }}>{graphLoading ? "加载中" : "检索"}</button>
              <button onClick={closeKnowledgeGraph} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontSize: "1.2rem", lineHeight: 1 }}>×</button>
            </div>
          </div>

          <div style={{ padding: "0.55rem 1rem", borderBottom: "1px solid rgba(34,211,238,0.10)", display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
            <select value={graphTypeFilter} onChange={e => setGraphTypeFilter(e.target.value)} style={{ background: "rgba(15,23,42,0.9)", border: "1px solid rgba(34,211,238,0.22)", borderRadius: "8px", color: "#e2e8f0", padding: "0.38rem 0.55rem", fontSize: "0.72rem" }}>
              <option value="all">全部节点类型</option>
              <option value="hazard">风险</option>
              <option value="symptom">信号</option>
              <option value="parameter">逻辑条件</option>
              <option value="sensor">监测设备</option>
              <option value="action">处置动作</option>
              <option value="department">责任部门</option>
              <option value="location">地点</option>
              <option value="equipment">设备</option>
            </select>
            <select value={graphRelationFilter} onChange={e => setGraphRelationFilter(e.target.value)} style={{ background: "rgba(15,23,42,0.9)", border: "1px solid rgba(34,211,238,0.22)", borderRadius: "8px", color: "#e2e8f0", padding: "0.38rem 0.55rem", fontSize: "0.72rem" }}>
              <option value="all">全部关系类型</option>
              <option value="indicates">征兆指向灾害</option>
              <option value="triggers_hazard">条件触发风险</option>
              <option value="monitors">监测</option>
              <option value="requires_action">需要动作</option>
              <option value="responsible_for">责任部门</option>
              <option value="occurs_at">发生场景</option>
            </select>
            <div style={{ fontSize: "0.68rem", color: graphExpanding ? "#fcd34d" : "#64748b" }}>
              {graphExpanding ? "正在展开邻居…" : "点击节点可展开一跳邻居"}
            </div>
          </div>

          <div style={{ flex: 1, display: "grid", gridTemplateColumns: "minmax(0, 1fr) 300px", minHeight: 0 }}>
            <div ref={graphViewportRef} style={{ position: "relative", overflow: "hidden", background: "radial-gradient(circle at center, rgba(34,211,238,0.08), rgba(8,17,31,0.2) 45%, rgba(8,17,31,0.95))" }}>
              {graphLoading ? (
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#94a3b8", fontSize: "0.82rem", textAlign: "center", lineHeight: 1.8 }}>
                  {graphBuildStatus.state === "queued" ? (
                    <div style={{ width: "min(420px, 82%)" }}>
                      <div style={{ marginBottom: "0.7rem" }}>图谱构建任务排队中…</div>
                      <div style={{ height: 10, background: "rgba(255,255,255,0.08)", borderRadius: 999, overflow: "hidden" }}>
                        <div style={{ width: "8%", height: "100%", background: "linear-gradient(90deg,#64748b,#22d3ee)", transition: "width 260ms ease" }} />
                      </div>
                      <div style={{ marginTop: "0.55rem", fontSize: "0.72rem", color: "#94a3b8" }}>
                        当前队列繁忙，稍后自动开始
                      </div>
                    </div>
                  ) : graphBuildStatus.state === "running" ? (
                    <div style={{ width: "min(420px, 82%)" }}>
                      <div style={{ marginBottom: "0.7rem" }}>正在用大模型抽取三元组并写入 Neo4j…</div>
                      <div style={{ height: 10, background: "rgba(255,255,255,0.08)", borderRadius: 999, overflow: "hidden" }}>
                        <div style={{ width: `${graphBuildStatus.progress_percent || 0}%`, height: "100%", background: "linear-gradient(90deg,#22d3ee,#4ade80)", transition: "width 260ms ease" }} />
                      </div>
                      <div style={{ marginTop: "0.55rem", fontSize: "0.72rem", color: "#67e8f9" }}>
                        {graphBuildStatus.current || 0}/{graphBuildStatus.total || 0} · {graphBuildStatus.progress_percent || 0}%
                      </div>
                    </div>
                  ) : "正在从 Neo4j 加载知识图谱…"}
                </div>
              ) : graphError ? (
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#fca5a5", fontSize: "0.8rem", textAlign: "center", lineHeight: 1.8, padding: "0 1.5rem" }}>
                  图谱加载失败
                  <br />
                  {graphError}
                </div>
              ) : graph.nodes.length === 0 ? (
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#64748b", fontSize: "0.82rem", textAlign: "center", lineHeight: 1.8 }}>
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
                  linkColor={() => "rgba(148,163,184,0.34)"}
                  linkWidth={(link) => link.duplicateCount > 1 ? 1.6 : 1}
                  nodeColor={(node) => node.color}
                  nodeVal={(node) => node.val}
                  nodeLabel={(node) => `${node.label || node.id || ""}${node.type ? ` (${node.type})` : ""}`}
                  linkLabel={(link) => [link.relation_label, link.condition].filter(Boolean).join(" | ")}
                  nodeCanvasObjectMode={() => "after"}
                  nodeCanvasObject={(node, ctx, globalScale) => {
                    const label = String(node.label || node.id || "");
                    const fontSize = Math.max(8, 10 / globalScale);
                    ctx.font = `${fontSize}px sans-serif`;
                    ctx.textAlign = "left";
                    ctx.textBaseline = "middle";
                    ctx.fillStyle = "#dbeafe";
                    ctx.fillText(label.slice(0, 18), node.x + 8, node.y);
                    if (graphExpandedNodes.includes(node.uid)) {
                      ctx.font = `${Math.max(7, 9 / globalScale)}px sans-serif`;
                      ctx.fillStyle = "#67e8f9";
                      ctx.textAlign = "center";
                      ctx.fillText("已展开", node.x, node.y - 12);
                    }
                  }}
                  linkCanvasObjectMode={() => "after"}
                  linkCanvasObject={(link, ctx, globalScale) => {
                    const start = link.source;
                    const end = link.target;
                    if (!start?.x || !end?.x) return;
                    const midX = (start.x + end.x) / 2;
                    const midY = (start.y + end.y) / 2;
                    if (link.condition) {
                      ctx.font = `${Math.max(7, 9 / globalScale)}px sans-serif`;
                      ctx.fillStyle = "#fcd34d";
                      ctx.textAlign = "center";
                      ctx.fillText(String(link.condition).slice(0, 18), midX, midY - 6);
                    }
                  }}
                  onNodeClick={handleGraphNodeClick}
                />
              )}
            </div>

            <div style={{ borderLeft: "1px solid rgba(34,211,238,0.14)", padding: "0.8rem", overflowY: "auto", background: "rgba(15,23,42,0.36)" }}>
              <div style={{ fontSize: "0.75rem", color: "#67e8f9", fontWeight: 800, marginBottom: "0.55rem" }}>图谱详情</div>
              {selectedGraphNode ? (
                <div style={{ display: "grid", gap: "0.45rem", fontSize: "0.68rem", color: "#cbd5e1", lineHeight: 1.6 }}>
                  <div style={{ fontSize: "0.86rem", color: nodeColor(selectedGraphNode.type), fontWeight: 800 }}>{selectedGraphNode.label}</div>
                  <div><span style={{ color: "#94a3b8" }}>类型：</span>{selectedGraphNode.type_label || selectedGraphNode.type}</div>
                  {selectedGraphNode.text_excerpt && <div style={{ color: "#94a3b8", whiteSpace: "pre-wrap" }}>{selectedGraphNode.text_excerpt}</div>}
                  {Array.isArray(selectedGraphNode.sources) && selectedGraphNode.sources.length > 0 && (
                    <div>
                      <span style={{ color: "#94a3b8" }}>来源：</span>
                      <div style={{ marginTop: "0.25rem", display: "grid", gap: "0.25rem" }}>
                        {selectedGraphNode.sources.slice(0, 5).map((source, idx) => (
                          <div key={`${source}-${idx}`} style={{ padding: "0.28rem 0.4rem", borderRadius: "6px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)", color: "#a7f3d0" }}>{source}</div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div style={{ marginTop: "0.4rem", color: "#67e8f9", fontWeight: 800 }}>相邻关系</div>
                  {selectedRelations.length === 0 ? (
                    <div style={{ color: "#64748b" }}>暂无相邻关系</div>
                  ) : selectedRelations.slice(0, 10).map((rel, idx) => (
                    <div key={`${rel.id || idx}`} style={{ padding: "0.42rem 0.48rem", borderRadius: "7px", background: "rgba(255,255,255,0.035)", border: "1px solid rgba(255,255,255,0.06)" }}>
                      <span style={{ color: "#fef08a" }}>{rel.head_label}</span>
                      <span style={{ color: "#94a3b8" }}> → {rel.relation_label} → </span>
                      <span style={{ color: "#bfdbfe" }}>{rel.tail_label}</span>
                      {rel.source_ref && <div style={{ color: "#64748b", marginTop: "0.15rem" }}>{rel.source_ref}</div>}
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ color: "#64748b", fontSize: "0.7rem", lineHeight: 1.8 }}>
                  图谱现在采用与 Neo4j Browser 更接近的力导向布局。点击节点可展开邻居，用筛选器收缩视图，文档和条款仍默认隐藏，仅作为来源追溯。
                  <div style={{ marginTop: "0.8rem", display: "flex", gap: "0.28rem", flexWrap: "wrap" }}>
                    {Object.entries({
                      sensor: "传感器",
                      symptom: "信号",
                      parameter: "条件",
                      hazard: "风险",
                      action: "动作",
                      department: "部门",
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
      <details style={{ marginTop: "0.55rem", background: "rgba(15,23,42,0.35)", border: "1px solid rgba(74,222,128,0.14)", borderRadius: "8px", padding: "0.45rem 0.6rem" }}>
        <summary style={{ cursor: "pointer", color: "#86efac", fontSize: "0.68rem", fontWeight: 700 }}>本次推理说明</summary>
        <div style={{ marginTop: "0.45rem", display: "grid", gap: "0.35rem", fontSize: "0.65rem", color: "#cbd5e1", lineHeight: 1.6 }}>
          <div><span style={{ color: "#86efac" }}>路由方式：</span>{meta.route_mode || "未知"}</div>
          <div><span style={{ color: "#86efac" }}>路由原因：</span>{meta.route_reason || "无"}</div>
          <div>
            <span style={{ color: "#86efac" }}>激活角色：</span>
            {selectedAgents.length > 0 ? selectedAgents.join("、") : "无"}
          </div>
          <div>
            <span style={{ color: "#86efac" }}>风险识别：</span>
            {risk.risk_level ? `${risk.risk_level}风险` : "未识别"}
            {Array.isArray(risk.risk_type_labels) && risk.risk_type_labels.length > 0 ? `（${risk.risk_type_labels.join("、")}）` : ""}
          </div>
          <div>
            <span style={{ color: "#86efac" }}>证据使用：</span>
            文档 {docEvidence.length} 条，图片 {stillImageEvidenceCount} 条，视频 {videoEvidenceCount} 帧
          </div>
          <div>
            <span style={{ color: "#86efac" }}>会话记忆：</span>
            {memory.history_messages || 0} 条历史消息，最终会话 {memory.session_history_messages || 0} 条
          </div>
          <div>
            <span style={{ color: "#86efac" }}>图谱命中：</span>
            节点 {kgUsed.node_count || 0} 个，关系 {kgUsed.relation_count || 0} 条，相关关系 {matchedRelations.length} 条
          </div>
          <div>
            <span style={{ color: "#86efac" }}>多源融合：</span>
            {sourceFusion.history_used ? "使用历史" : "未使用历史"}，文档 {sourceFusion.document_count || 0} 份，图像/视频证据 {sourceFusion.image_count || 0} 条
          </div>

          {docEvidence.length > 0 && (
            <div>
              <span style={{ color: "#86efac" }}>文档证据：</span>
              <div style={{ marginTop: "0.18rem", display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                {docEvidence.map((doc, idx) => (
                  <span key={`${doc.doc_name || "doc"}-${idx}`} style={{ padding: "0.08rem 0.38rem", borderRadius: "999px", background: "rgba(74,222,128,0.12)", border: "1px solid rgba(74,222,128,0.2)", color: "#bbf7d0" }}>
                    {(doc.doc_name || "未知文档")}{doc.chunk_id ? ` · ${doc.chunk_id}` : ""}
                  </span>
                ))}
              </div>
            </div>
          )}

          {imageEvidence.length > 0 && (
            <div>
              <span style={{ color: "#86efac" }}>图片证据：</span>
              <div style={{ marginTop: "0.18rem", display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                {imageEvidence.map((img, idx) => (
                  <span key={`${img.image_name || "img"}-${idx}`} style={{ padding: "0.08rem 0.38rem", borderRadius: "999px", background: "rgba(59,130,246,0.12)", border: "1px solid rgba(59,130,246,0.2)", color: "#bfdbfe" }}>
                    {img.image_name || "未知图片"}{String(img.source_type || "") === "video_analysis" ? "（视频帧）" : ""}
                  </span>
                ))}
              </div>
            </div>
          )}

          {riskSignals.length > 0 && (
            <div>
              <span style={{ color: "#86efac" }}>风险触发信号：</span>
              <div style={{ marginTop: "0.18rem", display: "grid", gap: "0.2rem" }}>
                {riskSignals.slice(0, 6).map((signal, idx) => (
                  <div key={`${signal.signal_id || "signal"}-${idx}`} style={{ color: "#94a3b8" }}>
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
              <span style={{ color: "#86efac" }}>命中实体：</span>
              <div style={{ marginTop: "0.18rem", display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                {matchedNodes.slice(0, 8).map((node) => (
                  <span key={node.id} style={{ padding: "0.08rem 0.38rem", borderRadius: "999px", background: "rgba(168,85,247,0.12)", border: "1px solid rgba(168,85,247,0.2)", color: "#e9d5ff" }}>
                    {node.label}{node.type ? ` · ${node.type}` : ""}
                  </span>
                ))}
              </div>
            </div>
          )}

          {matchedRelations.length > 0 && (
            <div>
              <span style={{ color: "#86efac" }}>命中关系链：</span>
              <div style={{ marginTop: "0.18rem", display: "grid", gap: "0.2rem" }}>
                {matchedRelations.slice(0, 6).map((rel, idx) => (
                  <div key={`${rel.head_id || "h"}-${rel.tail_id || "t"}-${idx}`} style={{ color: "#cbd5e1", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: "6px", padding: "0.28rem 0.42rem" }}>
                    <span style={{ color: "#fef08a" }}>{rel.head_label || rel.head_id}</span>
                    <span style={{ color: "#94a3b8" }}> → {rel.relation_label || rel.relation} → </span>
                    <span style={{ color: "#bfdbfe" }}>{rel.tail_label || rel.tail_id}</span>
                    {rel.source ? <span style={{ color: "#64748b" }}>（{rel.source}）</span> : null}
                  </div>
                ))}
              </div>
            </div>
          )}

          {risk.summary && (
            <div style={{ whiteSpace: "pre-wrap", color: "#94a3b8" }}>
              <span style={{ color: "#86efac" }}>风险摘要：</span>{risk.summary}
            </div>
          )}
          {kgUsed.summary && (
            <div style={{ whiteSpace: "pre-wrap", color: "#94a3b8" }}>
              <span style={{ color: "#86efac" }}>图谱摘要：</span>{kgUsed.summary}
            </div>
          )}
        </div>
      </details>
    );
  };

  return (
    <div style={{ height: "100vh", background: "linear-gradient(135deg,#0a0f1e,#0d1b2a,#0a1628)", fontFamily: "'Noto Sans SC','PingFang SC',sans-serif", color: "#e2e8f0", display: "flex", flexDirection: "column" }}>

      {/* Alert */}
      {alertLevel && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, zIndex: 200, background: alertLevel === "red" ? "rgba(239,68,68,0.96)" : "rgba(245,158,11,0.96)", padding: "0.7rem 2rem", textAlign: "center", fontWeight: 700, fontSize: "0.9rem", animation: "slideDown 0.3s ease" }}>
          {alertLevel === "red" ? "🚨 检测到高危情况 — 多智能体紧急协同启动" : "⚠️ 检测到风险信号 — 态势感知智能体已激活"}
        </div>
      )}

      {/* Header */}
      <div style={{ background: "rgba(255,255,255,0.03)", backdropFilter: "blur(20px)", borderBottom: "1px solid rgba(74,222,128,0.2)", padding: "0.8rem 1.25rem", display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0, gap: "1rem", flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.8rem" }}>
          <div style={{ width: 40, height: 40, background: "linear-gradient(135deg,#4ade80,#22d3ee)", borderRadius: "9px", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "1.2rem", boxShadow: "0 0 18px rgba(74,222,128,0.4)", flexShrink: 0 }}>⛏</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: "0.95rem" }}>煤矿应急救援决策 AI 智能体</div>
            <div style={{ fontSize: "0.68rem", color: "#64748b", marginTop: "0.1rem" }}>中国矿业大学 · 煤炭无人化开采数智技术全国重点实验室</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
          {AGENTS.map(a => (
            <div key={a.id} style={{ display: "flex", alignItems: "center", gap: "0.25rem", padding: "0.22rem 0.5rem", background: activeAgents.includes(a.id) ? `${a.color}20` : "rgba(255,255,255,0.04)", border: `1px solid ${activeAgents.includes(a.id) ? a.color : "rgba(255,255,255,0.08)"}`, borderRadius: "5px", fontSize: "0.65rem", transition: "all 0.3s", boxShadow: activeAgents.includes(a.id) ? `0 0 8px ${a.color}44` : "none" }}>
              <span style={{ width: 5, height: 5, borderRadius: "50%", background: activeAgents.includes(a.id) ? a.color : "#374151", animation: activeAgents.includes(a.id) ? "pulse 1s infinite" : "none", flexShrink: 0 }} />
              <span style={{ color: activeAgents.includes(a.id) ? a.color : "#6b7280" }}>{a.icon} {a.name}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>

        {/* Sidebar */}
        <div style={{ width: sidebarOpen ? 240 : 48, flexShrink: 0, background: "rgba(255,255,255,0.02)", borderRight: "1px solid rgba(74,222,128,0.1)", display: "flex", flexDirection: "column", transition: "width 0.3s ease", overflow: "hidden" }}>
          {/* Sidebar header */}
          <div style={{ padding: "0.65rem 0.55rem", borderBottom: "1px solid rgba(74,222,128,0.1)", display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <button onClick={() => setSidebarOpen(v => !v)} title="规程知识库" style={{ width: 34, height: 34, borderRadius: "7px", flexShrink: 0, background: sidebarOpen ? "rgba(74,222,128,0.15)" : "rgba(255,255,255,0.05)", border: "1px solid rgba(74,222,128,0.3)", color: "#4ade80", cursor: "pointer", fontSize: "0.95rem", display: "flex", alignItems: "center", justifyContent: "center" }}>📂</button>
            {sidebarOpen && <span style={{ fontSize: "0.76rem", fontWeight: 700, color: "#94a3b8", whiteSpace: "nowrap" }}>规程知识库{docs.length > 0 && <span style={{ color: "#4ade80" }}> ({docs.length})</span>}</span>}
          </div>

          {sidebarOpen && (
            <>
              {/* Upload */}
              <div style={{ padding: "0.55rem" }}>
                <input ref={fileInputRef} type="file" accept=".txt,.docx,.pdf" multiple onChange={handleUpload} style={{ display: "none" }} />
                <input ref={imageInputRef} type="file" accept="image/*" multiple onChange={handleImageUpload} style={{ display: "none" }} />
                <input ref={videoInputRef} type="file" accept="video/*" multiple onChange={handleVideoUpload} style={{ display: "none" }} />
                <button onClick={() => fileInputRef.current?.click()} disabled={uploading} style={{ width: "100%", padding: "0.5rem", background: "linear-gradient(135deg,rgba(74,222,128,0.15),rgba(34,211,238,0.1))", border: "1px dashed rgba(74,222,128,0.45)", borderRadius: "7px", color: uploading ? "#4ade8055" : "#4ade80", cursor: uploading ? "not-allowed" : "pointer", fontSize: "0.73rem", fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: "0.35rem" }}>
                  {uploading ? "⏳ 解析中..." : "＋ 上传规程文档"}
                </button>
                <div style={{ fontSize: "0.6rem", color: "#475569", textAlign: "center", marginTop: "0.3rem" }}>TXT · DOCX · PDF</div>
                
                <button onClick={() => imageInputRef.current?.click()} disabled={imageUploading} style={{ width: "100%", padding: "0.5rem", marginTop: "0.45rem", background: "linear-gradient(135deg,rgba(59,130,246,0.15),rgba(14,165,233,0.1))", border: "1px dashed rgba(59,130,246,0.45)", borderRadius: "7px", color: imageUploading ? "#60a5fa55" : "#60a5fa", cursor: imageUploading ? "not-allowed" : "pointer", fontSize: "0.73rem", fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: "0.35rem" }}>
                  {imageUploading ? "📸 上传中..." : "📸 上传现场图片"}
                </button>
                <div style={{ fontSize: "0.6rem", color: "#475569", textAlign: "center", marginTop: "0.3rem" }}>JPG · PNG · WEBP</div>

                <button onClick={() => videoInputRef.current?.click()} disabled={videoUploading} style={{ width: "100%", padding: "0.5rem", marginTop: "0.45rem", background: "linear-gradient(135deg,rgba(245,158,11,0.15),rgba(249,115,22,0.1))", border: "1px dashed rgba(245,158,11,0.45)", borderRadius: "7px", color: videoUploading ? "#f59e0b55" : "#f59e0b", cursor: videoUploading ? "not-allowed" : "pointer", fontSize: "0.73rem", fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: "0.35rem" }}>
                  {videoUploading ? "🎬 分析中..." : "🎬 上传现场视频"}
                </button>
                <div style={{ fontSize: "0.6rem", color: "#475569", textAlign: "center", marginTop: "0.3rem" }}>MP4 · WEBM · MOV</div>

                <button onClick={() => setSensorDialogOpen(true)} style={{ width: "100%", padding: "0.5rem", marginTop: "0.45rem", background: "linear-gradient(135deg,rgba(168,85,247,0.15),rgba(99,102,241,0.1))", border: "1px dashed rgba(168,85,247,0.45)", borderRadius: "7px", color: "#c084fc", cursor: "pointer", fontSize: "0.73rem", fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: "0.35rem" }}>
                  📡 接入传感器数据
                </button>
                <div style={{ fontSize: "0.6rem", color: "#475569", textAlign: "center", marginTop: "0.3rem" }}>JSON · HTTP 推送</div>

                <button onClick={openKnowledgeGraph} disabled={graphLoading && graphBuildStatus.state !== "running"} style={{ width: "100%", padding: "0.5rem", marginTop: "0.45rem", background: "linear-gradient(135deg,rgba(34,211,238,0.14),rgba(20,184,166,0.1))", border: "1px dashed rgba(34,211,238,0.45)", borderRadius: "7px", color: graphLoading && graphBuildStatus.state !== "running" ? "#22d3ee55" : "#67e8f9", cursor: graphLoading && graphBuildStatus.state !== "running" ? "not-allowed" : "pointer", fontSize: "0.73rem", fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: "0.35rem" }}>
                  {graphBuildStatus.state === "queued"
                    ? "🧠 图谱排队中..."
                    : graphBuildStatus.state === "running"
                    ? `🧠 图谱构建中 ${graphBuildStatus.progress_percent || 0}%`
                    : graphLoading
                      ? "🧠 加载图谱..."
                      : "🧠 查看知识图谱"}
                </button>
                <div style={{ fontSize: "0.6rem", color: "#475569", textAlign: "center", marginTop: "0.3rem" }}>实体 · 关系 · 条款来源</div>
              </div>

              {/* Doc list */}
              <div style={{ flex: 1, overflowY: "auto", padding: "0 0.55rem 0.55rem" }}>
                {docs.length === 0 ? (
                  <div style={{ padding: "1.2rem 0.4rem", textAlign: "center", color: "#374151", fontSize: "0.7rem", lineHeight: 1.7 }}>
                    暂无文档<br />上传后智能体将<br />优先参考规程内容
                  </div>
                ) : docs.map((doc, i) => (
                  <div key={i} style={{ padding: "0.5rem", background: "rgba(74,222,128,0.06)", border: "1px solid rgba(74,222,128,0.15)", borderRadius: "7px", marginBottom: "0.35rem", display: "flex", alignItems: "flex-start", gap: "0.35rem" }}>
                    <span style={{ fontSize: "0.9rem", flexShrink: 0 }}>{fileIcon(doc.name)}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: "0.7rem", fontWeight: 600, color: "#a3e635", wordBreak: "break-all", lineHeight: 1.3 }}>{doc.name}</div>
                      <div style={{ fontSize: "0.6rem", color: "#475569", marginTop: "0.12rem" }}>{doc.sizeMB} MB · {(doc.charCount || 0).toLocaleString()} 字符 · {doc.chunkCount || 0} 块</div>
                      {(doc.graphNodeCount || doc.graphRelationCount) ? (
                        <div style={{ fontSize: "0.58rem", color: "#22d3ee", marginTop: "0.12rem" }}>
                          图谱 {doc.graphNodeCount || 0} 节点 · {doc.graphRelationCount || 0} 关系
                        </div>
                      ) : null}
                    </div>
                    <button onClick={() => removeUploadedDocument(doc)} style={{ background: "none", border: "none", color: "#475569", cursor: "pointer", fontSize: "0.85rem", flexShrink: 0, padding: 0, lineHeight: 1 }}>×</button>
                  </div>
                ))}
                
                {images.length > 0 && (
                  <div style={{ marginTop: "0.65rem" }}>
                    <div style={{ fontSize: "0.7rem", color: "#60a5fa", marginBottom: "0.35rem", fontWeight: 700 }}>📸 上传的图片</div>
                    {images.map((img, i) => (
                      <div key={i} style={{ padding: "0.5rem", background: "rgba(59,130,246,0.08)", border: "1px solid rgba(59,130,246,0.18)", borderRadius: "7px", marginBottom: "0.35rem", display: "flex", alignItems: "center", gap: "0.45rem" }}>
                        <div style={{ width: 36, height: 36, borderRadius: "6px", background: "rgba(15,23,42,0.6)", overflow: "hidden", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
                          <img src={img.dataUrl} alt={img.name} style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "cover" }} />
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: "0.7rem", fontWeight: 600, color: "#93c5fd", wordBreak: "break-all", lineHeight: 1.3 }}>{img.name}</div>
                          <div style={{ fontSize: "0.6rem", color: "#475569", marginTop: "0.12rem" }}>{img.sizeMB} MB</div>
                        </div>
                        <button onClick={() => setImages(prev => prev.filter(i2 => i2.name !== img.name))} style={{ background: "none", border: "none", color: "#475569", cursor: "pointer", fontSize: "0.85rem", flexShrink: 0, padding: 0, lineHeight: 1 }}>×</button>
                      </div>
                    ))}
                  </div>
                )}

                {videos.length > 0 && (
                  <div style={{ marginTop: "0.65rem" }}>
                    <div style={{ fontSize: "0.7rem", color: "#f59e0b", marginBottom: "0.35rem", fontWeight: 700 }}>🎬 上传的视频</div>
                    {videos.map((video, i) => (
                      <div key={i} style={{ padding: "0.5rem", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.18)", borderRadius: "7px", marginBottom: "0.35rem", display: "flex", alignItems: "flex-start", gap: "0.45rem" }}>
                        <div style={{ width: 36, height: 36, borderRadius: "6px", background: "rgba(15,23,42,0.6)", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "#fbbf24", fontSize: "0.9rem" }}>🎞</div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: "0.7rem", fontWeight: 600, color: "#fbbf24", wordBreak: "break-all", lineHeight: 1.3 }}>{video.name}</div>
                          <div style={{ fontSize: "0.6rem", color: "#64748b", marginTop: "0.12rem" }}>
                            {video.sizeMB} MB · {video.frames_extracted || 0} 帧 · {video.frames_matched || 0} 帧命中
                          </div>
                          {video.issue_keywords && video.issue_keywords.length > 0 && (
                            <div style={{ marginTop: "0.28rem", display: "flex", gap: "0.2rem", flexWrap: "wrap" }}>
                              {video.issue_keywords.slice(0, 4).map((kw, idx) => (
                                <span key={`${kw}-${idx}`} style={{ padding: "0.05rem 0.35rem", borderRadius: "999px", background: "rgba(245,158,11,0.12)", border: "1px solid rgba(245,158,11,0.22)", color: "#fde68a", fontSize: "0.6rem" }}>{kw}</span>
                              ))}
                            </div>
                          )}
                          {video.summary_text && (
                            <div style={{ fontSize: "0.58rem", color: "#94a3b8", marginTop: "0.25rem", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                              {video.summary_text.split("\n").slice(0, 3).join("\n")}
                            </div>
                          )}
                        </div>
                        <button onClick={() => setVideos(prev => prev.filter(v => v.name !== video.name))} style={{ background: "none", border: "none", color: "#475569", cursor: "pointer", fontSize: "0.85rem", flexShrink: 0, padding: 0, lineHeight: 1 }}>×</button>
                      </div>
                    ))}
                  </div>
                )}

                {sensors.length > 0 && (
                  <div style={{ marginTop: "0.65rem" }}>
                    <div style={{ fontSize: "0.7rem", color: "#c084fc", marginBottom: "0.35rem", fontWeight: 700 }}>📡 传感器数据</div>
                    {sensors.map((sensor, i) => (
                      <div key={i} style={{ padding: "0.5rem", background: "rgba(168,85,247,0.08)", border: "1px solid rgba(168,85,247,0.18)", borderRadius: "7px", marginBottom: "0.35rem", display: "flex", alignItems: "flex-start", gap: "0.45rem" }}>
                        <div style={{ width: 36, height: 36, borderRadius: "6px", background: "rgba(15,23,42,0.6)", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "#c084fc", fontSize: "0.9rem" }}>📟</div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: "0.7rem", fontWeight: 600, color: "#d8b4fe", wordBreak: "break-all", lineHeight: 1.3 }}>{sensor.name || sensor.sensor_id}</div>
                          <div style={{ fontSize: "0.6rem", color: "#64748b", marginTop: "0.12rem" }}>
                            {(sensor.value_text || sensor.value || "未知")}{sensor.unit || ""} · {sensor.location || "未知位置"} · {sensor.status || "状态未知"}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* Chat */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Messages */}
          <div style={{ flex: 1, overflowY: "auto", padding: "1.1rem 1.25rem", display: "flex", flexDirection: "column", gap: "0.9rem" }}>
            {messages.map((msg, i) => (
              <div key={i} style={{ display: "flex", justifyContent: msg.role === "user" ? "flex-end" : "flex-start", animation: "fadeUp 0.3s ease" }}>
                {msg.role === "assistant" && (
                  <div style={{ width: 32, height: 32, borderRadius: "8px", flexShrink: 0, background: "linear-gradient(135deg,#4ade80,#22d3ee)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.9rem", marginRight: "0.6rem", marginTop: "0.2rem", boxShadow: "0 0 10px rgba(74,222,128,0.3)" }}>⛏</div>
                )}
                <div style={{ maxWidth: "76%", background: msg.role === "user" ? "linear-gradient(135deg,#1d4ed8,#1e40af)" : "rgba(255,255,255,0.05)", border: msg.role === "user" ? "1px solid rgba(59,130,246,0.4)" : "1px solid rgba(74,222,128,0.15)", borderRadius: msg.role === "user" ? "14px 4px 14px 14px" : "4px 14px 14px 14px", padding: "0.75rem 0.95rem", fontSize: "0.85rem", lineHeight: "1.7", backdropFilter: "blur(10px)", textAlign: "left" }}>
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
                <div style={{ padding: "0.75rem 0.95rem", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(74,222,128,0.15)", borderRadius: "4px 14px 14px 14px", fontSize: "0.82rem", color: "#94a3b8" }}>
                  <span>多智能体协同推理中</span><span className="dots">...</span>
                  {docs.length > 0 && <div style={{ fontSize: "0.63rem", color: "#4ade80", marginTop: "0.2rem" }}>📄 正在检索 {docs.length} 份规程文档</div>}
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

          {/* Quick questions */}
          <div style={{ padding: "0 1.25rem 0.55rem" }}>
            <div style={{ display: "flex", gap: "0.38rem", flexWrap: "wrap" }}>
              {QUICK_QUESTIONS.map((q, i) => (
                <button key={i} onClick={() => sendMessage(q.text)} disabled={loading}
                  style={{ padding: "0.32rem 0.75rem", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(74,222,128,0.2)", borderRadius: "20px", color: "#94a3b8", fontSize: "0.7rem", cursor: "pointer", transition: "all 0.2s" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "rgba(74,222,128,0.1)"; e.currentTarget.style.borderColor = "rgba(74,222,128,0.5)"; e.currentTarget.style.color = "#4ade80"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "rgba(255,255,255,0.04)"; e.currentTarget.style.borderColor = "rgba(74,222,128,0.2)"; e.currentTarget.style.color = "#94a3b8"; }}
                >{q.icon} {q.text}</button>
              ))}
            </div>
          </div>

          {/* Input */}
          <div style={{ padding: "0 1.25rem 1.1rem" }}>
            {(docs.length > 0 || images.length > 0 || videos.length > 0) && (
              <div style={{ marginBottom: "0.45rem" }}>
                {docs.length > 0 && (
                  <div style={{ marginBottom: "0.35rem", padding: "0.3rem 0.7rem", background: "rgba(74,222,128,0.07)", border: "1px solid rgba(74,222,128,0.2)", borderRadius: "7px", fontSize: "0.65rem", color: "#4ade80", display: "flex", alignItems: "center", gap: "0.35rem" }}>
                    📄 已加载 {docs.length} 份规程
                  </div>
                )}
                {images.length > 0 && (
                  <div style={{ padding: "0.3rem 0.7rem", background: "rgba(59,130,246,0.07)", border: "1px solid rgba(59,130,246,0.2)", borderRadius: "7px", fontSize: "0.65rem", color: "#60a5fa", display: "flex", alignItems: "center", gap: "0.35rem" }}>
                    📸 已上传 {images.length} 张图片（将进行百度识别分析）
                  </div>
                )}
                {videos.length > 0 && (
                  <div style={{ marginTop: "0.35rem", padding: "0.3rem 0.7rem", background: "rgba(245,158,11,0.07)", border: "1px solid rgba(245,158,11,0.2)", borderRadius: "7px", fontSize: "0.65rem", color: "#f59e0b", display: "flex", alignItems: "center", gap: "0.35rem" }}>
                    🎬 已上传 {videos.length} 段视频（将进行抽帧分析）
                  </div>
                )}
                {sensors.length > 0 && (
                  <div style={{ marginTop: "0.35rem", padding: "0.3rem 0.7rem", background: "rgba(168,85,247,0.07)", border: "1px solid rgba(168,85,247,0.2)", borderRadius: "7px", fontSize: "0.65rem", color: "#c084fc", display: "flex", alignItems: "center", gap: "0.35rem" }}>
                    📡 已接入 {sensors.length} 条传感器数据
                  </div>
                )}
              </div>
            )}
            <div style={{ display: "flex", gap: "0.6rem", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(74,222,128,0.25)", borderRadius: "13px", padding: "0.4rem 0.4rem 0.4rem 0.85rem", backdropFilter: "blur(20px)", boxShadow: "0 0 25px rgba(74,222,128,0.05)" }}>
              <button onClick={() => fileInputRef.current?.click()} title="上传规程文档" style={{ width: 34, height: 34, borderRadius: "7px", flexShrink: 0, alignSelf: "flex-end", background: "rgba(74,222,128,0.1)", border: "1px solid rgba(74,222,128,0.3)", color: "#4ade80", cursor: "pointer", fontSize: "0.95rem", display: "flex", alignItems: "center", justifyContent: "center" }}>📎</button>
              <button onClick={() => imageInputRef.current?.click()} title="上传现场图片" style={{ width: 34, height: 34, borderRadius: "7px", flexShrink: 0, alignSelf: "flex-end", background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.3)", color: "#60a5fa", cursor: "pointer", fontSize: "0.95rem", display: "flex", alignItems: "center", justifyContent: "center" }}>📸</button>
              <button onClick={() => videoInputRef.current?.click()} title="上传现场视频" style={{ width: 34, height: 34, borderRadius: "7px", flexShrink: 0, alignSelf: "flex-end", background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.3)", color: "#f59e0b", cursor: "pointer", fontSize: "0.95rem", display: "flex", alignItems: "center", justifyContent: "center" }}>🎬</button>
              <button onClick={() => setSensorDialogOpen(true)} title="接入传感器数据" style={{ width: 34, height: 34, borderRadius: "7px", flexShrink: 0, alignSelf: "flex-end", background: "rgba(168,85,247,0.1)", border: "1px solid rgba(168,85,247,0.3)", color: "#c084fc", cursor: "pointer", fontSize: "0.95rem", display: "flex", alignItems: "center", justifyContent: "center" }}>📡</button>
              <textarea value={input} onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
                placeholder="描述灾害情况或输入应急问题（Shift+Enter换行）..." rows={2}
                style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "#e2e8f0", fontSize: "0.85rem", lineHeight: "1.6", resize: "none", fontFamily: "inherit" }} />
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
      </div>

      {sensorDialogOpen && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(2,6,23,0.72)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 300 }}>
          <div style={{ width: "min(720px, 92vw)", background: "#0f172a", border: "1px solid rgba(168,85,247,0.28)", borderRadius: "12px", boxShadow: "0 18px 60px rgba(0,0,0,0.45)", padding: "1rem" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.8rem" }}>
              <div style={{ fontSize: "0.9rem", fontWeight: 800, color: "#d8b4fe" }}>传感器数据接入</div>
              <button onClick={() => setSensorDialogOpen(false)} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontSize: "1rem" }}>×</button>
            </div>
            <div style={{ fontSize: "0.68rem", color: "#94a3b8", lineHeight: 1.7, marginBottom: "0.6rem" }}>
              在这里粘贴传感器 JSON 数组，提交后会进入当前会话，并参与风险识别和多智能体问答。
            </div>
            <textarea
              value={sensorInput}
              onChange={e => setSensorInput(e.target.value)}
              rows={14}
              style={{ width: "100%", background: "rgba(15,23,42,0.9)", border: "1px solid rgba(168,85,247,0.2)", borderRadius: "10px", color: "#e2e8f0", fontSize: "0.75rem", lineHeight: 1.6, padding: "0.8rem", resize: "vertical", fontFamily: "Consolas, 'Courier New', monospace", outline: "none" }}
            />
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.6rem", marginTop: "0.8rem" }}>
              <button onClick={() => setSensorDialogOpen(false)} style={{ padding: "0.45rem 0.9rem", borderRadius: "8px", border: "1px solid rgba(148,163,184,0.2)", background: "rgba(255,255,255,0.04)", color: "#cbd5e1", cursor: "pointer" }}>取消</button>
              <button onClick={handleSensorSubmit} style={{ padding: "0.45rem 0.9rem", borderRadius: "8px", border: "none", background: "linear-gradient(135deg,#a855f7,#6366f1)", color: "#f8fafc", fontWeight: 700, cursor: "pointer" }}>接入数据</button>
            </div>
          </div>
        </div>
      )}

      {renderGraphDialog()}

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
