"""煤矿应急知识图谱构建、检索与会话级存储。"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from threading import RLock
from typing import Dict, List, Tuple

from config import config
from domain_schema import ENTITY_GROUPS, RELATION_LABELS


_DEFAULT_SESSION_ID = "default"
_SESSION_GRAPHS: Dict[str, Dict[str, object]] = {}
_GRAPH_LOCK = RLock()
_ARTICLE_LABEL_PATTERN = re.compile(r"第[一二三四五六七八九十百千万零两\d]+条")
_NUMERIC_PARAMETER_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|％|m|米|℃|度|小时|h|min|分钟)"
)

_TOPIC_RULES = {
    "gas": {
        "tokens": ["瓦斯", "甲烷", "超限", "瓦斯浓度"],
        "hazard_ids": {"gas"},
        "parameter_units": {"%", "％"},
        "parameter_tokens": ["瓦斯", "甲烷", "浓度", "超限"],
    },
    "fire": {
        "tokens": ["火灾", "明火", "火源", "烟雾", "燃烧"],
        "hazard_ids": {"fire"},
        "parameter_units": {"℃", "度", "%", "％"},
        "parameter_tokens": ["温度", "高温", "火", "氧气", "浓度"],
    },
    "water": {
        "tokens": ["水害", "突水", "透水", "涌水", "水位", "积水"],
        "hazard_ids": {"water"},
        "parameter_units": {"m", "米"},
        "parameter_tokens": ["水位", "涌水", "积水", "水量", "深度"],
    },
}

_DIRECT_TOPIC_RELATIONS = {
    "indicates",
    "requires_action",
    "triggers_hazard",
    "monitors",
    "occurs_at",
    "responsible_for",
    "in_stage",
    "supports_action",
    "governed_by",
    "related_to",
}


NODE_TYPE_LABELS = {
    "document": "文档",
    "clause": "条款",
    "document_type": "文档类型",
    "hazard": "风险类型",
    "symptom": "触发信号",
    "parameter": "参数阈值",
    "sensor": "监测设备",
    "action": "处置动作",
    "department": "责任部门",
    "location": "地点场景",
    "equipment": "设备设施",
    "stage": "处置阶段",
}

LAYER_BY_TYPE = {
    "sensor": "perception",
    "symptom": "perception",
    "parameter": "logic",
    "hazard": "logic",
    "action": "action",
    "department": "action",
    "location": "action",
    "equipment": "action",
}


def _get_session_id(session_id: str | None) -> str:
    sid = str(session_id or "").strip()
    return sid or _DEFAULT_SESSION_ID


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip_text(text: str, limit: int = 220) -> str:
    content = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(content) <= limit:
        return content
    return f"{content[:limit]}..."


def _node_uid(node_type: str, node_id: str) -> str:
    return f"{node_type}:{node_id}"


def _safe_id(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^\w\u4e00-\u9fa5.-]+", "_", text)
    return text.strip("_")[:80] or "unknown"


def _extract_article_label(text: str) -> str:
    match = _ARTICLE_LABEL_PATTERN.search(str(text or ""))
    return match.group(0) if match else ""


def _split_graph_segments(text: str, fallback_id: str) -> List[Dict[str, str]]:
    content = str(text or "").strip()
    if not content:
        return []

    matches = list(_ARTICLE_LABEL_PATTERN.finditer(content))
    if len(matches) >= 2:
        segments = []
        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
            segment_text = content[start:end].strip()
            if not segment_text:
                continue
            label = match.group(0)
            segments.append({
                "segment_id": f"{fallback_id}-{idx + 1:03d}",
                "article_label": label,
                "label": label,
                "text": segment_text,
            })
        return segments

    sentences = [item.strip() for item in re.split(r"(?<=[。；;!?！？])", content) if item.strip()]
    if len(sentences) <= 1:
        article_label = _extract_article_label(content)
        return [{
            "segment_id": fallback_id,
            "article_label": article_label,
            "label": article_label or fallback_id,
            "text": content,
        }]

    segments = []
    article_label = _extract_article_label(content)
    for idx, sentence in enumerate(sentences, start=1):
        segments.append({
            "segment_id": f"{fallback_id}-s{idx:02d}",
            "article_label": _extract_article_label(sentence) or article_label,
            "label": _extract_article_label(sentence) or article_label or f"{fallback_id}-句{idx}",
            "text": sentence,
        })
    return segments


def _match_entities(text: str) -> List[Dict[str, str]]:
    content = str(text or "")
    matched: List[Dict[str, str]] = []
    seen = set()
    for entity_type, definitions in ENTITY_GROUPS.items():
        for entity_id, definition in definitions.items():
            keywords = definition.get("keywords") or []
            hit_keywords = [keyword for keyword in keywords if keyword and keyword in content]
            if not hit_keywords:
                continue
            key = (entity_type, entity_id)
            if key in seen:
                continue
            seen.add(key)
            matched.append({
                "uid": _node_uid(entity_type, entity_id),
                "type": entity_type,
                "id": entity_id,
                "label": definition["label"],
                "keywords": hit_keywords[:4],
            })
    return matched


def _parameter_context_key(value: str, unit: str, context: str, close_context: str = "") -> Dict[str, str]:
    raw_value = f"{value}{unit}"
    context_text = str(context or "")
    close_text = str(close_context or "")
    if unit in {"%", "％"}:
        if any(token in context_text for token in ["瓦斯", "甲烷"]):
            return {"id": "gas_concentration", "label": "瓦斯浓度", "condition": f">= {raw_value}"}
        if "氧气" in context_text:
            return {"id": "oxygen_concentration", "label": "氧气浓度", "condition": f">= {raw_value}"}
        if any(token in context_text for token in ["粉尘", "煤尘"]):
            return {"id": "dust_concentration", "label": "粉尘浓度", "condition": f">= {raw_value}"}
        if "浓度" in context_text:
            return {"id": "concentration", "label": "浓度阈值", "condition": f">= {raw_value}"}
        return {"id": "percentage_parameter", "label": "百分比阈值", "condition": f">= {raw_value}"}
    if unit in {"℃", "度"}:
        return {"id": "temperature", "label": "温度", "condition": f">= {raw_value}"}
    if unit in {"小时", "h", "min", "分钟"}:
        return {"id": "response_time", "label": "处置时间", "condition": f"<= {raw_value}"}
    if unit in {"m", "米"}:
        if any(token in close_text for token in ["距离", "范围", "以内", "以外", "附近", "半径"]):
            return {"id": "distance", "label": "距离", "condition": f"<= {raw_value}"}
        if any(token in close_text for token in ["水位", "积水", "涌水", "水深"]):
            return {"id": "water_level", "label": "水位", "condition": f">= {raw_value}"}
        if any(token in context_text for token in ["距离", "范围", "以内", "以外", "附近", "半径"]):
            return {"id": "distance", "label": "距离", "condition": f"<= {raw_value}"}
        if any(token in context_text for token in ["水位", "积水", "涌水", "水深"]):
            return {"id": "water_level", "label": "水位", "condition": f">= {raw_value}"}
        return {"id": "distance", "label": "距离", "condition": f"<= {raw_value}"}
    return {"id": "generic_parameter", "label": "参数条件", "condition": raw_value}


def _extract_numeric_parameters(text: str) -> List[Dict[str, object]]:
    content = str(text or "")
    parameters: List[Dict[str, object]] = []
    seen = set()
    for match in _NUMERIC_PARAMETER_PATTERN.finditer(content):
        value = match.group("value")
        unit = match.group("unit")
        context = content[max(0, match.start() - 24): min(len(content), match.end() + 24)]
        close_context = content[max(0, match.start() - 8): min(len(content), match.end() + 8)]
        parameter = _parameter_context_key(value, unit, context, close_context)
        node_id = str(parameter["id"])
        condition = str(parameter["condition"])
        dedupe_key = (node_id, condition)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        parameters.append({
            "type": "parameter",
            "id": node_id,
            "label": str(parameter["label"]),
            "value": value,
            "unit": unit,
            "condition": condition,
            "keywords": [f"{value}{unit}", str(parameter["label"]), condition],
        })
    return parameters


def _merge_entity_nodes(entity_nodes: List[Dict[str, object]]) -> List[Dict[str, object]]:
    merged: List[Dict[str, object]] = []
    seen_keys = set()
    for entity in entity_nodes:
        node_type = str(entity.get("type") or "")
        label = str(entity.get("label") or "")
        value = str(entity.get("value") or "")
        unit = str(entity.get("unit") or "")
        condition = str(entity.get("condition") or "")
        dedupe_key = (node_type, label, condition) if label else (node_type, value, unit, condition)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        merged.append(entity)
    return merged


def _make_node(node_type: str, node_id: str, label: str, **extra) -> Dict[str, object]:
    return {
        "uid": _node_uid(node_type, node_id),
        "type": node_type,
        "type_label": NODE_TYPE_LABELS.get(node_type, node_type),
        "layer": LAYER_BY_TYPE.get(node_type, "support"),
        "id": node_id,
        "label": label,
        **{k: v for k, v in extra.items() if v not in (None, "", [])},
    }


def _make_relation(
    head: Dict[str, object],
    relation: str,
    tail: Dict[str, object],
    source: str,
    **extra,
) -> Dict[str, object]:
    head_uid = str(head.get("uid") or _node_uid(str(head["type"]), str(head["id"])))
    tail_uid = str(tail.get("uid") or _node_uid(str(tail["type"]), str(tail["id"])))
    relation_id = f"{head_uid}|{relation}|{tail_uid}|{_safe_id(source)}"
    return {
        "id": relation_id,
        "source": head_uid,
        "target": tail_uid,
        "head_type": head["type"],
        "head_id": head["id"],
        "head_label": head["label"],
        "relation": relation,
        "relation_label": RELATION_LABELS.get(relation, relation),
        "tail_type": tail["type"],
        "tail_id": tail["id"],
        "tail_label": tail["label"],
        "source_ref": source,
        **{k: v for k, v in extra.items() if v not in (None, "", [])},
    }


def _add_node(nodes_by_uid: Dict[str, Dict[str, object]], node: Dict[str, object]) -> Dict[str, object]:
    uid = str(node["uid"])
    if uid not in nodes_by_uid:
        nodes_by_uid[uid] = dict(node)
        nodes_by_uid[uid].setdefault("sources", [])
        return nodes_by_uid[uid]

    existing = nodes_by_uid[uid]
    for key, value in node.items():
        if key == "sources":
            continue
        if key not in existing or existing[key] in (None, "", []):
            existing[key] = value
    return existing


def _add_source(node: Dict[str, object], source: str) -> None:
    source = str(source or "").strip()
    if not source:
        return
    sources = node.setdefault("sources", [])
    if isinstance(sources, list) and source not in sources:
        sources.append(source)


def _group_nodes(nodes: List[Dict[str, object]]) -> Dict[str, List[Dict[str, object]]]:
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for node in nodes:
        grouped.setdefault(str(node.get("type")), []).append(node)
    return grouped


def _relations_for_clause(
    clause_node: Dict[str, object],
    doc_node: Dict[str, object],
    entity_nodes: List[Dict[str, object]],
    source: str,
) -> List[Dict[str, object]]:
    relations: List[Dict[str, object]] = [
        _make_relation(doc_node, "contains_clause", clause_node, source),
    ]

    grouped = _group_nodes(entity_nodes)
    parameter_conditions = sorted({
        str(item.get("condition"))
        for item in grouped.get("parameter", [])
        if item.get("condition")
    })
    combined_condition = "；".join(parameter_conditions) if parameter_conditions else None
    for entity in entity_nodes:
        relations.append(_make_relation(clause_node, "mentions", entity, source))

    for symptom in grouped.get("symptom", []):
        for hazard in grouped.get("hazard", []):
            relations.append(_make_relation(symptom, "indicates", hazard, source))

    for parameter in grouped.get("parameter", []):
        relations.append(_make_relation(clause_node, "has_parameter", parameter, source))
        for hazard in grouped.get("hazard", []):
            relations.append(
                _make_relation(
                    parameter,
                    "triggers_hazard",
                    hazard,
                    source,
                    condition=parameter.get("condition"),
                )
            )

    for sensor in grouped.get("sensor", []):
        for parameter in grouped.get("parameter", []):
            relations.append(
                _make_relation(
                    sensor,
                    "monitors",
                    parameter,
                    source,
                    condition=parameter.get("condition"),
                )
            )
        for symptom in grouped.get("symptom", []):
            relations.append(_make_relation(sensor, "monitors", symptom, source, condition=combined_condition))

    for hazard in grouped.get("hazard", []):
        for action in grouped.get("action", []):
            relations.append(_make_relation(hazard, "requires_action", action, source, condition=combined_condition))
        for location in grouped.get("location", []):
            relations.append(_make_relation(hazard, "occurs_at", location, source))
        for document_type in grouped.get("document_type", []):
            relations.append(_make_relation(hazard, "governed_by", document_type, source))

    for action in grouped.get("action", []):
        for department in grouped.get("department", []):
            relations.append(_make_relation(action, "responsible_for", department, source))
        for stage in grouped.get("stage", []):
            relations.append(_make_relation(action, "in_stage", stage, source))
        for equipment in grouped.get("equipment", []):
            relations.append(_make_relation(equipment, "supports_action", action, source))

    for location in grouped.get("location", []):
        for equipment in grouped.get("equipment", []):
            relations.append(_make_relation(equipment, "related_to", location, source))

    return relations


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
        doc_name = str(item.get("doc_name") or item.get("file_name") or item.get("docName") or "未命名文档").strip()
        chunk_id = str(item.get("chunk_id") or item.get("chunkId") or f"chunk-{idx + 1:03d}").strip()
        normalized.append({
            **item,
            "doc_name": doc_name or "未命名文档",
            "chunk_id": chunk_id,
            "text": text,
            "article_label": str(item.get("article_label") or _extract_article_label(text) or "").strip(),
        })
    return normalized


def build_knowledge_graph(documents: List[Dict[str, object]]) -> Dict[str, object]:
    if not config.KG_ENABLED:
        return {
            "nodes": [],
            "relations": [],
            "links": [],
            "document_summaries": [],
            "stats": {},
        }

    normalized_documents = _normalize_documents(documents)
    nodes_by_uid: Dict[str, Dict[str, object]] = {}
    relations_by_id: Dict[str, Dict[str, object]] = {}
    document_summaries: List[Dict[str, object]] = []

    for doc_index, doc in enumerate(normalized_documents, start=1):
        doc_name = str(doc["doc_name"])
        document_id = str(doc.get("document_id") or _safe_id(doc_name))
        doc_node = _add_node(
            nodes_by_uid,
            _make_node("document", document_id, doc_name, doc_name=doc_name),
        )

        chunk_id = str(doc["chunk_id"])
        base_article_label = str(doc.get("article_label") or _extract_article_label(str(doc["text"])) or "")
        segments = _split_graph_segments(str(doc["text"]), chunk_id) or [{
            "segment_id": chunk_id,
            "article_label": base_article_label,
            "label": base_article_label or chunk_id or f"片段{doc_index}",
            "text": str(doc["text"]),
        }]

        doc_node_total = 1
        doc_relation_total = 0
        for segment in segments:
            segment_id = str(segment.get("segment_id") or chunk_id)
            article_label = str(segment.get("article_label") or base_article_label or "")
            segment_text = str(segment.get("text") or "")
            clause_id = f"{document_id}:{_safe_id(segment_id)}"
            clause_label = str(segment.get("label") or article_label or segment_id)
            source = f"{doc_name} · {segment_id}"
            clause_node = _add_node(
                nodes_by_uid,
                _make_node(
                    "clause",
                    clause_id,
                    clause_label,
                    doc_name=doc_name,
                    chunk_id=segment_id,
                    article_label=article_label,
                    text_excerpt=_clip_text(segment_text, 260),
                ),
            )
            _add_source(doc_node, source)
            _add_source(clause_node, source)

            entity_nodes = _merge_entity_nodes(
                _match_entities(segment_text) + _extract_numeric_parameters(segment_text)
            )
            normalized_entities: List[Dict[str, object]] = []
            for entity in entity_nodes:
                node = _add_node(
                    nodes_by_uid,
                    _make_node(
                        str(entity["type"]),
                        str(entity["id"]),
                        str(entity["label"]),
                        keywords=entity.get("keywords"),
                        value=entity.get("value"),
                        unit=entity.get("unit"),
                    ),
                )
                _add_source(node, source)
                normalized_entities.append(node)

            segment_relations = _relations_for_clause(clause_node, doc_node, normalized_entities, source)
            for relation in segment_relations:
                relations_by_id.setdefault(str(relation["id"]), relation)

            doc_node_total += len(normalized_entities) + 1
            doc_relation_total += len(segment_relations)

        document_summaries.append({
            "doc_name": doc_name,
            "chunk_id": chunk_id,
            "article_label": base_article_label,
            "node_count": doc_node_total,
            "relation_count": doc_relation_total,
        })

    nodes = list(nodes_by_uid.values())
    relations = list(relations_by_id.values())
    type_counter = Counter(str(node.get("type")) for node in nodes)
    relation_counter = Counter(str(rel.get("relation")) for rel in relations)

    return {
        "nodes": nodes,
        "relations": relations,
        "links": relations,
        "document_summaries": document_summaries,
        "stats": {
            "node_count": len(nodes),
            "relation_count": len(relations),
            "node_types": dict(type_counter),
            "relation_types": dict(relation_counter),
            "updated_at": _now_iso(),
        },
    }


def build_and_store_session_graph(session_id: str | None, documents: List[Dict[str, object]]) -> Dict[str, object]:
    graph = build_knowledge_graph(documents)
    sid = _get_session_id(session_id)
    with _GRAPH_LOCK:
        _SESSION_GRAPHS[sid] = graph
    return graph


def get_session_graph(session_id: str | None) -> Dict[str, object]:
    sid = _get_session_id(session_id)
    with _GRAPH_LOCK:
        graph = _SESSION_GRAPHS.get(sid)
        if graph is None:
            return {
                "nodes": [],
                "relations": [],
                "links": [],
                "document_summaries": [],
                "stats": {"node_count": 0, "relation_count": 0},
            }
        return graph


def clear_session_graph(session_id: str | None) -> bool:
    sid = _get_session_id(session_id)
    with _GRAPH_LOCK:
        return _SESSION_GRAPHS.pop(sid, None) is not None


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
    sources = node.get("sources", []) if isinstance(node.get("sources"), list) else []
    keywords = node.get("keywords", []) if isinstance(node.get("keywords"), list) else []
    fields = [
        str(node.get("label", "")),
        str(node.get("id", "")),
        str(node.get("type_label", "")),
        " ".join(map(str, keywords)),
        " ".join(map(str, sources)),
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
    ]
    return any(text in field for field in fields)


def _topic_context_matches(node: Dict[str, object], rule: Dict[str, object]) -> bool:
    tokens = list(rule.get("tokens") or [])
    parameter_tokens = list(rule.get("parameter_tokens") or tokens)
    sources = node.get("sources", []) if isinstance(node.get("sources"), list) else []
    keywords = node.get("keywords", []) if isinstance(node.get("keywords"), list) else []
    context = " ".join([
        str(node.get("label", "")),
        str(node.get("id", "")),
        " ".join(map(str, keywords)),
        " ".join(map(str, sources)),
    ])
    if str(node.get("type")) == "parameter":
        unit = str(node.get("unit", ""))
        if unit and unit not in set(rule.get("parameter_units") or []):
            return False
        return any(token in context for token in parameter_tokens)
    return any(token in context for token in tokens)


def _relation_is_topic_consistent(rel: Dict[str, object], rule: Dict[str, object]) -> bool:
    hazard_ids = set(rule.get("hazard_ids") or [])
    parameter_units = set(rule.get("parameter_units") or [])
    parameter_tokens = list(rule.get("parameter_tokens") or rule.get("tokens") or [])
    endpoints = [
        (str(rel.get("head_type", "")), str(rel.get("head_id", "")), str(rel.get("head_label", ""))),
        (str(rel.get("tail_type", "")), str(rel.get("tail_id", "")), str(rel.get("tail_label", ""))),
    ]
    for endpoint_type, endpoint_id, _ in endpoints:
        if endpoint_type == "hazard" and endpoint_id and endpoint_id not in hazard_ids:
            return False
    for endpoint_type, _, endpoint_label in endpoints:
        if endpoint_type == "parameter":
            unit_ok = not parameter_units or any(unit in endpoint_label for unit in parameter_units)
            token_ok = any(token in endpoint_label for token in parameter_tokens)
            if not (unit_ok and token_ok):
                return False
    return True


def _topic_seed_uids(nodes: List[Dict[str, object]], keyword: str, rule: Dict[str, object]) -> set[str]:
    seeds = set()
    hazard_ids = set(rule.get("hazard_ids") or [])
    for node in nodes:
        uid = str(node.get("uid"))
        node_type = str(node.get("type", ""))
        if node_type == "hazard" and node.get("id") in hazard_ids:
            seeds.add(uid)
            continue
        if node_type in {"symptom", "sensor", "parameter", "action", "location", "equipment"}:
            if _topic_context_matches(node, rule):
                seeds.add(uid)
                continue
        if _node_matches_keyword(node, keyword):
            seeds.add(uid)
    return seeds


def _rank_topic_nodes(nodes: List[Dict[str, object]], keyword: str, seed_uids: set[str]) -> List[Dict[str, object]]:
    priority = {
        "hazard": 0,
        "symptom": 1,
        "parameter": 2,
        "sensor": 3,
        "action": 4,
        "department": 5,
        "location": 6,
        "equipment": 7,
        "stage": 8,
        "clause": 9,
        "document_type": 10,
        "document": 11,
    }
    return sorted(
        nodes,
        key=lambda node: (
            0 if str(node.get("uid")) in seed_uids else 1,
            priority.get(str(node.get("type")), 99),
            0 if _node_matches_keyword(node, keyword) else 1,
            str(node.get("label", "")),
        ),
    )


def _compact_topic_subgraph(
    nodes: List[Dict[str, object]],
    relations: List[Dict[str, object]],
    keyword: str,
    rule: Dict[str, object],
    limit: int,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    nodes_by_uid = {str(node.get("uid")): node for node in nodes}
    seed_uids = _topic_seed_uids(nodes, keyword, rule)
    if not seed_uids:
        seed_uids = {
            str(node.get("uid"))
            for node in nodes
            if _node_matches_keyword(node, keyword)
        }

    kept_relations: List[Dict[str, object]] = []
    kept_uids = set(seed_uids)

    for rel in relations:
        source = str(rel.get("source"))
        target = str(rel.get("target"))
        relation_type = str(rel.get("relation"))
        if source not in seed_uids and target not in seed_uids:
            continue
        if relation_type not in _DIRECT_TOPIC_RELATIONS:
            continue
        if not _relation_is_topic_consistent(rel, rule):
            continue

        other_uid = target if source in seed_uids else source
        other_node = nodes_by_uid.get(other_uid)
        if other_node and str(other_node.get("type")) == "parameter" and not _topic_context_matches(other_node, rule):
            continue
        if other_node and str(other_node.get("type")) in {"action", "department", "location", "equipment", "stage", "clause"}:
            if not _relation_matches_keyword(rel, keyword) and not _topic_context_matches(other_node, rule):
                continue

        kept_relations.append(rel)
        kept_uids.add(source)
        kept_uids.add(target)

    relation_sources = [str(rel.get("source_ref", "")) for rel in kept_relations if rel.get("source_ref")]
    top_sources = [source for source, _ in Counter(relation_sources).most_common(10)]
    for node in nodes:
        if str(node.get("type")) != "clause":
            continue
        sources = node.get("sources", []) if isinstance(node.get("sources"), list) else []
        if any(source in top_sources for source in sources):
            kept_uids.add(str(node.get("uid")))

    kept_nodes = [node for node in nodes if str(node.get("uid")) in kept_uids]
    if len(kept_nodes) > limit:
        ranked = _rank_topic_nodes(kept_nodes, keyword, seed_uids)
        keep_uids = {str(node.get("uid")) for node in ranked[:limit]}
        kept_nodes = [node for node in ranked if str(node.get("uid")) in keep_uids]
        kept_relations = [
            rel for rel in kept_relations
            if str(rel.get("source")) in keep_uids and str(rel.get("target")) in keep_uids
        ]

    return kept_nodes, kept_relations


def query_graph(graph: Dict[str, object], keyword: str = "", limit: int = 80) -> Dict[str, object]:
    nodes = list(graph.get("nodes", []))
    relations = list(graph.get("relations", graph.get("links", [])))
    keyword_text = str(keyword or "").strip()
    limit = max(10, int(limit or 80))

    topic_rule = _detect_topic(keyword_text)
    if keyword_text and topic_rule:
        filtered_nodes, filtered_relations = _compact_topic_subgraph(
            nodes,
            relations,
            keyword_text,
            topic_rule,
            limit=limit,
        )
    elif keyword_text:
        matched_node_uids = {
            str(node.get("uid"))
            for node in nodes
            if _node_matches_keyword(node, keyword_text)
        }
        matched_relations = [
            rel for rel in relations
            if str(rel.get("source")) in matched_node_uids
            or str(rel.get("target")) in matched_node_uids
            or _relation_matches_keyword(rel, keyword_text)
        ]
        related_uids = set(matched_node_uids)
        for rel in matched_relations:
            related_uids.add(str(rel.get("source")))
            related_uids.add(str(rel.get("target")))
        filtered_nodes = [node for node in nodes if str(node.get("uid")) in related_uids]
        filtered_relations = [
            rel for rel in matched_relations
            if str(rel.get("source")) in related_uids and str(rel.get("target")) in related_uids
        ]
    else:
        filtered_nodes = nodes
        filtered_relations = relations

    if len(filtered_nodes) > limit:
        keep_uids = {str(node.get("uid")) for node in filtered_nodes[:limit]}
        filtered_nodes = filtered_nodes[:limit]
        filtered_relations = [
            rel for rel in filtered_relations
            if str(rel.get("source")) in keep_uids and str(rel.get("target")) in keep_uids
        ][: limit * 2]

    return {
        "nodes": filtered_nodes,
        "relations": filtered_relations,
        "links": filtered_relations,
        "stats": graph.get("stats", {}),
        "query": keyword_text,
    }


def _relation_text(rel: Dict[str, object]) -> str:
    source = rel.get("source_ref") or rel.get("source") or "未知来源"
    return f"{rel['head_label']} -> {rel['relation_label']} -> {rel['tail_label']}（来源：{source}）"


def summarize_related_graph(
    query: str,
    graph: Dict[str, object],
    risk_types: List[str] | None = None,
) -> Tuple[str, Dict[str, object]]:
    if not config.KG_ENABLED:
        return "未启用知识图谱。", {"enabled": False, "matched_relations": [], "matched_nodes": []}

    relations = list(graph.get("relations", graph.get("links", [])))
    nodes = list(graph.get("nodes", []))
    if not relations and not nodes:
        return "无图谱命中。", {"enabled": True, "matched_relations": [], "matched_nodes": []}

    query_text = str(query or "")
    risk_types = risk_types or []
    matched_relations: List[Dict[str, object]] = []
    matched_nodes: List[Dict[str, object]] = []

    for rel in relations:
        labels = [
            str(rel.get("head_label", "")),
            str(rel.get("tail_label", "")),
            str(rel.get("relation_label", "")),
            str(rel.get("source_ref", "")),
        ]
        if any(token and token in query_text for token in labels):
            matched_relations.append(rel)
            continue
        if rel.get("head_id") in risk_types or rel.get("tail_id") in risk_types:
            matched_relations.append(rel)

    if not matched_relations:
        priority_relations = [
            rel for rel in relations
            if rel.get("relation") in {"indicates", "requires_action", "has_parameter", "triggers_hazard", "responsible_for"}
        ]
        matched_relations = priority_relations[:config.KG_MAX_RELATED_TRIPLES]
    else:
        matched_relations = matched_relations[:config.KG_MAX_RELATED_TRIPLES]

    matched_uids = {str(rel.get("source")) for rel in matched_relations} | {
        str(rel.get("target")) for rel in matched_relations
    }
    for node in nodes:
        if str(node.get("uid")) in matched_uids:
            matched_nodes.append(node)

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
