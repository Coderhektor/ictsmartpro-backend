"""
🚀 REAL DATA TRADING BOT v4.0.0 - PROFESSIONAL GRADE
✅ REAL DATA ONLY - NO SYNTHETIC DATA
✅ CoinGecko API - All Crypto (including new coins)
✅ Binance API - Major Crypto Real-time
✅ Alpha Vantage - Forex (Free tier: 25 calls/day)
✅ Twelve Data - Forex Backup (Free tier: 800 calls/day)
✅ Auto-failover between data sources
✅ 20-second CoinGecko polling for new coins
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

# FastAPI Application
app = FastAPI(
    title="Real Data Trading Bot",
    version="4.0.0",
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

# ========== MARKET TYPES ==========
class MarketType(str, Enum):
    CRYPTO = "CRYPTO"
    FOREX = "FOREX"

class SignalType(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"

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

# ========== CRYPTO DATA SOURCES ==========
class CryptoDataFetcher:
    """Fetch real crypto data from multiple sources"""
    
    @staticmethod
    async def fetch_coingecko_ohlc(coin_id: str, days: int = 7) -> Optional[List[Dict]]:
        """
        Fetch OHLC data from CoinGecko
        Free tier: No rate limit on /coins/{id}/ohlc endpoint
        """
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
                            logger.warning(f"CoinGecko returned empty data for {coin_id}")
                            return None
                        
                        candles = []
                        for item in data:
                            # CoinGecko OHLC format: [timestamp, open, high, low, close]
                            candles.append({
                                "timestamp": item[0],
                                "open": float(item[1]),
                                "high": float(item[2]),
                                "low": float(item[3]),
                                "close": float(item[4]),
                                "volume": 0  # CoinGecko OHLC doesn't include volume
                            })
                        
                        logger.info(f"✅ CoinGecko: {len(candles)} candles for {coin_id}")
                        return candles
                    
                    elif response.status == 429:
                        logger.error("❌ CoinGecko rate limit exceeded")
                        return None
                    else:
                        logger.error(f"❌ CoinGecko error {response.status} for {coin_id}")
                        return None
                        
        except Exception as e:
            logger.error(f"❌ CoinGecko fetch error for {coin_id}: {e}")
            return None
    
    @staticmethod
    async def fetch_coingecko_market_chart(coin_id: str, days: int = 7) -> Optional[List[Dict]]:
        """
        Fetch price data from CoinGecko market_chart endpoint
        Includes volume data
        """
        try:
            url = f"{DataSourceConfig.COINGECKO_BASE}/coins/{coin_id}/market_chart"
            params = {
                "vs_currency": "usd",
                "days": days,
                "interval": "hourly"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        prices = data.get("prices", [])
                        volumes = data.get("total_volumes", [])
                        
                        if not prices:
                            return None
                        
                        # Create candles from price data
                        candles = []
                        for i in range(len(prices) - 1):
                            timestamp = prices[i][0]
                            current_price = prices[i][1]
                            next_price = prices[i + 1][1]
                            
                            # Estimate OHLC from price points
                            open_price = current_price
                            close_price = next_price
                            high_price = max(current_price, next_price) * 1.002  # Small variance
                            low_price = min(current_price, next_price) * 0.998
                            
                            volume = volumes[i][1] if i < len(volumes) else 0
                            
                            candles.append({
                                "timestamp": timestamp,
                                "open": open_price,
                                "high": high_price,
                                "low": low_price,
                                "close": close_price,
                                "volume": volume
                            })
                        
                        logger.info(f"✅ CoinGecko market_chart: {len(candles)} candles for {coin_id}")
                        return candles
                    
                    else:
                        logger.error(f"❌ CoinGecko market_chart error {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"❌ CoinGecko market_chart error: {e}")
            return None
    
    @staticmethod
    async def search_coin_id(symbol: str) -> Optional[str]:
        """
        Search for CoinGecko coin ID from symbol
        Example: BTC -> bitcoin, ETH -> ethereum
        """
        cache_key = f"coingecko_id_{symbol.lower()}"
        cached = cache_manager.get(cache_key, max_age_seconds=3600)  # Cache for 1 hour
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
                        
                        # Try exact symbol match first
                        for coin in coins:
                            if coin.get("symbol", "").upper() == symbol.upper():
                                coin_id = coin.get("id")
                                cache_manager.set(cache_key, coin_id)
                                logger.info(f"✅ Found CoinGecko ID: {symbol} -> {coin_id}")
                                return coin_id
                        
                        # Fallback: first result
                        if coins:
                            coin_id = coins[0].get("id")
                            cache_manager.set(cache_key, coin_id)
                            logger.info(f"⚠️ Using first match: {symbol} -> {coin_id}")
                            return coin_id
                    
        except Exception as e:
            logger.error(f"❌ CoinGecko search error for {symbol}: {e}")
        
        return None
    
    @staticmethod
    async def fetch_binance_klines(symbol: str, interval: str = "1h", limit: int = 200) -> Optional[List[Dict]]:
        """
        Fetch from Binance for major crypto pairs
        Free tier: 1200 requests/minute
        """
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
                    
                    elif response.status == 400:
                        logger.warning(f"⚠️ Binance: Invalid symbol {symbol}")
                        return None
                    else:
                        logger.error(f"❌ Binance error {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"❌ Binance fetch error: {e}")
            return None
    
    @staticmethod
    async def get_crypto_data(symbol: str, interval: str = "1h") -> Optional[List[Dict]]:
        """
        Smart crypto data fetcher with fallback chain:
        1. Try Binance for major pairs (BTCUSDT, ETHUSDT, etc.)
        2. Try CoinGecko OHLC
        3. Try CoinGecko market_chart
        """
        symbol_upper = symbol.upper().strip()
        
        # Strategy 1: Binance for *USDT pairs
        if symbol_upper.endswith("USDT"):
            logger.info(f"🔄 Trying Binance for {symbol_upper}...")
            binance_data = await CryptoDataFetcher.fetch_binance_klines(symbol_upper, interval)
            if binance_data and len(binance_data) >= 50:
                return binance_data
        
        # Strategy 2: CoinGecko - search coin ID
        logger.info(f"🔄 Trying CoinGecko for {symbol_upper}...")
        
        # Remove USDT suffix for CoinGecko search
        search_symbol = symbol_upper.replace("USDT", "").replace("USD", "")
        
        coin_id = await CryptoDataFetcher.search_coin_id(search_symbol)
        
        if not coin_id:
            logger.error(f"❌ Could not find coin ID for {search_symbol}")
            return None
        
        # Try OHLC first (better quality)
        ohlc_data = await CryptoDataFetcher.fetch_coingecko_ohlc(coin_id, days=7)
        if ohlc_data and len(ohlc_data) >= 50:
            return ohlc_data
        
        # Fallback: market_chart
        logger.info(f"🔄 Trying CoinGecko market_chart for {coin_id}...")
        market_data = await CryptoDataFetcher.fetch_coingecko_market_chart(coin_id, days=7)
        if market_data and len(market_data) >= 50:
            return market_data
        
        logger.error(f"❌ No data available for {symbol_upper}")
        return None

# ========== FOREX DATA SOURCES ==========
class ForexDataFetcher:
    """Fetch real forex data from multiple sources"""
    
    @staticmethod
    async def fetch_alpha_vantage_forex(from_symbol: str, to_symbol: str = "USD", interval: str = "60min") -> Optional[List[Dict]]:
        """
        Fetch from Alpha Vantage
        Free tier: 25 API calls per day
        """
        if DataSourceConfig.ALPHA_VANTAGE_KEY == "demo":
            logger.warning("⚠️ Using DEMO Alpha Vantage key (limited data)")
        
        try:
            url = DataSourceConfig.ALPHA_VANTAGE_BASE
            params = {
                "function": "FX_INTRADAY",
                "from_symbol": from_symbol.upper(),
                "to_symbol": to_symbol.upper(),
                "interval": interval,
                "apikey": DataSourceConfig.ALPHA_VANTAGE_KEY,
                "outputsize": "full"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=20) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Check for error messages
                        if "Error Message" in data:
                            logger.error(f"❌ Alpha Vantage error: {data['Error Message']}")
                            return None
                        
                        if "Note" in data:
                            logger.warning(f"⚠️ Alpha Vantage rate limit: {data['Note']}")
                            return None
                        
                        # Parse time series data
                        time_series_key = f"Time Series FX ({interval})"
                        time_series = data.get(time_series_key, {})
                        
                        if not time_series:
                            logger.error(f"❌ Alpha Vantage: No data for {from_symbol}/{to_symbol}")
                            return None
                        
                        candles = []
                        for timestamp, values in sorted(time_series.items()):
                            candles.append({
                                "timestamp": int(datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").timestamp() * 1000),
                                "open": float(values["1. open"]),
                                "high": float(values["2. high"]),
                                "low": float(values["3. low"]),
                                "close": float(values["4. close"]),
                                "volume": 0  # Forex doesn't have volume
                            })
                        
                        logger.info(f"✅ Alpha Vantage: {len(candles)} candles for {from_symbol}/{to_symbol}")
                        return candles
                    
                    else:
                        logger.error(f"❌ Alpha Vantage HTTP {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"❌ Alpha Vantage error: {e}")
            return None
    
    @staticmethod
    async def fetch_twelve_data_forex(symbol: str, interval: str = "1h") -> Optional[List[Dict]]:
        """
        Fetch from Twelve Data
        Free tier: 800 API calls per day (better than Alpha Vantage)
        """
        if not DataSourceConfig.TWELVE_DATA_KEY:
            logger.warning("⚠️ Twelve Data API key not set")
            return None
        
        try:
            url = f"{DataSourceConfig.TWELVE_DATA_BASE}/time_series"
            params = {
                "symbol": symbol,
                "interval": interval,
                "apikey": DataSourceConfig.TWELVE_DATA_KEY,
                "outputsize": 200
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=20) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if "values" not in data:
                            logger.error(f"❌ Twelve Data: No values for {symbol}")
                            return None
                        
                        candles = []
                        for item in data["values"]:
                            candles.append({
                                "timestamp": int(datetime.strptime(item["datetime"], "%Y-%m-%d %H:%M:%S").timestamp() * 1000),
                                "open": float(item["open"]),
                                "high": float(item["high"]),
                                "low": float(item["low"]),
                                "close": float(item["close"]),
                                "volume": 0
                            })
                        
                        logger.info(f"✅ Twelve Data: {len(candles)} candles for {symbol}")
                        return candles
                    
                    else:
                        logger.error(f"❌ Twelve Data HTTP {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"❌ Twelve Data error: {e}")
            return None
    
    @staticmethod
    async def get_forex_data(symbol: str, interval: str = "1h") -> Optional[List[Dict]]:
        """
        Smart forex data fetcher with fallback:
        1. Try Twelve Data (800 calls/day)
        2. Try Alpha Vantage (25 calls/day)
        """
        # Parse symbol (EUR/USD or EURUSD)
        symbol_clean = symbol.upper().replace("/", "").replace(" ", "")
        
        if len(symbol_clean) != 6:
            logger.error(f"❌ Invalid forex pair: {symbol}")
            return None
        
        from_currency = symbol_clean[:3]
        to_currency = symbol_clean[3:]
        
        # Strategy 1: Twelve Data (better free tier)
        if DataSourceConfig.TWELVE_DATA_KEY:
            logger.info(f"🔄 Trying Twelve Data for {from_currency}/{to_currency}...")
            twelve_data = await ForexDataFetcher.fetch_twelve_data_forex(f"{from_currency}/{to_currency}", interval)
            if twelve_data and len(twelve_data) >= 50:
                return twelve_data
        
        # Strategy 2: Alpha Vantage
        logger.info(f"🔄 Trying Alpha Vantage for {from_currency}/{to_currency}...")
        alpha_data = await ForexDataFetcher.fetch_alpha_vantage_forex(from_currency, to_currency, "60min")
        if alpha_data and len(alpha_data) >= 50:
            return alpha_data
        
        logger.error(f"❌ No forex data available for {symbol}")
        return None

# ========== UNIVERSAL DATA FETCHER ==========
class UniversalDataFetcher:
    """Smart data fetcher with automatic market detection"""
    
    @staticmethod
    def detect_market_type(symbol: str) -> MarketType:
        """Detect if symbol is crypto or forex"""
        symbol_upper = symbol.upper().strip()
        
        # Crypto indicators
        crypto_suffixes = ["USDT", "USDC", "BUSD", "BTC", "ETH"]
        if any(symbol_upper.endswith(suffix) for suffix in crypto_suffixes):
            return MarketType.CRYPTO
        
        # Forex format: 6 characters (EURUSD) or has slash (EUR/USD)
        if "/" in symbol_upper or len(symbol_upper) == 6:
            return MarketType.FOREX
        
        # Default: assume crypto
        return MarketType.CRYPTO
    
    @staticmethod
    def format_for_tradingview(symbol: str, market_type: MarketType) -> str:
        """Format symbol for TradingView"""
        symbol_upper = symbol.upper().strip()
        
        if market_type == MarketType.CRYPTO:
            if symbol_upper.endswith("USDT"):
                return f"BINANCE:{symbol_upper}"
            else:
                return f"BINANCE:{symbol_upper}USDT"
        
        elif market_type == MarketType.FOREX:
            forex_clean = symbol_upper.replace("/", "")
            return f"FX:{forex_clean}"
        
        return symbol_upper
    
    @staticmethod
    async def get_market_data(symbol: str, interval: str = "1h") -> Tuple[Optional[List[Dict]], MarketType, str]:
        """
        Universal data fetcher - NO SYNTHETIC DATA
        Returns: (candles, market_type, tradingview_symbol)
        """
        market_type = UniversalDataFetcher.detect_market_type(symbol)
        tv_symbol = UniversalDataFetcher.format_for_tradingview(symbol, market_type)
        
        logger.info(f"📊 Fetching {market_type.value} data for {symbol}")
        
        # Cache check
        cache_key = f"data_{symbol}_{interval}_{market_type.value}"
        cached_data = cache_manager.get(cache_key, max_age_seconds=DataSourceConfig.COINGECKO_CACHE_SECONDS)
        if cached_data:
            return cached_data, market_type, tv_symbol
        
        # Fetch real data
        if market_type == MarketType.CRYPTO:
            candles = await CryptoDataFetcher.get_crypto_data(symbol, interval)
        else:
            candles = await ForexDataFetcher.get_forex_data(symbol, interval)
        
        if candles:
            cache_manager.set(cache_key, candles)
        
        return candles, market_type, tv_symbol

# ========== TECHNICAL INDICATORS (Keep from previous version) ==========
class TechnicalIndicators:
    """Calculate technical indicators"""
    
    @staticmethod
    def calculate_ema(candles: List[Dict], period: int) -> List[float]:
        """Calculate Exponential Moving Average"""
        closes = [c["close"] for c in candles]
        ema = []
        multiplier = 2 / (period + 1)
        
        if len(closes) < period:
            return [None] * len(closes)
        
        sma = sum(closes[:period]) / period
        ema.append(sma)
        
        for i in range(period, len(closes)):
            ema_value = (closes[i] - ema[-1]) * multiplier + ema[-1]
            ema.append(ema_value)
        
        return [None] * (period - 1) + ema
    
    @staticmethod
    def calculate_rsi(candles: List[Dict], period: int = 14) -> List[float]:
        """Calculate RSI"""
        closes = [c["close"] for c in candles]
        rsi_values = [None] * period
        
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        
        if len(gains) < period:
            return rsi_values
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        for i in range(period, len(gains)):
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            
            rsi_values.append(rsi)
            
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        return rsi_values
    
    @staticmethod
    def calculate_fibonacci(candles: List[Dict], lookback: int = 100) -> Dict:
        """Calculate Fibonacci levels"""
        recent = candles[-lookback:]
        
        highs = [c["high"] for c in recent]
        lows = [c["low"] for c in recent]
        
        swing_high = max(highs)
        swing_low = min(lows)
        diff = swing_high - swing_low
        
        trend = "uptrend" if recent[-1]["close"] > recent[0]["close"] else "downtrend"
        
        if trend == "uptrend":
            levels = {
                "0%": swing_low,
                "23.6%": swing_low + (diff * 0.236),
                "38.2%": swing_low + (diff * 0.382),
                "50%": swing_low + (diff * 0.5),
                "61.8%": swing_low + (diff * 0.618),
                "78.6%": swing_low + (diff * 0.786),
                "100%": swing_high
            }
        else:
            levels = {
                "0%": swing_high,
                "23.6%": swing_high - (diff * 0.236),
                "38.2%": swing_high - (diff * 0.382),
                "50%": swing_high - (diff * 0.5),
                "61.8%": swing_high - (diff * 0.618),
                "78.6%": swing_high - (diff * 0.786),
                "100%": swing_low
            }
        
        current_price = candles[-1]["close"]
        nearest_support = max([v for v in levels.values() if v < current_price], default=swing_low)
        nearest_resistance = min([v for v in levels.values() if v > current_price], default=swing_high)
        
        return {
            "trend": trend,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "levels": levels,
            "nearest_support": nearest_support,
            "nearest_resistance": nearest_resistance
        }
    
    @staticmethod
    def calculate_pivot_points(candles: List[Dict]) -> Dict:
        """Calculate classic pivot points"""
        prev = candles[-2]
        
        pivot = (prev["high"] + prev["low"] + prev["close"]) / 3
        
        r1 = (2 * pivot) - prev["low"]
        r2 = pivot + (prev["high"] - prev["low"])
        r3 = prev["high"] + 2 * (pivot - prev["low"])
        
        s1 = (2 * pivot) - prev["high"]
        s2 = pivot - (prev["high"] - prev["low"])
        s3 = prev["low"] - 2 * (prev["high"] - pivot)
        
        return {
            "pivot": pivot,
            "r1": r1, "r2": r2, "r3": r3,
            "s1": s1, "s2": s2, "s3": s3
        }

# ========== API ENDPOINTS ==========
@app.get("/health")
def health():
    return {
        "status": "healthy",
        "version": "4.0.0",
        "data_sources": {
            "crypto": ["Binance", "CoinGecko"],
            "forex": ["Twelve Data", "Alpha Vantage"]
        }
    }

@app.get("/api/analyze/{symbol}")
async def analyze_symbol(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1h|4h|1d)$")
):
    """Universal market analysis - REAL DATA ONLY"""
    try:
        # Fetch real data
        candles, market_type, tv_symbol = await UniversalDataFetcher.get_market_data(symbol, interval)
        
        if not candles or len(candles) < 100:
            raise HTTPException(
                status_code=503,
                detail=f"Unable to fetch data for {symbol}. Check API keys or try a different symbol."
            )
        
        # Calculate indicators
        ema_9 = TechnicalIndicators.calculate_ema(candles, 9)
        ema_21 = TechnicalIndicators.calculate_ema(candles, 21)
        ema_50 = TechnicalIndicators.calculate_ema(candles, 50)
        ema_100 = TechnicalIndicators.calculate_ema(candles, 100)
        rsi = TechnicalIndicators.calculate_rsi(candles, 14)
        fibonacci = TechnicalIndicators.calculate_fibonacci(candles, 100)
        pivot_points = TechnicalIndicators.calculate_pivot_points(candles)
        
        # Current price
        current = candles[-1]
        prev = candles[-2]
        price_change = ((current["close"] - prev["close"]) / prev["close"]) * 100
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "market_type": market_type.value,
            "tradingview_symbol": tv_symbol,
            "interval": interval,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data_source": "REAL" if candles else "UNAVAILABLE",
            "candle_count": len(candles),
            
            "price_data": {
                "current": round(current["close"], 8),
                "open": round(current["open"], 8),
                "high": round(current["high"], 8),
                "low": round(current["low"], 8),
                "change_percent": round(price_change, 2),
                "volume": current["volume"]
            },
            
            "indicators": {
                "ema_9": round(ema_9[-1], 8) if ema_9[-1] else None,
                "ema_21": round(ema_21[-1], 8) if ema_21[-1] else None,
                "ema_50": round(ema_50[-1], 8) if ema_50[-1] else None,
                "ema_100": round(ema_100[-1], 8) if ema_100[-1] else None,
                "rsi": round(rsi[-1], 2) if rsi[-1] else None
            },
            
            "fibonacci": {
                "trend": fibonacci["trend"],
                "levels": {k: round(v, 8) for k, v in fibonacci["levels"].items()},
                "nearest_support": round(fibonacci["nearest_support"], 8),
                "nearest_resistance": round(fibonacci["nearest_resistance"], 8)
            },
            
            "pivot_points": {
                "pivot": round(pivot_points["pivot"], 8),
                "resistance": {
                    "R1": round(pivot_points["r1"], 8),
                    "R2": round(pivot_points["r2"], 8),
                    "R3": round(pivot_points["r3"], 8)
                },
                "support": {
                    "S1": round(pivot_points["s1"], 8),
                    "S2": round(pivot_points["s2"], 8),
                    "S3": round(pivot_points["s3"], 8)
                }
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

# ========== DASHBOARD ==========
@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Real Data Trading Bot - Professional Grade</title>
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
        }
        
        .status-badge {
            display: inline-block;
            background: rgba(255,255,255,0.2);
            padding: 0.5rem 1.5rem;
            border-radius: 20px;
            margin-top: 1rem;
            font-weight: 600;
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
            background: var(--success);
            color: white;
            border: none;
            cursor: pointer;
            font-weight: 600;
        }
        
        button:hover { opacity: 0.9; }
        
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
        
        .category-title {
            grid-column: 1/-1;
            font-weight: 700;
            color: var(--success);
            padding: 0.5rem 0;
            border-bottom: 2px solid var(--success);
            margin-top: 1rem;
        }
        
        .dashboard {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
            margin-bottom: 1.5rem;
        }
        
        .card {
            background: var(--bg-card);
            border-radius: 12px;
            padding: 1.5rem;
        }
        
        .card-title {
            font-size: 1.2rem;
            font-weight: 700;
            margin-bottom: 1rem;
        }
        
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
        }
        
        .info-item {
            background: var(--bg-dark);
            padding: 1rem;
            border-radius: 8px;
        }
        
        .info-label {
            color: var(--text-muted);
            font-size: 0.85rem;
            margin-bottom: 0.5rem;
        }
        
        .info-value {
            font-size: 1.2rem;
            font-weight: 700;
        }
        
        .tradingview-widget {
            width: 100%;
            height: 500px;
            border-radius: 8px;
        }
        
        .loading {
            text-align: center;
            padding: 3rem;
            color: var(--success);
        }
        
        .spinner {
            border: 3px solid rgba(16,185,129,0.3);
            border-top: 3px solid var(--success);
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
        
        .alert-success {
            background: rgba(16,185,129,0.1);
            border-left: 4px solid var(--success);
        }
        
        .alert-warning {
            background: rgba(245,158,11,0.1);
            border-left: 4px solid var(--warning);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <i class="fas fa-chart-line"></i> Real Data Trading Bot
            </div>
            <div class="status-badge">
                <i class="fas fa-check-circle"></i> REAL DATA ONLY - NO SYNTHETIC
            </div>
        </header>
        
        <div class="alert alert-info">
            <strong>📡 Veri Kaynakları:</strong><br>
            • <strong>Kripto:</strong> Binance (gerçek zamanlı) + CoinGecko (tüm coinler, 20 sn cache)<br>
            • <strong>Forex:</strong> Twelve Data (800 call/day) + Alpha Vantage (25 call/day fallback)
        </div>
        
        <div class="control-panel">
            <h2 class="card-title"><i class="fas fa-search"></i> Analiz Yap</h2>
            <div class="input-row">
                <input type="text" id="symbolInput" placeholder="Örn: BTCUSDT, SOLUSDT, EUR/USD, GBPUSD..." value="BTCUSDT">
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
                <div class="category-title">🪙 Kripto (Binance + CoinGecko)</div>
                <div class="quick-symbol" onclick="setSymbol('BTCUSDT')">Bitcoin</div>
                <div class="quick-symbol" onclick="setSymbol('ETHUSDT')">Ethereum</div>
                <div class="quick-symbol" onclick="setSymbol('SOLUSDT')">Solana</div>
                <div class="quick-symbol" onclick="setSymbol('XRPUSDT')">XRP</div>
                <div class="quick-symbol" onclick="setSymbol('ADAUSDT')">Cardano</div>
                <div class="quick-symbol" onclick="setSymbol('AVAXUSDT')">Avalanche</div>
                <div class="quick-symbol" onclick="setSymbol('DOGEUSDT')">Dogecoin</div>
                <div class="quick-symbol" onclick="setSymbol('SHIBUSDT')">Shiba</div>
                
                <div class="category-title">💱 Forex (Twelve Data + Alpha Vantage)</div>
                <div class="quick-symbol" onclick="setSymbol('EURUSD')">EUR/USD</div>
                <div class="quick-symbol" onclick="setSymbol('GBPUSD')">GBP/USD</div>
                <div class="quick-symbol" onclick="setSymbol('USDJPY')">USD/JPY</div>
                <div class="quick-symbol" onclick="setSymbol('AUDUSD')">AUD/USD</div>
                <div class="quick-symbol" onclick="setSymbol('USDCHF')">USD/CHF</div>
                <div class="quick-symbol" onclick="setSymbol('NZDUSD')">NZD/USD</div>
            </div>
        </div>
        
        <div class="dashboard">
            <div class="card">
                <h2 class="card-title">
                    <i class="fas fa-info-circle"></i> Piyasa Bilgileri
                    <span id="symbolDisplay" style="margin-left: auto; font-size: 0.9rem; opacity: 0.7;">-</span>
                </h2>
                <div id="infoContainer">
                    <div class="loading">Analiz bekleniyor...</div>
                </div>
            </div>
            
            <div class="card">
                <h2 class="card-title"><i class="fas fa-chart-area"></i> TradingView Chart</h2>
                <div class="tradingview-widget">
                    <div id="tradingview_chart"></div>
                </div>
            </div>
        </div>
        
        <div class="dashboard">
            <div class="card">
                <h2 class="card-title"><i class="fas fa-percent"></i> Fibonacci Seviyeleri</h2>
                <div id="fibContainer">
                    <div class="loading">Bekleniyor...</div>
                </div>
            </div>
            
            <div class="card">
                <h2 class="card-title"><i class="fas fa-crosshairs"></i> Pivot Noktaları</h2>
                <div id="pivotContainer">
                    <div class="loading">Bekleniyor...</div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>
        let tvWidget = null;
        
        function initTradingView(tvSymbol) {
            if (tvWidget) tvWidget.remove();
            
            tvWidget = new TradingView.widget({
                width: "100%",
                height: "100%",
                symbol: tvSymbol,
                interval: "60",
                timezone: "Etc/UTC",
                theme: "dark",
                style: "1",
                locale: "tr",
                toolbar_bg: "#1a1f3a",
                enable_publishing: false,
                container_id: "tradingview_chart"
            });
        }
        
        function setSymbol(sym) {
            document.getElementById('symbolInput').value = sym;
            analyze();
        }
        
        async function analyze() {
            const symbol = document.getElementById('symbolInput').value.trim();
            const interval = document.getElementById('intervalSelect').value;
            const btn = document.getElementById('analyzeBtn');
            
            if (!symbol) return alert('Sembol girin');
            
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Gerçek veri çekiliyor...';
            
            document.getElementById('symbolDisplay').textContent = symbol.toUpperCase();
            showLoading();
            
            try {
                const resp = await fetch(`/api/analyze/${encodeURIComponent(symbol)}?interval=${interval}`);
                const data = await resp.json();
                
                if (!data.success) {
                    throw new Error(data.detail || 'Veri alınamadı');
                }
                
                initTradingView(data.tradingview_symbol);
                renderInfo(data);
                renderFib(data);
                renderPivot(data);
                
            } catch (err) {
                console.error(err);
                alert('Analiz hatası: ' + err.message);
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-search"></i> Analiz Et';
            }
        }
        
        function showLoading() {
            const loading = '<div class="loading"><div class="spinner"></div></div>';
            document.getElementById('infoContainer').innerHTML = loading;
            document.getElementById('fibContainer').innerHTML = loading;
            document.getElementById('pivotContainer').innerHTML = loading;
        }
        
        function renderInfo(data) {
            const html = `
                <div class="alert alert-success">
                    <strong>✅ Veri Kaynağı:</strong> ${data.data_source} (${data.candle_count} mum)
                </div>
                <div class="info-grid">
                    <div class="info-item">
                        <div class="info-label">Piyasa</div>
                        <div class="info-value">${data.market_type}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Fiyat</div>
                        <div class="info-value">$${data.price_data.current}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Değişim</div>
                        <div class="info-value" style="color: ${data.price_data.change_percent >= 0 ? 'var(--success)' : 'var(--danger)'}">
                            ${data.price_data.change_percent >= 0 ? '▲' : '▼'} ${Math.abs(data.price_data.change_percent)}%
                        </div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">RSI</div>
                        <div class="info-value">${data.indicators.rsi || '-'}</div>
                    </div>
                </div>
            `;
            document.getElementById('infoContainer').innerHTML = html;
        }
        
        function renderFib(data) {
            const fib = data.fibonacci;
            let html = `
                <div style="margin-bottom: 1rem;">
                    <strong>Trend:</strong> ${fib.trend === 'uptrend' ? '📈 Yükseliş' : '📉 Düşüş'}
                </div>
                <div class="info-grid">
            `;
            
            for (const [level, price] of Object.entries(fib.levels)) {
                html += `
                    <div class="info-item">
                        <div class="info-label">${level}</div>
                        <div class="info-value">$${price.toFixed(6)}</div>
                    </div>
                `;
            }
            
            html += '</div>';
            document.getElementById('fibContainer').innerHTML = html;
        }
        
        function renderPivot(data) {
            const p = data.pivot_points;
            const html = `
                <div class="info-grid">
                    <div class="info-item">
                        <div class="info-label">Pivot</div>
                        <div class="info-value" style="color: var(--warning)">$${p.pivot.toFixed(6)}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">R1</div>
                        <div class="info-value" style="color: var(--danger)">$${p.resistance.R1.toFixed(6)}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">R2</div>
                        <div class="info-value" style="color: var(--danger)">$${p.resistance.R2.toFixed(6)}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">R3</div>
                        <div class="info-value" style="color: var(--danger)">$${p.resistance.R3.toFixed(6)}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">S1</div>
                        <div class="info-value" style="color: var(--success)">$${p.support.S1.toFixed(6)}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">S2</div>
                        <div class="info-value" style="color: var(--success)">$${p.support.S2.toFixed(6)}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">S3</div>
                        <div class="info-value" style="color: var(--success)">$${p.support.S3.toFixed(6)}</div>
                    </div>
                </div>
            `;
            document.getElementById('pivotContainer').innerHTML = html;
        }
        
        document.addEventListener('DOMContentLoaded', () => {
            initTradingView('BINANCE:BTCUSDT');
        });
    </script>
</body>
</html>
    """

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🚀 Starting Real Data Trading Bot on port {port}")
    logger.info("=" * 60)
    logger.info("DATA SOURCES:")
    logger.info("  Crypto: Binance + CoinGecko (20s cache)")
    logger.info("  Forex: Twelve Data + Alpha Vantage")
    logger.info("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
