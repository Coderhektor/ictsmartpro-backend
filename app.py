from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx
import asyncio
from datetime import datetime

# SİNYAL İÇİN GEREKLİ KÜTÜPHANELER
import ccxt
import pandas as pd
import pandas_ta as ta

app = FastAPI()
app.mount("/assets", StaticFiles(directory=".", html=False), name="assets")

top_gainers = []
last_update = "Başlatılıyor..."

# Binance bağlantısı (sinyal için)
exchange = ccxt.binance({'enableRateLimit': True})

# ====================== PUMP RADAR VERİ ÇEKME ======================
async def fetch_data():
    global top_gainers, last_update
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            binance_urls = [
                "https://data.binance.com/api/v3/ticker/24hr",
                "https://data-api.binance.vision/api/v3/ticker/24hr",
                "https://api1.binance.com/api/v3/ticker/24hr",
                "https://api2.binance.com/api/v3/ticker/24hr",
                "https://api3.binance.com/api/v3/ticker/24hr",
            ]
            binance_data = None
            for url in binance_urls:
                try:
                    response = await client.get(url, timeout=10)
                    if response.status_code == 200:
                        binance_data = response.json()
                        print(f"Binance veri alındı: {url}")
                        break
                except:
                    continue

            if not binance_data or not isinstance(binance_data, list):
                print("Binance başarısız, CoinGecko'ya geçiliyor...")
                resp1 = await client.get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=percent_change_24h_desc&per_page=250&page=1")
                resp2 = await client.get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=percent_change_24h_desc&per_page=250&page=2")
                coingecko_data = resp1.json() + resp2.json() if resp1.status_code == 200 and resp2.status_code == 200 else []
            else:
                coingecko_data = []

            clean_coins = []
            if binance_data:
                for item in binance_data:
                    if not isinstance(item, dict): continue
                    symbol = item.get("symbol", "")
                    if not symbol.endswith("USDT"): continue
                    try:
                        price = float(item.get("lastPrice", 0))
                        change = float(item.get("priceChangePercent", 0))
                        volume = float(item.get("quoteVolume", 0))
                        if price > 0 and volume >= 1_000_000:
                            clean_coins.append({"symbol": symbol.replace("USDT", "/USDT"), "price": price, "change": change})
                    except: continue

            for item in coingecko_data:
                try:
                    sym = item.get("symbol", "").upper()
                    price = float(item.get("current_price", 0))
                    change = float(item.get("price_change_percentage_24h") or 0)
                    volume = float(item.get("total_volume", 0))
                    if price > 0 and volume >= 1_000_000:
                        if not any(c["symbol"].startswith(sym) for c in clean_coins):
                            clean_coins.append({"symbol": f"{sym}/USDT", "price": price, "change": change})
                except: continue

            top_gainers = sorted(clean_coins, key=lambda x: x["change"], reverse=True)[:10]
            last_update = datetime.now().strftime("%H:%M:%S")
            print(f"{len(top_gainers)} coin yüklendi – {last_update}")

    except Exception as e:
        print("Genel hata:", e)

@app.on_event("startup")
async def startup():
    await fetch_data()
    async def loop():
        while True:
            await asyncio.sleep(9)
            await fetch_data()
    asyncio.create_task(loop())
# ====================== SİNYAL SAYFASI (EKSİK OLAN KISIM!) ======================
@app.get("/signal", response_class=HTMLResponse)
async def signal_page():
    return f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ICT Smart Pro – Sinyal Sorgula</title>
        <style>
            body{{margin:0;padding:20px;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);color:#fff;font-family:Arial;text-align:center;min-height:100vh}}
            h1{{font-size:3.5rem;background:linear-gradient(90deg,#00dbde,#fc00ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
            .container{{max-width:600px;margin:40px auto;background:#00000099;padding:30px;border-radius:20px;box-shadow:0 0 40px #00ff8844}}
            input, select, button{{width:100%;padding:15px;margin:10px 0;font-size:1.4rem;border:none;border-radius:10px}}
            input, select{{background:#333;color:#fff}}
            button{{background:linear-gradient(90deg,#fc00ff,#00dbde);color:white;cursor:pointer;font-weight:bold}}
            .result{{margin-top:30px;padding:20px;background:#000000cc;border-radius:15px;font-size:1.6rem}}
            .back a{{color:#00dbde;font-size:1.4rem;text-decoration:none}}
        </style>
    </head>
    <body>
        <h1>SİNYAL SORGULA</h1>
        <div class="container">
            <form id="signalForm">
                <input type="text" id="pair" placeholder="Coin Çifti (ör: BTCUSDT)" value="BTCUSDT" required>
                <select id="timeframe">
                    <option value="5m">5 Dakika</option>
                    <option value="15m">15 Dakika</option>
                    <option value="30m">30 Dakika</option>
                    <option value="1h" selected>1 Saat</option>
                    <option value="4h">4 Saat</option>
                    <option value="1d">1 Gün</option>
                    <option value="1w">1 Hafta</option>
                </select>
                <button type="submit">SİNYAL AL</button>
            </form>
            <div id="result" class="result" style="display:none"></div>
        </div>
        <div class="back" style="margin-top:40px;"><a href="/">← Ana Sayfaya Dön</a></div>
        <script>
            document.getElementById('signalForm').addEventListener('submit', async (e) => {{
                e.preventDefault();
                const pair = document.getElementById('pair').value.trim().toUpperCase();
                const timeframe = document.getElementById('timeframe').value;
                const resultDiv = document.getElementById('result');
                resultDiv.style.display = 'block';
                resultDiv.innerHTML = '<p style="color:#ffd700">Hesaplanıyor...</p>';
                try {{
                    const resp = await fetch(`/api/signal?pair=${{pair}}&timeframe=${{timeframe}}`);
                    const data = await resp.json();
                    if (data.error) {{
                        resultDiv.innerHTML = `<p style="color:#ff4444">HATA: ${{data.error}}</p>`;
                        return;
                    }}
                    const color = data.signal_color === 'green' ? '#00ff88' : 
                                  data.signal_color === 'lightgreen' ? '#90EE90' : 
                                  data.signal_color === 'red' ? '#ff4444' : '#ffd700';
                    resultDiv.innerHTML = `
                        <h2 style="color:${{color}}">${{data.signal}}</h2>
                        <p><strong>${{data.pair}} - ${{data.timeframe}}</strong></p>
                        <p>Fiyat: <strong>$${data.current_price}</strong></p>
                        <p>EMA 21: <strong>${{data.ema_21 ?? 'Hesaplanıyor'}}</strong></p>
                        <p>RSI 14: <strong>${{data.rsi_14 ?? 'Hesaplanıyor'}}</strong></p>
                        <p>Son Mum: ${{data.last_candle}}</p>
                    `;
                }} catch {{
                    resultDiv.innerHTML = '<p style="color:#ff4444">Bağlantı hatası!</p>';
                }}
            }});
        </script>
    </body>
    </html>
    """
