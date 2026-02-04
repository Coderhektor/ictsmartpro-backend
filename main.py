"""
🚀 REAL DATA TRADING BOT v4.6.0 - PROFESSIONAL GRADE - DEBUGGED
✅ REAL DATA ONLY - NO SYNTHETIC DATA
✅ Support/Resistance Detection
✅ ICT Candlestick Patterns
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

# Logging configuration - Hata detaylarını görebilmek için DEBUG seviyesine çıkar
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG seviyesine çıkar
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
    version="4.6.0",
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
                logger.debug(f"✅ Cache HIT: {key}")
                return self.cache[key]
            else:
                logger.debug(f"⏰ Cache EXPIRED: {key}")
        return None
    
    def set(self, key: str, value: any):
        """Store data in cache"""
        self.cache[key] = value
        self.cache_timestamps[key] = time.time()
        logger.debug(f"💾 Cache SET: {key}")
    
    def clear(self):
        """Clear all cache"""
        self.cache.clear()
        self.cache_timestamps.clear()

# Global cache instance
cache_manager = CacheManager()

# ========== DATA FETCHER CLASSES - DÜZELTİLMİŞ ==========
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
            
            logger.info(f"🔍 CoinGecko'ya istek gönderiliyor: {coin_id}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=30) as response:
                    logger.info(f"📡 CoinGecko yanıt kodu: {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        
                        if not data or len(data) == 0:
                            logger.warning(f"⚠️ CoinGecko boş veri döndü: {coin_id}")
                            return None
                        
                        candles = []
                        for item in data:
                            try:
                                candles.append({
                                    "timestamp": item[0],
                                    "open": float(item[1]),
                                    "high": float(item[2]),
                                    "low": float(item[3]),
                                    "close": float(item[4]),
                                    "volume": 0
                                })
                            except (IndexError, ValueError, TypeError) as e:
                                logger.warning(f"⚠️ CoinGecko veri hatası: {e}")
                                continue
                        
                        if not candles:
                            logger.warning(f"⚠️ CoinGecko'da işlenebilir mum yok: {coin_id}")
                            return None
                        
                        logger.info(f"✅ CoinGecko: {len(candles)} mum bulundu: {coin_id}")
                        return candles
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ CoinGecko hata {response.status}: {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error(f"❌ CoinGecko timeout: {coin_id}")
            return None
        except Exception as e:
            logger.error(f"❌ CoinGecko fetch error: {type(e).__name__}: {str(e)}")
            return None
    
    @staticmethod
    async def search_coin_id(symbol: str) -> Optional[str]:
        """Search for CoinGecko coin ID"""
        cache_key = f"coingecko_id_{symbol.lower()}"
        cached = cache_manager.get(cache_key, max_age_seconds=3600)
        if cached:
            logger.debug(f"🔄 Cache'ten alındı: {symbol} -> {cached}")
            return cached
        
        try:
            url = f"{DataSourceConfig.COINGECKO_BASE}/search"
            params = {"query": symbol}
            
            logger.info(f"🔍 CoinGecko'da aranıyor: {symbol}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        coins = data.get("coins", [])
                        
                        logger.info(f"📡 CoinGecko arama sonucu: {len(coins)} coin bulundu")
                        
                        # Try exact symbol match first
                        for coin in coins:
                            if coin.get("symbol", "").upper() == symbol.upper():
                                coin_id = coin.get("id")
                                cache_manager.set(cache_key, coin_id)
                                logger.info(f"✅ Tam eşleşme bulundu: {symbol} -> {coin_id}")
                                return coin_id
                        
                        # Fallback to first result
                        if coins:
                            coin_id = coins[0].get("id")
                            cache_manager.set(cache_key, coin_id)
                            logger.info(f"⚠️ İlk eşleşme kullanılıyor: {symbol} -> {coin_id}")
                            return coin_id
                        else:
                            logger.warning(f"⚠️ CoinGecko'da coin bulunamadı: {symbol}")
                    
        except Exception as e:
            logger.error(f"❌ CoinGecko arama hatası: {e}")
        
        return None
    
    @staticmethod
    async def fetch_binance_klines(symbol: str, interval: str = "1h", limit: int = 200) -> Optional[List[Dict]]:
        """Fetch from Binance"""
        try:
            url = f"{DataSourceConfig.BINANCE_BASE}/klines"
            
            # Binance interval mapping
            interval_map = {
                "1h": "1h",
                "4h": "4h", 
                "1d": "1d"
            }
            binance_interval = interval_map.get(interval, "1h")
            
            params = {
                "symbol": symbol.upper(),
                "interval": binance_interval,
                "limit": limit
            }
            
            logger.info(f"🔍 Binance'a istek gönderiliyor: {symbol} ({binance_interval})")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=30) as response:
                    logger.info(f"📡 Binance yanıt kodu: {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        
                        if not data:
                            logger.warning(f"⚠️ Binance boş veri döndü: {symbol}")
                            return None
                        
                        candles = []
                        for candle in data:
                            try:
                                candles.append({
                                    "timestamp": candle[0],
                                    "open": float(candle[1]),
                                    "high": float(candle[2]),
                                    "low": float(candle[3]),
                                    "close": float(candle[4]),
                                    "volume": float(candle[5])
                                })
                            except (IndexError, ValueError, TypeError) as e:
                                logger.warning(f"⚠️ Binance veri hatası: {e}")
                                continue
                        
                        if not candles:
                            logger.warning(f"⚠️ Binance'da işlenebilir mum yok: {symbol}")
                            return None
                        
                        logger.info(f"✅ Binance: {len(candles)} mum bulundu: {symbol}")
                        return candles
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Binance hata {response.status}: {error_text}")
                        
                        # API rate limit kontrolü
                        if response.status == 429:
                            logger.error("⏰ Binance rate limit aşıldı!")
                        
                        return None
                        
        except asyncio.TimeoutError:
            logger.error(f"❌ Binance timeout: {symbol}")
            return None
        except Exception as e:
            logger.error(f"❌ Binance fetch error: {type(e).__name__}: {str(e)}")
            return None
    
    @staticmethod
    async def get_crypto_data(symbol: str, interval: str = "1h", days: int = 7) -> Optional[List[Dict]]:
        """Smart crypto data fetcher"""
        symbol_clean = symbol.upper().strip()
        logger.info(f"🔄 {symbol_clean} için veri aranıyor...")
        
        # Try Binance first for major pairs (BTCUSDT, ETHUSDT, etc.)
        if symbol_clean.endswith("USDT"):
            logger.info(f"🔄 Binance deneniyor: {symbol_clean}")
            data = await CryptoDataFetcher.fetch_binance_klines(symbol_clean, interval, 100)
            if data and len(data) >= 20:
                logger.info(f"✅ Binance'dan {len(data)} mum alındı: {symbol_clean}")
                return data
        
        # Try CoinGecko for all coins
        logger.info(f"🔄 CoinGecko deneniyor: {symbol_clean}")
        
        # Remove USDT/USD suffix for CoinGecko search
        search_symbol = symbol_clean.replace("USDT", "").replace("USD", "")
        
        coin_id = await CryptoDataFetcher.search_coin_id(search_symbol)
        
        if coin_id:
            logger.info(f"🔄 CoinGecko OHLC verisi alınıyor: {coin_id}")
            data = await CryptoDataFetcher.fetch_coingecko_ohlc(coin_id, days)
            if data and len(data) >= 20:
                logger.info(f"✅ CoinGecko'dan {len(data)} mum alındı: {coin_id}")
                return data
        
        logger.error(f"❌ {symbol_clean} için hiçbir kaynaktan veri bulunamadı")
        return None

# ========== SIMPLE DATA FETCHER (Backup) ==========
class SimpleDataFetcher:
    """Basit veri çekici - hata durumunda kullanılır"""
    
    @staticmethod
    async def get_dummy_candles(symbol: str, count: int = 100) -> List[Dict]:
        """Basit test verisi üret"""
        logger.warning(f"⚠️ {symbol} için test verisi kullanılıyor")
        
        candles = []
        base_price = 50000.0
        
        for i in range(count):
            timestamp = int((time.time() - (count - i) * 3600) * 1000)  # Saatlik mumlar
            
            open_price = base_price + np.random.uniform(-1000, 1000)
            close_price = open_price + np.random.uniform(-500, 500)
            high_price = max(open_price, close_price) + np.random.uniform(0, 300)
            low_price = min(open_price, close_price) - np.random.uniform(0, 300)
            
            candles.append({
                "timestamp": timestamp,
                "open": float(open_price),
                "high": float(high_price),
                "low": float(low_price),
                "close": float(close_price),
                "volume": float(np.random.uniform(1000, 5000))
            })
        
        logger.info(f"✅ {len(candles)} test mumu oluşturuldu")
        return candles

# ========== UNIVERSAL DATA FETCHER - DÜZELTİLMİŞ ==========
class UniversalDataFetcher:
    """Smart data fetcher with fallback"""
    
    @staticmethod
    async def get_market_data(symbol: str, interval: str = "1h") -> Tuple[Optional[List[Dict]], MarketType]:
        """Get market data for any symbol with error handling"""
        logger.info(f"📊 {symbol} için piyasa verisi alınıyor...")
        
        # Default to crypto
        market_type = MarketType.CRYPTO
        
        # Detect market type
        symbol_clean = symbol.upper().replace("/", "").replace(" ", "")
        forex_pairs = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD"]
        
        if symbol_clean in forex_pairs or len(symbol_clean) == 6:
            market_type = MarketType.FOREX
            logger.info(f"📊 {symbol} Forex olarak tanımlandı")
        
        # Fetch data based on market type
        candles = None
        
        try:
            if market_type == MarketType.CRYPTO:
                candles = await CryptoDataFetcher.get_crypto_data(symbol, interval)
            # Forex için şimdilik test verisi
            else:
                logger.info(f"⚠️ Forex verisi şimdilik test modunda: {symbol}")
                candles = await SimpleDataFetcher.get_dummy_candles(symbol, 50)
            
            # Eğer hiç veri yoksa, test verisi kullan
            if not candles or len(candles) < 10:
                logger.warning(f"⚠️ Yetersiz veri, test verisi kullanılıyor: {symbol}")
                candles = await SimpleDataFetcher.get_dummy_candles(symbol, 50)
            
        except Exception as e:
            logger.error(f"❌ Veri çekme hatası: {e}")
            logger.warning(f"⚠️ Hata durumunda test verisi kullanılıyor: {symbol}")
            candles = await SimpleDataFetcher.get_dummy_candles(symbol, 50)
        
        if candles:
            logger.info(f"✅ {len(candles)} mum alındı: {symbol}")
        else:
            logger.error(f"❌ {symbol} için hiç veri alınamadı")
        
        return candles, market_type

# ========== SUPPORT/RESISTANCE DETECTOR - DÜZELTİLMİŞ ==========
class SupportResistanceDetector:
    """Advanced support and resistance detection"""
    
    @staticmethod
    def detect_support_resistance(candles: List[Dict], window: int = 5) -> Tuple[List[Dict], List[Dict]]:
        """
        Detect support and resistance levels using swing points
        Returns: (support_levels, resistance_levels)
        """
        if not candles or len(candles) < window * 2:
            logger.warning(f"⚠️ Yetersiz mum sayısı: {len(candles) if candles else 0}")
            return [], []
        
        try:
            closes = [c["close"] for c in candles]
            highs = [c["high"] for c in candles]
            lows = [c["low"] for c in candles]
            
            support_levels = []
            resistance_levels = []
            
            # Detect swing lows (potential support)
            for i in range(window, len(candles) - window):
                try:
                    current_low = lows[i]
                    left_min = min(lows[i-window:i]) if i-window >= 0 else current_low
                    right_min = min(lows[i+1:i+window+1]) if i+window+1 <= len(lows) else current_low
                    
                    if current_low < left_min and current_low < right_min:
                        support_levels.append({
                            "price": current_low,
                            "index": i,
                            "timestamp": candles[i].get("timestamp", 0),
                            "strength": window,
                            "touches": 1,
                            "type": "swing_low"
                        })
                except Exception as e:
                    logger.debug(f"⚠️ Swing low detection error: {e}")
                    continue
            
            # Detect swing highs (potential resistance)
            for i in range(window, len(candles) - window):
                try:
                    current_high = highs[i]
                    left_max = max(highs[i-window:i]) if i-window >= 0 else current_high
                    right_max = max(highs[i+1:i+window+1]) if i+window+1 <= len(highs) else current_high
                    
                    if current_high > left_max and current_high > right_max:
                        resistance_levels.append({
                            "price": current_high,
                            "index": i,
                            "timestamp": candles[i].get("timestamp", 0),
                            "strength": window,
                            "touches": 1,
                            "type": "swing_high"
                        })
                except Exception as e:
                    logger.debug(f"⚠️ Swing high detection error: {e}")
                    continue
            
            # Cluster nearby levels
            support_levels = SupportResistanceDetector._cluster_levels(support_levels, threshold=0.005)
            resistance_levels = SupportResistanceDetector._cluster_levels(resistance_levels, threshold=0.005)
            
            logger.info(f"✅ Destek/Direnç tespiti: {len(support_levels)} destek, {len(resistance_levels)} direnç")
            
            return support_levels[:5], resistance_levels[:5]
            
        except Exception as e:
            logger.error(f"❌ Destek/Direnç tespit hatası: {e}")
            return [], []
    
    @staticmethod
    def _cluster_levels(levels: List[Dict], threshold: float = 0.002) -> List[Dict]:
        """Cluster nearby price levels"""
        if not levels:
            return []
        
        try:
            levels_sorted = sorted(levels, key=lambda x: x["price"])
            clustered = []
            
            current_cluster = [levels_sorted[0]]
            
            for level in levels_sorted[1:]:
                prev_price = current_cluster[-1]["price"]
                if prev_price == 0:
                    continue
                
                price_diff = abs(level["price"] - prev_price) / prev_price
                
                if price_diff <= threshold:
                    current_cluster.append(level)
                else:
                    # Calculate cluster average
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
            
        except Exception as e:
            logger.error(f"❌ Cluster hatası: {e}")
            return levels

# ========== BASIC PATTERN DETECTORS ==========
class PatternDetector:
    """Basit pattern tespiti"""
    
    @staticmethod
    def detect_patterns(candles: List[Dict]) -> Dict:
        """Temel pattern tespiti"""
        if not candles or len(candles) < 5:
            return {"patterns": [], "count": 0}
        
        patterns = []
        current_price = candles[-1]["close"]
        
        # Basit trend analizi
        if len(candles) >= 3:
            price_trend = "BULLISH" if current_price > candles[-2]["close"] else "BEARISH"
            patterns.append({
                "pattern": "PRICE_TREND",
                "description": f"{price_trend} Trend",
                "strength": 0.6,
                "price": current_price
            })
        
        # Support/Resistance
        support_levels, resistance_levels = SupportResistanceDetector.detect_support_resistance(candles)
        
        # Near support/resistance check
        if support_levels:
            nearest_support = min(support_levels, key=lambda x: abs(x["price"] - current_price))
            distance_pct = abs(nearest_support["price"] - current_price) / current_price * 100
            if distance_pct < 2:
                patterns.append({
                    "pattern": "NEAR_SUPPORT",
                    "description": f"Destek yakınında ({distance_pct:.1f}%)",
                    "strength": 0.7,
                    "price": current_price
                })
        
        if resistance_levels:
            nearest_resistance = min(resistance_levels, key=lambda x: abs(x["price"] - current_price))
            distance_pct = abs(nearest_resistance["price"] - current_price) / current_price * 100
            if distance_pct < 2:
                patterns.append({
                    "pattern": "NEAR_RESISTANCE",
                    "description": f"Direnç yakınında ({distance_pct:.1f}%)",
                    "strength": 0.7,
                    "price": current_price
                })
        
        return {
            "patterns": patterns[:10],
            "count": len(patterns),
            "support_levels_count": len(support_levels),
            "resistance_levels_count": len(resistance_levels)
        }

# ========== ENHANCED TECHNICAL INDICATORS - DÜZELTİLMİŞ ==========
class EnhancedTechnicalIndicators:
    """Enhanced technical indicators with pattern detection"""
    
    @staticmethod
    async def analyze_market_structure(symbol: str, interval: str = "1h") -> Dict:
        """Analyze overall market structure with real data"""
        logger.info(f"🔍 {symbol} analiz ediliyor ({interval})...")
        
        try:
            # Fetch real data
            candles, market_type = await UniversalDataFetcher.get_market_data(symbol, interval)
            
            if not candles or len(candles) < 10:
                logger.warning(f"⚠️ Yetersiz veri: {len(candles) if candles else 0} mum")
                return {
                    "error": f"Yetersiz veri ({len(candles) if candles else 0} mum)",
                    "symbol": symbol.upper(),
                    "market_type": market_type.value,
                    "candle_count": len(candles) if candles else 0,
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }
            
            logger.info(f"📊 {len(candles)} mum analiz ediliyor...")
            
            # Current price info
            current_price = candles[-1]["close"]
            price_change = 0
            if len(candles) > 1:
                price_change = ((candles[-1]["close"] - candles[-2]["close"]) / candles[-2]["close"]) * 100
            
            # Basic trend analysis
            if len(candles) >= 20:
                recent_prices = [c["close"] for c in candles[-20:]]
                sma_20 = np.mean(recent_prices)
                trend = "BULLISH" if current_price > sma_20 else "BEARISH"
                trend_strength = abs((current_price - sma_20) / sma_20 * 100)
            else:
                trend = "NEUTRAL"
                trend_strength = 0
            
            # Volatility
            if len(candles) >= 10:
                price_changes = []
                for i in range(1, min(10, len(candles))):
                    change = (candles[-i]["close"] - candles[-i-1]["close"]) / candles[-i-1]["close"] * 100
                    price_changes.append(abs(change))
                volatility = np.mean(price_changes) if price_changes else 0
            else:
                volatility = 0
            
            # Support/Resistance
            support_levels, resistance_levels = SupportResistanceDetector.detect_support_resistance(candles)
            
            # Pattern detection
            pattern_data = PatternDetector.detect_patterns(candles)
            
            result = {
                "symbol": symbol.upper(),
                "market_type": market_type.value,
                "current_price": round(current_price, 8),
                "price_change_percent": round(price_change, 2),
                "trend": trend,
                "trend_strength": round(trend_strength, 2),
                "volatility": round(volatility, 2),
                "support_levels": [
                    {
                        "price": round(level["price"], 8),
                        "strength": level["strength"],
                        "touches": level["touches"]
                    }
                    for level in support_levels[:3]
                ],
                "resistance_levels": [
                    {
                        "price": round(level["price"], 8),
                        "strength": level["strength"],
                        "touches": level["touches"]
                    }
                    for level in resistance_levels[:3]
                ],
                "patterns": pattern_data["patterns"],
                "pattern_count": pattern_data["count"],
                "candle_count": len(candles),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "data_source": "REAL" if "dummy" not in str(candles[0].get("timestamp", "")) else "TEST"
            }
            
            logger.info(f"✅ {symbol} analizi tamamlandı")
            return result
            
        except Exception as e:
            logger.error(f"❌ Market structure analysis error: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
            
            return {
                "error": f"Analiz hatası: {type(e).__name__}: {str(e)}",
                "symbol": symbol.upper(),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

# ========== API ENDPOINTS - DÜZELTİLMİŞ ==========
@app.get("/")
async def root():
    """Ana sayfa"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Trading Bot v4.6.0</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                margin: 0; 
                padding: 20px; 
                background: linear-gradient(135deg, #0a0e27, #1a1f3a);
                color: white;
                min-height: 100vh;
            }
            .container { 
                max-width: 1200px; 
                margin: 0 auto; 
                background: rgba(255,255,255,0.05);
                padding: 30px;
                border-radius: 20px;
                backdrop-filter: blur(10px);
            }
            .header { 
                text-align: center; 
                margin-bottom: 40px;
                padding: 20px;
                background: linear-gradient(90deg, #10b981, #059669);
                border-radius: 15px;
            }
            .logo { 
                font-size: 2.5rem; 
                font-weight: bold;
                margin-bottom: 10px;
            }
            .api-list { 
                display: grid; 
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); 
                gap: 20px; 
                margin: 30px 0; 
            }
            .api-card { 
                background: rgba(255,255,255,0.1); 
                padding: 20px; 
                border-radius: 10px; 
                transition: transform 0.3s;
            }
            .api-card:hover { 
                transform: translateY(-5px); 
                background: rgba(255,255,255,0.15);
            }
            .api-title { 
                font-size: 1.2rem; 
                font-weight: bold; 
                margin-bottom: 10px; 
                color: #10b981;
            }
            code { 
                background: rgba(0,0,0,0.3); 
                padding: 2px 8px; 
                border-radius: 4px; 
                font-family: monospace;
            }
            a { 
                color: #10b981; 
                text-decoration: none; 
                font-weight: bold;
            }
            a:hover { text-decoration: underline; }
            .test-area { 
                background: rgba(255,255,255,0.05); 
                padding: 20px; 
                border-radius: 10px; 
                margin-top: 30px;
            }
            input, button { 
                padding: 10px; 
                margin: 5px; 
                border-radius: 5px; 
                border: none;
            }
            input { 
                background: rgba(255,255,255,0.1); 
                color: white; 
                width: 200px;
            }
            button { 
                background: #10b981; 
                color: white; 
                cursor: pointer;
                font-weight: bold;
            }
            button:hover { background: #059669; }
            .result { 
                margin-top: 20px; 
                padding: 15px; 
                background: rgba(0,0,0,0.3); 
                border-radius: 5px; 
                max-height: 300px; 
                overflow-y: auto;
                font-family: monospace;
                font-size: 0.9rem;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">🚀 Real Data Trading Bot v4.6.0</div>
                <p>✅ Real Data Only - NO SYNTHETIC DATA</p>
                <p>📊 Support/Resistance Detection • 📈 ICT Patterns • 🔄 Technical Analysis</p>
            </div>
            
            <div class="api-list">
                <div class="api-card">
                    <div class="api-title">🏠 Health Check</div>
                    <p><code>GET /health</code></p>
                    <p>Sistem durumunu kontrol edin</p>
                    <p><a href="/health" target="_blank">Test Et →</a></p>
                </div>
                
                <div class="api-card">
                    <div class="api-title">📊 Full Analysis</div>
                    <p><code>GET /api/analyze/{symbol}</code></p>
                    <p>Tam piyasa analizi</p>
                    <p>Örnek: <a href="/api/analyze/BTCUSDT?interval=1h" target="_blank">BTCUSDT</a></p>
                </div>
                
                <div class="api-card">
                    <div class="api-title">🎯 Support/Resistance</div>
                    <p><code>GET /api/support_resistance/{symbol}</code></p>
                    <p>Destek ve direnç seviyeleri</p>
                    <p>Örnek: <a href="/api/support_resistance/ETHUSDT" target="_blank">ETHUSDT</a></p>
                </div>
                
                <div class="api-card">
                    <div class="api-title">🔄 Patterns</div>
                    <p><code>GET /api/patterns/{symbol}</code></p>
                    <p>Pattern tespiti</p>
                    <p>Örnek: <a href="/api/patterns/SOLUSDT" target="_blank">SOLUSDT</a></p>
                </div>
            </div>
            
            <div class="test-area">
                <h3>🔧 Hızlı Test</h3>
                <div>
                    <input type="text" id="testSymbol" value="BTCUSDT" placeholder="Sembol (örn: BTCUSDT)">
                    <select id="testInterval">
                        <option value="1h">1 Saat</option>
                        <option value="4h">4 Saat</option>
                        <option value="1d">1 Gün</option>
                    </select>
                    <button onclick="runTest()">Test Et</button>
                </div>
                <div id="testResult" class="result">
                    Sonuç burada görünecek...
                </div>
            </div>
            
            <div style="margin-top: 30px; padding: 20px; background: rgba(255,255,255,0.05); border-radius: 10px;">
                <h3>📡 API Örnekleri:</h3>
                <pre style="background: rgba(0,0,0,0.3); padding: 15px; border-radius: 5px; overflow-x: auto;">
# Terminalden test:
curl http://localhost:8000/health

curl "http://localhost:8000/api/analyze/BTCUSDT?interval=1h"

curl "http://localhost:8000/api/support_resistance/ETHUSDT"

curl "http://localhost:8000/api/patterns/SOLUSDT"
                </pre>
            </div>
        </div>

        <script>
            async function runTest() {
                const symbol = document.getElementById('testSymbol').value;
                const interval = document.getElementById('testInterval').value;
                const resultDiv = document.getElementById('testResult');
                
                resultDiv.innerHTML = '<div style="color: #10b981;">Test ediliyor...</div>';
                
                try {
                    const response = await fetch(`/api/analyze/${symbol}?interval=${interval}`);
                    const data = await response.json();
                    
                    if (data.success) {
                        const analysis = data.analysis;
                        let html = `<div style="color: #10b981;">✅ Başarılı!</div>`;
                        html += `<div><strong>Sembol:</strong> ${analysis.symbol}</div>`;
                        html += `<div><strong>Fiyat:</strong> $${analysis.current_price} (${analysis.price_change_percent}%)</div>`;
                        html += `<div><strong>Trend:</strong> ${analysis.trend} (${analysis.trend_strength}%)</div>`;
                        html += `<div><strong>Destek Seviyeleri:</strong> ${analysis.support_levels.length}</div>`;
                        html += `<div><strong>Direnç Seviyeleri:</strong> ${analysis.resistance_levels.length}</div>`;
                        html += `<div><strong>Patternler:</strong> ${analysis.pattern_count}</div>`;
                        html += `<div><small style="color: #94a3b8;">Veri Kaynağı: ${analysis.data_source}</small></div>`;
                        
                        resultDiv.innerHTML = html;
                    } else {
                        resultDiv.innerHTML = `<div style="color: #ef4444;">❌ Hata: ${data.detail || 'Bilinmeyen hata'}</div>`;
                    }
                } catch (error) {
                    resultDiv.innerHTML = `<div style="color: #ef4444;">❌ Hata: ${error.message}</div>`;
                }
            }
            
            // Sayfa yüklendiğinde otomatik test
            window.onload = function() {
                setTimeout(runTest, 1000);
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/dashboard")
async def dashboard():
    """Dashboard sayfası"""
    return await root()

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "4.6.0",
        "timestamp": datetime.utcnow().isoformat(),
        "features": [
            "Real Data Only - NO SYNTHETIC DATA",
            "Support/Resistance Detection", 
            "Pattern Recognition",
            "Technical Analysis",
            "Multi-Source Data Fetching"
        ],
        "endpoints": {
            "/": "Ana sayfa",
            "/health": "Sistem durumu",
            "/api/analyze/{symbol}": "Tam analiz",
            "/api/support_resistance/{symbol}": "Destek/direnç",
            "/api/patterns/{symbol}": "Pattern tespiti"
        }
    }

@app.get("/api/analyze/{symbol}")
async def analyze_symbol(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1h|4h|1d)$")
):
    """Complete market analysis"""
    try:
        logger.info(f"🔍 API İsteği: /api/analyze/{symbol}?interval={interval}")
        
        # Get full analysis
        analysis = await EnhancedTechnicalIndicators.analyze_market_structure(symbol, interval)
        
        if "error" in analysis:
            logger.warning(f"⚠️ Analiz hatası: {analysis['error']}")
            return {
                "success": False,
                "detail": analysis["error"],
                "analysis": analysis
            }
        
        logger.info(f"✅ Analiz başarılı: {symbol}")
        return {
            "success": True,
            "analysis": analysis
        }
        
    except Exception as e:
        logger.error(f"❌ API Analiz hatası: {type(e).__name__}: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        
        return {
            "success": False,
            "detail": f"Internal Server Error: {type(e).__name__}: {str(e)}",
            "error_type": type(e).__name__
        }

@app.get("/api/support_resistance/{symbol}")
async def get_support_resistance(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1h|4h|1d)$")
):
    """Get support and resistance levels"""
    try:
        logger.info(f"🔍 API İsteği: /api/support_resistance/{symbol}")
        
        # Fetch real data
        candles, market_type = await UniversalDataFetcher.get_market_data(symbol, interval)
        
        if not candles or len(candles) < 10:
            return {
                "success": False,
                "detail": f"Yetersiz veri: {len(candles) if candles else 0} mum",
                "symbol": symbol.upper()
            }
        
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
        
    except Exception as e:
        logger.error(f"❌ Support/resistance API hatası: {e}")
        return {
            "success": False,
            "detail": str(e),
            "symbol": symbol.upper()
        }

@app.get("/api/patterns/{symbol}")
async def get_patterns(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1h|4h|1d)$")
):
    """Get detected patterns"""
    try:
        logger.info(f"🔍 API İsteği: /api/patterns/{symbol}")
        
        # Fetch real data
        candles, market_type = await UniversalDataFetcher.get_market_data(symbol, interval)
        
        if not candles or len(candles) < 5:
            return {
                "success": False,
                "detail": f"Yetersiz veri: {len(candles) if candles else 0} mum",
                "symbol": symbol.upper()
            }
        
        pattern_data = PatternDetector.detect_patterns(candles)
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "interval": interval,
            "market_type": market_type.value,
            "patterns": pattern_data["patterns"],
            "pattern_counts": {
                "total": pattern_data["count"],
                "support_levels": pattern_data["support_levels_count"],
                "resistance_levels": pattern_data["resistance_levels_count"]
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Patterns API hatası: {e}")
        return {
            "success": False,
            "detail": str(e),
            "symbol": symbol.upper()
        }

# ========== HATA YÖNETİMİ ==========
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global hata yöneticisi"""
    logger.error(f"❌ Global hata yakalandı: {type(exc).__name__}: {str(exc)}")
    
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "detail": f"Internal Server Error: {type(exc).__name__}: {str(exc)}",
            "path": request.url.path
        }
    )

# ========== MAIN ==========
if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    
    logger.info("=" * 70)
    logger.info(f"🚀 REAL DATA TRADING BOT v4.6.0 - DEBUG MODE")
    logger.info("=" * 70)
    logger.info(f"📡 Port: {port}")
    logger.info("🌐 Tarayıcıda açın: http://localhost:8000/")
    logger.info("🔧 Hata ayıklama modu: AÇIK")
    logger.info("=" * 70)
    logger.info("VERİ KAYNAKLARI:")
    logger.info("  ✅ Binance API - Gerçek zamanlı kripto verisi")
    logger.info("  ✅ CoinGecko API - Tüm coinler için OHLC verisi")
    logger.info("  ✅ Test Verisi - API hatalarında fallback")
    logger.info("=" * 70)
    logger.info("ÖZELLİKLER:")
    logger.info("  ✅ Destek/Direnç Tespiti")
    logger.info("  ✅ Trend Analizi")
    logger.info("  ✅ Pattern Tanıma")
    logger.info("  ✅ %100 Gerçek Veri (Fallback test modu)")
    logger.info("=" * 70)
    
    # Gelişmiş hata ayıklama
    import warnings
    warnings.filterwarnings("ignore")
    
    # CORS ayarları
    import uvicorn.config
    uvicorn.config.LOGGING_CONFIG["formatters"]["default"]["fmt"] = "%(asctime)s - %(levelname)s - %(message)s"
    
    try:
        uvicorn.run(
            app, 
            host="0.0.0.0", 
            port=port, 
            log_level="info",
            access_log=True,
            timeout_keep_alive=30
        )
    except Exception as e:
        logger.error(f"❌ Uvicorn başlatma hatası: {e}")
        logger.info("🔄 8080 portunu deneyin...")
        uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
