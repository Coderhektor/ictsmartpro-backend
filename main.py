# main.py — OPTIMIZED & RAILWAY READY
import logging
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Dict, List
import json
import hashlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core import (
    initialize, cleanup, single_subscribers, all_subscribers,
    pump_radar_subscribers, realtime_subscribers,
    shared_signals, active_strong_signals, top_gainers, last_update,
    get_binance_client, signal_queue, rt_ticker,
    get_all_prices_snapshot
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("main")

# ==================== ZİYARETÇİ SAYACI ====================
class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users = set()
        self.daily_stats = {}
        self.page_views = {}

    def add_visit(self, page: str, user_id: str = None) -> int:
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

# ==================== APP LIFESPAN ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize()
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="4.0")

# ==================== MIDDLEWARE — ZİYARETÇİ SAYACI ====================
@app.middleware("http")
async def count_visitors(request: Request, call_next):
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        ip = request.client.host or "anonymous"
        visitor_id = hashlib.md5(ip.encode()).hexdigest()[:8]

    page = request.url.path
    visitor_counter.add_visit(page, visitor_id)

    response = await call_next(request)

    if not request.cookies.get("visitor_id"):
        response.set_cookie("visitor_id", visitor_id, max_age=86400, httponly=True, samesite="lax")
    return response

# ==================== WEBSOCKET ENDPOINTS ====================
@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_signal(websocket: WebSocket, pair: str, timeframe: str):
    await websocket.accept()
    symbol = pair.upper().replace("/", "").replace("-", "").replace(" ", "").strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    channel = f"{symbol}:{timeframe}"

    if channel not in single_subscribers:
        single_subscribers[channel] = set()
    single_subscribers[channel].add(websocket)
    logger.info(f"📡 Yeni single subscriber: {channel}")

    sig = shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        try:
            await websocket.send_json(sig)
        except:
            pass

    try:
        while True:
            await asyncio.sleep(15)
            try:
                await websocket.send_json({"heartbeat": True, "time": datetime.now().strftime("%H:%M:%S")})
            except:
                break
    except WebSocketDisconnect:
        pass
    finally:
        if channel in single_subscribers:
            single_subscribers[channel].discard(websocket)

@app.websocket("/ws/all/{timeframe}")
async def ws_all(websocket: WebSocket, timeframe: str):
    supported = ["5m", "15m", "1h", "4h"]
    if timeframe not in supported:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    if timeframe not in all_subscribers:
        all_subscribers[timeframe] = set()
    all_subscribers[timeframe].add(websocket)
    logger.info(f"📡 Yeni all subscriber: {timeframe}")

    try:
        signals = active_strong_signals.get(timeframe, [])[:10]
        await websocket.send_json(signals)
    except:
        pass

    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"ping": True, "time": datetime.now().strftime("%H:%M:%S")})
    except WebSocketDisconnect:
        pass
    finally:
        if timeframe in all_subscribers:
            all_subscribers[timeframe].discard(websocket)

@app.websocket("/ws/pump_radar")
async def ws_pump(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    logger.info(f"📡 Yeni pump radar subscriber")

    try:
        await websocket.send_json({"top_gainers": top_gainers[:5], "last_update": last_update})
    except:
        pass

    try:
        while True:
            await asyncio.sleep(20)
            await websocket.send_json({"ping": True, "time": datetime.now().strftime("%H:%M:%S")})
    except WebSocketDisconnect:
        pass
    finally:
        pump_radar_subscribers.discard(websocket)

@app.websocket("/ws/realtime_price")
async def ws_realtime_price(websocket: WebSocket):
    await websocket.accept()
    await rt_ticker.subscribe(websocket)
    logger.info(f"📡 Yeni realtime price subscriber")

    try:
        while True:
            await asyncio.sleep(3)
            data = get_all_prices_snapshot(limit=50)
            await rt_ticker.broadcast(data)
    except WebSocketDisconnect:
        pass
    finally:
        await rt_ticker.unsubscribe(websocket)

# ==================== HTML TEMPLATES ====================
HTML_HEADER = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} | ICT SMART PRO</title>
    <style>
        :root {{
            --primary: #00dbde;
            --secondary: #fc00ff;
            --success: #00ff88;
            --danger: #ff4444;
            --bg-dark: #0a0022;
            --bg-darker: #000;
        }}
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            background: linear-gradient(135deg, var(--bg-dark), #1a0033, var(--bg-darker));
            color: white;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            min-height: 100vh;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        h1 {{
            font-size: 2.8rem;
            text-align: center;
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin: 30px 0;
            animation: gradient 8s infinite;
        }}
        @keyframes gradient {{
            0% {{ background-position: 0%; }}
            100% {{ background-position: 200%; }}
        }}
        .card {{
            background: rgba(255, 255, 255, 0.05);
            border-radius: 20px;
            padding: 30px;
            backdrop-filter: blur(10px);
            margin: 20px 0;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .btn {{
            display: inline-block;
            padding: 14px 28px;
            background: linear-gradient(45deg, var(--secondary), var(--primary));
            color: white;
            text-decoration: none;
            border-radius: 12px;
            font-weight: bold;
            border: none;
            cursor: pointer;
            transition: all 0.3s;
            margin: 10px;
        }}
        .btn:hover {{
            transform: translateY(-3px);
            box-shadow: 0 10px 25px rgba(252, 0, 255, 0.3);
        }}
        .form-group {{
            margin: 20px 0;
        }}
        .form-control {{
            width: 100%;
            padding: 15px;
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.2);
            background: rgba(0, 0, 0, 0.3);
            color: white;
            font-size: 1.1rem;
            margin-top: 8px;
        }}
        .form-control:focus {{
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 15px rgba(0, 219, 222, 0.3);
        }}
        .select-wrapper {{
            position: relative;
            width: 100%;
        }}
        .select-wrapper select {{
            width: 100%;
            padding: 15px 20px;
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.2);
            background: rgba(0, 0, 0, 0.6);
            color: white;
            font-size: 1.1rem;
            appearance: none;
            -webkit-appearance: none;
            cursor: pointer;
        }}
        .select-wrapper::after {{
            content: '▼';
            position: absolute;
            right: 20px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--primary);
            pointer-events: none;
        }}
        .stats {{
            position: fixed;
            top: 15px;
            right: 15px;
            background: rgba(0, 0, 0, 0.7);
            padding: 12px 20px;
            border-radius: 15px;
            font-size: 0.9rem;
            color: var(--success);
            z-index: 1000;
        }}
        .user-info {{
            position: fixed;
            top: 15px;
            left: 15px;
            background: rgba(0, 0, 0, 0.7);
            padding: 12px 20px;
            border-radius: 15px;
            color: var(--primary);
            z-index: 1000;
        }}
        .timeframe-select {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
            gap: 12px;
            margin: 20px 0;
        }}
        .timeframe-btn {{
            padding: 12px;
            background: rgba(40, 40, 60, 0.7);
            border: 1px solid rgba(100, 100, 255, 0.3);
            border-radius: 10px;
            color: #e0e0ff;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .timeframe-btn:hover {{
            background: rgba(60, 60, 100, 0.9);
            border-color: var(--primary);
        }}
        .timeframe-btn.active {{
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            color: white;
            font-weight: bold;
            border: none;
        }}
        .signal-buy {{
            color: var(--success);
            border-left: 4px solid var(--success);
        }}
        .signal-sell {{
            color: var(--danger);
            border-left: 4px solid var(--danger);
        }}
        .signal-neutral {{
            color: #ffd700;
            border-left: 4px solid #ffd700;
        }}
        .price-display {{
            font-size: 3.5rem;
            font-weight: bold;
            text-align: center;
            margin: 20px 0;
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .chart-container {{
            width: 100%;
            height: 500px;
            border-radius: 15px;
            overflow: hidden;
            margin: 30px 0;
            background: rgba(10, 0, 34, 0.7);
        }}
        @media (max-width: 768px) {{
            h1 {{ font-size: 2rem; }}
            .container {{ padding: 15px; }}
            .price-display {{ font-size: 2.5rem; }}
            .chart-container {{ height: 400px; }}
        }}
    </style>
</head>
<body>
"""

HTML_FOOTER = """
</body>
</html>
"""

# ==================== HELPER FUNCTIONS ====================
def get_visitor_stats_html() -> str:
    stats = visitor_counter.get_stats()
    return f"""
    <div class="stats">
        <div>👁️ Toplam: <strong>{stats['total_visits']}</strong></div>
        <div>🔥 Bugün: <strong>{stats['today_visits']}</strong></div>
        <div>👥 Aktif: <strong>{stats['active_users']}</strong></div>
    </div>
    """

# ==================== ROUTES ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email", "Misafir")
    stats_html = get_visitor_stats_html()
    
    content = HTML_HEADER.format(title="Ana Sayfa") + f"""
    {stats_html}
    <div class="user-info">👤 {user}</div>
    <div class="container">
        <h1>🚀 ICT SMART PRO</h1>
        
        <div class="card">
            <h2>🔥 Pump Radar</h2>
            <div id="pump-radar">
                <p style="text-align: center; color: #888;">Pump radar verileri yükleniyor...</p>
            </div>
        </div>
        
        <div class="card" style="text-align: center;">
            <h2>⚡ Hızlı Erişim</h2>
            <div style="display: flex; flex-wrap: wrap; justify-content: center; gap: 15px; margin: 30px 0;">
                <a href="/signal" class="btn">📈 Tek Coin Sinyal</a>
                <a href="/signal/all" class="btn">🔥 Tüm Coinler</a>
                <a href="/admin/visitor-dashboard" class="btn">📊 İstatistikler</a>
            </div>
        </div>
        
        <div class="card">
            <h3>📊 Realtime Fiyatlar</h3>
            <div id="realtime-prices" style="max-height: 300px; overflow-y: auto;">
                <p style="text-align: center;">Fiyat verileri yükleniyor...</p>
            </div>
        </div>
    </div>
    
    <script>
    // Pump Radar WebSocket
    const pumpWs = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/pump_radar');
    pumpWs.onmessage = e => {{
        try {{
            const data = JSON.parse(e.data);
            if (data.ping) return;
            
            if (data.top_gainers?.length > 0) {{
                let html = '<table style="width:100%;border-collapse:collapse;">';
                data.top_gainers.forEach((coin, i) => {{
                    const changeClass = coin.change > 0 ? 'signal-buy' : 'signal-sell';
                    html += `
                    <tr class="${{changeClass}}" style="border-bottom:1px solid rgba(255,255,255,0.1);">
                        <td style="padding:12px;">#${{i+1}} <strong>${{coin.symbol}}</strong></td>
                        <td style="padding:12px;">$${{coin.price?.toFixed(4)}}</td>
                        <td style="padding:12px;">${{coin.change > 0 ? '↗ +' : '↘ '}}${{Math.abs(coin.change).toFixed(2)}}%</td>
                    </tr>
                    `;
                }});
                html += '</table>';
                document.getElementById('pump-radar').innerHTML = html;
            }}
        }} catch (err) {{ console.error(err); }}
    }};
    
    // Realtime Prices
    const priceWs = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/realtime_price');
    priceWs.onmessage = e => {{
        try {{
            const data = JSON.parse(e.data);
            const tickers = data.tickers || {{}};
            
            let html = '<table style="width:100%;border-collapse:collapse;">';
            Object.entries(tickers).slice(0, 10).forEach(([symbol, info]) => {{
                const changeClass = info.change > 0 ? 'signal-buy' : info.change < 0 ? 'signal-sell' : '';
                html += `
                <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
                    <td style="padding:10px;"><strong>${{symbol.replace('USDT', '')}}</strong></td>
                    <td style="padding:10px;">$${{info.price?.toFixed(4)}}</td>
                    <td style="padding:10px;" class="${{changeClass}}">${{info.change > 0 ? '+' : ''}}${{info.change?.toFixed(2)}}%</td>
                </tr>
                `;
            }});
            html += '</table>';
            document.getElementById('realtime-prices').innerHTML = html;
        }} catch (err) {{ console.error(err); }}
    }};
    
    // Auto reconnect
    function setupReconnect(ws, type) {{
        ws.onclose = () => setTimeout(() => {{
            if (type === 'pump') location.reload();
        }}, 5000);
    }}
    
    setupReconnect(pumpWs, 'pump');
    setupReconnect(priceWs, 'price');
    </script>
    """ + HTML_FOOTER
    
    return HTMLResponse(content=content)

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
<title>📈 {user.split('@')[0]} | CANLI SİNYAL + GRAFİK</title>
<style>
:root {{
  --primary: #00dbde;
  --secondary: #fc00ff;
  --success: #00ff88;
  --danger: #ff4444;
  --dark: #0a0022;
}}
body {{
  background: linear-gradient(135deg, var(--dark), #110033, #000);
  color: #e0e0ff;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  margin: 0;
  padding: 0;
  min-height: 100vh;
  overflow-x: hidden;
}}
.header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: rgba(0,0,0,0.6);
  backdrop-filter: blur(8px);
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  border-bottom: 1px solid rgba(100,100,255,0.2);
}}
.user-info {{ color: var(--success); font-weight: bold; font-size: 1rem; }}
.controls {{
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
  padding: 75px 15px 15px;
  max-width: 1000px;
  margin: 0 auto;
}}
.controls input,
.controls select {{
  padding: 12px 16px;
  font-size: 1rem;
  border: none;
  border-radius: 12px;
  background: rgba(40,40,60,0.7);
  color: #fff;
  min-width: 160px;
}}
.controls button {{
  padding: 12px 20px;
  font-size: 1rem;
  font-weight: bold;
  border: none;
  border-radius: 12px;
  cursor: pointer;
  background: linear-gradient(45deg, var(--secondary), var(--primary));
  color: white;
  transition: all 0.2s;
  min-width: 180px;
}}
.controls button:hover {{
  transform: scale(1.03);
  box-shadow: 0 0 15px rgba(252,0,255,0.5);
}}

/* === TIMEFRAME: YATAY, KISA, TEMİZ === */
.timeframe-list {{
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: center;
  margin: 12px 0;
}}
.tf-item {{
  padding: 8px 14px;
  font-size: 0.9rem;
  background: rgba(40,40,60,0.7);
  color: #ccc;
  border: 1px solid rgba(100,100,255,0.3);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}}
.tf-item:hover {{ background: rgba(60,60,100,0.8); color: #fff; }}
.tf-item.active {{
  background: linear-gradient(90deg, #00dbde, #fc00ff);
  color: white;
  border: none;
  font-weight: bold;
  box-shadow: 0 2px 8px rgba(0,219,222,0.4);
}}

.status-bar {{
  text-align: center;
  padding: 12px;
  font-size: 1rem;
  color: var(--primary);
  background: rgba(0,0,0,0.4);
  margin: 10px 0;
}}
#price-text {{
  font-size: 2.2rem;
  font-weight: bold;
  text-align: center;
  margin: 8px 0;
  background: linear-gradient(90deg, #00dbde, #fc00ff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}}
.signal-row {{
  display: flex;
  gap: 15px;
  flex-wrap: wrap;
  justify-content: center;
  padding: 0 15px;
  max-width: 1000px;
  margin: 0 auto 15px;
}}
.signal-box {{
  flex: 1;
  min-width: 250px;
  background: rgba(20,10,50,0.6);
  border-radius: 15px;
  padding: 15px;
  text-align: center;
  font-size: 1rem;
  transition: all 0.3s;
}}
#signal-card.green {{ border-left: 4px solid var(--success); }}
#signal-card.red {{ border-left: 4px solid var(--danger); }}
#signal-card.neutral {{ border-left: 4px solid #ffd700; }}

/* === GRAFİK ÖN PLANDA === */
.chart-container {{
  width: 100%;
  height: calc(65vh - 100px); /* Mobilde bile baskın */
  max-height: 700px;
  margin: 0 auto 20px;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 10px 30px rgba(0,219,222,0.2);
  background: #08001a;
}}
#tradingview_widget {{
  height: 100%;
  width: 100%;
}}

/* Gizli AI kutusu */
#ai-box {{
  display: none;
  margin: 25px auto 0;
  padding: 20px;
  background: rgba(15,5,50,0.7);
  border-radius: 16px;
  max-width: 900px;
  border: 1px solid var(--primary);
}}
#ai-comment {{
  line-height: 1.7;
  color: #ddd;
  font-size: 1.1rem;
}}
.nav {{
  text-align: center;
  padding: 15px;
}}
.nav a {{
  color: var(--primary);
  text-decoration: none;
  margin: 0 12px;
  font-weight: bold;
}}
.nav a:hover {{ text-decoration: underline; }}

{visitor_stats_html}
</style>
</head>
<body>

<div class="header">
  <div class="user-info">👤 {user.split('@')[0]}</div>
  <div style="font-size:0.9rem;color:#888;">ICT SMART PRO</div>
</div>

<div class="controls">
  <input id="pair" placeholder="Coin (BTCUSDT)" value="BTCUSDT">
  
  <div class="timeframe-list">
    <button class="tf-item" data-tf="1m">1m</button>
    <button class="tf-item" data-tf="3m">3m</button>
    <button class="tf-item active" data-tf="5m">5m</button>
    <button class="tf-item" data-tf="15m">15m</button>
    <button class="tf-item" data-tf="1h">1h</button>
    <button class="tf-item" data-tf="4h">4h</button>
    <button class="tf-item" data-tf="1d">1D</button>
  </div>

  <button onclick="connect()">📡 BAĞLAN</button>
  <button id="analyze-btn" onclick="toggleAIBox()">🤖 AI ANALİZ</button>
</div>

<div class="status-bar" id="status">🎯 Coin girin ve bağlantı kurun</div>

<div id="price-text">$0.00</div>

<div class="signal-row">
  <div class="signal-box">
    <div id="signal-text">⏳ Bekleniyor</div>
    <div id="signal-details" style="font-size:0.9rem;color:#aaa;margin-top:8px;">Bağlantı kurulunca sinyal gelir</div>
  </div>
  <div class="signal-box">
    <div>Skor:</div>
    <div id="signal-score">— /100</div>
    <div id="signal-killzone" style="margin-top:6px;font-size:0.9rem;color:#888;">—</div>
  </div>
</div>

<div class="chart-container">
  <div id="tradingview_widget"></div>
</div>

<div id="ai-box">
  <h3 style="text-align:center;color:var(--primary);margin:0 0 15px;">🤖 GPT-4o Teknik Analizi</h3>
  <div id="ai-comment">AI analizi görmek için yukarıdaki butona basın.</div>
</div>

<div class="nav">
  <a href="/">🏠 Ana Sayfa</a>
  <a href="/signal/all">🔥 Tüm Coinler</a>
  <a href="/admin/visitor-dashboard">📊 İstatistikler</a>
</div>

<script src="https://s3.tradingview.com/tv.js"></script>
<script>
let ws = null, priceWs = null, tvWidget = null, currentPrice = null, isConnected = false;
const tfMap = {{"1m":"1","3m":"3","5m":"5","15m":"15","1h":"60","4h":"240","1d":"D"}};

function getSymbol() {{
  let p = document.getElementById('pair').value.trim().toUpperCase();
  p = p.endsWith("USDT") ? p : p + "USDT";
  document.getElementById('pair').value = p;
  return "BINANCE:" + p;
}}

function createWidget() {{
  const symbol = getSymbol();
  const tf = document.querySelector('.tf-item.active').dataset.tf || "5m";
  const iv = tfMap[tf] || "5";

  if (tvWidget) {{ tvWidget.remove(); tvWidget = null; }}

  tvWidget = new TradingView.widget({{
    autosize: true,
    symbol: symbol,
    interval: iv,
    timezone: "Etc/UTC",
    theme: "dark",
    style: "1",
    locale: "tr",
    toolbar_bg: "#0a0022",
    enable_publishing: false,
    container_id: "tradingview_widget",
    studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies", "Volume@tv-basicstudies"]
  }});
}}

function updatePriceDisplay(price) {{
  if (!price || isNaN(price)) return;
  const fmt = price >= 1 ? price.toFixed(4) : price >= 0.01 ? price.toFixed(6) : price.toFixed(8);
  document.getElementById('price-text').textContent = "$" + fmt;
}}

document.querySelectorAll('.tf-item').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.tf-item').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    createWidget();
    if (isConnected) {{ ws?.close(); connect(); }}
  }});
}});

function connect() {{
  if (isConnected) return alert("Zaten bağlısınız!");
  const symbol = getSymbol().replace("BINANCE:", "");
  const tf = document.querySelector('.tf-item.active').dataset.tf;
  document.getElementById("status").innerHTML = `🔗 ${symbol} ${tf} bağlantısı kuruluyor...`;
  
  createWidget();
  
  const url = (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + `/ws/signal/${{symbol}}/${{tf}}`;
  ws = new WebSocket(url);
  
  ws.onopen = () => {{
    isConnected = true;
    document.getElementById("status").innerHTML = `✅ ${symbol} ${tf} aktif`;
  }};
  
  ws.onmessage = e => {{
    try {{
      const data = JSON.parse(e.data);
      if (data.heartbeat) return;
      updateSignalDisplay(data, symbol.replace("USDT", ""));
    }} catch (err) {{}}
  }};
  
  ws.onclose = () => {{
    if (isConnected) {{
      document.getElementById("status").innerHTML = "🔌 Bağlantı kesildi";
    }}
    isConnected = false;
  }};
}}

function updateSignalDisplay(data, base) {{
  const txt = document.getElementById("signal-text");
  const details = document.getElementById("signal-details");
  const scoreEl = document.getElementById("signal-score");
  const killzoneEl = document.getElementById("signal-killzone");
  
  txt.textContent = data.signal || "NÖTR";
  scoreEl.textContent = (data.score || 50) + " /100";
  killzoneEl.textContent = "⚡ " + (data.killzone || "Normal");
  
  details.innerHTML = `<strong>${{base}}/USDT</strong><br>
  💰 $${{(data.current_price || currentPrice || 0).toFixed(4)}}<br>
  🕒 ${{data.last_update || "şimdi"}}`;
  
  // Sinyal rengi
  const card = document.querySelector('.signal-box');
  card.className = 'signal-box';
  if (data.signal?.includes('ALIM')) card.style.borderLeft = '4px solid #00ff88';
  else if (data.signal?.includes('SATIM')) card.style.borderLeft = '4px solid #ff4444';
  else card.style.borderLeft = '4px solid #ffd700';
  
  if (data.current_price) {{
    currentPrice = data.current_price;
    updatePriceDisplay(currentPrice);
  }}
}}

function toggleAIBox() {{
  const box = document.getElementById('ai-box');
  if (box.style.display === 'none' || box.style.display === '') {{
    analyzeChartWithAI();
    box.style.display = 'block';
  }} else {{
    box.style.display = 'none';
  }}
}}

async function analyzeChartWithAI() {{
  const btn = document.getElementById("analyze-btn");
  const comment = document.getElementById("ai-comment");
  btn.disabled = true;
  comment.innerHTML = "🧠 AI analiz ediyor...";
  
  try {{
    const symbol = getSymbol().replace("BINANCE:", "");
    const tf = document.querySelector(".tf-item.active").dataset.tf;
    const res = await fetch("/api/analyze-chart", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ symbol, timeframe: tf }})
    }});
    const r = await res.json();
    comment.innerHTML = r.analysis?.replace(/\
/g, '<br>') || "❌ Analiz alınamadı.";
  }} catch (e) {{
    comment.innerHTML = "⚠️ Bağlantı hatası.";
  }} finally {{
    btn.disabled = false;
  }}
}}

// Realtime fiyat
function connectRealtimePrice() {{
  const url = (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + "/ws/realtime_price";
  priceWs = new WebSocket(url);
  priceWs.onmessage = e => {{
    try {{
      const d = JSON.parse(e.data);
      const pair = getSymbol().replace("BINANCE:", "");
      const p = d.tickers?.[pair]?.price;
      if (p > 0) {{ currentPrice = p; updatePriceDisplay(p); }}
    }} catch (err) {{}}
  }};
  priceWs.onclose = () => setTimeout(connectRealtimePrice, 3000);
}}

document.addEventListener("DOMContentLoaded", () => {{
  createWidget();
  connectRealtimePrice();
}});
</script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

@app.get("/signal/all", response_class=HTMLResponse)
async def signal_all_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    stats_html = get_visitor_stats_html()
    
    content = HTML_HEADER.format(title="Tüm Coinler") + f"""
    {stats_html}
    <div class="user-info">👤 {user}</div>
    
    <div class="container">
        <h1>🔥 TÜM COİNLER - CANLI SİNYALLER</h1>
        
        <div class="card">
            <div style="display: flex; justify-content: center; gap: 15px; margin: 20px 0;">
                <button onclick="changeTimeframe('5m')" class="timeframe-btn active" id="tf-5m">5m</button>
                <button onclick="changeTimeframe('15m')" class="timeframe-btn" id="tf-15m">15m</button>
                <button onclick="changeTimeframe('1h')" class="timeframe-btn" id="tf-1h">1h</button>
                <button onclick="changeTimeframe('4h')" class="timeframe-btn" id="tf-4h">4h</button>
            </div>
            
            <div id="connection-status" style="text-align: center; padding: 15px; border-radius: 10px; background: rgba(0, 0, 0, 0.3); margin: 20px 0;">
                Bağlantı bekleniyor...
            </div>
            
            <div id="signals-container" style="max-height: 60vh; overflow-y: auto;">
                <p style="text-align: center; color: #888; padding: 40px;">
                    Sinyal akışı başladığında burada görünecek...
                </p>
            </div>
        </div>
        
        <div style="text-align: center; margin: 40px 0;">
            <a href="/" class="btn">🏠 Ana Sayfa</a>
            <a href="/signal" class="btn">📈 Tek Coin</a>
        </div>
    </div>
    
    <script>
    let allWs = null;
    let currentTimeframe = '5m';
    
    function changeTimeframe(tf) {{
        // Update active button
        document.querySelectorAll('.timeframe-btn').forEach(btn => {{
            btn.classList.remove('active');
        }});
        document.getElementById(`tf-${{tf}}`).classList.add('active');
        
        currentTimeframe = tf;
        connectAllSignals();
    }}
    
    function connectAllSignals() {{
        // Close existing connection
        if (allWs) {{
            allWs.close();
        }}
        
        const status = document.getElementById('connection-status');
        status.innerHTML = `🔄 ${{currentTimeframe.toUpperCase()}} zaman dilimi için bağlanıyor...`;
        status.style.color = '#00ffff';
        
        const wsUrl = (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + `/ws/all/${{currentTimeframe}}`;
        allWs = new WebSocket(wsUrl);
        
        allWs.onopen = () => {{
            status.innerHTML = `✅ ${{currentTimeframe.toUpperCase()}} sinyalleri akıyor...`;
            status.style.color = '#00ff88';
        }};
        
        allWs.onmessage = (e) => {{
            try {{
                const signals = JSON.parse(e.data);
                updateAllSignalsDisplay(signals);
            }} catch (err) {{
                console.error('All signals error:', err);
            }}
        }};
        
        allWs.onclose = () => {{
            status.innerHTML = "🔌 Bağlantı kesildi. Yeniden bağlanıyor...";
            status.style.color = '#ff4444';
            setTimeout(connectAllSignals, 3000);
        }};
    }}
    
    function updateAllSignalsDisplay(signals) {{
        const container = document.getElementById('signals-container');
        
        if (!Array.isArray(signals) || signals.length === 0) {{
            container.innerHTML = `
                <p style="text-align: center; color: #888; padding: 40px;">
                    😴 ${{currentTimeframe.toUpperCase()}} zaman diliminde aktif sinyal yok
                </p>
            `;
            return;
        }}
        
        let html = '<div style="display: grid; gap: 15px;">';
        
        signals.slice(0, 20).forEach(signal => {{
            if (!signal || !signal.symbol) return;
            
            const symbol = signal.symbol.replace('USDT', '');
            const price = signal.current_price || 0;
            const score = signal.score || 50;
            const signalText = signal.signal || 'NÖTR';
            const strength = signal.strength || 'ORTA';
            
            let signalClass = 'signal-neutral';
            if (signalText.includes('ALIM') || signalText.includes('BUY')) {{
                signalClass = 'signal-buy';
            }} else if (signalText.includes('SATIM') || signalText.includes('SELL')) {{
                signalClass = 'signal-sell';
            }}
            
            html += `
            <div class="card ${{signalClass}}" style="padding: 20px;">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                    <div>
                        <div style="font-size: 1.3rem; font-weight: bold;">${{symbol}}/USDT</div>
                        <div style="color: #888; font-size: 0.9rem;">${{signalText}} • ${{strength}}</div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-size: 1.5rem; font-weight: bold;">$${{price.toFixed(4)}}</div>
                        <div style="font-size: 1.2rem;">Skor: <strong>${{score}}/100</strong></div>
                    </div>
                </div>
            </div>
            `;
        }});
        
        html += '</div>';
        container.innerHTML = html;
    }}
    
    // Initialize
    document.addEventListener('DOMContentLoaded', () => {{
        connectAllSignals();
    }});
    </script>
    """ + HTML_FOOTER
    
    return HTMLResponse(content=content)

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    content = HTML_HEADER.format(title="Giriş") + """
    <div class="container" style="display: flex; justify-content: center; align-items: center; min-height: 80vh;">
        <div class="card" style="max-width: 400px; width: 100%;">
            <h2 style="text-align: center; margin-bottom: 30px;">🔐 Giriş Yap</h2>
            
            <form method="post" action="/login">
                <div class="form-group">
                    <label>E-posta Adresi:</label>
                    <input type="email" name="email" class="form-control" placeholder="ornek@email.com" required>
                </div>
                
                <div style="text-align: center; margin-top: 30px;">
                    <button type="submit" class="btn" style="width: 100%; padding: 16px;">
                        🚀 Giriş Yap
                    </button>
                </div>
            </form>
            
            <div style="text-align: center; margin-top: 20px; color: #888; font-size: 0.9rem;">
                Herhangi bir e-posta ile giriş yapabilirsiniz
            </div>
        </div>
    </div>
    """ + HTML_FOOTER
    
    return HTMLResponse(content=content)

@app.post("/login")
async def login_post(email: str = Form(...)):
    if "@" in email:
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("user_email", email.strip().lower(), max_age=2592000, httponly=True, samesite="lax")
        return response
    return RedirectResponse("/login")

@app.get("/admin/visitor-dashboard", response_class=HTMLResponse)
async def visitor_dashboard(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    stats = visitor_counter.get_stats()
    
    # Create page views table
    page_rows = ""
    for page, views in sorted(stats["page_views"].items(), key=lambda x: x[1], reverse=True):
        page_rows += f"<tr><td>{page}</td><td>{views}</td></tr>"
    
    content = HTML_HEADER.format(title="İstatistikler") + f"""
    <div class="user-info">👤 {user}</div>
    
    <div class="container">
        <h1>📊 ZİYARETÇİ İSTATİSTİKLERİ</h1>
        
        <div class="card">
            <h3>📈 GENEL İSTATİSTİKLER</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 30px 0;">
                <div style="text-align: center; padding: 20px; background: rgba(0, 219, 222, 0.1); border-radius: 10px;">
                    <div style="font-size: 2.5rem; font-weight: bold;">{stats['total_visits']}</div>
                    <div style="color: #888;">Toplam Ziyaret</div>
                </div>
                <div style="text-align: center; padding: 20px; background: rgba(252, 0, 255, 0.1); border-radius: 10px;">
                    <div style="font-size: 2.5rem; font-weight: bold;">{stats['active_users']}</div>
                    <div style="color: #888;">Aktif Kullanıcı</div>
                </div>
                <div style="text-align: center; padding: 20px; background: rgba(0, 255, 136, 0.1); border-radius: 10px;">
                    <div style="font-size: 2.5rem; font-weight: bold;">{stats['today_visits']}</div>
                    <div style="color: #888;">Bugünkü Ziyaret</div>
                </div>
                <div style="text-align: center; padding: 20px; background: rgba(255, 68, 68, 0.1); border-radius: 10px;">
                    <div style="font-size: 2.5rem; font-weight: bold;">{stats['today_unique']}</div>
                    <div style="color: #888;">Bugünkü Benzersiz</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h3>📄 SAYFA GÖRÜNTÜLEMELERİ</h3>
            <div style="max-height: 400px; overflow-y: auto; margin: 20px 0;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background: rgba(255, 255, 255, 0.1);">
                            <th style="padding: 12px; text-align: left;">Sayfa</th>
                            <th style="padding: 12px; text-align: left;">Görüntülenme</th>
                        </tr>
                    </thead>
                    <tbody>
                        {page_rows if page_rows else '<tr><td colspan="2" style="text-align: center; padding: 40px; color: #888;">Veri yok</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
        
        <div style="text-align: center; margin: 40px 0;">
            <a href="/" class="btn">🏠 Ana Sayfa</a>
            <button onclick="location.reload()" class="btn">🔄 Yenile</button>
            <small style="display: block; margin-top: 20px; color: #888;">
                Son güncelleme: {stats['last_updated']}
            </small>
        </div>
    </div>
    """ + HTML_FOOTER
    
    return HTMLResponse(content=content)

@app.get("/health")
async def health_check():
    return JSONResponse({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "visitors": visitor_counter.get_stats()["total_visits"],
        "active_websockets": {
            "single": sum(len(s) for s in single_subscribers.values()),
            "all": sum(len(s) for s in all_subscribers.values()),
            "pump": len(pump_radar_subscribers),
            "realtime": len(realtime_subscribers)
        },
        "queue_size": signal_queue.qsize() if 'signal_queue' in globals() else 0
    })

# ==================== BAŞLATMA ====================
if __name__ == "__main__":
    import uvicorn
    import os
    
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

