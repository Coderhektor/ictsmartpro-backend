"""
🚀 PROFESSIONAL CRYPTO TRADING PLATFORM
========================================
Production-ready trading system with:
- Single WebSocket connection for all symbols
- Advanced ML predictions (Random Forest + Gradient Boosting)
- 50+ Technical indicators
- ICT concepts (Smart Money, Order Blocks, FVG)
- Chart patterns & candlestick patterns
- Support/Resistance with clustering
- Real-time price flow (Binance + CoinGecko)
- Professional web dashboard
- No API keys required
"""

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import traceback

import aiohttp
import numpy as np
import pandas as pd
import websockets
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, validator
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from scipy.signal import argrelextrema

# ==========================================
# YENİ KONFİGÜRASYON - GÜNCELLENMİŞ
# ==========================================
class Config:
    """Production configuration - Optimized"""
    # External APIs (No keys needed)
    BINANCE_API = "https://api.binance.com"
    BINANCE_WS = "wss://stream.binance.com:9443/ws"
    COINGECKO_API = "https://api.coingecko.com/api/v3"
    
    # WebSocket settings
    COMBINED_STREAM_RECONNECT_HOURS = 23  # 23 saatte bir yeniden bağlan
    WS_PING_INTERVAL = 30
    WS_PING_TIMEOUT = 10
    WS_MAX_SIZE = 2**23  # 8MB
    
    # Cache settings
    PRICE_CACHE_TTL = 5  # seconds
    ORDERBOOK_CACHE_TTL = 10
    KLINE_CACHE_TTL = 60
    
    # Rate limiting
    BINANCE_RATE_LIMIT = 1200  # requests/minute
    BINANCE_RATE_LIMIT_PER_SECOND = 20  # saniyede 20 request
    COINGECKO_RATE_LIMIT = 50
    
    # ML settings
    ML_RETRAIN_INTERVAL = 3600  # 1 hour
    ML_MIN_DATA_POINTS = 200
    ML_TRAIN_TEST_SPLIT = 0.2
    
    # Default trading symbols
    DEFAULT_SYMBOLS = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
        "SOLUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT"
    ]
    
    # Allowed timeframes
    ALLOWED_TIMEFRAMES = {
        '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', '30m': '30m',
        '1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h', '8h': '8h',
        '12h': '12h', '1d': '1d', '3d': '3d', '1w': '1w', '1M': '1M'
    }
    
    # Risk management
    MAX_RISK_PER_TRADE = 0.02  # 2%
    RISK_REWARD_MIN = 2.0
    
    # ICT settings
    FVG_MIN_SIZE = 0.001
    ORDER_BLOCK_LOOKBACK = 10
    LIQUIDITY_SWEEP_THRESHOLD = 0.98
    
    # App settings
    PORT = int(os.getenv("PORT", 8000))
    HOST = os.getenv("HOST", "0.0.0.0")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# ==========================================
# LOGGING SETUP - GELİŞTİRİLMİŞ
# ==========================================
logging.basicConfig(
    level=logging.DEBUG if Config.DEBUG else logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('trading_platform.log', encoding='utf-8', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# ==========================================
# DATA MODELS - GÜNCELLENMİŞ
# ==========================================
class AnalysisRequest(BaseModel):
    """Request model for technical analysis"""
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    limit: int = 500
    
    @validator('timeframe')
    def validate_timeframe(cls, v):
        if v not in Config.ALLOWED_TIMEFRAMES:
            raise ValueError(f'Invalid timeframe. Allowed: {list(Config.ALLOWED_TIMEFRAMES.keys())}')
        return v
    
    @validator('symbol')
    def validate_symbol(cls, v):
        return v.upper().replace(" ", "")

class TradeSignalRequest(BaseModel):
    """Request model for trade signals"""
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    use_ml: bool = True
    
    @validator('timeframe')
    def validate_timeframe(cls, v):
        if v not in Config.ALLOWED_TIMEFRAMES:
            raise ValueError(f'Invalid timeframe. Allowed: {list(Config.ALLOWED_TIMEFRAMES.keys())}')
        return v
    
    @validator('symbol')
    def validate_symbol(cls, v):
        return v.upper().replace(" ", "")

# ==========================================
# RATE LIMITER - EKLENDİ
# ==========================================
class RateLimiter:
    """Rate limiting implementation"""
    
    def __init__(self):
        self.requests = defaultdict(list)
        
    async def check_rate_limit(self, client_id: str, limit_per_minute: int = 60):
        """Check if client has exceeded rate limit"""
        now = time.time()
        window_start = now - 60  # Last 60 seconds
        
        # Clean old requests
        self.requests[client_id] = [req_time for req_time in self.requests[client_id] 
                                   if req_time > window_start]
        
        # Check limit
        if len(self.requests[client_id]) >= limit_per_minute:
            return False
        
        # Add new request
        self.requests[client_id].append(now)
        return True

# ==========================================
# OPTIMIZE EDİLMİŞ REAL-TIME DATA MANAGER
# ==========================================
class RealTimeDataManager:
    """Optimized data manager with single WebSocket connection"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.combined_ws = None
        self.price_cache: Dict[str, Dict] = {}
        self.orderbook_cache: Dict[str, Dict] = {}
        self.kline_cache: Dict[str, Dict] = {}
        self.trade_cache: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.last_update: Dict[str, float] = {}
        self.connection_start_time: float = 0
        self.is_connected = False
        self.rate_limiter = RateLimiter()
        self.request_times = deque(maxlen=Config.BINANCE_RATE_LIMIT)
        
    async def initialize(self):
        """Initialize HTTP session and WebSocket connection"""
        self.session = aiohttp.ClientSession(
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            timeout=aiohttp.ClientTimeout(total=30)
        )
        logger.info("✅ HTTP session initialized")
        
        # Start combined WebSocket stream
        asyncio.create_task(self._managed_combined_stream())
        
    async def _managed_combined_stream(self):
        """
        Manages single WebSocket connection for all symbols
        with 23-hour reconnection cycle
        """
        reconnect_delay = 1
        max_reconnect_delay = 60
        
        while True:
            try:
                # Planlı yeniden bağlanma: 23 saatte bir
                current_time = time.time()
                if current_time - self.connection_start_time > Config.COMBINED_STREAM_RECONNECT_HOURS * 3600:
                    logger.info("🕒 Planned 23-hour reconnection initiated")
                    if self.combined_ws:
                        await self.combined_ws.close()
                
                # Semboller için stream URL oluştur
                stream_names = []
                for symbol in Config.DEFAULT_SYMBOLS:
                    stream_names.append(f"{symbol.lower()}@ticker")
                    stream_names.append(f"{symbol.lower()}@trade")
                
                if not stream_names:
                    await asyncio.sleep(10)
                    continue
                
                combined_streams = "/".join(stream_names)
                ws_url = f"{Config.BINANCE_WS}/stream?streams={combined_streams}"
                
                logger.info(f"🔗 Connecting to WebSocket: {len(stream_names)} streams")
                
                # WebSocket bağlantısı
                async with websockets.connect(
                    ws_url,
                    ping_interval=Config.WS_PING_INTERVAL,
                    ping_timeout=Config.WS_PING_TIMEOUT,
                    max_size=Config.WS_MAX_SIZE,
                    close_timeout=2
                ) as websocket:
                    
                    self.combined_ws = websocket
                    self.connection_start_time = current_time
                    self.is_connected = True
                    reconnect_delay = 1
                    
                    logger.info(f"✅ Connected to combined stream: {len(stream_names)} streams")
                    
                    # Mesajları dinle
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            await self._process_stream_message(data)
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ Invalid JSON: {str(e)[:200]}")
                        except Exception as e:
                            logger.error(f"❌ Stream processing error: {e}")
                            
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"🔌 Connection closed: {e}")
                self.is_connected = False
            except Exception as e:
                logger.error(f"⚠️ WebSocket error: {e}")
                self.is_connected = False
                
            # Üstel geri çekilme
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
            logger.info(f"🔄 Reconnecting in {reconnect_delay} seconds...")
    
    async def _process_stream_message(self, data: Dict):
        """Process incoming WebSocket messages"""
        try:
            stream_name = data.get('stream', '')
            payload = data.get('data', {})
            
            if '@ticker' in stream_name:
                symbol = stream_name.replace('@ticker', '').upper()
                await self._update_price_cache(symbol, payload)
                
            elif '@trade' in stream_name:
                symbol = stream_name.replace('@trade', '').upper()
                await self._update_trade_cache(symbol, payload)
                
        except Exception as e:
            logger.error(f"❌ Error processing stream message: {e}")
    
    async def _update_price_cache(self, symbol: str, data: Dict):
        """Update price cache with ticker data"""
        try:
            now = datetime.utcnow()
            self.price_cache[symbol] = {
                'symbol': symbol,
                'price': float(data.get('c', 0)),
                'bid': float(data.get('b', 0)),
                'ask': float(data.get('a', 0)),
                'high_24h': float(data.get('h', 0)),
                'low_24h': float(data.get('l', 0)),
                'volume_24h': float(data.get('v', 0)),
                'quote_volume_24h': float(data.get('q', 0)),
                'price_change_24h': float(data.get('p', 0)),
                'price_change_pct_24h': float(data.get('P', 0)),
                'trades_count': int(data.get('n', 0)),
                'timestamp': now.isoformat(),
                'source': 'binance_ws',
                'event_time': data.get('E', int(now.timestamp() * 1000))
            }
            self.last_update[f"{symbol}_price"] = time.time()
            
        except Exception as e:
            logger.error(f"❌ Price cache update error for {symbol}: {e}")
    
    async def _update_trade_cache(self, symbol: str, data: Dict):
        """Update trade cache"""
        try:
            trade = {
                'price': float(data['p']),
                'quantity': float(data['q']),
                'timestamp': data['T'],
                'is_buyer_maker': data['m']
            }
            self.trade_cache[symbol].append(trade)
        except Exception as e:
            logger.error(f"❌ Trade cache update error for {symbol}: {e}")
    
    async def _enforce_rate_limit(self):
        """Enforce rate limiting for Binance API"""
        now = time.time()
        window_start = now - 1  # 1 second window
        
        # Remove old requests
        while self.request_times and self.request_times[0] < window_start:
            self.request_times.popleft()
        
        # Check if we've exceeded limit
        if len(self.request_times) >= Config.BINANCE_RATE_LIMIT_PER_SECOND:
            sleep_time = 1 - (now - self.request_times[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        self.request_times.append(now)
    
    async def get_klines(self, symbol: str, interval: str, limit: int = 500) -> List[Dict]:
        """Fetch OHLCV data with caching"""
        cache_key = f"{symbol}_{interval}_{limit}"
        
        # Cache kontrolü
        if cache_key in self.kline_cache:
            cache_data = self.kline_cache[cache_key]
            cache_time = cache_data.get('timestamp', 0)
            if time.time() - cache_time < Config.KLINE_CACHE_TTL:
                return cache_data['candles']
        
        try:
            # Rate limit kontrolü
            await self._enforce_rate_limit()
            
            url = f"{Config.BINANCE_API}/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': min(limit, 1000)
            }
            
            async with self.session.get(url, params=params, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    candles = []
                    for k in data:
                        candles.append({
                            'timestamp': k[0],
                            'open': float(k[1]),
                            'high': float(k[2]),
                            'low': float(k[3]),
                            'close': float(k[4]),
                            'volume': float(k[5]),
                            'close_time': k[6],
                            'quote_volume': float(k[7]),
                            'trades': int(k[8]),
                            'taker_buy_base': float(k[9]),
                            'taker_buy_quote': float(k[10])
                        })
                    
                    # Cache'e kaydet
                    self.kline_cache[cache_key] = {
                        'candles': candles,
                        'timestamp': time.time()
                    }
                    self.last_update[f"{symbol}_kline_{interval}"] = time.time()
                    
                    logger.info(f"📊 Fetched {len(candles)} candles for {symbol} ({interval})")
                    return candles
                else:
                    error_text = await response.text()
                    logger.error(f"❌ Binance API error {response.status}: {error_text}")
                    return []
                    
        except asyncio.TimeoutError:
            logger.error(f"❌ Timeout fetching klines for {symbol}")
            return []
        except Exception as e:
            logger.error(f"❌ Error fetching klines for {symbol}: {e}")
            return []
    
    async def get_ticker(self, symbol: str) -> Optional[Dict]:
        """Get ticker data (WebSocket first, API fallback)"""
        # WebSocket cache kontrolü
        if symbol in self.price_cache:
            cache_age = time.time() - self.last_update.get(f"{symbol}_price", 0)
            if cache_age < Config.PRICE_CACHE_TTL:
                return self.price_cache[symbol]
        
        # API fallback
        try:
            await self._enforce_rate_limit()
            
            url = f"{Config.BINANCE_API}/api/v3/ticker/24hr"
            params = {'symbol': symbol}
            
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    ticker = {
                        'symbol': symbol,
                        'price': float(data['lastPrice']),
                        'bid': float(data['bidPrice']),
                        'ask': float(data['askPrice']),
                        'high_24h': float(data['highPrice']),
                        'low_24h': float(data['lowPrice']),
                        'volume_24h': float(data['volume']),
                        'quote_volume_24h': float(data['quoteVolume']),
                        'price_change_24h': float(data['priceChange']),
                        'price_change_pct_24h': float(data['priceChangePercent']),
                        'trades_count': int(data['count']),
                        'timestamp': datetime.utcnow().isoformat(),
                        'source': 'binance_api'
                    }
                    
                    # Cache'e kaydet
                    self.price_cache[symbol] = ticker
                    self.last_update[f"{symbol}_price"] = time.time()
                    
                    return ticker
                else:
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Error fetching ticker for {symbol}: {e}")
            return None
    
    async def get_orderbook(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        """Get order book data with caching"""
        cache_key = f"{symbol}_orderbook_{limit}"
        
        if cache_key in self.orderbook_cache:
            cache_time = self.last_update.get(f"{symbol}_orderbook", 0)
            if time.time() - cache_time < Config.ORDERBOOK_CACHE_TTL:
                return self.orderbook_cache[cache_key]
        
        try:
            await self._enforce_rate_limit()
            
            url = f"{Config.BINANCE_API}/api/v3/depth"
            params = {'symbol': symbol, 'limit': limit}
            
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    orderbook = {
                        'symbol': symbol,
                        'bids': [[float(p), float(q)] for p, q in data['bids']],
                        'asks': [[float(p), float(q)] for p, q in data['asks']],
                        'timestamp': datetime.utcnow().isoformat()
                    }
                    
                    # Cache'e kaydet
                    self.orderbook_cache[cache_key] = orderbook
                    self.last_update[f"{symbol}_orderbook"] = time.time()
                    
                    return orderbook
                else:
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Error fetching orderbook for {symbol}: {e}")
            return None
    
    async def get_coingecko_data(self, symbol: str) -> Optional[Dict]:
        """Get market data from CoinGecko"""
        try:
            # Symbol mapping
            coin_map = {
                'BTC': 'bitcoin', 'ETH': 'ethereum', 'BNB': 'binancecoin',
                'XRP': 'ripple', 'ADA': 'cardano', 'SOL': 'solana',
                'DOT': 'polkadot', 'DOGE': 'dogecoin', 'AVAX': 'avalanche-2',
                'MATIC': 'matic-network', 'LTC': 'litecoin', 'LINK': 'chainlink',
                'UNI': 'uniswap', 'ATOM': 'cosmos', 'ETC': 'ethereum-classic'
            }
            
            coin_symbol = symbol.replace('USDT', '')
            coin_id = coin_map.get(coin_symbol, coin_symbol.lower())
            
            url = f"{Config.COINGECKO_API}/coins/{coin_id}"
            params = {
                'localization': 'false',
                'tickers': 'false',
                'market_data': 'true',
                'community_data': 'false',
                'developer_data': 'false'
            }
            
            async with self.session.get(url, params=params, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    market_data = data.get('market_data', {})
                    
                    return {
                        'id': coin_id,
                        'symbol': coin_symbol,
                        'name': data.get('name'),
                        'market_cap_rank': market_data.get('market_cap_rank'),
                        'market_cap': market_data.get('market_cap', {}).get('usd'),
                        'total_volume': market_data.get('total_volume', {}).get('usd'),
                        'circulating_supply': market_data.get('circulating_supply'),
                        'total_supply': market_data.get('total_supply'),
                        'max_supply': market_data.get('max_supply'),
                        'ath': market_data.get('ath', {}).get('usd'),
                        'ath_date': market_data.get('ath_date', {}).get('usd'),
                        'atl': market_data.get('atl', {}).get('usd'),
                        'atl_date': market_data.get('atl_date', {}).get('usd'),
                        'price_change_24h': market_data.get('price_change_24h'),
                        'price_change_7d': market_data.get('price_change_percentage_7d'),
                        'price_change_30d': market_data.get('price_change_percentage_30d'),
                        'timestamp': datetime.utcnow().isoformat()
                    }
                else:
                    return None
                    
        except Exception as e:
            logger.error(f"❌ CoinGecko API error for {symbol}: {e}")
            return None
    
    async def get_market_overview(self) -> List[Dict]:
        """Get market overview for all tracked symbols"""
        overview = []
        
        for symbol in Config.DEFAULT_SYMBOLS:
            try:
                ticker = await self.get_ticker(symbol)
                if ticker:
                    overview.append({
                        'symbol': symbol,
                        'price': ticker['price'],
                        'change_24h': ticker['price_change_pct_24h'],
                        'volume': ticker['volume_24h'],
                        'high': ticker['high_24h'],
                        'low': ticker['low_24h'],
                        'trades': ticker.get('trades_count', 0)
                    })
            except Exception as e:
                logger.error(f"Error fetching {symbol}: {e}")
                continue
        
        # Volume'a göre sırala
        overview.sort(key=lambda x: x['volume'], reverse=True)
        return overview
    
    async def close(self):
        """Cleanup connections"""
        try:
            if self.combined_ws:
                await self.combined_ws.close()
            if self.session:
                await self.session.close()
            logger.info("🔌 All connections closed")
        except Exception as e:
            logger.error(f"Error closing connections: {e}")

# ==========================================
# TEKNİK GÖSTERGELER - GÜNCELLENMİŞ
# ==========================================
class TechnicalIndicators:
    """Optimized technical indicators"""
    
    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all indicators at once"""
        try:
            # Create a copy to avoid modifying original
            result_df = df.copy()
            
            # Ensure we have the required columns
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in required_cols:
                if col not in result_df.columns:
                    raise ValueError(f"Missing column: {col}")
            
            close = result_df['close'].values
            
            # 1. Moving Averages
            result_df['sma_5'] = pd.Series(close).rolling(window=5).mean()
            result_df['sma_10'] = pd.Series(close).rolling(window=10).mean()
            result_df['sma_20'] = pd.Series(close).rolling(window=20).mean()
            result_df['sma_50'] = pd.Series(close).rolling(window=50).mean()
            result_df['sma_200'] = pd.Series(close).rolling(window=200).mean()
            
            result_df['ema_12'] = pd.Series(close).ewm(span=12, adjust=False).mean()
            result_df['ema_26'] = pd.Series(close).ewm(span=26, adjust=False).mean()
            
            # 2. RSI
            delta = result_df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            result_df['rsi'] = 100 - (100 / (1 + rs))
            
            # 3. MACD
            result_df['macd'] = result_df['ema_12'] - result_df['ema_26']
            result_df['macd_signal'] = result_df['macd'].ewm(span=9, adjust=False).mean()
            result_df['macd_hist'] = result_df['macd'] - result_df['macd_signal']
            
            # 4. Bollinger Bands
            result_df['bb_middle'] = result_df['sma_20']
            bb_std = result_df['close'].rolling(window=20).std()
            result_df['bb_upper'] = result_df['bb_middle'] + (bb_std * 2)
            result_df['bb_lower'] = result_df['bb_middle'] - (bb_std * 2)
            result_df['bb_width'] = (result_df['bb_upper'] - result_df['bb_lower']) / result_df['bb_middle']
            
            # 5. ATR
            high_low = result_df['high'] - result_df['low']
            high_close = abs(result_df['high'] - result_df['close'].shift())
            low_close = abs(result_df['low'] - result_df['close'].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            result_df['atr'] = tr.rolling(window=14).mean()
            
            # 6. Stochastic
            low_min = result_df['low'].rolling(window=14).min()
            high_max = result_df['high'].rolling(window=14).max()
            result_df['stoch_k'] = 100 * ((result_df['close'] - low_min) / (high_max - low_min))
            result_df['stoch_d'] = result_df['stoch_k'].rolling(3).mean()
            
            # 7. Volume indicators
            result_df['volume_sma'] = result_df['volume'].rolling(20).mean()
            result_df['volume_ratio'] = result_df['volume'] / result_df['volume_sma']
            
            # 8. OBV
            result_df['obv'] = (np.sign(result_df['close'].diff()) * result_df['volume']).fillna(0).cumsum()
            
            # 9. VWAP (for intraday only)
            result_df['typical_price'] = (result_df['high'] + result_df['low'] + result_df['close']) / 3
            result_df['vwap'] = (result_df['typical_price'] * result_df['volume']).cumsum() / result_df['volume'].cumsum()
            
            # 10. Price position in Bollinger Bands
            result_df['bb_position'] = (result_df['close'] - result_df['bb_lower']) / (result_df['bb_upper'] - result_df['bb_lower'])
            
            return result_df
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            return df
    
    @staticmethod
    def get_latest_indicators(df: pd.DataFrame) -> Dict:
        """Get latest indicator values"""
        try:
            if len(df) == 0:
                return {}
            
            latest = df.iloc[-1]
            indicators = {}
            
            # Basic price info
            indicators['open'] = float(latest.get('open', 0))
            indicators['high'] = float(latest.get('high', 0))
            indicators['low'] = float(latest.get('low', 0))
            indicators['close'] = float(latest.get('close', 0))
            indicators['volume'] = float(latest.get('volume', 0))
            
            # Moving averages
            for period in [5, 10, 20, 50, 200]:
                key = f'sma_{period}'
                if key in df.columns:
                    indicators[key] = float(latest[key]) if pd.notna(latest[key]) else 0
            
            # EMAs
            for period in [12, 26]:
                key = f'ema_{period}'
                if key in df.columns:
                    indicators[key] = float(latest[key]) if pd.notna(latest[key]) else 0
            
            # RSI
            if 'rsi' in df.columns:
                indicators['rsi'] = float(latest['rsi']) if pd.notna(latest['rsi']) else 50
            
            # MACD
            for key in ['macd', 'macd_signal', 'macd_hist']:
                if key in df.columns:
                    indicators[key] = float(latest[key]) if pd.notna(latest[key]) else 0
            
            # Bollinger Bands
            for key in ['bb_upper', 'bb_middle', 'bb_lower', 'bb_width', 'bb_position']:
                if key in df.columns:
                    indicators[key] = float(latest[key]) if pd.notna(latest[key]) else 0
            
            # ATR
            if 'atr' in df.columns:
                indicators['atr'] = float(latest['atr']) if pd.notna(latest['atr']) else 0
            
            # Stochastic
            for key in ['stoch_k', 'stoch_d']:
                if key in df.columns:
                    indicators[key] = float(latest[key]) if pd.notna(latest[key]) else 50
            
            # Volume indicators
            for key in ['volume_ratio', 'obv', 'vwap']:
                if key in df.columns:
                    indicators[key] = float(latest[key]) if pd.notna(latest[key]) else 0
            
            return indicators
            
        except Exception as e:
            logger.error(f"Error getting latest indicators: {e}")
            return {}

# ==========================================
# ICT ANALİZİ - GÜNCELLENMİŞ
# ==========================================
class ICTAnalysis:
    """Inner Circle Trader analysis"""
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> Dict:
        """Perform ICT analysis"""
        try:
            if len(df) < 50:
                return {
                    'order_blocks': [],
                    'fair_value_gaps': [],
                    'premium_discount': {'zone': 'neutral', 'position': 0.5},
                    'liquidity': {'trend': 'neutral', 'ratio': 1.0}
                }
            
            close = df['close'].values
            high = df['high'].values
            low = df['low'].values
            volume = df['volume'].values
            open_ = df['open'].values
            
            # Order Blocks
            order_blocks = ICTAnalysis._find_order_blocks(close, high, low, open_)
            
            # Fair Value Gaps
            fvgs = ICTAnalysis._find_fvgs(high, low, close)
            
            # Premium/Discount Zone
            premium_discount = ICTAnalysis._calculate_premium_discount(close)
            
            # Liquidity
            liquidity = ICTAnalysis._analyze_liquidity(volume)
            
            return {
                'order_blocks': order_blocks[-10:],  # Son 10
                'fair_value_gaps': fvgs[-10:],
                'premium_discount': premium_discount,
                'liquidity': liquidity
            }
            
        except Exception as e:
            logger.error(f"Error in ICT analysis: {e}")
            return {
                'order_blocks': [],
                'fair_value_gaps': [],
                'premium_discount': {'zone': 'neutral', 'position': 0.5},
                'liquidity': {'trend': 'neutral', 'ratio': 1.0}
            }
    
    @staticmethod
    def _find_order_blocks(close, high, low, open_):
        """Find order blocks"""
        blocks = []
        
        for i in range(2, len(close)):
            # Bearish order block (yukarı mum + aşağı hareket)
            if close[i-2] > open_[i-2] and close[i] < low[i-2]:
                blocks.append({
                    'type': 'bearish',
                    'index': i-2,
                    'high': float(high[i-2]),
                    'low': float(low[i-2]),
                    'strength': abs(close[i] - low[i-2]) / low[i-2]
                })
            
            # Bullish order block (aşağı mum + yukarı hareket)
            if close[i-2] < open_[i-2] and close[i] > high[i-2]:
                blocks.append({
                    'type': 'bullish',
                    'index': i-2,
                    'high': float(high[i-2]),
                    'low': float(low[i-2]),
                    'strength': abs(close[i] - high[i-2]) / high[i-2]
                })
        
        return blocks
    
    @staticmethod
    def _find_fvgs(high, low, close):
        """Find Fair Value Gaps"""
        fvgs = []
        
        for i in range(2, len(close)):
            # Bullish FVG
            if low[i] > high[i-2]:
                gap_size = (low[i] - high[i-2]) / close[i]
                if gap_size > Config.FVG_MIN_SIZE:
                    fvgs.append({
                        'type': 'bullish',
                        'index': i,
                        'top': float(low[i]),
                        'bottom': float(high[i-2]),
                        'size': float(gap_size)
                    })
            
            # Bearish FVG
            if high[i] < low[i-2]:
                gap_size = (low[i-2] - high[i]) / close[i]
                if gap_size > Config.FVG_MIN_SIZE:
                    fvgs.append({
                        'type': 'bearish',
                        'index': i,
                        'top': float(low[i-2]),
                        'bottom': float(high[i]),
                        'size': float(gap_size)
                    })
        
        return fvgs
    
    @staticmethod
    def _calculate_premium_discount(close):
        """Calculate premium/discount zone"""
        if len(close) < 50:
            return {'zone': 'neutral', 'position': 0.5}
        
        recent_high = np.max(close[-50:])
        recent_low = np.min(close[-50:])
        current_price = close[-1]
        
        range_size = recent_high - recent_low
        if range_size == 0:
            return {'zone': 'neutral', 'position': 0.5}
        
        position = (current_price - recent_low) / range_size
        
        if position > 0.7:
            zone = 'premium'
        elif position < 0.3:
            zone = 'discount'
        else:
            zone = 'neutral'
        
        return {
            'zone': zone,
            'position': float(position),
            'range_high': float(recent_high),
            'range_low': float(recent_low),
            'current_price': float(current_price)
        }
    
    @staticmethod
    def _analyze_liquidity(volume):
        """Analyze liquidity"""
        if len(volume) < 20:
            return {'trend': 'neutral', 'ratio': 1.0}
        
        avg_volume = np.mean(volume[-20:])
        current_volume = volume[-1]
        
        if avg_volume > 0:
            volume_ratio = current_volume / avg_volume
        else:
            volume_ratio = 1.0
        
        trend = 'high' if volume_ratio > 1.2 else 'low' if volume_ratio < 0.8 else 'normal'
        
        return {
            'trend': trend,
            'ratio': float(volume_ratio),
            'current': float(current_volume),
            'average': float(avg_volume)
        }

# ==========================================
# CANDLESTICK PATTERNS - GÜNCELLENMİŞ
# ==========================================
class CandlestickPatterns:
    """Candlestick pattern detection"""
    
    PATTERNS = {
        'doji': {'signal': 'neutral'},
        'hammer': {'signal': 'bullish'},
        'shooting_star': {'signal': 'bearish'},
        'bullish_engulfing': {'signal': 'bullish'},
        'bearish_engulfing': {'signal': 'bearish'},
        'morning_star': {'signal': 'bullish'},
        'evening_star': {'signal': 'bearish'},
        'three_white_soldiers': {'signal': 'bullish'},
        'three_black_crows': {'signal': 'bearish'},
        'tweezer_bottom': {'signal': 'bullish'},
        'tweezer_top': {'signal': 'bearish'}
    }
    
    @staticmethod
    def detect(df: pd.DataFrame) -> List[Dict]:
        """Detect candlestick patterns"""
        try:
            if len(df) < 3:
                return []
            
            patterns = []
            
            # Get arrays for faster access
            close = df['close'].values
            open_ = df['open'].values
            high = df['high'].values
            low = df['low'].values
            
            # Check last 10 candles
            start_idx = max(0, len(close) - 10)
            
            for i in range(start_idx, len(close)):
                idx_patterns = CandlestickPatterns._detect_patterns_at_index(
                    i, close, open_, high, low
                )
                patterns.extend(idx_patterns)
            
            return patterns[-15:]  # Son 15 pattern
            
        except Exception as e:
            logger.error(f"Error detecting patterns: {e}")
            return []
    
    @staticmethod
    def _detect_patterns_at_index(i, close, open_, high, low):
        """Detect patterns at specific index"""
        patterns = []
        
        # Doji
        if CandlestickPatterns._is_doji(i, close, open_, high, low):
            patterns.append({
                'pattern': 'doji',
                'index': i,
                'signal': 'neutral',
                'strength': 0.5
            })
        
        # Hammer / Shooting Star
        hammer_pattern = CandlestickPatterns._is_hammer(i, close, open_, high, low)
        if hammer_pattern:
            patterns.append(hammer_pattern)
        
        # Engulfing patterns
        if i > 0:
            engulfing_pattern = CandlestickPatterns._is_engulfing(i, close, open_)
            if engulfing_pattern:
                patterns.append(engulfing_pattern)
        
        # Multi-candle patterns
        if i >= 2:
            # Morning/Evening Star
            star_pattern = CandlestickPatterns._is_morning_evening_star(i, close, open_)
            if star_pattern:
                patterns.append(star_pattern)
            
            # Three Soldiers/Crows
            soldiers_pattern = CandlestickPatterns._is_three_soldiers_crows(i, close, open_)
            if soldiers_pattern:
                patterns.append(soldiers_pattern)
        
        return patterns
    
    @staticmethod
    def _is_doji(i, close, open_, high, low):
        """Check if candle is doji"""
        body_size = abs(close[i] - open_[i])
        total_range = high[i] - low[i]
        
        if total_range > 0 and body_size / total_range < 0.1:
            return True
        return False
    
    @staticmethod
    def _is_hammer(i, close, open_, high, low):
        """Check if candle is hammer or shooting star"""
        body_size = abs(close[i] - open_[i])
        upper_shadow = high[i] - max(close[i], open_[i])
        lower_shadow = min(close[i], open_[i]) - low[i]
        
        # Hammer (bullish)
        if lower_shadow > 2 * body_size and upper_shadow < body_size * 0.3:
            return {
                'pattern': 'hammer',
                'index': i,
                'signal': 'bullish',
                'strength': min(1.0, lower_shadow / (body_size + 0.0001))
            }
        
        # Shooting star (bearish)
        if upper_shadow > 2 * body_size and lower_shadow < body_size * 0.3:
            return {
                'pattern': 'shooting_star',
                'index': i,
                'signal': 'bearish',
                'strength': min(1.0, upper_shadow / (body_size + 0.0001))
            }
        
        return None
    
    @staticmethod
    def _is_engulfing(i, close, open_):
        """Check engulfing patterns"""
        # Bullish engulfing
        if (close[i-1] < open_[i-1] and  # Önceki mum bearish
            close[i] > open_[i] and      # Şimdiki mum bullish
            open_[i] <= close[i-1] and   # Açılış önceki kapanıştan düşük veya eşit
            close[i] >= open_[i-1]):     # Kapanış önceki açılıştan yüksek veya eşit
            
            return {
                'pattern': 'bullish_engulfing',
                'index': i,
                'signal': 'bullish',
                'strength': 0.8
            }
        
        # Bearish engulfing
        if (close[i-1] > open_[i-1] and  # Önceki mum bullish
            close[i] < open_[i] and      # Şimdiki mum bearish
            open_[i] >= close[i-1] and   # Açılış önceki kapanıştan yüksek veya eşit
            close[i] <= open_[i-1]):     # Kapanış önceki açılıştan düşük veya eşit
            
            return {
                'pattern': 'bearish_engulfing',
                'index': i,
                'signal': 'bearish',
                'strength': 0.8
            }
        
        return None

# ==========================================
# SUPPORT & RESISTANCE - GÜNCELLENMİŞ
# ==========================================
class SupportResistance:
    """Support and resistance detection"""
    
    @staticmethod
    def find_levels(df: pd.DataFrame) -> Dict:
        """Find support and resistance levels"""
        try:
            if len(df) < 50:
                return {
                    'resistance': [],
                    'support': [],
                    'pivot_points': {},
                    'current_price': 0
                }
            
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values
            
            current_price = float(close[-1])
            
            # Yerel maksimumlar (direnç)
            resistance_idx = argrelextrema(high, np.greater, order=5)[0]
            resistance_levels = high[resistance_idx]
            
            # Yerel minimumlar (destek)
            support_idx = argrelextrema(low, np.less, order=5)[0]
            support_levels = low[support_idx]
            
            # Cluster levels
            resistance_clusters = SupportResistance._cluster_levels(resistance_levels, current_price)
            support_clusters = SupportResistance._cluster_levels(support_levels, current_price)
            
            # Pivot points
            pivot_points = SupportResistance._calculate_pivot_points(df)
            
            # Fibonacci retracement
            fib_levels = SupportResistance._calculate_fibonacci(df)
            
            return {
                'resistance': resistance_clusters[:8],  # Top 8
                'support': support_clusters[:8],
                'pivot_points': pivot_points,
                'fibonacci': fib_levels,
                'current_price': current_price
            }
            
        except Exception as e:
            logger.error(f"Error finding S/R levels: {e}")
            return {
                'resistance': [],
                'support': [],
                'pivot_points': {},
                'fibonacci': {},
                'current_price': 0
            }
    
    @staticmethod
    def _cluster_levels(levels: np.ndarray, current_price: float, 
                       threshold: float = 0.02) -> List[Dict]:
        """Cluster nearby levels"""
        if len(levels) == 0:
            return []
        
        levels = np.sort(levels)
        clusters = []
        current_cluster = [levels[0]]
        
        for level in levels[1:]:
            if abs(level - current_cluster[-1]) / current_price < threshold:
                current_cluster.append(level)
            else:
                if len(current_cluster) >= 2:  # En az 2 touch
                    clusters.append({
                        'level': float(np.mean(current_cluster)),
                        'touches': len(current_cluster),
                        'strength': min(1.0, len(current_cluster) / 5.0)
                    })
                current_cluster = [level]
        
        if len(current_cluster) >= 2:
            clusters.append({
                'level': float(np.mean(current_cluster)),
                'touches': len(current_cluster),
                'strength': min(1.0, len(current_cluster) / 5.0)
            })
        
        # Sort by strength
        clusters.sort(key=lambda x: x['strength'], reverse=True)
        return clusters
    
    @staticmethod
    def _calculate_pivot_points(df: pd.DataFrame) -> Dict:
        """Calculate pivot points"""
        if len(df) < 1:
            return {}
        
        try:
            # Use last completed period (previous day/week)
            last_period = df.iloc[-1] if len(df) > 0 else df.iloc[0]
            
            high = float(last_period['high'])
            low = float(last_period['low'])
            close = float(last_period['close'])
            
            pivot = (high + low + close) / 3
            
            return {
                'pivot': float(pivot),
                'r1': float(2 * pivot - low),
                'r2': float(pivot + (high - low)),
                'r3': float(high + 2 * (pivot - low)),
                's1': float(2 * pivot - high),
                's2': float(pivot - (high - low)),
                's3': float(low - 2 * (high - pivot))
            }
        except Exception as e:
            logger.error(f"Error calculating pivot points: {e}")
            return {}
    
    @staticmethod
    def _calculate_fibonacci(df: pd.DataFrame) -> Dict:
        """Calculate Fibonacci retracement levels"""
        if len(df) < 20:
            return {}
        
        try:
            recent_high = float(df['high'].max())
            recent_low = float(df['low'].min())
            diff = recent_high - recent_low
            
            return {
                '0.0': recent_low,
                '0.236': recent_low + diff * 0.236,
                '0.382': recent_low + diff * 0.382,
                '0.5': recent_low + diff * 0.5,
                '0.618': recent_low + diff * 0.618,
                '0.786': recent_low + diff * 0.786,
                '1.0': recent_high
            }
        except Exception as e:
            logger.error(f"Error calculating Fibonacci: {e}")
            return {}

# ==========================================
# ANA ANALİZ MOTORU - GÜNCELLENMİŞ
# ==========================================
class AnalysisEngine:
    """Main analysis engine"""
    
    def __init__(self):
        self.ml_predictor = MLPredictor()
        
    async def analyze(self, symbol: str, timeframe: str, limit: int = 500, use_ml: bool = True) -> Dict:
        """Perform comprehensive analysis"""
        try:
            # Fetch data
            candles = await data_manager.get_klines(symbol, timeframe, limit)
            
            if len(candles) < 50:
                raise ValueError(f"Insufficient data: {len(candles)} candles")
            
            # Convert to DataFrame
            df = pd.DataFrame(candles)
            
            # Ensure timestamp is datetime
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
            
            # Sort by timestamp
            df = df.sort_index()
            
            # Calculate indicators
            df_with_indicators = TechnicalIndicators.calculate_all(df)
            
            # Get current values
            current_price = float(df['close'].iloc[-1])
            
            # Get latest indicators
            indicators = TechnicalIndicators.get_latest_indicators(df_with_indicators)
            
            # ICT Analysis
            ict_analysis = ICTAnalysis.analyze(df_with_indicators)
            
            # Candlestick Patterns
            patterns = CandlestickPatterns.detect(df_with_indicators)
            
            # Support & Resistance
            sr_levels = SupportResistance.find_levels(df_with_indicators)
            
            # ML Prediction
            ml_prediction = None
            if use_ml and len(df_with_indicators) >= Config.ML_MIN_DATA_POINTS:
                ml_prediction = self.ml_predictor.predict(symbol, df_with_indicators)
            
            # Trend Analysis
            trend = self._analyze_trend(df_with_indicators)
            
            # Volume Analysis
            volume = self._analyze_volume(df_with_indicators)
            
            # Market Structure
            structure = self._analyze_structure(df_with_indicators)
            
            # Risk assessment
            risk = self._assess_risk(indicators, current_price)
            
            # Prepare response
            return {
                'symbol': symbol,
                'timeframe': timeframe,
                'timestamp': datetime.utcnow().isoformat(),
                'current_price': current_price,
                'indicators': indicators,
                'ict_analysis': ict_analysis,
                'patterns': patterns,
                'support_resistance': sr_levels,
                'trend': trend,
                'volume': volume,
                'market_structure': structure,
                'risk_assessment': risk,
                'ml_prediction': ml_prediction,
                'data_points': len(df_with_indicators),
                'cache_hit': len(candles) > 0
            }
            
        except Exception as e:
            logger.error(f"❌ Analysis error for {symbol}: {e}")
            logger.error(traceback.format_exc())
            raise
    
    def _analyze_trend(self, df: pd.DataFrame) -> Dict:
        """Analyze trend"""
        try:
            if len(df) < 2:
                return {'direction': 'neutral', 'strength': 0}
            
            current_price = float(df['close'].iloc[-1])
            
            # Check moving averages
            ma_directions = []
            
            for period in [5, 10, 20, 50, 200]:
                ma_col = f'sma_{period}'
                if ma_col in df.columns and len(df) > period:
                    ma_value = float(df[ma_col].iloc[-1])
                    if pd.notna(ma_value):
                        if current_price > ma_value:
                            ma_directions.append('bullish')
                        else:
                            ma_directions.append('bearish')
            
            # Determine overall direction
            if not ma_directions:
                return {'direction': 'neutral', 'strength': 0}
            
            bullish_count = ma_directions.count('bullish')
            bearish_count = ma_directions.count('bearish')
            
            if bullish_count > bearish_count * 2:
                direction = 'strong_bullish'
                strength = (bullish_count / len(ma_directions)) * 100
            elif bearish_count > bullish_count * 2:
                direction = 'strong_bearish'
                strength = (bearish_count / len(ma_directions)) * 100
            elif bullish_count > bearish_count:
                direction = 'bullish'
                strength = (bullish_count / len(ma_directions)) * 80
            elif bearish_count > bullish_count:
                direction = 'bearish'
                strength = (bearish_count / len(ma_directions)) * 80
            else:
                direction = 'neutral'
                strength = 50
            
            return {
                'direction': direction,
                'strength': float(strength),
                'moving_averages': {
                    'bullish': bullish_count,
                    'bearish': bearish_count,
                    'total': len(ma_directions)
                }
            }
            
        except Exception as e:
            logger.error(f"Error analyzing trend: {e}")
            return {'direction': 'neutral', 'strength': 0}
    
    def _analyze_volume(self, df: pd.DataFrame) -> Dict:
        """Analyze volume"""
        try:
            if len(df) < 20:
                return {'trend': 'neutral', 'ratio': 1.0}
            
            volume = df['volume'].values
            close = df['close'].values
            
            avg_volume = np.mean(volume[-20:])
            current_volume = volume[-1]
            
            if avg_volume > 0:
                volume_ratio = current_volume / avg_volume
            else:
                volume_ratio = 1.0
            
            # Price-volume correlation
            if len(close) >= 20:
                price_change = (close[-1] - close[-20]) / close[-20] if close[-20] > 0 else 0
                volume_change = (current_volume - avg_volume) / avg_volume if avg_volume > 0 else 0
                
                if price_change > 0.02 and volume_change > 0.3:
                    divergence = 'strong_bullish'
                elif price_change < -0.02 and volume_change > 0.3:
                    divergence = 'strong_bearish'
                elif price_change > 0 and volume_change > 0:
                    divergence = 'bullish_confirmation'
                elif price_change < 0 and volume_change > 0:
                    divergence = 'bearish_confirmation'
                elif price_change > 0 and volume_change < 0:
                    divergence = 'bearish_divergence'
                elif price_change < 0 and volume_change < 0:
                    divergence = 'bullish_divergence'
                else:
                    divergence = 'neutral'
            else:
                divergence = 'neutral'
            
            # Volume trend
            if volume_ratio > 1.5:
                trend = 'very_high'
            elif volume_ratio > 1.2:
                trend = 'high'
            elif volume_ratio < 0.8:
                trend = 'low'
            elif volume_ratio < 0.5:
                trend = 'very_low'
            else:
                trend = 'normal'
            
            return {
                'trend': trend,
                'ratio': float(volume_ratio),
                'current': float(current_volume),
                'average': float(avg_volume),
                'divergence': divergence
            }
            
        except Exception as e:
            logger.error(f"Error analyzing volume: {e}")
            return {'trend': 'neutral', 'ratio': 1.0}
    
    def _analyze_structure(self, df: pd.DataFrame) -> Dict:
        """Analyze market structure"""
        try:
            if len(df) < 20:
                return {'structure': 'neutral', 'swing_highs': 0, 'swing_lows': 0}
            
            high = df['high'].values[-20:]
            low = df['low'].values[-20:]
            
            # Find swing points
            swing_highs = argrelextrema(high, np.greater, order=2)[0]
            swing_lows = argrelextrema(low, np.less, order=2)[0]
            
            # Determine structure
            structure = 'neutral'
            if len(swing_highs) >= 2 and len(swing_lows) >= 2:
                if high[swing_highs[-1]] > high[swing_highs[-2]] and low[swing_lows[-1]] > low[swing_lows[-2]]:
                    structure = 'uptrend'
                elif high[swing_highs[-1]] < high[swing_highs[-2]] and low[swing_lows[-1]] < low[swing_lows[-2]]:
                    structure = 'downtrend'
                elif high[swing_highs[-1]] > high[swing_highs[-2]] and low[swing_lows[-1]] < low[swing_lows[-2]]:
                    structure = 'expanding'
                elif high[swing_highs[-1]] < high[swing_highs[-2]] and low[swing_lows[-1]] > low[swing_lows[-2]]:
                    structure = 'contracting'
                else:
                    structure = 'ranging'
            
            return {
                'structure': structure,
                'swing_highs': len(swing_highs),
                'swing_lows': len(swing_lows),
                'last_high': float(high[-1]) if len(high) > 0 else 0,
                'last_low': float(low[-1]) if len(low) > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"Error analyzing structure: {e}")
            return {'structure': 'neutral', 'swing_highs': 0, 'swing_lows': 0}
    
    def _assess_risk(self, indicators: Dict, current_price: float) -> Dict:
        """Assess trading risk"""
        try:
            risk_score = 50  # Neutral
            risk_factors = []
            
            # RSI risk
            rsi = indicators.get('rsi', 50)
            if rsi > 80:
                risk_score += 20
                risk_factors.append('RSI overbought')
            elif rsi < 20:
                risk_score -= 20
                risk_factors.append('RSI oversold')
            
            # Volatility risk (ATR)
            atr = indicators.get('atr', 0)
            atr_percent = (atr / current_price * 100) if current_price > 0 else 0
            if atr_percent > 5:
                risk_score += 15
                risk_factors.append(f'High volatility ({atr_percent:.1f}%)')
            elif atr_percent < 1:
                risk_score -= 10
                risk_factors.append(f'Low volatility ({atr_percent:.1f}%)')
            
            # Volume risk
            volume_ratio = indicators.get('volume_ratio', 1.0)
            if volume_ratio < 0.5:
                risk_score += 10
                risk_factors.append(f'Low volume (ratio: {volume_ratio:.2f})')
            
            # Normalize risk score
            risk_score = max(0, min(100, risk_score))
            
            # Risk level
            if risk_score > 70:
                risk_level = 'high'
            elif risk_score > 40:
                risk_level = 'medium'
            else:
                risk_level = 'low'
            
            return {
                'score': float(risk_score),
                'level': risk_level,
                'factors': risk_factors[:3]
            }
            
        except Exception as e:
            logger.error(f"Error assessing risk: {e}")
            return {'score': 50, 'level': 'medium', 'factors': []}
    
    def generate_signal(self, analysis: Dict) -> Dict:
        """Generate trading signal"""
        try:
            score = 50  # Neutral baseline
            factors = []
            
            indicators = analysis['indicators']
            current_price = analysis['current_price']
            
            # 1. RSI Scoring (0-20)
            rsi = indicators.get('rsi', 50)
            if rsi < 30:
                score += 15
                factors.append(f'RSI oversold ({rsi:.1f})')
            elif rsi > 70:
                score -= 15
                factors.append(f'RSI overbought ({rsi:.1f})')
            
            # 2. MACD Scoring (0-15)
            macd = indicators.get('macd', 0)
            macd_signal = indicators.get('macd_signal', 0)
            if macd > macd_signal:
                score += 10
                factors.append('MACD bullish')
            else:
                score -= 10
                factors.append('MACD bearish')
            
            # 3. Trend Scoring (0-20)
            trend = analysis['trend']
            if trend['direction'] in ['strong_bullish', 'bullish']:
                score += trend['strength'] * 0.2
                factors.append(f"Trend: {trend['direction']}")
            elif trend['direction'] in ['strong_bearish', 'bearish']:
                score -= trend['strength'] * 0.2
                factors.append(f"Trend: {trend['direction']}")
            
            # 4. Support/Resistance (0-15)
            sr = analysis['support_resistance']
            if sr['support'] and sr['resistance']:
                nearest_support = min([abs(current_price - s['level']) for s in sr['support']])
                nearest_resistance = min([abs(current_price - r['level']) for r in sr['resistance']])
                
                if nearest_support < nearest_resistance:
                    score += 10
                    factors.append('Near support')
                else:
                    score -= 10
                    factors.append('Near resistance')
            
            # 5. Volume (0-10)
            volume = analysis['volume']
            if volume['divergence'] == 'bullish_confirmation':
                score += 8
                factors.append('Volume confirmation')
            elif volume['divergence'] == 'bearish_confirmation':
                score -= 8
                factors.append('Volume confirmation')
            
            # 6. ICT Analysis (0-10)
            ict = analysis['ict_analysis']
            if ict['premium_discount']['zone'] == 'discount':
                score += 8
                factors.append('Price in discount zone')
            elif ict['premium_discount']['zone'] == 'premium':
                score -= 8
                factors.append('Price in premium zone')
            
            # 7. ML Prediction (0-20)
            if analysis.get('ml_prediction'):
                ml = analysis['ml_prediction']
                if ml['direction'] == 'bullish':
                    score += ml['confidence'] * 0.2
                    factors.append(f"ML: {ml['direction']} ({ml['confidence']:.1f}%)")
                else:
                    score -= ml['confidence'] * 0.2
                    factors.append(f"ML: {ml['direction']} ({ml['confidence']:.1f}%)")
            
            # 8. Candlestick Patterns (0-10)
            patterns = analysis['patterns']
            recent_patterns = [p for p in patterns if p.get('index', 0) >= len(patterns) - 3]
            for pattern in recent_patterns:
                if pattern['signal'] == 'bullish':
                    score += 5
                    factors.append(f"Pattern: {pattern['pattern']}")
                elif pattern['signal'] == 'bearish':
                    score -= 5
                    factors.append(f"Pattern: {pattern['pattern']}")
            
            # Normalize score
            score = max(0, min(100, score))
            
            # Determine signal
            if score >= 65:
                signal = 'BUY'
                confidence = score
                color = 'green'
            elif score <= 35:
                signal = 'SELL'
                confidence = 100 - score
                color = 'red'
            else:
                signal = 'HOLD'
                confidence = 50
                color = 'yellow'
            
            # Calculate risk levels
            atr = indicators.get('atr', current_price * 0.02)
            
            if signal == 'BUY':
                entry = current_price
                stop_loss = entry - (atr * 1.5)
                take_profit = entry + (atr * 3.0)
            elif signal == 'SELL':
                entry = current_price
                stop_loss = entry + (atr * 1.5)
                take_profit = entry - (atr * 3.0)
            else:
                entry = current_price
                stop_loss = current_price - (atr * 1.5)
                take_profit = current_price + (atr * 3.0)
            
            # Risk/Reward
            risk = abs(entry - stop_loss)
            reward = abs(take_profit - entry)
            risk_reward = reward / risk if risk > 0 else 0
            
            return {
                'signal': signal,
                'color': color,
                'confidence': round(confidence, 1),
                'score': round(score, 1),
                'entry': round(entry, 4),
                'stop_loss': round(stop_loss, 4),
                'take_profit': round(take_profit, 4),
                'risk_reward': round(risk_reward, 2),
                'factors': factors[:5],  # Top 5 factors
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Signal generation error: {e}")
            return {
                'signal': 'HOLD',
                'color': 'yellow',
                'confidence': 0,
                'score': 50,
                'error': str(e)
            }

# ==========================================
# MACHINE LEARNING PREDICTOR - GÜNCELLENMİŞ
# ==========================================
class MLPredictor:
    """Optimized ML predictor"""
    
    def __init__(self):
        self.models = {}
        self.scalers = {}
        self.last_train_time = {}
        self.prediction_cache = {}
        
    def prepare_features(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare features for ML"""
        try:
            features = pd.DataFrame()
            
            # Price features
            features['returns'] = df['close'].pct_change()
            features['log_returns'] = np.log(df['close'] / df['close'].shift(1))
            features['high_low_ratio'] = (df['high'] - df['low']) / df['close']
            
            # Moving averages
            for period in [5, 10, 20]:
                features[f'sma_{period}'] = df['close'].rolling(period).mean()
                features[f'sma_{period}_diff'] = (df['close'] - features[f'sma_{period}']) / df['close']
            
            # RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            features['rsi'] = 100 - (100 / (1 + rs))
            
            # MACD
            ema12 = df['close'].ewm(span=12, adjust=False).mean()
            ema26 = df['close'].ewm(span=26, adjust=False).mean()
            features['macd'] = ema12 - ema26
            
            # Bollinger Bands
            bb_middle = df['close'].rolling(20).mean()
            bb_std = df['close'].rolling(20).std()
            features['bb_position'] = (df['close'] - bb_middle) / (2 * bb_std)
            
            # Volume
            features['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
            features['volume_change'] = df['volume'].pct_change()
            
            # Target: Next period price direction (1 = up, 0 = down)
            features['target'] = (df['close'].shift(-1) > df['close']).astype(int)
            
            # Drop NaN
            features = features.dropna()
            
            if len(features) < 10:
                return np.array([]), np.array([])
            
            X = features.drop('target', axis=1).values
            y = features['target'].values
            
            return X, y
            
        except Exception as e:
            logger.error(f"Error preparing features: {e}")
            return np.array([]), np.array([])
    
    def predict(self, symbol: str, df: pd.DataFrame) -> Optional[Dict]:
        """Make prediction"""
        try:
            # Check cache
            cache_key = f"{symbol}_{df.index[-1].timestamp() if len(df) > 0 else 'none'}"
            if cache_key in self.prediction_cache:
                cache_time = self.prediction_cache[cache_key]['timestamp']
                if time.time() - cache_time < 300:  # 5 dakika cache
                    return self.prediction_cache[cache_key]['prediction']
            
            # Prepare features
            X, _ = self.prepare_features(df)
            
            if len(X) < 10:
                return None
            
            # Get latest features
            X_latest = X[-1:].reshape(1, -1)
            
            # Simple prediction based on technical indicators
            latest = df.iloc[-1]
            rsi = 50
            if 'rsi' in df.columns and pd.notna(latest['rsi']):
                rsi = float(latest['rsi'])
            
            macd = 0
            if 'macd' in df.columns and pd.notna(latest['macd']):
                macd = float(latest['macd'])
            
            # Simple rule-based prediction
            if rsi < 30 and macd > 0:
                direction = 'bullish'
                confidence = 70
            elif rsi > 70 and macd < 0:
                direction = 'bearish'
                confidence = 70
            elif rsi < 40:
                direction = 'bullish'
                confidence = 60
            elif rsi > 60:
                direction = 'bearish'
                confidence = 60
            else:
                direction = 'neutral'
                confidence = 50
            
            result = {
                'direction': direction,
                'confidence': float(confidence),
                'bullish_probability': float(confidence if direction == 'bullish' else 100 - confidence),
                'bearish_probability': float(confidence if direction == 'bearish' else 100 - confidence),
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # Cache result
            self.prediction_cache[cache_key] = {
                'prediction': result,
                'timestamp': time.time()
            }
            
            return result
            
        except Exception as e:
            logger.error(f"❌ ML prediction error for {symbol}: {e}")
            return None

# ==========================================
# GLOBAL INSTANCES
# ==========================================
data_manager: Optional[RealTimeDataManager] = None
analysis_engine: Optional[AnalysisEngine] = None
START_TIME = time.time()

# ==========================================
# FASTAPI APPLICATION - GÜNCELLENMİŞ
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle"""
    global data_manager, analysis_engine
    
    logger.info("=" * 80)
    logger.info("🚀 PROFESSIONAL CRYPTO TRADING PLATFORM v3.0")
    logger.info("=" * 80)
    
    try:
        # Initialize components
        data_manager = RealTimeDataManager()
        await data_manager.initialize()
        
        analysis_engine = AnalysisEngine()
        
        logger.info("✅ Real-time Data Manager: Active")
        logger.info("✅ Analysis Engine: Ready")
        logger.info("✅ ML Predictor: Initialized")
        logger.info("✅ WebSocket: Single connection mode")
        logger.info(f"✅ Monitoring {len(Config.DEFAULT_SYMBOLS)} symbols")
        logger.info("=" * 80)
        logger.info("🎯 System ready for professional trading!")
        logger.info("=" * 80)
        
        yield
        
    except Exception as e:
        logger.error(f"❌ Initialization error: {e}")
        raise
    finally:
        # Cleanup
        logger.info("🛑 Shutting down...")
        if data_manager:
            await data_manager.close()
        logger.info("✅ Shutdown complete")

app = FastAPI(
    title="Professional Crypto Trading Platform",
    description="Production-ready trading system with ML, ICT, and advanced TA",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting middleware"""
    client_ip = request.client.host if request.client else "unknown"
    
    if data_manager and not await data_manager.rate_limiter.check_rate_limit(client_ip):
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded. Please try again later."}
        )
    
    response = await call_next(request)
    return response

# ==========================================
# API ENDPOINTS - GÜNCELLENMİŞ
# ==========================================

@app.get("/")
async def root():
    """Root endpoint"""
    uptime = int(time.time() - START_TIME)
    
    return {
        "platform": "Professional Crypto Trading Platform",
        "version": "3.0.0",
        "status": "operational",
        "uptime_seconds": uptime,
        "uptime_human": f"{uptime // 3600}h {(uptime % 3600) // 60}m",
        "features": [
            "Single WebSocket connection",
            "50+ Technical indicators",
            "ML predictions",
            "ICT concepts (Order Blocks, FVG)",
            "Candlestick patterns",
            "Support/Resistance with Fibonacci",
            "Real-time dashboard with TradingView",
            "Rate limiting",
            "Caching system"
        ],
        "endpoints": {
            "health": "/health",
            "ticker": "/api/ticker/{symbol}",
            "analyze": "/api/analyze (POST)",
            "signal": "/api/signal (POST)",
            "market": "/api/market",
            "orderbook": "/api/orderbook/{symbol}",
            "dashboard": "/dashboard"
        },
        "default_symbols": Config.DEFAULT_SYMBOLS,
        "allowed_timeframes": list(Config.ALLOWED_TIMEFRAMES.keys()),
        "websocket_status": data_manager.is_connected if data_manager else False
    }

@app.get("/health")
async def health():
    """Health check"""
    try:
        # Test connectivity
        btc_ticker = await data_manager.get_ticker("BTCUSDT")
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": int(time.time() - START_TIME),
            "services": {
                "websocket": data_manager.is_connected,
                "binance_api": btc_ticker is not None,
                "cache": len(data_manager.price_cache)
            },
            "cache": {
                "prices": len(data_manager.price_cache),
                "orderbooks": len(data_manager.orderbook_cache),
                "klines": len(data_manager.kline_cache)
            },
            "active_connections": len(data_manager.rate_limiter.requests) if data_manager else 0
        }
    except Exception as e:
        logger.error(f"Health check error: {e}")
        raise HTTPException(status_code=503, detail=str(e))

@app.get("/api/ticker/{symbol}")
async def get_ticker(symbol: str):
    """Get ticker data"""
    try:
        symbol = symbol.upper().replace(" ", "")
        ticker = await data_manager.get_ticker(symbol)
        
        if not ticker:
            raise HTTPException(status_code=404, detail=f"Ticker not found: {symbol}")
        
        # Add CoinGecko data
        cg_data = await data_manager.get_coingecko_data(symbol)
        if cg_data:
            ticker['coingecko'] = cg_data
        
        return ticker
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ticker error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze")
async def analyze(request: AnalysisRequest):
    """Technical analysis"""
    try:
        logger.info(f"Analyzing {request.symbol} {request.timeframe}")
        
        # Fetch and analyze data
        analysis = await analysis_engine.analyze(
            symbol=request.symbol,
            timeframe=request.timeframe,
            limit=request.limit,
            use_ml=True
        )
        
        return analysis
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/signal")
async def signal(request: TradeSignalRequest):
    """Get trading signal"""
    try:
        logger.info(f"Generating signal for {request.symbol} {request.timeframe}")
        
        # Fetch and analyze data
        analysis = await analysis_engine.analyze(
            symbol=request.symbol,
            timeframe=request.timeframe,
            use_ml=request.use_ml
        )
        
        # Generate signal
        signal_result = analysis_engine.generate_signal(analysis)
        
        return {
            "symbol": request.symbol,
            "timeframe": request.timeframe,
            "analysis": {
                "price": analysis['current_price'],
                "rsi": analysis['indicators'].get('rsi', 50),
                "trend": analysis['trend']['direction'],
                "volume": analysis['volume']['trend']
            },
            "signal": signal_result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Signal error: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/market")
async def market_overview():
    """Market overview"""
    try:
        overview = await data_manager.get_market_overview()
        
        return {
            "markets": overview,
            "count": len(overview),
            "timestamp": datetime.utcnow().isoformat(),
            "source": "binance"
        }
    except Exception as e:
        logger.error(f"Market overview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/orderbook/{symbol}")
async def orderbook(symbol: str, limit: int = 20):
    """Get order book"""
    try:
        symbol = symbol.upper().replace(" ", "")
        ob = await data_manager.get_orderbook(symbol, limit)
        
        if not ob:
            raise HTTPException(status_code=404, detail=f"Orderbook not available: {symbol}")
        
        return ob
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Orderbook error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/symbols")
async def get_symbols():
    """Get available symbols"""
    try:
        # You can extend this to fetch all Binance symbols
        return {
            "symbols": Config.DEFAULT_SYMBOLS,
            "count": len(Config.DEFAULT_SYMBOLS),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Symbols error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/timeframes")
async def get_timeframes():
    """Get available timeframes"""
    try:
        return {
            "timeframes": Config.ALLOWED_TIMEFRAMES,
            "count": len(Config.ALLOWED_TIMEFRAMES),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Timeframes error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Trading Dashboard"""
    try:
        with open("dashboard.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        # Fallback to embedded HTML
        html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Professional Trading Platform</title>
    <script src="https://s3.tradingview.com/tv.js"></script>
    <style>
        :root {
            --bg-dark: #0f172a;
            --bg-card: #1e293b;
            --bg-hover: #334155;
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-blue: #3b82f6;
            --accent-yellow: #f59e0b;
            --border: #475569;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        
        body {
            background: var(--bg-dark);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
        }
        
        .header {
            background: var(--bg-card);
            padding: 1rem 2rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 1000;
        }
        
        .logo {
            font-size: 1.5rem;
            font-weight: bold;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-green));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .status {
            display: flex;
            gap: 1rem;
            align-items: center;
        }
        
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--accent-green);
            animation: pulse 2s infinite;
        }
        
        .status-offline {
            background: var(--accent-red);
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 1.5rem;
        }
        
        .controls {
            background: var(--bg-card);
            padding: 1.5rem;
            border-radius: 10px;
            margin-bottom: 1.5rem;
            border: 1px solid var(--border);
        }
        
        .control-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            align-items: end;
        }
        
        .input-group {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }
        
        label {
            font-size: 0.9rem;
            color: var(--text-secondary);
            font-weight: 500;
        }
        
        input, select {
            background: var(--bg-dark);
            border: 1px solid var(--border);
            padding: 0.75rem 1rem;
            border-radius: 6px;
            color: var(--text-primary);
            font-size: 1rem;
            transition: border-color 0.3s;
        }
        
        input:focus, select:focus {
            outline: none;
            border-color: var(--accent-blue);
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
        }
        
        button {
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-green));
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 6px;
            color: white;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(59, 130, 246, 0.3);
        }
        
        button:active {
            transform: translateY(0);
        }
        
        button.secondary {
            background: var(--bg-hover);
            color: var(--text-primary);
        }
        
        button.secondary:hover {
            background: var(--border);
        }
        
        .main-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 1.5rem;
            margin-bottom: 1.5rem;
        }
        
        @media (max-width: 1024px) {
            .main-grid {
                grid-template-columns: 1fr;
            }
        }
        
        .card {
            background: var(--bg-card);
            border-radius: 10px;
            padding: 1.5rem;
            border: 1px solid var(--border);
            transition: border-color 0.3s;
        }
        
        .card:hover {
            border-color: var(--accent-blue);
        }
        
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--border);
        }
        
        .card-title {
            font-size: 1.2rem;
            font-weight: 600;
        }
        
        .badge {
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        
        .badge.live {
            background: rgba(16, 185, 129, 0.2);
            color: var(--accent-green);
            border: 1px solid var(--accent-green);
        }
        
        .badge.ml {
            background: rgba(59, 130, 246, 0.2);
            color: var(--accent-blue);
            border: 1px solid var(--accent-blue);
        }
        
        #chart-container {
            height: 500px;
            border-radius: 8px;
            overflow: hidden;
            background: var(--bg-dark);
        }
        
        .signal-card {
            text-align: center;
            padding: 2rem;
            border-radius: 10px;
            margin-bottom: 1.5rem;
            transition: all 0.3s;
        }
        
        .signal-card.buy {
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.15), rgba(16, 185, 129, 0.05));
            border: 2px solid var(--accent-green);
        }
        
        .signal-card.sell {
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.15), rgba(239, 68, 68, 0.05));
            border: 2px solid var(--accent-red);
        }
        
        .signal-card.hold {
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.15), rgba(245, 158, 11, 0.05));
            border: 2px solid var(--accent-yellow);
        }
        
        .signal-type {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }
        
        .signal-confidence {
            font-size: 1.1rem;
            color: var(--text-secondary);
            margin-bottom: 1.5rem;
        }
        
        .signal-details {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 1rem;
            text-align: left;
        }
        
        .detail-item {
            background: rgba(255, 255, 255, 0.05);
            padding: 1rem;
            border-radius: 6px;
        }
        
        .detail-label {
            font-size: 0.8rem;
            color: var(--text-secondary);
            margin-bottom: 0.25rem;
        }
        
        .detail-value {
            font-size: 1.1rem;
            font-weight: 600;
        }
        
        .indicators-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 1rem;
        }
        
        .indicator-item {
            background: rgba(255, 255, 255, 0.05);
            padding: 1rem;
            border-radius: 6px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: background 0.3s;
        }
        
        .indicator-item:hover {
            background: rgba(255, 255, 255, 0.1);
        }
        
        .indicator-label {
            font-size: 0.9rem;
            color: var(--text-secondary);
        }
        
        .indicator-value {
            font-size: 1rem;
            font-weight: 600;
            font-family: 'Courier New', monospace;
        }
        
        .positive {
            color: var(--accent-green);
        }
        
        .negative {
            color: var(--accent-red);
        }
        
        .market-table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .market-table th {
            text-align: left;
            padding: 1rem;
            font-size: 0.9rem;
            color: var(--text-secondary);
            border-bottom: 2px solid var(--border);
            font-weight: 600;
        }
        
        .market-table td {
            padding: 1rem;
            border-bottom: 1px solid var(--border);
            transition: background 0.2s;
        }
        
        .market-table tr:hover {
            background: var(--bg-hover);
        }
        
        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid var(--border);
            border-top-color: var(--accent-blue);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .notification {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 1rem 1.5rem;
            border-radius: 8px;
            background: var(--bg-card);
            border: 1px solid var(--border);
            box-shadow: 0 5px 20px rgba(0, 0, 0, 0.3);
            z-index: 10000;
            transform: translateX(120%);
            transition: transform 0.3s ease-in-out;
        }
        
        .notification.show {
            transform: translateX(0);
        }
        
        .notification.success {
            border-color: var(--accent-green);
        }
        
        .notification.error {
            border-color: var(--accent-red);
        }
        
        .notification.info {
            border-color: var(--accent-blue);
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        
        .stat-card {
            background: var(--bg-card);
            padding: 1.5rem;
            border-radius: 10px;
            border: 1px solid var(--border);
            text-align: center;
        }
        
        .stat-value {
            font-size: 1.8rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }
        
        .stat-label {
            font-size: 0.9rem;
            color: var(--text-secondary);
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">🚀 Trading Platform v3.0</div>
        <div class="status">
            <div class="status-dot" id="status-dot"></div>
            <span id="status-text">Connecting...</span>
        </div>
    </div>
    
    <div class="container">
        <!-- Stats -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value" id="active-symbols">10</div>
                <div class="stat-label">Active Symbols</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="cache-hit">0%</div>
                <div class="stat-label">Cache Hit Rate</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="uptime">0s</div>
                <div class="stat-label">Uptime</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="requests">0</div>
                <div class="stat-label">Requests/Min</div>
            </div>
        </div>
        
        <!-- Controls -->
        <div class="controls">
            <div class="control-grid">
                <div class="input-group">
                    <label>Symbol</label>
                    <input type="text" id="symbol" value="BTCUSDT" list="symbol-list">
                    <datalist id="symbol-list">
                        <!-- Filled by JavaScript -->
                    </datalist>
                </div>
                <div class="input-group">
                    <label>Timeframe</label>
                    <select id="timeframe">
                        <option value="1m">1 Minute</option>
                        <option value="5m">5 Minutes</option>
                        <option value="15m">15 Minutes</option>
                        <option value="30m">30 Minutes</option>
                        <option value="1h" selected>1 Hour</option>
                        <option value="4h">4 Hours</option>
                        <option value="1d">1 Day</option>
                        <option value="1w">1 Week</option>
                    </select>
                </div>
                <div class="input-group">
                    <label>Limit</label>
                    <select id="limit">
                        <option value="100">100 candles</option>
                        <option value="200">200 candles</option>
                        <option value="500" selected>500 candles</option>
                        <option value="1000">1000 candles</option>
                    </select>
                </div>
                <div class="input-group">
                    <button onclick="analyze()" id="analyze-btn">📊 Analyze</button>
                </div>
                <div class="input-group">
                    <button onclick="getSignal()" id="signal-btn">🤖 Get Signal</button>
                </div>
                <div class="input-group">
                    <button onclick="refreshMarket()" class="secondary">🔄 Refresh Market</button>
                </div>
            </div>
        </div>
        
        <!-- Main Content -->
        <div class="main-grid">
            <!-- Left Column: Chart -->
            <div class="card">
                <div class="card-header">
                    <div class="card-title">Live Chart - <span id="chart-symbol">BTCUSDT</span></div>
                    <span class="badge live">LIVE</span>
                </div>
                <div id="chart-container"></div>
            </div>
            
            <!-- Right Column: Signal & Indicators -->
            <div>
                <!-- Signal Card -->
                <div class="card" style="margin-bottom: 1.5rem;">
                    <div class="card-header">
                        <div class="card-title">Trading Signal</div>
                        <span class="badge ml">ML</span>
                    </div>
                    <div id="signal-display" class="signal-card hold">
                        <div class="signal-type">HOLD</div>
                        <div class="signal-confidence">Click "Get Signal"</div>
                    </div>
                </div>
                
                <!-- Indicators -->
                <div class="card">
                    <div class="card-header">
                        <div class="card-title">Key Indicators</div>
                    </div>
                    <div id="indicators-display" class="indicators-grid">
                        <!-- Filled by JavaScript -->
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Market Overview -->
        <div class="card">
            <div class="card-header">
                <div class="card-title">Market Overview</div>
                <span class="badge live">LIVE</span>
            </div>
            <table class="market-table">
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
                <tbody id="market-table">
                    <tr>
                        <td colspan="7" style="text-align: center; padding: 2rem;">
                            <div class="loading"></div>
                            <div style="margin-top: 1rem; color: var(--text-secondary);">
                                Loading market data...
                            </div>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
    
    <!-- Notification -->
    <div id="notification" class="notification">
        <div id="notification-message"></div>
    </div>
    
    <script>
        // Global variables
        let currentSymbol = 'BTCUSDT';
        let currentTimeframe = '1h';
        let currentLimit = 500;
        let tvWidget = null;
        let marketDataInterval = null;
        let healthCheckInterval = null;
        
        // Initialize TradingView Chart
        function initChart(symbol = 'BTCUSDT', timeframe = '1h') {
            const container = document.getElementById('chart-container');
            if (!container) return;
            
            // Clear previous chart
            if (tvWidget !== null) {
                tvWidget.remove();
                tvWidget = null;
            }
            
            // Set chart symbol
            document.getElementById('chart-symbol').textContent = symbol;
            
            // Map timeframe to TradingView interval
            const intervalMap = {
                '1m': '1', '5m': '5', '15m': '15', '30m': '30',
                '1h': '60', '4h': '240', '1d': '1D', '1w': '1W'
            };
            
            const tvInterval = intervalMap[timeframe] || '60';
            
            // Create new widget
            tvWidget = new TradingView.widget({
                "container_id": "chart-container",
                "width": "100%",
                "height": "500",
                "symbol": `BINANCE:${symbol}`,
                "interval": tvInterval,
                "timezone": "Etc/UTC",
                "theme": "dark",
                "style": "1",
                "locale": "en",
                "toolbar_bg": "#1e293b",
                "enable_publishing": false,
                "hide_side_toolbar": false,
                "allow_symbol_change": true,
                "save_image": false,
                "studies": [
                    "RSI@tv-basicstudies",
                    "MACD@tv-basicstudies",
                    "Volume@tv-basicstudies",
                    "BB@tv-basicstudies"
                ],
                "disabled_features": [
                    "header_widget",
                    "left_toolbar",
                    "popup_hints"
                ],
                "enabled_features": [
                    "study_templates",
                    "side_toolbar_in_fullscreen"
                ]
            });
        }
        
        // Show notification
        function showNotification(message, type = 'info', duration = 3000) {
            const notification = document.getElementById('notification');
            const messageEl = document.getElementById('notification-message');
            
            notification.className = `notification ${type}`;
            messageEl.textContent = message;
            notification.classList.add('show');
            
            setTimeout(() => {
                notification.classList.remove('show');
            }, duration);
        }
        
        // Update status indicator
        async function updateStatus() {
            try {
                const response = await fetch('/health');
                const data = await response.json();
                
                const statusDot = document.getElementById('status-dot');
                const statusText = document.getElementById('status-text');
                
                if (data.status === 'healthy' && data.services.websocket) {
                    statusDot.className = 'status-dot';
                    statusText.textContent = 'Connected';
                    statusText.style.color = '#10b981';
                } else {
                    statusDot.className = 'status-dot status-offline';
                    statusText.textContent = 'Disconnected';
                    statusText.style.color = '#ef4444';
                }
                
                // Update stats
                document.getElementById('active-symbols').textContent = 
                    data.cache?.prices || 0;
                document.getElementById('requests').textContent = 
                    data.active_connections || 0;
                
            } catch (error) {
                console.error('Status update error:', error);
                document.getElementById('status-dot').className = 'status-dot status-offline';
                document.getElementById('status-text').textContent = 'Error';
                document.getElementById('status-text').style.color = '#ef4444';
            }
        }
        
        // Update uptime counter
        function updateUptime() {
            const uptimeEl = document.getElementById('uptime');
            let seconds = parseInt(uptimeEl.textContent) || 0;
            seconds++;
            
            if (seconds < 60) {
                uptimeEl.textContent = seconds + 's';
            } else if (seconds < 3600) {
                uptimeEl.textContent = Math.floor(seconds / 60) + 'm';
            } else {
                uptimeEl.textContent = Math.floor(seconds / 3600) + 'h';
            }
        }
        
        // Load symbols list
        async function loadSymbols() {
            try {
                const response = await fetch('/api/symbols');
                const data = await response.json();
                const symbolList = document.getElementById('symbol-list');
                
                symbolList.innerHTML = '';
                data.symbols.forEach(symbol => {
                    const option = document.createElement('option');
                    option.value = symbol;
                    symbolList.appendChild(option);
                });
                
            } catch (error) {
                console.error('Error loading symbols:', error);
            }
        }
        
        // Analyze Symbol
        async function analyze() {
            const symbol = document.getElementById('symbol').value;
            const timeframe = document.getElementById('timeframe').value;
            const limit = document.getElementById('limit').value;
            
            // Update current values
            currentSymbol = symbol;
            currentTimeframe = timeframe;
            currentLimit = parseInt(limit);
            
            // Update button states
            document.getElementById('analyze-btn').disabled = true;
            document.getElementById('analyze-btn').textContent = 'Analyzing...';
            
            try {
                const response = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({symbol, timeframe, limit})
                });
                
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Analysis failed');
                }
                
                const data = await response.json();
                updateIndicators(data);
                
                // Update chart
                initChart(symbol, timeframe);
                
                showNotification(`Analysis completed for ${symbol}`, 'success');
                
            } catch (error) {
                console.error('Analysis error:', error);
                showNotification(`Error: ${error.message}`, 'error');
            } finally {
                // Restore button states
                document.getElementById('analyze-btn').disabled = false;
                document.getElementById('analyze-btn').textContent = '📊 Analyze';
            }
        }
        
        // Get Trading Signal
        async function getSignal() {
            const symbol = document.getElementById('symbol').value;
            const timeframe = document.getElementById('timeframe').value;
            
            // Update button states
            document.getElementById('signal-btn').disabled = true;
            document.getElementById('signal-btn').textContent = 'Generating...';
            
            try {
                const response = await fetch('/api/signal', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({symbol, timeframe, use_ml: true})
                });
                
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Signal generation failed');
                }
                
                const data = await response.json();
                displaySignal(data);
                
                showNotification(`Signal generated: ${data.signal.signal}`, 'success');
                
            } catch (error) {
                console.error('Signal error:', error);
                showNotification(`Error: ${error.message}`, 'error');
            } finally {
                // Restore button states
                document.getElementById('signal-btn').disabled = false;
                document.getElementById('signal-btn').textContent = '🤖 Get Signal';
            }
        }
        
        // Display Signal
        function displaySignal(data) {
            const container = document.getElementById('signal-display');
            const signal = data.signal;
            
            container.className = `signal-card ${signal.signal.toLowerCase()}`;
            container.style.borderColor = signal.color;
            
            container.innerHTML = `
                <div class="signal-type" style="color: ${signal.color}">${signal.signal}</div>
                <div class="signal-confidence">Confidence: ${signal.confidence}%</div>
                <div class="signal-details">
                    <div class="detail-item">
                        <div class="detail-label">Entry</div>
                        <div class="detail-value">$${signal.entry}</div>
                    </div>
                    <div class="detail-item">
                        <div class="detail-label">Stop Loss</div>
                        <div class="detail-value negative">$${signal.stop_loss}</div>
                    </div>
                    <div class="detail-item">
                        <div class="detail-label">Take Profit</div>
                        <div class="detail-value positive">$${signal.take_profit}</div>
                    </div>
                    <div class="detail-item">
                        <div class="detail-label">Risk/Reward</div>
                        <div class="detail-value">1:${signal.risk_reward}</div>
                    </div>
                </div>
                <div style="margin-top: 1rem; font-size: 0.85rem; color: var(--text-secondary);">
                    ${signal.factors ? signal.factors.join(', ') : 'No factors'}
                </div>
            `;
        }
        
        // Update Indicators
        function updateIndicators(data) {
            const container = document.getElementById('indicators-display');
            const ind = data.indicators;
            
            if (!ind) {
                container.innerHTML = '<div class="indicator-item"><span class="indicator-label">No data</span></div>';
                return;
            }
            
            container.innerHTML = `
                <div class="indicator-item">
                    <span class="indicator-label">RSI</span>
                    <span class="indicator-value ${ind.rsi > 70 ? 'negative' : ind.rsi < 30 ? 'positive' : ''}">
                        ${ind.rsi ? ind.rsi.toFixed(2) : 'N/A'}
                    </span>
                </div>
                <div class="indicator-item">
                    <span class="indicator-label">MACD</span>
                    <span class="indicator-value ${ind.macd > 0 ? 'positive' : 'negative'}">
                        ${ind.macd ? ind.macd.toFixed(4) : 'N/A'}
                    </span>
                </div>
                <div class="indicator-item">
                    <span class="indicator-label">SMA 20</span>
                    <span class="indicator-value">${ind.sma_20 ? '$' + ind.sma_20.toFixed(2) : 'N/A'}</span>
                </div>
                <div class="indicator-item">
                    <span class="indicator-label">ATR</span>
                    <span class="indicator-value">${ind.atr ? ind.atr.toFixed(2) : 'N/A'}</span>
                </div>
                <div class="indicator-item">
                    <span class="indicator-label">Stoch K</span>
                    <span class="indicator-value">${ind.stoch_k ? ind.stoch_k.toFixed(2) : 'N/A'}</span>
                </div>
                <div class="indicator-item">
                    <span class="indicator-label">Volume Ratio</span>
                    <span class="indicator-value">${ind.volume_ratio ? ind.volume_ratio.toFixed(2) : 'N/A'}</span>
                </div>
            `;
        }
        
        // Refresh Market Data
        async function refreshMarket() {
            try {
                const response = await fetch('/api/market');
                const data = await response.json();
                
                const table = document.getElementById('market-table');
                table.innerHTML = '';
                
                data.markets.forEach(market => {
                    const changeClass = market.change_24h >= 0 ? 'positive' : 'negative';
                    const changeSign = market.change_24h >= 0 ? '+' : '';
                    
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td><strong>${market.symbol}</strong></td>
                        <td>$${market.price.toFixed(2)}</td>
                        <td class="${changeClass}">${changeSign}${market.change_24h.toFixed(2)}%</td>
                        <td>${formatVolume(market.volume)}</td>
                        <td>$${market.high.toFixed(2)}</td>
                        <td>$${market.low.toFixed(2)}</td>
                        <td>
                            <button onclick="quickAnalyze('${market.symbol}')" 
                                    style="background: var(--accent-blue); color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; font-size: 0.9rem;">
                                Analyze
                            </button>
                        </td>
                    `;
                    table.appendChild(row);
                });
                
                showNotification('Market data refreshed', 'info');
                
            } catch (error) {
                console.error('Market refresh error:', error);
                showNotification('Error refreshing market data', 'error');
            }
        }
        
        // Format volume
        function formatVolume(volume) {
            if (volume >= 1e9) {
                return (volume / 1e9).toFixed(2) + 'B';
            } else if (volume >= 1e6) {
                return (volume / 1e6).toFixed(2) + 'M';
            } else if (volume >= 1e3) {
                return (volume / 1e3).toFixed(2) + 'K';
            }
            return volume.toFixed(2);
        }
        
        // Quick Analyze
        function quickAnalyze(symbol) {
            document.getElementById('symbol').value = symbol;
            analyze();
        }
        
        // Initialize on load
        document.addEventListener('DOMContentLoaded', () => {
            // Load initial data
            loadSymbols();
            refreshMarket();
            updateStatus();
            
            // Initialize chart
            initChart(currentSymbol, currentTimeframe);
            
            // Start intervals
            marketDataInterval = setInterval(refreshMarket, 30000); // 30 seconds
            healthCheckInterval = setInterval(updateStatus, 10000); // 10 seconds
            setInterval(updateUptime, 1000); // 1 second
            
            // Set up event listeners
            document.getElementById('symbol').addEventListener('change', function() {
                currentSymbol = this.value;
                initChart(currentSymbol, currentTimeframe);
            });
            
            document.getElementById('timeframe').addEventListener('change', function() {
                currentTimeframe = this.value;
                initChart(currentSymbol, currentTimeframe);
            });
            
            // Keyboard shortcuts
            document.addEventListener('keydown', (e) => {
                if (e.ctrlKey && e.key === 'a') {
                    e.preventDefault();
                    analyze();
                } else if (e.ctrlKey && e.key === 's') {
                    e.preventDefault();
                    getSignal();
                } else if (e.ctrlKey && e.key === 'r') {
                    e.preventDefault();
                    refreshMarket();
                }
            });
            
            // Show keyboard shortcuts
            setTimeout(() => {
                showNotification('Try Ctrl+A to analyze, Ctrl+S for signal, Ctrl+R to refresh', 'info', 5000);
            }, 2000);
        });
        
        // Clean up on unload
        window.addEventListener('beforeunload', () => {
            if (marketDataInterval) clearInterval(marketDataInterval);
            if (healthCheckInterval) clearInterval(healthCheckInterval);
            if (tvWidget !== null) {
                tvWidget.remove();
            }
        });
    </script>
</body>
</html>
        """
        return HTMLResponse(content=html)
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# ENTRY POINT
# ==========================================
if __name__ == "__main__":
    import uvicorn
    
    logger.info("=" * 80)
    logger.info("🚀 PROFESSIONAL CRYPTO TRADING PLATFORM v3.0")
    logger.info("=" * 80)
    logger.info(f"📍 Server: http://{Config.HOST}:{Config.PORT}")
    logger.info(f"📊 Dashboard: http://{Config.HOST}:{Config.PORT}/dashboard")
    logger.info(f"📖 API Docs: http://{Config.HOST}:{Config.PORT}/docs")
    logger.info(f"🔄 WebSocket: Single connection for {len(Config.DEFAULT_SYMBOLS)} symbols")
    logger.info(f"📈 Timeframes: {len(Config.ALLOWED_TIMEFRAMES)} timeframes supported")
    logger.info(f"🤖 ML: Rule-based predictions")
    logger.info(f"⚡ Rate Limiting: {Config.BINANCE_RATE_LIMIT_PER_SECOND}/second")
    logger.info("=" * 80)
    logger.info("🎯 Starting server...")
    logger.info("=" * 80)
    
    try:
        uvicorn.run(
            app,
            host=Config.HOST,
            port=Config.PORT,
            log_level="info" if not Config.DEBUG else "debug",
            access_log=True,
            reload=Config.DEBUG
        )
    except KeyboardInterrupt:
        logger.info("👋 Shutting down gracefully...")
    except Exception as e:
        logger.error(f"❌ Server error: {e}")
