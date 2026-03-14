import { useState, useRef, useEffect } from "react";
import * as mammoth from "mammoth";
import * as pdfjsLib from "pdfjs-dist";
import Fuse from "fuse.js";

const LONGCAT_API_KEY = "ak_2ho0is8Y064o6Bd1UI80m0Ab1mL5n";
const LONGCAT_BASE_URL = "https://api.longcat.chat/anthropic";
const LONGCAT_MODEL = "LongCat-Flash-Thinking-2601";

const BASE_SYSTEM_PROMPT = `你是一个专业的煤矿应急救援决策知识问答AI智能体，基于中国矿业大学袁冠团队的研究成果构建。

你的核心能力包括：
1. **应急知识问答**：基于煤矿作业规程、事故案例、应急预案等专业知识，快速精准回答应急相关问题
2. **灾害风险识别**：识别矿井水灾、火灾、瓦斯爆炸等典型灾害场景的风险特征
3. **救援决策支持**：依据法律法规与历史救援案例，智能生成自适应救援策略
4. **安全态势感知**：分析灾变场景态势，提供"人-地-险-策"的精准协同决策支持
5. **跨域知识融合**：整合多源异构专业知识，打通信息孤岛

回答规则：
- 回答要专业、准确、具有可操作性
- 针对紧急情况，优先给出立即行动步骤，再给出详细分析
- 如果用户上传了参考文档，优先基于文档内容作答，并注明引用来源文件名
- 引用相关法律法规和历史案例支撑建议
- 使用清晰的结构化格式（如步骤、风险等级、负责部门等）
- 对于超出知识范围的问题，明确说明并建议联系专业机构

你服务于煤矿指挥中心管理人员、带班队长和一线救援队员，目标是成为他们的"随身专家"。`;

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

async function extractText(file) {
  const name = file.name.toLowerCase();
  
  // 使用Python后端解析PDF
  const formData = new FormData();
  formData.append('file', file);
  
  try {
    let endpoint = '';
    if (name.endsWith('.pdf')) {
      endpoint = '/api/parse-pdf';
    } else if (name.endsWith('.docx')) {
      endpoint = '/api/parse-docx';
    } else if (name.endsWith('.txt')) {
      endpoint = '/api/parse-text';
    } else {
      return "（不支持的文件格式，请上传 TXT、DOCX 或 PDF）";
    }
    
    // 调用Flask后端
    const response = await fetch(`http://localhost:5001${endpoint}`, {
      method: 'POST',
      body: formData
    });
    
    const result = await response.json();
    
    if (result.success) {
      return result.text;
    } else {
      return `（文件解析失败：${result.error}）`;
    }
  } catch (err) {
    // 如果后端不可用，显示提示信息
    console.error('后端连接失败:', err);
    return "（请确保Python后端服务已启动：python server/pdf_parser.py）";
  }
}

function truncate(text, max = 8000) {
  if (text.length <= max) return text;
  return text.slice(0, max) + "\n\n...[文档内容较长，已截取前部分]";
}

// 文档分块函数 - 优先按条款编号分块
function chunkText(text, chunkSize = 800) {
  const chunks = [];
  
  // 第一步：按"第X条"分段（优先级最高）
  const articlePattern = /(?=第[一二三四五六七八九十百千万\d]+条)/;
  const articles = text.split(articlePattern).filter(p => p.trim());
  
  // 第二步：对每个条款进行细分
  articles.forEach(article => {
    if (article.length <= chunkSize) {
      // 如果条款本身不超长，直接加入
      if (article.trim()) chunks.push({
        text: article.trim(),
        index: chunks.length
      });
    } else {
      // 条款过长，按句号分段
      const sentences = article.split(/(?<=[。；！？])/);
      let currentChunk = '';
      
      sentences.forEach(sentence => {
        if ((currentChunk + sentence).length > chunkSize && currentChunk.length > 0) {
          chunks.push({
            text: currentChunk.trim(),
            index: chunks.length
          });
          currentChunk = sentence;
        } else {
          currentChunk += sentence;
        }
      });
      
      if (currentChunk.trim()) {
        chunks.push({
          text: currentChunk.trim(),
          index: chunks.length
        });
      }
    }
  });
  
  return chunks;
}

// RAG检索函数 - 智能条款定位 + 模糊搜索混合
function retrieveRelevantChunks(query, docs, topK = 4) {
  if (!docs || docs.length === 0) return [];
  
  // 第一步：尝试精确定位条款编号
  const articleMatch = query.match(/第([一二三四五六七八九十百千万]+)条|(\d{1,4})条/);
  let articleNum = null;
  
  if (articleMatch) {
    // 提取条款编号
    const cnNum = articleMatch[1];
    const digNum = articleMatch[2];
    articleNum = cnNum || digNum;
  }
  
  // 合并所有文档的块
  const allChunks = [];
  docs.forEach(doc => {
    if (doc.chunks) {
      doc.chunks.forEach(chunk => {
        allChunks.push({
          ...chunk,
          docName: doc.name
        });
      });
    }
  });
  
  if (allChunks.length === 0) return [];
  
  let results = [];
  
  // 策略1：如果找到条款号，先精确查找
  if (articleNum) {
    const exactMatches = allChunks.filter(chunk => 
      chunk.text.includes(`第${articleNum}条`) || 
      chunk.text.includes(`${articleNum}条`)
    );
    if (exactMatches.length > 0) {
      results = exactMatches.slice(0, topK).map(item => ({ ...item, score: 0 }));
    }
  }
  
  // 策略2：如果没有精确匹配或匹配数不足，使用模糊搜索补充
  if (results.length < topK) {
    const fuse = new Fuse(allChunks, {
      keys: ['text'],
      threshold: 0.3,  // 降低阈值，提高匹配率
      minMatchCharLength: 2,
      ignoreLocation: true,
      useExtendedSearch: true
    });
    
    const fuzzyResults = fuse.search(query, { limit: topK * 2 });
    const fuzzyChunks = fuzzyResults.map(r => r.item);
    
    // 合并结果，去重
    const seenIndexes = new Set(results.map(r => r.index + r.docName));
    for (const chunk of fuzzyChunks) {
      if (!seenIndexes.has(chunk.index + chunk.docName) && results.length < topK) {
        results.push(chunk);
      }
    }
  }
  
  return results.slice(0, topK);
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
  const [uploading, setUploading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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
        const content = await extractText(file);
        const sizeMB = (file.size / 1024 / 1024).toFixed(2);
        
        // 分块处理文档内容
        const chunks = chunkText(content, 600);
        
        setDocs(prev => [...prev.filter(d => d.name !== file.name), { 
          name: file.name, 
          content,
          chunks,
          sizeMB 
        }]);
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `📄 已加载《**${file.name}**》（${sizeMB} MB · ${content.length.toLocaleString()} 字符 · ${chunks.length} 个检索块）\n\n该文档已分块存储，后续回答将自动检索相关内容。`,
          timestamp: new Date(),
        }]);
      } catch (err) {
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `⚠️ 文档《${file.name}》加载失败：${err.message}`,
          timestamp: new Date(),
        }]);
      }
    }
    setUploading(false);
    e.target.value = "";
  };

  const buildSystemWithRAG = (retrievedChunks) => {
    let prompt = BASE_SYSTEM_PROMPT;
    
    if (retrievedChunks && retrievedChunks.length > 0) {
      const chunkTexts = retrievedChunks.map(c => `【${c.docName}】\n${c.text}`).join("\n\n───────\n\n");
      const docNames = [...new Set(retrievedChunks.map(c => c.docName))].join('、');
      prompt = `${BASE_SYSTEM_PROMPT}

⚠️ 【检索结果】根据用户问题，以下是相关的规程内容：

${chunkTexts}

【回答指示】
- 直接基于上述检索内容回答用户问题
- 引用具体的条文编号和原文内容
- 注明信息来源为〈${docNames}〉`;
    }
    
    return prompt;
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
    
    // RAG检索 - 从文档中查找相关内容
    const retrievedChunks = docs.length > 0 ? retrieveRelevantChunks(userText, docs, 4) : [];
    
    // 使用新的消息数组构建历史
    const history = messages.map(m => ({ role: m.role, content: m.content.replace(/\*\*/g, "") }));
    
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 90000);
      
      // 使用RAG检索结果构建系统消息
      const systemPrompt = buildSystemWithRAG(retrievedChunks);
      
      const res = await fetch(`${LONGCAT_BASE_URL}/v1/messages`, {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          "Authorization": `Bearer ${LONGCAT_API_KEY}`,
          "anthropic-version": "2023-06-01"
        },
        body: JSON.stringify({
          model: LONGCAT_MODEL,
          max_tokens: 4096,
          system: systemPrompt,
          messages: [...history, { role: "user", content: userText }]
        }),
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(`API错误 ${res.status}: ${err.error?.message || res.statusText}`);
      }
      
      const data = await res.json();
      let reply = "无响应";
      
      if (data.content && Array.isArray(data.content)) {
        const textBlock = data.content.find(b => b.type === "text" && b.text);
        if (textBlock) {
          reply = textBlock.text;
        }
      }
      
      setMessages(prev => [...prev, { role: "assistant", content: reply, timestamp: new Date() }]);
    } catch (error) {
      let msg = "连接错误";
      if (error.name === "AbortError") msg = "请求超时（90秒）";
      else msg = `错误: ${error.message}`;
      
      setMessages(prev => [...prev, { role: "assistant", content: msg, timestamp: new Date() }]);
    }
    setLoading(false);
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
                <button onClick={() => fileInputRef.current?.click()} disabled={uploading} style={{ width: "100%", padding: "0.5rem", background: "linear-gradient(135deg,rgba(74,222,128,0.15),rgba(34,211,238,0.1))", border: "1px dashed rgba(74,222,128,0.45)", borderRadius: "7px", color: uploading ? "#4ade8055" : "#4ade80", cursor: uploading ? "not-allowed" : "pointer", fontSize: "0.73rem", fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: "0.35rem" }}>
                  {uploading ? "⏳ 解析中..." : "＋ 上传规程文档"}
                </button>
                <div style={{ fontSize: "0.6rem", color: "#475569", textAlign: "center", marginTop: "0.3rem" }}>TXT · DOCX · PDF</div>
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
                      <div style={{ fontSize: "0.6rem", color: "#475569", marginTop: "0.12rem" }}>{doc.sizeMB} MB · {doc.content.length.toLocaleString()} 字符</div>
                    </div>
                    <button onClick={() => setDocs(prev => prev.filter(d => d.name !== doc.name))} style={{ background: "none", border: "none", color: "#475569", cursor: "pointer", fontSize: "0.85rem", flexShrink: 0, padding: 0, lineHeight: 1 }}>×</button>
                  </div>
                ))}
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
            {docs.length > 0 && (
              <div style={{ marginBottom: "0.45rem", padding: "0.3rem 0.7rem", background: "rgba(74,222,128,0.07)", border: "1px solid rgba(74,222,128,0.2)", borderRadius: "7px", fontSize: "0.65rem", color: "#4ade80", display: "flex", alignItems: "center", gap: "0.35rem" }}>
                📄 已加载 {docs.length} 份规程：{docs.map(d => d.name).join("、")}
              </div>
            )}
            <div style={{ display: "flex", gap: "0.6rem", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(74,222,128,0.25)", borderRadius: "13px", padding: "0.4rem 0.4rem 0.4rem 0.85rem", backdropFilter: "blur(20px)", boxShadow: "0 0 25px rgba(74,222,128,0.05)" }}>
              <button onClick={() => fileInputRef.current?.click()} title="上传规程文档" style={{ width: 34, height: 34, borderRadius: "7px", flexShrink: 0, alignSelf: "flex-end", background: "rgba(74,222,128,0.1)", border: "1px solid rgba(74,222,128,0.3)", color: "#4ade80", cursor: "pointer", fontSize: "0.95rem", display: "flex", alignItems: "center", justifyContent: "center" }}>📎</button>
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
