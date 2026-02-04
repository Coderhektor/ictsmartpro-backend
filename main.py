"""
🚀 PROFESSIONAL TRADING BOT v2.0.0 - ADVANCED ANALYSIS
✅ TradingView Integration ✅ EMA Crossovers ✅ RSI ✅ Heikin Ashi
✅ 12 Candlestick Patterns ✅ ICT Market Structure ✅ Multi-Timeframe
✅ High-Confidence Signals ✅ Real-time Data ✅ Risk Management
"""

import os
import logging
from datetime import datetime, timedelta
import random
import json
import asyncio
from typing import Dict, List, Optional, Tuple
import aiohttp
from enum import Enum

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

# FastAPI Application
app = FastAPI(
    title="Professional Trading Bot",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== SIGNAL TYPES ==========
class SignalType(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"

class SignalConfidence(str, Enum):
    VERY_HIGH = "VERY_HIGH"  # 85%+
    HIGH = "HIGH"            # 70-85%
    MEDIUM = "MEDIUM"        # 55-70%
    LOW = "LOW"              # <55%

# ========== HEALTH ENDPOINTS ==========
@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Professional Trading Bot</title>
        <meta http-equiv="refresh" content="0;url=/dashboard">
    </head>
    <body><p>Loading Trading Dashboard...</p></body>
    </html>
    """

@app.get("/health")
def health():
    return {"status": "healthy", "version": "2.0.0"}

@app.get("/ready")
async def ready_check():
    return PlainTextResponse("READY")

@app.get("/live")
async def liveness_probe():
    return {"status": "alive", "timestamp": datetime.utcnow().isoformat()}

# ========== YAPAY ZEKA BAĞLANTISI  ==========
# main.py dosyasına ekleyin
from fastapi import BackgroundTasks, UploadFile, File
from fastapi.responses import JSONResponse
import base64

# AI modülünü içe aktar
try:
    from ai_integration import ai_service
    AI_ENABLED = True
    logger.info("✅ AI module loaded successfully")
except ImportError as e:
    AI_ENABLED = False
    logger.warning(f"⚠️ AI module not available: {e}")
    # Sahte servis sınıfı
    class DummyAIService:
        async def initialize(self): return False
        async def get_quick_prediction(self, *args, **kwargs): 
            return {"error": "AI module not available"}
        async def get_comprehensive_analysis(self, *args, **kwargs):
            return {"error": "AI module not available"}
        async def chat_with_ai(self, *args, **kwargs):
            return {"error": "AI module not available"}
    
    ai_service = DummyAIService()

# ========== AI ENDPOINT'LERİ ==========
@app.get("/api/ai/status")
async def ai_status():
    """AI servis durumu"""
    return {
        "ai_enabled": AI_ENABLED,
        "initialized": ai_service.initialized if AI_ENABLED else False,
        "status": "ready" if AI_ENABLED and ai_service.initialized else "disabled"
    }

@app.post("/api/ai/initialize")
async def initialize_ai(background_tasks: BackgroundTasks):
    """AI servisini başlat"""
    if not AI_ENABLED:
        raise HTTPException(status_code=501, detail="AI module not available")
    
    async def init_ai():
        await ai_service.initialize()
    
    background_tasks.add_task(init_ai)
    
    return {
        "success": True,
        "message": "AI service initialization started",
        "status": "initializing"
    }

@app.get("/api/ai/predict/{symbol}")
async def ai_predict(
    symbol: str,
    detailed: bool = Query(default=False)
):
    """AI tahmini"""
    if not AI_ENABLED:
        raise HTTPException(status_code=501, detail="AI module not available")
    
    try:
        if not ai_service.initialized:
            await ai_service.initialize()
        
        if detailed:
            result = await ai_service.get_comprehensive_analysis(symbol)
        else:
            result = await ai_service.get_quick_prediction(symbol)
        
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/chat")
async def ai_chat(body: Dict):
    """AI chatbot"""
    if not AI_ENABLED:
        raise HTTPException(status_code=501, detail="AI module not available")
    
    try:
        message = body.get("message", "")
        symbol = body.get("symbol", None)
        
        result = await ai_service.chat_with_ai(message, symbol)
        
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/analyze-image")
async def ai_analyze_image(file: UploadFile = File(...)):
    """Trading grafiği analiz et"""
    if not AI_ENABLED:
        raise HTTPException(status_code=501, detail="AI module not available")
    
    try:
        image_bytes = await file.read()
        result = await ai_service.analyze_trading_image(image_bytes)
        
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========== KOMBİNE ANALİZ ENDPOINT'İ ==========
@app.get("/api/advanced/analyze/{symbol}")
async def advanced_analysis(
    symbol: str,
    include_ai: bool = Query(default=True),
    interval: str = Query(default="1h")
):
    """Gelişmiş analiz (Geleneksel + AI)"""
    try:
        # 1. Geleneksel analiz
        traditional = await analyze_symbol(symbol, interval)
        
        # 2. AI analizi
        ai_analysis = None
        if include_ai and AI_ENABLED:
            try:
                if not ai_service.initialized:
                    asyncio.create_task(ai_service.initialize())
                
                ai_analysis = await ai_service.get_comprehensive_analysis(symbol)
                
                # AI analizi başarısız olduysa
                if "error" in ai_analysis:
                    ai_analysis = None
            except Exception as ai_error:
                logger.warning(f"AI analysis skipped: {ai_error}")
                ai_analysis = None
        
        # 3. Birleştirilmiş sinyal
        combined_signal = await _combine_analysis(traditional, ai_analysis)
        
        return {
            "success": True,
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "traditional_analysis": traditional,
            "ai_analysis": ai_analysis,
            "combined_signal": combined_signal,
            "final_recommendation": await _generate_final_recommendation(combined_signal, traditional, ai_analysis)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def _combine_analysis(traditional: Dict, ai: Optional[Dict] = None) -> Dict:
    """Analizleri birleştir"""
    trad_signal = traditional.get("signal", {}).get("signal", "NEUTRAL")
    trad_conf = traditional.get("signal", {}).get("confidence", 50)
    
    if not ai:
        return {
            "signal": trad_signal,
            "confidence": trad_conf,
            "source": "traditional_only",
            "alignment": "single_source"
        }
    
    ai_signal = ai.get("final_signal", "Hold")
    ai_conf = ai.get("final_confidence", 0.5) * 100
    
    # Sinyal eşleştirme
    signal_map = {
        "STRONG_BUY": "Buy", "BUY": "Buy",
        "STRONG_SELL": "Sell", "SELL": "Sell",
        "NEUTRAL": "Hold"
    }
    
    trad_mapped = signal_map.get(trad_signal, "Hold")
    
    # Uyum kontrolü
    if trad_mapped == ai_signal:
        combined_conf = (trad_conf + ai_conf) / 2
        return {
            "signal": trad_signal if trad_conf >= 70 else ai_signal.upper(),
            "confidence": combined_conf,
            "source": "both_aligned",
            "alignment": "perfect",
            "description": f"✅ Both methods agree on {ai_signal.upper()}"
        }
    else:
        # Çatışma durumu - yüksek güvenilirliği seç
        if trad_conf > ai_conf:
            return {
                "signal": trad_signal,
                "confidence": trad_conf,
                "source": "traditional_preferred",
                "alignment": "conflict",
                "description": f"⚠️ Conflict: Traditional ({trad_signal}) chosen over AI ({ai_signal})"
            }
        else:
            return {
                "signal": ai_signal.upper(),
                "confidence": ai_conf,
                "source": "ai_preferred",
                "alignment": "conflict",
                "description": f"⚠️ Conflict: AI ({ai_signal}) chosen over Traditional ({trad_signal})"
            }

async def _generate_final_recommendation(combined: Dict, trad: Dict, ai: Optional[Dict] = None) -> str:
    """Nihai öneriyi oluştur"""
    signal = combined["signal"]
    confidence = combined["confidence"]
    
    base_recommendations = {
        "STRONG_BUY": "🚀 **STRONG BUY** - High conviction signal",
        "BUY": "✅ **BUY** - Bullish setup detected",
        "NEUTRAL": "⏸️ **NEUTRAL** - Wait for confirmation",
        "SELL": "📉 **SELL** - Consider reducing exposure",
        "STRONG_SELL": "🔴 **STRONG SELL** - Strong bearish signals"
    }
    
    recommendation = base_recommendations.get(signal, "No clear recommendation")
    
    # Güven seviyesi ekle
    if confidence >= 80:
        recommendation += f"\n📈 **Confidence**: Very High ({confidence:.1f}%)"
    elif confidence >= 70:HBO

# ========== PRICE DATA MODULE ==========
class PriceFetcher:
    """Price fetcher with REAL Binance data only - NO SIMULATION"""
    
    @staticmethod
    async def fetch_binance_klines(symbol: str, interval: str = "1h", limit: int = 100) -> Optional[List[Dict]]:
        """Fetch REAL candlestick data from Binance API"""
        try:
            # Validate symbol format
            sym = symbol.upper().strip()
            if not sym.endswith("USDT"):
                sym = f"{sym}USDT"
            
            async with aiohttp.ClientSession() as session:
                url = "https://api.binance.com/api/v3/klines"
                params = {
                    "symbol": sym,
                    "interval": interval,
                    "limit": min(limit, 1000)  # Binance max limit
                }
                
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        if not data:
                            return None
                        
                        candles = []
                        for candle in data:
                            candles.append({
                                "timestamp": candle[0],
                                "open": float(candle[1]),
                                "high": float(candle[2]),
                                "low": float(candle[3]),
                                "close": float(candle[4]),
                                "volume": float(candle[5])
                            })
                        logger.info(f"✅ Fetched {len(candles)} real candles for {sym}")
                        return candles
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Binance API error {response.status}: {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error(f"⚠️ Timeout fetching data for {symbol}")
            return None
        except Exception as e:
            logger.error(f"❌ Error fetching Binance data: {e}")
            return None
    
    @staticmethod
    async def get_candles(symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
        """Get ONLY real candlestick data - throws error if no data"""
        real_data = await PriceFetcher.fetch_binance_klines(symbol, interval, limit)
        
        if not real_data or len(real_data) < 20:
            logger.error(f"❌ INSUFFICIENT REAL DATA for {symbol}")
            return []  # Empty list for error handling
        
        return real_data

# ========== TECHNICAL INDICATORS ==========
class TechnicalIndicators:
    """Calculate technical indicators"""
    
    @staticmethod
    def calculate_ema(candles: List[Dict], period: int) -> List[float]:
        """Calculate Exponential Moving Average"""
        closes = [c["close"] for c in candles]
        ema = []
        multiplier = 2 / (period + 1)
        
        # First EMA is SMA
        sma = sum(closes[:period]) / period
        ema.append(sma)
        
        # Calculate EMA for rest
        for i in range(period, len(closes)):
            ema_value = (closes[i] - ema[-1]) * multiplier + ema[-1]
            ema.append(ema_value)
        
        # Pad with None for initial values
        return [None] * (period - 1) + ema
    
    @staticmethod
    def calculate_rsi(candles: List[Dict], period: int = 14) -> List[float]:
        """Calculate Relative Strength Index"""
        closes = [c["close"] for c in candles]
        rsi_values = [None] * period
        
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        
        if len(gains) < period:
            return rsi_values
        
        # First RSI
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        for i in range(period, len(gains)):
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            
            rsi_values.append(rsi)
            
            # Smooth averages
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        return rsi_values
    
    @staticmethod
    def convert_to_heikin_ashi(candles: List[Dict]) -> List[Dict]:
        """Convert regular candles to Heikin Ashi"""
        ha_candles = []
        
        for i, candle in enumerate(candles):
            if i == 0:
                # First HA candle
                ha_close = (candle["open"] + candle["high"] + candle["low"] + candle["close"]) / 4
                ha_open = (candle["open"] + candle["close"]) / 2
                ha_high = candle["high"]
                ha_low = candle["low"]
            else:
                prev_ha = ha_candles[-1]
                ha_close = (candle["open"] + candle["high"] + candle["low"] + candle["close"]) / 4
                ha_open = (prev_ha["open"] + prev_ha["close"]) / 2
                ha_high = max(candle["high"], ha_open, ha_close)
                ha_low = min(candle["low"], ha_open, ha_close)
            
            ha_candles.append({
                "timestamp": candle["timestamp"],
                "open": ha_open,
                "high": ha_high,
                "low": ha_low,
                "close": ha_close,
                "volume": candle["volume"]
            })
        
        return ha_candles

# ========== CANDLESTICK PATTERN DETECTOR ==========
class CandlestickPatternDetector:
    """Detect 12 major candlestick patterns"""
    
    @staticmethod
    def is_bullish_engulfing(prev: Dict, curr: Dict) -> bool:
        """Bullish Engulfing Pattern"""
        prev_body = abs(prev["close"] - prev["open"])
        curr_body = abs(curr["close"] - curr["open"])
        
        return (prev["close"] < prev["open"] and  # Previous bearish
                curr["close"] > curr["open"] and  # Current bullish
                curr["open"] < prev["close"] and  # Opens below prev close
                curr["close"] > prev["open"] and  # Closes above prev open
                curr_body > prev_body * 1.2)      # Larger body
    
    @staticmethod
    def is_bearish_engulfing(prev: Dict, curr: Dict) -> bool:
        """Bearish Engulfing Pattern"""
        prev_body = abs(prev["close"] - prev["open"])
        curr_body = abs(curr["close"] - curr["open"])
        
        return (prev["close"] > prev["open"] and  # Previous bullish
                curr["close"] < curr["open"] and  # Current bearish
                curr["open"] > prev["close"] and  # Opens above prev close
                curr["close"] < prev["open"] and  # Closes below prev open
                curr_body > prev_body * 1.2)      # Larger body
    
    @staticmethod
    def is_hammer(candle: Dict) -> bool:
        """Hammer Pattern (Bullish Reversal)"""
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        
        return (lower_shadow > body * 2 and
                upper_shadow < body * 0.3 and
                body > 0)
    
    @staticmethod
    def is_hanging_man(candle: Dict) -> bool:
        """Hanging Man Pattern (Bearish Reversal)"""
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        
        return (lower_shadow > body * 2 and
                upper_shadow < body * 0.3 and
                candle["close"] < candle["open"])
    
    @staticmethod
    def is_shooting_star(candle: Dict) -> bool:
        """Shooting Star Pattern (Bearish Reversal)"""
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        
        return (upper_shadow > body * 2 and
                lower_shadow < body * 0.3 and
                body > 0)
    
    @staticmethod
    def is_doji(candle: Dict) -> bool:
        """Doji Pattern (Indecision)"""
        body = abs(candle["close"] - candle["open"])
        total_range = candle["high"] - candle["low"]
        
        return body < total_range * 0.1 and total_range > 0
    
    @staticmethod
    def is_morning_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Morning Star Pattern (Bullish Reversal)"""
        return (c1["close"] < c1["open"] and  # First bearish
                abs(c2["close"] - c2["open"]) < abs(c1["close"] - c1["open"]) * 0.3 and  # Small body
                c3["close"] > c3["open"] and  # Third bullish
                c3["close"] > (c1["open"] + c1["close"]) / 2)  # Closes above midpoint
    
    @staticmethod
    def is_evening_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Evening Star Pattern (Bearish Reversal)"""
        return (c1["close"] > c1["open"] and  # First bullish
                abs(c2["close"] - c2["open"]) < abs(c1["close"] - c1["open"]) * 0.3 and  # Small body
                c3["close"] < c3["open"] and  # Third bearish
                c3["close"] < (c1["open"] + c1["close"]) / 2)  # Closes below midpoint
    
    @staticmethod
    def is_three_white_soldiers(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Three White Soldiers (Strong Bullish)"""
        return (c1["close"] > c1["open"] and
                c2["close"] > c2["open"] and
                c3["close"] > c3["open"] and
                c2["close"] > c1["close"] and
                c3["close"] > c2["close"] and
                c2["open"] > c1["open"] and c2["open"] < c1["close"] and
                c3["open"] > c2["open"] and c3["open"] < c2["close"])
    
    @staticmethod
    def is_three_black_crows(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Three Black Crows (Strong Bearish)"""
        return (c1["close"] < c1["open"] and
                c2["close"] < c2["open"] and
                c3["close"] < c3["open"] and
                c2["close"] < c1["close"] and
                c3["close"] < c2["close"] and
                c2["open"] < c1["open"] and c2["open"] > c1["close"] and
                c3["open"] < c2["open"] and c3["open"] > c2["close"])
    
    @staticmethod
    def is_bullish_harami(prev: Dict, curr: Dict) -> bool:
        """Bullish Harami Pattern"""
        return (prev["close"] < prev["open"] and  # Previous bearish
                curr["close"] > curr["open"] and  # Current bullish
                curr["open"] > prev["close"] and
                curr["close"] < prev["open"])
    
    @staticmethod
    def is_bearish_harami(prev: Dict, curr: Dict) -> bool:
        """Bearish Harami Pattern"""
        return (prev["close"] > prev["open"] and  # Previous bullish
                curr["close"] < curr["open"] and  # Current bearish
                curr["open"] < prev["close"] and
                curr["close"] > prev["open"])
    
    @staticmethod
    def detect_all_patterns(candles: List[Dict]) -> List[Dict]:
        """Detect all patterns in the candle data"""
        patterns = []
        
        if len(candles) < 3:
            return patterns
        
        # Two-candle patterns
        for i in range(1, len(candles)):
            prev = candles[i-1]
            curr = candles[i]
            
            if CandlestickPatternDetector.is_bullish_engulfing(prev, curr):
                patterns.append({
                    "name": "Bullish Engulfing",
                    "type": "reversal",
                    "direction": "bullish",
                    "confidence": 85,
                    "position": i,
                    "description": "Strong bullish reversal signal"
                })
            
            if CandlestickPatternDetector.is_bearish_engulfing(prev, curr):
                patterns.append({
                    "name": "Bearish Engulfing",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 85,
                    "position": i,
                    "description": "Strong bearish reversal signal"
                })
            
            if CandlestickPatternDetector.is_bullish_harami(prev, curr):
                patterns.append({
                    "name": "Bullish Harami",
                    "type": "reversal",
                    "direction": "bullish",
                    "confidence": 70,
                    "position": i,
                    "description": "Bullish reversal indication"
                })
            
            if CandlestickPatternDetector.is_bearish_harami(prev, curr):
                patterns.append({
                    "name": "Bearish Harami",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 70,
                    "position": i,
                    "description": "Bearish reversal indication"
                })
        
        # Single-candle patterns
        for i in range(len(candles)):
            candle = candles[i]
            
            if CandlestickPatternDetector.is_hammer(candle):
                patterns.append({
                    "name": "Hammer",
                    "type": "reversal",
                    "direction": "bullish",
                    "confidence": 75,
                    "position": i,
                    "description": "Bullish reversal at support"
                })
            
            if CandlestickPatternDetector.is_hanging_man(candle):
                patterns.append({
                    "name": "Hanging Man",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 75,
                    "position": i,
                    "description": "Bearish reversal at resistance"
                })
            
            if CandlestickPatternDetector.is_shooting_star(candle):
                patterns.append({
                    "name": "Shooting Star",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 80,
                    "position": i,
                    "description": "Strong bearish reversal"
                })
            
            if CandlestickPatternDetector.is_doji(candle):
                patterns.append({
                    "name": "Doji",
                    "type": "indecision",
                    "direction": "neutral",
                    "confidence": 60,
                    "position": i,
                    "description": "Market indecision, potential reversal"
                })
        
        # Three-candle patterns
        for i in range(2, len(candles)):
            c1, c2, c3 = candles[i-2], candles[i-1], candles[i]
            
            if CandlestickPatternDetector.is_morning_star(c1, c2, c3):
                patterns.append({
                    "name": "Morning Star",
                    "type": "reversal",
                    "direction": "bullish",
                    "confidence": 90,
                    "position": i,
                    "description": "Very strong bullish reversal"
                })
            
            if CandlestickPatternDetector.is_evening_star(c1, c2, c3):
                patterns.append({
                    "name": "Evening Star",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 90,
                    "position": i,
                    "description": "Very strong bearish reversal"
                })
            
            if CandlestickPatternDetector.is_three_white_soldiers(c1, c2, c3):
                patterns.append({
                    "name": "Three White Soldiers",
                    "type": "continuation",
                    "direction": "bullish",
                    "confidence": 95,
                    "position": i,
                    "description": "Extremely strong bullish trend"
                })
            
            if CandlestickPatternDetector.is_three_black_crows(c1, c2, c3):
                patterns.append({
                    "name": "Three Black Crows",
                    "type": "continuation",
                    "direction": "bearish",
                    "confidence": 95,
                    "position": i,
                    "description": "Extremely strong bearish trend"
                })
        
        return patterns

# ========== ICT ANALYZER ==========
class ICTAnalyzer:
    """Inner Circle Trader Market Structure Analysis"""
    
    @staticmethod
    def detect_fair_value_gaps(candles: List[Dict]) -> List[Dict]:
        """Detect Fair Value Gaps (FVG)"""
        fvgs = []
        
        for i in range(2, len(candles)):
            prev = candles[i-2]
            curr = candles[i]
            
            # Bullish FVG
            if prev["high"] < curr["low"]:
                gap_size = curr["low"] - prev["high"]
                fvgs.append({
                    "type": "bullish",
                    "start": prev["high"],
                    "end": curr["low"],
                    "size": gap_size,
                    "position": i,
                    "strength": "strong" if gap_size > (prev["close"] * 0.01) else "moderate"
                })
            
            # Bearish FVG
            if prev["low"] > curr["high"]:
                gap_size = prev["low"] - curr["high"]
                fvgs.append({
                    "type": "bearish",
                    "start": curr["high"],
                    "end": prev["low"],
                    "size": gap_size,
                    "position": i,
                    "strength": "strong" if gap_size > (prev["close"] * 0.01) else "moderate"
                })
        
        return fvgs
    
    @staticmethod
    def detect_order_blocks(candles: List[Dict]) -> List[Dict]:
        """Detect Order Blocks"""
        order_blocks = []
        
        for i in range(3, len(candles)):
            # Bullish Order Block (last bearish candle before strong move up)
            if (candles[i-1]["close"] < candles[i-1]["open"] and
                candles[i]["close"] > candles[i]["open"] and
                candles[i]["close"] > candles[i-1]["high"]):
                
                order_blocks.append({
                    "type": "bullish",
                    "high": candles[i-1]["high"],
                    "low": candles[i-1]["low"],
                    "position": i-1,
                    "strength": "strong" if (candles[i]["close"] - candles[i-1]["low"]) > (candles[i-1]["high"] - candles[i-1]["low"]) * 2 else "moderate"
                })
            
            # Bearish Order Block (last bullish candle before strong move down)
            if (candles[i-1]["close"] > candles[i-1]["open"] and
                candles[i]["close"] < candles[i]["open"] and
                candles[i]["close"] < candles[i-1]["low"]):
                
                order_blocks.append({
                    "type": "bearish",
                    "high": candles[i-1]["high"],
                    "low": candles[i-1]["low"],
                    "position": i-1,
                    "strength": "strong" if (candles[i-1]["high"] - candles[i]["close"]) > (candles[i-1]["high"] - candles[i-1]["low"]) * 2 else "moderate"
                })
        
        return order_blocks
    
    @staticmethod
    def analyze_market_structure(candles: List[Dict]) -> Dict:
        """Analyze overall market structure"""
        if len(candles) < 20:
            return {"structure": "insufficient_data"}
        
        recent_candles = candles[-20:]
        highs = [c["high"] for c in recent_candles]
        lows = [c["low"] for c in recent_candles]
        
        # Higher highs and higher lows = bullish
        higher_highs = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i-1])
        higher_lows = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i-1])
        
        # Lower highs and lower lows = bearish
        lower_highs = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i-1])
        lower_lows = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i-1])
        
        if higher_highs > 12 and higher_lows > 12:
            structure = "bullish_trend"
            strength = "strong"
        elif lower_highs > 12 and lower_lows > 12:
            structure = "bearish_trend"
            strength = "strong"
        elif higher_highs > 8 and higher_lows > 8:
            structure = "bullish_trend"
            strength = "moderate"
        elif lower_highs > 8 and lower_lows > 8:
            structure = "bearish_trend"
            strength = "moderate"
        else:
            structure = "ranging"
            strength = "weak"
        
        return {
            "structure": structure,
            "strength": strength,
            "higher_highs": higher_highs,
            "higher_lows": higher_lows,
            "lower_highs": lower_highs,
            "lower_lows": lower_lows
        }

# ========== SIGNAL GENERATOR ==========
class SignalGenerator:
    """Generate trading signals with confidence levels"""
    
    @staticmethod
    def calculate_ema_signal(ema_fast: List[float], ema_slow: List[float]) -> Dict:
        """Calculate signal from EMA crossover"""
        if not ema_fast or not ema_slow or len(ema_fast) < 2 or len(ema_slow) < 2:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "insufficient_data"}
        
        # Current and previous values
        fast_curr = ema_fast[-1]
        fast_prev = ema_fast[-2]
        slow_curr = ema_slow[-1]
        slow_prev = ema_slow[-2]
        
        if fast_curr is None or fast_prev is None or slow_curr is None or slow_prev is None:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "insufficient_data"}
        
        # Golden Cross (bullish)
        if fast_prev <= slow_prev and fast_curr > slow_curr:
            distance = abs(fast_curr - slow_curr) / slow_curr * 100
            confidence = min(90, 70 + distance * 10)
            return {
                "signal": "BUY",
                "confidence": confidence,
                "reason": "golden_cross",
                "description": "EMA fast crossed above EMA slow (Golden Cross)"
            }
        
        # Death Cross (bearish)
        if fast_prev >= slow_prev and fast_curr < slow_curr:
            distance = abs(fast_curr - slow_curr) / slow_curr * 100
            confidence = min(90, 70 + distance * 10)
            return {
                "signal": "SELL",
                "confidence": confidence,
                "reason": "death_cross",
                "description": "EMA fast crossed below EMA slow (Death Cross)"
            }
        
        # Trending
        if fast_curr > slow_curr:
            distance = (fast_curr - slow_curr) / slow_curr * 100
            if distance > 2:
                return {
                    "signal": "BUY",
                    "confidence": min(80, 50 + distance * 5),
                    "reason": "uptrend",
                    "description": f"Strong uptrend (EMA distance: {distance:.2f}%)"
                }
            else:
                return {
                    "signal": "NEUTRAL",
                    "confidence": 40,
                    "reason": "weak_uptrend",
                    "description": "Weak uptrend"
                }
        else:
            distance = (slow_curr - fast_curr) / slow_curr * 100
            if distance > 2:
                return {
                    "signal": "SELL",
                    "confidence": min(80, 50 + distance * 5),
                    "reason": "downtrend",
                    "description": f"Strong downtrend (EMA distance: {distance:.2f}%)"
                }
            else:
                return {
                    "signal": "NEUTRAL",
                    "confidence": 40,
                    "reason": "weak_downtrend",
                    "description": "Weak downtrend"
                }
    
    @staticmethod
    def calculate_rsi_signal(rsi: List[float]) -> Dict:
        """Calculate signal from RSI"""
        if not rsi or len(rsi) < 2:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "insufficient_data"}
        
        current_rsi = rsi[-1]
        prev_rsi = rsi[-2]
        
        if current_rsi is None or prev_rsi is None:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "insufficient_data"}
        
        # Oversold (< 30)
        if current_rsi < 30:
            if prev_rsi < 30 and current_rsi > prev_rsi:
                return {
                    "signal": "STRONG_BUY",
                    "confidence": 85,
                    "reason": "oversold_reversal",
                    "description": f"Oversold reversal (RSI: {current_rsi:.1f})"
                }
            return {
                "signal": "BUY",
                "confidence": 70,
                "reason": "oversold",
                "description": f"Oversold condition (RSI: {current_rsi:.1f})"
            }
        
        # Overbought (> 70)
        if current_rsi > 70:
            if prev_rsi > 70 and current_rsi < prev_rsi:
                return {
                    "signal": "STRONG_SELL",
                    "confidence": 85,
                    "reason": "overbought_reversal",
                    "description": f"Overbought reversal (RSI: {current_rsi:.1f})"
                }
            return {
                "signal": "SELL",
                "confidence": 70,
                "reason": "overbought",
                "description": f"Overbought condition (RSI: {current_rsi:.1f})"
            }
        
        # Neutral zone
        if 40 <= current_rsi <= 60:
            return {
                "signal": "NEUTRAL",
                "confidence": 50,
                "reason": "neutral_zone",
                "description": f"Neutral RSI (RSI: {current_rsi:.1f})"
            }
        
        # Bullish
        if current_rsi > 50 and current_rsi > prev_rsi:
            return {
                "signal": "BUY",
                "confidence": 60,
                "reason": "bullish_momentum",
                "description": f"Bullish momentum (RSI: {current_rsi:.1f})"
            }
        
        # Bearish
        if current_rsi < 50 and current_rsi < prev_rsi:
            return {
                "signal": "SELL",
                "confidence": 60,
                "reason": "bearish_momentum",
                "description": f"Bearish momentum (RSI: {current_rsi:.1f})"
            }
        
        return {
            "signal": "NEUTRAL",
            "confidence": 45,
            "reason": "unclear",
            "description": f"Unclear signal (RSI: {current_rsi:.1f})"
        }
    
    @staticmethod
    def calculate_pattern_signal(patterns: List[Dict]) -> Dict:
        """Calculate signal from candlestick patterns"""
        if not patterns:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "no_patterns"}
        
        # Get recent patterns (last 5 candles)
        recent_patterns = [p for p in patterns if p["position"] >= len(patterns) - 5]
        
        if not recent_patterns:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "no_recent_patterns"}
        
        # Calculate weighted signal
        bullish_score = sum(p["confidence"] for p in recent_patterns if p["direction"] == "bullish")
        bearish_score = sum(p["confidence"] for p in recent_patterns if p["direction"] == "bearish")
        
        max_confidence = max(p["confidence"] for p in recent_patterns)
        
        if bullish_score > bearish_score * 1.5:
            return {
                "signal": "BUY" if max_confidence < 90 else "STRONG_BUY",
                "confidence": min(95, max_confidence),
                "reason": "bullish_patterns",
                "description": f"{len([p for p in recent_patterns if p['direction'] == 'bullish'])} bullish pattern(s) detected",
                "patterns": recent_patterns
            }
        elif bearish_score > bullish_score * 1.5:
            return {
                "signal": "SELL" if max_confidence < 90 else "STRONG_SELL",
                "confidence": min(95, max_confidence),
                "reason": "bearish_patterns",
                "description": f"{len([p for p in recent_patterns if p['direction'] == 'bearish'])} bearish pattern(s) detected",
                "patterns": recent_patterns
            }
        else:
            return {
                "signal": "NEUTRAL",
                "confidence": 50,
                "reason": "mixed_patterns",
                "description": "Mixed pattern signals",
                "patterns": recent_patterns
            }
    
    @staticmethod
    def calculate_ict_signal(fvgs: List[Dict], order_blocks: List[Dict], market_structure: Dict) -> Dict:
        """Calculate signal from ICT analysis"""
        score = 0
        reasons = []
        
        # Market structure
        if market_structure["structure"] == "bullish_trend":
            score += 30 if market_structure["strength"] == "strong" else 20
            reasons.append(f"Bullish market structure ({market_structure['strength']})")
        elif market_structure["structure"] == "bearish_trend":
            score -= 30 if market_structure["strength"] == "strong" else 20
            reasons.append(f"Bearish market structure ({market_structure['strength']})")
        
        # Recent FVGs
        recent_fvgs = [f for f in fvgs if f["position"] >= len(fvgs) - 3] if fvgs else []
        for fvg in recent_fvgs:
            if fvg["type"] == "bullish":
                score += 15 if fvg["strength"] == "strong" else 10
                reasons.append(f"Bullish FVG ({fvg['strength']})")
            else:
                score -= 15 if fvg["strength"] == "strong" else 10
                reasons.append(f"Bearish FVG ({fvg['strength']})")
        
        # Recent Order Blocks
        recent_obs = [ob for ob in order_blocks if ob["position"] >= len(order_blocks) - 3] if order_blocks else []
        for ob in recent_obs:
            if ob["type"] == "bullish":
                score += 20 if ob["strength"] == "strong" else 12
                reasons.append(f"Bullish Order Block ({ob['strength']})")
            else:
                score -= 20 if ob["strength"] == "strong" else 12
                reasons.append(f"Bearish Order Block ({ob['strength']})")
        
        # Determine signal
        confidence = min(95, abs(score))
        
        if score > 50:
            signal = "STRONG_BUY"
        elif score > 25:
            signal = "BUY"
        elif score < -50:
            signal = "STRONG_SELL"
        elif score < -25:
            signal = "SELL"
        else:
            signal = "NEUTRAL"
        
        return {
            "signal": signal,
            "confidence": confidence,
            "score": score,
            "reasons": reasons,
            "description": " | ".join(reasons) if reasons else "No clear ICT signal"
        }
    
    @staticmethod
    def generate_combined_signal(ema_signal: Dict, rsi_signal: Dict, pattern_signal: Dict, ict_signal: Dict, ha_trend: str) -> Dict:
        """Combine all signals into final recommendation"""
        
        # Signal weights
        weights = {
            "ema": 0.25,
            "rsi": 0.20,
            "patterns": 0.30,
            "ict": 0.25
        }
        
        # Convert signals to numeric scores
        signal_values = {
            "STRONG_BUY": 2,
            "BUY": 1,
            "NEUTRAL": 0,
            "SELL": -1,
            "STRONG_SELL": -2
        }
        
        # Calculate weighted score
        total_score = 0
        total_confidence = 0
        
        for sig, weight in [
            (ema_signal, weights["ema"]),
            (rsi_signal, weights["rsi"]),
            (pattern_signal, weights["patterns"]),
            (ict_signal, weights["ict"])
        ]:
            sig_value = signal_values.get(sig.get("signal", "NEUTRAL"), 0)
            sig_conf = sig.get("confidence", 0)
            total_score += sig_value * weight * (sig_conf / 100)
            total_confidence += sig_conf * weight
        
        # Heikin Ashi trend bonus
        if ha_trend == "strong_bullish":
            total_score += 0.3
            total_confidence += 5
        elif ha_trend == "strong_bearish":
            total_score -= 0.3
            total_confidence += 5
        
        # Determine final signal
        if total_score > 1.2:
            final_signal = SignalType.STRONG_BUY
        elif total_score > 0.5:
            final_signal = SignalType.BUY
        elif total_score < -1.2:
            final_signal = SignalType.STRONG_SELL
        elif total_score < -0.5:
            final_signal = SignalType.SELL
        else:
            final_signal = SignalType.NEUTRAL
        
        # Determine confidence level
        if total_confidence >= 85:
            conf_level = SignalConfidence.VERY_HIGH
        elif total_confidence >= 70:
            conf_level = SignalConfidence.HIGH
        elif total_confidence >= 55:
            conf_level = SignalConfidence.MEDIUM
        else:
            conf_level = SignalConfidence.LOW
        
        return {
            "signal": final_signal,
            "confidence": round(total_confidence, 1),
            "confidence_level": conf_level,
            "score": round(total_score, 2),
            "components": {
                "ema": ema_signal,
                "rsi": rsi_signal,
                "patterns": pattern_signal,
                "ict": ict_signal,
                "heikin_ashi_trend": ha_trend
            },
            "recommendation": SignalGenerator._generate_recommendation(final_signal, total_confidence, total_score)
        }
    
    @staticmethod
    def _generate_recommendation(signal: SignalType, confidence: float, score: float) -> str:
        """Generate human-readable recommendation"""
        if signal == SignalType.STRONG_BUY:
            if confidence >= 85:
                return "🚀 STRONG BUY - Very high confidence signal. Consider entering long position."
            else:
                return "📈 STRONG BUY - Good bullish setup. Moderate confidence."
        elif signal == SignalType.BUY:
            return "✅ BUY - Bullish signal detected. Consider buying on dips."
        elif signal == SignalType.STRONG_SELL:
            if confidence >= 85:
                return "🔴 STRONG SELL - Very high confidence bearish signal. Consider exiting or shorting."
            else:
                return "📉 STRONG SELL - Bearish setup. Moderate confidence."
        elif signal == SignalType.SELL:
            return "⚠️ SELL - Bearish signal detected. Consider taking profits or shorting."
        else:
            return "⏸️ NEUTRAL - No clear directional bias. Wait for better setup."

# ========== API ENDPOINTS ==========
@app.get("/api/analyze/{symbol}")
async def analyze_symbol(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1h|4h|1d)$")
):
    """Complete technical analysis for a symbol"""
    try:
        # Fetch candle data
        candles = await PriceFetcher.get_candles(symbol, interval, 100)
        
        if not candles or len(candles) < 50:
            raise HTTPException(status_code=400, detail="Insufficient data for analysis")
        
        # Calculate indicators
        ema_9 = TechnicalIndicators.calculate_ema(candles, 9)
        ema_21 = TechnicalIndicators.calculate_ema(candles, 21)
        ema_50 = TechnicalIndicators.calculate_ema(candles, 50)
        rsi = TechnicalIndicators.calculate_rsi(candles, 14)
        ha_candles = TechnicalIndicators.convert_to_heikin_ashi(candles)
        
        # Detect patterns
        patterns = CandlestickPatternDetector.detect_all_patterns(candles)
        
        # ICT Analysis
        fvgs = ICTAnalyzer.detect_fair_value_gaps(candles)
        order_blocks = ICTAnalyzer.detect_order_blocks(candles)
        market_structure = ICTAnalyzer.analyze_market_structure(candles)
        
        # Heikin Ashi trend
        ha_recent = ha_candles[-5:]
        bullish_ha = sum(1 for c in ha_recent if c["close"] > c["open"])
        if bullish_ha >= 4:
            ha_trend = "strong_bullish"
        elif bullish_ha >= 3:
            ha_trend = "bullish"
        elif bullish_ha <= 1:
            ha_trend = "strong_bearish"
        elif bullish_ha <= 2:
            ha_trend = "bearish"
        else:
            ha_trend = "neutral"
        
        # Generate signals
        ema_signal = SignalGenerator.calculate_ema_signal(ema_9, ema_21)
        rsi_signal = SignalGenerator.calculate_rsi_signal(rsi)
        pattern_signal = SignalGenerator.calculate_pattern_signal(patterns)
        ict_signal = SignalGenerator.calculate_ict_signal(fvgs, order_blocks, market_structure)
        
        # Combined signal
        combined_signal = SignalGenerator.generate_combined_signal(
            ema_signal, rsi_signal, pattern_signal, ict_signal, ha_trend
        )
        
        # Current price data
        current_candle = candles[-1]
        prev_candle = candles[-2]
        price_change = ((current_candle["close"] - prev_candle["close"]) / prev_candle["close"]) * 100
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "interval": interval,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "price_data": {
                "current": current_candle["close"],
                "open": current_candle["open"],
                "high": current_candle["high"],
                "low": current_candle["low"],
                "change_percent": round(price_change, 2),
                "volume": current_candle["volume"]
            },
            "indicators": {
                "ema_9": round(ema_9[-1], 4) if ema_9[-1] else None,
                "ema_21": round(ema_21[-1], 4) if ema_21[-1] else None,
                "ema_50": round(ema_50[-1], 4) if ema_50[-1] else None,
                "rsi": round(rsi[-1], 2) if rsi[-1] else None,
                "heikin_ashi_trend": ha_trend
            },
            "patterns": patterns[-10:],  # Last 10 patterns
            "ict_analysis": {
                "fair_value_gaps": fvgs[-5:],  # Last 5 FVGs
                "order_blocks": order_blocks[-5:],  # Last 5 OBs
                "market_structure": market_structure
            },
            "signal": combined_signal
        }
        
    except Exception as e:
        logger.error(f"Analysis error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Main trading dashboard"""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Professional Trading Bot</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        :root {
            --bg-dark: #0a0e27;
            --bg-card: #1a1f3a;
            --bg-hover: #252b4a;
            --primary: #3b82f6;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --text: #e2e8f0;
            --text-muted: #94a3b8;
            --border: rgba(148, 163, 184, 0.1);
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, var(--bg-dark) 0%, #1a1f3a 100%);
            color: var(--text);
            min-height: 100vh;
            padding: 1rem;
        }
        
        .container { max-width: 1800px; margin: 0 auto; }
        
        header {
            background: linear-gradient(90deg, var(--primary), #8b5cf6);
            border-radius: 16px;
            padding: 2rem;
            margin-bottom: 2rem;
            text-align: center;
            box-shadow: 0 10px 30px rgba(59, 130, 246, 0.3);
        }
        
        .logo {
            font-size: 2.5rem;
            font-weight: 900;
            color: white;
            margin-bottom: 0.5rem;
        }
        
        .tagline {
            color: rgba(255, 255, 255, 0.9);
            font-size: 1.1rem;
        }
        
        .badges {
            display: flex;
            justify-content: center;
            gap: 0.75rem;
            margin-top: 1rem;
            flex-wrap: wrap;
        }
        
        .badge {
            background: rgba(255, 255, 255, 0.15);
            padding: 0.4rem 1rem;
            border-radius: 20px;
            font-size: 0.85rem;
            backdrop-filter: blur(10px);
        }
        
        .control-panel {
            background: var(--bg-card);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            border: 1px solid var(--border);
        }
        
        .panel-title {
            font-size: 1.3rem;
            font-weight: 700;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .input-row {
            display: grid;
            grid-template-columns: 1fr 200px auto;
            gap: 1rem;
            margin-bottom: 1rem;
        }
        
        input, select {
            background: var(--bg-dark);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 0.75rem 1rem;
            border-radius: 8px;
            font-size: 0.95rem;
        }
        
        input:focus, select:focus {
            outline: none;
            border-color: var(--primary);
        }
        
        button {
            background: linear-gradient(90deg, var(--primary), #8b5cf6);
            color: white;
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s;
        }
        
        button:hover { transform: translateY(-2px); }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        
        .quick-symbols {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }
        
        .quick-symbol {
            background: rgba(59, 130, 246, 0.1);
            border: 1px solid rgba(59, 130, 246, 0.3);
            padding: 0.4rem 0.8rem;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 0.85rem;
        }
        
        .quick-symbol:hover {
            background: rgba(59, 130, 246, 0.2);
            border-color: var(--primary);
        }
        
        .dashboard {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
            margin-bottom: 1.5rem;
        }
        
        @media (max-width: 1200px) {
            .dashboard { grid-template-columns: 1fr; }
            .input-row { grid-template-columns: 1fr; }
        }
        
        .card {
            background: var(--bg-card);
            border-radius: 12px;
            padding: 1.5rem;
            border: 1px solid var(--border);
        }
        
        .card-title {
            font-size: 1.2rem;
            font-weight: 700;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .signal-box {
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(139, 92, 246, 0.1) 100%);
            border: 2px solid var(--primary);
            border-radius: 12px;
            padding: 2rem;
            text-align: center;
            margin-bottom: 1.5rem;
        }
        
        .signal-box.buy { border-color: var(--success); background: linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(16, 185, 129, 0.05) 100%); }
        .signal-box.sell { border-color: var(--danger); background: linear-gradient(135deg, rgba(239, 68, 68, 0.1) 0%, rgba(239, 68, 68, 0.05) 100%); }
        
        .signal-type {
            font-size: 2.5rem;
            font-weight: 900;
            margin-bottom: 0.5rem;
        }
        
        .signal-type.buy { color: var(--success); }
        .signal-type.sell { color: var(--danger); }
        .signal-type.neutral { color: var(--text-muted); }
        
        .confidence-badge {
            display: inline-block;
            padding: 0.4rem 1rem;
            border-radius: 20px;
            font-weight: 600;
            font-size: 0.9rem;
            margin-top: 0.5rem;
        }
        
        .confidence-very-high { background: rgba(16, 185, 129, 0.2); color: var(--success); }
        .confidence-high { background: rgba(59, 130, 246, 0.2); color: var(--primary); }
        .confidence-medium { background: rgba(245, 158, 11, 0.2); color: var(--warning); }
        .confidence-low { background: rgba(148, 163, 184, 0.2); color: var(--text-muted); }
        
        .recommendation {
            margin-top: 1rem;
            padding: 1rem;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            font-size: 0.95rem;
        }
        
        .indicators-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        
        .indicator-item {
            background: var(--bg-dark);
            padding: 1rem;
            border-radius: 8px;
            text-align: center;
        }
        
        .indicator-label {
            color: var(--text-muted);
            font-size: 0.85rem;
            margin-bottom: 0.5rem;
        }
        
        .indicator-value {
            font-size: 1.3rem;
            font-weight: 700;
        }
        
        .pattern-list {
            max-height: 400px;
            overflow-y: auto;
        }
        
        .pattern-item {
            background: var(--bg-dark);
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 0.75rem;
            border-left: 3px solid var(--primary);
        }
        
        .pattern-item.bullish { border-left-color: var(--success); }
        .pattern-item.bearish { border-left-color: var(--danger); }
        
        .pattern-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }
        
        .pattern-name {
            font-weight: 600;
            font-size: 1rem;
        }
        
        .pattern-confidence {
            background: rgba(59, 130, 246, 0.2);
            padding: 0.2rem 0.6rem;
            border-radius: 12px;
            font-size: 0.85rem;
        }
        
        .pattern-desc {
            color: var(--text-muted);
            font-size: 0.9rem;
        }
        
        .loading {
            text-align: center;
            padding: 3rem;
            color: var(--primary);
        }
        
        .spinner {
            border: 3px solid rgba(59, 130, 246, 0.3);
            border-top: 3px solid var(--primary);
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 1rem;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
      .tradingview-widget {
    width: 100%;
    height: 60vh;              /* Ekranın %60'ı – mobil ve masaüstünde güzel durur */
    min-height: 450px;         /* Küçük ekranlarda çok küçülmesin */
    max-height: 900px;         /* Çok büyük olmasın */
    border-radius: 8px;
    overflow: hidden;
    background: #0a0e27;       /* Arka plan TradingView yüklenirken boş kalmasın */
    box-shadow: 0 4px 15px rgba(0,0,0,0.3);  /* Hafif gölge – şık durur */
}

/* Ekstra: Mobil için küçültme */
@media (max-width: 768px) {
    .tradingview-widget {
        height: 50vh;          /* Mobilde daha az yer kaplasın */
        min-height: 350px;
    }
}
        #tradingview_chart {
            width: 100%;
            height: 100%;
        }
        
        .ict-section {
            margin-top: 1rem;
        }
        
        .ict-item {
            background: var(--bg-dark);
            padding: 0.75rem;
            border-radius: 6px;
            margin-bottom: 0.5rem;
            font-size: 0.9rem;
        }
        
        .ict-label {
            color: var(--text-muted);
            display: inline-block;
            min-width: 120px;
        }
        
        footer {
            text-align: center;
            padding: 2rem;
            color: var(--text-muted);
            border-top: 1px solid var(--border);
            margin-top: 2rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <i class="fas fa-chart-line"></i> Professional Trading Bot
            </div>
            <div class="tagline">Advanced Technical Analysis • Multi-Timeframe • High-Confidence Signals</div>
            <div class="badges">
                <div class="badge"><i class="fas fa-wave-square"></i> EMA Crossovers</div>
                <div class="badge"><i class="fas fa-chart-bar"></i> RSI Analysis</div>
                <div class="badge"><i class="fas fa-candle-holder"></i> Heikin Ashi</div>
                <div class="badge"><i class="fas fa-chess-board"></i> ICT Structure</div>
                <div class="badge"><i class="fas fa-pattern"></i> 12 Patterns</div>
            </div>
        </header>
        
        <div class="control-panel">
            <h2 class="panel-title">
                <i class="fas fa-sliders-h"></i> Analysis Control
            </h2>
            <div class="input-row">
                <input type="text" id="symbolInput" placeholder="Enter symbol (e.g., BTCUSDT, ETHUSDT)" value="BTCUSDT">
                <select id="intervalSelect">
                    <option value="1h">1 Hour</option>
                    <option value="4h">4 Hours</option>
                    <option value="1d">1 Day</option>
                </select>
                <button onclick="analyze()" id="analyzeBtn">
                    <i class="fas fa-search"></i> Analyze
                </button>
            </div>
            <div class="quick-symbols">
                <div class="quick-symbol" onclick="setSymbol('BTCUSDT')">BTC/USDT</div>
                <div class="quick-symbol" onclick="setSymbol('ETHUSDT')">ETH/USDT</div>
                <div class="quick-symbol" onclick="setSymbol('SOLUSDT')">SOL/USDT</div>
                <div class="quick-symbol" onclick="setSymbol('XRPUSDT')">XRP/USDT</div>
                <div class="quick-symbol" onclick="setSymbol('ADAUSDT')">ADA/USDT</div>
            </div>
        </div>
        
        <div class="dashboard">
            <div class="card">
                <h2 class="card-title">
                    <i class="fas fa-signal"></i> Trading Signal
                    <span id="symbolDisplay" style="font-size: 0.9rem; color: var(--text-muted); margin-left: auto;">-</span>
                </h2>
                <div id="signalContainer">
                    <div class="loading">
                        <div class="spinner"></div>
                        <div>Ready to analyze...</div>
                    </div>
                </div>
            </div>
            
            <div class="card">
                <h2 class="card-title">
                    <i class="fas fa-chart-area"></i> TradingView Chart
                </h2>
                <div class="tradingview-widget">
                    <div id="tradingview_chart"></div>
                </div>
            </div>
        </div>
        
        <div class="dashboard">
           <!-- Dashboard HTML'ine bu kısmı ekleyin -->
<div class="card">
    <h2 class="card-title">
        <i class="fas fa-brain"></i> AI Trading Assistant
        <span id="aiStatus" style="font-size: 0.8rem; background: #ef4444; color: white; padding: 2px 8px; border-radius: 10px; margin-left: 10px;">
            OFF
        </span>
    </h2>
    
    <div id="aiContainer">
        <div id="aiLoading" style="text-align: center; padding: 20px;">
            <div class="spinner"></div>
            <div>Loading AI module...</div>
        </div>
        
        <div id="aiControls" style="display: none;">
            <!-- AI Chat Input -->
            <div style="margin-bottom: 20px;">
                <div style="display: flex; gap: 10px; margin-bottom: 10px;">
                    <input type="text" id="aiChatInput" placeholder="Ask AI trading question..." style="flex: 1;">
                    <button onclick="askAI()" style="background: #3b82f6; color: white; border: none; padding: 10px 15px; border-radius: 6px; cursor: pointer;">
                        <i class="fas fa-paper-plane"></i> Ask
                    </button>
                </div>
                <div id="aiChatResponse" style="background: #1a1f3a; padding: 10px; border-radius: 6px; min-height: 40px; font-size: 0.9rem;"></div>
            </div>
            
            <!-- AI Analysis Buttons -->
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 20px;">
                <button class="ai-btn" onclick="runQuickAIPrediction()" style="background: linear-gradient(135deg, #10b981, #059669);">
                    <i class="fas fa-bolt"></i> Quick AI
                </button>
                <button class="ai-btn" onclick="runDetailedAIAnalysis()" style="background: linear-gradient(135deg, #3b82f6, #2563eb);">
                    <i class="fas fa-chart-line"></i> AI Analysis
                </button>
                <button class="ai-btn" onclick="runAdvancedAnalysis()" style="background: linear-gradient(135deg, #8b5cf6, #7c3aed);">
                    <i class="fas fa-star"></i> Advanced
                </button>
            </div>
            
            <!-- AI Results -->
            <div id="aiResults" style="background: #1a1f3a; border-radius: 8px; padding: 15px; min-height: 100px;">
                <div style="text-align: center; color: #94a3b8;">
                    <i class="fas fa-robot" style="font-size: 2rem; margin-bottom: 10px;"></i>
                    <div>AI results will appear here</div>
                </div>
            </div>
            
            <!-- Image Analysis -->
            <div style="margin-top: 15px; border-top: 1px solid #334155; padding-top: 15px;">
                <div style="font-size: 0.9rem; color: #94a3b8; margin-bottom: 10px;">Chart Image Analysis</div>
                <div style="display: flex; gap: 10px;">
                    <input type="file" id="chartImage" accept="image/*" style="flex: 1; background: #0a0e27; border: 1px solid #334155; color: white; padding: 8px; border-radius: 6px;">
                    <button onclick="analyzeChartImage()" style="background: #f59e0b; color: white; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer;">
                        <i class="fas fa-image"></i> Analyze
                    </button>
                </div>
                <div id="imageAnalysisResult" style="margin-top: 10px; font-size: 0.85rem;"></div>
            </div>
        </div>
    </div>
</div>

<style>
.ai-btn {
    color: white;
    border: none;
    padding: 12px;
    border-radius: 8px;
    cursor: pointer;
    font-weight: 600;
    transition: all 0.3s;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 5px;
}
.ai-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 5px 15px rgba(0,0,0,0.3);
}
.ai-result {
    background: linear-gradient(135deg, rgba(59, 130, 246, 0.1), rgba(139, 92, 246, 0.1));
    border: 2px solid #3b82f6;
    border-radius: 10px;
    padding: 15px;
    margin-top: 10px;
}
.ai-signal-buy { border-color: #10b981; background: linear-gradient(135deg, rgba(16, 185, 129, 0.1), rgba(16, 185, 129, 0.05)); }
.ai-signal-sell { border-color: #ef4444; background: linear-gradient(135deg, rgba(239, 68, 68, 0.1), rgba(239, 68, 68, 0.05)); }
.ai-signal-hold { border-color: #f59e0b; background: linear-gradient(135deg, rgba(245, 158, 11, 0.1), rgba(245, 158, 11, 0.05)); }
</style>

<script>
// AI durumunu kontrol et
async function checkAIStatus() {
    try {
        const response = await fetch('/api/ai/status');
        const data = await response.json();
        
        const statusEl = document.getElementById('aiStatus');
        const loadingEl = document.getElementById('aiLoading');
        const controlsEl = document.getElementById('aiControls');
        
        if (data.ai_enabled) {
            if (data.initialized) {
                statusEl.textContent = 'ACTIVE';
                statusEl.style.background = '#10b981';
                loadingEl.style.display = 'none';
                controlsEl.style.display = 'block';
            } else {
                statusEl.textContent = 'INIT';
                statusEl.style.background = '#f59e0b';
                loadingEl.innerHTML = `
                    <div style="color: #f59e0b;">
                        <i class="fas fa-hourglass-half"></i>
                        <div>AI initializing...</div>
                        <button onclick="initializeAI()" style="margin-top: 10px; background: #3b82f6; color: white; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer;">
                            Initialize Now
                        </button>
                    </div>
                `;
            }
        } else {
            statusEl.textContent = 'OFF';
            statusEl.style.background = '#ef4444';
            loadingEl.innerHTML = '<div style="color: #ef4444;">AI module not available</div>';
        }
    } catch (error) {
        console.error('AI status check failed:', error);
    }
}

// AI başlat
async function initializeAI() {
    try {
        const response = await fetch('/api/ai/initialize', { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            showNotification('AI service initializing...', 'info');
            setTimeout(checkAIStatus, 2000);
        }
    } catch (error) {
        console.error('AI initialization failed:', error);
        showNotification('AI initialization failed', 'error');
    }
}

// AI'ya soru sor
async function askAI() {
    const input = document.getElementById('aiChatInput');
    const message = input.value.trim();
    const symbol = document.getElementById('symbolInput').value.trim();
    
    if (!message) {
        showNotification('Please enter a question', 'warning');
        return;
    }
    
    const responseEl = document.getElementById('aiChatResponse');
    responseEl.innerHTML = '<div class="loading"><div class="spinner" style="width: 20px; height: 20px;"></div> AI thinking...</div>';
    
    try {
        const response = await fetch('/api/ai/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message, symbol: symbol || 'BTCUSDT' })
        });
        
        const data = await response.json();
        
        if (data.success) {
            responseEl.innerHTML = `
                <div style="color: #3b82f6; margin-bottom: 5px;">
                    <i class="fas fa-robot"></i> AI Response:
                </div>
                <div>${data.response}</div>
            `;
            input.value = '';
        } else {
            responseEl.innerHTML = `<div style="color: #ef4444;">Error: ${data.error}</div>`;
        }
    } catch (error) {
        console.error('AI chat error:', error);
        responseEl.innerHTML = '<div style="color: #ef4444;">AI service unavailable</div>';
    }
}

// Hızlı AI tahmini
async function runQuickAIPrediction() {
    const symbol = document.getElementById('symbolInput').value.trim();
    if (!symbol) {
        showNotification('Please enter a symbol', 'warning');
        return;
    }
    
    const resultsEl = document.getElementById('aiResults');
    resultsEl.innerHTML = '<div class="loading"><div class="spinner"></div><div>Running quick AI prediction...</div></div>';
    
    try {
        const response = await fetch(`/api/ai/predict/${encodeURIComponent(symbol)}?detailed=false`);
        const data = await response.json();
        
        if (data.success) {
            const signalClass = `ai-signal-${data.prediction.toLowerCase()}`;
            
            let html = `
                <div class="ai-result ${signalClass}">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <div style="font-size: 1.3rem; font-weight: 700;">${data.prediction}</div>
                        <div style="background: ${data.confidence >= 0.7 ? '#10b981' : data.confidence >= 0.6 ? '#f59e0b' : '#ef4444'}; 
                                    color: white; padding: 3px 10px; border-radius: 12px;">
                            ${(data.confidence * 100).toFixed(0)}% confidence
                        </div>
                    </div>
                    
                    <div style="font-size: 0.9rem; margin-bottom: 15px;">
                        <div><strong>Symbol:</strong> ${data.symbol}</div>
                        <div><strong>Price:</strong> $${data.current_price}</div>
                        ${data.momentum ? `<div><strong>Momentum:</strong> ${data.momentum}%</div>` : ''}
                    </div>
                    
                    <div style="background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; font-size: 0.85rem;">
                        <strong>Quick AI Analysis:</strong>
                        <div style="margin-top: 5px;">
                            ${data.prediction === 'Buy' ? 'AI detects potential buying opportunity' : 
                              data.prediction === 'Sell' ? 'AI suggests caution or profit taking' : 
                              'AI recommends holding or waiting for clearer signals'}
                        </div>
                    </div>
                </div>
            `;
            
            resultsEl.innerHTML = html;
        } else {
            resultsEl.innerHTML = `<div style="color: #ef4444;">Error: ${data.error}</div>`;
        }
    } catch (error) {
        console.error('Quick AI prediction error:', error);
        resultsEl.innerHTML = '<div style="color: #ef4444;">AI service unavailable</div>';
    }
}

// Detaylı AI analizi
async function runDetailedAIAnalysis() {
    const symbol = document.getElementById('symbolInput').value.trim();
    if (!symbol) {
        showNotification('Please enter a symbol', 'warning');
        return;
    }
    
    const resultsEl = document.getElementById('aiResults');
    resultsEl.innerHTML = '<div class="loading"><div class="spinner"></div><div>Running detailed AI analysis...</div></div>';
    
    try {
        const response = await fetch(`/api/ai/predict/${encodeURIComponent(symbol)}?detailed=true`);
        const data = await response.json();
        
        if (data.success) {
            const signalClass = `ai-signal-${data.final_signal.toLowerCase()}`;
            
            let html = `
                <div class="ai-result ${signalClass}">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                        <div style="font-size: 1.5rem; font-weight: 900;">${data.final_signal}</div>
                        <div style="background: ${data.final_confidence >= 0.7 ? '#10b981' : data.final_confidence >= 0.6 ? '#f59e0b' : '#ef4444'}; 
                                    color: white; padding: 5px 15px; border-radius: 20px; font-weight: 600;">
                            ${(data.final_confidence * 100).toFixed(1)}%
                        </div>
                    </div>
                    
                    <div style="margin-bottom: 15px; font-size: 1.1rem;">
                        ${data.recommendation}
                    </div>
                    
                    <div style="background: rgba(255,255,255,0.05); padding: 15px; border-radius: 8px; margin-bottom: 15px;">
                        <strong>Multi-Timeframe Analysis:</strong>
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 10px;">
            `;
            
            for (const [tf, analysis] of Object.entries(data.timeframe_analysis)) {
                if (analysis && !analysis.error) {
                    html += `
                        <div style="background: #0a0e27; padding: 10px; border-radius: 6px; text-align: center;">
                            <div style="font-size: 0.8rem; color: #94a3b8;">${tf}</div>
                            <div style="font-size: 1.1rem; font-weight: 700; color: ${analysis.signal === 'Buy' ? '#10b981' : analysis.signal === 'Sell' ? '#ef4444' : '#f59e0b'}">
                                ${analysis.signal}
                            </div>
                            <div style="font-size: 0.8rem;">RSI: ${analysis.rsi || 'N/A'}</div>
                        </div>
                    `;
                }
            }
            
            html += `
                        </div>
                    </div>
                    
                    <div style="font-size: 0.9rem; color: #94a3b8;">
                        <div><strong>Risk Level:</strong> ${data.risk_level}</div>
                        <div><strong>Last Updated:</strong> ${new Date(data.timestamp).toLocaleTimeString()}</div>
                    </div>
                </div>
            `;
            
            resultsEl.innerHTML = html;
        } else {
            resultsEl.innerHTML = `<div style="color: #ef4444;">Error: ${data.error}</div>`;
        }
    } catch (error) {
        console.error('Detailed AI analysis error:', error);
        resultsEl.innerHTML = '<div style="color: #ef4444;">AI service unavailable</div>';
    }
}

// Gelişmiş analiz (Geleneksel + AI)
async function runAdvancedAnalysis() {
    const symbol = document.getElementById('symbolInput').value.trim();
    if (!symbol) {
        showNotification('Please enter a symbol', 'warning');
        return;
    }
    
    const resultsEl = document.getElementById('aiResults');
    resultsEl.innerHTML = '<div class="loading"><div class="spinner"></div><div>Running advanced analysis...</div></div>';
    
    try {
        const response = await fetch(`/api/advanced/analyze/${encodeURIComponent(symbol)}?include_ai=true`);
        const data = await response.json();
        
        if (data.success) {
            const signal = data.combined_signal.signal;
            const signalClass = signal.includes('BUY') ? 'ai-signal-buy' : 
                              signal.includes('SELL') ? 'ai-signal-sell' : 'ai-signal-hold';
            
            let html = `
                <div class="ai-result ${signalClass}">
                    <div style="text-align: center; margin-bottom: 20px;">
                        <div style="font-size: 2rem; font-weight: 900; margin-bottom: 10px;">${signal}</div>
                        <div style="font-size: 1.2rem; color: ${data.combined_signal.alignment === 'perfect' ? '#10b981' : '#f59e0b'}">
                            ${data.combined_signal.description || ''}
                        </div>
                    </div>
                    
                    <div style="margin-bottom: 20px; white-space: pre-line; font-size: 0.95rem; line-height: 1.5;">
                        ${data.final_recommendation}
                    </div>
                    
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px;">
                        <div style="background: rgba(59, 130, 246, 0.1); padding: 15px; border-radius: 8px;">
                            <div style="color: #3b82f6; font-weight: 700; margin-bottom: 10px;">
                                <i class="fas fa-chart-line"></i> Traditional
                            </div>
                            <div>Signal: <strong>${data.traditional_analysis.signal.signal}</strong></div>
                            <div>Confidence: ${data.traditional_analysis.signal.confidence}%</div>
                        </div>
                        
                        <div style="background: rgba(16, 185, 129, 0.1); padding: 15px; border-radius: 8px;">
                            <div style="color: #10b981; font-weight: 700; margin-bottom: 10px;">
                                <i class="fas fa-brain"></i> AI
                            </div>
                            <div>Signal: <strong>${data.ai_analysis?.final_signal || 'N/A'}</strong></div>
                            <div>Confidence: ${data.ai_analysis ? (data.ai_analysis.final_confidence * 100).toFixed(1) + '%' : 'N/A'}</div>
                        </div>
                    </div>
                    
                    <div style="font-size: 0.85rem; color: #94a3b8; text-align: center;">
                        Combined confidence: ${data.combined_signal.confidence.toFixed(1)}% • Source: ${data.combined_signal.source}
                    </div>
                </div>
            `;
            
            resultsEl.innerHTML = html;
        } else {
            resultsEl.innerHTML = `<div style="color: #ef4444;">Error: ${data.error}</div>`;
        }
    } catch (error) {
        console.error('Advanced analysis error:', error);
        resultsEl.innerHTML = '<div style="color: #ef4444;">Service unavailable</div>';
    }
}

// Grafik görseli analiz et
async function analyzeChartImage() {
    const fileInput = document.getElementById('chartImage');
    const file = fileInput.files[0];
    
    if (!file) {
        showNotification('Please select an image file', 'warning');
        return;
    }
    
    const resultEl = document.getElementById('imageAnalysisResult');
    resultEl.innerHTML = '<div class="loading"><div class="spinner" style="width: 16px; height: 16px;"></div> Analyzing chart...</div>';
    
    try {
        const formData = new FormData();
        formData.append('file', file);
        
        const response = await fetch('/api/ai/analyze-image', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            resultEl.innerHTML = `
                <div style="background: rgba(245, 158, 11, 0.1); padding: 10px; border-radius: 6px; border: 1px solid #f59e0b;">
                    <div style="color: #f59e0b; font-weight: 600; margin-bottom: 5px;">
                        <i class="fas fa-chart-bar"></i> Chart Analysis Result
                    </div>
                    <div><strong>Sentiment:</strong> ${data.sentiment}</div>
                    <div><strong>Confidence:</strong> ${(data.confidence * 100).toFixed(0)}%</div>
                    <div><strong>Patterns:</strong> ${data.patterns.join(', ')}</div>
                    <div style="margin-top: 5px; font-size: 0.8rem;">${data.analysis}</div>
                </div>
            `;
        } else {
            resultEl.innerHTML = `<div style="color: #ef4444;">Analysis failed: ${data.error}</div>`;
        }
    } catch (error) {
        console.error('Image analysis error:', error);
        resultEl.innerHTML = '<div style="color: #ef4444;">Image analysis service unavailable</div>';
    }
}

// Yardımcı fonksiyon
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        border-radius: 6px;
        color: white;
        font-weight: 600;
        z-index: 1000;
        animation: slideIn 0.3s ease;
    `;
    
    if (type === 'success') {
        notification.style.background = '#10b981';
    } else if (type === 'error') {
        notification.style.background = '#ef4444';
    } else if (type === 'warning') {
        notification.style.background = '#f59e0b';
    } else {
        notification.style.background = '#3b82f6';
    }
    
    notification.textContent = message;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Sayfa yüklendiğinde AI durumunu kontrol et
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(checkAIStatus, 1000);
});

// Mevcut analyze() fonksiyonunu güncelle
async function analyze() {
    const symbol = document.getElementById('symbolInput').value.trim();
    const interval = document.getElementById('intervalSelect').value;
    const btn = document.getElementById('analyzeBtn');
    
    if (!symbol) {
        alert('Please enter a symbol');
        return;
    }
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analyzing...';
    
    // Mevcut analiz kodunuz burada...
    
    // AI analizini de çalıştır
    setTimeout(() => {
        runQuickAIPrediction();
    }, 500);
    
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-search"></i> Analyze';
}
</script>

    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>
        let tvWidget = null;
        
        function initTradingView(symbol) {
            if (tvWidget) {
                tvWidget.remove();
            }
            
            let tvSymbol = symbol.toUpperCase();
            if (tvSymbol.endsWith("USDT")) {
                tvSymbol = `BINANCE:${tvSymbol}`;
            }
            
            tvWidget = new TradingView.widget({
                width: "100%",
                height: "100%",
                symbol: tvSymbol,
                interval: "60",
                timezone: "Etc/UTC",
                theme: "dark",
                style: "1",
                locale: "en",
                toolbar_bg: "#1a1f3a",
                enable_publishing: false,
                container_id: "tradingview_chart",
                studies: [
                    "RSI@tv-basicstudies",
                    "MASimple@tv-basicstudies"
                ],
                overrides: {
                    "paneProperties.background": "#0a0e27",
                    "paneProperties.vertGridProperties.color": "#1a1f3a",
                    "paneProperties.horzGridProperties.color": "#1a1f3a"
                }
            });
        }
        
        function setSymbol(symbol) {
            document.getElementById('symbolInput').value = symbol;
            analyze();
        }
        
        async function analyze() {
            const symbol = document.getElementById('symbolInput').value.trim();
            const interval = document.getElementById('intervalSelect').value;
            const btn = document.getElementById('analyzeBtn');
            
            if (!symbol) {
                alert('Please enter a symbol');
                return;
            }
            
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analyzing...';
            
            document.getElementById('symbolDisplay').textContent = symbol.toUpperCase();
            document.getElementById('signalContainer').innerHTML = '<div class="loading"><div class="spinner"></div><div>Analyzing ' + symbol + '...</div></div>';
            document.getElementById('indicatorsContainer').innerHTML = '<div class="loading"><div class="spinner"></div></div>';
            document.getElementById('patternsContainer').innerHTML = '<div class="loading"><div class="spinner"></div></div>';
            document.getElementById('ictContainer').innerHTML = '<div class="loading"><div class="spinner"></div></div>';
            
            initTradingView(symbol);
            
            try {
                const response = await fetch(`/api/analyze/${encodeURIComponent(symbol)}?interval=${interval}`);
                const data = await response.json();
                
                if (!data.success) {
                    throw new Error('Analysis failed');
                }
                
                renderSignal(data);
                renderIndicators(data);
                renderPatterns(data);
                renderICT(data);
                
            } catch (error) {
                console.error('Error:', error);
                document.getElementById('signalContainer').innerHTML = `
                    <div style="text-align: center; padding: 2rem; color: var(--danger);">
                        <i class="fas fa-exclamation-triangle" style="font-size: 2rem;"></i>
                        <div style="margin-top: 1rem;">Analysis failed. Please try again.</div>
                    </div>
                `;
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-search"></i> Analyze';
            }
        }
        
        function renderSignal(data) {
            const signal = data.signal;
            const signalClass = signal.signal.toLowerCase().includes('buy') ? 'buy' : 
                               signal.signal.toLowerCase().includes('sell') ? 'sell' : 'neutral';
            
            const confClass = `confidence-${signal.confidence_level.toLowerCase().replace('_', '-')}`;
            
            let html = `
                <div class="signal-box ${signalClass}">
                    <div class="signal-type ${signalClass}">${signal.signal.replace('_', ' ')}</div>
                    <div class="confidence-badge ${confClass}">
                        ${signal.confidence}% Confidence • ${signal.confidence_level.replace('_', ' ')}
                    </div>
                    <div class="recommendation">${signal.recommendation}</div>
                </div>
                
                <div style="font-size: 1.1rem; font-weight: 600; margin-bottom: 0.75rem;">
                    Price: $${data.price_data.current.toFixed(4)}
                    <span style="color: ${data.price_data.change_percent >= 0 ? 'var(--success)' : 'var(--danger)'}; margin-left: 1rem;">
                        ${data.price_data.change_percent >= 0 ? '▲' : '▼'} ${Math.abs(data.price_data.change_percent).toFixed(2)}%
                    </span>
                </div>
                
                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.75rem; font-size: 0.9rem;">
                    <div style="background: var(--bg-dark); padding: 0.75rem; border-radius: 6px;">
                        <div style="color: var(--text-muted);">EMA Signal</div>
                        <div style="font-weight: 600; margin-top: 0.3rem;">${signal.components.ema.signal}</div>
                    </div>
                    <div style="background: var(--bg-dark); padding: 0.75rem; border-radius: 6px;">
                        <div style="color: var(--text-muted);">RSI Signal</div>
                        <div style="font-weight: 600; margin-top: 0.3rem;">${signal.components.rsi.signal}</div>
                    </div>
                    <div style="background: var(--bg-dark); padding: 0.75rem; border-radius: 6px;">
                        <div style="color: var(--text-muted);">Pattern Signal</div>
                        <div style="font-weight: 600; margin-top: 0.3rem;">${signal.components.patterns.signal}</div>
                    </div>
                    <div style="background: var(--bg-dark); padding: 0.75rem; border-radius: 6px;">
                        <div style="color: var(--text-muted);">ICT Signal</div>
                        <div style="font-weight: 600; margin-top: 0.3rem;">${signal.components.ict.signal}</div>
                    </div>
                </div>
            `;
            
            document.getElementById('signalContainer').innerHTML = html;
        }
        
        function renderIndicators(data) {
            const ind = data.indicators;
            
            let rsiColor = 'var(--text)';
            if (ind.rsi > 70) rsiColor = 'var(--danger)';
            else if (ind.rsi < 30) rsiColor = 'var(--success)';
            
            const html = `
                <div class="indicators-grid">
                    <div class="indicator-item">
                        <div class="indicator-label">EMA 9</div>
                        <div class="indicator-value">${ind.ema_9 ? ind.ema_9.toFixed(2) : '-'}</div>
                    </div>
                    <div class="indicator-item">
                        <div class="indicator-label">EMA 21</div>
                        <div class="indicator-value">${ind.ema_21 ? ind.ema_21.toFixed(2) : '-'}</div>
                    </div>
                    <div class="indicator-item">
                        <div class="indicator-label">EMA 50</div>
                        <div class="indicator-value">${ind.ema_50 ? ind.ema_50.toFixed(2) : '-'}</div>
                    </div>
                    <div class="indicator-item">
                        <div class="indicator-label">RSI (14)</div>
                        <div class="indicator-value" style="color: ${rsiColor}">${ind.rsi ? ind.rsi.toFixed(1) : '-'}</div>
                    </div>
                    <div class="indicator-item" style="grid-column: span 2;">
                        <div class="indicator-label">Heikin Ashi Trend</div>
                        <div class="indicator-value" style="text-transform: capitalize; font-size: 1.1rem;">
                            ${ind.heikin_ashi_trend.replace('_', ' ')}
                        </div>
                    </div>
                </div>
            `;
            
            document.getElementById('indicatorsContainer').innerHTML = html;
        }
        
        function renderPatterns(data) {
            const patterns = data.patterns;
            
            if (!patterns || patterns.length === 0) {
                document.getElementById('patternsContainer').innerHTML = '<div style="text-align: center; padding: 2rem; color: var(--text-muted);">No patterns detected</div>';
                return;
            }
            
            let html = '<div class="pattern-list">';
            
            patterns.forEach(pattern => {
                html += `
                    <div class="pattern-item ${pattern.direction}">
                        <div class="pattern-header">
                            <div class="pattern-name">${pattern.name}</div>
                            <div class="pattern-confidence">${pattern.confidence}%</div>
                        </div>
                        <div class="pattern-desc">${pattern.description}</div>
                    </div>
                `;
            });
            
            html += '</div>';
            document.getElementById('patternsContainer').innerHTML = html;
        }
        
        function renderICT(data) {
            const ict = data.ict_analysis;
            
            let html = '<div class="ict-section">';
            
            html += `
                <div class="ict-item">
                    <span class="ict-label">Market Structure:</span>
                    <strong>${ict.market_structure.structure.replace('_', ' ').toUpperCase()}</strong>
                    (${ict.market_structure.strength})
                </div>
            `;
            
            if (ict.fair_value_gaps && ict.fair_value_gaps.length > 0) {
                html += `<div class="ict-item">
                    <span class="ict-label">Recent FVGs:</span>
                    ${ict.fair_value_gaps.length} detected
                </div>`;
            }
            
            if (ict.order_blocks && ict.order_blocks.length > 0) {
                html += `<div class="ict-item">
                    <span class="ict-label">Order Blocks:</span>
                    ${ict.order_blocks.length} detected
                </div>`;
            }
            
            html += '</div>';
            document.getElementById('ictContainer').innerHTML = html;
        }
        
        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            initTradingView('BTCUSDT');
        });
        
        document.getElementById('symbolInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') analyze();
        });
    </script>
</body>
</html>
    """

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    ) XXX
