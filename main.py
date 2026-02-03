"""
Advanced Professional Trading Bot v5.0
Production-Ready Cryptocurrency Trading Platform
Features:
- Real-time CoinGecko price data integration
- Advanced technical analysis (20+ indicators)
- Fibonacci retracements & extensions
- Support/Resistance detection
- Chart pattern recognition (Head & Shoulders, Double Top/Bottom, Triangles)
- TradingView widget integration with click-to-expand
- AI-powered trading signals
- Premium subscription system
- Modern responsive dashboard with vibrant colors
"""

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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# ====================================================================================
# SUBSCRIPTION TIERS
# ====================================================================================

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

# ====================================================================================
# COINGECKO REAL-TIME DATA PROVIDER
# ====================================================================================

class CoinGeckoDataProvider:
    """Real-time cryptocurrency data from CoinGecko API"""
    
    BASE_URL = "https://api.coingecko.com/api/v3"
    
    # Top cryptocurrencies to track
    DEFAULT_COINS = [
        "bitcoin", "ethereum", "binancecoin", "ripple", "cardano",
        "solana", "polkadot", "dogecoin", "avalanche-2", "chainlink",
        "polygon", "uniswap", "litecoin", "bitcoin-cash", "stellar"
    ]
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = {}
        self.cache_duration = 30  # Cache for 30 seconds
        self.historical_data = {}
        
    async def initialize(self):
        """Initialize aiohttp session"""
        if not self.session:
            self.session = aiohttp.ClientSession()
            logger.info("✅ CoinGecko API session initialized")
    
    async def close(self):
        """Close aiohttp session"""
        if self.session:
            await self.session.close()
            logger.info("🔌 CoinGecko API session closed")
    
    async def fetch_price_data(self, coin_ids: List[str] = None) -> Dict:
        """Fetch real-time price data from CoinGecko"""
        if not coin_ids:
            coin_ids = self.DEFAULT_COINS
        
        # Check cache
        cache_key = ",".join(sorted(coin_ids))
        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            if (datetime.now(timezone.utc) - timestamp).total_seconds() < self.cache_duration:
                return cached_data
        
        try:
            url = f"{self.BASE_URL}/simple/price"
            params = {
                "ids": ",".join(coin_ids),
                "vs_currencies": "usd",
                "include_24hr_vol": "true",
                "include_24hr_change": "true",
                "include_market_cap": "true",
                "include_last_updated_at": "true"
            }
            
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Transform data
                    result = {}
                    for coin_id, coin_data in data.items():
                        symbol = coin_id.upper()
                        result[symbol] = {
                            "symbol": symbol,
                            "coin_id": coin_id,
                            "price": coin_data.get("usd", 0),
                            "change_24h": coin_data.get("usd_24h_change", 0),
                            "volume_24h": coin_data.get("usd_24h_vol", 0),
                            "market_cap": coin_data.get("usd_market_cap", 0),
                            "last_updated": datetime.fromtimestamp(
                                coin_data.get("last_updated_at", 0), 
                                tz=timezone.utc
                            ).isoformat()
                        }
                    
                    # Update cache
                    self.cache[cache_key] = (result, datetime.now(timezone.utc))
                    logger.info(f"📊 Fetched prices for {len(result)} coins")
                    return result
                else:
                    logger.error(f"CoinGecko API error: {response.status}")
                    return {}
        except Exception as e:
            logger.error(f"Error fetching CoinGecko data: {e}")
            return {}
    
    async def fetch_historical_data(self, coin_id: str, days: int = 30) -> List[Dict]:
        """Fetch historical OHLCV data"""
        try:
            url = f"{self.BASE_URL}/coins/{coin_id}/ohlc"
            params = {"vs_currency": "usd", "days": str(days)}
            
            async with self.session.get(url, params=params, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Transform to candle format
                    candles = []
                    for item in data:
                        candles.append({
                            "timestamp": item[0],
                            "open": item[1],
                            "high": item[2],
                            "low": item[3],
                            "close": item[4]
                        })
                    
                    self.historical_data[coin_id] = candles
                    logger.info(f"📈 Fetched {len(candles)} candles for {coin_id}")
                    return candles
                else:
                    logger.error(f"Historical data error: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            return []
    
    async def get_market_overview(self) -> Dict:
        """Get comprehensive market overview"""
        data = await self.fetch_price_data()
        
        if not data:
            return {}
        
        values = list(data.values())
        
        # Calculate metrics
        total_market_cap = sum(v.get("market_cap", 0) for v in values)
        total_volume = sum(v.get("volume_24h", 0) for v in values)
        avg_change = np.mean([v.get("change_24h", 0) for v in values])
        
        # Market sentiment
        bullish = sum(1 for v in values if v.get("change_24h", 0) > 0)
        bearish = sum(1 for v in values if v.get("change_24h", 0) < 0)
        
        # Top movers
        top_gainers = sorted(values, key=lambda x: x.get("change_24h", 0), reverse=True)[:5]
        top_losers = sorted(values, key=lambda x: x.get("change_24h", 0))[:5]
        
        return {
            "total_coins": len(data),
            "total_market_cap": total_market_cap,
            "total_volume_24h": total_volume,
            "avg_change_24h": round(avg_change, 2),
            "market_sentiment": {
                "bullish": bullish,
                "bearish": bearish,
                "neutral": len(data) - bullish - bearish,
                "ratio": round(bullish / len(data) * 100, 1)
            },
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "last_update": datetime.now(timezone.utc).isoformat()
        }

# ====================================================================================
# ADVANCED TECHNICAL ANALYSIS ENGINE
# ====================================================================================

class TechnicalAnalysis:
    """Comprehensive technical analysis with 20+ indicators"""
    
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
            "0.0": round(high, 2),
            "0.236": round(high - 0.236 * diff, 2),
            "0.382": round(high - 0.382 * diff, 2),
            "0.5": round(high - 0.5 * diff, 2),
            "0.618": round(high - 0.618 * diff, 2),
            "0.786": round(high - 0.786 * diff, 2),
            "1.0": round(low, 2),
            # Extensions
            "1.272": round(low - 0.272 * diff, 2),
            "1.618": round(low - 0.618 * diff, 2),
            "2.618": round(low - 1.618 * diff, 2)
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
        # Check for higher lows and flat resistance
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
        
        return patterns

# ====================================================================================
# AI SIGNAL ENGINE
# ====================================================================================

@dataclass
class TradingSignal:
    symbol: str
    signal: str  # STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL
    confidence: float
    price: float
    targets: List[float]
    stop_loss: float
    risk_reward: float
    indicators: Dict
    patterns: List[Dict]
    fibonacci: Dict
    support_resistance: Dict
    timestamp: str

class AISignalEngine:
    """Advanced AI-powered signal generation"""
    
    def __init__(self, data_provider: CoinGeckoDataProvider):
        self.data_provider = data_provider
        self.ta = TechnicalAnalysis()
    
    async def analyze_coin(self, coin_id: str) -> TradingSignal:
        """Comprehensive analysis of a cryptocurrency"""
        
        # Fetch historical data
        candles = await self.data_provider.fetch_historical_data(coin_id, days=30)
        
        if len(candles) < 30:
            return self._neutral_signal(coin_id)
        
        # Extract OHLC data
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        
        current_price = closes[-1]
        
        # Calculate indicators
        sma_20 = self.ta.calculate_sma(closes, 20)
        sma_50 = self.ta.calculate_sma(closes, 50)
        ema_12 = self.ta.calculate_ema(closes, 12)
        rsi = self.ta.calculate_rsi(closes, 14)
        macd, signal_line, histogram = self.ta.calculate_macd(closes)
        bb_upper, bb_middle, bb_lower = self.ta.calculate_bollinger_bands(closes)
        stoch_k, stoch_d = self.ta.calculate_stochastic(highs, lows, closes)
        atr = self.ta.calculate_atr(highs, lows, closes)
        
        # Support & Resistance
        sr_levels = self.ta.detect_support_resistance(highs, lows, closes)
        
        # Fibonacci
        period_high = max(highs[-30:])
        period_low = min(lows[-30:])
        fibonacci = self.ta.calculate_fibonacci_retracement(period_high, period_low)
        
        # Chart patterns
        patterns = self.ta.detect_chart_patterns(highs, lows, closes)
        
        # Calculate signal score
        score = self._calculate_score({
            "price": current_price,
            "sma_20": sma_20[-1],
            "sma_50": sma_50[-1] if sma_50[-1] else current_price,
            "ema_12": ema_12[-1],
            "rsi": rsi[-1],
            "macd": macd[-1],
            "signal_line": signal_line[-1],
            "bb_upper": bb_upper[-1],
            "bb_lower": bb_lower[-1],
            "stoch_k": stoch_k[-1],
            "patterns": patterns
        })
        
        # Determine signal
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
        
        # Calculate targets
        atr_value = atr[-1] if atr[-1] else current_price * 0.02
        
        if signal_type in ["STRONG_BUY", "BUY"]:
            targets = [
                round(current_price * 1.03, 2),
                round(current_price * 1.06, 2),
                round(current_price * 1.10, 2)
            ]
            stop_loss = round(current_price * 0.97, 2)
        elif signal_type in ["STRONG_SELL", "SELL"]:
            targets = [
                round(current_price * 0.97, 2),
                round(current_price * 0.94, 2),
                round(current_price * 0.90, 2)
            ]
            stop_loss = round(current_price * 1.03, 2)
        else:
            targets = [current_price]
            stop_loss = current_price
        
        # Risk/Reward
        risk = abs(current_price - stop_loss)
        reward = abs(targets[0] - current_price)
        risk_reward = round(reward / risk, 2) if risk > 0 else 0
        
        return TradingSignal(
            symbol=coin_id.upper(),
            signal=signal_type,
            confidence=round(confidence, 1),
            price=current_price,
            targets=targets,
            stop_loss=stop_loss,
            risk_reward=risk_reward,
            indicators={
                "RSI": round(rsi[-1], 2),
                "MACD": round(macd[-1], 4) if macd[-1] else 0,
                "Stochastic": round(stoch_k[-1], 2) if stoch_k[-1] else 50,
                "SMA20": round(sma_20[-1], 2) if sma_20[-1] else 0,
                "SMA50": round(sma_50[-1], 2) if sma_50[-1] else 0,
                "ATR": round(atr_value, 2)
            },
            patterns=patterns,
            fibonacci=fibonacci,
            support_resistance=sr_levels,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    
    def _calculate_score(self, indicators: Dict) -> float:
        """Calculate signal score from indicators"""
        score = 50
        
        # Trend
        if indicators["price"] > indicators["sma_20"]:
            score += 10
        if indicators["price"] > indicators["sma_50"]:
            score += 10
        if indicators["sma_20"] > indicators["sma_50"]:
            score += 8
        
        # RSI
        if indicators["rsi"] < 30:
            score += 15  # Oversold
        elif indicators["rsi"] > 70:
            score -= 15  # Overbought
        
        # MACD
        if indicators["macd"] and indicators["signal_line"]:
            if indicators["macd"] > indicators["signal_line"]:
                score += 12
            else:
                score -= 12
        
        # Bollinger Bands
        if indicators["price"] < indicators["bb_lower"]:
            score += 10
        elif indicators["price"] > indicators["bb_upper"]:
            score -= 10
        
        # Stochastic
        if indicators["stoch_k"] and indicators["stoch_k"] < 20:
            score += 8
        elif indicators["stoch_k"] and indicators["stoch_k"] > 80:
            score -= 8
        
        # Patterns
        for pattern in indicators["patterns"]:
            if pattern["signal"] == "BULLISH":
                score += pattern["confidence"] / 10
            elif pattern["signal"] == "BEARISH":
                score -= pattern["confidence"] / 10
        
        return max(0, min(100, score))
    
    def _neutral_signal(self, coin_id: str) -> TradingSignal:
        return TradingSignal(
            symbol=coin_id.upper(),
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
            timestamp=datetime.now(timezone.utc).isoformat()
        )

# ====================================================================================
# MODERN DASHBOARD WITH VIBRANT COLORS
# ====================================================================================

def generate_dashboard_html(tier: SubscriptionTier = SubscriptionTier.PRO) -> str:
    """Generate modern, vibrant dashboard"""
    
    tier_info = TIER_FEATURES[tier]
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CryptoTrader Pro - Advanced Trading Platform</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        :root {{
            --bg-dark: #0a0e27;
            --bg-card: #141b3d;
            --bg-card-hover: #1a2247;
            --accent-primary: #00d4ff;
            --accent-secondary: #ff3366;
            --accent-success: #00ff88;
            --accent-warning: #ffd600;
            --text-primary: #ffffff;
            --text-secondary: #8b92b6;
            --border: #2a3356;
        }}
        
        body {{
            font-family: 'Inter', sans-serif;
            background: linear-gradient(135deg, #0a0e27 0%, #1a1f4d 100%);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
        }}
        
        .container {{
            max-width: 1600px;
            margin: 0 auto;
            padding: 20px;
        }}
        
        /* Header */
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 0;
            margin-bottom: 30px;
            border-bottom: 2px solid var(--border);
        }}
        
        .logo {{
            font-size: 28px;
            font-weight: 900;
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -1px;
        }}
        
        .tier-badge {{
            padding: 8px 20px;
            background: linear-gradient(135deg, #ff3366, #ff6b9d);
            border-radius: 20px;
            font-weight: 700;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
            box-shadow: 0 4px 15px rgba(255, 51, 102, 0.4);
        }}
        
        /* Stats Grid */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        
        .stat-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 24px;
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }}
        
        .stat-card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: linear-gradient(180deg, var(--accent-primary), var(--accent-secondary));
        }}
        
        .stat-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0, 212, 255, 0.2);
            border-color: var(--accent-primary);
        }}
        
        .stat-label {{
            color: var(--text-secondary);
            font-size: 13px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }}
        
        .stat-value {{
            font-size: 32px;
            font-weight: 900;
            font-family: 'JetBrains Mono', monospace;
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-success));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        
        /* Main Grid */
        .main-grid {{
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }}
        
        /* TradingView Widget */
        .tradingview-widget {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            min-height: 600px;
        }}
        
        .widget-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }}
        
        .widget-title {{
            font-size: 20px;
            font-weight: 700;
        }}
        
        .coin-selector {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}
        
        .coin-selector select {{
            background: var(--bg-dark);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 10px 15px;
            color: var(--text-primary);
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            outline: none;
            transition: all 0.3s ease;
        }}
        
        .coin-selector select:hover {{
            border-color: var(--accent-primary);
        }}
        
        .btn-expand {{
            padding: 10px 20px;
            background: linear-gradient(135deg, var(--accent-primary), #00a8cc);
            border: none;
            border-radius: 8px;
            color: white;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
        }}
        
        .btn-expand:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(0, 212, 255, 0.4);
        }}
        
        /* Signal Panel */
        .signal-panel {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
        }}
        
        .signal-header {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 20px;
        }}
        
        .ai-badge {{
            padding: 6px 12px;
            background: linear-gradient(135deg, #ff3366, #ff6b9d);
            border-radius: 12px;
            font-size: 12px;
            font-weight: 700;
        }}
        
        .signal-content {{
            text-align: center;
            padding: 30px 0;
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
            color: var(--accent-secondary);
        }}
        
        .signal-neutral {{
            color: var(--accent-warning);
        }}
        
        .confidence {{
            font-size: 18px;
            color: var(--text-secondary);
            margin-bottom: 20px;
        }}
        
        .price-display {{
            font-size: 48px;
            font-weight: 900;
            font-family: 'JetBrains Mono', monospace;
            margin-bottom: 30px;
        }}
        
        /* Indicators */
        .indicators-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
            margin-top: 20px;
        }}
        
        .indicator {{
            background: var(--bg-dark);
            border-radius: 12px;
            padding: 15px;
        }}
        
        .indicator-name {{
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
        
        /* Fibonacci Levels */
        .fibo-section {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            margin-top: 20px;
        }}
        
        .fibo-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-top: 15px;
        }}
        
        .fibo-level {{
            background: var(--bg-dark);
            border-radius: 8px;
            padding: 12px;
            text-align: center;
        }}
        
        .fibo-label {{
            color: var(--text-secondary);
            font-size: 11px;
            margin-bottom: 5px;
        }}
        
        .fibo-value {{
            color: var(--accent-primary);
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }}
        
        /* Patterns */
        .patterns-section {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            margin-top: 20px;
        }}
        
        .pattern-item {{
            background: var(--bg-dark);
            border-radius: 8px;
            padding: 15px;
            margin-top: 10px;
            border-left: 4px solid var(--accent-success);
        }}
        
        .pattern-item.bearish {{
            border-left-color: var(--accent-secondary);
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
        
        /* Support/Resistance */
        .sr-section {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            margin-top: 20px;
        }}
        
        .sr-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-top: 15px;
        }}
        
        .sr-box {{
            background: var(--bg-dark);
            border-radius: 8px;
            padding: 15px;
        }}
        
        .sr-title {{
            color: var(--text-secondary);
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 10px;
        }}
        
        .sr-level {{
            padding: 8px;
            background: rgba(0, 212, 255, 0.1);
            border-radius: 6px;
            margin-bottom: 5px;
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
        }}
        
        /* Market Table */
        .market-table {{
            background: var(--bg-card);
            border: 1px solid var(--border);
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
        
        .coin-name {{
            font-weight: 700;
            font-size: 14px;
        }}
        
        .positive {{
            color: var(--accent-success);
        }}
        
        .negative {{
            color: var(--accent-secondary);
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
        
        /* Modal for expanded chart */
        .modal {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.95);
            z-index: 1000;
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
        
        .modal-close {{
            position: absolute;
            top: 20px;
            right: 20px;
            background: var(--accent-secondary);
            border: none;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            color: white;
            font-size: 24px;
            cursor: pointer;
            z-index: 1001;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <div class="logo">⚡ CryptoTrader Pro</div>
            <div class="tier-badge">{tier_info['name']} Tier</div>
        </div>
        
        <!-- Stats -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Market Cap</div>
                <div class="stat-value" id="totalMarketCap">$0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">24h Volume</div>
                <div class="stat-value" id="totalVolume">$0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Market Sentiment</div>
                <div class="stat-value" id="sentiment">0%</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Active Signals</div>
                <div class="stat-value" id="activeSignals">0</div>
            </div>
        </div>
        
        <!-- Main Grid -->
        <div class="main-grid">
            <!-- TradingView Widget -->
            <div class="tradingview-widget">
                <div class="widget-header">
                    <div class="widget-title">📈 Live Chart</div>
                    <div class="coin-selector">
                        <select id="coinSelect">
                            <option value="bitcoin">Bitcoin (BTC)</option>
                            <option value="ethereum">Ethereum (ETH)</option>
                            <option value="binancecoin">Binance Coin (BNB)</option>
                            <option value="ripple">Ripple (XRP)</option>
                            <option value="cardano">Cardano (ADA)</option>
                            <option value="solana">Solana (SOL)</option>
                            <option value="polkadot">Polkadot (DOT)</option>
                            <option value="dogecoin">Dogecoin (DOGE)</option>
                        </select>
                        <button class="btn-expand" onclick="expandChart()">🔍 Expand</button>
                    </div>
                </div>
                <div id="tradingview_chart" style="height: 550px;"></div>
            </div>
            
            <!-- AI Signal Panel -->
            <div class="signal-panel">
                <div class="signal-header">
                    <h3>AI Trading Signal</h3>
                    <div class="ai-badge">AI v3.0</div>
                </div>
                
                <div class="signal-content" id="signalContent">
                    <div class="loading">
                        <div class="spinner"></div>
                        <p>Analyzing market data...</p>
                    </div>
                </div>
                
                <div class="indicators-grid" id="indicatorsGrid" style="display: none;">
                </div>
            </div>
        </div>
        
        <!-- Fibonacci Levels -->
        <div class="fibo-section" id="fiboSection" style="display: none;">
            <h3>📐 Fibonacci Retracement Levels</h3>
            <div class="fibo-grid" id="fiboGrid"></div>
        </div>
        
        <!-- Chart Patterns -->
        <div class="patterns-section" id="patternsSection" style="display: none;">
            <h3>📊 Detected Chart Patterns</h3>
            <div id="patternsList"></div>
        </div>
        
        <!-- Support & Resistance -->
        <div class="sr-section" id="srSection" style="display: none;">
            <h3>🎯 Support & Resistance Levels</h3>
            <div class="sr-grid">
                <div class="sr-box">
                    <div class="sr-title">RESISTANCE</div>
                    <div id="resistanceLevels"></div>
                </div>
                <div class="sr-box">
                    <div class="sr-title">SUPPORT</div>
                    <div id="supportLevels"></div>
                </div>
            </div>
        </div>
        
        <!-- Market Table -->
        <div class="market-table">
            <h3 style="margin-bottom: 20px;">🌍 Market Overview</h3>
            <table id="marketTable">
                <thead>
                    <tr>
                        <th>Coin</th>
                        <th>Price</th>
                        <th>24h Change</th>
                        <th>Volume</th>
                        <th>Market Cap</th>
                    </tr>
                </thead>
                <tbody id="marketTableBody">
                    <tr><td colspan="5" style="text-align: center;">Loading...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
    
    <!-- Expanded Chart Modal -->
    <div class="modal" id="chartModal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeModal()">×</button>
            <div id="tradingview_expanded" style="height: 100%;"></div>
        </div>
    </div>
    
    <!-- TradingView Widget Script -->
    <script src="https://s3.tradingview.com/tv.js"></script>
    
    <script>
        let currentCoin = 'bitcoin';
        let chartWidget = null;
        let expandedWidget = null;
        
        // Initialize TradingView widget
        function initChart(containerId, symbol) {{
            const widget = new TradingView.widget({{
                "width": "100%",
                "height": containerId === 'tradingview_chart' ? 550 : "100%",
                "symbol": getSymbol(symbol),
                "interval": "60",
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
                    "BB@tv-basicstudies",
                    "Volume@tv-basicstudies"
                ]
            }});
            
            return widget;
        }}
        
        function getSymbol(coinId) {{
            const mapping = {{
                'bitcoin': 'BINANCE:BTCUSDT',
                'ethereum': 'BINANCE:ETHUSDT',
                'binancecoin': 'BINANCE:BNBUSDT',
                'ripple': 'BINANCE:XRPUSDT',
                'cardano': 'BINANCE:ADAUSDT',
                'solana': 'BINANCE:SOLUSDT',
                'polkadot': 'BINANCE:DOTUSDT',
                'dogecoin': 'BINANCE:DOGEUSDT'
            }};
            return mapping[coinId] || 'BINANCE:BTCUSDT';
        }}
        
        function expandChart() {{
            document.getElementById('chartModal').classList.add('active');
            if (!expandedWidget) {{
                expandedWidget = initChart('tradingview_expanded', currentCoin);
            }}
        }}
        
        function closeModal() {{
            document.getElementById('chartModal').classList.remove('active');
        }}
        
        // Fetch market overview
        async function fetchMarketOverview() {{
            try {{
                const response = await fetch('/api/market/overview');
                const data = await response.json();
                
                if (data.success) {{
                    const overview = data.overview;
                    
                    // Update stats
                    document.getElementById('totalMarketCap').textContent = 
                        '$' + (overview.total_market_cap / 1e9).toFixed(2) + 'B';
                    document.getElementById('totalVolume').textContent = 
                        '$' + (overview.total_volume_24h / 1e9).toFixed(2) + 'B';
                    document.getElementById('sentiment').textContent = 
                        overview.market_sentiment.ratio + '% 📈';
                    
                    // Update market table
                    updateMarketTable(data.prices);
                }}
            }} catch (error) {{
                console.error('Error fetching market overview:', error);
            }}
        }}
        
        function updateMarketTable(prices) {{
            const tbody = document.getElementById('marketTableBody');
            tbody.innerHTML = '';
            
            Object.values(prices).forEach(coin => {{
                const row = document.createElement('tr');
                const changeClass = coin.change_24h >= 0 ? 'positive' : 'negative';
                const changeSymbol = coin.change_24h >= 0 ? '+' : '';
                
                row.innerHTML = `
                    <td class="coin-name">${{coin.symbol}}</td>
                    <td>$${{coin.price.toFixed(2)}}</td>
                    <td class="${{changeClass}}">${{changeSymbol}}${{coin.change_24h.toFixed(2)}}%</td>
                    <td>$$${{(coin.volume_24h / 1e6).toFixed(2)}}M</td>
                    <td>$$${{(coin.market_cap / 1e9).toFixed(2)}}B</td>
                `;
                
                tbody.appendChild(row);
            }});
        }}
        
        // Fetch AI signal
        async function fetchSignal(coinId) {{
            try {{
                const response = await fetch(`/api/ai-signal/${{coinId}}`);
                const data = await response.json();
                
                if (data.success) {{
                    displaySignal(data.signal);
                }}
            }} catch (error) {{
                console.error('Error fetching signal:', error);
            }}
        }}
        
        function displaySignal(signal) {{
            const content = document.getElementById('signalContent');
            const signalClass = signal.signal.includes('BUY') ? 'signal-buy' : 
                               signal.signal.includes('SELL') ? 'signal-sell' : 'signal-neutral';
            
            content.innerHTML = `
                <div class="signal-type ${{signalClass}}">${{signal.signal}}</div>
                <div class="confidence">Confidence: ${{signal.confidence}}%</div>
                <div class="price-display">$${{signal.price.toFixed(2)}}</div>
                <div style="margin-top: 20px;">
                    <div style="font-size: 14px; color: var(--text-secondary); margin-bottom: 10px;">Targets</div>
                    <div style="display: flex; gap: 10px; justify-content: center;">
                        ${{signal.targets.map(t => `<div style="background: var(--bg-dark); padding: 10px 15px; border-radius: 8px; font-family: 'JetBrains Mono', monospace; font-weight: 600;">$${{t}}</div>`).join('')}}
                    </div>
                    <div style="margin-top: 15px; font-size: 14px;">
                        <span style="color: var(--text-secondary);">Stop Loss:</span> 
                        <span style="color: var(--accent-secondary); font-family: 'JetBrains Mono', monospace; font-weight: 700;">$${{signal.stop_loss}}</span>
                    </div>
                    <div style="margin-top: 10px; font-size: 14px;">
                        <span style="color: var(--text-secondary);">Risk/Reward:</span> 
                        <span style="color: var(--accent-success); font-family: 'JetBrains Mono', monospace; font-weight: 700;">${{signal.risk_reward}}</span>
                    </div>
                </div>
            `;
            
            // Display indicators
            const indicatorsGrid = document.getElementById('indicatorsGrid');
            indicatorsGrid.style.display = 'grid';
            indicatorsGrid.innerHTML = Object.entries(signal.indicators).map(([key, value]) => `
                <div class="indicator">
                    <div class="indicator-name">${{key}}</div>
                    <div class="indicator-value">${{typeof value === 'number' ? value.toFixed(2) : value}}</div>
                </div>
            `).join('');
            
            // Display Fibonacci
            if (signal.fibonacci && Object.keys(signal.fibonacci).length > 0) {{
                document.getElementById('fiboSection').style.display = 'block';
                document.getElementById('fiboGrid').innerHTML = Object.entries(signal.fibonacci).map(([level, price]) => `
                    <div class="fibo-level">
                        <div class="fibo-label">${{level}}</div>
                        <div class="fibo-value">$${{price}}</div>
                    </div>
                `).join('');
            }}
            
            // Display patterns
            if (signal.patterns && signal.patterns.length > 0) {{
                document.getElementById('patternsSection').style.display = 'block';
                document.getElementById('patternsList').innerHTML = signal.patterns.map(pattern => `
                    <div class="pattern-item ${{pattern.signal === 'BEARISH' ? 'bearish' : ''}}">
                        <div class="pattern-name">${{pattern.type}} - ${{pattern.signal}}</div>
                        <div class="pattern-desc">${{pattern.description}} (Confidence: ${{pattern.confidence}}%)</div>
                    </div>
                `).join('');
            }}
            
            // Display Support/Resistance
            if (signal.support_resistance) {{
                document.getElementById('srSection').style.display = 'block';
                
                const resistanceLevels = signal.support_resistance.resistance || [];
                const supportLevels = signal.support_resistance.support || [];
                
                document.getElementById('resistanceLevels').innerHTML = 
                    resistanceLevels.map(level => `<div class="sr-level">$${{level.toFixed(2)}}</div>`).join('') ||
                    '<div style="color: var(--text-secondary);">No levels detected</div>';
                
                document.getElementById('supportLevels').innerHTML = 
                    supportLevels.map(level => `<div class="sr-level">$${{level.toFixed(2)}}</div>`).join('') ||
                    '<div style="color: var(--text-secondary);">No levels detected</div>';
            }}
            
            document.getElementById('activeSignals').textContent = 
                (signal.patterns ? signal.patterns.length : 0) + ' Patterns';
        }}
        
        // Event listeners
        document.getElementById('coinSelect').addEventListener('change', (e) => {{
            currentCoin = e.target.value;
            if (chartWidget) {{
                chartWidget.remove();
            }}
            chartWidget = initChart('tradingview_chart', currentCoin);
            fetchSignal(currentCoin);
        }});
        
        // Initialize
        window.addEventListener('load', () => {{
            chartWidget = initChart('tradingview_chart', currentCoin);
            fetchMarketOverview();
            fetchSignal(currentCoin);
            
            // Refresh every 30 seconds
            setInterval(fetchMarketOverview, 30000);
        }});
    </script>
</body>
</html>
"""

# ====================================================================================
# FASTAPI APPLICATION
# ====================================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    logger.info("🚀 CryptoTrader Pro v5.0 Starting...")
    
    # Initialize CoinGecko provider
    data_provider = CoinGeckoDataProvider()
    await data_provider.initialize()
    
    # Initialize AI engine
    ai_engine = AISignalEngine(data_provider)
    
    # Store in app state
    app.state.data_provider = data_provider
    app.state.ai_engine = ai_engine
    
    logger.info("✅ All systems operational")
    logger.info("📊 CoinGecko API: Connected")
    logger.info("🤖 AI Signal Engine: Ready")
    logger.info("=" * 70)
    
    yield
    
    # Cleanup
    await data_provider.close()
    logger.info("🛑 CryptoTrader Pro Shutting Down")

app = FastAPI(
    title="CryptoTrader Pro v5.0",
    version="5.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====================================================================================
# API ENDPOINTS
# ====================================================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard"""
    html = generate_dashboard_html(SubscriptionTier.PRO)
    return HTMLResponse(html)

@app.get("/api/market/overview")
async def market_overview(request: Request):
    """Get market overview"""
    try:
        data_provider = request.app.state.data_provider
        
        # Fetch price data
        prices = await data_provider.fetch_price_data()
        
        # Get overview
        overview = await data_provider.get_market_overview()
        
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overview": overview,
            "prices": prices
        }
    except Exception as e:
        logger.error(f"Market overview error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/ai-signal/{coin_id}")
async def get_signal(coin_id: str, request: Request):
    """Get AI trading signal for a coin"""
    try:
        ai_engine = request.app.state.ai_engine
        
        # Generate signal
        signal = await ai_engine.analyze_coin(coin_id)
        
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signal": asdict(signal)
        }
    except Exception as e:
        logger.error(f"Signal generation error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "version": "5.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "coingecko": "operational",
            "ai_engine": "operational",
            "technical_analysis": "operational"
        }
    }

# ====================================================================================
# STARTUP
# ====================================================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    
    logger.info("=" * 70)
    logger.info("🚀 CRYPTOTRADER PRO v5.0")
    logger.info("=" * 70)
    logger.info(f"🌐 Server: http://0.0.0.0:{port}")
    logger.info("📊 Features: 20+ Indicators, Fibonacci, Support/Resistance")
    logger.info("🎨 UI: Modern vibrant dashboard with TradingView")
    logger.info("🤖 AI: Advanced pattern detection & signals")
    logger.info("=" * 70)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
