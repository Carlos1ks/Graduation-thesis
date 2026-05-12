"""会话级传感器数据存储与规范化。"""
from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional

from config import config

_DEFAULT_SESSION_ID = "default"
_SESSION_SENSOR_STORES: Dict[str, Dict[str, Any]] = {}
_STORE_LOCK = RLock()


def _get_session_id(session_id: Optional[str]) -> str:
    sid = str(session_id or "").strip()
    return sid or _DEFAULT_SESSION_ID


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _normalize_sensor_item(item: Dict[str, Any], idx: int = 0, source_type: str = "sensor_push") -> Dict[str, Any]:
    sensor_id = str(item.get("sensor_id") or item.get("sensorId") or item.get("id") or f"sensor-{idx + 1}").strip()
    name = str(item.get("name") or item.get("sensor_name") or item.get("sensorName") or sensor_id).strip() or sensor_id
    value = item.get("value")
    unit = str(item.get("unit") or "").strip()
    threshold = _to_float(item.get("threshold"))
    timestamp = str(item.get("timestamp") or item.get("time") or _now_iso()).strip()
    location = str(item.get("location") or item.get("area") or item.get("place") or "").strip()
    status = str(item.get("status") or item.get("state") or "").strip()

    value_float = _to_float(value)
    value_text = str(value).strip() if value is not None else ""

    normalized: Dict[str, Any] = {
        "sensor_id": sensor_id,
        "name": name,
        "value": value_float if value_float is not None else value_text,
        "value_text": value_text,
        "unit": unit,
        "threshold": threshold,
        "timestamp": timestamp,
        "location": location,
        "status": status,
        "source_type": source_type,
    }

    extras = {}
    for key in ("gateway_id", "device_id", "channel", "trend", "alarm_level", "alarm", "description"):
        if key in item and item.get(key) not in {None, ""}:
            extras[key] = item.get(key)
    if extras:
        normalized["extras"] = extras
    return normalized


def normalize_sensor_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("records") or payload.get("sensors") or payload.get("data") or []
    else:
        items = []

    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        normalized.append(_normalize_sensor_item(item, idx=idx))
    return normalized


def push_session_sensors(session_id: Optional[str], payload: Any) -> Dict[str, Any]:
    sid = _get_session_id(session_id)
    records = normalize_sensor_payload(payload)
    if not records:
        return {
            "session_id": sid,
            "sensor_count": 0,
            "latest_records": [],
        }

    with _STORE_LOCK:
        store = _SESSION_SENSOR_STORES.setdefault(sid, {
            "latest_by_sensor": {},
            "history": [],
            "updated_at": None,
        })
        for record in records:
            store["latest_by_sensor"][record["sensor_id"]] = record
            store["history"].append(record)
        store["history"] = store["history"][-200:]
        store["updated_at"] = _now_iso()

    return {
        "session_id": sid,
        "sensor_count": len(records),
        "latest_records": list_session_sensors(sid),
        "updated_at": _SESSION_SENSOR_STORES.get(sid, {}).get("updated_at"),
    }


def list_session_sensors(session_id: Optional[str]) -> List[Dict[str, Any]]:
    sid = _get_session_id(session_id)
    with _STORE_LOCK:
        store = _SESSION_SENSOR_STORES.get(sid) or {}
        latest = list((store.get("latest_by_sensor") or {}).values())
        latest.sort(key=lambda item: (str(item.get("timestamp") or ""), str(item.get("sensor_id") or "")))
        return latest


def has_session_sensors(session_id: Optional[str]) -> bool:
    sid = _get_session_id(session_id)
    with _STORE_LOCK:
        store = _SESSION_SENSOR_STORES.get(sid)
        return bool(store and store.get("latest_by_sensor"))


def clear_session_sensors(session_id: Optional[str]) -> bool:
    sid = _get_session_id(session_id)
    with _STORE_LOCK:
        return _SESSION_SENSOR_STORES.pop(sid, None) is not None
