# main.py — DÜZELTİLMİŞ VERSİYON
import base64
import logging
import io
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional
import json

import pandas as pd
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response, UploadFile, File, HTTPException
from core import (
    initialize, cleanup, single_subscribers, all_subscribers,
    pump_radar_subscribers, realtime_subscribers,
    shared_signals, active_strong_signals, top_gainers, last_update, rt_ticker,
    get_binance_client  # BU SATIR DÜZELTİLDİ
)
from utils import all_usdt_symbols

from openai import OpenAI
import os
import aiohttp

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("main")

# OpenAI client - opsiyonel
openai_client = None
if os.getenv("OPENAI_API_KEY"):
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Uygulama başlatılıyor...")
    await initialize()
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    await cleanup()

app = FastAPI(lifespan=lifespan, title="ICT SMART PRO", version="3.0 - STABLE")

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
    supported = ["1m","3m","5m","15m","30m","1h","4h","1d","1w"]
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
    realtime_subscribers.add(websocket)
    try:
        while True:
            await websocket.send_json({
                "tickers": rt_ticker["tickers"],
                "last_update": rt_ticker["last_update"]
            })
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        realtime_subscribers.discard(websocket)

# ==================== PAGES ====================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>ICT SMART PRO</title>
    <style>
        body{{background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;font-family:sans-serif;min-height:100vh;margin:0;display:flex;flex-direction:column}}
        .container{{max-width:1200px;margin:auto;padding:20px;flex:1}}
        h1{{font-size:clamp(2rem, 5vw, 5rem);text-align:center;background:linear-gradient(90deg,#00dbde,#fc00ff,#00dbde);-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:g 8s infinite}}
        @keyframes g{{0%{{background-position:0%}}100%{{background-position:200%}}}}
        .update{{text-align:center;color:#00ffff;margin:30px;font-size:clamp(1rem, 3vw, 1.8rem)}}
        table{{width:100%;border-collapse:separate;border-spacing:0 12px;margin:30px 0}}
        th{{background:#ffffff11;padding:clamp(10px, 2vw, 20px);font-size:clamp(1rem, 2.5vw, 1.6rem)}}
        tr{{background:#ffffff08;transition:.4s}}
        tr:hover{{transform:scale(1.02);box-shadow:0 15px 40px #00ffff44}}
        .green{{color:#00ff88;text-shadow:0 0 20px #00ff88}}
        .red{{color:#ff4444;text-shadow:0 0 20px #ff4444}}
        .btn{{display:block;width:90%;max-width:500px;margin:20px auto;padding:clamp(15px, 3vw, 25px);font-size:clamp(1.2rem, 4vw, 2.2rem);
            background:linear-gradient(45deg,#fc00ff,#00dbde);color:#fff;text-align:center;border-radius:50px;
            text-decoration:none;box-shadow:0 0 60px #ff00ff88;transition:.3s}}
        .btn:hover{{transform:scale(1.08);box-shadow:0 0 100px #ff00ff}}
    </style>
</head>
<body>
    <div style='position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:clamp(0.8rem, 2vw, 1.2rem);'>Hoş geldin, {user}</div>
    <div class="container">
        <h1>ICT SMART PRO</h1>
        <div class="update" id="update">Veri yükleniyor...</div>
        <table>
            <thead><tr><th>SIRA</th><th>COİN</th><th>FİYAT</th><th>24S DEĞİŞİM</th></tr></thead>
            <tbody id="table-body">
                <tr><td colspan="4" style="padding:80px;color:#888">Pump radar yükleniyor...</td></tr>
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
                </tr>`).join('');
        }};
    </script>
</body>
</html>"""

@app.get("/signal", response_class=HTMLResponse)
async def signal(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>CANLI SİNYAL + GRAFİK | ICT SMART PRO</title>
<style>
    body{{background:linear-gradient(135deg,#0a0022,#1a0033,#000);color:#fff;font-family:sans-serif;margin:0;padding:20px 0;min-height:100vh}}
    .container{{max-width:1200px;margin:auto;padding:20px;display:flex;flex-direction:column;gap:25px}}
    h1{{font-size:clamp(2rem,5vw,3.8rem);text-align:center;background:linear-gradient(90deg,#00dbde,#fc00ff,#00dbde);-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:g 8s infinite}}
    @keyframes g{{0%{{background-position:0}}100%{{background-position:200%}}}}
    .controls{{background:#ffffff11;border-radius:20px;padding:20px;text-align:center}}
    input,select,button{{width:100%;max-width:500px;padding:15px;margin:10px auto;font-size:1.4rem;border:none;border-radius:16px;background:#333;color:#fff}}
    button{{background:linear-gradient(45deg,#fc00ff,#00dbde);font-weight:bold;cursor:pointer}}
    #analyze-btn{{background:linear-gradient(45deg,#00dbde,#ff00ff,#00ffff)}}
    #status{{color:#00ffff;text-align:center;margin:15px}}
    #price-text{{font-size:clamp(3rem,8vw,5rem);font-weight:bold;background:linear-gradient(90deg,#00ffff,#ff00ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
    #signal-card{{background:#000000aa;border-radius:20px;padding:25px;text-align:center;min-height:160px}}
    #signal-card.green{{border-left:8px solid #00ff88}}
    #signal-card.red{{border-left:8px solid #ff4444}}
    #signal-text{{font-size:clamp(2rem,5vw,3rem)}}
    #ai-box{{background:#0d0033ee;border-radius:20px;padding:25px;border:3px solid #00dbde;display:none}}
    .chart-container{{width:95%;max-width:1000px;margin:30px auto;border-radius:20px;overflow:hidden;box-shadow:0 15px 50px #00ffff44;background:#0a0022}}
    #tradingview_widget{{height:500px;width:100%}}
</style>
</head>
<body>
<div style="position:fixed;top:15px;left:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;z-index:100">Hoş geldin, {user}</div>
<div class="container">
    <h1>📊 CANLI SİNYAL + GRAFİK</h1>
    <div class="controls">
        <input id="pair" placeholder="Coin (örn: BTCUSDT)" value="BTCUSDT">
        <select id="tf">
            <option value="1m">1 Dakika</option><option value="3m">3 Dakika</option><option value="5m" selected>5 Dakika</option>
            <option value="15m">15 Dakika</option><option value="30m">30 Dakika</option><option value="1h">1 Saat</option>
            <option value="4h">4 Saat</option><option value="1d">1 Gün</option><option value="1w">1 Hafta</option>
        </select>
        <button onclick="connect()">🔴 CANLI SİNYAL BAĞLANTISI KUR</button>
        <button id="analyze-btn" onclick="analyzeChartWithAI()">🤖 GRAFİĞİ GPT-4o İLE ANALİZ ET</button>
        <div id="status">Grafik yükleniyor...</div>
    </div>
    <div style="text-align:center;margin:20px"><div id="price-text">Yükleniyor...</div></div>
    <div id="signal-card"><div id="signal-text" style="color:#ffd700">Sinyal bağlantısı kurulmadı</div>
        <div id="signal-details">Canlı sinyal için butona tıklayın.</div></div>
    <div id="ai-box"><h3 style="color:#00dbde;text-align:center">🤖 GPT-4o Teknik Analizi</h3>
        <p id="ai-comment">Analiz için butona tıklayın.</p></div>
    <div class="chart-container"><div id="tradingview_widget"></div></div>
    <div style="text-align:center"><a href="/" style="color:#00dbde">← Ana Sayfa</a> | <a href="/signal/all" style="color:#00dbde">Tüm Coinler</a></div>
</div>

<script src="https://s3.tradingview.com/tv.js"></script>
<script>
    let ws = null;
    let tvWidget = null;
    let currentPrice = null;

    const tfMap = {{"1m":"1","3m":"3","5m":"5","15m":"15","30m":"30","1h":"60","4h":"240","1d":"D","1w":"W"}};

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
            autosize: true, width: "100%", height: 500,
            symbol: symbol, interval: interval, timezone: "Etc/UTC",
            theme: "dark", style: "1", locale: "tr",
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
            // Önce kendi analiz motorumuzu çalıştır
            const symbol = getSymbol().replace("BINANCE:", "");
            const timeframe = document.getElementById('tf').value;
            
            // Kendi analiz API'mizi çağır
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
                
                // Eğer grafik resmi varsa göster
                if (data.chart_image) {{
                    comment.innerHTML += '<br><br><img src="' + data.chart_image + '" style="max-width:100%;border-radius:10px;margin-top:15px">';
                }}
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
        const symbol = getSymbol().replace("BINANCE:", "");
        const tf = document.getElementById('tf').value;
        if (ws) ws.close();
        ws = new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws/signal/'+symbol+'/'+tf);

        ws.onopen = () => {{
            document.getElementById('status').innerHTML = "✅ Canlı sinyal akışı başladı!";
        }};

        ws.onmessage = e => {{
            const d = JSON.parse(e.data);
            const card = document.getElementById('signal-card');
            const text = document.getElementById('signal-text');
            const details = document.getElementById('signal-details');

            text.innerHTML = d.signal || "Sinyal bekleniyor...";
            details.innerHTML = `<strong>${{d.pair || symbol.replace('USDT','/USDT')}}</strong><br>
                Skor: <strong>${{d.score || '?'}}/100</strong> | ${{d.killzone || ''}}<br>
                ${{d.last_update ? 'Son: ' + d.last_update : ''}}<br><small>${{d.triggers || ''}}</small>`;

            if (d.signal && d.signal.includes('ALIM')) {{ card.className = 'green'; text.style.color = '#00ff88'; }}
            else if (d.signal && d.signal.includes('SATIM')) {{ card.className = 'red'; text.style.color = '#ff4444'; }}
            else {{ card.className = ''; text.style.color = '#ffd700'; }}
        }};
    }}
</script>
</body>
</html>"""

# ==================== API ENDPOINTS ====================

@app.post("/api/analyze-chart")
async def analyze_chart(request: Request):
    try:
        body = await request.json()
        symbol = body.get("symbol", "BTCUSDT").upper()
        timeframe = body.get("timeframe", "5m")
        
        logger.info(f"Analiz için veri çekiliyor: {symbol} {timeframe}")
        
        # Binance client'ını al
        binance_client = get_binance_client()  # DÜZELTME: Bu satır değişti
        
        if not binance_client:
            return JSONResponse({
                "analysis": "❌ Binance bağlantısı kurulamadı. Lütfen daha sonra tekrar deneyin.",
                "success": False
            })
        
        # Binance'ten veri çek
        try:
            # Binance API formatına çevir
            interval_map = {
                "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
                "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
            }
            
            interval = interval_map.get(timeframe, "5m")
            
            # Format symbol for ccxt
            ccxt_symbol = symbol.replace('USDT', '/USDT')
            
            # Binance client'ı ile veri çek
            klines = await binance_client.fetch_ohlcv(
                ccxt_symbol, 
                timeframe=interval, 
                limit=100
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
        df = pd.DataFrame(klines[:100])
        if len(df.columns) >= 5:
            df = df[[0, 1, 2, 3, 4]]
            df.columns = ['timestamp', 'open', 'high', 'low', 'close']
        else:
            df.columns = ['timestamp', 'open', 'high', 'low', 'close'][:len(df.columns)]
        
        # Sayısal verilere çevir
        for col in ['open', 'high', 'low', 'close']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Sinyal üret (indicators.py'den)
        signal = None
        try:
            from indicators import generate_ict_signal
            signal = generate_ict_signal(df, symbol, timeframe)
        except ImportError:
            logger.warning("indicators modülü bulunamadı, demo sinyal üretiliyor")
            # Demo sinyal
            last_price = df['close'].iloc[-1] if not df.empty else 0
            prev_price = df['close'].iloc[-2] if len(df) > 1 else last_price
            change = ((last_price - prev_price) / prev_price * 100) if prev_price else 0
            
            signal = {
                "signal": "ALIM" if change > 0 else "SATIM",
                "score": min(abs(int(change * 10)), 95),
                "strength": "YÜKSEK" if abs(change) > 1 else "ORTA",
                "killzone": "LONDRA" if "12:00" in timeframe else "NEWYORK",
                "triggers": "Demo: " + ("Yükseliş" if change > 0 else "Düşüş") + " eğilimi",
                "pair": symbol,
                "last_update": datetime.now().strftime("%H:%M:%S")
            }
        
        # Kendi yorum motorumuz
        if not signal:
            analysis = f"{symbol} {timeframe} grafiğinde şu an güçlü bir ICT sinyali tespit edilmedi. Piyasa range içinde veya sinyal kriterleri sağlanmıyor. Gözlem devam ediyor."
        else:
            strength = signal.get("strength", "YÜKSEK")
            triggers = signal.get("triggers", "")
            score = signal.get("score", 0)
            killzone = signal.get("killzone", "Normal")

            analysis = f"""
{symbol} {timeframe} zaman diliminde <strong>{signal['signal']}</strong> tespit edildi!

📊 Skor: <strong>{score}/100</strong> ({strength})
🕐 Killzone: <strong>{killzone}</strong>
🎯 Tetikleyen Unsurlar: {triggers or "RSI6 + SMA50 kesişimi"}

Piyasa yapısında önemli bir hareket gözlemleniyor. Teknik seviyeler yakından takip edilmeli.

Bu bir yatırım tavsiyesi değildir. Yalnızca teknik analiz yorumudur.
            """.strip()

        return JSONResponse({
            "analysis": analysis,
            "signal_data": signal or {},
            "success": True
        })

    except Exception as e:
        logger.error(f"Analiz hatası: {e}", exc_info=True)
        return JSONResponse({
            "analysis": f"❌ Analiz sırasında hata: {str(e)[:100]}",
            "success": False,
            "detail": str(e)
        }, status_code=500)

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

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "symbols": len(all_usdt_symbols) if all_usdt_symbols else 0,
        "realtime_coins": len(rt_ticker.get("tickers", [])),
        "strong_5m": len(active_strong_signals.get("5m", [])),
        "openai_available": openai_client is not None
    }

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return """<form method="post" action="/login" style="max-width:400px;margin:100px auto;text-align:center;background:#0a0022;padding:40px;border-radius:20px">
    <h2 style="color:#00dbde">Giriş Yap</h2>
    <input name="email" type="email" placeholder="E-posta" required style="width:100%;padding:15px;margin:10px 0;border-radius:12px;border:none">
    <button type="submit" style="width:100%;padding:15px;background:linear-gradient(45deg,#fc00ff,#00dbde);border:none;border-radius:12px;color:white;font-weight:bold">Giriş Yap</button>
    </form>"""

@app.post("/login")
async def login(request: Request):
    form = await request.form()
    email = form.get("email", "").strip().lower()
    if "@" in email:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("user_email", email, max_age=2592000, httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
