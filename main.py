"""
ICT SMART PRO - VERSION 6.0
Basit ve Hatasız Sürüm
"""

import base64
import logging
import asyncio
import json
import hashlib
import os
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Dict, List, Set, Any
from collections import defaultdict

import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from openai import OpenAI

# Core modülleri
try:
    from core import (
        initialize, cleanup, single_subscribers, all_subscribers, pump_radar_subscribers,
        shared_signals, active_strong_signals, top_gainers, last_update, rt_ticker,
        get_binance_client, price_sources_status, price_pool, get_all_prices_snapshot
    )
    from utils import all_usdt_symbols
except ImportError as e:
    logging.error(f"Core modülleri import hatası: {e}")
    initialize = lambda: asyncio.sleep(0)
    cleanup = lambda: asyncio.sleep(0)
    single_subscribers = defaultdict(set)
    all_subscribers = defaultdict(set)
    pump_radar_subscribers = set()
    shared_signals = {}
    active_strong_signals = {}
    top_gainers = []
    last_update = ""
    rt_ticker = ""
    get_binance_client = lambda: None
    price_sources_status = {}
    price_pool = {}
    get_all_prices_snapshot = lambda: {}
    all_usdt_symbols = []

# OpenAI
openai_client = None
if os.getenv("OPENAI_API_KEY"):
    try:
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    except:
        pass

# Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ict_smart_pro")

# ==================== VISITOR COUNTER ====================

class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users = set()
        self.daily_stats = defaultdict(lambda: {"visits": 0, "unique": set()})
        self.page_views = defaultdict(int)

    def add_visit(self, page: str, user_id: Optional[str] = None) -> int:
        self.total_visits += 1
        self.page_views[page] += 1
        today = datetime.now().strftime("%Y-%m-%d")
        self.daily_stats[today]["visits"] += 1
        if user_id:
            self.active_users.add(user_id)
            self.daily_stats[today]["unique"].add(user_id)
        return self.total_visits

    def get_stats(self) -> Dict[str, Any]:
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = self.daily_stats.get(today, {"visits": 0, "unique": set()})
        return {
            "total_visits": self.total_visits,
            "active_users": len(self.active_users),
            "today_visits": today_stats["visits"],
            "today_unique": len(today_stats["unique"]),
            "page_views": dict(self.page_views),
            "last_updated": datetime.now().strftime("%H:%M:%S")
        }

visitor_counter = VisitorCounter()

def get_visitor_stats_html() -> str:
    stats = visitor_counter.get_stats()
    return f"""
    <div style="position:fixed;top:15px;right:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:clamp(0.8rem, 2vw, 1.2rem);z-index:1000;">
        <div>👁️ Toplam: <strong>{stats['total_visits']}</strong></div>
        <div>🔥 Bugün: <strong>{stats['today_visits']}</strong></div>
        <div>👥 Aktif: <strong>{stats['active_users']}</strong></div>
    </div>
    """

# ==================== GLOBAL STATE ====================

price_sources_subscribers = set()

# ==================== LIFESPAN ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    try:
        await initialize()
        logger.info("✅ Uygulama başlatıldı")
    except Exception as e:
        logger.error(f"❌ Başlatma hatası: {e}")
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    try:
        await cleanup()
    except Exception as e:
        logger.error(f"❌ Kapatma hatası: {e}")

# ==================== FASTAPI APP ====================

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="6.0")

# ==================== MIDDLEWARE ====================

@app.middleware("http")
async def count_visitors_middleware(request: Request, call_next):
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        ip = request.client.host or "anonymous"
        visitor_id = hashlib.md5(ip.encode()).hexdigest()[:8]
    
    page = request.url.path
    visitor_counter.add_visit(page, visitor_id)
    
    response = await call_next(request)
    
    if not request.cookies.get("visitor_id"):
        response.set_cookie(key="visitor_id", value=visitor_id, max_age=86400, httponly=True, samesite="lax")
    
    return response

# ==================== WEBSOCKET ENDPOINTS ====================

@app.websocket("/ws/price_sources")
async def websocket_price_sources(websocket: WebSocket):
    await websocket.accept()
    price_sources_subscribers.add(websocket)
    try:
        while True:
            await websocket.send_json({"sources": price_sources_status, "total_symbols": len(price_pool)})
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        price_sources_subscribers.discard(websocket)
    except Exception as e:
        logger.error(f"Price sources error: {e}")
        price_sources_subscribers.discard(websocket)

@app.websocket("/ws/signal/{pair}/{timeframe}")
async def websocket_signal(websocket: WebSocket, pair: str, timeframe: str):
    await websocket.accept()
    symbol = pair.upper().replace("/", "").replace("-", "").strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    channel = f"{symbol}:{timeframe}"
    single_subscribers[channel].add(websocket)
    
    sig = shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        await websocket.send_json(sig)
    
    try:
        while True:
            await asyncio.sleep(15)
            await websocket.send_json({"heartbeat": True})
    except WebSocketDisconnect:
        single_subscribers[channel].discard(websocket)
    except Exception as e:
        logger.error(f"Signal error: {e}")
        single_subscribers[channel].discard(websocket)

@app.websocket("/ws/all/{timeframe}")
async def websocket_all_signals(websocket: WebSocket, timeframe: str):
    supported = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
    if timeframe not in supported:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    all_subscribers[timeframe].add(websocket)
    await websocket.send_json(active_strong_signals.get(timeframe, []))
    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"ping": True})
    except WebSocketDisconnect:
        all_subscribers[timeframe].discard(websocket)
    except Exception as e:
        logger.error(f"All signals error: {e}")
        all_subscribers[timeframe].discard(websocket)

@app.websocket("/ws/pump_radar")
async def websocket_pump_radar(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    await websocket.send_json({"top_gainers": top_gainers, "last_update": last_update})
    try:
        while True:
            await asyncio.sleep(20)
            await websocket.send_json({"ping": True})
    except WebSocketDisconnect:
        pump_radar_subscribers.discard(websocket)
    except Exception as e:
        logger.error(f"Pump radar error: {e}")
        pump_radar_subscribers.discard(websocket)

# ==================== HTML PAGES ====================

@app.get("/")
async def home_page(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    visitor_stats = get_visitor_stats_html()
    
    # JavaScript kodunu ayrı string olarak oluştur
    js_code = """
    <script>
        const ws = new WebSocket((window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws/pump_radar');
        
        ws.onopen = function() {
            document.getElementById('update-info').innerHTML = '✅ Gerçek veri bağlantısı kuruldu';
        };
        
        ws.onmessage = function(event) {
            try {
                const data = JSON.parse(event.data);
                if (data.ping) return;
                
                if (data.last_update) {
                    document.getElementById('update-info').innerHTML = '🔄 Son güncelleme: ' + data.last_update;
                }
                
                const table = document.getElementById('pump-table');
                if (!data.top_gainers || data.top_gainers.length === 0) {
                    table.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 50px; color: #ffd700;">📊 Şu anda aktif pump hareketi yok</td></tr>';
                    return;
                }
                
                let html = '';
                data.top_gainers.slice(0, 15).forEach(function(coin, index) {
                    const changeClass = coin.change > 0 ? 'change-positive' : 'change-negative';
                    const changeSign = coin.change > 0 ? '+' : '';
                    
                    html += `
                        <tr>
                            <td>#${index + 1}</td>
                            <td><strong>${coin.symbol}</strong></td>
                            <td>$${formatPrice(coin.price)}</td>
                            <td class="${changeClass}">${changeSign}${coin.change.toFixed(2)}%</td>
                            <td>$${formatVolume(coin.volume || 0)}</td>
                        </tr>
                    `;
                });
                
                table.innerHTML = html;
                
            } catch (error) {
                console.error('Hata:', error);
            }
        };
        
        ws.onerror = function() {
            document.getElementById('update-info').innerHTML = '❌ Bağlantı hatası';
        };
        
        ws.onclose = function() {
            document.getElementById('update-info').innerHTML = '🔌 Bağlantı kesildi';
        };
        
        function formatPrice(price) {
            if (price >= 1000) {
                return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            } else if (price >= 1) {
                return price.toLocaleString('en-US', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
            } else {
                return price.toLocaleString('en-US', { minimumFractionDigits: 6, maximumFractionDigits: 6 });
            }
        }
        
        function formatVolume(volume) {
            if (volume >= 1000000) {
                return (volume / 1000000).toFixed(2) + 'M';
            } else if (volume >= 1000) {
                return (volume / 1000).toFixed(2) + 'K';
            } else {
                return volume.toFixed(2);
            }
        }
    </script>
    """
    
    html = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ICT SMART PRO - Ana Sayfa</title>
        <style>
            body {{
                background: linear-gradient(135deg, #0a0022, #1a0033, #000);
                color: white;
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                min-height: 100vh;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            .header {{
                text-align: center;
                padding: 40px 0;
            }}
            .title {{
                font-size: 3rem;
                background: linear-gradient(90deg, #00dbde, #fc00ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 20px;
            }}
            .update-info {{
                color: #00ffff;
                font-size: 1.2rem;
                margin: 20px 0;
                text-align: center;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 40px 0;
                background: rgba(255, 255, 255, 0.05);
                border-radius: 10px;
                overflow: hidden;
            }}
            th {{
                background: rgba(0, 219, 222, 0.2);
                padding: 15px;
                text-align: left;
                color: #00ffff;
            }}
            td {{
                padding: 12px 15px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }}
            tr:hover {{
                background: rgba(255, 255, 255, 0.08);
            }}
            .change-positive {{
                color: #00ff88;
                font-weight: bold;
            }}
            .change-negative {{
                color: #ff4444;
                font-weight: bold;
            }}
            .buttons {{
                display: flex;
                flex-direction: column;
                gap: 20px;
                max-width: 500px;
                margin: 40px auto;
            }}
            .btn {{
                display: block;
                padding: 20px;
                background: linear-gradient(45deg, #fc00ff, #00dbde);
                color: white;
                text-decoration: none;
                border-radius: 10px;
                text-align: center;
                font-size: 1.3rem;
                font-weight: bold;
                transition: transform 0.3s;
            }}
            .btn:hover {{
                transform: scale(1.05);
            }}
            .user-info {{
                position: fixed;
                top: 15px;
                left: 15px;
                background: rgba(0, 0, 0, 0.7);
                padding: 10px 20px;
                border-radius: 10px;
                color: #00ff88;
            }}
        </style>
    </head>
    <body>
        <div class="user-info">Hoş geldin, {user}</div>
        {visitor_stats}
        
        <div class="container">
            <div class="header">
                <h1 class="title">ICT SMART PRO</h1>
                <div class="update-info" id="update-info">📡 Gerçek veriler yükleniyor...</div>
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>SIRA</th>
                        <th>COİN</th>
                        <th>FİYAT</th>
                        <th>24S DEĞİŞİM</th>
                        <th>HACİM</th>
                    </tr>
                </thead>
                <tbody id="pump-table">
                    <tr>
                        <td colspan="5" style="text-align: center; padding: 50px;">
                            🔄 Pump radar verileri yükleniyor...
                        </td>
                    </tr>
                </tbody>
            </table>
            
            <div class="buttons">
                <a href="/signal" class="btn">🚀 Tek Coin Sinyal + Grafik</a>
                <a href="/signal/all" class="btn">🔥 Tüm Coinleri Tara</a>
            </div>
        </div>
        
        {js_code}
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)

@app.get("/signal")
async def signal_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    visitor_stats = get_visitor_stats_html()
    
    # JavaScript kodunu ayrı string olarak oluştur
    js_code = """
    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>
        let signalWs = null;
        let tradingViewWidget = null;
        
        const timeframeMap = {
            "1m": "1",
            "3m": "3",
            "5m": "5",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "4h": "240",
            "1d": "D",
            "1w": "W"
        };
        
        function getTradingViewSymbol() {
            let pair = document.getElementById('pair').value.trim().toUpperCase();
            if (!pair.endsWith("USDT")) {
                pair += "USDT";
            }
            return "BINANCE:" + pair;
        }
        
        function getWebSocketSymbol() {
            return document.getElementById('pair').value.trim().toUpperCase();
        }
        
        async function connectSignal() {
            const symbol = getWebSocketSymbol();
            const timeframe = document.getElementById('timeframe').value;
            const tvSymbol = getTradingViewSymbol();
            const interval = timeframeMap[timeframe] || "5";
            
            if (signalWs) {
                signalWs.close();
                signalWs = null;
            }
            
            if (tradingViewWidget) {
                tradingViewWidget.remove();
                tradingViewWidget = null;
            }
            
            tradingViewWidget = new TradingView.widget({
                width: "100%",
                height: "100%",
                symbol: tvSymbol,
                interval: interval,
                timezone: "Etc/UTC",
                theme: "dark",
                style: "1",
                locale: "tr",
                container_id: "tradingview_widget",
                studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies"]
            });
            
            tradingViewWidget.onChartReady(function() {
                document.getElementById('connection-status').innerHTML = '✅ Grafik yüklendi: ' + symbol + ' ' + timeframe.toUpperCase();
            });
            
            const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
            signalWs = new WebSocket(protocol + window.location.host + '/ws/signal/' + symbol + '/' + timeframe);
            
            signalWs.onopen = function() {
                document.getElementById('connection-status').innerHTML = '✅ ' + symbol + ' ' + timeframe.toUpperCase() + ' canlı sinyal başladı!';
            };
            
            signalWs.onmessage = function(event) {
                try {
                    if (event.data.includes('heartbeat')) return;
                    
                    const data = JSON.parse(event.data);
                    const card = document.getElementById('signal-card');
                    const text = document.getElementById('signal-text');
                    const details = document.getElementById('signal-details');
                    
                    text.innerHTML = data.signal || "⏸️ Sinyal bekleniyor...";
                    
                    details.innerHTML = `
                        <strong>${data.pair || symbol + '/USDT'}</strong><br>
                        💰 Fiyat: <strong>$${(data.current_price || 0).toLocaleString('en-US', {minimumFractionDigits: 4, maximumFractionDigits: 6})}</strong><br>
                        📊 Skor: <strong>${data.score || '?'}/100</strong> | ${data.killzone || 'Normal'}<br>
                        🕒 ${data.last_update ? 'Son: ' + data.last_update : ''}
                    `;
                    
                    if (data.signal && data.signal.includes('ALIM')) {
                        card.className = 'signal-card green';
                        text.style.color = '#00ff88';
                    } else if (data.signal && data.signal.includes('SATIM')) {
                        card.className = 'signal-card red';
                        text.style.color = '#ff4444';
                    } else {
                        card.className = 'signal-card';
                        text.style.color = '#ffd700';
                    }
                    
                } catch (error) {
                    console.error('Hata:', error);
                }
            };
            
            signalWs.onerror = function() {
                document.getElementById('connection-status').innerHTML = '❌ WebSocket hatası';
            };
            
            signalWs.onclose = function() {
                document.getElementById('connection-status').innerHTML = '🔌 Bağlantı kapandı';
            };
        }
        
        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(connectSignal, 1000);
        });
    </script>
    """
    
    html = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Tek Coin Sinyal - ICT SMART PRO</title>
        <style>
            body {{
                background: linear-gradient(135deg, #0a0022, #1a0033, #000);
                color: white;
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                min-height: 100vh;
            }}
            .container {{
                max-width: 1000px;
                margin: 0 auto;
            }}
            .header {{
                text-align: center;
                padding: 30px 0;
            }}
            .title {{
                font-size: 2.5rem;
                background: linear-gradient(90deg, #00dbde, #fc00ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 20px;
            }}
            .controls {{
                background: rgba(255, 255, 255, 0.05);
                padding: 20px;
                border-radius: 10px;
                margin: 20px 0;
                text-align: center;
            }}
            input, select, button {{
                width: 100%;
                max-width: 400px;
                padding: 12px;
                margin: 10px 0;
                border: none;
                border-radius: 8px;
                background: rgba(255, 255, 255, 0.1);
                color: white;
                font-size: 1rem;
            }}
            button {{
                background: linear-gradient(45deg, #fc00ff, #00dbde);
                font-weight: bold;
                cursor: pointer;
            }}
            button:hover {{
                opacity: 0.9;
            }}
            .signal-card {{
                background: rgba(0, 0, 0, 0.5);
                padding: 30px;
                border-radius: 10px;
                margin: 30px 0;
                text-align: center;
                border-left: 5px solid #ffd700;
            }}
            .signal-card.green {{
                border-left-color: #00ff88;
                box-shadow: 0 0 20px rgba(0, 255, 136, 0.3);
            }}
            .signal-card.red {{
                border-left-color: #ff4444;
                box-shadow: 0 0 20px rgba(255, 68, 68, 0.3);
            }}
            .signal-text {{
                font-size: 2rem;
                font-weight: bold;
                margin-bottom: 15px;
            }}
            .chart-container {{
                width: 100%;
                height: 500px;
                background: rgba(10, 0, 34, 0.8);
                border-radius: 10px;
                margin: 30px 0;
                overflow: hidden;
            }}
            .navigation {{
                text-align: center;
                margin-top: 30px;
            }}
            .nav-link {{
                color: #00dbde;
                text-decoration: none;
                margin: 0 15px;
            }}
            .nav-link:hover {{
                text-decoration: underline;
            }}
            .user-info {{
                position: fixed;
                top: 15px;
                left: 15px;
                background: rgba(0, 0, 0, 0.7);
                padding: 10px 20px;
                border-radius: 10px;
                color: #00ff88;
            }}
            .status {{
                color: #00ffff;
                text-align: center;
                margin: 10px 0;
                min-height: 24px;
            }}
        </style>
    </head>
    <body>
        <div class="user-info">Hoş geldin, {user}</div>
        {visitor_stats}
        
        <div class="container">
            <div class="header">
                <h1 class="title">📊 TEK COİN CANLI SİNYAL</h1>
            </div>
            
            <div class="controls">
                <input type="text" id="pair" placeholder="Coin (örn: BTC)" value="BTC">
                <select id="timeframe">
                    <option value="1m">1 Dakika</option>
                    <option value="3m">3 Dakika</option>
                    <option value="5m" selected>5 Dakika</option>
                    <option value="15m">15 Dakika</option>
                    <option value="30m">30 Dakika</option>
                    <option value="1h">1 Saat</option>
                    <option value="4h">4 Saat</option>
                    <option value="1d">1 Gün</option>
                    <option value="1w">1 Hafta</option>
                </select>
                <button onclick="connectSignal()">🔴 CANLI SİNYAL BAĞLANTISI KUR</button>
                <div class="status" id="connection-status">Bağlantı bekleniyor...</div>
            </div>
            
            <div id="signal-card" class="signal-card">
                <div id="signal-text" class="signal-text" style="color: #ffd700;">
                    Sinyal bağlantısı kurulmadı
                </div>
                <div id="signal-details">
                    Canlı sinyal için yukarıdaki butona tıklayın.
                </div>
            </div>
            
            <div class="chart-container">
                <div id="tradingview_widget"></div>
            </div>
            
            <div class="navigation">
                <a href="/" class="nav-link">← Ana Sayfa</a>
                <a href="/signal/all" class="nav-link">Tüm Coinler →</a>
            </div>
        </div>
        
        {js_code}
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)

@app.get("/signal/all")
async def all_signals_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    visitor_stats = get_visitor_stats_html()
    
    # JavaScript kodunu ayrı string olarak oluştur
    js_code = """
    <script>
        let allSignalsWs = null;
        
        function connectAllSignals() {
            const timeframe = document.getElementById('timeframe').value;
            document.getElementById('connection-status').innerHTML = '🔄 ' + timeframe.toUpperCase() + ' sinyalleri yükleniyor...';
            
            if (allSignalsWs) {
                allSignalsWs.close();
            }
            
            const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
            allSignalsWs = new WebSocket(protocol + window.location.host + '/ws/all/' + timeframe);
            
            allSignalsWs.onopen = function() {
                document.getElementById('connection-status').innerHTML = '✅ ' + timeframe.toUpperCase() + ' canlı sinyal akışı başladı!';
            };
            
            allSignalsWs.onmessage = function(event) {
                try {
                    if (event.data.includes('ping')) return;
                    
                    const signals = JSON.parse(event.data);
                    const table = document.getElementById('signals-table');
                    
                    if (!signals || signals.length === 0) {
                        table.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 50px; color: #ffd700;">📊 Şu anda güçlü sinyal bulunmuyor</td></tr>';
                        return;
                    }
                    
                    let html = '';
                    signals.slice(0, 50).forEach(function(signal, index) {
                        let signalClass = 'signal-neutral';
                        if (signal.signal && signal.signal.includes('ALIM')) {
                            signalClass = 'signal-buy';
                        } else if (signal.signal && signal.signal.includes('SATIM')) {
                            signalClass = 'signal-sell';
                        }
                        
                        html += `
                            <tr>
                                <td>#${index + 1}</td>
                                <td><strong>${signal.pair ? signal.pair.replace('USDT', '/USDT') : 'N/A'}</strong></td>
                                <td class="${signalClass}">${signal.signal || '⏸️ Bekle'}</td>
                                <td><strong>${signal.score || '?'}/100</strong></td>
                                <td>$${(signal.current_price || 0).toLocaleString('en-US', {minimumFractionDigits: 4, maximumFractionDigits: 6})}</td>
                                <td>${signal.killzone || 'Normal'}</td>
                                <td>${signal.last_update || ''}</td>
                            </tr>
                        `;
                    });
                    
                    table.innerHTML = html;
                    
                } catch (error) {
                    console.error('Hata:', error);
                }
            };
            
            allSignalsWs.onerror = function() {
                document.getElementById('connection-status').innerHTML = '❌ WebSocket hatası';
            };
            
            allSignalsWs.onclose = function() {
                document.getElementById('connection-status').innerHTML = '🔌 Bağlantı kapandı';
            };
        }
        
        document.addEventListener('DOMContentLoaded', function() {
            document.getElementById('timeframe').value = '5m';
            setTimeout(connectAllSignals, 500);
        });
    </script>
    """
    
    html = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Tüm Coinler - ICT SMART PRO</title>
        <style>
            body {{
                background: linear-gradient(135deg, #0a0022, #1a0033, #000);
                color: white;
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                min-height: 100vh;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            .header {{
                text-align: center;
                padding: 30px 0;
            }}
            .title {{
                font-size: 2.5rem;
                background: linear-gradient(90deg, #00dbde, #fc00ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 20px;
            }}
            .controls {{
                background: rgba(255, 255, 255, 0.05);
                padding: 20px;
                border-radius: 10px;
                margin: 20px 0;
                text-align: center;
            }}
            select {{
                padding: 12px;
                width: 200px;
                border: none;
                border-radius: 8px;
                background: rgba(255, 255, 255, 0.1);
                color: white;
                font-size: 1rem;
            }}
            .status {{
                color: #00ffff;
                text-align: center;
                margin: 15px 0;
                min-height: 24px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 30px 0;
                background: rgba(255, 255, 255, 0.05);
                border-radius: 10px;
                overflow: hidden;
            }}
            th {{
                background: rgba(0, 219, 222, 0.2);
                padding: 15px;
                text-align: left;
                color: #00ffff;
            }}
            td {{
                padding: 12px 15px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }}
            tr:hover {{
                background: rgba(255, 255, 255, 0.08);
            }}
            .signal-buy {{
                color: #00ff88;
                font-weight: bold;
            }}
            .signal-sell {{
                color: #ff4444;
                font-weight: bold;
            }}
            .signal-neutral {{
                color: #ffd700;
            }}
            .navigation {{
                text-align: center;
                margin-top: 30px;
            }}
            .nav-link {{
                color: #00dbde;
                text-decoration: none;
                margin: 0 15px;
            }}
            .nav-link:hover {{
                text-decoration: underline;
            }}
            .user-info {{
                position: fixed;
                top: 15px;
                left: 15px;
                background: rgba(0, 0, 0, 0.7);
                padding: 10px 20px;
                border-radius: 10px;
                color: #00ff88;
            }}
        </style>
    </head>
    <body>
        <div class="user-info">Hoş geldin, {user}</div>
        {visitor_stats}
        
        <div class="container">
            <div class="header">
                <h1 class="title">🔥 TÜM COİN SİNYALLERİ</h1>
            </div>
            
            <div class="controls">
                <select id="timeframe" onchange="connectAllSignals()">
                    <option value="5m">5 Dakika</option>
                    <option value="15m">15 Dakika</option>
                    <option value="1h">1 Saat</option>
                    <option value="4h">4 Saat</option>
                    <option value="1d">1 Gün</option>
                </select>
                <div class="status" id="connection-status">Zaman dilimi seçin...</div>
            </div>
            
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>COİN</th>
                            <th>SİNYAL</th>
                            <th>SKOR</th>
                            <th>FİYAT</th>
                            <th>KİLLZONE</th>
                            <th>ZAMAN</th>
                        </tr>
                    </thead>
                    <tbody id="signals-table">
                        <tr>
                            <td colspan="7" style="text-align: center; padding: 50px;">
                                📊 Zaman dilimi seçerek sinyalleri görüntüleyin...
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <div class="navigation">
                <a href="/" class="nav-link">← Ana Sayfa</a>
                <a href="/signal" class="nav-link">Tek Coin Sinyal →</a>
            </div>
        </div>
        
        {js_code}
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)

# ==================== API ENDPOINTS ====================

@app.post("/api/analyze-chart")
async def analyze_chart_endpoint(request: Request):
    try:
        body = await request.json()
        symbol = body.get("symbol", "BTC").upper()
        timeframe = body.get("timeframe", "5m")
        
        binance_client = get_binance_client()
        if not binance_client:
            return JSONResponse({"analysis": "❌ Binance bağlantısı yok", "success": False}, status_code=503)
        
        ccxt_symbol = f"{symbol}/USDT"
        interval_map = {"1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"4h","1d":"1d","1w":"1w"}
        ccxt_timeframe = interval_map.get(timeframe, "5m")
        
        klines = await binance_client.fetch_ohlcv(ccxt_symbol, timeframe=ccxt_timeframe, limit=150)
        if not klines or len(klines) < 50:
            return JSONResponse({"analysis": f"❌ Yetersiz veri: {len(klines)} mum", "success": False}, status_code=404)
        
        df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume'])
        df.iloc[:,1:] = df.iloc[:,1:].apply(pd.to_numeric, errors='coerce')
        df = df.dropna().tail(100)
        
        signal = None
        try:
            from indicators import generate_ict_signal, generate_simple_signal
            signal = generate_ict_signal(df, symbol, timeframe) or generate_simple_signal(df, symbol, timeframe)
        except Exception as e:
            logger.warning(f"Indicator hatası: {e}")
            last_price = float(df['close'].iloc[-1])
            prev_price = float(df['close'].iloc[-2])
            change = ((last_price - prev_price) / prev_price * 100) if prev_price > 0 else 0
            
            signal = {
                "pair": f"{symbol}/USDT",
                "timeframe": timeframe.upper(),
                "current_price": round(last_price, 6 if last_price < 1 else 4),
                "signal": "🚀 ALIM" if change > 0.3 else "🔥 SATIM" if change < -0.3 else "⏸️ NÖTR",
                "score": min(95, max(40, int(50 + abs(change) * 10))),
                "strength": "YÜKSEK" if abs(change) > 2 else "ORTA" if abs(change) > 1 else "ZAYIF",
                "killzone": "Normal",
                "triggers": f"Fiyat değişimi: {change:+.2f}%",
                "last_update": datetime.utcnow().strftime("%H:%M:%S UTC")
            }
        
        if not signal:
            last_price = float(df['close'].iloc[-1])
            signal = {
                "pair": f"{symbol}/USDT",
                "timeframe": timeframe.upper(),
                "current_price": round(last_price, 6 if last_price < 1 else 4),
                "signal": "⏸️ NÖTR",
                "score": 50,
                "strength": "ORTA",
                "killzone": "Normal",
                "triggers": "Yeterli veri yok",
                "last_update": datetime.utcnow().strftime("%H:%M:%S UTC")
            }
        
        analysis = f"""
🔍 <strong>{symbol}/USDT</strong> {timeframe.upper()} TEKNİK ANALİZ RAPORU

🎯 **SİNYAL**: {signal['signal']}
📊 **SKOR**: {signal['score']}/100 ({signal['strength']})
💰 **FİYAT**: ${signal['current_price']:,.6f}
🕐 **KİLLZONE**: {signal['killzone']}
🕒 **SON GÜNCELLEME**: {signal['last_update']}

🎯 **TETİKLEYENLER**:
• {signal.get('triggers', 'Veri yok')}

⚠️ **UYARI**: Bu bir yatırım tavsiyesi değildir.
"""
        
        return JSONResponse({"analysis": analysis, "signal_data": signal, "success": True})
        
    except Exception as e:
        logger.exception(f"Analiz hatası: {e}")
        return JSONResponse({"analysis": "❌ Sunucu hatası", "success": False}, status_code=500)

@app.post("/api/gpt-analyze")
async def gpt_analyze_endpoint(image_file: UploadFile = File(...)):
    if not openai_client:
        return JSONResponse({"error": "OpenAI API anahtarı yok"}, status_code=501)
    
    try:
        image_data = await image_file.read()
        image_b64 = base64.b64encode(image_data).decode('utf-8')
        
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Bu kripto grafiğini Türkçe analiz et:"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
                ]
            }],
            max_tokens=1000,
            temperature=0.3
        )
        
        return JSONResponse({"analysis": response.choices[0].message.content, "success": True})
        
    except Exception as e:
        logger.exception(f"GPT hatası: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/visitor-stats")
async def get_visitor_stats():
    return JSONResponse(visitor_counter.get_stats())

@app.get("/admin/visitor-dashboard")
async def visitor_dashboard_page(request: Request):
    user = request.cookies.get("user_email")
    if not user or "admin" not in user.lower():
        return RedirectResponse("/login")
    
    stats = visitor_counter.get_stats()
    rows = ""
    for page, views in sorted(stats['page_views'].items(), key=lambda x: x[1], reverse=True):
        rows += f"<tr><td>{page}</td><td><strong>{views}</strong></td></tr>"
    
    html = f"""
    <!DOCTYPE html><html><head><meta charset="utf-8"><title>Admin Panel</title>
    <style>body{{background:#000;color:#fff;padding:20px;font-family:sans-serif}}
    .card{{background:#00000088;padding:25px;border-radius:20px;margin:15px 0}}
    table{{width:100%;border-collapse:collapse}}th,td{{padding:12px;border-bottom:1px solid #333}}</style></head><body>
    {get_visitor_stats_html()}
    <div class="card"><h2>📊 İstatistikler</h2>
    Toplam: <strong>{stats['total_visits']:,}</strong> | Bugün: <strong>{stats['today_visits']:,}</strong> | Aktif: <strong>{stats['active_users']}</strong>
    </div>
    <div class="card"><h3>Sayfa Görüntülenmeleri</h3><table><tr><th>Sayfa</th><th>Görüntülenme</th></tr>{rows}</table></div>
    <a href="/" style="color:#00dbde">← Ana Sayfa</a></body></html>
    """
    
    return HTMLResponse(content=html)

@app.get("/login")
async def login_page():
    html = """
    <!DOCTYPE html><html><head><meta charset="utf-8"><title>Giriş</title>
    <style>body{{background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
    .box{{background:#000000aa;padding:40px;border-radius:20px;text-align:center;max-width:400px;width:90%}}
    input{{width:100%;padding:12px;margin:8px;border:none;border-radius:8px;background:#333;color:#fff}}
    button{{width:100%;padding:12px;background:linear-gradient(45deg,#00dbde,#fc00ff);border:none;border-radius:8px;color:#fff;font-weight:bold}}</style></head><body>
    <div class="box"><h2>🔐 ICT SMART PRO</h2>
    <form method="post"><input name="email" placeholder="E-posta" required><button type="submit">Giriş Yap</button></form>
    <p style="color:#888;margin-top:15px">Herhangi bir e-posta ile giriş yapabilirsiniz (demo)</p></div></body></html>
    """
    return HTMLResponse(content=html)

@app.post("/login")
async def login_user(request: Request):
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    if "@" in email and "." in email:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("user_email", email, max_age=2592000, httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login")

@app.get("/debug/sources")
async def debug_sources_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    js_code = """
    <script>
        const ws = new WebSocket((window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws/price_sources');
        
        ws.onmessage = function(event) {
            try {
                const data = JSON.parse(event.data);
                document.getElementById('total').innerText = '📈 Toplam ' + data.total_symbols.toLocaleString() + ' coin aktif';
                
                const table = document.getElementById('sources-table');
                let html = '';
                
                for (const [sourceName, sourceData] of Object.entries(data.sources)) {
                    const status = sourceData.healthy ? '✅ SAĞLIKLI' : '❌ HATA';
                    const bg = sourceData.healthy ? '#00ff8822' : '#ff444422';
                    
                    html += `
                        <tr style="background: ${bg}">
                            <td><strong>${sourceName.toUpperCase()}</strong></td>
                            <td>${status}</td>
                            <td>${sourceData.last_update || 'Asla'}</td>
                            <td><strong>${sourceData.symbols_count || 0}</strong></td>
                        </tr>
                    `;
                }
                
                table.innerHTML = html;
                
            } catch (error) {
                console.error('Hata:', error);
            }
        };
    </script>
    """
    
    html = f"""
    <!DOCTYPE html><html><head><meta charset="utf-8"><title>Fiyat Kaynakları Debug</title>
    <style>body{{background:#000;color:#fff;padding:20px;font-family:sans-serif}}
    table{{width:100%;border-collapse:collapse}}th,td{{padding:12px;text-align:left;border-bottom:1px solid #333}}th{{background:#00dbde22}}</style></head><body>
    {get_visitor_stats_html()}
    <h2>🟢 Fiyat Kaynakları</h2>
    <p id="total" style="font-size:1.2rem;color:#00ff88">Yükleniyor...</p>
    <table><thead><tr><th>KAYNAK</th><th>DURUM</th><th>SON GÜNCELLEME</th><th>COIN SAYISI</th></tr></thead><tbody id="sources-table">
    <tr><td colspan="4" style="text-align:center;padding:40px;">🔄 Veriler yükleniyor...</td></tr></tbody></table>
    {js_code}
    <a href="/" style="color:#00dbde;font-size:1.1rem;margin-top:20px;display:inline-block">← Ana Sayfa</a>
    </body></html>
    """
    return HTMLResponse(content=html)

@app.get("/health")
async def health_check_endpoint():
    stats = visitor_counter.get_stats()
    healthy_sources = 0
    if price_sources_status:
        healthy_sources = sum(1 for v in price_sources_status.values() if v.get("healthy", False))
    
    return {
        "status": "OK",
        "version": "6.0-REALTIME",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "binance_connected": get_binance_client() is not None,
            "price_sources_healthy": healthy_sources,
            "price_sources_total": len(price_sources_status),
            "symbols_loaded": len(all_usdt_symbols),
        },
        "visitor_stats": stats
    }

# ==================== APPLICATION START ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)), log_level="info")
