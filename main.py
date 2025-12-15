import ccxt
import pandas as pd
import pandas_ta as ta
import asyncio
import httpx
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import time
import os

app = FastAPI()
app.mount("/assets", StaticFiles(directory=".", html=False), name="assets")

# Global değişkenler
top_gainers = []
last_update = "Başlatılıyor..."
exchange = ccxt.binance({'enableRateLimit': True})

# Aktif WebSocket bağlantıları
active_connections: dict[str, WebSocket] = {}

# OHLCV verisi için cache (key: "PAIR_TIMEFRAME", value: (ohlcv_data, timestamp))
ohlcv_cache: dict[str, tuple[list, float]] = {}
MAX_CACHE_SIZE = 50  # Maksimum 50 farklı coin/timeframe cache'te tutulur

# Log dosyası
LOG_FILE = "/data/all_signals.csv"

async def fetch_data():
    global top_gainers, last_update
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            binance_urls = [
                "https://data.binance.com/api/v3/ticker/24hr",
                "https://data-api.binance.vision/api/v3/ticker/24hr",
                "https://api1.binance.com/api/v3/ticker/24hr",
            ]
            binance_data = None
            for url in binance_urls:
                try:
                    resp = await client.get(url, timeout=10)
                    if resp.status_code == 200:
                        binance_data = resp.json()
                        break
                except:
                    continue

            if not binance_data:
                r1 = await client.get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=percent_change_24h_desc&per_page=250&page=1")
                r2 = await client.get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=percent_change_24h_desc&per_page=250&page=2")
                coingecko_data = (r1.json() + r2.json()) if r1.status_code == 200 and r2.status_code == 200 else []
            else:
                coingecko_data = []

            clean_coins = []
            if binance_data:
                for item in binance_data:
                    s = item.get("symbol", "")
                    if not s.endswith("USDT"): continue
                    try:
                        price = float(item["lastPrice"])
                        change = float(item["priceChangePercent"])
                        volume = float(item["quoteVolume"])
                        if volume >= 1_000_000:
                            clean_coins.append({"symbol": s.replace("USDT", "/USDT"), "price": price, "change": change})
                    except: continue

            for item in coingecko_data:
                try:
                    sym = item["symbol"].upper()
                    if any(c["symbol"].startswith(sym) for c in clean_coins): continue
                    price = item["current_price"]
                    change = item["price_change_percentage_24h"] or 0
                    volume = item["total_volume"]
                    if volume >= 1_000_000:
                        clean_coins.append({"symbol": f"{sym}/USDT", "price": price, "change": change})
                except: continue

            top_gainers = sorted(clean_coins, key=lambda x: x["change"], reverse=True)[:10]
            last_update = datetime.now().strftime("%H:%M:%S")
    except Exception as e:
        print("Pump Radar veri hatası:", e)
        last_update = "Bağlantı Hatası"

@app.on_event("startup")
async def startup():
    await fetch_data()
    
    async def radar_loop():
        while True:
            await asyncio.sleep(30)
            await fetch_data()
    asyncio.create_task(radar_loop())

    async def signal_broadcaster():
        while True:
            await asyncio.sleep(15)
            for key, ws in list(active_connections.items()):
                try:
                    pair, timeframe = key.split("_", 1)
                    result = await calculate_signal(pair, timeframe)
                    if result and "error" not in result:
                        await ws.send_json(result)
                except Exception as e:
                    print(f"Broadcast hatası ({key}): {e}")
                    try:
                        await ws.close()
                    except:
                        pass
                    active_connections.pop(key, None)

    asyncio.create_task(signal_broadcaster())

# Sinyal hesaplama (cache'li + limit=100)
async def calculate_signal(original_pair: str, timeframe: str):
    global ohlcv_cache
    pair = original_pair.upper().replace("/", "").replace(" ", "").replace("-", "")
    if not pair.endswith("USDT"):
        if not (pair.endswith("UP") or pair.endswith("DOWN")):
            pair += "USDT"

    cache_key = f"{pair}_{timeframe}"
    current_time = time.time()

    try:
        valid_timeframes = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d','3d','1w','1M']
        if timeframe not in valid_timeframes:
            return {"error": "Geçersiz zaman dilimi"}

        # Cache kontrolü
        if cache_key in ohlcv_cache:
            cached_ohlcv, cached_time = ohlcv_cache[cache_key]
            if current_time - cached_time < 30:  # 30 saniye cache
                ohlcv = cached_ohlcv
                print(f"Cache'den alındı: {original_pair} {timeframe}")
            else:
                ohlcv = await asyncio.to_thread(exchange.fetch_ohlcv, pair, timeframe, limit=100)
                ohlcv_cache[cache_key] = (ohlcv, current_time)
                print(f"Yeni veri indirildi: {original_pair} {timeframe}")
        else:
            ohlcv = await asyncio.to_thread(exchange.fetch_ohlcv, pair, timeframe, limit=100)
            ohlcv_cache[cache_key] = (ohlcv, current_time)
            print(f"İlk indirme: {original_pair} {timeframe}")

        # Cache boyutu sınırı
        if len(ohlcv_cache) > MAX_CACHE_SIZE:
            # En eskiyi sil
            oldest_key = min(ohlcv_cache, key=lambda k: ohlcv_cache[k][1])
            del ohlcv_cache[oldest_key]

        if not ohlcv or len(ohlcv) < 50:
            return {"error": "Veri yetersiz veya coin bulunamadı"}

        df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','volume'])
        df['EMA21'] = ta.ema(df['close'], length=21)
        df['RSI14'] = ta.rsi(df['close'], length=14)
        
        last = df.iloc[-1]
        price = float(last['close'])
        ema = last['EMA21']
        rsi = last['RSI14']

        if pd.isna(ema) or pd.isna(rsi):
            signal = "Yetersiz Veri"
        elif price > ema and rsi < 30:
            signal = "🔥 ÇOK GÜÇLÜ ALIM 🔥"
        elif price > ema and rsi < 45:
            signal = "🚀 ALIM SİNYALİ 🚀"
        elif price < ema and rsi > 70:
            signal = "⚠️ SATIM SİNYALİ ⚠️"
        elif price < ema and rsi > 55:
            signal = "⚡ ZAYIF SATIŞ UYARISI ⚡"
        else:
            signal = "😐 NÖTR / BEKLEMEDE"

        result = {
            "pair": original_pair.replace("USDT", "/USDT") if "/" not in original_pair else original_pair,
            "timeframe": timeframe,
            "current_price": round(price, 8),
            "ema_21": round(ema, 8) if not pd.isna(ema) else None,
            "rsi_14": round(rsi, 2) if not pd.isna(rsi) else None,
            "signal": signal,
            "last_candle": pd.to_datetime(last['ts'], unit='ms').strftime("%d.%m %H:%M")
        }

        # Güvenli log kaydetme
        try:
            if os.path.exists("/data"):
                os.makedirs("/data", exist_ok=True)
                if not os.path.exists(LOG_FILE):
                    df.head(1).to_csv(LOG_FILE, index=False)
                df.tail(1).to_csv(LOG_FILE, mode='a', header=False, index=False)
                print(f"LOG KAYDEDİLDİ → {result['pair']} | {signal}")
        except Exception as e:
            print(f"Log hatası: {e}")

        return result

    except Exception as e:
        print(f"Sinyal hesaplama hatası ({original_pair} {timeframe}): {e}")
        return {"error": "Veri alınamadı veya teknik hata"}

# WebSocket Endpoint (değişmedi)
@app.websocket("/ws/signal/{pair}/{timeframe}")
async def websocket_endpoint(websocket: WebSocket, pair: str, timeframe: str):
    await websocket.accept()
    key = f"{pair.upper()}_{timeframe}"
    active_connections[key] = websocket

    try:
        initial_result = await calculate_signal(pair, timeframe)
        if initial_result:
            await websocket.send_json(initial_result)
    except:
        pass

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.pop(key, None)
    except Exception:
        active_connections.pop(key, None)

# Ana sayfa ve sinyal sayfası (öncekiyle aynı, değiştirmedim)
# ... (ana_sayfa ve signal_page fonksiyonları aynı kalıyor, önceki mesajdaki gibi)

@app.get("/", response_class=HTMLResponse)
async def ana_sayfa():
    # Önceki ana sayfa kodu (değişmedi)
    # ... (kodu kısalttım, önceki mesajdakiyle aynı)

@app.get("/signal", response_class=HTMLResponse)
async def signal_page():
    # Önceki canlı sinyal sayfası (değişmedi)
    # ... (kodu kısalttım, önceki mesajdakiyle aynı)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "time": datetime.now().isoformat(),
        "active_ws": len(active_connections),
        "cached_pairs": len(ohlcv_cache)
    }
