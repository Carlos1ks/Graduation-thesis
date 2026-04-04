"""
项目配置管理
"""
import os
from typing import Optional, Dict

class Config:
    """应用配置类"""
    
    # Flask 配置
    DEBUG = os.environ.get("DEBUG", "False") == "True"
    SERVER_PORT = int(os.environ.get("SERVER_PORT", "5001"))
    
    # CORS 配置
    CORS_ORIGINS = [
        "http://localhost:5173",
        "http://localhost:3000", 
        "http://127.0.0.1:5173",
        "*"
    ]
    
    # 百度 API 配置（用于图片识别）
    BAIDU_API_KEY = os.environ.get("BAIDU_API_KEY", "XBwe5ml18RsROS0jjpgQA2lf")
    BAIDU_SECRET_KEY = os.environ.get("BAIDU_SECRET_KEY", "uaoVCauFbrLh08u0qPH2fWRrRk2x27pU")
    BAIDU_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
    BAIDU_IMAGE_ANALYZE_URL = "https://aip.baidubce.com/rest/2.0/image-classify/v2/advanced_general"
    
    # LongCat LLM 配置
    LONGCAT_API_KEY = os.environ.get("LONGCAT_API_KEY", "ak_2ho0is8Y064o6Bd1UI80m0Ab1mL5n")
    LONGCAT_BASE_URL = os.environ.get("LONGCAT_BASE_URL", "https://api.longcat.chat/openai")
    LONGCAT_MODEL = os.environ.get("LONGCAT_MODEL", "LongCat-Flash-Thinking-2601")
    LONGCAT_READ_TIMEOUT = int(os.environ.get("LONGCAT_READ_TIMEOUT", "25"))
    LONGCAT_RETRIES = int(os.environ.get("LONGCAT_RETRIES", "1"))
    LONGCAT_MAX_TOKENS = int(os.environ.get("LONGCAT_MAX_TOKENS", "220"))
    
    # 代理配置
    USE_PROXY = os.environ.get("USE_PROXY", "0") == "1"
    HTTP_PROXY = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    HTTPS_PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    
    # Agent 配置
    AGENT_SYSTEM_PROMPT = "你是煤矿应急救援智能体，回答必须专业、可执行，并给出清晰步骤。"
    AGENT_MAX_ITERATIONS = int(os.environ.get("AGENT_MAX_ITERATIONS", "5"))
    
    @classmethod
    def get_proxies(cls) -> Optional[Dict[str, str]]:
        """获取代理配置"""
        if cls.USE_PROXY and (cls.HTTP_PROXY or cls.HTTPS_PROXY):
            return {
                "http": cls.HTTP_PROXY or cls.HTTPS_PROXY,
                "https": cls.HTTPS_PROXY or cls.HTTP_PROXY,
            }
        return None


config = Config()
