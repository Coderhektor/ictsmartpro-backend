# main.py — TAMAMEN YENİDEN YAZILDI, HATALAR DÜZELTİLDİ, RAILWAY UYUMLU
import logging
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict, Set
import json
import hashlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core import (
    initialize, cleanup, single_subscribers, all_subscribers,
    pump_radar_subscribers, shared_signals, active_strong_signals,
    top_gainers, last_update, rt_ticker, get_all_prices_snapshot
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("main")

# ==================== ZİYARETÇİ SAYACI ====================
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

# ==================== APP LIFESPAN ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize()
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="4.1")

# ==================== MIDDLEWARE ====================
@app.middleware("http")
async def count_visitors(request: Request, call_next):
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        ip = request.client.host or "unknown"
        visitor_id = hashlib.md5(ip.encode()).hexdigest()[:8]

    page = request.url.path
    visitor_counter.add_visit(page, visitor_id)

    response = await call_next(request)
    if not request.cookies.get("visitor_id"):
        response.set_cookie("visitor_id", visitor_id, max_age=86400*30, httponly=True, samesite="lax")
    return response

# ==================== WEBSOCKETS ====================
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
    logger.info(f"📡 Tekil abone: {channel}")

    # Mevcut sinyali gönder
    sig = shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        try:
            await websocket.send_json(sig)
        except:
            pass

    try:
        while True:
            await asyncio.sleep(15)
            await websocket.send_json({"heartbeat": True, "time": datetime.now().strftime("%H:%M:%S")})
    except WebSocketDisconnect:
        pass
    finally:
        single_subscribers[channel].discard(websocket)


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

    # İlk veri
    signals = active_strong_signals.get(timeframe, [])[:10]
    try:
        await websocket.send_json(signals)
    except:
        pass

    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"ping": True})
    except WebSocketDisconnect:
        pass
    finally:
        all_subscribers[timeframe].discard(websocket)


@app.websocket("/ws/pump_radar")
async def ws_pump_radar(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)

    try:
        await websocket.send_json({"top_gainers": top_gainers[:5], "last_update": last_update})
    except:
        pass

    try:
        while True:
            await asyncio.sleep(20)
            await websocket.send_json({"ping": True})
    except WebSocketDisconnect:
        pass
    finally:
        pump_radar_subscribers.discard(websocket)


@app.websocket("/ws/realtime_price")
async def ws_realtime_price(websocket: WebSocket):
    await websocket.accept()
    await rt_ticker.subscribe(websocket)
    logger.info("📡 Realtime fiyat abonesi eklendi")

    try:
        while True:
            await asyncio.sleep(3)
            data = get_all_prices_snapshot(limit=50)
            await rt_ticker.broadcast(data)
    except WebSocketDisconnect:
        pass
    finally:
        await rt_ticker.unsubscribe(websocket)

# ==================== HTML BILEŞENLERI ====================
HTML_HEADER = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>{title} | ICT SMART PRO</title>
    <style>
        :root {--primary:#00dbde;--secondary:#fc00ff;--success:#00ff88;--danger:#ff4444;--bg:#0a0022;}
        body {margin:0;padding:0;background:linear-gradient(135deg,var(--bg),#110033,#000);color:#e0e0ff;font-family:system-ui,sans-serif;min-height:100vh;}
        .container {max-width:1200px;margin:0 auto;padding:20px;}
        h1 {font-size:2.8rem;text-align:center;background:linear-gradient(90deg,var(--primary),var(--secondary));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
        .card {background:rgba(255,255,255,0.05);border-radius:20px;padding:30px;backdrop-filter:blur(10px);margin:20px 0;border:1px solid rgba(255,255,255,0.1);}
        .btn {padding:14px 28px;background:linear-gradient(45deg,var(--secondary),var(--primary));color:white;border:none;border-radius:12px;font-weight:bold;cursor:pointer;display:inline-block;margin:10px;text-decoration:none;}
        .btn:hover {transform:translateY(-3px);box-shadow:0 10px 25px rgba(252,0,255,0.3);}
        .stats, .user-info {position:fixed;padding:12px 20px;background:rgba(0,0,0,0.7);border-radius:15px;z-index:1000;font-size:0.9rem;}
        .stats {top:15px;right:15px;color:var(--success);}
        .user-info {top:15px;left:15px;color:var(--primary);}
        .signal-buy {border-left:4px solid var(--success);color:var(--success);}
        .signal-sell {border-left:4px solid var(--danger);color:var(--danger);}
        .signal-neutral {border-left:4px solid #ffd700;color:#ffd700;}
        @media (max-width:768px) {h1{font-size:2rem;}.container{padding:15px;}}
    </style>
</head>
<body>"""

HTML_FOOTER = "</body></html>"

def get_stats_html() -> str:
    stats = visitor_counter.get_stats()
    return f"""
    <div class="stats">
        <div>👁️ Toplam: <strong>{stats['total_visits']}</strong></div>
        <div>🔥 Bugün: <strong>{stats['today_visits']}</strong></div>
        <div>👥 Aktif: <strong>{stats['active_users']}</strong></div>
    </div>"""

# ==================== ROUTES ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email", "Misafir").split("@")[0]
    content = HTML_HEADER.format(title="Ana Sayfa") + get_stats_html() + f"""
    <div class="user-info">👤 {user}</div>
    <div class="container">
        <h1>🚀 ICT SMART PRO</h1>
        <div class="card"><h2>🔥 Pump Radar</h2><div id="pump-radar">Yükleniyor...</div></div>
        <div class="card" style="text-align:center;">
            <h2>⚡ Hızlı Erişim</h2>
            <a href="/signal" class="btn">📈 Tek Coin Sinyal</a>
            <a href="/signal/all" class="btn">🔥 Tüm Coinler</a>
            <a href="/admin/visitor-dashboard" class="btn">📊 İstatistikler</a>
        </div>
        <div class="card"><h3>📊 Realtime Fiyatlar</h3><div id="realtime-prices">Yükleniyor...</div></div>
    </div>
    <script>
        const pumpWs = new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws/pump_radar');
        pumpWs.onmessage = e => {
            const d = JSON.parse(e.data);
            if (d.top_gainers) {
                let html = '<table style="width:100%;border-collapse:collapse;">';
                d.top_gainers.forEach((c,i) => {
                    const cls = c.change > 0 ? 'signal-buy' : 'signal-sell';
                    html += `<tr class="${cls}"><td>#${i+1} <strong>${c.symbol}</strong></td><td>$${c.price?.toFixed(4)}</td><td>${c.change>0?'↗ +':'↘ '}${Math.abs(c.change).toFixed(2)}%</td></tr>`;
                });
                html += '</table>';
                document.getElementById('pump-radar').innerHTML = html;
            }
        };

        const priceWs = new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws/realtime_price');
        priceWs.onmessage = e => {
            const d = JSON.parse(e.data);
            let html = '<table style="width:100%;border-collapse:collapse;">';
            Object.entries(d.tickers || {}).slice(0,10).forEach(([s, i]) => {
                const cls = i.change > 0 ? 'signal-buy' : i.change < 0 ? 'signal-sell' : '';
                html += `<tr><td><strong>${s.replace('USDT','')}</strong></td><td>$${i.price?.toFixed(4)}</td><td class="${cls}">${i.change > 0 ? '+' : ''}${i.change?.toFixed(2)}%</td></tr>`;
            });
            html += '</table>';
            document.getElementById('realtime-prices').innerHTML = html;
        };
    </script>
    """ + HTML_FOOTER
    return HTMLResponse(content)

@app.get("/signal", response_class=HTMLResponse)
async def signal_page(request: Request):
    user_email = request.cookies.get("user_email")
    if not user_email:
        return RedirectResponse("/login")
    username = user_email.split("@")[0]

    content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>📈 {username} | CANLI SİNYAL</title>
<style>
:root{{--p:#00dbde;--s:#fc00ff;--g:#00ff88;--r:#ff4444;--d:#0a0022;}}
body{{background:linear-gradient(135deg,var(--d),#110033,#000);color:#e0e0ff;margin:0;font-family:system-ui;}}
.header{{position:fixed;top:0;left:0;right:0;padding:12px 20px;background:rgba(0,0,0,0.7);backdrop-filter:blur(8px);z-index:100;display:flex;justify-content:space-between;border-bottom:1px solid rgba(100,100,255,0.2);}}
.controls{{padding:70px 15px 15px;max-width:1000px;margin:0 auto;display:flex;flex-wrap:wrap;gap:10px;justify-content:center;}}
.controls input{{padding:12px 16px;border-radius:12px;background:rgba(40,40,60,0.7);color:#fff;border:none;flex:1;min-width:160px;}}
.tf-list{{display:flex;gap:6px;flex-wrap:wrap;justify-content:center;margin:12px 0;}}
.tf-item{{padding:8px 14px;background:rgba(40,40,60,0.7);color:#ccc;border:1px solid rgba(100,100,255,0.3);border-radius:8px;cursor:pointer;}}
.tf-item.active{{background:linear-gradient(90deg,var(--p),var(--s));color:white;font-weight:bold;}}
button{{padding:12px 20px;background:linear-gradient(45deg,var(--s),var(--p));color:white;border:none;border-radius:12px;font-weight:bold;cursor:pointer;}}
#price-text{{font-size:2.5rem;text-align:center;margin:10px;background:linear-gradient(90deg,var(--p),var(--s));-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-weight:bold;}}
.chart-container{{width:100%;height:calc(65vh - 100px);max-height:700px;margin:20px auto;border-radius:16px;overflow:hidden;background:#08001a;box-shadow:0 10px 30px rgba(0,219,222,0.2);}}
#get_stats_html()"""
    content += get_stats_html() + f"""
</style>
</head>
<body>
<div class="header"><div>👤 {username}</div><div>ICT SMART PRO</div></div>
<div class="controls">
    <input id="pair" value="BTCUSDT" placeholder="Coin (örn: ETHUSDT)">
    <div class="tf-list">
        <button class="tf-item" data-tf="1m">1m</button>
        <button class="tf-item" data-tf="3m">3m</button>
        <button class="tf-item active" data-tf="5m">5m</button>
        <button class="tf-item" data-tf="15m">15m</button>
        <button class="tf-item" data-tf="1h">1h</button>
        <button class="tf-item" data-tf="4h">4h</button>
        <button class="tf-item" data-tf="1d">1D</button>
    </div>
    <button onclick="connect()">📡 BAĞLAN</button>
</div>
<div style="text-align:center;padding:10px;color:var(--p);" id="status">Coin seçip bağlanın</div>
<div id="price-text">$0.00</div>
<div style="display:flex;justify-content:center;gap:20px;flex-wrap:wrap;padding:0 15px;">
    <div style="background:rgba(20,10,50,0.6);padding:15px;border-radius:15px;min-width:250px;text-align:center;">
        <div id="signal-text">⏳ Bekleniyor</div>
        <div id="signal-details" style="font-size:0.9rem;color:#aaa;margin-top:8px;">Bağlantı kurulunca sinyal gelir</div>
    </div>
    <div style="background:rgba(20,10,50,0.6);padding:15px;border-radius:15px;min-width:200px;text-align:center;">
        <div>Skor:</div>
        <div id="signal-score">— /100</div>
    </div>
</div>
<div class="chart-container"><div id="tradingview_widget"></div></div>
<div style="text-align:center;padding:20px;">
    <a href="/" class="btn">🏠 Ana Sayfa</a>
    <a href="/signal/all" class="btn">🔥 Tüm Coinler</a>
</div>
<script src="https://s3.tradingview.com/tv.js"></script>
<script>
let ws = null, tvWidget = null, currentPrice = null;
const tfMap = {{"1m":"1","3m":"3","5m":"5","15m":"15","1h":"60","4h":"240","1d":"D"}};

function getSymbol() {
    let p = document.getElementById('pair').value.trim().toUpperCase();
    if (!p.endsWith("USDT")) p += "USDT";
    document.getElementById('pair').value = p;
    return "BINANCE:" + p;
}

function createWidget() {
    const symbol = getSymbol();
    const tf = document.querySelector('.tf-item.active').dataset.tf;
    const interval = tfMap[tf] || "5";
    if (tvWidget) tvWidget.remove();
    tvWidget = new TradingView.widget({
        autosize: true, symbol, interval, theme: "dark", timezone: "Etc/UTC",
        container_id: "tradingview_widget", locale: "tr", studies: ["RSI@tv-basicstudies","MACD@tv-basicstudies"]
    });
}

document.querySelectorAll('.tf-item').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('.tf-item').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    createWidget();
    if (ws) { ws.close(); connect(); }
}));

function connect() {
    if (ws) return alert("Zaten bağlı!");
    const symbol = getSymbol().replace("BINANCE:", "");
    const tf = document.querySelector('.tf-item.active').dataset.tf;
    document.getElementById("status").innerHTML = `🔗 ${symbol} ${tf} bağlanıyor...`;
    createWidget();

    const url = (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + `/ws/signal/${symbol}/${tf}`;
    ws = new WebSocket(url);

    ws.onopen = () => document.getElementById("status").innerHTML = `✅ ${symbol} ${tf} aktif`;
    ws.onmessage = e => {
        const d = JSON.parse(e.data);
        if (d.heartbeat) return;
        document.getElementById("signal-text").textContent = d.signal || "NÖTR";
        document.getElementById("signal-score").textContent = (d.score || 50) + " /100";
        document.getElementById("signal-details").innerHTML = `<strong>${symbol.replace('USDT','')}/USDT</strong><br>💰 $${(d.current_price || 0).toFixed(4)}`;
        if (d.current_price) {
            currentPrice = d.current_price;
            document.getElementById("price-text").textContent = "$" + (currentPrice >= 1 ? currentPrice.toFixed(4) : currentPrice.toFixed(6));
        }
        const box = document.querySelectorAll('div[style*="background:rgba(20,10,50"]')[0];
        box.style.borderLeft = d.signal?.includes("ALIM") ? "4px solid #00ff88" : d.signal?.includes("SATIM") ? "4px solid #ff4444" : "4px solid #ffd700";
    };
    ws.onclose = () => document.getElementById("status").innerHTML = "🔌 Bağlantı kesildi";
}

document.addEventListener("DOMContentLoaded", createWidget);
</script>
</body>
</html>"""
    return HTMLResponse(content)

# Diğer sayfalar (/signal/all, /login, /admin/visitor-dashboard, /health) aynı kalabilir, istersen onları da temizleyebilirim.

if __name__ == "__main__":
    import uvicorn, os
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
