# exchanges/binance_ws.py
import asyncio
import websockets
import json
from datetime import datetime
from core import update_price, all_usdt_symbols

# exchanges/binance_ws.py'da kontrol edin:
async def binance_ticker_stream():
    while True:
        try:
            # WebSocket bağlantısı
            async with websockets.connect("wss://stream.binance.com:9443/ws/!ticker@arr") as ws:
                logger.info("Binance WebSocket bağlı")
                
                async for message in ws:
                    try:
                        data = json.loads(message)
                        
                        for ticker in data:
                            symbol = ticker.get('s', '').replace('USDT', 'USDT')
                            price = float(ticker.get('c', 0))
                            change = float(ticker.get('P', 0))
                            
                            if price > 0:
                                update_price("binance", symbol, price, change)
                                
                    except Exception as e:
                        logger.error(f"Binance mesaj işleme hatası: {e}")
                        
        except Exception as e:
            logger.error(f"Binance WS bağlantı hatası: {e}")
            await asyncio.sleep(5)
