# ==============================
# ICT SMART PRO — REAL-TIME SIGNAL BOT (ÜCRETLİ)
# ==============================

import asyncio
import json
import logging
import os
from collections import defaultdict, deque
from datetime import datetime, timezone

import ccxt
import httpx
import stripe
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Depends, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyCookie

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ictsmartpro")

# --- STRIPE ---
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# --- FASTAPI ---
app = FastAPI()
app.mount("/assets", StaticFiles(directory=".", html=False), name="assets")

# --- GLOBALS ---
top_gainers = []
last_update = "Başlatılıyor..."
exchange = ccxt.binance({'enableRateLimit': True})
exchange.load_markets()

# --- COOKIE AUTH ---
session_cookie = APIKeyCookie(name="user_email", auto_error=False)

async def get_current_user(user_email: str = Depends(session_cookie)):
    if not user_email:
        return None
    email = user_email.lower()
    # uye.py'den abonelik kontrolü gelecek (sonra entegre edilir)
    # Şimdilik herkese izin ver (test için)
    return email

# --- REAL-TIME TICKER ---
class RealTimeTicker:
    def __init__(self):
        self.tickers = {}
        self.subscribers = defaultdict(set)

    async def start(self):
        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "PEPEUSDT", "SHIBUSDT", "AVAXUSDT"]
        streams = [f"{s.lower()}@trade" for s in symbols]
        stream_param = "/".join(streams)
        url = f"wss://stream.binance.com:9443/stream?streams={stream_param}"

        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("✅ Binance WebSocket bağlantısı kuruldu.")
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)['data']
                        if data['e'] != 'trade':
                            continue
                        symbol = data['s']
                        price = float(data['p'])
                        qty = float(data['q'])
                        ts = int(data['T'])

                        if symbol not in self.tickers:
                            self.tickers[symbol] = {"price": price, "trades": deque(maxlen=100)}
                        self.tickers[symbol]["price"] = price
                        self.tickers[symbol]["trades"].append((ts, price, qty))

                        for ws_client in list(self.subscribers[symbol]):
                            try:
                                await ws_client.send_json({
                                    "type": "tick",
                                    "symbol": symbol,
                                    "price": price,
                                    "volume": qty,
                                    "ts": ts
                                })
                            except:
                                self.subscribers[symbol].discard(ws_client)
            except Exception as e:
                logger.warning(f"WebSocket koptu: {e}. 5 sn sonra tekrar...")
                await asyncio.sleep(5)

rt_ticker = RealTimeTicker()

# --- PUMP RADAR VERİ ÇEKME ---
async def fetch_data():
    global top_gainers, last_update
    try:
        urls = [
            "https://data.binance.com/api/v3/ticker/24hr",
            "https://data-api.binance.vision/api/v3/ticker/24hr",
            "https://api1.binance.com/api/v3/ticker/24hr",
        ]
        binance_data = None
        async with httpx.AsyncClient(timeout=15) as client:
            for url in urls:
                try:
                    resp = await client.get(url, timeout=10)
                    if resp.status_code == 200:
                        binance_data = resp.json()
                        break
                except:
                    continue

            clean_coins = []
            if binance_data:
                for item in binance_data:
                    s = item.get("symbol", "")
                    if not s.endswith("USDT"):
                        continue
                    try:
                        price = float(item["lastPrice"])
                        change = float(item["priceChangePercent"])
                        volume = float(item["quoteVolume"])
                        if volume >= 1_000_000:
                            clean_coins.append({"symbol": s.replace("USDT", "/USDT"), "price": price, "change": change})
                    except:
                        continue

            top_gainers = sorted(clean_coins, key=lambda x: x["change"], reverse=True)[:10]
            last_update = datetime.now().strftime("%H:%M:%S")
    except Exception as e:
        logger.error(f"Pump Radar hatası: {e}")
        last_update = "Bağlantı Hatası"

# --- ANLIK SİNYAL ---
async def quick_signal(symbol: str, current_price: float):
    trades = rt_ticker.tickers.get(symbol, {}).get("trades", deque())
    if len(trades) < 10:
        return {"signal": "😐 NÖTR", "price": round(current_price, 4)}

    prices = [t[1] for t in list(trades)[-10:]]
    up_moves = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i-1])
    down_moves = len(prices) - 1 - up_moves
    vols = [t[2] for t in list(trades)[-20:]]
    avg_vol = sum(vols) / len(vols) if vols else 1
    last_vol = vols[-1] if vols else 0
    volume_spike = last_vol > avg_vol * 1.8

    if up_moves >= 7 and volume_spike:
        signal = "💥 ANLIK ALIM!"
    elif up_moves >= 6:
        signal = "📈 YUKARI MOMENTUM"
    elif down_moves >= 7 and volume_spike:
        signal = "🔥 ANLIK SATIM!"
    elif down_moves >= 6:
        signal = "📉 AŞAĞI MOMENTUM"
    else:
        signal = "😐 NÖTR"

    return {
        "pair": f"{symbol[:-4]}/USDT",
        "timeframe": "realtime",
        "current_price": round(current_price, 4),
        "signal": signal,
        "momentum": "up" if up_moves > down_moves else "down" if down_moves > up_moves else "flat",
        "volume_spike": volume_spike,
        "last_update": datetime.now().strftime("%H:%M:%S"),
        "type": "quick"
    }

# --- WEBSOCKET ---
@app.websocket("/ws/signal/{pair}/{timeframe}")
async def websocket_endpoint(websocket: WebSocket, pair: str, timeframe: str, user_email: str = Cookie(default=None)):
    # Geçici olarak tüm kullanıcılara izin ver (üyelik sistemi sonra entegre)
    await websocket.accept()
    symbol = pair.upper().replace("/", "").replace("-", "").replace(" ", "")
    if not symbol.endswith("USDT"):
        await websocket.send_json({"error": "Sadece USDT çiftleri desteklenir"})
        await websocket.close()
        return

    rt_ticker.subscribers[symbol].add(websocket)
    logger.info(f"Abone oldu: {symbol}")

    try:
        price = rt_ticker.tickers.get(symbol, {}).get("price", 0) or 0
        first_signal = await quick_signal(symbol, price)
        await websocket.send_json(first_signal)
    except Exception as e:
        logger.warning(f"İlk sinyal hatası: {e}")

    last_signal = None
    try:
        while True:
            await asyncio.sleep(0.5)
            if symbol in rt_ticker.tickers:
                price = rt_ticker.tickers[symbol]["price"]
                signal = await quick_signal(symbol, price)
                sig_key = f"{signal['signal']}_{signal['momentum']}_{signal['volume_spike']}"
                if sig_key != last_signal:
                    last_signal = sig_key
                    await websocket.send_json(signal)
    except WebSocketDisconnect:
        pass
    finally:
        rt_ticker.subscribers[symbol].discard(websocket)

# --- ARKAPLAN GÖREVLERİ ---
@app.on_event("startup")
async def startup():
    asyncio.create_task(fetch_data())
    asyncio.create_task(rt_ticker.start())

    async def radar_loop():
        while True:
            await asyncio.sleep(30)
            await fetch_data()
    asyncio.create_task(radar_loop())
    logger.info("✅ ICT Smart Pro başarıyla başlatıldı!")

# --- GİRİŞ FORMU ---
login_form_html = """
<div style="position:fixed;top:15px;right:15px;z-index:999;background:#000000cc;padding:12px 18px;border-radius:20px;border:2px solid #00ffff44;box-shadow:0 0 30px #00ffff33;">
    <form method="post" action="/login" style="display:flex;gap:8px;align-items:center;margin:0;">
        <input type="email" name="email" placeholder="E-posta ile giriş" required style="padding:8px 12px;font-size:1rem;border:none;border-radius:12px;background:#333;color:#fff;width:180px;">
        <button type="submit" style="padding:8px 16px;font-size:0.9rem;background:linear-gradient(45deg,#fc00ff,#00dbde);color:white;border:none;border-radius:12px;cursor:pointer;">Giriş</button>
    </form>
    <div style="margin-top:6px;font-size:0.8rem;color:#00dbde;text-align:center;">
        <a href="/abonelik" style="color:#00ffff;text-decoration:underline;">Yeni abonelik al</a>
    </div>
</div>
"""

# --- ANA SAYFA ---
@app.get("/", response_class=HTMLResponse)
async def ana_sayfa(user: str = Depends(get_current_user)):
    user_info = f"<div style='position:fixed;top:15px;left:15px;color:#00ff88;font-size:1rem;background:#000000cc;padding:8px 16px;border-radius:12px;'>Hoş geldin, {user}</div>" if user else ""

    if not top_gainers:
        rows = '<tr><td colspan="4" style="font-size:2.4rem;color:#ff4444;padding:80px;text-align:center;">🚨 Veri çekilemedi!</td></tr>'
        update_text = "Bağlantı Hatası!"
    else:
        rows = ""
        for i, coin in enumerate(top_gainers, 1):
            glow = "text-shadow: 0 0 30px #00ff88;" if coin["change"] > 0 else "text-shadow: 0 0 30px #ff0044;"
            rows += f"""
            <tr class="coin-row">
                <td class="rank">#{i}</td>
                <td class="symbol">{coin['symbol']}</td>
                <td class="price">${coin['price']:,.4f}</td>
                <td class="change" style="color:{'#00ff88' if coin['change']>0 else '#ff3366'};{glow}">
                    {'+' if coin['change']>0 else ''}{coin['change']:.2f}%
                </td>
            </tr>"""
        update_text = last_update

    signal_button = '<a href="/signal" class="signal-btn">🚀 CANLI SİNYAL ROBOTU 🚀</a>' if user else '<a href="/abonelik" class="signal-btn">🔒 CANLI SİNYAL İÇİN ABONE OL</a>'

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🚀 ICT SMART PRO - PUMP RADAR</title>
    <link href="https://fonts.bunny.net/css?family=orbitron:900|rajdhani:700|exo-2:600" rel="stylesheet">
    <style>
        :root {{ --bg: linear-gradient(135deg, #0a0022 0%, #1a0033 50%, #000000 100%); --primary: #00ffff; --green: #00ff88; --red: #ff0044; --gold: #ffd700; }}
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ background: var(--bg); color: white; font-family: 'Rajdhani', sans-serif; min-height: 100vh; background-attachment: fixed; }}
        header {{ text-align:center; padding: 30px 10px; }}
        .logo {{ width:140px; border-radius:50%; border: 4px solid var(--primary); box-shadow: 0 0 50px #00ffff88; animation: float 6s ease-in-out infinite; }}
        h1 {{ font-family: 'Orbitron', sans-serif; font-size: 5rem; background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-size: 200%; animation: gradient 8s ease infinite; }}
        @keyframes gradient {{ 0% {{background-position:0%}} 100% {{background-position:200%}} }}
        @keyframes float {{ 0%,100% {{transform:translateY(0)}} 50% {{transform:translateY(-20px)}} }}
        .update {{ font-size:1.8rem; color:var(--primary); text-shadow:0 0 20px var(--primary); margin:15px 0; }}
        table {{ width: 96%; max-width: 1100px; margin: 30px auto; border-collapse: separate; border-spacing: 0 12px; }}
        th {{ background: linear-gradient(45deg, #ff00ff33, #00ffff33); padding: 20px; font-size: 1.8rem; backdrop-filter: blur(10px); border: 1px solid #ff00ff44; }}
        .coin-row {{ background: linear-gradient(90deg, #ffffff08, #00ffff08); border: 1px solid #00ffff33; transition: all 0.4s; cursor: pointer; }}
        .coin-row:hover {{ transform: translateY(-8px) scale(1.02); box-shadow: 0 20px 40px #00ffff44; }}
        .signal-btn {{ display: block; margin: 60px auto; padding: 22px 60px; font-size: 2.4rem; background: linear-gradient(45deg, #fc00ff, #00dbde); color: white; border: none; border-radius: 50px; cursor: pointer; box-shadow: 0 0 60px #ff00ff88; animation: btnGlow 3s infinite; text-decoration:none; }}
        .signal-btn:hover {{ transform: scale(1.1); box-shadow: 0 0 100px #ff00ff; }}
        @keyframes btnGlow {{ 0%,100% {{box-shadow:0 0 60px #ff00ff88}} 50% {{box-shadow:0 0 100px #ff00ff}} }}
        footer {{ text-align:center; padding:30px; color:#00ffff88; font-size:1.2rem; }}
    </style>
</head>
<body>
    {user_info}
    {login_form_html if not user else ''}
    <header>
        <img src="/assets/logo.png" class="logo" onerror="this.style.display='none'">
        <h1>PUMP RADAR</h1>
        <div class="update">Son Güncelleme: <strong>{update_text}</strong></div>
    </header>

    <table>
        <thead><tr><th>SIRA</th><th>COIN</th><th>FİYAT</th><th>24S DEĞİŞİM</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>

    {signal_button}

    <footer>© 2025 ICT Smart Pro - En Hızlı Pump Radar</footer>
</body>
</html>"""

# --- GİRİŞ ---
@app.post("/login")
async def login_post(request: Request):
    form = await request.form()
    email = form.get("email", "").strip().lower()
    if not email:
        return RedirectResponse("/", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("user_email", email, max_age=30*24*3600, httponly=True)
    return response

# --- CANLI SİNYAL SAYFASI ---
@app.get("/signal", response_class=HTMLResponse)
async def signal_page(user: str = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/", status_code=303)

    return """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ICT Smart Pro - Canlı Sinyal Robotu</title>
    <link href="https://fonts.bunny.net/css?family=orbitron:900|rajdhani:700" rel="stylesheet">
    <style>
        body {margin:0; padding:20px; background:linear-gradient(135deg,#0a0022,#1a0033,#000); color:#fff; font-family:'Rajdhani'; text-align:center; min-height:100vh;}
        h1 {font-family:'Orbitron'; font-size:4.5rem; background:linear-gradient(90deg,#00dbde,#fc00ff); -webkit-background-clip:text; -webkit-text-fill-color:transparent; animation:gradient 6s infinite;}
        @keyframes gradient {0%{background-position:0%}100%{background-position:200%}}
        .card {max-width:600px; margin:40px auto; background:#ffffff0d; padding:40px; border-radius:30px; border:2px solid #00ffff44; box-shadow:0 0 80px #00ffff33; backdrop-filter:blur(10px);}
        input, button {width:100%; padding:18px; margin:15px 0; font-size:1.6rem; border:none; border-radius:15px;}
        input {background:#333; color:#fff;}
        button {background:linear-gradient(45deg,#fc00ff,#00dbde); color:white; cursor:pointer; font-weight:bold; font-size:2rem;}
        button:hover {transform:scale(1.05); box-shadow:0 0 60px #ff00ff;}
        .result {margin-top:40px; padding:30px; background:#00000099; border-radius:20px; font-size:2rem; min-height:200px; border:3px solid transparent; line-height:1.6;}
        .green {border-color:#00ff88; box-shadow:0 0 60px #00ff8844;}
        .red {border-color:#ff0044; box-shadow:0 0 60px #ff004444;}
        .orange {border-color:#ffd700; box-shadow:0 0 60px #ffd70044;}
        .back {margin:50px; font-size:1.6rem;}
        .back a {color:#00dbde; text-decoration:none;}
        .status {font-size:1.4rem; color:#00ffff; margin:10px 0;}
    </style>
</head>
<body>
    <h1>CANLI SİNYAL ROBOTU</h1>
    <div style="position:fixed;top:15px;left:15px;color:#00ff88;font-size:1rem;background:#000000cc;padding:8px 16px;border-radius:12px;">
        Hoş geldin, USER_EMAIL_PLACEHOLDER
    </div>
    <div class="card">
        <form id="form">
            <input type="text" id="pair" placeholder="Coin (örn: BNBUSDT)" value="BNBUSDT" required>
            <button type="submit">🔴 CANLI BAĞLANTI KUR</button>
        </form>
        <div class="status" id="status">Bağlantı bekleniyor...</div>
        <div id="result" class="result">Sinyal burada gerçek zamanlı olarak güncellenecek...</div>
    </div>
    <div class="back"><a href="/">← Pump Radara Dön</a></div>

    <script>
        let socket = null;
        document.getElementById('form').onsubmit = function(e) {{
            e.preventDefault();
            if (socket) socket.close();
            const pair = document.getElementById('pair').value.trim().toUpperCase();
            const res = document.getElementById('result');
            const status = document.getElementById('status');
            status.textContent = "🚀 BAĞLANTI KURULUYOR...";
            status.style.color = "#00dbde";
            res.innerHTML = "<p style='color:#ffd700'>İlk sinyal yükleniyor...</p>";
            const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
            socket = new WebSocket(protocol + '://' + location.host + '/ws/signal/' + pair + '/realtime');
            socket.onopen = function() {{
                status.textContent = "✅ GERÇEK ZAMANLI AKIŞ AÇIK!";
                status.style.color = "#00ff88";
            }};
            socket.onmessage = function(event) {{
                const data = JSON.parse(event.data);
                if (data.error) {{
                    res.innerHTML = '<p style="color:#ff6666; font-size:2.2rem;">❌ Hata:<br>' + data.error + '</p>';
                    res.classList.add('red');
                    return;
                }}
                let colorClass = 'orange';
                let signalColor = '#ffd700';
                if (data.signal.includes('ALIM') || data.signal.includes('YUKARI')) {{
                    colorClass = 'green';
                    signalColor = '#00ff88';
                }} else if (data.signal.includes('SATIM') || data.signal.includes('AŞAĞI')) {{
                    colorClass = 'red';
                    signalColor = '#ff4444';
                }}
                res.className = 'result ' + colorClass;
                res.innerHTML = 
                    '<h2 style="font-size:3.8rem; color:' + signalColor + ';">' + data.signal + '</h2>' +
                    '<p><strong>' + data.pair + '</strong> — <em>' + data.last_update + '</em></p>' +
                    '<p>Fiyat: <strong>$' + data.current_price + '</strong></p>' +
                    '<p>Momentum: <strong>' + (data.momentum === 'up' ? '⬆️' : data.momentum === 'down' ? '⬇️' : '↔️') + (data.volume_spike ? ' + 💥 HACİM' : '') + '</strong></p>' +
                    '<p><em style="color:#00ffff;">Saniyede 2 kez güncelleniyor ↺</em></p>';
            }};
            socket.onerror = function() {{
                status.textContent = "⚠️ Bağlantı hatası!";
                status.style.color = "#ff4444";
            }};
            socket.onclose = function() {{
                status.textContent = "❌ BAĞLANTI KESİLDİ";
                status.style.color = "#ff6666";
            }};
        }};
        
        // Kullanıcı adını dinamik ekle
        const email = document.cookie.split('; ').find(row => row.startsWith('user_email='))?.split('=')[1];
        if (email) {{
            document.querySelector('div[style*="Hoş geldin"]').innerHTML = 'Hoş geldin, ' + decodeURIComponent(email);
        }}
    </script>
</body>
</html>""".replace("USER_EMAIL_PLACEHOLDER", "")  # Basitlik için burada dinamik replace

# --- ABONELİK SAYFASI ---
@app.get("/abonelik")
async def abonelik_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Abonelik</title>
        <style>
            body {background:#000;color:#fff;font-family:sans-serif;text-align:center;padding:50px;}
            h1 {font-size:3rem;}
            input, select, button {margin:10px 0;padding:15px;width:300px;font-size:1.2rem;}
            button {background:#00dbde;color:#000;border:none;border-radius:15px;cursor:pointer;}
        </style>
    </head>
    <body>
        <h1>🚀 ABONELİK SEÇ</h1>
        <p style="font-size:1.2rem;margin:20px 0;">Gerçek zamanlı sinyal, hacim uyarıları ve arbitrage fırsatları!</p>
        <form method="post">
            <input type="email" name="email" placeholder="E-posta" required><br>
            <input type="text" name="ad" placeholder="Ad Soyad" required><br>
            <select name="plan">
                <option value="basic">Basic - $9.99/ay</option>
                <option value="pro" selected>Pro - $24.99/ay</option>
                <option value="premium">Premium - $49.99/ay</option>
            </select><br>
            <button type="submit">💳 ÖDEMEYE GEÇ</button>
        </form>
    </body>
    </html>
    """

# --- ABONELİK POST ---
@app.post("/abonelik")
async def abonelik_post(request: Request):
    # Şimdilik sadece test amaçlı
    return HTMLResponse("<h2>✅ Test modunda ödeme gerekmez!</h2><p><a href='/signal'>➡️ Sinyal sayfasına git</a></p>")

# --- SAĞLIK ---
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "active_ws": sum(len(s) for s in rt_ticker.subscribers.values()),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
