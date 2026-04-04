"""
LangChain LLM 适配器：集成 LongCat 大语言模型
"""
import logging
from typing import Any, Optional, List
from langchain_core.language_models import LLM
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from config import config
from http_client import HTTPClient

logger = logging.getLogger(__name__)


class LongCatLLM(LLM):
    """
    LongCat (Anthropic 兼容 API) 到 LangChain LLM 接口的适配器
    支持 LongCat Chat Completions API
    """
    
    api_key: str
    base_url: str
    model: str
    timeout: int = 45
    max_tokens: int = 220
    temperature: float = 0.7
    
    @property
    def _llm_type(self) -> str:
        return "longcat_anthropic"
    
    @property
    def _identifying_params(self) -> dict:
        """返回识别参数"""
        return {
            "model": self.model,
            "api_key": self.api_key[:8] + "***",
            "base_url": self.base_url,
            "max_tokens": self.max_tokens,
        }
    
    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs
    ) -> str:
        """
        调用 LongCat API
        
        Args:
            prompt: 用户提示词
            stop: 停止词
            run_manager: LangChain 回调管理器
            **kwargs: 其他参数
            
        Returns:
            LLM 的文本响应
        """
        logger.debug(f"调用 LongCat LLM，模型: {self.model}")
        
        system_prompt = config.AGENT_SYSTEM_PROMPT
        
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
        
        if stop:
            payload["stop"] = stop
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        
        try:
            response = HTTPClient.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=(10, self.timeout),
                retries=config.LONGCAT_RETRIES
            )
            
            data = response.json()
            logger.debug(f"LongCat 响应: {data.keys()}")
            
            # 处理错误响应
            if "error" in data:
                error_msg = data["error"].get("message", "未知错误")
                logger.error(f"LongCat API 错误: {error_msg}")
                raise RuntimeError(f"LongCat API 错误: {error_msg}")
            
            # 提取回复
            choices = data.get("choices", [])
            if not choices:
                logger.warning("LongCat 返回空的 choices 列表")
                return "抱歉，未获取到有效响应。请重试。"
            
            message = choices[0].get("message", {})
            reply = message.get("content", "").strip()
            
            if not reply:
                logger.warning("LongCat 返回空的内容")
                return "抱歉，未获取到有效响应。请重试。"
            
            logger.debug(f"LongCat 返回内容长度: {len(reply)} 字符")
            
            # 处理停止词
            if stop:
                for stop_seq in stop:
                    if stop_seq in reply:
                        reply = reply.split(stop_seq)[0]
                        logger.debug(f"根据停止词截断回复")
            
            return reply
            
        except Exception as e:
            logger.error(f"LongCat LLM 调用失败: {e}", exc_info=True)
            raise


def create_longcat_llm() -> LongCatLLM:
    """创建 LongCat LLM 实例"""
    return LongCatLLM(
        api_key=config.LONGCAT_API_KEY,
        base_url=config.LONGCAT_BASE_URL,
        model=config.LONGCAT_MODEL,
        timeout=config.LONGCAT_READ_TIMEOUT,
        max_tokens=config.LONGCAT_MAX_TOKENS,
    )
