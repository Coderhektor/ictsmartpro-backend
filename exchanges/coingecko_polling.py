
# exchanges/coingecko_polling.py
import asyncio
import aiohttp
from core import update_price, all_usdt_symbols

async def coingecko_polling():
    symbols = [s.lower().replace("usdt", "") for s in all_usdt_symbols[:30]]
    ids = ",".join(symbols)  # btc,eth,sol gibi
    
    url = f"https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"}
    
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for coin_id, info in data.items():
                            symbol = coin_id.upper() + "USDT"
                            price = info["usd"]
                            change = info.get("usd_24h_change")
                            update_price("coingecko", symbol, price, change)
                print("Coingecko fiyatları güncellendi")
            except Exception as e:
                print(f"Coingecko hata: {e}")
            
            await asyncio.sleep(15)  # 15 saniyede bir
