"""
MAIN.PY - 11 EXCHANGE + COINGECKO ULTIMATE EDITION
===================================================
- 11 Borsa için Özel Parser'lar (Her borsaya özel)
- CoinGecko Tam Entegrasyon
- Akıllı Rate Limit Yönetimi
- Gelişmiş Hata Yönetimi & Retry Mekanizması
- Kusursuz Weighted Average Hesaplama
- Asenkron & Paralel Veri Çekme
"""

import os
import sys
import json
import time
import asyncio
import logging
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple, Callable
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum

# FastAPI
from fastapi import FastAPI, Request, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

# HTTP Client
import aiohttp
from aiohttp import ClientTimeout, TCPConnector, ClientResponseError

# Data Processing
import pandas as pd
import numpy as np

# ML Libraries (Optional)
ML_AVAILABLE = False
try:
    import lightgbm as lgb
    from sklearn.metrics import accuracy_score, precision_score, recall_score
    ML_AVAILABLE = True
except ImportError:
    pass

# ========================================================================================================
# ADVANCED LOGGING SETUP
# ========================================================================================================
def setup_logging():
    """Configure advanced logging system"""
    logger = logging.getLogger("trading_bot")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    
    # File handler
    file_handler = logging.FileHandler('trading_bot.log')
    file_handler.setLevel(logging.DEBUG)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | [%(name)s] | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()

# ========================================================================================================
# ENHANCED CONFIGURATION
# ========================================================================================================
class Config:
    """Advanced system configuration with dynamic settings"""
    
    # Environment
    ENV = os.getenv("ENV", "production")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    
    # API Settings
    API_TIMEOUT = 15
    MAX_RETRIES = 5
    RETRY_DELAY = 1
    RETRY_BACKOFF = 2.0
    
    # Data Requirements
    MIN_CANDLES = 50
    MIN_EXCHANGES = 3
    MAX_CANDLES = 1000
    
    # Cache
    CACHE_TTL = 30  # seconds
    CACHE_MAX_SIZE = 1000
    
    # Rate Limiting
    RATE_LIMIT_CALLS = 1200
    RATE_LIMIT_PERIOD = 60
    RATE_LIMIT_PER_HOST = 20
    
    # Connection Pool
    MAX_CONNECTIONS = 100
    MAX_CONNECTIONS_PER_HOST = 10
    
    # ML
    ML_MIN_SAMPLES = 500
    ML_TRAIN_SPLIT = 0.8
    
    # WebSocket
    WS_PING_INTERVAL = 30
    WS_PING_TIMEOUT = 10
    
    @classmethod
    def get_rate_limit_delay(cls, exchange: str) -> float:
        """Get rate limit delay for specific exchange"""
        delays = {
            'binance': 0.1,    # 10 requests/second
            'bybit': 0.2,      # 5 requests/second
            'okx': 0.2,        # 5 requests/second
            'kucoin': 0.3,     # 3 requests/second
            'gateio': 0.3,     # 3 requests/second
            'mexc': 0.2,       # 5 requests/second
            'kraken': 0.5,     # 2 requests/second
            'bitfinex': 0.3,   # 3 requests/second
            'huobi': 0.3,      # 3 requests/second
            'coinbase': 0.2,   # 5 requests/second
            'bitget': 0.3,     # 3 requests/second
            'coingecko': 1.0,  # 1 request/second
        }
        return delays.get(exchange.lower(), 0.5)

Config()

# ========================================================================================================
# ENHANCED DATA MODELS
# ========================================================================================================

@dataclass
class OHLCV:
    """OHLCV data model with validation"""
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    exchange: str
    quality_score: float = 1.0
    
    def __post_init__(self):
        """Validate data"""
        if self.high < self.low:
            self.high, self.low = self.low, self.high
        if self.open < 0 or self.high < 0 or self.low < 0 or self.close < 0:
            raise ValueError(f"Negative price in {self.exchange}")
        if self.volume < 0:
            self.volume = 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'timestamp': self.timestamp,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'exchange': self.exchange,
            'quality_score': self.quality_score
        }

@dataclass
class ExchangeStatus:
    """Exchange health status"""
    name: str
    is_active: bool = True
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    failure_count: int = 0
    success_count: int = 0
    avg_response_time: float = 0.0
    weight: float = 1.0
    
    @property
    def reliability_score(self) -> float:
        """Calculate reliability score"""
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.5
        return self.success_count / total
    
    @property
    def dynamic_weight(self) -> float:
        """Calculate dynamic weight based on reliability"""
        base_weight = self.weight
        reliability_bonus = self.reliability_score * 0.2
        return base_weight * (0.8 + reliability_bonus)

# ========================================================================================================
# RATE LIMITER
# ========================================================================================================
class RateLimiter:
    """Advanced rate limiter with per-exchange tracking"""
    
    def __init__(self):
        self.request_times: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.daily_limits: Dict[str, int] = defaultdict(int)
        self.last_reset = datetime.now()
        
    async def acquire(self, exchange: str) -> float:
        """Acquire permission to make request, returns delay needed"""
        now = datetime.now()
        
        # Reset daily limits
        if (now - self.last_reset).days > 0:
            self.daily_limits.clear()
            self.last_reset = now
        
        # Check daily limit
        if self.daily_limits[exchange] > Config.RATE_LIMIT_CALLS:
            wait_time = 60 - (now - self.last_reset).seconds
            if wait_time > 0:
                logger.warning(f"⚠️ Daily limit reached for {exchange}, waiting {wait_time}s")
                return wait_time
        
        # Check per-second rate
        recent_requests = [t for t in self.request_times[exchange] 
                          if (now - t).total_seconds() < Config.RATE_LIMIT_PERIOD]
        
        if len(recent_requests) >= Config.RATE_LIMIT_PER_HOST:
            # Calculate delay needed
            oldest = min(recent_requests) if recent_requests else now
            wait_time = Config.RATE_LIMIT_PERIOD - (now - oldest).total_seconds()
            if wait_time > 0:
                return wait_time + 0.1
        
        # Record request
        self.request_times[exchange].append(now)
        self.daily_limits[exchange] += 1
        
        return 0.0

# ========================================================================================================
# EXCHANGE DATA FETCHER - ULTIMATE EDITION
# ========================================================================================================
class ExchangeDataFetcher:
    """
    ULTIMATE EXCHANGE DATA FETCHER
    ===============================
    - 11 Borsa + CoinGecko tam entegrasyon
    - Her borsa için özel parser
    - Akıllı rate limit yönetimi
    - Dinamik weighted average
    - Gelişmiş hata yönetimi
    """
    
    # Exchange configurations with endpoints and data parsing
    EXCHANGES = [
        {
            "name": "Binance",
            "weight": 1.0,
            "endpoint": "https://api.binance.com/api/v3/klines",
            "symbol_fmt": lambda s: s.replace("/", ""),
            "needs_auth": False,
            "rate_limit": 1200,
            "timeout": 10
        },
        {
            "name": "Bybit",
            "weight": 0.95,
            "endpoint": "https://api.bybit.com/v5/market/kline",
            "symbol_fmt": lambda s: s.replace("/", ""),
            "needs_auth": False,
            "rate_limit": 600,
            "timeout": 10
        },
        {
            "name": "OKX",
            "weight": 0.9,
            "endpoint": "https://www.okx.com/api/v5/market/candles",
            "symbol_fmt": lambda s: s.replace("/", "-"),
            "needs_auth": False,
            "rate_limit": 600,
            "timeout": 10
        },
        {
            "name": "KuCoin",
            "weight": 0.85,
            "endpoint": "https://api.kucoin.com/api/v1/market/candles",
            "symbol_fmt": lambda s: s.replace("/", "-"),
            "needs_auth": False,
            "rate_limit": 300,
            "timeout": 15
        },
        {
            "name": "Gate.io",
            "weight": 0.8,
            "endpoint": "https://api.gateio.ws/api/v4/spot/candlesticks",
            "symbol_fmt": lambda s: s.replace("/", "_"),
            "needs_auth": False,
            "rate_limit": 300,
            "timeout": 15
        },
        {
            "name": "MEXC",
            "weight": 0.75,
            "endpoint": "https://api.mexc.com/api/v3/klines",
            "symbol_fmt": lambda s: s.replace("/", ""),
            "needs_auth": False,
            "rate_limit": 600,
            "timeout": 10
        },
        {
            "name": "Kraken",
            "weight": 0.7,
            "endpoint": "https://api.kraken.com/0/public/OHLC",
            "symbol_fmt": lambda s: s.replace("/", "").replace("USDT", "USD"),
            "needs_auth": False,
            "rate_limit": 300,
            "timeout": 15
        },
        {
            "name": "Bitfinex",
            "weight": 0.65,
            "endpoint": "https://api-pub.bitfinex.com/v2/candles/trade:{interval}:t{symbol}/hist",
            "symbol_fmt": lambda s: s.replace("/", "").replace("USDT", "UST"),
            "needs_auth": False,
            "rate_limit": 300,
            "timeout": 15
        },
        {
            "name": "Huobi",
            "weight": 0.6,
            "endpoint": "https://api.huobi.pro/market/history/kline",
            "symbol_fmt": lambda s: s.replace("/", "").lower(),
            "needs_auth": False,
            "rate_limit": 300,
            "timeout": 15
        },
        {
            "name": "Coinbase",
            "weight": 0.55,
            "endpoint": "https://api.exchange.coinbase.com/products/{symbol}/candles",
            "symbol_fmt": lambda s: s.replace("/", "-"),
            "needs_auth": False,
            "rate_limit": 600,
            "timeout": 10
        },
        {
            "name": "Bitget",
            "weight": 0.5,
            "endpoint": "https://api.bitget.com/api/spot/v1/market/candles",
            "symbol_fmt": lambda s: s.replace("/", ""),
            "needs_auth": False,
            "rate_limit": 300,
            "timeout": 15
        },
        {
            "name": "CoinGecko",
            "weight": 0.6,
            "endpoint": "https://api.coingecko.com/api/v3/coins/{symbol}/market_chart",
            "symbol_fmt": lambda s: s.replace("/", "").replace("USDT", "").lower(),
            "needs_auth": False,
            "rate_limit": 50,
            "timeout": 20
        }
    ]
    
    # Interval mappings for each exchange
    INTERVAL_MAP = {
        "1m": {
            "Binance": "1m", "Bybit": "1", "OKX": "1m", "KuCoin": "1min", 
            "Gate.io": "1m", "MEXC": "1m", "Kraken": "1", "Bitfinex": "1m", 
            "Huobi": "1min", "Coinbase": "60", "Bitget": "1m", "CoinGecko": "minutely"
        },
        "5m": {
            "Binance": "5m", "Bybit": "5", "OKX": "5m", "KuCoin": "5min",
            "Gate.io": "5m", "MEXC": "5m", "Kraken": "5", "Bitfinex": "5m",
            "Huobi": "5min", "Coinbase": "300", "Bitget": "5m", "CoinGecko": "minutely"
        },
        "15m": {
            "Binance": "15m", "Bybit": "15", "OKX": "15m", "KuCoin": "15min",
            "Gate.io": "15m", "MEXC": "15m", "Kraken": "15", "Bitfinex": "15m",
            "Huobi": "15min", "Coinbase": "900", "Bitget": "15m", "CoinGecko": "minutely"
        },
        "30m": {
            "Binance": "30m", "Bybit": "30", "OKX": "30m", "KuCoin": "30min",
            "Gate.io": "30m", "MEXC": "30m", "Kraken": "30", "Bitfinex": "30m",
            "Huobi": "30min", "Coinbase": "1800", "Bitget": "30m", "CoinGecko": "minutely"
        },
        "1h": {
            "Binance": "1h", "Bybit": "60", "OKX": "1H", "KuCoin": "1hour",
            "Gate.io": "1h", "MEXC": "1h", "Kraken": "60", "Bitfinex": "1h",
            "Huobi": "60min", "Coinbase": "3600", "Bitget": "1h", "CoinGecko": "hourly"
        },
        "4h": {
            "Binance": "4h", "Bybit": "240", "OKX": "4H", "KuCoin": "4hour",
            "Gate.io": "4h", "MEXC": "4h", "Kraken": "240", "Bitfinex": "4h",
            "Huobi": "4hour", "Coinbase": "14400", "Bitget": "4h", "CoinGecko": "hourly"
        },
        "1d": {
            "Binance": "1d", "Bybit": "D", "OKX": "1D", "KuCoin": "1day",
            "Gate.io": "1d", "MEXC": "1d", "Kraken": "1440", "Bitfinex": "1D",
            "Huobi": "1day", "Coinbase": "86400", "Bitget": "1d", "CoinGecko": "daily"
        },
        "1w": {
            "Binance": "1w", "Bybit": "W", "OKX": "1W", "KuCoin": "1week",
            "Gate.io": "1w", "MEXC": "1w", "Kraken": "10080", "Bitfinex": "1W",
            "Huobi": "1week", "Coinbase": "604800", "Bitget": "1w", "CoinGecko": "daily"
        }
    }
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, Any] = {}
        self.cache_time: Dict[str, float] = {}
        self.rate_limiter = RateLimiter()
        self.exchange_status: Dict[str, ExchangeStatus] = {}
        self.request_semaphore = asyncio.Semaphore(50)
        self._init_exchange_status()
        
    def _init_exchange_status(self):
        """Initialize exchange status tracking"""
        for exchange in self.EXCHANGES:
            self.exchange_status[exchange["name"]] = ExchangeStatus(
                name=exchange["name"],
                weight=exchange["weight"]
            )
    
    async def __aenter__(self):
        """Initialize HTTP session with optimized settings"""
        timeout = ClientTimeout(total=Config.API_TIMEOUT)
        connector = TCPConnector(
            limit=Config.MAX_CONNECTIONS,
            limit_per_host=Config.MAX_CONNECTIONS_PER_HOST,
            ttl_dns_cache=300,
            use_dns_cache=True,
            ssl=False
        )
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": "TradingBot/v7.0-Ultimate"}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close HTTP session"""
        if self.session:
            await self.session.close()
    
    # ========================================================================
    # EXCHANGE-SPECIFIC PARSERS
    # ========================================================================
    
    def _parse_binance(self, data: List) -> List[OHLCV]:
        """Binance özel parser"""
        candles = []
        try:
            for item in data:
                if isinstance(item, list) and len(item) >= 6:
                    candle = OHLCV(
                        timestamp=int(item[0]),
                        open=float(item[1]),
                        high=float(item[2]),
                        low=float(item[3]),
                        close=float(item[4]),
                        volume=float(item[5]),
                        exchange="Binance",
                        quality_score=1.0
                    )
                    candles.append(candle)
        except Exception as e:
            logger.error(f"Binance parse error: {e}")
        return candles
    
    def _parse_bybit(self, data: Dict) -> List[OHLCV]:
        """Bybit özel parser"""
        candles = []
        try:
            if data.get("result") and data["result"].get("list"):
                for item in data["result"]["list"]:
                    if len(item) >= 6:
                        candle = OHLCV(
                            timestamp=int(item[0]),
                            open=float(item[1]),
                            high=float(item[2]),
                            low=float(item[3]),
                            close=float(item[4]),
                            volume=float(item[5]),
                            exchange="Bybit",
                            quality_score=1.0
                        )
                        candles.append(candle)
        except Exception as e:
            logger.error(f"Bybit parse error: {e}")
        return candles
    
    def _parse_okx(self, data: Dict) -> List[OHLCV]:
        """OKX özel parser"""
        candles = []
        try:
            if data.get("data"):
                for item in data["data"]:
                    if len(item) >= 6:
                        candle = OHLCV(
                            timestamp=int(item[0]),
                            open=float(item[1]),
                            high=float(item[2]),
                            low=float(item[3]),
                            close=float(item[4]),
                            volume=float(item[5]),
                            exchange="OKX",
                            quality_score=1.0
                        )
                        candles.append(candle)
        except Exception as e:
            logger.error(f"OKX parse error: {e}")
        return candles
    
    def _parse_kucoin(self, data: Dict) -> List[OHLCV]:
        """KuCoin özel parser"""
        candles = []
        try:
            if data.get("data"):
                for item in data["data"]:
                    if isinstance(item, list) and len(item) >= 6:
                        candle = OHLCV(
                            timestamp=int(item[0]),
                            open=float(item[1]),
                            high=float(item[2]),
                            low=float(item[3]),
                            close=float(item[4]),
                            volume=float(item[5]),
                            exchange="KuCoin",
                            quality_score=0.95
                        )
                        candles.append(candle)
        except Exception as e:
            logger.error(f"KuCoin parse error: {e}")
        return candles
    
    def _parse_gateio(self, data: List) -> List[OHLCV]:
        """Gate.io özel parser"""
        candles = []
        try:
            for item in data:
                if isinstance(item, dict):
                    candle = OHLCV(
                        timestamp=int(item.get('t', 0)) * 1000,
                        open=float(item.get('o', 0)),
                        high=float(item.get('h', 0)),
                        low=float(item.get('l', 0)),
                        close=float(item.get('c', 0)),
                        volume=float(item.get('v', 0)),
                        exchange="Gate.io",
                        quality_score=0.95
                    )
                    candles.append(candle)
        except Exception as e:
            logger.error(f"Gate.io parse error: {e}")
        return candles
    
    def _parse_mexc(self, data: List) -> List[OHLCV]:
        """MEXC özel parser (Binance format)"""
        return self._parse_binance(data)
    
    def _parse_kraken(self, data: Dict) -> List[OHLCV]:
        """Kraken özel parser"""
        candles = []
        try:
            if data.get("result"):
                # Kraken returns pair as first key
                pair_key = [k for k in data["result"].keys() if k != "last"][0]
                for item in data["result"][pair_key]:
                    if len(item) >= 6:
                        candle = OHLCV(
                            timestamp=int(item[0]) * 1000,  # Kraken uses seconds
                            open=float(item[1]),
                            high=float(item[2]),
                            low=float(item[3]),
                            close=float(item[4]),
                            volume=float(item[6]),  # Volume is at index 6
                            exchange="Kraken",
                            quality_score=0.9
                        )
                        candles.append(candle)
        except Exception as e:
            logger.error(f"Kraken parse error: {e}")
        return candles
    
    def _parse_bitfinex(self, data: List) -> List[OHLCV]:
        """Bitfinex özel parser - OHLC sırası farklı!"""
        candles = []
        try:
            for item in data:
                if isinstance(item, list) and len(item) >= 6:
                    # Bitfinex format: [timestamp, open, close, high, low, volume]
                    candle = OHLCV(
                        timestamp=int(item[0]),
                        open=float(item[1]),
                        high=float(item[3]),  # High is index 3
                        low=float(item[4]),   # Low is index 4
                        close=float(item[2]), # Close is index 2
                        volume=float(item[5]),
                        exchange="Bitfinex",
                        quality_score=0.9
                    )
                    candles.append(candle)
        except Exception as e:
            logger.error(f"Bitfinex parse error: {e}")
        return candles
    
    def _parse_huobi(self, data: Dict) -> List[OHLCV]:
        """Huobi özel parser"""
        candles = []
        try:
            if data.get("data"):
                for item in data["data"]:
                    if isinstance(item, dict):
                        candle = OHLCV(
                            timestamp=int(item.get('id', 0)) * 1000,
                            open=float(item.get('open', 0)),
                            high=float(item.get('high', 0)),
                            low=float(item.get('low', 0)),
                            close=float(item.get('close', 0)),
                            volume=float(item.get('vol', 0)),
                            exchange="Huobi",
                            quality_score=0.9
                        )
                        candles.append(candle)
        except Exception as e:
            logger.error(f"Huobi parse error: {e}")
        return candles
    
    def _parse_coinbase(self, data: List) -> List[OHLCV]:
        """Coinbase özel parser - OHLC sırası farklı!"""
        candles = []
        try:
            for item in data:
                if isinstance(item, list) and len(item) >= 6:
                    # Coinbase format: [timestamp, low, high, open, close, volume]
                    candle = OHLCV(
                        timestamp=int(item[0]) * 1000,
                        open=float(item[3]),  # Open is index 3
                        high=float(item[2]),  # High is index 2
                        low=float(item[1]),   # Low is index 1
                        close=float(item[4]), # Close is index 4
                        volume=float(item[5]),
                        exchange="Coinbase",
                        quality_score=0.95
                    )
                    candles.append(candle)
        except Exception as e:
            logger.error(f"Coinbase parse error: {e}")
        return candles
    
    def _parse_bitget(self, data: Dict) -> List[OHLCV]:
        """Bitget özel parser"""
        candles = []
        try:
            if data.get("data"):
                for item in data["data"]:
                    if isinstance(item, list) and len(item) >= 6:
                        candle = OHLCV(
                            timestamp=int(item[0]),
                            open=float(item[1]),
                            high=float(item[2]),
                            low=float(item[3]),
                            close=float(item[4]),
                            volume=float(item[5]),
                            exchange="Bitget",
                            quality_score=0.9
                        )
                        candles.append(candle)
        except Exception as e:
            logger.error(f"Bitget parse error: {e}")
        return candles
    
    def _parse_coingecko(self, data: Dict) -> List[OHLCV]:
        """CoinGecko özel parser"""
        candles = []
        try:
            if data.get("prices") and data.get("total_volumes"):
                prices = data["prices"]
                volumes = data["total_volumes"]
                
                for i, (timestamp, price) in enumerate(prices):
                    if i < len(volumes):
                        # CoinGecko only gives close price
                        candle = OHLCV(
                            timestamp=int(timestamp),
                            open=float(price),
                            high=float(price * 1.001),  # Estimate
                            low=float(price * 0.999),   # Estimate
                            close=float(price),
                            volume=float(volumes[i][1]),
                            exchange="CoinGecko",
                            quality_score=0.8  # Lower quality due to estimation
                        )
                        candles.append(candle)
        except Exception as e:
            logger.error(f"CoinGecko parse error: {e}")
        return candles
    
    def _get_parser(self, exchange_name: str) -> Callable:
        """Get appropriate parser for exchange"""
        parsers = {
            "Binance": self._parse_binance,
            "Bybit": self._parse_bybit,
            "OKX": self._parse_okx,
            "KuCoin": self._parse_kucoin,
            "Gate.io": self._parse_gateio,
            "MEXC": self._parse_mexc,
            "Kraken": self._parse_kraken,
            "Bitfinex": self._parse_bitfinex,
            "Huobi": self._parse_huobi,
            "Coinbase": self._parse_coinbase,
            "Bitget": self._parse_bitget,
            "CoinGecko": self._parse_coingecko,
        }
        return parsers.get(exchange_name, self._parse_binance)
    
    # ========================================================================
    # ENHANCED FETCHING WITH RETRY MECHANISM
    # ========================================================================
    
    async def _fetch_with_retry(
        self, 
        exchange: Dict, 
        symbol: str, 
        interval: str, 
        limit: int
    ) -> Optional[List[OHLCV]]:
        """Fetch data with advanced retry logic"""
        exchange_name = exchange["name"]
        status = self.exchange_status[exchange_name]
        
        for attempt in range(Config.MAX_RETRIES):
            try:
                # Rate limiting
                delay = await self.rate_limiter.acquire(exchange_name)
                if delay > 0:
                    await asyncio.sleep(delay)
                
                # Add jitter to avoid thundering herd
                await asyncio.sleep(attempt * 0.1)
                
                # Fetch data
                start_time = time.time()
                candles = await self._fetch_exchange(exchange, symbol, interval, limit)
                response_time = time.time() - start_time
                
                if candles and len(candles) >= 10:
                    # Update success stats
                    status.last_success = datetime.now()
                    status.success_count += 1
                    status.avg_response_time = (status.avg_response_time * 0.7 + response_time * 0.3)
                    
                    return candles
                else:
                    raise ValueError(f"Insufficient data: {len(candles) if candles else 0} candles")
                    
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ Timeout {exchange_name} (attempt {attempt + 1}/{Config.MAX_RETRIES})")
                status.failure_count += 1
                
            except ClientResponseError as e:
                if e.status == 429:  # Rate limit
                    wait_time = Config.get_rate_limit_delay(exchange_name) * 10
                    logger.warning(f"⏳ Rate limit {exchange_name}, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                elif e.status >= 500:  # Server error
                    logger.warning(f"🔧 Server error {exchange_name}: {e.status}")
                    await asyncio.sleep(Config.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"❌ HTTP error {exchange_name}: {e.status}")
                    status.failure_count += 1
                    break
                    
            except Exception as e:
                logger.debug(f"⚠️ {exchange_name} error: {str(e)[:100]}")
                status.failure_count += 1
                
            # Exponential backoff
            if attempt < Config.MAX_RETRIES - 1:
                backoff = Config.RETRY_DELAY * (Config.RETRY_BACKOFF ** attempt)
                await asyncio.sleep(backoff)
        
        # Mark as temporarily inactive after multiple failures
        status.last_failure = datetime.now()
        if status.failure_count > 10:
            status.is_active = False
            logger.warning(f"⚠️ {exchange_name} marked as inactive (10+ failures)")
        
        return None
    
    async def _fetch_exchange(
        self, 
        exchange: Dict, 
        symbol: str, 
        interval: str, 
        limit: int
    ) -> Optional[List[OHLCV]]:
        """Fetch data from a single exchange"""
        exchange_name = exchange["name"]
        
        try:
            # Special handling for CoinGecko
            if exchange_name == "CoinGecko":
                return await self._fetch_coingecko(symbol, interval, limit)
            
            # Get exchange-specific interval format
            ex_interval = self.INTERVAL_MAP.get(interval, {}).get(exchange_name)
            if not ex_interval:
                return None
            
            # Format symbol for this exchange
            formatted_symbol = exchange["symbol_fmt"](symbol)
            
            # Build endpoint URL
            endpoint = exchange["endpoint"]
            if "{symbol}" in endpoint:
                endpoint = endpoint.format(symbol=formatted_symbol)
            if "{interval}" in endpoint:
                endpoint = endpoint.format(interval=ex_interval)
            
            # Build request parameters
            params = self._build_params(exchange_name, formatted_symbol, ex_interval, limit)
            
            # Make request
            async with self.request_semaphore:
                async with self.session.get(endpoint, params=params) as response:
                    if response.status != 200:
                        response.raise_for_status()
                    
                    data = await response.json()
                    
                    # Parse with exchange-specific parser
                    parser = self._get_parser(exchange_name)
                    candles = parser(data)
                    
                    if candles:
                        logger.debug(f"✅ {exchange_name}: {len(candles)} candles")
                    
                    return candles
                    
        except Exception as e:
            logger.debug(f"{exchange_name} fetch error: {str(e)[:100]}")
            return None
    
    async def _fetch_coingecko(
        self, 
        symbol: str, 
        interval: str, 
        limit: int
    ) -> Optional[List[OHLCV]]:
        """Special fetcher for CoinGecko"""
        try:
            # CoinGecko has different endpoint structure
            coin_id = symbol.replace("/", "").replace("USDT", "").lower()
            
            # Map interval to days
            days_map = {
                "1m": 1, "5m": 1, "15m": 1, "30m": 1,
                "1h": 7, "4h": 30, "1d": 90, "1w": 365
            }
            days = days_map.get(interval, 7)
            
            # Get interval for CoinGecko
            gecko_interval = self.INTERVAL_MAP.get(interval, {}).get("CoinGecko", "hourly")
            
            url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
            params = {
                "vs_currency": "usd",
                "days": days,
                "interval": gecko_interval
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                return self._parse_coingecko(data)
                
        except Exception as e:
            logger.debug(f"CoinGecko fetch error: {e}")
            return None
    
    def _build_params(
        self, 
        exchange_name: str, 
        symbol: str, 
        interval: str, 
        limit: int
    ) -> Dict:
        """Build request parameters for specific exchange"""
        params_map = {
            "Binance": {"symbol": symbol, "interval": interval, "limit": limit},
            "Bybit": {"category": "spot", "symbol": symbol, "interval": interval, "limit": limit},
            "OKX": {"instId": symbol, "bar": interval, "limit": limit},
            "KuCoin": {"symbol": symbol, "type": interval},
            "Gate.io": {"currency_pair": symbol, "interval": interval, "limit": limit},
            "MEXC": {"symbol": symbol, "interval": interval, "limit": limit},
            "Kraken": {"pair": symbol, "interval": interval},
            "Bitfinex": {"limit": min(limit, 100)},  # Bitfinex max 100
            "Huobi": {"symbol": symbol, "period": interval, "size": limit},
            "Coinbase": {"granularity": interval},
            "Bitget": {"symbol": symbol, "period": interval, "limit": limit},
        }
        return params_map.get(exchange_name, {})
    
    # ========================================================================
    # ADVANCED AGGREGATION
    # ========================================================================
    
    def _aggregate_candles(self, all_candles: List[List[OHLCV]]) -> List[Dict]:
        """
        Kusursuz weighted average hesaplama
        - Dinamik weight (reliability + base weight)
        - Quality score
        - Outlier elimination
        - Timestamp alignment
        """
        if not all_candles:
            return []
        
        # Group by timestamp (1-minute precision)
        timestamp_map = defaultdict(list)
        
        for exchange_candles in all_candles:
            for candle in exchange_candles:
                # Round timestamp to minute
                rounded_ts = (candle.timestamp // 60000) * 60000
                timestamp_map[rounded_ts].append(candle)
        
        # Aggregate each timestamp
        aggregated = []
        
        for timestamp in sorted(timestamp_map.keys()):
            candles_at_ts = timestamp_map[timestamp]
            
            if len(candles_at_ts) == 1:
                # Single source
                candle = candles_at_ts[0]
                aggregated.append({
                    "timestamp": timestamp,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                    "source_count": 1,
                    "sources": [candle.exchange],
                    "exchange": "aggregated",
                    "quality_score": candle.quality_score
                })
            else:
                # Multiple sources - remove outliers first
                closes = [c.close for c in candles_at_ts]
                q1, q3 = np.percentile(closes, [25, 75])
                iqr = q3 - q1
                lower_bound = q1 - 1.5 * iqr
                upper_bound = q3 + 1.5 * iqr
                
                # Filter outliers
                valid_candles = [
                    c for c in candles_at_ts 
                    if lower_bound <= c.close <= upper_bound
                ]
                
                if not valid_candles:
                    valid_candles = candles_at_ts  # Fallback to all
                
                # Calculate weights
                weights = []
                opens, highs, lows, closes, volumes = [], [], [], [], []
                
                for candle in valid_candles:
                    # Get dynamic weight from exchange status
                    status = self.exchange_status.get(candle.exchange)
                    base_weight = status.dynamic_weight if status else 0.5
                    
                    # Quality score adjustment
                    quality_adjustment = candle.quality_score
                    
                    # Recent success bonus
                    if status and status.last_success:
                        time_since_success = (datetime.now() - status.last_success).total_seconds()
                        recency_bonus = max(0, 1 - time_since_success / 3600) * 0.1
                    else:
                        recency_bonus = 0
                    
                    final_weight = base_weight * quality_adjustment * (1 + recency_bonus)
                    weights.append(final_weight)
                    
                    opens.append(candle.open * final_weight)
                    highs.append(candle.high * final_weight)
                    lows.append(candle.low * final_weight)
                    closes.append(candle.close * final_weight)
                    volumes.append(candle.volume * final_weight)
                
                total_weight = sum(weights)
                
                if total_weight > 0:
                    aggregated.append({
                        "timestamp": timestamp,
                        "open": sum(opens) / total_weight,
                        "high": sum(highs) / total_weight,
                        "low": sum(lows) / total_weight,
                        "close": sum(closes) / total_weight,
                        "volume": sum(volumes) / total_weight,
                        "source_count": len(candles_at_ts),
                        "valid_source_count": len(valid_candles),
                        "sources": [c.exchange for c in candles_at_ts[:5]],  # Top 5
                        "exchange": "aggregated",
                        "quality_score": np.mean([c.quality_score for c in valid_candles])
                    })
        
        return aggregated
    
    # ========================================================================
    # MAIN PUBLIC METHOD
    # ========================================================================
    
    async def get_candles(
        self, 
        symbol: str, 
        interval: str = "1h", 
        limit: int = 100
    ) -> List[Dict]:
        """
        Fetch and aggregate candle data from all exchanges
        
        Args:
            symbol: Trading pair (e.g., BTC/USDT)
            interval: Timeframe (e.g., 1h)
            limit: Number of candles
            
        Returns:
            List of aggregated OHLCV candles
        """
        # Check cache
        cache_key = f"{symbol}_{interval}_{limit}"
        if cache_key in self.cache:
            if time.time() - self.cache_time.get(cache_key, 0) < Config.CACHE_TTL:
                logger.debug(f"📦 Cache hit for {symbol} ({interval})")
                return self.cache[cache_key][-limit:]
        
        # Fetch from all exchanges in parallel
        logger.info(f"🔄 Fetching {symbol} ({interval}) from {len(self.EXCHANGES)} sources...")
        
        tasks = [
            self._fetch_with_retry(exchange, symbol, interval, limit * 2)
            for exchange in self.EXCHANGES
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter valid results
        valid_results = [
            result for result in results
            if isinstance(result, list) and len(result) >= 10
        ]
        
        active_exchanges = len([r for r in results if isinstance(r, list)])
        logger.info(f"✅ Got data from {active_exchanges}/{len(self.EXCHANGES)} sources")
        
        # Require minimum exchanges
        if active_exchanges < Config.MIN_EXCHANGES:
            logger.warning(f"⚠️ Only {active_exchanges} sources responded (need {Config.MIN_EXCHANGES})")
            
            # Try to return cached data if available
            if cache_key in self.cache:
                logger.info(f"📦 Returning cached data for {symbol}")
                return self.cache[cache_key][-limit:]
            return []
        
        # Aggregate data
        aggregated = self._aggregate_candles(valid_results)
        
        if len(aggregated) < Config.MIN_CANDLES:
            logger.warning(f"⚠️ Only {len(aggregated)} candles (need {Config.MIN_CANDLES})")
            
            # Try to return cached data
            if cache_key in self.cache:
                return self.cache[cache_key][-limit:]
            return []
        
        # Sort by timestamp
        aggregated.sort(key=lambda x: x["timestamp"])
        
        # Cache result
        self.cache[cache_key] = aggregated
        self.cache_time[cache_key] = time.time()
        
        # Clean old cache
        self._clean_cache()
        
        # Log exchange status
        self._log_exchange_status()
        
        logger.info(f"📊 Aggregated {len(aggregated)} candles from {active_exchanges} sources")
        
        return aggregated[-limit:]
    
    def _clean_cache(self):
        """Clean old cache entries"""
        current_time = time.time()
        keys_to_delete = []
        
        for key, cache_time in self.cache_time.items():
            if current_time - cache_time > Config.CACHE_TTL * 10:
                keys_to_delete.append(key)
        
        for key in keys_to_delete:
            del self.cache[key]
            del self.cache_time[key]
    
    def _log_exchange_status(self):
        """Log exchange health status"""
        active = [name for name, status in self.exchange_status.items() if status.is_active]
        inactive = [name for name, status in self.exchange_status.items() if not status.is_active]
        
        if inactive:
            logger.info(f"📡 Active sources: {len(active)}, Inactive: {len(inactive)}")
        
        # Log top performers
        top_exchanges = sorted(
            self.exchange_status.values(),
            key=lambda x: x.reliability_score,
            reverse=True
        )[:3]
        
        if top_exchanges:
            logger.debug(f"🏆 Top sources: " + 
                        ", ".join([f"{e.name}({e.reliability_score:.1%})" for e in top_exchanges]))
    
    def get_exchange_stats(self) -> Dict[str, Any]:
        """Get detailed exchange statistics"""
        stats = {}
        
        for name, status in self.exchange_status.items():
            stats[name] = {
                "active": status.is_active,
                "success_rate": f"{status.reliability_score:.1%}",
                "total_requests": status.success_count + status.failure_count,
                "success": status.success_count,
                "failure": status.failure_count,
                "avg_response_time": f"{status.avg_response_time:.3f}s",
                "last_success": status.last_success.isoformat() if status.last_success else None,
                "last_failure": status.last_failure.isoformat() if status.last_failure else None,
                "dynamic_weight": f"{status.dynamic_weight:.3f}"
            }
        
        return stats


# ========================================================================================================
# TECHNICAL ANALYSIS ENGINE (Enhanced)
# ========================================================================================================
class TechnicalAnalyzer:
    """Enhanced technical analysis with more indicators"""
    
    @staticmethod
    def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator"""
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)
    
    @staticmethod
    def calculate_macd(close: pd.Series) -> tuple:
        """Calculate MACD indicator"""
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        histogram = macd - signal
        return macd, signal, histogram
    
    @staticmethod
    def calculate_bollinger_bands(close: pd.Series, period: int = 20, std_dev: int = 2) -> tuple:
        """Calculate Bollinger Bands"""
        middle = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        return upper, middle, lower
    
    @staticmethod
    def calculate_stochastic_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Stochastic RSI"""
        rsi = TechnicalAnalyzer.calculate_rsi(close, period)
        rsi_min = rsi.rolling(window=period).min()
        rsi_max = rsi.rolling(window=period).max()
        stoch = 100 * (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
        return (stoch.fillna(50) / 100)
    
    @staticmethod
    def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Average True Range"""
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr.fillna(0)
    
    @staticmethod
    def calculate_volume_profile(df: pd.DataFrame, bins: int = 20) -> Dict:
        """Calculate Volume Profile"""
        try:
            df = df.copy()
            df['price_bin'] = pd.cut(df['close'], bins=bins)
            volume_profile = df.groupby('price_bin')['volume'].sum()
            
            if not volume_profile.empty:
                max_volume_bin = volume_profile.idxmax()
                poc_price = max_volume_bin.mid
                total_volume = volume_profile.sum()
                high_volume_nodes = volume_profile[volume_profile > total_volume * 0.1].index
                
                return {
                    'poc_price': poc_price,
                    'high_volume_nodes': [node.mid for node in high_volume_nodes[:3]],
                    'volume_distribution': volume_profile.to_dict()
                }
        except Exception as e:
            logger.debug(f"Volume profile error: {e}")
        
        return {}
    
    @staticmethod
    def analyze(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculate all technical indicators
        """
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        # RSI
        rsi = TechnicalAnalyzer.calculate_rsi(close)
        
        # MACD
        macd, macd_signal, macd_hist = TechnicalAnalyzer.calculate_macd(close)
        
        # Bollinger Bands
        bb_upper, bb_middle, bb_lower = TechnicalAnalyzer.calculate_bollinger_bands(close)
        bb_position = ((close - bb_lower) / (bb_upper - bb_lower) * 100).clip(0, 100).fillna(50)
        bb_width = ((bb_upper - bb_lower) / bb_middle * 100).fillna(0)
        
        # Stochastic RSI
        stoch_rsi = TechnicalAnalyzer.calculate_stochastic_rsi(close)
        
        # ATR
        atr = TechnicalAnalyzer.calculate_atr(high, low, close)
        atr_percent = (atr / close * 100).fillna(0)
        
        # Volume analysis
        volume_sma = volume.rolling(20).mean()
        volume_ratio = (volume / volume_sma.replace(0, 1)).fillna(1.0)
        volume_trend = "INCREASING" if volume.iloc[-1] > volume_sma.iloc[-1] else "DECREASING"
        
        # Volume Profile
        volume_profile = TechnicalAnalyzer.calculate_volume_profile(df)
        
        # Support and Resistance
        recent_high = high.tail(20).max()
        recent_low = low.tail(20).min()
        
        return {
            "rsi_value": float(rsi.iloc[-1]),
            "macd_histogram": float(macd_hist.iloc[-1]),
            "bb_position": float(bb_position.iloc[-1]),
            "bb_width": float(bb_width.iloc[-1]),
            "stoch_rsi": float(stoch_rsi.iloc[-1]),
            "volume_ratio": float(volume_ratio.iloc[-1]),
            "volume_trend": volume_trend,
            "atr": float(atr.iloc[-1]),
            "atr_percent": float(atr_percent.iloc[-1]),
            "bb_upper": float(bb_upper.iloc[-1]),
            "bb_middle": float(bb_middle.iloc[-1]),
            "bb_lower": float(bb_lower.iloc[-1]),
            "macd": float(macd.iloc[-1]),
            "macd_signal": float(macd_signal.iloc[-1]),
            "recent_high": float(recent_high),
            "recent_low": float(recent_low),
            "volume_profile": volume_profile
        }


# ========================================================================================================
# PATTERN DETECTOR (Enhanced)
# ========================================================================================================
class PatternDetector:
    """Advanced candlestick pattern detector"""
    
    PATTERNS = {
        'hammer': {'name': 'Hammer', 'direction': 'bullish', 'confidence': 0.75},
        'shooting_star': {'name': 'Shooting Star', 'direction': 'bearish', 'confidence': 0.75},
        'bullish_engulfing': {'name': 'Bullish Engulfing', 'direction': 'bullish', 'confidence': 0.85},
        'bearish_engulfing': {'name': 'Bearish Engulfing', 'direction': 'bearish', 'confidence': 0.85},
        'doji': {'name': 'Doji', 'direction': 'neutral', 'confidence': 0.60},
        'morning_star': {'name': 'Morning Star', 'direction': 'bullish', 'confidence': 0.80},
        'evening_star': {'name': 'Evening Star', 'direction': 'bearish', 'confidence': 0.80},
        'three_white_soldiers': {'name': 'Three White Soldiers', 'direction': 'bullish', 'confidence': 0.85},
        'three_black_crows': {'name': 'Three Black Crows', 'direction': 'bearish', 'confidence': 0.85},
    }
    
    @staticmethod
    def detect(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Detect candlestick patterns
        """
        patterns = []
        
        if len(df) < 10:
            return patterns
        
        close = df['close'].values
        open_ = df['open'].values
        high = df['high'].values
        low = df['low'].values
        
        # Analyze recent candles
        start_idx = max(0, len(df) - 30)
        
        for i in range(start_idx, len(df) - 1):
            # Hammer / Shooting Star
            body = abs(close[i] - open_[i])
            range_ = high[i] - low[i]
            
            if range_ > 0:
                lower_shadow = min(open_[i], close[i]) - low[i]
                upper_shadow = high[i] - max(open_[i], close[i])
                
                # Hammer
                if lower_shadow > body * 2 and upper_shadow < body * 0.3:
                    patterns.append({
                        "name": "Hammer",
                        "direction": "bullish",
                        "confidence": 0.75,
                        "candle_index": i
                    })
                
                # Shooting Star
                if upper_shadow > body * 2 and lower_shadow < body * 0.3:
                    patterns.append({
                        "name": "Shooting Star",
                        "direction": "bearish",
                        "confidence": 0.75,
                        "candle_index": i
                    })
            
            # Engulfing patterns
            if i > 0:
                # Bullish Engulfing
                if close[i] > open_[i] and \
                   close[i - 1] < open_[i - 1] and \
                   open_[i] < close[i - 1] and \
                   close[i] > open_[i - 1]:
                    patterns.append({
                        "name": "Bullish Engulfing",
                        "direction": "bullish",
                        "confidence": 0.85,
                        "candle_index": i
                    })
                
                # Bearish Engulfing
                if close[i] < open_[i] and \
                   close[i - 1] > open_[i - 1] and \
                   open_[i] > close[i - 1] and \
                   close[i] < open_[i - 1]:
                    patterns.append({
                        "name": "Bearish Engulfing",
                        "direction": "bearish",
                        "confidence": 0.85,
                        "candle_index": i
                    })
            
            # Doji
            if range_ > 0 and abs(close[i] - open_[i]) < range_ * 0.1:
                patterns.append({
                    "name": "Doji",
                    "direction": "neutral",
                    "confidence": 0.60,
                    "candle_index": i
                })
        
        # Remove duplicates and sort by confidence
        unique_patterns = []
        seen = set()
        
        for p in patterns:
            key = f"{p['name']}_{p['candle_index']}"
            if key not in seen:
                seen.add(key)
                unique_patterns.append(p)
        
        unique_patterns.sort(key=lambda x: x['confidence'], reverse=True)
        
        return unique_patterns[:15]  # Return top 15 patterns


# ========================================================================================================
# FASTAPI APPLICATION
# ========================================================================================================
app = FastAPI(
    title="Ultimate Trading Bot v7.0",
    description="Real-time cryptocurrency trading analysis from 11+ exchanges + CoinGecko",
    version="7.0.0",
    docs_url="/docs" if Config.DEBUG else None,
    redoc_url="/redoc" if Config.DEBUG else None,
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if Config.DEBUG else ["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Security headers
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["X-Content-Security-Policy"] = "default-src 'self'"
    return response

# Global instances
data_fetcher = ExchangeDataFetcher()
ml_engine = None  # Will be initialized if ML available
websocket_connections = set()
startup_time = time.time()


# ========================================================================================================
# API ENDPOINTS
# ========================================================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve index.html as homepage"""
    html_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return HTMLResponse("""
    <html>
    <head>
        <title>Ultimate Trading Bot v7.0</title>
        <style>
            body { font-family: Arial; margin: 40px; background: #0a0c10; color: #e6e9f0; }
            h1 { color: #00ff9d; }
            .status { padding: 20px; background: #1a1e24; border-radius: 10px; margin-top: 20px; }
            .green { color: #00ff9d; }
        </style>
    </head>
    <body>
        <h1>🚀 Ultimate Trading Bot v7.0</h1>
        <p>AI-Powered Crypto Trading Platform - 11 Exchanges + CoinGecko</p>
        <div class="status">
            <h2>✅ System Online</h2>
            <p class="green">✓ 11 Exchanges + CoinGecko Integrated</p>
            <p class="green">✓ Real-time Data Aggregation Active</p>
            <p class="green">✓ Advanced Technical Analysis Ready</p>
        </div>
    </body>
    </html>
    """)


@app.get("/health")
async def health_check():
    """Health check endpoint with detailed status"""
    uptime = time.time() - startup_time
    exchange_stats = data_fetcher.get_exchange_stats()
    
    active_exchanges = sum(1 for s in exchange_stats.values() if s.get('active', False))
    
    return {
        "status": "healthy",
        "version": "7.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": int(uptime),
        "uptime_formatted": str(timedelta(seconds=int(uptime))),
        "ml_available": ML_AVAILABLE,
        "exchanges": {
            "total": len(ExchangeDataFetcher.EXCHANGES),
            "active": active_exchanges,
            "inactive": len(ExchangeDataFetcher.EXCHANGES) - active_exchanges
        },
        "cache_size": len(data_fetcher.cache),
        "exchange_stats": exchange_stats
    }


@app.get("/api/analyze/{symbol}")
async def analyze_symbol(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1m|5m|15m|30m|1h|4h|1d|1w)$"),
    limit: int = Query(default=100, ge=50, le=500)
):
    """
    Complete market analysis with 11 exchanges + CoinGecko data
    """
    # Normalize symbol
    symbol = symbol.upper()
    if not symbol.endswith("USDT") and not symbol.endswith("USD"):
        symbol = f"{symbol}USDT"
    
    logger.info(f"🔍 Analyzing {symbol} ({interval}, limit={limit})")
    
    try:
        # Fetch candle data from all exchanges
        async with data_fetcher as fetcher:
            candles = await fetcher.get_candles(symbol, interval, limit)
        
        if not candles or len(candles) < Config.MIN_CANDLES:
            raise HTTPException(
                status_code=422,
                detail=f"Insufficient data. Got {len(candles) if candles else 0} candles, need {Config.MIN_CANDLES}"
            )
        
        # Convert to DataFrame
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp')
        
        # Calculate Technical Indicators
        technical_indicators = TechnicalAnalyzer.analyze(df)
        
        # Detect Patterns
        patterns = PatternDetector.detect(df)
        
        # Get Exchange Stats
        exchange_stats = data_fetcher.get_exchange_stats()
        
        # Price Data
        current_price = float(df['close'].iloc[-1])
        prev_price = float(df['close'].iloc[-2]) if len(df) > 1 else current_price
        change_percent = ((current_price - prev_price) / prev_price * 100) if prev_price != 0 else 0.0
        volume_24h = float(df['volume'].tail(24).sum())
        
        # Build response
        response = {
            "success": True,
            "symbol": symbol,
            "interval": interval,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data_quality": {
                "source_count": candles[-1].get('source_count', 0) if candles else 0,
                "valid_source_count": candles[-1].get('valid_source_count', 0) if candles else 0,
                "quality_score": candles[-1].get('quality_score', 1.0) if candles else 1.0
            },
            "price_data": {
                "current": current_price,
                "previous": prev_price,
                "change_percent": round(change_percent, 4),
                "change_abs": round(current_price - prev_price, 2),
                "volume_24h": volume_24h,
                "high_24h": float(df['high'].tail(24).max()),
                "low_24h": float(df['low'].tail(24).min())
            },
            "technical_indicators": technical_indicators,
            "patterns": patterns,
            "exchange_stats": exchange_stats
        }
        
        logger.info(f"✅ Analysis complete: {len(patterns)} patterns detected")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Analysis failed: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)[:200]}"
        )


@app.get("/api/exchanges")
async def get_exchanges():
    """Get detailed exchange status and statistics"""
    exchange_stats = data_fetcher.get_exchange_stats()
    
    return {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "exchanges": [
                {
                    "name": name,
                    **stats
                }
                for name, stats in exchange_stats.items()
            ],
            "total": len(exchange_stats),
            "active": sum(1 for s in exchange_stats.values() if s.get('active', False))
        }
    }


@app.websocket("/ws/{symbol}")
async def websocket_endpoint(websocket: WebSocket, symbol: str):
    """WebSocket for real-time price updates from aggregated data"""
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    
    await websocket.accept()
    websocket_connections.add(websocket)
    logger.info(f"🔗 WebSocket connected for {symbol}")
    
    try:
        last_price = None
        while True:
            # Fetch latest aggregated price
            async with data_fetcher as fetcher:
                candles = await fetcher.get_candles(symbol, "1m", 2)
            
            if candles and len(candles) >= 2:
                current_price = candles[-1]['close']
                prev_price = candles[-2]['close']
                
                if last_price is None or abs(current_price - last_price) > last_price * 0.0001:
                    change_pct = ((current_price - prev_price) / prev_price * 100) if prev_price != 0 else 0
                    
                    await websocket.send_json({
                        "type": "price_update",
                        "symbol": symbol,
                        "price": float(current_price),
                        "change_percent": round(change_pct, 4),
                        "volume": float(candles[-1]['volume']),
                        "source_count": candles[-1].get('source_count', 0),
                        "quality_score": candles[-1].get('quality_score', 1.0),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    
                    last_price = current_price
            
            await asyncio.sleep(2)
            
    except WebSocketDisconnect:
        logger.info(f"❌ WebSocket disconnected for {symbol}")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        websocket_connections.discard(websocket)


@app.get("/api/cache/stats")
async def get_cache_stats():
    """Get cache statistics"""
    return {
        "success": True,
        "cache_size": len(data_fetcher.cache),
        "cache_keys": list(data_fetcher.cache.keys())[:10],
        "cache_age": {
            key: time.time() - data_fetcher.cache_time[key]
            for key in list(data_fetcher.cache_time.keys())[:10]
        }
    }


@app.post("/api/cache/clear")
async def clear_cache():
    """Clear data cache"""
    data_fetcher.cache.clear()
    data_fetcher.cache_time.clear()
    return {"success": True, "message": "Cache cleared"}


# ========================================================================================================
# STARTUP/SHUTDOWN
# ========================================================================================================

@app.on_event("startup")
async def startup_event():
    """Application startup with enhanced logging"""
    logger.info("=" * 100)
    logger.info("🚀 ULTIMATE TRADING BOT v7.0 STARTED")
    logger.info("=" * 100)
    logger.info(f"Environment: {Config.ENV}")
    logger.info(f"Debug Mode: {Config.DEBUG}")
    logger.info(f"ML Available: {ML_AVAILABLE}")
    logger.info(f"Exchanges + CoinGecko: {len(ExchangeDataFetcher.EXCHANGES)}")
    logger.info(f"Min Exchanges Required: {Config.MIN_EXCHANGES}")
    logger.info(f"Min Candles Required: {Config.MIN_CANDLES}")
    logger.info(f"Cache TTL: {Config.CACHE_TTL}s")
    logger.info(f"Max Retries: {Config.MAX_RETRIES}")
    logger.info("=" * 100)


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown"""
    logger.info("🛑 Shutting down Ultimate Trading Bot v7.0")
    
    # Close all WebSocket connections
    for ws in websocket_connections:
        try:
            await ws.close()
        except:
            pass
    
    websocket_connections.clear()
    logger.info("✅ Shutdown complete")


# ========================================================================================================
# MAIN
# ========================================================================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info(f"🌐 Starting server on {host}:{port}")
    logger.info(f"📚 API Documentation: http://{host if host != '0.0.0.0' else 'localhost'}:{port}/docs")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=Config.DEBUG,
        log_level="info" if Config.DEBUG else "warning",
        access_log=Config.DEBUG
    )
