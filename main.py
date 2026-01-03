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

    # İlk veriyi gönder
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
                    gTable.innerHTML = data.top_gainers.map((coin, index) => `
                        <tr>
                            <td>#${{index + 1}}</td>
                            <td><strong>${{coin.symbol || coin.coin}}</strong></td>
                            <td>$${{(coin.price || 0).toFixed(4)}}</td>
                            <td class="${{coin.change > 0 ? 'green' : 'red'}}">$${coin.change > 0 ? '+' : ''}${{(coin.change || 0).toFixed(2)}}%</td>
                            <td><a href="https://www.tradingview.com/chart/?symbol=BINANCE:${{coin.symbol || coin.coin}}" target="_blank" style="color:var(--blue);text-decoration:none;font-weight:bold;">📈 Grafik Aç</a></td>
                        </tr>
                    `).join('');
                }}

                const lTable = document.getElementById('losers-table');
                if (!data.top_losers || data.top_losers.length === 0) {{
                    lTable.innerHTML = `<tr><td colspan="5" style="padding:60px;text-align:center;color:#ffd700;"><div style="font-size:3rem;">😴</div><div>Şu anda aktif dump yok</div></td></tr>`;
                }} else {{
                    lTable.innerHTML = data.top_losers.map((coin, index) => `
                        <tr>
                            <td>#${{index + 1}}</td>
                            <td><strong>${{coin.symbol || coin.coin}}</strong></td>
                            <td>$${{(coin.price || 0).toFixed(4)}}</td>
                            <td class="${{coin.change > 0 ? 'green' : 'red'}}">$${coin.change > 0 ? '+' : ''}${{(coin.change || 0).toFixed(2)}}%</td>
                            <td><a href="https://www.tradingview.com/chart/?symbol=BINANCE:${{coin.symbol || coin.coin}}" target="_blank" style="color:var(--blue);text-decoration:none;font-weight:bold;">📉 Grafik Aç</a></td>
                        </tr>
                    `).join('');
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

# ==================== ANALYZE CHART ENDPOINT ====================
@app.post("/api/analyze-chart")
async def analyze_chart(request: Request):
    try:
        body = await request.json()
        symbol = body.get("symbol", "BTCUSDT").upper()
        timeframe = body.get("timeframe", "5m")

        logger.info(f"Analiz talebi: {symbol} {timeframe}")

        if not symbol.endswith("USDT"):
            symbol += "USDT"

        binance_client = get_binance_client()
        bybit_client = get_bybit_client()
        okex_client = get_okex_client()

        clients = [binance_client, bybit_client, okex_client]
        client_names = ["Binance", "Bybit", "OKEX"]

        if not any(clients):
            logger.warning("Hiçbir exchange client'ı kullanılabilir değil")
            return JSONResponse({
                "analysis": "❌ Borsa bağlantıları kurulamadı.",
                "success": False,
                "symbol": symbol,
                "timeframe": timeframe
            })

        klines_list = []
        interval_map = {
            "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
            "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
        }
        interval = interval_map.get(timeframe, "5m")
        ccxt_symbol = symbol.replace('USDT', '/USDT')

        for client, name in zip(clients, client_names):
            if client:
                try:
                    if hasattr(client, 'fetch_ohlcv'):
                        klines = await client.fetch_ohlcv(ccxt_symbol, timeframe=interval, limit=200)
                    else:
                        klines = client.fetch_ohlcv(ccxt_symbol, timeframe=interval, limit=200)

                    if klines and len(klines) > 50:
                        klines_list.append((name, klines))
                        logger.info(f"{name}: {len(klines)} mum alındı ({symbol})")
                except Exception as e:
                    logger.warning(f"{name} OHLCV hatası ({symbol}): {e}")

        if not klines_list:
            logger.info(f"Borsalar başarısız, CoinGecko deneniyor: {symbol}")
            coingecko_klines = await fetch_coingecko_ohlcv(symbol, timeframe)
            if coingecko_klines and len(coingecko_klines) > 50:
                klines_list.append(("CoinGecko", coingecko_klines))
                logger.info(f"CoinGecko: {len(coingecko_klines)} mum alındı ({symbol})")

        if not klines_list:
            return JSONResponse({
                "analysis": f"❌ {symbol} için veri alınamadı. Lütfen sembolü kontrol edin.",
                "success": False,
                "symbol": symbol,
                "timeframe": timeframe
            })

        source_name, klines = max(klines_list, key=lambda x: len(x[1]))

        df = pd.DataFrame(klines)
        if len(df.columns) >= 6:
            df = df.iloc[:, :6]
            df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        elif len(df.columns) >= 5:
            df = df.iloc[:, :5]
            df.columns = ['timestamp', 'open', 'high', 'low', 'close']
            df['volume'] = 1000
        else:
            return JSONResponse({ "analysis": "❌ Veri formatı hatalı", "success": False })

        df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')

        if df['timestamp'].max() > 1e10:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        else:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')

        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        df = df.sort_values('timestamp')
        df = df.tail(150)

        if len(df) < 50:
            return JSONResponse({
                "analysis": f"❌ Yeterli veri yok ({len(df)} mum)",
                "success": False,
                "data_points": len(df)
            })

        signal = None
        try:
            signal = generate_ict_signal(df.copy(), symbol, timeframe)
            if not signal or signal.get("signal") == "⏸️ ANALİZ BEKLENİYOR":
                signal = generate_simple_signal(df.copy(), symbol, timeframe)
        except Exception as e:
            logger.error(f"Sinyal üretme hatası ({symbol} {timeframe}): {e}")
            last_price = float(df['close'].iloc[-1])
            signal = {
                "pair": symbol.replace("USDT", "/USDT"),
                "current_price": round(last_price, 6),
                "signal": "⏸️ ANALİZ BEKLENİYOR",
                "score": 50,
                "killzone": "Normal",
                "triggers": f"Hata oluştu: {str(e)[:100]}",
                "last_update": datetime.utcnow().strftime("%H:%M UTC"),
                "strength": "ORTA",
                "data_source": source_name,
                "data_points": len(df)
            }

        analysis = f"""🔍 **{symbol.replace('USDT', '/USDT')} {timeframe.upper()} Analizi**  
Kaynak: {source_name} | Veri Sayısı: {len(df)} mum

🎯 SİNYAL: <span style="color:{"#00ff88" if "🚀" in str(signal.get('signal', '')) else "#ff4444" if "🔻" in str(signal.get('signal', '')) else "#ffd700"}"><strong>{signal.get('signal', 'Bekleniyor')}</strong></span>

📊 Skor: <strong>{signal.get('score', '?')}/100</strong> ({signal.get('strength', 'Bilinmiyor')})
💰 Fiyat: <strong>${signal.get('current_price', 0):,.6f}</strong>
🕐 Killzone: <strong>{signal.get('killzone', 'Normal')}</strong>
🕒 Son Güncelleme: {signal.get('last_update', 'Şimdi')}

🎯 Tetikleyenler:
{signal.get('triggers', 'Analiz ediliyor...')}

📈 Teknik Özet:
{symbol.replace('USDT', '')} şu anda {signal.get('signal', '').replace('🚀', 'yükseliş').replace('🔻', 'düşüş').replace('⏸️', 'nötr')} yönünde hareket gösteriyor.

💡 Öneri:
Kendi araştırmanızı yapın, stop-loss kullanın ve risk yönetimi uygulayın.

⚠️ Uyarı: Bu bir yatırım tavsiyesi değildir. Kripto para yatırımları yüksek risk içerir."""

        return JSONResponse({
            "analysis": analysis,
            "signal_data": signal,
            "success": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "data_source": source_name,
            "data_points": len(df),
            "current_price": float(df['close'].iloc[-1]),
            "price_change_24h": None,
            "timestamp": datetime.now().isoformat()
        })

    except json.JSONDecodeError:
        return JSONResponse({"analysis": "❌ Geçersiz JSON verisi", "success": False}, status_code=400)
    except Exception as e:
        logger.error(f"Analiz endpoint hatası: {e}", exc_info=True)
        return JSONResponse({
            "analysis": "❌ Sunucu hatası oluştu. Lütfen tekrar deneyin.",
            "success": False,
            "error": str(e)[:200]
        }, status_code=500)

# ==================== SİGNAL SAYFASI ====================
@app.get("/signal", response_class=HTMLResponse)
async def signal_page(request: Request):
    visitor_stats_html = get_visitor_stats_html()
    timeframes = get_available_timeframes()
    popular_symbols = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT", "MATIC"]

    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tek Coin Sinyal - ICT SMART PRO</title>
    <style>
        body {{background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: #fff; font-family: sans-serif; margin: 0; padding: 20px;}}
        .container {{max-width: 1200px; margin: auto;}}
        h1 {{text-align: center; color: #00dbde; margin: 30px 0;}}
        .search-box {{display: flex; gap: 10px; margin: 30px 0; flex-wrap: wrap;}}
        input, select, button {{padding: 15px; font-size: 1rem; border-radius: 10px; border: none;}}
        input {{flex: 1; min-width: 200px;}}
        select {{min-width: 150px;}}
        button {{background: linear-gradient(45deg, #00dbde, #fc00ff); color: white; cursor: pointer; font-weight: bold;}}
        button:hover {{transform: scale(1.05);}}
        .result {{background: rgba(255,255,255,0.05); padding: 30px; border-radius: 15px; margin: 30px 0; min-height: 200px;}}
        .loading {{text-align: center; padding: 50px; color: #888;}}
        .signal-display {{font-size: 1.2rem; line-height: 1.6;}}
        .popular-symbols {{display: flex; gap: 10px; flex-wrap: wrap; margin: 20px 0;}}
        .symbol-btn {{padding: 10px 20px; background: rgba(0,219,222,0.2); border-radius: 20px; cursor: pointer; transition: 0.3s;}}
        .symbol-btn:hover {{background: rgba(0,219,222,0.4);}}
    </style>
</head>
<body>
    {visitor_stats_html}
    <div class="container">
        <h1>🔍 Tek Coin Sinyal Analizi</h1>
        <div class="search-box">
            <input type="text" id="symbolInput" placeholder="Örn: BTC, ETH, SOL..." value="BTC">
            <select id="timeframeSelect">
                { "".join([f'<option value="{tf}">{tf.upper()}</option>' for tf in timeframes]) }
            </select>
            <button onclick="analyze()">🚀 Analiz Et</button>
        </div>

        <div class="popular-symbols">
            <strong>Popülerler: </strong>
            { "".join([f'<div class="symbol-btn" onclick="setSymbol(\'{s}\')">{s}</div>' for s in popular_symbols]) }
        </div>

        <div class="result" id="result">
            <div class="loading">Sembol ve timeframe seçin, analiz butonuna tıklayın...</div>
        </div>
    </div>

    <script>
        function setSymbol(symbol) {{
            document.getElementById('symbolInput').value = symbol;
            analyze();
        }}

        async function analyze() {{
            const symbol = document.getElementById('symbolInput').value.trim().toUpperCase();
            const timeframe = document.getElementById('timeframeSelect').value;

            if (!symbol) {{
                alert('Lütfen bir sembol girin (Örn: BTC, ETH)');
                return;
            }}

            document.getElementById('result').innerHTML = '<div class="loading">⏳ Analiz yapılıyor...</div>';

            try {{
                const response = await fetch('/api/analyze-chart', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{symbol: symbol, timeframe: timeframe}})
                }});

                const data = await response.json();

                if (data.success) {{
                    document.getElementById('result').innerHTML = `
                        <div class="signal-display">
                            <h2>${{symbol}}/${{timeframe.toUpperCase()}} Analiz Sonucu</h2>
                            <div>${{data.analysis.replace(/\\n/g, '<br>')}}</div>
                            <hr>
                            <small>Kaynak: ${{data.data_source}} | Veri: ${{data.data_points}} mum | Fiyat: $${{data.current_price?.toFixed(4) || 'N/A'}}</small>
                        </div>
                    `;
                }} else {{
                    document.getElementById('result').innerHTML = `
                        <div style="color:#ff4444;text-align:center;padding:50px;">
                            <h3>❌ Hata</h3>
                            <p>${{data.analysis}}</p>
                        </div>
                    `;
                }}
            }} catch (error) {{
                document.getElementById('result').innerHTML = `
                    <div style="color:#ff4444;text-align:center;padding:50px;">
                        <h3>❌ Bağlantı Hatası</h3>
                        <p>Sunucuya bağlanılamadı. Lütfen internet bağlantınızı kontrol edin.</p>
                    </div>
                `;
                console.error('Analiz hatası:', error);
            }}
        }}

        document.getElementById('symbolInput').addEventListener('keypress', function(e) {{
            if (e.key === 'Enter') analyze();
        }});

        window.onload = function() {{
            analyze();
        }};
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

# ==================== ALL SIGNALS SAYFASI ====================
@app.get("/signal/all", response_class=HTMLResponse)
async def all_signals_page(request: Request):
    visitor_stats_html = get_visitor_stats_html()
    timeframes = get_available_timeframes()

    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tüm Sinyaller - ICT SMART PRO</title>
    <style>
        body {{background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: #fff; font-family: sans-serif; margin: 0; padding: 20px;}}
        .container {{max-width: 1400px; margin: auto;}}
        h1 {{text-align: center; color: #00dbde; margin: 30px 0;}}
        .timeframe-tabs {{display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; margin: 30px 0;}}
        .tab {{padding: 10px 20px; background: rgba(255,255,255,0.1); border-radius: 10px; cursor: pointer;}}
        .tab.active {{background: linear-gradient(45deg, #00dbde, #fc00ff);}}
        .signals-container {{display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px;}}
        .signal-card {{background: rgba(255,255,255,0.05); padding: 20px; border-radius: 15px; transition: 0.3s;}}
        .signal-card:hover {{transform: translateY(-5px); background: rgba(255,255,255,0.1);}}
        .signal-card.buy {{border-left: 5px solid #00ff88;}}
        .signal-card.sell {{border-left: 5px solid #ff4444;}}
        .signal-card.neutral {{border-left: 5px solid #ffd700;}}
        .signal-header {{display: flex; justify-content: space-between; align-items: center;}}
        .signal-score {{padding: 5px 15px; border-radius: 20px; font-weight: bold;}}
        .score-high {{background: rgba(0,255,136,0.2); color: #00ff88;}}
        .score-medium {{background: rgba(255,215,0,0.2); color: #ffd700;}}
        .score-low {{background: rgba(255,68,68,0.2); color: #ff4444;}}
        .loader {{text-align: center; padding: 50px;}}
        .loading {{border: 4px solid rgba(255,255,255,0.1); border-top: 4px solid #00dbde; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: auto;}}
        @keyframes spin {{0% {{transform: rotate(0deg);}} 100% {{transform: rotate(360deg);}}}}
    </style>
</head>
<body>
    {visitor_stats_html}
    <div class="container">
        <h1>🔥 Tüm Zaman Dilimi Sinyalleri</h1>
        <div class="timeframe-tabs" id="timeframeTabs">
            { "".join([f'<div class="tab" onclick="loadTimeframe(\'{tf}\')">{tf.upper()}</div>' for tf in timeframes]) }
        </div>

        <div id="signalsContent">
            <div class="loader">
                <div class="loading"></div>
                <p>Sinyaller yükleniyor...</p>
            </div>
        </div>
    </div>

    <script>
        let currentTimeframe = '5m';
        let ws = null;

        function loadTimeframe(tf) {{
            currentTimeframe = tf;
            document.querySelectorAll('.tab').forEach(tab => {{
                tab.classList.remove('active');
                if (tab.textContent === tf.toUpperCase()) tab.classList.add('active');
            }});

            if (ws) ws.close();

            const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
            ws = new WebSocket(protocol + '://' + window.location.host + '/ws/all/' + tf);

            ws.onopen = function() {{ console.log('All signals WebSocket connected for timeframe:', tf); }};

            ws.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    if (data.ping) return;
                    const signals = data.signals || [];
                    updateSignalsDisplay(signals, tf);
                }} catch (error) {{
                    console.error('WebSocket message error:', error);
                }}
            }};

            ws.onerror = function(error) {{
                console.error('WebSocket error:', error);
                document.getElementById('signalsContent').innerHTML = '<div style="color:#ff4444;text-align:center;padding:50px;">⚠️ Canlı bağlantı kurulamadı</div>';
            }};

            ws.onclose = function() {{ console.log('WebSocket closed for timeframe:', tf); }};
        }}

        function updateSignalsDisplay(signals, timeframe) {{
            const container = document.getElementById('signalsContent');

            if (!signals || signals.length === 0) {{
                container.innerHTML = `
                    <div style="text-align:center;padding:50px;color:#888;">
                        <div style="font-size:3rem;">😴</div>
                        <h3>${{timeframe.toUpperCase()}} zaman diliminde aktif sinyal bulunamadı</h3>
                        <p>Diğer zaman dilimlerini kontrol edin veya biraz bekleyin</p>
                    </div>
                `;
                return;
            }}

            let html = '<div class="signals-container">';
            signals.forEach(signal => {{
                const score = signal.score || 50;
                let scoreClass = 'score-medium';
                if (score >= 70) scoreClass = 'score-high';
                else if (score <= 30) scoreClass = 'score-low';

                let cardClass = 'signal-card neutral';
                if (signal.signal && signal.signal.includes('🚀')) cardClass = 'signal-card buy';
                else if (signal.signal && signal.signal.includes('🔻')) cardClass = 'signal-card sell';

                html += `
                    <div class="${{cardClass}}">
                        <div class="signal-header">
                            <h3>${{signal.pair || signal.symbol || 'N/A'}}</h3>
                            <div class="signal-score ${{scoreClass}}">${{score}}/100</div>
                        </div>
                        <p><strong>Sinyal:</strong> ${{signal.signal || 'N/A'}}</p>
                        <p><strong>Fiyat:</strong> $${{signal.current_price?.toFixed(4) || 'N/A'}}</p>
                        <p><strong>Güç:</strong> ${{signal.strength || 'ORTA'}}</p>
                        <p><strong>Zaman:</strong> ${{timeframe.toUpperCase()}}</p>
                        <p><strong>Son Güncelleme:</strong> ${{signal.last_update || 'Şimdi'}}</p>
                        <div style="margin-top:10px;font-size:0.9em;color:#888;">
                            ${{signal.triggers?.substring(0, 100) || ''}}${{signal.triggers?.length > 100 ? '...' : ''}}
                        </div>
                    </div>
                `;
            }});
            html += '</div>';
            container.innerHTML = html;
        }}

        window.onload = function() {{
            loadTimeframe('5m');
        }};

        window.addEventListener('beforeunload', function() {{
            if (ws) ws.close();
        }});
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

# ==================== REALTIME PRICE PAGE ====================
@app.get("/realtime", response_class=HTMLResponse)
async def realtime_price_page(request: Request):
    visitor_stats_html = get_visitor_stats_html()

    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Canlı Fiyatlar - ICT SMART PRO</title>
    <style>
        body {{background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: #fff; font-family: sans-serif; margin: 0; padding: 20px;}}
        .container {{max-width: 1200px; margin: auto;}}
        h1 {{text-align: center; color: #00dbde; margin: 30px 0;}}
        .controls {{display: flex; gap: 10px; margin: 30px 0; flex-wrap: wrap;}}
        input {{flex: 1; min-width: 200px; padding: 15px; border-radius: 10px; border: none; background: rgba(255,255,255,0.1); color: white;}}
        .prices-grid {{display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px;}}
        .price-card {{background: rgba(255,255,255,0.05); padding: 15px; border-radius: 10px; transition: 0.3s;}}
        .price-card:hover {{background: rgba(255,255,255,0.1);}}
        .price-up {{border-left: 5px solid #00ff88;}}
        .price-down {{border-left: 5px solid #ff4444;}}
        .price-neutral {{border-left: 5px solid #888;}}
        .symbol {{font-weight: bold; font-size: 1.1rem;}}
        .price {{font-size: 1.2rem; margin: 10px 0;}}
        .change {{font-size: 0.9rem;}}
        .change.up {{color: #00ff88;}}
        .change.down {{color: #ff4444;}}
        .update-time {{text-align: center; color: #888; margin: 20px 0;}}
    </style>
</head>
<body>
    {visitor_stats_html}
    <div class="container">
        <h1>📊 Canlı Fiyat Takibi</h1>
        <div class="controls">
            <input type="text" id="searchInput" placeholder="Sembol ara (BTC, ETH, vs.)" onkeyup="filterPrices()">
        </div>

        <div class="update-time" id="updateTime">Son güncelleme: --:--:--</div>

        <div class="prices-grid" id="pricesGrid">
            <div style="grid-column: 1/-1; text-align: center; padding: 50px; color: #888;">
                <div style="width: 40px; height: 40px; border: 4px solid rgba(255,255,255,0.1); border-top: 4px solid #00dbde; border-radius: 50%; animation: spin 1s linear infinite; margin: auto;"></div>
                <p>Canlı fiyatlar yükleniyor...</p>
            </div>
        </div>
    </div>

    <script>
        let allPrices = [];
        let ws = null;

        function connectWebSocket() {{
            const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
            ws = new WebSocket(protocol + '://' + window.location.host + '/ws/realtime_price');

            ws.onopen = function() {{
                console.log('Realtime price WebSocket connected');
                document.getElementById('updateTime').textContent = 'Bağlantı kuruldu, veriler geliyor...';
            }};

            ws.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    updatePricesDisplay(data);
                }} catch (error) {{
                    console.error('Price WebSocket message error:', error);
                }}
            }};

            ws.onerror = function(error) {{
                console.error('Price WebSocket error:', error);
                document.getElementById('updateTime').textContent = '⚠️ Bağlantı hatası, yeniden bağlanılıyor...';
                setTimeout(connectWebSocket, 5000);
            }};

            ws.onclose = function() {{
                console.log('Price WebSocket closed');
                setTimeout(connectWebSocket, 3000);
            }};
        }}

        function updatePricesDisplay(data) {{
            const prices = data.prices || [];
            const timestamp = data.timestamp || new Date().toISOString();

            allPrices = prices;

            const updateTime = new Date(timestamp).toLocaleTimeString('tr-TR');
            document.getElementById('updateTime').textContent = `Son güncelleme: ${{updateTime}}`;

            const grid = document.getElementById('pricesGrid');
            const searchTerm = document.getElementById('searchInput').value.toLowerCase();

            let filteredPrices = prices;
            if (searchTerm) {{
                filteredPrices = prices.filter(p =>
                    (p.symbol && p.symbol.toLowerCase().includes(searchTerm)) ||
                    (p.pair && p.pair.toLowerCase().includes(searchTerm))
                );
            }}

            if (filteredPrices.length === 0) {{
                grid.innerHTML = `
                    <div style="grid-column: 1/-1; text-align: center; padding: 50px; color: #888;">
                        <div style="font-size: 3rem;">🔍</div>
                        <h3>"${{searchTerm}}" için sonuç bulunamadı</h3>
                    </div>
                `;
                return;
            }}

            let html = '';
            filteredPrices.forEach(price => {{
                const symbol = price.symbol || price.pair || 'N/A';
                const value = price.price || price.last || 0;
                const change = price.change || price.change24h || 0;
                const changePercent = price.changePercent || price.changePercentage || 0;

                const changeClass = change > 0 ? 'up' : change < 0 ? 'down' : '';
                const cardClass = change > 0 ? 'price-up' : change < 0 ? 'price-down' : 'price-neutral';

                html += `
                    <div class="price-card ${{cardClass}}">
                        <div class="symbol">${{symbol.replace('USDT', '')}}</div>
                        <div class="price">$${{value.toFixed(4)}}</div>
                        <div class="change ${{changeClass}}">
                            ${{change > 0 ? '+' : ''}}${{change.toFixed(2)}} (${{changePercent > 0 ? '+' : ''}}${{changePercent.toFixed(2)}}%)
                        </div>
                        <div style="font-size:0.8rem;color:#888;margin-top:5px;">
                            ${{price.source || 'Binance'}}
                        </div>
                    </div>
                `;
            }});

            grid.innerHTML = html;
        }}

        function filterPrices() {{
            if (allPrices.length > 0) {{
                updatePricesDisplay({{prices: allPrices, timestamp: new Date().toISOString()}});
            }}
        }}

        window.onload = function() {{
            connectWebSocket();
        }};

        window.addEventListener('beforeunload', function() {{
            if (ws) ws.close();
        }});
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

# ==================== ADMIN PANEL ====================
@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    admin_token = request.cookies.get("admin_token") or request.query_params.get("token")
    valid_token = os.getenv("ADMIN_TOKEN", "ict-pro-admin-2024")

    if admin_token != valid_token:
        login_html = """<!DOCTYPE html>
<html>
<head>
    <title>Admin Girişi - ICT SMART PRO</title>
    <style>
        body {{background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: #fff; font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0;}}
        .login-box {{background: rgba(255,255,255,0.05); padding: 40px; border-radius: 20px; width: 100%; max-width: 400px; text-align: center;}}
        input {{width: 100%; padding: 15px; margin: 15px 0; border-radius: 10px; border: none; background: rgba(255,255,255,0.1); color: white;}}
        button {{width: 100%; padding: 15px; background: linear-gradient(45deg, #00dbde, #fc00ff); color: white; border: none; border-radius: 10px; font-weight: bold; cursor: pointer;}}
        h2 {{color: #00dbde;}}
    </style>
</head>
<body>
    <div class="login-box">
        <h2>🔒 Admin Girişi</h2>
        <input type="password" id="password" placeholder="Admin Şifresi">
        <button onclick="login()">Giriş Yap</button>
        <p id="error" style="color:#ff4444;display:none;">❌ Yanlış şifre!</p>
    </div>
    <script>
        function login() {{
            const password = document.getElementById('password').value;
            if (!password) return;
            document.cookie = "admin_token=" + password + "; path=/; max-age=86400; samesite=strict";
            window.location.href = "/admin";
        }}
    </script>
</body>
</html>"""
        return HTMLResponse(content=login_html)

    stats = visitor_counter.get_stats()

    ws_stats = {
        "price_sources_subscribers": len(price_sources_subscribers),
        "pump_radar_subscribers": len(pump_radar_subscribers),
        "single_subscribers_total": sum(len(v) for v in single_subscribers.values()),
        "all_subscribers_total": sum(len(v) for v in all_subscribers.values()),
        "rt_ticker_subscribers": len(rt_ticker.subscribers) if hasattr(rt_ticker, 'subscribers') else 0
    }

    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Paneli - ICT SMART PRO</title>
    <style>
        body {{background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: #fff; font-family: monospace; margin: 0; padding: 20px;}}
        .container {{max-width: 1400px; margin: auto;}}
        h1 {{text-align: center; color: #00ff88; margin: 30px 0;}}
        .stats-grid {{display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 30px 0;}}
        .stat-card {{background: rgba(255,255,255,0.05); padding: 20px; border-radius: 15px; border-left: 5px solid #00dbde;}}
        .stat-title {{color: #00dbde; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 1px;}}
        .stat-value {{font-size: 2rem; font-weight: bold; margin: 10px 0;}}
        .stat-sub {{color: #888; font-size: 0.9rem;}}
        .danger-zone {{background: rgba(255,68,68,0.1); border-color: #ff4444; padding: 30px; margin: 40px 0;}}
        .btn {{padding: 10px 20px; background: linear-gradient(45deg, #00dbde, #fc00ff); color: white; border: none; border-radius: 10px; cursor: pointer; margin: 5px;}}
        .btn-danger {{background: linear-gradient(45deg, #ff4444, #ff8800);}}
        .btn:hover {{opacity: 0.9;}}
        .log-container {{background: rgba(0,0,0,0.5); padding: 20px; border-radius: 10px; margin: 30px 0; max-height: 400px; overflow-y: auto; font-family: monospace; font-size: 0.9rem;}}
        .log-entry {{padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,0.1);}}
        .log-time {{color: #00ff88;}}
        .log-level-INFO {{color: #00dbde;}}
        .log-level-WARNING {{color: #ffd700;}}
        .log-level-ERROR {{color: #ff4444;}}
        .refresh-btn {{position: fixed; top: 20px; right: 20px;}}
    </style>
</head>
<body>
    <div class="container">
        <h1>⚙️ Admin Paneli - ICT SMART PRO</h1>
        <div class="refresh-btn">
            <button class="btn" onclick="location.reload()">🔄 Yenile</button>
            <button class="btn btn-danger" onclick="clearLogs()">🗑️ Logları Temizle</button>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-title">Ziyaretçi İstatistikleri</div>
                <div class="stat-value">{stats['total_visits']}</div>
                <div class="stat-sub">Toplam Ziyaret</div>
                <div>Bugün: {stats['today_visits']} ({stats['today_unique']} benzersiz)</div>
                <div>Aktif Kullanıcılar: {stats['active_users']}</div>
            </div>

            <div class="stat-card">
                <div class="stat-title">WebSocket Bağlantıları</div>
                <div class="stat-value">{ws_stats['single_subscribers_total'] + ws_stats['all_subscribers_total'] + ws_stats['price_sources_subscribers'] + ws_stats['pump_radar_subscribers'] + ws_stats['rt_ticker_subscribers']}</div>
                <div class="stat-sub">Toplam Aktif Bağlantı</div>
                <div>Tek Coin: {ws_stats['single_subscribers_total']}</div>
                <div>Tüm Coinler: {ws_stats['all_subscribers_total']}</div>
                <div>Pump Radar: {ws_stats['pump_radar_subscribers']}</div>
                <div>Canlı Fiyat: {ws_stats['rt_ticker_subscribers']}</div>
            </div>

            <div class="stat-card">
                <div class="stat-title">Sistem Durumu</div>
                <div class="stat-value">✅ ÇALIŞIYOR</div>
                <div class="stat-sub">Uptime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
                <div>Timeframes: {len(get_available_timeframes())}</div>
                <div>Price Pool: {len(price_pool)} sembol</div>
            </div>

            <div class="stat-card">
                <div class="stat-title">En Çok Ziyaret Edilen Sayfalar</div>
                { "".join([f'<div>{page}: {count} ziyaret</div>' for page, count in list(stats['page_views'].items())[:5]]) }
            </div>
        </div>

        <h2>📊 Canlı Sistem Logları</h2>
        <div class="log-container" id="logContainer">
            <div class="log-entry"><span class="log-time">{datetime.now().strftime('%H:%M:%S')}</span> <span class="log-level-INFO">INFO</span> Admin paneli yüklendi</div>
        </div>

        <div class="danger-zone">
            <h3 style="color:#ff4444;">⚠️ Tehlike Bölgesi</h3>
            <button class="btn btn-danger" onclick="clearAllData()">🗑️ Tüm Cache'i Temizle</button>
            <button class="btn btn-danger" onclick="forceReconnect()">🔌 Tüm WS Bağlantılarını Yeniden Başlat</button>
            <button class="btn btn-danger" onclick="restartSystem()">🔄 Sistemi Yeniden Başlat</button>
            <small style="color:#888; display:block; margin-top:10px;">Bu işlemler geri alınamaz!</small>
        </div>
    </div>

    <script>
        function clearLogs() {{
            document.getElementById('logContainer').innerHTML = '';
            addLog('INFO', 'Loglar temizlendi');
        }}

        function clearAllData() {{
            if (confirm('Tüm cache verilerini temizlemek istediğinize emin misiniz? Bu işlem geri alınamaz!')) {{
                fetch('/api/admin/clear-cache', {{method: 'POST'}})
                    .then(r => r.json())
                    .then(data => {{
                        addLog('INFO', 'Cache temizlendi: ' + JSON.stringify(data));
                        alert('Cache başarıyla temizlendi!');
                    }})
                    .catch(err => addLog('ERROR', 'Cache temizleme hatası: ' + err));
            }}
        }}

        function forceReconnect() {{
            if (confirm('Tüm WebSocket bağlantıları kesilecek ve yeniden bağlanacak. Devam etmek istiyor musunuz?')) {{
                fetch('/api/admin/reconnect-ws', {{method: 'POST'}})
                    .then(r => r.json())
                    .then(data => {{
                        addLog('INFO', 'WebSocket bağlantıları yeniden başlatıldı');
                        alert('WebSocket bağlantıları yeniden başlatıldı!');
                    }});
            }}
        }}

        function restartSystem() {{
            if (confirm('Sistem yeniden başlatılacak. Bu işlem 10-30 saniye sürebilir. Devam etmek istiyor musunuz?')) {{
                fetch('/api/admin/restart', {{method: 'POST'}})
                    .then(r => r.json())
                    .then(data => {{
                        addLog('INFO', 'Sistem yeniden başlatma komutu gönderildi');
                        alert('Sistem yeniden başlatma komutu gönderildi! Sayfa birkaç saniye içinde yeniden yüklenecek.');
                        setTimeout(() => location.reload(), 5000);
                    }});
            }}
        }}

        function addLog(level, message) {{
            const container = document.getElementById('logContainer');
            const time = new Date().toLocaleTimeString('tr-TR');
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            entry.innerHTML = `<span class="log-time">${{time}}</span> <span class="log-level-${{level}}">${{level}}</span> ${{message}}`;
            container.appendChild(entry);
            container.scrollTop = container.scrollHeight;
        }}

        setTimeout(() => addLog('INFO', 'Sistem durumu kontrol ediliyor...'), 1000);
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

# ==================== ADMIN API ENDPOINTS ====================
@app.post("/api/admin/clear-cache")
async def admin_clear_cache(request: Request):
    admin_token = request.cookies.get("admin_token") or request.query_params.get("token")
    valid_token = os.getenv("ADMIN_TOKEN", "ict-pro-admin-2024")
    if admin_token != valid_token:
        raise HTTPException(status_code=403, detail="Yetkisiz erişim")

    try:
        logger.info("Admin cache temizleme işlemi başlatıldı")
        return {"status": "success", "message": "Cache temizlendi", "timestamp": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"Cache temizleme hatası: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/reconnect-ws")
async def admin_reconnect_ws(request: Request):
    admin_token = request.cookies.get("admin_token") or request.query_params.get("token")
    valid_token = os.getenv("ADMIN_TOKEN", "ict-pro-admin-2024")
    if admin_token != valid_token:
        raise HTTPException(status_code=403, detail="Yetkisiz erişim")

    try:
        logger.info("Admin WS yeniden başlatma işlemi başlatıldı")
        return {"status": "success", "message": "WebSocket bağlantıları yeniden başlatılacak", "timestamp": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"WS yeniden başlatma hatası: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/restart")
async def admin_restart(request: Request):
    admin_token = request.cookies.get("admin_token") or request.query_params.get("token")
    valid_token = os.getenv("ADMIN_TOKEN", "ict-pro-admin-2024")
    if admin_token != valid_token:
        raise HTTPException(status_code=403, detail="Yetkisiz erişim")

    try:
        logger.warning("Admin sistem yeniden başlatma komutu gönderildi")
        return {
            "status": "success",
            "message": "Sistem yeniden başlatma komutu alındı",
            "timestamp": datetime.now().isoformat(),
            "note": "Bu sadece simülasyondur. Gerçek production'da process manager kullanın."
        }
    except Exception as e:
        logger.error(f"Sistem yeniden başlatma hatası: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== HEALTH CHECK ====================
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "ICT SMART PRO",
        "version": "3.0",
        "timestamp": datetime.now().isoformat(),
        "visitor_stats": visitor_counter.get_stats(),
        "system": {
            "python_version": "3.8+",
            "websocket_connections": {
                "price_sources": len(price_sources_subscribers),
                "pump_radar": len(pump_radar_subscribers),
                "single_signal": sum(len(v) for v in single_subscribers.values()),
                "all_signals": sum(len(v) for v in all_subscribers.values())
            }
        }
    }

# ==================== DEBUG ENDPOINT ====================
@app.get("/debug/sources")
async def debug_sources():
    return {
        "price_sources_status": price_sources_status,
        "price_pool_count": len(price_pool),
        "active_strong_signals": {tf: len(sigs) for tf, sigs in active_strong_signals.items()},
        "top_gainers_count": len(top_gainers),
        "top_losers_count": len(top_losers),
        "visitor_stats": visitor_counter.get_stats(),
        "timestamp": datetime.now().isoformat()
    }

# ==================== LOGIN ENDPOINT ====================
@app.post("/api/login")
async def login_user(response: Response, email: str = Form(...), password: str = Form(...)):
    if email and password:
        response.set_cookie(
            key="user_email",
            value=email.split("@")[0],
            max_age=86400 * 7,
            httponly=True,
            samesite="lax",
            secure=False
        )
        return {"status": "success", "message": "Giriş başarılı", "user": email}
    else:
        raise HTTPException(status_code=400, detail="E-posta ve şifre gerekli")

# ==================== LOGOUT ENDPOINT ====================
@app.get("/logout")
async def logout_user(response: Response):
    response.delete_cookie("user_email")
    response.delete_cookie("admin_token")
    return RedirectResponse(url="/")

# ==================== FILE UPLOAD ====================
@app.post("/api/upload-symbols")
async def upload_symbols(file: UploadFile = File(...)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Sadece CSV dosyaları yüklenebilir")

    try:
        contents = await file.read()
        df = pd.read_csv(io.StringIO(contents.decode('utf-8')))

        symbols = []
        if 'symbol' in df.columns:
            symbols = df['symbol'].tolist()
        elif 'coin' in df.columns:
            symbols = df['coin'].tolist()

        symbols = [s.upper() + ("USDT" if not s.upper().endswith("USDT") else "") for s in symbols]

        return {
            "status": "success",
            "filename": file.filename,
            "symbol_count": len(symbols),
            "symbols": symbols[:10],
            "message": f"{len(symbols)} sembol başarıyla yüklendi"
        }
    except Exception as e:
        logger.error(f"Dosya yükleme hatası: {e}")
        raise HTTPException(status_code=500, detail=f"Dosya işleme hatası: {str(e)}")

# ==================== ROOT REDIRECT ====================
@app.get("/favicon.ico")
async def favicon():
    return RedirectResponse(url="/")

# ==================== MAIN ENTRY POINT ====================
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
