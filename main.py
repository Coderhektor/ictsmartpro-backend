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
from functools import wraps
import hashlib
import secrets
from concurrent.futures import ThreadPoolExecutor

# ML Libraries
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split, cross_val_score, TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import xgboost as xgb
import lightgbm as lgb

# FastAPI
from fastapi import FastAPI, Request, HTTPException, Query, BackgroundTasks, WebSocket, WebSocketDisconnect, Depends, Security
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.security import APIKeyHeader

# Pydantic
from pydantic import BaseModel, Field

# Async HTTP
import aiohttp
from aiohttp import ClientTimeout, TCPConnector

# ========================================================================================================
# PRODUCTION LOGGING (JSON Format)
# ========================================================================================================
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
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
    HOST = os.getenv("HOST", "0.0.0.0")
    
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
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
    API_KEY = os.getenv("API_KEY", "")
    RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
    RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

# ========================================================================================================
# SECURITY & RATE LIMITING
# ========================================================================================================
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

class RateLimiter:
    def __init__(self):
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    async def is_allowed(self, client_id: str) -> bool:
        async with self._lock:
            now = time.time()
            window_start = now - Config.RATE_LIMIT_WINDOW
            self.requests[client_id] = [t for t in self.requests[client_id] if t > window_start]
            if len(self.requests[client_id]) >= Config.RATE_LIMIT_REQUESTS:
                return False
            self.requests[client_id].append(now)
            return True

rate_limiter = RateLimiter()

async def get_api_key(api_key: str = Security(api_key_header)) -> str:
    if Config.API_KEY and api_key != Config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return api_key or "anonymous"

async def check_rate_limit(request: Request, api_key: str = Depends(get_api_key)):
    client_id = request.client.host if request.client else "unknown"
    if not await rate_limiter.is_allowed(client_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

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
    
    async def __aenter__(self):
        await self.ensure_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    
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
                timeout=aiohttp.ClientTimeout(total=exchange['timeout'])
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
        interval_ms = self._interval_to_ms(interval)
        timestamp_map = defaultdict(list)
        for exchange_candles in all_candles:
            for candle in exchange_candles:
                rounded_ts = (candle["timestamp"] // interval_ms) * interval_ms
                timestamp_map[rounded_ts].append(candle)
        merged = []
        for timestamp in sorted(timestamp_map.keys()):
            candles = timestamp_map[timestamp]
            if len(candles) >= 1:
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
        if self._is_cache_valid(cache_key):
            logger.info(f"Cache hit: {symbol} {interval}")
            return self.cache[cache_key]['data'][-limit:]
        logger.info(f"Fetching {symbol} {interval} from exchanges...")
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
        merged = self._merge_candles(valid_results, interval)
        if len(merged) < Config.MIN_CANDLES:
            logger.warning(f"Only {len(merged)} merged candles")
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
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
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
        df = df.copy()
        df['is_bullish'] = df['close'] > df['open']
        df['is_bearish'] = df['close'] < df['open']
        for i in range(2, len(df) - 2):
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
                    if window.index.get_loc(high_idx) < window.index.get_loc(low_idx):
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
                    else:
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
            if prev['close'] > prev['open']:
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
            else:
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
        self.executor = ThreadPoolExecutor(max_workers=4)
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
        df['return_1'] = df['close'].pct_change(1)
        df['return_5'] = df['close'].pct_change(5)
        df['return_10'] = df['close'].pct_change(10)
        df['volatility'] = df['return_1'].rolling(20).std() * np.sqrt(252)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        df['rsi_14'] = 100 - (100 / (1 + rs))
        df['rsi_14_change'] = df['rsi_14'].diff(3)
        exp1 = df['close'].ewm(span=12).mean()
        exp2 = df['close'].ewm(span=26).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']
        sma20 = df['close'].rolling(20).mean()
        std20 = df['close'].rolling(20).std()
        bb_upper = sma20 + (std20 * 2)
        bb_lower = sma20 - (std20 * 2)
        bb_range = (bb_upper - bb_lower).replace(0, 1)
        df['bb_position'] = ((df['close'] - bb_lower) / bb_range * 100).clip(0, 100)
        df['bb_width'] = (bb_upper - bb_lower) / sma20
        df['sma20'] = df['close'].rolling(20).mean()
        df['sma50'] = df['close'].rolling(50).mean()
        df['price_to_sma20'] = df['close'] / df['sma20'] - 1
        df['price_to_sma50'] = df['close'] / df['sma50'] - 1
        df['sma20_above_sma50'] = (df['sma20'] > df['sma50']).astype(int)
        df['volume_sma20'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma20'].replace(0, 1)
        df['volume_trend'] = df['volume'].rolling(5).mean() / df['volume'].rolling(20).mean()
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['close'].shift()).abs()
        tr3 = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        df['atr_percent'] = df['atr'] / df['close']
        df['momentum_5'] = df['close'].pct_change(5) * 100
        df['momentum_10'] = df['close'].pct_change(10) * 100
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
        future_return = df['close'].shift(-5) / df['close'] - 1
        target = (future_return > 0.005).astype(int)
        features = df_features[feature_columns].copy()
        valid_idx = ~(target.isna() | features.isna().any(axis=1))
        features = features[valid_idx]
        target = target[valid_idx]
        return features, target
    
    def _train_sync(self, symbol: str, interval: str, df: pd.DataFrame, force: bool = False) -> Dict:
        """Synchronous training logic (runs in executor)"""
        model_key = self._get_model_key(symbol, interval)
        model_path = self.model_dir / f"{model_key}.joblib"
        if not force and model_path.exists():
            model_data = joblib.load(model_path)
            last_train = datetime.fromisoformat(model_data.get('trained_at', '2000-01-01'))
            hours_since = (datetime.now() - last_train).total_seconds() / 3600
            if hours_since < Config.ML_RETRAIN_HOURS:
                return model_data
        logger.info(f"Training ML model for {symbol} @ {interval}")
        features, target = self._prepare_training_data(df)
        if len(features) < Config.ML_MIN_TRAINING_SAMPLES:
            raise ValueError(f"Insufficient samples: {len(features)}")
        logger.info(f"Training samples: {len(features)}, Features: {len(features.columns)}")
        split_idx = int(len(features) * 0.8)
        X_train, X_test = features.iloc[:split_idx], features.iloc[split_idx:]
        y_train, y_test = target.iloc[:split_idx], target.iloc[split_idx:]
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
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
        best_model = max(
            [(n, r.get('accuracy', 0)) for n, r in results.items() if 'accuracy' in r],
            key=lambda x: x[1]
        )[0]
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
    
    async def train(self, symbol: str, interval: str, df: pd.DataFrame, force: bool = False) -> Dict:
        """Train ML model (non-blocking)"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._train_sync, symbol, interval, df, force)
    
    def _predict_sync(self, symbol: str, interval: str, df: pd.DataFrame) -> MLPrediction:
        """Synchronous prediction logic"""
        model_key = self._get_model_key(symbol, interval)
        if model_key not in self.models:
            model_path = self.model_dir / f"{model_key}.joblib"
            if model_path.exists():
                self.models[model_key] = joblib.load(model_path)
                scaler_path = self.model_dir / f"{model_key}_scaler.joblib"
                if scaler_path.exists():
                    self.scalers[model_key] = joblib.load(scaler_path)
            else:
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
        df_features = self._engineer_features(df)
        feature_names = model_data['feature_names']
        latest = df_features[feature_names].iloc[-1:].fillna(0)
        if scaler:
            X_scaled = scaler.transform(latest)
        else:
            X_scaled = latest.values
        best_model = model_data['models'][model_data['best_model']]
        if hasattr(best_model, 'predict_proba'):
            proba = best_model.predict_proba(X_scaled)[0]
            buy_prob = float(proba[1]) if len(proba) > 1 else 0.5
            sell_prob = float(proba[0]) if len(proba) > 0 else 0.5
        else:
            pred = best_model.predict(X_scaled)[0]
            buy_prob = 0.8 if pred == 1 else 0.2
            sell_prob = 0.2 if pred == 1 else 0.8
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
    
    async def predict(self, symbol: str, interval: str, df: pd.DataFrame) -> MLPrediction:
        """Make prediction using trained model (non-blocking)"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._predict_sync, symbol, interval, df)
    
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
# GLOBAL EXCEPTION HANDLER
# ========================================================================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Global exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": str(exc)[:200]}
    )

# ========================================================================================================
# API ENDPOINTS
# ========================================================================================================
@app.get("/", response_class=HTMLResponse)
async def root():
    """Ana sayfa"""
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>ICTSMARTPRO ML API</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
            h1 { color: #2c3e50; }
            .endpoint { background: #f8f9fa; padding: 15px; margin: 10px 0; border-radius: 5px; }
            .method { display: inline-block; padding: 5px 10px; border-radius: 3px; font-weight: bold; }
            .get { background: #61affe; color: white; }
            .post { background: #49cc90; color: white; }
        </style>
    </head>
    <body>
        <h1>🚀 ICTSMARTPRO ML API</h1>
        <p>Production Ready - Crypto Analysis with ML</p>
        <div class="endpoint">
            <span class="method get">GET</span>
            <strong>/docs</strong> - Swagger Documentation
        </div>
        <div class="endpoint">
            <span class="method get">GET</span>
            <strong>/health</strong> - Health Check
        </div>
        <div class="endpoint">
            <span class="method get">GET</span>
            <strong>/api/analyze/{symbol}</strong> - Full Analysis
        </div>
        <div class="endpoint">
            <span class="method post">POST</span>
            <strong>/api/train/{symbol}</strong> - Train Model
        </div>
        <div class="endpoint">
            <span class="method get">GET</span>
            <strong>/api/models</strong> - List Models
        </div>
        <div class="endpoint">
            <span class="method get">GET</span>
            <strong>/api/stats</strong> - System Stats
        </div>
    </body>
    </html>
    """)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Dashboard sayfası - Kullanıcı dostu görüntüleme"""
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ICTSMARTPRO Dashboard</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }
            .container {
                max-width: 1400px;
                margin: 0 auto;
            }
            .header {
                background: white;
                padding: 30px;
                border-radius: 15px;
                margin-bottom: 20px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                text-align: center;
            }
            .header h1 {
                color: #2c3e50;
                font-size: 2.5em;
                margin-bottom: 10px;
            }
            .header p {
                color: #7f8c8d;
                font-size: 1.1em;
            }
            .search-box {
                background: white;
                padding: 25px;
                border-radius: 15px;
                margin-bottom: 20px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                display: flex;
                gap: 15px;
                flex-wrap: wrap;
                align-items: center;
            }
            .search-box input, .search-box select {
                padding: 12px 20px;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                font-size: 16px;
                flex: 1;
                min-width: 150px;
            }
            .search-box input:focus, .search-box select:focus {
                outline: none;
                border-color: #667eea;
            }
            .search-box button {
                padding: 12px 30px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                cursor: pointer;
                transition: transform 0.2s;
            }
            .search-box button:hover {
                transform: translateY(-2px);
            }
            .search-box button:disabled {
                opacity: 0.6;
                cursor: not-allowed;
            }
            .status-bar {
                background: white;
                padding: 15px 25px;
                border-radius: 15px;
                margin-bottom: 20px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                display: flex;
                justify-content: space-between;
                align-items: center;
                flex-wrap: wrap;
                gap: 15px;
            }
            .status-item {
                display: flex;
                align-items: center;
                gap: 8px;
            }
            .status-dot {
                width: 12px;
                height: 12px;
                border-radius: 50%;
                background: #2ecc71;
                animation: pulse 2s infinite;
            }
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
            }
            .grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
                margin-bottom: 20px;
            }
            .card {
                background: white;
                border-radius: 15px;
                padding: 25px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            }
            .card h3 {
                color: #2c3e50;
                margin-bottom: 20px;
                padding-bottom: 10px;
                border-bottom: 3px solid #667eea;
                font-size: 1.3em;
            }
            .price-card {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .price-card h3 {
                color: white;
                border-bottom-color: rgba(255,255,255,0.3);
            }
            .price-value {
                font-size: 2.5em;
                font-weight: bold;
                margin: 15px 0;
            }
            .price-change {
                font-size: 1.2em;
                padding: 8px 15px;
                border-radius: 20px;
                display: inline-block;
            }
            .price-change.positive {
                background: rgba(46, 204, 113, 0.3);
            }
            .price-change.negative {
                background: rgba(231, 76, 60, 0.3);
            }
            .ml-signal {
                text-align: center;
                padding: 30px;
            }
            .signal-badge {
                display: inline-block;
                padding: 15px 40px;
                border-radius: 50px;
                font-size: 1.8em;
                font-weight: bold;
                margin: 20px 0;
                text-transform: uppercase;
            }
            .signal-STRONG_BUY {
                background: linear-gradient(135deg, #00b894 0%, #00cec9 100%);
                color: white;
            }
            .signal-BUY {
                background: linear-gradient(135deg, #55efc4 0%, #81ecec 100%);
                color: #2d3436;
            }
            .signal-NEUTRAL {
                background: linear-gradient(135deg, #b2bec3 0%, #dfe6e9 100%);
                color: #2d3436;
            }
            .signal-SELL {
                background: linear-gradient(135deg, #fab1a0 0%, #ff7675 100%);
                color: white;
            }
            .signal-STRONG_SELL {
                background: linear-gradient(135deg, #d63031 0%, #e17055 100%);
                color: white;
            }
            .confidence-meter {
                background: #f0f0f0;
                border-radius: 10px;
                height: 30px;
                margin: 20px 0;
                overflow: hidden;
                position: relative;
            }
            .confidence-fill {
                height: 100%;
                background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
                border-radius: 10px;
                transition: width 0.5s ease;
                display: flex;
                align-items: center;
                justify-content: flex-end;
                padding-right: 15px;
                color: white;
                font-weight: bold;
            }
            .indicator-grid {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 15px;
            }
            .indicator-item {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 10px;
                text-align: center;
            }
            .indicator-label {
                color: #7f8c8d;
                font-size: 0.9em;
                margin-bottom: 5px;
            }
            .indicator-value {
                font-size: 1.3em;
                font-weight: bold;
                color: #2c3e50;
            }
            .indicator-value.bullish {
                color: #27ae60;
            }
            .indicator-value.bearish {
                color: #e74c3c;
            }
            .pattern-list {
                max-height: 400px;
                overflow-y: auto;
            }
            .pattern-item {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 10px;
                margin-bottom: 10px;
                border-left: 5px solid #667eea;
            }
            .pattern-item.bullish {
                border-left-color: #27ae60;
            }
            .pattern-item.bearish {
                border-left-color: #e74c3c;
            }
            .pattern-item.neutral {
                border-left-color: #95a5a6;
            }
            .pattern-name {
                font-weight: bold;
                color: #2c3e50;
                margin-bottom: 5px;
                text-transform: capitalize;
            }
            .pattern-type {
                font-size: 0.85em;
                color: #7f8c8d;
                background: #e0e0e0;
                padding: 3px 10px;
                border-radius: 15px;
                display: inline-block;
                margin-bottom: 8px;
            }
            .pattern-confidence {
                font-size: 0.9em;
                color: #667eea;
                font-weight: bold;
            }
            .pattern-description {
                color: #7f8c8d;
                font-size: 0.9em;
                margin-top: 8px;
            }
            .market-structure {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 15px;
            }
            .structure-item {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 10px;
                text-align: center;
            }
            .structure-label {
                color: #7f8c8d;
                font-size: 0.9em;
                margin-bottom: 5px;
            }
            .structure-value {
                font-size: 1.1em;
                font-weight: bold;
                padding: 8px 15px;
                border-radius: 20px;
                display: inline-block;
            }
            .structure-value.uptrend {
                background: #d4edda;
                color: #155724;
            }
            .structure-value.downtrend {
                background: #f8d7da;
                color: #721c24;
            }
            .structure-value.neutral {
                background: #e2e3e5;
                color: #383d41;
            }
            .loading {
                text-align: center;
                padding: 50px;
                color: white;
                font-size: 1.5em;
            }
            .loading-spinner {
                border: 5px solid #f3f3f3;
                border-top: 5px solid #667eea;
                border-radius: 50%;
                width: 50px;
                height: 50px;
                animation: spin 1s linear infinite;
                margin: 0 auto 20px;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            .error-message {
                background: #f8d7da;
                color: #721c24;
                padding: 20px;
                border-radius: 10px;
                margin: 20px 0;
                text-align: center;
            }
            .hidden {
                display: none;
            }
            .tab-container {
                margin-bottom: 20px;
            }
            .tabs {
                display: flex;
                gap: 10px;
                margin-bottom: 15px;
                flex-wrap: wrap;
            }
            .tab {
                padding: 10px 25px;
                background: white;
                border: none;
                border-radius: 25px;
                cursor: pointer;
                font-weight: bold;
                transition: all 0.3s;
                box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            }
            .tab.active {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .tab:hover:not(.active) {
                transform: translateY(-2px);
            }
            .tab-content {
                display: none;
            }
            .tab-content.active {
                display: block;
            }
            .sources-list {
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
            }
            .source-badge {
                background: #e0e0e0;
                padding: 8px 15px;
                border-radius: 20px;
                font-size: 0.9em;
            }
            .source-badge.active {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .model-info {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 10px;
                margin-top: 15px;
            }
            .model-info-row {
                display: flex;
                justify-content: space-between;
                padding: 8px 0;
                border-bottom: 1px solid #e0e0e0;
            }
            .model-info-row:last-child {
                border-bottom: none;
            }
            .probability-bars {
                margin: 20px 0;
            }
            .prob-bar-container {
                display: flex;
                align-items: center;
                gap: 15px;
                margin-bottom: 10px;
            }
            .prob-label {
                width: 80px;
                font-weight: bold;
            }
            .prob-bar {
                flex: 1;
                height: 25px;
                background: #e0e0e0;
                border-radius: 15px;
                overflow: hidden;
            }
            .prob-fill {
                height: 100%;
                border-radius: 15px;
                display: flex;
                align-items: center;
                padding-left: 10px;
                color: white;
                font-weight: bold;
                transition: width 0.5s ease;
            }
            .prob-fill.buy {
                background: linear-gradient(90deg, #00b894 0%, #00cec9 100%);
            }
            .prob-fill.sell {
                background: linear-gradient(90deg, #d63031 0%, #e17055 100%);
            }
            @media (max-width: 768px) {
                .grid {
                    grid-template-columns: 1fr;
                }
                .search-box {
                    flex-direction: column;
                }
                .search-box input, .search-box select, .search-box button {
                    width: 100%;
                }
                .indicator-grid {
                    grid-template-columns: 1fr;
                }
                .market-structure {
                    grid-template-columns: 1fr;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 ICTSMARTPRO Dashboard</h1>
                <p>Professional Crypto Analysis with ML + 30+ Patterns</p>
            </div>
            
            <div class="search-box">
                <input type="text" id="symbol" placeholder="Sembol (örn: BTCUSDT)" value="BTCUSDT">
                <select id="interval">
                    <option value="1m">1 Dakika</option>
                    <option value="5m">5 Dakika</option>
                    <option value="15m">15 Dakika</option>
                    <option value="30m">30 Dakika</option>
                    <option value="1h" selected>1 Saat</option>
                    <option value="4h">4 Saat</option>
                    <option value="1d">1 Gün</option>
                    <option value="1w">1 Hafta</option>
                </select>
                <button onclick="analyze()" id="analyzeBtn">🔍 Analiz Et</button>
            </div>
            
            <div class="status-bar" id="statusBar">
                <div class="status-item">
                    <div class="status-dot"></div>
                    <span id="statusText">Sistem Hazır</span>
                </div>
                <div class="status-item">
                    <span id="uptimeText">Uptime: Hesaplanıyor...</span>
                </div>
                <div class="status-item">
                    <span id="modelsText">Modeller: 0</span>
                </div>
            </div>
            
            <div id="loading" class="loading hidden">
                <div class="loading-spinner"></div>
                <div>Analiz ediliyor, lütfen bekleyin...</div>
            </div>
            
            <div id="error" class="error-message hidden"></div>
            
            <div id="results" class="hidden">
                <div class="grid">
                    <div class="card price-card">
                        <h3>💰 Fiyat Bilgisi</h3>
                        <div class="price-value" id="currentPrice">$0.00</div>
                        <div id="priceChange" class="price-change">0.00%</div>
                        <div style="margin-top: 15px; font-size: 0.9em; opacity: 0.9;">
                            <div>Açılış: <span id="openPrice">$0.00</span></div>
                            <div>Yüksek: <span id="highPrice">$0.00</span></div>
                            <div>Düşük: <span id="lowPrice">$0.00</span></div>
                            <div>Hacim: <span id="volumeValue">0</span></div>
                        </div>
                    </div>
                    
                    <div class="card">
                        <h3>🤖 ML Tahmini</h3>
                        <div class="ml-signal">
                            <div class="signal-badge" id="mlSignal">NEUTRAL</div>
                            <div class="confidence-meter">
                                <div class="confidence-fill" id="confidenceFill" style="width: 50%;">50%</div>
                            </div>
                            <div class="probability-bars">
                                <div class="prob-bar-container">
                                    <div class="prob-label">AL</div>
                                    <div class="prob-bar">
                                        <div class="prob-fill buy" id="buyProbBar" style="width: 50%;">50%</div>
                                    </div>
                                </div>
                                <div class="prob-bar-container">
                                    <div class="prob-label">SAT</div>
                                    <div class="prob-bar">
                                        <div class="prob-fill sell" id="sellProbBar" style="width: 50%;">50%</div>
                                    </div>
                                </div>
                            </div>
                            <div style="font-size: 0.9em; color: #7f8c8d;">
                                Model: <span id="modelVersion">-</span>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="card" style="margin-bottom: 20px;">
                    <h3>📈 Teknik İndikatörler</h3>
                    <div class="indicator-grid" id="indicatorGrid">
                        <!-- Dinamik doldurulacak -->
                    </div>
                </div>
                
                <div class="card" style="margin-bottom: 20px;">
                    <h3>🏛️ Piyasa Yapısı</h3>
                    <div class="market-structure" id="marketStructure">
                        <!-- Dinamik doldurulacak -->
                    </div>
                </div>
                
                <div class="tab-container">
                    <div class="tabs">
                        <button class="tab active" onclick="showTab('ict')">🎯 ICT Patternler (<span id="ictCount">0</span>)</button>
                        <button class="tab" onclick="showTab('classical')">📐 Klasik Patternler (<span id="classicalCount">0</span>)</button>
                        <button class="tab" onclick="showTab('candlestick')">🕯️ Mum Patternler (<span id="candlestickCount">0</span>)</button>
                        <button class="tab" onclick="showTab('model')">📊 Model Bilgisi</button>
                    </div>
                    
                    <div class="tab-content active" id="tab-ict">
                        <div class="card">
                            <h3>ICT Patternler</h3>
                            <div class="pattern-list" id="ictPatterns">
                                <div style="text-align: center; color: #7f8c8d; padding: 20px;">
                                    Pattern bulunamadı
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="tab-content" id="tab-classical">
                        <div class="card">
                            <h3>Klasik Patternler</h3>
                            <div class="pattern-list" id="classicalPatterns">
                                <div style="text-align: center; color: #7f8c8d; padding: 20px;">
                                    Pattern bulunamadı
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="tab-content" id="tab-candlestick">
                        <div class="card">
                            <h3>Mum Patternler</h3>
                            <div class="pattern-list" id="candlestickPatterns">
                                <div style="text-align: center; color: #7f8c8d; padding: 20px;">
                                    Pattern bulunamadı
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="tab-content" id="tab-model">
                        <div class="card">
                            <h3>Model Bilgisi</h3>
                            <div class="model-info" id="modelInfo">
                                <div style="text-align: center; color: #7f8c8d; padding: 20px;">
                                    Model bilgisi yok
                                </div>
                            </div>
                            <div style="margin-top: 20px;">
                                <h4 style="margin-bottom: 15px; color: #2c3e50;">Aktif Veri Kaynakları</h4>
                                <div class="sources-list" id="activeSources">
                                    <!-- Dinamik doldurulacak -->
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="card" style="margin-top: 20px;">
                    <h3>⚡ Performans</h3>
                    <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                        <div class="structure-item">
                            <div class="structure-label">İşlem Süresi</div>
                            <div class="structure-value" id="performanceMs" style="background: #d4edda; color: #155724;">0ms</div>
                        </div>
                        <div class="structure-item">
                            <div class="structure-label">Veri Noktası</div>
                            <div class="structure-value" id="dataPoints" style="background: #d1ecf1; color: #0c5460;">0</div>
                        </div>
                        <div class="structure-item">
                            <div class="structure-label">Toplam Pattern</div>
                            <div class="structure-value" id="totalPatterns" style="background: #fff3cd; color: #856404;">0</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            let currentData = null;
            
            async function checkStatus() {
                try {
                    const res = await fetch('/health');
                    const data = await res.json();
                    document.getElementById('statusText').textContent = 'Sistem Sağlıklı';
                    document.getElementById('uptimeText').textContent = 'Uptime: ' + data.uptime;
                    document.getElementById('modelsText').textContent = 'Modeller: ' + data.models_loaded;
                } catch (e) {
                    document.getElementById('statusText').textContent = 'Bağlantı Hatası';
                    document.getElementById('statusText').style.color = '#e74c3c';
                }
            }
            
            function showTab(tabName) {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                event.target.classList.add('active');
                document.getElementById('tab-' + tabName).classList.add('active');
            }
            
            function getDirectionClass(direction) {
                if (direction.includes('bullish')) return 'bullish';
                if (direction.includes('bearish')) return 'bearish';
                return 'neutral';
            }
            
            function formatPatternName(name) {
                return name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            }
            
            function createPatternCard(pattern) {
                const directionClass = getDirectionClass(pattern.direction);
                return `
                    <div class="pattern-item ${directionClass}">
                        <div class="pattern-name">${formatPatternName(pattern.name)}</div>
                        <div class="pattern-type">${pattern.type}</div>
                        <div class="pattern-confidence">Güven: ${pattern.confidence.toFixed(1)}%</div>
                        <div class="pattern-description">${pattern.description || ''}</div>
                        <div style="margin-top: 8px; font-size: 0.85em; color: #95a5a6;">
                            Fiyat: $${pattern.price.toFixed(2)} | ${new Date(pattern.timestamp).toLocaleString('tr-TR')}
                        </div>
                    </div>
                `;
            }
            
            function renderPatterns(patterns, containerId) {
                const container = document.getElementById(containerId);
                if (!patterns || patterns.length === 0) {
                    container.innerHTML = '<div style="text-align: center; color: #7f8c8d; padding: 20px;">Pattern bulunamadı</div>';
                    return;
                }
                container.innerHTML = patterns.map(p => createPatternCard(p)).join('');
            }
            
            function renderIndicators(technical) {
                const container = document.getElementById('indicatorGrid');
                const indicators = [
                    { key: 'rsi', label: 'RSI (14)', bullish: 70, bearish: 30 },
                    { key: 'macd', label: 'MACD', bullish: 0, bearish: 0 },
                    { key: 'bb_position', label: 'BB Pozisyon', bullish: 50, bearish: 50 },
                    { key: 'volume_ratio', label: 'Hacim Oranı', bullish: 1.5, bearish: 0 },
                    { key: 'atr', label: 'ATR', bullish: null, bearish: null },
                    { key: 'sma_20', label: 'SMA 20', bullish: null, bearish: null },
                    { key: 'ema_9', label: 'EMA 9', bullish: null, bearish: null },
                    { key: 'ema_21', label: 'EMA 21', bullish: null, bearish: null }
                ];
                
                let html = '';
                indicators.forEach(ind => {
                    if (technical[ind.key] !== undefined) {
                        const value = technical[ind.key].toFixed(ind.key.includes('ratio') || ind.key.includes('position') ? 2 : 4);
                        let valueClass = '';
                        if (ind.bullish !== null) {
                            if (technical[ind.key] > ind.bullish) valueClass = 'bullish';
                            else if (technical[ind.key] < ind.bearish) valueClass = 'bearish';
                        }
                        html += `
                            <div class="indicator-item">
                                <div class="indicator-label">${ind.label}</div>
                                <div class="indicator-value ${valueClass}">${value}</div>
                            </div>
                        `;
                    }
                });
                container.innerHTML = html;
            }
            
            function renderMarketStructure(structure) {
                const container = document.getElementById('marketStructure');
                const items = [
                    { key: 'trend', label: 'Trend' },
                    { key: 'trend_strength', label: 'Trend Gücü' },
                    { key: 'volatility', label: 'Volatilite' },
                    { key: 'momentum', label: 'Momentum' }
                ];
                
                let html = '';
                items.forEach(item => {
                    const value = structure[item.key] || 'N/A';
                    let valueClass = 'neutral';
                    if (value.includes('UP') || value.includes('BULL')) valueClass = 'uptrend';
                    else if (value.includes('DOWN') || value.includes('BEAR')) valueClass = 'downtrend';
                    
                    html += `
                        <div class="structure-item">
                            <div class="structure-label">${item.label}</div>
                            <div class="structure-value ${valueClass}">${value.replace(/_/g, ' ')}</div>
                        </div>
                    `;
                });
                container.innerHTML = html;
            }
            
            function renderModelInfo(info) {
                const container = document.getElementById('modelInfo');
                if (!info || info.best_model === 'none') {
                    container.innerHTML = '<div style="text-align: center; color: #7f8c8d; padding: 20px;">Model henüz eğitilmedi</div>';
                    return;
                }
                
                const bestModelResults = info.results[info.best_model] || {};
                container.innerHTML = `
                    <div class="model-info-row">
                        <span>En İyi Model</span>
                        <strong>${info.best_model}</strong>
                    </div>
                    <div class="model-info-row">
                        <span>Eğitim Tarihi</span>
                        <span>${new Date(info.trained_at).toLocaleString('tr-TR')}</span>
                    </div>
                    <div class="model-info-row">
                        <span>Eğitim Örnekleri</span>
                        <strong>${info.training_samples}</strong>
                    </div>
                    <div class="model-info-row">
                        <span>Doğruluk</span>
                        <strong>${bestModelResults.accuracy || 'N/A'}%</strong>
                    </div>
                    <div class="model-info-row">
                        <span>Precision</span>
                        <strong>${bestModelResults.precision || 'N/A'}%</strong>
                    </div>
                    <div class="model-info-row">
                        <span>Recall</span>
                        <strong>${bestModelResults.recall || 'N/A'}%</strong>
                    </div>
                `;
            }
            
            function renderActiveSources(sources) {
                const container = document.getElementById('activeSources');
                if (!sources || sources.length === 0) {
                    container.innerHTML = '<div style="color: #7f8c8d;">Kaynak bilgisi yok</div>';
                    return;
                }
                container.innerHTML = sources.map(s => 
                    `<div class="source-badge active">✅ ${s}</div>`
                ).join('');
            }
            
            async function analyze() {
                const symbol = document.getElementById('symbol').value.toUpperCase();
                const interval = document.getElementById('interval').value;
                const btn = document.getElementById('analyzeBtn');
                const loading = document.getElementById('loading');
                const results = document.getElementById('results');
                const error = document.getElementById('error');
                
                btn.disabled = true;
                loading.classList.remove('hidden');
                results.classList.add('hidden');
                error.classList.add('hidden');
                
                try {
                    const res = await fetch(`/api/analyze/${symbol}?interval=${interval}`);
                    if (!res.ok) {
                        const errData = await res.json();
                        throw new Error(errData.detail || 'Analiz başarısız');
                    }
                    const data = await res.json();
                    currentData = data;
                    
                    // Fiyat bilgisi
                    document.getElementById('currentPrice').textContent = '$' + data.price.current.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                    document.getElementById('openPrice').textContent = '$' + data.price.open.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                    document.getElementById('highPrice').textContent = '$' + data.price.high.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                    document.getElementById('lowPrice').textContent = '$' + data.price.low.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                    document.getElementById('volumeValue').textContent = data.price.volume.toLocaleString('en-US');
                    
                    const changeEl = document.getElementById('priceChange');
                    const change = data.price.change;
                    changeEl.textContent = (change >= 0 ? '+' : '') + change.toFixed(2) + '%';
                    changeEl.className = 'price-change ' + (change >= 0 ? 'positive' : 'negative');
                    
                    // ML Tahmini
                    const mlPred = data.ml_prediction;
                    const signalEl = document.getElementById('mlSignal');
                    signalEl.textContent = mlPred.signal.replace('_', ' ');
                    signalEl.className = 'signal-badge signal-' + mlPred.signal;
                    
                    document.getElementById('confidenceFill').style.width = mlPred.confidence + '%';
                    document.getElementById('confidenceFill').textContent = mlPred.confidence.toFixed(1) + '%';
                    
                    document.getElementById('buyProbBar').style.width = (mlPred.buy_probability * 100) + '%';
                    document.getElementById('buyProbBar').textContent = (mlPred.buy_probability * 100).toFixed(1) + '%';
                    document.getElementById('sellProbBar').style.width = (mlPred.sell_probability * 100) + '%';
                    document.getElementById('sellProbBar').textContent = (mlPred.sell_probability * 100).toFixed(1) + '%';
                    
                    document.getElementById('modelVersion').textContent = mlPred.model_version;
                    
                    // Teknik İndikatörler
                    renderIndicators(data.technical);
                    
                    // Piyasa Yapısı
                    renderMarketStructure(data.market_structure);
                    
                    // Patternler
                    document.getElementById('ictCount').textContent = data.ict_patterns.length;
                    document.getElementById('classicalCount').textContent = data.classical_patterns.length;
                    document.getElementById('candlestickCount').textContent = data.candlestick_patterns.length;
                    
                    renderPatterns(data.ict_patterns, 'ictPatterns');
                    renderPatterns(data.classical_patterns, 'classicalPatterns');
                    renderPatterns(data.candlestick_patterns, 'candlestickPatterns');
                    
                    // Model Bilgisi
                    renderModelInfo(data.model_info);
                    renderActiveSources(data.active_sources);
                    
                    // Performans
                    document.getElementById('performanceMs').textContent = data.performance_ms + 'ms';
                    document.getElementById('dataPoints').textContent = data.data_points;
                    document.getElementById('totalPatterns').textContent = 
                        data.ict_patterns.length + data.classical_patterns.length + data.candlestick_patterns.length;
                    
                    loading.classList.add('hidden');
                    results.classList.remove('hidden');
                    
                } catch (e) {
                    loading.classList.add('hidden');
                    error.classList.remove('hidden');
                    error.textContent = 'Hata: ' + e.message;
                } finally {
                    btn.disabled = false;
                }
            }
            
            // Enter tuşu ile analiz
            document.getElementById('symbol').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') analyze();
            });
            
            // Sayfa yüklendiğinde status kontrolü
            checkStatus();
            setInterval(checkStatus, 30000);
        </script>
    </body>
    </html>
    """)

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
    request: Request,
    symbol: str,
    interval: str = Query("1h", regex="^(1m|5m|15m|30m|1h|4h|1d|1w)$"),
    limit: int = Query(500, ge=100, le=1000),
    background_tasks: BackgroundTasks = None,
    api_key: str = Depends(check_rate_limit)
):
    """Full analysis with ML + all patterns"""
    symbol = symbol.upper()
    if not symbol.endswith("USDT") and symbol not in ["BTC", "ETH", "BNB"]:
        symbol = f"{symbol}USDT"
    logger.info(f"Analysis: {symbol} @ {interval}")
    start_time_local = time.time()
    try:
        async with data_fetcher as fetcher:
            candles = await fetcher.get_candles(symbol, interval, limit)
        if not candles or len(candles) < Config.MIN_CANDLES:
            raise HTTPException(422, f"Insufficient data: {len(candles) if candles else 0}")
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp').sort_index()
        indicators = TechnicalIndicatorCalculator.calculate_all(df)
        technical = {k: float(v.iloc[-1]) if not np.isnan(v.iloc[-1]) else 0.0 for k, v in indicators.items()}
        market_structure = MarketStructureAnalyzer.analyze(df)
        ict_patterns = ICTPatternDetector.analyze(df)
        classical_patterns = ClassicalPatternDetector.analyze(df)
        candlestick_patterns = CandlestickPatternDetector.analyze(df)
        ml_pred = await ml_trainer.predict(symbol, interval, df)
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
        model_info = ml_trainer.get_model_info(symbol, interval) or {
            'best_model': 'none',
            'trained_at': 'never',
            'results': {},
            'training_samples': 0,
            'feature_names': []
        }
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
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Analysis failed: {e}")
        raise HTTPException(500, f"Analysis failed: {str(e)[:200]}")

@app.post("/api/train/{symbol}")
async def train_model(
    request: Request,
    symbol: str,
    interval: str = Query("1h", regex="^(1m|5m|15m|30m|1h|4h|1d|1w)$"),
    force: bool = False,
    background_tasks: BackgroundTasks = None,
    api_key: str = Depends(check_rate_limit)
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Training failed: {e}")
        raise HTTPException(500, f"Training failed: {str(e)[:200]}")

@app.get("/api/models")
async def list_models():
    """List all trained models"""
    models = []
    for model_file in Path(Config.ML_MODEL_DIR).glob("*.joblib"):
        try:
            if not model_file.stem.endswith('_scaler'):
                model_data = joblib.load(model_file)
                models.append({
                    'symbol': model_data.get('symbol'),
                    'interval': model_data.get('interval'),
                    'trained_at': model_data.get('trained_at'),
                    'best_model': model_data.get('best_model'),
                    'accuracy': model_data.get('results', {}).get(model_data.get('best_model'), {}).get('accuracy', 0)
                })
        except Exception as e:
            logger.debug(f"Error loading model {model_file}: {e}")
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
# STARTUP & SHUTDOWN
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
    logger.info(f"Rate Limit: {Config.RATE_LIMIT_REQUESTS} requests / {Config.RATE_LIMIT_WINDOW}s")
    logger.info("=" * 70)
    await data_fetcher.ensure_session()

@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down...")
    await data_fetcher.close_session()
    ml_trainer.executor.shutdown(wait=True)
    logger.info("Shutdown complete")

# ========================================================================================================
# MAIN
# ========================================================================================================
if __name__ == "__main__":
    import uvicorn
    current_file = Path(__file__).stem
    uvicorn.run(
        f"{current_file}:app",
        host=Config.HOST,
        port=Config.PORT,
        reload=Config.DEBUG,
        log_level="info"
    )
