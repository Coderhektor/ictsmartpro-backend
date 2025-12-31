# exchanges/bybit_ws.py
import asyncio
import websockets
import json
from core import update_price, all_usdt_symbols

async def bybit_ticker_stream():
    url = "wss://stream.bybit.com/v5/public/spot"
    symbols = [s for s in all_usdt_symbols if s.endswith("USDT")]
    args = [f"tickers.{s}" for s in symbols[:50]]  # Bybit max 50 arg destekler
    
    while True:
        try:
            async with websockets.connect(url) as ws:
                print("Bybit WebSocket bağlı")
                await ws.send(json.dumps({"op": "subscribe", "args": args}))
                
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(msg)
                    
                    if data.get("topic", "").startswith("tickers"):
                        ticker = data["data"]
                        symbol = ticker["symbol"]
                        if symbol in symbols:
                            price = float(ticker["lastPrice"])
                            change = float(ticker["price24hPcnt"]) * 100
                            update_price("bybit", symbol, price, change)
        
        except Exception as e:
            print(f"Bybit hata: {e}, yeniden bağlanılıyor...")
            await asyncio.sleep(5)
