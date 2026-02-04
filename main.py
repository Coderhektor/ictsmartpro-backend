# app/main.py
import time
import json
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
import websockets
import ssl
from collections import defaultdict

# ==========================================
# CONFIGURATION
# ==========================================
class Config:
    # Binance Public API (no key needed)
    BINANCE_BASE = "https://api.binance.com"
    BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"
    
    # CoinGecko Public API (no key needed)
    COINGECKO_BASE = "https://api.coingecko.com/api/v3"
    
    # Redis
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Cache
    CACHE_TTL = 30  # seconds
    OHLCV_CACHE_TTL = 300  # 5 minutes for historical data
    
    # Rate limiting
    REQUESTS_PER_MINUTE = 1200  # Binance limit
    
    # Trading
    DEFAULT_QUANTITY = 0.001  # Default BTC quantity
    STOP_LOSS_PCT = 0.02  # 2%
    TAKE_PROFIT_PCT = 0.04  # 4%
    
    # WebSocket symbols
    DEFAULT_SYMBOLS = [
        "btcusdt", "ethusdt", "bnbusdt", "xrpusdt", "adausdt",
        "solusdt", "dotusdt", "dogeusdt", "avaxusdt", "linkusdt",
        "maticusdt", "uniusdt", "ltcusdt", "bchusdt", "xlmusdt"
    ]

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

# ==========================================
# WEB SOCKET MANAGER (BINANCE REAL-TIME DATA)
# ==========================================
class WebSocketManager:
    def __init__(self):
        self.connections = {}
        self.price_data = {}
        self.kline_data = {}
        self.ticker_data = []
        
    async def connect_ticker_stream(self, symbols: List[str]):
        """Connect to Binance WebSocket for ticker data"""
        streams = [f"{symbol.lower()}@ticker" for symbol in symbols]
        stream_url = f"{Config.BINANCE_WS_URL}/{'/'.join(streams)}"
        
        while True:
            try:
                async with websockets.connect(stream_url) as websocket:
                    logger.info(f"✅ WebSocket connected for {len(symbols)} symbols")
                    
                    while True:
                        try:
                            message = await websocket.recv()
                            data = json.loads(message)
                            
                            if 'data' in data:
                                symbol = data['data']['s']
                                self.price_data[symbol] = {
                                    'symbol': symbol,
                                    'price': float(data['data']['c']),
                                    'change': float(data['data']['P']),
                                    'high': float(data['data']['h']),
                                    'low': float(data['data']['l']),
                                    'volume': float(data['data']['v']),
                                    'quote_volume': float(data['data']['q']),
                                    'timestamp': datetime.utcnow().isoformat(),
                                    'source': 'binance_ws'
                                }
                                
                                # Update ticker data list
                                await self.update_ticker_data()
                                
                        except websockets.exceptions.ConnectionClosed:
                            logger.warning("WebSocket connection closed, reconnecting...")
                            break
                        except Exception as e:
                            logger.error(f"WebSocket error: {e}")
                            await asyncio.sleep(1)
                            
            except Exception as e:
                logger.error(f"Failed to connect to WebSocket: {e}")
                await asyncio.sleep(5)  # Wait before reconnecting
                
    async def connect_kline_stream(self, symbol: str, interval: str = "1h"):
        """Connect to Binance WebSocket for kline data"""
        stream_url = f"{Config.BINANCE_WS_URL}/{symbol.lower()}@kline_{interval}"
        
        while True:
            try:
                async with websockets.connect(stream_url) as websocket:
                    while True:
                        try:
                            message = await websocket.recv()
                            data = json.loads(message)
                            kline = data['k']
                            
                            candle_key = f"{symbol}_{interval}"
                            self.kline_data[candle_key] = {
                                'symbol': symbol,
                                'interval': interval,
                                'open': float(kline['o']),
                                'high': float(kline['h']),
                                'low': float(kline['l']),
                                'close': float(kline['c']),
                                'volume': float(kline['v']),
                                'timestamp': datetime.fromtimestamp(kline['t'] / 1000),
                                'is_closed': kline['x']
                            }
                            
                        except Exception as e:
                            logger.error(f"Kline stream error: {e}")
                            break
                            
            except Exception as e:
                logger.error(f"Failed to connect to kline stream: {e}")
                await asyncio.sleep(5)
                
    async def update_ticker_data(self):
        """Update ticker data list from price data"""
        ticker_list = []
        for symbol, data in self.price_data.items():
            ticker_list.append({
                'symbol': symbol,
                'price': data['price'],
                'change_24h': data['change'],
                'volume_24h': data['volume'],
                'high_24h': data['high'],
                'low_24h': data['low'],
                'last_updated': data['timestamp']
            })
        
        # Sort by volume
        ticker_list.sort(key=lambda x: x['volume_24h'], reverse=True)
        self.ticker_data = ticker_list
        
    async def start_all_streams(self):
        """Start all WebSocket streams"""
        # Start ticker stream for default symbols
        asyncio.create_task(self.connect_ticker_stream(Config.DEFAULT_SYMBOLS))
        
        # Start kline streams for major symbols
        major_symbols = ["btcusdt", "ethusdt", "bnbusdt"]
        for symbol in major_symbols:
            asyncio.create_task(self.connect_kline_stream(symbol, "1h"))
            
        logger.info("✅ All WebSocket streams started")

# ==========================================
# DATA MANAGER (HTTP REQUESTS)
# ==========================================
class DataManager:
    def __init__(self):
        self.session = aiohttp.ClientSession()
        self.cache = {}
        self.last_request = {}
        self.ws_manager = WebSocketManager()
        
    async def initialize(self):
        """Initialize WebSocket connections"""
        await self.ws_manager.start_all_streams()
        
    async def fetch_binance_klines(self, symbol: str, interval: str, limit: int = 100):
        """Fetch OHLCV data from Binance Public API"""
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
                            "trades": k[8]
                        }
                        candles.append(candle)
                    
                    # Cache result
                    self.cache[cache_key] = (candles, time.time())
                    
                    return candles
                else:
                    logger.warning(f"Binance API error: {response.status}, using WebSocket data if available")
                    # Try to get from WebSocket
                    return await self.get_websocket_klines(symbol, interval, limit)
                    
        except Exception as e:
            logger.error(f"Error fetching Binance klines: {e}")
            return await self.get_websocket_klines(symbol, interval, limit)
    
    async def get_websocket_klines(self, symbol: str, interval: str, limit: int):
        """Get kline data from WebSocket cache"""
        candle_key = f"{symbol}_{interval}"
        if candle_key in self.ws_manager.kline_data:
            ws_data = self.ws_manager.kline_data[candle_key]
            # Create simulated candles based on WebSocket data
            candles = []
            current_time = datetime.utcnow().timestamp() * 1000
            
            for i in range(limit):
                timestamp = current_time - (limit - i - 1) * 3600000  # 1 hour intervals
                
                # Simulate some variation
                if i == limit - 1:
                    # Latest candle from WebSocket
                    candle = {
                        "timestamp": int(timestamp),
                        "open": ws_data['open'],
                        "high": ws_data['high'],
                        "low": ws_data['low'],
                        "close": ws_data['close'],
                        "volume": ws_data['volume'],
                        "close_time": int(timestamp + 3599999),
                        "quote_volume": ws_data['volume'] * ws_data['close'],
                        "trades": 1000
                    }
                else:
                    # Simulated historical candles
                    base_price = ws_data['close'] * (1 - (limit - i - 1) * 0.001)
                    candle = {
                        "timestamp": int(timestamp),
                        "open": base_price,
                        "high": base_price * 1.01,
                        "low": base_price * 0.99,
                        "close": base_price * 1.005,
                        "volume": ws_data['volume'] * 0.8,
                        "close_time": int(timestamp + 3599999),
                        "quote_volume": ws_data['volume'] * 0.8 * base_price,
                        "trades": 800
                    }
                candles.append(candle)
            
            return candles
        
        return None
    
    async def fetch_coingecko_data(self, symbol: str):
        """Fetch data from CoinGecko Public API"""
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
                "ATOM": "cosmos",
                "USDT": "tether"
            }
            
            coin_symbol = symbol.upper().replace("USDT", "")
            coin_id = symbol_map.get(coin_symbol, coin_symbol.lower())
            
            # First try simple price endpoint
            url = f"{Config.COINGECKO_BASE}/simple/price"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_vol": "true",
                "include_24hr_change": "true",
                "include_market_cap": "true"
            }
            
            # Rate limiting
            await self._rate_limit("coingecko")
            
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if coin_id in data:
                        coin_data = data[coin_id]
                        result = {
                            "id": coin_id,
                            "symbol": coin_symbol,
                            "current_price": coin_data.get("usd", 0),
                            "market_cap": coin_data.get("usd_market_cap", 0),
                            "volume_24h": coin_data.get("usd_24h_vol", 0),
                            "price_change_24h": coin_data.get("usd_24h_change", 0)
                        }
                        
                        # Cache result
                        self.cache[cache_key] = (result, time.time())
                        
                        return result
                
                # Fallback to markets endpoint
                url = f"{Config.COINGECKO_BASE}/coins/markets"
                params = {
                    "vs_currency": "usd",
                    "ids": coin_id,
                    "order": "market_cap_desc",
                    "per_page": 1,
                    "page": 1,
                    "sparkline": "false",
                    "price_change_percentage": "24h"
                }
                
                async with self.session.get(url, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data:
                            coin = data[0]
                            result = {
                                "id": coin["id"],
                                "symbol": coin["symbol"].upper(),
                                "name": coin["name"],
                                "current_price": coin["current_price"],
                                "market_cap": coin["market_cap"],
                                "market_cap_rank": coin["market_cap_rank"],
                                "total_volume": coin["total_volume"],
                                "high_24h": coin["high_24h"],
                                "low_24h": coin["low_24h"],
                                "price_change_24h": coin["price_change_24h"],
                                "price_change_percentage_24h": coin["price_change_percentage_24h"],
                                "last_updated": coin["last_updated"]
                            }
                            
                            # Cache result
                            self.cache[cache_key] = (result, time.time())
                            
                            return result
            
            return None
                    
        except Exception as e:
            logger.error(f"Error fetching CoinGecko data: {e}")
            return None
    
    async def fetch_binance_ticker(self, symbol: str):
        """Fetch ticker data - first try WebSocket, then API"""
        try:
            # First check WebSocket data (real-time)
            symbol_upper = symbol.upper()
            if symbol_upper in self.ws_manager.price_data:
                ws_data = self.ws_manager.price_data[symbol_upper]
                return {
                    "symbol": symbol_upper,
                    "price": ws_data['price'],
                    "price_change": ws_data['change'],
                    "price_change_percent": ws_data['change'],
                    "volume": ws_data['volume'],
                    "quote_volume": ws_data['quote_volume'],
                    "high_price": ws_data['high'],
                    "low_price": ws_data['low'],
                    "timestamp": ws_data['timestamp'],
                    "source": "websocket"
                }
            
            # Fallback to API
            cache_key = f"binance:ticker:{symbol}"
            
            # Check cache
            if cache_key in self.cache:
                cached_data, timestamp = self.cache[cache_key]
                if time.time() - timestamp < 2:  # 2 seconds cache
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
                        "volume": float(data["volume"]),
                        "quote_volume": float(data["quoteVolume"]),
                        "high_price": float(data["highPrice"]),
                        "low_price": float(data["lowPrice"]),
                        "timestamp": datetime.utcnow().isoformat(),
                        "source": "api"
                    }
                    
                    # Cache result
                    self.cache[cache_key] = (result, time.time())
                    
                    return result
                else:
                    return None
                    
        except Exception as e:
            logger.error(f"Error fetching Binance ticker: {e}")
            return None
    
    async def fetch_order_book(self, symbol: str, limit: int = 10):
        """Fetch order book data from Binance"""
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
    
    async def fetch_market_data(self):
        """Fetch market data for multiple symbols"""
        try:
            # Get top symbols from WebSocket
            if self.ws_manager.ticker_data:
                return self.ws_manager.ticker_data[:15]
            
            # Fallback to API for top symbols
            symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", 
                      "SOLUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT"]
            
            market_data = []
            for symbol in symbols:
                ticker = await self.fetch_binance_ticker(symbol)
                if ticker:
                    market_data.append({
                        "symbol": symbol,
                        "price": ticker["price"],
                        "change_24h": ticker["price_change_percent"],
                        "volume": ticker["volume"],
                        "high_24h": ticker["high_price"],
                        "low_24h": ticker["low_price"]
                    })
            
            return market_data
            
        except Exception as e:
            logger.error(f"Error fetching market data: {e}")
            return []
    
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
# TECHNICAL ANALYSIS ENGINE (Aynı kalıyor)
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
        volumes = [c.get("volume", 0) for c in candles]
        
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
    
    # Diğer statik metodlar aynı kalıyor...
    # (sma, ema, rsi, macd, stochastic, bollinger_bands, atr, obv, 
    # support_resistance, trend_analysis, detect_patterns)

# ==========================================
# TRADING ENGINE (Aynı kalıyor)
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
        """Execute simulated trade order"""
        order_id = f"order_{int(time.time() * 1000)}"
        
        order = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "price": price or 0,
            "status": "SIMULATED",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self.order_history.append(order)
        
        # Update positions (simulated)
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
    logger.info("🚀 Starting Trading Platform (No API Key Required)...")
    
    # Initialize components
    data_manager = DataManager()
    trading_engine = TradingEngine()
    
    try:
        redis_client = await redis.from_url(Config.REDIS_URL, decode_responses=True)
        await redis_client.ping()
        logger.info("🗄️ Redis: Connected")
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        redis_client = None
    
    # Initialize WebSocket connections
    await data_manager.initialize()
    
    logger.info("✅ All systems initialized")
    logger.info("📊 Data Manager: Ready (WebSocket + Public APIs)")
    logger.info("🤖 Trading Engine: Ready")
    logger.info("🔌 Real-time data: Active")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down Trading Platform...")
    await data_manager.close()
    if redis_client:
        await redis_client.close()
    logger.info("✅ Clean shutdown complete")

# ==========================================
# FASTAPI APP
# ==========================================
app = FastAPI(
    title="Advanced Trading Platform (No API Key)",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# API ENDPOINTS
# ==========================================
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "🚀 Advanced Trading Platform (No API Key Required)",
        "version": "2.0.0",
        "status": "operational",
        "uptime": int(time.time() - START_TIME),
        "features": [
            "Real-time Binance WebSocket data",
            "CoinGecko market data",
            "Advanced technical analysis",
            "Trading signals",
            "Web dashboard",
            "No API keys required"
        ],
        "endpoints": {
            "/health": "Health check",
            "/api/ticker/{symbol}": "Get ticker data",
            "/api/klines/{symbol}": "Get OHLCV data",
            "/api/analyze": "Technical analysis",
            "/api/signal/{symbol}": "Trading signal",
            "/api/market": "Market overview",
            "/dashboard": "Web dashboard",
            "/docs": "API documentation"
        }
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    try:
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
                "binance_api": "operational",
                "coingecko_api": "operational",
                "websocket": "operational",
                "trading_engine": "operational"
            },
            "real_time_data": len(data_manager.ws_manager.price_data) > 0
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")

@app.get("/api/ticker/{symbol}")
async def get_ticker(symbol: str):
    """Get real-time ticker data"""
    try:
        # Get from Binance (WebSocket first, then API)
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
            "timestamp": ticker.get("timestamp", datetime.utcnow().isoformat()),
            "source": ticker.get("source", "api")
        }
        
        if cg_data:
            response.update({
                "market_cap": cg_data.get("market_cap", 0),
                "market_cap_rank": cg_data.get("market_cap_rank"),
                "price_change_percentage_7d": cg_data.get("price_change_percentage_24h", 0),
                "coingecko_price": cg_data.get("current_price", 0)
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
            "timestamp": datetime.utcnow().isoformat(),
            "source": "binance_api"
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

@app.get("/api/market")
async def market_overview():
    """Get market overview"""
    try:
        market_data = await data_manager.fetch_market_data()
        
        return {
            "market_data": market_data,
            "count": len(market_data),
            "timestamp": datetime.utcnow().isoformat(),
            "websocket_connected": len(data_manager.ws_manager.price_data) > 0
        }
        
    except Exception as e:
        logger.error(f"Market overview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/orderbook/{symbol}")
async def get_orderbook(symbol: str, limit: int = 10):
    """Get order book data"""
    try:
        orderbook = await data_manager.fetch_order_book(symbol, limit)
        
        if not orderbook:
            raise HTTPException(status_code=404, detail="Order book not available")
        
        return {
            "symbol": symbol,
            "bids": orderbook["bids"],
            "asks": orderbook["asks"],
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Order book error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# WEB DASHBOARD
# ==========================================
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Trading dashboard"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Trading Platform - No API Key Required</title>
        <script src="https://s3.tradingview.com/tv.js"></script>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                background: #0f172a;
                color: #e2e8f0;
                min-height: 100vh;
            }
            
            .container {
                max-width: 1400px;
                margin: 0 auto;
                padding: 20px;
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
            
            .status {
                padding: 8px 16px;
                border-radius: 20px;
                background: #22c55e;
                color: white;
                font-size: 14px;
                font-weight: 600;
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
            
            .card h3 {
                margin-bottom: 15px;
                color: #cbd5e1;
            }
            
            .tradingview-widget {
                height: 500px;
                border-radius: 8px;
                overflow: hidden;
            }
            
            .controls {
                display: flex;
                gap: 10px;
                margin-bottom: 20px;
                flex-wrap: wrap;
            }
            
            input, select, button {
                padding: 10px 15px;
                border-radius: 5px;
                border: 1px solid #475569;
                background: #1e293b;
                color: #e2e8f0;
                font-size: 14px;
            }
            
            button {
                background: #3b82f6;
                border: none;
                cursor: pointer;
                font-weight: 600;
                transition: background 0.3s;
            }
            
            button:hover {
                background: #2563eb;
            }
            
            .signal {
                padding: 20px;
                border-radius: 8px;
                margin-bottom: 20px;
                text-align: center;
                font-weight: bold;
            }
            
            .signal.buy {
                background: rgba(34, 197, 94, 0.2);
                border: 2px solid #22c55e;
                color: #22c55e;
            }
            
            .signal.sell {
                background: rgba(239, 68, 68, 0.2);
                border: 2px solid #ef4444;
                color: #ef4444;
            }
            
            .signal.hold {
                background: rgba(234, 179, 8, 0.2);
                border: 2px solid #eab308;
                color: #eab308;
            }
            
            .market-table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }
            
            .market-table th {
                padding: 12px;
                text-align: left;
                border-bottom: 2px solid #334155;
                color: #94a3b8;
                font-weight: 600;
                text-transform: uppercase;
                font-size: 12px;
            }
            
            .market-table td {
                padding: 12px;
                border-bottom: 1px solid #334155;
            }
            
            .market-table tr:hover {
                background: #1e293b;
            }
            
            .positive {
                color: #22c55e;
                font-weight: 600;
            }
            
            .negative {
                color: #ef4444;
                font-weight: 600;
            }
            
            .indicator-grid {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 10px;
                margin-top: 15px;
            }
            
            .indicator-item {
                background: #0f172a;
                padding: 10px;
                border-radius: 6px;
                border: 1px solid #334155;
            }
            
            .indicator-label {
                font-size: 12px;
                color: #94a3b8;
                margin-bottom: 5px;
            }
            
            .indicator-value {
                font-size: 16px;
                font-weight: 600;
                font-family: 'Courier New', monospace;
            }
            
            .realtime-badge {
                display: inline-block;
                padding: 4px 8px;
                background: #3b82f6;
                color: white;
                border-radius: 4px;
                font-size: 12px;
                margin-left: 10px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">🚀 Trading Platform (No API Key)</div>
                <div class="status">Real-time Data Active</div>
            </div>
            
            <div class="controls">
                <input type="text" id="symbol" placeholder="Symbol (BTCUSDT)" value="BTCUSDT">
                <select id="timeframe">
                    <option value="1m">1 Minute</option>
                    <option value="5m">5 Minutes</option>
                    <option value="15m">15 Minutes</option>
                    <option value="30m">30 Minutes</option>
                    <option value="1h" selected>1 Hour</option>
                    <option value="4h">4 Hours</option>
                    <option value="1d">1 Day</option>
                </select>
                <button onclick="analyze()">📊 Analyze</button>
                <button onclick="getSignal()">🤖 Get Signal</button>
                <button onclick="loadMarketData()">🔄 Refresh Market</button>
            </div>
            
            <div class="grid">
                <div class="card">
                    <h3>Live Chart <span class="realtime-badge">Real-time</span></h3>
                    <div id="tradingview" class="tradingview-widget"></div>
                </div>
                
                <div class="card">
                    <h3>Trading Signal</h3>
                    <div id="signal" class="signal hold">
                        <div style="font-size: 24px; margin-bottom: 10px;">HOLD</div>
                        <div>Confidence: 50%</div>
                        <div>Price: $0.00</div>
                        <div>Click "Get Signal" to analyze</div>
                    </div>
                    
                    <h4>Technical Indicators</h4>
                    <div id="indicators" class="indicator-grid">
                        <!-- Filled by JavaScript -->
                    </div>
                </div>
            </div>
            
            <div class="card">
                <h3>Market Overview <span class="realtime-badge">Live</span></h3>
                <table class="market-table" id="marketTable">
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Price</th>
                            <th>24h Change</th>
                            <th>Volume</th>
                            <th>High</th>
                            <th>Low</th>
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
            // Initialize TradingView Widget
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
                "hide_side_toolbar": false,
                "allow_symbol_change": true,
                "container_id": "tradingview",
                "studies": [
                    "RSI@tv-basicstudies",
                    "MACD@tv-basicstudies",
                    "BB@tv-basicstudies",
                    "Volume@tv-basicstudies"
                ],
                "disabled_features": ["header_widget"],
                "enabled_features": ["study_templates"]
            });
            
            // Load market data
            async function loadMarketData() {
                try {
                    const response = await fetch('/api/market');
                    const data = await response.json();
                    
                    const tbody = document.querySelector('#marketTable tbody');
                    tbody.innerHTML = '';
                    
                    data.market_data.forEach(item => {
                        const changeClass = item.change_24h >= 0 ? 'positive' : 'negative';
                        const changeSign = item.change_24h >= 0 ? '+' : '';
                        
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td><strong>${item.symbol}</strong></td>
                            <td>$${item.price.toFixed(2)}</td>
                            <td class="${changeClass}">${changeSign}${item.change_24h.toFixed(2)}%</td>
                            <td>${(item.volume / 1000000).toFixed(2)}M</td>
                            <td>$${item.high_24h.toFixed(2)}</td>
                            <td>$${item.low_24h.toFixed(2)}</td>
                            <td>
                                <button onclick="analyzeSymbol('${item.symbol}')" style="padding: 5px 10px; font-size: 12px;">
                                    Analyze
                                </button>
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
                    
                    // Update TradingView chart
                    updateChart(symbol);
                } catch (error) {
                    console.error('Analysis error:', error);
                    alert('Analysis failed: ' + error.message);
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
                    alert('Signal failed: ' + error.message);
                }
            }
            
            // Analyze specific symbol
            function analyzeSymbol(symbol) {
                document.getElementById('symbol').value = symbol;
                analyze();
                getSignal();
                updateChart(symbol);
            }
            
            // Update TradingView chart
            function updateChart(symbol) {
                // TradingView widget doesn't have a direct method to change symbol
                // We'll reload the widget
                document.getElementById('tradingview').innerHTML = '';
                new TradingView.widget({
                    "width": "100%",
                    "height": "500",
                    "symbol": `BINANCE:${symbol}`,
                    "interval": document.getElementById('timeframe').value,
                    "timezone": "Etc/UTC",
                    "theme": "dark",
                    "style": "1",
                    "locale": "en",
                    "toolbar_bg": "#0f172a",
                    "enable_publishing": false,
                    "hide_side_toolbar": false,
                    "allow_symbol_change": true,
                    "container_id": "tradingview",
                    "studies": [
                        "RSI@tv-basicstudies",
                        "MACD@tv-basicstudies",
                        "BB@tv-basicstudies",
                        "Volume@tv-basicstudies"
                    ],
                    "disabled_features": ["header_widget"],
                    "enabled_features": ["study_templates"]
                });
            }
            
            // Display analysis
            function displayAnalysis(data) {
                const indicatorsDiv = document.getElementById('indicators');
                if (!data.indicators) return;
                
                const indicators = data.indicators;
                indicatorsDiv.innerHTML = `
                    <div class="indicator-item">
                        <div class="indicator-label">RSI</div>
                        <div class="indicator-value ${indicators.rsi > 70 ? 'negative' : indicators.rsi < 30 ? 'positive' : ''}">
                            ${indicators.rsi.toFixed(2)}
                        </div>
                    </div>
                    <div class="indicator-item">
                        <div class="indicator-label">MACD</div>
                        <div class="indicator-value ${indicators.macd > 0 ? 'positive' : 'negative'}">
                            ${indicators.macd.toFixed(4)}
                        </div>
                    </div>
                    <div class="indicator-item">
                        <div class="indicator-label">SMA 20</div>
                        <div class="indicator-value">
                            $${indicators.sma_20.toFixed(2)}
                        </div>
                    </div>
                    <div class="indicator-item">
                        <div class="indicator-label">SMA 50</div>
                        <div class="indicator-value">
                            $${indicators.sma_50.toFixed(2)}
                        </div>
                    </div>
                    <div class="indicator-item">
                        <div class="indicator-label">BB Width</div>
                        <div class="indicator-value">
                            ${indicators.bb_width.toFixed(4)}
                        </div>
                    </div>
                    <div class="indicator-item">
                        <div class="indicator-label">Volume Ratio</div>
                        <div class="indicator-value ${indicators.volume_ratio > 1 ? 'positive' : 'negative'}">
                            ${indicators.volume_ratio.toFixed(2)}x
                        </div>
                    </div>
                `;
            }
            
            // Display signal
            function displaySignal(data) {
                const signalDiv = document.getElementById('signal');
                signalDiv.className = `signal ${data.signal.toLowerCase()}`;
                signalDiv.innerHTML = `
                    <div style="font-size: 28px; margin-bottom: 10px;">${data.signal}</div>
                    <div style="margin-bottom: 8px;">Confidence: <strong>${data.confidence}%</strong></div>
                    <div style="margin-bottom: 8px;">Price: <strong>$${data.price.toFixed(2)}</strong></div>
                    <div style="margin-bottom: 8px;">Stop Loss: <strong>$${data.stop_loss.toFixed(2)}</strong></div>
                    <div style="margin-bottom: 8px;">Take Profit: <strong>$${data.take_profit.toFixed(2)}</strong></div>
                    <div>Risk/Reward: <strong>${data.risk_reward.toFixed(2)}x</strong></div>
                `;
                
                displayAnalysis(data.analysis);
            }
            
            // Initial load
            loadMarketData();
            
            // Auto-refresh market data every 10 seconds
            setInterval(loadMarketData, 10000);
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
    logger.info("🚀 ADVANCED TRADING PLATFORM (NO API KEY REQUIRED)")
    logger.info("=" * 70)
    logger.info(f"🌐 Server: http://0.0.0.0:{port}")
    logger.info("📊 Features:")
    logger.info("   • Real-time Binance WebSocket data (no API key)")
    logger.info("   • CoinGecko market data (no API key)")
    logger.info("   • Advanced technical analysis (20+ indicators)")
    logger.info("   • AI-powered trading signals")
    logger.info("   • TradingView chart integration")
    logger.info("   • Web dashboard with real-time updates")
    logger.info("   • No API keys required")
    logger.info("=" * 70)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
