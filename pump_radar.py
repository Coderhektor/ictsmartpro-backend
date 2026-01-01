# pump_radar.py - GERÇEK FİYATLI VERSİYON
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Optional
import pandas as pd
import numpy as np

from core import get_binance_client, get_all_prices_snapshot, price_pool
from utils import all_usdt_symbols

logger = logging.getLogger("pump_radar")

# Global değişkenler
top_gainers: List[Dict] = []
last_update: str = ""

async def fetch_real_prices_with_change(symbols: List[str], lookback_hours: int = 24) -> List[Dict]:
    """
    Gerçek borsa fiyatlarını ve 24 saatlik değişimleri getir
    """
    try:
        client = get_binance_client()
        if not client:
            logger.error("Binance client yok")
            return []
        
        results = []
        
        for symbol in symbols[:100]:  # İlk 100 coin için
            try:
                # Anlık fiyat
                ticker = await client.fetch_ticker(f"{symbol}/USDT")
                current_price = float(ticker['last'])
                
                # 24 saatlik değişim yüzdesi (gerçek)
                change_24h = float(ticker.get('percentage', 0))  # % olarak
                
                # Hacim bilgisi
                volume_24h = float(ticker.get('quoteVolume', 0))
                
                results.append({
                    'symbol': symbol.replace('USDT', ''),
                    'price': current_price,
                    'change': change_24h,
                    'volume': volume_24h,
                    'high_24h': float(ticker.get('high', 0)),
                    'low_24h': float(ticker.get('low', 0)),
                    'timestamp': datetime.utcnow().isoformat()
                })
                
                # Rate limit koruması
                await asyncio.sleep(0.05)
                
            except Exception as e:
                logger.debug(f"{symbol} fiyat hatası: {e}")
                continue
        
        # Değişime göre sırala
        results.sort(key=lambda x: x['change'], reverse=True)
        return results[:50]  # Top 50
        
    except Exception as e:
        logger.error(f"Fiyat çekme hatası: {e}")
        return []

async def fetch_pump_candidates() -> List[Dict]:
    """
    Gerçek anlık pompa adaylarını bul
    """
    try:
        # 1. Tüm fiyatları snapshot'tan al
        price_snapshot = get_all_prices_snapshot()
        if not price_snapshot:
            return []
        
        # 2. Değişim oranlarını hesapla (anlık - dakikalık)
        symbols = list(price_snapshot.keys())
        candidates = []
        
        for symbol in symbols[:200]:  # İlk 200 coin
            try:
                price_data = price_snapshot.get(symbol)
                if not price_data:
                    continue
                
                current_price = price_data.get('price', 0)
                change_5m = price_data.get('change_5m', 0)
                change_15m = price_data.get('change_15m', 0)
                volume = price_data.get('volume', 0)
                
                # Kombine skor (değişim + hacim)
                score = (change_5m * 2 + change_15m * 1) * (1 + np.log1p(volume) / 100)
                
                if score > 5:  # Anlamlı değişim
                    candidates.append({
                        'symbol': symbol.replace('USDT', ''),
                        'price': current_price,
                        'change': change_5m,
                        'score': score,
                        'volume': volume,
                        'source': price_data.get('source', 'unknown')
                    })
                    
            except Exception as e:
                continue
        
        # Skora göre sırala
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[:20]
        
    except Exception as e:
        logger.error(f"Pump candidate hatası: {e}")
        return []

async def update_top_gainers():
    """
    Top gainers listesini güncelle
    """
    global top_gainers, last_update
    
    try:
        # Yöntem 1: Gerçek 24 saatlik değişimleri al
        real_gainers = await fetch_real_prices_with_change(all_usdt_symbols[:150])
        
        # Yöntem 2: Anlık pompa adaylarını al
        pump_candidates = await fetch_pump_candidates()
        
        # İkisini birleştir
        combined = []
        
        # Gerçek gainers ekle
        for gainer in real_gainers[:30]:
            combined.append({
                'symbol': gainer['symbol'],
                'price': gainer['price'],
                'change': gainer['change'],
                'volume': gainer['volume'],
                'type': '24h_gainer'
            })
        
        # Pump candidates ekle
        for candidate in pump_candidates[:10]:
            combined.append({
                'symbol': candidate['symbol'],
                'price': candidate['price'],
                'change': candidate['change'],
                'volume': candidate['volume'],
                'type': 'pump_candidate'
            })
        
        # Benzersiz symbol'lar
        seen = set()
        unique_combined = []
        for item in combined:
            if item['symbol'] not in seen:
                seen.add(item['symbol'])
                unique_combined.append(item)
        
        # Değişime göre tekrar sırala
        unique_combined.sort(key=lambda x: x['change'], reverse=True)
        
        top_gainers = unique_combined[:25]  # Top 25
        last_update = datetime.utcnow().strftime("%H:%M:%S UTC")
        
        logger.info(f"📈 Top gainers güncellendi: {len(top_gainers)} coin")
        
    except Exception as e:
        logger.error(f"Top gainers güncelleme hatası: {e}")
        top_gainers = []
        last_update = "HATA"

async def start_pump_radar():
    """
    Pump radar'ı başlat
    """
    logger.info("🚀 Pump radar başlatılıyor...")
    
    while True:
        try:
            await update_top_gainers()
            await asyncio.sleep(30)  # 30 saniyede bir güncelle
        except Exception as e:
            logger.error(f"Pump radar loop hatası: {e}")
            await asyncio.sleep(60)

# WebSocket için fonksiyon
def get_pump_radar_data() -> Dict:
    """
    WebSocket için pump radar verilerini getir
    """
    return {
        "top_gainers": top_gainers,
        "last_update": last_update,
        "total_coins": len(top_gainers)
    }
