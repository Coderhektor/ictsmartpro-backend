# 📁 utils.py
"""
Multi-exchange OHLCV loader with symbol normalization, caching, and volume filtering.
Supports: Binance, Bybit, OKX
"""

import ccxt.async_support as ccxt
import httpx
import pandas as pd
from datetime import datetime, timedelta
import logging
import asyncio

# Logger
logger = logging.getLogger("utils")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

logger.info("🔄 utils.py yükleniyor...")

# ========== EXCHANGES ==========
exchanges = {}
ohlcv_cache = {}
CACHE_TTL = 25  # seconds

# ========== SYMBOL NORMALIZATION ==========
def normalize_symbol(symbol: str, exchange_id: str) -> str:
    """Normalize symbol for specific exchange"""
    symbol = symbol.strip().upper()

    # Split base/quote
    if "/" in symbol:
        base, quote = symbol.split("/", 1)
    elif "-" in symbol:
        base, quote = symbol.split("-", 1)
    elif symbol.endswith("USDT"):
        base, quote = symbol[:-4], "USDT"
    elif symbol.endswith("USD"):
        base, quote = symbol[:-3], "USD"
    else:
        # Fallback: last 3 chars = quote (e.g., ETHBTC)
        base, quote = symbol[:-3], symbol[-3:]

    # Bybit: remove 1000/100 prefixes for known memecoins
    if exchange_id == "bybit":
        memecoins = ["SHIB", "FLOKI", "CHEEMS", "BONK", "PEPE", "WIF", "MOG"]
        for prefix in ["1000", "100"]:
            if base.startswith(prefix):
                candidate = base[len(prefix):]
                if candidate in memecoins:
                    base = candidate
        return f"{base}{quote}"  # e.g., SHIBUSDT

    # OKX: requires BASE-QUOTE
    if exchange_id == "okx":
        return f"{base}-{quote}"  # e.g., BTC-USDT

    # Binance: prefers BASE/QUOTE or BASEUSDT (both work in fetch_ohlcv)
    if exchange_id == "binance":
        # We standardize to BASE/USDT internally for clarity
        return f"{base}/{quote}"

    return symbol  # fallback


async def init_exchanges():
    """Initialize exchanges with rate limiting and options"""
    global exchanges
    config = {
        "binance": {
            "enableRateLimit": True,
            "options": {"defaultType": "spot", "adjustForTimeDifference": True},
        },
        "bybit": {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        },
        "okx": {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        },
    }

    exchanges["binance"] = ccxt.binance(config["binance"])
    exchanges["bybit"] = ccxt.bybit(config["bybit"])
    exchanges["okx"] = ccxt.okx(config["okx"])

    logger.info("✅ Exchanges initialized (Binance, Bybit, OKX)")


# ========== SYMBOL DISCOVERY ==========
async def _fetch_binance_symbols() -> list:
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
    return symbols


async def _fetch_exchange_symbols(exchange_id: str) -> set:
    """Fetch active USDT spot symbols for given exchange"""
    try:
        ex = exchanges[exchange_id]
        await ex.load_markets()
        symbols = {
            m["symbol"]
            for m in ex.markets.values()
            if m.get("quote") == "USDT"
            and m.get("spot") is True
            and m.get("active") is True
        }
        logger.debug(f"{exchange_id}: {len(symbols)} active USDT symbols")
        return symbols
    except Exception as e:
        logger.warning(f"⚠️ {exchange_id} symbol list fetch failed: {e}")
        return set()


async def load_all_symbols():
    """
    Load top 150 high-volume USDT symbols (binance-based),
    then validate & normalize for each exchange.
    """
    global all_usdt_symbols, symbol_map

    logger.info("📡 High-volume symbols loading (Binance-based)...")

    try:
        # 1. Binance'den raw USDT sembolleri
        binance_raw = await _fetch_binance_symbols()
        if not binance_raw:
            raise Exception("Binance symbol list empty")

        # 2. Hacim bilgisi için ticker'ları çek (rate limit korumalı)
        binance = exchanges["binance"]
        # Batch: her seferinde 200 sembol, 100k altını eliyoruz
        vol_list = []
        for i in range(0, len(binance_raw), 200):
            batch = binance_raw[i : i + 200]
            try:
                tickers = await binance.fetch_tickers(batch)
                for sym in batch:
                    ticker = tickers.get(sym)
                    if ticker:
                        vol = float(ticker.get("quoteVolume", 0))
                        if vol >= 100_000:  # ≥ $100k daily volume
                            vol_list.append((sym, vol))
                await asyncio.sleep(0.1)  # Rate limit koruma
            except Exception as e:
                logger.warning(f"Ticker batch {i} skipped: {e}")

        # 3. Hacme göre sırala → top 150
        vol_list.sort(key=lambda x: x[1], reverse=True)
        top_symbols = [sym for sym, _ in vol_list[:150]]

        if not top_symbols:
            raise Exception("No high-volume symbols found")

        all_usdt_symbols = top_symbols
        logger.info(f"✅ {len(all_usdt_symbols)} high-volume USDT symbols selected")

        # 4. Her exchange için valid & normalize edilmiş map oluştur
        symbol_map = {}
        for ex_id in ["binance", "bybit", "okx"]:
            valid_symbols = await _fetch_exchange_symbols(ex_id)
            mapped = {}
            skipped = 0
            for s in all_usdt_symbols:
                norm = normalize_symbol(s, ex_id)
                if norm in valid_symbols:
                    mapped[s] = norm
                else:
                    skipped += 1
            symbol_map[ex_id] = mapped
            logger.info(f"→ {ex_id}: {len(mapped)} symbols mapped, {skipped} skipped")

    except Exception as e:
        logger.error(f"🚨 Symbol loading failed: {e}. Using fallback.")
        fallback = [
            "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
            "ADA/USDT", "DOGE/USDT", "TRX/USDT", "LINK/USDT", "DOT/USDT",
            "MATIC/USDT", "LTC/USDT", "AVAX/USDT", "SHIB/USDT", "PEPE/USDT",
            "TON/USDT", "BCH/USDT", "NEAR/USDT", "UNI/USDT", "SUI/USDT",
            "APT/USDT", "ICP/USDT", "FIL/USDT", "RNDR/USDT", "ATOM/USDT"
        ]
        all_usdt_symbols = [s.replace("/", "") for s in fallback]  # BTCUSDT format
        symbol_map = {
            "binance": {s: s.replace("/", "") for s in fallback},
            "bybit": {s: s.replace("/", "").replace("1000", "") for s in fallback},
            "okx": {s: s.replace("/", "-") for s in fallback},
        }
        logger.info(f"✅ Fallback: {len(all_usdt_symbols)} symbols loaded")


# ========== OHLCV FETCHER ==========
async def fetch_ohlcv(
    symbol: str,
    timeframe: str = "5m",
    limit: int = 200,
    exchange_id: str = "binance"
) -> pd.DataFrame:
    """
    Fetch OHLCV as DataFrame with caching & normalization.
    Parameters:
        symbol: "BTCUSDT" or "BTC/USDT" (base format)
        exchange_id: "binance" | "bybit" | "okx"
    Returns:
        pd.DataFrame with columns: open, high, low, close, volume, timestamp (index)
    """
    # Normalize symbol to base → exchange-specific
    if exchange_id not in symbol_map or symbol not in symbol_map[exchange_id]:
        logger.warning(f"Symbol '{symbol}' not mapped for {exchange_id}. Skipping.")
        return pd.DataFrame()

    actual_symbol = symbol_map[exchange_id][symbol]
    key = f"{exchange_id}_{actual_symbol}_{timeframe}_{limit}"
    now = datetime.now().timestamp()

    # Cache check
    cached = ohlcv_cache.get(key)
    if cached and (now - cached["ts"] < CACHE_TTL):
        return cached["data"]

    try:
        ex = exchanges[exchange_id]
        ohlcv = await ex.fetch_ohlcv(actual_symbol, timeframe, limit=limit)

        if not ohlcv or len(ohlcv) < 2:
            logger.warning(f"No OHLCV data for {exchange_id}:{actual_symbol}")
            return pd.DataFrame()

        # Convert to DataFrame
        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)

        # Cache
        ohlcv_cache[key] = {"data": df, "ts": now}
        if len(ohlcv_cache) > 500:
            # FIFO temizleme
            oldest_key = next(iter(ohlcv_cache))
            ohlcv_cache.pop(oldest_key, None)

        return df

    except Exception as e:
        logger.error(f"❌ OHLCV error ({exchange_id}:{actual_symbol}): {e}")
        return pd.DataFrame()


# ========== INIT ==========
async def initialize():
    """Initialize everything in correct order"""
    await init_exchanges()
    await load_all_symbols()


# Export globals
all_usdt_symbols = []
symbol_map = {}

logger.info("✅ utils.py hazır!")

# For direct run/test
if __name__ == "__main__":
    import asyncio
    asyncio.run(initialize())
    print(f"Top symbols: {all_usdt_symbols[:5]}")
