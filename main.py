"""
ICT SMART PRO - VERSION 7.0
Production Optimized - Fixed & Enhanced
"""

import base64
import logging
import asyncio
import json
import hashlib
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional, Dict, List, Set, Any
from collections import defaultdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from openai import OpenAI

# Configure logging for production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logging.getLogger("core").setLevel(logging.WARNING)
logging.getLogger("grok_indicators").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

logger = logging.getLogger("ict_smart_pro")

# Core modülleri - Import with error handling
try:
    from core import (
        initialize, cleanup, single_subscribers, all_subscribers, pump_radar_subscribers,
        shared_signals, active_strong_signals, top_gainers, last_update, rt_ticker,
        get_binance_client, price_sources_status, price_pool, get_all_prices_snapshot
    )
    from utils import all_usdt_symbols
    logger.info("✅ Core modülleri başarıyla yüklendi")
except ImportError as e:
    logger.warning(f"⚠️ Core modülleri import hatası: {e}")
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
        logger.info("✅ OpenAI client başlatıldı")
    except Exception as e:
        logger.warning(f"⚠️ OpenAI başlatma hatası: {e}")

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
        top_pages = sorted(self.page_views.items(), key=lambda x: x[1], reverse=True)[:5]
        return {
            "total_visits": self.total_visits,
            "active_users": len(self.active_users),
            "today_visits": today_stats["visits"],
            "today_unique": len(today_stats["unique"]),
            "top_pages": dict(top_pages),
            "last_updated": datetime.now().strftime("%H:%M:%S")
        }

visitor_counter = VisitorCounter()

def get_visitor_stats_html() -> str:
    stats = visitor_counter.get_stats()
    return f"""
    <div style="position:fixed;top:15px;right:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:clamp(0.8rem, 2vw, 1.2rem);z-index:1000;backdrop-filter:blur(10px);border:1px solid #00ff8844;">
        <div>👁️ Toplam: <strong>{stats['total_visits']}</strong></div>
        <div>🔥 Bugün: <strong>{stats['today_visits']}</strong></div>
        <div>👥 Aktif: <strong>{stats['active_users']}</strong></div>
    </div>
    """

# ==================== GLOBAL STATE ====================

price_sources_subscribers = set()
signal_history = defaultdict(list)

# ==================== TEKNİK ANALİZ FONKSİYONLARI ====================

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    try:
        deltas = prices.diff()
        gain = (deltas.where(deltas > 0, 0)).rolling(window=period).mean()
        loss = (-deltas.where(deltas < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50
    except:
        return 50

def calculate_macd(prices, fast=12, slow=26, signal=9):
    if len(prices) < slow + signal:
        return {"trend": "NÖTR"}
    try:
        exp1 = prices.ewm(span=fast, adjust=False).mean()
        exp2 = prices.ewm(span=slow, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        hist_value = histogram.iloc[-1]
        if hist_value > 0:
            return {"trend": "YÜKSELİŞ"}
        elif hist_value < 0:
            return {"trend": "DÜŞÜŞ"}
        else:
            return {"trend": "NÖTR"}
    except:
        return {"trend": "NÖTR"}

def generate_technical_analysis(df, symbol, timeframe):
    if len(df) < 20:
        return None
    try:
        current_price = float(df['close'].iloc[-1])
        prev_price = float(df['close'].iloc[-2])
        change_pct = ((current_price - prev_price) / prev_price * 100) if prev_price > 0 else 0
        rsi_value = calculate_rsi(df['close'])
        macd_data = calculate_macd(df['close'])
        ma20 = df['close'].rolling(window=20).mean().iloc[-1] if len(df) >= 20 else current_price
        ma50 = df['close'].rolling(window=50).mean().iloc[-1] if len(df) >= 50 else current_price

        if current_price > ma20 > ma50:
            trend_strength = "GÜÇLÜ YÜKSELİŞ"
            trend_score = 80
        elif current_price < ma20 < ma50:
            trend_strength = "GÜÇLÜ DÜŞÜŞ"
            trend_score = 20
        elif current_price > ma20 and ma20 > ma50:
            trend_strength = "YÜKSELİŞ"
            trend_score = 70
        elif current_price < ma20 and ma20 < ma50:
            trend_strength = "DÜŞÜŞ"
            trend_score = 30
        else:
            trend_strength = "YATAY"
            trend_score = 50

        score = trend_score
        if rsi_value > 70:
            score -= 15
        elif rsi_value < 30:
            score += 15
        if macd_data['trend'] == "YÜKSELİŞ":
            score += 10
        elif macd_data['trend'] == "DÜŞÜŞ":
            score -= 10

        score = max(10, min(95, score))

        if score >= 70:
            signal_type = "🚀 GÜÇLÜ ALIM"
            color = "green"
        elif score >= 60:
            signal_type = "📈 ALIM"
            color = "lightgreen"
        elif score <= 30:
            signal_type = "🔥 GÜÇLÜ SATIM"
            color = "red"
        elif score <= 40:
            signal_type = "📉 SATIM"
            color = "lightcoral"
        else:
            signal_type = "⏸️ NÖTR"
            color = "gold"

        now_utc = datetime.utcnow()
        hour = now_utc.hour
        if 7 <= hour < 11:
            killzone = "LONDRA"
        elif 12 <= hour < 16:
            killzone = "NEW YORK"
        elif 22 <= hour or hour < 2:
            killzone = "ASYA"
        else:
            killzone = "NORMAL"

        result = {
            "pair": f"{symbol}/USDT",
            "timeframe": timeframe.upper(),
            "current_price": round(current_price, 6 if current_price < 1 else 4),
            "signal": signal_type,
            "score": int(score),
            "strength": "YÜKSEK" if score >= 70 or score <= 30 else "ORTA" if score >= 60 or score <= 40 else "DÜŞÜK",
            "color": color,
            "killzone": killzone,
            "change_24h": round(change_pct, 2),
            "rsi": round(rsi_value, 1),
            "macd_trend": macd_data['trend'],
            "trend": trend_strength,
            "ma20": round(ma20, 6 if ma20 < 1 else 4),
            "ma50": round(ma50, 6 if ma50 < 1 else 4),
            "analysis_time": now_utc.strftime("%H:%M:%S UTC"),
            "timestamp": datetime.now().isoformat()
        }

        signal_key = f"{symbol}:{timeframe}"
        signal_history[signal_key].append(result)
        if len(signal_history[signal_key]) > 5:
            signal_history[signal_key] = signal_history[signal_key][-5:]

        return result
    except Exception as e:
        logger.error(f"Teknik analiz hatası: {e}")
        return None

# ==================== LIFESPAN ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 ICT SMART PRO başlatılıyor...")
    try:
        await initialize()
        logger.info("✅ Uygulama başarıyla başlatıldı")
    except Exception as e:
        logger.error(f"❌ Başlatma hatası: {e}")
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    try:
        await cleanup()
    except Exception as e:
        logger.error(f"❌ Kapatma hatası: {e}")

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="7.0", docs_url="/api/docs", redoc_url="/api/redoc")

# ==================== MIDDLEWARE ====================

@app.middleware("http")
async def count_visitors_middleware(request: Request, call_next):
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        ip = request.client.host or "anonymous"
        visitor_id = hashlib.md5(f"{ip}{datetime.now().strftime('%Y%m%d')}".encode()).hexdigest()[:12]
    page = request.url.path
    visitor_counter.add_visit(page, visitor_id)
    response = await call_next(request)
    if not request.cookies.get("visitor_id"):
        response.set_cookie(key="visitor_id", value=visitor_id, max_age=86400*30, httponly=True, samesite="lax", secure=request.url.scheme == "https")
    return response

# ==================== WEBSOCKET ENDPOINTS ====================

# (WebSocket endpoint'leri aynı kaldı, değişmedi)

@app.websocket("/ws/price_sources")
async def websocket_price_sources(websocket: WebSocket):
    await websocket.accept()
    price_sources_subscribers.add(websocket)
    try:
        while True:
            await websocket.send_json({"sources": price_sources_status, "total_symbols": len(price_pool), "timestamp": datetime.now().isoformat()})
            await asyncio.sleep(10)
    except:
        pass
    finally:
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
            await asyncio.sleep(30)
            await websocket.send_json({"heartbeat": True, "timestamp": datetime.now().isoformat()})
    except:
        pass
    finally:
        single_subscribers[channel].discard(websocket)

@app.websocket("/ws/all/{timeframe}")
async def websocket_all_signals(websocket: WebSocket, timeframe: str):
    supported = ["1m","3m","5m","15m","30m","1h","4h","1d","1W","1M"]
    if timeframe not in supported:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    all_subscribers[timeframe].add(websocket)
    initial_signals = active_strong_signals.get(timeframe, [])[:50]  # 50'ye çıkardık
    await websocket.send_json(initial_signals)
    try:
        while True:
            await asyncio.sleep(60)
            await websocket.send_json({"ping": True, "timestamp": datetime.now().isoformat()})
    except:
        pass
    finally:
        all_subscribers[timeframe].discard(websocket)

@app.websocket("/ws/pump_radar")
async def websocket_pump_radar(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    await websocket.send_json({"top_gainers": top_gainers[:10], "last_update": last_update, "total_coins": len(top_gainers)})
    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"ping": True, "timestamp": datetime.now().isoformat()})
    except:
        pass
    finally:
        pump_radar_subscribers.discard(websocket)

# ==================== HTML PAGES ====================

@app.get("/")
async def home_page(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    visitor_stats = get_visitor_stats_html()
    system_status = "🟢"
    binance_status = "🟢" if get_binance_client() else "🔴"
    
    html = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ICT SMART PRO</title>
        <style>
            /* (CSS aynı kaldı) */
            body {{background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: white; font-family: Arial, sans-serif; margin: 0; padding: 20px; min-height: 100vh;}}
            /* ... diğer stiller aynı ... */
        </style>
    </head>
    <body>
        <div class="user-info">👤 {user}</div>
        {visitor_stats}
        <!-- Ana sayfa içeriği aynı -->
        <script>
            const ws = new WebSocket((window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws/pump_radar');
            ws.onopen = function() {{ document.getElementById('update-info').innerHTML = '✅ Bağlantı kuruldu'; }};
            ws.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    if (data.ping) return;
                    if (data.last_update) document.getElementById('update-info').innerHTML = '🔄 ' + data.last_update;
                    const table = document.getElementById('pump-table');
                    if (!data.top_gainers || data.top_gainers.length === 0) {{
                        table.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:40px;color:#ffd700;">📊 Şu anda aktif pump yok</td></tr>';
                        return;
                    }}
                    let html = '';
                    data.top_gainers.forEach(function(coin, index) {{
                        const changeClass = coin.change > 0 ? 'change-positive' : 'change-negative';
                        const changeSign = coin.change > 0 ? '+' : '';
                        html += `
                            <tr>
                                <td>#${{index + 1}}</td>
                                <td><strong>${{coin.symbol}}</strong></td>
                                <td>$${{(coin.price >= 1 ? coin.price.toFixed(2) : coin.price.toFixed(6))}}</td>
                                <td class="${{changeClass}}">${{changeSign}}${{coin.change.toFixed(2)}}%</td>
                            </tr>`;
                    }});
                    table.innerHTML = html;
                }} catch (e) {{ console.error(e); }}
            }};
        </script>
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
    
    html = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Tek Coin Sinyal - ICT SMART PRO</title>
        <style>
            body {{background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: white; font-family: Arial, sans-serif; margin: 0; padding: 20px; min-height: 100vh;}}
            .container {{max-width: 1000px; margin: 0 auto;}}
            /* ... diğer stiller aynı ... */
            .chart-container {{
                width: 100%;
                height: 80vh;
                min-height: 800px;
                max-height: 1200px;
                background: rgba(10, 0, 34, 0.9);
                border-radius: 16px;
                margin: 30px 0;
                overflow: hidden;
                box-shadow: 0 8px 32px rgba(0,0,0,0.6), 0 0 30px rgba(0,219,222,0.15);
                border: 1px solid rgba(0,219,222,0.3);
            }}
            /* ... diğer stiller ... */
        </style>
        <script src="https://s3.tradingview.com/tv.js"></script>
    </head>
    <body>
        <div class="user-info">👤 {user}</div>
        {visitor_stats}
        <div class="container">
            <div class="header"><h1 class="title">📊 TEK COİN CANLI SİNYAL</h1></div>
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
                    <option value="1W">1 Hafta</option>
                    <option value="1M">1 Ay</option>
                </select>
                <div>
                    <button onclick="connectSignal()">🔴 CANLI SİNYAL BAĞLANTISI KUR</button>
                    <button onclick="analyzeChartWithAI()" style="background:linear-gradient(45deg,#00dbde,#ff00ff);">🤖 GRAFİĞİ ANALİZ ET</button>
                </div>
                <div id="connection-status" style="color:#00ffff;margin:10px 0;">Bağlantı bekleniyor...</div>
            </div>
            <div id="signal-card" class="signal-card">
                <div id="signal-text" class="signal-text" style="color: #ffd700;">Sinyal bağlantısı kurulmadı</div>
                <div id="signal-details">Canlı sinyal için yukarıdaki butona tıklayın.</div>
            </div>
            <div id="ai-box" class="ai-analysis">
                <h3 style="color:#00dbde;text-align:center;">🤖 TEKNİK ANALİZ RAPORU</h3>
                <p id="ai-comment">Analiz için "Grafiği Analiz Et" butonuna tıklayın.</p>
            </div>
            <div class="chart-container"><div id="tradingview_widget"></div></div>
            <div class="navigation">
                <a href="/" class="nav-link">← Ana Sayfa</a>
                <a href="/signal/all" class="nav-link">Tüm Coinler →</a>
            </div>
        </div>
        <script>
            let signalWs = null;
            let tradingViewWidget = null;
            let currentSymbol = "BTC";
            let currentTimeframe = "5m";
            
            const timeframeMap = {{
                "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
                "1h": "60", "4h": "240", "1d": "D", "1W": "W", "1M": "M"
            }};
            
            function getTradingViewSymbol(pair) {{
                let symbol = pair.trim().toUpperCase();
                if (!symbol.endsWith("USDT")) symbol += "USDT";
                return "BINANCE:" + symbol;
            }}
            
            function connectSignal() {{
                currentSymbol = document.getElementById('pair').value.trim().toUpperCase();
                currentTimeframe = document.getElementById('timeframe').value;
                const tvSymbol = getTradingViewSymbol(currentSymbol);
                const interval = timeframeMap[currentTimeframe] || "5";
                
                if (signalWs) {{ signalWs.close(); signalWs = null; }}
                if (tradingViewWidget) {{ tradingViewWidget.remove(); }}
                
                tradingViewWidget = new TradingView.widget({{
                    width: "100%", height: "100%", symbol: tvSymbol, interval: interval,
                    timezone: "Etc/UTC", theme: "dark", style: "1", locale: "tr",
                    container_id: "tradingview_widget"
                }});
                
                const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
                signalWs = new WebSocket(protocol + window.location.host + '/ws/signal/' + currentSymbol + '/' + currentTimeframe);
                
                signalWs.onopen = function() {{
                    document.getElementById('connection-status').innerHTML = '✅ ' + currentSymbol + ' ' + currentTimeframe.toUpperCase() + ' canlı sinyal başladı!';
                }};
                
                signalWs.onmessage = function(event) {{
                    try {{
                        if (event.data.includes('heartbeat')) return;
                        const data = JSON.parse(event.data);
                        const card = document.getElementById('signal-card');
                        const text = document.getElementById('signal-text');
                        const details = document.getElementById('signal-details');
                        
                        text.innerHTML = data.signal || "⏸️ Sinyal bekleniyor...";
                        
                        details.innerHTML = `
                            <strong>${{data.pair || currentSymbol + '/USDT'}}</strong><br>
                            💰 Fiyat: <strong>$${{(data.current_price || 0).toFixed(data.current_price < 1 ? 6 : 4)}}</strong><br>
                            📊 Skor: <strong>${{data.score || '?'}} / 100</strong> | ${{data.killzone || 'Normal'}}
                        `;
                        
                        if (data.signal && (data.signal.includes('ALIM') || data.signal.includes('YÜKSELİŞ'))) {{
                            card.className = 'signal-card green'; text.style.color = '#00ff88';
                        }} else if (data.signal && (data.signal.includes('SATIM') || data.signal.includes('DÜŞÜŞ'))) {{
                            card.className = 'signal-card red'; text.style.color = '#ff4444';
                        }} else {{
                            card.className = 'signal-card'; text.style.color = '#ffd700';
                        }}
                    }} catch (e) {{ console.error(e); }}
                }};
            }}
            
            async function analyzeChartWithAI() {{
                const btn = document.querySelector('button[onclick="analyzeChartWithAI()"]');
                const box = document.getElementById('ai-box');
                const comment = document.getElementById('ai-comment');
                btn.disabled = true; btn.innerHTML = "⏳ Analiz ediliyor...";
                box.style.display = 'block'; comment.innerHTML = "📊 Teknik analiz oluşturuluyor...";
                try {{
                    const response = await fetch('/api/analyze-chart', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ symbol: currentSymbol, timeframe: currentTimeframe }})
                    }});
                    const data = await response.json();
                    comment.innerHTML = data.success ? data.analysis.replace(/\\n/g, '<br>') : '<strong style="color:#ff4444">❌ Hata:</strong><br>' + data.analysis;
                }} catch (err) {{
                    comment.innerHTML = '<strong style="color:#ff4444">❌ Bağlantı hatası:</strong><br>' + err.message;
                }} finally {{
                    btn.disabled = false; btn.innerHTML = "🤖 GRAFİĞİ ANALİZ ET";
                }}
            }}
            
            setTimeout(connectSignal, 1000);
        </script>
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
    
    html = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Tüm Coin Sinyalleri - ICT SMART PRO</title>
        <style>
            /* Stil aynı */
        </style>
    </head>
    <body>
        <div class="user-info">👤 {user}</div>
        {visitor_stats}
        <div class="container">
            <div class="header"><h1 class="title">🔥 TÜM COİN SİNYALLERİ</h1></div>
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
                    <thead><tr><th>#</th><th>COİN</th><th>SİNYAL</th><th>SKOR</th><th>FİYAT</th></tr></thead>
                    <tbody id="signals-table">
                        <tr><td colspan="5" style="text-align: center; padding: 50px;">📊 Zaman dilimi seçerek sinyalleri görüntüleyin...</td></tr>
                    </tbody>
                </table>
            </div>
            <div class="navigation">
                <a href="/" class="nav-link">← Ana Sayfa</a>
                <a href="/signal" class="nav-link">Tek Coin Sinyal →</a>
            </div>
        </div>
        <script>
            let allSignalsWs = null;
            function connectAllSignals() {{
                const timeframe = document.getElementById('timeframe').value;
                document.getElementById('connection-status').innerHTML = '🔄 ' + timeframe.toUpperCase() + ' sinyalleri yükleniyor...';
                if (allSignalsWs) allSignalsWs.close();
                const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
                allSignalsWs = new WebSocket(protocol + window.location.host + '/ws/all/' + timeframe);
                allSignalsWs.onopen = function() {{
                    document.getElementById('connection-status').innerHTML = '✅ ' + timeframe.toUpperCase() + ' canlı sinyal akışı başladı!';
                }};
                allSignalsWs.onmessage = function(event) {{
                    try {{
                        if (event.data.includes('ping')) return;
                        const signals = JSON.parse(event.data);
                        const table = document.getElementById('signals-table');
                        if (!signals || signals.length === 0) {{
                            table.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 50px; color: #ffd700;">📊 Şu anda güçlü sinyal bulunmuyor</td></tr>';
                            return;
                        }}
                        let html = '';
                        signals.slice(0, 50).forEach(function(signal, index) {{  // 50'ye çıkardık
                            let signalClass = 'signal-neutral';
                            if (signal.signal && signal.signal.includes('ALIM')) signalClass = 'signal-buy';
                            else if (signal.signal && signal.signal.includes('SATIM')) signalClass = 'signal-sell';
                            html += `
                                <tr>
                                    <td>#${{index + 1}}</td>
                                    <td><strong>${{signal.pair ? signal.pair.replace('USDT', '/USDT') : 'N/A'}}</strong></td>
                                    <td class="${{signalClass}}">${{signal.signal || '⏸️ Bekle'}}</td>
                                    <td><strong>${{signal.score || '?'}}/100</strong></td>
                                    <td>$${{(signal.current_price || 0).toFixed(signal.current_price < 1 ? 6 : 4)}}</td>
                                </tr>
                            `;
                        }});
                        table.innerHTML = html;
                    }} catch (e) {{ console.error(e); }}
                }};
            }}
            setTimeout(() => {{ document.getElementById('timeframe').value = '5m'; connectAllSignals(); }}, 500);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

# ==================== API ENDPOINTS ====================

# (Diğer API endpoint'leri aynı kaldı)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    logger.info(f"🚀 ICT SMART PRO v7.0 başlatılıyor... Host: {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)
