
# exchanges/okx_ws.py
import asyncio
import websockets
import json
from core import update_price, all_usdt_symbols

async def okx_ticker_stream():
    url = "wss://ws.okx.com:8443/ws/v5/public"
    symbols = [s.replace("USDT", "-USDT") for s in all_usdt_symbols if s.endswith("USDT")]
    args = [{"channel": "tickers", "instId": s} for s in symbols[:50]]
    
    while True:
        try:
            async with websockets.connect(url) as ws:
                print("OKX WebSocket bağlı")
                await ws.send(json.dumps({"op": "subscribe", "args": args}))
                
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(msg)
                    
                    if data.get("arg", {}).get("channel") == "tickers" and "data" in data:
                        for ticker in data["data"]:
                            inst_id = ticker["instId"]
                            symbol = inst_id.replace("-", "")
                            if symbol in all_usdt_symbols:
                                price = float(ticker["last"])
                                change = float(ticker["priceChangePercent"]) if ticker.get("priceChangePercent") else None
                                update_price("okx", symbol, price, change)
        
        except Exception as e:
            print(f"OKX hata: {e}")
            await asyncio.sleep(5)
