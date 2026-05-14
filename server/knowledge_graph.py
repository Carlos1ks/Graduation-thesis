"""LLM triple extraction -> Neo4j graph storage and query helpers."""
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
from typing import Dict, List, Tuple

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
_GRAPH_BUILD_FUTURES: Dict[str, Future] = {}
_STATUS_DIR = Path(__file__).resolve().parent / ".graph_status"
_ARTICLE_SPLIT_PATTERN = re.compile(r"(?=第[一二三四五六七八九十百千万零两\d]+条)")
_ARTICLE_LABEL_PATTERN = re.compile(r"第[一二三四五六七八九十百千万零两\d]+条")
_GRAPH_QUERY_CACHE: Dict[str, Tuple[float, Dict[str, object]]] = {}
_GRAPH_QUERY_CACHE_LOCK = RLock()
_GRAPH_QUERY_CACHE_TTL_SECONDS = 60
_GRAPH_QUERY_CACHE_MAX_ITEMS = 256

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
}

RELATION_LABEL_OVERRIDES = {
    "CONTAINS": "包含",
    "NEXT": "下一步",
    "APPLIES_TO": "适用于",
    "REQUIRES": "需要",
    "PERFORMED_BY": "执行主体",
    "HAS_RISK": "存在风险",
    "IF": "条件",
}

RELATION_TYPE_MAP = {
    "CONTAINS": "CONTAINS",
    "NEXT": "NEXT",
    "APPLIES_TO": "APPLIES_TO",
    "REQUIRES": "REQUIRES",
    "PERFORMED_BY": "PERFORMED_BY",
    "HAS_RISK": "HAS_RISK",
    "IF": "IF",
}

RELATION_PRIORITY = {
    "APPLIES_TO": 1,
    "REQUIRES": 2,
    "PERFORMED_BY": 3,
    "HAS_RISK": 4,
    "IF": 5,
    "NEXT": 6,
    "CONTAINS": 9,
}

def _relation_label(rel_type: str) -> str:
    code = str(rel_type or "").strip()
    return RELATION_LABEL_OVERRIDES.get(code.upper()) or RELATION_LABELS.get(code) or RELATION_LABELS.get(code.lower()) or code


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=config.require_longcat_api_key(),
        base_url=config.LONGCAT_BASE_URL,
        model=config.LONGCAT_MODEL,
        temperature=0,
        max_tokens=config.LONGCAT_MAX_TOKENS,
        timeout=config.LONGCAT_READ_TIMEOUT,
    )


def _get_session_id(session_id: str | None) -> str:
    sid = str(session_id or "").strip()
    return sid or _DEFAULT_SESSION_ID


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^\w\u4e00-\u9fa5.-]+", "_", text)
    return text.strip("_")[:120] or "unknown"


def _node_uid(node_type: str, node_id: str) -> str:
    return f"{node_type}:{node_id}"


def _clip_text(text: str, limit: int = 220) -> str:
    content = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(content) <= limit:
        return content
    return f"{content[:limit]}..."


def _extract_article_label(text: str) -> str:
    match = _ARTICLE_LABEL_PATTERN.search(str(text or ""))
    return match.group(0) if match else ""


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


def _sanitize_node(node: Dict[str, object], doc_name: str, article_label: str, article_uid: str) -> Dict[str, object] | None:
    node_type = str(node.get("type") or "").strip().lower()
    if node_type not in ALLOWED_NODE_TYPES:
        return None
    node_id = str(node.get("id") or _safe_id(node.get("label") or "")).strip()
    label = str(node.get("label") or node_id).strip()
    if not node_id or not label:
        return None
    return {
        "uid": _node_uid(node_type, node_id),
        "type": node_type,
        "type_label": NODE_TYPE_LABELS.get(node_type, node_type),
        "id": node_id,
        "label": label,
        "doc_name": doc_name,
        "article_label": article_label,
        "sources": [f"{doc_name} · {article_label}"],
        "article_uid": article_uid,
    }


def _sanitize_relation(
    rel: Dict[str, object],
    nodes_by_uid: Dict[str, Dict[str, object]],
    doc_name: str,
    article_label: str,
) -> Dict[str, object] | None:
    rel_type = str(rel.get("type") or "").strip().upper()
    if rel_type not in ALLOWED_RELATIONS:
        return None
    source_type = str(rel.get("source_type") or "").strip().lower()
    target_type = str(rel.get("target_type") or "").strip().lower()
    source_id = str(rel.get("source_id") or "").strip()
    target_id = str(rel.get("target_id") or "").strip()
    if not source_type or not target_type or not source_id or not target_id:
        return None
    source_uid = _node_uid(source_type, source_id)
    target_uid = _node_uid(target_type, target_id)
    if source_uid not in nodes_by_uid or target_uid not in nodes_by_uid:
        return None
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


def _build_graph_documents(documents: List[Dict[str, object]]) -> Dict[str, object]:
    normalized_documents = _normalize_documents(documents)
    nodes_by_uid: Dict[str, Dict[str, object]] = {}
    relations_by_id: Dict[str, Dict[str, object]] = {}
    article_budget = max(1, int(config.KG_MAX_ARTICLES_PER_BUILD))
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

        articles = _split_articles(str(doc["text"]), str(doc["chunk_id"]))
        batch_size = max(1, int(config.KG_LLM_BATCH_SIZE))
        for start in range(0, len(articles), batch_size):
            for article in articles[start:start + batch_size]:
                if article_count >= article_budget:
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
                    nodes_by_uid.setdefault(clean["uid"], clean)

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
            if article_count >= article_budget:
                break
        if article_count >= article_budget:
            break

    nodes = list(nodes_by_uid.values())
    relations = list(relations_by_id.values())
    type_counter = Counter(str(node.get("type")) for node in nodes)
    relation_counter = Counter(str(rel.get("relation")) for rel in relations)
    return {
        "nodes": nodes,
        "relations": relations,
        "links": relations,
        "document_summaries": [],
        "stats": {
            "node_count": len(nodes),
            "relation_count": len(relations),
            "node_types": dict(type_counter),
            "relation_types": dict(relation_counter),
            "updated_at": _now_iso(),
        },
    }


def _build_graph_documents_with_progress(documents: List[Dict[str, object]], session_id: str) -> Dict[str, object]:
    normalized_documents = _normalize_documents(documents)
    nodes_by_uid: Dict[str, Dict[str, object]] = {}
    relations_by_id: Dict[str, Dict[str, object]] = {}
    article_budget = max(1, int(config.KG_MAX_ARTICLES_PER_BUILD))
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
            if len(articles_to_process) >= article_budget:
                break
        if len(articles_to_process) >= article_budget:
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
            nodes_by_uid.setdefault(clean["uid"], clean)

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

    nodes = list(nodes_by_uid.values())
    relations = list(relations_by_id.values())
    type_counter = Counter(str(node.get("type")) for node in nodes)
    relation_counter = Counter(str(rel.get("relation")) for rel in relations)
    return {
        "nodes": nodes,
        "relations": relations,
        "links": relations,
        "document_summaries": [],
        "stats": {
            "node_count": len(nodes),
            "relation_count": len(relations),
            "node_types": dict(type_counter),
            "relation_types": dict(relation_counter),
            "updated_at": _now_iso(),
        },
    }


def _get_driver():
    global _DRIVER
    with _DRIVER_LOCK:
        if _DRIVER is None:
            uri, username, password, _ = config.require_neo4j_credentials()
            _DRIVER = GraphDatabase.driver(uri, auth=(username, password))
        return _DRIVER


def close_driver() -> None:
    global _DRIVER
    with _DRIVER_LOCK:
        if _DRIVER is not None:
            _DRIVER.close()
            _DRIVER = None


def _execute_write(query: str, **params):
    driver = _get_driver()
    _, _, _, database = config.require_neo4j_credentials()
    with driver.session(database=database) as session:
        return session.execute_write(lambda tx: list(tx.run(query, **params)))


def _execute_read(query: str, **params):
    driver = _get_driver()
    _, _, _, database = config.require_neo4j_credentials()
    with driver.session(database=database) as session:
        return session.execute_read(lambda tx: [record.data() for record in tx.run(query, **params)])


def _ensure_schema() -> None:
    _execute_write("CREATE CONSTRAINT session_uid IF NOT EXISTS FOR (n:KGNode) REQUIRE (n.session_id, n.uid) IS UNIQUE")


def _clear_session_graph_neo4j(session_id: str) -> None:
    _execute_write(
        """
        MATCH (n:KGNode {session_id: $session_id})
        DETACH DELETE n
        """,
        session_id=session_id,
    )


def _write_graph_to_neo4j(session_id: str, graph: Dict[str, object]) -> None:
    _ensure_schema()
    _clear_session_graph_neo4j(session_id)
    _upsert_graph_to_neo4j(session_id, graph)


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
            "doc_name": node.get("doc_name"),
            "article_label": node.get("article_label"),
            "text_excerpt": node.get("text_excerpt"),
            "keywords": node.get("keywords") or [],
            "sources": node.get("sources") or [],
        })

    rel_rows = []
    for rel in graph.get("relations", []):
        rel_rows.append({
            "session_id": session_id,
            "id": rel.get("id"),
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

    nodes = list(node_map.values())
    relations = list(rel_map.values())
    type_counter = Counter(str(node.get("type")) for node in nodes)
    relation_counter = Counter(str(rel.get("relation")) for rel in relations)
    return {
        "nodes": nodes,
        "relations": relations,
        "links": relations,
        "document_summaries": [],
        "stats": {
            "node_count": len(nodes),
            "relation_count": len(relations),
            "node_types": dict(type_counter),
            "relation_types": dict(relation_counter),
            "updated_at": _now_iso(),
        },
    }


def _stats_for_session(session_id: str) -> Dict[str, object]:
    stats = _execute_read(
        """
        MATCH (n:KGNode {session_id: $session_id})
        OPTIONAL MATCH ()-[r:KG_REL {session_id: $session_id}]->()
        RETURN count(DISTINCT n) AS node_count, count(DISTINCT r) AS relation_count
        """,
        session_id=session_id,
    )
    return stats[0] if stats else {"node_count": 0, "relation_count": 0}


def _status_file(session_id: str) -> Path:
    _STATUS_DIR.mkdir(parents=True, exist_ok=True)
    return _STATUS_DIR / f"{_safe_id(session_id)}.json"


def _write_status_file(session_id: str, status: Dict[str, object]) -> None:
    path = _status_file(session_id)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_status_file(session_id: str) -> Dict[str, object] | None:
    path = _status_file(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


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


def get_graph_build_status(session_id: str | None) -> Dict[str, object]:
    sid = _get_session_id(session_id)
    with _TASK_LOCK:
        memory_status = _GRAPH_BUILD_STATUS.get(sid)
    file_status = _read_status_file(sid)
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
    if status["state"] == "completed" and config.NEO4J_ENABLED:
        stats = _stats_for_session(sid)
        status["node_count"] = int(stats.get("node_count") or 0)
        status["relation_count"] = int(stats.get("relation_count") or 0)
        _write_status_file(sid, status)
    return status


def build_knowledge_graph(documents: List[Dict[str, object]]) -> Dict[str, object]:
    return _build_graph_documents(documents) if config.KG_ENABLED else {
        "nodes": [], "relations": [], "links": [], "document_summaries": [], "stats": {}
    }


def build_and_store_session_graph(session_id: str | None, documents: List[Dict[str, object]]) -> Dict[str, object]:
    sid = _get_session_id(session_id)
    graph = build_knowledge_graph(documents)
    if config.NEO4J_ENABLED:
        _write_graph_to_neo4j(sid, graph)
    return graph


def start_graph_build(session_id: str | None, documents: List[Dict[str, object]]) -> Dict[str, object]:
    sid = _get_session_id(session_id)
    current = get_graph_build_status(sid)
    if current.get("state") in {"running", "queued"}:
        return current

    normalized_documents = _normalize_documents(documents)
    article_budget = max(1, int(config.KG_MAX_ARTICLES_PER_BUILD))
    total_articles = 0
    for doc in normalized_documents:
        articles = _split_articles(str(doc["text"]), str(doc["chunk_id"]))
        total_articles += len(articles)
        if total_articles >= article_budget:
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


def _normalize_relation(rel: Dict[str, object]) -> Dict[str, object]:
    normalized = dict(rel)
    relation = str(normalized.get("relation") or "").strip()
    normalized["relation"] = relation
    normalized["relation_label"] = _relation_label(normalized.get("relation_label") or relation)
    return normalized


def _normalize_node(node: Dict[str, object]) -> Dict[str, object]:
    normalized = dict(node)
    node_type = str(normalized.get("type") or "").strip()
    if node_type and not normalized.get("type_label"):
        normalized["type_label"] = NODE_TYPE_LABELS.get(node_type, node_type)
    return normalized


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


def _relation_priority(relation: str) -> int:
    return RELATION_PRIORITY.get(str(relation or "").upper(), 50)


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
    graph["nodes"] = [_normalize_node(node) for node in graph.get("nodes", [])]
    graph["relations"] = [_normalize_relation(rel) for rel in graph.get("relations", [])]
    graph["links"] = graph["relations"]
    relation_count = len(graph["relations"])
    total = total_relations if total_relations is not None else relation_count
    graph["stats"] = stats or {"node_count": len(graph["nodes"]), "relation_count": relation_count}
    graph["query"] = query
    graph["center_uid"] = center_uid
    graph["matched_uids"] = matched_uids or ([center_uid] if center_uid else [])
    graph["limit"] = limit
    graph["offset"] = offset
    graph["returned_relation_count"] = relation_count
    graph["total_relation_count"] = total
    graph["has_more"] = offset + relation_count < total
    graph["truncated"] = graph["has_more"] or relation_count >= limit
    graph["from_cache"] = False
    return graph


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
            nodes[str(node["uid"])] = dict(node)
        if rel:
            relations[str(rel["id"])] = dict(rel)
    return {"nodes": list(nodes.values()), "relations": list(relations.values()), "links": list(relations.values())}


def get_session_graph(session_id: str | None) -> Dict[str, object]:
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


def clear_session_graph(session_id: str | None) -> bool:
    sid = _get_session_id(session_id)
    if not config.NEO4J_ENABLED:
        return False
    _clear_session_graph_neo4j(sid)
    return True


def _strip_support_nodes(nodes: List[Dict[str, object]], relations: List[Dict[str, object]]) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    visible_nodes = [node for node in nodes if str(node.get("type")) in _VISIBLE_NODE_TYPES]
    visible_uids = {str(node.get("uid")) for node in visible_nodes}
    visible_relations = [
        rel for rel in relations
        if str(rel.get("source")) in visible_uids and str(rel.get("target")) in visible_uids
    ]
    return visible_nodes, visible_relations


def _detect_topic(keyword: str) -> Dict[str, object] | None:
    text = str(keyword or "").strip()
    if not text:
        return None
    for rule in _TOPIC_RULES.values():
        if any(token in text for token in rule["tokens"]):
            return rule
    return None


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


def query_graph(graph: Dict[str, object], keyword: str = "", limit: int = 80) -> Dict[str, object]:
    nodes = list(graph.get("nodes", []))
    relations = list(graph.get("relations", graph.get("links", [])))
    keyword_text = str(keyword or "").strip()
    limit = max(10, int(limit or 80))
    visible_nodes, visible_relations = _strip_support_nodes(nodes, relations)

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

    return {
        "nodes": filtered_nodes,
        "relations": filtered_relations,
        "links": filtered_relations,
        "stats": graph.get("stats", {}),
        "query": keyword_text,
    }


def query_centered_graph(session_id: str | None, keyword: str = "", limit: int = 80, depth: int = 1) -> Dict[str, object]:
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
            WITH n,
                 CASE
                   WHEN toLower(coalesce(n.label, '')) = toLower($keyword) THEN 0
                   WHEN toLower(coalesce(n.id, '')) = toLower($keyword) THEN 1
                   WHEN toLower(coalesce(n.label, '')) CONTAINS toLower($keyword) THEN 2
                   WHEN toLower(coalesce(n.id, '')) CONTAINS toLower($keyword) THEN 3
                   WHEN toLower(coalesce(n.type_label, '')) CONTAINS toLower($keyword) THEN 4
                   WHEN any(source IN coalesce(n.sources, []) WHERE toLower(toString(source)) CONTAINS toLower($keyword)) THEN 5
                   ELSE 99
                 END AS score
            WHERE score < 99
            RETURN n.uid AS uid, score
            ORDER BY score ASC, size(coalesce(n.label, '')) ASC
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
                WHERE toLower(coalesce(r.head_label, '')) CONTAINS toLower($keyword)
                   OR toLower(coalesce(r.tail_label, '')) CONTAINS toLower($keyword)
                   OR toLower(coalesce(r.relation_label, '')) CONTAINS toLower($keyword)
                   OR toLower(coalesce(r.condition, '')) CONTAINS toLower($keyword)
                   OR toLower(coalesce(r.evidence, '')) CONTAINS toLower($keyword)
                RETURN a.uid AS source_uid, b.uid AS target_uid
                LIMIT 6
                """,
                session_id=sid,
                keyword=keyword_text,
            )
            matched_uids = []
            for row in center_rows:
                if row.get("source_uid"):
                    matched_uids.append(str(row["source_uid"]))
                if row.get("target_uid"):
                    matched_uids.append(str(row["target_uid"]))
            matched_uids = list(dict.fromkeys(matched_uids))[:6]
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
    return _cache_set(cache_key, result)


def expand_graph_neighbors(session_id: str | None, node_uid: str, limit: int = 60, offset: int = 0, direction: str = "both") -> Dict[str, object]:
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


def _relation_text(rel: Dict[str, object]) -> str:
    source = rel.get("source_ref") or "未知来源"
    condition = f"；条件：{rel.get('condition')}" if rel.get("condition") else ""
    return f"{rel['head_label']} -> {rel['relation_label']} -> {rel['tail_label']}（来源：{source}{condition}）"


def summarize_related_graph(query: str, graph: Dict[str, object], risk_types: List[str] | None = None) -> Tuple[str, Dict[str, object]]:
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
