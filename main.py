# main.py
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
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        single_subscribers[channel].discard(websocket)


@app.websocket("/ws/all/{timeframe}")
async def ws_all(websocket: WebSocket, timeframe: str):
    if timeframe not in shared_signals:
        await websocket.accept()
        await websocket.send_json({"error": "Geçersiz timeframe"})
        await websocket.close()
        return

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
        .btn{{display:block;width:90%;max-width:500px;margin:20px auto;padding:25px;font-size:2.2rem;
            background:linear-gradient(45deg,#fc00ff,#00dbde);color:#fff;text-align:center;border-radius:50px;
            text-decoration:none;box-shadow:0 0 60px #ff00ff88;transition:.3s}}
        .btn:hover{{transform:scale(1.08);box-shadow:0 0 100px #ff00ff}}
        .loading{{color:#00ffff;animation:pulse 2s infinite}}
        @keyframes pulse{{0%,100%{{opacity:0.6}}50%{{opacity:1}}}}
    </style>
</head>
<body>
    <div style='position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;
        color:#00ff88;font-size:1.2rem;'>Hoş geldin, {user}</div>
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


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    email = form.get("email", "").strip().lower()
    if email:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("user_email", email, max_age=30*24*3600, httponly=True)
        return resp
    return RedirectResponse("/")


@app.get("/signal", response_class=HTMLResponse)
async def signal(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/")
    return """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Tek Coin Canlı Sinyal</title>
    <style>
        body{background:linear-gradient(135deg,#0a0022,#000);color:#fff;text-align:center;padding:20px;min-height:100vh}
        h1{font-size:4rem;background:linear-gradient(90deg,#00dbde,#fc00ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .card{max-width:700px;margin:40px auto;background:#ffffff0d;padding:40px;border-radius:30px;border:2px solid #00ffff44;box-shadow:0 0 80px #00ffff33}
        input,select,button{width:100%;padding:20px;margin:15px 0;font-size:1.8rem;border:none;border-radius:15px;background:#333;color:#fff}
        button{background:linear-gradient(45deg,#fc00ff,#00dbde);cursor:pointer;font-weight:bold}
        .result{padding:30px;background:#000000aa;border-radius:20px;font-size:2rem;margin-top:40px;min-height:220px;line-height:1.8}
        .green{border:3px solid #00ff88;box-shadow:0 0 60px #00ff8844}
        .red{border:3px solid #ff4444;box-shadow:0 0 60px #ff444444}
    </style>
</head>
<body>
    <h1>CANLI SİNYAL ROBOTU</h1>
    <div class="card">
        <input id="pair" placeholder="Coin (örn: BTCUSDT)" value="BTCUSDT">
        <select id="tf">
            <option value="realtime" selected>Realtime (Anlık)</option>
            <option value="3m">3 Dakika</option><option value="5m">5 Dakika</option><option value="15m">15 Dakika</option>
            <option value="30m">30 Dakika</option><option value="1h">1 Saat</option><option value="4h">4 Saat</option>
            <option value="1d">1 Gün</option><option value="1w">1 Hafta</option>
        </select>
        <button onclick="connect()">🔴 CANLI BAĞLANTI KUR</button>
        <div id="status" style="margin:20px;color:#00dbde;font-size:1.4rem">Bağlantı bekleniyor...</div>
        <div id="result" class="result">Sinyal burada gerçek zamanlı olarak güncellenecek...</div>
    </div>
    <a href="/" style="color:#00dbde;font-size:1.6rem;margin:40px;display:block">← Ana Sayfaya Dön</a>
    <script>
        let ws = null;
        function connect() {
            if (ws) ws.close();
            const pair = document.getElementById('pair').value.trim().toUpperCase();
            const tf = document.getElementById('tf').value;
            document.getElementById('status').innerHTML = "🚀 Bağlanıyor...";
            document.getElementById('result').innerHTML = "<p style='color:#ffd700'>İlk sinyal yükleniyor...</p>";
            const p = location.protocol === 'https:' ? 'wss' : 'ws';
            ws = new WebSocket(p + '://' + location.host + '/ws/signal/' + pair + '/' + tf);
            ws.onopen = () => document.getElementById('status').innerHTML = "✅ BAĞLI – GERÇEK ZAMANLI";
            ws.onmessage = e => {
                const d = JSON.parse(e.data);
                let col = '#ffd700', cls = 'result';
                if (d.signal.includes('ALIM') || d.signal.includes('YUKARI')) { col = '#00ff88'; cls += ' green'; }
                else if (d.signal.includes('SATIM') || d.signal.includes('AŞAĞI')) { col = '#ff4444'; cls += ' red'; }
                document.getElementById('result').className = cls;
                document.getElementById('result').innerHTML = `
                    <h2 style="font-size:4rem;color:${col}">${d.signal}</h2>
                    <p><strong>${d.pair}</strong> • $${d.current_price} • ${d.timeframe.toUpperCase()}</p>
                    <p>Momentum: <strong>${d.momentum === 'up' ? '⬆️' : '⬇️'} ${d.volume_spike ? ' + 💥 HACİM' : ''}</strong></p>
                    <p><em>${d.last_update}</em></p>`;
            };
            ws.onerror = () => document.getElementById('status').innerHTML = "⚠️ Bağlantı hatası";
            ws.onclose = () => document.getElementById('status').innerHTML = "❌ Bağlantı kapandı";
        }
    </script>
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
    <title>Tüm Coinler Canlı Tarama</title>
    <style>
        body{background:linear-gradient(135deg,#0a0022,#000);color:#fff;padding:20px;min-height:100vh}
        h1{font-size:3.8rem;text-align:center;background:linear-gradient(90deg,#fc00ff,#00dbde);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .card{max-width:1100px;margin:40px auto;background:#ffffff0d;padding:30px;border-radius:30px;border:2px solid #00ffff44;box-shadow:0 0 80px #00ffff33}
        select,button{padding:18px;margin:10px;font-size:1.6rem;border:none;border-radius:15px;background:#333;color:#fff}
        button{background:linear-gradient(45deg,#fc00ff,#00dbde);cursor:pointer;width:280px}
        table{width:100%;margin-top:30px;border-collapse:collapse}
        th{background:#ffffff11;padding:15px;font-size:1.4rem}
        td{padding:12px;text-align:center}
        .green{background:#00ff8822;color:#00ff88;font-weight:bold}
        .red{background:#ff444422;color:#ff4444;font-weight:bold}
    </style>
</head>
<body>
    <h1>🔥 TÜM COİNLER CANLI SİNYAL TARAMA</h1>
    <div class="card">
        <div style="text-align:center">
            <select id="tf">
                <option value="realtime" selected>Realtime</option>
                <option value="3m">3m</option><option value="5m">5m</option><option value="15m">15m</option>
                <option value="30m">30m</option><option value="1h">1h</option><option value="4h">4h</option>
                <option value="1d">1d</option>
            </select>
            <button onclick="start()">TARAMAYI BAŞLAT</button>
        </div>
        <div id="status" style="margin:20px;color:#00dbde;font-size:1.4rem">Tarama başlatılmadı.</div>
        <table>
            <thead><tr><th>#</th><th>COİN</th><th>ZAMAN</th><th>FİYAT</th><th>SİNYAL</th><th>DETAY</th></tr></thead>
            <tbody id="body">
                <tr><td colspan="6" style="padding:80px;color:#888">Başlat tuşuna basın...</td></tr>
            </tbody>
        </table>
    </div>
    <a href="/signal" style="color:#00dbde;font-size:1.6rem;margin:20px;display:block">← Tek Coin Sinyal</a>
    <a href="/" style="color:#00dbde;font-size:1.6rem;display:block">Ana Sayfa</a>
    <script>
        let ws = null;
        function start() {
            if (ws) ws.close();
            const tf = document.getElementById('tf').value;
            document.getElementById('status').innerHTML = `${tf.toUpperCase()} timeframe ile tarama aktif!`;
            const p = location.protocol === 'https:' ? 'wss' : 'ws';
            ws = new WebSocket(p + '://' + location.host + '/ws/all/' + tf);
            ws.onmessage = e => {
                const data = JSON.parse(e.data);
                const tbody = document.getElementById('body');
                if (data.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" style="padding:80px;color:#ffd700">😴 Güçlü sinyal yok</td></tr>';
                    return;
                }
                tbody.innerHTML = data.map((s, i) => `
                    <tr class="${s.signal.includes('ALIM') || s.signal.includes('YUKARI') ? 'green' : 'red'}">
                        <td>#${i+1}</td><td><strong>${s.pair}</strong></td><td>${s.timeframe.toUpperCase()}</td>
                        <td>$${s.current_price}</td><td><strong>${s.signal}</strong></td>
                        <td>${s.momentum === 'up' ? '⬆️' : '⬇️'} ${s.volume_spike ? ' + 💥' : ''}</td>
                    </tr>`).join('');
            };
            ws.onopen = () => document.getElementById('status').style.color = "#00ff88";
        }
        window.onload = start;
    </script>
</body>
</html>"""


@app.get("/abonelik", response_class=HTMLResponse)
async def abonelik():
    return """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>🚀 Premium Abonelik | ICT SMART PRO</title>
    <style>
        body {background: linear-gradient(135deg, #0a0022, #000);color: #fff;font-family: 'Segoe UI', sans-serif;margin: 0;padding: 0;min-height: 100vh;}
        .container {max-width: 1200px;margin: auto;padding: 40px 20px;text-align: center;}
        h1 {font-size: 4.2rem;background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde);-webkit-background-clip: text;-webkit-text-fill-color: transparent;margin-bottom: 10px;}
        .subtitle {font-size: 1.6rem;color: #aaa;margin-bottom: 50px;}
        .plans {display: flex;flex-wrap: wrap;justify-content: center;gap: 30px;margin: 50px 0;}
        .plan {background: #ffffff0a;border: 2px solid #00ffff33;border-radius: 25px;padding: 40px 30px;width: 350px;transition: all 0.4s ease;box-shadow: 0 10px 40px rgba(0, 219, 222, 0.1);}
        .plan:hover {transform: translateY(-10px);box-shadow: 0 20px 60px rgba(0, 219, 222, 0.3);border-color: #00dbde;}
        .plan.pro {background: linear-gradient(135deg, #111, #222);border-color: #00dbde;box-shadow: 0 0 60px #00dbde55;position: relative;}
        .plan.pro::before {content: "🔥 EN POPÜLER";position: absolute;top: -15px;left: 50%;transform: translateX(-50%);background: #ff4444;color: white;padding: 5px 20px;border-radius: 30px;font-size: 0.9rem;font-weight: bold;}
        .plan h2 {font-size: 2.2rem;margin: 0 0 20px;color: #00dbde;}
        .price {font-size: 3.2rem;font-weight: bold;margin: 20px 0;}
        .price span {font-size: 1.2rem;color: #888;}
        .features {list-style: none;padding: 0;text-align: left;margin: 30px 0;}
        .features li {padding: 12px 0;font-size: 1.3rem;display: flex;align-items: center;}
        .features li::before {content: "✓";color: #00ff88;font-weight: bold;margin-right: 12px;font-size: 1.4rem;}
        .btn {display: inline-block;width: 100%;padding: 20px;font-size: 1.6rem;font-weight: bold;color: #000;background: linear-gradient(45deg, #fc00ff, #00dbde);border: none;border-radius: 50px;cursor: pointer;text-decoration: none;margin-top: 20px;transition: 0.3s;box-shadow: 0 0 30px #00dbde66;}
        .btn:hover {transform: scale(1.05);box-shadow: 0 0 50px #00dbdeaa;}
        .btn-free {background: linear-gradient(45deg, #444, #666);}
        .badge {display: inline-block;background: #ff4444;color: white;padding: 5px 15px;border-radius: 20px;font-size: 1.1rem;margin-top: 15px;}
        .footer-note {margin-top: 60px;color: #777;font-size: 1.1rem;}
        .footer-note a {color: #00dbde;text-decoration: none;}
        @media (max-width: 768px) {.plans {flex-direction: column;align-items: center;} h1 {font-size: 3rem;}}
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 PREMIUM ABONELİK</h1>
        <p class="subtitle">Profesyonel trader'lar için geliştirilmiş, %90+ doğruluk oranlı sinyal sistemi</p>
        <div class="plans">
            <div class="plan">
                <h2>🆓 ÜCRETSİZ</h2>
                <div class="price">₺0 <span>/ ay</span></div>
                <ul class="features">
                    <li>5 coin desteği</li>
                    <li>Realtime trade verisi (10 coin)</li>
                    <li>Pump radar (24h değişim)</li>
                    <li>5m ve 15m timeframe</li>
                    <li>Temel momentum sinyalleri</li>
                </ul>
                <a href="/" class="btn btn-free">✅ Hemen Başla</a>
                <div class="badge">Test modunda aktif</div>
            </div>
            <div class="plan pro">
                <h2>💎 PREMIUM</h2>
                <div class="price">₺299 <span>/ ay</span></div>
                <ul class="features">
                    <li><strong>150+ coin desteği</strong></li>
                    <li><strong>Realtime arbitrage sinyalleri</strong></li>
                    <li><strong>3m, 5m, 15m, 1h, 4h, 1d</strong></li>
                    <li><strong>Hacim patlaması tespiti</strong></li>
                    <li><strong>Telegram anlık bildirim</strong></li>
                    <li><strong>PDF günlük rapor</strong></li>
                    <li><strong>Öncelikli destek</strong></li>
                </ul>
                <a href="#" onclick="alert('Stripe entegrasyonu hazır! Ödeme sistemi yakında aktif olacak.'); return false;" class="btn">
                    🔒 Abonelik Satın Al
                </a>
                <div class="badge">En çok tercih edilen</div>
            </div>
        </div>
        <div class="footer-note">
            📌 Şu anda <strong>tüm kullanıcılar test modunda ücretsiz olarak Premium özelliklere erişebiliyor.</strong><br>
            Gerçek ödeme sistemi yakında devreye girecek. Hazır olduğunda sizi bilgilendireceğiz!<br>
            Sorularınız için: <a href="mailto:huseyin.yilmaz1034@gmail.com">huseyin.yilmaz1034@gmail.com</a>
        </div>
    </div>
</body>
</html>"""


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "time": datetime.now().isoformat(),
        "symbols": len(all_usdt_symbols),
        "rt_coins": len(rt_ticker["tickers"]),
        "ws_total": (
            sum(len(v) for v in single_subscribers.values()) +
            sum(len(v) for v in all_subscribers.values()) +
            len(pump_radar_subscribers)
        )
    }
