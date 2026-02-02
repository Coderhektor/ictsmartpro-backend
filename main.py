"""
ICTSmartPro Trading AI Platform
Production-Ready Trading Analysis with Qwen AI + Lightweight ML
Version: 5.2.0 - 2026 February - Intraday Interval Support
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel, Field

import yfinance as yf
import pandas as pd
import pandas_ta_classic as ta
import httpx
from dotenv import load_dotenv

# ==================== KONFIGÜRASYON ====================
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen/qwen3-coder:free")

RATE_LIMIT_PER_MINUTE = 15
RATE_LIMIT_PER_HOUR   = 150

# Desteklenen interval'lar (kullanıcıya gösterilecek + yfinance eşleşmesi)
SUPPORTED_INTERVALS = {
    "1m":   {"yf": "1m",   "label": "1 Dakika",   "max_days": 7},
    "3m":   {"yf": "2m",   "label": "3 Dakika (yakın)", "max_days": 60},
    "5m":   {"yf": "5m",   "label": "5 Dakika",   "max_days": 60},
    "15m":  {"yf": "15m",  "label": "15 Dakika",  "max_days": 60},
    "30m":  {"yf": "30m",  "label": "30 Dakika",  "max_days": 60},
    "45m":  {"yf": "60m",  "label": "45 Dakika (yakın)", "max_days": 60},
    "1h":   {"yf": "1h",   "label": "1 Saat",    "max_days": None},
    "4h":   {"yf": "1h",   "label": "4 Saat (1h bazlı)", "max_days": None},
    "1d":   {"yf": "1d",   "label": "1 Gün",      "max_days": None},
    "1wk":  {"yf": "1wk",  "label": "1 Hafta",    "max_days": None},
}

ALLOWED_PERIODS = list(SUPPORTED_INTERVALS.keys())

# ==================== RATE LIMITER & APP ====================
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="ICTSmartPro Trading AI", version="5.2.0")
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Çok fazla istek. Lütfen bekleyin."})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if DEBUG else ["https://ictsmartpro.ai"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== CACHE ====================
class SimpleCache:
    def __init__(self, ttl_seconds: int = 300):
        self.data = {}
        self.ttl = ttl_seconds

    def get(self, key: str) -> Optional[Dict]:
        if key in self.data:
            v, ts = self.data[key]
            if datetime.now() - ts < timedelta(seconds=self.ttl):
                return v
            del self.data[key]
        return None

    def set(self, key: str, value: Dict):
        self.data[key] = (value, datetime.now())

finance_cache = SimpleCache(300)
ml_cache = SimpleCache(1800)

# ==================== QWEN ====================
async def call_qwen(messages: list, temperature: float = 0.65, max_tokens: int = 1400) -> str:
    if not OPENROUTER_API_KEY:
        return "❌ API anahtarı eksik."

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://ictsmartpro.ai",
        "X-Title": "ICTSmartPro Trading AI",
        "Content-Type": "application/json"
    }

    payload = {
        "model": QWEN_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }

    async with httpx.AsyncClient(timeout=75) as client:
        try:
            r = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Qwen error: {e}")
            return "❌ AI servisi hatası."

# ==================== FİNANS VERİ ====================
async def get_finance_data(symbol: str, interval_key: str = "1d") -> Dict:
    cache_key = f"fin_{symbol}_{interval_key}"
    if cached := finance_cache.get(cache_key):
        return cached

    try:
        int_cfg = SUPPORTED_INTERVALS.get(interval_key, SUPPORTED_INTERVALS["1d"])
        yf_interval = int_cfg["yf"]

        symbol = symbol.upper().strip()
        if symbol in ["THYAO", "AKBNK", "GARAN", "ISCTR", "EREGL", "SISE", "KCHOL", "ASELS"]:
            symbol += ".IS"

        ticker = yf.Ticker(symbol)
        # Kısa interval'lar için period otomatik sınırlanır
        hist = ticker.history(interval=yf_interval, period="max" if int_cfg["max_days"] is None else "60d")

        if hist.empty:
            raise ValueError("Veri yok")

        current = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current

        info = ticker.info
        result = {
            "symbol": symbol.replace(".IS", ""),
            "name": info.get("longName") or symbol,
            "currency": info.get("currency", "TRY" if ".IS" in symbol else "USD"),
            "current_price": round(current, 2),
            "change_percent": round((current - prev) / prev * 100 if prev else 0, 2),
            "volume": int(hist["Volume"].iloc[-1]),
            "interval": interval_key,
            "historical_data": {
                "dates": hist.index.strftime("%Y-%m-%d %H:%M").tolist(),
                "prices": hist["Close"].round(2).tolist(),
            },
            "fetched_at": datetime.now().isoformat()
        }

        finance_cache.set(cache_key, result)
        return result

    except Exception as e:
        return {"error": str(e)}

# ==================== ML TAHMİN (Hafif) ====================
async def get_ml_prediction(symbol: str) -> Dict:
    cache_key = f"ml_{symbol}"
    if cached := ml_cache.get(cache_key):
        return cached

    try:
        data = await get_finance_data(symbol, "1d")  # Günlük bazlı tahmin
        if "error" in data:
            return data

        df = pd.DataFrame({
            "Close": data["historical_data"]["prices"]
        }, index=pd.to_datetime(data["historical_data"]["dates"], format="%Y-%m-%d %H:%M"))

        df["rsi_14"] = ta.rsi(df["Close"], length=14)
        df = df.dropna()

        if len(df) < 30:
            return {"error": "Yeterli veri yok"}

        current = df["Close"].iloc[-1]
        rsi = df["rsi_14"].iloc[-1]
        change_10 = df["Close"].iloc[-10:].pct_change().mean()

        adj = 1.0
        if rsi > 70: adj = 0.96
        elif rsi < 30: adj = 1.04

        pred = current * (1 + change_10 * 5 * adj)  # 5 gün tahmini

        result = {
            "predicted_price": round(float(pred), 2),
            "current_price": round(float(current), 2),
            "direction": "↑ YUKARI" if pred > current else "↓ AŞAĞI",
            "rsi": round(float(rsi), 1),
            "note": "Hafif tahmin – tavsiye değildir"
        }

        ml_cache.set(cache_key, result)
        return result

    except Exception as e:
        return {"error": str(e)}

# ==================== MODELS ====================
class AIRequest(BaseModel):
    message: str = Field(..., min_length=5, max_length=1200)

# ==================== ROUTES ====================
@app.get("/")
async def home():
    html = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ICTSmartPro Trading AI</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:1.5rem;}
        .container{max-width:1200px;margin:0 auto;}
        header{text-align:center;padding:2rem;background:linear-gradient(90deg,#6366f1,#8b5cf6);border-radius:16px;}
        .logo{font-size:3rem;font-weight:900;background:linear-gradient(45deg,#fbbf24,#f97316);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
        .dashboard{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;}
        .card{background:rgba(30,41,59,0.7);border-radius:16px;padding:1.5rem;}
        select,textarea{width:100%;padding:0.8rem;border-radius:8px;background:#1e293b;color:white;border:1px solid #475569;}
        button{background:linear-gradient(90deg,#10b981,#3b82f6);color:white;border:none;padding:0.9rem;border-radius:10px;cursor:pointer;width:100%;margin-top:1rem;}
        .result{margin-top:1rem;padding:1rem;background:rgba(255,255,255,0.04);border-radius:10px;}
        .loading{text-align:center;color:#60a5fa;}
        .error{color:#ef4444;}
        .chart-container{height:340px;margin-top:1.5rem;}
    </style>
</head>
<body>
<div class="container">
    <header>
        <div class="logo">ICTSmartPro AI</div>
    </header>
    <div class="dashboard">
        <div class="card">
            <h2>📈 Hisse Analizi</h2>
            <label>Sembol:</label>
            <select id="symbol">
                <option value="THYAO">THYAO</option>
                <option value="AKBNK">AKBNK</option>
                <option value="GARAN">GARAN</option>
                <option value="AAPL">AAPL</option>
                <option value="NVDA">NVDA</option>
            </select>

            <label>Zaman Dilimi:</label>
            <select id="interval">
                <option value="1m">1 Dakika</option>
                <option value="5m">5 Dakika</option>
                <option value="15m">15 Dakika</option>
                <option value="30m">30 Dakika</option>
                <option value="1h">1 Saat</option>
                <option value="4h">4 Saat</option>
                <option value="1d" selected>1 Gün</option>
                <option value="1wk">1 Hafta</option>
            </select>

            <button id="analyzeBtn">Analiz Et</button>
            <div id="financeResult" class="result loading">Seçip Analiz Et'e basın...</div>
        </div>

        <div class="card">
            <h2>🤖 Qwen AI</h2>
            <textarea id="aiQuery" rows="5" placeholder="Soru yazın..."></textarea>
            <button id="askBtn">Sor</button>
            <div id="aiResult" class="result loading">Bekleniyor...</div>
        </div>
    </div>

    <div class="card" style="margin-top:2rem;">
        <h2>📊 Grafik</h2>
        <div class="chart-container"><canvas id="priceChart"></canvas></div>
    </div>
</div>

<script>
    let chart = null;
async function analyze() {
    const symbol = document.getElementById('symbol').value;
    const interval = document.getElementById('interval').value;
    const div = document.getElementById('financeResult');
    div.className = 'result loading';
    div.innerHTML = '<div class="loading">Veriler çekiliyor...</div>';

    try {
        const response = await fetch(`/api/finance/${encodeURIComponent(symbol)}?interval=${interval}`);
        
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `Sunucu hatası: ${response.status}`);
        }

        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        // Başarılı sonuç
        let html = `
            <strong>${data.symbol} - ${data.name || 'Bilinmiyor'}</strong><br>
            Fiyat: <strong>${data.current_price} ${data.currency}</strong><br>
            Değişim: <span class="${data.change_percent >= 0 ? 'positive' : 'negative'}">
                ${data.change_percent.toFixed(2)}% (${data.change_percent >= 0 ? '+' : ''}${data.change_percent.toFixed(2)})
            </span><br>
            Hacim: ${data.volume.toLocaleString('tr-TR')}
        `;

        div.className = 'result';
        div.innerHTML = html;

        // Grafik çiz
        if (data.historical_data?.prices?.length > 0) {
            const ctx = document.getElementById('priceChart').getContext('2d');
            if (chart) chart.destroy();

            // Tarihleri daha güvenli parse et
            const labels = data.historical_data.dates.map(d => {
                try { return new Date(d).toLocaleString('tr-TR', {dateStyle: 'short', timeStyle: 'short'}); }
                catch { return d; }
            });

            chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: data.symbol,
                        data: data.historical_data.prices,
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59,130,246,0.1)',
                        tension: 0.1,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { grid: { color: 'rgba(255,255,255,0.08)' }, ticks: { color: '#94a3b8' } },
                        x: { grid: { color: 'rgba(255,255,255,0.08)' }, ticks: { color: '#94a3b8', maxRotation: 45, minRotation: 45 } }
                    }
                }
            });
        } else {
            div.innerHTML += '<br><small>Grafik verisi yok</small>';
        }

    } catch (error) {
        console.error('Analyze error:', error);
        div.className = 'result error';
        div.innerHTML = `<strong>Hata:</strong> ${error.message || 'Bilinmeyen hata. Lütfen tekrar deneyin.'}`;
    }
}
 

    async function ask() {
        const q = document.getElementById('aiQuery').value.trim();
        if (!q) return;
        const div = document.getElementById('aiResult');
        div.innerHTML = '<div class="loading">Analiz...</div>';

        try {
            const r = await fetch('/api/ai/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:q})});
            const d = await r.json();
            div.innerHTML = d.reply.replace(/\n/g,'<br>');
        } catch(e) {
            div.innerHTML = `<div class="error">Hata: ${e.message}</div>`;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('analyzeBtn').onclick = analyze;
        document.getElementById('askBtn').onclick = ask;
        analyze();
    });
</script>
</body>
</html>"""
    return HTMLResponse(html)

@app.get("/api/finance/{symbol}")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def finance(symbol: str, interval: str = "1d", request: Request = None):
    if interval not in ALLOWED_PERIODS:
        raise HTTPException(400, f"Geçersiz zaman dilimi. Desteklenen: {', '.join(ALLOWED_PERIODS)}")
    data = await get_finance_data(symbol, interval)
    if "error" in data:
        raise HTTPException(400, data["error"])
    return data

@app.get("/api/predict/{symbol}")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def predict(symbol: str, request: Request = None):
    data = await get_ml_prediction(symbol)
    if "error" in data:
        raise HTTPException(400, data["error"])
    return data

@app.post("/api/ai/ask")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def ask_ai(body: AIRequest, request: Request = None):
    msg = body.message
    symbol_match = re.search(r'\b([A-Z]{3,5}(\.[A-Z]{2})?)\b', msg.upper())
    symbol = symbol_match.group(1) if symbol_match else "THYAO"

    ml = await get_ml_prediction(symbol)
    ml_text = ""
    if "error" not in ml:
        ml_text = f"ML Tahmini (5 gün): {ml['predicted_price']} ({ml['direction']}), RSI: {ml['rsi']}"

    system = "Deneyimli borsa analisti olarak kısa, gerçekçi Türkçe cevap ver. Teknik analiz yap, risk belirt."

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{msg}\n\n{ml_text}"}
    ]

    reply = await call_qwen(messages)
    return {"reply": reply}

@app.get("/health")
async def health():
    return {"status": "ok", "version": "5.2.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=DEBUG)
