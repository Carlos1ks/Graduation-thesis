# 会话级检索层。
# 这个模块负责把上传的规程文本切成可检索片段，
# 再在问答开始前用多种信号对证据进行排序。
import hashlib
import math
import re
from threading import RLock
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from config import config
from knowledge_graph import get_session_graph, score_graph_relevance

_DEFAULT_SESSION_ID = "default"
_ARTICLE_SPLIT_PATTERN = re.compile(r"(?=第[一二三四五六七八九十百千万零两\d]+条(?:\s|$))")
_ARTICLE_LABEL_PATTERN = re.compile(r"第[一二三四五六七八九十百千万零两\d]+条")
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[。；！？])")
_HASH_EMBEDDING_DIM = 384

# 每个会话各自维护自己的文档、分块和向量索引。
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
    # 当 sentence-transformers 不可用时，退化使用的简易向量器。
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
    # 只在真正需要时才加载 numpy / faiss / 向量模型，
    # 避免导入阶段过重，也方便缺依赖时优雅降级。
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


def _risk_alignment_score(
    query: str,
    record_text: str,
    *,
    risk_types: Optional[List[str]] = None,
    risk_signals: Optional[List[Dict[str, str]]] = None,
) -> float:
    text = str(record_text or "")
    if not text:
        return 0.0

    score = 0.0
    lowered_query = _normalize_text(query)
    normalized_risk_types: Set[str] = {str(item or "").strip() for item in (risk_types or []) if str(item or "").strip()}
    signal_tokens: List[str] = []
    for signal in risk_signals or []:
        if not isinstance(signal, dict):
            continue
        signal_label = str(signal.get("signal_label") or signal.get("signal_id") or "").strip()
        signal_keywords = str(signal.get("keywords") or "").strip()
        if signal_label:
            signal_tokens.append(signal_label)
        if signal_keywords:
            signal_tokens.extend([part for part in signal_keywords.split("、") if part])

    for risk_type in normalized_risk_types:
        if not risk_type:
            continue
        if risk_type in text:
            score += 1.2

    for token in signal_tokens:
        if token and token in text:
            score += 0.45

    if any(term in lowered_query for term in ["火灾", "瓦斯", "突水", "被困", "失联", "撤离", "断电", "通风"]):
        for action_term in ["停止作业", "切断电源", "撤离", "撤出人员", "加强通风", "设置警戒", "上报", "救援"]:
            if action_term in text:
                score += 0.22
    return score


def _sentence_similarity(text_a: str, text_b: str) -> float:
    left = _normalize_text(text_a)
    right = _normalize_text(text_b)
    if not left or not right:
        return 0.0
    left_tokens = set(_HashingEmbedder()._tokenize(left))
    right_tokens = set(_HashingEmbedder()._tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    scale = math.sqrt(len(left_tokens) * len(right_tokens))
    return overlap / scale if scale else 0.0


def _merge_sentences_by_semantics(sentences: List[str], max_chunk_size: int, overlap: int) -> List[str]:
    if not sentences:
        return []

    threshold = float(getattr(config, "RAG_SENTENCE_MERGE_THRESHOLD", 0.42))
    chunks: List[str] = []
    current = ""
    prev_sentence = ""

    for sentence in sentences:
        piece = str(sentence or "").strip()
        if not piece:
            continue
        sim = _sentence_similarity(prev_sentence, piece) if prev_sentence else 1.0
        can_concat = len(current) + len(piece) <= max_chunk_size

        if current and (not can_concat or sim < threshold):
            trimmed = current.strip()
            if trimmed:
                chunks.append(trimmed)
            if overlap > 0 and trimmed:
                current = trimmed[-overlap:] + piece
            else:
                current = piece
        else:
            current += piece
        prev_sentence = piece

    if current.strip():
        chunks.append(current.strip())
    return chunks


def chunk_text(text: str, chunk_size: Optional[int] = None, chunk_overlap: Optional[int] = None) -> List[Dict[str, str]]:
    # 先优先按规程条文边界切，再把过长条文拆成更平滑的语义块。
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
        merged_chunks = _merge_sentences_by_semantics(sentences, max_chunk_size=max_chunk_size, overlap=overlap)
        for merged_text in merged_chunks:
            chunks.append({
                "text": merged_text,
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
    # 把单个上传文档切块、向量化，并合并进当前会话的检索库。
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


def retrieve_relevant_chunks(
    session_id: Optional[str],
    query: str,
    top_k: Optional[int] = None,
    *,
    risk_types: Optional[List[str]] = None,
    risk_signals: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    # 问答前最核心的证据召回入口。
    # 排序不是只看向量相似度，还会综合图谱、关键词和风险一致性信号。
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

    weight_vector = float(config.RAG_WEIGHT_VECTOR)
    weight_graph = float(config.RAG_WEIGHT_GRAPH)
    weight_keyword = float(config.RAG_WEIGHT_KEYWORD)
    weight_risk = float(config.RAG_WEIGHT_RISK)
    total_weight = weight_vector + weight_graph + weight_keyword + weight_risk
    if total_weight <= 0:
        weight_vector, weight_graph, weight_keyword, weight_risk = 0.40, 0.25, 0.20, 0.15
        total_weight = 1.0
    weight_vector /= total_weight
    weight_graph /= total_weight
    weight_keyword /= total_weight
    weight_risk /= total_weight

    article_label = _extract_article_label(search_query) or ""
    try:
        graph_cache = get_session_graph(sid)
    except Exception:
        graph_cache = {"nodes": [], "relations": [], "links": []}
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
        risk_score = _risk_alignment_score(
            search_query,
            record.get("text", ""),
            risk_types=risk_types,
            risk_signals=risk_signals,
        )
        graph_signal = score_graph_relevance(
            search_query,
            session_id=sid,
            graph=graph_cache,
            article_label=str(record.get("article_label") or ""),
            text=str(record.get("text") or ""),
            doc_name=str(record.get("doc_name") or ""),
            risk_types=risk_types,
        )
        graph_score = float(graph_signal.get("score") or 0.0)
        score = (
            weight_vector * vector_score
            + weight_graph * graph_score
            + weight_keyword * keyword_score
            + weight_risk * risk_score
        )
        if article_label and record.get("article_label") == article_label:
            score += 0.8
        if record.get("article_label") and record.get("article_label") in record.get("chunk_id", ""):
            score += 0.15
        ranked.append((score, {
            **record,
            "_vector_score": vector_score,
            "_keyword_score": keyword_score,
            "_graph_score": graph_score,
            "_risk_score": risk_score,
            "_graph_signal": graph_signal,
        }))

    ranked.sort(
        key=lambda item: (
            item[0],
            item[1].get("_graph_score", 0.0),
            item[1].get("_risk_score", 0.0),
            item[1].get("_keyword_score", 0.0),
            item[1].get("_vector_score", 0.0),
        ),
        reverse=True,
    )
    results: List[Dict[str, Any]] = []
    for score, record in ranked[:search_k]:
        results.append({
            "doc_name": record.get("doc_name", "未命名文档"),
            "chunk_id": record.get("chunk_id", "未知片段"),
            "text": record.get("text", ""),
            "score": round(float(score), 4),
            "vector_score": round(float(record.get("_vector_score", 0.0)), 4),
            "keyword_score": round(float(record.get("_keyword_score", 0.0)), 4),
            "graph_score": round(float(record.get("_graph_score", 0.0)), 4),
            "risk_score": round(float(record.get("_risk_score", 0.0)), 4),
            "weights": {
                "vector": round(weight_vector, 4),
                "graph": round(weight_graph, 4),
                "keyword": round(weight_keyword, 4),
                "risk": round(weight_risk, 4),
            },
            "source_type": record.get("source_type", "uploaded_doc_vector"),
        })
    return results
