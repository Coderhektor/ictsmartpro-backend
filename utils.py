# utils.py
import ccxt.async_support as ccxt
import httpx
from datetime import datetime

print("🔄 utils.py yükleniyor...")

# Binance exchange – rate limit korumalı
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',
        'adjustForTimeDifference': True
    }
})

# OHLCV cache (tekrar çekmemek için)
ohlcv_cache = {}
CACHE_TTL = 25  # saniye (tarama sıklığına göre güvenli)

# Yüklenecek USDT sembolleri
all_usdt_symbols = []


async def load_all_symbols():
    """
    Binance'ten aktif ve hacimli USDT çiftlerini yükler.
    En iyi 150 coini seçer.
    """
    global all_usdt_symbols
    try:
        print("📡 Binance'ten sembol listesi alınıyor...")
        
        # exchangeInfo ile tüm sembolleri al
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get("https://api.binance.com/api/v3/exchangeInfo")
            info = response.json()

        symbols = [
            s["symbol"]
            for s in info.get("symbols", [])
            if s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
            and "SPOT" in s.get("permissions", [])
        ]

        print(f"✅ {len(symbols)} USDT çifti bulundu. Hacim sıralaması yapılıyor...")

        # Hacim bilgisi için ticker'ları toplu al
        tickers = await exchange.fetch_tickers(symbols[:300])  # Rate limit için sınırlı

        vol_list = []
        for sym in symbols:
            ticker = tickers.get(sym)
            if ticker:
                volume = ticker.get("quoteVolume", 0)
                if volume > 100_000:  # min 100k USDT günlük hacim
                    vol_list.append((sym, volume))

        # Hacme göre sırala ve en iyi 150'yi al
        vol_list.sort(key=lambda x: x[1], reverse=True)
        all_usdt_symbols = [sym for sym, _ in vol_list[:150]]

        print(f"🚀 {len(all_usdt_symbols)} yüksek hacimli USDT çifti yüklendi!")

    except Exception as e:
        print(f"⚠️ Sembol yükleme hatası: {e}")
        print("🔄 Fallback: Popüler coinler yüklenecek...")
        all_usdt_symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
            "ADAUSDT", "DOGEUSDT", "TRXUSDT", "LINKUSDT", "DOTUSDT",
            "MATICUSDT", "LTCUSDT", "AVAXUSDT", "SHIBUSDT", "PEPEUSDT",
            "TONUSDT", "BCHUSDT", "NEARUSDT", "UNIUSDT", "SUIUSDT"
        ]
        print(f"✅ Fallback ile {len(all_usdt_symbols)} coin yüklendi.")


async def fetch_ohlcv(symbol: str, timeframe: str, limit: int = 200) -> list:
    """
    Cache'li ve güvenli OHLCV çekme.
    indicators.py bu fonksiyonu kullanacak.
    """
    if not symbol.endswith("USDT"):
        symbol += "USDT"  # güvenlik

    key = f"{symbol}_{timeframe}_{limit}"
    now = datetime.now().timestamp()

    # Cache kontrol
    cached = ohlcv_cache.get(key)
    if cached and (now - cached["ts"] < CACHE_TTL):
        return cached["data"]

    try:
        data = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        ohlcv_cache[key] = {"data": data, "ts": now}
        return data
    except Exception as e:
        print(f"❌ OHLCV hatası ({symbol} {timeframe}): {e}")
        return []


print("✅ utils.py hazır!")
