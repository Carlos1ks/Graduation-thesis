"""Strict multi-model vision benchmark for an OpenAI-compatible proxy.

Examples:
    python tools/test_oneais_vision.py ^
      --images "c:\\self\\Draft_py\\煤矿突水.png" "c:\\self\\Draft_py\\巷道电路起火.png" ^
      --models gpt-5.4-mini gpt-5.5 ^
      --api-key sk-...

    $env:ONEAIS_API_KEY="sk-..."
    python tools/test_oneais_vision.py --images "c:\\self\\Draft_py\\*.png"

    python tools/test_oneais_vision.py ^
      --analyze-report tools\\reports\\oneais-vision-report-20260517-121246.json
"""

from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import requests


DEFAULT_BASE_URL = "https://api.oneais.dev/v1"
DEFAULT_MODELS = ["gpt-5.4-mini", "gpt-5.5", "gpt-5.4", "gpt-5.2"]
DEFAULT_PROMPT = (
    "你是煤矿安全应急图像识别助手。"
    "请严格只做煤矿场景判断，不要回答数学题、翻译题、闲聊或与图片无关的内容。"
    "请使用中文，并只返回 JSON，格式为："
    "{\"keywords\":[\"关键词1\",\"关键词2\",\"关键词3\"],"
    "\"summary\":\"一句不超过30字的中文摘要\","
    "\"risk_level\":\"低/中/高/极高/未识别\"}。"
    "若图片无法判断，请返回 keywords 为空数组，summary 写“未识别”，risk_level 写“未识别”。"
)
ALLOWED_RISK_LEVELS = ("低", "中", "高", "极高", "未识别")
EXPECTED_KEYS = ("keywords", "summary", "risk_level")
REPORT_DIR = Path(__file__).resolve().parent / "reports"


def configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def encode_image(image_path: Path) -> str:
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


def guess_mime_type(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "image/png"


def expand_image_args(image_args: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for raw in image_args:
        if any(ch in raw for ch in ["*", "?"]):
            paths.extend(sorted(Path(item) for item in glob.glob(raw)))
        else:
            paths.append(Path(raw))
    resolved = []
    for path in paths:
        p = path.expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Image not found: {p}")
        resolved.append(p)
    if not resolved:
        raise FileNotFoundError("No images matched the given --images arguments.")
    return resolved


def extract_message_content(data: dict[str, Any]) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
        return str(content or "")
    except Exception:
        return ""


def detect_off_topic(text: str) -> bool:
    lowered = str(text or "").lower()
    bad_tokens = [
        "missing number",
        "step by step",
        "if you want",
        "translate",
        "math",
        "yes —",
        "yes -",
        "это",
        "если",
        "тоннель метро",
    ]
    if any(token in lowered for token in bad_tokens):
        return True
    return not any("\u4e00" <= ch <= "\u9fff" for ch in lowered)


def parse_structured_output(text: str) -> tuple[dict[str, Any] | None, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return None, "empty response content"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"{exc.msg} at line {exc.lineno}, column {exc.colno}"
    if not isinstance(payload, dict):
        return None, f"expected JSON object, got {type(payload).__name__}"
    return payload, None


def validate_structured_output(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    missing = [key for key in EXPECTED_KEYS if key not in payload]
    if missing:
        issues.append(f"missing keys: {', '.join(missing)}")

    keywords = payload.get("keywords")
    if not isinstance(keywords, list) or not all(isinstance(item, str) for item in keywords):
        issues.append("keywords must be a list of strings")

    summary = payload.get("summary")
    if not isinstance(summary, str):
        issues.append("summary must be a string")
    elif len(summary) > 30:
        issues.append(f"summary exceeds 30 chars ({len(summary)})")

    risk_level = payload.get("risk_level")
    if risk_level not in ALLOWED_RISK_LEVELS:
        issues.append(f"risk_level must be one of: {', '.join(ALLOWED_RISK_LEVELS)}")

    return issues


def enrich_result(result: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(result)
    content = str(enriched.get("message_content") or "")
    http_ok = bool(enriched.get("ok"))
    off_topic = bool(enriched.get("off_topic")) if "off_topic" in enriched else detect_off_topic(content)
    parsed_output, parse_error = parse_structured_output(content)
    validation_errors = validate_structured_output(parsed_output) if parsed_output else []
    schema_ok = parsed_output is not None and not validation_errors

    enriched["message_content"] = content
    enriched["off_topic"] = off_topic
    enriched["parsed_output"] = parsed_output
    enriched["parse_error"] = parse_error
    enriched["validation_errors"] = validation_errors
    enriched["schema_ok"] = schema_ok
    enriched["strict_ok"] = http_ok and (not off_topic) and schema_ok
    return enriched


def run_single_request(image_path: Path, model: str, base_url: str, api_key: str, prompt: str) -> dict[str, Any]:
    image_b64 = encode_image(image_path)
    mime_type = guess_mime_type(image_path)

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_b64}"
                        },
                    },
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 300,
    }

    url = base_url.rstrip("/") + "/chat/completions"
    started = time.perf_counter()
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    elapsed = round(time.perf_counter() - started, 3)

    try:
        data = response.json()
    except Exception:
        data = {"raw_text": response.text}

    return enrich_result(
        {
            "image": str(image_path),
            "model": model,
            "http_status": response.status_code,
            "latency_s": elapsed,
            "ok": response.ok,
            "message_content": extract_message_content(data),
            "response_json": data,
        }
    )


def normalize_results(results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in results:
        if {"parsed_output", "schema_ok", "strict_ok", "validation_errors", "parse_error"} <= set(item):
            normalized.append(dict(item))
        else:
            normalized.append(enrich_result(item))
    return normalized


def build_summary(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    normalized = normalize_results(results)
    total = len(normalized)
    latency_values = [float(item.get("latency_s") or 0.0) for item in normalized if item.get("latency_s") is not None]

    per_model: dict[str, dict[str, Any]] = {}
    grouped_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_by_image: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in normalized:
        grouped_by_model[str(item.get("model") or "<unknown>")].append(item)
        image_name = Path(str(item.get("image") or "<unknown>")).name
        grouped_by_image[image_name].append(item)

    for model, items in grouped_by_model.items():
        risk_counter: Counter[str] = Counter()
        for item in items:
            parsed = item.get("parsed_output") or {}
            risk_level = parsed.get("risk_level")
            if isinstance(risk_level, str):
                risk_counter[risk_level] += 1

        per_model[model] = {
            "requests": len(items),
            "http_ok": sum(1 for item in items if item.get("ok")),
            "strict_ok": sum(1 for item in items if item.get("strict_ok")),
            "off_topic": sum(1 for item in items if item.get("off_topic")),
            "parse_ok": sum(1 for item in items if item.get("parse_error") is None),
            "schema_ok": sum(1 for item in items if item.get("schema_ok")),
            "avg_latency_s": round(
                sum(float(item.get("latency_s") or 0.0) for item in items) / len(items),
                3,
            ),
            "risk_levels": dict(risk_counter),
        }

    per_image: dict[str, list[dict[str, Any]]] = {}
    for image_name, items in grouped_by_image.items():
        sorted_items = sorted(items, key=lambda item: str(item.get("model") or ""))
        per_image[image_name] = [
            {
                "model": item.get("model"),
                "risk_level": (item.get("parsed_output") or {}).get("risk_level", "未识别"),
                "summary": (item.get("parsed_output") or {}).get("summary", item.get("message_content", "")),
                "strict_ok": bool(item.get("strict_ok")),
                "latency_s": item.get("latency_s"),
            }
            for item in sorted_items
        ]

    return {
        "total_requests": total,
        "http_ok_count": sum(1 for item in normalized if item.get("ok")),
        "strict_ok_count": sum(1 for item in normalized if item.get("strict_ok")),
        "off_topic_count": sum(1 for item in normalized if item.get("off_topic")),
        "parse_ok_count": sum(1 for item in normalized if item.get("parse_error") is None),
        "schema_ok_count": sum(1 for item in normalized if item.get("schema_ok")),
        "avg_latency_s": round(sum(latency_values) / len(latency_values), 3) if latency_values else None,
        "per_model": per_model,
        "per_image": per_image,
    }


def format_risk_levels(risk_levels: dict[str, int]) -> str:
    if not risk_levels:
        return "-"
    ordered = [level for level in ALLOWED_RISK_LEVELS if level in risk_levels]
    extras = [level for level in risk_levels if level not in ALLOWED_RISK_LEVELS]
    return ", ".join(f"{level}:{risk_levels[level]}" for level in [*ordered, *extras])


def build_markdown_summary(report_name: str, summary: dict[str, Any]) -> str:
    lines = [
        "# Vision Benchmark Summary",
        "",
        f"Source report: `{report_name}`",
        "",
        f"- Total requests: {summary['total_requests']}",
        f"- HTTP OK: {summary['http_ok_count']}",
        f"- Strict OK: {summary['strict_ok_count']}",
        f"- Parse OK: {summary['parse_ok_count']}",
        f"- Schema OK: {summary['schema_ok_count']}",
        f"- Off-topic: {summary['off_topic_count']}",
        f"- Avg latency: {summary['avg_latency_s']}s" if summary["avg_latency_s"] is not None else "- Avg latency: n/a",
        "",
        "## Model Summary",
        "",
        "| Model | Strict OK | HTTP OK | Parse OK | Schema OK | Off-topic | Avg latency (s) | Risk levels |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    for model, stats in summary["per_model"].items():
        lines.append(
            "| {model} | {strict_ok}/{requests} | {http_ok}/{requests} | {parse_ok}/{requests} | "
            "{schema_ok}/{requests} | {off_topic} | {avg_latency_s} | {risk_levels} |".format(
                model=model,
                strict_ok=stats["strict_ok"],
                requests=stats["requests"],
                http_ok=stats["http_ok"],
                parse_ok=stats["parse_ok"],
                schema_ok=stats["schema_ok"],
                off_topic=stats["off_topic"],
                avg_latency_s=stats["avg_latency_s"],
                risk_levels=format_risk_levels(stats["risk_levels"]),
            )
        )

    lines.extend(["", "## Image Comparison", ""])
    for image_name, items in summary["per_image"].items():
        lines.extend(
            [
                f"### {image_name}",
                "",
                "| Model | Risk level | Summary | Strict OK | Latency (s) |",
                "| --- | --- | --- | ---: | ---: |",
            ]
        )
        for item in items:
            lines.append(
                f"| {item['model']} | {item['risk_level']} | {item['summary']} | "
                f"{'yes' if item['strict_ok'] else 'no'} | {item['latency_s']} |"
            )
        lines.append("")

    return "\n".join(lines)


def print_result(result: dict[str, Any]) -> None:
    print("=" * 72)
    print(f"IMAGE : {Path(result['image']).name}")
    print(f"MODEL : {result['model']}")
    print(
        "HTTP  : {http_status} | latency={latency_s}s | off_topic={off_topic} | "
        "schema_ok={schema_ok} | strict_ok={strict_ok}".format(**result)
    )
    if result["parse_error"]:
        print(f"PARSE : {result['parse_error']}")
    elif result["validation_errors"]:
        print(f"VALID : {'; '.join(result['validation_errors'])}")
    print("OUTPUT :")
    print(result["message_content"] or "<empty>")


def print_summary(summary: dict[str, Any]) -> None:
    print("=" * 72)
    avg_latency = f"{summary['avg_latency_s']}s" if summary["avg_latency_s"] is not None else "n/a"
    print(
        f"TOTAL : strict_ok={summary['strict_ok_count']}/{summary['total_requests']} | "
        f"http_ok={summary['http_ok_count']} | parse_ok={summary['parse_ok_count']} | "
        f"schema_ok={summary['schema_ok_count']} | off_topic={summary['off_topic_count']} | "
        f"avg_latency={avg_latency}"
    )
    for model, stats in summary["per_model"].items():
        print(
            f"MODEL : {model} | strict_ok={stats['strict_ok']}/{stats['requests']} | "
            f"avg_latency={stats['avg_latency_s']}s | risks={format_risk_levels(stats['risk_levels'])}"
        )


def load_report(report_path: Path) -> dict[str, Any]:
    return json.loads(report_path.read_text(encoding="utf-8"))


def save_markdown_summary(report_path: Path, markdown_out: str | None, summary: dict[str, Any]) -> Path:
    if markdown_out:
        output_path = Path(markdown_out).expanduser().resolve()
    else:
        output_path = report_path.with_suffix(".md")
    output_path.write_text(
        build_markdown_summary(report_path.name, summary),
        encoding="utf-8",
    )
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strict OpenAI-compatible multi-model vision benchmark.")
    parser.add_argument(
        "--images",
        nargs="+",
        help="Image paths or glob patterns, e.g. c:\\self\\Draft_py\\*.png",
    )
    parser.add_argument(
        "--analyze-report",
        help="Analyze an existing report JSON without making API calls.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=DEFAULT_MODELS,
        help=f"Model list (default: {' '.join(DEFAULT_MODELS)})",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--api-key", default=os.environ.get("ONEAIS_API_KEY", ""), help="API key; or set ONEAIS_API_KEY")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Strict vision prompt")
    parser.add_argument("--print-json", action="store_true", help="Print full response JSON for each run")
    parser.add_argument("--markdown-out", help="Optional output path for the markdown summary.")
    args = parser.parse_args()

    if bool(args.images) == bool(args.analyze_report):
        parser.error("Pass either --images or --analyze-report.")
    return args


def analyze_existing_report(report_path: Path, markdown_out: str | None) -> int:
    report = load_report(report_path)
    results = normalize_results(report.get("results", []))
    summary = build_summary(results)
    markdown_path = save_markdown_summary(report_path, markdown_out, summary)

    print_summary(summary)
    print(f"Analyzed report: {report_path}")
    print(f"Saved summary: {markdown_path}")

    failed = [item for item in results if not item["strict_ok"]]
    return 1 if failed else 0


def benchmark_images(args: argparse.Namespace) -> int:
    if not args.api_key:
        raise SystemExit("Missing API key. Pass --api-key or set ONEAIS_API_KEY.")

    images = expand_image_args(args.images)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for image_path in images:
        for model in args.models:
            result = run_single_request(image_path, model, args.base_url, args.api_key, args.prompt)
            results.append(result)
            print_result(result)
            if args.print_json:
                print("RAW JSON:")
                print(json.dumps(result["response_json"], ensure_ascii=False, indent=2))

    summary = build_summary(results)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    report_path = REPORT_DIR / f"oneais-vision-report-{timestamp}.json"
    report_path.write_text(
        json.dumps(
            {
                "base_url": args.base_url,
                "models": args.models,
                "images": [str(p) for p in images],
                "prompt": args.prompt,
                "summary": summary,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    markdown_path = save_markdown_summary(report_path, args.markdown_out, summary)

    print_summary(summary)
    print(f"Saved report: {report_path}")
    print(f"Saved summary: {markdown_path}")

    failed = [item for item in results if not item["strict_ok"]]
    return 1 if failed else 0


def main() -> int:
    configure_stdio()
    args = parse_args()

    if args.analyze_report:
        report_path = Path(args.analyze_report).expanduser().resolve()
        if not report_path.exists():
            raise SystemExit(f"Report not found: {report_path}")
        return analyze_existing_report(report_path, args.markdown_out)

    return benchmark_images(args)


if __name__ == "__main__":
    raise SystemExit(main())
