"""
ICTSmartPro Trading AI Platform - Full Production Version
✅ Railway Compatible ✅ No Dependency Conflicts ✅ Fast Healthcheck
Version: 6.0.0
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
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
import numpy as np
import httpx
from dotenv import load_dotenv

# ==================== CONFIGURATION ====================
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", 8000))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_REFERER = os.getenv("OPENROUTER_REFERER", "https://ictsmartpro.ai")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen/qwen3-coder:free")
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", 10))

# ==================== RATE LIMITING ====================
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="ICTSmartPro Trading AI",
    description="Production-Ready Trading Analysis Platform with Qwen AI + ML",
    version="6.0.0",
    docs_url="/docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None,
)

app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"error": "Rate limit aşıldı. Lütfen 1 dakika bekleyin."}, status_code=429)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ictsmartpro.ai", "https://www.ictsmartpro.ai"] if not DEBUG else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ==================== CACHE ====================
class SimpleCache:
    def __init__(self, ttl_seconds: int = 300):
        self.cache: Dict[str, tuple] = {}
        self.ttl = ttl_seconds

    def get(self, key: str) -> Optional[Dict]:
        if key in self.cache:
            value, timestamp = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.ttl):
                return value
            del self.cache[key]
        return None

    def set(self, key: str, value: Dict):
        self.cache[key] = (value, datetime.now())

finance_cache = SimpleCache(ttl_seconds=300)
ml_cache = SimpleCache(ttl_seconds=3600)

# ==================== TECHNICAL INDICATORS (No pandas-ta!) ====================
def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()

def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def calculate_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def calculate_bollinger_bands(series: pd.Series, period: int = 20, std_dev: int = 2) -> tuple:
    sma = calculate_sma(series, period)
    std = series.rolling(window=period).std()
    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)
    return upper_band, lower_band

# ==================== UTILS ====================
def normalize_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    if symbol.startswith("BIST:"):
        symbol = symbol.replace("BIST:", "")
    if symbol in ["THYAO", "AKBNK", "GARAN", "ISCTR", "EREGL", "SISE", "KCHOL", "ASELS", "TUPRS", "FROTO"]:
        symbol += ".IS"
    return symbol

async def call_qwen(messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
    if not OPENROUTER_API_KEY:
        return "⚠️ OpenRouter API anahtarı tanımlı değil. AI analizleri devre dışı."

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": OPENROUTER_REFERER,
        "X-Title": "ICTSmartPro Trading AI",
        "Content-Type": "application/json"
    }

    payload = {
        "model": QWEN_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 1500,
        "stream": False
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(f"{OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                return "⚠️ API kotası aşıldı. Lütfen birkaç dakika bekleyin."
            logger.error(f"OpenRouter HTTP error: {e.response.status_code}")
            return f"❌ AI servisi hatası: {e.response.status_code}"
        except Exception as e:
            logger.error(f"Qwen error: {str(e)}")
            return "❌ AI servisi geçici olarak kullanılamıyor."

async def get_finance_data(symbol: str, period: str = "1mo") -> Dict:
    try:
        symbol = normalize_symbol(symbol)
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)

        if hist.empty and not symbol.endswith(".IS"):
            ticker = yf.Ticker(symbol + ".IS")
            hist = ticker.history(period=period)

        if hist.empty:
            raise ValueError("Veri bulunamadı")

        current = float(hist["Close"].iloc[-1])
        previous = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current
        change = current - previous
        change_pct = (change / previous * 100) if previous != 0 else 0

        info = ticker.info
        name = info.get("longName") or info.get("shortName") or symbol.replace(".IS", "")
        currency = info.get("currency", "TRY" if ".IS" in symbol else "USD")

        return {
            "symbol": symbol.replace(".IS", ""),
            "name": name,
            "currency": currency,
            "current_price": round(current, 2),
            "change": round(change, 2),
            "change_percent": round(change_pct, 2),
            "volume": int(hist["Volume"].iloc[-1]),
            "avg_volume_10d": int(hist["Volume"].tail(10).mean()) if len(hist) >= 10 else 0,
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "historical_data": {
                "dates": hist.index.strftime("%Y-%m-%d").tolist(),
                "prices": hist["Close"].round(2).tolist(),
                "highs": hist["High"].round(2).tolist(),
                "lows": hist["Low"].round(2).tolist(),
                "volumes": hist["Volume"].tolist()
            },
            "fetched_at": datetime.now().isoformat(),
            "error": None
        }
    except Exception as e:
        logger.error(f"Finance error {symbol}: {str(e)}")
        return {"symbol": symbol, "error": str(e), "historical_data": {"dates": [], "prices": [], "highs": [], "lows": [], "volumes": []}}

class MLModelManager:
    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["sma_20"] = calculate_sma(df["Close"], 20)
        df["ema_10"] = calculate_ema(df["Close"], 10)
        df["rsi_14"] = calculate_rsi(df["Close"], 14)
        
        macd_line, signal_line, histogram = calculate_macd(df["Close"])
        df["macd"] = macd_line
        df["macd_sig"] = signal_line
        df["macd_hist"] = histogram
        
        upper, lower = calculate_bollinger_bands(df["Close"], 20, 2)
        df["bb_upper"] = upper
        df["bb_lower"] = lower
        
        df["momentum"] = df["Close"].diff(4)
        df["volatility"] = df["Close"].rolling(window=10).std()
        
        return df.dropna()

    async def predict_price(self, symbol: str, horizon: int = 5) -> Dict:
        try:
            data = await get_finance_data(symbol, "6mo")
            if data.get("error"):
                return {"error": data["error"]}

            df = pd.DataFrame({
                "Date": data["historical_data"]["dates"],
                "Close": data["historical_data"]["prices"],
                "High": data["historical_data"]["highs"],
                "Low": data["historical_data"]["lows"],
                "Volume": data["historical_data"]["volumes"]
            }).set_index("Date")
            df.index = pd.to_datetime(df.index)
            df = self._prepare_features(df)

            if len(df) < 50:
                return {"error": "Yeterli veri yok (min 50 günlük)"}

            recent_trend = df["Close"].iloc[-10:].diff().mean()
            current_price = df["Close"].iloc[-1]
            rsi = df["rsi_14"].iloc[-1]
            
            rsi_factor = 1.0
            if rsi > 70:
                rsi_factor = 0.95
            elif rsi < 30:
                rsi_factor = 1.05

            predicted_price = current_price + (recent_trend * horizon * rsi_factor)
            direction = "↑ YUKARI" if predicted_price > current_price else "↓ AŞAĞI"

            return {
                "predicted_price": round(float(predicted_price), 2),
                "current_price": round(float(current_price), 2),
                "horizon": horizon,
                "direction": direction,
                "direction_class": "positive" if predicted_price > current_price else "negative",
                "confidence": round(min(95, max(50, 100 - abs(recent_trend) * 10)), 1),
                "note": "İstatistiksel tahmin – yatırım tavsiyesi değildir",
                "method": "Momentum + RSI Adjusted"
            }
        except Exception as e:
            logger.error(f"ML error: {str(e)}")
            return {"error": f"ML hatası: {str(e)}"}

ml_manager = MLModelManager()

# ==================== HEALTHCHECK ENDPOINTS ====================
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "6.0.0",
        "timestamp": datetime.now().isoformat(),
        "uptime": "ok"
    }

@app.get("/ready")
async def ready_check():
    return {"ready": True}

# ==================== API ENDPOINTS ====================
@app.get("/api/finance/{symbol}")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def api_finance(request: Request, symbol: str, period: str = "1mo"):
    allowed_periods = {"5d", "1mo", "3mo", "6mo", "1y", "2y"}
    if period not in allowed_periods:
        raise HTTPException(400, f"Geçersiz dönem. İzin verilenler: {allowed_periods}")
    
    cache_key = f"finance_{symbol}_{period}"
    if cached := finance_cache.get(cache_key):
        return cached
    
    result = await get_finance_data(symbol, period)
    if result.get("error"):
        raise HTTPException(404, result["error"])
    
    finance_cache.set(cache_key, result)
    return result

@app.get("/api/predict/{symbol}")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def api_predict(request: Request, symbol: str, horizon: int = 5):
    cache_key = f"ml_{symbol}_{horizon}"
    if cached := ml_cache.get(cache_key):
        return cached
    
    result = await ml_manager.predict_price(symbol, horizon)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    
    ml_cache.set(cache_key, result)
    return result

class AIQueryRequest(BaseModel):
    message: str = Field(..., min_length=5, max_length=1000)

    @field_validator("message")
    @classmethod
    def validate_message(cls, v):
        v = re.sub(r"<script.*?>.*?</script>", "", v, flags=re.IGNORECASE)
        return v.strip()

@app.post("/api/ai/ask")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def api_ai_ask(request: Request, query: AIQueryRequest):
    user_msg = query.message
    symbol_match = re.search(r'\b([A-Z]{3,5}(?:\.[A-Z]{2})?)\b', user_msg.upper())
    symbol = symbol_match.group(1) if symbol_match else "THYAO"
    
    ml_result = await ml_manager.predict_price(symbol, 5)
    ml_info = ""
    if not ml_result.get("error"):
        ml_info = f"""
📊 ML ANALİZ SONUÇLARI:
• Tahmini Fiyat (5 gün): {ml_result['predicted_price']}
• Mevcut Fiyat: {ml_result['current_price']}
• Beklenen Yön: {ml_result['direction']}
• Güven Seviyesi: %{ml_result['confidence']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    system_prompt = """Sen deneyimli bir finansal analist ve trading uzmanısın.
Kullanıcılara net, profesyonel ve dengeli analizler sun.
Kurallar:
1. Spekülatif ifadeler kullanma
2. Riskleri mutlaka belirt
3. Teknik analiz terimlerini açıkla
4. Kısa ve öz cevaplar ver (max 300 kelime)
5. Türkçe ve profesyonel bir dil kullan
6. ML tahminlerini referans al ama mutlak doğru varsayma
7. Yatırım tavsiyesi verme, sadece bilgilendir"""

    enhanced_msg = f"""
KULLANICI SORUSU:
{user_msg}

{ml_info}

Lütfen yukarıdaki bağlamda profesyonel bir analiz sun."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": enhanced_msg}
    ]

    reply = await call_qwen(messages)
    reply_safe = re.sub(r'<script.*?>.*?</script>', '', reply, flags=re.IGNORECASE)
    return {"reply": reply_safe, "symbol_used": symbol}

# ==================== MAIN FRONTEND (Full Trading Platform) ====================
@app.get("/", response_class=HTMLResponse)
async def home():
    return """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="ICTSmartPro - Yapay Zeka Destekli Hisse Analiz Platformu">
    <title>ICTSmartPro Trading AI 🚀</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/dompurify@3.0.5/dist/purify.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
    <style>
        :root {
            --primary: #6366f1;
            --secondary: #8b5cf6;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --info: #3b82f6;
            --dark: #0f172a;
            --dark-800: #1e293b;
            --dark-700: #334155;
            --light: #f8fafc;
            --gray: #94a3b8;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #e2e8f0;
            line-height: 1.6;
            min-height: 100vh;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 1.5rem;
        }

        header {
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            padding: 2rem 0;
            text-align: center;
            border-radius: 0 0 16px 16px;
            margin-bottom: 2rem;
            position: relative;
            overflow: hidden;
        }

        header::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 70%);
            animation: pulse 8s ease-in-out infinite;
        }

        @keyframes pulse {
            0%, 100% { transform: scale(1); opacity: 0.3; }
            50% { transform: scale(1.1); opacity: 0.5; }
        }

        .logo {
            font-size: 3.5rem;
            font-weight: 900;
            background: linear-gradient(45deg, #fbbf24, #f97316, #f59e0b);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: 0 2px 10px rgba(255, 255, 255, 0.1);
            margin-bottom: 0.5rem;
        }

        .tagline {
            font-size: 1.2rem;
            color: rgba(255, 255, 255, 0.9);
            margin-top: 0.5rem;
        }

        .dashboard {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 2rem;
            margin-bottom: 2rem;
        }

        @media (max-width: 768px) {
            .dashboard {
                grid-template-columns: 1fr;
            }
        }

        .card {
            background: rgba(30, 41, 59, 0.8);
            border-radius: 16px;
            padding: 1.8rem;
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        }

        .card-title {
            font-size: 1.5rem;
            font-weight: 700;
            color: white;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 1.2rem;
        }

        select, textarea {
            width: 100%;
            padding: 0.9rem;
            border-radius: 10px;
            border: 2px solid var(--dark-700);
            background: var(--dark-800);
            color: white;
            font-size: 1rem;
            margin-bottom: 1rem;
        }

        button {
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            color: white;
            border: none;
            padding: 1rem;
            border-radius: 12px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
            margin-top: 0.5rem;
            transition: all 0.3s;
        }

        button:hover {
            transform: translateY(-2px);
            opacity: 0.95;
        }

        .result {
            margin-top: 1rem;
            padding: 1rem;
            background: rgba(255, 255, 255, 0.04);
            border-radius: 10px;
            min-height: 60px;
        }

        .loading {
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--primary);
        }

        .spinner {
            border: 3px solid rgba(99, 102, 241, 0.3);
            border-top: 3px solid var(--primary);
            border-radius: 50%;
            width: 25px;
            height: 25px;
            animation: spin 1s linear infinite;
            margin-right: 10px;
        }

        @keyframes spin {
            0% { transform: rotate(0); }
            100% { transform: rotate(360deg); }
        }

        .positive { color: var(--success); font-weight: 600; }
        .negative { color: var(--danger); font-weight: 600; }

        .chart-container {
            height: 400px;
            margin-top: 1.5rem;
            background: rgba(0, 0, 0, 0.1);
            border-radius: 12px;
        }

        footer {
            text-align: center;
            padding: 2rem;
            margin-top: 2rem;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            color: var(--gray);
            font-size: 0.9rem;
        }

        footer a {
            color: var(--primary);
            text-decoration: none;
        }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <div class="logo">
                <i class="fas fa-rocket"></i> ICTSmartPro AI
            </div>
            <div class="tagline">Yapay Zeka + Makine Öğrenmesi ile Akıllı Hisse Analizi</div>
        </div>
    </header>

    <div class="container">
        <div class="dashboard">
            <div class="card">
                <h2 class="card-title"><i class="fas fa-chart-line"></i> Hisse Analizi</h2>
                <select id="symbol">
                    <optgroup label="BIST 100">
                        <option value="THYAO">THYAO - Türk Hava Yolları</option>
                        <option value="AKBNK">AKBNK - Akbank</option>
                        <option value="GARAN">GARAN - Garanti BBVA</option>
                        <option value="ISCTR">ISCTR - İş Bankası</option>
                        <option value="EREGL">EREGL - Ereğli Demir Çelik</option>
                        <option value="SISE">SISE - Şişecam</option>
                        <option value="KCHOL">KCHOL - Koç Holding</option>
                        <option value="ASELS">ASELS - Aselsan</option>
                    </optgroup>
                    <optgroup label="Global">
                        <option value="AAPL">AAPL - Apple</option>
                        <option value="MSFT">MSFT - Microsoft</option>
                        <option value="NVDA">NVDA - NVIDIA</option>
                        <option value="GOOGL">GOOGL - Google</option>
                        <option value="AMZN">AMZN - Amazon</option>
                        <option value="TSLA">TSLA - Tesla</option>
                    </optgroup>
                </select>

                <select id="period">
                    <option value="5d">Son 5 Gün</option>
                    <option value="1mo" selected>1 Ay</option>
                    <option value="3mo">3 Ay</option>
                    <option value="6mo">6 Ay</option>
                    <option value="1y">1 Yıl</option>
                </select>

                <button id="analyzeBtn"><i class="fas fa-search"></i> Analiz Et</button>
                <button id="predictBtn" style="background:linear-gradient(90deg,var(--secondary),#d946ef);margin-top:0.8rem">
                    <i class="fas fa-brain"></i> ML Tahmin Al
                </button>

                <div id="financeResult" class="result loading">
                    <div class="spinner"></div> Veriler yükleniyor...
                </div>

                <div id="mlResult" class="result" style="display:none;margin-top:1rem">
                    <div class="spinner"></div> ML tahmini hazırlanıyor...
                </div>
            </div>

            <div class="card">
                <h2 class="card-title"><i class="fas fa-robot"></i> Qwen AI Analisti</h2>
                <textarea id="aiQuery" placeholder="Örnek sorular:
• THYAO için teknik görünüm nasıl?
• AKBNK'ta alım fırsatı var mı?
• NVIDIA son 1 ay performansını değerlendir
• RSI ve MACD göstergelerine göre GARAN analizi"></textarea>
                
                <button id="askBtn"><i class="fas fa-paper-plane"></i> Qwen'e Sor</button>
                
                <div id="aiResult" class="result loading" style="min-height:200px">
                    <div class="spinner"></div> Sorunuzu yazıp Qwen'e sorun...
                </div>
                
                <div style="color:var(--gray);font-size:0.85rem;margin-top:0.8rem">
                    <i class="fas fa-info-circle"></i> AI analizleri ML tahminleri ile desteklenir. Yatırım tavsiyesi değildir.
                </div>
            </div>
        </div>

        <div class="card">
            <h2 class="card-title"><i class="fas fa-chart-bar"></i> Fiyat Grafiği</h2>
            <div class="chart-container">
                <canvas id="priceChart"></canvas>
            </div>
        </div>
    </div>

    <footer>
        <div class="container">
            <p>
                © 2026 ICTSmartPro Trading AI | 
                <a href="https://ictsmartpro.ai" target="_blank">Website</a> | 
                <span style="color:var(--danger);margin-left:10px">
                    <i class="fas fa-exclamation-triangle"></i> Yatırım danışmanlığı değildir
                </span>
            </p>
        </div>
    </footer>

    <script>
        let chartInstance = null;
        let isProcessing = false;

        async function analyzeStock() {
            if (isProcessing) return;
            isProcessing = true;
            
            const symbol = document.getElementById('symbol').value;
            const period = document.getElementById('period').value;
            const resDiv = document.getElementById('financeResult');
            
            resDiv.className = 'result loading';
            resDiv.innerHTML = '<div class="spinner"></div> Veriler çekiliyor...';

            try {
                const resp = await fetch(`/api/finance/${encodeURIComponent(symbol)}?period=${period}`);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();
                if (data.error) throw new Error(data.error);

                resDiv.className = 'result';
                resDiv.innerHTML = `
                    <strong>${data.symbol} - ${data.name}</strong><br>
                    Fiyat: <span style="font-size:1.4rem;color:${data.change_percent>=0?'#10b981':'#ef4444'}">
                    ${data.current_price} ${data.currency} ${data.change_percent>=0?'↑':'↓'}${Math.abs(data.change_percent).toFixed(2)}%</span><br>
                    Hacim: ${data.volume.toLocaleString('tr-TR')} | 10G Ort: ${(data.avg_volume_10d / 1e6).toFixed(1)}M
                `;

                if (data.historical_data.prices.length > 0) {
                    drawChart(data.historical_data, data.symbol, data.name);
                }
            } catch (err) {
                resDiv.className = 'result';
                resDiv.innerHTML = `<span style="color:#ef4444">❌ ${err.message}</span>`;
            } finally {
                isProcessing = false;
            }
        }

        async function getMLPrediction() {
            if (isProcessing) return;
            isProcessing = true;
            
            const symbol = document.getElementById('symbol').value;
            const mlDiv = document.getElementById('mlResult');
            
            mlDiv.style.display = 'block';
            mlDiv.className = 'result loading';
            mlDiv.innerHTML = '<div class="spinner"></div> ML tahmini hesaplanıyor...';

            try {
                const resp = await fetch(`/api/predict/${encodeURIComponent(symbol)}?horizon=5`);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();
                if (data.error) throw new Error(data.error);

                mlDiv.className = 'result';
                mlDiv.innerHTML = `
                    <strong>🎯 5 Gün Sonrası Tahmin</strong><br>
                    Tahmini: <span class="${data.direction_class}">${data.predicted_price} ${data.direction}</span><br>
                    Mevcut: ${data.current_price}<br>
                    Güven: %${data.confidence}<br>
                    <small style="color:#94a3b8">${data.note}</small>
                `;
            } catch (err) {
                mlDiv.className = 'result';
                mlDiv.innerHTML = `<span style="color:#ef4444">❌ ${err.message}</span>`;
            } finally {
                isProcessing = false;
            }
        }

        async function askQwen() {
            if (isProcessing) return;
            isProcessing = true;
            
            const query = document.getElementById('aiQuery').value.trim();
            const aiDiv = document.getElementById('aiResult');
            
            if (!query) {
                alert('Lütfen bir soru yazın!');
                isProcessing = false;
                return;
            }

            aiDiv.className = 'result loading';
            aiDiv.innerHTML = '<div class="spinner"></div> Qwen analiz ediyor...';

            try {
                const resp = await fetch('/api/ai/ask', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: query})
                });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();
                aiDiv.className = 'result';
                aiDiv.innerHTML = DOMPurify.sanitize(data.reply.replace(/\\n/g, '<br>'));
            } catch (err) {
                aiDiv.className = 'result';
                aiDiv.innerHTML = `<span style="color:#ef4444">❌ ${err.message}</span>`;
            } finally {
                isProcessing = false;
            }
        }

        function drawChart(hdata, symbol, name) {
            const ctx = document.getElementById('priceChart').getContext('2d');
            if (chartInstance) chartInstance.destroy();
            
            chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: hdata.dates.slice(-60),
                    datasets: [{
                        label: `${symbol} - ${name}`,
                        data: hdata.prices.slice(-60),
                        borderColor: '#6366f1',
                        backgroundColor: 'rgba(99,102,241,0.1)',
                        borderWidth: 2,
                        tension: 0.3,
                        fill: true,
                        pointRadius: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {labels: {color: '#e2e8f0'}},
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            titleColor: '#fff',
                            bodyColor: '#cbd5e1'
                        }
                    },
                    scales: {
                        y: {
                            grid: {color: 'rgba(255,255,255,0.05)'},
                            ticks: {color: '#94a3b8'}
                        },
                        x: {
                            grid: {color: 'rgba(255,255,255,0.03)'},
                            ticks: {
                                color: '#94a3b8',
                                maxRotation: 45,
                                minRotation: 45
                            }
                        }
                    }
                }
            });
        }

        document.addEventListener('DOMContentLoaded', () => {
            document.getElementById('analyzeBtn').addEventListener('click', analyzeStock);
            document.getElementById('predictBtn').addEventListener('click', getMLPrediction);
            document.getElementById('askBtn').addEventListener('click', askQwen);
            
            document.getElementById('aiQuery').addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    askQwen();
                }
            });
            
            setTimeout(analyzeStock, 500);
        });
    </script>
</body>
</html>
    """

# ==================== STARTUP ====================
@app.on_event("startup")
async def startup():
    logger.info("="*60)
    logger.info("🚀 ICTSmartPro Trading AI Platform Başlatılıyor")
    logger.info(f"🚀 Version: 6.0.0")
    logger.info(f"📍 Port: {PORT}")
    logger.info(f"🔧 Debug: {DEBUG}")
    logger.info(f"🤖 Qwen API: {'✓ Ayarlı' if OPENROUTER_API_KEY else '⚠️ Eksik (AI devre dışı)'}")
    logger.info(f"⏱️ Rate Limit: {RATE_LIMIT_PER_MINUTE}/dk")
    logger.info("="*60)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")
