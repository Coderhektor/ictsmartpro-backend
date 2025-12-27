# core.py — DÜZELTİLMİŞ — Railway deploy için hazır
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Set, List
from fastapi import WebSocket
import pandas as pd

logger = logging.getLogger("broadcast")

# ========== GLOBAL STATE ==========
single_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)
all_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)
pump_radar_subscribers: Set[WebSocket] = set()
realtime_subscribers: Set[WebSocket] = set()

shared_signals: Dict[str, Dict[str, dict]] = defaultdict(dict)
active_strong_signals: Dict[str, List[dict]] = defaultdict(list)

top_gainers: List[dict] = []
last_update: str = "Yükleniyor..."

rt_ticker = {
    "tickers": {},
    "last_update": ""
}

# ========== Broadcast Queue ==========
signal_queue: asyncio.Queue = asyncio.Queue(maxsize=500)

# ==================== BROADCAST WORKER ====================
async def broadcast_worker():
    logger.info("📡 Broadcast worker başladı")
    while True:
        try:
            msg_type, payload = await signal_queue.get()

            if msg_type == "signal":
                tf = payload["timeframe"]
                sym = payload["symbol"]
                channel = f"{sym}:{tf}"
                signal = payload["signal"]

                # Tek coin aboneler
                dead_ws = set()
                for ws in single_subscribers[channel]:
                    try:
                        await ws.send_json(signal)
                    except:
                        dead_ws.add(ws)
                single_subscribers[channel] -= dead_ws

                # Tüm coin aboneler — önce güncelle
                if tf in shared_signals:
                    strong_list = [
                        v for v in shared_signals[tf].values()
                        if v.get("score", 0) >= 85
                    ]
                    strong_list.sort(key=lambda x: -x["score"])
                    active_strong_signals[tf] = strong_list[:15]

                dead_ws = set()
                for ws in all_subscribers[tf]:
                    try:
                        await ws.send_json(active_strong_signals[tf])
                    except:
                        dead_ws.add(ws)
                all_subscribers[tf] -= dead_ws

            elif msg_type == "pump_radar":
                global top_gainers, last_update
                top_gainers = payload["top_gainers"]
                last_update = payload["last_update"]

                dead_ws = set()
                for ws in pump_radar_subscribers:
                    try:
                        await ws.send_json(payload)
                    except:
                        dead_ws.add(ws)
                pump_radar_subscribers -= dead_ws

            elif msg_type == "realtime_price":
                dead_ws = set()
                for ws in realtime_subscribers:
                    try:
                        await ws.send_json(payload)
                    except:
                        dead_ws.add(ws)
                realtime_subscribers -= dead_ws

            signal_queue.task_done()

        except Exception as e:
            logger.error(f"Broadcast worker hatası: {e}")
            await asyncio.sleep(0.1)

# ==================== REALTIME PRICE STREAM ====================
async def realtime_price_stream():
    try:
        from utils import all_usdt_symbols, exchange
        symbols = [s for s in all_usdt_symbols[:20] if s]
        logger.info(f"✅ Gerçek zamanlı fiyat stream: {len(symbols)} coin")

        while True:
            try:
                tickers = await exchange.fetch_tickers(symbols)
                rt_ticker["tickers"] = {
                    sym: {
                        "last": float(tickers[sym]["last"]),
                        "change": float(tickers[sym].get("percentage", 0)),
                        "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)
                    }
                    for sym in symbols if sym in tickers
                }
                rt_ticker["last_update"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                await signal_queue.put(("realtime_price", {
    "tickers": rt_ticker["tickers"],
    "last_update": rt_ticker["last_update"]
}))
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.warning(f"Realtime fiyat hatası: {e}")
                await asyncio.sleep(3)

    except Exception as e:
        logger.error(f"Realtime stream başlatılamadı: {e}")

# ==================== SIGNAL PRODUCER ====================
async def signal_producer():
    logger.info("🌀 Sinyal üretici başladı (genişletilmiş timeframes)")

    try:
        from indicators import generate_ict_signal
        from utils import all_usdt_symbols, fetch_ohlcv
    except Exception as e:
        logger.error(f"Import hatası: {e}")
        return

    # ✅ DÜZELTİLDİ: Binance destekli timeframe'ler (45m atlandı, desteklenmiyor)
    timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
    await asyncio.sleep(8)

    while True:
        start = asyncio.get_event_loop().time()
        signals_found = 0

        for tf in timeframes:
            for symbol in all_usdt_symbols[:50]:  # Limit düşürüldü (performans için)
                try:
                    ohlcv = await fetch_ohlcv(symbol, tf, limit=200)
                    if len(ohlcv) < 100:
                        continue

                    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    signal = generate_ict_signal(df, symbol, tf)

                    if signal:
                        shared_signals[tf][symbol] = signal
                        signals_found += 1
                        await signal_queue.put(("signal", {
                            "timeframe": tf,
                            "symbol": symbol,
                            "signal": signal
                        }))

                except Exception as e:
                    logger.debug(f"Sinyal atlandı ({symbol}/{tf}): {e}")

        # Pump radar (değişmedi)
        try:
            symbols_for_radar = all_usdt_symbols[:100]
            from utils import exchange
            tickers = await exchange.fetch_tickers(symbols_for_radar)
            gains = []
            for sym in symbols_for_radar:
                t = tickers.get(sym)
                if t and t.get("percentage"):
                    change = float(t["percentage"])
                    if abs(change) >= 5:
                        gains.append({
                            "symbol": sym.replace("USDT", ""),
                            "price": float(t["last"]),
                            "change": round(change, 2)
                        })
            gains.sort(key=lambda x: -abs(x["change"]))
            top10 = gains[:10]

            await signal_queue.put(("pump_radar", {
                "top_gainers": top10,
                "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            }))

        except Exception as e:
            logger.error(f"Pump radar hatası: {e}")

        elapsed = asyncio.get_event_loop().time() - start
        logger.info(f"✅ {signals_found} sinyal | {elapsed:.1f}s")
        await asyncio.sleep(max(5.0, 10.0 - elapsed))  # Sleep artırıldı (daha fazla tf için)

# ==================== INIT & CLEANUP ====================
async def initialize():
    logger.info("🚀 Uygulama başlatılıyor...")
    from utils import load_all_symbols
    await load_all_symbols()
    
    asyncio.create_task(broadcast_worker())
    asyncio.create_task(signal_producer())
    asyncio.create_task(realtime_price_stream())
    logger.info("✅ Tüm servisler çalışıyor!")

async def cleanup():
    logger.info("🛑 Temizlik yapılıyor...")
