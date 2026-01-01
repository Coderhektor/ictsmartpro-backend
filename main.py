"""
ICT SMART PRO - VERSION 7.0
Production Optimized
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

# Configure logging for production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Suppress noisy logs
logging.getLogger("core").setLevel(logging.WARNING)
logging.getLogger("grok_indicators").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

logger = logging.getLogger("ict_smart_pro")

# Core modülleri - Import with error handling
try:
    from core import (
        initialize, cleanup, single_subscribers, all_subscribers, pump_radar_subscribers,
        shared_signals, active_strong_signals, top_gainers, last_update, rt_ticker,
        get_binance_client, price_sources_status, price_pool, get_all_prices_snapshot
    )
    from utils import all_usdt_symbols
    logger.info("✅ Core modülleri başarıyla yüklendi")
except ImportError as e:
    logger.warning(f"⚠️ Core modülleri import hatası: {e}")
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
        logger.info("✅ OpenAI client başlatıldı")
    except Exception as e:
        logger.warning(f"⚠️ OpenAI başlatma hatası: {e}")

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
        
        today = datetime.now().strftime("%Y-%m-%d")
        self.daily_stats[today]["visits"] += 1
        
        if user_id:
            self.active_users.add(user_id)
            self.daily_stats[today]["unique"].add(user_id)
            
        return self.total_visits

    def get_stats(self) -> Dict[str, Any]:
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = self.daily_stats.get(today, {"visits": 0, "unique": set()})
        
        # En popüler sayfalar (max 5)
        top_pages = sorted(self.page_views.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            "total_visits": self.total_visits,
            "active_users": len(self.active_users),
            "today_visits": today_stats["visits"],
            "today_unique": len(today_stats["unique"]),
            "top_pages": dict(top_pages),
            "last_updated": datetime.now().strftime("%H:%M:%S")
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
signal_history = defaultdict(list)

# ==================== TEKNİK ANALİZ FONKSİYONLARI ====================

def calculate_rsi(prices, period=14):
    """RSI hesaplama fonksiyonu"""
    if len(prices) < period + 1:
        return 50
    
    try:
        deltas = prices.diff()
        gain = (deltas.where(deltas > 0, 0)).rolling(window=period).mean()
        loss = (-deltas.where(deltas < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50
    except:
        return 50

def calculate_macd(prices, fast=12, slow=26, signal=9):
    """MACD hesaplama fonksiyonu"""
    if len(prices) < slow + signal:
        return {"trend": "NÖTR"}
    
    try:
        exp1 = prices.ewm(span=fast, adjust=False).mean()
        exp2 = prices.ewm(span=slow, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        
        hist_value = histogram.iloc[-1]
        
        if hist_value > 0:
            trend = "YÜKSELİŞ"
        elif hist_value < 0:
            trend = "DÜŞÜŞ"
        else:
            trend = "NÖTR"
        
        return {"trend": trend}
    except:
        return {"trend": "NÖTR"}

def generate_technical_analysis(df, symbol, timeframe):
    """Basit ve hızlı teknik analiz üretimi"""
    if len(df) < 20:
        return None
    
    try:
        # Fiyat verileri
        current_price = float(df['close'].iloc[-1])
        prev_price = float(df['close'].iloc[-2])
        change_pct = ((current_price - prev_price) / prev_price * 100) if prev_price > 0 else 0
        
        # Teknik göstergeler
        rsi_value = calculate_rsi(df['close'])
        macd_data = calculate_macd(df['close'])
        
        # Hareketli ortalamalar
        ma20 = df['close'].rolling(window=20).mean().iloc[-1] if len(df) >= 20 else current_price
        ma50 = df['close'].rolling(window=50).mean().iloc[-1] if len(df) >= 50 else current_price
        
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
        score = trend_score
        
        # RSI sinyalleri
        if rsi_value > 70:
            score -= 15
        elif rsi_value < 30:
            score += 15
        
        # MACD sinyalleri
        if macd_data['trend'] == "YÜKSELİŞ":
            score += 10
        elif macd_data['trend'] == "DÜŞÜŞ":
            score -= 10
        
        # Sonuç sinyali
        score = max(10, min(95, score))
        
        if score >= 70:
            signal_type = "🚀 GÜÇLÜ ALIM"
            strength = "YÜKSEK"
            color = "green"
        elif score >= 60:
            signal_type = "📈 ALIM"
            strength = "ORTA"
            color = "lightgreen"
        elif score <= 30:
            signal_type = "🔥 GÜÇLÜ SATIM"
            strength = "YÜKSEK"
            color = "red"
        elif score <= 40:
            signal_type = "📉 SATIM"
            strength = "ORTA"
            color = "lightcoral"
        else:
            signal_type = "⏸️ NÖTR"
            strength = "DÜŞÜK"
            color = "gold"
        
        # Killzone belirleme
        now_utc = datetime.utcnow()
        hour = now_utc.hour
        
        if 7 <= hour < 11:
            killzone = "LONDRA"
        elif 12 <= hour < 16:
            killzone = "NEW YORK"
        elif 22 <= hour or hour < 2:
            killzone = "ASYA"
        else:
            killzone = "NORMAL"
        
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
            "rsi": round(rsi_value, 1),
            "macd_trend": macd_data['trend'],
            "trend": trend_strength,
            "ma20": round(ma20, 6 if ma20 < 1 else 4),
            "ma50": round(ma50, 6 if ma50 < 1 else 4),
            "analysis_time": now_utc.strftime("%H:%M:%S UTC"),
            "timestamp": datetime.now().isoformat()
        }
        
        # Sinyal geçmişine ekle (max 5)
        signal_key = f"{symbol}:{timeframe}"
        signal_history[signal_key].append(result)
        if len(signal_history[signal_key]) > 5:
            signal_history[signal_key] = signal_history[signal_key][-5:]
        
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
    version="7.0",
    description="Production Optimized Crypto Signal Platform",
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
    visitor_counter.add_visit(page, visitor_id)
    
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
            await asyncio.sleep(10)  # 10 saniyede bir güncelle
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
    
    try:
        while True:
            await asyncio.sleep(30)  # 30 saniyede bir heartbeat
            await websocket.send_json({"heartbeat": True, "timestamp": datetime.now().isoformat()})
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Signal WebSocket error: {e}")
    finally:
        single_subscribers[channel].discard(websocket)

@app.websocket("/ws/all/{timeframe}")
async def websocket_all_signals(websocket: WebSocket, timeframe: str):
    supported = ["5m", "15m", "1h", "4h", "1d"]  # Sadece önemli timeframeler
    
    if timeframe not in supported:
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    all_subscribers[timeframe].add(websocket)
    
    # Başlangıç sinyallerini gönder (max 20)
    initial_signals = active_strong_signals.get(timeframe, [])[:20]
    await websocket.send_json(initial_signals)
    
    try:
        while True:
            await asyncio.sleep(60)  # 1 dakikada bir güncelle
            await websocket.send_json({
                "ping": True, 
                "timestamp": datetime.now().isoformat()
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
    
    # Başlangıç verilerini gönder (max 10)
    await websocket.send_json({
        "top_gainers": top_gainers[:10], 
        "last_update": last_update,
        "total_coins": len(top_gainers)
    })
    
    try:
        while True:
            await asyncio.sleep(30)  # 30 saniyede bir güncelle
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
    
    # Sistem durumu
    system_status = "🟢"
    binance_status = "🟢" if get_binance_client() else "🔴"
    
    html = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ICT SMART PRO</title>
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
                padding: 40px 0;
            }}
            .title {{
                font-size: 3rem;
                background: linear-gradient(90deg, #00dbde, #fc00ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 20px;
            }}
            .system-status {{
                display: flex;
                justify-content: center;
                gap: 20px;
                margin: 30px 0;
                padding: 20px;
                background: rgba(255, 255, 255, 0.05);
                border-radius: 15px;
            }}
            .status-item {{
                padding: 10px 20px;
                background: rgba(0, 0, 0, 0.3);
                border-radius: 10px;
            }}
            .pump-radar {{
                background: rgba(255, 255, 255, 0.05);
                border-radius: 20px;
                padding: 30px;
                margin: 40px 0;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0;
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
            .change-positive {{ color: #00ff88; font-weight: bold; }}
            .change-negative {{ color: #ff4444; font-weight: bold; }}
            .buttons {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
                margin: 40px 0;
            }}
            .btn {{
                padding: 25px;
                background: linear-gradient(45deg, #fc00ff, #00dbde);
                color: white;
                text-decoration: none;
                border-radius: 15px;
                text-align: center;
                font-size: 1.2rem;
                font-weight: bold;
                transition: transform 0.3s;
            }}
            .btn:hover {{
                transform: scale(1.05);
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
        <div class="user-info">👤 {user}</div>
        {visitor_stats}
        
        <div class="container">
            <div class="header">
                <h1 class="title">ICT SMART PRO</h1>
                <div class="system-status">
                    <div class="status-item">Sistem: {system_status}</div>
                    <div class="status-item">Binance: {binance_status}</div>
                </div>
            </div>
            
            <div class="pump-radar">
                <h2 style="text-align:center;margin-bottom:20px;">🚀 PUMP RADAR</h2>
                <div id="update-info" style="text-align:center;color:#00ffff;margin:15px 0;">Yükleniyor...</div>
                <table>
                    <thead>
                        <tr>
                            <th>SIRA</th>
                            <th>COİN</th>
                            <th>FİYAT</th>
                            <th>DEĞİŞİM</th>
                        </tr>
                    </thead>
                    <tbody id="pump-table">
                        <tr><td colspan="4" style="text-align:center;padding:40px;">Yükleniyor...</td></tr>
                    </tbody>
                </table>
            </div>
            
            <div class="buttons">
                <a href="/signal" class="btn">📊 Tek Coin Sinyal + AI Analiz</a>
                <a href="/signal/all" class="btn">🔥 Tüm Coinleri Tara</a>
                <a href="/debug/sources" class="btn">🔧 Sistem Durumu</a>
            </div>
        </div>
        
        <script>
            const ws = new WebSocket((window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws/pump_radar');
            
            ws.onopen = function() {{
                document.getElementById('update-info').innerHTML = '✅ Bağlantı kuruldu';
            }};
            
            ws.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    if (data.ping) return;
                    
                    if (data.last_update) {{
                        document.getElementById('update-info').innerHTML = '🔄 ' + data.last_update;
                    }}
                    
                    const table = document.getElementById('pump-table');
                    if (!data.top_gainers || data.top_gainers.length === 0) {{
                        table.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:40px;color:#ffd700;">📊 Şu anda aktif pump yok</td></tr>';
                        return;
                    }}
                    
                    let html = '';
                    data.top_gainers.forEach(function(coin, index) {{
                        const changeClass = coin.change > 0 ? 'change-positive' : 'change-negative';
                        const changeSign = coin.change > 0 ? '+' : '';
                        
                        html += `
                            <tr>
                                <td>#${{index + 1}}</td>
                                <td><strong>${{coin.symbol}}</strong></td>
                                <td>$${{(coin.price >= 1 ? coin.price.toFixed(2) : coin.price.toFixed(6))}}</td>
                                <td class="${{changeClass}}">${{changeSign}}${{coin.change.toFixed(2)}}%</td>
                            </tr>
                        `;
                    }});
                    
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
            input, select, button {{
                width: 100%;
                max-width: 400px;
                padding: 12px;
                margin: 10px 0;
                border: none;
                border-radius: 8px;
                background: rgba(255, 255, 255, 0.1);
                color: white;
                font-size: 1rem;
            }}
            button {{
                background: linear-gradient(45deg, #fc00ff, #00dbde);
                font-weight: bold;
                cursor: pointer;
                margin: 10px 5px;
                display: inline-block;
                width: auto;
                min-width: 200px;
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
                height: 500px;
                background: rgba(10, 0, 34, 0.8);
                border-radius: 10px;
                margin: 30px 0;
                overflow: hidden;
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
        </style>
        <script src="https://s3.tradingview.com/tv.js"></script>
    </head>
    <body>
        <div class="user-info">👤 {user}</div>
        {visitor_stats}
        
        <div class="container">
            <div class="header">
                <h1 class="title">📊 TEK COİN CANLI SİNYAL</h1>
            </div>
            
            <div class="controls">
                <input type="text" id="pair" placeholder="Coin (örn: BTC)" value="BTC">
                <select id="timeframe">
                    <option value="5m" selected>5 Dakika</option>
                    <option value="15m">15 Dakika</option>
                    <option value="1h">1 Saat</option>
                    <option value="4h">4 Saat</option>
                    <option value="1d">1 Gün</option>
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
                <a href="/signal/all" class="nav-link">Tüm Coinler →</a>
            </div>
        </div>
        
        <script>
            let signalWs = null;
            let tradingViewWidget = null;
            let currentSymbol = "BTC";
            let currentTimeframe = "5m";
            
            const timeframeMap = {{
                "5m": "5",
                "15m": "15",
                "1h": "60",
                "4h": "240",
                "1d": "D"
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
                
                const tvSymbol = getTradingViewSymbol(currentSymbol);
                const interval = timeframeMap[currentTimeframe] || "5";
                
                if (signalWs) {{
                    signalWs.close();
                    signalWs = null;
                }}
                
                if (tradingViewWidget) {{
                    tradingViewWidget.remove();
                }}
                
                tradingViewWidget = new TradingView.widget({{
                    width: "100%",
                    height: "100%",
                    symbol: tvSymbol,
                    interval: interval,
                    timezone: "Etc/UTC",
                    theme: "dark",
                    style: "1",
                    locale: "tr",
                    container_id: "tradingview_widget"
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
                            📊 Skor: <strong>${{data.score || '?'}}/100</strong> | ${{data.killzone || 'Normal'}}
                        `;
                        
                        if (data.signal && (data.signal.includes('ALIM') || data.signal.includes('YÜKSELİŞ'))) {{
                            card.className = 'signal-card green';
                            text.style.color = '#00ff88';
                        }} else if (data.signal && (data.signal.includes('SATIM') || data.signal.includes('DÜŞÜŞ'))) {{
                            card.className = 'signal-card red';
                            text.style.color = '#ff4444';
                        }} else {{
                            card.className = 'signal-card';
                            text.style.color = '#ffd700';
                        }}
                        
                    }} catch (error) {{
                        console.error('Hata:', error);
                    }}
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
                        body: JSON.stringify({{ 
                            symbol: currentSymbol, 
                            timeframe: currentTimeframe 
                        }})
                    }});
                    
                    const data = await response.json();
                    
                    if (data.success) {{
                        comment.innerHTML = data.analysis.replace(/\\n/g, '<br>');
                    }} else {{
                        comment.innerHTML = '<strong style="color:#ff4444">❌ Analiz hatası:</strong><br>' + data.analysis;
                    }}
                }} catch (err) {{
                    comment.innerHTML = '<strong style="color:#ff4444">❌ Bağlantı hatası:</strong><br>' + err.message;
                }} finally {{
                    btn.disabled = false;
                    btn.innerHTML = "🤖 GRAFİĞİ ANALİZ ET";
                }}
            }}
            
            setTimeout(connectSignal, 1000);
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
            .signal-buy {{ color: #00ff88; font-weight: bold; }}
            .signal-sell {{ color: #ff4444; font-weight: bold; }}
            .signal-neutral {{ color: #ffd700; }}
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
        </style>
    </head>
    <body>
        <div class="user-info">👤 {user}</div>
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
                        </tr>
                    </thead>
                    <tbody id="signals-table">
                        <tr>
                            <td colspan="5" style="text-align: center; padding: 50px;">
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
                            table.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 50px; color: #ffd700;">📊 Şu anda güçlü sinyal bulunmuyor</td></tr>';
                            return;
                        }}
                        
                        let html = '';
                        signals.slice(0, 20).forEach(function(signal, index) {{
                            let signalClass = 'signal-neutral';
                            if (signal.signal && signal.signal.includes('ALIM')) {{
                                signalClass = 'signal-buy';
                            }} else if (signal.signal && signal.signal.includes('SATIM')) {{
                                signalClass = 'signal-sell';
                            }}
                            
                            html += `
                                <tr>
                                    <td>#${{index + 1}}</td>
                                    <td><strong>${{signal.pair ? signal.pair.replace('USDT', '/USDT') : 'N/A'}}</strong></td>
                                    <td class="${{signalClass}}">${{signal.signal || '⏸️ Bekle'}}</td>
                                    <td><strong>${{signal.score || '?'}}/100</strong></td>
                                    <td>$${{(signal.current_price || 0).toFixed(signal.current_price < 1 ? 6 : 4)}}</td>
                                </tr>
                            `;
                        }});
                        
                        table.innerHTML = html;
                        
                    }} catch (error) {{
                        console.error('Hata:', error);
                    }}
                }};
            }}
            
            setTimeout(() => {{
                document.getElementById('timeframe').value = '5m';
                connectAllSignals();
            }}, 500);
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
        
        logger.info(f"Analiz isteği: {symbol} @ {timeframe}")
        
        binance_client = get_binance_client()
        if not binance_client:
            return JSONResponse({
                "analysis": "❌ Binance bağlantısı aktif değil.",
                "success": False
            }, status_code=503)
        
        ccxt_symbol = f"{symbol}/USDT"
        
        interval_map = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
        ccxt_timeframe = interval_map.get(timeframe, "5m")
        
        try:
            klines = await binance_client.fetch_ohlcv(
                ccxt_symbol, 
                timeframe=ccxt_timeframe, 
                limit=100
            )
            
            if not klines or len(klines) < 20:
                return JSONResponse({
                    "analysis": f"❌ {symbol} için yeterli veri yok.",
                    "success": False
                }, status_code=404)
            
            df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume'])
            df.iloc[:,1:] = df.iloc[:,1:].apply(pd.to_numeric, errors='coerce')
            df = df.dropna()
            
            analysis = generate_technical_analysis(df, symbol, timeframe)
            
            if not analysis:
                last_price = float(df['close'].iloc[-1])
                analysis = {
                    "pair": f"{symbol}/USDT",
                    "timeframe": timeframe.upper(),
                    "current_price": round(last_price, 4),
                    "signal": "⏸️ NÖTR",
                    "score": 50,
                    "strength": "ORTA",
                    "killzone": "Normal"
                }
            
            analysis_report = f"""
🔍 <strong>{analysis['pair']}</strong> - <strong>{analysis['timeframe']}</strong>

🎯 <strong>{analysis['signal']}</strong>
📊 <strong>Skor:</strong> {analysis['score']}/100 ({analysis['strength']})
💰 <strong>Fiyat:</strong> ${analysis['current_price']:,.4f}

📈 <strong>Teknik Göstergeler:</strong>
• RSI: {analysis.get('rsi', '?')}
• MACD: {analysis.get('macd_trend', 'NÖTR')}
• Trend: {analysis.get('trend', 'Belirsiz')}

🕐 <strong>Seans:</strong> {analysis['killzone']}
🕒 <strong>Zaman:</strong> {analysis['analysis_time']}

⚠️ <strong>Not:</strong> Bu otomatik analizdir, yatırım tavsiyesi değildir.
"""
            
            return JSONResponse({
                "analysis": analysis_report, 
                "signal_data": analysis, 
                "success": True
            })
            
        except Exception as e:
            logger.error(f"Veri alma hatası: {e}")
            return JSONResponse({
                "analysis": f"❌ {symbol} için veri alınamadı.",
                "success": False
            }, status_code=404)
            
    except Exception as e:
        logger.error(f"Analiz hatası: {e}")
        return JSONResponse({
            "analysis": f"❌ Analiz hatası: {str(e)}",
            "success": False
        }, status_code=500)

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
                    {"type": "text", "text": "Bu kripto grafiğini Türkçe analiz et:"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
                ]
            }],
            max_tokens=500,
            temperature=0.3
        )
        
        return JSONResponse({
            "analysis": response.choices[0].message.content, 
            "success": True
        })
        
    except Exception as e:
        logger.error(f"GPT analiz hatası: {e}")
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
        "version": "7.0",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "binance_connected": get_binance_client() is not None,
            "price_sources_healthy": healthy_sources,
            "symbols_loaded": len(all_usdt_symbols),
            "active_connections": len(price_sources_subscribers)
        },
        "visitor_stats": visitor_counter.get_stats()
    })

@app.get("/admin/visitor-dashboard")
async def visitor_dashboard_page(request: Request):
    user = request.cookies.get("user_email")
    if not user or "admin" not in user.lower():
        return RedirectResponse("/login")
    
    stats = visitor_counter.get_stats()
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Admin Panel</title>
        <style>
            body {{ background: #000; color: #fff; padding: 20px; font-family: monospace; }}
            .dashboard {{ max-width: 800px; margin: 0 auto; }}
            .header {{ text-align: center; margin-bottom: 40px; }}
            .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 20px; margin-bottom: 40px; }}
            .stat-card {{ background: rgba(255, 255, 255, 0.05); padding: 20px; border-radius: 10px; text-align: center; }}
            .stat-value {{ font-size: 2rem; color: #00ff88; margin: 10px 0; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th, td {{ padding: 12px; border-bottom: 1px solid #333; }}
            th {{ background: #00dbde22; color: #00ffff; }}
            .nav {{ text-align: center; margin-top: 30px; }}
            .nav a {{ color: #00dbde; margin: 0 15px; }}
        </style>
    </head>
    <body>
        {get_visitor_stats_html()}
        <div class="dashboard">
            <div class="header">
                <h1>📊 ADMIN PANEL</h1>
                <p>Son Güncelleme: {stats['last_updated']}</p>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div>TOPLAM ZİYARET</div>
                    <div class="stat-value">{stats['total_visits']:,}</div>
                </div>
                <div class="stat-card">
                    <div>AKTİF KULLANICI</div>
                    <div class="stat-value">{stats['active_users']}</div>
                </div>
                <div class="stat-card">
                    <div>BUGÜNKÜ ZİYARET</div>
                    <div class="stat-value">{stats['today_visits']}</div>
                </div>
            </div>
            
            <div class="nav">
                <a href="/">🏠 Ana Sayfa</a>
                <a href="/api/system-status">🔄 Sistem Durumu</a>
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
        <title>Giriş</title>
        <style>
            body {
                background: linear-gradient(135deg, #0a0022, #1a0033, #000);
                color: #fff;
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                margin: 0;
            }
            .login-box {
                background: rgba(0, 0, 0, 0.8);
                padding: 40px;
                border-radius: 20px;
                text-align: center;
                max-width: 400px;
                width: 90%;
            }
            .login-title {
                font-size: 2rem;
                margin-bottom: 30px;
                background: linear-gradient(90deg, #00dbde, #fc00ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
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
                margin-top: 20px;
            }
        </style>
    </head>
    <body>
        <div class="login-box">
            <h1 class="login-title">ICT SMART PRO</h1>
            <form method="post">
                <input type="email" name="email" placeholder="E-posta adresiniz" required>
                <button type="submit">🔓 GİRİŞ YAP</button>
            </form>
            <p style="color:#888;margin-top:20px;">
                Demo amaçlıdır. Herhangi bir e-posta ile giriş yapabilirsiniz.
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
            max_age=2592000,
            httponly=True, 
            samesite="lax",
            secure=request.url.scheme == "https"
        )
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
        <title>Sistem Durumu</title>
        <style>
            body {{ background: #000; color: #fff; padding: 20px; font-family: monospace; }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th, td {{ padding: 12px; border-bottom: 1px solid #333; }}
            th {{ background: #00dbde22; color: #00ffff; }}
            .nav {{ margin-top: 30px; text-align: center; }}
            .nav a {{ color: #00dbde; margin: 0 15px; }}
        </style>
    </head>
    <body>
        {get_visitor_stats_html()}
        <div class="header">
            <h1>🔧 SİSTEM DURUMU</h1>
            <p id="total">Yükleniyor...</p>
        </div>
        
        <table>
            <thead>
                <tr>
                    <th>KAYNAK</th>
                    <th>DURUM</th>
                    <th>COIN SAYISI</th>
                </tr>
            </thead>
            <tbody id="sources-table">
                <tr><td colspan="3" style="text-align:center;">Yükleniyor...</td></tr>
            </tbody>
        </table>
        
        <div class="nav">
            <a href="/">🏠 Ana Sayfa</a>
            <a href="/signal">📊 Sinyal Ekranı</a>
        </div>
        
        <script>
            const ws = new WebSocket((window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws/price_sources');
            
            ws.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    document.getElementById('total').innerText = '📈 Toplam ' + data.total_symbols + ' coin';
                    
                    const table = document.getElementById('sources-table');
                    let html = '';
                    
                    for (const [sourceName, sourceData] of Object.entries(data.sources)) {{
                        const status = sourceData.healthy ? '✅' : '❌';
                        
                        html += `
                            <tr>
                                <td>${{sourceName.toUpperCase()}}</td>
                                <td>${{status}}</td>
                                <td>${{sourceData.symbols_count || 0}}</td>
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
    healthy_sources = 0
    if price_sources_status:
        healthy_sources = sum(1 for v in price_sources_status.values() if v.get("healthy", False))
    
    return JSONResponse({
        "status": "OK",
        "version": "7.0",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "binance_connected": get_binance_client() is not None,
            "price_sources_healthy": healthy_sources,
            "symbols_loaded": len(all_usdt_symbols)
        }
    })

# ==================== APPLICATION START ====================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info(f"🚀 ICT SMART PRO v7.0 başlatılıyor...")
    logger.info(f"📡 Host: {host}:{port}")
    
    uvicorn.run(
        app, 
        host=host, 
        port=port, 
        log_level="info",
        access_log=False
    )
