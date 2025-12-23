# core.py
import asyncio
import json
import logging
import websockets
import httpx
import pandas as pd
from datetime import datetime
from collections import defaultdict, deque

from utils import exchange, all_usdt_symbols, fetch_ohlcv  # sadece ihtiyacımız olanlar
from indicators import generate_ict_signal  # YENİ: Gelişmiş ICT sinyal motoru

logger = logging.getLogger("ictsmartpro")

# Global State
rt_ticker = {"tickers": {}}  # Realtime trade verisi
top_gainers = []
last_update = "Başlatılıyor..."

# Sinyaller
shared_signals = {tf: {} for tf in ["realtime", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]}
active_strong_signals = defaultdict(list)

# WebSocket aboneleri
single_subscribers = defaultdict(set)
all_subscribers = defaultdict(set)
pump_radar_subscribers = set()

tasks = []


# ===================== REALTIME TRADE STREAM =====================
async def start_realtime_stream():
    """
    Sadece popüler 15 coini realtime trade ile takip eder.
    Hızlı sinyal için eski basit mantığı koruyoruz (hacim + momentum)
    """
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

                    # Basit realtime sinyal (hızlı tepki için)
                    recent_trades = list(trades["trades"])[-10:]
                    if len(recent_trades) >= 10:
                        prices = [t[1] for t in recent_trades]
                        vols = [t[2] for t in list(trades["trades"])[-20:]]
                        up_moves = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i-1])
                        avg_vol = sum(vols) / len(vols)
                        volume_spike = vols[-1] > avg_vol * 1.8

                        if up_moves >= 7 and volume_spike:
                            signal_text = "💥 REALTIME GÜÇLÜ ALIM!"
                        elif up_moves >= 6:
                            signal_text = "📈 REALTIME YUKARI MOMENTUM"
                        elif up_moves <= 3 and volume_spike:
                            signal_text = "🔥 REALTIME GÜÇLÜ SATIM!"
                        elif up_moves <= 4:
                            signal_text = "📉 REALTIME AŞAĞI MOMENTUM"
                        else:
                            signal_text = None

                        if signal_text:
                            sig = {
                                "pair": f"{symbol[:-4]}/USDT",
                                "timeframe": "realtime",
                                "current_price": round(price, 6 if price < 1 else 4),
                                "signal": signal_text,
                                "momentum": "up" if up_moves > 5 else "down",
                                "last_update": datetime.now().strftime("%H:%M:%S")
                            }
                            shared_signals["realtime"][symbol] = sig
                            channel = f"{symbol}:realtime"
                            for client in list(single_subscribers[channel]):
                                try:
                                    await client.send_json(sig)
                                except:
                                    single_subscribers[channel].discard(client)

        except Exception as e:
            logger.warning(f"Realtime stream hatası: {e}")
            await asyncio.sleep(5)


# ===================== PUMP RADAR =====================
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


# ===================== MERKEZİ TARAMA (GELİŞMİŞ ICT SİNYALLERİ) =====================
async def central_scanner():
    timeframes = ["3m", "5m", "15m", "30m", "1h", "4h", "1d"]
    while True:
        try:
            for tf in timeframes:
                strong = []
                for symbol in all_usdt_symbols[:100]:  # En hacimli 100 coin
                    try:
                        # OHLCV verisini al (en az 150 mum olsun ki paternler hesaplanabilsin)
                        ohlcv = await fetch_ohlcv(symbol, tf, limit=200)
                        if len(ohlcv) < 100:
                            continue

                        # Pandas DataFrame'e çevir
                        df = pd.DataFrame(
                            ohlcv,
                            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
                        )

                        # Gelişmiş ICT sinyalini indicators.py'den al
                        sig = generate_ict_signal(df, symbol, tf)
                        if sig:
                            shared_signals[tf][symbol] = sig
                            strong.append(sig)
                        else:
                            shared_signals[tf].pop(symbol, None)

                    except Exception as e:
                        logger.debug(f"{symbol} {tf} tarama hatası: {e}")
                        continue

                # Güçlü sinyalleri sırala ve yayınla
                active_strong_signals[tf] = sorted(
                    strong,
                    key=lambda x: x.get("score", 0),
                    reverse=True
                )[:40]

                # Tüm timeframe abonelerine gönder
                for ws in list(all_subscribers[tf]):
                    try:
                        await ws.send_json(active_strong_signals[tf])
                    except:
                        all_subscribers[tf].discard(ws)

                # Tekil coin abonelerine gönder
                for symbol, sig in shared_signals[tf].items():
                    channel = f"{symbol}:{tf}"
                    for ws_client in list(single_subscribers[channel]):
                        try:
                            await ws_client.send_json(sig)
                        except:
                            single_subscribers[channel].discard(ws_client)

            await asyncio.sleep(25)  # Her tur ~3-4 dk sürer, rate limit için güvenli

        except Exception as e:
            logger.error(f"Central scanner kritik hata: {e}")
            await asyncio.sleep(15)


# ===================== INIT & CLEANUP =====================
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

    logger.info("✅ ICT SMART PRO — Gelişmiş ICT Sinyalleriyle Hazır!")


async def cleanup():
    for task in tasks:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    await exchange.close()
