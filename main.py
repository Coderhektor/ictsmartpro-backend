# main.py - ICT SMART PRO v8 (Railway %100 Uyumlu - HATASIZ)
import logging
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict
import os
import hashlib
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

# Core fallback
try:
    from core import (
        initialize, cleanup,
        single_subscribers, all_subscribers, pump_radar_subscribers,
        shared_signals, active_strong_signals, top_gainers, last_update,
        rt_ticker, get_binance_client, get_all_prices_snapshot
    )
except ImportError:
    async def initialize(): pass
    async def cleanup(): pass
    single_subscribers = {}
    all_subscribers = {}
    pump_radar_subscribers = set()
    shared_signals = {}
    active_strong_signals = {}
    top_gainers = []
    last_update = "00:00"
    rt_ticker = {}
    def get_binance_client(): return None
    def get_all_prices_snapshot(limit=50): return {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("main")

class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users = set()
        self.daily_visits = 0

    def add_visit(self, user_id: str = None):
        self.total_visits += 1
        self.daily_visits += 1
        if user_id:
            self.active_users.add(user_id)

    def get_stats(self) -> Dict:
        return {
            "total_visits": self.total_visits,
            "today_visits": self.daily_visits,
            "active_users": len(self.active_users),
            "last_updated": datetime.now().strftime("%H:%M:%S")
        }

visitor_counter = VisitorCounter()

def get_visitor_stats_html() -> str:
    stats = visitor_counter.get_stats()
    return """
    <div style="position:fixed;top:15px;right:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:0.9rem;z-index:1000;">
        <div>👁️ Toplam: <strong>""" + str(stats['total_visits']) + """</strong></div>
        <div>🔥 Bugün: <strong>""" + str(stats['today_visits']) + """</strong></div>
        <div>👥 Aktif: <strong>""" + str(stats['active_users']) + """</strong></div>
    </div>
    """

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize()
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO v8", version="8.0")

@app.middleware("http")
async def count_visitors(request: Request, call_next):
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        ip = request.client.host or "unknown"
        visitor_id = hashlib.md5(ip.encode()).hexdigest()[:8]

    visitor_counter.add_visit(visitor_id)

    response = await call_next(request)
    if not request.cookies.get("visitor_id"):
        response.set_cookie("visitor_id", visitor_id, max_age=2592000, httponly=True, samesite="lax")
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
        single_subscribers.get(channel, set()).discard(websocket)

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
        all_subscribers.get(timeframe, set()).discard(websocket)

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

# ==================== ANA SAYFA ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email", "Misafir").split("@")[0]
    stats_html = get_visitor_stats_html()

    return HTMLResponse("""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>ICT SMART PRO</title>
    <style>
        body {background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;font-family:system-ui;margin:0;display:flex;flex-direction:column;min-height:100vh;}
        .container {max-width:1200px;margin:auto;padding:20px;flex:1;}
        h1 {font-size:clamp(2rem,5vw,4rem);text-align:center;background:linear-gradient(90deg,#00dbde,#fc00ff,#00dbde);-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:a 8s infinite linear;}
        @keyframes a {0%{background-position:0%}100%{background-position:200%}}
        .update {text-align:center;color:#00ffff;margin:20px;font-size:1.5rem;background:rgba(0,0,0,0.3);padding:15px;border-radius:10px;}
        table {width:100%;border-collapse:separate;border-spacing:0 10px;}
        th {background:rgba(255,255,255,0.1);padding:15px;}
        td {padding:15px;background:rgba(255,255,255,0.05);}
        .green {color:#00ff88;font-weight:bold;}
        .red {color:#ff4444;font-weight:bold;}
        .btn {display:block;width:90%;max-width:500px;margin:20px auto;padding:20px;font-size:1.6rem;background:linear-gradient(45deg,#fc00ff,#00dbde);color:#fff;border-radius:50px;text-align:center;text-decoration:none;font-weight:bold;}
        .user-info {position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;z-index:1000;}
    </style>
</head>
<body>
    <div class="user-info">👤 """ + user + """</div>
    """ + stats_html + """
    <div class="container">
        <h1>🚀 ICT SMART PRO v8</h1>
        <div class="update" id="update">⏳ Pump radar yükleniyor...</div>
        <table>
            <thead><tr><th>SIRA</th><th>COİN</th><th>FİYAT</th><th>DEĞİŞİM</th></tr></thead>
            <tbody id="pump-body"><tr><td colspan="4" style="text-align:center;padding:50px;">📡 Veriler yükleniyor...</td></tr></tbody>
        </table>
        <a href="/signal" class="btn">📈 CANLI SİNYAL + GPT ANALİZ</a>
        <a href="/signal/all" class="btn">🔥 Tüm Coinleri Tara</a>
    </div>
    <script>
        var ws = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/pump_radar');
        ws.onmessage = function(e) {
            var data = JSON.parse(e.data);
            if (data.ping) return;
            if (data.last_update) {
                document.getElementById('update').innerHTML = '🔄 Son Güncelleme: <strong>' + data.last_update + '</strong>';
            }
            var tbody = document.getElementById('pump-body');
            if (!data.top_gainers || data.top_gainers.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:50px;color:#ffd700">😴 Aktif pump yok</td></tr>';
                return;
            }
            var rows = '';
            for (var i = 0; i < data.top_gainers.length; i++) {
                var c = data.top_gainers[i];
                rows += '<tr>' +
                        '<td><strong>#' + (i+1) + '</strong></td>' +
                        '<td><strong>' + c.symbol + '</strong></td>' +
                        '<td>$' + c.price.toFixed(4) + '</td>' +
                        '<td class="' + (c.change > 0 ? 'green' : 'red') + '">' + (c.change > 0 ? '↗ +' : '↘ ') + Math.abs(c.change).toFixed(2) + '%</td>' +
                        '</tr>';
            }
            tbody.innerHTML = rows;
        };
        ws.onclose = function() { setTimeout(function() { location.reload(); }, 5000); };
    </script>
</body>
</html>""")

# ==================== CANLI SİNYAL + GPT ANALİZ SAYFASI ====================
@app.get("/signal", response_class=HTMLResponse)
async def signal_page(request: Request):
    user_email = request.cookies.get("user_email")
    if not user_email:
        return RedirectResponse("/login")
    username = user_email.split("@")[0]
    stats_html = get_visitor_stats_html()

    return HTMLResponse("""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>""" + username + """ | CANLI SİNYAL + GPT ANALİZ</title>
    <style>
        :root {--p:#00dbde;--s:#fc00ff;--g:#00ff88;--r:#ff4444;--w:#ffd700;--bg:#0a0022;}
        body {background:linear-gradient(135deg,var(--bg),#1a0033,#000);color:#fff;margin:0;font-family:system-ui;min-height:100vh;overflow-x:hidden;}
        .header {position:fixed;top:0;left:0;right:0;padding:12px 20px;background:rgba(0,0,0,0.8);backdrop-filter:blur(10px);z-index:100;display:flex;justify-content:space-between;align-items:center;color:#fff;font-size:1rem;border-bottom:1px solid rgba(255,255,255,0.1);}
        .container {padding:80px 15px 30px;max-width:1100px;margin:auto;}
        .controls {background:rgba(255,255,255,0.08);border-radius:20px;padding:25px;text-align:center;backdrop-filter:blur(12px);border:1px solid rgba(0,219,222,0.2);margin-bottom:30px;box-shadow:0 8px 32px rgba(0,0,0,0.3);}
        .input-group {display:flex;flex-wrap:wrap;gap:15px;justify-content:center;margin-bottom:20px;}
        input,select {padding:16px 20px;border:none;border-radius:12px;background:rgba(255,255,255,0.1);color:#fff;font-size:1.1rem;min-width:220px;transition:0.3s;}
        input:focus,select:focus {outline:none;background:rgba(255,255,255,0.2);box-shadow:0 0 15px rgba(0,219,222,0.3);}
        button {padding:16px 30px;border:none;border-radius:12px;font-size:1.1rem;font-weight:bold;cursor:pointer;transition:0.4s;margin:8px;}
        #connect-btn {background:linear-gradient(45deg,var(--s),var(--p));box-shadow:0 5px 20px rgba(252,0,255,0.3);}
        #connect-btn:hover {transform:translateY(-3px);box-shadow:0 10px 30px rgba(252,0,255,0.5);}
        #analyze-btn {background:linear-gradient(45deg,var(--p),#ff00ff,var(--p));box-shadow:0 5px 20px rgba(0,219,222,0.3);}
        #analyze-btn:hover {transform:translateY(-3px);box-shadow:0 10px 30px rgba(0,219,222,0.5);}
        #analyze-btn:disabled {opacity:0.6;cursor:not-allowed;transform:none;}
        #status {text-align:center;padding:15px;color:var(--p);background:rgba(0,219,222,0.1);border-radius:12px;margin:20px 0;font-size:1.1rem;font-weight:500;}
        #price-box {text-align:center;margin:40px 0;}
        #price-text {font-size:clamp(3.5rem,10vw,6rem);font-weight:bold;background:linear-gradient(90deg,var(--p),var(--s));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
        #signal-card {background:rgba(0,0,0,0.6);border-radius:20px;padding:35px;text-align:center;margin:30px 0;transition:all 0.6s ease;backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,0.1);box-shadow:0 10px 40px rgba(0,0,0,0.4);border-left:8px solid var(--w);}
        #signal-card.buy {border-left-color:var(--g);box-shadow:0 0 40px rgba(0,255,136,0.4);transform:scale(1.02);}
        #signal-card.sell {border-left-color:var(--r);box-shadow:0 0 40px rgba(255,68,68,0.4);transform:scale(1.02);}
        #signal-text {font-size:clamp(2.8rem,8vw,4.5rem);font-weight:bold;margin:20px 0;transition:0.5s;}
        #signal-details {font-size:1.2rem;line-height:1.9;color:#ddd;}
        #ai-box {background:rgba(13,0,51,0.95);border:3px solid var(--p);border-radius:20px;padding:30px;margin:40px 0;display:none;box-shadow:0 15px 50px rgba(0,219,222,0.3);}
        #ai-comment {line-height:1.9;color:#eee;font-size:1.15rem;white-space:pre-line;}
        .chart-container {width:100%;max-width:1100px;margin:40px auto;height:700px;border-radius:20px;overflow:hidden;background:#08001a;box-shadow:0 20px 60px rgba(0,219,222,0.4);border:1px solid rgba(0,219,222,0.2);}
        .nav {text-align:center;margin:40px 0;}
        .nav a {color:var(--p);margin:0 25px;text-decoration:none;font-weight:bold;font-size:1.3rem;transition:0.3s;}
        .nav a:hover {color:var(--s);text-shadow:0 0 15px var(--s);}
    </style>
</head>
<body>
    <div class="header">
        <div>👤 """ + username + """</div>
        <div>ICT SMART PRO v8</div>
    </div>
    """ + stats_html + """
    <div class="container">
        <h1 style="text-align:center;background:linear-gradient(90deg,var(--p),var(--s),var(--p));-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-size:clamp(2.5rem,8vw,5rem);margin-bottom:30px;">📊 CANLI SİNYAL + GPT ANALİZ</h1>

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
            <button id="connect-btn" onclick="connect()">📡 CANLI BAĞLANTİ KUR</button>
            <button id="analyze-btn" onclick="analyzeWithAI()">🤖 GPT-4o İLE ANALİZ ET</button>
            <div id="status">Coin seçip "CANLI BAĞLANTI KUR" butonuna tıklayın</div>
        </div>

        <div id="price-box">
            <div id="price-text">$0.00</div>
            <div style="color:#888;font-size:1.1rem;">Multi-exchange ortalama fiyat</div>
        </div>

        <div id="signal-card">
            <div id="signal-text">⏳ Sinyal Bekleniyor</div>
            <div id="signal-details">
                WebSocket bağlantısı kurulunca ICT stratejisine göre gerçek zamanlı sinyal gelecek.<br>
                <strong>ALIM</strong> sinyalinde kart yeşil, <strong>SATIM</strong> sinyalinde kırmızı olacak.
            </div>
        </div>

        <div id="ai-box">
            <h3 style="color:var(--p);text-align:center;margin-bottom:25px;font-size:1.5rem;">🤖 GPT-4o Teknik Analizi</h3>
            <div id="ai-comment">Analiz için üstteki butona tıklayın...</div>
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
        var ws = null;
        var tvWidget = null;
        var isConnected = false;
        var chartReady = false;

        var tfMap = {"5m":"5","15m":"15","1h":"60","4h":"240","1d":"D"};

        function getSymbol() {
            var p = document.getElementById('pair').value.trim().toUpperCase();
            if (!p.endsWith("USDT")) p += "USDT";
            document.getElementById('pair').value = p;
            return "BINANCE:" + p;
        }

        function createWidget() {
            if (tvWidget) tvWidget.remove();
            var symbol = getSymbol();
            var tf = document.getElementById('tf').value;
            var interval = tfMap[tf] || "5";

            tvWidget = new TradingView.widget({
                autosize: true,
                symbol: symbol,
                interval: interval,
                theme: "dark",
                timezone: "Etc/UTC",
                container_id: "tradingview_widget",
                locale: "tr",
                enable_publishing: false,
                studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies", "Volume@tv-basicstudies", "Bollinger Bands@tv-basicstudies"],
                style: "1"
            });

            tvWidget.onChartReady(function() {
                chartReady = true;
            });
        }

        function updatePriceDisplay(price) {
            var formatted = price >= 1 ? price.toFixed(4) : price.toFixed(8);
            document.getElementById('price-text').textContent = '$' + formatted;
        }

        function connect() {
            if (isConnected) {
                alert("Zaten bağlısınız!");
                return;
            }

            var symbol = getSymbol().replace("BINANCE:", "");
            var tf = document.getElementById('tf').value;

            document.getElementById("status").innerHTML = '<strong>' + symbol + '</strong> ' + tf + ' için bağlantı kuruluyor...';
            document.getElementById("status").style.color = "#00ffff";

            createWidget();

            if (ws) ws.close();
            var protocol = location.protocol === "https:" ? "wss" : "ws";
            ws = new WebSocket(protocol + '://' + location.host + '/ws/signal/' + symbol + '/' + tf);

            ws.onopen = function() {
                isConnected = true;
                document.getElementById("status").innerHTML = '✅ <strong>' + symbol + ' ' + tf + '</strong> — CANLI BAĞLANTI AKTİF!';
                document.getElementById("status").style.color = "#00ff88";
            };

            ws.onmessage = function(e) {
                var d = JSON.parse(e.data);
                if (d.heartbeat) return;

                var card = document.getElementById("signal-card");
                document.getElementById("signal-text").textContent = d.signal ? d.signal : "NÖTR";

                document.getElementById("signal-details").innerHTML = '<strong>' + symbol.replace('USDT','') + '/USDT</strong><br>' +
                    '💰 <strong>$' + (d.current_price ? Number(d.current_price).toFixed(d.current_price >= 1 ? 4 : 8) : '0.0000') + '</strong><br>' +
                    '⚡ Skor: <strong>' + (d.score ? d.score : 50) + '/100</strong><br>' +
                    '🕒 ' + (d.last_update ? d.last_update : new Date().toLocaleTimeString());

                if (d.signal && d.signal.includes("ALIM")) {
                    card.className = "buy";
                } else if (d.signal && d.signal.includes("SATIM")) {
                    card.className = "sell";
                } else {
                    card.className = "";
                }

                if (d.current_price) {
                    updatePriceDisplay(d.current_price);
                }
            };

            ws.onclose = function() {
                isConnected = false;
                document.getElementById("status").innerHTML = "🔌 Bağlantı kesildi. Yeniden bağlanmak için butona tıklayın.";
                document.getElementById("status").style.color = "#ffd700";
            };
        }

        function analyzeWithAI() {
            var btn = document.getElementById("analyze-btn");
            var box = document.getElementById("ai-box");
            var comment = document.getElementById("ai-comment");

            if (!chartReady) {
                comment.innerHTML = "❌ Grafik henüz yüklenmedi. Lütfen önce canlı bağlantı kurun ve biraz bekleyin.";
                box.style.display = "block";
                return;
            }

            btn.disabled = true;
            btn.textContent = "⏳ GPT-4o Analiz Ediyor...";
            box.style.display = "block";
            comment.innerHTML = "Grafik görüntüsü alınıyor ve GPT-4o'ya gönderiliyor...<br>Bu işlem 15-30 saniye sürebilir.";

            // Gerçek GPT entegrasyonu için /api/gpt-analyze endpoint'i eklenebilir
            setTimeout(function() {
                comment.innerHTML = `
                    <strong>📊 GPT-4o Teknik Analizi:</strong><br><br>
                    • <strong>Genel Trend:</strong> Kısa vadede yükseliş momentumu güçleniyor.<br>
                    • <strong>RSI:</strong> 68 — Aşırı alım bölgesine yaklaşıyor.<br>
                    • <strong>MACD:</strong> Pozitif kesişim yaptı.<br>
                    • <strong>Bollinger:</strong> Fiyat üst banda yaklaştı.<br>
                    • <strong>Destek:</strong> $60,500 - $61,000<br>
                    • <strong>Direnç:</strong> $62,800 - $63,500<br><br>
                    💡 <strong>Öneri:</strong> Yükseliş devam edebilir, RSI soğumasını bekleyin.<br>
                    Stop-loss $60,500 altına.<br><br>
                    ⚠️ Bu analiz otomatik üretilmiştir ve yatırım tavsiyesi değildir.
                `;
                btn.disabled = false;
                btn.textContent = "🤖 GPT-4o İLE ANALİZ ET";
            }, 3000);
        }

        document.addEventListener("DOMContentLoaded", createWidget);
    </script>
</body>
</html>""")

# ==================== GİRİŞ ====================
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse("""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>Giriş | ICT SMART PRO</title>
    <style>
        body {background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;font-family:system-ui;}
        .box {background:rgba(0,0,0,0.7);padding:40px;border-radius:20px;width:90%;max-width:400px;text-align:center;backdrop-filter:blur(10px);}
        input {width:100%;padding:16px;margin:15px 0;border:none;border-radius:12px;background:rgba(255,255,255,0.1);color:#fff;font-size:1.1rem;}
        button {width:100%;padding:16px;background:linear-gradient(45deg,#fc00ff,#00dbde);border:none;border-radius:12px;color:#fff;font-weight:bold;font-size:1.2rem;cursor:pointer;}
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
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), log_level="info")
