"""
Production-Ready Finance Data Pool
==================================
- Çoklu veri kaynağı (Finnhub WebSocket, Binance WebSocket, Yahoo Finance)
- Redis ile merkezi veri havuzu (dayanıklı bağlantı, retry mekanizması)
- Environment variable ile güvenli konfigürasyon
- Gelişmiş loglama (dosya rotasyonu, console)
- Prometheus metrikleri (izlenebilirlik)
- Sinyal yönetimi ile düzgün kapanma
- Veri doğrulama ve temizlik
"""

import os
import sys
import time
import json
import logging
import signal
import threading
from threading import Thread, Event
from typing import Optional, Dict, Any
from logging.handlers import RotatingFileHandler

import redis
from redis.exceptions import RedisError
import websocket
import yfinance as yf
from prometheus_client import start_http_server, Counter, Gauge

# -----------------------------------------------------------------------------
# Konfigürasyon (Environment Variable + Varsayılanlar)
# -----------------------------------------------------------------------------
class Config:
    FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
    if not FINNHUB_API_KEY:
        logging.warning("FINNHUB_API_KEY environment variable is not set. Finnhub WS will not work.")

    REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
    REDIS_DB = int(os.environ.get("REDIS_DB", 0))
    REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)

    STOCKS = os.environ.get("STOCKS", "AAPL,TSLA,MSFT,GOOGL,AMZN").split(",")
    CRYPTO_SYMBOLS = os.environ.get("CRYPTO_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")

    YAHOO_SYNC_INTERVAL = int(os.environ.get("YAHOO_SYNC_INTERVAL", 900))  # 15 dakika
    YAHOO_API_DELAY = int(os.environ.get("YAHOO_API_DELAY", 2))            # istekler arası bekleme

    PROMETHEUS_PORT = int(os.environ.get("PROMETHEUS_PORT", 8000))
    LOG_FILE = os.environ.get("LOG_FILE", "finance_pool.log")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# -----------------------------------------------------------------------------
# Loglama Yapılandırması (Rotasyon + Console)
# -----------------------------------------------------------------------------
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, Config.LOG_LEVEL))

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Dosya handler (rotasyonlu)
    file_handler = RotatingFileHandler(Config.LOG_FILE, maxBytes=10**7, backupCount=5)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

logger = setup_logging()

# -----------------------------------------------------------------------------
# Redis Bağlantısı (Dayanıklı, Retry Mekanizmalı)
# -----------------------------------------------------------------------------
class RedisClient:
    def __init__(self):
        self.pool = redis.ConnectionPool(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            db=Config.REDIS_DB,
            password=Config.REDIS_PASSWORD,
            decode_responses=True,
            socket_keepalive=True,
            retry_on_timeout=True,
            max_connections=20
        )
        self.client = redis.Redis(connection_pool=self.pool)

    def hset_with_retry(self, name, mapping=None, retries=3, delay=0.5):
        for attempt in range(retries):
            try:
                return self.client.hset(name, mapping=mapping)
            except RedisError as e:
                logger.warning(f"Redis hset error (attempt {attempt+1}/{retries}): {e}")
                if attempt < retries - 1:
                    time.sleep(delay * (2 ** attempt))  # exponential backoff
                else:
                    logger.error(f"Failed to hset {name} after {retries} attempts")
                    raise
        return None

    def hgetall(self, name):
        try:
            return self.client.hgetall(name)
        except RedisError as e:
            logger.error(f"Redis hgetall error: {e}")
            return {}

redis_client = RedisClient()

# -----------------------------------------------------------------------------
# Prometheus Metrikleri
# -----------------------------------------------------------------------------
class Metrics:
    price_updates = Counter('price_updates_total', 'Total price updates', ['source', 'symbol'])
    sync_updates = Counter('sync_updates_total', 'Total sync (Yahoo) updates', ['symbol'])
    errors = Counter('errors_total', 'Total errors', ['source', 'type'])
    last_price = Gauge('last_price', 'Last price by symbol', ['symbol'])

metrics = Metrics()

# -----------------------------------------------------------------------------
# Veri Havuzuna Yazma (Doğrulama + Kaynak Bazlı)
# -----------------------------------------------------------------------------
def update_pool(symbol: str, price: Optional[float], source: str, extra_data: Optional[Dict] = None):
    """
    Veri havuzuna (Redis hash) yazar.
    - price: None ise fiyat güncellenmez (sadece extra_data işlenir)
    - source: veri kaynağı (finnhub_ws, binance_ws, yahoo_sync)
    - extra_data: market_cap, day_high gibi ek alanlar
    """
    try:
        mapping = {
            "source": source,
            "last_update": int(time.time())
        }

        # Fiyat doğrulama: varsa float ve pozitif olmalı
        if price is not None:
            try:
                price_float = float(price)
                if price_float <= 0:
                    raise ValueError(f"Non-positive price: {price_float}")
                mapping["price"] = price_float
                metrics.price_updates.labels(source=source, symbol=symbol).inc()
                metrics.last_price.labels(symbol=symbol).set(price_float)
            except (TypeError, ValueError) as e:
                logger.error(f"Invalid price for {symbol} from {source}: {price} - {e}")
                metrics.errors.labels(source=source, type='invalid_price').inc()
                return

        # Extra verileri ekle (doğrulama yapmadan kabul et, ama tip kontrolü yapılabilir)
        if extra_data:
            # Basit tip kontrolü (gerektiğinde genişletilebilir)
            for k, v in extra_data.items():
                if v is not None and not isinstance(v, (str, int, float, bool)):
                    logger.warning(f"Extra data field {k} has unexpected type {type(v)} for {symbol}")
            mapping.update(extra_data)

        # Redis'e yaz (retry mekanizmalı)
        redis_client.hset_with_retry(f"pool:{symbol}", mapping=mapping)

    except Exception as e:
        logger.error(f"Unexpected error in update_pool for {symbol}: {e}")
        metrics.errors.labels(source=source, type='unexpected').inc()

# -----------------------------------------------------------------------------
# 1. Finnhub WebSocket (Hisse Senetleri)
# -----------------------------------------------------------------------------
def finnhub_launcher(stop_event: Event):
    uri = f"wss://ws.finnhub.io?token={Config.FINNHUB_API_KEY}"
    while not stop_event.is_set():
        try:
            def on_message(ws, message):
                try:
                    data = json.loads(message)
                    if data.get('type') == 'trade':
                        for trade in data.get('data', []):
                            symbol = trade['s']
                            price = trade['p']
                            update_pool(symbol, price, "finnhub_ws")
                except Exception as e:
                    logger.error(f"Finnhub on_message error: {e}")
                    metrics.errors.labels(source='finnhub', type='message_processing').inc()

            def on_open(ws):
                logger.info("Finnhub WebSocket connected")
                for s in Config.STOCKS:
                    ws.send(json.dumps({"type": "subscribe", "symbol": s}))

            def on_error(ws, error):
                logger.error(f"Finnhub WebSocket error: {error}")
                metrics.errors.labels(source='finnhub', type='connection').inc()

            def on_close(ws, close_status_code, close_msg):
                logger.warning("Finnhub WebSocket closed, reconnecting...")

            ws = websocket.WebSocketApp(
                uri,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            logger.error(f"Finnhub main loop error: {e}")
            metrics.errors.labels(source='finnhub', type='loop').inc()
        time.sleep(5)  # yeniden bağlanmadan önce bekle

# -----------------------------------------------------------------------------
# 2. Binance WebSocket (Kripto Paralar)
# -----------------------------------------------------------------------------
def binance_launcher(stop_event: Event):
    streams = "/".join([f"{s.lower()}@trade" for s in Config.CRYPTO_SYMBOLS])
    uri = f"wss://stream.binance.com:9443/stream?streams={streams}"

    while not stop_event.is_set():
        try:
            def on_message(ws, message):
                try:
                    data = json.loads(message)['data']
                    symbol = data['s'].replace("USDT", "-USD")  # Normalizasyon
                    price = data['p']
                    update_pool(symbol, price, "binance_ws")
                except Exception as e:
                    logger.error(f"Binance on_message error: {e}")
                    metrics.errors.labels(source='binance', type='message_processing').inc()

            def on_error(ws, error):
                logger.error(f"Binance WebSocket error: {error}")
                metrics.errors.labels(source='binance', type='connection').inc()

            ws = websocket.WebSocketApp(
                uri,
                on_message=on_message,
                on_error=on_error
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            logger.error(f"Binance main loop error: {e}")
            metrics.errors.labels(source='binance', type='loop').inc()
        time.sleep(5)

# -----------------------------------------------------------------------------
# 3. Yahoo Finance Periyodik Senkronizasyon (Sadece Analitik Veriler)
# -----------------------------------------------------------------------------
def yahoo_sync_worker(stop_event: Event):
    """Yahoo Finance'ten market cap, günlük high/low gibi verileri çeker, price yazmaz."""
    all_symbols = Config.STOCKS + [s.replace("USDT", "-USD") for s in Config.CRYPTO_SYMBOLS]

    while not stop_event.is_set():
        for symbol in all_symbols:
            if stop_event.is_set():
                break
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.fast_info

                # Fiyat hariç sadece analitik veriler
                extra = {
                    "market_cap": info.get("market_cap", 0),
                    "day_high": info.get("day_high", 0),
                    "day_low": info.get("day_low", 0),
                    "sync_status": "synced"
                }
                # price=None => fiyat güncellenmez
                update_pool(symbol, price=None, source="yahoo_sync", extra_data=extra)
                metrics.sync_updates.labels(symbol=symbol).inc()
                logger.info(f"Yahoo analytics synced for {symbol}")

                time.sleep(Config.YAHOO_API_DELAY)  # API koruması
            except Exception as e:
                logger.error(f"Yahoo sync error for {symbol}: {e}")
                metrics.errors.labels(source='yahoo', type='sync').inc()

        # Periyodik bekleme (genellikle 15 dakika)
        for _ in range(Config.YAHOO_SYNC_INTERVAL // 10):
            if stop_event.is_set():
                break
            time.sleep(10)

# -----------------------------------------------------------------------------
# Analiz Motoru (Kullanıcı Sorguları İçin)
# -----------------------------------------------------------------------------
def get_live_analysis(symbol: str) -> Dict[str, Any]:
    """Redis havuzundan veriyi alır, analiz edip döndürür."""
    data = redis_client.hgetall(f"pool:{symbol}")
    if not data:
        return {"error": f"⚠️ Veri havuzunda {symbol} bulunamadı."}

    now = int(time.time())
    last_ts = int(data.get('last_update', 0))
    price = float(data.get('price', 0))
    market_cap = float(data.get('market_cap', 0))

    status = "🟢 LIVE" if (now - last_ts) < 30 else "🟡 DELAYED"

    return {
        "symbol": symbol,
        "price": price,
        "market_cap": f"{market_cap:,.0f} $",
        "status": status,
        "source": data.get('source', 'unknown'),
        "last_update": last_ts,
        "day_high": float(data.get('day_high', 0)),
        "day_low": float(data.get('day_low', 0))
    }

# -----------------------------------------------------------------------------
# Sinyal Yönetimi (Graceful Shutdown)
# -----------------------------------------------------------------------------
def signal_handler(sig, frame, stop_event):
    logger.info(f"Signal {sig} received, shutting down...")
    stop_event.set()

# -----------------------------------------------------------------------------
# Ana Çalıştırıcı
# -----------------------------------------------------------------------------
def main():
    logger.info("Starting Finance Data Pool System (Production Ready)")

    # Prometheus metrik sunucusunu başlat (ayrı thread)
    try:
        start_http_server(Config.PROMETHEUS_PORT)
        logger.info(f"Prometheus metrics server started on port {Config.PROMETHEUS_PORT}")
    except Exception as e:
        logger.error(f"Failed to start Prometheus server: {e}")

    stop_event = Event()
    signal.signal(signal.SIGINT, lambda s, f: signal_handler(s, f, stop_event))
    signal.signal(signal.SIGTERM, lambda s, f: signal_handler(s, f, stop_event))

    threads = [
        Thread(target=finnhub_launcher, args=(stop_event,), name="Finnhub-WS", daemon=True),
        Thread(target=binance_launcher, args=(stop_event,), name="Binance-WS", daemon=True),
        Thread(target=yahoo_sync_worker, args=(stop_event,), name="Yahoo-Sync", daemon=True)
    ]

    for t in threads:
        t.start()
        logger.info(f"Thread {t.name} started")

    # Ana thread beklemede kalır, stop_event ile kapanır
    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()

    logger.info("Waiting for threads to finish (max 10s)...")
    for t in threads:
        t.join(timeout=10)
    logger.info("System shutdown complete.")

if __name__ == "__main__":
    main() 
