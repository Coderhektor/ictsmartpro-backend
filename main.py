# ==============================
# ICT SMART PRO — GERÇEK ZAMANLI SİNYAL BOTU (PREMIUM)
# ==============================

import asyncio
import json
import logging
import os
from collections import defaultdict, deque
from datetime import datetime

import ccxt
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyCookie

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ictsmartpro")

# --- FASTAPI ---
app = FastAPI()
app.mount("/assets", StaticFiles(directory=".", html=False), name="assets")

# --- GLOBALS ---
top_gainers = []
last_update = "Başlatılıyor..."
exchange = ccxt.binance({'enableRateLimit': True})
exchange.load_markets()

# Tüm USDT çiftleri ve aktif sinyaller
all_usdt_symbols = []
active_signals = []  # Tüm coin tarayıcı için güçlü sinyaller

# OHLCV cache
ohlcv_cache = {}
CACHE_TTL = 25  # saniye

# --- AUTH (Basit cookie ile) ---
session_cookie = APIKeyCookie(name="user_email", auto_error=False)

async def get_current_user(user_email: str = Depends(session_cookie)):
    if not user_email:
        return None
    return user_email.lower()

# --- REAL-TIME TICKER (Sadece popüler coinler için trade stream) ---
class RealTimeTicker:
    def __init__(self):
        self.tickers = {}
        self.subscribers = defaultdict(set)

    async def start(self):
        # Popüler 20 coin için trade stream (performans için sınırlı)
        symbols = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT",
                   "PEPEUSDT","SHIBUSDT","AVAXUSDT","TRXUSDT","LINKUSDT","DOTUSDT",
                   "MATICUSDT","LTCUSDT","BCHUSDT","NEARUSDT","ICPUSDT","UNIUSDT","APTUSDT"]
        streams = [f"{s.lower()}@trade" for s in symbols]
        stream_param = "/".join(streams)
        url = f"wss://stream.binance.com:9443/stream?streams={stream_param}"

        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    logger.info("✅ Binance trade WebSocket bağlantısı kuruldu.")
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

                        # Abonelere gönder
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
                logger.warning(f"Trade WS koptu: {e} — 5sn sonra tekrar bağlanılıyor...")
                await asyncio.sleep(5)

rt_ticker = RealTimeTicker()

# --- PUMP RADAR ---
async def fetch_pump_radar():
    global top_gainers, last_update
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://api.binance.com/api/v3/ticker/24hr")
            data = resp.json()

        clean = []
        for item in data:
            if not item["symbol"].endswith("USDT"):
                continue
            try:
                price = float(item["lastPrice"])
                change = float(item["priceChangePercent"])
                volume = float(item["quoteVolume"])
                if volume >= 500_000:  # Min hacim filtresi
                    clean.append({
                        "symbol": item["symbol"][:-4] + "/USDT",
                        "price": price,
                        "change": change
                    })
            except:
                continue

        top_gainers = sorted(clean, key=lambda x: x["change"], reverse=True)[:15]
        last_update = datetime.now().strftime("%H:%M:%S")
    except Exception as e:
        logger.error(f"Pump radar hatası: {e}")
        last_update = "Bağlantı Hatası"

# --- TÜM USDT SEMBOLLERİNİ YÜKLE ---
async def load_all_symbols():
    global all_usdt_symbols
    try:
        tickers = exchange.fetch_tickers()
        all_usdt_symbols = [s.replace("/", "") for s in tickers.keys() if s.endswith("/USDT") and tickers[s]['quoteVolume'] > 100_000]
        logger.info(f"{len(all_usdt_symbols)} aktif USDT çifti yüklendi.")
    except:
        all_usdt_symbols = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT"]  # fallback

# --- SİNYAL HESAPLAMA ---
async def fetch_ohlcv(symbol: str, timeframe: str, limit=50):
    cache_key = f"{symbol}_{timeframe}"
    now = datetime.now().timestamp()
    if cache_key in ohlcv_cache and now - ohlcv_cache[cache_key]["ts"] < CACHE_TTL:
        return ohlcv_cache[cache_key]["data"]

    try:
        sym_formatted = symbol[:-4] + "/USDT" if "USDT" in symbol else symbol
        ohlcv = exchange.fetch_ohlcv(sym_formatted, timeframe=timeframe, limit=limit)
        ohlcv_cache[cache_key] = {"data": ohlcv, "ts": now}
        return ohlcv
    except Exception as e:
        logger.warning(f"OHLCV hatası {symbol} {timeframe}: {e}")
        return []

async def generate_signal(symbol: str, timeframe: str, current_price: float):
    if timeframe == "realtime":
        trades = rt_ticker.tickers.get(symbol, {}).get("trades", deque())
        if len(trades) < 10:
            return None
        prices = [t[1] for t in list(trades)[-10:]]
        vols = [t[2] for t in list(trades)[-20:]]
    else:
        ohlcv = await fetch_ohlcv(symbol, timeframe)
        if len(ohlcv) < 10:
            return None
        prices = [c[4] for c in ohlcv[-10:]]   # close
        vols = [c[5] for c in ohlcv[-20:]]     # volume

    up_moves = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i-1])
    down_moves = len(prices) - 1 - up_moves
    avg_vol = sum(vols) / len(vols) if vols else 1
    last_vol = vols[-1]
    volume_spike = last_vol > avg_vol * 1.8

    if up_moves >= 7 and volume_spike:
        signal = "💥 GÜÇLÜ ALIM!"
    elif up_moves >= 6:
        signal = "📈 YUKARI MOMENTUM"
    elif down_moves >= 7 and volume_spike:
        signal = "🔥 GÜÇLÜ SATIM!"
    elif down_moves >= 6:
        signal = "📉 AŞAĞI MOMENTUM"
    else:
        return None  # Sadece güçlü sinyalleri göster

    return {
        "pair": f"{symbol[:-4]}/USDT",
        "timeframe": timeframe,
        "current_price": round(current_price, 6 if current_price < 1 else 4),
        "signal": signal,
        "momentum": "up" if up_moves > down_moves else "down",
        "volume_spike": volume_spike,
        "last_update": datetime.now().strftime("%H:%M:%S")
    }

# --- TÜM COİNLERİ TARAMA GÖREVİ ---
async def scan_all_coins(timeframe: str = "realtime"):
    global active_signals
    signals = []
    # Rate limit için max 80-100 coin tarıyoruz
    for symbol in all_usdt_symbols[:100]:
        try:
            price = rt_ticker.tickers.get(symbol, {}).get("price")
            if not price:
                ticker = exchange.fetch_ticker(symbol)
                price = ticker['last']
            sig = await generate_signal(symbol, timeframe, price)
            if sig:
                signals.append(sig)
        except:
            continue

    # Güç sırasına göre sırala
    def strength(s):
        if "GÜÇLÜ ALIM" in s["signal"]: return 4
        if "ALIM" in s["signal"]: return 3
        if "YUKARI MOMENTUM" in s["signal"]: return 2
        if "GÜÇLÜ SATIM" in s["signal"]: return -4
        if "AŞAĞI MOMENTUM" in s["signal"]: return -2
        return 0
    active_signals = sorted(signals, key=strength, reverse=True)[:30]

# --- WEBSOCKET (TEK COİN İÇİN) ---
@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_single_coin(websocket: WebSocket, pair: str, timeframe: str, user_email: str = Cookie(default=None)):
    await websocket.accept()
    symbol = pair.upper().replace("/", "").replace("-", "")
    if not symbol.endswith("USDT"):
        await websocket.send_json({"error": "Sadece USDT çiftleri"})
        await websocket.close()
        return

    if timeframe == "realtime":
        rt_ticker.subscribers[symbol].add(websocket)

    try:
        price = rt_ticker.tickers.get(symbol, {}).get("price") or exchange.fetch_ticker(symbol)['last']
        sig = await generate_signal(symbol, timeframe, price)
        if sig:
            await websocket.send_json(sig)
    except:
        pass

    last_key = None
    try:
        while True:
            await asyncio.sleep(0.5 if timeframe == "realtime" else 25)
            price = rt_ticker.tickers.get(symbol, {}).get("price")
            if not price:
                continue
            sig = await generate_signal(symbol, timeframe, price)
            if sig:
                key = f"{sig['signal']}_{sig['momentum']}"
                if key != last_key:
                    last_key = key
                    await websocket.send_json(sig)
    except WebSocketDisconnect:
        pass
    finally:
        if timeframe == "realtime":
            rt_ticker.subscribers[symbol].discard(websocket)

# --- API: TÜM SİNYALLER ---
@app.get("/api/all-signals")
async def api_all_signals(tf: str = "realtime"):
    await scan_all_coins(tf)  # Manuel tetikleme
    return active_signals

# --- STARTUP ---
@app.on_event("startup")
async def startup():
    await load_all_symbols()
    asyncio.create_task(rt_ticker.start())
    asyncio.create_task(fetch_pump_radar())

    async def radar_loop():
        while True:
            await asyncio.sleep(35)
            await fetch_pump_radar()

    async def scanner_loop():
        tf = "realtime"
        while True:
            await scan_all_coins(tf)
            await asyncio.sleep(22)

    asyncio.create_task(radar_loop())
    asyncio.create_task(scanner_loop())
    logger.info("🚀 ICT SMART PRO başarıyla başlatıldı!")

# --- ANA SAYFA ---
@app.get("/", response_class=HTMLResponse)
async def home(user: str = Depends(get_current_user)):
    user_block = f"<div class='user-info'>Hoş geldin, <strong>{user}</strong> 👤</div>" if user else ""

    rows = ""
    if top_gainers:
        for i, c in enumerate(top_gainers, 1):
            glow = "text-shadow: 0 0 20px #00ff88;" if c["change"] > 0 else "text-shadow: 0 0 20px #ff0044;"
            rows += f"""
            <tr class="coin-row">
                <td>#{i}</td>
                <td class="symbol">{c['symbol']}</td>
                <td>${c['price']:,.4f}</td>
                <td style="color:{'#00ff88' if c['change']>0 else '#ff4444'};{glow}">
                    {'+' if c['change']>0 else ''}{c['change']:.2f}%
                </td>
            </tr>"""
    else:
        rows = '<tr><td colspan="4" style="padding:80px; color:#ff4444;">🚨 Veri yüklenemedi</td></tr>'

    buttons = """
    <a href="/signal" class="btn primary">🚀 Tek Coin Canlı Sinyal</a>
    <a href="/signal/all" class="btn secondary">🔥 Tüm Coinleri Tara (Yeni!)</a>
    """ if user else '<a href="/abonelik" class="btn primary">🔒 Premium Abonelik Al</a>'

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ICT SMART PRO - Pump Radar & Canlı Sinyal</title>
    <link href="https://fonts.bunny.net/css?family=orbitron:900|rajdhani:700" rel="stylesheet">
    <style>
        :root {{--bg: linear-gradient(135deg,#0f001a,#1a0033,#000); --pri:#00ffff; --green:#00ff88; --red:#ff3366;}}
        body {{margin:0; padding:0; background:var(--bg); color:#fff; font-family:'Rajdhani',sans-serif; min-height:100vh;}}
        .container {{max-width:1200px; margin:auto; padding:20px;}}
        header {{text-align:center; padding:40px 0;}}
        .logo {{width:120px; border-radius:50%; border:4px solid var(--pri); box-shadow:0 0 50px #00ffff88; animation:float 6s infinite;}}
        h1 {{font-family:'Orbitron'; font-size:4.5rem; background:linear-gradient(90deg,#00dbde,#fc00ff,#00dbde); -webkit-background-clip:text; -webkit-text-fill-color:transparent; animation:grad 8s infinite;}}
        @keyframes grad{{0%{{background-position:0%}}100%{{background-position:200%}}}}
        @keyframes float{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-20px)}}}}
        .update {{font-size:1.6rem; color:var(--pri); margin:20px 0;}}
        table {{width:100%; border-collapse:separate; border-spacing:0 12px; margin:30px 0;}}
        th {{background:#ffffff11; padding:18px; font-size:1.5rem;}}
        .coin-row {{background:#ffffff08; transition:all .4s;}}
        .coin-row:hover {{transform:scale(1.02); box-shadow:0 15px 40px #00ffff44;}}
        .btn {{display:block; width:90%; max-width:500px; margin:20px auto; padding:22px; font-size:2rem; border-radius:50px; text-decoration:none; text-align:center; box-shadow:0 0 60px #ff00ff88; transition:all .3s;}}
        .primary {{background:linear-gradient(45deg,#fc00ff,#00dbde); color:#fff;}}
        .secondary {{background:linear-gradient(45deg,#00dbde,#fc00ff); color:#fff;}}
        .btn:hover {{transform:scale(1.08);}}
        .user-info {{position:fixed; top:15px; left:15px; background:#000000cc; padding:10px 20px; border-radius:20px; color:#00ff88; font-size:1.1rem;}}
        footer {{text-align:center; padding:40px; color:#00ffff88;}}
    </style>
</head>
<body>
    {user_block}
    <div class="container">
        <header>
            <img src="/assets/logo.png" class="logo" onerror="this.style.display='none'">
            <h1>ICT SMART PRO</h1>
            <div class="update">Son Güncelleme: <strong>{last_update}</strong></div>
        </header>

        <table>
            <thead><tr><th>SIRA</th><th>COİN</th><th>FİYAT</th><th>24S DEĞİŞİM</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>

        <div>{buttons}</div>

        <footer>© 2025 ICT Smart Pro – En Hızlı ve Akıllı Kripto Sinyal Botu</footer>
    </div>

    <!-- Giriş Formu (giriş yapılmadıysa) -->
    {"<div style='position:fixed;top:15px;right:15px;background:#000000cc;padding:15px;border-radius:20px;'><form method='post' action='/login'><input type='email' name='email' placeholder='E-posta ile giriş' required style='padding:10px;border:none;border-radius:10px;background:#333;color:#fff;'><button type='submit' style='padding:10px 20px;margin-left:8px;background:#00dbde;color:#000;border:none;border-radius:10px;'>Giriş</button></form><div style='margin-top:8px;text-align:center;'><a href='/abonelik' style='color:#00ffff;font-size:0.9rem;'>Yeni Abonelik</a></div></div>" if not user else ""}
</body>
</html>"""

# --- GİRİŞ ---
@app.post("/login")
async def login(request: Request):
    form = await request.form()
    email = form.get("email","").strip().lower()
    if email:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("user_email", email, max_age=30*24*3600, httponly=True)
        return resp
    return RedirectResponse("/", status_code=303)

# --- TEK COİN SİNYAL SAYFASI ---
@app.get("/signal", response_class=HTMLResponse)
async def single_signal_page(user: str = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/")
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tek Coin Canlı Sinyal</title>
    <link href="https://fonts.bunny.net/css?family=orbitron:900|rajdhani:700" rel="stylesheet">
    <style>
        body{{background:var(--bg);color:#fff;font-family:'Rajdhani';padding:20px;min-height:100vh;text-align:center;}}
        h1{{font-family:'Orbitron';font-size:4rem;background:linear-gradient(90deg,#00dbde,#fc00ff); -webkit-background-clip:text; -webkit-text-fill-color:transparent;animation:grad 6s infinite;}}
        .card{{max-width:700px;margin:40px auto;background:#ffffff0d;padding:40px;border-radius:30px;border:2px solid #00ffff44;box-shadow:0 0 80px #00ffff33;}}
        input,select,button{{width:100%;padding:20px;margin:15px 0;font-size:1.8rem;border:none;border-radius:15px;}}
        input,select{{background:#333;color:#fff;}}
        button{{background:linear-gradient(45deg,#fc00ff,#00dbde);color:#fff;cursor:pointer;font-weight:bold;}}
        .result{{margin-top:40px;padding:30px;background:#000000aa;border-radius:20px;font-size:2rem;min-height:220px;line-height:1.8;}}
        .green{{border:3px solid #00ff88;box-shadow:0 0 60px #00ff8844;}}
        .red{{border:3px solid #ff4444;box-shadow:0 0 60px #ff444444;}}
        .back{{margin:50px;font-size:1.6rem;}}<a href="/" class="back-link">← Ana Sayfaya Dön</a>
    </style>
</head>
<body>
    <h1>CANLI SİNYAL ROBOTU</h1>
    <div class="card">
        <input type="text" id="pair" placeholder="Coin çifti (örn: BTCUSDT)" value="BTCUSDT">
        <select id="tf">
            <option value="realtime" selected>Realtime (Anlık)</option>
            <option value="3m">3 Dakika</option>
            <option value="5m">5 Dakika</option>
            <option value="15m">15 Dakika</option>
            <option value="30m">30 Dakika</option>
            <option value="1h">1 Saat</option>
            <option value="4h">4 Saat</option>
            <option value="1d">1 Gün</option>
            <option value="1w">1 Hafta</option>
        </select>
        <button onclick="connect()">🔴 CANLI BAĞLANTI KUR</button>
        <div id="status" style="margin:20px;color:#00dbde;">Bağlantı bekleniyor...</div>
        <div id="result" class="result">Sinyal burada görünecek...</div>
    </div>
    <div class="back"><a href="/signal/all">🔥 Tüm coinleri tara →</a> | <a href="/">Ana Sayfa</a></div>

    <script>
        let ws = null;
        function connect(){{
            if(ws) ws.close();
            const pair = document.getElementById('pair').value.trim().toUpperCase();
            const tf = document.getElementById('tf').value;
            document.getElementById('status').innerHTML = "🚀 Bağlanıyor...";
            document.getElementById('result').innerHTML = "<p style='color:#ffd700'>İlk sinyal yükleniyor...</p>";
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(protocol + '//' + location.host + '/ws/signal/' + pair + '/' + tf);
            ws.onopen = () => document.getElementById('status').innerHTML = "✅ BAĞLI – GERÇEK ZAMANLI";
            ws.onmessage = (e) => {{
                const d = JSON.parse(e.data);
                let cls = 'result'; let col = '#ffd700';
                if(d.signal.includes('ALIM') || d.signal.includes('YUKARI')){{ cls+=' green'; col='#00ff88'; }}
                else if(d.signal.includes('SATIM') || d.signal.includes('AŞAĞI')){{ cls+=' red'; col='#ff4444'; }}
                document.getElementById('result').className = cls;
                document.getElementById('result').innerHTML = `
                    <h2 style="font-size:4rem;color:${{col}}">${{d.signal}}</h2>
                    <p><strong>${{d.pair}}</strong> • ${{d.current_price}} • ${{d.timeframe.toUpperCase()}}</p>
                    <p>Momentum: <strong>${{d.momentum==='up'?'⬆️':'⬇️'}}${{d.volume_spike?' + 💥 HACİM':''}}</strong></p>
                    <p><em>Son güncelleme: ${{d.last_update}}</em></p>`;
            }};
            ws.onerror = () => document.getElementById('status').innerHTML = "⚠️ Bağlantı hatası";
            ws.onclose = () => document.getElementById('status').innerHTML = "❌ Bağlantı kapandı";
        }}
    </script>
</body>
</html>"""

# --- TÜM COİNLER SİNYAL TARAMA SAYFASI ---
@app.get("/signal/all", response_class=HTMLResponse)
async def all_signals_page(user: str = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/")
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tüm Coinler Canlı Tarama</title>
    <link href="https://fonts.bunny.net/css?family=orbitron:900|rajdhani:700" rel="stylesheet">
    <style>
        body{{background:var(--bg);color:#fff;font-family:'Rajdhani';padding:20px;min-height:100vh;}}
        h1{{font-family:'Orbitron';font-size:3.8rem;background:linear-gradient(90deg,#fc00ff,#00dbde); -webkit-background-clip:text; -webkit-text-fill-color:transparent;animation:grad 8s infinite;}}
        .card{{max-width:1100px;margin:40px auto;background:#ffffff0d;padding:30px;border-radius:30px;border:2px solid #00ffff44;box-shadow:0 0 80px #00ffff33;}}
        select,button{{padding:18px;margin:10px;font-size:1.6rem;border:none;border-radius:15px;background:#333;color:#fff;}}
        button{{background:linear-gradient(45deg,#fc00ff,#00dbde);cursor:pointer;width:280px;}}
        table{{width:100%;margin-top:30px;border-collapse:collapse;}}
        th{{background:#ffffff11;padding:15px;font-size:1.4rem;}}
        td{{padding:12px;text-align:center;}}
        .green{{background:#00ff8822;color:#00ff88;font-weight:bold;}}
        .red{{background:#ff444422;color:#ff4444;font-weight:bold;}}
        .back{{margin:40px;text-align:center;}}
    </style>
</head>
<body>
    <h1>🔥 TÜM COİNLER CANLI SİNYAL TARAMA</h1>
    <div class="card">
        <div style="text-align:center;">
            <select id="tf">
                <option value="realtime" selected>Realtime (Anlık)</option>
                <option value="3m">3 Dakika</option>
                <option value="5m">5 Dakika</option>
                <option value="15m">15 Dakika</option>
                <option value="30m">30 Dakika</option>
                <option value="1h">1 Saat</option>
                <option value="4h">4 Saat</option>
                <option value="1d">1 Gün</option>
            </select>
            <button onclick="start()">TARAMAYI BAŞLAT</button>
        </div>
        <div id="status" style="margin:20px;color:#00dbde;font-size:1.4rem;">Tarama başlatılmadı.</div>
        <table id="tbl">
            <thead><tr><th>#</th><th>COİN</th><th>ZAMAN</th><th>FİYAT</th><th>SİNYAL</th><th>DETAY</th></tr></thead>
            <tbody id="body"><tr><td colspan="6" style="padding:80px;color:#888;">Tarama başlatın...</td></tr></tbody>
        </table>
    </div>
    <div class="back"><a href="/signal">← Tek Coin Sinyal</a> | <a href="/">Ana Sayfa</a></div>

    <script>
        let intv = null;
        function start(){{
            if(intv) clearInterval(intv);
            const tf = document.getElementById('tf').value;
            document.getElementById('status').innerHTML = `✅ ${{tf.toUpperCase()}} timeframe ile tarama aktif! (Her ~20sn güncellenir)`;
            fetch(`/api/all-signals?tf=${{tf}}`).then(r=>r.json()).then(update);
            intv = setInterval(()=> fetch(`/api/all-signals?tf=${{tf}}`).then(r=>r.json()).then(update), 20000);
        }}
        function update(data){{
            const tbody = document.getElementById('body');
            if(data.length===0){{ tbody.innerHTML = `<tr><td colspan="6" style="padding:80px;color:#ffd700;">😴 Şu anda güçlü sinyal yok</td></tr>`; return; }}
            tbody.innerHTML = data.map((s,i)=>`
                <tr class="${{s.signal.includes('ALIM')||s.signal.includes('YUKARI')?'green':'red'}}">
                    <td>#${{i+1}}</td>
                    <td><strong>${{s.pair}}</strong></td>
                    <td>${{s.timeframe.toUpperCase()}}</td>
                    <td>$${s.current_price}</td>
                    <td><strong>${{s.signal}}</strong></td>
                    <td>${{s.momentum==='up'?'⬆️':'⬇️'}}${{s.volume_spike?' + 💥':''}}</td>
                </tr>`).join('');
        }}
    </script>
</body>
</html>"""

# --- ABONELİK (TEST MODU) ---
@app.get("/abonelik")
async def subscription():
    return """<html><head><title>Abonelik</title><style>body{background:#000;color:#fff;text-align:center;padding:100px;font-family:sans-serif;}</style></head>
    <body><h1>🚀 Premium Abonelik</h1><p>Şu anda test modunda herkes erişim sağlayabilir!</p>
    <a href="/login" style="padding:20px;background:#00dbde;color:#000;text-decoration:none;border-radius:20px;font-size:1.5rem;">Giriş Yap ve Başla</a></body></html>"""

@app.post("/abonelik")
async def sub_post():
    return HTMLResponse("<h2 style='color:#00ff88;text-align:center;padding:100px;background:#000;'>✅ Test modunda ödeme gerekmez!<br><a href='/'>Ana sayfaya git</a></h2>")
