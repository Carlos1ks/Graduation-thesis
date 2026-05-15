from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import fitz  # noqa: E402

from pdf_parser import clean_text  # noqa: E402
from knowledge_graph import (  # noqa: E402
    _build_graph_from_extracted_payload,
    _extract_article_graph,
    _split_articles,
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _load_pdf_text(pdf_path: Path) -> tuple[str, int]:
    raw_parts: list[str] = []
    with fitz.open(str(pdf_path)) as doc:
        page_count = len(doc)
        for page in doc:
            raw_parts.append(page.get_text())
    return clean_text("\n".join(raw_parts)), page_count


def _clean_node(node: object) -> dict[str, object] | None:
    if not isinstance(node, dict):
        return None
    node_type = str(node.get("type") or "").strip().lower()
    node_id = str(node.get("id") or node.get("label") or "").strip()
    label = str(node.get("label") or node_id).strip()
    if not node_type or not node_id or not label:
        return None
    return {
        "type": node_type,
        "id": node_id,
        "label": label,
    }


def _clean_relation(rel: object, article_label: str) -> dict[str, object] | None:
    if not isinstance(rel, dict):
        return None
    rel_type = str(rel.get("type") or rel.get("relation") or "").strip().upper()
    source_type = str(rel.get("source_type") or rel.get("head_type") or "").strip().lower()
    target_type = str(rel.get("target_type") or rel.get("tail_type") or "").strip().lower()
    source_id = str(rel.get("source_id") or rel.get("head_id") or "").strip()
    target_id = str(rel.get("target_id") or rel.get("tail_id") or "").strip()
    if not rel_type or not source_type or not target_type or not source_id or not target_id:
        return None
    return {
        "source_id": source_id,
        "source_type": source_type,
        "target_id": target_id,
        "target_type": target_type,
        "type": rel_type,
        "condition": str(rel.get("condition") or "").strip(),
        "evidence": str(rel.get("evidence") or "").strip(),
        "article_label": article_label,
    }


def _skip_reason(article_label: str, text: str, planned_labels: set[str] | None = None) -> str:
    label = str(article_label or "").strip()
    content = str(text or "").strip()
    if not label or not content:
        return "empty_article"
    if not content.startswith(label):
        return "label_not_at_article_start"
    remainder = content[len(label):]
    if not remainder:
        return "label_only_fragment"
    if not remainder[0].isspace():
        return "citation_fragment"
    if re.match(r"^\s*规定[。．.]", remainder):
        return "citation_fragment"
    if planned_labels is not None and label not in planned_labels:
        return "not_in_current_article_list"
    return ""


def _skip_key(index: object, article_label: str, text: str) -> str:
    return f"{index}|{article_label}|{str(text or '').strip()[:80]}"


def _skip_record(index: object, article_label: str, text: str, reason: str) -> dict[str, object]:
    return {
        "index": index,
        "article_label": article_label,
        "reason": reason,
        "text_start": str(text or "").strip()[:220],
        "skipped_at": _now(),
    }


def _dedupe_skipped(items: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in items:
        key = _skip_key(item.get("index"), str(item.get("article_label") or ""), str(item.get("text_start") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _prepare_resume_payload(
    payload: dict[str, object],
    planned_labels: set[str],
) -> tuple[dict[tuple[str, str], dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    kept_articles: list[dict[str, object]] = []
    skipped = [item for item in payload.get("skipped_articles", []) if isinstance(item, dict)]
    skipped_keys = {
        _skip_key(item.get("index"), str(item.get("article_label") or ""), str(item.get("text_start") or ""))
        for item in skipped
    }

    node_map: dict[tuple[str, str], dict[str, object]] = {}
    relationships: list[dict[str, object]] = []
    for item in payload.get("articles", []):
        if not isinstance(item, dict):
            continue
        article_label = str(item.get("article_label") or "").strip()
        text = str(item.get("text") or "").strip()
        reason = _skip_reason(article_label, text, planned_labels)
        if reason:
            key = _skip_key(item.get("index"), article_label, text)
            if key not in skipped_keys:
                skipped.append(_skip_record(item.get("index"), article_label, text, reason))
                skipped_keys.add(key)
            continue

        clean_nodes: list[dict[str, object]] = []
        for node in item.get("nodes", []):
            clean = _clean_node(node)
            if not clean:
                continue
            node_map[(str(clean["type"]), str(clean["id"]))] = clean
            clean_nodes.append(clean)

        clean_relationships: list[dict[str, object]] = []
        for rel in item.get("relationships", []):
            clean_rel = _clean_relation(rel, article_label)
            if not clean_rel:
                continue
            relationships.append(clean_rel)
            clean_relationships.append(clean_rel)

        kept_articles.append({
            **item,
            "nodes": clean_nodes,
            "relationships": clean_relationships,
        })

    errors = [item for item in payload.get("errors", []) if isinstance(item, dict)]
    return node_map, relationships, kept_articles, _dedupe_skipped(skipped), errors


def _extract_article_graph_with_retry(doc_name: str, article_label: str, article_text: str, attempts: int = 3, base_delay: float = 2.5) -> dict[str, object]:
    last_exc: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return _extract_article_graph(doc_name, article_label, article_text)
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            sleep_seconds = base_delay * attempt
            print(
                f"[retry] {article_label} attempt {attempt}/{attempts} failed: {exc}; retrying in {sleep_seconds:.1f}s",
                flush=True,
            )
            time.sleep(sleep_seconds)
    if last_exc is not None:
        raise last_exc
    return {"nodes": [], "relationships": []}


def _save(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _initial_payload(pdf_path: Path, page_count: int, articles: list[dict[str, str]]) -> dict[str, object]:
    return {
        "doc_name": pdf_path.name,
        "source_pdf": str(pdf_path),
        "page_count": page_count,
        "article_count": len(articles),
        "extracted_article_count": 0,
        "created_at": _now(),
        "updated_at": _now(),
        "nodes": [],
        "relationships": [],
        "articles": [],
        "errors": [],
        "skipped_articles": [],
        "validation": {
            "uploadable": False,
            "node_count_after_sanitize": 0,
            "relation_count_after_sanitize": 0,
        },
    }


def _load_or_create_payload(path: Path, pdf_path: Path, page_count: int, articles: list[dict[str, str]], resume: bool) -> dict[str, object]:
    if resume and path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("nodes", [])
                payload.setdefault("relationships", [])
                payload.setdefault("articles", [])
                payload.setdefault("errors", [])
                payload.setdefault("skipped_articles", [])
                payload["doc_name"] = pdf_path.name
                payload["source_pdf"] = str(pdf_path)
                payload["page_count"] = page_count
                payload["article_count"] = len(articles)
                return payload
        except Exception:
            pass
    return _initial_payload(pdf_path, page_count, articles)


def _rebuild_node_map(payload: dict[str, object]) -> dict[tuple[str, str], dict[str, object]]:
    node_map: dict[tuple[str, str], dict[str, object]] = {}
    for node in payload.get("nodes", []):
        clean = _clean_node(node)
        if clean:
            node_map[(str(clean["type"]), str(clean["id"]))] = clean
    return node_map


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract regulation triples from a PDF with the existing KG LLM pipeline.")
    parser.add_argument("--pdf", required=True, help="PDF file path")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--limit", type=int, default=0, help="Optional article limit for debugging")
    parser.add_argument("--no-resume", action="store_true", help="Start from scratch even if output exists")
    parser.add_argument("--save-every", type=int, default=1, help="Save after this many processed articles")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).resolve()
    out_path = Path(args.out).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    text, page_count = _load_pdf_text(pdf_path)
    articles = _split_articles(text, pdf_path.stem)
    if args.limit and args.limit > 0:
        articles = articles[: args.limit]
    if not articles:
        raise RuntimeError("No articles found in PDF")

    payload = _load_or_create_payload(out_path, pdf_path, page_count, articles, resume=not args.no_resume)
    planned_labels = {
        str(article.get("article_label") or "").strip()
        for article in articles
        if str(article.get("article_label") or "").strip()
    }
    node_map, relationships, article_outputs, skipped_articles, errors = _prepare_resume_payload(payload, planned_labels)
    failed_labels = {
        str(item.get("article_label") or "").strip()
        for item in errors
        if str(item.get("article_label") or "").strip()
    }
    if failed_labels:
        kept_articles = [item for item in article_outputs if str(item.get("article_label") or "").strip() not in failed_labels]
        kept_labels = {
            str(item.get("article_label") or "").strip()
            for item in kept_articles
            if str(item.get("article_label") or "").strip()
        }
        node_map = {}
        relationships = []
        for item in kept_articles:
            article_label = str(item.get("article_label") or "").strip()
            for node in item.get("nodes", []):
                clean = _clean_node(node)
                if clean:
                    node_map[(str(clean["type"]), str(clean["id"]))] = clean
            for rel in item.get("relationships", []):
                clean_rel = _clean_relation(rel, article_label)
                if clean_rel:
                    relationships.append(clean_rel)
        article_outputs = kept_articles
        processed_labels = kept_labels
        errors = []
        payload.update({
            "updated_at": _now(),
            "extracted_article_count": len(processed_labels),
            "nodes": list(node_map.values()),
            "relationships": relationships,
            "articles": article_outputs,
            "skipped_articles": skipped_articles,
            "skipped_article_count": len(skipped_articles),
            "errors": errors,
        })
        _save(out_path, payload)
    processed_labels = {
        str(item.get("article_label") or "")
        for item in article_outputs
        if isinstance(item, dict) and str(item.get("article_label") or "").strip()
    }
    payload.update({
        "updated_at": _now(),
        "extracted_article_count": len(processed_labels),
        "skipped_article_count": len(skipped_articles),
        "nodes": list(node_map.values()),
        "relationships": relationships,
        "articles": article_outputs,
        "skipped_articles": skipped_articles,
        "errors": errors,
    })
    _save(out_path, payload)

    start_time = time.time()
    newly_processed = 0
    print(
        json.dumps(
            {
                "pdf": str(pdf_path),
                "out": str(out_path),
                "articles_total": len(articles),
                "articles_done": len(processed_labels),
                "resume": not args.no_resume,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    for index, article in enumerate(articles, start=1):
        article_label = str(article.get("article_label") or "").strip()
        article_text = str(article.get("text") or "").strip()
        if not article_label or article_label in processed_labels:
            continue

        reason = _skip_reason(article_label, article_text, planned_labels)
        if reason:
            skipped_articles.append(_skip_record(index, article_label, article_text, reason))
            payload.update({
                "updated_at": _now(),
                "extracted_article_count": len(processed_labels),
                "skipped_article_count": len(skipped_articles),
                "nodes": list(node_map.values()),
                "relationships": relationships,
                "articles": article_outputs,
                "skipped_articles": _dedupe_skipped(skipped_articles),
                "errors": errors,
            })
            _save(out_path, payload)
            print(f"[{index}/{len(articles)}] skipping {article_label}: {reason}", flush=True)
            continue

        print(f"[{index}/{len(articles)}] extracting {article_label}", flush=True)
        try:
            raw_payload = _extract_article_graph_with_retry(pdf_path.name, article_label, article_text)
            raw_nodes = raw_payload.get("nodes", []) if isinstance(raw_payload, dict) else []
            raw_relationships = raw_payload.get("relationships", []) if isinstance(raw_payload, dict) else []
        except Exception as exc:
            raw_nodes = []
            raw_relationships = []
            errors.append({
                "index": index,
                "article_label": article_label,
                "error": str(exc),
            })
            print(f"[{index}/{len(articles)}] ERROR {article_label}: {exc}", flush=True)

        clean_nodes: list[dict[str, object]] = []
        for node in raw_nodes:
            clean = _clean_node(node)
            if not clean:
                continue
            node_map.setdefault((str(clean["type"]), str(clean["id"])), clean)
            clean_nodes.append(clean)

        clean_relationships: list[dict[str, object]] = []
        for rel in raw_relationships:
            clean_rel = _clean_relation(rel, article_label)
            if not clean_rel:
                continue
            relationships.append(clean_rel)
            clean_relationships.append(clean_rel)

        article_outputs.append({
            "index": index,
            "article_label": article_label,
            "text": article_text,
            "nodes": clean_nodes,
            "relationships": clean_relationships,
        })
        processed_labels.add(article_label)
        newly_processed += 1

        payload.update({
            "updated_at": _now(),
            "extracted_article_count": len(processed_labels),
            "nodes": list(node_map.values()),
            "relationships": relationships,
            "articles": article_outputs,
            "skipped_articles": _dedupe_skipped(skipped_articles),
            "skipped_article_count": len(_dedupe_skipped(skipped_articles)),
            "errors": errors,
        })

        print(
            f"[{index}/{len(articles)}] {article_label}: nodes={len(clean_nodes)} rels={len(clean_relationships)} total_done={len(processed_labels)} elapsed={time.time() - start_time:.1f}s",
            flush=True,
        )
        if newly_processed % max(1, args.save_every) == 0:
            _save(out_path, payload)

    payload.update({
        "updated_at": _now(),
        "extracted_article_count": len(processed_labels),
        "nodes": list(node_map.values()),
        "relationships": relationships,
        "articles": article_outputs,
        "skipped_articles": _dedupe_skipped(skipped_articles),
        "skipped_article_count": len(_dedupe_skipped(skipped_articles)),
        "errors": errors,
    })
    try:
        graph = _build_graph_from_extracted_payload(payload, doc_name=out_path.name)
        payload["validation"] = {
            "uploadable": True,
            "node_count_after_sanitize": len(graph.get("nodes", [])),
            "relation_count_after_sanitize": len(graph.get("relations", [])),
        }
    except Exception as exc:
        payload["validation"] = {
            "uploadable": False,
            "error": str(exc),
            "node_count_after_sanitize": 0,
            "relation_count_after_sanitize": 0,
        }
    _save(out_path, payload)

    print(
        json.dumps(
            {
                "output": str(out_path),
                "article_count": payload["article_count"],
                "extracted_article_count": payload["extracted_article_count"],
                "raw_nodes": len(payload["nodes"]),
                "raw_relationships": len(payload["relationships"]),
                "errors": len(errors),
                "skipped": len(payload.get("skipped_articles", [])),
                "validation": payload["validation"],
                "seconds": round(time.time() - start_time, 1),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
