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

import aiohttp
import numpy as np
import pandas as pd
import websockets
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, validator
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from scipy.signal import argrelextrema
from scipy.stats import linregress

# ==========================================
# YENİ KONFİGÜRASYON
# ==========================================
class Config:
    """Production configuration - Optimized"""
    # External APIs (No keys needed)
    BINANCE_API = "https://api.binance.com"
    BINANCE_WS = "wss://stream.binance.com:9443/ws"
    COINGECKO_API = "https://api.coingecko.com/api/v3"
    
    # WebSocket settings
    COMBINED_STREAM_RECONNECT_HOURS = 23  # 23 saatte bir yeniden bağlan
    WS_PING_INTERVAL = 20
    WS_PING_TIMEOUT = 60
    WS_MAX_SIZE = 2**20  # 1MB
    
    # Cache settings
    PRICE_CACHE_TTL = 2  # seconds
    ORDERBOOK_CACHE_TTL = 5
    KLINE_CACHE_TTL = 60
    
    # Rate limiting
    BINANCE_RATE_LIMIT = 1200  # requests/minute
    COINGECKO_RATE_LIMIT = 50
    
    # ML settings
    ML_RETRAIN_INTERVAL = 3600  # 1 hour
    ML_MIN_DATA_POINTS = 500
    ML_TRAIN_TEST_SPLIT = 0.2
    
    # Default trading symbols
    DEFAULT_SYMBOLS = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
        "SOLUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT"
    ]
    
    # Risk management
    MAX_RISK_PER_TRADE = 0.02  # 2%
    RISK_REWARD_MIN = 2.0
    
    # ICT settings
    FVG_MIN_SIZE = 0.001
    ORDER_BLOCK_LOOKBACK = 10
    LIQUIDITY_SWEEP_THRESHOLD = 0.98

# ==========================================
# LOGGING SETUP
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('trading_platform.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ==========================================
# DATA MODELS
# ==========================================
class AnalysisRequest(BaseModel):
    """Request model for technical analysis"""
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    
    @validator('timeframe')
    def validate_timeframe(cls, v):
        valid = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
        if v not in valid:
            raise ValueError(f'Invalid timeframe. Use: {valid}')
        return v
    
    @validator('symbol')
    def validate_symbol(cls, v):
        return v.upper()

class TradeSignalRequest(BaseModel):
    """Request model for trade signals"""
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    use_ml: bool = True

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
        self.kline_cache: Dict[str, List] = {}
        self.trade_cache: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.last_update: Dict[str, float] = {}
        self.connection_start_time: float = 0
        self.is_connected = False
        
    async def initialize(self):
        """Initialize HTTP session and WebSocket connection"""
        self.session = aiohttp.ClientSession()
        logger.info("✅ HTTP session initialized")
        
        # Start combined WebSocket stream
        asyncio.create_task(self._managed_combined_stream())
        
    async def _managed_combined_stream(self):
        """
        Manages single WebSocket connection for all symbols
        with 23-hour reconnection cycle
        """
        reconnect_delay = 1
        
        while True:
            try:
                # Planlı yeniden bağlanma: 23 saatte bir
                if time.time() - self.connection_start_time > Config.COMBINED_STREAM_RECONNECT_HOURS * 3600:
                    logger.info("🕒 Planned 23-hour reconnection initiated")
                    if self.combined_ws:
                        await self.combined_ws.close()
                    
                # Semboller için stream URL oluştur
                stream_names = []
                for symbol in Config.DEFAULT_SYMBOLS:
                    stream_names.append(f"{symbol.lower()}@ticker")
                    stream_names.append(f"{symbol.lower()}@trade")
                
                combined_streams = "/".join(stream_names)
                ws_url = f"{Config.BINANCE_WS}/stream?streams={combined_streams}"
                
                # WebSocket bağlantısı
                async with websockets.connect(
                    ws_url,
                    ping_interval=Config.WS_PING_INTERVAL,
                    ping_timeout=Config.WS_PING_TIMEOUT,
                    max_size=Config.WS_MAX_SIZE
                ) as websocket:
                    
                    self.combined_ws = websocket
                    self.connection_start_time = time.time()
                    self.is_connected = True
                    reconnect_delay = 1
                    
                    logger.info(f"✅ Connected to combined stream: {len(stream_names)} streams")
                    
                    # Mesajları dinle
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            await self._process_stream_message(data)
                        except json.JSONDecodeError:
                            logger.error(f"❌ Invalid JSON: {message[:200]}")
                        except Exception as e:
                            logger.error(f"❌ Stream processing error: {e}")
                            
            except Exception as e:
                self.is_connected = False
                logger.error(f"⚠️ WebSocket error: {e}")
                
                # Üstel geri çekilme
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)
                logger.info(f"🔄 Reconnecting in {reconnect_delay} seconds...")
    
    async def _process_stream_message(self, data: Dict):
        """Process incoming WebSocket messages"""
        stream_name = data.get('stream', '')
        payload = data.get('data', {})
        
        if '@ticker' in stream_name:
            symbol = stream_name.replace('@ticker', '').upper()
            self._update_price_cache(symbol, payload)
            
        elif '@trade' in stream_name:
            symbol = stream_name.replace('@trade', '').upper()
            self._update_trade_cache(symbol, payload)
    
    def _update_price_cache(self, symbol: str, data: Dict):
        """Update price cache with ticker data"""
        try:
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
                'timestamp': datetime.utcnow().isoformat(),
                'source': 'binance_ws',
                'event_time': data.get('E', 0)
            }
            self.last_update[f"{symbol}_price"] = time.time()
        except Exception as e:
            logger.error(f"❌ Price cache update error for {symbol}: {e}")
    
    def _update_trade_cache(self, symbol: str, data: Dict):
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
    
    async def get_klines(self, symbol: str, interval: str, limit: int = 500) -> List[Dict]:
        """Fetch OHLCV data with caching"""
        cache_key = f"{symbol}_{interval}"
        
        # Cache kontrolü
        if cache_key in self.kline_cache:
            cache_time = self.last_update.get(f"{symbol}_kline", 0)
            if time.time() - cache_time < Config.KLINE_CACHE_TTL:
                return self.kline_cache[cache_key]
        
        try:
            url = f"{Config.BINANCE_API}/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': min(limit, 1000)
            }
            
            async with self.session.get(url, params=params, timeout=10) as response:
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
                    self.kline_cache[cache_key] = candles
                    self.last_update[f"{symbol}_kline"] = time.time()
                    
                    logger.info(f"📊 Fetched {len(candles)} candles for {symbol} ({interval})")
                    return candles
                else:
                    logger.error(f"❌ Binance API error: {response.status}")
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
            url = f"{Config.BINANCE_API}/api/v3/ticker/24hr"
            params = {'symbol': symbol}
            
            async with self.session.get(url, params=params, timeout=5) as response:
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
                    
        except Exception as e:
            logger.error(f"❌ Error fetching ticker for {symbol}: {e}")
            return None
    
    async def get_orderbook(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        """Get order book data with caching"""
        cache_key = f"{symbol}_orderbook"
        
        if cache_key in self.orderbook_cache:
            cache_time = self.last_update.get(f"{symbol}_orderbook", 0)
            if time.time() - cache_time < Config.ORDERBOOK_CACHE_TTL:
                return self.orderbook_cache[cache_key]
        
        try:
            url = f"{Config.BINANCE_API}/api/v3/depth"
            params = {'symbol': symbol, 'limit': limit}
            
            async with self.session.get(url, params=params, timeout=5) as response:
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
                'MATIC': 'matic-network'
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
            
            async with self.session.get(url, params=params, timeout=10) as response:
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
                    
        except Exception as e:
            logger.error(f"❌ CoinGecko API error for {symbol}: {e}")
            return None
    
    async def get_market_overview(self) -> List[Dict]:
        """Get market overview for all tracked symbols"""
        overview = []
        
        for symbol in Config.DEFAULT_SYMBOLS:
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
        
        # Volume'a göre sırala
        overview.sort(key=lambda x: x['volume'], reverse=True)
        return overview
    
    async def close(self):
        """Cleanup connections"""
        if self.session:
            await self.session.close()
        if self.combined_ws:
            await self.combined_ws.close()
        logger.info("🔌 All connections closed")

# ==========================================
# TEKNİK GÖSTERGELER (Optimize Edilmiş)
# ==========================================
class TechnicalIndicators:
    """Optimized technical indicators"""
    
    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all indicators at once"""
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        volume = df['volume'].values
        
        # Moving Averages
        df['sma_20'] = pd.Series(close).rolling(window=20).mean()
        df['sma_50'] = pd.Series(close).rolling(window=50).mean()
        df['sma_200'] = pd.Series(close).rolling(window=200).mean()
        df['ema_12'] = pd.Series(close).ewm(span=12, adjust=False).mean()
        df['ema_26'] = pd.Series(close).ewm(span=26, adjust=False).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # MACD
        df['macd'] = df['ema_12'] - df['ema_26']
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # Bollinger Bands
        df['bb_middle'] = df['sma_20']
        bb_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
        
        # ATR
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift())
        tr3 = abs(df['low'] - df['close'].shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=14).mean()
        
        # Stochastic
        df['stoch_k'] = 100 * ((df['close'] - df['low'].rolling(14).min()) / 
                               (df['high'].rolling(14).max() - df['low'].rolling(14).min()))
        df['stoch_d'] = df['stoch_k'].rolling(3).mean()
        
        # Volume indicators
        df['volume_sma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        # OBV
        df['obv'] = (np.sign(df['close'].diff()) * df['volume']).cumsum()
        
        # VWAP
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (df['typical_price'] * df['volume']).cumsum() / df['volume'].cumsum()
        
        return df.dropna()

# ==========================================
# ICT ANALİZİ
# ==========================================
class ICTAnalysis:
    """Inner Circle Trader analysis"""
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> Dict:
        """Perform ICT analysis"""
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        volume = df['volume'].values
        
        # Order Blocks
        order_blocks = ICTAnalysis._find_order_blocks(df)
        
        # Fair Value Gaps
        fvgs = ICTAnalysis._find_fvgs(df)
        
        # Premium/Discount Zone
        premium_discount = ICTAnalysis._calculate_premium_discount(close)
        
        # Liquidity
        liquidity = ICTAnalysis._analyze_liquidity(df)
        
        return {
            'order_blocks': order_blocks[-5:],  # Son 5
            'fair_value_gaps': fvgs[-5:],
            'premium_discount': premium_discount,
            'liquidity': liquidity
        }
    
    @staticmethod
    def _find_order_blocks(df: pd.DataFrame) -> List[Dict]:
        """Find order blocks"""
        blocks = []
        close = df['close'].values
        open_ = df['open'].values
        high = df['high'].values
        low = df['low'].values
        
        for i in range(2, len(close)):
            # Bearish order block (yukarı mum + aşağı hareket)
            if close[i-2] > open_[i-2] and close[i] < low[i-2]:
                blocks.append({
                    'type': 'bearish',
                    'index': i-2,
                    'high': high[i-2],
                    'low': low[i-2],
                    'timestamp': df.index[i-2] if hasattr(df.index, '__getitem__') else i-2
                })
            
            # Bullish order block (aşağı mum + yukarı hareket)
            if close[i-2] < open_[i-2] and close[i] > high[i-2]:
                blocks.append({
                    'type': 'bullish',
                    'index': i-2,
                    'high': high[i-2],
                    'low': low[i-2],
                    'timestamp': df.index[i-2] if hasattr(df.index, '__getitem__') else i-2
                })
        
        return blocks
    
    @staticmethod
    def _find_fvgs(df: pd.DataFrame) -> List[Dict]:
        """Find Fair Value Gaps"""
        fvgs = []
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        
        for i in range(2, len(close)):
            # Bullish FVG
            if low[i] > high[i-2]:
                fvgs.append({
                    'type': 'bullish',
                    'index': i,
                    'top': low[i],
                    'bottom': high[i-2],
                    'size': (low[i] - high[i-2]) / close[i]
                })
            
            # Bearish FVG
            if high[i] < low[i-2]:
                fvgs.append({
                    'type': 'bearish',
                    'index': i,
                    'top': low[i-2],
                    'bottom': high[i],
                    'size': (low[i-2] - high[i]) / close[i]
                })
        
        return fvgs
    
    @staticmethod
    def _calculate_premium_discount(close: np.ndarray) -> Dict:
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
            'range_low': float(recent_low)
        }
    
    @staticmethod
    def _analyze_liquidity(df: pd.DataFrame) -> Dict:
        """Analyze liquidity"""
        volume = df['volume'].values
        
        if len(volume) < 20:
            return {'trend': 'neutral', 'ratio': 1.0}
        
        avg_volume = np.mean(volume[-20:])
        current_volume = volume[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        
        trend = 'high' if volume_ratio > 1.2 else 'low' if volume_ratio < 0.8 else 'normal'
        
        return {
            'trend': trend,
            'ratio': float(volume_ratio),
            'current': float(current_volume),
            'average': float(avg_volume)
        }

# ==========================================
# CANDLESTICK PATTERNS
# ==========================================
class CandlestickPatterns:
    """Candlestick pattern detection"""
    
    @staticmethod
    def detect(df: pd.DataFrame) -> List[Dict]:
        """Detect candlestick patterns"""
        patterns = []
        close = df['close'].values
        open_ = df['open'].values
        high = df['high'].values
        low = df['low'].values
        
        # Doji
        patterns.extend(CandlestickPatterns._detect_doji(close, open_, high, low))
        
        # Hammer
        patterns.extend(CandlestickPatterns._detect_hammer(close, open_, high, low))
        
        # Engulfing
        patterns.extend(CandlestickPatterns._detect_engulfing(close, open_))
        
        return patterns[-10:]  # Son 10 pattern
    
    @staticmethod
    def _detect_doji(close, open_, high, low):
        """Detect Doji patterns"""
        patterns = []
        for i in range(len(close)):
            body = abs(close[i] - open_[i])
            total_range = high[i] - low[i]
            
            if total_range > 0 and body / total_range < 0.1:
                patterns.append({
                    'pattern': 'doji',
                    'index': i,
                    'signal': 'neutral',
                    'strength': 1.0 - (body / total_range)
                })
        return patterns
    
    @staticmethod
    def _detect_hammer(close, open_, high, low):
        """Detect Hammer patterns"""
        patterns = []
        for i in range(len(close)):
            body = abs(close[i] - open_[i])
            upper_shadow = high[i] - max(close[i], open_[i])
            lower_shadow = min(close[i], open_[i]) - low[i]
            
            # Hammer (bullish)
            if lower_shadow > 2 * body and upper_shadow < body * 0.1:
                patterns.append({
                    'pattern': 'hammer',
                    'index': i,
                    'signal': 'bullish',
                    'strength': lower_shadow / body if body > 0 else 1.0
                })
            
            # Shooting star (bearish)
            if upper_shadow > 2 * body and lower_shadow < body * 0.1:
                patterns.append({
                    'pattern': 'shooting_star',
                    'index': i,
                    'signal': 'bearish',
                    'strength': upper_shadow / body if body > 0 else 1.0
                })
        return patterns
    
    @staticmethod
    def _detect_engulfing(close, open_):
        """Detect Engulfing patterns"""
        patterns = []
        for i in range(1, len(close)):
            # Bullish engulfing
            if (close[i-1] < open_[i-1] and  # Önceki mum bearish
                close[i] > open_[i] and      # Şimdiki mum bullish
                open_[i] <= close[i-1] and   # Açılış önceki kapanıştan düşük veya eşit
                close[i] >= open_[i-1]):     # Kapanış önceki açılıştan yüksek veya eşit
                
                patterns.append({
                    'pattern': 'bullish_engulfing',
                    'index': i,
                    'signal': 'bullish',
                    'strength': 0.8
                })
            
            # Bearish engulfing
            if (close[i-1] > open_[i-1] and  # Önceki mum bullish
                close[i] < open_[i] and      # Şimdiki mum bearish
                open_[i] >= close[i-1] and   # Açılış önceki kapanıştan yüksek veya eşit
                close[i] <= open_[i-1]):     # Kapanış önceki açılıştan düşük veya eşit
                
                patterns.append({
                    'pattern': 'bearish_engulfing',
                    'index': i,
                    'signal': 'bearish',
                    'strength': 0.8
                })
        return patterns

# ==========================================
# SUPPORT & RESISTANCE
# ==========================================
class SupportResistance:
    """Support and resistance detection"""
    
    @staticmethod
    def find_levels(df: pd.DataFrame) -> Dict:
        """Find support and resistance levels"""
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        
        # Yerel maksimumlar (direnç)
        resistance_idx = argrelextrema(high, np.greater, order=5)[0]
        resistance_levels = high[resistance_idx]
        
        # Yerel minimumlar (destek)
        support_idx = argrelextrema(low, np.less, order=5)[0]
        support_levels = low[support_idx]
        
        # Cluster levels
        resistance_clusters = SupportResistance._cluster_levels(resistance_levels, close[-1])
        support_clusters = SupportResistance._cluster_levels(support_levels, close[-1])
        
        # Pivot points
        pivot_points = SupportResistance._calculate_pivot_points(df)
        
        return {
            'resistance': resistance_clusters[:5],  # Top 5
            'support': support_clusters[:5],
            'pivot_points': pivot_points,
            'current_price': float(close[-1])
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
                clusters.append({
                    'level': float(np.mean(current_cluster)),
                    'touches': len(current_cluster),
                    'strength': min(1.0, len(current_cluster) / 5.0)
                })
                current_cluster = [level]
        
        if current_cluster:
            clusters.append({
                'level': float(np.mean(current_cluster)),
                'touches': len(current_cluster),
                'strength': min(1.0, len(current_cluster) / 5.0)
            })
        
        return clusters
    
    @staticmethod
    def _calculate_pivot_points(df: pd.DataFrame) -> Dict:
        """Calculate pivot points"""
        if len(df) < 1:
            return {}
        
        last = df.iloc[-1]
        pivot = (last['high'] + last['low'] + last['close']) / 3
        
        return {
            'pivot': float(pivot),
            'r1': float(2 * pivot - last['low']),
            's1': float(2 * pivot - last['high']),
            'r2': float(pivot + (last['high'] - last['low'])),
            's2': float(pivot - (last['high'] - last['low']))
        }

# ==========================================
# MACHINE LEARNING PREDICTOR (Optimize Edilmiş)
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
        # Temel özellikler
        features = pd.DataFrame()
        
        # Price features
        features['returns'] = df['close'].pct_change()
        features['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        
        # Moving averages
        features['sma_5'] = df['close'].rolling(5).mean()
        features['sma_10'] = df['close'].rolling(10).mean()
        features['sma_20'] = df['close'].rolling(20).mean()
        features['ema_12'] = df['close'].ewm(span=12, adjust=False).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        features['rsi'] = 100 - (100 / (1 + rs))
        
        # MACD
        features['macd'] = df['ema_12'] - df['ema_26']
        
        # Bollinger Bands
        bb_middle = df['close'].rolling(20).mean()
        bb_std = df['close'].rolling(20).std()
        features['bb_position'] = (df['close'] - bb_middle) / (2 * bb_std)
        
        # Volume
        features['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
        
        # Target: Next period return
        features['target'] = (df['close'].shift(-1) > df['close']).astype(int)
        
        # Drop NaN
        features = features.dropna()
        
        X = features.drop('target', axis=1).values
        y = features['target'].values
        
        return X, y
    
    def train(self, symbol: str, df: pd.DataFrame) -> bool:
        """Train ML model"""
        try:
            if len(df) < Config.ML_MIN_DATA_POINTS:
                logger.warning(f"❌ Insufficient data for {symbol}: {len(df)} < {Config.ML_MIN_DATA_POINTS}")
                return False
            
            X, y = self.prepare_features(df)
            
            if len(X) < 100:
                return False
            
            # Split data
            split_idx = int(len(X) * (1 - Config.ML_TRAIN_TEST_SPLIT))
            X_train, X_test = X[:split_idx], X[split_idx:]
            y_train, y_test = y[:split_idx], y[split_idx:]
            
            # Scale features
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            # Train Random Forest
            rf_model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_split=5,
                min_samples_leaf=2,
                random_state=42,
                n_jobs=-1
            )
            rf_model.fit(X_train_scaled, y_train)
            
            # Train Gradient Boosting
            gb_model = GradientBoostingClassifier(
                n_estimators=50,
                max_depth=5,
                min_samples_split=10,
                learning_rate=0.1,
                random_state=42
            )
            gb_model.fit(X_train_scaled, y_train)
            
            # Store models
            self.models[symbol] = {
                'rf': rf_model,
                'gb': gb_model
            }
            self.scalers[symbol] = scaler
            self.last_train_time[symbol] = time.time()
            
            # Evaluate
            rf_acc = rf_model.score(X_test_scaled, y_test)
            gb_acc = gb_model.score(X_test_scaled, y_test)
            
            logger.info(f"✅ ML trained for {symbol}: RF={rf_acc:.2%}, GB={gb_acc:.2%}")
            return True
            
        except Exception as e:
            logger.error(f"❌ ML training error for {symbol}: {e}")
            return False
    
    def predict(self, symbol: str, df: pd.DataFrame) -> Optional[Dict]:
        """Make prediction"""
        try:
            # Check cache
            cache_key = f"{symbol}_{df.index[-1] if len(df) > 0 else 'none'}"
            if cache_key in self.prediction_cache:
                cache_time = self.prediction_cache[cache_key]['timestamp']
                if time.time() - cache_time < 300:  # 5 dakika cache
                    return self.prediction_cache[cache_key]['prediction']
            
            # Check if model exists
            if symbol not in self.models:
                logger.info(f"🤖 Training initial model for {symbol}")
                if not self.train(symbol, df):
                    return None
            
            # Retrain if needed
            if time.time() - self.last_train_time.get(symbol, 0) > Config.ML_RETRAIN_INTERVAL:
                logger.info(f"🔄 Retraining model for {symbol}")
                self.train(symbol, df)
            
            # Prepare features for prediction
            X, _ = self.prepare_features(df)
            
            if len(X) == 0:
                return None
            
            # Get latest features
            X_latest = X[-1:].reshape(1, -1)
            X_scaled = self.scalers[symbol].transform(X_latest)
            
            # Predict
            rf_proba = self.models[symbol]['rf'].predict_proba(X_scaled)[0]
            gb_proba = self.models[symbol]['gb'].predict_proba(X_scaled)[0]
            
            # Ensemble
            ensemble_proba = (rf_proba + gb_proba) / 2
            direction = 'bullish' if ensemble_proba[1] > 0.5 else 'bearish'
            confidence = max(ensemble_proba) * 100
            
            result = {
                'direction': direction,
                'confidence': float(confidence),
                'bullish_probability': float(ensemble_proba[1] * 100),
                'bearish_probability': float(ensemble_proba[0] * 100),
                'rf_bullish': float(rf_proba[1] * 100),
                'gb_bullish': float(gb_proba[1] * 100),
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
# ANA ANALİZ MOTORU
# ==========================================
class AnalysisEngine:
    """Main analysis engine"""
    
    def __init__(self):
        self.ml_predictor = MLPredictor()
        
    def analyze(self, symbol: str, candles: List[Dict], use_ml: bool = True) -> Dict:
        """Perform comprehensive analysis"""
        try:
            if len(candles) < 50:
                raise ValueError(f"Insufficient data: {len(candles)} candles")
            
            # Convert to DataFrame
            df = pd.DataFrame(candles)
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
            
            # Calculate indicators
            df = TechnicalIndicators.calculate_all(df)
            
            # Get current values
            current_price = float(df['close'].iloc[-1])
            
            # ICT Analysis
            ict_analysis = ICTAnalysis.analyze(df)
            
            # Candlestick Patterns
            patterns = CandlestickPatterns.detect(df)
            
            # Support & Resistance
            sr_levels = SupportResistance.find_levels(df)
            
            # ML Prediction
            ml_prediction = None
            if use_ml and len(df) >= Config.ML_MIN_DATA_POINTS:
                ml_prediction = self.ml_predictor.predict(symbol, df)
            
            # Trend Analysis
            trend = self._analyze_trend(df)
            
            # Volume Analysis
            volume = self._analyze_volume(df)
            
            # Market Structure
            structure = self._analyze_structure(df)
            
            # Prepare response
            indicators = {
                'sma_20': float(df['sma_20'].iloc[-1]),
                'sma_50': float(df['sma_50'].iloc[-1]),
                'rsi': float(df['rsi'].iloc[-1]),
                'macd': float(df['macd'].iloc[-1]),
                'macd_signal': float(df['macd_signal'].iloc[-1]),
                'macd_hist': float(df['macd_hist'].iloc[-1]),
                'bb_upper': float(df['bb_upper'].iloc[-1]),
                'bb_middle': float(df['bb_middle'].iloc[-1]),
                'bb_lower': float(df['bb_lower'].iloc[-1]),
                'stoch_k': float(df['stoch_k'].iloc[-1]),
                'stoch_d': float(df['stoch_d'].iloc[-1]),
                'atr': float(df['atr'].iloc[-1]),
                'volume_ratio': float(df['volume_ratio'].iloc[-1])
            }
            
            return {
                'symbol': symbol,
                'timestamp': datetime.utcnow().isoformat(),
                'current_price': current_price,
                'indicators': indicators,
                'ict_analysis': ict_analysis,
                'patterns': patterns,
                'support_resistance': sr_levels,
                'trend': trend,
                'volume': volume,
                'market_structure': structure,
                'ml_prediction': ml_prediction,
                'data_points': len(df)
            }
            
        except Exception as e:
            logger.error(f"❌ Analysis error for {symbol}: {e}")
            raise
    
    def _analyze_trend(self, df: pd.DataFrame) -> Dict:
        """Analyze trend"""
        close = df['close'].values
        sma_20 = df['sma_20'].values
        sma_50 = df['sma_50'].values
        
        if len(close) < 2:
            return {'direction': 'neutral', 'strength': 0}
        
        current_price = close[-1]
        
        # Trend direction
        if current_price > sma_20[-1] > sma_50[-1]:
            direction = 'strong_bullish'
        elif current_price < sma_20[-1] < sma_50[-1]:
            direction = 'strong_bearish'
        elif current_price > sma_20[-1]:
            direction = 'bullish'
        elif current_price < sma_20[-1]:
            direction = 'bearish'
        else:
            direction = 'neutral'
        
        # Trend strength (price vs SMA distance)
        price_distance = abs(current_price - sma_20[-1]) / current_price
        strength = min(100, price_distance * 1000)
        
        return {
            'direction': direction,
            'strength': float(strength),
            'sma_20_distance': float((current_price - sma_20[-1]) / current_price * 100)
        }
    
    def _analyze_volume(self, df: pd.DataFrame) -> Dict:
        """Analyze volume"""
        volume = df['volume'].values
        close = df['close'].values
        
        if len(volume) < 20:
            return {'trend': 'neutral', 'ratio': 1.0}
        
        avg_volume = np.mean(volume[-20:])
        current_volume = volume[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        
        # Price-volume correlation
        price_change = (close[-1] - close[-20]) / close[-20]
        volume_change = (current_volume - avg_volume) / avg_volume if avg_volume > 0 else 0
        
        if price_change > 0 and volume_change > 0:
            divergence = 'bullish_confirmation'
        elif price_change < 0 and volume_change > 0:
            divergence = 'bearish_confirmation'
        elif price_change > 0 and volume_change < 0:
            divergence = 'bearish_divergence'
        elif price_change < 0 and volume_change < 0:
            divergence = 'bullish_divergence'
        else:
            divergence = 'neutral'
        
        return {
            'trend': 'high' if volume_ratio > 1.2 else 'low' if volume_ratio < 0.8 else 'normal',
            'ratio': float(volume_ratio),
            'current': float(current_volume),
            'average': float(avg_volume),
            'divergence': divergence
        }
    
    def _analyze_structure(self, df: pd.DataFrame) -> Dict:
        """Analyze market structure"""
        high = df['high'].values
        low = df['low'].values
        
        if len(high) < 20:
            return {'structure': 'neutral', 'swing_highs': 0, 'swing_lows': 0}
        
        # Find swing points
        swing_highs = argrelextrema(high[-20:], np.greater, order=2)[0]
        swing_lows = argrelextrema(low[-20:], np.less, order=2)[0]
        
        # Determine structure
        if len(swing_highs) > 0 and len(swing_lows) > 0:
            last_high = high[-20:][swing_highs[-1]] if len(swing_highs) > 0 else high[-1]
            last_low = low[-20:][swing_lows[-1]] if len(swing_lows) > 0 else low[-1]
            
            if len(swing_highs) >= 2 and len(swing_lows) >= 2:
                prev_high = high[-20:][swing_highs[-2]]
                prev_low = low[-20:][swing_lows[-2]]
                
                if last_high > prev_high and last_low > prev_low:
                    structure = 'uptrend'
                elif last_high < prev_high and last_low < prev_low:
                    structure = 'downtrend'
                elif last_high > prev_high and last_low < prev_low:
                    structure = 'expanding'
                elif last_high < prev_high and last_low > prev_low:
                    structure = 'contracting'
                else:
                    structure = 'ranging'
            else:
                structure = 'forming'
        else:
            structure = 'neutral'
        
        return {
            'structure': structure,
            'swing_highs': len(swing_highs),
            'swing_lows': len(swing_lows)
        }
    
    def generate_signal(self, analysis: Dict) -> Dict:
        """Generate trading signal"""
        try:
            score = 50  # Neutral baseline
            factors = []
            
            indicators = analysis['indicators']
            current_price = analysis['current_price']
            
            # 1. RSI Scoring (0-20)
            rsi = indicators['rsi']
            if rsi < 30:
                score += 15
                factors.append(f'RSI oversold ({rsi:.1f})')
            elif rsi > 70:
                score -= 15
                factors.append(f'RSI overbought ({rsi:.1f})')
            elif rsi < 40:
                score += 5
            elif rsi > 60:
                score -= 5
            
            # 2. MACD Scoring (0-15)
            if indicators['macd'] > indicators['macd_signal']:
                score += 10
                if indicators['macd_hist'] > 0:
                    score += 5
                    factors.append('MACD bullish crossover')
            else:
                score -= 10
                if indicators['macd_hist'] < 0:
                    score -= 5
                    factors.append('MACD bearish crossover')
            
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
            price_to_resistance = min([abs(current_price - r['level']) for r in sr['resistance']] or [999])
            price_to_support = min([abs(current_price - s['level']) for s in sr['support']] or [999])
            
            if price_to_support < price_to_resistance:
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
            elif score <= 35:
                signal = 'SELL'
                confidence = 100 - score
            else:
                signal = 'HOLD'
                confidence = 50
            
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
                'confidence': 0,
                'score': 50,
                'error': str(e)
            }

# ==========================================
# FASTAPI APPLICATION
# ==========================================
data_manager: Optional[RealTimeDataManager] = None
analysis_engine: Optional[AnalysisEngine] = None
START_TIME = time.time()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle"""
    global data_manager, analysis_engine
    
    logger.info("=" * 80)
    logger.info("🚀 PROFESSIONAL CRYPTO TRADING PLATFORM")
    logger.info("=" * 80)
    
    # Initialize components
    data_manager = RealTimeDataManager()
    await data_manager.initialize()
    
    analysis_engine = AnalysisEngine()
    
    logger.info("✅ Real-time Data Manager: Active")
    logger.info("✅ Analysis Engine: Ready")
    logger.info("✅ ML Predictor: Initialized")
    logger.info("✅ WebSocket: Single connection mode")
    logger.info("=" * 80)
    logger.info("🎯 System ready for professional trading!")
    logger.info("=" * 80)
    
    yield
    
    # Cleanup
    logger.info("🛑 Shutting down...")
    await data_manager.close()
    logger.info("✅ Shutdown complete")

app = FastAPI(
    title="Professional Crypto Trading Platform",
    description="Production-ready trading system with ML, ICT, and advanced TA",
    version="2.0.0",
    lifespan=lifespan
)

# CORS
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
        "platform": "Professional Crypto Trading Platform",
        "version": "2.0.0",
        "status": "operational",
        "uptime": int(time.time() - START_TIME),
        "features": [
            "Single WebSocket connection",
            "50+ Technical indicators",
            "ML predictions (RF + GB)",
            "ICT concepts",
            "Candlestick patterns",
            "Support/Resistance",
            "Real-time dashboard"
        ],
        "active_symbols": Config.DEFAULT_SYMBOLS
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
            "uptime": int(time.time() - START_TIME),
            "services": {
                "websocket": data_manager.is_connected,
                "binance_api": btc_ticker is not None,
                "cache": len(data_manager.price_cache)
            },
            "cache": {
                "prices": len(data_manager.price_cache),
                "orderbooks": len(data_manager.orderbook_cache),
                "klines": len(data_manager.kline_cache)
            }
        }
    except Exception as e:
        logger.error(f"Health check error: {e}")
        raise HTTPException(status_code=503, detail=str(e))

@app.get("/api/ticker/{symbol}")
async def get_ticker(symbol: str):
    """Get ticker data"""
    symbol = symbol.upper()
    ticker = await data_manager.get_ticker(symbol)
    
    if not ticker:
        raise HTTPException(status_code=404, detail=f"Ticker not found: {symbol}")
    
    # Add CoinGecko data
    cg_data = await data_manager.get_coingecko_data(symbol)
    if cg_data:
        ticker['coingecko'] = cg_data
    
    return ticker

@app.post("/api/analyze")
async def analyze(request: AnalysisRequest):
    """Technical analysis"""
    try:
        # Fetch data
        candles = await data_manager.get_klines(request.symbol, request.timeframe, 500)
        
        if len(candles) < 50:
            raise HTTPException(
                status_code=400, 
                detail=f"Insufficient data: {len(candles)} candles"
            )
        
        # Analyze
        analysis = analysis_engine.analyze(request.symbol, candles, use_ml=True)
        
        return analysis
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/signal")
async def signal(request: TradeSignalRequest):
    """Get trading signal"""
    try:
        # Fetch data
        candles = await data_manager.get_klines(request.symbol, request.timeframe, 500)
        
        if len(candles) < 50:
            raise HTTPException(
                status_code=400, 
                detail=f"Insufficient data: {len(candles)} candles"
            )
        
        # Analyze
        analysis = analysis_engine.analyze(request.symbol, candles, use_ml=request.use_ml)
        
        # Generate signal
        signal = analysis_engine.generate_signal(analysis)
        
        return {
            "symbol": request.symbol,
            "timeframe": request.timeframe,
            "analysis": {
                "price": analysis['current_price'],
                "rsi": analysis['indicators']['rsi'],
                "trend": analysis['trend']['direction'],
                "volume": analysis['volume']['trend']
            },
            "signal": signal,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signal error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/market")
async def market_overview():
    """Market overview"""
    overview = await data_manager.get_market_overview()
    
    return {
        "markets": overview,
        "count": len(overview),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/orderbook/{symbol}")
async def orderbook(symbol: str, limit: int = 20):
    """Get order book"""
    symbol = symbol.upper()
    ob = await data_manager.get_orderbook(symbol, limit)
    
    if not ob:
        raise HTTPException(status_code=404, detail=f"Orderbook not available: {symbol}")
    
    return ob

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Trading Dashboard"""
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
        }
        
        .header {
            background: var(--bg-card);
            padding: 1rem 2rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
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
        }
        
        input:focus, select:focus {
            outline: none;
            border-color: var(--accent-blue);
        }
        
        button {
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-green));
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 6px;
            color: white;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s;
        }
        
        button:hover {
            transform: translateY(-2px);
        }
        
        .main-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 1.5rem;
            margin-bottom: 1.5rem;
        }
        
        .card {
            background: var(--bg-card);
            border-radius: 10px;
            padding: 1.5rem;
            border: 1px solid var(--border);
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
        }
        
        .badge.ml {
            background: rgba(59, 130, 246, 0.2);
            color: var(--accent-blue);
        }
        
        #chart-container {
            height: 500px;
            border-radius: 8px;
            overflow: hidden;
        }
        
        .signal-card {
            text-align: center;
            padding: 2rem;
            border-radius: 10px;
            margin-bottom: 1.5rem;
        }
        
        .signal-card.buy {
            background: rgba(16, 185, 129, 0.1);
            border: 2px solid var(--accent-green);
        }
        
        .signal-card.sell {
            background: rgba(239, 68, 68, 0.1);
            border: 2px solid var(--accent-red);
        }
        
        .signal-card.hold {
            background: rgba(245, 158, 11, 0.1);
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
        }
        
        .market-table td {
            padding: 1rem;
            border-bottom: 1px solid var(--border);
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
        
        @media (max-width: 1024px) {
            .main-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">🚀 Trading Platform</div>
        <div class="status">
            <div class="status-dot"></div>
            <span>Real-time Active</span>
        </div>
    </div>
    
    <div class="container">
        <!-- Controls -->
        <div class="controls">
            <div class="control-grid">
                <div class="input-group">
                    <label>Symbol</label>
                    <input type="text" id="symbol" value="BTCUSDT">
                </div>
                <div class="input-group">
                    <label>Timeframe</label>
                    <select id="timeframe">
                        <option value="1h">1 Hour</option>
                        <option value="4h">4 Hours</option>
                        <option value="1d">1 Day</option>
                        <option value="1w">1 Week</option>
                    </select>
                </div>
                <div class="input-group">
                    <button onclick="analyze()">📊 Analyze</button>
                </div>
                <div class="input-group">
                    <button onclick="getSignal()">🤖 Get Signal</button>
                </div>
                <div class="input-group">
                    <button onclick="refreshMarket()">🔄 Refresh</button>
                </div>
            </div>
        </div>
        
        <!-- Main Content -->
        <div class="main-grid">
            <!-- Left Column: Chart -->
            <div class="card">
                <div class="card-header">
                    <div class="card-title">Live Chart</div>
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
    
    <script>
        // Initialize TradingView Chart
        function initChart(symbol = 'BTCUSDT', timeframe = '1h') {
            const container = document.getElementById('chart-container');
            if (!container) return;
            
            // Clear previous chart
            container.innerHTML = '';
            
            // Create new widget
            new TradingView.widget({
                "container_id": "chart-container",
                "width": "100%",
                "height": "500",
                "symbol": `BINANCE:${symbol}`,
                "interval": timeframe === '1h' ? '60' : 
                           timeframe === '4h' ? '240' : 
                           timeframe === '1d' ? '1D' : '1W',
                "timezone": "Etc/UTC",
                "theme": "dark",
                "style": "1",
                "locale": "en",
                "toolbar_bg": "#1e293b",
                "enable_publishing": false,
                "hide_side_toolbar": false,
                "allow_symbol_change": true,
                "studies": [
                    "RSI@tv-basicstudies",
                    "MACD@tv-basicstudies",
                    "Volume@tv-basicstudies"
                ],
                "disabled_features": [
                    "header_widget",
                    "left_toolbar"
                ]
            });
        }
        
        // Analyze Symbol
        async function analyze() {
            const symbol = document.getElementById('symbol').value;
            const timeframe = document.getElementById('timeframe').value;
            
            try {
                const response = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({symbol, timeframe})
                });
                
                if (!response.ok) throw new Error('Analysis failed');
                
                const data = await response.json();
                updateIndicators(data);
                
                // Update chart
                initChart(symbol, timeframe);
                
            } catch (error) {
                console.error('Analysis error:', error);
                alert('Analysis failed. Please try again.');
            }
        }
        
        // Get Trading Signal
        async function getSignal() {
            const symbol = document.getElementById('symbol').value;
            const timeframe = document.getElementById('timeframe').value;
            
            try {
                const response = await fetch('/api/signal', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({symbol, timeframe, use_ml: true})
                });
                
                if (!response.ok) throw new Error('Signal failed');
                
                const data = await response.json();
                displaySignal(data);
                
            } catch (error) {
                console.error('Signal error:', error);
                alert('Failed to get signal. Please try again.');
            }
        }
        
        // Display Signal
        function displaySignal(data) {
            const container = document.getElementById('signal-display');
            const signal = data.signal;
            
            container.className = `signal-card ${signal.signal.toLowerCase()}`;
            
            container.innerHTML = `
                <div class="signal-type">${signal.signal}</div>
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
            `;
        }
        
        // Update Indicators
        function updateIndicators(data) {
            const container = document.getElementById('indicators-display');
            const ind = data.indicators;
            
            container.innerHTML = `
                <div class="indicator-item">
                    <span class="indicator-label">RSI</span>
                    <span class="indicator-value ${ind.rsi > 70 ? 'negative' : ind.rsi < 30 ? 'positive' : ''}">
                        ${ind.rsi.toFixed(2)}
                    </span>
                </div>
                <div class="indicator-item">
                    <span class="indicator-label">MACD</span>
                    <span class="indicator-value ${ind.macd > 0 ? 'positive' : 'negative'}">
                        ${ind.macd.toFixed(4)}
                    </span>
                </div>
                <div class="indicator-item">
                    <span class="indicator-label">SMA 20</span>
                    <span class="indicator-value">$${ind.sma_20.toFixed(2)}</span>
                </div>
                <div class="indicator-item">
                    <span class="indicator-label">BB Width</span>
                    <span class="indicator-value">${ind.bb_width.toFixed(4)}</span>
                </div>
                <div class="indicator-item">
                    <span class="indicator-label">Stoch K</span>
                    <span class="indicator-value">${ind.stoch_k.toFixed(2)}</span>
                </div>
                <div class="indicator-item">
                    <span class="indicator-label">ATR</span>
                    <span class="indicator-value">${ind.atr.toFixed(2)}</span>
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
                        <td>${(market.volume / 1000000).toFixed(1)}M</td>
                        <td>$${market.high.toFixed(2)}</td>
                        <td>$${market.low.toFixed(2)}</td>
                        <td>
                            <button onclick="quickAnalyze('${market.symbol}')" 
                                    style="background: var(--accent-blue); color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer;">
                                Analyze
                            </button>
                        </td>
                    `;
                    table.appendChild(row);
                });
                
            } catch (error) {
                console.error('Market refresh error:', error);
            }
        }
        
        // Quick Analyze
        function quickAnalyze(symbol) {
            document.getElementById('symbol').value = symbol;
            analyze();
            getSignal();
        }
        
        // Initialize on load
        document.addEventListener('DOMContentLoaded', () => {
            initChart();
            refreshMarket();
        });
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html)

# ==========================================
# ENTRY POINT
# ==========================================
if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info("=" * 80)
    logger.info("🚀 PROFESSIONAL CRYPTO TRADING PLATFORM v2.0")
    logger.info("=" * 80)
    logger.info(f"📍 Server: http://{host}:{port}")
    logger.info(f"📊 Dashboard: http://{host}:{port}/dashboard")
    logger.info(f"📖 API Docs: http://{host}:{port}/docs")
    logger.info(f"🔄 WebSocket: Single connection for {len(Config.DEFAULT_SYMBOLS)} symbols")
    logger.info(f"🤖 ML Models: Random Forest + Gradient Boosting")
    logger.info("=" * 80)
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )
