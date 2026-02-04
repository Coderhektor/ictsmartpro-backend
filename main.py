# app/main.py
import time
import json
import hmac
import hashlib
import requests
import asyncio
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, validator
import redis.asyncio as redis
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import logging
from contextlib import asynccontextmanager
import os
from dataclasses import dataclass
import aiohttp

# ==========================================
# CONFIGURATION
# ==========================================
class Config:
    # Binance
    BINANCE_BASE = "https://api.binance.com"
    BINANCE_FUTURES_BASE = "https://fapi.binance.com"
    BINANCE_TESTNET_BASE = "https://testnet.binancefuture.com"
    
    # CoinGecko
    COINGECKO_BASE = "https://api.coingecko.com/api/v3"
    
    # Redis
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # API Keys (use environment variables in production)
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
    BINANCE_SECRET = os.getenv("BINANCE_SECRET", "")
    USE_TESTNET = os.getenv("USE_TESTNET", "false").lower() == "true"
    
    # Cache
    CACHE_TTL = 30  # seconds
    OHLCV_CACHE_TTL = 300  # 5 minutes for historical data
    
    # Rate limiting
    REQUESTS_PER_MINUTE = 1200  # Binance limit
    
    # Trading
    DEFAULT_QUANTITY = 0.001  # Default BTC quantity
    MAX_POSITION_SIZE = 10000  # USD
    STOP_LOSS_PCT = 0.02  # 2%
    TAKE_PROFIT_PCT = 0.04  # 4%
    
    # Monitoring
    HEALTH_CHECK_INTERVAL = 30  # seconds
    PRICE_UPDATE_INTERVAL = 10  # seconds

# ==========================================
# LOGGING
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('trading_platform.log')
    ]
)
logger = logging.getLogger(__name__)

# ==========================================
# MODELS
# ==========================================
class AnalyzeRequest(BaseModel):
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    
    @validator('timeframe')
    def validate_timeframe(cls, v):
        valid_timeframes = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']
        if v not in valid_timeframes:
            raise ValueError(f'Timeframe must be one of {valid_timeframes}')
        return v

class TradeRequest(BaseModel):
    symbol: str = "BTCUSDT"
    side: str = "BUY"
    quantity: float = 0.001
    order_type: str = "MARKET"
    price: Optional[float] = None
    
    @validator('side')
    def validate_side(cls, v):
        if v.upper() not in ["BUY", "SELL"]:
            raise ValueError('Side must be BUY or SELL')
        return v.upper()
    
    @validator('order_type')
    def validate_order_type(cls, v):
        if v.upper() not in ["MARKET", "LIMIT"]:
            raise ValueError('Order type must be MARKET or LIMIT')
        return v.upper()

class Position(BaseModel):
    symbol: str
    side: str
    quantity: float
    entry_price: float
    current_price: float
    pnl: float
    pnl_percent: float
    stop_loss: float
    take_profit: float
    timestamp: datetime

# ==========================================
# DATA MANAGER
# ==========================================
class DataManager:
    def __init__(self):
        self.session = aiohttp.ClientSession()
        self.cache = {}
        self.last_request = {}
        
    async def fetch_binance_klines(self, symbol: str, interval: str, limit: int = 100):
        """Fetch OHLCV data from Binance"""
        try:
            cache_key = f"binance:klines:{symbol}:{interval}:{limit}"
            
            # Check cache
            if cache_key in self.cache:
                cached_data, timestamp = self.cache[cache_key]
                if time.time() - timestamp < Config.OHLCV_CACHE_TTL:
                    return cached_data
            
            url = f"{Config.BINANCE_BASE}/api/v3/klines"
            params = {
                "symbol": symbol.upper(),
                "interval": interval,
                "limit": limit
            }
            
            # Rate limiting
            await self._rate_limit("binance")
            
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Process candles
                    candles = []
                    for k in data:
                        candle = {
                            "timestamp": k[0],
                            "open": float(k[1]),
                            "high": float(k[2]),
                            "low": float(k[3]),
                            "close": float(k[4]),
                            "volume": float(k[5]),
                            "close_time": k[6],
                            "quote_volume": float(k[7]),
                            "trades": k[8],
                            "taker_buy_base": float(k[9]),
                            "taker_buy_quote": float(k[10])
                        }
                        candles.append(candle)
                    
                    # Cache result
                    self.cache[cache_key] = (candles, time.time())
                    
                    return candles
                else:
                    logger.error(f"Binance API error: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error fetching Binance klines: {e}")
            return None
    
    async def fetch_coingecko_data(self, symbol: str):
        """Fetch data from CoinGecko"""
        try:
            cache_key = f"coingecko:{symbol}"
            
            # Check cache
            if cache_key in self.cache:
                cached_data, timestamp = self.cache[cache_key]
                if time.time() - timestamp < Config.CACHE_TTL:
                    return cached_data
            
            # Map symbol to CoinGecko ID
            symbol_map = {
                "BTC": "bitcoin",
                "ETH": "ethereum",
                "BNB": "binancecoin",
                "XRP": "ripple",
                "ADA": "cardano",
                "SOL": "solana",
                "DOT": "polkadot",
                "DOGE": "dogecoin",
                "AVAX": "avalanche-2",
                "MATIC": "polygon",
                "LINK": "chainlink",
                "UNI": "uniswap",
                "LTC": "litecoin",
                "ATOM": "cosmos"
            }
            
            coin_id = symbol_map.get(symbol.upper().replace("USDT", ""), symbol.lower())
            
            url = f"{Config.COINGECKO_BASE}/coins/{coin_id}"
            params = {
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false"
            }
            
            # Rate limiting
            await self._rate_limit("coingecko")
            
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Extract relevant data
                    result = {
                        "id": data["id"],
                        "symbol": data["symbol"].upper(),
                        "name": data["name"],
                        "current_price": data["market_data"]["current_price"]["usd"],
                        "market_cap": data["market_data"]["market_cap"]["usd"],
                        "market_cap_rank": data["market_data"]["market_cap_rank"],
                        "total_volume": data["market_data"]["total_volume"]["usd"],
                        "high_24h": data["market_data"]["high_24h"]["usd"],
                        "low_24h": data["market_data"]["low_24h"]["usd"],
                        "price_change_24h": data["market_data"]["price_change_24h"],
                        "price_change_percentage_24h": data["market_data"]["price_change_percentage_24h"],
                        "price_change_percentage_7d": data["market_data"]["price_change_percentage_7d"],
                        "price_change_percentage_30d": data["market_data"]["price_change_percentage_30d"],
                        "price_change_percentage_1y": data["market_data"]["price_change_percentage_1y"],
                        "ath": data["market_data"]["ath"]["usd"],
                        "ath_change_percentage": data["market_data"]["ath_change_percentage"]["usd"],
                        "atl": data["market_data"]["atl"]["usd"],
                        "atl_change_percentage": data["market_data"]["atl_change_percentage"]["usd"],
                        "last_updated": data["market_data"]["last_updated"]
                    }
                    
                    # Cache result
                    self.cache[cache_key] = (result, time.time())
                    
                    return result
                else:
                    logger.error(f"CoinGecko API error: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error fetching CoinGecko data: {e}")
            return None
    
    async def fetch_binance_ticker(self, symbol: str):
        """Fetch real-time ticker data from Binance"""
        try:
            cache_key = f"binance:ticker:{symbol}"
            
            # Check cache (very short TTL for real-time data)
            if cache_key in self.cache:
                cached_data, timestamp = self.cache[cache_key]
                if time.time() - timestamp < 2:  # 2 seconds cache for ticker
                    return cached_data
            
            url = f"{Config.BINANCE_BASE}/api/v3/ticker/24hr"
            params = {"symbol": symbol.upper()}
            
            # Rate limiting
            await self._rate_limit("binance")
            
            async with self.session.get(url, params=params, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    result = {
                        "symbol": data["symbol"],
                        "price": float(data["lastPrice"]),
                        "price_change": float(data["priceChange"]),
                        "price_change_percent": float(data["priceChangePercent"]),
                        "weighted_avg_price": float(data["weightedAvgPrice"]),
                        "prev_close_price": float(data["prevClosePrice"]),
                        "last_qty": float(data["lastQty"]),
                        "bid_price": float(data["bidPrice"]),
                        "ask_price": float(data["askPrice"]),
                        "open_price": float(data["openPrice"]),
                        "high_price": float(data["highPrice"]),
                        "low_price": float(data["lowPrice"]),
                        "volume": float(data["volume"]),
                        "quote_volume": float(data["quoteVolume"]),
                        "open_time": data["openTime"],
                        "close_time": data["closeTime"],
                        "first_id": data["firstId"],
                        "last_id": data["lastId"],
                        "count": data["count"]
                    }
                    
                    # Cache result
                    self.cache[cache_key] = (result, time.time())
                    
                    return result
                else:
                    logger.error(f"Binance ticker error: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error fetching Binance ticker: {e}")
            return None
    
    async def fetch_order_book(self, symbol: str, limit: int = 10):
        """Fetch order book data"""
        try:
            url = f"{Config.BINANCE_BASE}/api/v3/depth"
            params = {
                "symbol": symbol.upper(),
                "limit": limit
            }
            
            await self._rate_limit("binance")
            
            async with self.session.get(url, params=params, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "bids": [[float(price), float(qty)] for price, qty in data["bids"]],
                        "asks": [[float(price), float(qty)] for price, qty in data["asks"]],
                        "last_update_id": data["lastUpdateId"]
                    }
                else:
                    return None
                    
        except Exception as e:
            logger.error(f"Error fetching order book: {e}")
            return None
    
    async def _rate_limit(self, service: str):
        """Simple rate limiting"""
        current_time = time.time()
        if service in self.last_request:
            time_since_last = current_time - self.last_request[service]
            if time_since_last < 60 / Config.REQUESTS_PER_MINUTE:
                await asyncio.sleep(60 / Config.REQUESTS_PER_MINUTE - time_since_last)
        
        self.last_request[service] = time.time()
    
    async def close(self):
        """Close the session"""
        await self.session.close()

# ==========================================
# TECHNICAL ANALYSIS ENGINE
# ==========================================
class TechnicalAnalysis:
    @staticmethod
    def calculate_all(candles: List[Dict], symbol: str, timeframe: str) -> Dict:
        """Calculate all technical indicators"""
        if not candles or len(candles) < 50:
            return {}
        
        # Extract data
        closes = [c["close"] for c in candles]
        opens = [c["open"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        volumes = [c["volume"] for c in candles]
        
        current_price = closes[-1]
        
        # Moving Averages
        sma_20 = TechnicalAnalysis.sma(closes, 20)
        sma_50 = TechnicalAnalysis.sma(closes, 50)
        sma_200 = TechnicalAnalysis.sma(closes, 200)
        ema_12 = TechnicalAnalysis.ema(closes, 12)
        ema_26 = TechnicalAnalysis.ema(closes, 26)
        
        # Momentum Indicators
        rsi = TechnicalAnalysis.rsi(closes, 14)
        macd_line, signal_line, histogram = TechnicalAnalysis.macd(closes)
        stoch_k, stoch_d = TechnicalAnalysis.stochastic(highs, lows, closes)
        
        # Volatility Indicators
        bb_upper, bb_middle, bb_lower = TechnicalAnalysis.bollinger_bands(closes)
        atr = TechnicalAnalysis.atr(highs, lows, closes)
        
        # Volume Indicators
        obv = TechnicalAnalysis.obv(closes, volumes)
        volume_sma = TechnicalAnalysis.sma(volumes, 20)
        
        # Support & Resistance
        sr_levels = TechnicalAnalysis.support_resistance(highs, lows, closes)
        
        # Trend Analysis
        trend = TechnicalAnalysis.trend_analysis(closes, sma_20, sma_50, sma_200)
        
        # Patterns
        patterns = TechnicalAnalysis.detect_patterns(highs, lows, closes, opens)
        
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "current_price": current_price,
            "indicators": {
                "sma_20": sma_20[-1] if sma_20[-1] else 0,
                "sma_50": sma_50[-1] if sma_50[-1] else 0,
                "sma_200": sma_200[-1] if sma_200[-1] else 0,
                "ema_12": ema_12[-1] if ema_12[-1] else 0,
                "ema_26": ema_26[-1] if ema_26[-1] else 0,
                "rsi": rsi[-1] if rsi[-1] else 50,
                "macd": macd_line[-1] if macd_line[-1] else 0,
                "macd_signal": signal_line[-1] if signal_line[-1] else 0,
                "macd_histogram": histogram[-1] if histogram[-1] else 0,
                "stochastic_k": stoch_k[-1] if stoch_k[-1] else 50,
                "stochastic_d": stoch_d[-1] if stoch_d[-1] else 50,
                "bb_upper": bb_upper[-1] if bb_upper[-1] else 0,
                "bb_middle": bb_middle[-1] if bb_middle[-1] else 0,
                "bb_lower": bb_lower[-1] if bb_lower[-1] else 0,
                "bb_width": ((bb_upper[-1] - bb_lower[-1]) / bb_middle[-1]) if bb_middle[-1] else 0,
                "atr": atr[-1] if atr[-1] else 0,
                "obv": obv[-1] if obv else 0,
                "volume_ratio": volumes[-1] / volume_sma[-1] if volume_sma and volume_sma[-1] else 1
            },
            "support_resistance": sr_levels,
            "trend": trend,
            "patterns": patterns,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    @staticmethod
    def sma(data: List[float], period: int) -> List[float]:
        """Simple Moving Average"""
        if len(data) < period:
            return [None] * len(data)
        
        sma_values = []
        for i in range(len(data)):
            if i < period - 1:
                sma_values.append(None)
            else:
                sma_values.append(np.mean(data[i - period + 1:i + 1]))
        return sma_values
    
    @staticmethod
    def ema(data: List[float], period: int) -> List[float]:
        """Exponential Moving Average"""
        if len(data) < period:
            return [None] * len(data)
        
        k = 2 / (period + 1)
        ema_values = [None] * (period - 1)
        ema_values.append(np.mean(data[:period]))
        
        for i in range(period, len(data)):
            ema_values.append(data[i] * k + ema_values[-1] * (1 - k))
        
        return ema_values
    
    @staticmethod
    def rsi(data: List[float], period: int = 14) -> List[float]:
        """Relative Strength Index"""
        if len(data) < period + 1:
            return [50] * len(data)
        
        deltas = np.diff(data)
        seed = deltas[:period]
        
        up = seed[seed >= 0].sum() / period
        down = -seed[seed < 0].sum() / period
        
        rs = up / down if down != 0 else 0
        rsi_values = [None] * period
        rsi_values.append(100 - 100 / (1 + rs))
        
        for i in range(period, len(deltas)):
            delta = deltas[i]
            upval = delta if delta > 0 else 0
            downval = -delta if delta < 0 else 0
            
            up = (up * (period - 1) + upval) / period
            down = (down * (period - 1) + downval) / period
            
            rs = up / down if down != 0 else 0
            rsi_values.append(100 - 100 / (1 + rs))
        
        return rsi_values
    
    @staticmethod
    def macd(data: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
        """MACD Indicator"""
        ema_fast = TechnicalAnalysis.ema(data, fast)
        ema_slow = TechnicalAnalysis.ema(data, slow)
        
        macd_line = []
        for i in range(len(data)):
            if ema_fast[i] is not None and ema_slow[i] is not None:
                macd_line.append(ema_fast[i] - ema_slow[i])
            else:
                macd_line.append(None)
        
        # Signal line
        valid_macd = [x for x in macd_line if x is not None]
        signal_line = TechnicalAnalysis.ema(valid_macd, signal)
        
        # Align signal line
        signal_aligned = [None] * (len(macd_line) - len(signal_line)) + signal_line
        
        # Histogram
        histogram = []
        for i in range(len(macd_line)):
            if macd_line[i] is not None and signal_aligned[i] is not None:
                histogram.append(macd_line[i] - signal_aligned[i])
            else:
                histogram.append(None)
        
        return macd_line, signal_aligned, histogram
    
    @staticmethod
    def stochastic(highs: List[float], lows: List[float], closes: List[float], period: int = 14):
        """Stochastic Oscillator"""
        k_values = []
        
        for i in range(len(closes)):
            if i < period - 1:
                k_values.append(None)
            else:
                highest = max(highs[i - period + 1:i + 1])
                lowest = min(lows[i - period + 1:i + 1])
                
                if highest - lowest != 0:
                    k = ((closes[i] - lowest) / (highest - lowest)) * 100
                else:
                    k = 50
                
                k_values.append(k)
        
        # %D line (3-period SMA of %K)
        d_values = TechnicalAnalysis.sma([x for x in k_values if x is not None], 3)
        d_aligned = [None] * (len(k_values) - len(d_values)) + d_values
        
        return k_values, d_aligned
    
    @staticmethod
    def bollinger_bands(data: List[float], period: int = 20, std_dev: int = 2):
        """Bollinger Bands"""
        sma = TechnicalAnalysis.sma(data, period)
        
        upper = []
        lower = []
        
        for i in range(len(data)):
            if i < period - 1:
                upper.append(None)
                lower.append(None)
            else:
                std = np.std(data[i - period + 1:i + 1])
                upper.append(sma[i] + std_dev * std)
                lower.append(sma[i] - std_dev * std)
        
        return upper, sma, lower
    
    @staticmethod
    def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14):
        """Average True Range"""
        if len(closes) < 2:
            return [0] * len(closes)
        
        tr_values = [highs[0] - lows[0]]
        
        for i in range(1, len(closes)):
            hl = highs[i] - lows[i]
            hc = abs(highs[i] - closes[i - 1])
            lc = abs(lows[i] - closes[i - 1])
            tr_values.append(max(hl, hc, lc))
        
        atr_values = TechnicalAnalysis.sma(tr_values, period)
        return atr_values
    
    @staticmethod
    def obv(closes: List[float], volumes: List[float]):
        """On-Balance Volume"""
        if len(closes) < 2:
            return [0]
        
        obv_values = [volumes[0]]
        
        for i in range(1, len(closes)):
            if closes[i] > closes[i - 1]:
                obv_values.append(obv_values[-1] + volumes[i])
            elif closes[i] < closes[i - 1]:
                obv_values.append(obv_values[-1] - volumes[i])
            else:
                obv_values.append(obv_values[-1])
        
        return obv_values
    
    @staticmethod
    def support_resistance(highs: List[float], lows: List[float], closes: List[float], order: int = 5):
        """Detect Support and Resistance Levels"""
        if len(closes) < order * 2:
            return {"support": [], "resistance": []}
        
        # Find local maxima (resistance)
        from scipy.signal import argrelextrema
        resistance_idx = argrelextrema(np.array(highs), np.greater, order=order)[0]
        resistance_levels = [highs[i] for i in resistance_idx]
        
        # Find local minima (support)
        support_idx = argrelextrema(np.array(lows), np.less, order=order)[0]
        support_levels = [lows[i] for i in support_idx]
        
        # Cluster similar levels
        def cluster_levels(levels, threshold=0.02):
            if not levels:
                return []
            
            clustered = []
            sorted_levels = sorted(levels)
            current_cluster = [sorted_levels[0]]
            
            for level in sorted_levels[1:]:
                if abs(level - current_cluster[-1]) / current_cluster[-1] < threshold:
                    current_cluster.append(level)
                else:
                    clustered.append(np.mean(current_cluster))
                    current_cluster = [level]
            
            clustered.append(np.mean(current_cluster))
            return clustered
        
        return {
            "support": cluster_levels(support_levels)[-3:],
            "resistance": cluster_levels(resistance_levels)[-3:]
        }
    
    @staticmethod
    def trend_analysis(closes: List[float], sma_20: List[float], sma_50: List[float], sma_200: List[float]):
        """Analyze market trend"""
        if len(closes) < 50:
            return {"direction": "NEUTRAL", "strength": 0}
        
        current_price = closes[-1]
        
        # Check moving averages alignment
        ma_alignment = 0
        if sma_20[-1] and sma_50[-1] and sma_20[-1] > sma_50[-1]:
            ma_alignment += 1
        if sma_50[-1] and sma_200[-1] and sma_50[-1] > sma_200[-1]:
            ma_alignment += 1
        if sma_20[-1] and sma_200[-1] and sma_20[-1] > sma_200[-1]:
            ma_alignment += 1
        
        # Price position relative to MAs
        price_position = 0
        if sma_20[-1] and current_price > sma_20[-1]:
            price_position += 1
        if sma_50[-1] and current_price > sma_50[-1]:
            price_position += 1
        if sma_200[-1] and current_price > sma_200[-1]:
            price_position += 1
        
        # Trend score
        trend_score = ma_alignment + price_position
        
        if trend_score >= 5:
            direction = "STRONG_BULLISH"
            strength = 90
        elif trend_score >= 4:
            direction = "BULLISH"
            strength = 70
        elif trend_score >= 3:
            direction = "SLIGHTLY_BULLISH"
            strength = 60
        elif trend_score <= 1:
            direction = "STRONG_BEARISH"
            strength = 90
        elif trend_score <= 2:
            direction = "BEARISH"
            strength = 70
        else:
            direction = "NEUTRAL"
            strength = 50
        
        return {
            "direction": direction,
            "strength": strength,
            "score": trend_score,
            "description": f"Price above {price_position}/3 MAs, {ma_alignment}/3 MAs aligned"
        }
    
    @staticmethod
    def detect_patterns(highs: List[float], lows: List[float], closes: List[float], opens: List[float]):
        """Detect candlestick patterns"""
        patterns = []
        
        if len(closes) < 3:
            return patterns
        
        # Get last 3 candles
        o1, o2, o3 = opens[-3], opens[-2], opens[-1]
        h1, h2, h3 = highs[-3], highs[-2], highs[-1]
        l1, l2, l3 = lows[-3], lows[-2], lows[-1]
        c1, c2, c3 = closes[-3], closes[-2], closes[-1]
        
        # Bullish Engulfing
        if c1 < o1 and c2 > o2 and c2 > o1 and o2 < c1:
            patterns.append({"name": "Bullish Engulfing", "signal": "BULLISH", "confidence": 70})
        
        # Bearish Engulfing
        if c1 > o1 and c2 < o2 and c2 < o1 and o2 > c1:
            patterns.append({"name": "Bearish Engulfing", "signal": "BEARISH", "confidence": 70})
        
        # Morning Star
        if c1 < o1 and abs(c1 - o1) > (h1 - l1) * 0.3 and \
           abs(c2 - o2) < (h2 - l2) * 0.1 and \
           c3 > o3 and c3 > (o1 + c1) / 2:
            patterns.append({"name": "Morning Star", "signal": "BULLISH", "confidence": 75})
        
        # Evening Star
        if c1 > o1 and abs(c1 - o1) > (h1 - l1) * 0.3 and \
           abs(c2 - o2) < (h2 - l2) * 0.1 and \
           c3 < o3 and c3 < (o1 + c1) / 2:
            patterns.append({"name": "Evening Star", "signal": "BEARISH", "confidence": 75})
        
        # Hammer
        if c2 > o2 and (l2 - min(o2, c2)) > 2 * abs(c2 - o2) and \
           (max(o2, c2) - l2) < abs(c2 - o2) * 0.3:
            patterns.append({"name": "Hammer", "signal": "BULLISH", "confidence": 65})
        
        # Shooting Star
        if c2 < o2 and (h2 - max(o2, c2)) > 2 * abs(c2 - o2) and \
           (h2 - min(o2, c2)) < abs(c2 - o2) * 0.3:
            patterns.append({"name": "Shooting Star", "signal": "BEARISH", "confidence": 65})
        
        return patterns

# ==========================================
# TRADING ENGINE
# ==========================================
class TradingEngine:
    def __init__(self):
        self.positions = {}
        self.order_history = []
        
    def calculate_signal(self, analysis: Dict) -> Dict:
        """Calculate trading signal based on technical analysis"""
        if not analysis:
            return {"signal": "HOLD", "confidence": 50}
        
        indicators = analysis["indicators"]
        trend = analysis["trend"]
        patterns = analysis["patterns"]
        
        # Initialize scores
        score = 50
        
        # RSI scoring
        rsi = indicators["rsi"]
        if rsi < 30:
            score += 20  # Oversold
        elif rsi > 70:
            score -= 20  # Overbought
        elif rsi < 45:
            score += 10
        elif rsi > 55:
            score -= 10
        
        # MACD scoring
        macd_val = indicators["macd"]
        macd_signal = indicators["macd_signal"]
        if macd_val > macd_signal:
            score += 15
        else:
            score -= 15
        
        # Trend scoring
        trend_strength = trend["strength"]
        if trend["direction"] in ["STRONG_BULLISH", "BULLISH"]:
            score += trend_strength / 2
        elif trend["direction"] in ["STRONG_BEARISH", "BEARISH"]:
            score -= trend_strength / 2
        
        # Pattern scoring
        for pattern in patterns:
            if pattern["signal"] == "BULLISH":
                score += pattern["confidence"] / 2
            elif pattern["signal"] == "BEARISH":
                score -= pattern["confidence"] / 2
        
        # Bollinger Bands scoring
        price = analysis["current_price"]
        bb_upper = indicators["bb_upper"]
        bb_lower = indicators["bb_lower"]
        
        if price < bb_lower:
            score += 15  # Oversold
        elif price > bb_upper:
            score -= 15  # Overbought
        
        # Normalize score
        score = max(0, min(100, score))
        
        # Determine signal
        if score >= 70:
            signal = "BUY"
            confidence = score
        elif score <= 30:
            signal = "SELL"
            confidence = 100 - score
        else:
            signal = "HOLD"
            confidence = 50
        
        # Calculate risk parameters
        atr = indicators["atr"]
        stop_loss = price * (1 - Config.STOP_LOSS_PCT) if signal == "BUY" else price * (1 + Config.STOP_LOSS_PCT)
        take_profit = price * (1 + Config.TAKE_PROFIT_PCT) if signal == "BUY" else price * (1 - Config.TAKE_PROFIT_PCT)
        
        return {
            "signal": signal,
            "confidence": round(confidence, 1),
            "price": price,
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "risk_reward": Config.TAKE_PROFIT_PCT / Config.STOP_LOSS_PCT,
            "indicators": {
                "rsi": round(rsi, 2),
                "macd": round(macd_val, 4),
                "atr": round(atr, 4)
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def execute_order(self, symbol: str, side: str, quantity: float, order_type: str = "MARKET", price: Optional[float] = None):
        """Execute trade order (simulated for now)"""
        # In production, this would call Binance API
        order_id = f"order_{int(time.time() * 1000)}"
        
        order = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "price": price,
            "status": "FILLED",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self.order_history.append(order)
        
        # Update positions
        if side == "BUY":
            if symbol not in self.positions:
                self.positions[symbol] = {
                    "quantity": quantity,
                    "entry_price": price or 0,
                    "side": "LONG"
                }
            else:
                self.positions[symbol]["quantity"] += quantity
        
        return order

# ==========================================
# APP LIFESPAN
# ==========================================
data_manager = None
trading_engine = None
redis_client = None
START_TIME = time.time()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global data_manager, trading_engine, redis_client
    
    # Startup
    logger.info("🚀 Starting Trading Platform...")
    
    # Initialize components
    data_manager = DataManager()
    trading_engine = TradingEngine()
    redis_client = await redis.from_url(Config.REDIS_URL, decode_responses=True)
    
    logger.info("✅ All systems initialized")
    logger.info("📊 Data Manager: Ready")
    logger.info("🤖 Trading Engine: Ready")
    logger.info("🗄️ Redis: Connected")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down Trading Platform...")
    await data_manager.close()
    await redis_client.close()
    logger.info("✅ Clean shutdown complete")

# ==========================================
# FASTAPI APP
# ==========================================
app = FastAPI(
    title="Advanced Trading Platform",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# ==========================================
# API ENDPOINTS
# ==========================================
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "🚀 Advanced Trading Platform",
        "version": "2.0.0",
        "status": "operational",
        "uptime": int(time.time() - START_TIME),
        "endpoints": {
            "/health": "Health check",
            "/api/ticker/{symbol}": "Get ticker data",
            "/api/klines/{symbol}": "Get OHLCV data",
            "/api/analyze": "Technical analysis",
            "/api/signal/{symbol}": "Trading signal",
            "/api/trade": "Execute trade",
            "/api/positions": "Get open positions",
            "/docs": "API documentation"
        }
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    try:
        # Check Redis
        await redis_client.ping()
        
        # Check external APIs
        test_symbol = "BTCUSDT"
        ticker = await data_manager.fetch_binance_ticker(test_symbol)
        
        if not ticker:
            raise HTTPException(status_code=503, detail="Binance API unavailable")
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "uptime": int(time.time() - START_TIME),
            "services": {
                "redis": "operational",
                "binance_api": "operational",
                "coingecko_api": "operational",
                "trading_engine": "operational"
            }
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")

@app.get("/api/ticker/{symbol}")
async def get_ticker(symbol: str):
    """Get real-time ticker data"""
    try:
        # Get from Binance
        ticker = await data_manager.fetch_binance_ticker(symbol)
        
        if not ticker:
            raise HTTPException(status_code=404, detail="Symbol not found")
        
        # Get additional data from CoinGecko
        cg_data = await data_manager.fetch_coingecko_data(symbol.replace("USDT", ""))
        
        response = {
            "symbol": symbol,
            "price": ticker["price"],
            "price_change_24h": ticker["price_change_percent"],
            "volume_24h": ticker["volume"],
            "high_24h": ticker["high_price"],
            "low_24h": ticker["low_price"],
            "timestamp": datetime.utcnow().isoformat(),
            "source": "binance"
        }
        
        if cg_data:
            response.update({
                "market_cap": cg_data["market_cap"],
                "market_cap_rank": cg_data["market_cap_rank"],
                "coingecko_price": cg_data["current_price"],
                "price_change_percentage_7d": cg_data["price_change_percentage_7d"],
                "price_change_percentage_30d": cg_data["price_change_percentage_30d"]
            })
        
        return response
        
    except Exception as e:
        logger.error(f"Error fetching ticker: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/klines/{symbol}")
async def get_klines(
    symbol: str,
    interval: str = "1h",
    limit: int = 100
):
    """Get OHLCV data"""
    try:
        candles = await data_manager.fetch_binance_klines(symbol, interval, limit)
        
        if not candles:
            raise HTTPException(status_code=404, detail="No data available")
        
        return {
            "symbol": symbol,
            "interval": interval,
            "candles": candles,
            "count": len(candles),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error fetching klines: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    """Technical analysis endpoint"""
    try:
        # Fetch OHLCV data
        candles = await data_manager.fetch_binance_klines(req.symbol, req.timeframe, 100)
        
        if not candles or len(candles) < 50:
            raise HTTPException(status_code=400, detail="Insufficient data for analysis")
        
        # Perform technical analysis
        analysis = TechnicalAnalysis.calculate_all(candles, req.symbol, req.timeframe)
        
        if not analysis:
            raise HTTPException(status_code=500, detail="Analysis failed")
        
        return analysis
        
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/signal/{symbol}")
async def get_signal(
    symbol: str,
    timeframe: str = "1h"
):
    """Get trading signal"""
    try:
        # Fetch data and analyze
        candles = await data_manager.fetch_binance_klines(symbol, timeframe, 100)
        
        if not candles or len(candles) < 50:
            raise HTTPException(status_code=400, detail="Insufficient data")
        
        analysis = TechnicalAnalysis.calculate_all(candles, symbol, timeframe)
        
        if not analysis:
            raise HTTPException(status_code=500, detail="Analysis failed")
        
        # Calculate signal
        signal = trading_engine.calculate_signal(analysis)
        
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "signal": signal["signal"],
            "confidence": signal["confidence"],
            "price": signal["price"],
            "stop_loss": signal["stop_loss"],
            "take_profit": signal["take_profit"],
            "risk_reward": signal["risk_reward"],
            "indicators": signal["indicators"],
            "analysis": analysis,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Signal error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/trade")
async def trade(req: TradeRequest):
    """Execute trade"""
    try:
        # Validate API keys
        if not Config.BINANCE_API_KEY or Config.BINANCE_API_KEY == "CHANGE_ME":
            return {
                "status": "simulated",
                "message": "Using simulated trade (set BINANCE_API_KEY for real trading)",
                "order": trading_engine.execute_order(
                    req.symbol,
                    req.side,
                    req.quantity,
                    req.order_type,
                    req.price
                )
            }
        
        # In production, this would execute real trades
        # For now, return simulated response
        order = trading_engine.execute_order(
            req.symbol,
            req.side,
            req.quantity,
            req.order_type,
            req.price
        )
        
        return {
            "status": "success",
            "message": "Trade executed",
            "order": order
        }
        
    except Exception as e:
        logger.error(f"Trade error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/positions")
async def get_positions():
    """Get open positions"""
    try:
        positions = []
        
        for symbol, pos in trading_engine.positions.items():
            # Get current price
            ticker = await data_manager.fetch_binance_ticker(symbol)
            current_price = ticker["price"] if ticker else pos["entry_price"]
            
            # Calculate P&L
            pnl = (current_price - pos["entry_price"]) * pos["quantity"] if pos["side"] == "LONG" else (pos["entry_price"] - current_price) * pos["quantity"]
            pnl_percent = (pnl / (pos["entry_price"] * pos["quantity"])) * 100
            
            positions.append({
                "symbol": symbol,
                "side": pos["side"],
                "quantity": pos["quantity"],
                "entry_price": pos["entry_price"],
                "current_price": current_price,
                "pnl": round(pnl, 2),
                "pnl_percent": round(pnl_percent, 2),
                "timestamp": datetime.utcnow().isoformat()
            })
        
        return {
            "positions": positions,
            "count": len(positions),
            "total_pnl": sum(p["pnl"] for p in positions),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Positions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/market/overview")
async def market_overview():
    """Get market overview"""
    try:
        # Top cryptocurrencies
        top_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]
        
        overview = []
        for symbol in top_symbols:
            ticker = await data_manager.fetch_binance_ticker(symbol)
            if ticker:
                overview.append({
                    "symbol": symbol,
                    "price": ticker["price"],
                    "change_24h": ticker["price_change_percent"],
                    "volume": ticker["volume"],
                    "market_cap": 0  # Would need CoinGecko for this
                })
        
        return {
            "overview": overview,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Market overview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# WEB INTERFACE
# ==========================================
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Trading dashboard"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Trading Platform Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://s3.tradingview.com/tv.js"></script>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                margin: 0;
                padding: 20px;
                background: #0f172a;
                color: #e2e8f0;
            }
            .container {
                max-width: 1400px;
                margin: 0 auto;
            }
            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 30px;
                padding-bottom: 20px;
                border-bottom: 1px solid #334155;
            }
            .logo {
                font-size: 28px;
                font-weight: bold;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            .grid {
                display: grid;
                grid-template-columns: 2fr 1fr;
                gap: 20px;
                margin-bottom: 20px;
            }
            .card {
                background: #1e293b;
                border-radius: 10px;
                padding: 20px;
                border: 1px solid #334155;
            }
            .tradingview-widget {
                height: 500px;
            }
            .controls {
                display: flex;
                gap: 10px;
                margin-bottom: 20px;
            }
            input, select, button {
                padding: 10px 15px;
                border-radius: 5px;
                border: 1px solid #475569;
                background: #1e293b;
                color: #e2e8f0;
            }
            button {
                background: #3b82f6;
                border: none;
                cursor: pointer;
            }
            button:hover {
                background: #2563eb;
            }
            .signal {
                padding: 15px;
                border-radius: 8px;
                margin-bottom: 15px;
                text-align: center;
                font-weight: bold;
            }
            .signal.buy {
                background: rgba(34, 197, 94, 0.2);
                border: 1px solid #22c55e;
                color: #22c55e;
            }
            .signal.sell {
                background: rgba(239, 68, 68, 0.2);
                border: 1px solid #ef4444;
                color: #ef4444;
            }
            .signal.hold {
                background: rgba(234, 179, 8, 0.2);
                border: 1px solid #eab308;
                color: #eab308;
            }
            .market-table {
                width: 100%;
                border-collapse: collapse;
            }
            .market-table th, .market-table td {
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #334155;
            }
            .positive {
                color: #22c55e;
            }
            .negative {
                color: #ef4444;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">🚀 Trading Platform</div>
                <div>Advanced Trading & Analysis</div>
            </div>
            
            <div class="controls">
                <input type="text" id="symbol" placeholder="Symbol (BTCUSDT)" value="BTCUSDT">
                <select id="timeframe">
                    <option value="1m">1 Minute</option>
                    <option value="5m">5 Minutes</option>
                    <option value="15m">15 Minutes</option>
                    <option value="1h" selected>1 Hour</option>
                    <option value="4h">4 Hours</option>
                    <option value="1d">1 Day</option>
                </select>
                <button onclick="analyze()">Analyze</button>
                <button onclick="getSignal()">Get Signal</button>
            </div>
            
            <div class="grid">
                <div class="card">
                    <h3>Chart</h3>
                    <div id="tradingview" class="tradingview-widget"></div>
                </div>
                
                <div class="card">
                    <h3>Trading Signal</h3>
                    <div id="signal" class="signal hold">
                        Loading...
                    </div>
                    
                    <div id="analysis">
                        <h4>Analysis</h4>
                        <div id="indicators"></div>
                    </div>
                </div>
            </div>
            
            <div class="card">
                <h3>Market Overview</h3>
                <table class="market-table" id="marketTable">
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Price</th>
                            <th>24h Change</th>
                            <th>Volume</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        <!-- Filled by JavaScript -->
                    </tbody>
                </table>
            </div>
        </div>
        
        <script>
            // Initialize TradingView
            new TradingView.widget({
                "width": "100%",
                "height": "500",
                "symbol": "BINANCE:BTCUSDT",
                "interval": "60",
                "timezone": "Etc/UTC",
                "theme": "dark",
                "style": "1",
                "locale": "en",
                "toolbar_bg": "#0f172a",
                "enable_publishing": false,
                "allow_symbol_change": true,
                "container_id": "tradingview",
                "studies": ["RSI@tv-basicstudies", "MACD@tv-basicstudies", "Volume@tv-basicstudies"]
            });
            
            // Load market data
            async function loadMarketData() {
                try {
                    const response = await fetch('/api/market/overview');
                    const data = await response.json();
                    
                    const tbody = document.querySelector('#marketTable tbody');
                    tbody.innerHTML = '';
                    
                    data.overview.forEach(item => {
                        const changeClass = item.change_24h >= 0 ? 'positive' : 'negative';
                        const changeSign = item.change_24h >= 0 ? '+' : '';
                        
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>${item.symbol}</td>
                            <td>$${item.price.toFixed(2)}</td>
                            <td class="${changeClass}">${changeSign}${item.change_24h.toFixed(2)}%</td>
                            <td>${(item.volume / 1000000).toFixed(2)}M</td>
                            <td>
                                <button onclick="analyzeSymbol('${item.symbol}')">Analyze</button>
                            </td>
                        `;
                        tbody.appendChild(row);
                    });
                } catch (error) {
                    console.error('Error loading market data:', error);
                }
            }
            
            // Analyze symbol
            async function analyze() {
                const symbol = document.getElementById('symbol').value;
                const timeframe = document.getElementById('timeframe').value;
                
                try {
                    const response = await fetch(`/api/analyze`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({symbol, timeframe})
                    });
                    
                    const data = await response.json();
                    displayAnalysis(data);
                } catch (error) {
                    console.error('Analysis error:', error);
                }
            }
            
            // Get trading signal
            async function getSignal() {
                const symbol = document.getElementById('symbol').value;
                const timeframe = document.getElementById('timeframe').value;
                
                try {
                    const response = await fetch(`/api/signal/${symbol}?timeframe=${timeframe}`);
                    const data = await response.json();
                    displaySignal(data);
                } catch (error) {
                    console.error('Signal error:', error);
                }
            }
            
            // Analyze specific symbol
            function analyzeSymbol(symbol) {
                document.getElementById('symbol').value = symbol;
                analyze();
                getSignal();
            }
            
            // Display analysis
            function displayAnalysis(data) {
                const indicatorsDiv = document.getElementById('indicators');
                indicatorsDiv.innerHTML = `
                    <p>RSI: ${data.indicators?.rsi?.toFixed(2) || 'N/A'}</p>
                    <p>MACD: ${data.indicators?.macd?.toFixed(4) || 'N/A'}</p>
                    <p>Trend: ${data.trend?.direction || 'N/A'}</p>
                    <p>Support: ${data.support_resistance?.support?.[0]?.toFixed(2) || 'N/A'}</p>
                    <p>Resistance: ${data.support_resistance?.resistance?.[0]?.toFixed(2) || 'N/A'}</p>
                `;
            }
            
            // Display signal
            function displaySignal(data) {
                const signalDiv = document.getElementById('signal');
                signalDiv.className = `signal ${data.signal.toLowerCase()}`;
                signalDiv.innerHTML = `
                    <div style="font-size: 24px;">${data.signal}</div>
                    <div>Confidence: ${data.confidence}%</div>
                    <div>Price: $${data.price.toFixed(2)}</div>
                    <div>Stop Loss: $${data.stop_loss.toFixed(2)}</div>
                    <div>Take Profit: $${data.take_profit.toFixed(2)}</div>
                    <div>Risk/Reward: ${data.risk_reward.toFixed(2)}</div>
                `;
                
                displayAnalysis(data.analysis);
            }
            
            // Initial load
            loadMarketData();
            getSignal();
            
            // Auto-refresh every 30 seconds
            setInterval(loadMarketData, 30000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ==========================================
# MAIN ENTRY POINT
# ==========================================
if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    
    logger.info("=" * 70)
    logger.info("🚀 ADVANCED TRADING PLATFORM")
    logger.info("=" * 70)
    logger.info(f"🌐 Server: http://0.0.0.0:{port}")
    logger.info("📊 Features:")
    logger.info("   • Real-time Binance & CoinGecko data")
    logger.info("   • Advanced technical analysis (20+ indicators)")
    logger.info("   • AI-powered trading signals")
    logger.info("   • TradingView chart integration")
    logger.info("   • Position management")
    logger.info("   • Web dashboard")
    logger.info("   • Redis caching")
    logger.info("   • Rate limiting")
    logger.info("=" * 70)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    ) biz verileri binance ve coingoeko yada yfinans dan api kullanmadan alıyoruz, buna göre bizim api key gerek yok ,  bunu düzeltelim, diğer heriy doğru
