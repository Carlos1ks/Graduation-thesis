# 鐓ょ熆搴旀€ユ晳鎻存櫤鑳戒綋椤圭洰璇存槑

鏈」鐩负鍓嶅悗绔垎绂诲簲鐢細
1. 鍓嶇浣跨敤 React + Vite 鎻愪緵浜や簰鐣岄潰銆?
2. 鍚庣浣跨敤 Flask 鎻愪緵鏂囨。瑙ｆ瀽銆佸浘鐗囪瘑鍒€佹绱㈠寮哄拰澶氭櫤鑳戒綋闂瓟鎺ュ彛銆?

## 杩愯鏂瑰紡

### 鍓嶇

鍦ㄩ」鐩牴鐩綍鎵ц锛?

```bash
npm install
npm run dev
```

鍓嶇榛樿浠庣幆澧冨彉閲?`VITE_API_BASE_URL` 璇诲彇鍚庣鍦板潃锛屼緥濡傦細

```bash
VITE_API_BASE_URL=http://127.0.0.1:5001 npm run dev
```

### 鍚庣

鍦?server 鐩綍鎵ц锛?

```bash
pip install -r requirements.txt
python app.py
```

杩愯鍓嶉渶瑕侀厤缃互涓嬬幆澧冨彉閲忥細

```bash
export LONGCAT_API_KEY="..."
export VISION_API_KEY="..."
```

鍙€夌幆澧冨彉閲忥細

- `LONGCAT_BASE_URL`锛氶粯璁?`https://api.longcat.chat/openai`
- `LONGCAT_CHAT_PROXY_URL`锛氶粯璁?`https://api.longcat.chat/anthropic/v1/messages`
- `SERVER_PORT`锛氶粯璁?`5001`
- `CORS_ORIGINS`锛氶€楀彿鍒嗛殧鐨勫厑璁告潵婧愬垪琛?

## 鐩綍缁撴瀯

```text
coal-mine-agent/
鈹溾攢 README.md
鈹溾攢 package.json
鈹溾攢 vite.config.js
鈹溾攢 src/
鈹? 鈹溾攢 App.jsx
鈹? 鈹溾攢 index.css
鈹? 鈹斺攢 main.jsx
鈹溾攢 server/
鈹? 鈹溾攢 agent.py
鈹? 鈹溾攢 config.py
鈹? 鈹溾攢 domain_schema.py
鈹? 鈹溾攢 knowledge_graph.py
鈹? 鈹溾攢 app.py
鈹? 鈹溾攢 requirements.txt
鈹? 鈹溾攢 retrieval.py
鈹? 鈹斺攢 risk_fusion.py
鈹溾攢 tools/
```

## 鏍稿績妯″潡璇存槑

- `src/App.jsx`锛氬墠绔富鐣岄潰锛岃礋璐ｈ亰澶┿€佹枃妗ｄ笂浼犮€佸浘鐗囦笂浼犲拰缁撴灉灞曠ず銆?
- `server/app.py`锛欶lask 涓绘湇鍔″叆鍙ｏ紝鎻愪緵鏂囨。涓婁紶銆佸浘鐗囧垎鏋愩€佽亰澶╀唬鐞嗗拰澶氭櫤鑳戒綋鎺ュ彛銆?- `server/retrieval.py`锛氭枃妗ｅ垏鍧椼€佸悜閲忕储寮曞拰浼氳瘽绾ф绱€?
- `server/risk_fusion.py`锛氬婧愰闄╄瘑鍒笌椋庨櫓绛夌骇鐢熸垚銆?
- `server/knowledge_graph.py`锛氳交閲忕煡璇嗗浘璋辨娊鍙栦笌鎽樿銆?
- `server/agent.py`锛氬鏅鸿兘浣撹矾鐢便€佽鑹茶皟鐢ㄥ拰缁撴灉鑱氬悎銆?

## 瀵瑰鎺ュ彛璇存槑

1. `POST /api/documents/upload`
   - 涓婁紶 PDF/DOCX/TXT 鏂囨。骞跺缓绔嬪悗绔悜閲忕储寮曘€?

2. `POST /api/documents/remove`
   - 绉婚櫎褰撳墠浼氳瘽涓殑宸蹭笂浼犳枃妗ｅ強绱㈠紩銆?

3. `POST /api/agent-chat`
   - 澶氭櫤鑳戒綋闂瓟涓绘帴鍙ｏ紝鏀寔缁撴瀯鍖栧巻鍙蹭笌璇佹嵁杈撳叆銆?

4. `POST /api/image-analyze`
   - 调用 OpenAI 兼容视觉接口分析图片内容。

5. `POST /api/chat`
   - 鍚庣浠ｇ悊 LongCat 鑱婂ぉ璇锋眰銆?

   - 鍏煎淇濈暀鐨勫崟鏂囦欢瑙ｆ瀽鎺ュ彛銆?
