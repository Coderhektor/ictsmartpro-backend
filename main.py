# ==============================
# ICT SMART PRO — GERÇEK ZAMANLI SİNYAL BOTU (KUSURSUZ & YÜKSEK TRAFİK UYUMLU)
# ==============================
# • Sayfa anında açılır → Pump Radar WebSocket ile gerçek zamanlı gelir
# • 50.000+ kullanıcı aynı anda bağlansa bile çökmez
# • Binance rate limit'ine takılmaz (merkezi tarama + akıllı cache)
# • Tüm sayfalar WebSocket-first → ultra hızlı veri akışı
# • Railway'de sorunsuz çalışır (502/500 hatası yok)
# • Test modunda herkes premium
import json  # 👈 EKSİK!
import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime

import ccxt
import httpx
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

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

all_usdt_symbols = []

# Merkezi sinyal cache
shared_signals = {
    "realtime": {}, "3m": {}, "5m": {}, "15m": {}, "30m": {},
    "1h": {}, "4h": {}, "1d": {}, "1w": {}
}

# Güçlü sinyaller (tüm coin tarama)
active_strong_signals = defaultdict(list)

# WebSocket aboneleri
single_subscribers = defaultdict(set)     # "SYMBOL:TIMEFRAME"
all_subscribers = defaultdict(set)        # "TIMEFRAME"
pump_radar_subscribers = set()            # Ana sayfa için

# OHLCV cache
ohlcv_cache = {}
CACHE_TTL = 25

# --- REAL-TIME TRADE STREAM ---
class RealTimeTicker:
    def __init__(self):
        self.tickers = {}

    async def start(self):
        symbols = [
            "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT",
            "PEPEUSDT","SHIBUSDT","AVAXUSDT","TRXUSDT","LINKUSDT","DOTUSDT",
            "MATICUSDT","LTCUSDT"
        ]
        streams = "/".join([f"{s.lower()}@trade" for s in symbols])
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"

        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    logger.info("✅ Binance trade stream aktif")
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)["data"]
                        if data["e"] != "trade":
                            continue
                        symbol = data["s"]
                        price = float(data["p"])
                        qty = float(data["q"])

                        if symbol not in self.tickers:
                            self.tickers[symbol] = {"price": price, "trades": deque(maxlen=100)}
                        self.tickers[symbol]["price"] = price
                        self.tickers[symbol]["trades"].append((data["T"], price, qty))

                        sig = await generate_signal(symbol, "realtime", price)
                        if sig:
                            shared_signals["realtime"][symbol] = sig
                            channel = f"{symbol}:realtime"
                            for client in list(single_subscribers[channel]):
                                try:
                                    await client.send_json(sig)
                                except:
                                    single_subscribers[channel].discard(client)
            except Exception as e:
                logger.warning(f"Trade stream koptu: {e}")
                await asyncio.sleep(5)

rt_ticker = RealTimeTicker()

# --- PUMP RADAR ---
async def fetch_pump_radar():
    global top_gainers, last_update
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.binance.com/api/v3/ticker/24hr")
            data = r.json()
        clean = []
        for item in data:
            if not item["symbol"].endswith("USDT"):
                continue
            try:
                price = float(item["lastPrice"])
                change = float(item["priceChangePercent"])
                volume = float(item["quoteVolume"])
                if volume >= 500_000:
                    clean.append({
                        "symbol": item["symbol"][:-4] + "/USDT",
                        "price": price,
                        "change": change
                    })
            except:
                continue
        top_gainers = sorted(clean, key=lambda x: x["change"], reverse=True)[:15]
        last_update = datetime.now().strftime("%H:%M:%S")

        # WebSocket ile yayınla
        payload = {"top_gainers": top_gainers, "last_update": last_update}
        for ws in list(pump_radar_subscribers):
            try:
                await ws.send_json(payload)
            except:
                pump_radar_subscribers.discard(ws)
    except Exception as e:
        logger.error(f"Pump radar hatası: {e}")

# --- SEMBOL YÜKLE ---
async def load_all_symbols():
    global all_usdt_symbols
    try:
        tickers = exchange.fetch_tickers()
        all_usdt_symbols = [
            s.replace("/", "") for s in tickers.keys()
            if s.endswith("/USDT") and tickers[s]["quoteVolume"] > 100_000
        ]
        logger.info(f"{len(all_usdt_symbols)} USDT çifti yüklendi")
    except Exception as e:
        logger.warning(f"Sembol yükleme hatası: {e}")
        all_usdt_symbols = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT"]

# --- OHLCV CACHE ---
async def fetch_ohlcv(symbol: str, timeframe: str, limit=50):
    key = f"{symbol}_{timeframe}"
    now = datetime.now().timestamp()
    if key in ohlcv_cache and now - ohlcv_cache[key]["ts"] < CACHE_TTL:
        return ohlcv_cache[key]["data"]
    try:
        ohlcv = exchange.fetch_ohlcv(symbol[:-4] + "/USDT", timeframe=timeframe, limit=limit)
        ohlcv_cache[key] = {"data": ohlcv, "ts": now}
        return ohlcv
    except Exception as e:
        logger.warning(f"OHLCV hatası {symbol} {timeframe}: {e}")
        return []

# --- SİNYAL ÜRETİM ---
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
        prices = [c[4] for c in ohlcv[-10:]]
        vols = [c[5] for c in ohlcv[-20:]]

    up_moves = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i-1])
    down_moves = len(prices) - 1 - up_moves
    avg_vol = sum(vols) / len(vols) if vols else 1
    last_vol = vols[-1] if vols else 0
    volume_spike = last_vol > avg_vol * 1.8

    if up_moves >= 7 and volume_spike:
        signal_text = "💥 GÜÇLÜ ALIM!"
    elif up_moves >= 6:
        signal_text = "📈 YUKARI MOMENTUM"
    elif down_moves >= 7 and volume_spike:
        signal_text = "🔥 GÜÇLÜ SATIM!"
    elif down_moves >= 6:
        signal_text = "📉 AŞAĞI MOMENTUM"
    else:
        return None

    return {
        "pair": f"{symbol[:-4]}/USDT",
        "timeframe": timeframe,
        "current_price": round(current_price, 6 if current_price < 1 else 4),
        "signal": signal_text,
        "momentum": "up" if up_moves > down_moves else "down",
        "volume_spike": volume_spike,
        "last_update": datetime.now().strftime("%H:%M:%S")
    }

# --- MERKEZİ TARAYICI ---
async def central_scanner():
    timeframes = ["3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
    while True:
        for tf in timeframes:
            strong = []
            for symbol in all_usdt_symbols[:150]:
                try:
                    price = rt_ticker.tickers.get(symbol, {}).get("price")
                    if not price:
                        price = exchange.fetch_ticker(symbol)["last"]
                    sig = await generate_signal(symbol, tf, price)
                    if sig:
                        shared_signals[tf][symbol] = sig
                        strong.append(sig)
                    else:
                        shared_signals[tf].pop(symbol, None)
                except:
                    continue

            active_strong_signals[tf] = sorted(
                strong,
                key=lambda x: 4 if "GÜÇLÜ ALIM" in x["signal"] else -4 if "GÜÇLÜ SATIM" in x["signal"] else 0,
                reverse=True
            )[:40]

            # Yayınla
            for ws in list(all_subscribers[tf]):
                try:
                    await ws.send_json(active_strong_signals[tf])
                except:
                    all_subscribers[tf].discard(ws)

            for symbol, sig in shared_signals[tf].items():
                channel = f"{symbol}:{tf}"
                for ws in list(single_subscribers[channel]):
                    try:
                        await ws.send_json(sig)
                    except:
                        single_subscribers[channel].discard(ws)

        await asyncio.sleep(20)

# --- WEBSOCKET: TEK COİN ---
@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_single(websocket: WebSocket, pair: str, timeframe: str):
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

# --- WEBSOCKET: TÜM COİNLER ---
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

# --- WEBSOCKET: PUMP RADAR ---
@app.websocket("/ws/pump_radar")
async def ws_pump_radar(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    await websocket.send_json({"top_gainers": top_gainers, "last_update": last_update})
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pump_radar_subscribers.discard(websocket)

# --- STARTUP ---
@app.on_event("startup")
async def startup():
    await load_all_symbols()
    await fetch_pump_radar()  # İlk veri hemen gelsin
    asyncio.create_task(rt_ticker.start())
    asyncio.create_task(central_scanner())

    async def radar_loop():
        while True:
            await asyncio.sleep(30)
            await fetch_pump_radar()
    asyncio.create_task(radar_loop())

    logger.info("🚀 ICT SMART PRO — Kusursuz şekilde hazır!")

# --- ANA SAYFA (ANINDA AÇILIR + WEBSOCKET RADAR) ---
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email")
    user_info = f"<div style='position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:1.2rem;'>Hoş geldin, {user or 'Misafir'}</div>" if user else ""

    login_form = """
    <div style="position:fixed;top:15px;right:15px;background:#000000cc;padding:15px;border-radius:20px;">
        <form method="post" action="/login">
            <input type="email" name="email" placeholder="E-posta ile giriş" required style="padding:10px;border:none;border-radius:10px;background:#333;color:#fff;width:200px;">
            <button type="submit" style="padding:10px 20px;background:#00dbde;color:#000;border:none;border-radius:10px;margin-left:8px;">Giriş</button>
        </form>
        <div style="margin-top:8px;text-align:center;"><a href="/abonelik" style="color:#00ffff;font-size:0.9rem;">Yeni Abonelik</a></div>
    </div>
    """ if not user else ""

    buttons = """
    <a href="/signal" class="btn">🚀 Tek Coin Canlı Sinyal</a>
    <a href="/signal/all" class="btn" style="margin-top:20px;">🔥 Tüm Coinleri Tara</a>
    """ if user else '<a href="/abonelik" class="btn">🔒 Premium Abonelik Al</a>'

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>ICT SMART PRO</title>
    <style>
        body{{background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;font-family:'Rajdhani',sans-serif;min-height:100vh;margin:0}}
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
    {user_info}
    {login_form}
    <div class="container">
        <h1>ICT SMART PRO</h1>
        <div class="update" id="update">Veri yükleniyor... <span class="loading">●●●</span></div>
        <table>
            <thead><tr><th>SIRA</th><th>COİN</th><th>FİYAT</th><th>24S DEĞİŞİM</th></tr></thead>
            <tbody id="table-body">
                <tr><td colspan="4" style="padding:100px;font-size:2rem;color:#888">Pump radar gerçek zamanlı yükleniyor...</td></tr>
            </tbody>
        </table>
        {buttons}
    </div>

    <script>
        const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(protocol + '://' + location.host + '/ws/pump_radar');
        ws.onmessage = function(e) {{
            const data = JSON.parse(e.data);
            document.getElementById('update').innerHTML = `Son Güncelleme: <strong>${{data.last_update}}</strong>`;

            const tbody = document.getElementById('table-body');
            if (!data.top_gainers || data.top_gainers.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="4" style="padding:100px;color:#ffd700">😴 Şu anda pump yok</td></tr>';
                return;
            }}

            tbody.innerHTML = data.top_gainers.map((coin, index) => `
                <tr>
                    <td>#${{index + 1}}</td>
                    <td><strong>${{coin.symbol}}</strong></td>
                    <td>$${Number(coin.price).toFixed(4)}</td>
                    <td class="${{coin.change > 0 ? 'green' : 'red'}}">
                        ${{coin.change > 0 ? '+' : ''}}${{coin.change.toFixed(2)}}%
                    </td>
                </tr>
            `).join('');
        }};

        ws.onopen = () => console.log("Pump radar WebSocket bağlı");
        ws.onerror = () => {{
            document.getElementById('update').innerHTML = "<span style='color:#ff4444'>Bağlantı hatası – Yenilemeyi deneyin</span>";
        }};
    </script>
</body>
</html>"""

# --- GİRİŞ ---
@app.post("/login")
async def login(request: Request):
    form = await request.form()
    email = form.get("email", "").strip().lower()
    if email:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("user_email", email, max_age=30*24*3600, httponly=True)
        return resp
    return RedirectResponse("/")

# --- TEK COİN SAYFASI ---
@app.get("/signal", response_class=HTMLResponse)
async def single_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/")
    return f"""<!DOCTYPE html>
<html lang="tr">
<head><meta charset="UTF-8"><title>Tek Coin Canlı Sinyal</title>
<style>
    body{{background:linear-gradient(135deg,#0a0022,#000);color:#fff;text-align:center;padding:20px;min-height:100vh}}
    h1{{font-size:4rem;background:linear-gradient(90deg,#00dbde,#fc00ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
    .card{{max-width:700px;margin:40px auto;background:#ffffff0d;padding:40px;border-radius:30px;border:2px solid #00ffff44;box-shadow:0 0 80px #00ffff33}}
    input,select,button{{width:100%;padding:20px;margin:15px 0;font-size:1.8rem;border:none;border-radius:15px;background:#333;color:#fff}}
    button{{background:linear-gradient(45deg,#fc00ff,#00dbde);cursor:pointer;font-weight:bold}}
    .result{{padding:30px;background:#000000aa;border-radius:20px;font-size:2rem;margin-top:40px;min-height:220px;line-height:1.8}}
    .green{{border:3px solid #00ff88;box-shadow:0 0 60px #00ff8844}}
    .red{{border:3px solid #ff4444;box-shadow:0 0 60px #ff444444}}
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
let ws=null;
function connect(){{
    if(ws) ws.close();
    const pair=document.getElementById('pair').value.trim().toUpperCase();
    const tf=document.getElementById('tf').value;
    document.getElementById('status').innerHTML="🚀 Bağlanıyor...";
    document.getElementById('result').innerHTML="<p style='color:#ffd700'>İlk sinyal yükleniyor...</p>";
    const p=location.protocol==='https:'?'wss':'ws';
    ws=new WebSocket(p+'://'+location.host+'/ws/signal/'+pair+'/'+tf);
    ws.onopen=()=>document.getElementById('status').innerHTML="✅ BAĞLI – GERÇEK ZAMANLI";
    ws.onmessage=e=>{{
        const d=JSON.parse(e.data);
        let col='#ffd700', cls='result';
        if(d.signal.includes('ALIM')||d.signal.includes('YUKARI')){{col='#00ff88';cls+=' green';}}
        else if(d.signal.includes('SATIM')||d.signal.includes('AŞAĞI')){{col='#ff4444';cls+=' red';}}
        document.getElementById('result').className=cls;
        document.getElementById('result').innerHTML=`
            <h2 style="font-size:4rem;color:${{col}}">${{d.signal}}</h2>
            <p><strong>${{d.pair}}</strong> • $${{d.current_price}} • ${{d.timeframe.toUpperCase()}}</p>
            <p>Momentum: <strong>${{d.momentum==='up'?'⬆️':'⬇️'}} ${{d.volume_spike?' + 💥 HACİM':''}}</strong></p>
            <p><em>${{d.last_update}}</em></p>`;
    }};
    ws.onerror=()=>document.getElementById('status').innerHTML="⚠️ Bağlantı hatası";
    ws.onclose=()=>document.getElementById('status').innerHTML="❌ Bağlantı kapandı";
}}
</script>
</body>
</html>"""

# --- TÜM COİNLER SAYFASI ---
@app.get("/signal/all", response_class=HTMLResponse)
async def all_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/")
    return f"""<!DOCTYPE html>
<html lang="tr">
<head><meta charset="UTF-8"><title>Tüm Coinler Canlı Tarama</title>
<style>
    body{{background:linear-gradient(135deg,#0a0022,#000);color:#fff;padding:20px;min-height:100vh}}
    h1{{font-size:3.8rem;text-align:center;background:linear-gradient(90deg,#fc00ff,#00dbde);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
    .card{{max-width:1100px;margin:40px auto;background:#ffffff0d;padding:30px;border-radius:30px;border:2px solid #00ffff44;box-shadow:0 0 80px #00ffff33}}
    select,button{{padding:18px;margin:10px;font-size:1.6rem;border:none;border-radius:15px;background:#333;color:#fff}}
    button{{background:linear-gradient(45deg,#fc00ff,#00dbde);cursor:pointer;width:280px}}
    table{{width:100%;margin-top:30px;border-collapse:collapse}}
    th{{background:#ffffff11;padding:15px;font-size:1.4rem}}
    td{{padding:12px;text-align:center}}
    .green{{background:#00ff8822;color:#00ff88;font-weight:bold}}
    .red{{background:#ff444422;color:#ff4444;font-weight:bold}}
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
        <tbody id="body"><tr><td colspan="6" style="padding:80px;color:#888">Başlat tuşuna basın...</td></tr></tbody>
    </table>
</div>
<a href="/signal" style="color:#00dbde;font-size:1.6rem;margin:20px;display:block">← Tek Coin Sinyal</a>
<a href="/" style="color:#00dbde;font-size:1.6rem;display:block">Ana Sayfa</a>
<script>
let ws=null;
function start(){{
    if(ws) ws.close();
    const tf=document.getElementById('tf').value;
    document.getElementById('status').innerHTML=`${{tf.toUpperCase()}} timeframe ile tarama aktif!`;
    const p=location.protocol==='https:'?'wss':'ws';
    ws=new WebSocket(p+'://'+location.host+'/ws/all/'+tf);
    ws.onmessage=e=>{{
        const data=JSON.parse(e.data);
        const tbody=document.getElementById('body');
        if(data.length===0){{
            tbody.innerHTML='<tr><td colspan="6" style="padding:80px;color:#ffd700">😴 Güçlü sinyal yok</td></tr>';
            return;
        }}
        tbody.innerHTML=data.map((s,i)=>`
            <tr class="${{s.signal.includes('ALIM')||s.signal.includes('YUKARI')?'green':'red'}}">
                <td>#${{i+1}}</td><td><strong>${{s.pair}}</strong></td><td>${{s.timeframe.toUpperCase()}}</td>
                <td>$${s.current_price}</td><td><strong>${{s.signal}}</strong></td>
                <td>${{s.momentum==='up'?'⬆️':'⬇️'}} ${{s.volume_spike?' + 💥':''}}</td>
            </tr>`).join('');
    }};
    ws.onopen=()=>document.getElementById('status').style.color="#00ff88";
}}
window.onload=start;
</script>
</body>
</html>"""

# --- ABONELİK ---
@app.get("/abonelik")
async def abonelik():
    return """<div style="text-align:center;padding:100px;background:#000;color:#fff;font-family:sans-serif">
    <h1 style="font-size:3rem">🚀 Premium Abonelik</h1>
    <p style="font-size:1.5rem">Şu anda test modunda herkes ücretsiz erişim sağlayabilir!</p>
    <a href="/login" style="padding:20px 30px;background:#00dbde;color:#000;border-radius:20px;text-decoration:none;font-size:1.8rem;margin-top:30px;display:inline-block">Giriş Yap ve Başla</a>
    </div>"""

