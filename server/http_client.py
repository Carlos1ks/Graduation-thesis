"""
HTTP 请求工具和重试机制
"""
import requests
import time
import logging
from typing import Dict, Optional, Any
from config import config

logger = logging.getLogger(__name__)


class HTTPClient:
    """统一的 HTTP 客户端，带有代理和重试支持"""
    
    @staticmethod
    def post(
        url: str,
        timeout: tuple = (10, 30),
        retries: int = None,
        **kwargs
    ) -> requests.Response:
        """
        发送 POST 请求，支持代理和重试
        
        Args:
            url: 请求 URL
            timeout: 超时配置 (connect_timeout, read_timeout)
            retries: 重试次数，None 时使用默认配置
            **kwargs: 其他传递给 requests.post 的参数
        """
        session = requests.Session()
        session.trust_env = config.USE_PROXY
        
        if config.get_proxies():
            kwargs["proxies"] = config.get_proxies()
        
        kwargs["timeout"] = timeout
        
        if retries is None:
            retries = config.LONGCAT_RETRIES
        
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                logger.debug(f"POST 请求 (尝试 {attempt}/{retries}): {url}")
                response = session.post(url, **kwargs)
                response.raise_for_status()
                logger.debug(f"POST 请求成功: {url}")
                return response
            except requests.exceptions.Timeout as e:
                last_error = e
                if attempt < retries:
                    wait_time = 1.2 ** attempt
                    logger.warning(f"超时，{wait_time:.1f}秒后重试... (尝试 {attempt}/{retries})")
                    time.sleep(wait_time)
                continue
            except requests.exceptions.ConnectionError as e:
                last_error = e
                if attempt < retries:
                    wait_time = 1.2 ** attempt
                    logger.warning(f"连接错误，{wait_time:.1f}秒后重试... (尝试 {attempt}/{retries})")
                    time.sleep(wait_time)
                continue
            except requests.exceptions.RequestException as e:
                logger.error(f"请求失败: {e}")
                raise
        
        logger.error(f"所有重试均失败: {last_error}")
        raise last_error if last_error else RuntimeError("HTTP 请求失败")
    
    @staticmethod
    def get(
        url: str,
        timeout: tuple = (10, 30),
        **kwargs
    ) -> requests.Response:
        """发送 GET 请求"""
        session = requests.Session()
        session.trust_env = config.USE_PROXY
        
        if config.get_proxies():
            kwargs["proxies"] = config.get_proxies()
        
        kwargs["timeout"] = timeout
        
        logger.debug(f"GET 请求: {url}")
        response = session.get(url, **kwargs)
        response.raise_for_status()
        return response


# 百度 API Token 缓存
_baidu_token_cache = {"token": None, "expires_at": 0}


class BaiduAPIClient:
    """百度 API 客户端"""
    
    @staticmethod
    def get_access_token() -> str:
        """获取百度 API 访问令牌"""
        import time
        
        current_time = time.time()
        if _baidu_token_cache["token"] and _baidu_token_cache["expires_at"] > current_time:
            logger.debug("使用缓存的百度 Token")
            return _baidu_token_cache["token"]
        
        logger.info("获取新的百度 API Token...")
        params = {
            "grant_type": "client_credentials",
            "client_id": config.BAIDU_API_KEY,
            "client_secret": config.BAIDU_SECRET_KEY
        }
        
        try:
            response = HTTPClient.post(
                config.BAIDU_TOKEN_URL,
                data=params,
                timeout=(8, 15),
                retries=3
            )
            data = response.json()
            
            if "error" in data:
                raise RuntimeError(f"百度 Token 获取失败: {data.get('error_description', data)}")
            
            token = data.get("access_token")
            expires_in = data.get("expires_in", 2592000)  # 默认30天
            
            _baidu_token_cache["token"] = token
            _baidu_token_cache["expires_at"] = current_time + expires_in - 60
            
            logger.info(f"成功获取百度 Token，有效期 {expires_in} 秒")
            return token
            
        except Exception as e:
            logger.error(f"获取百度 Token 失败: {e}")
            raise
