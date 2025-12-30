# core.py — RAILWAY İÇİN TAMAMEN DÜZELTİLDİ & OPTİMİZE EDİLDİ
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Set, List, Optional
import ccxt.async_support as ccxt_async

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

# ==================== BINANCE CLIENT ====================
exchange: Optional[ccxt_async.binance] = None

# ==================== SYMBOLS ====================
all_usdt_symbols: List[str] = []

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
                if channel in single_subscribers:
                    dead_ws = set()
                    for ws in list(single_subscribers[channel]):  # Listeye çevirerek güvenli iterasyon
                        try:
                            await ws.send_json(signal_data)
                        except Exception:
                            dead_ws.add(ws)
                    single_subscribers[channel] -= dead_ws

                # Güçlü sinyalleri güncelle
                if tf in shared_signals:
                    strong_list = [
                        sig for sig in shared_signals[tf].values()
                        if sig.get("score", 0) >= 85
                    ]
                    strong_list.sort(key=lambda x: x.get("score", 0), reverse=True)
                    active_strong_signals[tf] = strong_list[:15]

                    # Tüm coin abonelerine gönder
                    if tf in all_subscribers:
                        dead_ws = set()
                        for ws in list(all_subscribers[tf]):
                            try:
                                await ws.send_json(active_strong_signals[tf])
                            except Exception:
                                dead_ws.add(ws)
                        all_subscribers[tf] -= dead_ws

            elif msg_type == "pump_radar":
                global top_gainers, last_update
                top_gainers = payload.get("top_gainers", [])
                last_update = payload.get("last_update", "N/A")

                dead_ws = set()
                for ws in list(pump_radar_subscribers):
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        dead_ws.add(ws)
                pump_radar_subscribers.difference_update(dead_ws)

            elif msg_type == "realtime_price":
                dead_ws = set()
                for ws in list(realtime_subscribers):
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

# ==================== UTILITY FUNCTIONS ====================
async def load_all_symbols():
    """Binance'ten tüm USDT çiftlerini yükle"""
    global all_usdt_symbols, exchange
    
    try:
        if not exchange:
            exchange = ccxt_async.binance({
                'enableRateLimit': True,
                'rateLimit': 1200,
                'options': {
                    'defaultType': 'spot',
                }
            })
        
        markets = await exchange.load_markets()
        usdt_pairs = [symbol for symbol in markets 
                     if symbol.endswith('/USDT') and markets[symbol]['active']]
        
        # Clean symbol names (remove /)
        all_usdt_symbols = [s.replace('/', '') for s in usdt_pairs][:200]  # Limit for performance
        
        logger.info(f"✅ {len(all_usdt_symbols)} USDT çifti yüklendi")
        return all_usdt_symbols
        
    except Exception as e:
        logger.error(f"Symbol yükleme hatası: {e}")
        # Fallback: hardcoded symbols
        all_usdt_symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
            "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "MATICUSDT",
            "SHIBUSDT", "TRXUSDT", "LTCUSDT", "UNIUSDT", "LINKUSDT"
        ]
        return all_usdt_symbols

async def fetch_ohlcv(symbol: str, timeframe: str = "5m", limit: int = 150):
    """Binance'ten OHLCV verisi çek"""
    global exchange
    
    if not exchange:
        exchange = ccxt_async.binance({
            'enableRateLimit': True,
            'rateLimit': 1200
        })
    
    try:
        # Format symbol for ccxt (BTCUSDT -> BTC/USDT)
        formatted_symbol = symbol.replace('USDT', '/USDT')
        ohlcv = await exchange.fetch_ohlcv(
            formatted_symbol, 
            timeframe=timeframe, 
            limit=limit
        )
        return ohlcv
    except Exception as e:
        logger.error(f"OHLCV çekme hatası {symbol}: {e}")
        return []

# ==================== REALTIME PRICE STREAM ====================
async def realtime_price_stream():
    """Gerçek zamanlı fiyat akışı"""
    global exchange
    
    if not exchange:
        exchange = ccxt_async.binance({
            'enableRateLimit': True,
            'rateLimit': 1200
        })
    
    # İzlemek için semboller (ilk 50 tanesi)
    symbols_to_watch = all_usdt_symbols[:50] if all_usdt_symbols else ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    
    while True:
        try:
            if not exchange:
                await asyncio.sleep(5)
                continue
            
            # Binance ticker verilerini çek
            formatted_symbols = [s.replace('USDT', '/USDT') for s in symbols_to_watch]
            tickers = await exchange.fetch_tickers(formatted_symbols)
            
            updated = {}
            for sym in symbols_to_watch:
                ccxt_sym = sym.replace('USDT', '/USDT')
                if ccxt_sym in tickers and tickers[ccxt_sym]:
                    data = tickers[ccxt_sym]
                    updated[sym] = {
                        "price": float(data.get('last', 0)),
                        "change": float(data.get('percentage', 0) or 0)
                    }
            
            if updated:
                rt_ticker["tickers"] = updated
                rt_ticker["last_update"] = datetime.now(timezone.utc).strftime("%H:%M:%S")
                
                # Broadcast et
                await signal_queue.put(("realtime_price", rt_ticker.copy()))
            
        except Exception as e:
            logger.warning(f"Fiyat akışı hatası: {e}")
            await asyncio.sleep(5)  # Hata durumunda bekle
            
        await asyncio.sleep(3)  # 3 saniyede bir güncelle

# ==================== SIGNAL PRODUCER ====================
async def signal_producer():
    """ICT sinyalleri üret"""
    logger.info("🌀 Sinyal üretici başladı")

    try:
        from indicators import generate_ict_signal
        logger.info("✅ Indicators modülü yüklendi")
    except ImportError as e:
        logger.error(f"❌ Indicators modülü yüklenemedi: {e}")
        # Fallback function
        def generate_ict_signal(df, symbol, timeframe):
            last_price = df['close'].iloc[-1] if not df.empty else 0
            prev_price = df['close'].iloc[-2] if len(df) > 1 else last_price
            change = ((last_price - prev_price) / prev_price * 100) if prev_price else 0
            
            return {
                "signal": "ALIM" if change > 0 else "SATIM",
                "score": min(abs(int(change * 10)), 95),
                "strength": "YÜKSEK" if abs(change) > 1 else "ORTA",
                "killzone": "LONDRA" if "00:00" in timeframe else "NEWYORK",
                "triggers": "Demo: " + ("Yükseliş" if change > 0 else "Düşüş") + " eğilimi",
                "pair": symbol,
                "last_update": datetime.now().strftime("%H:%M:%S")
            }

    timeframes = ["5m", "15m", "1h", "4h"]  # Railway CPU için optimize edildi
    symbols_to_scan = all_usdt_symbols[:20] if all_usdt_symbols else ["BTCUSDT", "ETHUSDT"]  # Sınırlı sayıda

    await asyncio.sleep(10)  # Sistem yerleşsin

    while True:
        start_time = asyncio.get_event_loop().time()
        signals_found = 0

        for tf in timeframes:
            for symbol in symbols_to_scan:
                try:
                    ohlcv = await fetch_ohlcv(symbol, tf, limit=100)
                    if len(ohlcv) < 50:
                        continue

                    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    
                    # Sayısal verilere çevir
                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                    
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
                    continue

        # Pump Radar Güncelle (daha az sıklıkta)
        try:
            if symbols_to_scan:
                formatted_symbols = [s.replace('USDT', '/USDT') for s in symbols_to_scan]
                tickers = await exchange.fetch_tickers(formatted_symbols)
                gains = []
                
                for sym in symbols_to_scan:
                    ccxt_sym = sym.replace('USDT', '/USDT')
                    if ccxt_sym in tickers and tickers[ccxt_sym]:
                        data = tickers[ccxt_sym]
                        change = float(data.get('percentage', 0) or 0)
                        if abs(change) >= 3.0:  # %3+ hareket edenler
                            gains.append({
                                "symbol": sym.replace("USDT", ""),
                                "price": float(data.get('last', 0)),
                                "change": round(change, 2)
                            })

                gains.sort(key=lambda x: abs(x["change"]), reverse=True)
                await signal_queue.put(("pump_radar", {
                    "top_gainers": gains[:5],  # Daha az sayıda
                    "last_update": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                }))

        except Exception as e:
            logger.error(f"Pump radar hatası: {e}")

        elapsed = asyncio.get_event_loop().time() - start_time
        logger.info(f"Scan tamamlandı: {signals_found} sinyal bulundu | {elapsed:.1f}s")
        
        # Railway CPU için optimize bekleme süresi
        wait_time = max(10.0, 30.0 - elapsed)  # Minimum 10s, maksimum 30s
        await asyncio.sleep(wait_time)

# ==================== INIT & CLEANUP ====================
async def initialize():
    """Uygulamayı başlat"""
    logger.info("🚀 Core initialize ediliyor...")
    
    try:
        # Önce sembolleri yükle
        await load_all_symbols()
        
        # Exchange client'ı başlat
        global exchange
        if not exchange:
            exchange = ccxt_async.binance({
                'enableRateLimit': True,
                'rateLimit': 1200,
                'options': {
                    'defaultType': 'spot',
                }
            })
        
        # Worker'ları başlat
        asyncio.create_task(broadcast_worker())
        asyncio.create_task(signal_producer())
        asyncio.create_task(realtime_price_stream())
        
        logger.info("✅ Tüm core servisler başarıyla başlatıldı!")
        
    except Exception as e:
        logger.error(f"❌ Core initialize hatası: {e}", exc_info=True)
        raise

async def cleanup():
    """Uygulamayı temizle"""
    logger.info("🛑 Core cleanup yapılıyor...")
    
    global exchange
    
    try:
        # Exchange client'ı kapat
        if exchange:
            await exchange.close()
            exchange = None
            logger.info("✅ Exchange client kapatıldı")
            
    except Exception as e:
        logger.error(f"Cleanup hatası: {e}")
    
    logger.info("✅ Core cleanup tamamlandı")

# ==================== BINANCE CLIENT GETTER ====================
def get_binance_client():
    """main.py için binance client getter"""
    return exchange
