"""
项目配置管理
"""
import os
from pathlib import Path
from typing import Optional, Dict


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

class Config:
    """应用配置类"""
    
    # Flask 配置
    DEBUG = os.environ.get("DEBUG", "False") == "True"
    SERVER_PORT = int(os.environ.get("SERVER_PORT", "5001"))
    
    # CORS 配置
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ]
    
    # 百度 API 配置（用于图片识别）
    BAIDU_API_KEY = os.environ.get("BAIDU_API_KEY")
    BAIDU_SECRET_KEY = os.environ.get("BAIDU_SECRET_KEY")
    BAIDU_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
    BAIDU_IMAGE_ANALYZE_URL = "https://aip.baidubce.com/rest/2.0/image-classify/v2/advanced_general"
    
    # LongCat LLM 配置
    LONGCAT_API_KEY = os.environ.get("LONGCAT_API_KEY")
    LONGCAT_BASE_URL = os.environ.get("LONGCAT_BASE_URL", "https://api.longcat.chat/openai")
    LONGCAT_CHAT_PROXY_URL = os.environ.get("LONGCAT_CHAT_PROXY_URL", "https://api.longcat.chat/anthropic/v1/messages")
    LONGCAT_MODEL = os.environ.get("LONGCAT_MODEL", "LongCat-Flash-Chat")
    LONGCAT_READ_TIMEOUT = int(os.environ.get("LONGCAT_READ_TIMEOUT", "60"))
    LONGCAT_RETRIES = int(os.environ.get("LONGCAT_RETRIES", "1"))
    LONGCAT_MAX_TOKENS = int(os.environ.get("LONGCAT_MAX_TOKENS", "800"))
    
    # 代理配置
    USE_PROXY = os.environ.get("USE_PROXY", "0") == "1"
    HTTP_PROXY = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    HTTPS_PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    
    # Agent 配置
    AGENT_SYSTEM_PROMPT = "你是煤矿应急救援智能体，回答必须专业、可执行，并给出清晰步骤。"
    AGENT_MAX_ITERATIONS = int(os.environ.get("AGENT_MAX_ITERATIONS", "5"))
    MULTI_AGENT_ENABLED = os.environ.get("MULTI_AGENT_ENABLED", "1") == "1"
    AGENT_MAX_HISTORY_MESSAGES = int(os.environ.get("AGENT_MAX_HISTORY_MESSAGES", "12"))
    AGENT_MAX_HISTORY_TURNS = int(os.environ.get("AGENT_MAX_HISTORY_TURNS", "6"))
    AGENT_MAX_HISTORY_CHARS = int(os.environ.get("AGENT_MAX_HISTORY_CHARS", "1800"))
    AGENT_MAX_EVIDENCE_DOCUMENTS = int(os.environ.get("AGENT_MAX_EVIDENCE_DOCUMENTS", "4"))
    AGENT_MAX_EVIDENCE_DOCUMENT_CHARS = int(os.environ.get("AGENT_MAX_EVIDENCE_DOCUMENT_CHARS", "2200"))
    AGENT_MAX_EVIDENCE_IMAGES = int(os.environ.get("AGENT_MAX_EVIDENCE_IMAGES", "2"))
    AGENT_MAX_EVIDENCE_SENSORS = int(os.environ.get("AGENT_MAX_EVIDENCE_SENSORS", "12"))

    # 轻量知识图谱配置
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
    KG_MAX_ARTICLES_PER_BUILD = int(os.environ.get("KG_MAX_ARTICLES_PER_BUILD", "80"))

    # 多源风险识别配置
    RISK_RULES_ENABLED = os.environ.get("RISK_RULES_ENABLED", "1") == "1"
    RISK_SCORE_THRESHOLDS = {
        "medium": int(os.environ.get("RISK_SCORE_MEDIUM", "4")),
        "high": int(os.environ.get("RISK_SCORE_HIGH", "8")),
        "critical": int(os.environ.get("RISK_SCORE_CRITICAL", "12")),
    }
    FORCE_KNOWLEDGE_ON_DECISION = os.environ.get("FORCE_KNOWLEDGE_ON_DECISION", "1") == "1"

    # 视频分析配置
    VIDEO_MAX_FRAMES = int(os.environ.get("VIDEO_MAX_FRAMES", "8"))
    VIDEO_SAMPLE_SECONDS = float(os.environ.get("VIDEO_SAMPLE_SECONDS", "1.5"))
    VIDEO_FRAME_MAX_WIDTH = int(os.environ.get("VIDEO_FRAME_MAX_WIDTH", "960"))
    VIDEO_JPEG_QUALITY = int(os.environ.get("VIDEO_JPEG_QUALITY", "85"))

    # 后端向量 RAG 配置
    RAG_ENABLED = os.environ.get("RAG_ENABLED", "1") == "1"
    RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "4"))
    RAG_CHUNK_SIZE = int(os.environ.get("RAG_CHUNK_SIZE", "700"))
    RAG_CHUNK_OVERLAP = int(os.environ.get("RAG_CHUNK_OVERLAP", "80"))
    RAG_MAX_CHUNKS_PER_DOC = int(os.environ.get("RAG_MAX_CHUNKS_PER_DOC", "0"))
    RAG_EMBEDDING_MODEL = os.environ.get(
        "RAG_EMBEDDING_MODEL",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )

    @classmethod
    def get_proxies(cls) -> Optional[Dict[str, str]]:
        """获取代理配置"""
        if cls.USE_PROXY and (cls.HTTP_PROXY or cls.HTTPS_PROXY):
            return {
                "http": cls.HTTP_PROXY or cls.HTTPS_PROXY,
                "https": cls.HTTPS_PROXY or cls.HTTP_PROXY,
            }
        return None

    @classmethod
    def require_longcat_api_key(cls) -> str:
        if cls.LONGCAT_API_KEY:
            return cls.LONGCAT_API_KEY
        raise RuntimeError("未配置 LONGCAT_API_KEY 环境变量。")

    @classmethod
    def require_baidu_credentials(cls) -> tuple[str, str]:
        if cls.BAIDU_API_KEY and cls.BAIDU_SECRET_KEY:
            return cls.BAIDU_API_KEY, cls.BAIDU_SECRET_KEY
        raise RuntimeError("未配置 BAIDU_API_KEY / BAIDU_SECRET_KEY 环境变量。")

    @classmethod
    def require_neo4j_credentials(cls) -> tuple[str, str, str, str]:
        if cls.NEO4J_URI and cls.NEO4J_USERNAME and cls.NEO4J_PASSWORD:
            uri = cls.NEO4J_URI
            if uri.startswith("neo4j://"):
                uri = "bolt://" + uri[len("neo4j://"):]
            return uri, cls.NEO4J_USERNAME, cls.NEO4J_PASSWORD, cls.NEO4J_DATABASE
        raise RuntimeError("未配置 NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD。")


config = Config()
