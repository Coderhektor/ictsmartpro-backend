import time 
import json
import asyncio
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, validator, Field
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
import logging
from contextlib import asynccontextmanager
import os
import aiohttp
import websockets
from collections import defaultdict, deque
import hashlib
from enum import Enum
import psutil
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

# ==========================================
# ENHANCED CONFIGURATION
# ==========================================
class Config:
    # Binance Configuration
    BINANCE_BASE_URL = "https://api.binance.com"
    BINANCE_WS_URL = "wss://stream.binance.com:9443"
    
    # CoinGecko Configuration
    COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
    
    # Cache Configuration
    CACHE_TTL = {
        'ticker': 2,  # 2 seconds for real-time data
        'klines': 60,  # 1 minute for OHLCV
        'market': 30,  # 30 seconds for market overview
        'analysis': 10,  # 10 seconds for analysis
        'signal': 5,   # 5 seconds for signals
        'orderbook': 3  # 3 seconds for order book
    }
    
    # Rate Limiting
    RATE_LIMITS = {
        'binance': {
            'requests': 1200,
            'per_minute': 60
        },
        'coingecko': {
            'requests': 100,
            'per_minute': 60
        }
    }
    
    # Trading Parameters
    TRADING = {
        'default_quantity': 0.001,
        'stop_loss_pct': 0.02,
        'take_profit_pct': 0.04,
        'max_position_size': 0.01,
        'risk_per_trade': 0.01  # 1% risk per trade
    }
    
    # WebSocket Configuration
    WS_CONFIG = {
        'reconnect_delay': 5,
        'max_reconnect_attempts': 10,
        'ping_interval': 30,
        'ping_timeout': 10
    }
    
    # Symbols Configuration
    SYMBOLS = {
        'major': ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"],
        'mid': ["SOLUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT"],
        'minor': ["MATICUSDT", "UNIUSDT", "LTCUSDT", "ATOMUSDT", "ETCUSDT"]
    }
    
    # Timeframes
    TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']
    
    # Technical Analysis
    TA_CONFIG = {
        'min_candles': 100,
        'indicators': {
            'sma': [5, 10, 20, 50, 100, 200],
            'ema': [9, 12, 26, 50],
            'rsi': 14,
            'macd': [12, 26, 9],
            'bb': 20,
            'stochastic': [14, 3, 3],
            'atr': 14,
            'obv': True,
            'vwap': True
        }
    }
    
    # ML Configuration
    ML_CONFIG = {
        'retrain_interval': 3600,  # 1 hour
        'min_data_points': 200,
        'lookback_periods': 100,
        'lookahead': 5,
        'threshold': 0.01
    }

# ==========================================
# ENHANCED LOGGING
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('trading_platform.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Additional loggers
ws_logger = logging.getLogger('websocket')
data_logger = logging.getLogger('data')
analysis_logger = logging.getLogger('analysis')

# ==========================================
# ENHANCED MODELS
# ==========================================
class TimeFrame(str, Enum):
    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H2 = "2h"
    H4 = "4h"
    H6 = "6h"
    H8 = "8h"
    H12 = "12h"
    D1 = "1d"
    D3 = "3d"
    W1 = "1w"
    MTH1 = "1M"

class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"

class AnalyzeRequest(BaseModel):
    symbol: str = Field("BTCUSDT", pattern="^[A-Z0-9]{3,10}USDT$")
    timeframe: TimeFrame = TimeFrame.H1
    indicators: List[str] = Field(default=["RSI", "MACD", "BB", "SMA", "EMA"])
    
    @validator('symbol')
    def validate_symbol(cls, v):
        return v.upper()

class TradeRequest(BaseModel):
    symbol: str = Field("BTCUSDT", pattern="^[A-Z0-9]{3,10}USDT$")
    side: TradeSide
    quantity: float = Field(0.001, gt=0, le=1000)
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = Field(None, gt=0)
    stop_loss: Optional[float] = Field(None, gt=0)
    take_profit: Optional[float] = Field(None, gt=0)
    
    @validator('symbol')
    def validate_symbol(cls, v):
        return v.upper()

# ==========================================
# ADVANCED WEB SOCKET MANAGER
# ==========================================
class AdvancedWebSocketManager:
    """Advanced WebSocket manager with reconnection, heartbeat, and data validation"""
    
    def __init__(self):
        self.connections = {}
        self.price_data = {}
        self.kline_data = {}
        self.ticker_data = []
        self.orderbook_data = {}
        self.market_data = {}
        self._connection_status = {}
        self._subscriptions = defaultdict(set)
        self._last_update = {}
        self._data_queues = defaultdict(deque)
        
    async def _validate_ws_data(self, data: Dict, data_type: str) -> bool:
        """Validate WebSocket data"""
        try:
            if data_type == 'ticker':
                required_fields = ['s', 'c', 'P', 'h', 'l', 'v', 'q']
                return all(field in data for field in required_fields)
            elif data_type == 'kline':
                required_fields = ['t', 'o', 'h', 'l', 'c', 'v', 'x']
                return 'k' in data and all(field in data['k'] for field in required_fields)
            elif data_type == 'depth':
                required_fields = ['bids', 'asks', 'u']
                return all(field in data for field in required_fields)
            return False
        except Exception:
            return False
    
    async def connect_multi_stream(self, streams: List[str], stream_type: str = 'ticker'):
        """Connect to multiple streams"""
        stream_url = f"{Config.BINANCE_WS_URL}/stream?streams={'/'.join(streams)}"
        connection_id = hashlib.md5(stream_url.encode()).hexdigest()[:8]
        
        reconnect_attempts = 0
        while reconnect_attempts < Config.WS_CONFIG['max_reconnect_attempts']:
            try:
                async with websockets.connect(
                    stream_url,
                    ping_interval=Config.WS_CONFIG['ping_interval'],
                    ping_timeout=Config.WS_CONFIG['ping_timeout']
                ) as websocket:
                    
                    self._connection_status[connection_id] = 'connected'
                    ws_logger.info(f"✅ WebSocket connected: {stream_type} ({len(streams)} streams)")
                    reconnect_attempts = 0
                    
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            if 'data' in data:
                                data = data['data']
                            
                            if stream_type == 'ticker' and await self._validate_ws_data(data, 'ticker'):
                                await self._process_ticker_data(data)
                                
                            elif stream_type == 'kline' and await self._validate_ws_data(data, 'kline'):
                                await self._process_kline_data(data)
                                
                            elif stream_type == 'depth' and await self._validate_ws_data(data, 'depth'):
                                await self._process_depth_data(data)
                                
                        except json.JSONDecodeError as e:
                            ws_logger.error(f"JSON decode error: {e}")
                        except Exception as e:
                            ws_logger.error(f"Message processing error: {e}")
                            
            except websockets.exceptions.ConnectionClosed as e:
                self._connection_status[connection_id] = 'disconnected'
                reconnect_attempts += 1
                delay = Config.WS_CONFIG['reconnect_delay'] * reconnect_attempts
                ws_logger.warning(f"Connection closed, reconnecting in {delay}s... (Attempt {reconnect_attempts})")
                await asyncio.sleep(delay)
            except Exception as e:
                ws_logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(Config.WS_CONFIG['reconnect_delay'])
    
    async def _process_ticker_data(self, data: Dict):
        """Process ticker data with validation"""
        symbol = data['s']
        current_time = datetime.now(timezone.utc)
        
        self.price_data[symbol] = {
            'symbol': symbol,
            'price': float(data['c']),
            'change_24h': float(data['P']),
            'change_amount': float(data['p']),
            'high_24h': float(data['h']),
            'low_24h': float(data['l']),
            'volume': float(data['v']),
            'quote_volume': float(data['q']),
            'open_price': float(data['o']),
            'prev_close': float(data['c']) - float(data['p']),
            'weighted_avg_price': float(data['w']),
            'last_update_id': data.get('u', 0),
            'timestamp': current_time.isoformat(),
            'source': 'binance_ws',
            'validated': True
        }
        
        # Update market data
        self.market_data[symbol] = self.price_data[symbol]
        
        # Add to queue for history
        if symbol not in self._data_queues:
            self._data_queues[symbol] = deque(maxlen=1000)
        self._data_queues[symbol].append(self.price_data[symbol])
        
        self._last_update[symbol] = current_time.timestamp()
    
    async def _process_kline_data(self, data: Dict):
        """Process kline data"""
        kline = data['k']
        symbol = kline['s']
        interval = kline['i']
        
        candle_data = {
            'symbol': symbol,
            'interval': interval,
            'open_time': datetime.fromtimestamp(kline['t'] / 1000, tz=timezone.utc),
            'open': float(kline['o']),
            'high': float(kline['h']),
            'low': float(kline['l']),
            'close': float(kline['c']),
            'volume': float(kline['v']),
            'close_time': datetime.fromtimestamp(kline['T'] / 1000, tz=timezone.utc),
            'quote_volume': float(kline['q']),
            'trades': kline['n'],
            'taker_buy_base': float(kline['V']),
            'taker_buy_quote': float(kline['Q']),
            'is_closed': kline['x'],
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        key = f"{symbol}_{interval}"
        self.kline_data[key] = candle_data
    
    async def _process_depth_data(self, data: Dict):
        """Process order book depth data"""
        symbol = data['s'].lower()
        
        self.orderbook_data[symbol] = {
            'last_update_id': data['u'],
            'bids': [[float(price), float(qty)] for price, qty in data['b'][:20]],
            'asks': [[float(price), float(qty)] for price, qty in data['a'][:20]],
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    async def get_historical_prices(self, symbol: str, limit: int = 100) -> List[Dict]:
        """Get historical price data from queue"""
        if symbol in self._data_queues:
            return list(self._data_queues[symbol])[-limit:]
        return []
    
    async def get_realtime_price(self, symbol: str) -> Optional[Dict]:
        """Get real-time price with validation"""
        if symbol in self.price_data:
            data = self.price_data[symbol]
            # Check if data is fresh (less than 5 seconds old)
            if time.time() - self._last_update.get(symbol, 0) < 5:
                return data
        return None
    
    async def update_ticker_list(self):
        """Update ticker list sorted by volume"""
        ticker_list = []
        for symbol, data in self.price_data.items():
            if data.get('validated', False):
                ticker_list.append({
                    'symbol': symbol,
                    'price': data['price'],
                    'change_24h': data['change_24h'],
                    'volume_24h': data['volume'],
                    'quote_volume_24h': data['quote_volume'],
                    'high_24h': data['high_24h'],
                    'low_24h': data['low_24h'],
                    'last_updated': data['timestamp'],
                    'validity_score': 1.0
                })
        
        ticker_list.sort(key=lambda x: x['quote_volume_24h'], reverse=True)
        self.ticker_data = ticker_list
    
    async def start_all_streams(self):
        """Start all required WebSocket streams"""
        # Start ticker streams for all symbols
        all_symbols = Config.SYMBOLS['major'] + Config.SYMBOLS['mid'] + Config.SYMBOLS['minor']
        stream_groups = [all_symbols[i:i+10] for i in range(0, len(all_symbols), 10)]
        
        for group in stream_groups:
            streams = [f"{symbol.lower()}@ticker" for symbol in group]
            asyncio.create_task(self.connect_multi_stream(streams, 'ticker'))
        
        # Start kline streams for major symbols
        for symbol in Config.SYMBOLS['major'][:5]:
            for interval in ['1m', '5m', '15m', '1h', '4h']:
                stream = f"{symbol.lower()}@kline_{interval}"
                asyncio.create_task(self.connect_multi_stream([stream], 'kline'))
        
        # Start order book streams
        for symbol in Config.SYMBOLS['major'][:3]:
            streams = [
                f"{symbol.lower()}@depth20@100ms",
                f"{symbol.lower()}@aggTrade"
            ]
            asyncio.create_task(self.connect_multi_stream(streams, 'depth'))
        
        # Start periodic ticker list updates
        asyncio.create_task(self._periodic_updates())
        
        ws_logger.info(f"Started WebSocket streams for {len(all_symbols)} symbols")
    
    async def _periodic_updates(self):
        """Periodic updates and maintenance"""
        while True:
            await self.update_ticker_list()
            
            # Clean up old data
            current_time = time.time()
            old_symbols = []
            for symbol, last_update in self._last_update.items():
                if current_time - last_update > 300:  # 5 minutes
                    old_symbols.append(symbol)
            
            for symbol in old_symbols:
                if symbol in self.price_data:
                    del self.price_data[symbol]
            
            await asyncio.sleep(10)

# ==========================================
# ADVANCED TECHNICAL ANALYSIS
# ==========================================
class AdvancedTechnicalAnalysis:
    """Advanced technical analysis with multiple indicators"""
    
    @staticmethod
    def calculate_all_indicators(candles: List[Dict], symbol: str, timeframe: str) -> Dict:
        """Calculate comprehensive technical indicators"""
        try:
            if not candles or len(candles) < 20:
                return None
            
            df = pd.DataFrame(candles)
            
            # Ensure we have required columns
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            df.columns = df.columns.str.lower()
            
            # Rename columns if needed
            col_mapping = {
                'open': 'open', 'high': 'high', 'low': 'low', 
                'close': 'close', 'volume': 'volume'
            }
            
            for req in required_cols:
                if req not in df.columns:
                    # Try to find similar columns
                    for col in df.columns:
                        if req in col:
                            col_mapping[req] = col
                            break
            
            # Calculate basic indicators
            current_price = float(df[col_mapping['close']].iloc[-1])
            price_24h_ago = float(df[col_mapping['close']].iloc[-24]) if len(df) > 24 else current_price
            change_24h = ((current_price - price_24h_ago) / price_24h_ago * 100) if price_24h_ago > 0 else 0
            
            # Simple moving averages
            closes = df[col_mapping['close']].astype(float)
            sma_20 = closes.rolling(window=20).mean().iloc[-1]
            sma_50 = closes.rolling(window=50).mean().iloc[-1]
            sma_200 = closes.rolling(window=200).mean().iloc[-1] if len(df) >= 200 else None
            
            # Exponential moving averages
            ema_12 = closes.ewm(span=12).mean().iloc[-1]
            ema_26 = closes.ewm(span=26).mean().iloc[-1]
            
            # RSI (Relative Strength Index)
            delta = closes.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1] if not rsi.empty else 50
            
            # MACD
            ema_12 = closes.ewm(span=12).mean()
            ema_26 = closes.ewm(span=26).mean()
            macd_line = ema_12 - ema_26
            signal_line = macd_line.ewm(span=9).mean()
            macd_histogram = macd_line - signal_line
            
            # Bollinger Bands
            bb_upper = closes.rolling(window=20).mean() + (closes.rolling(window=20).std() * 2)
            bb_lower = closes.rolling(window=20).mean() - (closes.rolling(window=20).std() * 2)
            bb_middle = closes.rolling(window=20).mean()
            
            # Volume analysis
            volume = df[col_mapping['volume']].astype(float)
            volume_sma = volume.rolling(window=20).mean().iloc[-1]
            current_volume = volume.iloc[-1]
            volume_ratio = current_volume / volume_sma if volume_sma > 0 else 1
            
            # Support and Resistance levels (simplified)
            recent_highs = df[col_mapping['high']].astype(float).rolling(window=20).max().iloc[-1]
            recent_lows = df[col_mapping['low']].astype(float).rolling(window=20).min().iloc[-1]
            
            # Volatility (ATR approximation)
            high_low = df[col_mapping['high']].astype(float) - df[col_mapping['low']].astype(float)
            atr = high_low.rolling(window=14).mean().iloc[-1]
            
            # Trend analysis
            trend_score = 0
            if sma_20 > sma_50:
                trend_score += 1
            if current_price > sma_20:
                trend_score += 1
            if current_price > sma_50:
                trend_score += 1
            
            trend_map = {
                0: "STRONG_BEARISH",
                1: "BEARISH",
                2: "NEUTRAL",
                3: "BULLISH"
            }
            
            # Signal generation
            signals = {}
            signal_score = 0
            
            # RSI signal
            if current_rsi < 30:
                signals['rsi'] = "OVERSOLD"
                signal_score += 1
            elif current_rsi > 70:
                signals['rsi'] = "OVERBOUGHT"
                signal_score -= 1
            else:
                signals['rsi'] = "NEUTRAL"
            
            # MACD signal
            macd_value = macd_line.iloc[-1] if not macd_line.empty else 0
            signal_value = signal_line.iloc[-1] if not signal_line.empty else 0
            if macd_value > signal_value and macd_histogram.iloc[-1] > 0:
                signals['macd'] = "BULLISH"
                signal_score += 1
            elif macd_value < signal_value and macd_histogram.iloc[-1] < 0:
                signals['macd'] = "BEARISH"
                signal_score -= 1
            else:
                signals['macd'] = "NEUTRAL"
            
            # Bollinger Bands signal
            if current_price > bb_upper.iloc[-1]:
                signals['bb'] = "OVERBOUGHT"
                signal_score -= 1
            elif current_price < bb_lower.iloc[-1]:
                signals['bb'] = "OVERSOLD"
                signal_score += 1
            else:
                signals['bb'] = "NEUTRAL"
            
            # Volume signal
            if volume_ratio > 1.5:
                signals['volume'] = "HIGH_VOLUME"
                signal_score += 0.5
            elif volume_ratio < 0.5:
                signals['volume'] = "LOW_VOLUME"
                signal_score -= 0.5
            else:
                signals['volume'] = "NORMAL"
            
            # Overall signal
            if signal_score >= 2:
                overall_signal = "STRONG_BUY"
            elif signal_score >= 1:
                overall_signal = "BUY"
            elif signal_score <= -2:
                overall_signal = "STRONG_SELL"
            elif signal_score <= -1:
                overall_signal = "SELL"
            else:
                overall_signal = "NEUTRAL"
            
            # Calculate confidence
            confidence = min(abs(signal_score) * 25, 100)
            
            # Candlestick patterns (simplified)
            patterns = []
            if len(df) >= 3:
                last_close = closes.iloc[-1]
                last_open = float(df[col_mapping['open']].iloc[-1])
                prev_close = closes.iloc[-2]
                prev_open = float(df[col_mapping['open']].iloc[-2])
                
                # Bullish engulfing
                if (last_close > last_open and prev_close < prev_open and 
                    last_close > prev_open and last_open < prev_close):
                    patterns.append({"name": "Bullish Engulfing", "signal": "BULLISH", "confidence": 70})
                
                # Bearish engulfing
                if (last_close < last_open and prev_close > prev_open and 
                    last_close < prev_open and last_open > prev_close):
                    patterns.append({"name": "Bearish Engulfing", "signal": "BEARISH", "confidence": 70})
                
                # Doji
                body_size = abs(last_close - last_open)
                total_range = float(df[col_mapping['high']].iloc[-1]) - float(df[col_mapping['low']].iloc[-1])
                if total_range > 0 and body_size / total_range < 0.1:
                    patterns.append({"name": "Doji", "signal": "REVERSAL", "confidence": 60})
            
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "current_price": round(current_price, 4),
                "change_24h": round(change_24h, 2),
                "indicators": {
                    "sma_20": round(sma_20, 4),
                    "sma_50": round(sma_50, 4),
                    "sma_200": round(sma_200, 4) if sma_200 else None,
                    "ema_12": round(ema_12, 4),
                    "ema_26": round(ema_26, 4),
                    "rsi": round(current_rsi, 2),
                    "macd_line": round(macd_value, 4),
                    "macd_signal": round(signal_value, 4),
                    "macd_histogram": round(macd_histogram.iloc[-1], 4) if not macd_histogram.empty else 0,
                    "bb_upper": round(bb_upper.iloc[-1], 4) if not bb_upper.empty else 0,
                    "bb_middle": round(bb_middle.iloc[-1], 4) if not bb_middle.empty else 0,
                    "bb_lower": round(bb_lower.iloc[-1], 4) if not bb_lower.empty else 0,
                    "atr": round(atr, 4),
                    "volume_ratio": round(volume_ratio, 2)
                },
                "levels": {
                    "support": round(recent_lows, 4),
                    "resistance": round(recent_highs, 4)
                },
                "trend": {
                    "direction": trend_map.get(trend_score, "NEUTRAL"),
                    "strength": trend_score,
                    "score": trend_score
                },
                "signals": {
                    **signals,
                    "overall": overall_signal,
                    "confidence": round(confidence, 1),
                    "score": signal_score
                },
                "patterns": patterns,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data_points": len(df)
            }
            
        except Exception as e:
            logger.error(f"Technical analysis error for {symbol}: {e}")
            return None

# ==========================================
# ENHANCED DATA MANAGER
# ==========================================
class EnhancedDataManager:
    """Enhanced data manager with failover, validation, and caching"""
    
    def __init__(self):
        self.session = None
        self.cache = {}
        self.rate_limiters = {}
        self.ws_manager = AdvancedWebSocketManager()
        self._init_time = time.time()
        self._stats = {
            'requests': defaultdict(int),
            'errors': defaultdict(int),
            'cache_hits': 0,
            'cache_misses': 0
        }
    
    async def initialize(self):
        """Initialize the data manager"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        )
        
        # Initialize rate limiters
        for service in ['binance', 'coingecko']:
            self.rate_limiters[service] = {
                'last_request': 0,
                'request_count': 0,
                'window_start': time.time()
            }
        
        # Initialize WebSocket manager
        await self.ws_manager.start_all_streams()
        
        data_logger.info("Enhanced Data Manager initialized")
    
    async def _get_cache_key(self, prefix: str, params: Dict) -> str:
        """Generate cache key"""
        param_str = json.dumps(params, sort_keys=True)
        return f"{prefix}:{hashlib.md5(param_str.encode()).hexdigest()}"
    
    async def _get_cached(self, cache_key: str, ttl: int) -> Optional[Any]:
        """Get cached data with TTL check"""
        if cache_key in self.cache:
            data, timestamp = self.cache[cache_key]
            if time.time() - timestamp < ttl:
                self._stats['cache_hits'] += 1
                return data
            else:
                del self.cache[cache_key]
        
        self._stats['cache_misses'] += 1
        return None
    
    async def _set_cached(self, cache_key: str, data: Any):
        """Set cached data"""
        self.cache[cache_key] = (data, time.time())
    
    async def _rate_limit(self, service: str):
        """Enhanced rate limiting with sliding window"""
        limiter = self.rate_limiters[service]
        current_time = time.time()
        
        # Reset window if needed
        if current_time - limiter['window_start'] > 60:
            limiter['window_start'] = current_time
            limiter['request_count'] = 0
        
        # Check rate limit
        max_requests = Config.RATE_LIMITS[service]['requests']
        if limiter['request_count'] >= max_requests:
            wait_time = 60 - (current_time - limiter['window_start'])
            if wait_time > 0:
                data_logger.debug(f"Rate limiting {service}, waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
            limiter['window_start'] = current_time
            limiter['request_count'] = 0
        
        # Check minimum delay between requests
        min_delay = 60 / max_requests
        time_since_last = current_time - limiter['last_request']
        if time_since_last < min_delay:
            await asyncio.sleep(min_delay - time_since_last)
        
        limiter['last_request'] = time.time()
        limiter['request_count'] += 1
        self._stats['requests'][service] += 1
    
    async def fetch_binance_klines(self, symbol: str, interval: str, limit: int = 500) -> List[Dict]:
        """Fetch OHLCV data from Binance with validation"""
        try:
            cache_key = await self._get_cache_key(
                f"binance:klines:{symbol}:{interval}",
                {'limit': limit}
            )
            
            # Try cache first
            cached = await self._get_cached(cache_key, Config.CACHE_TTL['klines'])
            if cached:
                return cached
            
            # Try WebSocket first
            ws_data = await self._get_ws_klines(symbol, interval, limit)
            if ws_data and len(ws_data) >= limit * 0.8:  # At least 80% data from WS
                data_logger.debug(f"Using WebSocket data for {symbol} {interval}")
                await self._set_cached(cache_key, ws_data)
                return ws_data
            
            # Fallback to API
            await self._rate_limit('binance')
            
            url = f"{Config.BINANCE_BASE_URL}/api/v3/klines"
            params = {
                "symbol": symbol.upper(),
                "interval": interval,
                "limit": min(limit, 1000)
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Validate data
                    if not isinstance(data, list) or len(data) == 0:
                        raise ValueError("Invalid data format")
                    
                    candles = []
                    for i, k in enumerate(data):
                        try:
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
                                "taker_buy_quote": float(k[10]),
                                "ignore": k[11],
                                "index": i,
                                "valid": True
                            }
                            
                            # Validate candle data
                            if not (candle['high'] >= candle['low'] >= 0 and
                                   candle['high'] >= candle['close'] >= candle['low'] and
                                   candle['high'] >= candle['open'] >= candle['low']):
                                candle['valid'] = False
                                data_logger.warning(f"Invalid candle data for {symbol} at index {i}")
                            
                            candles.append(candle)
                        except (ValueError, IndexError) as e:
                            data_logger.error(f"Error parsing candle {i}: {e}")
                            continue
                    
                    # Filter valid candles
                    valid_candles = [c for c in candles if c['valid']]
                    
                    if len(valid_candles) < limit * 0.5:  # Need at least 50% valid data
                        raise ValueError(f"Insufficient valid data: {len(valid_candles)}/{len(data)}")
                    
                    # Cache result
                    await self._set_cached(cache_key, valid_candles)
                    
                    data_logger.info(f"Fetched {len(valid_candles)} candles for {symbol} {interval}")
                    return valid_candles
                else:
                    error_text = await response.text()
                    data_logger.error(f"Binance API error {response.status}: {error_text}")
                    
                    # Try WebSocket as fallback
                    return await self._get_ws_klines(symbol, interval, limit)
                    
        except Exception as e:
            self._stats['errors']['binance_klines'] += 1
            data_logger.error(f"Error fetching Binance klines for {symbol}: {e}")
            
            # Final fallback to WebSocket
            return await self._get_ws_klines(symbol, interval, limit)
    
    async def _get_ws_klines(self, symbol: str, interval: str, limit: int) -> List[Dict]:
        """Get kline data from WebSocket without synthetic generation"""
        try:
            key = f"{symbol}_{interval}"
            if key in self.ws_manager.kline_data:
                ws_candle = self.ws_manager.kline_data[key]
                
                # Use real data only, if not enough, return what is available
                candles = []
                # Assuming we have only latest from WS, fetch more from API if needed
                candles.append(ws_candle)
                return candles  # Only latest, or extend with API in production
            return []
            
        except Exception as e:
            data_logger.error(f"Error getting WS klines: {e}")
            return []
    
    def _interval_to_minutes(self, interval: str) -> int:
        interval_map = {
            '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
            '1h': 60, '2h': 120, '4h': 240, '6h': 360, '8h': 480, '12h': 720,
            '1d': 1440, '3d': 4320, '1w': 10080, '1M': 43200
        }
        return interval_map.get(interval, 60)
    
    async def fetch_coingecko_data(self, coin_id: str = None, symbol: str = None) -> Optional[Dict]:
        try:
            if not coin_id and symbol:
                coin_id = await self._symbol_to_coingecko_id(symbol)
            
            if not coin_id:
                return None
            
            cache_key = await self._get_cache_key(f"coingecko:{coin_id}", {})
            
            # Try cache
            cached = await self._get_cached(cache_key, Config.CACHE_TTL['ticker'])
            if cached:
                return cached
            
            await self._rate_limit('coingecko')
            
            # Fetch comprehensive data
            url = f"{Config.COINGECKO_BASE_URL}/coins/{coin_id}"
            params = {
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "true"
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
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
                        "price_change_24h": data["market_data"]["price_change_24h"]["usd"],
                        "price_change_percentage_24h": data["market_data"]["price_change_percentage_24h"],
                        "price_change_percentage_7d": data["market_data"]["price_change_percentage_7d_in_currency"]["usd"],
                        "price_change_percentage_30d": data["market_data"]["price_change_percentage_30d_in_currency"]["usd"],
                        "price_change_percentage_1y": data["market_data"]["price_change_percentage_1y_in_currency"]["usd"],
                        "ath": data["market_data"]["ath"]["usd"],
                        "ath_change_percentage": data["market_data"]["ath_change_percentage"]["usd"],
                        "ath_date": data["market_data"]["ath_date"]["usd"],
                        "atl": data["market_data"]["atl"]["usd"],
                        "atl_change_percentage": data["market_data"]["atl_change_percentage"]["usd"],
                        "atl_date": data["market_data"]["atl_date"]["usd"],
                        "last_updated": data["market_data"]["last_updated"],
                        "sparkline_7d": data["market_data"]["sparkline_7d"]["price"] if data["market_data"]["sparkline_7d"] else [],
                        "validated": True
                    }
                    
                    await self._set_cached(cache_key, result)
                    return result
                else:
                    data_logger.warning(f"CoinGecko API error: {response.status}")
                    return None
                    
        except Exception as e:
            self._stats['errors']['coingecko'] += 1
            data_logger.error(f"Error fetching CoinGecko data: {e}")
            return None
    
    async def _symbol_to_coingecko_id(self, symbol: str) -> Optional[str]:
        """Convert symbol to CoinGecko ID"""
        symbol_map = {
            'BTC': 'bitcoin', 'ETH': 'ethereum', 'BNB': 'binancecoin',
            'XRP': 'ripple', 'ADA': 'cardano', 'SOL': 'solana',
            'DOT': 'polkadot', 'DOGE': 'dogecoin', 'AVAX': 'avalanche-2',
            'MATIC': 'polygon', 'LINK': 'chainlink', 'UNI': 'uniswap',
            'LTC': 'litecoin', 'ATOM': 'cosmos', 'ETC': 'ethereum-classic',
            'BCH': 'bitcoin-cash', 'XLM': 'stellar', 'TRX': 'tron',
            'ALGO': 'algorand', 'VET': 'vechain', 'THETA': 'theta-token'
        }
        
        clean_symbol = symbol.upper().replace('USDT', '')
        return symbol_map.get(clean_symbol, clean_symbol.lower())
    
    async def get_realtime_ticker(self, symbol: str) -> Optional[Dict]:
        """Get real-time ticker data with priority: WebSocket > API"""
        try:
            symbol_upper = symbol.upper()
            
            # Try WebSocket first
            ws_price = await self.ws_manager.get_realtime_price(symbol_upper)
            if ws_price:
                return ws_price
            
            # Fallback to API
            cache_key = await self._get_cache_key(f"binance:ticker:{symbol}", {})
            cached = await self._get_cached(cache_key, Config.CACHE_TTL['ticker'])
            if cached:
                return cached
            
            await self._rate_limit('binance')
            
            url = f"{Config.BINANCE_BASE_URL}/api/v3/ticker/24hr"
            params = {"symbol": symbol_upper}
            
            async with self.session.get(url, params=params) as response:
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
                        "open_price": float(data["openPrice"]),
                        "prev_close": float(data["prevClosePrice"]),
                        "weighted_avg_price": float(data["weightedAvgPrice"]),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source": "api",
                        "validated": True
                    }
                    
                    await self._set_cached(cache_key, result)
                    return result
                else:
                    return None
                    
        except Exception as e:
            self._stats['errors']['ticker'] += 1
            data_logger.error(f"Error fetching ticker for {symbol}: {e}")
            return None
    
    async def get_market_overview(self) -> List[Dict]:
        """Get comprehensive market overview"""
        try:
            cache_key = "market:overview:all"
            cached = await self._get_cached(cache_key, Config.CACHE_TTL['market'])
            if cached:
                return cached
            
            # Use WebSocket data if available
            if self.ws_manager.ticker_data:
                result = self.ws_manager.ticker_data[:20]
            else:
                # Fallback to API
                result = []
                symbols = Config.SYMBOLS['major'] + Config.SYMBOLS['mid'][:5]
                
                for symbol in symbols:
                    ticker = await self.get_realtime_ticker(symbol)
                    if ticker:
                        result.append({
                            'symbol': symbol,
                            'price': ticker['price'],
                            'change_24h': ticker.get('price_change_percent', 0),
                            'volume_24h': ticker.get('volume', 0),
                            'quote_volume_24h': ticker.get('quote_volume', 0),
                            'high_24h': ticker.get('high_price', 0),
                            'low_24h': ticker.get('low_price', 0),
                            'last_updated': ticker.get('timestamp'),
                            'validity_score': 0.9 if ticker.get('source') == 'api' else 1.0
                        })
            
            await self._set_cached(cache_key, result)
            return result
            
        except Exception as e:
            data_logger.error(f"Error getting market overview: {e}")
            return []
    
    async def get_order_book(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        """Get order book data"""
        try:
            symbol_lower = symbol.lower()
            
            # Try WebSocket first
            if symbol_lower in self.ws_manager.orderbook_data:
                return self.ws_manager.orderbook_data[symbol_lower]
            
            # Fallback to API
            cache_key = await self._get_cache_key(f"orderbook:{symbol}", {'limit': limit})
            cached = await self._get_cached(cache_key, Config.CACHE_TTL['orderbook'])
            if cached:
                return cached
            
            await self._rate_limit('binance')
            
            url = f"{Config.BINANCE_BASE_URL}/api/v3/depth"
            params = {
                "symbol": symbol.upper(),
                "limit": min(limit, 100)
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    result = {
                        "symbol": symbol.upper(),
                        "bids": [[float(price), float(qty)] for price, qty in data["bids"][:limit]],
                        "asks": [[float(price), float(qty)] for price, qty in data["asks"][:limit]],
                        "last_update_id": data["lastUpdateId"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source": "api"
                    }
                    
                    await self._set_cached(cache_key, result)
                    return result
                else:
                    return None
                    
        except Exception as e:
            self._stats['errors']['orderbook'] += 1
            data_logger.error(f"Error fetching order book for {symbol}: {e}")
            return None
    
    async def close(self):
        """Close the session"""
        if self.session:
            await self.session.close()
        
        data_logger.info("Data Manager closed")

# ==========================================
# ==========================================
# MACHINE LEARNING PREDICTOR (TA-Lib olmadan)
# ==========================================
class MLPredictor:
    """Machine Learning predictor for trading signals using XGBoost"""
    
    def __init__(self):
        self.models = {}
        self.scalers = {}
        self.last_train_time = {}
        self.feature_cols = None
    
    async def train(self, symbol: str, df: pd.DataFrame):
        """Train ML model"""
        if len(df) < Config.ML_CONFIG['min_data_points']:
            return
        
        # Add indicators
        df_ta = self.add_indicators(df)
        
        # Generate labels
        lookahead = Config.ML_CONFIG['lookahead']
        thresh = Config.ML_CONFIG['threshold']
        labels = self.generate_label(df_ta, lookahead, thresh)
        
        df_ta['label'] = labels
        
        # Drop NaN
        df_ta.dropna(inplace=True)
        
        # Features
        feature_cols = [c for c in df_ta.columns if c not in ["Open","High","Low","Close","Adj Close","Volume","label"]]
        self.feature_cols = feature_cols
        
        X = df_ta[feature_cols]
        y = df_ta['label']
        
        if len(X) < 100:
            return
        
        # Split
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        # Scale
        scaler = StandardScaler().fit(X_train)
        X_train_scaled = scaler.transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Model
        model = XGBClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.8,
            objective='multi:softprob',
            num_class=3,
            n_jobs=-1,
            eval_metric='mlogloss',
            random_state=42
        )
        
        model.fit(X_train_scaled, y_train)
        
        self.models[symbol] = model
        self.scalers[symbol] = scaler
        self.last_train_time[symbol] = time.time()
    
    async def predict(self, symbol: str, df: pd.DataFrame) -> str:
        """Predict using ML model"""
        if symbol not in self.models or time.time() - self.last_train_time.get(symbol, 0) > Config.ML_CONFIG['retrain_interval']:
            await self.train(symbol, df)
        
        if symbol not in self.models:
            return "HOLD"
        
        # Add indicators to latest data
        df_ta = self.add_indicators(df.iloc[-100:])  # Use last 100 for indicators
        
        # Features
        X = df_ta[self.feature_cols].iloc[-1:]  # Latest row
        
        # Scale
        X_scaled = self.scalers[symbol].transform(X)
        
        # Predict
        pred = self.models[symbol].predict(X_scaled)[0]
        
        mapping = {0: "HOLD", 1: "SELL", 2: "BUY"}
        return mapping.get(pred, "HOLD")
    
    def add_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicators without TA-Lib"""
        df = data.copy()
        
        # Ensure we have required columns
        if 'close' not in df.columns.str.lower():
            # Try to find close column
            for col in df.columns:
                if 'close' in col.lower():
                    df['Close'] = df[col]
                    break
        
        # Ensure Close column exists
        if 'Close' not in df.columns:
            logger.warning("No Close column found for indicators")
            return df
        
        # RSI (Relative Strength Index)
        def calculate_rsi(prices, period=14):
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            return 100 - (100 / (1 + rs))
        
        for length in [5, 10, 15]:
            df[f"rsi_{length}"] = calculate_rsi(df["Close"], length)
        
        # Rate of Change (ROC)
        def calculate_roc(prices, period=10):
            return (prices / prices.shift(period) - 1) * 100
        
        df["roc_10"] = calculate_roc(df["Close"], 10)
        
        # Momentum
        def calculate_mom(prices, period=10):
            return prices - prices.shift(period)
        
        df["mom_10"] = calculate_mom(df["Close"], 10)
        
        # Stochastic RSI (simplified)
        def calculate_stoch_rsi(prices, period=14):
            rsi = calculate_rsi(prices, period)
            lowest = rsi.rolling(window=period).min()
            highest = rsi.rolling(window=period).max()
            return ((rsi - lowest) / (highest - lowest)) * 100
        
        df["stochrsi_k"] = calculate_stoch_rsi(df["Close"], 14)
        df["stochrsi_d"] = df["stochrsi_k"].rolling(window=3).mean()
        
        # CCI (Commodity Channel Index)
        def calculate_cci(high, low, close, period=20):
            tp = (high + low + close) / 3
            sma_tp = tp.rolling(window=period).mean()
            mad = tp.rolling(window=period).apply(lambda x: np.mean(np.abs(x - np.mean(x))))
            return (tp - sma_tp) / (0.015 * mad)
        
        if 'High' in df.columns and 'Low' in df.columns:
            df["cci_20"] = calculate_cci(df["High"], df["Low"], df["Close"], 20)
        
        # Williams %R
        def calculate_williams_r(high, low, close, period=14):
            highest_high = high.rolling(window=period).max()
            lowest_low = low.rolling(window=period).min()
            return ((highest_high - close) / (highest_high - lowest_low)) * -100
        
        if 'High' in df.columns and 'Low' in df.columns:
            df["wr_14"] = calculate_williams_r(df["High"], df["Low"], df["Close"], 14)
        
        # MACD
        def calculate_macd(prices, fast=12, slow=26, signal=9):
            ema_fast = prices.ewm(span=fast).mean()
            ema_slow = prices.ewm(span=slow).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal).mean()
            histogram = macd_line - signal_line
            return macd_line, signal_line, histogram
        
        macd_line, signal_line, histogram = calculate_macd(df["Close"], 12, 26, 9)
        df["macd_line"] = macd_line
        df["macd_signal"] = signal_line
        df["macd_histogram"] = histogram
        
        # Simple Moving Averages
        for length in [5, 10, 20, 50, 200]:
            if len(df) >= length:
                df[f"sma_{length}"] = df["Close"].rolling(window=length).mean()
        
        # Exponential Moving Averages
        for length in [5, 10, 20, 50]:
            if len(df) >= length:
                df[f"ema_{length}"] = df["Close"].ewm(span=length).mean()
        
        # Volume Weighted Moving Average
        def calculate_vwma(close, volume, period=20):
            vw = (close * volume).rolling(window=period).sum()
            v = volume.rolling(window=period).sum()
            return vw / v
        
        if 'Volume' in df.columns:
            df["vwma_20"] = calculate_vwma(df["Close"], df["Volume"], 20)
        
        # Bollinger Bands
        def calculate_bollinger_bands(prices, period=20, std_dev=2):
            sma = prices.rolling(window=period).mean()
            std = prices.rolling(window=period).std()
            upper = sma + (std * std_dev)
            lower = sma - (std * std_dev)
            return upper, sma, lower
        
        bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(df["Close"], 20, 2)
        df["bb_upper"] = bb_upper
        df["bb_middle"] = bb_middle
        df["bb_lower"] = bb_lower
        df["bb_width"] = (bb_upper - bb_lower) / bb_middle
        df["bb_position"] = (df["Close"] - bb_lower) / (bb_upper - bb_lower)
        
        # Average True Range (ATR)
        def calculate_atr(high, low, close, period=14):
            tr1 = high - low
            tr2 = abs(high - close.shift())
            tr3 = abs(low - close.shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            return tr.rolling(window=period).mean()
        
        if 'High' in df.columns and 'Low' in df.columns:
            df["atr_14"] = calculate_atr(df["High"], df["Low"], df["Close"], 14)
        
        # Keltner Channels
        def calculate_keltner_channels(high, low, close, period=20, atr_mult=2):
            middle = close.ewm(span=period).mean()
            atr = calculate_atr(high, low, close, period)
            upper = middle + (atr * atr_mult)
            lower = middle - (atr * atr_mult)
            return upper, middle, lower
        
        if 'High' in df.columns and 'Low' in df.columns:
            kc_upper, kc_middle, kc_lower = calculate_keltner_channels(
                df["High"], df["Low"], df["Close"], 20, 2
            )
            df["kc_upper"] = kc_upper
            df["kc_middle"] = kc_middle
            df["kc_lower"] = kc_lower
        
        # On-Balance Volume (OBV)
        def calculate_obv(close, volume):
            obv = pd.Series(0, index=close.index)
            for i in range(1, len(close)):
                if close.iloc[i] > close.iloc[i-1]:
                    obv.iloc[i] = obv.iloc[i-1] + volume.iloc[i]
                elif close.iloc[i] < close.iloc[i-1]:
                    obv.iloc[i] = obv.iloc[i-1] - volume.iloc[i]
                else:
                    obv.iloc[i] = obv.iloc[i-1]
            return obv
        
        if 'Volume' in df.columns:
            df["obv"] = calculate_obv(df["Close"], df["Volume"])
        
        # Accumulation/Distribution Line
        def calculate_ad_line(high, low, close, volume):
            clv = ((close - low) - (high - close)) / (high - low)
            clv = clv.replace([np.inf, -np.inf], 0)
            return (clv * volume).cumsum()
        
        if 'High' in df.columns and 'Low' in df.columns and 'Volume' in df.columns:
            df["ad_line"] = calculate_ad_line(df["High"], df["Low"], df["Close"], df["Volume"])
        
        # Elder's Force Index
        def calculate_efi(close, volume, period=13):
            force = (close - close.shift(1)) * volume
            return force.ewm(span=period).mean()
        
        if 'Volume' in df.columns:
            df["efi"] = calculate_efi(df["Close"], df["Volume"], 13)
        
        # Negative Volume Index (NVI)
        def calculate_nvi(close, volume):
            pct_change = close.pct_change()
            nvi = pd.Series(1000, index=close.index)  # Start with 1000
            for i in range(1, len(close)):
                if volume.iloc[i] < volume.iloc[i-1]:
                    nvi.iloc[i] = nvi.iloc[i-1] * (1 + pct_change.iloc[i])
                else:
                    nvi.iloc[i] = nvi.iloc[i-1]
            return nvi
        
        if 'Volume' in df.columns:
            df["nvi"] = calculate_nvi(df["Close"], df["Volume"])
        
        # Positive Volume Index (PVI)
        def calculate_pvi(close, volume):
            pct_change = close.pct_change()
            pvi = pd.Series(1000, index=close.index)  # Start with 1000
            for i in range(1, len(close)):
                if volume.iloc[i] > volume.iloc[i-1]:
                    pvi.iloc[i] = pvi.iloc[i-1] * (1 + pct_change.iloc[i])
                else:
                    pvi.iloc[i] = pvi.iloc[i-1]
            return pvi
        
        if 'Volume' in df.columns:
            df["pvi"] = calculate_pvi(df["Close"], df["Volume"])
        
        # Price velocity (rate of change of price)
        df["price_velocity_5"] = df["Close"].pct_change(5)
        df["price_velocity_10"] = df["Close"].pct_change(10)
        df["price_velocity_20"] = df["Close"].pct_change(20)
        
        # Volume ratio
        if 'Volume' in df.columns:
            df["volume_ratio_5"] = df["Volume"] / df["Volume"].rolling(window=5).mean()
            df["volume_ratio_10"] = df["Volume"] / df["Volume"].rolling(window=10).mean()
        
        # Price position within recent range
        if 'High' in df.columns and 'Low' in df.columns:
            df["price_position"] = (df["Close"] - df["Low"].rolling(window=20).min()) / \
                                   (df["High"].rolling(window=20).max() - df["Low"].rolling(window=20).min())
        
        # Volatility indicators
        df["volatility_5"] = df["Close"].rolling(window=5).std() / df["Close"].rolling(window=5).mean()
        df["volatility_10"] = df["Close"].rolling(window=10).std() / df["Close"].rolling(window=10).mean()
        df["volatility_20"] = df["Close"].rolling(window=20).std() / df["Close"].rolling(window=20).mean()
        
        return df
    
    def generate_label(self, data: pd.DataFrame, lookahead: int = 5, thresh: float = 0.01, col: str = "Close") -> pd.Series:
        """Generate labels for ML training"""
        if col not in data.columns:
            col = 'Close' if 'Close' in data.columns else data.columns[0]
        
        future_mean = (
            data[col]
            .shift(-lookahead)
            .rolling(window=lookahead, min_periods=lookahead)
            .mean()
        )
        pct_change = (future_mean - data[col]) / data[col]
        
        labels = np.select(
            [pct_change >= thresh, pct_change <= -thresh],
            [2, 1],
            default=0
        )
        
        return pd.Series(labels, index=data.index)

# ==========================================
# ENHANCED TRADING ENGINE
# ==========================================
class EnhancedTradingEngine:
    """Enhanced trading engine with risk management and backtesting"""
    
    def __init__(self):
        self.positions = {}
        self.order_history = []
        self.trade_history = []
        self.performance = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_profit': 0,
            'max_drawdown': 0,
            'sharpe_ratio': 0
        }
        self.ml_predictor = MLPredictor()
        
    async def calculate_trading_signal(self, analysis: Dict, df: pd.DataFrame) -> Dict:
        """Calculate comprehensive trading signal with ML integration"""
        try:
            if not analysis or not analysis.get('indicators'):
                return self._default_signal()
            
            indicators = analysis['indicators']
            signals = analysis.get('signals', {})
            trend = analysis.get('trend', {})
            patterns = analysis.get('patterns', [])
            current_price = analysis['current_price']
            
            # Initialize scoring
            score = 50
            reasons = []
            
            # Trend scoring (40% weight)
            trend_direction = trend.get('direction', 'SIDEWAYS')
            trend_strength = trend.get('strength', 0)
            
            if trend_direction in ['STRONG_BULLISH', 'BULLISH']:
                score += trend_strength * 0.4
                reasons.append(f"Trend: {trend_direction} (Strength: {trend_strength})")
            elif trend_direction in ['STRONG_BEARISH', 'BEARISH']:
                score -= trend_strength * 0.4
                reasons.append(f"Trend: {trend_direction} (Strength: {trend_strength})")
            
            # Signal scoring (30% weight)
            overall_signal = signals.get('overall', 'NEUTRAL')
            signal_confidence = signals.get('confidence', 50)
            
            if overall_signal in ['STRONG_BUY', 'BUY']:
                score += signal_confidence * 0.3
                reasons.append(f"Signal: {overall_signal} (Confidence: {signal_confidence}%)")
            elif overall_signal in ['STRONG_SELL', 'SELL']:
                score -= signal_confidence * 0.3
                reasons.append(f"Signal: {overall_signal} (Confidence: {signal_confidence}%)")
            
            # Pattern scoring (20% weight)
            pattern_score = 0
            for pattern in patterns:
                if pattern['signal'] == 'BULLISH':
                    pattern_score += pattern['confidence']
                    reasons.append(f"Pattern: {pattern['name']} (Bullish)")
                elif pattern['signal'] == 'BEARISH':
                    pattern_score -= pattern['confidence']
                    reasons.append(f"Pattern: {pattern['name']} (Bearish)")
            
            score += pattern_score * 0.2
            
            # ML scoring (10% weight)
            ml_signal = await self.ml_predictor.predict(analysis['symbol'], df)
            if ml_signal == "BUY":
                score += 10
                reasons.append("ML Signal: BUY")
            elif ml_signal == "SELL":
                score -= 10
                reasons.append("ML Signal: SELL")
            else:
                reasons.append("ML Signal: HOLD")
            
            # Normalize score
            score = max(0, min(100, score))
            
            # Calculate risk parameters
            atr = indicators.get('atr', current_price * 0.01)
            stop_loss_distance = max(atr * 1.5, current_price * Config.TRADING['stop_loss_pct'])
            take_profit_distance = stop_loss_distance * 2  # 2:1 risk-reward
            
            if score >= 70:
                signal_type = "STRONG_BUY"
                stop_loss = current_price - stop_loss_distance
                take_profit = current_price + take_profit_distance
                position_size = Config.TRADING['max_position_size'] * (score / 100)
            elif score >= 60:
                signal_type = "BUY"
                stop_loss = current_price - stop_loss_distance
                take_profit = current_price + take_profit_distance
                position_size = Config.TRADING['max_position_size'] * (score / 100) * 0.7
            elif score <= 30:
                signal_type = "STRONG_SELL"
                stop_loss = current_price + stop_loss_distance
                take_profit = current_price - take_profit_distance
                position_size = Config.TRADING['max_position_size'] * ((100 - score) / 100)
            elif score <= 40:
                signal_type = "SELL"
                stop_loss = current_price + stop_loss_distance
                take_profit = current_price - take_profit_distance
                position_size = Config.TRADING['max_position_size'] * ((100 - score) / 100) * 0.7
            else:
                signal_type = "HOLD"
                stop_loss = None
                take_profit = None
                position_size = 0
            
            # Calculate confidence
            confidence = abs(score - 50) * 2
            
            result = {
                "signal": signal_type,
                "confidence": round(confidence, 1),
                "score": round(score, 1),
                "price": round(current_price, 4),
                "stop_loss": round(stop_loss, 4) if stop_loss else None,
                "take_profit": round(take_profit, 4) if take_profit else None,
                "position_size": round(position_size, 6),
                "risk_reward": 2.0 if stop_loss and take_profit else 0,
                "atr": round(atr, 4),
                "reasons": reasons[:5],  # Top 5 reasons
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "analysis_summary": {
                    "trend": trend_direction,
                    "signal_strength": signal_confidence,
                    "pattern_count": len(patterns),
                    "ml_signal": ml_signal
                }
            }
            
            logger.info(f"Generated signal: {signal_type} with {confidence}% confidence")
            return result
            
        except Exception as e:
            logger.error(f"Error calculating trading signal: {e}")
            return self._default_signal()
    
    def _default_signal(self) -> Dict:
        """Default signal when analysis fails"""
        return {
            "signal": "HOLD",
            "confidence": 0,
            "score": 50,
            "price": 0,
            "stop_loss": None,
            "take_profit": None,
            "position_size": 0,
            "risk_reward": 0,
            "atr": 0,
            "reasons": ["Insufficient data for analysis"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "analysis_summary": {}
        }
    
    def execute_simulated_order(self, symbol: str, side: str, quantity: float, 
                               order_type: str = "MARKET", price: Optional[float] = None,
                               stop_loss: Optional[float] = None, 
                               take_profit: Optional[float] = None) -> Dict:
        """Execute simulated trade order"""
        try:
            order_id = f"SIM_{int(time.time() * 1000)}_{symbol}"
            
            # Calculate order values
            execution_price = price or self._get_current_simulated_price(symbol)
            if not execution_price:
                execution_price = 50000  # Default for simulation
            
            order_value = quantity * execution_price
            
            order = {
                "order_id": order_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "price": execution_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "value": round(order_value, 2),
                "status": "FILLED",
                "fee": order_value * 0.001,  # 0.1% fee
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "simulated": True
            }
            
            # Update position
            if side == "BUY":
                if symbol not in self.positions:
                    self.positions[symbol] = {
                        "quantity": quantity,
                        "entry_price": execution_price,
                        "current_price": execution_price,
                        "side": "LONG",
                        "unrealized_pnl": 0,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit
                    }
                else:
                    pos = self.positions[symbol]
                    # Average entry price
                    total_qty = pos["quantity"] + quantity
                    pos["entry_price"] = (
                        (pos["entry_price"] * pos["quantity"]) + 
                        (execution_price * quantity)
                    ) / total_qty
                    pos["quantity"] = total_qty
                    pos["current_price"] = execution_price
                    pos["stop_loss"] = stop_loss or pos["stop_loss"]
                    pos["take_profit"] = take_profit or pos["take_profit"]
            
            elif side == "SELL":
                if symbol in self.positions:
                    pos = self.positions[symbol]
                    if quantity >= pos["quantity"]:
                        # Close position
                        profit_loss = (execution_price - pos["entry_price"]) * pos["quantity"]
                        self._record_trade(symbol, profit_loss)
                        del self.positions[symbol]
                    else:
                        # Partial close
                        profit_loss = (execution_price - pos["entry_price"]) * quantity
                        self._record_trade(symbol, profit_loss)
                        pos["quantity"] -= quantity
            
            self.order_history.append(order)
            
            # Update performance metrics
            self._update_performance_metrics()
            
            logger.info(f"Simulated order executed: {order_id}")
            return order
            
        except Exception as e:
            logger.error(f"Error executing simulated order: {e}")
            return {
                "order_id": f"ERROR_{int(time.time())}",
                "status": "FAILED",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
    
    def _get_current_simulated_price(self, symbol: str) -> Optional[float]:
        """Get simulated current price (in real app, would fetch from data manager)"""
        # This is a placeholder - in real implementation, fetch from data manager
        price_map = {
            "BTCUSDT": 50000,
            "ETHUSDT": 3000,
            "BNBUSDT": 500,
            # Add more symbols as needed
        }
        return price_map.get(symbol.upper())
    
    def _record_trade(self, symbol: str, pnl: float):
        """Record trade for performance tracking"""
        trade = {
            "trade_id": f"TRADE_{int(time.time() * 1000)}",
            "symbol": symbol,
            "pnl": round(pnl, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "winning": pnl > 0
        }
        
        self.trade_history.append(trade)
        
        # Update performance
        self.performance['total_trades'] += 1
        if pnl > 0:
            self.performance['winning_trades'] += 1
        else:
            self.performance['losing_trades'] += 1
        
        self.performance['total_profit'] += pnl
        
        # Update max drawdown (simplified)
        if pnl < self.performance['max_drawdown']:
            self.performance['max_drawdown'] = pnl
    
    def _update_performance_metrics(self):
        """Update performance metrics"""
        if self.performance['total_trades'] > 0:
            win_rate = (self.performance['winning_trades'] / 
                       self.performance['total_trades'] * 100)
            
            # Calculate Sharpe ratio (simplified)
            if len(self.trade_history) >= 2:
                returns = [t['pnl'] for t in self.trade_history[-20:]]
                if returns:
                    avg_return = np.mean(returns)
                    std_return = np.std(returns)
                    self.performance['sharpe_ratio'] = (
                        avg_return / std_return if std_return > 0 else 0
                    )
            
            self.performance['win_rate'] = round(win_rate, 2)
            self.performance['avg_profit_per_trade'] = round(
                self.performance['total_profit'] / self.performance['total_trades'], 2
            )
    
    def get_performance_report(self) -> Dict:
        """Get performance report"""
        return {
            **self.performance,
            "current_positions": len(self.positions),
            "open_orders": len([o for o in self.order_history if o.get('status') == 'OPEN']),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

# ==========================================
# WEBSOCKET ENDPOINT FOR REAL-TIME DATA
# ==========================================
class ConnectionManager:
    """Manage WebSocket connections for real-time data"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[str, set] = defaultdict(set)
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        # Remove subscriptions
        for symbol in list(self.subscriptions.keys()):
            self.subscriptions[symbol].discard(websocket)
    
    async def broadcast(self, data: Dict):
        """Broadcast data to all connected clients"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception:
                disconnected.append(connection)
        
        for connection in disconnected:
            self.disconnect(connection)
    
    async def send_to_subscribers(self, symbol: str, data: Dict):
        """Send data to subscribers of specific symbol"""
        if symbol in self.subscriptions:
            disconnected = []
            for connection in self.subscriptions[symbol]:
                try:
                    await connection.send_json(data)
                except Exception:
                    disconnected.append(connection)
            
            for connection in disconnected:
                self.disconnect(connection)

# ==========================================
# APP LIFESPAN
# ==========================================
data_manager = None
trading_engine = None
ws_manager = ConnectionManager()
START_TIME = time.time()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global data_manager, trading_engine
    # Startup
    logger.info("=" * 80)
    logger.info("🚀 ADVANCED TRADING PLATFORM - INITIALIZING")
    logger.info("=" * 80)
    
    data_manager = EnhancedDataManager()
    trading_engine = EnhancedTradingEngine()
    
    await data_manager.initialize()
    
    asyncio.create_task(_background_data_updater())
    asyncio.create_task(_background_analysis_updater())
    
    logger.info("✅ All systems initialized")
    logger.info("📊 Data Manager: Ready with WebSocket + API fallbacks")
    logger.info("🤖 Trading Engine: Ready with risk management")
    logger.info("🔌 Real-time WebSocket: Active")
    logger.info("📈 Technical Analysis: 20+ indicators")
    logger.info("=" * 80)
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down Trading Platform...")
    await data_manager.close()
    logger.info("✅ Clean shutdown complete")

async def _background_data_updater():
    """Background task to update market data periodically"""
    while True:
        try:
            # Update market overview every 10 seconds
            market_data = await data_manager.get_market_overview()
            
            # Broadcast to WebSocket clients
            await ws_manager.broadcast({
                "type": "market_update",
                "data": market_data,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Background data updater error: {e}")
            await asyncio.sleep(30)
            
async def _background_analysis_updater():
    """Background task to update analysis for major symbols"""
    major_symbols = Config.SYMBOLS['major']
    
    while True:
        try:
            for symbol in major_symbols[:3]:  # Only first 3 symbols
                candles = await data_manager.fetch_binance_klines(symbol, "1h", 100)
                if candles and len(candles) >= 50:
                    # Perform analysis
                    analysis = AdvancedTechnicalAnalysis.calculate_all_indicators(candles, symbol, "1h")
                    
                    if analysis:
                        df = pd.DataFrame(candles)
                        # Get trading signal
                        signal = await trading_engine.calculate_trading_signal(analysis, df)
                        
                        # Log the signal
                        logger.info(f"Signal for {symbol}: {signal['signal']} with {signal['confidence']}% confidence")
                    
                await asyncio.sleep(2)  # Small delay between symbols
            
            await asyncio.sleep(60)  # Wait 1 minute before next update
            
        except Exception as e:
            logger.error(f"Background analysis updater error: {e}")
            await asyncio.sleep(60)

# ==========================================
# FASTAPI APP
# ==========================================
app = FastAPI(
    title="Advanced Trading Platform (No API Keys Required)",
    description="Real-time trading platform with advanced technical analysis, no API keys needed",
    version="3.0.0",
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
# WEBSOCKET ENDPOINTS
# ==========================================
@app.websocket("/ws/realtime")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    
    try:
        # Send initial data
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to real-time data feed",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Handle messages
        while True:
            try:
                data = await websocket.receive_json()
                
                # Handle subscriptions
                if data.get("type") == "subscribe":
                    symbol = data.get("symbol")
                    if symbol:
                        ws_manager.subscriptions[symbol].add(websocket)
                        await websocket.send_json({
                            "type": "subscribed",
                            "symbol": symbol,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                
                elif data.get("type") == "unsubscribe":
                    symbol = data.get("symbol")
                    if symbol and websocket in ws_manager.subscriptions.get(symbol, set()):
                        ws_manager.subscriptions[symbol].discard(websocket)
                        await websocket.send_json({
                            "type": "unsubscribed",
                            "symbol": symbol,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                await asyncio.sleep(1)
                
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    finally:
        ws_manager.disconnect(websocket)

# ==========================================
# API ENDPOINTS
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def root():
    """Root endpoint redirects to dashboard"""
    return RedirectResponse(url="/dashboard")

@app.get("/api/health")
async def health():
    """Comprehensive health check"""
    try:
        # Check data sources
        binance_status = "healthy"
        coingecko_status = "healthy"
        ws_status = "healthy"
        
        # Test Binance API
        try:
            ticker = await data_manager.get_realtime_ticker("BTCUSDT")
            if not ticker:
                binance_status = "degraded"
        except Exception:
            binance_status = "unhealthy"
        
        # Test CoinGecko API
        try:
            cg_data = await data_manager.fetch_coingecko_data("bitcoin")
            if not cg_data:
                coingecko_status = "degraded"
        except Exception:
            coingecko_status = "unhealthy"
        
        # Check WebSocket connections
        ws_connections = len(data_manager.ws_manager.price_data)
        if ws_connections < 5:
            ws_status = "degraded"
        
        # System metrics
        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime": int(time.time() - START_TIME),
            "services": {
                "binance_api": binance_status,
                "coingecko_api": coingecko_status,
                "websocket": ws_status,
                "trading_engine": "healthy",
                "technical_analysis": "healthy"
            },
            "metrics": {
                "websocket_connections": ws_connections,
                "active_symbols": len(data_manager.ws_manager.price_data),
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "cache_hits": data_manager._stats.get('cache_hits', 0),
                "cache_misses": data_manager._stats.get('cache_misses', 0)
            },
            "data_sources": {
                "primary": "websocket",
                "fallback": "api",
                "validation": "enabled"
            }
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

@app.get("/api/ticker/{symbol}")
async def get_ticker(symbol: str, detailed: bool = False):
    """Get real-time ticker data with validation"""
    try:
        # Get Binance data
        binance_ticker = await data_manager.get_realtime_ticker(symbol)
        if not binance_ticker:
            raise HTTPException(status_code=404, detail="Symbol not found on Binance")
        
        result = {
            "symbol": symbol,
            "price": binance_ticker["price"],
            "price_change_24h": binance_ticker.get("price_change_percent", 0),
            "price_change_amount": binance_ticker.get("price_change", 0),
            "volume_24h": binance_ticker.get("volume", 0),
            "quote_volume_24h": binance_ticker.get("quote_volume", 0),
            "high_24h": binance_ticker.get("high_price", 0),
            "low_24h": binance_ticker.get("low_price", 0),
            "open_price": binance_ticker.get("open_price", 0),
            "timestamp": binance_ticker.get("timestamp"),
            "source": binance_ticker.get("source", "unknown"),
            "validated": binance_ticker.get("validated", False)
        }
        
        if detailed:
            # Get CoinGecko data
            cg_data = await data_manager.fetch_coingecko_data(symbol=symbol)
            if cg_data:
                result.update({
                    "market_cap": cg_data.get("market_cap", 0),
                    "market_cap_rank": cg_data.get("market_cap_rank"),
                    "ath": cg_data.get("ath", 0),
                    "ath_change_percentage": cg_data.get("ath_change_percentage", 0),
                    "atl": cg_data.get("atl", 0),
                    "atl_change_percentage": cg_data.get("atl_change_percentage", 0),
                    "price_change_percentage_7d": cg_data.get("price_change_percentage_7d", 0),
                    "price_change_percentage_30d": cg_data.get("price_change_percentage_30d", 0),
                    "sparkline_7d": cg_data.get("sparkline_7d", []),
                    "coingecko_last_updated": cg_data.get("last_updated")
                })
            
            # Get order book
            orderbook = await data_manager.get_order_book(symbol, limit=10)
            if orderbook:
                result["orderbook"] = {
                    "best_bid": orderbook["bids"][0][0] if orderbook["bids"] else 0,
                    "best_ask": orderbook["asks"][0][0] if orderbook["asks"] else 0,
                    "bid_ask_spread": orderbook["asks"][0][0] - orderbook["bids"][0][0] if orderbook["asks"] and orderbook["bids"] else 0
                }
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching ticker for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/klines/{symbol}")
async def get_klines(
    symbol: str,
    interval: TimeFrame = TimeFrame.H1,
    limit: int = 100,
    validate: bool = True
        ):
    """Get OHLCV data with validation"""
    try:
        if limit > 1000:
            raise HTTPException(status_code=400, detail="Limit cannot exceed 1000")
        
        candles = await data_manager.fetch_binance_klines(symbol, interval.value, limit)
        
        if not candles:
            # Fallback to CoinGecko
            cg_id = await data_manager._symbol_to_coingecko_id(symbol)
            if cg_id:
                cg_url = f"{Config.COINGECKO_BASE_URL}/coins/{cg_id}/ohlc?vs_currency=usd&days={limit}"
                
             async with data_manager.session.get(cg_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        candles = []
                        for i, d in enumerate(data):
                            candle = {
                                "timestamp": d[0],
                                "open": d[1],
                                "high": d[2],
                                "low": d[3],
                                "close": d[4],
                                "volume": 0,  # CoinGecko volume yok, 0 koy
                                "close_time": d[0] + 3600*1000,  # Tahmini
                                "quote_volume": 0,
                                "trades": 0,
                                "taker_buy_base": 0,
                                "taker_buy_quote": 0,
                                "index": i,
                                "valid": True,
                                "source": "coingecko"
                            }
                            candles.append(candle)
        
        if not candles:
            raise HTTPException(status_code=404, detail="No data available")
        
        # Filter valid candles if validation requested
        if validate:
            valid_candles = [c for c in candles if c.get('valid', True)]
            if len(valid_candles) < limit * 0.5:
                logger.warning(f"Only {len(valid_candles)}/{len(candles)} valid candles for {symbol}")
        else:
            valid_candles = candles
        
        # Calculate statistics
        if valid_candles:
            closes = [c["close"] for c in valid_candles]
            volumes = [c["volume"] for c in valid_candles]
            stats = {
                "price_stats": {
                    "current": closes[-1],
                    "min": min(closes),
                    "max": max(closes),
                    "avg": sum(closes) / len(closes),
                    "change": ((closes[-1] - closes[0]) / closes[0]) * 100 if closes[0] != 0 else 0
                },
                "volume_stats": {
                    "current": volumes[-1],
                    "total": sum(volumes),
                    "avg": sum(volumes) / len(volumes)
                }
            }
        else:
            stats = {}
        
        return {
            "symbol": symbol,
            "interval": interval.value,
            "candles": valid_candles,
            "count": len(valid_candles),
            "valid_percentage": (len(valid_candles) / len(candles) * 100) if candles else 0,
            "statistics": stats,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": valid_candles[0].get('source', 'unknown') if valid_candles else 'unknown'
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching klines for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    """Advanced technical analysis endpoint"""
    try:
        # Fetch data
        candles = await data_manager.fetch_binance_klines(
            req.symbol, req.timeframe.value, 
            Config.TA_CONFIG['min_candles']
        )
        
        if not candles or len(candles) < 50:
            raise HTTPException(status_code=400, detail="Insufficient data for analysis")
        
        # Perform analysis
        analysis = AdvancedTechnicalAnalysis.calculate_all_indicators(
            candles, req.symbol, req.timeframe.value
        )
        
        if not analysis:
            raise HTTPException(status_code=500, detail="Analysis failed")
        
        # Add additional metrics
        closes = [c["close"] for c in candles[-50:]]
        analysis["additional_metrics"] = {
            "volatility": float(np.std(closes) / np.mean(closes) * 100) if len(closes) > 1 else 0,
            "momentum": ((closes[-1] - closes[0]) / closes[0] * 100) if closes[0] != 0 else 0,
            "data_quality": {
                "total_candles": len(candles),
                "valid_candles": len([c for c in candles if c.get('valid', True)]),
                "time_range": {
                    "start": candles[0]["timestamp"] if candles else None,
                    "end": candles[-1]["timestamp"] if candles else None
                }
            }
        }
        
        return analysis
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis error for {req.symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/signal/{symbol}")
async def get_signal(
    symbol: str,
    timeframe: TimeFrame = TimeFrame.H1,
    include_analysis: bool = True
):
    """Get trading signal with analysis"""
    try:
        # Fetch data and analyze
        candles = await data_manager.fetch_binance_klines(
            symbol, timeframe.value, Config.TA_CONFIG['min_candles']
        )
        
        if not candles or len(candles) < 50:
            raise HTTPException(status_code=400, detail="Insufficient data")
        
        analysis = AdvancedTechnicalAnalysis.calculate_all_indicators(
            candles, symbol, timeframe.value
        )
        
        if not analysis:
            raise HTTPException(status_code=500, detail="Analysis failed")
        
        # Calculate signal
        df = pd.DataFrame(candles)
        signal = await trading_engine.calculate_trading_signal(analysis, df)
        
        result = {
            "symbol": symbol,
            "timeframe": timeframe.value,
            "signal": signal["signal"],
            "confidence": signal["confidence"],
            "score": signal["score"],
            "price": signal["price"],
            "position_size": signal["position_size"],
            "risk_management": {
                "stop_loss": signal["stop_loss"],
                "take_profit": signal["take_profit"],
                "risk_reward": signal["risk_reward"],
                "atr": signal["atr"]
            },
            "reasons": signal["reasons"],
            "analysis_summary": signal["analysis_summary"],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if include_analysis:
            result["analysis"] = analysis
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signal error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/market")
async def market_overview(
    category: str = "all",  # major, mid, minor, all
    sort_by: str = "volume",  # volume, change, price
    limit: int = 20
):
    """Get market overview"""
    try:
        market_data = await data_manager.get_market_overview()
        
        if not market_data:
            raise HTTPException(status_code=500, detail="Market data unavailable")
        
        # Filter by category
        if category != "all":
            if category in Config.SYMBOLS:
                category_symbols = set(Config.SYMBOLS[category])
                market_data = [d for d in market_data if d['symbol'] in category_symbols]
        
        # Sort data
        if sort_by == "volume":
            market_data.sort(key=lambda x: x.get('quote_volume_24h', 0), reverse=True)
        elif sort_by == "change":
            market_data.sort(key=lambda x: abs(x.get('change_24h', 0)), reverse=True)
        elif sort_by == "price":
            market_data.sort(key=lambda x: x.get('price', 0), reverse=True)
        
        # Apply limit
        market_data = market_data[:limit]
        
        # Calculate market statistics
        if market_data:
            total_volume = sum(d.get('quote_volume_24h', 0) for d in market_data)
            avg_change = sum(d.get('change_24h', 0) for d in market_data) / len(market_data)
            
            # Count bullish vs bearish
            bullish = len([d for d in market_data if d.get('change_24h', 0) > 0])
            bearish = len([d for d in market_data if d.get('change_24h', 0) < 0])
            
            stats = {
                "total_symbols": len(market_data),
                "total_volume_24h": total_volume,
                "average_change_24h": avg_change,
                "market_sentiment": {
                    "bullish": bullish,
                    "bearish": bearish,
                    "neutral": len(market_data) - bullish - bearish,
                    "bullish_percentage": (bullish / len(market_data)) * 100 if market_data else 0
                }
            }
        else:
            stats = {}
        
        return {
            "market_data": market_data,
            "statistics": stats,
            "count": len(market_data),
            "category": category,
            "sort_by": sort_by,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "websocket_status": {
                "connected_symbols": len(data_manager.ws_manager.price_data),
                "data_freshness": "real-time" if data_manager.ws_manager.ticker_data else "delayed"
            }
        }
        
    except Exception as e:
        logger.error(f"Market overview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/orderbook/{symbol}")
async def get_orderbook(
    symbol: str,
    limit: int = 20,
    detailed: bool = False
):
    """Get order book data"""
    try:
        orderbook = await data_manager.get_order_book(symbol, limit)
        
        if not orderbook:
            raise HTTPException(status_code=404, detail="Order book not available")
        
        result = {
            "symbol": symbol,
            "bids": orderbook["bids"],
            "asks": orderbook["asks"],
            "timestamp": orderbook.get("timestamp"),
            "source": orderbook.get("source", "api")
        }
        
        if detailed:
            # Calculate order book metrics
            if orderbook["bids"] and orderbook["asks"]:
                best_bid = orderbook["bids"][0][0]
                best_ask = orderbook["asks"][0][0]
                mid_price = (best_bid + best_ask) / 2
                spread = best_ask - best_bid
                spread_percentage = (spread / mid_price) * 100 if mid_price > 0 else 0
                
                # Calculate bid/ask volume
                bid_volume = sum(qty for _, qty in orderbook["bids"])
                ask_volume = sum(qty for _, qty in orderbook["asks"])
                volume_imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume) if (bid_volume + ask_volume) > 0 else 0
                
                result["metrics"] = {
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "mid_price": mid_price,
                    "spread": spread,
                    "spread_percentage": spread_percentage,
                    "bid_volume": bid_volume,
                    "ask_volume": ask_volume,
                    "volume_imbalance": volume_imbalance,
                    "order_imbalance": len(orderbook["bids"]) - len(orderbook["asks"])
                }
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Order book error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/performance")
async def get_performance():
    """Get trading performance"""
    try:
        return trading_engine.get_performance_report()
    except Exception as e:
        logger.error(f"Performance error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/trade/simulate")
async def simulate_trade(req: TradeRequest):
    """Simulate a trade"""
    try:
        # Validate trade
        if req.order_type == OrderType.LIMIT and not req.price:
            raise HTTPException(status_code=400, detail="Price required for limit orders")
        
        # Execute simulated order
        order = trading_engine.execute_simulated_order(
            symbol=req.symbol,
            side=req.side.value,
            quantity=req.quantity,
            order_type=req.order_type.value,
            price=req.price,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit
        )
        
        return order
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Trade simulation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# ENHANCED WEB DASHBOARD
# ==========================================
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Enhanced trading dashboard with TradingView widget"""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Advanced Trading Platform - Real-time Dashboard</title>
        <script src="https://s3.tradingview.com/tv.js"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        <style>
            :root {
                --primary: #3b82f6;
                --secondary: #10b981;
                --danger: #ef4444;
                --warning: #f59e0b;
                --dark: #0f172a;
                --darker: #020617;
                --light: #f8fafc;
                --gray: #64748b;
                --success-bg: rgba(34, 197, 94, 0.1);
                --danger-bg: rgba(239, 68, 68, 0.1);
                --warning-bg: rgba(245, 158, 11, 0.1);
            }
            
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                background: var(--darker);
                color: var(--light);
                min-height: 100vh;
                overflow-x: hidden;
            }
            
            .container {
                max-width: 1600px;
                margin: 0 auto;
                padding: 20px;
            }
            
            /* Header */
            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 30px;
                padding: 20px;
                background: rgba(15, 23, 42, 0.8);
                backdrop-filter: blur(10px);
                border-radius: 16px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
            }
            
            .logo {
                display: flex;
                align-items: center;
                gap: 12px;
            }
            
            .logo-icon {
                font-size: 32px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            
            .logo-text {
                font-size: 24px;
                font-weight: 800;
                background: linear-gradient(135deg, #3b82f6, #8b5cf6);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            
            .status-badge {
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 10px 20px;
                background: rgba(34, 197, 94, 0.2);
                border: 1px solid #22c55e;
                border-radius: 50px;
                font-size: 14px;
                font-weight: 600;
            }
            
            .status-dot {
                width: 8px;
                height: 8px;
                background: #22c55e;
                border-radius: 50%;
                animation: pulse 2s infinite;
            }
            
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
            }
            
            /* Controls */
            .controls {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 30px;
            }
            
            .control-group {
                display: flex;
                gap: 10px;
                align-items: center;
            }
            
            .control-label {
                color: var(--gray);
                font-size: 14px;
                font-weight: 500;
            }
            
            select, input, button {
                padding: 12px 16px;
                border-radius: 10px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                background: rgba(15, 23, 42, 0.8);
                color: var(--light);
                font-size: 14px;
                transition: all 0.3s;
            }
            
            select:focus, input:focus {
                outline: none;
                border-color: var(--primary);
                box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
            }
            
            button {
                background: var(--primary);
                border: none;
                cursor: pointer;
                font-weight: 600;
                display: flex;
                align-items: center;
                gap: 8px;
                justify-content: center;
            }
            
            button:hover {
                background: #2563eb;
                transform: translateY(-2px);
                box-shadow: 0 10px 20px rgba(59, 130, 246, 0.3);
            }
            
            button:active {
                transform: translateY(0);
            }
            
            .btn-danger {
                background: var(--danger);
            }
            
            .btn-danger:hover {
                background: #dc2626;
                box-shadow: 0 10px 20px rgba(239, 68, 68, 0.3);
            }
            
            .btn-success {
                background: var(--secondary);
            }
            
            .btn-success:hover {
                background: #0d966e;
                box-shadow: 0 10px 20px rgba(16, 185, 129, 0.3);
            }
            
            /* Main Grid */
            .main-grid {
                display: grid;
                grid-template-columns: 1fr 400px;
                gap: 20px;
                margin-bottom: 20px;
            }
            
            @media (max-width: 1200px) {
                .main-grid {
                    grid-template-columns: 1fr;
                }
            }
            
            /* Card Styles */
            .card {
                background: rgba(15, 23, 42, 0.8);
                backdrop-filter: blur(10px);
                border-radius: 16px;
                padding: 24px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
                transition: transform 0.3s, box-shadow 0.3s;
            }
            
            .card:hover {
                transform: translateY(-5px);
                box-shadow: 0 30px 60px rgba(0, 0, 0, 0.4);
            }
            
            .card-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
            }
            
            .card-title {
                font-size: 18px;
                font-weight: 700;
                color: var(--light);
                display: flex;
                align-items: center;
                gap: 10px;
            }
            
            .card-title i {
                color: var(--primary);
            }
            
            /* Chart Container */
            .chart-container {
                height: 500px;
                border-radius: 12px;
                overflow: hidden;
                position: relative;
            }
            
            /* Signal Card */
            .signal-card {
                margin-bottom: 20px;
            }
            
            .signal-indicator {
                padding: 25px;
                border-radius: 12px;
                text-align: center;
                transition: all 0.3s;
            }
            
            .signal-indicator.buy {
                background: var(--success-bg);
                border: 2px solid #22c55e;
            }
            
            .signal-indicator.sell {
                background: var(--danger-bg);
                border: 2px solid #ef4444;
            }
            
            .signal-indicator.hold {
                background: var(--warning-bg);
                border: 2px solid #f59e0b;
            }
            
            .signal-type {
                font-size: 32px;
                font-weight: 800;
                margin-bottom: 10px;
            }
            
            .signal-confidence {
                font-size: 48px;
                font-weight: 900;
                margin-bottom: 10px;
            }
            
            .signal-price {
                font-size: 24px;
                color: var(--gray);
                margin-bottom: 20px;
            }
            
            .signal-meta {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 10px;
                margin-top: 15px;
            }
            
            .meta-item {
                background: rgba(255, 255, 255, 0.05);
                padding: 12px;
                border-radius: 8px;
            }
            
            .meta-label {
                font-size: 12px;
                color: var(--gray);
                margin-bottom: 4px;
            }
            
            .meta-value {
                font-size: 14px;
                font-weight: 600;
            }
            
            /* Indicators Grid */
            .indicators-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
                gap: 12px;
                margin-top: 20px;
            }
            
            .indicator-item {
                background: rgba(255, 255, 255, 0.05);
                padding: 15px;
                border-radius: 10px;
                transition: all 0.3s;
            }
            
            .indicator-item:hover {
                background: rgba(255, 255, 255, 0.1);
                transform: translateY(-2px);
            }
            
            .indicator-name {
                font-size: 12px;
                color: var(--gray);
                margin-bottom: 6px;
            }
            
            .indicator-value {
                font-size: 18px;
                font-weight: 700;
                font-family: 'Courier New', monospace;
            }
            
            .indicator-value.positive {
                color: #22c55e;
            }
            
            .indicator-value.negative {
                color: #ef4444;
            }
            
            .indicator-value.neutral {
                color: #f59e0b;
            }
            
            /* Market Table */
            .market-table-container {
                overflow-x: auto;
            }
            
            .market-table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
            }
            
            .market-table th {
                padding: 15px;
                text-align: left;
                font-size: 12px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: var(--gray);
                border-bottom: 2px solid rgba(255, 255, 255, 0.1);
            }
            
            .market-table td {
                padding: 15px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                transition: background 0.3s;
            }
            
            .market-table tr:hover td {
                background: rgba(255, 255, 255, 0.05);
            }
            
            .symbol-cell {
                display: flex;
                align-items: center;
                gap: 10px;
            }
            
            .symbol-icon {
                width: 32px;
                height: 32px;
                border-radius: 50%;
                background: linear-gradient(135deg, #3b82f6, #8b5cf6);
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: 700;
            }
            
            .price-change {
                font-weight: 600;
            }
            
            .price-change.positive {
                color: #22c55e;
            }
            
            .price-change.negative {
                color: #ef4444;
            }
            
            /* Performance Stats */
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 15px;
                margin-top: 20px;
            }
            
            .stat-card {
                background: rgba(255, 255, 255, 0.05);
                padding: 20px;
                border-radius: 12px;
                text-align: center;
            }
            
            .stat-value {
                font-size: 28px;
                font-weight: 800;
                margin-bottom: 5px;
            }
            
            .stat-label {
                font-size: 12px;
                color: var(--gray);
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            
            /* Footer */
            .footer {
                text-align: center;
                padding: 20px;
                margin-top: 40px;
                color: var(--gray);
                font-size: 14px;
                border-top: 1px solid rgba(255, 255, 255, 0.1);
            }
            
            /* Real-time Badge */
            .realtime-badge {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 6px 12px;
                background: rgba(59, 130, 246, 0.2);
                border: 1px solid var(--primary);
                border-radius: 20px;
                font-size: 12px;
                font-weight: 600;
            }
            
            /* Loading Spinner */
            .spinner {
                width: 40px;
                height: 40px;
                border: 3px solid rgba(255, 255, 255, 0.1);
                border-top: 3px solid var(--primary);
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin: 20px auto;
            }
            
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            
            /* Responsive */
            @media (max-width: 768px) {
                .container {
                    padding: 10px;
                }
                
                .header {
                    flex-direction: column;
                    gap: 15px;
                    text-align: center;
                }
                
                .controls {
                    grid-template-columns: 1fr;
                }
                
                .main-grid {
                    grid-template-columns: 1fr;
                }
                
                .signal-meta {
                    grid-template-columns: 1fr;
                }
                
                .indicators-grid {
                    grid-template-columns: repeat(2, 1fr);
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <!-- Header -->
            <div class="header">
                <div class="logo">
                    <div class="logo-icon">📊</div>
                    <div class="logo-text">Advanced Trading Platform</div>
                </div>
                <div class="status-badge">
                    <div class="status-dot"></div>
                    <span>Real-time Data Active</span>
                    <span class="realtime-badge">
                        <i class="fas fa-bolt"></i>
                        Live
                    </span>
                </div>
            </div>
            
            <!-- Controls -->
            <div class="controls">
                <div class="control-group">
                    <label class="control-label">Symbol</label>
                    <input type="text" id="symbol" value="BINANCE:BTCUSDT" placeholder="BINANCE:BTCUSDT">
                </div>
                <div class="control-group">
                    <label class="control-label">Timeframe</label>
                    <select id="timeframe">
                        <option value="1">1m</option>
                        <option value="5">5m</option>
                        <option value="15">15m</option>
                        <option value="60" selected>1h</option>
                        <option value="240">4h</option>
                        <option value="1D">1d</option>
                    </select>
                </div>
                <button onclick="updateChart()"><i class="fas fa-sync"></i> Update Chart</button>
                <button onclick="analyze()"><i class="fas fa-chart-line"></i> Analyze</button>
                <button onclick="getSignal()"><i class="fas fa-signal"></i> Get Signal</button>
            </div>
            
            <!-- Main Grid -->
            <div class="main-grid">
                <!-- Chart Card -->
                <div class="card">
                    <div class="card-header">
                        <div class="card-title">
                            <i class="fas fa-chart-candlestick"></i>
                            Interactive Chart
                        </div>
                        <span class="realtime-badge">
                            <i class="fas fa-sync fa-spin"></i>
                            Real-time
                        </span>
                    </div>
                    <div id="chartContainer" class="chart-container"></div>
                </div>
                
                <!-- Signal Card -->
                <div class="card signal-card">
                    <div class="card-header">
                        <div class="card-title">
                            <i class="fas fa-signal"></i>
                            Trading Signal
                        </div>
                        <button onclick="getSignal()" class="btn-success">
                            <i class="fas fa-sync"></i>
                            Refresh
                        </button>
                    </div>
                    <div id="signalIndicator" class="signal-indicator hold">
                        <div class="signal-type">HOLD</div>
                        <div class="signal-confidence">50%</div>
                        <div class="signal-price">Current Price: $--</div>
                        <div class="signal-meta">
                            <div class="meta-item">
                                <div class="meta-label">Stop Loss</div>
                                <div class="meta-value">$--</div>
                            </div>
                            <div class="meta-item">
                                <div class="meta-label">Take Profit</div>
                                <div class="meta-value">$--</div>
                            </div>
                            <div class="meta-item">
                                <div class="meta-label">Risk/Reward</div>
                                <div class="meta-value">2.0</div>
                            </div>
                            <div class="meta-item">
                                <div class="meta-label">Position Size</div>
                                <div class="meta-value">0.001</div>
                            </div>
                        </div>
                    </div>
                    <div id="signalReasons" class="indicators-grid"></div>
                </div>
            </div>
            
            <!-- Market Overview Card -->
            <div class="card">
                <div class="card-header">
                    <div class="card-title">
                        <i class="fas fa-market-alt"></i>
                        Market Overview
                    </div>
                    <span class="realtime-badge">
                        <i class="fas fa-sync fa-spin"></i>
                        Real-time
                    </span>
                </div>
                <div class="market-table-container">
                    <table class="market-table">
                        <thead>
                            <tr>
                                <th>Symbol</th>
                                <th>Price</th>
                                <th>24h Change</th>
                                <th>Volume</th>
                                <th>High/Low</th>
                            </tr>
                        </thead>
                        <tbody id="marketTableBody">
                            <!-- Data will be populated here -->
                        </tbody>
                    </table>
                </div>
            </div>
            
            <!-- Footer -->
            <div class="footer">
                © 2026 Advanced Trading Platform. All rights reserved.
            </div>
        </div>
        
        <script>
            let widget = null;
            
            function updateChart() {
                const symbol = document.getElementById('symbol').value.trim();
                const interval = document.getElementById('timeframe').value;
                
                if (widget) {
                    widget.remove();
                }
                
                widget = new TradingView.widget({
                    "container_id": "chartContainer",
                    "width": "100%",
                    "height": "100%",
                    "symbol": symbol || "BINANCE:BTCUSDT",
                    "interval": interval,
                    "timezone": "Etc/UTC",
                    "theme": "dark",
                    "style": "1",  // 1 = mum grafik
                    "locale": "en",
                    "toolbar_bg": "#f1f3f6",
                    "enable_publishing": false,
                    "allow_symbol_change": true,
                    "studies": [
                        "MASimple@tv-basicstudies",
                        "RSI@tv-basicstudies",
                        "MACD@tv-basicstudies",
                        "BollingerBands@tv-basicstudies",
                        "Stochastic@tv-basicstudies",
                        "Volume@tv-basicstudies"
                    ],
                    "show_popup_button": true,
                    "hide_side_toolbar": false,
                    "withdateranges": true,
                    "details": true,
                    "hotlist": true,
                    "calendar": true,
                    "support_host": "https://www.tradingview.com"
                });
            }
            
            async function analyze() {
                const symbol = document.getElementById('symbol').value.trim();
                const timeframe = document.getElementById('timeframe').value;
                
                try {
                    const response = await fetch(`/api/analyze`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({symbol, timeframe: timeframe === '1D' ? '1d' : timeframe + 'm'})
                    });
                    const data = await response.json();
                    alert(`Analysis complete for ${symbol}`);
                    // You can display the analysis data here
                } catch (e) {
                    alert('Error performing analysis');
                }
            }
            
            async function getSignal() {
                const symbol = document.getElementById('symbol').value.trim();
                const timeframe = document.getElementById('timeframe').value;
                
                try {
                    const response = await fetch(`/api/signal/${symbol}?timeframe=${timeframe === '1D' ? '1d' : timeframe + 'm'}`);
                    const data = await response.json();
                    
                    // Update signal indicator
                    const indicator = document.getElementById('signalIndicator');
                    indicator.className = 'signal-indicator';
                    if (data.signal.includes('BUY')) {
                        indicator.classList.add('buy');
                    } else if (data.signal.includes('SELL')) {
                        indicator.classList.add('sell');
                    } else {
                        indicator.classList.add('hold');
                    }
                    
                    indicator.querySelector('.signal-type').textContent = data.signal;
                    indicator.querySelector('.signal-confidence').textContent = `${data.confidence}%`;
                    indicator.querySelector('.signal-price').textContent = `Current Price: $${data.price}`;
                    
                    // Update meta
                    const metaItems = indicator.querySelectorAll('.meta-value');
                    metaItems[0].textContent = data.risk_management.stop_loss ? `$${data.risk_management.stop_loss}` : '--';
                    metaItems[1].textContent = data.risk_management.take_profit ? `$${data.risk_management.take_profit}` : '--';
                    metaItems[2].textContent = data.risk_management.risk_reward;
                    metaItems[3].textContent = data.position_size;
                    
                    // Update reasons (as indicators)
                    const reasonsGrid = document.getElementById('signalReasons');
                    reasonsGrid.innerHTML = '';
                    data.reasons.forEach(reason => {
                        const item = document.createElement('div');
                        item.className = 'indicator-item';
                        item.innerHTML = `
                            <div class="indicator-name">${reason.split(':')[0]}</div>
                            <div class="indicator-value">${reason.split(':')[1]}</div>
                        `;
                        reasonsGrid.appendChild(item);
                    });
                } catch (e) {
                    alert('Error getting signal');
                }
            }
            
            async function updateMarketOverview() {
                try {
                    const response = await fetch('/api/market');
                    const data = await response.json();
                    
                    const tableBody = document.getElementById('marketTableBody');
                    tableBody.innerHTML = '';
                    
                    data.market_data.forEach(item => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td class="symbol-cell">
                                <div class="symbol-icon">${item.symbol.slice(0,3)}</div>
                                ${item.symbol}
                            </td>
                            <td>$${item.price.toFixed(2)}</td>
                            <td class="price-change ${item.change_24h > 0 ? 'positive' : 'negative'}">
                                ${item.change_24h.toFixed(2)}%
                            </td>
                            <td>$${item.volume_24h.toLocaleString()}</td>
                            <td>$${item.high_24h.toFixed(2)} / $${item.low_24h.toFixed(2)}</td>
                        `;
                        tableBody.appendChild(tr);
                    });
                } catch (e) {
                    console.error('Error updating market overview', e);
                }
            }
            
            // Initial load
            window.onload = () => {
                updateChart();
                getSignal();
                updateMarketOverview();
            };
            
            // Periodic market update
            setInterval(updateMarketOverview, 10000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ==========================================
# ERROR HANDLERS
# ==========================================
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail, "timestamp": datetime.now(timezone.utc).isoformat(), "path": request.url.path})

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Global exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal server error", "detail": str(exc), "timestamp": datetime.now(timezone.utc).isoformat(), "path": request.url.path})

# ==========================================
# MAIN ENTRY POINT
# ==========================================
if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info("=" * 80)
    logger.info("🚀 ADVANCED TRADING PLATFORM - STARTING")
    logger.info("=" * 80)
    logger.info(f"🌐 Server: http://{host}:{port}")
    logger.info("=" * 80)
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True
    )

# Teşekkürler! Bu kusursuz platform sizin için hazırlandı. Başarılar!
