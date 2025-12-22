# ==============================
# ICT SMART PRO — FINAL ASYNC & RAILWAY-OPTIMIZED
# ==============================
import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, Set

import ccxt.async_support as ccxt  # 🔥 ASYNC CCXT
import httpx
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ictsmartpro")


# --- LIFESPAN MANAGEMENT ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize_app()
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()


app = FastAPI(lifespan=lifespan)

# --- STATIC FILES (Railway-safe) ---
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    logger.warning(f"Static dizini yüklenemedi: {e}")


# --- GLOBAL STATE ---
class GlobalState:
    def __init__(self):
        # Exchange async olarak başlatıldı
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'timeout': 30000,
            'options': {'adjustForTimeDifference': True},
        })
        self.top_gainers = []
        self.last_update = "Yükleniyor..."
        self.all_usdt_symbols = []  # ["BTCUSDT", "ETHUSDT", ...]
        self.shared_signals = {tf: {} for tf in [
            "realtime", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"
        ]}
        self.active_strong_signals = defaultdict(list)
        self.single_subscribers = defaultdict(set)
        self.all_subscribers = defaultdict(set)
        self.pump_radar_subscribers = set()
        self.ohlcv_cache = {}
        self.rt_ticker = None
        self.tasks: list[asyncio.Task] = []


state = GlobalState()


# --- REAL-TIME TRADE STREAM (10 COIN) ---
class RealTimeTicker:
    def __init__(self):
        self.tickers = {}
        self.running = True

    async def start(self):
        symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
            "ADAUSDT", "DOGEUSDT", "SHIBUSDT", "AVAXUSDT", "TRXUSDT"
        ]
        streams = "/".join(f"{s.lower()}@trade" for s in symbols)
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"

        while self.running:
            try:
                async with websockets.connect(
                    url, ping_interval=20, ping_timeout=10, timeout=30
                ) as ws:
                    logger.info("✅ Realtime trade stream aktif (10 coin)")
                    while self.running:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=30)
                            data = json.loads(message)["data"]
                            if data["e"] != "trade":
                                continue
                            symbol = data["s"]
                            price = float(data["p"])
                            qty = float(data["q"])
                            timestamp = data["T"]

                            if symbol not in self.tickers:
                                self.tickers[symbol] = {
                                    "price": price,
                                    "trades": deque(maxlen=50)
                                }
                            self.tickers[symbol]["price"] = price
                            self.tickers[symbol]["trades"].append({
                                "time": timestamp,
                                "price": price,
                                "qty": qty
                            })
                        except asyncio.TimeoutError:
                            logger.debug("Trade stream timeout — ping bekleniyor")
                        except Exception as e:
                            logger.debug(f"Trade parse error: {e}")
            except Exception as e:
                logger.warning(f"Trade stream bağlantısı koptu: {e}")
                if self.running:
                    await asyncio.sleep(5)

    async def stop(self):
        self.running = False


# --- PUMP RADAR (24H TOP GAINERS) ---
async def fetch_pump_radar():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # ❗ Düzeltme: trailing space vardı — '24hr  ' → '24hr'
            r = await client.get("https://api.binance.com/api/v3/ticker/24hr")
            data = r.json()

        clean = []
        for item in data:
            if not item.get("symbol", "").endswith("USDT"):
                continue
            try:
                symbol = item["symbol"]
                price = float(item.get("lastPrice", 0))
                change = float(item.get("priceChangePercent", 0))
                volume = float(item.get("quoteVolume", 0))
                if volume >= 100_000 and abs(change) > 0.1:  # min 0.1% değişim
                    clean.append({
                        "symbol": symbol[:-4] + "/USDT",
                        "price": price,
                        "change": change,
                        "volume": volume
                    })
            except (ValueError, TypeError, KeyError):
                continue

        state.top_gainers = sorted(clean, key=lambda x: abs(x["change"]), reverse=True)[:10]
        state.last_update = datetime.now().strftime("%H:%M:%S")

        # WS abonelerine yayınla
        disconnected = set()
        payload = {"top_gainers": state.top_gainers, "last_update": state.last_update}
        for ws in state.pump_radar_subscribers:
            try:
                await ws.send_json(payload)
            except:
                disconnected.add(ws)

        for ws in disconnected:
            state.pump_radar_subscribers.discard(ws)

    except Exception as e:
        logger.error(f"Pump radar hatası: {e}")


# --- SEMBOL YÜKLE (ASYNC & GÜVENLİ) ---
async def load_all_symbols():
    try:
        # 🌟 En güvenli yöntem: exchangeInfo ile aktif USDT çiftlerini al
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get("https://api.binance.com/api/v3/exchangeInfo")
            info = r.json()

        # Sadece TRADING durumunda olan USDT çiftlerini al
        symbols = [
            s["symbol"] for s in info.get("symbols", [])
            if s.get("quoteAsset") == "USDT"
               and s.get("status") == "TRADING"
               and "SPOT" in s.get("permissions", [])
        ]

        # Hacim sıralaması için tickers al (rate limit dikkatli!)
        try:
            tickers = await state.exchange.fetch_tickers(symbols[:200])  # max 200
            # quoteVolume güvenli erişim
            symbol_volume = []
            for sym in symbols:
                ticker = tickers.get(sym)
                if ticker:
                    vol = ticker.get("quoteVolume", 0)
                    if vol and vol > 100_000:  # min 100k USDT hacim
                        symbol_volume.append((sym, vol))

            # Hacme göre sırala, ilk 100'ü al
            symbol_volume.sort(key=lambda x: x[1], reverse=True)
            state.all_usdt_symbols = [sym for sym, _ in symbol_volume[:100]]
        except Exception as e:
            logger.warning(f"Ticker sıralama hatası: {e}. Varsayılan 20 coin kullanılacak.")
            # Varsayılan popüler coin listesi
            state.all_usdt_symbols = [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
                "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT", "LINKUSDT",
                "DOTUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "XLMUSDT",
                "ETCUSDT", "BCHUSDT", "FILUSDT", "ICPUSDT", "VETUSDT"
            ]

        logger.info(f"✅ {len(state.all_usdt_symbols)} USDT çifti yüklendi")
    except Exception as e:
        logger.error(f"Sembol yükleme hatası: {e}")
        state.all_usdt_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]


# --- OHLCV CACHE (ASYNC & RATE-LIMIT SAFE) ---
async def fetch_ohlcv(symbol: str, timeframe: str, limit=30):
    key = f"{symbol}_{timeframe}"
    now = time.time()

    cached = state.ohlcv_cache.get(key)
    if cached and (now - cached["ts"] < 30):
        return cached["data"]

    try:
        ohlcv = await state.exchange.fetch_ohlcv(
            symbol=symbol[:-4] + "/USDT",
            timeframe=timeframe,
            limit=min(limit, 30)
        )
        state.ohlcv_cache[key] = {"data": ohlcv, "ts": now}
        return ohlcv
    except Exception as e:
        logger.debug(f"OHLCV hatası — {symbol} {timeframe}: {e}")
        return []


# --- SİNYAL ÜRETİMİ ---
async def generate_signal(symbol: str, timeframe: str, current_price: float):
    try:
        if timeframe == "realtime":
            ticker_data = state.rt_ticker.tickers.get(symbol) if state.rt_ticker else None
            if not ticker_data or len(ticker_data["trades"]) < 5:
                return None
            prices = [t["price"] for t in list(ticker_data["trades"])[-5:]]
            vols = [t["qty"] for t in list(ticker_data["trades"])[-10:]]
        else:
            ohlcv = await fetch_ohlcv(symbol, timeframe, 15)
            if len(ohlcv) < 5:
                return None
            prices = [c[4] for c in ohlcv[-5:]]  # close
            vols = [c[5] for c in ohlcv[-10:]]    # volume

        if len(prices) < 2:
            return None

        up_moves = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i-1])
        down_moves = len(prices) - 1 - up_moves

        avg_vol = sum(vols) / len(vols) if vols else 1
        last_vol = vols[-1] if vols else 0
        volume_spike = last_vol > avg_vol * 1.5

        if up_moves >= 4 and volume_spike:
            signal_text = "💥 GÜÇLÜ ALIM!"
        elif up_moves >= 3:
            signal_text = "📈 YUKARI MOMENTUM"
        elif down_moves >= 4 and volume_spike:
            signal_text = "🔥 GÜÇLÜ SATIM!"
        elif down_moves >= 3:
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
    except Exception as e:
        logger.debug(f"Sinyal üretimi hatası {symbol} {timeframe}: {e}")
        return None


# --- MERKEZİ TARAYICI (ASYNC) ---
async def central_scanner():
    timeframes = ["3m", "5m", "15m", "30m", "1h"]  # realtime ayrı yönetiliyor

    while True:
        try:
            for tf in timeframes:
                strong_signals = []
                symbols_to_check = state.all_usdt_symbols[:30]  # ilk 30 coin

                for symbol in symbols_to_check:
                    try:
                        # 🚀 Fiyat alımı artık async!
                        price = None
                        if state.rt_ticker and symbol in state.rt_ticker.tickers:
                            price = state.rt_ticker.tickers[symbol]["price"]
                        if not price:
                            ticker = await state.exchange.fetch_ticker(symbol)
                            price = ticker.get("last") or ticker.get("close")
                            if not price:
                                continue

                        # Sinyal üret
                        sig = await generate_signal(symbol, tf, price)
                        if sig:
                            state.shared_signals[tf][symbol] = sig
                            strong_signals.append(sig)
                        else:
                            state.shared_signals[tf].pop(symbol, None)

                    except Exception as e:
                        logger.debug(f"Scanner hata — {symbol} {tf}: {e}")
                        continue

                # Güçlü sinyalleri sırala
                state.active_strong_signals[tf] = sorted(
                    strong_signals,
                    key=lambda x: (
                        "GÜÇLÜ" in x["signal"],  # Önce güçlü sinyaller
                        "ALIM" in x["signal"],   # Sonra alım önceliği
                    ),
                    reverse=True
                )[:15]  # max 15

                # Abonelere yayınla
                disconnected = set()
                for ws in state.all_subscribers[tf]:
                    try:
                        await ws.send_json(state.active_strong_signals[tf][:10])
                    except:
                        disconnected.add(ws)
                for ws in disconnected:
                    state.all_subscribers[tf].discard(ws)

                # Single coin aboneleri
                for symbol, sig in list(state.shared_signals[tf].items()):
                    channel = f"{symbol}:{tf}"
                    disconnected = set()
                    for ws in state.single_subscribers[channel]:
                        try:
                            await ws.send_json(sig)
                        except:
                            disconnected.add(ws)
                    for ws in disconnected:
                        state.single_subscribers[channel].discard(ws)

            await asyncio.sleep(10)

        except Exception as e:
            logger.error(f"Central scanner kritik hata: {e}")
            await asyncio.sleep(5)


# --- CONNECTION MANAGER ---
class ConnectionManager:
    def disconnect_ws(self, websocket: WebSocket, channel: str = None):
        if channel and channel in state.single_subscribers:
            state.single_subscribers[channel].discard(websocket)
        for tf in state.all_subscribers:
            state.all_subscribers[tf].discard(websocket)
        state.pump_radar_subscribers.discard(websocket)


manager = ConnectionManager()


# --- WEBSOCKET ENDPOINTS ---
@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_single(websocket: WebSocket, pair: str, timeframe: str):
    # Symbol normalize
    symbol = pair.upper().replace("/", "").replace("-", "").replace(" ", "")
    if not symbol.endswith("USDT"):
        await websocket.accept()
        await websocket.send_json({"error": "Sadece USDT çiftleri (örn: BTCUSDT) desteklenir"})
        await websocket.close(code=1008)
        return

    await websocket.accept()
    channel = f"{symbol}:{timeframe}"
    state.single_subscribers[channel].add(websocket)

    # İlk sinyal varsa gönder
    sig = state.shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        try:
            await websocket.send_json(sig)
        except:
            pass

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_ws(websocket, channel)
    except Exception:
        manager.disconnect_ws(websocket, channel)


@app.websocket("/ws/all/{timeframe}")
async def ws_all(websocket: WebSocket, timeframe: str):
    if timeframe not in state.shared_signals:
        await websocket.accept()
        await websocket.send_json({"error": "Geçersiz timeframe"})
        await websocket.close(code=1003)
        return

    await websocket.accept()
    state.all_subscribers[timeframe].add(websocket)

    try:
        await websocket.send_json(state.active_strong_signals.get(timeframe, [])[:10])
    except:
        pass

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_ws(websocket)
    except Exception:
        manager.disconnect_ws(websocket)


@app.websocket("/ws/pump_radar")
async def ws_pump_radar(websocket: WebSocket):
    await websocket.accept()
    state.pump_radar_subscribers.add(websocket)

    try:
        await websocket.send_json({
            "top_gainers": state.top_gainers,
            "last_update": state.last_update
        })
    except:
        pass

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_ws(websocket)
    except Exception:
        manager.disconnect_ws(websocket)


# --- INIT & CLEANUP ---
async def initialize_app():
    try:
        await state.exchange.load_markets()
        await load_all_symbols()
        await fetch_pump_radar()

        # Realtime ticker
        state.rt_ticker = RealTimeTicker()
        state.tasks.append(asyncio.create_task(state.rt_ticker.start()))

        # Scanner
        state.tasks.append(asyncio.create_task(central_scanner()))

        # Pump radar updater
        async def radar_updater():
            while True:
                await asyncio.sleep(45)
                await fetch_pump_radar()
        state.tasks.append(asyncio.create_task(radar_updater()))

        logger.info("✅ ICT SMART PRO — Başarıyla başlatıldı!")

    except Exception as e:
        logger.critical(f"❌ Başlatma başarısız: {e}")
        raise


async def cleanup():
    if state.rt_ticker:
        await state.rt_ticker.stop()
    for task in state.tasks:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # WS temizliği
    for subs in [state.single_subscribers, state.all_subscribers]:
        for ws_set in subs.values():
            for ws in list(ws_set):
                try:
                    await ws.close()
                except:
                    pass
            ws_set.clear()
    for ws in list(state.pump_radar_subscribers):
        try:
            await ws.close()
        except:
            pass
    state.pump_radar_subscribers.clear()

    # Exchange kapat
    await state.exchange.close()


# --- EXCEPTION HANDLER ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception at {request.url}: {exc}")
    return HTMLResponse(
        content="""<h1 style='color:#ff4444;text-align:center;padding:100px;background:#000'>
                    Sunucu Hatası 😔</h1>
                    <p style='text-align:center;color:#fff'>
                    Lütfen birkaç dakika sonra tekrar deneyin.</p>""",
        status_code=500
    )


# --- PAGES ---
@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(content=HOME_HTML)


@app.get("/signal", response_class=HTMLResponse)
async def signal_page():
    return HTMLResponse(content,SIGNAL_HTML)


@app.get("/login")
async def login_redirect():
    return RedirectResponse("/", status_code=303)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "uptime": datetime.now().isoformat(),
        "symbols_loaded": len(state.all_usdt_symbols),
        "rt_ticker": bool(state.rt_ticker and state.rt_ticker.running),
        "active_ws": sum(len(s) for s in state.all_subscribers.values()) +
                     sum(len(s) for s in state.single_subscribers.values()) +
                     len(state.pump_radar_subscribers)
    }


# --- HTML TEMPLATES (INLINE) ---
HOME_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>ICT SMART PRO</title>
    <style>
        body{background:#0a0022;color:#fff;font-family:sans-serif;margin:0;min-height:100vh}
        .container{max-width:1200px;margin:auto;padding:20px}
        h1{font-size:3rem;text-align:center;color:#00dbde;margin:30px 0}
        .update{text-align:center;color:#00ffff;margin:20px;font-size:1.2rem}
        table{width:100%;border-collapse:collapse;margin:20px 0}
        th{background:#ffffff11;padding:15px}
        td{padding:12px;text-align:center}
        .green{color:#00ff88}
        .red{color:#ff4444}
        .btn{display:block;width:300px;margin:20px auto;padding:15px;
             background:#00dbde;color:#000;text-align:center;
             border-radius:25px;text-decoration:none;font-weight:bold}
    </style>
</head>
<body>
    <div class="container">
        <h1>ICT SMART PRO</h1>
        <div class="update" id="update">Yükleniyor...</div>
        <table>
            <thead><tr><th>SIRA</th><th>COİN</th><th>FİYAT</th><th>24S DEĞİŞİM</th></tr></thead>
            <tbody id="table-body">
                <tr><td colspan="4">Veriler yükleniyor...</td></tr>
            </tbody>
        </table>
        <a href="/signal" class="btn">🚀 Tek Coin Sinyal</a>
        <div style="text-align:center;margin-top:50px;font-size:0.9em;color:#aaa">
            © 2025 ICT SMART PRO — coderhektor
        </div>
    </div>
    <script>
        const ws = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') 
                                 + '://' + location.host + '/ws/pump_radar');
        ws.onmessage = (e) => {
            const data = JSON.parse(e.data);
            document.getElementById('update').innerHTML = 
                `Son Güncelleme: <strong>${data.last_update}</strong>`;
            const tbody = document.getElementById('table-body');
            if (!data.top_gainers || data.top_gainers.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4">Veri yok</td></tr>';
                return;
            }
            tbody.innerHTML = data.top_gainers.map((coin, i) => `
                <tr>
                    <td>#${i+1}</td>
                    <td><strong>${coin.symbol}</strong></td>
                    <td>$${coin.price.toFixed(coin.price < 1 ? 6 : 2)}</td>
                    <td class="${coin.change > 0 ? 'green' : 'red'}">
                        ${coin.change > 0 ? '+' : ''}${coin.change.toFixed(2)}%
                    </td>
                </tr>
            `).join('');
        };
        ws.onerror = () => {
            document.getElementById('update').innerHTML = 
                '<span style="color:#ff4444">❌ Bağlantı hatası</span>';
        };
    </script>
</body>
</html>
"""

SIGNAL_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Tek Coin Sinyal</title>
    <style>
        body{background:#0a0022;color:#fff;text-align:center;padding:20px;font-family:sans-serif}
        .card{max-width:500px;margin:50px auto;background:#fff1;padding:30px;border-radius:20px}
        input,select,button{width:100%;padding:15px;margin:10px 0;border-radius:10px;font-size:1rem}
        button{background:#00dbde;color:#000;font-weight:bold;border:none;cursor:pointer}
        button:hover{opacity:0.9}
        #result{margin-top:20px;padding:15px;border-radius:10px;background:#00000055}
        .signal{font-size:1.4rem;font-weight:bold}
    </style>
</head>
<body>
    <div class="card">
        <h2>🎯 Tek Coin Sinyal İzleyici</h2>
        <input id="pair" placeholder="BTCUSDT" value="BTCUSDT">
        <select id="tf">
            <option value="realtime">Realtime (Trade)</option>
            <option value="3m">3 Dakika</option>
            <option value="5m">5 Dakika</option>
            <option value="15m">15 Dakika</option>
        </select>
        <button onclick="connect()">Bağlan</button>
        <div id="result">Bağlantı bekleniyor...</div>
    </div>
    <script>
        let ws = null;
        function connect() {
            if(ws) ws.close();
            const pair = document.getElementById('pair').value.trim().toUpperCase();
            const tf = document.getElementById('tf').value;
            if(!pair || !pair.endsWith('USDT')) {
                alert('Lütfen geçerli bir USDT çifti girin (örn: BTCUSDT)');
                return;
            }
            const url = `ws://${location.host}/ws/signal/${pair}/${tf}`;
            ws = new WebSocket(url);
            const resultDiv = document.getElementById('result');
            resultDiv.innerHTML = '📶 Bağlanıyor...';
            ws.onopen = () => resultDiv.innerHTML = '✅ Bağlandı — sinyal bekleniyor...';
            ws.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if(data.error) {
                    resultDiv.innerHTML = `<span style="color:#ff4444">❌ ${data.error}</span>`;
                    return;
                }
                resultDiv.innerHTML = `
                    <div class="signal" style="color:${data.signal.includes('ALIM') ? '#00ff88' : '#ff4444'}">
                        ${data.signal}
                    </div>
                    <div><strong>${data.pair}</strong> — $${data.current_price}</div>
                    <div style="font-size:0.9em; color:#aaa">
                        ${data.timeframe} | ${data.last_update}
                    </div>
                `;
            };
            ws.onerror = () => resultDiv.innerHTML = '<span style="color:#ff4444">❌ Bağlantı hatası</span>';
            ws.onclose = () => resultDiv.innerHTML = '📴 Bağlantı kapandı';
        }
        // İlk bağlantı
        window.onload = () => connect();
    </script>
</body>
</html>
"""


# --- ENTRY POINT ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))  # ✅ Railway'de PORT dinamik
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,  # Railway'de reload=False önerilir
        timeout_keep_alive=30,
        limit_concurrency=100,
    )
