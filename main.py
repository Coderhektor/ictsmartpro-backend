"""
ICTSmartPro Trading AI - WebSocket Entegreli (Binance API'siz)
✅ Public WebSocket ✅ İlk 10 Coin ✅ TradingView ✅ Zero API Key
Version: 8.0.0
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import re
import json
import asyncio

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
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
import websockets

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

# ==================== POPÜLER COINLER (Binance Public WebSocket) ====================
POPULAR_COINS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT", "DOTUSDT"
]

# ==================== RATE LIMITING ====================
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="ICTSmartPro Trading AI",
    description="WebSocket Entegreli Dinamik Trading Platformu",
    version="8.0.0",
    docs_url=None,
    redoc_url=None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse({"error": "Rate limit aşıldı"}, 429))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ictsmartpro.ai", "https://www.ictsmartpro.ai"] if not DEBUG else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ==================== EXCHANGE DETECTION ====================
def detect_exchange(symbol: str) -> str:
    """
    Sembolü analiz ederek exchange tespiti
    BTCUSDT → binance_ws (WebSocket)
    TSLA → yfinance_stock
    BTC-USD → yfinance_crypto
    """
    symbol_upper = symbol.upper().strip()
    
    # Binance formatı: BTCUSDT, ETHUSDT (USDT bitenler)
    if symbol_upper in POPULAR_COINS or (symbol_upper.endswith("USDT") and len(symbol_upper) <= 12):
        return "binance_ws"
    
    # YFinance crypto formatı: BTC-USD, ETH-USD
    if re.match(r'^[A-Z]{3,8}-USD$', symbol_upper):
        return "yfinance_crypto"
    
    # Stock sembolleri: TSLA, AAPL, NVDA
    if re.match(r'^[A-Z]{2,6}$', symbol_upper) and len(symbol_upper) <= 6:
        return "yfinance_stock"
    
    # Varsayılan: yfinance stock
    return "yfinance_stock"

# ==================== BINANCE WEBSOCKET MANAGER ====================
class BinanceWebSocketManager:
    def __init__(self):
        self.ws_url = "wss://stream.binance.com:9443/stream"
        self.active_connections: Dict[str, dict] = {}  # symbol -> {price, volume, timestamp}
        logger.info("✅ Binance WebSocket Manager başlatıldı (Public API - Zero Key)")
    
    async def get_latest_price(self, symbol: str) -> Dict:
        """
        Public WebSocket'ten son fiyatı alır
        """
        symbol_lower = symbol.lower()
        stream_name = f"{symbol_lower}@ticker"
        
        try:
            async with websockets.connect(self.ws_url) as websocket:
                # Stream'i subscribe et
                await websocket.send(json.dumps({
                    "method": "SUBSCRIBE",
                    "params": [stream_name],
                    "id": 1
                }))
                
                # İlk mesajı bekle (subscription confirmation)
                await websocket.recv()
                
                # Gerçek veriyi bekle
                message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                data = json.loads(message)
                
                if 'e' in data and data['e'] == '24hrTicker':
                    return {
                        "symbol": symbol.upper(),
                        "current_price": float(data['c']),  # close price
                        "change_percent": float(data['P']),  # price change percent
                        "volume": float(data['v']),  # volume
                        "high_24h": float(data['h']),
                        "low_24h": float(data['l']),
                        "exchange": "binance_ws",
                        "error": None
                    }
                else:
                    return {"error": "Geçersiz WebSocket yanıtı", "exchange": "binance_ws"}
                    
        except asyncio.TimeoutError:
            return {"error": "WebSocket timeout", "exchange": "binance_ws"}
        except Exception as e:
            logger.error(f"Binance WebSocket error for {symbol}: {str(e)}")
            return {"error": str(e), "exchange": "binance_ws"}

binance_ws_manager = BinanceWebSocketManager()

# ==================== YFINANCE MANAGER ====================
async def get_yfinance_data(symbol: str, period: str = "1mo", is_crypto: bool = False) -> Dict:
    """
    YFinance'dan hisse/crypto verisi çeker
    """
    try:
        # Crypto için format düzeltme
        if is_crypto and not symbol.endswith("-USD"):
            symbol = f"{symbol}-USD"
        
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        
        if hist.empty:
            # Alternative symbol denemeleri
            alt_symbols = [
                symbol + ".IS",  # BIST
                symbol.replace("-USD", "USD=X"),  # Forex format
            ]
            for alt in alt_symbols:
                ticker = yf.Ticker(alt)
                hist = ticker.history(period=period)
                if not hist.empty:
                    symbol = alt
                    break
            
            if hist.empty:
                return {"error": f"{symbol} için veri bulunamadı"}
        
        current = float(hist["Close"].iloc[-1])
        previous = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current
        change = current - previous
        change_pct = (change / previous * 100) if previous != 0 else 0

        info = ticker.info
        name = info.get("longName") or info.get("shortName") or symbol
        currency = info.get("currency", "USD")

        return {
            "symbol": symbol,
            "name": name,
            "currency": currency,
            "current_price": round(current, 2),
            "change": round(change, 2),
            "change_percent": round(change_pct, 2),
            "volume": int(hist["Volume"].iloc[-1]) if not hist["Volume"].empty else 0,
            "market_cap": info.get("marketCap"),
            "historical_data": {
                "dates": hist.index.strftime("%Y-%m-%d").tolist(),
                "prices": hist["Close"].round(2).tolist(),
                "highs": hist["High"].round(2).tolist(),
                "lows": hist["Low"].round(2).tolist(),
                "volumes": hist["Volume"].tolist()
            },
            "exchange": "yfinance",
            "error": None
        }
    except Exception as e:
        logger.error(f"YFinance error for {symbol}: {str(e)}")
        return {"error": str(e), "exchange": "yfinance"}

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

finance_cache = SimpleCache(ttl_seconds=60)  # WebSocket için kısa cache
ml_cache = SimpleCache(ttl_seconds=3600)

# ==================== ML PREDICTION (Simple Momentum) ====================
class MLModelManager:
    async def predict_price(self, symbol: str, exchange: str, horizon: int = 5) -> Dict:
        """
        Basit momentum tabanlı tahmin
        """
        try:
            # Veri çekme (sadece yfinance için historical data gerekli)
            if exchange == "binance_ws":
                # WebSocket sadece anlık veri verir, historical için yfinance kullan
                symbol_yf = symbol.replace("USDT", "-USD")
                data = await get_yfinance_data(symbol_yf, period="3mo", is_crypto=True)
            elif exchange == "yfinance_crypto":
                data = await get_yfinance_data(symbol, period="3mo", is_crypto=True)
            else:  # yfinance_stock
                data = await get_yfinance_data(symbol, period="3mo", is_crypto=False)
            
            if data.get("error"):
                return {"error": data["error"]}
            
            if not data.get("historical_data") or not data["historical_data"]["prices"]:
                return {"error": "Yeterli veri yok"}
            
            prices = data["historical_data"]["prices"]
            current_price = prices[-1]
            
            if len(prices) < 10:
                return {"error": "Tahmin için yeterli veri yok (min 10 veri noktası)"}
            
            # Basit momentum hesaplama
            recent_trend = (prices[-1] - prices[-10]) / 10
            predicted_price = current_price + (recent_trend * horizon)
            
            direction = "↑ YUKARI" if predicted_price > current_price else "↓ AŞAĞI"
            confidence = min(95, max(60, 100 - abs(recent_trend) * 20))
            
            return {
                "predicted_price": round(float(predicted_price), 8 if exchange == "binance_ws" else 2),
                "current_price": round(float(current_price), 8 if exchange == "binance_ws" else 2),
                "horizon": horizon,
                "direction": direction,
                "direction_class": "positive" if predicted_price > current_price else "negative",
                "confidence": round(confidence, 1),
                "exchange": exchange,
                "note": "İstatistiksel momentum tahmini - yatırım tavsiyesi değildir",
                "method": "Simple Momentum Analysis"
            }
        except Exception as e:
            logger.error(f"ML prediction error: {str(e)}")
            return {"error": f"Tahmin hatası: {str(e)}"}

ml_manager = MLModelManager()

# ==================== AI ANALYSIS (Qwen) ====================
async def call_qwen(messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
    if not OPENROUTER_API_KEY:
        return "⚠️ OpenRouter API anahtarı tanımsız. AI analizleri sınırlı çalışıyor."
    
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
        "max_tokens": 1200,
        "stream": False
    }
    
    async with httpx.AsyncClient(timeout=45.0) as client:
        try:
            response = await client.post(f"{OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Qwen error: {str(e)}")
            return f"⚠️ AI geçici olarak kullanılamıyor"

# ==================== HEALTHCHECK ====================
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "8.0.0",
        "timestamp": datetime.now().isoformat(),
        "websocket_ready": True,
        "openrouter_configured": bool(OPENROUTER_API_KEY)
    }

@app.get("/ready")
async def ready_check():
    return {"ready": True}

# ==================== API ENDPOINTS ====================
@app.get("/api/symbols")
async def get_symbols():
    """Desteklenen semboller"""
    return {
        "popular_coins": POPULAR_COINS,
        "example_stocks": ["TSLA", "AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "AMD", "INTC", "COIN"],
        "example_crypto": ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"]
    }

@app.get("/api/finance/{symbol}")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def api_finance(request: Request, symbol: str, timeframe: str = "1h"):
    """
    Dinamik sembol için finansal veri (WebSocket + YFinance)
    """
    try:
        # Exchange tespiti
        exchange = detect_exchange(symbol)
        logger.info(f"Symbol: {symbol} → Exchange: {exchange}")
        
        cache_key = f"finance_{symbol}_{timeframe}_{exchange}"
        if cached := finance_cache.get(cache_key):
            logger.info(f"Cache hit: {cache_key}")
            return cached
        
        # Veri çekme
        if exchange == "binance_ws":
            # WebSocket'ten anlık veri
            result = await binance_ws_manager.get_latest_price(symbol)
            
            if not result.get("error"):
                # Historical data için yfinance kullan (grafik için)
                symbol_yf = symbol.replace("USDT", "-USD")
                yf_data = await get_yfinance_data(symbol_yf, period="1mo", is_crypto=True)
                
                if not yf_data.get("error"):
                    result["name"] = yf_data.get("name", symbol)
                    result["currency"] = "USDT"
                    result["historical_data"] = yf_data.get("historical_data", {})
        elif exchange == "yfinance_crypto":
            period_map = {"1d": "1mo", "1w": "3mo", "1h": "5d", "4h": "10d"}
            result = await get_yfinance_data(symbol, period=period_map.get(timeframe, "1mo"), is_crypto=True)
        else:  # yfinance_stock
            period_map = {"1d": "1mo", "1w": "3mo", "1h": "5d", "4h": "10d"}
            result = await get_yfinance_data(symbol, period=period_map.get(timeframe, "1mo"), is_crypto=False)
        
        if result.get("error"):
            logger.warning(f"Finance data error for {symbol}: {result['error']}")
            raise HTTPException(404, f"Veri alınamadı: {result['error']}")
        
        result["exchange"] = exchange
        finance_cache.set(cache_key, result)
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Finance API error: {str(e)}")
        raise HTTPException(500, f"Veri hatası: {str(e)}")

@app.get("/api/predict/{symbol}")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def api_predict(request: Request, symbol: str, horizon: int = 5):
    """
    Dinamik sembol için ML tahmini
    """
    try:
        exchange = detect_exchange(symbol)
        cache_key = f"ml_{symbol}_{horizon}_{exchange}"
        
        if cached := ml_cache.get(cache_key):
            return cached
        
        result = await ml_manager.predict_price(symbol, exchange, horizon)
        
        if result.get("error"):
            raise HTTPException(400, result["error"])
        
        ml_cache.set(cache_key, result)
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Prediction API error: {str(e)}")
        raise HTTPException(500, f"Tahmin hatası: {str(e)}")

class AIQueryRequest(BaseModel):
    message: str = Field(..., min_length=3, max_length=1000)
    symbol: str = Field(..., min_length=2, max_length=20)

    @field_validator("message")
    @classmethod
    def validate_message(cls, v):
        v = re.sub(r"<script.*?>.*?</script>", "", v, flags=re.IGNORECASE)
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Mesaj en az 3 karakter olmalı")
        return v

@app.post("/api/ai/ask")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def api_ai_ask(request: Request, query: AIQueryRequest):
    """
    Dinamik sembol için AI analizi
    """
    try:
        user_msg = query.message
        symbol = query.symbol
        exchange = detect_exchange(symbol)
        
        # ML tahmini al
        ml_result = await ml_manager.predict_price(symbol, exchange, 5)
        ml_info = ""
        if not ml_result.get("error"):
            ml_info = f"""
📊 ML ANALİZ SONUÇLARI:
• Tahmini Fiyat (5 gün): {ml_result['predicted_price']}
• Mevcut Fiyat: {ml_result['current_price']}
• Beklenen Yön: {ml_result['direction']}
• Güven Seviyesi: %{ml_result['confidence']}
• Exchange: {exchange.upper()}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        system_prompt = """Sen profesyonel bir trading analisti ve finansal uzmanısın.
Kullanıcılara net, profesyonel ve dengeli analizler sun.
Kurallar:
1. Spekülatif ifadeler kullanma ("kesinlikle yükselecek" gibi)
2. Riskleri mutlaka belirt
3. Teknik analiz terimlerini açıkla
4. Kısa ve öz cevaplar ver (max 300 kelime)
5. Türkçe ve profesyonel bir dil kullan
6. ML tahminlerini referans al ama mutlak doğru varsayma
7. Yatırım tavsiyesi verme, sadece bilgilendir"""

        enhanced_msg = f"""
KULLANICI SORUSU:
{user_msg}

SEMBOL: {symbol} (Exchange: {exchange.upper()})

{ml_info}

Lütfen yukarıdaki bağlamda profesyonel bir analiz sun."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": enhanced_msg}
        ]

        reply = await call_qwen(messages)
        reply_safe = re.sub(r'<script.*?>.*?</script>', '', reply, flags=re.IGNORECASE)
        
        return {
            "reply": reply_safe,
            "symbol_used": symbol,
            "exchange": exchange
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI API error: {str(e)}")
        raise HTTPException(500, f"AI hatası: {str(e)}")

# ==================== MAIN FRONTEND (TradingView + WebSocket) ====================
@app.get("/", response_class=HTMLResponse)
async def home():
    return """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="ICTSmartPro - WebSocket Entegreli Dinamik Trading Platformu">
    <title>ICTSmartPro Trading AI 🚀</title>
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
            max-width: 1600px;
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

        .control-panel {
            background: rgba(30, 41, 59, 0.9);
            border-radius: 16px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        }

        .control-row {
            display: grid;
            grid-template-columns: 2fr 1fr 1fr;
            gap: 1rem;
            align-items: center;
        }

        @media (max-width: 768px) {
            .control-row {
                grid-template-columns: 1fr;
            }
        }

        .input-group {
            display: flex;
            gap: 0.8rem;
        }

        input[type="text"], select {
            padding: 0.9rem 1.2rem;
            border-radius: 10px;
            border: 2px solid var(--dark-700);
            background: var(--dark-800);
            color: white;
            font-size: 1rem;
            font-family: inherit;
            flex: 1;
        }

        input[type="text"]:focus, select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
        }

        button {
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            color: white;
            border: none;
            padding: 0.9rem 1.5rem;
            border-radius: 12px;
            font-weight: 600;
            font-size: 1rem;
            cursor: pointer;
            transition: all 0.3s;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            white-space: nowrap;
        }

        button:hover {
            transform: translateY(-2px);
            opacity: 0.95;
        }

        button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }

        .btn-ml {
            background: linear-gradient(90deg, var(--secondary), #d946ef);
        }

        .btn-ai {
            background: linear-gradient(90deg, var(--info), #6366f1);
        }

        .dashboard {
            display: grid;
            grid-template-columns: 1fr 400px;
            gap: 2rem;
            margin-bottom: 2rem;
        }

        @media (max-width: 1024px) {
            .dashboard {
                grid-template-columns: 1fr;
            }
        }

        .card {
            background: rgba(30, 41, 59, 0.8);
            border-radius: 16px;
            padding: 1.5rem;
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        }

        .card-title {
            font-size: 1.3rem;
            font-weight: 700;
            color: white;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 1rem;
            padding-bottom: 0.8rem;
            border-bottom: 2px solid rgba(99, 102, 241, 0.2);
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

        .error {
            color: var(--danger);
            background: rgba(239, 68, 68, 0.1);
            padding: 0.8rem;
            border-radius: 8px;
        }

        .success {
            color: var(--success);
        }

        .positive { color: var(--success); font-weight: 600; }
        .negative { color: var(--danger); font-weight: 600; }

        .tradingview-widget {
            width: 100%;
            height: 600px;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 12px;
            overflow: hidden;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
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
            font-size: 1.2rem;
            font-weight: 700;
            margin: 0.3rem 0;
        }

        .stat-label {
            font-size: 0.8rem;
            color: var(--gray);
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

        .symbol-badge {
            display: inline-block;
            background: rgba(99, 102, 241, 0.2);
            padding: 0.3rem 0.8rem;
            border-radius: 20px;
            font-size: 0.85rem;
            margin-top: 0.5rem;
            font-weight: 600;
        }

        .example-symbols {
            display: flex;
            gap: 0.5rem;
            margin-top: 0.8rem;
            flex-wrap: wrap;
        }

        .example-symbol {
            background: rgba(255, 255, 255, 0.1);
            padding: 0.4rem 0.8rem;
            border-radius: 8px;
            font-size: 0.85rem;
            cursor: pointer;
            transition: all 0.2s;
        }

        .example-symbol:hover {
            background: rgba(99, 102, 241, 0.3);
        }

        .websocket-badge {
            display: inline-block;
            background: rgba(16, 185, 129, 0.2);
            color: var(--success);
            padding: 0.2rem 0.6rem;
            border-radius: 12px;
            font-size: 0.8rem;
            margin-left: 0.5rem;
        }

        .no-key-badge {
            display: inline-block;
            background: rgba(239, 68, 68, 0.15);
            color: var(--danger);
            padding: 0.2rem 0.6rem;
            border-radius: 12px;
            font-size: 0.8rem;
            margin-left: 0.5rem;
        }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <div class="logo">
                <i class="fas fa-rocket"></i> ICTSmartPro AI
            </div>
            <div class="tagline">
                WebSocket Entegreli • <span class="websocket-badge">Public API</span> 
                <span class="no-key-badge">Zero API Key</span> • Gerçek Zamanlı Veri
            </div>
        </div>
    </header>

    <div class="container">
        <!-- Control Panel -->
        <div class="control-panel">
            <div class="control-row">
                <div class="input-group">
                    <input type="text" id="symbolInput" placeholder="Sembol girin (ör: BTCUSDT, TSLA, ETHUSDT)" value="BTCUSDT">
                    <select id="timeframe">
                        <option value="1m">1 Dakika</option>
                        <option value="5m">5 Dakika</option>
                        <option value="15m">15 Dakika</option>
                        <option value="30m">30 Dakika</option>
                        <option value="1h" selected>1 Saat</option>
                        <option value="4h">4 Saat</option>
                        <option value="1d">1 Gün</option>
                        <option value="1w">1 Hafta</option>
                    </select>
                </div>
                <button id="analyzeBtn">
                    <i class="fas fa-search"></i> Analiz Et
                </button>
                <button id="predictBtn" class="btn-ml">
                    <i class="fas fa-brain"></i> ML Tahmin
                </button>
            </div>
            <div class="example-symbols">
                <div class="example-symbol" onclick="setSymbol('BTCUSDT')">BTCUSDT</div>
                <div class="example-symbol" onclick="setSymbol('ETHUSDT')">ETHUSDT</div>
                <div class="example-symbol" onclick="setSymbol('BNBUSDT')">BNBUSDT</div>
                <div class="example-symbol" onclick="setSymbol('SOLUSDT')">SOLUSDT</div>
                <div class="example-symbol" onclick="setSymbol('XRPUSDT')">XRPUSDT</div>
                <div class="example-symbol" onclick="setSymbol('TSLA')">TSLA</div>
                <div class="example-symbol" onclick="setSymbol('AAPL')">AAPL</div>
                <div class="example-symbol" onclick="setSymbol('NVDA')">NVDA</div>
                <div class="example-symbol" onclick="setSymbol('ADAUSDT')">ADAUSDT</div>
                <div class="example-symbol" onclick="setSymbol('DOGEUSDT')">DOGEUSDT</div>
            </div>
            <div style="color: var(--gray); font-size: 0.85rem; margin-top: 0.8rem;">
                <i class="fas fa-info-circle"></i> 
                İlk 10 coin (BTC, ETH, BNB, SOL, XRP, ADA, DOGE, AVAX, MATIC, DOT) + Tüm hisseler desteklenir.
                Binance API key GEREKSİZ - Tamamen public WebSocket.
            </div>
        </div>

        <!-- Dashboard -->
        <div class="dashboard">
            <!-- TradingView Chart -->
            <div class="card">
                <h2 class="card-title">
                    <i class="fas fa-chart-line"></i> TradingView Grafik
                </h2>
                <div class="symbol-badge" id="chartSymbolBadge">BTCUSDT - Binance WebSocket</div>
                <div class="tradingview-widget" id="tradingview_chart"></div>
                <div id="financeResult" class="result loading" style="margin-top: 1rem;">
                    <div class="spinner"></div> Veriler yükleniyor...
                </div>
                <div id="statsGrid" class="stats-grid" style="display: none;"></div>
            </div>

            <!-- AI & ML Panel -->
            <div class="card">
                <h2 class="card-title">
                    <i class="fas fa-robot"></i> Qwen AI Analisti
                </h2>
                <div class="symbol-badge" id="aiSymbolBadge">BTCUSDT</div>
                <textarea id="aiQuery" placeholder="Sorunuzu yazın (ör: Teknik analiz, trend, direnç seviyeleri)" 
                    style="width: 100%; padding: 0.8rem; border-radius: 10px; border: 2px solid var(--dark-700); 
                    background: var(--dark-800); color: white; font-size: 1rem; min-height: 120px; margin-bottom: 1rem; 
                    resize: vertical;"></textarea>
                <button id="askBtn" class="btn-ai" style="width: 100%;">
                    <i class="fas fa-paper-plane"></i> Qwen'e Sor
                </button>
                <div id="aiResult" class="result loading" style="margin-top: 1rem; min-height: 200px;">
                    <div class="spinner"></div> AI analizi bekleniyor...
                </div>
            </div>
        </div>

        <!-- ML Prediction Card -->
        <div class="card">
            <h2 class="card-title">
                <i class="fas fa-chart-bar"></i> Makine Öğrenmesi Tahmini
            </h2>
            <div class="symbol-badge" id="mlSymbolBadge">BTCUSDT - 5 Gün Tahmini</div>
            <div id="mlResult" class="result loading">
                <div class="spinner"></div> ML tahmini hesaplanıyor...
            </div>
        </div>
    </div>

    <footer>
        <div class="container">
            <p>
                © 2026 ICTSmartPro Trading AI | 
                <a href="https://ictsmartpro.ai" target="_blank">Website</a> | 
                <span style="color: var(--danger); margin-left: 10px;">
                    <i class="fas fa-exclamation-triangle"></i> Yatırım danışmanlığı değildir
                </span>
            </p>
            <p style="color: var(--gray); font-size: 0.8rem; margin-top: 0.5rem;">
                🔒 Güvenli: Binance API key kullanılmaz | 📡 Kaynak: Public Binance WebSocket + YFinance
            </p>
        </div>
    </footer>

    <!-- TradingView Widget Script -->
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <script>
        let currentSymbol = "BTCUSDT";
        let currentExchange = "binance_ws";
        let currentInterval = "1h";
        let tvWidget = null;

        // TradingView Widget Başlat
        function initTradingView(symbol, exchange, interval) {
            if (tvWidget) {
                tvWidget.remove();
                tvWidget = null;
            }

            let tvSymbol = symbol;
            if (exchange === "binance_ws") {
                tvSymbol = `BINANCE:${symbol.replace('USDT', 'USDT.P')}`;
            } else if (exchange === "yfinance_crypto") {
                tvSymbol = `BITSTAMP:${symbol.replace('-USD', 'USD')}`;
            } else { // yfinance_stock
                // Stock exchange detection
                const usStocks = ["TSLA", "AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "AMD", "INTC", "COIN"];
                tvSymbol = usStocks.includes(symbol.toUpperCase()) ? `NASDAQ:${symbol}` : `NYSE:${symbol}`;
            }

            const intervalMap = {
                "1m": "1", "5m": "5", "15m": "15", "30m": "30",
                "1h": "60", "4h": "240", "1d": "D", "1w": "W"
            };
            const tvInterval = intervalMap[interval] || "60";

            tvWidget = new TradingView.widget({
                width: "100%",
                height: "600",
                symbol: tvSymbol,
                interval: tvInterval,
                timezone: "Etc/UTC",
                theme: "dark",
                style: "1",
                locale: "tr",
                toolbar_bg: "#1e293b",
                enable_publishing: false,
                allow_symbol_change: true,
                container_id: "tradingview_chart",
                studies: [
                    "RSI@tv-basicstudies",
                    "MASimple@tv-basicstudies"
                ],
                overrides: {
                    "paneProperties.background": "#0f172a",
                    "paneProperties.vertGridProperties.color": "#1e293b",
                    "paneProperties.horzGridProperties.color": "#1e293b",
                    "symbolWatermarkProperties.color": "rgba(0, 0, 0, 0)",
                    "scalesProperties.textColor": "#e2e8f0",
                    "mainSeriesProperties.candleStyle.wickUpColor": "#10b981",
                    "mainSeriesProperties.candleStyle.wickDownColor": "#ef4444",
                    "mainSeriesProperties.candleStyle.upColor": "#10b981",
                    "mainSeriesProperties.candleStyle.downColor": "#ef4444",
                    "mainSeriesProperties.candleStyle.borderColor": "#1e293b"
                },
                drawings_access: { type: "black", tools: [ { name: "Regression Trend" } ] },
                debug: false
            });

            console.log(`TradingView başlatıldı: ${tvSymbol} @ ${tvInterval}`);
        }

        // Symbol Değiştir
        function setSymbol(symbol) {
            document.getElementById('symbolInput').value = symbol;
            analyzeStock();
        }

        // Hisse Analizi
        async function analyzeStock() {
            const symbol = document.getElementById('symbolInput').value.trim().toUpperCase();
            const timeframe = document.getElementById('timeframe').value;
            
            if (!symbol) {
                alert('Lütfen bir sembol girin!');
                return;
            }

            currentSymbol = symbol;
            currentInterval = timeframe;
            currentExchange = detectExchange(symbol);

            document.getElementById('chartSymbolBadge').textContent = `${symbol} - ${currentExchange === 'binance_ws' ? 'Binance WebSocket' : 'YFinance'}`;
            document.getElementById('aiSymbolBadge').textContent = symbol;
            document.getElementById('mlSymbolBadge').textContent = `${symbol} - 5 Gün Tahmini`;

            const resDiv = document.getElementById('financeResult');
            const statsGrid = document.getElementById('statsGrid');
            
            resDiv.className = 'result loading';
            resDiv.innerHTML = '<div class="spinner"></div> Veriler çekiliyor...';
            statsGrid.style.display = 'none';

            try {
                initTradingView(symbol, currentExchange, timeframe);

                const resp = await fetch(`/api/finance/${encodeURIComponent(symbol)}?timeframe=${timeframe}`);
                
                if (!resp.ok) {
                    const errorData = await resp.json().catch(() => ({}));
                    throw new Error(errorData.detail || `HTTP ${resp.status}`);
                }

                const data = await resp.json();

                if (data.error) {
                    throw new Error(data.error);
                }

                let html = `
                    <div style="font-size: 1.3rem; font-weight: 700; margin-bottom: 0.8rem; color: white;">
                        ${data.symbol} ${data.name ? `- ${data.name}` : ''}
                    </div>
                    <div style="font-size: 2rem; font-weight: 800; margin: 0.5rem 0; color: ${data.change_percent >= 0 ? '#10b981' : '#ef4444'};">
                        ${Number(data.current_price).toLocaleString('tr-TR', {maximumFractionDigits: 8})} ${data.currency || (currentExchange === 'binance_ws' ? 'USDT' : 'USD')}
                        <span style="font-size: 1.2rem; margin-left: 10px;">
                            ${data.change_percent >= 0 ? '↑' : '↓'} ${Math.abs(data.change_percent).toFixed(2)}%
                        </span>
                    </div>
                    <div style="color: var(--gray); margin-bottom: 1rem;">
                        Değişim: ${data.change >= 0 ? '+' : ''}${Number(data.change || 0).toFixed(2)} | 
                        Hacim: ${Number(data.volume || 0).toLocaleString('tr-TR')} | 
                        Exchange: ${data.exchange.toUpperCase()}
                    </div>
                `;

                if (data.market_cap) {
                    html += `<div style="color: var(--gray); font-size: 0.9rem;">
                        Piyasa Değeri: ${(data.market_cap / 1e9).toFixed(1)} Milyar USD
                    </div>`;
                }

                resDiv.className = 'result success';
                resDiv.innerHTML = html;

                statsGrid.innerHTML = `
                    <div class="stat-card">
                        <div class="stat-value">${Number(data.current_price).toLocaleString('tr-TR', {maximumFractionDigits: 2})}</div>
                        <div class="stat-label">Mevcut Fiyat</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" style="color: ${data.change_percent >= 0 ? 'var(--success)' : 'var(--danger)'}">
                            ${data.change_percent >= 0 ? '+' : ''}${data.change_percent.toFixed(2)}%
                        </div>
                        <div class="stat-label">Değişim</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${data.exchange.toUpperCase()}</div>
                        <div class="stat-label">Kaynak</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${timeframe.toUpperCase()}</div>
                        <div class="stat-label">Timeframe</div>
                    </div>
                `;
                statsGrid.style.display = 'grid';

            } catch (err) {
                resDiv.className = 'result error';
                resDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${err.message || 'Veri alınamadı'}`;
                console.error('Analyze error:', err);
            }
        }

        // ML Prediction
        async function getMLPrediction() {
            if (!currentSymbol) {
                alert('Lütfen önce bir sembol analiz edin!');
                return;
            }

            const mlDiv = document.getElementById('mlResult');
            mlDiv.className = 'result loading';
            mlDiv.innerHTML = '<div class="spinner"></div> ML tahmini hesaplanıyor...';

            try {
                const resp = await fetch(`/api/predict/${encodeURIComponent(currentSymbol)}?horizon=5`);
                
                if (!resp.ok) {
                    const errorData = await resp.json().catch(() => ({}));
                    throw new Error(errorData.detail || `HTTP ${resp.status}`);
                }

                const data = await resp.json();

                if (data.error) {
                    throw new Error(data.error);
                }

                let html = `
                    <div style="font-size: 1.2rem; font-weight: 700; margin-bottom: 1rem; color: white;">
                        🎯 5 Gün Sonrası ML Tahmini
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem;">
                        <div>
                            <div style="color: var(--gray); font-size: 0.9rem;">Tahmini Fiyat</div>
                            <div style="font-size: 1.6rem; font-weight: 800; color: ${data.direction_class === 'positive' ? 'var(--success)' : 'var(--danger)'};">
                                ${data.predicted_price} ${data.direction.includes('↑') ? '📈' : '📉'}
                            </div>
                        </div>
                        <div>
                            <div style="color: var(--gray); font-size: 0.9rem;">Mevcut Fiyat</div>
                            <div style="font-size: 1.6rem; font-weight: 800;">
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
                        <div style="display: flex; justify-content: space-between; margin-top: 0.5rem;">
                            <span style="color: var(--gray);">Kaynak:</span>
                            <span style="color: var(--info); font-weight: 600;">
                                ${data.exchange.toUpperCase()} (Public WebSocket)
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

            } catch (err) {
                mlDiv.className = 'result error';
                mlDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${err.message || 'ML hatası'}`;
                console.error('ML error:', err);
            }
        }

        // Ask AI
        async function askQwen() {
            if (!currentSymbol) {
                alert('Lütfen önce bir sembol analiz edin!');
                return;
            }

            const query = document.getElementById('aiQuery').value.trim();
            const aiDiv = document.getElementById('aiResult');
            
            if (query.length < 3) {
                aiDiv.className = 'result error';
                aiDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> Mesaj en az 3 karakter olmalı`;
                return;
            }

            aiDiv.className = 'result loading';
            aiDiv.innerHTML = '<div class="spinner"></div> Qwen analiz ediyor...';

            try {
                const resp = await fetch('/api/ai/ask', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: query, symbol: currentSymbol})
                });

                if (!resp.ok) {
                    const errorData = await resp.json().catch(() => ({}));
                    throw new Error(errorData.detail || `HTTP ${resp.status}`);
                }

                const data = await resp.json();
                aiDiv.className = 'result success';
                aiDiv.innerHTML = DOMPurify.sanitize(data.reply.replace(/\\n/g, '<br>'));

            } catch (err) {
                aiDiv.className = 'result error';
                aiDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${err.message || 'AI hatası'}`;
                console.error('AI error:', err);
            }
        }

        // Exchange Detection (Client-side)
        function detectExchange(symbol) {
            const sym = symbol.toUpperCase();
            if (sym.endsWith("USDT") && sym.length <= 12) {
                return "binance_ws";
            }
            if (/^[A-Z]{3,8}-USD$/.test(sym)) {
                return "yfinance_crypto";
            }
            return "yfinance_stock";
        }

        // Event Listeners
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

            document.getElementById('symbolInput').addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    analyzeStock();
                }
            });

            setTimeout(() => {
                analyzeStock();
                getMLPrediction();
            }, 500);
        });
    </script>
</body>
</html>
    """

@app.on_event("startup")
async def startup():
    logger.info("="*70)
    logger.info("🚀 ICTSmartPro Trading AI v8.0.0 - WebSocket Entegreli")
    logger.info("="*70)
    logger.info("✅ Public Binance WebSocket (Zero API Key)")
    logger.info("✅ İlk 10 Popüler Coin: BTC, ETH, BNB, SOL, XRP, ADA, DOGE, AVAX, MATIC, DOT")
    logger.info("✅ Tüm Hisse Senetleri (YFinance)")
    logger.info("✅ TradingView Widget Entegrasyonu")
    logger.info("✅ Gerçek Zamanlı Fiyat Güncelleme")
    logger.info("✅ ML Momentum Tahmini")
    logger.info("✅ Qwen AI Entegrasyonu")
    logger.info("-" * 70)
    logger.info(f"🔧 Port: {PORT}")
    logger.info(f"⏱️ Rate Limit: {RATE_LIMIT_PER_MINUTE}/dk")
    logger.info(f"🤖 OpenRouter: {'✓ Ayarlı' if OPENROUTER_API_KEY else '⚠️ Eksik (AI sınırlı)'}")
    logger.info(f"🔒 Güvenlik: Binance API key KULLANILMAZ")
    logger.info("="*70)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")
