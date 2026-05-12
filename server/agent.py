"""
LangChain多智能体协同定义（兼容OpenAI协议网关）
"""
from concurrent.futures import ThreadPoolExecutor
import json
from typing import Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import config
from knowledge_graph import build_knowledge_graph, summarize_related_graph
from risk_fusion import build_risk_profile

# 进程内会话记忆，按 session_id 隔离
_SESSION_CHAT_HISTORY: Dict[str, List[Dict[str, str]]] = {}
_MAX_HISTORY_MESSAGES = config.AGENT_MAX_HISTORY_MESSAGES
_DEFAULT_SESSION_ID = "default"

def _build_llm(temperature: float, max_tokens: int, timeout: int) -> ChatOpenAI:
    return ChatOpenAI(
        api_key=config.require_longcat_api_key(),
        base_url=config.LONGCAT_BASE_URL,
        model=config.LONGCAT_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )


def _get_llm() -> ChatOpenAI:
    return _build_llm(
        temperature=0.2,
        max_tokens=config.LONGCAT_MAX_TOKENS,
        timeout=config.LONGCAT_READ_TIMEOUT,
    )


def _get_router_llm() -> ChatOpenAI:
    return _build_llm(
        temperature=0,
        max_tokens=96,
        timeout=max(8, min(15, config.LONGCAT_READ_TIMEOUT)),
    )

_ROLE_CONTEXT_LIMIT = 1400
_SHORT_RETRY_LIMIT = 700


def _normalize_content(content) -> str:
    """将模型返回内容统一为纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return "\n".join(parts).strip() or "无响应"
    return str(content)


def _run_role(role_name: str, role_prompt: str, user_query: str) -> str:
    """执行单个角色智能体。"""
    try:
        messages = [
            SystemMessage(content=role_prompt),
            HumanMessage(content=user_query),
        ]
        result = _get_llm().invoke(messages)
        return _normalize_content(result.content)
    except Exception as e:
        raise RuntimeError(f"{role_name}智能体调用失败：{str(e)}") from e


def _is_timeout_error_msg(msg: str) -> bool:
    """判断错误信息是否属于超时类错误。"""
    text = (msg or "").lower()
    return "timed out" in text or "timeout" in text or "超时" in text


def _clip_text(text: str, max_len: int) -> str:
    """截断长文本，避免单次角色调用输入过大导致超时。"""
    text = str(text or "")
    if len(text) <= max_len:
        return text
    head = max_len // 2
    tail = max_len - head
    return f"{text[:head]}\n...(中间已省略)...\n{text[-tail:]}"


def _build_fallback_role_output(
    role_name: str,
    risk_profile: Dict[str, object],
    documents: List[Dict[str, object]],
    images: List[Dict[str, str]],
    graph_used: Dict[str, object],
) -> str:
    risk_level = str(risk_profile.get("risk_level") or "未知")
    risk_labels = list(risk_profile.get("risk_type_labels") or [])
    actions = list(risk_profile.get("recommended_actions_seed") or [])
    matched_relations = list(graph_used.get("matched_relations") or [])
    relation_text = "；".join(
        f"{item.get('head_label')}→{item.get('tail_label')}" for item in matched_relations[:3]
    ) or "无明确图谱关系"
    fallback_prefix = "说明：模型调用失败，已切换规则化兜底。"

    if role_name == "perception":
        threats = "、".join(risk_labels[:3]) or "需结合现场复核的复合风险"
        immediate_actions = "、".join(actions[:3] or ["停止作业", "组织撤离", "上报调度"])
        return (
            f"{fallback_prefix}\n"
            f"风险等级：{risk_level}\n"
            f"主要威胁：{threats}\n"
            f"立即动作：{immediate_actions}"
        )

    if role_name == "knowledge":
        if documents:
            first_doc = documents[0]
            return (
                f"{fallback_prefix}\n"
                f"相关依据：已上传文档《{first_doc.get('doc_name', '未命名文档')}》片段 {first_doc.get('chunk_id', '未知')}。\n"
                f"关键参数：{_clip_text(str(first_doc.get('text', '')), 180)}\n"
                f"注意事项：结合图谱关系 {relation_text} 进行复核。"
            )
        return (
            f"{fallback_prefix}\n"
            "通用原则：出现高风险信号时应立即停止危险作业、组织撤人、控制能量源并上报调度。\n"
            f"关键参数：当前识别风险等级为{risk_level}。\n"
            "复核提醒：需结合本矿规程复核。"
        )

    if role_name == "decision":
        immediate = actions[:3] or ["停止作业", "撤离人员", "加强通风"]
        follow_up = actions[3:6] or ["设置警戒", "持续监测", "组织复核"]
        return (
            f"{fallback_prefix}\n"
            f"0-10分钟动作：1. {'；2. '.join(immediate)}。\n"
            f"10-30分钟动作：1. {'；2. '.join(follow_up)}。\n"
            "责任分工：现场班组负责撤人与警戒，调度室负责上报与协调，专业部门负责复测和技术处置。"
        )

    return (
        f"{fallback_prefix}\n"
        "调度流程：现场先控险并上报，调度室统一通知通防、机电、安全与救援力量。\n"
        "通信机制：保持对讲机、电话和广播同步，每5分钟回报一次进展。\n"
        "升级触发条件：风险持续升高、出现人员伤害、现场失联或常规处置无效时立即升级。"
    )


def _normalize_history(history: Optional[List[dict]]) -> List[Dict[str, str]]:
    if not isinstance(history, list):
        return []

    normalized: List[Dict[str, str]] = []
    max_messages = max(2, min(_MAX_HISTORY_MESSAGES, config.AGENT_MAX_HISTORY_TURNS * 2))
    for item in history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append({
            "role": role,
            "content": _clip_text(content, 500),
        })

    return normalized[-max_messages:]


def _normalize_document_evidence(documents: Optional[List[dict]]) -> List[Dict[str, object]]:
    if not isinstance(documents, list):
        return []

    normalized: List[Dict[str, object]] = []
    for idx, item in enumerate(documents[:config.AGENT_MAX_EVIDENCE_DOCUMENTS]):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        doc_name = str(item.get("doc_name") or item.get("docName") or "未命名文档").strip() or "未命名文档"
        chunk_id = str(item.get("chunk_id") or item.get("chunkId") or f"{doc_name}:{idx}").strip()
        score = item.get("score")
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            score = None
        normalized.append({
            "doc_name": doc_name,
            "chunk_id": chunk_id,
            "score": score,
            "text": _clip_text(text, 900),
            "source_type": str(item.get("source_type") or "uploaded_doc"),
        })
    return normalized


def _normalize_image_evidence(images: Optional[List[dict]]) -> List[Dict[str, str]]:
    if not isinstance(images, list):
        return []

    normalized: List[Dict[str, str]] = []
    for item in images[:config.AGENT_MAX_EVIDENCE_IMAGES]:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary", "")).strip()
        if not summary:
            continue
        normalized.append({
            "image_name": str(item.get("image_name") or item.get("imageName") or "未命名图片").strip() or "未命名图片",
            "summary": _clip_text(summary, 300),
            "source_type": str(item.get("source_type") or "image_analysis"),
        })
    return normalized


def _get_session_id(session_id: Optional[str]) -> str:
    sid = str(session_id or "").strip()
    return sid or _DEFAULT_SESSION_ID


def _get_session_history(session_id: Optional[str]) -> List[Dict[str, str]]:
    return list(_SESSION_CHAT_HISTORY.get(_get_session_id(session_id), []))


def _save_session_history(session_id: Optional[str], history: List[Dict[str, str]]) -> None:
    sid = _get_session_id(session_id)
    trimmed = _normalize_history(history)
    _SESSION_CHAT_HISTORY[sid] = trimmed[-_MAX_HISTORY_MESSAGES:]


def _append_session_turn(session_id: Optional[str], user_query: str, reply: str) -> List[Dict[str, str]]:
    history = _get_session_history(session_id)
    history.extend([
        {"role": "user", "content": _clip_text(user_query, 500)},
        {"role": "assistant", "content": _clip_text(reply, 500)},
    ])
    _save_session_history(session_id, history)
    return _get_session_history(session_id)


def _limit_history_chars(history: List[Dict[str, str]], max_chars: int) -> List[Dict[str, str]]:
    selected: List[Dict[str, str]] = []
    total = 0
    for item in reversed(history):
        content = str(item.get("content", ""))
        if total + len(content) > max_chars and selected:
            break
        selected.append(item)
        total += len(content)
    return list(reversed(selected))


def _format_history_for_prompt(history: List[Dict[str, str]]) -> str:
    if not history:
        return "无历史会话。"
    lines = []
    for item in history:
        prefix = "用户" if item.get("role") == "user" else "助手"
        lines.append(f"{prefix}: {item.get('content', '')}")
    return "\n".join(lines)


def _format_document_evidence_for_prompt(documents: List[Dict[str, object]]) -> str:
    if not documents:
        return "无文档证据。"

    blocks = []
    used_chars = 0
    for doc in documents:
        score = doc.get("score")
        score_text = f"；相似度分数={score:.3f}" if isinstance(score, float) else ""
        block = (
            f"来源文档：{doc.get('doc_name', '未命名文档')}\n"
            f"片段编号：{doc.get('chunk_id', '未知')}\n"
            f"内容：{doc.get('text', '')}{score_text}"
        )
        if used_chars + len(block) > config.AGENT_MAX_EVIDENCE_DOCUMENT_CHARS and blocks:
            break
        blocks.append(block)
        used_chars += len(block)
    return "\n\n----\n\n".join(blocks) if blocks else "无文档证据。"


def _format_image_evidence_for_prompt(images: List[Dict[str, str]]) -> str:
    if not images:
        return "无图片证据。"
    return "\n".join(
        f"图片：{item.get('image_name', '未命名图片')}；识别摘要：{item.get('summary', '')}"
        for item in images
    )


def _format_sensor_evidence_for_prompt(sensors: List[Dict[str, object]]) -> str:
    if not sensors:
        return "无传感器数据。"
    lines = []
    for item in sensors:
        value = item.get("value_text") if item.get("value_text") not in {None, ""} else item.get("value")
        lines.append(
            "；".join([
                f"传感器：{item.get('name', item.get('sensor_id', '未知传感器'))}",
                f"编号：{item.get('sensor_id', '未知')}",
                f"值：{value if value not in {None, ''} else '未知'}{item.get('unit', '')}",
                f"阈值：{item.get('threshold') if item.get('threshold') not in {None, ''} else '未知'}",
                f"位置：{item.get('location') or '未知'}",
                f"状态：{item.get('status') or '未知'}",
            ])
        )
    return "\n".join(lines)


def _format_graph_summary_for_prompt(graph_summary: str) -> str:
    return graph_summary or "无图谱命中。"


def _format_risk_profile_for_prompt(risk_profile: Dict[str, object]) -> str:
    return str(risk_profile.get("summary") or "未识别风险画像。")


def _build_shared_context(
    query: str,
    history: List[Dict[str, str]],
    documents: List[Dict[str, object]],
    images: List[Dict[str, str]],
    sensors: Optional[List[Dict[str, object]]] = None,
    risk_profile: Optional[Dict[str, object]] = None,
    graph_summary: str = "",
) -> str:
    limited_history = _limit_history_chars(history, config.AGENT_MAX_HISTORY_CHARS)
    history_text = _format_history_for_prompt(limited_history)
    doc_text = _format_document_evidence_for_prompt(documents)
    image_text = _format_image_evidence_for_prompt(images)
    sensor_text = _format_sensor_evidence_for_prompt(sensors or [])
    risk_text = _format_risk_profile_for_prompt(risk_profile or {})
    kg_text = _format_graph_summary_for_prompt(graph_summary)
    return (
        f"当前问题：\n{query.strip()}\n\n"
        f"对话上下文（仅用于承接语义与场景）：\n{history_text}\n\n"
        f"文档证据（优先依据这些片段作答，并尽量引用来源）：\n{doc_text}\n\n"
        f"图片证据（作为现场补充观察）：\n{image_text}\n\n"
        f"传感器数据（作为实时监测补充）：\n{sensor_text}\n\n"
        f"多源风险识别结果：\n{risk_text}\n\n"
        f"知识图谱摘要：\n{kg_text}"
    )


def _route_agents_by_rules(query: str) -> List[str]:
    """规则路由（仅用于模型路由失败时的后备）。"""
    q = query.strip()

    regulation_keywords = ["规程", "条", "条款", "依据", "规定", "要求", "是什么", "哪些"]
    emergency_keywords = ["火灾", "爆炸", "突水", "瓦斯", "透水", "被困", "事故", "险情"]
    decision_keywords = ["怎么办", "如何", "处置", "决策", "方案", "步骤", "流程"]
    coordination_keywords = ["协同", "调度", "指挥", "联动", "部门", "协调"]

    selected: List[str] = []

    if any(k in q for k in regulation_keywords):
        selected.append("knowledge")

    if any(k in q for k in emergency_keywords):
        selected.append("perception")

    if any(k in q for k in decision_keywords):
        selected.append("decision")

    if any(k in q for k in coordination_keywords):
        selected.append("coordination")

    if not selected:
        selected = ["knowledge", "decision"]

    ordered = [role for role in ["perception", "knowledge", "decision", "coordination"] if role in selected]
    return ordered


def _sanitize_selected_agents(agents: List[str]) -> List[str]:
    """清洗路由结果并按固定顺序输出。"""
    allow = {"perception", "knowledge", "decision", "coordination"}
    selected = [a for a in agents if a in allow]
    if not selected:
        selected = ["knowledge", "decision"]
    return [a for a in ["perception", "knowledge", "decision", "coordination"] if a in selected]


def _apply_route_guard(query: str, selected_agents: List[str]) -> List[str]:
    """路由守门：去掉明显不必要的高耗时角色，降低超时率。"""
    q = query.strip()
    coordination_keywords = ["协同", "调度", "联动", "指挥", "部门", "上报"]
    step_keywords = ["步骤", "流程", "怎么办", "如何", "处置"]
    regulation_keywords = ["规程", "条", "条款", "依据", "规定", "要求"]
    perception_need_keywords = ["风险", "预警", "识别", "研判", "态势", "超限", "烟雾"]

    guarded = list(selected_agents)
    if "coordination" in guarded and not any(k in q for k in coordination_keywords):
        guarded.remove("coordination")

    if "decision" in guarded and any(k in q for k in step_keywords):
        if "knowledge" in guarded and not any(k in q for k in regulation_keywords):
            guarded.remove("knowledge")
        if "perception" in guarded and not any(k in q for k in perception_need_keywords):
            guarded.remove("perception")

    if not guarded:
        guarded = ["knowledge", "decision"]

    return [a for a in ["perception", "knowledge", "decision", "coordination"] if a in guarded]


def _route_agents(
    query: str,
    has_doc_evidence: bool = False,
    has_image_evidence: bool = False,
    risk_profile: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """轻量路由模型：仅一次小调用，返回需要执行的子智能体。"""
    risk_profile = risk_profile or {}
    router_prompt = (
        "你是多智能体路由器。请根据用户问题，仅返回JSON，不要输出其他文字。"
        "JSON格式: {\"selected_agents\":[...],\"reason\":\"...\"}。"
        "selected_agents 只允许从 perception, knowledge, decision, coordination 中选择。"
        "路由原则: 法规/条款问答优先 knowledge；风险识别含灾害征兆优先 perception；"
        "处置步骤类问题加 decision；跨部门联动/调度类问题加 coordination。"
        "若提供了文档证据，应优先保留 knowledge；若提供了图片证据，应优先保留 perception。"
        "若多源风险识别为高/极高，应优先保留 perception；若推荐动作明确，应保留 decision。"
        "若不确定，返回 [\"knowledge\",\"decision\"]。"
    )
    routed_query = query.strip()
    if risk_profile.get("enabled"):
        routed_query = f"{routed_query}\n\n风险识别摘要：{risk_profile.get('summary', '')}"
    try:
        messages = [
            SystemMessage(content=router_prompt),
            HumanMessage(content=routed_query),
        ]
        resp = _get_router_llm().invoke(messages)
        text = _normalize_content(resp.content)
        data = json.loads(text)
        selected = _sanitize_selected_agents(data.get("selected_agents", []))
        if has_doc_evidence and "knowledge" not in selected:
            selected.append("knowledge")
        if has_image_evidence and "perception" not in selected:
            selected.append("perception")
        for role in risk_profile.get("recommended_agents", []):
            if role not in selected:
                selected.append(role)
        selected = _sanitize_selected_agents(selected)
        selected = _apply_route_guard(routed_query, selected)
        reason = str(data.get("reason", "模型路由"))
        return {
            "selected_agents": selected,
            "route_reason": reason,
            "route_mode": "llm-router",
        }
    except Exception:
        selected = _route_agents_by_rules(routed_query)
        if has_doc_evidence and "knowledge" not in selected:
            selected.append("knowledge")
        if has_image_evidence and "perception" not in selected:
            selected.append("perception")
        for role in risk_profile.get("recommended_agents", []):
            if role not in selected:
                selected.append(role)
        selected = _sanitize_selected_agents(selected)
        selected = _apply_route_guard(routed_query, selected)
        return {
            "selected_agents": selected,
            "route_reason": "模型路由失败，已回退到规则路由",
            "route_mode": "rule-fallback",
        }


def _compose_final_reply(user_query: str, agents: Dict[str, str], selected_agents: List[str]) -> str:
    """总控聚合器：仅融合本次被路由选中的智能体结果。"""
    title_map = {
        "perception": "态势感知",
        "knowledge": "知识检索",
        "decision": "决策推理",
        "coordination": "协同指挥",
    }
    lines = [f"问题：{user_query}", "", "【多智能体协同结论】"]
    for idx, role in enumerate(selected_agents, start=1):
        lines.append(f"{idx}. {title_map.get(role, role)}")
        lines.append(str(agents.get(role, "无结果")))
        lines.append("")
    lines.extend([
        "【执行建议】",
        "- 先执行本次已选智能体结论中的立即动作。",
        "- 若现场风险上升，补充调用未选中的智能体进行二次研判。",
    ])
    return "\n".join(lines)


def multi_agent_ask(
    query: str,
    session_id: Optional[str] = None,
    history: Optional[List[dict]] = None,
    evidence_documents: Optional[List[dict]] = None,
    evidence_images: Optional[List[dict]] = None,
    evidence_sensors: Optional[List[dict]] = None,
    options: Optional[dict] = None,
) -> Dict[str, object]:
    """执行多智能体协同流程并返回聚合结果。"""
    if not query or not query.strip():
        return {
            "reply": "请输入有效问题。",
            "agents": {},
        }

    options = options or {}
    user_query = query.strip()
    normalized_documents = _normalize_document_evidence(evidence_documents)
    normalized_images = _normalize_image_evidence(evidence_images)
    normalized_sensors = evidence_sensors if isinstance(evidence_sensors, list) else []

    use_session_memory = options.get("use_session_memory", True)
    provided_history = _normalize_history(history)
    session_history = _get_session_history(session_id) if use_session_memory else []
    if use_session_memory:
        effective_history = provided_history or session_history
    else:
        effective_history = provided_history
    effective_history = _limit_history_chars(effective_history, config.AGENT_MAX_HISTORY_CHARS)

    risk_profile = build_risk_profile(
        user_query,
        effective_history,
        normalized_documents,
        normalized_images,
        normalized_sensors,
    )
    graph = build_knowledge_graph(normalized_documents)
    graph_summary, graph_used = summarize_related_graph(
        user_query,
        graph,
        risk_types=list(risk_profile.get("risk_types", [])),
    )

    shared_context = _build_shared_context(
        user_query,
        effective_history,
        normalized_documents,
        normalized_images,
        normalized_sensors,
        risk_profile=risk_profile,
        graph_summary=graph_summary,
    )

    perception_prompt = (
        "你是态势感知智能体。任务：结合多源风险识别结果、图片证据和历史上下文，识别风险等级、事故类型、关键威胁、第一响应窗口。"
        "输出简洁结构：风险等级、主要威胁、立即动作。"
        "优先承接共享上下文中的风险画像，不要忽略高危信号。"
    )
    if normalized_documents:
        knowledge_prompt = (
            "你是知识检索智能体。任务：严格基于用户上传的文档证据和知识图谱摘要给出可依据的规程要点与术语解释。"
            "输出简洁结构：相关依据、关键参数、注意事项。"
            "只允许引用当前提供的文档片段、条款号和来源名称，不要补充未提供来源的具体条款。"
            "如果文档证据不足以支持某个判断，就明确写“需结合本矿规程复核”。"
        )
    else:
        knowledge_prompt = (
            "你是知识检索智能体。任务：在没有上传规程文档时，只能提供通用安全处置原则、知识图谱中抽象出的关系提示与术语解释。"
            "输出简洁结构：通用原则、关键参数、复核提醒。"
            "禁止编造或假设具体法规名称、条款编号、条文原文和来源。"
            "必须明确提示“需结合本矿规程复核”，不得写成“第X条”“依据某规程”等具体条款表达。"
        )
    if normalized_documents:
        decision_prompt = (
            "你是决策推理智能体。任务：将风险画像、知识依据和知识图谱关系转为可执行行动计划。"
            "输出简洁结构：0-10分钟动作、10-30分钟动作、责任分工。"
            "若共享上下文包含具体条款，只能基于已给文档片段表达；若证据不足，明确提示需结合本矿规程复核。"
            "要承接历史场景，不要把本轮问题当成孤立输入。"
        )
        coordination_prompt = (
            "你是协同指挥智能体。任务：给出跨部门协同与通信机制。"
            "输出简洁结构：调度流程、通信机制、升级触发条件。"
            "若共享上下文包含具体规程依据，只能使用已给证据；不得补造额外条款来源。"
            "需要结合已有决策结论和上下文中的责任部门关系。"
        )
    else:
        decision_prompt = (
            "你是决策推理智能体。任务：将风险画像和通用安全原则转为可执行行动计划。"
            "输出简洁结构：0-10分钟动作、10-30分钟动作、责任分工。"
            "禁止编造具体规程条款或来源，必须明确提示“需结合本矿规程复核”。"
            "要承接历史场景，不要把本轮问题当成孤立输入。"
        )
        coordination_prompt = (
            "你是协同指挥智能体。任务：给出跨部门协同与通信机制。"
            "输出简洁结构：调度流程、通信机制、升级触发条件。"
            "禁止编造具体规程条款或来源，必须明确提示“需结合本矿规程复核”。"
            "需要结合已有决策结论和上下文中的责任部门关系。"
        )

    route = _route_agents(
        shared_context,
        has_doc_evidence=bool(normalized_documents),
        has_image_evidence=bool(normalized_images),
        risk_profile=risk_profile,
    )
    selected_agents = route["selected_agents"]
    agents: Dict[str, str] = {}

    stage1_roles = [r for r in ["perception", "knowledge"] if r in selected_agents]
    stage1_prompts = {
        "perception": perception_prompt,
        "knowledge": knowledge_prompt,
    }
    if stage1_roles:
        with ThreadPoolExecutor(max_workers=len(stage1_roles)) as executor:
            futures = {
                role: executor.submit(_run_role, role, stage1_prompts[role], shared_context)
                for role in stage1_roles
            }
            for role, fut in futures.items():
                try:
                    agents[role] = fut.result()
                except RuntimeError as e:
                    if _is_timeout_error_msg(str(e)):
                        short_stage1_input = (
                            f"当前问题：{_clip_text(user_query, _SHORT_RETRY_LIMIT)}\n"
                            f"历史上下文：{_clip_text(_format_history_for_prompt(effective_history), 400)}\n"
                            f"文档证据：{_clip_text(_format_document_evidence_for_prompt(normalized_documents), 500)}\n"
                            f"图片证据：{_clip_text(_format_image_evidence_for_prompt(normalized_images), 200)}\n"
                            f"传感器数据：{_clip_text(_format_sensor_evidence_for_prompt(normalized_sensors), 260)}\n"
                            f"风险画像：{_clip_text(_format_risk_profile_for_prompt(risk_profile), 250)}\n"
                            f"图谱摘要：{_clip_text(graph_summary, 250)}\n"
                            "请用不超过5条给出关键结论。"
                        )
                        try:
                            agents[role] = _run_role(role, stage1_prompts[role], short_stage1_input)
                        except RuntimeError as e2:
                            if _is_timeout_error_msg(str(e2)):
                                agents[role] = _build_fallback_role_output(role, risk_profile, normalized_documents, normalized_images, graph_used)
                            else:
                                agents[role] = _build_fallback_role_output(role, risk_profile, normalized_documents, normalized_images, graph_used)
                    else:
                        agents[role] = _build_fallback_role_output(role, risk_profile, normalized_documents, normalized_images, graph_used)

    perception = agents.get("perception", "未调用")
    knowledge = agents.get("knowledge", "未调用")

    compact_context = _clip_text(shared_context, _ROLE_CONTEXT_LIMIT)
    compact_perception = _clip_text(perception, _ROLE_CONTEXT_LIMIT)
    compact_knowledge = _clip_text(knowledge, _ROLE_CONTEXT_LIMIT)
    compact_risk = _clip_text(risk_profile.get("summary", ""), _ROLE_CONTEXT_LIMIT)
    compact_graph = _clip_text(graph_summary, _ROLE_CONTEXT_LIMIT)
    compact_sensor = _clip_text(_format_sensor_evidence_for_prompt(normalized_sensors), _ROLE_CONTEXT_LIMIT)

    decision_input = (
        f"共享上下文：\n{compact_context}\n\n"
        f"多源风险画像：\n{compact_risk}\n\n"
        f"传感器数据：\n{compact_sensor}\n\n"
        f"知识图谱摘要：\n{compact_graph}\n\n"
        f"态势感知结论：\n{compact_perception}\n\n"
        f"知识依据结论：\n{compact_knowledge}"
    )
    if "decision" in selected_agents:
        try:
            agents["decision"] = _run_role("decision", decision_prompt, decision_input)
        except RuntimeError as e:
            if _is_timeout_error_msg(str(e)):
                short_decision_input = (
                    f"当前问题：{_clip_text(user_query, _SHORT_RETRY_LIMIT)}\n"
                    f"历史上下文：{_clip_text(_format_history_for_prompt(effective_history), 300)}\n"
                    f"文档证据：{_clip_text(_format_document_evidence_for_prompt(normalized_documents), 400)}\n"
                    f"传感器数据：{_clip_text(_format_sensor_evidence_for_prompt(normalized_sensors), 260)}\n"
                    f"风险画像：{_clip_text(_format_risk_profile_for_prompt(risk_profile), 250)}\n"
                    f"图谱摘要：{_clip_text(graph_summary, 250)}\n"
                    "请用5条以内给出紧急处置步骤与责任分工。"
                )
                try:
                    agents["decision"] = _run_role("decision", decision_prompt, short_decision_input)
                except RuntimeError:
                    agents["decision"] = _build_fallback_role_output("decision", risk_profile, normalized_documents, normalized_images, graph_used)
            else:
                agents["decision"] = _build_fallback_role_output("decision", risk_profile, normalized_documents, normalized_images, graph_used)

    if "coordination" in selected_agents:
        decision_for_coord = agents.get("decision", "未调用")
        coordination_input = (
            f"共享上下文：\n{compact_context}\n\n"
            f"多源风险画像：\n{compact_risk}\n\n"
            f"传感器数据：\n{compact_sensor}\n\n"
            f"知识图谱摘要：\n{compact_graph}\n\n"
            f"态势感知结论：\n{compact_perception}\n\n"
            f"知识依据结论：\n{compact_knowledge}\n\n"
            f"决策结论：\n{_clip_text(decision_for_coord, _ROLE_CONTEXT_LIMIT)}"
        )
        try:
            agents["coordination"] = _run_role("coordination", coordination_prompt, coordination_input)
        except RuntimeError as e:
            if _is_timeout_error_msg(str(e)):
                short_coord_input = (
                    f"当前问题：{_clip_text(user_query, _SHORT_RETRY_LIMIT)}\n"
                    f"历史上下文：{_clip_text(_format_history_for_prompt(effective_history), 300)}\n"
                    f"传感器数据：{_clip_text(_format_sensor_evidence_for_prompt(normalized_sensors), 260)}\n"
                    f"风险画像：{_clip_text(_format_risk_profile_for_prompt(risk_profile), 250)}\n"
                    f"图谱摘要：{_clip_text(graph_summary, 250)}\n"
                    "请给出跨部门协同调度流程、通信机制、升级条件，控制在6条内。"
                )
                try:
                    agents["coordination"] = _run_role("coordination", coordination_prompt, short_coord_input)
                except RuntimeError:
                    agents["coordination"] = _build_fallback_role_output("coordination", risk_profile, normalized_documents, normalized_images, graph_used)
            else:
                agents["coordination"] = _build_fallback_role_output("coordination", risk_profile, normalized_documents, normalized_images, graph_used)

    reply = _compose_final_reply(user_query, agents, selected_agents)
    final_history = _append_session_turn(session_id, user_query, reply) if use_session_memory else effective_history

    return {
        "reply": reply,
        "agents": agents,
        "selected_agents": selected_agents,
        "route_mode": route["route_mode"],
        "route_reason": route["route_reason"],
        "session_id": _get_session_id(session_id),
        "memory_used": {
            "history_messages": len(effective_history),
            "history_chars": sum(len(item.get("content", "")) for item in effective_history),
            "session_history_messages": len(final_history),
        },
        "evidence_used": {
            "documents": [
                {"doc_name": item.get("doc_name"), "chunk_id": item.get("chunk_id")}
                for item in normalized_documents
            ],
            "images": [
                {
                    "image_name": item.get("image_name"),
                    "summary": item.get("summary"),
                    "source_type": item.get("source_type"),
                }
                for item in normalized_images
            ],
            "sensors": [
                {
                    "sensor_id": item.get("sensor_id"),
                    "name": item.get("name"),
                    "value": item.get("value"),
                    "value_text": item.get("value_text"),
                    "unit": item.get("unit"),
                    "threshold": item.get("threshold"),
                    "location": item.get("location"),
                    "status": item.get("status"),
                }
                for item in normalized_sensors
            ],
        },
        "risk_assessment": risk_profile,
        "kg_used": graph_used,
        "source_fusion": {
            "history_used": bool(effective_history),
            "document_count": len(normalized_documents),
            "image_count": len(normalized_images),
            "sensor_count": len(normalized_sensors),
        },
    }


def agent_ask(query: str) -> str:
    """兼容旧调用方式，仅返回最终答复文本。"""
    result = multi_agent_ask(query=query)
    return str(result.get("reply", "无响应"))
