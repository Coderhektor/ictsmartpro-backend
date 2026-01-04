# main.py — RAILWAY'DE %100 ÇALIŞAN SON VERSİYON
import logging
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict
import json
import hashlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

# DİKKAT: realtime_subscribers KALDIRILDI!
from core import (
    initialize, cleanup,
    single_subscribers, all_subscribers, pump_radar_subscribers,
    shared_signals, active_strong_signals, top_gainers, last_update,
    rt_ticker, get_binance_client, get_all_prices_snapshot
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("main")

# ==================== ZİYARETÇİ SAYACI ====================
class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users = set()
        self.daily_stats = {}
        self.page_views = {}

    def add_visit(self, page: str, user_id: str = None):
        self.total_visits += 1
        self.page_views[page] = self.page_views.get(page, 0) + 1
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self.daily_stats:
            self.daily_stats[today] = {"visits": 0, "unique": set()}
        self.daily_stats[today]["visits"] += 1
        if user_id:
            self.active_users.add(user_id)
            self.daily_stats[today]["unique"].add(user_id)

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
    <div style="position:fixed;top:15px;right:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:0.9rem;z-index:1000;">
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

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="7.0 - Railway Ready")

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

    signals = active_strong_signals.get(timeframe, [])[:15]
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
        await websocket.send_json({"top_gainers": top_gainers[:8], "last_update": last_update})
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
    await rt_ticker.subscribe(websocket)  # rt_ticker kullanıyoruz

    try:
        while True:
            await asyncio.sleep(3)
            data = get_all_prices_snapshot(limit=50)
            await rt_ticker.broadcast(data)
    except WebSocketDisconnect:
        pass
    finally:
        await rt_ticker.unsubscribe(websocket)

# ==================== ANA SAYFA ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email", "Misafir").split("@")[0]
    stats_html = get_visitor_stats_html()

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>ICT SMART PRO</title>
    <style>
        body {{background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;font-family:system-ui;margin:0;min-height:100vh;display:flex;flex-direction:column;}}
        .container {{max-width:1200px;margin:auto;padding:20px;flex:1;}}
        h1 {{font-size:clamp(2rem,5vw,4rem);text-align:center;background:linear-gradient(90deg,#00dbde,#fc00ff,#00dbde);-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:a 8s infinite linear;}}
        @keyframes a {{0%{{background-position:0%}}100%{{background-position:200%}}}}
        .btn {{display:block;width:90%;max-width:500px;margin:20px auto;padding:18px;background:linear-gradient(45deg,#fc00ff,#00dbde);color:#fff;text-align:center;border-radius:50px;font-weight:bold;text-decoration:none;}}
        .btn:hover {{transform:scale(1.05);box-shadow:0 0 60px rgba(252,0,255,0.5);}}
        .user-info {{position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;z-index:1000;}}
        table {{width:100%;border-collapse:separate;border-spacing:0 10px;}}
        th {{background:rgba(255,255,255,0.1);padding:15px;}}
        td {{padding:15px;background:rgba(255,255,255,0.05);}}
        .green {{color:#00ff88;font-weight:bold;}}
        .red {{color:#ff4444;font-weight:bold;}}
    </style>
</head>
<body>
    <div class="user-info">👤 Hoş geldin, {user}</div>
    {stats_html}
    <div class="container">
        <h1>🚀 ICT SMART PRO</h1>
        <div id="update" style="text-align:center;color:#00ffff;padding:15px;background:#00000066;border-radius:10px;">⏳ Pump radar yükleniyor...</div>
        <table>
            <thead><tr><th>#</th><th>COİN</th><th>FİYAT</th><th>DEĞİŞİM</th></tr></thead>
            <tbody id="pump-body"><tr><td colspan="4" style="text-align:center;padding:50px;color:#888;">Veriler yükleniyor...</td></tr></tbody>
        </table>
        <a href="/signal" class="btn">📈 Tek Coin Sinyal + Grafik</a>
        <a href="/signal/all" class="btn">🔥 Tüm Coinler</a>
    </div>
    <script>
        const ws = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/pump_radar');
        ws.onmessage = function(e) {{
            const data = JSON.parse(e.data);
            if (data.ping) return;
            if (data.last_update) document.getElementById('update').innerHTML = '🔄 Son Güncelleme: <strong>' + data.last_update + '</strong>';
            const tbody = document.getElementById('pump-body');
            if (!data.top_gainers || data.top_gainers.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:50px;color:#ffd700;">😴 Şu anda aktif pump yok</td></tr>';
                return;
            }}
            tbody.innerHTML = data.top_gainers.map((c, i) => `
                <tr>
                    <td><strong>#${{i+1}}</strong></td>
                    <td><strong>${{c.symbol}}</strong></td>
                    <td>$${{c.price.toFixed(4)}}</td>
                    <td class="${{c.change > 0 ? 'green' : 'red'}}">${{c.change > 0 ? '↗ +' : '↘ '}}${{Math.abs(c.change).toFixed(2)}}%</td>
                </tr>
            `).join('');
        }};
        ws.onclose = function() {{ setTimeout(() => location.reload(), 5000); }};
    </script>
</body>
</html>"""
    return HTMLResponse(html)

# ==================== DİĞER SAYFALAR (login, health vs.) ====================
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse("""<!DOCTYPE html>
<html lang="tr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Giriş | ICT SMART PRO</title>
<style>
    body{{background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;font-family:system-ui;}}
    .box{{background:rgba(0,0,0,0.7);padding:40px;border-radius:20px;width:90%;max-width:400px;text-align:center;backdrop-filter:blur(10px);}}
    input{{width:100%;padding:16px;margin:15px 0;border:none;border-radius:12px;background:rgba(255,255,255,0.1);color:#fff;font-size:1.1rem;}}
    button{{width:100%;padding:16px;background:linear-gradient(45deg,#fc00ff,#00dbde);border:none;border-radius:12px;color:#fff;font-weight:bold;font-size:1.2rem;cursor:pointer;}}
</style>
</head>
<body>
    <div class="box">
        <h2>🔐 ICT SMART PRO</h2>
        <form method="post" action="/login">
            <input name="email" type="email" placeholder="E-posta" required>
            <button type="submit">🚀 Giriş Yap</button>
        </form>
        <p style="margin-top:20px;color:#888;font-size:0.9rem;">Herhangi bir e-posta ile giriş yapabilirsiniz</p>
    </div>
</body>
</html>""")

@app.post("/login")
async def login_post(email: str = Form(...)):
    if "@" in email:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("user_email", email.strip().lower(), max_age=2592000, httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login")

@app.get("/health")
async def health():
    return JSONResponse({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "visitors": visitor_counter.get_stats()["total_visits"]
    })

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
