# exchanges/binance_ws.py
import asyncio
import websockets
import json
from datetime import datetime
from core import update_price, all_usdt_symbols

async def binance_ticker_stream():
    url = "wss://stream.binance.com:9443/ws/!ticker@arr"
    symbols = [s for s in all_usdt_symbols if s.endswith("USDT")]
    
    while True:
        try:
            async with websockets.connect(url) as ws:
                print("Binance WebSocket bağlı")
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(msg)
                    
                    if isinstance(data, list):
                        for ticker in data:
                            symbol = ticker['s']
                            if symbol in symbols:
                                price = float(ticker['c'])
                                change = float(ticker['P']) if ticker['P'] else None
                                update_price("binance", symbol, price, change)
        
        except (websockets.ConnectionClosed, asyncio.TimeoutError, Exception) as e:
            print(f"Binance bağlantı hatası: {e}, 5sn sonra yeniden bağlanılıyor...")
            await asyncio.sleep(5)
