import ccxt
import pandas as pd
import pandas_ta as ta
import asyncio
import httpx
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import time
import os

app = FastAPI()
app.mount("/assets", StaticFiles(directory=".", html=False), name="assets")

# Global değişkenler
top_gainers = []
last_update = "Başlatılıyor..."
exchange = ccxt.binance({'enableRateLimit': True})

# Aktif WebSocket bağlantıları
active_connections: dict[str, WebSocket] = {}

# OHLCV cache (performans için)
ohlcv_cache: dict[str, tuple[list, float]] = {}
MAX_CACHE_SIZE = 50

# Log dosyası
LOG_FILE = "/data/all_signals.csv"

async def fetch_data():
    global top_gainers, last_update
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            binance_urls = [
                "https://data.binance.com/api/v3/ticker/24hr",
                "https://data-api.binance.vision/api/v3/ticker/24hr",
                "https://api1.binance.com/api/v3/ticker/24hr",
            ]
            binance_data = None
            for url in binance_urls:
                try:
                    resp = await client.get(url, timeout=10)
                    if resp.status_code == 200:
                        binance_data = resp.json()
                        break
                except:
                    continue

            if not binance_data:
                r1 = await client.get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=percent_change_24h_desc&per_page=250&page=1")
                r2 = await client.get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=percent_change_24h_desc&per_page=250&page=2")
                coingecko_data = (r1.json() + r2.json()) if r1.status_code == 200 and r2.status_code == 200 else []
            else:
                coingecko_data = []

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

            for item in coingecko_data:
                try:
                    sym = item["symbol"].upper()
                    if any(c["symbol"].startswith(sym) for c in clean_coins): continue
                    price = item["current_price"]
                    change = item["price_change_percentage_24h"] or 0
                    volume = item["total_volume"]
                    if volume >= 1_000_000:
                        clean_coins.append({"symbol": f"{sym}/USDT", "price": price, "change": change})
                except: continue

            top_gainers = sorted(clean_coins, key=lambda x: x["change"], reverse=True)[:10]
            last_update = datetime.now().strftime("%H:%M:%S")
    except Exception as e:
        print("Pump Radar veri hatası:", e)
        last_update = "Bağlantı Hatası"

@app.on_event("startup")
async def startup():
    await fetch_data()
    
    async def radar_loop():
        while True:
            await asyncio.sleep(30)
            await fetch_data()
    asyncio.create_task(radar_loop())

    async def signal_broadcaster():
        while True:
            await asyncio.sleep(15)
            for key, ws in list(active_connections.items()):
                try:
                    pair, timeframe = key.split("_", 1)
                    result = await calculate_signal(pair, timeframe)
                    if result and "error" not in result:
                        await ws.send_json(result)
                except Exception as e:
                    print(f"Broadcast hatası ({key}): {e}")
                    try:
                        await ws.close()
                    except:
                        pass
                    active_connections.pop(key, None)

    asyncio.create_task(signal_broadcaster())

async def calculate_signal(original_pair: str, timeframe: str):
    global ohlcv_cache
    pair = original_pair.upper().replace("/", "").replace(" ", "").replace("-", "")
    if not pair.endswith("USDT"):
        if not (pair.endswith("UP") or pair.endswith("DOWN")):
            pair += "USDT"

    cache_key = f"{pair}_{timeframe}"
    current_time = time.time()

    try:
        valid_timeframes = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d','3d','1w','1M']
        if timeframe not in valid_timeframes:
            return {"error": "Geçersiz zaman dilimi"}

        # Cache kontrol
        if cache_key in ohlcv_cache:
            cached_ohlcv, cached_time = ohlcv_cache[cache_key]
            if current_time - cached_time < 30:
                ohlcv = cached_ohlcv
            else:
                ohlcv = await asyncio.to_thread(exchange.fetch_ohlcv, pair, timeframe, limit=100)
                ohlcv_cache[cache_key] = (ohlcv, current_time)
        else:
            ohlcv = await asyncio.to_thread(exchange.fetch_ohlcv, pair, timeframe, limit=100)
            ohlcv_cache[cache_key] = (ohlcv, current_time)

        # Cache temizleme
        if len(ohlcv_cache) > MAX_CACHE_SIZE:
            oldest = min(ohlcv_cache, key=lambda k: ohlcv_cache[k][1])
            del ohlcv_cache[oldest]

        if not ohlcv or len(ohlcv) < 50:
            return {"error": "Veri yetersiz"}

        df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','volume'])
        df['EMA21'] = ta.ema(df['close'], length=21)
        df['RSI14'] = ta.rsi(df['close'], length=14)
        
        last = df.iloc[-1]
        price = float(last['close'])
        ema = last['EMA21']
        rsi = last['RSI14']

        if pd.isna(ema) or pd.isna(rsi):
            signal = "Yetersiz Veri"
        elif price > ema and rsi < 30:
            signal = "🔥 ÇOK GÜÇLÜ ALIM 🔥"
        elif price > ema and rsi < 45:
            signal = "🚀 ALIM SİNYALİ 🚀"
        elif price < ema and rsi > 70:
            signal = "⚠️ SATIM SİNYALİ ⚠️"
        elif price < ema and rsi > 55:
            signal = "⚡ ZAYIF SATIŞ UYARISI ⚡"
        else:
            signal = "😐 NÖTR / BEKLEMEDE"

        result = {
            "pair": original_pair.replace("USDT", "/USDT") if "/" not in original_pair else original_pair,
            "timeframe": timeframe,
            "current_price": round(price, 8),
            "ema_21": round(ema, 8) if not pd.isna(ema) else None,
            "rsi_14": round(rsi, 2) if not pd.isna(rsi) else None,
            "signal": signal,
            "last_candle": pd.to_datetime(last['ts'], unit='ms').strftime("%d.%m %H:%M")
        }

        # Log kaydet
        try:
            if os.path.exists("/data"):
                os.makedirs("/data", exist_ok=True)
                if not os.path.exists(LOG_FILE):
                    df.head(1).to_csv(LOG_FILE, index=False)
                df.tail(1).to_csv(LOG_FILE, mode='a', header=False, index=False)
        except Exception as e:
            print(f"Log hatası: {e}")

        return result

    except Exception as e:
        print(f"Sinyal hatası ({original_pair} {timeframe}): {e}")
        return {"error": "Teknik hata"}

@app.websocket("/ws/signal/{pair}/{timeframe}")
async def websocket_endpoint(websocket: WebSocket, pair: str, timeframe: str):
    await websocket.accept()
    key = f"{pair.upper()}_{timeframe}"
    active_connections[key] = websocket

    try:
        result = await calculate_signal(pair, timeframe)
        if result:
            await websocket.send_json(result)
    except:
        pass

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.pop(key, None)
    except:
        active_connections.pop(key, None)

# ====================== ANA SAYFA ======================
@app.get("/", response_class=HTMLResponse)
async def ana_sayfa():
    if not top_gainers:
        rows = '<tr><td colspan="4" style="font-size:2.4rem;color:#ff4444;padding:80px;text-align:center;">🚨 Veri çekilemedi!<br><br>Binance veya CoinGecko bağlantısında sorun var.<br>Lütfen biraz sonra tekrar deneyin.</td></tr>'
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

# ====================== CANLI SİNYAL SAYFASI ======================
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
            <input type="text" id="pair" placeholder="Coin (örn: BTCUSDT)" value="BTCUSDT" required>
            <select id="tf">
                <option value="5m">5 Dakika</option>
                <option value="15m">15 Dakika</option>
                <option value="30m">30 Dakika</option>
                <option value="1h" selected>1 Saat</option>
                <option value="4h">4 Saat</option>
                <option value="1d">1 Gün</option>
                <option value="1w">1 Hafta</option>
            </select>
            <button type="submit">🔴 CANLI BAĞLANTI KUR</button>
        </form>
        <div class="status" id="status">Bağlantı bekleniyor...</div>
        <div id="result" class="result">Sinyal burada canlı olarak güncellenecek...</div>
    </div>
    <div class="back"><a href="/">← Pump Radara Dön</a></div>

    <script>
        let socket = null;

        document.getElementById('form').onsubmit = e => {
            e.preventDefault();
            if (socket) socket.close();

            const pair = document.getElementById('pair').value.trim().toUpperCase();
            const tf = document.getElementById('tf').value;
            const res = document.getElementById('result');
            const status = document.getElementById('status');

            status.textContent = "Bağlantı kuruluyor...";
            status.style.color = "#ffd700";
            res.innerHTML = "<p style='color:#ffd700'>İlk sinyal yükleniyor...</p>";

            const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
            socket = new WebSocket(`${protocol}://${location.host}/ws/signal/${pair}/${tf}`);

            socket.onopen = () => {
                status.textContent = "✅ CANLI BAĞLANTI AKTİF!";
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
                if (data.signal.includes('ALIM') || data.signal.includes('GÜÇLÜ')) {
                    colorClass = 'green';
                    signalColor = '#00ff88';
                } else if (data.signal.includes('SAT')) {
                    colorClass = 'red';
                    signalColor = '#ff4444';
                }

                res.className = 'result ' + colorClass;
                res.innerHTML = `
                    <h2 style="font-size:3.8rem; color:${signalColor}; margin:15px 0;">${data.signal}</h2>
                    <p><strong>${data.pair} - ${data.timeframe}</strong></p>
                    <p>Fiyat: <strong>$${data.current_price}</strong></p>
                    <p>EMA21: <strong>${data.ema_21 ?? '-'} | RSI14: ${data.rsi_14 ?? '-'}</strong></p>
                    <p>Son Mum: ${data.last_candle} <em style="color:#00ffff;">(canlı güncelleniyor ↺)</em></p>
                `;
            };

            socket.onerror = () => {
                status.textContent = "Bağlantı hatası!";
                status.style.color = "#ff4444";
            };

            socket.onclose = () => {
                status.textContent = "Bağlantı kapandı. Yeniden bağlan.";
                status.style.color = "#ff6666";
            };
        };
    </script>
</body>
</html>"""

@app.get("/health")
async def health_check():
    return {"status": "healthy", "active_ws": len(active_connections), "cache_size": len(ohlcv_cache)}
