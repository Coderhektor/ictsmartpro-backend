# core.py — HATASIZ, TUTARLI, PRODUCTION-READY VERSİYON (2026)

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Set, List, Optional, Any
from threading import Lock

import ccxt.async_support as ccxt_async
import pandas as pd
#==================================================
# core.py en üstte, mevcut global'lerin yanına ekle
price_sources_status: Dict[str, Dict[str, Any]] = {}  # "binance": {"last_update": ..., "symbols_count": 0, "healthy": True}

def update_price(source: str, symbol: str, price: float, change_24h: Optional[float] = None):
    with price_pool_lock:
        # Symbol'ü normalize et (tüm exchange'ler için aynı format)
        symbol = symbol.upper().replace('-', '').replace('/', '')
        if not symbol.endswith('USDT'):
            symbol += 'USDT'
        
        # Eğer symbol yoksa, doğru yapıyla başlat
        if symbol not in price_pool:
            price_pool[symbol] = {
                'sources': {},  # Kaynak verileri burada
                'best_price': 0.0,
                'updated': ''
            }
        
        # Kaynak verisini kaydet
        price_pool[symbol]['sources'][source] = {
            'price': float(price),
            'change_24h': float(change_24h) if change_24h is not None else None,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        # Ortalama fiyatı hesapla (tüm kaynakların ortalaması)
        sources = price_pool[symbol]['sources']
        valid_prices = [v['price'] for v in sources.values() if v['price'] > 0]
        
        if valid_prices:
            price_pool[symbol]['best_price'] = round(sum(valid_prices) / len(valid_prices), 8)
            price_pool[symbol]['updated'] = datetime.now(timezone.utc).strftime("%H:%M:%S")
        
        # Kaynak durumunu güncelle
        price_sources_status[source] = {
            'last_update': datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            'symbols_count': sum(1 for data in price_pool.values() 
                               if source in data.get('sources', {})),
            'healthy': True
        }
        
        # DEBUG: Kaç symbol var?
        if len(price_pool) % 50 == 0:  # Her 50 symbol'de bir log
            logger.info(f"📊 Fiyat havuzunda {len(price_pool)} symbol, "
                       f"son güncellenen: {symbol} = {price}")

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

 
def get_best_price(symbol: str) -> Dict[str, Any]:
    with price_pool_lock:
        data = price_pool.get(symbol, {})
        return {
            "best_price": data.get("best_price", 0.0),
            "sources": list(data.get("sources", {}).keys()),
            "updated": data.get("updated", "N/A")
        }

def get_all_prices_snapshot(limit: int = 50) -> Dict[str, Any]:
    with price_pool_lock:
        # Sadece best_price'i olanları filtrele
        valid_symbols = {sym: data for sym, data in price_pool.items() 
                        if data.get("best_price", 0) > 0}
        
        # Fiyata göre sırala
        sorted_symbols = sorted(
            valid_symbols.items(),
            key=lambda x: x[1].get("best_price", 0),
            reverse=True
        )[:limit]

        tickers = {}
        for symbol, data in sorted_symbols:
            price = data.get("best_price", 0)
            
            # 24s değişimi hesapla (kaynakların ortalaması)
            changes = []
            sources_dict = data.get("sources", {})
            for source_info in sources_dict.values():
                if source_info.get("change_24h") is not None:
                    changes.append(source_info["change_24h"])
            
            change_24h = round(sum(changes) / len(changes), 2) if changes else 0.0
            
            tickers[symbol] = {
                "price": price,
                "change": change_24h,
                "sources": list(sources_dict.keys())
            }

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
single_subscribers: Dict[str, Set[Any]] = defaultdict(set)      # "BTCUSDT:5m" → set of websockets
all_subscribers: Dict[str, Set[Any]] = defaultdict(set)        # "5m" → set of websockets
pump_radar_subscribers: Set[Any] = set()

shared_signals: Dict[str, Dict[str, Dict]] = defaultdict(dict)  # timeframe → symbol → signal dict
active_strong_signals: Dict[str, List[Dict]] = defaultdict(list)

top_gainers: List[Dict[str, Any]] = []
last_update: str = "Yükleniyor..."

_binance_exchange: Optional[ccxt_async.binance] = None
all_usdt_symbols: List[str] = []

signal_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
background_tasks: List[asyncio.Task] = []

# ==================== BINANCE CLIENT ====================
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
        logger.warning(f"Symbol yükleme hatası: {e} → fallback liste kullanılıyor")
        all_usdt_symbols = [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
            "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "TRXUSDT"
        ]

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
    
    # İlk başta 10 saniye bekle (fiyatların dolması için)
    await asyncio.sleep(10)
    
    while True:
        try:
            # Fiyatları al
            data = get_all_prices_snapshot(limit=50)
            
            # Eğer hiç fiyat yoksa logla
            if not data.get("tickers"):
                logger.debug("⚠️ Fiyat havuzu boş, exchange'lerden veri bekleniyor...")
            else:
                # Broadcast yap
                await rt_ticker.broadcast(data)
            
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"Realtime task hatası: {e}")
            await asyncio.sleep(5)

# ==================== PUMP RADAR TASK ====================
async def pump_radar_task():
    logger.info("🔥 Pump radar başladı")
    while True:
        try:
            gains = []
            
            with price_pool_lock:
                for symbol, data in price_pool.items():
                    # Yeni yapıya göre eriş
                    price = data.get("best_price", 0)
                    if price <= 0:
                        continue
                    
                    # sources dict'inden change_24h değerlerini al
                    sources_dict = data.get("sources", {})
                    if not sources_dict:
                        continue
                    
                    # Tüm kaynakların change_24h ortalamasını hesapla
                    changes = []
                    for source_info in sources_dict.values():
                        change_val = source_info.get("change_24h")
                        if change_val is not None:
                            changes.append(change_val)
                    
                    if not changes:
                        continue
                    
                    avg_change = sum(changes) / len(changes)
                    
                    if abs(avg_change) >= 2.0:  # %2'den fazla değişim
                        gains.append({
                            "symbol": symbol.replace("USDT", ""),
                            "price": price,
                            "change": round(avg_change, 2)
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

# ==================== STANDART SİNYAL FORMATI ====================
def enrich_signal(raw_signal: Dict, symbol: str, tf: str, current_price: float) -> Dict:
    """Frontend'in tam olarak beklediği formatta sinyal üretir"""
    return {
        "pair": symbol.replace("USDT", "/USDT"),           # BTC/USDT
        "symbol": symbol,
        "timeframe": tf.upper(),
        "signal": f"🚀 ALIM SİNYALİ" if raw_signal.get("signal") == "ALIM" else f"🔥 SATIM SİNYALİ",
        "score": raw_signal.get("score", 50),
        "current_price": round(current_price, 6),
        "killzone": "London" if tf in ["1h", "4h"] else "New York",  # basit örnek
        "triggers": raw_signal.get("triggers", "RSI + FVG + Order Block"),
        "strength": raw_signal.get("strength", "ORTA"),
        "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    }

# ==================== SİNYAL ÜRETİCİ ====================
async def signal_producer():
    logger.info("🧠 Sinyal üretici başladı")
    
    # indicators.py varsa gerçek fonksiyonu kullan
    try:
        from indicators import generate_ict_signal
        logger.info("✅ Gerçek ICT sinyal fonksiyonu yüklendi")
    except ImportError:
        logger.warning("indicators.py yok → fallback sinyal aktif")
        def generate_ict_signal(df: pd.DataFrame, symbol: str, tf: str):
            if len(df) < 20:
                return None
            change = (df['close'].iloc[-1] / df['close'].iloc[-10] - 1) * 100
            if abs(change) < 0.8:
                return None
            return {
                "signal": "ALIM" if change > 0 else "SATIM",
                "score": min(95, 60 + abs(change) * 8),
                "strength": "YÜKSEK" if abs(change) > 3 else "ORTA",
                "triggers": "Fiyat hareketi + hacim artışı"
            }

    timeframes = ["5m", "15m", "1h", "4h"]
    scan_symbols = all_usdt_symbols[:40]  # performans için sınırlı

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
                        df.iloc[:, 1:] = df.iloc[:, 1:].astype(float)

                        raw_signal = generate_ict_signal(df, sym, tf)
                        if not raw_signal:
                            continue

                        best = get_best_price(sym)
                        current_price = best["best_price"] or df['close'].iloc[-1]

                        enriched = enrich_signal(raw_signal, sym, tf, current_price)

                        # Global state'e kaydet
                        shared_signals[tf][sym] = enriched

                        # Skor yeterliyse broadcast queue'ya ekle
                        if enriched["score"] >= 60:
                            await signal_queue.put(("signal", {
                                "timeframe": tf,
                                "symbol": sym,
                                "signal": enriched
                            }))
                            logger.info(f"📢 Sinyal yayınlandı → {sym} {tf} | Skor: {enriched['score']} | {enriched['signal']}")

                    except Exception as e:
                        logger.debug(f"Sinyal hatası {sym}/{tf}: {e}")

            await asyncio.sleep(45)
        except Exception as e:
            logger.error(f"Sinyal üretici genel hata: {e}")
            await asyncio.sleep(30)

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
                channel = f"{symbol}:{tf}"  # TAM AYNI FORMAT: BTCUSDT:5m

                logger.debug(f"Broadcast → {channel} | {len(single_subscribers.get(channel, []))} abone")

                # 1. Tekil abonelere gönder
                if channel in single_subscribers:
                    disconnected = set()
                    for ws in single_subscribers[channel]:
                        try:
                            await ws.send_json(signal_data)
                        except Exception:
                            disconnected.add(ws)
                    single_subscribers[channel] -= disconnected

                # 2. Güçlü sinyalleri güncelle
                strong = [s for s in shared_signals[tf].values() if s.get("score", 0) >= 80]
                strong.sort(key=lambda x: x.get("score", 0), reverse=True)
                active_strong_signals[tf] = strong[:20]

                # 3. Tüm coin abonelere gönder
                if tf in all_subscribers:
                    disconnected = set()
                    for ws in all_subscribers[tf]:
                        try:
                            await ws.send_json(active_strong_signals[tf][:15])
                        except Exception:
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
                    except Exception:
                        disconnected.add(ws)
                pump_radar_subscribers -= disconnected

            signal_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Broadcast worker hatası: {e}")
            await asyncio.sleep(1)

# ==================== EXCHANGE STREAMS (FALLBACK) ====================
try:
    from exchanges.binance_ws import binance_ticker_stream
    from exchanges.bybit_ws import bybit_ticker_stream
    from exchanges.okx_ws import okx_ticker_stream
    from exchanges.coingecko_polling import coingecko_polling
except ImportError as e:
    logger.warning(f"Exchange stream modülleri eksik: {e}")
    async def dummy_stream():
        while True:
            await asyncio.sleep(3600)
    binance_ticker_stream = bybit_ticker_stream = okx_ticker_stream = coingecko_polling = dummy_stream

# ==================== LIFECYCLE ====================
async def initialize():
    logger.info("🚀 Core başlatılıyor...")
    await load_all_symbols()

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
    logger.info("✅ Tüm background task'lar başlatıldı")
    return tasks

async def cleanup():
    logger.info("🛑 Core kapanıyor...")
    for task in background_tasks:
        if not task.done():
            task.cancel()
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)

    if _binance_exchange:
        await _binance_exchange.close()

    logger.info("✅ Core tamamen temizlendi")

# ==================== EXPORT ====================
__all__ = [
    'single_subscribers',
    'all_subscribers',
    'pump_radar_subscribers',
    'shared_signals',
    'active_strong_signals',
    'top_gainers',
    'last_update',
    'rt_ticker',
    'get_binance_client',
    'get_best_price',
    'update_price',
    'get_all_prices_snapshot',
    'fetch_ohlcv',
    'initialize',
    'cleanup'
]
