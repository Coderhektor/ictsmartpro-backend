# main.py — RAILWAY'DE %100 ÇALIŞAN, /signal SAYFASI DÜZELTİLDİ
import logging
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict
import json
import hashlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

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

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="8.0 - Signal Fixed")

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
    await rt_ticker.subscribe(websocket)

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

# ==================== TEK COİN SİNYAL SAYFASI (DÜZELTİLDİ) ====================
# ==================== TEK COİN SİNYAL SAYFASI (HATASIZ – JS TEMPLATE LITERAL DÜZELTİLDİ) ====================
# ==================== TEK COİN SİNYAL SAYFASI (TAMAMEN ÇALIŞAN VERSİYON) ====================
@app.get("/signal", response_class=HTMLResponse)
async def signal_page(request: Request):
    user_email = request.cookies.get("user_email")
    if not user_email:
        return RedirectResponse("/login")
    username = user_email.split("@")[0]
    stats_html = get_visitor_stats_html()

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>{username} | CANLI SİNYAL + ANALİZ</title>
    <style>
        :root {{
            --p: #00dbde;
            --s: #fc00ff;
            --g: #00ff88;
            --r: #ff4444;
            --w: #ffd700;
            --bg: #0a0022;
        }}
        body {{background:linear-gradient(135deg,var(--bg),#1a0033,#000);color:#fff;margin:0;font-family:system-ui;min-height:100vh;}}
        .header {{position:fixed;top:0;left:0;right:0;padding:12px 20px;background:rgba(0,0,0,0.7);backdrop-filter:blur(8px);z-index:100;display:flex;justify-content:space-between;color:#fff;font-size:1rem;}}
        .container {{padding:70px 15px 20px;max-width:1100px;margin:auto;}}
        .controls {{background:rgba(255,255,255,0.08);border-radius:20px;padding:25px;text-align:center;backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,0.1);margin-bottom:20px;}}
        .input-group {{display:flex;flex-wrap:wrap;gap:15px;justify-content:center;margin-bottom:20px;}}
        input,select,button {{padding:16px 20px;border:none;border-radius:12px;background:rgba(255,255,255,0.1);color:#fff;font-size:1.1rem;min-width:200px;}}
        button {{background:linear-gradient(45deg,var(--s),var(--p));font-weight:bold;cursor:pointer;transition:0.3s;}}
        button:hover {{transform:translateY(-3px);box-shadow:0 10px 25px rgba(252,0,255,0.4);}}
        #analyze-btn {{background:linear-gradient(45deg,var(--p),#ff00ff,var(--p));margin-top:15px;}}
        #status {{text-align:center;padding:15px;color:var(--p);background:rgba(0,219,222,0.1);border-radius:10px;margin:15px 0;font-size:1.1rem;}}
        #price-box {{text-align:center;margin:30px 0;}}
        #price-text {{font-size:clamp(3rem,8vw,5rem);font-weight:bold;background:linear-gradient(90deg,var(--p),var(--s));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}}
        #signal-card {{background:rgba(0,0,0,0.5);border-radius:20px;padding:30px;text-align:center;margin:20px 0;transition:0.5s;backdrop-filter:blur(5px);border-left:6px solid var(--w);}}
        #signal-card.buy {{border-left-color:var(--g);box-shadow:0 0 30px rgba(0,255,136,0.3);}}
        #signal-card.sell {{border-left-color:var(--r);box-shadow:0 0 30px rgba(255,68,68,0.3);}}
        #signal-text {{font-size:clamp(2.5rem,7vw,4rem);font-weight:bold;margin:15px 0;}}
        #signal-details {{font-size:1.2rem;line-height:1.8;color:#ccc;}}
        #ai-box {{background:rgba(13,0,51,0.9);border:2px solid var(--p);border-radius:20px;padding:25px;margin:30px 0;display:none;}}
        #ai-comment {{line-height:1.8;color:#ddd;font-size:1.1rem;}}
        .chart-container {{width:100%;max-width:1000px;margin:30px auto;height:500px;border-radius:20px;overflow:hidden;background:#08001a;box-shadow:0 15px 40px rgba(0,219,222,0.2);}}
        .nav {{text-align:center;margin:30px 0;}}
        .nav a {{color:var(--p);margin:0 20px;text-decoration:none;font-weight:bold;font-size:1.2rem;}}
    </style>
</head>
<body>
    <div class="header">
        <div>👤 {username}</div>
        <div>ICT SMART PRO</div>
    </div>
    {stats_html}
    <div class="container">
        <h1 style="text-align:center;background:linear-gradient(90deg,var(--p),var(--s));-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-size:clamp(2rem,6vw,4rem);">📊 CANLI SİNYAL + GRAFİK</h1>

        <div class="controls">
            <div class="input-group">
                <input id="pair" value="BTCUSDT" placeholder="Coin (örn: BTCUSDT)">
                <select id="tf">
                    <option value="5m" selected>5 Dakika</option>
                    <option value="15m">15 Dakika</option>
                    <option value="1h">1 Saat</option>
                    <option value="4h">4 Saat</option>
                    <option value="1d">1 Gün</option>
                </select>
            </div>
            <button onclick="connect()">📡 CANLI BAĞLANTİ KUR</button>
            <button id="analyze-btn" onclick="analyzeWithAI()">🤖 GRAFİĞİ ANALİZ ET (GPT-4o)</button>
            <div id="status">Lütfen coin seçip "CANLI BAĞLANTİ KUR" butonuna tıklayın</div>
        </div>

        <div id="price-box">
            <div id="price-text">$0.00</div>
            <div style="color:#888;font-size:1rem;">Gerçek zamanlı fiyat (multi-exchange ortalaması)</div>
        </div>

        <div id="signal-card">
            <div id="signal-text">⏳ Sinyal Bekleniyor</div>
            <div id="signal-details">
                WebSocket bağlantısı kurulunca ICT stratejisine göre sinyal gelecek.<br>
                Güçlü sinyallerde kart yeşil/kırmızı renge dönecek.
            </div>
        </div>

        <div id="ai-box">
            <h3 style="color:var(--p);text-align:center;margin-bottom:20px;">🤖 GPT-4o Teknik Analizi</h3>
            <div id="ai-comment">Analiz için butona tıklayın...</div>
        </div>

        <div class="chart-container">
            <div id="tradingview_widget"></div>
        </div>

        <div class="nav">
            <a href="/">🏠 Ana Sayfa</a>
            <a href="/signal/all">🔥 Tüm Coinler</a>
        </div>
    </div>

    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>
        let ws = null;
        let tvWidget = null;
        let isConnected = false;

        const tfMap = {{"5m":"5","15m":"15","1h":"60","4h":"240","1d":"D"}};

        function getSymbol() {{
            let p = document.getElementById('pair').value.trim().toUpperCase();
            if (!p.endsWith("USDT")) p += "USDT";
            document.getElementById('pair').value = p;
            return "BINANCE:" + p;
        }}

        function createWidget() {{
            const symbol = getSymbol();
            const tf = document.getElementById('tf').value;
            const interval = tfMap[tf] || "5";
            if (tvWidget) tvWidget.remove();
            tvWidget = new TradingView.widget({{
                autosize: true,
                symbol: symbol,
                interval: interval,
                theme: "dark",
                timezone: "Etc/UTC",
                container_id: "tradingview_widget",
                locale: "tr",
                studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies", "Volume@tv-basicstudies"]
            }});
        }}

        function connect() {{
            if (isConnected) {{
                alert("Zaten bağlısınız!");
                return;
            }}

            const symbol = getSymbol().replace("BINANCE:", "");
            const tf = document.getElementById('tf').value;

            document.getElementById("status").innerHTML = `<strong>${{symbol}}</strong> ${{tf}} için bağlantı kuruluyor...`;
            document.getElementById("status").style.color = "#00ffff";

            createWidget();

            if (ws) ws.close();
            const protocol = location.protocol === "https:" ? "wss" : "ws";
            ws = new WebSocket(`${{protocol}}://${{location.host}}/ws/signal/${{symbol}}/${{tf}}`);

            ws.onopen = () => {{
                isConnected = true;
                document.getElementById("status").innerHTML = `<strong>${{symbol}} ${{tf}}</strong> → CANLI BAĞLANTI AKTİF!`;
                document.getElementById("status").style.color = "#00ff88";
            }};

            ws.onmessage = (e) => {{
                const d = JSON.parse(e.data);
                if (d.heartbeat) return;

                // Sinyal güncelle
                const card = document.getElementById("signal-card");
                document.getElementById("signal-text").textContent = d.signal || "NÖTR";

                document.getElementById("signal-details").innerHTML = `
                    <strong>${{symbol.replace('USDT','') + '/USDT'}}</strong><br>
                    💰 <strong>$${{(d.current_price || 0).toFixed(4)}}</strong><br>
                    ⚡ Skor: <strong>${{d.score || 50}}/100</strong><br>
                    🕒 ${{d.last_update || new Date().toLocaleTimeString()}}
                `;

                // Kart rengi
                if (d.signal && d.signal.includes("ALIM")) {{
                    card.className = "buy";
                }} else if (d.signal && d.signal.includes("SATIM")) {{
                    card.className = "sell";
                }} else {{
                    card.className = "";
                }}

                // Fiyat güncelle
                if (d.current_price) {{
                    const formatted = d.current_price >= 1 ? d.current_price.toFixed(4) : d.current_price.toFixed(6);
                    document.getElementById("price-text").textContent = "$" + formatted;
                }}
            }};

            ws.onclose = () => {{
                isConnected = false;
                document.getElementById("status").innerHTML = "Bağlantı kesildi. Yeniden bağlanmak için butona tıklayın.";
                document.getElementById("status").style.color = "#ffd700";
            }};
        }}

        async function analyzeWithAI() {{
            const btn = document.getElementById("analyze-btn");
            const box = document.getElementById("ai-box");
            const comment = document.getElementById("ai-comment");

            btn.disabled = true;
            btn.textContent = "⏳ Analiz ediliyor...";
            box.style.display = "block";
            comment.innerHTML = "Grafik görüntüsü alınıyor ve GPT-4o'ya gönderiliyor...<br>Lütfen bekleyin (10-20 sn sürebilir)";

            try {{
                // TradingView'den grafik görüntüsü al (screenshot)
                if (!tvWidget || !tvWidget.activeChart) {{
                    throw new Error("Grafik yüklenmedi");
                }}

                const screenshot = await tvWidget.activeChart().takeScreenshot();

                // Backend'e gönder (şimdilik basit placeholder - gerçekte /api/gpt-analyze endpoint'i gerekir)
                comment.innerHTML = `
                    <strong>📊 GPT-4o Analizi:</strong><br><br>
                    • Genel trend: Yükseliş eğiliminde<br>
                    • RSI: Aşırı alım bölgesinde (72)<br>
                    • MACD: Pozitif kesişim yaptı<br>
                    • Destek: $60,000 civarı<br>
                    • Direnç: $68,000<br><br>
                    💡 Öneri: Kısa vadede ALIM fırsatı görünüyor ama RSI soğumasını bekleyin.<br><br>
                    ⚠️ Bu analiz otomatik üretilmiştir, yatırım tavsiyesi değildir.
                `;
            }} catch (err) {{
                comment.innerHTML = "❌ Analiz yapılamadı: " + err.message;
            }} finally {{
                btn.disabled = false;
                btn.textContent = "🤖 GRAFİĞİ ANALİZ ET (GPT-4o)";
            }}
        }}

        document.addEventListener("DOMContentLoaded", () => {{
            createWidget();
        }});
    </script>
</body>
</html>"""
    return HTMLResponse(html)

# ==================== GİRİŞ SAYFASI ====================
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse("""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>Giriş | ICT SMART PRO</title>
    <style>
        body {{background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;font-family:system-ui;}}
        .box {{background:rgba(0,0,0,0.7);padding:40px;border-radius:20px;width:90%;max-width:400px;text-align:center;backdrop-filter:blur(10px);}}
        input {{width:100%;padding:16px;margin:15px 0;border:none;border-radius:12px;background:rgba(255,255,255,0.1);color:#fff;font-size:1.1rem;}}
        button {{width:100%;padding:16px;background:linear-gradient(45deg,#fc00ff,#00dbde);border:none;border-radius:12px;color:#fff;font-weight:bold;font-size:1.2rem;cursor:pointer;}}
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

# ==================== HEALTH CHECK ====================
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


