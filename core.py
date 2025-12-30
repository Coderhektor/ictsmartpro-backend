# core.py — RAILWAY İÇİN TAMAMEN DÜZELTİLDİ & OPTİMİZE EDİLDİ
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Set, List

from fastapi import WebSocket
import pandas as pd

logger = logging.getLogger("broadcast")

# ==================== GLOBAL STATE ====================
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

# ==================== BROADCAST QUEUE ====================
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
                signal_data = payload["signal"]

                # Tek coin abonelerine gönder
                dead_ws = set()
                for ws in single_subscribers[channel].copy():  # .copy() ile güvenli iterasyon
                    try:
                        await ws.send_json(signal_data)
                    except Exception:
                        dead_ws.add(ws)
                single_subscribers[channel] -= dead_ws

                # Güçlü sinyalleri güncelle ve tüm coin abonelerine gönder
                strong_list = [
                    sig for sig in shared_signals[tf].values()
                    if sig.get("score", 0) >= 85
                ]
                strong_list.sort(key=lambda x: x.get("score", 0), reverse=True)
                active_strong_signals[tf] = strong_list[:15]

                dead_ws = set()
                for ws in all_subscribers[tf].copy():
                    try:
                        await ws.send_json(active_strong_signals[tf])
                    except Exception:
                        dead_ws.add(ws)
                all_subscribers[tf] -= dead_ws

            elif msg_type == "pump_radar":
                global top_gainers, last_update
                top_gainers = payload["top_gainers"]
                last_update = payload["last_update"]

                dead_ws = set()
                for ws in pump_radar_subscribers.copy():
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        dead_ws.add(ws)
                pump_radar_subscribers.difference_update(dead_ws)

            elif msg_type == "realtime_price":
                # KRİTİK DÜZELTME: Global değişken ataması olmadan güvenli kullanım
                dead_ws = set()
                current_subscribers = realtime_subscribers.copy()  # Anlık kopya al
                for ws in current_subscribers:
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        dead_ws.add(ws)
                realtime_subscribers.difference_update(dead_ws)

            signal_queue.task_done()

        except asyncio.CancelledError:
            logger.info("Broadcast worker iptal edildi.")
            break
        except Exception as e:
            logger.error(f"Broadcast worker hatası: {e}", exc_info=True)
            await asyncio.sleep(0.1)


# ==================== REALTIME PRICE STREAM ====================
async def realtime_price_stream():
    sources = ["binance", "coingecko", "bybit"]  # Gelecekte ekleyebiliriz
    symbols = [s for s in all_usdt_symbols[:50] if s.endswith("USDT")]

    while True:
        try:
            # Önce Binance dene
            tickers = await exchange.fetch_tickers(symbols)  # ccxt binance
            updated = {}
            for sym in symbols:
                if sym in tickers and tickers[sym]:
                    data = tickers[sym]
                    updated[sym] = {
                        "price": float(data.get("last", 0)),
                        "change": float(data.get("percentage", 0))
                    }
            if updated:
                rt_ticker["tickers"] = updated
                rt_ticker["last_update"] = datetime.now(timezone.utc).strftime("%H:%M:%S")
            
            await signal_queue.put(("realtime_price", rt_ticker.copy()))

        except Exception as e:
            logger.warning(f"Fiyat akışı hatası: {e}")

        await asyncio.sleep(3)  # 3 saniyede bir güncelle

# ==================== SIGNAL PRODUCER ====================
async def signal_producer():
    logger.info("🌀 Sinyal üretici başladı")

    try:
        from indicators import generate_ict_signal
        from utils import all_usdt_symbols, fetch_ohlcv, exchange
    except ImportError as e:
        logger.error(f"Modül import edilemedi: {e}")
        return

    timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]  # 1w çok yavaş, çıkardım
    symbols_to_scan = all_usdt_symbols[:40]  # CPU'yu yakmasın diye limit

    await asyncio.sleep(10)  # Sistem yerleşsin

    while True:
        start_time = asyncio.get_event_loop().time()
        signals_found = 0

        for tf in timeframes:
            for symbol in symbols_to_scan:
                try:
                    ohlcv = await fetch_ohlcv(symbol, tf, limit=150)
                    if len(ohlcv) < 80:
                        continue

                    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')

                    signal = generate_ict_signal(df, symbol, tf)
                    if signal and signal.get("score", 0) >= 70:  # Sadece iyi sinyalleri paylaş
                        shared_signals[tf][symbol] = signal
                        signals_found += 1

                        await signal_queue.put(("signal", {
                            "timeframe": tf,
                            "symbol": symbol,
                            "signal": signal
                        }))

                except Exception as e:
                    logger.debug(f"Sinyal hatası {symbol}/{tf}: {e}")

        # Pump Radar Güncelle
        try:
            tickers = await exchange.fetch_tickers(symbols_to_scan)
            gains = []
            for sym, data in tickers.items():
                if data and data.get("percentage") is not None:
                    change = float(data["percentage"])
                    if abs(change) >= 4.0:  # %4+ hareket edenler
                        gains.append({
                            "symbol": sym.replace("USDT", ""),
                            "price": float(data.get("last", 0)),
                            "change": round(change, 2)
                        })

            gains.sort(key=lambda x: abs(x["change"]), reverse=True)
            await signal_queue.put(("pump_radar", {
                "top_gainers": gains[:10],
                "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            }))

        except Exception as e:
            logger.error(f"Pump radar hatası: {e}")

        elapsed = asyncio.get_event_loop().time() - start_time
        logger.info(f"Scan tamamlandı: {signals_found} sinyal bulundu | {elapsed:.1f}s")
        await asyncio.sleep(max(8.0, 15.0 - elapsed))  # Railway'de CPU patlamasın


# ==================== INIT & CLEANUP ====================
async def initialize():
    logger.info("🚀 Core initialize ediliyor...")
    try:
        from utils import load_all_symbols
        await load_all_symbols()
    except Exception as e:
        logger.error(f"Symbol yükleme hatası: {e}")

    # Worker'ları başlat
    asyncio.create_task(broadcast_worker())
    asyncio.create_task(signal_producer())
    asyncio.create_task(realtime_price_stream())

    logger.info("✅ Tüm core servisler başarıyla başlatıldı!")


async def cleanup():
    logger.info("🛑 Core cleanup yapılıyor...")
    # Task'lar otomatik kapanır, gerekirse cancel edilebilir
