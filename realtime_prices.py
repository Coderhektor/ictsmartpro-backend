# realtime_prices.py - ÜRETİM HAZIR, SON DOKUNUŞLU VERSİYON

import ccxt.async_support as ccxt
import pandas as pd
import asyncio
from datetime import datetime
from typing import Dict, Any, Set, List
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def normalize_symbol(symbol: str) -> str:
    """
    Kullanıcı ne formatta yazarsa yazsın → BTC/USDT döndürür
    Örnekler:
        BTC         → BTC/USDT
        btcusdt     → BTC/USDT
        BTC-USDT    → BTC/USDT
        btc/USDT    → BTC/USDT
        BTC/USDT    → BTC/USDT
    """
    s = symbol.upper().replace('-', '').replace('/', '')
    if s.endswith('USDT'):
        base = s[:-4]  # USDT'yi çıkar
    else:
        base = s
    return f"{base}/USDT"


class GlobalPriceManager:
    """
    Singleton global fiyat yöneticisi.
    Tüm kullanıcılar bu tek instance'ı paylaşır → ölçeklenebilir, düşük bellek tüketimi.
    """
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.exchanges = {
                'binance': ccxt.binance({
                    'enableRateLimit': True,
                    'timeout': 10000,
                    'options': {'defaultType': 'spot'}
                }),
                'bybit': ccxt.bybit({'enableRateLimit': True}),
                'okx': ccxt.okx({'enableRateLimit': True}),
            }
            self.price_pool: Dict[str, pd.DataFrame] = {}  # key: BTCUSDT → DataFrame
            self.running = False
            self.all_symbols: Set[str] = set()  # Takip edilen normalized semboller: BTC/USDT
            self.initialized = True

    async def initialize(self):
        async with GlobalPriceManager._lock:
            if self.running:
                return

            for name, ex in self.exchanges.items():
                try:
                    await ex.load_markets()
                    logger.info(f"✅ Global {name.upper()} markets yüklendi ({len(ex.symbols)} sembol)")
                except Exception as e:
                    logger.error(f"❌ Global {name.upper()} markets yükleme hatası: {e}")

            self.running = True
            asyncio.create_task(self._update_loop())
            logger.info("✅ GlobalPriceManager başlatıldı ve sürekli güncelleme döngüsü çalışıyor")

    async def _fetch_price(self, ex, ex_name: str, symbol: str) -> Dict[str, Any] | None:
        try:
            ticker = await ex.fetch_ticker(symbol)
            return {
                'exchange': ex_name,
                'price': float(ticker['last'] or 0),
                'change_24h': float(ticker.get('percentage') or 0),
                'volume_24h': float(
                    ticker.get('baseVolume') or
                    ticker.get('quoteVolume') or
                    ticker.get('volume') or 0
                ),
                'timestamp': datetime.utcnow()
            }
        except Exception as e:
            logger.debug(f"[{ex_name}] {symbol} fetch hatası: {e}")
            return None

    async def _update_symbol(self, symbol: str):
        tasks = [
            self._fetch_price(ex, name, symbol)
            for name, ex in self.exchanges.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        valid = [r for r in results if isinstance(r, dict) and 'price' in r]

        if valid:
            df = pd.DataFrame(valid).set_index('exchange')
            key = symbol.replace('/', '').upper()  # BTC/USDT → BTCUSDT
            self.price_pool[key] = df

    async def _update_loop(self):
        """Tüm takip edilen sembolleri ardışık olarak günceller"""
        while self.running:
            if not self.all_symbols:
                await asyncio.sleep(1)
                continue

            symbols_list = list(self.all_symbols)
            for symbol in symbols_list:
                await self._update_symbol(symbol)
                await asyncio.sleep(0.1)  # Rate limit ve nazik davranış için

            await asyncio.sleep(0.5)  # Tur arası hafif dinlenme

    async def add_symbol(self, symbol: str):
        """Yeni sembol ekle (normalize edilmiş halde)"""
        normalized = normalize_symbol(symbol)
        if normalized not in self.all_symbols:
            self.all_symbols.add(normalized)
            logger.info(f"🆕 Yeni sembol eklendi: {normalized} | Toplam takip: {len(self.all_symbols)}")
            await self._update_symbol(normalized)  # Hemen ilk veriyi çek

    def get_price(self, symbol: str) -> Dict[str, Any]:
        """Ortalama fiyat ve kaynak detaylarını döndür"""
        key = normalize_symbol(symbol).replace('/', '').upper()
        if key in self.price_pool:
            df = self.price_pool[key]
            return {
                'symbol': key,
                'average_price': round(df['price'].mean(), 8),
                'average_change_24h': round(df['change_24h'].mean(), 2),
                'volume_24h_avg': round(df['volume_24h'].mean(), 2),
                'sources': df[['price', 'change_24h', 'volume_24h', 'timestamp']].to_dict(orient='index'),
                'last_update': df['timestamp'].max().isoformat() + 'Z',
                'source_count': len(df)
            }
        return {
            'symbol': key,
            'error': 'Henüz veri yok veya sembol takip edilmiyor',
            'tip': 'Birkaç saniye içinde güncellenecek'
        }

    async def cleanup(self):
        self.running = False
        for name, ex in self.exchanges.items():
            try:
                await ex.close()
                logger.info(f"✅ {name.upper()} bağlantısı kapatıldı")
            except Exception as e:
                logger.warning(f"{name.upper()} kapatma hatası: {e}")
        logger.info("✅ GlobalPriceManager tamamen kapatıldı")


# Global singleton instance
price_manager = GlobalPriceManager()


class UserPriceTracker:
    """
    Her kullanıcı için hafif bir wrapper.
    Sadece hangi sembolleri takip ettiğini tutar.
    """
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.tracked_symbols: Set[str] = set()  # Normalized formatta: BTC/USDT

    async def track(self, symbol: str):
        """Kullanıcı yeni bir coin takip etmek istediğinde"""
        normalized = normalize_symbol(symbol)
        if normalized not in self.tracked_symbols:
            self.tracked_symbols.add(normalized)
            await price_manager.add_symbol(normalized)  # Global managera ekle
            logger.info(f"[{self.user_id}] → {normalized} takibe alındı")

    def get_price(self, symbol: str) -> Dict[str, Any]:
        return price_manager.get_price(symbol)

    def get_all_tracked_prices(self) -> Dict[str, Any]:
        """Kullanıcının takip ettiği tüm coinlerin fiyatlarını döndür"""
        return {
            sym: self.get_price(sym)
            for sym in self.tracked_symbols
        }

    def list_tracked(self) -> List[str]:
        return list(self.tracked_symbols)

#   Tüm takip edilen fiyatları snapshot olarak döndür
def get_all_prices_snapshot(limit: int = 50) -> Dict[str, Any]:
    """
    Global olarak takip edilen tüm sembollerin güncel fiyat snapshot'ını döndürür.
    HTTP endpoint'ler için kullanışlı.
    """
    try:
        # Tüm global sembolleri al
        all_keys = list(price_manager.price_pool.keys())
        # En son güncellenenlere göre sırala (timestamp'e göre)
        sorted_keys = sorted(
            all_keys,
            key=lambda k: price_manager.price_pool[k]['timestamp'].max() if k in price_manager.price_pool else datetime.min,
            reverse=True
        )[:limit]

        snapshot = {}
        for key in sorted_keys:
            snapshot[key] = price_manager.get_price(key.replace('USDT', '/USDT'))  # kullanıcı dostu format

        return {
            "snapshot": snapshot,
            "total_tracked": len(price_manager.all_symbols),
            "returned_count": len(snapshot),
            "timestamp": datetime.utcnow().isoformat() + 'Z'
        }
    except Exception as e:
        logger.error(f"get_all_prices_snapshot hatası: {e}")
        return {
            "error": "Snapshot alınamadı",
            "details": str(e),
            "timestamp": datetime.utcnow().isoformat() + 'Z'
        }

# Test / Örnek kullanım
async def main():
    await price_manager.initialize()

    # Kullanıcı 1
    user1 = UserPriceTracker("user_42")
    await user1.track('BTC')
    await user1.track('ethusdt')
    await user1.track('XRP-USDT')
    await user1.track('Ada')

    # Kullanıcı 2
    user2 = UserPriceTracker("user_99")
    await user2.track('SOL')
    await user2.track('dogeusdt')
    await user2.track('AVAX/USDT')

    # Biraz bekle, veriler gelsin
    await asyncio.sleep(20)

    print("\n=== User 1 (user_42) ===")
    print("BTC:", user1.get_price('BTC'))
    print("ETH:", user1.get_price('ETHUSDT'))

    print("\n=== User 2 (user_99) ===")
    print("SOL:", user2.get_price('SOL'))
    print("DOGE:", user2.get_price('DOGEUSDT'))

    await price_manager.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
