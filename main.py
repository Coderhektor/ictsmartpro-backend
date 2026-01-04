# main.py — ICT SMART PRO v3.0 | TAM ÇALIŞAN, PRODUCTION-READY & RAILWAY UYUMLU
import logging
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict, Set, Any, List
import json
import pandas as pd
import hashlib
import os
from decimal import Decimal
import contextlib
import numpy as np 
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from openai import OpenAI
import ccxt.async_support as ccxt

# ====================== PROJE MODÜLLERİ ======================
from core import (
    initialize, cleanup,
    top_gainers, last_update,
    rt_ticker, price_pool
)

# top_losers opsiyonel → core.py'de yoksa boş liste fallback
try:
    from core import top_losers
except ImportError:
    top_losers = []
    logging.getLogger("main").warning("core.py'de top_losers tanımlı değil → boş liste kullanılıyor.")

# indicators.py opsiyonel
try:
    from indicators import generate_ict_signal, generate_simple_signal
except ImportError:
    logging.getLogger("main").warning("indicators.py bulunamadı → Sinyal üretimi fallback veya kapalı.")
    generate_ict_signal = generate_simple_signal = None

from utils import all_usdt_symbols

# ====================== LOGGING ======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("main")

# ====================== OPENAI (OPSİYONEL) ======================
openai_client = None
if os.getenv("OPENAI_API_KEY"):
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ====================== CCXT CLIENT'LARI ======================
binance_client = ccxt.binance({'enableRateLimit': True})
bybit_client = ccxt.bybit({'enableRateLimit': True})
okx_client = ccxt.okx({'enableRateLimit': True})
coingecko_client = None

def get_binance_client(): return binance_client
def get_bybit_client(): return bybit_client
def get_okex_client(): return okx_client
def get_coingecko_client(): return coingecko_client

# ====================== GLOBAL DEĞİŞKENLER ======================
single_subscribers: Dict[str, Set[WebSocket]] = {}
all_subscribers: Dict[str, Set[WebSocket]] = {
    "1m": set(), "3m": set(), "5m": set(), "15m": set(), "30m": set(),
    "1h": set(), "4h": set(), "1d": set(), "1w": set()
}
pump_radar_subscribers: Set[WebSocket] = set()
price_sources_subscribers: Set[WebSocket] = set()
shared_signals: Dict[str, Dict[str, Dict]] = {}
active_strong_signals: Dict[str, List[Dict]] = {tf: [] for tf in all_subscribers.keys()}
price_sources_status = {
    "binance": {"healthy": True, "last_update": "", "symbols_count": 0, "last_error": ""},
    "bybit": {"healthy": True, "last_update": "", "symbols_count": 0, "last_error": ""},
    "okx": {"healthy": True, "last_update": "", "symbols_count": 0, "last_error": ""}
}

# ====================== ZİYARETÇİ SAYACI ======================
class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users: Set[str] = set()
        self.daily_stats: Dict[str, Dict] = {}
        self.page_views: Dict[str, int] = {}

    def add_visit(self, page: str, user_id: str = None) -> int:
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
            "today_unique": len(today_stats.get("unique", set())),
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

# ====================== APP & LIFESPAN ======================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize()
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="3.0")

# ====================== MIDDLEWARE ======================
@app.middleware("http")
async def count_visitors(request: Request, call_next):
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        ip = request.client.host or "anonymous"
        visitor_id = hashlib.md5(ip.encode()).hexdigest()[:8]
    visitor_counter.add_visit(request.url.path, visitor_id)
    response = await call_next(request)
    if not request.cookies.get("visitor_id"):
        response.set_cookie("visitor_id", visitor_id, max_age=86400*30, httponly=True, samesite="lax")
    return response

# ====================== WEBSOCKET YARDIMCILARI ======================
SEND_TIMEOUT_SEC = 3.0
SUPPORTED_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"}

def pair_normalize(pair: str) -> str:
    sym = pair.upper().replace("/", "").replace("-", "").strip()
    if not sym.endswith("USDT"):
        sym += "USDT"
    return sym

def timeframe_validate(tf: str) -> bool:
    return tf in SUPPORTED_TIMEFRAMES

def to_json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_json_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, '__dict__'):
        return to_json_safe(obj.__dict__)
    return obj

async def safe_send_json(websocket: WebSocket, payload: Dict[str, Any]) -> bool:
    try:
        data = to_json_safe(payload)
        await asyncio.wait_for(websocket.send_json(data), timeout=SEND_TIMEOUT_SEC)
        return True
    except Exception:
        return False

async def heartbeat_task(websocket: WebSocket, interval_sec: int = 20):
    while True:
        if not await safe_send_json(websocket, {"ping": True, "ts": datetime.utcnow().isoformat()}):
            break
        await asyncio.sleep(interval_sec)

# ====================== WEBSOCKET ENDPOINTS ======================
@app.websocket("/ws/price_sources")
async def ws_price_sources(websocket: WebSocket):
    await websocket.accept()
    price_sources_subscribers.add(websocket)
    await safe_send_json(websocket, {"sources": price_sources_status, "total_symbols": len(all_usdt_symbols)})
    hb = asyncio.create_task(heartbeat_task(websocket, 20))
    try:
        while True:
            await safe_send_json(websocket, {"sources": price_sources_status, "total_symbols": len(all_usdt_symbols)})
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
    finally:
        hb.cancel()
        price_sources_subscribers.discard(websocket)
        with contextlib.suppress(Exception):
            await websocket.close()

@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_signal(websocket: WebSocket, pair: str, timeframe: str):
    if not timeframe_validate(timeframe):
        await websocket.close(code=1008, reason="Unsupported timeframe")
        return
    await websocket.accept()
    symbol = pair_normalize(pair)
    channel = f"{symbol}:{timeframe}"
    if channel not in single_subscribers:
        single_subscribers[channel] = set()
    single_subscribers[channel].add(websocket)

    try:
        sig = shared_signals.get(timeframe, {}).get(symbol)
        if sig:
            await safe_send_json(websocket, {"signal": sig})
    except Exception as e:
        logger.warning(f"İlk sinyal gönderim hatası ({channel}): {e}")

    hb = asyncio.create_task(heartbeat_task(websocket, 15))
    try:
        while True:
            await asyncio.sleep(3600)
    except WebSocketDisconnect:
        pass
    finally:
        hb.cancel()
        if channel in single_subscribers:
            single_subscribers[channel].discard(websocket)
            if not single_subscribers[channel]:
                del single_subscribers[channel]
        with contextlib.suppress(Exception):
            await websocket.close()

@app.websocket("/ws/all/{timeframe}")
async def ws_all(websocket: WebSocket, timeframe: str):
    if not timeframe_validate(timeframe):
        await websocket.close(code=1008, reason="Unsupported timeframe")
        return
    await websocket.accept()
    all_subscribers[timeframe].add(websocket)
    await safe_send_json(websocket, {"signals": active_strong_signals.get(timeframe, [])})
    hb = asyncio.create_task(heartbeat_task(websocket, 30))
    try:
        while True:
            await asyncio.sleep(3600)
    except WebSocketDisconnect:
        pass
    finally:
        hb.cancel()
        all_subscribers[timeframe].discard(websocket)
        with contextlib.suppress(Exception):
            await websocket.close()

@app.websocket("/ws/pump_radar")
async def ws_pump(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    await safe_send_json(websocket, {
        "top_gainers": top_gainers,
        "top_losers": top_losers or [],  # Güvenli fallback
        "last_update": last_update
    })
    hb = asyncio.create_task(heartbeat_task(websocket, 20))
    try:
        while True:
            await asyncio.sleep(3600)
    except WebSocketDisconnect:
        pass
    finally:
        hb.cancel()
        pump_radar_subscribers.discard(websocket)
        with contextlib.suppress(Exception):
            await websocket.close()

@app.websocket("/ws/realtime_price")
async def ws_realtime_price(websocket: WebSocket):
    await websocket.accept()
    await rt_ticker.subscribe(websocket)
    snapshot = await price_pool.snapshot(limit=50)
    await safe_send_json(websocket, snapshot)
    hb = asyncio.create_task(heartbeat_task(websocket, 15))
    try:
        while True:
            await asyncio.sleep(3600)
    except WebSocketDisconnect:
        pass
    finally:
        hb.cancel()
        await rt_ticker.unsubscribe(websocket)
        with contextlib.suppress(Exception):
            await websocket.close()

# ====================== HTML SAYFALAR ======================
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
        body {{background: linear-gradient(135deg, #0a0022, #1a0033, #000);color: #fff;font-family: sans-serif;min-height: 100vh;margin: 0;display: flex;flex-direction: column;}}
        .container {{max-width: 1200px;margin: auto;padding: 20px;flex: 1;}}
        h1 {{font-size: clamp(2rem, 5vw, 5rem);text-align: center;background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde);-webkit-background-clip: text;-webkit-text-fill-color: transparent;animation: g 8s infinite;}}
        @keyframes g {{0% {{background-position: 0%;}}100% {{background-position: 200%;}}}}
        .update {{text-align: center;color: #00ffff;margin: 30px;font-size: clamp(1rem, 3vw, 1.8rem);}}
        table {{width: 100%;border-collapse: separate;border-spacing: 0 12px;margin: 30px 0;}}
        th {{background: #ffffff11;padding: clamp(10px, 2vw, 20px);font-size: clamp(1rem, 2.5vw, 1.6rem);}}
        tr {{background: #ffffff08;transition: .4s;}}
        tr:hover {{transform: scale(1.02);box-shadow: 0 15px 40px #00ffff44;}}
        .green {{color: #00ff88;text-shadow: 0 0 20px #00ff88;}}
        .red {{color: #ff4444;text-shadow: 0 0 20px #ff4444;}}
        .btn {{display: block;width: 90%;max-width: 500px;margin: 20px auto;padding: clamp(15px, 3vw, 25px);font-size: clamp(1.2rem, 4vw, 2.2rem);background: linear-gradient(45deg, #fc00ff, #00dbde);color: #fff;text-align: center;border-radius: 50px;text-decoration: none;box-shadow: 0 0 60px #ff00ff88;transition: .3s;}}
        .btn:hover {{transform: scale(1.08);box-shadow: 0 0 100px #ff00ff;}}
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
            <thead>
                <tr><th>SIRA</th><th>COİN</th><th>FİYAT</th><th>24S DEĞİŞİM</th></tr>
            </thead>
            <tbody id="table-body">
                <tr><td colspan="4" style="padding:80px;color:#888">Pump radar yükleniyor...</td></tr>
            </tbody>
        </table>
        <a href="/signal" class="btn">🚀 Tek Coin Canlı Sinyal + Grafik</a>
        <a href="/signal/all" class="btn">🔥 Tüm Coinleri Tara</a>
    </div>
    <script>
        const ws = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/realtime_price');
        ws.onmessage = function(e) {{
            try {{
                const d = JSON.parse(e.data);
                document.getElementById('update').innerHTML = `Son Güncelleme: <strong>${{d.last_update || 'Şimdi'}}</strong>`;
                const t = document.getElementById('table-body');
                if (!d.tickers || Object.keys(d.tickers).length === 0) {{
                    t.innerHTML = '<tr><td colspan="4" style="padding:80px;color:#ffd700">⏳ Fiyatlar yükleniyor...</td></tr>';
                    return;
                }}
                const tickers = Object.entries(d.tickers);
                t.innerHTML = tickers.slice(0, 10).map(([symbol, data], i) => `
                    <tr>
                        <td>#${{i+1}}</td>
                        <td><strong>${{symbol.replace('USDT', '')}}</strong></td>
                        <td>$${{data.price.toFixed(data.price > 1 ? 2 : 6)}}</td>
                        <td class="${{data.change > 0 ? 'green' : 'red'}}">${{data.change > 0 ? '+' : ''}}${{data.change.toFixed(2)}}%</td>
                    </tr>
                `).join('');
            }} catch (err) {{
                console.error('WebSocket veri hatası:', err);
            }}
        }};
        ws.onopen = () => document.getElementById('update').innerHTML = 'Canlı fiyatlar bağlandı...';
        ws.onerror = () => document.getElementById('update').innerHTML = '❌ Bağlantı hatası';
        ws.onclose = () => document.getElementById('update').innerHTML = '🔌 Bağlantı kesildi';
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
        body {{background: linear-gradient(135deg, #0a0022, #1a0033, #000);color: #fff;font-family: sans-serif;margin: 0;padding: 20px 0;min-height: 100vh;}}
        .container {{max-width: 1200px;margin: auto;padding: 20px;display: flex;flex-direction: column;gap: 25px;}}
        h1 {{font-size: clamp(2rem, 5vw, 3.8rem);text-align: center;background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde);-webkit-background-clip: text;-webkit-text-fill-color: transparent;animation: g 8s infinite;}}
        @keyframes g {{0% {{background-position: 0;}}100% {{background-position: 200%;}}}}
        .controls {{background: #ffffff11;border-radius: 20px;padding: 20px;text-align: center;}}
        input, select, button {{width: 100%;max-width: 500px;padding: 15px;margin: 10px auto;font-size: 1.4rem;border: none;border-radius: 16px;background: #333;color: #fff;}}
        button {{background: linear-gradient(45deg, #fc00ff, #00dbde);font-weight: bold;cursor: pointer;}}
        #analyze-btn {{background: linear-gradient(45deg, #00dbde, #ff00ff, #00ffff);}}
        #status {{color: #00ffff;text-align: center;margin: 15px;}}
        #price-text {{font-size: clamp(3rem, 8vw, 5rem);font-weight: bold;background: linear-gradient(90deg, #00ffff, #ff00ff);-webkit-background-clip: text;-webkit-text-fill-color: transparent;}}
        #signal-card {{background: #000000aa;border-radius: 20px;padding: 25px;text-align: center;min-height: 160px;}}
        #signal-card.green {{border-left: 8px solid #00ff88;}}
        #signal-card.red {{border-left: 8px solid #ff4444;}}
        #signal-text {{font-size: clamp(2rem, 5vw, 3rem);}}
        #ai-box {{background: #0d0033ee;border-radius: 20px;padding: 25px;border: 3px solid #00dbde;display: none;}}
        .chart-container {{width: 95%;max-width: 1000px;margin: 30px auto;border-radius: 20px;overflow: hidden;box-shadow: 0 15px 50px #00ffff44;background: #0a0022;}}
        #tradingview_widget {{height: 500px;width: 100%;}}
    </style>
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
    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>
        let ws = null;
        let tvWidget = null;
        let currentPrice = null;
        const tfMap = {{"1m":"1","3m":"3","5m":"5","15m":"15","30m":"30","1h":"60","4h":"240","1d":"D","1w":"W"}};

        function getSymbol() {{
            let pair = document.getElementById('pair').value.trim().toUpperCase();
            if (!pair.endsWith("USDT")) pair += "USDT";
            return "BINANCE:" + pair;
        }}

        function createWidget() {{
            const symbol = getSymbol();
            const interval = tfMap[document.getElementById('tf').value] || "5";
            if (tvWidget) tvWidget.remove();
            tvWidget = new TradingView.widget({{
                autosize: true, width: "100%", height: 500, symbol: symbol, interval: interval,
                timezone: "Etc/UTC", theme: "dark", style: "1", locale: "tr",
                container_id: "tradingview_widget",
                studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies"]
            }});
            tvWidget.onChartReady(() => {{
                document.getElementById('status').innerHTML = "✅ Grafik yüklendi • Sinyal bağlantısı kurun";
                setInterval(() => {{
                    try {{
                        const price = tvWidget.activeChart().getSeries().lastPrice();
                        if (price && price !== currentPrice) {{
                            currentPrice = price;
                            document.getElementById('price-text').innerHTML = '$' + parseFloat(price).toFixed(price > 1 ? 2 : 6);
                        }}
                    }} catch(e) {{}}
                }}, 1500);
            }});
        }}

        document.addEventListener("DOMContentLoaded", createWidget);
        document.getElementById('pair').addEventListener('change', createWidget);
        document.getElementById('tf').addEventListener('change', createWidget);

        async function analyzeChartWithAI() {{
            const btn = document.getElementById('analyze-btn');
            const box = document.getElementById('ai-box');
            const comment = document.getElementById('ai-comment');
            btn.disabled = true;
            btn.innerHTML = "Analiz ediliyor...";
            box.style.display = 'block';
            comment.innerHTML = "📸 Grafik yakalanıyor...<br>🧠 Analiz yapılıyor...";
            try {{
                const symbol = getSymbol().replace("BINANCE:", "");
                const timeframe = document.getElementById('tf').value;
                const response = await fetch('/api/analyze-chart', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{symbol: symbol, timeframe: timeframe}})
                }});
                const data = await response.json();
                if (data.analysis) {{
                    comment.innerHTML = data.analysis.replace(/\\n/g, '<br>');
                }} else {{
                    comment.innerHTML = "❌ Analiz alınamadı: " + (data.detail || 'Bilinmeyen hata');
                }}
            }} catch (err) {{
                comment.innerHTML = "❌ Bağlantı hatası. Tekrar deneyin.<br>" + err.message;
            }} finally {{
                btn.disabled = false;
                btn.innerHTML = "🤖 GRAFİĞİ GPT-4o İLE ANALİZ ET";
            }}
        }}

        function connect() {{
            const symbolInput = document.getElementById('pair').value.trim().toUpperCase();
            const tfSelect = document.getElementById('tf').value;
            let symbol = symbolInput;
            if (!symbol.endsWith("USDT")) symbol += "USDT";
            const tvSymbol = "BINANCE:" + symbol;
            const interval = tfMap[tfSelect] || "5";

            if (tvWidget) {{ tvWidget.remove(); tvWidget = null; }}
            tvWidget = new TradingView.widget({{
                autosize: true, width: "100%", height: 500, symbol: tvSymbol, interval: interval,
                timezone: "Etc/UTC", theme: "dark", style: "1", locale: "tr",
                container_id: "tradingview_widget",
                studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies"]
            }});

            tvWidget.onChartReady(() => {{
                document.getElementById('status').innerHTML = `✅ Grafik yüklendi: ${{symbol}} ${{tfSelect.toUpperCase()}} • Canlı sinyal akışı başladı!`;
                setInterval(() => {{
                    try {{
                        const price = tvWidget.activeChart().getSeries().lastPrice();
                        if (price && price !== currentPrice) {{
                            currentPrice = price;
                            document.getElementById('price-text').innerHTML = '$' + parseFloat(price).toFixed(price > 1 ? 2 : 6);
                        }}
                    }} catch(e) {{}}
                }}, 1500);
            }});

            if (ws) ws.close();
            ws = new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws/signal/'+symbol+'/'+tfSelect);

            ws.onopen = () => {{
                document.getElementById('status').innerHTML = `✅ ${{symbol}} ${{tfSelect.toUpperCase()}} için canlı sinyal akışı başladı!`;
            }};

            ws.onmessage = e => {{
                const d = JSON.parse(e.data);
                const card = document.getElementById('signal-card');
                const text = document.getElementById('signal-text');
                const details = document.getElementById('signal-details');

                text.innerHTML = d.signal?.signal || "Sinyal bekleniyor...";
                details.innerHTML = `
                    <strong>${{d.signal?.pair || symbol.replace('USDT','/USDT')}}</strong><br>
                    Skor: <strong>${{d.signal?.score || '?'}}/100</strong> | ${{d.signal?.killzone || ''}}<br>
                    ${{d.signal?.last_update ? 'Son: ' + d.signal.last_update : ''}}<br>
                    <small>${{d.signal?.triggers || ''}}</small>
                `;

                if (d.signal?.signal?.includes('ALIM') || d.signal?.signal?.includes('🚀')) {{
                    card.className = 'signal-card green';
                    text.style.color = '#00ff88';
                }} else if (d.signal?.signal?.includes('SATIM') || d.signal?.signal?.includes('🔻')) {{
                    card.className = 'signal-card red';
                    text.style.color = '#ff4444';
                }} else {{
                    card.className = 'signal-card';
                    text.style.color = '#ffd700';
                }}
            }};

            ws.onerror = () => document.getElementById('status').innerHTML = "❌ WebSocket bağlantı hatası";
            ws.onclose = () => document.getElementById('status').innerHTML = "🔌 Sinyal bağlantısı kapandı. Yeniden bağlanmak için butona tıklayın.";
        }}
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
        body {{background: linear-gradient(135deg, #0a0022, #1a0033, #000);color: #fff;font-family: sans-serif;margin: 0;padding: 20px 0;min-height: 100vh;}}
        .container {{max-width: 1200px;margin: auto;padding: 20px;}}
        h1 {{font-size: clamp(2rem, 5vw, 3rem);text-align: center;background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde);-webkit-background-clip: text;-webkit-text-fill-color: transparent;}}
        .controls {{background: #ffffff11;border-radius: 20px;padding: 20px;text-align: center;margin: 20px 0;}}
        select {{width: 90%;max-width: 400px;padding: 15px;margin: 10px;font-size: 1.2rem;border: none;border-radius: 12px;background: #333;color: #fff;}}
        #status {{color: #00ffff;text-align: center;margin: 15px;}}
        table {{width: 100%;border-collapse: collapse;margin: 30px 0;}}
        th {{background: #ffffff11;padding: 15px;text-align: left;}}
        tr {{border-bottom: 1px solid #333;}}
        tr:hover {{background: #00ffff11;}}
        .green {{color: #00ff88;}}
        .red {{color: #ff4444;}}
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
                <thead>
                    <tr>
                        <th>#</th><th>COİN</th><th>SİNYAL</th><th>SKOR</th><th>FİYAT</th><th>ZAMAN</th>
                    </tr>
                </thead>
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
            ws = new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws/all/'+timeframe);
            ws.onopen = () => document.getElementById('status').innerHTML = `✅ ${{timeframe.toUpperCase()}} canlı sinyal akışı başladı!`;
            ws.onmessage = e => {{
                const data = JSON.parse(e.data).signals || [];
                const table = document.getElementById('signal-table');
                if (data.length === 0) {{
                    table.innerHTML = '<tr><td colspan="6" style="padding:50px;text-align:center;color:#ffd700">😴 Şu anda güçlü sinyal yok</td></tr>';
                    return;
                }}
                table.innerHTML = data.map((sig, i) => `
                    <tr>
                        <td>#${{i+1}}</td>
                        <td><strong>${{sig.pair || 'N/A'}}</strong></td>
                        <td class="${{sig.signal?.includes('ALIM') || sig.signal?.includes('🚀') ? 'green' : sig.signal?.includes('SATIM') || sig.signal?.includes('🔻') ? 'red' : ''}}">
                            ${{sig.signal || 'Bekle'}}
                        </td>
                        <td>${{sig.score || '?'}}/100</td>
                        <td>$${{sig.current_price ? sig.current_price.toFixed(4) : 'N/A'}}</td>
                        <td>${{sig.last_update || ''}}</td>
                    </tr>
                `).join('');
            }};
            ws.onerror = () => document.getElementById('status').innerHTML = "❌ WebSocket bağlantı hatası";
            ws.onclose = () => document.getElementById('status').innerHTML = "🔌 Bağlantı kapandı. Yeniden seçin.";
        }}
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

# ====================== ANALİZ ENDPOINT ======================
 
from fastapi import Request, APIRouter
from fastapi.responses import JSONResponse
import asyncio
import pandas as pd
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

router = APIRouter()

# Mevcut yardımcılar (varsayım)
# get_binance_client(), get_bybit_client(), get_okex_client()
# generate_ict_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Dict[str, Any]
# logger

INTERVAL_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
}
DEFAULT_LIMIT = 300
MIN_REQUIRED = 50
FETCH_TIMEOUT_SEC = 10


def _normalize_symbol(symbol: str) -> Tuple[str, str]:
    """
    Sembol normalizasyonu:
    - Girilen her şeyi UPPERCASE.
    - 'BTCUSDT' => 'BTC/USDT'
    - 'BTC/USDT' => 'BTC/USDT'
    - 'ETHUSDC' => 'ETH/USDC' vb.
    """
    s = (symbol or "BTCUSDT").upper().replace(" ", "")
    if "/" in s:
        base, quote = s.split("/", 1)
        return f"{base}/{quote}", f"{base}{quote}"
    else:
        # BTCUSDT -> BTC/USDT (en yaygın çift)
        # 6+ karakterli ve USDT/USDC/USDP/FDUSD/USDD gibi stable eşleşmelerine bakılır
        stable_candidates = ("USDT", "USDC", "USDP", "FDUSD", "USDD", "BUSD")
        for st in stable_candidates:
            if s.endswith(st) and len(s) > len(st):
                base = s[:-len(st)]
                return f"{base}/{st}", s
        # Fallback
        return "BTC/USDT", "BTCUSDT"


async def _fetch_ohlcv(
    client: Any,
    name: str,
    ccxt_symbol: str,
    interval: str,
    limit: int
) -> Optional[Dict[str, Any]]:
    """
    Borsa’dan veri çekme. Timeout ve hata yakalama.
    Dönen dict:
      {name, klines, df, last_ts, length}
    """
    if client is None:
        return None
    try:
        klines = await asyncio.wait_for(
            client.fetch_ohlcv(ccxt_symbol, timeframe=interval, limit=limit),
            timeout=FETCH_TIMEOUT_SEC
        )
        if not klines or len(klines) < MIN_REQUIRED:
            return None

        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df = df.sort_values('timestamp').reset_index(drop=True)
        last_ts = df['timestamp'].iloc[-1]
        return {
            "name": name,
            "klines": klines,
            "df": df,
            "last_ts": last_ts,
            "length": len(klines)
        }
    except Exception as e:
        # Borsa spesifik hata loglanır ama akış durmaz
        try:
            logger.warning(f"{name} veri hatası: {e}")
        except Exception:
            pass
        return None


def _compute_freshness_minutes(last_ts: pd.Timestamp) -> float:
    now = datetime.now(timezone.utc)
    delta = now - last_ts
    return max(delta.total_seconds() / 60.0, 0.0)


def _volatility_weight(vol: str) -> float:
    """
    Volatiliteye göre güven etkisi:
      High -> daha düşük güven, Normal -> nötr, Low -> biraz daha yüksek.
    """
    v = (vol or "").lower()
    if "high" in v or "yüksek" in v:
        return 0.9
    if "low" in v or "düşük" in v:
        return 1.05
    return 1.0


def _freshness_weight(minutes: float, interval: str) -> float:
    """
    Tazelik (freshness) ağırlığı:
      - İntervale göre kabul edilebilir gecikme penceresi.
      - 5m için 2-3 bar gecikmeden sonra güven düşer.
    """
    baseline = {
        "1m": 3,
        "3m": 9,
        "5m": 15,
        "15m": 45,
        "30m": 90,
        "1h": 180,
        "4h": 720,
        "1d": 1440,
        "1w": 10080
    }.get(interval, 15)
    if minutes <= baseline:
        return 1.0
    elif minutes <= baseline * 2:
        return 0.95
    else:
        return 0.85


def _coverage_weight(length: int, limit: int) -> float:
    """
    Verinin kapsama oranına göre ağırlık:
      length/limit ile lineer ölçeklenir, taban 0.85, tavan 1.0.
    """
    ratio = max(min(length / float(limit), 1.0), 0.0)
    return 0.85 + 0.15 * ratio


def _agreement_weight(signals: List[str]) -> Tuple[float, Dict[str, Any]]:
    """
    Çoklu borsa sinyal uyumu:
      - Basit çoğunluk ile uyum yüzdesi.
      - Ağırlık: (0.90 .. 1.05)
    """
    if not signals:
        return 0.95, {"agreement_ratio": 0.0, "majority": "N/A"}

    from collections import Counter
    c = Counter([s or "Nötr" for s in signals])
    majority_signal, majority_count = c.most_common(1)[0]
    ratio = majority_count / max(len(signals), 1)

    # Nötr çoğunlukta hafif nötr yaklaşım
    if majority_signal.lower().startswith("nötr"):
        weight = 0.98 if ratio >= 0.6 else 0.95
    else:
        # Yüksek uyum -> daha yüksek güven
        if ratio >= 0.75:
            weight = 1.05
        elif ratio >= 0.6:
            weight = 1.02
        else:
            weight = 0.97

    return weight, {
        "agreement_ratio": round(ratio, 3),
        "majority": majority_signal
    }


def _derive_base_confidence(signal_dict: Dict[str, Any]) -> float:
    """
    Base confidence:
      - Varsa 'confidence' (0..1) kullanılır.
      - Yoksa 'score' (0..100) normalize edilir.
    """
    conf = signal_dict.get("confidence")
    if isinstance(conf, (float, int)):
        return max(min(float(conf), 1.0), 0.0)
    score = signal_dict.get("score")
    if isinstance(score, (float, int)):
        return max(min(float(score) / 100.0, 1.0), 0.0)
    return 0.5


@router.post("/api/analyze-chart")
async def analyze_chart(request: Request):
    try:
        body = await request.json()
        raw_symbol = body.get("symbol", "BTCUSDT")
        timeframe = body.get("timeframe", "5m")
        # Kullanıcının ek parametreleri şimdiden topla (ileride indicators.py'ye aktarılabilir)
        extra_params = {k: v for k, v in body.items() if k not in ("symbol", "timeframe")}
        try:
            logger.info(f"Analiz talebi: {raw_symbol} {timeframe} | extra={list(extra_params.keys())}")
        except Exception:
            pass

        ccxt_symbol, canonical = _normalize_symbol(raw_symbol)
        interval = INTERVAL_MAP.get(timeframe, "5m")

        clients = [
            (get_binance_client(), "Binance"),
            (get_bybit_client(), "Bybit"),
            (get_okex_client(), "OKX")
        ]
        tasks = [
            _fetch_ohlcv(client, name, ccxt_symbol, interval, DEFAULT_LIMIT)
            for client, name in clients
            if client is not None
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        sources = [r for r in results if r]

        if not sources:
            return JSONResponse({
                "analysis": "❌ Hiçbir borsadan veri alınamadı. Lütfen daha sonra tekrar deneyin.",
                "success": False
            })

        # Primary seçimi: en uzun ve en taze veri öncelikli
        sources_sorted = sorted(
            sources,
            key=lambda x: (x["length"], -_compute_freshness_minutes(x["last_ts"])),
            reverse=True
        )
        primary = sources_sorted[0]

        # Tazelik ve kapsama metrikleri
        freshness_min = _compute_freshness_minutes(primary["last_ts"])
        coverage_w = _coverage_weight(primary["length"], DEFAULT_LIMIT)
        freshness_w = _freshness_weight(freshness_min, interval)

        # Çoklu borsa sinyalleri (ensemble)
        per_exchange_signals = []
        for src in sources_sorted:
            try:
                # indicators.py tüm parametreleri kullanır: df + sembol + timeframe (+ extra_params)
                # Eğer generate_ict_signal ekstra kwargs desteklemiyorsa, bu çağrı sadece 3 parametreyi kullanır.
               	sig = generate_ict_signal(src["df"].copy(), canonical, timeframe, extra_params or {})
                per_exchange_signals.append({
                    "name": src["name"],
                    "signal": sig.get("signal", "Nötr"),
                    "score": sig.get("score", None),
                    "confidence": sig.get("confidence", None),
                    "killzone": sig.get("killzone", None),
                    "current_price": sig.get("current_price", None),
                    "status": sig.get("status", "unknown")
                })
            except Exception as e:
                try:
                    logger.warning(f"{src['name']} sinyal üretim hatası: {e}")
                except Exception:
                    pass

        # Primary kaynak ile detaylı analiz
       	signal_dict = generate_ict_signal(primary["df"].copy(), canonical, timeframe, extra_params or {})

        # Ensemble uyum ve ağırlıklar
        ensemble_signals = [s["signal"] for s in per_exchange_signals if s.get("signal") is not None]
        agreement_w, agreement_meta = _agreement_weight(ensemble_signals)

        market_struct = signal_dict.get("market_structure", {}) or {}
        vol = market_struct.get("volatility", "Normal")
        vol_w = _volatility_weight(vol)

        base_conf = _derive_base_confidence(signal_dict)

        # Nihai güven: çarpan bazlı kombinasyon, üst limit
        final_conf = base_conf * coverage_w * freshness_w * agreement_w * vol_w
        final_conf = max(min(final_conf, 1.0), 0.0)

        # Meta detaylar (kullanıcıya net bilgi)
        confidence_components = {
            "base_confidence": round(base_conf, 4),
            "coverage_weight": round(coverage_w, 4),
            "freshness_weight": round(freshness_w, 4),
            "agreement_weight": round(agreement_w, 4),
            "volatility_weight": round(vol_w, 4),
            "data_freshness_minutes": round(freshness_min, 2),
            "data_length": primary["length"],
            "interval": interval,
            "agreement_majority": agreement_meta["majority"],
            "agreement_ratio": agreement_meta["agreement_ratio"]
        }

        # Signal dict’e güven skorunu net şekilde yansıt
        signal_dict["confidence_final"] = final_conf
        signal_dict["confidence_components"] = confidence_components
        signal_dict["source_used"] = primary["name"]
        signal_dict["available_sources"] = [s["name"] for s in sources_sorted]

        # Analiz metni (tam durum veya fallback)
        if signal_dict.get("status") != "success":
            analysis = (
                f"🔍 {canonical} {timeframe.upper()} Grafik Analizi\n"
                f"⚠️ Tam ICT analizi yapılamadı (veri sınırlı olabilir).\n\n"
                f"📡 Kaynak: <strong>{primary['name']}</strong> ({primary['length']} mum)\n"
                f"💰 Güncel Fiyat: <strong>${signal_dict.get('current_price', 0.0)}</strong>\n\n"
                f"🎯 SİNYAL: <strong>{signal_dict.get('signal', 'Nötr')}</strong>\n"
                f"📊 Skor: <strong>{signal_dict.get('score', 0)}/100</strong>\n"
                f"🕐 Killzone: <strong>{signal_dict.get('killzone', 'Normal')}</strong>\n"
                f"🔒 Güven (nihai): <strong>%{int(final_conf * 100)}</strong>\n"
                f"🧩 Bileşenler: kapsama={confidence_components['coverage_weight']}, "
                f"tazelik={confidence_components['freshness_weight']}, uyum={confidence_components['agreement_weight']}, "
                f"volatilite={confidence_components['volatility_weight']}\n\n"
                f"🔥 Tetikleyenler:\n{signal_dict.get('triggers', 'Tetikleyici yok')}\n\n"
                f"⚠️ Bu bir yatırım tavsiyesi değildir."
            )
        else:
            trend = market_struct.get("trend", "Bilinmiyor")
            momentum = market_struct.get("momentum", "Nötr")
            volatility = market_struct.get("volatility", "Normal")
            volume_trend = market_struct.get("volume_trend", "Nötr")

            key_levels_list = market_struct.get("key_levels", []) or []
            key_levels = "\n".join([
                f"• {lvl.get('type', 'Seviye').capitalize()}: ${lvl.get('price', '—')}"
                for lvl in key_levels_list[:6]
            ]) or "Ana seviyeler hesaplanamadı"

            analysis = (
                f"🔍 {canonical} {timeframe.upper()} Grafik Analizi (ICT + SMC)\n"
                f"✅ <strong>Tam analiz başarıyla tamamlandı!</strong>\n"
                f"📡 Veri Kaynağı: <strong>{primary['name']}</strong> ({primary['length']} mum)\n"
                f"💰 Güncel Fiyat: <strong>${signal_dict.get('current_price', 0.0)}</strong>\n\n"
                f"🎯 SİNYAL: <strong>{signal_dict.get('signal', 'Nötr')}</strong>\n"
                f"📊 Güç Skoru: <strong>{signal_dict.get('score', 0)}/100</strong> ({signal_dict.get('strength', 'Nötr')})\n"
                f"🕐 Oturum: <strong>{signal_dict.get('killzone', 'Normal')}</strong>\n"
                f"🔒 Güven (nihai): <strong>%{int(final_conf * 100)}</strong>\n"
                f"🧩 Bileşenler: kapsama={confidence_components['coverage_weight']}, "
                f"tazelik={confidence_components['freshness_weight']}, uyum={confidence_components['agreement_weight']}, "
                f"volatilite={confidence_components['volatility_weight']}\n\n"
                f"📈 Piyasa Yapısı:\n"
                f"• Trend: <strong>{trend}</strong>\n"
                f"• Momentum: <strong>{momentum}</strong>\n"
                f"• Volatilite: <strong>{volatility}</strong>\n"
                f"• Hacim Trendi: <strong>{volume_trend}</strong>\n\n"
                f"🔑 Ana Seviyeler:\n{key_levels}\n\n"
                f"🔥 Tetikleyen Faktörler:\n{signal_dict.get('triggers', 'Tetikleyici tespit edilmedi')}\n\n"
                f"💡 Öneri: {signal_dict.get('recommended_action', 'Kendi analizinizi yapın')}\n\n"
                f"⚠️ Bu bir yatırım tavsiyesi değildir. Kendi araştırmanızı yapın ve risk yönetiminizi unutmayın."
            )

        # Kullanıcıya şeffaf kaynak metasını da dönelim
        sources_meta = []
        for src in sources_sorted:
            sources_meta.append({
                "name": src["name"],
                "length": src["length"],
                "freshness_minutes": round(_compute_freshness_minutes(src["last_ts"]), 2)
            })

        response_payload = {
            "analysis": analysis,
            "signal_data": signal_dict,
            "ensemble": {
                "per_exchange_signals": per_exchange_signals,
                "agreement": agreement_meta,
            },
            "sources": sources_meta,
            "success": True
        }
        return JSONResponse(response_payload)

    except Exception as e:
        try:
            logger.error(f"analyze_chart genel hatası: {e}")
        except Exception:
            pass
        return JSONResponse({
            "analysis": "❌ Sistem hatası oluştu. Lütfen tekrar deneyin.",
            "success": False
        }, status_code=500)
# ====================== GİRİŞ & HEALTH ======================
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse("""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Giriş Yap | ICT SMART PRO</title>
    <style>
        body {{background: linear-gradient(135deg, #0a0022, #1a0033, #000);color: #fff;font-family: sans-serif;min-height: 100vh;display: flex;align-items: center;justify-content: center;}}
        .login-box {{background: #000000cc;padding: 40px;border-radius: 20px;text-align: center;max-width: 400px;width: 90%;}}
        h2 {{color: #00dbde;margin-bottom: 30px;}}
        input {{width: 100%;padding: 15px;margin: 10px 0;border: none;border-radius: 12px;background: #333;color: #fff;font-size: 1.1rem;}}
        button {{width: 100%;padding: 15px;background: linear-gradient(45deg, #fc00ff, #00dbde);border: none;border-radius: 12px;color: #fff;font-weight: bold;font-size: 1.2rem;cursor: pointer;margin-top: 20px;}}
    </style>
</head>
<body>
    <div class="login-box">
        <h2>🔐 ICT SMART PRO</h2>
        <form method="post" action="/login">
            <input name="email" type="email" placeholder="E-posta adresiniz" required>
            <button type="submit">🚀 Giriş Yap</button>
        </form>
        <p style="margin-top:20px;color:#888">Demo için herhangi bir e-posta kullanabilirsiniz</p>
    </div>
</body>
</html>""")

@app.post("/login")
async def login(request: Request):
    form = await request.form()
    email = form.get("email", "").strip().lower()
    if "@" in email:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("user_email", email, max_age=2592000, httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login")

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

# ====================== RUN ======================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False)







