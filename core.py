# core.py
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Set, List, Optional
from fastapi import WebSocket

logger = logging.getLogger("broadcast")

# ========== GLOBAL STATE (paylaşımlı, thread-safe değil ama FastAPI async-loop güvenli) ==========
single_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)  # "BTCUSDT:5m" → {ws1, ws2}
all_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)      # "5m" → {ws1, ws2, ...}
pump_radar_subscribers: Set[WebSocket] = set()

shared_signals: Dict[str, Dict[str, dict]] = defaultdict(dict)  # {timeframe: {symbol: signal}}
active_strong_signals: Dict[str, List[dict]] = defaultdict(list)
top_gainers: List[dict] = []
last_update: str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

# ========== Broadcast Queue (tek üretim noktası) ==========
signal_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)  # 1 sn ~ 100 update → 10 sn buffer

async def broadcast_worker():
    """Tek bir async task → tüm client'lara eşzamanlı broadcast yapar."""
    logger.info("📡 Broadcast worker başlatılıyor...")
    while True:
        try:
            msg_type, payload = await signal_queue.get()
            
            if msg_type == "signal":
                # payload: {"timeframe": "5m", "symbol": "BTCUSDT", "signal": {...}}
                tf, sym = payload["timeframe"], payload["symbol"]
                channel = f"{sym}:{tf}"
                
                # 1) İlgili tek coin takipçilerine
                dead_ws = set()
                for ws in single_subscribers[channel]:
                    try:
                        await ws.send_json(payload["signal"])
                    except:
                        dead_ws.add(ws)
                single_subscribers[channel] -= dead_ws

                # 2) Tüm coin takipçilerine (timeframe'e göre)
                dead_ws = set()
                for ws in all_subscribers[tf]:
                    try:
                        await ws.send_json([payload["signal"]])  # array olarak
                    except:
                        dead_ws.add(ws)
                all_subscribers[tf] -= dead_ws

            elif msg_type == "pump_radar":
                # payload: {"top_gainers": [...], "last_update": "..."}
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
            logger.error(f"Broadcast hatası: {e}")
            await asyncio.sleep(0.1)


# ========== Signal Üretici (Tarama döngüsü) ==========
async def signal_producer():
    """5 saniyede bir tüm coinleri tarar, sinyalleri queue'ya atar."""
    logger.info("🌀 Signal producer başlatılıyor (5 sn periyodik)...")
    
    from indicators import generate_ict_signal
    from utils import all_usdt_symbols, fetch_ohlcv

    timeframes = ["5m", "15m", "1h"]  # realtime hariç — realtime başka mekanizma ile
    await asyncio.sleep(2)  # init delay
    
    while True:
        start = asyncio.get_event_loop().time()
        signals_this_cycle = 0

        for tf in timeframes:
            for symbol in all_usdt_symbols[:100]:  # 150 yerine 100 → daha stabil
                try:
                    ohlcv = await fetch_ohlcv(symbol, tf, limit=200)
                    if len(ohlcv) < 100:
                        continue

                    signal = generate_ict_signal(pd.DataFrame(ohlcv), symbol, tf)
                    if signal and signal["score"] >= 85:
                        shared_signals[tf][symbol] = signal
                        active_strong_signals[tf] = [shared_signals[tf][s] for s in shared_signals[tf] if shared_signals[tf][s]["score"] >= 85]
                        active_strong_signals[tf].sort(key=lambda x: -x["score"])

                        await signal_queue.put(("signal", {
                            "timeframe": tf,
                            "symbol": symbol,
                            "signal": signal
                        }))
                        signals_this_cycle += 1

                except Exception as e:
                    logger.warning(f"Tarama hatası ({symbol}/{tf}): {e}")

        # Pump radar (24h %gain)
        try:
            tickers = await exchange.fetch_tickers(all_usdt_symbols[:100])
            gains = []
            for sym in all_usdt_symbols[:100]:
                t = tickers.get(sym)
                if t and t.get("percentage"):
                    change = float(t["percentage"])
                    if abs(change) > 5:  # %5+ değişim
                        gains.append({
                            "symbol": sym.replace("USDT", ""),
                            "price": float(t["last"]),
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

        elapsed = asyncio.get_event_loop().time() - start
        logger.info(f"✅ {signals_this_cycle} sinyal üretildi. {len(all_usdt_symbols[:100])*len(timeframes)} coin tarandı. ({elapsed:.1f}s)")

        # Dinamik sleep: 5 sn - geçen_süre (min 1 sn)
        await asyncio.sleep(max(1.0, 5.0 - elapsed))


# ========== Init & Cleanup ==========
async def initialize():
    import asyncio
    from utils import load_all_symbols
    await load_all_symbols()
    
    # Arka plan görevleri başlat
    asyncio.create_task(broadcast_worker())
    asyncio.create_task(signal_producer())

async def cleanup():
    pass  # WebSocket temizliği zaten disconnect handler'da
