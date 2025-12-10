from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx
import asyncio
from datetime import datetime
import os

app = FastAPI(title="ICT Smart Pro - Canlı Kripto Sıralaması")

app.mount("/assets", StaticFiles(directory=".", html=False), name="assets")

# Memory'de tutacağımız veri (her 10 saniyede bir güncellenecek)
top_gainers = []
last_update = "Henüz yüklenmedi"

async def update_top_gainers():
    global top_gainers, last_update
    while True:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # 24 saatlik tüm verileri al (değişim yüzdesi burda var)
                r = await client.get("https://api.binance.com/api/v3/ticker/24hr")
                data = r.json()

                # Sadece USDT çiftleri ve hacmi yüksek olanlar
                usdt_pairs = [
                    coin for coin in data
                    if coin["symbol"].endswith("USDT")
                    and float(coin["quoteVolume"]) > 10_000_000  # min $10M hacim
                ]

                # 24 saatlik değişime göre sırala (en çok yükselen en üstte)
                sorted_coins = sorted(
                    usdt_pairs,
                    key=lambda x: float(x["priceChangePercent"]),
                    reverse=True
                )

                # İlk 10'u al
                top_gainers = sorted_coins[:10]
                last_update = datetime.now().strftime("%d %B %Y - %H:%M:%S")

        except Exception as e:
            print("Güncelleme hatası:", e)
            top_gainers = []
            last_update = "Bağlantı hatası"

        await asyncio.sleep(10)  # Her 10 saniyede bir güncelle


# Uygulama başladığında arka planda çalışsın
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(update_top_gainers())


@app.get("/", response_class=HTMLResponse)
async def root():
    return f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ICT Smart Pro - En Hızlı Yükselen Coinler</title>
        <link rel="icon" href="/assets/logo.png" type="image/png">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@800&family=Rajdhani:wght@600&display=swap');
            body {{margin:0;padding:0;height:100vh;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);color:white;font-family:'Rajdhani',sans-serif;overflow:hidden}}
            .container {{display:flex;flex-direction:column;align-items:center;padding:20px}}
            .logo {{width:160px;margin-bottom:20px;animation:pulse 3s infinite;border-radius:25px;box-shadow:0 0 30px #00dbde}}
            h1 {{font-family:'Orbitron',sans-serif;font-size:4rem;margin:10px;background:linear-gradient(90deg,#00dbde,#fc00ff,#00dbde);-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:glow 2s infinite alternate}}
            .update {{margin:15px 0;font-size:1.1rem;opacity:0.8}}
            table {{width:90%;max-width:1000px;border-collapse:collapse;margin-top:20px;background:rgba(0,0,0,0.4);border-radius:20px;overflow:hidden;box-shadow:0 0 40px rgba(0,255,136,0.3)}}
            th {{background:linear-gradient(90deg,#fc00ff,#00dbde);padding:18px;font-size:1.4rem}}
            td {{padding:16px 12px;text-align:center;font-size:1.3rem;transition:0.3s}}
            tr:nth-child(even) {{background:rgba(255,255,255,0.05)}}
            tr:hover {{background:rgba(0,255,255,0.15);transform:scale(1.02);box-shadow:0 0 20px #00ffff}}
            .rank {{font-size:2rem;font-weight:bold;color:#00ff88;text-shadow:0 0 15px #00ff88}}
            .symbol {{font-size:1.6rem;font-weight:bold;color:#00dbde;text-shadow:0 0 10px}}
            .price {{color:#ffd700}}
            .positive {{color:#00ff88;font-weight:bold;text-shadow:0 0 15px #00ff88;animation:pulseGreen 1.5s infinite}}
            .status {{margin-top:30px;padding:15px 40px;background:rgba(0,255,136,0.2);border:2px solid #00ff88;border-radius:50px;font-size:1.4rem;font-weight:bold;color:#00ff88;box-shadow:0 0 20px #00ff8850}}
            @keyframes pulse {{0%,100%{{transform:scale(1)}}50%{{transform:scale(1.08)}}}}
            @keyframes glow {{from{{text-shadow:0 0 20px #00dbde}}to{{text-shadow:0 0 40px #fc00ff}}}}
            @keyframes pulseGreen {{0%,100%{{opacity:1}}50%{{opacity:0.7}}}}
        </style>
    </head>
    <body>
        <div class="container">
            <img src="/assets/logo.png" alt="Logo" class="logo">
            <h1>EN ÇOK YÜKSELENLER</h1>
            <p style="font-size:1.6rem;margin:10px">Son 24 Saatte Pompalar Burada!</p>
            <div class="update">Son Güncelleme: {last_update}</div>
            <div class="status">7/24 CANLI TAKİP</div>

            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Coin</th>
                        <th>Fiyat</th>
                        <th>24s Değişim</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(
                        f"""
                        <tr>
                            <td class="rank">{i+1}</td>
                            <td class="symbol">{coin['symbol']}</td>
                            <td class="price">${float(coin['lastPrice']):,.4f}</td>
                            <td class="positive">+{coin['priceChangePercent']}%</td>
                        </tr>
                        """ for i, coin in enumerate(top_gainers)
                    ) if top_gainers else "<tr><td colspan='4'>Yükleniyor...</td></tr>"}
                </tbody>
            </table>

            <script>
                // Her 10 saniyede bir sayfayı yenile (sadece tablo güncellenir)
                setTimeout(() => location.reload(), 10000);
            </script>
        </div>
    </body>
    </html>
    """

@app.get("/health")
async def health():
    return {"status": "pump hunting", "coins_tracked": len(top_gainers), "last_update": last_update}
