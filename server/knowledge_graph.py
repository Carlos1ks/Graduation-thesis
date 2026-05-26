"""LLM triple extraction -> Neo4j graph storage and query helpers."""
# 知识图谱层。
# 主要职责有四个：
# 1. 从规程文本里抽取轻量三元组；
# 2. 把三元组标准化并合并成会话级图谱；
# 3. 在 Neo4j 中存储和查询图谱；
# 4. 为检索和问答提供图谱摘要证据。
from __future__ import annotations

import json
import re
import time
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Dict, List, Optional, Tuple

from neo4j import GraphDatabase
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import config
from domain_schema import RELATION_LABELS


_DEFAULT_SESSION_ID = "default"
_DRIVER = None
_DRIVER_LOCK = RLock()
_TASK_LOCK = RLock()
_BUILD_EXECUTOR = ThreadPoolExecutor(max_workers=1)
_GRAPH_BUILD_STATUS: Dict[str, Dict[str, object]] = {}
# 图谱构建进度按会话维护，方便前端轮询显示状态。
_GRAPH_BUILD_FUTURES: Dict[str, Future] = {}
_STATUS_DIR = Path(__file__).resolve().parent / ".graph_status"
_ARTICLE_SPLIT_PATTERN = re.compile(r"(?=第[一二三四五六七八九十百千万零两\d]+条(?:\s|$))")
_ARTICLE_LABEL_PATTERN = re.compile(r"第[一二三四五六七八九十百千万零两\d]+条")
_GRAPH_QUERY_CACHE: Dict[str, Tuple[float, Dict[str, object]]] = {}
_GRAPH_QUERY_CACHE_LOCK = RLock()
_GRAPH_QUERY_CACHE_TTL_SECONDS = 600
_GRAPH_QUERY_CACHE_MAX_ITEMS = 256
_NO_ARTICLE_LIMIT = 0

_VISIBLE_NODE_TYPES = {
    "hazard",
    "condition",
    "step",
    "role",
    "equipment",
    "risk",
}

_TOPIC_RULES = {
    "gas": {"tokens": ["瓦斯", "甲烷", "超限", "瓦斯浓度"]},
    "water": {"tokens": ["透水", "突水", "水害", "涌水", "水位"]},
    "fire": {"tokens": ["火灾", "明火", "火源", "烟雾", "燃烧"]},
}

NODE_TYPE_LABELS = {
    "regulation": "规程",
    "chapter": "编章",
    "article": "条文",
    "hazard": "灾害类型",
    "step": "处置步骤",
    "condition": "条件约束",
    "equipment": "设备设施",
    "role": "责任主体",
    "risk": "风险点",
}

NEO4J_LABELS = {
    "regulation": "Regulation",
    "chapter": "Chapter",
    "article": "Article",
    "hazard": "Hazard",
    "step": "Step",
    "condition": "Condition",
    "equipment": "Equipment",
    "role": "Role",
    "risk": "Risk",
}

ALLOWED_NODE_TYPES = set(NEO4J_LABELS.keys())
ALLOWED_RELATIONS = {
    "CONTAINS",
    "NEXT",
    "APPLIES_TO",
    "REQUIRES",
    "PERFORMED_BY",
    "HAS_RISK",
    "IF",
    "MENTIONS",
}

RELATION_LABEL_OVERRIDES = {
    "CONTAINS": "包含",
    "NEXT": "下一步",
    "APPLIES_TO": "适用于",
    "REQUIRES": "需要",
    "PERFORMED_BY": "执行主体",
    "HAS_RISK": "存在风险",
    "IF": "条件",
    "MENTIONS": "提及",
}

RELATION_TYPE_MAP = {
    "CONTAINS": "CONTAINS",
    "NEXT": "NEXT",
    "APPLIES_TO": "APPLIES_TO",
    "REQUIRES": "REQUIRES",
    "PERFORMED_BY": "PERFORMED_BY",
    "HAS_RISK": "HAS_RISK",
    "IF": "IF",
    "MENTIONS": "MENTIONS",
}

RELATION_PRIORITY = {
    "APPLIES_TO": 1,
    "REQUIRES": 2,
    "PERFORMED_BY": 3,
    "HAS_RISK": 4,
    "IF": 5,
    "NEXT": 6,
    "CONTAINS": 9,
    "MENTIONS": 10,
}

_SUPPORT_RELATIONS = {"CONTAINS", "MENTIONS"}

_CANONICAL_NODE_RULES = {
    "hazard": [
        ("gas", "瓦斯灾害", ["gas", "ch4", "甲烷", "瓦斯"]),
        ("fire", "火灾灾害", ["fire", "明火", "火灾", "烟雾", "烟气", "燃烧"]),
        ("water", "水害风险", ["water", "突水", "透水", "涌水", "积水", "水害"]),
        ("roof", "顶板风险", ["roof", "冒顶", "顶板", "片帮", "垮落"]),
        ("personnel", "人员风险", ["personnel", "被困", "失联", "中毒", "窒息", "伤亡"]),
    ],
    "risk": [
        ("gas", "瓦斯风险", ["gas", "ch4", "甲烷", "瓦斯"]),
        ("fire", "火灾风险", ["fire", "明火", "火灾", "烟雾", "烟气", "燃烧"]),
        ("water", "水害风险", ["water", "突水", "透水", "涌水", "积水", "水害"]),
        ("roof", "顶板风险", ["roof", "冒顶", "顶板", "片帮", "垮落"]),
        ("personnel", "人员风险", ["personnel", "被困", "失联", "中毒", "窒息", "伤亡"]),
    ],
    "step": [
        ("stop_work", "停止作业", ["stop_work", "停止作业", "停止施工", "停产", "停掘"]),
        ("cut_power", "切断电源", ["cut_power", "切断电源", "断电", "停电", "切电"]),
        ("evacuate", "撤离人员", ["evacuate", "撤离", "撤人", "撤出人员", "疏散"]),
        ("ventilate", "加强通风", ["ventilate", "通风", "排放瓦斯", "稀释", "局部通风"]),
        ("report", "上报调度", ["report", "上报", "汇报", "报告调度", "调度室"]),
        ("alert", "设置警戒", ["alert", "警戒", "封控", "禁止进入", "栅栏"]),
        ("rescue", "组织救援", ["rescue", "救援", "搜救", "救护队"]),
        ("self_rescue", "佩戴自救器", ["self_rescue", "自救器", "佩戴"]),
    ],
    "role": [
        ("dispatch", "调度室", ["dispatch", "调度室", "调度中心", "指挥中心"]),
        ("ventilation", "通防部门", ["ventilation", "通防", "通风队", "瓦斯检查", "瓦检"]),
        ("electrical", "机电部门", ["electrical", "机电", "供电", "电工"]),
        ("mining_team", "现场班组", ["mining", "班组", "班组长", "现场人员", "作业人员"]),
        ("safety", "安监部门", ["safety", "安监", "安全员", "安全管理"]),
        ("rescue_team", "矿山救护队", ["rescue_team", "救护队", "救援队", "专业救援"]),
    ],
    "equipment": [
        ("local_fan", "局部通风机", ["local_fan", "局部通风机", "风机"]),
        ("detector", "检测仪", ["detector", "检测仪", "传感器", "监测装置"]),
        ("communication", "通信设备", ["communication", "对讲机", "广播", "通信"]),
        ("self_rescuer", "自救器", ["self_rescuer", "自救器"]),
    ],
    "condition": [
        ("gas_overlimit", "瓦斯超限条件", ["gas_overlimit", "瓦斯浓度", "甲烷浓度", "超限", "1.5%"]),
        ("fire_condition", "火灾征兆", ["fire_condition", "明火", "烟雾", "烟气", "燃烧", "高温"]),
        ("water_inrush_condition", "突水征兆", ["water_inrush", "突水", "透水", "涌水", "积水", "水位"]),
        ("trapped_condition", "人员受困条件", ["trapped", "被困", "失联", "通信中断"]),
    ],
}


# 把关系编码转换成人类可读的关系标签。
def _relation_label(rel_type: str) -> str:
    code = str(rel_type or "").strip()
    return RELATION_LABEL_OVERRIDES.get(code.upper()) or RELATION_LABELS.get(code) or RELATION_LABELS.get(code.lower()) or code


# 读取单次图谱构建允许处理的最大条文数。
def _article_limit() -> int:
    return max(_NO_ARTICLE_LIMIT, int(config.KG_MAX_ARTICLES_PER_BUILD))


# 判断当前处理条文数是否达到预算上限。
def _article_budget_reached(count: int, limit: int) -> bool:
    return limit > 0 and count >= limit


# 创建用于图谱抽取的大模型客户端。
def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=config.require_longcat_api_key(),
        base_url=config.LONGCAT_BASE_URL,
        model=config.LONGCAT_MODEL,
        temperature=0,
        max_tokens=config.LONGCAT_MAX_TOKENS,
        timeout=config.LONGCAT_READ_TIMEOUT,
    )


# 规范化图谱作用域使用的会话编号。
def _get_session_id(session_id: str | None) -> str:
    sid = str(session_id or "").strip()
    return sid or _DEFAULT_SESSION_ID


# 返回当前 UTC 时间戳字符串。
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# 把任意字符串清洗为安全的标识符。
def _safe_id(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^\w\u4e00-\u9fa5.-]+", "_", text)
    return text.strip("_")[:120] or "unknown"


# 生成图节点唯一 UID。
def _node_uid(node_type: str, node_id: str) -> str:
    return f"{node_type}:{node_id}"


# 清洗节点文本键，便于实体归一。
def _normalize_node_key_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[：:；;，,。、“”\"'（）()【】\[\]{}<>《》\-_/\\|]+", "", text)
    for token in ["灾害", "风险", "事故", "措施", "步骤", "动作", "处置", "要求", "条件", "主体", "部门", "设备", "设施"]:
        if len(text) > len(token) + 1:
            text = text.replace(token, "")
    return text or "unknown"


# 把节点归并为统一实体表示。
def _canonical_entity(node_type: str, node_id: str, label: str) -> Tuple[str, str]:
    # 将 LLM 抽取的实体映射到预定义的规范实体 ID 和中文标签（如 "瓦斯""火灾"→ 规范 hazard:gas）。
    clean_type = str(node_type or "").strip().lower()
    raw_id = str(node_id or "").strip()
    raw_label = str(label or raw_id).strip()
    haystack = f"{raw_id} {raw_label}".lower()
    for canonical_id, canonical_label, aliases in _CANONICAL_NODE_RULES.get(clean_type, []):
        if any(str(alias).lower() in haystack for alias in aliases):
            return canonical_id, canonical_label
    if clean_type in {"hazard", "risk", "step", "role", "equipment", "condition"}:
        canonical_id = _safe_id(raw_id) if raw_id else _normalize_node_key_text(raw_label)
        return canonical_id, raw_label or canonical_id
    canonical_id = _safe_id(raw_id) if raw_id else _normalize_node_key_text(raw_label)
    return canonical_id, raw_label or canonical_id


# 为原始实体解析或生成规范化节点 UID。
def _resolve_node_uid(nodes_by_uid: Dict[str, Dict[str, object]], node_type: str, raw_id: str) -> str:
    canonical_id, _ = _canonical_entity(node_type, raw_id, raw_id)
    canonical_uid = _node_uid(node_type, canonical_id)
    if canonical_uid in nodes_by_uid:
        return canonical_uid

    needle = _normalize_node_key_text(raw_id)
    for uid, node in nodes_by_uid.items():
        if str(node.get("type") or "").strip().lower() != node_type:
            continue
        fields = [
            str(node.get("id") or ""),
            str(node.get("label") or ""),
            *(str(item) for item in node.get("aliases", []) if item),
        ]
        if any(_normalize_node_key_text(field) == needle for field in fields):
            return uid
    return canonical_uid


# 从已有 UID 中提取规范化 UID。
def _canonical_uid_from_uid(uid: str) -> str:
    text = str(uid or "").strip()
    if ":" not in text:
        return text
    node_type, raw_id = text.split(":", 1)
    canonical_id, _ = _canonical_entity(node_type, raw_id, raw_id)
    return _node_uid(node_type, canonical_id)


# 合并同一节点的多次抽取结果。
def _merge_node_record(existing: Dict[str, object] | None, incoming: Dict[str, object]) -> Dict[str, object]:
    if not existing:
        merged = dict(incoming)
    else:
        merged = {**existing, **incoming}
    for key in ("sources", "aliases"):
        values = []
        for source in ((existing or {}).get(key), incoming.get(key)):
            if isinstance(source, list):
                values.extend(source)
            elif source:
                values.append(source)
        if values:
            merged[key] = list(dict.fromkeys(str(item) for item in values if str(item or "").strip()))
    return merged


# 将一个节点写入节点映射表。
def _put_node(nodes_by_uid: Dict[str, Dict[str, object]], node: Dict[str, object]) -> None:
    uid = str(node.get("uid") or "").strip()
    if not uid:
        return
    nodes_by_uid[uid] = _merge_node_record(nodes_by_uid.get(uid), node)


# 截断过长证据文本。
def _clip_text(text: str, limit: int = 220) -> str:
    content = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(content) <= limit:
        return content
    return f"{content[:limit]}..."


# 从文本中提取条文编号。
def _extract_article_label(text: str) -> str:
    match = _ARTICLE_LABEL_PATTERN.search(str(text or ""))
    return match.group(0) if match else ""


# 清洗文档列表并统一图谱构建输入。
def _normalize_documents(documents: List[Dict[str, object]] | None) -> List[Dict[str, object]]:
    if not isinstance(documents, list):
        return []
    normalized = []
    for idx, item in enumerate(documents):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        doc_name = str(item.get("doc_name") or item.get("file_name") or item.get("docName") or "未命名文档").strip() or "未命名文档"
        chunk_id = str(item.get("chunk_id") or item.get("chunkId") or f"chunk-{idx + 1:03d}").strip()
        normalized.append({
            **item,
            "doc_name": doc_name,
            "chunk_id": chunk_id,
            "text": text,
            "article_label": str(item.get("article_label") or _extract_article_label(text) or "").strip(),
        })
    return normalized


# 按条文边界切分规程文本。
def _split_articles(text: str, fallback_id: str) -> List[Dict[str, str]]:
    content = str(text or "").strip()
    if not content:
        return []
    parts = [item.strip() for item in _ARTICLE_SPLIT_PATTERN.split(content) if item.strip()]
    if not parts:
        return []
    results = []
    for idx, part in enumerate(parts, start=1):
        label = _extract_article_label(part)
        if not label:
            continue
        results.append({
            "article_id": f"{fallback_id}-{idx:03d}",
            "article_label": label,
            "text": part,
        })
    return results


# 构造单条文图谱抽取提示词。
def _build_graph_extraction_prompt(doc_name: str, article_label: str, text: str) -> str:
    return (
        "请从下面的煤矿安全规程条文中抽取知识图谱三元组，严格输出 JSON。\n"
        "目标：面向煤矿灾害处置与应急救援，只保留真正有决策价值的实体和关系。\n"
        "节点类型只允许使用：regulation, chapter, article, hazard, step, condition, equipment, role, risk。\n"
        "关系类型只允许使用：CONTAINS, NEXT, APPLIES_TO, REQUIRES, PERFORMED_BY, HAS_RISK, IF。\n"
        "不要把纯数字或百分比单独抽成节点；如果有阈值，请放到关系的 condition 属性里。\n"
        "步骤节点应当是可执行动作，如“停止作业”“切断电源”“撤离人员”。\n"
        "条件节点应当是适用条件或前提，如“瓦斯浓度达到1.5%”“突出矿井”“高瓦斯矿井”。\n"
        "输出格式必须是 JSON 对象，结构如下：\n"
        "{\n"
        '  "nodes": [{"type":"hazard","id":"gas","label":"瓦斯灾害"}],\n'
        '  "relationships": [{"source_id":"gas","source_type":"hazard","target_id":"stop_work","target_type":"step","type":"APPLIES_TO","condition":">=1.5%","evidence":"原文片段"}]\n'
        "}\n"
        "如果某条文没有明显的灾害处置知识，返回空数组。\n\n"
        f"文档：{doc_name}\n"
        f"条文：{article_label}\n"
        f"正文：{text}"
    )


# 解析图谱抽取模型返回的 JSON。
def _parse_llm_json(text: str) -> Dict[str, object]:
    content = str(text or "").strip()
    if not content:
        return {"nodes": [], "relationships": []}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            return json.loads(match.group(0))
    return {"nodes": [], "relationships": []}


# 抽取单个条文对应的图谱片段。
def _extract_article_graph(doc_name: str, article_label: str, text: str) -> Dict[str, object]:
    prompt = _build_graph_extraction_prompt(doc_name, article_label, text)
    messages = [
        SystemMessage(content="你是煤矿安全规程知识图谱抽取器，只能输出合法 JSON。"),
        HumanMessage(content=prompt),
    ]
    result = _build_llm().invoke(messages)
    payload = _parse_llm_json(getattr(result, "content", result))
    if not isinstance(payload, dict):
        return {"nodes": [], "relationships": []}
    nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    relationships = payload.get("relationships") if isinstance(payload.get("relationships"), list) else []
    return {"nodes": nodes, "relationships": relationships}


# 清洗和补全抽取出的节点。
def _sanitize_node(node: Dict[str, object], doc_name: str, article_label: str, article_uid: str) -> Dict[str, object] | None:
    # 清洗 LLM 抽取的单个节点：校验类型、映射规范实体、生成 uid，不合格则返回 None。
    node_type = str(node.get("type") or "").strip().lower()
    if node_type not in ALLOWED_NODE_TYPES:
        return None
    raw_id = str(node.get("id") or _safe_id(node.get("label") or "")).strip()
    raw_label = str(node.get("label") or raw_id).strip()
    node_id, label = _canonical_entity(node_type, raw_id, raw_label)
    if not node_id or not label:
        return None
    return {
        "uid": _node_uid(node_type, node_id),
        "type": node_type,
        "type_label": NODE_TYPE_LABELS.get(node_type, node_type),
        "id": node_id,
        "label": label,
        "aliases": list(dict.fromkeys([raw_label, raw_id, label])),
        "doc_name": doc_name,
        "article_label": article_label,
        "sources": [f"{doc_name} · {article_label}"],
        "article_uid": article_uid,
    }


# 清洗和补全抽取出的关系。
def _sanitize_relation(
    rel: Dict[str, object],
    nodes_by_uid: Dict[str, Dict[str, object]],
    doc_name: str,
    article_label: str,
) -> Dict[str, object] | None:
    # 清洗 LLM 抽取的关系：校验类型、解析头尾节点 uid，不合格则返回 None。
    article_label = str(rel.get("article_label") or article_label or "").strip()
    rel_type = str(rel.get("type") or "").strip().upper()
    if rel_type not in ALLOWED_RELATIONS:
        return None
    source_type = str(rel.get("source_type") or "").strip().lower()
    target_type = str(rel.get("target_type") or "").strip().lower()
    #解析头尾节点在已累积的全局 node 池中的 uid
    raw_source_id = str(rel.get("source_id") or "").strip()
    raw_target_id = str(rel.get("target_id") or "").strip()
    if not source_type or not target_type or not raw_source_id or not raw_target_id:
        return None
    source_uid = _resolve_node_uid(nodes_by_uid, source_type, raw_source_id)
    target_uid = _resolve_node_uid(nodes_by_uid, target_type, raw_target_id)
    if source_uid not in nodes_by_uid or target_uid not in nodes_by_uid:
        return None
    source_id = str(nodes_by_uid[source_uid].get("id") or "").strip()
    target_id = str(nodes_by_uid[target_uid].get("id") or "").strip()
    condition = str(rel.get("condition") or "").strip() or None
    evidence = _clip_text(str(rel.get("evidence") or ""), 180) or None
    return {
        "id": f"{source_uid}|{rel_type}|{target_uid}|{_safe_id(article_label)}",
        "source": source_uid,
        "target": target_uid,
        "head_type": source_type,
        "head_id": source_id,
        "head_label": nodes_by_uid[source_uid]["label"],
        "tail_type": target_type,
        "tail_id": target_id,
        "tail_label": nodes_by_uid[target_uid]["label"],
        "relation": rel_type,
        "relation_label": _relation_label(rel_type),
        "source_ref": f"{doc_name} · {article_label}",
        "condition": condition,
        "evidence": evidence,
    }


# 从文档集合构建完整图谱对象。
def _build_graph_documents(documents: List[Dict[str, object]]) -> Dict[str, object]:
    normalized_documents = _normalize_documents(documents)
    nodes_by_uid: Dict[str, Dict[str, object]] = {}
     # 全局节点池，key 是 uid
    relations_by_id: Dict[str, Dict[str, object]] = {}
    # 全局关系池，key 是关系 id
    article_budget = _article_limit()
    article_count = 0

    for doc in normalized_documents:
        doc_name = str(doc["doc_name"])
        document_id = str(doc.get("document_id") or _safe_id(doc_name))
        regulation_uid = _node_uid("regulation", document_id)
        nodes_by_uid.setdefault(regulation_uid, {
            "uid": regulation_uid,
            "type": "regulation",
            "type_label": NODE_TYPE_LABELS["regulation"],
            "id": document_id,
            "label": doc_name,
            "doc_name": doc_name,
            "sources": [doc_name],
        })

        articles = _split_articles(str(Zc["text"]), str(doc["chunk_id"]))
        batch_size = max(1, int(config.KG_LLM_BATCH_SIZE))
        for start in range(0, len(articles), batch_size):
            for article in articles[start:start + batch_size]:
                if _article_budget_reached(article_count, article_budget):
                    break
                article_label = str(article["article_label"])
                article_text = str(article["text"])
                article_uid = _node_uid("article", _safe_id(f"{document_id}:{article_label}"))
                article_node = {
                    "uid": article_uid,
                    "type": "article",
                    "type_label": NODE_TYPE_LABELS["article"],
                    "id": _safe_id(f"{document_id}:{article_label}"),
                    "label": article_label,
                    "doc_name": doc_name,
                    "article_label": article_label,
                    "text_excerpt": _clip_text(article_text, 260),
                    "sources": [f"{doc_name} · {article_label}"],
                }
                nodes_by_uid.setdefault(article_uid, article_node)

                payload = _extract_article_graph(doc_name, article_label, article_text) if config.KG_LLM_ENABLED else {"nodes": [], "relationships": []}
                article_local_nodes: Dict[str, Dict[str, object]] = {}
                for raw_node in payload.get("nodes", []):
                    clean = _sanitize_node(raw_node, doc_name, article_label, article_uid)
                    if clean is None:
                        continue
                    article_local_nodes[clean["uid"]] = clean
                    _put_node(nodes_by_uid, clean)
                    relations_by_id.setdefault(
                        f"{article_uid}|MENTIONS|{clean['uid']}",
                        {
                            "id": f"{article_uid}|MENTIONS|{clean['uid']}",
                            "source": article_uid,
                            "target": clean["uid"],
                            "head_type": "article",
                            "head_id": article_node["id"],
                            "head_label": article_label,
                            "tail_type": clean["type"],
                            "tail_id": clean["id"],
                            "tail_label": clean["label"],
                            "relation": "MENTIONS",
                            "relation_label": _relation_label("MENTIONS"),
                            "source_ref": f"{doc_name} · {article_label}",
                        },
                    )

                relations_by_id.setdefault(
                    f"{regulation_uid}|CONTAINS|{article_uid}",
                    {
                        "id": f"{regulation_uid}|CONTAINS|{article_uid}",
                        "source": regulation_uid,
                        "target": article_uid,
                        "head_type": "regulation",
                        "head_id": document_id,
                        "head_label": doc_name,
                        "tail_type": "article",
                        "tail_id": article_node["id"],
                        "tail_label": article_label,
                        "relation": "CONTAINS",
                        "relation_label": _relation_label("CONTAINS"),
                        "source_ref": doc_name,
                    },
                )

                for raw_rel in payload.get("relationships", []):
                    clean_rel = _sanitize_relation(raw_rel, nodes_by_uid, doc_name, article_label)
                    if clean_rel is None:
                        continue
                    relations_by_id.setdefault(clean_rel["id"], clean_rel)
                article_count += 1
            if _article_budget_reached(article_count, article_budget):
                break
        if _article_budget_reached(article_count, article_budget):
            break

    return _normalize_graph_shape(list(nodes_by_uid.values()), list(relations_by_id.values()))


# 带进度状态地构建文档图谱。
def _build_graph_documents_with_progress(documents: List[Dict[str, object]], session_id: str) -> Dict[str, object]:
    normalized_documents = _normalize_documents(documents)
    nodes_by_uid: Dict[str, Dict[str, object]] = {}
    relations_by_id: Dict[str, Dict[str, object]] = {}
    article_budget = _article_limit()
    article_count = 0

    articles_to_process: List[Tuple[str, str, str, str]] = []
    for doc in normalized_documents:
        doc_name = str(doc["doc_name"])
        document_id = str(doc.get("document_id") or _safe_id(doc_name))
        regulation_uid = _node_uid("regulation", document_id)
        nodes_by_uid.setdefault(regulation_uid, {
            "uid": regulation_uid,
            "type": "regulation",
            "type_label": NODE_TYPE_LABELS["regulation"],
            "id": document_id,
            "label": doc_name,
            "doc_name": doc_name,
            "sources": [doc_name],
        })
        articles = _split_articles(str(doc["text"]), str(doc["chunk_id"]))
        for article in articles:
            articles_to_process.append((doc_name, document_id, article["article_label"], article["text"]))
            if _article_budget_reached(len(articles_to_process), article_budget):
                break
        if _article_budget_reached(len(articles_to_process), article_budget):
            break

    total = len(articles_to_process)
    _set_build_status(session_id, total=total, current=0, progress_percent=0)

    partial_graph = {"nodes": [], "relations": [], "links": [], "document_summaries": [], "stats": {"node_count": 0, "relation_count": 0}}

    for index, (doc_name, document_id, article_label, article_text) in enumerate(articles_to_process, start=1):
        started_percent = max(1, int(index * 100 / total)) if total else 100
        _set_build_status(
            session_id,
            current=index,
            total=total,
            progress_percent=started_percent,
            message=f"正在抽取第 {index}/{total} 条条文",
        )
        article_uid = _node_uid("article", _safe_id(f"{document_id}:{article_label}"))
        article_node = {
            "uid": article_uid,
            "type": "article",
            "type_label": NODE_TYPE_LABELS["article"],
            "id": _safe_id(f"{document_id}:{article_label}"),
            "label": article_label,
            "doc_name": doc_name,
            "article_label": article_label,
            "text_excerpt": _clip_text(article_text, 260),
            "sources": [f"{doc_name} · {article_label}"],
        }
        nodes_by_uid.setdefault(article_uid, article_node)

        payload = _extract_article_graph(doc_name, article_label, article_text) if config.KG_LLM_ENABLED else {"nodes": [], "relationships": []}
        for raw_node in payload.get("nodes", []):
            clean = _sanitize_node(raw_node, doc_name, article_label, article_uid)
            if clean is None:
                continue
            _put_node(nodes_by_uid, clean)
            relations_by_id.setdefault(
                f"{article_uid}|MENTIONS|{clean['uid']}",
                {
                    "id": f"{article_uid}|MENTIONS|{clean['uid']}",
                    "source": article_uid,
                    "target": clean["uid"],
                    "head_type": "article",
                    "head_id": article_node["id"],
                    "head_label": article_label,
                    "tail_type": clean["type"],
                    "tail_id": clean["id"],
                    "tail_label": clean["label"],
                    "relation": "MENTIONS",
                    "relation_label": _relation_label("MENTIONS"),
                    "source_ref": f"{doc_name} · {article_label}",
                },
            )

        regulation_uid = _node_uid("regulation", document_id)
        relations_by_id.setdefault(
            f"{regulation_uid}|CONTAINS|{article_uid}",
            {
                "id": f"{regulation_uid}|CONTAINS|{article_uid}",
                "source": regulation_uid,
                "target": article_uid,
                "head_type": "regulation",
                "head_id": document_id,
                "head_label": doc_name,
                "tail_type": "article",
                "tail_id": article_node["id"],
                "tail_label": article_label,
                "relation": "CONTAINS",
                "relation_label": "包含条文",
                "source_ref": doc_name,
            },
        )

        for raw_rel in payload.get("relationships", []):
            clean_rel = _sanitize_relation(raw_rel, nodes_by_uid, doc_name, article_label)
            if clean_rel is None:
                continue
            relations_by_id.setdefault(clean_rel["id"], clean_rel)

        article_count += 1
        progress_percent = int(article_count * 100 / total) if total else 100
        partial_graph = _merge_graph_chunks(partial_graph, {
            "nodes": list(nodes_by_uid.values()),
            "relations": list(relations_by_id.values()),
            "links": list(relations_by_id.values()),
            "document_summaries": [],
            "stats": {},
        })
        if config.NEO4J_ENABLED:
            _upsert_graph_to_neo4j(session_id, partial_graph)
        _set_build_status(
            session_id,
            current=article_count,
            total=total,
            progress_percent=progress_percent,
            message=f"正在抽取第 {article_count}/{total} 条条文",
        )

    return _normalize_graph_shape(list(nodes_by_uid.values()), list(relations_by_id.values()))


# 获取 Neo4j 驱动连接。
def _get_driver():
    global _DRIVER
    with _DRIVER_LOCK:
        if _DRIVER is None:
            uri, username, password, _ = config.require_neo4j_credentials()
            _DRIVER = GraphDatabase.driver(uri, auth=(username, password))
        return _DRIVER


# 关闭全局 Neo4j 驱动。
def close_driver() -> None:
    # 关闭 Neo4j 连接驱动，在服务关闭时调用释放资源。
    global _DRIVER
    with _DRIVER_LOCK:
        if _DRIVER is not None:
            _DRIVER.close()
            _DRIVER = None


# 执行一条 Neo4j 写操作。
def _execute_write(query: str, **params):
    driver = _get_driver()
    _, _, _, database = config.require_neo4j_credentials()
    with driver.session(database=database) as session:
        return session.execute_write(lambda tx: list(tx.run(query, **params)))


# 执行一条 Neo4j 读操作。
def _execute_read(query: str, **params):
    driver = _get_driver()
    _, _, _, database = config.require_neo4j_credentials()
    with driver.session(database=database) as session:
        return session.execute_read(lambda tx: [record.data() for record in tx.run(query, **params)])


# 确保 Neo4j 中的约束与索引存在。
def _ensure_schema() -> None:
    _execute_write("CREATE CONSTRAINT session_uid IF NOT EXISTS FOR (n:KGNode) REQUIRE (n.session_id, n.uid) IS UNIQUE")
    _execute_write("CREATE INDEX kg_node_session_label IF NOT EXISTS FOR (n:KGNode) ON (n.session_id, n.label)")
    _execute_write("CREATE INDEX kg_node_session_id IF NOT EXISTS FOR (n:KGNode) ON (n.session_id, n.id)")
    _execute_write("CREATE INDEX kg_node_session_type IF NOT EXISTS FOR (n:KGNode) ON (n.session_id, n.type)")
    _execute_write("CREATE INDEX kg_rel_session_id IF NOT EXISTS FOR ()-[r:KG_REL]-() ON (r.session_id, r.id)")
    _execute_write("CREATE INDEX kg_rel_session_relation IF NOT EXISTS FOR ()-[r:KG_REL]-() ON (r.session_id, r.relation)")


# 删除指定会话在 Neo4j 中的图谱数据。
def _clear_session_graph_neo4j(session_id: str) -> None:
    _execute_write(
        """
        MATCH (n:KGNode {session_id: $session_id})
        DETACH DELETE n
        """,
        session_id=session_id,
    )


# 把整张图谱完整写入 Neo4j。
def _write_graph_to_neo4j(session_id: str, graph: Dict[str, object]) -> None:
    _ensure_schema()
    _clear_session_graph_neo4j(session_id)
    _upsert_graph_to_neo4j(session_id, graph)


# 把节点和关系增量写入 Neo4j。
def _upsert_graph_to_neo4j(session_id: str, graph: Dict[str, object]) -> None:
    _ensure_schema()

    node_rows = []
    for node in graph.get("nodes", []):
        node_rows.append({
            "session_id": session_id,
            "uid": node.get("uid"),
            "type": node.get("type"),
            "type_label": node.get("type_label"),
            "id": node.get("id"),
            "label": node.get("label"),
            "aliases": node.get("aliases") or [],
            "doc_name": node.get("doc_name"),
            "article_label": node.get("article_label"),
            "text_excerpt": node.get("text_excerpt"),
            "keywords": node.get("keywords") or [],
            "sources": node.get("sources") or [],
        })

    rel_rows = []
    for rel in graph.get("relations", []):
        rel_id = str(rel.get("id") or "").strip()
        if not rel_id:
            rel_id = f"{rel.get('source')}|{rel.get('relation')}|{rel.get('target')}|{_safe_id(rel.get('source_ref') or rel.get('condition') or '')}"
        rel_rows.append({
            "session_id": session_id,
            "id": rel_id,
            "source": rel.get("source"),
            "target": rel.get("target"),
            "head_type": rel.get("head_type"),
            "head_id": rel.get("head_id"),
            "head_label": rel.get("head_label"),
            "tail_type": rel.get("tail_type"),
            "tail_id": rel.get("tail_id"),
            "tail_label": rel.get("tail_label"),
            "relation": rel.get("relation"),
            "relation_label": rel.get("relation_label"),
            "source_ref": rel.get("source_ref"),
            "condition": rel.get("condition"),
            "evidence": rel.get("evidence"),
        })

    if node_rows:
        _execute_write(
        """
        UNWIND $rows AS row
        MERGE (n:KGNode {session_id: row.session_id, uid: row.uid})
        SET n += row
        FOREACH (_ IN CASE WHEN row.type = 'regulation' THEN [1] ELSE [] END | SET n:Regulation)
        FOREACH (_ IN CASE WHEN row.type = 'chapter' THEN [1] ELSE [] END | SET n:Chapter)
        FOREACH (_ IN CASE WHEN row.type = 'article' THEN [1] ELSE [] END | SET n:Article)
        FOREACH (_ IN CASE WHEN row.type = 'hazard' THEN [1] ELSE [] END | SET n:Hazard)
        FOREACH (_ IN CASE WHEN row.type = 'step' THEN [1] ELSE [] END | SET n:Step)
        FOREACH (_ IN CASE WHEN row.type = 'condition' THEN [1] ELSE [] END | SET n:Condition)
        FOREACH (_ IN CASE WHEN row.type = 'equipment' THEN [1] ELSE [] END | SET n:Equipment)
        FOREACH (_ IN CASE WHEN row.type = 'role' THEN [1] ELSE [] END | SET n:Role)
        FOREACH (_ IN CASE WHEN row.type = 'risk' THEN [1] ELSE [] END | SET n:Risk)
        """,
        rows=node_rows,
        )

    if rel_rows:
        _execute_write(
        """
        UNWIND $rows AS row
        MATCH (a:KGNode {session_id: row.session_id, uid: row.source})
        MATCH (b:KGNode {session_id: row.session_id, uid: row.target})
        MERGE (a)-[r:KG_REL {id: row.id}]->(b)
        SET r += row
        """,
        rows=rel_rows,
        )


# 把多批次抽取得到的图谱片段合并成一张图。
def _merge_graph_chunks(base: Dict[str, object], incoming: Dict[str, object]) -> Dict[str, object]:
    node_map = {str(node.get("uid")): dict(node) for node in base.get("nodes", [])}
    for node in incoming.get("nodes", []):
        uid = str(node.get("uid"))
        if not uid:
            continue
        merged = {**node_map.get(uid, {}), **node}
        sources = list(dict.fromkeys((node_map.get(uid, {}).get("sources") or []) + (node.get("sources") or [])))
        if sources:
            merged["sources"] = sources
        node_map[uid] = merged

    rel_map = {str(rel.get("id")): dict(rel) for rel in base.get("relations", [])}
    for rel in incoming.get("relations", []):
        rid = str(rel.get("id"))
        if rid:
            rel_map[rid] = {**rel_map.get(rid, {}), **rel}

    return _normalize_graph_shape(list(node_map.values()), list(rel_map.values()))


# 统计指定会话图谱的节点和关系数量。
def _stats_for_session(session_id: str) -> Dict[str, object]:
    # 统计某会话在 Neo4j 中的节点和关系数量，结果缓存 10 分钟。
    cache_key = f"stats::{session_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {key: value for key, value in cached.items() if key != "from_cache"}
    stats = _execute_read(
        """
        MATCH (n:KGNode {session_id: $session_id})
        OPTIONAL MATCH ()-[r:KG_REL {session_id: $session_id}]->()
        RETURN count(DISTINCT n) AS node_count, count(DISTINCT r) AS relation_count
        """,
        session_id=session_id,
    )
    result = stats[0] if stats else {"node_count": 0, "relation_count": 0}
    _cache_set(cache_key, result)
    return result


# 返回图谱构建状态文件的路径。
def _status_file(session_id: str) -> Path:
    _STATUS_DIR.mkdir(parents=True, exist_ok=True)
    return _STATUS_DIR / f"{_safe_id(session_id)}.json"


# 将图谱构建状态写入本地文件。
def _write_status_file(session_id: str, status: Dict[str, object]) -> None:
    path = _status_file(session_id)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


# 从本地文件读取图谱构建状态。
def _read_status_file(session_id: str) -> Dict[str, object] | None:
    path = _status_file(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# 更新指定会话的图谱构建状态。
def _set_build_status(session_id: str, **updates) -> Dict[str, object]:
    with _TASK_LOCK:
        status = _GRAPH_BUILD_STATUS.setdefault(session_id, {
            "session_id": session_id,
            "state": "idle",
            "message": "",
            "started_at": None,
            "finished_at": None,
            "node_count": 0,
            "relation_count": 0,
            "current": 0,
            "total": 0,
            "progress_percent": 0,
            "error": "",
        })
        status.update(updates)
        snapshot = dict(status)
        _write_status_file(session_id, snapshot)
        return snapshot


# 获取当前会话图谱构建状态。
def get_graph_build_status(session_id: str | None) -> Dict[str, object]:
    sid = _get_session_id(session_id)
    with _TASK_LOCK:
        memory_status = _GRAPH_BUILD_STATUS.get(sid)
    file_status = _read_status_file(sid)
    if memory_status is None and file_status and file_status.get("state") in {"running", "queued"}:
        file_status = {
            **file_status,
            "state": "failed",
            "message": "上次知识图谱构建已中断，请重新构建",
            "finished_at": _now_iso(),
            "error": "stale build status after backend restart",
        }
        _write_status_file(sid, file_status)
    status = dict(memory_status or file_status or {
            "session_id": sid,
            "state": "idle",
            "message": "",
            "started_at": None,
            "finished_at": None,
            "node_count": 0,
            "relation_count": 0,
            "current": 0,
            "total": 0,
            "progress_percent": 0,
            "error": "",
        })
    if (
        status["state"] == "completed"
        and config.NEO4J_ENABLED
        and (not int(status.get("node_count") or 0) or not int(status.get("relation_count") or 0))
    ):
        stats = _stats_for_session(sid)
        status["node_count"] = int(stats.get("node_count") or 0)
        status["relation_count"] = int(stats.get("relation_count") or 0)
        _write_status_file(sid, status)
    return status


# 在文档变化后把图谱状态标记为待重建。
def mark_graph_build_pending(session_id: str | None, has_documents: bool = True) -> Dict[str, object]:
    sid = _get_session_id(session_id)
    _cache_clear()
    return _set_build_status(
        sid,
        state="idle",
        message="文档已更新，请在知识图谱库点击“生成知识图谱”" if has_documents else "当前会话暂无文档，可先上传规程文档后再生成知识图谱",
        started_at=None,
        finished_at=None,
        node_count=0,
        relation_count=0,
        current=0,
        total=0,
        progress_percent=0,
        error="",
    )


# 构建一张内存中的知识图谱。
def build_knowledge_graph(documents: List[Dict[str, object]]) -> Dict[str, object]:
    # 从文档列表构建知识图谱：LLM 抽取三元组 → 标准化 → 合并去重，不写入 Neo4j。
    return _build_graph_documents(documents) if config.KG_ENABLED else {
        "nodes": [], "relations": [], "links": [], "document_summaries": [], "stats": {}
    }


# 构建并持久化当前会话的知识图谱。
def build_and_store_session_graph(session_id: str | None, documents: List[Dict[str, object]]) -> Dict[str, object]:
    # 从文档构建图谱并写入 Neo4j。同步执行，一般被 rebuild 接口或问答流程调用。
    sid = _get_session_id(session_id)
    graph = build_knowledge_graph(documents)
    if config.NEO4J_ENABLED:
        _write_graph_to_neo4j(sid, graph)
    return graph


# 启动异步知识图谱构建任务。
def start_graph_build(session_id: str | None, documents: List[Dict[str, object]]) -> Dict[str, object]:
    sid = _get_session_id(session_id)
    current = get_graph_build_status(sid)
    if current.get("state") in {"running", "queued"}:
        return current

    normalized_documents = _normalize_documents(documents)
    article_budget = _article_limit()
    total_articles = 0
    for doc in normalized_documents:
        articles = _split_articles(str(doc["text"]), str(doc["chunk_id"]))
        total_articles += len(articles)
        if _article_budget_reached(total_articles, article_budget):
            total_articles = article_budget
            break

    _set_build_status(
        sid,
        state="queued",
        message=f"图谱构建任务排队中（共 {total_articles} 条条文）",
        started_at=_now_iso(),
        finished_at=None,
        current=0,
        total=total_articles,
        progress_percent=0,
        error="",
    )

    # 异步任务执行函数：在后台真正完成图谱构建并更新状态。
    def _runner():
        try:
            _set_build_status(
                sid,
                state="running",
                message=f"正在使用大模型抽取三元组并写入 Neo4j（共 {total_articles} 条）",
            )
            graph = _build_graph_documents_with_progress(documents, sid)
            if config.NEO4J_ENABLED:
                _write_graph_to_neo4j(sid, graph)
            stats = graph.get("stats", {})
            _set_build_status(
                sid,
                state="completed",
                message="知识图谱构建完成",
                finished_at=_now_iso(),
                node_count=int(stats.get("node_count") or 0),
                relation_count=int(stats.get("relation_count") or 0),
                progress_percent=100,
                error="",
            )
        except Exception as exc:
            _set_build_status(
                sid,
                state="failed",
                message="知识图谱构建失败",
                finished_at=_now_iso(),
                error=str(exc),
            )

    future = _BUILD_EXECUTOR.submit(_runner)
    with _TASK_LOCK:
        _GRAPH_BUILD_FUTURES[sid] = future
    return get_graph_build_status(sid)


# 把外部三元组载荷转换成图谱对象。
def _build_graph_from_extracted_payload(payload: Dict[str, object], doc_name: str = "uploaded triples") -> Dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("三元组文件必须是 JSON 对象")
    nodes_by_uid: Dict[str, Dict[str, object]] = {}
    relations_by_id: Dict[str, Dict[str, object]] = {}

    article_label = str(payload.get("article_label") or "上传三元组").strip()
    article_uid = _node_uid("article", _safe_id(f"{doc_name}:{article_label}"))
    raw_nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    raw_relations = payload.get("relationships") if isinstance(payload.get("relationships"), list) else []
    if not raw_relations:
        raw_relations = payload.get("relations") if isinstance(payload.get("relations"), list) else []
    if not raw_relations:
        raw_relations = payload.get("links") if isinstance(payload.get("links"), list) else []

    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue
        clean = _sanitize_node(raw_node, doc_name, article_label, article_uid)
        if clean:
            _put_node(nodes_by_uid, clean)

    for raw_rel in raw_relations:
        if not isinstance(raw_rel, dict):
            continue
        clean_rel = _sanitize_relation(raw_rel, nodes_by_uid, doc_name, article_label)
        if clean_rel:
            relations_by_id[clean_rel["id"]] = clean_rel

    graph = _normalize_graph_shape(list(nodes_by_uid.values()), list(relations_by_id.values()))
    if not graph["nodes"] or not graph["relations"]:
        raise ValueError("三元组文件没有可导入的节点或关系")
    return graph


# 导入外部三元组 JSON 并写入会话图谱。
def import_triples_graph(session_id: str | None, payload: Dict[str, object], doc_name: str = "uploaded triples") -> Dict[str, object]:
    # 导入预抽取的三元组 JSON：规范化后直接写入 Neo4j，跳过 LLM 抽取步骤。
    sid = _get_session_id(session_id)
    graph = _build_graph_from_extracted_payload(payload, doc_name=doc_name)
    if config.NEO4J_ENABLED:
        _write_graph_to_neo4j(sid, graph)
    _cache_clear()
    stats = graph.get("stats", {})
    _set_build_status(
        sid,
        state="completed",
        message="三元组已导入 Neo4j",
        started_at=_now_iso(),
        finished_at=_now_iso(),
        node_count=int(stats.get("node_count") or 0),
        relation_count=int(stats.get("relation_count") or 0),
        current=int(stats.get("relation_count") or 0),
        total=int(stats.get("relation_count") or 0),
        progress_percent=100,
        error="",
    )
    return graph


# 标准化关系对象字段。
def _normalize_relation(rel: Dict[str, object]) -> Dict[str, object]:
    normalized = dict(rel)
    relation = str(normalized.get("relation") or normalized.get("type") or "").strip().upper()
    normalized["relation"] = relation
    normalized["relation_label"] = _relation_label(normalized.get("relation_label") or relation)
    return normalized


# 标准化节点对象字段。
def _normalize_node(node: Dict[str, object]) -> Dict[str, object]:
    normalized = dict(node)
    node_type = str(normalized.get("type") or "").strip()
    if node_type:
        canonical_id, canonical_label = _canonical_entity(
            node_type,
            str(normalized.get("id") or ""),
            str(normalized.get("label") or ""),
        )
        normalized["id"] = canonical_id
        normalized["label"] = canonical_label or normalized.get("label") or canonical_id
        normalized["uid"] = _node_uid(node_type, canonical_id)
    if node_type and not normalized.get("type_label"):
        normalized["type_label"] = NODE_TYPE_LABELS.get(node_type, node_type)
    return normalized


# 统一图谱对象的 nodes/relations/links 结构。
def _normalize_graph_shape(nodes: List[Dict[str, object]], relations: List[Dict[str, object]]) -> Dict[str, object]:
    # 将节点和关系列表统一规范化：实体映射、uid 重定向、去重合并、按优先级排序，输出标准图谱结构。
    node_map: Dict[str, Dict[str, object]] = {}
    uid_redirect: Dict[str, str] = {}
    for raw_node in nodes:
        if not isinstance(raw_node, dict):
            continue
        old_uid = str(raw_node.get("uid") or "").strip()
        node = _normalize_node(raw_node)
        uid = str(node.get("uid") or "").strip()
        if not uid:
            continue
        if old_uid and old_uid != uid:
            uid_redirect[old_uid] = uid
        _put_node(node_map, node)

    rel_map: Dict[str, Dict[str, object]] = {}
    for raw_rel in relations:
        if not isinstance(raw_rel, dict):
            continue
        rel = _normalize_relation(raw_rel)
        source = uid_redirect.get(str(rel.get("source") or ""), str(rel.get("source") or ""))
        target = uid_redirect.get(str(rel.get("target") or ""), str(rel.get("target") or ""))
        if not source or not target or source == target or source not in node_map or target not in node_map:
            continue
        source_node = node_map[source]
        target_node = node_map[target]
        relation = str(rel.get("relation") or "").strip().upper()
        rel["source"] = source
        rel["target"] = target
        rel["head_type"] = source_node.get("type")
        rel["head_id"] = source_node.get("id")
        rel["head_label"] = source_node.get("label")
        rel["tail_type"] = target_node.get("type")
        rel["tail_id"] = target_node.get("id")
        rel["tail_label"] = target_node.get("label")
        rel["relation"] = relation
        rel["relation_label"] = _relation_label(relation)
        rel["id"] = f"{source}|{relation}|{target}|{_safe_id(rel.get('source_ref') or rel.get('condition') or rel.get('evidence') or '')}"
        rel_map[str(rel["id"])] = rel

    normalized_nodes = list(node_map.values())
    normalized_relations = sorted(
        rel_map.values(),
        key=lambda item: (_relation_priority(str(item.get("relation"))), str(item.get("head_label")), str(item.get("tail_label"))),
    )
    type_counter = Counter(str(node.get("type")) for node in normalized_nodes)
    relation_counter = Counter(str(rel.get("relation")) for rel in normalized_relations)
    return {
        "nodes": normalized_nodes,
        "relations": normalized_relations,
        "links": normalized_relations,
        "document_summaries": [],
        "stats": {
            "node_count": len(normalized_nodes),
            "relation_count": len(normalized_relations),
            "node_types": dict(type_counter),
            "relation_types": dict(relation_counter),
            "updated_at": _now_iso(),
        },
    }


# 裁剪图谱视图，只保留适合展示的语义节点和关系。
def _visible_semantic_view(nodes: List[Dict[str, object]], relations: List[Dict[str, object]], limit: int = 1000) -> Dict[str, object]:
    # 过滤掉支援边（CONTAINS/MENTIONS）和非业务节点（regulation/chapter/article），只保留语义关系和灾害相关节点供前端展示。
    visible_nodes_by_uid = {
        str(node.get("uid")): node
        for node in nodes
        if str(node.get("type")) in _VISIBLE_NODE_TYPES and str(node.get("uid") or "").strip()
    }
    semantic_relations = [
        rel for rel in relations
        if str(rel.get("relation") or "").upper() not in _SUPPORT_RELATIONS
        and str(rel.get("source")) in visible_nodes_by_uid
        and str(rel.get("target")) in visible_nodes_by_uid
    ]
    semantic_relations = sorted(
        semantic_relations,
        key=lambda item: (_relation_priority(str(item.get("relation"))), str(item.get("head_label")), str(item.get("tail_label"))),
    )
    safe_limit = max(1, int(limit or 1000))
    visible_relations = semantic_relations[:safe_limit]
    connected_uids = {str(rel.get("source")) for rel in visible_relations} | {str(rel.get("target")) for rel in visible_relations}
    visible_nodes = [node for uid, node in visible_nodes_by_uid.items() if uid in connected_uids]
    return {
        "nodes": visible_nodes,
        "relations": visible_relations,
        "links": visible_relations,
        "view_stats": {
            "node_count": len(visible_nodes),
            "relation_count": len(visible_relations),
        },
        "has_more": len(semantic_relations) > len(visible_relations),
        "truncated": len(semantic_relations) > len(visible_relations),
    }


# 读取图谱查询缓存。
def _cache_get(key: str) -> Dict[str, object] | None:
    now = time.time()
    with _GRAPH_QUERY_CACHE_LOCK:
        item = _GRAPH_QUERY_CACHE.get(key)
        if not item:
            return None
        created_at, value = item
        if now - created_at > _GRAPH_QUERY_CACHE_TTL_SECONDS:
            _GRAPH_QUERY_CACHE.pop(key, None)
            return None
        cached = deepcopy(value)
        cached["from_cache"] = True
        return cached


# 写入图谱查询缓存。
def _cache_set(key: str, value: Dict[str, object]) -> Dict[str, object]:
    with _GRAPH_QUERY_CACHE_LOCK:
        if len(_GRAPH_QUERY_CACHE) >= _GRAPH_QUERY_CACHE_MAX_ITEMS:
            oldest_key = min(_GRAPH_QUERY_CACHE, key=lambda item: _GRAPH_QUERY_CACHE[item][0])
            _GRAPH_QUERY_CACHE.pop(oldest_key, None)
        snapshot = deepcopy(value)
        snapshot["from_cache"] = False
        _GRAPH_QUERY_CACHE[key] = (time.time(), snapshot)
    result = deepcopy(value)
    result["from_cache"] = False
    return result


# 清空图谱查询缓存。
def _cache_clear() -> None:
    with _GRAPH_QUERY_CACHE_LOCK:
        _GRAPH_QUERY_CACHE.clear()


# 返回关系类型的排序优先级。
def _relation_priority(relation: str) -> int:
    return RELATION_PRIORITY.get(str(relation or "").upper(), 50)


# 把底层记录整理成前端可直接消费的图谱结果。
def _finalize_graph_response(
    records: List[Dict[str, object]],
    *,
    stats: Dict[str, object] | None = None,
    query: str = "",
    center_uid: str = "",
    matched_uids: List[str] | None = None,
    limit: int = 80,
    offset: int = 0,
    total_relations: int | None = None,
) -> Dict[str, object]:
    graph = _map_neo4j_records_to_graph(records)
    graph = _normalize_graph_shape(list(graph.get("nodes", [])), list(graph.get("relations", [])))
    relation_count = len(graph["relations"])
    total = total_relations if total_relations is not None else relation_count
    graph["stats"] = stats or {"node_count": len(graph["nodes"]), "relation_count": relation_count}
    graph["query"] = query
    graph["center_uid"] = _canonical_uid_from_uid(center_uid)
    graph["matched_uids"] = list(dict.fromkeys(
        _canonical_uid_from_uid(uid)
        for uid in (matched_uids or ([center_uid] if center_uid else []))
        if str(uid or "").strip()
    ))
    graph["limit"] = limit
    graph["offset"] = offset
    graph["returned_relation_count"] = relation_count
    graph["total_relation_count"] = total
    graph["has_more"] = offset + relation_count < total
    graph["truncated"] = graph["has_more"] or relation_count >= limit
    graph["from_cache"] = False
    return graph


# 把 Neo4j 查询结果映射成图谱结构。
def _map_neo4j_records_to_graph(records: List[Dict[str, object]]) -> Dict[str, object]:
    nodes: Dict[str, Dict[str, object]] = {}
    relations: Dict[str, Dict[str, object]] = {}
    for record in records:
        source_node = record.get("source_node")
        target_node = record.get("target_node")
        rel = record.get("rel")
        for node in [source_node, target_node]:
            if not node:
                continue
            nodes[str(node["uid"])] = _merge_node_record(nodes.get(str(node["uid"])), dict(node))
        if rel:
            relations[str(rel["id"])] = dict(rel)

    for node in list(nodes.values()):
        article_uid = str(node.get("article_uid") or "").strip()
        node_uid = str(node.get("uid") or "").strip()
        if not article_uid or not node_uid or article_uid == node_uid or article_uid not in nodes:
            continue
        rel_id = f"{article_uid}|MENTIONS|{node_uid}"
        if rel_id in relations:
            continue
        article = nodes[article_uid]
        relations[rel_id] = {
            "id": rel_id,
            "source": article_uid,
            "target": node_uid,
            "head_type": "article",
            "head_id": article.get("id"),
            "head_label": article.get("label"),
            "tail_type": node.get("type"),
            "tail_id": node.get("id"),
            "tail_label": node.get("label"),
            "relation": "MENTIONS",
            "relation_label": _relation_label("MENTIONS"),
            "source_ref": node.get("source_ref") or node.get("article_label") or article.get("article_label"),
            "virtual": True,
        }

    return {"nodes": list(nodes.values()), "relations": list(relations.values()), "links": list(relations.values())}


# 读取某个会话完整的知识图谱。
def get_session_graph(session_id: str | None) -> Dict[str, object]:
    # 从 Neo4j 读取指定会话的完整知识图谱，返回标准化格式。
    sid = _get_session_id(session_id)
    if not config.NEO4J_ENABLED:
        return {"nodes": [], "relations": [], "links": [], "document_summaries": [], "stats": {"node_count": 0, "relation_count": 0}}
    records = _execute_read(
        """
        MATCH (a:KGNode {session_id: $session_id})-[r:KG_REL {session_id: $session_id}]->(b:KGNode {session_id: $session_id})
        RETURN properties(a) AS source_node, properties(r) AS rel, properties(b) AS target_node
        """,
        session_id=sid,
    )
    graph = _finalize_graph_response(records, stats=_stats_for_session(sid), limit=len(records) or 1)
    graph["document_summaries"] = []
    return graph


# 清空某个会话的知识图谱。
def clear_session_graph(session_id: str | None) -> bool:
    # 删除指定会话在 Neo4j 中的所有图谱节点和关系。
    sid = _get_session_id(session_id)
    if not config.NEO4J_ENABLED:
        return False
    _clear_session_graph_neo4j(sid)
    return True


# 过滤掉不需要展示的支撑类节点。
def _strip_support_nodes(nodes: List[Dict[str, object]], relations: List[Dict[str, object]]) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    view = _visible_semantic_view(nodes, relations, limit=max(len(relations), 1))
    return view["nodes"], view["relations"]


# 根据关键词判断当前查询主题。
def _detect_topic(keyword: str) -> Dict[str, object] | None:
    text = str(keyword or "").strip()
    if not text:
        return None
    for rule in _TOPIC_RULES.values():
        if any(token in text for token in rule["tokens"]):
            return rule
    return None


# 判断节点是否命中查询关键词。
def _node_matches_keyword(node: Dict[str, object], keyword: str) -> bool:
    text = str(keyword or "").strip()
    if not text:
        return False
    fields = [
        str(node.get("label", "")),
        str(node.get("id", "")),
        str(node.get("type_label", "")),
        " ".join(map(str, node.get("keywords", []) if isinstance(node.get("keywords"), list) else [])),
        " ".join(map(str, node.get("sources", []) if isinstance(node.get("sources"), list) else [])),
    ]
    return any(text in field for field in fields)


# 判断关系是否命中查询关键词。
def _relation_matches_keyword(rel: Dict[str, object], keyword: str) -> bool:
    text = str(keyword or "").strip()
    if not text:
        return False
    fields = [
        str(rel.get("head_label", "")),
        str(rel.get("tail_label", "")),
        str(rel.get("relation_label", "")),
        str(rel.get("source_ref", "")),
        str(rel.get("condition", "")),
        str(rel.get("evidence", "")),
    ]
    return any(text in field for field in fields)


# 为检索阶段计算图谱相关度分值。
def score_graph_relevance(
    query: str,
    *,
    session_id: Optional[str] = None,
    graph: Optional[Dict[str, object]] = None,
    risk_types: Optional[List[str]] = None,
    article_label: str = "",
    text: str = "",
    doc_name: str = "",
) -> Dict[str, object]:
    """为检索重排提供图谱相关度分数。"""
    query_text = str(query or "").strip()
    if not query_text:
        return {
            "score": 0.0,
            "matched_nodes": [],
            "matched_relations": [],
            "matched_article_labels": [],
            "matched_doc_names": [],
        }

    source_graph = graph
    if source_graph is None:
        sid = _get_session_id(session_id)
        if config.NEO4J_ENABLED:
            try:
                source_graph = get_session_graph(sid)
            except Exception:
                source_graph = {"nodes": [], "relations": [], "links": []}
        else:
            source_graph = {"nodes": [], "relations": [], "links": []}

    normalized = _normalize_graph_shape(
        list((source_graph or {}).get("nodes", [])),
        list((source_graph or {}).get("relations", (source_graph or {}).get("links", []))),
    )
    nodes = list(normalized.get("nodes", []))
    relations = list(normalized.get("relations", []))

    matched_nodes = [node for node in nodes if _node_matches_keyword(node, query_text)]
    matched_relations = [rel for rel in relations if _relation_matches_keyword(rel, query_text)]

    score = 0.0
    seen_node_uids = set()
    for node in matched_nodes:
        uid = str(node.get("uid") or "")
        if uid in seen_node_uids:
            continue
        seen_node_uids.add(uid)
        label = str(node.get("label") or "")
        node_score = 1.0
        if label == query_text:
            node_score += 2.0
        elif query_text in label:
            node_score += 0.8
        score += node_score

    seen_rel_ids = set()
    for rel in matched_relations:
        rel_id = str(rel.get("id") or "")
        if rel_id in seen_rel_ids:
            continue
        seen_rel_ids.add(rel_id)
        rel_score = 1.2
        if query_text in str(rel.get("relation_label") or ""):
            rel_score += 0.8
        if query_text in str(rel.get("condition") or ""):
            rel_score += 0.6
        if query_text in str(rel.get("evidence") or ""):
            rel_score += 0.6
        rel_score += max(0.1, 1.2 / max(1, _relation_priority(str(rel.get("relation")))))
        score += rel_score

    article_hits = {
        str(rel.get("source_ref") or "").split("·", 1)[-1].strip()
        for rel in matched_relations
        if str(rel.get("source_ref") or "").strip()
    }
    article_hits |= {
        str(node.get("article_label") or "").strip()
        for node in matched_nodes
        if str(node.get("article_label") or "").strip()
    }

    doc_hits = {
        str(rel.get("source_ref") or "").split("·", 1)[0].strip()
        for rel in matched_relations
        if str(rel.get("source_ref") or "").strip()
    }
    doc_hits |= {
        str(node.get("doc_name") or "").strip()
        for node in matched_nodes
        if str(node.get("doc_name") or "").strip()
    }

    article_label_text = str(article_label or "").strip()
    if article_label_text and article_label_text in article_hits:
        score += 2.0

    doc_name_text = str(doc_name or "").strip()
    if doc_name_text and doc_name_text in doc_hits:
        score += 1.0

    text_content = str(text or "")
    if article_label_text and article_label_text in text_content:
        score += 0.5
    if query_text and query_text in text_content:
        score += 0.5

    normalized_risk_types = {str(item or "").strip() for item in (risk_types or []) if str(item or "").strip()}
    if normalized_risk_types:
        for node in matched_nodes:
            if str(node.get("type") or "").strip() in {"hazard", "risk"}:
                node_id = str(node.get("id") or "").strip()
                if node_id in normalized_risk_types:
                    score += 1.5

    return {
        "score": round(float(score), 4),
        "matched_nodes": matched_nodes,
        "matched_relations": matched_relations,
        "matched_article_labels": sorted(item for item in article_hits if item),
        "matched_doc_names": sorted(item for item in doc_hits if item),
    }


# 在图谱上执行轻量关键字查询。
def query_graph(graph: Dict[str, object], keyword: str = "", limit: int = 80) -> Dict[str, object]:
    # 在内存图谱中按关键词过滤节点和关系，过滤支援边（CONTAINS/MENTIONS）只保留语义边。
    normalized = _normalize_graph_shape(list(graph.get("nodes", [])), list(graph.get("relations", graph.get("links", []))))
    nodes = list(normalized.get("nodes", []))
    relations = list(normalized.get("relations", normalized.get("links", [])))
    keyword_text = str(keyword or "").strip()
    limit = max(10, int(limit or 80))
    visible_view = _visible_semantic_view(nodes, relations, limit=max(len(relations), 1))
    visible_nodes = visible_view["nodes"]
    visible_relations = visible_view["relations"]

    if keyword_text:
        matched_uids = {str(node.get("uid")) for node in visible_nodes if _node_matches_keyword(node, keyword_text)}
        filtered_relations = [
            rel for rel in visible_relations
            if str(rel.get("source")) in matched_uids
            or str(rel.get("target")) in matched_uids
            or _relation_matches_keyword(rel, keyword_text)
        ]
        related_uids = set(matched_uids)
        for rel in filtered_relations:
            related_uids.add(str(rel.get("source")))
            related_uids.add(str(rel.get("target")))
        filtered_nodes = [node for node in visible_nodes if str(node.get("uid")) in related_uids]
    else:
        filtered_nodes = visible_nodes
        filtered_relations = visible_relations

    if len(filtered_nodes) > limit:
        keep_uids = {str(node.get("uid")) for node in filtered_nodes[:limit]}
        filtered_nodes = filtered_nodes[:limit]
        filtered_relations = [
            rel for rel in filtered_relations
            if str(rel.get("source")) in keep_uids and str(rel.get("target")) in keep_uids
        ]
    connected_uids = {str(rel.get("source")) for rel in filtered_relations} | {str(rel.get("target")) for rel in filtered_relations}
    filtered_nodes = [node for node in filtered_nodes if str(node.get("uid")) in connected_uids]

    return {
        "nodes": filtered_nodes,
        "relations": filtered_relations,
        "links": filtered_relations,
        "stats": normalized.get("stats", graph.get("stats", {})),
        "query": keyword_text,
    }


# 围绕关键词返回局部聚焦子图。
def query_centered_graph(session_id: str | None, keyword: str = "", limit: int = 80, depth: int = 1) -> Dict[str, object]:
    # 在 Neo4j 中以关键词匹配的节点为中心，返回其一跳邻居子图（按关系优先级排序输出）。
    sid = _get_session_id(session_id)
    keyword_text = str(keyword or "").strip()
    safe_limit = min(160, max(10, int(limit or 80)))
    safe_depth = min(2, max(1, int(depth or 1)))
    cache_key = f"center::{sid}::{keyword_text}::{safe_limit}::{safe_depth}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    if not config.NEO4J_ENABLED:
        return {"nodes": [], "relations": [], "links": [], "stats": {"node_count": 0, "relation_count": 0}, "query": keyword_text, "center_uid": "", "matched_uids": [], "has_more": False, "truncated": False, "from_cache": False}

    if keyword_text:
        center_rows = _execute_read(
            """
            MATCH (n:KGNode {session_id: $session_id})
            WHERE n.label = $keyword OR n.id = $keyword
               OR n.label CONTAINS $keyword OR n.id CONTAINS $keyword
               OR n.type_label CONTAINS $keyword
            OPTIONAL MATCH (n)-[r:KG_REL {session_id: $session_id}]-()
            WITH n,
                 CASE
                   WHEN n.label = $keyword THEN 0
                   WHEN n.id = $keyword THEN 1
                   WHEN n.label CONTAINS $keyword THEN 2
                   WHEN n.id CONTAINS $keyword THEN 3
                   ELSE 4
                 END AS score,
                 count(r) AS degree
            RETURN n.uid AS uid, score, degree
            ORDER BY degree DESC, score ASC, size(coalesce(n.label, '')) ASC
            LIMIT 6
            """,
            session_id=sid,
            keyword=keyword_text,
        )
        matched_uids = [str(row.get("uid")) for row in center_rows if row.get("uid")]
        if not matched_uids:
            center_rows = _execute_read(
                """
                MATCH (a:KGNode {session_id: $session_id})-[r:KG_REL {session_id: $session_id}]->(b:KGNode {session_id: $session_id})
                WHERE r.head_label CONTAINS $keyword
                   OR r.tail_label CONTAINS $keyword
                   OR r.relation_label CONTAINS $keyword
                   OR r.condition CONTAINS $keyword
                   OR r.evidence CONTAINS $keyword
                OPTIONAL MATCH (a)-[ra:KG_REL {session_id: $session_id}]-()
                OPTIONAL MATCH (b)-[rb:KG_REL {session_id: $session_id}]-()
                RETURN a.uid AS source_uid, b.uid AS target_uid, count(DISTINCT ra) AS source_degree, count(DISTINCT rb) AS target_degree
                LIMIT 6
                """,
                session_id=sid,
                keyword=keyword_text,
            )
            ranked_uids = []
            for row in center_rows:
                if row.get("source_uid"):
                    ranked_uids.append((str(row["source_uid"]), int(row.get("source_degree") or 0)))
                if row.get("target_uid"):
                    ranked_uids.append((str(row["target_uid"]), int(row.get("target_degree") or 0)))
            deduped = {}
            for uid, degree in ranked_uids:
                if uid not in deduped or degree > deduped[uid]:
                    deduped[uid] = degree
            matched_uids = [
                uid for uid, _degree in sorted(deduped.items(), key=lambda item: (-item[1], item[0]))
            ][:1]
    else:
        center_rows = _execute_read(
            """
            MATCH (n:KGNode {session_id: $session_id})
            OPTIONAL MATCH (n)-[r1:KG_REL {session_id: $session_id}]-()
            WITH n, count(r1) AS degree
            WHERE degree > 0
            RETURN n.uid AS uid, degree
            ORDER BY degree DESC
            LIMIT 1
            """,
            session_id=sid,
        )
        matched_uids = [str(row.get("uid")) for row in center_rows if row.get("uid")]

    if not matched_uids:
        result = _finalize_graph_response([], stats=_stats_for_session(sid), query=keyword_text, limit=safe_limit)
        return _cache_set(cache_key, result)

    matched_uids = matched_uids[:1]

    records = _execute_read(
        """
        MATCH (center:KGNode {session_id: $session_id})
        WHERE center.uid IN $uids
        MATCH (center)-[r:KG_REL {session_id: $session_id}]-(neighbor:KGNode {session_id: $session_id})
        WITH center, r, neighbor,
             CASE coalesce(r.relation, '')
               WHEN 'APPLIES_TO' THEN 1
               WHEN 'REQUIRES' THEN 2
               WHEN 'PERFORMED_BY' THEN 3
               WHEN 'HAS_RISK' THEN 4
               WHEN 'IF' THEN 5
               WHEN 'NEXT' THEN 6
               WHEN 'CONTAINS' THEN 9
               ELSE 50
             END AS rel_order
        ORDER BY center.uid, rel_order ASC, coalesce(r.relation_label, '') ASC, coalesce(neighbor.label, '') ASC
        WITH collect({source_node: properties(startNode(r)), rel: properties(r), target_node: properties(endNode(r))}) AS rows
        WITH rows, size(rows) AS total
        UNWIND rows[..$limit] AS row
        RETURN row.source_node AS source_node, row.rel AS rel, row.target_node AS target_node, total
        """,
        session_id=sid,
        uids=matched_uids,
        limit=safe_limit,
    )
    total_relations = int(records[0].get("total") or len(records)) if records else 0
    result = _finalize_graph_response(
        records,
        stats=_stats_for_session(sid),
        query=keyword_text,
        center_uid=matched_uids[0],
        matched_uids=matched_uids,
        limit=safe_limit,
        total_relations=total_relations,
    )
    semantic_view = _visible_semantic_view(result.get("nodes", []), result.get("relations", []), limit=safe_limit)
    result["nodes"] = semantic_view["nodes"]
    result["relations"] = semantic_view["relations"]
    result["links"] = semantic_view["links"]
    result["has_more"] = semantic_view["has_more"]
    result["truncated"] = semantic_view["truncated"]
    result["returned_relation_count"] = len(result["relations"])
    return _cache_set(cache_key, result)


# 沿某个节点继续展开邻接关系。
def expand_graph_neighbors(session_id: str | None, node_uid: str, limit: int = 60, offset: int = 0, direction: str = "both") -> Dict[str, object]:
    # 展开指定节点的一跳邻居，支持分页和方向过滤（out/in/both），用于前端图谱交互式探索。
    sid = _get_session_id(session_id)
    target_uid = str(node_uid or "").strip()
    safe_limit = min(120, max(10, int(limit or 60)))
    safe_offset = max(0, int(offset or 0))
    safe_direction = str(direction or "both").strip().lower()
    if safe_direction not in {"both", "out", "in"}:
        safe_direction = "both"
    if not target_uid:
        return {"nodes": [], "relations": [], "links": [], "stats": {"node_count": 0, "relation_count": 0}, "has_more": False, "from_cache": False}
    cache_key = f"expand::{sid}::{target_uid}::{safe_limit}::{safe_offset}::{safe_direction}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if safe_direction == "out":
        query = """
        MATCH (center:KGNode {session_id: $session_id, uid: $uid})-[r:KG_REL {session_id: $session_id}]->(neighbor:KGNode {session_id: $session_id})
        WITH r,
             CASE coalesce(r.relation, '')
               WHEN 'APPLIES_TO' THEN 1
               WHEN 'REQUIRES' THEN 2
               WHEN 'PERFORMED_BY' THEN 3
               WHEN 'HAS_RISK' THEN 4
               WHEN 'IF' THEN 5
               WHEN 'NEXT' THEN 6
               WHEN 'CONTAINS' THEN 9
               ELSE 50
             END AS rel_order
        ORDER BY rel_order ASC, coalesce(r.relation_label, '') ASC, coalesce(neighbor.label, '') ASC
        WITH collect({source_node: properties(startNode(r)), rel: properties(r), target_node: properties(endNode(r))}) AS rows
        WITH rows, size(rows) AS total
        UNWIND rows[$offset..$end] AS row
        RETURN row.source_node AS source_node, row.rel AS rel, row.target_node AS target_node, total
        """
    elif safe_direction == "in":
        query = """
        MATCH (neighbor:KGNode {session_id: $session_id})-[r:KG_REL {session_id: $session_id}]->(center:KGNode {session_id: $session_id, uid: $uid})
        WITH r,
             CASE coalesce(r.relation, '')
               WHEN 'APPLIES_TO' THEN 1
               WHEN 'REQUIRES' THEN 2
               WHEN 'PERFORMED_BY' THEN 3
               WHEN 'HAS_RISK' THEN 4
               WHEN 'IF' THEN 5
               WHEN 'NEXT' THEN 6
               WHEN 'CONTAINS' THEN 9
               ELSE 50
             END AS rel_order
        ORDER BY rel_order ASC, coalesce(r.relation_label, '') ASC, coalesce(neighbor.label, '') ASC
        WITH collect({source_node: properties(startNode(r)), rel: properties(r), target_node: properties(endNode(r))}) AS rows
        WITH rows, size(rows) AS total
        UNWIND rows[$offset..$end] AS row
        RETURN row.source_node AS source_node, row.rel AS rel, row.target_node AS target_node, total
        """
    else:
        query = """
        MATCH (center:KGNode {session_id: $session_id, uid: $uid})-[r:KG_REL {session_id: $session_id}]-(neighbor:KGNode {session_id: $session_id})
        WITH r, neighbor,
             CASE coalesce(r.relation, '')
               WHEN 'APPLIES_TO' THEN 1
               WHEN 'REQUIRES' THEN 2
               WHEN 'PERFORMED_BY' THEN 3
               WHEN 'HAS_RISK' THEN 4
               WHEN 'IF' THEN 5
               WHEN 'NEXT' THEN 6
               WHEN 'CONTAINS' THEN 9
               ELSE 50
             END AS rel_order
        ORDER BY rel_order ASC, coalesce(r.relation_label, '') ASC, coalesce(neighbor.label, '') ASC
        WITH collect({source_node: properties(startNode(r)), rel: properties(r), target_node: properties(endNode(r))}) AS rows
        WITH rows, size(rows) AS total
        UNWIND rows[$offset..$end] AS row
        RETURN row.source_node AS source_node, row.rel AS rel, row.target_node AS target_node, total
        """

    records = _execute_read(
        query,
        session_id=sid,
        uid=target_uid,
        offset=safe_offset,
        end=safe_offset + safe_limit,
    )
    total_relations = int(records[0].get("total") or len(records)) if records else 0
    result = _finalize_graph_response(
        records,
        query=target_uid,
        center_uid=target_uid,
        matched_uids=[target_uid],
        limit=safe_limit,
        offset=safe_offset,
        total_relations=total_relations,
    )
    return _cache_set(cache_key, result)


# 把单条关系格式化为文本摘要。
def _relation_text(rel: Dict[str, object]) -> str:
    source = rel.get("source_ref") or "未知来源"
    condition = f"；条件：{rel.get('condition')}" if rel.get("condition") else ""
    return f"{rel['head_label']} -> {rel['relation_label']} -> {rel['tail_label']}（来源：{source}{condition}）"


# 根据问题和风险类型生成图谱关系摘要。
def summarize_related_graph(query: str, graph: Dict[str, object], risk_types: List[str] | None = None) -> Tuple[str, Dict[str, object]]:
    # 从图谱中检索与查询相关的三元组并生成文本摘要，供多智能体流程引用。
    if not config.KG_ENABLED:
        return "未启用知识图谱。", {"enabled": False, "matched_relations": [], "matched_nodes": []}
    relations = list(graph.get("relations", graph.get("links", [])))
    nodes = list(graph.get("nodes", []))
    if not relations and not nodes:
        return "无图谱命中。", {"enabled": True, "matched_relations": [], "matched_nodes": []}

    query_text = str(query or "")
    matched_relations = []
    for rel in relations:
        if any(token and token in query_text for token in [
            str(rel.get("head_label", "")),
            str(rel.get("tail_label", "")),
            str(rel.get("relation_label", "")),
            str(rel.get("condition", "")),
        ]):
            matched_relations.append(rel)

    if not matched_relations:
        matched_relations = relations[:config.KG_MAX_RELATED_TRIPLES]
    else:
        matched_relations = matched_relations[:config.KG_MAX_RELATED_TRIPLES]

    matched_uids = {str(rel.get("source")) for rel in matched_relations} | {str(rel.get("target")) for rel in matched_relations}
    matched_nodes = [node for node in nodes if str(node.get("uid")) in matched_uids]

    lines = ["知识图谱命中摘要："]
    for rel in matched_relations:
        lines.append(f"- {_relation_text(rel)}")
    summary = "\n".join(lines) if matched_relations else "无图谱命中。"
    return summary, {
        "enabled": True,
        "node_count": len(nodes),
        "relation_count": len(relations),
        "matched_nodes": matched_nodes,
        "matched_relations": matched_relations,
        "summary": summary,
    }
