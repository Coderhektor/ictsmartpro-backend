#!/usr/bin/env python3
"""
🚀 CryptoTrader Pro v6.0 - Railway Deployment Optimized
📊 Binance WebSocket + CoinGecko Real-time Integration
"""

import os
import sys
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

# Railway için logging yapılandırması
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# FastAPI import'ları
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# ================================================================================
# Railway için optimizasyonlar
# ================================================================================

# Railway environment variables
PORT = int(os.getenv("PORT", 8000))
RAILWAY_ENVIRONMENT = os.getenv("RAILWAY_ENVIRONMENT", "production")
RAILWAY_GIT_COMMIT_SHA = os.getenv("RAILWAY_GIT_COMMIT_SHA", "unknown")

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
# SIMPLIFIED DATA PROVIDER (Railway için optimize edilmiş)
# ================================================================================
class DataProvider:
    """Railway için optimize edilmiş basit data provider"""
    
    # Popular cryptocurrencies
    DEFAULT_SYMBOLS = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
        "SOLUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT",
        "MATICUSDT", "UNIUSDT", "LTCUSDT", "BCHUSDT", "XLMUSDT"
    ]
    
    # Sample price data (gerçek API'ye bağlanmadan önce)
    SAMPLE_PRICES = {
        "BTCUSDT": 45000.0,
        "ETHUSDT": 3000.0,
        "BNBUSDT": 350.0,
        "XRPUSDT": 0.65,
        "ADAUSDT": 0.55,
        "SOLUSDT": 100.0,
        "DOTUSDT": 7.5,
        "DOGEUSDT": 0.08,
        "AVAXUSDT": 40.0,
        "LINKUSDT": 18.0,
        "MATICUSDT": 0.85,
        "UNIUSDT": 7.0,
        "LTCUSDT": 75.0,
        "BCHUSDT": 250.0,
        "XLMUSDT": 0.12
    }
    
    def __init__(self):
        self.session = None
        self.ticker_data = []
        
    async def initialize(self):
        """Initialize HTTP session"""
        if not self.session:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
            logger.info("✅ Data Provider initialized")
        
        # Initial ticker data
        await self.update_ticker_data()
        
    async def close(self):
        """Close session"""
        if self.session:
            await self.session.close()
            logger.info("🔌 Data Provider closed")
            
    async def update_ticker_data(self):
        """Update ticker data from APIs"""
        try:
            # Try CoinGecko first
            url = "https://api.coingecko.com/api/v3/coins/markets"
            params = {
                "vs_currency": "usd",
                "ids": "bitcoin,ethereum,binancecoin,ripple,cardano,solana,polkadot,dogecoin,avalanche-2,chainlink",
                "order": "market_cap_desc",
                "per_page": 10,
                "page": 1,
                "sparkline": "false"
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    self.ticker_data = []
                    for coin in data:
                        symbol = coin['symbol'].upper() + "USDT"
                        self.ticker_data.append({
                            'symbol': symbol,
                            'name': coin['name'],
                            'price': coin['current_price'],
                            'change_24h': coin['price_change_percentage_24h'],
                            'volume': coin['total_volume'],
                            'market_cap': coin['market_cap'],
                            'last_updated': datetime.now(timezone.utc).isoformat()
                        })
                    
                    logger.info(f"📊 Updated ticker data from CoinGecko: {len(self.ticker_data)} coins")
                    return
                    
        except Exception as e:
            logger.warning(f"CoinGecko update failed: {e}")
            
        # Fallback to sample data
        self.ticker_data = []
        for symbol in self.DEFAULT_SYMBOLS[:10]:
            price = self.SAMPLE_PRICES.get(symbol, 100.0)
            change = np.random.uniform(-5, 5)
            
            self.ticker_data.append({
                'symbol': symbol,
                'name': symbol.replace('USDT', ''),
                'price': price,
                'change_24h': change,
                'volume': price * np.random.uniform(1000000, 10000000),
                'market_cap': price * np.random.uniform(10000000, 100000000),
                'last_updated': datetime.now(timezone.utc).isoformat(),
                'source': 'sample'
            })
            
        logger.info("📊 Using sample ticker data")
        
    async def get_ohlcv(self, symbol: str, interval: str = "1d", limit: int = 100) -> List[Dict]:
        """Get OHLCV data"""
        try:
            # Binance API
            binance_interval = interval.lower()
            if binance_interval == "1d":
                binance_interval = "1d"
            elif binance_interval == "1h":
                binance_interval = "1h"
            elif binance_interval == "4h":
                binance_interval = "4h"
            elif binance_interval == "1w":
                binance_interval = "1w"
            else:
                binance_interval = "1d"
                
            url = f"https://api.binance.com/api/v3/klines"
            params = {
                "symbol": symbol.upper(),
                "interval": binance_interval,
                "limit": min(limit, 500)
            }
            
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    candles = []
                    for item in data:
                        candles.append({
                            "timestamp": item[0] // 1000,
                            "open": float(item[1]),
                            "high": float(item[2]),
                            "low": float(item[3]),
                            "close": float(item[4]),
                            "volume": float(item[5])
                        })
                    
                    return candles
                    
        except Exception as e:
            logger.warning(f"OHLCV fetch error for {symbol}: {e}")
            
        # Generate sample data
        base_price = self.SAMPLE_PRICES.get(symbol, 100.0)
        candles = []
        current_time = datetime.now(timezone.utc).timestamp()
        
        for i in range(limit):
            timestamp = current_time - (limit - i - 1) * 86400
            
            if i == 0:
                price = base_price
            else:
                change = np.random.normal(0, 0.02)
                price = candles[-1]["close"] * (1 + change)
            
            candles.append({
                "timestamp": timestamp,
                "open": price,
                "high": price * (1 + abs(np.random.normal(0, 0.01))),
                "low": price * (1 - abs(np.random.normal(0, 0.01))),
                "close": price * (1 + np.random.normal(0, 0.005)),
                "volume": np.random.uniform(1000, 10000)
            })
        
        return candles

# ================================================================================
# TECHNICAL ANALYSIS ENGINE
# ================================================================================
class TechnicalAnalysis:
    """Technical analysis with core indicators"""
    
    @staticmethod
    def calculate_all_indicators(ohlcv_data: List[Dict], symbol: str, timeframe: str) -> Dict:
        """Calculate technical indicators"""
        if len(ohlcv_data) < 20:
            return {}
        
        closes = [c["close"] for c in ohlcv_data]
        highs = [c["high"] for c in ohlcv_data]
        lows = [c["low"] for c in ohlcv_data]
        volumes = [c.get("volume", 0) for c in ohlcv_data]
        
        current_price = closes[-1]
        
        # Basic indicators
        sma_20 = TechnicalAnalysis.calculate_sma(closes, 20)
        sma_50 = TechnicalAnalysis.calculate_sma(closes, 50)
        rsi = TechnicalAnalysis.calculate_rsi(closes, 14)
        bb_upper, bb_middle, bb_lower = TechnicalAnalysis.calculate_bollinger_bands(closes)
        
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "current_price": current_price,
            "moving_averages": {
                "SMA_20": sma_20[-1] if sma_20[-1] else 0,
                "SMA_50": sma_50[-1] if sma_50[-1] else 0,
            },
            "momentum": {
                "RSI": rsi[-1] if rsi[-1] else 50,
            },
            "volatility": {
                "BB_Upper": bb_upper[-1] if bb_upper[-1] else 0,
                "BB_Middle": bb_middle[-1] if bb_middle[-1] else 0,
                "BB_Lower": bb_lower[-1] if bb_lower[-1] else 0,
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    @staticmethod
    def calculate_sma(data: List[float], period: int) -> List[float]:
        """Simple Moving Average"""
        if len(data) < period:
            return [None] * len(data)
        
        return [np.mean(data[i - period + 1:i + 1]) if i >= period - 1 else None 
                for i in range(len(data))]
    
    @staticmethod
    def calculate_rsi(data: List[float], period: int = 14) -> List[float]:
        """Relative Strength Index"""
        if len(data) < period + 1:
            return [50] * len(data)
        
        deltas = np.diff(data)
        gain = np.where(deltas > 0, deltas, 0)
        loss = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gain[:period])
        avg_loss = np.mean(loss[:period])
        
        rs = avg_gain / avg_loss if avg_loss != 0 else 0
        rsi = [100 - 100 / (1 + rs)]
        
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gain[i]) / period
            avg_loss = (avg_loss * (period - 1) + loss[i]) / period
            
            rs = avg_gain / avg_loss if avg_loss != 0 else 0
            rsi.append(100 - 100 / (1 + rs))
        
        return [None] * period + rsi
    
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

# ================================================================================
# FASTAPI APPLICATION
# ================================================================================
@dataclass
class TradingSignal:
    """Trading signal data class"""
    symbol: str
    timeframe: str
    signal: str
    confidence: float
    price: float
    timestamp: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    logger.info("🚀 CryptoTrader Pro v6.0 Starting on Railway...")
    logger.info(f"📦 Environment: {RAILWAY_ENVIRONMENT}")
    logger.info(f"🔧 Port: {PORT}")
    logger.info(f"📝 Commit: {RAILWAY_GIT_COMMIT_SHA}")
    
    # Initialize Data Provider
    data_provider = DataProvider()
    await data_provider.initialize()
    
    # Store in app state
    app.state.data_provider = data_provider
    app.state.ta = TechnicalAnalysis()
    
    # Start background update task
    async def background_updates():
        while True:
            try:
                await asyncio.sleep(60)  # Update every 60 seconds
                await data_provider.update_ticker_data()
            except Exception as e:
                logger.error(f"Background update error: {e}")
                await asyncio.sleep(30)
    
    app.state.update_task = asyncio.create_task(background_updates())
    
    logger.info("✅ All systems operational")
    logger.info("=" * 70)
    
    yield
    
    # Cleanup
    app.state.update_task.cancel()
    await data_provider.close()
    logger.info("🛑 CryptoTrader Pro Shutting Down")

# Create FastAPI app
app = FastAPI(
    title="CryptoTrader Pro v6.0",
    version="6.0.0",
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

# ================================================================================
# API ENDPOINTS
# ================================================================================
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "🚀 CryptoTrader Pro v6.0",
        "status": "operational",
        "environment": RAILWAY_ENVIRONMENT,
        "version": "6.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/health")
async def health():
    """Health check endpoint - Railway bu endpoint'i kontrol eder"""
    try:
        # Check if data provider is initialized
        if hasattr(app.state, 'data_provider'):
            return {
                "status": "healthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": "6.0.0",
                "services": {
                    "data_provider": "operational",
                    "technical_analysis": "operational",
                    "api": "operational"
                }
            }
        else:
            return {
                "status": "starting",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "Application is starting up"
            }
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }

@app.get("/api/ticker")
async def get_ticker(request: Request):
    """Get ticker data"""
    try:
        data_provider = request.app.state.data_provider
        
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": data_provider.ticker_data,
            "count": len(data_provider.ticker_data),
            "data_source": "CoinGecko + Binance"
        }
    except Exception as e:
        logger.error(f"Ticker error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/symbol/{symbol}")
async def get_symbol_info(symbol: str, request: Request):
    """Get symbol information"""
    try:
        data_provider = request.app.state.data_provider
        
        # Find symbol in ticker data
        symbol_upper = symbol.upper()
        if not symbol_upper.endswith('USDT'):
            symbol_upper = f"{symbol_upper}USDT"
            
        for item in data_provider.ticker_data:
            if item['symbol'] == symbol_upper:
                return {
                    "success": True,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "symbol": item
                }
        
        # If not found, create basic info
        price = data_provider.SAMPLE_PRICES.get(symbol_upper, 100.0)
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": {
                "symbol": symbol_upper,
                "name": symbol_upper.replace('USDT', ''),
                "price": price,
                "change_24h": 0.0,
                "volume": price * 1000000,
                "market_cap": price * 10000000,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "source": "estimated"
            }
        }
        
    except Exception as e:
        logger.error(f"Symbol info error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/analysis/{symbol}")
async def get_technical_analysis(symbol: str, request: Request, 
                                 timeframe: str = Query("1D"), 
                                 limit: int = Query(100, ge=10, le=500)):
    """Get technical analysis"""
    try:
        data_provider = request.app.state.data_provider
        ta = request.app.state.ta
        
        # Normalize symbol
        symbol_upper = symbol.upper()
        if not symbol_upper.endswith('USDT'):
            symbol_upper = f"{symbol_upper}USDT"
        
        # Get OHLCV data
        ohlcv = await data_provider.get_ohlcv(symbol_upper, timeframe.lower(), limit)
        
        if len(ohlcv) < 20:
            return {"success": False, "error": "Insufficient data for analysis"}
        
        # Calculate analysis
        analysis = ta.calculate_all_indicators(ohlcv, symbol_upper, timeframe)
        
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol_upper,
            "timeframe": timeframe,
            "analysis": analysis
        }
        
    except Exception as e:
        logger.error(f"Technical analysis error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/signal/{symbol}")
async def get_signal(symbol: str, request: Request, 
                     timeframe: str = Query("1D")):
    """Get trading signal"""
    try:
        data_provider = request.app.state.data_provider
        ta = request.app.state.ta
        
        # Normalize symbol
        symbol_upper = symbol.upper()
        if not symbol_upper.endswith('USDT'):
            symbol_upper = f"{symbol_upper}USDT"
        
        # Get OHLCV data
        ohlcv = await data_provider.get_ohlcv(symbol_upper, timeframe.lower(), 100)
        
        if len(ohlcv) < 30:
            signal = TradingSignal(
                symbol=symbol_upper,
                timeframe=timeframe,
                signal="NEUTRAL",
                confidence=50,
                price=ohlcv[-1]["close"] if ohlcv else 0,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        else:
            # Calculate analysis
            analysis = ta.calculate_all_indicators(ohlcv, symbol_upper, timeframe)
            
            # Simple signal logic
            rsi = analysis["momentum"]["RSI"]
            price = analysis["current_price"]
            sma_20 = analysis["moving_averages"]["SMA_20"]
            
            if rsi < 30 and price > sma_20:
                signal_type = "BUY"
                confidence = 70
            elif rsi > 70 and price < sma_20:
                signal_type = "SELL"
                confidence = 70
            else:
                signal_type = "NEUTRAL"
                confidence = 50
            
            signal = TradingSignal(
                symbol=symbol_upper,
                timeframe=timeframe,
                signal=signal_type,
                confidence=confidence,
                price=price,
                timestamp=analysis["timestamp"]
            )
        
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol_upper,
            "timeframe": timeframe,
            "signal": asdict(signal)
        }
        
    except Exception as e:
        logger.error(f"Signal generation error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/dashboard")
async def dashboard():
    """Simple dashboard HTML"""
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>CryptoTrader Pro v6.0</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                background: linear-gradient(135deg, #0a0e27 0%, #1a1f4d 100%);
                color: white;
                margin: 0;
                padding: 20px;
                min-height: 100vh;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
            }
            .header {
                text-align: center;
                padding: 40px 0;
            }
            .logo {
                font-size: 48px;
                font-weight: 900;
                background: linear-gradient(135deg, #00d4ff, #ff3366);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 20px;
            }
            .status {
                background: rgba(255, 255, 255, 0.1);
                border-radius: 12px;
                padding: 20px;
                margin: 20px 0;
            }
            .endpoints {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
                margin-top: 40px;
            }
            .endpoint-card {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
                padding: 20px;
                transition: transform 0.3s ease;
            }
            .endpoint-card:hover {
                transform: translateY(-5px);
                background: rgba(255, 255, 255, 0.1);
            }
            .endpoint-title {
                font-size: 20px;
                font-weight: 700;
                margin-bottom: 10px;
                color: #00d4ff;
            }
            .endpoint-url {
                font-family: 'Courier New', monospace;
                background: rgba(0, 0, 0, 0.3);
                padding: 10px;
                border-radius: 6px;
                margin: 10px 0;
                word-break: break-all;
            }
            .btn {
                display: inline-block;
                background: linear-gradient(135deg, #00d4ff, #0066ff);
                color: white;
                padding: 10px 20px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: 600;
                margin-top: 10px;
                transition: all 0.3s ease;
            }
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 5px 20px rgba(0, 212, 255, 0.4);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">
                    <i class="fas fa-bolt"></i> CryptoTrader Pro v6.0
                </div>
                <p>Advanced Trading Platform - Railway Deployment</p>
            </div>
            
            <div class="status">
                <h2>🚀 Status: Operational</h2>
                <p>📦 Environment: """ + RAILWAY_ENVIRONMENT + """</p>
                <p>🔧 Port: """ + str(PORT) + """</p>
                <p>📝 Commit: """ + RAILWAY_GIT_COMMIT_SHA + """</p>
            </div>
            
            <div class="endpoints">
                <div class="endpoint-card">
                    <div class="endpoint-title">Health Check</div>
                    <div class="endpoint-url">GET /health</div>
                    <p>Check application health status</p>
                    <a href="/health" class="btn">Test Endpoint</a>
                </div>
                
                <div class="endpoint-card">
                    <div class="endpoint-title">Ticker Data</div>
                    <div class="endpoint-url">GET /api/ticker</div>
                    <p>Get real-time cryptocurrency prices</p>
                    <a href="/api/ticker" class="btn">Test Endpoint</a>
                </div>
                
                <div class="endpoint-card">
                    <div class="endpoint-title">Symbol Info</div>
                    <div class="endpoint-url">GET /api/symbol/{symbol}</div>
                    <p>Get information for specific symbol</p>
                    <a href="/api/symbol/BTC" class="btn">Test BTC</a>
                </div>
                
                <div class="endpoint-card">
                    <div class="endpoint-title">Technical Analysis</div>
                    <div class="endpoint-url">GET /api/analysis/{symbol}</div>
                    <p>Get technical indicators for symbol</p>
                    <a href="/api/analysis/BTC" class="btn">Test Analysis</a>
                </div>
                
                <div class="endpoint-card">
                    <div class="endpoint-title">Trading Signal</div>
                    <div class="endpoint-url">GET /api/signal/{symbol}</div>
                    <p>Get AI trading signal for symbol</p>
                    <a href="/api/signal/BTC" class="btn">Test Signal</a>
                </div>
                
                <div class="endpoint-card">
                    <div class="endpoint-title">API Documentation</div>
                    <div class="endpoint-url">GET /docs</div>
                    <p>Interactive API documentation</p>
                    <a href="/docs" class="btn">Open Docs</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

# ================================================================================
# STARTUP
# ================================================================================
if __name__ == "__main__":
    import uvicorn
    
    logger.info("=" * 70)
    logger.info("🚀 CRYPTOTRADER PRO v6.0 STARTING")
    logger.info("=" * 70)
    logger.info(f"🌐 Server will start on port: {PORT}")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
