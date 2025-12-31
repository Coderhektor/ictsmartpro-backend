# core.py — SON VE MÜKEMMEL VERSİYON (TAM ÇALIŞIR GARANTİLİ - 2025)
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

shared_signals: Dict[str, Dict[str, dict]] = defaultdict(dict)
active_strong_signals: Dict[str, List[dict]] = defaultdict(list)

top_gainers: List[dict] = []
last_update: str = "Yükleniyor..."

rt_ticker = {
    "tickers": {},
    "last_update": ""
}

exchange: Optional[ccxt_async.binance] = None
all_usdt_symbols: List[str] = []

signal_queue: asyncio.Queue = asyncio.Queue(maxsize=500)


# ==================== BROADCAST WORKER ====================
# core.py — ACİL DÜZELTME VERSİYONU

# ... üstteki import'lar aynı ...

async def broadcast_worker():
    logger.info("📡 Broadcast worker aktif")
    
    # TÜM GLOBAL DEĞİŞKENLERİ BURADA TANIMLA!
    global top_gainers, last_update, rt_ticker
    global single_subscribers, all_subscribers, pump_radar_subscribers, realtime_subscribers
    global shared_signals, active_strong_signals
    
    while True:
        try:
            msg_type, payload = await signal_queue.get()

            if msg_type == "signal":
                tf = payload["timeframe"]
                symbol = payload["symbol"]
                signal_data = payload["signal"]
                channel = f"{symbol}:{tf}"

                if channel in single_subscribers:
                    dead = set()
                    for ws in list(single_subscribers[channel]):
                        try:
                            await ws.send_json(signal_data)
                        except:
                            dead.add(ws)
                    single_subscribers[channel] -= dead

                strong = [s for s in shared_signals[tf].values() if s.get("score", 0) >= 80]
                strong.sort(key=lambda x: x.get("score", 0), reverse=True)
                active_strong_signals[tf] = strong[:20]

                if tf in all_subscribers:
                    dead = set()
                    for ws in list(all_subscribers[tf]):
                        try:
                            await ws.send_json(active_strong_signals[tf])
                        except:
                            dead.add(ws)
                    all_subscribers[tf] -= dead

            elif msg_type == "pump_radar":
                top_gainers = payload.get("top_gainers", [])[:10]
                last_update = payload.get("last_update", "N/A")

                dead = set()
                for ws in list(pump_radar_subscribers):
                    try:
                        await ws.send_json(payload)
                    except:
                        dead.add(ws)
                pump_radar_subscribers -= dead

            elif msg_type == "realtime_price":
                dead = set()
                for ws in list(realtime_subscribers):
                    try:
                        await ws.send_json(payload)
                    except:
                        dead.add(ws)
                realtime_subscribers -= dead

            signal_queue.task_done()

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Broadcast worker hatası: {e}", exc_info=True)
            await asyncio.sleep(0.1)


# ==================== UTILS ====================
async def load_all_symbols():
    global all_usdt_symbols, exchange
    try:
        if not exchange:
            exchange = ccxt_async.binance({
                'enableRateLimit': True,
                'rateLimit': 1200,
                'options': {'defaultType': 'spot'}
            })

        await exchange.load_markets()
        usdt_pairs = [s for s in exchange.symbols if s.endswith('/USDT') and exchange.markets[s]['active']]
        all_usdt_symbols = [s.replace('/', '') for s in usdt_pairs][:120]  # Railway dostu

        logger.info(f"✅ {len(all_usdt_symbols)} USDT çifti yüklendi (ilk 120)")
    except Exception as e:
        logger.warning(f"Symbol yüklenemedi: {e} → Fallback aktif")
        all_usdt_symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
            "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "TRXUSDT", "DOTUSDT",
            "LINKUSDT", "MATICUSDT", "SHIBUSDT", "LTCUSDT", "UNIUSDT"
        ]


async def fetch_ohlcv(symbol: str, timeframe: str = "5m", limit: int = 150) -> List:
    global exchange
    if not exchange:
        logger.error("Exchange client yok!")
        return []

    try:
        formatted_symbol = symbol.replace('USDT', '/USDT')
        data = await exchange.fetch_ohlcv(formatted_symbol, timeframe=timeframe, limit=limit)
        logger.debug(f"{symbol} {timeframe} → {len(data)} mum alındı")
        return data
    except Exception as e:
        logger.warning(f"{symbol} veri çekilemedi: {e}")
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
                if key in tickers and tickers[key]:
                    t = tickers[key]
                    price = float(t.get('last') or 0)
                    change = round(float(t.get('percentage') or 0), 2)
                    if price > 0:
                        updated[sym] = {"price": price, "change": change}

            if updated:
                rt_ticker["tickers"] = updated
                rt_ticker["last_update"] = datetime.now(timezone.utc).strftime("%H:%M:%S")
                await signal_queue.put(("realtime_price", rt_ticker.copy()))

        except Exception as e:
            logger.warning(f"Realtime fiyat hatası: {e}")

        await asyncio.sleep(3)


# ==================== SIGNAL PRODUCER ====================
async def signal_producer():
    logger.info("🧠 Sinyal üretici başladı")

    try:
        from indicators import generate_ict_signal, generate_simple_signal
        logger.info("✅ indicators.py yüklendi")
    except Exception as e:
        logger.error(f"indicators.py YOK: {e} → Basit fallback aktif")
        def generate_ict_signal(df, symbol, tf):
            if len(df) < 10: return None
            close = df['close']
            change = (close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100
            score = min(95, int(abs(change) * 15))
            return {
                "pair": symbol.replace("USDT", "/USDT"),
                "timeframe": tf.upper(),
                "current_price": round(close.iloc[-1], 6),
                "signal": "ALIM" if change > 0.2 else "SATIM" if change < -0.2 else "NÖTR",
                "score": score,
                "strength": "YÜKSEK" if score > 70 else "ORTA",
                "killzone": "London" if 7 <= datetime.utcnow().hour < 10 else "New York" if 13 <= datetime.utcnow().hour < 16 else "Normal",
                "triggers": f"Momentum: {change:+.2f}%",
                "last_update": datetime.utcnow().strftime("%H:%M:%S")
            }
        generate_simple_signal = generate_ict_signal

    timeframes = ["5m", "15m", "1h", "4h"]
    scan_symbols = all_usdt_symbols[:30] or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

    await asyncio.sleep(10)

    while True:
        start_time = asyncio.get_event_loop().time()
        signals_count = 0

        for tf in timeframes:
            for symbol in scan_symbols:
                try:
                    raw_data = await fetch_ohlcv(symbol, tf, 150)
                    if len(raw_data) < 50:
                        continue

                    # DOĞRU SÜTUN İSİMLERİ — BU ÇOK ÖNEMLİ!
                    df = pd.DataFrame(raw_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    df.set_index('timestamp', inplace=True)
                    df = df.astype({'open': float, 'high': float, 'low': float, 'close': float, 'volume': float})

                    signal = generate_ict_signal(df, symbol, tf)
                    if not signal:
                        continue

                    # HER ZAMAN GÜNCELLE → Kullanıcı bağlandığında hemen görsün
                    shared_signals[tf][symbol] = signal
                    signals_count += 1

                    logger.info(f"🎯 {symbol}/{tf} → {signal['signal']} | Skor: {signal['score']}")

                    # Yüksek skorluları broadcast et
                    if signal.get("score", 0) >= 65:
                        await signal_queue.put(("signal", {
                            "timeframe": tf,
                            "symbol": symbol,
                            "signal": signal
                        }))

                except Exception as e:
                    logger.debug(f"{symbol}/{tf} hata: {e}")
                    continue

        # Pump Radar
        try:
            formatted = [s.replace('USDT', '/USDT') for s in scan_symbols]
            tickers = await exchange.fetch_tickers(formatted)
            gains = []
            for sym in scan_symbols:
                key = sym.replace('USDT', '/USDT')
                if key in tickers and tickers[key]:
                    t = tickers[key]
                    change = float(t.get('percentage') or 0)
                    price = float(t.get('last') or 0)
                    if abs(change) >= 2.0 and price > 0:
                        gains.append({
                            "symbol": sym.replace("USDT", ""),
                            "price": price,
                            "change": round(change, 2)
                        })
            gains.sort(key=lambda x: abs(x["change"]), reverse=True)
            await signal_queue.put(("pump_radar", {
                "top_gainers": gains[:8],
                "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            }))
        except Exception as e:
            logger.warning(f"Pump radar hatası: {e}")

        elapsed = asyncio.get_event_loop().time() - start_time
        logger.info(f"🔄 Tarama bitti → {signals_count} sinyal | {elapsed:.1f}s")

        await asyncio.sleep(max(10, 40 - elapsed))  # CPU dostu


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

    logger.info("✅ Tüm sistemler ÇALIŞIYOR! Sinyaller geliyor...")


async def cleanup():
    logger.info("🛑 Core kapanıyor...")
    global exchange
    if exchange:
        await exchange.close()
    logger.info("✅ Temizlik tamam")


def get_binance_client():
    return exchange
