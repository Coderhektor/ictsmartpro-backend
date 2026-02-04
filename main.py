"""
🚀 PROFESSIONAL TRADING BOT v2.0.0 - ADVANCED ANALYSIS
✅ TradingView Integration ✅ EMA Crossovers ✅ RSI ✅ Heikin Ashi
✅ 12 Candlestick Patterns ✅ ICT Market Structure ✅ Multi-Timeframe
✅ High-Confidence Signals ✅ Real-time Data ✅ Risk Management
✅ ONLY REAL DATA - NO SIMULATION
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

# ========== FASTAPI IMPORTS ==========
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, UploadFile, File
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# ========== YAPAY ZEKA BAĞLANTISI ==========
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
        def __init__(self):
            self.initialized = False
        
        async def initialize(self): 
            self.initialized = True
            return True
            
        async def get_quick_prediction(self, *args, **kwargs): 
            return {"error": "AI module not available"}
            
        async def get_comprehensive_analysis(self, *args, **kwargs):
            return {"error": "AI module not available"}
            
        async def chat_with_ai(self, *args, **kwargs):
            return {"error": "AI module not available"}
            
        async def analyze_trading_image(self, *args, **kwargs):
            return {"error": "AI module not available"}
    
    ai_service = DummyAIService()

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

# ========== REAL DATA FETCHER ==========
class RealDataFetcher:
    """SADECE gerçek veri alır - sentetik veri YOK"""
    
    BINANCE_API = "https://api.binance.com/api/v3"
    COINGECKO_API = "https://api.coingecko.com/api/v3"
    
    @staticmethod
    async def fetch_binance_klines(symbol: str, interval: str = "1h", limit: int = 100) -> Optional[List[Dict]]:
        """Fetch REAL candlestick data from Binance API"""
        try:
            # Validate symbol format
            sym = symbol.upper().strip()
            if not sym.endswith("USDT"):
                sym = f"{sym}USDT"
            
            async with aiohttp.ClientSession() as session:
                url = f"{RealDataFetcher.BINANCE_API}/klines"
                params = {
                    "symbol": sym,
                    "interval": interval,
                    "limit": min(limit, 1000)  # Binance max limit
                }
                
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        if not data:
                            logger.warning(f"No data returned for {sym}")
                            return None
                        
                        candles = []
                        for candle in data:
                            candles.append({
                                "timestamp": candle[0],
                                "open": float(candle[1]),
                                "high": float(candle[2]),
                                "low": float(candle[3]),
                                "close": float(candle[4]),
                                "volume": float(candle[5]),
                                "close_time": candle[6],
                                "quote_volume": float(candle[7]),
                                "trades": candle[8],
                                "taker_buy_base": float(candle[9]),
                                "taker_buy_quote": float(candle[10])
                            })
                        logger.info(f"✅ Fetched {len(candles)} real candles for {sym} ({interval})")
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
    async def fetch_current_price(symbol: str) -> Optional[Dict]:
        """Fetch current price from Binance"""
        try:
            sym = symbol.upper().strip()
            if not sym.endswith("USDT"):
                sym = f"{sym}USDT"
            
            async with aiohttp.ClientSession() as session:
                url = f"{RealDataFetcher.BINANCE_API}/ticker/24hr"
                params = {"symbol": sym}
                
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "symbol": data["symbol"],
                            "price": float(data["lastPrice"]),
                            "open": float(data["openPrice"]),
                            "high": float(data["highPrice"]),
                            "low": float(data["lowPrice"]),
                            "volume": float(data["volume"]),
                            "quoteVolume": float(data["quoteVolume"]),
                            "priceChange": float(data["priceChange"]),
                            "priceChangePercent": float(data["priceChangePercent"]),
                            "timestamp": data["closeTime"]
                        }
                    return None
        except Exception as e:
            logger.error(f"Error fetching current price: {e}")
            return None
    
    @staticmethod
    async def get_candles_with_retry(symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
        """Get real candles with retry logic"""
        max_retries = 3
        for retry in range(max_retries):
            candles = await RealDataFetcher.fetch_binance_klines(symbol, interval, limit)
            
            if candles and len(candles) >= 20:
                return candles
            
            logger.warning(f"⚠️ Retry {retry + 1}/{max_retries} for {symbol}")
            await asyncio.sleep(1 * (retry + 1))
        
        # Son çare: Coingecko API (sadece günlük veri)
        if interval in ["1d", "daily"]:
            try:
                candles = await RealDataFetcher._fetch_coingecko_data(symbol)
                if candles:
                    logger.info(f"✅ Using Coingecko data as fallback for {symbol}")
                    return candles
            except:
                pass
        
        logger.error(f"❌ Could not fetch real data for {symbol}")
        return []  # Boş liste döndür
    
    @staticmethod
    async def _fetch_coingecko_data(symbol: str) -> Optional[List[Dict]]:
        """Coingecko'dan yedek veri al (sadece günlük)"""
        try:
            sym = symbol.lower().strip()
            
            async with aiohttp.ClientSession() as session:
                # Önce ID'yi bul
                url = f"{RealDataFetcher.COINGECKO_API}/coins/list"
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        coins = await response.json()
                        coin_id = None
                        for coin in coins:
                            if coin["symbol"].lower() == sym.lower():
                                coin_id = coin["id"]
                                break
                        
                        if coin_id:
                            # Market chart verisi al
                            chart_url = f"{RealDataFetcher.COINGECKO_API}/coins/{coin_id}/market_chart"
                            params = {
                                "vs_currency": "usd",
                                "days": 90,
                                "interval": "daily"
                            }
                            async with session.get(chart_url, params=params, timeout=15) as chart_resp:
                                if chart_resp.status == 200:
                                    data = await chart_resp.json()
                                    prices = data.get("prices", [])
                                    
                                    candles = []
                                    for i in range(len(prices)):
                                        if i < len(prices) - 1:
                                            ts, price = prices[i]
                                            next_ts, next_price = prices[i + 1]
                                            candles.append({
                                                "timestamp": ts,
                                                "open": price,
                                                "high": max(price, next_price),
                                                "low": min(price, next_price),
                                                "close": next_price,
                                                "volume": 0  # Coingecko volume data separate
                                            })
                                    return candles[-100:] if len(candles) > 100 else candles
        except Exception as e:
            logger.warning(f"Coingecko fallback failed: {e}")
        
        return None

# ========== TECHNICAL INDICATORS ==========
class TechnicalIndicators:
    """Calculate technical indicators on REAL data"""
    
    @staticmethod
    def calculate_ema(candles: List[Dict], period: int) -> List[Optional[float]]:
        """Calculate Exponential Moving Average"""
        if len(candles) < period:
            return [None] * len(candles)
        
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
    def calculate_rsi(candles: List[Dict], period: int = 14) -> List[Optional[float]]:
        """Calculate Relative Strength Index"""
        if len(candles) < period + 1:
            return [None] * len(candles)
        
        closes = [c["close"] for c in candles]
        rsi_values = [None] * period
        
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        
        # First RSI
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        if avg_loss == 0:
            rsi_values.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))
        
        # Calculate remaining RSI values
        for i in range(period + 1, len(closes)):
            avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
            
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            
            rsi_values.append(rsi)
        
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
    
    @staticmethod
    def calculate_atr(candles: List[Dict], period: int = 14) -> List[Optional[float]]:
        """Calculate Average True Range"""
        if len(candles) < period + 1:
            return [None] * len(candles)
        
        tr_values = []
        for i in range(1, len(candles)):
            high = candles[i]["high"]
            low = candles[i]["low"]
            prev_close = candles[i-1]["close"]
            
            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)
            tr = max(tr1, tr2, tr3)
            tr_values.append(tr)
        
        atr_values = [None] * period
        # First ATR is average of first 'period' TR values
        atr = sum(tr_values[:period]) / period
        atr_values.append(atr)
        
        # Calculate subsequent ATR values
        for i in range(period + 1, len(candles)):
            atr = (atr * (period - 1) + tr_values[i-1]) / period
            atr_values.append(atr)
        
        return atr_values
    
    @staticmethod
    def calculate_macd(candles: List[Dict]) -> Dict[str, List[Optional[float]]]:
        """Calculate MACD indicator"""
        if len(candles) < 26:
            return {"macd": [None]*len(candles), "signal": [None]*len(candles), "histogram": [None]*len(candles)}
        
        closes = [c["close"] for c in candles]
        
        # Calculate EMAs
        ema12 = TechnicalIndicators._calculate_simple_ema(closes, 12)
        ema26 = TechnicalIndicators._calculate_simple_ema(closes, 26)
        
        # MACD line
        macd_line = []
        for i in range(len(closes)):
            if ema12[i] is not None and ema26[i] is not None:
                macd_line.append(ema12[i] - ema26[i])
            else:
                macd_line.append(None)
        
        # Signal line (EMA of MACD)
        signal_line = TechnicalIndicators._calculate_simple_ema(macd_line, 9, True)
        
        # Histogram
        histogram = []
        for i in range(len(closes)):
            if macd_line[i] is not None and signal_line[i] is not None:
                histogram.append(macd_line[i] - signal_line[i])
            else:
                histogram.append(None)
        
        return {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": histogram
        }
    
    @staticmethod
    def _calculate_simple_ema(values: List[float], period: int, allow_none: bool = False) -> List[Optional[float]]:
        """Helper function for EMA calculation"""
        if len(values) < period:
            return [None] * len(values)
        
        result = [None] * (period - 1)
        multiplier = 2 / (period + 1)
        
        # Check if we have enough valid values
        if allow_none:
            valid_values = [v for v in values[:period] if v is not None]
            if len(valid_values) < period:
                return [None] * len(values)
        
        # First EMA is SMA
        sma = sum(values[:period]) / period
        result.append(sma)
        
        # Calculate EMA for rest
        for i in range(period, len(values)):
            if values[i] is None:
                result.append(None)
            else:
                ema_value = (values[i] - result[-1]) * multiplier + result[-1]
                result.append(ema_value)
        
        return result

# ========== CANDLESTICK PATTERN DETECTOR ==========
class CandlestickPatternDetector:
    """Detect 12 major candlestick patterns on REAL data"""
    
    @staticmethod
    def is_bullish_engulfing(prev: Dict, curr: Dict) -> bool:
        """Bullish Engulfing Pattern"""
        if prev["close"] >= prev["open"] or curr["close"] <= curr["open"]:
            return False
        
        prev_body = abs(prev["close"] - prev["open"])
        curr_body = abs(curr["close"] - curr["open"])
        
        return (curr["open"] < prev["close"] and
                curr["close"] > prev["open"] and
                curr_body > prev_body * 1.2)
    
    @staticmethod
    def is_bearish_engulfing(prev: Dict, curr: Dict) -> bool:
        """Bearish Engulfing Pattern"""
        if prev["close"] <= prev["open"] or curr["close"] >= curr["open"]:
            return False
        
        prev_body = abs(prev["close"] - prev["open"])
        curr_body = abs(curr["close"] - curr["open"])
        
        return (curr["open"] > prev["close"] and
                curr["close"] < prev["open"] and
                curr_body > prev_body * 1.2)
    
    @staticmethod
    def is_hammer(candle: Dict) -> bool:
        """Hammer Pattern (Bullish Reversal)"""
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        total_range = candle["high"] - candle["low"]
        
        if total_range == 0:
            return False
        
        body_ratio = body / total_range
        lower_ratio = lower_shadow / total_range
        upper_ratio = upper_shadow / total_range
        
        return (lower_ratio > 0.6 and
                upper_ratio < 0.1 and
                body_ratio < 0.3 and
                candle["close"] > candle["open"])  # Bullish hammer
    
    @staticmethod
    def is_hanging_man(candle: Dict) -> bool:
        """Hanging Man Pattern (Bearish Reversal)"""
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        total_range = candle["high"] - candle["low"]
        
        if total_range == 0:
            return False
        
        body_ratio = body / total_range
        lower_ratio = lower_shadow / total_range
        upper_ratio = upper_shadow / total_range
        
        return (lower_ratio > 0.6 and
                upper_ratio < 0.1 and
                body_ratio < 0.3 and
                candle["close"] < candle["open"])  # Bearish hanging man
    
    @staticmethod
    def is_shooting_star(candle: Dict) -> bool:
        """Shooting Star Pattern (Bearish Reversal)"""
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        total_range = candle["high"] - candle["low"]
        
        if total_range == 0:
            return False
        
        body_ratio = body / total_range
        upper_ratio = upper_shadow / total_range
        lower_ratio = lower_shadow / total_range
        
        return (upper_ratio > 0.6 and
                lower_ratio < 0.1 and
                body_ratio < 0.3)
    
    @staticmethod
    def is_doji(candle: Dict) -> bool:
        """Doji Pattern (Indecision)"""
        body = abs(candle["close"] - candle["open"])
        total_range = candle["high"] - candle["low"]
        
        if total_range == 0:
            return False
        
        body_ratio = body / total_range
        return body_ratio < 0.1
    
    @staticmethod
    def is_morning_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Morning Star Pattern (Bullish Reversal)"""
        if not (c1["close"] < c1["open"] and c3["close"] > c3["open"]):
            return False
        
        c1_body = abs(c1["close"] - c1["open"])
        c2_body = abs(c2["close"] - c2["open"])
        c3_body = abs(c3["close"] - c3["open"])
        
        # Middle candle should be small
        if c2_body > c1_body * 0.5:
            return False
        
        # Gap down then gap up
        has_gap_down = c2["high"] < c1["low"]
        has_gap_up = c3["low"] > c2["high"]
        
        return has_gap_down and has_gap_up and c3["close"] > (c1["open"] + c1["close"]) / 2
    
    @staticmethod
    def is_evening_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Evening Star Pattern (Bearish Reversal)"""
        if not (c1["close"] > c1["open"] and c3["close"] < c3["open"]):
            return False
        
        c1_body = abs(c1["close"] - c1["open"])
        c2_body = abs(c2["close"] - c2["open"])
        c3_body = abs(c3["close"] - c3["open"])
        
        # Middle candle should be small
        if c2_body > c1_body * 0.5:
            return False
        
        # Gap up then gap down
        has_gap_up = c2["low"] > c1["high"]
        has_gap_down = c3["high"] < c2["low"]
        
        return has_gap_up and has_gap_down and c3["close"] < (c1["open"] + c1["close"]) / 2
    
    @staticmethod
    def is_three_white_soldiers(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Three White Soldiers (Strong Bullish)"""
        if not (c1["close"] > c1["open"] and c2["close"] > c2["open"] and c3["close"] > c3["open"]):
            return False
        
        # Each candle should close higher than previous
        if not (c2["close"] > c1["close"] and c3["close"] > c2["close"]):
            return False
        
        # Bodies should be reasonably sized
        c1_body = c1["close"] - c1["open"]
        c2_body = c2["close"] - c2["open"]
        c3_body = c3["close"] - c3["open"]
        
        avg_body = (c1_body + c2_body + c3_body) / 3
        min_body_threshold = avg_body * 0.5
        
        return (c1_body > min_body_threshold and
                c2_body > min_body_threshold and
                c3_body > min_body_threshold)
    
    @staticmethod
    def is_three_black_crows(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Three Black Crows (Strong Bearish)"""
        if not (c1["close"] < c1["open"] and c2["close"] < c2["open"] and c3["close"] < c3["open"]):
            return False
        
        # Each candle should close lower than previous
        if not (c2["close"] < c1["close"] and c3["close"] < c2["close"]):
            return False
        
        # Bodies should be reasonably sized
        c1_body = c1["open"] - c1["close"]
        c2_body = c2["open"] - c2["close"]
        c3_body = c3["open"] - c3["close"]
        
        avg_body = (c1_body + c2_body + c3_body) / 3
        min_body_threshold = avg_body * 0.5
        
        return (c1_body > min_body_threshold and
                c2_body > min_body_threshold and
                c3_body > min_body_threshold)
    
    @staticmethod
    def is_bullish_harami(prev: Dict, curr: Dict) -> bool:
        """Bullish Harami Pattern"""
        if not (prev["close"] < prev["open"] and curr["close"] > curr["open"]):
            return False
        
        return (curr["open"] > prev["close"] and
                curr["close"] < prev["open"])
    
    @staticmethod
    def is_bearish_harami(prev: Dict, curr: Dict) -> bool:
        """Bearish Harami Pattern"""
        if not (prev["close"] > prev["open"] and curr["close"] < curr["open"]):
            return False
        
        return (curr["open"] < prev["close"] and
                curr["close"] > prev["open"])
    
    @staticmethod
    def detect_all_patterns(candles: List[Dict]) -> List[Dict]:
        """Detect all patterns in the candle data"""
        patterns = []
        
        if len(candles) < 3:
            return patterns
        
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
        
        # Sort by position
        patterns.sort(key=lambda x: x["position"])
        return patterns

# ========== ICT ANALYZER ==========
class ICTAnalyzer:
    """Inner Circle Trader Market Structure Analysis on REAL data"""
    
    @staticmethod
    def detect_fair_value_gaps(candles: List[Dict]) -> List[Dict]:
        """Detect Fair Value Gaps (FVG)"""
        fvgs = []
        
        for i in range(2, len(candles)):
            prev = candles[i-2]
            curr = candles[i]
            
            # Bullish FVG (previous high < current low)
            if prev["high"] < curr["low"]:
                gap_size = curr["low"] - prev["high"]
                gap_percent = (gap_size / prev["close"]) * 100
                
                fvgs.append({
                    "type": "bullish",
                    "start": prev["high"],
                    "end": curr["low"],
                    "size": gap_size,
                    "size_percent": round(gap_percent, 2),
                    "position": i,
                    "strength": "strong" if gap_percent > 0.5 else "moderate",
                    "description": f"Bullish FVG: {prev['high']:.4f} to {curr['low']:.4f}"
                })
            
            # Bearish FVG (previous low > current high)
            if prev["low"] > curr["high"]:
                gap_size = prev["low"] - curr["high"]
                gap_percent = (gap_size / prev["close"]) * 100
                
                fvgs.append({
                    "type": "bearish",
                    "start": curr["high"],
                    "end": prev["low"],
                    "size": gap_size,
                    "size_percent": round(gap_percent, 2),
                    "position": i,
                    "strength": "strong" if gap_percent > 0.5 else "moderate",
                    "description": f"Bearish FVG: {curr['high']:.4f} to {prev['low']:.4f}"
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
                
                move_size = candles[i]["close"] - candles[i-1]["low"]
                block_size = candles[i-1]["high"] - candles[i-1]["low"]
                strength_ratio = move_size / block_size if block_size > 0 else 0
                
                order_blocks.append({
                    "type": "bullish",
                    "high": candles[i-1]["high"],
                    "low": candles[i-1]["low"],
                    "position": i-1,
                    "strength": "strong" if strength_ratio > 2 else "moderate",
                    "strength_ratio": round(strength_ratio, 2),
                    "description": f"Bullish OB: {candles[i-1]['low']:.4f} - {candles[i-1]['high']:.4f}"
                })
            
            # Bearish Order Block (last bullish candle before strong move down)
            if (candles[i-1]["close"] > candles[i-1]["open"] and
                candles[i]["close"] < candles[i]["open"] and
                candles[i]["close"] < candles[i-1]["low"]):
                
                move_size = candles[i-1]["high"] - candles[i]["close"]
                block_size = candles[i-1]["high"] - candles[i-1]["low"]
                strength_ratio = move_size / block_size if block_size > 0 else 0
                
                order_blocks.append({
                    "type": "bearish",
                    "high": candles[i-1]["high"],
                    "low": candles[i-1]["low"],
                    "position": i-1,
                    "strength": "strong" if strength_ratio > 2 else "moderate",
                    "strength_ratio": round(strength_ratio, 2),
                    "description": f"Bearish OB: {candles[i-1]['low']:.4f} - {candles[i-1]['high']:.4f}"
                })
        
        return order_blocks
    
    @staticmethod
    def analyze_market_structure(candles: List[Dict]) -> Dict:
        """Analyze overall market structure"""
        if len(candles) < 20:
            return {
                "structure": "insufficient_data",
                "strength": "weak",
                "description": "Need at least 20 candles for structure analysis"
            }
        
        recent_candles = candles[-20:]
        highs = [c["high"] for c in recent_candles]
        lows = [c["low"] for c in recent_candles]
        
        # Higher highs and higher lows = bullish
        higher_highs = 0
        higher_lows = 0
        lower_highs = 0
        lower_lows = 0
        
        for i in range(1, len(highs)):
            if highs[i] > highs[i-1]:
                higher_highs += 1
            elif highs[i] < highs[i-1]:
                lower_highs += 1
            
            if lows[i] > lows[i-1]:
                higher_lows += 1
            elif lows[i] < lows[i-1]:
                lower_lows += 1
        
        # Determine structure
        if higher_highs >= 15 and higher_lows >= 15:
            structure = "strong_bullish_trend"
            strength = "very_strong"
        elif higher_highs >= 12 and higher_lows >= 12:
            structure = "bullish_trend"
            strength = "strong"
        elif lower_highs >= 15 and lower_lows >= 15:
            structure = "strong_bearish_trend"
            strength = "very_strong"
        elif lower_highs >= 12 and lower_lows >= 12:
            structure = "bearish_trend"
            strength = "strong"
        elif higher_highs > lower_highs and higher_lows > lower_lows:
            structure = "mildly_bullish"
            strength = "moderate"
        elif lower_highs > higher_highs and lower_lows > higher_lows:
            structure = "mildly_bearish"
            strength = "moderate"
        else:
            # Check if highs and lows are consolidating
            max_high = max(highs)
            min_low = min(lows)
            avg_range = (max_high - min_low) / min_low * 100
            
            if avg_range < 2:  # Very narrow range
                structure = "tight_consolidation"
                strength = "very_weak"
            elif avg_range < 5:  # Moderate range
                structure = "consolidation"
                strength = "weak"
            else:
                structure = "choppy"
                strength = "weak"
        
        # Current swing detection
        current_price = candles[-1]["close"]
        swing_high = max(highs[-5:])
        swing_low = min(lows[-5:])
        
        if current_price > swing_high * 0.95:
            swing_status = "testing_resistance"
        elif current_price < swing_low * 1.05:
            swing_status = "testing_support"
        else:
            swing_status = "mid_range"
        
        return {
            "structure": structure,
            "strength": strength,
            "higher_highs": higher_highs,
            "higher_lows": higher_lows,
            "lower_highs": lower_highs,
            "lower_lows": lower_lows,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "swing_status": swing_status,
            "description": f"Market is {structure.replace('_', ' ')} with {strength.replace('_', ' ')} strength"
        }

# ========== SIGNAL GENERATOR ==========
class SignalGenerator:
    """Generate trading signals with confidence levels from REAL data"""
    
    @staticmethod
    def calculate_ema_signal(candles: List[Dict], ema_fast: List[Optional[float]], ema_slow: List[Optional[float]]) -> Dict:
        """Calculate signal from EMA crossover"""
        if (not ema_fast or not ema_slow or 
            len(ema_fast) < 2 or len(ema_slow) < 2 or
            ema_fast[-1] is None or ema_fast[-2] is None or
            ema_slow[-1] is None or ema_slow[-2] is None):
            
            return {
                "signal": "NEUTRAL", 
                "confidence": 0, 
                "reason": "insufficient_data",
                "description": "Not enough data for EMA analysis"
            }
        
        # Current and previous values
        fast_curr = ema_fast[-1]
        fast_prev = ema_fast[-2]
        slow_curr = ema_slow[-1]
        slow_prev = ema_slow[-2]
        current_price = candles[-1]["close"]
        
        # Golden Cross (bullish) - fast crosses above slow
        if fast_prev <= slow_prev and fast_curr > slow_curr:
            distance = abs(fast_curr - slow_curr) / slow_curr * 100
            confidence = min(90, 70 + distance * 10)
            
            # Check if price confirms
            price_above = current_price > fast_curr
            confirmation = "price_confirms" if price_above else "price_lags"
            
            return {
                "signal": "BUY",
                "confidence": confidence,
                "reason": "golden_cross",
                "confirmation": confirmation,
                "description": f"EMA {len(ema_fast)-len([x for x in ema_fast if x is None])} crossed above EMA {len(ema_slow)-len([x for x in ema_slow if x is None])} (Golden Cross)"
            }
        
        # Death Cross (bearish) - fast crosses below slow
        if fast_prev >= slow_prev and fast_curr < slow_curr:
            distance = abs(fast_curr - slow_curr) / slow_curr * 100
            confidence = min(90, 70 + distance * 10)
            
            # Check if price confirms
            price_below = current_price < fast_curr
            confirmation = "price_confirms" if price_below else "price_lags"
            
            return {
                "signal": "SELL",
                "confidence": confidence,
                "reason": "death_cross",
                "confirmation": confirmation,
                "description": f"EMA {len(ema_fast)-len([x for x in ema_fast if x is None])} crossed below EMA {len(ema_slow)-len([x for x in ema_slow if x is None])} (Death Cross)"
            }
        
        # Trending analysis
        if fast_curr > slow_curr:
            distance = (fast_curr - slow_curr) / slow_curr * 100
            price_distance = (current_price - fast_curr) / fast_curr * 100
            
            if distance > 2:
                if price_distance > 0:
                    confidence = min(85, 60 + distance * 5)
                    return {
                        "signal": "BUY",
                        "confidence": confidence,
                        "reason": "strong_uptrend",
                        "description": f"Strong uptrend (EMA distance: {distance:.2f}%, Price above EMA: {price_distance:.2f}%)"
                    }
                else:
                    confidence = min(75, 50 + distance * 3)
                    return {
                        "signal": "NEUTRAL",
                        "confidence": confidence,
                        "reason": "uptrend_pullback",
                        "description": f"Uptrend with pullback (EMA distance: {distance:.2f}%, Price below EMA: {abs(price_distance):.2f}%)"
                    }
            else:
                return {
                    "signal": "NEUTRAL",
                    "confidence": 40,
                    "reason": "weak_uptrend",
                    "description": "Weak uptrend, needs confirmation"
                }
        else:
            distance = (slow_curr - fast_curr) / slow_curr * 100
            price_distance = (fast_curr - current_price) / fast_curr * 100
            
            if distance > 2:
                if price_distance > 0:
                    confidence = min(85, 60 + distance * 5)
                    return {
                        "signal": "SELL",
                        "confidence": confidence,
                        "reason": "strong_downtrend",
                        "description": f"Strong downtrend (EMA distance: {distance:.2f}%, Price below EMA: {price_distance:.2f}%)"
                    }
                else:
                    confidence = min(75, 50 + distance * 3)
                    return {
                        "signal": "NEUTRAL",
                        "confidence": confidence,
                        "reason": "downtrend_bounce",
                        "description": f"Downtrend with bounce (EMA distance: {distance:.2f}%, Price above EMA: {abs(price_distance):.2f}%)"
                    }
            else:
                return {
                    "signal": "NEUTRAL",
                    "confidence": 40,
                    "reason": "weak_downtrend",
                    "description": "Weak downtrend, needs confirmation"
                }
    
    @staticmethod
    def calculate_rsi_signal(candles: List[Dict], rsi: List[Optional[float]]) -> Dict:
        """Calculate signal from RSI"""
        if (not rsi or len(rsi) < 2 or 
            rsi[-1] is None or rsi[-2] is None):
            
            return {
                "signal": "NEUTRAL", 
                "confidence": 0, 
                "reason": "insufficient_data",
                "description": "Not enough data for RSI analysis"
            }
        
        current_rsi = rsi[-1]
        prev_rsi = rsi[-2]
        current_price = candles[-1]["close"]
        prev_price = candles[-2]["close"] if len(candles) >= 2 else current_price
        
        # Oversold conditions (< 30)
        if current_rsi < 30:
            # Bullish divergence check
            if current_rsi > prev_rsi and current_price < prev_price:
                return {
                    "signal": "STRONG_BUY",
                    "confidence": 85,
                    "reason": "oversold_divergence",
                    "description": f"Bullish divergence in oversold zone (RSI: {current_rsi:.1f})"
                }
            
            # Simple oversold
            if current_rsi < 25:
                confidence = 80
                signal = "STRONG_BUY"
            else:
                confidence = 70
                signal = "BUY"
            
            return {
                "signal": signal,
                "confidence": confidence,
                "reason": "oversold",
                "description": f"Oversold condition (RSI: {current_rsi:.1f})"
            }
        
        # Overbought conditions (> 70)
        if current_rsi > 70:
            # Bearish divergence check
            if current_rsi < prev_rsi and current_price > prev_price:
                return {
                    "signal": "STRONG_SELL",
                    "confidence": 85,
                    "reason": "overbought_divergence",
                    "description": f"Bearish divergence in overbought zone (RSI: {current_rsi:.1f})"
                }
            
            # Simple overbought
            if current_rsi > 75:
                confidence = 80
                signal = "STRONG_SELL"
            else:
                confidence = 70
                signal = "SELL"
            
            return {
                "signal": signal,
                "confidence": confidence,
                "reason": "overbought",
                "description": f"Overbought condition (RSI: {current_rsi:.1f})"
            }
        
        # Neutral zone analysis
        if 40 <= current_rsi <= 60:
            # RSI trending up in neutral zone
            if current_rsi > prev_rsi and current_rsi > 50:
                return {
                    "signal": "BUY",
                    "confidence": 60,
                    "reason": "neutral_bullish",
                    "description": f"Bullish momentum in neutral zone (RSI: {current_rsi:.1f}, Trend: up)"
                }
            # RSI trending down in neutral zone
            elif current_rsi < prev_rsi and current_rsi < 50:
                return {
                    "signal": "SELL",
                    "confidence": 60,
                    "reason": "neutral_bearish",
                    "description": f"Bearish momentum in neutral zone (RSI: {current_rsi:.1f}, Trend: down)"
                }
            else:
                return {
                    "signal": "NEUTRAL",
                    "confidence": 50,
                    "reason": "neutral_balanced",
                    "description": f"Balanced in neutral zone (RSI: {current_rsi:.1f})"
                }
        
        # Bullish zone (60-70)
        if 60 < current_rsi <= 70:
            if current_rsi > prev_rsi:
                return {
                    "signal": "BUY",
                    "confidence": 65,
                    "reason": "bullish_zone_up",
                    "description": f"Strong bullish momentum (RSI: {current_rsi:.1f})"
                }
            else:
                return {
                    "signal": "NEUTRAL",
                    "confidence": 55,
                    "reason": "bullish_zone_pullback",
                    "description": f"Bullish zone pullback (RSI: {current_rsi:.1f})"
                }
        
        # Bearish zone (30-40)
        if 30 <= current_rsi < 40:
            if current_rsi < prev_rsi:
                return {
                    "signal": "SELL",
                    "confidence": 65,
                    "reason": "bearish_zone_down",
                    "description": f"Strong bearish momentum (RSI: {current_rsi:.1f})"
                }
            else:
                return {
                    "signal": "NEUTRAL",
                    "confidence": 55,
                    "reason": "bearish_zone_bounce",
                    "description": f"Bearish zone bounce (RSI: {current_rsi:.1f})"
                }
        
        return {
            "signal": "NEUTRAL",
            "confidence": 45,
            "reason": "unclear",
            "description": f"Unclear RSI signal (RSI: {current_rsi:.1f})"
        }
    
    @staticmethod
    def calculate_pattern_signal(patterns: List[Dict]) -> Dict:
        """Calculate signal from candlestick patterns"""
        if not patterns:
            return {
                "signal": "NEUTRAL", 
                "confidence": 0, 
                "reason": "no_patterns",
                "description": "No candlestick patterns detected"
            }
        
        # Get recent patterns (last 5 candles)
        recent_patterns = [p for p in patterns if p.get("position", 0) >= len(patterns) - 5]
        
        if not recent_patterns:
            return {
                "signal": "NEUTRAL",
                "confidence": 30,
                "reason": "no_recent_patterns",
                "description": "No recent patterns detected"
            }
        
        # Calculate weighted scores
        bullish_score = 0
        bearish_score = 0
        neutral_score = 0
        
        for pattern in recent_patterns:
            weight = pattern.get("confidence", 50) / 100
            direction = pattern.get("direction", "neutral")
            
            if direction == "bullish":
                bullish_score += weight
            elif direction == "bearish":
                bearish_score += weight
            else:
                neutral_score += weight
        
        total_score = bullish_score + bearish_score + neutral_score
        
        if total_score == 0:
            return {
                "signal": "NEUTRAL",
                "confidence": 30,
                "reason": "neutral_patterns",
                "description": "Only neutral patterns detected",
                "patterns": recent_patterns
            }
        
        bullish_ratio = bullish_score / total_score
        bearish_ratio = bearish_score / total_score
        
        # High confidence patterns
        strong_patterns = [p for p in recent_patterns if p.get("confidence", 0) >= 80]
        strong_bullish = [p for p in strong_patterns if p.get("direction") == "bullish"]
        strong_bearish = [p for p in strong_patterns if p.get("direction") == "bearish"]
        
        # Determine signal based on strongest evidence
        if strong_bullish and not strong_bearish:
            max_conf = max(p["confidence"] for p in strong_bullish)
            return {
                "signal": "STRONG_BUY" if max_conf >= 90 else "BUY",
                "confidence": min(95, max_conf),
                "reason": "strong_bullish_patterns",
                "description": f"{len(strong_bullish)} strong bullish pattern(s) detected",
                "patterns": recent_patterns
            }
        
        if strong_bearish and not strong_bullish:
            max_conf = max(p["confidence"] for p in strong_bearish)
            return {
                "signal": "STRONG_SELL" if max_conf >= 90 else "SELL",
                "confidence": min(95, max_conf),
                "reason": "strong_bearish_patterns",
                "description": f"{len(strong_bearish)} strong bearish pattern(s) detected",
                "patterns": recent_patterns
            }
        
        # Mixed strong patterns
        if strong_bullish and strong_bearish:
            return {
                "signal": "NEUTRAL",
                "confidence": 50,
                "reason": "conflicting_strong_patterns",
                "description": f"Conflicting signals: {len(strong_bullish)} bullish vs {len(strong_bearish)} bearish strong patterns",
                "patterns": recent_patterns
            }
        
        # No strong patterns, use ratio
        if bullish_ratio > 0.7:
            avg_conf = sum(p.get("confidence", 50) for p in recent_patterns if p.get("direction") == "bullish") / max(1, len([p for p in recent_patterns if p.get("direction") == "bullish"]))
            return {
                "signal": "BUY",
                "confidence": min(80, avg_conf),
                "reason": "bullish_patterns",
                "description": f"{len([p for p in recent_patterns if p.get('direction') == 'bullish'])} bullish pattern(s) detected",
                "patterns": recent_patterns
            }
        
        if bearish_ratio > 0.7:
            avg_conf = sum(p.get("confidence", 50) for p in recent_patterns if p.get("direction") == "bearish") / max(1, len([p for p in recent_patterns if p.get("direction") == "bearish"]))
            return {
                "signal": "SELL",
                "confidence": min(80, avg_conf),
                "reason": "bearish_patterns",
                "description": f"{len([p for p in recent_patterns if p.get('direction') == 'bearish'])} bearish pattern(s) detected",
                "patterns": recent_patterns
            }
        
        return {
            "signal": "NEUTRAL",
            "confidence": 50,
            "reason": "mixed_patterns",
            "description": f"Mixed patterns: {len([p for p in recent_patterns if p.get('direction') == 'bullish'])} bullish, {len([p for p in recent_patterns if p.get('direction') == 'bearish'])} bearish, {len([p for p in recent_patterns if p.get('direction') == 'neutral'])} neutral",
            "patterns": recent_patterns
        }
    
    @staticmethod
    def calculate_ict_signal(candles: List[Dict], fvgs: List[Dict], order_blocks: List[Dict], market_structure: Dict) -> Dict:
        """Calculate signal from ICT analysis"""
        if len(candles) < 20:
            return {
                "signal": "NEUTRAL",
                "confidence": 0,
                "reason": "insufficient_data",
                "description": "Need at least 20 candles for ICT analysis"
            }
        
        score = 0
        reasons = []
        current_price = candles[-1]["close"]
        
        # 1. Market Structure (40 points max)
        structure = market_structure.get("structure", "")
        strength = market_structure.get("strength", "")
        
        if "bullish" in structure:
            if "strong" in structure or "very_strong" in strength:
                score += 40
                reasons.append("Very strong bullish structure")
            else:
                score += 25
                reasons.append("Bullish market structure")
        elif "bearish" in structure:
            if "strong" in structure or "very_strong" in strength:
                score -= 40
                reasons.append("Very strong bearish structure")
            else:
                score -= 25
                reasons.append("Bearish market structure")
        
        # 2. Fair Value Gaps (20 points max each)
        recent_fvgs = [f for f in fvgs if f.get("position", 0) >= len(candles) - 10]
        
        for fvg in recent_fvgs:
            fvg_type = fvg.get("type", "")
            fvg_strength = fvg.get("strength", "")
            
            if fvg_type == "bullish":
                # Check if price is near FVG for potential fill
                fvg_start = fvg.get("start", 0)
                fvg_end = fvg.get("end", 0)
                
                if current_price <= fvg_end:  # Price in or below bullish FVG
                    if fvg_strength == "strong":
                        score += 20
                        reasons.append("Price in strong bullish FVG")
                    else:
                        score += 12
                        reasons.append("Price in bullish FVG")
                elif fvg_end < current_price <= fvg_end * 1.02:  # Near bullish FVG
                    score += 8
                    reasons.append("Price near bullish FVG")
            
            elif fvg_type == "bearish":
                # Check if price is near FVG for potential fill
                fvg_start = fvg.get("start", 0)
                fvg_end = fvg.get("end", 0)
                
                if current_price >= fvg_end:  # Price in or above bearish FVG
                    if fvg_strength == "strong":
                        score -= 20
                        reasons.append("Price in strong bearish FVG")
                    else:
                        score -= 12
                        reasons.append("Price in bearish FVG")
                elif fvg_end > current_price >= fvg_end * 0.98:  # Near bearish FVG
                    score -= 8
                    reasons.append("Price near bearish FVG")
        
        # 3. Order Blocks (25 points max each)
        recent_obs = [ob for ob in order_blocks if ob.get("position", 0) >= len(candles) - 10]
        
        for ob in recent_obs:
            ob_type = ob.get("type", "")
            ob_strength = ob.get("strength", "")
            ob_high = ob.get("high", 0)
            ob_low = ob.get("low", 0)
            
            if ob_type == "bullish":
                # Check if price is reacting to bullish OB
                if ob_low <= current_price <= ob_high:  # Price in bullish OB
                    if ob_strength == "strong":
                        score += 25
                        reasons.append("Price in strong bullish Order Block")
                    else:
                        score += 15
                        reasons.append("Price in bullish Order Block")
                elif ob_high < current_price <= ob_high * 1.02:  # Just above bullish OB
                    score += 10
                    reasons.append("Price above bullish Order Block (support)")
                elif ob_low * 0.98 <= current_price < ob_low:  # Just below bullish OB
                    score += 5
                    reasons.append("Price below bullish Order Block (potential rejection)")
            
            elif ob_type == "bearish":
                # Check if price is reacting to bearish OB
                if ob_low <= current_price <= ob_high:  # Price in bearish OB
                    if ob_strength == "strong":
                        score -= 25
                        reasons.append("Price in strong bearish Order Block")
                    else:
                        score -= 15
                        reasons.append("Price in bearish Order Block")
                elif ob_low * 0.98 <= current_price < ob_low:  # Just below bearish OB
                    score -= 10
                    reasons.append("Price below bearish Order Block (resistance)")
                elif ob_high < current_price <= ob_high * 1.02:  # Just above bearish OB
                    score -= 5
                    reasons.append("Price above bearish Order Block (potential rejection)")
        
        # 4. Swing points analysis
        swing_status = market_structure.get("swing_status", "")
        swing_high = market_structure.get("swing_high", current_price)
        swing_low = market_structure.get("swing_low", current_price)
        
        if swing_status == "testing_resistance":
            resistance_distance = (swing_high - current_price) / swing_high * 100
            if resistance_distance < 1:  # Very close to resistance
                score -= 15
                reasons.append("Testing major resistance")
            else:
                score -= 8
                reasons.append("Approaching resistance")
        
        elif swing_status == "testing_support":
            support_distance = (current_price - swing_low) / current_price * 100
            if support_distance < 1:  # Very close to support
                score += 15
                reasons.append("Testing major support")
            else:
                score += 8
                reasons.append("Approaching support")
        
        # Normalize score and determine signal
        max_possible_score = 120  # Approximate max
        confidence = min(95, (abs(score) / max_possible_score) * 100)
        
        if score > 60:
            signal = "STRONG_BUY"
        elif score > 30:
            signal = "BUY"
        elif score < -60:
            signal = "STRONG_SELL"
        elif score < -30:
            signal = "SELL"
        else:
            signal = "NEUTRAL"
        
        return {
            "signal": signal,
            "confidence": round(confidence, 1),
            "score": round(score, 1),
            "reasons": reasons,
            "description": " | ".join(reasons) if reasons else "No clear ICT signals",
            "analysis": {
                "market_structure": structure,
                "recent_fvgs": len(recent_fvgs),
                "recent_order_blocks": len(recent_obs),
                "swing_status": swing_status
            }
        }
    
    @staticmethod
    def calculate_heikin_ashi_signal(ha_candles: List[Dict]) -> Dict:
        """Calculate signal from Heikin Ashi candles"""
        if len(ha_candles) < 3:
            return {
                "signal": "NEUTRAL",
                "confidence": 0,
                "reason": "insufficient_data",
                "description": "Need at least 3 Heikin Ashi candles"
            }
        
        # Analyze last 5 HA candles
        recent_ha = ha_candles[-5:]
        
        # Count bullish and bearish candles
        bullish_count = sum(1 for c in recent_ha if c["close"] > c["open"])
        bearish_count = len(recent_ha) - bullish_count
        
        # Check for strong trends
        if bullish_count >= 4:
            # All/most candles bullish
            bodies = [c["close"] - c["open"] for c in recent_ha if c["close"] > c["open"]]
            avg_body = sum(bodies) / len(bodies) if bodies else 0
            
            # Check if bodies are increasing (strong trend)
            if len(bodies) >= 3 and bodies[-1] > bodies[-2] > bodies[-3]:
                return {
                    "signal": "STRONG_BUY",
                    "confidence": 85,
                    "reason": "strong_ha_uptrend",
                    "description": "Very strong Heikin Ashi uptrend with increasing bodies"
                }
            else:
                return {
                    "signal": "BUY",
                    "confidence": 75,
                    "reason": "ha_uptrend",
                    "description": f"Heikin Ashi uptrend ({bullish_count}/5 bullish candles)"
                }
        
        elif bearish_count >= 4:
            # All/most candles bearish
            bodies = [c["open"] - c["close"] for c in recent_ha if c["close"] < c["open"]]
            avg_body = sum(bodies) / len(bodies) if bodies else 0
            
            # Check if bodies are increasing (strong trend)
            if len(bodies) >= 3 and bodies[-1] > bodies[-2] > bodies[-3]:
                return {
                    "signal": "STRONG_SELL",
                    "confidence": 85,
                    "reason": "strong_ha_downtrend",
                    "description": "Very strong Heikin Ashi downtrend with increasing bodies"
                }
            else:
                return {
                    "signal": "SELL",
                    "confidence": 75,
                    "reason": "ha_downtrend",
                    "description": f"Heikin Ashi downtrend ({bearish_count}/5 bearish candles)"
                }
        
        # Check for doji-like candles (indecision)
        recent_candle = recent_ha[-1]
        body = abs(recent_candle["close"] - recent_candle["open"])
        total_range = recent_candle["high"] - recent_candle["low"]
        
        if total_range > 0 and body / total_range < 0.1:
            return {
                "signal": "NEUTRAL",
                "confidence": 60,
                "reason": "ha_doji",
                "description": "Heikin Ashi doji indicates indecision"
            }
        
        # Check for potential reversal patterns
        last_3 = ha_candles[-3:]
        
        # Bullish reversal: bearish -> small body -> bullish
        if (last_3[0]["close"] < last_3[0]["open"] and
            abs(last_3[1]["close"] - last_3[1]["open"]) < abs(last_3[0]["close"] - last_3[0]["open"]) * 0.3 and
            last_3[2]["close"] > last_3[2]["open"]):
            
            return {
                "signal": "BUY",
                "confidence": 70,
                "reason": "ha_bullish_reversal",
                "description": "Heikin Ashi bullish reversal pattern"
            }
        
        # Bearish reversal: bullish -> small body -> bearish
        if (last_3[0]["close"] > last_3[0]["open"] and
            abs(last_3[1]["close"] - last_3[1]["open"]) < abs(last_3[0]["close"] - last_3[0]["open"]) * 0.3 and
            last_3[2]["close"] < last_3[2]["open"]):
            
            return {
                "signal": "SELL",
                "confidence": 70,
                "reason": "ha_bearish_reversal",
                "description": "Heikin Ashi bearish reversal pattern"
            }
        
        # Default neutral
        return {
            "signal": "NEUTRAL",
            "confidence": 50,
            "reason": "ha_mixed",
            "description": f"Heikin Ashi mixed signals ({bullish_count} bullish, {bearish_count} bearish)"
        }
    
    @staticmethod
    def generate_combined_signal(
        ema_signal: Dict, 
        rsi_signal: Dict, 
        pattern_signal: Dict, 
        ict_signal: Dict,
        ha_signal: Dict
    ) -> Dict:
        """Combine all signals into final recommendation"""
        
        # Signal weights (sum to 1.0)
        weights = {
            "ema": 0.25,      # 25% - Trend following
            "rsi": 0.20,      # 20% - Momentum
            "patterns": 0.25,  # 25% - Price action
            "ict": 0.20,      # 20% - Market structure
            "heikin_ashi": 0.10  # 10% - Smoothed trend
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
        
        signals = [
            (ema_signal, weights["ema"], "EMA"),
            (rsi_signal, weights["rsi"], "RSI"),
            (pattern_signal, weights["patterns"], "Patterns"),
            (ict_signal, weights["ict"], "ICT"),
            (ha_signal, weights["heikin_ashi"], "Heikin Ashi")
        ]
        
        component_details = {}
        
        for sig, weight, name in signals:
            sig_value = signal_values.get(sig.get("signal", "NEUTRAL"), 0)
            sig_conf = sig.get("confidence", 0)
            
            # Adjust score by confidence
            adjusted_score = sig_value * weight * (sig_conf / 100)
            total_score += adjusted_score
            
            # Weighted confidence
            weighted_conf = sig_conf * weight
            total_confidence += weighted_conf
            
            component_details[name.lower()] = {
                "signal": sig.get("signal", "NEUTRAL"),
                "confidence": sig_conf,
                "score": sig_value,
                "adjusted_score": round(adjusted_score, 3),
                "reason": sig.get("reason", ""),
                "description": sig.get("description", "")[:100]  # Truncate
            }
        
        # Determine final signal
        if total_score > 1.2:
            final_signal = SignalType.STRONG_BUY
            signal_strength = "very_strong"
        elif total_score > 0.6:
            final_signal = SignalType.BUY
            signal_strength = "strong"
        elif total_score > 0.2:
            final_signal = SignalType.BUY
            signal_strength = "moderate"
        elif total_score > -0.2:
            final_signal = SignalType.NEUTRAL
            signal_strength = "neutral"
        elif total_score > -0.6:
            final_signal = SignalType.SELL
            signal_strength = "moderate"
        elif total_score > -1.2:
            final_signal = SignalType.SELL
            signal_strength = "strong"
        else:
            final_signal = SignalType.STRONG_SELL
            signal_strength = "very_strong"
        
        # Determine confidence level
        if total_confidence >= 85:
            conf_level = SignalConfidence.VERY_HIGH
        elif total_confidence >= 70:
            conf_level = SignalConfidence.HIGH
        elif total_confidence >= 55:
            conf_level = SignalConfidence.MEDIUM
        else:
            conf_level = SignalConfidence.LOW
        
        # Generate recommendation
        recommendation = SignalGenerator._generate_recommendation(
            final_signal, 
            total_confidence, 
            total_score,
            component_details
        )
        
        # Check for conflicts
        signals_list = [s[0].get("signal", "NEUTRAL") for s in signals]
        buy_signals = signals_list.count("BUY") + signals_list.count("STRONG_BUY")
        sell_signals = signals_list.count("SELL") + signals_list.count("STRONG_SELL")
        
        conflict = False
        if buy_signals > 0 and sell_signals > 0:
            if abs(buy_signals - sell_signals) <= 1:  # Close conflict
                conflict = True
        
        return {
            "signal": final_signal,
            "confidence": round(total_confidence, 1),
            "confidence_level": conf_level,
            "score": round(total_score, 2),
            "signal_strength": signal_strength,
            "has_conflict": conflict,
            "component_details": component_details,
            "recommendation": recommendation
        }
    
    @staticmethod
    def _generate_recommendation(signal: SignalType, confidence: float, score: float, components: Dict) -> str:
        """Generate human-readable recommendation with details"""
        
        base_messages = {
            SignalType.STRONG_BUY: "🚀 **STRONG BUY SIGNAL**",
            SignalType.BUY: "✅ **BUY SIGNAL**",
            SignalType.NEUTRAL: "⏸️ **NEUTRAL / WAIT**",
            SignalType.SELL: "📉 **SELL SIGNAL**",
            SignalType.STRONG_SELL: "🔴 **STRONG SELL SIGNAL**"
        }
        
        message = base_messages.get(signal, "⏸️ **NEUTRAL / WAIT**")
        
        # Add confidence
        if confidence >= 85:
            message += f"\n📈 **Confidence**: Very High ({confidence:.1f}%)"
        elif confidence >= 70:
            message += f"\n📈 **Confidence**: High ({confidence:.1f}%)"
        elif confidence >= 55:
            message += f"\n📊 **Confidence**: Moderate ({confidence:.1f}%)"
        else:
            message += f"\n⚠️ **Confidence**: Low ({confidence:.1f}%) - Trade carefully"
        
        # Add signal strength
        message += f"\n📊 **Signal Strength**: {score:.2f}"
        
        # Add key component insights
        strong_components = []
        for name, comp in components.items():
            if comp.get("confidence", 0) >= 70:
                strong_components.append(f"{name}: {comp.get('signal')} ({comp.get('confidence')}%)")
        
        if strong_components:
            message += f"\n🔍 **Strong Signals**: {', '.join(strong_components)}"
        
        # Add specific recommendations
        if signal == SignalType.STRONG_BUY:
            if confidence >= 85:
                message += "\n\n🎯 **Action**: Consider entering long position with 3-5% risk. Look for entry on minor pullbacks."
            else:
                message += "\n\n🎯 **Action**: Good buying opportunity. Consider scaling in over 2-3 entries."
        
        elif signal == SignalType.BUY:
            message += "\n\n🎯 **Action**: Bullish setup. Consider buying with 2-3% risk. Wait for confirmation if confidence < 70%."
        
        elif signal == SignalType.STRONG_SELL:
            if confidence >= 85:
                message += "\n\n🎯 **Action**: Strong bearish momentum. Consider exiting longs or entering shorts with 3-5% risk."
            else:
                message += "\n\n🎯 **Action**: Good selling opportunity. Consider scaling out of long positions."
        
        elif signal == SignalType.SELL:
            message += "\n\n🎯 **Action**: Bearish signals. Consider reducing exposure or shorting with 2-3% risk."
        
        else:  # NEUTRAL
            message += "\n\n🎯 **Action**: No clear edge. Wait for better setup. Monitor key levels for breakout/breakdown."
        
        # Risk management note
        message += "\n\n⚠️ **Risk Management**: Always use stop losses. Never risk more than 5% per trade."
        
        return message

# ========== KOMBİNE ANALİZ FONKSİYONLARI ==========
async def analyze_symbol(symbol: str, interval: str = "1h") -> Dict:
    """Complete technical analysis for a symbol using ONLY REAL DATA"""
    try:
        logger.info(f"Starting analysis for {symbol} ({interval})")
        
        # 1. Fetch REAL candle data
        candles = await RealDataFetcher.get_candles_with_retry(symbol, interval, 100)
        
        if not candles or len(candles) < 50:
            error_msg = f"Insufficient real data for {symbol}. Only {len(candles) if candles else 0} candles available (need at least 50)."
            logger.error(error_msg)
            raise HTTPException(status_code=400, detail=error_msg)
        
        logger.info(f"✅ Got {len(candles)} real candles for {symbol}")
        
        # 2. Calculate all indicators
        ema_9 = TechnicalIndicators.calculate_ema(candles, 9)
        ema_21 = TechnicalIndicators.calculate_ema(candles, 21)
        ema_50 = TechnicalIndicators.calculate_ema(candles, 50)
        rsi = TechnicalIndicators.calculate_rsi(candles, 14)
        ha_candles = TechnicalIndicators.convert_to_heikin_ashi(candles)
        atr = TechnicalIndicators.calculate_atr(candles, 14)
        macd_data = TechnicalIndicators.calculate_macd(candles)
        
        # 3. Detect patterns
        patterns = CandlestickPatternDetector.detect_all_patterns(candles)
        
        # 4. ICT Analysis
        fvgs = ICTAnalyzer.detect_fair_value_gaps(candles)
        order_blocks = ICTAnalyzer.detect_order_blocks(candles)
        market_structure = ICTAnalyzer.analyze_market_structure(candles)
        
        # 5. Generate individual signals
        ema_signal = SignalGenerator.calculate_ema_signal(candles, ema_9, ema_21)
        rsi_signal = SignalGenerator.calculate_rsi_signal(candles, rsi)
        pattern_signal = SignalGenerator.calculate_pattern_signal(patterns)
        ict_signal = SignalGenerator.calculate_ict_signal(candles, fvgs, order_blocks, market_structure)
        ha_signal = SignalGenerator.calculate_heikin_ashi_signal(ha_candles)
        
        # 6. Combined signal
        combined_signal = SignalGenerator.generate_combined_signal(
            ema_signal, rsi_signal, pattern_signal, ict_signal, ha_signal
        )
        
        # 7. Current price data
        current_candle = candles[-1]
        prev_candle = candles[-2] if len(candles) >= 2 else current_candle
        price_change = ((current_candle["close"] - prev_candle["close"]) / prev_candle["close"]) * 100
        
        # 8. Volume analysis
        recent_volume = candles[-5:]
        avg_volume = sum(c["volume"] for c in recent_volume) / len(recent_volume)
        volume_ratio = current_candle["volume"] / avg_volume if avg_volume > 0 else 1
        
        # 9. Support/Resistance levels (simplified)
        recent_highs = [c["high"] for c in candles[-20:]]
        recent_lows = [c["low"] for c in candles[-20:]]
        
        resistance = max(recent_highs)
        support = min(recent_lows)
        
        # Format timestamps
        candle_time = datetime.fromtimestamp(current_candle["timestamp"] / 1000).strftime('%Y-%m-%d %H:%M:%S')
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "interval": interval,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "candle_time": candle_time,
            "data_source": "Binance Real Data",
            "candles_analyzed": len(candles),
            "price_data": {
                "current": round(current_candle["close"], 4),
                "open": round(current_candle["open"], 4),
                "high": round(current_candle["high"], 4),
                "low": round(current_candle["low"], 4),
                "change_percent": round(price_change, 2),
                "volume": round(current_candle["volume"], 2),
                "volume_ratio": round(volume_ratio, 2),
                "volume_status": "high" if volume_ratio > 1.5 else "normal" if volume_ratio > 0.7 else "low"
            },
            "key_levels": {
                "resistance": round(resistance, 4),
                "support": round(support, 4),
                "distance_to_resistance": round((resistance - current_candle["close"]) / current_candle["close"] * 100, 2),
                "distance_to_support": round((current_candle["close"] - support) / current_candle["close"] * 100, 2)
            },
            "indicators": {
                "ema_9": round(ema_9[-1], 4) if ema_9[-1] is not None else None,
                "ema_21": round(ema_21[-1], 4) if ema_21[-1] is not None else None,
                "ema_50": round(ema_50[-1], 4) if ema_50[-1] is not None else None,
                "rsi": round(rsi[-1], 2) if rsi[-1] is not None else None,
                "atr": round(atr[-1], 4) if atr[-1] is not None else None,
                "macd": round(macd_data["macd"][-1], 4) if macd_data["macd"][-1] is not None else None,
                "macd_signal": round(macd_data["signal"][-1], 4) if macd_data["signal"][-1] is not None else None,
                "macd_histogram": round(macd_data["histogram"][-1], 4) if macd_data["histogram"][-1] is not None else None
            },
            "patterns": {
                "count": len(patterns),
                "recent": patterns[-10:] if len(patterns) > 10 else patterns,
                "bullish": len([p for p in patterns if p.get("direction") == "bullish"]),
                "bearish": len([p for p in patterns if p.get("direction") == "bearish"]),
                "neutral": len([p for p in patterns if p.get("direction") == "neutral"])
            },
            "ict_analysis": {
                "market_structure": market_structure,
                "fair_value_gaps": {
                    "count": len(fvgs),
                    "recent": fvgs[-5:] if len(fvgs) > 5 else fvgs
                },
                "order_blocks": {
                    "count": len(order_blocks),
                    "recent": order_blocks[-5:] if len(order_blocks) > 5 else order_blocks
                }
            },
            "signal": combined_signal
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis error for {symbol}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail=f"Analysis failed: {str(e)}. Please check if {symbol} is a valid trading pair."
        )

# ========== API ENDPOINTS ==========
@app.get("/health")
def health():
    return {"status": "healthy", "version": "2.0.0", "data_source": "Binance Real Data Only"}

@app.get("/ready")
async def ready_check():
    return PlainTextResponse("READY")

@app.get("/live")
async def liveness_probe():
    return {"status": "alive", "timestamp": datetime.utcnow().isoformat()}

@app.get("/api/analyze/{symbol}")
async def analyze_endpoint(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1h|4h|1d)$")
):
    """Complete technical analysis for a symbol using REAL DATA"""
    return await analyze_symbol(symbol, interval)

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
                    logger.warning(f"AI analysis failed: {ai_analysis['error']}")
                    ai_analysis = None
            except Exception as ai_error:
                logger.warning(f"AI analysis skipped: {ai_error}")
                ai_analysis = None
        
        # 3. Birleştirme
        trad_signal = traditional.get("signal", {}).get("signal", "NEUTRAL")
        trad_conf = traditional.get("signal", {}).get("confidence", 50)
        
        if not ai_analysis:
            combined = {
                "signal": trad_signal,
                "confidence": trad_conf,
                "source": "traditional_only",
                "alignment": "single_source"
            }
        else:
            ai_signal = ai_analysis.get("final_signal", "Hold")
            ai_conf = ai_analysis.get("final_confidence", 0.5) * 100
            
            # Sinyal eşleştirme
            signal_map = {
                "STRONG_BUY": "Buy", "BUY": "Buy",
                "STRONG_SELL": "Sell", "SELL": "Sell",
                "NEUTRAL": "Hold"
            }
            
            trad_mapped = signal_map.get(trad_signal, "Hold")
            
            # Uyum kontrolü
            if trad_mapped.lower() == ai_signal.lower():
                combined_conf = (trad_conf + ai_conf) / 2
                combined = {
                    "signal": trad_signal if trad_conf >= 70 else ai_signal.upper(),
                    "confidence": combined_conf,
                    "source": "both_aligned",
                    "alignment": "perfect",
                    "description": f"✅ Both methods agree on {ai_signal.upper()}"
                }
            else:
                # Çatışma durumu - yüksek güvenilirliği seç
                if trad_conf > ai_conf:
                    combined = {
                        "signal": trad_signal,
                        "confidence": trad_conf,
                        "source": "traditional_preferred",
                        "alignment": "conflict",
                        "description": f"⚠️ Conflict: Traditional ({trad_signal}) chosen over AI ({ai_signal})"
                    }
                else:
                    combined = {
                        "signal": ai_signal.upper(),
                        "confidence": ai_conf,
                        "source": "ai_preferred",
                        "alignment": "conflict",
                        "description": f"⚠️ Conflict: AI ({ai_signal}) chosen over Traditional ({trad_signal})"
                    }
        
        # 4. Nihai öneri
        base_recommendations = {
            "STRONG_BUY": "🚀 **STRONG BUY** - High conviction signal",
            "BUY": "✅ **BUY** - Bullish setup detected",
            "NEUTRAL": "⏸️ **NEUTRAL** - Wait for confirmation",
            "SELL": "📉 **SELL** - Consider reducing exposure",
            "STRONG_SELL": "🔴 **STRONG SELL** - Strong bearish signals"
        }
        
        recommendation = base_recommendations.get(combined["signal"], "No clear recommendation")
        
        # Güven seviyesi ekle
        if combined["confidence"] >= 80:
            recommendation += f"\n📈 **Confidence**: Very High ({combined['confidence']:.1f}%)"
        elif combined["confidence"] >= 70:
            recommendation += f"\n📈 **Confidence**: High ({combined['confidence']:.1f}%)"
        elif combined["confidence"] >= 60:
            recommendation += f"\n📈 **Confidence**: Moderate ({combined['confidence']:.1f}%)"
        else:
            recommendation += f"\n⚠️ **Confidence**: Low ({combined['confidence']:.1f}%) - Trade carefully"
        
        # AI önerisi ekle
        if ai_analysis and ai_analysis.get("recommendation"):
            recommendation += f"\n🤖 **AI Insight**: {ai_analysis['recommendation']}"
        
        return {
            "success": True,
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "traditional_analysis": traditional,
            "ai_analysis": ai_analysis,
            "combined_signal": combined,
            "final_recommendation": recommendation
        }
        
    except Exception as e:
        logger.error(f"Advanced analysis error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/data/price/{symbol}")
async def get_current_price(symbol: str):
    """Get current price from Binance"""
    price_data = await RealDataFetcher.fetch_current_price(symbol)
    
    if not price_data:
        raise HTTPException(status_code=404, detail=f"Could not fetch price for {symbol}")
    
    return {
        "symbol": price_data["symbol"],
        "price": price_data["price"],
        "change_24h": price_data["priceChangePercent"],
        "high_24h": price_data["high"],
        "low_24h": price_data["low"],
        "volume_24h": price_data["volume"],
        "timestamp": price_data["timestamp"]
    }

@app.get("/api/data/candles/{symbol}")
async def get_candle_data(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1h|4h|1d)$"),
    limit: int = Query(default=100, ge=10, le=1000)
):
    """Get raw candle data from Binance"""
    candles = await RealDataFetcher.get_candles_with_retry(symbol, interval, limit)
    
    if not candles:
        raise HTTPException(status_code=404, detail=f"No data available for {symbol}")
    
    # Format for frontend
    formatted_candles = []
    for candle in candles:
        formatted_candles.append({
            "time": candle["timestamp"] / 1000,  # TradingView format
            "open": candle["open"],
            "high": candle["high"],
            "low": candle["low"],
            "close": candle["close"],
            "volume": candle["volume"]
        })
    
    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "count": len(formatted_candles),
        "candles": formatted_candles
    }

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Main trading dashboard"""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Professional Trading Bot - Real Data Analysis</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            /* CSS kodunuz buraya gelecek */
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
            
            .container {
                max-width: 1400px;
                margin: 0 auto;
            }
            
            header {
                text-align: center;
                margin-bottom: 2rem;
                padding: 1.5rem;
                background: var(--bg-card);
                border-radius: 15px;
                border: 1px solid var(--border);
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
            }
            
            .logo {
                font-size: 2.2rem;
                font-weight: 800;
                background: linear-gradient(90deg, var(--primary), var(--success));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 0.5rem;
            }
            
            .tagline {
                font-size: 1.1rem;
                color: var(--text-muted);
                margin-bottom: 1.5rem;
            }
            
            .badges {
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                gap: 0.8rem;
            }
            
            .badge {
                background: rgba(59, 130, 246, 0.1);
                border: 1px solid rgba(59, 130, 246, 0.3);
                padding: 0.5rem 1rem;
                border-radius: 50px;
                font-size: 0.85rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }
            
            .main-content {
                display: grid;
                grid-template-columns: 1fr 400px;
                gap: 1.5rem;
            }
            
            @media (max-width: 1024px) {
                .main-content {
                    grid-template-columns: 1fr;
                }
            }
            
            .card {
                background: var(--bg-card);
                border-radius: 15px;
                padding: 1.5rem;
                border: 1px solid var(--border);
                margin-bottom: 1.5rem;
            }
            
            .card-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 1.5rem;
                padding-bottom: 1rem;
                border-bottom: 1px solid var(--border);
            }
            
            .card-title {
                font-size: 1.3rem;
                font-weight: 600;
                display: flex;
                align-items: center;
                gap: 0.7rem;
            }
            
            .input-group {
                display: flex;
                gap: 1rem;
                margin-bottom: 1.5rem;
            }
            
            .symbol-input {
                flex: 1;
                padding: 1rem;
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid var(--border);
                border-radius: 10px;
                color: var(--text);
                font-size: 1rem;
            }
            
            .interval-select {
                padding: 1rem;
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid var(--border);
                border-radius: 10px;
                color: var(--text);
                font-size: 1rem;
            }
            
            .analyze-btn {
                padding: 1rem 2rem;
                background: linear-gradient(90deg, var(--primary), #2563eb);
                border: none;
                border-radius: 10px;
                color: white;
                font-weight: 600;
                font-size: 1rem;
                cursor: pointer;
                transition: all 0.3s;
            }
            
            .analyze-btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 8px 25px rgba(37, 99, 235, 0.3);
            }
            
            .chart-container {
                height: 500px;
                background: rgba(0, 0, 0, 0.2);
                border-radius: 10px;
                overflow: hidden;
            }
            
            .signal-card {
                background: linear-gradient(135deg, rgba(16, 185, 129, 0.1), rgba(16, 185, 129, 0.05));
                border: 2px solid var(--success);
            }
            
            .signal-card.sell {
                background: linear-gradient(135deg, rgba(239, 68, 68, 0.1), rgba(239, 68, 68, 0.05));
                border-color: var(--danger);
            }
            
            .signal-card.neutral {
                background: linear-gradient(135deg, rgba(245, 158, 11, 0.1), rgba(245, 158, 11, 0.05));
                border-color: var(--warning);
            }
            
            .signal-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 1rem;
            }
            
            .signal-type {
                font-size: 1.8rem;
                font-weight: 800;
            }
            
            .signal-confidence {
                padding: 0.5rem 1rem;
                border-radius: 50px;
                font-weight: 600;
                background: rgba(255, 255, 255, 0.1);
            }
            
            .confidence-high {
                background: rgba(16, 185, 129, 0.2);
                color: var(--success);
            }
            
            .confidence-medium {
                background: rgba(245, 158, 11, 0.2);
                color: var(--warning);
            }
            
            .confidence-low {
                background: rgba(239, 68, 68, 0.2);
                color: var(--danger);
            }
            
            .price-info {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 1rem;
                margin-bottom: 1.5rem;
            }
            
            .price-item {
                text-align: center;
                padding: 1rem;
                background: rgba(255, 255, 255, 0.05);
                border-radius: 10px;
            }
            
            .price-label {
                font-size: 0.9rem;
                color: var(--text-muted);
                margin-bottom: 0.5rem;
            }
            
            .price-value {
                font-size: 1.5rem;
                font-weight: 700;
            }
            
            .price-change.positive {
                color: var(--success);
            }
            
            .price-change.negative {
                color: var(--danger);
            }
            
            .indicators-grid {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 1rem;
                margin-bottom: 1.5rem;
            }
            
            .indicator {
                text-align: center;
                padding: 1rem;
                background: rgba(255, 255, 255, 0.05);
                border-radius: 10px;
            }
            
            .indicator-label {
                font-size: 0.85rem;
                color: var(--text-muted);
                margin-bottom: 0.5rem;
            }
            
            .indicator-value {
                font-size: 1.2rem;
                font-weight: 600;
            }
            
            .loading {
                display: none;
                text-align: center;
                padding: 3rem;
                color: var(--text-muted);
            }
            
            .loading-spinner {
                width: 50px;
                height: 50px;
                border: 3px solid var(--border);
                border-top-color: var(--primary);
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin: 0 auto 1rem;
            }
            
            @keyframes spin {
                to { transform: rotate(360deg); }
            }
            
            .error-message {
                display: none;
                background: rgba(239, 68, 68, 0.1);
                border: 1px solid var(--danger);
                border-radius: 10px;
                padding: 1rem;
                margin-bottom: 1rem;
                color: var(--danger);
            }
            
            .ai-section {
                margin-top: 1.5rem;
                padding: 1rem;
                background: linear-gradient(135deg, rgba(59, 130, 246, 0.1), rgba(139, 92, 246, 0.1));
                border: 2px solid var(--primary);
                border-radius: 10px;
            }
            
            .ai-toggle {
                display: flex;
                align-items: center;
                gap: 1rem;
                margin-bottom: 1rem;
            }
            
            .toggle-switch {
                position: relative;
                width: 60px;
                height: 30px;
            }
            
            .toggle-slider {
                position: absolute;
                cursor: pointer;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background-color: var(--bg-hover);
                transition: .4s;
                border-radius: 34px;
            }
            
            .toggle-slider:before {
                position: absolute;
                content: "";
                height: 22px;
                width: 22px;
                left: 4px;
                bottom: 4px;
                background-color: white;
                transition: .4s;
                border-radius: 50%;
            }
            
            input:checked + .toggle-slider {
                background-color: var(--success);
            }
            
            input:checked + .toggle-slider:before {
                transform: translateX(30px);
            }
            
            .ai-result {
                display: none;
                margin-top: 1rem;
                padding: 1rem;
                background: rgba(255, 255, 255, 0.05);
                border-radius: 10px;
            }
            
            .real-data-badge {
                position: fixed;
                bottom: 20px;
                right: 20px;
                background: var(--success);
                color: white;
                padding: 0.5rem 1rem;
                border-radius: 50px;
                font-size: 0.9rem;
                font-weight: 600;
                box-shadow: 0 4px 15px rgba(16, 185, 129, 0.3);
                z-index: 1000;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <div class="logo">
                    <i class="fas fa-chart-line"></i> Professional Trading Bot
                </div>
                <div class="tagline">Advanced Technical Analysis • Real Binance Data • High-Confidence Signals</div>
                <div class="badges">
                    <div class="badge"><i class="fas fa-database"></i> Real Binance Data</div>
                    <div class="badge"><i class="fas fa-wave-square"></i> EMA Crossovers</div>
                    <div class="badge"><i class="fas fa-chart-bar"></i> RSI Analysis</div>
                    <div class="badge"><i class="fas fa-candle-holder"></i> Heikin Ashi</div>
                    <div class="badge"><i class="fas fa-chess-board"></i> ICT Structure</div>
                    <div class="badge"><i class="fas fa-pattern"></i> 12 Patterns</div>
                </div>
            </header>
            
            <div class="main-content">
                <div class="left-column">
                    <div class="card">
                        <div class="card-header">
                            <div class="card-title">
                                <i class="fas fa-chart-candlestick"></i> Live Chart
                            </div>
                            <div class="input-group">
                                <input type="text" class="symbol-input" id="symbolInput" placeholder="Enter symbol (e.g., BTC, ETH)" value="BTC">
                                <select class="interval-select" id="intervalSelect">
                                    <option value="1h">1 Hour</option>
                                    <option value="4h">4 Hours</option>
                                    <option value="1d">1 Day</option>
                                </select>
                                <button class="analyze-btn" id="analyzeBtn">
                                    <i class="fas fa-play"></i> Analyze
                                </button>
                            </div>
                        </div>
                        
                        <div class="loading" id="loading">
                            <div class="loading-spinner"></div>
                            <p>Fetching real data from Binance...</p>
                            <p class="loading-details">This may take a few seconds</p>
                        </div>
                        
                        <div class="error-message" id="errorMessage"></div>
                        
                        <div class="chart-container" id="chartContainer">
                            <!-- TradingView chart will be loaded here -->
                        </div>
                    </div>
                    
                    <div class="card" id="analysisResults" style="display: none;">
                        <div class="card-header">
                            <div class="card-title">
                                <i class="fas fa-file-alt"></i> Analysis Details
                            </div>
                        </div>
                        
                        <div class="price-info" id="priceInfo"></div>
                        
                        <div class="indicators-grid" id="indicatorsGrid"></div>
                        
                        <div class="ai-section">
                            <div class="ai-toggle">
                                <span>🤖 Enable AI Analysis</span>
                                <label class="toggle-switch">
                                    <input type="checkbox" id="aiToggle" checked>
                                    <span class="toggle-slider"></span>
                                </label>
                            </div>
                            
                            <div class="ai-result" id="aiResult"></div>
                        </div>
                    </div>
                </div>
                
                <div class="right-column">
                    <div class="card signal-card" id="signalCard" style="display: none;">
                        <div class="signal-header">
                            <div class="signal-type" id="signalType">NEUTRAL</div>
                            <div class="signal-confidence confidence-high" id="signalConfidence">85%</div>
                        </div>
                        
                        <div id="signalRecommendation"></div>
                        
                        <div class="card" style="margin-top: 1.5rem;">
                            <div class="card-header">
                                <div class="card-title">
                                    <i class="fas fa-lightbulb"></i> Trading Advice
                                </div>
                            </div>
                            <div id="tradingAdvice">
                                <!-- Will be populated by JavaScript -->
                            </div>
                        </div>
                    </div>
                    
                    <div class="card">
                        <div class="card-header">
                            <div class="card-title">
                                <i class="fas fa-history"></i> Recent Signals
                            </div>
                        </div>
                        <div id="recentSignals">
                            <p style="text-align: center; color: var(--text-muted); padding: 2rem;">
                                Analyze a symbol to see signals
                            </p>
                        </div>
                    </div>
                    
                    <div class="card">
                        <div class="card-header">
                            <div class="card-title">
                                <i class="fas fa-info-circle"></i> About This System
                            </div>
                        </div>
                        <div style="line-height: 1.6;">
                            <p><strong>📊 Data Source:</strong> Real-time Binance API</p>
                            <p><strong>✅ No Simulation:</strong> All data is real market data</p>
                            <p><strong>🔒 Risk Warning:</strong> Trading involves risk</p>
                            <p><strong>🔄 Update Frequency:</strong> Real-time with each request</p>
                            <p><strong>📈 Indicators Used:</strong> EMA, RSI, MACD, ATR, Heikin Ashi</p>
                            <p><strong>🎯 Pattern Detection:</strong> 12 major candlestick patterns</p>
                            <p><strong>🏛️ ICT Analysis:</strong> Market structure, FVGs, Order Blocks</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="real-data-badge">
            <i class="fas fa-bolt"></i> REAL BINANCE DATA
        </div>
        
        <!-- TradingView Widget -->
        <script src="https://s3.tradingview.com/tv.js"></script>
        
        <script>
            // Global variables
            let tvWidget = null;
            let currentSymbol = 'BTC';
            let currentInterval = '1h';
            let recentAnalyses = [];
            
            // DOM Elements
            const symbolInput = document.getElementById('symbolInput');
            const intervalSelect = document.getElementById('intervalSelect');
            const analyzeBtn = document.getElementById('analyzeBtn');
            const loading = document.getElementById('loading');
            const errorMessage = document.getElementById('errorMessage');
            const analysisResults = document.getElementById('analysisResults');
            const signalCard = document.getElementById('signalCard');
            const signalType = document.getElementById('signalType');
            const signalConfidence = document.getElementById('signalConfidence');
            const signalRecommendation = document.getElementById('signalRecommendation');
            const priceInfo = document.getElementById('priceInfo');
            const indicatorsGrid = document.getElementById('indicatorsGrid');
            const tradingAdvice = document.getElementById('tradingAdvice');
            const recentSignals = document.getElementById('recentSignals');
            const aiToggle = document.getElementById('aiToggle');
            const aiResult = document.getElementById('aiResult');
            
            // Initialize
            document.addEventListener('DOMContentLoaded', function() {
                // Load default analysis
                analyzeSymbol('BTC', '1h', true);
                
                // Set up event listeners
                analyzeBtn.addEventListener('click', function() {
                    const symbol = symbolInput.value.trim().toUpperCase();
                    const interval = intervalSelect.value;
                    
                    if (!symbol) {
                        showError('Please enter a symbol');
                        return;
                    }
                    
                    analyzeSymbol(symbol, interval, aiToggle.checked);
                });
                
                symbolInput.addEventListener('keypress', function(e) {
                    if (e.key === 'Enter') {
                        analyzeBtn.click();
                    }
                });
                
                aiToggle.addEventListener('change', function() {
                    if (currentSymbol) {
                        analyzeSymbol(currentSymbol, currentInterval, aiToggle.checked);
                    }
                });
            });
            
            // Main analysis function
            async function analyzeSymbol(symbol, interval, useAI = true) {
                try {
                    // Show loading
                    showLoading();
                    hideError();
                    analysisResults.style.display = 'none';
                    signalCard.style.display = 'none';
                    aiResult.style.display = 'none';
                    
                    // Update current values
                    currentSymbol = symbol;
                    currentInterval = interval;
                    
                    // Update UI
                    symbolInput.value = symbol;
                    
                    // Fetch analysis
                    const apiUrl = useAI 
                        ? `/api/advanced/analyze/${symbol}?interval=${interval}&include_ai=true`
                        : `/api/analyze/${symbol}?interval=${interval}`;
                    
                    const response = await fetch(apiUrl);
                    
                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.detail || `HTTP ${response.status}`);
                    }
                    
                    const data = await response.json();
                    
                    if (!data.success) {
                        throw new Error(data.error || 'Analysis failed');
                    }
                    
                    // Update TradingView chart
                    updateChart(symbol);
                    
                    // Update analysis results
                    updateAnalysisResults(data, useAI);
                    
                    // Add to recent analyses
                    addToRecentAnalyses(data);
                    
                    // Hide loading
                    hideLoading();
                    
                } catch (error) {
                    console.error('Analysis error:', error);
                    showError(`Analysis failed: ${error.message}`);
                    hideLoading();
                }
            }
            
            // Update TradingView chart
            function updateChart(symbol) {
                const container = document.getElementById('chartContainer');
                
                // Remove existing widget
                if (tvWidget) {
                    tvWidget.remove();
                    tvWidget = null;
                }
                
                // Create TradingView widget
                const widgetOptions = {
                    width: "100%",
                    height: "100%",
                    symbol: `BINANCE:${symbol.toUpperCase()}USDT`,
                    interval: currentInterval === '1h' ? '60' : currentInterval === '4h' ? '240' : 'D',
                    timezone: "Etc/UTC",
                    theme: "dark",
                    style: "1",
                    locale: "en",
                    toolbar_bg: "#1a1f3a",
                    enable_publishing: false,
                    hide_volume: true,
                    container_id: "chartContainer",
                    studies: [
                        "RSI@tv-basicstudies",
                        "MASimple@tv-basicstudies",
                        "Volume@tv-basicstudies"
                    ],
                    overrides: {
                        "paneProperties.background": "#0a0e27",
                        "paneProperties.vertGridProperties.color": "#1a1f3a",
                        "paneProperties.horzGridProperties.color": "#1a1f3a",
                        "scalesProperties.textColor": "#94a3b8"
                    }
                };
                
                // Check if TradingView is available
                if (typeof TradingView !== 'undefined') {
                    tvWidget = new TradingView.widget(widgetOptions);
                } else {
                    console.warn('TradingView widget not available');
                    container.innerHTML = `
                        <div style="display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-muted);">
                            <div style="text-align: center;">
                                <i class="fas fa-chart-line" style="font-size: 3rem; margin-bottom: 1rem;"></i>
                                <p>TradingView chart unavailable</p>
                                <p style="font-size: 0.9rem;">Using real Binance data for analysis</p>
                            </div>
                        </div>
                    `;
                }
            }
            
            // Update analysis results
            function updateAnalysisResults(data, useAI) {
                const analysis = useAI && data.traditional_analysis ? data.traditional_analysis : data;
                const signalData = analysis.signal;
                
                // Update signal card
                signalType.textContent = signalData.signal;
                signalConfidence.textContent = `${signalData.confidence}%`;
                
                // Set confidence class
                signalConfidence.className = 'signal-confidence';
                if (signalData.confidence >= 80) {
                    signalConfidence.classList.add('confidence-high');
                } else if (signalData.confidence >= 60) {
                    signalConfidence.classList.add('confidence-medium');
                } else {
                    signalConfidence.classList.add('confidence-low');
                }
                
                // Set signal card class
                signalCard.className = 'card signal-card';
                if (signalData.signal.includes('BUY')) {
                    signalCard.classList.add('buy');
                } else if (signalData.signal.includes('SELL')) {
                    signalCard.classList.add('sell');
                } else {
                    signalCard.classList.add('neutral');
                }
                
                // Update recommendation
                const recommendation = useAI ? data.final_recommendation : signalData.recommendation;
                signalRecommendation.innerHTML = recommendation.replace(/\n/g, '<br>');
                
                // Update price info
                const price = analysis.price_data;
                priceInfo.innerHTML = `
                    <div class="price-item">
                        <div class="price-label">Current Price</div>
                        <div class="price-value">$${price.current.toLocaleString()}</div>
                    </div>
                    <div class="price-item">
                        <div class="price-label">24h Change</div>
                        <div class="price-value price-change ${price.change_percent >= 0 ? 'positive' : 'negative'}">
                            ${price.change_percent >= 0 ? '+' : ''}${price.change_percent}%
                        </div>
                    </div>
                    <div class="price-item">
                        <div class="price-label">24h High</div>
                        <div class="price-value">$${price.high.toLocaleString()}</div>
                    </div>
                    <div class="price-item">
                        <div class="price-label">24h Low</div>
                        <div class="price-value">$${price.low.toLocaleString()}</div>
                    </div>
                `;
                
                // Update indicators
                const indicators = analysis.indicators;
                indicatorsGrid.innerHTML = `
                    <div class="indicator">
                        <div class="indicator-label">EMA 9</div>
                        <div class="indicator-value">${indicators.ema_9 ? indicators.ema_9.toLocaleString() : 'N/A'}</div>
                    </div>
                    <div class="indicator">
                        <div class="indicator-label">EMA 21</div>
                        <div class="indicator-value">${indicators.ema_21 ? indicators.ema_21.toLocaleString() : 'N/A'}</div>
                    </div>
                    <div class="indicator">
                        <div class="indicator-label">RSI</div>
                        <div class="indicator-value ${indicators.rsi > 70 ? 'negative' : indicators.rsi < 30 ? 'positive' : ''}">
                            ${indicators.rsi || 'N/A'}
                        </div>
                    </div>
                    <div class="indicator">
                        <div class="indicator-label">MACD</div>
                        <div class="indicator-value">${indicators.macd ? indicators.macd.toFixed(4) : 'N/A'}</div>
                    </div>
                    <div class="indicator">
                        <div class="indicator-label">ATR</div>
                        <div class="indicator-value">${indicators.atr ? indicators.atr.toFixed(4) : 'N/A'}</div>
                    </div>
                    <div class="indicator">
                        <div class="indicator-label">Volume</div>
                        <div class="indicator-value ${price.volume_ratio > 1.5 ? 'positive' : price.volume_ratio < 0.7 ? 'negative' : ''}">
                            ${price.volume_status.toUpperCase()}
                        </div>
                    </div>
                `;
                
                // Update trading advice
                updateTradingAdvice(signalData, analysis);
                
                // Update AI results if available
                if (useAI && data.ai_analysis && !data.ai_analysis.error) {
                    aiResult.innerHTML = `
                        <div style="margin-bottom: 0.5rem;">
                            <strong>🤖 AI Analysis:</strong> ${data.ai_analysis.final_signal || 'N/A'}
                        </div>
                        <div style="font-size: 0.9rem; color: var(--text-muted);">
                            ${data.ai_analysis.recommendation || 'No AI recommendation available'}
                        </div>
                    `;
                    aiResult.style.display = 'block';
                }
                
                // Show results
                analysisResults.style.display = 'block';
                signalCard.style.display = 'block';
            }
            
            // Update trading advice
            function updateTradingAdvice(signalData, analysis) {
                const advice = [];
                const price = analysis.price_data;
                const levels = analysis.key_levels;
                
                // Signal-based advice
                if (signalData.signal.includes('STRONG_BUY')) {
                    advice.push('✅ <strong>Strong buying opportunity</strong>');
                    advice.push('🎯 Consider entering with 3-5% position size');
                    advice.push('⏰ Look for entry on minor pullbacks');
                } else if (signalData.signal.includes('BUY')) {
                    advice.push('✅ <strong>Buying opportunity</strong>');
                    advice.push('🎯 Consider entering with 2-3% position size');
                    advice.push('📊 Wait for confirmation if confidence < 70%');
                } else if (signalData.signal.includes('STRONG_SELL')) {
                    advice.push('🔴 <strong>Strong selling opportunity</strong>');
                    advice.push('🎯 Consider exiting longs or entering shorts');
                    advice.push('⚠️ Monitor for potential trend continuation');
                } else if (signalData.signal.includes('SELL')) {
                    advice.push('📉 <strong>Selling pressure</strong>');
                    advice.push('🎯 Consider reducing exposure');
                    advice.push('📊 Wait for breakdown confirmation');
                } else {
                    advice.push('⏸️ <strong>No clear edge</strong>');
                    advice.push('🎯 Wait for better setup');
                    advice.push('📊 Monitor key levels for breakout');
                }
                
                // RSI advice
                if (analysis.indicators.rsi > 70) {
                    advice.push('📈 <strong>RSI Overbought</strong>: Caution advised');
                } else if (analysis.indicators.rsi < 30) {
                    advice.push('📉 <strong>RSI Oversold</strong>: Potential bounce');
                }
                
                // Volume advice
                if (price.volume_ratio > 1.5) {
                    advice.push('📊 <strong>High Volume</strong>: Strong interest in current move');
                } else if (price.volume_ratio < 0.7) {
                    advice.push('📊 <strong>Low Volume</strong>: Move may lack conviction');
                }
                
                // Support/Resistance advice
                advice.push(`🏔️ <strong>Resistance</strong>: $${levels.resistance.toLocaleString()} (${levels.distance_to_resistance}% away)`);
                advice.push(`🛡️ <strong>Support</strong>: $${levels.support.toLocaleString()} (${levels.distance_to_support}% away)`);
                
                // Risk management
                advice.push('<br>⚠️ <strong>Risk Management</strong>:');
                advice.push('• Always use stop losses');
                advice.push('• Never risk more than 5% per trade');
                advice.push('• Consider position sizing based on volatility');
                
                tradingAdvice.innerHTML = advice.join('<br>');
            }
            
            // Add to recent analyses
            function addToRecentAnalyses(data) {
                const analysis = data.traditional_analysis || data;
                const signal = analysis.signal;
                
                const recentItem = {
                    symbol: analysis.symbol,
                    timestamp: new Date().toLocaleTimeString(),
                    signal: signal.signal,
                    confidence: signal.confidence,
                    price: analysis.price_data.current
                };
                
                recentAnalyses.unshift(recentItem);
                
                // Keep only last 5
                if (recentAnalyses.length > 5) {
                    recentAnalyses = recentAnalyses.slice(0, 5);
                }
                
                updateRecentSignals();
            }
            
            // Update recent signals display
            function updateRecentSignals() {
                if (recentAnalyses.length === 0) {
                    recentSignals.innerHTML = `
                        <p style="text-align: center; color: var(--text-muted); padding: 2rem;">
                            Analyze a symbol to see signals
                        </p>
                    `;
                    return;
                }
                
                let html = '';
                recentAnalyses.forEach(item => {
                    const signalClass = item.signal.includes('BUY') ? 'success' : item.signal.includes('SELL') ? 'danger' : 'warning';
                    
                    html += `
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-bottom: 1px solid var(--border);">
                            <div>
                                <div style="font-weight: 600;">${item.symbol}</div>
                                <div style="font-size: 0.85rem; color: var(--text-muted);">${item.timestamp}</div>
                            </div>
                            <div style="text-align: right;">
                                <div style="color: var(--${signalClass}); font-weight: 600;">${item.signal}</div>
                                <div style="font-size: 0.85rem;">${item.confidence}% confidence</div>
                            </div>
                        </div>
                    `;
                });
                
                recentSignals.innerHTML = html;
            }
            
            // UI helper functions
            function showLoading() {
                loading.style.display = 'block';
                analyzeBtn.disabled = true;
                analyzeBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analyzing...';
            }
            
            function hideLoading() {
                loading.style.display = 'none';
                analyzeBtn.disabled = false;
                analyzeBtn.innerHTML = '<i class="fas fa-play"></i> Analyze';
            }
            
            function showError(message) {
                errorMessage.textContent = message;
                errorMessage.style.display = 'block';
                
                // Auto-hide after 10 seconds
                setTimeout(() => {
                    hideError();
                }, 10000);
            }
            
            function hideError() {
                errorMessage.style.display = 'none';
            }
            
            // Example symbols for quick testing
            const exampleSymbols = ['BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'DOT', 'DOGE'];
            
            // Quick analyze buttons (optional enhancement)
            function addQuickButtons() {
                const quickButtons = document.createElement('div');
                quickButtons.style.marginTop = '1rem';
                quickButtons.style.display = 'flex';
                quickButtons.style.flexWrap = 'wrap';
                quickButtons.style.gap = '0.5rem';
                
                exampleSymbols.forEach(symbol => {
                    const btn = document.createElement('button');
                    btn.textContent = symbol;
                    btn.style.padding = '0.5rem 1rem';
                    btn.style.background = 'rgba(255, 255, 255, 0.05)';
                    btn.style.border = '1px solid var(--border)';
                    btn.style.borderRadius = '5px';
                    btn.style.color = 'var(--text)';
                    btn.style.cursor = 'pointer';
                    btn.style.fontSize = '0.9rem';
                    
                    btn.addEventListener('click', () => {
                        symbolInput.value = symbol;
                        analyzeSymbol(symbol, intervalSelect.value, aiToggle.checked);
                    });
                    
                    quickButtons.appendChild(btn);
                });
                
                const inputGroup = document.querySelector('.input-group');
                inputGroup.parentNode.insertBefore(quickButtons, inputGroup.nextSibling);
            }
            
            // Uncomment to add quick buttons
            // addQuickButtons();
        </script>
    </body>
    </html>
    """
    return html_content

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
    <body>
        <div style="display: flex; justify-content: center; align-items: center; height: 100vh; background: #0a0e27; color: white; font-family: sans-serif;">
            <div style="text-align: center;">
                <h1 style="font-size: 2.5rem; margin-bottom: 1rem;">🚀 Professional Trading Bot</h1>
                <p style="font-size: 1.2rem; color: #94a3b8;">Loading dashboard...</p>
                <p style="margin-top: 2rem; color: #10b981;">
                    <i class="fas fa-spinner fa-spin"></i> Connecting to Binance API
                </p>
            </div>
        </div>
    </body>
    </html>
    """

# ========== AI ENDPOINTS (from original) ==========
@app.get("/api/ai/status")
async def ai_status():
    """AI servis durumu"""
    return {
        "ai_enabled": AI_ENABLED,
        "initialized": ai_service.initialized,
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

# ========== RUN APPLICATION ==========
if __name__ == "__main__":
    import uvicorn
    
    # Configuration
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info(f"🚀 Starting Professional Trading Bot v2.0.0")
    logger.info(f"🌐 Server: {host}:{port}")
    logger.info(f"📊 Data Source: Binance Real Data Only")
    logger.info(f"🤖 AI Enabled: {AI_ENABLED}")
    logger.info("✅ No synthetic data - Only real market analysis")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )
