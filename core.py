# core.py - PROD İÇİN TAM VERSİYON
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Set, List, Optional

import ccxt.async_support as ccxt_async
import pandas as pd

from fastapi import WebSocket
from threading import Lock
from datetime import datetime
import asyncio

# Global thread-safe price pool
price_pool = {}
price_pool_lock = Lock()

def update_price(source: str, symbol: str, price: float, change_24h: float = None):
    """Tüm borsalardan gelen fiyatları güvenli şekilde güncelle"""
    with price_pool_lock:
        if symbol not in price_pool:
            price_pool[symbol] = {}
        
        price_pool[symbol][source] = {
            "price": price,
            "change_24h": change_24h,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # En iyi fiyatı hesapla (örneğin ortalama veya en güncel)
        prices = [v["price"] for v in price_pool[symbol].values() if v["price"] > 0]
        if prices:
            price_pool[symbol]["best_price"] = sum(prices) / len(prices)
            price_pool[symbol]["sources"] = list(price_pool[symbol].keys())
            price_pool[symbol]["updated"] = datetime.utcnow().isoformat()

def get_price(symbol: str) -> dict:
    """Sinyal üretiminde kullanılacak fiyat bilgisini dön"""
    with price_pool_lock:
        return price_pool.get(symbol, {})

logger = logging.getLogger("core")
logger.setLevel(logging.INFO)

# GLOBAL STATE
single_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)
all_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)
pump_radar_subscribers: Set[WebSocket] = set()
realtime_subscribers: Set[WebSocket] = set()

shared_signals: Dict[str, Dict[str, dict]] = defaultdict(dict)
active_strong_signals: Dict[str, List[dict]] = defaultdict(list)

top_gainers: List[dict] = []
last_update: str = "Yükleniyor..."

rt_ticker = { "tickers": {}, "last_update": "" }

exchange: Optional[ccxt_async.binance] = None
all_usdt_symbols: List[str] = []

signal_queue: asyncio.Queue = asyncio.Queue(maxsize=500)

async def broadcast_worker():
    logger.info("📡 Broadcast worker başladı")
    
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
                last_update = payload.get("last_update", datetime.now(timezone.utc).strftime("%H:%M:%S"))
                
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

async def load_all_symbols():
    global all_usdt_symbols, exchange
    try:
        if not exchange:
            exchange = ccxt_async.binance({'enableRateLimit': True, 'rateLimit': 1200})
        await exchange.load_markets()
        usdt_pairs = [s for s in exchange.symbols if s.endswith('/USDT') and exchange.markets[s]['active']]
        all_usdt_symbols = [s.replace('/', '') for s in usdt_pairs][:120]
        logger.info(f"✅ {len(all_usdt_symbols)} USDT çifti yüklendi")
    except Exception as e:
        logger.warning(f"Symbol hatası: {e} → Fallback")
        all_usdt_symbols = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","AVAXUSDT","TRXUSDT","DOTUSDT"]

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

async def realtime_price_stream():
    logger.info("💹 Realtime fiyat başladı")
    symbols = all_usdt_symbols[:50] or ["BTCUSDT","ETHUSDT"]
    while True:
        try:
            formatted = [s.replace('USDT', '/USDT') for s in symbols]
            tickers = await exchange.fetch_tickers(formatted)
            updated = {}
            for sym in symbols:
                key = sym.replace('USDT', '/USDT')
                if key in tickers:
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
            logger.warning(f"Realtime hata: {e}")
        await asyncio.sleep(3)

async def signal_producer():
    logger.info("🧠 Sinyal üretici başladı")
    
    try:
        from indicators import generate_ict_signal
        logger.info("✅ indicators.py yüklendi")
    except Exception as e:
        logger.error(f"indicators.py yüklenemedi: {e}")
        def generate_ict_signal(df, symbol, tf):
            return None
    
    timeframes = ["5m", "15m", "1h", "4h"]
    scan_symbols = all_usdt_symbols[:30] or ["BTCUSDT","ETHUSDT","SOLUSDT"]
    
    await asyncio.sleep(10)
    
    while True:
        start = asyncio.get_event_loop().time()
        count = 0
        
        for tf in timeframes:
            for symbol in scan_symbols:
                try:
                    data = await fetch_ohlcv(symbol, tf, 150)
                    if len(data) < 50:
                        continue
                    df = pd.DataFrame(data, columns=['timestamp','open','high','low','close','volume'])
                    df.iloc[:,1:] = df.iloc[:,1:].astype(float)
                    
                    signal = generate_ict_signal(df, symbol, tf)
                    if signal:
                        shared_signals[tf][symbol] = signal
                        count += 1
                        logger.info(f"🎯 {symbol}/{tf} → {signal['signal']} | Skor: {signal['score']}")
                        if signal.get("score", 0) >= 65:
                            await signal_queue.put(("signal", {"timeframe": tf, "symbol": symbol, "signal": signal}))
                except Exception as e:
                    logger.debug(f"Sinyal hatası {symbol}/{tf}: {e}")
        
        # Pump radar
        try:
            formatted = [s.replace('USDT', '/USDT') for s in scan_symbols]
            tickers = await exchange.fetch_tickers(formatted)
            gains = []
            for sym in scan_symbols:
                key = sym.replace('USDT', '/USDT')
                if key in tickers:
                    t = tickers[key]
                    change = float(t.get('percentage') or 0)
                    price = float(t.get('last') or 0)
                    if abs(change) >= 2.0 and price > 0:
                        gains.append({"symbol": sym.replace("USDT",""), "price": price, "change": round(change,2)})
            gains.sort(key=lambda x: abs(x["change"]), reverse=True)
            await signal_queue.put(("pump_radar", {"top_gainers": gains[:8], "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")}))
        except Exception as e:
            logger.warning(f"Pump radar hatası: {e}")
        
        elapsed = asyncio.get_event_loop().time() - start
        logger.info(f"🔄 Tarama: {count} sinyal | {elapsed:.1f}s")
        await asyncio.sleep(max(10, 40 - elapsed))

async def initialize():
    logger.info("🚀 Core başlatılıyor...")
    await load_all_symbols()
    global exchange
    if not exchange:
        exchange = ccxt_async.binance({'enableRateLimit': True, 'rateLimit': 1200, 'options': {'defaultType': 'spot'}})
    asyncio.create_task(broadcast_worker())
    asyncio.create_task(signal_producer())
    asyncio.create_task(realtime_price_stream())
    logger.info("✅ Tüm sistemler aktif!")

async def cleanup():
    logger.info("🛑 Core kapanıyor...")
    global exchange
    if exchange:
        await exchange.close()
    logger.info("✅ Temizlendi")

def get_binance_client():
    return exchange
