"""
ICTSmartPro Trading AI Platform
Production-Ready Trading Analysis with Qwen AI + Lightweight ML
Version: 5.1.0 - 2026 February - Stabilized Dependencies
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
from pydantic import BaseModel, Field, field_validator

import yfinance as yf
import pandas as pd
import pandas_ta_classic as ta      # ← STABİL FORK
import httpx
from dotenv import load_dotenv

# ==================== KONFIGÜRASYON ====================
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen/qwen3-coder:free")

RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", 15))
RATE_LIMIT_PER_HOUR   = int(os.getenv("RATE_LIMIT_PER_HOUR", 150))

ALLOWED_PERIODS = {"5d", "1mo", "3mo", "6mo", "1y", "2y"}

# ==================== RATE LIMITER ====================
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="ICTSmartPro Trading AI",
    description="Qwen AI + Hafif ML ile Hisse Analizi",
    version="5.1.0",
    docs_url="/docs" if DEBUG else None,
)

app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Çok fazla istek. Lütfen biraz bekleyin."}
    )

# ==================== CORS ====================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if DEBUG else ["https://ictsmartpro.ai", "https://www.ictsmartpro.ai"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== SIMPLE CACHE ====================
class SimpleCache:
    def __init__(self, ttl_seconds: int = 300):
        self.data: Dict[str, tuple] = {}
        self.ttl = ttl_seconds

    def get(self, key: str) -> Optional[Dict]:
        if key in self.data:
            value, ts = self.data[key]
            if datetime.now() - ts < timedelta(seconds=self.ttl):
                return value
            del self.data[key]
        return None

    def set(self, key: str, value: Dict):
        self.data[key] = (value, datetime.now())

finance_cache = SimpleCache(300)   # 5 dk
ml_cache      = SimpleCache(1800)  # 30 dk

# ==================== QWEN HELPER ====================
async def call_qwen(messages: list, temperature: float = 0.65, max_tokens: int = 1400) -> str:
    if not OPENROUTER_API_KEY:
        return "❌ OpenRouter API anahtarı eksik."

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

    async with httpx.AsyncClient(timeout=75.0) as client:
        try:
            r = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                return "⚠️ Rate limit aşıldı. Biraz bekleyin."
            return f"AI hatası: {e.response.status_code}"
        except Exception as e:
            logger.error(f"Qwen error: {e}")
            return "❌ AI servisi şu an yanıt vermiyor."

# ==================== FİNANS VERİ ====================
async def get_finance_data(symbol: str, period: str = "1mo") -> Dict:
    cache_key = f"fin_{symbol}_{period}"
    if cached := finance_cache.get(cache_key):
        return cached

    try:
        symbol = symbol.upper().strip()
        if symbol in ["THYAO", "AKBNK", "GARAN", "ISCTR", "EREGL", "SISE", "KCHOL", "ASELS"]:
            symbol += ".IS"

        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)

        if hist.empty:
            raise ValueError("Veri alınamadı")

        current = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current

        info = ticker.info
        result = {
            "symbol": symbol.replace(".IS", ""),
            "name": info.get("longName") or info.get("shortName") or symbol,
            "currency": info.get("currency", "TRY" if ".IS" in symbol else "USD"),
            "current_price": round(current, 2),
            "change": round(current - prev, 2),
            "change_percent": round((current - prev) / prev * 100 if prev else 0, 2),
            "volume": int(hist["Volume"].iloc[-1]),
            "historical_data": {
                "dates": hist.index.strftime("%Y-%m-%d").tolist(),
                "prices": hist["Close"].round(2).tolist(),
                "highs": hist["High"].round(2).tolist(),
                "lows": hist["Low"].round(2).tolist(),
                "volumes": hist["Volume"].tolist()
            },
            "fetched_at": datetime.now().isoformat()
        }

        finance_cache.set(cache_key, result)
        return result

    except Exception as e:
        logger.error(f"Finance error {symbol}: {e}")
        return {"error": str(e)}

# ==================== HAFİF ML TAHMİN ====================
async def get_ml_prediction(symbol: str, horizon: int = 5) -> Dict:
    cache_key = f"ml_{symbol}_{horizon}"
    if cached := ml_cache.get(cache_key):
        return cached

    try:
        data = await get_finance_data(symbol, "6mo")
        if "error" in data:
            return {"error": data["error"]}

        df = pd.DataFrame({
            "Close": data["historical_data"]["prices"],
            "High": data["historical_data"]["highs"],
            "Low": data["historical_data"]["lows"],
            "Volume": data["historical_data"]["volumes"]
        }, index=pd.to_datetime(data["historical_data"]["dates"]))

        # Basit ama etkili indikatörler
        df["rsi_14"] = ta.rsi(df["Close"], length=14)
        df["sma_20"] = ta.sma(df["Close"], length=20)
        df = df.dropna()

        if len(df) < 30:
            return {"error": "Yeterli veri yok"}

        current = df["Close"].iloc[-1]
        recent_change = df["Close"].iloc[-10:].pct_change().mean()
        rsi = df["rsi_14"].iloc[-1]

        rsi_adj = 1.0
        if rsi > 70: rsi_adj = 0.96
        elif rsi < 30: rsi_adj = 1.04

        predicted = current * (1 + recent_change * horizon * rsi_adj)

        result = {
            "predicted_price": round(float(predicted), 2),
            "current_price": round(float(current), 2),
            "horizon_days": horizon,
            "direction": "↑ YUKARI" if predicted > current else "↓ AŞAĞI",
            "rsi_current": round(float(rsi), 1),
            "note": "Hafif momentum + RSI tahmini – yatırım tavsiyesi değildir"
        }

        ml_cache.set(cache_key, result)
        return result

    except Exception as e:
        logger.error(f"ML error {symbol}: {e}")
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
        header{text-align:center;padding:2rem;background:linear-gradient(90deg,#6366f1,#8b5cf6);border-radius:16px;margin-bottom:2rem;}
        .logo{font-size:3rem;font-weight:900;background:linear-gradient(45deg,#fbbf24,#f97316);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
        .dashboard{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;}
        @media (max-width:768px){.dashboard{grid-template-columns:1fr;}}
        .card{background:rgba(30,41,59,0.7);border-radius:16px;padding:1.5rem;border:1px solid rgba(255,255,255,0.1);}
        label{display:block;margin:0.8rem 0 0.4rem;color:#cbd5e1;}
        select,textarea{width:100%;padding:0.8rem;border-radius:8px;border:1px solid #475569;background:#1e293b;color:white;}
        button{background:linear-gradient(90deg,#10b981,#3b82f6);color:white;border:none;padding:0.9rem;border-radius:10px;font-weight:600;cursor:pointer;width:100%;margin-top:1rem;}
        .result{margin-top:1.2rem;padding:1rem;background:rgba(255,255,255,0.04);border-radius:10px;white-space:pre-wrap;}
        .positive{color:#10b981;} .negative{color:#ef4444;}
        .chart-container{height:340px;margin-top:1.5rem;}
        .loading{text-align:center;color:#60a5fa;padding:1.5rem;}
        .error{color:#ef4444;background:rgba(239,68,68,0.12);padding:0.8rem;border-radius:8px;}
    </style>
</head>
<body>
<div class="container">
    <header>
        <div class="logo">ICTSmartPro AI</div>
        <div>Yapay Zeka Destekli Hisse Analizi</div>
    </header>

    <div class="dashboard">
        <div class="card">
            <h2>📈 Hisse Analizi</h2>
            <label>Sembol:</label>
            <select id="symbol">
                <option value="THYAO">THYAO - Türk Hava Yolları</option>
                <option value="AKBNK">AKBNK - Akbank</option>
                <option value="GARAN">GARAN - Garanti</option>
                <option value="ISCTR">ISCTR - İş Bankası</option>
                <option value="EREGL">EREGL - Ereğli Demir Çelik</option>
                <option value="AAPL">AAPL - Apple</option>
                <option value="NVDA">NVDA - NVIDIA</option>
            </select>

            <label>Dönem:</label>
            <select id="period">
                <option value="5d">5 Gün</option>
                <option value="1mo" selected>1 Ay</option>
                <option value="3mo">3 Ay</option>
                <option value="6mo">6 Ay</option>
                <option value="1y">1 Yıl</option>
            </select>

            <button id="analyzeBtn">Analiz Et</button>
            <div id="financeResult" class="result loading">Sembol seçip Analiz Et'e basın...</div>
        </div>

        <div class="card">
            <h2>🤖 Qwen AI</h2>
            <label>Soru:</label>
            <textarea id="aiQuery" rows="5" placeholder="Örnek: THYAO teknik görünüm nasıl?"></textarea>
            <button id="askBtn">Sor</button>
            <div id="aiResult" class="result loading">Soru bekleniyor...</div>
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
        const s = document.getElementById('symbol').value;
        const p = document.getElementById('period').value;
        const div = document.getElementById('financeResult');
        div.innerHTML = '<div class="loading">Yükleniyor...</div>';

        try {
            const r = await fetch(`/api/finance/${encodeURIComponent(s)}?period=${p}`);
            const d = await r.json();
            if (d.error) throw new Error(d.error);

            let h = `<strong>${d.symbol} - ${d.name}</strong><br>`;
            h += `Fiyat: ${d.current_price} ${d.currency}<br>`;
            h += `Değişim: <span class="${d.change_percent>=0?'positive':'negative'}">${d.change_percent.toFixed(2)}%</span><br>`;

            div.innerHTML = h;

            if (d.historical_data?.prices?.length) {
                const ctx = document.getElementById('priceChart').getContext('2d');
                if (chart) chart.destroy();
                chart = new Chart(ctx, {
                    type: 'line',
                    data: { labels: d.historical_data.dates, datasets: [{label:s,data:d.historical_data.prices,borderColor:'#3b82f6',fill:true}] },
                    options: { responsive:true, scales:{ y:{grid:{color:'rgba(255,255,255,0.1)'}}, x:{grid:{color:'rgba(255,255,255,0.1)'}} } }
                });
            }
        } catch(e) {
            div.innerHTML = `<div class="error">Hata: ${e.message}</div>`;
        }
    }

    async function ask() {
        const q = document.getElementById('aiQuery').value.trim();
        if (!q) return alert('Soru yazın');
        const div = document.getElementById('aiResult');
        div.innerHTML = '<div class="loading">Analiz yapılıyor...</div>';

        try {
            const r = await fetch('/api/ai/ask', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({message:q})
            });
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
async def finance(symbol: str, period: str = "1mo", request: Request = None):
    if period not in ALLOWED_PERIODS:
        raise HTTPException(400, "Geçersiz dönem")
    data = await get_finance_data(symbol, period)
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
        ml_text = f"""
ML Tahmini (5 gün sonrası):
Tahmin: {ml['predicted_price']} ({ml['direction']})
Mevcut: {ml['current_price']}
RSI: {ml['rsi_current']}
"""

    system = """Deneyimli borsa analisti olarak kısa, gerçekçi ve Türkçe cevap ver.
Teknik analiz, destek-direnç, riskleri belirt. Spekülasyon yapma."""

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{msg}\n\n{ml_text}"}
    ]

    reply = await call_qwen(messages)
    return {"reply": reply}

@app.get("/health")
async def health():
    return {"status": "ok", "version": "5.1.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=DEBUG)
