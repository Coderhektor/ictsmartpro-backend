# core.py - ÜRETİM HAZIR, GERÇEK ZAMANLI WEBSOCKET + SAĞLAM HAVUZ

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Set

import ccxt.pro as ccxt_pro          # Gerçek WebSocket akışları için
import ccxt.async_support as ccxt_async
import pandas as pd

# ==================== LOGGER ====================
logger = logging.getLogger("core")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | core | %(message)s"))
    logger.addHandler(handler)

# ==================== NORMALIZATION ====================
def normalize_pool_key(symbol: str) -> str:
    """
    Havuz anahtarı: COINUSDT (ör: BTCUSDT)
    Her giriş formatını normalize eder.
    """
    s = symbol.upper().replace('-', '').replace('/', '')
    if not s.endswith('USDT'):
        s += 'USDT'
    return s

def to_exchange_symbol(symbol_key: str, exchange: str) -> str:
    """
    Havuz anahtarından (BTCUSDT) exchange abonelik formatına çeviri:
    - binance:      BTC/USDT
    - bybit:        BTCUSDT
    - okx:          BTC-USDT
    """
    base = symbol_key[:-4]
    if exchange == 'binance':
        return f"{base}/USDT"
    if exchange == 'bybit':
        return symbol_key
    if exchange == 'okx':
        return f"{base}-USDT"
    return symbol_key

# ==================== PRICE POOL (ASYNC SAFE) ====================
class PricePool:
    """
    Tek, global fiyat havuzu. Exchange’lerden gelen anlık verileri birleştirir.
    """
    def __init__(self):
        self._pool: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def update(self, source: str, symbol_key: str, price: float,
                     change_24h: Optional[float] = None):
        async with self._lock:
            if symbol_key not in self._pool:
                self._pool[symbol_key] = {"sources": {}, "best_price": 0.0, "updated": ""}
            self._pool[symbol_key]["sources"][source] = {
                "price": float(price) if price is not None else 0.0,
                "change_24h": float(change_24h) if change_24h is not None else None,
                "timestamp": datetime.now(timezone.utc),
            }
            valid_prices = [
                v["price"]
                for v in self._pool[symbol_key]["sources"].values()
                if v["price"] and v["price"] > 0
            ]
            if valid_prices:
                self._pool[symbol_key]["best_price"] = round(sum(valid_prices) / len(valid_prices), 8)
                self._pool[symbol_key]["updated"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    async def get_best_price(self, symbol: str) -> float:
        key = normalize_pool_key(symbol)
        async with self._lock:
            return self._pool.get(key, {}).get("best_price", 0.0)

    async def snapshot(self, limit: int = 50) -> Dict[str, Any]:
        async with self._lock:
            if not self._pool:
                return {"tickers": {}, "last_update": "N/A"}
            valid = {s: d for s, d in self._pool.items() if d.get("best_price", 0) > 0}
            sorted_symbols = sorted(
                valid.items(),
                key=lambda x: x[1]["best_price"],
                reverse=True
            )[:limit]
            tickers = {}
            for symbol, data in sorted_symbols:
                changes = [
                    src.get("change_24h")
                    for src in data["sources"].values()
                    if src.get("change_24h") is not None
                ]
                avg_change = round(sum(changes) / len(changes), 2) if changes else 0.0
                tickers[symbol] = {
                    "price": data["best_price"],
                    "change": avg_change,
                    "sources": list(data["sources"].keys()),
                }
            return {
                "tickers": tickers,
                "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            }

    async def all_items(self):
        async with self._lock:
            return dict(self._pool)

price_pool = PricePool()

# ==================== REALTIME BROADCAST ====================
class RealtimeTicker:
    def __init__(self):
        self.subscribers: Set[Any] = set()
        self.lock = asyncio.Lock()

    async def subscribe(self, ws):
        async with self.lock:
            self.subscribers.add(ws)

    async def unsubscribe(self, ws):
        async with self.lock:
            self.subscribers.discard(ws)

    async def broadcast(self, data: dict):
        async with self.lock:
            disconnected = set()
            for ws in list(self.subscribers):
                try:
                    await ws.send_json(data)
                except Exception:
                    disconnected.add(ws)
            for ws in disconnected:
                self.subscribers.discard(ws)

rt_ticker = RealtimeTicker()

# ==================== GLOBAL STATE ====================
top_gainers: List[Dict] = []
last_update: str = "Yükleniyor..."
all_usdt_symbols: List[str] = []  # Havuz anahtarı formatında: BTCUSDT
background_tasks: List[asyncio.Task] = []
shutdown_evt = asyncio.Event()

# ==================== SYMBOL YÜKLEME (REST) ====================
async def load_symbols():
    """
    Binance REST ile aktif USDT paritelerini yükler, havuz anahtarı formatına çevirir.
    """
    global all_usdt_symbols  # Bu satırı EN ÜSTE TAŞI (önce kullanım yok diye)
    try:
        binance_rest = ccxt_async.binance({'enableRateLimit': True})
        await binance_rest.load_markets()
        pairs = [
            s for s in binance_rest.symbols
            if s.endswith('/USDT') and binance_rest.markets[s].get('active', True)
        ]
        # Havuz formatına çeviri: BTC/USDT -> BTCUSDT
        normalized = [normalize_pool_key(s) for s in pairs]
        max_symbols = 150
        all_usdt_symbols = normalized[:max_symbols]  # Artık güvenli
        await binance_rest.close()
        logger.info(f"✅ {len(all_usdt_symbols)} USDT çifti yüklendi")
    except Exception as e:
        logger.warning(f"Symbol yükleme hatası: {e}")
        # Fallback
        all_usdt_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT"]

# ==================== WEBSOCKET STREAMS (GERÇEK ZAMANLI) ====================
async def binance_stream():
    """
    Binance WS: watch_tickers. Semboller chunk'lanarak abone olunur.
    """
    exchange = ccxt_pro.binance()
    try:
        # Exchange formatına çeviri
        symbols = [to_exchange_symbol(s, 'binance') for s in all_usdt_symbols]
        chunk_size = 50  # Binance tek seferde çok fazla sembol subscription’da sorun yaratabilir
        chunks = [symbols[i:i + chunk_size] for i in range(0, len(symbols), chunk_size)]
        logger.info(f"📡 Binance WS subscribing in {len(chunks)} chunks")

        while not shutdown_evt.is_set():
            for chunk in chunks:
                try:
                    tickers = await exchange.watch_tickers(chunk)
                    for sym, t in tickers.items():
                        key = normalize_pool_key(sym)  # "BTC/USDT" -> "BTCUSDT"
                        await price_pool.update('binance', key, t.get('last') or 0, t.get('percentage'))
                except Exception as e:
                    logger.error(f"Binance WS hata: {e}")
                    await asyncio.sleep(3)
            await asyncio.sleep(0.3)
    finally:
        try:
            await exchange.close()
        except Exception:
            pass

async def bybit_stream():
    """
    Bybit WS: watch_tickers. Bybit formatı BTCUSDT şeklindedir.
    """
    exchange = ccxt_pro.bybit()
    try:
        symbols = [to_exchange_symbol(s, 'bybit') for s in all_usdt_symbols]
        chunk_size = 50
        chunks = [symbols[i:i + chunk_size] for i in range(0, len(symbols), chunk_size)]
        logger.info(f"📡 Bybit WS subscribing in {len(chunks)} chunks")

        while not shutdown_evt.is_set():
            for chunk in chunks:
                try:
                    tickers = await exchange.watch_tickers(chunk)
                    for sym, t in tickers.items():
                        key = normalize_pool_key(sym)  # "BTCUSDT" -> "BTCUSDT"
                        await price_pool.update('bybit', key, t.get('last') or 0, t.get('percentage'))
                except Exception as e:
                    logger.error(f"Bybit WS hata: {e}")
                    await asyncio.sleep(3)
            await asyncio.sleep(0.3)
    finally:
        try:
            await exchange.close()
        except Exception:
            pass

async def okx_stream():
    """
    OKX WS: watch_tickers. OKX formatı BTC-USDT şeklindedir.
    """
    exchange = ccxt_pro.okx()
    try:
        symbols = [to_exchange_symbol(s, 'okx') for s in all_usdt_symbols]
        chunk_size = 50
        chunks = [symbols[i:i + chunk_size] for i in range(0, len(symbols), chunk_size)]
        logger.info(f"📡 OKX WS subscribing in {len(chunks)} chunks")

        while not shutdown_evt.is_set():
            for chunk in chunks:
                try:
                    tickers = await exchange.watch_tickers(chunk)
                    for sym, t in tickers.items():
                        key = normalize_pool_key(sym)  # "BTC-USDT" -> "BTCUSDT"
                        await price_pool.update('okx', key, t.get('last') or 0, t.get('percentage'))
                except Exception as e:
                    logger.error(f"OKX WS hata: {e}")
                    await asyncio.sleep(3)
            await asyncio.sleep(0.3)
    finally:
        try:
            await exchange.close()
        except Exception:
            pass

# ==================== REALTIME PRICE BROADCAST ====================
async def realtime_broadcast_task():
    logger.info("📊 Realtime broadcast başladı")
    await asyncio.sleep(2)
    while not shutdown_evt.is_set():
        data = await price_pool.snapshot(50)
        await rt_ticker.broadcast(data)
        await asyncio.sleep(3)

# ==================== PUMP RADAR ====================
async def pump_radar_task():
    logger.info("🔥 Pump radar başladı")
    global top_gainers, last_update
    while not shutdown_evt.is_set():
        try:
            pool_items = await price_pool.all_items()
            candidates = []
            for symbol_key, data in pool_items.items():
                if data.get("best_price", 0) <= 0:
                    continue
                changes = [
                    s.get("change_24h")
                    for s in data["sources"].values()
                    if s.get("change_24h") is not None
                ]
                if not changes:
                    continue
                avg_change = sum(changes) / len(changes)
                if abs(avg_change) >= 2.0:
                    candidates.append({
                        "symbol": symbol_key.replace("USDT", ""),
                        "price": data["best_price"],
                        "change": round(avg_change, 2),
                    })
            candidates.sort(key=lambda x: x["change"], reverse=True)
            top_gainers = candidates[:10]
            last_update = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            await asyncio.sleep(20)
        except Exception as e:
            logger.error(f"Pump radar hata: {e}")
            await asyncio.sleep(20)

# ==================== LIFECYCLE ====================
async def initialize():
    logger.info("🚀 Core başlatılıyor...")
    await load_symbols()
    tasks = [
        realtime_broadcast_task(),
        pump_radar_task(),
        binance_stream(),
        bybit_stream(),
        okx_stream(),
    ]
    background_tasks.extend([asyncio.create_task(t) for t in tasks])
    logger.info("✅ Tüm gerçek zamanlı görevler başlatıldı")

async def cleanup():
    logger.info("🛑 Core kapanıyor...")
    shutdown_evt.set()
    for task in background_tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
    background_tasks.clear()
    logger.info("✅ Core temizlendi")

# ==================== EXPORT ====================
__all__ = [
    'rt_ticker',
    'top_gainers',
    'last_update',
    'initialize',
    'cleanup',
    'price_pool',              # gerekirse dışarıdan snapshot almak için
    'normalize_pool_key',
    'to_exchange_symbol',
]
