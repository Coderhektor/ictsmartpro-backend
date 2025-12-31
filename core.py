# core.py — MULTI-EXCHANGE & RAILWAY PRODUCTION READY (HATALAR DÜZELTİLDİ)
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

#=======================================================================================
# core.py (güncellenmiş kısım)
# ... (diğer kodlar aynı)

# Price Pool (havuz)
price_pool: Dict[str, Dict[str, Any]] = {}
price_pool_lock = Lock()

def update_price(source: str, symbol: str, price: float, change_24h: Optional[float] = None):
    """Exchange'den veri at - havuza ekle"""
    with price_pool_lock:
        if symbol not in price_pool:
            price_pool[symbol] = {}
        price_pool[symbol][source] = {
            "price": float(price),
            "change_24h": float(change_24h) if change_24h is not None else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        # Ortalama best_price hesapla
        valid_prices = [info["price"] for info in price_pool[symbol].values() if isinstance(info, dict) and info["price"] > 0]
        if valid_prices:
            price_pool[symbol]["best_price"] = sum(valid_prices) / len(valid_prices)
            price_pool[symbol]["sources"] = list(price_pool[symbol].keys())
            price_pool[symbol]["updated"] = datetime.now(timezone.utc).strftime("%H:%M:%S")

# Ardışık Veri Atma (opsiyonel - paralel yerine kullanma)
async def sequential_price_update():
    """Exchange'leri sırayla çağır - havuza at"""
    while True:
        for exchange_func in [binance_ticker_stream, bybit_ticker_stream, okx_ticker_stream, coingecko_polling]:
            try:
                await exchange_func()  # Sırayla çalıştır
            except Exception as e:
                logger.error(f"Exchange hatası: {e}")
        await asyncio.sleep(60)  # 1 dakika sonra tekrarla

# initialize() içine ekle (eğer ardışık istersen):
background_tasks.append(asyncio.create_task(sequential_price_update()))

# Ama tavsiye: Her exchange'i ayrı task olarak bırak (paralel)!
#=======================================================================================
# ==================== MULTI-EXCHANGE PRICE POOL ====================
price_pool: Dict[str, Dict[str, Any]] = {}
price_pool_lock = Lock()

def update_price(source: str, symbol: str, price: float, change_24h: Optional[float] = None):
    """Güvenli şekilde coin fiyatını havuza ekler"""
    with price_pool_lock:
        if symbol not in price_pool:
            price_pool[symbol] = {}

        price_pool[symbol][source] = {
            "price": float(price),
            "change_24h": float(change_24h) if change_24h is not None else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # En iyi fiyatı (ortalama) hesapla
        valid_prices = [
            info["price"]
            for info in price_pool[symbol].values()
            if isinstance(info, dict) and info.get("price", 0) > 0
        ]
        if valid_prices:
            avg = sum(valid_prices) / len(valid_prices)
            price_pool[symbol]["best_price"] = round(avg, 8)
            price_pool[symbol]["sources"] = [
                src for src, info in price_pool[symbol].items()
                if isinstance(info, dict) and info.get("price", 0) > 0
            ]
            price_pool[symbol]["updated"] = datetime.now(timezone.utc).strftime("%H:%M:%S")

def get_best_price(symbol: str) -> Dict[str, Any]:
    """Belirli bir sembol için en iyi fiyatı döndür"""
    with price_pool_lock:
        data = price_pool.get(symbol, {})
        return {
            "best_price": data.get("best_price", 0.0),
            "sources": data.get("sources", []),
            "updated": data.get("updated", "N/A")
        }

def get_all_prices_snapshot(limit: int = 50) -> Dict[str, Any]:
    """Frontend'e gönderilecek realtime_price payload'ı üretir"""
    with price_pool_lock:
        tickers = {}
        for symbol, data in list(price_pool.items())[:limit]:
            price = data.get("best_price", 0)
            if price <= 0:
                continue

            # change_24h: herhangi bir kaynaktan al
            change = 0.0
            for src_data in data.values():
                if isinstance(src_data, dict) and src_data.get("change_24h") is not None:
                    change = float(src_data["change_24h"])
                    break

            tickers[symbol] = {
                "price": price,
                "change": round(change, 2)
            }

        return {
            "tickers": tickers,
            "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        }


# ==================== REALTIME TICKER ====================
class RealtimeTicker:
    """Real-time ticker broadcast için manager"""
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
        """Tüm abonelere veri gönder"""
        async with self.lock:
            dead = []
            for ws in self.subscribers:
                try:
                    await ws.send_json(data)
                except:
                    dead.append(ws)
            for ws in dead:
                self.subscribers.discard(ws)

# Global realtime ticker instance
rt_ticker = RealtimeTicker()


# ==================== GLOBAL STATE ====================
# WebSocket subscriber kümeleri
single_subscribers: Dict[str, Set[Any]] = defaultdict(set)
all_subscribers: Dict[str, Set[Any]] = defaultdict(set)
pump_radar_subscribers: Set[Any] = set()
realtime_subscribers: Set[Any] = set()  # DÜZELTİLDİ: main.py için gerekli

# Sinyal verileri
shared_signals: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
active_strong_signals: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

# Pump radar
top_gainers: List[Dict[str, Any]] = []
last_update: str = "Yükleniyor..."

# Binance client
_binance_exchange: Optional[ccxt_async.binance] = None
all_usdt_symbols: List[str] = []

# Sinyal iş kuyruğu
signal_queue: asyncio.Queue = asyncio.Queue(maxsize=500)

# Background tasks
background_tasks: List[asyncio.Task] = []


# ==================== UTILITY FUNCTIONS ====================
def get_binance_client() -> Optional[ccxt_async.binance]:
    """Frontend ve sinyal üretici tarafından OHLCV çekerken kullanılır"""
    return _binance_exchange


# ==================== BROADCAST WORKER (DÜZELTİLDİ) ====================
async def broadcast_worker():
    """Tüm WebSocket abonelerine veri broadcast eder"""
    logger.info("📡 Broadcast worker başladı")
    
    while True:
        try:
            msg_type, payload = await signal_queue.get()

            if msg_type == "signal":
                tf = payload["timeframe"]
                symbol = payload["symbol"]
                signal_data = payload["signal"]
                channel = f"{symbol}:{tf}"

                # 1. Tek coin abonelerine gönder
                if channel in single_subscribers:
                    dead = set()
                    for ws in list(single_subscribers[channel]):
                        try:
                            await ws.send_json(signal_data)
                        except:
                            dead.add(ws)
                    single_subscribers[channel] -= dead

                # 2. Güçlü sinyalleri güncelle
                strong = [
                    s for s in shared_signals[tf].values()
                    if isinstance(s, dict) and s.get("score", 0) >= 80
                ]
                strong.sort(key=lambda x: x.get("score", 0), reverse=True)
                active_strong_signals[tf] = strong[:20]

                # 3. Tüm coin abonelerine gönder
                if tf in all_subscribers:
                    dead = set()
                    for ws in list(all_subscribers[tf]):
                        try:
                            await ws.send_json(active_strong_signals[tf][:15])
                        except:
                            dead.add(ws)
                    all_subscribers[tf] -= dead

            elif msg_type == "pump_radar":
                global top_gainers, last_update
                top_gainers = payload.get("top_gainers", [])[:10]
                last_update = payload.get("last_update", datetime.now(timezone.utc).strftime("%H:%M:%S"))

                dead = set()
                for ws in list(pump_radar_subscribers):
                    try:
                        await ws.send_json(payload)
                    except:
                        dead.add(ws)
                pump_radar_subscribers -= dead

            elif msg_type == "realtime_price":
                # realtime_subscribers'a gönder (global değişken)
                dead = set()
                for ws in list(realtime_subscribers):
                    try:
                        await ws.send_json(payload)
                    except:
                        dead.add(ws)
                realtime_subscribers -= dead

            signal_queue.task_done()

        except asyncio.CancelledError:
            logger.info("⏹️ Broadcast worker durduruldu")
            break
        except Exception as e:
            logger.error(f"Broadcast worker hatası: {e}", exc_info=True)
            await asyncio.sleep(1)


# ==================== SYMBOL YÜKLEME ====================
async def load_all_symbols():
    global all_usdt_symbols, _binance_exchange
    try:
        if not _binance_exchange:
            _binance_exchange = ccxt_async.binance({
                'enableRateLimit': True,
                'rateLimit': 1200,
                'options': {'defaultType': 'spot'}
            })
        await _binance_exchange.load_markets()
        usdt_pairs = [
            s for s in _binance_exchange.symbols 
            if s.endswith('/USDT') and _binance_exchange.markets[s].get('active', False)
        ]
        all_usdt_symbols = [s.replace('/', '') for s in usdt_pairs][:120]
        logger.info(f"✅ {len(all_usdt_symbols)} USDT çifti yüklendi (Binance)")
    except Exception as e:
        logger.warning(f"Symbol yükleme hatası: {e} → Fallback liste")
        all_usdt_symbols = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","BNBUSDT","ADAUSDT","DOGEUSDT"]


# ==================== OHLCV ====================
async def fetch_ohlcv(symbol: str, timeframe: str = "5m", limit: int = 150):
    global _binance_exchange
    if not _binance_exchange:
        return []
    try:
        formatted = symbol.replace('USDT', '/USDT')
        return await _binance_exchange.fetch_ohlcv(formatted, timeframe=timeframe, limit=limit)
    except Exception as e:
        logger.debug(f"{symbol} OHLCV hatası: {e}")
        return []


# ==================== REALTIME PRICE BROADCAST ====================
async def realtime_price_broadcast_task():
    """Her 3 saniyede bir price_pool'dan en iyi fiyatları toplayıp abonelere gönderir"""
    logger.info("📊 Realtime fiyat broadcast başladı")
    while True:
        try:
            payload = get_all_prices_snapshot(limit=50)
            await signal_queue.put(("realtime_price", payload))
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"Realtime broadcast hatası: {e}")
            await asyncio.sleep(5)


# ==================== PUMP RADAR TASK ====================
async def pump_radar_task():
    """price_pool'dan en çok yükselenleri tespit eder"""
    logger.info("🔥 Pump radar başladı")
    while True:
        try:
            gains = []
            scan_symbols = all_usdt_symbols[:30]
            with price_pool_lock:
                for symbol in scan_symbols:
                    data = price_pool.get(symbol, {})
                    price = data.get("best_price", 0)
                    if price <= 0:
                        continue

                    change = 0.0
                    for src_data in data.values():
                        if isinstance(src_data, dict) and src_data.get("change_24h") is not None:
                            change = float(src_data["change_24h"])
                            break

                    if abs(change) >= 2.0:
                        gains.append({
                            "symbol": symbol.replace("USDT", ""),
                            "price": price,
                            "change": round(change, 2)
                        })

            if gains:
                gains.sort(key=lambda x: abs(x["change"]), reverse=True)
                await signal_queue.put(("pump_radar", {
                    "top_gainers": gains[:8],
                    "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                }))

            await asyncio.sleep(20)
        except Exception as e:
            logger.error(f"Pump radar hatası: {e}")
            await asyncio.sleep(20)


# ==================== SİNYAL ÜRETİCİ ====================
async def signal_producer():
    """Sinyal üretici task"""
    logger.info("🧠 Sinyal üretici başladı")
    
    try:
        # Indicators modülünü dynamic import et
        from indicators import generate_ict_signal
    except ImportError as e:
        logger.warning(f"indicators.py yüklenemedi, fallback fonksiyon kullanılıyor: {e}")
        def generate_ict_signal(df: pd.DataFrame, symbol: str, tf: str) -> Optional[Dict[str, Any]]:
            # Fallback basit sinyal üretici
            if len(df) < 10:
                return None
            
            last_close = df['close'].iloc[-1]
            prev_close = df['close'].iloc[-2]
            change = ((last_close - prev_close) / prev_close) * 100
            
            if abs(change) > 1.5:
                return {
                    "symbol": symbol,
                    "timeframe": tf,
                    "score": 70,
                    "action": "BUY" if change > 0 else "SELL",
                    "signal": "ALIM" if change > 0 else "SATIM",  # Türkçe sinyal
                    "change": round(change, 2),
                    "current_price": float(last_close),
                    "strength": "YÜKSEK" if abs(change) > 3 else "ORTA",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S")
                }
            return None

    timeframes = ["5m", "15m", "1h", "4h"]
    scan_symbols = all_usdt_symbols[:30]
    await asyncio.sleep(15)  # Sistemin tam başlaması için bekle

    while True:
        signal_count = 0
        start = asyncio.get_event_loop().time()

        for tf in timeframes:
            for symbol in scan_symbols:
                try:
                    klines = await fetch_ohlcv(symbol, tf, 150)
                    if len(klines) < 50:
                        continue

                    df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume'])
                    df.iloc[:,1:] = df.iloc[:,1:].astype(float)
                    
                    signal = generate_ict_signal(df, symbol, tf)
                    if signal:
                        price_info = get_best_price(symbol)
                        signal["current_price"] = price_info.get("best_price", signal.get("current_price", 0))
                        signal["sources"] = ", ".join(price_info.get("sources", ["binance"]))
                        shared_signals[tf][symbol] = signal
                        signal_count += 1

                        if signal.get("score", 0) >= 65:
                            await signal_queue.put(("signal", {
                                "timeframe": tf,
                                "symbol": symbol,
                                "signal": signal
                            }))
                except Exception as e:
                    logger.debug(f"Sinyal hatası {symbol}/{tf}: {e}")

        elapsed = asyncio.get_event_loop().time() - start
        logger.info(f"🔄 Tarama tamamlandı: {signal_count} sinyal | {elapsed:.1f}s")
        await asyncio.sleep(max(10, 45 - elapsed))


# ==================== LIFECYCLE ====================
async def initialize():
    """Core sistemini başlat"""
    logger.info("🚀 Core başlatılıyor (Multi-Exchange Ready)")
    await load_all_symbols()
    
    # Task'ları oluştur ve sakla
    tasks = [
        asyncio.create_task(broadcast_worker(), name="broadcast_worker"),
        asyncio.create_task(signal_producer(), name="signal_producer"),
        asyncio.create_task(realtime_price_broadcast_task(), name="realtime_price_broadcast"),
        asyncio.create_task(pump_radar_task(), name="pump_radar")
    ]
    
    # Global task listesine ekle
    background_tasks.extend(tasks)
    
    logger.info("✅ Core sistemi aktif")
    return tasks


async def cleanup():
    """Core sistemini temizle"""
    logger.info("🛑 Core kapanıyor...")
    
    # Tüm background task'ları iptal et
    for task in background_tasks:
        if not task.done():
            task.cancel()
    
    # Task'ların tamamlanmasını bekle
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)
    
    # Binance exchange'i kapat
    global _binance_exchange
    if _binance_exchange:
        await _binance_exchange.close()
        _binance_exchange = None
    
    logger.info("✅ Temizlendi")


# ==================== EXPORT ====================
# Dışa aktarılacak değişkenler ve fonksiyonlar
__all__ = [
    # Değişkenler
    'single_subscribers',
    'all_subscribers',
    'pump_radar_subscribers',
    'realtime_subscribers',
    'shared_signals',
    'active_strong_signals',
    'top_gainers',
    'last_update',
    'rt_ticker',
    
    # Fonksiyonlar
    'get_binance_client',
    'get_best_price',
    'update_price',
    'get_all_prices_snapshot',
    'fetch_ohlcv',
    'signal_queue',
    
    # Lifecycle
    'initialize',
    'cleanup'
]
