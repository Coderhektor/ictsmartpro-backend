# main.py — KUSURSUZ & RAILWAY-OPTİMİZE EDİLMİŞ
import base64
import logging
import io
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Dict, List
import json
import pandas as pd
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File
from core import (
    initialize, cleanup, single_subscribers, all_subscribers,
    pump_radar_subscribers, realtime_subscribers,
    shared_signals, active_strong_signals, top_gainers, last_update, rt_ticker,
    get_binance_client, signal_queue
)
from utils import all_usdt_symbols
from openai import OpenAI
import os
import hashlib

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("main")

# OpenAI client - opsiyonel
openai_client = None
if os.getenv("OPENAI_API_KEY"):
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ==================== ZİYARETÇİ SAYACI ====================
class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users = set()
        self.daily_stats = {}
        self.page_views = {}

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
            "page_views": self.page_views,
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


# ==================== APP LIFESPAN ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize()
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()


app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="3.1 - CLEAN & OPTIMIZED")


# ==================== MIDDLEWARE — ZİYARETÇİ SAYACI ====================
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
@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_signal(websocket: WebSocket, pair: str, timeframe: str):
    await websocket.accept()
    symbol = pair.upper().replace("/", "").replace("-", "").replace(" ", "").strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    channel = f"{symbol}:{timeframe}"

    if channel not in single_subscribers:
        single_subscribers[channel] = set()
    single_subscribers[channel].add(websocket)
    logger.info(f"📡 Yeni single subscriber: {channel} (Toplam: {len(single_subscribers[channel])})")

    sig = shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        try:
            await websocket.send_json(sig)
        except:
            pass

    try:
        while True:
            await asyncio.sleep(15)
            try:
                await websocket.send_json({"heartbeat": True, "time": datetime.now().strftime("%H:%M:%S")})
            except:
                break
    except WebSocketDisconnect:
        pass
    finally:
        if channel in single_subscribers:
            single_subscribers[channel].discard(websocket)
        logger.info(f"📡 Single subscriber ayrıldı: {channel} (Kalan: {len(single_subscribers[channel])})")


@app.websocket("/ws/all/{timeframe}")
async def ws_all(websocket: WebSocket, timeframe: str):
    supported = ["5m", "15m", "1h", "4h"]
    if timeframe not in supported:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    if timeframe not in all_subscribers:
        all_subscribers[timeframe] = set()
    all_subscribers[timeframe].add(websocket)
    logger.info(f"📡 Yeni all subscriber: {timeframe} (Toplam: {len(all_subscribers[timeframe])})")

    try:
        signals = active_strong_signals.get(timeframe, [])[:10]
        await websocket.send_json(signals)
    except:
        pass

    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"ping": True, "time": datetime.now().strftime("%H:%M:%S")})
    except WebSocketDisconnect:
        pass
    finally:
        if timeframe in all_subscribers:
            all_subscribers[timeframe].discard(websocket)
        logger.info(f"📡 All subscriber ayrıldı: {timeframe} (Kalan: {len(all_subscribers[timeframe])})")


@app.websocket("/ws/pump_radar")
async def ws_pump(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    logger.info(f"📡 Yeni pump radar subscriber (Toplam: {len(pump_radar_subscribers)})")

    try:
        await websocket.send_json({"top_gainers": top_gainers[:5], "last_update": last_update})
    except:
        pass

    try:
        while True:
            await asyncio.sleep(20)
            await websocket.send_json({"ping": True, "time": datetime.now().strftime("%H:%M:%S")})
    except WebSocketDisconnect:
        pass
    finally:
        pump_radar_subscribers.discard(websocket)
        logger.info(f"📡 Pump radar subscriber ayrıldı (Kalan: {len(pump_radar_subscribers)})")


@app.websocket("/ws/realtime_price")
async def ws_realtime_price(websocket: WebSocket):
    await websocket.accept()
    realtime_subscribers.add(websocket)
    logger.info(f"📡 Yeni realtime subscriber (Toplam: {len(realtime_subscribers)})")

    try:
        while True:
            await websocket.send_json({
                "tickers": rt_ticker.get("tickers", {}),
                "last_update": rt_ticker.get("last_update", "")
            })
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        pass
    finally:
        realtime_subscribers.discard(websocket)
        logger.info(f"📡 Realtime subscriber ayrıldı (Kalan: {len(realtime_subscribers)})")


# ==================== ANA SAYFA (/) ====================
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
body {{ background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: #fff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; min-height: 100vh; margin: 0; }}
.container {{ max-width: 1200px; margin: auto; padding: 20px; }}
h1 {{ font-size: clamp(2rem, 5vw, 4rem); text-align: center; background: linear-gradient(90deg, #00dbde, #fc00ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; animation: g 8s infinite; margin: 20px 0; }}
@keyframes g {{ 0% {{ background-position: 0%; }} 100% {{ background-position: 200%; }} }}
.update {{ text-align: center; color: #00ffff; margin: 20px; font-size: 1.2rem; padding: 10px; background: rgba(0,0,0,0.3); border-radius: 10px; }}
table {{ width: 100%; border-collapse: separate; border-spacing: 0 8px; margin: 20px 0; }}
th {{ background: rgba(255,255,255,0.1); padding: 12px 15px; font-size: 1rem; text-align: left; }}
tr {{ background: rgba(255,255,255,0.05); transition: transform 0.2s; }}
tr:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,255,255,0.2); }}
td {{ padding: 15px; }}
.green {{ color: #00ff88; font-weight: bold; }}
.red {{ color: #ff4444; font-weight: bold; }}
.btn {{ display: block; width: 90%; max-width: 500px; margin: 15px auto; padding: 18px 25px; font-size: 1.4rem; background: linear-gradient(45deg, #fc00ff, #00dbde); color: #fff; text-align: center; border-radius: 50px; text-decoration: none; font-weight: bold; box-shadow: 0 0 30px rgba(255,0,255,0.3); transition: all 0.3s; border: none; cursor: pointer; }}
.btn:hover {{ transform: scale(1.05); box-shadow: 0 0 50px rgba(255,0,255,0.5); }}
.user-info {{ position: fixed; top: 15px; left: 15px; background: rgba(0,0,0,0.7); padding: 10px 20px; border-radius: 20px; color: #00ff88; font-size: 0.9rem; z-index: 1000; }}
.loading {{ text-align: center; padding: 50px; color: #888; }}
</style>
</head>
<body>
<div class="user-info">👤 Hoş geldin, {user}</div>
{visitor_stats_html}
<div class="container">
<h1>🚀 ICT SMART PRO</h1>
<div class="update" id="update">⏳ Veriler yükleniyor...</div>
<table><thead><tr><th>SIRA</th><th>COİN</th><th>FİYAT</th><th>DEĞİŞİM</th></tr></thead>
<tbody id="table-body"><tr><td colspan="4" class="loading">📡 Pump radar verileri bekleniyor...</td></tr></tbody></table>
<a href="/signal" class="btn">📈 Tek Coin Sinyal + Grafik</a>
<a href="/signal/all" class="btn">🔥 Tüm Coinleri Tara</a>
<div style="text-align:center;margin-top:30px;color:#888;font-size:0.9rem;">⚡ Railway Optimized | 🚀 Real-time Signals</div>
</div>
<script>
const ws = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/pump_radar');
ws.onmessage = e => {{
    try {{
        const data = JSON.parse(e.data);
        if (data.ping) return;
        if (data.last_update) document.getElementById('update').innerHTML = `🔄 Son Güncelleme: <strong>${{data.last_update}}</strong>`;
        const tbody = document.getElementById('table-body');
        if (!data.top_gainers?.length) {{
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:40px;color:#ffd700">😴 Şu anda aktif pump yok</td></tr>';
            return;
        }}
        tbody.innerHTML = data.top_gainers.map((coin,i) => `<tr><td><strong>#${{i+1}}</strong></td><td><strong>${{coin.symbol}}</strong></td><td>$${{coin.price?.toFixed(4)}}</td><td class="${{coin.change > 0 ? 'green' : 'red'}}">${{coin.change > 0 ? '↗ +' : '↘ '}}${{Math.abs(coin.change).toFixed(2)}}%</td></tr>`).join('');
    }} catch (err) {{ console.error(err); }}
}};
ws.onerror = () => document.getElementById('update').innerHTML = '❌ Bağlantı hatası';
ws.onclose = () => setTimeout(() => location.reload(), 3000);
</script>
</body>
</html>"""
    return HTMLResponse(content=html_content)


# ==================== TEK COİN SAYFA (/signal) — ZAMAN DİLİMLERİ DÜZELTİLMİŞ! ====================
@app.get("/signal", response_class=HTMLResponse)
async def signal(request: Request):
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
:root {{ --primary: #00dbde; --secondary: #fc00ff; --success: #00ff88; --danger: #ff4444; }}
body {{ background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: #fff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; min-height: 100vh; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 20px; display: flex; flex-direction: column; gap: 25px; }}
h1 {{ font-size: clamp(2rem, 5vw, 3.5rem); text-align: center; background: linear-gradient(90deg, var(--primary), var(--secondary)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; animation: g 8s infinite; margin: 10px 0; }}
@keyframes g {{ 0% {{ background-position: 0%; }} 100% {{ background-position: 200%; }} }}
.controls {{ background: rgba(255,255,255,0.08); border-radius: 20px; padding: 30px; text-align: center; backdrop-filter: blur(10px); }}
input {{ padding: 16px 20px; font-size: 1.2rem; border: none; border-radius: 16px; background: rgba(255,255,255,0.12); color: #fff; width: 100%; max-width: 420px; text-align: center; }}
input:focus {{ outline: 3px solid var(--primary); background: rgba(255,255,255,0.18); }}

/* ✅ ESKİ, DÜŞEY, TEMİZ ZAMAN DİLİMİ BUTONLARI — TAM İSTENEN ŞEKİLDE */
.timeframe-title {{ color: #00ffff; font-size: 1.6rem; font-weight: bold; margin: 30px 0 20px; text-shadow: 0 0 10px rgba(0,255,255,0.5); }}
.timeframe-list {{ display: flex; flex-direction: column; gap: 12px; max-width: 220px; margin: 20px auto; }}
.tf-item {{ width: 100%; padding: 14px; font-size: 1.1rem; font-weight: 600; background: rgba(40,40,60,0.7); color: #e0e0ff; border: 1px solid rgba(100,100,255,0.3); border-radius: 12px; cursor: pointer; text-align: left; transition: all 0.25s ease; }}
.tf-item:hover {{ background: rgba(60,60,100,0.9); border-color: #00dbde; color: #ffffff; }}
.tf-item.active {{ background: linear-gradient(90deg, #00dbde, #fc00ff); color: white; font-weight: bold; border: none; box-shadow: 0 4px 12px rgba(0,219,222,0.4); }}

button {{ display: block; width: 90%; max-width: 500px; margin: 12px auto; padding: 18px; font-size: 1.2rem; background: linear-gradient(45deg, var(--secondary), var(--primary)); color: #fff; border: none; border-radius: 16px; cursor: pointer; transition: all 0.3s; font-weight: bold; }}
button:hover {{ transform: translateY(-4px); box-shadow: 0 10px 30px rgba(252,0,255,0.4); }}
#analyze-btn {{ background: linear-gradient(45deg, var(--primary), #ff00ff, var(--primary)); }}

#status {{ color: var(--primary); text-align: center; margin: 25px 0; font-size: 1.2rem; padding: 12px; border-radius: 12px; background: rgba(0,219,222,0.1); min-height: 50px; font-weight: bold; }}

#price-text {{ font-size: clamp(3.5rem, 10vw, 5rem); font-weight: bold; background: linear-gradient(90deg, var(--primary), var(--secondary)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 20px 0; }}

#signal-card {{ background: rgba(0,0,0,0.6); border-radius: 25px; padding: 35px; text-align: center; min-height: 180px; transition: all 0.3s; backdrop-filter: blur(5px); }}
#signal-card.green {{ border-left: 6px solid var(--success); box-shadow: 0 5px 20px rgba(0,255,136,0.3); }}
#signal-card.red {{ border-left: 6px solid var(--danger); box-shadow: 0 5px 20px rgba(255,68,68,0.3); }}
#signal-card.neutral {{ border-left: 6px solid #ffd700; }}

.chart-container {{ width: 100%; max-width: 1000px; margin: 40px auto; border-radius: 20px; overflow: hidden; box-shadow: 0 15px 40px rgba(0,219,222,0.3); background: rgba(10,0,34,0.7); height: 500px; }}
#tradingview_widget {{ height: 100%; width: 100%; }}

.user-info {{ position: fixed; top: 15px; left: 15px; background: rgba(0,0,0,0.7); padding: 12px 25px; border-radius: 25px; color: var(--success); font-size: 1rem; backdrop-filter: blur(8px); }}
</style>
</head>
<body>
<div class="user-info">👤 Hoş geldin, {user}</div>
{visitor_stats_html}

<div class="container">
<h1>📊 CANLI SİNYAL + GRAFİK</h1>

<div class="controls">
<input id="pair" placeholder="Coin (örn: BTCUSDT veya BTC)" value="BTCUSDT">

<div class="timeframe-title">⏱ ZAMAN DİLİMİ SEÇİN</div>
<div class="timeframe-list">
<button class="tf-item" data-tf="1m">1 Dakika</button>
<button class="tf-item" data-tf="3m">3 Dakika</button>
<button class="tf-item active" data-tf="5m">5 Dakika</button>
<button class="tf-item" data-tf="15m">15 Dakika</button>
<button class="tf-item" data-tf="30m">30 Dakika</button>
<button class="tf-item" data-tf="1h">1 Saat</button>
<button class="tf-item" data-tf="4h">4 Saat</button>
<button class="tf-item" data-tf="1d">1 Gün</button>
<button class="tf-item" data-tf="1w">1 Hafta</button>
</div>

<button onclick="connect()">📡 CANLI SİNYAL BAĞLANTISI KUR</button>
<button id="analyze-btn" onclick="analyzeChartWithAI()">🤖 GRAFİĞİ ANALİZ ET</button>
<div id="status">🎯 Lütfen coin seçip bağlantı kurun</div>
</div>

<div style="text-align:center;"><div id="price-text">$0.00</div><div style="color:#888;font-size:1rem;">Gerçek zamanlı fiyat</div></div>

<div id="signal-card" class="neutral">
<div id="signal-text">⏳ Sinyal bekleniyor</div>
<div id="signal-details">Canlı sinyal için yukarıdaki butona tıklayın.<br>ICT stratejisine göre analiz yapılacaktır.</div>
</div>

<div class="chart-container">
<div id="tradingview_widget"></div>
</div>

<div style="text-align:center;margin:20px;">
<a href="/" style="color:#00dbde;text-decoration:none;margin:0 15px;">🏠 Ana Sayfa</a>
<a href="/signal/all" style="color:#ff4444;text-decoration:none;margin:0 15px;">🔥 Tüm Coinler</a>
</div>
</div>

<script src="https://s3.tradingview.com/tv.js"></script>
<script>
let ws = null, priceWs = null, tvWidget = null, currentPrice = null, isConnected = false;
const tfMap = {{"1m":"1","3m":"3","5m":"5","15m":"15","30m":"30","1h":"60","4h":"240","1d":"D","1w":"W"}};

function getSymbol() {{
    let p = document.getElementById('pair').value.trim().toUpperCase();
    p = p.endsWith("USDT") ? p : p + "USDT";
    document.getElementById('pair').value = p;
    return "BINANCE:" + p;
}}

function createWidget() {{
    const symbol = getSymbol();
    const tf = document.querySelector('.tf-item.active').dataset.tf || "5m";
    const iv = tfMap[tf] || "5";

    if (tvWidget) {{ tvWidget.remove(); tvWidget = null; }}

    tvWidget = new TradingView.widget({{
        autosize: true,
        symbol: symbol,
        interval: iv,
        timezone: "Etc/UTC",
        theme: "dark",
        style: "1",
        locale: "tr",
        toolbar_bg: "#0a0022",
        enable_publishing: false,
        container_id: "tradingview_widget",
        studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies", "Volume@tv-basicstudies"]
    }});
}}

function updatePriceDisplay(price) {{
    if (!price || isNaN(price)) return;
    const fmt = price >= 1 ? price.toFixed(4) : price >= 0.01 ? price.toFixed(6) : price.toFixed(8);
    document.getElementById('price-text').textContent = "$" + fmt;
}}

function connectRealtimePrice() {{
    if (priceWs?.readyState === WebSocket.OPEN) return;
    const url = (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + "/ws/realtime_price";
    priceWs = new WebSocket(url);
    priceWs.onmessage = e => {{
        try {{
            const d = JSON.parse(e.data).tickers || {{}};
            const pair = getSymbol().replace("BINANCE:", "");
            const p = d[pair]?.price;
            if (p > 0) {{ currentPrice = p; updatePriceDisplay(p); }}
        }} catch (err) {{}}
    }};
    priceWs.onclose = () => setTimeout(connectRealtimePrice, 3000);
}}

document.querySelectorAll(".tf-item").forEach(btn => {{
    btn.addEventListener("click", function() {{
        document.querySelectorAll(".tf-item").forEach(b => b.classList.remove("active"));
        this.classList.add("active");
        createWidget();
        if (isConnected) {{ ws?.close(); connect(); }}
    }});
}});

function connect() {{
    if (isConnected) return alert("Zaten bağlısınız!");
    const symbol = getSymbol().replace("BINANCE:", "");
    const tf = document.querySelector(".tf-item.active").dataset.tf;

    document.getElementById("status").innerHTML = `Bağlantı kuruluyor: <strong>${{symbol}} ${{tf.toUpperCase()}}</strong>`;
    createWidget();

    const url = (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + `/ws/signal/${{symbol}}/${{tf}}`;
    ws = new WebSocket(url);

    ws.onopen = () => {{
        isConnected = true;
        document.getElementById("status").innerHTML = `✅ <strong>${{symbol}} ${{tf.toUpperCase()}}</strong> sinyal akışı başladı!`;
    }};

    ws.onmessage = e => {{
        try {{
            const data = JSON.parse(e.data);
            if (data.heartbeat) return;
            updateSignalDisplay(data, symbol.replace("USDT", ""));
        }} catch (err) {{}}
    }};

    ws.onclose = () => {{
        if (isConnected) {{
            document.getElementById("status").innerHTML = "🔌 Bağlantı kesildi. Tekrar bağlanmak için tıklayın.";
            isConnected = false;
        }}
    }};
}}

function updateSignalDisplay(data, base) {{
    const card = document.getElementById("signal-card");
    const text = document.getElementById("signal-text");
    const details = document.getElementById("signal-details");

    text.textContent = data.signal || "NÖTR";
    const price = data.current_price || currentPrice || 0;
    details.innerHTML = `<strong>${{base}}/USDT</strong><br>⚡ Skor: <strong>${{data.score || 50}}/100</strong><br>💰 Fiyat: <strong>$${{price.toFixed(4)}}</strong><br>🕒 Gönderim: ${{data.last_update || "şimdi"}}`;

    if (data.signal?.includes("ALIM") || data.signal?.includes("BUY")) {{
        card.className = "green";
    }} else if (data.signal?.includes("SATIM") || data.signal?.includes("SELL")) {{
        card.className = "red";
    }} else {{
        card.className = "neutral";
    }}

    if (data.current_price) {{
        currentPrice = data.current_price;
        updatePriceDisplay(currentPrice);
    }}
}}

async function analyzeChartWithAI() {{
    const btn = document.getElementById("analyze-btn");
    btn.disabled = true; btn.innerHTML = "Analiz ediliyor...";
    try {{
        const symbol = getSymbol().replace("BINANCE:", "");
        const tf = document.querySelector(".tf-item.active").dataset.tf;
        const res = await fetch("/api/analyze-chart", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ symbol, timeframe: tf }})
        }});
        const r = await res.json();
        alert(r.analysis || "Analiz alınamadı.");
    }} catch (e) {{
        alert("Bağlantı hatası.");
    }} finally {{
        btn.disabled = false; btn.innerHTML = "🤖 GRAFİĞİ ANALİZ ET";
    }}
}}

document.addEventListener("DOMContentLoaded", () => {{
    createWidget();
    connectRealtimePrice();
}});

window.addEventListener("beforeunload", () => {{
    ws?.close(); priceWs?.close();
}});
</script>
</body>
</html>"""
    return HTMLResponse(content=html_content)


# ==================== TÜM COİNLER (/signal/all) ====================
@app.get("/signal/all", response_class=HTMLResponse)
async def signal_all(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")

    visitor_stats_html = get_visitor_stats_html()
    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>TÜM COİNLER | ICT SMART PRO</title>
<style>
body {{ background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: #fff; font-family: sans-serif; padding: 20px; }}
h1 {{ text-align: center; background: linear-gradient(90deg, #00dbde, #fc00ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-size: 2.5rem; }}
.status {{ text-align: center; margin: 20px; color: #00ffff; }}
#signals {{ max-height: 70vh; overflow-y: auto; }}
.signal {{ background: rgba(255,255,255,0.05); padding: 15px; margin: 8px 0; border-radius: 10px; }}
.signal.buy {{ border-left: 4px solid #00ff88; }}
.signal.sell {{ border-left: 4px solid #ff4444; }}
</style>
</head>
<body>
<div class="user-info" style="position:fixed;top:15px;left:15px;background:rgba(0,0,0,0.7);padding:10px 20px;border-radius:20px;color:#00ff88;">👤 {user}</div>
{visitor_stats_html}

<h1>🔥 TÜM COİNLER - CANLI SİNYALLER</h1>
<div class="status" id="status">Bağlantı bekleniyor...</div>

<div id="signals">
<p style="text-align:center;color:#888;">Sinyal akışı başladığında burada görünecek.</p>
</div>

<script>
const tf = "5m";
const ws = new WebSocket((location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + `/ws/all/${{tf}}`);
ws.onopen = () => document.getElementById("status").textContent = "✅ Bağlantı kuruldu — sinyaller akıyor...";
ws.onmessage = e => {{
    try {{
        const signals = JSON.parse(e.data);
        if (Array.isArray(signals) && signals.length > 0) {{
            const html = signals.map(s => `<div class="signal ${{s.signal?.includes('ALIM') ? 'buy' : s.signal?.includes('SATIM') ? 'sell' : ''}}"><strong>${{s.pair}}</strong><br>${{s.signal}} | Skor: ${{s.score}}/100 | $${{s.current_price?.toFixed(4) || '?'}}</div>`).join("");
            document.getElementById("signals").innerHTML = html;
        }}
    }} catch (err) {{ console.error(err); }}
}};
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ==================== API ENDPOINTS ====================
@app.post("/api/analyze-chart")
async def analyze_chart(request: Request):
    try:
        body = await request.json()
        symbol = body.get("symbol", "BTCUSDT").upper()
        timeframe = body.get("timeframe", "5m")

        binance_client = get_binance_client()
        if not binance_client:
            return JSONResponse({"analysis": "❌ Binance bağlantısı yok.", "success": False})

        interval = timeframe
        ccxt_symbol = symbol.replace("USDT", "/USDT")
        klines = await binance_client.fetch_ohlcv(ccxt_symbol, timeframe=interval, limit=100)
        if len(klines) < 50:
            return JSONResponse({"analysis": f"❌ Yetersiz veri: {len(klines)} mum", "success": False})

        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        signal = None

        try:
            from indicators import generate_ict_signal
            signal = generate_ict_signal(df, symbol, timeframe)
        except Exception as e:
            logger.error(f"Sinyal üretilemedi: {e}")

        if not signal:
            signal = {{
                "pair": ccxt_symbol,
                "timeframe": timeframe,
                "current_price": round(df.iloc[-1]["close"], 4),
                "signal": "NÖTR",
                "score": 50,
                "last_update": datetime.utcnow().strftime("%H:%M:%S UTC"),
                "killzone": "Normal",
                "triggers": "İndikatör yüklenemedi",
                "strength": "DÜŞÜK"
            }}

        analysis = f"""
🔍 {symbol} {timeframe} Analiz
🎯 Sinyal: <strong>{signal['signal']}</strong>
📊 Skor: <strong>{signal['score']}/100</strong> ({signal['strength']})
💰 Fiyat: <strong>${signal['current_price']}</strong>
🕒 Güncelleme: {signal['last_update']}
⚠️ Bu bir yatırım tavsiyesi değildir.
        """.strip()

        return JSONResponse({{"analysis": analysis, "success": True}})

    except Exception as e:
        logger.exception("Analiz hatası")
        return JSONResponse({{"analysis": f"❌ Hata: {str(e)[:150]}", "success": False}}, status_code=500)


@app.get("/api/visitor-stats")
async def get_visitor_stats():
    return JSONResponse(visitor_counter.get_stats())


@app.get("/admin/visitor-dashboard", response_class=HTMLResponse)
async def visitor_dashboard(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")

    stats = visitor_counter.get_stats()
    rows = "".join(f"<tr><td>{p}</td><td>{v}</td></tr>" for p, v in stats["page_views"].items())
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>📊 İstatistikler</title><style>body{{background:#000;color:#fff;padding:20px;}} table{{width:100%;background:rgba(255,255,255,0.05);border-collapse:collapse;}} th,td{{padding:12px;text-align:left;border-bottom:1px solid #333;}} th{{color:#00dbde;}}</style></head>
<body>
<h1>Ziyaretçi İstatistikleri</h1>
<div><strong>Toplam:</strong> {stats['total_visits']} | <strong>Aktif:</strong> {stats['active_users']} | <strong>Bugün:</strong> {stats['today_visits']}<br><small>Son güncelleme: {stats['last_updated']}</small></div>
<table><thead><tr><th>Sayfa</th><th>Görüntülenme</th></tr></thead><tbody>{rows or "<tr><td colspan='2'>Veri yok</td></tr>"}</tbody></table>
<a href="/" style="color:#00dbde;">← Ana Sayfa</a>
</body></html>""")


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Giriş</title><style>body{background:#000;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;}</style></head>
<body><div style="text-align:center;background:rgba(0,0,0,0.7);padding:40px;border-radius:15px;">
<h2>ICT SMART PRO</h2>
<form method="post"><input name="email" placeholder="E-posta" required style="padding:12px;width:250px;margin:10px;border:1px solid #555;border-radius:8px;background:#111;color:#fff;">
<button type="submit" style="padding:12px 30px;background:linear-gradient(45deg,#fc00ff,#00dbde);border:none;border-radius:8px;color:white;cursor:pointer;">Giriş Yap</button>
</form></div></body></html>""")


@app.post("/login")
async def login_post(request: Request):
    form = await request.form()
    email = form.get("email", "").strip().lower()
    if "@" in email:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("user_email", email, max_age=2592000, httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "visitors": visitor_counter.get_stats(),
        "symbols": len(all_usdt_symbols) if all_usdt_symbols else 0,
        "signal_queue": signal_queue.qsize() if 'signal_queue' in globals() else 0
    }


# ==================== BAŞLATMA ====================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
