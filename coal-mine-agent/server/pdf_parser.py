from flask import Flask, request, jsonify
from flask_cors import CORS
import fitz  # PyMuPDF
from docx import Document as DocxDocument
import re
import requests
import base64
import os

app = Flask(__name__)
CORS(app)

# 百度图片识别 API 配置
# 通过环境变量 BAIDU_API_KEY 和 BAIDU_SECRET_KEY 设置您的百度AI平台凭据
# 也可以在启动时直接赋值（不建议提交到版本库）
BAIDU_API_KEY = os.getenv("BAIDU_API_KEY", "")
BAIDU_SECRET_KEY = os.getenv("BAIDU_SECRET_KEY", "")
BAIDU_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
BAIDU_RECOGNIZE_URL = "https://aip.baidubce.com/rest/2.0/image-classify/v2/advanced_general"
BAIDU_DESCRIPTION_MAX_LEN = 100

_baidu_token_cache = {"token": None, "expires": 0}


def get_baidu_access_token():
    """获取百度API访问令牌（带缓存）"""
    import time
    now = time.time()
    if _baidu_token_cache["token"] and now < _baidu_token_cache["expires"]:
        return _baidu_token_cache["token"]

    if not BAIDU_API_KEY or not BAIDU_SECRET_KEY:
        raise RuntimeError("百度API密钥未配置，请设置环境变量 BAIDU_API_KEY 和 BAIDU_SECRET_KEY")
    params = {
        "grant_type": "client_credentials",
        "client_id": BAIDU_API_KEY,
        "client_secret": BAIDU_SECRET_KEY,
    }
    resp = requests.post(BAIDU_TOKEN_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"获取百度token失败: {data}")
    _baidu_token_cache["token"] = data["access_token"]
    _baidu_token_cache["expires"] = now + data.get("expires_in", 2592000) - 60
    return _baidu_token_cache["token"]

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

@app.route('/api/baidu-image-recognize', methods=['POST'])
def baidu_image_recognize():
    """使用百度AI识别上传的图片内容"""
    if 'file' not in request.files:
        return jsonify({'error': '未找到图片文件'}), 400

    file = request.files['file']
    allowed_types = {'image/jpeg', 'image/png', 'image/bmp', 'image/webp'}
    if file.mimetype and file.mimetype not in allowed_types:
        return jsonify({'error': f'不支持的图片格式：{file.mimetype}，请上传 JPG/PNG/BMP/WEBP'}), 400

    try:
        image_data = file.read()
        image_b64 = base64.b64encode(image_data).decode('utf-8')

        access_token = get_baidu_access_token()

        payload = {
            "image": image_b64,
            "baike_num": 1,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = requests.post(
            f"{BAIDU_RECOGNIZE_URL}?access_token={access_token}",
            data=payload,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()

        if "error_code" in result:
            return jsonify({
                'error': f"百度API错误 {result['error_code']}: {result.get('error_msg', '未知错误')}"
            }), 500

        results = result.get("result", [])
        formatted = []
        for item in results:
            entry = {
                "keyword": item.get("keyword", ""),
                "score": round(item.get("score", 0) * 100, 1),
                "root": item.get("root", ""),
            }
            baike = item.get("baike_info", {})
            if baike.get("description"):
                entry["description"] = baike["description"][:BAIDU_DESCRIPTION_MAX_LEN]
            formatted.append(entry)

        return jsonify({
            'success': True,
            'results': formatted,
            'log_id': result.get("log_id"),
        })

    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'请求百度API失败: {str(e)}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=False, port=5001)
