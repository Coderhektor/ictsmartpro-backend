# indicators.py — TAM DÜZELTİLMİŞ VERSİYON
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger("indicators")

# ----------------------------- PARAMETRELER -----------------------------
RSI6_LENGTH = 6
SMA50_LENGTH = 50
RSI_OB_LEVEL = 70
CRT_RANGE_MULTIPLIER = 1.5
CRT_LOOKBACK = 5
SIGNAL_STRENGTH = 55

LONDON_KILLZONE_START_UTC = 7
LONDON_KILLZONE_END_UTC = 10
NY_KILLZONE_START_UTC = 13
NY_KILLZONE_END_UTC = 16

def rsi(series: pd.Series, period: int) -> pd.Series:
    """RSI hesapla - pandas Series için"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    rsi_vals = 100 - (100 / (1 + rs))
    rsi_vals = rsi_vals.fillna(50)
    return rsi_vals

def generate_ict_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """ICT sinyali üret - DataFrame formatını kontrol et"""
    try:
        logger.info(f"generate_ict_signal çağrıldı: {symbol}, {timeframe}, shape: {df.shape}")
        logger.info(f"DataFrame columns: {df.columns.tolist() if hasattr(df, 'columns') else 'N/A'}")
        logger.info(f"DataFrame type: {type(df)}")
        
        # DataFrame mi kontrol et
        if not isinstance(df, pd.DataFrame):
            logger.error(f"{symbol}: df pandas DataFrame değil, type: {type(df)}")
            return None
        
        # Minimum veri kontrolü
        if len(df) < 100:
            logger.warning(f"{symbol}: Yeterli veri yok ({len(df)} < 100)")
            return None
        
        # Gerekli sütunları kontrol et ve düzelt
        required_cols = ['open', 'high', 'low', 'close']
        
        # Eğer sütun isimleri farklıysa düzelt
        if not all(col in df.columns for col in required_cols):
            logger.warning(f"{symbol}: Gerekli sütunlar yok, düzeltiliyor...")
            
            # Binance formatı: [timestamp, open, high, low, close, volume]
            if len(df.columns) >= 5:
                # İlk 5 sütunu kullan
                df = df.iloc[:, :5].copy()
                df.columns = ['timestamp', 'open', 'high', 'low', 'close'][:len(df.columns)]
                logger.info(f"{symbol}: Sütunlar düzeltildi: {df.columns.tolist()}")
            else:
                logger.error(f"{symbol}: Yeterli sütun yok: {df.columns.tolist()}")
                return None
        
        # Sayısal verilere çevir
        for col in required_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            else:
                logger.error(f"{symbol}: {col} sütunu hala yok")
                return None
        
        # NaN değerleri temizle
        df_clean = df[required_cols].copy()
        df_clean = df_clean.dropna()
        
        if len(df_clean) < 100:
            logger.warning(f"{symbol}: Temizleme sonrası yeterli veri yok ({len(df_clean)} < 100)")
            return None
        
        # Son 100 mum'u al
        df_clean = df_clean.tail(100).copy()
        
        # Index'i ayarla (timestamp yoksa oluştur)
        if 'timestamp' in df_clean.columns:
            df_clean = df_clean.set_index('timestamp')
            try:
                df_clean.index = pd.to_datetime(df_clean.index, unit='ms', utc=True)
            except:
                df_clean.index = pd.to_datetime(df_clean.index, utc=True)
        else:
            # Timestamp yoksa, son 100 dakikayı kullan
            end_time = pd.Timestamp.now(tz=timezone.utc)
            start_time = end_time - pd.Timedelta(minutes=100)
            df_clean.index = pd.date_range(start=start_time, periods=100, freq='1min', tz=timezone.utc)
        
        # Volume ekle (yoksa)
        if 'volume' not in df_clean.columns:
            df_clean['volume'] = 1000  # Default volume
        
        # Heikin-Ashi hesapla
        ha_close = (df_clean['open'] + df_clean['high'] + df_clean['low'] + df_clean['close']) / 4
        
        # Heikin-Ashi open hesapla (özel formül)
        ha_open = pd.Series(index=df_clean.index, dtype=float)
        ha_open.iloc[0] = (df_clean['open'].iloc[0] + df_clean['close'].iloc[0]) / 2
        
        for i in range(1, len(df_clean)):
            ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
        
        ha_high = pd.concat([df_clean['high'], ha_open, ha_close], axis=1).max(axis=1)
        ha_low = pd.concat([df_clean['low'], ha_open, ha_close], axis=1).min(axis=1)
        
        # Killzone kontrolü (UTC saat)
        hours = df_clean.index.hour
        london_kz = (hours >= LONDON_KILLZONE_START_UTC) & (hours < LONDON_KILLZONE_END_UTC)
        ny_kz = (hours >= NY_KILLZONE_START_UTC) & (hours < NY_KILLZONE_END_UTC)
        in_killzone = london_kz | ny_kz
        
        # RSI6 ve SMA50 - pandas Series olarak kalmalı
        rsi6_series = rsi(ha_close, RSI6_LENGTH)
        sma50_series = rsi6_series.rolling(SMA50_LENGTH).mean()
        
        # pandas Series üzerinde boolean operasyonları
        rsi6_crossover = (rsi6_series > sma50_series) & (rsi6_series.shift(1) <= sma50_series.shift(1))
        rsi6_crossunder = (rsi6_series < sma50_series) & (rsi6_series.shift(1) >= sma50_series.shift(1))
        
        # CRT (Compression → Release → Thrust)
        ha_range = ha_high - ha_low
        avg_range = ha_range.rolling(CRT_LOOKBACK).mean()
        narrow_prev = ha_range.shift(1) < (avg_range.shift(1) * CRT_RANGE_MULTIPLIER)
        wide_now = ha_range > (avg_range * CRT_RANGE_MULTIPLIER)
        
        # DataFrame değerlerine erişim
        crt_buy = narrow_prev & wide_now & (ha_close > ha_open) & (ha_close > df_clean['high'].shift(1))
        crt_sell = narrow_prev & wide_now & (ha_close < ha_open) & (ha_close < df_clean['low'].shift(1))
        
        # Diğer patternler
        mom_buy = (df_clean['close'] > df_clean['close'].shift(1)) & (df_clean['close'] > df_clean['close'].shift(2))
        mom_sell = (df_clean['close'] < df_clean['close'].shift(1)) & (df_clean['close'] < df_clean['close'].shift(2))
        
        # FVG (Fair Value Gap)
        fvg_up = (df_clean['low'].shift(1) > df_clean['high'].shift(-1)) & (df_clean['close'] > df_clean['open'])
        fvg_down = (df_clean['high'].shift(1) < df_clean['low'].shift(-1)) & (df_clean['close'] < df_clean['open'])
        
        # Engulfing pattern
        bullish_engulfing = (df_clean['close'].shift(1) < df_clean['open'].shift(1)) & \
                           (df_clean['open'] < df_clean['close'].shift(1)) & \
                           (df_clean['close'] > df_clean['open'].shift(1))
        
        bearish_engulfing = (df_clean['close'].shift(1) > df_clean['open'].shift(1)) & \
                           (df_clean['open'] > df_clean['close'].shift(1)) & \
                           (df_clean['close'] < df_clean['open'].shift(1))
        
        # Pin bar
        body = (df_clean['close'] - df_clean['open']).abs()
        lower_wick = df_clean[['open', 'close']].min(axis=1) - df_clean['low']
        upper_wick = df_clean['high'] - df_clean[['open', 'close']].max(axis=1)
        total_range = df_clean['high'] - df_clean['low'] + 1e-8
        
        bullish_pin = (lower_wick > 2 * body) & (upper_wick < body)
        bearish_pin = (upper_wick > 2 * body) & (lower_wick < body)
        
        # Displacement
        displacement_up = (df_clean['close'] - df_clean['open']) > (total_range * 0.8)
        displacement_down = (df_clean['open'] - df_clean['close']) > (total_range * 0.8)
        
        # Skor hesaplama (son mum) - pandas Series'den değer al
        score = 0
        last_idx = -1
        
        # .iloc yerine .iat veya değer kontrolü
        if rsi6_crossover.iat[last_idx] if hasattr(rsi6_crossover, 'iat') else rsi6_crossover.iloc[last_idx]:
            score += 35
        if rsi6_crossunder.iat[last_idx] if hasattr(rsi6_crossunder, 'iat') else rsi6_crossunder.iloc[last_idx]:
            score -= 35
        
        if rsi6_series.iat[last_idx] > RSI_OB_LEVEL:
            score += 15
        
        if crt_buy.iat[last_idx] if hasattr(crt_buy, 'iat') else crt_buy.iloc[last_idx]:
            score += 40
        if crt_sell.iat[last_idx] if hasattr(crt_sell, 'iat') else crt_sell.iloc[last_idx]:
            score -= 40
        
        if fvg_up.iat[last_idx] if hasattr(fvg_up, 'iat') else fvg_up.iloc[last_idx]:
            score += 30
        if fvg_down.iat[last_idx] if hasattr(fvg_down, 'iat') else fvg_down.iloc[last_idx]:
            score -= 30
        
        if bullish_engulfing.iat[last_idx] if hasattr(bullish_engulfing, 'iat') else bullish_engulfing.iloc[last_idx]:
            score += 25
        if bearish_engulfing.iat[last_idx] if hasattr(bearish_engulfing, 'iat') else bearish_engulfing.iloc[last_idx]:
            score -= 25
        
        if bullish_pin.iat[last_idx] if hasattr(bullish_pin, 'iat') else bullish_pin.iloc[last_idx]:
            score += 20
        if bearish_pin.iat[last_idx] if hasattr(bearish_pin, 'iat') else bearish_pin.iloc[last_idx]:
            score -= 20
        
        if displacement_up.iat[last_idx] if hasattr(displacement_up, 'iat') else displacement_up.iloc[last_idx]:
            score += 25
        if displacement_down.iat[last_idx] if hasattr(displacement_down, 'iat') else displacement_down.iloc[last_idx]:
            score -= 25
        
        if mom_buy.iat[last_idx] if hasattr(mom_buy, 'iat') else mom_buy.iloc[last_idx]:
            score += 25
        if mom_sell.iat[last_idx] if hasattr(mom_sell, 'iat') else mom_sell.iloc[last_idx]:
            score -= 25
        
        if in_killzone.iat[last_idx] if hasattr(in_killzone, 'iat') else in_killzone.iloc[last_idx]:
            score += 25
        
        if london_kz.iat[last_idx] if hasattr(london_kz, 'iat') else london_kz.iloc[last_idx]:
            score += 15
        
        # Skoru 0-100 aralığına normalize et
        normalized_score = int(np.clip((score + 100), 0, 200) / 2)
        
        if normalized_score < SIGNAL_STRENGTH:
            logger.info(f"{symbol}/{timeframe}: Skor yetersiz: {normalized_score} < {SIGNAL_STRENGTH}")
            return None
        
        current_price = float(df_clean['close'].iat[last_idx])
        signal_text = "🚀 ICT GÜÇLÜ ALIM SİNYALİ" if score > 0 else "🔥 ICT GÜÇLÜ SATIM SİNYALİ"
        
        triggers = []
        if crt_buy.iat[last_idx] if hasattr(crt_buy, 'iat') else crt_buy.iloc[last_idx]:
            triggers.append("CRT Alım")
        if crt_sell.iat[last_idx] if hasattr(crt_sell, 'iat') else crt_sell.iloc[last_idx]:
            triggers.append("CRT Satım")
        if fvg_up.iat[last_idx] if hasattr(fvg_up, 'iat') else fvg_up.iloc[last_idx]:
            triggers.append("FVG↑")
        if fvg_down.iat[last_idx] if hasattr(fvg_down, 'iat') else fvg_down.iloc[last_idx]:
            triggers.append("FVG↓")
        if bullish_engulfing.iat[last_idx] if hasattr(bullish_engulfing, 'iat') else bullish_engulfing.iloc[last_idx]:
            triggers.append("Engulfing↑")
        if bearish_engulfing.iat[last_idx] if hasattr(bearish_engulfing, 'iat') else bearish_engulfing.iloc[last_idx]:
            triggers.append("Engulfing↓")
        if bullish_pin.iat[last_idx] if hasattr(bullish_pin, 'iat') else bullish_pin.iloc[last_idx]:
            triggers.append("Pin Bar↑")
        if bearish_pin.iat[last_idx] if hasattr(bearish_pin, 'iat') else bearish_pin.iloc[last_idx]:
            triggers.append("Pin Bar↓")
        if displacement_up.iat[last_idx] if hasattr(displacement_up, 'iat') else displacement_up.iloc[last_idx]:
            triggers.append("Displacement↑")
        if displacement_down.iat[last_idx] if hasattr(displacement_down, 'iat') else displacement_down.iloc[last_idx]:
            triggers.append("Displacement↓")
        if mom_buy.iat[last_idx] if hasattr(mom_buy, 'iat') else mom_buy.iloc[last_idx]:
            triggers.append("Momentum↑")
        if mom_sell.iat[last_idx] if hasattr(mom_sell, 'iat') else mom_sell.iloc[last_idx]:
            triggers.append("Momentum↓")
        
        killzone_name = "London" if (london_kz.iat[last_idx] if hasattr(london_kz, 'iat') else london_kz.iloc[last_idx]) else \
                       "New York" if (ny_kz.iat[last_idx] if hasattr(ny_kz, 'iat') else ny_kz.iloc[last_idx]) else "Normal"
        
        pair = symbol.replace("USDT", "/USDT")
        
        result = {
            "pair": pair,
            "timeframe": timeframe.upper(),
            "current_price": round(current_price, 6 if current_price < 1 else 4),
            "signal": signal_text,
            "score": normalized_score,
            "last_update": datetime.utcnow().strftime("%H:%M:%S UTC"),
            "killzone": killzone_name,
            "triggers": " | ".join(triggers) if triggers else "RSI6 + SMA50",
            "strength": "ÇOK YÜKSEK" if normalized_score >= 85 else "YÜKSEK"
        }
        
        logger.info(f"{symbol}/{timeframe}: Sinyal üretildi: {result['signal']}, Skor: {result['score']}")
        return result
        
    except Exception as e:
        logger.error(f"ICT sinyal hatası {symbol}/{timeframe}: {str(e)}", exc_info=True)
        return None


# BASİT SİNYAL ÜRETİCİ - FALLBACK
def generate_simple_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """Basit sinyal üret - hata durumunda fallback"""
    try:
        if len(df) < 10:
            return None
        
        # DataFrame kontrolü
        if not isinstance(df, pd.DataFrame):
            return None
        
        # Close price'ı bul
        if 'close' in df.columns:
            close_prices = df['close']
        elif len(df.columns) >= 5:
            close_prices = df.iloc[:, 4]  # 5. sütun genellikle close
        else:
            return None
        
        close_prices = pd.to_numeric(close_prices, errors='coerce').dropna()
        
        if len(close_prices) < 2:
            return None
        
        last_price = float(close_prices.iloc[-1])
        prev_price = float(close_prices.iloc[-2])
        change = ((last_price - prev_price) / prev_price * 100) if prev_price else 0
        
        signal = "🚀 ALIM" if change > 0 else "🔥 SATIM" if change < 0 else "⏸️ BEKLE"
        score = min(abs(int(change * 20)), 95)
        
        return {
            "pair": symbol.replace("USDT", "/USDT"),
            "timeframe": timeframe.upper(),
            "current_price": round(last_price, 4),
            "signal": signal,
            "score": score,
            "last_update": datetime.utcnow().strftime("%H:%M:%S UTC"),
            "killzone": "Normal",
            "triggers": f"Fiyat değişimi: {change:.2f}%",
            "strength": "YÜKSEK" if abs(change) > 2 else "ORTA" if abs(change) > 1 else "DÜŞÜK"
        }
    except Exception as e:
        logger.error(f"Basit sinyal hatası: {e}")
        return None
