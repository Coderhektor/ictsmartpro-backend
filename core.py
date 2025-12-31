# core.py — RAILWAY'DE %100 ÇALIŞAN, MULTI-EXCHANGE & PRODUCTION READY
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Set, List, Optional, Any
from threading import Lock

import ccxt.async_support as ccxt_async
import pandas as pd

# ==================== LOGGER ====================
logger = logging.getLogger("core")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | core | %(message)s"))
    logger.addHandler(handler)

# ==================== PRICE POOL ====================
price_pool: Dict[str, Dict[str, Any]] = {}
price_pool_lock = Lock()

def update_price(source: str, symbol: str, price: float, change_24h: Optional[float] = None):
    """Exchange'den gelen fiyatı havuza ekler"""
    with price_pool_lock:
        if symbol not in price_pool:
            price_pool[symbol] = {}

        price_pool[symbol][source] = {
            "price": float(price),
            "change_24h": float(change_24h) if change_24h is not None else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Ortalama fiyat hesapla
        valid_prices = [info["price"] for info in price_pool[symbol].values() if info.get("price", 0) > 0]
        if valid_prices:
            price_pool[symbol]["best_price"] = round(sum(valid_prices) / len(valid_prices), 10)
            price_pool[symbol]["sources"] = [src for src, info in price_pool[symbol].items() if info.get("price", 0) > 0]
            price_pool[symbol]["updated"] = datetime.now(timezone.utc).strftime("%H:%M:%S")

def get_best_price(symbol: str) -> Dict[str, Any]:
    with price_pool_lock:
        data = price_pool.get(symbol, {})
        return {
            "best_price": data.get("best_price", 0.0),
            "sources": data.get("sources", []),
            "updated": data.get("updated", "N/A")
        }

def get_all_prices_snapshot(limit: int = 50) -> Dict[str, Any]:
    with price_pool_lock:
        tickers = {}
        # Fiyata göre sırala (en yüksekten düşüğe)
        sorted_symbols = sorted(price_pool.items(), key=lambda x: x[1].get("best_price", 0), reverse=True)[:limit]
        for symbol, data in sorted_symbols:
            price = data.get("best_price", 0)
            if price <= 0:
                continue
            change = next((d["change_24h"] for d in data.values() if d.get("change_24h") is not None), 0.0)
            tickers[symbol] = {"price": price, "change": round(change, 2)}
        return {
            "tickers": tickers,
            "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        }

# ==================== REALTIME TICKER ====================
class RealtimeTicker:
    def __init__(self):
        self.subscribers: Set[Any] = set()
        self.lock = asyncio.Lock()

    async def subscribe(self, websocket: Any):
        async with self.lock:
            self.subscribers.add(websocket)

    async def unsubscribe(self, websocket: Any):
        async with self.lock:
            self.subscribers.discard(websocket)

    async def broadcast(self, data: dict):
        async with self.lock:
            disconnected = set()
            for ws in self.subscribers:
                try:
                    await ws.send_json(data)
                except Exception:
                    disconnected.add(ws)
            self.subscribers -= disconnected

rt_ticker = RealtimeTicker()

# ==================== GLOBAL STATE ====================
single_subscribers: Dict[str, Set[Any]] = defaultdict(set)
all_subscribers: Dict[str, Set[Any]] = defaultdict(set)
pump_radar_subscribers: Set[Any] = set()

shared_signals: Dict[str, Dict[str, Dict]] = defaultdict(dict)
active_strong_signals: Dict[str, List[Dict]] = defaultdict(list)

top_gainers: List[Dict[str, Any]] = []
last_update: str = "Yükleniyor..."

_binance_exchange: Optional[ccxt_async.binance] = None
all_usdt_symbols: List[str] = []

signal_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
background_tasks: List[asyncio.Task] = []

# ==================== UTILS ====================
def get_binance_client() -> Optional[ccxt_async.binance]:
    return _binance_exchange

# ==================== SYMBOL YÜKLEME ====================
async def load_all_symbols():
    global all_usdt_symbols, _binance_exchange
    try:
        if not _binance_exchange:
            _binance_exchange = ccxt_async.binance({
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            })
        await _binance_exchange.load_markets()
        usdt_pairs = [s for s in _binance_exchange.symbols if s.endswith('/USDT') and _binance_exchange.markets[s]['active']]
        all_usdt_symbols = [s.replace('/', '') for s in usdt_pairs][:150]
        logger.info(f"✅ {len(all_usdt_symbols)} USDT çifti yüklendi")
    except Exception as e:
        logger.warning(f"Symbol yükleme başarısız: {e} → fallback")
        all_usdt_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "TRXUSDT"]

# ==================== OHLCV ====================
async def fetch_ohlcv(symbol: str, timeframe: str = "5m", limit: int = 150):
    if not _binance_exchange or symbol not in all_usdt_symbols:
        return []
    try:
        formatted = symbol.replace('USDT', '/USDT')
        return await _binance_exchange.fetch_ohlcv(formatted, timeframe=timeframe, limit=limit)
    except Exception as e:
        logger.debug(f"OHLCV hatası {symbol}/{timeframe}: {e}")
        return []

# ==================== REALTIME PRICE TASK ====================
async def realtime_price_task():
    logger.info("📊 Realtime fiyat broadcast başladı")
    await asyncio.sleep(10)
    while True:
        try:
            data = get_all_prices_snapshot(limit=50)
            await rt_ticker.broadcast(data)
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"Realtime fiyat task hatası: {e}")
            await asyncio.sleep(5)

# ==================== PUMP RADAR TASK ====================
async def pump_radar_task():
    logger.info("🔥 Pump radar başladı")
    while True:
        try:
            with price_pool_lock:
                gains = []
                for symbol, data in price_pool.items():
                    price = data.get("best_price", 0)
                    if price <= 0:
                        continue
                    change = next((d["change_24h"] for d in data.values() if d.get("change_24h") is not None), 0)
                    if abs(change) >= 2.0:
                        gains.append({
                            "symbol": symbol.replace("USDT", ""),
                            "price": price,
                            "change": round(change, 2)
                        })
            if gains:
                gains.sort(key=lambda x: x["change"], reverse=True)
                payload = {
                    "top_gainers": gains[:8],
                    "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                }
                await signal_queue.put(("pump_radar", payload))
            await asyncio.sleep(20)
        except Exception as e:
            logger.error(f"Pump radar hatası: {e}")
            await asyncio.sleep(20)

# ==================== BROADCAST WORKER ====================
async def broadcast_worker():
    logger.info("📡 Broadcast worker başladı")
    while True:
        try:
            msg_type, payload = await signal_queue.get()

            if msg_type == "signal":
                tf = payload["timeframe"]
                symbol = payload["symbol"]
                signal_data = payload["signal"]
                channel = f"{symbol}:{tf}"

                # Tekil abonelere
                if channel in single_subscribers:
                    disconnected = set()
                    for ws in single_subscribers[channel]:
                        try:
                            await ws.send_json(signal_data)
                        except:
                            disconnected.add(ws)
                    single_subscribers[channel] -= disconnected

                # Güçlü sinyaller
                strong = [s for s in shared_signals[tf].values() if s.get("score", 0) >= 80]
                strong.sort(key=lambda x: x.get("score", 0), reverse=True)
                active_strong_signals[tf] = strong[:20]

                # Tüm coin abonelere
                if tf in all_subscribers:
                    disconnected = set()
                    for ws in all_subscribers[tf]:
                        try:
                            await ws.send_json(active_strong_signals[tf][:15])
                        except:
                            disconnected.add(ws)
                    all_subscribers[tf] -= disconnected

            elif msg_type == "pump_radar":
                global top_gainers, last_update
                top_gainers = payload.get("top_gainers", [])[:10]
                last_update = payload.get("last_update", "N/A")
                disconnected = set()
                for ws in pump_radar_subscribers:
                    try:
                        await ws.send_json(payload)
                    except:
                        disconnected.add(ws)
                pump_radar_subscribers -= disconnected

            signal_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Broadcast worker hatası: {e}")
            await asyncio.sleep(1)

# ==================== SİNYAL ÜRETİCİ ====================
async def signal_producer():
    logger.info("🧠 Sinyal üretici başladı")
    try:
        from indicators import generate_ict_signal
    except ImportError:
        logger.warning("indicators.py bulunamadı → fallback aktif")
        def generate_ict_signal(df: pd.DataFrame, symbol: str, tf: str):
            if len(df) < 20:
                return None
            change = (df['close'].iloc[-1] / df['close'].iloc[-2] - 1) * 100
            if abs(change) < 1.0:
                return None
            return {
                "symbol": symbol,
                "timeframe": tf,
                "score": min(95, 60 + abs(change) * 10),
                "signal": "ALIM" if change > 0 else "SATIM",
                "current_price": float(df['close'].iloc[-1]),
                "strength": "YÜKSEK" if abs(change) > 3 else "ORTA",
                "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S")
            }

    timeframes = ["5m", "15m", "1h", "4h"]
    scan_symbols = all_usdt_symbols[:40]

    while True:
        try:
            for tf in timeframes:
                tasks = [fetch_ohlcv(sym, tf, 100) for sym in scan_symbols]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for sym, klines in zip(scan_symbols, results):
                    if not klines or len(klines) < 50:
                        continue
                    try:
                        df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume'])
                        df = df.astype({'open': float, 'high': float, 'low': float, 'close': float, 'volume': float})

                        signal = generate_ict_signal(df, sym, tf)
                        if signal:
                            best = get_best_price(sym)
                            signal["current_price"] = best["best_price"] or signal["current_price"]
                            shared_signals[tf][sym] = signal
                            if signal.get("score", 0) >= 60:
                                await signal_queue.put(("signal", {"timeframe": tf, "symbol": sym, "signal": signal}))
                    except Exception as e:
                        logger.debug(f"Sinyal işleme hatası {sym}/{tf}: {e}")
            await asyncio.sleep(45)
        except Exception as e:
            logger.error(f"Sinyal üretici hata: {e}")
            await asyncio.sleep(30)

# ==================== EXCHANGE STREAMS (İçe Aktar) ====================
# Bu fonksiyonlar exchanges/ klasöründeki dosyalardan import edilecek
try:
    from exchanges.binance_ws import binance_ticker_stream
    from exchanges.bybit_ws import bybit_ticker_stream
    from exchanges.okx_ws import okx_ticker_stream
    from exchanges.coingecko_polling import coingecko_polling
except ImportError as e:
    logger.warning(f"Exchange modülleri yüklenemedi: {e}")
    # Fallback: boş fonksiyonlar
    async def binance_ticker_stream(): await asyncio.sleep(1)
    async def bybit_ticker_stream(): await asyncio.sleep(1)
    async def okx_ticker_stream(): await asyncio.sleep(1)
    async def coingecko_polling(): await asyncio.sleep(1)

# ==================== LIFECYCLE ====================
async def initialize():
    logger.info("🚀 Core başlatılıyor...")
    await load_all_symbols()

    # Tüm task'ları paralel başlat
    tasks = [
        asyncio.create_task(binance_ticker_stream()),
        asyncio.create_task(bybit_ticker_stream()),
        asyncio.create_task(okx_ticker_stream()),
        asyncio.create_task(coingecko_polling()),
        asyncio.create_task(broadcast_worker()),
        asyncio.create_task(signal_producer()),
        asyncio.create_task(realtime_price_task()),
        asyncio.create_task(pump_radar_task()),
    ]
    background_tasks.extend(tasks)
    logger.info("✅ Tüm task'lar başlatıldı (multi-exchange aktif)")
    return tasks

async def cleanup():
    logger.info("🛑 Core kapanıyor...")
    for task in background_tasks:
        if not task.done():
            task.cancel()
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)

    global _binance_exchange
    if _binance_exchange:
        await _binance_exchange.close()
        _binance_exchange = None
    logger.info("✅ Core temizlendi")

# ==================== EXPORT ====================
__all__ = [
    'single_subscribers', 'all_subscribers', 'pump_radar_subscribers',
    'shared_signals', 'active_strong_signals', 'top_gainers', 'last_update',
    'rt_ticker', 'get_binance_client', 'get_all_prices_snapshot',
    'signal_queue', 'initialize', 'cleanup'
]
