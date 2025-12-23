# utils.py
import ccxt.async_support as ccxt
import httpx
from datetime import datetime

# Binance exchange (rate limit korumalı)
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot'
    }
})

# OHLCV cache (tekrar tekrar çekmemek için)
ohlcv_cache = {}
CACHE_TTL = 25  # saniye

# Yüklü USDT sembolleri
all_usdt_symbols = []


async def load_all_symbols():
    """
    Binance'ten aktif USDT çiftlerini alır, hacme göre sıralar ve en iyi 150'sini seçer.
    """
    global all_usdt_symbols
    try:
        # exchangeInfo'dan sembol listesi al
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://api.binance.com/api/v3/exchangeInfo")
            info = r.json()

        symbols = [
            s["symbol"] for s in info.get("symbols", [])
            if s.get("quoteAsset") == "USDT"
               and s.get("status") == "TRADING"
               and "SPOT" in s.get("permissions", [])
        ]

        # Ticker'larla hacim bilgisi al
        tickers = await exchange.fetch_tickers(symbols[:300])  # Rate limit için sınırlı

        vol_sorted = []
        for sym in symbols:
            ticker = tickers.get(sym)
            if ticker and ticker.get("quoteVolume", 0) > 100_000:  # min 100k USDT hacim
                vol_sorted.append((sym, ticker["quoteVolume"]))

        vol_sorted.sort(key=lambda x: x[1], reverse=True)
        all_usdt_symbols = [sym for sym, _ in vol_sorted[:150]]

        print(f"✅ {len(all_usdt_symbols)} USDT çifti yüklendi (en hacimli)")

    except Exception as e:
        print(f"⚠️ Sembol yükleme hatası: {e}")
        # Fallback: Popüler coinler
        all_usdt_symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
            "DOGEUSDT", "TRXUSDT", "LINKUSDT", "DOTUSDT", "MATICUSDT", "LTCUSDT",
            "AVAXUSDT", "SHIBUSDT", "PEPEUSDT"
        ]


async def fetch_ohlcv(symbol: str, timeframe: str, limit: int = 200):
    """
    Cache'li OHLCV çekme fonksiyonu.
    indicators.py bu fonksiyonu kullanarak veri alacak.
    """
    key = f"{symbol}_{timeframe}_{limit}"
    now = datetime.now().timestamp()

    cached = ohlcv_cache.get(key)
    if cached and (now - cached["ts"] < CACHE_TTL):
        return cached["data"]

    try:
        # Binance format: [timestamp, open, high, low, close, volume]
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        ohlcv_cache[key] = {"data": ohlcv, "ts": now}
        return ohlcv
    except Exception as e:
        print(f"OHLCV çekme hatası {symbol} {timeframe}: {e}")
        return []
