"""
🤖 ICTSmartPro.ai - Modern AI Chatbot
Production-Ready | %100 Ücretsiz | Açık Kaynak
"""

import os
import re
import secrets
import sqlite3
import base64
import imghdr
import logging
from datetime import datetime
from io import BytesIO

import torch
from flask import Flask, render_template_string, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from PIL import Image, UnidentifiedImageError
from transformers import AutoModelForCausalLM, AutoTokenizer, BlipProcessor, BlipForConditionalGeneration
from duckduckgo_search import DDGS

# Logging ayarları
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# CORS - İzin verilen originler
ALLOWED_ORIGINS = [
    "https://ictsmartpro.ai",
    "https://www.ictsmartpro.ai",
    "http://localhost:5000",
    "http://127.0.0.1:5000"
]

CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}}, supports_credentials=True)

# Rate Limiting
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Güvenlik header'ları
@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    response.headers['Content-Security-Policy'] = "default-src 'self' 'unsafe-inline' 'unsafe-eval'; img-src 'self' data: https:;"
    return response

def sanitize_input(text):
    """Güvenli metin temizleme"""
    if not text:
        return ""
    # XSS koruması
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'<script.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()[:3000]

# ==================== CONFIG ====================

MODEL_NAME = "Qwen/Qwen2-1.5B-Instruct"
VISION_MODEL = "Salesforce/blip-image-captioning-base"
MAX_NEW_TOKENS = 512
MAX_CONTEXT_TOKENS = 2048
MAX_IMAGE_SIZE_MB = 5

# Veritabanı
DB_DIR = os.environ.get("DB_DIR", "/app/data")
DB_PATH = os.path.join(DB_DIR, "chat_history.db")

# Klasör oluştur
os.makedirs(DB_DIR, exist_ok=True)

# ==================== DATABASE ====================

def init_db():
    """Veritabanı başlatma"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_session (session_id)
            )
        ''')
        conn.commit()
        conn.close()
        logger.info(f"✓ Veritabanı hazır: {DB_PATH}")
    except Exception as e:
        logger.error(f"Veritabanı hatası: {e}")
        raise

def clean_old_messages():
    """Eski mesajları temizle"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE timestamp < datetime('now', '-30 days')")
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            logger.info(f"🧹 {deleted} eski mesaj temizlendi")
    except Exception as e:
        logger.error(f"Temizlik hatası: {e}")

# Veritabanı başlat
init_db()
clean_old_messages()

# ==================== AI MODEL ====================

class LocalAI:
    """Lokal AI motoru - Text ve Vision"""
    
    def __init__(self):
        logger.info("="*70)
        logger.info("🤖 AI MODELLERİ YÜKLENİYOR...")
        logger.info("="*70)
        
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"🖥️  Cihaz: {self.device.upper()}")
        
        if self.device == "cuda":
            logger.info(f"🎮 GPU: {torch.cuda.get_device_name(0)}")
        
        # Text model
        logger.info("📥 Qwen2-1.5B yükleniyor...")
        self.tokenizer = AutoTokenizer.from_pretrained(
            MODEL_NAME, 
            trust_remote_code=True,
            use_fast=True
        )
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
        self.model.eval()
        logger.info("✅ Qwen2 hazır")
        
        # Vision model (lazy load)
        self.vision_processor = None
        self.vision_model = None
        self.vision_loaded = False
        logger.info("ℹ️  BLIP (görsel) ilk kullanımda yüklenecek")
        logger.info("="*70)
    
    def load_vision(self):
        """Vision modeli lazy load"""
        if not self.vision_loaded:
            logger.info("📥 BLIP yükleniyor...")
            self.vision_processor = BlipProcessor.from_pretrained(VISION_MODEL)
            self.vision_model = BlipForConditionalGeneration.from_pretrained(
                VISION_MODEL,
                torch_dtype=torch.bfloat16 if self.device == "cuda" else torch.float32,
                device_map="auto" if self.device == "cuda" else None,
                low_cpu_mem_usage=True
            )
            self.vision_model.eval()
            self.vision_loaded = True
            logger.info("✅ BLIP hazır")
    
    def generate(self, prompt):
        """Text generation"""
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
                    temperature=0.7,
                    top_p=0.9,
                    top_k=50,
                    repetition_penalty=1.1,
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
            logger.error(f"Generate hatası: {e}")
            return "Üzgünüm, şu anda yanıt üretemiyorum. Lütfen tekrar deneyin."
    
    def describe_image(self, base64_str):
        """Görsel analizi"""
        self.load_vision()
        try:
            # Base64 decode
            img_bytes = base64.b64decode(base64_str)
            
            # Boyut kontrolü
            if len(img_bytes) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
                return f"⚠️ Görsel çok büyük (max {MAX_IMAGE_SIZE_MB}MB)"
            
            # Format kontrolü
            file_type = imghdr.what(None, img_bytes)
            allowed = {'jpeg', 'png', 'webp', 'gif', 'bmp'}
            if file_type not in allowed:
                return f"⚠️ Desteklenmeyen format: {file_type}"
            
            # Resmi aç ve doğrula
            try:
                image = Image.open(BytesIO(img_bytes))
                image.verify()
                image = Image.open(BytesIO(img_bytes)).convert("RGB")
            except (UnidentifiedImageError, Exception) as e:
                logger.error(f"Resim doğrulama hatası: {e}")
                return "⚠️ Geçersiz resim dosyası"
            
            # Çözünürlük kontrolü
            if max(image.size) > 4000:
                return "⚠️ Çözünürlük çok yüksek (max 4000px)"
            
            # Yeniden boyutlandır
            if max(image.size) > 896:
                image.thumbnail((896, 896), Image.Resampling.LANCZOS)
            
            # Vision model inference
            inputs = self.vision_processor(images=image, return_tensors="pt").to(self.device)
            
            with torch.no_grad():
                output = self.vision_model.generate(
                    **inputs, 
                    max_length=100, 
                    num_beams=4,
                    temperature=0.8
                )
            
            caption = self.vision_processor.decode(output[0], skip_special_tokens=True).strip()
            
            # Türkçe yanıt
            return f"🖼️ **Görselde gördüklerim:**\n{caption}\n\n*Bu görselle ilgili sorularınızı sorabilirsiniz.*"
        
        except base64.binascii.Error:
            return "⚠️ Geçersiz base64 formatı"
        except Exception as e:
            logger.error(f"Görsel işleme hatası: {e}")
            return "⚠️ Görsel analiz edilemedi"

# AI motorunu başlat
ai = LocalAI()

# ==================== HELPERS ====================

def get_history(session_id, limit=8):
    """Sohbet geçmişi"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
            (session_id, limit)
        )
        rows = c.fetchall()
        conn.close()
        return list(reversed(rows))
    except Exception as e:
        logger.error(f"History hatası: {e}")
        return []

def save_message(session_id, role, content):
    """Mesaj kaydet"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content[:5000])
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Save hatası: {e}")

def needs_web_search(text):
    """Web araması gerekli mi?"""
    text = text.lower()
    triggers = [
        "haber", "güncel", "bugün", "fiyat", "ara", "bul", 
        "kim", "nedir", "nerede", "ne zaman", "kaç", "hangi",
        "son", "yeni", "şimdi", "anlat", "söyle"
    ]
    return any(t in text for t in triggers)

def do_web_search(query):
    """Web araması yap"""
    try:
        ddgs = DDGS(timeout=8)
        results = list(ddgs.text(query, max_results=4, region="tr-tr", safesearch="moderate"))
        
        if not results:
            return "", []
        
        output = "🔍 **Web'den güncel bilgiler:**\n\n"
        sources = []
        
        for i, r in enumerate(results, 1):
            title = r.get('title', '')[:100]
            body = r.get('body', '')[:150]
            href = r.get('href', '')
            
            output += f"**{i}.** {title}\n{body}...\n\n"
            if href:
                sources.append(href)
        
        return output, sources
    except Exception as e:
        logger.error(f"Web arama hatası: {e}")
        return "", []

def process_message(message, session_id, image_b64=None):
    """Ana mesaj işleme"""
    try:
        message = sanitize_input(message)
        history = get_history(session_id)
        context_parts = []
        sources = []
        
        # Görsel varsa analiz et
        if image_b64:
            description = ai.describe_image(image_b64)
            if description.startswith("⚠️"):
                return {
                    "text": description,
                    "sources": [],
                    "timestamp": datetime.now().strftime("%H:%M")
                }
            context_parts.append(description)
        
        # Web araması gerekli mi?
        if needs_web_search(message) and not image_b64:
            search_text, srcs = do_web_search(message)
            if search_text:
                context_parts.append(search_text)
                sources.extend(srcs)
        
        # Prompt oluştur
        messages = [{
            "role": "system",
            "content": """Sen ictsmartpro.ai'nin akıllı, samimi ve yardımsever AI asistanısın. 

Özellikler:
- Doğal ve sıcak bir dille konuşursun
- Kısa, öz ve anlaşılır yanıtlar verirsin
- Türkçe yazım kurallarına dikkat edersin
- Emojileri uygun yerlerde kullanırsın
- Kullanıcıya değer katan bilgiler sunarsun
- Gerektiğinde detaylı açıklama yaparsın

Unutma: Sen bir insan değilsin, dürüst bir AI asistanısın."""
        }]
        
        # Geçmiş ekle (son 5 mesaj)
        for role, content in history[-5:]:
            messages.append({"role": role, "content": content})
        
        # Kullanıcı mesajı + ek bilgiler
        user_content = message
        if context_parts:
            user_content += "\n\n**Ek Bilgiler:**\n" + "\n".join(context_parts)
        
        messages.append({"role": "user", "content": user_content})
        
        # Prompt şablonu
        prompt = ai.tokenizer.apply_chat_template(
            messages, 
            tokenize=False, 
            add_generation_prompt=True
        )
        
        # Yanıt üret
        response = ai.generate(prompt)
        
        # Kaydet
        save_message(session_id, "user", message)
        save_message(session_id, "assistant", response)
        
        return {
            "text": response,
            "sources": sources,
            "timestamp": datetime.now().strftime("%H:%M")
        }
        
    except Exception as e:
        logger.error(f"Process hatası: {e}")
        return {
            "text": "Üzgünüm, bir hata oluştu. Lütfen tekrar deneyin.",
            "sources": [],
            "timestamp": datetime.now().strftime("%H:%M")
        }

# ==================== HTML TEMPLATE ====================

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Chatbot • ictsmartpro.ai</title>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0e27;
            --bg-secondary: #141937;
            --bg-tertiary: #1e2447;
            --accent-primary: #00f5ff;
            --accent-secondary: #ff006e;
            --accent-gradient: linear-gradient(135deg, #00f5ff 0%, #ff006e 100%);
            --text-primary: #ffffff;
            --text-secondary: #a0a8c5;
            --text-muted: #6b7394;
            --success: #00ff9f;
            --warning: #ffb800;
            --error: #ff4757;
            --shadow-lg: 0 20px 60px rgba(0, 245, 255, 0.15);
            --shadow-md: 0 10px 30px rgba(0, 0, 0, 0.3);
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'DM Sans', -apple-system, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            overflow: hidden;
            height: 100vh;
        }

        /* Animated background */
        .bg-animation {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 0;
            background: 
                radial-gradient(circle at 20% 50%, rgba(0, 245, 255, 0.1) 0%, transparent 50%),
                radial-gradient(circle at 80% 80%, rgba(255, 0, 110, 0.1) 0%, transparent 50%);
            animation: bgPulse 8s ease-in-out infinite;
        }

        @keyframes bgPulse {
            0%, 100% { opacity: 0.5; transform: scale(1); }
            50% { opacity: 0.8; transform: scale(1.1); }
        }

        .container {
            position: relative;
            z-index: 1;
            max-width: 1400px;
            height: 100vh;
            margin: 0 auto;
            display: grid;
            grid-template-columns: 320px 1fr;
            gap: 24px;
            padding: 24px;
        }

        /* Sidebar */
        .sidebar {
            background: var(--bg-secondary);
            border-radius: 24px;
            padding: 32px 24px;
            display: flex;
            flex-direction: column;
            gap: 24px;
            box-shadow: var(--shadow-md);
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 12px;
            padding-bottom: 24px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }

        .logo-icon {
            width: 48px;
            height: 48px;
            background: var(--accent-gradient);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            animation: logoPulse 2s ease-in-out infinite;
        }

        @keyframes logoPulse {
            0%, 100% { transform: scale(1); box-shadow: 0 0 20px rgba(0, 245, 255, 0.3); }
            50% { transform: scale(1.05); box-shadow: 0 0 30px rgba(255, 0, 110, 0.5); }
        }

        .logo-text {
            flex: 1;
        }

        .logo-text h1 {
            font-size: 20px;
            font-weight: 700;
            background: var(--accent-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .logo-text p {
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 4px;
        }

        .features {
            flex: 1;
        }

        .feature-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px;
            margin-bottom: 8px;
            border-radius: 12px;
            background: var(--bg-tertiary);
            border: 1px solid rgba(255, 255, 255, 0.05);
            transition: all 0.3s ease;
        }

        .feature-item:hover {
            background: rgba(0, 245, 255, 0.1);
            border-color: var(--accent-primary);
            transform: translateX(4px);
        }

        .feature-icon {
            width: 40px;
            height: 40px;
            background: var(--bg-secondary);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
        }

        .feature-text h3 {
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 2px;
        }

        .feature-text p {
            font-size: 12px;
            color: var(--text-muted);
        }

        .stats {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }

        .stat-card {
            background: var(--bg-tertiary);
            padding: 16px;
            border-radius: 12px;
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .stat-value {
            font-size: 24px;
            font-weight: 700;
            background: var(--accent-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .stat-label {
            font-size: 11px;
            color: var(--text-muted);
            margin-top: 4px;
        }

        /* Chat area */
        .chat-area {
            display: flex;
            flex-direction: column;
            height: 100%;
            background: var(--bg-secondary);
            border-radius: 24px;
            overflow: hidden;
            box-shadow: var(--shadow-lg);
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .chat-header {
            background: var(--bg-tertiary);
            padding: 20px 32px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .status {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .status-dot {
            width: 12px;
            height: 12px;
            background: var(--success);
            border-radius: 50%;
            animation: statusPulse 2s ease-in-out infinite;
            box-shadow: 0 0 10px var(--success);
        }

        @keyframes statusPulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .status-text {
            font-size: 14px;
            font-weight: 600;
        }

        .header-actions {
            display: flex;
            gap: 8px;
        }

        .action-btn {
            width: 40px;
            height: 40px;
            background: var(--bg-secondary);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 18px;
        }

        .action-btn:hover {
            background: var(--accent-primary);
            color: var(--bg-primary);
            transform: scale(1.1);
            border-color: var(--accent-primary);
        }

        .messages {
            flex: 1;
            padding: 32px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 24px;
        }

        .messages::-webkit-scrollbar {
            width: 8px;
        }

        .messages::-webkit-scrollbar-track {
            background: transparent;
        }

        .messages::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 4px;
        }

        .messages::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.2);
        }

        .message {
            display: flex;
            gap: 16px;
            animation: messageSlide 0.4s ease;
        }

        @keyframes messageSlide {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        .message.user {
            flex-direction: row-reverse;
        }

        .message-avatar {
            width: 48px;
            height: 48px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            flex-shrink: 0;
        }

        .message.bot .message-avatar {
            background: var(--accent-gradient);
            box-shadow: 0 4px 20px rgba(0, 245, 255, 0.3);
        }

        .message.user .message-avatar {
            background: var(--bg-tertiary);
            border: 2px solid rgba(255, 255, 255, 0.1);
        }

        .message-content {
            flex: 1;
            max-width: 80%;
        }

        .message-bubble {
            background: var(--bg-tertiary);
            padding: 20px 24px;
            border-radius: 20px;
            line-height: 1.6;
            font-size: 15px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .message.bot .message-bubble {
            border-left: 3px solid var(--accent-primary);
            background: linear-gradient(135deg, var(--bg-tertiary) 0%, rgba(0, 245, 255, 0.05) 100%);
        }

        .message.user .message-bubble {
            background: rgba(255, 0, 110, 0.1);
            border: 1px solid rgba(255, 0, 110, 0.2);
            text-align: right;
        }

        .message-meta {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 8px;
            font-size: 12px;
            color: var(--text-muted);
        }

        .message.user .message-meta {
            justify-content: flex-end;
        }

        .sources {
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
        }

        .sources-title {
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .source-link {
            display: block;
            color: var(--accent-primary);
            text-decoration: none;
            font-size: 12px;
            padding: 6px 0;
            transition: all 0.2s ease;
        }

        .source-link:hover {
            color: var(--accent-secondary);
            padding-left: 8px;
        }

        .typing-indicator {
            display: none;
            align-items: center;
            gap: 6px;
            color: var(--text-muted);
            font-size: 13px;
        }

        .typing-indicator.active {
            display: flex;
        }

        .typing-dot {
            width: 8px;
            height: 8px;
            background: var(--accent-primary);
            border-radius: 50%;
            animation: typingBounce 1.4s infinite;
        }

        .typing-dot:nth-child(2) {
            animation-delay: 0.2s;
        }

        .typing-dot:nth-child(3) {
            animation-delay: 0.4s;
        }

        @keyframes typingBounce {
            0%, 60%, 100% { transform: translateY(0); }
            30% { transform: translateY(-10px); }
        }

        /* Input area */
        .input-area {
            background: var(--bg-tertiary);
            padding: 24px 32px;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
        }

        .input-tools {
            display: flex;
            gap: 12px;
            margin-bottom: 16px;
        }

        .tool-btn {
            padding: 10px 16px;
            background: var(--bg-secondary);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            color: var(--text-secondary);
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 14px;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .tool-btn:hover {
            background: rgba(0, 245, 255, 0.1);
            border-color: var(--accent-primary);
            color: var(--accent-primary);
            transform: translateY(-2px);
        }

        .image-preview {
            display: none;
            position: relative;
            max-width: 200px;
            margin-bottom: 16px;
        }

        .image-preview.active {
            display: block;
        }

        .preview-img {
            width: 100%;
            border-radius: 12px;
            border: 2px solid var(--accent-primary);
            box-shadow: 0 4px 20px rgba(0, 245, 255, 0.3);
        }

        .preview-remove {
            position: absolute;
            top: -8px;
            right: -8px;
            width: 28px;
            height: 28px;
            background: var(--error);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 16px;
            transition: all 0.3s ease;
        }

        .preview-remove:hover {
            transform: scale(1.1);
            box-shadow: 0 4px 15px rgba(255, 71, 87, 0.5);
        }

        .input-wrapper {
            display: flex;
            gap: 12px;
            align-items: flex-end;
        }

        #messageInput {
            flex: 1;
            background: var(--bg-secondary);
            border: 2px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 16px 20px;
            color: var(--text-primary);
            font-family: inherit;
            font-size: 15px;
            resize: none;
            max-height: 120px;
            transition: all 0.3s ease;
        }

        #messageInput:focus {
            outline: none;
            border-color: var(--accent-primary);
            box-shadow: 0 0 20px rgba(0, 245, 255, 0.2);
        }

        #messageInput::placeholder {
            color: var(--text-muted);
        }

        #sendBtn {
            width: 56px;
            height: 56px;
            background: var(--accent-gradient);
            border: none;
            border-radius: 14px;
            color: var(--text-primary);
            font-size: 24px;
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 4px 20px rgba(0, 245, 255, 0.3);
        }

        #sendBtn:hover:not(:disabled) {
            transform: scale(1.05) rotate(-5deg);
            box-shadow: 0 6px 30px rgba(255, 0, 110, 0.5);
        }

        #sendBtn:active:not(:disabled) {
            transform: scale(0.95);
        }

        #sendBtn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Responsive */
        @media (max-width: 1024px) {
            .container {
                grid-template-columns: 1fr;
            }

            .sidebar {
                display: none;
            }
        }

        @media (max-width: 768px) {
            .container {
                padding: 12px;
                gap: 12px;
            }

            .messages {
                padding: 20px 16px;
            }

            .message-content {
                max-width: 90%;
            }

            .input-area {
                padding: 16px;
            }
        }

        /* Welcome message */
        .welcome-card {
            background: linear-gradient(135deg, rgba(0, 245, 255, 0.1) 0%, rgba(255, 0, 110, 0.1) 100%);
            border: 2px solid rgba(0, 245, 255, 0.3);
            border-radius: 20px;
            padding: 32px;
            text-align: center;
            animation: welcomeFloat 3s ease-in-out infinite;
        }

        @keyframes welcomeFloat {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-10px); }
        }

        .welcome-title {
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 16px;
            background: var(--accent-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .welcome-text {
            font-size: 16px;
            color: var(--text-secondary);
            line-height: 1.6;
            margin-bottom: 24px;
        }

        .welcome-features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 16px;
            margin-top: 24px;
        }

        .welcome-feature {
            background: var(--bg-tertiary);
            padding: 16px;
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .welcome-feature-icon {
            font-size: 32px;
            margin-bottom: 8px;
        }

        .welcome-feature-text {
            font-size: 13px;
            color: var(--text-secondary);
        }
    </style>
</head>
<body>
    <div class="bg-animation"></div>
    
    <div class="container">
        <!-- Sidebar -->
        <div class="sidebar">
            <div class="logo">
                <div class="logo-icon">🤖</div>
                <div class="logo-text">
                    <h1>AI Chatbot</h1>
                    <p>ictsmartpro.ai</p>
                </div>
            </div>

            <div class="features">
                <div class="feature-item">
                    <div class="feature-icon">💬</div>
                    <div class="feature-text">
                        <h3>Akıllı Sohbet</h3>
                        <p>Doğal konuşma</p>
                    </div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">🖼️</div>
                    <div class="feature-text">
                        <h3>Görsel Analizi</h3>
                        <p>Resim okuma</p>
                    </div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">🔍</div>
                    <div class="feature-text">
                        <h3>Web Araması</h3>
                        <p>Güncel bilgi</p>
                    </div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">🧠</div>
                    <div class="feature-text">
                        <h3>Hafıza</h3>
                        <p>Geçmiş hatırlama</p>
                    </div>
                </div>
            </div>

            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value">24/7</div>
                    <div class="stat-label">Aktif</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">⚡</div>
                    <div class="stat-label">Hızlı</div>
                </div>
            </div>
        </div>

        <!-- Chat Area -->
        <div class="chat-area">
            <div class="chat-header">
                <div class="status">
                    <div class="status-dot"></div>
                    <div class="status-text">AI Asistan • Çevrimiçi</div>
                </div>
                <div class="header-actions">
                    <div class="action-btn" onclick="clearChat()" title="Sohbeti temizle">🗑️</div>
                    <div class="action-btn" onclick="exportChat()" title="Dışa aktar">💾</div>
                </div>
            </div>

            <div class="messages" id="messages">
                <div class="welcome-card">
                    <div class="welcome-title">👋 Merhaba!</div>
                    <div class="welcome-text">
                        Ben <strong>ictsmartpro.ai</strong>'nin AI asistanıyım.<br>
                        Size nasıl yardımcı olabilirim?
                    </div>
                    <div class="welcome-features">
                        <div class="welcome-feature">
                            <div class="welcome-feature-icon">💬</div>
                            <div class="welcome-feature-text">Sohbet Et</div>
                        </div>
                        <div class="welcome-feature">
                            <div class="welcome-feature-icon">🖼️</div>
                            <div class="welcome-feature-text">Görsel Gönder</div>
                        </div>
                        <div class="welcome-feature">
                            <div class="welcome-feature-icon">🔍</div>
                            <div class="welcome-feature-text">Bilgi Ara</div>
                        </div>
                        <div class="welcome-feature">
                            <div class="welcome-feature-icon">❓</div>
                            <div class="welcome-feature-text">Soru Sor</div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="input-area">
                <div class="input-tools">
                    <div class="tool-btn" onclick="document.getElementById('imageInput').click()">
                        📎 Görsel Ekle
                    </div>
                    <input type="file" id="imageInput" accept="image/*" style="display: none;">
                </div>

                <div class="image-preview" id="imagePreview">
                    <img id="previewImg" class="preview-img" alt="Önizleme">
                    <div class="preview-remove" onclick="removeImage()">✕</div>
                </div>

                <div class="input-wrapper">
                    <textarea 
                        id="messageInput" 
                        rows="1" 
                        placeholder="Mesajınızı yazın... (Enter: gönder, Shift+Enter: yeni satır)"
                    ></textarea>
                    <button id="sendBtn" onclick="sendMessage()">
                        🚀
                    </button>
                </div>

                <div class="typing-indicator" id="typingIndicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <span style="margin-left: 8px;">AI düşünüyor...</span>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Global değişkenler
        let sessionId = localStorage.getItem('chatSession') || 'session_' + Date.now();
        localStorage.setItem('chatSession', sessionId);
        
        let currentImage = null;
        let isProcessing = false;
        let messageCount = parseInt(localStorage.getItem('messageCount') || '0');

        // DOM elementleri
        const messagesDiv = document.getElementById('messages');
        const messageInput = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendBtn');
        const imageInput = document.getElementById('imageInput');
        const imagePreview = document.getElementById('imagePreview');
        const previewImg = document.getElementById('previewImg');
        const typingIndicator = document.getElementById('typingIndicator');

        // Otomatik yükseklik ayarı
        messageInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 120) + 'px';
            updateSendButton();
        });

        // Enter tuşu kontrolü
        messageInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (canSend()) sendMessage();
            }
        });

        // Görsel seçimi
        imageInput.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (!file) return;

            // Boyut kontrolü
            if (file.size > 5 * 1024 * 1024) {
                alert('⚠️ Görsel 5MB\'dan küçük olmalıdır!');
                return;
            }

            // Format kontrolü
            if (!file.type.startsWith('image/')) {
                alert('⚠️ Lütfen geçerli bir görsel dosyası seçin!');
                return;
            }

            const reader = new FileReader();
            reader.onload = function(ev) {
                currentImage = ev.target.result.split(',')[1];
                previewImg.src = ev.target.result;
                imagePreview.classList.add('active');
                updateSendButton();
            };
            reader.readAsDataURL(file);
        });

        // Görseli kaldır
        function removeImage() {
            currentImage = null;
            imageInput.value = '';
            imagePreview.classList.remove('active');
            updateSendButton();
        }

        // Gönderme kontrolü
        function canSend() {
            const hasText = messageInput.value.trim().length > 0;
            const hasImage = currentImage !== null;
            return (hasText || hasImage) && !isProcessing;
        }

        // Buton durumu güncelle
        function updateSendButton() {
            sendBtn.disabled = !canSend();
        }

        // Mesaj gönder
        async function sendMessage() {
            if (!canSend()) return;

            const text = messageInput.value.trim();
            const image = currentImage;

            // UI güncelle
            isProcessing = true;
            updateSendButton();
            
            const now = new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
            
            // Kullanıcı mesajını göster
            addMessage('user', text || '🖼️ [Görsel gönderildi]', now);
            
            // Input'u temizle
            messageInput.value = '';
            messageInput.style.height = 'auto';
            removeImage();

            // Typing indicator
            typingIndicator.classList.add('active');

            try {
                const response = await fetch('/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        message: text,
                        image: image,
                        session: sessionId
                    })
                });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const data = await response.json();
                
                // AI yanıtını göster
                addMessage('bot', data.text, data.timestamp, data.sources);
                
                // İstatistik güncelle
                messageCount++;
                localStorage.setItem('messageCount', messageCount);

            } catch (error) {
                console.error('Hata:', error);
                addMessage('bot', '❌ Üzgünüm, bir hata oluştu. Lütfen tekrar deneyin.', now);
            } finally {
                typingIndicator.classList.remove('active');
                isProcessing = false;
                updateSendButton();
                messageInput.focus();
            }
        }

        // Mesaj ekle
        function addMessage(role, text, time, sources = []) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${role}`;
            
            const isBot = role === 'bot';
            const avatar = isBot ? '🤖' : '👤';
            
            let html = `
                <div class="message-avatar">${avatar}</div>
                <div class="message-content">
                    <div class="message-bubble">
                        ${formatText(text)}
                    </div>
                    <div class="message-meta">
                        <span>${time}</span>
            `;
            
            if (sources && sources.length > 0) {
                html += `
                    </div>
                    <div class="sources">
                        <div class="sources-title">🔗 Kaynaklar:</div>
                        ${sources.map((url, i) => `
                            <a href="${url}" target="_blank" rel="noopener noreferrer" class="source-link">
                                ${i + 1}. ${truncate(url, 50)}
                            </a>
                        `).join('')}
                    </div>
                `;
            } else {
                html += `</div>`;
            }
            
            html += `</div>`;
            messageDiv.innerHTML = html;
            
            messagesDiv.appendChild(messageDiv);
            scrollToBottom();
        }

        // Metin formatlama
        function formatText(text) {
            return text
                .replace(/\n/g, '<br>')
                .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.*?)\*/g, '<em>$1</em>');
        }

        // URL kısaltma
        function truncate(str, maxLen) {
            if (str.length <= maxLen) return str;
            return str.substring(0, maxLen) + '...';
        }

        // Scroll en alta
        function scrollToBottom() {
            setTimeout(() => {
                messagesDiv.scrollTop = messagesDiv.scrollHeight;
            }, 100);
        }

        // Sohbeti temizle
        async function clearChat() {
            if (!confirm('Sohbet geçmişi silinsin mi?')) return;

            try {
                const response = await fetch('/clear', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session: sessionId })
                });

                if (response.ok) {
                    messagesDiv.innerHTML = `
                        <div class="welcome-card">
                            <div class="welcome-title">✅ Sohbet Temizlendi!</div>
                            <div class="welcome-text">Yeni bir sohbet başlatabilirsiniz.</div>
                        </div>
                    `;
                    
                    sessionId = 'session_' + Date.now();
                    localStorage.setItem('chatSession', sessionId);
                    messageCount = 0;
                    localStorage.setItem('messageCount', '0');
                }
            } catch (error) {
                console.error('Temizleme hatası:', error);
                alert('❌ Sohbet temizlenemedi. Lütfen tekrar deneyin.');
            }
        }

        // Sohbeti dışa aktar
        function exportChat() {
            const messages = Array.from(document.querySelectorAll('.message'));
            const text = messages.map(msg => {
                const role = msg.classList.contains('user') ? 'SİZ' : 'AI';
                const bubble = msg.querySelector('.message-bubble');
                const content = bubble ? bubble.innerText : '';
                const time = msg.querySelector('.message-meta span')?.innerText || '';
                return `[${time}] ${role}:\n${content}`;
            }).join('\n\n---\n\n');

            const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `sohbet_${sessionId}_${Date.now()}.txt`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }

        // İlk odaklanma
        messageInput.focus();
    </script>
</body>
</html>'''

# ==================== ROUTES ====================

@app.route('/')
def home():
    """Ana sayfa"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/chat', methods=['POST'])
@limiter.limit("40 per minute")
def chat():
    """Chat endpoint"""
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Geçersiz istek"}), 400

        message = data.get('message', '').strip()
        image = data.get('image')
        session = data.get('session', 'default')
        
        if not message and not image:
            return jsonify({"error": "Mesaj veya görsel gerekli"}), 400
        
        # Mesajı işle
        result = process_message(message, session, image)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Chat endpoint hatası: {e}")
        return jsonify({
            "text": "Üzgünüm, bir hata oluştu. Lütfen tekrar deneyin.",
            "sources": [],
            "timestamp": datetime.now().strftime("%H:%M")
        }), 500

@app.route('/clear', methods=['POST'])
@limiter.limit("10 per hour")
def clear():
    """Sohbet geçmişini temizle"""
    try:
        data = request.get_json(silent=True)
        session = data.get('session') if data else None
        
        if session:
            conn = sqlite3.connect(DB_PATH, timeout=5)
            c = conn.cursor()
            c.execute("DELETE FROM messages WHERE session_id = ?", (session,))
            conn.commit()
            conn.close()
            logger.info(f"Session temizlendi: {session}")
        
        return '', 204
    except Exception as e:
        logger.error(f"Clear hatası: {e}")
        return '', 500

@app.route('/health')
def health():
    """Sağlık kontrolü"""
    return jsonify({
        "status": "healthy",
        "model": MODEL_NAME,
        "device": ai.device,
        "timestamp": datetime.now().isoformat()
    })

# ==================== START ====================

if __name__ == '__main__':
    logger.info("\n" + "="*70)
    logger.info("🚀 ICTSMARTPRO.AI - AI CHATBOT")
    logger.info("="*70)
    logger.info(f"📍 Model: {MODEL_NAME}")
    logger.info(f"🖥️  Cihaz: {ai.device.upper()}")
    logger.info(f"🗄️  Database: {DB_PATH}")
    logger.info("="*70 + "\n")
    
    port = int(os.environ.get("PORT", 5000))
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True
    )
