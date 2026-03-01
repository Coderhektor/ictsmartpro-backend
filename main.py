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

    MIN_CANDLES = int(os.getenv("MIN_CANDLES", "50"))  # 30 -> 50'ye çıkar
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
    BULLISH_REVERSAL = "bullish_reversal"
    BEARISH_REVERSAL = "bearish_reversal"


class PatternType(str, Enum):
    ICT = "ict"
    ICTSMARTPRO = "ictsmartpro"  # Yeni!
    CLASSICAL = "classical"
    PRICE_ACTION = "price_action"
    SUPPORT_RESISTANCE = "support_resistance"
    TREND = "trend"


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
    ictsmartpro_signals: List[Dict[str, Any]]  # GainzAlgo kalktı, ICTSMARTPRO geldi
    market_structure: Dict[str, Any]
    active_sources: List[str]
    data_points: int
    all_patterns: List[Pattern]
    exchange_stats: Optional[Dict] = None


# ========================================================================================================
# EXCHANGE DATA FETCHER (DÜZELTİLMİŞ)
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

    def _get_interval_ms(self, interval: str) -> int:
        """Interval'i milisaniyeye çevir"""
        multipliers = {
            "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800
        }
        return multipliers.get(interval, 3600) * 1000

    def _round_timestamp(self, ts_ms: int, interval_ms: int) -> int:
        """Timestamp'i interval'a yuvarla (floor)"""
        return (ts_ms // interval_ms) * interval_ms

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

                logger.debug(f"✅ {name}: {len(candles)} candles")
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
                            # Yahoo'da None değerler olabiliyor, fallback ekle
                            open_val = opens[i] if i < len(opens) and opens[i] is not None else closes[i]
                            high_val = highs[i] if i < len(highs) and highs[i] is not None else closes[i]
                            low_val = lows[i] if i < len(lows) and lows[i] is not None else closes[i]
                            volume_val = volumes[i] if i < len(volumes) and volumes[i] is not None else 0
                            
                            candles.append({
                                "timestamp": int(timestamps[i]) * 1000,
                                "open": float(open_val),
                                "high": float(high_val),
                                "low": float(low_val),
                                "close": float(closes[i]),
                                "volume": float(volume_val),
                                "exchange": exchange
                            })

            candles.sort(key=lambda x: x["timestamp"])
            return candles

        except Exception as e:
            logger.debug(f"Parse error for {exchange}: {str(e)}")
            return []

    def _aggregate_candles(self, all_candles: List[List[Dict]], interval: str) -> List[Dict]:
        """Mum verilerini birleştir - timestamp hizalamalı"""
        if not all_candles:
            return []
        
        interval_ms = self._get_interval_ms(interval)
        timestamp_map = defaultdict(list)
        
        for exchange_data in all_candles:
            for candle in exchange_data:
                # Timestamp'i interval'a yuvarla
                rounded_ts = self._round_timestamp(candle["timestamp"], interval_ms)
                candle["rounded_timestamp"] = rounded_ts
                timestamp_map[rounded_ts].append(candle)
        
        logger.info(f"⏰ Timestamp yuvarlama: {len(timestamp_map)} farklı zaman dilimi")
        
        aggregated = []
        for timestamp in sorted(timestamp_map.keys()):
            candles = timestamp_map[timestamp]
            
            # Ağırlıklı ortalama hesapla
            total_weight = 0
            open_sum = high_sum = low_sum = close_sum = volume_sum = 0
            sources = []
            
            valid_candles = 0
            for candle in candles:
                # NaN kontrolü
                if any(pd.isna(v) for v in [candle["open"], candle["high"], candle["low"], candle["close"], candle["volume"]]):
                    continue
                    
                exchange_config = next((e for e in self.EXCHANGES if e["name"] == candle["exchange"]), None)
                weight = exchange_config["weight"] if exchange_config else 0.5
                
                total_weight += weight
                open_sum += candle["open"] * weight
                high_sum += candle["high"] * weight
                low_sum += candle["low"] * weight
                close_sum += candle["close"] * weight
                volume_sum += candle["volume"] * weight
                sources.append(candle["exchange"])
                valid_candles += 1
            
            if total_weight > 0 and valid_candles >= 1:
                aggregated.append({
                    "timestamp": timestamp,
                    "open": open_sum / total_weight,
                    "high": high_sum / total_weight,
                    "low": low_sum / total_weight,
                    "close": close_sum / total_weight,
                    "volume": volume_sum / total_weight,
                    "source_count": valid_candles,
                    "sources": sources,
                    "exchange": "aggregated"
                })
        
        # DataFrame'e çevir ve NaN'ları temizle
        if not aggregated:
            return []
        
        df = pd.DataFrame(aggregated).sort_values("timestamp")
        cols = ['open', 'high', 'low', 'close', 'volume']
        df[cols] = df[cols].ffill().bfill()  # İleri ve geri doldur
        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        
        logger.info(f"📊 Aggregation sonrası: {len(df)} mum (kaynak: {len(all_candles)} borsa)")
        
        return df.to_dict('records')

    async def get_candles(self, symbol: str, interval: str = "1h", limit: int = 200) -> List[Dict]:
        cache_key = self._get_cache_key(symbol, interval)

        # Cache kontrolü
        if self._is_cache_valid(cache_key):
            cached = self.cache.get(cache_key, [])
            if cached and len(cached) >= Config.MIN_CANDLES:
                logger.info(f"📦 CACHE: {symbol} ({interval}) - {len(cached)} candles")
                return cached[-limit:]
            else:
                logger.warning(f"⚠️ Cache geçersiz: {len(cached) if cached else 0} mum (min:{Config.MIN_CANDLES})")

        logger.info(f"🔄 FETCH: {symbol} ({interval}) from {len(self.EXCHANGES)} sources...")

        tasks = [
            self._fetch_exchange(exchange, symbol, interval, limit * 2)
            for exchange in self.EXCHANGES
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results = []
        source_stats = {}
        
        for i, r in enumerate(results):
            exchange_name = self.EXCHANGES[i]["name"]
            if isinstance(r, list) and len(r) >= 10:
                valid_results.append(r)
                source_stats[exchange_name] = len(r)
            elif isinstance(r, Exception):
                logger.debug(f"❌ {exchange_name} hata: {str(r)[:50]}")
            else:
                logger.debug(f"⚠️ {exchange_name} yetersiz veri: {len(r) if r else 0}")

        logger.info(f"✅ RECEIVED: {len(valid_results)}/{len(self.EXCHANGES)} sources")
        logger.debug(f"📊 Source stats: {source_stats}")

        if len(valid_results) < Config.MIN_EXCHANGES:
            logger.warning(f"⚠️ Only {len(valid_results)} sources, using available...")
            if not valid_results:
                return []

        aggregated = self._aggregate_candles(valid_results, interval)

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
# ORTAK DATAFRAME HAZIRLAMA FONKSİYONU (DRY)
# ========================================================================================================
def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Tüm indikatörleri tek yerde hesapla - DRY prensibi"""
    df = df.copy()
    
    # Temel mum özellikleri
    df['is_bullish'] = df['close'] > df['open']
    df['is_bearish'] = df['close'] < df['open']
    df['body'] = abs(df['close'] - df['open'])
    df['range'] = df['high'] - df['low']
    df['upper_shadow'] = df['high'] - df[['close', 'open']].max(axis=1)
    df['lower_shadow'] = df[['close', 'open']].min(axis=1) - df['low']
    df['body_percent'] = df['body'] / df['range'].replace(0, 1)
    
    # RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    df['rsi'] = df['rsi'].fillna(50)
    
    # EMA'lar
    df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # ATR
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift(1)).abs()
    tr3 = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()
    df['atr'] = df['atr'].fillna(df['range'].rolling(14).mean())
    
    # Volume
    df['volume_sma'] = df['volume'].rolling(window=20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_sma'].replace(0, 1)
    df['volume_ratio'] = df['volume_ratio'].fillna(1.0)
    
    # Bollinger Bands
    df['bb_middle'] = df['close'].rolling(window=20).mean()
    df['bb_std'] = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * 2)
    df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * 2)
    bb_range = (df['bb_upper'] - df['bb_lower']).replace(0, 1)
    df['bb_position'] = ((df['close'] - df['bb_lower']) / bb_range * 100).clip(0, 100)
    
    # Momentum
    df['mom_5'] = df['close'].pct_change(5) * 100
    df['mom_10'] = df['close'].pct_change(10) * 100
    
    # NaN'ları agresif temizle
    df = df.ffill().bfill()
    df = df.fillna({
        'rsi': 50,
        'volume_ratio': 1.0,
        'mom_5': 0,
        'mom_10': 0,
        'bb_position': 50
    })
    
    return df


# ========================================================================================================
# GELİŞMİŞ MARKET STRUCTURE ANALYZER (HH/HL/LH/LL + S/R ZONES)
# ========================================================================================================
class MarketStructureAnalyzer:
    """Gelişmiş piyasa yapısı analizörü - HH/HL/LH/LL doğru hesaplama + destek/direnç bölgeleri"""
    
    @staticmethod
    def find_swing_points(high: pd.Series, low: pd.Series, window: int = 5) -> Dict:
        """Swing high/low'ları bul (HH/HL/LH/LL için)"""
        swings = {
            'swing_highs': [],
            'swing_lows': [],
            'hh': [],  # Higher Highs
            'hl': [],  # Higher Lows
            'lh': [],  # Lower Highs
            'll': []   # Lower Lows
        }
        
        n = len(high)
        
        # Swing High'ları bul (merkezî pencere ile)
        for i in range(window, n - window):
            if high.iloc[i] == high.iloc[i-window:i+window+1].max():
                if not pd.isna(high.iloc[i]):
                    swings['swing_highs'].append((i, high.iloc[i]))
        
        # Swing Low'ları bul
        for i in range(window, n - window):
            if low.iloc[i] == low.iloc[i-window:i+window+1].min():
                if not pd.isna(low.iloc[i]):
                    swings['swing_lows'].append((i, low.iloc[i]))
        
        # HH/HL/LH/LL sınıflandırması (bir öncekine göre karşılaştır)
        for idx, (i, val) in enumerate(swings['swing_highs']):
            if idx > 0:
                prev_idx, prev_val = swings['swing_highs'][idx-1]
                if val > prev_val * 1.001:  # %0.1'den fazla artış
                    swings['hh'].append((i, val, "HH"))
                elif val < prev_val * 0.999:  # %0.1'den fazla düşüş
                    swings['lh'].append((i, val, "LH"))
        
        for idx, (i, val) in enumerate(swings['swing_lows']):
            if idx > 0:
                prev_idx, prev_val = swings['swing_lows'][idx-1]
                if val > prev_val * 1.001:
                    swings['hl'].append((i, val, "HL"))
                elif val < prev_val * 0.999:
                    swings['ll'].append((i, val, "LL"))
        
        logger.debug(f"📈 Swing points: HH:{len(swings['hh'])}, HL:{len(swings['hl'])}, LH:{len(swings['lh'])}, LL:{len(swings['ll'])}")
        
        return swings
    
    @staticmethod
    def find_support_resistance_zones(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20, tolerance: float = 0.01) -> List[Dict]:
        """Destek/direnç aralıklarını bul (net çizgi değil, bölge olarak)"""
        zones = []
        n = len(high)
        
        if n < window * 2:
            return zones
        
        # Son 50 periyottaki önemli seviyeler
        lookback = min(50, n)
        
        for i in range(window, n - window):
            zone_high = high.iloc[i-window:i+window].max()
            zone_low = low.iloc[i-window:i+window].min()
            zone_center = (zone_high + zone_low) / 2
            
            # ATR'ye göre bölge kalınlığı
            atr_value = (high - low).rolling(14).mean().iloc[min(i, n-1)]
            if pd.isna(atr_value):
                atr_value = (high.iloc[i] - low.iloc[i]) * 0.5
            
            zone_thickness = atr_value * 0.3  # Biraz daha dar
            
            # Fiyat bu bölgeye kaç kez temas etmiş?
            touches = 0
            start_idx = max(0, i - lookback)
            end_idx = min(n, i + lookback)
            
            for j in range(start_idx, end_idx):
                if abs(high.iloc[j] - zone_center) < zone_thickness:
                    touches += 1
            
            # Güç hesapla (temas sayısına göre)
            strength = min(touches * 5, 70)  # Max 70
            
            if touches >= 3 and strength >= 15:  # En az 3 temas
                zone_type = "resistance" if zone_center > close.iloc[i] else "support"
                
                zones.append({
                    "level": round(zone_center, 2),
                    "zone_low": round(zone_center - zone_thickness, 2),
                    "zone_high": round(zone_center + zone_thickness, 2),
                    "type": zone_type,
                    "strength": strength,
                    "touches": touches,
                    "timestamp": str(close.index[i]) if hasattr(close.index[i], 'strftime') else str(i)
                })
        
        # Birleştir yakın bölgeleri
        merged_zones = []
        zones.sort(key=lambda x: x['level'])
        
        for zone in zones:
            if not merged_zones:
                merged_zones.append(zone)
            else:
                last = merged_zones[-1]
                # Bölgeler örtüşüyorsa birleştir
                if abs(zone['level'] - last['level']) < (last['zone_high'] - last['zone_low']):
                    last['zone_low'] = min(last['zone_low'], zone['zone_low'])
                    last['zone_high'] = max(last['zone_high'], zone['zone_high'])
                    last['level'] = (last['zone_low'] + last['zone_high']) / 2
                    last['strength'] = max(last['strength'], zone['strength'])
                    last['touches'] += zone['touches']
                else:
                    merged_zones.append(zone)
        
        logger.debug(f"🎯 Support/Resistance zones: {len(merged_zones)}")
        
        return merged_zones[-10:]  # Son 10 bölge
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> Dict[str, Any]:
        if len(df) < 50:
            return {
                "trend": "NEUTRAL",
                "trend_strength": "WEAK",
                "structure": "Neutral",
                "swings": {"hh": [], "hl": [], "lh": [], "ll": []},
                "support_resistance": [],
                "volatility": "NORMAL",
                "volatility_index": 100,
                "momentum": "Neutral"
            }
        
        close = df['close']
        high = df['high']
        low = df['low']
        
        # Swing noktalarını bul
        swings = MarketStructureAnalyzer.find_swing_points(high, low)
        
        # Destek/direnç bölgelerini bul
        sr_zones = MarketStructureAnalyzer.find_support_resistance_zones(high, low, close)
        
        # Trend belirleme (HH/HL bazlı)
        last_20_idx = len(df) - 20
        
        recent_hh = [h for h in swings['hh'] if h[0] > last_20_idx]
        recent_hl = [h for h in swings['hl'] if h[0] > last_20_idx]
        recent_lh = [h for h in swings['lh'] if h[0] > last_20_idx]
        recent_ll = [h for h in swings['ll'] if h[0] > last_20_idx]
        
        if len(recent_hh) >= 2 and len(recent_hl) >= 2:
            trend = "STRONG_UPTREND"
            trend_strength = "STRONG"
            structure = "Bullish"
        elif len(recent_hh) >= 1 and len(recent_hl) >= 1:
            trend = "UPTREND"
            trend_strength = "MODERATE"
            structure = "Bullish"
        elif len(recent_ll) >= 2 and len(recent_lh) >= 2:
            trend = "STRONG_DOWNTREND"
            trend_strength = "STRONG"
            structure = "Bearish"
        elif len(recent_ll) >= 1 and len(recent_lh) >= 1:
            trend = "DOWNTREND"
            trend_strength = "MODERATE"
            structure = "Bearish"
        else:
            trend = "NEUTRAL"
            trend_strength = "WEAK"
            structure = "Neutral"
        
        # Volatilite hesapla (ATR bazlı)
        atr = df['atr'] if 'atr' in df.columns else (high - low).rolling(14).mean()
        current_atr = atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else (high.iloc[-1] - low.iloc[-1])
        avg_atr = atr.rolling(50).mean().iloc[-1] if len(atr) >= 50 else current_atr
        
        if pd.isna(avg_atr) or avg_atr == 0:
            avg_atr = current_atr
        
        if current_atr > avg_atr * 1.5:
            vol_regime = "HIGH"
            vol_index = 150
        elif current_atr < avg_atr * 0.7:
            vol_regime = "LOW"
            vol_index = 70
        else:
            vol_regime = "NORMAL"
            vol_index = 100
        
        # Momentum
        mom_5 = (close.iloc[-1] / close.iloc[-5] - 1) if len(close) >= 5 else 0
        mom_10 = (close.iloc[-1] / close.iloc[-10] - 1) if len(close) >= 10 else 0
        
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
        
        # Son HH/HL/LH/LL'leri formatla
        last_swings = {
            "hh": [{"index": s[0], "price": s[1], "type": s[2]} for s in swings['hh'][-5:]],
            "hl": [{"index": s[0], "price": s[1], "type": s[2]} for s in swings['hl'][-5:]],
            "lh": [{"index": s[0], "price": s[1], "type": s[2]} for s in swings['lh'][-5:]],
            "ll": [{"index": s[0], "price": s[1], "type": s[2]} for s in swings['ll'][-5:]]
        }
        
        result = {
            "trend": trend,
            "trend_strength": trend_strength,
            "structure": structure,
            "swings": last_swings,
            "support_resistance": sr_zones[-5:],
            "volatility": vol_regime,
            "volatility_index": vol_index,
            "momentum": momentum,
            "current_price": float(close.iloc[-1])
        }
        
        logger.info(f"📊 Market Structure: {trend} ({trend_strength}) | Vol:{vol_regime} | Mom:{momentum}")
        
        return result


# ========================================================================================================
# ICT PATTERN DETECTOR (GENİŞLETİLMİŞ)
# ========================================================================================================
class ICTPatternDetector:
    """ICT Pattern dedektörü - FVG, Order Blocks, Breaker, MSS, CHoCH, OTE, etc."""
    
    @staticmethod
    def detect_fair_value_gap(df: pd.DataFrame) -> List[Dict]:
        fvgs = []
        if len(df) < 3:
            return fvgs
        
        n = len(df)
        for i in range(1, n - 1):
            # Bullish FVG
            if df['low'].iloc[i + 1] > df['high'].iloc[i - 1]:
                gap_size = df['low'].iloc[i + 1] - df['high'].iloc[i - 1]
                gap_percent = (gap_size / df['high'].iloc[i - 1]) * 100 if df['high'].iloc[i - 1] > 0 else 0
                
                if gap_percent > 0.1:
                    fvgs.append({
                        "pattern": "bullish_fvg",
                        "type": "ict",
                        "direction": "bullish",
                        "strength": min(round(gap_percent * 5, 1), 80),
                        "timestamp": str(df.index[i]),
                        "price": float(df['close'].iloc[i]),
                        "gap_low": float(df['high'].iloc[i - 1]),
                        "gap_high": float(df['low'].iloc[i + 1]),
                        "gap_percent": round(gap_percent, 2),
                        "description": f"Bullish Fair Value Gap at {gap_percent:.2f}%"
                    })
            
            # Bearish FVG
            elif df['high'].iloc[i + 1] < df['low'].iloc[i - 1]:
                gap_size = df['low'].iloc[i - 1] - df['high'].iloc[i + 1]
                gap_percent = (gap_size / df['low'].iloc[i - 1]) * 100 if df['low'].iloc[i - 1] > 0 else 0
                
                if gap_percent > 0.1:
                    fvgs.append({
                        "pattern": "bearish_fvg",
                        "type": "ict",
                        "direction": "bearish",
                        "strength": min(round(gap_percent * 5, 1), 80),
                        "timestamp": str(df.index[i]),
                        "price": float(df['close'].iloc[i]),
                        "gap_low": float(df['high'].iloc[i + 1]),
                        "gap_high": float(df['low'].iloc[i - 1]),
                        "gap_percent": round(gap_percent, 2),
                        "description": f"Bearish Fair Value Gap at {gap_percent:.2f}%"
                    })
        
        return fvgs[-10:]
    
    @staticmethod
    def detect_order_blocks(df: pd.DataFrame) -> List[Dict]:
        obs = []
        if len(df) < 5:
            return obs
        
        n = len(df)
        for i in range(2, n - 2):
            # Bullish Order Block
            if (df['is_bullish'].iloc[i] and
                df['is_bearish'].iloc[i - 1] and
                df['low'].iloc[i] < df['low'].iloc[i - 1] and
                df['close'].iloc[i] > df['high'].iloc[i - 1]):
                
                ob_range = abs(df['high'].iloc[i - 1] - df['low'].iloc[i - 1])
                ob_percent = (ob_range / df['close'].iloc[i - 1]) * 100 if df['close'].iloc[i - 1] > 0 else 0
                
                obs.append({
                    "pattern": "bullish_order_block",
                    "type": "ict",
                    "direction": "bullish",
                    "strength": min(round(ob_percent * 10, 1), 75),
                    "timestamp": str(df.index[i - 1]),
                    "price": float(df['close'].iloc[i]),
                    "block_low": float(df['low'].iloc[i - 1]),
                    "block_high": float(df['high'].iloc[i - 1]),
                    "description": "Bullish Order Block - Smart money buying zone"
                })
            
            # Bearish Order Block
            elif (df['is_bearish'].iloc[i] and
                  df['is_bullish'].iloc[i - 1] and
                  df['high'].iloc[i] > df['high'].iloc[i - 1] and
                  df['close'].iloc[i] < df['low'].iloc[i - 1]):
                
                ob_range = abs(df['high'].iloc[i - 1] - df['low'].iloc[i - 1])
                ob_percent = (ob_range / df['close'].iloc[i - 1]) * 100 if df['close'].iloc[i - 1] > 0 else 0
                
                obs.append({
                    "pattern": "bearish_order_block",
                    "type": "ict",
                    "direction": "bearish",
                    "strength": min(round(ob_percent * 10, 1), 75),
                    "timestamp": str(df.index[i - 1]),
                    "price": float(df['close'].iloc[i]),
                    "block_low": float(df['low'].iloc[i - 1]),
                    "block_high": float(df['high'].iloc[i - 1]),
                    "description": "Bearish Order Block - Smart money selling zone"
                })
        
        return obs[-10:]
    
    @staticmethod
    def detect_breaker_blocks(df: pd.DataFrame) -> List[Dict]:
        breakers = []
        if len(df) < 15:
            return breakers
        
        n = len(df)
        for i in range(10, n - 1):
            recent_high = df['high'].iloc[i - 10:i].max()
            recent_low = df['low'].iloc[i - 10:i].min()
            
            # Bullish Breaker (eski direnç -> destek)
            if (df['close'].iloc[i] > recent_high and
                df['close'].iloc[i - 1] < recent_high):
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
                  df['close'].iloc[i - 1] > recent_low):
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
        
        n = len(df)
        for i in range(20, n):
            swing_highs = df['high'].iloc[i - 20:i - 5].nlargest(3)
            swing_lows = df['low'].iloc[i - 20:i - 5].nsmallest(3)
            
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
        
        n = len(df)
        for i in range(10, n):
            recent_high = df['high'].iloc[i - 10:i].max()
            recent_low = df['low'].iloc[i - 10:i].min()
            
            # Bullish BOS
            if df['high'].iloc[i] > recent_high * 1.005:
                bos_size = (df['high'].iloc[i] - recent_high) / recent_high * 100 if recent_high > 0 else 0
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
                bos_size = (recent_low - df['low'].iloc[i]) / recent_low * 100 if recent_low > 0 else 0
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
        
        n = len(df)
        for i in range(15, n):
            recent_trend = df['close'].iloc[i - 10:i].pct_change().mean()
            
            # Bullish CHoCH (downtrend -> uptrend)
            if recent_trend < -0.001 and df['close'].iloc[i] > df['high'].iloc[i - 1]:
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
            elif recent_trend > 0.001 and df['close'].iloc[i] < df['low'].iloc[i - 1]:
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
        
        n = len(df)
        for i in range(10, n - 2):
            # Bullish MSS (higher high + higher low)
            if (df['high'].iloc[i] > df['high'].iloc[i - 1] and
                df['low'].iloc[i] > df['low'].iloc[i - 1] and
                df['high'].iloc[i - 2] < df['high'].iloc[i - 1]):
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
            if (df['low'].iloc[i] < df['low'].iloc[i - 1] and
                df['high'].iloc[i] < df['high'].iloc[i - 1] and
                df['low'].iloc[i - 2] > df['low'].iloc[i - 1]):
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
        
        n = len(df)
        for i in range(25, n):
            # Son swing high/low'ları bul
            window_data = df.iloc[i - 20:i]
            if len(window_data) == 0:
                continue
                
            high_idx = window_data['high'].idxmax()
            low_idx = window_data['low'].idxmin()
            
            if isinstance(high_idx, pd.Timestamp) and isinstance(low_idx, pd.Timestamp):
                high_pos = window_data.index.get_loc(high_idx)
                low_pos = window_data.index.get_loc(low_idx)
                
                if high_pos < low_pos:  # Önce high, sonra low -> düşüş trendi
                    swing_high = window_data.loc[high_idx, 'high']
                    swing_low = window_data.loc[low_idx, 'low']
                    
                    if swing_high > swing_low:
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
                
                elif low_pos < high_pos:  # Önce low, sonra high -> yükseliş trendi
                    swing_low = window_data.loc[low_idx, 'low']
                    swing_high = window_data.loc[high_idx, 'high']
                    
                    if swing_high > swing_low:
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
        
        n = len(df)
        for i in range(25, n):
            period_high = df['high'].iloc[i - 20:i].max()
            period_low = df['low'].iloc[i - 20:i].min()
            
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
        
        n = len(df)
        for i in range(20, n):
            avg_volume = df['volume'].iloc[i - 20:i].mean()
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
    def analyze(df: pd.DataFrame) -> Dict[str, List[Dict]]:
        """Tüm ICT pattern'lerini analiz et"""
        
        return {
            "fair_value_gaps": ICTPatternDetector.detect_fair_value_gap(df),
            "order_blocks": ICTPatternDetector.detect_order_blocks(df),
            "breaker_blocks": ICTPatternDetector.detect_breaker_blocks(df),
            "liquidity_sweeps": ICTPatternDetector.detect_liquidity_sweeps(df),
            "break_of_structure": ICTPatternDetector.detect_break_of_structure(df),
            "change_of_character": ICTPatternDetector.detect_change_of_character(df),
            "market_structure_shift": ICTPatternDetector.detect_market_structure_shift(df),
            "optimal_trade_entry": ICTPatternDetector.detect_optimal_trade_entry(df),
            "turtle_soup": ICTPatternDetector.detect_turtle_soup(df),
            "displacement": ICTPatternDetector.detect_displacement(df)
        }


# ========================================================================================================
# ICTSMARTPRO STRATEJİSİ (GainzAlgo ve Ultimate KALDIRILDI)
# ========================================================================================================
class ICTSmartProDetector:
    """ICTSMARTPRO Ana Strateji - HH/HL/LH/LL + S/R Bölgeleri + FVG + Order Blocks"""
    
    @staticmethod
    def detect(df: pd.DataFrame, market_structure: Dict) -> List[Dict]:
        signals = []
        
        if len(df) < 50:
            return signals
        
        # Swing noktalarını al
        swings = market_structure.get('swings', {})
        sr_zones = market_structure.get('support_resistance', [])
        
        recent_hh = swings.get('hh', [])
        recent_hl = swings.get('hl', [])
        recent_lh = swings.get('lh', [])
        recent_ll = swings.get('ll', [])
        
        current_price = df['close'].iloc[-1]
        current_idx = len(df) - 1
        
        # === YÜKSELİŞ SİNYALİ: HH + HL ===
        if len(recent_hh) >= 1 and len(recent_hl) >= 1:
            last_hh = recent_hh[-1]
            last_hl = recent_hl[-1]
            
            # Son 10 mum içinde mi?
            if last_hh['index'] > len(df) - 15 or last_hl['index'] > len(df) - 15:
                
                # TP: Son HH'in biraz üstü
                tp_level = last_hh['price'] * 1.02
                
                # SL: Son HL'in biraz altı
                sl_level = last_hl['price'] * 0.98
                
                # Güç hesapla
                strength = 70
                if len(recent_hh) >= 2 and len(recent_hl) >= 2:
                    strength = 85
                
                signals.append({
                    "pattern": "ictsmartpro_hh_hl_buy",
                    "type": "ictsmartpro",
                    "direction": "bullish",
                    "strength": strength,
                    "timestamp": str(df.index[-1]),
                    "price": float(current_price),
                    "sl_level": float(sl_level),
                    "tp_level": float(tp_level),
                    "description": f"ICTSMARTPRO BUY - HH/HL Structure (HH:{last_hh['price']:.2f}, HL:{last_hl['price']:.2f})"
                })
        
        # === DÜŞÜŞ SİNYALİ: LL + LH ===
        if len(recent_ll) >= 1 and len(recent_lh) >= 1:
            last_ll = recent_ll[-1]
            last_lh = recent_lh[-1]
            
            if last_ll['index'] > len(df) - 15 or last_lh['index'] > len(df) - 15:
                
                # TP: Son LL'in biraz altı
                tp_level = last_ll['price'] * 0.98
                
                # SL: Son LH'in biraz üstü
                sl_level = last_lh['price'] * 1.02
                
                strength = 70
                if len(recent_ll) >= 2 and len(recent_lh) >= 2:
                    strength = 85
                
                signals.append({
                    "pattern": "ictsmartpro_ll_lh_sell",
                    "type": "ictsmartpro",
                    "direction": "bearish",
                    "strength": strength,
                    "timestamp": str(df.index[-1]),
                    "price": float(current_price),
                    "sl_level": float(sl_level),
                    "tp_level": float(tp_level),
                    "description": f"ICTSMARTPRO SELL - LL/LH Structure (LL:{last_ll['price']:.2f}, LH:{last_lh['price']:.2f})"
                })
        
        # === DESTEK BÖLGESİNDEN DÖNÜŞ ===
        for zone in sr_zones:
            if zone['type'] == 'support' and zone['zone_low'] <= current_price <= zone['zone_high']:
                if df['is_bullish'].iloc[-1]:  # Bullish mum
                    signals.append({
                        "pattern": "ictsmartpro_support_bounce",
                        "type": "ictsmartpro",
                        "direction": "bullish",
                        "strength": zone['strength'],
                        "timestamp": str(df.index[-1]),
                        "price": float(current_price),
                        "sl_level": float(zone['zone_low'] * 0.99),
                        "tp_level": float(zone['zone_high'] * 1.05),
                        "description": f"ICTSMARTPRO BUY - Support Bounce (Strength:{zone['strength']}%)"
                    })
            
            # === DİRENÇ BÖLGESİNDEN DÖNÜŞ ===
            elif zone['type'] == 'resistance' and zone['zone_low'] <= current_price <= zone['zone_high']:
                if df['is_bearish'].iloc[-1]:  # Bearish mum
                    signals.append({
                        "pattern": "ictsmartpro_resistance_reject",
                        "type": "ictsmartpro",
                        "direction": "bearish",
                        "strength": zone['strength'],
                        "timestamp": str(df.index[-1]),
                        "price": float(current_price),
                        "sl_level": float(zone['zone_high'] * 1.01),
                        "tp_level": float(zone['zone_low'] * 0.95),
                        "description": f"ICTSMARTPRO SELL - Resistance Rejection (Strength:{zone['strength']}%)"
                    })
        
        logger.info(f"🎯 ICTSMARTPRO: {len(signals)} sinyal üretildi")
        
        return signals[-5:]  # Son 5 sinyal


# ========================================================================================================
# CLASSICAL PATTERN DETECTOR
# ========================================================================================================
class ClassicalPatternDetector:

    @staticmethod
    def detect_double_top_bottom(df: pd.DataFrame) -> List[Dict]:
        patterns = []
        if len(df) < 30:
            return patterns
        
        n = len(df)
        for i in range(20, n):
            # Double Top
            high1 = df['high'].iloc[i - 15:i - 5].max()
            high2 = df['high'].iloc[i - 5:i].max()
            
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
            low1 = df['low'].iloc[i - 15:i - 5].min()
            low2 = df['low'].iloc[i - 5:i].min()
            
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
        
        n = len(df)
        for i in range(30, n):
            # Head and Shoulders (Top)
            left_shoulder = df['high'].iloc[i - 25:i - 15].max()
            head = df['high'].iloc[i - 15:i - 5].max()
            right_shoulder = df['high'].iloc[i - 5:i].max()
            
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
            left_shoulder = df['low'].iloc[i - 25:i - 15].min()
            head = df['low'].iloc[i - 15:i - 5].min()
            right_shoulder = df['low'].iloc[i - 5:i].min()
            
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
        
        n = len(df)
        for i in range(30, n):
            first_bottom = df['low'].iloc[i - 25:i - 15].min()
            peak = df['high'].iloc[i - 15:i - 8].max()
            second_bottom = df['low'].iloc[i - 8:i - 2].min()
            
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
        
        n = len(df)
        for i in range(30, n):
            first_top = df['high'].iloc[i - 25:i - 15].max()
            bottom = df['low'].iloc[i - 15:i - 8].min()
            second_top = df['high'].iloc[i - 8:i - 2].max()
            
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
        
        n = len(df)
        for i in range(25, n):
            highs = df['high'].iloc[i - 20:i].values
            lows = df['low'].iloc[i - 20:i].values
            
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
        
        n = len(df)
        for i in range(45, n):
            expand_high = df['high'].iloc[i - 40:i - 20].max()
            expand_low = df['low'].iloc[i - 40:i - 20].min()
            expand_range = expand_high - expand_low
            
            contract_high = df['high'].iloc[i - 20:i].max()
            contract_low = df['low'].iloc[i - 20:i].min()
            contract_range = contract_high - contract_low
            
            if expand_range > 0 and contract_range < expand_range * 0.6:
                if df['close'].iloc[i] > df['high'].iloc[i - 5:i].mean():
                    patterns.append({
                        "pattern": "diamond_bullish",
                        "type": "classical",
                        "direction": "bullish",
                        "strength": 70,
                        "timestamp": str(df.index[i]),
                        "price": float(df['close'].iloc[i]),
                        "description": "Diamond Pattern - Bullish breakout"
                    })
                elif df['close'].iloc[i] < df['low'].iloc[i - 5:i].mean():
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
        
        logger.info(f"📚 Classical patterns: {len(patterns)}")
        
        return patterns[-20:]


# ========================================================================================================
# CANDLESTICK PATTERN DETECTOR
# ========================================================================================================
class CandlestickPatternDetector:

    @staticmethod
    def detect_doji(candle: pd.Series) -> Optional[Dict]:
        body = candle['body']
        range_candle = candle['range']
        if range_candle == 0:
            return None
        
        if (body / range_candle) < 0.1:
            return {
                "pattern": "doji",
                "type": "price_action",
                "direction": "neutral",
                "strength": 50,
                "description": "Doji - Market indecision"
            }
        return None
    
    @staticmethod
    def detect_hammer(candle: pd.Series) -> Optional[Dict]:
        body = candle['body']
        lower_shadow = candle['lower_shadow']
        upper_shadow = candle['upper_shadow']
        
        if body == 0 or candle['range'] == 0:
            return None
        
        if lower_shadow > 2 * body and upper_shadow < body and candle['is_bullish']:
            return {
                "pattern": "hammer",
                "type": "price_action",
                "direction": "bullish",
                "strength": 70,
                "description": "Hammer - Bullish reversal"
            }
        return None
    
    @staticmethod
    def detect_shooting_star(candle: pd.Series) -> Optional[Dict]:
        body = candle['body']
        lower_shadow = candle['lower_shadow']
        upper_shadow = candle['upper_shadow']
        
        if body == 0 or candle['range'] == 0:
            return None
        
        if upper_shadow > 2 * body and lower_shadow < body and candle['is_bearish']:
            return {
                "pattern": "shooting_star",
                "type": "price_action",
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
                "type": "price_action",
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
        prev = df.iloc[i - 1]
        
        curr_bullish = curr['close'] > curr['open']
        curr_bearish = curr['close'] < curr['open']
        prev_bearish = prev['close'] < prev['open']
        prev_bullish = prev['close'] > prev['open']
        
        if (curr_bullish and prev_bearish and
            curr['open'] < prev['close'] and
            curr['close'] > prev['open']):
            return {
                "pattern": "bullish_engulfing",
                "type": "price_action",
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
                "type": "price_action",
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
        prev = df.iloc[i - 1]
        
        curr_range = abs(curr['close'] - curr['open'])
        prev_range = abs(prev['close'] - prev['open'])
        
        if prev_range == 0:
            return None
        
        if curr_range < prev_range * 0.6:
            if prev['close'] > prev['open']:
                if (curr['close'] < prev['close'] and curr['open'] > prev['open']):
                    return {
                        "pattern": "bearish_harami",
                        "type": "price_action",
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
                        "type": "price_action",
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
        
        c1 = df.iloc[i - 2]
        c2 = df.iloc[i - 1]
        c3 = df.iloc[i]
        
        if c1['close'] < c1['open'] and c3['close'] > c3['open']:
            body2 = abs(c2['close'] - c2['open'])
            range2 = c2['high'] - c2['low']
            if range2 > 0 and (body2 / range2) < 0.3:
                if c2['low'] < c1['low'] and c3['open'] > c2['close']:
                    return {
                        "pattern": "morning_star",
                        "type": "price_action",
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
        
        c1 = df.iloc[i - 2]
        c2 = df.iloc[i - 1]
        c3 = df.iloc[i]
        
        if c1['close'] > c1['open'] and c3['close'] < c3['open']:
            body2 = abs(c2['close'] - c2['open'])
            range2 = c2['high'] - c2['low']
            if range2 > 0 and (body2 / range2) < 0.3:
                if c2['high'] > c1['high'] and c3['open'] < c2['close']:
                    return {
                        "pattern": "evening_star",
                        "type": "price_action",
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
        
        if (df['is_bullish'].iloc[i - 2] and
            df['is_bullish'].iloc[i - 1] and
            df['is_bullish'].iloc[i] and
            df['close'].iloc[i - 1] > df['close'].iloc[i - 2] and
            df['close'].iloc[i] > df['close'].iloc[i - 1]):
            return {
                "pattern": "three_white_soldiers",
                "type": "price_action",
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
        
        if (df['is_bearish'].iloc[i - 2] and
            df['is_bearish'].iloc[i - 1] and
            df['is_bearish'].iloc[i] and
            df['close'].iloc[i - 1] < df['close'].iloc[i - 2] and
            df['close'].iloc[i] < df['close'].iloc[i - 1]):
            return {
                "pattern": "three_black_crows",
                "type": "price_action",
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
        
        logger.info(f"🕯️ Candlestick patterns: {len(patterns)}")
        
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
                ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2
            
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
    def analyze(df: pd.DataFrame) -> Dict[str, Any]:
        if len(df) < 30:
            return {}
        
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        # RSI
        rsi = df['rsi'] if 'rsi' in df.columns else 50
        
        # MACD
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd - signal
        
        # Bollinger
        bb_upper = df['bb_upper'] if 'bb_upper' in df.columns else close.rolling(20).mean() + close.rolling(20).std() * 2
        bb_middle = df['bb_middle'] if 'bb_middle' in df.columns else close.rolling(20).mean()
        bb_lower = df['bb_lower'] if 'bb_lower' in df.columns else close.rolling(20).mean() - close.rolling(20).std() * 2
        bb_position = df['bb_position'] if 'bb_position' in df.columns else 50
        
        # ATR
        atr = df['atr'] if 'atr' in df.columns else (high - low).rolling(14).mean()
        atr_percent = (atr / close * 100).fillna(0)
        
        # Volume ratio
        volume_ratio = df['volume_ratio'] if 'volume_ratio' in df.columns else 1.0
        
        # SMA
        sma_20 = close.rolling(20).mean()
        sma_50 = close.rolling(50).mean()
        
        # Momentum
        mom_5 = df['mom_5'] if 'mom_5' in df.columns else close.pct_change(5) * 100
        mom_10 = df['mom_10'] if 'mom_10' in df.columns else close.pct_change(10) * 100
        
        heikin_ashi = TechnicalAnalyzer.calculate_heikin_ashi(df)
        
        result = {
            "rsi": round(float(rsi.iloc[-1]), 1),
            "macd": round(float(macd.iloc[-1]), 2),
            "macd_signal": round(float(signal.iloc[-1]), 2),
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
        ictsmartpro_signals: List[Dict]  # GainzAlgo ve Ultimate kalktı, ICTSMARTPRO geldi
    ) -> Dict[str, Any]:

        signals = []
        confidences = []
        weights = []
        all_patterns = []
        
        # === ICTSMARTPRO SİNYALLERİ (En yüksek öncelik) ===
        for sig in ictsmartpro_signals:
            if sig.get('direction') in ['bullish', 'bullish_reversal']:
                signals.append('BUY')
                confidences.append(sig.get('strength', 70) / 100)
                weights.append(2.5)
                all_patterns.append(sig)
            elif sig.get('direction') in ['bearish', 'bearish_reversal']:
                signals.append('SELL')
                confidences.append(sig.get('strength', 70) / 100)
                weights.append(2.5)
                all_patterns.append(sig)
        
        # === ICT PATTERNS ===
        for pattern_list in ict_patterns.values():
            for pattern in pattern_list[:3]:
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
        
        # En güçlü pattern'in TP/SL'sini bul
        best_pattern = None
        max_strength = 0
        
        for i in range(len(signals)):
            s = signals[i]
            c = confidences[i]
            w = weights[i]
            
            if s == 'BUY':
                buy_score += c * w
                buy_count += 1
            elif s == 'SELL':
                sell_score += c * w
                sell_count += 1
            
            # En güçlü pattern'i bul (TP/SL için)
            if i < len(all_patterns):
                strength = all_patterns[i].get('strength', 0)
                if strength > max_strength:
                    max_strength = strength
                    best_pattern = all_patterns[i]
        
        if buy_score > sell_score:
            final_signal = "BUY"
            total_score = buy_score + sell_score
            avg_conf = (buy_score / total_score * 100) if total_score > 0 else Config.DEFAULT_CONFIDENCE
            tp_level = best_pattern.get('tp_level') if best_pattern and best_pattern.get('direction') in ['bullish', 'bullish_reversal'] else None
            sl_level = best_pattern.get('sl_level') if best_pattern and best_pattern.get('direction') in ['bullish', 'bullish_reversal'] else None
        elif sell_score > buy_score:
            final_signal = "SELL"
            total_score = buy_score + sell_score
            avg_conf = (sell_score / total_score * 100) if total_score > 0 else Config.DEFAULT_CONFIDENCE
            tp_level = best_pattern.get('tp_level') if best_pattern and best_pattern.get('direction') in ['bearish', 'bearish_reversal'] else None
            sl_level = best_pattern.get('sl_level') if best_pattern and best_pattern.get('direction') in ['bearish', 'bearish_reversal'] else None
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
    description="AI-Powered Crypto Analysis with ICT & Classical Patterns",
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
async def analyze_symbol(
    symbol: str,
    interval: str = Query(
        default="1h",
        regex="^(1m|5m|15m|30m|1h|4h|1d|1w)$",
        description="Timeframe (1m,5m,15m,30m,1h,4h,1d,1w)"
    ),
    limit: int = Query(
        default=200,
        ge=50,
        le=1000,
        description="Candle count (50-1000)"
    )
):
    # Symbol formatını düzelt
    original_symbol = symbol.upper().strip()
    symbol = original_symbol
    
    if not symbol.endswith("USDT"):
        if "USDT" in symbol:
            symbol = symbol.replace("-", "").replace("/", "").replace(" ", "")
        else:
            symbol = f"{symbol}USDT"
    
    if not symbol.endswith("USDT") or len(symbol) < 6:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid symbol format: {original_symbol}. Use format like BTC, ETH, or BTCUSDT"
        )
    
    logger.info(f"🔍 Analyzing {symbol} @ {interval} (limit={limit})")
    
    start_time = time.time()
    timeout = 25
    
    try:
        async with data_fetcher as fetcher:
            candles = await asyncio.wait_for(
                fetcher.get_candles(symbol, interval, limit),
                timeout=15
            )
            exchange_stats = fetcher.get_stats()
        
        if not candles:
            raise HTTPException(
                status_code=422,
                detail=f"No candle data received from exchanges for {symbol}"
            )
        
        if len(candles) < Config.MIN_CANDLES:
            logger.warning(f"⚠️ Yetersiz mum: {len(candles)} (min:{Config.MIN_CANDLES})")
            raise HTTPException(
                status_code=422,
                detail=f"Insufficient candles for {symbol}. Got {len(candles)}, minimum required: {Config.MIN_CANDLES}"
            )
        
        # DataFrame oluştur
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp').sort_index()
        
        # ORTAK DataFrame hazırlama
        df_prepared = prepare_dataframe(df)
        
        logger.info(f"📊 DataFrame hazır: {len(df_prepared)} mum, {len(df_prepared.columns)} kolon")
        
        # Piyasa yapısı analizi (önce bunu yap, ICTSMARTPRO için lazım)
        market_structure = MarketStructureAnalyzer.analyze(df_prepared)
        
        # Analizleri yap
        technical = TechnicalAnalyzer.analyze(df_prepared)
        ict_patterns = ICTPatternDetector.analyze(df_prepared)
        candle_patterns = CandlestickPatternDetector.analyze(df_prepared)
        classical_patterns = ClassicalPatternDetector.analyze(df_prepared)
        
        # ICTSMARTPRO stratejisi (GainzAlgo ve Ultimate KALDIRILDI)
        ictsmartpro_signals = ICTSmartProDetector.detect(df_prepared, market_structure)
        
        # Signal oluştur
        signal = SignalGenerator.generate(
            technical,
            market_structure,
            ict_patterns,
            candle_patterns,
            classical_patterns,
            ictsmartpro_signals
        )
        
        # Tüm pattern'leri topla
        all_patterns = []
        
        # ICT pattern'leri
        for pattern_list in ict_patterns.values():
            for p in pattern_list:
                formatted_p = {
                    "name": p.get("pattern", "ict_pattern"),
                    "type": PatternType.ICT,
                    "direction": p.get("direction", "neutral"),
                    "confidence": float(p.get("strength", 50)),
                    "timestamp": p.get("timestamp", datetime.now().isoformat()),
                    "price": float(p.get("price", 0)),
                    "description": p.get("description", ""),
                    "sl_level": p.get("sl_level"),
                    "tp_level": p.get("tp_level")
                }
                all_patterns.append(formatted_p)
        
        # Candlestick pattern'leri
        for p in candle_patterns:
            formatted_p = {
                "name": p.get("pattern", "candle_pattern"),
                "type": PatternType.PRICE_ACTION,
                "direction": p.get("direction", "neutral"),
                "confidence": float(p.get("strength", 50)),
                "timestamp": p.get("timestamp", datetime.now().isoformat()),
                "price": float(p.get("price", 0)),
                "description": p.get("description", ""),
                "sl_level": p.get("sl_level"),
                "tp_level": p.get("tp_level")
            }
            all_patterns.append(formatted_p)
        
        # Classical pattern'leri
        for p in classical_patterns:
            formatted_p = {
                "name": p.get("pattern", "classical_pattern"),
                "type": PatternType.CLASSICAL,
                "direction": p.get("direction", "neutral"),
                "confidence": float(p.get("strength", 50)),
                "timestamp": p.get("timestamp", datetime.now().isoformat()),
                "price": float(p.get("price", 0)),
                "description": p.get("description", ""),
                "sl_level": p.get("sl_level"),
                "tp_level": p.get("tp_level")
            }
            all_patterns.append(formatted_p)
        
        # ICTSMARTPRO pattern'leri
        for p in ictsmartpro_signals:
            formatted_p = {
                "name": p.get("pattern", "ictsmartpro"),
                "type": PatternType.ICTSMARTPRO,
                "direction": p.get("direction", "neutral"),
                "confidence": float(p.get("strength", 50)),
                "timestamp": p.get("timestamp", datetime.now().isoformat()),
                "price": float(p.get("price", 0)),
                "description": p.get("description", ""),
                "sl_level": p.get("sl_level"),
                "tp_level": p.get("tp_level")
            }
            all_patterns.append(formatted_p)
        
        # Aktif kaynaklar
        active_sources = fetcher.get_active_sources()
        
        # Son mum verileri
        last_row = df_prepared.iloc[-1]
        first_row = df_prepared.iloc[0]
        volume_sum = float(df_prepared["volume"].sum())
        
        # 24h hacim tahmini
        interval_multipliers = {
            "1m": 1440, "5m": 288, "15m": 96, "30m": 48,
            "1h": 24, "4h": 6, "1d": 1, "1w": 0.142857
        }
        volume_24h = volume_sum * interval_multipliers.get(interval, 24)
        
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
                "volume_24h_approx": round(volume_24h, 2),
                "volume_candle": float(last_row.get("volume", 0)),
                "change_percent": round(
                    (float(last_row["close"]) / float(first_row["close"]) - 1) * 100,
                    2
                ),
                "change_24h": round(
                    (float(last_row["close"]) / float(df_prepared.iloc[-min(24, len(df_prepared))]["close"]) - 1) * 100
                    if len(df_prepared) >= 24 else 0,
                    2
                )
            },
            "signal": signal,
            "technical": technical,
            "ict_patterns": ict_patterns,
            "candle_patterns": candle_patterns[-20:],
            "classical_patterns": classical_patterns[-10:],
            "ictsmartpro_signals": ictsmartpro_signals[-5:],  # GainzAlgo yerine ICTSMARTPRO
            "market_structure": market_structure,
            "active_sources": active_sources,
            "data_points": len(df_prepared),
            "all_patterns": all_patterns[-50:],
            "exchange_stats": exchange_stats,
            "performance_ms": round((time.time() - start_time) * 1000, 2)
        }
        
        # Log
        logger.info(
            f"✅ {symbol} @ {interval} | {signal.get('signal', 'UNKNOWN')} "
            f"({signal.get('confidence', 0):.1f}%) | {len(df_prepared)} candles | "
            f"ICT:{sum(len(v) for v in ict_patterns.values())} "
            f"Classical:{len(classical_patterns)} | "
            f"ICTSMARTPRO:{len(ictsmartpro_signals)} | "
            f"⏱️ {response['performance_ms']}ms"
        )
        
        return response
    
    except asyncio.TimeoutError:
        logger.error(f"⏰ Timeout analyzing {symbol}")
        raise HTTPException(
            status_code=504,
            detail=f"Analysis timeout for {symbol} after {timeout}s"
        )
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"❌ Value error for {symbol}: {str(e)}")
        raise HTTPException(status_code=422, detail=str(e)[:300])
    except Exception as e:
        logger.exception(f"❌ Critical error for {symbol}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)[:200]}"
        )


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
    logger.info(f"Pattern Types: ICT (15+), Classical (10+), Candlestick (15+), ICTSMARTPRO")
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
