# main.py — RAILWAY İÇİN TAMAMEN DÜZELTİLDİ & OPTİMİZE EDİLDİ
import base64
import logging
import io
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Dict, List
import json

import pandas as pd
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File
from core import (
    initialize, cleanup, single_subscribers, all_subscribers,
    pump_radar_subscribers, realtime_subscribers,
    shared_signals, active_strong_signals, top_gainers, last_update, rt_ticker,
    get_binance_client, signal_queue
)
from utils import all_usdt_symbols

from openai import OpenAI
import os
import hashlib

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("main")

# OpenAI client - opsiyonel
openai_client = None
if os.getenv("OPENAI_API_KEY"):
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==================== ZİYARETÇİ SAYACI ====================
class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users = set()
        self.daily_stats = {}
        self.page_views = {}
    
    def add_visit(self, page: str, user_id: str = None) -> int:
        """Ziyaretçi ekle ve toplam sayıyı döndür"""
        self.total_visits += 1
        
        # Sayfa görüntüleme sayısını güncelle
        self.page_views[page] = self.page_views.get(page, 0) + 1
        
        # Günlük istatistik
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self.daily_stats:
            self.daily_stats[today] = {"visits": 0, "unique": set()}
        
        self.daily_stats[today]["visits"] += 1
        
        if user_id:
            self.active_users.add(user_id)
            self.daily_stats[today]["unique"].add(user_id)
        
        return self.total_visits
    
    def get_stats(self) -> Dict:
        """İstatistikleri döndür"""
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

# Global ziyaretçi sayacı
visitor_counter = VisitorCounter()

def get_visitor_stats_html() -> str:
    """Ziyaretçi istatistiklerini HTML formatında döndür"""
    stats = visitor_counter.get_stats()
    
    return f"""
    <div style="position:fixed;top:15px;right:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:clamp(0.8rem, 2vw, 1.2rem);z-index:1000;">
        <div>👁️ Toplam: <strong>{stats['total_visits']}</strong></div>
        <div>🔥 Bugün: <strong>{stats['today_visits']}</strong></div>
        <div>👥 Aktif: <strong>{stats['active_users']}</strong></div>
    </div>
    """

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize()
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="3.0 - RAILWAY OPTIMIZED")

# ==================== MIDDLEWARE FOR VISITOR COUNTING ====================
@app.middleware("http")
async def count_visitors(request: Request, call_next):
    """Her istekte ziyaretçi sayacını güncelle"""
    # Ziyaretçi ID'sini belirle (cookie veya IP)
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        # IP adresinden hash oluştur (privacy için)
        ip = request.client.host or "anonymous"
        visitor_id = hashlib.md5(ip.encode()).hexdigest()[:8]
    
    # Sayfa adını al
    page = request.url.path
    
    # Ziyaretçiyi say
    visitor_counter.add_visit(page, visitor_id)
    
    # Yanıtı al
    response = await call_next(request)
    
    # Visitor ID cookie'sini ayarla (1 gün)
    if not request.cookies.get("visitor_id"):
        response.set_cookie(
            "visitor_id", 
            visitor_id, 
            max_age=86400,  # 1 gün
            httponly=True, 
            samesite="lax"
        )
    
    return response

# ==================== WEBSOCKETS ====================
@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_signal(websocket: WebSocket, pair: str, timeframe: str):
    """Tek coin sinyal WebSocket'i"""
    await websocket.accept()
    
    # Symbol'ü standartlaştır
    symbol = pair.upper().replace("/", "").replace("-", "").replace(" ", "").strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    
    # KESİN OLARAK aynı formatı kullan
    channel = f"{symbol}:{timeframe}"
    
    # Abone ol
    if channel not in single_subscribers:
        single_subscribers[channel] = set()
    single_subscribers[channel].add(websocket)
    logger.info(f"📡 Yeni single subscriber: {channel} (Toplam: {len(single_subscribers[channel])})")
    
    # Mevcut sinyali varsa hemen gönder
    sig = shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        try:
            await websocket.send_json(sig)
        except:
            pass
    
    try:
        while True:
            # Keep connection alive
            await asyncio.sleep(15)
            try:
                await websocket.send_json({"heartbeat": True, "time": datetime.now().strftime("%H:%M:%S")})
            except:
                break
    except WebSocketDisconnect:
        pass
    finally:
        # Bağlantı kesildiğinde abonelikten çıkar
        if channel in single_subscribers:
            single_subscribers[channel].discard(websocket)
            logger.info(f"📡 Single subscriber ayrıldı: {channel} (Kalan: {len(single_subscribers[channel])})")

@app.websocket("/ws/all/{timeframe}")
async def ws_all(websocket: WebSocket, timeframe: str):
    """Tüm coinler sinyal WebSocket'i"""
    supported = ["5m", "15m", "1h", "4h"]  # Railway için optimize edildi
    if timeframe not in supported:
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    
    if timeframe not in all_subscribers:
        all_subscribers[timeframe] = set()
    all_subscribers[timeframe].add(websocket)
    logger.info(f"📡 Yeni all subscriber: {timeframe} (Toplam: {len(all_subscribers[timeframe])})")
    
    # Mevcut sinyalleri hemen gönder
    try:
        signals = active_strong_signals.get(timeframe, [])
        await websocket.send_json(signals[:10])  # Sadece ilk 10'u gönder
    except:
        pass
    
    try:
        while True:
            # Keep connection alive
            await asyncio.sleep(30)
            try:
                await websocket.send_json({"ping": True, "time": datetime.now().strftime("%H:%M:%S")})
            except:
                break
    except WebSocketDisconnect:
        pass
    finally:
        if timeframe in all_subscribers:
            all_subscribers[timeframe].discard(websocket)
            logger.info(f"📡 All subscriber ayrıldı: {timeframe} (Kalan: {len(all_subscribers[timeframe])})")

@app.websocket("/ws/pump_radar")
async def ws_pump(websocket: WebSocket):
    """Pump radar WebSocket'i"""
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    logger.info(f"📡 Yeni pump radar subscriber (Toplam: {len(pump_radar_subscribers)})")
    
    # Mevcut verileri hemen gönder
    try:
        await websocket.send_json({"top_gainers": top_gainers[:5], "last_update": last_update})
    except:
        pass
    
    try:
        while True:
            await asyncio.sleep(20)
            try:
                await websocket.send_json({"ping": True, "time": datetime.now().strftime("%H:%M:%S")})
            except:
                break
    except WebSocketDisconnect:
        pass
    finally:
        pump_radar_subscribers.discard(websocket)
        logger.info(f"📡 Pump radar subscriber ayrıldı (Kalan: {len(pump_radar_subscribers)})")

@app.websocket("/ws/realtime_price")
async def ws_realtime_price(websocket: WebSocket):
    """Realtime fiyat WebSocket'i"""
    await websocket.accept()
    realtime_subscribers.add(websocket)
    logger.info(f"📡 Yeni realtime subscriber (Toplam: {len(realtime_subscribers)})")
    
    try:
        while True:
            try:
                # Mevcut verileri gönder
                await websocket.send_json({
                    "tickers": rt_ticker.get("tickers", {}),
                    "last_update": rt_ticker.get("last_update", "")
                })
            except:
                break
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        pass
    finally:
        realtime_subscribers.discard(websocket)
        logger.info(f"📡 Realtime subscriber ayrıldı (Kalan: {len(realtime_subscribers)})")

# ==================== ANA SAYFA ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    
    # Ziyaretçi istatistikleri HTML'i
    visitor_stats_html = get_visitor_stats_html()
    
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>ICT SMART PRO</title>
    <style>
        body {{
            background: linear-gradient(135deg, #0a0022, #1a0033, #000);
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            min-height: 100vh;
            margin: 0;
            display: flex;
            flex-direction: column;
        }}
        .container {{
            max-width: 1200px;
            margin: auto;
            padding: 20px;
            flex: 1;
        }}
        h1 {{
            font-size: clamp(2rem, 5vw, 4rem);
            text-align: center;
            background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: g 8s infinite;
            margin: 20px 0;
        }}
        @keyframes g {{
            0% {{ background-position: 0%; }}
            100% {{ background-position: 200%; }}
        }}
        .update {{
            text-align: center;
            color: #00ffff;
            margin: 20px;
            font-size: clamp(1rem, 3vw, 1.5rem);
            padding: 10px;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 10px;
        }}
        table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0 8px;
            margin: 20px 0;
        }}
        th {{
            background: rgba(255, 255, 255, 0.1);
            padding: 12px 15px;
            font-size: clamp(0.9rem, 2vw, 1.2rem);
            text-align: left;
        }}
        tr {{
            background: rgba(255, 255, 255, 0.05);
            transition: transform 0.3s, box-shadow 0.3s;
        }}
        tr:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0, 255, 255, 0.2);
        }}
        td {{
            padding: 15px;
        }}
        .green {{ color: #00ff88; font-weight: bold; }}
        .red {{ color: #ff4444; font-weight: bold; }}
        .btn {{
            display: block;
            width: 90%;
            max-width: 500px;
            margin: 15px auto;
            padding: 18px 25px;
            font-size: clamp(1.2rem, 3vw, 1.8rem);
            background: linear-gradient(45deg, #fc00ff, #00dbde);
            color: #fff;
            text-align: center;
            border-radius: 50px;
            text-decoration: none;
            font-weight: bold;
            box-shadow: 0 0 40px rgba(255, 0, 255, 0.3);
            transition: all 0.3s;
            border: none;
            cursor: pointer;
        }}
        .btn:hover {{
            transform: scale(1.05);
            box-shadow: 0 0 60px rgba(255, 0, 255, 0.5);
        }}
        .user-info {{
            position: fixed;
            top: 15px;
            left: 15px;
            background: rgba(0, 0, 0, 0.7);
            padding: 10px 20px;
            border-radius: 20px;
            color: #00ff88;
            font-size: clamp(0.8rem, 2vw, 1rem);
            z-index: 1000;
            backdrop-filter: blur(5px);
        }}
        .loading {{
            text-align: center;
            padding: 50px;
            color: #888;
            font-size: 1.2rem;
        }}
    </style>
</head>
<body>
    <div class="user-info">
        👤 Hoş geldin, {user}
    </div>
    {visitor_stats_html}
    <div class="container">
        <h1>🚀 ICT SMART PRO</h1>
        <div class="update" id="update">⏳ Veriler yükleniyor...</div>
        <table>
            <thead>
                <tr>
                    <th>SIRA</th>
                    <th>COİN</th>
                    <th>FİYAT</th>
                    <th>DEĞİŞİM</th>
                </tr>
            </thead>
            <tbody id="table-body">
                <tr>
                    <td colspan="4" class="loading">📡 Pump radar verileri bekleniyor...</td>
                </tr>
            </tbody>
        </table>
        <a href="/signal" class="btn">📈 Tek Coin Sinyal + Grafik</a>
        <a href="/signal/all" class="btn">🔥 Tüm Coinleri Tara</a>
        <div style="text-align: center; margin-top: 30px; color: #888; font-size: 0.9rem;">
            <p>⚡ Railway Optimized | 🚀 Real-time Signals | 📊 ICT Strategy</p>
        </div>
    </div>
    <script>
        const ws = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/pump_radar');
        
        ws.onopen = function() {{
            console.log('📡 Pump radar bağlantısı kuruldu');
        }};
        
        ws.onmessage = function(e) {{
            try {{
                const data = JSON.parse(e.data);
                if (data.ping) return; // Ping mesajlarını yoksay
                
                // Güncelleme zamanını göster
                if (data.last_update) {{
                    document.getElementById('update').innerHTML = `🔄 Son Güncelleme: <strong>${{data.last_update}}</strong>`;
                }}
                
                const tbody = document.getElementById('table-body');
                
                if (!data.top_gainers || data.top_gainers.length === 0) {{
                    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:40px;color:#ffd700">😴 Şu anda aktif pump yok</td></tr>';
                    return;
                }}
                
                // Tabloyu güncelle
                tbody.innerHTML = data.top_gainers.map((coin, index) => `
                    <tr>
                        <td><strong>#${{index + 1}}</strong></td>
                        <td><strong>${{coin.symbol || 'N/A'}}</strong></td>
                        <td>$${{coin.price ? coin.price.toFixed(4) : '0.0000'}}</td>
                        <td class="${{coin.change > 0 ? 'green' : 'red'}}">
                            ${{coin.change > 0 ? '↗ +' : '↘ '}}${{Math.abs(coin.change).toFixed(2)}}%
                        </td>
                    </tr>
                `).join('');
            }} catch (error) {{
                console.error('Veri işleme hatası:', error);
            }}
        }};
        
        ws.onerror = function(error) {{
            console.error('WebSocket hatası:', error);
            document.getElementById('update').innerHTML = '❌ Bağlantı hatası. Sayfayı yenileyin.';
        }};
        
        ws.onclose = function() {{
            console.log('📡 Pump radar bağlantısı kapandı');
            document.getElementById('update').innerHTML = '🔌 Bağlantı kesildi. Yeniden bağlanılıyor...';
            setTimeout(() => location.reload(), 3000);
        }};
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

# ==================== TEK COİN SİNYAL SAYFASI ====================
# ==================== TEK COİN SİNYAL SAYFASI ====================
@app.get("/signal", response_class=HTMLResponse)
async def signal(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    visitor_stats_html = get_visitor_stats_html()
    
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>CANLI SİNYAL + GRAFİK | ICT SMART PRO</title>
    <style>
        :root {{
            --primary: #00dbde;
            --secondary: #fc00ff;
            --success: #00ff88;
            --danger: #ff4444;
            --warning: #ffd700;
            --dark-bg: #0a0022;
        }}
        
        body {{
            background: linear-gradient(135deg, var(--dark-bg), #1a0033, #000);
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            margin: 0;
            padding: 0;
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 25px;
        }}
        
        h1 {{
            font-size: clamp(2rem, 5vw, 3.5rem);
            text-align: center;
            background: linear-gradient(90deg, var(--primary), var(--secondary), var(--primary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: gradient 8s infinite linear;
            margin: 10px 0;
        }}
        
        @keyframes gradient {{
            0% {{ background-position: 0%; }}
            100% {{ background-position: 200%; }}
        }}
        
        .controls {{
            background: rgba(255, 255, 255, 0.08);
            border-radius: 20px;
            padding: 30px;
            text-align: center;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        
        .input-group {{
            display: flex;
            justify-content: center;
            margin-bottom: 25px;
        }}
        
        input {{
            padding: 16px 20px;
            font-size: 1.2rem;
            border: none;
            border-radius: 16px;
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
            width: 100%;
            max-width: 400px;
            box-sizing: border-box;
            text-align: center;
        }}
        
        input:focus {{
            outline: 3px solid var(--primary);
            background: rgba(255, 255, 255, 0.15);
        }}
        
             /* GÜNCELLENMİŞ: Zaman Dilimi Butonları - Çok Daha Belirgin! */
        .timeframe-title {
            color: #00ffff;
            font-size: 1.4rem;
            font-weight: bold;
            margin: 25px 0 15px 0;
            text-shadow: 0 0 10px rgba(0, 255, 255, 0.5);
        }
        
        .timeframe-buttons {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 14px;
            margin: 15px 0 30px 0;
            padding: 10px;
        }
        
        .tf-btn {
            padding: 16px 24px;
            font-size: 1.2rem;
            font-weight: bold;
            background: rgba(255, 255, 255, 0.15);
            color: #ffffff;
            border: 2px solid rgba(255, 255, 255, 0.3);
            border-radius: 18px;
            cursor: pointer;
            transition: all 0.4s ease;
            min-width: 90px;
            backdrop-filter: blur(10px);
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .tf-btn:hover {
            background: rgba(255, 255, 255, 0.25);
            border-color: #00dbde;
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0, 219, 222, 0.4);
        }
        
        .tf-btn.active {
            background: linear-gradient(45deg, #00dbde, #fc00ff, #00dbde);
            background-size: 200% 200%;
            animation: gradientShift 4s ease infinite;
            border-color: #fc00ff;
            color: white !important;
            box-shadow: 0 0 40px rgba(252, 0, 255, 0.8), 
                        0 0 60px rgba(0, 219, 222, 0.6);
            transform: translateY(-6px);
            font-weight: bolder;
            text-shadow: 0 0 15px rgba(0, 0, 0, 0.8);
        }
        
        @keyframes gradientShift {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }
        
        .tf-btn:active {
            transform: translateY(-2px);
        }
        
        @media (max-width: 768px) {
            .tf-btn {
                padding: 14px 20px;
                font-size: 1.1rem;
                min-width: 80px;
            }
            .timeframe-buttons {
                gap: 10px;
            }
        }
        
        .tf-btn {{
            padding: 14px 22px;
            font-size: 1.1rem;
            font-weight: bold;
            background: rgba(255, 255, 255, 0.08);
            color: #fff;
            border: 2px solid rgba(255, 255, 255, 0.2);
            border-radius: 16px;
            cursor: pointer;
            transition: all 0.3s ease;
            min-width: 80px;
            backdrop-filter: blur(5px);
        }}
        
        .tf-btn:hover {{
            background: rgba(255, 255, 255, 0.2);
            transform: translateY(-4px);
            box-shadow: 0 8px 30px rgba(0, 219, 222, 0.4);
        }}
        
        .tf-btn.active {{
            background: linear-gradient(45deg, var(--primary), var(--secondary));
            border-color: var(--secondary);
            color: white;
            box-shadow: 0 0 40px rgba(252, 0, 255, 0.6);
            transform: translateY(-4px);
        }}
        
        button {{
            background: linear-gradient(45deg, var(--secondary), var(--primary));
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s;
            min-width: 280px;
            margin: 10px;
        }}
        
        button:hover {{
            transform: translateY(-3px);
            box-shadow: 0 10px 30px rgba(252, 0, 255, 0.5);
        }}
        
        #analyze-btn {{
            background: linear-gradient(45deg, var(--primary), #ff00ff, var(--primary));
        }}
        
        #status {{
            color: var(--primary);
            text-align: center;
            margin: 20px 0;
            font-size: 1.2rem;
            padding: 12px;
            border-radius: 12px;
            background: rgba(0, 219, 222, 0.1);
            min-height: 50px;
        }}
        
        .price-display {{
            text-align: center;
            margin: 30px 0;
        }}
        
        #price-text {{
            font-size: clamp(3.5rem, 10vw, 5rem);
            font-weight: bold;
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin: 15px 0;
        }}
        
        #signal-card {{
            background: rgba(0, 0, 0, 0.5);
            border-radius: 20px;
            padding: 35px;
            text-align: center;
            min-height: 200px;
            border-left: 8px solid transparent;
            backdrop-filter: blur(8px);
        }}
        
        #signal-card.green {{ border-left-color: var(--success); }}
        #signal-card.red {{ border-left-color: var(--danger); }}
        #signal-card.neutral {{ border-left-color: var(--warning); }}
        
        #signal-text {{
            font-size: clamp(2.5rem, 7vw, 4rem);
            margin-bottom: 20px;
            font-weight: bold;
        }}
        
        .chart-container {{
            width: 100%;
            max-width: 1000px;
            margin: 40px auto;
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 20px 50px rgba(0, 219, 222, 0.3);
            background: rgba(10, 0, 34, 0.6);
        }}
        
        .user-info {{
            position: fixed;
            top: 15px;
            left: 15px;
            background: rgba(0, 0, 0, 0.7);
            padding: 10px 20px;
            border-radius: 20px;
            color: var(--success);
            font-size: clamp(0.8rem, 2vw, 1rem);
            z-index: 1000;
            backdrop-filter: blur(5px);
        }}
        
        @media (max-width: 768px) {{
            .tf-btn {{
                padding: 12px 18px;
                font-size: 1rem;
                min-width: 70px;
            }}
            .timeframe-buttons {{
                gap: 10px;
            }}
        }}
    </style>
</head>
<body>
    <div class="user-info">
        👤 Hoş geldin, {user}
    </div>
    {visitor_stats_html}
    <div class="container">
        <h1>📊 CANLI SİNYAL + GRAFİK</h1>
        
        <div class="controls">
            <div class="input-group">
                <input id="pair" placeholder="Coin (örn: BTCUSDT veya BTC)" value="BTCUSDT">
            </div>
            
            <div class="timeframe-title">📊 Zaman Dilimi Seçin</div>
            <div class="timeframe-buttons">
                <button class="tf-btn" data-tf="1m">1m</button>
                <button class="tf-btn" data-tf="3m">3m</button>
                <button class="tf-btn active" data-tf="5m">5m</button>
                <button class="tf-btn" data-tf="15m">15m</button>
                <button class="tf-btn" data-tf="30m">30m</button>
                <button class="tf-btn" data-tf="1h">1h</button>
                <button class="tf-btn" data-tf="4h">4h</button>
                <button class="tf-btn" data-tf="1d">1D</button>
                <button class="tf-btn" data-tf="1w">1W</button>
            </div>
            
            <button onclick="connect()">📡 CANLI SİNYAL BAĞLANTISI KUR</button>
            <button id="analyze-btn" onclick="analyzeChartWithAI()">🤖 GRAFİĞİ ANALİZ ET</button>
            
            <div id="status">🎯 Lütfen coin ve zaman dilimi seçip bağlantı kurun</div>
        </div>
        
        <div class="price-display">
            <div id="price-text">$0.00</div>
            <div style="color: #888; font-size: 1.1rem;">Gerçek zamanlı fiyat</div>
        </div>
        
        <div id="signal-card" class="neutral">
            <div id="signal-text" class="signal-neutral">⏳ Sinyal bekleniyor</div>
            <div id="signal-details">
                Canlı sinyal için yukarıdaki butona tıklayın.<br>
                Sistem otomatik olarak ICT stratejisine göre sinyal üretecektir.
            </div>
        </div>
        
        <div id="ai-box">
            <h3 style="color: var(--primary); text-align: center; margin-bottom: 15px;">
                🤖 GPT-4o Teknik Analizi
            </h3>
            <p id="ai-comment" style="line-height: 1.6; color: #ccc;">
                Analiz sonuçları burada görüntülenecek...
            </p>
        </div>
        
        <div class="chart-container">
            <div id="tradingview_widget"></div>
        </div>
        
        <div class="navigation">
            <a href="/" class="nav-link">🏠 Ana Sayfa</a>
            <a href="/signal/all" class="nav-link">🔥 Tüm Coinler</a>
            <a href="/admin/visitor-dashboard" class="nav-link">📊 İstatistikler</a>
        </div>
    </div>
    
    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>
        // Global variables
        let ws = null;
        let priceWs = null;
        let tvWidget = null;
        let currentPrice = null;
        let isConnected = false;
        
        const tfMap = {{
            "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
            "1h": "60", "4h": "240", "1d": "D", "1w": "W"
        }};
        
        function getSymbol() {{
            let pair = document.getElementById('pair').value.trim().toUpperCase();
            if (!pair.endsWith("USDT")) {{
                pair += "USDT";
                document.getElementById('pair').value = pair;
            }}
            return "BINANCE:" + pair;
        }}
        
        function createWidget(symbol = null, interval = null) {{
            const tvSymbol = symbol || getSymbol();
            const tf = document.getElementById('tf') ? document.getElementById('tf').value : "5m";
            const tvInterval = interval || tfMap[tf] || "5";
            
            if (tvWidget) {{
                try {{ tvWidget.remove(); }} catch (e) {{}}
                tvWidget = null;
            }}
            
            tvWidget = new TradingView.widget({{
                autosize: true,
                width: "100%",
                height: 500,
                symbol: tvSymbol,
                interval: tvInterval,
                timezone: "Etc/UTC",
                theme: "dark",
                style: "1",
                locale: "tr",
                toolbar_bg: "#0a0022",
                enable_publishing: false,
                hide_side_toolbar: false,
                allow_symbol_change: true,
                container_id: "tradingview_widget",
                studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies", "Volume@tv-basicstudies"]
            }});
        }}
        
        function updatePriceDisplay(price) {{
            if (!price || isNaN(price)) return;
            let formattedPrice = price >= 1000 ? '$' + price.toFixed(2) :
                                 price >= 1 ? '$' + price.toFixed(4) :
                                 price >= 0.01 ? '$' + price.toFixed(6) : '$' + price.toFixed(8);
            
            const el = document.getElementById('price-text');
            el.textContent = formattedPrice;
            el.style.transform = 'scale(1.05)';
            setTimeout(() => el.style.transform = 'scale(1)', 200);
        }}
        
        // Realtime fiyat WebSocket
        function connectRealtimePrice() {{
            if (priceWs && priceWs.readyState === WebSocket.OPEN) return;
            const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
            priceWs = new WebSocket(`${{protocol}}://${{location.host}}/ws/realtime_price`);
            
            priceWs.onmessage = (e) => {{
                try {{
                    const data = JSON.parse(e.data);
                    const tickers = data.tickers || {{}};
                    let pair = document.getElementById('pair').value.trim().toUpperCase();
                    if (!pair.endsWith("USDT")) pair += "USDT";
                    if (tickers[pair]?.price > 0) {{
                        currentPrice = tickers[pair].price;
                        updatePriceDisplay(currentPrice);
                    }}
                }} catch (err) {{}}
            }};
            
            priceWs.onclose = () => setTimeout(connectRealtimePrice, 3000);
        }}
        
        // Zaman dilimi butonları
        document.querySelectorAll('.tf-btn').forEach(btn => {{
            btn.addEventListener('click', function() {{
                document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                
                // Gizli select yoksa oluştur (eski kodlar için)
                let hiddenTf = document.getElementById('tf');
                if (!hiddenTf) {{
                    hiddenTf = document.createElement('input');
                    hiddenTf.type = 'hidden';
                    hiddenTf.id = 'tf';
                    document.body.appendChild(hiddenTf);
                }}
                hiddenTf.value = this.dataset.tf;
                
                createWidget();
                if (isConnected) {{ disconnectWebSocket(); connect(); }}
            }});
        }});
        
        function connect() {{
            if (isConnected) {{ alert('Zaten bağlısınız!'); return; }}
            
            let symbol = document.getElementById('pair').value.trim().toUpperCase();
            const tf = document.querySelector('.tf-btn.active').dataset.tf || "5m";
            
            if (!symbol.endsWith("USDT")) {{
                symbol += "USDT";
                document.getElementById('pair').value = symbol;
            }}
            
            document.getElementById('status').innerHTML = `🔗 <strong>${{symbol}}</strong> - ${{tf.toUpperCase()}} bağlantısı kuruluyor...`;
            document.getElementById('status').style.color = '#00ffff';
            
            createWidget("BINANCE:" + symbol, tfMap[tf]);
            disconnectWebSocket();
            
            const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
            ws = new WebSocket(`${{protocol}}://${{location.host}}/ws/signal/${{symbol}}/${{tf}}`);
            
            ws.onopen = () => {{
                isConnected = true;
                document.getElementById('status').innerHTML = `✅ <strong>${{symbol}} ${{tf.toUpperCase()}}</strong> canlı sinyal akışı başladı!`;
                document.getElementById('status').style.color = '#00ff88';
            }};
            
            ws.onmessage = (e) => {{
                try {{
                    const data = JSON.parse(e.data);
                    if (data.heartbeat) return;
                    updateSignalDisplay(data, symbol);
                }} catch (err) {{}}
            }};
            
            ws.onclose = () => {{
                if (isConnected) {{
                    document.getElementById('status').innerHTML = '🔌 Bağlantı kesildi. Yeniden bağlanmak için tıklayın.';
                    document.getElementById('status').style.color = '#ffd700';
                }}
                isConnected = false;
            }};
        }}
        
        function disconnectWebSocket() {{
            if (ws) {{ ws.close(); ws = null; }}
            isConnected = false;
        }}
        
        function updateSignalDisplay(data, symbol) {{
            const card = document.getElementById('signal-card');
            const text = document.getElementById('signal-text');
            const details = document.getElementById('signal-details');
            
            const signal = data.signal || "NÖTR";
            const score = data.score || 50;
            const price = data.current_price || currentPrice || 0;
            const killzone = data.killzone || "Normal";
            const triggers = data.triggers || "Analiz ediliyor";
            const time = data.last_update || new Date().toLocaleTimeString();
            
            text.textContent = signal;
            details.innerHTML = `
                <strong>${{symbol.replace('USDT', '/USDT')}}</strong><br>
                ⚡ Skor: <strong>${{score}}/100</strong> | 🎯 Killzone: <strong>${{killzone}}</strong><br>
                💰 Fiyat: <strong>$${{price.toFixed(4)}}</strong><br>
                🕒 Son: <strong>${{time}}</strong><br>
                <small style="color:#888">${{triggers}}</small>
            `;
            
            card.className = signal.includes('ALIM') || signal.includes('BUY') ? 'green' :
                            signal.includes('SATIM') || signal.includes('SELL') ? 'red' : 'neutral';
            text.className = card.className === 'green' ? 'signal-green' :
                            card.className === 'red' ? 'signal-red' : 'signal-neutral';
            
            if (price > 0 && price !== currentPrice) {{
                currentPrice = price;
                updatePriceDisplay(price);
            }}
            
            card.style.transform = 'scale(1.02)';
            setTimeout(() => card.style.transform = 'scale(1)', 300);
        }}
        
        async function analyzeChartWithAI() {{
            const btn = document.getElementById('analyze-btn');
            const box = document.getElementById('ai-box');
            const comment = document.getElementById('ai-comment');
            
            btn.disabled = true;
            btn.innerHTML = "⏳ Analiz ediliyor...";
            box.style.display = 'block';
            comment.innerHTML = "Grafik analiz ediliyor...";
            
            try {{
                const symbol = getSymbol().replace("BINANCE:", "");
                const tf = document.querySelector('.tf-btn.active').dataset.tf || "5m";
                
                const res = await fetch('/api/analyze-chart', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ symbol, timeframe: tf }})
                }});
                const data = await res.json();
                
                comment.innerHTML = data.success && data.analysis ?
                    data.analysis.replace(/\\n/g, '<br>').replace(/🔍/g, '<br>🔍 ').replace(/📊/g, '<br>📊 ') :
                    "❌ Analiz alınamadı.";
            }} catch (e) {{
                comment.innerHTML = "❌ Bağlantı hatası.";
            }} finally {{
                btn.disabled = false;
                btn.innerHTML = "🤖 GRAFİĞİ ANALİZ ET";
            }}
        }}
        
        document.addEventListener("DOMContentLoaded", () => {{
            createWidget();
            connectRealtimePrice();
            
            document.getElementById('pair').addEventListener('change', () => {{
                createWidget();
                if (isConnected) {{ disconnectWebSocket(); connect(); }}
            }});
        }});
        
        window.addEventListener('beforeunload', () => {{
            disconnectWebSocket();
            if (priceWs) priceWs.close();
        }});
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

# ==================== API ENDPOINTS ====================
@app.post("/api/analyze-chart")
async def analyze_chart(request: Request):
    """Chart analysis endpoint"""
    try:
        body = await request.json()
        symbol = body.get("symbol", "BTCUSDT").upper()
        timeframe = body.get("timeframe", "5m")
        
        logger.info(f"Chart analizi isteği: {symbol} {timeframe}")
        
        # Binance client'ını al
        binance_client = get_binance_client()
        
        if not binance_client:
            return JSONResponse({
                "analysis": "❌ Binance bağlantısı kurulamadı. Lütfen daha sonra tekrar deneyin.",
                "success": False
            })
        
        # Binance'ten veri çek
        try:
            interval_map = {
                "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
                "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
            }
            
            interval = interval_map.get(timeframe, "5m")
            ccxt_symbol = symbol.replace('USDT', '/USDT')
            
            logger.info(f"{ccxt_symbol} için {interval} verisi çekiliyor...")
            klines = await binance_client.fetch_ohlcv(
                ccxt_symbol, 
                timeframe=interval, 
                limit=150
            )
            
            if not klines or len(klines) < 50:
                return JSONResponse({
                    "analysis": f"❌ {symbol} için yeterli veri bulunamadı.",
                    "success": False
                })
            
        except Exception as e:
            logger.error(f"Binance veri hatası: {e}")
            return JSONResponse({
                "analysis": f"❌ Veri alınamadı: {str(e)[:100]}",
                "success": False
            })
        
        # DataFrame oluştur
        df = pd.DataFrame(klines)
        
        if len(df.columns) >= 6:
            df = df.iloc[:, :6]
            df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        elif len(df.columns) >= 5:
            df = df.iloc[:, :5]
            df.columns = ['timestamp', 'open', 'high', 'low', 'close']
            df['volume'] = 1000
        
        # Sinyal üret
        signal = None
        try:
            from indicators import generate_ict_signal, generate_simple_signal
            
            # Try main signal function
            signal = generate_ict_signal(df, symbol, timeframe)
            
            # Fallback to simple signal
            if not signal:
                logger.info(f"{symbol}: Ana sinyal üretilemedi, basit sinyal deneniyor...")
                signal = generate_simple_signal(df, symbol, timeframe)
            
        except Exception as e:
            logger.error(f"Sinyal üretim hatası: {e}")
            # Fallback sinyal
            last_price = df['close'].iloc[-1] if len(df) > 0 else 0
            signal = {
                "pair": symbol.replace("USDT", "/USDT"),
                "timeframe": timeframe.upper(),
                "current_price": round(last_price, 4),
                "signal": "⏸️ ANALİZ BEKLENİYOR",
                "score": 50,
                "last_update": datetime.utcnow().strftime("%H:%M:%S UTC"),
                "killzone": "Normal",
                "triggers": "Veri analiz ediliyor",
                "strength": "ORTA"
            }
        
        # Analiz metnini oluştur
        if not signal:
            analysis = f"""🔍 {symbol} {timeframe} Grafik Analizi
📊 Durum: <strong>Sinyal tespit edilemedi</strong>
🤔 Sebep: Piyasa nötr veya sinyal kriterleri sağlanmıyor.

💡 Tavsiye:
• Farklı zaman dilimi deneyin (15m, 1h)
• Başka bir coin analiz edin
• Piyasa volatilitesini bekleyin

⚠️ Bu bir yatırım tavsiyesi değildir."""
        else:
            analysis = f"""🔍 {symbol} {timeframe} Grafik Analizi

🎯 SİNYAL: <strong>{signal['signal']}</strong>

📊 Skor: <strong>{signal['score']}/100</strong> ({signal['strength']})
💰 Fiyat: <strong>${signal['current_price']}</strong>
🕐 Killzone: <strong>{signal['killzone']}</strong>
🕒 Güncelleme: {signal['last_update']}

📈 Teknik Analiz:
{symbol} {timeframe} grafiğinde ICT stratejisine göre analiz yapıldı.

💡 Öneri:
{symbol} için {signal['signal']} sinyali mevcut.
Ancak kendi araştırmanızı yapın ve risk yönetimi uygulayın.

⚠️ Uyarı: Bu bir yatırım tavsiyesi değildir.
Yalnızca teknik analiz yorumudur."""
        
        return JSONResponse({
            "analysis": analysis,
            "signal_data": signal or {},
            "success": True
        })
        
    except Exception as e:
        logger.error(f"Analiz hatası: {e}", exc_info=True)
        return JSONResponse({
            "analysis": f"""❌ Analiz hatası:

Hata: {str(e)[:100]}

Lütfen:
• Coin adını kontrol edin
• Sayfayı yenileyin
• Daha sonra tekrar deneyin""",
            "success": False
        }, status_code=500)

# ==================== TÜM COİNLER SAYFASI ====================
@app.get("/signal", response_class=HTMLResponse)
async def signal(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    visitor_stats_html = get_visitor_stats_html()
    
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>CANLI SİNYAL + GRAFİK | ICT SMART PRO</title>
    <style>
        :root {{
            --primary: #00dbde;
            --secondary: #fc00ff;
            --success: #00ff88;
            --danger: #ff4444;
            --warning: #ffd700;
            --dark-bg: #0a0022;
        }}
        
        body {{
            background: linear-gradient(135deg, var(--dark-bg), #1a0033, #000);
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            margin: 0;
            padding: 0;
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 25px;
        }}
        
        h1 {{
            font-size: clamp(2rem, 5vw, 3.5rem);
            text-align: center;
            background: linear-gradient(90deg, var(--primary), var(--secondary), var(--primary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: gradient 8s infinite linear;
            margin: 10px 0;
        }}
        
        @keyframes gradient {{
            0% {{ background-position: 0%; }}
            100% {{ background-position: 200%; }}
        }}
        
        .controls {{
            background: rgba(255, 255, 255, 0.08);
            border-radius: 20px;
            padding: 25px;
            text-align: center;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        
        .input-group {{
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            justify-content: center;
            margin-bottom: 20px;
        }}
        
        input, select, button {{
            padding: 16px 20px;
            font-size: 1.1rem;
            border: none;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
            min-width: 200px;
            box-sizing: border-box;
        }}
        
        input:focus, select:focus {{
            outline: 2px solid var(--primary);
            background: rgba(255, 255, 255, 0.15);
        }}
        
        button {{
            background: linear-gradient(45deg, var(--secondary), var(--primary));
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s;
            min-width: 250px;
        }}
        
        button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(252, 0, 255, 0.4);
        }}
        
        #analyze-btn {{
            background: linear-gradient(45deg, var(--primary), #ff00ff, var(--primary));
            margin-top: 15px;
        }}
        
        #status {{
            color: var(--primary);
            text-align: center;
            margin: 15px;
            font-size: 1.1rem;
            padding: 10px;
            border-radius: 10px;
            background: rgba(0, 219, 222, 0.1);
        }}
        
        .price-display {{
            text-align: center;
            margin: 20px 0;
        }}
        
        #price-text {{
            font-size: clamp(3rem, 8vw, 4.5rem);
            font-weight: bold;
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin: 10px 0;
        }}
        
        #signal-card {{
            background: rgba(0, 0, 0, 0.5);
            border-radius: 20px;
            padding: 30px;
            text-align: center;
            min-height: 180px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            transition: all 0.3s;
            border-left: 6px solid transparent;
            backdrop-filter: blur(5px);
        }}
        
        #signal-card.green {{ border-left-color: var(--success); }}
        #signal-card.red {{ border-left-color: var(--danger); }}
        #signal-card.neutral {{ border-left-color: var(--warning); }}
        
        #signal-text {{
            font-size: clamp(2rem, 5vw, 3rem);
            margin-bottom: 15px;
            font-weight: bold;
        }}
        
        #signal-details {{
            font-size: 1.1rem;
            line-height: 1.6;
            color: #ccc;
        }}
        
        .signal-green {{ color: var(--success); }}
        .signal-red {{ color: var(--danger); }}
        .signal-neutral {{ color: var(--warning); }}
        
        #ai-box {{
            background: rgba(13, 0, 51, 0.9);
            border-radius: 20px;
            padding: 25px;
            border: 2px solid var(--primary);
            display: none;
            margin-top: 20px;
        }}
        
        .chart-container {{
            width: 100%;
            max-width: 1000px;
            margin: 30px auto;
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 15px 40px rgba(0, 219, 222, 0.2);
            background: rgba(10, 0, 34, 0.5);
        }}
        
        #tradingview_widget {{
            height: 500px;
            width: 100%;
            border-radius: 20px;
        }}
        
        .navigation {{
            text-align: center;
            margin-top: 30px;
            display: flex;
            justify-content: center;
            gap: 30px;
            flex-wrap: wrap;
        }}
        
        .nav-link {{
            color: var(--primary);
            text-decoration: none;
            font-size: 1.2rem;
            padding: 10px 20px;
            border-radius: 10px;
            transition: all 0.3s;
        }}
        
        .nav-link:hover {{
            background: rgba(0, 219, 222, 0.1);
            transform: translateY(-2px);
        }}
        
        .user-info {{
            position: fixed;
            top: 15px;
            left: 15px;
            background: rgba(0, 0, 0, 0.7);
            padding: 10px 20px;
            border-radius: 20px;
            color: var(--success);
            font-size: clamp(0.8rem, 2vw, 1rem);
            z-index: 1000;
            backdrop-filter: blur(5px);
        }}
        
        @media (max-width: 768px) {{
            .input-group {{
                flex-direction: column;
                align-items: center;
            }}
            
            input, select, button {{
                width: 100%;
                max-width: 400px;
            }}
            
            .chart-container {{
                margin: 15px auto;
            }}
            
            #tradingview_widget {{
                height: 400px;
            }}
        }}
    </style>
</head>
<body>
    <div class="user-info">
        👤 Hoş geldin, {user}
    </div>
    {visitor_stats_html}
    <div class="container">
        <h1>📊 CANLI SİNYAL + GRAFİK</h1>
        
        <div class="controls">
            <div class="input-group">
                <input id="pair" placeholder="Coin (örn: BTCUSDT veya BTC)" value="BTCUSDT">
                <select id="tf">
                    <option value="5m" selected>5 Dakika</option>
                    <option value="15m">15 Dakika</option>
                    <option value="1h">1 Saat</option>
                    <option value="4h">4 Saat</option>
                    <option value="1d">1 Gün</option>
                </select>
            </div>
            
            <button onclick="connect()">📡 CANLI SİNYAL BAĞLANTISI KUR</button>
            <button id="analyze-btn" onclick="analyzeChartWithAI()">🤖 GRAFİĞİ ANALİZ ET</button>
            
            <div id="status">🎯 Lütfen coin ve zaman dilimi seçin</div>
        </div>
        
        <div class="price-display">
            <div id="price-text">$0.00</div>
            <div style="color: #888; font-size: 1rem;">Gerçek zamanlı fiyat</div>
        </div>
        
        <div id="signal-card" class="neutral">
            <div id="signal-text" class="signal-neutral">⏳ Sinyal bekleniyor</div>
            <div id="signal-details">
                Canlı sinyal için yukarıdaki butona tıklayın.<br>
                Sistem otomatik olarak ICT stratejisine göre sinyal üretecektir.
            </div>
        </div>
        
        <div id="ai-box">
            <h3 style="color: var(--primary); text-align: center; margin-bottom: 15px;">
                🤖 GPT-4o Teknik Analizi
            </h3>
            <p id="ai-comment" style="line-height: 1.6; color: #ccc;">
                Analiz sonuçları burada görüntülenecek...
            </p>
        </div>
        
        <div class="chart-container">
            <div id="tradingview_widget"></div>
        </div>
        
        <div class="navigation">
            <a href="/" class="nav-link">🏠 Ana Sayfa</a>
            <a href="/signal/all" class="nav-link">🔥 Tüm Coinler</a>
            <a href="/admin/visitor-dashboard" class="nav-link">📊 İstatistikler</a>
        </div>
    </div>
    
    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>
        // Global variables
        let ws = null;                    // Sinyal WebSocket
        let priceWs = null;               // YENİ: Realtime fiyat WebSocket
        let tvWidget = null;
        let currentPrice = null;
        let isConnected = false;
        
        // Timeframe mapping
        const tfMap = {{
            "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
            "1h": "60", "4h": "240", "1d": "D", "1w": "W"
        }};
        
        // Get formatted symbol
        function getSymbol() {{
            let pair = document.getElementById('pair').value.trim().toUpperCase();
            if (!pair.endsWith("USDT")) {{
                pair += "USDT";
                document.getElementById('pair').value = pair;
            }}
            return "BINANCE:" + pair;
        }}
        
        // Create TradingView widget
        function createWidget(symbol = null, interval = null) {{
            const tvSymbol = symbol || getSymbol();
            const tf = document.getElementById('tf').value;
            const tvInterval = interval || tfMap[tf] || "5";
            
            if (tvWidget) {{
                try {{ tvWidget.remove(); }} catch (e) {{}}
                tvWidget = null;
            }}
            
            tvWidget = new TradingView.widget({{
                autosize: true,
                width: "100%",
                height: 500,
                symbol: tvSymbol,
                interval: tvInterval,
                timezone: "Etc/UTC",
                theme: "dark",
                style: "1",
                locale: "tr",
                toolbar_bg: "#0a0022",
                enable_publishing: false,
                hide_side_toolbar: false,
                allow_symbol_change: true,
                container_id: "tradingview_widget",
                studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies", "Volume@tv-basicstudies"]
            }});
            
            tvWidget.onChartReady(() => {{
                console.log('✅ Grafik yüklendi:', tvSymbol);
            }});
        }}
        
        // Update price display
        function updatePriceDisplay(price) {{
            if (!price || isNaN(price)) return;
            
            let formattedPrice;
            if (price >= 1000) {{
                formattedPrice = '$' + price.toFixed(2);
            }} else if (price >= 1) {{
                formattedPrice = '$' + price.toFixed(4);
            }} else if (price >= 0.01) {{
                formattedPrice = '$' + price.toFixed(6);
            }} else {{
                formattedPrice = '$' + price.toFixed(8);
            }}
            
            const priceElement = document.getElementById('price-text');
            priceElement.textContent = formattedPrice;
            
            priceElement.style.transform = 'scale(1.05)';
            setTimeout(() => {{ priceElement.style.transform = 'scale(1)'; }}, 200);
        }}
        
        // ==================== REALTIME FİYAT WEBSOCKET ====================
        function connectRealtimePrice() {{
            if (priceWs && priceWs.readyState === WebSocket.OPEN) return;
            
            const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
            priceWs = new WebSocket(`${{protocol}}://${{location.host}}/ws/realtime_price`);
            
            priceWs.onopen = () => console.log('✅ Realtime fiyat bağlantısı kuruldu');
            
            priceWs.onmessage = (event) => {{
                try {{
                    const data = JSON.parse(event.data);
                    const tickers = data.tickers || {{}};
                    
                    let pair = document.getElementById('pair').value.trim().toUpperCase();
                    if (!pair.endsWith("USDT")) pair += "USDT";
                    
                    if (tickers[pair] && tickers[pair].price > 0) {{
                        currentPrice = tickers[pair].price;
                        updatePriceDisplay(currentPrice);
                    }}
                }} catch (e) {{
                    console.error('Realtime fiyat hatası:', e);
                }}
            }};
            
            priceWs.onclose = () => {{
                console.log('🔌 Realtime fiyat bağlantısı kapandı, 3sn sonra yeniden bağlanılıyor...');
                setTimeout(connectRealtimePrice, 3000);
            }};
            
            priceWs.onerror = (err) => console.error('Realtime fiyat WebSocket hatası:', err);
        }}
        
        // ==================== SİNYAL WEBSOCKET ====================
        function connect() {{
            if (isConnected) {{
                alert('⚠️ Zaten bağlısınız!');
                return;
            }}
            
            let symbol = document.getElementById('pair').value.trim().toUpperCase();
            const tfSelect = document.getElementById('tf').value;
            
            if (!symbol.endsWith("USDT")) {{
                symbol += "USDT";
                document.getElementById('pair').value = symbol;
            }}
            
            document.getElementById('status').innerHTML = 
                `🔗 <strong>${{symbol}}</strong> için ${{tfSelect.toUpperCase()}} bağlantısı kuruluyor...`;
            document.getElementById('status').style.color = '#00ffff';
            
            createWidget("BINANCE:" + symbol, tfMap[tfSelect]);
            disconnectWebSocket();
            
            const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
            ws = new WebSocket(`${{protocol}}://${{location.host}}/ws/signal/${{symbol}}/${{tfSelect}}`);
            
            ws.onopen = () => {{
                isConnected = true;
                document.getElementById('status').innerHTML = 
                    `✅ <strong>${{symbol}} ${{tfSelect.toUpperCase()}}</strong> canlı sinyal akışı başladı!`;
                document.getElementById('status').style.color = '#00ff88';
            }};
            
            ws.onmessage = (event) => {{
                try {{
                    const data = JSON.parse(event.data);
                    if (data.heartbeat) return;
                    updateSignalDisplay(data, symbol);
                }} catch (e) {{
                    console.error('Sinyal WebSocket hatası:', e);
                }}
            }};
            
            ws.onclose = () => {{
                if (isConnected) {{
                    document.getElementById('status').innerHTML = '🔌 Bağlantı kesildi. Yeniden bağlanmak için tıklayın.';
                    document.getElementById('status').style.color = '#ffd700';
                }}
                isConnected = false;
            }};
        }}
        
        function disconnectWebSocket() {{
            if (ws) {{ ws.close(); ws = null; }}
            isConnected = false;
        }}
        
        function updateSignalDisplay(signalData, symbol) {{
            const signalCard = document.getElementById('signal-card');
            const signalText = document.getElementById('signal-text');
            const signalDetails = document.getElementById('signal-details');
            
            const signal = signalData.signal || "NÖTR";
            const score = signalData.score || 50;
            const price = signalData.current_price || currentPrice || 0;
            const killzone = signalData.killzone || "Normal";
            const triggers = signalData.triggers || "Sinyal analiz ediliyor";
            const lastUpdate = signalData.last_update || new Date().toLocaleTimeString();
            
            signalText.textContent = signal;
            
            signalDetails.innerHTML = `
                <strong>${{symbol.replace('USDT', '/USDT')}}</strong><br>
                ⚡ Skor: <strong>${{score}}/100</strong> | 🎯 Killzone: <strong>${{killzone}}</strong><br>
                💰 Fiyat: <strong>$${{price.toFixed(4)}}</strong><br>
                🕒 Son Güncelleme: <strong>${{lastUpdate}}</strong><br>
                <small style="color: #888;">${{triggers}}</small>
            `;
            
            if (signal.includes('ALIM') || signal.includes('BUY')) {{
                signalCard.className = 'green'; signalText.className = 'signal-green';
            }} else if (signal.includes('SATIM') || signal.includes('SELL')) {{
                signalCard.className = 'red'; signalText.className = 'signal-red';
            }} else {{
                signalCard.className = 'neutral'; signalText.className = 'signal-neutral';
            }}
            
            if (price && price !== currentPrice) {{
                currentPrice = price;
                updatePriceDisplay(price);
            }}
            
            signalCard.style.transform = 'scale(1.02)';
            setTimeout(() => {{ signalCard.style.transform = 'scale(1)'; }}, 300);
        }}
        
        async function analyzeChartWithAI() {{
            const btn = document.getElementById('analyze-btn');
            const box = document.getElementById('ai-box');
            const comment = document.getElementById('ai-comment');
            
            btn.disabled = true;
            btn.innerHTML = "⏳ Analiz ediliyor...";
            box.style.display = 'block';
            comment.innerHTML = "📊 Grafik analiz ediliyor...<br>🤖 AI yanıt bekleniyor...";
            
            try {{
                const symbol = getSymbol().replace("BINANCE:", "");
                const timeframe = document.getElementById('tf').value;
                
                const response = await fetch('/api/analyze-chart', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ symbol, timeframe }})
                }});
                
                const data = await response.json();
                
                if (data.success && data.analysis) {{
                    comment.innerHTML = data.analysis
                        .replace(/\\n/g, '<br>')
                        .replace(/🔍/g, '🔍 ').replace(/📊/g, '<br>📊 ')
                        .replace(/🤔/g, '<br>🤔 ').replace(/💡/g, '<br>💡 ')
                        .replace(/⚠️/g, '<br>⚠️ ');
                }} else {{
                    comment.innerHTML = "❌ Analiz alınamadı.<br>" + (data.detail || 'Tekrar deneyin.');
                }}
            }} catch (error) {{
                comment.innerHTML = "❌ Bağlantı hatası.<br>Lütfen internetinizi kontrol edin.";
            }} finally {{
                btn.disabled = false;
                btn.innerHTML = "🤖 GRAFİĞİ ANALİZ ET";
            }}
        }}
        
        // Sayfa yüklendiğinde başlat
        document.addEventListener("DOMContentLoaded", () => {{
            createWidget();
            connectRealtimePrice();  // ← EN ÖNEMLİ SATIR: Realtime fiyat başlıyor!
            
            document.getElementById('pair').addEventListener('change', () => {{
                createWidget();
                if (isConnected) {{ disconnectWebSocket(); connect(); }}
            }});
            
            document.getElementById('tf').addEventListener('change', () => {{
                createWidget();
                if (isConnected) {{ disconnectWebSocket(); connect(); }}
            }});
        }});
        
        // Sayfa kapanırken temizle
        window.addEventListener('beforeunload', () => {{
            disconnectWebSocket();
            if (priceWs) priceWs.close();
        }});
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

# ==================== ZİYARETÇİ İSTATİSTİKLERİ API ====================
@app.get("/api/visitor-stats")
async def get_visitor_stats():
    """Ziyaretçi istatistiklerini JSON olarak döndür"""
    stats = visitor_counter.get_stats()
    return JSONResponse(stats)

@app.get("/admin/visitor-dashboard")
async def visitor_dashboard(request: Request):
    """Yönetici için ziyaretçi dashboard'u"""
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    stats = visitor_counter.get_stats()
    
    # Sayfa görüntüleme tablosu
    page_views_html = ""
    for page, views in stats['page_views'].items():
        page_views_html += f"<tr><td>{page}</td><td>{views}</td></tr>"
    
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ziyaretçi İstatistikleri | ICT SMART PRO</title>
    <style>
        body {{
            background: linear-gradient(135deg, #0a0022, #1a0033, #000);
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: auto;
        }}
        h1 {{
            color: #00dbde;
            text-align: center;
            margin-bottom: 30px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        .stat-card {{
            background: rgba(255, 255, 255, 0.1);
            padding: 25px;
            border-radius: 15px;
            text-align: center;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: transform 0.3s;
        }}
        .stat-card:hover {{
            transform: translateY(-5px);
        }}
        .stat-card h3 {{
            color: #00ffff;
            margin-top: 0;
            font-size: 1.2rem;
        }}
        .stat-card .number {{
            font-size: 2.8rem;
            font-weight: bold;
            color: #00ff88;
            margin: 10px 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 30px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            overflow: hidden;
        }}
        th, td {{
            padding: 15px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}
        th {{
            background: rgba(255, 255, 255, 0.1);
            color: #00dbde;
            font-weight: bold;
        }}
        .back-btn {{
            display: inline-block;
            margin: 20px 0;
            padding: 12px 25px;
            background: linear-gradient(45deg, #00dbde, #fc00ff);
            color: #fff;
            text-decoration: none;
            border-radius: 8px;
            font-weight: bold;
            transition: all 0.3s;
        }}
        .back-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0, 219, 222, 0.3);
        }}
        .update-time {{
            color: #888;
            margin-top: 20px;
            text-align: center;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Ziyaretçi İstatistikleri</h1>
        
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Toplam Ziyaret</h3>
                <div class="number">{stats['total_visits']}</div>
                <div style="color: #ccc; font-size: 0.9rem;">Tüm zamanlar</div>
            </div>
            <div class="stat-card">
                <h3>Aktif Kullanıcılar</h3>
                <div class="number">{stats['active_users']}</div>
                <div style="color: #ccc; font-size: 0.9rem;">Şu an çevrimiçi</div>
            </div>
            <div class="stat-card">
                <h3>Bugünkü Ziyaretler</h3>
                <div class="number">{stats['today_visits']}</div>
                <div style="color: #ccc; font-size: 0.9rem;">24 saatte</div>
            </div>
            <div class="stat-card">
                <h3>Bugünkü Benzersiz</h3>
                <div class="number">{stats['today_unique']}</div>
                <div style="color: #ccc; font-size: 0.9rem;">Farklı kullanıcı</div>
            </div>
        </div>
        
        <h2 style="color: #00dbde; margin-top: 40px;">Sayfa Görüntülemeleri</h2>
        <table>
            <thead>
                <tr>
                    <th>Sayfa</th>
                    <th>Görüntülenme</th>
                </tr>
            </thead>
            <tbody>
                {page_views_html if page_views_html else '<tr><td colspan="2" style="text-align:center;color:#888">Henüz veri yok</td></tr>'}
            </tbody>
        </table>
        
        <div class="update-time">
            Son Güncelleme: {stats['last_updated']}
        </div>
        
        <div style="text-align: center;">
            <a href="/" class="back-btn">🏠 Ana Sayfaya Dön</a>
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)

# ==================== GPT-4o ANALİZ ENDPOINT ====================
@app.post("/api/gpt-analyze")
async def gpt_analyze_endpoint(image_file: UploadFile = File(...)):
    """Bu endpoint sadece OPENAI_API_KEY varsa çalışır"""
    if not openai_client:
        return JSONResponse({
            "error": "OpenAI API anahtarı tanımlı değil",
            "tip": "OPENAI_API_KEY environment variable'ını ayarlayın"
        }, status_code=501)
    
    try:
        # Resmi oku
        image_data = await image_file.read()
        
        # Base64'e çevir
        image_b64 = base64.b64encode(image_data).decode('utf-8')
        
        # GPT-4o'ya gönder
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Bu grafik bir kripto para birimine ait. Lütfen teknik analiz yap ve şu konuları değerlendir:\n1. Genel trend\n2. Önemli destek/direnç seviyeleri\n3. Mum formasyonları\n4. RSI ve MACD durumu\n5. Potansiyel alım/satım seviyeleri\n\nYanıtını Türkçe olarak ver, net ve anlaşılır ol."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_b64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1000
        )
        
        analysis = response.choices[0].message.content
        
        return JSONResponse({
            "analysis": analysis,
            "success": True
        })
        
    except Exception as e:
        logger.error(f"GPT analiz hatası: {e}")
        return JSONResponse({
            "error": "GPT analiz başarısız",
            "detail": str(e)
        }, status_code=500)

# ==================== SAĞLIK KONTROLÜ ====================
@app.get("/health")
async def health():
    stats = visitor_counter.get_stats()
    
    # Get some system info
    from core import all_usdt_symbols, rt_ticker, active_strong_signals
    
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "system": {
            "symbols_loaded": len(all_usdt_symbols) if all_usdt_symbols else 0,
            "realtime_tickers": len(rt_ticker.get("tickers", {})),
            "strong_signals_5m": len(active_strong_signals.get("5m", [])),
            "openai_available": openai_client is not None,
        },
        "visitors": {
            "total_visits": stats["total_visits"],
            "active_users": stats["active_users"],
            "today_visits": stats["today_visits"],
            "last_updated": stats["last_updated"]
        },
        "websockets": {
            "single_subscribers": sum(len(v) for v in single_subscribers.values()),
            "all_subscribers": sum(len(v) for v in all_subscribers.values()),
            "pump_subscribers": len(pump_radar_subscribers),
            "realtime_subscribers": len(realtime_subscribers)
        }
    }
#==========================================================
# main.py dosyasına ekleyin (sağlık kontrolünden sonra)

# ==================== DEBUG ENDPOINTS ====================
@app.get("/debug/websocket-status")
async def debug_websocket_status():
    """WebSocket durumlarını göster"""
    from core import single_subscribers, all_subscribers, pump_radar_subscribers, realtime_subscribers
    
    # Single subscribers detayları
    single_details = {}
    for channel, subscribers in single_subscribers.items():
        if subscribers:
            single_details[channel] = len(subscribers)
    
    # All subscribers detayları
    all_details = {}
    for timeframe, subscribers in all_subscribers.items():
        if subscribers:
            all_details[timeframe] = len(subscribers)
    
    # Shared signals durumu
    from core import shared_signals
    signal_counts = {}
    for tf, signals in shared_signals.items():
        signal_counts[tf] = len(signals)
    
    # Active strong signals
    from core import active_strong_signals
    strong_counts = {}
    for tf, signals in active_strong_signals.items():
        strong_counts[tf] = len(signals)
    
    return JSONResponse({
        "timestamp": datetime.now().isoformat(),
        "websockets": {
            "single_subscribers": {
                "total": sum(len(v) for v in single_subscribers.values()),
                "details": single_details
            },
            "all_subscribers": {
                "total": sum(len(v) for v in all_subscribers.values()),
                "details": all_details
            },
            "pump_radar": len(pump_radar_subscribers),
            "realtime": len(realtime_subscribers)
        },
        "signals": {
            "shared_signals": signal_counts,
            "active_strong_signals": strong_counts,
            "last_update": last_update
        },
        "queue_status": {
            "signal_queue_size": signal_queue.qsize() if 'signal_queue' in globals() else 0
        }
    })

@app.get("/debug/signal/{symbol}/{timeframe}")
async def debug_signal(symbol: str, timeframe: str = "5m"):
    """Belirli bir sembol ve timeframe için sinyal durumunu göster"""
    symbol = symbol.upper().replace("/", "").replace("-", "").strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    
    from core import shared_signals
    
    signal_data = shared_signals.get(timeframe, {}).get(symbol)
    
    return JSONResponse({
        "symbol": symbol,
        "timeframe": timeframe,
        "has_signal": signal_data is not None,
        "signal_data": signal_data,
        "shared_signals_count": len(shared_signals.get(timeframe, {})),
        "timestamp": datetime.now().isoformat()
    })

@app.get("/debug/test-indicator/{symbol}")
async def test_indicator(symbol: str, timeframe: str = "5m"):
    """İndicator fonksiyonlarını test et"""
    try:
        from indicators import generate_ict_signal
        from core import get_binance_client
        
        symbol = symbol.upper().replace("/", "").replace("-", "").strip()
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        
        binance_client = get_binance_client()
        
        if not binance_client:
            return JSONResponse({
                "error": "Binance client not available",
                "success": False
            })
        
        # Veri çek
        ccxt_symbol = symbol.replace('USDT', '/USDT')
        klines = await binance_client.fetch_ohlcv(
            ccxt_symbol, 
            timeframe=timeframe, 
            limit=100
        )
        
        if not klines or len(klines) < 50:
            return JSONResponse({
                "error": f"Insufficient data for {symbol}: {len(klines) if klines else 0} candles",
                "success": False
            })
        
        # DataFrame oluştur
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Indicator'ü test et
        signal = generate_ict_signal(df, symbol, timeframe)
        
        return JSONResponse({
            "success": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "data_points": len(klines),
            "indicator_working": signal is not None,
            "signal_result": signal,
            "test_timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Indicator test error: {e}", exc_info=True)
        return JSONResponse({
            "error": str(e),
            "success": False,
            "traceback": str(e.__traceback__) if hasattr(e, '__traceback__') else None
        })

@app.get("/debug/websocket-test")
async def websocket_test_page():
    """WebSocket test sayfası"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WebSocket Test</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; background: #f0f0f0; }
            .test-container { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
            button { padding: 10px 20px; margin: 5px; background: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; }
            .log { background: #333; color: #0f0; padding: 10px; border-radius: 5px; font-family: monospace; height: 300px; overflow-y: auto; }
            .success { color: green; }
            .error { color: red; }
            .info { color: blue; }
        </style>
    </head>
    <body>
        <h1>WebSocket Test Sayfası</h1>
        
        <div class="test-container">
            <h3>Test 1: WebSocket Bağlantısı</h3>
            <input id="symbol" value="BTCUSDT" placeholder="Sembol">
            <input id="timeframe" value="5m" placeholder="Timeframe">
            <button onclick="testWebSocket()">WebSocket Bağlantısını Test Et</button>
            <div id="ws-log" class="log"></div>
        </div>
        
        <div class="test-container">
            <h3>Test 2: Sinyal Durumu</h3>
            <button onclick="checkSignal()">Sinyal Durumunu Kontrol Et</button>
            <div id="signal-log" class="log"></div>
        </div>
        
        <div class="test-container">
            <h3>Test 3: Indicator Test</h3>
            <button onclick="testIndicator()">Indicator'ü Test Et</button>
            <div id="indicator-log" class="log"></div>
        </div>
        
        <script>
            let ws = null;
            let logCount = 0;
            
            function log(containerId, message, className = '') {
                const container = document.getElementById(containerId);
                const line = document.createElement('div');
                line.innerHTML = `[${new Date().toLocaleTimeString()}] ${message}`;
                if (className) line.className = className;
                container.appendChild(line);
                container.scrollTop = container.scrollHeight;
                logCount++;
            }
            
            function testWebSocket() {
                const symbol = document.getElementById('symbol').value || 'BTCUSDT';
                const timeframe = document.getElementById('timeframe').value || '5m';
                const logId = 'ws-log';
                
                log(logId, `🔗 ${symbol}/${timeframe} için WebSocket bağlantısı deneniyor...`, 'info');
                
                if (ws) {
                    ws.close();
                    ws = null;
                }
                
                const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
                ws = new WebSocket(`${protocol}://${window.location.host}/ws/signal/${symbol}/${timeframe}`);
                
                ws.onopen = function() {
                    log(logId, `✅ WebSocket bağlantısı kuruldu!`, 'success');
                };
                
                ws.onmessage = function(event) {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.heartbeat) {
                            log(logId, `💓 Heartbeat: ${data.time || 'now'}`, 'info');
                        } else {
                            log(logId, `📨 Sinyal alındı: ${JSON.stringify(data).substring(0, 200)}...`, 'success');
                        }
                    } catch (e) {
                        log(logId, `❌ Veri parse hatası: ${e.message}`, 'error');
                    }
                };
                
                ws.onerror = function(error) {
                    log(logId, `❌ WebSocket hatası: ${error}`, 'error');
                };
                
                ws.onclose = function() {
                    log(logId, '🔌 WebSocket bağlantısı kapandı', 'info');
                };
                
                // 10 saniye sonra kapat
                setTimeout(() => {
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.close();
                        log(logId, '⏱️ Test tamamlandı, bağlantı kapatıldı', 'info');
                    }
                }, 10000);
            }
            
            async function checkSignal() {
                const symbol = document.getElementById('symbol').value || 'BTCUSDT';
                const timeframe = document.getElementById('timeframe').value || '5m';
                const logId = 'signal-log';
                
                log(logId, `🔍 ${symbol}/${timeframe} sinyal durumu kontrol ediliyor...`, 'info');
                
                try {
                    const response = await fetch(`/debug/signal/${symbol}/${timeframe}`);
                    const data = await response.json();
                    
                    if (data.has_signal) {
                        log(logId, `✅ Sinyal bulundu!`, 'success');
                        log(logId, `📊 Sinyal verisi: ${JSON.stringify(data.signal_data)}`, 'success');
                    } else {
                        log(logId, `❌ Sinyal bulunamadı`, 'error');
                        log(logId, `ℹ️ Toplam sinyal sayısı: ${data.shared_signals_count}`, 'info');
                    }
                    
                    // WebSocket durumunu da kontrol et
                    const wsStatus = await fetch('/debug/websocket-status');
                    const wsData = await wsStatus.json();
                    log(logId, `📡 WebSocket istatistikleri: ${JSON.stringify(wsData.websockets)}`, 'info');
                    
                } catch (error) {
                    log(logId, `❌ Kontrol hatası: ${error.message}`, 'error');
                }
            }
            
            async function testIndicator() {
                const symbol = document.getElementById('symbol').value || 'BTCUSDT';
                const timeframe = document.getElementById('timeframe').value || '5m';
                const logId = 'indicator-log';
                
                log(logId, `🧪 ${symbol}/${timeframe} için indicator test ediliyor...`, 'info');
                
                try {
                    const response = await fetch(`/debug/test-indicator/${symbol}?timeframe=${timeframe}`);
                    const data = await response.json();
                    
                    if (data.success) {
                        log(logId, `✅ Indicator başarıyla çalıştı!`, 'success');
                        log(logId, `📊 Veri noktaları: ${data.data_points}`, 'info');
                        log(logId, `⚡ Indicator çalışıyor: ${data.indicator_working}`, 'info');
                        if (data.signal_result) {
                            log(logId, `🎯 Sinyal sonucu: ${JSON.stringify(data.signal_result)}`, 'success');
                        }
                    } else {
                        log(logId, `❌ Indicator hatası: ${data.error}`, 'error');
                    }
                } catch (error) {
                    log(logId, `❌ Test hatası: ${error.message}`, 'error');
                }
            }
            
            // Otomatik test başlat
            setTimeout(() => {
                log('ws-log', '🚀 Otomatik test başlatılıyor...', 'info');
                testWebSocket();
                setTimeout(checkSignal, 2000);
                setTimeout(testIndicator, 4000);
            }, 1000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
# ==================== GİRİŞ SAYFASI ====================
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Giriş Yap | ICT SMART PRO</title>
    <style>
        body {{
            background: linear-gradient(135deg, #0a0022, #1a0033, #000);
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0;
        }}
        .login-box {{
            background: rgba(0, 0, 0, 0.7);
            padding: 40px;
            border-radius: 20px;
            text-align: center;
            max-width: 400px;
            width: 90%;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
        }}
        h2 {{
            color: #00dbde;
            margin-bottom: 30px;
            font-size: 2rem;
        }}
        input {{
            width: 100%;
            padding: 16px;
            margin: 12px 0;
            border: none;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
            font-size: 1.1rem;
            box-sizing: border-box;
        }}
        input:focus {{
            outline: 2px solid #00dbde;
            background: rgba(255, 255, 255, 0.15);
        }}
        button {{
            width: 100%;
            padding: 16px;
            background: linear-gradient(45deg, #fc00ff, #00dbde);
            border: none;
            border-radius: 12px;
            color: #fff;
            font-weight: bold;
            font-size: 1.2rem;
            cursor: pointer;
            margin-top: 20px;
            transition: all 0.3s;
        }}
        button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(252, 0, 255, 0.4);
        }}
        .demo-note {{
            margin-top: 20px;
            color: #888;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
    <div class="login-box">
        <h2>🔐 ICT SMART PRO</h2>
        <form method="post" action="/login">
            <input name="email" type="email" placeholder="E-posta adresiniz" required>
            <button type="submit">🚀 Giriş Yap</button>
        </form>
        <p class="demo-note">Demo için herhangi bir e-posta kullanabilirsiniz</p>
    </div>
</body>
</html>"""

@app.post("/login")
async def login(request: Request):
    form = await request.form()
    email = form.get("email", "").strip().lower()
    if "@" in email:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("user_email", email, max_age=2592000, httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login")

# ==================== BAŞLATMA ====================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=port,
        log_level="info",
        access_log=True
    )



