# ==============================
# ICT SMART PRO — DÜZELTİLMİŞ VERSİYON
# ==============================

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, Set

import ccxt
import httpx
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ictsmartpro")

# --- LIFESPAN MANAGEMENT ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize_app()
    yield
    # Shutdown
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()

app = FastAPI(lifespan=lifespan)

# Static dosyalar için geçici çözüm - Railway uyumlu
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except:
    logger.warning("Static dizini bulunamadı, devre dışı bırakıldı")

# --- GLOBALS ---
class GlobalState:
    def __init__(self):
        self.top_gainers = []
        self.last_update = "Başlatılıyor..."
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'timeout': 30000,
            'rateLimit': 1200
        })
        self.all_usdt_symbols = []
        self.shared_signals = {
            "realtime": {}, "3m": {}, "5m": {}, "15m": {}, "30m": {},
            "1h": {}, "4h": {}, "1d": {}, "1w": {}
        }
        self.active_strong_signals = defaultdict(list)
        self.single_subscribers = defaultdict(set)
        self.all_subscribers = defaultdict(set)
        self.pump_radar_subscribers = set()
        self.ohlcv_cache = {}
        self.rt_ticker = None
        self.tasks = []

state = GlobalState()

# --- REAL-TIME TRADE STREAM (Optimized) ---
class RealTimeTicker:
    def __init__(self):
        self.tickers = {}
        self.running = True
        
    async def start(self):
        # Sadece en popüler 10 coin'i izle
        symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
            "ADAUSDT", "DOGEUSDT", "SHIBUSDT", "AVAXUSDT", "TRXUSDT"
        ]
        
        while self.running:
            try:
                streams = "/".join([f"{s.lower()}@trade" for s in symbols])
                url = f"wss://stream.binance.com:9443/stream?streams={streams}"
                
                async with websockets.connect(url, ping_interval=30, ping_timeout=10) as ws:
                    logger.info("✅ Binance trade stream aktif")
                    async for message in ws:
                        if not self.running:
                            break
                        try:
                            data = json.loads(message)["data"]
                            if data["e"] != "trade":
                                continue
                                
                            symbol = data["s"]
                            price = float(data["p"])
                            
                            if symbol not in self.tickers:
                                self.tickers[symbol] = {
                                    "price": price,
                                    "trades": deque(maxlen=50)
                                }
                            self.tickers[symbol]["price"] = price
                            self.tickers[symbol]["trades"].append({
                                "time": data["T"],
                                "price": price,
                                "qty": float(data["q"])
                            })
                        except Exception as e:
                            logger.debug(f"Trade parse error: {e}")
                            continue
            except Exception as e:
                logger.warning(f"Trade stream koptu: {e}")
                if self.running:
                    await asyncio.sleep(5)
                    
    async def stop(self):
        self.running = False

# --- PUMP RADAR (Optimized) ---
async def fetch_pump_radar():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get("https://api.binance.com/api/v3/ticker/24hr")
            data = r.json()
        
        clean = []
        for item in data:
            if not item["symbol"].endswith("USDT"):
                continue
            try:
                price = float(item["lastPrice"])
                change = float(item["priceChangePercent"])
                volume = float(item["quoteVolume"])
                if volume >= 100_000 and change != 0:
                    clean.append({
                        "symbol": item["symbol"][:-4] + "/USDT",
                        "price": price,
                        "change": change,
                        "volume": volume
                    })
            except:
                continue
        
        state.top_gainers = sorted(clean, key=lambda x: abs(x["change"]), reverse=True)[:10]
        state.last_update = datetime.now().strftime("%H:%M:%S")
        
        # Sadece aktif bağlantılara gönder
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

# --- SEMBOL YÜKLE (Optimized) ---
async def load_all_symbols():
    try:
        # Sadece ilk 100 popüler sembol
        tickers = state.exchange.fetch_tickers()
        state.all_usdt_symbols = [
            s.replace("/", "") for s in tickers.keys()
            if s.endswith("/USDT") and tickers[s]["quoteVolume"] > 500_000
        ][:100]  # Limit to 100 symbols
        
        logger.info(f"{len(state.all_usdt_symbols)} USDT çifti yüklendi")
    except Exception as e:
        logger.warning(f"Sembol yükleme hatası: {e}")
        state.all_usdt_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

# --- OHLCV CACHE (Optimized) ---
async def fetch_ohlcv(symbol: str, timeframe: str, limit=30):
    key = f"{symbol}_{timeframe}"
    now = time.time()
    
    if key in state.ohlcv_cache and now - state.ohlcv_cache[key]["ts"] < 30:
        return state.ohlcv_cache[key]["data"]
    
    try:
        ohlcv = state.exchange.fetch_ohlcv(
            symbol[:-4] + "/USDT", 
            timeframe=timeframe, 
            limit=min(limit, 30)
        )
        state.ohlcv_cache[key] = {"data": ohlcv, "ts": now}
        return ohlcv
    except Exception as e:
        logger.debug(f"OHLCV hatası {symbol} {timeframe}: {e}")
        return []

# --- SİNYAL ÜRETİM (Optimized) ---
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
            prices = [c[4] for c in ohlcv[-5:]]
            vols = [c[5] for c in ohlcv[-10:]]
        
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
        logger.debug(f"Signal generation error {symbol}: {e}")
        return None

# --- MERKEZİ TARAYICI (Optimized) ---
async def central_scanner():
    timeframes = ["3m", "5m", "15m", "30m", "1h"]
    
    while True:
        try:
            for tf in timeframes:
                strong_signals = []
                symbols_to_check = state.all_usdt_symbols[:30]  # Sadece ilk 30
                
                for symbol in symbols_to_check:
                    try:
                        # Fiyat al
                        price = None
                        if state.rt_ticker:
                            ticker_data = state.rt_ticker.tickers.get(symbol)
                            if ticker_data:
                                price = ticker_data["price"]
                        
                        if not price:
                            ticker = state.exchange.fetch_ticker(symbol)
                            price = ticker["last"]
                        
                        # Sinyal üret
                        sig = await generate_signal(symbol, tf, price)
                        if sig:
                            state.shared_signals[tf][symbol] = sig
                            strong_signals.append(sig)
                        else:
                            state.shared_signals[tf].pop(symbol, None)
                            
                    except Exception as e:
                        logger.debug(f"Scanner error {symbol}: {e}")
                        continue
                
                # Sırala ve sınırla
                state.active_strong_signals[tf] = sorted(
                    strong_signals,
                    key=lambda x: ("GÜÇLÜ" in x["signal"], "ALIM" in x["signal"]),
                    reverse=True
                )[:15]
                
                # Abonelere gönder
                disconnected = set()
                for ws in state.all_subscribers[tf]:
                    try:
                        await ws.send_json(state.active_strong_signals[tf][:10])
                    except:
                        disconnected.add(ws)
                
                for ws in disconnected:
                    state.all_subscribers[tf].discard(ws)
                
                # Single subscribers
                for symbol, sig in state.shared_signals[tf].items():
                    channel = f"{symbol}:{tf}"
                    disconnected = set()
                    for ws in state.single_subscribers[channel]:
                        try:
                            await ws.send_json(sig)
                        except:
                            disconnected.add(ws)
                    
                    for ws in disconnected:
                        state.single_subscribers[channel].discard(ws)
            
            await asyncio.sleep(10)  # 10 saniyede bir tarama
            
        except Exception as e:
            logger.error(f"Scanner error: {e}")
            await asyncio.sleep(5)

# --- WEBSOCKET CONNECTION MANAGER ---
class ConnectionManager:
    async def connect(self, websocket: WebSocket, channel: str = None):
        await websocket.accept()
        return websocket
    
    def disconnect(self, websocket: WebSocket, channel: str = None):
        if channel and channel in state.single_subscribers:
            state.single_subscribers[channel].discard(websocket)
        
        # Tüm subscriber listelerinden kaldır
        for tf in state.all_subscribers:
            state.all_subscribers[tf].discard(websocket)
        
        state.pump_radar_subscribers.discard(websocket)

manager = ConnectionManager()

# --- WEBSOCKET ENDPOINTS ---
@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_single(websocket: WebSocket, pair: str, timeframe: str):
    symbol = pair.upper().replace("/", "").replace("-", "").replace(" ", "")
    if not symbol.endswith("USDT"):
        try:
            await websocket.accept()
            await websocket.send_json({"error": "Sadece USDT çiftleri desteklenir"})
            await websocket.close()
        except:
            pass
        return
    
    await manager.connect(websocket)
    channel = f"{symbol}:{timeframe}"
    state.single_subscribers[channel].add(websocket)
    
    # İlk sinyali gönder
    sig = state.shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        try:
            await websocket.send_json(sig)
        except:
            pass
    
    try:
        while True:
            # Sadece bağlantıyı açık tut
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel)
    except Exception:
        manager.disconnect(websocket, channel)

@app.websocket("/ws/all/{timeframe}")
async def ws_all(websocket: WebSocket, timeframe: str):
    await manager.connect(websocket)
    state.all_subscribers[timeframe].add(websocket)
    
    # İlk veriyi gönder
    try:
        await websocket.send_json(state.active_strong_signals.get(timeframe, [])[:10])
    except:
        pass
    
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

@app.websocket("/ws/pump_radar")
async def ws_pump_radar(websocket: WebSocket):
    await manager.connect(websocket)
    state.pump_radar_subscribers.add(websocket)
    
    # İlk veriyi gönder
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
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

# --- INITIALIZATION ---
async def initialize_app():
    """Uygulamayı başlat"""
    try:
        # Önce exchange'i yükle
        state.exchange.load_markets()
        
        # Sembolleri yükle
        await load_all_symbols()
        
        # Pump radar başlangıç verisi
        await fetch_pump_radar()
        
        # Real-time ticker başlat
        state.rt_ticker = RealTimeTicker()
        ticker_task = asyncio.create_task(state.rt_ticker.start())
        state.tasks.append(ticker_task)
        
        # Scanner başlat
        scanner_task = asyncio.create_task(central_scanner())
        state.tasks.append(scanner_task)
        
        # Pump radar güncelleme
        async def radar_updater():
            while True:
                await asyncio.sleep(45)
                await fetch_pump_radar()
        
        radar_task = asyncio.create_task(radar_updater())
        state.tasks.append(radar_task)
        
        logger.info("✅ ICT SMART PRO — Başarıyla başlatıldı!")
        
    except Exception as e:
        logger.error(f"❌ Başlatma hatası: {e}")
        raise

async def cleanup():
    """Uygulamayı temizle"""
    if state.rt_ticker:
        await state.rt_ticker.stop()
    
    for task in state.tasks:
        task.cancel()
    
    # Tüm WebSocket bağlantılarını kapat
    for channel in list(state.single_subscribers.keys()):
        for ws in state.single_subscribers[channel]:
            try:
                await ws.close()
            except:
                pass
        state.single_subscribers[channel].clear()
    
    for tf in state.all_subscribers:
        for ws in state.all_subscribers[tf]:
            try:
                await ws.close()
            except:
                pass
        state.all_subscribers[tf].clear()
    
    for ws in state.pump_radar_subscribers:
        try:
            await ws.close()
        except:
            pass
    state.pump_radar_subscribers.clear()

# --- GLOBAL EXCEPTION HANDLER ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=False)
    return HTMLResponse(
        content="""<h1 style='color:#ff4444;text-align:center;padding:100px;background:#000'>
                    Sunucu Hatası 😔</h1>
                    <p style='text-align:center;color:#fff'>
                    Lütfen birkaç dakika sonra tekrar deneyin.</p>""",
        status_code=500
    )

# --- ANA SAYFA (Optimized) ---
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # Ana sayfa HTML'i - Railway için optimize edilmiş
    html_content = """
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
            <a href="/signal/all" class="btn">🔥 Tüm Coinler</a>
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
                        <td>$${coin.price.toFixed(coin.price < 1 ? 6 : 4)}</td>
                        <td class="${coin.change > 0 ? 'green' : 'red'}">
                            ${coin.change > 0 ? '+' : ''}${coin.change.toFixed(2)}%
                        </td>
                    </tr>
                `).join('');
            };
            ws.onerror = () => {
                document.getElementById('update').innerHTML = 
                    '<span style="color:#ff4444">Bağlantı hatası</span>';
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# --- GİRİŞ SAYFASI ---
@app.get("/login")
async def login_page():
    return RedirectResponse("/")

# --- TEK COİN SAYFASI ---
@app.get("/signal")
async def signal_page():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Tek Coin Sinyal</title>
        <style>
            body{background:#0a0022;color:#fff;text-align:center;padding:20px}
            .card{max-width:500px;margin:50px auto;background:#fff1;padding:30px;border-radius:20px}
            input,select,button{width:100%;padding:15px;margin:10px 0;border-radius:10px}
            button{background:#00dbde;color:#000;font-weight:bold}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>Tek Coin Sinyal</h2>
            <input id="pair" placeholder="BTCUSDT" value="BTCUSDT">
            <select id="tf">
                <option value="realtime">Realtime</option>
                <option value="3m">3m</option>
                <option value="5m">5m</option>
            </select>
            <button onclick="connect()">Bağlan</button>
            <div id="result"></div>
        </div>
        <script>
            let ws = null;
            function connect() {
                if(ws) ws.close();
                const pair = document.getElementById('pair').value.toUpperCase();
                const tf = document.getElementById('tf').value;
                ws = new WebSocket(`ws://${location.host}/ws/signal/${pair}/${tf}`);
                ws.onmessage = (e) => {
                    const data = JSON.parse(e.data);
                    document.getElementById('result').innerHTML = 
                        `<h3>${data.signal}</h3><p>${data.pair} - $${data.current_price}</p>`;
                };
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# Railway için gerekli: root path'i dinle
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        timeout_keep_alive=30,
        limit_concurrency=100
    )
