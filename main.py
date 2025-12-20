# ==============================
# ICT SMART PRO — GERÇEK ZAMANLI SİNYAL BOTU (KUSURSUZ & RAILWAY ÇALIŞIR)
# ==============================

import asyncio
import json
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

shared_signals = {
    "realtime": {}, "3m": {}, "5m": {}, "15m": {}, "30m": {},
    "1h": {}, "4h": {}, "1d": {}, "1w": {}
}

active_strong_signals = defaultdict(list)

single_subscribers = defaultdict(set)
all_subscribers = defaultdict(set)
pump_radar_subscribers = set()

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
    await fetch_pump_radar()
    asyncio.create_task(rt_ticker.start())
    asyncio.create_task(central_scanner())

    async def radar_loop():
        while True:
            await asyncio.sleep(30)
            await fetch_pump_radar()
    asyncio.create_task(radar_loop())

    logger.info("🚀 ICT SMART PRO — Kusursuz şekilde hazır!")

# --- ANA SAYFA (WebSocket Radar) ---
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
        ws.onerror = () => document.getElementById('update').innerHTML = "<span style='color:#ff4444'>Bağlantı hatası</span>";
    </script>
</body>
</html>"""

# --- GİRİŞ, TEK COİN, TÜM COİNLER, ABONELİK (önceki gibi, değişmedi)

# __name__ == "__main__" BLOĞU YOK — Railway kendi çalıştırıyor
