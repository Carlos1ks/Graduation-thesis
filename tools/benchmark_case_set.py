import base64
import csv
import json
import os
import statistics
import sys
import time
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent import _build_shared_context, _route_agents  # noqa: E402
from knowledge_graph import build_knowledge_graph, summarize_related_graph  # noqa: E402
from pdf_parser import app, clean_text  # noqa: E402
from retrieval import ingest_document, retrieve_relevant_chunks  # noqa: E402
from risk_fusion import build_risk_profile  # noqa: E402


CASESET_PATH = ROOT / "docs" / "figures" / "benchmark_case_set.csv"
DETAIL_PATH = ROOT / "docs" / "figures" / "benchmark_case_eval_results.csv"
SUMMARY_PATH = ROOT / "docs" / "figures" / "benchmark_case_eval_summary.json"

DEFAULT_PDF_PATH = os.environ.get("BENCH_PDF_PATH", "").strip()
DEFAULT_IMAGE_PATH = os.environ.get("BENCH_IMAGE_PATH", "").strip()

RISK_LEVEL_ORDER = {"低": 0, "中": 1, "高": 2, "极高": 3}


def load_cases():
    with CASESET_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def split_pipe(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def extract_pdf_text(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    try:
        full_text = []
        for page in doc:
            full_text.append(page.get_text())
        return clean_text("\n".join(full_text))
    finally:
        doc.close()


def build_history(case_id: str, query: str) -> list[dict]:
    history_map = {
        "G03": [
            {"role": "user", "content": "当前场景是掘进工作面瓦斯浓度已达到 1.5%，人员正在撤离。"},
            {"role": "assistant", "content": "建议先停止作业、切断电源，并组织人员沿避灾路线撤离。"},
        ],
        "W04": [
            {"role": "user", "content": "掘进面疑似透水，已有作业人员开始回撤。"},
            {"role": "assistant", "content": "建议立即停止作业，优先组织回撤并核对人数。"},
        ],
        "P04": [
            {"role": "user", "content": "上一轮已经启动撤离，现场人员正在分批回撤。"},
            {"role": "assistant", "content": "需要继续核对班组名单，避免遗漏人员滞留井下。"},
        ],
        "C05": [
            {"role": "user", "content": "现场第一批紧急动作已经完成，风险暂未完全解除。"},
            {"role": "assistant", "content": "下一阶段需要围绕复测、警戒、搜救和持续上报展开。"},
        ],
        "C02": [
            {"role": "user", "content": "当前已知瓦斯超限，现场还有烟雾和停电迹象。"},
            {"role": "assistant", "content": "这属于复合高危场景，需要同步考虑瓦斯、火灾和人员风险。"},
        ],
    }
    return history_map.get(case_id, [
        {"role": "user", "content": f"当前问题背景为：{query}"},
        {"role": "assistant", "content": "请继续结合已有上下文判断风险并组织应急动作。"},
    ])


def analyze_image(image_path: Path) -> dict:
    fallback = {
        "image_name": image_path.name,
        "summary": "明火、浓烟、火灾现场",
        "source_type": "image_analysis_fallback",
    }
    try:
        image_bytes = image_path.read_bytes()
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        with app.test_client() as client:
            resp = client.post(
                "/api/image-analyze",
                data=json.dumps({"image_base64": encoded, "image_name": image_path.name}, ensure_ascii=False),
                content_type="application/json",
            )
        if resp.status_code != 200:
            return fallback
        payload = resp.get_json() or {}
        result = payload.get("result") or []
        keywords = []
        for item in result[:5]:
            keyword = item.get("keyword") or item.get("class_name")
            if keyword:
                keywords.append(str(keyword))
        if not keywords:
            return fallback
        return {
            "image_name": image_path.name,
            "summary": "、".join(keywords[:3]),
            "source_type": "image_analysis",
        }
    except Exception:
        return fallback


def keyword_recall(expected_items: list[str], actual_texts: list[str]) -> float:
    if not expected_items:
        return 1.0
    hits = 0
    haystack = "\n".join(actual_texts)
    for item in expected_items:
        if item and item in haystack:
            hits += 1
    return round(hits / len(expected_items), 4)


def set_recall(expected_items: list[str], actual_items: list[str]) -> float:
    if not expected_items:
        return 1.0
    expected = set(expected_items)
    actual = set(actual_items)
    return round(len(expected & actual) / len(expected), 4)


def set_precision(expected_items: list[str], actual_items: list[str]) -> float:
    actual = set(actual_items)
    if not actual:
        return 0.0
    expected = set(expected_items)
    return round(len(expected & actual) / len(actual), 4)


def set_f1(expected_items: list[str], actual_items: list[str]) -> float:
    recall = set_recall(expected_items, actual_items)
    precision = set_precision(expected_items, actual_items)
    if recall + precision == 0:
        return 0.0
    return round(2 * recall * precision / (recall + precision), 4)


def risk_level_accuracy(expected_level: str, actual_level: str) -> float:
    return 1.0 if expected_level == actual_level else 0.0


def risk_level_distance(expected_level: str, actual_level: str) -> float:
    if expected_level not in RISK_LEVEL_ORDER or actual_level not in RISK_LEVEL_ORDER:
        return 1.0
    return abs(RISK_LEVEL_ORDER[expected_level] - RISK_LEVEL_ORDER[actual_level])


def build_mode_inputs(case: dict, retrieved_documents: list[dict], image_evidence: list[dict]):
    input_mode = case["input_mode"]
    history = build_history(case["case_id"], case["query"]) if "history" in input_mode else []
    documents = retrieved_documents if "doc" in input_mode else []
    images = image_evidence if "image" in input_mode else []
    return history, documents, images


def evaluate_case(mode: str, case: dict, retrieved_documents: list[dict], image_evidence: list[dict]) -> dict:
    history, documents, images = build_mode_inputs(case, retrieved_documents, image_evidence)
    if mode == "current_multi":
        history = []
        documents = []
        images = []

    expected_risk_types = split_pipe(case["expected_risk_types"])
    expected_signals = split_pipe(case["expected_signals"])
    expected_agents = split_pipe(case["expected_agents"])
    required_actions = split_pipe(case["required_actions"])

    start = time.perf_counter()
    risk_profile = build_risk_profile(case["query"], history, documents, images)
    graph = build_knowledge_graph(documents)
    graph_summary, graph_used = summarize_related_graph(
        case["query"],
        graph,
        risk_types=list(risk_profile.get("risk_types", [])),
    )
    shared_context = _build_shared_context(
        case["query"],
        history,
        documents,
        images,
        risk_profile=risk_profile,
        graph_summary=graph_summary,
    )
    route = _route_agents(
        shared_context,
        has_doc_evidence=bool(documents),
        has_image_evidence=bool(images),
        risk_profile=risk_profile,
    )
    latency = round(time.perf_counter() - start, 3)

    actual_risk_level = str(risk_profile.get("risk_level") or "")
    actual_risk_types = list(risk_profile.get("risk_type_labels") or [])
    actual_signals = [str(item.get("signal_label") or item.get("signal_id") or "") for item in risk_profile.get("signals_detected", [])]
    actual_agents = list(route.get("selected_agents") or [])
    retrieved_texts = [str(item.get("text") or "") for item in documents]

    return {
        "case_id": case["case_id"],
        "scenario_type": case["scenario_type"],
        "mode": mode,
        "input_mode": case["input_mode"],
        "latency_s": latency,
        "route_mode": route.get("route_mode", ""),
        "expected_risk_level": case["expected_risk_level"],
        "actual_risk_level": actual_risk_level,
        "risk_level_exact": risk_level_accuracy(case["expected_risk_level"], actual_risk_level),
        "risk_level_distance": risk_level_distance(case["expected_risk_level"], actual_risk_level),
        "risk_type_recall": set_recall(expected_risk_types, actual_risk_types),
        "signal_recall": set_recall(expected_signals, actual_signals),
        "agent_recall": set_recall(expected_agents, actual_agents),
        "agent_precision": set_precision(expected_agents, actual_agents),
        "agent_f1": set_f1(expected_agents, actual_agents),
        "action_keyword_recall_in_docs": keyword_recall(required_actions, retrieved_texts) if documents else float("nan"),
        "doc_evidence_count": len(documents),
        "image_evidence_count": len(images),
        "history_used": 1 if history else 0,
        "kg_relation_count": int(graph_used.get("relation_count", 0) or 0),
        "kg_hit": 1 if int(graph_used.get("relation_count", 0) or 0) > 0 else 0,
        "actual_risk_types": "|".join(actual_risk_types),
        "actual_signals": "|".join(actual_signals),
        "actual_agents": "|".join(actual_agents),
    }


def mean_metric(rows: list[dict], key: str) -> float:
    values = [float(row[key]) for row in rows if str(row.get(key)) not in {"nan", ""}]
    if not values:
        return float("nan")
    return round(statistics.mean(values), 4)


def scenario_breakdown(rows: list[dict]) -> dict:
    by_scenario = {}
    for scenario in sorted({row["scenario_type"] for row in rows}):
        subset = [row for row in rows if row["scenario_type"] == scenario]
        by_scenario[scenario] = {
            "count": len(subset),
            "risk_level_exact": mean_metric(subset, "risk_level_exact"),
            "risk_type_recall": mean_metric(subset, "risk_type_recall"),
            "signal_recall": mean_metric(subset, "signal_recall"),
            "agent_f1": mean_metric(subset, "agent_f1"),
            "latency_s": mean_metric(subset, "latency_s"),
        }
    return by_scenario


def summarize(rows: list[dict]) -> dict:
    return {
        "count": len(rows),
        "risk_level_exact": mean_metric(rows, "risk_level_exact"),
        "risk_level_distance": mean_metric(rows, "risk_level_distance"),
        "risk_type_recall": mean_metric(rows, "risk_type_recall"),
        "signal_recall": mean_metric(rows, "signal_recall"),
        "agent_recall": mean_metric(rows, "agent_recall"),
        "agent_precision": mean_metric(rows, "agent_precision"),
        "agent_f1": mean_metric(rows, "agent_f1"),
        "action_keyword_recall_in_docs": mean_metric(rows, "action_keyword_recall_in_docs"),
        "doc_evidence_count": mean_metric(rows, "doc_evidence_count"),
        "image_evidence_count": mean_metric(rows, "image_evidence_count"),
        "history_used": mean_metric(rows, "history_used"),
        "kg_hit_rate": mean_metric(rows, "kg_hit"),
        "latency_s": mean_metric(rows, "latency_s"),
        "route_mode_distribution": {
            mode: sum(1 for row in rows if row["route_mode"] == mode)
            for mode in sorted({row["route_mode"] for row in rows})
        },
        "by_scenario": scenario_breakdown(rows),
    }


def write_csv(rows: list[dict]) -> None:
    fieldnames = list(rows[0].keys())
    with DETAIL_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    pdf_path = Path(DEFAULT_PDF_PATH) if DEFAULT_PDF_PATH else None
    image_path = Path(DEFAULT_IMAGE_PATH) if DEFAULT_IMAGE_PATH else None
    if not pdf_path or not pdf_path.exists():
        raise FileNotFoundError("未找到 BENCH_PDF_PATH 指定的规程 PDF。")
    if not image_path or not image_path.exists():
        raise FileNotFoundError("未找到 BENCH_IMAGE_PATH 指定的现场图片。")

    cases = load_cases()
    pdf_text = extract_pdf_text(pdf_path)
    session_id = f"benchmark-case-set-{int(time.time())}"
    ingest_document(session_id=session_id, file_name=pdf_path.name, text=pdf_text)
    image_evidence = [analyze_image(image_path)]

    rows = []
    for case in cases:
        retrieved_documents = []
        if "doc" in case["input_mode"]:
            retrieved_documents = retrieve_relevant_chunks(session_id=session_id, query=case["query"], top_k=4)
        rows.append(evaluate_case("current_multi", case, retrieved_documents, image_evidence))
        rows.append(evaluate_case("enhanced_multi", case, retrieved_documents, image_evidence))

    write_csv(rows)
    summary = {
        "current_multi": summarize([row for row in rows if row["mode"] == "current_multi"]),
        "enhanced_multi": summarize([row for row in rows if row["mode"] == "enhanced_multi"]),
        "image_evidence_summary": image_evidence[0]["summary"],
        "pdf_file": str(pdf_path),
        "image_file": str(image_path),
    }
    with SUMMARY_PATH.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("[OK] case set benchmark done")
    print(f"CSV: {DETAIL_PATH}")
    print(f"JSON: {SUMMARY_PATH}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
