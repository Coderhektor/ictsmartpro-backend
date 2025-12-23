# core.py
import asyncio
import json
import logging
import websockets
import httpx
from datetime import datetime
from collections import defaultdict, deque
from utils import exchange, all_usdt_symbols, generate_signal

logger = logging.getLogger("ictsmartpro")

rt_ticker = {"tickers": {}}
top_gainers = []
last_update = "Başlatılıyor..."

shared_signals = {tf: {} for tf in ["realtime", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]}
active_strong_signals = defaultdict(list)

single_subscribers = defaultdict(set)
all_subscribers = defaultdict(set)
pump_radar_subscribers = set()

tasks = []

async def start_realtime_stream():
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
               "PEPEUSDT", "SHIBUSDT", "AVAXUSDT", "TRXUSDT", "LINKUSDT", "DOTUSDT",
               "MATICUSDT", "LTCUSDT"]
    streams = "/".join(f"{s.lower()}@trade" for s in symbols)
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"

    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as ws:
                logger.info("✅ Realtime trade stream aktif")
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)["data"]
                    if data["e"] != "trade":
                        continue
                    symbol = data["s"]
                    price = float(data["p"])
                    qty = float(data["q"])
                    timestamp_ms = data["T"]

                    trades = rt_ticker["tickers"].setdefault(symbol, {
                        "price": price, "trades": deque(maxlen=100)
                    })
                    trades["price"] = price
                    trades["trades"].append((timestamp_ms, price, qty))

                    sig = await generate_signal(symbol, "realtime", price, rt_ticker)
                    if sig:
                        shared_signals["realtime"][symbol] = sig
                        channel = f"{symbol}:realtime"
                        for ws_client in list(single_subscribers[channel]):
                            try:
                                await ws_client.send_json(sig)
                            except:
                                single_subscribers[channel].discard(ws_client)

        except Exception as e:
            logger.warning(f"Trade stream bağlantı hatası: {e}")
            await asyncio.sleep(5)

async def fetch_pump_radar():
    global top_gainers, last_update
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://api.binance.com/api/v3/ticker/24hr")
            data = r.json()

        clean = []
        for item in data:
            sym = item.get("symbol")
            if not sym or not sym.endswith("USDT"):
                continue
            try:
                price = float(item["lastPrice"])
                change = float(item["priceChangePercent"])
                vol = float(item.get("quoteVolume", 0))
                if vol >= 500_000 and abs(change) > 0.5:
                    clean.append({
                        "symbol": sym[:-4] + "/USDT",
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

async def central_scanner():
    timeframes = ["3m", "5m", "15m", "30m", "1h", "4h", "1d"]
    while True:
        try:
            try:
                tickers = await exchange.fetch_tickers(all_usdt_symbols[:100])
            except:
                tickers = {}

            for tf in timeframes:
                strong = []
                for symbol in all_usdt_symbols[:100]:
                    price = rt_ticker["tickers"].get(symbol, {}).get("price")
                    if not price:
                        ticker = tickers.get(symbol)
                        if ticker:
                            price = ticker.get("last") or ticker.get("close")
                    if not price:
                        continue

                    sig = await generate_signal(symbol, tf, price, rt_ticker)
                    if sig:
                        shared_signals[tf][symbol] = sig
                        strong.append(sig)
                    else:
                        shared_signals[tf].pop(symbol, None)

                active_strong_signals[tf] = sorted(
                    strong,
                    key=lambda x: (
                        4 if "GÜÇLÜ ALIM" in x["signal"] else
                        3 if "YUKARI" in x["signal"] else
                        -4 if "GÜÇLÜ SATIM" in x["signal"] else
                        -3
                    ),
                    reverse=True
                )[:40]

                for ws in list(all_subscribers[tf]):
                    try:
                        await ws.send_json(active_strong_signals[tf])
                    except:
                        all_subscribers[tf].discard(ws)

                for symbol, sig in shared_signals[tf].items():
                    channel = f"{symbol}:{tf}"
                    for ws_client in list(single_subscribers[channel]):
                        try:
                            await ws_client.send_json(sig)
                        except:
                            single_subscribers[channel].discard(ws_client)

            await asyncio.sleep(20)

        except Exception as e:
            logger.error(f"Scanner kritik hata: {e}")
            await asyncio.sleep(10)

async def initialize():
    await exchange.load_markets()
    from utils import load_all_symbols
    await load_all_symbols()
    await fetch_pump_radar()

    tasks.append(asyncio.create_task(start_realtime_stream()))
    tasks.append(asyncio.create_task(central_scanner()))

    async def radar_loop():
        while True:
            await asyncio.sleep(30)
            await fetch_pump_radar()
    tasks.append(asyncio.create_task(radar_loop()))

    logger.info("✅ ICT SMART PRO — Tamamen hazır!")

async def cleanup():
    for task in tasks:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    await exchange.close()
