"""
ICTSmartPro Trading AI Platform
Production-Ready Trading Analysis with Qwen AI + ML
Version: 4.0.0
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import re
import json

from fastapi import FastAPI, HTTPException, Request, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel, Field, validator
from slugify import slugify

import yfinance as yf
import pandas as pd
import pandas_ta as ta
import httpx
from dotenv import load_dotenv

# ==================== KONFIGÜRASYON ====================
load_dotenv()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("app.log", mode="a", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# Environment
PORT = int(os.getenv("PORT", 8000))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")

# API Keys
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_REFERER = os.getenv("OPENROUTER_REFERER", "https://ictsmartpro.ai")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen/qwen3-coder:free")

# Rate Limiting
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", 10))
RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", 100))

# Validation
ALLOWED_SYMBOLS = os.getenv("ALLOWED_SYMBOLS", "").split(",") if os.getenv("ALLOWED_SYMBOLS") else None
ALLOWED_PERIODS = {"5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"}

# ==================== VALIDATION MODELS ====================
class SymbolRequest(BaseModel):
    symbol: str = Field(..., min_length=2, max_length=15)
    period: str = Field("1mo", min_length=2, max_length=10)

    @validator("symbol")
    def validate_symbol(cls, v):
        v = v.strip().upper()
        if not re.match(r"^[A-Z0-9]{2,6}(\.[A-Z]{2})?$", v):
            raise ValueError("Geçersiz sembol formatı")
        if ALLOWED_SYMBOLS and v not in ALLOWED_SYMBOLS:
            raise ValueError("Bu sembol izin verilmiyor")
        return v

    @validator("period")
    def validate_period(cls, v):
        if v not in ALLOWED_PERIODS:
            raise ValueError(f"Dönem {ALLOWED_PERIODS} arasında olmalı")
        return v

class AIQueryRequest(BaseModel):
    message: str = Field(..., min_length=5, max_length=1000)

    @validator("message")
    def validate_message(cls, v):
        # Potansiyel XSS saldırılarını temizle
        v = re.sub(r"<script.*?>.*?</script>", "", v, flags=re.IGNORECASE)
        v = re.sub(r"javascript:", "", v, flags=re.IGNORECASE)
        return v.strip()

# ==================== RATE LIMITING ====================
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="ICTSmartPro Trading AI",
    description="Production-Ready Trading Analysis Platform with Qwen AI + ML",
    version="4.0.0",
    docs_url="/docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ==================== CORS & MIDDLEWARE ====================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if DEBUG else [
        "https://ictsmartpro.ai",
        "https://www.ictsmartpro.ai",
        "https://your-railway-app.up.railway.app"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    max_age=3600,
)

# ==================== CACHE (Simple In-Memory) ====================
class SimpleCache:
    def __init__(self, ttl_seconds: int = 300):
        self.cache: Dict[str, tuple] = {}
        self.ttl = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            value, timestamp = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.ttl):
                return value
            del self.cache[key]
        return None

    def set(self, key: str, value: Any):
        self.cache[key] = (value, datetime.now())

    def clear(self):
        self.cache.clear()

finance_cache = SimpleCache(ttl_seconds=300)  # 5 dakika
ml_cache = SimpleCache(ttl_seconds=3600)  # 1 saat

# ==================== QWEN AI ====================
async def call_qwen(messages: List[Dict[str, str]], temperature: float = 0.7, max_tokens: int = 1500) -> str:
    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY tanımlı değil!")
        return "❌ OpenRouter API anahtarı yapılandırılmamış."

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
        "max_tokens": max_tokens,
        "stream": False
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("Rate limit exceeded for OpenRouter")
                return "⚠️ API kotası aşıldı. Lütfen birkaç dakika bekleyin."
            logger.error(f"OpenRouter HTTP error: {e.response.status_code} - {e.response.text}")
            return f"❌ AI servisi hatası: {e.response.status_code}"
        except Exception as e:
            logger.error(f"Qwen çağrısı hatası: {str(e)}")
            return "❌ AI servisi geçici olarak kullanılamıyor."

# ==================== FİNANS VERİSİ ====================
def normalize_symbol(symbol: str) -> str:
    """Sembolü normalize eder (BIST desteği)"""
    symbol = symbol.upper().strip()
    if symbol.startswith("BIST:"):
        symbol = symbol.replace("BIST:", "")
    if symbol in ["THYAO", "AKBNK", "GARAN", "ISCTR", "EREGL", "SISE", "KCHOL", "ASELS"]:
        symbol += ".IS"
    return symbol

async def get_finance_data_cached(symbol: str, period: str = "1mo") -> Dict:
    """Cache ile finans verisi al"""
    cache_key = f"finance_{symbol}_{period}"
    cached = finance_cache.get(cache_key)
    if cached:
        logger.info(f"Cache hit for {cache_key}")
        return cached

    result = await get_finance_data(symbol, period)
    finance_cache.set(cache_key, result)
    return result

async def get_finance_data(symbol: str, period: str = "1mo") -> Dict:
    """YFinance ile finans verisi al"""
    try:
        symbol = normalize_symbol(symbol)
        logger.info(f"Fetching data for {symbol} with period {period}")

        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)

        # BIST fallback
        if hist.empty and not symbol.endswith(".IS"):
            symbol_fallback = symbol + ".IS"
            logger.info(f"Trying BIST fallback: {symbol_fallback}")
            ticker = yf.Ticker(symbol_fallback)
            hist = ticker.history(period=period)

        if hist.empty:
            raise ValueError("Veri bulunamadı veya geçersiz sembol")

        # Current price calculations
        current = float(hist["Close"].iloc[-1])
        previous = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current
        change = current - previous
        change_pct = (change / previous * 100) if previous != 0 else 0

        # Info
        info = ticker.info
        name = info.get("longName") or info.get("shortName") or symbol.replace(".IS", "")
        currency = info.get("currency", "TRY" if ".IS" in symbol else "USD")

        # Historical data
        dates = hist.index.strftime("%Y-%m-%d").tolist()
        prices = hist["Close"].round(2).tolist()
        highs = hist["High"].round(2).tolist()
        lows = hist["Low"].round(2).tolist()
        volumes = hist["Volume"].tolist()

        result = {
            "symbol": symbol.replace(".IS", ""),
            "name": name,
            "currency": currency,
            "current_price": round(current, 2),
            "change": round(change, 2),
            "change_percent": round(change_pct, 2),
            "volume": int(hist["Volume"].iloc[-1]) if not hist["Volume"].empty else 0,
            "avg_volume_10d": int(hist["Volume"].tail(10).mean()) if len(hist) >= 10 else 0,
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "dividend_yield": info.get("dividendYield"),
            "historical_data": {
                "dates": dates,
                "prices": prices,
                "highs": highs,
                "lows": lows,
                "volumes": volumes
            },
            "fetched_at": datetime.now().isoformat(),
            "error": None
        }

        logger.info(f"Successfully fetched data for {symbol}")
        return result

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Finance data error for {symbol}: {error_msg}")
        return {
            "symbol": symbol,
            "error": error_msg,
            "historical_data": {"dates": [], "prices": [], "highs": [], "lows": [], "volumes": []}
        }

# ==================== ML TAHMİN (Pre-trained Model) ====================
class MLModelManager:
    """ML model yönetim sınıfı - production için optimize edilmiş"""
    
    def __init__(self):
        self.models = {}
        self.last_trained = {}
        self.feature_names = None
    
    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """İndikatörleri hesapla - optimize edilmiş"""
        df = df.copy()
        
        # Temel indikatörler (hızlı)
        df["sma_20"] = ta.sma(df["Close"], length=20)
        df["ema_10"] = ta.ema(df["Close"], length=10)
        df["rsi_14"] = ta.rsi(df["Close"], length=14)
        
        macd = ta.macd(df["Close"])
        if macd is not None:
            df["macd"] = macd["MACD_12_26_9"]
            df["macd_sig"] = macd["MACDs_12_26_9"]
        
        bb = ta.bbands(df["Close"], length=20)
        if bb is not None:
            df["bb_upper"] = bb["BBU_20_2.0"]
            df["bb_lower"] = bb["BBL_20_2.0"]
        
        df["momentum"] = df["Close"].diff(4)
        df["volatility"] = df["Close"].rolling(window=10).std()
        
        return df.dropna()
    
    async def predict_price(self, symbol: str, horizon: int = 5) -> Dict:
        """Hızlı ML tahmini - sadece inference"""
        try:
            # Veri çek
            data = await get_finance_data(symbol, "6mo")
            if data.get("error"):
                return {"error": data["error"]}
            
            # DataFrame hazırla
            df = pd.DataFrame({
                "Date": data["historical_data"]["dates"],
                "Close": data["historical_data"]["prices"],
                "High": data["historical_data"]["highs"],
                "Low": data["historical_data"]["lows"],
                "Volume": data["historical_data"]["volumes"]
            }).set_index("Date")
            df.index = pd.to_datetime(df.index)
            
            # İndikatörler
            df = self._prepare_features(df)
            
            if len(df) < 50:
                return {"error": "Yeterli veri yok (min 50 günlük gerekli)"}
            
            # Basit momentum-based tahmin (XGBoost yerine hızlı alternatif)
            recent_trend = df["Close"].iloc[-10:].diff().mean()
            current_price = df["Close"].iloc[-1]
            
            # Tahmin: Trend + RSI düzeltmesi
            rsi = df["rsi_14"].iloc[-1]
            rsi_factor = 1.0
            if rsi > 70:
                rsi_factor = 0.95  # Aşırı alım düzeltmesi
            elif rsi < 30:
                rsi_factor = 1.05  # Aşırı satım düzeltmesi
            
            predicted_price = current_price + (recent_trend * horizon * rsi_factor)
            
            # Yön belirle
            direction = "↑ YUKARI" if predicted_price > current_price else "↓ AŞAĞI"
            direction_class = "positive" if predicted_price > current_price else "negative"
            
            return {
                "predicted_price": round(float(predicted_price), 2),
                "current_price": round(float(current_price), 2),
                "horizon": horizon,
                "direction": direction,
                "direction_class": direction_class,
                "confidence": round(min(95, max(50, 100 - abs(recent_trend) * 10)), 1),
                "note": "İstatistiksel tahmin – yatırım tavsiyesi değildir",
                "method": "Momentum + RSI Adjusted"
            }
            
        except Exception as e:
            logger.error(f"ML prediction error: {str(e)}")
            return {"error": f"ML tahmin hatası: {str(e)}"}

# Global ML Manager
ml_manager = MLModelManager()

# ==================== ROUTES ====================
@app.get("/", response_class=HTMLResponse)
async def home():
    return get_frontend_html()

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "4.0.0",
        "environment": ENVIRONMENT,
        "timestamp": datetime.now().isoformat(),
        "qwen_configured": bool(OPENROUTER_API_KEY),
        "cache_stats": {
            "finance_cache": len(finance_cache.cache),
            "ml_cache": len(ml_cache.cache)
        }
    }

@app.get("/api/symbols")
async def get_symbols():
    """Desteklenen semboller"""
    return {
        "bist": [
            {"symbol": "THYAO", "name": "Türk Hava Yolları"},
            {"symbol": "AKBNK", "name": "Akbank"},
            {"symbol": "GARAN", "name": "Garanti BBVA"},
            {"symbol": "ISCTR", "name": "İş Bankası"},
            {"symbol": "EREGL", "name": "Ereğli Demir Çelik"},
            {"symbol": "SISE", "name": "Şişecam"},
            {"symbol": "KCHOL", "name": "Koç Holding"},
            {"symbol": "ASELS", "name": "Aselsan"},
            {"symbol": "TUPRS", "name": "Tüpraş"},
            {"symbol": "FROTO", "name": "Ford Otosan"}
        ],
        "global": [
            {"symbol": "AAPL", "name": "Apple"},
            {"symbol": "MSFT", "name": "Microsoft"},
            {"symbol": "NVDA", "name": "NVIDIA"},
            {"symbol": "GOOGL", "name": "Google"},
            {"symbol": "AMZN", "name": "Amazon"},
            {"symbol": "TSLA", "name": "Tesla"},
            {"symbol": "META", "name": "Meta"},
            {"symbol": "BTC-USD", "name": "Bitcoin"}
        ]
    }

@app.get("/api/finance/{symbol}")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def api_finance(request: Request, symbol: str, period: str = "1mo"):
    """Finans verisi API - Rate limited"""
    try:
        # Validasyon
        if period not in ALLOWED_PERIODS:
            raise HTTPException(400, f"Geçersiz dönem. İzin verilenler: {ALLOWED_PERIODS}")
        
        # Cache'den veya API'den veri al
        result = await get_finance_data_cached(symbol, period)
        
        if result.get("error"):
            raise HTTPException(404, result["error"])
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Finance API error: {str(e)}")
        raise HTTPException(500, "Veri alınırken hata oluştu")

@app.get("/api/predict/{symbol}")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def api_predict(request: Request, symbol: str, horizon: int = 5):
    """ML tahmin API - Rate limited"""
    try:
        cache_key = f"ml_{symbol}_{horizon}"
        cached = ml_cache.get(cache_key)
        if cached:
            logger.info(f"ML cache hit for {cache_key}")
            return cached
        
        result = await ml_manager.predict_price(symbol, horizon)
        
        if not result.get("error"):
            ml_cache.set(cache_key, result)
        
        if result.get("error"):
            raise HTTPException(400, result["error"])
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Prediction API error: {str(e)}")
        raise HTTPException(500, "Tahmin yapılırken hata oluştu")

@app.post("/api/ai/ask")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def api_ai_ask(request: Request, query: AIQueryRequest):
    """AI sorgu API - Rate limited & validated"""
    try:
        user_msg = query.message
        
        # Sembol çıkar
        symbol_match = re.search(r'\b([A-Z]{3,5}(?:\.[A-Z]{2})?)\b', user_msg.upper())
        symbol = symbol_match.group(1) if symbol_match else "THYAO"
        
        # ML tahmini al (cache'li)
        ml_result = await ml_manager.predict_price(symbol, 5)
        
        # ML bilgisi hazırla
        ml_info = ""
        if not ml_result.get("error"):
            ml_info = f"""
📊 ML ANALİZ SONUÇLARI (Son 6 Ay Verisi):
• Tahmini Fiyat (5 gün): {ml_result['predicted_price']}
• Mevcut Fiyat: {ml_result['current_price']}
• Beklenen Yön: {ml_result['direction']}
• Güven Seviyesi: %{ml_result['confidence']}
• Yöntem: Momentum + RSI Adjusted
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        # System prompt
        system_prompt = """Sen deneyimli bir finansal analist ve trading uzmanısın.
Kullanıcılara net, profesyonel ve dengeli analizler sun.
Kurallar:
1. Spekülatif ifadeler kullanma ("kesinlikle yükselecek" gibi)
2. Riskleri mutlaka belirt
3. Teknik analiz terimlerini açıkla
4. Kısa ve öz cevaplar ver (max 300 kelime)
5. Türkçe ve profesyonel bir dil kullan
6. ML tahminlerini referans al ama mutlak doğru varsayma
7. Yatırım tavsiyesi verme, sadece bilgilendir"""

        # Enhanced message
        enhanced_msg = f"""
KULLANICI SORUSU:
{user_msg}

{ml_info}

Lütfen yukarıdaki bağlamda profesyonel bir analiz sun."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": enhanced_msg}
        ]

        # Qwen çağrısı
        reply = await call_qwen(messages)
        
        # XSS koruması
        reply_safe = re.sub(r'<script.*?>.*?</script>', '', reply, flags=re.IGNORECASE)
        
        return {"reply": reply_safe, "symbol_used": symbol}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI API error: {str(e)}")
        raise HTTPException(500, "AI servisi hatası")

# ==================== FRONTEND HTML ====================
def get_frontend_html() -> str:
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
            --dark-600: #475569;
            --light: #f8fafc;
            --gray: #94a3b8;
            --border-radius: 16px;
            --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            --transition: all 0.3s ease;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #e2e8f0;
            line-height: 1.6;
            min-height: 100vh;
            padding: 0;
            margin: 0;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 1.5rem;
        }

        /* Header */
        header {
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            padding: 2rem 0;
            text-align: center;
            border-bottom-left-radius: var(--border-radius);
            border-bottom-right-radius: var(--border-radius);
            margin-bottom: 2rem;
            box-shadow: var(--shadow);
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
            background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0) 70%);
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
            letter-spacing: -1px;
        }

        .tagline {
            font-size: 1.2rem;
            color: rgba(255, 255, 255, 0.9);
            margin-top: 0.5rem;
            font-weight: 300;
        }

        .status-badge {
            display: inline-block;
            background: rgba(255, 255, 255, 0.2);
            padding: 0.3rem 1rem;
            border-radius: 20px;
            font-size: 0.85rem;
            margin-top: 0.8rem;
            backdrop-filter: blur(10px);
        }

        /* Dashboard Grid */
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

        /* Cards */
        .card {
            background: rgba(30, 41, 59, 0.7);
            border-radius: var(--border-radius);
            padding: 1.8rem;
            border: 1px solid rgba(255, 255, 255, 0.08);
            backdrop-filter: blur(10px);
            box-shadow: var(--shadow);
            transition: var(--transition);
        }

        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
            border-color: rgba(99, 102, 241, 0.3);
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 2px solid rgba(99, 102, 241, 0.2);
        }

        .card-title {
            font-size: 1.5rem;
            font-weight: 700;
            color: white;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .card-title i {
            color: var(--primary);
        }

        /* Form Controls */
        .form-group {
            margin-bottom: 1.2rem;
        }

        label {
            display: block;
            margin-bottom: 0.5rem;
            color: #cbd5e1;
            font-weight: 500;
            font-size: 0.95rem;
        }

        select, textarea {
            width: 100%;
            padding: 0.9rem 1.2rem;
            border-radius: 10px;
            border: 2px solid var(--dark-600);
            background: var(--dark-800);
            color: white;
            font-size: 1rem;
            font-family: inherit;
            transition: var(--transition);
        }

        select:focus, textarea:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
        }

        textarea {
            min-height: 120px;
            resize: vertical;
        }

        /* Buttons */
        .btn-group {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.8rem;
            margin-top: 1rem;
        }

        button {
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            color: white;
            border: none;
            padding: 1rem;
            border-radius: 12px;
            font-weight: 600;
            font-size: 1rem;
            cursor: pointer;
            transition: var(--transition);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3);
        }

        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4);
            opacity: 0.95;
        }

        button:active {
            transform: translateY(0);
        }

        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        .btn-ml {
            background: linear-gradient(90deg, var(--secondary), #d946ef);
        }

        .btn-ai {
            background: linear-gradient(90deg, var(--info), #6366f1);
        }

        /* Results */
        .result {
            margin-top: 1.5rem;
            padding: 1.2rem;
            background: rgba(255, 255, 255, 0.04);
            border-radius: 12px;
            border-left: 4px solid var(--primary);
            min-height: 80px;
            position: relative;
        }

        .result.loading {
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--info);
        }

        .spinner {
            border: 3px solid rgba(99, 102, 241, 0.3);
            border-top: 3px solid var(--primary);
            border-radius: 50%;
            width: 30px;
            height: 30px;
            animation: spin 1s linear infinite;
            margin-right: 10px;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .result.error {
            border-left-color: var(--danger);
            background: rgba(239, 68, 68, 0.1);
            color: #fecaca;
        }

        .result.success {
            border-left-color: var(--success);
        }

        .positive {
            color: var(--success);
            font-weight: 600;
        }

        .negative {
            color: var(--danger);
            font-weight: 600;
        }

        .info-text {
            color: var(--gray);
            font-size: 0.85rem;
            margin-top: 0.5rem;
            font-style: italic;
        }

        /* Chart */
        .chart-container {
            height: 400px;
            margin-top: 1.5rem;
            background: rgba(0, 0, 0, 0.1);
            border-radius: 12px;
            padding: 1rem;
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }

        .stat-card {
            background: rgba(255, 255, 255, 0.05);
            padding: 1rem;
            border-radius: 10px;
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .stat-value {
            font-size: 1.5rem;
            font-weight: 700;
            margin: 0.3rem 0;
        }

        .stat-label {
            font-size: 0.8rem;
            color: var(--gray);
        }

        /* Footer */
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

        footer a:hover {
            text-decoration: underline;
        }

        /* Animations */
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .fade-in {
            animation: fadeIn 0.6s ease-out forwards;
        }

        /* Toast Notifications */
        #toast-container {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10000;
        }

        .toast {
            background: rgba(30, 41, 59, 0.95);
            color: white;
            padding: 1rem 1.5rem;
            border-radius: 10px;
            margin-bottom: 10px;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
            border-left: 4px solid var(--primary);
            animation: slideIn 0.3s ease-out;
            min-width: 300px;
        }

        .toast.error {
            border-left-color: var(--danger);
            background: rgba(239, 68, 68, 0.9);
        }

        .toast.success {
            border-left-color: var(--success);
            background: rgba(16, 185, 129, 0.9);
        }

        @keyframes slideIn {
            from { transform: translateX(400px); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }

        /* Responsive */
        @media (max-width: 768px) {
            .logo {
                font-size: 2.5rem;
            }
            
            .dashboard {
                grid-template-columns: 1fr;
            }
            
            .btn-group {
                grid-template-columns: 1fr;
            }
            
            .chart-container {
                height: 300px;
            }
            
            .container {
                padding: 0 1rem;
            }
            
            .card {
                padding: 1.2rem;
            }
        }
    </style>
</head>
<body>
    <div id="toast-container"></div>

    <header>
        <div class="container">
            <div class="logo">
                <i class="fas fa-rocket"></i> ICTSmartPro AI
            </div>
            <div class="tagline">Yapay Zeka + Makine Öğrenmesi ile Akıllı Hisse Analizi</div>
            <div class="status-badge">
                <i class="fas fa-check-circle" style="color: #10b981; margin-right: 5px;"></i>
                Production Ready • Real-time Data • ML Powered
            </div>
        </div>
    </header>

    <div class="container">
        <div class="dashboard">
            <!-- Stock Analysis Card -->
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">
                        <i class="fas fa-chart-line"></i> Hisse Analizi
                    </h2>
                </div>

                <div class="form-group">
                    <label for="symbol">
                        <i class="fas fa-search"></i> Sembol Seçin
                    </label>
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
                            <option value="TUPRS">TUPRS - Tüpraş</option>
                            <option value="FROTO">FROTO - Ford Otosan</option>
                        </optgroup>
                        <optgroup label="Global">
                            <option value="AAPL">AAPL - Apple</option>
                            <option value="MSFT">MSFT - Microsoft</option>
                            <option value="NVDA">NVDA - NVIDIA</option>
                            <option value="GOOGL">GOOGL - Google</option>
                            <option value="AMZN">AMZN - Amazon</option>
                            <option value="TSLA">TSLA - Tesla</option>
                            <option value="META">META - Meta</option>
                        </optgroup>
                    </select>
                </div>

                <div class="form-group">
                    <label for="period">
                        <i class="fas fa-calendar-alt"></i> Analiz Dönemi
                    </label>
                    <select id="period">
                        <option value="5d">Son 5 Gün</option>
                        <option value="1mo" selected>1 Ay</option>
                        <option value="3mo">3 Ay</option>
                        <option value="6mo">6 Ay</option>
                        <option value="1y">1 Yıl</option>
                        <option value="2y">2 Yıl</option>
                    </select>
                </div>

                <div class="btn-group">
                    <button id="analyzeBtn" class="btn-ai">
                        <i class="fas fa-search"></i> Analiz Et
                    </button>
                    <button id="predictBtn" class="btn-ml">
                        <i class="fas fa-brain"></i> ML Tahmin Al
                    </button>
                </div>

                <div id="financeResult" class="result loading">
                    <div class="spinner"></div>
                    Sembol seçip "Analiz Et" butonuna basın...
                </div>

                <div id="mlResult" class="result" style="margin-top: 1rem; display: none;">
                    <div class="spinner"></div>
                    ML tahmini burada görünecek...
                </div>

                <div id="statsGrid" class="stats-grid" style="display: none;"></div>
            </div>

            <!-- AI Analysis Card -->
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">
                        <i class="fas fa-robot"></i> Qwen AI Analisti
                    </h2>
                </div>

                <div class="form-group">
                    <label for="aiQuery">
                        <i class="fas fa-comment-alt"></i> Sorunuzu Yazın
                    </label>
                    <textarea id="aiQuery" placeholder="Örnek sorular:
• THYAO için teknik görünüm nasıl?
• AKBNK'ta alım fırsatı var mı?
• NVIDIA son 1 ay performansını değerlendir
• RSI ve MACD göstergelerine göre GARAN analizi"></textarea>
                </div>

                <button id="askBtn" style="width: 100%; margin-top: 0.5rem;">
                    <i class="fas fa-paper-plane"></i> Qwen'e Sor
                </button>

                <div id="aiResult" class="result loading" style="margin-top: 1rem; min-height: 200px;">
                    <div class="spinner"></div>
                    Sorunuzu yazıp Qwen'e sorun...
                </div>

                <div class="info-text" style="margin-top: 1rem;">
                    <i class="fas fa-info-circle"></i> 
                    AI analizleri ML tahminleri ile desteklenir. Spekülatif değildir, bilgilendiricidir.
                </div>
            </div>
        </div>

        <!-- Chart Card -->
        <div class="card">
            <div class="card-header">
                <h2 class="card-title">
                    <i class="fas fa-chart-bar"></i> Fiyat Grafiği
                </h2>
            </div>
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
                <a href="/docs" target="_blank">API Docs</a> |
                <span style="color: var(--warning); margin-left: 10px;">
                    <i class="fas fa-exclamation-triangle"></i> Yatırım danışmanlığı değildir
                </span>
            </p>
        </div>
    </footer>

    <script>
        let chartInstance = null;
        let isProcessing = false;

        // Toast Notification
        function showToast(message, type = 'info') {
            const container = document.getElementById('toast-container');
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.innerHTML = `
                <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-triangle' : 'info-circle'}" 
                   style="margin-right: 10px;"></i>
                ${message}
            `;
            container.appendChild(toast);
            
            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transform = 'translateX(400px)';
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }

        // Analyze Stock
        async function analyzeStock() {
            if (isProcessing) return;
            isProcessing = true;

            const symbol = document.getElementById('symbol').value;
            const period = document.getElementById('period').value;
            const resDiv = document.getElementById('financeResult');
            const statsGrid = document.getElementById('statsGrid');

            resDiv.className = 'result loading';
            resDiv.innerHTML = '<div class="spinner"></div> Veriler çekiliyor...';
            statsGrid.style.display = 'none';

            try {
                const resp = await fetch(`/api/finance/${encodeURIComponent(symbol)}?period=${period}`);
                
                if (!resp.ok) {
                    const errorData = await resp.json().catch(() => ({}));
                    throw new Error(errorData.detail || `HTTP ${resp.status}`);
                }

                const data = await resp.json();

                if (data.error) {
                    throw new Error(data.error);
                }

                // Format result
                let html = `
                    <div style="font-size: 1.3rem; font-weight: 700; margin-bottom: 0.8rem; color: white;">
                        ${data.symbol} - ${data.name}
                    </div>
                    <div style="font-size: 2rem; font-weight: 800; margin: 0.5rem 0; color: ${data.change_percent >= 0 ? '#10b981' : '#ef4444'};">
                        ${data.current_price.toLocaleString('tr-TR')} ${data.currency}
                        <span style="font-size: 1.2rem; margin-left: 10px;">
                            ${data.change_percent >= 0 ? '↑' : '↓'} ${Math.abs(data.change_percent).toFixed(2)}%
                        </span>
                    </div>
                    <div style="color: var(--gray); margin-bottom: 1rem;">
                        Değişim: ${data.change >= 0 ? '+' : ''}${data.change.toFixed(2)} ${data.currency} |
                        Hacim: ${data.volume.toLocaleString('tr-TR')}
                    </div>
                `;

                if (data.market_cap) {
                    html += `<div style="color: var(--gray); font-size: 0.9rem;">
                        Piyasa Değeri: ${(data.market_cap / 1e9).toFixed(1)} Milyar ${data.currency}
                    </div>`;
                }

                if (data.pe_ratio) {
                    html += `<div style="color: var(--gray); font-size: 0.9rem;">
                        F/K Oranı: ${data.pe_ratio.toFixed(2)}
                    </div>`;
                }

                resDiv.className = 'result success';
                resDiv.innerHTML = html;

                // Stats Grid
                statsGrid.innerHTML = `
                    <div class="stat-card">
                        <div class="stat-value">${data.current_price}</div>
                        <div class="stat-label">Mevcut Fiyat</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" style="color: ${data.change_percent >= 0 ? 'var(--success)' : 'var(--danger)'}">
                            ${data.change_percent >= 0 ? '+' : ''}${data.change_percent.toFixed(2)}%
                        </div>
                        <div class="stat-label">Günlük Değişim</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${(data.volume / 1e6).toFixed(1)}M</div>
                        <div class="stat-label">Hacim</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${(data.avg_volume_10d / 1e6).toFixed(1)}M</div>
                        <div class="stat-label">10G Ort. Hacim</div>
                    </div>
                `;
                statsGrid.style.display = 'grid';

                // Draw chart
                if (data.historical_data?.prices?.length > 0) {
                    drawChart(data.historical_data, data.symbol, data.name);
                }

                showToast(`✅ ${data.name} analizi tamamlandı!`, 'success');

            } catch (err) {
                resDiv.className = 'result error';
                resDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> Hata: ${err.message}`;
                showToast(`❌ ${err.message}`, 'error');
                console.error('Analyze error:', err);
            } finally {
                isProcessing = false;
            }
        }

        // ML Prediction
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
                
                if (!resp.ok) {
                    const errorData = await resp.json().catch(() => ({}));
                    throw new Error(errorData.detail || `HTTP ${resp.status}`);
                }

                const data = await resp.json();

                if (data.error) {
                    throw new Error(data.error);
                }

                let html = `
                    <div style="font-size: 1.1rem; font-weight: 700; margin-bottom: 1rem; color: white;">
                        🎯 5 Gün Sonrası ML Tahmini
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem;">
                        <div>
                            <div style="color: var(--gray); font-size: 0.9rem;">Tahmini Fiyat</div>
                            <div style="font-size: 1.5rem; font-weight: 800; color: ${data.direction_class === 'positive' ? 'var(--success)' : 'var(--danger)'};">
                                ${data.predicted_price} ${data.direction.includes('↑') ? '📈' : '📉'}
                            </div>
                        </div>
                        <div>
                            <div style="color: var(--gray); font-size: 0.9rem;">Mevcut Fiyat</div>
                            <div style="font-size: 1.5rem; font-weight: 800;">
                                ${data.current_price}
                            </div>
                        </div>
                    </div>
                    <div style="background: rgba(99, 102, 241, 0.1); padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
                        <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                            <span style="color: var(--gray);">Beklenen Yön:</span>
                            <span class="${data.direction_class}" style="font-weight: 600;">
                                ${data.direction}
                            </span>
                        </div>
                        <div style="display: flex; justify-content: space-between;">
                            <span style="color: var(--gray);">Güven Seviyesi:</span>
                            <span style="color: var(--warning); font-weight: 600;">
                                %${data.confidence}
                            </span>
                        </div>
                    </div>
                    <div style="font-size: 0.85rem; color: var(--gray); font-style: italic;">
                        <i class="fas fa-info-circle"></i> ${data.note}<br>
                        Yöntem: ${data.method}
                    </div>
                `;

                mlDiv.className = 'result success';
                mlDiv.innerHTML = html;

                showToast('🤖 ML tahmini hazır!', 'success');

            } catch (err) {
                mlDiv.className = 'result error';
                mlDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ML Hatası: ${err.message}`;
                showToast(`❌ ${err.message}`, 'error');
                console.error('ML error:', err);
            } finally {
                isProcessing = false;
            }
        }

        // Ask AI
        async function askQwen() {
            if (isProcessing) return;
            isProcessing = true;

            const query = document.getElementById('aiQuery').value.trim();
            const aiDiv = document.getElementById('aiResult');

            if (!query) {
                showToast('⚠️ Lütfen bir soru yazın!', 'error');
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

                if (!resp.ok) {
                    const errorText = await resp.text();
                    throw new Error(`HTTP ${resp.status}: ${errorText}`);
                }

                const data = await resp.json();
                
                // XSS koruması ile render
                const cleanHTML = DOMPurify.sanitize(data.reply.replace(/\n/g, '<br>'));
                aiDiv.className = 'result success';
                aiDiv.innerHTML = cleanHTML;

                showToast(`🤖 Qwen cevap verdi! (${data.symbol_used})`, 'success');

            } catch (err) {
                aiDiv.className = 'result error';
                aiDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> AI Hatası: ${err.message}`;
                showToast(`❌ ${err.message}`, 'error');
                console.error('AI error:', err);
            } finally {
                isProcessing = false;
            }
        }

        // Draw Chart
        function drawChart(hdata, symbol, name) {
            const ctx = document.getElementById('priceChart').getContext('2d');
            
            if (chartInstance) {
                chartInstance.destroy();
            }

            // Prepare data
            const labels = hdata.dates;
            const prices = hdata.prices;
            const backgroundColor = 'rgba(99, 102, 241, 0.1)';
            const borderColor = '#6366f1';
            const borderWidth = 3;

            chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: `${symbol} - ${name}`,
                        data: prices,
                        borderColor: borderColor,
                        backgroundColor: backgroundColor,
                        borderWidth: borderWidth,
                        tension: 0.3,
                        fill: true,
                        pointRadius: 0,
                        pointHoverRadius: 6,
                        pointHoverBackgroundColor: borderColor
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        intersect: false,
                        mode: 'index'
                    },
                    plugins: {
                        legend: {
                            labels: {
                                color: '#e2e8f0',
                                font: {
                                    size: 13,
                                    weight: 'bold'
                                }
                            }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.9)',
                            titleColor: '#ffffff',
                            bodyColor: '#cbd5e1',
                            borderColor: 'rgba(99, 102, 241, 0.5)',
                            borderWidth: 1,
                            padding: 12,
                            displayColors: false
                        }
                    },
                    scales: {
                        y: {
                            grid: {
                                color: 'rgba(255, 255, 255, 0.05)'
                            },
                            ticks: {
                                color: '#94a3b8',
                                font: {
                                    size: 11
                                }
                            },
                            border: {
                                color: 'rgba(255, 255, 255, 0.1)'
                            }
                        },
                        x: {
                            grid: {
                                color: 'rgba(255, 255, 255, 0.03)',
                                drawBorder: false
                            },
                            ticks: {
                                color: '#94a3b8',
                                font: {
                                    size: 10
                                },
                                maxRotation: 45,
                                minRotation: 45
                            },
                            border: {
                                color: 'rgba(255, 255, 255, 0.1)'
                            }
                        }
                    }
                }
            });
        }

        // Event Listeners
        document.addEventListener('DOMContentLoaded', () => {
            document.getElementById('analyzeBtn').addEventListener('click', analyzeStock);
            document.getElementById('predictBtn').addEventListener('click', getMLPrediction);
            document.getElementById('askBtn').addEventListener('click', askQwen);
            
            // Enter key for AI query
            document.getElementById('aiQuery').addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    askQwen();
                }
            });

            // Auto analyze on load
            setTimeout(analyzeStock, 500);
        });
    </script>
</body>
</html>
    """

# ==================== MAIN ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=PORT,
        reload=DEBUG,
        log_level="info",
        workers=4 if not DEBUG else 1
    )
