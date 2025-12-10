from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx
import asyncio
from datetime import datetime

app = FastAPI()
app.mount("/assets", StaticFiles(directory=".", html=False), name="assets")

# Başlangıçta boş değil, ilk veri hemen gelsin diye
top_gainers = [{"symbol": "YÜKLENİYOR...", "price": 0, "change": 0}] * 10
last_update = "Başlatılıyor..."

async def fetch_and_update():
    global top_gainers, last_update
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            res = await client.get("https://api.binance.com/api/v3/ticker/24hr")
            data = res.json()

            clean = []
            for c in data:
                if not c.get("symbol", "").endswith("USDT"): continue
                try:
                    price = float(c["lastPrice"])
                    change = float(c["priceChangePercent"])
                    vol = float(c.get("quoteVolume", 0))
                    if price > 0 and vol >= 3_000_000:  # biraz düşürdüm ki daha çok coin çıksın
                        clean.append({
                            "symbol": c["symbol"].replace("USDT", "/USDT"),
                            "price": price,
                            "change": change
                        })
                except: continue

            top_gainers = sorted(clean, key=lambda x: x["change"], reverse=True)[:10]
            last_update = datetime.now().strftime("%H:%M:%S")
        except Exception as e:
            print("Hata:", e)
            top_gainers = [{"symbol": "BAĞLANTI HATASI", "price": 0, "change": -100}]

# Uygulama başlar başlamaz ilk veriyi çek
@app.on_event("startup")
async def startup():
    await fetch_and_update()  # İlk açılışta hemen veri çek
    asyncio.create_task(background_update())  # Sonra 8 saniyede bir güncelle

async def background_update():
    while True:
        await asyncio.sleep(8)
        await fetch_and_update()

@app.get("/", response_class=HTMLResponse)
async def home():
    rows = ""
    for i, c in enumerate(top_gainers, 1):
        color = "#00ff88" if c["change"] > 0 else "#ff4444"
        rows += f'<tr><td class="r">{i}</td><td class="s">{c["symbol"]}</td><td class="p">${c["price"]:,.4f}</td><td style="color:{color};font-weight:bold">{c["change"]:+.2f}%</td></tr>'

    return f"""
    <!DOCTYPE html>
    <html lang="tr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ICT Smart Pro - PUMP RADARI</title>
    <style>
        body{{margin:0;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);color:#fff;font-family:Arial;text-align:center;padding:20px}}
        h1{{font-size:4.5rem;background:linear-gradient(90deg,#00dbde,#fc00ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
        table{{width:95%;max-width:1000px;margin:30px auto;background:rgba(0,0,0,0.6);border-radius:20px;overflow:hidden}}
        th{{background:linear-gradient(90deg,#fc00ff,#00dbde);padding:20px;font-size:1.6rem}}
        td{{padding:18px;font-size:1.5rem}}
        .r{{font-size:2.5rem;color:#00ff88;text-shadow:0 0 20px #00ff88}}
        .s{{font-size:1.8rem;color:#00dbde;font-weight:bold}}
        .p{{color:#ffd700}}
        .u{{font-size:1.4rem;color:#00ff88;margin:20px}}
        img{{width:140px;border-radius:20px;animation:p 3s infinite}}
        @keyframes p{{0%,100%{{transform:scale(1)}}50%{{transform:scale(1.1)}}}}
    </style></head>
    <body>
        <img src="/assets/logo.png" onerror="this.style.display='none'">
        <h1>PUMP RADARI</h1>
        <div class="u">Son Güncelleme: {last_update} → 8sn'de yenilenecek</div>
        <table>
            <tr><th>#</th><th>COIN</th><th>FİYAT</th><th>24S %</th></tr>
            {rows}
        </table>
        <script>setTimeout(()=>location.reload(),8000)</script>
    </body></html>
    """
