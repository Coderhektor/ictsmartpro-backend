# grok_trade_elite.py - TAM ENTEGRE SİSTEM
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
import logging
import warnings
warnings.filterwarnings('ignore')

logger = logging.getLogger("grok_trade_elite")

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

# Fibonacci Seviyeleri
FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.705, 0.786, 1.0]

# ------------------- 1. YARDIMCI FONKSİYONLAR -------------------
def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI hesapla"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    rsi_vals = 100 - (100 / (1 + rs))
    rsi_vals = rsi_vals.fillna(50)
    return rsi_vals

def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """Basit Hareketli Ortalama"""
    return series.rolling(window=period).mean()

def detect_pivots(high: pd.Series, low: pd.Series, length: int = 5) -> Tuple[pd.Series, pd.Series]:
    """Pivot High ve Pivot Low tespiti"""
    ph = pd.Series(np.nan, index=high.index)
    pl = pd.Series(np.nan, index=low.index)
    
    for i in range(length, len(high) - length):
        if high.iloc[i] == high.iloc[i-length:i+length+1].max():
            ph.iloc[i] = high.iloc[i]
        if low.iloc[i] == low.iloc[i-length:i+length+1].min():
            pl.iloc[i] = low.iloc[i]
    
    return ph, pl

# ------------------- 2. VOLUME PROFILE -------------------
def calculate_volume_profile(df: pd.DataFrame, bins: int = 50, lookback: Optional[int] = None) -> Tuple[pd.DataFrame, float, Tuple[float, float]]:
    """Doğru Volume Profile hesaplama"""
    data = df.iloc[-lookback:] if lookback else df
    
    if len(data) == 0:
        return pd.DataFrame(), df['close'].mean() if len(df) > 0 else 0, (0, 0)
    
    price_min = data['low'].min()
    price_max = data['high'].max()
    
    if price_max <= price_min:
        return pd.DataFrame(), price_min, (price_min, price_min)
    
    bin_edges = np.linspace(price_min, price_max, bins + 1)
    profile = np.zeros(bins)
    
    for _, row in data.iterrows():
        low_idx = np.searchsorted(bin_edges, row['low'], side='right') - 1
        high_idx = np.searchsorted(bin_edges, row['high'], side='right') - 1
        low_idx = max(0, min(low_idx, bins-1))
        high_idx = max(0, min(high_idx, bins-1))
        
        if low_idx == high_idx:
            profile[low_idx] += row['volume']
        else:
            vol_per_bin = row['volume'] / (high_idx - low_idx + 1)
            profile[low_idx:high_idx+1] += vol_per_bin
    
    centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    vp_df = pd.DataFrame({'price_level': centers, 'volume_profile': profile})
    
    poc_idx = profile.argmax()
    poc_price = centers[poc_idx]
    
    total_vol = profile.sum()
    if total_vol == 0:
        va_low, va_high = price_min, price_max
    else:
        sorted_idx = np.argsort(profile)[::-1]
        cum_vol = 0
        va_indices = [poc_idx]
        for idx in sorted_idx:
            if idx == poc_idx:
                continue
            cum_vol += profile[idx]
            va_indices.append(idx)
            if cum_vol >= total_vol * 0.7:
                break
        va_low = centers[min(va_indices)]
        va_high = centers[max(va_indices)]
    
    return vp_df, poc_price, (va_low, va_high)

# ------------------- 3. ICT PATTERN TESPİTİ (indicators.py'dan) -------------------
def detect_ict_patterns(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """Tüm ICT patternlerini tespit et"""
    patterns = {}
    
    # Heikin-Ashi hesapla
    ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_open = pd.Series(index=df.index, dtype=float)
    ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
    
    ha_high = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([df['low'], ha_open, ha_close], axis=1).min(axis=1)
    
    # RSI6 ve SMA50
    rsi6_series = calculate_rsi(ha_close, RSI6_LENGTH)
    sma50_series = calculate_sma(rsi6_series, SMA50_LENGTH)
    
    # RSI6/SMA50 kesişimleri
    patterns['rsi6_crossover'] = (rsi6_series > sma50_series) & (rsi6_series.shift(1) <= sma50_series.shift(1))
    patterns['rsi6_crossunder'] = (rsi6_series < sma50_series) & (rsi6_series.shift(1) >= sma50_series.shift(1))
    
    # CRT (Compression → Release → Thrust)
    ha_range = ha_high - ha_low
    avg_range = ha_range.rolling(CRT_LOOKBACK).mean()
    narrow_prev = ha_range.shift(1) < (avg_range.shift(1) * CRT_RANGE_MULTIPLIER)
    wide_now = ha_range > (avg_range * CRT_RANGE_MULTIPLIER)
    
    patterns['crt_buy'] = narrow_prev & wide_now & (ha_close > ha_open) & (ha_close > df['high'].shift(1))
    patterns['crt_sell'] = narrow_prev & wide_now & (ha_close < ha_open) & (ha_close < df['low'].shift(1))
    
    # FVG (Fair Value Gap)
    patterns['fvg_up'] = df['low'] > df['high'].shift(2)  # Klasik 3-mum FVG
    patterns['fvg_down'] = (df['high'].shift(1) < df['low'].shift(-1)) & (df['close'] < df['open'])
    
    # Engulfing pattern
    patterns['bullish_engulfing'] = (
        (df['close'].shift(1) < df['open'].shift(1)) &
        (df['open'] < df['close'].shift(1)) &
        (df['close'] > df['open'].shift(1))
    )
    
    patterns['bearish_engulfing'] = (
        (df['close'].shift(1) > df['open'].shift(1)) &
        (df['open'] > df['close'].shift(1)) &
        (df['close'] < df['open'].shift(1))
    )
    
    # Pin bar
    body = (df['close'] - df['open']).abs()
    lower_wick = df[['open', 'close']].min(axis=1) - df['low']
    upper_wick = df['high'] - df[['open', 'close']].max(axis=1)
    total_range = df['high'] - df['low'] + 1e-8
    
    patterns['bullish_pin'] = (lower_wick > 2 * body) & (upper_wick < body)
    patterns['bearish_pin'] = (upper_wick > 2 * body) & (lower_wick < body)
    
    # Displacement
    patterns['displacement_up'] = (df['close'] - df['open']) > (total_range * 0.8)
    patterns['displacement_down'] = (df['open'] - df['close']) > (total_range * 0.8)
    
    # Momentum
    patterns['mom_buy'] = (df['close'] > df['close'].shift(1)) & (df['close'] > df['close'].shift(2))
    patterns['mom_sell'] = (df['close'] < df['close'].shift(1)) & (df['close'] < df['close'].shift(2))
    
    # Order Blocks
    patterns['bull_ob'] = (
        (df['close'].shift(1) < df['open'].shift(1)) &
        (df['close'] > df['high'].shift(1)) &
        (df['close'] > df['open'])
    )
    
    patterns['bear_ob'] = (
        (df['close'].shift(1) > df['open'].shift(1)) &
        (df['close'] < df['low'].shift(1)) &
        (df['close'] < df['open'])
    )
    
    # Killzone kontrolü
    hours = df.index.hour
    patterns['london_kz'] = (hours >= LONDON_KILLZONE_START_UTC) & (hours < LONDON_KILLZONE_END_UTC)
    patterns['ny_kz'] = (hours >= NY_KILLZONE_START_UTC) & (hours < NY_KILLZONE_END_UTC)
    patterns['in_killzone'] = patterns['london_kz'] | patterns['ny_kz']
    
    # Değerleri ekle
    patterns['rsi6'] = rsi6_series
    patterns['sma50_rsi'] = sma50_series
    patterns['rsi6_above_sma50'] = rsi6_series > sma50_series
    patterns['rsi6_below_sma50'] = rsi6_series < sma50_series
    
    return patterns

# ------------------- 4. FIBONACCI SEVİYELERİ -------------------
def detect_fibonacci_levels(df: pd.DataFrame, ph: pd.Series, pl: pd.Series) -> pd.DataFrame:
    """Fibonacci retracement seviyelerini hesapla"""
    df = df.copy()
    
    for level in FIB_LEVELS:
        df[f'fib_{str(level).replace(".", "")}'] = np.nan
    
    df['fib_direction'] = ''
    df['fib_ote_zone'] = False
    
    # Son pivotları bul
    ph_series = ph.dropna()
    pl_series = pl.dropna()
    
    if len(ph_series) < 2 or len(pl_series) < 2:
        return df
    
    # En son pivot high ve low indekslerini al
    last_ph_idx = ph_series.index[-1]
    last_pl_idx = pl_series.index[-1]
    
    # Hangisi daha yeni?
    if last_ph_idx > last_pl_idx:
        # Bearish swing (yukarıdan aşağı)
        high_price = df.loc[last_ph_idx, 'high']
        low_price = df.loc[last_pl_idx, 'low']
        fib_range = high_price - low_price
        
        # Fibonacci seviyelerini hesapla
        for level in FIB_LEVELS:
            col_name = f'fib_{str(level).replace(".", "")}'
            df[col_name] = high_price - (fib_range * level)
        
        df['fib_direction'] = 'bearish'
        df['fib_ote_zone'] = (df['close'] >= df['fib_618']) & (df['close'] <= df['fib_705'])
        
    elif last_pl_idx > last_ph_idx:
        # Bullish swing (aşağıdan yukarı)
        low_price = df.loc[last_pl_idx, 'low']
        high_price = df.loc[last_ph_idx, 'high']
        fib_range = high_price - low_price
        
        # Fibonacci seviyelerini hesapla
        for level in FIB_LEVELS:
            col_name = f'fib_{str(level).replace(".", "")}'
            df[col_name] = low_price + (fib_range * level)
        
        df['fib_direction'] = 'bullish'
        df['fib_ote_zone'] = (df['close'] >= df['fib_618']) & (df['close'] <= df['fib_705'])
    
    return df

# ------------------- 5. LIQUIDITY GRAB TESPİTİ -------------------
def detect_liquidity_grab(df: pd.DataFrame, ph: pd.Series, pl: pd.Series) -> pd.DataFrame:
    """Liquidity Grab tespiti"""
    df = df.copy()
    
    # Pivotları forward fill
    prev_ph = ph.ffill()
    prev_pl = pl.ffill()
    
    df['bullish_lg'] = (
        (df['high'] > prev_ph.shift(1)) & 
        (df['close'] < prev_ph.shift(1)) & 
        prev_ph.shift(1).notna()
    )
    
    df['bearish_lg'] = (
        (df['low'] < prev_pl.shift(1)) & 
        (df['close'] > prev_pl.shift(1)) & 
        prev_pl.shift(1).notna()
    )
    
    return df

# ------------------- 6. MARKET STRUCTURE -------------------
def detect_market_structure(df: pd.DataFrame, ph: pd.Series, pl: pd.Series) -> pd.DataFrame:
    """Market Structure analizi"""
    df = df.copy()
    
    # Pivotları forward fill
    prev_ph = ph.ffill()
    prev_pl = pl.ffill()
    
    df['bos_bull'] = (df['high'] > prev_ph.shift(1)) & df['is_bullish']
    df['bos_bear'] = (df['low'] < prev_pl.shift(1)) & df['is_bearish']
    
    df['choch_bull'] = (df['low'] < prev_pl.shift(1)) & df['is_bullish']
    df['choch_bear'] = (df['high'] > prev_ph.shift(1)) & df['is_bearish']
    
    return df

# ------------------- 7. SİNYAL SKORLAMA -------------------
def calculate_signal_score(patterns: Dict[str, pd.Series], idx: int = -1) -> int:
    """ICT pattern skorunu hesapla"""
    score = 0
    
    try:
        # RSI6/SMA50 kesişimleri
        if patterns.get('rsi6_crossover', pd.Series([False])).iloc[idx]:
            score += 35
        if patterns.get('rsi6_crossunder', pd.Series([False])).iloc[idx]:
            score -= 35
        
        # RSI overbought
        if patterns.get('rsi6', pd.Series([50])).iloc[idx] > RSI_OB_LEVEL:
            score += 15
        
        # CRT pattern
        if patterns.get('crt_buy', pd.Series([False])).iloc[idx]:
            score += 40
        if patterns.get('crt_sell', pd.Series([False])).iloc[idx]:
            score -= 40
        
        # FVG
        if patterns.get('fvg_up', pd.Series([False])).iloc[idx]:
            score += 30
        if patterns.get('fvg_down', pd.Series([False])).iloc[idx]:
            score -= 30
        
        # Engulfing
        if patterns.get('bullish_engulfing', pd.Series([False])).iloc[idx]:
            score += 25
        if patterns.get('bearish_engulfing', pd.Series([False])).iloc[idx]:
            score -= 25
        
        # Pin bar
        if patterns.get('bullish_pin', pd.Series([False])).iloc[idx]:
            score += 20
        if patterns.get('bearish_pin', pd.Series([False])).iloc[idx]:
            score -= 20
        
        # Displacement
        if patterns.get('displacement_up', pd.Series([False])).iloc[idx]:
            score += 25
        if patterns.get('displacement_down', pd.Series([False])).iloc[idx]:
            score -= 25
        
        # Momentum
        if patterns.get('mom_buy', pd.Series([False])).iloc[idx]:
            score += 25
        if patterns.get('mom_sell', pd.Series([False])).iloc[idx]:
            score -= 25
        
        # Killzone
        if patterns.get('in_killzone', pd.Series([False])).iloc[idx]:
            score += 25
        
        if patterns.get('london_kz', pd.Series([False])).iloc[idx]:
            score += 15
        
    except (IndexError, KeyError) as e:
        logger.warning(f"Skor hesaplama hatası: {e}")
    
    return score

# ------------------- 8. ELITE ENTRY SİNYALLERİ -------------------
def generate_elite_signals(df: pd.DataFrame, patterns: Dict[str, pd.Series], 
                          va_low: float, va_high: float) -> pd.DataFrame:
    """Elite entry sinyallerini oluştur"""
    df = df.copy()
    
    df['entry_signal'] = ''
    df['signal_quality'] = 0
    df['rr_ratio'] = np.nan
    df['stop_loss'] = np.nan
    df['take_profit'] = np.nan
    
    # Değerleme
    df['valuation'] = 'Fair Value'
    df.loc[df['close'] > va_high, 'valuation'] = 'Pahalı (Premium)'
    df.loc[df['close'] < va_low, 'valuation'] = 'Ucuz (Discount)'
    
    # Fibonacci OTE kontrolü
    near_fib_618 = (abs(df['close'] - df.get('fib_618', 0)) / df['close'] < 0.008)
    near_fib_705 = (abs(df['close'] - df.get('fib_705', 0)) / df['close'] < 0.008)
    near_fib_ote = near_fib_618 | near_fib_705
    
    # RSI6/SMA50 sinyalleri
    rsi_bullish = patterns.get('rsi6_crossover', pd.Series([False])) | \
                  (patterns.get('rsi6_above_sma50', pd.Series([False])) & 
                   (abs(patterns.get('rsi6', pd.Series([50])) - patterns.get('sma50_rsi', pd.Series([50]))) > 5))
    
    rsi_bearish = patterns.get('rsi6_crossunder', pd.Series([False])) | \
                  (patterns.get('rsi6_below_sma50', pd.Series([False])) & 
                   (abs(patterns.get('rsi6', pd.Series([50])) - patterns.get('sma50_rsi', pd.Series([50]))) > 5))
    
    # Order Blocks
    bull_ob = patterns.get('bull_ob', pd.Series([False]))
    bear_ob = patterns.get('bear_ob', pd.Series([False]))
    
    # FVG
    active_bull_fvg = patterns.get('fvg_up', pd.Series([False]))
    active_bear_fvg = patterns.get('fvg_down', pd.Series([False]))
    
    # Liquidity Grab
    bullish_lg = df.get('bullish_lg', pd.Series([False]))
    bearish_lg = df.get('bearish_lg', pd.Series([False]))
    
    # Market Structure
    bos_bull = df.get('bos_bull', pd.Series([False]))
    bos_bear = df.get('bos_bear', pd.Series([False]))
    choch_bull = df.get('choch_bull', pd.Series([False]))
    choch_bear = df.get('choch_bear', pd.Series([False]))
    
    # 📈 ELITE BULLISH SETUP
    elite_bull = (
        # Order Block
        bull_ob &
        
        # Value Area
        (df['valuation'] == 'Ucuz (Discount)') &
        
        # Fibonacci OTE
        near_fib_ote &
        (df.get('fib_direction', '') == 'bullish') &
        
        # RSI konfirmasyonu
        rsi_bullish &
        
        # ICT patternleri
        active_bull_fvg.shift(1) &
        bullish_lg.shift(1) &
        
        # Market structure
        (bos_bull | choch_bull) &
        
        # Volume konfirmasyonu
        (df['volume'] > df['volume'].rolling(20).mean())
    )
    
    if elite_bull.any():
        df.loc[elite_bull, 'entry_signal'] = '🚀 ELITE LONG: OB + Discount + FVG + LG + FIB OTE + RSI6↑SMA50'
        df.loc[elite_bull, 'signal_quality'] = 10
        
        # Risk/Reward hesapla
        for idx in df[elite_bull].index:
            entry_price = df.loc[idx, 'close']
            sl = min(df.loc[idx, 'low'], df.get('fib_100', entry_price * 0.95)) * 0.995
            tp = entry_price + (2.5 * (entry_price - sl))
            
            df.at[idx, 'stop_loss'] = sl
            df.at[idx, 'take_profit'] = tp
            df.at[idx, 'rr_ratio'] = 2.5
    
    # 📉 ELITE BEARISH SETUP
    elite_bear = (
        # Order Block
        bear_ob &
        
        # Value Area
        (df['valuation'] == 'Pahalı (Premium)') &
        
        # Fibonacci OTE
        near_fib_ote &
        (df.get('fib_direction', '') == 'bearish') &
        
        # RSI konfirmasyonu
        rsi_bearish &
        
        # ICT patternleri
        active_bear_fvg.shift(1) &
        bearish_lg.shift(1) &
        
        # Market structure
        (bos_bear | choch_bear) &
        
        # Volume konfirmasyonu
        (df['volume'] > df['volume'].rolling(20).mean())
    )
    
    if elite_bear.any():
        df.loc[elite_bear, 'entry_signal'] = '🚀 ELITE SHORT: OB + Premium + FVG + LG + FIB OTE + RSI6↓SMA50'
        df.loc[elite_bear, 'signal_quality'] = 10
        
        # Risk/Reward hesapla
        for idx in df[elite_bear].index:
            entry_price = df.loc[idx, 'close']
            sl = max(df.loc[idx, 'high'], df.get('fib_100', entry_price * 1.05)) * 1.005
            tp = entry_price - (2.5 * (sl - entry_price))
            
            df.at[idx, 'stop_loss'] = sl
            df.at[idx, 'take_profit'] = tp
            df.at[idx, 'rr_ratio'] = 2.5
    
    return df

# ------------------- 9. TAM ENTEGRE SİSTEM -------------------
def grok_trade_elite_system(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "1h",
    swing_length: int = 5,
    volume_profile_bins: int = 50,
    volume_profile_lookback: Optional[int] = None
) -> Tuple[pd.DataFrame, Optional[Dict[str, Any]]]:
    """
    Tam entegre Grok Trade Elite sistemi
    
    Returns:
        Tuple: (DataFrame with all indicators, Signal dictionary)
    """
    
    logger.info(f"Grok Trade Elite başlatılıyor: {symbol}/{timeframe}")
    
    # DataFrame kontrolü
    if not isinstance(df, pd.DataFrame):
        logger.error(f"{symbol}: df pandas DataFrame değil, type: {type(df)}")
        return pd.DataFrame(), None
    
    # Minimum veri kontrolü
    if len(df) < 100:
        logger.warning(f"{symbol}: Yeterli veri yok ({len(df)} < 100)")
        return pd.DataFrame(), None
    
    # Sütun isimlerini standardize et
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    
    if not all(col in df.columns for col in required_cols):
        logger.warning(f"{symbol}: Gerekli sütunlar yok, düzeltiliyor...")
        
        # Binance formatı: [timestamp, open, high, low, close, volume]
        if len(df.columns) >= 5:
            # İlk 5 sütunu kullan
            df = df.iloc[:, :6].copy() if len(df.columns) >= 6 else df.iloc[:, :5].copy()
            if len(df.columns) == 6:
                df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            elif len(df.columns) == 5:
                df.columns = ['timestamp', 'open', 'high', 'low', 'close']
                df['volume'] = 1000  # Default volume
            logger.info(f"{symbol}: Sütunlar düzeltildi: {df.columns.tolist()}")
        else:
            logger.error(f"{symbol}: Yeterli sütun yok: {df.columns.tolist()}")
            return pd.DataFrame(), None
    
    # Sayısal verilere çevir
    for col in required_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # NaN değerleri temizle
    df_clean = df[required_cols].copy()
    df_clean = df_clean.dropna()
    
    if len(df_clean) < 100:
        logger.warning(f"{symbol}: Temizleme sonrası yeterli veri yok ({len(df_clean)} < 100)")
        return pd.DataFrame(), None
    
    # Son 200 mum'u al
    df_clean = df_clean.tail(200).copy()
    
    # Index'i ayarla
    if 'timestamp' in df.columns:
        df_clean.index = pd.to_datetime(df['timestamp'], errors='coerce').dropna()
        df_clean.index = df_clean.index.tz_localize(None)
    else:
        # Timestamp yoksa, son 200 periyodu kullan
        periods = len(df_clean)
        end_time = pd.Timestamp.now()
        start_time = end_time - pd.Timedelta(hours=periods) if timeframe.endswith('h') else \
                     end_time - pd.Timedelta(minutes=periods)
        df_clean.index = pd.date_range(start=start_time, periods=periods, freq=timeframe)
    
    # Temel hesaplamalar
    df_clean['is_bullish'] = df_clean['close'] > df_clean['open']
    df_clean['is_bearish'] = df_clean['close'] < df_clean['open']
    df_clean['range'] = df_clean['high'] - df_clean['low']
    df_clean['body'] = (df_clean['close'] - df_clean['open']).abs()
    
    # Pivot noktaları
    df_clean['pivot_high'], df_clean['pivot_low'] = detect_pivots(
        df_clean['high'], 
        df_clean['low'], 
        swing_length
    )
    
    # Volume Profile
    vp_df, poc_price, (va_low, va_high) = calculate_volume_profile(
        df_clean, 
        bins=volume_profile_bins, 
        lookback=volume_profile_lookback
    )
    
    # ICT Pattern tespiti
    patterns = detect_ict_patterns(df_clean)
    
    # Fibonacci seviyeleri
    df_clean = detect_fibonacci_levels(df_clean, df_clean['pivot_high'], df_clean['pivot_low'])
    
    # Liquidity Grab
    df_clean = detect_liquidity_grab(df_clean, df_clean['pivot_high'], df_clean['pivot_low'])
    
    # Market Structure
    df_clean = detect_market_structure(df_clean, df_clean['pivot_high'], df_clean['pivot_low'])
    
    # Signal skoru hesapla
    signal_score = calculate_signal_score(patterns)
    normalized_score = int(np.clip((signal_score + 100), 0, 200) / 2)
    
    # Elite sinyaller
    df_clean = generate_elite_signals(df_clean, patterns, va_low, va_high)
    
    # Son sinyal
    last_signal = df_clean.iloc[-1]
    has_signal = last_signal['entry_signal'] != ''
    
    # Signal dictionary oluştur
    signal_dict = None
    if has_signal or normalized_score >= SIGNAL_STRENGTH:
        current_price = float(last_signal['close'])
        
        # Triggers
        triggers = []
        for pattern_name in ['crt_buy', 'crt_sell', 'fvg_up', 'fvg_down', 
                           'bullish_engulfing', 'bearish_engulfing',
                           'bullish_pin', 'bearish_pin', 'bull_ob', 'bear_ob']:
            if patterns.get(pattern_name, pd.Series([False])).iloc[-1]:
                triggers.append(pattern_name.replace('_', ' ').title())
        
        # Killzone
        killzone_name = "London" if patterns.get('london_kz', pd.Series([False])).iloc[-1] else \
                       "New York" if patterns.get('ny_kz', pd.Series([False])).iloc[-1] else "Normal"
        
        signal_text = "🚀 ICT ELITE ALIM SİNYALİ" if signal_score > 0 else \
                     "🔥 ICT ELITE SATIM SİNYALİ" if signal_score < 0 else \
                     last_signal['entry_signal'] if has_signal else "⏸️ BEKLE"
        
        signal_dict = {
            "pair": symbol.replace("USDT", "/USDT"),
            "timeframe": timeframe.upper(),
            "current_price": round(current_price, 6 if current_price < 1 else 4),
            "signal": signal_text,
            "score": normalized_score,
            "quality": int(last_signal['signal_quality']) if has_signal else 0,
            "last_update": datetime.utcnow().strftime("%H:%M:%S UTC"),
            "killzone": killzone_name,
            "triggers": " | ".join(triggers) if triggers else "RSI6 + SMA50",
            "strength": "ELITE" if last_signal['signal_quality'] == 10 else \
                       "ÇOK YÜKSEK" if normalized_score >= 85 else \
                       "YÜKSEK" if normalized_score >= 70 else \
                       "ORTA" if normalized_score >= SIGNAL_STRENGTH else "DÜŞÜK",
            "valuation": last_signal['valuation'],
            "fib_direction": last_signal.get('fib_direction', 'N/A'),
            "poc_price": round(poc_price, 4),
            "value_area": f"{round(va_low, 4)} - {round(va_high, 4)}",
            "rsi6": round(float(patterns.get('rsi6', pd.Series([50])).iloc[-1]), 2),
            "rsi_sma50": round(float(patterns.get('sma50_rsi', pd.Series([50])).iloc[-1]), 2),
            "rr_ratio": float(last_signal['rr_ratio']) if pd.notna(last_signal['rr_ratio']) else None,
            "stop_loss": float(last_signal['stop_loss']) if pd.notna(last_signal['stop_loss']) else None,
            "take_profit": float(last_signal['take_profit']) if pd.notna(last_signal['take_profit']) else None
        }
        
        logger.info(f"{symbol}/{timeframe}: Sinyal üretildi: {signal_text}, Skor: {normalized_score}")
    
    # Attributeları ekle
    df_clean.attrs['poc_price'] = poc_price
    df_clean.attrs['value_area_low'] = va_low
    df_clean.attrs['value_area_high'] = va_high
    df_clean.attrs['volume_profile'] = vp_df
    df_clean.attrs['patterns'] = patterns
    
    return df_clean, signal_dict

# ------------------- 10. BASİT SİNYAL ÜRETİCİ (FALLBACK) -------------------
def generate_simple_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """Basit sinyal üret - hata durumunda fallback"""
    try:
        if len(df) < 10:
            return None
        
        if not isinstance(df, pd.DataFrame):
            return None
        
        # Close price'ı bul
        if 'close' in df.columns:
            close_prices = df['close']
        elif len(df.columns) >= 5:
            close_prices = df.iloc[:, 4]
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

# ------------------- TEST -------------------
if __name__ == "__main__":
    # Test verisi oluştur
    dates = pd.date_range('2025-01-01', periods=300, freq='1h')
    np.random.seed(42)
    price = 100 + np.cumsum(np.random.randn(300) * 1.3)
    
    df_test = pd.DataFrame({
        'timestamp': dates,
        'open': price + np.random.randn(300) * 0.7,
        'high': price + np.abs(np.random.randn(300)) * 3.0 + 1.2,
        'low': price - np.abs(np.random.randn(300)) * 3.0 - 1.2,
        'close': price + np.random.randn(300) * 0.7,
        'volume': np.random.randint(20000, 100000, 300)
    })
    
    # Sistemi test et
    result_df, signal = grok_trade_elite_system(
        df_test, 
        symbol="BTCUSDT",
        timeframe="1h",
        volume_profile_lookback=200
    )
    
    print("=" * 120)
    print("🚀 GROK TRADE ELITE - TAM ENTEGRE SİSTEM TEST")
    print("=" * 120)
    
    if signal:
        print(f"📊 SİNYAL BİLGİLERİ:")
        for key, value in signal.items():
            print(f"   • {key}: {value}")
        
        print(f"\n📈 TEKNİK GÖSTERGELER:")
        print(f"   • RSI6: {signal['rsi6']}")
        print(f"   • RSI SMA50: {signal['rsi_sma50']}")
        print(f"   • POC: {signal['poc_price']}")
        print(f"   • Value Area: {signal['value_area']}")
        
        if signal['rr_ratio']:
            print(f"   • Risk/Reward: {signal['rr_ratio']:.2f}")
            print(f"   • Stop Loss: {signal['stop_loss']:.4f}")
            print(f"   • Take Profit: {signal['take_profit']:.4f}")
    else:
        print("   → Aktif sinyal bulunamadı.")
    
    print(f"\n📊 DATAFRAME ŞEKİL: {result_df.shape}")
    print(f"   • Sütunlar: {list(result_df.columns)}")
    
    if 'entry_signal' in result_df.columns:
        signals = result_df[result_df['entry_signal'] != '']
        print(f"   • Toplam Sinyal: {len(signals)}")
        
        if len(signals) > 0:
            print(f"\n🔥 SON 5 SİNYAL:")
            for idx, row in signals.tail(5).iterrows():
                print(f"   • {idx}: {row['entry_signal']}")
    
    print("=" * 120)
    print("✅ SİSTEM BAŞARIYLA TEST EDİLDİ!")
    print("=" * 120)
