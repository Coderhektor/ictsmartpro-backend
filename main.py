import base64
import logging
import io
import asyncio
from datetime import datetime, timezone
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

# ==================== LOGGER ====================
logger = logging.getLogger("uvicorn")
logger.setLevel(logging.INFO)

# ==================== GLOBAL FALLBACKS (HER ZAMAN TANIMLI!) ====================
# → NameError riskini tamamen ortadan kaldırır

def get_available_timeframes():
    return ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

# Dummy fonksiyonlar
def get_binance_client(): return None
def get_bybit_client(): return None
def get_okex_client(): return None
def get_strong_signals_for_timeframe(tf): return []

class GrokIndicators:
    def __init__(self): pass
    def detect_all_patterns(self, df: pd.DataFrame) -> Dict[str, Any]:
        return {}

def generate_ict_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Dict[str, Any]:
    price = float(df['close'].iloc[-1]) if not df.empty else 0.0
    return {
        "pair": symbol,
        "timeframe": timeframe,
        "current_price": price,
        "signal": "⏸️ ANALİZ BEKLENİYOR",
        "score": 50,
        "killzone": "Normal",
        "triggers": "Indicators modülü eksik",
        "last_update": datetime.now(timezone.utc).strftime("%H:%M UTC"),
        "strength": "ORTA"
    }

def generate_simple_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Dict[str, Any]:
    if len(df) < 2:
        return generate_ict_signal(df, symbol, timeframe)
    price = float(df['close'].iloc[-1])
    prev = float(df['close'].iloc[-2])
    change = ((price - prev) / prev) * 100
    if change > 1.5:
        signal, score, strength = "🚀 AL", 75, "GÜÇLÜ"
    elif change < -1.5:
        signal, score, strength = "🔻 SAT", 25, "ZAYIF"
    else:
        signal, score, strength = "⏸️ BEKLE", 50, "ORTA"
    return {
        "pair": symbol,
        "timeframe": timeframe,
        "current_price": price,
        "signal": signal,
        "score": score,
        "killzone": "Normal",
        "triggers": f"Değişim: {change:.2f}%",
        "last_update": datetime.now(timezone.utc).strftime("%H:%M UTC"),
        "strength": strength
    }

# Dummy state
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
    def __init__(self): self.subscribers = set()
    async def subscribe(self, ws): self.subscribers.add(ws)
    async def unsubscribe(self, ws): self.subscribers.discard(ws)
rt_ticker = DummyRTicker()

async def initialize(): logger.info("🔄 Dummy initialize")
async def cleanup(): logger.info("🔄 Dummy cleanup")

# ==================== CORE MODULE ====================
try:
    from core import rt_ticker, top_gainers, last_update, initialize, cleanup, price_pool
    logger.info("✅ Core modülü yüklendi")
except ImportError as e:
    logger.warning(f"⚠️ Core yüklenemedi: {e}")

# ==================== INDICATORS MODULE ====================
try:
    from indicators import GrokIndicatorsPro as GrokIndicators, generate_ict_signal, generate_simple_signal
    logger.info("✅ Indicators modülü yüklendi")
except ImportError as e:
    logger.warning(f"⚠️ Indicators yüklenemedi: {e}")

# ==================== EXTERNAL CLIENTS ====================
from pycoingecko import CoinGeckoAPI
cg_client = CoinGeckoAPI()

# ==================== VISITOR COUNTER ====================
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

    def get_stats(self):
        today = datetime.now().strftime("%Y-%m-%d")
        d = self.daily_stats.get(today, {"visits": 0, "unique": set()})
        return {
            "total_visits": self.total_visits,
            "active_users": len(self.active_users),
            "today_visits": d["visits"],
            "today_unique": len(d["unique"]),
            "page_views": self.page_views,
            "last_updated": datetime.now().strftime("%H:%M:%S")
        }

visitor_counter = VisitorCounter()

def get_visitor_stats_html():
    s = visitor_counter.get_stats()
    return f"""
<div style="position:fixed;top:15px;right:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:clamp(0.8rem,2vw,1.2rem);z-index:1000;backdrop-filter:blur(10px);border:1px solid #00ff8855;">
<div>👁️ Toplam: <strong>{s['total_visits']}</strong></div>
<div>🔥 Bugün: <strong>{s['today_visits']}</strong></div>
<div>👥 Aktif: <strong>{s['active_users']}</strong></div>
</div>"""

# ==================== LIFESPAN ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 ICT SMART PRO başlatılıyor...")
    await initialize()
    yield
    logger.info("🛑 ICT SMART PRO kapatılıyor...")
    await cleanup()

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="3.2 PROD")

# ==================== MIDDLEWARE ====================
@app.middleware("http")
async def count_visitors(request: Request, call_next):
    vid = request.cookies.get("visitor_id") or hashlib.sha256(
        f"{request.client.host}{request.headers.get('user-agent','')}".encode()
    ).hexdigest()[:12]
    await visitor_counter.add_visit(request.url.path, vid)
    res = await call_next(request)
    if not request.cookies.get("visitor_id"):
        res.set_cookie("visitor_id", vid, max_age=2592000, httponly=True, samesite="lax")
    return res

# ==================== WEBSOCKETS ====================
@app.websocket("/ws/pump_radar")
async def ws_pump(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    try:
        # Core sadece gainers üretir → losers simülasyon
        losers = [{**g, "change": -abs(g["change"])} for g in top_gainers][:len(top_gainers)]
        await websocket.send_json({
            "top_gainers": top_gainers,
            "top_losers": losers,
            "last_update": last_update,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        while True:
            await asyncio.sleep(30)
            losers = [{**g, "change": -abs(g["change"])} for g in top_gainers][:len(top_gainers)]
            await websocket.send_json({
                "top_gainers": top_gainers,
                "top_losers": losers,
                "last_update": last_update,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
    except WebSocketDisconnect:
        pass
    finally:
        pump_radar_subscribers.discard(websocket)

@app.websocket("/ws/signal/{pair}/{timeframe}")
async def ws_signal(websocket: WebSocket, pair: str, timeframe: str):
    tf = timeframe.lower()
    if tf not in get_available_timeframes():
        await websocket.close(code=1008, reason="Desteklenmeyen timeframe")
        return
    symbol = pair.upper().replace("/", "").replace("-", "")
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    await websocket.accept()
    try:
        price = await price_pool.get_best_price(symbol) if hasattr(price_pool, 'get_best_price') else 0.0
        await websocket.send_json({
            "pair": symbol,
            "timeframe": tf.upper(),
            "current_price": price,
            "signal": "⏸️ Bekleniyor",
            "score": 50,
            "killzone": "Normal",
            "triggers": "Sinyal bağlantısı aktif"
        })
        while True:
            await asyncio.sleep(30)
            price = await price_pool.get_best_price(symbol) if hasattr(price_pool, 'get_best_price') else 0.0
            await websocket.send_json({"heartbeat": True, "price": price})
    except WebSocketDisconnect:
        pass

# ==================== HELPERS ====================
async def fetch_coingecko_ohlcv(symbol: str, timeframe: str) -> List[List]:
    coin_id_map = {
        "BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "BNBUSDT": "binancecoin",
        "SOLUSDT": "solana", "XRPUSDT": "ripple", "ADAUSDT": "cardano",
        "DOGEUSDT": "dogecoin", "TRXUSDT": "tron", "AVAXUSDT": "avalanche-2"
    }
    coin_id = coin_id_map.get(symbol, symbol.replace("USDT", "").lower())
    days = {"1m":1,"3m":1,"5m":1,"15m":1,"30m":1,"1h":7,"4h":14,"1d":30,"1w":90}.get(timeframe, 30)
    try:
        data = cg_client.get_coin_market_chart_by_id(coin_id, "usd", days=days)
        prices = data.get('prices', [])
        volumes = data.get('total_volumes', [])
        ohlcv = []
        for i in range(len(prices)):
            ts = int(prices[i][0] / 1000)
            p = prices[i][1]
            o = h = l = c = p
            if i > 0:
                o = prices[i-1][1]
                h = max(o, p)
                l = min(o, p)
                c = p
            v = volumes[i][1] if i < len(volumes) else 0
            ohlcv.append([ts, o, h, l, c, v])
        return ohlcv[-150:]
    except Exception as e:
        logger.warning(f"CoinGecko OHLCV hatası: {e}")
        return []

# ==================== API: ANALYZE CHART ====================
@app.post("/api/analyze-chart")
async def analyze_chart(request: Request):
    try:
        body = await request.json()
        symbol = (body.get("symbol") or "BTC").upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        tf = body.get("timeframe", "5m")

        klines = await fetch_coingecko_ohlcv(symbol, tf)
        if not klines or len(klines) < 50:
            return JSONResponse({
                "success": False,
                "analysis": f"❌ {symbol} için yeterli veri yok. Lütfen geçerli bir coin girin (BTC, ETH, SOL vs.)"
            })

        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].apply(pd.to_numeric)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        df = df.sort_values('timestamp').tail(150)

        # Signal & Patterns
        try:
            signal = generate_ict_signal(df.copy(), symbol, tf)
        except:
            signal = generate_simple_signal(df.copy(), symbol, tf)
        analyzer = GrokIndicators()
        patterns = analyzer.detect_all_patterns(df)

        pos = [f"✅ {k.replace('_',' ').title()}" for k,v in patterns.items() 
               if isinstance(v, pd.Series) and len(v) and v.iloc[-1] and 'bull' in k.lower()]
        neg = [f"⚠️ {k.replace('_',' ').title()}" for k,v in patterns.items() 
               if isinstance(v, pd.Series) and len(v) and v.iloc[-1] and 'bear' in k.lower()]
        triggers = "\n".join(pos + neg) or "😐 Belirgin patern yok"

        price = signal.get("current_price", 0)
        analysis = f"""🔍 **{symbol} · {tf.upper()} Analiz**
🎯 **Sinyal:** **{signal.get('signal', 'N/A')}**
📈 **Skor:** {signal.get('score', '?')}/100 | {signal.get('strength', 'N/A')}
💰 **Fiyat:** ${price:,.6f}
🕐 **Killzone:** {signal.get('killzone', 'N/A')}
🔥 **Tetikleyiciler:**
{triggers}
💡 AI analiz hazır. Gerçek zamanlı veri için Core modülü gereklidir.

⚠️ Bu bir yatırım tavsiyesi değildir."""
        return JSONResponse({"success": True, "analysis": analysis})
    except Exception as e:
        logger.exception("Analiz hatası")
        return JSONResponse({"success": False, "analysis": f"❌ Hata: {str(e)[:150]}"}, status_code=500)

# ==================== ROUTES ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    stats = get_visitor_stats_html()
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>ICT SMART PRO</title>
<style>:root{{--g:linear-gradient(135deg,#0a0022,#1a0033,#000);--a:linear-gradient(90deg,#00dbde,#fc00ff,#00dbde);}}
body{{background:var(--g);color:#fff;font-family:Segoe UI;margin:0;min-height:100vh;overflow-x:hidden;}}
.container{{max-width:1400px;margin:0 auto;padding:20px;}}
.h1{{font-size:clamp(2rem,5vw,4.5rem);text-align:center;background:var(--a);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:20px 0;font-weight:800;}}
.btn{{display:inline-block;min-width:240px;padding:18px 24px;font-size:clamp(1.1rem,2.5vw,1.6rem);background:var(--a);color:#fff;text-align:center;border-radius:15px;text-decoration:none;box-shadow:0 0 30px rgba(252,0,255,0.4);border:none;cursor:pointer;margin:10px;}}
.btn:hover{{transform:scale(1.03);box-shadow:0 0 50px rgba(252,0,255,0.7);}}
.loader{{border:4px solid #00ffff33;border-top:#00ffff solid 4px;border-radius:50%;width:40px;height:40px;animation:spin 1s linear infinite;margin:20px auto;}}
@keyframes spin{{0%{{transform:rotate(0)}}100%{{transform:rotate(360deg)}}}}
</style></head><body>
<div style='position:fixed;top:15px;left:15px;background:rgba(0,0,0,0.8);padding:10px 20px;border-radius:20px;color:#00ff88;font-size:clamp(0.8rem,2vw,1.2rem)'>👤 Hoş geldin, <strong>{user}</strong></div>
{stats}
<div class="container">
<h1 class="h1">ICT SMART PRO</h1>
<div style="text-align:center;color:#00dbde;margin:30px 0;font-size:1.4rem">Akıllı Kripto Sinyal ve Analiz Platformu</div>
<div style="text-align:center;color:#00dbde;margin:20px 0;font-size:1.2rem;background:rgba(0,219,222,0.1);padding:15px;border-radius:10px">
<div class="loader"></div>
<div id="update">Veri yükleniyor...</div>
</div>
<div style="text-align:center;margin:40px 0;">
<a href="/signal" class="btn">🚀 Tek Coin Canlı Sinyal</a>
<a href="/signal/all" class="btn">🔥 Tüm Coinleri Tara</a>
<a href="/admin" class="btn">⚙️ Admin Paneli</a>
</div>
</div>
<script>
const ws = new WebSocket((window.location.protocol==='https:'?'wss':'ws')+'://'+window.location.host+'/ws/pump_radar');
ws.onmessage=e=>{{try{{const d=JSON.parse(e.data);document.getElementById('update').innerHTML=`📊 Son Güncelleme: <strong>${{d.last_update||'Şimdi'}}</strong>`}}catch(_){}}};
ws.onerror=()=>document.getElementById('update').innerHTML='⚠️ Bağlantı hatası';
</script>
</body></html>""")

@app.get("/signal/", response_class=HTMLResponse)
async def signal_page(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    stats = get_visitor_stats_html()
    tfs = get_available_timeframes()
    tf_options = ''.join([f'<option value="{tf}"{" selected" if tf=="5m" else ""}>{tf.upper()}</option>' for tf in tfs])

    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Tek Coin Sinyal</title>
<style>
body{{background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;font-family:Arial,sans-serif;margin:0;padding:20px;min-height:100vh;}}
.container{{max-width:1000px;margin:0 auto;}}
.title{{text-align:center;font-size:2.4rem;background:linear-gradient(90deg,#00dbde,#fc00ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:30px 0;}}
.controls{{background:rgba(255,255,255,0.05);padding:25px;border-radius:15px;text-align:center;margin:25px 0;}}
input,select{{background:#1a0033;color:#00ff88;border:2px solid #00dbde;border-radius:12px;padding:14px;font-size:1.2rem;margin:0 10px;}}
select{{min-width:200px;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='10'%3E%3Cpath fill='%2300ff88' d='M1 1l6 6 6-6'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 15px center;background-size:14px;}}
.btn{{background:linear-gradient(45deg,#fc00ff,#00dbde);color:#fff;border:none;padding:14px 28px;border-radius:10px;font-size:1.1rem;font-weight:bold;margin:10px;cursor:pointer;display:inline-block;min-width:220px;}}
.card{{background:rgba(0,0,0,0.5);padding:25px;border-radius:15px;margin:30px 0;text-align:center;border-left:5px solid #ffd700;}}
.card.green{{border-left-color:#00ff88;}}
.card.red{{border-left-color:#ff4444;}}
#signal{{font-size:2rem;font-weight:bold;margin:15px 0;color:#ffd700;}}
.ai{{background:rgba(10,0,30,0.8);padding:20px;border-radius:10px;border:2px solid #00dbde;display:none;margin:25px 0;}}
.chart{{width:100%;height:80vh;min-height:900px;background:#000;border-radius:16px;margin:30px 0;box-shadow:0 0 30px rgba(0,219,222,0.2);}}
</style>
<script src="https://s3.tradingview.com/tv.js"></script>
</head><body>
<div style="position:fixed;top:15px;left:15px;background:rgba(0,0,0,0.8);padding:10px 20px;border-radius:20px;color:#00ff88;font-size:1.1rem">👤 Hoş geldin, <strong>{user}</strong></div>
{stats}
<div class="container">
<h1 class="title">📊 Tek Coin Canlı Sinyal</h1>
<div class="controls">
<input type="text" id="pair" placeholder="Coin (örn: BTC)" value="BTC">
<select id="timeframe">{tf_options}</select><br>
<button class="btn" onclick="connect()">🔴 Canlı Sinyal Kur</button>
<button class="btn" style="background:linear-gradient(45deg,#00dbde,#ff00ff)" onclick="analyze()">🤖 Grafiği Analiz Et</button>
<div id="status" style="color:#00ffff;margin-top:10px">Bağlantı bekleniyor...</div>
</div>
<div class="card" id="card">
<div id="signal">Sinyal bekleniyor...</div>
<div id="details">Lütfen "Canlı Sinyal Kur" butonuna tıklayın.</div>
</div>
<div class="ai" id="ai"></div>
<div class="chart"><div id="tv"></div></div>
</div>
<script>
let ws, widget;
const tfMap = {{'1m':'1','3m':'3','5m':'5','15m':'15','30m':'30','1h':'60','4h':'240','1d':'D','1w':'W'}};

function symbolToTV(s) {{
    s = s.trim().toUpperCase();
    return 'BINANCE:' + (s.endsWith('USDT') ? s : s + 'USDT');
}}

function connect() {{
    const pair = document.getElementById('pair').value;
    const tf = document.getElementById('timeframe').value;
    const sym = symbolToTV(pair);
    const int = tfMap[tf] || '5';

    if (ws) ws.close();
    if (widget) widget.remove();

    widget = new TradingView.widget({{
        width: '100%', height: '100%',
        symbol: sym,
        interval: int,
        timezone: 'Etc/UTC',
        theme: 'dark',
        style: '1',
        locale: 'tr',
        container_id: 'tv',
        library_path: 'https://s3.tradingview.com/tv.js',
        autosize: true,
        overrides: {{
            'paneProperties.background': '#000000',
            'scalesProperties.textColor': '#FFFFFF'
        }}
    }});

    ws = new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws/signal/'+pair+'/'+tf);
    ws.onopen = () => document.getElementById('status').innerHTML = `✅ ${pair} ${tf.toUpperCase()} bağlantısı kuruldu`;
    ws.onmessage = e => {{
        if (e.data.includes('heartbeat')) return;
        try {{
            const d = JSON.parse(e.data);
            const card = document.getElementById('card');
            const sig = d.signal || '⏸️ Bekleniyor';
            document.getElementById('signal').innerHTML = sig;
            document.getElementById('details').innerHTML = `<strong>${{d.pair||pair}}</strong><br>💰 Fiyat: $${{(d.current_price||0).toFixed(6)}}</br>📊 Skor: ${{d.score||'?'}}`;
            card.className = 'card ' + (sig.includes('AL')?'green':sig.includes('SAT')?'red':'');
            document.getElementById('signal').style.color = sig.includes('AL')?'#00ff88':sig.includes('SAT')?'#ff4444':'#ffd700';
        }} catch(_){} 
    }};
}}

async function analyze() {{
    const btn = Array.from(document.querySelectorAll('.btn')).find(b=>b.textContent.includes('Analiz'));
    btn.disabled = true;
    btn.innerHTML = '⏳ Analiz ediliyor...';
    const ai = document.getElementById('ai');
    ai.style.display = 'block';
    ai.innerHTML = '📊 Analiz yapılıyor...';

    try {{
        const res = await fetch('/api/analyze-chart', {{
            method: 'POST',
            headers: {{'Content-Type':'application/json'}},
            body: JSON.stringify({{
                symbol: document.getElementById('pair').value,
                timeframe: document.getElementById('timeframe').value
            }})
        }});
        const d = await res.json();
        ai.innerHTML = d.success ? d.analysis.replace(/\
/g, '<br>') : `<strong style="color:#ff4444">Hata:</strong><br>${{d.analysis}}`;
    }} catch(err) {{
        ai.innerHTML = `<strong style="color:#ff4444">Bağlantı hatası:</strong><br>${{err.message}}`;
    }} finally {{
        btn.disabled = false;
        btn.innerHTML = '🤖 Grafiği Analiz Et';
    }}
}}

// Sayfa yüklendiğinde otomatik bağlan
setTimeout(connect, 500);
</script>
</body></html>""")

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}

# ==================== ENTRY POINT ====================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🚀 ICT SMART PRO {port} portunda başlatılıyor...")
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=1, log_level="info")

