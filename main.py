# main.py — GÜNCELLENMİŞ VERSİYON: Mobil uyumlu, veri akışı haberleri, sinyal anında gösterim 🚀
import os
import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

# Core modüller
from core import (
    initialize,
    cleanup,
    single_subscribers,
    all_subscribers,
    pump_radar_subscribers,
    realtime_subscribers,
    shared_signals,
    active_strong_signals,
    top_gainers,
    last_update,
    rt_ticker,
)
from utils import all_usdt_symbols

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("main")

# ==================== LIFESPAN ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize()
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="2.1")

# ==================== WEBSOCKET ENDPOINTS ====================

@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_signal(websocket: WebSocket, pair: str, timeframe: str):
    await websocket.accept()
    symbol = pair.upper().replace("/", "").replace("-", "").strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    channel = f"{symbol}:{timeframe}"
    single_subscribers[channel].add(websocket)

    # Mevcut sinyali gönder
    sig = shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        await websocket.send_json(sig)

    try:
        await websocket.receive()  # bağlantıyı açık tut
    except WebSocketDisconnect:
        single_subscribers[channel].discard(websocket)


@app.websocket("/ws/all/{timeframe}")
async def ws_all(websocket: WebSocket, timeframe: str):
    supported_tfs = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
    if timeframe not in supported_tfs:
        await websocket.accept()
        await websocket.send_json({"error": "Zaman dilimi desteklenmiyor"})
        await websocket.close()
        return

    await websocket.accept()
    all_subscribers[timeframe].add(websocket)

    # Mevcut güçlü sinyalleri gönder
    signals = active_strong_signals.get(timeframe, [])
    await websocket.send_json(signals)

    try:
        await websocket.receive()
    except WebSocketDisconnect:
        all_subscribers[timeframe].discard(websocket)


@app.websocket("/ws/pump_radar")
async def ws_pump(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    await websocket.send_json({
        "top_gainers": top_gainers,
        "last_update": last_update
    })
    try:
        await websocket.receive()
    except WebSocketDisconnect:
        pump_radar_subscribers.discard(websocket)


@app.websocket("/ws/realtime_price")
async def ws_realtime_price(websocket: WebSocket):
    await websocket.accept()
    realtime_subscribers.add(websocket)
    try:
        while True:
            # İlk veriyi gönder
            await websocket.send_json(rt_ticker["tickers"])
            await asyncio.sleep(5)  # güncelleme frekansı
    except WebSocketDisconnect:
        realtime_subscribers.discard(websocket)


# ==================== HTML SAYFALAR ====================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>ICT SMART PRO</title>
    <style>
        body{{background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;font-family:sans-serif;min-height:100vh;margin:0;display:flex;flex-direction:column}}
        .container{{max-width:1200px;margin:auto;padding:20px;flex:1}}
        h1{{font-size:clamp(2rem, 5vw, 5rem);text-align:center;background:linear-gradient(90deg,#00dbde,#fc00ff,#00dbde);-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:g 8s infinite}}
        @keyframes g{{0%{{background-position:0%}}100%{{background-position:200%}}}}
        .update{{text-align:center;color:#00ffff;margin:30px;font-size:clamp(1rem, 3vw, 1.8rem)}}
        table{{width:100%;border-collapse:separate;border-spacing:0 12px;margin:30px 0}}
        th{{background:#ffffff11;padding:clamp(10px, 2vw, 20px);font-size:clamp(1rem, 2.5vw, 1.6rem)}}
        tr{{background:#ffffff08;transition:.4s}}
        tr:hover{{transform:scale(1.02);box-shadow:0 15px 40px #00ffff44}}
        .green{{color:#00ff88;text-shadow:0 0 20px #00ff88}}
        .red{{color:#ff4444;text-shadow:0 0 20px #ff4444}}
        .btn{{display:block;width:90%;max-width:500px;margin:20px auto;padding:clamp(15px, 3vw, 25px);font-size:clamp(1.2rem, 4vw, 2.2rem);
            background:linear-gradient(45deg,#fc00ff,#00dbde);color:#fff;text-align:center;border-radius:50px;
            text-decoration:none;box-shadow:0 0 60px #ff00ff88;transition:.3s}}
        .btn:hover{{transform:scale(1.08);box-shadow:0 0 100px #ff00ff}}
        .loading{{color:#00ffff;animation:pulse 2s infinite}}
        @keyframes pulse{{0%,100%{{opacity:0.6}}50%{{opacity:1}}}}
    </style>
</head>
<body>
    <div style='position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;
        color:#00ff88;font-size:clamp(0.8rem, 2vw, 1.2rem);'>Hoş geldin, {user}</div>
    <div class="container">
        <h1>ICT SMART PRO</h1>
        <div class="update" id="update">Veri yükleniyor... <span class="loading">●●●</span></div>
        <table>
            <thead><tr><th>SIRA</th><th>COİN</th><th>FİYAT</th><th>24S DEĞİŞİM</th></tr></thead>
            <tbody id="table-body">
                <tr><td colspan="4" style="padding:clamp(50px, 10vw, 100px);font-size:clamp(1rem, 3vw, 2rem);color:#888">Pump radar gerçek zamanlı yükleniyor...</td></tr>
            </tbody>
        </table>
        <a href="/signal" class="btn">🚀 Tek Coin Canlı Sinyal + Grafik</a>
        <a href="/signal/all" class="btn" style="margin-top:20px;">🔥 Tüm Coinleri Tara</a>
    </div>
    <script>
        const p = location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(p + '://' + location.host + '/ws/pump_radar');
        ws.onmessage = e => {{
            const d = JSON.parse(e.data);
            document.getElementById('update').innerHTML = `Son Güncelleme: <strong>${{d.last_update}}</strong>`;
            const t = document.getElementById('table-body');
            if (!d.top_gainers || d.top_gainers.length === 0) {{
                t.innerHTML = '<tr><td colspan="4" style="padding:clamp(50px, 10vw, 100px);color:#ffd700">😴 Şu anda pump yok</td></tr>';
                return;
            }}
            t.innerHTML = d.top_gainers.map((c, i) => `
                <tr>
                    <td>#${{i+1}}</td>
                    <td><strong>${{c.symbol}}</strong></td>
                    <td>$${{c.price.toFixed(4)}}</td>
                    <td class="${{c.change > 0 ? 'green' : 'red'}}">${{c.change > 0 ? '+' : ''}}${{c.change.toFixed(2)}}%</td>
                </tr>`).join('');
        }};
    </script>
</body>
</html>"""


@app.get("/signal", response_class=HTMLResponse)
async def signal(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/")
    return """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>📊 CANLI SİNYAL + GRAFİK | ICT SMART PRO</title>
    <style>
        body{{background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;font-family:sans-serif;margin:0;padding:0;overflow-x:hidden;display:flex;flex-direction:column}}
        .container{{padding:15px;position:relative;flex:1}}
        h1{{text-align:center;font-size:clamp(2rem, 5vw, 3.2rem);background:linear-gradient(90deg,#00dbde,#fc00ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:15px 0}}
        .controls{{max-width:750px;margin:15px auto;text-align:center}}
        input,select,button{{width:100%;padding:clamp(10px, 3vw, 16px);margin:8px 0;font-size:clamp(1rem, 3vw, 1.5rem);border:none;border-radius:12px;background:#333;color:#fff}}
        button{{background:linear-gradient(45deg,#fc00ff,#00dbde);cursor:pointer;font-weight:bold}}
        #status{{color:#00dbde;font-size:clamp(0.8rem, 2.5vw, 1.3rem);margin:12px}}
        #result{{padding:20px;background:#000000aa;border-radius:18px;font-size:clamp(1rem, 3vw, 1.6rem);margin:15px 0;min-height:160px;line-height:1.6;text-align:center}}
        #chart{{height:clamp(40vh, 60vh, 70vh);width:100%;max-width:1100px;margin:20px auto;border-radius:12px;overflow:hidden;box-shadow:0 8px 30px #00ffff33;position:relative}}
        #tradingview_widget{{height:100% !important;width:100% !important;position:absolute;top:0;left:0}}
        #ai-box{{background:#0d0033;border-radius:15px;padding:18px;margin-top:15px}}
        .green{{border-left:4px solid #00ff88;background:#00ff880f}}
        .red{{border-left:4px solid #ff4444;background:#ff44440f}}
        .footer{{text-align:center;color:#888;margin-top:20px}}
    </style>
</head>
<body>
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
            <button onclick="connect()">🔴 CANLI BAĞLANTI KUR</button>
            <div id="status">Bağlantı bekleniyor...</div>
        </div>

        <div id="result">🔴 CANLI BAĞLANTI KUR butonuna basarak veri akışını başlatın</div>

        <!-- 📈 TRADINGVIEW CHART -->
        <div id="chart">
            <div id="tradingview_widget"></div>
        </div>

        <!-- 🤖 AI ANALİZ (Gelecek için hazır) -->
        <div id="ai-box" style="display:none">
            <h3>🤖 DeepSeek AI Analizi</h3>
            <p id="ai-comment">AI analizi yükleniyor...</p>
        </div>

        <a href="/" class="footer">← Ana Sayfaya Dön</a>
    </div>

    <script>
        let ws = null;
        let tvWidget = null;
        let hasReceivedSignal = false;

        // TradingView Widget
        function createTVWidget(symbol = "BINANCE:BTCUSDT", interval = "5") {
            if (tvWidget) {
                tvWidget.remove();
                tvWidget = null;
            }
            tvWidget = new TradingView.widget({
                "width": "100%",
                "height": "100%",
                "autosize": true,
                "symbol": symbol,
                "interval": interval,
                "timezone": "Etc/UTC",
                "theme": "dark",
                "style": "1",
                "locale": "tr",
                "toolbar_bg": "#131722",
                "enable_publishing": false,
                "hide_side_toolbar": false,
                "allow_symbol_change": false,
                "container_id": "tradingview_widget",
                "studies": ["RSI@tv-basicstudies"],
                "overrides": {"paneProperties.background": "#0a0022"}
            });
        }

        // Sayfa yüklendiğinde varsayılan grafik
        document.addEventListener("DOMContentLoaded", () => {
            createTVWidget("BINANCE:BTCUSDT", "5");
        });

        // TF → interval mapping
        const tfIntervalMap = {
            "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
            "1h": "60", "4h": "240", "1d": "D", "1w": "W"
        };

        function connect() {
            const pair = document.getElementById('pair').value.trim().toUpperCase();
            const tf = document.getElementById('tf').value;
            const symbol = pair.endsWith("USDT") ? pair : pair + "USDT";
            const tvSymbol = "BINANCE:" + symbol;
            const interval = tfIntervalMap[tf] || "5";

            // Grafik güncelle
            createTVWidget(tvSymbol, interval);

            // WebSocket bağlantısı
            if (ws) ws.close();
            const p = location.protocol === 'https:' ? 'wss' : 'ws';
            ws = new WebSocket(p + '://' + location.host + '/ws/signal/' + symbol + '/' + tf);

            ws.onopen = () => {
                document.getElementById('status').innerHTML = "✅ Veri akışı başladı! 🚀 Sinyal bekleniyor...";
                document.getElementById('result').innerHTML = '<p style="color:#00ffff">🔄 Veri aktarılıyor... Sinyal taraması devam ediyor!</p>';
                hasReceivedSignal = false;
            };

            ws.onmessage = (e) => {
                const d = JSON.parse(e.data);
                hasReceivedSignal = true;
                document.getElementById('status').innerHTML = "✅ Sinyal alındı! 📈 Veri akışı devam ediyor.";

                const resultDiv = document.getElementById('result');
                let cls = '', col = '#ffd700';
                if (d.signal && d.signal.includes('ALIM')) { 
                    cls = 'green'; col = '#00ff88'; 
                } else if (d.signal && d.signal.includes('SATIM')) { 
                    cls = 'red'; col = '#ff4444'; 
                }

                resultDiv.className = cls;
                resultDiv.innerHTML = `
                    <h2 style="font-size:clamp(1.5rem, 4vw, 2.8rem);color:${col};margin:0">${d.signal || 'Sinyal Yükleniyor...'}</h2>
                    <p><strong>${d.pair || symbol.replace('USDT','/USDT')}</strong> • $${d.current_price || '?'}</p>
                    <p>Skor: <strong>${d.score || '?'} / 100</strong> | ${d.killzone || ''} | ${d.last_update || ''}</p>
                    <p><small>${d.triggers || ''}</small></p>`;
            };

            ws.onerror = () => document.getElementById('status').innerHTML = "⚠️ Bağlantı hatası – Yeniden dene!";
            ws.onclose = () => {
                document.getElementById('status').innerHTML = "❌ Bağlantı kapandı";
                if (!hasReceivedSignal) {
                    document.getElementById('result').innerHTML = '<p style="color:#ffd700">😴 Şu an güçlü sinyal yok – Tarama devam ediyor!</p>';
                }
            };
        }
    </script>
    <script src="https://s3.tradingview.com/tv.js"></script>
</body>
</html>"""


@app.get("/signal/all", response_class=HTMLResponse)
async def signal_all(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/")
    return """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Tüm Coinler Canlı Tarama</title>
    <style>
        body{{background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;padding:20px;font-family:sans-serif;margin:0;display:flex;flex-direction:column}}
        .container{{max-width:1200px;margin:auto;flex:1}}
        h1{{text-align:center;font-size:clamp(2rem, 5vw, 3.6rem);background:linear-gradient(90deg,#fc00ff,#00dbde);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
        .card{{background:#00000088;border-radius:20px;padding:clamp(15px, 4vw, 25px);margin:25px 0}}
        table{{width:100%;border-collapse:collapse;margin-top:20px}}
        th,td{{padding:clamp(8px, 2vw, 12px);text-align:left;border-bottom:1px solid #333;font-size:clamp(0.8rem, 2vw, 1rem)}}
        th{{background:#00ffff22}}
        .green{{color:#00ff88}}
        .red{{color:#ff4444}}
        select{{width:100%;padding:clamp(10px, 3vw, 16px);margin:8px 0;font-size:clamp(1rem, 3vw, 1.5rem);border:none;border-radius:12px;background:#333;color:#fff}}
    </style>
</head>
<body>
<div class="container">
    <h1>🔥 TÜM COİNLER CANLI TARANIYOR</h1>
    <div class="card">
        <p>🟢 Sistem çalışıyor — Seçilen timeframe'de sinyal aranıyor.</p>
        <p>⏳ Güncelleme sıklığı: <strong>10 saniye</strong></p>
        <select id="tf" onchange="connect()">
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
        <table id="sig-table">
            <thead><tr><th>COİN</th><th>ZAMAN</th><th>FİYAT</th><th>SİNYAL</th><th>SKOR</th><th>TRİGGER</th></tr></thead>
            <tbody id="table-body">
                <tr><td colspan="6" style="padding:clamp(30px, 8vw, 60px);color:#888">İlk sinyal 5-10 sn içinde gelecek...</td></tr>
            </tbody>
        </table>
    </div>
    <a href="/signal" style="color:#00dbde;display:block;text-align:center;margin:20px">← Tek Coin Sinyal + Grafik</a>
</div>

<script>
let ws = null;

function connect() {
    const tf = document.getElementById('tf').value;
    if (ws) ws.close();
    const p = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(p + '://' + location.host + '/ws/all/' + tf);

    const tbody = document.getElementById('table-body');

    ws.onopen = () => {
        tbody.innerHTML = '<tr><td colspan="6" style="padding:clamp(30px, 8vw, 60px);color:#00ffff">✅ Veri akışı başladı! 🚀 Sinyaller taranıyor...</td></tr>';
    };

    ws.onmessage = e => {
        const signals = JSON.parse(e.data);
        if (!Array.isArray(signals) || signals.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="padding:clamp(30px, 8vw, 60px);color:#ffd700">😴 Şu an güçlü sinyal yok</td></tr>';
            return;
        }
        tbody.innerHTML = signals.map((s, i) => `
            <tr>
                <td><strong>${s.pair}</strong></td>
                <td>${s.timeframe}</td>
                <td>$${s.current_price}</td>
                <td class="${s.signal.includes('ALIM') ? 'green' : 'red'}">${s.signal}</td>
                <td>${s.score}</td>
                <td><small>${s.triggers}</small></td>
            </tr>`).join('');
    };
}

// Sayfa yüklendiğinde bağlan
document.addEventListener("DOMContentLoaded", connect);
</script>
</body>
</html>"""


# ==================== UTIL ENDPOINTS ====================

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "time": datetime.utcnow().isoformat(),
        "symbols_loaded": len(all_usdt_symbols),
        "rt_coins": len(rt_ticker["tickers"]),
        "ws_connections": (
            sum(len(v) for v in single_subscribers.values()) +
            sum(len(v) for v in all_subscribers.values()) +
            len(pump_radar_subscribers) +
            len(realtime_subscribers)
        ),
        "strong_signals_5m": len(active_strong_signals.get("5m", [])),
        "last_pump_update": last_update
    }

@app.get("/login")
async def login_page():
    return HTMLResponse("""
    <form method="post" style="max-width:400px;margin:100px auto;text-align:center;background:#0a0022;padding:30px;border-radius:20px">
        <h2 style="color:#00dbde">Giriş Yap</h2>
        <input name="email" placeholder="E-posta" required style="width:100%;padding:12px;margin:10px 0;border:none;border-radius:8px">
        <button type="submit" style="width:100%;padding:12px;background:linear-gradient(45deg,#fc00ff,#00dbde);border:none;border-radius:8px;color:white;font-weight:bold">
            Giriş Yap
        </button>
    </form>
    """)

@app.post("/login")
async def login(request: Request):
    form = await request.form()
    email = form.get("email", "").strip().lower()
    if email:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("user_email", email, max_age=30*24*3600, httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login")

@app.get("/abonelik", response_class=HTMLResponse)
async def abonelik():
    return """<h1 style='text-align:center;color:#00dbde'>🚀 Premium Abonelik</h1>
    <p style='text-align:center'>Stripe entegrasyonu yakında!</p>
    <div style='text-align:center;margin:40px'>
        <a href="/" style="color:#00dbde">&larr; Ana Sayfaya Dön</a>
    </div>"""
