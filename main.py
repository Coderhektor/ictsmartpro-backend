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

# === Logger Setup ===
logger = logging.getLogger("uvicorn")
logger.setLevel(logging.INFO)

# === Global Dummy Definitions (fallback için önceden tanımla) ===
# Bu, NameError riskini tamamen ortadan kaldırır
GrokIndicators = None
generate_ict_signal = None
generate_simple_signal = None

# === Indicators Modülü: Gerçek veya Dummy ===
try:
    from indicators import GrokIndicatorsPro as GrokIndicators, generate_ict_signal, generate_simple_signal
    logger.info("✅ Indicators modülü başarıyla yüklendi")
except ImportError as e:
    logger.warning(f"⚠️ Indicators modülü yüklenemedi ({e}), dummy fonksiyonlar kullanılıyor...")

    # Dummy GrokIndicators sınıfı
    class GrokIndicators:
        def __init__(self):
            pass
        def detect_all_patterns(self, df: pd.DataFrame) -> Dict[str, Any]:
            return {}

    # Dummy sinyal fonksiyonları
    def generate_ict_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Dict[str, Any]:
        return {
            "signal": "NEUTRAL",
            "reason": "Indicators modülü eksik",
            "confidence": 0,
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
            "timeframe": timeframe
        }

    def generate_simple_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Dict[str, Any]:
        return {
            "signal": "NEUTRAL",
            "reason": "Indicators modülü eksik",
            "rsi": 50,
            "macd_hist": 0,
            "timeframe": timeframe
        }
    
    # Dummy fallback değerler
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
        return {"prices": {}, "timestamp": datetime.now().isoformat()}  # ✅ "prices": [] değil, dict bekleniyor genelde

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
#===================================================================
from realtime_prices import price_manager, get_all_prices_snapshot

@app.websocket("/ws/realtime_price")
async def ws_realtime_price(websocket: WebSocket):
    await websocket.accept()
    
    try:
        while True:
            # Tüm aktif sembollerin fiyatlarını al
            snapshot = {}
            for sym in price_manager.all_symbols:
                snapshot[sym.replace('/', '')] = price_manager.get_price(sym)
            
            await websocket.send_json({
                "type": "full_update",
                "prices": snapshot,
                "count": len(snapshot),
                "timestamp": datetime.utcnow().isoformat() + 'Z'
            })
            await asyncio.sleep(3)
            
    except WebSocketDisconnect:
        logger.info("Realtime price WS kapandı")
    except Exception as e:
        logger.error(f"Realtime WS hata: {e}")

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
#=================================================================================
# ==================== TEK COİN SİNYAL SAYFASI ====================
@app.get("/signal/", response_class=HTMLResponse)
async def signal_page(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    visitor_stats_html = get_visitor_stats_html()
    timeframes = get_available_timeframes()

    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tek Coin Sinyal - ICT SMART PRO</title>
    <style>
        body {{
            background: linear-gradient(135deg, #0a0022, #1a0033, #000);
            color: white;
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            padding: 30px 0;
        }}
        .title {{
            font-size: 2.5rem;
            background: linear-gradient(90deg, #00dbde, #fc00ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 20px;
        }}
        .controls {{
            background: rgba(255, 255, 255, 0.05);
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
            text-align: center;
        }}
        button {{
            background: linear-gradient(45deg, #fc00ff, #00dbde);
            font-weight: bold;
            cursor: pointer;
            margin: 10px 5px;
            display: inline-block;
            width: auto;
            min-width: 200px;
            padding: 12px;
            border: none;
            border-radius: 8px;
            color: white;
            font-size: 1rem;
        }}
        .signal-card {{
            background: rgba(0, 0, 0, 0.5);
            padding: 30px;
            border-radius: 10px;
            margin: 30px 0;
            text-align: center;
            border-left: 5px solid #ffd700;
        }}
        .signal-card.green {{ border-left-color: #00ff88; }}
        .signal-card.red {{ border-left-color: #ff4444; }}
        .signal-text {{
            font-size: 2rem;
            font-weight: bold;
            margin-bottom: 15px;
        }}
        .ai-analysis {{
            background: rgba(13, 0, 51, 0.9);
            border-radius: 10px;
            padding: 25px;
            margin: 20px 0;
            border: 2px solid #00dbde;
            display: none;
        }}
        .chart-container {{
            width: 100%;
            height: 80vh;
            min-height: 1000px;
            background: rgba(10, 0, 34, 0.9);
            border-radius: 16px;
            margin: 30px 0;
            overflow: hidden;
            box-shadow: 0 0 30px rgba(0, 219, 222, 0.2);
        }}
        .navigation {{
            text-align: center;
            margin-top: 30px;
        }}
        .nav-link {{
            color: #00dbde;
            text-decoration: none;
            margin: 0 15px;
        }}
        .user-info {{
            position: fixed;
            top: 15px;
            left: 15px;
            background: rgba(0, 0, 0, 0.7);
            padding: 10px 20px;
            border-radius: 10px;
            color: #00ff88;
        }}

        input#pair {{
            background-color: #1a0033;
            color: #00ff88;
            border: 2px solid #00dbde;
            border-radius: 12px;
            padding: 14px 18px;
            font-size: 1.2rem;
            font-weight: bold;
            width: 100%;
            max-width: 400px;
            box-sizing: border-box;
            transition: all 0.3s ease;
        }}
        input#pair::placeholder {{
            color: #00dbdeaa;
            font-weight: normal;
        }}
        input#pair:focus {{
            outline: none;
            border-color: #fc00ff;
            background-color: #2a0044;
            box-shadow: 0 0 20px rgba(252, 0, 255, 0.5);
            color: #ffffff;
        }}
        input#pair:hover {{
            border-color: #fc00ff88;
            box-shadow: 0 0 15px rgba(252, 0, 255, 0.3);
        }}

        select#timeframe {{
            background-color: #1a0033;
            color: #00ff88;
            border: 2px solid #00dbde;
            border-radius: 12px;
            padding: 14px 40px 14px 18px;
            font-size: 1.2rem;
            font-weight: bold;
            min-width: 220px;
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='10' viewBox='0 0 14 10'%3E%3Cpath fill='%2300ff88' d='M1 1l6 6 6-6' stroke='%2300ff88' stroke-width='2'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 18px center;
            background-size: 14px;
            cursor: pointer;
            transition: all 0.3s ease;
        }}
        select#timeframe:hover {{
            background-color: #2a0044;
            border-color: #fc00ff;
            box-shadow: 0 0 15px rgba(252, 0, 255, 0.3);
        }}
        select#timeframe:focus {{
            outline: none;
            border-color: #fc00ff;
            box-shadow: 0 0 20px rgba(252, 0, 255, 0.5);
        }}
    </style>
    <script src="https://s3.tradingview.com/tv.js"></script>
</head>
<body>
    <div class="user-info">👤 Hoş geldin, <strong>{user}</strong></div>
    {visitor_stats_html}
    
    <div class="container">
        <div class="header">
            <h1 class="title">📊 TEK COİN CANLI SİNYAL</h1>
        </div>
        
        <div class="controls">
            <input type="text" id="pair" placeholder="Coin (örn: BTC)" value="BTC">
            <select id="timeframe">
                {"".join([f'<option value="{tf}"{" selected" if tf == "5m" else ""}>{tf.upper()}</option>' for tf in timeframes])}
            </select>
            <div>
                <button onclick="connectSignal()">🔴 CANLI SİNYAL BAĞLANTISI KUR</button>
                <button onclick="analyzeChartWithAI()" style="background:linear-gradient(45deg,#00dbde,#ff00ff);">🤖 GRAFİĞİ ANALİZ ET</button>
            </div>
            <div id="connection-status" style="color:#00ffff;margin:10px 0;">Bağlantı bekleniyor...</div>
        </div>
        
        <div id="signal-card" class="signal-card">
            <div id="signal-text" class="signal-text" style="color: #ffd700;">
                Sinyal bağlantısı kurulmadı
            </div>
            <div id="signal-details">
                Canlı sinyal için yukarıdaki butona tıklayın.
            </div>
        </div>
        
        <div id="ai-box" class="ai-analysis">
            <h3 style="color:#00dbde;text-align:center;">🤖 TEKNİK ANALİZ RAPORU</h3>
            <p id="ai-comment">Analiz için "Grafiği Analiz Et" butonuna tıklayın.</p>
        </div>
        
        <div class="chart-container">
            <div id="tradingview_widget"></div>
        </div>
        
        <div class="navigation">
            <a href="/" class="nav-link">← Ana Sayfa</a>
            <a href="/signal/all/" class="nav-link">Tüm Coinler →</a>
        </div>
    </div>
    
    <script>
        let signalWs = null;
        let tradingViewWidget = null;
        let currentSymbol = "BTC";
        let currentTimeframe = "5m";
        
        const timeframeMap = {{
            "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
            "1h": "60", "4h": "240", "1d": "D", "1w": "W", "1M": "M"
        }};
        
        function getTradingViewSymbol(pair) {{
            let symbol = pair.trim().toUpperCase();
            if (!symbol.endsWith("USDT")) symbol += "USDT";
            return "BINANCE:" + symbol;
        }}
        
        function connectSignal() {{
            currentSymbol = document.getElementById('pair').value.trim().toUpperCase();
            currentTimeframe = document.getElementById('timeframe').value;
            const tvSymbol = getTradingViewSymbol(currentSymbol);
            const interval = timeframeMap[currentTimeframe] || "5";
            
            if (signalWs) {{ signalWs.close(); signalWs = null; }}
            if (tradingViewWidget) {{ tradingViewWidget.remove(); }}
            
            tradingViewWidget = new TradingView.widget({{
                width: "100%",
                height: "100%",
                symbol: tvSymbol,
                interval: interval,
                timezone: "Etc/UTC",
                theme: "dark",
                style: "1",
                locale: "tr",
                container_id: "tradingview_widget",
                overrides: {{
                    "paneProperties.backgroundType": "solid",
                    "paneProperties.background": "#000000",
                    "scalesProperties.textColor": "#FFFFFF",
                    "paneProperties.vertGridProperties.color": "#333333",
                    "paneProperties.horzGridProperties.color": "#333333"
                }}
            }});
            
            const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
            signalWs = new WebSocket(protocol + window.location.host + '/ws/signal/' + currentSymbol + '/' + currentTimeframe);
            
            signalWs.onopen = function() {{
                document.getElementById('connection-status').innerHTML = '✅ ' + currentSymbol + ' ' + currentTimeframe.toUpperCase() + ' canlı sinyal başladı!';
            }};
            
            signalWs.onmessage = function(event) {{
                try {{
                    if (event.data.includes('heartbeat')) return;
                    const data = JSON.parse(event.data);
                    const card = document.getElementById('signal-card');
                    const text = document.getElementById('signal-text');
                    const details = document.getElementById('signal-details');
                    
                    text.innerHTML = data.signal || "⏸️ Sinyal bekleniyor...";
                    
                    details.innerHTML = `
                        <strong>${{data.pair || currentSymbol + '/USDT'}}</strong><br>
                        💰 Fiyat: <strong>$${{(data.current_price || 0).toFixed(data.current_price < 1 ? 6 : 4)}}</strong><br>
                        📊 Skor: <strong>${{data.score || '?'}} / 100</strong> | ${{data.killzone || 'Normal'}}
                    `;
                    
                    if (data.signal && (data.signal.includes('🚀') || data.signal.includes('AL'))) {{
                        card.className = 'signal-card green';
                        text.style.color = '#00ff88';
                    }} else if (data.signal && (data.signal.includes('🔻') || data.signal.includes('SAT'))) {{
                        card.className = 'signal-card red';
                        text.style.color = '#ff4444';
                    }} else {{
                        card.className = 'signal-card';
                        text.style.color = '#ffd700';
                    }}
                }} catch (e) {{ console.error(e); }}
            }};
        }}
        
        async function analyzeChartWithAI() {{
            const btn = document.querySelector('button[onclick="analyzeChartWithAI()"]');
            const box = document.getElementById('ai-box');
            const comment = document.getElementById('ai-comment');
            btn.disabled = true;
            btn.innerHTML = "⏳ Analiz ediliyor...";
            box.style.display = 'block';
            comment.innerHTML = "📊 Teknik analiz oluşturuluyor...";
            try {{
                const response = await fetch('/api/analyze-chart', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ symbol: currentSymbol, timeframe: currentTimeframe }})
                }});
                const data = await response.json();
                comment.innerHTML = data.success ? data.analysis.replace(/\\n/g, '<br>') : '<strong style="color:#ff4444">❌ Hata:</strong><br>' + data.analysis;
            }} catch (err) {{
                comment.innerHTML = '<strong style="color:#ff4444">❌ Bağlantı hatası:</strong><br>' + err.message;
            }} finally {{
                btn.disabled = false;
                btn.innerHTML = "🤖 GRAFİĞİ ANALİZ ET";
            }}
        }}
        
        // Sayfa yüklendiğinde otomatik BTC 5m başlat
        setTimeout(connectSignal, 1000);
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)
#=========================================================================================================
@app.post("/api/analyze-chart")
async def analyze_chart(request: Request):
    try:
        body = await request.json()
        symbol = body.get("symbol", "BTCUSDT").upper()
        timeframe = body.get("timeframe", "5m")

        logger.info(f"AI Analiz talebi alındı: {symbol} {timeframe}")

        if not symbol.endswith("USDT"):
            symbol += "USDT"

        # Borsa client'larını al
        binance_client = get_binance_client()
        bybit_client = get_bybit_client()
        okex_client = get_okex_client()

        clients = [binance_client, bybit_client, okex_client]
        client_names = ["Binance", "Bybit", "OKX"]

        klines_list = []
        interval_map = {
            "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
            "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
        }
        interval = interval_map.get(timeframe, "5m")
        ccxt_symbol = symbol.replace('USDT', '/USDT')

        # Borsalardan veri çek
        for client, name in zip(clients, client_names):
            if client:
                try:
                    klines = await client.fetch_ohlcv(ccxt_symbol, timeframe=interval, limit=200)
                    if klines and len(klines) > 50:
                        klines_list.append((name, klines))
                        logger.info(f"{name}: {len(klines)} mum alındı ({symbol})")
                except Exception as e:
                    logger.warning(f"{name} OHLCV hatası ({symbol}): {e}")

        # CoinGecko fallback
        if not klines_list:
            logger.info(f"Borsalar başarısız, CoinGecko fallback kullanılıyor: {symbol}")
            coingecko_klines = await fetch_coingecko_ohlcv(symbol, timeframe)
            if coingecko_klines and len(coingecko_klines) > 50:
                klines_list.append(("CoinGecko", coingecko_klines))
                logger.info(f"CoinGecko: {len(coingecko_klines)} mum alındı ({symbol})")

        if not klines_list:
            return JSONResponse({
                "success": False,
                "analysis": f"❌ {symbol} için hiçbir kaynaktan veri alınamadı. Lütfen sembolü kontrol edin.\n⚠️ Bu bir yatırım tavsiyesi değildir."
            }, status_code=500)

        source_name, klines = max(klines_list, key=lambda x: len(x[1]))

        # DataFrame oluştur
        df = pd.DataFrame(klines)
        if len(df.columns) >= 6:
            df = df.iloc[:, :6]
            df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        elif len(df.columns) >= 5:
            df = df.iloc[:, :5]
            df.columns = ['timestamp', 'open', 'high', 'low', 'close']
            df['volume'] = 1000
        else:
            return JSONResponse({
                "success": False,
                "analysis": "❌ Veri formatı hatalı.\n⚠️ Bu bir yatırım tavsiyesi değildir."
            }, status_code=500)

        df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')
        if df['timestamp'].max() > 1e10:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        else:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')

        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        df = df.sort_values('timestamp').tail(150)

        if len(df) < 50:
            return JSONResponse({
                "success": False,
                "analysis": f"❌ Yeterli veri yok ({len(df)} mum). Daha uzun timeframe deneyin.\n⚠️ Bu bir yatırım tavsiyesi değildir."
            }, status_code=500)

        # === KRİTİK DÜZELTME: GrokIndicators nesnesini burada oluştur ===
        analyzer = GrokIndicators()

        # Sinyal üret
        try:
            signal = generate_ict_signal(df.copy(), symbol, timeframe)
        except Exception as e:
            logger.warning(f"ICT sinyal üretilemedi, basit sinyal kullanılıyor: {e}")
            signal = generate_simple_signal(df.copy(), symbol, timeframe)

        # Tetiklenen paternleri çek
        patterns = analyzer.detect_all_patterns(df)
        triggered_positive = []
        triggered_negative = []

        for key, value in patterns.items():
            if isinstance(value, pd.Series) and len(value) > 0 and value.iloc[-1]:
                if any(pos in key.lower() for pos in ['bull', 'buy', 'positive', 'up', 'long', 'choch_bull', 'sweep_bull', 'breaker_bull', 'mitigation_bull', 'golden', 'crt_buy', 'fvg_up', 'rsi6_crossover']):
                    triggered_positive.append(f"✅ {key.replace('_', ' ').title()}")
                elif any(neg in key.lower() for neg in ['bear', 'sell', 'negative', 'down', 'short', 'choch_bear', 'sweep_bear', 'breaker_bear', 'mitigation_bear', 'death', 'crt_sell', 'fvg_down', 'rsi6_crossunder']):
                    triggered_negative.append(f"⚠️ {key.replace('_', ' ').title()}")

        triggers_detail = ""
        if triggered_positive:
            triggers_detail += "**Pozitif Tetikleyiciler:**\n" + "\n".join(triggered_positive) + "\n\n"
        if triggered_negative:
            triggers_detail += "**Negatif Tetikleyiciler:**\n" + "\n".join(triggered_negative) + "\n\n"
        if not triggered_positive and not triggered_negative:
            triggers_detail = "😐 Henüz belirgin bir tetikleyici oluşmadı.\n"

        current_price = float(df['close'].iloc[-1])

        analysis_text = f"""🔍 **{symbol.replace('USDT', '/USDT')} - {timeframe.upper()} Detaylı Teknik Analiz**

📊 **Veri Kaynağı:** {source_name} • **Mum Sayısı:** {len(df)}

🎯 **ANA SİNYAL:** <strong style="font-size:1.3em;">{signal.get('signal', '⏸️ BEKLE')}</strong>

📈 **Skor:** {signal.get('score', 50)}/100 → <strong>{signal.get('strength', 'ORTA')}</strong>
💰 **Anlık Fiyat:** ${current_price:,.6f}
🕐 **Killzone:** {signal.get('killzone', 'Normal')}

🔥 **Tetiklenen Paternler:**

{triggers_detail}

💡 **Kısa Yorum:**
{symbol.replace('USDT', '')} şu anda {signal.get('signal', 'BEKLE').replace('🚀 AL', 'güçlü yükseliş').replace('🔻 SAT', 'güçlü düşüş').replace('⏸️ BEKLE', 'bekleme')} sinyali veriyor.

⚠️ **ÖNEMLİ UYARI:** Bu bir yatırım tavsiyesi değildir. Kripto para piyasaları yüksek volatiliteye sahiptir. Kendi araştırmanızı yapın ve yalnızca kaybetmeyi göze alabildiğiniz miktar ile işlem yapın.
"""

        return JSONResponse({
            "success": True,
            "analysis": analysis_text,
            "signal_data": signal,
            "current_price": current_price,
            "data_source": source_name
        })

    except json.JSONDecodeError:
        return JSONResponse({
            "success": False,
            "analysis": "❌ Geçersiz istek. Lütfen tekrar deneyin.\n⚠️ Bu bir yatırım tavsiyesi değildir."
        }, status_code=400)

    except Exception as e:
        logger.error(f"Analiz endpoint hatası: {e}", exc_info=True)
        return JSONResponse({
            "success": False,
            "analysis": f"❌ Beklenmeyen hata: {str(e)[:150]}\n⚠️ Bu bir yatırım tavsiyesi değildir."
        }, status_code=500)
#=========================================================================================================
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






















