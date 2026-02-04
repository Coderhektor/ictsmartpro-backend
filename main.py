🚀 CryptoTrader Pro v6.0 - Advanced Trading Platform
📊 Coingecko Real-time Ticker + TradingView Integration + Full Technical Analysis
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
import asyncio
import json
import aiohttp
import pandas as pd
import numpy as np
from dataclasses import dataclass, asdict
from enum import Enum
from scipy.signal import argrelextrema
from scipy.stats import linregress

Configure logging
logging.basicConfig(
level=logging.INFO,
format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(name)

from fastapi import FastAPI, HTTPException, Query, Request, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uuid

====================================================================================
SUBSCRIPTION TIERS
====================================================================================
class SubscriptionTier(Enum):
FREE = "free"
BASIC = "basic"
PRO = "pro"
ENTERPRISE = "enterprise"

TIER_FEATURES = {
SubscriptionTier.FREE: {
"name": "Free",
"price": 0,
"max_symbols": 3,
"features": ["Basic charts", "5 indicators", "Community support"]
},
SubscriptionTier.BASIC: {
"name": "Basic",
"price": 9.99,
"max_symbols": 10,
"features": ["Advanced charts", "15 indicators", "Real-time data", "Email support"]
},
SubscriptionTier.PRO: {
"name": "Pro",
"price": 29.99,
"max_symbols": 50,
"features": ["All indicators", "AI signals", "Fibonacci tools", "Pattern detection", "Priority support"]
},
SubscriptionTier.ENTERPRISE: {
"name": "Enterprise",
"price": 99.99,
"max_symbols": 999,
"features": ["Everything + API", "Custom indicators", "White-label", "24/7 support"]
}
}

====================================================================================
COINGECKO REAL-TIME TICKER PROVIDER
====================================================================================
class CoinGeckoTicker:
"""Real-time cryptocurrency ticker with streaming updates"""

text
BASE_URL = "https://api.coingecko.com/api/v3"

# Popular cryptocurrencies and forex pairs
DEFAULT_SYMBOLS = [
    "bitcoin", "ethereum", "binancecoin", "ripple", "cardano",
    "solana", "polkadot", "dogecoin", "avalanche-2", "chainlink",
    "polygon", "uniswap", "litecoin", "bitcoin-cash", "stellar",
    # Forex pairs (simulated for Coingecko)
    "usd", "eur", "gbp", "jpy"
]

# TradingView symbol mappings
TRADINGVIEW_SYMBOLS = {
    "bitcoin": "BINANCE:BTCUSDT",
    "ethereum": "BINANCE:ETHUSDT",
    "binancecoin": "BINANCE:BNBUSDT",
    "ripple": "BINANCE:XRPUSDT",
    "cardano": "BINANCE:ADAUSDT",
    "solana": "BINANCE:SOLUSDT",
    "polkadot": "BINANCE:DOTUSDT",
    "dogecoin": "BINANCE:DOGEUSDT",
    "avalanche-2": "BINANCE:AVAXUSDT",
    "chainlink": "BINANCE:LINKUSDT",
    "polygon": "BINANCE:MATICUSDT",
    "uniswap": "BINANCE:UNIUSDT",
    "litecoin": "BINANCE:LTCUSDT",
    "bitcoin-cash": "BINANCE:BCHUSDT",
    "stellar": "BINANCE:XLMUSDT",
    # Forex mappings
    "usd": "FX:USDUSD",
    "eur": "FX:EURUSD",
    "gbp": "FX:GBPUSD",
    "jpy": "FX:JPYUSD",
    # Metals
    "gold": "FX:XAUUSD",
    "silver": "FX:XAGUSD",
    # Indices
    "sp500": "AMEX:SPY",
    "nasdaq": "NASDAQ:QQQ",
    "dowjones": "DOW:DJI",
}

def __init__(self):
    self.session: Optional[aiohttp.ClientSession] = None
    self.price_cache = {}
    self.last_update = datetime.now(timezone.utc)
    self.ticker_data = []
    self.subscribers = set()
    self.historical_cache = {}
    
async def initialize(self):
    """Initialize aiohttp session"""
    if not self.session:
        self.session = aiohttp.ClientSession()
        logger.info("✅ CoinGecko Ticker initialized")

async def close(self):
    """Close aiohttp session"""
    if self.session:
        await self.session.close()
        logger.info("🔌 CoinGecko Ticker closed")

async def fetch_ticker_data(self, symbols: List[str] = None) -> List[Dict]:
    """Fetch real-time ticker data"""
    if not symbols:
        symbols = self.DEFAULT_SYMBOLS
    
    try:
        url = f"{self.BASE_URL}/simple/price"
        params = {
            "ids": ",".join(symbols),
            "vs_currencies": "usd",
            "include_24hr_vol": "true",
            "include_24hr_change": "true",
            "include_market_cap": "true",
            "include_last_updated_at": "true",
            "precision": "full"
        }
        
        async with self.session.get(url, params=params, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                
                ticker_list = []
                for coin_id, coin_data in data.items():
                    symbol = coin_id.upper()
                    price = coin_data.get("usd", 0)
                    change = coin_data.get("usd_24h_change", 0)
                    
                    ticker_list.append({
                        "id": coin_id,
                        "symbol": symbol,
                        "price": price,
                        "change_24h": change,
                        "change_24h_pct": round(change, 2),
                        "volume_24h": coin_data.get("usd_24h_vol", 0),
                        "market_cap": coin_data.get("usd_market_cap", 0),
                        "last_updated": datetime.fromtimestamp(
                            coin_data.get("last_updated_at", 0),
                            tz=timezone.utc
                        ).isoformat(),
                        "tradingview_symbol": self.TRADINGVIEW_SYMBOLS.get(coin_id, f"BINANCE:{symbol}USDT"),
                        "type": "crypto"
                    })
                
                # Sort by market cap
                ticker_list.sort(key=lambda x: x["market_cap"], reverse=True)
                self.ticker_data = ticker_list
                self.last_update = datetime.now(timezone.utc)
                
                logger.info(f"📊 Ticker updated with {len(ticker_list)} symbols")
                return ticker_list
            else:
                logger.error(f"CoinGecko API error: {response.status}")
                return []
    except Exception as e:
        logger.error(f"Error fetching ticker data: {e}")
        return []

async def get_symbol_info(self, symbol: str) -> Optional[Dict]:
    """Get information for a specific symbol"""
    # Check cache first
    if symbol in self.price_cache:
        cached_data, timestamp = self.price_cache[symbol]
        if (datetime.now(timezone.utc) - timestamp).total_seconds() < 30:
            return cached_data
    
    try:
        # Try to fetch from Coingecko
        url = f"{self.BASE_URL}/simple/price"
        params = {
            "ids": symbol.lower(),
            "vs_currencies": "usd",
            "include_24hr_vol": "true",
            "include_24hr_change": "true",
            "include_market_cap": "true",
            "include_last_updated_at": "true"
        }
        
        async with self.session.get(url, params=params, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                
                if symbol.lower() in data:
                    coin_data = data[symbol.lower()]
                    info = {
                        "symbol": symbol.upper(),
                        "id": symbol.lower(),
                        "price": coin_data.get("usd", 0),
                        "change_24h": coin_data.get("usd_24h_change", 0),
                        "volume_24h": coin_data.get("usd_24h_vol", 0),
                        "market_cap": coin_data.get("usd_market_cap", 0),
                        "tradingview_symbol": self.TRADINGVIEW_SYMBOLS.get(symbol.lower(), f"BINANCE:{symbol.upper()}USDT"),
                        "type": "crypto",
                        "available": True
                    }
                    
                    # Update cache
                    self.price_cache[symbol] = (info, datetime.now(timezone.utc))
                    return info
        
        # If not found in Coingecko, create a simulated entry
        simulated_price = np.random.uniform(10, 1000)
        simulated_change = np.random.uniform(-5, 5)
        
        info = {
            "symbol": symbol.upper(),
            "id": symbol.lower(),
            "price": simulated_price,
            "change_24h": simulated_change,
            "volume_24h": simulated_price * np.random.uniform(1000, 10000),
            "market_cap": simulated_price * np.random.uniform(1000000, 10000000),
            "tradingview_symbol": f"BINANCE:{symbol.upper()}USDT",
            "type": "forex" if len(symbol) == 6 else "crypto",
            "available": False,
            "simulated": True
        }
        
        self.price_cache[symbol] = (info, datetime.now(timezone.utc))
        return info
        
    except Exception as e:
        logger.error(f"Error fetching symbol info: {e}")
        return None

async def fetch_ohlcv(self, symbol: str, timeframe: str = "1D", limit: int = 100) -> List[Dict]:
    """Fetch OHLCV data for a symbol"""
    cache_key = f"{symbol}_{timeframe}_{limit}"
    
    # Check cache
    if cache_key in self.historical_cache:
        cached_data, timestamp = self.historical_cache[cache_key]
        if (datetime.now(timezone.utc) - timestamp).total_seconds() < 300:  # 5 minutes
            return cached_data
    
    try:
        # Calculate days based on timeframe
        days_map = {
            "1m": 1/1440, "5m": 5/1440, "15m": 15/1440, "30m": 30/1440,
            "1h": 1/24, "4h": 4/24, "1D": 1, "1W": 7, "1M": 30
        }
        
        days = days_map.get(timeframe, 30)
        max_days = min(days * limit, 365)  # Max 1 year
        
        url = f"{self.BASE_URL}/coins/{symbol.lower()}/ohlc"
        params = {
            "vs_currency": "usd",
            "days": str(int(max_days))
        }
        
        async with self.session.get(url, params=params, timeout=15) as response:
            if response.status == 200:
                data = await response.json()
                
                candles = []
                for item in data:
                    candles.append({
                        "timestamp": item[0] // 1000,  # Convert ms to seconds
                        "open": item[1],
                        "high": item[2],
                        "low": item[3],
                        "close": item[4],
                        "volume": 0  # Coingecko doesn't provide volume in OHLC
                    })
                
                # Resample based on timeframe
                resampled = self._resample_candles(candles, timeframe)
                
                # Cache the data
                self.historical_cache[cache_key] = (resampled, datetime.now(timezone.utc))
                
                return resampled[:limit]
            else:
                logger.warning(f"Could not fetch OHLCV for {symbol}, using simulated data")
                return self._generate_simulated_ohlcv(symbol, timeframe, limit)
    except Exception as e:
        logger.error(f"Error fetching OHLCV: {e}")
        return self._generate_simulated_ohlcv(symbol, timeframe, limit)

def _resample_candles(self, candles: List[Dict], timeframe: str) -> List[Dict]:
    """Resample candles to different timeframe"""
    if not candles:
        return []
    
    # For now, return as-is (Coingecko provides daily data)
    # In production, you would implement proper resampling
    return candles

def _generate_simulated_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[Dict]:
    """Generate simulated OHLCV data for symbols not in Coingecko"""
    candles = []
    base_price = np.random.uniform(10, 1000)
    current_time = datetime.now(timezone.utc).timestamp()
    
    # Time interval in seconds
    interval_map = {
        "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "4h": 14400, "1D": 86400, "1W": 604800, "1M": 2592000
    }
    interval = interval_map.get(timeframe, 86400)
    
    for i in range(limit):
        timestamp = current_time - (limit - i - 1) * interval
        
        # Generate random walk price
        if i == 0:
            price = base_price
        else:
            change = np.random.normal(0, 0.02)  # 2% daily volatility
            price = candles[-1]["close"] * (1 + change)
        
        # Generate OHLC
        open_price = price
        high_price = price * (1 + abs(np.random.normal(0, 0.01)))
        low_price = price * (1 - abs(np.random.normal(0, 0.01)))
        close_price = price * (1 + np.random.normal(0, 0.005))
        
        candles.append({
            "timestamp": timestamp,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": np.random.uniform(1000, 10000)
        })
    
    return candles

async def start_ticker_stream(self):
    """Start streaming ticker updates"""
    while True:
        try:
            await self.fetch_ticker_data()
            await asyncio.sleep(10)  # Update every 10 seconds
        except Exception as e:
            logger.error(f"Ticker stream error: {e}")
            await asyncio.sleep(30)
====================================================================================
ADVANCED TECHNICAL ANALYSIS ENGINE
====================================================================================
class TechnicalAnalysis:
"""Comprehensive technical analysis with 20+ indicators"""

text
@staticmethod
def calculate_all_indicators(ohlcv_data: List[Dict], symbol: str, timeframe: str) -> Dict:
    """Calculate all technical indicators for given OHLCV data"""
    if len(ohlcv_data) < 50:
        return {}
    
    # Extract data
    closes = [c["close"] for c in ohlcv_data]
    opens = [c["open"] for c in ohlcv_data]
    highs = [c["high"] for c in ohlcv_data]
    lows = [c["low"] for c in ohlcv_data]
    volumes = [c.get("volume", 0) for c in ohlcv_data]
    
    current_price = closes[-1]
    
    # Moving Averages
    sma_10 = TechnicalAnalysis.calculate_sma(closes, 10)
    sma_20 = TechnicalAnalysis.calculate_sma(closes, 20)
    sma_50 = TechnicalAnalysis.calculate_sma(closes, 50)
    sma_200 = TechnicalAnalysis.calculate_sma(closes, 200)
    
    ema_12 = TechnicalAnalysis.calculate_ema(closes, 12)
    ema_26 = TechnicalAnalysis.calculate_ema(closes, 26)
    
    # Momentum Indicators
    rsi = TechnicalAnalysis.calculate_rsi(closes, 14)
    macd_line, signal_line, histogram = TechnicalAnalysis.calculate_macd(closes)
    stoch_k, stoch_d = TechnicalAnalysis.calculate_stochastic(highs, lows, closes)
    
    # Volatility Indicators
    bb_upper, bb_middle, bb_lower = TechnicalAnalysis.calculate_bollinger_bands(closes)
    atr = TechnicalAnalysis.calculate_atr(highs, lows, closes)
    
    # Volume Indicators
    obv = TechnicalAnalysis.calculate_obv(closes, volumes)
    volume_sma = TechnicalAnalysis.calculate_sma(volumes, 20) if volumes[0] > 0 else []
    
    # Support & Resistance
    sr_levels = TechnicalAnalysis.detect_support_resistance(highs, lows, closes)
    
    # Fibonacci
    period_high = max(highs[-50:])
    period_low = min(lows[-50:])
    fibonacci = TechnicalAnalysis.calculate_fibonacci_retracement(period_high, period_low)
    
    # Chart Patterns
    patterns = TechnicalAnalysis.detect_chart_patterns(highs, lows, closes)
    
    # Trend Analysis
    trend = TechnicalAnalysis.analyze_trend(closes, sma_20, sma_50, sma_200)
    
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": current_price,
        "moving_averages": {
            "SMA_10": sma_10[-1] if sma_10[-1] else 0,
            "SMA_20": sma_20[-1] if sma_20[-1] else 0,
            "SMA_50": sma_50[-1] if sma_50[-1] else 0,
            "SMA_200": sma_200[-1] if sma_200[-1] else 0,
            "EMA_12": ema_12[-1] if ema_12[-1] else 0,
            "EMA_26": ema_26[-1] if ema_26[-1] else 0,
        },
        "momentum": {
            "RSI": rsi[-1] if rsi[-1] else 50,
            "MACD": macd_line[-1] if macd_line[-1] else 0,
            "MACD_Signal": signal_line[-1] if signal_line[-1] else 0,
            "MACD_Histogram": histogram[-1] if histogram[-1] else 0,
            "Stochastic_K": stoch_k[-1] if stoch_k[-1] else 50,
            "Stochastic_D": stoch_d[-1] if stoch_d[-1] else 50,
        },
        "volatility": {
            "BB_Upper": bb_upper[-1] if bb_upper[-1] else 0,
            "BB_Middle": bb_middle[-1] if bb_middle[-1] else 0,
            "BB_Lower": bb_lower[-1] if bb_lower[-1] else 0,
            "ATR": atr[-1] if atr[-1] else 0,
            "BB_Width": ((bb_upper[-1] - bb_lower[-1]) / bb_middle[-1]) if bb_middle[-1] else 0,
        },
        "volume": {
            "OBV": obv[-1] if obv else 0,
            "Volume_SMA": volume_sma[-1] if volume_sma and volume_sma[-1] else 0,
            "Volume_Ratio": volumes[-1] / volume_sma[-1] if volume_sma and volume_sma[-1] else 1,
        },
        "support_resistance": sr_levels,
        "fibonacci": fibonacci,
        "patterns": patterns,
        "trend": trend,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@staticmethod
def calculate_sma(data: List[float], period: int) -> List[float]:
    """Simple Moving Average"""
    if len(data) < period:
        return [None] * len(data)
    
    sma = []
    for i in range(len(data)):
        if i < period - 1:
            sma.append(None)
        else:
            sma.append(np.mean(data[i - period + 1:i + 1]))
    return sma

@staticmethod
def calculate_ema(data: List[float], period: int) -> List[float]:
    """Exponential Moving Average"""
    if len(data) < period:
        return [None] * len(data)
    
    ema = [None] * (period - 1)
    ema.append(np.mean(data[:period]))
    
    multiplier = 2 / (period + 1)
    for i in range(period, len(data)):
        ema.append((data[i] - ema[-1]) * multiplier + ema[-1])
    
    return ema

@staticmethod
def calculate_rsi(data: List[float], period: int = 14) -> List[float]:
    """Relative Strength Index"""
    if len(data) < period + 1:
        return [50] * len(data)
    
    deltas = np.diff(data)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    
    rs = up / down if down != 0 else 0
    rsi = [None] * period
    rsi.append(100 - 100 / (1 + rs))
    
    for i in range(period, len(deltas)):
        delta = deltas[i]
        if delta > 0:
            upval = delta
            downval = 0
        else:
            upval = 0
            downval = -delta
        
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        
        rs = up / down if down != 0 else 0
        rsi.append(100 - 100 / (1 + rs))
    
    return rsi

@staticmethod
def calculate_macd(data: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[List, List, List]:
    """MACD (Moving Average Convergence Divergence)"""
    ema_fast = TechnicalAnalysis.calculate_ema(data, fast)
    ema_slow = TechnicalAnalysis.calculate_ema(data, slow)
    
    macd_line = []
    for i in range(len(data)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line.append(ema_fast[i] - ema_slow[i])
        else:
            macd_line.append(None)
    
    # Signal line
    valid_macd = [x for x in macd_line if x is not None]
    signal_line = TechnicalAnalysis.calculate_ema(valid_macd, signal)
    
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
def calculate_bollinger_bands(data: List[float], period: int = 20, std_dev: int = 2) -> Tuple[List, List, List]:
    """Bollinger Bands"""
    sma = TechnicalAnalysis.calculate_sma(data, period)
    
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
def calculate_stochastic(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Tuple[List, List]:
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
    
    # %D (3-period SMA of %K)
    d_values = TechnicalAnalysis.calculate_sma([x for x in k_values if x is not None], 3)
    d_aligned = [None] * (len(k_values) - len(d_values)) + d_values
    
    return k_values, d_aligned

@staticmethod
def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    """Average True Range (volatility indicator)"""
    if len(closes) < 2:
        return [0] * len(closes)
    
    tr_values = [highs[0] - lows[0]]
    
    for i in range(1, len(closes)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr_values.append(max(hl, hc, lc))
    
    atr = TechnicalAnalysis.calculate_sma(tr_values, period)
    return atr

@staticmethod
def calculate_obv(closes: List[float], volumes: List[float]) -> List[float]:
    """On-Balance Volume"""
    if len(closes) < 2:
        return [0]
    
    obv = [volumes[0]]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    
    return obv

@staticmethod
def detect_support_resistance(highs: List[float], lows: List[float], closes: List[float], order: int = 5) -> Dict:
    """Detect support and resistance levels using local extrema"""
    if len(closes) < order * 2:
        return {"support": [], "resistance": []}
    
    # Find local maxima (resistance)
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
        "support": cluster_levels(support_levels)[-3:],  # Last 3 support levels
        "resistance": cluster_levels(resistance_levels)[-3:]  # Last 3 resistance levels
    }

@staticmethod
def calculate_fibonacci_retracement(high: float, low: float) -> Dict:
    """Calculate Fibonacci retracement levels"""
    diff = high - low
    
    return {
        "0.0": round(high, 4),
        "0.236": round(high - 0.236 * diff, 4),
        "0.382": round(high - 0.382 * diff, 4),
        "0.5": round(high - 0.5 * diff, 4),
        "0.618": round(high - 0.618 * diff, 4),
        "0.786": round(high - 0.786 * diff, 4),
        "1.0": round(low, 4),
        # Extensions
        "1.272": round(low - 0.272 * diff, 4),
        "1.618": round(low - 0.618 * diff, 4),
        "2.0": round(low - 1.0 * diff, 4),
        "2.618": round(low - 1.618 * diff, 4)
    }

@staticmethod
def detect_chart_patterns(highs: List[float], lows: List[float], closes: List[float]) -> List[Dict]:
    """Detect chart patterns: Head & Shoulders, Double Top/Bottom, Triangles"""
    patterns = []
    
    if len(closes) < 50:
        return patterns
    
    # Recent data for pattern detection
    recent_highs = highs[-50:]
    recent_lows = lows[-50:]
    recent_closes = closes[-50:]
    
    # 1. Head and Shoulders Pattern
    peaks = argrelextrema(np.array(recent_highs), np.greater, order=3)[0]
    if len(peaks) >= 3:
        # Check for 3 consecutive peaks where middle is highest
        for i in range(len(peaks) - 2):
            left = recent_highs[peaks[i]]
            head = recent_highs[peaks[i + 1]]
            right = recent_highs[peaks[i + 2]]
            
            # Head should be higher than shoulders
            if head > left and head > right and abs(left - right) / left < 0.05:
                patterns.append({
                    "type": "Head and Shoulders",
                    "signal": "BEARISH",
                    "confidence": 75,
                    "description": "Classic reversal pattern detected"
                })
                break
    
    # 2. Double Top Pattern
    if len(peaks) >= 2:
        for i in range(len(peaks) - 1):
            peak1 = recent_highs[peaks[i]]
            peak2 = recent_highs[peaks[i + 1]]
            
            # Two similar peaks
            if abs(peak1 - peak2) / peak1 < 0.03:
                patterns.append({
                    "type": "Double Top",
                    "signal": "BEARISH",
                    "confidence": 70,
                    "description": "Resistance level tested twice"
                })
                break
    
    # 3. Double Bottom Pattern
    troughs = argrelextrema(np.array(recent_lows), np.less, order=3)[0]
    if len(troughs) >= 2:
        for i in range(len(troughs) - 1):
            trough1 = recent_lows[troughs[i]]
            trough2 = recent_lows[troughs[i + 1]]
            
            # Two similar troughs
            if abs(trough1 - trough2) / trough1 < 0.03:
                patterns.append({
                    "type": "Double Bottom",
                    "signal": "BULLISH",
                    "confidence": 70,
                    "description": "Support level tested twice"
                })
                break
    
    # 4. Ascending Triangle
    if len(recent_closes) >= 20:
        recent_trend = linregress(range(20), recent_lows[-20:])
        if recent_trend.slope > 0:  # Rising lows
            resistance_level = max(recent_highs[-20:])
            touches = sum(1 for h in recent_highs[-20:] if abs(h - resistance_level) / resistance_level < 0.01)
            
            if touches >= 2:
                patterns.append({
                    "type": "Ascending Triangle",
                    "signal": "BULLISH",
                    "confidence": 65,
                    "description": "Bullish continuation pattern"
                })
    
    # 5. Descending Triangle
    if len(recent_closes) >= 20:
        recent_trend = linregress(range(20), recent_highs[-20:])
        if recent_trend.slope < 0:  # Falling highs
            support_level = min(recent_lows[-20:])
            touches = sum(1 for l in recent_lows[-20:] if abs(l - support_level) / support_level < 0.01)
            
            if touches >= 2:
                patterns.append({
                    "type": "Descending Triangle",
                    "signal": "BEARISH",
                    "confidence": 65,
                    "description": "Bearish continuation pattern"
                })
    
    # 6. Bullish Flag
    if len(recent_closes) >= 25:
        # Check for sharp rise followed by consolidation
        first_half = recent_closes[:15]
        second_half = recent_closes[15:]
        
        if len(first_half) >= 2 and len(second_half) >= 2:
            first_trend = linregress(range(len(first_half)), first_half)
            second_trend = linregress(range(len(second_half)), second_half)
            
            if first_trend.slope > 0 and abs(second_trend.slope) < 0.01:
                patterns.append({
                    "type": "Bullish Flag",
                    "signal": "BULLISH",
                    "confidence": 60,
                    "description": "Bullish continuation pattern"
                })
    
    return patterns

@staticmethod
def analyze_trend(closes: List[float], sma_20: List[float], sma_50: List[float], sma_200: List[float]) -> Dict:
    """Analyze market trend"""
    if len(closes) < 50:
        return {"direction": "NEUTRAL", "strength": 0, "description": "Insufficient data"}
    
    current_price = closes[-1]
    
    # Check moving averages alignment
    ma_alignment = 0
    
    if sma_20[-1] and sma_50[-1]:
        if sma_20[-1] > sma_50[-1]:
            ma_alignment += 1
    
    if sma_50[-1] and sma_200[-1]:
        if sma_50[-1] > sma_200[-1]:
            ma_alignment += 1
    
    if sma_20[-1] and sma_200[-1]:
        if sma_20[-1] > sma_200[-1]:
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
====================================================================================
AI SIGNAL ENGINE
====================================================================================
@dataclass
class TradingSignal:
symbol: str
timeframe: str
signal: str # STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL
confidence: float
price: float
targets: List[float]
stop_loss: float
risk_reward: float
indicators: Dict
patterns: List[Dict]
fibonacci: Dict
support_resistance: Dict
trend: Dict
timestamp: str

class AISignalEngine:
"""Advanced AI-powered signal generation"""

text
def __init__(self, ticker: CoinGeckoTicker):
    self.ticker = ticker
    self.ta = TechnicalAnalysis()

async def generate_signal(self, symbol: str, timeframe: str = "1D") -> TradingSignal:
    """Generate trading signal for a symbol and timeframe"""
    
    # Fetch OHLCV data
    ohlcv_data = await self.ticker.fetch_ohlcv(symbol, timeframe, 100)
    
    if len(ohlcv_data) < 30:
        return self._neutral_signal(symbol, timeframe)
    
    # Get symbol info
    symbol_info = await self.ticker.get_symbol_info(symbol)
    
    # Calculate all indicators
    analysis = self.ta.calculate_all_indicators(ohlcv_data, symbol, timeframe)
    
    if not analysis:
        return self._neutral_signal(symbol, timeframe)
    
    # Generate signal based on analysis
    signal_result = self._generate_signal_from_analysis(analysis, symbol_info)
    
    return signal_result

def _generate_signal_from_analysis(self, analysis: Dict, symbol_info: Optional[Dict]) -> TradingSignal:
    """Generate trading signal from technical analysis"""
    
    current_price = analysis["current_price"]
    indicators = analysis["momentum"]
    ma = analysis["moving_averages"]
    trend = analysis["trend"]
    
    # Calculate signal score
    score = 50  # Neutral starting point
    
    # RSI scoring
    rsi = indicators["RSI"]
    if rsi < 30:
        score += 15  # Oversold
    elif rsi > 70:
        score -= 15  # Overbought
    elif rsi < 45:
        score += 5
    elif rsi > 55:
        score -= 5
    
    # MACD scoring
    macd = indicators["MACD"]
    macd_signal = indicators["MACD_Signal"]
    if macd > macd_signal:
        score += 12
    else:
        score -= 12
    
    # Moving Average scoring
    price_above_sma20 = current_price > ma["SMA_20"]
    price_above_sma50 = current_price > ma["SMA_50"]
    sma20_above_sma50 = ma["SMA_20"] > ma["SMA_50"]
    
    if price_above_sma20:
        score += 5
    if price_above_sma50:
        score += 8
    if sma20_above_sma50:
        score += 7
    
    # Bollinger Bands scoring
    bb_upper = analysis["volatility"]["BB_Upper"]
    bb_lower = analysis["volatility"]["BB_Lower"]
    
    if current_price < bb_lower:
        score += 10  # Oversold
    elif current_price > bb_upper:
        score -= 10  # Overbought
    
    # Trend scoring
    if trend["direction"] == "STRONG_BULLISH":
        score += 20
    elif trend["direction"] == "BULLISH":
        score += 10
    elif trend["direction"] == "STRONG_BEARISH":
        score -= 20
    elif trend["direction"] == "BEARISH":
        score -= 10
    
    # Pattern scoring
    for pattern in analysis["patterns"]:
        if pattern["signal"] == "BULLISH":
            score += pattern["confidence"] / 10
        elif pattern["signal"] == "BEARISH":
            score -= pattern["confidence"] / 10
    
    # Normalize score
    score = max(0, min(100, score))
    
    # Determine signal type
    if score >= 80:
        signal_type = "STRONG_BUY"
        confidence = min(95, score)
    elif score >= 60:
        signal_type = "BUY"
        confidence = score
    elif score <= 20:
        signal_type = "STRONG_SELL"
        confidence = min(95, 100 - score)
    elif score <= 40:
        signal_type = "SELL"
        confidence = 100 - score
    else:
        signal_type = "NEUTRAL"
        confidence = 50
    
    # Calculate targets and stop loss
    atr_value = analysis["volatility"]["ATR"] or current_price * 0.02
    
    if signal_type in ["STRONG_BUY", "BUY"]:
        targets = [
            round(current_price * 1.02, 4),
            round(current_price * 1.04, 4),
            round(current_price * 1.06, 4),
            round(current_price * 1.08, 4)
        ]
        stop_loss = round(current_price * 0.98, 4)
    elif signal_type in ["STRONG_SELL", "SELL"]:
        targets = [
            round(current_price * 0.98, 4),
            round(current_price * 0.96, 4),
            round(current_price * 0.94, 4),
            round(current_price * 0.92, 4)
        ]
        stop_loss = round(current_price * 1.02, 4)
    else:
        targets = [current_price]
        stop_loss = current_price
    
    # Risk/Reward ratio
    risk = abs(current_price - stop_loss)
    reward = abs(targets[0] - current_price)
    risk_reward = round(reward / risk, 2) if risk > 0 else 0
    
    return TradingSignal(
        symbol=analysis["symbol"].upper(),
        timeframe=analysis["timeframe"],
        signal=signal_type,
        confidence=round(confidence, 1),
        price=current_price,
        targets=targets,
        stop_loss=stop_loss,
        risk_reward=risk_reward,
        indicators={
            "RSI": round(indicators["RSI"], 2),
            "MACD": round(macd, 4),
            "Stochastic_K": round(indicators["Stochastic_K"], 2),
            "Stochastic_D": round(indicators["Stochastic_D"], 2),
            "ATR": round(atr_value, 4),
            "BB_Width": round(analysis["volatility"]["BB_Width"], 4),
            "Volume_Ratio": round(analysis["volume"]["Volume_Ratio"], 2)
        },
        patterns=analysis["patterns"],
        fibonacci=analysis["fibonacci"],
        support_resistance=analysis["support_resistance"],
        trend=analysis["trend"],
        timestamp=analysis["timestamp"]
    )

def _neutral_signal(self, symbol: str, timeframe: str) -> TradingSignal:
    return TradingSignal(
        symbol=symbol.upper(),
        timeframe=timeframe,
        signal="NEUTRAL",
        confidence=50,
        price=0,
        targets=[0],
        stop_loss=0,
        risk_reward=0,
        indicators={},
        patterns=[],
        fibonacci={},
        support_resistance={"support": [], "resistance": []},
        trend={"direction": "NEUTRAL", "strength": 0, "description": "Insufficient data"},
        timestamp=datetime.now(timezone.utc).isoformat()
    )
====================================================================================
FASTAPI APPLICATION
====================================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
"""Application lifespan handler"""
logger.info("🚀 CryptoTrader Pro v6.0 Starting...")

text
# Initialize CoinGecko Ticker
ticker = CoinGeckoTicker()
await ticker.initialize()

# Initialize AI Engine
ai_engine = AISignalEngine(ticker)

# Start ticker stream in background
ticker_task = asyncio.create_task(ticker.start_ticker_stream())

# Store in app state
app.state.ticker = ticker
app.state.ai_engine = ai_engine
app.state.ticker_task = ticker_task

logger.info("✅ All systems operational")
logger.info("📊 CoinGecko Ticker: Streaming")
logger.info("🤖 AI Signal Engine: Ready")
logger.info("📈 Technical Analysis: 20+ Indicators")
logger.info("🎯 Support/Resistance Detection: Active")
logger.info("📐 Fibonacci Tools: Enabled")
logger.info("=" * 70)

yield

# Cleanup
ticker_task.cancel()
await ticker.close()
logger.info("🛑 CryptoTrader Pro Shutting Down")
app = FastAPI(
title="CryptoTrader Pro v6.0",
version="6.0.0",
docs_url="/docs",
redoc_url="/redoc",
lifespan=lifespan
)

app.add_middleware(
CORSMiddleware,
allow_origins=[""],
allow_credentials=True,
allow_methods=[""],
allow_headers=["*"],
)

Templates directory
templates = Jinja2Templates(directory="templates")

====================================================================================
HTML TEMPLATES
====================================================================================
def generate_dashboard_html(tier: SubscriptionTier = SubscriptionTier.PRO) -> str:
"""Generate modern, vibrant dashboard with ticker"""

text
tier_info = TIER_FEATURES[tier]

return f"""<!DOCTYPE html>
<html lang="en"> <head> <meta charset="UTF-8"> <meta name="viewport" content="width=device-width, initial-scale=1.0"> <title>CryptoTrader Pro v6.0 - Advanced Trading Platform</title> <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"> <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css"> <style> :root {{ --bg-dark: #0a0e27; --bg-card: #141b3d; --bg-card-hover: #1a2247; --accent-primary: #00d4ff; --accent-secondary: #ff3366; --accent-success: #00ff88; --accent-warning: #ffd600; --accent-danger: #ff3366; --text-primary: #ffffff; --text-secondary: #8b92b6; --border: #2a3356; }}
text
    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}
    
    body {{
        font-family: 'Inter', sans-serif;
        background: linear-gradient(135deg, #0a0e27 0%, #1a1f4d 100%);
        color: var(--text-primary);
        min-height: 100vh;
        overflow-x: hidden;
    }}
    
    .container {{
        max-width: 1800px;
        margin: 0 auto;
        padding: 20px;
    }}
    
    /* Ticker Container */
    .ticker-container {{
        background: var(--bg-card);
        border-bottom: 1px solid var(--border);
        overflow: hidden;
        height: 60px;
        position: relative;
        margin-bottom: 30px;
        border-radius: 12px;
    }}
    
    .ticker-wrapper {{
        display: flex;
        animation: ticker 120s linear infinite;
        white-space: nowrap;
        padding: 18px 0;
    }}
    
    .ticker-item {{
        display: flex;
        align-items: center;
        padding: 0 30px;
        border-right: 1px solid var(--border);
        cursor: pointer;
        transition: all 0.3s ease;
    }}
    
    .ticker-item:hover {{
        background: rgba(0, 212, 255, 0.1);
    }}
    
    .ticker-symbol {{
        font-weight: 700;
        font-size: 16px;
        margin-right: 12px;
        min-width: 70px;
    }}
    
    .ticker-price {{
        font-family: 'JetBrains Mono', monospace;
        font-weight: 600;
        font-size: 16px;
        margin-right: 12px;
        min-width: 110px;
    }}
    
    .ticker-change {{
        font-family: 'JetBrains Mono', monospace;
        font-weight: 600;
        font-size: 14px;
        padding: 4px 10px;
        border-radius: 6px;
        min-width: 80px;
        text-align: center;
    }}
    
    .positive {{
        background: rgba(0, 255, 136, 0.15);
        color: var(--accent-success);
    }}
    
    .negative {{
        background: rgba(255, 51, 102, 0.15);
        color: var(--accent-danger);
    }}
    
    @keyframes ticker {{
        0% {{ transform: translateX(0); }}
        100% {{ transform: translateX(-50%); }}
    }}
    
    /* Header */
    .header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 20px 0;
        margin-bottom: 30px;
    }}
    
    .logo {{
        font-size: 32px;
        font-weight: 900;
        background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -1px;
    }}
    
    .tier-badge {{
        padding: 10px 25px;
        background: linear-gradient(135deg, #ff3366, #ff6b9d);
        border-radius: 25px;
        font-weight: 700;
        font-size: 14px;
        text-transform: uppercase;
        letter-spacing: 1px;
        box-shadow: 0 4px 20px rgba(255, 51, 102, 0.4);
    }}
    
    /* Controls */
    .controls {{
        display: grid;
        grid-template-columns: 2fr 1fr 1fr;
        gap: 20px;
        margin-bottom: 30px;
    }}
    
    .search-box {{
        background: var(--bg-card);
        border: 2px solid var(--border);
        border-radius: 12px;
        padding: 0 20px;
        display: flex;
        align-items: center;
    }}
    
    .search-box i {{
        color: var(--text-secondary);
        margin-right: 12px;
        font-size: 18px;
    }}
    
    .search-box input {{
        background: transparent;
        border: none;
        color: var(--text-primary);
        font-size: 16px;
        padding: 18px 0;
        width: 100%;
        outline: none;
    }}
    
    .select-box {{
        background: var(--bg-card);
        border: 2px solid var(--border);
        border-radius: 12px;
        padding: 0 20px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        cursor: pointer;
        position: relative;
    }}
    
    .select-box select {{
        background: transparent;
        border: none;
        color: var(--text-primary);
        font-size: 16px;
        padding: 18px 0;
        width: 100%;
        outline: none;
        appearance: none;
        cursor: pointer;
    }}
    
    .select-box i {{
        color: var(--accent-primary);
        font-size: 14px;
    }}
    
    .btn-analyze {{
        background: linear-gradient(135deg, var(--accent-primary), #00a8cc);
        border: none;
        border-radius: 12px;
        color: white;
        font-size: 16px;
        font-weight: 700;
        padding: 0 30px;
        cursor: pointer;
        transition: all 0.3s ease;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
    }}
    
    .btn-analyze:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 30px rgba(0, 212, 255, 0.4);
    }}
    
    /* Main Grid */
    .main-grid {{
        display: grid;
        grid-template-columns: 2fr 1fr;
        gap: 20px;
        margin-bottom: 20px;
    }}
    
    /* Chart Container */
    .chart-container {{
        background: var(--bg-card);
        border: 2px solid var(--border);
        border-radius: 16px;
        overflow: hidden;
    }}
    
    .chart-header {{
        padding: 20px;
        border-bottom: 1px solid var(--border);
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    
    .chart-title {{
        font-size: 20px;
        font-weight: 700;
        display: flex;
        align-items: center;
        gap: 10px;
    }}
    
    .chart-title i {{
        color: var(--accent-primary);
    }}
    
    .chart-controls {{
        display: flex;
        gap: 10px;
    }}
    
    .timeframe-btn {{
        background: var(--bg-dark);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 8px 16px;
        color: var(--text-secondary);
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
    }}
    
    .timeframe-btn.active {{
        background: var(--accent-primary);
        color: white;
        border-color: var(--accent-primary);
    }}
    
    .btn-expand {{
        background: linear-gradient(135deg, var(--accent-secondary), #ff6b9d);
        border: none;
        border-radius: 8px;
        color: white;
        font-size: 14px;
        font-weight: 600;
        padding: 8px 20px;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 8px;
        transition: all 0.3s ease;
    }}
    
    .btn-expand:hover {{
        transform: translateY(-2px);
        box-shadow: 0 5px 20px rgba(255, 51, 102, 0.4);
    }}
    
    .chart-wrapper {{
        height: 550px;
        padding: 20px;
    }}
    
    /* Signal Panel */
    .signal-panel {{
        background: var(--bg-card);
        border: 2px solid var(--border);
        border-radius: 16px;
        overflow: hidden;
    }}
    
    .signal-header {{
        padding: 20px;
        border-bottom: 1px solid var(--border);
        display: flex;
        align-items: center;
        justify-content: space-between;
    }}
    
    .signal-title {{
        font-size: 20px;
        font-weight: 700;
        display: flex;
        align-items: center;
        gap: 10px;
    }}
    
    .ai-badge {{
        background: linear-gradient(135deg, #ff3366, #ff6b9d);
        padding: 6px 12px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 700;
    }}
    
    .signal-content {{
        padding: 30px 20px;
        text-align: center;
    }}
    
    .signal-type {{
        font-size: 36px;
        font-weight: 900;
        margin-bottom: 10px;
    }}
    
    .signal-buy {{
        color: var(--accent-success);
    }}
    
    .signal-sell {{
        color: var(--accent-danger);
    }}
    
    .signal-neutral {{
        color: var(--accent-warning);
    }}
    
    .signal-price {{
        font-size: 48px;
        font-weight: 900;
        font-family: 'JetBrains Mono', monospace;
        margin: 20px 0;
    }}
    
    /* Analysis Grid */
    .analysis-grid {{
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 20px;
        margin-top: 30px;
    }}
    
    .analysis-card {{
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 20px;
    }}
    
    .card-title {{
        color: var(--text-secondary);
        font-size: 14px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 15px;
        display: flex;
        align-items: center;
        gap: 10px;
    }}
    
    .indicator-grid {{
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 15px;
    }}
    
    .indicator-item {{
        background: var(--bg-dark);
        border-radius: 12px;
        padding: 15px;
    }}
    
    .indicator-label {{
        color: var(--text-secondary);
        font-size: 12px;
        font-weight: 600;
        margin-bottom: 5px;
    }}
    
    .indicator-value {{
        font-size: 20px;
        font-weight: 700;
        font-family: 'JetBrains Mono', monospace;
    }}
    
    /* Patterns */
    .patterns-list {{
        margin-top: 10px;
    }}
    
    .pattern-item {{
        background: var(--bg-dark);
        border-radius: 12px;
        padding: 15px;
        margin-bottom: 10px;
        border-left: 4px solid var(--accent-success);
    }}
    
    .pattern-item.bearish {{
        border-left-color: var(--accent-danger);
    }}
    
    .pattern-name {{
        font-weight: 700;
        font-size: 16px;
        margin-bottom: 5px;
    }}
    
    .pattern-desc {{
        color: var(--text-secondary);
        font-size: 13px;
    }}
    
    /* Fibonacci Levels */
    .fibo-grid {{
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 10px;
        margin-top: 10px;
    }}
    
    .fibo-level {{
        background: var(--bg-dark);
        border-radius: 8px;
        padding: 12px;
        text-align: center;
    }}
    
    .fibo-ratio {{
        color: var(--text-secondary);
        font-size: 11px;
        margin-bottom: 5px;
    }}
    
    .fibo-price {{
        color: var(--accent-primary);
        font-weight: 700;
        font-family: 'JetBrains Mono', monospace;
    }}
    
    /* Market Table */
    .market-table {{
        background: var(--bg-card);
        border: 2px solid var(--border);
        border-radius: 16px;
        padding: 20px;
        margin-top: 20px;
    }}
    
    table {{
        width: 100%;
        border-collapse: collapse;
    }}
    
    th {{
        color: var(--text-secondary);
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        padding: 15px;
        text-align: left;
        border-bottom: 2px solid var(--border);
    }}
    
    td {{
        padding: 15px;
        border-bottom: 1px solid var(--border);
    }}
    
    tr:hover {{
        background: var(--bg-card-hover);
    }}
    
    .coin-cell {{
        font-weight: 700;
        font-size: 14px;
        cursor: pointer;
    }}
    
    .coin-cell:hover {{
        color: var(--accent-primary);
    }}
    
    /* Modal */
    .modal {{
        display: none;
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.95);
        z-index: 10000;
        padding: 20px;
    }}
    
    .modal.active {{
        display: flex;
        align-items: center;
        justify-content: center;
    }}
    
    .modal-content {{
        background: var(--bg-card);
        border-radius: 20px;
        width: 95%;
        height: 90%;
        padding: 20px;
        position: relative;
    }}
    
    .modal-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding-bottom: 20px;
        border-bottom: 1px solid var(--border);
        margin-bottom: 20px;
    }}
    
    .modal-close {{
        background: var(--accent-danger);
        border: none;
        width: 40px;
        height: 40px;
        border-radius: 50%;
        color: white;
        font-size: 24px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
    }}
    
    /* Loading */
    .loading {{
        text-align: center;
        padding: 40px;
    }}
    
    .spinner {{
        border: 4px solid var(--border);
        border-top: 4px solid var(--accent-primary);
        border-radius: 50%;
        width: 50px;
        height: 50px;
        animation: spin 1s linear infinite;
        margin: 0 auto 20px;
    }}
    
    @keyframes spin {{
        0% {{ transform: rotate(0deg); }}
        100% {{ transform: rotate(360deg); }}
    }}
</style>
</head> <body> <div class="container"> <!-- Ticker Bar --> <div class="ticker-container"> <div class="ticker-wrapper" id="tickerWrapper"> <!-- Ticker items will be populated by JavaScript --> </div> </div>
text
    <!-- Header -->
    <div class="header">
        <div class="logo">
            <i class="fas fa-bolt"></i> CryptoTrader Pro v6.0
        </div>
        <div class="tier-badge">
            <i class="fas fa-crown"></i> {tier_info['name']} Tier
        </div>
    </div>
    
    <!-- Controls -->
    <div class="controls">
        <div class="search-box">
            <i class="fas fa-search"></i>
            <input type="text" id="symbolSearch" placeholder="Search symbol (BTC, ETH, EURUSD, etc.)" autocomplete="off">
        </div>
        
        <div class="select-box">
            <select id="timeframeSelect">
                <option value="1m">1 Minute</option>
                <option value="5m">5 Minutes</option>
                <option value="15m">15 Minutes</option>
                <option value="30m">30 Minutes</option>
                <option value="1h">1 Hour</option>
                <option value="4h">4 Hours</option>
                <option value="1D" selected>1 Day</option>
                <option value="1W">1 Week</option>
                <option value="1M">1 Month</option>
            </select>
            <i class="fas fa-chevron-down"></i>
        </div>
        
        <button class="btn-analyze" id="analyzeBtn">
            <i class="fas fa-brain"></i> Analyze Symbol
        </button>
    </div>
    
    <!-- Main Grid -->
    <div class="main-grid">
        <!-- Chart Section -->
        <div class="chart-container">
            <div class="chart-header">
                <div class="chart-title">
                    <i class="fas fa-chart-line"></i>
                    <span id="chartSymbol">BTC/USD</span> - 
                    <span id="chartTimeframe">1D</span>
                </div>
                <div class="chart-controls">
                    <div class="timeframe-buttons">
                        <button class="timeframe-btn active" data-tf="1D">1D</button>
                        <button class="timeframe-btn" data-tf="4h">4H</button>
                        <button class="timeframe-btn" data-tf="1h">1H</button>
                        <button class="timeframe-btn" data-tf="15m">15M</button>
                    </div>
                    <button class="btn-expand" id="expandChartBtn">
                        <i class="fas fa-expand"></i> Expand
                    </button>
                </div>
            </div>
            <div class="chart-wrapper">
                <div id="tradingview_chart" style="height: 100%;"></div>
            </div>
        </div>
        
        <!-- Signal Panel -->
        <div class="signal-panel">
            <div class="signal-header">
                <div class="signal-title">
                    <i class="fas fa-robot"></i> AI Signal
                </div>
                <div class="ai-badge">AI v3.0</div>
            </div>
            
            <div class="signal-content" id="signalContent">
                <div class="loading">
                    <div class="spinner"></div>
                    <p>Waiting for symbol analysis...</p>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Analysis Grid -->
    <div class="analysis-grid">
        <!-- Technical Indicators -->
        <div class="analysis-card">
            <div class="card-title">
                <i class="fas fa-chart-bar"></i> Technical Indicators
            </div>
            <div class="indicator-grid" id="indicatorsGrid">
                <!-- Indicators will be populated by JavaScript -->
            </div>
        </div>
        
        <!-- Chart Patterns -->
        <div class="analysis-card">
            <div class="card-title">
                <i class="fas fa-shapes"></i> Chart Patterns
            </div>
            <div class="patterns-list" id="patternsList">
                <div style="color: var(--text-secondary); text-align: center; padding: 20px;">
                    No patterns detected
                </div>
            </div>
        </div>
        
        <!-- Fibonacci Levels -->
        <div class="analysis-card">
            <div class="card-title">
                <i class="fas fa-ruler-combined"></i> Fibonacci Levels
            </div>
            <div class="fibo-grid" id="fiboGrid">
                <!-- Fibonacci levels will be populated by JavaScript -->
            </div>
        </div>
        
        <!-- Support & Resistance -->
        <div class="analysis-card">
            <div class="card-title">
                <i class="fas fa-bullseye"></i> Support & Resistance
            </div>
            <div class="sr-grid" style="margin-top: 10px;">
                <div style="margin-bottom: 15px;">
                    <div style="color: var(--accent-danger); font-size: 12px; font-weight: 600; margin-bottom: 10px;">RESISTANCE</div>
                    <div id="resistanceLevels" style="color: var(--text-secondary);">
                        No levels detected
                    </div>
                </div>
                <div>
                    <div style="color: var(--accent-success); font-size: 12px; font-weight: 600; margin-bottom: 10px;">SUPPORT</div>
                    <div id="supportLevels" style="color: var(--text-secondary);">
                        No levels detected
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Market Overview Table -->
    <div class="market-table">
        <div class="card-title" style="margin-bottom: 20px;">
            <i class="fas fa-globe"></i> Market Overview
        </div>
        <table>
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Price</th>
                    <th>24h Change</th>
                    <th>Volume</th>
                    <th>Market Cap</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody id="marketTableBody">
                <tr><td colspan="6" style="text-align: center; padding: 40px;">Loading market data...</td></tr>
            </tbody>
        </table>
    </div>
</div>

<!-- Expanded Chart Modal -->
<div class="modal" id="chartModal">
    <div class="modal-content">
        <div class="modal-header">
            <h2 style="font-size: 24px; font-weight: 700;">
                <i class="fas fa-chart-line"></i>
                <span id="modalSymbol">BTC/USD</span> - Full Screen Chart
            </h2>
            <button class="modal-close" id="closeModalBtn">
                <i class="fas fa-times"></i>
            </button>
        </div>
        <div id="tradingview_expanded" style="height: calc(100% - 80px);"></div>
    </div>
</div>

<!-- TradingView Widget Script -->
<script src="https://s3.tradingview.com/tv.js"></script>

<script>
    // Global variables
    let currentSymbol = 'bitcoin';
    let currentTimeframe = '1D';
    let chartWidget = null;
    let expandedWidget = null;
    let tickerData = [];
    
    // TradingView symbol mapping
    const tradingViewSymbols = {{
        'bitcoin': 'BINANCE:BTCUSDT',
        'ethereum': 'BINANCE:ETHUSDT',
        'binancecoin': 'BINANCE:BNBUSDT',
        'ripple': 'BINANCE:XRPUSDT',
        'cardano': 'BINANCE:ADAUSDT',
        'solana': 'BINANCE:SOLUSDT',
        'polkadot': 'BINANCE:DOTUSDT',
        'dogecoin': 'BINANCE:DOGEUSDT',
        'avalanche-2': 'BINANCE:AVAXUSDT',
        'chainlink': 'BINANCE:LINKUSDT',
        'polygon': 'BINANCE:MATICUSDT',
        'uniswap': 'BINANCE:UNIUSDT',
        'litecoin': 'BINANCE:LTCUSDT',
        'bitcoin-cash': 'BINANCE:BCHUSDT',
        'stellar': 'BINANCE:XLMUSDT',
        'usd': 'FX:USDUSD',
        'eur': 'FX:EURUSD',
        'gbp': 'FX:GBPUSD',
        'jpy': 'FX:JPYUSD',
        'gold': 'FX:XAUUSD',
        'silver': 'FX:XAGUSD',
        'sp500': 'AMEX:SPY',
        'nasdaq': 'NASDAQ:QQQ',
        'dowjones': 'DOW:DJI'
    }};
    
    // Initialize TradingView chart
    function initChart(containerId, symbol, timeframe) {{
        const symbolKey = tradingViewSymbols[symbol] || `BINANCE:${{symbol.toUpperCase()}}USDT`;
        
        const widget = new TradingView.widget({{
            "width": "100%",
            "height": containerId === 'tradingview_chart' ? 500 : "100%",
            "symbol": symbolKey,
            "interval": getInterval(timeframe),
            "timezone": "Etc/UTC",
            "theme": "dark",
            "style": "1",
            "locale": "en",
            "toolbar_bg": "#0a0e27",
            "enable_publishing": false,
            "hide_side_toolbar": false,
            "allow_symbol_change": true,
            "container_id": containerId,
            "studies": [
                "RSI@tv-basicstudies",
                "MACD@tv-basicstudies",
                "StochasticRSI@tv-basicstudies",
                "BB@tv-basicstudies",
                "Volume@tv-basicstudies",
                "EMA@tv-basicstudies"
            ],
            "overrides": {{
                "paneProperties.background": "#0a0e27",
                "paneProperties.vertGridProperties.color": "#1a2247",
                "paneProperties.horzGridProperties.color": "#1a2247",
                "symbolWatermarkProperties.transparency": 90,
                "scalesProperties.textColor" : "#8b92b6"
            }},
            "disabled_features": ["header_widget", "left_toolbar"],
            "enabled_features": ["study_templates"]
        }});
        
        return widget;
    }}
    
    function getInterval(timeframe) {{
        const intervals = {{
            '1m': '1', '5m': '5', '15m': '15', '30m': '30',
            '1h': '60', '4h': '240', '1D': 'D', '1W': 'W', '1M': 'M'
        }};
        return intervals[timeframe] || 'D';
    }}
    
    // Fetch ticker data
    async function fetchTickerData() {{
        try {{
            const response = await fetch('/api/ticker');
            const data = await response.json();
            
            if (data.success && data.ticker) {{
                tickerData = data.ticker;
                updateTickerBar();
                updateMarketTable();
            }}
        }} catch (error) {{
            console.error('Error fetching ticker data:', error);
        }}
    }}
    
    // Update ticker bar
    function updateTickerBar() {{
        const wrapper = document.getElementById('tickerWrapper');
        wrapper.innerHTML = '';
        
        // Create two copies for seamless looping
        const items = [...tickerData, ...tickerData];
        
        items.forEach(item => {{
            const tickerItem = document.createElement('div');
            tickerItem.className = 'ticker-item';
            tickerItem.dataset.symbol = item.id;
            
            const changeClass = item.change_24h >= 0 ? 'positive' : 'negative';
            const changeSign = item.change_24h >= 0 ? '+' : '';
            
            tickerItem.innerHTML = `
                <div class="ticker-symbol">${{item.symbol}}</div>
                <div class="ticker-price">$${{item.price.toFixed(4)}}</div>
                <div class="ticker-change ${{changeClass}}">
                    ${{changeSign}}${{item.change_24h.toFixed(2)}}%
                </div>
            `;
            
            tickerItem.addEventListener('click', () => {{
                currentSymbol = item.id;
                document.getElementById('symbolSearch').value = item.symbol;
                updateChart();
                fetchSignal();
            }});
            
            wrapper.appendChild(tickerItem);
        }});
    }}
    
    // Update market table
    function updateMarketTable() {{
        const tbody = document.getElementById('marketTableBody');
        tbody.innerHTML = '';
        
        tickerData.slice(0, 15).forEach(item => {{
            const row = document.createElement('tr');
            const changeClass = item.change_24h >= 0 ? 'positive' : 'negative';
            const changeSign = item.change_24h >= 0 ? '+' : '';
            
            row.innerHTML = `
                <td class="coin-cell" data-symbol="${{item.id}}">
                    <i class="fas fa-coins" style="margin-right: 8px; color: var(--accent-warning);"></i>
                    ${{item.symbol}}
                </td>
                <td>$${{item.price.toFixed(4)}}</td>
                <td class="${{changeClass}}">${{changeSign}}${{item.change_24h.toFixed(2)}}%</td>
                <td>$$${{(item.volume_24h / 1e6).toFixed(2)}}M</td>
                <td>$$${{(item.market_cap / 1e9).toFixed(2)}}B</td>
                <td>
                    <button class="timeframe-btn" style="padding: 5px 10px; font-size: 12px;" data-symbol="${{item.id}}">
                        <i class="fas fa-chart-line"></i> Analyze
                    </button>
                </td>
            `;
            
            // Add click handler to coin cell
            row.querySelector('.coin-cell').addEventListener('click', () => {{
                currentSymbol = item.id;
                document.getElementById('symbolSearch').value = item.symbol;
                updateChart();
                fetchSignal();
            }});
            
            // Add click handler to analyze button
            row.querySelector('button').addEventListener('click', () => {{
                currentSymbol = item.id;
                document.getElementById('symbolSearch').value = item.symbol;
                updateChart();
                fetchSignal();
            }});
            
            tbody.appendChild(row);
        }});
    }}
    
    // Update chart
    function updateChart() {{
        if (chartWidget) {{
            chartWidget.remove();
        }}
        
        chartWidget = initChart('tradingview_chart', currentSymbol, currentTimeframe);
        document.getElementById('chartSymbol').textContent = currentSymbol.toUpperCase();
        document.getElementById('chartTimeframe').textContent = currentTimeframe;
        document.getElementById('modalSymbol').textContent = currentSymbol.toUpperCase();
    }}
    
    // Fetch AI signal
    async function fetchSignal() {{
        try {{
            const signalContent = document.getElementById('signalContent');
            signalContent.innerHTML = `
                <div class="loading">
                    <div class="spinner"></div>
                    <p>Analyzing ${{currentSymbol.toUpperCase()}}...</p>
                </div>
            `;
            
            const response = await fetch(`/api/signal/${{currentSymbol}}?timeframe=${{currentTimeframe}}`);
            const data = await response.json();
            
            if (data.success && data.signal) {{
                displaySignal(data.signal);
            }} else {{
                signalContent.innerHTML = `
                    <div style="color: var(--accent-danger); text-align: center; padding: 40px;">
                        <i class="fas fa-exclamation-triangle" style="font-size: 48px; margin-bottom: 20px;"></i>
                        <p>Error loading signal</p>
                    </div>
                `;
            }}
        }} catch (error) {{
            console.error('Error fetching signal:', error);
        }}
    }}
    
    // Display signal
    function displaySignal(signal) {{
        const signalContent = document.getElementById('signalContent');
        const signalClass = signal.signal.includes('BUY') ? 'signal-buy' : 
                           signal.signal.includes('SELL') ? 'signal-sell' : 'signal-neutral';
        
        // Format price with appropriate decimals
        const priceFormat = signal.price >= 1000 ? '0,0.00' : 
                           signal.price >= 100 ? '0,0.000' : 
                           signal.price >= 10 ? '0,0.0000' : '0,0.00000';
        
        signalContent.innerHTML = `
            <div class="signal-type ${{signalClass}}">${{signal.signal}}</div>
            <div style="color: var(--text-secondary); font-size: 14px; margin-top: 5px;">
                Confidence: <span style="color: var(--accent-primary); font-weight: 700;">${{signal.confidence}}%</span>
            </div>
            
            <div class="signal-price">$${{signal.price.toFixed(signal.price >= 100 ? 2 : 4)}}</div>
            
            <div style="margin-top: 20px;">
                <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px;">
                    Targets
                </div>
                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 20px;">
                    ${{signal.targets.slice(0, 4).map((t, i) => `
                        <div style="background: var(--bg-dark); padding: 10px; border-radius: 8px; text-align: center;">
                            <div style="font-size: 10px; color: var(--text-secondary);">T${{i+1}}</div>
                            <div style="font-family: 'JetBrains Mono', monospace; font-weight: 700; color: var(--accent-success);">
                                $${{t.toFixed(signal.price >= 100 ? 2 : 4)}}
                            </div>
                        </div>
                    `).join('')}}
                </div>
                
                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px;">
                    <div style="background: var(--bg-dark); padding: 12px; border-radius: 8px;">
                        <div style="font-size: 10px; color: var(--text-secondary);">Stop Loss</div>
                        <div style="font-family: 'JetBrains Mono', monospace; font-weight: 700; color: var(--accent-danger);">
                            $${{signal.stop_loss.toFixed(signal.price >= 100 ? 2 : 4)}}
                        </div>
                    </div>
                    <div style="background: var(--bg-dark); padding: 12px; border-radius: 8px;">
                        <div style="font-size: 10px; color: var(--text-secondary);">Risk/Reward</div>
                        <div style="font-family: 'JetBrains Mono', monospace; font-weight: 700; color: var{{signal.risk_reward >= 1 ? '--accent-success' : '--accent-warning'}};">
                            ${{signal.risk_reward.toFixed(2)}}x
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Update indicators
        updateIndicators(signal.indicators);
        
        // Update patterns
        updatePatterns(signal.patterns);
        
        // Update Fibonacci
        updateFibonacci(signal.fibonacci);
        
        // Update Support/Resistance
        updateSupportResistance(signal.support_resistance);
    }}
    
    // Update indicators
    function updateIndicators(indicators) {{
        const grid = document.getElementById('indicatorsGrid');
        
        if (!indicators || Object.keys(indicators).length === 0) {{
            grid.innerHTML = '<div style="color: var(--text-secondary); text-align: center; padding: 20px;">No indicators available</div>';
            return;
        }}
        
        const items = Object.entries(indicators).slice(0, 8);
        grid.innerHTML = items.map(([key, value]) => `
            <div class="indicator-item">
                <div class="indicator-label">${{key}}</div>
                <div class="indicator-value">${{typeof value === 'number' ? value.toFixed(4) : value}}</div>
            </div>
        `).join('');
    }}
    
    // Update patterns
    function updatePatterns(patterns) {{
        const list = document.getElementById('patternsList');
        
        if (!patterns || patterns.length === 0) {{
            list.innerHTML = '<div style="color: var(--text-secondary); text-align: center; padding: 20px;">No patterns detected</div>';
            return;
        }}
        
        list.innerHTML = patterns.map(pattern => `
            <div class="pattern-item ${{pattern.signal === 'BEARISH' ? 'bearish' : ''}}">
                <div class="pattern-name">${{pattern.type}}</div>
                <div class="pattern-desc">
                    ${{pattern.description}} • Confidence: <span style="color: var(--accent-primary); font-weight: 700;">${{pattern.confidence}}%</span>
                </div>
            </div>
        `).join('');
    }}
    
    // Update Fibonacci levels
    function updateFibonacci(fibonacci) {{
        const grid = document.getElementById('fiboGrid');
        
        if (!fibonacci || Object.keys(fibonacci).length === 0) {{
            grid.innerHTML = '<div style="color: var(--text-secondary); text-align: center; padding: 20px; grid-column: 1 / -1;">No Fibonacci levels</div>';
            return;
        }}
        
        const importantLevels = ['0.0', '0.236', '0.382', '0.5', '0.618', '0.786', '1.0', '1.618'];
        
        grid.innerHTML = importantLevels.map(level => `
            <div class="fibo-level">
                <div class="fibo-ratio">${{level}}</div>
                <div class="fibo-price">$${{fibonacci[level]?.toFixed(4) || 'N/A'}}</div>
            </div>
        `).join('');
    }}
    
    // Update support and resistance
    function updateSupportResistance(sr) {{
        const resistanceDiv = document.getElementById('resistanceLevels');
        const supportDiv = document.getElementById('supportLevels');
        
        if (sr.resistance && sr.resistance.length > 0) {{
            resistanceDiv.innerHTML = sr.resistance.map(level => `
                <div style="background: rgba(255, 51, 102, 0.1); padding: 8px 12px; border-radius: 6px; margin-bottom: 5px; font-family: 'JetBrains Mono', monospace; font-weight: 600;">
                    $${{level.toFixed(4)}}
                </div>
            `).join('');
        }} else {{
            resistanceDiv.innerHTML = '<div style="color: var(--text-secondary);">No resistance levels</div>';
        }}
        
        if (sr.support && sr.support.length > 0) {{
            supportDiv.innerHTML = sr.support.map(level => `
                <div style="background: rgba(0, 255, 136, 0.1); padding: 8px 12px; border-radius: 6px; margin-bottom: 5px; font-family: 'JetBrains Mono', monospace; font-weight: 600;">
                    $${{level.toFixed(4)}}
                </div>
            `).join('');
        }} else {{
            supportDiv.innerHTML = '<div style="color: var(--text-secondary);">No support levels</div>';
        }}
    }}
    
    // Event Listeners
    document.getElementById('symbolSearch').addEventListener('keypress', (e) => {{
        if (e.key === 'Enter') {{
            const symbol = e.target.value.toLowerCase();
            if (symbol) {{
                currentSymbol = symbol;
                updateChart();
                fetchSignal();
            }}
        }}
    }});
    
    document.getElementById('timeframeSelect').addEventListener('change', (e) => {{
        currentTimeframe = e.target.value;
        updateChart();
        fetchSignal();
        
        // Update timeframe buttons
        document.querySelectorAll('.timeframe-btn').forEach(btn => {{
            btn.classList.remove('active');
            if (btn.dataset.tf === currentTimeframe) {{
                btn.classList.add('active');
            }}
        }});
    }});
    
    document.getElementById('analyzeBtn').addEventListener('click', () => {{
        const symbol = document.getElementById('symbolSearch').value.toLowerCase();
        if (symbol) {{
            currentSymbol = symbol;
            updateChart();
            fetchSignal();
        }}
    }});
    
    document.getElementById('expandChartBtn').addEventListener('click', () => {{
        document.getElementById('chartModal').classList.add('active');
        if (!expandedWidget) {{
            expandedWidget = initChart('tradingview_expanded', currentSymbol, currentTimeframe);
        }}
    }});
    
    document.getElementById('closeModalBtn').addEventListener('click', () => {{
        document.getElementById('chartModal').classList.remove('active');
    }});
    
    // Timeframe buttons
    document.querySelectorAll('.timeframe-btn').forEach(btn => {{
        btn.addEventListener('click', () => {{
            currentTimeframe = btn.dataset.tf;
            document.getElementById('timeframeSelect').value = currentTimeframe;
            updateChart();
            fetchSignal();
            
            document.querySelectorAll('.timeframe-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        }});
    }});
    
    // Initialize
    window.addEventListener('load', () => {{
        updateChart();
        fetchTickerData();
        fetchSignal();
        
        // Refresh ticker every 10 seconds
        setInterval(fetchTickerData, 10000);
    }});
</script>
</body> </html> """
====================================================================================
API ENDPOINTS
====================================================================================
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
"""Main dashboard"""
html = generate_dashboard_html(SubscriptionTier.PRO)
return HTMLResponse(html)

@app.get("/api/ticker")
async def get_ticker(request: Request):
"""Get ticker data"""
try:
ticker = request.app.state.ticker

text
    # Fetch ticker data if not recently updated
    if not ticker.ticker_data or (datetime.now(timezone.utc) - ticker.last_update).total_seconds() > 10:
        await ticker.fetch_ticker_data()
    
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker.ticker_data,
        "count": len(ticker.ticker_data)
    }
except Exception as e:
    logger.error(f"Ticker error: {e}")
    return {"success": False, "error": str(e)}
@app.get("/api/symbol/{symbol}")
async def get_symbol_info(symbol: str, request: Request):
"""Get symbol information"""
try:
ticker = request.app.state.ticker

text
    info = await ticker.get_symbol_info(symbol)
    
    if info:
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": info
        }
    else:
        return {"success": False, "error": "Symbol not found"}
except Exception as e:
    logger.error(f"Symbol info error: {e}")
    return {"success": False, "error": str(e)}
@app.get("/api/signal/{symbol}")
async def get_signal(symbol: str, request: Request, timeframe: str = Query("1D", enum=["1m", "5m", "15m", "30m", "1h", "4h", "1D", "1W", "1M"])):
"""Get AI trading signal for a symbol"""
try:
ai_engine = request.app.state.ai_engine

text
    # Generate signal
    signal = await ai_engine.generate_signal(symbol, timeframe)
    
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "signal": asdict(signal)
    }
except Exception as e:
    logger.error(f"Signal generation error: {e}")
    return {"success": False, "error": str(e)}
@app.get("/api/analysis/{symbol}")
async def get_technical_analysis(symbol: str, request: Request, timeframe: str = Query("1D"), limit: int = Query(100, ge=10, le=500)):
"""Get comprehensive technical analysis"""
try:
ticker = request.app.state.ticker
ta = TechnicalAnalysis()

text
    # Fetch OHLCV data
    ohlcv = await ticker.fetch_ohlcv(symbol, timeframe, limit)
    
    if len(ohlcv) < 20:
        return {"success": False, "error": "Insufficient data for analysis"}
    
    # Calculate analysis
    analysis = ta.calculate_all_indicators(ohlcv, symbol, timeframe)
    
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_count": len(ohlcv),
        "analysis": analysis
    }
except Exception as e:
    logger.error(f"Technical analysis error: {e}")
    return {"success": False, "error": str(e)}
@app.get("/health")
async def health():
"""Health check"""
return {
"status": "healthy",
"version": "6.0.0",
"timestamp": datetime.now(timezone.utc).isoformat(),
"services": {
"coingecko_ticker": "operational",
"ai_engine": "operational",
"technical_analysis": "operational",
"signal_generation": "operational"
}
}

====================================================================================
STARTUP
====================================================================================
if name == "main":
import uvicorn

text
port = int(os.getenv("PORT", 8000))

logger.info("=" * 70)
logger.info("🚀 CRYPTOTRADER PRO v6.0 - ADVANCED TRADING PLATFORM")
logger.info("=" * 70)
logger.info(f"🌐 Server: http://0.0.0.0:{port}")
logger.info("📊 Features:")
logger.info("   • Real-time CoinGecko ticker with streaming updates")
logger.info("   • TradingView integration with click-to-expand charts")
logger.info("   • 20+ Technical indicators (RSI, MACD, Bollinger Bands, etc.)")
logger.info("   • Fibonacci retracement & extension levels")
logger.info("   • Support & Resistance detection")
logger.info("   • Chart pattern recognition (Head & Shoulders, Triangles, etc.)")
logger.info("   • AI-powered trading signals with risk/reward analysis")
logger.info("   • Multi-timeframe analysis (1m to 1M)")
logger.info("   • Support for Crypto, Forex, and Indices")
logger.info("=" * 70)

uvicorn.run(
    app,
    host="0.0.0.0",
    port=port,
    log_level="info"
)
 
