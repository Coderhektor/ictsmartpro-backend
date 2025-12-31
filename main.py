# main.py — TAMAMEN YENİDEN YAZILDI, HATALAR DÜZELTİLDİ, RAILWAY UYUMLU
import logging
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict, Set
import json
import hashlib
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from core import (
    initialize, cleanup, single_subscribers, all_subscribers,
    pump_radar_subscribers, shared_signals, active_strong_signals,
    top_gainers, last_update, rt_ticker, get_all_prices_snapshot
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("main")

# ==================== ZİYARETÇİ SAYACI ====================
class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users: Set[str] = set()
        self.daily_stats: Dict[str, Dict] = {}
        self.page_views: Dict[str, int] = {}

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
            "page_views": dict(self.page_views),
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

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="4.1")

# ==================== MIDDLEWARE ====================
@app.middleware("http")
async def count_visitors(request: Request, call_next):
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        ip = request.client.host or "unknown"
        visitor_id = hashlib.md5(ip.encode()).hexdigest()[:8]

    page = request.url.path
    visitor_counter.add_visit(page, visitor_id)

    response = await call_next(request)
    if not request.cookies.get("visitor_id"):
        response.set_cookie("visitor_id", visitor_id, max_age=86400*30, httponly=True, samesite="lax")
    return response

# ==================== WEBSOCKETS ====================
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
    logger.info(f"📡 Tekil abone: {channel}")

    # Mevcut sinyali gönder
    sig = shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        try:
            await websocket.send_json(sig)
        except:
            pass

    try:
        while True:
            await asyncio.sleep(15)
            await websocket.send_json({"heartbeat": True, "time": datetime.now().strftime("%H:%M:%S")})
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

    # İlk veri
    signals = active_strong_signals.get(timeframe, [])[:10]
    try:
        await websocket.send_json(signals)
    except:
        pass

    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"ping": True})
    except WebSocketDisconnect:
        pass
    finally:
        if timeframe in all_subscribers:
            all_subscribers[timeframe].discard(websocket)


@app.websocket("/ws/pump_radar")
async def ws_pump_radar(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)

    try:
        await websocket.send_json({"top_gainers": top_gainers[:5], "last_update": last_update})
    except:
        pass

    try:
        while True:
            await asyncio.sleep(20)
            await websocket.send_json({"ping": True})
    except WebSocketDisconnect:
        pass
    finally:
        pump_radar_subscribers.discard(websocket)


@app.websocket("/ws/realtime_price")
async def ws_realtime_price(websocket: WebSocket):
    await websocket.accept()
    await rt_ticker.subscribe(websocket)
    logger.info("📡 Realtime fiyat abonesi eklendi")

    try:
        while True:
            await asyncio.sleep(3)
            data = get_all_prices_snapshot(limit=50)
            await rt_ticker.broadcast(data)
    except WebSocketDisconnect:
        pass
    finally:
        await rt_ticker.unsubscribe(websocket)

# ==================== HTML BILEŞENLERI ====================
def get_stats_html() -> str:
    stats = visitor_counter.get_stats()
    return f"""
    <div class="stats">
        <div>👁️ Toplam: <strong>{stats['total_visits']}</strong></div>
        <div>🔥 Bugün: <strong>{stats['today_visits']}</strong></div>
        <div>👥 Aktif: <strong>{stats['active_users']}</strong></div>
    </div>"""

# ==================== ROUTES ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email", "Misafir").split("@")[0]
    
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Ana Sayfa | ICT SMART PRO</title>
    <style>
        :root {{
            --primary: #00dbde;
            --secondary: #fc00ff;
            --success: #00ff88;
            --danger: #ff4444;
            --bg: #0a0022;
        }}
        body {{
            margin: 0;
            padding: 0;
            background: linear-gradient(135deg, var(--bg), #110033, #000);
            color: #e0e0ff;
            font-family: system-ui, sans-serif;
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
            margin: 20px 0;
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
            padding: 14px 28px;
            background: linear-gradient(45deg, var(--secondary), var(--primary));
            color: white;
            border: none;
            border-radius: 12px;
            font-weight: bold;
            cursor: pointer;
            display: inline-block;
            margin: 10px;
            text-decoration: none;
        }}
        .btn:hover {{
            transform: translateY(-3px);
            box-shadow: 0 10px 25px rgba(252, 0, 255, 0.3);
        }}
        .stats, .user-info {{
            position: fixed;
            padding: 12px 20px;
            background: rgba(0, 0, 0, 0.7);
            border-radius: 15px;
            z-index: 1000;
            font-size: 0.9rem;
        }}
        .stats {{
            top: 15px;
            right: 15px;
            color: var(--success);
        }}
        .user-info {{
            top: 15px;
            left: 15px;
            color: var(--primary);
        }}
        .signal-buy {{
            border-left: 4px solid var(--success);
            color: var(--success);
        }}
        .signal-sell {{
            border-left: 4px solid var(--danger);
            color: var(--danger);
        }}
        .signal-neutral {{
            border-left: 4px solid #ffd700;
            color: #ffd700;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        td {{
            padding: 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}
        @media (max-width: 768px) {{
            h1 {{
                font-size: 2rem;
            }}
            .container {{
                padding: 15px;
            }}
        }}
    </style>
</head>
<body>
    {get_stats_html()}
    <div class="user-info">👤 {user}</div>
    <div class="container">
        <h1>🚀 ICT SMART PRO</h1>
        <div class="card">
            <h2>🔥 Pump Radar</h2>
            <div id="pump-radar">Yükleniyor...</div>
        </div>
        <div class="card" style="text-align: center;">
            <h2>⚡ Hızlı Erişim</h2>
            <a href="/signal" class="btn">📈 Tek Coin Sinyal</a>
            <a href="/signal/all" class="btn">🔥 Tüm Coinler</a>
            <a href="/admin/visitor-dashboard" class="btn">📊 İstatistikler</a>
        </div>
        <div class="card">
            <h3>📊 Realtime Fiyatlar</h3>
            <div id="realtime-prices">Yükleniyor...</div>
        </div>
    </div>
    <script>
        const pumpWs = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/pump_radar');
        pumpWs.onmessage = e => {{
            try {{
                const d = JSON.parse(e.data);
                if (d.top_gainers) {{
                    let html = '<table>';
                    d.top_gainers.forEach((c, i) => {{
                        const cls = c.change > 0 ? 'signal-buy' : 'signal-sell';
                        html += `<tr class="${{cls}}"><td>#${{i+1}} <strong>${{c.symbol}}</strong></td><td>$$${{c.price?.toFixed(4)}}</td><td>${{c.change > 0 ? '↗ +' : '↘ '}}${{Math.abs(c.change).toFixed(2)}}%</td></tr>`;
                    }});
                    html += '</table>';
                    document.getElementById('pump-radar').innerHTML = html;
                }}
            }} catch (err) {{
                console.error(err);
            }}
        }};

        const priceWs = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/realtime_price');
        priceWs.onmessage = e => {{
            try {{
                const d = JSON.parse(e.data);
                let html = '<table>';
                Object.entries(d.tickers || {{}}).slice(0, 10).forEach(([s, i]) => {{
                    const cls = i.change > 0 ? 'signal-buy' : i.change < 0 ? 'signal-sell' : '';
                    html += `<tr><td><strong>${{s.replace('USDT', '')}}</strong></td><td>$$${{i.price?.toFixed(4)}}</td><td class="${{cls}}">${{i.change > 0 ? '+' : ''}}${{i.change?.toFixed(2)}}%</td></tr>`;
                }});
                html += '</table>';
                document.getElementById('realtime-prices').innerHTML = html;
            }} catch (err) {{
                console.error(err);
            }}
        }};

        // Auto reconnect
        pumpWs.onclose = () => setTimeout(() => location.reload(), 5000);
        priceWs.onclose = () => setTimeout(() => location.reload(), 5000);
    </script>
</body>
</html>"""
    
    return HTMLResponse(content=html_content)


@app.get("/signal", response_class=HTMLResponse)
async def signal_page(request: Request):
    user_email = request.cookies.get("user_email")
    if not user_email:
        return RedirectResponse("/login")
    
    username = user_email.split("@")[0]
    stats_html = get_stats_html()
    
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>📈 {username} | CANLI SİNYAL</title>
    <style>
        :root {{
            --p: #00dbde;
            --s: #fc00ff;
            --g: #00ff88;
            --r: #ff4444;
            --d: #0a0022;
        }}
        body {{
            background: linear-gradient(135deg, var(--d), #110033, #000);
            color: #e0e0ff;
            margin: 0;
            font-family: system-ui, sans-serif;
        }}
        .header {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            padding: 12px 20px;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(8px);
            z-index: 100;
            display: flex;
            justify-content: space-between;
            border-bottom: 1px solid rgba(100, 100, 255, 0.2);
        }}
        .controls {{
            padding: 70px 15px 15px;
            max-width: 1000px;
            margin: 0 auto;
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            justify-content: center;
        }}
        .controls input {{
            padding: 12px 16px;
            border-radius: 12px;
            background: rgba(40, 40, 60, 0.7);
            color: #fff;
            border: none;
            flex: 1;
            min-width: 160px;
        }}
        .tf-list {{
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
            justify-content: center;
            margin: 12px 0;
        }}
        .tf-item {{
            padding: 8px 14px;
            background: rgba(40, 40, 60, 0.7);
            color: #ccc;
            border: 1px solid rgba(100, 100, 255, 0.3);
            border-radius: 8px;
            cursor: pointer;
        }}
        .tf-item.active {{
            background: linear-gradient(90deg, var(--p), var(--s));
            color: white;
            font-weight: bold;
        }}
        button {{
            padding: 12px 20px;
            background: linear-gradient(45deg, var(--s), var(--p));
            color: white;
            border: none;
            border-radius: 12px;
            font-weight: bold;
            cursor: pointer;
        }}
        #price-text {{
            font-size: 2.5rem;
            text-align: center;
            margin: 10px;
            background: linear-gradient(90deg, var(--p), var(--s));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-weight: bold;
        }}
        .chart-container {{
            width: 100%;
            height: calc(65vh - 100px);
            max-height: 700px;
            margin: 20px auto;
            border-radius: 16px;
            overflow: hidden;
            background: #08001a;
            box-shadow: 0 10px 30px rgba(0, 219, 222, 0.2);
        }}
        .signal-box {{
            background: rgba(20, 10, 50, 0.6);
            padding: 15px;
            border-radius: 15px;
            min-width: 250px;
            text-align: center;
            margin: 10px;
        }}
        .stats {{
            position: fixed;
            top: 15px;
            right: 15px;
            padding: 12px 20px;
            background: rgba(0, 0, 0, 0.7);
            border-radius: 15px;
            color: #00ff88;
            font-size: 0.9rem;
            z-index: 1000;
        }}
        @media (max-width: 768px) {{
            .chart-container {{
                height: 400px;
            }}
            #price-text {{
                font-size: 2rem;
            }}
        }}
    </style>
</head>
<body>
    {stats_html}
    <div class="header">
        <div>👤 {username}</div>
        <div>ICT SMART PRO</div>
    </div>
    
    <div class="controls">
        <input id="pair" value="BTCUSDT" placeholder="Coin (örn: ETHUSDT)">
        <div class="tf-list">
            <button class="tf-item" data-tf="1m">1m</button>
            <button class="tf-item" data-tf="3m">3m</button>
            <button class="tf-item active" data-tf="5m">5m</button>
            <button class="tf-item" data-tf="15m">15m</button>
            <button class="tf-item" data-tf="1h">1h</button>
            <button class="tf-item" data-tf="4h">4h</button>
            <button class="tf-item" data-tf="1d">1D</button>
        </div>
        <button onclick="connect()">📡 BAĞLAN</button>
    </div>
    
    <div style="text-align: center; padding: 10px; color: var(--p);" id="status">Coin seçip bağlanın</div>
    <div id="price-text">$0.00</div>
    
    <div style="display: flex; justify-content: center; gap: 20px; flex-wrap: wrap; padding: 0 15px;">
        <div class="signal-box" id="signal-box">
            <div id="signal-text">⏳ Bekleniyor</div>
            <div id="signal-details" style="font-size: 0.9rem; color: #aaa; margin-top: 8px;">
                Bağlantı kurulunca sinyal gelir
            </div>
        </div>
        <div class="signal-box">
            <div>Skor:</div>
            <div id="signal-score">— /100</div>
        </div>
    </div>
    
    <div class="chart-container">
        <div id="tradingview_widget"></div>
    </div>
    
    <div style="text-align: center; padding: 20px;">
        <a href="/" style="padding: 12px 24px; background: linear-gradient(45deg, var(--s), var(--p)); color: white; border-radius: 12px; text-decoration: none; margin: 10px;">🏠 Ana Sayfa</a>
        <a href="/signal/all" style="padding: 12px 24px; background: linear-gradient(45deg, var(--p), #ff00ff); color: white; border-radius: 12px; text-decoration: none; margin: 10px;">🔥 Tüm Coinler</a>
    </div>
    
    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>
        let ws = null;
        let tvWidget = null;
        let currentPrice = null;
        const tfMap = {{
            "1m": "1",
            "3m": "3", 
            "5m": "5",
            "15m": "15",
            "1h": "60",
            "4h": "240",
            "1d": "D"
        }};

        function getSymbol() {{
            let p = document.getElementById('pair').value.trim().toUpperCase();
            if (!p.endsWith("USDT")) p += "USDT";
            document.getElementById('pair').value = p;
            return "BINANCE:" + p;
        }}

        function createWidget() {{
            const symbol = getSymbol();
            const tf = document.querySelector('.tf-item.active').dataset.tf;
            const interval = tfMap[tf] || "5";
            
            if (tvWidget) {{
                tvWidget.remove();
            }}
            
            tvWidget = new TradingView.widget({{
                autosize: true,
                symbol: symbol,
                interval: interval,
                theme: "dark",
                timezone: "Etc/UTC",
                container_id: "tradingview_widget",
                locale: "tr",
                studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies"]
            }});
        }}

        document.querySelectorAll('.tf-item').forEach(btn => {{
            btn.addEventListener('click', () => {{
                document.querySelectorAll('.tf-item').forEach(x => x.classList.remove('active'));
                btn.classList.add('active');
                createWidget();
                if (ws) {{
                    ws.close();
                    connect();
                }}
            }});
        }});

        function connect() {{
            if (ws && ws.readyState === WebSocket.OPEN) {{
                alert("Zaten bağlısınız!");
                return;
            }}
            
            const symbol = getSymbol().replace("BINANCE:", "");
            const tf = document.querySelector('.tf-item.active').dataset.tf;
            document.getElementById("status").innerHTML = `🔗 ${{symbol}} ${{tf}} bağlanıyor...`;
            createWidget();

            const url = (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + `/ws/signal/${{symbol}}/${{tf}}`;
            ws = new WebSocket(url);

            ws.onopen = () => {{
                document.getElementById("status").innerHTML = `✅ ${{symbol}} ${{tf}} aktif`;
            }};

            ws.onmessage = e => {{
                try {{
                    const d = JSON.parse(e.data);
                    if (d.heartbeat) return;
                    
                    document.getElementById("signal-text").textContent = d.signal || "NÖTR";
                    document.getElementById("signal-score").textContent = (d.score || 50) + " /100";
                    document.getElementById("signal-details").innerHTML = `<strong>${{symbol.replace('USDT','')}}/USDT</strong><br>💰 $${{(d.current_price || 0).toFixed(4)}}`;
                    
                    if (d.current_price) {{
                        currentPrice = d.current_price;
                        const priceText = currentPrice >= 1 ? 
                            currentPrice.toFixed(4) : 
                            currentPrice.toFixed(6);
                        document.getElementById("price-text").textContent = "$" + priceText;
                    }}
                    
                    const signalBox = document.getElementById("signal-box");
                    if (d.signal && d.signal.includes("ALIM")) {{
                        signalBox.style.borderLeft = "4px solid #00ff88";
                    }} else if (d.signal && d.signal.includes("SATIM")) {{
                        signalBox.style.borderLeft = "4px solid #ff4444";
                    }} else {{
                        signalBox.style.borderLeft = "4px solid #ffd700";
                    }}
                }} catch (err) {{
                    console.error("WebSocket message error:", err);
                }}
            }};

            ws.onclose = () => {{
                document.getElementById("status").innerHTML = "🔌 Bağlantı kesildi";
            }};
        }}

        document.addEventListener("DOMContentLoaded", () => {{
            createWidget();
            // Auto connect after 2 seconds
            setTimeout(connect, 2000);
        }});
    </script>
</body>
</html>"""
    
    return HTMLResponse(content=html_content)


@app.get("/signal/all", response_class=HTMLResponse)
async def signal_all_page(request: Request):
    user_email = request.cookies.get("user_email")
    if not user_email:
        return RedirectResponse("/login")
    
    username = user_email.split("@")[0]
    stats_html = get_stats_html()
    
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tüm Coinler | ICT SMART PRO</title>
    <style>
        :root {{
            --p: #00dbde;
            --s: #fc00ff;
            --g: #00ff88;
            --r: #ff4444;
        }}
        body {{
            background: linear-gradient(135deg, #0a0022, #110033, #000);
            color: white;
            font-family: system-ui;
            margin: 0;
            padding: 20px;
        }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        h1 {{ text-align: center; background: linear-gradient(90deg, var(--p), var(--s)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .timeframe-btns {{ display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; margin: 20px 0; }}
        .timeframe-btn {{ padding: 10px 20px; background: rgba(40,40,60,0.7); border: 1px solid rgba(100,100,255,0.3); color: #ccc; border-radius: 8px; cursor: pointer; }}
        .timeframe-btn.active {{ background: linear-gradient(90deg, var(--p), var(--s)); color: white; font-weight: bold; }}
        #signals-container {{ max-height: 70vh; overflow-y: auto; }}
        .signal-card {{
            background: rgba(255,255,255,0.05);
            padding: 15px;
            margin: 10px 0;
            border-radius: 12px;
            border-left: 4px solid #888;
        }}
        .signal-card.buy {{ border-left-color: var(--g); }}
        .signal-card.sell {{ border-left-color: var(--r); }}
        {stats_html}
    </style>
</head>
<body>
    {stats_html}
    <div style="position: fixed; top: 15px; left: 15px; background: rgba(0,0,0,0.7); padding: 10px 20px; border-radius: 15px; color: var(--p);">
        👤 {username}
    </div>
    
    <div class="container">
        <h1>🔥 TÜM COİNLER - CANLI SİNYALLER</h1>
        
        <div class="timeframe-btns">
            <button class="timeframe-btn active" onclick="changeTimeframe('5m')">5m</button>
            <button class="timeframe-btn" onclick="changeTimeframe('15m')">15m</button>
            <button class="timeframe-btn" onclick="changeTimeframe('1h')">1h</button>
            <button class="timeframe-btn" onclick="changeTimeframe('4h')">4h</button>
        </div>
        
        <div id="status" style="text-align: center; padding: 15px; border-radius: 10px; background: rgba(0,0,0,0.3); margin: 20px 0;">
            Bağlantı bekleniyor...
        </div>
        
        <div id="signals-container">
            <p style="text-align: center; color: #888; padding: 40px;">
                Sinyal akışı başladığında burada görünecek...
            </p>
        </div>
        
        <div style="text-align: center; margin: 40px 0;">
            <a href="/" style="padding: 12px 24px; background: linear-gradient(45deg, var(--s), var(--p)); color: white; border-radius: 12px; text-decoration: none; margin: 10px;">🏠 Ana Sayfa</a>
            <a href="/signal" style="padding: 12px 24px; background: linear-gradient(45deg, var(--p), #ff00ff); color: white; border-radius: 12px; text-decoration: none; margin: 10px;">📈 Tek Coin</a>
        </div>
    </div>
    
    <script>
        let allWs = null;
        let currentTimeframe = '5m';
        
        function changeTimeframe(tf) {{
            document.querySelectorAll('.timeframe-btn').forEach(btn => {{
                btn.classList.remove('active');
            }});
            event.target.classList.add('active');
            
            currentTimeframe = tf;
            connectAllSignals();
        }}
        
        function connectAllSignals() {{
            if (allWs) {{
                allWs.close();
            }}
            
            document.getElementById('status').innerHTML = `🔄 ${{currentTimeframe.toUpperCase()}} için bağlanıyor...`;
            
            allWs = new WebSocket((location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + `/ws/all/${{currentTimeframe}}`);
            
            allWs.onopen = () => {{
                document.getElementById('status').innerHTML = `✅ ${{currentTimeframe.toUpperCase()}} sinyalleri akıyor...`;
            }};
            
            allWs.onmessage = e => {{
                try {{
                    const signals = JSON.parse(e.data);
                    updateSignals(signals);
                }} catch (err) {{
                    console.error(err);
                }}
            }};
            
            allWs.onclose = () => {{
                document.getElementById('status').innerHTML = "🔌 Bağlantı kesildi. Yeniden bağlanıyor...";
                setTimeout(connectAllSignals, 3000);
            }};
        }}
        
        function updateSignals(signals) {{
            const container = document.getElementById('signals-container');
            
            if (!signals || signals.length === 0) {{
                container.innerHTML = `<p style="text-align: center; color: #888; padding: 40px;">
                    😴 ${{currentTimeframe.toUpperCase()}} zaman diliminde aktif sinyal yok
                </p>`;
                return;
            }}
            
            let html = '';
            signals.forEach(signal => {{
                if (!signal) return;
                
                const symbol = signal.symbol?.replace('USDT', '') || 'N/A';
                const price = signal.current_price || 0;
                const score = signal.score || 50;
                const signalText = signal.signal || 'NÖTR';
                const strength = signal.strength || 'ORTA';
                
                let cardClass = 'signal-card';
                if (signalText.includes('ALIM') || signalText.includes('BUY')) {{
                    cardClass += ' buy';
                }} else if (signalText.includes('SATIM') || signalText.includes('SELL')) {{
                    cardClass += ' sell';
                }}
                
                html += `
                <div class="${{cardClass}}">
                    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                        <div>
                            <div style="font-size: 1.2rem; font-weight: bold;">${{symbol}}/USDT</div>
                            <div style="color: #888; font-size: 0.9rem;">${{signalText}} • ${{strength}}</div>
                        </div>
                        <div style="text-align: right;">
                            <div style="font-size: 1.3rem; font-weight: bold;">$${{price.toFixed(4)}}</div>
                            <div>Skor: <strong>${{score}}/100</strong></div>
                        </div>
                    </div>
                </div>`;
            }});
            
            container.innerHTML = html;
        }}
        
        // Initialize
        connectAllSignals();
    </script>
</body>
</html>"""
    
    return HTMLResponse(content=html_content)


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    html_content = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Giriş | ICT SMART PRO</title>
    <style>
        body {
            background: linear-gradient(135deg, #0a0022, #110033, #000);
            color: white;
            font-family: system-ui;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
        }
        .login-box {
            background: rgba(255,255,255,0.05);
            padding: 40px;
            border-radius: 20px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
            width: 100%;
            max-width: 400px;
            text-align: center;
        }
        h2 {
            background: linear-gradient(90deg, #00dbde, #fc00ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 30px;
        }
        input {
            width: 100%;
            padding: 15px;
            margin: 10px 0;
            border-radius: 12px;
            background: rgba(0,0,0,0.3);
            border: 1px solid rgba(255,255,255,0.2);
            color: white;
            font-size: 1rem;
        }
        button {
            width: 100%;
            padding: 15px;
            margin-top: 20px;
            background: linear-gradient(45deg, #fc00ff, #00dbde);
            color: white;
            border: none;
            border-radius: 12px;
            font-weight: bold;
            cursor: pointer;
            font-size: 1.1rem;
        }
        button:hover {
            transform: translateY(-3px);
            box-shadow: 0 10px 25px rgba(252,0,255,0.3);
        }
    </style>
</head>
<body>
    <div class="login-box">
        <h2>🔐 Giriş Yap</h2>
        <form method="post" action="/login">
            <input type="email" name="email" placeholder="E-posta adresiniz" required>
            <button type="submit">🚀 Giriş Yap</button>
        </form>
        <p style="color: #888; margin-top: 20px; font-size: 0.9rem;">
            Herhangi bir e-posta ile giriş yapabilirsiniz
        </p>
    </div>
</body>
</html>"""
    
    return HTMLResponse(content=html_content)


@app.post("/login")
async def login_post(request: Request):
    form = await request.form()
    email = form.get("email", "").strip().lower()
    
    if "@" in email:
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("user_email", email, max_age=2592000, httponly=True, samesite="lax")
        return response
    
    return RedirectResponse("/login")


@app.get("/admin/visitor-dashboard", response_class=HTMLResponse)
async def visitor_dashboard(request: Request):
    user_email = request.cookies.get("user_email")
    if not user_email:
        return RedirectResponse("/login")
    
    stats = visitor_counter.get_stats()
    
    # Sayfa görüntülemeleri tablosu
    page_rows = ""
    for page, views in sorted(stats["page_views"].items(), key=lambda x: x[1], reverse=True):
        page_rows += f"<tr><td>{page}</td><td>{views}</td></tr>"
    
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 İstatistikler | ICT SMART PRO</title>
    <style>
        body {{
            background: linear-gradient(135deg, #0a0022, #110033, #000);
            color: white;
            font-family: system-ui;
            margin: 0;
            padding: 20px;
        }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        h1 {{ text-align: center; background: linear-gradient(90deg, #00dbde, #fc00ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        .stat-box {{
            background: rgba(255,255,255,0.05);
            padding: 20px;
            border-radius: 15px;
            text-align: center;
        }}
        .stat-value {{
            font-size: 2.5rem;
            font-weight: bold;
            margin: 10px 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 30px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        th {{
            background: rgba(255,255,255,0.1);
        }}
        .btn {{
            padding: 12px 24px;
            background: linear-gradient(45deg, #fc00ff, #00dbde);
            color: white;
            border-radius: 12px;
            text-decoration: none;
            display: inline-block;
            margin: 10px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 ZİYARETÇİ İSTATİSTİKLERİ</h1>
        
        <div class="stats-grid">
            <div class="stat-box">
                <div>Toplam Ziyaret</div>
                <div class="stat-value">{stats['total_visits']}</div>
            </div>
            <div class="stat-box">
                <div>Aktif Kullanıcılar</div>
                <div class="stat-value">{stats['active_users']}</div>
            </div>
            <div class="stat-box">
                <div>Bugünkü Ziyaretler</div>
                <div class="stat-value">{stats['today_visits']}</div>
            </div>
            <div class="stat-box">
                <div>Bugünkü Benzersiz</div>
                <div class="stat-value">{stats['today_unique']}</div>
            </div>
        </div>
        
        <h2>📄 Sayfa Görüntülemeleri</h2>
        <table>
            <thead>
                <tr>
                    <th>Sayfa</th>
                    <th>Görüntülenme</th>
                </tr>
            </thead>
            <tbody>
                {page_rows if page_rows else '<tr><td colspan="2" style="text-align: center; padding: 40px; color: #888;">Henüz veri yok</td></tr>'}
            </tbody>
        </table>
        
        <div style="text-align: center; margin: 40px 0;">
            <a href="/" class="btn">🏠 Ana Sayfa</a>
            <a href="javascript:location.reload()" class="btn">🔄 Yenile</a>
        </div>
        
        <div style="text-align: center; color: #888; font-size: 0.9rem;">
            Son güncelleme: {stats['last_updated']}
        </div>
    </div>
</body>
</html>"""
    
    return HTMLResponse(content=html_content)


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
        }
    })


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
