# utils.py
import ccxt.async_support as ccxt
import httpx
from datetime import datetime
from collections import deque

exchange = ccxt.binance({'enableRateLimit': True})

ohlcv_cache = {}
CACHE_TTL = 25

all_usdt_symbols = []

async def load_all_symbols():
    global all_usdt_symbols
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://api.binance.com/api/v3/exchangeInfo")
            info = r.json()

        symbols = [
            s["symbol"] for s in info.get("symbols", [])
            if s.get("quoteAsset") == "USDT"
               and s.get("status") == "TRADING"
               and "SPOT" in s.get("permissions", [])
        ][:200]

        tickers = await exchange.fetch_tickers(symbols)
        vol_sorted = []
        for sym in symbols:
            ticker = tickers.get(sym)
            if ticker and ticker.get("quoteVolume", 0) > 100_000:
                vol_sorted.append((sym, ticker["quoteVolume"]))
        vol_sorted.sort(key=lambda x: x[1], reverse=True)
        all_usdt_symbols = [sym for sym, _ in vol_sorted[:150]]

    except Exception as e:
        print(f"Sembol yükleme hatası: {e}")
        all_usdt_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

async def fetch_ohlcv(symbol: str, timeframe: str, limit=50):
    key = f"{symbol}_{timeframe}"
    now = datetime.now().timestamp()
    cached = ohlcv_cache.get(key)
    if cached and now - cached["ts"] < CACHE_TTL:
        return cached["data"]

    try:
        ohlcv = await exchange.fetch_ohlcv(symbol[:-4] + "/USDT", timeframe=timeframe, limit=limit)
        ohlcv_cache[key] = {"data": ohlcv, "ts": now}
        return ohlcv
    except Exception as e:
        print(f"OHLCV hatası {symbol} {timeframe}: {e}")
        return []

async def generate_signal(symbol: str, timeframe: str, current_price: float, rt_ticker: dict):
    if timeframe == "realtime":
        trades = rt_ticker["tickers"].get(symbol, {}).get("trades", deque())
        if len(trades) < 10:
            return None
        prices = [t[1] for t in list(trades)[-10:]]
        vols = [t[2] for t in list(trades)[-20:]]
    else:
        ohlcv = await fetch_ohlcv(symbol, timeframe)
        if len(ohlcv) < 10:
            return None
        prices = [c[4] for c in ohlcv[-10:]]
        vols = [c[5] for c in ohlcv[-20:]]

    up_moves = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i - 1])
    down_moves = len(prices) - 1 - up_moves
    avg_vol = sum(vols) / len(vols) if vols else 1
    last_vol = vols[-1] if vols else 0
    volume_spike = last_vol > avg_vol * 1.8

    if up_moves >= 7 and volume_spike:
        signal_text = "💥 GÜÇLÜ ALIM!"
    elif up_moves >= 6:
        signal_text = "📈 YUKARI MOMENTUM"
    elif down_moves >= 7 and volume_spike:
        signal_text = "🔥 GÜÇLÜ SATIM!"
    elif down_moves >= 6:
        signal_text = "📉 AŞAĞI MOMENTUM"
    else:
        return None

    return {
        "pair": f"{symbol[:-4]}/USDT",
        "timeframe": timeframe,
        "current_price": round(current_price, 6 if current_price < 1 else 4),
        "signal": signal_text,
        "momentum": "up" if up_moves > down_moves else "down",
        "volume_spike": volume_spike,
        "last_update": datetime.now().strftime("%H:%M:%S")
    }
