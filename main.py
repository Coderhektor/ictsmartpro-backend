from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx
import asyncio
from datetime import datetime
import os

app = FastAPI(title="ICT Smart Pro – Canlı Pump Tablosu")
app.mount("/assets", StaticFiles(directory=".", html=False), name="assets")

# Global değişkenler
top_gainers = []
last_update = "Yükleniyor..."

async def update_data():
    global top_gainers, last_update
    while True:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                # Tek seferde hem fiyat hem 24s değişim alıyoruz
                r = await client.get("https://api.binance.com/api/v3/ticker/24hr")
                r.raise_for_status()
                raw_data = r.json()

            # Temiz ve güvenli liste oluştur
            clean_list = []
            for item in raw_data:
                if not isinstance(item, dict):
                    continue
                symbol = item.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue
                try:
                    price = float(item.get("lastPrice", 0))
                    change = float(item.get("priceChangePercent", 0))
                    volume = float(item.get("quoteVolume", 0))
                except (TypeError, ValueError):
                    continue

                if price > 0 and volume >= 5_000_000:  # min 5M$ hacim (daha çok coin çıksın)
                    clean_list.append({
                        "symbol": symbol.replace("USDT", "/USDT"),
                        "price": price,
                        "change": change,
                        "volume": volume
                    })

            # Sırala ve ilk 10’u al
            top_gainers = sorted(clean_list, key=lambda x: x["change"], reverse=True)[:10]
            last_update = datetime.now().strftime("%d %b %Y – %H:%M:%S")

        except Exception as e:
            print("Bağlantı hatası (tekrar deneyecek):", e)
            # Hata olsa bile eski veriyi koru (boş kalmasın)
            await asyncio.sleep(5)
            continue

        await asyncio.sleep(10)  # 10 saniyede bir güncelle


@app.on_event("startup")
async def on_startup():
    asyncio.create_task(update_data())


@app.get("/", response_class=HTMLResponse)
async def ana_sayfa():
    rows = ""
    if top_gainers:
        for i, coin in enumerate(top_gainers, 1):
            renk = "color:#00ff88" if coin["change"] > 0 else "color:#ff4444"
            rows += f"""
            <tr>
                <td class="rank">{i}</td>
                <td class="coin">{coin['symbol']}</td>
                <td class="price">${coin['price']:,.4f}</td>
                <td style="{renk};font-weight:bold">{coin['change']:+.2f}%</td>
            </tr>
            """
    else:
        rows = '<tr><td colspan="4" style="color:#ff9900">Veri yükleniyor, 10 saniye içinde gelecek...</td></tr>'

    return f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ICT Smart Pro – En Çok Yükselenler</title>
        <link rel="icon" href="/assets/logo.png" type="image/png">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@900&family=Rajdhani:wght@700&display=swap');
            body {{margin:0;padding:0;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);color:#fff;font-family:'Rajdhani',sans-serif;overflow:hidden;height:100vh}}
            .container {{text-align:center;padding:20px}}
            .logo {{width:140px;margin:20px auto;display:block;animation:pulse 3s infinite;border-radius:20px}}
            h1 {{font-family:'Orbitron',sans-serif;font-size:4.5rem;background:-webkit-linear-gradient(#00dbde,#fc00ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
            table {{width:95%;max-width:1100px;margin:30px auto;border-collapse:collapse;background:rgba(0,0,0,0.5);border-radius:20px;overflow:hidden;box-shadow:0 0 50px rgba(0,255,136,0.4)}}
            th {{background:linear-gradient(90deg,#fc00ff,#00dbde);padding:20px;font-size:1.5rem}}
            td {{padding:18px;font-size:1.4rem}}
            tr:hover {{background:rgba(0,255,255,0.2);transform:scale(1.02)}
            .rank {{font-size:2.5rem;color:#00ff88;text-shadow:0 0 20px #00ff88}}
            .coin {{font-size:1.8rem;color:#00dbde;font-weight:bold}}
            .price {{color:#ffd700}}
            .update {{margin:20px;font-size:1.3rem;color:#00ff88}}
            @keyframes pulse {{0%,100%{{transform:scale(1)}}50%{{transform:scale(1.1)}}}}
        </style>
    </head>
    <body>
        <div class="container">
            <img src="/assets/logo.png" class="logo" onerror="this.style.display='none'">
            <h1>PUMP RADARI</h1>
            <div class="update">Son Güncelleme: {last_update}</div>
            <table>
                <thead><tr><th>#</th><th>COIN</th><th>FİYAT</th><th>24S DEĞİŞİM</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
        <script>setTimeout(()=>location.reload(), 10000)</script>
    </body>
    </html>
    """

@app.get("/health")
async def health(): return {"status": "pump hunting", "coins": len(top_gainers)}
