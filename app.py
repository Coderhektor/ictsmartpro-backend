from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx
import asyncio
from datetime import datetime

# Sinyal kısmı için gerekli importlar
import ccxt
import pandas as pd
import pandas_ta as ta

app = FastAPI()

# Statik dosyalar (logo vs.)
app.mount("/assets", StaticFiles(directory=".", html=False), name="assets")

# Global değişkenler (Pump Radar için)
top_gainers = []
last_update = "Başlatılıyor..."

# ccxt ile Binance bağlantısı (sinyal için)
exchange = ccxt.binance({
    'enableRateLimit': True,
})

# ====================== PUMP RADAR VERİ ÇEKME ======================
async def fetch_data():
    global top_gainers, last_update
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Binance alternatif endpoint'leri (en stabil olanlar)
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

            # Binance başarısızsa CoinGecko'ya fallback
            if not binance_data or not isinstance(binance_data, list):
                print("Binance başarısız, CoinGecko'ya geçiliyor...")
                resp1 = await client.get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=percent_change_24h_desc&per_page=250&page=1")
                resp2 = await client.get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=percent_change_24h_desc&per_page=250&page=2")
                if resp1.status_code == 200 and resp2.status_code == 200:
                    coingecko_data = resp1.json() + resp2.json()
                    print("CoinGecko veri alındı")
                else:
                    coingecko_data = []
            else:
                coingecko_data = []

            clean_coins = []

            # Binance verisini öncelikli kullan
            if binance_data:
                for item in binance_data:
                    if not isinstance(item, dict):
                        continue
                    symbol = item.get("symbol", "")
                    if not symbol or not symbol.endswith("USDT"):
                        continue
                    try:
                        price = float(item.get("lastPrice", 0))
                        change = float(item.get("priceChangePercent", 0))
                        volume = float(item.get("quoteVolume", 0))
                        if price > 0 and volume >= 1_000_000:
                            clean_coins.append({
                                "symbol": symbol.replace("USDT", "/USDT"),
                                "price": price,
                                "change": change
                            })
                    except:
                        continue

            # CoinGecko'yu ekle (tekrar önlemek için basit kontrol)
            for item in coingecko_data:
                try:
                    sym = item.get("symbol", "").upper()
                    if not sym:
                        continue
                    price = float(item.get("current_price", 0))
                    change = float(item.get("price_change_percentage_24h") or 0)
                    volume = float(item.get("total_volume", 0))
                    if price > 0 and volume >= 1_000_000:
                        if not any(c["symbol"].startswith(sym) for c in clean_coins):
                            clean_coins.append({
                                "symbol": f"{sym}/USDT",
                                "price": price,
                                "change": change
                            })
                except:
                    continue

            # En iyi 10'u sırala
            top_gainers = sorted(clean_coins, key=lambda x: x["change"], reverse=True)[:10]
            last_update = datetime.now().strftime("%H:%M:%S")
            print(f"{len(top_gainers)} coin yüklendi – {last_update}")

    except Exception as e:
        print("Genel hata (fetch_data):", e)

# ====================== UYGULAMA BAŞLANGICI ======================
@app.on_event("startup")
async def startup():
    await fetch_data()  # İlk açılışta hemen çek
    async def loop():
        while True:
            await asyncio.sleep(9)  # Her 9 saniyede güncelle
            await fetch_data()
    asyncio.create_task(loop())

# ====================== ANA SAYFA (PUMP RADAR) ======================
@app.get("/", response_class=HTMLResponse)
async def ana_sayfa():
    mesaj = f"Son Güncelleme: {last_update}" if top_gainers else "Veri yükleniyor... (10 saniye içinde gelecek)"

    rows = ""
    for i, coin in enumerate(top_gainers or [], 1):
        renk = "#00ff88" if coin["change"] > 0 else "#ff4444"
        rows += f"""
        <tr>
            <td class="sira">{i}</td>
            <td class="coin">{coin['symbol']}</td>
            <td class="fiyat">${coin['price']:,.4f}</td>
            <td style="color:{renk};font-weight:bold;font-size:1.6rem">{coin['change']:+.2f}%</td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="4" style="color:#ff9900;font-size:2rem">Veri geliyor, biraz bekle...</td></tr>'

    return f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ICT Smart Pro – PUMP RADARI</title>
        <style>
            body{{margin:0;padding:20px;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);color:#fff;font-family:Arial;text-align:center}}
            h1{{font-size:4.5rem;background:linear-gradient(90deg,#00dbde,#fc00ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
            table{{width:98%;max-width:1100px;margin:30px auto;background:#00000088;border-radius:20px;overflow:hidden;box-shadow:0 0 40px #00ff8844}}
            th{{background:linear-gradient(90deg,#fc00ff,#00dbde);padding:20px;font-size:1.7rem}}
            td{{padding:18px;font-size:1.5rem}}
            .sira{{font-size:2.8rem;color:#00ff88;text-shadow:0 0 20px #00ff88}}
            .coin{{font-size:2rem;color:#00dbde;font-weight:bold}}
            .fiyat{{color:#ffd700}}
            img{{width:150px;border-radius:20px;animation:pulse 3s infinite}}
            .info{{font-size:1.5rem;color:#00ff88;margin:20px}}
            @keyframes pulse{{0%,100%{{transform:scale(1)}}50%{{transform:scale(1.1)}}}}
        </style>
    </head>
    <body>
        <img src="/assets/logo.png" onerror="this.style.display='none'">
        <h1>PUMP RADARI</h1>
        <div class="info">{mesaj}</div>
        <table>
            <tr><th>SIRA</th><th>COIN</th><th>FİYAT</th><th>24 SAAT</th></tr>
            {rows}
        </table>

        <div style="margin:60px auto; text-align:center;">
            <a href="/signal" style="background:linear-gradient(90deg,#fc00ff,#00dbde); color:white; padding:20px 50px; font-size:2.2rem; text-decoration:none; border-radius:20px; display:inline-block; box-shadow:0 0 40px #00ff88; transition:0.3s;">
                🚀 SİNYAL SORGULA 🚀
            </a>
        </div>

        <script>
            setTimeout(()=>location.reload(), 9000);
        </script>
    </body>
    </html>
    """

# ====================== SİNYAL API ======================
@app.get("/api/signal")
async def api_signal(pair: str = "BTCUS ضدT", timeframe: str = "1h"):
    pair = pair.upper().replace("/", "").replace(" ", "")
    try:
        valid_tf = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w']
        if timeframe not in valid_tf:
            return {"error": f"Geçersiz timeframe. Desteklenenler: {', '.join(valid_tf)}"}

        ohlcv = await asyncio.to_thread(exchange.fetch_ohlcv, pair, timeframe, limit=100)
        if not ohlcv or len(ohlcv) == 0:
            return {"error": "Bu pair için veri bulunamadı. Örnek: BTCUSDT, ETHUSDT"}

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        df['EMA_21'] = ta.ema(df['close'], length=21)
        df['RSI_14'] = ta.rsi(df['close'], length=14)

        latest = df.iloc[-1]
        current_price = latest['close']
        ema_21 = latest['EMA_21']
        rsi_14 = latest['RSI_14']

        if pd.isna(ema_21) or pd.isna(rsi_14):
            signal = "Yetersiz veri (daha fazla mum gerekiyor)"
            color = "orange"
        elif current_price > ema_21 and rsi_14 < 30:
            signal = "🔥 GÜÇLÜ ALIM SİNYALİ 🔥"
            color = "green"
        elif current_price > ema_21 and rsi_14 < 45:
            signal = "ALIM FIRSATI (Yükseliş trendi + RSI düşük)"
            color = "lightgreen"
        elif current_price < ema_21 and rsi_14 > 70:
            signal = "SATIM SİNYALİ (Aşırı alım)"
            color = "red"
        else:
            signal = "BEKLE (Net sinyal yok)"
            color = "gray"

        return {
            "pair": pair.replace("USDT", "/USDT"),
            "timeframe": timeframe,
            "current_price": round(current_price, 6),
            "ema_21": round(ema_21, 6) if not pd.isna(ema_21) else None,
            "rsi_14": round(rsi_14, 2) if not pd.isna(rsi_14) else None,
            "signal": signal,
            "signal_color": color,
            "last_candle": latest['timestamp'].strftime("%d.%m.%Y %H:%M")
        }

    except Exception as e:
        return {"error": f"Hata: {str(e)}"}

# ====================== SİNYAL SAYFASI ======================
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
            h1{{font-size:3.5rem;background:linear-gradient(90deg,#00dbde,#fc00ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:10px}}
            .container{{max-width:600px;margin:40px auto;background:#00000099;padding:30px;border-radius:20px;box-shadow:0 0 40px #00ff8844}}
            input, select, button{{width:100%;padding:15px;margin:10px 0;font-size:1.4rem;border:none;border-radius:10px}}
            input, select{{background:#333;color:#fff}}
            button{{background:linear-gradient(90deg,#fc00ff,#00dbde);color:white;cursor:pointer;font-weight:bold}}
            button:hover{{transform:scale(1.05);transition:0.3s}}
            .result{{margin-top:30px;padding:20px;background:#000000cc;border-radius:15px;font-size:1.6rem}}
            .back{{margin-top:40px}}
            .back a{{color:#00dbde;font-size:1.4rem;text-decoration:none}}
            .back a:hover{{text-decoration:underline}}
        </style>
    </head>
    <body>
        <h1>SİNYAL SORGULA</h1>
        <div class="container">
            <form id="signalForm">
                <input type="text" id="pair" placeholder="Coin Çifti (örneğin: BTCUSDT)" value="BTCUSDT" required>
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

        <div class="back">
            <a href="/">← Ana Sayfaya Dön (Pump Radar)</a>
        </div>

        <script>
            document.getElementById('signalForm').addEventListener('submit', async (e) => {{
                e.preventDefault();
                const pair = document.getElementById('pair').value.trim().toUpperCase();
                const timeframe = document.getElementById('timeframe').value;
                const resultDiv = document.getElementById('result');
                resultDiv.style.display = 'block';
                resultDiv.innerHTML = '<p style="color:#ffd700">Sinyal hesaplanıyor...</p>';

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
                        <p><strong>${{data.pair}}</strong> - ${{data.timeframe}}</p>
                        <p>Fiyat: <strong>$${data.current_price}</strong></p>
                        <p>EMA 21: <strong>${{data.ema_21 !== null ? data.ema_21 : 'Hesaplanıyor'}}</strong></p>
                        <p>RSI 14: <strong>${{data.rsi_14 !== null ? data.rsi_14 : 'Hesaplanıyor'}}</strong></p>
                        <p>Son Mum: ${{data.last_candle}}</p>
                    `;
                }} catch (err) {{
                    resultDiv.innerHTML = `<p style="color:#ff4444">Bağlantı hatası!</p>`;
                }}
            }});
        </script>
    </body>
    </html>
    """