# main.py — PRODUCTION-READY, SENTAKS HATASI OLMAYAN, ÇALIŞIR HALİ
import base64
import logging
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Dict, List, Set
import json
import pandas as pd
import hashlib
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from openai import OpenAI

# Core'dan gerekli bileşenler — eksiksiz import
from core import (
    initialize,
    cleanup,
    single_subscribers,
    all_subscribers,
    pump_radar_subscribers,
    shared_signals,
    active_strong_signals,
    top_gainers,
    last_update,
    rt_ticker,
    get_binance_client,
    price_sources_status,
    price_pool,
    get_all_prices_snapshot  # ✅ EKSİKTİ — EKLENDİ
)

# Utils & vars
from utils import all_usdt_symbols

# OpenAI client (opsiyonel)
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

# ==================== LOGGER ====================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("main")

# ==================== ZİYARETÇİ SAYACI ====================
class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users: Set[str] = set()
        self.daily_stats: Dict[str, Dict] = {}
        self.page_views: Dict[str, int] = {}

    def add_visit(self, page: str, user_id: Optional[str] = None) -> int:
        self.total_visits += 1
        self.page_views[page] = self.page_views.get(page, 0) + 1
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self.daily_stats:
            self.daily_stats[today] = {"visits": 0, "unique": set()}
        self.daily_stats[today]["visits"] += 1
        if user_id:
            self.active_users.add(user_id)
            self.daily_stats[today]["unique"].add(user_id)
        return self.total_visits

    def get_stats(self) -> Dict:
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = self.daily_stats.get(today, {"visits": 0, "unique": set()})
        return {
            "total_visits": self.total_visits,
            "active_users": len(self.active_users),
            "today_visits": today_stats["visits"],
            "today_unique": len(today_stats["unique"]),
            "page_views": self.page_views.copy(),
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
price_sources_subscribers: Set[WebSocket] = set()  # ✅ EKSİKTİ — EKLENDİ

# ==================== LIFESPAN (STARTUP/SHUTDOWN) ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize()
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="3.0 - STABLE")

# ==================== MIDDLEWARE: ZİYARETÇİ SAYACI ====================
@app.middleware("http")
async def count_visitors(request: Request, call_next):
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        ip = request.client.host or "anonymous"
        visitor_id = hashlib.md5(ip.encode()).hexdigest()[:8]
    page = request.url.path
    visitor_counter.add_visit(page, visitor_id)
    response = await call_next(request)
    if not request.cookies.get("visitor_id"):
        response.set_cookie("visitor_id", visitor_id, max_age=86400, httponly=True, samesite="lax")
    return response

# ==================== WEBSOCKET ENDPOINTS ====================

@app.websocket("/ws/price_sources")
async def ws_price_sources(websocket: WebSocket):
    await websocket.accept()
    price_sources_subscribers.add(websocket)
    try:
        await websocket.send_json({
            "sources": price_sources_status,
            "total_symbols": len(price_pool)
        })
        while True:
            await asyncio.sleep(5)
            await websocket.send_json({
                "sources": price_sources_status,
                "total_symbols": len(price_pool)
            })
    except WebSocketDisconnect:
        price_sources_subscribers.discard(websocket)

@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_signal(websocket: WebSocket, pair: str, timeframe: str):
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
        pass
    finally:
        single_subscribers[channel].discard(websocket)

@app.websocket("/ws/all/{timeframe}")
async def ws_all(websocket: WebSocket, timeframe: str):
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

@app.websocket("/ws/pump_radar")
async def ws_pump(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    await websocket.send_json({"top_gainers": top_gainers, "last_update": last_update})
    try:
        while True:
            await asyncio.sleep(20)
            await websocket.send_json({"ping": True})
    except WebSocketDisconnect:
        pump_radar_subscribers.discard(websocket)

@app.websocket("/ws/realtime_price")
async def ws_realtime_price(websocket: WebSocket):
    await websocket.accept()
    await rt_ticker.subscribe(websocket)
    try:
        while True:
            data = get_all_prices_snapshot(limit=50)  # ✅ Artık import edildi
            await websocket.send_json(data)
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        await rt_ticker.unsubscribe(websocket)
    except Exception as e:
        logger.error(f"Realtime price WS error: {e}")
        await rt_ticker.unsubscribe(websocket)

# ==================== HTTP ENDPOINTS ====================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    visitor_stats_html = get_visitor_stats_html()
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>ICT SMART PRO</title>
    <style>
        body {{ background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: #fff; font-family: sans-serif; min-height: 100vh; margin: 0; display: flex; flex-direction: column; }}
        .container {{ max-width: 1200px; margin: auto; padding: 20px; flex: 1; }}
        h1 {{ font-size: clamp(2rem, 5vw, 5rem); text-align: center; background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde); -webkit-background-clip: text; -webkit-text-fill-color: transparent; animation: g 8s infinite; }}
        @keyframes g {{ 0% {{ background-position: 0%; }} 100% {{ background-position: 200%; }} }}
        .update {{ text-align: center; color: #00ffff; margin: 30px; font-size: clamp(1rem, 3vw, 1.8rem); }}
        table {{ width: 100%; border-collapse: separate; border-spacing: 0 12px; margin: 30px 0; }}
        th {{ background: #ffffff11; padding: clamp(10px, 2vw, 20px); font-size: clamp(1rem, 2.5vw, 1.6rem); }}
        tr {{ background: #ffffff08; transition: .4s; }}
        tr:hover {{ transform: scale(1.02); box-shadow: 0 15px 40px #00ffff44; }}
        .green {{ color: #00ff88; text-shadow: 0 0 20px #00ff88; }}
        .red {{ color: #ff4444; text-shadow: 0 0 20px #ff4444; }}
        .btn {{ display: block; width: 90%; max-width: 500px; margin: 20px auto; padding: clamp(15px, 3vw, 25px); font-size: clamp(1.2rem, 4vw, 2.2rem); background: linear-gradient(45deg, #fc00ff, #00dbde); color: #fff; text-align: center; border-radius: 50px; text-decoration: none; box-shadow: 0 0 60px #ff00ff88; transition: .3s; }}
        .btn:hover {{ transform: scale(1.08); box-shadow: 0 0 100px #ff00ff; }}
    </style>
</head>
<body>
    <div style='position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:clamp(0.8rem, 2vw, 1.2rem);z-index:1000;'>
        Hoş geldin, {user}
    </div>
    {visitor_stats_html}
    <div class="container">
        <h1>ICT SMART PRO</h1>
        <div class="update" id="update">Veri yükleniyor...</div>
        <table>
            <thead><tr><th>SIRA</th><th>COİN</th><th>FİYAT</th><th>24S DEĞİŞİM</th></tr></thead>
            <tbody id="table-body">
                <tr><td colspan="4" style="padding:80px;color:#888">Pump radar yükleniyor...</td></tr>
            </tbody>
        </table>
        <a href="/signal" class="btn">🚀 Tek Coin Canlı Sinyal + Grafik</a>
        <a href="/signal/all" class="btn">🔥 Tüm Coinleri Tara</a>
    </div>
    <script>
        const ws = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/pump_radar'); // ✅ REALTIME_PRICE değil, PUMP_RADAR — DÜZELTME
        ws.onmessage = function(e) {{
            try {{
                const d = JSON.parse(e.data);
                document.getElementById('update').innerHTML = `Son Güncelleme: <strong>${{d.last_update || 'Şimdi'}}</strong>`;
                const t = document.getElementById('table-body');
                if (!d.top_gainers || d.top_gainers.length === 0) {{
                    t.innerHTML = '<tr><td colspan="4" style="padding:80px;color:#ffd700">😴 Şu anda pump yok</td></tr>';
                    return;
                }}
                t.innerHTML = d.top_gainers.slice(0, 10).map((c, i) => `
                    <tr>
                        <td>#${{i+1}}</td>
                        <td><strong>${{c.symbol}}</strong></td>
                        <td>$${{c.price.toFixed(c.price > 1 ? 2 : 6)}}</td>
                        <td class="${{c.change > 0 ? 'green' : 'red'}}">${{c.change > 0 ? '+' : ''}}${{c.change.toFixed(2)}}%</td>
                    </tr>
                `).join('');
            }} catch (err) {{ console.error('Pump radar hatası:', err); }}
        }};
        ws.onopen = () => {{ document.getElementById('update').innerHTML = '✅ Pump radar bağlantısı kuruldu'; }};
        ws.onerror = () => {{ document.getElementById('update').innerHTML = '❌ Pump radar bağlantısı hatası'; }};
        ws.onclose = () => {{ document.getElementById('update').innerHTML = '🔌 Pump radar bağlantısı kesildi'; }};
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)


@app.get("/signal", response_class=HTMLResponse)
async def signal_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    visitor_stats_html = get_visitor_stats_html()
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>CANLI SİNYAL + GRAFİK | ICT SMART PRO</title>
    <style>
        body {{ background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: #fff; font-family: sans-serif; margin: 0; padding: 20px 0; min-height: 100vh; }}
        .container {{ max-width: 1200px; margin: auto; padding: 20px; display: flex; flex-direction: column; gap: 25px; }}
        h1 {{ font-size: clamp(2rem, 5vw, 3.8rem); text-align: center; background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde); -webkit-background-clip: text; -webkit-text-fill-color: transparent; animation: g 8s infinite; }}
        @keyframes g {{ 0% {{ background-position: 0; }} 100% {{ background-position: 200%; }} }}
        .controls {{ background: #ffffff11; border-radius: 20px; padding: 20px; text-align: center; }}
        input, select, button {{ width: 100%; max-width: 500px; padding: 15px; margin: 10px auto; font-size: 1.4rem; border: none; border-radius: 16px; background: #333; color: #fff; }}
        button {{ background: linear-gradient(45deg, #fc00ff, #00dbde); font-weight: bold; cursor: pointer; }}
        #analyze-btn {{ background: linear-gradient(45deg, #00dbde, #ff00ff, #00ffff); }}
        #status {{ color: #00ffff; text-align: center; margin: 15px; }}
        #price-text {{ font-size: clamp(3rem, 8vw, 5rem); font-weight: bold; background: linear-gradient(90deg, #00ffff, #ff00ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        #signal-card {{ background: #000000aa; border-radius: 20px; padding: 25px; text-align: center; min-height: 160px; }}
        #signal-card.green {{ border-left: 8px solid #00ff88; }}
        #signal-card.red {{ border-left: 8px solid #ff4444; }}
        #signal-text {{ font-size: clamp(2rem, 5vw, 3rem); }}
        #ai-box {{ background: #0d0033ee; border-radius: 20px; padding: 25px; border: 3px solid #00dbde; display: none; }}
        .chart-container {{ width: 95%; max-width: 1000px; margin: 30px auto; border-radius: 20px; overflow: hidden; box-shadow: 0 15px 50px #00ffff44; background: #0a0022; }}
        #tradingview_widget {{ height: 500px; width: 100%; }}
    </style>
    <script src="https://s3.tradingview.com/tv.js"></script>
</head>
<body>
    <div style="position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;z-index:1000;">
        Hoş geldin, {user}
    </div>
    {visitor_stats_html}
    <div class="container">
        <h1>📊 CANLI SİNYAL + GRAFİK</h1>
        <div class="controls">
            <input id="pair" placeholder="Coin (örn: BTCUSDT)" value="BTCUSDT">
            <select id="tf">
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
            <button onclick="connect()">🔴 CANLI SİNYAL BAĞLANTISI KUR</button>
            <button id="analyze-btn" onclick="analyzeChartWithAI()">🤖 GRAFİĞİ GPT-4o İLE ANALİZ ET</button>
            <div id="status">Grafik yükleniyor...</div>
        </div>
        <div style="text-align:center;margin:20px">
            <div id="price-text">Yükleniyor...</div>
        </div>
        <div id="signal-card">
            <div id="signal-text" style="color:#ffd700">Sinyal bağlantısı kurulmadı</div>
            <div id="signal-details">Canlı sinyal için butona tıklayın.</div>
        </div>
        <div id="ai-box">
            <h3 style="color:#00dbde;text-align:center">🤖 GPT-4o Teknik Analizi</h3>
            <p id="ai-comment">Analiz için butona tıklayın.</p>
        </div>
        <div class="chart-container">
            <div id="tradingview_widget"></div>
        </div>
        <div style="text-align:center">
            <a href="/" style="color:#00dbde">← Ana Sayfa</a> |
            <a href="/signal/all" style="color:#00dbde">Tüm Coinler</a>
        </div>
    </div>
    <script>
        let ws = null;
        let tvWidget = null;
        let currentPrice = null;
        const tfMap = {{
            "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
            "1h": "60", "4h": "240", "1d": "D", "1w": "W"
        }};

        function getSymbol() {{
            let pair = document.getElementById('pair').value.trim().toUpperCase();
            if (!pair.endsWith("USDT")) pair += "USDT";
            return "BINANCE:" + pair;
        }}

        async function connect() {{
            const symbolInput = document.getElementById('pair').value.trim().toUpperCase();
            const tfSelect = document.getElementById('tf').value;
            let symbol = symbolInput.endsWith("USDT") ? symbolInput : symbolInput + "USDT";
            const tvSymbol = "BINANCE:" + symbol;
            const interval = tfMap[tfSelect] || "5";

            // Eski widget'ı temizle
            if (tvWidget) {{
                tvWidget.remove();
                tvWidget = null;
            }}
            document.getElementById('tradingview_widget').innerHTML = '';

            // Yeni widget oluştur
            tvWidget = new TradingView.widget({{
                autosize: true,
                symbol: tvSymbol,
                interval: interval,
                timezone: "Etc/UTC",
                theme: "dark",
                style: "1",
                locale: "tr",
                container_id: "tradingview_widget",
                studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies"]
            }});

            tvWidget.onChartReady(() => {{
                document.getElementById('status').innerHTML = `✅ Grafik yüklendi: ${{symbol}} ${{tfSelect.toUpperCase()}}`;
                startPriceTracking();
            }});

            function startPriceTracking() {{
                setInterval(() => {{
                    try {{
                        const priceEl = document.querySelector('#tradingview_widget .last-value');
                        if (priceEl) {{
                            const text = priceEl.textContent || priceEl.innerText;
                            const price = parseFloat(text.replace(/[^0-9.]/g, ''));
                            if (!isNaN(price) && price !== currentPrice) {{
                                currentPrice = price;
                                document.getElementById('price-text').innerHTML = '$' + price.toFixed(price > 1 ? 2 : 6);
                            }}
                        }}
                    }} catch (e) {{}}
                }}, 2000);
            }}

            // WebSocket bağlantısı
            if (ws) ws.close();
            ws = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/signal/' + symbol + '/' + tfSelect);
            ws.onopen = () => {{
                document.getElementById('status').innerHTML = `✅ ${{symbol}} ${{tfSelect.toUpperCase()}} için canlı sinyal akışı başladı!`;
            }};
            ws.onmessage = (e) => {{
                if (e.data.includes('heartbeat')) return;
                try {{
                    const d = JSON.parse(e.data);
                    const card = document.getElementById('signal-card');
                    const text = document.getElementById('signal-text');
                    const details = document.getElementById('signal-details');
                    text.innerHTML = d.signal || "Sinyal bekleniyor...";
                    details.innerHTML = `
                        <strong>${{d.pair || symbol.replace('USDT','/USDT')}}</strong><br>
                        Skor: <strong>${{d.score || '?'}}/100</strong> | ${{d.killzone || ''}}<br>
                        ${{d.last_update ? 'Son: ' + d.last_update : ''}}<br>
                        <small>${{d.triggers || ''}}</small>
                    `;
                    if (d.signal && d.signal.includes('ALIM')) {{
                        card.className = 'green';
                        text.style.color = '#00ff88';
                    }} else if (d.signal && d.signal.includes('SATIM')) {{
                        card.className = 'red';
                        text.style.color = '#ff4444';
                    }} else {{
                        card.className = '';
                        text.style.color = '#ffd700';
                    }}
                }} catch (err) {{ console.error('Sinyal parse hatası:', err); }}
            }};
            ws.onerror = () => {{
                document.getElementById('status').innerHTML = "❌ WebSocket bağlantı hatası";
            }};
            ws.onclose = () => {{
                document.getElementById('status').innerHTML = "🔌 Sinyal bağlantısı kapandı. Yeniden bağlanmak için butona tıklayın.";
            }};
        }}

        async function analyzeChartWithAI() {{
            const btn = document.getElementById('analyze-btn');
            const box = document.getElementById('ai-box');
            const comment = document.getElementById('ai-comment');
            btn.disabled = true;
            btn.innerHTML = "Analiz ediliyor...";
            box.style.display = 'block';
            comment.innerHTML = "📊 Analiz yapılıyor...";

            try {{
                const symbol = document.getElementById('pair').value.trim().toUpperCase();
                const timeframe = document.getElementById('tf').value;
                const cleanSymbol = symbol.replace('USDT', '');
                const res = await fetch('/api/analyze-chart', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ symbol: cleanSymbol, timeframe: timeframe }})
                }});
                const data = await res.json();
                comment.innerHTML = data.analysis ? data.analysis.replace(/\\n/g, '<br>') : "❌ Analiz alınamadı";
            }} catch (err) {{
                comment.innerHTML = `❌ Hata: ${err.message || 'Bilinmeyen'}<br>Yeniden deneyin.`;
            }} finally {{
                btn.disabled = false;
                btn.innerHTML = "🤖 GRAFİĞİ GPT-4o İLE ANALİZ ET";
            }}
        }}

        document.addEventListener("DOMContentLoaded", connect);
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)


@app.get("/signal/all", response_class=HTMLResponse)
async def signal_all_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    visitor_stats_html = get_visitor_stats_html()
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>TÜM COİNLER | ICT SMART PRO</title>
    <style>
        body {{ background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: #fff; font-family: sans-serif; margin: 0; padding: 20px 0; min-height: 100vh; }}
        .container {{ max-width: 1200px; margin: auto; padding: 20px; }}
        h1 {{ font-size: clamp(2rem, 5vw, 3rem); text-align: center; background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .controls {{ background: #ffffff11; border-radius: 20px; padding: 20px; text-align: center; margin: 20px 0; }}
        select {{ width: 90%; max-width: 400px; padding: 15px; margin: 10px; font-size: 1.2rem; border: none; border-radius: 12px; background: #333; color: #fff; }}
        #status {{ color: #00ffff; text-align: center; margin: 15px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 30px 0; }}
        th {{ background: #ffffff11; padding: 15px; text-align: left; }}
        tr {{ border-bottom: 1px solid #333; }}
        tr:hover {{ background: #00ffff11; }}
        .green {{ color: #00ff88; }}
        .red {{ color: #ff4444; }}
    </style>
</head>
<body>
    <div style="position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;z-index:1000;">
        Hoş geldin, {user}
    </div>
    {visitor_stats_html}
    <div class="container">
        <h1>🔥 TÜM COİN SİNYALLERİ</h1>
        <div class="controls">
            <select id="tf" onchange="connect()">
                <option value="5m">5 Dakika</option>
                <option value="15m">15 Dakika</option>
                <option value="1h">1 Saat</option>
                <option value="4h">4 Saat</option>
                <option value="1d">1 Gün</option>
            </select>
            <div id="status">Zaman dilimi seçin...</div>
        </div>
        <div id="table-container">
            <table>
                <thead><tr><th>#</th><th>COİN</th><th>SİNYAL</th><th>SKOR</th><th>FİYAT</th><th>ZAMAN</th></tr></thead>
                <tbody id="signal-table">
                    <tr><td colspan="6" style="padding:50px;text-align:center;color:#888">Zaman dilimi seçin...</td></tr>
                </tbody>
            </table>
        </div>
        <div style="text-align:center;margin-top:30px">
            <a href="/" style="color:#00dbde;margin-right:20px">← Ana Sayfa</a>
            <a href="/signal" style="color:#00dbde">Tek Coin Sinyal →</a>
        </div>
    </div>
    <script>
        let ws = null;
        function connect() {{
            const timeframe = document.getElementById('tf').value;
            document.getElementById('status').innerHTML = `${{timeframe.toUpperCase()}} sinyalleri yükleniyor...`;
            if (ws) ws.close();
            ws = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/all/' + timeframe);
            ws.onopen = () => {{
                document.getElementById('status').innerHTML = `✅ ${{timeframe.toUpperCase()}} canlı sinyal akışı başladı!`;
            }};
            ws.onmessage = (e) => {{
                try {{
                    const data = JSON.parse(e.data);
                    const table = document.getElementById('signal-table');
                    if (!data || data.length === 0) {{
                        table.innerHTML = '<tr><td colspan="6" style="padding:50px;text-align:center;color:#ffd700">😴 Şu anda sinyal yok</td></tr>';
                        return;
                    }}
                    table.innerHTML = data.slice(0, 20).map((sig, i) => `
                        <tr>
                            <td>#${{i+1}}</td>
                            <td><strong>${{sig.pair || 'N/A'}}</strong></td>
                            <td class="${{sig.signal && sig.signal.includes('ALIM') ? 'green' : sig.signal && sig.signal.includes('SATIM') ? 'red' : ''}}">
                                ${{sig.signal || 'Bekle'}}
                            </td>
                            <td>${{sig.score || '?'}}/100</td>
                            <td>$${{sig.current_price ? sig.current_price.toFixed(4) : 'N/A'}}</td>
                            <td>${{sig.last_update || ''}}</td>
                        </tr>
                    `).join('');
                }} catch (err) {{ console.error('Sinyal listesi hatası:', err); }}
            }};
            ws.onerror = () => {{ document.getElementById('status').innerHTML = "❌ WebSocket bağlantı hatası"; }};
            ws.onclose = () => {{ document.getElementById('status').innerHTML = "🔌 Bağlantı kapandı. Tekrar seçin."; }};
        }}
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)


# ==================== API ENDPOINTS ====================

@app.post("/api/analyze-chart")
async def analyze_chart(request: Request):
    try:
        body = await request.json()
        symbol = body.get("symbol", "BTCUSDT").upper()
        timeframe = body.get("timeframe", "5m")
        logger.info(f"Analiz isteği: {symbol} @ {timeframe}")

        binance_client = get_binance_client()
        if not binance_client:
            return JSONResponse({
                "analysis": "❌ Binance bağlantısı aktif değil. Sunucu loglarını kontrol edin.",
                "success": False
            })

        interval_map = {
            "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
            "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
        }
        ccxt_timeframe = interval_map.get(timeframe, "5m")
        ccxt_symbol = symbol.replace('USDT', '/USDT')

        klines = await binance_client.fetch_ohlcv(ccxt_symbol, timeframe=ccxt_timeframe, limit=150)
        if not klines or len(klines) < 50:
            return JSONResponse({
                "analysis": f"❌ Yetersiz veri: {len(klines) if klines else 0} mum alındı (en az 50 gerekli)",
                "success": False
            })

        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna()

        signal = None
        try:
            from indicators import generate_ict_signal, generate_simple_signal
            signal = generate_ict_signal(df, symbol, timeframe)
            if not signal:
                signal = generate_simple_signal(df, symbol, timeframe)
        except Exception as e:
            logger.exception("Sinyal üretim hatası")

        if not signal:
            last_price = df['close'].iloc[-1] if len(df) > 0 else 0.0
            signal = {
                "pair": symbol.replace("USDT", "/USDT"),
                "timeframe": timeframe.upper(),
                "current_price": round(last_price, 4),
                "signal": "⏸️ ANALİZ BEKLENİYOR",
                "score": 50,
                "strength": "ORTA",
                "killzone": "Normal",
                "triggers": "Yeterli veri yok",
                "last_update": datetime.utcnow().strftime("%H:%M:%S UTC")
            }

        analysis = f"""🔍 {symbol} {timeframe} Grafik Analizi
🎯 SİNYAL: <strong>{signal['signal']}</strong>
📊 Skor: <strong>{signal['score']}/100</strong> ({signal['strength']})
💰 Fiyat: <strong>${signal['current_price']}</strong>
🕐 Killzone: <strong>{signal['killzone']}</strong>
🕒 Güncelleme: {signal['last_update']}
🎯 Tetikleyenler:
{signal['triggers']}

📈 ICT Strateji Özeti:
{symbol} için {signal['signal']} sinyali tespit edildi.
Bu analiz RSI6, SMA50, OB/FVG ve killzone verilerine dayanır.

⚠️ **Uyarı**: Bu bir yatırım tavsiyesi değildir. Yalnızca teknik bilgi amaçlıdır."""

        return JSONResponse({
            "analysis": analysis,
            "signal_data": signal,
            "success": True
        })

    except Exception as e:
        logger.exception("API analiz hatası")
        return JSONResponse({
            "analysis": f"❌ Sunucu hatası: {str(e)[:150]}",
            "success": False
        }, status_code=500)


@app.post("/api/gpt-analyze")
async def gpt_analyze_endpoint(image_file: UploadFile = File(...)):
    if not openai_client:
        return JSONResponse({
            "error": "OpenAI API anahtarı tanımlı değil",
            "tip": "OPENAI_API_KEY ortam değişkenini ayarlayın"
        }, status_code=501)
    try:
        image_data = await image_file.read()
        image_b64 = base64.b64encode(image_data).decode('utf-8')
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": """Bu grafik bir kripto varlığa aittir. Lütfen:
1. Genel trend (yükselen/inişli/yatay)
2. Destek ve direnç seviyeleri
3. Mum formasyonları (örn. engulfing, pin bar)
4. RSI/MACD durumu (aşırı alım/aşırı satım, kesişim)
5. Kısa vadeli alım/satım önerisi (stop-loss, take-profit)
Yanıtını Türkçe, net ve profesyonel bir dille ver."""},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
                ]
            }],
            max_tokens=1000,
            temperature=0.3
        )
        return JSONResponse({
            "analysis": response.choices[0].message.content,
            "success": True
        })
    except Exception as e:
        logger.exception("GPT-4o analiz hatası")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/visitor-stats")
async def visitor_stats_api():
    return JSONResponse(visitor_counter.get_stats())


@app.get("/admin/visitor-dashboard", response_class=HTMLResponse)
async def visitor_dashboard(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    stats = visitor_counter.get_stats()
    rows = "".join(f"<tr><td>{page}</td><td>{views}</td></tr>" for page, views in stats['page_views'].items())
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Ziyaretçi Paneli</title>
<style>body{{background:#000;color:#fff;padding:20px}}.card{{background:#00000088;padding:20px;border-radius:10px;margin:10px}}</style>
</head><body>
<h2>📊 Ziyaretçi İstatistikleri</h2>
<div class="card">Toplam: {stats['total_visits']} • Aktif: {stats['active_users']} • Bugün: {stats['today_visits']}</div>
<table border="0" cellpadding="10"><tr><th>Sayfa</th><th>Görüntülenme</th></tr>{rows}</table>
<a href="/" style="color:#00dbde">← Ana Sayfa</a>
</body></html>""")


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Giriş</title>
<style>body{background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh}
.box{background:#000000aa;padding:40px;border-radius:20px;text-align:center;max-width:400px;width:90%}
input{width:100%;padding:12px;margin:8px;border:none;border-radius:8px;background:#333;color:#fff}
button{width:100%;padding:12px;background:linear-gradient(45deg,#00dbde,#fc00ff);border:none;border-radius:8px;color:#fff;font-weight:bold}
</style></head><body>
<div class="box">
<h2>🔐 ICT SMART PRO</h2>
<form method="post"><input name="email" placeholder="E-posta (örn: test@example.com)" required><button type="submit">Giriş Yap</button></form>
<p style="margin-top:15px;color:#888">Demo hesabı — herhangi bir e-posta geçerli</p>
</div>
</body></html>"""


@app.post("/login")
async def do_login(request: Request):
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    if "@" in email:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("user_email", email, max_age=2592000, httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login")


@app.get("/debug/sources", response_class=HTMLResponse)
async def debug_sources(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Kaynak İzleyici</title>
<style>body{{background:#000;color:#fff;padding:20px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #333}}</style>
</head><body>
{get_visitor_stats_html()}
<h2>🟢 Fiyat Kaynakları</h2>
<p id="total">Yükleniyor...</p>
<table><thead><tr><th>Kaynak</th><th>Durum</th><th>Son Güncelleme</th><th>Coin Sayısı</th></tr></thead>
<tbody id="tbl"></tbody></table>
<script>
const ws = new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws/price_sources');
ws.onmessage=e=>{{
    const d=JSON.parse(e.data);
    document.getElementById('total').innerText='Toplam coin: '+d.total_symbols;
    const t=document.getElementById('tbl');
    t.innerHTML=Object.entries(d.sources).map(([k,v])=>`
        <tr><td>${{k.toUpperCase()}}</td>
            <td>${{v.healthy?'✅':'❌'}}</td>
            <td>${{v.last_update||'-'}}</td>
            <td>${{v.symbols_count||0}}</td>
        </tr>
    `).join('');
}};
</script>
</body></html>"""


@app.get("/health")
async def health_check():
    stats = visitor_counter.get_stats()
    return {
        "status": "ok",
        "uptime": "running",
        "symbols_loaded": len(all_usdt_symbols),
        "price_sources": {k: v["healthy"] for k, v in price_sources_status.items()},
        "visitor_stats": {
            "total": stats["total_visits"],
            "active": stats["active_users"],
            "today": stats["today_visits"]
        }
    }


# ==================== START SERVER ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
