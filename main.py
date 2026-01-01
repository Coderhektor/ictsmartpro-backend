"""
ICT SMART PRO - VERSION 6.1
Grafik Analiz Özellikli Tam Sürüm
"""

import base64
import logging
import asyncio
import json
import hashlib
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional, Dict, List, Set, Any
from collections import defaultdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from openai import OpenAI

# Core modülleri
try:
    from core import (
        initialize, cleanup, single_subscribers, all_subscribers, pump_radar_subscribers,
        shared_signals, active_strong_signals, top_gainers, last_update, rt_ticker,
        get_binance_client, price_sources_status, price_pool, get_all_prices_snapshot
    )
    from utils import all_usdt_symbols
except ImportError as e:
    logging.error(f"Core modülleri import hatası: {e}")
    # Fallback fonksiyonlar
    initialize = lambda: asyncio.sleep(0)
    cleanup = lambda: asyncio.sleep(0)
    single_subscribers = defaultdict(set)
    all_subscribers = defaultdict(set)
    pump_radar_subscribers = set()
    shared_signals = {}
    active_strong_signals = {}
    top_gainers = []
    last_update = ""
    rt_ticker = ""
    get_binance_client = lambda: None
    price_sources_status = {}
    price_pool = {}
    get_all_prices_snapshot = lambda: {}
    all_usdt_symbols = []

# OpenAI
openai_client = None
if os.getenv("OPENAI_API_KEY"):
    try:
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    except:
        pass

# Logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ict_smart_pro.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ict_smart_pro")

# ==================== VISITOR COUNTER ====================

class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users = set()
        self.daily_stats = defaultdict(lambda: {"visits": 0, "unique": set()})
        self.page_views = defaultdict(int)
        self.user_agents = defaultdict(int)
        self.referrers = defaultdict(int)

    def add_visit(self, page: str, user_id: Optional[str] = None, 
                  user_agent: Optional[str] = None, referrer: Optional[str] = None) -> int:
        self.total_visits += 1
        self.page_views[page] += 1
        
        if user_agent:
            self.user_agents[user_agent[:100]] += 1
            
        if referrer:
            self.referrers[referrer[:200]] += 1
            
        today = datetime.now().strftime("%Y-%m-%d")
        self.daily_stats[today]["visits"] += 1
        
        if user_id:
            self.active_users.add(user_id)
            self.daily_stats[today]["unique"].add(user_id)
            
        return self.total_visits

    def get_stats(self) -> Dict[str, Any]:
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = self.daily_stats.get(today, {"visits": 0, "unique": set()})
        
        # En popüler sayfalar
        top_pages = sorted(self.page_views.items(), key=lambda x: x[1], reverse=True)[:10]
        
        return {
            "total_visits": self.total_visits,
            "active_users": len(self.active_users),
            "today_visits": today_stats["visits"],
            "today_unique": len(today_stats["unique"]),
            "page_views": dict(self.page_views),
            "top_pages": dict(top_pages),
            "last_updated": datetime.now().strftime("%H:%M:%S"),
            "user_agents_count": len(self.user_agents),
            "referrers_count": len(self.referrers)
        }

visitor_counter = VisitorCounter()

def get_visitor_stats_html() -> str:
    stats = visitor_counter.get_stats()
    return f"""
    <div style="position:fixed;top:15px;right:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:clamp(0.8rem, 2vw, 1.2rem);z-index:1000;backdrop-filter:blur(10px);border:1px solid #00ff8844;">
        <div>👁️ Toplam: <strong>{stats['total_visits']}</strong></div>
        <div>🔥 Bugün: <strong>{stats['today_visits']}</strong></div>
        <div>👥 Aktif: <strong>{stats['active_users']}</strong></div>
    </div>
    """

# ==================== GLOBAL STATE ====================

price_sources_subscribers = set()
signal_history = defaultdict(list)  # Sinyal geçmişi tutmak için

# ==================== TEKNİK ANALİZ FONKSİYONLARI ====================

def calculate_rsi(prices, period=14):
    """RSI hesaplama fonksiyonu"""
    if len(prices) < period + 1:
        return 50
    
    deltas = prices.diff()
    gain = (deltas.where(deltas > 0, 0)).rolling(window=period).mean()
    loss = (-deltas.where(deltas < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50

def calculate_macd(prices, fast=12, slow=26, signal=9):
    """MACD hesaplama fonksiyonu"""
    if len(prices) < slow + signal:
        return {"macd": 0, "signal": 0, "histogram": 0, "trend": "NÖTR"}
    
    exp1 = prices.ewm(span=fast, adjust=False).mean()
    exp2 = prices.ewm(span=slow, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    
    macd_value = macd_line.iloc[-1]
    signal_value = signal_line.iloc[-1]
    hist_value = histogram.iloc[-1]
    
    if hist_value > 0:
        trend = "YÜKSELİŞ"
    elif hist_value < 0:
        trend = "DÜŞÜŞ"
    else:
        trend = "NÖTR"
    
    return {
        "macd": macd_value,
        "signal": signal_value,
        "histogram": hist_value,
        "trend": trend
    }

def calculate_bollinger_bands(prices, period=20, std_dev=2):
    """Bollinger Bantları hesaplama"""
    if len(prices) < period:
        return {"upper": prices.iloc[-1], "middle": prices.iloc[-1], "lower": prices.iloc[-1]}
    
    middle = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    
    return {
        "upper": upper.iloc[-1],
        "middle": middle.iloc[-1],
        "lower": lower.iloc[-1]
    }

def analyze_price_action(df):
    """Fiyat hareketi analizi"""
    if len(df) < 3:
        return {"trend": "NÖTR", "momentum": 0, "volatility": 0}
    
    # Son 3 mumun kapanış fiyatları
    closes = df['close'].tail(3).values
    
    # Trend belirleme
    if closes[2] > closes[1] > closes[0]:
        trend = "YÜKSELİŞ"
        momentum = 1
    elif closes[2] < closes[1] < closes[0]:
        trend = "DÜŞÜŞ"
        momentum = -1
    else:
        trend = "YATAY"
        momentum = 0
    
    # Volatilite
    highs = df['high'].tail(10)
    lows = df['low'].tail(10)
    volatility = ((highs.max() - lows.min()) / lows.min() * 100) if lows.min() > 0 else 0
    
    # Mum formasyonları
    last_candle = df.iloc[-1]
    prev_candle = df.iloc[-2]
    
    # Yeşil mum (yükseliş)
    is_green = last_candle['close'] > last_candle['open']
    # Kırmızı mum (düşüş)
    is_red = last_candle['close'] < last_candle['open']
    
    # Uzun gövde
    body_size = abs(last_candle['close'] - last_candle['open'])
    avg_body = abs(df['close'] - df['open']).tail(20).mean()
    is_long_body = body_size > avg_body * 1.5
    
    # Üst gölge
    upper_shadow = last_candle['high'] - max(last_candle['close'], last_candle['open'])
    # Alt gölge
    lower_shadow = min(last_candle['close'], last_candle['open']) - last_candle['low']
    
    return {
        "trend": trend,
        "momentum": momentum,
        "volatility": round(volatility, 2),
        "is_green": is_green,
        "is_red": is_red,
        "is_long_body": is_long_body,
        "upper_shadow": upper_shadow,
        "lower_shadow": lower_shadow,
        "body_size": body_size
    }

def generate_technical_analysis(df, symbol, timeframe):
    """Detaylı teknik analiz üretimi"""
    if len(df) < 50:
        return None
    
    try:
        # Fiyat verileri
        current_price = float(df['close'].iloc[-1])
        prev_price = float(df['close'].iloc[-2])
        change_pct = ((current_price - prev_price) / prev_price * 100) if prev_price > 0 else 0
        
        # Hacim analizi
        volume = float(df['volume'].iloc[-1])
        avg_volume = float(df['volume'].tail(20).mean())
        volume_ratio = volume / avg_volume if avg_volume > 0 else 1
        
        # Teknik göstergeler
        rsi_value = calculate_rsi(df['close'])
        macd_data = calculate_macd(df['close'])
        bb_data = calculate_bollinger_bands(df['close'])
        price_action = analyze_price_action(df)
        
        # Hareketli ortalamalar
        ma20 = df['close'].rolling(window=20).mean().iloc[-1]
        ma50 = df['close'].rolling(window=50).mean().iloc[-1]
        ma100 = df['close'].rolling(window=100).mean().iloc[-1] if len(df) >= 100 else current_price
        
        # Trend analizi
        if current_price > ma20 > ma50:
            trend_strength = "GÜÇLÜ YÜKSELİŞ"
            trend_score = 80
        elif current_price < ma20 < ma50:
            trend_strength = "GÜÇLÜ DÜŞÜŞ"
            trend_score = 20
        elif current_price > ma20 and ma20 > ma50:
            trend_strength = "YÜKSELİŞ"
            trend_score = 70
        elif current_price < ma20 and ma20 < ma50:
            trend_strength = "DÜŞÜŞ"
            trend_score = 30
        else:
            trend_strength = "YATAY"
            trend_score = 50
        
        # Sinyal oluşturma
        signals = []
        score = trend_score
        
        # RSI sinyalleri
        if rsi_value > 70:
            signals.append("RSI Aşırı Alım")
            score -= 15
        elif rsi_value < 30:
            signals.append("RSI Aşırı Satım")
            score += 15
        elif rsi_value > 60:
            signals.append("RSI Alım Bölgesi")
            score += 5
        elif rsi_value < 40:
            signals.append("RSI Satım Bölgesi")
            score -= 5
        
        # MACD sinyalleri
        if macd_data['trend'] == "YÜKSELİŞ":
            signals.append("MACD Yükseliş Trendi")
            score += 10
        elif macd_data['trend'] == "DÜŞÜŞ":
            signals.append("MACD Düşüş Trendi")
            score -= 10
        
        # Bollinger Bantları
        if current_price > bb_data['upper']:
            signals.append("Üst Bollinger Bandının Üzerinde")
            score -= 10
        elif current_price < bb_data['lower']:
            signals.append("Alt Bollinger Bandının Altında")
            score += 10
        
        # Hacim analizi
        if volume_ratio > 1.5:
            signals.append(f"Hacim Artışı ({volume_ratio:.1f}x)")
            score += 5
        elif volume_ratio < 0.5:
            signals.append(f"Hacim Düşüşü ({volume_ratio:.1f}x)")
            score -= 5
        
        # Fiyat hareketi
        if price_action['is_long_body']:
            if price_action['is_green']:
                signals.append("Güçlü Yükseliş Mumu")
                score += 8
            elif price_action['is_red']:
                signals.append("Güçlü Düşüş Mumu")
                score -= 8
        
        # Sonuç sinyali
        score = max(10, min(95, score))
        
        if score >= 70:
            signal_type = "🚀 GÜÇLÜ ALIM"
            strength = "ÇOK YÜKSEK"
            color = "green"
        elif score >= 60:
            signal_type = "📈 ALIM"
            strength = "YÜKSEK"
            color = "lightgreen"
        elif score <= 30:
            signal_type = "🔥 GÜÇLÜ SATIM"
            strength = "ÇOK YÜKSEK"
            color = "red"
        elif score <= 40:
            signal_type = "📉 SATIM"
            strength = "YÜKSEK"
            color = "lightcoral"
        else:
            signal_type = "⏸️ NÖTR"
            strength = "ORTA"
            color = "gold"
        
        # Killzone belirleme
        now_utc = datetime.utcnow()
        hour = now_utc.hour
        
        if 7 <= hour < 11:  # 07:00-11:00 UTC
            killzone = "LONDRA AÇILIŞI"
        elif 12 <= hour < 16:  # 12:00-16:00 UTC
            killzone = "NEW YORK AÇILIŞI"
        elif 22 <= hour or hour < 2:  # 22:00-02:00 UTC
            killzone = "ASYA SEANSI"
        else:
            killzone = "NORMAL SEANS"
        
        # Destek/Direnç seviyeleri
        recent_high = df['high'].tail(50).max()
        recent_low = df['low'].tail(50).min()
        
        # Pivot noktaları
        pivot = (df['high'].iloc[-1] + df['low'].iloc[-1] + df['close'].iloc[-1]) / 3
        r1 = 2 * pivot - df['low'].iloc[-1]
        s1 = 2 * pivot - df['high'].iloc[-1]
        
        result = {
            "pair": f"{symbol}/USDT",
            "timeframe": timeframe.upper(),
            "current_price": round(current_price, 6 if current_price < 1 else 4),
            "signal": signal_type,
            "score": int(score),
            "strength": strength,
            "color": color,
            "killzone": killzone,
            "change_24h": round(change_pct, 2),
            "volume_ratio": round(volume_ratio, 2),
            "rsi": round(rsi_value, 1),
            "macd_trend": macd_data['trend'],
            "trend": trend_strength,
            "ma20": round(ma20, 6 if ma20 < 1 else 4),
            "ma50": round(ma50, 6 if ma50 < 1 else 4),
            "support": round(recent_low, 6 if recent_low < 1 else 4),
            "resistance": round(recent_high, 6 if recent_high < 1 else 4),
            "pivot": round(pivot, 6 if pivot < 1 else 4),
            "r1": round(r1, 6 if r1 < 1 else 4),
            "s1": round(s1, 6 if s1 < 1 else 4),
            "triggers": " | ".join(signals) if signals else "Belirgin sinyal yok",
            "analysis_time": now_utc.strftime("%H:%M:%S UTC"),
            "timestamp": datetime.now().isoformat()
        }
        
        # Sinyal geçmişine ekle
        signal_key = f"{symbol}:{timeframe}"
        signal_history[signal_key].append(result)
        # Son 10 sinyali tut
        if len(signal_history[signal_key]) > 10:
            signal_history[signal_key] = signal_history[signal_key][-10:]
        
        return result
        
    except Exception as e:
        logger.error(f"Teknik analiz hatası: {e}")
        return None

# ==================== LIFESPAN ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 ICT SMART PRO başlatılıyor...")
    try:
        await initialize()
        logger.info("✅ Uygulama başarıyla başlatıldı")
    except Exception as e:
        logger.error(f"❌ Başlatma hatası: {e}")
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    try:
        await cleanup()
    except Exception as e:
        logger.error(f"❌ Kapatma hatası: {e}")

# ==================== FASTAPI APP ====================

app = FastAPI(
    lifespan=lifespan,
    title="ICT SMART PRO",
    version="6.1",
    description="Gelişmiş Kripto Sinyal ve Analiz Platformu",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# ==================== MIDDLEWARE ====================

@app.middleware("http")
async def count_visitors_middleware(request: Request, call_next):
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        ip = request.client.host or "anonymous"
        visitor_id = hashlib.md5(f"{ip}{datetime.now().strftime('%Y%m%d')}".encode()).hexdigest()[:12]
    
    page = request.url.path
    user_agent = request.headers.get("user-agent", "")
    referrer = request.headers.get("referer", "")
    
    visitor_counter.add_visit(page, visitor_id, user_agent, referrer)
    
    response = await call_next(request)
    
    if not request.cookies.get("visitor_id"):
        response.set_cookie(
            key="visitor_id", 
            value=visitor_id, 
            max_age=86400 * 30,  # 30 gün
            httponly=True, 
            samesite="lax",
            secure=request.url.scheme == "https"
        )
    
    return response

# ==================== WEBSOCKET ENDPOINTS ====================

@app.websocket("/ws/price_sources")
async def websocket_price_sources(websocket: WebSocket):
    await websocket.accept()
    price_sources_subscribers.add(websocket)
    try:
        while True:
            try:
                await websocket.send_json({
                    "sources": price_sources_status, 
                    "total_symbols": len(price_pool),
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Price sources send error: {e}")
                break
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Price sources error: {e}")
    finally:
        price_sources_subscribers.discard(websocket)

@app.websocket("/ws/signal/{pair}/{timeframe}")
async def websocket_signal(websocket: WebSocket, pair: str, timeframe: str):
    await websocket.accept()
    symbol = pair.upper().replace("/", "").replace("-", "").strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    channel = f"{symbol}:{timeframe}"
    single_subscribers[channel].add(websocket)
    
    # Mevcut sinyali gönder
    sig = shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        await websocket.send_json(sig)
    else:
        # Eğer shared_signals'da yoksa, teknik analiz yap
        try:
            binance_client = get_binance_client()
            if binance_client:
                ccxt_symbol = f"{symbol}/USDT"
                interval_map = {"1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"4h","1d":"1d","1w":"1w"}
                ccxt_timeframe = interval_map.get(timeframe, "5m")
                
                klines = await binance_client.fetch_ohlcv(ccxt_symbol, timeframe=ccxt_timeframe, limit=100)
                if klines and len(klines) >= 50:
                    df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume'])
                    df.iloc[:,1:] = df.iloc[:,1:].apply(pd.to_numeric, errors='coerce')
                    df = df.dropna()
                    
                    analysis = generate_technical_analysis(df, symbol, timeframe)
                    if analysis:
                        await websocket.send_json(analysis)
        except Exception as e:
            logger.error(f"Initial signal error: {e}")
    
    try:
        heartbeat_count = 0
        while True:
            await asyncio.sleep(15)
            heartbeat_count += 1
            
            # Her 4. heartbeat'te (1 dakikada bir) sinyal güncelle
            if heartbeat_count % 4 == 0:
                sig = shared_signals.get(timeframe, {}).get(symbol)
                if sig:
                    await websocket.send_json(sig)
            else:
                await websocket.send_json({"heartbeat": True, "timestamp": datetime.now().isoformat()})
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Signal WebSocket error: {e}")
    finally:
        single_subscribers[channel].discard(websocket)

@app.websocket("/ws/all/{timeframe}")
async def websocket_all_signals(websocket: WebSocket, timeframe: str):
    supported = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
    if timeframe not in supported:
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    all_subscribers[timeframe].add(websocket)
    
    # Başlangıç sinyallerini gönder
    initial_signals = active_strong_signals.get(timeframe, [])
    await websocket.send_json(initial_signals)
    
    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({
                "ping": True, 
                "timestamp": datetime.now().isoformat(),
                "signal_count": len(active_strong_signals.get(timeframe, []))
            })
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"All signals WebSocket error: {e}")
    finally:
        all_subscribers[timeframe].discard(websocket)

@app.websocket("/ws/pump_radar")
async def websocket_pump_radar(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    
    # Başlangıç verilerini gönder
    await websocket.send_json({
        "top_gainers": top_gainers, 
        "last_update": last_update,
        "total_coins": len(top_gainers)
    })
    
    try:
        while True:
            await asyncio.sleep(20)
            await websocket.send_json({
                "ping": True,
                "timestamp": datetime.now().isoformat()
            })
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Pump radar WebSocket error: {e}")
    finally:
        pump_radar_subscribers.discard(websocket)

# ==================== HTML PAGES ====================

@app.get("/")
async def home_page(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    visitor_stats = get_visitor_stats_html()
    
    # Sistem durumu kontrolü
    system_status = "🟢 ÇALIŞIYOR"
    binance_status = "🟢 BAĞLI" if get_binance_client() else "🔴 BAĞLANTI YOK"
    sources_healthy = sum(1 for v in price_sources_status.values() if v.get("healthy", False)) if price_sources_status else 0
    total_sources = len(price_sources_status) if price_sources_status else 0
    
    html = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>ICT SMART PRO v6.1 - Ana Sayfa</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                background: linear-gradient(135deg, #0a0022, #1a0033, #000000);
                color: #ffffff;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                min-height: 100vh;
                position: relative;
                overflow-x: hidden;
            }}
            
            body::before {{
                content: '';
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: 
                    radial-gradient(circle at 20% 30%, rgba(120, 0, 255, 0.1) 0%, transparent 50%),
                    radial-gradient(circle at 80% 70%, rgba(0, 219, 222, 0.1) 0%, transparent 50%),
                    radial-gradient(circle at 40% 80%, rgba(255, 0, 255, 0.1) 0%, transparent 50%);
                z-index: -1;
            }}
            
            .container {{
                max-width: 1400px;
                margin: 0 auto;
                padding: 20px;
                position: relative;
                z-index: 1;
            }}
            
            .header {{
                text-align: center;
                padding: 40px 20px;
                margin-bottom: 30px;
                position: relative;
            }}
            
            .title {{
                font-size: clamp(2.5rem, 5vw, 4rem);
                font-weight: 800;
                background: linear-gradient(90deg, #00dbde, #fc00ff, #00ffff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                margin-bottom: 20px;
                text-shadow: 0 5px 15px rgba(0, 219, 222, 0.3);
                animation: glow 3s ease-in-out infinite alternate;
            }}
            
            @keyframes glow {{
                from {{ text-shadow: 0 0 20px rgba(0, 219, 222, 0.5); }}
                to {{ text-shadow: 0 0 30px rgba(252, 0, 255, 0.5), 0 0 40px rgba(0, 219, 222, 0.5); }}
            }}
            
            .subtitle {{
                font-size: 1.2rem;
                color: #a0a0ff;
                margin-bottom: 30px;
                max-width: 800px;
                margin-left: auto;
                margin-right: auto;
                line-height: 1.6;
            }}
            
            .system-status {{
                display: flex;
                justify-content: center;
                gap: 20px;
                flex-wrap: wrap;
                margin: 30px 0;
                padding: 20px;
                background: rgba(255, 255, 255, 0.05);
                border-radius: 15px;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.1);
            }}
            
            .status-item {{
                display: flex;
                align-items: center;
                gap: 10px;
                padding: 10px 20px;
                background: rgba(0, 0, 0, 0.3);
                border-radius: 10px;
                border-left: 4px solid #00ff88;
            }}
            
            .status-item.warning {{
                border-left-color: #ffaa00;
            }}
            
            .status-item.error {{
                border-left-color: #ff4444;
            }}
            
            .pump-radar-container {{
                background: rgba(255, 255, 255, 0.05);
                border-radius: 20px;
                padding: 30px;
                margin: 40px 0;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.1);
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
                transition: transform 0.3s ease;
            }}
            
            .pump-radar-container:hover {{
                transform: translateY(-5px);
                box-shadow: 0 15px 40px rgba(0, 0, 0, 0.4);
            }}
            
            .pump-radar-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 25px;
                padding-bottom: 15px;
                border-bottom: 2px solid rgba(0, 219, 222, 0.3);
            }}
            
            .pump-radar-title {{
                font-size: 1.8rem;
                font-weight: 700;
                color: #00ffff;
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            
            .update-info {{
                color: #a0a0ff;
                font-size: 1rem;
                background: rgba(0, 0, 0, 0.3);
                padding: 8px 15px;
                border-radius: 20px;
                border: 1px solid rgba(0, 219, 222, 0.2);
            }}
            
            table {{
                width: 100%;
                border-collapse: separate;
                border-spacing: 0;
                margin: 20px 0;
            }}
            
            th {{
                background: linear-gradient(135deg, rgba(0, 219, 222, 0.2), rgba(252, 0, 255, 0.2));
                padding: 18px 15px;
                text-align: left;
                color: #00ffff;
                font-weight: 600;
                border-bottom: 2px solid rgba(0, 219, 222, 0.3);
                position: sticky;
                top: 0;
                backdrop-filter: blur(10px);
            }}
            
            td {{
                padding: 16px 15px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                transition: background-color 0.3s ease;
            }}
            
            tr:hover td {{
                background: rgba(255, 255, 255, 0.08);
            }}
            
            .change-positive {{
                color: #00ff88;
                font-weight: bold;
                background: rgba(0, 255, 136, 0.1);
                padding: 4px 12px;
                border-radius: 12px;
                display: inline-block;
            }}
            
            .change-negative {{
                color: #ff4444;
                font-weight: bold;
                background: rgba(255, 68, 68, 0.1);
                padding: 4px 12px;
                border-radius: 12px;
                display: inline-block;
            }}
            
            .buttons-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 25px;
                margin: 50px 0;
            }}
            
            .btn {{
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 35px 25px;
                background: linear-gradient(135deg, rgba(252, 0, 255, 0.1), rgba(0, 219, 222, 0.1));
                color: white;
                text-decoration: none;
                border-radius: 20px;
                text-align: center;
                transition: all 0.3s ease;
                border: 1px solid rgba(255, 255, 255, 0.1);
                backdrop-filter: blur(10px);
                position: relative;
                overflow: hidden;
            }}
            
            .btn::before {{
                content: '';
                position: absolute;
                top: 0;
                left: -100%;
                width: 100%;
                height: 100%;
                background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
                transition: left 0.5s ease;
            }}
            
            .btn:hover::before {{
                left: 100%;
            }}
            
            .btn:hover {{
                transform: translateY(-8px) scale(1.02);
                box-shadow: 0 20px 40px rgba(252, 0, 255, 0.3);
                border-color: rgba(0, 219, 222, 0.5);
            }}
            
            .btn-icon {{
                font-size: 2.5rem;
                margin-bottom: 15px;
            }}
            
            .btn-title {{
                font-size: 1.5rem;
                font-weight: 700;
                margin-bottom: 10px;
                background: linear-gradient(90deg, #00dbde, #fc00ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
            }}
            
            .btn-description {{
                font-size: 1rem;
                color: #a0a0ff;
                line-height: 1.5;
            }}
            
            .user-info {{
                position: fixed;
                top: 15px;
                left: 15px;
                background: rgba(0, 0, 0, 0.7);
                padding: 12px 24px;
                border-radius: 15px;
                color: #00ff88;
                font-weight: 600;
                z-index: 1000;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(0, 255, 136, 0.3);
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.3);
            }}
            
            .loading {{
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 60px 20px;
            }}
            
            .spinner {{
                width: 50px;
                height: 50px;
                border: 4px solid rgba(0, 219, 222, 0.3);
                border-top: 4px solid #00dbde;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin-bottom: 20px;
            }}
            
            @keyframes spin {{
                0% {{ transform: rotate(0deg); }}
                100% {{ transform: rotate(360deg); }}
            }}
            
            .footer {{
                text-align: center;
                margin-top: 60px;
                padding-top: 30px;
                border-top: 1px solid rgba(255, 255, 255, 0.1);
                color: #888;
                font-size: 0.9rem;
            }}
            
            .version {{
                color: #00dbde;
                font-weight: bold;
                margin-top: 10px;
            }}
            
            @media (max-width: 768px) {{
                .container {{
                    padding: 15px;
                }}
                
                .header {{
                    padding: 20px 15px;
                }}
                
                .title {{
                    font-size: 2.2rem;
                }}
                
                .buttons-grid {{
                    grid-template-columns: 1fr;
                    gap: 20px;
                }}
                
                .btn {{
                    padding: 25px 20px;
                }}
                
                .pump-radar-container {{
                    padding: 20px;
                }}
                
                table {{
                    font-size: 0.9rem;
                }}
                
                th, td {{
                    padding: 12px 8px;
                }}
            }}
            
            @media (max-width: 480px) {{
                .title {{
                    font-size: 1.8rem;
                }}
                
                .system-status {{
                    flex-direction: column;
                    align-items: flex-start;
                }}
                
                .pump-radar-header {{
                    flex-direction: column;
                    gap: 15px;
                    align-items: flex-start;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="user-info">👤 Hoş geldin, {user}</div>
        {visitor_stats}
        
        <div class="container">
            <div class="header">
                <h1 class="title">ICT SMART PRO</h1>
                <p class="subtitle">Gerçek zamanlı kripto sinyalleri, teknik analiz ve pump radar ile akıllı yatırım kararları alın.</p>
                
                <div class="system-status">
                    <div class="status-item">
                        <span>Sistem:</span>
                        <strong>{system_status}</strong>
                    </div>
                    <div class="status-item">
                        <span>Binance:</span>
                        <strong>{binance_status}</strong>
                    </div>
                    <div class="status-item">
                        <span>Fiyat Kaynakları:</span>
                        <strong>{sources_healthy}/{total_sources} Aktif</strong>
                    </div>
                </div>
            </div>
            
            <div class="pump-radar-container">
                <div class="pump-radar-header">
                    <h2 class="pump-radar-title">
                        <span>🚀 PUMP RADAR</span>
                    </h2>
                    <div class="update-info" id="update-info">
                        📡 Gerçek veriler yükleniyor...
                    </div>
                </div>
                
                <div style="overflow-x: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>SIRA</th>
                                <th>COİN</th>
                                <th>FİYAT</th>
                                <th>24S DEĞİŞİM</th>
                                <th>HACİM</th>
                            </tr>
                        </thead>
                        <tbody id="pump-table">
                            <tr>
                                <td colspan="5" style="text-align: center; padding: 50px;">
                                    <div class="loading">
                                        <div class="spinner"></div>
                                        <div>Pump radar verileri yükleniyor...</div>
                                    </div>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
            
            <div class="buttons-grid">
                <a href="/signal" class="btn">
                    <div class="btn-icon">📊</div>
                    <div class="btn-title">Tek Coin Sinyal + Grafik</div>
                    <div class="btn-description">Herhangi bir coin için canlı sinyal alın, TradingView grafiği ile analiz yapın ve AI destekli teknik analiz raporu alın.</div>
                </a>
                
                <a href="/signal/all" class="btn">
                    <div class="btn-icon">🔥</div>
                    <div class="btn-title">Tüm Coinleri Tara</div>
                    <div class="btn-description">Tüm kripto paraları tara, güçlü sinyalleri filtrele ve en iyi fırsatları anında görüntüle.</div>
                </a>
                
                <a href="/debug/sources" class="btn">
                    <div class="btn-icon">🔧</div>
                    <div class="btn-title">Sistem Durumu</div>
                    <div class="btn-description">Fiyat kaynakları, bağlantı durumu ve sistem performansını gerçek zamanlı takip edin.</div>
                </a>
                
                <a href="/admin/visitor-dashboard" class="btn">
                    <div class="btn-icon">📈</div>
                    <div class="btn-title">İstatistikler</div>
                    <div class="btn-description">Ziyaretçi istatistikleri, kullanım verileri ve platform performans metrikleri.</div>
                </a>
            </div>
            
            <div class="footer">
                <p>© 2024 ICT SMART PRO - Tüm hakları saklıdır.</p>
                <p class="version">Sürüm 6.1 - Realtime AI Analytics</p>
            </div>
        </div>
        
        <script>
            const ws = new WebSocket((window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws/pump_radar');
            
            ws.onopen = function() {{
                document.getElementById('update-info').innerHTML = '✅ Gerçek veri bağlantısı kuruldu';
            }};
            
            ws.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    if (data.ping) return;
                    
                    if (data.last_update) {{
                        document.getElementById('update-info').innerHTML = '🔄 Son güncelleme: ' + data.last_update;
                    }}
                    
                    const table = document.getElementById('pump-table');
                    if (!data.top_gainers || data.top_gainers.length === 0) {{
                        table.innerHTML = `
                            <tr>
                                <td colspan="5" style="text-align: center; padding: 50px; color: #ffd700;">
                                    📊 Şu anda aktif pump hareketi yok
                                </td>
                            </tr>
                        `;
                        return;
                    }}
                    
                    let html = '';
                    data.top_gainers.slice(0, 15).forEach(function(coin, index) {{
                        const changeClass = coin.change > 0 ? 'change-positive' : 'change-negative';
                        const changeSign = coin.change > 0 ? '+' : '';
                        const rankClass = index < 3 ? 'rank-highlight' : '';
                        
                        html += `
                            <tr>
                                <td><strong>#${{index + 1}}</strong></td>
                                <td><strong>${{coin.symbol}}</strong></td>
                                <td>$${{formatPrice(coin.price)}}</td>
                                <td><span class="${{changeClass}}">${{changeSign}}${{coin.change.toFixed(2)}}%</span></td>
                                <td>$${{formatVolume(coin.volume || 0)}}</td>
                            </tr>
                        `;
                    }});
                    
                    table.innerHTML = html;
                    
                }} catch (error) {{
                    console.error('Hata:', error);
                    document.getElementById('update-info').innerHTML = '❌ Veri işleme hatası';
                }}
            }};
            
            ws.onerror = function() {{
                document.getElementById('update-info').innerHTML = '❌ Bağlantı hatası';
            }};
            
            ws.onclose = function() {{
                document.getElementById('update-info').innerHTML = '🔌 Bağlantı kesildi - Sayfayı yenileyin';
            }};
            
            function formatPrice(price) {{
                if (price >= 1000) {{
                    return price.toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
                }} else if (price >= 1) {{
                    return price.toLocaleString('en-US', {{ minimumFractionDigits: 3, maximumFractionDigits: 3 }});
                }} else {{
                    return price.toLocaleString('en-US', {{ minimumFractionDigits: 6, maximumFractionDigits: 8 }});
                }}
            }}
            
            function formatVolume(volume) {{
                if (volume >= 1000000000) {{
                    return (volume / 1000000000).toFixed(2) + 'B';
                }} else if (volume >= 1000000) {{
                    return (volume / 1000000).toFixed(2) + 'M';
                }} else if (volume >= 1000) {{
                    return (volume / 1000).toFixed(2) + 'K';
                }} else {{
                    return volume.toFixed(2);
                }}
            }}
            
            // Sayfa yenileme butonu
            document.addEventListener('keydown', function(e) {{
                if (e.ctrlKey && e.key === 'r') {{
                    e.preventDefault();
                    location.reload();
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)

@app.get("/signal")
async def signal_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    visitor_stats = get_visitor_stats_html()
    
    html = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Tek Coin Sinyal + AI Analiz - ICT SMART PRO</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                background: linear-gradient(135deg, #0a0022, #1a0033, #000000);
                color: #ffffff;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                min-height: 100vh;
                position: relative;
                overflow-x: hidden;
            }}
            
            body::before {{
                content: '';
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: 
                    radial-gradient(circle at 20% 30%, rgba(120, 0, 255, 0.1) 0%, transparent 50%),
                    radial-gradient(circle at 80% 70%, rgba(0, 219, 222, 0.1) 0%, transparent 50%);
                z-index: -1;
            }}
            
            .container {{
                max-width: 1400px;
                margin: 0 auto;
                padding: 20px;
                position: relative;
                z-index: 1;
            }}
            
            .header {{
                text-align: center;
                padding: 30px 20px;
                margin-bottom: 30px;
            }}
            
            .title {{
                font-size: clamp(2rem, 4vw, 3rem);
                font-weight: 800;
                background: linear-gradient(90deg, #00dbde, #fc00ff, #00ffff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                margin-bottom: 15px;
                text-shadow: 0 5px 15px rgba(0, 219, 222, 0.3);
            }}
            
            .subtitle {{
                font-size: 1.1rem;
                color: #a0a0ff;
                max-width: 600px;
                margin: 0 auto 30px;
                line-height: 1.6;
            }}
            
            .user-info {{
                position: fixed;
                top: 15px;
                left: 15px;
                background: rgba(0, 0, 0, 0.7);
                padding: 12px 24px;
                border-radius: 15px;
                color: #00ff88;
                font-weight: 600;
                z-index: 1000;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(0, 255, 136, 0.3);
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.3);
            }}
            
            .controls-panel {{
                background: rgba(255, 255, 255, 0.05);
                border-radius: 20px;
                padding: 30px;
                margin-bottom: 30px;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.1);
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
            }}
            
            .input-group {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-bottom: 25px;
            }}
            
            .input-field {{
                display: flex;
                flex-direction: column;
                gap: 8px;
            }}
            
            .input-field label {{
                color: #00ffff;
                font-weight: 600;
                font-size: 0.95rem;
            }}
            
            input, select {{
                width: 100%;
                padding: 14px 18px;
                background: rgba(0, 0, 0, 0.4);
                border: 2px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
                color: white;
                font-size: 1rem;
                transition: all 0.3s ease;
            }}
            
            input:focus, select:focus {{
                outline: none;
                border-color: #00dbde;
                box-shadow: 0 0 0 3px rgba(0, 219, 222, 0.2);
            }}
            
            .button-group {{
                display: flex;
                gap: 15px;
                flex-wrap: wrap;
                justify-content: center;
                margin-top: 25px;
            }}
            
            .btn {{
                padding: 16px 32px;
                border: none;
                border-radius: 12px;
                font-size: 1.1rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 10px;
                min-width: 200px;
            }}
            
            .btn-primary {{
                background: linear-gradient(135deg, #fc00ff, #00dbde);
                color: white;
            }}
            
            .btn-primary:hover {{
                transform: translateY(-3px);
                box-shadow: 0 10px 25px rgba(252, 0, 255, 0.4);
            }}
            
            .btn-ai {{
                background: linear-gradient(135deg, #00dbde, #ff00ff, #00ffff);
                background-size: 200% 200%;
                animation: gradientShift 3s ease infinite;
                color: white;
            }}
            
            @keyframes gradientShift {{
                0% {{ background-position: 0% 50%; }}
                50% {{ background-position: 100% 50%; }}
                100% {{ background-position: 0% 50%; }}
            }}
            
            .btn-ai:hover {{
                transform: translateY(-3px);
                box-shadow: 0 10px 25px rgba(0, 219, 222, 0.4);
            }}
            
            .status-display {{
                text-align: center;
                margin-top: 20px;
                padding: 15px;
                background: rgba(0, 0, 0, 0.3);
                border-radius: 12px;
                border-left: 4px solid #00dbde;
                font-size: 1rem;
                color: #a0a0ff;
                min-height: 54px;
                display: flex;
                align-items: center;
                justify-content: center;
            }}
            
            .signal-card {{
                background: rgba(255, 255, 255, 0.05);
                border-radius: 20px;
                padding: 35px;
                margin: 30px 0;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.1);
                transition: all 0.3s ease;
            }}
            
            .signal-card.green {{
                border-left: 6px solid #00ff88;
                box-shadow: 0 10px 30px rgba(0, 255, 136, 0.2);
            }}
            
            .signal-card.red {{
                border-left: 6px solid #ff4444;
                box-shadow: 0 10px 30px rgba(255, 68, 68, 0.2);
            }}
            
            .signal-card.neutral {{
                border-left: 6px solid #ffd700;
                box-shadow: 0 10px 30px rgba(255, 215, 0, 0.2);
            }}
            
            .signal-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 25px;
                padding-bottom: 15px;
                border-bottom: 2px solid rgba(255, 255, 255, 0.1);
            }}
            
            .signal-text {{
                font-size: clamp(1.8rem, 3vw, 2.5rem);
                font-weight: 800;
                margin: 0;
            }}
            
            .signal-score {{
                font-size: 1.3rem;
                font-weight: 700;
                padding: 8px 20px;
                border-radius: 20px;
                background: rgba(0, 0, 0, 0.4);
            }}
            
            .signal-details {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin-top: 25px;
            }}
            
            .detail-item {{
                background: rgba(0, 0, 0, 0.3);
                padding: 18px;
                border-radius: 12px;
                border-left: 4px solid #00dbde;
            }}
            
            .detail-label {{
                color: #a0a0ff;
                font-size: 0.9rem;
                margin-bottom: 5px;
            }}
            
            .detail-value {{
                color: white;
                font-size: 1.2rem;
                font-weight: 600;
            }}
            
            .ai-analysis-panel {{
                background: rgba(13, 0, 51, 0.9);
                border-radius: 20px;
                padding: 30px;
                margin: 30px 0;
                border: 3px solid #00dbde;
                box-shadow: 0 10px 40px rgba(0, 219, 222, 0.3);
                display: none;
            }}
            
            .ai-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 25px;
                padding-bottom: 15px;
                border-bottom: 2px solid rgba(0, 219, 222, 0.3);
            }}
            
            .ai-title {{
                font-size: 1.5rem;
                font-weight: 700;
                color: #00dbde;
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            
            .close-btn {{
                background: #ff4444;
                color: white;
                border: none;
                border-radius: 50%;
                width: 36px;
                height: 36px;
                cursor: pointer;
                font-size: 1.5rem;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.3s ease;
            }}
            
            .close-btn:hover {{
                background: #ff6666;
                transform: rotate(90deg);
            }}
            
            #ai-comment {{
                font-size: 1.1rem;
                line-height: 1.7;
                color: #e0e0ff;
                max-height: 400px;
                overflow-y: auto;
                padding-right: 10px;
            }}
            
            #ai-comment::-webkit-scrollbar {{
                width: 8px;
            }}
            
            #ai-comment::-webkit-scrollbar-track {{
                background: rgba(0, 0, 0, 0.2);
                border-radius: 4px;
            }}
            
            #ai-comment::-webkit-scrollbar-thumb {{
                background: #00dbde;
                border-radius: 4px;
            }}
            
            .chart-container {{
                width: 100%;
                height: 600px;
                background: rgba(10, 0, 34, 0.8);
                border-radius: 20px;
                margin: 40px 0;
                overflow: hidden;
                border: 1px solid rgba(255, 255, 255, 0.1);
                box-shadow: 0 15px 35px rgba(0, 0, 0, 0.4);
            }}
            
            .navigation {{
                display: flex;
                justify-content: center;
                gap: 30px;
                margin-top: 40px;
                flex-wrap: wrap;
            }}
            
            .nav-link {{
                color: #00dbde;
                text-decoration: none;
                font-size: 1.1rem;
                font-weight: 600;
                padding: 12px 25px;
                border-radius: 12px;
                background: rgba(0, 219, 222, 0.1);
                border: 2px solid rgba(0, 219, 222, 0.3);
                transition: all 0.3s ease;
            }}
            
            .nav-link:hover {{
                background: rgba(0, 219, 222, 0.2);
                transform: translateY(-3px);
                box-shadow: 0 10px 20px rgba(0, 219, 222, 0.3);
            }}
            
            .loading {{
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 40px;
            }}
            
            .spinner {{
                width: 50px;
                height: 50px;
                border: 4px solid rgba(0, 219, 222, 0.3);
                border-top: 4px solid #00dbde;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin-bottom: 20px;
            }}
            
            @keyframes spin {{
                0% {{ transform: rotate(0deg); }}
                100% {{ transform: rotate(360deg); }}
            }}
            
            .triggers-list {{
                margin-top: 20px;
                padding: 15px;
                background: rgba(0, 0, 0, 0.3);
                border-radius: 12px;
                border-left: 4px solid #fc00ff;
            }}
            
            .triggers-title {{
                color: #fc00ff;
                font-weight: 600;
                margin-bottom: 10px;
            }}
            
            .trigger-item {{
                color: #e0e0ff;
                padding: 5px 0;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }}
            
            .trigger-item:last-child {{
                border-bottom: none;
            }}
            
            @media (max-width: 768px) {{
                .container {{
                    padding: 15px;
                }}
                
                .controls-panel {{
                    padding: 20px;
                }}
                
                .input-group {{
                    grid-template-columns: 1fr;
                }}
                
                .button-group {{
                    flex-direction: column;
                }}
                
                .btn {{
                    width: 100%;
                    min-width: auto;
                }}
                
                .signal-details {{
                    grid-template-columns: 1fr;
                }}
                
                .chart-container {{
                    height: 400px;
                }}
                
                .navigation {{
                    flex-direction: column;
                    align-items: center;
                }}
                
                .nav-link {{
                    width: 100%;
                    text-align: center;
                }}
            }}
            
            @media (max-width: 480px) {{
                .signal-header {{
                    flex-direction: column;
                    gap: 15px;
                    align-items: flex-start;
                }}
                
                .signal-text {{
                    font-size: 1.5rem;
                }}
                
                .ai-analysis-panel {{
                    padding: 20px;
                }}
            }}
        </style>
        <script src="https://s3.tradingview.com/tv.js"></script>
    </head>
    <body>
        <div class="user-info">👤 {user}</div>
        {visitor_stats}
        
        <div class="container">
            <div class="header">
                <h1 class="title">📊 TEK COİN CANLI SİNYAL + AI ANALİZ</h1>
                <p class="subtitle">Herhangi bir kripto para için canlı sinyal alın, TradingView grafiği ile analiz yapın ve AI destekli detaylı teknik analiz raporu oluşturun.</p>
            </div>
            
            <div class="controls-panel">
                <div class="input-group">
                    <div class="input-field">
                        <label for="pair">📈 COİN ADI</label>
                        <input type="text" id="pair" placeholder="örn: BTC, ETH, SOL..." value="BTC" autocomplete="off">
                    </div>
                    
                    <div class="input-field">
                        <label for="timeframe">⏰ ZAMAN DİLİMİ</label>
                        <select id="timeframe">
                            <option value="1m">1 Dakika</option>
                            <option value="3m">3 Dakika</option>
                            <option value="5m" selected>5 Dakika</option>
                            <option value="15m">15 Dakika</option>
                            <option value="30m">30 Dakika</option>
                            <option value="1h">1 Saat</option>
                            <option value="4h">4 Saat</option>
                            <option value="1d">1 Gün</option>
                            <option value="1w">1 Hafta</option>
                        </select>
                    </div>
                </div>
                
                <div class="button-group">
                    <button class="btn btn-primary" onclick="connectSignal()">
                        <span>🔴 CANLI SİNYAL BAĞLANTISI KUR</span>
                    </button>
                    
                    <button class="btn btn-ai" id="analyze-btn" onclick="analyzeChartWithAI()">
                        <span>🤖 GRAFİĞİ ANALİZ ET</span>
                    </button>
                </div>
                
                <div class="status-display" id="connection-status">
                    Bağlantı bekleniyor... Lütfen yukarıdaki butona tıklayın.
                </div>
            </div>
            
            <div id="signal-card" class="signal-card neutral">
                <div class="signal-header">
                    <div id="signal-text" class="signal-text" style="color: #ffd700;">
                        Sinyal bağlantısı kurulmadı
                    </div>
                    <div id="signal-score" class="signal-score" style="color: #ffd700;">
                        ?/100
                    </div>
                </div>
                
                <div id="signal-details">
                    <div class="detail-item">
                        <div class="detail-label">COİN</div>
                        <div class="detail-value" id="detail-pair">BTC/USDT</div>
                    </div>
                    
                    <div class="detail-item">
                        <div class="detail-label">FİYAT</div>
                        <div class="detail-value" id="detail-price">$0.00</div>
                    </div>
                    
                    <div class="detail-item">
                        <div class="detail-label">DEĞİŞİM (24S)</div>
                        <div class="detail-value" id="detail-change">+0.00%</div>
                    </div>
                    
                    <div class="detail-item">
                        <div class="detail-label">KİLLZONE</div>
                        <div class="detail-value" id="detail-killzone">Normal</div>
                    </div>
                </div>
                
                <div id="triggers-container" class="triggers-list" style="display: none;">
                    <div class="triggers-title">🎯 SİNYAL TETİKLEYİCİLER</div>
                    <div id="triggers-content"></div>
                </div>
            </div>
            
            <div id="ai-box" class="ai-analysis-panel">
                <div class="ai-header">
                    <div class="ai-title">🤖 DETAYLI TEKNİK ANALİZ RAPORU</div>
                    <button class="close-btn" onclick="toggleAIBox()">×</button>
                </div>
                <div id="ai-comment">
                    AI analiz raporu burada görüntülenecek. Analiz için yukarıdaki butona tıklayın.
                </div>
            </div>
            
            <div class="chart-container">
                <div id="tradingview_widget"></div>
            </div>
            
            <div class="navigation">
                <a href="/" class="nav-link">← Ana Sayfaya Dön</a>
                <a href="/signal/all" class="nav-link">Tüm Coin Sinyalleri →</a>
                <a href="/debug/sources" class="nav-link">🔧 Sistem Durumu</a>
            </div>
        </div>
        
        <script>
            let signalWs = null;
            let tradingViewWidget = null;
            let currentSymbol = "BTC";
            let currentTimeframe = "5m";
            let isAnalyzing = false;
            
            const timeframeMap = {{
                "1m": "1",
                "3m": "3",
                "5m": "5",
                "15m": "15",
                "30m": "30",
                "1h": "60",
                "4h": "240",
                "1d": "D",
                "1w": "W"
            }};
            
            function getTradingViewSymbol(pair) {{
                let symbol = pair.trim().toUpperCase();
                if (!symbol.endsWith("USDT")) {{
                    symbol += "USDT";
                }}
                return "BINANCE:" + symbol;
            }}
            
            async function connectSignal() {{
                currentSymbol = document.getElementById('pair').value.trim().toUpperCase();
                currentTimeframe = document.getElementById('timeframe').value;
                
                if (!currentSymbol) {{
                    showStatus("❌ Lütfen bir coin adı girin!", "error");
                    return;
                }}
                
                const tvSymbol = getTradingViewSymbol(currentSymbol);
                const interval = timeframeMap[currentTimeframe] || "5";
                
                showStatus("🔄 Bağlantı kuruluyor...", "loading");
                
                // WebSocket'i kapat
                if (signalWs) {{
                    signalWs.close();
                    signalWs = null;
                }}
                
                // TradingView widget'ı yenile
                if (tradingViewWidget) {{
                    tradingViewWidget.remove();
                    tradingViewWidget = null;
                }}
                
                try {{
                    // TradingView widget oluştur
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
                        toolbar_bg: "#1a0033",
                        enable_publishing: false,
                        hide_side_toolbar: false,
                        allow_symbol_change: false,
                        studies: [
                            "RSI@tv-basicstudies",
                            "MACD@tv-basicstudies",
                            "Volume@tv-basicstudies",
                            "BB@tv-basicstudies"
                        ],
                        disabled_features: [
                            "volume_force_overlay",
                            "use_localstorage_for_settings"
                        ],
                        enabled_features: [
                            "study_templates",
                            "save_chart_properties_to_local_storage"
                        ]
                    }});
                    
                    tradingViewWidget.onChartReady(function() {{
                        showStatus(`✅ Grafik yüklendi: ${{currentSymbol}} ${{currentTimeframe.toUpperCase()}}`, "success");
                    }});
                    
                }} catch (error) {{
                    console.error('TradingView hatası:', error);
                    showStatus("❌ TradingView yüklenemedi", "error");
                }}
                
                // WebSocket bağlantısı
                const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
                signalWs = new WebSocket(protocol + window.location.host + '/ws/signal/' + currentSymbol + '/' + currentTimeframe);
                
                signalWs.onopen = function() {{
                    showStatus(`✅ ${{currentSymbol}} ${{currentTimeframe.toUpperCase()}} canlı sinyal başladı!`, "success");
                    document.getElementById('ai-box').style.display = 'none';
                }};
                
                signalWs.onmessage = function(event) {{
                    try {{
                        if (event.data.includes('heartbeat')) return;
                        
                        const data = JSON.parse(event.data);
                        updateSignalCard(data);
                        
                    }} catch (error) {{
                        console.error('Sinyal işleme hatası:', error);
                    }}
                }};
                
                signalWs.onerror = function() {{
                    showStatus("❌ WebSocket bağlantı hatası", "error");
                }};
                
                signalWs.onclose = function() {{
                    showStatus("🔌 Bağlantı kapandı. Yeniden bağlanmak için butona tıklayın.", "warning");
                }};
            }}
            
            function updateSignalCard(data) {{
                const card = document.getElementById('signal-card');
                const text = document.getElementById('signal-text');
                const score = document.getElementById('signal-score');
                
                // Sinyal metnini güncelle
                text.innerHTML = data.signal || "⏸️ Sinyal bekleniyor...";
                score.innerHTML = `${{data.score || '?'}}/100`;
                
                // Detayları güncelle
                document.getElementById('detail-pair').textContent = data.pair || currentSymbol + '/USDT';
                document.getElementById('detail-price').textContent = `$${{formatPrice(data.current_price || 0)}}`;
                
                const change = data.change_24h || 0;
                const changeElement = document.getElementById('detail-change');
                changeElement.textContent = `${{change >= 0 ? '+' : ''}}${{change.toFixed(2)}}%`;
                changeElement.style.color = change >= 0 ? '#00ff88' : '#ff4444';
                
                document.getElementById('detail-killzone').textContent = data.killzone || 'Normal';
                
                // Tetikleyicileri güncelle
                const triggersContainer = document.getElementById('triggers-container');
                const triggersContent = document.getElementById('triggers-content');
                
                if (data.triggers && data.triggers !== 'Belirgin sinyal yok') {{
                    triggersContainer.style.display = 'block';
                    const triggers = data.triggers.split(' | ');
                    triggersContent.innerHTML = triggers.map(trigger => 
                        `<div class="trigger-item">• ${{trigger}}</div>`
                    ).join('');
                }} else {{
                    triggersContainer.style.display = 'none';
                }}
                
                // Kart stilini güncelle
                card.className = 'signal-card';
                if (data.signal) {{
                    if (data.signal.includes('ALIM') || data.signal.includes('YÜKSELİŞ')) {{
                        card.classList.add('green');
                        text.style.color = '#00ff88';
                        score.style.color = '#00ff88';
                    }} else if (data.signal.includes('SATIM') || data.signal.includes('DÜŞÜŞ')) {{
                        card.classList.add('red');
                        text.style.color = '#ff4444';
                        score.style.color = '#ff4444';
                    }} else {{
                        card.classList.add('neutral');
                        text.style.color = '#ffd700';
                        score.style.color = '#ffd700';
                    }}
                }}
            }}
            
            async function analyzeChartWithAI() {{
                if (isAnalyzing) return;
                
                const btn = document.getElementById('analyze-btn');
                const box = document.getElementById('ai-box');
                const comment = document.getElementById('ai-comment');
                
                if (!currentSymbol) {{
                    currentSymbol = document.getElementById('pair').value.trim().toUpperCase();
                    if (!currentSymbol) {{
                        showStatus("❌ Lütfen önce bir coin adı girin!", "error");
                        return;
                    }}
                }}
                
                isAnalyzing = true;
                btn.disabled = true;
                btn.innerHTML = '<span>⏳ Analiz ediliyor...</span>';
                box.style.display = 'block';
                comment.innerHTML = `
                    <div class="loading">
                        <div class="spinner"></div>
                        <div style="margin-top: 15px; color: #00dbde;">Teknik analiz oluşturuluyor...</div>
                        <div style="font-size: 0.9rem; color: #a0a0ff; margin-top: 10px;">Lütfen bekleyin, bu işlem birkaç saniye sürebilir.</div>
                    </div>
                `;
                
                try {{
                    const response = await fetch('/api/analyze-chart', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ 
                            symbol: currentSymbol, 
                            timeframe: currentTimeframe 
                        }})
                    }});
                    
                    const data = await response.json();
                    
                    if (data.success) {{
                        // AI yorumunu güncelle
                        comment.innerHTML = data.analysis.replace(/\\n/g, '<br>');
                        
                        // Sinyal kartını da güncelle
                        if (data.signal_data) {{
                            updateSignalCard(data.signal_data);
                        }}
                        
                        showStatus("✅ AI analiz tamamlandı!", "success");
                        
                    }} else {{
                        comment.innerHTML = `
                            <div style="color: #ff4444; padding: 20px; text-align: center;">
                                <strong>❌ Analiz hatası:</strong><br>
                                ${{data.analysis || 'Bilinmeyen hata oluştu'}}
                            </div>
                        `;
                        showStatus("❌ Analiz başarısız", "error");
                    }}
                    
                }} catch (err) {{
                    console.error('Analiz hatası:', err);
                    comment.innerHTML = `
                        <div style="color: #ff4444; padding: 20px; text-align: center;">
                            <strong>❌ Bağlantı hatası:</strong><br>
                            ${{err.message || 'Sunucuya ulaşılamıyor'}}
                        </div>
                    `;
                    showStatus("❌ Sunucu hatası", "error");
                    
                }} finally {{
                    isAnalyzing = false;
                    btn.disabled = false;
                    btn.innerHTML = '<span>🤖 GRAFİĞİ ANALİZ ET</span>';
                }}
            }}
            
            function toggleAIBox() {{
                const box = document.getElementById('ai-box');
                box.style.display = box.style.display === 'none' ? 'block' : 'none';
            }}
            
            function showStatus(message, type) {{
                const status = document.getElementById('connection-status');
                status.textContent = message;
                
                status.style.borderLeftColor = 
                    type === 'success' ? '#00ff88' :
                    type === 'error' ? '#ff4444' :
                    type === 'warning' ? '#ffaa00' : '#00dbde';
            }}
            
            function formatPrice(price) {{
                if (price >= 1000) {{
                    return price.toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
                }} else if (price >= 1) {{
                    return price.toLocaleString('en-US', {{ minimumFractionDigits: 3, maximumFractionDigits: 3 }});
                }} else {{
                    return price.toLocaleString('en-US', {{ minimumFractionDigits: 6, maximumFractionDigits: 8 }});
                }}
            }}
            
            // Sayfa yüklendiğinde otomatik bağlan
            document.addEventListener('DOMContentLoaded', function() {{
                // Kısayol tuşları
                document.addEventListener('keydown', function(e) {{
                    if (e.ctrlKey && e.key === 'Enter') {{
                        e.preventDefault();
                        connectSignal();
                    }} else if (e.ctrlKey && e.key === 'a') {{
                        e.preventDefault();
                        analyzeChartWithAI();
                    }}
                }});
                
                // Otomatik bağlanma için kısa bir gecikme
                setTimeout(() => {{
                    connectSignal();
                }}, 1500);
            }});
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)

@app.get("/signal/all")
async def all_signals_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    visitor_stats = get_visitor_stats_html()
    
    html = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Tüm Coin Sinyalleri - ICT SMART PRO</title>
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
                max-width: 1200px;
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
            select {{
                padding: 12px;
                width: 200px;
                border: none;
                border-radius: 8px;
                background: rgba(255, 255, 255, 0.1);
                color: white;
                font-size: 1rem;
            }}
            .status {{
                color: #00ffff;
                text-align: center;
                margin: 15px 0;
                min-height: 24px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 30px 0;
                background: rgba(255, 255, 255, 0.05);
                border-radius: 10px;
                overflow: hidden;
            }}
            th {{
                background: rgba(0, 219, 222, 0.2);
                padding: 15px;
                text-align: left;
                color: #00ffff;
            }}
            td {{
                padding: 12px 15px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }}
            tr:hover {{
                background: rgba(255, 255, 255, 0.08);
            }}
            .signal-buy {{
                color: #00ff88;
                font-weight: bold;
            }}
            .signal-sell {{
                color: #ff4444;
                font-weight: bold;
            }}
            .signal-neutral {{
                color: #ffd700;
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
            .nav-link:hover {{
                text-decoration: underline;
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
        </style>
    </head>
    <body>
        <div class="user-info">Hoş geldin, {user}</div>
        {visitor_stats}
        
        <div class="container">
            <div class="header">
                <h1 class="title">🔥 TÜM COİN SİNYALLERİ</h1>
            </div>
            
            <div class="controls">
                <select id="timeframe" onchange="connectAllSignals()">
                    <option value="5m">5 Dakika</option>
                    <option value="15m">15 Dakika</option>
                    <option value="1h">1 Saat</option>
                    <option value="4h">4 Saat</option>
                    <option value="1d">1 Gün</option>
                </select>
                <div class="status" id="connection-status">Zaman dilimi seçin...</div>
            </div>
            
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>COİN</th>
                            <th>SİNYAL</th>
                            <th>SKOR</th>
                            <th>FİYAT</th>
                            <th>KİLLZONE</th>
                            <th>ZAMAN</th>
                        </tr>
                    </thead>
                    <tbody id="signals-table">
                        <tr>
                            <td colspan="7" style="text-align: center; padding: 50px;">
                                📊 Zaman dilimi seçerek sinyalleri görüntüleyin...
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <div class="navigation">
                <a href="/" class="nav-link">← Ana Sayfa</a>
                <a href="/signal" class="nav-link">Tek Coin Sinyal →</a>
            </div>
        </div>
        
        <script>
            let allSignalsWs = null;
            
            function connectAllSignals() {{
                const timeframe = document.getElementById('timeframe').value;
                document.getElementById('connection-status').innerHTML = '🔄 ' + timeframe.toUpperCase() + ' sinyalleri yükleniyor...';
                
                if (allSignalsWs) {{
                    allSignalsWs.close();
                }}
                
                const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
                allSignalsWs = new WebSocket(protocol + window.location.host + '/ws/all/' + timeframe);
                
                allSignalsWs.onopen = function() {{
                    document.getElementById('connection-status').innerHTML = '✅ ' + timeframe.toUpperCase() + ' canlı sinyal akışı başladı!';
                }};
                
                allSignalsWs.onmessage = function(event) {{
                    try {{
                        if (event.data.includes('ping')) return;
                        
                        const signals = JSON.parse(event.data);
                        const table = document.getElementById('signals-table');
                        
                        if (!signals || signals.length === 0) {{
                            table.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 50px; color: #ffd700;">📊 Şu anda güçlü sinyal bulunmuyor</td></tr>';
                            return;
                        }}
                        
                        let html = '';
                        signals.slice(0, 50).forEach(function(signal, index) {{
                            let signalClass = 'signal-neutral';
                            if (signal.signal && signal.signal.includes('ALIM')) {{
                                signalClass = 'signal-buy';
                            }} else if (signal.signal && signal.signal.includes('SATIM')) {{
                                signalClass = 'signal-sell';
                            }}
                            
                            html += `
                                <tr>
                                    <td>#${index + 1}</td>
                                    <td><strong>${{signal.pair ? signal.pair.replace('USDT', '/USDT') : 'N/A'}}</strong></td>
                                    <td class="${{signalClass}}">${{signal.signal || '⏸️ Bekle'}}</td>
                                    <td><strong>${{signal.score || '?'}}/100</strong></td>
                                    <td>$${{(signal.current_price || 0).toLocaleString('en-US', {{minimumFractionDigits: 4, maximumFractionDigits: 6}})}}</td>
                                    <td>${{signal.killzone || 'Normal'}}</td>
                                    <td>${{signal.last_update || ''}}</td>
                                </tr>
                            `;
                        }});
                        
                        table.innerHTML = html;
                        
                    }} catch (error) {{
                        console.error('Hata:', error);
                    }}
                }};
                
                allSignalsWs.onerror = function() {{
                    document.getElementById('connection-status').innerHTML = '❌ WebSocket hatası';
                }};
                
                allSignalsWs.onclose = function() {{
                    document.getElementById('connection-status').innerHTML = '🔌 Bağlantı kapandı';
                }};
            }}
            
            document.addEventListener('DOMContentLoaded', function() {{
                document.getElementById('timeframe').value = '5m';
                setTimeout(connectAllSignals, 500);
            }});
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)

# ==================== API ENDPOINTS ====================

@app.post("/api/analyze-chart")
async def analyze_chart_endpoint(request: Request):
    try:
        body = await request.json()
        symbol = body.get("symbol", "BTC").upper()
        timeframe = body.get("timeframe", "5m")
        
        logger.info(f"📊 AI Analiz isteği: {symbol} @ {timeframe}")
        
        # Binance bağlantısı kontrolü
        binance_client = get_binance_client()
        if not binance_client:
            return JSONResponse({
                "analysis": "❌ Binance bağlantısı aktif değil. Lütfen daha sonra tekrar deneyin.",
                "success": False
            }, status_code=503)
        
        # Sembolü formatla
        ccxt_symbol = f"{symbol}/USDT"
        
        # Zaman dilimi eşleme
        interval_map = {
            "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
            "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
        }
        ccxt_timeframe = interval_map.get(timeframe, "5m")
        
        try:
            # Kline verilerini al
            klines = await binance_client.fetch_ohlcv(
                ccxt_symbol, 
                timeframe=ccxt_timeframe, 
                limit=200
            )
            
            if not klines or len(klines) < 50:
                return JSONResponse({
                    "analysis": f"❌ {symbol} için yeterli veri yok. Lütfen daha sonra tekrar deneyin.",
                    "success": False
                }, status_code=404)
            
            # DataFrame oluştur
            df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume'])
            df.iloc[:,1:] = df.iloc[:,1:].apply(pd.to_numeric, errors='coerce')
            df = df.dropna()
            
            # Teknik analiz yap
            analysis = generate_technical_analysis(df, symbol, timeframe)
            
            if not analysis:
                # Fallback analiz
                last_price = float(df['close'].iloc[-1])
                prev_price = float(df['close'].iloc[-2])
                change_pct = ((last_price - prev_price) / prev_price * 100) if prev_price > 0 else 0
                
                analysis = {
                    "pair": f"{symbol}/USDT",
                    "timeframe": timeframe.upper(),
                    "current_price": round(last_price, 6 if last_price < 1 else 4),
                    "signal": "🚀 ALIM" if change_pct > 0.5 else "🔥 SATIM" if change_pct < -0.5 else "⏸️ NÖTR",
                    "score": min(90, max(30, int(50 + change_pct * 5))),
                    "strength": "YÜKSEK" if abs(change_pct) > 2 else "ORTA" if abs(change_pct) > 1 else "ZAYIF",
                    "killzone": "Normal",
                    "triggers": f"Fiyat değişimi: {change_pct:+.2f}%",
                    "analysis_time": datetime.utcnow().strftime("%H:%M:%S UTC")
                }
            
            # Detaylı analiz raporu oluştur
            analysis_report = f"""
🔍 <strong style="color:#00dbde">{analysis['pair']}</strong> - <strong>{analysis['timeframe']}</strong> TEKNİK ANALİZ RAPORU

🎯 <strong style="font-size: 1.2em; color:{analysis.get('color', '#ffffff')}">{analysis['signal']}</strong>
📊 <strong>GÜÇ SKORU:</strong> {analysis['score']}/100 ({analysis['strength']})
💰 <strong>MEVCUT FİYAT:</strong> ${analysis['current_price']:,.6f}
📈 <strong>24S DEĞİŞİM:</strong> <span style="color:{'#00ff88' if analysis.get('change_24h', 0) >= 0 else '#ff4444'}">{analysis.get('change_24h', 0):+.2f}%</span>
🕐 <strong>KİLLZONE:</strong> {analysis['killzone']}

📊 <strong>TEKNİK GÖSTERGELER:</strong>
• 📈 <strong>Trend:</strong> {analysis.get('trend', 'Belirsiz')}
• 🎯 <strong>RSI(14):</strong> {analysis.get('rsi', '?')} - {get_rsi_status(analysis.get('rsi', 50))}
• 🔄 <strong>MACD:</strong> {analysis.get('macd_trend', 'NÖTR')}
• 📊 <strong>Hacim Oranı:</strong> {analysis.get('volume_ratio', '1.0')}x

📈 <strong>HAREKETLİ ORTALAMALAR:</strong>
• MA20: ${analysis.get('ma20', 0):,.6f}
• MA50: ${analysis.get('ma50', 0):,.6f}

🎯 <strong>ANA SEVİYELER:</strong>
• 🛡️ <strong>Destek:</strong> ${analysis.get('support', 0):,.6f}
• 🚧 <strong>Direnç:</strong> ${analysis.get('resistance', 0):,.6f}
• ⚖️ <strong>Pivot:</strong> ${analysis.get('pivot', 0):,.6f}

🎯 <strong>SİNYAL TETİKLEYİCİLER:</strong>
{analysis['triggers']}

⚠️ <strong>RISK UYARILARI:</strong>
• Bu analiz otomatik olarak oluşturulmuştur ve yatırım tavsiyesi değildir
• Her zaman kendi araştırmanızı yapın
• Stop-loss kullanmayı unutmayın
• Yüksek volatilite nedeniyle kayıp riski bulunmaktadır

🕒 <strong>ANALİZ ZAMANI:</strong> {analysis['analysis_time']}
🔧 <strong>VERİ KAYNAĞI:</strong> Binance Spot
"""

            logger.info(f"✅ Analiz başarılı: {symbol} - Skor: {analysis['score']}")
            
            return JSONResponse({
                "analysis": analysis_report, 
                "signal_data": analysis, 
                "success": True
            })
            
        except Exception as e:
            logger.error(f"Veri alma hatası: {e}")
            return JSONResponse({
                "analysis": f"❌ {symbol} için veri alınamadı. Lütfen geçerli bir coin adı girin.",
                "success": False
            }, status_code=404)
            
    except Exception as e:
        logger.exception(f"❌ Analiz hatası: {e}")
        return JSONResponse({
            "analysis": f"❌ Analiz sırasında hata oluştu: {str(e)}",
            "success": False
        }, status_code=500)

def get_rsi_status(rsi):
    """RSI durumunu belirle"""
    if rsi >= 70:
        return "<span style='color:#ff4444'>AŞIRI ALIM</span>"
    elif rsi <= 30:
        return "<span style='color:#00ff88'>AŞIRI SATIM</span>"
    elif rsi >= 60:
        return "<span style='color:#ffaa00'>ALIM BÖLGESİ</span>"
    elif rsi <= 40:
        return "<span style='color:#ffaa00'>SATIM BÖLGESİ</span>"
    else:
        return "<span style='color:#00ffff'>NÖTR</span>"

@app.post("/api/gpt-analyze")
async def gpt_analyze_endpoint(image_file: UploadFile = File(...)):
    if not openai_client:
        return JSONResponse({
            "error": "OpenAI API anahtarı yok",
            "success": False
        }, status_code=501)
    
    try:
        image_data = await image_file.read()
        image_b64 = base64.b64encode(image_data).decode('utf-8')
        
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": """Bu kripto grafiğini Türkçe olarak detaylı analiz et:
1. Genel trend ve momentum analizi
2. Önemli destek ve direnç seviyeleri
3. Mum formasyonları ve hacim analizi
4. RSI, MACD ve diğer teknik göstergelerin durumu
5. Kısa vadeli öneriler ve risk seviyesi
6. Stop-loss ve take-profit önerileri

Analizi net, anlaşılır ve profesyonel bir dille yap."""},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
                ]
            }],
            max_tokens=1500,
            temperature=0.3
        )
        
        return JSONResponse({
            "analysis": response.choices[0].message.content, 
            "success": True
        })
        
    except Exception as e:
        logger.exception(f"GPT analiz hatası: {e}")
        return JSONResponse({
            "error": str(e),
            "success": False
        }, status_code=500)

@app.get("/api/visitor-stats")
async def get_visitor_stats():
    return JSONResponse(visitor_counter.get_stats())

@app.get("/api/system-status")
async def get_system_status():
    healthy_sources = 0
    if price_sources_status:
        healthy_sources = sum(1 for v in price_sources_status.values() if v.get("healthy", False))
    
    return JSONResponse({
        "status": "OK",
        "version": "6.1",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "binance_connected": get_binance_client() is not None,
            "price_sources_healthy": healthy_sources,
            "price_sources_total": len(price_sources_status),
            "symbols_loaded": len(all_usdt_symbols),
            "active_websockets": len(price_sources_subscribers) + 
                               sum(len(s) for s in single_subscribers.values()) + 
                               sum(len(s) for s in all_subscribers.values()) + 
                               len(pump_radar_subscribers)
        },
        "visitor_stats": visitor_counter.get_stats()
    })

@app.get("/admin/visitor-dashboard")
async def visitor_dashboard_page(request: Request):
    user = request.cookies.get("user_email")
    if not user or "admin" not in user.lower():
        return RedirectResponse("/login")
    
    stats = visitor_counter.get_stats()
    
    # Top 10 sayfa
    top_pages_html = ""
    for page, views in stats.get('top_pages', {}).items():
        top_pages_html += f"<tr><td>{page}</td><td><strong>{views}</strong></td></tr>"
    
    # Günlük istatistikler
    today = datetime.now().strftime("%Y-%m-%d")
    today_stats = visitor_counter.daily_stats.get(today, {"visits": 0, "unique": set()})
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Admin Panel - ICT SMART PRO</title>
        <style>
            body {{
                background: #000;
                color: #fff;
                font-family: monospace;
                padding: 20px;
                margin: 0;
            }}
            .dashboard {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            .header {{
                text-align: center;
                margin-bottom: 40px;
                padding: 20px;
                background: rgba(0, 219, 222, 0.1);
                border-radius: 10px;
                border: 1px solid #00dbde;
            }}
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-bottom: 40px;
            }}
            .stat-card {{
                background: rgba(255, 255, 255, 0.05);
                padding: 20px;
                border-radius: 10px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                text-align: center;
            }}
            .stat-value {{
                font-size: 2.5rem;
                font-weight: bold;
                color: #00ff88;
                margin: 10px 0;
            }}
            .stat-label {{
                color: #aaa;
                font-size: 0.9rem;
            }}
            .table-container {{
                overflow-x: auto;
                margin: 30px 0;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: rgba(255, 255, 255, 0.05);
            }}
            th {{
                background: rgba(0, 219, 222, 0.2);
                padding: 15px;
                text-align: left;
                color: #00ffff;
            }}
            td {{
                padding: 12px 15px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }}
            tr:hover {{
                background: rgba(255, 255, 255, 0.08);
            }}
            .nav {{
                margin-top: 30px;
                text-align: center;
            }}
            .nav a {{
                color: #00dbde;
                text-decoration: none;
                margin: 0 15px;
                padding: 10px 20px;
                border: 1px solid #00dbde;
                border-radius: 5px;
                transition: all 0.3s;
            }}
            .nav a:hover {{
                background: #00dbde;
                color: #000;
            }}
        </style>
    </head>
    <body>
        {get_visitor_stats_html()}
        <div class="dashboard">
            <div class="header">
                <h1>📊 ADMIN PANEL - İSTATİSTİKLER</h1>
                <p>Son Güncelleme: {stats['last_updated']}</p>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">TOPLAM ZİYARET</div>
                    <div class="stat-value">{stats['total_visits']:,}</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-label">AKTİF KULLANICI</div>
                    <div class="stat-value">{stats['active_users']}</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-label">BUGÜNKÜ ZİYARET</div>
                    <div class="stat-value">{stats['today_visits']}</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-label">BUGÜNKÜ TEKİL</div>
                    <div class="stat-value">{stats['today_unique']}</div>
                </div>
            </div>
            
            <h2>📈 EN POPÜLER SAYFALAR</h2>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>SAYFA</th>
                            <th>GÖRÜNTÜLENME</th>
                        </tr>
                    </thead>
                    <tbody>
                        {top_pages_html if top_pages_html else '<tr><td colspan="2">Veri yok</td></tr>'}
                    </tbody>
                </table>
            </div>
            
            <div class="nav">
                <a href="/">🏠 Ana Sayfa</a>
                <a href="/api/system-status">🔄 Sistem Durumu</a>
                <a href="/debug/sources">🔧 Fiyat Kaynakları</a>
            </div>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)

@app.get("/login")
async def login_page():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Giriş - ICT SMART PRO</title>
        <style>
            body {
                background: linear-gradient(135deg, #0a0022, #1a0033, #000);
                color: #fff;
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                margin: 0;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            .login-box {
                background: rgba(0, 0, 0, 0.8);
                padding: 50px;
                border-radius: 20px;
                text-align: center;
                max-width: 400px;
                width: 90%;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(0, 219, 222, 0.3);
                box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
            }
            .login-title {
                font-size: 2rem;
                margin-bottom: 30px;
                background: linear-gradient(90deg, #00dbde, #fc00ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
            }
            input {
                width: 100%;
                padding: 15px;
                margin: 10px 0;
                border: none;
                border-radius: 10px;
                background: rgba(255, 255, 255, 0.1);
                color: #fff;
                font-size: 1rem;
                transition: all 0.3s;
            }
            input:focus {
                outline: none;
                background: rgba(255, 255, 255, 0.15);
                box-shadow: 0 0 0 3px rgba(0, 219, 222, 0.3);
            }
            button {
                width: 100%;
                padding: 15px;
                background: linear-gradient(45deg, #00dbde, #fc00ff);
                border: none;
                border-radius: 10px;
                color: #fff;
                font-size: 1.1rem;
                font-weight: bold;
                cursor: pointer;
                transition: all 0.3s;
                margin-top: 20px;
            }
            button:hover {
                transform: translateY(-3px);
                box-shadow: 0 10px 25px rgba(252, 0, 255, 0.4);
            }
            .demo-note {
                color: #888;
                margin-top: 20px;
                font-size: 0.9rem;
                line-height: 1.5;
            }
            .logo {
                font-size: 3rem;
                margin-bottom: 20px;
            }
        </style>
    </head>
    <body>
        <div class="login-box">
            <div class="logo">🚀</div>
            <h1 class="login-title">ICT SMART PRO</h1>
            <form method="post">
                <input type="email" name="email" placeholder="E-posta adresiniz" required>
                <button type="submit">🔓 GİRİŞ YAP</button>
            </form>
            <p class="demo-note">
                Demo amaçlıdır. Herhangi bir e-posta adresi ile giriş yapabilirsiniz.<br>
                Örnek: demo@ictsmart.com
            </p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.post("/login")
async def login_user(request: Request):
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    
    if "@" in email and "." in email:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            "user_email", 
            email, 
            max_age=2592000,  # 30 gün
            httponly=True, 
            samesite="lax",
            secure=request.url.scheme == "https"
        )
        logger.info(f"✅ Kullanıcı girişi: {email}")
        return resp
    
    return RedirectResponse("/login")

@app.get("/debug/sources")
async def debug_sources_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Sistem Durumu - ICT SMART PRO</title>
        <style>
            body {{
                background: #000;
                color: #fff;
                font-family: monospace;
                padding: 20px;
            }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
                padding: 20px;
                background: rgba(0, 219, 222, 0.1);
                border-radius: 10px;
            }}
            .status-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
                margin-bottom: 40px;
            }}
            .status-card {{
                background: rgba(255, 255, 255, 0.05);
                padding: 20px;
                border-radius: 10px;
                border: 1px solid;
            }}
            .status-card.healthy {{
                border-color: #00ff88;
            }}
            .status-card.unhealthy {{
                border-color: #ff4444;
            }}
            .status-title {{
                font-weight: bold;
                margin-bottom: 10px;
                font-size: 1.1rem;
            }}
            .status-data {{
                color: #aaa;
                font-size: 0.9rem;
                margin: 5px 0;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0;
            }}
            th, td {{
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #333;
            }}
            th {{
                background: #00dbde22;
                color: #00ffff;
            }}
            .nav {{
                margin-top: 30px;
                text-align: center;
            }}
            .nav a {{
                color: #00dbde;
                text-decoration: none;
                margin: 0 15px;
                padding: 10px 20px;
                border: 1px solid #00dbde;
                border-radius: 5px;
            }}
        </style>
    </head>
    <body>
        {get_visitor_stats_html()}
        <div class="header">
            <h1>🔧 SİSTEM DURUMU - FİYAT KAYNAKLARI</h1>
            <p id="total">Yükleniyor...</p>
        </div>
        
        <div class="status-grid" id="status-grid">
            <div class="status-card">
                <div class="status-title">🔄 Veriler yükleniyor...</div>
            </div>
        </div>
        
        <table>
            <thead>
                <tr>
                    <th>KAYNAK</th>
                    <th>DURUM</th>
                    <th>SON GÜNCELLEME</th>
                    <th>COIN SAYISI</th>
                </tr>
            </thead>
            <tbody id="sources-table">
                <tr>
                    <td colspan="4" style="text-align:center;padding:40px;">🔄 Veriler yükleniyor...</td>
                </tr>
            </tbody>
        </table>
        
        <div class="nav">
            <a href="/">🏠 Ana Sayfa</a>
            <a href="/signal">📊 Sinyal Ekranı</a>
            <a href="/admin/visitor-dashboard">📈 İstatistikler</a>
        </div>
        
        <script>
            const ws = new WebSocket((window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws/price_sources');
            
            ws.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    document.getElementById('total').innerText = '📈 Toplam ' + data.total_symbols.toLocaleString() + ' coin aktif';
                    
                    // Status grid güncelle
                    const grid = document.getElementById('status-grid');
                    const healthySources = Object.values(data.sources).filter(s => s.healthy).length;
                    const totalSources = Object.keys(data.sources).length;
                    
                    grid.innerHTML = `
                        <div class="status-card ${{healthySources === totalSources ? 'healthy' : 'unhealthy'}}">
                            <div class="status-title">${{healthySources === totalSources ? '✅ TÜM KAYNAKLAR SAĞLIKLI' : '⚠️ BAZI KAYNAKLARDA SORUN'}}</div>
                            <div class="status-data">Sağlıklı: ${{healthySources}} / ${{totalSources}}</div>
                            <div class="status-data">Toplam Coin: ${{data.total_symbols.toLocaleString()}}</div>
                            <div class="status-data">Son Güncelleme: ${{new Date().toLocaleTimeString('tr-TR')}}</div>
                        </div>
                    `;
                    
                    // Tablo güncelle
                    const table = document.getElementById('sources-table');
                    let html = '';
                    
                    for (const [sourceName, sourceData] of Object.entries(data.sources)) {{
                        const status = sourceData.healthy ? '✅ SAĞLIKLI' : '❌ HATA';
                        const statusClass = sourceData.healthy ? 'healthy' : 'unhealthy';
                        
                        html += `
                            <tr>
                                <td><strong>${{sourceName.toUpperCase()}}</strong></td>
                                <td><span class="${{statusClass}}">${{status}}</span></td>
                                <td>${{sourceData.last_update || 'Asla'}}</td>
                                <td><strong>${{sourceData.symbols_count || 0}}</strong></td>
                            </tr>
                        `;
                    }}
                    
                    table.innerHTML = html;
                    
                }} catch (error) {{
                    console.error('Hata:', error);
                }}
            }};
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/health")
async def health_check_endpoint():
    stats = visitor_counter.get_stats()
    healthy_sources = 0
    if price_sources_status:
        healthy_sources = sum(1 for v in price_sources_status.values() if v.get("healthy", False))
    
    return JSONResponse({
        "status": "OK",
        "version": "6.1-REALTIME",
        "timestamp": datetime.utcnow().isoformat(),
        "uptime": str(datetime.utcnow() - app_start_time) if 'app_start_time' in globals() else "unknown",
        "services": {
            "binance_connected": get_binance_client() is not None,
            "price_sources_healthy": healthy_sources,
            "price_sources_total": len(price_sources_status),
            "symbols_loaded": len(all_usdt_symbols),
            "active_connections": {
                "price_sources": len(price_sources_subscribers),
                "single_signals": sum(len(s) for s in single_subscribers.values()),
                "all_signals": sum(len(s) for s in all_subscribers.values()),
                "pump_radar": len(pump_radar_subscribers)
            }
        },
        "performance": {
            "memory_usage_mb": os.sys.getsizeof({}) / 1024 / 1024,  # Basit bir tahmin
            "python_version": os.sys.version,
            "platform": os.sys.platform
        },
        "visitor_stats": stats
    })

# ==================== APPLICATION START ====================

app_start_time = datetime.utcnow()

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info(f"🚀 ICT SMART PRO v6.1 başlatılıyor...")
    logger.info(f"📡 Host: {host}:{port}")
    logger.info(f"🔗 API Documentation: http://{host}:{port}/api/docs")
    logger.info(f"📊 Health Check: http://{host}:{port}/health")
    
    uvicorn.run(
        app, 
        host=host, 
        port=port, 
        log_level="info",
        access_log=True,
        timeout_keep_alive=30
    )
