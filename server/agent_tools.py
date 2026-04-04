"""
LangChain Agent 工具定义
为煤矿应急救援智能体定义所有可用工具
"""
import logging
from typing import List, Dict, Any
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def format_chunks(chunks: List[Dict[str, Any]]) -> str:
    """
    格式化检索的规程片段
    
    Args:
        chunks: 规程片段列表 [{docName, text}, ...]
        
    Returns:
        格式化后的文本
    """
    if not chunks:
        return "未检索到相关规程内容。"
    
    lines = []
    for idx, item in enumerate(chunks[:6], start=1):
        doc_name = item.get("docName", "未命名文档")
        text = item.get("text", "").strip()
        if text:
            lines.append(f"[{idx}] 来源:{doc_name}\n{text}")
    
    result = "\n\n".join(lines) if lines else "未检索到相关规程内容。"
    logger.debug(f"格式化后的规程内容长度: {len(result)} 字符")
    return result


class EmergencyAgentTools:
    """
    煤矿应急救援智能体工具集
    
    这个类包含所有 Agent 可以调用的工具，
    支持：规程查询、图片分析、风险评估等
    """
    
    def __init__(
        self,
        retrieved_chunks: List[Dict[str, Any]] = None,
        image_analysis: str = None,
    ):
        """
        初始化工具集
        
        Args:
            retrieved_chunks: 已检索的规程片段
            image_analysis: 图片识别分析结果
        """
        self.retrieved_chunks = retrieved_chunks or []
        self.image_analysis = image_analysis or ""
        
        logger.info(
            f"初始化应急工具集: {len(self.retrieved_chunks)} 个规程片段, "
            f"图片分析 {len(self.image_analysis)} 字符"
        )
    
    @tool("retrieve_regulations")
    def retrieve_regulations(self, query: str) -> str:
        """
        检索相关规程与标准
        
        当需要查询煤矿安全规程、应急预案、技术标准时调用此工具。
        
        Args:
            query: 查询关键词或问题
            
        Returns:
            相关规程文本片段
        """
        logger.info(f"检索规程，查询词: {query}")
        result = format_chunks(self.retrieved_chunks)
        logger.debug(f"返回规程内容: {len(result)} 字符")
        return result
    
    @tool("get_situation_analysis")
    def get_situation_analysis(self, question: str) -> str:
        """
        获取图片识别的现场态势分析
        
        分析上传的图片，识别现场设备、环境、人员等信息。
        用于辅助态势判断和决策。
        
        Args:
            question: 关于图片的问题或查询
            
        Returns:
            图片识别分析结果
        """
        logger.info(f"获取态势分析: {question}")
        result = self.image_analysis or "当前无图片识别信息。"
        logger.debug(f"返回态势分析: {len(result)} 字符")
        return result
    
    @tool("assess_risk_level")
    def assess_risk_level(self, scene_description: str) -> str:
        """
        基于场景描述进行风险等级评估
        
        根据场景关键词进行风险等级初步评估（高/中/低）。
        支持多类型灾害识别：瓦斯、火灾、水灾、坍塌等。
        
        Args:
            scene_description: 现场场景及征兆描述
            
        Returns:
            风险等级评估结果
        """
        logger.info(f"评估风险等级: {scene_description[:50]}...")
        
        text = scene_description.lower()
        
        # 高风险关键词
        high_risk_keywords = ["爆炸", "瓦斯", "明火", "突水", "坍塌", "中毒", "火灾"]
        # 中风险关键词
        medium_risk_keywords = ["烟雾", "高温", "漏水", "设备异常", "通风异常", "异响"]
        
        if any(keyword in text for keyword in high_risk_keywords):
            result = (
                "风险等级: 高风险（红色）\n"
                "判断依据: 识别到重大灾害隐患\n"
                "建议: 立即组织撤离、断电、通风隔离并启动专项应急预案"
            )
            logger.warning("识别为高风险")
        elif any(keyword in text for keyword in medium_risk_keywords):
            result = (
                "风险等级: 中风险（橙/黄色）\n"
                "判断依据: 识别到明显异常迹象\n"
                "建议: 立即现场排查并准备升级响应"
            )
            logger.warning("识别为中风险")
        else:
            result = (
                "风险等级: 一般风险（蓝色）\n"
                "判断依据: 无明显灾害迹象\n"
                "建议: 持续监测并复核关键指标"
            )
            logger.info("识别为低风险")
        
        return result
    
    def get_tools(self) -> List[Any]:
        """
        返回所有工具列表，用于 Agent 注册
        
        Returns:
            工具对象列表
        """
        tools = [
            self.retrieve_regulations,
            self.get_situation_analysis,
            self.assess_risk_level,
        ]
        logger.info(f"返回 {len(tools)} 个工具")
        return tools


def create_agent_tools(
    retrieved_chunks: List[Dict[str, Any]] = None,
    image_analysis: str = None,
) -> List[Any]:
    """
    便利函数：创建 Agent 工具列表
    
    Args:
        retrieved_chunks: 已检索的规程片段
        image_analysis: 图片识别分析结果
        
    Returns:
        LangChain 工具列表
    """
    chunks = retrieved_chunks or []
    image_text = image_analysis or ""

    @tool("retrieve_regulations")
    def retrieve_regulations(query: str) -> str:
        """检索相关规程与标准。"""
        logger.info(f"检索规程，查询词: {query}")
        return format_chunks(chunks)

    @tool("get_situation_analysis")
    def get_situation_analysis(question: str) -> str:
        """获取图片识别的现场态势分析。"""
        logger.info(f"获取态势分析: {question}")
        return image_text or "当前无图片识别信息。"

    @tool("assess_risk_level")
    def assess_risk_level(scene_description: str) -> str:
        """基于场景描述进行风险等级评估。"""
        logger.info(f"评估风险等级: {scene_description[:50]}...")
        text = scene_description.lower()

        high_risk_keywords = ["爆炸", "瓦斯", "明火", "突水", "坍塌", "中毒", "火灾"]
        medium_risk_keywords = ["烟雾", "高温", "漏水", "设备异常", "通风异常", "异响"]

        if any(keyword in text for keyword in high_risk_keywords):
            return (
                "风险等级: 高风险（红色）\n"
                "判断依据: 识别到重大灾害隐患\n"
                "建议: 立即组织撤离、断电、通风隔离并启动专项应急预案"
            )
        if any(keyword in text for keyword in medium_risk_keywords):
            return (
                "风险等级: 中风险（橙/黄色）\n"
                "判断依据: 识别到明显异常迹象\n"
                "建议: 立即现场排查并准备升级响应"
            )
        return (
            "风险等级: 一般风险（蓝色）\n"
            "判断依据: 无明显灾害迹象\n"
            "建议: 持续监测并复核关键指标"
        )

    tools = [
        retrieve_regulations,
        get_situation_analysis,
        assess_risk_level,
    ]
    logger.info(f"返回 {len(tools)} 个工具")
    return tools
