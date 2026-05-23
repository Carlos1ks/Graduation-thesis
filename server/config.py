"""
椤圭洰閰嶇疆绠＄悊
"""
import os
from pathlib import Path
from typing import Optional, Dict


# 从本地 .env.local 文件加载开发环境变量。
def _load_local_env() -> None:
    candidates = [
        Path(__file__).resolve().parent / ".env.local",
        Path(__file__).resolve().parents[1] / ".env.local",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


_load_local_env()

# 集中定义后端运行时需要的各类配置项。
class Config:
    """应用配置类"""
    
    # Flask 閰嶇疆
    DEBUG = os.environ.get("DEBUG", "False") == "True"
    SERVER_PORT = int(os.environ.get("SERVER_PORT", "5001"))
    
    # CORS 閰嶇疆
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ]
    
    # 视觉模型配置（当前仅保留 OpenAI 兼容链路）
    VISION_PROVIDER = os.environ.get("VISION_PROVIDER", "openai")
    VISION_API_KEY = os.environ.get("VISION_API_KEY") or os.environ.get("ONEAIS_API_KEY")
    VISION_BASE_URL = os.environ.get("VISION_BASE_URL", "https://api.openai.com/v1")
    VISION_MODEL = os.environ.get("VISION_MODEL", "gpt-5.4")
    VISION_READ_TIMEOUT = int(os.environ.get("VISION_READ_TIMEOUT", "120"))
    VISION_MAX_TOKENS = int(os.environ.get("VISION_MAX_TOKENS", "300"))
    
    # LongCat LLM 閰嶇疆
    LONGCAT_API_KEY = os.environ.get("LONGCAT_API_KEY")
    LONGCAT_BASE_URL = os.environ.get("LONGCAT_BASE_URL", "https://api.longcat.chat/openai")
    LONGCAT_CHAT_PROXY_URL = os.environ.get("LONGCAT_CHAT_PROXY_URL", "https://api.longcat.chat/anthropic/v1/messages")
    LONGCAT_MODEL = os.environ.get("LONGCAT_MODEL", "LongCat-Flash-Chat")
    LONGCAT_READ_TIMEOUT = int(os.environ.get("LONGCAT_READ_TIMEOUT", "60"))
    LONGCAT_RETRIES = int(os.environ.get("LONGCAT_RETRIES", "1"))
    LONGCAT_MAX_TOKENS = int(os.environ.get("LONGCAT_MAX_TOKENS", "800"))
    
    # 浠ｇ悊閰嶇疆
    USE_PROXY = os.environ.get("USE_PROXY", "0") == "1"
    HTTP_PROXY = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    HTTPS_PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    
    # Agent 閰嶇疆
    AGENT_SYSTEM_PROMPT = "你是煤矿应急救援智能体，回答必须专业、可执行，并给出清晰步骤。"
    AGENT_MAX_ITERATIONS = int(os.environ.get("AGENT_MAX_ITERATIONS", "5"))
    MULTI_AGENT_ENABLED = os.environ.get("MULTI_AGENT_ENABLED", "1") == "1"
    AGENT_MAX_HISTORY_MESSAGES = int(os.environ.get("AGENT_MAX_HISTORY_MESSAGES", "12"))
    AGENT_MAX_HISTORY_TURNS = int(os.environ.get("AGENT_MAX_HISTORY_TURNS", "6"))
    AGENT_MAX_HISTORY_CHARS = int(os.environ.get("AGENT_MAX_HISTORY_CHARS", "1800"))
    AGENT_MAX_EVIDENCE_DOCUMENTS = int(os.environ.get("AGENT_MAX_EVIDENCE_DOCUMENTS", "4"))
    AGENT_MAX_EVIDENCE_DOCUMENT_CHARS = int(os.environ.get("AGENT_MAX_EVIDENCE_DOCUMENT_CHARS", "2200"))
    AGENT_MAX_EVIDENCE_IMAGES = int(os.environ.get("AGENT_MAX_EVIDENCE_IMAGES", "6"))
    AGENT_MAX_EVIDENCE_SENSORS = int(os.environ.get("AGENT_MAX_EVIDENCE_SENSORS", "12"))

    # 杞婚噺鐭ヨ瘑鍥捐氨閰嶇疆
    KG_ENABLED = os.environ.get("KG_ENABLED", "1") == "1"
    KG_MAX_TRIPLES_PER_DOC = int(os.environ.get("KG_MAX_TRIPLES_PER_DOC", "6"))
    KG_MAX_RELATED_TRIPLES = int(os.environ.get("KG_MAX_RELATED_TRIPLES", "6"))
    NEO4J_ENABLED = os.environ.get("NEO4J_ENABLED", "1") == "1"
    NEO4J_URI = os.environ.get("NEO4J_URI", "neo4j://127.0.0.1:7687")
    NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
    NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
    NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
    KG_LLM_ENABLED = os.environ.get("KG_LLM_ENABLED", "1") == "1"
    KG_LLM_BATCH_SIZE = int(os.environ.get("KG_LLM_BATCH_SIZE", "8"))
    # 0 means no artificial article cap; set a positive value for quick debug builds.
    KG_MAX_ARTICLES_PER_BUILD = int(os.environ.get("KG_MAX_ARTICLES_PER_BUILD", "20"))

    # 澶氭簮椋庨櫓璇嗗埆閰嶇疆
    RISK_RULES_ENABLED = os.environ.get("RISK_RULES_ENABLED", "1") == "1"
    RISK_SCORE_THRESHOLDS = {
        "medium": int(os.environ.get("RISK_SCORE_MEDIUM", "4")),
        "high": int(os.environ.get("RISK_SCORE_HIGH", "8")),
        "critical": int(os.environ.get("RISK_SCORE_CRITICAL", "12")),
    }
    FORCE_KNOWLEDGE_ON_DECISION = os.environ.get("FORCE_KNOWLEDGE_ON_DECISION", "1") == "1"

    # 瑙嗛鍒嗘瀽閰嶇疆
    VIDEO_MAX_FRAMES = int(os.environ.get("VIDEO_MAX_FRAMES", "8"))
    VIDEO_SAMPLE_SECONDS = float(os.environ.get("VIDEO_SAMPLE_SECONDS", "1.5"))
    VIDEO_FRAME_MAX_WIDTH = int(os.environ.get("VIDEO_FRAME_MAX_WIDTH", "960"))
    VIDEO_JPEG_QUALITY = int(os.environ.get("VIDEO_JPEG_QUALITY", "85"))

    # 鍚庣鍚戦噺 RAG 閰嶇疆
    RAG_ENABLED = os.environ.get("RAG_ENABLED", "1") == "1"
    RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "4"))
    RAG_CHUNK_SIZE = int(os.environ.get("RAG_CHUNK_SIZE", "700"))
    RAG_CHUNK_OVERLAP = int(os.environ.get("RAG_CHUNK_OVERLAP", "80"))
    RAG_MAX_CHUNKS_PER_DOC = int(os.environ.get("RAG_MAX_CHUNKS_PER_DOC", "0"))
    RAG_SENTENCE_MERGE_THRESHOLD = float(os.environ.get("RAG_SENTENCE_MERGE_THRESHOLD", "0.42"))
    RAG_WEIGHT_VECTOR = float(os.environ.get("RAG_WEIGHT_VECTOR", "0.40"))
    RAG_WEIGHT_GRAPH = float(os.environ.get("RAG_WEIGHT_GRAPH", "0.25"))
    RAG_WEIGHT_KEYWORD = float(os.environ.get("RAG_WEIGHT_KEYWORD", "0.20"))
    RAG_WEIGHT_RISK = float(os.environ.get("RAG_WEIGHT_RISK", "0.15"))
    RAG_EMBEDDING_MODEL = os.environ.get(
        "RAG_EMBEDDING_MODEL",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )

    # 根据配置返回 requests 可用的代理设置。
    @classmethod
    def get_proxies(cls) -> Optional[Dict[str, str]]:
        """鑾峰彇浠ｇ悊閰嶇疆"""
        if cls.USE_PROXY and (cls.HTTP_PROXY or cls.HTTPS_PROXY):
            return {
                "http": cls.HTTP_PROXY or cls.HTTPS_PROXY,
                "https": cls.HTTPS_PROXY or cls.HTTP_PROXY,
            }
        return None

    # 确保 LongCat 模型调用所需的 API Key 已配置。
    @classmethod
    def require_longcat_api_key(cls) -> str:
        if cls.LONGCAT_API_KEY:
            return cls.LONGCAT_API_KEY
        raise RuntimeError("未配置 LONGCAT_API_KEY 环境变量。")

    # 确保视觉模型调用所需的 API Key 已配置。
    @classmethod
    def require_vision_api_key(cls) -> str:
        if cls.VISION_API_KEY:
            return cls.VISION_API_KEY
        raise RuntimeError("未配置 VISION_API_KEY / ONEAIS_API_KEY 环境变量。")

    # 确保 Neo4j 连接参数齐全并返回标准化后的连接信息。
    @classmethod
    def require_neo4j_credentials(cls) -> tuple[str, str, str, str]:
        if cls.NEO4J_URI and cls.NEO4J_USERNAME and cls.NEO4J_PASSWORD:
            uri = cls.NEO4J_URI
            if uri.startswith("neo4j://"):
                uri = "bolt://" + uri[len("neo4j://"):]
            return uri, cls.NEO4J_USERNAME, cls.NEO4J_PASSWORD, cls.NEO4J_DATABASE
        raise RuntimeError("未配置 NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD。")


config = Config()
