"""
ICTSmartPro Trading AI - Zero API Dependency Edition
✅ Public WebSocket ✅ Rule-Based Akıllı Analiz ✅ Resim Yükleme
Version: 9.0.0
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import re
import json
import asyncio
import base64
import hashlib

from fastapi import FastAPI, HTTPException, Request, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel, Field, field_validator

import yfinance as yf
import pandas as pd
import numpy as np
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
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", 15))

# ==================== POPÜLER COINLER (Binance Public WebSocket) ====================
POPULAR_COINS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT", "DOTUSDT"
]

# ==================== RATE LIMITING ====================
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="ICTSmartPro Trading AI",
    description="Zero API Dependency Trading Platform",
    version="9.0.0",
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
    symbol_upper = symbol.upper().strip()
    if symbol_upper in POPULAR_COINS or (symbol_upper.endswith("USDT") and len(symbol_upper) <= 12):
        return "binance_ws"
    if re.match(r'^[A-Z]{3,8}-USD$', symbol_upper):
        return "yfinance_crypto"
    if re.match(r'^[A-Z]{2,6}$', symbol_upper) and len(symbol_upper) <= 6:
        return "yfinance_stock"
    return "yfinance_stock"

# ==================== BINANCE WEBSOCKET MANAGER ====================
class BinanceWebSocketManager:
    def __init__(self):
        self.ws_url = "wss://stream.binance.com:9443/stream"
        logger.info("✅ Binance WebSocket Manager (Public API - Zero Key)")
    
    async def get_latest_price(self, symbol: str) -> Dict:
        symbol_lower = symbol.lower()
        stream_name = f"{symbol_lower}@ticker"
        
        try:
            async with websockets.connect(self.ws_url, timeout=5) as websocket:
                await websocket.send(json.dumps({
                    "method": "SUBSCRIBE",
                    "params": [stream_name],
                    "id": 1
                }))
                await asyncio.wait_for(websocket.recv(), timeout=3.0)
                message = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                data = json.loads(message)
                
                if 'e' in data and data['e'] == '24hrTicker':
                    return {
                        "symbol": symbol.upper(),
                        "current_price": float(data['c']),
                        "change_percent": float(data['P']),
                        "volume": float(data['v']),
                        "high_24h": float(data['h']),
                        "low_24h": float(data['l']),
                        "exchange": "binance_ws",
                        "error": None
                    }
                return {"error": "Geçersiz yanıt", "exchange": "binance_ws"}
        except Exception as e:
            return {"error": "WebSocket hatası", "exchange": "binance_ws"}

binance_ws_manager = BinanceWebSocketManager()

# ==================== YFINANCE MANAGER ====================
async def get_yfinance_data(symbol: str, period: str = "1mo", is_crypto: bool = False) -> Dict:
    try:
        if is_crypto and not symbol.endswith("-USD"):
            symbol = f"{symbol}-USD"
        
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        
        if hist.empty:
            alt_symbols = [symbol + ".IS", symbol.replace("-USD", "USD=X")]
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
        change_pct = ((current - previous) / previous * 100) if previous != 0 else 0

        info = ticker.info
        name = info.get("longName") or info.get("shortName") or symbol
        currency = info.get("currency", "USD")

        return {
            "symbol": symbol,
            "name": name,
            "currency": currency,
            "current_price": round(current, 2),
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
        return {"error": str(e), "exchange": "yfinance"}

# ==================== RULE-BASED "AKILLI ANALİZ" (AI YERİNE) ====================
def generate_smart_analysis(symbol: str, exchange: str, current_price: float, change_percent: float, 
                          volume: float, historical_prices: list) -> str:
    """
    Gerçek AI olmadan rule-based akıllı analiz
    """
    analysis = []
    analysis.append(f"📊 <strong>{symbol} Analizi</strong>")
    analysis.append(f"Fiyat: ${current_price:,.2f} ({'↑' if change_percent >= 0 else '↓'} {abs(change_percent):.2f}%)")
    analysis.append("")
    
    # Trend analizi
    if len(historical_prices) >= 20:
        recent = historical_prices[-5:]
        avg_recent = sum(recent) / len(recent)
        avg_20 = sum(historical_prices[-20:]) / 20
        
        if avg_recent > avg_20:
            analysis.append("📈 <strong>Trend:</strong> Yükseliş eğilimi (Son 5 gün > 20 günlük ortalama)")
        else:
            analysis.append("📉 <strong>Trend:</strong> Düşüş eğilimi (Son 5 gün < 20 günlük ortalama)")
    
    # Volatility analizi
    if len(historical_prices) >= 10:
        volatility = (max(historical_prices[-10:]) - min(historical_prices[-10:])) / min(historical_prices[-10:]) * 100
        if volatility > 5:
            analysis.append(f"⚠️ <strong>Oynaklık:</strong> Yüksek (%{volatility:.1f} son 10 günde)")
        else:
            analysis.append(f"✅ <strong>Oynaklık:</strong> Düşük (%{volatility:.1f} son 10 günde)")
    
    # Volume analizi
    if volume > 0:
        avg_volume = sum(historical_prices[-10:]) / 10 if len(historical_prices) >= 10 else volume
        if volume > avg_volume * 1.5:
            analysis.append("🔊 <strong>Hacim:</strong> Anormal yüksek hacim (Trend onayı olabilir)")
        elif volume < avg_volume * 0.5:
            analysis.append("🔉 <strong>Hacim:</strong> Düşük hacim (Trend zayıf olabilir)")
    
    # RSI benzeri analiz (basit momentum)
    if len(historical_prices) >= 14:
        gains = sum(max(0, historical_prices[i] - historical_prices[i-1]) for i in range(-14, 0))
        losses = sum(max(0, historical_prices[i-1] - historical_prices[i]) for i in range(-14, 0))
        if losses > 0:
            rs = gains / losses
            rsi = 100 - (100 / (1 + rs))
            if rsi > 70:
                analysis.append("⚠️ <strong>Momentum:</strong> Aşırı alım bölgesi (RSI ~70+)")
            elif rsi < 30:
                analysis.append("✅ <strong>Momentum:</strong> Aşırı satım bölgesi (RSI ~30-)")
    
    analysis.append("")
    analysis.append("<em>💡 Not: Bu analiz rule-based sistem tarafından üretilmiştir.</em>")
    analysis.append("<em>⚠️ Yatırım tavsiyesi değildir, sadece bilgilendirme amaçlıdır.</em>")
    
    return "<br>".join(analysis)

# ==================== ML PREDICTION (Simple Momentum) ====================
class MLModelManager:
    async def predict_price(self, symbol: str, exchange: str, horizon: int = 5) -> Dict:
        try:
            if exchange == "binance_ws":
                symbol_yf = symbol.replace("USDT", "-USD")
                data = await get_yfinance_data(symbol_yf, period="3mo", is_crypto=True)
            elif exchange == "yfinance_crypto":
                data = await get_yfinance_data(symbol, period="3mo", is_crypto=True)
            else:
                data = await get_yfinance_data(symbol, period="3mo", is_crypto=False)
            
            if data.get("error") or not data.get("historical_data", {}).get("prices"):
                return {"error": "Yeterli veri yok"}
            
            prices = data["historical_data"]["prices"]
            if len(prices) < 10:
                return {"error": "Tahmin için yeterli veri yok"}
            
            recent_trend = (prices[-1] - prices[-10]) / 10
            current_price = prices[-1]
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
                "note": "Momentum tahmini - yatırım tavsiyesi değildir",
                "method": "Simple Momentum Analysis"
            }
        except Exception as e:
            return {"error": f"Tahmin hatası: {str(e)[:50]}"}

ml_manager = MLModelManager()

# ==================== IMAGE UPLOAD (Client-Side Base64) ====================
@app.post("/api/upload-image")
@limiter.limit("5/minute")
async def upload_image(request: Request, file: UploadFile = File(...)):
    """
    Resim yükleme (client-side base64 dönüşümü için endpoint)
    """
    try:
        if not file.content_type.startswith("image/"):
            raise HTTPException(400, "Sadece resim dosyaları kabul edilir")
        
        contents = await file.read()
        if len(contents) > 5 * 1024 * 1024:  # 5MB limit
            raise HTTPException(400, "Dosya 5MB'dan büyük olamaz")
        
        # Base64'e çevir (client-side gösterim için)
        base64_str = base64.b64encode(contents).decode('utf-8')
        file_hash = hashlib.md5(contents).hexdigest()[:8]
        
        return {
            "success": True,
            "filename": file.filename,
            "hash": file_hash,
            "base64_preview": f"data:{file.content_type};base64,{base64_str[:100]}...",  # Preview için kısalt
            "message": "Resim başarıyla yüklendi. İnceleme panelinde görüntüleyebilirsiniz."
        }
    except Exception as e:
        logger.error(f"Image upload error: {str(e)}")
        raise HTTPException(500, f"Yükleme hatası: {str(e)}")

# ==================== HEALTHCHECK ====================
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "9.0.0",
        "timestamp": datetime.now().isoformat(),
        "websocket_ready": True,
        "ai_mode": "rule-based (zero api)",
        "ml_ready": True
    }

@app.get("/ready")
async def ready_check():
    return {"ready": True}

# ==================== API ENDPOINTS ====================
@app.get("/api/symbols")
async def get_symbols():
    return {
        "popular_coins": POPULAR_COINS,
        "example_stocks": ["TSLA", "AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "AMD", "INTC", "COIN"],
        "example_crypto": ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"]
    }

@app.get("/api/finance/{symbol}")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def api_finance(request: Request, symbol: str, timeframe: str = "1h"):
    try:
        exchange = detect_exchange(symbol)
        cache_key = f"finance_{symbol}_{timeframe}_{exchange}"
        
        if exchange == "binance_ws":
            result = await binance_ws_manager.get_latest_price(symbol)
            if not result.get("error"):
                symbol_yf = symbol.replace("USDT", "-USD")
                yf_data = await get_yfinance_data(symbol_yf, period="1mo", is_crypto=True)
                if not yf_data.get("error"):
                    result["name"] = yf_data.get("name", symbol)
                    result["currency"] = "USDT"
                    result["historical_data"] = yf_data.get("historical_data", {})
        elif exchange == "yfinance_crypto":
            period_map = {"1d": "1mo", "1w": "3mo", "1h": "5d", "4h": "10d"}
            result = await get_yfinance_data(symbol, period=period_map.get(timeframe, "1mo"), is_crypto=True)
        else:
            period_map = {"1d": "1mo", "1w": "3mo", "1h": "5d", "4h": "10d"}
            result = await get_yfinance_data(symbol, period=period_map.get(timeframe, "1mo"), is_crypto=False)
        
        if result.get("error"):
            raise HTTPException(404, f"Veri alınamadı: {result['error']}")
        
        result["exchange"] = exchange
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Finance API error: {str(e)}")
        raise HTTPException(500, f"Veri hatası: {str(e)}")

@app.get("/api/predict/{symbol}")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def api_predict(request: Request, symbol: str, horizon: int = 5):
    try:
        exchange = detect_exchange(symbol)
        result = await ml_manager.predict_price(symbol, exchange, horizon)
        if result.get("error"):
            raise HTTPException(400, result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Prediction API error: {str(e)}")
        raise HTTPException(500, f"Tahmin hatası: {str(e)}")

@app.get("/api/smart-analysis/{symbol}")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def api_smart_analysis(request: Request, symbol: str):
    """
    Rule-based akıllı analiz (Zero API)
    """
    try:
        exchange = detect_exchange(symbol)
        
        # Veri çek
        if exchange == "binance_ws":
            ws_data = await binance_ws_manager.get_latest_price(symbol)
            if ws_data.get("error"):
                raise HTTPException(404, ws_data["error"])
            
            symbol_yf = symbol.replace("USDT", "-USD")
            yf_data = await get_yfinance_data(symbol_yf, period="1mo", is_crypto=True)
            if yf_data.get("error"):
                raise HTTPException(404, yf_data["error"])
            
            prices = yf_data["historical_data"]["prices"]
            analysis = generate_smart_analysis(
                symbol, exchange, 
                ws_data["current_price"], 
                ws_data["change_percent"],
                ws_data["volume"],
                prices
            )
        else:
            period_map = {"1d": "1mo", "1w": "3mo"}
            yf_data = await get_yfinance_data(symbol, period="1mo", is_crypto=(exchange == "yfinance_crypto"))
            if yf_data.get("error"):
                raise HTTPException(404, yf_data["error"])
            
            prices = yf_data["historical_data"]["prices"]
            analysis = generate_smart_analysis(
                symbol, exchange,
                yf_data["current_price"],
                yf_data["change_percent"],
                yf_data["volume"],
                prices
            )
        
        return {
            "symbol": symbol,
            "exchange": exchange,
            "analysis_html": analysis,
            "analysis_type": "rule-based",
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Smart analysis error: {str(e)}")
        return {
            "symbol": symbol,
            "analysis_html": f"<div class='error'>❌ Analiz oluşturulamadı: {str(e)[:100]}</div>",
            "analysis_type": "rule-based",
            "timestamp": datetime.now().isoformat()
        }

# ==================== MAIN FRONTEND (Zero API • TradingView) ====================
@app.get("/", response_class=HTMLResponse)
async def home():
    return """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="ICTSmartPro - Zero API Dependency Trading Platform">
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

        .badges {
            display: flex;
            justify-content: center;
            gap: 0.8rem;
            margin-top: 1rem;
            flex-wrap: wrap;
        }

        .badge {
            background: rgba(255, 255, 255, 0.15);
            padding: 0.3rem 0.8rem;
            border-radius: 20px;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .badge.zero-api { background: rgba(16, 185, 129, 0.2); color: var(--success); }
        .badge.websocket { background: rgba(99, 102, 241, 0.2); color: var(--primary); }
        .badge.ml { background: rgba(139, 92, 246, 0.2); color: var(--secondary); }

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

        .btn-analysis {
            background: linear-gradient(90deg, var(--success), #14b8a6);
        }

        .btn-image {
            background: linear-gradient(90deg, #f59e0b, #f97316);
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
            margin-top: 1rem;
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

        .ai-badge {
            display: inline-block;
            background: rgba(16, 185, 129, 0.15);
            color: var(--success);
            padding: 0.2rem 0.6rem;
            border-radius: 12px;
            font-size: 0.8rem;
            margin-left: 0.5rem;
        }

        .image-preview {
            max-width: 100%;
            max-height: 300px;
            border-radius: 8px;
            margin-top: 1rem;
            display: none;
        }

        .upload-area {
            border: 2px dashed var(--dark-700);
            border-radius: 10px;
            padding: 1.5rem;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s;
            margin-top: 1rem;
        }

        .upload-area:hover {
            border-color: var(--primary);
            background: rgba(99, 102, 241, 0.05);
        }

        .upload-area i {
            font-size: 2rem;
            color: var(--gray);
            margin-bottom: 0.5rem;
        }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <div class="logo">
                <i class="fas fa-rocket"></i> ICTSmartPro AI
            </div>
            <div class="tagline">Zero API Dependency • Public WebSocket • Rule-Based Analysis</div>
            <div class="badges">
                <div class="badge zero-api"><i class="fas fa-shield-alt"></i> Zero API Key</div>
                <div class="badge websocket"><i class="fas fa-plug"></i> Public WebSocket</div>
                <div class="badge ml"><i class="fas fa-brain"></i> ML Tahmin</div>
                <div class="badge zero-api"><i class="fas fa-robot"></i> Rule-Based Analiz</div>
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
                    <i class="fas fa-chart-line"></i> ML Tahmin
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
            </div>
            <div style="color: var(--gray); font-size: 0.85rem; margin-top: 0.8rem;">
                <i class="fas fa-info-circle"></i> 
                Tüm coinler ve hisseler için anlık veri. Binance API key GEREKSİZ. Tamamen ücretsiz.
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
                <div id="financeResult" class="result loading">
                    <div class="spinner"></div> Veriler yükleniyor...
                </div>
                <div id="statsGrid" class="stats-grid" style="display: none;"></div>
            </div>

            <!-- Smart Analysis Panel -->
            <div class="card">
                <h2 class="card-title">
                    <i class="fas fa-brain"></i> Akıllı Analiz <span class="ai-badge">Rule-Based</span>
                </h2>
                <div class="symbol-badge" id="analysisSymbolBadge">BTCUSDT</div>
                <button id="smartAnalysisBtn" class="btn-analysis" style="width: 100%; margin-top: 0.5rem;">
                    <i class="fas fa-lightbulb"></i> Akıllı Analiz Oluştur
                </button>
                <div id="analysisResult" class="result loading" style="margin-top: 1rem; min-height: 250px;">
                    <div class="spinner"></div> Analiz hazırlanıyor...
                </div>
                
                <div style="margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid rgba(255,255,255,0.05);">
                    <h3 style="font-size: 1.1rem; margin-bottom: 0.8rem; display: flex; align-items: center; gap: 0.5rem;">
                        <i class="fas fa-image"></i> Kendi Analiz Resmini Yükle
                    </h3>
                    <div class="upload-area" id="uploadArea">
                        <i class="fas fa-cloud-upload-alt"></i>
                        <div style="margin-top: 0.5rem; font-size: 0.9rem; color: var(--gray);">
                            TradingView/MT4 ekran görüntünüzü buraya sürükleyin veya tıklayın
                        </div>
                        <input type="file" id="imageUpload" accept="image/*" style="display: none;">
                    </div>
                    <img id="imagePreview" class="image-preview" src="" alt="Yüklenen analiz">
                </div>
            </div>
        </div>

        <!-- ML Prediction Card -->
        <div class="card">
            <h2 class="card-title">
                <i class="fas fa-robot"></i> Makine Öğrenmesi Tahmini
            </h2>
            <div class="symbol-badge" id="mlSymbolBadge">BTCUSDT - 5 Gün Tahmini</div>
            <div id="mlResult" class="result loading">
                <div class="spinner"></div> ML tahmini hesaplanıyor...
            </div>
            <div style="color: var(--gray); font-size: 0.85rem; margin-top: 1rem; font-style: italic;">
                <i class="fas fa-info-circle"></i> Tahminler momentum analizine dayanır. Yatırım tavsiyesi değildir.
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
                🔒 Güvenli: Zero API Key • 💡 Akıllı Analiz: Rule-Based (Zero Cost) • 📡 Veri: Public WebSocket + YFinance
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
            } else {
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
                studies: ["RSI@tv-basicstudies", "MASimple@tv-basicstudies"],
                overrides: {
                    "paneProperties.background": "#0f172a",
                    "paneProperties.vertGridProperties.color": "#1e293b",
                    "paneProperties.horzGridProperties.color": "#1e293b",
                    "symbolWatermarkProperties.color": "rgba(0, 0, 0, 0)",
                    "scalesProperties.textColor": "#e2e8f0",
                    "mainSeriesProperties.candleStyle.wickUpColor": "#10b981",
                    "mainSeriesProperties.candleStyle.wickDownColor": "#ef4444",
                    "mainSeriesProperties.candleStyle.upColor": "#10b981",
                    "mainSeriesProperties.candleStyle.downColor": "#ef4444"
                },
                drawings_access: { type: "black", tools: [ { name: "Regression Trend" } ] },
                debug: false
            });
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
            document.getElementById('analysisSymbolBadge').textContent = symbol;
            document.getElementById('mlSymbolBadge').textContent = `${symbol} - 5 Gün Tahmini`;

            const resDiv = document.getElementById('financeResult');
            const statsGrid = document.getElementById('statsGrid');
            
            resDiv.className = 'result loading';
            resDiv.innerHTML = '<div class="spinner"></div> Veriler çekiliyor...';
            statsGrid.style.display = 'none';

            try {
                initTradingView(symbol, currentExchange, timeframe);

                const resp = await fetch(`/api/finance/${encodeURIComponent(symbol)}?timeframe=${timeframe}`);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();
                if (data.error) throw new Error(data.error);

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
                        Hacim: ${Number(data.volume || 0).toLocaleString('tr-TR')} | 
                        Kaynak: ${data.exchange.toUpperCase()}
                    </div>
                `;

                resDiv.className = 'result success';
                resDiv.innerHTML = html;

                statsGrid.innerHTML = `
                    <div class="stat-card">
                        <div class="stat-value">${Number(data.current_price).toLocaleString('tr-TR', {maximumFractionDigits: 2})}</div>
                        <div class="stat-label">Fiyat</div>
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
                        <div class="stat-label">Periyot</div>
                    </div>
                `;
                statsGrid.style.display = 'grid';

            } catch (err) {
                resDiv.className = 'result error';
                resDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${err.message || 'Veri alınamadı'}`;
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
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();
                if (data.error) throw new Error(data.error);

                let html = `
                    <div style="font-size: 1.2rem; font-weight: 700; margin-bottom: 1rem; color: white;">
                        🎯 5 Gün Sonrası Tahmin
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
                            <span style="color: var(--gray);">Güven:</span>
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

            } catch (err) {
                mlDiv.className = 'result error';
                mlDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${err.message || 'ML hatası'}`;
            }
        }

        // Smart Analysis (Rule-Based - Zero API)
        async function generateSmartAnalysis() {
            if (!currentSymbol) {
                alert('Lütfen önce bir sembol analiz edin!');
                return;
            }

            const analysisDiv = document.getElementById('analysisResult');
            analysisDiv.className = 'result loading';
            analysisDiv.innerHTML = '<div class="spinner"></div> Akıllı analiz hazırlanıyor...';

            try {
                const resp = await fetch(`/api/smart-analysis/${encodeURIComponent(currentSymbol)}`);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();

                analysisDiv.className = 'result success';
                analysisDiv.innerHTML = DOMPurify.sanitize(data.analysis_html);

            } catch (err) {
                analysisDiv.className = 'result error';
                analysisDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${err.message || 'Analiz hatası'}`;
            }
        }

        // Image Upload
        document.getElementById('uploadArea').addEventListener('click', () => {
            document.getElementById('imageUpload').click();
        });

        document.getElementById('imageUpload').addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (!file || !file.type.startsWith('image/')) {
                alert('Lütfen geçerli bir resim dosyası seçin!');
                return;
            }

            if (file.size > 5 * 1024 * 1024) {
                alert('Dosya 5MB\'dan büyük olamaz!');
                return;
            }

            const reader = new FileReader();
            reader.onload = (event) => {
                const preview = document.getElementById('imagePreview');
                preview.src = event.target.result;
                preview.style.display = 'block';
                
                // Optional: Sunucuya yükleme
                const formData = new FormData();
                formData.append('file', file);
                
                fetch('/api/upload-image', {
                    method: 'POST',
                    body: formData
                })
                .then(resp => resp.json())
                .then(data => {
                    if (data.success) {
                        alert(`✅ Resim yüklendi!\nHash: ${data.hash}\nİnceleme panelinde görüntüleyebilirsiniz.`);
                    }
                })
                .catch(err => {
                    console.error('Upload error:', err);
                    // Yine de preview göster (client-side)
                });
            };
            reader.readAsDataURL(file);
        });

        // Exchange Detection
        function detectExchange(symbol) {
            const sym = symbol.toUpperCase();
            if (sym.endsWith("USDT") && sym.length <= 12) return "binance_ws";
            if (/^[A-Z]{3,8}-USD$/.test(sym)) return "yfinance_crypto";
            return "yfinance_stock";
        }

        // Event Listeners
        document.addEventListener('DOMContentLoaded', () => {
            document.getElementById('analyzeBtn').addEventListener('click', analyzeStock);
            document.getElementById('predictBtn').addEventListener('click', getMLPrediction);
            document.getElementById('smartAnalysisBtn').addEventListener('click', generateSmartAnalysis);
            
            document.getElementById('symbolInput').addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    analyzeStock();
                }
            });

            // Başlangıç analizi
            setTimeout(() => {
                analyzeStock();
                getMLPrediction();
                generateSmartAnalysis();
            }, 500);
        });
    </script>
</body>
</html>
    """

@app.on_event("startup")
async def startup():
    logger.info("="*70)
    logger.info("🚀 ICTSmartPro Trading AI v9.0.0 - Zero API Dependency")
    logger.info("="*70)
    logger.info("✅ Public Binance WebSocket (Zero API Key)")
    logger.info("✅ TradingView Entegrasyonu")
    logger.info("✅ ML Momentum Tahmini")
    logger.info("✅ Rule-Based Akıllı Analiz (Zero Cost • Zero API)")
    logger.info("✅ Resim Yükleme Desteği")
    logger.info("✅ İlk 10 Coin + Tüm Hisse Senetleri")
    logger.info("-" * 70)
    logger.info(f"🔧 Port: {PORT}")
    logger.info(f"⏱️ Rate Limit: {RATE_LIMIT_PER_MINUTE}/dk")
    logger.info(f"🔒 Güvenlik: Hiçbir API key kullanılmaz")
    logger.info(f"💰 Maliyet: SIFIR (Public kaynaklar)")
    logger.info("="*70)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")
