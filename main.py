# main.py
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core import initialize, cleanup, single_subscribers, all_subscribers, pump_radar_subscribers
from core import shared_signals, active_strong_signals, top_gainers, last_update

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ictsmartpro")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize()
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()

app = FastAPI(lifespan=lifespan)

# WebSocket Handlers
@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_signal(websocket: WebSocket, pair: str, timeframe: str):
    await websocket.accept()
    symbol = pair.upper().replace("/", "").replace("-", "").replace(" ", "")
    if not symbol.endswith("USDT"):
        await websocket.send_json({"error": "Sadece USDT çiftleri desteklenir"})
        await websocket.close()
        return

    channel = f"{symbol}:{timeframe}"
    single_subscribers[channel].add(websocket)

    sig = shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        await websocket.send_json(sig)

    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        single_subscribers[channel].discard(websocket)

@app.websocket("/ws/all/{timeframe}")
async def ws_all(websocket: WebSocket, timeframe: str):
    if timeframe not in shared_signals:
        await websocket.accept()
        await websocket.send_json({"error": "Geçersiz timeframe"})
        await websocket.close()
        return
    await websocket.accept()
    all_subscribers[timeframe].add(websocket)
    await websocket.send_json(active_strong_signals.get(timeframe, []))
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        all_subscribers[timeframe].discard(websocket)

@app.websocket("/ws/pump_radar")
async def ws_pump(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    await websocket.send_json({"top_gainers": top_gainers, "last_update": last_update})
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pump_radar_subscribers.discard(websocket)

# HTML Pages (tamamen aynı kalıyor, sadece kısaltılmış olarak burada)
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    # ... (tam HTML kodu aynı kalıyor)

@app.post("/login")
async def login(request: Request):
    # ... aynı

@app.get("/signal", response_class=HTMLResponse)
async def signal(request: Request):
    # ... aynı HTML

@app.get("/signal/all", response_class=HTMLResponse)
async def signal_all(request: Request):
    # ... aynı HTML

@app.get("/abonelik", response_class=HTMLResponse)
async def abonelik():
    # ... aynı HTML

@app.get("/health")
async def health():
    from core import rt_ticker
    from utils import all_usdt_symbols
    return {
        "status": "healthy",
        "time": datetime.now().isoformat(),
        "symbols": len(all_usdt_symbols),
        "rt_coins": len(rt_ticker["tickers"]),
        "ws_total": len(single_subscribers) + len(all_subscribers) + len(pump_radar_subscribers)
    }

# Stripe kısmı (isteğe bağlı)
# import stripe
# stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
# @app.post("/api/checkout") ...
