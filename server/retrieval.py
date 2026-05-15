import hashlib
import re
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from config import config

_DEFAULT_SESSION_ID = "default"
_ARTICLE_SPLIT_PATTERN = re.compile(r"(?=第[一二三四五六七八九十百千万零两\d]+条(?:\s|$))")
_ARTICLE_LABEL_PATTERN = re.compile(r"第[一二三四五六七八九十百千万零两\d]+条")
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[。；！？])")
_HASH_EMBEDDING_DIM = 384

_SESSION_RAG_STORES: Dict[str, Dict[str, Any]] = {}
_STORE_LOCK = RLock()
_MODEL_LOCK = RLock()

_np = None
_faiss = None
_embedder = None


_QUERY_EXPANSION_GROUPS = [
    {
        "triggers": ["井下火灾", "火灾", "着火", "火警", "火源", "明火", "烟雾", "烟火"],
        "terms": [
            "井下火灾", "火灾", "着火", "火警", "火源", "明火", "烟雾", "烟火", "灭火", "火区", "火灾事故",
            "撤离", "撤人", "撤出人员", "切断电源", "停止作业", "汇报调度室", "自救器", "反风", "安全出口", "避灾路线",
            "应急预案", "灾害预防和处理计划",
        ],
    },
    {
        "triggers": ["瓦斯", "超限", "超标", "浓度"],
        "terms": [
            "瓦斯", "瓦斯超限", "瓦斯浓度", "超限", "超标", "停止作业", "撤出人员", "切断电源", "加强通风", "风流", "爆炸",
        ],
    },
    {
        "triggers": ["突水", "透水", "涌水", "积水", "水害"],
        "terms": [
            "突水", "透水", "涌水", "积水", "水害", "停止作业", "撤离", "撤出人员", "上报", "注浆", "堵水", "含水层",
        ],
    },
    {
        "triggers": ["被困", "失联", "搜救", "救援"],
        "terms": [
            "被困", "失联", "搜救", "救援", "撤离", "救护队", "调度室", "通信", "定位", "避灾路线",
        ],
    },
]

_QUERY_ALIAS_TERMS = {
    "怎么办": ["如何处置", "处置措施", "处理流程", "应急处置", "行动步骤"],
    "怎么处理": ["如何处置", "处置措施", "处理流程", "应急处置", "行动步骤"],
    "流程": ["处理流程", "处置流程", "应急预案", "行动步骤"],
    "步骤": ["行动步骤", "处置步骤", "处理流程"],
    "应急": ["应急处置", "应急预案", "处理流程"],
    "预案": ["应急预案", "灾害预防和处理计划", "专项应急预案"],
}

_EXACT_PRIORITY_TERMS = [
    "井下火灾", "火灾", "着火", "明火", "烟雾", "瓦斯", "超限", "突水", "透水", "涌水", "被困", "失联",
    "撤离", "撤出人员", "切断电源", "停止作业", "加强通风", "安全出口", "避灾路线", "自救器", "调度室",
]


class _HashingEmbedder:
    def __init__(self, dimension: int = _HASH_EMBEDDING_DIM):
        self.dimension = max(64, int(dimension))

    def _tokenize(self, text: str) -> List[str]:
        normalized = _normalize_text(text)
        if not normalized:
            return []
        char_ngrams: List[str] = []
        chars = list(normalized)
        for n in (2, 3, 4):
            if len(chars) < n:
                continue
            for idx in range(len(chars) - n + 1):
                char_ngrams.append("".join(chars[idx: idx + n]))
        words = re.findall(r"[A-Za-z0-9_一-鿿]+", normalized)
        return words + char_ngrams

    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False):
        np = _np
        vectors = []
        for text in texts:
            vector = np.zeros(self.dimension, dtype="float32")
            for token in self._tokenize(str(text or "")):
                digest = hashlib.md5(token.encode("utf-8")).hexdigest()
                bucket = int(digest[:8], 16) % self.dimension
                sign = 1.0 if int(digest[8:10], 16) % 2 == 0 else -1.0
                vector[bucket] += sign
            norm = float(np.linalg.norm(vector))
            if normalize_embeddings and norm > 0:
                vector = vector / norm
            vectors.append(vector)
        if not vectors:
            return np.zeros((0, self.dimension), dtype="float32")
        return np.asarray(vectors, dtype="float32")


def _get_session_id(session_id: Optional[str]) -> str:
    sid = str(session_id or "").strip()
    return sid or _DEFAULT_SESSION_ID


def _ensure_dependencies() -> Tuple[Any, Any, Any]:
    global _np, _faiss, _embedder
    with _MODEL_LOCK:
        if _np is not None and _faiss is not None and _embedder is not None:
            return _np, _faiss, _embedder

        try:
            import numpy as np
        except Exception as exc:
            raise RuntimeError("缺少 numpy，无法启用后端向量检索。") from exc

        try:
            import faiss
        except Exception as exc:
            raise RuntimeError("缺少 faiss-cpu，无法启用后端向量检索。") from exc

        _np = np
        _faiss = faiss

        if _embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                _embedder = SentenceTransformer(config.RAG_EMBEDDING_MODEL)
            except Exception:
                _embedder = _HashingEmbedder()
        return _np, _faiss, _embedder


def _normalize_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    return normalized


def _extract_article_label(text: str) -> Optional[str]:
    match = _ARTICLE_LABEL_PATTERN.search(str(text or ""))
    return match.group(0) if match else None


def _build_search_terms(query: str) -> List[str]:
    text = _normalize_text(query)
    if not text:
        return []

    terms = {text}
    for trigger, related_terms in _QUERY_ALIAS_TERMS.items():
        if trigger in text:
            terms.update(related_terms)

    for group in _QUERY_EXPANSION_GROUPS:
        if any(trigger in text for trigger in group["triggers"]):
            terms.update(group["terms"])

    return sorted(
        {term.strip() for term in terms if str(term or "").strip()},
        key=lambda item: (-len(item), item),
    )


def _keyword_overlap_score(query: str, record_text: str) -> float:
    search_text = str(record_text or "")
    if not search_text:
        return 0.0

    score = 0.0
    search_terms = _build_search_terms(query)
    query_text = _normalize_text(query)

    for term in search_terms:
        if term in search_text:
            score += 1.8 if len(term) >= 4 else 0.8

    for term in _EXACT_PRIORITY_TERMS:
        if term in query_text and term in search_text:
            score += 2.4

    if "第" in query_text and "条" in query_text:
        article_label = _extract_article_label(query_text)
        if article_label and article_label in search_text:
            score += 4.5

    if any(term in query_text for term in ["怎么办", "怎么处理", "应急", "处置", "处理流程", "步骤"]):
        for action_term in ["停止作业", "撤离", "撤出人员", "切断电源", "加强通风", "汇报调度室", "自救器", "安全出口", "避灾路线"]:
            if action_term in search_text:
                score += 0.9

    return score


def chunk_text(text: str, chunk_size: Optional[int] = None, chunk_overlap: Optional[int] = None) -> List[Dict[str, str]]:
    normalized = _normalize_text(text)
    if not normalized:
        return []

    max_chunk_size = max(200, int(chunk_size or config.RAG_CHUNK_SIZE))
    overlap = max(0, int(chunk_overlap or config.RAG_CHUNK_OVERLAP))
    max_chunks = int(config.RAG_MAX_CHUNKS_PER_DOC)
    article_blocks = [block.strip() for block in _ARTICLE_SPLIT_PATTERN.split(normalized) if block.strip()]
    if not article_blocks:
        article_blocks = [normalized]

    chunks: List[Dict[str, str]] = []
    for block in article_blocks:
        article_label = _extract_article_label(block)
        if len(block) <= max_chunk_size:
            chunks.append({
                "text": block,
                "article_label": article_label or "",
            })
            continue

        sentences = [item for item in _SENTENCE_SPLIT_PATTERN.split(block) if item]
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) <= max_chunk_size:
                current += sentence
                continue

            trimmed = current.strip()
            if trimmed:
                chunks.append({
                    "text": trimmed,
                    "article_label": article_label or "",
                })
            if overlap > 0 and trimmed:
                current = trimmed[-overlap:] + sentence
            else:
                current = sentence

        if current.strip():
            chunks.append({
                "text": current.strip(),
                "article_label": article_label or "",
            })

    if max_chunks > 0:
        return chunks[:max_chunks]
    return chunks


def _embed_texts(texts: List[str]):
    np, _, embedder = _ensure_dependencies()
    vectors = embedder.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(vectors, dtype="float32")


def _create_index(dimension: int):
    _, faiss, _ = _ensure_dependencies()
    return faiss.IndexFlatIP(dimension)


def _rebuild_index_from_chunks(chunks: List[Dict[str, Any]]):
    if not chunks:
        return None
    index = _create_index(len(chunks[0]["embedding"]))
    matrix = _np.vstack([item["embedding"] for item in chunks]).astype("float32")
    index.add(matrix)
    return index


def has_session_documents(session_id: Optional[str]) -> bool:
    sid = _get_session_id(session_id)
    with _STORE_LOCK:
        store = _SESSION_RAG_STORES.get(sid)
        return bool(store and store.get("documents"))


def list_session_documents(session_id: Optional[str]) -> List[Dict[str, Any]]:
    sid = _get_session_id(session_id)
    with _STORE_LOCK:
        store = _SESSION_RAG_STORES.get(sid) or {}
        documents = list((store.get("documents") or {}).values())
        return [
            {
                "document_id": item["document_id"],
                "file_name": item["file_name"],
                "char_count": item["char_count"],
                "chunk_count": item["chunk_count"],
            }
            for item in documents
        ]


def list_session_chunks(session_id: Optional[str]) -> List[Dict[str, Any]]:
    sid = _get_session_id(session_id)
    with _STORE_LOCK:
        store = _SESSION_RAG_STORES.get(sid) or {}
        chunks = list(store.get("chunks") or [])
    return [
        {
            "document_id": item.get("document_id"),
            "doc_name": item.get("doc_name", "未命名文档"),
            "chunk_id": item.get("chunk_id", "未知片段"),
            "article_label": item.get("article_label", ""),
            "text": item.get("text", ""),
            "source_type": item.get("source_type", "uploaded_doc_vector"),
        }
        for item in chunks
    ]


def ingest_document(session_id: Optional[str], file_name: str, text: str) -> Dict[str, Any]:
    if not config.RAG_ENABLED:
        raise RuntimeError("后端向量检索已关闭。")

    normalized_text = _normalize_text(text)
    if not normalized_text:
        raise ValueError("文档内容为空，无法建立向量索引。")

    chunk_records = chunk_text(normalized_text)
    if not chunk_records:
        raise ValueError("文档切块结果为空，无法建立向量索引。")

    chunk_texts = [item["text"] for item in chunk_records]
    embeddings = _embed_texts(chunk_texts)
    document_id = uuid4().hex[:12]
    sid = _get_session_id(session_id)

    records: List[Dict[str, Any]] = []
    for idx, chunk in enumerate(chunk_records, start=1):
        article_label = str(chunk.get("article_label") or "").strip()
        if article_label:
            chunk_id = f"{article_label}-{idx:03d}"
        else:
            chunk_id = f"chunk-{idx:03d}"
        records.append({
            "document_id": document_id,
            "doc_name": str(file_name or "未命名文档").strip() or "未命名文档",
            "chunk_id": chunk_id,
            "text": chunk["text"],
            "article_label": article_label,
            "embedding": embeddings[idx - 1],
            "source_type": "uploaded_doc_vector",
        })

    with _STORE_LOCK:
        store = _SESSION_RAG_STORES.setdefault(sid, {
            "documents": {},
            "chunks": [],
            "index": None,
        })
        if store["index"] is None:
            store["index"] = _create_index(embeddings.shape[1])
        store["index"].add(embeddings)
        store["chunks"].extend(records)
        store["documents"][document_id] = {
            "document_id": document_id,
            "file_name": str(file_name or "未命名文档").strip() or "未命名文档",
            "char_count": len(normalized_text),
            "chunk_count": len(records),
        }

    return {
        "document_id": document_id,
        "file_name": str(file_name or "未命名文档").strip() or "未命名文档",
        "char_count": len(normalized_text),
        "chunk_count": len(records),
        "session_id": sid,
    }


def remove_document(session_id: Optional[str], document_id: str) -> bool:
    sid = _get_session_id(session_id)
    target_id = str(document_id or "").strip()
    if not target_id:
        return False

    with _STORE_LOCK:
        store = _SESSION_RAG_STORES.get(sid)
        if not store or target_id not in store.get("documents", {}):
            return False

        del store["documents"][target_id]
        remaining_chunks = [item for item in store.get("chunks", []) if item.get("document_id") != target_id]
        store["chunks"] = remaining_chunks
        if not remaining_chunks:
            store["index"] = None
            if not store["documents"]:
                _SESSION_RAG_STORES.pop(sid, None)
            return True

        store["index"] = _rebuild_index_from_chunks(remaining_chunks)
        return True


def retrieve_relevant_chunks(session_id: Optional[str], query: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
    if not config.RAG_ENABLED:
        return []

    search_query = _normalize_text(query)
    if not search_query:
        return []

    sid = _get_session_id(session_id)
    with _STORE_LOCK:
        store = _SESSION_RAG_STORES.get(sid)
        if not store or not store.get("chunks") or store.get("index") is None:
            return []
        chunks = list(store["chunks"])
        index = store["index"]

    search_k = max(1, int(top_k or config.RAG_TOP_K))
    candidate_k = min(len(chunks), max(search_k * 8, search_k + 8))
    query_vector = _embed_texts([search_query])
    scores, indices = index.search(query_vector, candidate_k)

    article_label = _extract_article_label(search_query) or ""
    ranked: List[Tuple[float, Dict[str, Any]]] = []
    seen = set()
    for raw_score, raw_index in zip(scores[0], indices[0]):
        idx = int(raw_index)
        if idx < 0 or idx >= len(chunks):
            continue
        record = chunks[idx]
        key = (record.get("document_id"), record.get("chunk_id"))
        if key in seen:
            continue
        seen.add(key)
        vector_score = float(raw_score)
        keyword_score = _keyword_overlap_score(search_query, record.get("text", ""))
        score = vector_score + keyword_score
        if article_label and record.get("article_label") == article_label:
            score += 0.8
        if record.get("article_label") and record.get("article_label") in record.get("chunk_id", ""):
            score += 0.15
        ranked.append((score, {**record, "_vector_score": vector_score, "_keyword_score": keyword_score}))

    ranked.sort(key=lambda item: (item[0], item[1].get("_keyword_score", 0.0), item[1].get("_vector_score", 0.0)), reverse=True)
    results: List[Dict[str, Any]] = []
    for score, record in ranked[:search_k]:
        results.append({
            "doc_name": record.get("doc_name", "未命名文档"),
            "chunk_id": record.get("chunk_id", "未知片段"),
            "text": record.get("text", ""),
            "score": round(float(score), 4),
            "source_type": record.get("source_type", "uploaded_doc_vector"),
        })
    return results
