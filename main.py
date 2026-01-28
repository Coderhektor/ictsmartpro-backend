"""
Production-Ready AI Chatbot for ictsmartpro.ai
- %100 Ücretsiz & Açık Kaynak
- API Key Gerektirmez
- Tamamen Lokal Çalışır
- Güvenli & Hızlı
"""

from flask import Flask, render_template_string, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BlipProcessor, BlipForConditionalGeneration
from PIL import Image
import io
import base64
from datetime import datetime
from duckduckgo_search import DDGS
import sqlite3
import secrets
import os
import re

# ==================== FLASK APP ====================

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# CORS - Sadece ictsmartpro.ai
ALLOWED_ORIGINS = [
    "https://ictsmartpro.ai",
    "https://www.ictsmartpro.ai",
    "http://localhost:5000",
    "http://127.0.0.1:5000"
]

CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}}, supports_credentials=True)

# Rate Limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per day", "30 per hour"],
    storage_uri="memory://"
)

# ==================== GÜVENLİK ====================

@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response

def sanitize_input(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'<script.*?</script>', '', text, flags=re.DOTALL)
    return text.strip()[:2000]

# ==================== CONFIG ====================

MODEL_NAME = "Qwen/Qwen2-1.5B-Instruct"
VISION_MODEL = "Salesforce/blip-image-captioning-base"
DB_PATH = "chat_history.db"
MAX_NEW_TOKENS = 400
MAX_CONTEXT_TOKENS = 2400
MAX_IMAGE_SIZE_MB = 5

# ==================== DATABASE ====================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    print(f"✓ Veritabanı hazır: {DB_PATH}")

def clean_old_messages():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE timestamp < datetime('now', '-30 days')")
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            print(f"🧹 {deleted} eski mesaj temizlendi")
    except Exception as e:
        print(f"Temizlik hatası: {e}")

init_db()

# ==================== AI MODEL ====================

class LocalAI:
    def __init__(self):
        print("\n" + "="*70)
        print("🤖 AI MODELLERİ YÜKLENİYOR...")
        print("="*70)
        
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"🖥️  Cihaz: {self.device.upper()}")
        
        if self.device == "cuda":
            print(f"🎮 GPU: {torch.cuda.get_device_name(0)}")
        
        print("\n📥 Qwen2-1.5B yükleniyor...")
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
            self.tokenizer.padding_side = "left"
        
        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL_NAME,
            torch_dtype=torch.bfloat16 if self.device == "cuda" else torch.float32,
            device_map="auto" if self.device == "cuda" else None,
            low_cpu_mem_usage=True,
            trust_remote_code=True
        )
        print("✅ Qwen2 hazır")
        
        self.vision_processor = None
        self.vision_model = None
        self.vision_loaded = False
        print("ℹ️  BLIP (görsel) ilk kullanımda yüklenecek\n")
        print("="*70 + "\n")
    
    def load_vision(self):
        if not self.vision_loaded:
            print("📥 BLIP yükleniyor...")
            self.vision_processor = BlipProcessor.from_pretrained(VISION_MODEL)
            self.vision_model = BlipForConditionalGeneration.from_pretrained(
                VISION_MODEL,
                torch_dtype=torch.bfloat16 if self.device == "cuda" else torch.float32,
                device_map="auto" if self.device == "cuda" else None,
                low_cpu_mem_usage=True
            )
            self.vision_loaded = True
            print("✅ BLIP hazır")
    
    def generate(self, prompt):
        try:
            inputs = self.tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=MAX_CONTEXT_TOKENS
            ).to(self.device)
            
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=MAX_NEW_TOKENS,
                    temperature=0.75,
                    top_p=0.92,
                    repetition_penalty=1.08,
                    do_sample=True,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id
                )
            
            response = self.tokenizer.decode(
                outputs[0][inputs.input_ids.shape[1]:],
                skip_special_tokens=True
            ).strip()
            
            return sanitize_input(response)
        except Exception as e:
            print(f"❌ Generate hatası: {e}")
            return "Üzgünüm, yanıt üretemiyorum. Lütfen tekrar deneyin."
    
    def describe_image(self, base64_str):
        self.load_vision()
        try:
            img_bytes = base64.b64decode(base64_str)
            
            if len(img_bytes) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
                return f"⚠️ Görsel çok büyük (max {MAX_IMAGE_SIZE_MB}MB)"
            
            image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            
            if max(image.size) > 896:
                image.thumbnail((896, 896), Image.Resampling.LANCZOS)
            
            inputs = self.vision_processor(images=image, return_tensors="pt").to(self.device)
            
            with torch.no_grad():
                output = self.vision_model.generate(**inputs, max_length=80, num_beams=3)
            
            caption = self.vision_processor.decode(output[0], skip_special_tokens=True).strip()
            return f"🖼️ Görselde: {caption}"
        except Exception as e:
            print(f"❌ Görsel hatası: {e}")
            return "⚠️ Görsel analiz edilemedi"

ai = LocalAI()

# ==================== HELPERS ====================

def get_history(session_id, limit=6):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
            (session_id, limit)
        )
        rows = c.fetchall()
        conn.close()
        return list(reversed(rows))
    except Exception as e:
        print(f"❌ History hatası: {e}")
        return []

def save_message(session_id, role, content):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content[:4000])
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Save hatası: {e}")

def needs_web_search(text):
    text = text.lower()
    triggers = ["haber", "güncel", "fiyat", "bugün", "ne oldu", "ara", "bul", "kim", "nedir", "nerede"]
    return any(t in text for t in triggers)

def do_web_search(query):
    try:
        ddgs = DDGS(timeout=10)
        results = list(ddgs.text(query, max_results=3, region="tr-tr", safesearch="moderate"))
        
        if not results:
            return "", []
        
        output = "🔍 Web'den güncel bilgiler:\n\n"
        sources = []
        
        for i, r in enumerate(results, 1):
            title = r.get('title', '')[:80]
            body = r.get('body', '')[:120]
            href = r.get('href', '')
            
            output += f"{i}. {title}\n   {body}...\n\n"
            if href:
                sources.append(href)
        
        return output, sources
    except Exception as e:
        print(f"❌ Web arama hatası: {e}")
        return "", []

def process_message(message, session_id, image_b64=None):
    try:
        message = sanitize_input(message)
        history = get_history(session_id)
        context_parts = []
        sources = []
        
        if image_b64:
            context_parts.append(ai.describe_image(image_b64))
        
        if needs_web_search(message) and not image_b64:
            search_text, srcs = do_web_search(message)
            if search_text:
                context_parts.append(search_text)
                sources.extend(srcs)
        
        messages = [{
            "role": "system",
            "content": "Sen ictsmartpro.ai'nin samimi, yardımsever ve akıllı Türk AI asistanısın. Doğal ve profesyonel konuş. Kısa ve net cevap ver."
        }]
        
        for role, content in history[-5:]:
            messages.append({"role": role, "content": content})
        
        user_content = message
        if context_parts:
            user_content += "\n\nEk bilgiler:\n" + "\n".join(context_parts)
        
        messages.append({"role": "user", "content": user_content})
        
        prompt = ai.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        response = ai.generate(prompt)
        
        save_message(session_id, "user", message)
        save_message(session_id, "assistant", response)
        
        return {
            "text": response,
            "sources": sources,
            "timestamp": datetime.now().strftime("%H:%M")
        }
    except Exception as e:
        print(f"❌ Process hatası: {e}")
        return {
            "text": "Bir hata oluştu, lütfen tekrar deneyin.",
            "sources": [],
            "timestamp": datetime.now().strftime("%H:%M")
        }

# ==================== HTML ====================

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Chatbot | ictsmartpro.ai</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 20px;
}
.chat-container {
    width: 100%;
    max-width: 900px;
    height: 90vh;
    background: white;
    border-radius: 24px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.3);
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 24px;
    text-align: center;
}
.header h1 { font-size: 1.8rem; margin-bottom: 8px; }
.header .domain { font-size: 1rem; opacity: 0.9; }
.badge {
    display: inline-flex;
    gap: 8px;
    background: rgba(255,255,255,0.2);
    padding: 6px 16px;
    border-radius: 20px;
    font-size: 0.85rem;
    margin-top: 12px;
}
.messages {
    flex: 1;
    padding: 20px;
    overflow-y: auto;
    background: #f7fafc;
}
.msg {
    margin: 16px 0;
    display: flex;
    animation: fadeIn 0.3s;
}
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}
.msg.user { justify-content: flex-end; }
.bubble {
    max-width: 75%;
    padding: 14px 18px;
    border-radius: 18px;
    line-height: 1.5;
    word-wrap: break-word;
}
.user .bubble {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border-bottom-right-radius: 4px;
}
.bot .bubble {
    background: white;
    border: 1px solid #e2e8f0;
    border-bottom-left-radius: 4px;
}
.time { font-size: 0.7rem; opacity: 0.6; margin-top: 6px; }
.sources {
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid #e2e8f0;
    font-size: 0.8rem;
}
.sources a {
    color: #667eea;
    text-decoration: none;
    display: block;
    margin: 4px 0;
}
.input-area {
    padding: 20px;
    background: white;
    border-top: 2px solid #e2e8f0;
}
.tools {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
}
textarea {
    width: 100%;
    padding: 14px;
    border: 2px solid #e2e8f0;
    border-radius: 16px;
    resize: none;
    font-size: 1rem;
    font-family: inherit;
    margin-bottom: 12px;
}
textarea:focus { outline: none; border-color: #667eea; }
button {
    padding: 12px 20px;
    border: none;
    border-radius: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
}
.send-btn {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    width: 100%;
}
.send-btn:hover { transform: scale(1.02); }
.send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.tool-btn { background: #f7fafc; color: #4a5568; }
.tool-btn:hover { background: #e2e8f0; }
#preview {
    max-width: 200px;
    max-height: 200px;
    margin: 12px 0;
    border-radius: 12px;
    border: 3px solid #667eea;
    display: none;
}
</style>
</head>
<body>
<div class="chat-container">
<div class="header">
<h1>🤖 AI Asistan</h1>
<div class="domain">ictsmartpro.ai</div>
<div class="badge">
<span>✅ Ücretsiz</span>
<span>•</span>
<span>🔒 Güvenli</span>
<span>•</span>
<span>⚡ Hızlı</span>
</div>
</div>

<div class="messages" id="messages">
<div class="msg bot">
<div class="bubble">
👋 <strong>Merhaba!</strong> Ben ictsmartpro.ai'nin AI asistanıyım.<br><br>
<strong>Yapabileceklerim:</strong><br>
• 💬 Doğal sohbet<br>
• 🖼️ Görsel analizi<br>
• 🔍 Web'de arama<br>
• 🧠 Geçmişi hatırlama<br><br>
Size nasıl yardımcı olabilirim? 😊
</div>
</div>
</div>

<div class="input-area">
<div class="tools">
<button class="tool-btn" onclick="document.getElementById('file').click()">📎 Görsel</button>
<button class="tool-btn" onclick="clearChat()">🗑️ Temizle</button>
<button class="tool-btn" onclick="exportChat()">💾 Dışa Aktar</button>
</div>
<input type="file" id="file" accept="image/*" style="display:none;">
<img id="preview" alt="Önizleme">
<textarea id="input" rows="3" placeholder="Mesaj yazın... (Enter ile gönderin)"></textarea>
<button class="send-btn" id="sendBtn" onclick="send()">Gönder 🚀</button>
</div>
</div>

<script>
let session = localStorage.getItem('chatId') || 'ch_' + Date.now();
localStorage.setItem('chatId', session);
let currentImage = null;
let isProcessing = false;

const messagesDiv = document.getElementById('messages');
const input = document.getElementById('input');
const sendBtn = document.getElementById('sendBtn');
const fileInput = document.getElementById('file');
const preview = document.getElementById('preview');

fileInput.onchange = e => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
        alert('⚠️ Dosya max 5MB olmalı!');
        return;
    }
    const reader = new FileReader();
    reader.onload = ev => {
        currentImage = ev.target.result.split(',')[1];
        preview.src = ev.target.result;
        preview.style.display = 'block';
    };
    reader.readAsDataURL(file);
};

input.onkeydown = e => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send();
    }
};

function addMsg(role, text, time, sources = []) {
    const div = document.createElement('div');
    div.className = 'msg ' + role;
    let html = '<div class="bubble">' + text.replace(/\n/g, '<br>') + '<div class="time">' + time + '</div>';
    if (sources.length) {
        html += '<div class="sources">🔗 Kaynaklar:<br>';
        sources.forEach((s, i) => html += '<a href="' + s + '" target="_blank">' + (i+1) + '. ' + s.slice(0, 50) + '...</a>');
        html += '</div>';
    }
    html += '</div>';
    div.innerHTML = html;
    messagesDiv.appendChild(div);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

async function send() {
    const text = input.value.trim();
    if ((!text && !currentImage) || isProcessing) return;
    
    isProcessing = true;
    sendBtn.disabled = true;
    sendBtn.textContent = '⏳ İşleniyor...';
    
    const now = new Date().toLocaleTimeString('tr-TR', {hour: '2-digit', minute: '2-digit'});
    addMsg('user', text || '🖼️ [Görsel]', now);
    input.value = '';
    
    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: text, image: currentImage, session: session})
        });
        const data = await response.json();
        addMsg('bot', data.text, data.timestamp, data.sources || []);
        currentImage = null;
        preview.style.display = 'none';
    } catch (e) {
        addMsg('bot', '❌ Hata: ' + e.message, now);
    } finally {
        isProcessing = false;
        sendBtn.disabled = false;
        sendBtn.textContent = 'Gönder 🚀';
    }
}

async function clearChat() {
    if (!confirm('Sohbet silinsin mi?')) return;
    await fetch('/clear', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({session})});
    messagesDiv.innerHTML = '';
    addMsg('bot', '✅ Temizlendi!', new Date().toLocaleTimeString('tr-TR', {hour: '2-digit', minute: '2-digit'}));
}

function exportChat() {
    const msgs = Array.from(document.querySelectorAll('.msg'));
    const text = msgs.map(m => {
        const role = m.classList.contains('user') ? 'SİZ' : 'AI';
        return role + ': ' + m.querySelector('.bubble').textContent.trim();
    }).join('\n\n');
    const blob = new Blob([text], {type: 'text/plain'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'sohbet-' + Date.now() + '.txt';
    a.click();
}
</script>
</body>
</html>'''

# ==================== ROUTES ====================

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/chat', methods=['POST'])
@limiter.limit("30 per minute")
def chat():
    try:
        data = request.json
        msg = data.get('message', '').strip()
        img = data.get('image')
        sid = data.get('session', 'default')
        
        if not msg and not img:
            return jsonify({"error": "Mesaj veya görsel gerekli"}), 400
        
        result = process_message(msg, sid, img)
        return jsonify(result)
    except Exception as e:
        print(f"❌ Chat hatası: {e}")
        return jsonify({"text": "Hata oluştu", "sources": [], "timestamp": datetime.now().strftime("%H:%M")}), 500

@app.route('/clear', methods=['POST'])
@limiter.limit("10 per hour")
def clear():
    try:
        data = request.json
        sid = data.get('session')
        if sid:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
            conn.commit()
            conn.close()
        return '', 204
    except:
        return '', 500

@app.route('/health')
def health():
    return jsonify({"status": "ok", "model": MODEL_NAME, "device": ai.device})

# ==================== START ====================

if __name__ == '__main__':
    print("\n" + "="*70)
    print("🚀 ICTSMARTPRO.AI - AI CHATBOT")
    print("="*70)
    print(f"📍 Sunucu: http://127.0.0.1:5000")
    print(f"🤖 Model: {MODEL_NAME}")
    print(f"🖥️  Device: {ai.device.upper()}")
    print("="*70 + "\n")
    
    clean_old_messages()
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True) kanka tamam mı proda alıyorum
