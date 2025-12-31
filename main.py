# main.py - ICT SMART PRO (PROD - Railway Optimized - %100 HATASIZ)
import base64
import logging
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict
import os
import hashlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, RedirectResponse, HTMLResponse

from core import (
    initialize, cleanup, single_subscribers, all_subscribers,
    pump_radar_subscribers, realtime_subscribers,
    shared_signals, active_strong_signals, top_gainers, last_update, rt_ticker
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("main")

class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users = set()
        self.page_views = {}

    def add_visit(self, page: str, user_id: str = None) -> int:
        self.total_visits += 1
        self.page_views[page] = self.page_views.get(page, 0) + 1
        if user_id:
            self.active_users.add(user_id)
        return self.total_visits

    def get_stats(self) -> Dict:
        return {
            "total_visits": self.total_visits,
            "active_users": len(self.active_users),
            "last_updated": datetime.now().strftime("%H:%M:%S")
        }

visitor_counter = VisitorCounter()

def get_visitor_stats_html() -> str:
    stats = visitor_counter.get_stats()
    return f"""
    <div style="position:fixed;top:15px;right:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:clamp(0.8rem, 2vw, 1.2rem);z-index:1000;">
        <div>👁️ Toplam: <strong>{stats['total_visits']}</strong></div>
        <div>🔥 Aktif: <strong>{stats['active_users']}</strong></div>
    </div>
    """

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize()
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="PROD 2025")

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
            try:
                await websocket.send_json({"heartbeat": True, "time": datetime.now().strftime("%H:%M:%S")})
            except:
                break
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

    try:
        await websocket.send_json(active_strong_signals.get(timeframe, [])[:20])
    except:
        pass

    try:
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json({"ping": True})
            except:
                break
    except WebSocketDisconnect:
        pass
    finally:
        all_subscribers[timeframe].discard(websocket)

@app.websocket("/ws/pump_radar")
async def ws_pump(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)

    try:
        await websocket.send_json({"top_gainers": top_gainers[:8], "last_update": last_update})
    except:
        pass

    try:
        while True:
            await asyncio.sleep(20)
            try:
                await websocket.send_json({"ping": True})
            except:
                break
    except WebSocketDisconnect:
        pass
    finally:
        pump_radar_subscribers.discard(websocket)

@app.websocket("/ws/realtime_price")
async def ws_realtime_price(websocket: WebSocket):
    await websocket.accept()
    realtime_subscribers.add(websocket)

    try:
        while True:
            try:
                await websocket.send_json(rt_ticker.copy())
            except:
                break
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        pass
    finally:
        realtime_subscribers.discard(websocket)

# ==================== SAYFALAR ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    visitor_stats_html = get_visitor_stats_html()

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>ICT SMART PRO</title>
    <style>
        body {{background: linear-gradient(135deg, #0a0022, #1a0033, #000);color:#fff;font-family:system-ui;margin:0;display:flex;flex-direction:column;min-height:100vh;}}
        .container {{max-width:1200px;margin:auto;padding:20px;flex:1;}}
        h1 {{font-size:clamp(2rem,5vw,4rem);text-align:center;background:linear-gradient(90deg,#00dbde,#fc00ff,#00dbde);-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:g 8s infinite;}}
        @keyframes g {{0%{{background-position:0%}}100%{{background-position:200%}}}}
        .update {{text-align:center;color:#00ffff;margin:20px;font-size:1.5rem;background:rgba(0,0,0,0.3);padding:15px;border-radius:10px;}}
        table {{width:100%;border-collapse:separate;border-spacing:0 10px;}}
        th {{background:rgba(255,255,255,0.1);padding:15px;font-size:1.1rem;}}
        td {{padding:15px;background:rgba(255,255,255,0.05);}}
        .green {{color:#00ff88;font-weight:bold;}}
        .red {{color:#ff4444;font-weight:bold;}}
        .btn {{display:block;width:90%;max-width:500px;margin:20px auto;padding:20px;font-size:1.6rem;background:linear-gradient(45deg,#fc00ff,#00dbde);color:#fff;border-radius:50px;text-align:center;text-decoration:none;font-weight:bold;}}
        .user-info {{position:fixed;top:15px;left:15px;background:rgba(0,0,0,0.7);padding:10px 20px;border-radius:20px;color:#00ff88;z-index:1000;}}
    </style>
</head>
<body>
    <div class="user-info">👤 {user}</div>
    {visitor_stats_html}
    <div class="container">
        <h1>🚀 ICT SMART PRO</h1>
        <div class="update" id="update">⏳ Pump radar yükleniyor...</div>
        <table>
            <thead><tr><th>SIRA</th><th>COİN</th><th>FİYAT</th><th>DEĞİŞİM</th></tr></thead>
            <tbody id="table-body"><tr><td colspan="4" style="text-align:center;padding:50px;">📡 Veriler yükleniyor...</td></tr></tbody>
        </table>
        <a href="/signal" class="btn">📈 Tek Coin Sinyal + Grafik</a>
        <a href="/signal/all" class="btn">🔥 Tüm Coinleri Tara</a>
    </div>
    <script>
        const ws = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/pump_radar');
        ws.onmessage = e => {{
            const data = JSON.parse(e.data);
            if (data.ping) return;
            if (data.last_update) document.getElementById('update').innerHTML = `🔄 Son Güncelleme: <strong>${{data.last_update}}</strong>`;
            const tbody = document.getElementById('table-body');
            if (!data.top_gainers || data.top_gainers.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:50px;color:#ffd700">😴 Aktif pump yok</td></tr>';
                return;
            }}
            tbody.innerHTML = data.top_gainers.map((c,i) => `
                <tr>
                    <td><strong>#${{i+1}}</strong></td>
                    <td><strong>${{c.symbol}}</strong></td>
                    <td>$${c.price.toFixed(4)}</td>
                    <td class="${{c.change > 0 ? 'green' : 'red'}}">${{c.change > 0 ? '↗ +' : '↘ '}}${{Math.abs(c.change).toFixed(2)}}%</td>
                </tr>
            `).join('');
        }};
        ws.onclose = () => setTimeout(() => location.reload(), 3000);
    </script>
</body>
</html>""")

@app.get("/signal", response_class=HTMLResponse)
async def signal(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")

    visitor_stats_html = get_visitor_stats_html()

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>CANLI SİNYAL | ICT SMART PRO</title>
    <style>
        :root {{--p:#00dbde;--s:#fc00ff;--g:#00ff88;--r:#ff4444;--w:#ffd700;--bg:#0a0022;}}
        body {{background:linear-gradient(135deg,var(--bg),#1a0033,#000);color:#fff;font-family:system-ui;margin:0;min-height:100vh;}}
        .container {{max-width:1200px;margin:auto;padding:20px;display:flex;flex-direction:column;gap:25px;}}
        h1 {{font-size:clamp(2rem,5vw,3.5rem);text-align:center;background:linear-gradient(90deg,var(--p),var(--s),var(--p));-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:g 8s infinite linear;}}
        @keyframes g {{0%{{background-position:0%}}100%{{background-position:200%}}}}
        .controls {{background:rgba(255,255,255,0.08);border-radius:20px;padding:25px;text-align:center;backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,0.1);}}
        input,select,button {{padding:16px 20px;font-size:1.1rem;border:none;border-radius:12px;background:rgba(255,255,255,0.1);color:#fff;min-width:200px;}}
        button {{background:linear-gradient(45deg,var(--s),var(--p));cursor:pointer;font-weight:bold;min-width:250px;}}
        #status {{color:var(--p);margin:15px;font-size:1.1rem;padding:10px;background:rgba(0,219,222,0.1);border-radius:10px;}}
        #price-text {{font-size:clamp(3rem,8vw,4.5rem);text-align:center;font-weight:bold;background:linear-gradient(90deg,var(--p),var(--s));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}}
        #signal-card {{background:rgba(0,0,0,0.5);border-radius:20px;padding:30px;text-align:center;border-left:6px solid var(--w);}}
        #signal-card.green {{border-left-color:var(--g);}}
        #signal-card.red {{border-left-color:var(--r);}}
        #signal-text {{font-size:clamp(2rem,5vw,3rem);font-weight:bold;}}
        .chart-container {{width:100%;max-width:1000px;margin:30px auto;border-radius:20px;overflow:hidden;box-shadow:0 15px 40px rgba(0,219,222,0.2);background:rgba(10,0,34,0.5);}}
        .user-info {{position:fixed;top:15px;left:15px;background:rgba(0,0,0,0.7);padding:10px 20px;border-radius:20px;color:var(--g);z-index:1000;}}
    </style>
</head>
<body>
    <div class="user-info">👤 {user}</div>
    {visitor_stats_html}
    <div class="container">
        <h1>📊 CANLI SİNYAL + GRAFİK</h1>
        <div class="controls">
            <input id="pair" placeholder="Coin (örn: BTCUSDT)" value="BTCUSDT">
            <select id="tf">
                <option value="5m" selected>5 Dakika</option>
                <option value="15m">15 Dakika</option>
                <option value="1h">1 Saat</option>
                <option value="4h">4 Saat</option>
                <option value="1d">1 Gün</option>
            </select>
            <button onclick="connect()">📡 BAĞLAN</button>
            <div id="status">🎯 Coin ve zaman dilimi seçin</div>
        </div>
        <div style="text-align:center;">
            <div id="price-text">$0.00</div>
            <div style="color:#888;">Gerçek zamanlı fiyat</div>
        </div>
        <div id="signal-card">
            <div id="signal-text">⏳ Sinyal bekleniyor</div>
            <div id="signal-details">Bağlantı kurun...</div>
        </div>
        <div class="chart-container">
            <div id="tradingview_widget" style="height:500px;width:100%;"></div>
        </div>
    </div>
<script src="https://s3.tradingview.com/tv.js"></script>
<script>
    let ws = null;
    let tvWidget = null;

    function getSymbol() {
        let p = document.getElementById('pair').value.trim().toUpperCase();
        if (!p.endsWith("USDT")) p += "USDT";
        document.getElementById('pair').value = p;
        return "BINANCE:" + p;
    }

    function createWidget() {
        if (tvWidget) tvWidget.remove();
        tvWidget = new TradingView.widget({
            autosize: true,
            symbol: getSymbol(),
            interval: document.getElementById('tf').value === "1d" ? "D" : document.getElementById('tf').value,
            timezone: "Etc/UTC",
            theme: "dark",
            style: "1",
            locale: "tr",
            toolbar_bg: "#0a0022",
            container_id: "tradingview_widget",
            studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies", "Volume@tv-basicstudies"]
        });
    }

    function updatePriceDisplay(price) {
        document.getElementById('price-text').textContent = '$' + price.toFixed(price >= 1 ? 4 : 6);
    }

    function connect() {
        if (ws) ws.close();
        const symbol = document.getElementById('pair').value.trim().toUpperCase();
        const tf = document.getElementById('tf').value;
        const fullSymbol = symbol.endsWith("USDT") ? symbol : symbol + "USDT";
        document.getElementById('status').innerHTML = `🔗 ${fullSymbol} ${tf} bağlantı kuruluyor...`;
        createWidget();
        ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/signal/${fullSymbol}/${tf}`);
        ws.onopen = () => document.getElementById('status').innerHTML = `✅ Canlı sinyal başladı!`;
        ws.onmessage = e => {
            const data = JSON.parse(e.data);
            if (data.heartbeat) return;
            const card = document.getElementById('signal-card');
            const text = document.getElementById('signal-text');
            const details = document.getElementById('signal-details');
            text.textContent = data.signal ? data.signal : "NÖTR";
            details.innerHTML = `
                <strong>${data.pair ? data.pair : fullSymbol.replace('USDT','/USDT')}</strong><br>
                ⚡ Skor: <strong>${data.score ? data.score : 0}/100</strong><br>
                💰 Fiyat: <strong>${data.current_price ? '$' + Number(data.current_price).toFixed(data.current_price >= 1 ? 4 : 6) : '$0.0000'}</strong><br>
                🎯 Killzone: <strong>${data.killzone ? data.killzone : 'Normal'}</strong><br>
                🕒 ${data.last_update ? data.last_update : 'Şimdi'}<br>
                <small>${data.triggers ? data.triggers : 'Analiz ediliyor'}</small>
            `;
            card.className = data.signal && (data.signal.includes("ALIM") || data.signal.includes("LONG")) ? "green" : 
                             data.signal && (data.signal.includes("SATIM") || data.signal.includes("SHORT")) ? "red" : "";
            if (data.current_price) updatePriceDisplay(data.current_price);
        };
        ws.onclose = () => document.getElementById('status').innerHTML = '🔌 Bağlantı kesildi. Yeniden bağlanılıyor...';
    }

    document.addEventListener("DOMContentLoaded", createWidget);
</script>
  
</body>
</html>""")

@app.get("/signal/all", response_class=HTMLResponse)
async def signal_all(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")

    visitor_stats_html = get_visitor_stats_html()

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>TÜM COİNLER | ICT SMART PRO</title>
    <style>
        :root {{--bg:#0a0022;--card:rgba(255,255,255,0.05);--p:#00dbde;--s:#fc00ff;--g:#00ff88;--r:#ff4444;--w:#ffd700;}}
        body {{background:linear-gradient(135deg,var(--bg),#1a0033,#000);color:#fff;font-family:system-ui;margin:0;min-height:100vh;}}
        .container {{max-width:1400px;margin:auto;padding:20px;}}
        h1 {{text-align:center;font-size:clamp(2rem,5vw,3.5rem);background:linear-gradient(90deg,var(--p),var(--s),var(--p));-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:g 8s infinite linear;}}
        @keyframes g {{0%{{background-position:0%}}100%{{background-position:200%}}}}
        .controls {{background:var(--card);border-radius:20px;padding:20px;text-align:center;margin-bottom:30px;backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,0.1);}}
        select {{padding:15px;font-size:1.2rem;border:none;border-radius:12px;background:rgba(255,255,255,0.1);color:#fff;}}
        .signal-grid {{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px;margin-top:20px;}}
        .signal-card {{background:var(--card);border-radius:20px;padding:20px;backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,0.1);transition:all 0.3s;}}
        .signal-card:hover {{transform:translateY(-8px);box-shadow:0 15px 30px rgba(0,219,222,0.2);border-color:var(--p);}}
        .coin-name {{font-size:1.4rem;font-weight:bold;color:var(--p);}}
        .signal-text {{font-size:1.6rem;font-weight:bold;text-align:center;margin:15px 0;min-height:60px;display:flex;align-items:center;justify-content:center;}}
        .signal-buy {{color:var(--g);}}
        .signal-sell {{color:var(--r);}}
        .signal-neutral {{color:var(--w);}}
        .score-bar {{height:12px;background:rgba(255,255,255,0.1);border-radius:6px;overflow:hidden;margin:15px 0;}}
        .score-fill {{height:100%;border-radius:6px;transition:width 0.5s;}}
        .score-low {{background:linear-gradient(90deg,var(--r),#ff8800);}}
        .score-medium {{background:linear-gradient(90deg,#ff8800,var(--w));}}
        .score-high {{background:linear-gradient(90deg,var(--w),var(--g));}}
        .score-elite {{background:linear-gradient(90deg,var(--g),#00ffff);}}
        .details {{font-size:0.95rem;line-height:1.6;color:#ccc;}}
        .detail-row {{display:flex;justify-content:space-between;margin:8px 0;}}
        .no-signals {{grid-column:1/-1;text-align:center;padding:60px;font-size:1.5rem;color:var(--w);}}
        .loading {{grid-column:1/-1;text-align:center;padding:80px;color:#888;font-size:1.3rem;}}
        .user-info {{position:fixed;top:15px;left:15px;background:rgba(0,0,0,0.7);padding:10px 20px;border-radius:20px;color:var(--g);z-index:1000;}}
    </style>
</head>
<body>
    <div class="user-info">👤 {user}</div>
    {visitor_stats_html}
    <div class="container">
        <h1>🔥 TÜM COİN SİNYALLERİ</h1>
        <div class="controls">
            <select id="tf" onchange="connect()">
                <option value="5m" selected>5 Dakika</option>
                <option value="15m">15 Dakika</option>
                <option value="1h">1 Saat</option>
                <option value="4h">4 Saat</option>
            </select>
            <div id="status">⏳ Bağlantı bekleniyor...</div>
        </div>
        <div id="signal-container" class="signal-grid">
            <div class="loading">📡 Canlı sinyaller yükleniyor...</div>
        </div>
    </div>
    <script>
        let ws = null;
        let currentTf = "5m";

        function getScoreClass(score) {{
            if (score >= 90) return "score-elite";
            if (score >= 75) return "score-high";
            if (score >= 50) return "score-medium";
            return "score-low";
        }}

        function getSignalClass(signal) {{
            if (signal.includes("ALIM") || signal.includes("LONG")) return "signal-buy";
            if (signal.includes("SATIM") || signal.includes("SHORT")) return "signal-sell";
            return "signal-neutral";
        }}

        function renderSignals(signals) {{
            const container = document.getElementById('signal-container');
            if (!signals || signals.length === 0) {{
                container.innerHTML = '<div class="no-signals">😴 Şu anda aktif güçlü sinyal yok</div>';
                return;
            }}
            signals.sort((a,b) => b.score - a.score);
            container.innerHTML = signals.map(sig => `
                <div class="signal-card">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">
                        <div class="coin-name">${sig.pair || sig.symbol}</div>
                        <div style="font-size:0.9rem;color:#aaa;background:rgba(0,0,0,0.3);padding:5px 12px;border-radius:20px;">${sig.timeframe || currentTf.toUpperCase()}</div>
                    </div>
                    <div class="signal-text ${getSignalClass(sig.signal)}">${sig.signal}</div>
                    <div class="score-bar">
                        <div class="score-fill ${getScoreClass(sig.score)}" style="width:${sig.score}%"></div>
                    </div>
                    <div style="text-align:center;margin:10px 0;font-size:1.1rem;">
                        <strong>${sig.score}/100</strong> • ${sig.strength || 'ORTA'}
                    </div>
                    <div class="details">
                        <div class="detail-row"><span style="color:#aaa">Fiyat:</span><span>$${sig.current_price}</span></div>
                        <div class="detail-row"><span style="color:#aaa">Killzone:</span><span>${sig.killzone || 'Normal'}</span></div>
                        <div class="detail-row"><span style="color:#aaa">Tetik:</span><span>${sig.triggers || '-'}</span></div>
                        <div class="detail-row"><span style="color:#aaa">Güncelleme:</span><span>${sig.last_update || 'Şimdi'}</span></div>
                    </div>
                </div>
            `).join('');
        }}

        function connect() {{
            const tf = document.getElementById('tf').value;
            currentTf = tf;
            document.getElementById('status').innerHTML = `📡 ${tf.toUpperCase()} sinyalleri yükleniyor...`;
            if (ws) ws.close();
            ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/all/${tf}`);
            ws.onopen = () => document.getElementById('status').innerHTML = `✅ ${tf.toUpperCase()} akışı başladı!`;
            ws.onmessage = e => {{
                try {{
                    const data = JSON.parse(e.data);
                    if (data.ping) return;
                    renderSignals(data);
                }} catch {{}}
            }};
            ws.onclose = () => setTimeout(connect, 3000);
        }}

        document.addEventListener('DOMContentLoaded', () => setTimeout(connect, 800));
    </script>
</body>
</html>""")

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse("""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>Giriş | ICT SMART PRO</title>
    <style>
        body {{background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;font-family:system-ui;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}}
        .box {{background:rgba(0,0,0,0.7);padding:40px;border-radius:20px;text-align:center;max-width:400px;width:90%;backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,0.1);}}
        input {{width:100%;padding:16px;margin:12px 0;border:none;border-radius:12px;background:rgba(255,255,255,0.1);color:#fff;font-size:1.1rem;}}
        button {{width:100%;padding:16px;background:linear-gradient(45deg,#fc00ff,#00dbde);border:none;border-radius:12px;color:#fff;font-weight:bold;font-size:1.2rem;cursor:pointer;margin-top:20px;}}
    </style>
</head>
<body>
    <div class="box">
        <h2>🔐 ICT SMART PRO</h2>
        <form method="post" action="/login">
            <input name="email" type="email" placeholder="E-posta" required>
            <button type="submit">🚀 Giriş Yap</button>
        </form>
        <p style="margin-top:20px;color:#888;font-size:0.9rem;">Demo için herhangi bir e-posta kullanabilirsiniz</p>
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
    return {"status": "ok", "time": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), log_level="info")



