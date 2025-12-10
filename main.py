from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx
import asyncio
from datetime import datetime

app = FastAPI()
app.mount("/assets", StaticFiles(directory=".", html=False), name="assets")

top_gainers = []
last_update = "Yükleniyor..."

async def update_data():
    global top_gainers, last_update
    while True:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                res = await client.get("https://api.binance.com/api/v3/ticker/24hr")
                data = res.json()

            clean = []
            for c in data:
                if not isinstance(c, dict): continue
                if not c.get("symbol", "").endswith("USDT"): continue
                try:
                    price = float(c["lastPrice"])
                    change = float(c["priceChangePercent"])
                    volume = float(c.get("quoteVolume", 0))
                    if price > 0 and volume >= 5_000_000:
                        clean.append({
                            "symbol": c["symbol"].replace("USDT", "/USDT"),
                            "price": price,
                            "change": change
                        })
                except:
                    continue

            top_gainers = sorted(clean, key=lambda x: x["change"], reverse=True)[:10]
            last_update = datetime.now().strftime("%d %b %Y – %H:%M:%S")

        except Exception as e:
            print("Hata:", e)

        await asyncio.sleep(10)

@app.on_event("startup")
async def start_bg_task():
    asyncio.create_task(update_data())

@app.get("/", response_class=HTMLResponse)
async def home():
    rows = ""
    for i, coin in enumerate(top_gainers, 1):
        color = "#00ff88" if coin["change"] > 0 else "#ff4444"
        rows += f'<tr><td class="r">{i}</td><td class="c">{coin["symbol"]}</td><td class="p">${coin["price"]:,.4f}</td><td style="color:{color};font-weight:bold">{coin["change"]:+.2f}%</td></tr>'

    if not rows:
        rows = '<tr><td colspan="4" style="color:#ffa500;font-size:1.5rem">Veri yükleniyor, 10 saniye içinde gelecek...</td></tr>'

    return f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ICT Smart Pro - Pump Radarı</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@900&display=swap');
            body {{margin:0;padding:0;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);color:white;font-family:'Segoe UI',sans-serif;overflow:hidden}}
            .ct {{text-align:center;padding:20px}}
            .logo {{width:150px;margin:20px;animation:a 3s infinite;border-radius:20px}}
            h1 {{font-family:'Orbitron',sans-serif;font-size:4.5rem;background:linear-gradient(90deg,#00dbde,#fc00ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
            table {{width:95%;max-width:1100px;margin:30px auto;border-collapse:collapse;background:rgba(0,0,0,0.5);border-radius:20px;overflow:hidden;box-shadow:0 0 40px #00ff8830}}
            th {{background:linear-gradient(90deg,#fc00ff,#00dbde);padding:20px;font-size:1.6rem}}
            td {{padding:18px;font-size:1.5rem;text-align:center}}
            tr:hover {{background:rgba(0,255,255,0.2)}}
            .r {{font-size:2.5rem;color:#00ff88;text-shadow:0 0 20px #00ff88}}
            .c {{font-size:1.8rem;color:#00dbde;font-weight:bold}}
            .p {{color:#ffd700}}
            .u {{margin:20px;font-size:1.4rem;color:#00ff88}}
            @keyframes a {{0%,100%{{transform:scale(1)}}50%{{transform:scale(1.1)}}}}
        </style>
    </head>
    <body>
        <div class="ct">
            <img src="/assets/logo.png" class="logo" onerror="this.style.display='none'">
            <h1>PUMP RADARI</h1>
            <div class="u">Son Güncelleme: {last_update}</div>
            <table>
                <thead><tr><th>#</th><th>COIN</th><th>FİYAT</th><th>24S</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
        <script>setInterval(()=>location.reload(),10000)</script>
    </body>
    </html>
    """

@app.get("/health")
async def health():
    return {"status": "aktif", "coin_sayisi": len(top_gainers), "son_guncelleme": last_update}
