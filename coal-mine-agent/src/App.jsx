import { useState, useRef, useEffect } from "react";
import * as mammoth from "mammoth";

const LONGCAT_API_KEY = "ak_2ho0is8Y064o6Bd1UI80m0Ab1mL5n";
const LONGCAT_BASE_URL = "https://api.longcat.chat/anthropic";
const LONGCAT_MODEL = "LongCat-Flash-Thinking-2601";

const AGENT_SYSTEM_PROMPTS = {
  knowledge: {
    name: "知识图谱智能体",
    prompt: (docs) => `你是煤矿应急救援系统中的【知识图谱智能体】(🧠)。
你的职责是：快速检索和提取与用户问题相关的专业知识。

核心任务：
1. 从上传的规程文档中精准提取相关条例、规范、案例
2. 整理知识点的层级关系（法律→规程→具体操作）
3. 标注引用源（文档名+条款号）
4. 如无相关文档，调用领域基础知识

回答格式（务必遵循）：
📚 知识检索结果：
- 相关条款或规范（注明来源）
- 关键概念定义
- 历史案例引用

${docs.length > 0 ? `\n备注：用户上传了${docs.length}份规程文档，优先从中提取知识。` : ""}`,
  },
  
  perception: {
    name: "态势感知智能体",
    prompt: () => `你是煤矿应急救援系统中的【态势感知智能体】(📡)。
你的职责是：全面分析灾害场景的态势。

分析维度（必须覆盖）：
1. 【灾害类型】：识别具体灾害 + 触发原因
2. 【危害程度】：人数影响、区域范围、扩散速度（红/橙/黄/绿）
3. 【环境因素】：井深、通风系统、地质特征、逃生通道
4. 【资源评估】：现有人员、设备、物资的应对能力
5. 【时间压力】：黄金救援窗口（小时级/分钟级）

回答格式（务必遵循）：
📡 态势分析：
- 灾害分类：[类型] | 危害等级：[红/橙/黄/绿]
- 影响范围：[区域] | 指挥级别：[日常/重大/特别重大]
- 核心制约：[最紧迫的3个问题]`,
  },
  
  decision: {
    name: "决策推理智能体",
    prompt: () => `你是煤矿应急救援系统中的【决策推理智能体】(⚡)。
你的职责是：基于态势感知结果，生成科学的救援方案。

方案设计规则：
1. 优先级排序：立即救人 > 防止扩散 > 善后处理
2. 可操作性：每步都明确责任部门、时间窗口、资源需求
3. 备选方案：至少2个方案（主方案+备选）
4. 风险识别：每步的潜在二次风险

回答格式（务必遵循）：
⚡ 救援方案决策：
【主方案】
- 第1步（当下）：[行动] | 责任部门：[部门] | 时间窗口：[时间]
- 第2步：...
- 第3步：...

【备选方案】
- 如果[条件]则执行：[方案]

【风险提示】
- 需要警惕的二次灾害：[风险]`,
  },
  
  coordination: {
    name: "协同指挥智能体",
    prompt: () => `你是煤矿应急救援系统中的【协同指挥智能体】(🎯)。
你的职责是：整合各智能体的分析结果，给出完整的指挥协同方案。

协同内容（必须包含）：
1. 【指挥层级】：明确指挥官、副指挥、各专业组长
2. 【部门分工】：安全科、调度室、救援队、医疗组各自职责
3. 【信息流】：每5分钟汇报的关键指标
4. 【资源调配】：人员、装备、物资的调度优先级
5. 【应急预警】：如何及时升级/降级指挥等级

回答格式（务必遵循）：
🎯 协同指挥方案（5分钟内启动）：
│
├─ 现场指挥官：[职务名称] → 目标：[核心目标]
├─ 汇报链条：现场 → [中间级] → 矿长 → 政府部门
│
├─ 分工执行表：
│   ├─ 救援队（组长：___）：第1步___ → 第2步___ → 第3步___
│   ├─ 调度室（组长：___）：通风调整 → 人员清点 → 情报汇总
│   ├─ 医疗组（组长：___）：待机位置 → 伤员分类标准 → 转运路线
│   ├─ 安全科（组长：___）：全面停工 → 风险评估 → 撤离范围确定
│
├─ 5分钟汇报关键指标：[指标1]、[指标2]、[指标3]
│
└─ 升级条件：如果___ 则上升为___ 级指挥`,
  }
};

const BASE_SYSTEM_PROMPT = `你是一个专业的煤矿应急救援决策AI协同系统，基于中国矿业大学袁冠团队的研究成果构建。
系统由4个专业智能体组成，各自独立分析、协同输出。请严格按照各智能体的角色要求和回答格式进行响应。`;

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
  if (name.endsWith(".txt")) {
    return await file.text();
  }
  if (name.endsWith(".docx")) {
    const arrayBuffer = await file.arrayBuffer();
    const result = await mammoth.extractRawText({ arrayBuffer });
    return result.value;
  }
  if (name.endsWith(".pdf")) {
    return await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const bytes = new Uint8Array(e.target.result);
          let text = "";
          for (let i = 0; i < bytes.length; i++) {
            if (bytes[i] >= 32 && bytes[i] < 127) text += String.fromCharCode(bytes[i]);
            else if (bytes[i] === 10 || bytes[i] === 13) text += "\n";
          }
          const lines = text.split("\n")
            .map(l => l.trim())
            .filter(l => l.length > 5 && /[\u4e00-\u9fa5a-zA-Z]/.test(l));
          resolve(lines.join("\n") || "（PDF内容提取有限，建议转为TXT或DOCX格式上传）");
        } catch {
          resolve("（PDF解析失败，建议转为TXT或DOCX格式上传）");
        }
      };
      reader.readAsArrayBuffer(file);
    });
  }
  return "（不支持的文件格式，请上传 TXT、DOCX 或 PDF）";
}

function truncate(text, max = 5000) {
  if (text.length <= max) return text;
  return text.slice(0, max) + "\n...[文档内容较长，已截取前部分]";
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

  const handleUpload = async (e) => {
    const files = Array.from(e.target.files);
    if (!files.length) return;
    setUploading(true);
    for (const file of files) {
      try {
        const content = await extractText(file);
        const sizeMB = (file.size / 1024 / 1024).toFixed(2);
        setDocs(prev => [...prev.filter(d => d.name !== file.name), { name: file.name, content, sizeMB }]);
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `📄 已加载《**${file.name}**》（${sizeMB} MB · ${content.length.toLocaleString()} 字符）\n\n该文档已加入知识库，后续回答将优先参考此规程内容。`,
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

  const buildSystem = (agentId) => {
    if (agentId) {
      const agentConfig = AGENT_SYSTEM_PROMPTS[agentId];
      let docText = "";
      if (agentId === "knowledge" && docs.length > 0) {
        docText = docs.map(d => `【文档：${d.name}】\n${truncate(d.content, 3000)}`).join("\n\n---\n\n");
      }
      return `${agentConfig.prompt(docs)}\n${docText ? `\n\n=== 参考规程文档 ===\n${docText}` : ""}`;
    }
    if (!docs.length) return BASE_SYSTEM_PROMPT;
    const docText = docs.map(d => `【文档：${d.name}】\n${truncate(d.content)}`).join("\n\n---\n\n");
    return `${BASE_SYSTEM_PROMPT}\n\n===== 用户上传的参考规程文档（优先依据以下内容作答，并注明引用文档名）=====\n\n${docText}\n\n=====`;
  };

  const callAgent = async (agentId, userText, history) => {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 45000);
      
      const res = await fetch(`${LONGCAT_BASE_URL}/v1/messages`, {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          "Authorization": `Bearer ${LONGCAT_API_KEY}`,
          "anthropic-version": "2023-06-01"
        },
        body: JSON.stringify({
          model: LONGCAT_MODEL,
          max_tokens: 1024,
          system: buildSystem(agentId),
          messages: [...history, { role: "user", content: userText }]
        }),
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(`${res.status}: ${err.error?.message || res.statusText}`);
      }
      
      const data = await res.json();
      if (data.content && Array.isArray(data.content)) {
        const textBlock = data.content.find(b => b.type === "text" && b.text);
        if (textBlock) return textBlock.text;
      }
      return "无响应";
    } catch (error) {
      if (error.name === "AbortError") {
        return `智能体请求超时`;
      }
      return `错误: ${error.message}`;
    }
  };

  const sendMessage = async (text) => {
    const userText = text || input.trim();
    if (!userText || loading) return;
    const level = detectAlertLevel(userText);
    setAlertLevel(level);
    if (level) setTimeout(() => setAlertLevel(null), 5000);
    setMessages(prev => [...prev, { role: "user", content: userText, timestamp: new Date() }]);
    setInput("");
    setLoading(true);
    
    const history = messages.map(m => ({ role: m.role, content: m.content.replace(/\*\*/g, "") }));
    const isUrgent = level === "red"; // 紧急情况
    
    try {
      // 展示协同推理中的加载状态
      setMessages(prev => [...prev, { 
        role: "assistant", 
        content: `🤖 多智能体协同推理启动${isUrgent ? '（紧急模式）' : ''}...`,
        timestamp: new Date(),
        isThinking: true
      }]);
      
      let agentResults = {};
      const agentOrder = ["knowledge", "perception", "decision", "coordination"];
      
      if (isUrgent) {
        // 紧急情况：并行调用所有智能体
        setActiveAgents(agentOrder);
        const promises = agentOrder.map(agentId =>
          callAgent(agentId, userText, history).then(result => ({ agentId, result }))
        );
        const results = await Promise.all(promises);
        results.forEach(({ agentId, result }) => {
          agentResults[agentId] = result;
        });
      } else {
        // 普通情况：串行调用（成本低，逐步展示进度）
        for (const agentId of agentOrder) {
          setActiveAgents(prev => {
            if (!prev.includes(agentId)) return [...prev, agentId];
            return prev;
          });
          agentResults[agentId] = await callAgent(agentId, userText, history);
          await new Promise(resolve => setTimeout(resolve, 300)); // 视觉间隔
        }
      }
      
      // 移除加载提示
      setMessages(prev => prev.filter(m => !m.isThinking));
      
      // 构建最终协同输出
      const finalOutput = `🤖 **多智能体协同决策结果**

${agentResults["knowledge"] ? `## 📚 知识图谱智能体输出
${agentResults["knowledge"]}

` : ""}${agentResults["perception"] ? `## 📡 态势感知智能体输出
${agentResults["perception"]}

` : ""}${agentResults["decision"] ? `## ⚡ 决策推理智能体输出
${agentResults["decision"]}

` : ""}${agentResults["coordination"] ? `## 🎯 协同指挥智能体输出
${agentResults["coordination"]}

` : ""}---
⏱️ 协同耗时：${isUrgent ? '并行' : '串行'}执行 | 📊 智能体: ${agentOrder.join(' → ')}`;

      setMessages(prev => [...prev, { role: "assistant", content: finalOutput, timestamp: new Date() }]);
      setActiveAgents([]);
    } catch (error) {
      setMessages(prev => [...prev, { 
        role: "assistant", 
        content: `❌ 多智能体协同出错: ${error.message}`, 
        timestamp: new Date() 
      }]);
      setActiveAgents([]);
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
                <div style={{ maxWidth: "76%", background: msg.role === "user" ? "linear-gradient(135deg,#1d4ed8,#1e40af)" : "rgba(255,255,255,0.05)", border: msg.role === "user" ? "1px solid rgba(59,130,246,0.4)" : "1px solid rgba(74,222,128,0.15)", borderRadius: msg.role === "user" ? "14px 4px 14px 14px" : "4px 14px 14px 14px", padding: "0.75rem 0.95rem", fontSize: "0.85rem", lineHeight: "1.7", backdropFilter: "blur(10px)" }}>
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
                <div style={{ padding: "0.75rem 0.95rem", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(74,222,128,0.15)", borderRadius: "4px 14px 14px 14px", fontSize: "0.82rem", color: "#94a3b8", minWidth: "280px" }}>
                  <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>🤖 多智能体协同推理中...</div>
                  <div style={{ fontSize: "0.75rem", lineHeight: "1.8" }}>
                    {AGENTS.map(a => (
                      <div key={a.id} style={{ display: "flex", alignItems: "center", gap: "0.4rem", color: activeAgents.includes(a.id) ? a.color : "#475569", transition: "all 0.3s" }}>
                        <span style={{ width: 8, height: 8, borderRadius: "50%", background: activeAgents.includes(a.id) ? a.color : "#374151", animation: activeAgents.includes(a.id) ? "pulse 1s infinite" : "none", flexShrink: 0 }} />
                        <span>{a.icon} {a.name}</span>
                        {activeAgents.includes(a.id) && <span style={{ fontSize: "0.65rem", color: a.color }}>处理中</span>}
                      </div>
                    ))}
                  </div>
                  {docs.length > 0 && <div style={{ fontSize: "0.63rem", color: "#4ade80", marginTop: "0.3rem", paddingTop: "0.3rem", borderTop: "1px solid rgba(74,222,128,0.2)" }}>📄 检索 {docs.length} 份规程 | 知识库激活</div>}
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
