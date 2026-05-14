from flask import Flask, request, jsonify
from flask_cors import CORS
import fitz  # PyMuPDF
from docx import Document as DocxDocument
import re
import os
import tempfile
import requests
import base64
from pathlib import Path
from config import config
from retrieval import (
    ingest_document,
    retrieve_relevant_chunks,
    has_session_documents,
    remove_document,
    list_session_chunks,
)
from sensor_store import push_session_sensors, list_session_sensors, has_session_sensors, clear_session_sensors
from knowledge_graph import (
    build_and_store_session_graph,
    get_session_graph,
    query_graph,
    query_centered_graph,
    clear_session_graph,
    expand_graph_neighbors,
    start_graph_build,
    get_graph_build_status,
)

# LangChain Agent
from agent import multi_agent_ask

app = Flask(__name__)

# 更明确的CORS配置
CORS(
    app,
    origins=config.CORS_ORIGINS,
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "OPTIONS"],
)


def _graph_payload(graph):
    stats = graph.get("stats") if isinstance(graph, dict) else {}
    return {
        "node_count": int((stats or {}).get("node_count") or len(graph.get("nodes", []))),
        "relation_count": int((stats or {}).get("relation_count") or len(graph.get("relations", []))),
        "stats": stats or {},
    }


def _rebuild_session_knowledge_graph(session_id):
    chunks = list_session_chunks(session_id)
    graph = build_and_store_session_graph(session_id, chunks)
    return graph

# Token缓存
_token_cache = {"token": None, "expires_at": 0}

def clean_text(text):
    """清洗PDF提取的文本"""
    # 1. 删除页眉页脚
    text = text.replace('应急管理部规章', '').replace('应急管理部发布', '')

    # 2. 删除页码 "- 数字 -"
    text = re.sub(r'-\s*\d+\s*-', '', text)

    # 3. 修复断句问题 - 非句末的换行改为空格
    text = re.sub(r'(?<![。；？！])\n', ' ', text)

    # 4. 规范化空格
    text = re.sub(r'\s+', ' ', text).strip()

    # 5. 确保"第"和条号之间没有多余空格
    text = re.sub(r'第\s+([一二三四五六七八九十百千万\d]+)\s*条', r'第\1条', text)

    return text


def _clip_text(text, max_len):
    text = str(text or "").strip()
    if len(text) <= max_len:
        return text
    head = max_len // 2
    tail = max_len - head
    return f"{text[:head]}\n...(中间已省略)...\n{text[-tail:]}"


def _normalize_history(history):
    if not isinstance(history, list):
        return []

    normalized = []
    max_messages = max(2, config.AGENT_MAX_HISTORY_TURNS * 2)
    for item in history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append({
            "role": role,
            "content": _clip_text(content, 600),
        })

    return normalized[-max_messages:]


def _normalize_document_evidence(documents):
    if not isinstance(documents, list):
        return []

    normalized = []
    for idx, item in enumerate(documents[:config.AGENT_MAX_EVIDENCE_DOCUMENTS]):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        doc_name = str(item.get("doc_name") or item.get("docName") or "未命名文档").strip() or "未命名文档"
        chunk_id = str(item.get("chunk_id") or item.get("chunkId") or f"{doc_name}:{idx}").strip()
        score = item.get("score")
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            score = None
        normalized.append({
            "doc_name": doc_name,
            "chunk_id": chunk_id,
            "text": _clip_text(text, 900),
            "score": score,
            "source_type": str(item.get("source_type") or "uploaded_doc"),
        })

    return normalized


def _normalize_image_evidence(images):
    if not isinstance(images, list):
        return []

    normalized = []
    for item in images[:config.AGENT_MAX_EVIDENCE_IMAGES]:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary", "")).strip()
        if not summary:
            continue
        normalized.append({
            "image_name": str(item.get("image_name") or item.get("imageName") or "未命名图片").strip() or "未命名图片",
            "summary": _clip_text(summary, 300),
            "source_type": str(item.get("source_type") or "image_analysis"),
        })

    return normalized


def _normalize_sensor_evidence(sensors):
    if not isinstance(sensors, list):
        return []

    normalized = []
    for idx, item in enumerate(sensors[:20]):
        if not isinstance(item, dict):
            continue
        sensor_id = str(item.get("sensor_id") or item.get("sensorId") or item.get("id") or f"sensor-{idx + 1}").strip()
        name = str(item.get("name") or item.get("sensor_name") or item.get("sensorName") or sensor_id).strip() or sensor_id
        value = item.get("value")
        unit = str(item.get("unit") or "").strip()
        threshold = item.get("threshold")
        timestamp = str(item.get("timestamp") or item.get("time") or "").strip()
        location = str(item.get("location") or item.get("area") or item.get("place") or "").strip()
        status = str(item.get("status") or item.get("state") or "").strip()
        source_type = str(item.get("source_type") or "sensor").strip() or "sensor"

        normalized.append({
            "sensor_id": sensor_id,
            "name": name,
            "value": value,
            "value_text": str(value).strip() if value is not None else "",
            "unit": unit,
            "threshold": threshold,
            "timestamp": timestamp,
            "location": location,
            "status": status,
            "source_type": source_type,
        })
    return normalized


def _normalize_agent_chat_request(data):
    payload = data if isinstance(data, dict) else {}
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}

    return {
        "query": str(payload.get("query", "")).strip(),
        "session_id": str(payload.get("session_id", "")).strip() or None,
        "history": _normalize_history(payload.get("history")),
        "evidence_documents": _normalize_document_evidence(evidence.get("documents")),
        "evidence_images": _normalize_image_evidence(evidence.get("images")),
        "evidence_sensors": _normalize_sensor_evidence(evidence.get("sensors")),
        "options": options,
    }

def _extract_pdf_text(file_storage):
    pdf_data = file_storage.read()
    doc = fitz.open(stream=pdf_data, filetype="pdf")
    full_text = ""
    for page_num in range(len(doc)):
        page = doc[page_num]
        full_text += page.get_text() + "\n"
    cleaned_text = clean_text(full_text)
    return {
        "text": cleaned_text,
        "char_count": len(cleaned_text),
        "page_count": len(doc),
    }


def _extract_docx_text(file_storage):
    doc = DocxDocument(file_storage)
    text = "\n".join([para.text for para in doc.paragraphs])
    return {
        "text": text,
        "char_count": len(text),
    }


def _extract_plain_text(file_storage):
    text = file_storage.read().decode('utf-8', errors='ignore')
    return {
        "text": text,
        "char_count": len(text),
    }


def _extract_text_from_upload(file_storage):
    filename = str(getattr(file_storage, "filename", "") or "").lower()
    if filename.endswith('.pdf'):
        return _extract_pdf_text(file_storage)
    if filename.endswith('.docx'):
        return _extract_docx_text(file_storage)
    if filename.endswith('.txt'):
        return _extract_plain_text(file_storage)
    raise ValueError('不支持的文件格式，请上传 TXT、DOCX 或 PDF')


def _analyze_baidu_image_base64(img_base64, image_name="image"):
    image_data = str(img_base64 or "").strip()
    if not image_data:
        raise ValueError("Empty image data")

    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    access_token = get_baidu_access_token()
    api_url = f"{config.BAIDU_IMAGE_ANALYZE_URL}?access_token={access_token}"
    payload = {"image": image_data}

    resp = requests.post(
        api_url,
        data=payload,
        timeout=15
    )
    resp.raise_for_status()
    result = resp.json()

    if "error_code" in result and result["error_code"] != 0:
        raise RuntimeError(result.get("error_msg", "Baidu API error"))

    if "result" not in result:
        result["result"] = []
    return result


def _extract_image_keywords(result, limit=3):
    keywords = []
    items = result.get("result", []) if isinstance(result, dict) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        keyword = item.get("keyword") or item.get("class_name")
        if not keyword:
            continue
        keyword = str(keyword).strip()
        if keyword and keyword not in keywords:
            keywords.append(keyword)
        if len(keywords) >= limit:
            break
    return keywords


def _load_cv2():
    try:
        import cv2
    except Exception as exc:
        raise RuntimeError("缺少 opencv-python-headless，无法分析视频。") from exc
    return cv2


def _resize_video_frame(frame, cv2):
    if frame is None:
        return frame
    height, width = frame.shape[:2]
    max_width = max(320, int(config.VIDEO_FRAME_MAX_WIDTH))
    if width <= max_width:
        return frame
    scale = max_width / float(width)
    new_height = max(1, int(height * scale))
    return cv2.resize(frame, (max_width, new_height), interpolation=cv2.INTER_AREA)


def _sample_video_positions(total_frames, fps, max_frames):
    if total_frames <= 0:
        return [0]

    max_frames = max(1, int(max_frames))
    if fps and fps > 0:
        step = max(1, int(round(float(config.VIDEO_SAMPLE_SECONDS) * fps)))
    else:
        step = max(1, total_frames // max_frames)

    positions = list(range(0, total_frames, step))
    if positions and positions[-1] != total_frames - 1:
        positions.append(total_frames - 1)

    positions = sorted(set(pos for pos in positions if pos >= 0))
    if len(positions) > max_frames:
        stride = max(1, len(positions) // max_frames)
        positions = positions[::stride]
        if positions and positions[-1] != total_frames - 1:
            positions.append(total_frames - 1)
        positions = sorted(set(positions))[:max_frames]
    return positions[:max_frames]


def _format_video_timestamp(seconds):
    if seconds is None:
        return "未知时刻"
    total = max(0, int(round(float(seconds))))
    minute, second = divmod(total, 60)
    hour, minute = divmod(minute, 60)
    if hour > 0:
        return f"{hour:02d}:{minute:02d}:{second:02d}"
    return f"{minute:02d}:{second:02d}"


def _extract_video_frames(video_path):
    cv2 = _load_cv2()
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError("无法打开视频文件。")

    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration_s = float(total_frames / fps) if fps > 0 else 0.0
        positions = _sample_video_positions(total_frames or 1, fps, config.VIDEO_MAX_FRAMES)

        frames = []
        for position in positions:
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(position))
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            frame = _resize_video_frame(frame, cv2)
            ok, buffer = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), int(config.VIDEO_JPEG_QUALITY)],
            )
            if not ok:
                continue
            image_base64 = base64.b64encode(buffer.tobytes()).decode("utf-8")
            timestamp_s = float(position / fps) if fps > 0 else float(len(frames))
            frames.append({
                "frame_index": int(position),
                "timestamp_s": timestamp_s,
                "image_base64": image_base64,
            })

        return {
            "fps": fps,
            "total_frames": total_frames,
            "duration_s": duration_s,
            "frames": frames,
        }
    finally:
        capture.release()


def _build_video_analysis_response(video_name, extracted, frame_reports):
    keywords = []
    evidence = []
    detail_lines = []

    for item in frame_reports:
        item_keywords = list(item.get("keywords") or [])
        for keyword in item_keywords:
            if keyword not in keywords:
                keywords.append(keyword)
        evidence.append({
            "image_name": f"{video_name} · {item.get('timestamp_label', '未知时刻')}",
            "summary": "、".join(item_keywords[:3]) or "未识别到明显异常",
            "source_type": "video_analysis",
            "timestamp_s": round(float(item.get("timestamp_s") or 0.0), 2),
            "frame_index": int(item.get("frame_index") or 0),
        })
        detail_lines.append(
            f"- {item.get('timestamp_label', '未知时刻')}：{'、'.join(item_keywords[:3]) or '未识别到明显异常'}"
        )

    if keywords:
        issue_text = "、".join(keywords[:5])
    else:
        issue_text = "未识别到明显异常"

    summary_lines = [
        f"🎬 视频《{video_name}》分析完成。",
        f"时长：{float(extracted.get('duration_s') or 0.0):.1f}s，抽取关键帧：{len(extracted.get('frames') or [])} 张。",
        f"疑似问题：{issue_text}",
    ]
    if detail_lines:
        summary_lines.append("关键片段：")
        summary_lines.extend(detail_lines[:6])
    else:
        summary_lines.append("未发现明显异常画面，建议结合现场问题继续研判。")

    return {
        "success": True,
        "video_name": video_name,
        "duration_s": round(float(extracted.get("duration_s") or 0.0), 2),
        "fps": round(float(extracted.get("fps") or 0.0), 2),
        "total_frames": int(extracted.get("total_frames") or 0),
        "frames_extracted": len(extracted.get("frames") or []),
        "frames_matched": len(frame_reports),
        "issue_keywords": keywords[:10],
        "summary_text": "\n".join(summary_lines),
        "evidence": evidence,
    }


@app.route('/api/parse-pdf', methods=['POST'])
def parse_pdf():
    """处理PDF文件上传"""
    if 'file' not in request.files:
        return jsonify({'error': '未找到文件'}), 400

    file = request.files['file']

    try:
        result = _extract_pdf_text(file)
        return jsonify({
            'success': True,
            'text': result['text'],
            'char_count': result['char_count'],
            'page_count': result['page_count'],
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/parse-docx', methods=['POST'])
def parse_docx():
    """处理DOCX文件"""
    if 'file' not in request.files:
        return jsonify({'error': '未找到文件'}), 400

    file = request.files['file']

    try:
        result = _extract_docx_text(file)
        return jsonify({
            'success': True,
            'text': result['text'],
            'char_count': result['char_count'],
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/parse-text', methods=['POST'])
def parse_text():
    """处理TXT文件"""
    if 'file' not in request.files:
        return jsonify({'error': '未找到文件'}), 400

    file = request.files['file']

    try:
        result = _extract_plain_text(file)
        return jsonify({
            'success': True,
            'text': result['text'],
            'char_count': result['char_count'],
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/documents/upload', methods=['POST'])
def upload_document():
    """统一文档入库接口：解析文本后建立后端向量索引，并异步构建图谱。"""
    if 'file' not in request.files:
        return jsonify({'error': '未找到文件'}), 400

    file = request.files['file']
    session_id = str(request.form.get('session_id', '')).strip() or None

    try:
        parsed = _extract_text_from_upload(file)
        result = ingest_document(
            session_id=session_id,
            file_name=str(getattr(file, 'filename', '') or '未命名文档'),
            text=parsed['text'],
        )
        build_status = start_graph_build(session_id, list_session_chunks(session_id))
        return jsonify({
            'success': True,
            **result,
            "knowledge_graph": {
                "build_status": build_status,
            },
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/documents/remove', methods=['POST'])
def remove_uploaded_document():
    """移除当前会话中的已入库文档。"""
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get('session_id', '')).strip() or None
    document_id = str(payload.get('document_id', '')).strip()

    if not document_id:
        return jsonify({'error': 'document_id不能为空'}), 400

    removed = remove_document(session_id=session_id, document_id=document_id)
    if not removed:
        return jsonify({'error': '未找到对应文档'}), 404
    if not list_session_chunks(session_id):
        clear_session_graph(session_id)
    return jsonify({
        'success': True,
        'document_id': document_id,
        "knowledge_graph": {
            "build_status": get_graph_build_status(session_id),
        },
    })


@app.route('/api/knowledge-graph', methods=['GET'])
def get_knowledge_graph():
    """获取当前会话完整知识图谱。"""
    session_id = str(request.args.get('session_id', '')).strip() or None
    keyword = str(request.args.get('keyword', '')).strip()
    limit = request.args.get('limit', 160)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 160

    if keyword:
        view = query_centered_graph(session_id=session_id, keyword=keyword, limit=limit)
        stats = view.get("stats", {})
    else:
        graph = get_session_graph(session_id)
        compact_view = query_graph(graph, limit=limit)
        all_links = compact_view.get("links", []) if isinstance(compact_view, dict) else []
        safe_limit = max(50, min(int(limit or 1000), 2000))
        visible_links = all_links[:safe_limit]
        visible_uids = {str(link.get("source")) for link in visible_links} | {str(link.get("target")) for link in visible_links}
        view = {
            "nodes": [node for node in compact_view.get("nodes", []) if str(node.get("uid")) in visible_uids],
            "links": visible_links,
            "relations": visible_links,
            "stats": graph.get("stats", {}),
            "has_more": len(all_links) > len(visible_links),
            "truncated": len(all_links) > len(visible_links),
        }
        stats = graph.get("stats", {}) if isinstance(graph, dict) else {}
    return jsonify({
        "success": True,
        "session_id": str(session_id or "default"),
        "nodes": view.get("nodes", []),
        "links": view.get("links", []),
        "relations": view.get("relations", []),
        "stats": stats,
        "view_stats": {
            "node_count": len(view.get("nodes", [])),
            "relation_count": len(view.get("relations", [])),
        },
        "relation_types": stats.get("relation_types", {}),
        "query": keyword,
        "center_uid": view.get("center_uid", ""),
        "matched_uids": view.get("matched_uids", []),
        "has_more": view.get("has_more", False),
        "truncated": view.get("truncated", False),
        "from_cache": view.get("from_cache", False),
    })


@app.route('/api/knowledge-graph/query', methods=['POST'])
def query_knowledge_graph():
    """按关键词返回图谱子图。"""
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get('session_id', '')).strip() or None
    keyword = str(payload.get('keyword', '')).strip()
    try:
        limit = int(payload.get("limit") or 80)
    except (TypeError, ValueError):
        limit = 80
    try:
        depth = int(payload.get("depth") or 1)
    except (TypeError, ValueError):
        depth = 1

    view = query_centered_graph(session_id=session_id, keyword=keyword, limit=limit, depth=depth)
    return jsonify({
        "success": True,
        "session_id": str(session_id or "default"),
        "nodes": view.get("nodes", []),
        "links": view.get("links", []),
        "relations": view.get("relations", []),
        "stats": view.get("stats", {}),
        "view_stats": {
            "node_count": len(view.get("nodes", [])),
            "relation_count": len(view.get("relations", [])),
        },
        "relation_types": view.get("stats", {}).get("relation_types", {}),
        "query": keyword,
        "center_uid": view.get("center_uid", ""),
        "matched_uids": view.get("matched_uids", []),
        "has_more": view.get("has_more", False),
        "truncated": view.get("truncated", False),
        "from_cache": view.get("from_cache", False),
    })


@app.route('/api/knowledge-graph/rebuild', methods=['POST'])
def rebuild_knowledge_graph():
    """根据当前会话已上传文档异步重建知识图谱。"""
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get('session_id', '')).strip() or None
    status = start_graph_build(session_id, list_session_chunks(session_id))
    return jsonify({
        "success": True,
        "session_id": str(session_id or "default"),
        "build_status": status,
    })


@app.route('/api/knowledge-graph/status', methods=['GET'])
def knowledge_graph_status():
    """获取当前会话知识图谱构建状态。"""
    session_id = str(request.args.get('session_id', '')).strip() or None
    status = get_graph_build_status(session_id)
    return jsonify({
        "success": True,
        "session_id": str(session_id or "default"),
        "build_status": status,
    })


@app.route('/api/knowledge-graph/expand', methods=['POST'])
def expand_knowledge_graph():
    """按节点展开一跳邻居。"""
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get('session_id', '')).strip() or None
    node_uid = str(payload.get('node_uid', '')).strip()
    try:
        limit = int(payload.get("limit") or 60)
    except (TypeError, ValueError):
        limit = 60
    try:
        offset = int(payload.get("offset") or 0)
    except (TypeError, ValueError):
        offset = 0
    direction = str(payload.get("direction") or "both").strip().lower()

    graph = expand_graph_neighbors(session_id=session_id, node_uid=node_uid, limit=limit, offset=offset, direction=direction)
    return jsonify({
        "success": True,
        "session_id": str(session_id or "default"),
        "node_uid": node_uid,
        "nodes": graph.get("nodes", []),
        "links": graph.get("links", []),
        "relations": graph.get("relations", []),
        "stats": graph.get("stats", {}),
        "offset": graph.get("offset", offset),
        "limit": graph.get("limit", limit),
        "has_more": graph.get("has_more", False),
        "truncated": graph.get("truncated", False),
        "from_cache": graph.get("from_cache", False),
        "returned_relation_count": graph.get("returned_relation_count", len(graph.get("relations", []))),
        "total_relation_count": graph.get("total_relation_count", len(graph.get("relations", []))),
    })


@app.route('/api/sensors/push', methods=['POST'])
def push_sensor_data():
    """接收传感器接口推送的数据。"""
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get('session_id', '')).strip() or None
    records = payload.get("records")
    if records is None:
        records = payload.get("sensors")
    if records is None:
        records = payload.get("data")

    result = push_session_sensors(session_id=session_id, payload=records)
    return jsonify({
        "success": True,
        **result,
    })


@app.route('/api/sensors/latest', methods=['GET'])
def latest_sensor_data():
    """获取当前会话最新传感器数据。"""
    session_id = str(request.args.get('session_id', '')).strip() or None
    records = list_session_sensors(session_id)
    return jsonify({
        "success": True,
        "session_id": str(session_id or "default"),
        "sensor_count": len(records),
        "records": records,
    })


@app.route('/api/sensors/clear', methods=['POST'])
def clear_sensor_data():
    """清空当前会话传感器缓存。"""
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get('session_id', '')).strip() or None
    cleared = clear_session_sensors(session_id)
    return jsonify({
        "success": True,
        "session_id": str(session_id or "default"),
        "cleared": cleared,
    })

# 获取百度API Token
def get_baidu_access_token():
    import time
    current_time = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > current_time:
        return _token_cache["token"]

    baidu_api_key, baidu_secret_key = config.require_baidu_credentials()
    params = {
        "grant_type": "client_credentials",
        "client_id": baidu_api_key,
        "client_secret": baidu_secret_key,
    }
    try:
        resp = requests.post(config.BAIDU_TOKEN_URL, data=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token")
        expires_in = data.get("expires_in", 2592000)
        _token_cache["token"] = token
        _token_cache["expires_at"] = current_time + expires_in - 60
        return token
    except Exception as e:
        print(f"获取百度token失败: {e}")
        raise

# 图片识别API
@app.route('/api/image-analyze', methods=['POST'])
def image_analyze():
    try:
        data = request.get_json()
        
        if not data or "image_base64" not in data:
            return jsonify({"error": "No image data provided", "result": []}), 400
        
        img_base64 = data.get("image_base64", "")
        img_name = data.get("image_name", "image")
        
        if not img_base64:
            return jsonify({"error": "Empty image data", "result": []}), 400
        result = _analyze_baidu_image_base64(img_base64, img_name)
        return jsonify(result)
    except Exception as e:
        print(f"图片分析错误: {e}")
        return jsonify({"error": str(e), "result": []}), 500


@app.route('/api/video-analyze', methods=['POST'])
def video_analyze():
    """处理视频上传并抽帧分析。"""
    if 'file' not in request.files:
        return jsonify({'error': '未找到视频文件'}), 400

    file = request.files['file']
    video_name = str(getattr(file, "filename", "") or "未命名视频")
    suffix = Path(video_name).suffix or ".mp4"
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = tmp.name
        file.save(temp_path)

        extracted = _extract_video_frames(Path(temp_path))
        frame_reports = []
        for frame in extracted["frames"]:
            frame_name = f"{video_name} @ {_format_video_timestamp(frame['timestamp_s'])}"
            result = _analyze_baidu_image_base64(frame["image_base64"], frame_name)
            keywords = _extract_image_keywords(result, limit=5)
            if not keywords:
                continue
            frame_reports.append({
                "frame_index": frame["frame_index"],
                "timestamp_s": frame["timestamp_s"],
                "timestamp_label": _format_video_timestamp(frame["timestamp_s"]),
                "keywords": keywords,
            })

        payload = _build_video_analysis_response(video_name, extracted, frame_reports)
        return jsonify(payload)
    except RuntimeError as e:
        return jsonify({"error": str(e), "summary_text": "", "evidence": []}), 500
    except Exception as e:
        print(f"视频分析错误: {e}")
        return jsonify({"error": str(e), "summary_text": "", "evidence": []}), 500
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass


@app.route('/api/chat', methods=['POST'])
def chat_with_longcat():
    """后端代理 LongCat 请求，避免浏览器直连外网导致超时或受限。"""
    try:
        payload = request.get_json(silent=True) or {}
        system_prompt = payload.get("system", "")
        messages = payload.get("messages", [])
        model = payload.get("model") or config.LONGCAT_MODEL
        max_tokens = int(payload.get("max_tokens", 2048))

        if not isinstance(messages, list) or not messages:
            return jsonify({"error": "messages 不能为空"}), 400

        api_payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system_prompt:
            api_payload["system"] = system_prompt

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.require_longcat_api_key()}",
            "anthropic-version": "2023-06-01",
        }

        url = config.LONGCAT_CHAT_PROXY_URL
        # 连接超时 12 秒，读取超时使用配置值。
        resp = requests.post(
            url,
            headers=headers,
            json=api_payload,
            timeout=(12, config.LONGCAT_READ_TIMEOUT),
        )
        data = resp.json() if resp.content else {}

        if not resp.ok:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            err_msg = err.get("message") or data.get("error") or resp.text
            return jsonify({"error": f"LongCat API错误 {resp.status_code}: {err_msg}"}), resp.status_code

        reply = "无响应"
        content = data.get("content", []) if isinstance(data, dict) else []
        if isinstance(content, list):
            text_block = next((b for b in content if isinstance(b, dict) and b.get("type") == "text" and b.get("text")), None)
            if text_block:
                reply = text_block.get("text", "无响应")

        return jsonify({"reply": reply, "raw": data})
    except requests.exceptions.Timeout:
        return jsonify({"error": "LongCat 请求超时（后端150秒）"}), 504
    except Exception as e:
        print(f"LongCat代理错误: {e}")
        return jsonify({"error": f"LongCat代理错误: {str(e)}"}), 500

# LangChain智能体对话接口
@app.route('/api/agent-chat', methods=['POST'])
def agent_chat():
    """
    LangChain智能体问答接口
    入参兼容旧格式 {"query": "你的问题"}，也支持结构化会话与证据字段。
    出参: {"reply": "智能体回复"}
    """
    try:
        normalized = _normalize_agent_chat_request(request.get_json(silent=True) or {})
        if not normalized["query"]:
            return jsonify({"error": "query不能为空"}), 400

        options = normalized["options"] or {}
        retrieval_documents = normalized["evidence_documents"]
        sensor_records = normalized["evidence_sensors"]
        use_retrieval = options.get("use_retrieval_evidence", True)
        use_sensor_evidence = options.get("use_sensor_evidence", True)
        session_id = normalized["session_id"]

        if config.RAG_ENABLED and use_retrieval and has_session_documents(session_id):
            retrieval_documents = retrieve_relevant_chunks(
                session_id=session_id,
                query=normalized["query"],
                top_k=config.RAG_TOP_K,
            )

        if use_sensor_evidence and not sensor_records and has_session_sensors(session_id):
            sensor_records = list_session_sensors(session_id)

        result = multi_agent_ask(
            query=normalized["query"],
            session_id=session_id,
            history=normalized["history"],
            evidence_documents=retrieval_documents,
            evidence_images=normalized["evidence_images"],
            evidence_sensors=sensor_records,
            options=options,
        )
        return jsonify(result)
    except TimeoutError as e:
        return jsonify({"error": str(e)}), 504
    except RuntimeError as e:
        if "timed out" in str(e).lower() or "timeout" in str(e).lower() or "超时" in str(e):
            return jsonify({"error": str(e)}), 504
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=False, port=config.SERVER_PORT)
