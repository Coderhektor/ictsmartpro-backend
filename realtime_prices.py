# realtime_prices.py
import ccxt
import asyncio
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class RealTimePriceManager:
    def __init__(self):
        self.exchanges = {}
        self.prices_cache = {}
        self.last_update = None
        self.session = None
        
        # Popüler semboller
        self.default_symbols = [
            "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
            "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "DOT/USDT", "MATIC/USDT",
            "LTC/USDT", "TRX/USDT", "LINK/USDT", "UNI/USDT", "ATOM/USDT"
        ]
        
    async def initialize(self):
        """Exchange'leri başlat"""
        try:
            self.session = aiohttp.ClientSession()
            
            # Exchange'leri async olarak başlat
            self.exchanges = {
                'binance': ccxt.binance({
                    'enableRateLimit': True,
                    'timeout': 10000
                }),
                'bybit': ccxt.bybit({
                    'enableRateLimit': True,
                    'timeout': 10000
                }),
                'kucoin': ccxt.kucoin({
                    'enableRateLimit': True,
                    'timeout': 10000
                })
            }
            
            logger.info("✅ Exchange'ler başlatıldı")
            
        except Exception as e:
            logger.error(f"Exchange başlatma hatası: {e}")
    
    async def fetch_price_from_exchange(self, exchange_name: str, symbol: str) -> Optional[Dict]:
        """Bir exchange'den fiyat çek"""
        try:
            exchange = self.exchanges.get(exchange_name)
            if not exchange:
                return None
            
            # Ticker verisini çek
            ticker = exchange.fetch_ticker(symbol)
            
            return {
                'symbol': symbol.replace('/', ''),
                'price': float(ticker['last']),
                'change_24h': float(ticker['percentage']),
                'volume': float(ticker['baseVolume']),
                'high_24h': float(ticker['high']),
                'low_24h': float(ticker['low']),
                'bid': float(ticker['bid']),
                'ask': float(ticker['ask']),
                'exchange': exchange_name,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.debug(f"{exchange_name} {symbol} fiyat çekme hatası: {e}")
            return None
    
    async def fetch_all_prices(self, symbols: List[str] = None, limit: int = 50) -> Dict:
        """Tüm sembollerin fiyatlarını çek"""
        if symbols is None:
            symbols = self.default_symbols
        
        all_prices = []
        
        # Her sembol için tüm exchange'lerden veri çek
        for symbol in symbols[:limit]:
            symbol_prices = []
            
            # Binance'den çek (primary)
            binance_price = await self.fetch_price_from_exchange('binance', symbol)
            if binance_price:
                symbol_prices.append(binance_price)
            
            # Bybit'ten çek (fallback)
            bybit_price = await self.fetch_price_from_exchange('bybit', symbol)
            if bybit_price:
                symbol_prices.append(bybit_price)
            
            # En iyi fiyatı seç (volume'a göre)
            if symbol_prices:
                best_price = max(symbol_prices, key=lambda x: x['volume'])
                all_prices.append(best_price)
        
        # Cache'i güncelle
        self.prices_cache = {p['symbol']: p for p in all_prices}
        self.last_update = datetime.now()
        
        return {
            "prices": all_prices,
            "count": len(all_prices),
            "last_update": self.last_update.isoformat(),
            "source": "multi-exchange"
        }
    
    async def get_price_snapshot(self, limit: int = 50) -> Dict:
        """Cache'den fiyat snapshot'ı getir"""
        # Cache boşsa veya 10 saniyeden eskiyse yenile
        if (not self.prices_cache or 
            not self.last_update or 
            (datetime.now() - self.last_update).seconds > 10):
            await self.fetch_all_prices(limit=limit)
        
        # Cache'den verileri al
        prices = list(self.prices_cache.values())[:limit]
        
        return {
            "prices": prices,
            "count": len(prices),
            "timestamp": datetime.now().isoformat(),
            "cached": self.last_update.isoformat() if self.last_update else None
        }
    
    async def cleanup(self):
        """Temizlik"""
        if self.session:
            await self.session.close()

# Global instance
price_manager = RealTimePriceManager()

# main.py'de kullanmak için
async def initialize_prices():
    await price_manager.initialize()

def get_all_prices_snapshot(limit=50):
    """Main.py için sync wrapper"""
    # Async fonksiyonu sync olarak çağır
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # Loop çalışıyorsa, future oluştur
        import asyncio
        return asyncio.create_task(price_manager.get_price_snapshot(limit))
    else:
        # Loop çalışmıyorsa, run kullan
        return asyncio.run(price_manager.get_price_snapshot(limit))
