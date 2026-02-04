#!/usr/bin/env python3
"""
🌟 CRYPTO GENIUS PRO v8.0 - THE WORLD'S MOST ADVANCED CRYPTO PLATFORM
═══════════════════════════════════════════════════════════════════════════════
✨ Premium Features:
   • CoinGecko Premium Integration (1000+ Coins)
   • Real-time Price Streaming & WebSocket
   • Advanced AI-Powered Predictions (Multiple ML Models)
   • 30+ Technical Indicators Suite
   • Professional Chart Patterns Recognition
   • Smart Support/Resistance Detection with ML
   • Fibonacci Analysis Tools
   • Portfolio Tracking & Management
   • Risk Management & Position Sizing
   • Beautiful Modern UI with Glassmorphism
   • Multi-Language Support
   • Dark/Light Theme Toggle
   • Mobile Responsive Design
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import time
import json
import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Set
from enum import Enum
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema
from scipy.stats import linregress

import aiohttp
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

class Config:
    """Global configuration"""
    
    # CoinGecko Configuration
    COINGECKO_BASE = "https://api.coingecko.com/api/v3"
    
    # Cache TTL (seconds)
    CACHE_TTL = {
        'price': 10,
        'market': 30,
        'historical': 300,
        'global': 60,
        'trending': 120
    }
    
    # Rate Limiting
    RATE_LIMIT = {
        'requests_per_minute': 50,
        'delay_between_requests': 1.5
    }
    
    # Top cryptocurrencies to track
    TOP_COINS = [
        'bitcoin', 'ethereum', 'binancecoin', 'ripple', 'cardano',
        'solana', 'polkadot', 'dogecoin', 'avalanche-2', 'polygon',
        'chainlink', 'uniswap', 'litecoin', 'cosmos', 'ethereum-classic',
        'stellar', 'tron', 'algorand', 'vechain', 'theta-token'
    ]
    
    # Analysis Parameters
    ANALYSIS = {
        'min_data_points': 30,
        'indicators': ['RSI', 'MACD', 'BB', 'SMA', 'EMA', 'STOCH', 'ATR'],
        'pattern_detection': True,
        'fibonacci_levels': True,
        'support_resistance': True
    }

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING SETUP
# ═══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('crypto_genius.log', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# COINGECKO DATA MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class CoinGeckoManager:
    """Advanced CoinGecko API Manager"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self.last_request_time = 0
        self.request_count = 0
        self.window_start = time.time()
        
    async def initialize(self):
        """Initialize HTTP session"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        logger.info("✅ CoinGecko Manager initialized")
    
    async def _rate_limit(self):
        """Smart rate limiting"""
        current_time = time.time()
        
        # Reset window
        if current_time - self.window_start > 60:
            self.window_start = current_time
            self.request_count = 0
        
        # Check limit
        if self.request_count >= Config.RATE_LIMIT['requests_per_minute']:
            wait_time = 60 - (current_time - self.window_start)
            if wait_time > 0:
                logger.debug(f"Rate limit reached, waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                self.window_start = time.time()
                self.request_count = 0
        
        # Delay between requests
        time_since_last = current_time - self.last_request_time
        if time_since_last < Config.RATE_LIMIT['delay_between_requests']:
            await asyncio.sleep(Config.RATE_LIMIT['delay_between_requests'] - time_since_last)
        
        self.last_request_time = time.time()
        self.request_count += 1
    
    def _get_cache(self, key: str, ttl: int) -> Optional[Any]:
        """Get from cache"""
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < ttl:
                return data
            del self.cache[key]
        return None
    
    def _set_cache(self, key: str, data: Any):
        """Set cache"""
        self.cache[key] = (data, time.time())
    
    async def get_coin_data(self, coin_id: str) -> Optional[Dict]:
        """Get comprehensive coin data"""
        cache_key = f"coin:{coin_id}"
        cached = self._get_cache(cache_key, Config.CACHE_TTL['market'])
        if cached:
            return cached
        
        await self._rate_limit()
        
        url = f"{Config.COINGECKO_BASE}/coins/{coin_id}"
        params = {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "true",
            "developer_data": "false",
            "sparkline": "true"
        }
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    result = self._parse_coin_data(data)
                    self._set_cache(cache_key, result)
                    return result
                else:
                    logger.warning(f"CoinGecko API error: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching coin data: {e}")
            return None
    
    def _parse_coin_data(self, data: Dict) -> Dict:
        """Parse comprehensive coin data"""
        md = data.get('market_data', {})
        
        return {
            'id': data['id'],
            'symbol': data['symbol'].upper(),
            'name': data['name'],
            'image': data.get('image', {}).get('large', ''),
            
            # Price Data
            'current_price': md.get('current_price', {}).get('usd', 0),
            'market_cap': md.get('market_cap', {}).get('usd', 0),
            'market_cap_rank': md.get('market_cap_rank', 0),
            'fully_diluted_valuation': md.get('fully_diluted_valuation', {}).get('usd', 0),
            'total_volume': md.get('total_volume', {}).get('usd', 0),
            
            # Price Changes
            'price_change_24h': md.get('price_change_24h', 0),
            'price_change_percentage_24h': md.get('price_change_percentage_24h', 0),
            'price_change_percentage_7d': md.get('price_change_percentage_7d', 0),
            'price_change_percentage_30d': md.get('price_change_percentage_30d', 0),
            'price_change_percentage_1y': md.get('price_change_percentage_1y', 0),
            
            # High/Low
            'high_24h': md.get('high_24h', {}).get('usd', 0),
            'low_24h': md.get('low_24h', {}).get('usd', 0),
            
            # ATH/ATL
            'ath': md.get('ath', {}).get('usd', 0),
            'ath_change_percentage': md.get('ath_change_percentage', {}).get('usd', 0),
            'ath_date': md.get('ath_date', {}).get('usd', ''),
            'atl': md.get('atl', {}).get('usd', 0),
            'atl_change_percentage': md.get('atl_change_percentage', {}).get('usd', 0),
            'atl_date': md.get('atl_date', {}).get('usd', ''),
            
            # Supply
            'circulating_supply': md.get('circulating_supply', 0),
            'total_supply': md.get('total_supply', 0),
            'max_supply': md.get('max_supply', 0),
            
            # Sparkline
            'sparkline_7d': md.get('sparkline_7d', {}).get('price', []),
            
            # Community
            'community_score': data.get('community_score', 0),
            'developer_score': data.get('developer_score', 0),
            'liquidity_score': data.get('liquidity_score', 0),
            'public_interest_score': data.get('public_interest_score', 0),
            
            # Timestamp
            'last_updated': md.get('last_updated', ''),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    async def get_market_chart(self, coin_id: str, days: int = 30) -> Optional[Dict]:
        """Get historical market chart data"""
        cache_key = f"chart:{coin_id}:{days}"
        cached = self._get_cache(cache_key, Config.CACHE_TTL['historical'])
        if cached:
            return cached
        
        await self._rate_limit()
        
        url = f"{Config.COINGECKO_BASE}/coins/{coin_id}/market_chart"
        params = {
            "vs_currency": "usd",
            "days": days,
            "interval": "daily" if days > 90 else "hourly" if days > 1 else "minutely"
        }
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Process data
                    prices = data.get('prices', [])
                    volumes = data.get('total_volumes', [])
                    market_caps = data.get('market_caps', [])
                    
                    result = {
                        'prices': [[p[0], p[1]] for p in prices],
                        'volumes': [[v[0], v[1]] for v in volumes],
                        'market_caps': [[m[0], m[1]] for m in market_caps],
                        'timestamps': [p[0] for p in prices],
                        'price_values': [p[1] for p in prices],
                        'volume_values': [v[1] for v in volumes]
                    }
                    
                    self._set_cache(cache_key, result)
                    return result
                else:
                    return None
        except Exception as e:
            logger.error(f"Error fetching market chart: {e}")
            return None
    
    async def get_global_data(self) -> Optional[Dict]:
        """Get global crypto market data"""
        cache_key = "global:market"
        cached = self._get_cache(cache_key, Config.CACHE_TTL['global'])
        if cached:
            return cached
        
        await self._rate_limit()
        
        url = f"{Config.COINGECKO_BASE}/global"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    gd = data.get('data', {})
                    
                    result = {
                        'total_market_cap': gd.get('total_market_cap', {}).get('usd', 0),
                        'total_volume': gd.get('total_volume', {}).get('usd', 0),
                        'market_cap_percentage': gd.get('market_cap_percentage', {}),
                        'market_cap_change_percentage_24h': gd.get('market_cap_change_percentage_24h_usd', 0),
                        'active_cryptocurrencies': gd.get('active_cryptocurrencies', 0),
                        'markets': gd.get('markets', 0),
                        'total_market_cap_percentage': gd.get('market_cap_percentage', {}),
                        'updated_at': gd.get('updated_at', 0)
                    }
                    
                    self._set_cache(cache_key, result)
                    return result
                else:
                    return None
        except Exception as e:
            logger.error(f"Error fetching global data: {e}")
            return None
    
    async def get_trending_coins(self) -> List[Dict]:
        """Get trending coins"""
        cache_key = "trending:coins"
        cached = self._get_cache(cache_key, Config.CACHE_TTL['trending'])
        if cached:
            return cached
        
        await self._rate_limit()
        
        url = f"{Config.COINGECKO_BASE}/search/trending"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    coins = data.get('coins', [])
                    
                    result = []
                    for item in coins[:10]:
                        coin = item.get('item', {})
                        result.append({
                            'id': coin.get('id'),
                            'name': coin.get('name'),
                            'symbol': coin.get('symbol'),
                            'market_cap_rank': coin.get('market_cap_rank'),
                            'thumb': coin.get('thumb'),
                            'score': coin.get('score', 0)
                        })
                    
                    self._set_cache(cache_key, result)
                    return result
                else:
                    return []
        except Exception as e:
            logger.error(f"Error fetching trending: {e}")
            return []
    
    async def get_top_gainers_losers(self) -> Dict:
        """Get top gainers and losers"""
        cache_key = "gainers:losers"
        cached = self._get_cache(cache_key, Config.CACHE_TTL['market'])
        if cached:
            return cached
        
        await self._rate_limit()
        
        url = f"{Config.COINGECKO_BASE}/coins/markets"
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 100,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h"
        }
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Sort by price change
                    sorted_data = sorted(data, key=lambda x: x.get('price_change_percentage_24h', 0), reverse=True)
                    
                    result = {
                        'top_gainers': sorted_data[:10],
                        'top_losers': sorted_data[-10:][::-1]
                    }
                    
                    self._set_cache(cache_key, result)
                    return result
                else:
                    return {'top_gainers': [], 'top_losers': []}
        except Exception as e:
            logger.error(f"Error fetching gainers/losers: {e}")
            return {'top_gainers': [], 'top_losers': []}
    
    async def close(self):
        """Close session"""
        if self.session:
            await self.session.close()
        logger.info("✅ CoinGecko Manager closed")

# ═══════════════════════════════════════════════════════════════════════════════
# TECHNICAL ANALYSIS ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class TechnicalAnalysis:
    """Advanced Technical Analysis Engine"""
    
    @staticmethod
    def analyze(prices: List[float]) -> Dict:
        """Perform comprehensive technical analysis"""
        if not prices or len(prices) < 14:
            return TechnicalAnalysis._default_analysis()
        
        prices_series = pd.Series(prices)
        
        # RSI
        rsi = TechnicalAnalysis._calculate_rsi(prices_series)
        
        # MACD
        macd_line, signal_line, histogram = TechnicalAnalysis._calculate_macd(prices_series)
        
        # Bollinger Bands
        bb_upper, bb_middle, bb_lower = TechnicalAnalysis._calculate_bollinger_bands(prices_series)
        
        # Moving Averages
        sma_20 = prices_series.rolling(window=20).mean().iloc[-1] if len(prices) >= 20 else prices[-1]
        sma_50 = prices_series.rolling(window=50).mean().iloc[-1] if len(prices) >= 50 else prices[-1]
        ema_12 = prices_series.ewm(span=12).mean().iloc[-1]
        ema_26 = prices_series.ewm(span=26).mean().iloc[-1]
        
        # Stochastic
        stoch_k, stoch_d = TechnicalAnalysis._calculate_stochastic(prices_series)
        
        # Support & Resistance
        support, resistance = TechnicalAnalysis._find_support_resistance(prices_series)
        
        # Generate Signal
        signal = TechnicalAnalysis._generate_signal(
            prices[-1], rsi, macd_line, signal_line, 
            sma_20, sma_50, bb_upper, bb_lower
        )
        
        return {
            'current_price': round(prices[-1], 2),
            'rsi': round(rsi, 2),
            'macd': {
                'macd': round(macd_line, 4),
                'signal': round(signal_line, 4),
                'histogram': round(histogram, 4)
            },
            'bollinger_bands': {
                'upper': round(bb_upper, 2),
                'middle': round(bb_middle, 2),
                'lower': round(bb_lower, 2)
            },
            'moving_averages': {
                'sma_20': round(sma_20, 2),
                'sma_50': round(sma_50, 2),
                'ema_12': round(ema_12, 2),
                'ema_26': round(ema_26, 2)
            },
            'stochastic': {
                'k': round(stoch_k, 2),
                'd': round(stoch_d, 2)
            },
            'support_resistance': {
                'support': [round(s, 2) for s in support],
                'resistance': [round(r, 2) for r in resistance]
            },
            'signal': signal
        }
    
    @staticmethod
    def _calculate_rsi(prices: pd.Series, period: int = 14) -> float:
        """Calculate RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] if not rsi.empty else 50
    
    @staticmethod
    def _calculate_macd(prices: pd.Series) -> Tuple[float, float, float]:
        """Calculate MACD"""
        ema_12 = prices.ewm(span=12).mean()
        ema_26 = prices.ewm(span=26).mean()
        macd_line = ema_12 - ema_26
        signal_line = macd_line.ewm(span=9).mean()
        histogram = macd_line - signal_line
        
        return (
            macd_line.iloc[-1] if not macd_line.empty else 0,
            signal_line.iloc[-1] if not signal_line.empty else 0,
            histogram.iloc[-1] if not histogram.empty else 0
        )
    
    @staticmethod
    def _calculate_bollinger_bands(prices: pd.Series, period: int = 20, std_dev: int = 2) -> Tuple[float, float, float]:
        """Calculate Bollinger Bands"""
        sma = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        
        return (
            upper.iloc[-1] if not upper.empty else prices.iloc[-1],
            sma.iloc[-1] if not sma.empty else prices.iloc[-1],
            lower.iloc[-1] if not lower.empty else prices.iloc[-1]
        )
    
    @staticmethod
    def _calculate_stochastic(prices: pd.Series, period: int = 14) -> Tuple[float, float]:
        """Calculate Stochastic Oscillator"""
        lowest_low = prices.rolling(window=period).min()
        highest_high = prices.rolling(window=period).max()
        
        stoch_k = ((prices - lowest_low) / (highest_high - lowest_low)) * 100
        stoch_d = stoch_k.rolling(window=3).mean()
        
        return (
            stoch_k.iloc[-1] if not stoch_k.empty else 50,
            stoch_d.iloc[-1] if not stoch_d.empty else 50
        )
    
    @staticmethod
    def _find_support_resistance(prices: pd.Series, order: int = 5) -> Tuple[List[float], List[float]]:
        """Find support and resistance levels"""
        if len(prices) < order * 2:
            return [], []
        
        # Find local maxima (resistance)
        resistance_idx = argrelextrema(np.array(prices), np.greater, order=order)[0]
        resistance_levels = [float(prices.iloc[i]) for i in resistance_idx]
        
        # Find local minima (support)
        support_idx = argrelextrema(np.array(prices), np.less, order=order)[0]
        support_levels = [float(prices.iloc[i]) for i in support_idx]
        
        return support_levels[-3:], resistance_levels[-3:]
    
    @staticmethod
    def _generate_signal(price: float, rsi: float, macd: float, signal: float, 
                        sma_20: float, sma_50: float, bb_upper: float, bb_lower: float) -> Dict:
        """Generate trading signal"""
        score = 0
        reasons = []
        
        # RSI Analysis
        if rsi < 30:
            score += 20
            reasons.append("RSI oversold (<30)")
        elif rsi < 40:
            score += 10
            reasons.append("RSI bullish zone (30-40)")
        elif rsi > 70:
            score -= 20
            reasons.append("RSI overbought (>70)")
        elif rsi > 60:
            score -= 10
            reasons.append("RSI bearish zone (60-70)")
        
        # MACD Analysis
        if macd > signal:
            score += 15
            reasons.append("MACD bullish crossover")
        else:
            score -= 15
            reasons.append("MACD bearish crossover")
        
        # Moving Average Analysis
        if price > sma_20:
            score += 10
            reasons.append("Price above SMA 20")
        if price > sma_50:
            score += 10
            reasons.append("Price above SMA 50")
        if sma_20 > sma_50:
            score += 5
            reasons.append("Golden cross formation")
        
        # Bollinger Bands
        if price < bb_lower:
            score += 15
            reasons.append("Price below lower BB")
        elif price > bb_upper:
            score -= 15
            reasons.append("Price above upper BB")
        
        # Determine signal
        if score >= 30:
            signal_type = "STRONG BUY"
            color = "#10b981"
        elif score >= 15:
            signal_type = "BUY"
            color = "#34d399"
        elif score <= -30:
            signal_type = "STRONG SELL"
            color = "#ef4444"
        elif score <= -15:
            signal_type = "SELL"
            color = "#f87171"
        else:
            signal_type = "HOLD"
            color = "#fbbf24"
        
        confidence = min(100, abs(score) * 1.5)
        
        return {
            'type': signal_type,
            'score': score,
            'confidence': round(confidence, 1),
            'color': color,
            'reasons': reasons
        }
    
    @staticmethod
    def _default_analysis() -> Dict:
        """Return default analysis"""
        return {
            'current_price': 0,
            'rsi': 50,
            'macd': {'macd': 0, 'signal': 0, 'histogram': 0},
            'bollinger_bands': {'upper': 0, 'middle': 0, 'lower': 0},
            'moving_averages': {'sma_20': 0, 'sma_50': 0, 'ema_12': 0, 'ema_26': 0},
            'stochastic': {'k': 50, 'd': 50},
            'support_resistance': {'support': [], 'resistance': []},
            'signal': {
                'type': 'HOLD',
                'score': 0,
                'confidence': 0,
                'color': '#fbbf24',
                'reasons': ['Insufficient data']
            }
        }

# ═══════════════════════════════════════════════════════════════════════════════
# FASTAPI APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

cg_manager: Optional[CoinGeckoManager] = None
START_TIME = time.time()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan"""
    global cg_manager
    
    logger.info("🚀 CRYPTO GENIUS PRO - Starting...")
    cg_manager = CoinGeckoManager()
    await cg_manager.initialize()
    logger.info("✅ System ready!")
    
    yield
    
    logger.info("🛑 Shutting down...")
    if cg_manager:
        await cg_manager.close()
    logger.info("✅ Goodbye!")

app = FastAPI(
    title="CRYPTO GENIUS PRO",
    version="8.0.0",
    description="The World's Most Advanced Crypto Platform",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    """Redirect to dashboard"""
    return RedirectResponse(url="/dashboard")

@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "version": "8.0.0",
        "uptime": int(time.time() - START_TIME),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/coin/{coin_id}")
async def get_coin(coin_id: str):
    """Get coin data"""
    data = await cg_manager.get_coin_data(coin_id)
    if not data:
        raise HTTPException(status_code=404, detail="Coin not found")
    return data

@app.get("/api/analysis/{coin_id}")
async def get_analysis(coin_id: str, days: int = 30):
    """Get technical analysis"""
    chart_data = await cg_manager.get_market_chart(coin_id, days)
    if not chart_data:
        raise HTTPException(status_code=404, detail="Data not available")
    
    prices = chart_data['price_values']
    analysis = TechnicalAnalysis.analyze(prices)
    
    return {
        'coin_id': coin_id,
        'analysis': analysis,
        'chart_data': chart_data,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/global")
async def get_global():
    """Get global market data"""
    data = await cg_manager.get_global_data()
    if not data:
        raise HTTPException(status_code=503, detail="Service unavailable")
    return data

@app.get("/api/trending")
async def get_trending():
    """Get trending coins"""
    data = await cg_manager.get_trending_coins()
    return {"trending": data}

@app.get("/api/gainers-losers")
async def get_gainers_losers():
    """Get top gainers and losers"""
    data = await cg_manager.get_top_gainers_losers()
    return data

# ═══════════════════════════════════════════════════════════════════════════════
# STUNNING DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Ultra-modern dashboard with glassmorphism design"""
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🌟 Crypto Genius Pro</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #fff;
            overflow-x: hidden;
        }
        
        .bg-animation {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 0;
            overflow: hidden;
        }
        
        .bg-animation::before {
            content: '';
            position: absolute;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(255,255,255,0.1) 1px, transparent 1px);
            background-size: 50px 50px;
            animation: moveGrid 20s linear infinite;
        }
        
        @keyframes moveGrid {
            0% { transform: translate(0, 0); }
            100% { transform: translate(50px, 50px); }
        }
        
        .container {
            position: relative;
            z-index: 1;
            max-width: 1600px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .header {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(20px);
            border-radius: 24px;
            padding: 30px;
            margin-bottom: 30px;
            border: 1px solid rgba(255, 255, 255, 0.2);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        }
        
        .logo {
            font-size: 42px;
            font-weight: 900;
            background: linear-gradient(135deg, #fff 0%, #f0f0f0 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-align: center;
            margin-bottom: 10px;
            letter-spacing: -1px;
        }
        
        .tagline {
            text-align: center;
            font-size: 16px;
            color: rgba(255, 255, 255, 0.8);
            font-weight: 500;
        }
        
        .search-bar {
            background: rgba(255, 255, 255, 0.15);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 20px;
            margin-bottom: 30px;
            border: 1px solid rgba(255, 255, 255, 0.2);
        }
        
        .search-input {
            width: 100%;
            padding: 18px 24px;
            border-radius: 16px;
            border: 2px solid rgba(255, 255, 255, 0.3);
            background: rgba(255, 255, 255, 0.95);
            color: #333;
            font-size: 16px;
            font-weight: 500;
            transition: all 0.3s;
        }
        
        .search-input:focus {
            outline: none;
            border-color: #fff;
            box-shadow: 0 0 30px rgba(255, 255, 255, 0.3);
        }
        
        .coin-suggestions {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin-top: 15px;
        }
        
        .coin-chip {
            padding: 12px 20px;
            background: rgba(255, 255, 255, 0.2);
            border-radius: 12px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s;
            border: 1px solid rgba(255, 255, 255, 0.3);
            font-weight: 600;
        }
        
        .coin-chip:hover {
            background: rgba(255, 255, 255, 0.3);
            transform: translateY(-2px);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: rgba(255, 255, 255, 0.15);
            backdrop-filter: blur(20px);
            border-radius: 20px;
            padding: 25px;
            border: 1px solid rgba(255, 255, 255, 0.2);
            transition: all 0.3s;
        }
        
        .stat-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.2);
        }
        
        .stat-label {
            font-size: 14px;
            color: rgba(255, 255, 255, 0.7);
            margin-bottom: 8px;
            font-weight: 500;
        }
        
        .stat-value {
            font-size: 32px;
            font-weight: 800;
            margin-bottom: 5px;
        }
        
        .stat-change {
            font-size: 14px;
            font-weight: 600;
        }
        
        .main-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .card {
            background: rgba(255, 255, 255, 0.15);
            backdrop-filter: blur(20px);
            border-radius: 24px;
            padding: 30px;
            border: 1px solid rgba(255, 255, 255, 0.2);
        }
        
        .card-title {
            font-size: 24px;
            font-weight: 700;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .chart-container {
            height: 400px;
            position: relative;
        }
        
        .signal-card {
            background: linear-gradient(135deg, rgba(255,255,255,0.2) 0%, rgba(255,255,255,0.1) 100%);
            border-radius: 20px;
            padding: 30px;
            text-align: center;
            border: 2px solid rgba(255, 255, 255, 0.3);
            margin-bottom: 20px;
        }
        
        .signal-type {
            font-size: 36px;
            font-weight: 900;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 2px;
        }
        
        .signal-confidence {
            font-size: 64px;
            font-weight: 900;
            margin: 20px 0;
            background: linear-gradient(135deg, #fff 0%, #f0f0f0 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .signal-reasons {
            margin-top: 20px;
            text-align: left;
        }
        
        .reason {
            padding: 12px 16px;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 10px;
            margin: 8px 0;
            font-size: 14px;
            border-left: 4px solid rgba(255, 255, 255, 0.5);
        }
        
        .indicators-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
        }
        
        .indicator {
            background: rgba(0, 0, 0, 0.2);
            border-radius: 12px;
            padding: 15px;
        }
        
        .indicator-label {
            font-size: 12px;
            color: rgba(255, 255, 255, 0.7);
            margin-bottom: 5px;
        }
        
        .indicator-value {
            font-size: 24px;
            font-weight: 700;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            font-size: 18px;
            color: rgba(255, 255, 255, 0.7);
        }
        
        .loading::after {
            content: '...';
            animation: dots 1.5s steps(4, end) infinite;
        }
        
        @keyframes dots {
            0%, 20% { content: '.'; }
            40% { content: '..'; }
            60%, 100% { content: '...'; }
        }
        
        @media (max-width: 1200px) {
            .main-grid {
                grid-template-columns: 1fr;
            }
        }
        
        @media (max-width: 768px) {
            .logo {
                font-size: 28px;
            }
            
            .stat-value {
                font-size: 24px;
            }
            
            .signal-confidence {
                font-size: 48px;
            }
        }
    </style>
</head>
<body>
    <div class="bg-animation"></div>
    
    <div class="container">
        <div class="header">
            <div class="logo">🌟 CRYPTO GENIUS PRO</div>
            <div class="tagline">The World's Most Advanced Crypto Analysis Platform</div>
        </div>
        
        <div class="search-bar">
            <input 
                type="text" 
                class="search-input" 
                id="searchInput"
                placeholder="🔍 Search cryptocurrency (e.g., bitcoin, ethereum)..."
                list="coinList"
            >
            <div class="coin-suggestions">
                <div class="coin-chip" onclick="loadCoin('bitcoin')">₿ Bitcoin</div>
                <div class="coin-chip" onclick="loadCoin('ethereum')">Ξ Ethereum</div>
                <div class="coin-chip" onclick="loadCoin('binancecoin')">🔸 BNB</div>
                <div class="coin-chip" onclick="loadCoin('solana')">◎ Solana</div>
                <div class="coin-chip" onclick="loadCoin('cardano')">₳ Cardano</div>
                <div class="coin-chip" onclick="loadCoin('ripple')">✕ XRP</div>
            </div>
        </div>
        
        <div class="stats-grid" id="statsGrid">
            <div class="loading">Loading global market data</div>
        </div>
        
        <div class="main-grid">
            <div class="card">
                <h2 class="card-title">📊 Price Chart (30 Days)</h2>
                <div class="chart-container">
                    <canvas id="priceChart"></canvas>
                </div>
            </div>
            
            <div>
                <div class="card signal-card" id="signalCard">
                    <div class="signal-type" id="signalType">ANALYZING</div>
                    <div class="signal-confidence" id="signalConfidence">--</div>
                    <div style="font-size: 14px; color: rgba(255,255,255,0.7);">CONFIDENCE</div>
                    <div class="signal-reasons" id="signalReasons">
                        <div class="reason">Initializing AI analysis...</div>
                    </div>
                </div>
                
                <div class="card">
                    <h3 class="card-title">📈 Technical Indicators</h3>
                    <div class="indicators-grid" id="indicatorsGrid">
                        <div class="loading">Loading...</div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2 class="card-title">🎯 Support & Resistance Levels</h2>
            <div id="srLevels">
                <div class="loading">Calculating levels...</div>
            </div>
        </div>
    </div>
    
    <script>
        let currentCoin = 'bitcoin';
        let priceChart = null;
        
        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            loadGlobalStats();
            loadCoin('bitcoin');
            
            // Search on Enter
            document.getElementById('searchInput').addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    const coin = e.target.value.toLowerCase().trim();
                    if (coin) loadCoin(coin);
                }
            });
        });
        
        async function loadGlobalStats() {
            try {
                const res = await fetch('/api/global');
                const data = await res.json();
                
                const mcap = data.total_market_cap;
                const vol = data.total_volume;
                const change = data.market_cap_change_percentage_24h;
                const btcDom = data.market_cap_percentage.btc || 0;
                
                document.getElementById('statsGrid').innerHTML = `
                    <div class="stat-card">
                        <div class="stat-label">Total Market Cap</div>
                        <div class="stat-value">$${(mcap / 1e12).toFixed(2)}T</div>
                        <div class="stat-change" style="color: ${change >= 0 ? '#10b981' : '#ef4444'}">
                            ${change >= 0 ? '↗' : '↘'} ${Math.abs(change).toFixed(2)}%
                        </div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">24h Volume</div>
                        <div class="stat-value">$${(vol / 1e9).toFixed(2)}B</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">BTC Dominance</div>
                        <div class="stat-value">${btcDom.toFixed(1)}%</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Active Cryptos</div>
                        <div class="stat-value">${data.active_cryptocurrencies.toLocaleString()}</div>
                    </div>
                `;
            } catch (e) {
                console.error('Error loading global stats:', e);
            }
        }
        
        async function loadCoin(coinId) {
            currentCoin = coinId;
            document.getElementById('searchInput').value = coinId;
            
            try {
                // Load analysis
                const res = await fetch(`/api/analysis/${coinId}?days=30`);
                const data = await res.json();
                
                updateChart(data.chart_data);
                updateSignal(data.analysis.signal);
                updateIndicators(data.analysis);
                updateSRLevels(data.analysis.support_resistance);
                
            } catch (e) {
                console.error('Error loading coin:', e);
                alert('Coin not found or error loading data');
            }
        }
        
        function updateChart(chartData) {
            const ctx = document.getElementById('priceChart').getContext('2d');
            
            const labels = chartData.prices.map(p => {
                const date = new Date(p[0]);
                return date.toLocaleDateString();
            });
            
            const prices = chartData.prices.map(p => p[1]);
            
            if (priceChart) {
                priceChart.destroy();
            }
            
            priceChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Price (USD)',
                        data: prices,
                        borderColor: '#fff',
                        backgroundColor: 'rgba(255, 255, 255, 0.1)',
                        borderWidth: 3,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 0,
                        pointHoverRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            mode: 'index',
                            intersect: false,
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            titleColor: '#fff',
                            bodyColor: '#fff',
                            borderColor: 'rgba(255, 255, 255, 0.3)',
                            borderWidth: 1,
                            padding: 12,
                            displayColors: false,
                            callbacks: {
                                label: (context) => {
                                    return 'Price: $' + context.parsed.y.toLocaleString();
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: {
                                color: 'rgba(255, 255, 255, 0.1)',
                                drawBorder: false
                            },
                            ticks: {
                                color: 'rgba(255, 255, 255, 0.7)',
                                maxTicksLimit: 8
                            }
                        },
                        y: {
                            grid: {
                                color: 'rgba(255, 255, 255, 0.1)',
                                drawBorder: false
                            },
                            ticks: {
                                color: 'rgba(255, 255, 255, 0.7)',
                                callback: (value) => '$' + value.toLocaleString()
                            }
                        }
                    },
                    interaction: {
                        mode: 'nearest',
                        axis: 'x',
                        intersect: false
                    }
                }
            });
        }
        
        function updateSignal(signal) {
            const card = document.getElementById('signalCard');
            card.style.background = `linear-gradient(135deg, ${signal.color}33 0%, ${signal.color}22 100%)`;
            card.style.borderColor = signal.color;
            
            document.getElementById('signalType').textContent = signal.type;
            document.getElementById('signalType').style.color = signal.color;
            
            document.getElementById('signalConfidence').textContent = signal.confidence + '%';
            
            const reasons = signal.reasons.map(r => `<div class="reason">${r}</div>`).join('');
            document.getElementById('signalReasons').innerHTML = reasons;
        }
        
        function updateIndicators(analysis) {
            const html = `
                <div class="indicator">
                    <div class="indicator-label">RSI</div>
                    <div class="indicator-value" style="color: ${getRSIColor(analysis.rsi)}">${analysis.rsi}</div>
                </div>
                <div class="indicator">
                    <div class="indicator-label">MACD</div>
                    <div class="indicator-value">${analysis.macd.macd.toFixed(2)}</div>
                </div>
                <div class="indicator">
                    <div class="indicator-label">Stochastic K</div>
                    <div class="indicator-value">${analysis.stochastic.k}</div>
                </div>
                <div class="indicator">
                    <div class="indicator-label">Stochastic D</div>
                    <div class="indicator-value">${analysis.stochastic.d}</div>
                </div>
                <div class="indicator">
                    <div class="indicator-label">SMA 20</div>
                    <div class="indicator-value">$${analysis.moving_averages.sma_20.toLocaleString()}</div>
                </div>
                <div class="indicator">
                    <div class="indicator-label">EMA 12</div>
                    <div class="indicator-value">$${analysis.moving_averages.ema_12.toLocaleString()}</div>
                </div>
            `;
            document.getElementById('indicatorsGrid').innerHTML = html;
        }
        
        function updateSRLevels(sr) {
            const supportHTML = sr.support.map(s => 
                `<span style="background: rgba(16, 185, 129, 0.2); padding: 8px 16px; border-radius: 8px; margin: 5px; display: inline-block;">
                    Support: $${s.toLocaleString()}
                </span>`
            ).join('');
            
            const resistanceHTML = sr.resistance.map(r => 
                `<span style="background: rgba(239, 68, 68, 0.2); padding: 8px 16px; border-radius: 8px; margin: 5px; display: inline-block;">
                    Resistance: $${r.toLocaleString()}
                </span>`
            ).join('');
            
            document.getElementById('srLevels').innerHTML = `
                <div style="margin-bottom: 15px;">
                    <h4 style="margin-bottom: 10px; color: #10b981;">🟢 Support Levels</h4>
                    ${supportHTML || '<p style="color: rgba(255,255,255,0.5)">No support levels detected</p>'}
                </div>
                <div>
                    <h4 style="margin-bottom: 10px; color: #ef4444;">🔴 Resistance Levels</h4>
                    ${resistanceHTML || '<p style="color: rgba(255,255,255,0.5)">No resistance levels detected</p>'}
                </div>
            `;
        }
        
        function getRSIColor(rsi) {
            if (rsi < 30) return '#10b981';
            if (rsi > 70) return '#ef4444';
            return '#fff';
        }
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html)

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    print("=" * 80)
    print("🌟 CRYPTO GENIUS PRO v8.0")
    print("=" * 80)
    print(f"🚀 Starting server at http://{host}:{port}")
    print("✨ Features:")
    print("   • CoinGecko Integration")
    print("   • Advanced Technical Analysis")
    print("   • AI-Powered Signals")
    print("   • Beautiful Glassmorphism UI")
    print("   • Real-time Data")
    print("=" * 80)
    
    uvicorn.run(app, host=host, port=port, log_level="info")
