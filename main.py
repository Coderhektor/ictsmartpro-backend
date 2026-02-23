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
from datetime import datetime, timezone, timedelta  # ✅ timedelta EKLENDİ
from typing import Dict, List, Optional, Any, Tuple, Set
from collections import defaultdict
from contextlib import asynccontextmanager

# ✅ Pydantic EKLENDİ
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
# LOGGING SETUP - Renkli ve detaylı
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
    """Logging sistemi - renkli ve dosyaya"""
    logger = logging.getLogger("ictsmartpro")
    logger.setLevel(logging.DEBUG if os.getenv("DEBUG") else logging.INFO)
    logger.handlers.clear()
    
    # Console handler (renkli)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(ColoredFormatter())
    logger.addHandler(console)
    
    # File handler (detaylı)
    try:
        file_handler = logging.FileHandler('ictsmartpro.log')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)-12s | %(filename)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    except:
        pass
    
    return logger

logger = setup_logging()

# ========================================================================================================
# CONFIGURATION - Environment based
# ========================================================================================================
class Config:
    """Sistem konfigürasyonu - çevre değişkenlerinden okur"""
    
    # Environment
    ENV = os.getenv("ENV", "production")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    PORT = int(os.getenv("PORT", 8000))
    
    # API Settings
    API_TIMEOUT = int(os.getenv("API_TIMEOUT", "8"))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
    
    # Data Requirements
    MIN_CANDLES = int(os.getenv("MIN_CANDLES", "30"))
    MIN_EXCHANGES = int(os.getenv("MIN_EXCHANGES", "2"))
    
    # Cache
    CACHE_TTL = int(os.getenv("CACHE_TTL", "45"))
    
    # Signal Confidence - GERÇEKÇİ SINIRLAR
    MAX_CONFIDENCE = float(os.getenv("MAX_CONFIDENCE", "78.5"))
    DEFAULT_CONFIDENCE = float(os.getenv("DEFAULT_CONFIDENCE", "51.5"))
    MIN_CONFIDENCE_FOR_SIGNAL = float(os.getenv("MIN_CONFIDENCE", "54.0"))
    
    # Rate Limiting
    RATE_LIMIT_CALLS = int(os.getenv("RATE_LIMIT_CALLS", "60"))
    RATE_LIMIT_PERIOD = int(os.getenv("RATE_LIMIT_PERIOD", "60"))
    
    # Allowed origins
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# ========================================================================================================
# DATA MODELS
# ========================================================================================================
class Candle(BaseModel):
    """Mum verisi modeli"""
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
    """Sinyal modeli"""
    signal: str  # STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL
    confidence: float
    recommendation: str
    buy_count: int = 0
    sell_count: int = 0

class AnalysisResponse(BaseModel):
    """Analiz cevap modeli"""
    success: bool
    symbol: str
    interval: str
    timestamp: str
    price: Dict[str, float]
    signal: Signal
    technical: Dict[str, Any]
    ict_patterns: Dict[str, Any]
    candle_patterns: List[Dict[str, Any]]
    market_structure: Dict[str, Any]
    active_sources: List[str]
    data_points: int

# ========================================================================================================
# EXCHANGE DATA FETCHER - SADECE 4 GÜVENİLİR KAYNAK
# ========================================================================================================
class ExchangeDataFetcher:
    """
    📊 2026 ULTRA STABIL - 4 GÜVENİLİR KAYNAK
    
    ✓ KRAKEN    - En stabil, en eski
    ✓ BINANCE   - En yüksek likidite
    ✓ MEXC      - En hızlı API
    ✓ YAHOO     - Sınırsız ücretsiz veri (fallback)
    """
    
    EXCHANGES = [
        # Kraken
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
        # Binance
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
        # MEXC
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
        # Yahoo Finance
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
    
    # WebSocket konfigürasyonu
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
        """HTTP session başlat"""
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
        """Rate limit kontrolü"""
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
        """Tek bir borsadan veri çek"""
        if not self._check_rate_limit():
            return None
        
        name = exchange["name"]
        
        try:
            # Interval kontrolü
            if interval not in exchange["interval_map"]:
                return None
            
            ex_interval = exchange["interval_map"][interval]
            formatted_symbol = exchange["symbol_fmt"](symbol)
            
            # URL ve params hazırla
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
            
            # HTTP isteği
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
                
                # Başarılı
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
        """API cevabını parse et"""
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
        """Farklı borsalardan gelen verileri birleştir"""
        if not all_candles:
            return []
        
        # Timestamp bazında grupla
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
            
            # Ağırlıklı ortalama hesapla
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
        """Ana veri çekme fonksiyonu"""
        cache_key = self._get_cache_key(symbol, interval)
        
        # Cache kontrolü
        if self._is_cache_valid(cache_key):
            cached = self.cache.get(cache_key, [])
            if cached:
                logger.info(f"📦 CACHE: {symbol} ({interval}) - {len(cached)} candles")
                return cached[-limit:]
        
        logger.info(f"🔄 FETCH: {symbol} ({interval}) from {len(self.EXCHANGES)} sources...")
        
        # Tüm borsalardan paralel çek
        tasks = [
            self._fetch_exchange(exchange, symbol, interval, limit * 2)
            for exchange in self.EXCHANGES
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Başarılı sonuçları filtrele
        valid_results = []
        for r in results:
            if isinstance(r, list) and len(r) >= 10:
                valid_results.append(r)
        
        logger.info(f"✅ RECEIVED: {len(valid_results)}/{len(self.EXCHANGES)} sources")
        
        if len(valid_results) < Config.MIN_EXCHANGES:
            logger.warning(f"⚠️ Only {len(valid_results)} sources, using available...")
            if not valid_results:
                return []
        
        # Birleştir
        aggregated = self._aggregate_candles(valid_results)
        
        if len(aggregated) < Config.MIN_CANDLES:
            logger.warning(f"⚠️ Only {len(aggregated)} candles (need {Config.MIN_CANDLES})")
            return []
        
        # Cache'e kaydet
        self.cache[cache_key] = aggregated
        self.cache_time[cache_key] = time.time()
        
        return aggregated[-limit:]
    
    async def get_current_price(self, symbol: str) -> Optional[float]:
        """Anlık fiyat - hızlı"""
        # Cache kontrolü
        if symbol in self.price_cache:
            if time.time() - self.price_cache[symbol].get("time", 0) < 10:
                return self.price_cache[symbol].get("price")
        
        # Binance'ten dene
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
        
        # MEXC'ten dene
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
        """Borsa istatistiklerini döndür"""
        return dict(self.stats)
    
    def get_active_sources(self) -> List[str]:
        """Aktif kaynakları döndür"""
        active = []
        now = time.time()
        for name, stats in self.stats.items():
            # Son 5 dakikada başarılı olanlar
            if stats.get("last_success", 0) > now - 300:
                active.append(name)
        return active

# ========================================================================================================
# ICT PATTERN DETECTOR (Smart Money Concepts)
# ========================================================================================================
class ICTPatternDetector:
    """
    ICT (Inner Circle Trader) Pattern Detection
    - Fair Value Gap (FVG)
    - Order Block (OB)
    - Break of Structure (BOS)
    - Change of Character (CHoCH)
    - Liquidity Sweep
    """
    
    @staticmethod
    def detect_fair_value_gap(df: pd.DataFrame) -> List[Dict]:
        """Fair Value Gap tespiti"""
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
                        "type": "bullish_fvg",
                        "direction": "bullish",
                        "index": i,
                        "timestamp": str(df.index[i]),
                        "gap_low": float(df['high'].iloc[i-1]),
                        "gap_high": float(df['low'].iloc[i+1]),
                        "gap_percent": round(gap_percent, 2),
                        "strength": min(round(gap_percent * 5, 1), 80)
                    })
            
            # Bearish FVG
            elif df['high'].iloc[i+1] < df['low'].iloc[i-1]:
                gap_size = df['low'].iloc[i-1] - df['high'].iloc[i+1]
                gap_percent = (gap_size / df['low'].iloc[i-1]) * 100
                
                if gap_percent > 0.1:
                    fvgs.append({
                        "type": "bearish_fvg",
                        "direction": "bearish",
                        "index": i,
                        "timestamp": str(df.index[i]),
                        "gap_low": float(df['high'].iloc[i+1]),
                        "gap_high": float(df['low'].iloc[i-1]),
                        "gap_percent": round(gap_percent, 2),
                        "strength": min(round(gap_percent * 5, 1), 80)
                    })
        
        return fvgs[-5:]  # Son 5 FVG
    
    @staticmethod
    def detect_order_blocks(df: pd.DataFrame) -> List[Dict]:
        """Order Block tespiti"""
        obs = []
        if len(df) < 5:
            return obs
        
        for i in range(2, len(df)-2):
            # Bullish Order Block
            if (df['close'].iloc[i] > df['open'].iloc[i] and
                df['close'].iloc[i-1] < df['open'].iloc[i-1] and
                df['high'].iloc[i] > df['high'].iloc[i-1]):
                
                ob_range = abs(df['high'].iloc[i-1] - df['low'].iloc[i-1])
                ob_percent = (ob_range / df['close'].iloc[i-1]) * 100
                
                obs.append({
                    "type": "bullish_ob",
                    "direction": "bullish",
                    "index": i-1,
                    "timestamp": str(df.index[i-1]),
                    "price_low": float(df['low'].iloc[i-1]),
                    "price_high": float(df['high'].iloc[i-1]),
                    "strength": min(round(ob_percent * 10, 1), 75)
                })
            
            # Bearish Order Block
            elif (df['close'].iloc[i] < df['open'].iloc[i] and
                  df['close'].iloc[i-1] > df['open'].iloc[i-1] and
                  df['low'].iloc[i] < df['low'].iloc[i-1]):
                
                ob_range = abs(df['high'].iloc[i-1] - df['low'].iloc[i-1])
                ob_percent = (ob_range / df['close'].iloc[i-1]) * 100
                
                obs.append({
                    "type": "bearish_ob",
                    "direction": "bearish",
                    "index": i-1,
                    "timestamp": str(df.index[i-1]),
                    "price_low": float(df['low'].iloc[i-1]),
                    "price_high": float(df['high'].iloc[i-1]),
                    "strength": min(round(ob_percent * 10, 1), 75)
                })
        
        return obs[-5:]
    
    @staticmethod
    def detect_break_of_structure(df: pd.DataFrame) -> List[Dict]:
        """Break of Structure tespiti"""
        bos_signals = []
        if len(df) < 10:
            return bos_signals
        
        recent_high = df['high'].iloc[-11:-1].max()
        recent_low = df['low'].iloc[-11:-1].min()
        current_close = df['close'].iloc[-1]
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        # Bullish BOS
        if current_high > recent_high * 1.005:
            bos_size = (current_high - recent_high) / recent_high * 100
            bos_signals.append({
                "type": "bullish_bos",
                "direction": "bullish",
                "timestamp": str(df.index[-1]),
                "break_level": float(recent_high),
                "current_price": float(current_close),
                "break_size": round(bos_size, 2),
                "strength": min(round(bos_size * 20, 1), 80)
            })
        
        # Bearish BOS
        elif current_low < recent_low * 0.995:
            bos_size = (recent_low - current_low) / recent_low * 100
            bos_signals.append({
                "type": "bearish_bos",
                "direction": "bearish",
                "timestamp": str(df.index[-1]),
                "break_level": float(recent_low),
                "current_price": float(current_close),
                "break_size": round(bos_size, 2),
                "strength": min(round(bos_size * 20, 1), 80)
            })
        
        return bos_signals
    
    @staticmethod
    def detect_change_of_character(df: pd.DataFrame) -> List[Dict]:
        """Change of Character tespiti"""
        if len(df) < 15:
            return []
        
        choch_signals = []
        ema_fast = df['close'].ewm(span=9).mean()
        ema_slow = df['close'].ewm(span=21).mean()
        
        prev_trend = "bullish" if ema_fast.iloc[-5] > ema_slow.iloc[-5] else "bearish"
        current_trend = "bullish" if ema_fast.iloc[-1] > ema_slow.iloc[-1] else "bearish"
        
        if prev_trend != current_trend:
            mom_prev = df['close'].iloc[-5] - df['close'].iloc[-6]
            mom_current = df['close'].iloc[-1] - df['close'].iloc[-2]
            
            if current_trend == "bullish" and mom_current > mom_prev * 1.5:
                choch_signals.append({
                    "type": "bullish_choch",
                    "direction": "bullish",
                    "timestamp": str(df.index[-1]),
                    "strength": 70
                })
            elif current_trend == "bearish" and mom_current < mom_prev * 1.5:
                choch_signals.append({
                    "type": "bearish_choch",
                    "direction": "bearish",
                    "timestamp": str(df.index[-1]),
                    "strength": 70
                })
        
        return choch_signals
    
    @staticmethod
    def detect_liquidity_sweep(df: pd.DataFrame) -> List[Dict]:
        """Liquidity Sweep tespiti"""
        sweeps = []
        if len(df) < 20:
            return sweeps
        
        swing_high = df['high'].iloc[-21:-1].max()
        swing_low = df['low'].iloc[-21:-1].min()
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        current_close = df['close'].iloc[-1]
        
        # Yukarı yönlü sweep
        if current_high > swing_high * 1.01 and current_close < swing_high:
            sweep_size = (current_high - swing_high) / swing_high * 100
            sweeps.append({
                "type": "liquidity_sweep_up",
                "direction": "bearish_reversal",
                "timestamp": str(df.index[-1]),
                "swept_level": float(swing_high),
                "sweep_high": float(current_high),
                "current_price": float(current_close),
                "sweep_size": round(sweep_size, 2),
                "strength": min(round(sweep_size * 20, 1), 75)
            })
        
        # Aşağı yönlü sweep
        elif current_low < swing_low * 0.99 and current_close > swing_low:
            sweep_size = (swing_low - current_low) / swing_low * 100
            sweeps.append({
                "type": "liquidity_sweep_down",
                "direction": "bullish_reversal",
                "timestamp": str(df.index[-1]),
                "swept_level": float(swing_low),
                "sweep_low": float(current_low),
                "current_price": float(current_close),
                "sweep_size": round(sweep_size, 2),
                "strength": min(round(sweep_size * 20, 1), 75)
            })
        
        return sweeps
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> Dict[str, Any]:
        """Tüm ICT pattern'lerini analiz et"""
        fvgs = ICTPatternDetector.detect_fair_value_gap(df)
        obs = ICTPatternDetector.detect_order_blocks(df)
        bos = ICTPatternDetector.detect_break_of_structure(df)
        choch = ICTPatternDetector.detect_change_of_character(df)
        sweeps = ICTPatternDetector.detect_liquidity_sweep(df)
        
        # Bullish/Bearish pattern sayıları
        bullish_count = sum(1 for f in fvgs if f['direction'] == 'bullish')
        bullish_count += sum(1 for o in obs if o['direction'] == 'bullish')
        bullish_count += sum(1 for b in bos if b['direction'] == 'bullish')
        bullish_count += sum(1 for c in choch if c['direction'] == 'bullish')
        bullish_count += sum(1 for s in sweeps if 'bullish' in s['direction'])
        
        bearish_count = sum(1 for f in fvgs if f['direction'] == 'bearish')
        bearish_count += sum(1 for o in obs if o['direction'] == 'bearish')
        bearish_count += sum(1 for b in bos if b['direction'] == 'bearish')
        bearish_count += sum(1 for c in choch if c['direction'] == 'bearish')
        bearish_count += sum(1 for s in sweeps if 'bearish' in s['direction'])
        
        return {
            "fair_value_gaps": fvgs,
            "order_blocks": obs,
            "break_of_structure": bos,
            "change_of_character": choch,
            "liquidity_sweeps": sweeps,
            "has_bullish_patterns": bullish_count > bearish_count,
            "has_bearish_patterns": bearish_count > bullish_count
        }

# ========================================================================================================
# CANDLESTICK PATTERN DETECTOR
# ========================================================================================================
class CandlestickPatternDetector:
    """Klasik Japon mumu pattern'leri"""
    
    @staticmethod
    def detect_doji(candle: pd.Series) -> bool:
        body = abs(candle['close'] - candle['open'])
        range_candle = candle['high'] - candle['low']
        if range_candle == 0:
            return False
        return (body / range_candle) < 0.1
    
    @staticmethod
    def detect_hammer(candle: pd.Series) -> bool:
        body = abs(candle['close'] - candle['open'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        
        if body == 0:
            return False
        
        return (lower_shadow > 2 * body and upper_shadow < body)
    
    @staticmethod
    def detect_shooting_star(candle: pd.Series) -> bool:
        body = abs(candle['close'] - candle['open'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        
        if body == 0:
            return False
        
        return (upper_shadow > 2 * body and lower_shadow < body)
    
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
        
        # Bullish Engulfing
        if (curr_bullish and prev_bearish and 
            curr['open'] < prev['close'] and 
            curr['close'] > prev['open']):
            return {
                "pattern": "bullish_engulfing",
                "direction": "bullish",
                "strength": 70,
                "timestamp": str(df.index[i])
            }
        
        # Bearish Engulfing
        elif (curr_bearish and prev_bullish and 
              curr['open'] > prev['close'] and 
              curr['close'] < prev['open']):
            return {
                "pattern": "bearish_engulfing",
                "direction": "bearish",
                "strength": 70,
                "timestamp": str(df.index[i])
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
            if prev['close'] > prev['open']:  # Previous bullish
                if (curr['close'] < prev['close'] and curr['open'] > prev['open']):
                    return {
                        "pattern": "bullish_harami",
                        "direction": "bullish_reversal",
                        "strength": 60,
                        "timestamp": str(df.index[i])
                    }
            else:  # Previous bearish
                if (curr['close'] > prev['close'] and curr['open'] < prev['open']):
                    return {
                        "pattern": "bearish_harami",
                        "direction": "bearish_reversal",
                        "strength": 60,
                        "timestamp": str(df.index[i])
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
                        "direction": "bullish",
                        "strength": 75,
                        "timestamp": str(df.index[i])
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
                        "direction": "bearish",
                        "strength": 75,
                        "timestamp": str(df.index[i])
                    }
        
        return None
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> List[Dict]:
        """Tüm klasik pattern'leri analiz et"""
        patterns = []
        
        if len(df) < 10:
            return patterns
        
        for i in range(2, len(df)):
            curr = df.iloc[i]
            
            # Tek mum pattern'leri
            if CandlestickPatternDetector.detect_doji(curr):
                patterns.append({
                    "pattern": "doji",
                    "direction": "neutral",
                    "strength": 50,
                    "timestamp": str(df.index[i])
                })
            
            if CandlestickPatternDetector.detect_hammer(curr):
                patterns.append({
                    "pattern": "hammer",
                    "direction": "bullish",
                    "strength": 65,
                    "timestamp": str(df.index[i])
                })
            
            if CandlestickPatternDetector.detect_shooting_star(curr):
                patterns.append({
                    "pattern": "shooting_star",
                    "direction": "bearish",
                    "strength": 65,
                    "timestamp": str(df.index[i])
                })
            
            # Çift mum pattern'leri
            engulfing = CandlestickPatternDetector.detect_engulfing(df, i)
            if engulfing:
                patterns.append(engulfing)
            
            harami = CandlestickPatternDetector.detect_harami(df, i)
            if harami:
                patterns.append(harami)
            
            # Üçlü mum pattern'leri
            morning = CandlestickPatternDetector.detect_morning_star(df, i)
            if morning:
                patterns.append(morning)
            
            evening = CandlestickPatternDetector.detect_evening_star(df, i)
            if evening:
                patterns.append(evening)
        
        return patterns[-15:]

# ========================================================================================================
# TECHNICAL ANALYZER - Heikin Ashi + Indicators
# ========================================================================================================
class TechnicalAnalyzer:
    """Teknik göstergeler + Heikin Ashi"""
    
    @staticmethod
    def calculate_heikin_ashi(df: pd.DataFrame) -> Dict[str, Any]:
        """Heikin Ashi hesaplamaları"""
        try:
            if len(df) < 20:
                return {}
            
            # Heikin Ashi close
            ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
            
            # Heikin Ashi open
            ha_open = ha_close.copy()
            for i in range(1, len(ha_open)):
                ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
            
            # Heikin Ashi high/low
            ha_high = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
            ha_low = pd.concat([df['low'], ha_open, ha_close], axis=1).min(axis=1)
            
            # Trend analizi
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
            
            # Heikin Ashi RSI
            delta = ha_close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss.replace(0, np.nan)
            ha_rsi = 100 - (100 / (1 + rs))
            
            # Renk değişimi
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
        """Tüm teknik göstergeleri hesapla"""
        if len(df) < 30:
            return {}
        
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        # Temel göstergeler
        rsi = TechnicalAnalyzer.calculate_rsi(close)
        macd, macd_signal, macd_hist = TechnicalAnalyzer.calculate_macd(close)
        bb_upper, bb_middle, bb_lower = TechnicalAnalyzer.calculate_bollinger_bands(close)
        
        # Bollinger pozisyonu
        bb_range = bb_upper - bb_lower
        bb_range = bb_range.replace(0, 1)
        bb_position = ((close - bb_lower) / bb_range * 100).clip(0, 100)
        
        # ATR
        atr = TechnicalAnalyzer.calculate_atr(high, low, close)
        atr_percent = (atr / close * 100).fillna(0)
        
        # Volume
        volume_sma = volume.rolling(20).mean().fillna(volume)
        volume_ratio = (volume / volume_sma).fillna(1.0)
        
        # SMA'lar
        sma_20 = close.rolling(20).mean()
        sma_50 = close.rolling(50).mean()
        
        # Heikin Ashi
        heikin_ashi = TechnicalAnalyzer.calculate_heikin_ashi(df)
        
        # Sonuçları birleştir
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
        }
        
        # Heikin Ashi'yi ekle
        result.update(heikin_ashi)
        
        return result

# ========================================================================================================
# MARKET STRUCTURE ANALYZER
# ========================================================================================================
class MarketStructureAnalyzer:
    """Piyasa yapısı analizi"""
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> Dict[str, Any]:
        """Trend, yapı, volatilite analizi"""
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
        
        # EMA'lar ile trend
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
        
        # Yapı analizi
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
        
        # Volatilite
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
        
        # Momentum
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
# SIGNAL GENERATOR
# ========================================================================================================
class SignalGenerator:
    """Sinyal üretici - tüm kaynakları birleştirir"""
    
    @staticmethod
    def generate(
        technical: Dict[str, Any],
        market_structure: Dict[str, Any],
        ict_patterns: Dict[str, Any],
        candle_patterns: List[Dict]
    ) -> Dict[str, Any]:
        """Tüm analizleri birleştirerek sinyal üret"""
        signals = []
        confidences = []
        weights = []
        
        # Heikin Ashi
        ha_trend = technical.get('ha_trend', 'NEUTRAL')
        ha_color = technical.get('ha_color_change', 0)
        ha_rsi = technical.get('ha_rsi', 50)
        
        if ha_trend in ['STRONG_BULLISH', 'BULLISH']:
            signals.append('BUY')
            confidences.append(0.72 if 'STRONG' in ha_trend else 0.68)
            weights.append(1.8 if 'STRONG' in ha_trend else 1.5)
        elif ha_trend in ['STRONG_BEARISH', 'BEARISH']:
            signals.append('SELL')
            confidences.append(0.72 if 'STRONG' in ha_trend else 0.68)
            weights.append(1.8 if 'STRONG' in ha_trend else 1.5)
        
        if ha_color == 1:
            signals.append('BUY')
            confidences.append(0.70)
            weights.append(1.6)
        elif ha_color == -1:
            signals.append('SELL')
            confidences.append(0.70)
            weights.append(1.6)
        
        if ha_rsi < 30:
            signals.append('BUY')
            confidences.append(0.66)
            weights.append(1.3)
        elif ha_rsi > 70:
            signals.append('SELL')
            confidences.append(0.66)
            weights.append(1.3)
        
        # ICT Patterns
        for fvg in ict_patterns.get('fair_value_gaps', [])[:2]:
            signals.append('BUY' if fvg['direction'] == 'bullish' else 'SELL')
            confidences.append(0.68)
            weights.append(1.4)
        
        for ob in ict_patterns.get('order_blocks', [])[:2]:
            signals.append('BUY' if ob['direction'] == 'bullish' else 'SELL')
            confidences.append(0.70)
            weights.append(1.5)
        
        for bos in ict_patterns.get('break_of_structure', []):
            signals.append('BUY' if bos['direction'] == 'bullish' else 'SELL')
            confidences.append(0.71)
            weights.append(1.5)
        
        for choch in ict_patterns.get('change_of_character', []):
            signals.append('BUY' if choch['direction'] == 'bullish' else 'SELL')
            confidences.append(0.72)
            weights.append(1.6)
        
        # Klasik pattern'ler
        for pattern in candle_patterns[-5:]:
            if pattern.get('direction') in ['bullish', 'bullish_reversal']:
                signals.append('BUY')
                confidences.append(pattern.get('strength', 60) / 100)
                weights.append(1.2)
            elif pattern.get('direction') in ['bearish', 'bearish_reversal']:
                signals.append('SELL')
                confidences.append(pattern.get('strength', 60) / 100)
                weights.append(1.2)
        
        # RSI
        rsi = technical.get('rsi', 50)
        if rsi < 30:
            signals.append('BUY')
            confidences.append(0.64)
            weights.append(1.1)
        elif rsi > 70:
            signals.append('SELL')
            confidences.append(0.64)
            weights.append(1.1)
        
        # MACD
        macd_hist = technical.get('macd_histogram', 0)
        if macd_hist > 0:
            signals.append('BUY')
            confidences.append(0.62)
            weights.append(1.0)
        elif macd_hist < 0:
            signals.append('SELL')
            confidences.append(0.62)
            weights.append(1.0)
        
        # Bollinger
        bb_pos = technical.get('bb_position', 50)
        if bb_pos < 15:
            signals.append('BUY')
            confidences.append(0.58)
            weights.append(0.9)
        elif bb_pos > 85:
            signals.append('SELL')
            confidences.append(0.58)
            weights.append(0.9)
        
        # Market Structure
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
                "sell_count": 0
            }
        
        # Ağırlıklı skor hesapla
        buy_score = sum(c * w for s, c, w in zip(signals, confidences, weights) if s == 'BUY')
        sell_score = sum(c * w for s, c, w in zip(signals, confidences, weights) if s == 'SELL')
        
        buy_count = sum(1 for s in signals if s == 'BUY')
        sell_count = sum(1 for s in signals if s == 'SELL')
        
        if buy_score > sell_score:
            final_signal = "BUY"
            total_score = buy_score + sell_score
            avg_conf = (buy_score / total_score * 100) if total_score > 0 else Config.DEFAULT_CONFIDENCE
        elif sell_score > buy_score:
            final_signal = "SELL"
            total_score = buy_score + sell_score
            avg_conf = (sell_score / total_score * 100) if total_score > 0 else Config.DEFAULT_CONFIDENCE
        else:
            final_signal = "NEUTRAL"
            avg_conf = Config.DEFAULT_CONFIDENCE
        
        # Güven sınırlaması
        avg_conf = min(avg_conf, Config.MAX_CONFIDENCE)
        avg_conf = max(avg_conf, 45.0)
        
        # Güçlü sinyal
        if avg_conf > 72 and buy_count > sell_count * 2:
            final_signal = "STRONG_BUY"
        elif avg_conf > 72 and sell_count > buy_count * 2:
            final_signal = "STRONG_SELL"
        
        # Recommendation
        rec = SignalGenerator._generate_recommendation(
            final_signal, avg_conf, technical, market_structure, ict_patterns
        )
        
        return {
            "signal": final_signal,
            "confidence": round(avg_conf, 1),
            "recommendation": rec,
            "buy_count": buy_count,
            "sell_count": sell_count
        }
    
    @staticmethod
    def _generate_recommendation(signal, conf, technical, structure, ict):
        """Öneri metni oluştur"""
        parts = []
        
        ha_trend = technical.get('ha_trend', '')
        if ha_trend:
            parts.append(f"Heikin Ashi: {ha_trend}")
        
        if ict.get('fair_value_gaps'):
            parts.append("FVG detected")
        if ict.get('order_blocks'):
            parts.append("Order Block active")
        
        trend = structure.get('trend', '')
        if trend != 'NEUTRAL':
            parts.append(f"Trend: {trend}")
        
        if signal == "STRONG_BUY":
            base = "🟢 STRONG BUY - Multiple bullish signals"
        elif signal == "BUY":
            base = "🟢 BUY - Bullish bias"
        elif signal == "STRONG_SELL":
            base = "🔴 STRONG SELL - Multiple bearish signals"
        elif signal == "SELL":
            base = "🔴 SELL - Bearish bias"
        else:
            base = "⚪ NEUTRAL - No clear bias"
        
        parts.insert(0, base)
        
        if conf > 70:
            parts.append(f"High confidence ({conf:.0f}%)")
        elif conf > 60:
            parts.append(f"Moderate confidence ({conf:.0f}%)")
        else:
            parts.append(f"Low confidence ({conf:.0f}%)")
        
        return ". ".join(parts) + "."

# ========================================================================================================
# FASTAPI APPLICATION
# ========================================================================================================
app = FastAPI(
    title="ICTSMARTPRO v9.0",
    description="AI-Powered Crypto Analysis with ICT & Heikin Ashi",
    version="9.0.0",
    docs_url="/docs" if Config.DEBUG else None,
    redoc_url=None
)

# CORS - Güvenli yapılandırma
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
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>ICTSMARTPRO AI v9.0</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                   margin: 40px; background: #0a0b0d; color: #e0e0e0; line-height: 1.6; }
            .container { max-width: 800px; margin: 0 auto; }
            h1 { color: #00ff88; border-bottom: 2px solid #333; padding-bottom: 10px; }
            .status { background: #1a1c20; padding: 20px; border-radius: 10px; margin: 20px 0; 
                      border-left: 4px solid #00ff88; }
            .feature { background: #222; padding: 15px; margin: 10px 0; border-radius: 8px; 
                      border-left: 4px solid #2563eb; }
            .endpoint { background: #2a2c30; padding: 10px; border-radius: 5px; 
                       font-family: monospace; }
            a { color: #00ff88; text-decoration: none; }
            a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 ICTSMARTPRO AI v9.0</h1>
            <div class="status">
                <strong>✅ SYSTEM ONLINE</strong><br>
                Kraken • Binance • MEXC • Yahoo Finance
            </div>
            <div class="feature">
                <strong>📊 ICT PATTERNS</strong><br>
                Fair Value Gaps • Order Blocks • Break of Structure • Change of Character • Liquidity Sweeps
            </div>
            <div class="feature">
                <strong>🕯️ HEIKIN ASHI + CANDLESTICK PATTERNS</strong><br>
                Doji • Hammer • Engulfing • Morning/Evening Star • Three Soldiers/Crows
            </div>
            <div class="endpoint">
                <a href="/docs">📚 API Documentation</a> • 
                <a href="/health">🔍 Health Check</a> • 
                <a href="/api/exchanges">🌐 Exchange Status</a>
            </div>
        </div>
    </body>
    </html>
    """)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    uptime = time.time() - startup_time
    active_sources = data_fetcher.get_active_sources()
    return {
        "status": "healthy",
        "version": "9.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": int(uptime),
        "uptime_human": str(timedelta(seconds=int(uptime))),  # ✅ timedelta ÇALIŞIYOR
        "active_sources": active_sources,
        "max_confidence": Config.MAX_CONFIDENCE,
        "environment": Config.ENV,
        "debug": Config.DEBUG
    }

@app.get("/api/analyze/{symbol}", response_model=AnalysisResponse)
async def analyze_symbol(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1m|5m|15m|30m|1h|4h|1d|1w)$"),
    limit: int = Query(default=100, ge=30, le=500)
):
    """Complete market analysis with ICT, Heikin Ashi, and candlestick patterns"""
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    
    logger.info(f"🔍 Analyzing {symbol} ({interval})")
    
    try:
        async with data_fetcher as fetcher:
            candles = await fetcher.get_candles(symbol, interval, limit)
        
        if not candles or len(candles) < Config.MIN_CANDLES:
            raise HTTPException(
                status_code=422,
                detail=f"Insufficient data. Got {len(candles) if candles else 0} candles"
            )
        
        # DataFrame oluştur
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp')
        
        # Analizler
        technical = TechnicalAnalyzer.analyze(df)
        ict_patterns = ICTPatternDetector.analyze(df)
        candle_patterns = CandlestickPatternDetector.analyze(df)
        market_structure = MarketStructureAnalyzer.analyze(df)
        
        # Sinyal üret
        signal = SignalGenerator.generate(
            technical,
            market_structure,
            ict_patterns,
            candle_patterns
        )
        
        # Aktif kaynaklar
        active_sources = list(df['sources'].iloc[0]) if 'sources' in df.columns else []
        
        response = {
            "success": True,
            "symbol": symbol,
            "interval": interval,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": {
                "current": round(float(df['close'].iloc[-1]), 2),
                "open": round(float(df['open'].iloc[-1]), 2),
                "high": round(float(df['high'].iloc[-1]), 2),
                "low": round(float(df['low'].iloc[-1]), 2),
                "volume": float(df['volume'].sum()),
                "change_24h": round(float((df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100), 2)
            },
            "signal": signal,
            "technical": technical,
            "ict_patterns": ict_patterns,
            "candle_patterns": candle_patterns[-10:],
            "market_structure": market_structure,
            "active_sources": active_sources,
            "data_points": len(df)
        }
        
        logger.info(f"✅ {symbol} | {signal['signal']} ({signal['confidence']:.1f}%)")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Analysis failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e)[:200])

@app.get("/api/price/{symbol}")
async def get_price(symbol: str):
    """Get current price only (fast)"""
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
    """Get exchange status with statistics"""
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
    """Get raw exchange statistics"""
    stats = data_fetcher.get_stats()
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stats": stats
    }

@app.websocket("/wss/{symbol}")
async def websocket_endpoint(websocket: WebSocket, symbol: str):
    """WebSocket for real-time price updates (WSS)"""
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

# ========================================================================================================
# STARTUP & SHUTDOWN EVENTS
# ========================================================================================================
@app.on_event("startup")
async def startup_event():
    logger.info("=" * 60)
    logger.info("🚀 ICTSMARTPRO v9.0 STARTED")
    logger.info("=" * 60)
    logger.info(f"Environment: {Config.ENV}")
    logger.info(f"Debug Mode: {Config.DEBUG}")
    logger.info(f"Sources: Kraken, Binance, MEXC, Yahoo")
    logger.info(f"ICT Patterns: FVG, OB, BOS, CHoCH, Liquidity Sweep")
    logger.info(f"Heikin Ashi: Enabled")
    logger.info(f"Candlestick: 15+ patterns")
    logger.info(f"Max Confidence: {Config.MAX_CONFIDENCE}%")
    logger.info(f"Cache TTL: {Config.CACHE_TTL}s")
    logger.info("=" * 60)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Shutting down ICTSMARTPRO v9.0...")
    # WebSocket'leri kapat
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
        log_level="info",
        access_log=True
    )
