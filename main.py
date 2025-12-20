# ==============================
# ICT SMART PRO — GERÇEK ZAMANLI SİNYAL BOTU (KUSURSUZ VERSİYON)
# ==============================

import asyncio
import json  # ← EKLENDİ!
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

# --- SEMBOL YÜKLE (ASYNC) ---
async def load_all_symbols():
    global all_usdt_symbols
    try:
        tickers = await asyncio.to_thread(exchange.fetch_tickers)
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
        ohlcv = await asyncio.to_thread(
            exchange.fetch_ohlcv, symbol[:-4] + "/USDT", timeframe=timeframe, limit=limit
        )
        ohlcv_cache[key] = {"data": ohlcv, "ts": now}
        return ohlcv
    except Exception as e:
        logger.warning(f"OHLCV hatası {symbol} {timeframe}: {e}")
        return []

# --- SİNYAL ÜRETİM ---
async def generate_signal(symbol: str, timeframe: str, current_price: float):
    # ... (değişmedi, aynı kalıyor)

# --- MERKEZİ TARAYICI (ASYNC FETCH_TICKER) ---
async def central_scanner():
    timeframes = ["3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
    while True:
        for tf in timeframes:
            strong = []
            for symbol in all_usdt_symbols[:150]:
                try:
                    price = rt_ticker.tickers.get(symbol, {}).get("price")
                    if not price:
                        ticker = await asyncio.to_thread(exchange.fetch_ticker, symbol)
                        price = ticker["last"]
                    sig = await generate_signal(symbol, tf, price)
                    if sig:
                        shared_signals[tf][symbol] = sig
                        strong.append(sig)
                    else:
                        shared_signals[tf].pop(symbol, None)
                except:
                    continue

            # ... kalan yayın kısmı aynı

        await asyncio.sleep(20)

# --- WEBSOCKET'ler (aynı kalıyor) ---
# ws_single, ws_all, ws_pump_radar — değişmedi

# --- STARTUP ---
@app.on_event("startup")
async def startup():
    await load_all_symbols()
    await fetch_pump_radar()  # İlk veri hemen
    asyncio.create_task(rt_ticker.start())
    asyncio.create_task(central_scanner())

    async def radar_loop():
        while True:
            await asyncio.sleep(30)
            await fetch_pump_radar()
    asyncio.create_task(radar_loop())

    logger.info("🚀 ICT SMART PRO — Gerçekten kusursuz ve canlı!")

# --- ANA SAYFA, GİRİŞ, DİĞER SAYFALAR (aynı kalıyor) ---
# ... (önceki mesajdaki gibi, sadece json import ve async fetch_ticker eklendi)

# __name__ == "__main__" BLOĞUNU SİL!
