# core.py - MULTI-EXCHANGE PROD VERSİYON (YENİDEN YAPILANDIRILDI)

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Set, List, Optional

import ccxt.async_support as ccxt_async
import pandas as pd
from fastapi import WebSocket
from threading import Lock

logger = logging.getLogger("core")
logger.setLevel(logging.INFO)

# ==================== MULTI-EXCHANGE PRICE POOL ====================
price_pool = {}  # Ana havuz: {"BTCUSDT": {"binance": {...}, "bybit": {...}, "best_price": 65000, ...}}
price_pool_lock = Lock()

def update_price(source: str, symbol: str, price: float, change_24h: float = None):
    """Her borsadan gelen fiyatı güvenli şekilde havuza ekler"""
    with price_pool_lock:
        if symbol not in price_pool:
            price_pool[symbol] = {}
        
        price_pool[symbol][source] = {
            "price": price,
            "change_24h": change_24h,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Tüm kaynaklardan gelen geçerli fiyatları topla
        valid_prices = [info["price"] for info in price_pool[symbol].values() if info["price"] > 0]
        if valid_prices:
            avg_price = sum(valid_prices) / len(valid_prices)
            price_pool[symbol]["best_price"] = round(avg_price, 8)
            price_pool[symbol]["sources"] = [src for src, info in price_pool[symbol].items() if info["price"] > 0]
            price_pool[symbol]["updated"] = datetime.utcnow().strftime("%H:%M:%S")

def get_best_price(symbol: str) -> dict:
    """Sinyal ve radar için en iyi fiyatı dön"""
    with price_pool_lock:
        data = price_pool.get(symbol, {})
        return {
            "best_price": data.get("best_price", 0),
            "sources": data.get("sources", []),
            "updated": data.get("updated", "N/A")
        }

# ==================== GLOBAL STATE (WebSocket aboneleri vs.) ====================
single_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)
all_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)
pump_radar_subscribers: Set[WebSocket] = set()
realtime_subscribers: Set[WebSocket] = set()

shared_signals: Dict[str, Dict[str, dict]] = defaultdict(dict)
active_strong_signals: Dict[str, List[dict]] = defaultdict(list)

top_gainers: List[dict] = []
last_update: str = "Yükleniyor..."

# Eski rt_ticker'ı kaldırdık → artık price_pool kullanıyoruz
# Ama frontend hâlâ /ws/realtime_price bekliyor → onu da price_pool'dan besleyeceğiz

exchange: Optional[ccxt_async.binance] = None
all_usdt_symbols: List[str] = []

signal_queue: asyncio.Queue = asyncio.Queue(maxsize=500)

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
                
                # Tek coin abonelerine gönder
                if channel in single_subscribers:
                    dead = set()
                    for ws in list(single_subscribers[channel]):
                        try:
                            await ws.send_json(signal_data)
                        except:
                            dead.add(ws)
                    single_subscribers[channel] -= dead
                
                # Güçlü sinyalleri güncelle
                strong = [s for s in shared_signals[tf].values() if s.get("score", 0) >= 80]
                strong.sort(key=lambda x: x.get("score", 0), reverse=True)
                active_strong_signals[tf] = strong[:20]
                
                # Tüm coin abonelerine güçlü sinyalleri gönder
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
                # Frontend hâlâ eski endpoint'i kullanıyor → price_pool'dan en iyi 50'yi gönder
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

# ==================== SYMBOL YÜKLEME ====================
async def load_all_symbols():
    global all_usdt_symbols, exchange
    try:
        if not exchange:
            exchange = ccxt_async.binance({'enableRateLimit': True, 'rateLimit': 1200})
        await exchange.load_markets()
        usdt_pairs = [s for s in exchange.symbols if s.endswith('/USDT') and exchange.markets[s]['active']]
        all_usdt_symbols = [s.replace('/', '') for s in usdt_pairs][:120]
        logger.info(f"✅ {len(all_usdt_symbols)} USDT çifti yüklendi (Binance)")
    except Exception as e:
        logger.warning(f"Symbol yükleme hatası: {e} → Fallback liste")
        all_usdt_symbols = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","BNBUSDT","ADAUSDT","DOGEUSDT"]

# ==================== OHLCV (Hâlâ Binance'dan çekiyoruz - grafik için) ====================
async def fetch_ohlcv(symbol: str, timeframe: str = "5m", limit: int = 150):
    global exchange
    if not exchange:
        return []
    try:
        formatted = symbol.replace('USDT', '/USDT')
        return await exchange.fetch_ohlcv(formatted, timeframe=timeframe, limit=limit)
    except Exception as e:
        logger.debug(f"{symbol} OHLCV hatası: {e}")
        return []

# ==================== REALTIME FİYAT GÖNDERİM (price_pool'dan besleniyor) ====================
async def realtime_price_broadcast_task():
    """price_pool'dan en iyi fiyatları toplayıp frontend'e gönderir"""
    logger.info("📊 Realtime fiyat broadcast başladı (multi-exchange)")
    while True:
        try:
            with price_pool_lock:
                tickers = {}
                for symbol, data in list(price_pool.items())[:50]:  # İlk 50 coin
                    if data.get("best_price", 0) > 0:
                        change = None
                        # Kaynaklardan birinin change'ini al
                        for src_data in data.values():
                            if isinstance(src_data, dict) and src_data.get("change_24h") is not None:
                                change = src_data["change_24h"]
                                break
                        tickers[symbol] = {
                            "price": data["best_price"],
                            "change": round(change, 2) if change is not None else 0
                        }
            
            if tickers:
                payload = {
                    "tickers": tickers,
                    "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S")
                }
                await signal_queue.put(("realtime_price", payload))
                
            await asyncio.sleep(3)  # Her 3 saniyede bir güncelle
            
        except Exception as e:
            logger.error(f"Realtime broadcast hatası: {e}")
            await asyncio.sleep(5)

# ==================== PUMP RADAR (price_pool'dan çalışacak) ====================
async def pump_radar_task():
    """price_pool'dan en çok yükselenleri bulup broadcast eder"""
    logger.info("🔥 Pump radar başladı (multi-exchange)")
    scan_symbols = all_usdt_symbols[:30]
    
    while True:
        try:
            gains = []
            with price_pool_lock:
                for symbol in scan_symbols:
                    data = price_pool.get(symbol, {})
                    price = data.get("best_price", 0)
                    if price <= 0:
                        continue
                    # En az bir kaynaktan change al
                    change = 0
                    for src_data in data.values():
                        if isinstance(src_data, dict) and src_data.get("change_24h") is not None:
                            change = src_data["change_24h"]
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
                
            await asyncio.sleep(20)  # Her 20 saniyede bir kontrol
            
        except Exception as e:
            logger.error(f"Pump radar hatası: {e}")
            await asyncio.sleep(20)

# ==================== SİNYAL ÜRETİCİ (price_pool kullanacak) ====================
async def signal_producer():
    logger.info("🧠 Sinyal üretici başladı (multi-exchange ready)")
    
    try:
        from indicators import generate_ict_signal
    except Exception as e:
        logger.error(f"indicators.py yüklenemedi: {e}")
        def generate_ict_signal(df, symbol, tf): return None
    
    timeframes = ["5m", "15m", "1h", "4h"]
    scan_symbols = all_usdt_symbols[:30]
    
    await asyncio.sleep(15)
    
    while True:
        start_time = asyncio.get_event_loop().time()
        signal_count = 0
        
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
                        # Fiyatı price_pool'dan al → daha doğru
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
        
        elapsed = asyncio.get_event_loop().time() - start_time
        logger.info(f"🔄 Tarama tamamlandı: {signal_count} sinyal | {elapsed:.1f}s")
        await asyncio.sleep(max(10, 45 - elapsed))

# ==================== INITIALIZE ====================
async def initialize():
    logger.info("🚀 Core başlatılıyor (Multi-Exchange Ready)")
    await load_all_symbols()
    
    global exchange
    if not exchange:
        exchange = ccxt_async.binance({
            'enableRateLimit': True,
            'rateLimit': 1200,
            'options': {'defaultType': 'spot'}
        })
    
    # Ana task'lar
    asyncio.create_task(broadcast_worker())
    asyncio.create_task(signal_producer())
    asyncio.create_task(realtime_price_broadcast_task())  # Yeni: price_pool'dan besleniyor
    asyncio.create_task(pump_radar_task())                # Yeni: price_pool'dan çalışıyor
    
    logger.info("✅ Core sistemleri aktif! Multi-exchange hazır.")

# ==================== CLEANUP ====================
async def cleanup():
    logger.info("🛑 Core kapanıyor...")
    global exchange
    if exchange:
        await exchange.close()
    logger.info("✅ Temizlendi")

def get_binance_client():
    return exchange
