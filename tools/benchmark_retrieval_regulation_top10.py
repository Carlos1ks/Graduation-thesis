import csv
import importlib.util
import json
import statistics
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_SCRIPT = ROOT / "tools" / "benchmark_retrieval_strategies.py"
CASE_PATH = ROOT / "docs" / "figures" / "retrieval_strategy_top10_regulation_cases.json"
DETAIL_PATH = ROOT / "docs" / "figures" / "retrieval_strategy_top10_regulation_results.csv"
SUMMARY_PATH = ROOT / "docs" / "figures" / "retrieval_strategy_top10_regulation_summary.json"


def load_base_module():
    spec = importlib.util.spec_from_file_location("benchmark_retrieval_strategies", BASE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    brs = load_base_module()
    cases = json.loads(CASE_PATH.read_text(encoding="utf-8"))

    llm = brs.build_llm()
    graph = brs.load_triples(brs.TRIPLES_PATH)
    session_id = f"retrieval-regulation-top10-{int(time.time())}"
    pdf_text = brs.extract_pdf_text(brs.PDF_PATH)
    brs.ingest_document(session_id=session_id, file_name=brs.PDF_PATH.name, text=pdf_text)

    rows = []
    for case in cases:
        query = case["query"]

        start = time.perf_counter()
        pure_answer = brs.answer_pure_llm(llm, query)
        pure_latency = time.perf_counter() - start
        rows.append({
            **case,
            "strategy": "pure_llm",
            "method": "纯LLM",
            "answer": pure_answer,
            "latency_s": round(pure_latency, 3),
            "doc_context": "",
            "graph_context": "",
            **brs.score_answer(pure_answer, case),
        })

        vector_docs = brs.vector_retrieve(session_id, query, brs.TOP_K)
        start = time.perf_counter()
        vector_answer = brs.answer_vector_rag(llm, query, vector_docs)
        vector_latency = time.perf_counter() - start
        rows.append({
            **case,
            "strategy": "vector_rag",
            "method": "纯向量RAG",
            "answer": vector_answer,
            "latency_s": round(vector_latency, 3),
            "doc_context": brs.format_documents(vector_docs),
            "graph_context": "",
            **brs.score_answer(vector_answer, case),
        })

        hybrid_docs, relations = brs.hybrid_retrieve(session_id, query, graph, brs.TOP_K)
        start = time.perf_counter()
        hybrid_answer = brs.answer_hybrid_graph(llm, query, hybrid_docs, relations)
        hybrid_latency = time.perf_counter() - start
        rows.append({
            **case,
            "strategy": "hybrid_graph",
            "method": "混合图检索策略",
            "answer": hybrid_answer,
            "latency_s": round(hybrid_latency, 3),
            "doc_context": brs.format_documents(hybrid_docs),
            "graph_context": brs.format_relations(relations),
            **brs.score_answer(hybrid_answer, case),
        })

    fieldnames = list(rows[0].keys())
    with DETAIL_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "pdf_file": str(brs.PDF_PATH),
        "triples_file": str(brs.TRIPLES_PATH),
        "top_k": brs.TOP_K,
        "case_count": len(cases),
        "summary": {},
    }
    for strategy, method in [
        ("pure_llm", "纯LLM"),
        ("vector_rag", "纯向量RAG"),
        ("hybrid_graph", "混合图检索策略"),
    ]:
        subset = [r for r in rows if r["strategy"] == strategy]
        summary["summary"][strategy] = {
            "method": method,
            "case_count": len(subset),
            "coverage": round(statistics.mean(float(r["em"]) for r in subset), 4),
            "f1": round(statistics.mean(float(r["f1"]) for r in subset), 4),
            "rouge_l": round(statistics.mean(float(r["rouge_l"]) for r in subset), 4),
            "semantic_similarity": round(statistics.mean(float(r["semantic_similarity"]) for r in subset), 4),
            "latency_s": round(statistics.mean(float(r["latency_s"]) for r in subset), 4),
        }

    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(DETAIL_PATH)
    print(SUMMARY_PATH)


if __name__ == "__main__":
    main()
