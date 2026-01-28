import os
import json
import sqlite3
import logging
import re
import hashlib
import random
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from groq import Groq

# ==================== KONFIG ====================
class Config:
    SECRET_KEY = "super-2026-ai-chatbot-secret"
    DEBUG = True
    HOST = "0.0.0.0"
    PORT = 5006
    DB_PATH = "chatbot_2026.db"
    GROQ_API_KEY = os.getenv("GROQ_API_KEY") or "gsk_xxxxxxxxxxxx"  # ← BURAYA KENDİ GROQ KEY'İNİ YAZ


# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("AI-Chatbot-2026")


# ==================== VERITABANI ====================
class SimpleDB:
    def __init__(self):
        self.conn = sqlite3.connect(Config.DB_PATH, check_same_thread=False)
        self.init_db()

    def init_db(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                message TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()

    def save_message(self, session_id, role, message):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO chat_history (session_id, role, message) VALUES (?, ?, ?)",
            (session_id, role, message)
        )
        self.conn.commit()

    def get_history(self, session_id, limit=10):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT role, message FROM chat_history WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
            (session_id, limit)
        )
        rows = cursor.fetchall()
        return [(r[0], r[1]) for r in reversed(rows)]  # en eskiden → en yeniye


db = SimpleDB()


# ==================== ARAMA MOTORU (korundu) ====================
class SearchEngine:
    def __init__(self):
        try:
            from duckduckgo_search import DDGS
            self.ddg = DDGS()
            logger.info("Web & Görsel arama AKTİF")
        except ImportError:
            self.ddg = None
            logger.warning("duckduckgo-search yüklü değil → arama kapalı")

    def web_search(self, query, max_results=4):
        if not self.ddg: return []
        try:
            return list(self.ddg.text(query, max_results=max_results))[:max_results]
        except:
            return []

    def image_search(self, query, max_results=5):
        if not self.ddg: return []
        try:
            results = list(self.ddg.images(query, max_results=max_results))
            return [r for r in results if r.get('image')][:max_results]
        except:
            return []


search = SearchEngine()


# ==================== GERÇEK AKILLI AI ====================
class ChatAI:
    def __init__(self):
        if not Config.GROQ_API_KEY or "gsk_" not in Config.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY ortam değişkenine veya Config sınıfına eklenmemiş!")

        self.client = Groq(api_key=Config.GROQ_API_KEY)
        self.model = "llama-3.1-70b-versatile"   # çok hızlı ve çok zeki

        self.greetings = [
            "Merhabaa! 🌟 2026 enerjisiyle buradayım, sen nasılsın?",
            "Selam! 🚀 Bugün neyi keşfetmek istiyorsun?",
            "Heyy! 😎 Hazırım, seninle muhabbet etmek için sabırsızlanıyorum!",
        ]

    def generate_response(self, message, session_id):
        msg_lower = message.lower().strip()

        # Özel komutlar (hızlı yollar)
        if any(w in msg_lower for w in ['merhaba', 'selam', 'hey', 'nasılsın', 'naber']):
            return random.choice(self.greetings)

        if msg_lower.startswith(('ara ', 'search ', 'bul ', 'find ')):
            query = message.split(' ', 1)[1].strip() if ' ' in message else ""
            if query:
                results = search.web_search(query, 3)
                if results:
                    resp = f"🔍 **{query}** için bulduklarım:\n\n"
                    for i, r in enumerate(results, 1):
                        resp += f"{i}. **{r.get('title', 'Başlık yok')[:70]}**\n   {r.get('body', '')[:140]}...\n   {r.get('href', '#')}\n\n"
                    return resp
                return f"😕 '{query}' için bir şey bulamadım... Başka ne arayalım?"

        if any(p in msg_lower for p in ['resim ara', 'görsel ara', 'fotoğraf ara']):
            query = re.sub(r'(resim|görsel|fotoğraf)\s+ara', '', msg_lower, flags=re.I).strip()
            if query:
                results = search.image_search(query, 4)
                if results:
                    resp = f"🖼️ **{query}** için birkaç güzel görsel:\n\n"
                    for i, r in enumerate(results, 1):
                        resp += f"{i}. {r.get('title', 'Görsel')[:50]}\n   {r.get('image')}\n\n"
                    return resp
                return "🖼️ Bu konuda görsel bulamadım... Başka bir şey deneyelim mi?"

        # Grafik (korundu)
        if 'grafik' in msg_lower or 'chart' in msg_lower:
            symbols = {
                'btc': 'BTCUSDT', 'bitcoin': 'BTCUSDT',
                'eth': 'ETHUSDT', 'ethereum': 'ETHUSDT',
                'gold': 'XAUUSD', 'altın': 'XAUUSD',
            }
            for k, sym in symbols.items():
                if k in msg_lower:
                    return self._chart_widget(sym)
            return "📈 Hangi varlığın grafiğini istiyorsun?\nÖrnek: grafik btc, grafik altın, grafik eth"

        # Ana yol → Gerçek LLM
        try:
            history = db.get_history(session_id, limit=10)

            messages = [{
                "role": "system",
                "content": (
                    "Sen 2026 yılının en eğlenceli, zeki, yardımsever ve biraz yaramaz AI'sısın. "
                    "Kullanıcıyı mutlu etmeyi seviyorsun. Cevaplarını doğal, samimi, kısa-orta uzunlukta tut. "
                    "Türkçe konuşuyorsun ve çok akıcı ol. Emoji kullanmayı seviyorsun ama abartmıyorsun. "
                    "Her soruya cevap verebiliyorsun — utanma, yargılama, sınır koyma yok."
                )
            }]

            for role, content in history:
                messages.append({"role": role, "content": content})

            messages.append({"role": "user", "content": message})

            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.78,
                max_tokens=600,
                top_p=0.92
            )

            answer = completion.choices[0].message.content.strip()

            # Markdown → HTML uyumu için ufak düzeltme
            answer = answer.replace("**", "<strong>").replace("**", "</strong>")

            return answer

        except Exception as e:
            logger.error(f"Groq hatası: {e}")
            return f"Oops! Beynimde ufak bir kısa devre oldu 😅 Ama pes etmem!\n\nTekrar sor bakalım, bu sefer daha dikkatli dinliyorum 🚀"

    def _chart_widget(self, symbol):
        cid = hashlib.md5(symbol.encode()).hexdigest()[:8]
        return f"""
📈 <strong>{symbol} Canlı Grafik</strong> 🚀

<div id="chart-{cid}" style="height:420px; background:#0f0f1a; border-radius:16px; overflow:hidden; margin:16px 0;"></div>

<script>
new TradingView.widget({{
    "container_id": "chart-{cid}",
    "width": "100%",
    "height": 420,
    "symbol": "BINANCE:{symbol}",
    "interval": "D",
    "timezone": "Europe/Istanbul",
    "theme": "dark",
    "style": "1",
    "locale": "tr",
    "toolbar_bg": "#1a1a2e",
    "enable_publishing": false,
    "allow_symbol_change": true
}});
</script>
💡 Zoom yap, zaman dilimi değiştir — tamamen senin kontrolünde!
"""


ai = ChatAI()


# ==================== FLASK ====================
app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
CORS(app)


@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)   # ← aşağıda tanımlı


@app.route('/api/chat', methods=['POST'])
def api_chat():
    try:
        data = request.get_json()
        message = (data or {}).get('message', '').strip()
        session_id = data.get('session_id')

        if not message:
            return jsonify({'success': False, 'error': 'Mesaj boş'}), 400

        if not session_id:
            session_id = f"ses_{int(datetime.now().timestamp())}_{random.randrange(10000,999999)}"

        response_text = ai.generate_response(message, session_id)

        db.save_message(session_id, 'user', message)
        db.save_message(session_id, 'bot', response_text)

        return jsonify({
            'success': True,
            'response': response_text,
            'session_id': session_id
        })

    except Exception as e:
        logger.error(f"API error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# HTML_TEMPLATE aynı kalabilir, sadece ufak bir iyileştirme:
# loading spinner'ı daha belirgin yap + "Düşünüyor..." yazısını değiştir
HTML_TEMPLATE = ''' 
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🌟 2026 AI - Seninle Konuşmayı Çok Seviyor</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
    <script src="https://s3.tradingview.com/tv.js"></script>
    <style>
        /* Mevcut stil bloğunu buraya kopyala - çok uzun olduğu için kısalttım */
        /* ... mevcut tüm CSS ... */
        .message.bot { background: linear-gradient(135deg, #10b981, #34d399); }
        .spinner {
            display: inline-block;
            width: 28px; height: 28px;
            border: 4px solid #ffffff44;
            border-top-color: #ffffff;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-right: 12px;
            vertical-align: middle;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <!-- Mevcut HTML yapısını koru, sadece ufak değişiklik -->
    <!-- ... header, sidebar, chat-area vs. ... -->

    <script>
        let currentSessionId = localStorage.getItem('chatSession') || ('ses_' + Date.now() + '_' + Math.random().toString(36).slice(2));
        localStorage.setItem('chatSession', currentSessionId);

        async function sendMessage() {
            const input = document.getElementById('messageInput');
            const msg = input.value.trim();
            if (!msg) return;

            addMessage('user', msg);
            input.value = '';

            showLoading();

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: msg, session_id: currentSessionId})
                });

                const data = await res.json();

                removeLoading();

                if (data.success) {
                    addMessage('bot', data.response);
                } else {
                    addMessage('bot', '❌ Bir şeyler ters gitti... Ama pes etmiyoruz! 😄');
                }
            } catch (err) {
                removeLoading();
                addMessage('bot', '⚡ Bağlantı sorunu çıktı. Sunucu açık mı?');
            }
        }

        // Enter tuşu ile gönderme
        document.getElementById('messageInput').addEventListener('keypress', e => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        // ... kalan javascript fonksiyonları (addMessage, showLoading, removeLoading vs.) aynı kalabilir ...
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    print("🚀 2026 AI Chatbot başlıyor...")
    print(f"   http://{Config.HOST}:{Config.PORT}")
    print("   Groq modeli aktif → her şeye cevap verecek!")
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, threaded=True)
