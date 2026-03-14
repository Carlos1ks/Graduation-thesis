from flask import Flask, request, jsonify
from flask_cors import CORS
import fitz  # PyMuPDF
from docx import Document as DocxDocument
import re

app = Flask(__name__)
CORS(app)

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

if __name__ == '__main__':
    app.run(debug=False, port=5001)
