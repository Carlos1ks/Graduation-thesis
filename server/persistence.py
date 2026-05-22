from __future__ import annotations

import base64
import json
import mimetypes
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / ".persist"
UPLOAD_DIR = DATA_DIR / "uploads"
IMAGE_DIR = UPLOAD_DIR / "images"
VIDEO_DIR = UPLOAD_DIR / "videos"
DOCUMENT_DIR = UPLOAD_DIR / "documents"
DB_PATH = DATA_DIR / "app_state.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    DOCUMENT_DIR.mkdir(parents=True, exist_ok=True)


def _connect() -> sqlite3.Connection:
    _ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _safe_name(file_name: str) -> str:
    raw = Path(str(file_name or "asset")).name
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw)
    return cleaned or "asset"


def _write_binary(kind_dir: Path, file_name: str, raw_bytes: bytes) -> str:
    _ensure_dirs()
    safe_name = _safe_name(file_name)
    target = kind_dir / f"{secrets.token_hex(8)}-{safe_name}"
    target.write_bytes(raw_bytes)
    return str(target.relative_to(DATA_DIR))


def _read_binary(relative_path: str) -> bytes:
    path = DATA_DIR / str(relative_path or "")
    if not path.exists():
        return b""
    return path.read_bytes()


def _remove_binary(relative_path: str) -> None:
    path = DATA_DIR / str(relative_path or "")
    if path.exists():
        path.unlink()


def _row_to_dict(row: sqlite3.Row | None) -> Dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def init_storage() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                library_session_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS auth_tokens (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                text_content TEXT NOT NULL,
                char_count INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS images (
                image_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                summary_text TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                duration_s REAL NOT NULL,
                frames_extracted INTEGER NOT NULL,
                frames_matched INTEGER NOT NULL,
                summary_text TEXT NOT NULL,
                issue_keywords_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sensor_records (
                user_id INTEGER NOT NULL,
                sensor_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, sensor_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )


def _issue_token(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO auth_tokens (token, user_id, created_at) VALUES (?, ?, ?)",
        (token, int(user_id), _now_iso()),
    )
    return token


def register_user(username: str, password: str) -> Dict[str, Any]:
    name = str(username or "").strip()
    secret = str(password or "")
    if len(name) < 3:
        raise ValueError("用户名至少需要 3 个字符。")
    if len(secret) < 6:
        raise ValueError("密码至少需要 6 个字符。")

    created_at = _now_iso()
    library_session_id = f"user-{secrets.token_hex(10)}"
    password_hash = generate_password_hash(secret)

    with _connect() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, library_session_id, created_at) VALUES (?, ?, ?, ?)",
                (name, password_hash, library_session_id, created_at),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("用户名已存在。") from exc
        user_id = int(cursor.lastrowid)
        token = _issue_token(conn, user_id)
        conn.commit()

    return {
        "token": token,
        "user": {
            "id": user_id,
            "username": name,
            "library_session_id": library_session_id,
            "created_at": created_at,
        },
    }


def login_user(username: str, password: str) -> Dict[str, Any]:
    name = str(username or "").strip()
    secret = str(password or "")
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, library_session_id, created_at FROM users WHERE username = ?",
            (name,),
        ).fetchone()
        if row is None or not check_password_hash(row["password_hash"], secret):
            raise ValueError("用户名或密码错误。")
        token = _issue_token(conn, int(row["id"]))
        conn.commit()
    return {
        "token": token,
        "user": {
            "id": int(row["id"]),
            "username": row["username"],
            "library_session_id": row["library_session_id"],
            "created_at": row["created_at"],
        },
    }


def get_user_by_token(token: str) -> Dict[str, Any] | None:
    value = str(token or "").strip()
    if not value:
        return None
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.library_session_id, u.created_at, t.token
            FROM auth_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.token = ?
            """,
            (value,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "library_session_id": row["library_session_id"],
        "created_at": row["created_at"],
        "token": row["token"],
    }


def delete_token(token: str) -> None:
    value = str(token or "").strip()
    if not value:
        return
    with _connect() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE token = ?", (value,))
        conn.commit()


def save_document_asset(
    user_id: int,
    document_id: str,
    file_name: str,
    raw_bytes: bytes,
    text_content: str,
    char_count: int,
    chunk_count: int,
) -> Dict[str, Any]:
    stored_path = _write_binary(DOCUMENT_DIR, file_name, raw_bytes)
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO documents
            (document_id, user_id, file_name, stored_path, text_content, char_count, chunk_count, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(document_id),
                int(user_id),
                str(file_name),
                stored_path,
                str(text_content),
                int(char_count),
                int(chunk_count),
                int(len(raw_bytes)),
                now,
            ),
        )
        conn.commit()
    return {
        "document_id": str(document_id),
        "file_name": str(file_name),
        "stored_path": stored_path,
        "char_count": int(char_count),
        "chunk_count": int(chunk_count),
        "size_bytes": int(len(raw_bytes)),
        "created_at": now,
    }


def list_document_assets(user_id: int) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT document_id, file_name, stored_path, text_content, char_count, chunk_count, size_bytes, created_at
            FROM documents
            WHERE user_id = ?
            ORDER BY created_at ASC
            """,
            (int(user_id),),
        ).fetchall()
    return [
        {
            "document_id": row["document_id"],
            "file_name": row["file_name"],
            "stored_path": row["stored_path"],
            "text": row["text_content"],
            "char_count": int(row["char_count"]),
            "chunk_count": int(row["chunk_count"]),
            "size_bytes": int(row["size_bytes"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def delete_document_asset(user_id: int, document_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT stored_path FROM documents WHERE user_id = ? AND document_id = ?",
            (int(user_id), str(document_id)),
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            "DELETE FROM documents WHERE user_id = ? AND document_id = ?",
            (int(user_id), str(document_id)),
        )
        conn.commit()
    _remove_binary(row["stored_path"])
    return True


def _image_data_url(relative_path: str, mime_type: str) -> str:
    raw = _read_binary(relative_path)
    if not raw:
        return ""
    encoded = base64.b64encode(raw).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def save_image_asset(
    user_id: int,
    file_name: str,
    raw_bytes: bytes,
    mime_type: str,
    summary_text: str,
    evidence: List[Dict[str, Any]],
) -> Dict[str, Any]:
    image_id = secrets.token_hex(10)
    stored_path = _write_binary(IMAGE_DIR, file_name, raw_bytes)
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO images
            (image_id, user_id, file_name, stored_path, mime_type, size_bytes, summary_text, evidence_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                image_id,
                int(user_id),
                str(file_name),
                stored_path,
                str(mime_type),
                int(len(raw_bytes)),
                str(summary_text or ""),
                json.dumps(evidence or [], ensure_ascii=False),
                now,
            ),
        )
        conn.commit()
    return {
        "image_id": image_id,
        "name": str(file_name),
        "dataUrl": _image_data_url(stored_path, mime_type),
        "sizeMB": f"{len(raw_bytes) / 1024 / 1024:.2f}",
        "summary_text": str(summary_text or ""),
        "evidence": evidence or [],
        "created_at": now,
    }


def list_image_assets(user_id: int) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT image_id, file_name, stored_path, mime_type, size_bytes, summary_text, evidence_json, created_at
            FROM images
            WHERE user_id = ?
            ORDER BY created_at ASC
            """,
            (int(user_id),),
        ).fetchall()
    items = []
    for row in rows:
        evidence = json.loads(row["evidence_json"] or "[]")
        items.append({
            "image_id": row["image_id"],
            "name": row["file_name"],
            "dataUrl": _image_data_url(row["stored_path"], row["mime_type"]),
            "sizeMB": f"{int(row['size_bytes']) / 1024 / 1024:.2f}",
            "summary_text": row["summary_text"] or "",
            "evidence": evidence if isinstance(evidence, list) else [],
            "created_at": row["created_at"],
        })
    return items


def delete_image_asset(user_id: int, image_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT stored_path FROM images WHERE user_id = ? AND image_id = ?",
            (int(user_id), str(image_id)),
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            "DELETE FROM images WHERE user_id = ? AND image_id = ?",
            (int(user_id), str(image_id)),
        )
        conn.commit()
    _remove_binary(row["stored_path"])
    return True


def save_video_asset(
    user_id: int,
    file_name: str,
    raw_bytes: bytes,
    mime_type: str,
    duration_s: float,
    frames_extracted: int,
    frames_matched: int,
    summary_text: str,
    issue_keywords: List[str],
    evidence: List[Dict[str, Any]],
) -> Dict[str, Any]:
    video_id = secrets.token_hex(10)
    stored_path = _write_binary(VIDEO_DIR, file_name, raw_bytes)
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO videos
            (video_id, user_id, file_name, stored_path, mime_type, size_bytes, duration_s, frames_extracted, frames_matched, summary_text, issue_keywords_json, evidence_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                int(user_id),
                str(file_name),
                stored_path,
                str(mime_type),
                int(len(raw_bytes)),
                float(duration_s),
                int(frames_extracted),
                int(frames_matched),
                str(summary_text or ""),
                json.dumps(issue_keywords or [], ensure_ascii=False),
                json.dumps(evidence or [], ensure_ascii=False),
                now,
            ),
        )
        conn.commit()
    return {
        "video_id": video_id,
        "name": str(file_name),
        "sizeMB": f"{len(raw_bytes) / 1024 / 1024:.2f}",
        "duration_s": float(duration_s),
        "frames_extracted": int(frames_extracted),
        "frames_matched": int(frames_matched),
        "issue_keywords": issue_keywords or [],
        "summary_text": str(summary_text or ""),
        "evidence": evidence or [],
        "created_at": now,
    }


def list_video_assets(user_id: int) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT video_id, file_name, size_bytes, duration_s, frames_extracted, frames_matched, summary_text, issue_keywords_json, evidence_json, created_at
            FROM videos
            WHERE user_id = ?
            ORDER BY created_at ASC
            """,
            (int(user_id),),
        ).fetchall()
    items = []
    for row in rows:
        issue_keywords = json.loads(row["issue_keywords_json"] or "[]")
        evidence = json.loads(row["evidence_json"] or "[]")
        items.append({
            "video_id": row["video_id"],
            "name": row["file_name"],
            "sizeMB": f"{int(row['size_bytes']) / 1024 / 1024:.2f}",
            "duration_s": float(row["duration_s"] or 0.0),
            "frames_extracted": int(row["frames_extracted"] or 0),
            "frames_matched": int(row["frames_matched"] or 0),
            "issue_keywords": issue_keywords if isinstance(issue_keywords, list) else [],
            "summary_text": row["summary_text"] or "",
            "evidence": evidence if isinstance(evidence, list) else [],
            "created_at": row["created_at"],
        })
    return items


def delete_video_asset(user_id: int, video_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT stored_path FROM videos WHERE user_id = ? AND video_id = ?",
            (int(user_id), str(video_id)),
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            "DELETE FROM videos WHERE user_id = ? AND video_id = ?",
            (int(user_id), str(video_id)),
        )
        conn.commit()
    _remove_binary(row["stored_path"])
    return True


def save_sensor_records(user_id: int, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = _now_iso()
    with _connect() as conn:
        for record in records:
            sensor_id = str(record.get("sensor_id") or "").strip()
            if not sensor_id:
                continue
            conn.execute(
                """
                INSERT INTO sensor_records (user_id, sensor_id, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, sensor_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    int(user_id),
                    sensor_id,
                    json.dumps(record, ensure_ascii=False),
                    now,
                ),
            )
        conn.commit()
    return list_sensor_records(user_id)


def list_sensor_records(user_id: int) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT payload_json
            FROM sensor_records
            WHERE user_id = ?
            ORDER BY updated_at ASC, sensor_id ASC
            """,
            (int(user_id),),
        ).fetchall()
    items: List[Dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            items.append(payload)
    return items


def clear_sensor_records(user_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM sensor_records WHERE user_id = ?", (int(user_id),))
        conn.commit()


def save_message(user_id: int, role: str, content: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (int(user_id), str(role), str(content), _now_iso()),
        )
        conn.commit()


def list_messages(user_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 500))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT role, content, created_at
            FROM messages
            WHERE user_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (int(user_id), safe_limit),
        ).fetchall()
    return [
        {
            "role": row["role"],
            "content": row["content"],
            "timestamp": row["created_at"],
        }
        for row in rows
    ]
