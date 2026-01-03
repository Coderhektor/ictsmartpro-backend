import base64
import logging
import io
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Dict, List, Any
import json

import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response, UploadFile, File, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
import os
import hashlib

# Core modülleri
try:
    from core import (
        initialize, cleanup, single_subscribers, all_subscribers,
        pump_radar_subscribers,
        shared_signals, active_strong_signals, top_gainers, top_losers, last_update, rt_ticker,
        get_binance_client, get_bybit_client, get_okex_client,
        price_sources_status, price_pool,
        get_all_prices_snapshot, get_available_timeframes, get_strong_signals_for_timeframe
    )
except ImportError:
    print("⚠️ Core modülü bulunamadı, dummy değerler kullanılıyor...")

    # Dummy değerler
    single_subscribers = {}
    all_subscribers = {}
    pump_radar_subscribers = set()
    shared_signals = {}
    active_strong_signals = {}
    top_gainers = []
    top_losers = []
    last_update = "00:00"
    price_sources_status = {}
    price_pool = {}

    class DummyRTicker:
        def __init__(self):
            self.subscribers = set()

        async def subscribe(self, websocket):
            self.subscribers.add(websocket)

        async def unsubscribe(self, websocket):
            self.subscribers.discard(websocket)

    rt_ticker = DummyRTicker()

    def get_all_prices_snapshot(limit=50):
        return {"prices": [], "timestamp": datetime.now().isoformat()}

    async def initialize():
        print("Dummy initialize çalıştı")

    async def cleanup():
        print("Dummy cleanup çalıştı")

    def get_binance_client():
        return None

    def get_bybit_client():
        return None

    def get_okex_client():
        return None

    def get_available_timeframes():
        return ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

    def get_strong_signals_for_timeframe(tf):
        return []

from utils import all_usdt_symbols

from openai import OpenAI
import ccxt.async_support as ccxt_async
from pycoingecko import CoinGeckoAPI

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("main")

# OpenAI client - opsiyonel
openai_client = None
if os.getenv("OPENAI_API_KEY"):
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
else:
    logger.warning("OPENAI_API_KEY bulunamadı, AI özellikleri devre dışı")

# CoinGecko API client
cg_client = CoinGeckoAPI()

# ==================== ZİYARETÇİ SAYACI ====================
class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users = set()
        self.daily_stats = {}
        self.page_views = {}
        self.lock = asyncio.Lock()

    async def add_visit(self, page: str, user_id: str = None) -> int:
        async with self.lock:
            self.total_visits += 1
            self.page_views[page] = self.page_views.get(page, 0) + 1
            today = datetime.now().strftime("%Y-%m-%d")
            if today not in self.daily_stats:
                self.daily_stats[today] = {"visits": 0, "unique": set()}
            self.daily_stats[today]["visits"] += 1
            if user_id:
                self.active_users.add(user_id)
                self.daily_stats[today]["unique"].add(user_id)
            return self.total_visits

    def get_stats(self) -> Dict:
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = self.daily_stats.get(today, {"visits": 0, "unique": set()})
        return {
            "total_visits": self.total_visits,
            "active_users": len(self.active_users),
            "today_visits": today_stats["visits"],
            "today_unique": len(today_stats.get("unique", set())),
            "page_views": self.page_views,
            "last_updated": datetime.now().strftime("%H:%M:%S")
        }

visitor_counter = VisitorCounter()

def get_visitor_stats_html() -> str:
    stats = visitor_counter.get_stats()
    return f"""
    <div style="position:fixed;top:15px;right:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:clamp(0.8rem, 2vw, 1.2rem);z-index:1000;backdrop-filter:blur(10px);border:1px solid #00ff8855;">
        <div>👁️ Toplam: <strong>{stats['total_visits']}</strong></div>
        <div>🔥 Bugün: <strong>{stats['today_visits']}</strong></div>
        <div>👥 Aktif: <strong>{stats['active_users']}</strong></div>
    </div>
    """

# ==================== LIFESPAN ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 ICT SMART PRO başlatılıyor...")
    try:
        await initialize()
        logger.info("✅ ICT SMART PRO başarıyla başlatıldı")
    except Exception as e:
        logger.error(f"❌ Başlatma hatası: {e}")
    yield
    logger.info("🛑 ICT SMART PRO kapatılıyor...")
    try:
        await cleanup()
        logger.info("✅ ICT SMART PRO temiz bir şekilde kapatıldı")
    except Exception as e:
        logger.error(f"❌ Kapatma hatası: {e}")

app = FastAPI(
    lifespan=lifespan,
    title="ICT SMART PRO",
    version="3.0 - PROD READY",
    description="Akıllı Kripto Sinyal ve Analiz Platformu",
    docs_url="/docs" if os.getenv("ENABLE_DOCS", "false").lower() == "true" else None,
    redoc_url="/redoc" if os.getenv("ENABLE_DOCS", "false").lower() == "true" else None
)

# Static dosyalar
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    logger.warning("Static dosya dizini bulunamadı")

# Templates
try:
    templates = Jinja2Templates(directory="templates")
except Exception:
    logger.warning("Templates dizini bulunamadı, HTML inline olarak render edilecek")

# ==================== WEBSOCKET MANAGER ====================
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, channel: str):
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = []
        self.active_connections[channel].append(websocket)
        logger.debug(f"WebSocket bağlandı: {channel}")

    async def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self.active_connections:
            if websocket in self.active_connections[channel]:
                self.active_connections[channel].remove(websocket)
            if not self.active_connections[channel]:
                del self.active_connections[channel]
        logger.debug(f"WebSocket ayrıldı: {channel}")

    async def broadcast(self, channel: str, message: Dict):
        if channel in self.active_connections:
            disconnected = []
            for connection in self.active_connections[channel]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"WebSocket gönderme hatası: {e}")
                    disconnected.append(connection)
            for connection in disconnected:
                await self.disconnect(connection, channel)

ws_manager = ConnectionManager()

# ==================== PRICE SOURCES WEBSOCKET ====================
price_sources_subscribers = set()

@app.websocket("/ws/price_sources")
async def ws_price_sources(websocket: WebSocket):
    await websocket.accept()
    price_sources_subscribers.add(websocket)

    try:
        await websocket.send_json({
            "sources": price_sources_status,
            "total_symbols": len(price_pool),
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Price sources WS ilk veri gönderme hatası: {e}")
        return

    try:
        while True:
            await asyncio.sleep(10)
            try:
                await websocket.send_json({
                    "sources": price_sources_status,
                    "total_symbols": len(price_pool),
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.warning(f"Price sources WS gönderme hatası: {e}")
                break
    except WebSocketDisconnect:
        logger.info("Price sources WebSocket bağlantısı kesildi")
    except Exception as e:
        logger.error(f"Price sources WS hatası: {e}")
    finally:
        price_sources_subscribers.discard(websocket)

# ==================== MIDDLEWARE ====================
@app.middleware("http")
async def count_visitors(request: Request, call_next):
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        ip = request.client.host if request.client else "anonymous"
        user_agent = request.headers.get("user-agent", "")
        visitor_string = f"{ip}{user_agent}"
        visitor_id = hashlib.sha256(visitor_string.encode()).hexdigest()[:12]

    page = request.url.path
    await visitor_counter.add_visit(page, visitor_id)

    response = await call_next(request)

    if not request.cookies.get("visitor_id"):
        response.set_cookie(
            key="visitor_id",
            value=visitor_id,
            max_age=86400 * 30,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https"
        )

    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    return response

# ==================== WEBSOCKET ENDPOINTS ====================
# (WebSocket endpoint'leri aynı kaldı, hata yoktu)
@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_signal(websocket: WebSocket, pair: str, timeframe: str):
    supported_tfs = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
    if timeframe not in supported_tfs:
        await websocket.close(code=1008, reason=f"Desteklenmeyen timeframe: {timeframe}")
        return

    symbol = pair.upper().replace("/", "").replace("-", "").strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    channel = f"{symbol}:{timeframe}"

    if channel not in single_subscribers:
        single_subscribers[channel] = set()

    await websocket.accept()
    single_subscribers[channel].add(websocket)

    try:
        sig = shared_signals.get(timeframe, {}).get(symbol)
        if sig:
            await websocket.send_json(sig)
        else:
            await websocket.send_json({
                "status": "no_signal",
                "pair": symbol,
                "timeframe": timeframe,
                "message": "Henüz sinyal oluşmadı"
            })
    except Exception as e:
        logger.error(f"İlk sinyal gönderme hatası: {e}")

    try:
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json({
                    "heartbeat": True,
                    "timestamp": datetime.now().isoformat()
                })
            except:
                break
    except WebSocketDisconnect:
        logger.info(f"Signal WebSocket bağlantısı kesildi: {channel}")
    except Exception as e:
        logger.error(f"Signal WS hatası: {e}")
    finally:
        if channel in single_subscribers:
            single_subscribers[channel].discard(websocket)

@app.websocket("/ws/all/{timeframe}")
async def ws_all(websocket: WebSocket, timeframe: str):
    supported = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
    if timeframe not in supported:
        await websocket.close(code=1008, reason=f"Desteklenmeyen timeframe: {timeframe}")
        return

    await websocket.accept()

    if timeframe not in all_subscribers:
        all_subscribers[timeframe] = set()

    all_subscribers[timeframe].add(websocket)

    try:
        signals = active_strong_signals.get(timeframe, [])
        await websocket.send_json({
            "signals": signals,
            "count": len(signals),
            "timeframe": timeframe
        })
    except Exception as e:
        logger.error(f"Tüm sinyaller gönderme hatası: {e}")

    try:
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json({
                    "ping": True,
                    "timestamp": datetime.now().isoformat()
                })
            except:
                break
    except WebSocketDisconnect:
        logger.info(f"All signals WebSocket bağlantısı kesildi: {timeframe}")
    except Exception as e:
        logger.error(f"All signals WS hatası: {e}")
    finally:
        if timeframe in all_subscribers:
            all_subscribers[timeframe].discard(websocket)

@app.websocket("/ws/pump_radar")
async def ws_pump(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)

    try:
        await websocket.send_json({
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "last_update": last_update,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Pump radar ilk veri gönderme hatası: {e}")

    try:
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json({
                    "top_gainers": top_gainers,
                    "top_losers": top_losers,
                    "last_update": last_update,
                    "timestamp": datetime.now().isoformat()
                })
            except:
                break
    except WebSocketDisconnect:
        logger.info("Pump radar WebSocket bağlantısı kesildi")
    except Exception as e:
        logger.error(f"Pump radar WS hatası: {e}")
    finally:
        pump_radar_subscribers.discard(websocket)

@app.websocket("/ws/realtime_price")
async def ws_realtime_price(websocket: WebSocket):
    await websocket.accept()

    try:
        if hasattr(rt_ticker, 'subscribe'):
            await rt_ticker.subscribe(websocket)
        else:
            rt_ticker.subscribers.add(websocket)
    except Exception as e:
        logger.error(f"RT Ticker aboneliği hatası: {e}")

    try:
        while True:
            data = get_all_prices_snapshot(limit=50)
            await websocket.send_json(data)
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        logger.info("Realtime price WebSocket bağlantısı kesildi")
    except Exception as e:
        logger.error(f"Realtime price WS hatası: {e}")
    finally:
        try:
            if hasattr(rt_ticker, 'unsubscribe'):
                await rt_ticker.unsubscribe(websocket)
            else:
                rt_ticker.subscribers.discard(websocket)
        except:
            pass

# ==================== COINGECKO HELPER ====================
async def fetch_coingecko_ohlcv(symbol: str, timeframe: str) -> List[List]:
    coin_id_map = {
        "BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "BNBUSDT": "binancecoin",
        "SOLUSDT": "solana", "XRPUSDT": "ripple", "ADAUSDT": "cardano",
        "DOGEUSDT": "dogecoin", "TRXUSDT": "tron", "AVAXUSDT": "avalanche-2",
        "LINKUSDT": "chainlink", "TONUSDT": "the-open-network", "SHIBUSDT": "shiba-inu",
        "DOTUSDT": "polkadot", "MATICUSDT": "matic-network", "UNIUSDT": "uniswap",
        "LTCUSDT": "litecoin", "ATOMUSDT": "cosmos", "ETCUSDT": "ethereum-classic"
    }

    base = symbol.replace("USDT", "").lower()
    coin_id = coin_id_map.get(symbol, base)

    days_map = {
        "1m": 1, "3m": 1, "5m": 1, "15m": 1, "30m": 1,
        "1h": 7, "4h": 14, "1d": 30, "1w": 90
    }
    days = days_map.get(timeframe, 30)

    try:
        data = cg_client.get_coin_market_chart_by_id(
            id=coin_id,
            vs_currency='usd',
            days=days
        )

        prices = data.get('prices', [])
        volumes = data.get('total_volumes', [])

        if not prices or len(prices) < 20:
            logger.warning(f"CoinGecko: Yetersiz veri - {symbol}")
            return []

        ohlcv = []
        for i in range(len(prices)):
            ts = int(prices[i][0] / 1000)
            price = prices[i][1]

            if i == 0:
                o = h = l = c = price
            else:
                prev_price = prices[i-1][1]
                o = prev_price
                h = max(prev_price, price)
                l = min(prev_price, price)
                c = price

            volume = volumes[i][1] if i < len(volumes) else 0
            ohlcv.append([ts, o, h, l, c, volume])

        return ohlcv[-150:] if len(ohlcv) > 150 else ohlcv

    except Exception as e:
        if "id not found" in str(e).lower():
            logger.warning(f"CoinGecko: Coin ID bulunamadı → {coin_id}")
        else:
            logger.warning(f"CoinGecko OHLCV hatası ({symbol}): {e}")
        return []

# ==================== INDICATORS IMPORT ====================
try:
    from indicators import generate_ict_signal, generate_simple_signal
    logger.info("✅ Indicators modülü başarıyla yüklendi")
except ImportError as e:
    logger.error(f"❌ Indicators modülü yüklenemedi: {e}")

    def generate_ict_signal(df, symbol, timeframe):
        return {
            "pair": symbol,
            "timeframe": timeframe,
            "current_price": float(df['close'].iloc[-1]),
            "signal": "⏸️ ANALİZ BEKLENİYOR",
            "score": 50,
            "killzone": "Normal",
            "triggers": "Indicators modülü yüklenemedi",
            "last_update": datetime.utcnow().strftime("%H:%M UTC"),
            "strength": "ORTA"
        }

    def generate_simple_signal(df, symbol, timeframe):
        price = float(df['close'].iloc[-1])
        prev_price = float(df['close'].iloc[-2])
        change = ((price - prev_price) / prev_price) * 100

        if change > 1:
            signal = "🚀 AL"
            score = 70
        elif change < -1:
            signal = "🔻 SAT"
            score = 30
        else:
            signal = "⏸️ BEKLE"
            score = 50

        return {
            "pair": symbol,
            "timeframe": timeframe,
            "current_price": price,
            "signal": signal,
            "score": score,
            "killzone": "Normal",
            "triggers": f"Basit fiyat değişimi: {change:.2f}%",
            "last_update": datetime.utcnow().strftime("%H:%M UTC"),
            "strength": "GÜÇLÜ" if abs(change) > 2 else "ZAYIF"
        }

# ==================== ANA SAYFA ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    visitor_stats_html = get_visitor_stats_html()

    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>ICT SMART PRO - Akıllı Kripto Sinyal Platformu</title>
    <style>
        :root {{
            --primary-gradient: linear-gradient(135deg, #0a0022, #1a0033, #000);
            --accent-gradient: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde);
            --green: #00ff88;
            --red: #ff4444;
            --blue: #00dbde;
            --purple: #fc00ff;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--primary-gradient);
            color: #fff;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            min-height: 100vh;
            margin: 0;
            display: flex;
            flex-direction: column;
            overflow-x: hidden;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; flex: 1; width: 100%; }}
        h1 {{
            font-size: clamp(2rem, 5vw, 4.5rem);
            text-align: center;
            background: var(--accent-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-size: 200% auto;
            animation: gradient 8s ease infinite;
            margin: 20px 0;
            font-weight: 800;
            letter-spacing: 1px;
        }}
        @keyframes gradient {{ 0% {{ background-position: 0% center; }} 50% {{ background-position: 100% center; }} 100% {{ background-position: 0% center; }} }}
        .subtitle {{ text-align: center; color: var(--blue); font-size: clamp(1rem, 2vw, 1.4rem); margin-bottom: 40px; opacity: 0.9; }}
        .update {{ text-align: center; color: var(--blue); margin: 30px auto; font-size: clamp(1rem, 2vw, 1.5rem); background: rgba(0, 219, 222, 0.1); padding: 15px 30px; border-radius: 15px; border: 1px solid rgba(0, 219, 222, 0.3); max-width: 600px; }}
        .section-title {{ font-size: clamp(1.5rem, 3vw, 2.5rem); margin: 40px 0 20px; color: var(--blue); border-left: 5px solid var(--purple); padding-left: 20px; }}
        table {{ width: 100%; border-collapse: separate; border-spacing: 0 12px; margin: 30px 0; }}
        th {{ background: rgba(255, 255, 255, 0.08); padding: clamp(12px, 2vw, 20px); font-size: clamp(0.9rem, 2vw, 1.3rem); color: var(--blue); text-align: left; border-bottom: 2px solid rgba(0, 219, 222, 0.3); }}
        tr {{ background: rgba(255, 255, 255, 0.05); transition: all 0.3s ease; border-radius: 10px; overflow: hidden; }}
        tr:hover {{ transform: translateY(-5px); background: rgba(255, 255, 255, 0.1); box-shadow: 0 15px 40px rgba(0, 219, 222, 0.3); }}
        td {{ padding: clamp(12px, 2vw, 20px); font-size: clamp(0.9rem, 1.8vw, 1.1rem); }}
        .green {{ color: var(--green); text-shadow: 0 0 10px rgba(0, 255, 136, 0.5); font-weight: bold; }}
        .red {{ color: var(--red); text-shadow: 0 0 10px rgba(255, 68, 68, 0.5); font-weight: bold; }}
        .btn-container {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; margin: 50px 0; }}
        .btn {{
            display: inline-block;
            min-width: 250px;
            padding: clamp(15px, 3vw, 25px);
            font-size: clamp(1.1rem, 2.5vw, 1.8rem);
            background: var(--accent-gradient);
            color: #fff;
            text-align: center;
            border-radius: 15px;
            text-decoration: none;
            box-shadow: 0 0 40px rgba(252, 0, 255, 0.4);
            transition: all 0.3s ease;
            border: none;
            cursor: pointer;
            position: relative;
            overflow: hidden;
        }}
        .btn:hover {{ transform: scale(1.05); box-shadow: 0 0 80px rgba(252, 0, 255, 0.8); }}
        .btn::before {{ content: ''; position: absolute; top: 0; left: -100%; width: 100%; height: 100%; background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent); transition: 0.5s; }}
        .btn:hover::before {{ left: 100%; }}
        .footer {{ text-align: center; padding: 30px; color: #888; font-size: 0.9rem; margin-top: 50px; border-top: 1px solid rgba(255, 255, 255, 0.1); }}
        .loader {{ border: 4px solid rgba(255, 255, 255, 0.1); border-top: 4px solid var(--blue); border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }}
        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        @media (max-width: 768px) {{
            .container {{ padding: 10px; }}
            table {{ font-size: 0.8rem; }}
            th, td {{ padding: 8px; }}
            .btn-container {{ flex-direction: column; align-items: center; }}
            .btn {{ width: 90%; }}
        }}
    </style>
</head>
<body>
    <div style='position:fixed;top:15px;left:15px;background:rgba(0,0,0,0.8);padding:10px 20px;border-radius:20px;color:var(--green);font-size:clamp(0.8rem, 2vw, 1.2rem);z-index:1000;backdrop-filter:blur(10px);border:1px solid rgba(0,255,136,0.3);'>
        👤 Hoş geldin, <strong>{user}</strong>
    </div>
    {visitor_stats_html}
    <div class="container">
        <h1>ICT SMART PRO</h1>
        <div class="subtitle">Akıllı Kripto Sinyal ve Analiz Platformu</div>

        <div class="update" id="update">
            <div class="loader"></div>
            <div>Veri yükleniyor...</div>
        </div>

        <h2 class="section-title">🚀 Pump Coinler</h2>
        <table>
            <thead>
                <tr>
                    <th>SIRA</th>
                    <th>COİN</th>
                    <th>FİYAT</th>
                    <th>24S DEĞİŞİM</th>
                    <th>GRAFİK</th>
                </tr>
            </thead>
            <tbody id="gainers-table">
                <tr>
                    <td colspan="5" style="padding:60px;text-align:center;color:#888">
                        <div class="loader"></div>
                        <div>Pump radar yükleniyor...</div>
                    </td>
                </tr>
            </tbody>
        </table>

        <h2 class="section-title">🔻 Dump Coinler</h2>
        <table>
            <thead>
                <tr>
                    <th>SIRA</th>
                    <th>COİN</th>
                    <th>FİYAT</th>
                    <th>24S DEĞİŞİM</th>
                    <th>GRAFİK</th>
                </tr>
            </thead>
            <tbody id="losers-table">
                <tr>
                    <td colspan="5" style="padding:60px;text-align:center;color:#888">
                        <div class="loader"></div>
                        <div>Dump radar yükleniyor...</div>
                    </td>
                </tr>
            </tbody>
        </table>

        <div class="btn-container">
            <a href="/signal" class="btn">🚀 Tek Coin Canlı Sinyal + Grafik</a>
            <a href="/signal/all" class="btn">🔥 Tüm Coinleri Tara</a>
            <a href="/realtime" class="btn">📊 Canlı Fiyat Takibi</a>
            <a href="/admin" class="btn">⚙️ Admin Paneli</a>
        </div>

        <div style="display:flex;justify-content:center;gap:20px;flex-wrap:wrap;margin:40px 0;">
            <div style="background:rgba(0,255,136,0.1);padding:15px;border-radius:10px;min-width:200px;text-align:center;">
                <div style="font-size:2rem;color:var(--green);">⚡</div>
                <div>Gerçek Zamanlı</div>
                <div style="font-weight:bold;font-size:1.2rem;">Sinyaller</div>
            </div>
            <div style="background:rgba(0,219,222,0.1);padding:15px;border-radius:10px;min-width:200px;text-align:center;">
                <div style="font-size:2rem;color:var(--blue);">📈</div>
                <div>Multi Timeframe</div>
                <div style="font-weight:bold;font-size:1.2rem;">Analiz</div>
            </div>
            <div style="background:rgba(252,0,255,0.1);padding:15px;border-radius:10px;min-width:200px;text-align:center;">
                <div style="font-size:2rem;color:var(--purple);">🔔</div>
                <div>Pump/Dump</div>
                <div style="font-weight:bold;font-size:1.2rem;">Radar</div>
            </div>
        </div>
    </div>

    <div class="footer">
        © 2024 ICT SMART PRO | Tüm hakları saklıdır.<br>
        <small>Bu bir yatırım tavsiyesi değildir. Kripto para yatırımları yüksek risk içerir.</small>
    </div>

    <script>
        const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(wsProtocol + '://' + window.location.host + '/ws/pump_radar');

        ws.onopen = function() {{
            console.log('Pump radar WebSocket bağlantısı kuruldu');
        }};

        ws.onmessage = function(event) {{
            try {{
                const data = JSON.parse(event.data);
                document.getElementById('update').innerHTML = `📊 Son Güncelleme: <strong>${{data.last_update || 'Şimdi'}}</strong>`;

                const gTable = document.getElementById('gainers-table');
                if (!data.top_gainers || data.top_gainers.length === 0) {{
                    gTable.innerHTML = `<tr><td colspan="5" style="padding:60px;text-align:center;color:#ffd700;"><div style="font-size:3rem;">😴</div><div>Şu anda aktif pump yok</div></td></tr>`;
                }} else {{
                    gTable.innerHTML = data.top_gainers.map((coin, index) => {{
                        const changeClass = coin.change > 0 ? 'green' : 'red';
                        const sign = coin.change > 0 ? '+' : '';
                        return `
                            <tr>
                                <td>#${{index + 1}}</td>
                                <td><strong>${{coin.symbol || coin.coin}}</strong></td>
                                <td>$${{(coin.price || 0).toFixed(4)}}</td>
                                <td class="${{changeClass}}">${{sign}}${{(coin.change || 0).toFixed(2)}}%</td>
                                <td><a href="https://www.tradingview.com/chart/?symbol=BINANCE:${{coin.symbol || coin.coin}}" target="_blank" style="color:var(--blue);text-decoration:none;font-weight:bold;">📈 Grafik Aç</a></td>
                            </tr>
                        `;
                    }}).join('');
                }}

                const lTable = document.getElementById('losers-table');
                if (!data.top_losers || data.top_losers.length === 0) {{
                    lTable.innerHTML = `<tr><td colspan="5" style="padding:60px;text-align:center;color:#ffd700;"><div style="font-size:3rem;">😴</div><div>Şu anda aktif dump yok</div></td></tr>`;
                }} else {{
                    lTable.innerHTML = data.top_losers.map((coin, index) => {{
                        const changeClass = coin.change > 0 ? 'green' : 'red';
                        const sign = coin.change > 0 ? '+' : '';
                        return `
                            <tr>
                                <td>#${{index + 1}}</td>
                                <td><strong>${{coin.symbol || coin.coin}}</strong></td>
                                <td>$${{(coin.price || 0).toFixed(4)}}</td>
                                <td class="${{changeClass}}">${{sign}}${{(coin.change || 0).toFixed(2)}}%</td>
                                <td><a href="https://www.tradingview.com/chart/?symbol=BINANCE:${{coin.symbol || coin.coin}}" target="_blank" style="color:var(--blue);text-decoration:none;font-weight:bold;">📉 Grafik Aç</a></td>
                            </tr>
                        `;
                    }}).join('');
                }}
            }} catch (error) {{
                console.error('WebSocket veri işleme hatası:', error);
            }}
        }};

        ws.onerror = function(error) {{
            console.error('WebSocket hatası:', error);
            document.getElementById('update').innerHTML = '⚠️ Canlı veri bağlantısı kurulamadı. Sayfayı yenileyin.';
        }};

        ws.onclose = function() {{
            console.log('WebSocket bağlantısı kapandı');
        }};

        window.addEventListener('beforeunload', function() {{
            ws.close();
        }});
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

# Diğer endpoint'ler (analyze-chart, signal, all, realtime, admin vs.) tamamen aynı kalıyor,
# çünkü hata sadece ana sayfadaki JavaScript template literal'lerinden kaynaklanıyordu.

# Geri kalan tüm kod (analyze-chart, signal sayfaları, admin, health vs.) önceki mesajdaki gibi aynı.
# Sadece ana sayfa düzeltildi.

# ... (geri kalan tüm endpoint'ler önceki gibi aynı kalıyor, burada yer kaplamasın diye atlıyorum ama senin dosyana tamamen eklenmiş haliyle kullan)

if __name__ == "__main__":
    uvicorn_config = {
        "app": "main:app",
        "host": "0.0.0.0",
        "port": int(os.getenv("PORT", 8000)),
        "reload": os.getenv("ENVIRONMENT", "production") == "development",
        "workers": int(os.getenv("UVICORN_WORKERS", 4)),
        "log_level": "info",
        "access_log": True,
        "timeout_keep_alive": 30,
        "limit_concurrency": 1000,
        "limit_max_requests": 10000,
    }

    logger.info(f"🚀 ICT SMART PRO {uvicorn_config['port']} portunda başlatılıyor...")
    logger.info(f"🌍 Environment: {os.getenv('ENVIRONMENT', 'production')}")
    logger.info(f"👷 Workers: {uvicorn_config['workers']}")

    uvicorn.run(**uvicorn_config)
