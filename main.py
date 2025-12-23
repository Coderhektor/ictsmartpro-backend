# main.py — TEMİZ VERSİYON, 1 DAKİKA DAHİL, CANLI SİNYAL HAZIR

import os
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, RedirectResponse

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
)
from utils import all_usdt_symbols

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ictsmartpro")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize()
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()

app = FastAPI(lifespan=lifespan)

# ==================== WEBSOCKET HANDLERS ====================
@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_signal(websocket: WebSocket, pair: str, timeframe: str):
    await websocket.accept()
    symbol = pair.upper().replace("/", "").replace("-", "").replace(" ", "")
    if not symbol.endswith("USDT"):
        await websocket.send_json({"error": "Sadece USDT çiftleri desteklenir"})
        await websocket.close()
        return

    channel = f"{symbol}:{timeframe}"
    single_subscribers[channel].add(websocket)

    sig = shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        await websocket.send_json(sig)

    try:
        await websocket.receive()
    except WebSocketDisconnect:
        single_subscribers[channel].discard(websocket)

@app.websocket("/ws/all/{timeframe}")
async def ws_all(websocket: WebSocket, timeframe: str):
    await websocket.accept()
    all_subscribers[timeframe].add(websocket)
    await websocket.send_json(active_strong_signals.get(timeframe, []))
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        all_subscribers[timeframe].discard(websocket)

@app.websocket("/ws/pump_radar")
async def ws_pump(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    await websocket.send_json({"top_gainers": top_gainers, "last_update": last_update})
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pump_radar_subscribers.discard(websocket)

# ==================== HTML PAGES ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>ICT SMART PRO</title>
    <style>
        body{{background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;font-family:sans-serif;min-height:100vh;margin:0}}
        .container{{max-width:1200px;margin:auto;padding:20px}}
        h1{{font-size:5rem;text-align:center;background:linear-gradient(90deg,#00dbde,#fc00ff,#00dbde);-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:g 8s infinite}}
        @keyframes g{{0%{{background-position:0%}}100%{{background-position:200%}}}}
        .update{{text-align:center;color:#00ffff;margin:30px;font-size:1.8rem}}
        table{{width:100%;border-collapse:separate;border-spacing:0 12px;margin:30px 0}}
        th{{background:#ffffff11;padding:20px;font-size:1.6rem}}
        tr{{background:#ffffff08;transition:.4s}}
        tr:hover{{transform:scale(1.02);box-shadow:0 15px 40px #00ffff44}}
        .green{{color:#00ff88;text-shadow:0 0 20px #00ff88}}
        .red{{color:#ff4444;text-shadow:0 0 20px #ff4444}}
        .btn{{display:block;width:90%;max-width:500px;margin:20px auto;padding:25px;font-size:2.2rem;background:linear-gradient(45deg,#fc00ff,#00dbde);color:#fff;text-align:center;border-radius:50px;text-decoration:none;box-shadow:0 0 60px #ff00ff88;transition:.3s}}
        .btn:hover{{transform:scale(1.08);box-shadow:0 0 100px #ff00ff}}
        .loading{{color:#00ffff;animation:pulse 2s infinite}}
        @keyframes pulse{{0%,100%{{opacity:0.6}}50%{{opacity:1}}}}
    </style>
</head>
<body>
    <div style='position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:1.2rem;'>Hoş geldin, {user}</div>
    <div class="container">
        <h1>ICT SMART PRO</h1>
        <div class="update" id="update">Veri yükleniyor... <span class="loading">●●●</span></div>
        <table>
            <thead><tr><th>SIRA</th><th>COİN</th><th>FİYAT</th><th>24S DEĞİŞİM</th></tr></thead>
            <tbody id="table-body">
                <tr><td colspan="4" style="padding:100px;font-size:2rem;color:#888">Pump radar gerçek zamanlı yükleniyor...</td></tr>
            </tbody>
        </table>
        <a href="/signal" class="btn">🚀 Tek Coin Canlı Sinyal</a>
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
                t.innerHTML = '<tr><td colspan="4" style="padding:100px;color:#ffd700">😴 Şu anda pump yok</td></tr>';
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
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CANLI SİNYAL + GRAFİK | ICT SMART PRO</title>
    <style>
        body{background:linear-gradient(135deg,#0a0022,#000);color:#fff;font-family:sans-serif;margin:0;padding:0}
        .container{padding:20px}
        h1{text-align:center;font-size:3.8rem;background:linear-gradient(90deg,#00dbde,#fc00ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:20px}
        .controls{max-width:800px;margin:20px auto;text-align:center}
        input,select,button{width:100%;padding:18px;margin:10px 0;font-size:1.6rem;border:none;border-radius:15px;background:#333;color:#fff}
        button{background:linear-gradient(45deg,#fc00ff,#00dbde);cursor:pointer;font-weight:bold}
        #status{color:#00dbde;font-size:1.4rem;margin:15px}
        #result{padding:25px;background:#000000aa;border-radius:20px;font-size:1.8rem;margin:20px 0;min-height:180px;line-height:1.6}
        #chart{height:60vh;width:100%;max-width:1200px;margin:20px auto;border-radius:15px;overflow:hidden;box-shadow:0 10px 40px #00ffff33}
        .green{border:2px solid #00ff88;box-shadow:0 0 40px #00ff8833}
        .red{border:2px solid #ff4444;box-shadow:0 0 40px #ff444433}
        .footer{color:#888;text-align:center;margin-top:30px}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 CANLI SİNYAL + GRAFİK</h1>
        <div class="controls">
            <input id="pair" placeholder="Coin (örn: BTCUSDT)" value="BTCUSDT">
            <select id="tf">
                <option value="1m">1 Dakika</option>
                <option value="5m" selected>5 Dakika</option>
                <option value="15m">15 Dakika</option>
                <option value="1h">1 Saat</option>
                <option value="4h">4 Saat</option>
                <option value="1d">1 Gün</option>
            </select>
            <button onclick="connect()">🔴 CANLI BAĞLANTI KUR</button>
            <div id="status">Bağlantı bekleniyor...</div>
        </div>
        <div id="result" class="result">Sinyal burada gerçek zamanlı olarak güncellenecek...</div>
        <div id="chart"><div id="tradingview_widget"></div></div>
        <a href="/" class="footer">← Ana Sayfaya Dön</a>
    </div>

    <script type="text/javascript">
        let tvWidget = null;
        let currentWs = null;

        function createTradingViewWidget(symbol = "BINANCE:BTCUSDT", interval = "5") {
            if (tvWidget) tvWidget.remove();
            tvWidget = new TradingView.widget({
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
                "allow_symbol_change": true,
                "container_id": "tradingview_widget",
                "studies": ["RSI@tv-basicstudies", "MAExp@tv-basicstudies"]
            });
        }

        document.addEventListener("DOMContentLoaded", () => {
            createTradingViewWidget("BINANCE:BTCUSDT", "5");
        });

        // 1 DAKİKA DAHİL TF MAP
        const tfMap = {
            "1m": "1",
            "5m": "5",
            "15m": "15",
            "1h": "60",
            "4h": "240",
            "1d": "D"
        };

        function connect() {
            const pair = document.getElementById('pair').value.trim().toUpperCase();
            const tf = document.getElementById('tf').value;

            const tvSymbol = "BINANCE:" + (pair.endsWith("USDT") ? pair : pair + "USDT");
            const tvInterval = tfMap[tf] || "5";

            createTradingViewWidget(tvSymbol, tvInterval);

            if (currentWs) currentWs.close();

            const p = location.protocol === 'https:' ? 'wss' : 'ws';
            currentWs = new WebSocket(p + '://' + location.host + '/ws/signal/' + pair + '/' + tf);

            currentWs.onopen = () => {
                document.getElementById('status').innerHTML = "✅ CANLI BAĞLANTI AKTİF – SİNYAL BEKLENİYOR";
                document.getElementById('status').style.color = "#00ff88";
            };

            currentWs.onmessage = e => {
                const d = JSON.parse(e.data);
                let cls = 'result';
                let col = '#ffd700';

                if (d.signal && d.signal.includes('ALIM')) {
                    cls += ' green';
                    col = '#00ff88';
                } else if (d.signal && d.signal.includes('SATIM')) {
                    cls += ' red';
                    col = '#ff4444';
                }

                document.getElementById('result').className = cls;
                document.getElementById('result').innerHTML = `
                    <h2 style="font-size:3.2rem;color:${col}">${d.signal || 'GÜÇLÜ SİNYAL YOK'}</h2>
                    <p><strong>${d.pair || pair}</strong> • $${d.current_price || '?'} • ${tf.toUpperCase()}</p>
                    <p>Momentum: <strong>${d.momentum === 'up' ? '⬆️ YUKARI' : '⬇️ AŞAĞI'}</strong> | Skor: <strong>${d.score || 0}/100</strong>${d.volume_spike ? ' | 💥 HACİM PATLAMASI' : ''}</p>
                    <p><em>${d.last_update || 'Bekleniyor...'}</em> | ${d.killzone || 'Normal'} • ${d.triggers || 'Standart'}</p>`;
            };

            currentWs.onerror = () => {
                document.getElementById('status').innerHTML = "⚠️ Bağlantı hatası";
                document.getElementById('status').style.color = "#ff4444";
            };

            currentWs.onclose = () => {
                document.getElementById('status').innerHTML = "❌ Bağlantı kapandı – Yeniden bağlan";
                document.getElementById('status').style.color = "#ff4444";
            };
        }
    </script>
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
</body>
</html>"""

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "time": datetime.now().isoformat(),
        "symbols": len(all_usdt_symbols),
        "rt_coins": len(rt_ticker.get("tickers", {})),
        "ws_total": (
            sum(len(v) for v in single_subscribers.values()) +
            sum(len(v) for v in all_subscribers.values()) +
            len(pump_radar_subscribers)
        )
    }
