"""
LangChain Agent 工厂和核心执行逻辑
创建和管理煤矿应急救援智能体
"""
import logging
import json
import re
import inspect
from typing import List, Dict, Any, Optional
from langchain_core.prompts import PromptTemplate
from config import config
from llm_adapter import create_longcat_llm
from agent_tools import create_agent_tools

logger = logging.getLogger(__name__)


# 简化的 Agent 提示模板
REACT_PROMPT_TEMPLATE = """你是一个专业的煤矿应急救援决策智能体。

可用工具：
{tools_description}

回答问题时：
1. 先分析问题的关键信息
2. 根据需要调用工具获取相关数据
3. 综合所有信息生成结构化答案

如果需要调用工具，请仅输出严格 JSON（不要输出 markdown 代码块）：
{{"tool_calls":[{{"name":"工具名","arguments":{{"参数名":"参数值"}}}}]}}

如果不需要调用工具，请直接输出最终答案。

问题: {input}

请按如下格式回答：
1. 风险判断：[评估风险等级]
2. 立即措施：[列出3条以内的立即行动]
3. 后续措施：[列出3条以内的后续行动]
4. 引用依据：[引用相关规程或数据]"""


class SimpleAgentExecutor:
    """
    简化的 Agent 执行器
    直接调用 LLM 和工具，不依赖废弃的 API
    """
    
    def __init__(self, llm, tools, prompt):
        self.llm = llm
        self.tools = tools
        self.prompt = prompt
        self.tool_map = {tool.name: tool for tool in tools}

    def _extract_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """从 LLM 响应中提取 tool_calls。"""
        if not response:
            return []

        text = response.strip()

        # 优先直接解析完整 JSON
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and isinstance(parsed.get("tool_calls"), list):
                return parsed["tool_calls"]
        except Exception:
            pass

        # 兼容 markdown 代码块中的 JSON
        fenced_json = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
        if fenced_json:
            try:
                parsed = json.loads(fenced_json.group(1))
                if isinstance(parsed, dict) and isinstance(parsed.get("tool_calls"), list):
                    return parsed["tool_calls"]
            except Exception:
                pass

        # 兼容响应里夹杂说明文字的场景
        loose_json = re.search(r"(\{\s*\"tool_calls\"[\s\S]*\})", text)
        if loose_json:
            try:
                parsed = json.loads(loose_json.group(1))
                if isinstance(parsed, dict) and isinstance(parsed.get("tool_calls"), list):
                    return parsed["tool_calls"]
            except Exception:
                pass

        return []

    def _run_tool_calls(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """执行 tool_calls 并返回工具结果。"""
        results: List[Dict[str, Any]] = []

        for idx, call in enumerate(tool_calls, start=1):
            name = call.get("name", "")
            args = call.get("arguments", {})

            if name not in self.tool_map:
                results.append({
                    "index": idx,
                    "name": name,
                    "status": "error",
                    "output": f"未找到工具: {name}"
                })
                continue

            tool = self.tool_map[name]
            try:
                if not isinstance(args, dict):
                    args = {}
                try:
                    output = tool.invoke(args)
                except Exception as invoke_error:
                    # 兼容类方法 @tool 场景（Pydantic 可能要求 self 字段）
                    logger.warning(f"tool.invoke 失败，尝试直接调用函数: {name} - {invoke_error}")
                    if hasattr(tool, "func") and callable(tool.func):
                        fn = tool.func
                        sig = inspect.signature(fn)
                        param_names = [
                            p.name for p in sig.parameters.values()
                            if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
                        ]

                        if len(param_names) == 1:
                            key = param_names[0]
                            if key in args:
                                value = args.get(key, "")
                            elif args:
                                # 兼容 LLM 传错参数名（如 query -> keywords）
                                value = next(iter(args.values()))
                            else:
                                value = ""
                            output = fn(value)
                        else:
                            filtered_kwargs = {k: v for k, v in args.items() if k in param_names}
                            output = fn(**filtered_kwargs)
                    else:
                        raise
                results.append({
                    "index": idx,
                    "name": name,
                    "status": "success",
                    "output": str(output)
                })
            except Exception as e:
                logger.error(f"工具执行失败: {name} - {e}", exc_info=True)
                results.append({
                    "index": idx,
                    "name": name,
                    "status": "error",
                    "output": f"工具执行异常: {e}"
                })

        return results

    def _compose_answer_from_tools(self, query: str, tool_results: List[Dict[str, Any]]) -> str:
        """基于工具结果快速生成结构化回答，避免二次 LLM 调用导致超时。"""
        regulations = []
        situation = []
        risk = []
        others = []

        for item in tool_results:
            name = item.get("name", "")
            output = str(item.get("output", "")).strip()
            if not output:
                continue
            if name == "retrieve_regulations":
                regulations.append(output)
            elif name == "get_situation_analysis":
                situation.append(output)
            elif name == "assess_risk_level":
                risk.append(output)
            else:
                others.append(output)

        risk_text = risk[0] if risk else "风险判断: 依据当前信息，建议按中高风险标准先行处置并持续复核。"
        immediate = [
            "立即确认现场指挥链路（调度中心-现场负责人-专业小组）并统一口径。",
            "同步执行人员清点、危险源隔离和关键参数复测（瓦斯/火源/积水/通风）。",
            "按预案分组处置（侦检、抢险、医疗、通信、后勤），每 10-15 分钟回传进展。",
        ]
        follow_up = [
            "根据监测数据动态调整救援资源与撤离路线，必要时升级响应级别。",
            "记录关键决策与时间线，形成复盘与整改清单。",
        ]

        refs = []
        if regulations:
            refs.append(regulations[0][:700])
        if situation:
            refs.append(situation[0][:400])
        if others:
            refs.append(others[0][:300])
        refs_text = "\n\n".join(refs) if refs else "暂无可引用的规程片段。"

        return (
            f"1. 风险判断\n{risk_text}\n\n"
            "2. 立即措施\n"
            + "\n".join([f"- {x}" for x in immediate])
            + "\n\n3. 后续措施\n"
            + "\n".join([f"- {x}" for x in follow_up])
            + "\n\n4. 引用依据\n"
            + refs_text
        )
    
    def invoke(self, input_dict: Dict[str, str]) -> Dict[str, str]:
        """执行 Agent"""
        query = input_dict.get("input", "")
        
        # 生成工具描述
        tool_descriptions = "\n".join([
            f"- {tool.name}: {tool.description}"
            for tool in self.tools
        ])
        
        # 填充提示
        prompt_text = self.prompt.format(
            tools_description=tool_descriptions,
            input=query
        )
        
        logger.debug(f"执行查询: {query[:50]}...")
        
        # 调用 LLM
        response = self.llm.invoke(prompt_text)
        
        logger.debug(f"LLM 响应长度: {len(response)} 字符")

        # 如果响应包含工具调用，执行工具并让 LLM 基于结果生成最终答案
        tool_calls = self._extract_tool_calls(response)
        if not tool_calls and '"tool_calls"' in (response or ""):
            logger.warning("检测到 tool_calls 文本但 JSON 解析失败，启用默认工具调用修复")
            tool_calls = [
                {"name": "retrieve_regulations", "arguments": {"query": query}},
                {"name": "assess_risk_level", "arguments": {"scene_description": query}},
            ]

        if not tool_calls:
            return {"output": response}

        logger.info(f"检测到工具调用: {len(tool_calls)} 个")
        tool_results = self._run_tool_calls(tool_calls)

        final_response = self._compose_answer_from_tools(query, tool_results)
        return {
            "output": final_response,
            "intermediate_steps": tool_results,
        }


class EmergencyAgentFactory:
    """
    应急救援智能体工厂
    
    负责创建和配置智能体，
    用于处理煤矿应急救援相关的问题和任务
    """
    
    @staticmethod
    def _is_effective_output(text: str) -> bool:
        """判断 Agent 输出是否有效。"""
        if not text or not str(text).strip():
            return False
        bad_markers = [
            "未获取到有效响应",
            "请重试",
            '"tool_calls"',
        ]
        content = str(text)
        return not any(marker in content for marker in bad_markers)

    @staticmethod
    def create_agent(
        retrieved_chunks: List[Dict[str, Any]] = None,
        image_analysis: str = None,
        max_iterations: int = None,
    ) -> SimpleAgentExecutor:
        """
        创建并配置煤矿应急救援智能体
        
        Args:
            retrieved_chunks: 预检索的规程片段
            image_analysis: 图片识别分析结果
            max_iterations: 最大迭代次数（此版本中未使用）
            
        Returns:
            配置好的 Agent 执行器实例
        """
        if max_iterations is None:
            max_iterations = config.AGENT_MAX_ITERATIONS
        
        logger.info(
            f"创建应急救援 Agent: "
            f"规程片段={len(retrieved_chunks or [])}, "
            f"图片分析={len(image_analysis or '')} 字符"
        )
        
        # 1. 创建 LLM
        llm = create_longcat_llm()
        logger.debug(f"LLM 已创建: {llm.model}")
        
        # 2. 创建工具
        tools = create_agent_tools(retrieved_chunks, image_analysis)
        logger.debug(f"工具已创建: {len(tools)} 个")
        
        # 3. 创建提示模板
        prompt = PromptTemplate.from_template(REACT_PROMPT_TEMPLATE)
        logger.debug("提示模板已创建")
        
        # 4. 创建执行器
        executor = SimpleAgentExecutor(llm, tools, prompt)
        logger.info("Agent 执行器已创建")
        
        return executor
    
    @staticmethod
    def run_agent(
        query: str,
        retrieved_chunks: List[Dict[str, Any]] = None,
        image_analysis: str = None,
        max_iterations: int = None,
    ) -> Dict[str, Any]:
        """
        执行智能体处理查询
        
        这是标准的 Agent 执行入口，返回完整的执行结果。
        
        Args:
            query: 用户查询问题
            retrieved_chunks: 预检索的规程片段
            image_analysis: 图片识别分析结果
            max_iterations: 最大迭代次数
            
        Returns:
            {
                "output": 最终答案,
                "mode": "agent" | "fallback",
                "status": "success" | "error",
                "error": 错误信息（如有）,
                "iterations": 实际迭代次数（如有）
            }
        """
        logger.info(f"开始执行 Agent，查询: {query[:50]}...")
        
        if not query or not query.strip():
            return {
                "output": "错误：查询不能为空",
                "mode": "fallback",
                "status": "error",
                "error": "empty_query"
            }
        
        try:
            executor = EmergencyAgentFactory.create_agent(
                retrieved_chunks,
                image_analysis,
                max_iterations
            )
            
            result = executor.invoke({"input": query})
            
            logger.info(f"Agent 执行成功")
            
            return {
                "output": result.get("output", ""),
                "mode": "agent",
                "status": "success",
                "iterations": result.get("intermediate_steps", [])
            }
            
        except Exception as e:
            logger.error(f"Agent 执行失败: {e}", exc_info=True)
            return {
                "output": "",
                "mode": "fallback",
                "status": "error",
                "error": str(e)
            }
    
    @staticmethod
    def run_agent_with_fallback(
        query: str,
        retrieved_chunks: List[Dict[str, Any]] = None,
        image_analysis: str = None,
        max_iterations: int = None,
        fallback_fn=None,
    ) -> Dict[str, Any]:
        """
        执行智能体，如果失败则使用回退函数
        
        Args:
            query: 用户查询问题
            retrieved_chunks: 预检索的规程片段
            image_analysis: 图片识别分析结果  
            max_iterations: 最大迭代次数
            fallback_fn: 回退函数 fn(query, chunks, image) -> str
            
        Returns:
            执行结果字典
        """
        logger.info("执行 Agent，启用回退机制")
        
        # 先尝试 Agent 执行
        result = EmergencyAgentFactory.run_agent(
            query,
            retrieved_chunks,
            image_analysis,
            max_iterations
        )
        
        # 如果成功且有输出，直接返回
        if result["status"] == "success" and EmergencyAgentFactory._is_effective_output(result.get("output", "")):
            logger.info("Agent 执行成功，返回结果")
            return result
        
        # 如果失败或无输出，尝试回退
        if fallback_fn:
            logger.warning("Agent 未返回有效结果，使用回退函数")
            try:
                fallback_output = fallback_fn(query, retrieved_chunks, image_analysis)
                return {
                    "output": fallback_output,
                    "mode": "fallback",
                    "status": "success",
                    "warning": "使用本地回退处理"
                }
            except Exception as e:
                logger.error(f"回退函数执行失败: {e}", exc_info=True)
        
        return result
