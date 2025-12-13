# main.py'nin en başına EKLEYİN (app = FastAPI() tanımından önce/sonra farketmez, ama önce tercih edilir)
import ccxt
import pandas as pd
import pandas_ta as ta
import asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx
import asyncio
from datetime import datetime

app = FastAPI()
app.mount("/assets", StaticFiles(directory=".", html=False), name="assets")

top_gainers = []
last_update = "Başlatılıyor..."

async def fetch_data():
    global top_gainers, last_update
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # 1. Önce Binance alternatif endpoint'lerini dene (en hızlı olanlar)
            binance_urls = [
                "https://data.binance.com/api/v3/ticker/24hr",          # En stabil
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

            # 2. Binance başarısızsa veya hiç veri gelmediyse → CoinGecko'ya geç
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

            # 3. Verileri birleştir ve temizle
            clean_coins = []

            # Binance verisi varsa öncelikli kullan
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
                        if price > 0 and volume >= 1_000_000:  # 1M USDT hacim
                            clean_coins.append({
                                "symbol": symbol.replace("USDT", "/USDT"),
                                "price": price,
                                "change": change,
                                "source": "Binance"  # Opsiyonel: kaynağını gösterebiliriz
                            })
                    except:
                        continue

            # Binance yoksa veya az veri geldiyse CoinGecko'yu ekle (tekrar olmasın diye kontrol edebilirsin ama gerek yok)
            for item in coingecko_data:
                try:
                    sym = item.get("symbol", "").upper()
                    if not sym:
                        continue
                    price = float(item.get("current_price", 0))
                    change = float(item.get("price_change_percentage_24h") or 0)
                    volume = float(item.get("total_volume", 0))
                    if price > 0 and volume >= 1_000_000:
                        # Binance'te yoksa ekle (tekrar önlemek için basit kontrol)
                        if not any(c["symbol"].startswith(sym) for c in clean_coins):
                            clean_coins.append({
                                "symbol": f"{sym}/USDT",
                                "price": price,
                                "change": change,
                                "source": "CoinGecko"
                            })
                except:
                    continue

            # Sırala ve ilk 10'u al
            top_gainers = sorted(clean_coins, key=lambda x: x["change"], reverse=True)[:10]
            last_update = datetime.now().strftime("%H:%M:%S")
            print(f"{len(top_gainers)} coin yüklendi – {last_update} (Kaynak: {'Binance' if binance_data else 'CoinGecko'})")

    except Exception as e:
        print("Genel hata:", e)

# Uygulama başladığında hemen veri çek + sonra her 9 saniyede bir
@app.on_event("startup")
async def startup():
    await fetch_data()  # ilk açılışta hemen çek
    async def loop():
        while True:
            await asyncio.sleep(9)
            await fetch_data()
    asyncio.create_task(loop())

@app.get("/", response_class=HTMLResponse)
async def ana_sayfa():
    if not top_gainers:
        mesaj = "Veri yükleniyor... (10 saniye içinde gelecek)"
    else:
        mesaj = f"Son Güncelleme: {last_update}"

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

        <!-- YENİ BUTON -->
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

