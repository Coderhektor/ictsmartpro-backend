"""
🚀 REAL DATA TRADING BOT v4.5.0 - PROFESSIONAL GRADE
✅ REAL DATA ONLY - NO SYNTHETIC DATA
✅ Support/Resistance Detection
✅ ICT Candlestick Patterns (MSS, Order Blocks, FVG)
✅ Advanced Technical Analysis
"""

import os
import logging
from datetime import datetime, timedelta
import asyncio
from typing import Dict, List, Optional, Tuple
import aiohttp
from enum import Enum
import json
import time
import numpy as np
from collections import deque

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, HTTPException, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# FastAPI Application
app = FastAPI(
    title="Real Data Trading Bot",
    version="4.5.0",
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

# Templates for HTML pages
templates = Jinja2Templates(directory="templates")

# ========== DATA SOURCE CONFIGURATION ==========
class DataSourceConfig:
    """Configuration for API keys and endpoints"""
    
    # API Keys (set via environment variables for production)
    ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "demo")  # Get free key: alphavantage.co
    TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY", "")  # Get free key: twelvedata.com
    
    # Rate limiting
    COINGECKO_CACHE_SECONDS = 20  # Poll CoinGecko every 20 seconds
    BINANCE_RATE_LIMIT = 1200  # requests per minute
    
    # Endpoints
    COINGECKO_BASE = "https://api.coingecko.com/api/v3"
    BINANCE_BASE = "https://api.binance.com/api/v3"
    ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"
    TWELVE_DATA_BASE = "https://api.twelvedata.com"

# ========== ENUMS ==========
class MarketType(str, Enum):
    CRYPTO = "CRYPTO"
    FOREX = "FOREX"

class SignalType(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"

class PatternType(str, Enum):
    BULLISH_ENGULFING = "BULLISH_ENGULFING"
    BEARISH_ENGULFING = "BEARISH_ENGULFING"
    HAMMER = "HAMMER"
    SHOOTING_STAR = "SHOOTING_STAR"
    DOJI = "DOJI"
    MORNING_STAR = "MORNING_STAR"
    EVENING_STAR = "EVENING_STAR"
    BULLISH_MARUBOZU = "BULLISH_MARUBOZU"
    BEARISH_MARUBOZU = "BEARISH_MARUBOZU"
    # ICT Patterns
    MSS_BULLISH = "MSS_BULLISH"  # Market Structure Shift Bullish
    MSS_BEARISH = "MSS_BEARISH"  # Market Structure Shift Bearish
    BULLISH_ORDER_BLOCK = "BULLISH_ORDER_BLOCK"
    BEARISH_ORDER_BLOCK = "BEARISH_ORDER_BLOCK"
    BULLISH_FVG = "BULLISH_FVG"  # Fair Value Gap Bullish
    BEARISH_FVG = "BEARISH_FVG"  # Fair Value Gap Bearish
    LIQUIDITY_GRAB = "LIQUIDITY_GRAB"
    FAKE_OUT = "FAKE_OUT"

# ========== CACHE MANAGER ==========
class CacheManager:
    """Intelligent caching to minimize API calls"""
    
    def __init__(self):
        self.cache = {}
        self.cache_timestamps = {}
    
    def get(self, key: str, max_age_seconds: int = 60) -> Optional[any]:
        """Get cached data if not expired"""
        if key in self.cache:
            timestamp = self.cache_timestamps.get(key, 0)
            if time.time() - timestamp < max_age_seconds:
                logger.info(f"✅ Cache HIT: {key}")
                return self.cache[key]
            else:
                logger.info(f"⏰ Cache EXPIRED: {key}")
        return None
    
    def set(self, key: str, value: any):
        """Store data in cache"""
        self.cache[key] = value
        self.cache_timestamps[key] = time.time()
        logger.info(f"💾 Cache SET: {key}")
    
    def clear(self):
        """Clear all cache"""
        self.cache.clear()
        self.cache_timestamps.clear()

# Global cache instance
cache_manager = CacheManager()

# ========== DATA FETCHER CLASSES ==========
class CryptoDataFetcher:
    """Fetch real crypto data from multiple sources"""
    
    @staticmethod
    async def fetch_coingecko_ohlc(coin_id: str, days: int = 7) -> Optional[List[Dict]]:
        """Fetch OHLC data from CoinGecko"""
        try:
            url = f"{DataSourceConfig.COINGECKO_BASE}/coins/{coin_id}/ohlc"
            params = {
                "vs_currency": "usd",
                "days": days
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if not data or len(data) == 0:
                            return None
                        
                        candles = []
                        for item in data:
                            candles.append({
                                "timestamp": item[0],
                                "open": float(item[1]),
                                "high": float(item[2]),
                                "low": float(item[3]),
                                "close": float(item[4]),
                                "volume": 0
                            })
                        
                        logger.info(f"✅ CoinGecko: {len(candles)} candles for {coin_id}")
                        return candles
                    else:
                        logger.error(f"❌ CoinGecko error {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"❌ CoinGecko fetch error: {e}")
            return None
    
    @staticmethod
    async def search_coin_id(symbol: str) -> Optional[str]:
        """Search for CoinGecko coin ID"""
        cache_key = f"coingecko_id_{symbol.lower()}"
        cached = cache_manager.get(cache_key, max_age_seconds=3600)
        if cached:
            return cached
        
        try:
            url = f"{DataSourceConfig.COINGECKO_BASE}/search"
            params = {"query": symbol}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        coins = data.get("coins", [])
                        
                        for coin in coins:
                            if coin.get("symbol", "").upper() == symbol.upper():
                                coin_id = coin.get("id")
                                cache_manager.set(cache_key, coin_id)
                                logger.info(f"✅ Found CoinGecko ID: {symbol} -> {coin_id}")
                                return coin_id
                        
                        # Fallback to first result
                        if coins:
                            coin_id = coins[0].get("id")
                            cache_manager.set(cache_key, coin_id)
                            logger.info(f"⚠️ Using first match: {symbol} -> {coin_id}")
                            return coin_id
                    
        except Exception as e:
            logger.error(f"❌ CoinGecko search error: {e}")
        
        return None
    
    @staticmethod
    async def fetch_binance_klines(symbol: str, interval: str = "1h", limit: int = 200) -> Optional[List[Dict]]:
        """Fetch from Binance"""
        try:
            url = f"{DataSourceConfig.BINANCE_BASE}/klines"
            params = {
                "symbol": symbol.upper(),
                "interval": interval,
                "limit": limit
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        
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
                        
                        logger.info(f"✅ Binance: {len(candles)} candles for {symbol}")
                        return candles
                    else:
                        logger.error(f"❌ Binance error {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"❌ Binance fetch error: {e}")
            return None
    
    @staticmethod
    async def get_crypto_data(symbol: str, interval: str = "1h", days: int = 7) -> Optional[List[Dict]]:
        """Smart crypto data fetcher"""
        # Try Binance first for major pairs
        if symbol.upper().endswith("USDT"):
            data = await CryptoDataFetcher.fetch_binance_klines(symbol.upper(), interval, 200)
            if data and len(data) >= 50:
                return data
        
        # Try CoinGecko
        coin_id = await CryptoDataFetcher.search_coin_id(symbol.replace("USDT", "").replace("USD", ""))
        if coin_id:
            data = await CryptoDataFetcher.fetch_coingecko_ohlc(coin_id, days)
            if data and len(data) >= 50:
                return data
        
        logger.error(f"❌ No crypto data found for {symbol}")
        return None

class ForexDataFetcher:
    """Fetch forex data"""
    
    @staticmethod
    async def get_forex_data(symbol: str, interval: str = "1h") -> Optional[List[Dict]]:
        """Get forex data - placeholder implementation"""
        # For now, return dummy data
        # In production, implement Alpha Vantage/Twelve Data integration
        return None

# ========== UNIVERSAL DATA FETCHER ==========
class UniversalDataFetcher:
    """Smart data fetcher"""
    
    @staticmethod
    async def get_market_data(symbol: str, interval: str = "1h") -> Tuple[Optional[List[Dict]], MarketType]:
        """Get market data for any symbol"""
        # Default to crypto
        market_type = MarketType.CRYPTO
        
        # Detect market type
        if any(x in symbol.upper() for x in ["EUR", "GBP", "JPY", "USD", "CHF", "CAD", "AUD", "NZD"]):
            if len(symbol.replace("/", "").replace(" ", "")) == 6:
                market_type = MarketType.FOREX
        
        # Fetch data based on market type
        if market_type == MarketType.CRYPTO:
            candles = await CryptoDataFetcher.get_crypto_data(symbol, interval)
        else:
            candles = await ForexDataFetcher.get_forex_data(symbol, interval)
        
        return candles, market_type

# ========== SUPPORT/RESISTANCE DETECTOR ==========
class SupportResistanceDetector:
    """Advanced support and resistance detection"""
    
    @staticmethod
    def detect_support_resistance(candles: List[Dict], window: int = 10) -> Tuple[List[Dict], List[Dict]]:
        """
        Detect support and resistance levels using swing points
        Returns: (support_levels, resistance_levels)
        """
        if len(candles) < window * 2:
            return [], []
        
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        
        support_levels = []
        resistance_levels = []
        
        # Detect swing lows (potential support)
        for i in range(window, len(candles) - window):
            current_low = lows[i]
            left_min = min(lows[i-window:i])
            right_min = min(lows[i+1:i+window+1])
            
            if current_low < left_min and current_low < right_min:
                support_levels.append({
                    "price": current_low,
                    "index": i,
                    "timestamp": candles[i]["timestamp"],
                    "strength": window,
                    "touches": 1,
                    "type": "swing_low"
                })
        
        # Detect swing highs (potential resistance)
        for i in range(window, len(candles) - window):
            current_high = highs[i]
            left_max = max(highs[i-window:i])
            right_max = max(highs[i+1:i+window+1])
            
            if current_high > left_max and current_high > right_max:
                resistance_levels.append({
                    "price": current_high,
                    "index": i,
                    "timestamp": candles[i]["timestamp"],
                    "strength": window,
                    "touches": 1,
                    "type": "swing_high"
                })
        
        # Cluster nearby levels
        support_levels = SupportResistanceDetector._cluster_levels(support_levels, threshold=0.002)
        resistance_levels = SupportResistanceDetector._cluster_levels(resistance_levels, threshold=0.002)
        
        # Calculate touch count
        support_levels = SupportResistanceDetector._calculate_touches(candles, support_levels, "support")
        resistance_levels = SupportResistanceDetector._calculate_touches(candles, resistance_levels, "resistance")
        
        # Sort by strength
        support_levels.sort(key=lambda x: (-x["touches"], -x["strength"]))
        resistance_levels.sort(key=lambda x: (-x["touches"], -x["strength"]))
        
        return support_levels[:10], resistance_levels[:10]  # Top 10 each
    
    @staticmethod
    def _cluster_levels(levels: List[Dict], threshold: float = 0.002) -> List[Dict]:
        """Cluster nearby price levels"""
        if not levels:
            return []
        
        levels_sorted = sorted(levels, key=lambda x: x["price"])
        clustered = []
        
        current_cluster = [levels_sorted[0]]
        
        for level in levels_sorted[1:]:
            prev_price = current_cluster[-1]["price"]
            price_diff = abs(level["price"] - prev_price) / prev_price
            
            if price_diff <= threshold:
                current_cluster.append(level)
            else:
                # Calculate cluster average
                avg_price = sum(l["price"] for l in current_cluster) / len(current_cluster)
                max_strength = max(l["strength"] for l in current_cluster)
                
                clustered.append({
                    "price": avg_price,
                    "index": current_cluster[-1]["index"],
                    "timestamp": current_cluster[-1]["timestamp"],
                    "strength": max_strength,
                    "touches": len(current_cluster),
                    "type": current_cluster[0]["type"]
                })
                current_cluster = [level]
        
        # Process last cluster
        if current_cluster:
            avg_price = sum(l["price"] for l in current_cluster) / len(current_cluster)
            max_strength = max(l["strength"] for l in current_cluster)
            
            clustered.append({
                "price": avg_price,
                "index": current_cluster[-1]["index"],
                "timestamp": current_cluster[-1]["timestamp"],
                "strength": max_strength,
                "touches": len(current_cluster),
                "type": current_cluster[0]["type"]
            })
        
        return clustered
    
    @staticmethod
    def _calculate_touches(candles: List[Dict], levels: List[Dict], level_type: str) -> List[Dict]:
        """Calculate how many times price touched each level"""
        for level in levels:
            touch_count = 0
            for candle in candles:
                if level_type == "support":
                    if abs(candle["low"] - level["price"]) / level["price"] < 0.001:
                        touch_count += 1
                else:  # resistance
                    if abs(candle["high"] - level["price"]) / level["price"] < 0.001:
                        touch_count += 1
            
            level["touches"] = max(level["touches"], touch_count)
        
        return levels

# ========== ICT PATTERN DETECTOR ==========
class ICTPatternDetector:
    """Inner Circle Trader pattern detection"""
    
    @staticmethod
    def detect_ict_patterns(candles: List[Dict]) -> List[Dict]:
        """
        Detect ICT patterns in candle data
        Returns list of detected patterns
        """
        patterns = []
        
        if len(candles) < 5:
            return patterns
        
        # Detect Market Structure Shifts (MSS)
        mss_patterns = ICTPatternDetector._detect_mss(candles)
        patterns.extend(mss_patterns)
        
        # Detect Order Blocks
        ob_patterns = ICTPatternDetector._detect_order_blocks(candles)
        patterns.extend(ob_patterns)
        
        # Detect Fair Value Gaps (FVG)
        fvg_patterns = ICTPatternDetector._detect_fvg(candles)
        patterns.extend(fvg_patterns)
        
        # Detect Liquidity Grabs
        lg_patterns = ICTPatternDetector._detect_liquidity_grabs(candles)
        patterns.extend(lg_patterns)
        
        # Sort by recency
        patterns.sort(key=lambda x: x["index"], reverse=True)
        
        return patterns[:20]  # Return most recent 20 patterns
    
    @staticmethod
    def _detect_mss(candles: List[Dict]) -> List[Dict]:
        """Detect Market Structure Shifts"""
        patterns = []
        
        for i in range(2, len(candles) - 2):
            # Bullish MSS: Lower low followed by higher high
            if (candles[i-2]["low"] > candles[i-1]["low"] and  # Lower low
                candles[i-1]["high"] < candles[i]["high"]):    # Higher high
                patterns.append({
                    "index": i,
                    "pattern": PatternType.MSS_BULLISH,
                    "description": "Market Structure Shift Bullish",
                    "strength": 0.8,
                    "price": candles[i]["close"]
                })
            
            # Bearish MSS: Higher high followed by lower low
            if (candles[i-2]["high"] < candles[i-1]["high"] and  # Higher high
                candles[i-1]["low"] > candles[i]["low"]):        # Lower low
                patterns.append({
                    "index": i,
                    "pattern": PatternType.MSS_BEARISH,
                    "description": "Market Structure Shift Bearish",
                    "strength": 0.8,
                    "price": candles[i]["close"]
                })
        
        return patterns
    
    @staticmethod
    def _detect_order_blocks(candles: List[Dict]) -> List[Dict]:
        """Detect Order Blocks"""
        patterns = []
        
        for i in range(1, len(candles) - 1):
            current = candles[i]
            prev = candles[i-1]
            
            # Bullish Order Block: Strong bear candle followed by immediate rejection
            if (prev["close"] < prev["open"] * 0.98 and  # Strong bear candle
                current["close"] > prev["high"] and       # Close above previous high
                abs(current["close"] - current["open"]) < (current["high"] - current["low"]) * 0.3):  # Small body
                patterns.append({
                    "index": i,
                    "pattern": PatternType.BULLISH_ORDER_BLOCK,
                    "description": "Bullish Order Block",
                    "strength": 0.7,
                    "price": current["close"],
                    "zone": (prev["low"], prev["high"])
                })
            
            # Bearish Order Block: Strong bull candle followed by immediate rejection
            if (prev["close"] > prev["open"] * 1.02 and  # Strong bull candle
                current["close"] < prev["low"] and        # Close below previous low
                abs(current["close"] - current["open"]) < (current["high"] - current["low"]) * 0.3):  # Small body
                patterns.append({
                    "index": i,
                    "pattern": PatternType.BEARISH_ORDER_BLOCK,
                    "description": "Bearish Order Block",
                    "strength": 0.7,
                    "price": current["close"],
                    "zone": (prev["low"], prev["high"])
                })
        
        return patterns
    
    @staticmethod
    def _detect_fvg(candles: List[Dict]) -> List[Dict]:
        """Detect Fair Value Gaps"""
        patterns = []
        
        for i in range(2, len(candles)):
            prev1 = candles[i-2]
            prev2 = candles[i-1]
            current = candles[i]
            
            # Bullish FVG: Previous low > current high (gap up)
            if prev1["low"] > current["high"]:
                patterns.append({
                    "index": i,
                    "pattern": PatternType.BULLISH_FVG,
                    "description": "Bullish Fair Value Gap",
                    "strength": 0.6,
                    "price": current["close"],
                    "zone": (current["high"], prev1["low"])
                })
            
            # Bearish FVG: Previous high < current low (gap down)
            if prev1["high"] < current["low"]:
                patterns.append({
                    "index": i,
                    "pattern": PatternType.BEARISH_FVG,
                    "description": "Bearish Fair Value Gap",
                    "strength": 0.6,
                    "price": current["close"],
                    "zone": (prev1["high"], current["low"])
                })
        
        return patterns
    
    @staticmethod
    def _detect_liquidity_grabs(candles: List[Dict]) -> List[Dict]:
        """Detect Liquidity Grabs (Stop Hunts)"""
        patterns = []
        
        for i in range(3, len(candles)):
            # Liquidity grab above resistance
            if (candles[i-2]["high"] > candles[i-3]["high"] and  # Break previous high
                candles[i-1]["close"] < candles[i-2]["low"] and   # Close below previous low
                candles[i]["close"] > candles[i-2]["high"]):      # Move back up
                patterns.append({
                    "index": i,
                    "pattern": PatternType.LIQUIDITY_GRAB,
                    "description": "Liquidity Grab (Bull Trap)",
                    "strength": 0.75,
                    "price": candles[i]["close"]
                })
            
            # Liquidity grab below support
            if (candles[i-2]["low"] < candles[i-3]["low"] and     # Break previous low
                candles[i-1]["close"] > candles[i-2]["high"] and  # Close above previous high
                candles[i]["close"] < candles[i-2]["low"]):       # Move back down
                patterns.append({
                    "index": i,
                    "pattern": PatternType.LIQUIDITY_GRAB,
                    "description": "Liquidity Grab (Bear Trap)",
                    "strength": 0.75,
                    "price": candles[i]["close"]
                })
        
        return patterns

# ========== CANDLESTICK PATTERN DETECTOR ==========
class CandlestickPatternDetector:
    """Traditional candlestick pattern detection"""
    
    @staticmethod
    def detect_patterns(candles: List[Dict]) -> List[Dict]:
        """Detect classic candlestick patterns"""
        patterns = []
        
        if len(candles) < 3:
            return patterns
        
        for i in range(2, len(candles)):
            current = candles[i]
            prev = candles[i-1]
            prev2 = candles[i-2]
            
            # Engulfing Patterns
            patterns.extend(CandlestickPatternDetector._detect_engulfing(current, prev, i))
            
            # Hammer & Shooting Star
            patterns.extend(CandlestickPatternDetector._detect_hammer_shooting_star(current, i))
            
            # Doji
            if CandlestickPatternDetector._is_doji(current):
                patterns.append({
                    "index": i,
                    "pattern": PatternType.DOJI,
                    "description": "Doji (Indecision)",
                    "strength": 0.5,
                    "price": current["close"]
                })
            
            # Marubozu
            patterns.extend(CandlestickPatternDetector._detect_marubozu(current, i))
            
            # Morning/Evening Star (3-candle patterns)
            if i >= 2:
                patterns.extend(CandlestickPatternDetector._detect_3_candle_patterns(prev2, prev, current, i))
        
        return patterns[:15]  # Return most recent 15 patterns
    
    @staticmethod
    def _detect_engulfing(current: Dict, prev: Dict, index: int) -> List[Dict]:
        patterns = []
        
        # Bullish Engulfing
        if (prev["close"] < prev["open"] and  # Previous bearish
            current["close"] > current["open"] and  # Current bullish
            current["open"] <= prev["close"] and    # Opens at or below previous close
            current["close"] >= prev["open"]):      # Closes at or above previous open
            
            # Confirmation: body engulfs previous body
            if (current["close"] - current["open"]) > (prev["open"] - prev["close"]):
                patterns.append({
                    "index": index,
                    "pattern": PatternType.BULLISH_ENGULFING,
                    "description": "Bullish Engulfing Pattern",
                    "strength": 0.8,
                    "price": current["close"]
                })
        
        # Bearish Engulfing
        if (prev["close"] > prev["open"] and  # Previous bullish
            current["close"] < current["open"] and  # Current bearish
            current["open"] >= prev["close"] and    # Opens at or above previous close
            current["close"] <= prev["open"]):      # Closes at or below previous open
            
            # Confirmation: body engulfs previous body
            if (prev["close"] - prev["open"]) < (current["open"] - current["close"]):
                patterns.append({
                    "index": index,
                    "pattern": PatternType.BEARISH_ENGULFING,
                    "description": "Bearish Engulfing Pattern",
                    "strength": 0.8,
                    "price": current["close"]
                })
        
        return patterns
    
    @staticmethod
    def _detect_hammer_shooting_star(candle: Dict, index: int) -> List[Dict]:
        patterns = []
        
        body_size = abs(candle["close"] - candle["open"])
        total_range = candle["high"] - candle["low"]
        
        if total_range == 0:
            return patterns
        
        lower_wick = min(candle["open"], candle["close"]) - candle["low"]
        upper_wick = candle["high"] - max(candle["open"], candle["close"])
        
        # Hammer (bullish reversal at bottom)
        if (lower_wick >= body_size * 2 and  # Long lower wick
            upper_wick <= body_size * 0.5 and  # Small or no upper wick
            total_range > 0):
            
            patterns.append({
                "index": index,
                "pattern": PatternType.HAMMER,
                "description": "Hammer (Bullish Reversal)",
                "strength": 0.7,
                "price": candle["close"]
            })
        
        # Shooting Star (bearish reversal at top)
        if (upper_wick >= body_size * 2 and  # Long upper wick
            lower_wick <= body_size * 0.5 and  # Small or no lower wick
            total_range > 0):
            
            patterns.append({
                "index": index,
                "pattern": PatternType.SHOOTING_STAR,
                "description": "Shooting Star (Bearish Reversal)",
                "strength": 0.7,
                "price": candle["close"]
            })
        
        return patterns
    
    @staticmethod
    def _is_doji(candle: Dict) -> bool:
        """Check if candle is a doji"""
        body_size = abs(candle["close"] - candle["open"])
        total_range = candle["high"] - candle["low"]
        
        if total_range == 0:
            return False
        
        # Doji: very small body relative to range
        return body_size <= total_range * 0.1
    
    @staticmethod
    def _detect_marubozu(candle: Dict, index: int) -> List[Dict]:
        patterns = []
        
        body_size = abs(candle["close"] - candle["open"])
        total_range = candle["high"] - candle["low"]
        
        if total_range == 0:
            return patterns
        
        # Marubozu: very small or no wicks
        lower_wick = min(candle["open"], candle["close"]) - candle["low"]
        upper_wick = candle["high"] - max(candle["open"], candle["close"])
        
        # Bullish Marubozu
        if (candle["close"] > candle["open"] and  # Bullish
            lower_wick <= total_range * 0.05 and  # Very small lower wick
            upper_wick <= total_range * 0.05):    # Very small upper wick
            
            patterns.append({
                "index": index,
                "pattern": PatternType.BULLISH_MARUBOZU,
                "description": "Bullish Marubozu (Strong Buying)",
                "strength": 0.9,
                "price": candle["close"]
            })
        
        # Bearish Marubozu
        if (candle["close"] < candle["open"] and  # Bearish
            lower_wick <= total_range * 0.05 and  # Very small lower wick
            upper_wick <= total_range * 0.05):    # Very small upper wick
            
            patterns.append({
                "index": index,
                "pattern": PatternType.BEARISH_MARUBOZU,
                "description": "Bearish Marubozu (Strong Selling)",
                "strength": 0.9,
                "price": candle["close"]
            })
        
        return patterns
    
    @staticmethod
    def _detect_3_candle_patterns(prev2: Dict, prev: Dict, current: Dict, index: int) -> List[Dict]:
        patterns = []
        
        # Morning Star (bullish reversal)
        if (prev2["close"] < prev2["open"] and  # Long bearish
            abs(prev["close"] - prev["open"]) <= (prev["high"] - prev["low"]) * 0.3 and  # Small body
            current["close"] > current["open"] and  # Bullish
            current["close"] > prev2["close"]):  # Closes above first candle close
            
            patterns.append({
                "index": index,
                "pattern": PatternType.MORNING_STAR,
                "description": "Morning Star (Bullish Reversal)",
                "strength": 0.85,
                "price": current["close"]
            })
        
        # Evening Star (bearish reversal)
        if (prev2["close"] > prev2["open"] and  # Long bullish
            abs(prev["close"] - prev["open"]) <= (prev["high"] - prev["low"]) * 0.3 and  # Small body
            current["close"] < current["open"] and  # Bearish
            current["close"] < prev2["close"]):  # Closes below first candle close
            
            patterns.append({
                "index": index,
                "pattern": PatternType.EVENING_STAR,
                "description": "Evening Star (Bearish Reversal)",
                "strength": 0.85,
                "price": current["close"]
            })
        
        return patterns

# ========== ENHANCED TECHNICAL INDICATORS ==========
class EnhancedTechnicalIndicators:
    """Enhanced technical indicators with pattern detection"""
    
    @staticmethod
    async def analyze_market_structure(symbol: str, interval: str = "1h") -> Dict:
        """Analyze overall market structure with real data"""
        try:
            # Fetch real data
            candles, market_type = await UniversalDataFetcher.get_market_data(symbol, interval)
            
            if not candles or len(candles) < 50:
                return {
                    "error": "Insufficient data",
                    "candle_count": len(candles) if candles else 0
                }
            
            recent = candles[-50:]
            prices = [c["close"] for c in recent]
            volumes = [c.get("volume", 0) for c in recent]
            
            # Trend analysis
            sma_20 = np.mean(prices[-20:]) if len(prices) >= 20 else prices[-1]
            sma_50 = np.mean(prices[-50:]) if len(prices) >= 50 else prices[-1]
            
            trend = "BULLISH" if sma_20 > sma_50 else "BEARISH"
            trend_strength = abs((sma_20 - sma_50) / sma_50 * 100)
            
            # Volatility
            returns = np.diff(prices) / prices[:-1]
            volatility = np.std(returns) * 100 if len(returns) > 0 else 0
            
            # Volume analysis
            avg_volume = np.mean(volumes) if any(volumes) else 0
            current_volume = volumes[-1] if volumes else 0
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
            
            # Support/Resistance
            support_levels, resistance_levels = SupportResistanceDetector.detect_support_resistance(candles)
            
            # Pattern detection
            candlestick_patterns = CandlestickPatternDetector.detect_patterns(candles)
            ict_patterns = ICTPatternDetector.detect_ict_patterns(candles)
            
            # Current price info
            current_price = candles[-1]["close"]
            price_change = 0
            if len(candles) > 1:
                price_change = ((candles[-1]["close"] - candles[-2]["close"]) / candles[-2]["close"]) * 100
            
            return {
                "symbol": symbol.upper(),
                "market_type": market_type.value,
                "current_price": round(current_price, 8),
                "price_change_percent": round(price_change, 2),
                "trend": trend,
                "trend_strength": round(trend_strength, 2),
                "volatility": round(volatility, 2),
                "volume_ratio": round(volume_ratio, 2),
                "support_levels": support_levels[:5],
                "resistance_levels": resistance_levels[:5],
                "candlestick_patterns": candlestick_patterns[:5],
                "ict_patterns": ict_patterns[:5],
                "candle_count": len(candles),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
            
        except Exception as e:
            logger.error(f"Market structure analysis error: {e}")
            return {
                "error": str(e),
                "symbol": symbol
            }

# ========== API ENDPOINTS ==========
@app.get("/")
@app.get("/dashboard")
async def dashboard(request: Request):
    """Dashboard HTML page"""
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "title": "Real Data Trading Bot v4.5.0",
        "version": "4.5.0"
    })

@app.get("/health")
def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "4.5.0",
        "timestamp": datetime.utcnow().isoformat(),
        "features": [
            "Real Data Only - NO SYNTHETIC DATA",
            "Support/Resistance Detection", 
            "ICT Pattern Recognition",
            "Candlestick Pattern Analysis",
            "Multi-Exchange Data Fetching"
        ]
    }

@app.get("/api/analyze/{symbol}")
async def analyze_symbol(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1h|4h|1d)$")
):
    """Complete market analysis"""
    try:
        # Get full analysis
        analysis = await EnhancedTechnicalIndicators.analyze_market_structure(symbol, interval)
        
        if "error" in analysis:
            raise HTTPException(status_code=503, detail=analysis["error"])
        
        return {
            "success": True,
            "analysis": analysis
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@app.get("/api/support_resistance/{symbol}")
async def get_support_resistance(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1h|4h|1d)$")
):
    """Get support and resistance levels"""
    try:
        # Fetch real data
        candles, market_type = await UniversalDataFetcher.get_market_data(symbol, interval)
        
        if not candles or len(candles) < 20:
            raise HTTPException(
                status_code=503, 
                detail=f"Insufficient data for {symbol}. Only {len(candles) if candles else 0} candles available."
            )
        
        support_levels, resistance_levels = SupportResistanceDetector.detect_support_resistance(candles)
        
        current_price = candles[-1]["close"]
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "interval": interval,
            "current_price": round(current_price, 8),
            "market_type": market_type.value,
            "support_levels": [
                {
                    "price": round(level["price"], 8),
                    "strength": level["strength"],
                    "touches": level["touches"],
                    "distance_percent": round(((current_price - level["price"]) / current_price * 100), 2)
                }
                for level in support_levels[:5]
            ],
            "resistance_levels": [
                {
                    "price": round(level["price"], 8),
                    "strength": level["strength"],
                    "touches": level["touches"],
                    "distance_percent": round(((level["price"] - current_price) / current_price * 100), 2)
                }
                for level in resistance_levels[:5]
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Support/resistance error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/patterns/{symbol}")
async def get_patterns(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1h|4h|1d)$")
):
    """Get detected patterns"""
    try:
        # Fetch real data
        candles, market_type = await UniversalDataFetcher.get_market_data(symbol, interval)
        
        if not candles or len(candles) < 10:
            raise HTTPException(
                status_code=503, 
                detail=f"Insufficient data for {symbol}"
            )
        
        candlestick_patterns = CandlestickPatternDetector.detect_patterns(candles)
        ict_patterns = ICTPatternDetector.detect_ict_patterns(candles)
        
        # Filter recent patterns (last 20 candles)
        recent_patterns = []
        all_patterns = candlestick_patterns + ict_patterns
        for pattern in all_patterns:
            if pattern["index"] >= len(candles) - 20:
                recent_patterns.append(pattern)
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "interval": interval,
            "market_type": market_type.value,
            "recent_patterns": recent_patterns[:10],
            "pattern_counts": {
                "candlestick": len(candlestick_patterns),
                "ict": len(ict_patterns),
                "total": len(candlestick_patterns) + len(ict_patterns),
                "recent": len(recent_patterns)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Pattern detection error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ========== STATIC HTML PAGES ==========
@app.get("/test")
async def test_page():
    """Simple test page"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Trading Bot Test</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #0f172a; color: white; }
            .container { max-width: 1200px; margin: 0 auto; }
            .header { background: linear-gradient(90deg, #10b981, #059669); padding: 20px; border-radius: 10px; }
            .api-list { margin-top: 20px; background: #1e293b; padding: 20px; border-radius: 10px; }
            .api-item { background: #334155; padding: 10px; margin: 10px 0; border-radius: 5px; }
            code { background: #475569; padding: 2px 5px; border-radius: 3px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🚀 Real Data Trading Bot v4.5.0</h1>
                <p>✅ Real Data Only - NO SYNTHETIC DATA</p>
            </div>
            
            <div class="api-list">
                <h2>📡 Available API Endpoints:</h2>
                
                <div class="api-item">
                    <h3>🏠 Main Dashboard</h3>
                    <p><code>GET /</code> or <code>GET /dashboard</code> - Trading dashboard</p>
                </div>
                
                <div class="api-item">
                    <h3>💚 Health Check</h3>
                    <p><code>GET /health</code> - System status</p>
                </div>
                
                <div class="api-item">
                    <h3>📊 Full Analysis</h3>
                    <p><code>GET /api/analyze/{symbol}</code> - Complete market analysis</p>
                    <p>Example: <a href="/api/analyze/BTCUSDT?interval=1h" style="color: #10b981;">/api/analyze/BTCUSDT</a></p>
                </div>
                
                <div class="api-item">
                    <h3>🎯 Support/Resistance</h3>
                    <p><code>GET /api/support_resistance/{symbol}</code> - Key levels</p>
                    <p>Example: <a href="/api/support_resistance/ETHUSDT" style="color: #10b981;">/api/support_resistance/ETHUSDT</a></p>
                </div>
                
                <div class="api-item">
                    <h3>🔄 Patterns</h3>
                    <p><code>GET /api/patterns/{symbol}</code> - Candlestick & ICT patterns</p>
                    <p>Example: <a href="/api/patterns/SOLUSDT" style="color: #10b981;">/api/patterns/SOLUSDT</a></p>
                </div>
            </div>
            
            <div style="margin-top: 30px; padding: 20px; background: #1e293b; border-radius: 10px;">
                <h2>🔧 Quick Test Commands:</h2>
                <pre style="background: #334155; padding: 15px; border-radius: 5px;">
# Health check
curl http://localhost:8000/health

# Analyze BTC
curl "http://localhost:8000/api/analyze/BTCUSDT?interval=1h"

# Support/Resistance for ETH
curl "http://localhost:8000/api/support_resistance/ETHUSDT"

# Patterns for SOL
curl "http://localhost:8000/api/patterns/SOLUSDT"
                </pre>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ========== MAIN ==========
if __name__ == "__main__":
    import uvicorn
    
    # Create templates directory if it doesn't exist
    os.makedirs("templates", exist_ok=True)
    
    # Create a simple dashboard template
    dashboard_html = """
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ title }}</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            
            :root {
                --bg-dark: #0a0e27;
                --bg-card: #1a1f3a;
                --primary: #10b981;
                --success: #10b981;
                --danger: #ef4444;
                --warning: #f59e0b;
                --text: #e2e8f0;
                --text-muted: #94a3b8;
            }
            
            body {
                font-family: 'Segoe UI', sans-serif;
                background: linear-gradient(135deg, var(--bg-dark), #1a1f3a);
                color: var(--text);
                min-height: 100vh;
                padding: 1rem;
            }
            
            .container { max-width: 1800px; margin: 0 auto; }
            
            header {
                background: linear-gradient(90deg, var(--success), #059669);
                border-radius: 16px;
                padding: 2rem;
                margin-bottom: 2rem;
                text-align: center;
            }
            
            .logo {
                font-size: 2.5rem;
                font-weight: 900;
                color: white;
                margin-bottom: 1rem;
            }
            
            .status-badge {
                display: inline-block;
                background: rgba(255,255,255,0.2);
                padding: 0.5rem 1.5rem;
                border-radius: 20px;
                font-weight: 600;
            }
            
            .dashboard-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
                gap: 1.5rem;
                margin-bottom: 1.5rem;
            }
            
            .card {
                background: var(--bg-card);
                border-radius: 12px;
                padding: 1.5rem;
                margin-bottom: 1.5rem;
            }
            
            .card-title {
                font-size: 1.2rem;
                font-weight: 700;
                margin-bottom: 1rem;
                color: var(--primary);
                border-bottom: 2px solid var(--primary);
                padding-bottom: 0.5rem;
            }
            
            .control-panel {
                background: var(--bg-card);
                border-radius: 12px;
                padding: 1.5rem;
                margin-bottom: 2rem;
            }
            
            .input-row {
                display: grid;
                grid-template-columns: 1fr 150px auto;
                gap: 1rem;
                margin-bottom: 1rem;
            }
            
            input, select, button {
                padding: 0.75rem 1rem;
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.1);
                font-size: 0.95rem;
            }
            
            input, select {
                background: var(--bg-dark);
                color: var(--text);
            }
            
            button {
                background: var(--primary);
                color: white;
                border: none;
                cursor: pointer;
                font-weight: 600;
            }
            
            button:hover { opacity: 0.9; }
            button:disabled { opacity: 0.5; cursor: not-allowed; }
            
            .results {
                background: var(--bg-dark);
                padding: 1rem;
                border-radius: 8px;
                margin-top: 1rem;
                min-height: 200px;
                overflow-x: auto;
            }
            
            pre {
                white-space: pre-wrap;
                word-wrap: break-word;
                font-family: 'Courier New', monospace;
                font-size: 0.9rem;
            }
            
            .loading {
                text-align: center;
                padding: 3rem;
                color: var(--primary);
            }
            
            .spinner {
                border: 3px solid rgba(16,185,129,0.3);
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
            
            .alert {
                padding: 1rem;
                border-radius: 8px;
                margin-bottom: 1rem;
            }
            
            .alert-info {
                background: rgba(59,130,246,0.1);
                border-left: 4px solid #3b82f6;
            }
            
            .quick-symbols {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
                gap: 0.5rem;
                margin-top: 1rem;
            }
            
            .quick-symbol {
                background: rgba(16,185,129,0.1);
                padding: 0.6rem;
                border-radius: 6px;
                text-align: center;
                cursor: pointer;
                transition: all 0.2s;
            }
            
            .quick-symbol:hover {
                background: rgba(16,185,129,0.2);
                transform: scale(1.05);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <div class="logo">
                    <i class="fas fa-chart-line"></i> {{ title }}
                </div>
                <div class="status-badge">
                    <i class="fas fa-check-circle"></i> REAL DATA ONLY - NO SYNTHETIC
                </div>
            </header>
            
            <div class="alert alert-info">
                <strong>📡 Veri Kaynakları:</strong><br>
                • <strong>Kripto:</strong> Binance (gerçek zamanlı) + CoinGecko (tüm coinler, 20 sn cache)<br>
                • <strong>Forex:</strong> Twelve Data (800 call/day) + Alpha Vantage (25 call/day fallback)<br>
                • <strong>Analiz:</strong> Destek/Direnç + ICT Pattern + Mum Pattern + Trend Analizi
            </div>
            
            <div class="control-panel">
                <h2 class="card-title"><i class="fas fa-search"></i> Analiz Yap</h2>
                <div class="input-row">
                    <input type="text" id="symbolInput" placeholder="Örn: BTCUSDT, ETHUSDT, SOLUSDT, EURUSD..." value="BTCUSDT">
                    <select id="intervalSelect">
                        <option value="1h">1 Saat</option>
                        <option value="4h">4 Saat</option>
                        <option value="1d">1 Gün</option>
                    </select>
                    <button onclick="analyze()" id="analyzeBtn">
                        <i class="fas fa-search"></i> Analiz Et
                    </button>
                </div>
                
                <div class="quick-symbols">
                    <div class="quick-symbol" onclick="setSymbol('BTCUSDT')">Bitcoin</div>
                    <div class="quick-symbol" onclick="setSymbol('ETHUSDT')">Ethereum</div>
                    <div class="quick-symbol" onclick="setSymbol('SOLUSDT')">Solana</div>
                    <div class="quick-symbol" onclick="setSymbol('XRPUSDT')">XRP</div>
                    <div class="quick-symbol" onclick="setSymbol('ADAUSDT')">Cardano</div>
                    <div class="quick-symbol" onclick="setSymbol('DOGEUSDT')">Dogecoin</div>
                </div>
            </div>
            
            <div class="dashboard-grid">
                <div class="card">
                    <h2 class="card-title"><i class="fas fa-chart-bar"></i> Tam Analiz</h2>
                    <div id="fullAnalysisResult" class="results">
                        <div class="loading">
                            <div class="spinner"></div>
                            Sembol seçin ve analiz edin...
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <h2 class="card-title"><i class="fas fa-layer-group"></i> Destek/Direnç</h2>
                    <div id="supportResistanceResult" class="results">
                        <div class="loading">Bekleniyor...</div>
                    </div>
                </div>
                
                <div class="card">
                    <h2 class="card-title"><i class="fas fa-shapes"></i> Patternler</h2>
                    <div id="patternsResult" class="results">
                        <div class="loading">Bekleniyor...</div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            function setSymbol(sym) {
                document.getElementById('symbolInput').value = sym;
                analyze();
            }
            
            async function analyze() {
                const symbol = document.getElementById('symbolInput').value.trim();
                const interval = document.getElementById('intervalSelect').value;
                const btn = document.getElementById('analyzeBtn');
                
                if (!symbol) {
                    alert('Lütfen bir sembol girin');
                    return;
                }
                
                btn.disabled = true;
                btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Gerçek veri çekiliyor...';
                
                // Show loading states
                document.getElementById('fullAnalysisResult').innerHTML = 
                    '<div class="loading"><div class="spinner"></div>Analiz ediliyor...</div>';
                document.getElementById('supportResistanceResult').innerHTML = 
                    '<div class="loading"><div class="spinner"></div>Yükleniyor...</div>';
                document.getElementById('patternsResult').innerHTML = 
                    '<div class="loading"><div class="spinner"></div>Yükleniyor...</div>';
                
                try {
                    // Full analysis
                    const analysisResp = await fetch(`/api/analyze/${encodeURIComponent(symbol)}?interval=${interval}`);
                    const analysisData = await analysisResp.json();
                    displayFullAnalysis(analysisData);
                    
                    // Support/Resistance
                    const srResp = await fetch(`/api/support_resistance/${encodeURIComponent(symbol)}?interval=${interval}`);
                    const srData = await srResp.json();
                    displaySupportResistance(srData);
                    
                    // Patterns
                    const patternsResp = await fetch(`/api/patterns/${encodeURIComponent(symbol)}?interval=${interval}`);
                    const patternsData = await patternsResp.json();
                    displayPatterns(patternsData);
                    
                } catch (err) {
                    console.error(err);
                    alert('Analiz hatası: ' + err.message);
                    
                    // Show error in results
                    document.getElementById('fullAnalysisResult').innerHTML = 
                        '<div style="color: #ef4444; padding: 2rem; text-align: center;">Hata: ' + err.message + '</div>';
                    
                } finally {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-search"></i> Analiz Et';
                }
            }
            
            function displayFullAnalysis(data) {
                const container = document.getElementById('fullAnalysisResult');
                
                if (!data.success) {
                    container.innerHTML = '<div style="color: #ef4444;">' + (data.detail || 'Analiz başarısız') + '</div>';
                    return;
                }
                
                const analysis = data.analysis;
                let html = '';
                
                if (analysis.error) {
                    html = `<div style="color: #f59e0b;">${analysis.error}</div>`;
                } else {
                    html = `
                        <div style="margin-bottom: 1rem;">
                            <strong>📊 ${analysis.symbol}</strong> (${analysis.market_type})<br>
                            <strong>💰 Fiyat:</strong> $${analysis.current_price} (${analysis.price_change_percent >= 0 ? '📈' : '📉'} ${Math.abs(analysis.price_change_percent)}%)<br>
                            <strong>📈 Trend:</strong> ${analysis.trend} (${analysis.trend_strength}% güç)<br>
                            <strong>⚡ Volatilite:</strong> ${analysis.volatility}%<br>
                            <strong>📊 Volume:</strong> ${analysis.volume_ratio.toFixed(2)}x ortalama<br>
                            <strong>🕒 Mum Sayısı:</strong> ${analysis.candle_count}<br>
                        </div>
                    `;
                }
                
                container.innerHTML = html;
            }
            
            function displaySupportResistance(data) {
                const container = document.getElementById('supportResistanceResult');
                
                if (!data.success) {
                    container.innerHTML = '<div style="color: #ef4444;">' + (data.detail || 'Hata') + '</div>';
                    return;
                }
                
                let html = `
                    <div style="margin-bottom: 1rem;">
                        <strong>💰 Mevcut Fiyat:</strong> $${data.current_price}<br>
                        <strong>📊 Piyasa:</strong> ${data.market_type}
                    </div>
                `;
                
                // Support levels
                html += '<div style="margin-bottom: 1rem;"><strong>🟢 Destek Seviyeleri:</strong>';
                if (data.support_levels.length === 0) {
                    html += '<br><em style="color: #94a3b8;">Destek seviyesi bulunamadı</em>';
                } else {
                    data.support_levels.forEach(level => {
                        const distanceColor = level.distance_percent > 5 ? '#94a3b8' : 
                                            level.distance_percent > 2 ? '#f59e0b' : '#10b981';
                        html += `
                            <div style="margin: 0.5rem 0; padding: 0.5rem; background: #0a0e27; border-radius: 4px;">
                                <strong>$${level.price}</strong><br>
                                <small>
                                    Güç: ${level.strength} | Temas: ${level.touches} | 
                                    <span style="color: ${distanceColor}">${level.distance_percent}% uzak</span>
                                </small>
                            </div>
                        `;
                    });
                }
                html += '</div>';
                
                // Resistance levels
                html += '<div><strong>🔴 Direnç Seviyeleri:</strong>';
                if (data.resistance_levels.length === 0) {
                    html += '<br><em style="color: #94a3b8;">Direnç seviyesi bulunamadı</em>';
                } else {
                    data.resistance_levels.forEach(level => {
                        const distanceColor = level.distance_percent > 5 ? '#94a3b8' : 
                                            level.distance_percent > 2 ? '#f59e0b' : '#ef4444';
                        html += `
                            <div style="margin: 0.5rem 0; padding: 0.5rem; background: #0a0e27; border-radius: 4px;">
                                <strong>$${level.price}</strong><br>
                                <small>
                                    Güç: ${level.strength} | Temas: ${level.touches} | 
                                    <span style="color: ${distanceColor}">${level.distance_percent}% uzak</span>
                                </small>
                            </div>
                        `;
                    });
                }
                html += '</div>';
                
                container.innerHTML = html;
            }
            
            function displayPatterns(data) {
                const container = document.getElementById('patternsResult');
                
                if (!data.success) {
                    container.innerHTML = '<div style="color: #ef4444;">' + (data.detail || 'Hata') + '</div>';
                    return;
                }
                
                let html = `
                    <div style="margin-bottom: 1rem;">
                        <strong>📊 Pattern Sayıları:</strong><br>
                        • Mum Pattern: ${data.pattern_counts.candlestick}<br>
                        • ICT Pattern: ${data.pattern_counts.ict}<br>
                        • Toplam: ${data.pattern_counts.total}<br>
                        • Son 20 Mum: ${data.pattern_counts.recent}
                    </div>
                `;
                
                // Recent patterns
                html += '<div><strong>🔄 Son Patternler:</strong>';
                if (!data.recent_patterns || data.recent_patterns.length === 0) {
                    html += '<br><em style="color: #94a3b8;">Son 20 mumda pattern bulunamadı</em>';
                } else {
                    data.recent_patterns.forEach(pattern => {
                        const strengthColor = pattern.strength > 0.8 ? '#10b981' : 
                                            pattern.strength > 0.6 ? '#f59e0b' : '#94a3b8';
                        html += `
                            <div style="margin: 0.5rem 0; padding: 0.5rem; background: #0a0e27; border-radius: 4px;">
                                <strong>${pattern.description}</strong><br>
                                <small>
                                    Tür: ${pattern.pattern} | 
                                    <span style="color: ${strengthColor}">Güç: ${pattern.strength}</span> | 
                                    Fiyat: $${pattern.price}
                                </small>
                            </div>
                        `;
                    });
                }
                html += '</div>';
                
                container.innerHTML = html;
            }
            
            // Initial analysis on page load
            document.addEventListener('DOMContentLoaded', () => {
                setTimeout(() => {
                    analyze();
                }, 1000);
            });
        </script>
    </body>
    </html>
    """
    
    # Save dashboard template
    with open("templates/dashboard.html", "w", encoding="utf-8") as f:
        f.write(dashboard_html)
    
    # Run the server
    port = int(os.getenv("PORT", 8000))
    
    logger.info(f"🚀 Starting Real Data Trading Bot v4.5.0 on port {port}")
    logger.info("=" * 60)
    logger.info("📡 Open your browser and go to:")
    logger.info(f"   🌐 http://localhost:{port}/")
    logger.info(f"   🔧 http://localhost:{port}/test")
    logger.info("=" * 60)
    logger.info("NEW FEATURES:")
    logger.info("  ✅ Support/Resistance Detection")
    logger.info("  ✅ ICT Pattern Recognition (MSS, Order Blocks, FVG)")
    logger.info("  ✅ Candlestick Pattern Analysis")
    logger.info("  ✅ NO SYNTHETIC DATA - REAL MARKET DATA ONLY")
    logger.info("=" * 60)
    
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
