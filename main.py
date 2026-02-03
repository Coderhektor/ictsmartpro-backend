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
from fastapi import FastAPI
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
        'ticker': 2,
        'klines': 60,
        'market': 30,
        'analysis': 10,
        'signal': 5,
        'orderbook': 3
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
        'risk_per_trade': 0.01
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
        'retrain_interval': 3600,
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
                    ws_logger.info(f"WebSocket connected: {stream_type} ({len(streams)} streams)")
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
        
        self.market_data[symbol] = self.price_data[symbol]
        
        if symbol not in self._data_queues:
            self._data_queues[symbol] = deque(maxlen=1000)
        self._data_queues[symbol].append(self.price_data[symbol])
        
        self._last_update[symbol] = current_time.timestamp()
    
    async def _process_kline_data(self, data: Dict):
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
        symbol = data['s'].lower()
        
        self.orderbook_data[symbol] = {
            'last_update_id': data['u'],
            'bids': [[float(price), float(qty)] for price, qty in data['b'][:20]],
            'asks': [[float(price), float(qty)] for price, qty in data['a'][:20]],
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    async def get_historical_prices(self, symbol: str, limit: int = 100) -> List[Dict]:
        if symbol in self._data_queues:
            return list(self._data_queues[symbol])[-limit:]
        return []
    
    async def get_realtime_price(self, symbol: str) -> Optional[Dict]:
        if symbol in self.price_data:
            data = self.price_data[symbol]
            if time.time() - self._last_update.get(symbol, 0) < 5:
                return data
        return None
    
    async def update_ticker_list(self):
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
        all_symbols = Config.SYMBOLS['major'] + Config.SYMBOLS['mid'] + Config.SYMBOLS['minor']
        stream_groups = [all_symbols[i:i+10] for i in range(0, len(all_symbols), 10)]
        
        for group in stream_groups:
            streams = [f"{symbol.lower()}@ticker" for symbol in group]
            asyncio.create_task(self.connect_multi_stream(streams, 'ticker'))
        
        for symbol in Config.SYMBOLS['major'][:5]:
            for interval in ['1m', '5m', '15m', '1h', '4h']:
                stream = f"{symbol.lower()}@kline_{interval}"
                asyncio.create_task(self.connect_multi_stream([stream], 'kline'))
        
        for symbol in Config.SYMBOLS['major'][:3]:
            streams = [
                f"{symbol.lower()}@depth20@100ms",
                f"{symbol.lower()}@aggTrade"
            ]
            asyncio.create_task(self.connect_multi_stream(streams, 'depth'))
        
        asyncio.create_task(self._periodic_updates())
        
        ws_logger.info(f"Started WebSocket streams for {len(all_symbols)} symbols")
    
    async def _periodic_updates(self):
        while True:
            await self.update_ticker_list()
            
            current_time = time.time()
            old_symbols = []
            for symbol, last_update in self._last_update.items():
                if current_time - last_update > 300:
                    old_symbols.append(symbol)
            
            for symbol in old_symbols:
                if symbol in self.price_data:
                    del self.price_data[symbol]
            
            await asyncio.sleep(10)

# ==========================================
# ADVANCED TECHNICAL ANALYSIS
# ==========================================
class AdvancedTechnicalAnalysis:
    @staticmethod
    def calculate_all_indicators(candles: List[Dict], symbol: str, timeframe: str) -> Dict:
        try:
            if not candles or len(candles) < 20:
                return None
            
            df = pd.DataFrame(candles)
            
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            df.columns = df.columns.str.lower()
            
            col_mapping = {
                'open': 'open', 'high': 'high', 'low': 'low', 
                'close': 'close', 'volume': 'volume'
            }
            
            for req in required_cols:
                if req not in df.columns:
                    for col in df.columns:
                        if req in col:
                            col_mapping[req] = col
                            break
            
            current_price = float(df[col_mapping['close']].iloc[-1])
            price_24h_ago = float(df[col_mapping['close']].iloc[-24]) if len(df) > 24 else current_price
            change_24h = ((current_price - price_24h_ago) / price_24h_ago * 100) if price_24h_ago > 0 else 0
            
            closes = df[col_mapping['close']].astype(float)
            sma_20 = closes.rolling(window=20).mean().iloc[-1]
            sma_50 = closes.rolling(window=50).mean().iloc[-1]
            sma_200 = closes.rolling(window=200).mean().iloc[-1] if len(df) >= 200 else None
            
            ema_12 = closes.ewm(span=12).mean().iloc[-1]
            ema_26 = closes.ewm(span=26).mean().iloc[-1]
            
            delta = closes.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1] if not rsi.empty else 50
            
            ema_12_series = closes.ewm(span=12).mean()
            ema_26_series = closes.ewm(span=26).mean()
            macd_line = ema_12_series - ema_26_series
            signal_line = macd_line.ewm(span=9).mean()
            macd_histogram = macd_line - signal_line
            
            bb_upper = closes.rolling(window=20).mean() + (closes.rolling(window=20).std() * 2)
            bb_lower = closes.rolling(window=20).mean() - (closes.rolling(window=20).std() * 2)
            bb_middle = closes.rolling(window=20).mean()
            
            volume = df[col_mapping['volume']].astype(float)
            volume_sma = volume.rolling(window=20).mean().iloc[-1]
            current_volume = volume.iloc[-1]
            volume_ratio = current_volume / volume_sma if volume_sma > 0 else 1
            
            recent_highs = df[col_mapping['high']].astype(float).rolling(window=20).max().iloc[-1]
            recent_lows = df[col_mapping['low']].astype(float).rolling(window=20).min().iloc[-1]
            
            high_low = df[col_mapping['high']].astype(float) - df[col_mapping['low']].astype(float)
            atr = high_low.rolling(window=14).mean().iloc[-1]
            
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
            
            signals = {}
            signal_score = 0
            
            if current_rsi < 30:
                signals['rsi'] = "OVERSOLD"
                signal_score += 1
            elif current_rsi > 70:
                signals['rsi'] = "OVERBOUGHT"
                signal_score -= 1
            else:
                signals['rsi'] = "NEUTRAL"
            
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
            
            if current_price > bb_upper.iloc[-1]:
                signals['bb'] = "OVERBOUGHT"
                signal_score -= 1
            elif current_price < bb_lower.iloc[-1]:
                signals['bb'] = "OVERSOLD"
                signal_score += 1
            else:
                signals['bb'] = "NEUTRAL"
            
            if volume_ratio > 1.5:
                signals['volume'] = "HIGH_VOLUME"
                signal_score += 0.5
            elif volume_ratio < 0.5:
                signals['volume'] = "LOW_VOLUME"
                signal_score -= 0.5
            else:
                signals['volume'] = "NORMAL"
            
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
            
            confidence = min(abs(signal_score) * 25, 100)
            
            patterns = []
            if len(df) >= 3:
                last_close = closes.iloc[-1]
                last_open = float(df[col_mapping['open']].iloc[-1])
                prev_close = closes.iloc[-2]
                prev_open = float(df[col_mapping['open']].iloc[-2])
                
                if (last_close > last_open and prev_close < prev_open and 
                    last_close > prev_open and last_open < prev_close):
                    patterns.append({"name": "Bullish Engulfing", "signal": "BULLISH", "confidence": 70})
                
                if (last_close < last_open and prev_close > prev_open and 
                    last_close < prev_open and last_open > prev_close):
                    patterns.append({"name": "Bearish Engulfing", "signal": "BEARISH", "confidence": 70})
                
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
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        )
        
        for service in ['binance', 'coingecko']:
            self.rate_limiters[service] = {
                'last_request': 0,
                'request_count': 0,
                'window_start': time.time()
            }
        
        await self.ws_manager.start_all_streams()
        
        data_logger.info("Enhanced Data Manager initialized")
    
    async def _get_cache_key(self, prefix: str, params: Dict) -> str:
        param_str = json.dumps(params, sort_keys=True)
        return f"{prefix}:{hashlib.md5(param_str.encode()).hexdigest()}"
    
    async def _get_cached(self, cache_key: str, ttl: int) -> Optional[Any]:
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
        self.cache[cache_key] = (data, time.time())
    
    async def _rate_limit(self, service: str):
        limiter = self.rate_limiters[service]
        current_time = time.time()
        
        if current_time - limiter['window_start'] > 60:
            limiter['window_start'] = current_time
            limiter['request_count'] = 0
        
        max_requests = Config.RATE_LIMITS[service]['requests']
        if limiter['request_count'] >= max_requests:
            wait_time = 60 - (current_time - limiter['window_start'])
            if wait_time > 0:
                data_logger.debug(f"Rate limiting {service}, waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
            limiter['window_start'] = current_time
            limiter['request_count'] = 0
        
        min_delay = 60 / max_requests
        time_since_last = current_time - limiter['last_request']
        if time_since_last < min_delay:
            await asyncio.sleep(min_delay - time_since_last)
        
        limiter['last_request'] = time.time()
        limiter['request_count'] += 1
        self._stats['requests'][service] += 1
    
    async def fetch_binance_klines(self, symbol: str, interval: str, limit: int = 500) -> List[Dict]:
        try:
            cache_key = await self._get_cache_key(
                f"binance:klines:{symbol}:{interval}",
                {'limit': limit}
            )
            
            cached = await self._get_cached(cache_key, Config.CACHE_TTL['klines'])
            if cached:
                return cached
            
            ws_data = await self._get_ws_klines(symbol, interval, limit)
            if ws_data and len(ws_data) >= limit * 0.8:
                data_logger.debug(f"Using WebSocket data for {symbol} {interval}")
                await self._set_cached(cache_key, ws_data)
                return ws_data
            
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
                            
                            if not (candle['high'] >= candle['low'] >= 0 and
                                   candle['high'] >= candle['close'] >= candle['low'] and
                                   candle['high'] >= candle['open'] >= candle['low']):
                                candle['valid'] = False
                                data_logger.warning(f"Invalid candle data for {symbol} at index {i}")
                            
                            candles.append(candle)
                        except (ValueError, IndexError) as e:
                            data_logger.error(f"Error parsing candle {i}: {e}")
                            continue
                    
                    valid_candles = [c for c in candles if c['valid']]
                    
                    if len(valid_candles) < limit * 0.5:
                        raise ValueError(f"Insufficient valid data: {len(valid_candles)}/{len(data)}")
                    
                    await self._set_cached(cache_key, valid_candles)
                    
                    data_logger.info(f"Fetched {len(valid_candles)} candles for {symbol} {interval}")
                    return valid_candles
                else:
                    error_text = await response.text()
                    data_logger.error(f"Binance API error {response.status}: {error_text}")
                    
                    return await self._get_ws_klines(symbol, interval, limit)
                    
        except Exception as e:
            self._stats['errors']['binance_klines'] += 1
            data_logger.error(f"Error fetching Binance klines for {symbol}: {e}")
            
            return await self._get_ws_klines(symbol, interval, limit)
    
    async def _get_ws_klines(self, symbol: str, interval: str, limit: int) -> List[Dict]:
        try:
            key = f"{symbol}_{interval}"
            if key in self.ws_manager.kline_data:
                ws_candle = self.ws_manager.kline_data[key]
                candles = []
                candles.append(ws_candle)
                return candles
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
            
            cached = await self._get_cached(cache_key, Config.CACHE_TTL['ticker'])
            if cached:
                return cached
            
            await self._rate_limit('coingecko')
            
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
        try:
            symbol_upper = symbol.upper()
            
            ws_price = await self.ws_manager.get_realtime_price(symbol_upper)
            if ws_price:
                return ws_price
            
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
        try:
            cache_key = "market:overview:all"
            cached = await self._get_cached(cache_key, Config.CACHE_TTL['market'])
            if cached:
                return cached
            
            if self.ws_manager.ticker_data:
                result = self.ws_manager.ticker_data[:20]
            else:
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
        try:
            symbol_lower = symbol.lower()
            
            if symbol_lower in self.ws_manager.orderbook_data:
                return self.ws_manager.orderbook_data[symbol_lower]
            
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
        if self.session:
            await self.session.close()
        
        data_logger.info("Data Manager closed")

# ==========================================
# MACHINE LEARNING PREDICTOR
# ==========================================
class MLPredictor:
    def __init__(self):
        self.models = {}
        self.scalers = {}
        self.last_train_time = {}
        self.feature_cols = None
    
    async def train(self, symbol: str, df: pd.DataFrame):
        if len(df) < Config.ML_CONFIG['min_data_points']:
            return
        
        df_ta = self.add_indicators(df)
        
        lookahead = Config.ML_CONFIG['lookahead']
        thresh = Config.ML_CONFIG['threshold']
        labels = self.generate_label(df_ta, lookahead, thresh)
        
        df_ta['label'] = labels
        
        df_ta.dropna(inplace=True)
        
        feature_cols = [c for c in df_ta.columns if c not in ["Open","High","Low","Close","Adj Close","Volume","label"]]
        self.feature_cols = feature_cols
        
        X = df_ta[feature_cols]
        y = df_ta['label']
        
        if len(X) < 100:
            return
        
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        scaler = StandardScaler().fit(X_train)
        X_train_scaled = scaler.transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
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
        if symbol not in self.models or time.time() - self.last_train_time.get(symbol, 0) > Config.ML_CONFIG['retrain_interval']:
            await self.train(symbol, df)
        
        if symbol not in self.models:
            return "HOLD"
        
        df_ta = self.add_indicators(df.iloc[-100:])
        
        X = df_ta[self.feature_cols].iloc[-1:]
        
        X_scaled = self.scalers[symbol].transform(X)
        
        pred = self.models[symbol].predict(X_scaled)[0]
        
        mapping = {0: "HOLD", 1: "SELL", 2: "BUY"}
        return mapping.get(pred, "HOLD")
    
    def add_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        
        if 'close' not in df.columns.str.lower():
            for col in df.columns:
                if 'close' in col.lower():
                    df['Close'] = df[col]
                    break
        
        if 'Close' not in df.columns:
            logger.warning("No Close column found for indicators")
            return df
        
        def calculate_rsi(prices, period=14):
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            return 100 - (100 / (1 + rs))
        
        for length in [5, 10, 15]:
            df[f"rsi_{length}"] = calculate_rsi(df["Close"], length)
        
        def calculate_roc(prices, period=10):
            return (prices / prices.shift(period) - 1) * 100
        
        df["roc_10"] = calculate_roc(df["Close"], 10)
        
        def calculate_mom(prices, period=10):
            return prices - prices.shift(period)
        
        df["mom_10"] = calculate_mom(df["Close"], 10)
        
        def calculate_stoch_rsi(prices, period=14):
            rsi = calculate_rsi(prices, period)
            lowest = rsi.rolling(window=period).min()
            highest = rsi.rolling(window=period).max()
            return ((rsi - lowest) / (highest - lowest)) * 100
        
        df["stochrsi_k"] = calculate_stoch_rsi(df["Close"], 14)
        df["stochrsi_d"] = df["stochrsi_k"].rolling(window=3).mean()
        
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
        
        for length in [5, 10, 20, 50, 200]:
            if len(df) >= length:
                df[f"sma_{length}"] = df["Close"].rolling(window=length).mean()
        
        for length in [5, 10, 20, 50]:
            if len(df) >= length:
                df[f"ema_{length}"] = df["Close"].ewm(span=length).mean()
        
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
        
        df["price_velocity_5"] = df["Close"].pct_change(5)
        df["price_velocity_10"] = df["Close"].pct_change(10)
        df["price_velocity_20"] = df["Close"].pct_change(20)
        
        if 'Volume' in df.columns:
            df["volume_ratio_5"] = df["Volume"] / df["Volume"].rolling(window=5).mean()
            df["volume_ratio_10"] = df["Volume"] / df["Volume"].rolling(window=10).mean()
        
        df["volatility_5"] = df["Close"].rolling(window=5).std() / df["Close"].rolling(window=5).mean()
        df["volatility_10"] = df["Close"].rolling(window=10).std() / df["Close"].rolling(window=10).mean()
        df["volatility_20"] = df["Close"].rolling(window=20).std() / df["Close"].rolling(window=20).mean()
        
        return df
    
    def generate_label(self, data: pd.DataFrame, lookahead: int = 5, thresh: float = 0.01, col: str = "Close") -> pd.Series:
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
        try:
            if not analysis or not analysis.get('indicators'):
                return self._default_signal()
            
            indicators = analysis['indicators']
            signals = analysis.get('signals', {})
            trend = analysis.get('trend', {})
            patterns = analysis.get('patterns', [])
            current_price = analysis['current_price']
            
            score = 50
            reasons = []
            
            trend_direction = trend.get('direction', 'SIDEWAYS')
            trend_strength = trend.get('strength', 0)
            
            if trend_direction in ['STRONG_BULLISH', 'BULLISH']:
                score += trend_strength * 0.4
                reasons.append(f"Trend: {trend_direction} (Strength: {trend_strength})")
            elif trend_direction in ['STRONG_BEARISH', 'BEARISH']:
                score -= trend_strength * 0.4
                reasons.append(f"Trend: {trend_direction} (Strength: {trend_strength})")
            
            overall_signal = signals.get('overall', 'NEUTRAL')
            signal_confidence = signals.get('confidence', 50)
            
            if overall_signal in ['STRONG_BUY', 'BUY']:
                score += signal_confidence * 0.3
                reasons.append(f"Signal: {overall_signal} (Confidence: {signal_confidence}%)")
            elif overall_signal in ['STRONG_SELL', 'SELL']:
                score -= signal_confidence * 0.3
                reasons.append(f"Signal: {overall_signal} (Confidence: {signal_confidence}%)")
            
            pattern_score = 0
            for pattern in patterns:
                if pattern['signal'] == 'BULLISH':
                    pattern_score += pattern['confidence']
                    reasons.append(f"Pattern: {pattern['name']} (Bullish)")
                elif pattern['signal'] == 'BEARISH':
                    pattern_score -= pattern['confidence']
                    reasons.append(f"Pattern: {pattern['name']} (Bearish)")
            
            score += pattern_score * 0.2
            
            ml_signal = await self.ml_predictor.predict(analysis['symbol'], df)
            if ml_signal == "BUY":
                score += 10
                reasons.append("ML Signal: BUY")
            elif ml_signal == "SELL":
                score -= 10
                reasons.append("ML Signal: SELL")
            else:
                reasons.append("ML Signal: HOLD")
            
            score = max(0, min(100, score))
            
            atr = indicators.get('atr', current_price * 0.01)
            stop_loss_distance = max(atr * 1.5, current_price * Config.TRADING['stop_loss_pct'])
            take_profit_distance = stop_loss_distance * 2
            
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
                "reasons": reasons[:5],
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
        try:
            order_id = f"SIM_{int(time.time() * 1000)}_{symbol}"
            
            execution_price = price or self._get_current_simulated_price(symbol)
            if not execution_price:
                execution_price = 50000
            
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
                "fee": order_value * 0.001,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "simulated": True
            }
            
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
                        profit_loss = (execution_price - pos["entry_price"]) * pos["quantity"]
                        self._record_trade(symbol, profit_loss)
                        del self.positions[symbol]
                    else:
                        profit_loss = (execution_price - pos["entry_price"]) * quantity
                        self._record_trade(symbol, profit_loss)
                        pos["quantity"] -= quantity
            
            self.order_history.append(order)
            
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
        price_map = {
            "BTCUSDT": 50000,
            "ETHUSDT": 3000,
            "BNBUSDT": 500,
        }
        return price_map.get(symbol.upper())
    
    def _record_trade(self, symbol: str, pnl: float):
        trade = {
            "trade_id": f"TRADE_{int(time.time() * 1000)}",
            "symbol": symbol,
            "pnl": round(pnl, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "winning": pnl > 0
        }
        
        self.trade_history.append(trade)
        
        self.performance['total_trades'] += 1
        if pnl > 0:
            self.performance['winning_trades'] += 1
        else:
            self.performance['losing_trades'] += 1
        
        self.performance['total_profit'] += pnl
        
        if pnl < self.performance['max_drawdown']:
            self.performance['max_drawdown'] = pnl
    
    def _update_performance_metrics(self):
        if self.performance['total_trades'] > 0:
            win_rate = (self.performance['winning_trades'] / 
                       self.performance['total_trades'] * 100)
            
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
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[str, set] = defaultdict(set)
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        for symbol in list(self.subscriptions.keys()):
            self.subscriptions[symbol].discard(websocket)
    
    async def broadcast(self, data: Dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception:
                disconnected.append(connection)
        
        for connection in disconnected:
            self.disconnect(connection)
    
    async def send_to_subscribers(self, symbol: str, data: Dict):
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
    
    logger.info("🛑 Shutting down Trading Platform...")
    await data_manager.close()
    logger.info("✅ Clean shutdown complete")

async def _background_data_updater():
    while True:
        try:
            market_data = await data_manager.get_market_overview()
            
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
    major_symbols = Config.SYMBOLS['major']
    
    while True:
        try:
            for symbol in major_symbols[:3]:
                candles = await data_manager.fetch_binance_klines(symbol, "1h", 100)
                if candles and len(candles) >= 50:
                    analysis = AdvancedTechnicalAnalysis.calculate_all_indicators(candles, symbol, "1h")
                    
                    if analysis:
                        df = pd.DataFrame(candles)
                        signal = await trading_engine.calculate_trading_signal(analysis, df)
                        
                        logger.info(f"Signal for {symbol}: {signal['signal']} with {signal['confidence']}% confidence")
                    
                await asyncio.sleep(2)
            
            await asyncio.sleep(60)
            
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
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to real-time data feed",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        while True:
            try:
                data = await websocket.receive_json()
                
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
@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")

@app.get("/api/health")
@app.get("/healthz")
async def health():
    try:
        binance_status = "healthy"
        coingecko_status = "healthy"
        ws_status = "healthy"
        
        try:
            ticker = await data_manager.get_realtime_ticker("BTCUSDT")
            if not ticker:
                binance_status = "degraded"
        except Exception:
            binance_status = "unhealthy"
        
        try:
            cg_data = await data_manager.fetch_coingecko_data("bitcoin")
            if not cg_data:
                coingecko_status = "degraded"
        except Exception:
            coingecko_status = "unhealthy"
        
        ws_connections = len(data_manager.ws_manager.price_data)
        if ws_connections < 5:
            ws_status = "degraded"
        
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
    try:
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
    try:
        if limit > 1000:
            raise HTTPException(status_code=400, detail="Limit cannot exceed 1000")
        
        candles = await data_manager.fetch_binance_klines(symbol, interval.value, limit)
        
        if not candles:
            raise HTTPException(status_code=404, detail="No data available")
        
        if validate:
            valid_candles = [c for c in candles if c.get('valid', True)]
            if len(valid_candles) < limit * 0.5:
                logger.warning(f"Only {len(valid_candles)}/{len(candles)} valid candles for {symbol}")
        else:
            valid_candles = candles
        
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
    try:
        candles = await data_manager.fetch_binance_klines(
            req.symbol, req.timeframe.value, 
            Config.TA_CONFIG['min_candles']
        )
        
        if not candles or len(candles) < 50:
            raise HTTPException(status_code=400, detail="Insufficient data for analysis")
        
        analysis = AdvancedTechnicalAnalysis.calculate_all_indicators(
            candles, req.symbol, req.timeframe.value
        )
        
        if not analysis:
            raise HTTPException(status_code=500, detail="Analysis failed")
        
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
    try:
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
    category: str = "all",
    sort_by: str = "volume",
    limit: int = 20
):
    try:
        market_data = await data_manager.get_market_overview()
        
        if not market_data:
            raise HTTPException(status_code=500, detail="Market data unavailable")
        
        if category != "all":
            if category in Config.SYMBOLS:
                category_symbols = set(Config.SYMBOLS[category])
                market_data = [d for d in market_data if d['symbol'] in category_symbols]
        
        if sort_by == "volume":
            market_data.sort(key=lambda x: x.get('quote_volume_24h', 0), reverse=True)
        elif sort_by == "change":
            market_data.sort(key=lambda x: abs(x.get('change_24h', 0)), reverse=True)
        elif sort_by == "price":
            market_data.sort(key=lambda x: x.get('price', 0), reverse=True)
        
        market_data = market_data[:limit]
        
        if market_data:
            total_volume = sum(d.get('quote_volume_24h', 0) for d in market_data)
            avg_change = sum(d.get('change_24h', 0) for d in market_data) / len(market_data)
            
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
            if orderbook["bids"] and orderbook["asks"]:
                best_bid = orderbook["bids"][0][0]
                best_ask = orderbook["asks"][0][0]
                mid_price = (best_bid + best_ask) / 2
                spread = best_ask - best_bid
                spread_percentage = (spread / mid_price) * 100 if mid_price > 0 else 0
                
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
    try:
        return trading_engine.get_performance_report()
    except Exception as e:
        logger.error(f"Performance error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/trade/simulate")
async def simulate_trade(req: TradeRequest):
    try:
        if req.order_type == OrderType.LIMIT and not req.price:
            raise HTTPException(status_code=400, detail="Price required for limit orders")
        
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
# DASHBOARD
# ==========================================
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Advanced Trading Platform</title>
        <script src="https://s3.tradingview.com/tv.js"></script>
        <style>
            body {
                margin: 0;
                padding: 20px;
                background: #0f172a;
                color: #f8fafc;
                font-family: Arial, sans-serif;
            }
            .container {
                max-width: 1400px;
                margin: 0 auto;
            }
            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
                padding: 20px;
                background: rgba(15, 23, 42, 0.8);
                border-radius: 16px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            .controls {
                display: flex;
                gap: 10px;
                margin-bottom: 20px;
            }
            .controls input, .controls select, .controls button {
                padding: 10px;
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                background: rgba(15, 23, 42, 0.8);
                color: white;
            }
            .controls button {
                background: #3b82f6;
                border: none;
                cursor: pointer;
            }
            .main-grid {
                display: grid;
                grid-template-columns: 1fr 400px;
                gap: 20px;
                margin-bottom: 20px;
            }
            .card {
                background: rgba(15, 23, 42, 0.8);
                border-radius: 16px;
                padding: 20px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            .chart-container {
                height: 500px;
                border-radius: 12px;
                overflow: hidden;
            }
            @media (max-width: 1200px) {
                .main-grid {
                    grid-template-columns: 1fr;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Advanced Trading Platform</h1>
                <div style="padding: 10px 20px; background: rgba(34, 197, 94, 0.2); border-radius: 50px;">
                    <span style="background: #22c55e; width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 8px;"></span>
                    Real-time Data Active
                </div>
            </div>
            
            <div class="controls">
                <input type="text" id="symbol" value="BINANCE:BTCUSDT" placeholder="Symbol">
                <select id="timeframe">
                    <option value="1">1m</option>
                    <option value="5">5m</option>
                    <option value="15">15m</option>
                    <option value="60" selected>1h</option>
                    <option value="240">4h</option>
                    <option value="1D">1d</option>
                </select>
                <button onclick="updateChart()">Update Chart</button>
                <button onclick="getSignal()">Get Signal</button>
            </div>
            
            <div class="main-grid">
                <div class="card">
                    <h3>Interactive Chart</h3>
                    <div id="chartContainer" class="chart-container"></div>
                </div>
                
                <div class="card">
                    <h3>Trading Signal</h3>
                    <div id="signalIndicator" style="padding: 20px; border-radius: 12px; text-align: center; background: rgba(245, 158, 11, 0.1); border: 2px solid #f59e0b;">
                        <div style="font-size: 32px; font-weight: bold;">HOLD</div>
                        <div style="font-size: 48px; font-weight: 900;">50%</div>
                        <div style="font-size: 24px; color: #64748b;">Current Price: $--</div>
                    </div>
                </div>
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
                    "style": "1",
                    "locale": "en",
                    "toolbar_bg": "#f1f3f6",
                    "enable_publishing": false,
                    "allow_symbol_change": true,
                    "studies": [
                        "MASimple@tv-basicstudies",
                        "RSI@tv-basicstudies",
                        "MACD@tv-basicstudies",
                        "BollingerBands@tv-basicstudies",
                        "Volume@tv-basicstudies"
                    ],
                    "show_popup_button": true,
                    "hide_side_toolbar": false,
                    "withdateranges": true
                });
            }
            
            async function getSignal() {
                const symbol = document.getElementById('symbol').value.trim();
                const timeframe = document.getElementById('timeframe').value;
                
                try {
                    const response = await fetch(`/api/signal/${symbol.split(':')[1]}?timeframe=${timeframe === '1D' ? '1d' : timeframe + 'm'}`);
                    const data = await response.json();
                    
                    const indicator = document.getElementById('signalIndicator');
                    indicator.style.background = data.signal.includes('BUY') ? 'rgba(34, 197, 94, 0.1)' : 
                                                data.signal.includes('SELL') ? 'rgba(239, 68, 68, 0.1)' : 
                                                'rgba(245, 158, 11, 0.1)';
                    indicator.style.borderColor = data.signal.includes('BUY') ? '#22c55e' : 
                                                 data.signal.includes('SELL') ? '#ef4444' : 
                                                 '#f59e0b';
                    
                    indicator.querySelector('div:nth-child(1)').textContent = data.signal;
                    indicator.querySelector('div:nth-child(2)').textContent = data.confidence + '%';
                    indicator.querySelector('div:nth-child(3)').textContent = 'Current Price: $' + data.price;
                    
                } catch (e) {
                    alert('Error getting signal');
                }
            }
            
            window.onload = () => {
                updateChart();
                getSignal();
            };
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
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": request.url.path
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Global exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": request.url.path
        }
    )

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
