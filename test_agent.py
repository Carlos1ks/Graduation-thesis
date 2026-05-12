# -*- coding: utf-8 -*-
"""测试多智能体系统"""
import json
import sys

sys.path.insert(0, 'C:/self/Draft_py/coal-mine-agent/server')

from pdf_parser import app


def print_result(title, resp):
    print(f"\n=== {title} ===")
    print(f"HTTP状态码: {resp.status_code}")
    result = resp.get_json()
    if not result:
        print("无响应内容")
        return None

    if 'error' in result:
        print(f"错误: {result['error']}")
        return result

    print("响应已获取，详情将保存到结果文件。")
    print(f"选中的角色: {result.get('selected_agents')}")
    print(f"路由模式: {result.get('route_mode')}")
    print(f"路由原因: {result.get('route_reason')}")
    print(f"会话ID: {result.get('session_id')}")
    print(f"记忆使用情况: {result.get('memory_used')}")
    print(f"证据使用情况: {result.get('evidence_used')}")
    print(f"风险识别: {result.get('risk_assessment', {}).get('risk_level')}")
    print(f"图谱关系数: {result.get('kg_used', {}).get('relation_count')}")
    return result


def assert_enriched_result(title, result):
    if not result:
        raise AssertionError(f"{title} 无结果")
    if 'risk_assessment' not in result:
        raise AssertionError(f"{title} 缺少 risk_assessment")
    if 'kg_used' not in result:
        raise AssertionError(f"{title} 缺少 kg_used")
    if 'source_fusion' not in result:
        raise AssertionError(f"{title} 缺少 source_fusion")


def test_agent():
    with app.test_client() as client:
        no_evidence_payload = {
            'query': '瓦斯浓度超标如何处置？'
        }
        no_evidence_resp = client.post(
            '/api/agent-chat',
            data=json.dumps(no_evidence_payload, ensure_ascii=False),
            content_type='application/json'
        )
        no_evidence_result = print_result('无规程文档测试', no_evidence_resp)
        assert_enriched_result('无规程文档测试', no_evidence_result)

        legacy_payload = {
            'query': '掘进工作面瓦斯浓度达到1.5%，现场有20名作业人员，应如何处置？'
        }
        legacy_resp = client.post(
            '/api/agent-chat',
            data=json.dumps(legacy_payload),
            content_type='application/json'
        )
        legacy_result = print_result('旧格式兼容测试', legacy_resp)
        assert_enriched_result('旧格式兼容测试', legacy_result)

        structured_payload = {
            'query': '那第一批先做什么？',
            'session_id': 'demo-session-001',
            'history': [
                {'role': 'user', 'content': '当前场景是掘进工作面瓦斯浓度1.5%，有20名作业人员。'},
                {'role': 'assistant', 'content': '建议立即停止作业、组织撤人并通知通防部门复核。'}
            ],
            'evidence': {
                'documents': [
                    {
                        'doc_name': '煤矿安全规程.pdf',
                        'chunk_id': '煤矿安全规程.pdf:12',
                        'text': '第十二条 发现瓦斯浓度超限时，应立即停止作业、撤出人员并采取通风处理措施。现场班组长和调度室应按职责组织断电、撤人和通风复核。',
                        'score': 0.01,
                        'source_type': 'uploaded_doc'
                    }
                ],
                'images': [
                    {
                        'image_name': '现场1.jpg',
                        'summary': '识别到巷道、烟雾和作业设备',
                        'source_type': 'image_analysis'
                    }
                ]
            },
            'options': {
                'use_session_memory': True,
                'use_retrieval_evidence': True
            }
        }
        structured_resp = client.post(
            '/api/agent-chat',
            data=json.dumps(structured_payload, ensure_ascii=False),
            content_type='application/json'
        )
        structured_result = print_result('结构化会话与证据测试', structured_resp)
        assert_enriched_result('结构化会话与证据测试', structured_result)

        if structured_result.get('kg_used', {}).get('relation_count', 0) <= 0:
            raise AssertionError('结构化会话与证据测试 未生成图谱关系')
        if structured_result.get('risk_assessment', {}).get('risk_level') not in {'中', '高', '极高'}:
            raise AssertionError('结构化会话与证据测试 风险等级异常')

        if no_evidence_result:
            with open('C:/self/Draft_py/coal-mine-agent/test_result_no_evidence.json', 'w', encoding='utf-8') as f:
                json.dump(no_evidence_result, f, ensure_ascii=False, indent=2)
        if legacy_result:
            with open('C:/self/Draft_py/coal-mine-agent/test_result.json', 'w', encoding='utf-8') as f:
                json.dump(legacy_result, f, ensure_ascii=False, indent=2)
        if structured_result:
            with open('C:/self/Draft_py/coal-mine-agent/test_result_structured.json', 'w', encoding='utf-8') as f:
                json.dump(structured_result, f, ensure_ascii=False, indent=2)
            print('\n结构化结果已保存到 test_result_structured.json')


if __name__ == '__main__':
    test_agent()
