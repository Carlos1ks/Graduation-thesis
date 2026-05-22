import csv
import json
import math
import os
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import fitz
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from config import config  # noqa: E402
from app import clean_text  # noqa: E402
from retrieval import _embed_texts, ingest_document, retrieve_relevant_chunks  # noqa: E402
from risk_fusion import build_risk_profile  # noqa: E402


PDF_PATH = Path(os.environ.get("BENCH_PDF_PATH", ROOT.parent / "煤矿安全规程2025.pdf"))
TRIPLES_PATH = ROOT / "docs" / "coal-mine-safety-2025-triples.json"
OUT_DIR = ROOT / "docs" / "figures"
DETAIL_PATH = OUT_DIR / "retrieval_strategy_results.csv"
SUMMARY_PATH = OUT_DIR / "retrieval_strategy_summary.json"

TOP_K = int(os.environ.get("BENCH_TOP_K", "4"))
CASE_LIMIT = int(os.environ.get("BENCH_CASE_LIMIT", "8"))


CASES = [
    {
        "case_id": "Q01",
        "query": "掘进工作面瓦斯浓度持续上升并接近超限，调度室应立即组织哪些处置步骤？",
        "reference": "应立即停止作业，切断相关电源，组织作业人员沿避灾路线撤离，加强通风和瓦斯复测，并向调度室和相关专业部门报告。",
        "expected": ["瓦斯超限", "停止作业", "切断电源", "撤离人员", "加强通风", "上报调度", "复测"],
    },
    {
        "case_id": "Q02",
        "query": "井下运输巷道出现明火和浓烟，如何组织初期救援并防止事故扩大？",
        "reference": "应先停止危险作业并切断电源，组织人员撤离和设置警戒，通知调度室、通防和救护力量，控制火源并持续监测烟雾和有害气体。",
        "expected": ["火灾", "停止作业", "切断电源", "撤离人员", "设置警戒", "上报调度", "组织救援", "持续监测"],
    },
    {
        "case_id": "Q03",
        "query": "掘进面连续出现挂红、挂汗和底鼓现象，是否属于突水前兆，应如何处置？",
        "reference": "该情况属于突水前兆，应立即停止作业，撤出受威胁区域人员，报告调度室，设置警戒，开展水害排查和排水准备。",
        "expected": ["水害", "突水前兆", "停止作业", "撤离人员", "上报调度", "设置警戒", "排水"],
    },
    {
        "case_id": "Q04",
        "query": "井下2名作业人员失联且对讲机无响应，搜救行动应如何分组并保证救援队安全？",
        "reference": "应立即核对人员位置并上报调度，组织救护队分组搜救，保持通信联络，设置警戒和安全员监护，严禁盲目进入高风险区域。",
        "expected": ["人员失联", "核对人数", "上报调度", "组织救援", "保持通信", "设置警戒", "安全员"],
    },
    {
        "case_id": "Q05",
        "query": "瓦斯超限同时出现烟雾和停电迹象，系统应如何整合规程、图谱关系和历史信息给出处置建议？",
        "reference": "该场景属于瓦斯、火灾和人员风险叠加的复合风险，应停止作业、切断电源、撤离人员、加强通风复测，结合规程依据和图谱关系组织调度、通防、机电和救护力量联动。",
        "expected": ["瓦斯超限", "火灾", "复合风险", "停止作业", "切断电源", "撤离人员", "加强通风", "复测", "协同联动"],
    },
    {
        "case_id": "Q06",
        "query": "泵房水位持续上升并伴随排水能力下降，调度室应如何组织处置？",
        "reference": "应判断为水害风险，及时上报调度，组织排水设备检查和加强排水，设置警戒，必要时撤离受威胁人员并安排专业人员复查。",
        "expected": ["水害", "水位异常", "上报调度", "排水", "设置警戒", "撤离人员", "复查"],
    },
    {
        "case_id": "Q07",
        "query": "封闭火区附近监测异常并伴随回风温度升高，应如何安排复查与警戒？",
        "reference": "应按照火灾复燃风险处理，限制人员进入，设置警戒，组织专业人员复查火区和回风监测数据，持续监测并向调度室报告。",
        "expected": ["火灾", "高温", "设置警戒", "限制进入", "复查", "持续监测", "上报调度"],
    },
    {
        "case_id": "Q08",
        "query": "事故扩大需要调度室、通防、机电和救护队同时联动，统一口径应包含哪些内容？",
        "reference": "统一口径应包含事故类型、风险等级、人员撤离情况、规程依据、处置阶段、责任分工、通信频率和升级上报条件，确保调度室、通防、机电和救护队协同一致。",
        "expected": ["事故扩大", "风险等级", "撤离人员", "规程依据", "责任分工", "保持通信", "协同联动", "升级上报"],
    },
]


KEYPOINT_ALIASES = {
    "瓦斯超限": ["瓦斯超限", "瓦斯浓度", "甲烷", "超限"],
    "火灾": ["火灾", "明火", "浓烟", "烟雾", "火源", "复燃"],
    "水害": ["水害", "突水", "透水", "涌水"],
    "突水前兆": ["突水前兆", "挂红", "挂汗", "底鼓", "前兆"],
    "人员失联": ["人员失联", "失联", "无响应", "被困"],
    "事故扩大": ["事故扩大", "扩大", "升级"],
    "复合风险": ["复合风险", "叠加", "多重风险"],
    "水位异常": ["水位", "排水能力下降", "泵房"],
    "高温": ["高温", "温度升高", "回风温度"],
    "停止作业": ["停止作业", "停工", "停产", "停产撤人", "停止施工"],
    "切断电源": ["切断电源", "断电", "停电"],
    "撤离人员": ["撤离人员", "撤人", "撤出人员", "疏散", "撤离"],
    "加强通风": ["加强通风", "恢复通风", "通风"],
    "上报调度": ["上报调度", "报告调度", "汇报调度", "报告", "上报", "调度室"],
    "复测": ["复测", "检测", "复核", "瓦斯复测", "监测"],
    "设置警戒": ["设置警戒", "警戒", "封控"],
    "组织救援": ["组织救援", "救护队", "搜救", "救援", "救援力量"],
    "持续监测": ["持续监测", "监测", "观察"],
    "排水": ["排水", "水泵", "排水设备", "备用水泵"],
    "核对人数": ["核对人数", "清点人数", "核对人员", "人员位置", "人员状态"],
    "保持通信": ["保持通信", "通信联络", "对讲机", "通信"],
    "安全员": ["安全员", "监护", "安全监护", "安全部门"],
    "协同联动": ["协同", "联动", "协调", "统一口径"],
    "复查": ["复查", "检查", "排查"],
    "限制进入": ["限制进入", "严禁进入", "禁止进入"],
    "风险等级": ["风险等级", "等级"],
    "规程依据": ["规程依据", "依据", "条款", "规程"],
    "责任分工": ["责任分工", "分工", "职责", "责任", "责任主体"],
    "升级上报": ["升级上报", "升级条件", "上报条件", "升级"],
}


def build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=config.require_longcat_api_key(),
        base_url=config.LONGCAT_BASE_URL,
        model=config.LONGCAT_MODEL,
        temperature=0.1,
        max_tokens=700,
        timeout=config.LONGCAT_READ_TIMEOUT,
    )


def invoke_llm(llm: ChatOpenAI, system_prompt: str, user_prompt: str) -> str:
    resp = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])
    content = resp.content
    if isinstance(content, str):
        return content.strip()
    return str(content).strip()


def extract_pdf_text(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    try:
        return clean_text("\n".join(page.get_text() for page in doc))
    finally:
        doc.close()


def load_triples(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = {}
    for node in payload.get("nodes", []):
        if not isinstance(node, dict):
            continue
        key = (str(node.get("type") or ""), str(node.get("id") or ""))
        nodes[key] = str(node.get("label") or node.get("id") or "")

    relations = []
    for rel in payload.get("relationships", []):
        if not isinstance(rel, dict):
            continue
        source_label = nodes.get((str(rel.get("source_type") or ""), str(rel.get("source_id") or "")), str(rel.get("source_id") or ""))
        target_label = nodes.get((str(rel.get("target_type") or ""), str(rel.get("target_id") or "")), str(rel.get("target_id") or ""))
        relation_text = "；".join(
            item for item in [
                source_label,
                str(rel.get("type") or ""),
                target_label,
                str(rel.get("condition") or ""),
                str(rel.get("evidence") or ""),
                str(rel.get("article_label") or ""),
            ]
            if item
        )
        relations.append({
            "source_label": source_label,
            "target_label": target_label,
            "relation": str(rel.get("type") or ""),
            "condition": str(rel.get("condition") or ""),
            "evidence": str(rel.get("evidence") or ""),
            "article_label": str(rel.get("article_label") or ""),
            "text": relation_text,
        })
    return {"nodes": nodes, "relations": relations}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").lower())


def char_ngrams(text: str, min_n: int = 2, max_n: int = 4) -> Counter:
    content = normalize_text(text)
    grams = Counter()
    for n in range(min_n, max_n + 1):
        if len(content) < n:
            continue
        for idx in range(len(content) - n + 1):
            grams[content[idx: idx + n]] += 1
    return grams


def cosine_counter(left: Counter, right: Counter) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[key] * right.get(key, 0) for key in left)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def text_similarity(left: str, right: str) -> float:
    return cosine_counter(char_ngrams(left), char_ngrams(right))


def embedding_similarity(left: str, right: str) -> float:
    vectors = _embed_texts([left, right])
    if len(vectors) < 2:
        return 0.0
    left_vec = vectors[0]
    right_vec = vectors[1]
    denom = float((left_vec @ left_vec) ** 0.5 * (right_vec @ right_vec) ** 0.5)
    return float(left_vec @ right_vec / denom) if denom else 0.0


def relation_score(query: str, relation_text: str) -> float:
    score = text_similarity(query, relation_text)
    for key, aliases in KEYPOINT_ALIASES.items():
        if any(alias in query for alias in aliases) and any(alias in relation_text for alias in aliases):
            score += 0.18
    return score


def find_article_label(text: str) -> str:
    match = re.search(r"第[一二三四五六七八九十百千万零两\d]+条", str(text or ""))
    return match.group(0) if match else ""


def top_graph_relations(query: str, graph: dict[str, Any], article_label: str = "", limit: int = 5) -> list[dict[str, Any]]:
    ranked = []
    for rel in graph["relations"]:
        score = relation_score(query, rel["text"])
        if article_label and rel.get("article_label") == article_label:
            score += 0.35
        if score > 0:
            ranked.append((score, rel))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [rel for _, rel in ranked[:limit]]


def format_documents(documents: list[dict[str, Any]]) -> str:
    if not documents:
        return "无检索片段。"
    blocks = []
    for idx, doc in enumerate(documents, start=1):
        blocks.append(
            f"[{idx}] 来源：{doc.get('doc_name', '规程文档')}；片段：{doc.get('chunk_id', '')}；"
            f"得分：{doc.get('score', '')}\n{doc.get('text', '')[:650]}"
        )
    return "\n\n".join(blocks)


def format_relations(relations: list[dict[str, Any]]) -> str:
    if not relations:
        return "无图谱关系命中。"
    lines = []
    for idx, rel in enumerate(relations, start=1):
        condition = f"；条件：{rel['condition']}" if rel.get("condition") else ""
        evidence = f"；证据：{rel['evidence']}" if rel.get("evidence") else ""
        lines.append(
            f"[{idx}] {rel['source_label']} -> {rel['relation']} -> {rel['target_label']}"
            f"（{rel.get('article_label', '')}{condition}{evidence}）"
        )
    return "\n".join(lines)


def with_retrieval_weights(vector: float, graph: float, keyword: float, risk: float):
    class _WeightContext:
        def __enter__(self):
            self.old = (
                config.RAG_WEIGHT_VECTOR,
                config.RAG_WEIGHT_GRAPH,
                config.RAG_WEIGHT_KEYWORD,
                config.RAG_WEIGHT_RISK,
            )
            config.RAG_WEIGHT_VECTOR = vector
            config.RAG_WEIGHT_GRAPH = graph
            config.RAG_WEIGHT_KEYWORD = keyword
            config.RAG_WEIGHT_RISK = risk
            return self

        def __exit__(self, exc_type, exc, tb):
            (
                config.RAG_WEIGHT_VECTOR,
                config.RAG_WEIGHT_GRAPH,
                config.RAG_WEIGHT_KEYWORD,
                config.RAG_WEIGHT_RISK,
            ) = self.old

    return _WeightContext()


def vector_retrieve(session_id: str, query: str, top_k: int) -> list[dict[str, Any]]:
    with with_retrieval_weights(1.0, 0.0, 0.0, 0.0):
        return retrieve_relevant_chunks(session_id=session_id, query=query, top_k=top_k)


def hybrid_retrieve(session_id: str, query: str, graph: dict[str, Any], top_k: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    vector_docs = vector_retrieve(session_id, query, top_k)
    candidates = vector_retrieve(session_id, query, max(top_k * 4, 12))
    risk_profile = build_risk_profile(query, [], [], [])
    risk_summary = str(risk_profile.get("summary") or "")
    ranked = []
    all_relations = []
    for doc in candidates:
        text = str(doc.get("text") or "")
        article_label = find_article_label(text) or find_article_label(str(doc.get("chunk_id") or ""))
        rels = top_graph_relations(query, graph, article_label=article_label, limit=4)
        all_relations.extend(rels)
        vector_score = float(doc.get("vector_score") or doc.get("score") or 0.0)
        graph_score = max([relation_score(query, rel["text"]) for rel in rels] or [0.0])
        keyword_score = text_similarity(query, text)
        risk_score = text_similarity(risk_summary, text) if risk_summary else 0.0
        score = 0.40 * vector_score + 0.25 * graph_score + 0.20 * keyword_score + 0.15 * risk_score
        ranked.append((score, {**doc, "score": round(score, 4), "graph_score": round(graph_score, 4)}))
    ranked.sort(key=lambda item: item[0], reverse=True)

    selected_docs = list(vector_docs)
    seen_chunks = {str(doc.get("chunk_id") or "") for doc in selected_docs}
    for _, doc in ranked:
        if len(selected_docs) >= top_k:
            break
        chunk_id = str(doc.get("chunk_id") or "")
        if chunk_id in seen_chunks:
            continue
        seen_chunks.add(chunk_id)
        selected_docs.append(doc)

    dedup_relations = []
    seen = set()
    for rel in sorted(all_relations, key=lambda item: relation_score(query, item["text"]), reverse=True):
        key = (rel.get("source_label"), rel.get("relation"), rel.get("target_label"), rel.get("article_label"))
        if key in seen:
            continue
        seen.add(key)
        dedup_relations.append(rel)
        if len(dedup_relations) >= 5:
            break
    return selected_docs[:top_k], dedup_relations


def answer_pure_llm(llm: ChatOpenAI, query: str) -> str:
    system = (
        "你是煤矿应急问答助手。请直接回答用户问题，不使用外部检索结果，"
        "不要编造具体条款编号。必须按“风险判断、依据、处置动作、责任分工”四项输出，"
        "每项只写一句，控制在220字以内。"
    )
    return invoke_llm(llm, system, query)


def answer_vector_rag(llm: ChatOpenAI, query: str, documents: list[dict[str, Any]]) -> str:
    system = (
        "你是煤矿应急问答助手。请只根据给定规程片段和用户问题组织回答。"
        "必须按“风险判断、依据、处置动作、责任分工”四项输出，每项只写一句，控制在220字以内。"
    )
    prompt = f"用户问题：{query}\n\n规程片段：\n{format_documents(documents)}"
    return invoke_llm(llm, system, prompt)


def answer_hybrid_graph(llm: ChatOpenAI, query: str, documents: list[dict[str, Any]], relations: list[dict[str, Any]]) -> str:
    system = (
        "你是煤矿应急问答助手。请结合规程片段和知识图谱关系回答，优先使用图谱中的风险、条件、步骤和责任主体关系。"
        "必须按“风险判断、依据、处置动作、责任分工”四项输出，每项只写一句，控制在220字以内。"
    )
    prompt = (
        f"用户问题：{query}\n\n"
        f"规程片段：\n{format_documents(documents)}\n\n"
        f"知识图谱关系：\n{format_relations(relations)}"
    )
    return invoke_llm(llm, system, prompt)


def detect_keypoints(text: str) -> set[str]:
    hits = set()
    for key, aliases in KEYPOINT_ALIASES.items():
        if any(alias in text for alias in aliases):
            hits.add(key)
    return hits


def keypoint_metrics(answer: str, expected: list[str]) -> dict[str, float]:
    expected_set = set(expected)
    actual_set = detect_keypoints(answer)
    if not expected_set:
        return {"em": 1.0, "precision": 1.0, "recall": 1.0, "f1": 1.0}
    tp = len(expected_set & actual_set)
    fp = len(actual_set - expected_set)
    fn = len(expected_set - actual_set)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    em = tp / len(expected_set)
    return {
        "em": round(em, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def rouge_l(answer: str, reference: str) -> float:
    a = normalize_text(answer)
    b = normalize_text(reference)
    if not a or not b:
        return 0.0
    prev = [0] * (len(b) + 1)
    for char_a in a:
        curr = [0]
        for j, char_b in enumerate(b, start=1):
            if char_a == char_b:
                curr.append(prev[j - 1] + 1)
            else:
                curr.append(max(prev[j], curr[-1]))
        prev = curr
    lcs = prev[-1]
    precision = lcs / len(a) if a else 0.0
    recall = lcs / len(b) if b else 0.0
    return round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0


def score_answer(answer: str, case: dict[str, Any]) -> dict[str, float]:
    key_metrics = keypoint_metrics(answer, case["expected"])
    return {
        "em": key_metrics["em"],
        "f1": key_metrics["f1"],
        "rouge_l": rouge_l(answer, case["reference"]),
        "semantic_similarity": round(embedding_similarity(answer, case["reference"]), 4),
        "key_precision": key_metrics["precision"],
        "key_recall": key_metrics["recall"],
    }


def mean(rows: list[dict[str, Any]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) not in {"", None}]
    return round(statistics.mean(values), 4) if values else 0.0


def main() -> None:
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"PDF not found: {PDF_PATH}")
    if not TRIPLES_PATH.exists():
        raise FileNotFoundError(f"Triples not found: {TRIPLES_PATH}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    llm = build_llm()
    graph = load_triples(TRIPLES_PATH)
    session_id = f"retrieval-strategy-{int(time.time())}"
    pdf_text = extract_pdf_text(PDF_PATH)
    ingest_document(session_id=session_id, file_name=PDF_PATH.name, text=pdf_text)

    rows = []
    for case in CASES[:CASE_LIMIT]:
        query = case["query"]

        start = time.perf_counter()
        pure_answer = answer_pure_llm(llm, query)
        pure_latency = time.perf_counter() - start
        rows.append({
            **case,
            "strategy": "pure_llm",
            "method": "纯LLM",
            "answer": pure_answer,
            "latency_s": round(pure_latency, 3),
            "doc_context": "",
            "graph_context": "",
            **score_answer(pure_answer, case),
        })

        vector_docs = vector_retrieve(session_id, query, TOP_K)
        start = time.perf_counter()
        vector_answer = answer_vector_rag(llm, query, vector_docs)
        vector_latency = time.perf_counter() - start
        rows.append({
            **case,
            "strategy": "vector_rag",
            "method": "纯向量RAG",
            "answer": vector_answer,
            "latency_s": round(vector_latency, 3),
            "doc_context": " || ".join(str(doc.get("chunk_id", "")) for doc in vector_docs),
            "graph_context": "",
            **score_answer(vector_answer, case),
        })

        hybrid_docs, hybrid_relations = hybrid_retrieve(session_id, query, graph, TOP_K)
        start = time.perf_counter()
        hybrid_answer = answer_hybrid_graph(llm, query, hybrid_docs, hybrid_relations)
        hybrid_latency = time.perf_counter() - start
        rows.append({
            **case,
            "strategy": "hybrid_graph",
            "method": "混合图检索策略",
            "answer": hybrid_answer,
            "latency_s": round(hybrid_latency, 3),
            "doc_context": " || ".join(str(doc.get("chunk_id", "")) for doc in hybrid_docs),
            "graph_context": " || ".join(
                f"{rel.get('source_label')}->{rel.get('target_label')}@{rel.get('article_label')}"
                for rel in hybrid_relations
            ),
            **score_answer(hybrid_answer, case),
        })

    fieldnames = [
        "case_id", "query", "reference", "expected", "strategy", "method", "answer",
        "em", "f1", "rouge_l", "semantic_similarity", "key_precision", "key_recall",
        "latency_s", "doc_context", "graph_context",
    ]
    with DETAIL_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    summary = {}
    for strategy in ["pure_llm", "vector_rag", "hybrid_graph"]:
        subset = [row for row in rows if row["strategy"] == strategy]
        method = subset[0]["method"] if subset else strategy
        summary[strategy] = {
            "method": method,
            "case_count": len(subset),
            "em": mean(subset, "em"),
            "f1": mean(subset, "f1"),
            "rouge_l": mean(subset, "rouge_l"),
            "semantic_similarity": mean(subset, "semantic_similarity"),
            "latency_s": mean(subset, "latency_s"),
        }

    with SUMMARY_PATH.open("w", encoding="utf-8") as f:
        json.dump({
            "pdf_file": str(PDF_PATH),
            "triples_file": str(TRIPLES_PATH),
            "top_k": TOP_K,
            "case_count": len(CASES[:CASE_LIMIT]),
            "metrics_note": "EM is the exact hit rate of annotated key information units for open-domain emergency answers; F1 is keypoint precision/recall F1.",
            "summary": summary,
        }, f, ensure_ascii=False, indent=2)

    print("[OK] retrieval strategy benchmark done")
    print(f"CSV: {DETAIL_PATH}")
    print(f"JSON: {SUMMARY_PATH}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
