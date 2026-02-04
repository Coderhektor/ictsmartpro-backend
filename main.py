
"""
ICTSmartPro Real-Time Price Tracker v2.0 - PURE REAL-TIME
✅ Sadece gerçek zamanlı veri ✅ Sıfır simülasyon
✅ TradingView WebSocket entegrasyonu ✅ Minimal bellek kullanımı
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Deque
from collections import deque
import json
import asyncio
import aiohttp
import websockets
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

# ==================== WEBSOCKET CLIENT FOR REAL DATA ====================
class BinanceWebSocketClient:
    """Binance WebSocket'ten gerçek zamanlı veri alır"""
    
    def __init__(self):
        self.ws = None
        self.connected = False
        self.symbol_data = {}
        self.subscribed_symbols = set()
        
    async def connect(self, symbols: List[str]):
        """Binance WebSocket'ine bağlan"""
        try:
            # Binance WebSocket URL
            stream_names = [f"{symbol.lower()}@ticker" for symbol in symbols]
            streams = "/".join(stream_names)
            ws_url = f"wss://stream.binance.com:9443/stream?streams={streams}"
            
            logger.info(f"Connecting to Binance WebSocket: {ws_url}")
            
            async with websockets.connect(ws_url) as websocket:
                self.ws = websocket
                self.connected = True
                logger.info(f"✅ Connected to Binance WebSocket for {len(symbols)} symbols")
                
                # WebSocket mesajlarını dinle
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        await self.process_message(data)
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON decode error: {e}")
                    except Exception as e:
                        logger.error(f"Message processing error: {e}")
                        
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            self.connected = False
            raise
            
    async def process_message(self, data: Dict):
        """WebSocket mesajını işle"""
        try:
            if 'data' in data:
                stream_data = data['data']
                symbol = stream_data['s']  # Örnek: BTCUSDT
                
                # Güncel fiyat verisini kaydet
                self.symbol_data[symbol] = {
                    'symbol': symbol,
                    'price': float(stream_data.get('c', 0)),  # Son fiyat
                    'change': float(stream_data.get('P', 0)),  # Yüzde değişim
                    'volume': float(stream_data.get('v', 0)),  # Hacim
                    'high': float(stream_data.get('h', 0)),    # 24s yüksek
                    'low': float(stream_data.get('l', 0)),     # 24s düşük
                    'open': float(stream_data.get('o', 0)),    # 24s açılış
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'last_update': datetime.now(timezone.utc)
                }
                
                # Her 10. mesajda log
                if len(self.symbol_data) % 10 == 0:
                    logger.debug(f"📡 {symbol}: ${self.symbol_data[symbol]['price']}")
                    
        except Exception as e:
            logger.error(f"Message processing error: {e}")
            
    async def get_symbol_data(self, symbol: str) -> Optional[Dict]:
        """Sembol verisini getir"""
        return self.symbol_data.get(symbol.upper())
        
    async def get_all_symbols_data(self) -> Dict:
        """Tüm sembol verilerini getir"""
        return self.symbol_data.copy()

# ==================== PRICE TRACKER (Real Data Only) ====================
class RealTimePriceTracker:
    """Sadece gerçek veriyi kullanır, hiç simülasyon yok"""
    
    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self.current_data = None
        self.candle_cache = deque(maxlen=50)  # Son 50 mum
        self.levels_cache = None
        self.last_calculated = None
        
    def update_from_websocket(self, ws_data: Dict):
        """WebSocket verisi ile güncelle"""
        try:
            if not ws_data:
                return
                
            self.current_data = {
                'symbol': self.symbol,
                'price': ws_data.get('price', 0),
                'change_percent': ws_data.get('change', 0),
                'volume': ws_data.get('volume', 0),
                'high_24h': ws_data.get('high', 0),
                'low_24h': ws_data.get('low', 0),
                'open_24h': ws_data.get('open', 0),
                'timestamp': ws_data.get('timestamp'),
                'last_update': datetime.now(timezone.utc)
            }
            
            # Yeni mum ekle (basit zaman bazlı)
            now = datetime.now(timezone.utc)
            if not self.candle_cache or (now - self.candle_cache[-1]['timestamp']).seconds >= 60:
                new_candle = {
                    'timestamp': now,
                    'open': ws_data.get('price', 0),
                    'high': ws_data.get('price', 0),
                    'low': ws_data.get('price', 0),
                    'close': ws_data.get('price', 0),
                    'volume': ws_data.get('volume', 0),
                    'is_final': False
                }
                self.candle_cache.append(new_candle)
                
        except Exception as e:
            logger.error(f"Update error for {self.symbol}: {e}")
            
    def get_statistics(self) -> Dict:
        """İstatistikleri hesapla"""
        if not self.current_data:
            return {
                'symbol': self.symbol,
                'status': 'waiting_for_data',
                'message': 'Gerçek zamanlı veri bekleniyor...'
            }
            
        return {
            'symbol': self.symbol,
            'current_price': round(self.current_data['price'], 4),
            'price_change_percent': round(self.current_data['change_percent'], 2),
            'volume_24h': round(self.current_data['volume'], 2),
            'high_24h': round(self.current_data['high_24h'], 4),
            'low_24h': round(self.current_data['low_24h'], 4),
            'open_24h': round(self.current_data['open_24h'], 4),
            'last_update': self.current_data['last_update'].isoformat(),
            'candle_count': len(self.candle_cache),
            'status': 'live'
        }
        
    def calculate_levels(self) -> Dict:
        """Destek/direnç seviyelerini hesapla (gerçek veri ile)"""
        if len(self.candle_cache) < 10:
            return {
                "supports": [],
                "resistances": [],
                "ready": False,
                "message": f"{len(self.candle_cache)}/10 mum gerekiyor",
                "calculated_at": datetime.now(timezone.utc).isoformat()
            }
            
        try:
            # Gerçek fiyat verileri
            closes = [c['close'] for c in self.candle_cache]
            highs = [c['high'] for c in self.candle_cache]
            lows = [c['low'] for c in self.candle_cache]
            
            # Basit destek/direnç hesaplama
            current_price = self.current_data['price'] if self.current_data else closes[-1]
            
            # Pivot Point (klasik hesaplama)
            recent_high = max(highs[-5:]) if len(highs) >= 5 else highs[-1]
            recent_low = min(lows[-5:]) if len(lows) >= 5 else lows[-1]
            recent_close = closes[-1]
            
            pivot = (recent_high + recent_low + recent_close) / 3
            
            # Seviyeler
            r1 = 2 * pivot - recent_low
            r2 = pivot + (recent_high - recent_low)
            s1 = 2 * pivot - recent_high
            s2 = pivot - (recent_high - recent_low)
            
            # Mevcut fiyata göre filtrele
            resistances = sorted([r for r in [r1, r2] if r > current_price], reverse=True)[:3]
            supports = sorted([s for s in [s1, s2] if s < current_price])[:3]
            
            self.levels_cache = {
                "supports": [round(s, 4) for s in supports],
                "resistances": [round(r, 4) for r in resistances],
                "pivot": round(pivot, 4),
                "current_price": round(current_price, 4),
                "ready": True,
                "calculated_at": datetime.now(timezone.utc).isoformat()
            }
            self.last_calculated = datetime.now(timezone.utc)
            
            return self.levels_cache
            
        except Exception as e:
            logger.error(f"Level calculation error for {self.symbol}: {e}")
            return {
                "supports": [],
                "resistances": [],
                "ready": False,
                "error": str(e),
                "calculated_at": datetime.now(timezone.utc).isoformat()
            }

# ==================== GLOBAL MANAGER ====================
class RealTimeTrackerManager:
    """Gerçek zamanlı veri yöneticisi"""
    
    def __init__(self):
        self.trackers = {}
        self.ws_client = BinanceWebSocketClient()
        self.symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
        self.is_running = False
        
        # Tracker'ları oluştur
        for symbol in self.symbols:
            self.trackers[symbol] = RealTimePriceTracker(symbol)
            
        logger.info(f"✅ {len(self.symbols)} sembol için gerçek zamanlı tracker oluşturuldu")
        
    async def start_real_time_updates(self):
        """Gerçek zamanlı veri akışını başlat"""
        if self.is_running:
            return
            
        self.is_running = True
        
        # Binance WebSocket'e bağlan
        try:
            # WebSocket bağlantısını arka planda çalıştır
            asyncio.create_task(self.ws_client.connect(self.symbols))
            
            # Veri güncelleme döngüsü
            while self.is_running:
                try:
                    # Tüm sembolleri güncelle
                    for symbol in self.symbols:
                        ws_data = await self.ws_client.get_symbol_data(symbol)
                        if ws_data:
                            self.trackers[symbol].update_from_websocket(ws_data)
                    
                    # Her 5 saniyede bir güncelle
                    await asyncio.sleep(5)
                    
                except Exception as e:
                    logger.error(f"Update loop error: {e}")
                    await asyncio.sleep(10)
                    
        except Exception as e:
            logger.error(f"Real-time updates failed: {e}")
            self.is_running = False
            
    async def stop_real_time_updates(self):
        """Gerçek zamanlı güncellemeyi durdur"""
        self.is_running = False
        
    def get_symbol_data(self, symbol: str) -> Optional[Dict]:
        """Sembol verisini getir"""
        symbol = symbol.upper()
        if symbol not in self.trackers:
            return None
            
        tracker = self.trackers[symbol]
        
        # WebSocket bağlantı durumu
        ws_connected = self.ws_client.connected
        ws_data = None
        
        return {
            "symbol": symbol,
            "statistics": tracker.get_statistics(),
            "levels": tracker.calculate_levels(),
            "connection": {
                "websocket_connected": ws_connected,
                "data_received": tracker.current_data is not None,
                "last_update": tracker.current_data['last_update'].isoformat() if tracker.current_data else None
            },
            "status": "live" if tracker.current_data else "waiting"
        }
        
    def get_all_symbols_data(self) -> Dict:
        """Tüm sembollerin verisini getir"""
        result = {}
        for symbol in self.symbols:
            result[symbol] = self.get_symbol_data(symbol)
        return result

# ==================== FASTAPI APP LIFECYCLE ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama ömrünü yönet"""
    # Başlangıç
    logger.info("🚀 ICTSmartPro Real-Time Tracker v2.0 starting...")
    
    # Global manager oluştur
    app.state.tracker_manager = RealTimeTrackerManager()
    
    # Gerçek zamanlı güncellemeleri başlat
    asyncio.create_task(app.state.tracker_manager.start_real_time_updates())
    
    yield
    
    # Kapanış
    logger.info("🛑 ICTSmartPro Real-Time Tracker shutting down...")
    await app.state.tracker_manager.stop_real_time_updates()

# FastAPI uygulaması
app = FastAPI(
    title="ICTSmartPro Real-Time Price Tracker",
    version="2.0",
    docs_url=None,
    redoc_url=None,
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

# ==================== RAILWAY CRITICAL ENDPOINTS ====================
@app.get("/", response_class=HTMLResponse)
async def root():
    """Ana sayfa"""
    return """
    <html>
    <head>
        <meta http-equiv="refresh" content="0;url=/dashboard">
        <title>ICTSmartPro Tracker</title>
    </head>
    <body>
        <div style="text-align: center; margin-top: 50px;">
            <h2>ICTSmartPro Real-Time Tracker v2.0</h2>
            <p>Gerçek zamanlı fiyat takip sistemine yönlendiriliyorsunuz...</p>
            <p><a href="/dashboard">Hemen git</a></p>
        </div>
    </body>
    </html>
    """

@app.get("/health", response_class=JSONResponse)
async def health_check():
    """Railway health check"""
    manager = app.state.tracker_manager
    
    # Bağlantı durumu kontrolü
    live_trackers = 0
    for symbol in manager.symbols:
        data = manager.get_symbol_data(symbol)
        if data and data.get("status") == "live":
            live_trackers += 1
            
    return {
        "status": "healthy" if live_trackers > 0 else "starting",
        "version": "2.0",
        "service": "ICTSmartPro Real-Time Tracker",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tracked_symbols": len(manager.symbols),
        "live_symbols": live_trackers,
        "websocket_connected": manager.ws_client.connected,
        "real_time_updates": manager.is_running
    }

@app.get("/ready", response_class=PlainTextResponse)
async def ready_check():
    """Kubernetes readiness probe"""
    manager = app.state.tracker_manager
    
    # En az 2 sembol canlı veri alıyorsa hazır
    live_count = 0
    for symbol in manager.symbols:
        data = manager.get_symbol_data(symbol)
        if data and data.get("status") == "live":
            live_count += 1
            
    return "READY" if live_count >= 2 else "NOT_READY"

@app.get("/live", response_class=JSONResponse)
async def live_check():
    """Liveness probe"""
    return {
        "status": "alive",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "real-time-tracker"
    }

# ==================== API ENDPOINTS ====================
@app.get("/api/price/{symbol}")
async def get_price(symbol: str):
    """Sembolün gerçek zamanlı fiyatını getir"""
    manager = app.state.tracker_manager
    data = manager.get_symbol_data(symbol)
    
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"Sembol bulunamadı. Desteklenenler: {', '.join(manager.symbols)}"
        )
        
    return {
        "success": True,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "binance_websocket",
        "is_real_time": True
    }

@app.get("/api/price/{symbol}/levels")
async def get_levels(symbol: str):
    """Destek/direnç seviyelerini getir"""
    manager = app.state.tracker_manager
    data = manager.get_symbol_data(symbol)
    
    if not data:
        raise HTTPException(status_code=404, detail="Sembol bulunamadı")
        
    levels = data["levels"]
    
    if not levels["ready"]:
        return {
            "success": False,
            "error": "Yetersiz gerçek zamanlı veri",
            "message": levels.get("message", "Veri bekleniyor..."),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    # Seviye analizi
    current_price = levels["current_price"]
    supports = levels["supports"]
    resistances = levels["resistances"]
    
    nearest_support = min([current_price - s for s in supports]) if supports else None
    nearest_resistance = min([r - current_price for r in resistances]) if resistances else None
    
    # Analiz
    if nearest_support and nearest_support < current_price * 0.01: #  % 1'den az
        analysis = "ALIM BÖLGESİ"
        signal = "BUY"
    elif nearest_resistance and nearest_resistance < current_price * 0.01:  % 1'den az
        analysis = "SATIŞ BÖLGESİ"
        signal = "SELL"
    else:
        analysis = "NÖTR BÖLGE"
        signal = "HOLD"
        
    return {
        "success": True,
        "symbol": symbol.upper(),
        "current_price": current_price,
        "pivot_point": levels["pivot"],
        "supports": supports,
        "resistances": resistances,
        "nearest_support": round(nearest_support, 4) if nearest_support else None,
        "nearest_resistance": round(nearest_resistance, 4) if nearest_resistance else None,
        "analysis": analysis,
        "signal": signal,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "real_time_binance",
        "calculation_time": levels["calculated_at"]
    }

@app.get("/api/market/overview")
async def market_overview():
    """Piyasa genel görünümü"""
    manager = app.state.tracker_manager
    all_data = manager.get_all_symbols_data()
    
    # İstatistikler
    live_count = 0
    total_change = 0
    symbol_summary = {}
    
    for symbol, data in all_data.items():
        if data and data["statistics"]:
            stats = data["statistics"]
            
            if stats.get("status") == "live":
                live_count += 1
                total_change += stats.get("price_change_percent", 0)
                
            symbol_summary[symbol] = {
                "price": stats.get("current_price", 0),
                "change": stats.get("price_change_percent", 0),
                "volume": stats.get("volume_24h", 0),
                "status": stats.get("status", "waiting"),
                "last_update": stats.get("last_update")
            }
    
    avg_change = total_change / live_count if live_count > 0 else 0
    
    return {
        "success": True,
        "market": {
            "total_symbols": len(symbol_summary),
            "live_symbols": live_count,
            "average_change": round(avg_change, 2),
            "trend": "BULLISH" if avg_change > 0 else "BEARISH" if avg_change < 0 else "NEUTRAL",
            "websocket_status": manager.ws_client.connected,
            "update_active": manager.is_running,
            "timestamp": datetime.now(timezone.utc).isoformat()
        },
        "symbols": symbol_summary
    }

@app.get("/api/system/status")
async def system_status():
    """Sistem durumu detayları"""
    manager = app.state.tracker_manager
    
    symbol_status = {}
    for symbol in manager.symbols:
        data = manager.get_symbol_data(symbol)
        symbol_status[symbol] = {
            "status": data.get("status") if data else "unknown",
            "last_update": data.get("connection", {}).get("last_update") if data else None,
            "has_data": data.get("statistics", {}).get("current_price") is not None if data else False
        }
    
    return {
        "system": {
            "version": "2.0",
            "mode": "real_time_only",
            "simulation": False,
            "websocket": {
                "connected": manager.ws_client.connected,
                "symbols_subscribed": list(manager.symbols)
            },
            "update_service": {
                "running": manager.is_running,
                "interval_seconds": 5
            }
        },
        "symbols": symbol_status,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ==================== DASHBOARD ====================
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Ana kontrol paneli"""
    return """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ICTSmartPro Real-Time Tracker v2.0</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --primary: #3b82f6;
            --secondary: #8b5cf6;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --dark: #0f172a;
            --dark-800: #1e293b;
            --gray: #94a3b8;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: linear-gradient(135deg, var(--dark), var(--dark-800));
            color: #e2e8f0;
            min-height: 100vh;
            padding: 1rem;
        }
        
        .container { max-width: 1400px; margin: 0 auto; }
        
        header {
            text-align: center;
            padding: 2rem 1rem;
            margin-bottom: 2rem;
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            border-radius: 20px;
            box-shadow: 0 10px 30px rgba(59, 130, 246, 0.3);
        }
        
        .logo {
            font-size: 2.5rem;
            font-weight: 900;
            background: linear-gradient(45deg, #fbbf24, #f97316);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }
        
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: rgba(16, 185, 129, 0.2);
            color: var(--success);
            padding: 0.4rem 1.2rem;
            border-radius: 50px;
            margin-top: 1rem;
            font-weight: 500;
        }
        
        .card {
            background: rgba(30, 41, 59, 0.85);
            border-radius: 16px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
        
        .card-title {
            font-size: 1.4rem;
            font-weight: 700;
            color: white;
            margin-bottom: 1.2rem;
            display: flex;
            align-items: center;
            gap: 0.7rem;
        }
        
        .symbols-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
            gap: 1.2rem;
            margin-top: 1rem;
        }
        
        .symbol-card {
            background: rgba(25, 35, 60, 0.7);
            border-radius: 12px;
            padding: 1.2rem;
            cursor: pointer;
            transition: all 0.3s ease;
            border: 1px solid rgba(59, 130, 246, 0.1);
        }
        
        .symbol-card:hover {
            transform: translateY(-3px);
            border-color: var(--primary);
        }
        
        .symbol-name {
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }
        
        .symbol-price {
            font-size: 1.5rem;
            font-weight: 700;
            margin: 0.5rem 0;
        }
        
        .symbol-change {
            font-size: 0.95rem;
            font-weight: 500;
        }
        
        .positive { color: var(--success); }
        .negative { color: var(--danger); }
        
        .analysis-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1.2rem;
            margin-top: 1rem;
        }
        
        .analysis-card {
            background: rgba(25, 35, 60, 0.7);
            border-radius: 12px;
            padding: 1.2rem;
        }
        
        .analysis-title {
            color: var(--gray);
            font-size: 0.9rem;
            margin-bottom: 0.5rem;
        }
        
        .analysis-value {
            font-size: 1.4rem;
            font-weight: 700;
            color: white;
        }
        
        .support-value { color: var(--success); }
        .resistance-value { color: var(--danger); }
        
        .tradingview-container {
            width: 100%;
            height: 500px;
            border-radius: 12px;
            overflow: hidden;
            margin-top: 1.5rem;
            background: rgba(15, 23, 42, 0.6);
        }
        
        #tradingview_chart {
            width: 100%;
            height: 100%;
        }
        
        .connection-status {
            padding: 0.5rem 1rem;
            border-radius: 8px;
            font-size: 0.9rem;
            font-weight: 500;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .connected { background: rgba(16, 185, 129, 0.2); color: var(--success); }
        .disconnected { background: rgba(239, 68, 68, 0.2); color: var(--danger); }
        
        .loading {
            text-align: center;
            padding: 2rem;
            color: var(--primary);
        }
        
        .spinner {
            border: 4px solid rgba(59, 130, 246, 0.3);
            border-top: 4px solid var(--primary);
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 1rem;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        footer {
            text-align: center;
            padding: 2rem;
            color: var(--gray);
            border-top: 1px solid rgba(255, 255, 255, 0.07);
            margin-top: 2rem;
        }
        
        @media (max-width: 768px) {
            .symbols-grid {
                grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            }
            .analysis-grid {
                grid-template-columns: 1fr;
            }
            .logo {
                font-size: 2rem;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <i class="fas fa-bolt"></i> ICTSmartPro v2.0
            </div>
            <div style="color: rgba(255, 255, 255, 0.9); margin: 0.5rem 0; font-size: 1.1rem;">
                Gerçek Zamanlı Fiyat Takip - Sıfır Simülasyon
            </div>
            <div class="status-badge">
                <i class="fas fa-satellite-dish"></i> 
                <span id="statusText">Binance WebSocket Bağlanıyor...</span>
                <span id="lastUpdate" style="margin-left: 1rem; font-size: 0.9rem;"></span>
            </div>
        </header>
        
        <div class="card">
            <h2 class="card-title">
                <i class="fas fa-coins"></i> Canlı Semboller
                <div id="connectionStatus" class="connection-status disconnected">
                    <i class="fas fa-circle"></i> Bağlantı Yok
                </div>
            </h2>
            <div class="symbols-grid" id="symbolsGrid">
                <div class="loading">
                    <div class="spinner"></div>
                    <div>Binance'dan veri bekleniyor...</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2 class="card-title">
                <i class="fas fa-chart-bar"></i> Gerçek Zamanlı Analiz - <span id="selectedSymbol">BTCUSDT</span>
            </h2>
            
            <div class="analysis-grid">
                <div class="analysis-card">
                    <div class="analysis-title">Mevcut Fiyat (Gerçek Zamanlı)</div>
                    <div class="analysis-value" id="currentPrice">-</div>
                    <div style="font-size: 0.85rem; color: var(--gray); margin-top: 0.5rem;" id="priceSource"></div>
                </div>
                <div class="analysis-card">
                    <div class="analysis-title">Pivot Noktası</div>
                    <div class="analysis-value" id="pivotPoint">-</div>
                </div>
                <div class="analysis-card">
                    <div class="analysis-title">Destek Seviyeleri</div>
                    <div class="analysis-value support-value" id="supports">-</div>
                </div>
                <div class="analysis-card">
                    <div class="analysis-title">Direnç Seviyeleri</div>
                    <div class="analysis-value resistance-value" id="resistances">-</div>
                </div>
            </div>
            
            <div class="tradingview-container">
                <div id="tradingview_chart"></div>
            </div>
        </div>
        
        <footer>
            <div>© 2024 ICTSmartPro Real-Time Tracker v2.0</div>
            <div style="color: var(--success); margin-top: 0.5rem; font-size: 0.9rem;">
                <i class="fas fa-check-circle"></i> Sıfır Simülasyon - Tamamen Gerçek Veri
            </div>
            <div style="margin-top: 1rem; font-size: 0.85rem; color: var(--gray);">
                Binance WebSocket • Real-time Updates • Live Technical Analysis
            </div>
        </footer>
    </div>

    <!-- TradingView Widget -->
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <script>
        let tvWidget = null;
        let currentSymbol = "BTCUSDT";
        let connectionStatus = "disconnected";
        
        // Bağlantı durumunu güncelle
        function updateConnectionStatus(connected) {
            const statusEl = document.getElementById('connectionStatus');
            if (connected) {
                statusEl.className = 'connection-status connected';
                statusEl.innerHTML = '<i class="fas fa-circle"></i> Binance WebSocket Bağlı';
                connectionStatus = "connected";
            } else {
                statusEl.className = 'connection-status disconnected';
                statusEl.innerHTML = '<i class="fas fa-circle"></i> WebSocket Bağlantısı Yok';
                connectionStatus = "disconnected";
            }
        }
        
        // TradingView başlat
        function initTradingView(symbol = "BTCUSDT") {
            if (tvWidget) {
                tvWidget.remove();
            }
            
            let tvSymbol = symbol.toUpperCase();
            if (tvSymbol.endsWith("USDT")) {
                tvSymbol = `BINANCE:${tvSymbol.replace('USDT', 'USDT.P')}`;
            }
            
            tvWidget = new TradingView.widget({
                width: "100%",
                height: "100%",
                symbol: tvSymbol,
                interval: "1",
                timezone: "Etc/UTC",
                theme: "dark",
                style: "1",
                locale: "tr",
                toolbar_bg: "#1e293b",
                enable_publishing: false,
                allow_symbol_change: true,
                container_id: "tradingview_chart",
                studies: ["RSI@tv-basicstudies", "MASimple@tv-basicstudies"],
                overrides: {
                    "paneProperties.background": "#0f172a",
                    "paneProperties.vertGridProperties.color": "#1e293b",
                    "paneProperties.horzGridProperties.color": "#1e293b",
                    "symbolWatermarkProperties.color": "rgba(0,0,0,0)",
                    "scalesProperties.textColor": "#e2e8f0",
                    "mainSeriesProperties.candleStyle.wickUpColor": "#10b981",
                    "mainSeriesProperties.candleStyle.wickDownColor": "#ef4444"
                }
            });
        }
        
        // Sembolleri yükle
        async function loadSymbols() {
            try {
                const response = await fetch('/api/market/overview');
                const data = await response.json();
                
                if (!data.success) {
                    throw new Error('Market data failed');
                }
                
                // Bağlantı durumu
                updateConnectionStatus(data.market.websocket_status);
                
                const grid = document.getElementById('symbolsGrid');
                grid.innerHTML = '';
                
                for (const [symbol, info] of Object.entries(data.symbols)) {
                    const card = document.createElement('div');
                    card.className = 'symbol-card';
                    card.onclick = () => selectSymbol(symbol);
                    
                    const statusColor = info.status === 'live' ? '#10b981' : 
                                      info.status === 'waiting' ? '#f59e0b' : '#ef4444';
                    const statusIcon = info.status === 'live' ? '🔴' : '⏳';
                    
                    card.innerHTML = `
                        <div class="symbol-name">${symbol} ${statusIcon}</div>
                        <div class="symbol-price">$${info.price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 4})}</div>
                        <div class="symbol-change ${info.change >= 0 ? 'positive' : 'negative'}">
                            ${info.change >= 0 ? '↗' : '↘'} ${Math.abs(info.change).toFixed(2)}%
                        </div>
                        <div style="margin-top: 0.5rem; font-size: 0.85rem; color: ${statusColor}">
                            ${info.status === 'live' ? '✅ Gerçek Zamanlı' : '⏳ Veri Bekleniyor'}
                        </div>
                        ${info.last_update ? `<div style="font-size: 0.75rem; color: #94a3b8; margin-top: 0.3rem;">${new Date(info.last_update).toLocaleTimeString('tr-TR')}</div>` : ''}
                    `;
                    grid.appendChild(card);
                }
                
                // İlk canlı sembolü seç
                const liveSymbols = Object.keys(data.symbols).filter(s => data.symbols[s].status === 'live');
                if (liveSymbols.length > 0) {
                    selectSymbol(liveSymbols[0]);
                }
                
                // Status güncelle
                document.getElementById('statusText').textContent = 
                    `${data.market.live_symbols}/${data.market.total_symbols} sembol canlı`;
                document.getElementById('lastUpdate').textContent = 
                    new Date().toLocaleTimeString('tr-TR');
                
            } catch (error) {
                console.error('Symbol load error:', error);
                document.getElementById('symbolsGrid').innerHTML = `
                    <div style="grid-column: 1/-1; text-align: center; padding: 2rem; color: #ef4444;">
                        <i class="fas fa-exclamation-triangle" style="font-size: 2rem; margin-bottom: 1rem;"></i>
                        <div>Binance bağlantısı kurulamadı</div>
                        <div style="font-size: 0.9rem; color: #94a3b8; margin-top: 0.5rem;">
                            WebSocket bağlantısı bekleniyor...
                        </div>
                    </div>
                `;
                updateConnectionStatus(false);
            }
        }
        
        // Sembol seç
        async function selectSymbol(symbol) {
            currentSymbol = symbol;
            document.getElementById('selectedSymbol').textContent = symbol;
            
            // Fiyat bilgisi
            try {
                const priceRes = await fetch(`/api/price/${symbol}`);
                const priceData = await priceRes.json();
                
                if (priceData.success && priceData.data) {
                    const stats = priceData.data.statistics;
                    
                    if (stats.status === 'live') {
                        document.getElementById('currentPrice').textContent = 
                            `$${stats.current_price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 4})}`;
                        document.getElementById('priceSource').innerHTML = 
                            `<i class="fas fa-satellite-dish"></i> Binance WebSocket • ${new Date(stats.last_update).toLocaleTimeString('tr-TR')}`;
                    } else {
                        document.getElementById('currentPrice').textContent = 'Veri Bekleniyor';
                        document.getElementById('priceSource').textContent = 'Binance bağlantısı kuruluyor...';
                    }
                }
            } catch (e) {
                console.error('Price fetch error:', e);
                document.getElementById('currentPrice').textContent = 'Hata';
                document.getElementById('priceSource').textContent = 'Bağlantı hatası';
            }
            
            // Seviyeler
            try {
                const levelsRes = await fetch(`/api/price/${symbol}/levels`);
                const levelsData = await levelsRes.json();
                
                if (levelsData.success) {
                    document.getElementById('pivotPoint').textContent = 
                        `$${levelsData.pivot_point.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 4})}`;
                    document.getElementById('supports').innerHTML = 
                        levelsData.supports.map(s => `$${s.toFixed(2)}`).join('<br>');
                    document.getElementById('resistances').innerHTML = 
                        levelsData.resistances.map(r => `$${r.toFixed(2)}`).join('<br>');
                } else {
                    document.getElementById('pivotPoint').textContent = '-';
                    document.getElementById('supports').innerHTML = levelsData.message || 'Veri yok';
                    document.getElementById('resistances').innerHTML = '-';
                }
            } catch (e) {
                console.error('Levels fetch error:', e);
                document.getElementById('pivotPoint').textContent = '-';
                document.getElementById('supports').innerHTML = 'Hata';
                document.getElementById('resistances').innerHTML = 'Hata';
            }
            
            // TradingView güncelle (sadece bağlıysa)
            if (connectionStatus === "connected") {
                initTradingView(symbol);
            }
        }
        
        // Sayfa yüklendiğinde
        document.addEventListener('DOMContentLoaded', () => {
            // İlk yükleme
            loadSymbols();
            
            // Her 3 saniyede bir güncelle (gerçek zamanlı)
            setInterval(loadSymbols, 3000);
            setInterval(() => {
                if (connectionStatus === "connected") {
                    selectSymbol(currentSymbol);
                }
            }, 3000);
        });
    </script>
</body>
</html>
    """

# ==================== RAILWAY DEPLOYMENT ====================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
