"""煤矿应急多源风险融合。"""
from __future__ import annotations
# 这个模块负责把多源证据融合成“可解释的风险画像”。
# 后面的检索重排、图谱摘要和智能体路由都会复用这里的输出。

from typing import Dict, List, Optional

from config import config
from domain_schema import ACTION_DEFINITIONS, HAZARD_DEFINITIONS, SYMPTOM_DEFINITIONS


_SEVERE_SIGNAL_MIN_LEVEL = {
    "gas_overlimit": "中",
    "water_inrush": "中",
    "trapped": "高",
}

_LEVEL_ORDER = {"低": 0, "中": 1, "高": 2, "极高": 3}


_RISK_WEIGHTS = {
    "query": 3,
    "history": 2,
    "document": 2,
    "image": 2,
    "sensor": 3,
}


def _collect_texts(
    query: str,
    history: List[Dict[str, str]],
    documents: List[Dict[str, object]],
    images: List[Dict[str, str]],
    sensors: Optional[List[Dict[str, object]]] = None,
) -> Dict[str, str]:
    # 把不同来源的证据摊平成几类可比较的文本通道。
    sensor_lines = []
    for item in sensors or []:
        if not isinstance(item, dict):
            continue
        sensor_lines.append(
            "；".join([
                f"传感器={item.get('name') or item.get('sensor_id') or '未知'}",
                f"编号={item.get('sensor_id') or '未知'}",
                f"值={item.get('value_text') if item.get('value_text') not in {None, ''} else item.get('value') if item.get('value') not in {None, ''} else '未知'}{item.get('unit') or ''}",
                f"阈值={item.get('threshold') if item.get('threshold') not in {None, ''} else '未知'}",
                f"位置={item.get('location') or '未知'}",
                f"状态={item.get('status') or '未知'}",
                f"时间={item.get('timestamp') or '未知'}",
            ])
        )
    return {
        "query": str(query or ""),
        "history": "\n".join(str(item.get("content", "")) for item in history),
        "document": "\n".join(str(item.get("text", "")) for item in documents),
        "image": "\n".join(str(item.get("summary", "")) for item in images),
        "sensor": "\n".join(sensor_lines),
    }


def _contains_any(text: str, keywords: List[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _to_float(value):
    try:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _append_signal(signals: List[Dict[str, str]], seen: set, signal_id: str, source: str, keywords: str) -> None:
    key = (signal_id, source)
    if key in seen:
        return
    seen.add(key)
    label_map = {item: definition["label"] for item, definition in SYMPTOM_DEFINITIONS.items()}
    signals.append({
        "signal_id": signal_id,
        "signal_label": label_map.get(signal_id, signal_id),
        "source": source,
        "keywords": keywords,
    })


def _score_sensor_risks(sensors: Optional[List[Dict[str, object]]]) -> Dict[str, object]:
    # 传感器数据被视为强信号，因为它比纯文本描述更接近实时现场状态。
    hazard_scores = {hazard_id: 0 for hazard_id in HAZARD_DEFINITIONS}
    signals: List[Dict[str, str]] = []
    seen = set()
    abnormal_count = 0
    summary_lines: List[str] = []

    critical_status_keywords = ["超限", "报警", "警报", "异常", "critical", "alarm", "warning", "offline", "lost", "中断"]
    gas_keywords = ["瓦斯", "甲烷", "ch4", "CH4", "CH₄", "气体"]
    water_keywords = ["水位", "涌水", "突水", "透水", "积水", "排水"]
    fire_keywords = ["烟雾", "烟气", "明火", "高温", "温升", "火灾", "火源", "温度"]
    power_keywords = ["断电", "停电", "电压", "电流", "供电", "电源", "电气"]
    personnel_keywords = ["人员", "定位", "失联", "通信", "被困", "人数", "uwb", "UWB"]

    for idx, sensor in enumerate(sensors or []):
        if not isinstance(sensor, dict):
            continue
        name = str(sensor.get("name") or sensor.get("sensor_id") or f"sensor-{idx + 1}").strip()
        sensor_id = str(sensor.get("sensor_id") or name or f"sensor-{idx + 1}").strip()
        location = str(sensor.get("location") or "").strip()
        status = str(sensor.get("status") or "").strip()
        status_lower = status.lower()
        unit = str(sensor.get("unit") or "").strip()
        threshold = _to_float(sensor.get("threshold"))
        value = _to_float(sensor.get("value"))
        value_text = str(sensor.get("value_text") or sensor.get("value") or "").strip()
        text = " ".join(part for part in [name, sensor_id, location, status, unit, value_text] if part)
        summary_lines.append(
            f"{name}({sensor_id})={value_text or '未知'}{unit}，阈值={threshold if threshold is not None else '未知'}，位置={location or '未知'}，状态={status or '未知'}"
        )

        if _contains_any(text, gas_keywords):
            if value is not None:
                gas_limit = threshold if threshold is not None else 1.5
                if value >= gas_limit:
                    hazard_scores["gas"] += 4 if value >= max(gas_limit + 0.5, 2.0) else 3
                    _append_signal(signals, seen, "gas_overlimit", sensor_id, f"{value_text or value}{unit}")
                    abnormal_count += 1
                elif value >= max(1.0, gas_limit * 0.8):
                    hazard_scores["gas"] += 1
            elif any(keyword in status_lower for keyword in critical_status_keywords):
                hazard_scores["gas"] += 2
                _append_signal(signals, seen, "gas_overlimit", sensor_id, status or "异常")
                abnormal_count += 1

        if _contains_any(text, water_keywords):
            if value is not None:
                water_limit = threshold if threshold is not None else 0.0
                if value > water_limit:
                    hazard_scores["water"] += 3 if value > water_limit * 1.2 else 2
                    _append_signal(signals, seen, "water_inrush", sensor_id, f"{value_text or value}{unit}")
                    abnormal_count += 1
            elif any(keyword in status_lower for keyword in critical_status_keywords):
                hazard_scores["water"] += 2
                _append_signal(signals, seen, "water_inrush", sensor_id, status or "异常")
                abnormal_count += 1

        if _contains_any(text, fire_keywords):
            if any(keyword in text for keyword in ["烟雾", "烟气", "明火", "火灾", "火源"]):
                hazard_scores["fire"] += 2
                _append_signal(signals, seen, "smoke", sensor_id, "烟雾/明火")
                abnormal_count += 1
            elif value is not None and value >= (threshold if threshold is not None else 60.0):
                hazard_scores["fire"] += 1
                _append_signal(signals, seen, "smoke", sensor_id, f"{value_text or value}{unit}")
                abnormal_count += 1

        if _contains_any(text, power_keywords):
            if any(keyword in status_lower for keyword in critical_status_keywords) or (
                value is not None and threshold is not None and value < threshold
            ):
                hazard_scores["fire"] += 1
                _append_signal(signals, seen, "power_issue", sensor_id, status or f"{value_text or value}{unit}")
                abnormal_count += 1

        if _contains_any(text, personnel_keywords):
            if any(keyword in status_lower for keyword in critical_status_keywords + ["missing", "lost", "disconnect"]):
                hazard_scores["personnel"] += 3
                _append_signal(signals, seen, "trapped", sensor_id, status or "异常")
                abnormal_count += 1
            elif "人员" in text and ("失联" in text or "被困" in text or "通信" in text):
                hazard_scores["personnel"] += 2
                _append_signal(signals, seen, "trapped", sensor_id, status or "人员异常")
                abnormal_count += 1

    summary = "；".join(summary_lines[:5]) if summary_lines else "无传感器数据。"
    return {
        "hazard_scores": hazard_scores,
        "signals": signals,
        "summary": summary,
        "abnormal_count": abnormal_count,
        "sensor_count": len(sensors or []),
    }


def _score_hazards(texts: Dict[str, str]) -> Dict[str, int]:
    scores = {hazard_id: 0 for hazard_id in HAZARD_DEFINITIONS}
    for source_name, text in texts.items():
        if not text:
            continue
        weight = _RISK_WEIGHTS[source_name]
        for hazard_id, definition in HAZARD_DEFINITIONS.items():
            if any(keyword in text for keyword in definition["keywords"]):
                scores[hazard_id] += weight
    return scores


def _detect_signals(texts: Dict[str, str]) -> List[Dict[str, str]]:
    signals: List[Dict[str, str]] = []
    seen = set()
    for source_name, text in texts.items():
        if not text:
            continue
        for signal_id, definition in SYMPTOM_DEFINITIONS.items():
            hit_keywords = [keyword for keyword in definition["keywords"] if keyword in text]
            if not hit_keywords:
                continue
            key = (signal_id, source_name)
            if key in seen:
                continue
            seen.add(key)
            signals.append({
                "signal_id": signal_id,
                "signal_label": definition["label"],
                "source": source_name,
                "keywords": "、".join(hit_keywords[:3]),
            })
    return signals


def _risk_level(total_score: int, signals_count: int) -> str:
    critical = config.RISK_SCORE_THRESHOLDS.get("critical", 12)
    high = config.RISK_SCORE_THRESHOLDS.get("high", 8)
    medium = config.RISK_SCORE_THRESHOLDS.get("medium", 4)
    adjusted = total_score + max(0, signals_count - 1)
    if adjusted >= critical:
        return "极高"
    if adjusted >= high:
        return "高"
    if adjusted >= medium:
        return "中"
    return "低"


def _apply_signal_floor(level: str, signals: List[Dict[str, str]]) -> str:
    floored_level = level
    for signal in signals:
        min_level = _SEVERE_SIGNAL_MIN_LEVEL.get(signal.get("signal_id", ""))
        if min_level and _LEVEL_ORDER[min_level] > _LEVEL_ORDER[floored_level]:
            floored_level = min_level
    return floored_level


def _recommended_actions(risk_types: List[str]) -> List[str]:
    recommended: List[str] = []
    for action_id, definition in ACTION_DEFINITIONS.items():
        if action_id in {"stop_work", "cut_power", "evacuate", "ventilate", "report", "alert"} and risk_types:
            recommended.append(definition["label"])
    if any(risk_type in {"personnel", "fire", "water"} for risk_type in risk_types):
        recommended.append(ACTION_DEFINITIONS["rescue"]["label"])
    deduped: List[str] = []
    for item in recommended:
        if item not in deduped:
            deduped.append(item)
    return deduped[:6]


def _recommended_agents(risk_types: List[str], has_documents: bool, has_images: bool, has_sensors: bool = False) -> List[str]:
    agents = ["decision"]
    if risk_types or has_images or has_sensors:
        agents.append("perception")
    if has_documents or config.FORCE_KNOWLEDGE_ON_DECISION:
        agents.append("knowledge")
    if any(risk_type in {"fire", "water", "personnel"} for risk_type in risk_types):
        agents.append("coordination")
    ordered = []
    for role in ["perception", "knowledge", "decision", "coordination"]:
        if role in agents and role not in ordered:
            ordered.append(role)
    return ordered


def build_risk_profile(
    query: str,
    history: List[Dict[str, str]],
    documents: List[Dict[str, object]],
    images: List[Dict[str, str]],
    sensors: Optional[List[Dict[str, object]]] = None,
) -> Dict[str, object]:
    # 系统里统一使用的风险画像主入口。
    # 它返回的是结构化风险信息，而不是一个孤立标签，方便后续模块继续解释和复用。
    if not config.RISK_RULES_ENABLED:
        return {
            "enabled": False,
            "risk_level": "未知",
            "risk_types": [],
            "signals_detected": [],
            "evidence_basis": {},
            "recommended_agents": ["knowledge", "decision"],
            "recommended_actions_seed": [],
            "summary": "未启用风险识别。",
        }

    sensor_analysis = _score_sensor_risks(sensors)
    texts = _collect_texts(query, history, documents, images, sensors)
    hazard_scores = _score_hazards(texts)
    for hazard_id, score in sensor_analysis["hazard_scores"].items():
        hazard_scores[hazard_id] += score
    signals = _detect_signals(texts) + sensor_analysis["signals"]
    deduped_signals = []
    seen = set()
    for signal in signals:
        key = (signal.get("signal_id"), signal.get("source"))
        if key in seen:
            continue
        seen.add(key)
        deduped_signals.append(signal)
    signals = deduped_signals
    risk_types = [hazard_id for hazard_id, score in hazard_scores.items() if score > 0]
    risk_types_sorted = sorted(risk_types, key=lambda item: hazard_scores[item], reverse=True)
    total_score = sum(hazard_scores.values())
    level = _apply_signal_floor(_risk_level(total_score, len(signals)), signals)
    actions = _recommended_actions(risk_types_sorted)
    recommended_agents = _recommended_agents(risk_types_sorted, bool(documents), bool(images), bool(sensors))

    summary_lines = [
        f"风险等级：{level}",
        f"主要风险类型：{'、'.join(HAZARD_DEFINITIONS[item]['label'] for item in risk_types_sorted) if risk_types_sorted else '未识别'}",
    ]
    if signals:
        summary_lines.append(
            "触发信号：" + "；".join(
                f"{signal['signal_label']}（来源：{signal['source']}；命中：{signal['keywords']}）"
                for signal in signals[:5]
            )
        )
    if actions:
        summary_lines.append("建议动作种子：" + "、".join(actions))
    if sensor_analysis["summary"] != "无传感器数据。":
        summary_lines.append("传感器数据：" + sensor_analysis["summary"])

    return {
        "enabled": True,
        "risk_level": level,
        "risk_types": risk_types_sorted,
        "risk_type_labels": [HAZARD_DEFINITIONS[item]["label"] for item in risk_types_sorted],
        "signals_detected": signals,
        "evidence_basis": {
            "has_history": bool(history),
            "document_count": len(documents),
            "image_count": len(images),
            "sensor_count": sensor_analysis["sensor_count"],
            "sensor_abnormal_count": sensor_analysis["abnormal_count"],
            "hazard_scores": hazard_scores,
        },
        "recommended_agents": recommended_agents,
        "recommended_actions_seed": actions,
        "summary": "\n".join(summary_lines),
    }
