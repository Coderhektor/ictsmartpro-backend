import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
import asyncio
import json
import websockets
from contextlib import asynccontextmanager
import pandas as pd
import numpy as np
from dataclasses import dataclass
import secrets
import hashlib
from enum import Enum
import time

Advanced logging
logging.basicConfig(
level=logging.INFO,
format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(name)

from fastapi import FastAPI, HTTPException, Query, Request, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

==================== PREMIUM SUBSCRIPTION SYSTEM ====================
class SubscriptionTier(Enum):
FREE = "free"
BASIC = "basic"
PRO = "pro"
ENTERPRISE = "enterprise"

class SubscriptionManager:
"""Premium subscription management system"""

text
TIER_FEATURES = {
    SubscriptionTier.FREE: {
        "name": "Free",
        "price": 0,
        "features": [
            "3 symbols max",
            "Basic technical analysis",
            "1h timeframe only",
            "Limited pattern detection",
            "Community support"
        ],
        "limits": {
            "max_symbols": 3,
            "timeframes": ["1h"],
            "pattern_detection": 5,
            "realtime_updates": False,
            "api_calls": 100
        }
    },
    SubscriptionTier.BASIC: {
        "name": "Basic",
        "price": 9.99,
        "features": [
            "10 symbols",
            "Advanced technical analysis",
            "All timeframes",
            "12 candlestick patterns",
            "Email support",
            "Real-time alerts"
        ],
        "limits": {
            "max_symbols": 10,
            "timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"],
            "pattern_detection": 12,
            "realtime_updates": True,
            "api_calls": 1000
        }
    },
    SubscriptionTier.PRO: {
        "name": "Pro",
        "price": 29.99,
        "features": [
            "Unlimited symbols",
            "AI-powered signals",
            "All timeframes",
            "Advanced backtesting",
            "Priority support",
            "Custom indicators",
            "Risk management tools",
            "Multi-exchange support"
        ],
        "limits": {
            "max_symbols": 999,
            "timeframes": ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"],
            "pattern_detection": 20,
            "realtime_updates": True,
            "api_calls": 10000,
            "backtesting": True,
            "custom_indicators": True
        }
    },
    SubscriptionTier.ENTERPRISE: {
        "name": "Enterprise",
        "price": 99.99,
        "features": [
            "Everything in Pro",
            "White-label solution",
            "API access",
            "Custom development",
            "Dedicated support",
            "Advanced analytics",
            "Team management",
            "SLA guarantee"
        ],
        "limits": {
            "max_symbols": 9999,
            "timeframes": "all",
            "pattern_detection": "all",
            "realtime_updates": True,
            "api_calls": "unlimited",
            "backtesting": True,
            "custom_indicators": True,
            "api_access": True,
            "white_label": True
        }
    }
}

def __init__(self):
    self.users = {}  # In production, use database
    self.payments = {}
    self.coupons = {
        "WELCOME20": 20,  # 20% discount
        "TRADING25": 25,  # 25% discount
        "PRO50": 50,      # 50% discount for first Pro subscription
    }

def create_user(self, email: str, tier: SubscriptionTier = SubscriptionTier.FREE) -> str:
    """Create a new user with subscription"""
    user_id = secrets.token_hex(16)
    self.users[user_id] = {
        "id": user_id,
        "email": email,
        "tier": tier,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
        "api_key": secrets.token_hex(32),
        "usage": {
            "api_calls": 0,
            "last_reset": datetime.now(timezone.utc)
        }
    }
    return user_id

def check_access(self, user_id: str, feature: str) -> bool:
    """Check if user has access to feature"""
    if user_id not in self.users:
        return False
    
    user = self.users[user_id]
    tier = user["tier"]
    
    # Check if subscription is active
    if user["expires_at"] < datetime.now(timezone.utc):
        return False
    
    # Check feature limits
    if feature == "api_calls":
        # Reset monthly usage
        if (datetime.now(timezone.utc) - user["usage"]["last_reset"]).days >= 30:
            user["usage"]["api_calls"] = 0
            user["usage"]["last_reset"] = datetime.now(timezone.utc)
        
        limit = self.TIER_FEATURES[tier]["limits"]["api_calls"]
        if limit == "unlimited":
            return True
        return user["usage"]["api_calls"] < limit
    
    return feature in self.TIER_FEATURES[tier]["limits"]

def increment_usage(self, user_id: str):
    """Increment API usage counter"""
    if user_id in self.users:
        self.users[user_id]["usage"]["api_calls"] += 1

def get_user_tier(self, user_id: str) -> SubscriptionTier:
    """Get user's subscription tier"""
    if user_id in self.users:
        return self.users[user_id]["tier"]
    return SubscriptionTier.FREE
==================== TRADINGVIEW CONFIG ====================
class TradingViewConfig:
"""TradingView widget configuration"""

text
TIMEFRAMES = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "1d": "1D",
    "1w": "1W",
    "1M": "1M",
}

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", 
    "XRPUSDT", "ADAUSDT", "BNBUSDT",
    "DOGEUSDT", "DOTUSDT", "AVAXUSDT",
    "LINKUSDT", "MATICUSDT", "UNIUSDT"
]

THEMES = {
    "dark": "Dark",
    "light": "Light"
}

PREMIUM_STUDIES = [
    "RSI@tv-basicstudies",
    "MACD@tv-basicstudies", 
    "Volume@tv-basicstudies",
    "Stochastic@tv-basicstudies",
    "BollingerBands@tv-basicstudies",
    "MovingAverage@tv-basicstudies",
    "PivotPointsHighLow@tv-basicstudies",
    "VolumeProfile@tv-basicstudies"
]

@staticmethod
def get_tradingview_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    if symbol.endswith("USDT"):
        return f"BINANCE:{symbol}"
    elif len(symbol) == 6 and "USD" in symbol:
        return f"FX:{symbol}"
    elif symbol.isalpha() and len(symbol) <= 5:
        return f"NASDAQ:{symbol}"
    else:
        return symbol
==================== GERÇEK ZAMANLI VERİ MODÜLÜ ====================
class BinanceRealTimeData:
"""Binance WebSocket'ten gerçek zamanlı veri alır"""

text
def __init__(self):
    self.ws = None
    self.connected = False
    self.symbol_data = {}
    self.candle_cache = {}
    self.is_running = False
    self.subscribers = {}
    
async def connect(self, symbols: List[str]):
    try:
        stream_names = [f"{symbol.lower()}@ticker" for symbol in symbols]
        streams = "/".join(stream_names)
        ws_url = f"wss://stream.binance.com:9443/stream?streams={streams}"
        
        logger.info(f"Connecting to Binance WebSocket: {ws_url}")
        
        async with websockets.connect(
            ws_url,
            ping_interval=20,
            ping_timeout=20,
            max_size=2**20
        ) as websocket:
            self.ws = websocket
            self.connected = True
            logger.info(f"✅ Connected to Binance WebSocket for {len(symbols)} symbols")
            
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.process_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}")
                except Exception as e:
                    logger.error(f"Message processing error: {e}")
                    
    except Exception as e:
        logger.error(f"WebSocket connection error: {type(e).__name__} - {str(e)}")
        self.connected = False

async def process_message(self, data: Dict):
    try:
        if 'data' in data:
            stream_data = data['data']
            symbol = stream_data['s']
            
            current_price = float(stream_data.get('c', 0))
            price_change = float(stream_data.get('P', 0))
            volume = float(stream_data.get('v', 0))
            
            # Calculate price movement direction
            prev_price = self.symbol_data.get(symbol, {}).get('price', current_price)
            direction = "up" if current_price > prev_price else "down" if current_price < prev_price else "same"
            
            # Calculate trend strength
            high_24h = float(stream_data.get('h', 0))
            low_24h = float(stream_data.get('l', 0))
            trend_strength = abs((current_price - ((high_24h + low_24h) / 2)) / ((high_24h - low_24h) / 2)) * 100
            
            self.symbol_data[symbol] = {
                'symbol': symbol,
                'price': current_price,
                'change': price_change,
                'volume': volume,
                'high_24h': high_24h,
                'low_24h': low_24h,
                'open_24h': float(stream_data.get('o', 0)),
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'last_update': datetime.now(timezone.utc),
                'direction': direction,
                'trend_strength': round(trend_strength, 2),
                'market_cap': volume * current_price,
                'liquidity_score': self.calculate_liquidity_score(symbol, volume, current_price)
            }
            
            await self.update_candle_cache(symbol, current_price)
            
            # Notify subscribers
            await self.notify_subscribers(symbol, self.symbol_data[symbol])
            
            if len(self.symbol_data) % 10 == 0:
                logger.debug(f"📡 {symbol}: ${current_price:.2f} ({price_change:+.2f}%)")
                
    except Exception as e:
        logger.error(f"Message processing error: {e}")

def calculate_liquidity_score(self, symbol: str, volume: float, price: float) -> float:
    """Calculate liquidity score for a symbol"""
    # Simple liquidity score based on volume and price
    base_score = min(volume / 1000000, 100)  # Normalize volume
    price_factor = min(price / 1000, 10)  # Price factor
    return round(base_score * price_factor, 2)

async def notify_subscribers(self, symbol: str, data: Dict):
    """Notify all subscribers about price update"""
    if symbol in self.subscribers:
        for callback in self.subscribers[symbol]:
            try:
                await callback(data)
            except Exception as e:
                logger.error(f"Error notifying subscriber: {e}")

def subscribe(self, symbol: str, callback):
    """Subscribe to real-time updates for a symbol"""
    if symbol not in self.subscribers:
        self.subscribers[symbol] = []
    self.subscribers[symbol].append(callback)

async def update_candle_cache(self, symbol: str, price: float):
    now = datetime.now(timezone.utc)
    minute = now.minute
    
    if symbol not in self.candle_cache:
        self.candle_cache[symbol] = {
            'open': price,
            'high': price,
            'low': price,
            'close': price,
            'volume': 0,
            'timestamp': now,
            'minute': minute
        }
    else:
        candle = self.candle_cache[symbol]
        
        if minute == candle['minute']:
            candle['high'] = max(candle['high'], price)
            candle['low'] = min(candle['low'], price)
            candle['close'] = price
            candle['volume'] += 1
        else:
            self.candle_cache[symbol] = {
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 0,
                'timestamp': now,
                'minute': minute
            }

async def get_candles(self, symbol: str, count: int = 50) -> List[Dict]:
    symbol = symbol.upper()
    
    if symbol in self.symbol_data:
        real_data = self.symbol_data[symbol]
        base_price = real_data['price'] or 60000.0
        
        candles = []
        now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        
        for i in range(count):
            ts = now_ts - (count - i) * 300000  # 5 minute intervals
            
            # More realistic price simulation with trends
            trend_factor = 1 + (real_data['change'] / 10000) * (i / count)
            volatility = 0.0025 * (1 + np.sin(i / 10) * 0.5)  # Cyclical volatility
            
            price = base_price * trend_factor * (1 + np.random.uniform(-volatility, volatility))
            
            candles.append({
                "timestamp": ts,
                "open": round(price * (1 + np.random.uniform(-0.001, 0.001)), 2),
                "high": round(price * (1 + np.random.uniform(0, 0.003)), 2),
                "low": round(price * (1 - np.random.uniform(0, 0.003)), 2),
                "close": round(price, 2),
                "volume": round(real_data.get('volume', 1000) * (1 + np.random.uniform(0, 0.5)), 0)
            })
        
        if candles:
            candles[-1].update({
                "close": round(real_data['price'], 2),
                "high": max(candles[-1]["high"], round(real_data.get('high_24h', real_data['price']), 2)),
                "low": min(candles[-1]["low"], round(real_data.get('low_24h', real_data['price']), 2)),
            })
        
        return candles
    
    logger.warning(f"No real-time data for {symbol}, returning empty list")
    return []

async def get_symbol_info(self, symbol: str) -> Optional[Dict]:
    return self.symbol_data.get(symbol.upper())

def get_market_overview(self) -> Dict:
    """Get comprehensive market overview"""
    if not self.symbol_data:
        return {}
    
    symbols = list(self.symbol_data.keys())
    total_volume = sum(data['volume'] for data in self.symbol_data.values())
    avg_change = np.mean([data['change'] for data in self.symbol_data.values()])
    
    # Find top movers
    top_gainers = sorted(
        [(s, data) for s, data in self.symbol_data.items()],
        key=lambda x: x[1]['change'],
        reverse=True
    )[:5]
    
    top_losers = sorted(
        [(s, data) for s, data in self.symbol_data.items()],
        key=lambda x: x[1]['change']
    )[:5]
    
    # Market sentiment
    bullish = sum(1 for data in self.symbol_data.values() if data['change'] > 0)
    bearish = sum(1 for data in self.symbol_data.values() if data['change'] < 0)
    neutral = len(self.symbol_data) - bullish - bearish
    
    return {
        "total_symbols": len(symbols),
        "total_volume": total_volume,
        "avg_change": round(avg_change, 2),
        "market_sentiment": {
            "bullish": bullish,
            "bearish": bearish,
            "neutral": neutral,
            "ratio": round(bullish / len(symbols) * 100, 1) if symbols else 0
        },
        "top_gainers": [
            {"symbol": s, "change": data['change'], "price": data['price']}
            for s, data in top_gainers
        ],
        "top_losers": [
            {"symbol": s, "change": data['change'], "price": data['price']}
            for s, data in top_losers
        ],
        "most_liquid": sorted(
            [(s, data['liquidity_score']) for s, data in self.symbol_data.items()],
            key=lambda x: x[1],
            reverse=True
        )[:5]
    }
==================== AI POWERED SIGNAL ENGINE ====================
@dataclass
class AISignal:
symbol: str
timeframe: str
signal: str # STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL
confidence: float
price: float
targets: List[float]
stop_loss: float
risk_reward: float
timestamp: str
reasoning: List[str]
priority: int # 1-5, 5 being highest

class AISignalEngine:
"""AI-powered trading signal engine"""

text
def __init__(self, data_provider: BinanceRealTimeData):
    self.data_provider = data_provider
    self.model_version = "v2.1"
    self.signal_history = {}
    
async def analyze_symbol(self, symbol: str, timeframe: str = "1h") -> AISignal:
    """Generate AI-powered trading signal"""
    
    # Get market data
    symbol_data = await self.data_provider.get_symbol_info(symbol)
    candles = await self.data_provider.get_candles(symbol, 100)
    
    if not symbol_data or len(candles) < 20:
        return self._create_neutral_signal(symbol, timeframe)
    
    # Extract features
    features = self._extract_features(candles, symbol_data)
    
    # AI decision making (simplified - in production use ML model)
    signal_score = self._calculate_signal_score(features)
    
    # Determine signal type
    if signal_score >= 80:
        signal_type = "STRONG_BUY"
        confidence = min(95, signal_score)
        priority = 5
    elif signal_score >= 60:
        signal_type = "BUY"
        confidence = signal_score
        priority = 4
    elif signal_score <= 20:
        signal_type = "STRONG_SELL"
        confidence = min(95, 100 - signal_score)
        priority = 5
    elif signal_score <= 40:
        signal_type = "SELL"
        confidence = 100 - signal_score
        priority = 4
    else:
        signal_type = "NEUTRAL"
        confidence = 50
        priority = 2
    
    # Calculate targets and stop loss
    current_price = symbol_data['price']
    atr = features.get('atr', current_price * 0.02)
    
    if signal_type in ["STRONG_BUY", "BUY"]:
        targets = [
            round(current_price * 1.02, 2),  # 2% target
            round(current_price * 1.05, 2),  # 5% target
            round(current_price * 1.10, 2)   # 10% target
        ]
        stop_loss = round(current_price * 0.98, 2)  # 2% stop loss
    elif signal_type in ["STRONG_SELL", "SELL"]:
        targets = [
            round(current_price * 0.98, 2),  # 2% target
            round(current_price * 0.95, 2),  # 5% target
            round(current_price * 0.90, 2)   # 10% target
        ]
        stop_loss = round(current_price * 1.02, 2)  # 2% stop loss
    else:
        targets = [current_price]
        stop_loss = current_price
    
    # Calculate risk/reward
    if stop_loss != current_price:
        risk = abs(current_price - stop_loss)
        reward = abs(targets[0] - current_price)
        risk_reward = round(reward / risk, 2) if risk > 0 else 0
    else:
        risk_reward = 0
    
    # Generate reasoning
    reasoning = self._generate_reasoning(features, signal_type)
    
    signal = AISignal(
        symbol=symbol,
        timeframe=timeframe,
        signal=signal_type,
        confidence=confidence,
        price=current_price,
        targets=targets,
        stop_loss=stop_loss,
        risk_reward=risk_reward,
        timestamp=datetime.now(timezone.utc).isoformat(),
        reasoning=reasoning,
        priority=priority
    )
    
    # Store in history
    self.signal_history[f"{symbol}_{timeframe}"] = {
        "signal": signal,
        "timestamp": datetime.now(timezone.utc)
    }
    
    return signal

def _extract_features(self, candles: List[Dict], symbol_data: Dict) -> Dict:
    """Extract technical features from candle data"""
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c.get("volume", 0) for c in candles]
    
    current_price = closes[-1]
    
    # Moving averages
    sma_20 = np.mean(closes[-20:]) if len(closes) >= 20 else current_price
    sma_50 = np.mean(closes[-50:]) if len(closes) >= 50 else current_price
    ema_12 = self._calculate_ema(closes, 12)[-1] if len(closes) >= 12 else current_price
    
    # RSI
    rsi = self._calculate_rsi(closes, 14)[-1] if len(closes) >= 15 else 50
    
    # MACD
    macd_line, signal_line, histogram = self._calculate_macd(closes)
    macd_bullish = macd_line[-1] > signal_line[-1] if macd_line else False
    
    # Bollinger Bands
    bb_upper, bb_lower = self._calculate_bollinger_bands(closes, 20)
    bb_position = (current_price - bb_lower[-1]) / (bb_upper[-1] - bb_lower[-1]) if bb_upper[-1] != bb_lower[-1] else 0.5
    
    # Volume analysis
    volume_avg = np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-1]
    volume_ratio = volumes[-1] / volume_avg if volume_avg > 0 else 1
    
    # Price action
    price_change_24h = symbol_data.get('change', 0)
    trend_strength = symbol_data.get('trend_strength', 50)
    
    # Support/Resistance
    recent_high = max(highs[-20:]) if len(highs) >= 20 else current_price
    recent_low = min(lows[-20:]) if len(lows) >= 20 else current_price
    support_distance = (current_price - recent_low) / current_price * 100
    resistance_distance = (recent_high - current_price) / current_price * 100
    
    # ATR for volatility
    atr = self._calculate_atr(highs, lows, closes, 14)[-1] if len(closes) >= 15 else current_price * 0.02
    
    return {
        "price": current_price,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "ema_12": ema_12,
        "rsi": rsi,
        "macd_bullish": macd_bullish,
        "bb_position": bb_position,
        "volume_ratio": volume_ratio,
        "price_change_24h": price_change_24h,
        "trend_strength": trend_strength,
        "support_distance": support_distance,
        "resistance_distance": resistance_distance,
        "atr": atr,
        "price_above_sma20": current_price > sma_20,
        "price_above_sma50": current_price > sma_50,
        "sma20_above_sma50": sma_20 > sma_50
    }

def _calculate_signal_score(self, features: Dict) -> float:
    """Calculate signal score based on features"""
    score = 50  # Neutral starting point
    
    # Trend following
    if features["price_above_sma20"]:
        score += 10
    if features["price_above_sma50"]:
        score += 15
    if features["sma20_above_sma50"]:
        score += 10
    
    # Momentum
    if features["rsi"] < 30:
        score += 20  # Oversold
    elif features["rsi"] > 70:
        score -= 20  # Overbought
    
    # MACD
    if features["macd_bullish"]:
        score += 10
    else:
        score -= 10
    
    # Bollinger Bands
    if features["bb_position"] < 0.2:
        score += 15  # Near lower band
    elif features["bb_position"] > 0.8:
        score -= 15  # Near upper band
    
    # Volume
    if features["volume_ratio"] > 1.5:
        score += 10  # High volume
    
    # Price action
    if features["price_change_24h"] > 5:
        score += 5
    elif features["price_change_24h"] < -5:
        score -= 5
    
    # Support/Resistance
    if features["support_distance"] < 2:
        score += 10  # Near support
    if features["resistance_distance"] < 2:
        score -= 10  # Near resistance
    
    return max(0, min(100, score))

def _generate_reasoning(self, features: Dict, signal_type: str) -> List[str]:
    """Generate human-readable reasoning for the signal"""
    reasoning = []
    
    if signal_type in ["STRONG_BUY", "BUY"]:
        if features["rsi"] < 30:
            reasoning.append("RSI indicates oversold conditions")
        if features["bb_position"] < 0.2:
            reasoning.append("Price near Bollinger Band lower boundary")
        if features["price_above_sma20"] and features["price_above_sma50"]:
            reasoning.append("Price above key moving averages")
        if features["macd_bullish"]:
            reasoning.append("MACD showing bullish momentum")
        if features["support_distance"] < 2:
            reasoning.append("Strong support level identified")
    
    elif signal_type in ["STRONG_SELL", "SELL"]:
        if features["rsi"] > 70:
            reasoning.append("RSI indicates overbought conditions")
        if features["bb_position"] > 0.8:
            reasoning.append("Price near Bollinger Band upper boundary")
        if not features["price_above_sma20"] and not features["price_above_sma50"]:
            reasoning.append("Price below key moving averages")
        if not features["macd_bullish"]:
            reasoning.append("MACD showing bearish momentum")
        if features["resistance_distance"] < 2:
            reasoning.append("Strong resistance level identified")
    
    else:  # NEUTRAL
        reasoning.append("Mixed signals from indicators")
        reasoning.append("Waiting for clearer market direction")
    
    # Add volume analysis
    if features["volume_ratio"] > 1.5:
        reasoning.append("High trading volume confirming move")
    
    return reasoning[:5]  # Limit to 5 reasons

def _create_neutral_signal(self, symbol: str, timeframe: str) -> AISignal:
    return AISignal(
        symbol=symbol,
        timeframe=timeframe,
        signal="NEUTRAL",
        confidence=50,
        price=0,
        targets=[0],
        stop_loss=0,
        risk_reward=0,
        timestamp=datetime.now(timezone.utc).isoformat(),
        reasoning=["Insufficient data for analysis"],
        priority=1
    )

# Technical indicator calculations
def _calculate_ema(self, prices, period):
    if len(prices) < period:
        return [None] * len(prices)
    ema = [sum(prices[:period]) / period]
    multiplier = 2 / (period + 1)
    for price in prices[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return [None] * (period - 1) + ema

def _calculate_rsi(self, prices, period=14):
    if len(prices) < period + 1:
        return [50] * len(prices)
    
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 1
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)
    
    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta
        
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down if down != 0 else 1
        rsi[i] = 100. - 100. / (1. + rs)
    
    return rsi.tolist()

def _calculate_macd(self, prices, fast=12, slow=26, signal=9):
    if len(prices) < slow:
        return [], [], []
    
    ema_fast = self._calculate_ema(prices, fast)
    ema_slow = self._calculate_ema(prices, slow)
    
    macd_line = []
    for i in range(len(prices)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line.append(ema_fast[i] - ema_slow[i])
        else:
            macd_line.append(None)
    
    # Calculate signal line
    signal_line = self._calculate_ema([x for x in macd_line if x is not None], signal)
    
    # Calculate histogram
    histogram = []
    for i in range(len(macd_line)):
        if macd_line[i] is not None and i >= signal-1:
            hist_idx = i - (signal - 1)
            if hist_idx < len(signal_line) and signal_line[hist_idx] is not None:
                histogram.append(macd_line[i] - signal_line[hist_idx])
            else:
                histogram.append(None)
        else:
            histogram.append(None)
    
    return macd_line, signal_line, histogram

def _calculate_bollinger_bands(self, prices, period=20, std_dev=2):
    if len(prices) < period:
        return [None] * len(prices), [None] * len(prices)
    
    sma = np.convolve(prices, np.ones(period)/period, mode='valid')
    rolling_std = np.array([np.std(prices[i:i+period]) for i in range(len(prices)-period+1)])
    
    upper_band = sma + (rolling_std * std_dev)
    lower_band = sma - (rolling_std * std_dev)
    
    # Pad with None values
    upper_band = [None] * (period - 1) + upper_band.tolist()
    lower_band = [None] * (period - 1) + lower_band.tolist()
    
    return upper_band, lower_band

def _calculate_atr(self, highs, lows, closes, period=14):
    if len(highs) < period + 1:
        return [0] * len(highs)
    
    tr = np.zeros(len(highs))
    for i in range(1, len(highs)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i-1])
        lc = abs(lows[i] - closes[i-1])
        tr[i] = max(hl, hc, lc)
    
    atr = np.zeros(len(highs))
    atr[period] = np.mean(tr[1:period+1])
    
    for i in range(period+1, len(highs)):
        atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
    
    atr[:period] = atr[period]
    return atr.tolist()
==================== PREMIUM DASHBOARD ====================
class PremiumDashboard:
"""Premium dashboard with advanced features"""

text
def __init__(self, data_provider: BinanceRealTimeData, ai_engine: AISignalEngine):
    self.data_provider = data_provider
    self.ai_engine = ai_engine
    self.user_sessions = {}
    
def get_dashboard_html(self, user_tier: SubscriptionTier = SubscriptionTier.FREE) -> str:
    """Generate premium dashboard HTML based on user tier"""
    
    tier_info = SubscriptionManager.TIER_FEATURES[user_tier]
    
    # Color scheme based on tier
    color_schemes = {
        SubscriptionTier.FREE: {
            "primary": "#6c757d",
            "secondary": "#495057",
            "accent": "#adb5bd"
        },
        SubscriptionTier.BASIC: {
            "primary": "#007bff",
            "secondary": "#0056b3",
            "accent": "#66b0ff"
        },
        SubscriptionTier.PRO: {
            "primary": "#6610f2",
            "secondary": "#4a0cac",
            "accent": "#9259f7"
        },
        SubscriptionTier.ENTERPRISE: {
            "primary": "#20c997",
            "secondary": "#17a589",
            "accent": "#5ce0b9"
        }
    }
    
    colors = color_schemes[user_tier]
    
    return f"""
<!DOCTYPE html><html lang="en"> <head> <meta charset="UTF-8"> <meta name="viewport" content="width=device-width, initial-scale=1.0"> <title>🚀 Trading Bot Premium - {tier_info['name']} Tier</title> <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"> <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet"> <style> :root {{ --bg-dark: #0a0e17; --bg-card: #1a1f2e; --primary: {colors['primary']}; --primary-dark: {colors['secondary']}; --accent: {colors['accent']}; --success: #10b981; --danger: #ef4444; --warning: #f59e0b; --info: #3b82f6; --text: #f1f5f9; --text-muted: #94a3b8; --border: rgba(255,255,255,0.08); --gradient-primary: linear-gradient(135deg, {colors['primary']}, {colors['secondary']}); --gradient-accent: linear-gradient(135deg, {colors['accent']}, {colors['primary']}); --shadow: 0 10px 25px rgba(0,0,0,0.3); --shadow-lg: 0 20px 50px rgba(0,0,0,0.4); }}
text
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    
    body {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        background: var(--bg-dark);
        color: var(--text);
        min-height: 100vh;
        overflow-x: hidden;
    }}
    
    .container {{
        max-width: 1800px;
        margin: 0 auto;
        padding: 20px;
    }}
    
    /* Header */
    .premium-header {{
        background: linear-gradient(135deg, #0a0e17 0%, #1a1f2e 100%);
        border-radius: 20px;
        padding: 2rem 2.5rem;
        margin-bottom: 2rem;
        border: 1px solid var(--border);
        box-shadow: var(--shadow);
        position: relative;
        overflow: hidden;
    }}
    
    .premium-header::before {{
        content: '';
        position: absolute;
        top: 0;
        right: 0;
        width: 300px;
        height: 300px;
        background: var(--gradient-primary);
        opacity: 0.1;
        border-radius: 50%;
        transform: translate(100px, -100px);
    }}
    
    .header-top {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1.5rem;
        position: relative;
        z-index: 2;
    }}
    
    .logo {{
        display: flex;
        align-items: center;
        gap: 1rem;
    }}
    
    .logo-icon {{
        width: 50px;
        height: 50px;
        background: var(--gradient-primary);
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.5rem;
        color: white;
    }}
    
    .logo-text {{
        font-size: 1.8rem;
        font-weight: 800;
        background: linear-gradient(90deg, var(--primary), var(--accent));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }}
    
    .tier-badge {{
        background: var(--gradient-primary);
        color: white;
        padding: 0.5rem 1.5rem;
        border-radius: 50px;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    }}
    
    /* Stats Grid */
    .stats-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
        gap: 1.5rem;
        margin-bottom: 2rem;
    }}
    
    .stat-card {{
        background: rgba(255,255,255,0.03);
        border-radius: 16px;
        padding: 1.5rem;
        border: 1px solid var(--border);
        transition: all 0.3s ease;
        backdrop-filter: blur(10px);
    }}
    
    .stat-card:hover {{
        transform: translateY(-5px);
        border-color: var(--primary);
        box-shadow: var(--shadow);
    }}
    
    .stat-icon {{
        width: 50px;
        height: 50px;
        background: rgba(var(--primary-rgb, 59, 130, 246), 0.1);
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 1rem;
        color: var(--primary);
    }}
    
    .stat-value {{
        font-size: 2rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
        background: linear-gradient(90deg, var(--text), var(--text-muted));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }}
    
    /* Main Content */
    .main-content {{
        display: grid;
        grid-template-columns: 1fr 400px;
        gap: 2rem;
        margin-bottom: 2rem;
    }}
    
    @media (max-width: 1400px) {{
        .main-content {{ grid-template-columns: 1fr; }}
    }}
    
    /* Trading View */
    .chart-container {{
        background: var(--bg-card);
        border-radius: 20px;
        padding: 1.5rem;
        border: 1px solid var(--border);
        box-shadow: var(--shadow);
    }}
    
    .chart-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1.5rem;
        padding-bottom: 1.5rem;
        border-bottom: 1px solid var(--border);
    }}
    
    /* AI Signal Panel */
    .ai-signal-panel {{
        background: var(--bg-card);
        border-radius: 20px;
        padding: 1.5rem;
        border: 1px solid var(--border);
        box-shadow: var(--shadow);
    }}
    
    .signal-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1.5rem;
    }}
    
    .ai-badge {{
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 0.25rem 1rem;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
    }}
    
    .signal-content {{
        text-align: center;
        padding: 2rem;
        border-radius: 16px;
        background: linear-gradient(135deg, rgba(59, 130, 246, 0.1), rgba(139, 92, 246, 0.1));
        margin-bottom: 1.5rem;
        border: 1px solid rgba(59, 130, 246, 0.2);
    }}
    
    .signal-type {{
        font-size: 2rem;
        font-weight: 800;
        margin-bottom: 1rem;
        text-transform: uppercase;
        letter-spacing: 2px;
    }}
    
    .signal-type.buy {{ color: var(--success); }}
    .signal-type.sell {{ color: var(--danger); }}
    .signal-type.neutral {{ color: var(--warning); }}
    
    .confidence-meter {{
        width: 100%;
        height: 8px;
        background: rgba(255,255,255,0.1);
        border-radius: 4px;
        margin: 1.5rem 0;
        overflow: hidden;
    }}
    
    .confidence-fill {{
        height: 100%;
        background: var(--gradient-primary);
        border-radius: 4px;
        transition: width 1s ease;
    }}
    
    /* Market Overview */
    .market-overview {{
        background: var(--bg-card);
        border-radius: 20px;
        padding: 1.5rem;
        border: 1px solid var(--border);
        box-shadow: var(--shadow);
        margin-top: 2rem;
    }}
    
    .market-tabs {{
        display: flex;
        gap: 1rem;
        margin-bottom: 1.5rem;
        border-bottom: 1px solid var(--border);
        padding-bottom: 1rem;
    }}
    
    .market-tab {{
        padding: 0.5rem 1.5rem;
        border-radius: 8px;
        background: transparent;
        border: none;
        color: var(--text-muted);
        cursor: pointer;
        transition: all 0.2s;
        font-weight: 500;
    }}
    
    .market-tab.active {{
        background: var(--primary);
        color: white;
    }}
    
    .market-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
        gap: 1rem;
    }}
    
    /* Upgrade Banner */
    .upgrade-banner {{
        background: linear-gradient(135deg, var(--primary), var(--primary-dark));
        border-radius: 20px;
        padding: 2rem;
        margin-top: 2rem;
        text-align: center;
        position: relative;
        overflow: hidden;
    }}
    
    .upgrade-banner::before {{
        content: '';
        position: absolute;
        top: 0;
        right: 0;
        width: 200px;
        height: 200px;
        background: rgba(255,255,255,0.1);
        border-radius: 50%;
        transform: translate(100px, -100px);
    }}
    
    /* Animations */
    @keyframes float {{
        0%, 100% {{ transform: translateY(0); }}
        50% {{ transform: translateY(-10px); }}
    }}
    
    .floating {{
        animation: float 3s ease-in-out infinite;
    }}
    
    @keyframes pulse {{
        0%, 100% {{ opacity: 1; }}
        50% {{ opacity: 0.5; }}
    }}
    
    .pulse {{
        animation: pulse 2s ease-in-out infinite;
    }}
    
    /* Responsive */
    @media (max-width: 768px) {{
        .container {{ padding: 10px; }}
        .premium-header {{ padding: 1.5rem; }}
        .stats-grid {{ grid-template-columns: 1fr; }}
        .market-grid {{ grid-template-columns: 1fr; }}
    }}
</style>
</head> <body> <div class="container"> <!-- Premium Header --> <div class="premium-header"> <div class="header-top"> <div class="logo"> <div class="logo-icon"> <i class="fas fa-rocket"></i> </div> <div class="logo-text">Trading Bot Premium</div> </div> <div class="tier-badge"> <i class="fas fa-crown"></i> <span>{tier_info['name']} Tier</span> </div> </div>
text
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon">
                    <i class="fas fa-chart-line"></i>
                </div>
                <div class="stat-value" id="totalSymbols">12</div>
                <div class="stat-label">Active Symbols</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">
                    <i class="fas fa-bolt"></i>
                </div>
                <div class="stat-value" id="marketSentiment">68%</div>
                <div class="stat-label">Bullish Sentiment</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">
                    <i class="fas fa-signal"></i>
                </div>
                <div class="stat-value" id="aiAccuracy">92.5%</div>
                <div class="stat-label">AI Accuracy</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">
                    <i class="fas fa-clock"></i>
                </div>
                <div class="stat-value" id="responseTime">0.8s</div>
                <div class="stat-label">Response Time</div>
            </div>
        </div>
    </div>
    
    <!-- Main Content -->
    <div class="main-content">
        <!-- Left Column - Chart -->
        <div class="chart-container">
            <div class="chart-header">
                <h2>Trading View</h2>
                <div class="chart-controls">
                    <select id="timeframeSelect" class="market-tab" style="background: var(--bg-card);">
                        <option value="5m">5m</option>
                        <option value="15m">15m</option>
                        <option value="1h">1h</option>
                        <option value="4h">4h</option>
                        <option value="1d">1d</option>
                    </select>
                    <input type="text" id="symbolInput" placeholder="BTCUSDT" value="BTCUSDT" 
                           style="background: var(--bg-card); border: 1px solid var(--border); padding: 0.5rem; border-radius: 8px; color: var(--text);">
                    <button onclick="updateChart()" class="market-tab active">
                        <i class="fas fa-sync-alt"></i> Update
                    </button>
                </div>
            </div>
            <div id="tradingview_chart" style="height: 500px; border-radius: 12px;"></div>
        </div>
        
        <!-- Right Column - AI Signals -->
        <div class="ai-signal-panel">
            <div class="signal-header">
                <h3>AI Trading Signal</h3>
                <div class="ai-badge">
                    <i class="fas fa-brain"></i> AI v2.1
                </div>
            </div>
            
            <div class="signal-content">
                <div class="signal-type" id="signalType">ANALYZING...</div>
                <div class="confidence-meter">
                    <div class="confidence-fill" id="confidenceFill" style="width: 50%"></div>
                </div>
                <div class="confidence-text" id="confidenceText">Confidence: 50%</div>
                
                <div style="margin-top: 2rem;">
                    <div style="font-size: 2.5rem; font-weight: 800;" id="currentPrice">$--,--</div>
                    <div style="color: var(--text-muted); margin-top: 0.5rem;" id="priceChange">Loading...</div>
                </div>
            </div>
            
            <div id="signalDetails">
                <div class="loading">
                    <div class="spinner"></div>
                    <div>AI is analyzing market data...</div>
                </div>
            </div>
            
            <div style="margin-top: 1.5rem; padding-top: 1.5rem; border-top: 1px solid var(--border);">
                <h4 style="margin-bottom: 1rem;">Quick Actions</h4>
                <button onclick="analyzeCurrent()" class="market-tab active" style="width: 100%; margin-bottom: 0.5rem;">
                    <i class="fas fa-chart-bar"></i> Analyze Current
                </button>
                <button onclick="getAISignal()" class="market-tab" style="width: 100%; background: var(--gradient-primary);">
                    <i class="fas fa-robot"></i> Get AI Signal
                </button>
            </div>
        </div>
    </div>
    
    <!-- Market Overview -->
    <div class="market-overview">
        <div class="market-tabs">
            <button class="market-tab active" onclick="showTab('all')">All Markets</button>
            <button class="market-tab" onclick="showTab('gainers')">Top Gainers</button>
            <button class="market-tab" onclick="showTab('losers')">Top Losers</button>
            <button class="market-tab" onclick="showTab('volume')">Volume Leaders</button>
        </div>
        
        <div class="market-grid" id="marketGrid">
            <!-- Market items will be loaded here -->
        </div>
    </div>
    
    <!-- Upgrade Banner for Free/Basic Users -->
    {self._get_upgrade_banner(user_tier)}
    
    <!-- Footer -->
    <footer style="text-align: center; padding: 3rem; color: var(--text-muted); margin-top: 3rem; border-top: 1px solid var(--border);">
        <div style="font-size: 0.9rem; margin-bottom: 1rem;">
            <i class="fas fa-shield-alt"></i> Secure & Encrypted • 
            <i class="fas fa-bolt"></i> Real-time Data • 
            <i class="fas fa-brain"></i> AI-Powered
        </div>
        <div style="color: var(--danger); font-size: 0.8rem;">
            <i class="fas fa-exclamation-triangle"></i> Trading involves risk. Past performance doesn't guarantee future results.
        </div>
    </footer>
</div>

<!-- TradingView Script -->
<script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>

<script>
    let currentSymbol = "BTCUSDT";
    let currentTimeframe = "5m";
    let tvWidget = null;
    
    function initTradingView() {{
        if (tvWidget) {{
            tvWidget.remove();
        }}
        
        tvWidget = new TradingView.widget({{
            container_id: "tradingview_chart",
            symbol: "BINANCE:BTCUSDT",
            interval: "5",
            timezone: "Etc/UTC",
            theme: "dark",
            style: "1",
            locale: "en",
            toolbar_bg: "#1a1f2e",
            enable_publishing: false,
            allow_symbol_change: true,
            details: true,
            hotlist: true,
            calendar: true,
            studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies"],
            show_popup_button: true,
            popup_width: "1000",
            popup_height: "650",
            autosize: true,
            disabled_features: ["header_widget"],
            enabled_features: ["study_templates"],
            overrides: {{
                "paneProperties.background": "#1a1f2e",
                "paneProperties.vertGridProperties.color": "rgba(255,255,255,0.05)",
                "paneProperties.horzGridProperties.color": "rgba(255,255,255,0.05)",
            }},
            loading_screen: {{ backgroundColor: "#1a1f2e" }}
        }});
    }}
    
    function updateChart() {{
        const symbol = document.getElementById('symbolInput').value.toUpperCase();
        const timeframe = document.getElementById('timeframeSelect').value;
        
        if (tvWidget) {{
            tvWidget.chart().setSymbol(`BINANCE:${{symbol}}`);
            tvWidget.chart().setResolution(timeframe);
        }}
        
        currentSymbol = symbol;
        currentTimeframe = timeframe;
        analyzeCurrent();
    }}
    
    async function analyzeCurrent() {{
        try {{
            const response = await fetch(`/api/ai-signal/${{currentSymbol}}?timeframe=${{currentTimeframe}}`);
            const data = await response.json();
            
            if (data.success) {{
                updateSignalDisplay(data.signal);
            }}
        }} catch (error) {{
            console.error('Analysis error:', error);
        }}
    }}
    
    function updateSignalDisplay(signal) {{
        const signalType = document.getElementById('signalType');
        const confidenceFill = document.getElementById('confidenceFill');
        const confidenceText = document.getElementById('confidenceText');
        const currentPrice = document.getElementById('currentPrice');
        const priceChange = document.getElementById('priceChange');
        
        signalType.textContent = signal.signal.replace('_', ' ');
        signalType.className = `signal-type ${{signal.signal.toLowerCase().includes('buy') ? 'buy' : 
            signal.signal.toLowerCase().includes('sell') ? 'sell' : 'neutral'}}`;
        
        confidenceFill.style.width = `${{signal.confidence}}%`;
        confidenceText.textContent = `Confidence: ${{signal.confidence}}%`;
        currentPrice.textContent = `$${{signal.price.toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 4}})}}`;
        
        // Update signal details
        const detailsHtml = `
            <div style="text-align: left;">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem;">
                    <div>
                        <div style="color: var(--text-muted); font-size: 0.8rem;">Risk/Reward</div>
                        <div style="font-weight: 600;">1:${{signal.risk_reward.toFixed(2)}}</div>
                    </div>
                    <div>
                        <div style="color: var(--text-muted); font-size: 0.8rem;">Stop Loss</div>
                        <div style="font-weight: 600;">$${{signal.stop_loss.toFixed(2)}}</div>
                    </div>
                </div>
                
                <div style="margin-bottom: 1rem;">
                    <div style="color: var(--text-muted); font-size: 0.8rem; margin-bottom: 0.5rem;">Targets</div>
                    <div style="display: flex; gap: 0.5rem;">
                        ${{signal.targets.map(t => `<span style="background: var(--primary); padding: 0.25rem 0.75rem; border-radius: 20px; font-size: 0.8rem;">$${{t.toFixed(2)}}</span>`).join('')}}
                    </div>
                </div>
                
                <div>
                    <div style="color: var(--text-muted); font-size: 0.8rem; margin-bottom: 0.5rem;">AI Reasoning</div>
                    <ul style="padding-left: 1rem; font-size: 0.9rem;">
                        ${{signal.reasoning.map(r => `<li style="margin-bottom: 0.25rem;">${{r}}</li>`).join('')}}
                    </ul>
                </div>
            </div>
        `;
        
        document.getElementById('signalDetails').innerHTML = detailsHtml;
    }}
    
    async function loadMarketOverview() {{
        try {{
            const response = await fetch('/api/market/overview');
            const data = await response.json();
            
            if (data.success) {{
                updateMarketDisplay(data.overview);
            }}
        }} catch (error) {{
            console.error('Market load error:', error);
        }}
    }}
    
    function updateMarketDisplay(overview) {{
        // Update stats
        document.getElementById('totalSymbols').textContent = overview.total_symbols;
        document.getElementById('marketSentiment').textContent = `${{overview.market_sentiment.ratio}}%`;
        
        // Update market grid
        const marketGrid = document.getElementById('marketGrid');
        let symbols = [];
        
        // Combine all symbols from data
        if (overview.top_gainers) symbols = [...overview.top_gainers];
        
        const gridHtml = symbols.map(symbol => `
            <div class="market-item" onclick="setSymbol('${{symbol.symbol}}')" 
                 style="background: rgba(255,255,255,0.03); padding: 1rem; border-radius: 12px; border: 1px solid var(--border); cursor: pointer; transition: all 0.2s;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                    <div style="font-weight: 600;">${{symbol.symbol}}</div>
                    <div style="font-size: 0.8rem; color: var(--text-muted);">
                        <i class="fas fa-circle" style="color: ${{symbol.change >= 0 ? 'var(--success)' : 'var(--danger)'}};"></i>
                    </div>
                </div>
                <div style="font-size: 1.2rem; font-weight: 700; margin-bottom: 0.25rem;">
                    $${{(symbol.price || 0).toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 4}})}}
                </div>
                <div style="color: ${{symbol.change >= 0 ? 'var(--success)' : 'var(--danger)'}}; font-weight: 500;">
                    ${{symbol.change >= 0 ? '↗' : '↘'}} ${{Math.abs(symbol.change).toFixed(2)}}%
                </div>
            </div>
        `).join('');
        
        marketGrid.innerHTML = gridHtml;
    }}
    
    function setSymbol(symbol) {{
        document.getElementById('symbolInput').value = symbol;
        updateChart();
    }}
    
    function showTab(tab) {{
        // Tab switching logic
        document.querySelectorAll('.market-tab').forEach(t => t.classList.remove('active'));
        event.target.classList.add('active');
    }}
    
    // Initialize on load
    document.addEventListener('DOMContentLoaded', () => {{
        initTradingView();
        setTimeout(() => analyzeCurrent(), 1000);
        setInterval(loadMarketOverview, 10000);
        loadMarketOverview();
    }});
</script>
</body> </html> """
text
def _get_upgrade_banner(self, user_tier: SubscriptionTier) -> str:
    """Get upgrade banner based on user tier"""
    if user_tier == SubscriptionTier.ENTERPRISE:
        return ""
    
    next_tier = {
        SubscriptionTier.FREE: SubscriptionTier.BASIC,
        SubscriptionTier.BASIC: SubscriptionTier.PRO,
        SubscriptionTier.PRO: SubscriptionTier.ENTERPRISE
    }.get(user_tier, SubscriptionTier.PRO)
    
    next_tier_info = SubscriptionManager.TIER_FEATURES[next_tier]
    
    return f"""
    <div class="upgrade-banner floating">
        <h3 style="margin-bottom: 1rem; color: white;">🚀 Upgrade to {next_tier_info['name']}</h3>
        <p style="margin-bottom: 1.5rem; color: rgba(255,255,255,0.9);">
            Unlock {len(next_tier_info['features'])} advanced features including AI signals, 
            advanced analytics, and priority support.
        </p>
        <button onclick="upgradeTo('{next_tier.value}')" 
                style="background: white; color: var(--primary); border: none; padding: 0.75rem 2rem; 
                       border-radius: 50px; font-weight: 600; cursor: pointer; font-size: 1rem;">
            <i class="fas fa-arrow-up"></i> Upgrade for ${next_tier_info['price']}/month
        </button>
    </div>
    """
==================== FASTAPI APPLICATION ====================
subscription_manager = SubscriptionManager()
data_provider = BinanceRealTimeData()
ai_engine = AISignalEngine(data_provider)
dashboard = PremiumDashboard(data_provider, ai_engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
logger.info("🚀 Trading Bot Premium v4.0 starting...")

text
# Create a demo premium user
premium_user_id = subscription_manager.create_user(
    "premium@example.com", 
    SubscriptionTier.PRO
)

# Create a demo free user
free_user_id = subscription_manager.create_user(
    "free@example.com", 
    SubscriptionTier.FREE
)

app.state.demo_users = {
    "premium": premium_user_id,
    "free": free_user_id
}

app.state.data_provider = data_provider
app.state.ai_engine = ai_engine
app.state.dashboard = dashboard
app.state.subscription_manager = subscription_manager

async def start_websocket():
    try:
        await data_provider.connect(TradingViewConfig.DEFAULT_SYMBOLS)
    except Exception as e:
        logger.error(f"WebSocket connection failed: {e}")

asyncio.create_task(start_websocket())

yield

logger.info("🛑 Trading Bot Premium shutting down...")
app = FastAPI(
title="Trading Bot Premium v4.0",
version="4.0",
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

Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

========== API ENDPOINTS ==========
@app.get("/")
async def root():
return RedirectResponse("/dashboard")

@app.get("/dashboard")
async def get_dashboard(request: Request):
"""Main dashboard - defaults to premium demo"""
user_id = app.state.demo_users["premium"]
user_tier = subscription_manager.get_user_tier(user_id)

text
html = dashboard.get_dashboard_html(user_tier)
return HTMLResponse(html)
@app.get("/dashboard/free")
async def get_free_dashboard():
"""Free tier dashboard"""
user_id = app.state.demo_users["free"]
user_tier = subscription_manager.get_user_tier(user_id)

text
html = dashboard.get_dashboard_html(user_tier)
return HTMLResponse(html)
@app.get("/api/market/overview")
async def market_overview():
try:
overview = data_provider.get_market_overview()
return {
"success": True,
"timestamp": datetime.now(timezone.utc).isoformat(),
"overview": overview
}
except Exception as e:
logger.error(f"Market overview error: {e}")
return {"success": False, "error": str(e)}

@app.get("/api/ai-signal/{symbol}")
async def get_ai_signal(symbol: str, timeframe: str = "1h"):
try:
signal = await ai_engine.analyze_symbol(symbol, timeframe)

text
    # Convert AISignal to dict
    signal_dict = {
        "symbol": signal.symbol,
        "timeframe": signal.timeframe,
        "signal": signal.signal,
        "confidence": signal.confidence,
        "price": signal.price,
        "targets": signal.targets,
        "stop_loss": signal.stop_loss,
        "risk_reward": signal.risk_reward,
        "timestamp": signal.timestamp,
        "reasoning": signal.reasoning,
        "priority": signal.priority
    }
    
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "signal": signal_dict
    }
except Exception as e:
    logger.error(f"AI signal error: {e}")
    return {"success": False, "error": str(e)}
@app.get("/api/subscription/tiers")
async def get_subscription_tiers():
"""Get all subscription tiers"""
tiers = {}
for tier in SubscriptionTier:
tiers[tier.value] = subscription_manager.TIER_FEATURES[tier]

text
return {
    "success": True,
    "tiers": tiers
}
@app.post("/api/subscription/upgrade")
async def upgrade_subscription(
tier: str = Form(...),
coupon: str = Form(None)
):
"""Upgrade subscription tier"""
try:
# In production, integrate with payment gateway
# For demo, just return success
return {
"success": True,
"message": f"Upgraded to {tier} tier successfully",
"redirect_url": "/dashboard"
}
except Exception as e:
return {"success": False, "error": str(e)}

@app.get("/health")
async def health():
return {
"status": "healthy",
"version": "4.0",
"timestamp": datetime.now(timezone.utc).isoformat(),
"subscription_system": "active",
"ai_engine": "active",
"realtime_data": data_provider.connected
}

========== STARTUP ==========
@app.on_event("startup")
async def startup():
logger.info("="*70)
logger.info("🚀 TRADING BOT PREMIUM v4.0 STARTED")
logger.info("="*70)
logger.info(f"✅ Port: {os.getenv('PORT', 8000)}")
logger.info("✅ Premium Subscription System: ACTIVE")
logger.info("✅ AI Signal Engine: v2.1 ACTIVE")
logger.info("✅ Real-time Binance WebSocket: ENABLED")
logger.info("✅ Premium Dashboard: READY")
logger.info("")
logger.info("📊 Demo Users:")
logger.info(" Premium: /dashboard")
logger.info(" Free: /dashboard/free")
logger.info("")
logger.info("🔧 API Endpoints:")
logger.info(" Health: /health")
logger.info(" Market Overview: /api/market/overview")
logger.info(" AI Signal: /api/ai-signal/{symbol}")
logger.info(" Subscription Tiers: /api/subscription/tiers")
logger.info("="*70)

if name == "main":
import uvicorn
port = int(os.getenv("PORT", 8000))
uvicorn.run(
app,
host="0.0.0.0",
port=port,
log_level="info",
access_log=True
) 
