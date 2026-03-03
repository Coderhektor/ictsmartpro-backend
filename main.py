import sys
import json
import time
import asyncio
import logging
import os
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set 
from collections import defaultdict
from enum import Enum
from pathlib import Path

# ML Libraries
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split, cross_val_score, TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import xgboost as xgb
import lightgbm as lgb

# FastAPI
from fastapi import FastAPI, Request, HTTPException, Query, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

# Pydantic
from pydantic import BaseModel, Field

# Async HTTP
import aiohttp
from aiohttp import ClientTimeout, TCPConnector


# ========================================================================================================
# PRODUCTION LOGGING
# ========================================================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("ictsmartpro-ml")


# ========================================================================================================
# PRODUCTION CONFIGURATION
# ========================================================================================================
class Config:
    """Production config with ML settings"""
    
    # Server
    ENV = os.getenv("ENV", "production")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    PORT = int(os.getenv("PORT", "8000"))
    
    # API Settings
    API_TIMEOUT = int(os.getenv("API_TIMEOUT", "10"))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "25"))
    
    # Data Settings
    MIN_CANDLES = int(os.getenv("MIN_CANDLES", "100"))
    MIN_EXCHANGES = int(os.getenv("MIN_EXCHANGES", "1"))
    CACHE_TTL = int(os.getenv("CACHE_TTL", "30"))
    
    # ML Settings
    ML_MODEL_DIR = os.getenv("ML_MODEL_DIR", "/app/models")
    ML_AUTO_RETRAIN = os.getenv("ML_AUTO_RETRAIN", "true").lower() == "true"
    ML_RETRAIN_HOURS = int(os.getenv("ML_RETRAIN_HOURS", "24"))
    ML_MIN_TRAINING_SAMPLES = int(os.getenv("ML_MIN_TRAINING_SAMPLES", "500"))
    ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.6"))
    
    # Pattern Settings
    MAX_PATTERNS = int(os.getenv("MAX_PATTERNS", "50"))
    
    # Security
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")


# ========================================================================================================
# ENUMS
# ========================================================================================================
class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    BULLISH_REVERSAL = "bullish_reversal"
    BEARISH_REVERSAL = "bearish_reversal"


class PatternType(str, Enum):
    ICT = "ict"
    CLASSICAL = "classical"
    CANDLESTICK = "candlestick"
    PRICE_ACTION = "price_action"
    SUPPORT_RESISTANCE = "support_resistance"
    TREND = "trend"


class SignalType(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


# ========================================================================================================
# DATA MODELS
# ========================================================================================================
class Candle(BaseModel):
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    exchange: str
    source_count: Optional[int] = 1


class Pattern(BaseModel):
    name: str
    type: PatternType
    direction: Direction
    confidence: float = Field(ge=0, le=100)
    timestamp: str
    price: float
    description: Optional[str] = None
    sl_level: Optional[float] = None
    tp_level: Optional[float] = None


class MLFeatures(BaseModel):
    return_1: float
    return_5: float
    return_10: float
    volatility: float
    rsi_14: float
    rsi_14_change: float
    macd: float
    macd_signal: float
    macd_histogram: float
    bb_position: float
    bb_width: float
    price_to_sma20: float
    price_to_sma50: float
    sma20_above_sma50: int
    volume_ratio: float
    volume_trend: float
    atr_percent: float
    momentum_5: float
    momentum_10: float


class MLPrediction(BaseModel):
    signal: SignalType
    confidence: float
    probability: float
    model_version: str
    features_used: List[str]
    buy_probability: float
    sell_probability: float


class AnalysisResponse(BaseModel):
    success: bool
    symbol: str
    interval: str
    timestamp: str
    price: Dict[str, float]
    ml_prediction: MLPrediction
    technical: Dict[str, Any]
    ict_patterns: List[Pattern]
    classical_patterns: List[Pattern]
    candlestick_patterns: List[Pattern]
    market_structure: Dict[str, str]
    active_sources: List[str]
    data_points: int
    model_info: Dict[str, Any]
    performance_ms: float


# ========================================================================================================
# PRODUCTION EXCHANGE DATA FETCHER
# ========================================================================================================
 
class ExchangeDataFetcher:
    """Production data fetcher with multiple exchanges"""
    
    EXCHANGES = [
        {
            "name": "Binance",
            "priority": 1,
            "base_url": "https://api.binance.com/api/v3/klines",
            "symbol_fmt": lambda s: s.replace("/", ""),
            "interval_map": {
                "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
            },
            "parser": "binance",
            "timeout": 5
        },
        {
            "name": "Kraken",
            "priority": 2,
            "base_url": "https://api.kraken.com/0/public/OHLC",
            "symbol_fmt": lambda s: s.replace("USDT", "USD").replace("/", ""),
            "interval_map": {
                "1m": "1", "5m": "5", "15m": "15", "30m": "30",
                "1h": "60", "4h": "240", "1d": "1440", "1w": "10080"
            },
            "parser": "kraken",
            "timeout": 8
        },
        {
            "name": "MEXC",
            "priority": 3,
            "base_url": "https://api.mexc.com/api/v3/klines",
            "symbol_fmt": lambda s: s.replace("/", ""),
            "interval_map": {
                "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
            },
            "parser": "binance",
            "timeout": 5
        }
    ]
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, Dict] = {}
        self.stats: Dict = defaultdict(lambda: {"success": 0, "fail": 0, "last_error": ""})
        self._lock = asyncio.Lock()
        self._session_initialized = False
    
    async def ensure_session(self):
        """Ensure session exists"""
        if not self._session_initialized or not self.session or self.session.closed:
            timeout = ClientTimeout(total=Config.API_TIMEOUT)
            connector = TCPConnector(limit=50, ttl_dns_cache=300, force_close=False)
            self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            self._session_initialized = True
        return self.session
    
    async def close_session(self):
        """Close session"""
        if self.session and not self.session.closed:
            await self.session.close()
            self._session_initialized = False
    
    def _get_cache_key(self, symbol: str, interval: str) -> str:
        return f"{symbol}_{interval}"
    
    def _is_cache_valid(self, key: str) -> bool:
        if key not in self.cache:
            return False
        return (time.time() - self.cache[key]['timestamp']) < Config.CACHE_TTL
    
    async def _fetch_exchange(self, exchange: Dict, symbol: str, interval: str, limit: int) -> Optional[List[Dict]]:
        """Fetch from single exchange"""
        try:
            session = await self.ensure_session()
            
            if interval not in exchange['interval_map']:
                return None
            
            params = {
                'symbol': exchange['symbol_fmt'](symbol),
                'interval': exchange['interval_map'][interval],
                'limit': limit
            }
            
            async with session.get(
                exchange['base_url'],
                params=params,
                timeout=exchange['timeout']
            ) as response:
                if response.status != 200:
                    async with self._lock:
                        self.stats[exchange['name']]['fail'] += 1
                        self.stats[exchange['name']]['last_error'] = f"HTTP {response.status}"
                    return None
                
                data = await response.json()
                candles = await self._parse_response(exchange['name'], data)
                
                if candles and len(candles) >= 10:
                    async with self._lock:
                        self.stats[exchange['name']]['success'] += 1
                    return candles
                else:
                    async with self._lock:
                        self.stats[exchange['name']]['fail'] += 1
                        self.stats[exchange['name']]['last_error'] = "Insufficient data"
                    return None
                    
        except asyncio.TimeoutError:
            async with self._lock:
                self.stats[exchange['name']]['fail'] += 1
                self.stats[exchange['name']]['last_error'] = "Timeout"
            return None
        except Exception as e:
            async with self._lock:
                self.stats[exchange['name']]['fail'] += 1
                self.stats[exchange['name']]['last_error'] = str(e)[:100]
            return None
    
    async def _parse_response(self, exchange: str, data: Any) -> List[Dict]:
        """Parse exchange response"""
        candles = []
        
        try:
            if exchange in ["Binance", "MEXC"]:
                if isinstance(data, list):
                    for item in data:
                        if len(item) >= 6:
                            candles.append({
                                "timestamp": int(item[0]),
                                "open": float(item[1]),
                                "high": float(item[2]),
                                "low": float(item[3]),
                                "close": float(item[4]),
                                "volume": float(item[5]),
                                "exchange": exchange
                            })
            
            elif exchange == "Kraken":
                if isinstance(data, dict) and "result" in data:
                    result = data["result"]
                    for key, value in result.items():
                        if isinstance(value, list) and key != "last":
                            for item in value:
                                if len(item) >= 6:
                                    candles.append({
                                        "timestamp": int(item[0]) * 1000,
                                        "open": float(item[1]),
                                        "high": float(item[2]),
                                        "low": float(item[3]),
                                        "close": float(item[4]),
                                        "volume": float(item[5]),
                                        "exchange": exchange
                                    })
                            break
            
            candles.sort(key=lambda x: x["timestamp"])
            return candles
            
        except Exception as e:
            logger.debug(f"Parse error for {exchange}: {e}")
            return []
    
    def _merge_candles(self, all_candles: List[List[Dict]], interval: str) -> List[Dict]:
        """Merge candles from multiple sources"""
        if not all_candles:
            return []
        
        # Interval in ms
        interval_ms = self._interval_to_ms(interval)
        
        # Group by rounded timestamp
        timestamp_map = defaultdict(list)
        
        for exchange_candles in all_candles:
            for candle in exchange_candles:
                rounded_ts = (candle["timestamp"] // interval_ms) * interval_ms
                timestamp_map[rounded_ts].append(candle)
        
        # Merge
        merged = []
        for timestamp in sorted(timestamp_map.keys()):
            candles = timestamp_map[timestamp]
            
            if len(candles) >= 1:
                # Simple average
                merged.append({
                    "timestamp": timestamp,
                    "open": sum(c["open"] for c in candles) / len(candles),
                    "high": sum(c["high"] for c in candles) / len(candles),
                    "low": sum(c["low"] for c in candles) / len(candles),
                    "close": sum(c["close"] for c in candles) / len(candles),
                    "volume": sum(c["volume"] for c in candles) / len(candles),
                    "source_count": len(candles),
                    "exchange": "merged"
                })
        
        return merged
    
    def _interval_to_ms(self, interval: str) -> int:
        multipliers = {
            "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800
        }
        return multipliers.get(interval, 3600) * 1000
    
    async def get_candles(self, symbol: str, interval: str = "1h", limit: int = 500) -> List[Dict]:
        """Get candles from multiple exchanges"""
        cache_key = self._get_cache_key(symbol, interval)
        
        # Check cache
        if self._is_cache_valid(cache_key):
            logger.info(f"Cache hit: {symbol} {interval}")
            return self.cache[cache_key]['data'][-limit:]
        
        logger.info(f"Fetching {symbol} {interval} from exchanges...")
        
        # Try all exchanges
        tasks = [self._fetch_exchange(ex, symbol, interval, limit) for ex in self.EXCHANGES]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_results = []
        for r in results:
            if isinstance(r, Exception):
                logger.debug(f"Exchange error: {r}")
            elif r and len(r) >= Config.MIN_CANDLES:
                valid_results.append(r)
        
        if not valid_results:
            logger.error(f"No data from any exchange for {symbol}")
            return []
        
        logger.info(f"Got data from {len(valid_results)} exchanges")
        
        # Merge candles
        merged = self._merge_candles(valid_results, interval)
        
        if len(merged) < Config.MIN_CANDLES:
            logger.warning(f"Only {len(merged)} merged candles")
            return merged[-limit:]
        
        # Update cache
        self.cache[cache_key] = {
            'data': merged,
            'timestamp': time.time()
        }
        
        return merged[-limit:]
    
    async def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price from Binance"""
        try:
            session = await self.ensure_session()
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.replace('/', '')}"
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    return float(data['price'])
        except Exception as e:
            logger.debug(f"Price fetch error: {e}")
        return None
    
    def get_stats(self) -> Dict:
        return dict(self.stats)
    
    def get_active_sources(self) -> List[str]:
        active = []
        for name, stats in self.stats.items():
            if stats['success'] > stats['fail']:
                active.append(name)
        return active


# ========================================================================================================
# TECHNICAL INDICATORS
# ========================================================================================================
class TechnicalIndicatorCalculator:
    """Technical indicator calculator"""
    
    @staticmethod
    def calculate_all(df: pd.DataFrame) -> Dict[str, pd.Series]:
        """Calculate all technical indicators"""
        df = df.copy()
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        
        # MACD
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        macd_signal = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd - macd_signal
        
        # Bollinger Bands
        sma20 = close.rolling(window=20).mean()
        std20 = close.rolling(window=20).std()
        bb_upper = sma20 + (std20 * 2)
        bb_lower = sma20 - (std20 * 2)
        bb_range = (bb_upper - bb_lower).replace(0, 1)
        bb_position = ((close - bb_lower) / bb_range * 100).clip(0, 100)
        
        # ATR
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean()
        
        # Volume
        volume_sma = volume.rolling(window=20).mean()
        volume_ratio = volume / volume_sma.replace(0, 1)
        
        # Moving Averages
        sma_50 = close.rolling(window=50).mean()
        ema_9 = close.ewm(span=9, adjust=False).mean()
        ema_21 = close.ewm(span=21, adjust=False).mean()
        
        return {
            'rsi': rsi,
            'macd': macd,
            'macd_signal': macd_signal,
            'macd_histogram': macd_hist,
            'bb_upper': bb_upper,
            'bb_middle': sma20,
            'bb_lower': bb_lower,
            'bb_position': bb_position,
            'atr': atr,
            'volume_ratio': volume_ratio,
            'sma_20': sma20,
            'sma_50': sma_50,
            'ema_9': ema_9,
            'ema_21': ema_21
        }


# ========================================================================================================
# MARKET STRUCTURE ANALYZER
# ========================================================================================================
class MarketStructureAnalyzer:
    """Market structure analysis"""
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> Dict[str, str]:
        if len(df) < 50:
            return {
                "trend": "NEUTRAL",
                "trend_strength": "WEAK",
                "volatility": "NORMAL",
                "momentum": "NEUTRAL"
            }
        
        close = df['close']
        
        # Trend analysis with EMAs
        ema_9 = close.ewm(span=9).mean()
        ema_21 = close.ewm(span=21).mean()
        ema_50 = close.ewm(span=50).mean()
        
        if ema_9.iloc[-1] > ema_21.iloc[-1] > ema_50.iloc[-1]:
            trend = "STRONG_UPTREND"
            trend_strength = "STRONG"
        elif ema_9.iloc[-1] > ema_21.iloc[-1]:
            trend = "UPTREND"
            trend_strength = "MODERATE"
        elif ema_9.iloc[-1] < ema_21.iloc[-1] < ema_50.iloc[-1]:
            trend = "STRONG_DOWNTREND"
            trend_strength = "STRONG"
        elif ema_9.iloc[-1] < ema_21.iloc[-1]:
            trend = "DOWNTREND"
            trend_strength = "MODERATE"
        else:
            trend = "NEUTRAL"
            trend_strength = "WEAK"
        
        # Volatility analysis
        returns = close.pct_change().fillna(0)
        volatility = returns.rolling(20).std() * np.sqrt(252) * 100
        avg_vol = volatility.mean()
        current_vol = volatility.iloc[-1]
        
        if current_vol > avg_vol * 1.5:
            vol_regime = "HIGH"
        elif current_vol < avg_vol * 0.7:
            vol_regime = "LOW"
        else:
            vol_regime = "NORMAL"
        
        # Momentum analysis
        mom_5 = close.iloc[-1] / close.iloc[-5] - 1 if len(close) >= 5 else 0
        mom_10 = close.iloc[-1] / close.iloc[-10] - 1 if len(close) >= 10 else 0
        
        if mom_5 > 0.02 and mom_10 > 0.03:
            momentum = "STRONG_BULLISH"
        elif mom_5 > 0.01:
            momentum = "BULLISH"
        elif mom_5 < -0.02 and mom_10 < -0.03:
            momentum = "STRONG_BEARISH"
        elif mom_5 < -0.01:
            momentum = "BEARISH"
        else:
            momentum = "NEUTRAL"
        
        return {
            "trend": trend,
            "trend_strength": trend_strength,
            "volatility": vol_regime,
            "momentum": momentum
        }


# ========================================================================================================
# ICT PATTERN DETECTOR
# ========================================================================================================
class ICTPatternDetector:
    """ICT (Inner Circle Trader) Pattern Detector"""
    
    @staticmethod
    def detect_fair_value_gap(df: pd.DataFrame) -> List[Pattern]:
        """Fair Value Gap detection"""
        patterns = []
        if len(df) < 3:
            return patterns
        
        for i in range(1, len(df) - 1):
            # Bullish FVG
            if df['low'].iloc[i + 1] > df['high'].iloc[i - 1]:
                gap_size = df['low'].iloc[i + 1] - df['high'].iloc[i - 1]
                gap_percent = (gap_size / df['high'].iloc[i - 1]) * 100
                
                if gap_percent > 0.1:
                    patterns.append(Pattern(
                        name="bullish_fvg",
                        type=PatternType.ICT,
                        direction=Direction.BULLISH,
                        confidence=min(gap_percent * 5, 80),
                        timestamp=str(df.index[i]),
                        price=float(df['close'].iloc[i]),
                        description=f"Bullish FVG at {gap_percent:.2f}%"
                    ))
            
            # Bearish FVG
            elif df['high'].iloc[i + 1] < df['low'].iloc[i - 1]:
                gap_size = df['low'].iloc[i - 1] - df['high'].iloc[i + 1]
                gap_percent = (gap_size / df['low'].iloc[i - 1]) * 100
                
                if gap_percent > 0.1:
                    patterns.append(Pattern(
                        name="bearish_fvg",
                        type=PatternType.ICT,
                        direction=Direction.BEARISH,
                        confidence=min(gap_percent * 5, 80),
                        timestamp=str(df.index[i]),
                        price=float(df['close'].iloc[i]),
                        description=f"Bearish FVG at {gap_percent:.2f}%"
                    ))
        
        return patterns[-10:]
    
    @staticmethod
    def detect_order_blocks(df: pd.DataFrame) -> List[Pattern]:
        """Order Block detection"""
        patterns = []
        if len(df) < 5:
            return patterns
        
        df['is_bullish'] = df['close'] > df['open']
        df['is_bearish'] = df['close'] < df['open']
        
        for i in range(2, len(df) - 2):
            # Bullish Order Block
            if (df['is_bullish'].iloc[i] and
                df['is_bearish'].iloc[i - 1] and
                df['low'].iloc[i] < df['low'].iloc[i - 1] and
                df['close'].iloc[i] > df['high'].iloc[i - 1]):
                
                patterns.append(Pattern(
                    name="bullish_order_block",
                    type=PatternType.ICT,
                    direction=Direction.BULLISH,
                    confidence=70,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="Bullish Order Block - Smart money buying zone"
                ))
            
            # Bearish Order Block
            elif (df['is_bearish'].iloc[i] and
                  df['is_bullish'].iloc[i - 1] and
                  df['high'].iloc[i] > df['high'].iloc[i - 1] and
                  df['close'].iloc[i] < df['low'].iloc[i - 1]):
                
                patterns.append(Pattern(
                    name="bearish_order_block",
                    type=PatternType.ICT,
                    direction=Direction.BEARISH,
                    confidence=70,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="Bearish Order Block - Smart money selling zone"
                ))
        
        return patterns[-10:]
    
    @staticmethod
    def detect_breaker_blocks(df: pd.DataFrame) -> List[Pattern]:
        """Breaker Block detection"""
        patterns = []
        if len(df) < 15:
            return patterns
        
        for i in range(10, len(df) - 1):
            recent_high = df['high'].iloc[i - 10:i].max()
            recent_low = df['low'].iloc[i - 10:i].min()
            
            # Bullish Breaker
            if (df['close'].iloc[i] > recent_high and
                df['close'].iloc[i - 1] < recent_high):
                patterns.append(Pattern(
                    name="bullish_breaker",
                    type=PatternType.ICT,
                    direction=Direction.BULLISH,
                    confidence=72,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="Bullish Breaker - Resistance turned support"
                ))
            
            # Bearish Breaker
            elif (df['close'].iloc[i] < recent_low and
                  df['close'].iloc[i - 1] > recent_low):
                patterns.append(Pattern(
                    name="bearish_breaker",
                    type=PatternType.ICT,
                    direction=Direction.BEARISH,
                    confidence=72,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="Bearish Breaker - Support turned resistance"
                ))
        
        return patterns[-10:]
    
    @staticmethod
    def detect_liquidity_sweeps(df: pd.DataFrame) -> List[Pattern]:
        """Liquidity Sweep detection"""
        patterns = []
        if len(df) < 25:
            return patterns
        
        for i in range(20, len(df)):
            swing_highs = df['high'].iloc[i - 20:i - 5].nlargest(3)
            swing_lows = df['low'].iloc[i - 20:i - 5].nsmallest(3)
            
            # Upward liquidity sweep (bearish)
            if len(swing_highs) > 0 and df['high'].iloc[i] > swing_highs.iloc[0] * 1.001:
                if df['close'].iloc[i] < swing_highs.iloc[0]:
                    patterns.append(Pattern(
                        name="liquidity_sweep_up",
                        type=PatternType.ICT,
                        direction=Direction.BEARISH_REVERSAL,
                        confidence=70,
                        timestamp=str(df.index[i]),
                        price=float(df['close'].iloc[i]),
                        description="Liquidity Sweep Above - Bearish reversal"
                    ))
            
            # Downward liquidity sweep (bullish)
            if len(swing_lows) > 0 and df['low'].iloc[i] < swing_lows.iloc[0] * 0.999:
                if df['close'].iloc[i] > swing_lows.iloc[0]:
                    patterns.append(Pattern(
                        name="liquidity_sweep_down",
                        type=PatternType.ICT,
                        direction=Direction.BULLISH_REVERSAL,
                        confidence=70,
                        timestamp=str(df.index[i]),
                        price=float(df['close'].iloc[i]),
                        description="Liquidity Sweep Below - Bullish reversal"
                    ))
        
        return patterns[-10:]
    
    @staticmethod
    def detect_break_of_structure(df: pd.DataFrame) -> List[Pattern]:
        """Break of Structure detection"""
        patterns = []
        if len(df) < 15:
            return patterns
        
        for i in range(10, len(df)):
            recent_high = df['high'].iloc[i - 10:i].max()
            recent_low = df['low'].iloc[i - 10:i].min()
            
            # Bullish BOS
            if df['high'].iloc[i] > recent_high * 1.005:
                bos_size = (df['high'].iloc[i] - recent_high) / recent_high * 100
                patterns.append(Pattern(
                    name="bullish_bos",
                    type=PatternType.ICT,
                    direction=Direction.BULLISH,
                    confidence=min(bos_size * 15, 80),
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description=f"Bullish BOS at {bos_size:.2f}%"
                ))
            
            # Bearish BOS
            elif df['low'].iloc[i] < recent_low * 0.995:
                bos_size = (recent_low - df['low'].iloc[i]) / recent_low * 100
                patterns.append(Pattern(
                    name="bearish_bos",
                    type=PatternType.ICT,
                    direction=Direction.BEARISH,
                    confidence=min(bos_size * 15, 80),
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description=f"Bearish BOS at {bos_size:.2f}%"
                ))
        
        return patterns[-10:]
    
    @staticmethod
    def detect_change_of_character(df: pd.DataFrame) -> List[Pattern]:
        """Change of Character detection"""
        patterns = []
        if len(df) < 20:
            return patterns
        
        for i in range(15, len(df)):
            recent_trend = df['close'].iloc[i - 10:i].pct_change().mean()
            
            # Bullish CHoCH
            if recent_trend < -0.001 and df['close'].iloc[i] > df['high'].iloc[i - 1]:
                patterns.append(Pattern(
                    name="bullish_choch",
                    type=PatternType.ICT,
                    direction=Direction.BULLISH,
                    confidence=75,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="Bullish Change of Character"
                ))
            
            # Bearish CHoCH
            elif recent_trend > 0.001 and df['close'].iloc[i] < df['low'].iloc[i - 1]:
                patterns.append(Pattern(
                    name="bearish_choch",
                    type=PatternType.ICT,
                    direction=Direction.BEARISH,
                    confidence=75,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="Bearish Change of Character"
                ))
        
        return patterns[-10:]
    
    @staticmethod
    def detect_optimal_trade_entry(df: pd.DataFrame) -> List[Pattern]:
        """Optimal Trade Entry detection (Fibonacci retracement)"""
        patterns = []
        if len(df) < 30:
            return patterns
        
        for i in range(25, len(df)):
            window = df.iloc[i - 20:i]
            if window.empty:
                continue
            
            high_idx = window['high'].idxmax()
            low_idx = window['low'].idxmin()
            
            if high_idx is not None and low_idx is not None:
                high_val = float(window.loc[high_idx, 'high'])
                low_val = float(window.loc[low_idx, 'low'])
                
                if high_val > low_val:
                    if window.index.get_loc(high_idx) < window.index.get_loc(low_idx):  # Downtrend
                        retrace = (high_val - df['close'].iloc[i]) / (high_val - low_val)
                        if 0.618 <= retrace <= 0.79:
                            patterns.append(Pattern(
                                name="bearish_ote",
                                type=PatternType.ICT,
                                direction=Direction.BEARISH,
                                confidence=78,
                                timestamp=str(df.index[i]),
                                price=float(df['close'].iloc[i]),
                                description=f"Bearish OTE at {retrace:.2f} retracement"
                            ))
                    else:  # Uptrend
                        retrace = (df['close'].iloc[i] - low_val) / (high_val - low_val)
                        if 0.618 <= retrace <= 0.79:
                            patterns.append(Pattern(
                                name="bullish_ote",
                                type=PatternType.ICT,
                                direction=Direction.BULLISH,
                                confidence=78,
                                timestamp=str(df.index[i]),
                                price=float(df['close'].iloc[i]),
                                description=f"Bullish OTE at {retrace:.2f} retracement"
                            ))
        
        return patterns[-10:]
    
    @staticmethod
    def detect_turtle_soup(df: pd.DataFrame) -> List[Pattern]:
        """Turtle Soup pattern (false breakout)"""
        patterns = []
        if len(df) < 30:
            return patterns
        
        for i in range(25, len(df)):
            period_high = df['high'].iloc[i - 20:i].max()
            period_low = df['low'].iloc[i - 20:i].min()
            
            # False breakout above (bearish)
            if df['high'].iloc[i] > period_high * 1.001 and df['close'].iloc[i] < period_high:
                patterns.append(Pattern(
                    name="turtle_soup_bearish",
                    type=PatternType.ICT,
                    direction=Direction.BEARISH,
                    confidence=70,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="Turtle Soup - False breakout above"
                ))
            
            # False breakout below (bullish)
            elif df['low'].iloc[i] < period_low * 0.999 and df['close'].iloc[i] > period_low:
                patterns.append(Pattern(
                    name="turtle_soup_bullish",
                    type=PatternType.ICT,
                    direction=Direction.BULLISH,
                    confidence=70,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="Turtle Soup - False breakout below"
                ))
        
        return patterns[-10:]
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> List[Pattern]:
        """Run all ICT pattern detectors"""
        patterns = []
        patterns.extend(ICTPatternDetector.detect_fair_value_gap(df))
        patterns.extend(ICTPatternDetector.detect_order_blocks(df))
        patterns.extend(ICTPatternDetector.detect_breaker_blocks(df))
        patterns.extend(ICTPatternDetector.detect_liquidity_sweeps(df))
        patterns.extend(ICTPatternDetector.detect_break_of_structure(df))
        patterns.extend(ICTPatternDetector.detect_change_of_character(df))
        patterns.extend(ICTPatternDetector.detect_optimal_trade_entry(df))
        patterns.extend(ICTPatternDetector.detect_turtle_soup(df))
        return patterns[-Config.MAX_PATTERNS:]


# ========================================================================================================
# CLASSICAL PATTERN DETECTOR
# ========================================================================================================
class ClassicalPatternDetector:
    """Classical chart pattern detector"""
    
    @staticmethod
    def detect_double_top_bottom(df: pd.DataFrame) -> List[Pattern]:
        """Double Top/Bottom detection"""
        patterns = []
        if len(df) < 30:
            return patterns
        
        for i in range(20, len(df)):
            # Double Top
            high1 = df['high'].iloc[i - 15:i - 5].max()
            high2 = df['high'].iloc[i - 5:i].max()
            
            if high1 > 0 and abs(high1 - high2) / high1 < 0.02 and df['close'].iloc[i] < high2 * 0.98:
                patterns.append(Pattern(
                    name="double_top",
                    type=PatternType.CLASSICAL,
                    direction=Direction.BEARISH,
                    confidence=72,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="Double Top - Bearish reversal"
                ))
            
            # Double Bottom
            low1 = df['low'].iloc[i - 15:i - 5].min()
            low2 = df['low'].iloc[i - 5:i].min()
            
            if low1 > 0 and abs(low1 - low2) / low1 < 0.02 and df['close'].iloc[i] > low2 * 1.02:
                patterns.append(Pattern(
                    name="double_bottom",
                    type=PatternType.CLASSICAL,
                    direction=Direction.BULLISH,
                    confidence=72,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="Double Bottom - Bullish reversal"
                ))
        
        return patterns[-5:]
    
    @staticmethod
    def detect_head_shoulders(df: pd.DataFrame) -> List[Pattern]:
        """Head and Shoulders detection"""
        patterns = []
        if len(df) < 40:
            return patterns
        
        for i in range(30, len(df)):
            # Head and Shoulders Top
            left_shoulder = df['high'].iloc[i - 25:i - 15].max()
            head = df['high'].iloc[i - 15:i - 5].max()
            right_shoulder = df['high'].iloc[i - 5:i].max()
            
            if (head > left_shoulder * 1.02 and head > right_shoulder * 1.02 and
                abs(left_shoulder - right_shoulder) / left_shoulder < 0.05 and
                df['close'].iloc[i] < head * 0.98):
                patterns.append(Pattern(
                    name="head_and_shoulders",
                    type=PatternType.CLASSICAL,
                    direction=Direction.BEARISH,
                    confidence=80,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="Head and Shoulders - Bearish reversal"
                ))
            
            # Inverse Head and Shoulders
            left_shoulder = df['low'].iloc[i - 25:i - 15].min()
            head = df['low'].iloc[i - 15:i - 5].min()
            right_shoulder = df['low'].iloc[i - 5:i].min()
            
            if (head < left_shoulder * 0.98 and head < right_shoulder * 0.98 and
                abs(left_shoulder - right_shoulder) / left_shoulder < 0.05 and
                df['close'].iloc[i] > head * 1.02):
                patterns.append(Pattern(
                    name="inverse_head_shoulders",
                    type=PatternType.CLASSICAL,
                    direction=Direction.BULLISH,
                    confidence=80,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="Inverse Head and Shoulders - Bullish reversal"
                ))
        
        return patterns[-5:]
    
    @staticmethod
    def detect_w_pattern(df: pd.DataFrame) -> List[Pattern]:
        """W Pattern (double bottom variant)"""
        patterns = []
        if len(df) < 35:
            return patterns
        
        for i in range(30, len(df)):
            first_bottom = df['low'].iloc[i - 25:i - 15].min()
            peak = df['high'].iloc[i - 15:i - 8].max()
            second_bottom = df['low'].iloc[i - 8:i - 2].min()
            
            if (first_bottom > 0 and second_bottom > 0 and peak > 0 and
                abs(first_bottom - second_bottom) / first_bottom < 0.03 and
                peak > first_bottom * 1.05 and
                df['close'].iloc[i] > peak * 0.98):
                patterns.append(Pattern(
                    name="w_pattern",
                    type=PatternType.CLASSICAL,
                    direction=Direction.BULLISH,
                    confidence=75,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="W Pattern - Bullish reversal"
                ))
        
        return patterns[-5:]
    
    @staticmethod
    def detect_m_pattern(df: pd.DataFrame) -> List[Pattern]:
        """M Pattern (double top variant)"""
        patterns = []
        if len(df) < 35:
            return patterns
        
        for i in range(30, len(df)):
            first_top = df['high'].iloc[i - 25:i - 15].max()
            bottom = df['low'].iloc[i - 15:i - 8].min()
            second_top = df['high'].iloc[i - 8:i - 2].max()
            
            if (first_top > 0 and second_top > 0 and bottom > 0 and
                abs(first_top - second_top) / first_top < 0.03 and
                bottom < first_top * 0.95 and
                df['close'].iloc[i] < bottom * 1.02):
                patterns.append(Pattern(
                    name="m_pattern",
                    type=PatternType.CLASSICAL,
                    direction=Direction.BEARISH,
                    confidence=75,
                    timestamp=str(df.index[i]),
                    price=float(df['close'].iloc[i]),
                    description="M Pattern - Bearish reversal"
                ))
        
        return patterns[-5:]
    
    @staticmethod
    def detect_triangle_patterns(df: pd.DataFrame) -> List[Pattern]:
        """Triangle patterns detection"""
        patterns = []
        if len(df) < 30:
            return patterns
        
        for i in range(25, len(df)):
            highs = df['high'].iloc[i - 20:i].values
            lows = df['low'].iloc[i - 20:i].values
            
            if len(highs) >= 5:
                x = np.arange(len(highs))
                high_slope = np.polyfit(x, highs, 1)[0]
                low_slope = np.polyfit(x, lows, 1)[0]
                
                # Rising Wedge (Bearish)
                if high_slope > 0 and low_slope > 0 and high_slope < low_slope * 1.1:
                    if df['close'].iloc[i] < lows[-1]:
                        patterns.append(Pattern(
                            name="rising_wedge",
                            type=PatternType.CLASSICAL,
                            direction=Direction.BEARISH,
                            confidence=75,
                            timestamp=str(df.index[i]),
                            price=float(df['close'].iloc[i]),
                            description="Rising Wedge - Bearish breakdown"
                        ))
                
                # Falling Wedge (Bullish)
                if high_slope < 0 and low_slope < 0 and low_slope < high_slope:
                    if df['close'].iloc[i] > highs[-1]:
                        patterns.append(Pattern(
                            name="falling_wedge",
                            type=PatternType.CLASSICAL,
                            direction=Direction.BULLISH,
                            confidence=75,
                            timestamp=str(df.index[i]),
                            price=float(df['close'].iloc[i]),
                            description="Falling Wedge - Bullish breakout"
                        ))
        
        return patterns[-5:]
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> List[Pattern]:
        """Run all classical pattern detectors"""
        patterns = []
        patterns.extend(ClassicalPatternDetector.detect_double_top_bottom(df))
        patterns.extend(ClassicalPatternDetector.detect_head_shoulders(df))
        patterns.extend(ClassicalPatternDetector.detect_w_pattern(df))
        patterns.extend(ClassicalPatternDetector.detect_m_pattern(df))
        patterns.extend(ClassicalPatternDetector.detect_triangle_patterns(df))
        return patterns[-Config.MAX_PATTERNS:]


# ========================================================================================================
# CANDLESTICK PATTERN DETECTOR
# ========================================================================================================
class CandlestickPatternDetector:
    """Candlestick pattern detector"""
    
    @staticmethod
    def _calculate_shadows(candle: pd.Series) -> tuple:
        body_top = max(candle['open'], candle['close'])
        body_bottom = min(candle['open'], candle['close'])
        upper_shadow = candle['high'] - body_top
        lower_shadow = body_bottom - candle['low']
        body = body_top - body_bottom
        return upper_shadow, lower_shadow, body
    
    @staticmethod
    def detect_doji(candle: pd.Series, idx, df) -> Optional[Pattern]:
        upper, lower, body = CandlestickPatternDetector._calculate_shadows(candle)
        total_range = candle['high'] - candle['low']
        
        if total_range > 0 and body / total_range < 0.1:
            return Pattern(
                name="doji",
                type=PatternType.CANDLESTICK,
                direction=Direction.NEUTRAL,
                confidence=50,
                timestamp=str(df.index[idx]),
                price=float(candle['close']),
                description="Doji - Market indecision"
            )
        return None
    
    @staticmethod
    def detect_hammer(candle: pd.Series, idx, df) -> Optional[Pattern]:
        upper, lower, body = CandlestickPatternDetector._calculate_shadows(candle)
        
        if body > 0 and lower > 2 * body and upper < body and candle['close'] > candle['open']:
            return Pattern(
                name="hammer",
                type=PatternType.CANDLESTICK,
                direction=Direction.BULLISH,
                confidence=70,
                timestamp=str(df.index[idx]),
                price=float(candle['close']),
                description="Hammer - Bullish reversal"
            )
        return None
    
    @staticmethod
    def detect_shooting_star(candle: pd.Series, idx, df) -> Optional[Pattern]:
        upper, lower, body = CandlestickPatternDetector._calculate_shadows(candle)
        
        if body > 0 and upper > 2 * body and lower < body and candle['close'] < candle['open']:
            return Pattern(
                name="shooting_star",
                type=PatternType.CANDLESTICK,
                direction=Direction.BEARISH,
                confidence=70,
                timestamp=str(df.index[idx]),
                price=float(candle['close']),
                description="Shooting Star - Bearish reversal"
            )
        return None
    
    @staticmethod
    def detect_marubozu(candle: pd.Series, idx, df) -> Optional[Pattern]:
        upper, lower, body = CandlestickPatternDetector._calculate_shadows(candle)
        
        if body > 0 and upper < body * 0.1 and lower < body * 0.1:
            direction = Direction.BULLISH if candle['close'] > candle['open'] else Direction.BEARISH
            return Pattern(
                name="marubozu",
                type=PatternType.CANDLESTICK,
                direction=direction,
                confidence=65,
                timestamp=str(df.index[idx]),
                price=float(candle['close']),
                description=f"Marubozu - Strong {direction.value} momentum"
            )
        return None
    
    @staticmethod
    def detect_engulfing(df: pd.DataFrame, idx: int) -> Optional[Pattern]:
        if idx < 1:
            return None
        
        curr = df.iloc[idx]
        prev = df.iloc[idx - 1]
        
        curr_bullish = curr['close'] > curr['open']
        curr_bearish = curr['close'] < curr['open']
        prev_bearish = prev['close'] < prev['open']
        prev_bullish = prev['close'] > prev['open']
        
        if curr_bullish and prev_bearish and curr['open'] < prev['close'] and curr['close'] > prev['open']:
            return Pattern(
                name="bullish_engulfing",
                type=PatternType.CANDLESTICK,
                direction=Direction.BULLISH,
                confidence=75,
                timestamp=str(df.index[idx]),
                price=float(curr['close']),
                description="Bullish Engulfing - Strong reversal"
            )
        
        elif curr_bearish and prev_bullish and curr['open'] > prev['close'] and curr['close'] < prev['open']:
            return Pattern(
                name="bearish_engulfing",
                type=PatternType.CANDLESTICK,
                direction=Direction.BEARISH,
                confidence=75,
                timestamp=str(df.index[idx]),
                price=float(curr['close']),
                description="Bearish Engulfing - Strong reversal"
            )
        
        return None
    
    @staticmethod
    def detect_harami(df: pd.DataFrame, idx: int) -> Optional[Pattern]:
        if idx < 1:
            return None
        
        curr = df.iloc[idx]
        prev = df.iloc[idx - 1]
        
        curr_range = abs(curr['close'] - curr['open'])
        prev_range = abs(prev['close'] - prev['open'])
        
        if prev_range == 0:
            return None
        
        if curr_range < prev_range * 0.6:
            if prev['close'] > prev['open']:  # Bullish previous
                if curr['close'] < prev['close'] and curr['open'] > prev['open']:
                    return Pattern(
                        name="bearish_harami",
                        type=PatternType.CANDLESTICK,
                        direction=Direction.BEARISH,
                        confidence=65,
                        timestamp=str(df.index[idx]),
                        price=float(curr['close']),
                        description="Bearish Harami"
                    )
            else:  # Bearish previous
                if curr['close'] > prev['close'] and curr['open'] < prev['open']:
                    return Pattern(
                        name="bullish_harami",
                        type=PatternType.CANDLESTICK,
                        direction=Direction.BULLISH,
                        confidence=65,
                        timestamp=str(df.index[idx]),
                        price=float(curr['close']),
                        description="Bullish Harami"
                    )
        
        return None
    
    @staticmethod
    def detect_morning_star(df: pd.DataFrame, idx: int) -> Optional[Pattern]:
        if idx < 2:
            return None
        
        c1 = df.iloc[idx - 2]
        c2 = df.iloc[idx - 1]
        c3 = df.iloc[idx]
        
        if c1['close'] < c1['open'] and c3['close'] > c3['open']:
            body2 = abs(c2['close'] - c2['open'])
            range2 = c2['high'] - c2['low']
            if range2 > 0 and (body2 / range2) < 0.3:
                if c2['low'] < c1['low'] and c3['open'] > c2['close']:
                    return Pattern(
                        name="morning_star",
                        type=PatternType.CANDLESTICK,
                        direction=Direction.BULLISH,
                        confidence=80,
                        timestamp=str(df.index[idx]),
                        price=float(c3['close']),
                        description="Morning Star - Bullish reversal"
                    )
        
        return None
    
    @staticmethod
    def detect_evening_star(df: pd.DataFrame, idx: int) -> Optional[Pattern]:
        if idx < 2:
            return None
        
        c1 = df.iloc[idx - 2]
        c2 = df.iloc[idx - 1]
        c3 = df.iloc[idx]
        
        if c1['close'] > c1['open'] and c3['close'] < c3['open']:
            body2 = abs(c2['close'] - c2['open'])
            range2 = c2['high'] - c2['low']
            if range2 > 0 and (body2 / range2) < 0.3:
                if c2['high'] > c1['high'] and c3['open'] < c2['close']:
                    return Pattern(
                        name="evening_star",
                        type=PatternType.CANDLESTICK,
                        direction=Direction.BEARISH,
                        confidence=80,
                        timestamp=str(df.index[idx]),
                        price=float(c3['close']),
                        description="Evening Star - Bearish reversal"
                    )
        
        return None
    
    @staticmethod
    def detect_three_white_soldiers(df: pd.DataFrame, idx: int) -> Optional[Pattern]:
        if idx < 2:
            return None
        
        if (df['close'].iloc[idx - 2] > df['open'].iloc[idx - 2] and
            df['close'].iloc[idx - 1] > df['open'].iloc[idx - 1] and
            df['close'].iloc[idx] > df['open'].iloc[idx] and
            df['close'].iloc[idx - 1] > df['close'].iloc[idx - 2] and
            df['close'].iloc[idx] > df['close'].iloc[idx - 1]):
            return Pattern(
                name="three_white_soldiers",
                type=PatternType.CANDLESTICK,
                direction=Direction.BULLISH,
                confidence=78,
                timestamp=str(df.index[idx]),
                price=float(df['close'].iloc[idx]),
                description="Three White Soldiers - Strong bullish continuation"
            )
        return None
    
    @staticmethod
    def detect_three_black_crows(df: pd.DataFrame, idx: int) -> Optional[Pattern]:
        if idx < 2:
            return None
        
        if (df['close'].iloc[idx - 2] < df['open'].iloc[idx - 2] and
            df['close'].iloc[idx - 1] < df['open'].iloc[idx - 1] and
            df['close'].iloc[idx] < df['open'].iloc[idx] and
            df['close'].iloc[idx - 1] < df['close'].iloc[idx - 2] and
            df['close'].iloc[idx] < df['close'].iloc[idx - 1]):
            return Pattern(
                name="three_black_crows",
                type=PatternType.CANDLESTICK,
                direction=Direction.BEARISH,
                confidence=78,
                timestamp=str(df.index[idx]),
                price=float(df['close'].iloc[idx]),
                description="Three Black Crows - Strong bearish continuation"
            )
        return None
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> List[Pattern]:
        """Run all candlestick pattern detectors"""
        patterns = []
        
        if len(df) < 10:
            return patterns
        
        # Single candle patterns
        for i in range(len(df) - 10, len(df)):
            candle = df.iloc[i]
            
            for detector in [
                CandlestickPatternDetector.detect_doji,
                CandlestickPatternDetector.detect_hammer,
                CandlestickPatternDetector.detect_shooting_star,
                CandlestickPatternDetector.detect_marubozu
            ]:
                pattern = detector(candle, i, df)
                if pattern:
                    patterns.append(pattern)
        
        # Multi-candle patterns
        for i in range(max(2, len(df) - 10), len(df)):
            for detector in [
                CandlestickPatternDetector.detect_engulfing,
                CandlestickPatternDetector.detect_harami,
                CandlestickPatternDetector.detect_morning_star,
                CandlestickPatternDetector.detect_evening_star,
                CandlestickPatternDetector.detect_three_white_soldiers,
                CandlestickPatternDetector.detect_three_black_crows
            ]:
                pattern = detector(df, i)
                if pattern:
                    patterns.append(pattern)
        
        return patterns[-Config.MAX_PATTERNS:]


# ========================================================================================================
# ML MODEL TRAINER
# ========================================================================================================
class MLModelTrainer:
    """ML Model Trainer with feature engineering"""
    
    def __init__(self, model_dir: str = "models"):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.models: Dict[str, Dict] = {}
        self.scalers: Dict[str, StandardScaler] = {}
        self._load_models()
    
    def _load_models(self):
        """Load saved models"""
        for model_file in self.model_dir.glob("*.joblib"):
            try:
                model_key = model_file.stem
                if not model_key.endswith('_scaler'):
                    model_data = joblib.load(model_file)
                    self.models[model_key] = model_data
                    
                    scaler_file = self.model_dir / f"{model_key}_scaler.joblib"
                    if scaler_file.exists():
                        self.scalers[model_key] = joblib.load(scaler_file)
                    
                    logger.info(f"Loaded model: {model_key}")
            except Exception as e:
                logger.error(f"Failed to load {model_file}: {e}")
    
    def _get_model_key(self, symbol: str, interval: str) -> str:
        return f"{symbol}_{interval}".replace("/", "_")
    
    def _engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Feature engineering for ML"""
        df = df.copy()
        
        # Returns
        df['return_1'] = df['close'].pct_change(1)
        df['return_5'] = df['close'].pct_change(5)
        df['return_10'] = df['close'].pct_change(10)
        df['volatility'] = df['return_1'].rolling(20).std() * np.sqrt(252)
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        df['rsi_14'] = 100 - (100 / (1 + rs))
        df['rsi_14_change'] = df['rsi_14'].diff(3)
        
        # MACD
        exp1 = df['close'].ewm(span=12).mean()
        exp2 = df['close'].ewm(span=26).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']
        
        # Bollinger
        sma20 = df['close'].rolling(20).mean()
        std20 = df['close'].rolling(20).std()
        bb_upper = sma20 + (std20 * 2)
        bb_lower = sma20 - (std20 * 2)
        bb_range = (bb_upper - bb_lower).replace(0, 1)
        df['bb_position'] = ((df['close'] - bb_lower) / bb_range * 100).clip(0, 100)
        df['bb_width'] = (bb_upper - bb_lower) / sma20
        
        # Moving averages
        df['sma20'] = df['close'].rolling(20).mean()
        df['sma50'] = df['close'].rolling(50).mean()
        df['price_to_sma20'] = df['close'] / df['sma20'] - 1
        df['price_to_sma50'] = df['close'] / df['sma50'] - 1
        df['sma20_above_sma50'] = (df['sma20'] > df['sma50']).astype(int)
        
        # Volume
        df['volume_sma20'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma20'].replace(0, 1)
        df['volume_trend'] = df['volume'].rolling(5).mean() / df['volume'].rolling(20).mean()
        
        # ATR
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['close'].shift()).abs()
        tr3 = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        df['atr_percent'] = df['atr'] / df['close']
        
        # Momentum
        df['momentum_5'] = df['close'].pct_change(5) * 100
        df['momentum_10'] = df['close'].pct_change(10) * 100
        
        # Clean up
        df = df.ffill().bfill()
        df = df.fillna(0)
        df = df.replace([np.inf, -np.inf], 0)
        
        return df
    
    def _prepare_training_data(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
        """Prepare features and labels"""
        df_features = self._engineer_features(df)
        
        feature_columns = [
            'return_1', 'return_5', 'return_10', 'volatility',
            'rsi_14', 'rsi_14_change',
            'macd', 'macd_signal', 'macd_histogram',
            'bb_position', 'bb_width',
            'price_to_sma20', 'price_to_sma50', 'sma20_above_sma50',
            'volume_ratio', 'volume_trend',
            'atr_percent',
            'momentum_5', 'momentum_10'
        ]
        
        # Target: 1 if price up in next 5 periods, 0 otherwise
        future_return = df['close'].shift(-5) / df['close'] - 1
        target = (future_return > 0.005).astype(int)
        
        features = df_features[feature_columns].copy()
        
        # Align
        valid_idx = ~(target.isna() | features.isna().any(axis=1))
        features = features[valid_idx]
        target = target[valid_idx]
        
        return features, target
    
    async def train(self, symbol: str, interval: str, df: pd.DataFrame, force: bool = False) -> Dict:
        """Train ML model"""
        model_key = self._get_model_key(symbol, interval)
        model_path = self.model_dir / f"{model_key}.joblib"
        
        # Check if retraining needed
        if not force and model_path.exists():
            model_data = joblib.load(model_path)
            last_train = datetime.fromisoformat(model_data.get('trained_at', '2000-01-01'))
            hours_since = (datetime.now() - last_train).total_seconds() / 3600
            if hours_since < Config.ML_RETRAIN_HOURS:
                return model_data
        
        logger.info(f"Training ML model for {symbol} @ {interval}")
        
        try:
            features, target = self._prepare_training_data(df)
            
            if len(features) < Config.ML_MIN_TRAINING_SAMPLES:
                raise ValueError(f"Insufficient samples: {len(features)}")
            
            logger.info(f"Training samples: {len(features)}, Features: {len(features.columns)}")
            
            # Time-series split
            split_idx = int(len(features) * 0.8)
            X_train, X_test = features.iloc[:split_idx], features.iloc[split_idx:]
            y_train, y_test = target.iloc[:split_idx], target.iloc[split_idx:]
            
            # Scale
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            # Train models
            models = {
                'xgboost': xgb.XGBClassifier(n_estimators=200, max_depth=8, learning_rate=0.05, random_state=42),
                'lightgbm': lgb.LGBMClassifier(n_estimators=200, max_depth=10, learning_rate=0.05, random_state=42, verbose=-1),
                'random_forest': RandomForestClassifier(n_estimators=200, max_depth=15, random_state=42)
            }
            
            results = {}
            trained_models = {}
            
            for name, model in models.items():
                try:
                    model.fit(X_train_scaled, y_train)
                    y_pred = model.predict(X_test_scaled)
                    
                    accuracy = accuracy_score(y_test, y_pred)
                    precision = precision_score(y_test, y_pred, zero_division=0)
                    recall = recall_score(y_test, y_pred, zero_division=0)
                    
                    # Time series cross-validation
                    tscv = TimeSeriesSplit(n_splits=3)
                    cv_scores = cross_val_score(model, X_train_scaled, y_train, cv=tscv, scoring='accuracy')
                    
                    results[name] = {
                        'accuracy': round(accuracy * 100, 2),
                        'precision': round(precision * 100, 2),
                        'recall': round(recall * 100, 2),
                        'cv_mean': round(cv_scores.mean() * 100, 2),
                        'cv_std': round(cv_scores.std() * 100, 2)
                    }
                    
                    trained_models[name] = model
                    logger.info(f"✅ {name}: Accuracy={accuracy*100:.1f}%")
                    
                except Exception as e:
                    logger.error(f"❌ {name} failed: {e}")
                    results[name] = {'error': str(e)}
            
            # Select best model
            best_model = max(
                [(n, r.get('accuracy', 0)) for n, r in results.items() if 'accuracy' in r],
                key=lambda x: x[1]
            )[0]
            
            # Save
            model_data = {
                'models': trained_models,
                'best_model': best_model,
                'results': results,
                'feature_names': list(features.columns),
                'trained_at': datetime.now().isoformat(),
                'symbol': symbol,
                'interval': interval,
                'training_samples': len(features)
            }
            
            joblib.dump(model_data, model_path)
            joblib.dump(scaler, self.model_dir / f"{model_key}_scaler.joblib")
            
            self.models[model_key] = model_data
            self.scalers[model_key] = scaler
            
            logger.info(f"✅ Model saved: {model_key} (best: {best_model})")
            
            return model_data
            
        except Exception as e:
            logger.error(f"Training failed: {e}")
            raise
    
    async def predict(self, symbol: str, interval: str, df: pd.DataFrame) -> MLPrediction:
        """Make prediction using trained model"""
        model_key = self._get_model_key(symbol, interval)
        
        # Load model if not in memory
        if model_key not in self.models:
            model_path = self.model_dir / f"{model_key}.joblib"
            if model_path.exists():
                self.models[model_key] = joblib.load(model_path)
                scaler_path = self.model_dir / f"{model_key}_scaler.joblib"
                if scaler_path.exists():
                    self.scalers[model_key] = joblib.load(scaler_path)
            else:
                # Return fallback prediction
                return MLPrediction(
                    signal=SignalType.NEUTRAL,
                    confidence=50.0,
                    probability=0.5,
                    model_version="fallback",
                    features_used=[],
                    buy_probability=0.5,
                    sell_probability=0.5
                )
        
        model_data = self.models[model_key]
        scaler = self.scalers.get(model_key)
        
        # Engineer features
        df_features = self._engineer_features(df)
        feature_names = model_data['feature_names']
        
        # Get latest features
        latest = df_features[feature_names].iloc[-1:].fillna(0)
        
        # Scale
        if scaler:
            X_scaled = scaler.transform(latest)
        else:
            X_scaled = latest.values
        
        # Get best model
        best_model = model_data['models'][model_data['best_model']]
        
        # Predict probabilities
        if hasattr(best_model, 'predict_proba'):
            proba = best_model.predict_proba(X_scaled)[0]
            buy_prob = float(proba[1]) if len(proba) > 1 else 0.5
            sell_prob = float(proba[0]) if len(proba) > 0 else 0.5
        else:
            pred = best_model.predict(X_scaled)[0]
            buy_prob = 0.8 if pred == 1 else 0.2
            sell_prob = 0.2 if pred == 1 else 0.8
        
        # Determine signal
        confidence = buy_prob * 100
        
        if buy_prob > 0.7:
            signal = SignalType.STRONG_BUY
        elif buy_prob > 0.55:
            signal = SignalType.BUY
        elif sell_prob > 0.7:
            signal = SignalType.STRONG_SELL
        elif sell_prob > 0.55:
            signal = SignalType.SELL
        else:
            signal = SignalType.NEUTRAL
        
        return MLPrediction(
            signal=signal,
            confidence=round(confidence, 1),
            probability=round(buy_prob, 3),
            model_version=model_data['best_model'],
            features_used=feature_names[:10],
            buy_probability=round(buy_prob, 3),
            sell_probability=round(sell_prob, 3)
        )
    
    def get_model_info(self, symbol: str, interval: str) -> Optional[Dict]:
        """Get model info"""
        model_key = self._get_model_key(symbol, interval)
        if model_key in self.models:
            data = self.models[model_key]
            return {
                'best_model': data['best_model'],
                'trained_at': data['trained_at'],
                'results': data['results'],
                'training_samples': data['training_samples'],
                'feature_names': data['feature_names'][:10]
            }
        return None


# ========================================================================================================
# FASTAPI APPLICATION
# ========================================================================================================
app = FastAPI(
    title="ICTSMARTPRO ML - Production API",
    description="Professional Crypto Analysis with ML + 30+ Patterns",
    version="3.0.0"
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware)

# Global instances
data_fetcher = ExchangeDataFetcher()
ml_trainer = MLModelTrainer(model_dir=Config.ML_MODEL_DIR)
startup_time = time.time()


# ========================================================================================================
# API ENDPOINTS
# ========================================================================================================

# ========================================================================================================
# STATIC FILES & TEMPLATES
# ========================================================================================================
@app.get("/", response_class=HTMLResponse)
async def root():
    """Ana sayfa"""
    index_path = Path(__file__).parent / "templates" / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>ICTSMARTPRO ML API</h1><p>Çalışıyor. <a href='/docs'>Dökümanlar</a></p>")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Dashboard sayfası"""
    dashboard_path = Path(__file__).parent / "templates" / "dashboard.html"
    if dashboard_path.exists():
        return FileResponse(dashboard_path)
    return HTMLResponse("<h1>Dashboard bulunamadı</h1><p>dashboard.html dosyası eksik</p>", status_code=404)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "models_loaded": len(ml_trainer.models),
        "uptime": str(timedelta(seconds=int(time.time() - startup_time)))
    }


@app.get("/api/analyze/{symbol}", response_model=AnalysisResponse)
async def analyze_symbol(
    symbol: str,
    interval: str = Query("1h", regex="^(1m|5m|15m|30m|1h|4h|1d|1w)$"),
    limit: int = Query(500, ge=100, le=1000),
    background_tasks: BackgroundTasks = None
):
    """Full analysis with ML + all patterns"""
    
    # Format symbol
    symbol = symbol.upper()
    if not symbol.endswith("USDT") and symbol not in ["BTC", "ETH", "BNB"]:
        symbol = f"{symbol}USDT"
    
    logger.info(f"Analysis: {symbol} @ {interval}")
    start_time_local = time.time()
    
    try:
        # Fetch data
        async with data_fetcher as fetcher:
            candles = await fetcher.get_candles(symbol, interval, limit)
        
        if not candles or len(candles) < Config.MIN_CANDLES:
            raise HTTPException(422, f"Insufficient data: {len(candles) if candles else 0}")
        
        # DataFrame
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp').sort_index()
        
        # Technical indicators
        indicators = TechnicalIndicatorCalculator.calculate_all(df)
        technical = {k: float(v.iloc[-1]) for k, v in indicators.items()}
        
        # Market structure
        market_structure = MarketStructureAnalyzer.analyze(df)
        
        # Pattern detection
        ict_patterns = ICTPatternDetector.analyze(df)
        classical_patterns = ClassicalPatternDetector.analyze(df)
        candlestick_patterns = CandlestickPatternDetector.analyze(df)
        
        # ML Prediction
        ml_pred = await ml_trainer.predict(symbol, interval, df)
        
        # Auto-train if needed
        if background_tasks and Config.ML_AUTO_RETRAIN:
            model_info = ml_trainer.get_model_info(symbol, interval)
            if not model_info:
                logger.info(f"Scheduling training for {symbol}")
                background_tasks.add_task(
                    ml_trainer.train,
                    symbol=symbol,
                    interval=interval,
                    df=df,
                    force=False
                )
        
        # Model info
        model_info = ml_trainer.get_model_info(symbol, interval) or {
            'best_model': 'none',
            'trained_at': 'never',
            'results': {},
            'training_samples': 0,
            'feature_names': []
        }
        
        # Price data
        last = df.iloc[-1]
        first = df.iloc[0]
        
        response = AnalysisResponse(
            success=True,
            symbol=symbol,
            interval=interval,
            timestamp=datetime.now(timezone.utc).isoformat(),
            price={
                'current': float(last['close']),
                'open': float(last['open']),
                'high': float(last['high']),
                'low': float(last['low']),
                'volume': float(last['volume']),
                'change': float((last['close'] / first['close'] - 1) * 100),
                'change_24h': float((last['close'] / df.iloc[-min(24, len(df))]['close'] - 1) * 100) if len(df) >= 24 else 0
            },
            ml_prediction=ml_pred,
            technical=technical,
            ict_patterns=ict_patterns,
            classical_patterns=classical_patterns,
            candlestick_patterns=candlestick_patterns,
            market_structure=market_structure,
            active_sources=data_fetcher.get_active_sources(),
            data_points=len(df),
            model_info=model_info,
            performance_ms=round((time.time() - start_time_local) * 1000, 2)
        )
        
        logger.info(f"✅ Complete: {ml_pred.signal.value} ({ml_pred.confidence:.1f}%) | "
                   f"ICT:{len(ict_patterns)} Class:{len(classical_patterns)} Candle:{len(candlestick_patterns)} | "
                   f"{response.performance_ms}ms")
        
        return response
        
    except Exception as e:
        logger.exception(f"Analysis failed: {e}")
        raise HTTPException(500, f"Analysis failed: {str(e)[:200]}")


@app.post("/api/train/{symbol}")
async def train_model(
    symbol: str,
    interval: str = Query("1h", regex="^(1m|5m|15m|30m|1h|4h|1d|1w)$"),
    force: bool = False,
    background_tasks: BackgroundTasks = None
):
    """Train ML model"""
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    
    logger.info(f"Training request: {symbol} @ {interval}")
    
    try:
        async with data_fetcher as fetcher:
            candles = await fetcher.get_candles(symbol, interval, 1000)
        
        if not candles or len(candles) < Config.ML_MIN_TRAINING_SAMPLES:
            raise HTTPException(422, f"Insufficient data: {len(candles) if candles else 0}")
        
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp').sort_index()
        
        if background_tasks:
            background_tasks.add_task(ml_trainer.train, symbol, interval, df, force)
            return {"success": True, "message": f"Training started for {symbol}"}
        else:
            result = await ml_trainer.train(symbol, interval, df, force)
            return {"success": True, "message": "Training completed", "result": result}
            
    except Exception as e:
        logger.error(f"Training failed: {e}")
        raise HTTPException(500, f"Training failed: {str(e)[:200]}")


@app.get("/api/models")
async def list_models():
    """List all trained models"""
    models = []
    for model_file in Path(Config.ML_MODEL_DIR).glob("*_meta.json"):
        try:
            with open(model_file, 'r') as f:
                data = json.load(f)
                models.append({
                    'symbol': data.get('symbol'),
                    'interval': data.get('interval'),
                    'trained_at': data.get('trained_at'),
                    'best_model': data.get('best_model'),
                    'accuracy': data.get('results', {}).get(data.get('best_model'), {}).get('accuracy', 0)
                })
        except:
            continue
    
    return {"success": True, "count": len(models), "models": models}


@app.get("/api/stats")
async def get_stats():
    """System stats"""
    stats = data_fetcher.get_stats()
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime": str(timedelta(seconds=int(time.time() - startup_time))),
        "exchange_stats": stats,
        "models_loaded": len(ml_trainer.models)
    }


@app.websocket("/ws/{symbol}")
async def websocket_endpoint(websocket: WebSocket, symbol: str):
    """WebSocket price feed"""
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    
    await websocket.accept()
    logger.info(f"WebSocket connected: {symbol}")
    
    try:
        last_price = None
        while True:
            async with data_fetcher as fetcher:
                price = await fetcher.get_current_price(symbol)
            
            if price and price != last_price:
                await websocket.send_json({
                    "type": "price",
                    "symbol": symbol,
                    "price": round(price, 2),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                last_price = price
            
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {symbol}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")


# ========================================================================================================
# STARTUP
# ========================================================================================================
@app.on_event("startup")
async def startup():
    logger.info("=" * 70)
    logger.info("🚀 ICTSMARTPRO ML Production API Started")
    logger.info("=" * 70)
    logger.info(f"Environment: {Config.ENV}")
    logger.info(f"Models loaded: {len(ml_trainer.models)}")
    logger.info(f"Patterns: ICT(8), Classical(5), Candlestick(10+)")
    logger.info(f"Auto-retrain: {Config.ML_AUTO_RETRAIN}")
    logger.info("=" * 70)


# ========================================================================================================
# MAIN
# ========================================================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=Config.PORT,
        reload=Config.DEBUG,
        log_level="info"
    )
