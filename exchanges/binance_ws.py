# Bağlantı hatalarını daha iyi handle et
async def binance_ticker_stream():
    reconnect_delay = 1
    max_reconnect_delay = 30
    
    while True:
        try:
            logger.info("🔗 Binance WebSocket bağlanıyor...")
            async with websockets.connect(
                "wss://stream.binance.com:9443/ws/!ticker@arr",
                ping_interval=20,
                ping_timeout=10
            ) as ws:
                logger.info("✅ Binance WebSocket bağlandı")
                reconnect_delay = 1  # Reset delay
                
                async for message in ws:
                    try:
                        data = json.loads(message)
                        if not isinstance(data, list):
                            continue
                            
                        for ticker in data:
                            symbol = ticker.get('s', '')
                            price_str = ticker.get('c', '0')
                            change_str = ticker.get('P', '0')
                            
                            if not symbol or not price_str:
                                continue
                                
                            try:
                                price = float(price_str)
                                change = float(change_str)
                                
                                if price > 0:
                                    update_price("binance", symbol, price, change)
                                    
                            except (ValueError, TypeError) as e:
                                continue
                                
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        logger.debug(f"Binance mesaj işleme: {e}")
                        
        except Exception as e:
            logger.error(f"❌ Binance WS hatası: {str(e)[:100]}")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
