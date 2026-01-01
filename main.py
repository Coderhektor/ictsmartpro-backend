"""
ICT SMART PRO - VERSION 4.0
Tamamen gerçek borsa verileri ile çalışan kesin sinyal sistemi
"""

import base64
import logging
import asyncio
import json
import hashlib
import os
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Dict, List, Set, Any
from collections import defaultdict

import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from openai import OpenAI

# Core bileşenler
from core import (
    initialize, cleanup, single_subscribers, all_subscribers, pump_radar_subscribers,
    shared_signals, active_strong_signals, top_gainers, last_update, rt_ticker,
    get_binance_client, price_sources_status, price_pool, get_all_prices_snapshot
)
from utils import all_usdt_symbols

# OpenAI (opsiyonel)
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

# Logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ict_smart_pro")
logger.setLevel(logging.INFO)

# ==================== VISITOR COUNTER ====================

class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users: Set[str] = set()
        self.daily_stats: Dict[str, Dict] = defaultdict(lambda: {"visits": 0, "unique": set()})
        self.page_views: Dict[str, int] = defaultdict(int)

    def add_visit(self, page: str, user_id: Optional[str] = None) -> int:
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
        
        return {
            "total_visits": self.total_visits,
            "active_users": len(self.active_users),
            "today_visits": today_stats["visits"],
            "today_unique": len(today_stats["unique"]),
            "page_views": dict(self.page_views),
            "last_updated": datetime.now().strftime("%H:%M:%S")
        }

visitor_counter = VisitorCounter()

def get_visitor_stats_html() -> str:
    stats = visitor_counter.get_stats()
    return f"""
    <div style="position:fixed;top:15px;right:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:clamp(0.8rem, 2vw, 1.2rem);z-index:1000;">
        <div>👁️ Toplam: <strong>{stats['total_visits']}</strong></div>
        <div>🔥 Bugün: <strong>{stats['today_visits']}</strong></div>
        <div>👥 Aktif: <strong>{stats['active_users']}</strong></div>
    </div>
    """

# ==================== GLOBAL STATE ====================

price_sources_subscribers: Set[WebSocket] = set()

# ==================== LIFESPAN ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 ICT SMART PRO Uygulaması başlatılıyor...")
    await initialize()
    logger.info("✅ Uygulama başlatıldı")
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()

# ==================== FASTAPI APP ====================

app = FastAPI(
    lifespan=lifespan,
    title="ICT SMART PRO",
    version="4.0 - REAL-TIME",
    description="Gerçek borsa verileri ile kesin sinyaller",
    docs_url="/docs" if os.getenv("ENVIRONMENT") == "development" else None,
    redoc_url="/redoc" if os.getenv("ENVIRONMENT") == "development" else None
)

# ==================== MIDDLEWARE ====================

@app.middleware("http")
async def count_visitors_middleware(request: Request, call_next):
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        ip = request.client.host or "anonymous"
        visitor_id = hashlib.md5(ip.encode()).hexdigest()[:8]
    
    page = request.url.path
    visitor_counter.add_visit(page, visitor_id)
    
    response = await call_next(request)
    
    if not request.cookies.get("visitor_id"):
        response.set_cookie(
            key="visitor_id",
            value=visitor_id,
            max_age=86400,
            httponly=True,
            samesite="lax"
        )
    
    return response

# ==================== WEBSOCKET ENDPOINTS ====================

@app.websocket("/ws/price_sources")
async def websocket_price_sources(websocket: WebSocket):
    await websocket.accept()
    price_sources_subscribers.add(websocket)
    
    try:
        # İlk veriyi gönder
        await websocket.send_json({
            "sources": price_sources_status,
            "total_symbols": len(price_pool)
        })
        
        # Her 5 saniyede bir güncelle
        while True:
            await asyncio.sleep(5)
            await websocket.send_json({
                "sources": price_sources_status,
                "total_symbols": len(price_pool)
            })
            
    except WebSocketDisconnect:
        price_sources_subscribers.discard(websocket)
    except Exception as e:
        logger.error(f"Price sources WebSocket hatası: {e}")
        price_sources_subscribers.discard(websocket)

@app.websocket("/ws/signal/{pair}/{timeframe}")
async def websocket_signal(websocket: WebSocket, pair: str, timeframe: str):
    await websocket.accept()
    
    # Sembolü temizle ve USDT ekle
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
        # Heartbeat gönder
        while True:
            await asyncio.sleep(15)
            await websocket.send_json({"heartbeat": True, "timestamp": datetime.utcnow().isoformat()})
            
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Signal WebSocket hatası: {e}")
    finally:
        single_subscribers[channel].discard(websocket)

@app.websocket("/ws/all/{timeframe}")
async def websocket_all_signals(websocket: WebSocket, timeframe: str):
    # Desteklenen timeframe'ler
    supported_timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
    
    if timeframe not in supported_timeframes:
        await websocket.close(code=1008, reason="Desteklenmeyen timeframe")
        return
    
    await websocket.accept()
    all_subscribers[timeframe].add(websocket)
    
    # Mevcut sinyalleri gönder
    signals = active_strong_signals.get(timeframe, [])
    await websocket.send_json(signals)
    
    try:
        # Ping gönder
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({
                "ping": True,
                "timestamp": datetime.utcnow().isoformat(),
                "signal_count": len(signals)
            })
            
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"All signals WebSocket hatası: {e}")
    finally:
        all_subscribers[timeframe].discard(websocket)

@app.websocket("/ws/pump_radar")
async def websocket_pump_radar(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    
    # İlk veriyi gönder
    await websocket.send_json({
        "top_gainers": top_gainers,
        "last_update": last_update,
        "total_coins": len(top_gainers)
    })
    
    try:
        # Her 20 saniyede bir ping gönder
        while True:
            await asyncio.sleep(20)
            await websocket.send_json({
                "ping": True,
                "timestamp": datetime.utcnow().isoformat()
            })
            
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Pump radar WebSocket hatası: {e}")
    finally:
        pump_radar_subscribers.discard(websocket)

# ==================== HTTP ENDPOINTS ====================

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    visitor_stats_html = get_visitor_stats_html()
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>ICT SMART PRO - Gerçek Borsa Sinyalleri</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            
            body {{
                background: linear-gradient(135deg, #0a0022, #1a0033, #000);
                color: #fff;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                min-height: 100vh;
                margin: 0;
                padding: 20px 0;
            }}
            
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
            }}
            
            .header {{
                text-align: center;
                padding: 30px 0;
                margin-bottom: 30px;
            }}
            
            .title {{
                font-size: clamp(2.5rem, 6vw, 4.5rem);
                background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-size: 200% auto;
                animation: gradient 8s infinite linear;
                margin-bottom: 20px;
            }}
            
            @keyframes gradient {{
                0% {{ background-position: 0% center; }}
                100% {{ background-position: 200% center; }}
            }}
            
            .update-info {{
                color: #00ffff;
                font-size: clamp(1rem, 3vw, 1.5rem);
                margin: 30px 0;
                text-align: center;
            }}
            
            .stats-table {{
                width: 100%;
                border-collapse: separate;
                border-spacing: 0 10px;
                margin: 40px 0;
            }}
            
            .stats-table th {{
                background: rgba(255, 255, 255, 0.1);
                padding: 15px 20px;
                text-align: left;
                font-size: clamp(0.9rem, 2vw, 1.2rem);
                font-weight: 600;
                color: #00ffff;
            }}
            
            .stats-table tr {{
                background: rgba(255, 255, 255, 0.05);
                transition: all 0.3s ease;
            }}
            
            .stats-table tr:hover {{
                transform: translateY(-3px);
                box-shadow: 0 10px 30px rgba(0, 255, 255, 0.3);
                background: rgba(255, 255, 255, 0.08);
            }}
            
            .stats-table td {{
                padding: 15px 20px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }}
            
            .change-positive {{
                color: #00ff88;
                font-weight: bold;
                text-shadow: 0 0 10px rgba(0, 255, 136, 0.5);
            }}
            
            .change-negative {{
                color: #ff4444;
                font-weight: bold;
                text-shadow: 0 0 10px rgba(255, 68, 68, 0.5);
            }}
            
            .button-container {{
                display: flex;
                flex-direction: column;
                gap: 25px;
                max-width: 600px;
                margin: 50px auto;
            }}
            
            .nav-button {{
                display: block;
                padding: clamp(18px, 4vw, 25px);
                font-size: clamp(1.3rem, 4vw, 1.8rem);
                background: linear-gradient(45deg, #fc00ff, #00dbde);
                color: white;
                text-decoration: none;
                border-radius: 15px;
                text-align: center;
                font-weight: 600;
                box-shadow: 0 10px 40px rgba(255, 0, 255, 0.4);
                transition: all 0.3s ease;
                border: none;
                cursor: pointer;
            }}
            
            .nav-button:hover {{
                transform: scale(1.05);
                box-shadow: 0 15px 50px rgba(255, 0, 255, 0.6);
            }}
            
            .user-info {{
                position: fixed;
                top: 15px;
                left: 15px;
                background: rgba(0, 0, 0, 0.8);
                padding: 10px 20px;
                border-radius: 15px;
                color: #00ff88;
                font-size: clamp(0.8rem, 2vw, 1rem);
                z-index: 1000;
            }}
            
            .loading {{
                text-align: center;
                padding: 60px;
                color: #888;
                font-size: 1.2rem;
            }}
            
            @media (max-width: 768px) {{
                .container {{
                    padding: 10px;
                }}
                
                .stats-table {{
                    font-size: 0.9rem;
                }}
                
                .stats-table th,
                .stats-table td {{
                    padding: 10px 5px;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="user-info">Hoş geldin, {user}</div>
        {visitor_stats_html}
        
        <div class="container">
            <div class="header">
                <h1 class="title">ICT SMART PRO</h1>
                <div class="update-info" id="update-info">📡 Gerçek veriler yükleniyor...</div>
            </div>
            
            <table class="stats-table">
                <thead>
                    <tr>
                        <th>SIRA</th>
                        <th>COİN</th>
                        <th>FİYAT</th>
                        <th>24S DEĞİŞİM</th>
                        <th>HACİM (24s)</th>
                    </tr>
                </thead>
                <tbody id="pump-table">
                    <tr>
                        <td colspan="5" class="loading">
                            🔄 Pump radar verileri yükleniyor...
                        </td>
                    </tr>
                </tbody>
            </table>
            
            <div class="button-container">
                <a href="/signal" class="nav-button">🚀 Tek Coin Canlı Sinyal + Grafik</a>
                <a href="/signal/all" class="nav-button">🔥 Tüm Coinleri Canlı Tara</a>
            </div>
        </div>
        
        <script>
            // Pump radar WebSocket bağlantısı
            const pumpWs = new WebSocket(
                (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + 
                window.location.host + '/ws/pump_radar'
            );
            
            pumpWs.onopen = function() {{
                document.getElementById('update-info').innerHTML = '✅ Gerçek veri bağlantısı kuruldu';
            }};
            
            pumpWs.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    
                    // Ping mesajlarını yoksay
                    if (data.ping) return;
                    
                    // Güncelleme zamanını göster
                    if (data.last_update) {{
                        document.getElementById('update-info').innerHTML = 
                            `🔄 Son güncelleme: <strong>${{data.last_update}}</strong> | 
                             Toplam: <strong>${{data.total_coins || 0}}</strong> coin`;
                    }}
                    
                    // Tabloyu güncelle
                    const tableBody = document.getElementById('pump-table');
                    
                    if (!data.top_gainers || data.top_gainers.length === 0) {{
                        tableBody.innerHTML = `
                            <tr>
                                <td colspan="5" style="text-align: center; padding: 50px; color: #ffd700;">
                                    📊 Şu anda aktif pump hareketi yok
                                </td>
                            </tr>
                        `;
                        return;
                    }}
                    
                    // İlk 15 coin'i göster
                    const top15 = data.top_gainers.slice(0, 15);
                    
                    tableBody.innerHTML = top15.map((coin, index) => {{
                        const changeClass = coin.change > 0 ? 'change-positive' : 'change-negative';
                        const changeSign = coin.change > 0 ? '+' : '';
                        
                        // Fiyat formatlama
                        const formatPrice = (price) => {{
                            if (price >= 1000) {{
                                return price.toLocaleString('en-US', {{ 
                                    minimumFractionDigits: 2, 
                                    maximumFractionDigits: 2 
                                }});
                            }} else if (price >= 1) {{
                                return price.toLocaleString('en-US', {{ 
                                    minimumFractionDigits: 3, 
                                    maximumFractionDigits: 3 
                                }});
                            }} else {{
                                return price.toLocaleString('en-US', {{ 
                                    minimumFractionDigits: 6, 
                                    maximumFractionDigits: 6 
                                }});
                            }}
                        }};
                        
                        // Hacim formatlama
                        const formatVolume = (volume) => {{
                            if (volume >= 1000000) {{
                                return (volume / 1000000).toFixed(2) + 'M';
                            }} else if (volume >= 1000) {{
                                return (volume / 1000).toFixed(2) + 'K';
                            }} else {{
                                return volume.toFixed(2);
                            }}
                        }};
                        
                        return `
                            <tr>
                                <td>#${{index + 1}}</td>
                                <td><strong>${{coin.symbol}}</strong></td>
                                <td>$${{formatPrice(coin.price)}}</td>
                                <td class="${{changeClass}}">${{changeSign}}${{coin.change.toFixed(2)}}%</td>
                                <td>$${{formatVolume(coin.volume || 0)}}</td>
                            </tr>
                        `;
                    }}).join('');
                    
                }} catch (error) {{
                    console.error('Veri işleme hatası:', error);
                }}
            }};
            
            pumpWs.onerror = function() {{
                document.getElementById('update-info').innerHTML = '❌ Veri bağlantı hatası';
            }};
            
            pumpWs.onclose = function() {{
                document.getElementById('update-info').innerHTML = '🔌 Bağlantı kesildi. Sayfayı yenileyin.';
            }};
            
            // Sayfa kapatılırken WebSocket'i kapat
            window.addEventListener('beforeunload', function() {{
                if (pumpWs.readyState === WebSocket.OPEN) {{
                    pumpWs.close();
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)

@app.get("/signal", response_class=HTMLResponse)
async def single_signal_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    visitor_stats_html = get_visitor_stats_html()
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Tek Coin Sinyal | ICT SMART PRO</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            
            body {{
                background: linear-gradient(135deg, #0a0022, #1a0033, #000);
                color: #fff;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                min-height: 100vh;
                margin: 0;
                padding: 20px 0;
            }}
            
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
                display: flex;
                flex-direction: column;
                gap: 30px;
            }}
            
            .header {{
                text-align: center;
                padding: 20px 0;
            }}
            
            .title {{
                font-size: clamp(2rem, 5vw, 3.5rem);
                background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-size: 200% auto;
                animation: gradient 8s infinite linear;
                margin-bottom: 20px;
            }}
            
            @keyframes gradient {{
                0% {{ background-position: 0% center; }}
                100% {{ background-position: 200% center; }}
            }}
            
            .controls {{
                background: rgba(255, 255, 255, 0.08);
                border-radius: 20px;
                padding: 25px;
                text-align: center;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
            }}
            
            .input-group {{
                display: flex;
                flex-direction: column;
                gap: 15px;
                max-width: 500px;
                margin: 0 auto;
            }}
            
            input, select, button {{
                width: 100%;
                padding: 16px 20px;
                font-size: 1.2rem;
                border: none;
                border-radius: 12px;
                background: rgba(255, 255, 255, 0.1);
                color: #fff;
                outline: none;
                transition: all 0.3s ease;
            }}
            
            input:focus, select:focus {{
                background: rgba(255, 255, 255, 0.15);
                box-shadow: 0 0 0 2px #00dbde;
            }}
            
            button {{
                background: linear-gradient(45deg, #fc00ff, #00dbde);
                font-weight: 600;
                cursor: pointer;
                margin-top: 10px;
                transition: all 0.3s ease;
            }}
            
            button:hover {{
                transform: translateY(-3px);
                box-shadow: 0 10px 30px rgba(255, 0, 255, 0.4);
            }}
            
            #analyze-btn {{
                background: linear-gradient(45deg, #00dbde, #ff00ff, #00ffff);
                margin-top: 15px;
            }}
            
            .status {{
                color: #00ffff;
                text-align: center;
                margin: 15px 0;
                font-size: 1.1rem;
                min-height: 24px;
            }}
            
            .signal-card {{
                background: rgba(0, 0, 0, 0.6);
                border-radius: 20px;
                padding: 30px;
                text-align: center;
                min-height: 180px;
                display: flex;
                flex-direction: column;
                justify-content: center;
                transition: all 0.3s ease;
            }}
            
            .signal-card.green {{
                border-left: 8px solid #00ff88;
                box-shadow: 0 0 40px rgba(0, 255, 136, 0.3);
            }}
            
            .signal-card.red {{
                border-left: 8px solid #ff4444;
                box-shadow: 0 0 40px rgba(255, 68, 68, 0.3);
            }}
            
            .signal-card.neutral {{
                border-left: 8px solid #ffd700;
                box-shadow: 0 0 40px rgba(255, 215, 0, 0.3);
            }}
            
            .signal-text {{
                font-size: clamp(1.8rem, 4vw, 2.8rem);
                font-weight: 700;
                margin-bottom: 15px;
            }}
            
            .signal-details {{
                font-size: 1.1rem;
                opacity: 0.9;
                line-height: 1.6;
            }}
            
            .ai-analysis {{
                background: rgba(13, 0, 51, 0.95);
                border-radius: 20px;
                padding: 25px;
                border: 3px solid #00dbde;
                display: none;
                max-height: 400px;
                overflow-y: auto;
            }}
            
            .ai-analysis h3 {{
                color: #00dbde;
                text-align: center;
                margin-bottom: 20px;
                font-size: 1.5rem;
            }}
            
            .chart-container {{
                width: 100%;
                max-width: 1000px;
                margin: 30px auto;
                border-radius: 20px;
                overflow: hidden;
                box-shadow: 0 15px 50px rgba(0, 255, 255, 0.2);
                background: rgba(10, 0, 34, 0.8);
                height: 550px;
            }}
            
            #tradingview_widget {{
                width: 100%;
                height: 100%;
            }}
            
            .navigation {{
                text-align: center;
                margin-top: 30px;
                font-size: 1.1rem;
            }}
            
            .navigation a {{
                color: #00dbde;
                text-decoration: none;
                margin: 0 15px;
                transition: color 0.3s ease;
            }}
            
            .navigation a:hover {{
                color: #fc00ff;
                text-decoration: underline;
            }}
            
            .user-info {{
                position: fixed;
                top: 15px;
                left: 15px;
                background: rgba(0, 0, 0, 0.8);
                padding: 10px 20px;
                border-radius: 15px;
                color: #00ff88;
                font-size: clamp(0.8rem, 2vw, 1rem);
                z-index: 1000;
            }}
            
            @media (max-width: 768px) {{
                .container {{
                    padding: 10px;
                    gap: 20px;
                }}
                
                .controls {{
                    padding: 15px;
                }}
                
                .signal-card {{
                    padding: 20px;
                }}
                
                .chart-container {{
                    height: 400px;
                }}
            }}
        </style>
        <script src="https://s3.tradingview.com/tv.js"></script>
    </head>
    <body>
        <div class="user-info">Hoş geldin, {user}</div>
        {visitor_stats_html}
        
        <div class="container">
            <div class="header">
                <h1 class="title">📊 TEK COİN CANLI SİNYAL</h1>
            </div>
            
            <div class="controls">
                <div class="input-group">
                    <input type="text" id="pair" placeholder="Coin adı girin (örn: BTC, ETH)" value="BTC">
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
                    <button onclick="connectSignal()">🔴 CANLI SİNYAL BAĞLANTISI KUR</button>
                    <button id="analyze-btn" onclick="analyzeChartWithAI()">🤖 GRAFİĞİ ANALİZ ET</button>
                </div>
                <div class="status" id="connection-status">Grafik yükleniyor...</div>
            </div>
            
            <div id="signal-card" class="signal-card neutral">
                <div id="signal-text" class="signal-text" style="color: #ffd700;">
                    Sinyal bağlantısı kurulmadı
                </div>
                <div id="signal-details" class="signal-details">
                    Canlı sinyal için yukarıdaki butona tıklayın.
                </div>
            </div>
            
            <div id="ai-analysis" class="ai-analysis">
                <h3>🤖 TEKNİK ANALİZ RAPORU</h3>
                <p id="ai-comment">Analiz için butona tıklayın.</p>
            </div>
            
            <div class="chart-container">
                <div id="tradingview_widget"></div>
            </div>
            
            <div class="navigation">
                <a href="/">← Ana Sayfa</a>
                <a href="/signal/all">Tüm Coinler →</a>
            </div>
        </div>
        
        <script>
            let signalWs = null;
            let tradingViewWidget = null;
            
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
            
            function getTradingViewSymbol() {{
                let pair = document.getElementById('pair').value.trim().toUpperCase();
                if (!pair.endsWith("USDT")) {{
                    pair += "USDT";
                }}
                return "BINANCE:" + pair;
            }}
            
            function getWebSocketSymbol() {{
                return document.getElementById('pair').value.trim().toUpperCase();
            }}
            
            async function connectSignal() {{
                const symbol = getWebSocketSymbol();
                const timeframe = document.getElementById('timeframe').value;
                const tvSymbol = getTradingViewSymbol();
                const interval = timeframeMap[timeframe] || "5";
                
                // Önceki bağlantıları kapat
                if (signalWs) {{
                    signalWs.close();
                    signalWs = null;
                }}
                
                if (tradingViewWidget) {{
                    tradingViewWidget.remove();
                    tradingViewWidget = null;
                }}
                
                // TradingView grafiğini yükle
                tradingViewWidget = new TradingView.widget({{
                    width: "100%",
                    height: "100%",
                    symbol: tvSymbol,
                    interval: interval,
                    timezone: "Etc/UTC",
                    theme: "dark",
                    style: "1",
                    locale: "tr",
                    toolbar_bg: "#f1f3f6",
                    enable_publishing: false,
                    hide_side_toolbar: false,
                    allow_symbol_change: false,
                    container_id: "tradingview_widget",
                    studies: [
                        "RSI@tv-basicstudies",
                        "MACD@tv-basicstudies",
                        "Volume@tv-basicstudies"
                    ]
                }});
                
                // TradingView yüklendiğinde
                tradingViewWidget.onChartReady(function() {{
                    document.getElementById('connection-status').innerHTML = 
                        \`✅ Grafik yüklendi: \${symbol} \${timeframe.toUpperCase()}\`;
                }});
                
                // WebSocket bağlantısı kur
                const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
                signalWs = new WebSocket(
                    protocol + window.location.host + '/ws/signal/' + symbol + '/' + timeframe
                );
                
                signalWs.onopen = function() {{
                    document.getElementById('connection-status').innerHTML = 
                        \`✅ \${symbol} \${timeframe.toUpperCase()} canlı sinyal akışı başladı!\`;
                }};
                
                signalWs.onmessage = function(event) {{
                    try {{
                        // Heartbeat mesajlarını yoksay
                        if (event.data.includes('heartbeat')) return;
                        
                        const data = JSON.parse(event.data);
                        const card = document.getElementById('signal-card');
                        const text = document.getElementById('signal-text');
                        const details = document.getElementById('signal-details');
                        
                        // Sinyal metnini güncelle
                        text.innerHTML = data.signal || "⏸️ Sinyal bekleniyor...";
                        
                        // Detayları güncelle
                        details.innerHTML = \`
                            <strong>\${data.pair || symbol + '/USDT'}</strong><br>
                            💰 Fiyat: <strong>\$\${(data.current_price || 0).toLocaleString('en-US', {{ 
                                minimumFractionDigits: 4, 
                                maximumFractionDigits: 6 
                            }})}</strong><br>
                            📊 Skor: <strong>\${data.score || '?'}/100</strong> | \${data.killzone || 'Normal'}<br>
                            🕒 \${data.last_update ? 'Son: ' + data.last_update : ''}<br>
                            <small>🎯 \${data.triggers || 'Veri yükleniyor...'}</small>
                        \`;
                        
                        // Sinyal rengini ayarla
                        if (data.signal && data.signal.includes('ALIM')) {{
                            card.className = 'signal-card green';
                            text.style.color = '#00ff88';
                        }} else if (data.signal && data.signal.includes('SATIM')) {{
                            card.className = 'signal-card red';
                            text.style.color = '#ff4444';
                        }} else {{
                            card.className = 'signal-card neutral';
                            text.style.color = '#ffd700';
                        }}
                        
                    }} catch (error) {{
                        console.error('Sinyal verisi işleme hatası:', error);
                    }}
                }};
                
                signalWs.onerror = function() {{
                    document.getElementById('connection-status').innerHTML = 
                        "❌ WebSocket bağlantı hatası";
                }};
                
                signalWs.onclose = function() {{
                    document.getElementById('connection-status').innerHTML = 
                        "🔌 Sinyal bağlantısı kapandı. Yeniden bağlanmak için butona tıklayın.";
                }};
            }}
            
            async function analyzeChartWithAI() {{
                const analyzeBtn = document.getElementById('analyze-btn');
                const analysisBox = document.getElementById('ai-analysis');
                const analysisText = document.getElementById('ai-comment');
                const symbol = getWebSocketSymbol();
                const timeframe = document.getElementById('timeframe').value;
                
                // Butonu devre dışı bırak
                analyzeBtn.disabled = true;
                analyzeBtn.innerHTML = "⏳ Analiz ediliyor...";
                
                // Analiz kutusunu göster
                analysisBox.style.display = 'block';
                analysisText.innerHTML = "📊 Sunucuya istek gönderiliyor... Lütfen bekleyin.";
                
                try {{
                    const response = await fetch('/api/analyze-chart', {{
                        method: 'POST',
                        headers: {{ 
                            'Content-Type': 'application/json'
                        }},
                        body: JSON.stringify({{
                            symbol: symbol,
                            timeframe: timeframe
                        }})
                    }});
                    
                    const data = await response.json();
                    
                    if (data.success) {{
                        analysisText.innerHTML = data.analysis.replace(/\\n/g, '<br>');
                    }} else {{
                        analysisText.innerHTML = \`
                            <strong style="color:#ff4444">❌ Analiz hatası:</strong><br>
                            \${data.analysis || 'Bilinmeyen hata'}
                        \`;
                    }}
                    
                }} catch (error) {{
                    analysisText.innerHTML = \`
                        <strong style="color:#ff4444">❌ Bağlantı hatası:</strong><br>
                        \${error.message || 'Sunucuya ulaşılamıyor'}
                    \`;
                    console.error('Analiz hatası:', error);
                    
                }} finally {{
                    // Butonu tekrar aktif et
                    analyzeBtn.disabled = false;
                    analyzeBtn.innerHTML = "🤖 GRAFİĞİ ANALİZ ET";
                }}
            }}
            
            // Sayfa yüklendiğinde otomatik bağlan
            document.addEventListener('DOMContentLoaded', function() {{
                setTimeout(connectSignal, 1000);
            }});
            
            // Sayfa kapatılırken WebSocket'i kapat
            window.addEventListener('beforeunload', function() {{
                if (signalWs && signalWs.readyState === WebSocket.OPEN) {{
                    signalWs.close();
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)

@app.get("/signal/all", response_class=HTMLResponse)
async def all_signals_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    visitor_stats_html = get_visitor_stats_html()
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Tüm Coinler | ICT SMART PRO</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            
            body {{
                background: linear-gradient(135deg, #0a0022, #1a0033, #000);
                color: #fff;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                min-height: 100vh;
                margin: 0;
                padding: 20px 0;
            }}
            
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
            }}
            
            .header {{
                text-align: center;
                padding: 20px 0;
                margin-bottom: 30px;
            }}
            
            .title {{
                font-size: clamp(2rem, 5vw, 3rem);
                background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-size: 200% auto;
                animation: gradient 8s infinite linear;
                margin-bottom: 20px;
            }}
            
            @keyframes gradient {{
                0% {{ background-position: 0% center; }}
                100% {{ background-position: 200% center; }}
            }}
            
            .controls {{
                background: rgba(255, 255, 255, 0.08);
                border-radius: 20px;
                padding: 20px;
                text-align: center;
                margin: 20px 0;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
            }}
            
            select {{
                width: 90%;
                max-width: 400px;
                padding: 15px;
                margin: 10px;
                font-size: 1.1rem;
                border: none;
                border-radius: 12px;
                background: rgba(255, 255, 255, 0.1);
                color: #fff;
                outline: none;
                transition: all 0.3s ease;
            }}
            
            select:focus {{
                background: rgba(255, 255, 255, 0.15);
                box-shadow: 0 0 0 2px #00dbde;
            }}
            
            .status {{
                color: #00ffff;
                text-align: center;
                margin: 15px;
                font-size: 1.1rem;
                min-height: 24px;
            }}
            
            .table-container {{
                overflow-x: auto;
                margin: 30px 0;
                background: rgba(0, 0, 0, 0.3);
                border-radius: 15px;
                padding: 15px;
            }}
            
            .signals-table {{
                width: 100%;
                border-collapse: collapse;
                min-width: 800px;
            }}
            
            .signals-table th {{
                background: rgba(255, 255, 255, 0.1);
                padding: 16px 12px;
                text-align: left;
                font-weight: 600;
                color: #00ffff;
                position: sticky;
                top: 0;
                z-index: 10;
                border-bottom: 2px solid rgba(0, 255, 255, 0.3);
            }}
            
            .signals-table tr {{
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                transition: all 0.3s ease;
            }}
            
            .signals-table tr:hover {{
                background: rgba(0, 255, 255, 0.08);
                transform: scale(1.01);
            }}
            
            .signals-table td {{
                padding: 14px 12px;
                vertical-align: middle;
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
            
            .score-high {{
                background: rgba(0, 255, 136, 0.15);
            }}
            
            .score-medium {{
                background: rgba(255, 215, 0, 0.15);
            }}
            
            .score-low {{
                background: rgba(255, 68, 68, 0.15);
            }}
            
            .navigation {{
                text-align: center;
                margin-top: 40px;
                font-size: 1.1rem;
            }}
            
            .navigation a {{
                color: #00dbde;
                text-decoration: none;
                margin: 0 15px;
                transition: color 0.3s ease;
            }}
            
            .navigation a:hover {{
                color: #fc00ff;
                text-decoration: underline;
            }}
            
            .user-info {{
                position: fixed;
                top: 15px;
                left: 15px;
                background: rgba(0, 0, 0, 0.8);
                padding: 10px 20px;
                border-radius: 15px;
                color: #00ff88;
                font-size: clamp(0.8rem, 2vw, 1rem);
                z-index: 1000;
            }}
            
            .loading {{
                text-align: center;
                padding: 60px;
                color: #888;
                font-size: 1.2rem;
            }}
            
            @media (max-width: 768px) {{
                .container {{
                    padding: 10px;
                }}
                
                .controls {{
                    padding: 15px;
                }}
                
                .signals-table th,
                .signals-table td {{
                    padding: 10px 8px;
                    font-size: 0.9rem;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="user-info">Hoş geldin, {user}</div>
        {visitor_stats_html}
        
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
            
            <div class="table-container">
                <table class="signals-table">
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
                    <tbody id="signals-table-body">
                        <tr>
                            <td colspan="7" class="loading">
                                📊 Zaman dilimi seçerek sinyalleri görüntüleyin...
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <div class="navigation">
                <a href="/">← Ana Sayfa</a>
                <a href="/signal">Tek Coin Sinyal →</a>
            </div>
        </div>
        
        <script>
            let allSignalsWs = null;
            
            function connectAllSignals() {{
                const timeframe = document.getElementById('timeframe').value;
                document.getElementById('connection-status').innerHTML = 
                    \`🔄 \${timeframe.toUpperCase()} sinyalleri yükleniyor...\`;
                
                // Önceki bağlantıyı kapat
                if (allSignalsWs) {{
                    allSignalsWs.close();
                }}
                
                // Yeni WebSocket bağlantısı kur
                const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
                allSignalsWs = new WebSocket(
                    protocol + window.location.host + '/ws/all/' + timeframe
                );
                
                allSignalsWs.onopen = function() {{
                    document.getElementById('connection-status').innerHTML = 
                        \`✅ \${timeframe.toUpperCase()} canlı sinyal akışı başladı!\`;
                }};
                
                allSignalsWs.onmessage = function(event) {{
                    try {{
                        // Ping mesajlarını yoksay
                        if (event.data.includes('ping')) return;
                        
                        const signals = JSON.parse(event.data);
                        const tableBody = document.getElementById('signals-table-body');
                        
                        if (!signals || signals.length === 0) {{
                            tableBody.innerHTML = \`
                                <tr>
                                    <td colspan="7" style="text-align: center; padding: 50px; color: #ffd700;">
                                        📊 Şu anda güçlü sinyal bulunmuyor
                                    </td>
                                </tr>
                            \`;
                            return;
                        }}
                        
                        // İlk 50 sinyali göster
                        const topSignals = signals.slice(0, 50);
                        
                        tableBody.innerHTML = topSignals.map((signal, index) => {{
                            // Skor sınıfını belirle
                            let scoreClass = '';
                            if (signal.score >= 75) {{
                                scoreClass = 'score-high';
                            }} else if (signal.score >= 50) {{
                                scoreClass = 'score-medium';
                            }} else {{
                                scoreClass = 'score-low';
                            }}
                            
                            // Sinyal sınıfını belirle
                            let signalClass = 'signal-neutral';
                            if (signal.signal && signal.signal.includes('ALIM')) {{
                                signalClass = 'signal-buy';
                            }} else if (signal.signal && signal.signal.includes('SATIM')) {{
                                signalClass = 'signal-sell';
                            }}
                            
                            return \`
                                <tr class="\${scoreClass}">
                                    <td><strong>#\${index + 1}</strong></td>
                                    <td><strong>\${signal.pair ? signal.pair.replace('USDT', '/USDT') : 'N/A'}</strong></td>
                                    <td class="\${signalClass}">\${signal.signal || '⏸️ Bekle'}</td>
                                    <td><strong>\${signal.score || '?'}/100</strong></td>
                                    <td style="font-family: monospace;">
                                        \$\${(signal.current_price || 0).toLocaleString('en-US', {{ 
                                            minimumFractionDigits: 4, 
                                            maximumFractionDigits: 6 
                                        }})}
                                    </td>
                                    <td>\${signal.killzone || 'Normal'}</td>
                                    <td>\${signal.last_update || ''}</td>
                                </tr>
                            \`;
                        }}).join('');
                        
                    }} catch (error) {{
                        console.error('Sinyal verisi işleme hatası:', error);
                    }}
                }};
                
                allSignalsWs.onerror = function() {{
                    document.getElementById('connection-status').innerHTML = 
                        "❌ WebSocket bağlantı hatası";
                }};
                
                allSignalsWs.onclose = function() {{
                    document.getElementById('connection-status').innerHTML = 
                        "🔌 Bağlantı kapandı. Zaman dilimi seçerek tekrar bağlanın.";
                }};
            }}
            
            // Sayfa yüklendiğinde otomatik bağlan
            document.addEventListener('DOMContentLoaded', function() {{
                document.getElementById('timeframe').value = '5m';
                setTimeout(connectAllSignals, 500);
            }});
            
            // Sayfa kapatılırken WebSocket'i kapat
            window.addEventListener('beforeunload', function() {{
                if (allSignalsWs && allSignalsWs.readyState === WebSocket.OPEN) {{
                    allSignalsWs.close();
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)

# ==================== API ENDPOINTS ====================

@app.post("/api/analyze-chart")
async def analyze_chart_endpoint(request: Request):
    """
    Grafik analizi yap ve sinyal üret
    """
    try:
        body = await request.json()
        symbol = body.get("symbol", "BTC").upper()
        timeframe = body.get("timeframe", "5m")
        
        logger.info(f"Grafik analizi isteği: {symbol} @ {timeframe}")
        
        # Binance client'ını al
        binance_client = get_binance_client()
        if not binance_client:
            return JSONResponse({
                "analysis": "❌ Binance bağlantısı aktif değil.",
                "success": False
            }, status_code=503)
        
        # Sembolü hazırla
        ccxt_symbol = f"{symbol}/USDT"
        
        # Timeframe mapping
        interval_map = {
            "1m": "1m", "3m": "3m", "5m": "5m",
            "15m": "15m", "30m": "30m", "1h": "1h",
            "4h": "4h", "1d": "1d", "1w": "1w"
        }
        ccxt_timeframe = interval_map.get(timeframe, "5m")
        
        # Mum verilerini al
        klines = await binance_client.fetch_ohlcv(
            ccxt_symbol,
            timeframe=ccxt_timeframe,
            limit=200
        )
        
        if not klines or len(klines) < 50:
            return JSONResponse({
                "analysis": f"❌ Yetersiz veri: {len(klines) if klines else 0} mum",
                "success": False
            }, status_code=404)
        
        # DataFrame oluştur
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume'
        ])
        
        # Sayısal verilere dönüştür
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # NaN değerleri temizle
        df = df.dropna().tail(100)
        
        # Sinyal üret
        signal = None
        try:
            from indicators import generate_ict_signal, generate_simple_signal
            signal = generate_ict_signal(df, symbol, timeframe) or generate_simple_signal(df, symbol, timeframe)
        except Exception as e:
            logger.warning(f"Indicator modülü hatası: {e}")
            # Fallback sinyal üret
            last_price = float(df['close'].iloc[-1])
            prev_price = float(df['close'].iloc[-2])
            change = ((last_price - prev_price) / prev_price * 100) if prev_price > 0 else 0
            
            signal = {
                "pair": f"{symbol}/USDT",
                "timeframe": timeframe.upper(),
                "current_price": round(last_price, 6 if last_price < 1 else 4),
                "signal": "🚀 ALIM" if change > 0.3 else "🔥 SATIM" if change < -0.3 else "⏸️ NÖTR",
                "score": min(95, max(40, int(50 + abs(change) * 10))),
                "strength": "YÜKSEK" if abs(change) > 2 else "ORTA" if abs(change) > 1 else "ZAYIF",
                "killzone": "Normal",
                "triggers": f"Fiyat değişimi: {change:+.2f}%",
                "last_update": datetime.utcnow().strftime("%H:%M:%S UTC")
            }
        
        if not signal:
            last_price = float(df['close'].iloc[-1])
            signal = {
                "pair": f"{symbol}/USDT",
                "timeframe": timeframe.upper(),
                "current_price": round(last_price, 6 if last_price < 1 else 4),
                "signal": "⏸️ NÖTR",
                "score": 50,
                "strength": "ORTA",
                "killzone": "Normal",
                "triggers": "Yeterli veri yok",
                "last_update": datetime.utcnow().strftime("%H:%M:%S UTC")
            }
        
        # Analiz raporu oluştur
        analysis_report = f"""
🔍 <strong>{symbol}/USDT</strong> {timeframe.upper()} TEKNİK ANALİZ RAPORU

🎯 <strong>SİNYAL:</strong> {signal['signal']}
📊 <strong>SKOR:</strong> {signal['score']}/100 ({signal['strength']})
💰 <strong>FİYAT:</strong> ${signal['current_price']:,.6f}
🕐 <strong>KİLLZONE:</strong> {signal['killzone']}
🕒 <strong>SON GÜNCELLEME:</strong> {signal['last_update']}

🎯 <strong>TETİKLEYENLER:</strong>
• {signal.get('triggers', 'Veri yok')}

📈 <strong>ÖZET:</strong>
{symbol.upper()}/USDT için <strong>{signal['signal']}</strong> sinyali üretildi. 
Skor: <strong>{signal['score']}/100</strong>

⚠️ <strong>UYARI:</strong> Bu bir yatırım tavsiyesi değildir. 
Kendi araştırmanızı yapmadan işlem yapmayın.
"""
        
        return JSONResponse({
            "analysis": analysis_report,
            "signal_data": signal,
            "success": True
        })
        
    except Exception as e:
        logger.exception(f"Analiz hatası: {e}")
        return JSONResponse({
            "analysis": "❌ Sunucu hatası: Teknik analiz yapılamadı",
            "success": False
        }, status_code=500)

@app.post("/api/gpt-analyze")
async def gpt_analyze_endpoint(image_file: UploadFile = File(...)):
    """
    OpenAI GPT ile grafik analizi
    """
    if not openai_client:
        return JSONResponse({
            "error": "OpenAI API anahtarı yok"
        }, status_code=501)
    
    try:
        # Resmi oku ve base64'e çevir
        image_data = await image_file.read()
        image_b64 = base64.b64encode(image_data).decode('utf-8')
        
        # OpenAI API'yi çağır
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": """Bu bir kripto para grafiği. Lütfen Türkçe, net ve profesyonel bir teknik analiz yap:

1. MEVCUT TREND (Yükseliş/Alçalış/Yatay)
2. ÖNEMLİ DESTEK/DİRENÇ SEVİYELERİ
3. MUM FORMASYONLARI (Engulfing, Doji, Hammer vb.)
4. İNDİKATÖR DURUMLARI (RSI, MACD)
5. KISA VADELİ ÖNERİ (Stop Loss/Take Profit ile)
6. RİSK SEVİYESİ (Düşük/Orta/Yüksek)

Analizi maddeler halinde yap ve net ifadeler kullan."""
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}"
                        }
                    }
                ]
            }],
            max_tokens=1500,
            temperature=0.3
        )
        
        analysis = response.choices[0].message.content
        
        return JSONResponse({
            "analysis": analysis,
            "success": True
        })
        
    except Exception as e:
        logger.exception(f"GPT analiz hatası: {e}")
        return JSONResponse({
            "error": f"GPT analiz hatası: {str(e)}",
            "success": False
        }, status_code=500)

@app.get("/api/visitor-stats")
async def get_visitor_stats():
    """
    Ziyaretçi istatistiklerini getir
    """
    stats = visitor_counter.get_stats()
    return JSONResponse(stats)

@app.get("/admin/visitor-dashboard", response_class=HTMLResponse)
async def visitor_dashboard_page(request: Request):
    """
    Admin ziyaretçi dashboard'u
    """
    user = request.cookies.get("user_email")
    if not user or "admin" not in user.lower():
        return RedirectResponse("/login")
    
    stats = visitor_counter.get_stats()
    
    # Sayfa görüntülemelerini sırala
    page_rows = ""
    for page, views in sorted(stats['page_views'].items(), key=lambda x: x[1], reverse=True):
        page_rows += f"<tr><td>{page}</td><td><strong>{views:,}</strong></td></tr>"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Admin Panel - Ziyaretçi İstatistikleri</title>
        <style>
            body {{
                background: #000;
                color: #fff;
                font-family: sans-serif;
                padding: 20px;
                margin: 0;
            }}
            
            .container {{
                max-width: 1000px;
                margin: 0 auto;
            }}
            
            .header {{
                text-align: center;
                margin-bottom: 40px;
                padding-bottom: 20px;
                border-bottom: 2px solid #00dbde;
            }}
            
            .header h1 {{
                color: #00dbde;
                font-size: 2.5rem;
                margin-bottom: 10px;
            }}
            
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-bottom: 40px;
            }}
            
            .stat-card {{
                background: rgba(255, 255, 255, 0.05);
                padding: 25px;
                border-radius: 15px;
                text-align: center;
                box-shadow: 0 5px 20px rgba(0, 0, 0, 0.3);
                transition: transform 0.3s ease;
            }}
            
            .stat-card:hover {{
                transform: translateY(-5px);
                box-shadow: 0 10px 30px rgba(0, 219, 222, 0.2);
            }}
            
            .stat-value {{
                font-size: 2.5rem;
                font-weight: bold;
                color: #00ff88;
                margin: 10px 0;
            }}
            
            .stat-label {{
                color: #aaa;
                font-size: 1.1rem;
            }}
            
            .table-container {{
                background: rgba(255, 255, 255, 0.05);
                border-radius: 15px;
                padding: 20px;
                margin-top: 30px;
            }}
            
            .table-container h2 {{
                color: #00dbde;
                margin-bottom: 20px;
            }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
            }}
            
            th {{
                background: rgba(0, 219, 222, 0.2);
                padding: 15px;
                text-align: left;
                color: #00ffff;
                border-bottom: 2px solid #00dbde;
            }}
            
            td {{
                padding: 12px 15px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }}
            
            tr:hover {{
                background: rgba(255, 255, 255, 0.05);
            }}
            
            .back-link {{
                display: inline-block;
                margin-top: 30px;
                color: #00dbde;
                text-decoration: none;
                font-size: 1.1rem;
                padding: 10px 20px;
                border: 2px solid #00dbde;
                border-radius: 8px;
                transition: all 0.3s ease;
            }}
            
            .back-link:hover {{
                background: #00dbde;
                color: #000;
            }}
            
            .update-time {{
                text-align: center;
                color: #888;
                margin-top: 20px;
                font-size: 0.9rem;
            }}
        </style>
    </head>
    <body>
        {get_visitor_stats_html()}
        
        <div class="container">
            <div class="header">
                <h1>📊 ADMIN PANEL</h1>
                <p>Ziyaretçi İstatistikleri</p>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">TOPLAM ZİYARET</div>
                    <div class="stat-value">{stats['total_visits']:,}</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-label">BUGÜNKÜ ZİYARET</div>
                    <div class="stat-value">{stats['today_visits']:,}</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-label">AKTİF KULLANICI</div>
                    <div class="stat-value">{stats['active_users']}</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-label">BUGÜNKÜ TEKİL</div>
                    <div class="stat-value">{stats['today_unique']}</div>
                </div>
            </div>
            
            <div class="table-container">
                <h2>📈 SAYFA GÖRÜNTÜLEMELERİ</h2>
                <table>
                    <thead>
                        <tr>
                            <th>SAYFA</th>
                            <th>GÖRÜNTÜLENME</th>
                        </tr>
                    </thead>
                    <tbody>
                        {page_rows}
                    </tbody>
                </table>
            </div>
            
            <div class="update-time">
                Son güncelleme: {stats['last_updated']}
            </div>
            
            <a href="/" class="back-link">← Ana Sayfaya Dön</a>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """
    Giriş sayfası
    """
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Giriş Yap | ICT SMART PRO</title>
        <style>
            body {
                background: linear-gradient(135deg, #0a0022, #1a0033, #000);
                color: #fff;
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100vh;
                margin: 0;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            
            .login-container {
                background: rgba(0, 0, 0, 0.7);
                padding: 40px;
                border-radius: 20px;
                text-align: center;
                max-width: 400px;
                width: 90%;
                box-shadow: 0 15px 50px rgba(0, 219, 222, 0.3);
                border: 2px solid #00dbde;
            }
            
            .login-header {
                margin-bottom: 30px;
            }
            
            .login-header h2 {
                color: #00dbde;
                font-size: 2rem;
                margin-bottom: 10px;
                background: linear-gradient(90deg, #00dbde, #fc00ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            
            .login-form {
                display: flex;
                flex-direction: column;
                gap: 20px;
            }
            
            input {
                width: 100%;
                padding: 15px;
                border: none;
                border-radius: 10px;
                background: rgba(255, 255, 255, 0.1);
                color: #fff;
                font-size: 1rem;
                outline: none;
                transition: all 0.3s ease;
            }
            
            input:focus {
                background: rgba(255, 255, 255, 0.15);
                box-shadow: 0 0 0 2px #00dbde;
            }
            
            input::placeholder {
                color: #aaa;
            }
            
            button {
                width: 100%;
                padding: 15px;
                background: linear-gradient(45deg, #00dbde, #fc00ff);
                border: none;
                border-radius: 10px;
                color: #fff;
                font-size: 1.1rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
            }
            
            button:hover {
                transform: translateY(-3px);
                box-shadow: 0 10px 30px rgba(255, 0, 255, 0.4);
            }
            
            .login-note {
                margin-top: 20px;
                color: #888;
                font-size: 0.9rem;
                line-height: 1.5;
            }
            
            .error-message {
                color: #ff4444;
                margin-top: 10px;
                display: none;
            }
        </style>
    </head>
    <body>
        <div class="login-container">
            <div class="login-header">
                <h2>🔐 ICT SMART PRO</h2>
                <p>Gerçek Borsa Sinyalleri</p>
            </div>
            
            <form method="post" action="/login" class="login-form">
                <input 
                    type="email" 
                    name="email" 
                    placeholder="E-posta adresiniz" 
                    required
                >
                
                <button type="submit">
                    GİRİŞ YAP
                </button>
            </form>
            
            <div class="login-note">
                📝 Demo için herhangi bir e-posta adresi kullanabilirsiniz.
                <br>
                Örnek: kullanici@ornek.com
            </div>
            
            <div id="error-message" class="error-message"></div>
            
            <script>
                // Form gönderildiğinde hata kontrolü
                document.querySelector('form').addEventListener('submit', function(e) {
                    const email = document.querySelector('input[name="email"]').value;
                    const errorDiv = document.getElementById('error-message');
                    
                    if (!email.includes('@') || !email.includes('.')) {
                        e.preventDefault();
                        errorDiv.textContent = 'Lütfen geçerli bir e-posta adresi girin.';
                        errorDiv.style.display = 'block';
                    }
                });
            </script>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)

@app.post("/login")
async def login_user(request: Request):
    """
    Kullanıcı girişi yap
    """
    form_data = await request.form()
    email = str(form_data.get("email", "")).strip().lower()
    
    # Basit e-posta kontrolü
    if "@" in email and "." in email:
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            key="user_email",
            value=email,
            max_age=30 * 24 * 60 * 60,  # 30 gün
            httponly=True,
            samesite="lax"
        )
        return response
    
    # Geçersiz e-posta durumunda login sayfasına geri dön
    return RedirectResponse("/login")

@app.get("/debug/sources", response_class=HTMLResponse)
async def debug_sources_page(request: Request):
    """
    Fiyat kaynakları debug sayfası
    """
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Fiyat Kaynakları | ICT SMART PRO</title>
        <style>
            body {{
                background: #000;
                color: #fff;
                font-family: sans-serif;
                padding: 20px;
                margin: 0;
            }}
            
            .container {{
                max-width: 1000px;
                margin: 0 auto;
            }}
            
            .header {{
                text-align: center;
                margin-bottom: 40px;
            }}
            
            .header h1 {{
                color: #00dbde;
                font-size: 2.5rem;
                margin-bottom: 10px;
            }}
            
            .total-info {{
                text-align: center;
                font-size: 1.3rem;
                color: #00ff88;
                margin-bottom: 30px;
                padding: 15px;
                background: rgba(0, 255, 136, 0.1);
                border-radius: 10px;
            }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
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
            
            .status-healthy {{
                color: #00ff88;
                font-weight: bold;
            }}
            
            .status-error {{
                color: #ff4444;
                font-weight: bold;
            }}
            
            .healthy-row {{
                background: rgba(0, 255, 136, 0.05);
            }}
            
            .error-row {{
                background: rgba(255, 68, 68, 0.05);
            }}
            
            .back-link {{
                display: inline-block;
                margin-top: 30px;
                color: #00dbde;
                text-decoration: none;
                font-size: 1.1rem;
            }}
            
            .back-link:hover {{
                text-decoration: underline;
            }}
        </style>
    </head>
    <body>
        {get_visitor_stats_html()}
        
        <div class="container">
            <div class="header">
                <h1>🟢 FİYAT KAYNAKLARI DURUMU</h1>
                <p>Gerçek zamanlı fiyat kaynakları izleme</p>
            </div>
            
            <div class="total-info" id="total-info">
                📊 Toplam coin yükleniyor...
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>KAYNAK</th>
                        <th>DURUM</th>
                        <th>SON GÜNCELLEME</th>
                        <th>COİN SAYISI</th>
                    </tr>
                </thead>
                <tbody id="sources-table">
                    <tr>
                        <td colspan="4" style="text-align: center; padding: 40px;">
                            🔄 Veriler yükleniyor...
                        </td>
                    </tr>
                </tbody>
            </table>
            
            <a href="/" class="back-link">← Ana Sayfaya Dön</a>
        </div>
        
        <script>
            // WebSocket bağlantısı
            const ws = new WebSocket(
                (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + 
                window.location.host + '/ws/price_sources'
            );
            
            ws.onopen = function() {{
                console.log('Fiyat kaynakları WebSocket bağlantısı kuruldu');
            }};
            
            ws.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    
                    // Toplam bilgisini güncelle
                    document.getElementById('total-info').innerHTML = 
                        \`📈 Toplam <strong>\${data.total_symbols.toLocaleString()}</strong> coin aktif\`;
                    
                    // Tabloyu güncelle
                    const tableBody = document.getElementById('sources-table');
                    const sources = data.sources;
                    
                    if (!sources || Object.keys(sources).length === 0) {{
                        tableBody.innerHTML = \`
                            <tr>
                                <td colspan="4" style="text-align: center; padding: 40px; color: #ffd700;">
                                    📊 Kaynak bulunamadı
                                </td>
                            </tr>
                        \`;
                        return;
                    }}
                    
                    let tableRows = '';
                    
                    Object.entries(sources).forEach(([sourceName, sourceData]) => {{
                        const statusClass = sourceData.healthy ? 'status-healthy' : 'status-error';
                        const rowClass = sourceData.healthy ? 'healthy-row' : 'error-row';
                        const statusText = sourceData.healthy ? '✅ SAĞLIKLI' : '❌ HATA';
                        
                        tableRows += \`
                            <tr class="\${rowClass}">
                                <td><strong>\${sourceName.toUpperCase()}</strong></td>
                                <td class="\${statusClass}">\${statusText}</td>
                                <td>\${sourceData.last_update || 'Asla'}</td>
                                <td><strong>\${sourceData.symbols_count || 0}</strong></td>
                            </tr>
                        \`;
                    }});
                    
                    tableBody.innerHTML = tableRows;
                    
                }} catch (error) {{
                    console.error('Veri işleme hatası:', error);
                }}
            }};
            
            ws.onerror = function() {{
                document.getElementById('total-info').innerHTML = 
                    '❌ WebSocket bağlantı hatası';
            }};
            
            ws.onclose = function() {{
                document.getElementById('total-info').innerHTML = 
                    '🔌 Bağlantı kesildi. Sayfayı yenileyin.';
            }};
            
            // Sayfa kapatılırken WebSocket'i kapat
            window.addEventListener('beforeunload', function() {{
                if (ws.readyState === WebSocket.OPEN) {{
                    ws.close();
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)

@app.get("/health")
async def health_check_endpoint():
    """
    Sağlık kontrolü endpoint'i
    """
    stats = visitor_counter.get_stats()
    
    # Sağlıklı kaynak sayısını hesapla
    healthy_sources = 0
    if price_sources_status:
        healthy_sources = sum(1 for v in price_sources_status.values() if v.get("healthy", False))
    
    return {
        "status": "OK",
        "version": "4.0-REALTIME",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "binance_connected": get_binance_client() is not None,
            "price_sources_healthy": healthy_sources,
            "price_sources_total": len(price_sources_status),
            "symbols_loaded": len(all_usdt_symbols),
            "active_connections": {
                "price_sources": len(price_sources_subscribers),
                "single_signals": sum(len(subs) for subs in single_subscribers.values()),
                "all_signals": sum(len(subs) for subs in all_subscribers.values()),
                "pump_radar": len(pump_radar_subscribers)
            }
        },
        "performance": {
            "top_gainers_count": len(top_gainers),
            "active_signals": {tf: len(sigs) for tf, sigs in active_strong_signals.items()},
            "shared_signals": {tf: len(sigs) for tf, sigs in shared_signals.items()}
        },
        "visitor_stats": stats
    }

# ==================== APPLICATION START ====================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_level="info"
    )
