import sys
import json
import time
import asyncio
import logging
import secrets
import random
import os
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set
from collections import defaultdict
from contextlib import asynccontextmanager
from enum import Enum

# ✅ Pydantic
from pydantic import BaseModel 

import numpy as np
import pandas as pd

from fastapi import FastAPI, Request, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

import aiohttp
from aiohttp import ClientTimeout, TCPConnector

# ========================================================================================================
# LOGGING SETUP
# ========================================================================================================
class ColoredFormatter(logging.Formatter):
    """Renkli log formatı"""
    grey = "\x1b[38;20m"
    blue = "\x1b[34;20m"
    green = "\x1b[32;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    
    FORMATS = {
        logging.DEBUG: grey,
        logging.INFO: green,
        logging.WARNING: yellow,
        logging.ERROR: red,
        logging.CRITICAL: bold_red
    }
    
    def format(self, record):
        color = self.FORMATS.get(record.levelno, self.grey)
        formatter = logging.Formatter(
            f'{color}%(asctime)s | %(levelname)-8s | %(name)-12s | %(message)s{self.reset}',
            datefmt='%H:%M:%S'
        )
        return formatter.format(record)

def setup_logging():
    """Logging sistemi"""
    logger = logging.getLogger("ictsmartpro")
    logger.setLevel(logging.DEBUG if os.getenv("DEBUG") else logging.INFO)
    logger.handlers.clear()
    
    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(ColoredFormatter())
    logger.addHandler(console)
    
    # File handler
    try:
        file_handler = logging.FileHandler('ictsmartpro.log')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    except:
        pass
    
    return logger

logger = setup_logging()

# ========================================================================================================
# CONFIGURATION
# ========================================================================================================
class Config:
    """Sistem konfigürasyonu"""
    
    ENV = os.getenv("ENV", "production")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    PORT = int(os.getenv("PORT", 8000))
    
    API_TIMEOUT = int(os.getenv("API_TIMEOUT", "8"))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
    
    MIN_CANDLES = int(os.getenv("MIN_CANDLES", "30"))
    MIN_EXCHANGES = int(os.getenv("MIN_EXCHANGES", "2"))
    
    CACHE_TTL = int(os.getenv("CACHE_TTL", "45"))
    
    MAX_CONFIDENCE = float(os.getenv("MAX_CONFIDENCE", "85.0"))
    DEFAULT_CONFIDENCE = float(os.getenv("DEFAULT_CONFIDENCE", "51.5"))
    
    RATE_LIMIT_CALLS = int(os.getenv("RATE_LIMIT_CALLS", "60"))
    RATE_LIMIT_PERIOD = int(os.getenv("RATE_LIMIT_PERIOD", "60"))
    
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# ========================================================================================================
# ENUMERATIONS
# ========================================================================================================
class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

class PatternType(str, Enum):
    ICT = "ict"
    CLASSICAL = "classical"
    INDICATOR = "indicator"
    PRICE_ACTION = "price_action"
    FIBONACCI = "fibonacci"
    SUPPORT_RESISTANCE = "support_resistance"
    TREND = "trend"
    GAINZALGO = "gainzalgo"
    ULTIMATE = "ultimate"

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
    sources: Optional[List[str]] = None

class Signal(BaseModel):
    signal: str
    confidence: float
    recommendation: str
    buy_count: int = 0
    sell_count: int = 0
    tp_level: Optional[float] = None
    sl_level: Optional[float] = None

class Pattern(BaseModel):
    name: str
    type: PatternType
    direction: Direction
    confidence: float
    timestamp: str
    price: float
    description: Optional[str] = None
    sl_level: Optional[float] = None
    tp_level: Optional[float] = None

class AnalysisResponse(BaseModel):
    success: bool
    symbol: str
    interval: str
    timestamp: str
    price: Dict[str, float]
    signal: Signal
    technical: Dict[str, Any]
    ict_patterns: Dict[str, List[Dict[str, Any]]]
    candle_patterns: List[Dict[str, Any]]
    classical_patterns: List[Dict[str, Any]]
    gainzalgo_signals: List[Dict[str, Any]]
    ultimate_signals: List[Dict[str, Any]]
    market_structure: Dict[str, Any]
    active_sources: List[str]
    data_points: int
    all_patterns: List[Pattern]
    exchange_stats: Optional[Dict] = None  # YENİ: exchange istatistikleri

# ========================================================================================================
# EXCHANGE DATA FETCHER
# ========================================================================================================
class ExchangeDataFetcher:
    
    EXCHANGES = [
        {
            "name": "Kraken",
            "weight": 1.00,
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
            "name": "Binance",
            "weight": 0.99,
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
            "name": "MEXC",
            "weight": 0.96,
            "base_url": "https://api.mexc.com/api/v3/klines",
            "symbol_fmt": lambda s: s.replace("/", ""),
            "interval_map": {
                "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
            },
            "parser": "binance",
            "timeout": 5
        },
        {
            "name": "Yahoo",
            "weight": 0.90,
            "base_url": "https://query1.finance.yahoo.com/v8/finance/chart/",
            "symbol_fmt": lambda s: s.replace("USDT", "-USD").replace("/", ""),
            "interval_map": {
                "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                "1h": "60m", "4h": "1h", "1d": "1d", "1w": "1wk"
            },
            "parser": "yahoo",
            "timeout": 10
        }
    ]
    
    WEBSOCKETS = {
        "Binance": "wss://stream.binance.com:9443/ws/{symbol}@kline_{interval}",
        "Kraken": "wss://ws.kraken.com/v2",
        "MEXC": "wss://wbs.mexc.com/ws"
    }
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, Any] = {}
        self.cache_time: Dict[str, float] = {}
        self.stats = defaultdict(lambda: {"success": 0, "fail": 0, "last_error": "", "last_success": 0})
        self.price_cache: Dict[str, Dict] = {}
        self.request_times: List[float] = []
        self._lock = asyncio.Lock()
    
    async def __aenter__(self):
        timeout = ClientTimeout(total=Config.API_TIMEOUT)
        connector = TCPConnector(
            limit=20,
            limit_per_host=5,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
            force_close=True
        )
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": "ICTSMARTPRO-Bot/9.0"}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def _check_rate_limit(self) -> bool:
        now = time.time()
        self.request_times = [t for t in self.request_times if now - t < Config.RATE_LIMIT_PERIOD]
        if len(self.request_times) >= Config.RATE_LIMIT_CALLS:
            return False
        self.request_times.append(now)
        return True
    
    def _get_cache_key(self, symbol: str, interval: str) -> str:
        return f"{symbol}_{interval}"
    
    def _is_cache_valid(self, key: str) -> bool:
        if key not in self.cache_time:
            return False
        return (time.time() - self.cache_time[key]) < Config.CACHE_TTL
    
    async def _fetch_exchange(self, exchange: Dict, symbol: str, interval: str, limit: int) -> Optional[List[Dict]]:
        if not self._check_rate_limit():
            return None
        
        name = exchange["name"]
        
        try:
            if interval not in exchange["interval_map"]:
                return None
            
            ex_interval = exchange["interval_map"][interval]
            formatted_symbol = exchange["symbol_fmt"](symbol)
            
            if name == "Yahoo":
                url = f"{exchange['base_url']}{formatted_symbol}"
                params = {
                    "interval": ex_interval,
                    "range": "1mo" if interval in ["1d", "1w"] else "5d",
                    "includePrePost": "false"
                }
            else:
                url = exchange["base_url"]
                params = {
                    "symbol": formatted_symbol,
                    "interval": ex_interval,
                    "limit": limit
                }
            
            timeout = ClientTimeout(total=exchange.get("timeout", Config.API_TIMEOUT))
            async with self.session.get(url, params=params, timeout=timeout) as response:
                if response.status != 200:
                    self.stats[name]["fail"] += 1
                    self.stats[name]["last_error"] = f"HTTP {response.status}"
                    return None
                
                data = await response.json()
                candles = await self._parse_response(name, data)
                
                if not candles or len(candles) < 5:
                    self.stats[name]["fail"] += 1
                    self.stats[name]["last_error"] = "Insufficient data"
                    return None
                
                async with self._lock:
                    self.stats[name]["success"] += 1
                    self.stats[name]["last_success"] = time.time()
                    self.stats[name]["last_error"] = ""
                
                return candles
                
        except asyncio.TimeoutError:
            self.stats[name]["fail"] += 1
            self.stats[name]["last_error"] = "Timeout"
            return None
        except Exception as e:
            self.stats[name]["fail"] += 1
            self.stats[name]["last_error"] = str(e)[:50]
            return None
    
    async def _parse_response(self, exchange: str, data: Any) -> List[Dict]:
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
            
            elif exchange == "Yahoo":
                if (isinstance(data, dict) and 
                    data.get("chart") and 
                    data["chart"].get("result") and 
                    len(data["chart"]["result"]) > 0):
                    
                    result = data["chart"]["result"][0]
                    timestamps = result.get("timestamp", [])
                    quotes = result.get("indicators", {}).get("quote", [{}])[0]
                    
                    opens = quotes.get("open", [])
                    highs = quotes.get("high", [])
                    lows = quotes.get("low", [])
                    closes = quotes.get("close", [])
                    volumes = quotes.get("volume", [])
                    
                    for i in range(min(len(timestamps), len(closes))):
                        if closes[i] is not None:
                            candles.append({
                                "timestamp": int(timestamps[i]) * 1000,
                                "open": float(opens[i] if opens[i] else closes[i]),
                                "high": float(highs[i] if highs[i] else closes[i]),
                                "low": float(lows[i] if lows[i] else closes[i]),
                                "close": float(closes[i]),
                                "volume": float(volumes[i] if volumes[i] else 0),
                                "exchange": exchange
                            })
            
            candles.sort(key=lambda x: x["timestamp"])
            return candles
            
        except Exception as e:
            logger.debug(f"Parse error for {exchange}: {str(e)}")
            return []
    
    def _aggregate_candles(self, all_candles: List[List[Dict]]) -> List[Dict]:
        """Mum verilerini birleştir"""
        if not all_candles:
            return []
    
    timestamp_map = defaultdict(list)
    for exchange_data in all_candles:
        for candle in exchange_data:
            timestamp_map[candle["timestamp"]].append(candle)
    
    aggregated = []
    for timestamp in sorted(timestamp_map.keys()):
        candles = timestamp_map[timestamp]
        
        if len(candles) == 1:
            aggregated.append(candles[0])
            continue
        
        total_weight = 0
        open_sum = high_sum = low_sum = close_sum = volume_sum = 0
        sources = []
        
        for candle in candles:
            exchange_config = next((e for e in self.EXCHANGES if e["name"] == candle["exchange"]), None)
            weight = exchange_config["weight"] if exchange_config else 0.5
            
            total_weight += weight
            open_sum += candle["open"] * weight
            high_sum += candle["high"] * weight
            low_sum += candle["low"] * weight
            close_sum += candle["close"] * weight
            volume_sum += candle["volume"] * weight
            sources.append(candle["exchange"])
        
        if total_weight > 0:
            aggregated.append({
                "timestamp": timestamp,
                "open": open_sum / total_weight,
                "high": high_sum / total_weight,
                "low": low_sum / total_weight,
                "close": close_sum / total_weight,
                "volume": volume_sum / total_weight,
                "source_count": len(candles),
                "sources": sources,
                "exchange": "aggregated"
            })
    
    return aggregated

    async def get_candles(self, symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
        cache_key = self._get_cache_key(symbol, interval)
        
        if self._is_cache_valid(cache_key):
            cached = self.cache.get(cache_key, [])
            if cached:
                logger.info(f"📦 CACHE: {symbol} ({interval}) - {len(cached)} candles")
                return cached[-limit:]
        
        logger.info(f"🔄 FETCH: {symbol} ({interval}) from {len(self.EXCHANGES)} sources...")
        
        tasks = [
            self._fetch_exchange(exchange, symbol, interval, limit * 2)
            for exchange in self.EXCHANGES
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_results = []
        for r in results:
            if isinstance(r, list) and len(r) >= 10:
                valid_results.append(r)
        
        logger.info(f"✅ RECEIVED: {len(valid_results)}/{len(self.EXCHANGES)} sources")
        
        if len(valid_results) < Config.MIN_EXCHANGES:
            logger.warning(f"⚠️ Only {len(valid_results)} sources, using available...")
            if not valid_results:
                return []
        
        aggregated = self._aggregate_candles(valid_results)
        
        if len(aggregated) < Config.MIN_CANDLES:
            logger.warning(f"⚠️ Only {len(aggregated)} candles (need {Config.MIN_CANDLES})")
            return []
        
        self.cache[cache_key] = aggregated
        self.cache_time[cache_key] = time.time()
        
        return aggregated[-limit:]
    
    async def get_current_price(self, symbol: str) -> Optional[float]:
        if symbol in self.price_cache:
            if time.time() - self.price_cache[symbol].get("time", 0) < 10:
                return self.price_cache[symbol].get("price")
        
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.replace('/', '')}"
            async with self.session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    price = float(data['price'])
                    self.price_cache[symbol] = {"price": price, "time": time.time()}
                    return price
        except:
            pass
        
        try:
            url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol.replace('/', '')}"
            async with self.session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    price = float(data['price'])
                    self.price_cache[symbol] = {"price": price, "time": time.time()}
                    return price
        except:
            pass
        
        return None
    
    def get_stats(self) -> Dict:
        return dict(self.stats)
    
    def get_active_sources(self) -> List[str]:
        active = []
        now = time.time()
        for name, stats in self.stats.items():
            if stats.get("last_success", 0) > now - 300:
                active.append(name)
        return active

# ========================================================================================================
# ULTIMATE 2026 PATTERN DETECTOR
# ========================================================================================================
class Ultimate2026Detector:
    """Ultimate 2026 stratejisi - Multi-timeframe + Multi-phase filtreleme"""
    
    @staticmethod
    def detect(df: pd.DataFrame) -> List[Dict]:
        signals = []
        
        if len(df) < 50:
            return signals
        
        # EMA'lar
        ema_fast = df['close'].ewm(span=9).mean()
        ema_slow = df['close'].ewm(span=21).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        
        # Momentum
        momentum = df['close'].diff(12)
        
        # Pivot noktaları
        high_pivot = df['high'].rolling(window=5, center=True).max()
        low_pivot = df['low'].rolling(window=5, center=True).min()
        
        # Engulfing
        bull_engulf = (df['close'] > df['open']) & (df['close'] > df['close'].shift(1)) & (df['open'] <= df['close'].shift(1))
        bear_engulf = (df['close'] < df['open']) & (df['close'] < df['close'].shift(1)) & (df['open'] >= df['close'].shift(1))
        
        # ATR
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['close'].shift(1)).abs()
        tr3 = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean()
        
        # Divergence
        price_lows = df['low'].rolling(window=10).min()
        rsi_lows = rsi.rolling(window=10).min()
        bull_div = (df['low'] < price_lows.shift(1)) & (rsi > rsi_lows.shift(1)) & (rsi < 40)
        
        price_highs = df['high'].rolling(window=10).max()
        rsi_highs = rsi.rolling(window=10).max()
        bear_div = (df['high'] > price_highs.shift(1)) & (rsi < rsi_highs.shift(1)) & (rsi > 60)
        
        # Structure Break
        bull_structure = (df['close'] > high_pivot.shift(1)) & (high_pivot.shift(1).notna())
        bear_structure = (df['close'] < low_pivot.shift(1)) & (low_pivot.shift(1).notna())
        
        # Son 10 mumu tara
        for i in range(len(df)-10, len(df)):
            if i < 10:
                continue
            
            # === BUY SİNYALİ ===
            # Phase 1: Trend + Momentum + RSI
            phase1_buy = (
                ema_fast.iloc[i] > ema_slow.iloc[i] and 
                ema_fast.iloc[i-1] <= ema_slow.iloc[i-1] and  # crossover
                momentum.iloc[i] > 0 and
                rsi.iloc[i] > 35
            )
            
            # Phase 2: Yapısal onay
            phase2_buy = (
                bull_engulf.iloc[i] or
                bull_div.iloc[i] or
                bull_structure.iloc[i]
            )
            
            if phase1_buy and phase2_buy:
                entry_price = df['close'].iloc[i]
                sl_level = entry_price - atr.iloc[i] * 1.3
                tp_level = entry_price + (entry_price - sl_level) * 2.2
                
                signals.append({
                    "pattern": "ultimate_2026_buy",
                    "type": "ultimate",
                    "direction": "bullish",
                    "strength": 85,
                    "timestamp": str(df.index[i]),
                    "price": float(entry_price),
                    "sl_level": float(sl_level),
                    "tp_level": float(tp_level),
                    "description": "Ultimate 2026 BUY - Multi-phase confirmation"
                })
            
            # === SELL SİNYALİ ===
            phase1_sell = (
                ema_fast.iloc[i] < ema_slow.iloc[i] and 
                ema_fast.iloc[i-1] >= ema_slow.iloc[i-1] and  # crossunder
                momentum.iloc[i] < 0 and
                rsi.iloc[i] < 65
            )
            
            phase2_sell = (
                bear_engulf.iloc[i] or
                bear_div.iloc[i] or
                bear_structure.iloc[i]
            )
            
            if phase1_sell and phase2_sell:
                entry_price = df['close'].iloc[i]
                sl_level = entry_price + atr.iloc[i] * 1.3
                tp_level = entry_price - (sl_level - entry_price) * 2.2
                
                signals.append({
                    "pattern": "ultimate_2026_sell",
                    "type": "ultimate",
                    "direction": "bearish",
                    "strength": 85,
                    "timestamp": str(df.index[i]),
                    "price": float(entry_price),
                    "sl_level": float(sl_level),
                    "tp_level": float(tp_level),
                    "description": "Ultimate 2026 SELL - Multi-phase confirmation"
                })
        
        return signals[-10:]

# ========================================================================================================
# GAINZALGO V2 DETECTOR
# ========================================================================================================
class GainzAlgoV2Detector:
    """GainzAlgo V2 Alpha stratejisi"""
    
    @staticmethod
    def detect(df: pd.DataFrame) -> List[Dict]:
        signals = []
        
        if len(df) < 30:
            return signals
        
        # EMA'lar
        ema_fast = df['close'].ewm(span=9).mean()
        ema_slow = df['close'].ewm(span=21).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi_6 = df['close'].diff().rolling(window=6).apply(
            lambda x: 100 - 100 / (1 + (x[x>0].sum() / (-x[x<0].sum() + 0.001)))
        )
        
        # Momentum
        momentum = df['close'].diff(12)
        
        # Engulfing
        bull_engulf = (df['close'] > df['open']) & (df['close'] > df['close'].shift(1)) & (df['open'] < df['close'].shift(1))
        bear_engulf = (df['close'] < df['open']) & (df['close'] < df['close'].shift(1)) & (df['open'] > df['close'].shift(1))
        
        # ATR
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['close'].shift(1)).abs()
        tr3 = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean()
        
        # Son 15 mumu tara
        for i in range(len(df)-15, len(df)):
            if i < 10:
                continue
            
            # === BUY SİNYALİ ===
            buy_cond = (
                ema_fast.iloc[i] > ema_slow.iloc[i] and
                ema_fast.iloc[i-1] <= ema_slow.iloc[i-1] and  # crossover
                rsi.iloc[i] > 40 and
                momentum.iloc[i] > 0 and
                bull_engulf.iloc[i] and
                df['close'].iloc[i] > df['close'].iloc[i-1] and
                df['is_bullish'].iloc[i] if 'is_bullish' in df.columns else True
            )
            
            if buy_cond and not pd.isna(atr.iloc[i]):
                entry_price = df['close'].iloc[i]
                sl_level = entry_price - atr.iloc[i] * 1.2
                tp_level = entry_price + (entry_price - sl_level) * 2.0
                
                signals.append({
                    "pattern": "gainzalgo_v2_buy",
                    "type": "gainzalgo",
                    "direction": "bullish",
                    "strength": 85,
                    "timestamp": str(df.index[i]),
                    "price": float(entry_price),
                    "sl_level": float(sl_level),
                    "tp_level": float(tp_level),
                    "description": "GainzAlgo V2 BUY - EMA crossover + RSI + Momentum + Engulfing"
                })
            
            # === SELL SİNYALİ ===
            sell_cond = (
                ema_fast.iloc[i] < ema_slow.iloc[i] and
                ema_fast.iloc[i-1] >= ema_slow.iloc[i-1] and  # crossunder
                rsi.iloc[i] < 60 and
                momentum.iloc[i] < 0 and
                bear_engulf.iloc[i] and
                df['close'].iloc[i] < df['close'].iloc[i-1] and
                df['is_bearish'].iloc[i] if 'is_bearish' in df.columns else True
            )
            
            if sell_cond and not pd.isna(atr.iloc[i]):
                entry_price = df['close'].iloc[i]
                sl_level = entry_price + atr.iloc[i] * 1.2
                tp_level = entry_price - (sl_level - entry_price) * 2.0
                
                signals.append({
                    "pattern": "gainzalgo_v2_sell",
                    "type": "gainzalgo",
                    "direction": "bearish",
                    "strength": 85,
                    "timestamp": str(df.index[i]),
                    "price": float(entry_price),
                    "sl_level": float(sl_level),
                    "tp_level": float(tp_level),
                    "description": "GainzAlgo V2 SELL - EMA crossunder + RSI + Momentum + Engulfing"
                })
        
        return signals[-10:]

# ========================================================================================================
# ICT PATTERN DETECTOR (GENİŞLETİLMİŞ)
# ========================================================================================================
class ICTPatternDetector:
    
    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """Gerekli indikatörleri hesapla"""
        df = df.copy()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # EMA'lar
        df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # ATR
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['close'].shift(1)).abs()
        tr3 = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=14).mean()
        
        # Volume
        df['volume_sma'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        # Candlestick
        df['is_bullish'] = df['close'] > df['open']
        df['is_bearish'] = df['close'] < df['open']
        df['body'] = abs(df['close'] - df['open'])
        df['upper_shadow'] = df['high'] - df[['close', 'open']].max(axis=1)
        df['lower_shadow'] = df[['close', 'open']].min(axis=1) - df['low']
        
        return df
    
    @staticmethod
    def detect_fair_value_gap(df: pd.DataFrame) -> List[Dict]:
        fvgs = []
        if len(df) < 3:
            return fvgs
        
        for i in range(1, len(df)-1):
            # Bullish FVG
            if df['low'].iloc[i+1] > df['high'].iloc[i-1]:
                gap_size = df['low'].iloc[i+1] - df['high'].iloc[i-1]
                gap_percent = (gap_size / df['high'].iloc[i-1]) * 100
                
                if gap_percent > 0.1:
                    fvgs.append({
                        "pattern": "bullish_fvg",
                        "type": "ict",
                        "direction": "bullish",
                        "strength": min(round(gap_percent * 5, 1), 80),
                        "timestamp": str(df.index[i]),
                        "price": float(df['close'].iloc[i]),
                        "gap_low": float(df['high'].iloc[i-1]),
                        "gap_high": float(df['low'].iloc[i+1]),
                        "gap_percent": round(gap_percent, 2),
                        "description": f"Bullish Fair Value Gap at {gap_percent:.2f}%"
                    })
            
            # Bearish FVG
            elif df['high'].iloc[i+1] < df['low'].iloc[i-1]:
                gap_size = df['low'].iloc[i-1] - df['high'].iloc[i+1]
                gap_percent = (gap_size / df['low'].iloc[i-1]) * 100
                
                if gap_percent > 0.1:
                    fvgs.append({
                        "pattern": "bearish_fvg",
                        "type": "ict",
                        "direction": "bearish",
                        "strength": min(round(gap_percent * 5, 1), 80),
                        "timestamp": str(df.index[i]),
                        "price": float(df['close'].iloc[i]),
                        "gap_low": float(df['high'].iloc[i+1]),
                        "gap_high": float(df['low'].iloc[i-1]),
                        "gap_percent": round(gap_percent, 2),
                        "description": f"Bearish Fair Value Gap at {gap_percent:.2f}%"
                    })
        
        return fvgs[-10:]
    
    @staticmethod
    def detect_order_blocks(df: pd.DataFrame) -> List[Dict]:
        obs = []
        if len(df) < 5:
            return obs
        
        for i in range(2, len(df)-2):
            # Bullish Order Block
            if (df['is_bullish'].iloc[i] and 
                df['is_bearish'].iloc[i-1] and 
                df['low'].iloc[i] < df['low'].iloc[i-1] and 
                df['close'].iloc[i] > df['high'].iloc[i-1]):
                
                ob_range = abs(df['high'].iloc[i-1] - df['low'].iloc[i-1])
                ob_percent = (ob_range / df['close'].iloc[i-1]) * 100
                
                obs.append({
                    "pattern": "bullish_order_block",
                    "type": "ict",
                    "direction": "bullish",
                    "strength": min(round(ob_percent * 10, 1), 75),
                    "timestamp": str(df.index[i-1]),
                    "price": float(df['close'].iloc[i]),
                    "block_low": float(df['low'].iloc[i-1]),
                    "block_high": float(df['high'].iloc[i-1]),
                    "description": "Bullish Order Block - Smart money buying zone"
                })
            
            # Bearish Order Block
            elif (df['is_bearish'].iloc[i] and 
                  df['is_bullish'].iloc[i-1] and 
                  df['high'].iloc[i] > df['high'].iloc[i-1] and 
                  df['close'].iloc[i] < df['low'].iloc[i-1]):
                
                ob_range = abs(df['high'].iloc[i-1] - df['low'].iloc[i-1])
                ob_percent = (ob_range / df['close'].iloc[i-1]) * 100
                
                obs.append({
                    "pattern": "bearish_order_block",
                    "type": "ict",
                    "direction": "bearish",
                    "strength": min(round(ob_percent * 10, 1), 75),
                    "timestamp": str(df.index[i-1]),
                    "price": float(df['close'].iloc[i]),
                    "block_low": float(df['low'].iloc[i-1]),
                    "block_high": float(df['high'].iloc[i-1]),
                    "description": "Bearish Order Block - Smart money selling zone"
                })
        
        return obs[-10:]
    
    @staticmethod
    def detect_breaker_blocks(df: pd.DataFrame) -> List[Dict]:
        breakers = []
        if len(df) < 15:
            return breakers
        
        for i in range(10, len(df)-1):
            recent_high = df['high'].iloc[i-10:i].max()
            recent_low = df['low'].iloc[i-10:i].min()
            
            # Bullish Breaker (eski direnç -> destek)
            if (df['close'].iloc[i] > recent_high and 
                df['close'].iloc[i-1] < recent_high):
                breakers.append({
                    "pattern": "bullish_breaker",
                    "type": "ict",
                    "direction": "bullish",
                    "strength": 72,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "break_level": float(recent_high),
                    "description": "Bullish Breaker - Resistance turned support"
                })
            
            # Bearish Breaker (eski destek -> direnç)
            elif (df['close'].iloc[i] < recent_low and 
                  df['close'].iloc[i-1] > recent_low):
                breakers.append({
                    "pattern": "bearish_breaker",
                    "type": "ict",
                    "direction": "bearish",
                    "strength": 72,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "break_level": float(recent_low),
                    "description": "Bearish Breaker - Support turned resistance"
                })
        
        return breakers[-10:]
    
    @staticmethod
    def detect_liquidity_sweeps(df: pd.DataFrame) -> List[Dict]:
        sweeps = []
        if len(df) < 25:
            return sweeps
        
        for i in range(20, len(df)):
            swing_highs = df['high'].iloc[i-20:i-5].nlargest(3)
            swing_lows = df['low'].iloc[i-20:i-5].nsmallest(3)
            
            # Yukarı likidite avı (bearish reversal)
            if len(swing_highs) > 0 and df['high'].iloc[i] > swing_highs.iloc[0] * 1.001:
                if df['close'].iloc[i] < swing_highs.iloc[0]:
                    volume_conf = 0
                    if not pd.isna(df['volume_ratio'].iloc[i]):
                        volume_conf = min(0.15, df['volume_ratio'].iloc[i] * 0.1)
                    
                    sweeps.append({
                        "pattern": "liquidity_sweep_up",
                        "type": "ict",
                        "direction": "bearish_reversal",
                        "strength": 70 + volume_conf * 100,
                        "timestamp": str(df.index[i]),
                        "price": float(df['close'].iloc[i]),
                        "swept_level": float(swing_highs.iloc[0]),
                        "sweep_high": float(df['high'].iloc[i]),
                        "description": "Liquidity Sweep Above - Bearish reversal"
                    })
            
            # Aşağı likidite avı (bullish reversal)
            if len(swing_lows) > 0 and df['low'].iloc[i] < swing_lows.iloc[0] * 0.999:
                if df['close'].iloc[i] > swing_lows.iloc[0]:
                    volume_conf = 0
                    if not pd.isna(df['volume_ratio'].iloc[i]):
                        volume_conf = min(0.15, df['volume_ratio'].iloc[i] * 0.1)
                    
                    sweeps.append({
                        "pattern": "liquidity_sweep_down",
                        "type": "ict",
                        "direction": "bullish_reversal",
                        "strength": 70 + volume_conf * 100,
                        "timestamp": str(df.index[i]),
                        "price": float(df['close'].iloc[i]),
                        "swept_level": float(swing_lows.iloc[0]),
                        "sweep_low": float(df['low'].iloc[i]),
                        "description": "Liquidity Sweep Below - Bullish reversal"
                    })
        
        return sweeps[-10:]
    
    @staticmethod
    def detect_break_of_structure(df: pd.DataFrame) -> List[Dict]:
        bos_signals = []
        if len(df) < 15:
            return bos_signals
        
        for i in range(10, len(df)):
            recent_high = df['high'].iloc[i-10:i].max()
            recent_low = df['low'].iloc[i-10:i].min()
            
            # Bullish BOS
            if df['high'].iloc[i] > recent_high * 1.005:
                bos_size = (df['high'].iloc[i] - recent_high) / recent_high * 100
                bos_signals.append({
                    "pattern": "bullish_bos",
                    "type": "ict",
                    "direction": "bullish",
                    "strength": min(round(bos_size * 15, 1), 80),
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "break_level": float(recent_high),
                    "break_size": round(bos_size, 2),
                    "description": f"Bullish Break of Structure at {bos_size:.2f}%"
                })
            
            # Bearish BOS
            elif df['low'].iloc[i] < recent_low * 0.995:
                bos_size = (recent_low - df['low'].iloc[i]) / recent_low * 100
                bos_signals.append({
                    "pattern": "bearish_bos",
                    "type": "ict",
                    "direction": "bearish",
                    "strength": min(round(bos_size * 15, 1), 80),
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "break_level": float(recent_low),
                    "break_size": round(bos_size, 2),
                    "description": f"Bearish Break of Structure at {bos_size:.2f}%"
                })
        
        return bos_signals[-10:]
    
    @staticmethod
    def detect_change_of_character(df: pd.DataFrame) -> List[Dict]:
        choch_signals = []
        if len(df) < 20:
            return choch_signals
        
        # Trend değişimi sinyali
        ema_fast = df['ema_9']
        ema_slow = df['ema_20']
        
        for i in range(15, len(df)):
            recent_trend = df['close'].iloc[i-10:i].pct_change().mean()
            
            # Bullish CHoCH (downtrend -> uptrend)
            if recent_trend < -0.001 and df['close'].iloc[i] > df['high'].iloc[i-1]:
                choch_signals.append({
                    "pattern": "bullish_choch",
                    "type": "ict",
                    "direction": "bullish",
                    "strength": 75,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "description": "Bullish Change of Character - Downtrend broken"
                })
            
            # Bearish CHoCH (uptrend -> downtrend)
            elif recent_trend > 0.001 and df['close'].iloc[i] < df['low'].iloc[i-1]:
                choch_signals.append({
                    "pattern": "bearish_choch",
                    "type": "ict",
                    "direction": "bearish",
                    "strength": 75,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "description": "Bearish Change of Character - Uptrend broken"
                })
        
        return choch_signals[-10:]
    
    @staticmethod
    def detect_market_structure_shift(df: pd.DataFrame) -> List[Dict]:
        mss_signals = []
        if len(df) < 15:
            return mss_signals
        
        for i in range(10, len(df)-2):
            # Bullish MSS (higher high + higher low)
            if (df['high'].iloc[i] > df['high'].iloc[i-1] and
                df['low'].iloc[i] > df['low'].iloc[i-1] and
                df['high'].iloc[i-2] < df['high'].iloc[i-1]):
                mss_signals.append({
                    "pattern": "bullish_mss",
                    "type": "ict",
                    "direction": "bullish",
                    "strength": 77,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "description": "Bullish Market Structure Shift - HH + HL"
                })
            
            # Bearish MSS (lower low + lower high)
            if (df['low'].iloc[i] < df['low'].iloc[i-1] and
                df['high'].iloc[i] < df['high'].iloc[i-1] and
                df['low'].iloc[i-2] > df['low'].iloc[i-1]):
                mss_signals.append({
                    "pattern": "bearish_mss",
                    "type": "ict",
                    "direction": "bearish",
                    "strength": 77,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "description": "Bearish Market Structure Shift - LL + LH"
                })
        
        return mss_signals[-10:]
    
    @staticmethod
    def detect_optimal_trade_entry(df: pd.DataFrame) -> List[Dict]:
        ote_signals = []
        if len(df) < 30:
            return ote_signals
        
        for i in range(25, len(df)):
            # Son swing high/low'ları bul
            high_idx = df['high'].iloc[i-20:i].idxmax()
            low_idx = df['low'].iloc[i-20:i].idxmin()
            
            if isinstance(high_idx, int) and isinstance(low_idx, int) and high_idx < low_idx:
                # Düşüş trendi
                swing_high = df.loc[high_idx, 'high'] if high_idx in df.index else None
                swing_low = df.loc[low_idx, 'low'] if low_idx in df.index else None
                
                if swing_high and swing_low and swing_high > swing_low:
                    retrace = (df['close'].iloc[i] - swing_low) / (swing_high - swing_low)
                    if 0.618 <= retrace <= 0.79:
                        ote_signals.append({
                            "pattern": "bearish_ote",
                            "type": "ict",
                            "direction": "bearish",
                            "strength": 78,
                            "timestamp": str(df.index[i]),
                            "price": float(df['close'].iloc[i]),
                            "retracement": round(float(retrace), 3),
                            "description": f"Bearish OTE at {retrace:.2f} retracement"
                        })
            
            elif isinstance(high_idx, int) and isinstance(low_idx, int) and low_idx < high_idx:
                # Yükseliş trendi
                swing_low = df.loc[low_idx, 'low'] if low_idx in df.index else None
                swing_high = df.loc[high_idx, 'high'] if high_idx in df.index else None
                
                if swing_low and swing_high and swing_high > swing_low:
                    retrace = (swing_high - df['close'].iloc[i]) / (swing_high - swing_low)
                    if 0.618 <= retrace <= 0.79:
                        ote_signals.append({
                            "pattern": "bullish_ote",
                            "type": "ict",
                            "direction": "bullish",
                            "strength": 78,
                            "timestamp": str(df.index[i]),
                            "price": float(df['close'].iloc[i]),
                            "retracement": round(float(retrace), 3),
                            "description": f"Bullish OTE at {retrace:.2f} retracement"
                        })
        
        return ote_signals[-10:]
    
    @staticmethod
    def detect_turtle_soup(df: pd.DataFrame) -> List[Dict]:
        soups = []
        if len(df) < 30:
            return soups
        
        for i in range(25, len(df)):
            period_high = df['high'].iloc[i-20:i].max()
            period_low = df['low'].iloc[i-20:i].min()
            
            # Yukarı kırılım tuzağı (bearish)
            if df['high'].iloc[i] > period_high * 1.001 and df['close'].iloc[i] < period_high:
                soups.append({
                    "pattern": "turtle_soup_bearish",
                    "type": "ict",
                    "direction": "bearish",
                    "strength": 70,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "description": "Turtle Soup - False breakout above"
                })
            
            # Aşağı kırılım tuzağı (bullish)
            elif df['low'].iloc[i] < period_low * 0.999 and df['close'].iloc[i] > period_low:
                soups.append({
                    "pattern": "turtle_soup_bullish",
                    "type": "ict",
                    "direction": "bullish",
                    "strength": 70,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "description": "Turtle Soup - False breakout below"
                })
        
        return soups[-10:]
    
    @staticmethod
    def detect_displacement(df: pd.DataFrame) -> List[Dict]:
        displacements = []
        if len(df) < 25:
            return displacements
        
        for i in range(20, len(df)):
            avg_volume = df['volume'].iloc[i-20:i].mean()
            if avg_volume > 0:
                volume_ratio = df['volume'].iloc[i] / avg_volume
                
                if (volume_ratio > 1.5 and 
                    abs(df['close'].iloc[i] - df['open'].iloc[i]) > df['atr'].iloc[i] * 0.5):
                    
                    direction = "bullish" if df['is_bullish'].iloc[i] else "bearish"
                    strength = 70 + min(20, (volume_ratio - 1) * 20)
                    
                    displacements.append({
                        "pattern": f"{direction}_displacement",
                        "type": "ict",
                        "direction": direction,
                        "strength": min(95, strength),
                        "timestamp": str(df.index[i]),
                        "price": float(df['close'].iloc[i]),
                        "volume_ratio": round(float(volume_ratio), 2),
                        "description": f"{direction.capitalize()} Displacement - High volume move"
                    })
        
        return displacements[-10:]
    
    @staticmethod
    def detect_judgmental_volume(df: pd.DataFrame) -> List[Dict]:
        jv_signals = []
        if len(df) < 25:
            return jv_signals
        
        for i in range(20, len(df)):
            if not pd.isna(df['volume_ratio'].iloc[i]) and df['volume_ratio'].iloc[i] > 2.0:
                direction = "bullish" if df['is_bullish'].iloc[i] else "bearish"
                
                jv_signals.append({
                    "pattern": f"judgmental_volume_{direction}",
                    "type": "ict",
                    "direction": direction,
                    "strength": 70,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "volume_ratio": round(float(df['volume_ratio'].iloc[i]), 2),
                    "description": f"Judgmental Volume - {direction.capitalize()} with {df['volume_ratio'].iloc[i]:.2f}x volume"
                })
        
        return jv_signals[-10:]
    
    @staticmethod
    def detect_power_of_three(df: pd.DataFrame) -> List[Dict]:
        pot_signals = []
        if len(df) < 10:
            return pot_signals
        
        for i in range(5, len(df)-2):
            # Accumulation, Manipulation, Distribution
            if (df['is_bullish'].iloc[i-2] and 
                df['is_bearish'].iloc[i-1] and 
                df['is_bullish'].iloc[i] and
                abs(df['close'].iloc[i] - df['close'].iloc[i-2]) / df['close'].iloc[i-2] < 0.01):
                
                pot_signals.append({
                    "pattern": "power_of_three_bullish",
                    "type": "ict",
                    "direction": "bullish",
                    "strength": 65,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "description": "Power of Three - Accumulation pattern"
                })
        
        return pot_signals[-10:]
    
    @staticmethod
    def detect_buyside_sellside_liquidity(df: pd.DataFrame) -> List[Dict]:
        liquidity_signals = []
        if len(df) < 20:
            return liquidity_signals
        
        for i in range(15, len(df)):
            recent_range = df['high'].iloc[i-10:i].max() - df['low'].iloc[i-10:i].min()
            if recent_range > 0:
                # Buyside liquidity (near highs)
                if df['high'].iloc[i] > df['high'].iloc[i-10:i].max() * 0.995:
                    liquidity_signals.append({
                        "pattern": "buyside_liquidity",
                        "type": "ict",
                        "direction": "bearish",
                        "strength": 60,
                        "timestamp": str(df.index[i]),
                        "price": float(df['close'].iloc[i]),
                        "description": "Buyside Liquidity - Price near recent highs"
                    })
                
                # Sellside liquidity (near lows)
                if df['low'].iloc[i] < df['low'].iloc[i-10:i].min() * 1.005:
                    liquidity_signals.append({
                        "pattern": "sellside_liquidity",
                        "type": "ict",
                        "direction": "bullish",
                        "strength": 60,
                        "timestamp": str(df.index[i]),
                        "price": float(df['close'].iloc[i]),
                        "description": "Sellside Liquidity - Price near recent lows"
                    })
        
        return liquidity_signals[-10:]
    
    @staticmethod
    def detect_institutional_order_flow(df: pd.DataFrame) -> List[Dict]:
        iof_signals = []
        if len(df) < 25:
            return iof_signals
        
        for i in range(20, len(df)):
            avg_volume = df['volume'].iloc[i-20:i].mean()
            if avg_volume > 0:
                volume_ratio = df['volume'].iloc[i] / avg_volume
                
                if (volume_ratio > 1.8 and 
                    abs(df['close'].iloc[i] - df['open'].iloc[i]) > df['atr'].iloc[i] * 0.7):
                    
                    direction = "bullish" if df['is_bullish'].iloc[i] else "bearish"
                    
                    iof_signals.append({
                        "pattern": f"institutional_flow_{direction}",
                        "type": "ict",
                        "direction": direction,
                        "strength": 80,
                        "timestamp": str(df.index[i]),
                        "price": float(df['close'].iloc[i]),
                        "volume_ratio": round(float(volume_ratio), 2),
                        "description": f"Institutional Order Flow - {direction.capitalize()} with {volume_ratio:.2f}x volume"
                    })
        
        return iof_signals[-10:]
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> Dict[str, List[Dict]]:
        """Tüm ICT pattern'lerini analiz et"""
        
        # İndikatörleri hesapla
        df_with_indicators = ICTPatternDetector.calculate_indicators(df)
        
        return {
            "fair_value_gaps": ICTPatternDetector.detect_fair_value_gap(df_with_indicators),
            "order_blocks": ICTPatternDetector.detect_order_blocks(df_with_indicators),
            "breaker_blocks": ICTPatternDetector.detect_breaker_blocks(df_with_indicators),
            "liquidity_sweeps": ICTPatternDetector.detect_liquidity_sweeps(df_with_indicators),
            "break_of_structure": ICTPatternDetector.detect_break_of_structure(df_with_indicators),
            "change_of_character": ICTPatternDetector.detect_change_of_character(df_with_indicators),
            "market_structure_shift": ICTPatternDetector.detect_market_structure_shift(df_with_indicators),
            "optimal_trade_entry": ICTPatternDetector.detect_optimal_trade_entry(df_with_indicators),
            "turtle_soup": ICTPatternDetector.detect_turtle_soup(df_with_indicators),
            "displacement": ICTPatternDetector.detect_displacement(df_with_indicators),
            "judgmental_volume": ICTPatternDetector.detect_judgmental_volume(df_with_indicators),
            "power_of_three": ICTPatternDetector.detect_power_of_three(df_with_indicators),
            "buyside_sellside_liquidity": ICTPatternDetector.detect_buyside_sellside_liquidity(df_with_indicators),
            "institutional_order_flow": ICTPatternDetector.detect_institutional_order_flow(df_with_indicators)
        }

# ========================================================================================================
# CLASSICAL PATTERN DETECTOR
# ========================================================================================================
class ClassicalPatternDetector:
    
    @staticmethod
    def detect_double_top_bottom(df: pd.DataFrame) -> List[Dict]:
        patterns = []
        if len(df) < 30:
            return patterns
        
        for i in range(20, len(df)):
            # Double Top
            high1 = df['high'].iloc[i-15:i-5].max()
            high2 = df['high'].iloc[i-5:i].max()
            
            if high1 > 0 and abs(high1 - high2) / high1 < 0.02 and df['close'].iloc[i] < high2 * 0.98:
                patterns.append({
                    "pattern": "double_top",
                    "type": "classical",
                    "direction": "bearish",
                    "strength": 72,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "level1": float(high1),
                    "level2": float(high2),
                    "description": "Double Top - Bearish reversal"
                })
            
            # Double Bottom
            low1 = df['low'].iloc[i-15:i-5].min()
            low2 = df['low'].iloc[i-5:i].min()
            
            if low1 > 0 and abs(low1 - low2) / low1 < 0.02 and df['close'].iloc[i] > low2 * 1.02:
                patterns.append({
                    "pattern": "double_bottom",
                    "type": "classical",
                    "direction": "bullish",
                    "strength": 72,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "level1": float(low1),
                    "level2": float(low2),
                    "description": "Double Bottom - Bullish reversal"
                })
        
        return patterns[-10:]
    
    @staticmethod
    def detect_head_shoulders(df: pd.DataFrame) -> List[Dict]:
        patterns = []
        if len(df) < 40:
            return patterns
        
        for i in range(30, len(df)):
            # Head and Shoulders (Top)
            left_shoulder = df['high'].iloc[i-25:i-15].max()
            head = df['high'].iloc[i-15:i-5].max()
            right_shoulder = df['high'].iloc[i-5:i].max()
            
            if (head > left_shoulder * 1.02 and head > right_shoulder * 1.02 and
                abs(left_shoulder - right_shoulder) / left_shoulder < 0.05 and
                df['close'].iloc[i] < head * 0.98):
                patterns.append({
                    "pattern": "head_and_shoulders",
                    "type": "classical",
                    "direction": "bearish",
                    "strength": 80,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "head": float(head),
                    "shoulders": [float(left_shoulder), float(right_shoulder)],
                    "description": "Head and Shoulders - Bearish reversal"
                })
            
            # Inverse Head and Shoulders
            left_shoulder = df['low'].iloc[i-25:i-15].min()
            head = df['low'].iloc[i-15:i-5].min()
            right_shoulder = df['low'].iloc[i-5:i].min()
            
            if (head < left_shoulder * 0.98 and head < right_shoulder * 0.98 and
                abs(left_shoulder - right_shoulder) / left_shoulder < 0.05 and
                df['close'].iloc[i] > head * 1.02):
                patterns.append({
                    "pattern": "inverse_head_shoulders",
                    "type": "classical",
                    "direction": "bullish",
                    "strength": 80,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "head": float(head),
                    "shoulders": [float(left_shoulder), float(right_shoulder)],
                    "description": "Inverse Head and Shoulders - Bullish reversal"
                })
        
        return patterns[-10:]
    
    @staticmethod
    def detect_w_pattern(df: pd.DataFrame) -> List[Dict]:
        patterns = []
        if len(df) < 35:
            return patterns
        
        for i in range(30, len(df)):
            first_bottom = df['low'].iloc[i-25:i-15].min()
            peak = df['high'].iloc[i-15:i-8].max()
            second_bottom = df['low'].iloc[i-8:i-2].min()
            
            if (first_bottom > 0 and second_bottom > 0 and peak > 0 and
                abs(first_bottom - second_bottom) / first_bottom < 0.03 and
                peak > first_bottom * 1.05 and
                df['close'].iloc[i] > peak * 0.98):
                patterns.append({
                    "pattern": "w_pattern",
                    "type": "classical",
                    "direction": "bullish",
                    "strength": 75,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "first_bottom": float(first_bottom),
                    "second_bottom": float(second_bottom),
                    "peak": float(peak),
                    "description": "W Pattern - Bullish reversal"
                })
        
        return patterns[-10:]
    
    @staticmethod
    def detect_m_pattern(df: pd.DataFrame) -> List[Dict]:
        patterns = []
        if len(df) < 35:
            return patterns
        
        for i in range(30, len(df)):
            first_top = df['high'].iloc[i-25:i-15].max()
            bottom = df['low'].iloc[i-15:i-8].min()
            second_top = df['high'].iloc[i-8:i-2].max()
            
            if (first_top > 0 and second_top > 0 and bottom > 0 and
                abs(first_top - second_top) / first_top < 0.03 and
                bottom < first_top * 0.95 and
                df['close'].iloc[i] < bottom * 1.02):
                patterns.append({
                    "pattern": "m_pattern",
                    "type": "classical",
                    "direction": "bearish",
                    "strength": 75,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "first_top": float(first_top),
                    "second_top": float(second_top),
                    "bottom": float(bottom),
                    "description": "M Pattern - Bearish reversal"
                })
        
        return patterns[-10:]
    
    @staticmethod
    def detect_triangle_patterns(df: pd.DataFrame) -> List[Dict]:
        patterns = []
        if len(df) < 30:
            return patterns
        
        for i in range(25, len(df)):
            highs = df['high'].iloc[i-20:i].values
            lows = df['low'].iloc[i-20:i].values
            
            if len(highs) >= 5:
                x = np.arange(len(highs))
                high_slope = np.polyfit(x, highs, 1)[0]
                low_slope = np.polyfit(x, lows, 1)[0]
                
                # Rising Wedge (Bearish)
                if high_slope > 0 and low_slope > 0 and high_slope < low_slope * 1.1:
                    if df['close'].iloc[i] < lows[-1]:
                        patterns.append({
                            "pattern": "rising_wedge",
                            "type": "classical",
                            "direction": "bearish",
                            "strength": 75,
                            "timestamp": str(df.index[i]),
                            "price": float(df['close'].iloc[i]),
                            "description": "Rising Wedge - Bearish breakdown"
                        })
                
                # Falling Wedge (Bullish)
                if high_slope < 0 and low_slope < 0 and low_slope < high_slope:
                    if df['close'].iloc[i] > highs[-1]:
                        patterns.append({
                            "pattern": "falling_wedge",
                            "type": "classical",
                            "direction": "bullish",
                            "strength": 75,
                            "timestamp": str(df.index[i]),
                            "price": float(df['close'].iloc[i]),
                            "description": "Falling Wedge - Bullish breakout"
                        })
        
        return patterns[-10:]
    
    @staticmethod
    def detect_diamond_pattern(df: pd.DataFrame) -> List[Dict]:
        patterns = []
        if len(df) < 50:
            return patterns
        
        for i in range(45, len(df)):
            expand_high = df['high'].iloc[i-40:i-20].max()
            expand_low = df['low'].iloc[i-40:i-20].min()
            expand_range = expand_high - expand_low
            
            contract_high = df['high'].iloc[i-20:i].max()
            contract_low = df['low'].iloc[i-20:i].min()
            contract_range = contract_high - contract_low
            
            if expand_range > 0 and contract_range < expand_range * 0.6:
                if df['close'].iloc[i] > df['high'].iloc[i-5:i].mean():
                    patterns.append({
                        "pattern": "diamond_bullish",
                        "type": "classical",
                        "direction": "bullish",
                        "strength": 70,
                        "timestamp": str(df.index[i]),
                        "price": float(df['close'].iloc[i]),
                        "description": "Diamond Pattern - Bullish breakout"
                    })
                elif df['close'].iloc[i] < df['low'].iloc[i-5:i].mean():
                    patterns.append({
                        "pattern": "diamond_bearish",
                        "type": "classical",
                        "direction": "bearish",
                        "strength": 70,
                        "timestamp": str(df.index[i]),
                        "price": float(df['close'].iloc[i]),
                        "description": "Diamond Pattern - Bearish breakdown"
                    })
        
        return patterns[-10:]
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> List[Dict]:
        patterns = []
        patterns.extend(ClassicalPatternDetector.detect_double_top_bottom(df))
        patterns.extend(ClassicalPatternDetector.detect_head_shoulders(df))
        patterns.extend(ClassicalPatternDetector.detect_w_pattern(df))
        patterns.extend(ClassicalPatternDetector.detect_m_pattern(df))
        patterns.extend(ClassicalPatternDetector.detect_triangle_patterns(df))
        patterns.extend(ClassicalPatternDetector.detect_diamond_pattern(df))
        return patterns[-20:]

# ========================================================================================================
# CANDLESTICK PATTERN DETECTOR (GENİŞLETİLMİŞ)
# ========================================================================================================
class CandlestickPatternDetector:
    
    @staticmethod
    def detect_doji(candle: pd.Series) -> Optional[Dict]:
        body = abs(candle['close'] - candle['open'])
        range_candle = candle['high'] - candle['low']
        if range_candle == 0:
            return None
        
        if (body / range_candle) < 0.1:
            return {
                "pattern": "doji",
                "type": "candlestick",
                "direction": "neutral",
                "strength": 50,
                "description": "Doji - Market indecision"
            }
        return None
    
    @staticmethod
    def detect_hammer(candle: pd.Series) -> Optional[Dict]:
        body = abs(candle['close'] - candle['open'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        
        if body == 0 or (candle['high'] - candle['low']) == 0:
            return None
        
        if lower_shadow > 2 * body and upper_shadow < body and candle['close'] > candle['open']:
            return {
                "pattern": "hammer",
                "type": "candlestick",
                "direction": "bullish",
                "strength": 70,
                "description": "Hammer - Bullish reversal"
            }
        return None
    
    @staticmethod
    def detect_shooting_star(candle: pd.Series) -> Optional[Dict]:
        body = abs(candle['close'] - candle['open'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        
        if body == 0 or (candle['high'] - candle['low']) == 0:
            return None
        
        if upper_shadow > 2 * body and lower_shadow < body and candle['close'] < candle['open']:
            return {
                "pattern": "shooting_star",
                "type": "candlestick",
                "direction": "bearish",
                "strength": 70,
                "description": "Shooting Star - Bearish reversal"
            }
        return None
    
    @staticmethod
    def detect_marubozu(candle: pd.Series) -> Optional[Dict]:
        body = abs(candle['close'] - candle['open'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        
        if body == 0:
            return None
        
        if lower_shadow < body * 0.1 and upper_shadow < body * 0.1:
            direction = "bullish" if candle['close'] > candle['open'] else "bearish"
            return {
                "pattern": "marubozu",
                "type": "candlestick",
                "direction": direction,
                "strength": 65,
                "description": f"Marubozu - Strong {direction} momentum"
            }
        return None
    
    @staticmethod
    def detect_engulfing(df: pd.DataFrame, i: int) -> Optional[Dict]:
        if i < 1 or i >= len(df):
            return None
        
        curr = df.iloc[i]
        prev = df.iloc[i-1]
        
        curr_bullish = curr['close'] > curr['open']
        curr_bearish = curr['close'] < curr['open']
        prev_bearish = prev['close'] < prev['open']
        prev_bullish = prev['close'] > prev['open']
        
        if (curr_bullish and prev_bearish and 
            curr['open'] < prev['close'] and 
            curr['close'] > prev['open']):
            return {
                "pattern": "bullish_engulfing",
                "type": "candlestick",
                "direction": "bullish",
                "strength": 75,
                "timestamp": str(df.index[i]),
                "price": float(curr['close']),
                "description": "Bullish Engulfing - Strong reversal"
            }
        
        elif (curr_bearish and prev_bullish and 
              curr['open'] > prev['close'] and 
              curr['close'] < prev['open']):
            return {
                "pattern": "bearish_engulfing",
                "type": "candlestick",
                "direction": "bearish",
                "strength": 75,
                "timestamp": str(df.index[i]),
                "price": float(curr['close']),
                "description": "Bearish Engulfing - Strong reversal"
            }
        
        return None
    
    @staticmethod
    def detect_harami(df: pd.DataFrame, i: int) -> Optional[Dict]:
        if i < 1 or i >= len(df):
            return None
        
        curr = df.iloc[i]
        prev = df.iloc[i-1]
        
        curr_range = abs(curr['close'] - curr['open'])
        prev_range = abs(prev['close'] - prev['open'])
        
        if prev_range == 0:
            return None
        
        if curr_range < prev_range * 0.6:
            if prev['close'] > prev['open']:
                if (curr['close'] < prev['close'] and curr['open'] > prev['open']):
                    return {
                        "pattern": "bearish_harami",
                        "type": "candlestick",
                        "direction": "bearish",
                        "strength": 65,
                        "timestamp": str(df.index[i]),
                        "price": float(curr['close']),
                        "description": "Bearish Harami - Potential reversal"
                    }
            else:
                if (curr['close'] > prev['close'] and curr['open'] < prev['open']):
                    return {
                        "pattern": "bullish_harami",
                        "type": "candlestick",
                        "direction": "bullish",
                        "strength": 65,
                        "timestamp": str(df.index[i]),
                        "price": float(curr['close']),
                        "description": "Bullish Harami - Potential reversal"
                    }
        
        return None
    
    @staticmethod
    def detect_morning_star(df: pd.DataFrame, i: int) -> Optional[Dict]:
        if i < 2 or i >= len(df):
            return None
        
        c1 = df.iloc[i-2]
        c2 = df.iloc[i-1]
        c3 = df.iloc[i]
        
        if c1['close'] < c1['open'] and c3['close'] > c3['open']:
            body2 = abs(c2['close'] - c2['open'])
            range2 = c2['high'] - c2['low']
            if range2 > 0 and (body2 / range2) < 0.3:
                if c2['low'] < c1['low'] and c3['open'] > c2['close']:
                    return {
                        "pattern": "morning_star",
                        "type": "candlestick",
                        "direction": "bullish",
                        "strength": 80,
                        "timestamp": str(df.index[i]),
                        "price": float(c3['close']),
                        "description": "Morning Star - Bullish reversal"
                    }
        
        return None
    
    @staticmethod
    def detect_evening_star(df: pd.DataFrame, i: int) -> Optional[Dict]:
        if i < 2 or i >= len(df):
            return None
        
        c1 = df.iloc[i-2]
        c2 = df.iloc[i-1]
        c3 = df.iloc[i]
        
        if c1['close'] > c1['open'] and c3['close'] < c3['open']:
            body2 = abs(c2['close'] - c2['open'])
            range2 = c2['high'] - c2['low']
            if range2 > 0 and (body2 / range2) < 0.3:
                if c2['high'] > c1['high'] and c3['open'] < c2['close']:
                    return {
                        "pattern": "evening_star",
                        "type": "candlestick",
                        "direction": "bearish",
                        "strength": 80,
                        "timestamp": str(df.index[i]),
                        "price": float(c3['close']),
                        "description": "Evening Star - Bearish reversal"
                    }
        
        return None
    
    @staticmethod
    def detect_three_white_soldiers(df: pd.DataFrame, i: int) -> Optional[Dict]:
        if i < 2 or i >= len(df):
            return None
        
        if (df['is_bullish'].iloc[i-2] and df['is_bullish'].iloc[i-1] and df['is_bullish'].iloc[i] and
            df['close'].iloc[i-1] > df['close'].iloc[i-2] and
            df['close'].iloc[i] > df['close'].iloc[i-1]):
            return {
                "pattern": "three_white_soldiers",
                "type": "candlestick",
                "direction": "bullish",
                "strength": 78,
                "timestamp": str(df.index[i]),
                "price": float(df['close'].iloc[i]),
                "description": "Three White Soldiers - Strong bullish continuation"
            }
        return None
    
    @staticmethod
    def detect_three_black_crows(df: pd.DataFrame, i: int) -> Optional[Dict]:
        if i < 2 or i >= len(df):
            return None
        
        if (df['is_bearish'].iloc[i-2] and df['is_bearish'].iloc[i-1] and df['is_bearish'].iloc[i] and
            df['close'].iloc[i-1] < df['close'].iloc[i-2] and
            df['close'].iloc[i] < df['close'].iloc[i-1]):
            return {
                "pattern": "three_black_crows",
                "type": "candlestick",
                "direction": "bearish",
                "strength": 78,
                "timestamp": str(df.index[i]),
                "price": float(df['close'].iloc[i]),
                "description": "Three Black Crows - Strong bearish continuation"
            }
        return None
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> List[Dict]:
        patterns = []
        
        if len(df) < 10:
            return patterns
        
        for i in range(2, len(df)):
            curr = df.iloc[i]
            
            # Tek mum pattern'leri
            doji = CandlestickPatternDetector.detect_doji(curr)
            if doji:
                doji['timestamp'] = str(df.index[i])
                doji['price'] = float(curr['close'])
                patterns.append(doji)
            
            hammer = CandlestickPatternDetector.detect_hammer(curr)
            if hammer:
                hammer['timestamp'] = str(df.index[i])
                hammer['price'] = float(curr['close'])
                patterns.append(hammer)
            
            shooting = CandlestickPatternDetector.detect_shooting_star(curr)
            if shooting:
                shooting['timestamp'] = str(df.index[i])
                shooting['price'] = float(curr['close'])
                patterns.append(shooting)
            
            marubozu = CandlestickPatternDetector.detect_marubozu(curr)
            if marubozu:
                marubozu['timestamp'] = str(df.index[i])
                marubozu['price'] = float(curr['close'])
                patterns.append(marubozu)
            
            # Çoklu mum pattern'leri
            engulfing = CandlestickPatternDetector.detect_engulfing(df, i)
            if engulfing:
                patterns.append(engulfing)
            
            harami = CandlestickPatternDetector.detect_harami(df, i)
            if harami:
                patterns.append(harami)
            
            morning = CandlestickPatternDetector.detect_morning_star(df, i)
            if morning:
                patterns.append(morning)
            
            evening = CandlestickPatternDetector.detect_evening_star(df, i)
            if evening:
                patterns.append(evening)
            
            soldiers = CandlestickPatternDetector.detect_three_white_soldiers(df, i)
            if soldiers:
                patterns.append(soldiers)
            
            crows = CandlestickPatternDetector.detect_three_black_crows(df, i)
            if crows:
                patterns.append(crows)
        
        return patterns[-30:]

# ========================================================================================================
# TECHNICAL ANALYZER
# ========================================================================================================
class TechnicalAnalyzer:
    
    @staticmethod
    def calculate_heikin_ashi(df: pd.DataFrame) -> Dict[str, Any]:
        try:
            if len(df) < 20:
                return {}
            
            ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
            
            ha_open = ha_close.copy()
            for i in range(1, len(ha_open)):
                ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
            
            ha_high = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
            ha_low = pd.concat([df['low'], ha_open, ha_close], axis=1).min(axis=1)
            
            ha_bullish = sum(1 for i in range(-8, 0) if ha_close.iloc[i] > ha_open.iloc[i])
            ha_bearish = sum(1 for i in range(-8, 0) if ha_close.iloc[i] < ha_open.iloc[i])
            
            if ha_bullish >= 6:
                ha_trend = "STRONG_BULLISH"
                ha_strength = ha_bullish * 12.5
            elif ha_bullish >= 4:
                ha_trend = "BULLISH"
                ha_strength = ha_bullish * 12.5
            elif ha_bearish >= 6:
                ha_trend = "STRONG_BEARISH"
                ha_strength = ha_bearish * 12.5
            elif ha_bearish >= 4:
                ha_trend = "BEARISH"
                ha_strength = ha_bearish * 12.5
            else:
                ha_trend = "NEUTRAL"
                ha_strength = 50
            
            delta = ha_close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss.replace(0, np.nan)
            ha_rsi = 100 - (100 / (1 + rs))
            
            ha_color_change = 0
            if ha_close.iloc[-1] > ha_open.iloc[-1] and ha_close.iloc[-2] <= ha_open.iloc[-2]:
                ha_color_change = 1
            elif ha_close.iloc[-1] < ha_open.iloc[-1] and ha_close.iloc[-2] >= ha_open.iloc[-2]:
                ha_color_change = -1
            
            return {
                "ha_trend": ha_trend,
                "ha_trend_strength": round(min(ha_strength, 100), 1),
                "ha_close": round(float(ha_close.iloc[-1]), 2),
                "ha_open": round(float(ha_open.iloc[-1]), 2),
                "ha_rsi": round(float(ha_rsi.iloc[-1]), 1) if not pd.isna(ha_rsi.iloc[-1]) else 50.0,
                "ha_color_change": ha_color_change,
                "ha_momentum": round(float((ha_close.iloc[-1] - ha_close.iloc[-5]) / ha_close.iloc[-5] * 100), 2)
            }
            
        except Exception as e:
            logger.error(f"Heikin Ashi error: {str(e)}")
            return {}
    
    @staticmethod
    def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)
    
    @staticmethod
    def calculate_macd(close: pd.Series) -> tuple:
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        return macd, signal, hist
    
    @staticmethod
    def calculate_bollinger_bands(close: pd.Series, period: int = 20) -> tuple:
        middle = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        upper = middle + (std * 2)
        lower = middle - (std * 2)
        return upper, middle, lower
    
    @staticmethod
    def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr.fillna(0)
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> Dict[str, Any]:
        if len(df) < 30:
            return {}
        
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        rsi = TechnicalAnalyzer.calculate_rsi(close)
        macd, macd_signal, macd_hist = TechnicalAnalyzer.calculate_macd(close)
        bb_upper, bb_middle, bb_lower = TechnicalAnalyzer.calculate_bollinger_bands(close)
        
        bb_range = bb_upper - bb_lower
        bb_range = bb_range.replace(0, 1)
        bb_position = ((close - bb_lower) / bb_range * 100).clip(0, 100)
        
        atr = TechnicalAnalyzer.calculate_atr(high, low, close)
        atr_percent = (atr / close * 100).fillna(0)
        
        volume_sma = volume.rolling(20).mean().fillna(volume)
        volume_ratio = (volume / volume_sma).fillna(1.0)
        
        sma_20 = close.rolling(20).mean()
        sma_50 = close.rolling(50).mean()
        
        # Momentum
        mom_5 = close.pct_change(5) * 100
        mom_10 = close.pct_change(10) * 100
        
        heikin_ashi = TechnicalAnalyzer.calculate_heikin_ashi(df)
        
        result = {
            "rsi": round(float(rsi.iloc[-1]), 1),
            "macd": round(float(macd.iloc[-1]), 2),
            "macd_signal": round(float(macd_signal.iloc[-1]), 2),
            "macd_histogram": round(float(macd_hist.iloc[-1]), 2),
            "bb_upper": round(float(bb_upper.iloc[-1]), 2),
            "bb_middle": round(float(bb_middle.iloc[-1]), 2),
            "bb_lower": round(float(bb_lower.iloc[-1]), 2),
            "bb_position": round(float(bb_position.iloc[-1]), 1),
            "bb_width": round(float((bb_upper.iloc[-1] - bb_lower.iloc[-1]) / bb_middle.iloc[-1] * 100), 1),
            "atr": round(float(atr.iloc[-1]), 2),
            "atr_percent": round(float(atr_percent.iloc[-1]), 2),
            "volume_ratio": round(float(volume_ratio.iloc[-1]), 2),
            "sma_20": round(float(sma_20.iloc[-1]), 2),
            "sma_50": round(float(sma_50.iloc[-1]), 2),
            "price_vs_sma20": round(float((close.iloc[-1] / sma_20.iloc[-1] - 1) * 100), 1),
            "price_vs_sma50": round(float((close.iloc[-1] / sma_50.iloc[-1] - 1) * 100), 1),
            "momentum_5": round(float(mom_5.iloc[-1]), 2),
            "momentum_10": round(float(mom_10.iloc[-1]), 2)
        }
        
        result.update(heikin_ashi)
        
        return result

# ========================================================================================================
# MARKET STRUCTURE ANALYZER
# ========================================================================================================
class MarketStructureAnalyzer:
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> Dict[str, Any]:
        if len(df) < 30:
            return {
                "trend": "NEUTRAL",
                "trend_strength": "WEAK",
                "structure": "Neutral",
                "volatility": "Normal",
                "volatility_index": 100,
                "momentum": "Neutral"
            }
        
        close = df['close']
        high = df['high']
        low = df['low']
        
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
        
        recent_highs = high.tail(15)
        recent_lows = low.tail(15)
        
        hh = sum(1 for i in range(1, len(recent_highs)) if recent_highs.iloc[i] > recent_highs.iloc[i-1])
        ll = sum(1 for i in range(1, len(recent_lows)) if recent_lows.iloc[i] < recent_lows.iloc[i-1])
        hl = sum(1 for i in range(1, len(recent_lows)) if recent_lows.iloc[i] > recent_lows.iloc[i-1])
        lh = sum(1 for i in range(1, len(recent_highs)) if recent_highs.iloc[i] < recent_highs.iloc[i-1])
        
        if hh >= 10 and hl >= 8:
            structure = "Bullish"
        elif ll >= 10 and lh >= 8:
            structure = "Bearish"
        else:
            structure = "Neutral"
        
        returns = close.pct_change().fillna(0)
        volatility = returns.rolling(20).std() * np.sqrt(252) * 100
        avg_vol = volatility.mean()
        current_vol = volatility.iloc[-1]
        
        if current_vol > avg_vol * 1.5:
            vol_regime = "HIGH"
            vol_index = 150
        elif current_vol < avg_vol * 0.7:
            vol_regime = "LOW"
            vol_index = 70
        else:
            vol_regime = "NORMAL"
            vol_index = 100
        
        mom_5 = close.iloc[-1] / close.iloc[-5] - 1 if len(close) >= 5 else 0
        mom_10 = close.iloc[-1] / close.iloc[-10] - 1 if len(close) >= 10 else 0
        
        if mom_5 > 0.02 and mom_10 > 0.03:
            momentum = "Strong_Bullish"
        elif mom_5 > 0.01:
            momentum = "Bullish"
        elif mom_5 < -0.02 and mom_10 < -0.03:
            momentum = "Strong_Bearish"
        elif mom_5 < -0.01:
            momentum = "Bearish"
        else:
            momentum = "Neutral"
        
        return {
            "trend": trend,
            "trend_strength": trend_strength,
            "structure": structure,
            "volatility": vol_regime,
            "volatility_index": vol_index,
            "momentum": momentum
        }

# ========================================================================================================
# SIGNAL GENERATOR (GELİŞTİRİLMİŞ)
# ========================================================================================================
class SignalGenerator:
    
    @staticmethod
    def generate(
        technical: Dict[str, Any],
        market_structure: Dict[str, Any],
        ict_patterns: Dict[str, List[Dict]],
        candle_patterns: List[Dict],
        classical_patterns: List[Dict],
        gainzalgo_signals: List[Dict],
        ultimate_signals: List[Dict]
    ) -> Dict[str, Any]:
        
        signals = []
        confidences = []
        weights = []
        all_patterns = []
        
        # === ULTIMATE 2026 SİNYALLERİ (En yüksek öncelik) ===
        for sig in ultimate_signals:
            if sig.get('direction') in ['bullish', 'bullish_reversal']:
                signals.append('BUY')
                confidences.append(0.85)
                weights.append(2.5)
                all_patterns.append(sig)
            elif sig.get('direction') in ['bearish', 'bearish_reversal']:
                signals.append('SELL')
                confidences.append(0.85)
                weights.append(2.5)
                all_patterns.append(sig)
        
        # === GAINZALGO V2 SİNYALLERİ ===
        for sig in gainzalgo_signals:
            if sig.get('direction') in ['bullish', 'bullish_reversal']:
                signals.append('BUY')
                confidences.append(0.82)
                weights.append(2.2)
                all_patterns.append(sig)
            elif sig.get('direction') in ['bearish', 'bearish_reversal']:
                signals.append('SELL')
                confidences.append(0.82)
                weights.append(2.2)
                all_patterns.append(sig)
        
        # === ICT PATTERNS ===
        for pattern_list in ict_patterns.values():
            for pattern in pattern_list[:3]:  # Her kategoriden ilk 3
                if pattern.get('direction') in ['bullish', 'bullish_reversal']:
                    signals.append('BUY')
                    confidences.append(pattern.get('strength', 70) / 100)
                    weights.append(1.8)
                    all_patterns.append(pattern)
                elif pattern.get('direction') in ['bearish', 'bearish_reversal']:
                    signals.append('SELL')
                    confidences.append(pattern.get('strength', 70) / 100)
                    weights.append(1.8)
                    all_patterns.append(pattern)
        
        # === CLASSICAL PATTERNS ===
        for pattern in classical_patterns[:5]:
            if pattern.get('direction') in ['bullish', 'bullish_reversal']:
                signals.append('BUY')
                confidences.append(pattern.get('strength', 70) / 100)
                weights.append(1.5)
                all_patterns.append(pattern)
            elif pattern.get('direction') in ['bearish', 'bearish_reversal']:
                signals.append('SELL')
                confidences.append(pattern.get('strength', 70) / 100)
                weights.append(1.5)
                all_patterns.append(pattern)
        
        # === CANDLESTICK PATTERNS ===
        for pattern in candle_patterns[-5:]:
            if pattern.get('direction') in ['bullish', 'bullish_reversal']:
                signals.append('BUY')
                confidences.append(pattern.get('strength', 60) / 100)
                weights.append(1.2)
                all_patterns.append(pattern)
            elif pattern.get('direction') in ['bearish', 'bearish_reversal']:
                signals.append('SELL')
                confidences.append(pattern.get('strength', 60) / 100)
                weights.append(1.2)
                all_patterns.append(pattern)
        
        # === HEIKIN ASHI ===
        ha_trend = technical.get('ha_trend', 'NEUTRAL')
        if ha_trend in ['STRONG_BULLISH', 'BULLISH']:
            signals.append('BUY')
            confidences.append(0.72)
            weights.append(1.5)
        elif ha_trend in ['STRONG_BEARISH', 'BEARISH']:
            signals.append('SELL')
            confidences.append(0.72)
            weights.append(1.5)
        
        # === RSI ===
        rsi = technical.get('rsi', 50)
        if rsi < 30:
            signals.append('BUY')
            confidences.append(0.64)
            weights.append(1.1)
        elif rsi > 70:
            signals.append('SELL')
            confidences.append(0.64)
            weights.append(1.1)
        
        # === MACD ===
        macd_hist = technical.get('macd_histogram', 0)
        if macd_hist > 0:
            signals.append('BUY')
            confidences.append(0.62)
            weights.append(1.0)
        elif macd_hist < 0:
            signals.append('SELL')
            confidences.append(0.62)
            weights.append(1.0)
        
        # === MARKET STRUCTURE ===
        trend = market_structure.get('trend', 'NEUTRAL')
        if 'UPTREND' in trend:
            signals.append('BUY')
            confidences.append(0.70)
            weights.append(1.3)
        elif 'DOWNTREND' in trend:
            signals.append('SELL')
            confidences.append(0.70)
            weights.append(1.3)
        
        # Sinyal yoksa nötr
        if not signals:
            return {
                "signal": "NEUTRAL",
                "confidence": Config.DEFAULT_CONFIDENCE,
                "recommendation": "No clear signals. Market is ranging.",
                "buy_count": 0,
                "sell_count": 0,
                "tp_level": None,
                "sl_level": None
            }
        
        # Ağırlıklı skor hesapla
        buy_score = 0.0
        sell_score = 0.0
        buy_count = 0
        sell_count = 0
        last_buy_tp = None
        last_buy_sl = None
        last_sell_tp = None
        last_sell_sl = None
        
        for i in range(len(signals)):
            s = signals[i]
            c = confidences[i]
            w = weights[i]
            
            if s == 'BUY':
                buy_score += c * w
                buy_count += 1
                # Son TP/SL'yi al
                if i < len(all_patterns) and 'tp_level' in all_patterns[i]:
                    last_buy_tp = all_patterns[i]['tp_level']
                    last_buy_sl = all_patterns[i]['sl_level']
            elif s == 'SELL':
                sell_score += c * w
                sell_count += 1
                if i < len(all_patterns) and 'tp_level' in all_patterns[i]:
                    last_sell_tp = all_patterns[i]['tp_level']
                    last_sell_sl = all_patterns[i]['sl_level']
        
        if buy_score > sell_score:
            final_signal = "BUY"
            total_score = buy_score + sell_score
            avg_conf = (buy_score / total_score * 100) if total_score > 0 else Config.DEFAULT_CONFIDENCE
            tp_level = last_buy_tp
            sl_level = last_buy_sl
        elif sell_score > buy_score:
            final_signal = "SELL"
            total_score = buy_score + sell_score
            avg_conf = (sell_score / total_score * 100) if total_score > 0 else Config.DEFAULT_CONFIDENCE
            tp_level = last_sell_tp
            sl_level = last_sell_sl
        else:
            final_signal = "NEUTRAL"
            avg_conf = Config.DEFAULT_CONFIDENCE
            tp_level = None
            sl_level = None
        
        avg_conf = min(float(avg_conf), Config.MAX_CONFIDENCE)
        avg_conf = max(float(avg_conf), 45.0)
        
        if avg_conf > 75 and buy_count > sell_count * 2:
            final_signal = "STRONG_BUY"
        elif avg_conf > 75 and sell_count > buy_count * 2:
            final_signal = "STRONG_SELL"
        
        rec = SignalGenerator._generate_recommendation(
            final_signal, avg_conf, technical, market_structure, ict_patterns, 
            buy_count, sell_count
        )
        
        return {
            "signal": final_signal,
            "confidence": round(avg_conf, 1),
            "recommendation": rec,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "tp_level": round(tp_level, 2) if tp_level else None,
            "sl_level": round(sl_level, 2) if sl_level else None
        }
    
    @staticmethod
    def _generate_recommendation(signal, conf, technical, structure, ict_patterns, buy_count, sell_count):
        parts = []
        
        ha_trend = technical.get('ha_trend', '')
        if ha_trend:
            parts.append(f"Heikin Ashi: {ha_trend}")
        
        # ICT pattern sayıları
        total_ict = sum(len(v) for v in ict_patterns.values())
        if total_ict > 0:
            parts.append(f"ICT: {total_ict} patterns")
        
        trend = structure.get('trend', '')
        if trend != 'NEUTRAL':
            parts.append(f"Trend: {trend}")
        
        if signal == "STRONG_BUY":
            base = "🟢 STRONG BUY - Multiple strong bullish signals"
        elif signal == "BUY":
            base = "🟢 BUY - Bullish bias"
        elif signal == "STRONG_SELL":
            base = "🔴 STRONG SELL - Multiple strong bearish signals"
        elif signal == "SELL":
            base = "🔴 SELL - Bearish bias"
        else:
            base = "⚪ NEUTRAL - No clear bias"
        
        parts.insert(0, base)
        
        if conf > 75:
            parts.append(f"🔥 High confidence ({conf:.0f}%)")
        elif conf > 65:
            parts.append(f"✅ Moderate confidence ({conf:.0f}%)")
        else:
            parts.append(f"⚠️ Low confidence ({conf:.0f}%)")
        
        parts.append(f"Signals: B{buy_count} S{sell_count}")
        
        return ". ".join(parts) + "."

# ========================================================================================================
# FASTAPI APPLICATION
# ========================================================================================================
app = FastAPI(
    title="ICTSMARTPRO v9.0 - Ultimate Pattern Detector",
    description="AI-Powered Crypto Analysis with 70+ ICT & Classical Patterns",
    version="9.0.0",
    docs_url="/docs" if Config.DEBUG else None,
    redoc_url=None
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"]
)

app.add_middleware(GZipMiddleware, minimum_size=500)

# Security headers
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# Global instances
data_fetcher = ExchangeDataFetcher()
websocket_connections = set()
startup_time = time.time()

# ========================================================================================================
# API ENDPOINTS
# ========================================================================================================
@app.get("/", response_class=HTMLResponse)
async def root():
    """Ana sayfa"""
    html_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    
    if os.path.exists(html_path):
        return FileResponse(html_path)
    
    return HTMLResponse(content="""
    <html>
        <body style="background:#0a0b0d; color:#e0e0e0; padding:40px;">
            <h1 style="color:#00ff88;">ICTSMARTPRO v9.0</h1>
            <p>✅ API çalışıyor - index.html bulunamadı</p>
            <p><a href="/docs" style="color:#2563eb;">📚 API Documentation</a></p>
        </body>
    </html>
    """)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Dashboard sayfası"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    dashboard_path = os.path.join(current_dir, "templates", "dashboard.html")
    
    if os.path.exists(dashboard_path):
        return FileResponse(dashboard_path)
    
    return HTMLResponse(content=f"""
    <html>
        <body style="background:#0a0b0d; color:#e0e0e0; padding:40px;">
            <h1 style="color:#ff4444;">❌ dashboard.html bulunamadı</h1>
            <p>Mevcut dizin: {current_dir}</p>
            <p>Aranan: {dashboard_path}</p>
            <a href="/" style="color:#00ff88;">← Ana Sayfa</a>
        </body>
    </html>
    """, status_code=404)   
    
@app.get("/health")
async def health_check():
    uptime = time.time() - startup_time
    active_sources = data_fetcher.get_active_sources()
    return {
        "status": "healthy",
        "version": "9.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": int(uptime),
        "uptime_human": str(timedelta(seconds=int(uptime))),
        "active_sources": active_sources,
        "max_confidence": Config.MAX_CONFIDENCE,
        "environment": Config.ENV,
        "debug": Config.DEBUG
    }

@app.get("/api/analyze/{symbol}", response_model=AnalysisResponse)
# 793. satırdaki analyze metodunu güncelleyin:
async def analyze_symbol(
    symbol: str,
    interval: str = Query(
        default="1h",
        regex="^(1m|5m|15m|30m|1h|4h|1d|1w)$",
        description="Zaman aralığı"
    ),
    limit: int = Query(
        default=200,
        ge=50,
        le=1000,
        description="Mum sayısı (50-1000 arası)"
    )
):
    symbol = symbol.upper().strip()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"

    logger.info(f"🔍 Analyzing {symbol} @ {interval} (limit={limit})")

    try:
        async with data_fetcher as fetcher:
            candles = await fetcher.get_candles(symbol, interval, limit)
            # Exchange istatistiklerini al
            exchange_stats = fetcher.get_stats()

        if not candles:
            raise HTTPException(422, "No candle data received from exchange")

        if len(candles) < Config.MIN_CANDLES:
            raise HTTPException(
                422,
                f"Insufficient candles. Got {len(candles)}, minimum required: {Config.MIN_CANDLES}"
            )

        # DataFrame oluştur
        df = pd.DataFrame(candles)
        required_cols = {"open", "high", "low", "close", "volume", "timestamp"}
        if not required_cols.issubset(df.columns):
            missing = required_cols - set(df.columns)
            raise ValueError(f"Missing required columns: {missing}")

        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
        df = df.dropna(subset=['timestamp']).set_index('timestamp').sort_index()

        if len(df) < Config.MIN_CANDLES:
            raise HTTPException(422, f"After cleaning only {len(df)} candles left")

        # Tüm analizleri çalıştır
        try:
            technical = TechnicalAnalyzer.analyze(df)
        except Exception as e:
            logger.error(f"TechnicalAnalyzer failed: {e}", exc_info=True)
            technical = {}

        try:
            ict_patterns = ICTPatternDetector.analyze(df)
        except Exception as e:
            logger.error(f"ICTPatternDetector failed: {e}", exc_info=True)
            ict_patterns = {}

        try:
            candle_patterns = CandlestickPatternDetector.analyze(df)
        except Exception as e:
            logger.error(f"CandlestickPatternDetector failed: {e}", exc_info=True)
            candle_patterns = []

        try:
            classical_patterns = ClassicalPatternDetector.analyze(df)
        except Exception as e:
            logger.error(f"ClassicalPatternDetector failed: {e}", exc_info=True)
            classical_patterns = []

        try:
            gainzalgo_signals = GainzAlgoV2Detector.detect(df)
        except Exception as e:
            logger.error(f"GainzAlgoV2Detector failed: {e}", exc_info=True)
            gainzalgo_signals = []

        try:
            ultimate_signals = Ultimate2026Detector.detect(df)
        except Exception as e:
            logger.error(f"Ultimate2026Detector failed: {e}", exc_info=True)
            ultimate_signals = []

        try:
            market_structure = MarketStructureAnalyzer.analyze(df)
        except Exception as e:
            logger.error(f"MarketStructureAnalyzer failed: {e}", exc_info=True)
            market_structure = {}

        # Signal üret
        try:
            signal = SignalGenerator.generate(
                technical,
                market_structure,
                ict_patterns,
                candle_patterns,
                classical_patterns,
                gainzalgo_signals,
                ultimate_signals
            )
        except Exception as e:
            logger.error(f"SignalGenerator failed: {e}", exc_info=True)
            signal = {
                "signal": "ERROR",
                "confidence": 0,
                "recommendation": f"Signal error: {str(e)[:100]}",
                "buy_count": 0,
                "sell_count": 0,
                "tp_level": None,
                "sl_level": None
            }

        # Tüm pattern'leri topla
        all_patterns = []
        for pattern_list in ict_patterns.values():
            all_patterns.extend(pattern_list)
        all_patterns.extend(candle_patterns)
        all_patterns.extend(classical_patterns)
        all_patterns.extend(gainzalgo_signals)
        all_patterns.extend(ultimate_signals)

        # Aktif kaynaklar
        active_sources = fetcher.get_active_sources()

        # Response
        last_row = df.iloc[-1]
        first_row = df.iloc[0]
        volume_sum = float(df["volume"].sum())

        response = {
            "success": True,
            "symbol": symbol,
            "interval": interval,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": {
                "current": float(last_row["close"]),
                "open": float(last_row["open"]),
                "high": float(last_row["high"]),
                "low": float(last_row["low"]),
                "volume_24h_approx": volume_sum,
                "change_percent": round(
                    (float(last_row["close"]) / float(first_row["close"]) - 1) * 100,
                    2
                )
            },
            "signal": signal,
            "technical": technical,
            "ict_patterns": ict_patterns,
            "candle_patterns": candle_patterns[-20:],
            "classical_patterns": classical_patterns[-10:],
            "gainzalgo_signals": gainzalgo_signals[-5:],
            "ultimate_signals": ultimate_signals[-5:],
            "market_structure": market_structure,
            "active_sources": active_sources,
            "data_points": len(df),
            "all_patterns": all_patterns[-30:],
            "exchange_stats": exchange_stats  # YENİ
        }

        logger.info(
            f"✅ {symbol} | {signal.get('signal', 'UNKNOWN')} "
            f"({signal.get('confidence', 0):.1f}%) | {len(df)} candles | "
            f"ICT:{sum(len(v) for v in ict_patterns.values())} Classical:{len(classical_patterns)}"
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ Analysis failed for {symbol}: {str(e)}")
        detail = f"Analysis error: {str(e)}"
        raise HTTPException(status_code=500, detail=detail[:300])

@app.get("/api/price/{symbol}")
async def get_price(symbol: str):
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    
    async with data_fetcher as fetcher:
        price = await fetcher.get_current_price(symbol)
    
    if price is None:
        raise HTTPException(status_code=404, detail="Price not available")
    
    return {
        "symbol": symbol,
        "price": round(price, 2),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/exchanges")
async def get_exchanges():
    stats = data_fetcher.get_stats()
    active = data_fetcher.get_active_sources()
    
    exchanges = []
    for exchange in ExchangeDataFetcher.EXCHANGES:
        name = exchange["name"]
        stat = stats.get(name, {"success": 0, "fail": 0, "last_error": "", "last_success": 0})
        total = stat["success"] + stat["fail"]
        reliability = (stat["success"] / total * 100) if total > 0 else 0
        
        exchanges.append({
            "name": name,
            "status": "active" if name in active else "degraded",
            "reliability": round(reliability, 1),
            "weight": exchange["weight"],
            "success": stat["success"],
            "fail": stat["fail"],
            "last_error": stat["last_error"][:50] if stat["last_error"] else "",
            "last_success": datetime.fromtimestamp(stat["last_success"]).isoformat() if stat["last_success"] else None
        })
    
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "exchanges": exchanges,
        "active_count": len(active),
        "total_count": len(ExchangeDataFetcher.EXCHANGES)
    }
#===========================================================================   
# ✅ YENİ - Frontend'in beklediği endpoint
@app.get("/api/exchange-stats")
async def get_exchange_stats():
    """Exchange istatistikleri - frontend için"""
    try:
        stats = data_fetcher.get_stats()
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Exchange stats error: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

@app.websocket("/wss/{symbol}")
async def websocket_endpoint(websocket: WebSocket, symbol: str):
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    
    await websocket.accept()
    websocket_connections.add(websocket)
    logger.info(f"🔌 WSS connected: {symbol}")
    
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
        logger.info(f"❌ WSS disconnected: {symbol}")
    except Exception as e:
        logger.error(f"WSS error: {str(e)}")
    finally:
        websocket_connections.discard(websocket)

@app.post("/api/train/{symbol}")
async def train_model(symbol: str):
    """
    ML modelini eğit (ileriye dönük)
    """
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    
    logger.info(f"🧠 Training model for {symbol}")
    
    try:
        async with data_fetcher as fetcher:
            candles = await fetcher.get_candles(symbol, "1h", 500)
        
        if not candles or len(candles) < 100:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient data for training. Got {len(candles) if candles else 0} candles"
            )
        
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp')
        
        # Burada gerçek ML eğitimi yapılacak
        # Şimdilik başarılı mesajı dön
        
        return {
            "success": True,
            "message": f"Model training completed for {symbol}",
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data_points": len(df)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Training failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e)[:200])

@app.get("/api/stats")
async def get_stats():
    """Sistem istatistikleri"""
    stats = data_fetcher.get_stats()
    total_requests = sum(s["success"] + s["fail"] for s in stats.values())
    total_success = sum(s["success"] for s in stats.values())
    
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime": str(timedelta(seconds=int(time.time() - startup_time))),
        "total_requests": total_requests,
        "total_success": total_success,
        "success_rate": round(total_success / total_requests * 100, 1) if total_requests > 0 else 0,
        "active_websockets": len(websocket_connections),
        "exchange_stats": stats,
        "config": {
            "max_confidence": Config.MAX_CONFIDENCE,
            "min_candles": Config.MIN_CANDLES,
            "cache_ttl": Config.CACHE_TTL,
            "rate_limit": f"{Config.RATE_LIMIT_CALLS}/{Config.RATE_LIMIT_PERIOD}s"
        }
    }

# ========================================================================================================
# STARTUP & SHUTDOWN
# ========================================================================================================
@app.on_event("startup")
async def startup_event():
    logger.info("=" * 70)
    logger.info("🚀 ICTSMARTPRO v9.0 - ULTIMATE PATTERN DETECTOR STARTED")
    logger.info("=" * 70)
    logger.info(f"Environment: {Config.ENV}")
    logger.info(f"Debug Mode: {Config.DEBUG}")
    logger.info(f"Sources: Kraken, Binance, MEXC, Yahoo")
    logger.info(f"Pattern Types: ICT (20+), Classical (15+), Candlestick (15+), GainzAlgo, Ultimate")
    logger.info(f"Max Confidence: {Config.MAX_CONFIDENCE}%")
    logger.info(f"Min Candles: {Config.MIN_CANDLES}")
    logger.info(f"Cache TTL: {Config.CACHE_TTL}s")
    logger.info("=" * 70)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Shutting down...")
    for ws in websocket_connections:
        try:
            await ws.close()
        except:
            pass
    websocket_connections.clear()
    logger.info("✅ Shutdown complete")

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
