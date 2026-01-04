# 📁 core.py
"""
Real-time price aggregation & WebSocket broadcaster.
Depends on `utils.py` for symbol map and exchange instances.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Set, Any, Optional

import ccxt.pro as ccxt_pro
import pandas as pd

# Logger
logger = logging.getLogger("core")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | core | %(message)s"))
    logger.addHandler(handler)

logger.info("🔄 core.py yükleniyor...")

# ========== DEPENDENCIES FROM utils.py ==========
# utils.initialize() çağrıldığında doldurulacak
all_usdt_symbols: List[str] = []      # e.g., ["BTCUSDT", "ETHUSDT", ...]
symbol_map: Dict[str, Dict[str, str]] = {}  # exchange → {base_sym: actual_sym}
exchanges: Dict[str, ccxt_pro.Exchange] = {}  # ccxt.pro instance’ları

# ========== PRICE POOL ==========
class PricePool:
    def __init__(self):
        self._pool: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def update(self, source: str, symbol_key: str, price: float, change_24h: Optional[float] = None):
        async with self._lock:
            if symbol_key not in self._pool:
                self._pool[symbol_key] = {"sources": {}, "best_price": 0.0, "updated": ""}
            self._pool[symbol_key]["sources"][source] = {
                "price": float(price) if price is not None else 0.0,
                "change_24h": float(change_24h) if change_24h is not None else None,
                "timestamp": datetime.now(timezone.utc),
            }
            valid_prices = [
                v["price"] for v in self._pool[symbol_key]["sources"].values()
                if v["price"] > 0
            ]
            if valid_prices:
                self._pool[symbol_key]["best_price"] = round(sum(valid_prices) / len(valid_prices), 8)
                self._pool[symbol_key]["updated"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    async def get_best_price(self, symbol: str) -> float:
        key = symbol.upper().replace("/", "").replace("-", "")
        if not key.endswith("USDT"):
            key += "USDT"
        async with self._lock:
            return self._pool.get(key, {}).get("best_price", 0.0)

    async def snapshot(self, limit: int = 50) -> Dict[str, Any]:
        async with self._lock:
            valid = {
                s: d for s, d in self._pool.items()
                if d.get("best_price", 0) > 0
            }
            sorted_items = sorted(
                valid.items(),
                key=lambda x: x[1]["best_price"],
                reverse=True
            )[:limit]
            tickers = {}
            for symbol, data in sorted_items:
                changes = [
                    src["change_24h"]
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

    async def all_items(self) -> Dict[str, Dict]:
        async with self._lock:
            return dict(self._pool)

price_pool = PricePool()

# ========== REALTIME BROADCAST ==========
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
            self.subscribers -= disconnected

rt_ticker = RealtimeTicker()

# ========== GLOBAL STATE ==========
top_gainers: List[Dict] = []
top_losers: List[Dict] = []   # ✅ eksik olan eklendi
last_update: str = "Yükleniyor..."
background_tasks: List[asyncio.Task] = []
shutdown_evt = asyncio.Event()

# ========== WEBSOCKET STREAMS ==========
async def _watch_tickers(exchange_id: str):
    """
    Generic ticker stream for Binance/Bybit/OKX using ccxt.pro
    """
    exchange = exchanges.get(exchange_id)
    if not exchange:
        logger.error(f"{exchange_id} exchange not initialized")
        return

    # utils.symbol_map’dan sembolleri al
    symbols = [
        symbol_map[exchange_id][s]
        for s in all_usdt_symbols
        if s in symbol_map[exchange_id]
    ]
    if not symbols:
        logger.warning(f"{exchange_id}: No valid symbols to subscribe")
        return

    chunk_size = 50
    chunks = [symbols[i:i + chunk_size] for i in range(0, len(symbols), chunk_size)]
    logger.info(f"📡 {exchange_id.upper()} WS subscribing {len(symbols)} symbols in {len(chunks)} chunks")

    while not shutdown_evt.is_set():
        for chunk in chunks:
            try:
                tickers = await exchange.watch_tickers(chunk)
                for raw_sym, t in tickers.items():
                    # Normalize to pool key: BTC/USDT → BTCUSDT
                    key = raw_sym.upper().replace("/", "").replace("-", "")
                    if not key.endswith("USDT"):
                        key += "USDT"
                    price = t.get("last") or t.get("close") or 0
                    change = t.get("percentage") or 0
                    await price_pool.update(exchange_id, key, price, change)
            except Exception as e:
                logger.error(f"{exchange_id} WS error: {e}")
                await asyncio.sleep(3)
                break  # Chunk başarısızsa yeniden dene
        await asyncio.sleep(0.3)

async def binance_stream():
    await _watch_tickers("binance")

async def bybit_stream():
    await _watch_tickers("bybit")

async def okx_stream():
    await _watch_tickers("okx")

# ========== REALTIME BROADCAST TASK ==========
async def realtime_broadcast_task():
    logger.info("📊 Realtime broadcast başladı")
    await asyncio.sleep(2)
    while not shutdown_evt.is_set():
        data = await price_pool.snapshot(50)
        await rt_ticker.broadcast(data)
        await asyncio.sleep(3)

# ========== PUMP RADAR ==========
async def pump_radar_task():
    logger.info("🔥 Pump radar başladı")
    global top_gainers, top_losers, last_update
    while not shutdown_evt.is_set():
        try:
            pool_items = await price_pool.all_items()
            gainers, losers = [], []
            for symbol_key, data in pool_items.items():
                if data.get("best_price", 0) <= 0:
                    continue
                changes = [
                    s["change_24h"]
                    for s in data["sources"].values()
                    if s.get("change_24h") is not None
                ]
                if not changes:
                    continue
                avg_change = sum(changes) / len(changes)
                entry = {
                    "symbol": symbol_key.replace("USDT", ""),
                    "price": data["best_price"],
                    "change": round(avg_change, 2),
                }
                if avg_change >= 2.0:
                    gainers.append(entry)
                elif avg_change <= -2.0:
                    losers.append(entry)

            gainers.sort(key=lambda x: x["change"], reverse=True)
            losers.sort(key=lambda x: x["change"])  # en düşen ilk
            top_gainers = gainers[:10]
            top_losers = losers[:10]
            last_update = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        except Exception as e:
            logger.error(f"Pump radar error: {e}")
        await asyncio.sleep(20)

# ========== LIFECYCLE ==========
async def initialize():
    """
    core.py’yi başlat. utils.py önceden initialize edilmelidir.
    """
    global all_usdt_symbols, symbol_map, exchanges

    # utils.py’dan import edilen global’lere ulaş
    from utils import all_usdt_symbols as _sym, symbol_map as _map, exchanges as _ex

    all_usdt_symbols = _sym
    symbol_map = _map
    exchanges = {
        "binance": ccxt_pro.binance({"enableRateLimit": True}),
        "bybit": ccxt_pro.bybit({"enableRateLimit": True}),
        "okx": ccxt_pro.okx({"enableRateLimit": True}),
    }

    logger.info(f"🚀 Core başlatılıyor... ({len(all_usdt_symbols)} symbols)")

    tasks = [
        realtime_broadcast_task(),
        pump_radar_task(),
        binance_stream(),
        bybit_stream(),
        okx_stream(),
    ]
    background_tasks.extend([asyncio.create_task(t) for t in tasks])
    logger.info("✅ Core hazır")

async def cleanup():
    logger.info("🛑 Core kapanıyor...")
    shutdown_evt.set()
    for task in background_tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
    background_tasks.clear()

    # ccxt.pro exchange’leri kapat
    for ex in exchanges.values():
        try:
            await ex.close()
        except Exception:
            pass

    logger.info("✅ Core temizlendi")


# ========== EXPORT ==========
__all__ = [
    "rt_ticker",
    "price_pool",
    "top_gainers",
    "top_losers",        # ✅ artık var
    "last_update",
    "initialize",
    "cleanup",
]

logger.info("✅ core.py hazır!")
