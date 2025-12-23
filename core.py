# core.py
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Set, List, Optional
from fastapi import WebSocket
import pandas as pd  # signal_producer içinde kullanılıyor

logger = logging.getLogger("broadcast")

# ========== GLOBAL STATE ==========
single_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)  # "BTCUSDT:5m" → {ws1, ws2}
all_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)     # "5m" → {ws1, ws2}
pump_radar_subscribers: Set[WebSocket] = set()

shared_signals: Dict[str, Dict[str, dict]] = defaultdict(dict)  # {timeframe: {symbol: signal}}
active_strong_signals: Dict[str, List[dict]] = defaultdict(list)

top_gainers: List[dict] = []
last_update: str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

# EKSİK OLAN: Realtime ticker verisi için
rt_ticker = {
    "tickers": {},  # {symbol: {"last": price, "percentage": change, ...}}
    "last_update": ""
}

# ========== Broadcast Queue ==========
signal_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

async def broadcast_worker():
    """Tüm WebSocket client'lara broadcast yapar"""
    logger.info("📡 Broadcast worker başlatılıyor...")
    while True:
        try:
            msg_type, payload = await signal_queue.get()

            if msg_type == "signal":
                tf, sym = payload["timeframe"], payload["symbol"]
                channel = f"{sym}:{tf}"

                # Tek coin takipçileri
                dead_ws = set()
                for ws in single_subscribers[channel]:
                    try:
                        await ws.send_json(payload["signal"])
                    except:
                        dead_ws.add(ws)
                single_subscribers[channel] -= dead_ws

                # Tüm coin takipçileri
                dead_ws = set()
                for ws in all_subscribers[tf]:
                    try:
                        await ws.send_json(active_strong_signals[tf])  # güncel listeyi gönder
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

            elif msg_type == "realtime_ticker":
                global rt_ticker
                rt_ticker["tickers"] = payload["tickers"]
                rt_ticker["last_update"] = payload["last_update"]

            signal_queue.task_done()

        except Exception as e:
            logger.error(f"Broadcast hatası: {e}")
            await asyncio.sleep(0.1)


# ========== Signal Üretici ==========
async def signal_producer():
    logger.info("🌀 Signal producer başlatılıyor (5 sn periyodik)...")

    try:
        from indicators import generate_ict_signal
        from utils import all_usdt_symbols, fetch_ohlcv
    except ImportError as e:
        logger.error(f"İmport hatası (indicators/utils): {e}")
        return

    timeframes = ["5m", "15m", "1h"]

    await asyncio.sleep(5)

    while True:
        start_time = asyncio.get_event_loop().time()
        signals_found = 0

        for tf in timeframes:
            for symbol in all_usdt_symbols[:100]:  # performans için 100 coin
                try:
                    ohlcv = await fetch_ohlcv(symbol, tf, limit=200)
                    if len(ohlcv) < 100:
                        continue
 df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
 df['timestamp'] = df['timestamp'].astype('int64')
 signal = generate_ict_signal(df, symbol, tf)

                    if signal and signal.get("score", 0) >= 85:
                        shared_signals[tf][symbol] = signal
                        signals_found += 1

                        await signal_queue.put(("signal", {
                            "timeframe": tf,
                            "symbol": symbol,
                            "signal": signal
                        }))

                except Exception as e:
                    logger.warning(f"{symbol}/{tf} tarama hatası: {e}")

        # Aktif güçlü sinyalleri güncelle
        for tf in timeframes:
            strong = [shared_signals[tf][s] for s in shared_signals[tf] if shared_signals[tf][s].get("score", 0) >= 85]
            strong.sort(key=lambda x: -x.get("score", 0))
            active_strong_signals[tf] = strong

        # Pump radar güncelle
        try:
            from utils import exchange  # exchange utils'te tanımlı olmalı
            tickers = await exchange.fetch_tickers()
            gains = []
            for sym, t in tickers.items():
                if sym.endswith("USDT") and "percentage" in t:
                    change = t["percentage"]
                    if abs(change) >= 5:
                        gains.append({
                            "symbol": sym.replace("USDT", ""),
                            "price": t["last"],
                            "change": change
                        })
            gains.sort(key=lambda x: -abs(x["change"]))
            top10 = gains[:10]

            if top10:
                await signal_queue.put(("pump_radar", {
                    "top_gainers": top10,
                    "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                }))

        except Exception as e:
            logger.error(f"Pump radar hatası: {e}")

        elapsed = asyncio.get_event_loop().time() - start_time
        logger.info(f"Tarama tamamlandı: {signals_found} güçlü sinyal, {elapsed:.1f}s sürdü")

        await asyncio.sleep(max(1.0, 5.0 - elapsed))


# ========== Init & Cleanup ==========
async def initialize():
    from utils import load_all_symbols
    await load_all_symbols()

    asyncio.create_task(broadcast_worker())
    asyncio.create_task(signal_producer())
    logger.info("✅ Tüm arka plan görevleri başlatıldı")

async def cleanup():
    logger.info("🛑 Cleanup çalıştırılıyor...")
    # Gerekirse ek temizlik
