from flask import Flask, request, jsonify
from flask_cors import CORS
import fitz  # PyMuPDF
from docx import Document as DocxDocument
import re
import os
import requests
import base64
from config import config

app = Flask(__name__)

# 更明确的CORS配置
CORS(app, 
     origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173", "*"],
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "OPTIONS"])

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# 百度智能云API配置
BAIDU_API_KEY = os.environ.get("BAIDU_API_KEY", "XBwe5ml18RsROS0jjpgQA2lf")
BAIDU_SECRET_KEY = os.environ.get("BAIDU_SECRET_KEY", "uaoVCauFbrLh08u0qPH2fWRrRk2x27pU")

# Token缓存
_token_cache = {"token": None, "expires_at": 0}

def clean_text(text):
    """清洗PDF提取的文本"""
    # 1. 删除页眉页脚
    text = text.replace('应急管理部规章', '').replace('应急管理部发布', '')
    
    # 2. 删除页码 "- 数字 -"
    text = re.sub(r'-\s*\d+\s*-', '', text)
    
    # 3. 修复断句问题 - 非句末的换行改为空格
    text = re.sub(r'(?<![。；？！])\n', ' ', text)
    
    # 4. 规范化空格
    text = re.sub(r'\s+', ' ', text).strip()
    
    # 5. 确保"第"和条号之间没有多余空格
    text = re.sub(r'第\s+([一二三四五六七八九十百千万\d]+)\s*条', r'第\1条', text)
    
    return text

@app.route('/api/parse-pdf', methods=['POST'])
def parse_pdf():
    """处理PDF文件上传"""
    if 'file' not in request.files:
        return jsonify({'error': '未找到文件'}), 400
    
    file = request.files['file']
    
    try:
        # 读取PDF
        pdf_data = file.read()
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        
        # 提取文本
        full_text = ""
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            full_text += text + "\n"
        
        # 清洗文本
        cleaned_text = clean_text(full_text)
        
        return jsonify({
            'success': True,
            'text': cleaned_text,
            'char_count': len(cleaned_text),
            'page_count': len(doc)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/parse-docx', methods=['POST'])
def parse_docx():
    """处理DOCX文件"""
    if 'file' not in request.files:
        return jsonify({'error': '未找到文件'}), 400
    
    file = request.files['file']
    
    try:
        doc = DocxDocument(file)
        text = "\n".join([para.text for para in doc.paragraphs])
        
        return jsonify({
            'success': True,
            'text': text,
            'char_count': len(text)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/parse-text', methods=['POST'])
def parse_text():
    """处理TXT文件"""
    if 'file' not in request.files:
        return jsonify({'error': '未找到文件'}), 400
    
    file = request.files['file']
    
    try:
        text = file.read().decode('utf-8', errors='ignore')
        
        return jsonify({
            'success': True,
            'text': text,
            'char_count': len(text)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 获取百度API Token
def get_baidu_access_token():
    import time
    current_time = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > current_time:
        return _token_cache["token"]
    
    url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {
        "grant_type": "client_credentials",
        "client_id": BAIDU_API_KEY,
        "client_secret": BAIDU_SECRET_KEY
    }
    try:
        resp = requests.post(url, data=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token")
        expires_in = data.get("expires_in", 2592000)
        _token_cache["token"] = token
        _token_cache["expires_at"] = current_time + expires_in - 60
        return token
    except Exception as e:
        print(f"获取百度token失败: {e}")
        raise

# 图片识别API
@app.route('/api/image-analyze', methods=['POST'])
def image_analyze():
    try:
        data = request.get_json()
        
        if not data or "image_base64" not in data:
            return jsonify({"error": "No image data provided", "result": []}), 400
        
        img_base64 = data.get("image_base64", "")
        img_name = data.get("image_name", "image")
        
        if not img_base64:
            return jsonify({"error": "Empty image data", "result": []}), 400
        
        # 清理base64数据 - 移除data URI前缀
        if "," in img_base64:
            img_base64 = img_base64.split(",")[1]
        
        print(f"开始分析图片: {img_name}")
        print(f"Base64数据长度: {len(img_base64)} 字符")
        
        # 调用百度API - 使用form-data方式
        access_token = get_baidu_access_token()
        api_url = f"https://aip.baidubce.com/rest/2.0/image-classify/v2/advanced_general?access_token={access_token}"
        
        # 使用form-data格式发送base64数据
        payload = {
            "image": img_base64
        }
        
        resp = requests.post(
            api_url, 
            data=payload,  # 使用data而不是json
            timeout=15
        )
        
        print(f"百度API响应状态: {resp.status_code}")
        resp.raise_for_status()
        result = resp.json()
        
        # 百度API成功响应
        if "error_code" in result and result["error_code"] != 0:
            print(f"百度API错误: {result.get('error_msg', '未知错误')} (错误码: {result['error_code']})")
            return jsonify({"error": result.get("error_msg", "Baidu API error"), "result": []}), 400
        
        if "result" not in result:
            result["result"] = []
        
        print(f"分析完成，识别到 {len(result.get('result', []))} 个对象")
        return jsonify(result)
    except Exception as e:
        print(f"图片分析错误: {e}")
        return jsonify({"error": str(e), "result": []}), 500


@app.route('/api/chat', methods=['POST'])
def chat_with_longcat():
    """后端代理 LongCat 请求，避免浏览器直连外网导致超时或受限。"""
    try:
        payload = request.get_json(silent=True) or {}
        system_prompt = payload.get("system", "")
        messages = payload.get("messages", [])
        model = payload.get("model") or config.LONGCAT_MODEL
        max_tokens = int(payload.get("max_tokens", 2048))

        if not isinstance(messages, list) or not messages:
            return jsonify({"error": "messages 不能为空"}), 400

        api_payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system_prompt:
            api_payload["system"] = system_prompt

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.LONGCAT_API_KEY}",
            "anthropic-version": "2023-06-01",
        }

        url = "https://api.longcat.chat/anthropic/v1/messages"
        # 连接超时 12 秒，读取超时 150 秒，尽量覆盖较慢推理。
        resp = requests.post(url, headers=headers, json=api_payload, timeout=(12, 150))
        data = resp.json() if resp.content else {}

        if not resp.ok:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            err_msg = err.get("message") or data.get("error") or resp.text
            return jsonify({"error": f"LongCat API错误 {resp.status_code}: {err_msg}"}), resp.status_code

        reply = "无响应"
        content = data.get("content", []) if isinstance(data, dict) else []
        if isinstance(content, list):
            text_block = next((b for b in content if isinstance(b, dict) and b.get("type") == "text" and b.get("text")), None)
            if text_block:
                reply = text_block.get("text", "无响应")

        return jsonify({"reply": reply, "raw": data})
    except requests.exceptions.Timeout:
        return jsonify({"error": "LongCat 请求超时（后端150秒）"}), 504
    except Exception as e:
        print(f"LongCat代理错误: {e}")
        return jsonify({"error": f"LongCat代理错误: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=False, port=5001)
