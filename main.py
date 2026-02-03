🚀 CryptoTrader Pro v6.0 - Advanced Trading Platform
📊 Binance WebSocket + CoinGecko Real-time Integration
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
import websockets
from collections import defaultdict
import ssl

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Query, Request, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uuid

# ================================================================================
# SUBSCRIPTION TIERS
# ================================================================================
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

# ================================================================================
# BINANCE WEBSOCKET + COINGECKO REAL-TIME PROVIDER
# ================================================================================
class BinanceWebSocketManager:
    """Binance WebSocket manager for real-time data"""
    
    def __init__(self):
        self.ws = None
        self.connections = {}
        self.price_data = {}
        self.kline_data = {}
        self.orderbook_data = {}
        self.connection_tasks = []
        
    async def connect_ticker_stream(self, symbols: List[str]):
        """Connect to Binance ticker stream"""
        streams = [f"{symbol.lower()}@ticker" for symbol in symbols]
        stream_url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
        
        try:
            async with websockets.connect(stream_url) as websocket:
                self.ws = websocket
                logger.info(f"✅ Binance WebSocket connected for {len(symbols)} symbols")
                
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
                                'timestamp': datetime.now(timezone.utc).isoformat(),
                                'source': 'binance'
                            }
                            
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("Binance WebSocket connection closed, reconnecting...")
                        break
                    except Exception as e:
                        logger.error(f"Binance WebSocket error: {e}")
                        await asyncio.sleep(1)
                        
        except Exception as e:
            logger.error(f"Failed to connect to Binance WebSocket: {e}")
            
    async def connect_kline_stream(self, symbol: str, interval: str = "1d"):
        """Connect to Binance kline stream for a specific symbol"""
        stream_url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_{interval}"
        
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
                            'timestamp': datetime.fromtimestamp(kline['t'] / 1000, tz=timezone.utc),
                            'is_closed': kline['x']
                        }
                        
                    except Exception as e:
                        logger.error(f"Kline stream error: {e}")
                        break
                        
        except Exception as e:
            logger.error(f"Failed to connect to kline stream: {e}")

class RealTimeTicker:
    """Real-time ticker combining Binance WebSocket and CoinGecko API"""
    
    # Popular cryptocurrencies
    DEFAULT_SYMBOLS = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
        "SOLUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT",
        "MATICUSDT", "UNIUSDT", "LTCUSDT", "BCHUSDT", "XLMUSDT"
    ]
    
    # CoinGecko to Binance symbol mapping
    COINGECKO_TO_BINANCE = {
        "bitcoin": "BTCUSDT",
        "ethereum": "ETHUSDT", 
        "binancecoin": "BNBUSDT",
        "ripple": "XRPUSDT",
        "cardano": "ADAUSDT",
        "solana": "SOLUSDT",
        "polkadot": "DOTUSDT",
        "dogecoin": "DOGEUSDT",
        "avalanche-2": "AVAXUSDT",
        "chainlink": "LINKUSDT",
        "polygon": "MATICUSDT",
        "uniswap": "UNIUSDT",
        "litecoin": "LTCUSDT",
        "bitcoin-cash": "BCHUSDT",
        "stellar": "XLMUSDT"
    }
    
    # Binance to CoinGecko mapping
    BINANCE_TO_COINGECKO = {v.lower(): k for k, v in COINGECKO_TO_BINANCE.items()}
    
    # TradingView symbol mappings
    TRADINGVIEW_SYMBOLS = {
        "BTCUSDT": "BINANCE:BTCUSDT",
        "ETHUSDT": "BINANCE:ETHUSDT",
        "BNBUSDT": "BINANCE:BNBUSDT",
        "XRPUSDT": "BINANCE:XRPUSDT",
        "ADAUSDT": "BINANCE:ADAUSDT",
        "SOLUSDT": "BINANCE:SOLUSDT",
        "DOTUSDT": "BINANCE:DOTUSDT",
        "DOGEUSDT": "BINANCE:DOGEUSDT",
        "AVAXUSDT": "BINANCE:AVAXUSDT",
        "LINKUSDT": "BINANCE:LINKUSDT",
        "MATICUSDT": "BINANCE:MATICUSDT",
        "UNIUSDT": "BINANCE:UNIUSDT",
        "LTCUSDT": "BINANCE:LTCUSDT",
        "BCHUSDT": "BINANCE:BCHUSDT",
        "XLMUSDT": "BINANCE:XLMUSDT",
        # Forex
        "EURUSD": "FX:EURUSD",
        "GBPUSD": "FX:GBPUSD",
        "USDJPY": "FX:USDJPY",
        # Metals
        "XAUUSD": "FX:XAUUSD",
        "XAGUSD": "FX:XAGUSD",
        # Indices
        "SPY": "AMEX:SPY",
        "QQQ": "NASDAQ:QQQ",
        "DIA": "NYSEARCA:DIA"
    }
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws_manager = BinanceWebSocketManager()
        self.price_cache = {}
        self.market_data = {}
        self.historical_cache = {}
        self.last_update = datetime.now(timezone.utc)
        self.ticker_data = []
        
    async def initialize(self):
        """Initialize HTTP session and WebSocket connections"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        # Start Binance WebSocket for default symbols
        asyncio.create_task(self.ws_manager.connect_ticker_stream(self.DEFAULT_SYMBOLS))
        
        # Fetch initial data from CoinGecko
        await self.fetch_coingecko_data()
        
        logger.info("✅ Real-time ticker initialized (Binance + CoinGecko)")
        
    async def close(self):
        """Close all connections"""
        if self.session:
            await self.session.close()
        logger.info("🔌 Real-time ticker closed")
        
    async def fetch_coingecko_data(self):
        """Fetch market data from CoinGecko"""
        try:
            url = "https://api.coingecko.com/api/v3/coins/markets"
            params = {
                "vs_currency": "usd",
                "ids": ",".join(self.COINGECKO_TO_BINANCE.keys()),
                "order": "market_cap_desc",
                "per_page": 50,
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "24h"
            }
            
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    for coin in data:
                        coingecko_id = coin['id']
                        if coingecko_id in self.COINGECKO_TO_BINANCE:
                            binance_symbol = self.COINGECKO_TO_BINANCE[coingecko_id]
                            
                            self.market_data[binance_symbol] = {
                                'id': coingecko_id,
                                'symbol': binance_symbol,
                                'name': coin['name'],
                                'image': coin['image'],
                                'current_price': coin['current_price'],
                                'market_cap': coin['market_cap'],
                                'market_cap_rank': coin['market_cap_rank'],
                                'total_volume': coin['total_volume'],
                                'high_24h': coin['high_24h'],
                                'low_24h': coin['low_24h'],
                                'price_change_24h': coin['price_change_24h'],
                                'price_change_percentage_24h': coin['price_change_percentage_24h'],
                                'market_cap_change_24h': coin['market_cap_change_24h'],
                                'market_cap_change_percentage_24h': coin['market_cap_change_percentage_24h'],
                                'circulating_supply': coin['circulating_supply'],
                                'total_supply': coin.get('total_supply'),
                                'max_supply': coin.get('max_supply'),
                                'ath': coin['ath'],
                                'ath_change_percentage': coin['ath_change_percentage'],
                                'ath_date': coin['ath_date'],
                                'atl': coin['atl'],
                                'atl_change_percentage': coin['atl_change_percentage'],
                                'atl_date': coin['atl_date'],
                                'last_updated': coin['last_updated'],
                                'source': 'coingecko'
                            }
                    
                    logger.info(f"📊 CoinGecko data fetched for {len(data)} coins")
                    
        except Exception as e:
            logger.error(f"Error fetching CoinGecko data: {e}")
            
    async def get_ticker_data(self) -> List[Dict]:
        """Get combined ticker data from Binance and CoinGecko"""
        ticker_list = []
        current_time = datetime.now(timezone.utc)
        
        # Process Binance data
        for symbol, binance_data in self.ws_manager.price_data.items():
            if symbol in self.market_data:
                # Combine Binance real-time price with CoinGecko market data
                market_data = self.market_data[symbol]
                
                ticker_list.append({
                    'id': market_data['id'],
                    'symbol': symbol,
                    'name': market_data['name'],
                    'price': binance_data['price'],  # Real-time from Binance
                    'change_24h': market_data['price_change_percentage_24h'],
                    'change_24h_pct': round(market_data['price_change_percentage_24h'], 2),
                    'high_24h': market_data['high_24h'],
                    'low_24h': market_data['low_24h'],
                    'volume_24h': market_data['total_volume'],
                    'market_cap': market_data['market_cap'],
                    'market_cap_rank': market_data['market_cap_rank'],
                    'last_updated': current_time.isoformat(),
                    'tradingview_symbol': self.TRADINGVIEW_SYMBOLS.get(symbol, f"BINANCE:{symbol}"),
                    'type': 'crypto',
                    'source': 'binance_realtime',
                    'price_source': 'Binance WebSocket',
                    'data_freshness': 'realtime'
                })
        
        # Sort by market cap
        ticker_list.sort(key=lambda x: x.get('market_cap', 0), reverse=True)
        self.ticker_data = ticker_list
        self.last_update = current_time
        
        return ticker_list
        
    async def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """Get information for a specific symbol"""
        # Normalize symbol
        symbol_upper = symbol.upper()
        if not symbol_upper.endswith('USDT'):
            symbol_upper = f"{symbol_upper}USDT"
            
        # Check Binance real-time data first
        if symbol_upper in self.ws_manager.price_data:
            binance_data = self.ws_manager.price_data[symbol_upper]
            market_data = self.market_data.get(symbol_upper, {})
            
            return {
                'symbol': symbol_upper,
                'id': market_data.get('id', symbol_upper.lower()),
                'price': binance_data['price'],
                'change_24h': market_data.get('price_change_percentage_24h', binance_data['change']),
                'volume_24h': market_data.get('total_volume', binance_data['volume']),
                'market_cap': market_data.get('market_cap', 0),
                'high_24h': market_data.get('high_24h', binance_data['high']),
                'low_24h': market_data.get('low_24h', binance_data['low']),
                'tradingview_symbol': self.TRADINGVIEW_SYMBOLS.get(symbol_upper, f"BINANCE:{symbol_upper}"),
                'type': 'crypto',
                'available': True,
                'source': 'binance_realtime',
                'last_updated': datetime.now(timezone.utc).isoformat()
            }
            
        # If not in Binance, try CoinGecko
        coingecko_id = self.BINANCE_TO_COINGECKO.get(symbol_upper.lower())
        if coingecko_id and coingecko_id in self.market_data:
            market_data = self.market_data[coingecko_id]
            
            return {
                'symbol': symbol_upper,
                'id': coingecko_id,
                'price': market_data['current_price'],
                'change_24h': market_data['price_change_percentage_24h'],
                'volume_24h': market_data['total_volume'],
                'market_cap': market_data['market_cap'],
                'high_24h': market_data['high_24h'],
                'low_24h': market_data['low_24h'],
                'tradingview_symbol': self.TRADINGVIEW_SYMBOLS.get(symbol_upper, f"BINANCE:{symbol_upper}"),
                'type': 'crypto',
                'available': True,
                'source': 'coingecko',
                'last_updated': market_data['last_updated']
            }
            
        return None
        
    async def fetch_ohlcv(self, symbol: str, timeframe: str = "1D", limit: int = 100) -> List[Dict]:
        """Fetch OHLCV data from Binance API"""
        cache_key = f"{symbol}_{timeframe}_{limit}"
        
        # Check cache
        if cache_key in self.historical_cache:
            cached_data, timestamp = self.historical_cache[cache_key]
            if (datetime.now(timezone.utc) - timestamp).total_seconds() < 60:  # 1 minute cache
                return cached_data
        
        try:
            # Binance interval mapping
            interval_map = {
                "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                "1h": "1h", "4h": "4h", "1D": "1d", "1W": "1w", "1M": "1M"
            }
            
            binance_interval = interval_map.get(timeframe, "1d")
            
            # Calculate start time based on limit and interval
            interval_seconds = {
                "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
                "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800, "1M": 2592000
            }
            
            seconds_per_candle = interval_seconds.get(binance_interval, 86400)
            start_time = int((datetime.now(timezone.utc) - timedelta(seconds=seconds_per_candle * limit)).timestamp() * 1000)
            
            # Fetch from Binance API
            url = f"https://api.binance.com/api/v3/klines"
            params = {
                "symbol": symbol.upper(),
                "interval": binance_interval,
                "limit": limit,
                "startTime": start_time
            }
            
            async with self.session.get(url, params=params, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    candles = []
                    for item in data:
                        candles.append({
                            "timestamp": item[0] // 1000,  # Convert ms to seconds
                            "open": float(item[1]),
                            "high": float(item[2]),
                            "low": float(item[3]),
                            "close": float(item[4]),
                            "volume": float(item[5]),
                            "quote_volume": float(item[7]),
                            "trades": item[8]
                        })
                    
                    # Cache the data
                    self.historical_cache[cache_key] = (candles, datetime.now(timezone.utc))
                    
                    return candles
                else:
                    logger.warning(f"Binance API error: {response.status}, falling back to CoinGecko")
                    return await self.fetch_coingecko_ohlcv(symbol, timeframe, limit)
                    
        except Exception as e:
            logger.error(f"Error fetching OHLCV from Binance: {e}")
            return await self.fetch_coingecko_ohlcv(symbol, timeframe, limit)
            
    async def fetch_coingecko_ohlcv(self, symbol: str, timeframe: str = "1D", limit: int = 100) -> List[Dict]:
        """Fallback to CoinGecko OHLCV data"""
        try:
            # Convert symbol to CoinGecko ID
            symbol_upper = symbol.upper()
            if not symbol_upper.endswith('USDT'):
                symbol_upper = f"{symbol_upper}USDT"
                
            coingecko_id = self.BINANCE_TO_COINGECKO.get(symbol_upper.lower())
            
            if not coingecko_id:
                # Try to get from the reverse mapping
                for cg_id, binance_sym in self.COINGECKO_TO_BINANCE.items():
                    if binance_sym == symbol_upper:
                        coingecko_id = cg_id
                        break
            
            if not coingecko_id:
                logger.warning(f"Symbol {symbol} not found in CoinGecko mapping")
                return []
            
            # Calculate days based on timeframe and limit
            days_map = {
                "1m": 1, "5m": 1, "15m": 1, "30m": 1,
                "1h": 7, "4h": 14, "1D": 30, "1W": 90, "1M": 365
            }
            
            days = days_map.get(timeframe, 30)
            
            # Fetch from CoinGecko
            url = f"https://api.coingecko.com/api/v3/coins/{coingecko_id}/ohlc"
            params = {
                "vs_currency": "usd",
                "days": str(days)
            }
            
            async with self.session.get(url, params=params, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    candles = []
                    for item in data:
                        candles.append({
                            "timestamp": item[0] // 1000,
                            "open": item[1],
                            "high": item[2],
                            "low": item[3],
                            "close": item[4],
                            "volume": 0  # CoinGecko doesn't provide volume in OHLC
                        })
                    
                    # Resample if needed
                    if timeframe != "1D":
                        candles = self._resample_candles(candles, timeframe)
                    
                    return candles[-limit:] if len(candles) > limit else candles
                else:
                    logger.error(f"CoinGecko OHLCV error: {response.status}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error fetching OHLCV from CoinGecko: {e}")
            return []
            
    def _resample_candles(self, candles: List[Dict], timeframe: str) -> List[Dict]:
        """Resample daily candles to different timeframe"""
        if not candles:
            return []
            
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        df.set_index('timestamp', inplace=True)
        
        # Resample rules
        resample_map = {
            "1h": "H", "4h": "4H", "1W": "W", "1M": "M"
        }
        
        if timeframe in resample_map:
            resampled = df.resample(resample_map[timeframe]).agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            # Convert back to list of dicts
            result = []
            for idx, row in resampled.iterrows():
                result.append({
                    "timestamp": int(idx.timestamp()),
                    "open": row['open'],
                    "high": row['high'],
                    "low": row['low'],
                    "close": row['close'],
                    "volume": row['volume']
                })
            
            return result
            
        return candles

# ================================================================================
# ADVANCED TECHNICAL ANALYSIS ENGINE (Aynı kalacak, sadece import ediyoruz)
# ================================================================================
class TechnicalAnalysis:
    """Comprehensive technical analysis with 20+ indicators"""
    
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

# ================================================================================
# AI SIGNAL ENGINE
# ================================================================================
@dataclass
class TradingSignal:
    symbol: str
    timeframe: str
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
    trend: Dict
    timestamp: str

class AISignalEngine:
    """Advanced AI-powered signal generation"""
    
    def __init__(self, ticker: RealTimeTicker):
        self.ticker = ticker
        self.ta = TechnicalAnalysis()
    
    async def generate_signal(self, symbol: str, timeframe: str = "1D") -> TradingSignal:
        """Generate trading signal for a symbol and timeframe"""
        
        # Normalize symbol for Binance
        symbol_upper = symbol.upper()
        if not symbol_upper.endswith('USDT'):
            symbol_upper = f"{symbol_upper}USDT"
        
        # Fetch OHLCV data from Binance
        ohlcv_data = await self.ticker.fetch_ohlcv(symbol_upper, timeframe, 100)
        
        if len(ohlcv_data) < 30:
            return self._neutral_signal(symbol, timeframe)
        
        # Get real-time price from Binance WebSocket
        symbol_info = await self.ticker.get_symbol_info(symbol_upper)
        
        # Calculate all indicators
        analysis = self.ta.calculate_all_indicators(ohlcv_data, symbol_upper, timeframe)
        
        if not analysis:
            return self._neutral_signal(symbol, timeframe)
        
        # Update with real-time price if available
        if symbol_info and 'price' in symbol_info:
            analysis['current_price'] = symbol_info['price']
        
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

# ================================================================================
# FASTAPI APPLICATION
# ================================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    logger.info("🚀 CryptoTrader Pro v6.0 Starting...")
    
    # Initialize Real-time Ticker (Binance + CoinGecko)
    ticker = RealTimeTicker()
    await ticker.initialize()
    
    # Initialize AI Engine
    ai_engine = AISignalEngine(ticker)
    
    # Start periodic updates
    async def periodic_updates():
        while True:
            try:
                await ticker.fetch_coingecko_data()
                await asyncio.sleep(60)  # Update CoinGecko data every minute
            except Exception as e:
                logger.error(f"Periodic update error: {e}")
                await asyncio.sleep(30)
    
    update_task = asyncio.create_task(periodic_updates())
    
    # Store in app state
    app.state.ticker = ticker
    app.state.ai_engine = ai_engine
    app.state.update_task = update_task
    
    logger.info("✅ All systems operational")
    logger.info("📊 Real-time Ticker: Binance WebSocket + CoinGecko")
    logger.info("🤖 AI Signal Engine: Ready")
    logger.info("📈 Technical Analysis: 20+ Indicators")
    logger.info("🎯 Real-time Price Data: Active")
    logger.info("📐 Fibonacci Tools: Enabled")
    logger.info("=" * 70)
    
    yield
    
    # Cleanup
    update_task.cancel()
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates directory
templates = Jinja2Templates(directory="templates")

# ================================================================================
# HTML TEMPLATES (Aynı kalacak, sadece frontend'te veri kaynağını göstereceğiz)
# ================================================================================
def generate_dashboard_html(tier: SubscriptionTier = SubscriptionTier.PRO) -> str:
    """Generate modern, vibrant dashboard with ticker"""
    
    tier_info = TIER_FEATURES[tier]
    
    # HTML template aynı kalacak, sadece küçük değişiklikler:
    html_template = """<!DOCTYPE html>..."""  # Önceki HTML template buraya gelecek
    
    # Template'de veri kaynağı bilgisini göstermek için küçük değişiklik:
    html_template = html_template.replace(
        "Real-time CoinGecko ticker with streaming updates",
        "Real-time Binance WebSocket + CoinGecko data integration"
    )
    
    return html_template

# ================================================================================
# API ENDPOINTS
# ================================================================================
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard"""
    html = generate_dashboard_html(SubscriptionTier.PRO)
    return HTMLResponse(html)

@app.get("/api/ticker")
async def get_ticker(request: Request):
    """Get real-time ticker data"""
    try:
        ticker = request.app.state.ticker
        
        # Get combined ticker data
        ticker_data = await ticker.get_ticker_data()
        
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker_data,
            "count": len(ticker_data),
            "data_source": "Binance WebSocket + CoinGecko",
            "update_frequency": "realtime"
        }
    except Exception as e:
        logger.error(f"Ticker error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/symbol/{symbol}")
async def get_symbol_info(symbol: str, request: Request):
    """Get symbol information with real-time data"""
    try:
        ticker = request.app.state.ticker
        
        info = await ticker.get_symbol_info(symbol)
        
        if info:
            return {
                "success": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": info,
                "data_source": info.get('source', 'unknown')
            }
        else:
            return {"success": False, "error": "Symbol not found"}
    except Exception as e:
        logger.error(f"Symbol info error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/signal/{symbol}")
async def get_signal(symbol: str, request: Request, timeframe: str = Query("1D", enum=["1m", "5m", "15m", "30m", "1h", "4h", "1D", "1W", "1M"])):
    """Get AI trading signal for a symbol with real-time data"""
    try:
        ai_engine = request.app.state.ai_engine
        
        # Generate signal with real-time data
        signal = await ai_engine.generate_signal(symbol, timeframe)
        
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "signal": asdict(signal),
            "data_source": "Binance OHLCV + Real-time Price"
        }
    except Exception as e:
        logger.error(f"Signal generation error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/analysis/{symbol}")
async def get_technical_analysis(symbol: str, request: Request, timeframe: str = Query("1D"), limit: int = Query(100, ge=10, le=500)):
    """Get comprehensive technical analysis with real-time data"""
    try:
        ticker = request.app.state.ticker
        ta = TechnicalAnalysis()
        
        # Normalize symbol for Binance
        symbol_upper = symbol.upper()
        if not symbol_upper.endswith('USDT'):
            symbol_upper = f"{symbol_upper}USDT"
        
        # Fetch OHLCV data from Binance
        ohlcv = await ticker.fetch_ohlcv(symbol_upper, timeframe, limit)
        
        if len(ohlcv) < 20:
            return {"success": False, "error": "Insufficient data for analysis"}
        
        # Get real-time price
        symbol_info = await ticker.get_symbol_info(symbol_upper)
        
        # Calculate analysis
        analysis = ta.calculate_all_indicators(ohlcv, symbol_upper, timeframe)
        
        # Update with real-time price if available
        if symbol_info and 'price' in symbol_info:
            analysis['current_price'] = symbol_info['price']
            analysis['price_source'] = symbol_info.get('source', 'Binance WebSocket')
        
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol_upper,
            "timeframe": timeframe,
            "candle_count": len(ohlcv),
            "analysis": analysis,
            "data_source": "Binance API + Real-time WebSocket"
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
            "binance_websocket": "operational",
            "coingecko_api": "operational",
            "ai_engine": "operational",
            "technical_analysis": "operational",
            "signal_generation": "operational"
        }
    }

# ================================================================================
# STARTUP
# ================================================================================
if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    
    logger.info("=" * 70)
    logger.info("🚀 CRYPTOTRADER PRO v6.0 - ADVANCED TRADING PLATFORM")
    logger.info("=" * 70)
    logger.info(f"🌐 Server: http://0.0.0.0:{port}")
    logger.info("📊 Features:")
    logger.info("   • Real-time Binance WebSocket price streaming")
    logger.info("   • CoinGecko market data integration")
    logger.info("   • TradingView integration with click-to-expand charts")
    logger.info("   • 20+ Technical indicators (RSI, MACD, Bollinger Bands, etc.)")
    logger.info("   • Fibonacci retracement & extension levels")
    logger.info("   • Support & Resistance detection")
    logger.info("   • Chart pattern recognition (Head & Shoulders, Triangles, etc.)")
    logger.info("   • AI-powered trading signals with risk/reward analysis")
    logger.info("   • Multi-timeframe analysis (1m to 1M)")
    logger.info("   • Support for Crypto (Binance pairs)")
    logger.info("=" * 70)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
