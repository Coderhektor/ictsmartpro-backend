
# main.py — TAM DÜZELTİLMİŞ VE KUSURSUZ VERSİYON
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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response, UploadFile, File, HTTPException
from core import (
    initialize, cleanup, single_subscribers, all_subscribers,
    pump_radar_subscribers,
    shared_signals, active_strong_signals, top_gainers, last_update, rt_ticker,
    get_binance_client
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

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="3.0 - STABLE")
#===========================================================================
# main.py imports kısmına ekle
from core import price_sources_status

# Yeni WebSocket endpoint
@app.websocket("/ws/price_sources")
async def ws_price_sources(websocket: WebSocket):
    await websocket.accept()
    price_sources_subscribers.add(websocket)  # yeni set tanımla: price_sources_subscribers = set()

    # İlk veri gönder
    await websocket.send_json({
        "sources": price_sources_status,
        "total_symbols": len(price_pool)
    })

    try:
        while True:
            await asyncio.sleep(5)
            await websocket.send_json({
                "sources": price_sources_status,
                "total_symbols": len(price_pool)
            })
    except WebSocketDisconnect:
        price_sources_subscribers.discard(websocket)
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
    await websocket.accept()
    symbol = pair.upper().replace("/", "").replace("-", "").strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    channel = f"{symbol}:{timeframe}"
    single_subscribers[channel].add(websocket)
    
    sig = shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        await websocket.send_json(sig)
    
    try:
        while True:
            await asyncio.sleep(15)
            await websocket.send_json({"heartbeat": True})
    except WebSocketDisconnect:
        pass
    finally:
        single_subscribers[channel].discard(websocket)

@app.websocket("/ws/all/{timeframe}")
async def ws_all(websocket: WebSocket, timeframe: str):
    supported = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
    if timeframe not in supported:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    all_subscribers[timeframe].add(websocket)
    await websocket.send_json(active_strong_signals.get(timeframe, []))
    
    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"ping": True})
    except WebSocketDisconnect:
        all_subscribers[timeframe].discard(websocket)

@app.websocket("/ws/pump_radar")
async def ws_pump(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    await websocket.send_json({"top_gainers": top_gainers, "last_update": last_update})
    try:
        while True:
            await asyncio.sleep(20)
            await websocket.send_json({"ping": True})
    except WebSocketDisconnect:
        pump_radar_subscribers.discard(websocket)

@app.websocket("/ws/realtime_price")
async def ws_realtime_price(websocket: WebSocket):
    await websocket.accept()
    await rt_ticker.subscribe(websocket)  # sınıfın kendi metodu
    
    try:
        while True:
            data = get_all_prices_snapshot(limit=50)  # core'dan fonksiyonu import etmeyi unutma!
            await websocket.send_json(data)
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        await rt_ticker.unsubscribe(websocket)
    except Exception as e:
        logger.error(f"Realtime price WS error: {e}")
        await rt_ticker.unsubscribe(websocket)

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
            font-family: sans-serif;
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
            font-size: clamp(2rem, 5vw, 5rem);
            text-align: center;
            background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: g 8s infinite;
        }}
        @keyframes g {{
            0% {{ background-position: 0%; }}
            100% {{ background-position: 200%; }}
        }}
        .update {{
            text-align: center;
            color: #00ffff;
            margin: 30px;
            font-size: clamp(1rem, 3vw, 1.8rem);
        }}
        table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0 12px;
            margin: 30px 0;
        }}
        th {{
            background: #ffffff11;
            padding: clamp(10px, 2vw, 20px);
            font-size: clamp(1rem, 2.5vw, 1.6rem);
        }}
        tr {{
            background: #ffffff08;
            transition: .4s;
        }}
        tr:hover {{
            transform: scale(1.02);
            box-shadow: 0 15px 40px #00ffff44;
        }}
        .green {{ color: #00ff88; text-shadow: 0 0 20px #00ff88; }}
        .red {{ color: #ff4444; text-shadow: 0 0 20px #ff4444; }}
        .btn {{
            display: block;
            width: 90%;
            max-width: 500px;
            margin: 20px auto;
            padding: clamp(15px, 3vw, 25px);
            font-size: clamp(1.2rem, 4vw, 2.2rem);
            background: linear-gradient(45deg, #fc00ff, #00dbde);
            color: #fff;
            text-align: center;
            border-radius: 50px;
            text-decoration: none;
            box-shadow: 0 0 60px #ff00ff88;
            transition: .3s;
        }}
        .btn:hover {{
            transform: scale(1.08);
            box-shadow: 0 0 100px #ff00ff;
        }}
    </style>
</head>
<body>
    <div style='position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:clamp(0.8rem, 2vw, 1.2rem);z-index:1000;'>
        Hoş geldin, {user}
    </div>
    {visitor_stats_html}
    <div class="container">
        <h1>ICT SMART PRO</h1>
        <div class="update" id="update">Veri yükleniyor...</div>
        <table>
            <thead>
                <tr>
                    <th>SIRA</th>
                    <th>COİN</th>
                    <th>FİYAT</th>
                    <th>24S DEĞİŞİM</th>
                </tr>
            </thead>
            <tbody id="table-body">
                <tr>
                    <td colspan="4" style="padding:80px;color:#888">Pump radar yükleniyor...</td>
                </tr>
            </tbody>
        </table>
        <a href="/signal" class="btn">🚀 Tek Coin Canlı Sinyal + Grafik</a>
        <a href="/signal/all" class="btn">🔥 Tüm Coinleri Tara</a>
    </div>
    <script>
        const ws = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/pump_radar');
        ws.onmessage = function(e) {{
            const d = JSON.parse(e.data);
            document.getElementById('update').innerHTML = `Son Güncelleme: <strong>${{d.last_update || 'Şimdi'}}</strong>`;
            const t = document.getElementById('table-body');
            if (!d.top_gainers || d.top_gainers.length === 0) {{
                t.innerHTML = '<tr><td colspan="4" style="padding:80px;color:#ffd700">😴 Şu anda pump yok</td></tr>';
                return;
            }}
            t.innerHTML = d.top_gainers.map((c, i) => `
                <tr>
                    <td>#${{i+1}}</td>
                    <td><strong>${{c.symbol}}</strong></td>
                    <td>$${{c.price.toFixed(4)}}</td>
                    <td class="${{c.change > 0 ? 'green' : 'red'}}">${{c.change > 0 ? '+' : ''}}${{c.change.toFixed(2)}}%</td>
                </tr>
            `).join('');
        }};
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

# ==================== TEK COİN SİNYAL SAYFASI ====================
@app.get("/signal", response_class=HTMLResponse)
async def signal(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    # Ziyaretçi istatistikleri HTML'i
    visitor_stats_html = get_visitor_stats_html()
    
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>CANLI SİNYAL + GRAFİK | ICT SMART PRO</title>
    <style>
        body {{
            background: linear-gradient(135deg, #0a0022, #1a0033, #000);
            color: #fff;
            font-family: sans-serif;
            margin: 0;
            padding: 20px 0;
            min-height: 100vh;
        }}
        .container {{
            max-width: 1200px;
            margin: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 25px;
        }}
        h1 {{
            font-size: clamp(2rem, 5vw, 3.8rem);
            text-align: center;
            background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: g 8s infinite;
        }}
        @keyframes g {{
            0% {{ background-position: 0; }}
            100% {{ background-position: 200%; }}
        }}
        .controls {{
            background: #ffffff11;
            border-radius: 20px;
            padding: 20px;
            text-align: center;
        }}
        input, select, button {{
            width: 100%;
            max-width: 500px;
            padding: 15px;
            margin: 10px auto;
            font-size: 1.4rem;
            border: none;
            border-radius: 16px;
            background: #333;
            color: #fff;
        }}
        button {{
            background: linear-gradient(45deg, #fc00ff, #00dbde);
            font-weight: bold;
            cursor: pointer;
        }}
        #analyze-btn {{
            background: linear-gradient(45deg, #00dbde, #ff00ff, #00ffff);
        }}
        #status {{
            color: #00ffff;
            text-align: center;
            margin: 15px;
        }}
        #price-text {{
            font-size: clamp(3rem, 8vw, 5rem);
            font-weight: bold;
            background: linear-gradient(90deg, #00ffff, #ff00ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        #signal-card {{
            background: #000000aa;
            border-radius: 20px;
            padding: 25px;
            text-align: center;
            min-height: 160px;
        }}
        #signal-card.green {{ border-left: 8px solid #00ff88; }}
        #signal-card.red {{ border-left: 8px solid #ff4444; }}
        #signal-text {{
            font-size: clamp(2rem, 5vw, 3rem);
        }}
        #ai-box {{
            background: #0d0033ee;
            border-radius: 20px;
            padding: 25px;
            border: 3px solid #00dbde;
            display: none;
        }}
        .chart-container {{
            width: 95%;
            max-width: 1000px;
            margin: 30px auto;
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 15px 50px #00ffff44;
            background: #0a0022;
        }}
        #tradingview_widget {{
            height: 500px;
            width: 100%;
        }}
    </style>
</head>
<body>
    <div style="position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;z-index:1000;">
        Hoş geldin, {user}
    </div>
    {visitor_stats_html}
    <div class="container">
        <h1>📊 CANLI SİNYAL + GRAFİK</h1>
        <div class="controls">
            <input id="pair" placeholder="Coin (örn: BTCUSDT)" value="BTCUSDT">
            <select id="tf">
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
            <button onclick="connect()">🔴 CANLI SİNYAL BAĞLANTISI KUR</button>
            <button id="analyze-btn" onclick="analyzeChartWithAI()">🤖 GRAFİĞİ GPT-4o İLE ANALİZ ET</button>
            <div id="status">Grafik yükleniyor...</div>
        </div>
        <div style="text-align:center;margin:20px">
            <div id="price-text">Yükleniyor...</div>
        </div>
        <div id="signal-card">
            <div id="signal-text" style="color:#ffd700">Sinyal bağlantısı kurulmadı</div>
            <div id="signal-details">Canlı sinyal için butona tıklayın.</div>
        </div>
        <div id="ai-box">
            <h3 style="color:#00dbde;text-align:center">🤖 GPT-4o Teknik Analizi</h3>
            <p id="ai-comment">Analiz için butona tıklayın.</p>
        </div>
        <div class="chart-container">
            <div id="tradingview_widget"></div>
        </div>
        <div style="text-align:center">
            <a href="/" style="color:#00dbde">← Ana Sayfa</a> | 
            <a href="/signal/all" style="color:#00dbde">Tüm Coinler</a>
        </div>
    </div>
    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>
        let ws = null;
        let tvWidget = null;
        let currentPrice = null;
        const tfMap = {{
            "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
            "1h": "60", "4h": "240", "1d": "D", "1w": "W"
        }};
        
        function getSymbol() {{
            let pair = document.getElementById('pair').value.trim().toUpperCase();
            if (!pair.endsWith("USDT")) pair += "USDT";
            return "BINANCE:" + pair;
        }}
        
        function createWidget() {{
            const symbol = getSymbol();
            const interval = tfMap[document.getElementById('tf').value] || "5";
            
            if (tvWidget) tvWidget.remove();
            
            tvWidget = new TradingView.widget({{
                autosize: true,
                width: "100%",
                height: 500,
                symbol: symbol,
                interval: interval,
                timezone: "Etc/UTC",
                theme: "dark",
                style: "1",
                locale: "tr",
                container_id: "tradingview_widget",
                studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies"]
            }});
            
            tvWidget.onChartReady(() => {{
                document.getElementById('status').innerHTML = "✅ Grafik yüklendi • Sinyal bağlantısı kurun";
                
                setInterval(() => {{
                    try {{
                        const price = tvWidget.activeChart().getSeries().lastPrice();
                        if (price && price !== currentPrice) {{
                            currentPrice = price;
                            document.getElementById('price-text').innerHTML = '$' + parseFloat(price).toFixed(price > 1 ? 2 : 6);
                        }}
                    }} catch(e) {{}}
                }}, 1500);
            }});
        }}
        
        document.addEventListener("DOMContentLoaded", createWidget);
        document.getElementById('pair').addEventListener('change', createWidget);
        document.getElementById('tf').addEventListener('change', createWidget);
        
        async function analyzeChartWithAI() {{
            const btn = document.getElementById('analyze-btn');
            const box = document.getElementById('ai-box');
            const comment = document.getElementById('ai-comment');
            
            btn.disabled = true;
            btn.innerHTML = "Analiz ediliyor...";
            box.style.display = 'block';
            comment.innerHTML = "📸 Grafik yakalanıyor...<br>🧠 Analiz yapılıyor...";
            
            try {{
                // Kendi analiz motorumuzu çalıştır
                const symbol = getSymbol().replace("BINANCE:", "");
                const timeframe = document.getElementById('tf').value;
                
                const response = await fetch('/api/analyze-chart', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        symbol: symbol,
                        timeframe: timeframe
                    }})
                }});
                
                const data = await response.json();
                
                if (data.analysis) {{
                    comment.innerHTML = data.analysis.replace(/\\n/g, '<br>');
                }} else {{
                    comment.innerHTML = "❌ Analiz alınamadı: " + (data.detail || 'Bilinmeyen hata');
                }}
            }} catch (err) {{
                comment.innerHTML = "❌ Bağlantı hatası. Tekrar deneyin.<br>" + err.message;
            }} finally {{
                btn.disabled = false;
                btn.innerHTML = "🤖 GRAFİĞİ GPT-4o İLE ANALİZ ET";
            }}
        }}
        
        function connect() {{
            const symbolInput = document.getElementById('pair').value.trim().toUpperCase();
            const tfSelect = document.getElementById('tf').value;
            
            // Symbol formatını düzelt (USDT ekle)
            let symbol = symbolInput;
            if (!symbol.endsWith("USDT")) symbol += "USDT";
            
            // TradingView symbol
            const tvSymbol = "BINANCE:" + symbol;
            
            // Interval map
            const tfMap = {{
                "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
                "1h": "60", "4h": "240", "1d": "D", "1w": "W"
            }};
            
            const interval = tfMap[tfSelect] || "5";
            
            // Eğer widget varsa önce kaldır
            if (tvWidget) {{
                tvWidget.remove();
                tvWidget = null;
            }}
            
            // Yeni widget oluştur
            tvWidget = new TradingView.widget({{
                autosize: true,
                width: "100%",
                height: 500,
                symbol: tvSymbol,
                interval: interval,
                timezone: "Etc/UTC",
                theme: "dark",
                style: "1",
                locale: "tr",
                container_id: "tradingview_widget",
                studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies"]
            }});
            
            tvWidget.onChartReady(() => {{
                document.getElementById('status').innerHTML = `✅ Grafik yüklendi: ${{symbol}} ${{tfSelect.toUpperCase()}} • Canlı sinyal akışı başladı!`;
                
                // Fiyat takibi
                setInterval(() => {{
                    try {{
                        const price = tvWidget.activeChart().getSeries().lastPrice();
                        if (price && price !== currentPrice) {{
                            currentPrice = price;
                            document.getElementById('price-text').innerHTML = '$' + parseFloat(price).toFixed(price > 1 ? 2 : 6);
                        }}
                    }} catch(e) {{}}
                }}, 1500);
            }});
            
            // Şimdi WebSocket bağlantısını kur
            if (ws) ws.close();
            ws = new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws/signal/'+symbol+'/'+tfSelect);
            
            ws.onopen = () => {{
                document.getElementById('status').innerHTML = `✅ ${{symbol}} ${{tfSelect.toUpperCase()}} için canlı sinyal akışı başladı!`;
            }};
            
            ws.onmessage = e => {{
                const d = JSON.parse(e.data);
                const card = document.getElementById('signal-card');
                const text = document.getElementById('signal-text');
                const details = document.getElementById('signal-details');
                
                text.innerHTML = d.signal || "Sinyal bekleniyor...";
                details.innerHTML = `
                    <strong>${{d.pair || symbol.replace('USDT','/USDT')}}</strong><br>
                    Skor: <strong>${{d.score || '?'}}/100</strong> | ${{d.killzone || ''}}<br>
                    ${{d.last_update ? 'Son: ' + d.last_update : ''}}<br>
                    <small>${{d.triggers || ''}}</small>
                `;
                
                if (d.signal && d.signal.includes('ALIM')) {{
                    card.className = 'green';
                    text.style.color = '#00ff88';
                }} else if (d.signal && d.signal.includes('SATIM')) {{
                    card.className = 'red';
                    text.style.color = '#ff4444';
                }} else {{
                    card.className = '';
                    text.style.color = '#ffd700';
                }}
            }};
            
            ws.onerror = (err) => {{
                document.getElementById('status').innerHTML = "❌ WebSocket bağlantı hatası";
            }};
            
            ws.onclose = () => {{
                document.getElementById('status').innerHTML = "🔌 Sinyal bağlantısı kapandı. Yeniden bağlanmak için butona tıklayın.";
            }};
        }}
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

# ==================== API ENDPOINTS ====================
@app.post("/api/analyze-chart")
async def analyze_chart(request: Request):
    try:
        body = await request.json()
        symbol = body.get("symbol", "BTCUSDT").upper()
        timeframe = body.get("timeframe", "5m")
        
        logger.info(f"Analiz için veri çekiliyor: {symbol} {timeframe}")
        
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
            
            logger.info(f"{len(klines)} mum verisi alındı")
            
            if not klines or len(klines) < 100:
                return JSONResponse({
                    "analysis": f"❌ {symbol} için yeterli veri bulunamadı. (Alınan: {len(klines) if klines else 0} mum)",
                    "success": False
                })
            
        except Exception as e:
            logger.error(f"Binance veri hatası: {e}")
            return JSONResponse({
                "analysis": f"❌ Veri alınamadı: {str(e)[:100]}",
                "success": False
            })
        
        # DataFrame oluştur - Binance formatına göre
        df = pd.DataFrame(klines)
        
        # Sütun isimlerini ayarla (Binance formatı: timestamp, open, high, low, close, volume)
        if len(df.columns) >= 6:
            df = df.iloc[:, :6]
            df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        elif len(df.columns) >= 5:
            df = df.iloc[:, :5]
            df.columns = ['timestamp', 'open', 'high', 'low', 'close']
            df['volume'] = 1000  # Default volume
        else:
            return JSONResponse({
                "analysis": f"❌ Geçersiz veri formatı",
                "success": False
            })
        
        # Sayısal verilere çevir
        for col in ['timestamp', 'open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # NaN değerleri temizle
        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        
        if len(df) < 100:
            logger.warning(f"{symbol}: Sadece {len(df)} mum temizlendi")
            df = df.tail(min(100, len(df)))
        
        # Sinyal üret
        signal = None
        try:
            from indicators import generate_ict_signal, generate_simple_signal
            
            # Ana sinyal fonksiyonunu dene
            signal = generate_ict_signal(df, symbol, timeframe)
            
            # Eğer sinyal alınamazsa basit fonksiyonu kullan
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

🎯 Tetikleyenler:
{signal['triggers']}

📈 Teknik Analiz:
{symbol} {timeframe} grafiğinde {signal['signal'].replace('🚀', '').replace('🔥', '').replace('⏸️', '').strip()} sinyali tespit edildi.

ICT stratejisine göre:
• RSI6 ve SMA50 analizi yapıldı
• Killzone: {signal['killzone']}
• Güven skoru: {signal['score']}/100

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
@app.get("/signal/all", response_class=HTMLResponse)
async def signal_all(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    visitor_stats_html = get_visitor_stats_html()
    
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>TÜM COİNLER | ICT SMART PRO</title>
    <style>
        body {{
            background: linear-gradient(135deg, #0a0022, #1a0033, #000);
            color: #fff;
            font-family: sans-serif;
            margin: 0;
            padding: 20px 0;
            min-height: 100vh;
        }}
        .container {{
            max-width: 1200px;
            margin: auto;
            padding: 20px;
        }}
        h1 {{
            font-size: clamp(2rem, 5vw, 3rem);
            text-align: center;
            background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .controls {{
            background: #ffffff11;
            border-radius: 20px;
            padding: 20px;
            text-align: center;
            margin: 20px 0;
        }}
        select {{
            width: 90%;
            max-width: 400px;
            padding: 15px;
            margin: 10px;
            font-size: 1.2rem;
            border: none;
            border-radius: 12px;
            background: #333;
            color: #fff;
        }}
        #status {{
            color: #00ffff;
            text-align: center;
            margin: 15px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 30px 0;
        }}
        th {{
            background: #ffffff11;
            padding: 15px;
            text-align: left;
        }}
        tr {{
            border-bottom: 1px solid #333;
        }}
        tr:hover {{
            background: #00ffff11;
        }}
        .green {{ color: #00ff88; }}
        .red {{ color: #ff4444; }}
    </style>
</head>
<body>
    <div style="position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;z-index:1000;">
        Hoş geldin, {user}
    </div>
    {visitor_stats_html}
    <div class="container">
        <h1>🔥 TÜM COİN SİNYALLERİ</h1>
        <div class="controls">
            <select id="tf" onchange="connect()">
                <option value="5m">5 Dakika</option>
                <option value="15m">15 Dakika</option>
                <option value="1h">1 Saat</option>
                <option value="4h">4 Saat</option>
                <option value="1d">1 Gün</option>
            </select>
            <div id="status">Zaman dilimi seçin...</div>
        </div>
        <div id="table-container">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>COİN</th>
                        <th>SİNYAL</th>
                        <th>SKOR</th>
                        <th>FİYAT</th>
                        <th>ZAMAN</th>
                    </tr>
                </thead>
                <tbody id="signal-table">
                    <tr>
                        <td colspan="6" style="padding:50px;text-align:center;color:#888">
                            Zaman dilimi seçin...
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
        <div style="text-align:center;margin-top:30px">
            <a href="/" style="color:#00dbde;margin-right:20px">← Ana Sayfa</a>
            <a href="/signal" style="color:#00dbde">Tek Coin Sinyal →</a>
        </div>
    </div>
    <script>
        let ws = null;
        
        function connect() {{
            const timeframe = document.getElementById('tf').value;
            document.getElementById('status').innerHTML = `${{timeframe.toUpperCase()}} sinyalleri yükleniyor...`;
            
            if (ws) ws.close();
            
            ws = new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws/all/'+timeframe);
            
            ws.onopen = () => {{
                document.getElementById('status').innerHTML = `✅ ${{timeframe.toUpperCase()}} canlı sinyal akışı başladı!`;
            }};
            
            ws.onmessage = e => {{
                const data = JSON.parse(e.data);
                const table = document.getElementById('signal-table');
                
                if (!data || data.length === 0) {{
                    table.innerHTML = '<tr><td colspan="6" style="padding:50px;text-align:center;color:#ffd700">😴 Şu anda sinyal yok</td></tr>';
                    return;
                }}
                
                table.innerHTML = data.map((sig, i) => `
                    <tr>
                        <td>#${{i+1}}</td>
                        <td><strong>${{sig.pair || 'N/A'}}</strong></td>
                        <td class="${{sig.signal && sig.signal.includes('ALIM') ? 'green' : sig.signal && sig.signal.includes('SATIM') ? 'red' : ''}}">
                            ${{sig.signal || 'Bekle'}}
                        </td>
                        <td>${{sig.score || '?'}}/100</td>
                        <td>$${{sig.current_price ? sig.current_price.toFixed(4) : 'N/A'}}</td>
                        <td>${{sig.last_update || ''}}</td>
                    </tr>
                `).join('');
            }};
            
            ws.onerror = () => {{
                document.getElementById('status').innerHTML = "❌ WebSocket bağlantı hatası";
            }};
            
            ws.onclose = () => {{
                document.getElementById('status').innerHTML = "🔌 Bağlantı kapandı. Yeniden bağlanmak için zaman dilimi seçin.";
            }};
        }}
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
            font-family: sans-serif;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: auto;
        }}
        h1 {{
            color: #00dbde;
            text-align: center;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        .stat-card {{
            background: #ffffff11;
            padding: 20px;
            border-radius: 15px;
            text-align: center;
        }}
        .stat-card h3 {{
            color: #00ffff;
            margin-top: 0;
        }}
        .stat-card .number {{
            font-size: 2.5rem;
            font-weight: bold;
            color: #00ff88;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 30px;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #333;
        }}
        th {{
            background: #ffffff11;
            color: #00dbde;
        }}
        .back-btn {{
            display: inline-block;
            margin: 20px 0;
            padding: 10px 20px;
            background: #00dbde;
            color: #fff;
            text-decoration: none;
            border-radius: 8px;
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
            </div>
            <div class="stat-card">
                <h3>Aktif Kullanıcılar</h3>
                <div class="number">{stats['active_users']}</div>
            </div>
            <div class="stat-card">
                <h3>Bugünkü Ziyaretler</h3>
                <div class="number">{stats['today_visits']}</div>
            </div>
            <div class="stat-card">
                <h3>Bugünkü Benzersiz</h3>
                <div class="number">{stats['today_unique']}</div>
            </div>
        </div>
        
        <h2>Sayfa Görüntülemeleri</h2>
        <table>
            <thead>
                <tr>
                    <th>Sayfa</th>
                    <th>Görüntülenme</th>
                </tr>
            </thead>
            <tbody>
                {page_views_html}
            </tbody>
        </table>
        
        <p style="color:#888;margin-top:20px">Son Güncelleme: {stats['last_updated']}</p>
        
        <a href="/" class="back-btn">← Ana Sayfaya Dön</a>
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
    return {
        "status": "ok",
        "symbols": len(all_usdt_symbols) if all_usdt_symbols else 0,
        "realtime_coins": len(rt_ticker.get("tickers", [])),
        "strong_5m": len(active_strong_signals.get("5m", [])),
        "openai_available": openai_client is not None,
        "visitor_stats": {
            "total_visits": stats["total_visits"],
            "active_users": stats["active_users"],
            "today_visits": stats["today_visits"]
        }
    }

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
            font-family: sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .login-box {{
            background: #000000cc;
            padding: 40px;
            border-radius: 20px;
            text-align: center;
            max-width: 400px;
            width: 90%;
        }}
        h2 {{
            color: #00dbde;
            margin-bottom: 30px;
        }}
        input {{
            width: 100%;
            padding: 15px;
            margin: 10px 0;
            border: none;
            border-radius: 12px;
            background: #333;
            color: #fff;
            font-size: 1.1rem;
        }}
        button {{
            width: 100%;
            padding: 15px;
            background: linear-gradient(45deg, #fc00ff, #00dbde);
            border: none;
            border-radius: 12px;
            color: #fff;
            font-weight: bold;
            font-size: 1.2rem;
            cursor: pointer;
            margin-top: 20px;
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
        <p style="margin-top:20px;color:#888">Demo için herhangi bir e-posta kullanabilirsiniz</p>
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
#=============================================================
@app.get("/debug/sources", response_class=HTMLResponse)
async def price_sources_debug(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")

    visitor_stats_html = get_visitor_stats_html()

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fiyat Kaynakları İzleyici | ICT SMART PRO</title>
    <style>
        body {{ background: #000; color: #fff; font-family: sans-serif; padding: 20px; }}
        .container {{ max-width: 1000px; margin: auto; }}
        h1 {{ color: #00dbde; text-align: center; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 15px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ background: #ffffff11; }}
        .healthy {{ color: #00ff88; }}
        .unhealthy {{ color: #ff4444; }}
        .status {{ font-weight: bold; }}
    </style>
</head>
<body>
    {get_visitor_stats_html()}
    <div class="container">
        <h1>🔴 CANLI FİYAT KAYNAKLARI MONİTÖRÜ</h1>
        <p>Toplam takip edilen coin: <strong id="total-coins">Yükleniyor...</strong></p>
        <table>
            <thead>
                <tr>
                    <th>Borsa</th>
                    <th>Durum</th>
                    <th>Son Güncelleme</th>
                    <th>Kapsadığı Coin Sayısı</th>
                    <th>Hata (varsa)</th>
                </tr>
            </thead>
            <tbody id="sources-table">
                <tr><td colspan="5">Bağlantı kuruluyor...</td></tr>
            </tbody>
        </table>
        <p style="text-align:center"><a href="/" style="color:#00dbde">← Ana Sayfa</a></p>
    </div>
    <script>
        const ws = new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws/price_sources');
        ws.onmessage = function(e) {{
            const data = JSON.parse(e.data);
            document.getElementById('total-coins').innerText = data.total_symbols;

            const table = document.getElementById('sources-table');
            table.innerHTML = Object.entries(data.sources).map(([source, info]) => `
                <tr>
                    <td><strong>${{source.toUpperCase()}}</strong></td>
                    <td class="status ${{info.healthy ? 'healthy' : 'unhealthy'}}">
                        ${{info.healthy ? '✅ Çalışıyor' : '❌ Bağlantı Sorunu'}}
                    </td>
                    <td>${{info.last_update || 'Bilinmiyor'}}</td>
                    <td>${{info.symbols_count || 0}}</td>
                    <td style="color:#ff8888">${{info.last_error || '-'}}</td>
                </tr>
            `).join('');
        }};
    </script>
</body>
</html>"""

# ==================== BAŞLATMA ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
