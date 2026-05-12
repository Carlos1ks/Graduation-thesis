import csv
import json
import statistics
import time
from pathlib import Path
import sys
import math
import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent import multi_agent_ask
from config import config


QUERIES = [
    "瓦斯浓度持续上升并接近超限，应立即执行哪些处置步骤？",
    "井下运输巷道出现明火和烟雾，如何组织初期救援并防止二次事故？",
    "掘进面疑似突水前兆，调度室应如何在30分钟内完成撤离与封控？",
    "发生人员失联且通信中断时，搜救行动应如何分组并保证救援队安全？",
    "事故扩大需要多部门联动时，如何设置统一口径与升级上报条件？",
]

SAMPLE_EVIDENCE = {
    "documents": [
        {
            "doc_name": "煤矿安全规程.pdf",
            "chunk_id": "煤矿安全规程.pdf:12",
            "text": "第十二条 发现瓦斯浓度超限时，应立即停止作业、撤出人员并采取通风处理措施。调度室、通防部门和现场班组应按职责组织断电、撤人和复核。",
            "score": 0.02,
            "source_type": "uploaded_doc",
        }
    ],
    "images": [
        {
            "image_name": "现场1.jpg",
            "summary": "巷道内有烟雾、设备和作业面迹象",
            "source_type": "image_analysis",
        }
    ],
}

QUERY_LIMIT = max(1, int(os.environ.get("BENCH_QUERY_LIMIT", "3")))
RETRY_TIMES = max(0, int(os.environ.get("BENCH_RETRIES", "0")))


def score_single_reply(text: str) -> dict:
    text = text or ""
    completeness_hits = sum(
        1
        for k in ["风险", "依据", "步骤", "协同"]
        if k in text
    )
    executable_hits = sum(
        1 for k in ["立即", "分钟", "责任", "先", "后"] if k in text
    )
    citation_hits = sum(1 for k in ["规程", "条", "依据", "注意事项"] if k in text)
    explain_hits = sum(1 for k in ["因为", "原因", "依据", "触发"] if k in text)

    return {
        "completeness": round(completeness_hits / 4 * 10, 2),
        "executability": round(min(executable_hits, 4) / 4 * 10, 2),
        "citation_consistency": round(min(citation_hits, 4) / 4 * 10, 2),
        "explainability": round(min(explain_hits, 4) / 4 * 10, 2),
        "risk_coverage": round(min(sum(1 for k in ["风险", "威胁", "超限", "烟雾"] if k in text), 4) / 4 * 10, 2),
        "route_quality": float("nan"),
    }


def score_multi_result(result: dict) -> dict:
    reply = result.get("reply", "")
    selected = result.get("selected_agents", [])
    selected_set = set(selected)
    coverage = len(selected_set & {"perception", "knowledge", "decision", "coordination"})

    completeness = min(coverage, 4) / 4 * 10
    executability_hits = sum(1 for k in ["0-10分钟", "10-30分钟", "责任分工", "立即动作"] if k in reply)
    citation_hits = sum(1 for k in ["相关依据", "关键参数", "注意事项", "条"] if k in reply)
    explain_hits = sum(1 for k in ["风险等级", "触发", "升级", "建议"] if k in reply)
    risk = result.get("risk_assessment", {})
    kg_used = result.get("kg_used", {})
    risk_hits = 0
    if risk.get("risk_level"):
        risk_hits += 1
    if risk.get("risk_type_labels"):
        risk_hits += 1
    if risk.get("signals_detected"):
        risk_hits += 1
    if result.get("source_fusion"):
        risk_hits += 1
    route_quality_hits = 0
    if result.get("route_mode"):
        route_quality_hits += 1
    if selected:
        route_quality_hits += 1
    if result.get("route_reason"):
        route_quality_hits += 1
    if kg_used.get("matched_relations"):
        route_quality_hits += 1

    return {
        "completeness": round(completeness, 2),
        "executability": round(min(executability_hits, 4) / 4 * 10, 2),
        "citation_consistency": round(min(citation_hits, 4) / 4 * 10, 2),
        "explainability": round(min(explain_hits, 4) / 4 * 10, 2),
        "risk_coverage": round(min(risk_hits, 4) / 4 * 10, 2),
        "route_quality": round(min(route_quality_hits, 4) / 4 * 10, 2),
    }


def build_single_model() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=config.LONGCAT_API_KEY,
        base_url=config.LONGCAT_BASE_URL,
        model=config.LONGCAT_MODEL,
        temperature=0.2,
        max_tokens=config.LONGCAT_MAX_TOKENS,
        timeout=config.LONGCAT_READ_TIMEOUT,
    )


def run_single_model(llm: ChatOpenAI, query: str) -> tuple[float, str]:
    prompt = (
        "你是煤矿应急助手，请直接给出处置建议。"
        "回答尽量包含风险判断、依据、步骤与协同安排。"
    )
    start = time.perf_counter()
    resp = llm.invoke([SystemMessage(content=prompt), HumanMessage(content=query)])
    latency = time.perf_counter() - start
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return latency, text


def run_multi_model(query: str) -> tuple[float, dict]:
    start = time.perf_counter()
    result = multi_agent_ask(query)
    latency = time.perf_counter() - start
    return latency, result


def run_enhanced_multi_model(query: str) -> tuple[float, dict]:
    start = time.perf_counter()
    result = multi_agent_ask(
        query=query,
        session_id="benchmark-session",
        history=[
            {"role": "user", "content": "当前矿井存在应急处置场景，需要结合规程和现场态势判断。"},
            {"role": "assistant", "content": "请提供事故类型、现场迹象和可用证据。"},
        ],
        evidence_documents=SAMPLE_EVIDENCE["documents"],
        evidence_images=SAMPLE_EVIDENCE["images"],
        options={"use_session_memory": True, "use_retrieval_evidence": True},
    )
    latency = time.perf_counter() - start
    return latency, result


def invoke_with_retry(func, *args, retries: int = 2):
    """带重试的调用包装，避免单次超时导致整轮基准失败。"""
    last_err = None
    for _ in range(retries + 1):
        try:
            return func(*args)
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise last_err


def mean_metric(rows: list[dict], key: str) -> float:
    values = [r[key] for r in rows if isinstance(r[key], (int, float)) and not math.isnan(r[key])]
    if not values:
        return float("nan")
    return round(statistics.mean(values), 2)


def main() -> None:
    out_dir = ROOT / "docs" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    single_llm = build_single_model()

    single_scores = []
    multi_scores = []
    enhanced_scores = []
    detail_rows = []

    for i, query in enumerate(QUERIES[:QUERY_LIMIT], start=1):
        s_latency = float("nan")
        m_latency = float("nan")
        e_latency = float("nan")
        s_reply = ""
        m_result = {}
        e_result = {}
        s_error = ""
        m_error = ""
        e_error = ""

        try:
            s_latency, s_reply = invoke_with_retry(run_single_model, single_llm, query, retries=RETRY_TIMES)
        except Exception as e:  # noqa: BLE001
            s_error = str(e)

        try:
            m_latency, m_result = invoke_with_retry(run_multi_model, query, retries=RETRY_TIMES)
        except Exception as e:  # noqa: BLE001
            m_error = str(e)

        try:
            e_latency, e_result = invoke_with_retry(run_enhanced_multi_model, query, retries=RETRY_TIMES)
        except Exception as e:  # noqa: BLE001
            e_error = str(e)

        s_score = score_single_reply(s_reply) if s_reply else {
            "completeness": float("nan"),
            "executability": float("nan"),
            "citation_consistency": float("nan"),
            "explainability": float("nan"),
            "risk_coverage": float("nan"),
            "route_quality": float("nan"),
        }
        m_score = score_multi_result(m_result) if m_result else {
            "completeness": float("nan"),
            "executability": float("nan"),
            "citation_consistency": float("nan"),
            "explainability": float("nan"),
            "risk_coverage": float("nan"),
            "route_quality": float("nan"),
        }
        e_score = score_multi_result(e_result) if e_result else {
            "completeness": float("nan"),
            "executability": float("nan"),
            "citation_consistency": float("nan"),
            "explainability": float("nan"),
            "risk_coverage": float("nan"),
            "route_quality": float("nan"),
        }

        single_scores.append({**s_score, "latency": round(s_latency, 3) if not math.isnan(s_latency) else float("nan")})
        multi_scores.append({**m_score, "latency": round(m_latency, 3) if not math.isnan(m_latency) else float("nan")})
        enhanced_scores.append({**e_score, "latency": round(e_latency, 3) if not math.isnan(e_latency) else float("nan")})

        detail_rows.append(
            {
                "query_id": i,
                "query": query,
                "single_latency_s": round(s_latency, 3) if not math.isnan(s_latency) else float("nan"),
                "multi_latency_s": round(m_latency, 3) if not math.isnan(m_latency) else float("nan"),
                "enhanced_latency_s": round(e_latency, 3) if not math.isnan(e_latency) else float("nan"),
                "single_completeness": s_score["completeness"],
                "multi_completeness": m_score["completeness"],
                "enhanced_completeness": e_score["completeness"],
                "single_executability": s_score["executability"],
                "multi_executability": m_score["executability"],
                "enhanced_executability": e_score["executability"],
                "single_citation_consistency": s_score["citation_consistency"],
                "multi_citation_consistency": m_score["citation_consistency"],
                "enhanced_citation_consistency": e_score["citation_consistency"],
                "single_explainability": s_score["explainability"],
                "multi_explainability": m_score["explainability"],
                "enhanced_explainability": e_score["explainability"],
                "single_risk_coverage": s_score["risk_coverage"],
                "multi_risk_coverage": m_score["risk_coverage"],
                "enhanced_risk_coverage": e_score["risk_coverage"],
                "multi_route_quality": m_score["route_quality"],
                "enhanced_route_quality": e_score["route_quality"],
                "route_mode": m_result.get("route_mode", ""),
                "selected_agents": "|".join(m_result.get("selected_agents", [])),
                "enhanced_route_mode": e_result.get("route_mode", ""),
                "enhanced_selected_agents": "|".join(e_result.get("selected_agents", [])),
                "single_error": s_error,
                "multi_error": m_error,
                "enhanced_error": e_error,
            }
        )

    summary = {
        "single": {
            "completeness": mean_metric(single_scores, "completeness"),
            "executability": mean_metric(single_scores, "executability"),
            "citation_consistency": mean_metric(single_scores, "citation_consistency"),
            "explainability": mean_metric(single_scores, "explainability"),
            "risk_coverage": mean_metric(single_scores, "risk_coverage"),
            "route_quality": mean_metric(single_scores, "route_quality"),
            "latency": mean_metric(single_scores, "latency"),
        },
        "multi": {
            "completeness": mean_metric(multi_scores, "completeness"),
            "executability": mean_metric(multi_scores, "executability"),
            "citation_consistency": mean_metric(multi_scores, "citation_consistency"),
            "explainability": mean_metric(multi_scores, "explainability"),
            "risk_coverage": mean_metric(multi_scores, "risk_coverage"),
            "route_quality": mean_metric(multi_scores, "route_quality"),
            "latency": mean_metric(multi_scores, "latency"),
        },
        "enhanced_multi": {
            "completeness": mean_metric(enhanced_scores, "completeness"),
            "executability": mean_metric(enhanced_scores, "executability"),
            "citation_consistency": mean_metric(enhanced_scores, "citation_consistency"),
            "explainability": mean_metric(enhanced_scores, "explainability"),
            "risk_coverage": mean_metric(enhanced_scores, "risk_coverage"),
            "route_quality": mean_metric(enhanced_scores, "route_quality"),
            "latency": mean_metric(enhanced_scores, "latency"),
        },
    }

    csv_path = out_dir / "benchmark_real_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
        writer.writeheader()
        writer.writerows(detail_rows)

    json_path = out_dir / "benchmark_summary.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("[OK] benchmark done")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
