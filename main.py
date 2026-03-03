import sys
import json
import time
import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
from contextlib import asynccontextmanager
from enum import Enum

import numpy as np
import pandas as pd
import yfinance as yf

from fastapi import FastAPI, Request, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

import aiohttp
from aiohttp import ClientTimeout, TCPConnector


# ========================================================================================================
# LOGGING SETUP
# ========================================================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("ictsmartpro")


# ========================================================================================================
# CONFIGURATION
# ========================================================================================================
class Config:
    ENV = os.getenv("ENV", "production")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    PORT = int(os.getenv("PORT", 8000))
    
    API_TIMEOUT = int(os.getenv("API_TIMEOUT", "10"))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
    
    MIN_CANDLES = int(os.getenv("MIN_CANDLES", "30"))
    MIN_EXCHANGES = int(os.getenv("MIN_EXCHANGES", "1"))
    
    CACHE_TTL = int(os.getenv("CACHE_TTL", "30"))
    
    MAX_CONFIDENCE = float(os.getenv("MAX_CONFIDENCE", "85.0"))
    DEFAULT_CONFIDENCE = float(os.getenv("DEFAULT_CONFIDENCE", "51.5"))
    
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
    ICTSMARTPRO = "ictsmartpro"
    CLASSICAL = "classical"
    PRICE_ACTION = "price_action"


# ========================================================================================================
# EXCHANGE DATA FETCHER (ÇALIŞAN VERSİYON)
# ========================================================================================================
class ExchangeDataFetcher:
    EXCHANGES = [
        {
            "name": "Binance",
            "weight": 1.00,
            "base_url": "https://api.binance.com/api/v3/klines",
            "symbol_fmt": lambda s: s.upper().replace("/", ""),
            "interval_map": {
                "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
            },
            "parser": "binance",
            "timeout": 5
        },
        {
            "name": "MEXC",
            "weight": 0.98,
            "base_url": "https://api.mexc.com/api/v3/klines",
            "symbol_fmt": lambda s: s.upper().replace("/", ""),
            "interval_map": {
                "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
            },
            "parser": "binance",
            "timeout": 5
        },
        {
            "name": "Kraken",
            "weight": 0.95,
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
            "name": "Yahoo",
            "weight": 0.85,
            "base_url": "https://query1.finance.yahoo.com/v8/finance/chart/",
            "symbol_fmt": lambda s: s.replace("USDT", "-USD") if "USDT" in s else s,
            "interval_map": {
                "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                "1h": "60m", "4h": "60m", "1d": "1d", "1w": "1wk"
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

    async def __aenter__(self):
        timeout = ClientTimeout(total=Config.API_TIMEOUT)
        connector = TCPConnector(limit=20, limit_per_host=5, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": "ICTSMARTPRO-Bot/9.0"}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _get_cache_key(self, symbol: str, interval: str) -> str:
        return f"{symbol}_{interval}"

    def _is_cache_valid(self, key: str) -> bool:
        if key not in self.cache_time:
            return False
        return (time.time() - self.cache_time[key]) < Config.CACHE_TTL

    async def _fetch_exchange(self, exchange: Dict, symbol: str, interval: str, limit: int) -> Optional[List[Dict]]:
        name = exchange["name"]
        
        try:
            if interval not in exchange["interval_map"]:
                return None

            ex_interval = exchange["interval_map"][interval]
            formatted_symbol = exchange["symbol_fmt"](symbol)

            if name == "Yahoo":
                # Yahoo Finance özel işlem
                try:
                    yahoo_symbol = formatted_symbol
                    ticker = yf.Ticker(yahoo_symbol)
                    
                    # Interval'e göre period belirle
                    if interval in ["1m", "5m", "15m", "30m"]:
                        period = "5d"
                    elif interval in ["1h", "4h"]:
                        period = "1mo"
                    else:
                        period = "3mo"
                    
                    data = ticker.history(period=period, interval=ex_interval)
                    
                    if data.empty:
                        return None
                    
                    candles = []
                    for idx, row in data.iterrows():
                        candles.append({
                            "timestamp": int(idx.timestamp() * 1000),
                            "open": float(row["Open"]),
                            "high": float(row["High"]),
                            "low": float(row["Low"]),
                            "close": float(row["Close"]),
                            "volume": float(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
                            "exchange": name
                        })
                    
                    return candles[-limit:]
                    
                except Exception as e:
                    logger.debug(f"Yahoo error for {symbol}: {str(e)}")
                    return None
            
            else:
                # Kripto borsaları
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
                    
                    if name in ["Binance", "MEXC"]:
                        candles = []
                        for item in data:
                            if len(item) >= 6:
                                candles.append({
                                    "timestamp": int(item[0]),
                                    "open": float(item[1]),
                                    "high": float(item[2]),
                                    "low": float(item[3]),
                                    "close": float(item[4]),
                                    "volume": float(item[5]),
                                    "exchange": name
                                })
                        return candles
                    
                    elif name == "Kraken":
                        candles = []
                        if isinstance(data, dict) and "result" in data:
                            result = data["result"]
                            for key, values in result.items():
                                if isinstance(values, list) and key != "last":
                                    for item in values:
                                        if len(item) >= 6:
                                            candles.append({
                                                "timestamp": int(item[0]) * 1000,
                                                "open": float(item[1]),
                                                "high": float(item[2]),
                                                "low": float(item[3]),
                                                "close": float(item[4]),
                                                "volume": float(item[6]),
                                                "exchange": name
                                            })
                                    break
                        return candles

        except asyncio.TimeoutError:
            self.stats[name]["fail"] += 1
            self.stats[name]["last_error"] = "Timeout"
        except Exception as e:
            self.stats[name]["fail"] += 1
            self.stats[name]["last_error"] = str(e)[:50]
        
        return None

    def _aggregate_candles(self, all_candles: List[List[Dict]], interval: str) -> List[Dict]:
        """Mum verilerini birleştir"""
        if not all_candles:
            return []
        
        # Interval'i milisaniyeye çevir
        interval_ms = {
            "1m": 60000, "5m": 300000, "15m": 900000, "30m": 1800000,
            "1h": 3600000, "4h": 14400000, "1d": 86400000, "1w": 604800000
        }.get(interval, 3600000)
        
        # Timestamp'leri yuvarla
        timestamp_map = defaultdict(list)
        
        for exchange_data in all_candles:
            for candle in exchange_data:
                rounded_ts = (candle["timestamp"] // interval_ms) * interval_ms
                candle["rounded_timestamp"] = rounded_ts
                timestamp_map[rounded_ts].append(candle)
        
        aggregated = []
        for timestamp in sorted(timestamp_map.keys())[-200:]:  # Son 200
            candles = timestamp_map[timestamp]
            
            total_weight = 0
            open_sum = high_sum = low_sum = close_sum = volume_sum = 0
            sources = []
            
            for candle in candles:
                # Exchange weight'ini bul
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
                    "sources": sources
                })
        
        return aggregated

    async def get_candles(self, symbol: str, interval: str = "1h", limit: int = 200) -> List[Dict]:
        cache_key = self._get_cache_key(symbol, interval)

        # Cache kontrolü
        if self._is_cache_valid(cache_key):
            cached = self.cache.get(cache_key, [])
            if cached and len(cached) >= Config.MIN_CANDLES:
                logger.info(f"📦 CACHE: {symbol} ({interval}) - {len(cached)} candles")
                return cached[-limit:]

        logger.info(f"🔄 FETCH: {symbol} @ {interval}")

        tasks = [
            self._fetch_exchange(exchange, symbol, interval, limit)
            for exchange in self.EXCHANGES
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results = []
        for i, r in enumerate(results):
            exchange_name = self.EXCHANGES[i]["name"]
            if isinstance(r, list) and len(r) >= 5:
                valid_results.append(r)
                self.stats[exchange_name]["success"] += 1
                self.stats[exchange_name]["last_success"] = time.time()
                self.stats[exchange_name]["last_error"] = ""
                logger.debug(f"✅ {exchange_name}: {len(r)} candles")
            elif isinstance(r, Exception):
                logger.debug(f"❌ {exchange_name} error: {str(r)[:50]}")
            else:
                logger.debug(f"⚠️ {exchange_name}: insufficient data")

        if not valid_results:
            logger.warning(f"⚠️ No data from any exchange for {symbol}")
            return []

        aggregated = self._aggregate_candles(valid_results, interval)

        if len(aggregated) < Config.MIN_CANDLES:
            logger.warning(f"⚠️ Only {len(aggregated)} candles (min: {Config.MIN_CANDLES})")
            return aggregated  # Yine de döndür

        self.cache[cache_key] = aggregated
        self.cache_time[cache_key] = time.time()

        logger.info(f"✅ {symbol}: {len(aggregated)} candles from {len(valid_results)} sources")
        
        return aggregated[-limit:]

    async def get_current_price(self, symbol: str) -> Optional[float]:
        # Cache kontrolü
        if symbol in self.price_cache:
            if time.time() - self.price_cache[symbol].get("time", 0) < 10:
                return self.price_cache[symbol].get("price")

        # Binance'ten dene
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
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
            url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
            async with self.session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    price = float(data['price'])
                    self.price_cache[symbol] = {"price": price, "time": time.time()}
                    return price
        except:
            pass

        # Yahoo'dan dene (kripto değilse)
        if "USDT" not in symbol:
            try:
                yahoo_symbol = symbol.replace("USDT", "-USD") if "USDT" in symbol else symbol
                ticker = yf.Ticker(yahoo_symbol)
                data = ticker.history(period="1d", interval="1m")
                if not data.empty:
                    price = float(data["Close"].iloc[-1])
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
            if stats.get("last_success", 0) > now - 300:  # Son 5 dakika
                active.append(name)
        return active


# ========================================================================================================
# ML MODEL SIMULATOR (FRONTEND İÇİN)
# ========================================================================================================
class MLModelSimulator:
    """Gerçek ML modelleri yok, frontend için simülasyon"""
    
    @staticmethod
    def generate_scores(confidence: float) -> Dict[str, float]:
        """ML model skorları üret"""
        base = confidence
        
        return {
            "lightgbm": min(95, max(30, base + np.random.normal(0, 5))),
            "xgboost": min(95, max(30, base + np.random.normal(-2, 6))),
            "transformer": min(95, max(30, base + np.random.normal(5, 8))),
            "random_forest": min(95, max(30, base + np.random.normal(-1, 4)))
        }


# ========================================================================================================
# DATA PREPARATION
# ========================================================================================================
def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Temel indikatörleri hesapla"""
    df = df.copy()
    
    # Temel mum özellikleri
    df['is_bullish'] = df['close'] > df['open']
    df['is_bearish'] = df['close'] < df['open']
    df['body'] = abs(df['close'] - df['open'])
    df['range'] = df['high'] - df['low']
    
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
    
    # NaN'ları temizle
    df = df.ffill().bfill()
    
    return df


# ========================================================================================================
# MARKET STRUCTURE ANALYZER
# ========================================================================================================
class MarketStructureAnalyzer:
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> Dict[str, Any]:
        if len(df) < 20:
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
        
        # Basit trend belirleme
        sma_20 = close.rolling(20).mean()
        sma_50 = close.rolling(50).mean()
        
        if close.iloc[-1] > sma_20.iloc[-1] > sma_50.iloc[-1]:
            trend = "UPTREND"
            trend_strength = "MODERATE"
            structure = "Bullish"
        elif close.iloc[-1] < sma_20.iloc[-1] < sma_50.iloc[-1]:
            trend = "DOWNTREND"
            trend_strength = "MODERATE"
            structure = "Bearish"
        else:
            trend = "NEUTRAL"
            trend_strength = "WEAK"
            structure = "Neutral"
        
        # Volatilite
        atr = df['atr'].iloc[-1]
        avg_atr = df['atr'].rolling(20).mean().iloc[-1]
        
        if pd.isna(avg_atr) or avg_atr == 0:
            vol_regime = "NORMAL"
            vol_index = 100
        elif atr > avg_atr * 1.5:
            vol_regime = "HIGH"
            vol_index = 150
        elif atr < avg_atr * 0.7:
            vol_regime = "LOW"
            vol_index = 70
        else:
            vol_regime = "NORMAL"
            vol_index = 100
        
        # Momentum
        mom_5 = (close.iloc[-1] / close.iloc[-5] - 1) if len(close) >= 5 else 0
        if mom_5 > 0.02:
            momentum = "Bullish"
        elif mom_5 < -0.02:
            momentum = "Bearish"
        else:
            momentum = "Neutral"
        
        return {
            "trend": trend,
            "trend_strength": trend_strength,
            "structure": structure,
            "swings": {"hh": [], "hl": [], "lh": [], "ll": []},
            "support_resistance": [],
            "volatility": vol_regime,
            "volatility_index": vol_index,
            "momentum": momentum,
            "current_price": float(close.iloc[-1])
        }


# ========================================================================================================
# ICT PATTERN DETECTOR (BASİT VERSİYON)
# ========================================================================================================
class ICTPatternDetector:
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> Dict[str, List[Dict]]:
        patterns = {
            "fair_value_gaps": [],
            "order_blocks": [],
            "liquidity_sweeps": [],
            "break_of_structure": []
        }
        
        if len(df) < 10:
            return patterns
        
        # FVG tespiti
        for i in range(1, len(df) - 1):
            # Bullish FVG
            if df['low'].iloc[i + 1] > df['high'].iloc[i - 1]:
                gap_size = (df['low'].iloc[i + 1] - df['high'].iloc[i - 1]) / df['high'].iloc[i - 1] * 100
                patterns["fair_value_gaps"].append({
                    "pattern": "bullish_fvg",
                    "direction": "bullish",
                    "strength": min(round(gap_size * 10, 1), 80),
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "description": f"Bullish FVG at {gap_size:.2f}%"
                })
            
            # Bearish FVG
            elif df['high'].iloc[i + 1] < df['low'].iloc[i - 1]:
                gap_size = (df['low'].iloc[i - 1] - df['high'].iloc[i + 1]) / df['low'].iloc[i - 1] * 100
                patterns["fair_value_gaps"].append({
                    "pattern": "bearish_fvg",
                    "direction": "bearish",
                    "strength": min(round(gap_size * 10, 1), 80),
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "description": f"Bearish FVG at {gap_size:.2f}%"
                })
        
        # Order Block tespiti (basit)
        for i in range(2, len(df) - 2):
            if (df['is_bullish'].iloc[i] and 
                df['is_bearish'].iloc[i-1] and 
                df['low'].iloc[i] < df['low'].iloc[i-1]):
                patterns["order_blocks"].append({
                    "pattern": "bullish_order_block",
                    "direction": "bullish",
                    "strength": 70,
                    "timestamp": str(df.index[i-1]),
                    "price": float(df['close'].iloc[i]),
                    "description": "Bullish Order Block"
                })
            
            if (df['is_bearish'].iloc[i] and 
                df['is_bullish'].iloc[i-1] and 
                df['high'].iloc[i] > df['high'].iloc[i-1]):
                patterns["order_blocks"].append({
                    "pattern": "bearish_order_block",
                    "direction": "bearish",
                    "strength": 70,
                    "timestamp": str(df.index[i-1]),
                    "price": float(df['close'].iloc[i]),
                    "description": "Bearish Order Block"
                })
        
        return patterns


# ========================================================================================================
# ICTSMARTPRO STRATEJİSİ
# ========================================================================================================
class ICTSmartProDetector:
    
    @staticmethod
    def detect(df: pd.DataFrame, market_structure: Dict) -> List[Dict]:
        signals = []
        
        if len(df) < 20:
            return signals
        
        current_price = df['close'].iloc[-1]
        
        # Basit trend bazlı sinyaller
        sma_20 = df['close'].rolling(20).mean().iloc[-1]
        sma_50 = df['close'].rolling(50).mean().iloc[-1]
        
        # Altın haç (bullish)
        if sma_20 > sma_50 and df['close'].iloc[-1] > sma_20:
            signals.append({
                "pattern": "ictsmartpro_golden_cross",
                "direction": "bullish",
                "strength": 75,
                "timestamp": str(df.index[-1]),
                "price": float(current_price),
                "sl_level": float(sma_50 * 0.98),
                "tp_level": float(current_price * 1.05),
                "description": "ICTSMARTPRO BUY - Golden Cross"
            })
        
        # Ölüm haçı (bearish)
        elif sma_20 < sma_50 and df['close'].iloc[-1] < sma_20:
            signals.append({
                "pattern": "ictsmartpro_death_cross",
                "direction": "bearish",
                "strength": 75,
                "timestamp": str(df.index[-1]),
                "price": float(current_price),
                "sl_level": float(sma_50 * 1.02),
                "tp_level": float(current_price * 0.95),
                "description": "ICTSMARTPRO SELL - Death Cross"
            })
        
        # RSI bazlı sinyaller
        rsi = df['rsi'].iloc[-1]
        if rsi < 30:
            signals.append({
                "pattern": "ictsmartpro_rsi_oversold",
                "direction": "bullish",
                "strength": 70,
                "timestamp": str(df.index[-1]),
                "price": float(current_price),
                "sl_level": float(current_price * 0.97),
                "tp_level": float(current_price * 1.03),
                "description": "ICTSMARTPRO BUY - RSI Oversold"
            })
        elif rsi > 70:
            signals.append({
                "pattern": "ictsmartpro_rsi_overbought",
                "direction": "bearish",
                "strength": 70,
                "timestamp": str(df.index[-1]),
                "price": float(current_price),
                "sl_level": float(current_price * 1.03),
                "tp_level": float(current_price * 0.97),
                "description": "ICTSMARTPRO SELL - RSI Overbought"
            })
        
        return signals[-5:]


# ========================================================================================================
# CLASSICAL PATTERN DETECTOR
# ========================================================================================================
class ClassicalPatternDetector:
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> List[Dict]:
        patterns = []
        
        if len(df) < 30:
            return patterns
        
        # Double Top/Bottom (basit)
        for i in range(20, len(df)):
            high1 = df['high'].iloc[i-15:i-5].max()
            high2 = df['high'].iloc[i-5:i].max()
            
            if abs(high1 - high2) / high1 < 0.02 and df['close'].iloc[i] < high2 * 0.98:
                patterns.append({
                    "pattern": "double_top",
                    "direction": "bearish",
                    "strength": 72,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "description": "Double Top - Bearish reversal"
                })
            
            low1 = df['low'].iloc[i-15:i-5].min()
            low2 = df['low'].iloc[i-5:i].min()
            
            if abs(low1 - low2) / low1 < 0.02 and df['close'].iloc[i] > low2 * 1.02:
                patterns.append({
                    "pattern": "double_bottom",
                    "direction": "bullish",
                    "strength": 72,
                    "timestamp": str(df.index[i]),
                    "price": float(df['close'].iloc[i]),
                    "description": "Double Bottom - Bullish reversal"
                })
        
        return patterns[-10:]


# ========================================================================================================
# CANDLESTICK PATTERN DETECTOR
# ========================================================================================================
class CandlestickPatternDetector:
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> List[Dict]:
        patterns = []
        
        if len(df) < 5:
            return patterns
        
        for i in range(1, len(df)):
            curr = df.iloc[i]
            prev = df.iloc[i-1]
            
            # Doji
            if curr['range'] > 0 and (curr['body'] / curr['range']) < 0.1:
                patterns.append({
                    "pattern": "doji",
                    "direction": "neutral",
                    "strength": 50,
                    "timestamp": str(df.index[i]),
                    "price": float(curr['close']),
                    "description": "Doji - Indecision"
                })
            
            # Hammer
            if (curr['is_bullish'] and 
                curr['lower_shadow'] > curr['body'] * 2 and 
                curr['upper_shadow'] < curr['body']):
                patterns.append({
                    "pattern": "hammer",
                    "direction": "bullish",
                    "strength": 70,
                    "timestamp": str(df.index[i]),
                    "price": float(curr['close']),
                    "description": "Hammer - Bullish reversal"
                })
            
            # Shooting Star
            if (curr['is_bearish'] and 
                curr['upper_shadow'] > curr['body'] * 2 and 
                curr['lower_shadow'] < curr['body']):
                patterns.append({
                    "pattern": "shooting_star",
                    "direction": "bearish",
                    "strength": 70,
                    "timestamp": str(df.index[i]),
                    "price": float(curr['close']),
                    "description": "Shooting Star - Bearish reversal"
                })
            
            # Bullish Engulfing
            if (curr['is_bullish'] and prev['is_bearish'] and
                curr['open'] < prev['close'] and curr['close'] > prev['open']):
                patterns.append({
                    "pattern": "bullish_engulfing",
                    "direction": "bullish",
                    "strength": 75,
                    "timestamp": str(df.index[i]),
                    "price": float(curr['close']),
                    "description": "Bullish Engulfing"
                })
            
            # Bearish Engulfing
            if (curr['is_bearish'] and prev['is_bullish'] and
                curr['open'] > prev['close'] and curr['close'] < prev['open']):
                patterns.append({
                    "pattern": "bearish_engulfing",
                    "direction": "bearish",
                    "strength": 75,
                    "timestamp": str(df.index[i]),
                    "price": float(curr['close']),
                    "description": "Bearish Engulfing"
                })
        
        return patterns[-20:]


# ========================================================================================================
# TECHNICAL ANALYZER
# ========================================================================================================
class TechnicalAnalyzer:
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> Dict[str, Any]:
        if len(df) < 20:
            return {}
        
        close = df['close']
        
        # Heikin Ashi hesapla
        ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        
        ha_open = ha_close.copy()
        for i in range(1, len(ha_open)):
            ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2
        
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
        
        # RSI
        rsi = df['rsi'].iloc[-1] if 'rsi' in df.columns else 50
        
        # MACD
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd - signal
        
        # Bollinger
        bb_position = df['bb_position'].iloc[-1] if 'bb_position' in df.columns else 50
        
        # ATR
        atr = df['atr'].iloc[-1] if 'atr' in df.columns else (df['high'] - df['low']).rolling(14).mean().iloc[-1]
        atr_percent = (atr / close.iloc[-1] * 100) if close.iloc[-1] > 0 else 0
        
        # Volume ratio
        volume_ratio = df['volume_ratio'].iloc[-1] if 'volume_ratio' in df.columns else 1.0
        
        # SMA
        sma_20 = close.rolling(20).mean().iloc[-1]
        sma_50 = close.rolling(50).mean().iloc[-1]
        
        # Momentum
        mom_5 = (close.iloc[-1] / close.iloc[-5] - 1) * 100 if len(close) >= 5 else 0
        mom_10 = (close.iloc[-1] / close.iloc[-10] - 1) * 100 if len(close) >= 10 else 0
        
        return {
            "rsi": round(float(rsi), 1),
            "macd": round(float(macd.iloc[-1]), 2),
            "macd_signal": round(float(signal.iloc[-1]), 2),
            "macd_histogram": round(float(macd_hist.iloc[-1]), 2),
            "bb_position": round(float(bb_position), 1),
            "bb_width": round(float((df['bb_upper'].iloc[-1] - df['bb_lower'].iloc[-1]) / sma_20 * 100), 1),
            "atr": round(float(atr), 2),
            "atr_percent": round(float(atr_percent), 2),
            "volume_ratio": round(float(volume_ratio), 2),
            "sma_20": round(float(sma_20), 2),
            "sma_50": round(float(sma_50), 2),
            "price_vs_sma20": round(float((close.iloc[-1] / sma_20 - 1) * 100), 1),
            "price_vs_sma50": round(float((close.iloc[-1] / sma_50 - 1) * 100), 1),
            "momentum_5": round(float(mom_5), 2),
            "momentum_10": round(float(mom_10), 2),
            "ha_trend": ha_trend,
            "ha_trend_strength": round(min(ha_strength, 100), 1),
            "ha_close": round(float(ha_close.iloc[-1]), 2),
            "ha_rsi": round(float(rsi), 1),
            "ha_momentum": round(float((ha_close.iloc[-1] / ha_close.iloc[-5] - 1) * 100), 2)
        }


# ========================================================================================================
# SIGNAL GENERATOR
# ========================================================================================================
class SignalGenerator:
    
    @staticmethod
    def generate(
        technical: Dict[str, Any],
        market_structure: Dict[str, Any],
        ict_patterns: Dict[str, List[Dict]],
        candle_patterns: List[Dict],
        classical_patterns: List[Dict],
        ictsmartpro_signals: List[Dict]
    ) -> Dict[str, Any]:
        
        buy_signals = 0
        sell_signals = 0
        total_confidence = 0
        
        # ICTSMARTPRO sinyalleri
        for sig in ictsmartpro_signals:
            if sig['direction'] in ['bullish', 'bullish_reversal']:
                buy_signals += 2
                total_confidence += sig.get('strength', 70) * 2
            else:
                sell_signals += 2
                total_confidence += sig.get('strength', 70) * 2
        
        # ICT pattern'leri
        for pattern_list in ict_patterns.values():
            for pattern in pattern_list[:3]:
                if pattern['direction'] in ['bullish', 'bullish_reversal']:
                    buy_signals += 1
                    total_confidence += pattern.get('strength', 60)
                else:
                    sell_signals += 1
                    total_confidence += pattern.get('strength', 60)
        
        # Candlestick pattern'leri
        for pattern in candle_patterns[:5]:
            if pattern['direction'] in ['bullish', 'bullish_reversal']:
                buy_signals += 1
                total_confidence += pattern.get('strength', 50)
            elif pattern['direction'] in ['bearish', 'bearish_reversal']:
                sell_signals += 1
                total_confidence += pattern.get('strength', 50)
        
        # RSI
        rsi = technical.get('rsi', 50)
        if rsi < 30:
            buy_signals += 1
            total_confidence += 60
        elif rsi > 70:
            sell_signals += 1
            total_confidence += 60
        
        # MACD
        macd_hist = technical.get('macd_histogram', 0)
        if macd_hist > 0:
            buy_signals += 1
            total_confidence += 55
        elif macd_hist < 0:
            sell_signals += 1
            total_confidence += 55
        
        # Heikin Ashi
        ha_trend = technical.get('ha_trend', '')
        if 'BULLISH' in ha_trend:
            buy_signals += 1
            total_confidence += 65
        elif 'BEARISH' in ha_trend:
            sell_signals += 1
            total_confidence += 65
        
        total_signals = buy_signals + sell_signals
        if total_signals == 0:
            return {
                "signal": "NEUTRAL",
                "confidence": Config.DEFAULT_CONFIDENCE,
                "recommendation": "No clear signals",
                "buy_count": 0,
                "sell_count": 0,
                "tp_level": None,
                "sl_level": None
            }
        
        avg_confidence = total_confidence / total_signals
        avg_confidence = min(avg_confidence, Config.MAX_CONFIDENCE)
        
        if buy_signals > sell_signals * 1.5:
            signal = "STRONG_BUY" if avg_confidence > 75 else "BUY"
        elif sell_signals > buy_signals * 1.5:
            signal = "STRONG_SELL" if avg_confidence > 75 else "SELL"
        elif buy_signals > sell_signals:
            signal = "BUY"
        elif sell_signals > buy_signals:
            signal = "SELL"
        else:
            signal = "NEUTRAL"
        
        # TP/SL seviyeleri
        tp_level = None
        sl_level = None
        
        if ictsmartpro_signals:
            best = max(ictsmartpro_signals, key=lambda x: x.get('strength', 0))
            tp_level = best.get('tp_level')
            sl_level = best.get('sl_level')
        
        rec = f"Signals: B{buy_signals} S{sell_signals}. Confidence: {avg_confidence:.0f}%"
        
        return {
            "signal": signal,
            "confidence": round(avg_confidence, 1),
            "recommendation": rec,
            "buy_count": buy_signals,
            "sell_count": sell_signals,
            "tp_level": tp_level,
            "sl_level": sl_level
        }


# ========================================================================================================
# FASTAPI APPLICATION
# ========================================================================================================
app = FastAPI(
    title="ICTSMARTPRO v9.0",
    description="AI-Powered Crypto Analysis",
    version="9.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.add_middleware(GZipMiddleware, minimum_size=500)

# Global instances
data_fetcher = ExchangeDataFetcher()
ml_simulator = MLModelSimulator()
startup_time = time.time()


# ========================================================================================================
# API ENDPOINTS
# ========================================================================================================
@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(content="""
    <html>
        <body style="background:#0a0b0d; color:#e0e0e0; padding:40px; font-family:monospace;">
            <h1 style="color:#3b82f6;">ICTSMARTPRO v9.0</h1>
            <p>✅ Backend çalışıyor</p>
            <p><a href="/health" style="color:#22d3ee;">Health Check</a></p>
            <p><a href="/dashboard" style="color:#22d3ee;">Dashboard</a></p>
        </body>
    </html>
    """)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    
    if os.path.exists(html_path):
        return FileResponse(html_path)
    
    return HTMLResponse(content=f"""
    <html>
        <body style="background:#0a0b0d; color:#e0e0e0; padding:40px;">
            <h1 style="color:#ff4444;">❌ dashboard.html bulunamadı</h1>
            <p>Dosyayı şuraya koyun: {html_path}</p>
        </body>
    </html>
    """, status_code=404)


@app.get("/health")
async def health_check():
    uptime = time.time() - startup_time
    return {
        "status": "healthy",
        "version": "9.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_human": str(timedelta(seconds=int(uptime)))
    }


@app.get("/api/analyze/{symbol}")
async def analyze_symbol(
    symbol: str,
    interval: str = Query("1h", regex="^(1m|5m|15m|30m|1h|4h|1d|1w)$"),
    limit: int = Query(200, ge=30, le=500)
):
    original_symbol = symbol.upper()
    symbol = original_symbol
    
    if not symbol.endswith("USDT") and symbol not in ["XAU", "XAG", "EURUSD", "GBPUSD", "USDTRY"]:
        symbol = f"{symbol}USDT"
    
    logger.info(f"🔍 Analyzing {symbol} @ {interval}")
    
    start_time = time.time()
    
    try:
        async with data_fetcher as fetcher:
            candles = await fetcher.get_candles(symbol, interval, limit)
            exchange_stats = fetcher.get_stats()
        
        if not candles:
            raise HTTPException(422, f"No data for {symbol}")
        
        # DataFrame hazırla
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp').sort_index()
        df_prepared = prepare_dataframe(df)
        
        # Analizleri yap
        market_structure = MarketStructureAnalyzer.analyze(df_prepared)
        technical = TechnicalAnalyzer.analyze(df_prepared)
        ict_patterns = ICTPatternDetector.analyze(df_prepared)
        candle_patterns = CandlestickPatternDetector.analyze(df_prepared)
        classical_patterns = ClassicalPatternDetector.analyze(df_prepared)
        ictsmartpro_signals = ICTSmartProDetector.detect(df_prepared, market_structure)
        
        # Signal oluştur
        signal = SignalGenerator.generate(
            technical, market_structure, ict_patterns,
            candle_patterns, classical_patterns, ictsmartpro_signals
        )
        
        # Son mum verileri
        last_row = df_prepared.iloc[-1]
        first_row = df_prepared.iloc[0]
        volume_sum = float(df_prepared["volume"].sum())
        
        # 24h hacim tahmini
        interval_multipliers = {
            "1m": 1440, "5m": 288, "15m": 96, "30m": 48,
            "1h": 24, "4h": 6, "1d": 1, "1w": 0.14
        }
        volume_24h = volume_sum * interval_multipliers.get(interval, 24)
        
        # Aktif kaynaklar
        active_sources = fetcher.get_active_sources()
        
        # ML skorları (simülasyon)
        ml_scores = ml_simulator.generate_scores(signal['confidence'])
        
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
                "change_percent": round((last_row["close"] / first_row["close"] - 1) * 100, 2),
                "change_24h": round((last_row["close"] / df_prepared.iloc[-min(24, len(df_prepared))]["close"] - 1) * 100, 2)
            },
            "signal": signal,
            "technical": technical,
            "ict_patterns": ict_patterns,
            "candle_patterns": candle_patterns[-20:],
            "classical_patterns": classical_patterns[-10:],
            "ictsmartpro_signals": ictsmartpro_signals,
            "market_structure": market_structure,
            "active_sources": active_sources,
            "data_points": len(df_prepared),
            "ml_scores": ml_scores,
            "exchange_stats": exchange_stats,
            "performance_ms": round((time.time() - start_time) * 1000, 2)
        }
        
        logger.info(f"✅ {symbol} @ {interval} | {signal['signal']} ({signal['confidence']:.0f}%) | {len(df_prepared)} candles")
        
        return response
        
    except Exception as e:
        logger.exception(f"❌ Error: {str(e)}")
        raise HTTPException(500, f"Analysis failed: {str(e)[:200]}")


@app.get("/api/price/{symbol}")
async def get_price(symbol: str):
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    
    async with data_fetcher as fetcher:
        price = await fetcher.get_current_price(symbol)
    
    if price is None:
        raise HTTPException(404, "Price not available")
    
    return {
        "symbol": symbol,
        "price": round(price, 2),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/api/exchange-stats")
async def get_exchange_stats():
    stats = data_fetcher.get_stats()
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stats": stats
    }


@app.websocket("/ws/{symbol}")
async def websocket_endpoint(websocket: WebSocket, symbol: str):
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    
    await websocket.accept()
    logger.info(f"🔌 WebSocket connected: {symbol}")
    
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
            
            await asyncio.sleep(2)
            
    except WebSocketDisconnect:
        logger.info(f"❌ WebSocket disconnected: {symbol}")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")


@app.get("/api/stats")
async def get_stats():
    stats = data_fetcher.get_stats()
    total_requests = sum(s["success"] + s["fail"] for s in stats.values())
    total_success = sum(s["success"] for s in stats.values())
    
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime": str(timedelta(seconds=int(time.time() - startup_time))),
        "total_requests": total_requests,
        "total_success": total_success,
        "success_rate": round(total_success / total_requests * 100, 1) if total_requests > 0 else 0
    }


@app.post("/api/train/{symbol}")
async def train_model(symbol: str):
    """ML model eğitimi simülasyonu"""
    await asyncio.sleep(1)  # Simülasyon
    return {
        "success": True,
        "message": f"Model training completed for {symbol}",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ========================================================================================================
# STARTUP
# ========================================================================================================
@app.on_event("startup")
async def startup_event():
    logger.info("=" * 70)
    logger.info("🚀 ICTSMARTPRO v9.0 STARTED")
    logger.info("=" * 70)
    logger.info(f"Environment: {Config.ENV}")
    logger.info(f"Debug: {Config.DEBUG}")
    logger.info(f"Sources: Binance, MEXC, Kraken, Yahoo")
    logger.info(f"Cache TTL: {Config.CACHE_TTL}s")
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
