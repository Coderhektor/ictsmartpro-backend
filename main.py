# ==============================
# ICT SMART PRO — REAL-TIME SIGNAL BOT
# API KEY'SİZ | GERÇEK ZAMANLI | BINLERCE KULLANICI
# ==============================

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import ccxt
import httpx
import pandas as pd
import pandas_ta as ta
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("pump_radar")

# --- FASTAPI ---
app = FastAPI()
app.mount("/assets", StaticFiles(directory=".", html=False), name="assets")

# --- GLOBALS ---
top_gainers = []
last_update = "Başlatılıyor..."
exchange = ccxt.binance({'enableRateLimit': True})
exchange.load_markets()

# --- REAL-TIME TICKER (WebSocket ile) ---
class RealTimeTicker:
    def __init__(self):
        self.tickers = {}  # symbol → {price, trades: deque}
        self.subscribers = defaultdict(set)  # symbol → set(websockets)

    async def start(self):
        # En popüler coinler (isteğe göre genişletilebilir)
        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "PEPEUSDT", "SHIBUSDT", "AVAXUSDT"]
        streams = []
        for s in symbols:
            streams.append(f"{s.lower()}@trade")
        stream_param = "/".join(streams)
        url = f"wss://stream.binance.com:9443/stream?streams={stream_param}"

        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("✅ Binance WebSocket bağlantısı kuruldu.")
                    while True:
                        msg = await ws.recv()
                        try:
                            data = json.loads(msg)['data']
                            if data['e'] != 'trade': 
                                continue
                            symbol = data['s']
                            price = float(data['p'])
                            qty = float(data['q'])
                            ts = int(data['T'])

                            if symbol not in self.tickers:
                                self.tickers[symbol] = {"price": price, "trades": deque(maxlen=100)}
                            self.tickers[symbol]["price"] = price
                            self.tickers[symbol]["trades"].append((ts, price, qty))

                            # Abonelere yayınla
                            for ws_client in list(self.subscribers[symbol]):
                                try:
                                    await ws_client.send_json({
                                        "type": "tick",
                                        "symbol": symbol,
                                        "price": price,
                                        "volume": qty,
                                        "ts": ts
                                    })
                                except:
                                    self.subscribers[symbol].discard(ws_client)
                        except Exception as e:
                            logger.debug(f"Mesaj işlenemedi: {e}")
            except Exception as e:
                logger.warning(f"WebSocket bağlantısı koptu: {e}. 5 sn sonra tekrar denenecek...")
                await asyncio.sleep(5)

rt_ticker = RealTimeTicker()

# --- HTTP CLIENT ---
http_client = httpx.AsyncClient(
    limits=httpx.Limits(max_connections=20),
    timeout=httpx.Timeout(10.0),
    headers={"User-Agent": "Mozilla/5.0"}
)

# --- PUMP RADAR VERİ ÇEKME ---
async def fetch_data():
    global top_gainers, last_update
    try:
        urls = [
            "https://data.binance.com/api/v3/ticker/24hr",
            "https://data-api.binance.vision/api/v3/ticker/24hr",
            "https://api1.binance.com/api/v3/ticker/24hr",
        ]
        binance_data = None
        async with httpx.AsyncClient(timeout=15) as client:
            for url in urls:
                try:
                    resp = await client.get(url, timeout=10)
                    if resp.status_code == 200:
                        binance_data = resp.json()
                        break
                except: continue

            clean_coins = []
            if binance_data:
                for item in binance_data:
                    s = item.get("symbol", "")
                    if not s.endswith("USDT"): continue
                    try:
                        price = float(item["lastPrice"])
                        change = float(item["priceChangePercent"])
                        volume = float(item["quoteVolume"])
                        if volume >= 1_000_000:
                            clean_coins.append({"symbol": s.replace("USDT", "/USDT"), "price": price, "change": change})
                    except: continue

            top_gainers = sorted(clean_coins, key=lambda x: x["change"], reverse=True)[:10]
            last_update = datetime.now().strftime("%H:%M:%S")
    except Exception as e:
        logger.error(f"Pump Radar hatası: {e}")
        last_update = "Bağlantı Hatası"

# --- ANLIK SİNYAL (500ms) ---
async def quick_signal(symbol: str, current_price: float):
    trades = rt_ticker.tickers.get(symbol, {}).get("trades", deque())
    if len(trades) < 10:
        return {"signal": "😐 NÖTR", "price": round(current_price, 4)}

    prices = [t[1] for t in list(trades)[-10:]]
    up_moves = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i-1])
    down_moves = len(prices) - 1 - up_moves
    
    vols = [t[2] for t in list(trades)[-20:]]
    avg_vol = sum(vols) / len(vols) if vols else 1
    last_vol = vols[-1] if vols else 0
    volume_spike = last_vol > avg_vol * 1.8

    # Sinyal mantığı
    if up_moves >= 7 and volume_spike:
        signal = "💥 ANLIK ALIM!"
    elif up_moves >= 6:
        signal = "📈 YUKARI MOMENTUM"
    elif down_moves >= 7 and volume_spike:
        signal = "🔥 ANLIK SATIM!"
    elif down_moves >= 6:
        signal = "📉 AŞAĞI MOMENTUM"
    else:
        signal = "😐 NÖTR"

    return {
        "pair": f"{symbol[:-4]}/USDT",
        "timeframe": "realtime",
        "current_price": round(current_price, 4),
        "signal": signal,
        "momentum": "up" if up_moves > down_moves else "down" if down_moves > up_moves else "flat",
        "volume_spike": volume_spike,
        "last_update": datetime.now().strftime("%H:%M:%S"),
        "type": "quick"
    }

# --- WEBSOCKET ENDPOINT (GERÇEK ZAMANLI) ---
@app.websocket("/ws/signal/{pair}/{timeframe}")
async def websocket_endpoint(websocket: WebSocket, pair: str, timeframe: str):
    await websocket.accept()
    symbol = pair.upper().replace("/", "").replace("-", "").replace(" ", "")
    if not symbol.endswith("USDT"):
        await websocket.send_json({"error": "Sadece USDT çiftleri desteklenir (örn: BNBUSDT)"})
        await websocket.close()
        return

    # Abonelik
    rt_ticker.subscribers[symbol].add(websocket)
    logger.info(f"🔔 Abone oldu: {symbol} ({len(rt_ticker.subscribers[symbol])} aktif)")

    # İlk sinyal
    try:
        first_signal = await quick_signal(symbol, rt_ticker.tickers.get(symbol, {}).get("price", 0) or 0)
        await websocket.send_json(first_signal)
    except Exception as e:
        logger.warning(f"İlk sinyal hatası: {e}")

    # Gerçek zamanlı izleme
    last_signal = None
    try:
        while True:
            await asyncio.sleep(0.5)
            if symbol in rt_ticker.tickers:
                price = rt_ticker.tickers[symbol]["price"]
                signal = await quick_signal(symbol, price)
                sig_key = f"{signal['signal']}_{signal['momentum']}_{signal['volume_spike']}"
                if sig_key != last_signal:
                    last_signal = sig_key
                    await websocket.send_json(signal)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS hatası: {e}")
    finally:
        rt_ticker.subscribers[symbol].discard(websocket)
        logger.info(f"🔴 Abonelik sonlandı: {symbol}")

# --- ARKAPLAN GÖREVLERİ ---
@app.on_event("startup")
async def startup():
    # Arka plan görevleri
    asyncio.create_task(fetch_data())
    asyncio.create_task(rt_ticker.start())

    async def radar_loop():
        while True:
            await asyncio.sleep(30)
            await fetch_data()
    asyncio.create_task(radar_loop())

    logger.info("✅ Sistem başladı — Gerçek zamanlı sinyal aktif!")

# --- ANA SAYFA ---
@app.get("/", response_class=HTMLResponse)
async def ana_sayfa():
    if not top_gainers:
        rows = '<tr><td colspan="4" style="font-size:2.4rem;color:#ff4444;padding:80px;text-align:center;">🚨 Veri çekilemedi!<br>Lütfen biraz sonra tekrar deneyin.</td></tr>'
        update_text = "Bağlantı Hatası!"
    else:
        rows = ""
        for i, coin in enumerate(top_gainers, 1):
            glow = "text-shadow: 0 0 30px #00ff88;" if coin["change"] > 0 else "text-shadow: 0 0 30px #ff0044;"
            rows += f"""
            <tr class="coin-row">
                <td class="rank">#{i}</td>
                <td class="symbol">{coin['symbol']}</td>
                <td class="price">${coin['price']:,.4f}</td>
                <td class="change" style="color:{'#00ff88' if coin['change']>0 else '#ff3366'};{glow}">
                    {'+' if coin['change']>0 else ''}{coin['change']:.2f}%
                </td>
            </tr>"""
        update_text = last_update

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🚀 ICT SMART PRO - PUMP RADAR</title>
    <link href="https://fonts.bunny.net/css?family=orbitron:900|rajdhani:700|exo-2:600" rel="stylesheet">
    <style>
        :root {{ --bg: linear-gradient(135deg, #0a0022 0%, #1a0033 50%, #000000 100%); --primary: #00ffff; --green: #00ff88; --red: #ff0044; --gold: #ffd700; }}
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ background: var(--bg); color: white; font-family: 'Rajdhani', sans-serif; min-height: 100vh; overflow-x: hidden; background-attachment: fixed; }}
        header {{ text-align:center; padding: 30px 10px; position:relative; z-index:10; }}
        .logo {{ width:140px; border-radius:50%; border: 4px solid var(--primary); box-shadow: 0 0 50px #00ffff88; animation: float 6s ease-in-out infinite; }}
        h1 {{ font-family: 'Orbitron', sans-serif; font-size: 5rem; background: linear-gradient(90deg, #00dbde, #fc00ff, #00dbde); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-size: 200%; animation: gradient 8s ease infinite; margin: 20px 0; text-shadow: 0 0 40px #ff00ff88; }}
        @keyframes gradient {{ 0% {{background-position:0%}} 100% {{background-position:200%}} }}
        @keyframes float {{ 0%,100% {{transform:translateY(0)}} 50% {{transform:translateY(-20px)}} }}
        .update {{ font-size:1.8rem; color:var(--primary); text-shadow:0 0 20px var(--primary); margin:15px 0; }}
        table {{ width: 96%; max-width: 1100px; margin: 30px auto; border-collapse: separate; border-spacing: 0 12px; }}
        th {{ background: linear-gradient(45deg, #ff00ff33, #00ffff33); padding: 20px; font-size: 1.8rem; backdrop-filter: blur(10px); border: 1px solid #ff00ff44; }}
        .coin-row {{ background: linear-gradient(90deg, #ffffff08, #00ffff08); border: 1px solid #00ffff33; transition: all 0.4s; cursor: pointer; }}
        .coin-row:hover {{ transform: translateY(-8px) scale(1.02); box-shadow: 0 20px 40px #00ffff44; border-color: var(--primary); }}
        .coin-row td {{ padding: 22px 15px; text-align: center; font-size: 1.6rem; }}
        .rank {{ font-size: 3rem; font-weight: bold; color: var(--gold); text-shadow: 0 0 20px var(--gold); }}
        .symbol {{ font-size: 2.2rem; color:var(--primary); font-weight: bold; }}
        .price {{ color: var(--gold); }}
        .change {{ font-size: 2.4rem; font-weight: bold; animation: pulse 1.5s infinite; }}
        @keyframes pulse {{ 0%,100% {{transform:scale(1)}} 50% {{transform:scale(1.1)}} }}
        .signal-btn {{ display: block; margin: 60px auto; padding: 22px 60px; font-size: 2.4rem; font-weight: bold; background: linear-gradient(45deg, #fc00ff, #00dbde); color: white; border: none; border-radius: 50px; cursor: pointer; box-shadow: 0 0 60px #ff00ff88; animation: btnGlow 3s infinite; transition: all 0.3s; text-decoration:none; }}
        .signal-btn:hover {{ transform: scale(1.1); box-shadow: 0 0 100px #ff00ff; }}
        @keyframes btnGlow {{ 0%,100% {{box-shadow:0 0 60px #ff00ff88}} 50% {{box-shadow:0 0 100px #ff00ff}} }}
        footer {{ text-align:center; padding:30px; color:#00ffff88; font-size:1.2rem; }}
    </style>
</head>
<body>
    <header>
        <img src="/assets/logo.png" class="logo" onerror="this.style.display='none'">
        <h1>PUMP RADAR</h1>
        <div class="update">Son Güncelleme: <strong>{update_text}</strong></div>
    </header>

    <table>
        <thead><tr><th>SIRA</th><th>COIN</th><th>FİYAT</th><th>24S DEĞİŞİM</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>

    <a href="/signal" class="signal-btn">🚀 CANLI SİNYAL ROBOTU 🚀</a>

    <footer>© 2025 ICT Smart Pro - En Hızlı Pump Radar</footer>
</body>
</html>"""

# --- CANLI SİNYAL SAYFASI ---
@app.get("/signal", response_class=HTMLResponse)
async def signal_page():
    return """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ICT Smart Pro - Canlı Sinyal Robotu</title>
    <link href="https://fonts.bunny.net/css?family=orbitron:900|rajdhani:700" rel="stylesheet">
    <style>
        body {margin:0; padding:20px; background:linear-gradient(135deg,#0a0022,#1a0033,#000); color:#fff; font-family:'Rajdhani'; text-align:center; min-height:100vh;}
        h1 {font-family:'Orbitron'; font-size:4.5rem; background:linear-gradient(90deg,#00dbde,#fc00ff); -webkit-background-clip:text; -webkit-text-fill-color:transparent; animation:gradient 6s infinite;}
        @keyframes gradient {0%{background-position:0%}100%{background-position:200%}}
        .card {max-width:600px; margin:40px auto; background:#ffffff0d; padding:40px; border-radius:30px; border:2px solid #00ffff44; box-shadow:0 0 80px #00ffff33; backdrop-filter:blur(10px);}
        input, select, button {width:100%; padding:18px; margin:15px 0; font-size:1.6rem; border:none; border-radius:15px;}
        input, select {background:#333; color:#fff;}
        button {background:linear-gradient(45deg,#fc00ff,#00dbde); color:white; cursor:pointer; font-weight:bold; font-size:2rem; transition:0.4s;}
        button:hover {transform:scale(1.05); box-shadow:0 0 60px #ff00ff;}
        .result {margin-top:40px; padding:30px; background:#00000099; border-radius:20px; font-size:2rem; min-height:200px; border:3px solid transparent; line-height:1.6;}
        .green {border-color:#00ff88; box-shadow:0 0 60px #00ff8844;}
        .red {border-color:#ff0044; box-shadow:0 0 60px #ff004444;}
        .orange {border-color:#ffd700; box-shadow:0 0 60px #ffd70044;}
        .back {margin:50px; font-size:1.6rem;}
        .back a {color:#00dbde; text-decoration:none;}
        .status {font-size:1.4rem; color:#00ffff; margin:10px 0;}
    </style>
</head>
<body>
    <h1>CANLI SİNYAL ROBOTU</h1>
    <div class="card">
        <form id="form">
            <input type="text" id="pair" placeholder="Coin (örn: BNBUSDT)" value="BNBUSDT" required>
            <select id="tf" style="display:none"><option value="realtime">Gerçek Zamanlı</option></select>
            <button type="submit">🔴 CANLI BAĞLANTI KUR</button>
        </form>
        <div class="status" id="status">Bağlantı bekleniyor...</div>
        <div id="result" class="result">Sinyal burada <strong>gerçek zamanlı</strong> olarak güncellenecek...</div>
    </div>
    <div class="back"><a href="/">← Pump Radara Dön</a></div>

    <script>
        let socket = null;

        document.getElementById('form').onsubmit = e => {
            e.preventDefault();
            if (socket) socket.close();

            const pair = document.getElementById('pair').value.trim().toUpperCase();
            const res = document.getElementById('result');
            const status = document.getElementById('status');

            status.textContent = "🚀 CANLI BAĞLANTI KURULUYOR...";
            status.style.color = "#00dbde";
            res.innerHTML = "<p style='color:#ffd700'>İlk sinyal yükleniyor...</p>";

            const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
            socket = new WebSocket(`${protocol}://${location.host}/ws/signal/${pair}/realtime`);

            socket.onopen = () => {
                status.textContent = "✅ GERÇEK ZAMANLI AKIŞ AÇIK!";
                status.style.color = "#00ff88";
            };

            socket.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.error) {
                    res.innerHTML = `<p style="color:#ff6666; font-size:2.2rem;">❌ Hata:<br>${data.error}</p>`;
                    res.classList.add('red');
                    return;
                }

                let colorClass = 'orange';
                let signalColor = '#ffd700';
                if (data.signal.includes('ALIM') || data.signal.includes('YUKARI')) {
                    colorClass = 'green';
                    signalColor = '#00ff88';
                } else if (data.signal.includes('SATIM') || data.signal.includes('AŞAĞI')) {
                    colorClass = 'red';
                    signalColor = '#ff4444';
                }

                res.className = 'result ' + colorClass;
                res.innerHTML = `
                    <h2 style="font-size:3.8rem; color:${signalColor}; margin:15px 0;">${data.signal}</h2>
                    <p><strong>${data.pair}</strong> — <em>${data.last_update}</em></p>
                    <p>Fiyat: <strong>$${data.current_price}</strong></p>
                    <p>Momentum: <strong>${data.momentum === 'up' ? '⬆️' : data.momentum === 'down' ? '⬇️' : '↔️'} ${
                        data.volume_spike ? ' + 💥 HACİM' : ''
                    }</strong></p>
                    <p><em style="color:#00ffff;">Saniyede 2 kez güncelleniyor ↺</em></p>
                `;
            };

            socket.onerror = () => {
                status.textContent = "⚠️ Bağlantı hatası!";
                status.style.color = "#ff4444";
            };

            socket.onclose = () => {
                status.textContent = "❌ BAĞLANTI KESİLDİ";
                status.style.color = "#ff6666";
            };
        };
    </script>
</body>
</html>"""

# --- SAĞLIK KONTROLÜ ---
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "active_subscriptions": sum(len(ws_set) for ws_set in rt_ticker.subscribers.values()),
        "tracked_symbols": list(rt_ticker.subscribers.keys()),
        "tickers_active": len(rt_ticker.tickers),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
