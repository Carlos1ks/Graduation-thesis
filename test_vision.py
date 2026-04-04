import requests
import base64
import json
from pathlib import Path

# Longcat API 配置
LONGCAT_API_KEY = "ak_2ho0is8Y064o6Bd1UI80m0Ab1mL5n"
LONGCAT_BASE_URL = "https://api.longcat.chat/anthropic"
LONGCAT_MODEL = "LongCat-Flash-Thinking-2601"

def test_vision_with_base64():
    """测试Longcat API的vision能力 - 使用Base64编码的示例图片"""
    
    # 创建一个简单的示例图片（1x1像素的红色PNG）
    # 这是最小的有效PNG文件
    png_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LONGCAT_API_KEY}",
        "anthropic-version": "2023-06-01"
    }
    
    # 测试1：简单的vision请求
    payload = {
        "model": LONGCAT_MODEL,
        "max_tokens": 1024,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": png_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": "这是什么图片？请简要描述。"
                    }
                ]
            }
        ]
    }
    
    try:
        print("=" * 60)
        print("测试 Longcat API Vision 能力")
        print("=" * 60)
        print(f"\n【发送请求】")
        print(f"URL: {LONGCAT_BASE_URL}/v1/messages")
        print(f"Model: {LONGCAT_MODEL}")
        print(f"Content: Image (PNG) + Text\n")
        
        response = requests.post(
            f"{LONGCAT_BASE_URL}/v1/messages",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        print(f"【响应状态】HTTP {response.status_code}\n")
        
        if response.status_code == 200:
            data = response.json()
            print("✅ API 支持 Vision！")
            print(f"\n【API响应】")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            
            # 提取回复内容
            if 'content' in data and len(data['content']) > 0:
                for block in data['content']:
                    if block.get('type') == 'text':
                        print(f"\n【AI回复】")
                        print(block.get('text'))
            
            return True
        else:
            print(f"❌ API 返回错误")
            print(f"状态码: {response.status_code}")
            print(f"响应内容: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

def test_text_only():
    """对比测试：纯文本请求（验证API本身是否正常）"""
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LONGCAT_API_KEY}",
        "anthropic-version": "2023-06-01"
    }
    
    payload = {
        "model": LONGCAT_MODEL,
        "max_tokens": 256,
        "messages": [
            {
                "role": "user",
                "content": "简要说明什么是煤矿安全规程。"
            }
        ]
    }
    
    try:
        print("\n" + "=" * 60)
        print("对比测试：纯文本请求")
        print("=" * 60 + "\n")
        
        response = requests.post(
            f"{LONGCAT_BASE_URL}/v1/messages",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        print(f"【响应状态】HTTP {response.status_code}\n")
        
        if response.status_code == 200:
            data = response.json()
            print("✅ API 文本模式正常！")
            
            if 'content' in data and len(data['content']) > 0:
                for block in data['content']:
                    if block.get('type') == 'text':
                        print(f"\n【AI回复】")
                        print(block.get('text'))
            
            return True
        else:
            print(f"❌ API 返回错误")
            print(f"状态码: {response.status_code}")
            print(f"响应内容: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

if __name__ == "__main__":
    print("\n🧪 开始测试 Longcat API 能力\n")
    
    # 先测试文本模式
    text_ok = test_text_only()
    
    # 再测试vision模式
    vision_ok = test_vision_with_base64()
    
    print("\n" + "=" * 60)
    print("📊 测试结果总结")
    print("=" * 60)
    print(f"文本模式: {'✅ 支持' if text_ok else '❌ 不支持'}")
    print(f"Vision模式: {'✅ 支持' if vision_ok else '❌ 不支持'}")
    
    if vision_ok:
        print("\n✅ 可以继续实现图片分析功能！")
    else:
        print("\n⚠️  Longcat 可能不支持Vision，需要改用其他API（如Anthropic Claude）")
