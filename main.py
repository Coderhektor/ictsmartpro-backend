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
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get("https://api.binance.us/api/v3/ticker/24hr")
            
        # KRİTİK KONTROL: veri gerçekten JSON listesi mi?
        if response.status_code != 200:
            print("Binance API hatası:", response.status_code)
            return
            
        data = response.json()
        if not isinstance(data, list):  # bazen string dönebiliyor
            print("Binance garip veri döndü:", type(data))
            return

        clean_coins = []
        for item in data:
            # item dict değilse (string vs) atla
            if not isinstance(item, dict):
                continue
                
            symbol = item.get("symbol", "")
            if not symbol or not symbol.endswith("USDT"):
                continue
                
            try:
                price = float(item.get("lastPrice", 0))
                change = float(item.get("priceChangePercent", 0))
                volume = float(item.get("quoteVolume", 0))
                
                if price > 0 and volume >= 2_000_000:  # 2 milyon dolar hacim
                    clean_coins.append({
                        "symbol": symbol.replace("USDT", "/USDT"),
                        "price": price,
                        "change": change
                    })
            except (ValueError, TypeError):
                continue

        # Sırala ve ilk 10'u al
        top_gainers = sorted(clean_coins, key=lambda x: x["change"], reverse=True)[:10]
        last_update = datetime.now().strftime("%H:%M:%S")
        print(f"{len(top_gainers)} coin yüklendi – {last_update}")

    except Exception as e:
        print("Bağlantı hatası:", e)

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
            h1{{font-size:4.5rem;background:linear-gradient(90deg,#00dbde,#fc00ff);-webkit-background-clip-path:text;-webkit-text-fill-color:transparent}}
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
        <script>
            setTimeout(()=>location.reload(), 9000);
        </script>
    </body>
    </html>
    """

