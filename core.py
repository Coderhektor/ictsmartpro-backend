# core.py — MUHTEŞEM YENİ VERSİYON (2025 Railway Optimized)
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Set, List, Optional

import ccxt.async_support as ccxt_async
import pandas as pd

from fastapi import WebSocket

logger = logging.getLogger("core")
logger.setLevel(logging.INFO)

# ==================== GLOBAL STATE ====================
single_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)
all_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)
pump_radar_subscribers: Set[WebSocket] = set()
realtime_subscribers: Set[WebSocket] = set()

# Ana sinyal deposu: timeframe → symbol → signal
shared_signals: Dict[str, Dict[str, dict]] = defaultdict(dict)

# Güçlü sinyaller listesi (skor >= 80)
active_strong_signals: Dict[str, List[dict]] = defaultdict(list)

# Pump radar
top_gainers: List[dict] = []
last_update: str = "Yükleniyor..."

# Realtime fiyatlar
rt_ticker = {
    "tickers": {},
    "last_update": ""
}

# Binance client
exchange: Optional[ccxt_async.binance] = None

# Tüm USDT sembolleri
all_usdt_symbols: List[str] = []

# Broadcast queue
signal_queue: asyncio.Queue = asyncio.Queue(maxsize=500)


# ==================== BROADCAST WORKER ====================
async def broadcast_worker():
    logger.info("📡 Broadcast worker başlatıldı")
    while True:
        try:
            msg_type, payload = await signal_queue.get()

            if msg_type == "signal":
                tf = payload["timeframe"]
                symbol = payload["symbol"]
                signal_data = payload["signal"]
                channel = f"{symbol}:{tf}"

                # Tek coin abonelerine gönder
                if channel in single_subscribers:
                    dead = set()
                    for ws in list(single_subscribers[channel]):
                        try:
                            await ws.send_json(signal_data)
                        except Exception:
                            dead.add(ws)
                    single_subscribers[channel] -= dead

                # Güçlü sinyalleri güncelle ve tüm coin abonelerine gönder
                strong = [s for s in shared_signals[tf].values() if s.get("score", 0) >= 80]
                strong.sort(key=lambda x: x.get("score", 0), reverse=True)
                active_strong_signals[tf] = strong[:20]  # En iyi 20

                if tf in all_subscribers:
                    dead = set()
                    for ws in list(all_subscribers[tf]):
                        try:
                            await ws.send_json(active_strong_signals[tf])
                        except Exception:
                            dead.add(ws)
                    all_subscribers[tf] -= dead

            elif msg_type == "pump_radar":
                global top_gainers, last_update
                top_gainers = payload.get("top_gainers", [])[:10]
                last_update = payload.get("last_update", "N/A")

                dead = set()
                for ws in list(pump_radar_subscribers):
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        dead.add(ws)
                pump_radar_subscribers -= dead

            elif msg_type == "realtime_price":
                dead = set()
                for ws in list(realtime_subscribers):
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        dead.add(ws)
                realtime_subscribers -= dead

            signal_queue.task_done()

        except asyncio.CancelledError:
            logger.info("Broadcast worker durduruldu")
            break
        except Exception as e:
            logger.error(f"Broadcast worker hatası: {e}", exc_info=True)
            await asyncio.sleep(0.1)


# ==================== UTILS ====================
async def load_all_symbols():
    global all_usdt_symbols, exchange
    try:
        if not exchange:
            exchange = ccxt_async.binance({'enableRateLimit': True, 'rateLimit': 1200})

        await exchange.load_markets()
        usdt_pairs = [s for s in exchange.symbols if s.endswith('/USDT') and exchange.markets[s]['active']]
        all_usdt_symbols = [s.replace('/', '') for s in usdt_pairs][:150]  # Railway için makul limit

        logger.info(f"✅ {len(all_usdt_symbols)} USDT çifti yüklendi")
    except Exception as e:
        logger.warning(f"Symbol yükleme hatası: {e} → Fallback kullanılıyor")
        all_usdt_symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
            "DOGEUSDT", "AVAXUSDT", "TRXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT",
            "SHIBUSDT", "LTCUSDT", "UNIUSDT"
        ]


async def fetch_ohlcv(symbol: str, timeframe: str = "5m", limit: int = 100):
    global exchange
    if not exchange:
        return []

    try:
        formatted = symbol.replace('USDT', '/USDT')
        data = await exchange.fetch_ohlcv(formatted, timeframe=timeframe, limit=limit)
        return data
    except Exception as e:
        logger.debug(f"{symbol} OHLCV hatası: {e}")
        return []


# ==================== REALTIME PRICE ====================
async def realtime_price_stream():
    logger.info("💹 Realtime fiyat akışı başladı")
    symbols = all_usdt_symbols[:50] or ["BTCUSDT", "ETHUSDT"]

    while True:
        try:
            formatted = [s.replace('USDT', '/USDT') for s in symbols]
            tickers = await exchange.fetch_tickers(formatted)

            updated = {}
            for sym in symbols:
                key = sym.replace('USDT', '/USDT')
                if key in tickers:
                    t = tickers[key]
                    updated[sym] = {
                        "price": float(t.get('last') or 0),
                        "change": round(float(t.get('percentage') or 0), 2)
                    }

            if updated:
                rt_ticker["tickers"] = updated
                rt_ticker["last_update"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                await signal_queue.put(("realtime_price", rt_ticker.copy()))

        except Exception as e:
            logger.warning(f"Realtime fiyat hatası: {e}")

        await asyncio.sleep(3)


# ==================== SIGNAL PRODUCER ====================
async def signal_producer():
    logger.info("🧠 ICT Sinyal üretici başladı")

    # Indicator yükle, yoksa güçlü fallback
    try:
        from indicators import generate_ict_signal, generate_simple_signal
        logger.info("✅ indicators.py başarıyla yüklendi")
    except Exception as e:
        logger.warning(f"indicators.py yüklenemedi: {e} → Güçlü fallback aktif")

        def generate_ict_signal(df: pd.DataFrame, symbol: str, timeframe: str):
            if df.empty or len(df) < 10:
                return None
            close = df['close']
            change = (close.iloc[-1] / close.iloc[-2] - 1) * 100 if len(close) > 1 else 0
            score = min(95, int(abs(change) * 12))

            return {
                "signal": "ALIM SİNYALİ" if change > 0.05 else "SATIM SİNYALİ" if change < -0.05 else "NÖTR",
                "score": score,
                "strength": "ÇOK YÜKSEK" if score >= 85 else "YÜKSEK" if score >= 70 else "ORTA",
                "killzone": "LONDRA" if "m" in timeframe else "NEWYORK",
                "triggers": f"Fiyat %{abs(change):.2f} değişti → Güçlü momentum",
                "current_price": round(close.iloc[-1], 6),
                "pair": symbol.replace("USDT", "/USDT"),
                "timeframe": timeframe.upper(),
                "last_update": datetime.now().strftime("%H:%M:%S")
            }

        generate_simple_signal = generate_ict_signal

    timeframes = ["5m", "15m", "1h", "4h"]
    scan_symbols = all_usdt_symbols[:25] or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    await asyncio.sleep(8)

    while True:
        start = asyncio.get_event_loop().time()
        signals_produced = 0

        for tf in timeframes:
            for symbol in scan_symbols:
                try:
                    ohlcv = await fetch_ohlcv(symbol, tf, 100)
                    if len(ohlcv) < 30:
                        continue

                    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    df.iloc[:, 1:] = df.iloc[:, 1:].apply(pd.to_numeric, errors='coerce')

                    signal = generate_ict_signal(df, symbol, tf)
                    if not signal:
                        continue

                    # HER ZAMAN shared_signals'ı güncelle (bağlanan kullanıcı hemen görsün)
                    shared_signals[tf][symbol] = signal
                    signals_produced += 1

                    logger.info(f"🎯 {symbol}/{tf} → {signal['signal']} (Skor: {signal['score']})")

                    # Sadece yüksek skorluları broadcast et (performans)
                    if signal["score"] >= 70:
                        await signal_queue.put(("signal", {
                            "timeframe": tf,
                            "symbol": symbol,
                            "signal": signal
                        }))

                except Exception as e:
                    logger.debug(f"{symbol}/{tf} sinyal hatası: {e}")
                    continue

        # Pump Radar (her turda bir kez)
        try:
            formatted = [s.replace('USDT', '/USDT') for s in scan_symbols]
            tickers = await exchange.fetch_tickers(formatted)
            gains = []
            for sym in scan_symbols:
                key = sym.replace('USDT', '/USDT')
                if key in tickers:
                    t = tickers[key]
                    change = float(t.get('percentage') or 0)
                    if abs(change) >= 2.5:
                        gains.append({
                            "symbol": sym.replace("USDT", ""),
                            "price": float(t.get('last') or 0),
                            "change": round(change, 2)
                        })
            gains.sort(key=lambda x: abs(x["change"]), reverse=True)
            await signal_queue.put(("pump_radar", {
                "top_gainers": gains[:8],
                "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            }))
        except Exception as e:
            logger.warning(f"Pump radar hatası: {e}")

        elapsed = asyncio.get_event_loop().time() - start
        logger.info(f"🔄 Tarama tamam: {signals_produced} sinyal üretildi | {elapsed:.1f}s")

        # Dinamik bekleme (CPU dostu)
        await asyncio.sleep(max(12, 35 - elapsed))


# ==================== INIT & CLEANUP ====================
async def initialize():
    logger.info("🚀 Core başlatılıyor...")
    await load_all_symbols()

    global exchange
    if not exchange:
        exchange = ccxt_async.binance({
            'enableRateLimit': True,
            'rateLimit': 1200,
            'options': {'defaultType': 'spot'}
        })

    asyncio.create_task(broadcast_worker())
    asyncio.create_task(signal_producer())
    asyncio.create_task(realtime_price_stream())

    logger.info("✅ Tüm core sistemler aktif! Sinyaller akıyor...")


async def cleanup():
    logger.info("🛑 Core kapanıyor...")
    global exchange
    if exchange:
        await exchange.close()
    logger.info("✅ Core temizlendi")


def get_binance_client():
    return exchange
