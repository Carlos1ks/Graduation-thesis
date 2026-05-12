"""基于规则的轻量煤矿应急知识图谱构建与检索。"""
from __future__ import annotations

from typing import Dict, List, Tuple

from config import config
from domain_schema import ENTITY_GROUPS, RELATION_LABELS


def _match_entities(text: str) -> List[Dict[str, str]]:
    content = str(text or "")
    matched: List[Dict[str, str]] = []
    seen = set()
    for entity_type, definitions in ENTITY_GROUPS.items():
        for entity_id, definition in definitions.items():
            if any(keyword in content for keyword in definition["keywords"]):
                key = (entity_type, entity_id)
                if key in seen:
                    continue
                seen.add(key)
                matched.append({
                    "type": entity_type,
                    "id": entity_id,
                    "label": definition["label"],
                })
    return matched


def _make_relation(head: Dict[str, str], relation: str, tail: Dict[str, str], source: str) -> Dict[str, str]:
    return {
        "head_type": head["type"],
        "head_id": head["id"],
        "head_label": head["label"],
        "relation": relation,
        "relation_label": RELATION_LABELS.get(relation, relation),
        "tail_type": tail["type"],
        "tail_id": tail["id"],
        "tail_label": tail["label"],
        "source": source,
    }


def build_knowledge_graph(documents: List[Dict[str, object]]) -> Dict[str, object]:
    if not config.KG_ENABLED or not documents:
        return {
            "nodes": [],
            "relations": [],
            "document_summaries": [],
        }

    nodes: List[Dict[str, str]] = []
    relations: List[Dict[str, str]] = []
    node_seen = set()
    relation_seen = set()
    document_summaries: List[Dict[str, object]] = []

    for doc in documents:
        source = str(doc.get("chunk_id") or doc.get("doc_name") or "unknown")
        text = str(doc.get("text", ""))
        doc_nodes = _match_entities(text)
        for node in doc_nodes:
            key = (node["type"], node["id"])
            if key not in node_seen:
                node_seen.add(key)
                nodes.append(node)

        grouped: Dict[str, List[Dict[str, str]]] = {}
        for node in doc_nodes:
            grouped.setdefault(node["type"], []).append(node)

        for symptom in grouped.get("symptom", []):
            for hazard in grouped.get("hazard", []):
                rel = _make_relation(symptom, "indicates", hazard, source)
                key = tuple(rel.values())
                if key not in relation_seen:
                    relation_seen.add(key)
                    relations.append(rel)

        for hazard in grouped.get("hazard", []):
            for action in grouped.get("action", []):
                rel = _make_relation(hazard, "requires_action", action, source)
                key = tuple(rel.values())
                if key not in relation_seen:
                    relation_seen.add(key)
                    relations.append(rel)
            for location in grouped.get("location", []):
                rel = _make_relation(hazard, "occurs_at", location, source)
                key = tuple(rel.values())
                if key not in relation_seen:
                    relation_seen.add(key)
                    relations.append(rel)

        for action in grouped.get("action", []):
            for department in grouped.get("department", []):
                rel = _make_relation(action, "responsible_for", department, source)
                key = tuple(rel.values())
                if key not in relation_seen:
                    relation_seen.add(key)
                    relations.append(rel)

        triples_preview = relations[-config.KG_MAX_TRIPLES_PER_DOC:]
        document_summaries.append({
            "doc_name": doc.get("doc_name"),
            "chunk_id": doc.get("chunk_id"),
            "node_count": len(doc_nodes),
            "relation_count": len(triples_preview),
        })

    return {
        "nodes": nodes,
        "relations": relations,
        "document_summaries": document_summaries,
    }


def _relation_text(rel: Dict[str, str]) -> str:
    return f"{rel['head_label']} -> {rel['relation_label']} -> {rel['tail_label']}（来源：{rel['source']}）"


def summarize_related_graph(
    query: str,
    graph: Dict[str, object],
    risk_types: List[str] | None = None,
) -> Tuple[str, Dict[str, object]]:
    if not config.KG_ENABLED:
        return "未启用知识图谱。", {"enabled": False, "matched_relations": [], "matched_nodes": []}

    relations = list(graph.get("relations", []))
    nodes = list(graph.get("nodes", []))
    if not relations and not nodes:
        return "无图谱命中。", {"enabled": True, "matched_relations": [], "matched_nodes": []}

    query_text = str(query or "")
    risk_types = risk_types or []
    matched_relations: List[Dict[str, str]] = []
    matched_nodes: List[Dict[str, str]] = []

    for rel in relations:
        if any(token in query_text for token in [rel["head_label"], rel["tail_label"]]):
            matched_relations.append(rel)
            continue
        if rel["head_id"] in risk_types or rel["tail_id"] in risk_types:
            matched_relations.append(rel)

    if not matched_relations:
        matched_relations = relations[:config.KG_MAX_RELATED_TRIPLES]
    else:
        matched_relations = matched_relations[:config.KG_MAX_RELATED_TRIPLES]

    matched_keys = {(rel["head_type"], rel["head_id"]) for rel in matched_relations} | {
        (rel["tail_type"], rel["tail_id"]) for rel in matched_relations
    }
    for node in nodes:
        if (node["type"], node["id"]) in matched_keys:
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
