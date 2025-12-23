# core.py — GIRINTI HATASIZ, CANLI SİNYAL ÇALIŞIR VERSİYON

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

shared_signals: Dict[str, Dict[str, dict]] = defaultdict(dict)
active_strong_signals: Dict[str, List[dict]] = defaultdict(list)

top_gainers: List[dict] = []
last_update: str = "Yükleniyor..."

rt_ticker = {
    "tickers": {},
    "last_update": ""
}

# ========== Broadcast Queue ==========
signal_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

async def broadcast_worker():
    logger.info("📡 Broadcast worker başladı")
    while True:
        try:
            msg_type, payload = await signal_queue.get()

            if msg_type == "signal":
                tf, sym = payload["timeframe"], payload["symbol"]
                channel = f"{sym}:{tf}"

                # Tek coin aboneler
                dead_ws = set()
                for ws in single_subscribers[channel]:
                    try:
                        await ws.send_json(payload["signal"])
                    except:
                        dead_ws.add(ws)
                single_subscribers[channel] -= dead_ws

                # Tüm coin aboneler
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

            signal_queue.task_done()

        except Exception as e:
            logger.error(f"Broadcast worker hatası: {e}")

# ========== SİNYAL VE PUMP RADAR ÜRETİCİ ==========
async def signal_producer():
    logger.info("🌀 Sinyal ve pump radar üretici başladı")

    try:
        from indicators import generate_ict_signal
        from utils import all_usdt_symbols, fetch_ohlcv, exchange
        logger.info("✅ indicators ve utils başarıyla yüklendi")
    except Exception as e:
        logger.error(f"Import hatası: {e}")
        return

    timeframes = ["5m", "15m", "1h"]
    await asyncio.sleep(8)  # sembollerin yüklenmesini bekle

    while True:
        start_time = asyncio.get_event_loop().time()
        signals_found = 0

        # SİNYAL ÜRETİMİ
        for tf in timeframes:
            for symbol in all_usdt_symbols[:60]:  # rate limit için 60 coin
                try:
                    ohlcv = await fetch_ohlcv(symbol, tf, limit=200)
                    if len(ohlcv) < 100:
                        continue

                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

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
                    logger.warning(f"Sinyal hatası ({symbol}/{tf}): {e}")

        # Güçlü sinyalleri güncelle
        for tf in timeframes:
            strong = [v for v in shared_signals[tf].values() if v.get("score", 0) >= 85]
            strong.sort(key=lambda x: -x.get("score", 0))
            active_strong_signals[tf] = strong[:15]

        # PUMP RADAR
        try:
            logger.info("Pump radar verisi çekiliyor...")
            tickers = await exchange.fetch_tickers()
            gains = []

            for sym in all_usdt_symbols[:100]:
                t = tickers.get(sym)
                if t and t.get("percentage") is not None:
                    change = float(t["percentage"])
                    if abs(change) >= 5:
                        gains.append({
                            "symbol": sym.replace("USDT", ""),
                            "price": float(t["last"]),
                            "change": round(change, 2)
                        })

            gains.sort(key=lambda x: -abs(x["change"]))
            top10 = gains[:10]

            payload = {
                "top_gainers": top10,
                "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            }

            await signal_queue.put(("pump_radar", payload))
            logger.info(f"✅ Pump radar güncellendi: {len(top10)} coin bulundu")

        except Exception as e:
            logger.error(f"Pump radar hatası: {e}")
            await signal_queue.put(("pump_radar", {
                "top_gainers": [],
                "last_update": "Bağlantı hatası"
            }))

        elapsed = asyncio.get_event_loop().time() - start_time
        logger.info(f"Tarama tamamlandı: {signals_found} sinyal bulundu, {elapsed:.1f}s sürdü")

        # 4 saniyede bir tarama (canlı hissi için)
        await asyncio.sleep(max(1.0, 4.0 - elapsed))

# ========== INIT & CLEANUP ==========
async def initialize():
    try:
        from utils import load_all_symbols
        await load_all_symbols()
        logger.info("✅ Semboller yüklendi")
    except Exception as e:
        logger.error(f"Sembol yükleme hatası: {e}")

    asyncio.create_task(broadcast_worker())
    asyncio.create_task(signal_producer())
    logger.info("✅ Tüm arka plan görevleri başlatıldı")

async def cleanup():
    logger.info("🛑 Uygulama kapanıyor...")
