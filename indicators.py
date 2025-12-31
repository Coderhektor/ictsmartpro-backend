# indicators.py - GROK TRADE ELITE (CANLI PROD - WEB SOCKET UYUMLU)
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
import logging

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

FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.705, 0.786, 1.0]

# ------------------- YARDIMCI FONKSİYONLAR (SENİN KODUNDAN ALINDI) -------------------
def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
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
    return series.rolling(window=period).mean()

def detect_pivots(high: pd.Series, low: pd.Series, length: int = 5) -> Tuple[pd.Series, pd.Series]:
    ph = pd.Series(np.nan, index=high.index)
    pl = pd.Series(np.nan, index=low.index)
    
    for i in range(length, len(high) - length):
        if high.iloc[i] == high.iloc[i-length:i+length+1].max():
            ph.iloc[i] = high.iloc[i]
        if low.iloc[i] == low.iloc[i-length:i+length+1].min():
            pl.iloc[i] = low.iloc[i]
    
    return ph, pl

def calculate_volume_profile(df: pd.DataFrame, bins: int = 50, lookback: Optional[int] = None) -> Tuple[pd.DataFrame, float, Tuple[float, float]]:
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

def detect_ict_patterns(df: pd.DataFrame) -> Dict[str, pd.Series]:
    patterns = {}
    
    ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_open = pd.Series(index=df.index, dtype=float)
    ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
    
    ha_high = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([df['low'], ha_open, ha_close], axis=1).min(axis=1)
    
    rsi6_series = calculate_rsi(ha_close, RSI6_LENGTH)
    sma50_series = calculate_sma(rsi6_series, SMA50_LENGTH)
    
    patterns['rsi6_crossover'] = (rsi6_series > sma50_series) & (rsi6_series.shift(1) <= sma50_series.shift(1))
    patterns['rsi6_crossunder'] = (rsi6_series < sma50_series) & (rsi6_series.shift(1) >= sma50_series.shift(1))
    
    ha_range = ha_high - ha_low
    avg_range = ha_range.rolling(CRT_LOOKBACK).mean()
    narrow_prev = ha_range.shift(1) < (avg_range.shift(1) * CRT_RANGE_MULTIPLIER)
    wide_now = ha_range > (avg_range * CRT_RANGE_MULTIPLIER)
    
    patterns['crt_buy'] = narrow_prev & wide_now & (ha_close > ha_open) & (ha_close > df['high'].shift(1))
    patterns['crt_sell'] = narrow_prev & wide_now & (ha_close < ha_open) & (ha_close < df['low'].shift(1))
    
    patterns['fvg_up'] = df['low'] > df['high'].shift(2)
    patterns['fvg_down'] = (df['high'].shift(1) < df['low'].shift(-1)) & (df['close'] < df['open'])
    
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
    
    body = (df['close'] - df['open']).abs()
    lower_wick = df[['open', 'close']].min(axis=1) - df['low']
    upper_wick = df['high'] - df[['open', 'close']].max(axis=1)
    total_range = df['high'] - df['low'] + 1e-8
    
    patterns['bullish_pin'] = (lower_wick > 2 * body) & (upper_wick < body)
    patterns['bearish_pin'] = (upper_wick > 2 * body) & (lower_wick < body)
    
    patterns['displacement_up'] = (df['close'] - df['open']) > (total_range * 0.8)
    patterns['displacement_down'] = (df['open'] - df['close']) > (total_range * 0.8)
    
    patterns['mom_buy'] = (df['close'] > df['close'].shift(1)) & (df['close'] > df['close'].shift(2))
    patterns['mom_sell'] = (df['close'] < df['close'].shift(1)) & (df['close'] < df['close'].shift(2))
    
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
    
    hours = df.index.hour
    patterns['london_kz'] = (hours >= LONDON_KILLZONE_START_UTC) & (hours < LONDON_KILLZONE_END_UTC)
    patterns['ny_kz'] = (hours >= NY_KILLZONE_START_UTC) & (hours < NY_KILLZONE_END_UTC)
    patterns['in_killzone'] = patterns['london_kz'] | patterns['ny_kz']
    
    patterns['rsi6'] = rsi6_series
    patterns['sma50_rsi'] = sma50_series
    patterns['rsi6_above_sma50'] = rsi6_series > sma50_series
    patterns['rsi6_below_sma50'] = rsi6_series < sma50_series
    
    return patterns

def detect_fibonacci_levels(df: pd.DataFrame, ph: pd.Series, pl: pd.Series) -> pd.DataFrame:
    df = df.copy()
    
    for level in FIB_LEVELS:
        df[f'fib_{str(level).replace(".", "")}'] = np.nan
    
    df['fib_direction'] = ''
    df['fib_ote_zone'] = False
    
    ph_series = ph.dropna()
    pl_series = pl.dropna()
    
    if len(ph_series) < 2 or len(pl_series) < 2:
        return df
    
    last_ph_idx = ph_series.index[-1]
    last_pl_idx = pl_series.index[-1]
    
    if last_ph_idx > last_pl_idx:
        high_price = df.loc[last_ph_idx, 'high']
        low_price = df.loc[last_pl_idx, 'low']
        fib_range = high_price - low_price
        
        for level in FIB_LEVELS:
            col_name = f'fib_{str(level).replace(".", "")}'
            df[col_name] = high_price - (fib_range * level)
        
        df['fib_direction'] = 'bearish'
        df['fib_ote_zone'] = (df['close'] >= df['fib_618']) & (df['close'] <= df['fib_705'])
        
    elif last_pl_idx > last_ph_idx:
        low_price = df.loc[last_pl_idx, 'low']
        high_price = df.loc[last_ph_idx, 'high']
        fib_range = high_price - low_price
        
        for level in FIB_LEVELS:
            col_name = f'fib_{str(level).replace(".", "")}'
            df[col_name] = low_price + (fib_range * level)
        
        df['fib_direction'] = 'bullish'
        df['fib_ote_zone'] = (df['close'] >= df['fib_618']) & (df['close'] <= df['fib_705'])
    
    return df

def detect_liquidity_grab(df: pd.DataFrame, ph: pd.Series, pl: pd.Series) -> pd.DataFrame:
    df = df.copy()
    
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

def detect_market_structure(df: pd.DataFrame, ph: pd.Series, pl: pd.Series) -> pd.DataFrame:
    df = df.copy()
    
    prev_ph = ph.ffill()
    prev_pl = pl.ffill()
    
    df['bos_bull'] = (df['high'] > prev_ph.shift(1)) & df['is_bullish']
    df['bos_bear'] = (df['low'] < prev_pl.shift(1)) & df['is_bearish']
    
    df['choch_bull'] = (df['low'] < prev_pl.shift(1)) & df['is_bullish']
    df['choch_bear'] = (df['high'] > prev_ph.shift(1)) & df['is_bearish']
    
    return df

def calculate_signal_score(patterns: Dict[str, pd.Series], idx: int = -1) -> int:
    score = 0
    
    try:
        if patterns.get('rsi6_crossover', pd.Series([False])).iloc[idx]:
            score += 35
        if patterns.get('rsi6_crossunder', pd.Series([False])).iloc[idx]:
            score -= 35
        
        if patterns.get('rsi6', pd.Series([50])).iloc[idx] > RSI_OB_LEVEL:
            score += 15
        
        if patterns.get('crt_buy', pd.Series([False])).iloc[idx]:
            score += 40
        if patterns.get('crt_sell', pd.Series([False])).iloc[idx]:
            score -= 40
        
        if patterns.get('fvg_up', pd.Series([False])).iloc[idx]:
            score += 30
        if patterns.get('fvg_down', pd.Series([False])).iloc[idx]:
            score -= 30
        
        if patterns.get('bullish_engulfing', pd.Series([False])).iloc[idx]:
            score += 25
        if patterns.get('bearish_engulfing', pd.Series([False])).iloc[idx]:
            score -= 25
        
        if patterns.get('bullish_pin', pd.Series([False])).iloc[idx]:
            score += 20
        if patterns.get('bearish_pin', pd.Series([False])).iloc[idx]:
            score -= 20
        
        if patterns.get('displacement_up', pd.Series([False])).iloc[idx]:
            score += 25
        if patterns.get('displacement_down', pd.Series([False])).iloc[idx]:
            score -= 25
        
        if patterns.get('mom_buy', pd.Series([False])).iloc[idx]:
            score += 25
        if patterns.get('mom_sell', pd.Series([False])).iloc[idx]:
            score -= 25
        
        if patterns.get('in_killzone', pd.Series([False])).iloc[idx]:
            score += 25
        
        if patterns.get('london_kz', pd.Series([False])).iloc[idx]:
            score += 15
        
    except Exception as e:
        logger.warning(f"Skor hesaplama hatası: {e}")
    
    return score

def generate_elite_signals(df: pd.DataFrame, patterns: Dict[str, pd.Series], va_low: float, va_high: float) -> pd.DataFrame:
    df = df.copy()
    
    df['entry_signal'] = ''
    df['signal_quality'] = 0
    df['rr_ratio'] = np.nan
    df['stop_loss'] = np.nan
    df['take_profit'] = np.nan
    
    df['valuation'] = 'Fair Value'
    df.loc[df['close'] > va_high, 'valuation'] = 'Pahalı (Premium)'
    df.loc[df['close'] < va_low, 'valuation'] = 'Ucuz (Discount)'
    
    near_fib_618 = (abs(df['close'] - df.get('fib_618', 0)) / df['close'] < 0.008)
    near_fib_705 = (abs(df['close'] - df.get('fib_705', 0)) / df['close'] < 0.008)
    near_fib_ote = near_fib_618 | near_fib_705
    
    rsi_bullish = patterns.get('rsi6_crossover', pd.Series([False])) | \
                  (patterns.get('rsi6_above_sma50', pd.Series([False])) & 
                   (abs(patterns.get('rsi6', pd.Series([50])) - patterns.get('sma50_rsi', pd.Series([50]))) > 5))
    
    rsi_bearish = patterns.get('rsi6_crossunder', pd.Series([False])) | \
                  (patterns.get('rsi6_below_sma50', pd.Series([False])) & 
                   (abs(patterns.get('rsi6', pd.Series([50])) - patterns.get('sma50_rsi', pd.Series([50]))) > 5))
    
    bull_ob = patterns.get('bull_ob', pd.Series([False]))
    bear_ob = patterns.get('bear_ob', pd.Series([False]))
    
    active_bull_fvg = patterns.get('fvg_up', pd.Series([False]))
    active_bear_fvg = patterns.get('fvg_down', pd.Series([False]))
    
    bullish_lg = df.get('bullish_lg', pd.Series([False]))
    bearish_lg = df.get('bearish_lg', pd.Series([False]))
    
    bos_bull = df.get('bos_bull', pd.Series([False]))
    bos_bear = df.get('bos_bear', pd.Series([False]))
    choch_bull = df.get('choch_bull', pd.Series([False]))
    choch_bear = df.get('choch_bear', pd.Series([False]))
    
    elite_bull = (
        bull_ob &
        (df['valuation'] == 'Ucuz (Discount)') &
        near_fib_ote &
        (df.get('fib_direction', '') == 'bullish') &
        rsi_bullish &
        active_bull_fvg.shift(1) &
        bullish_lg.shift(1) &
        (bos_bull | choch_bull) &
        (df['volume'] > df['volume'].rolling(20).mean())
    )
    
    if elite_bull.any():
        df.loc[elite_bull, 'entry_signal'] = '🚀 ELITE LONG: OB + Discount + FVG + LG + FIB OTE + RSI6↑SMA50'
        df.loc[elite_bull, 'signal_quality'] = 10
        
        for idx in df[elite_bull].index:
            entry_price = df.loc[idx, 'close']
            sl = min(df.loc[idx, 'low'], df.get('fib_100', entry_price * 0.95)) * 0.995
            tp = entry_price + (2.5 * (entry_price - sl))
            df.at[idx, 'stop_loss'] = sl
            df.at[idx, 'take_profit'] = tp
            df.at[idx, 'rr_ratio'] = 2.5
    
    elite_bear = (
        bear_ob &
        (df['valuation'] == 'Pahalı (Premium)') &
        near_fib_ote &
        (df.get('fib_direction', '') == 'bearish') &
        rsi_bearish &
        active_bear_fvg.shift(1) &
        bearish_lg.shift(1) &
        (bos_bear | choch_bear) &
        (df['volume'] > df['volume'].rolling(20).mean())
    )
    
    if elite_bear.any():
        df.loc[elite_bear, 'entry_signal'] = '🚀 ELITE SHORT: OB + Premium + FVG + LG + FIB OTE + RSI6↓SMA50'
        df.loc[elite_bear, 'signal_quality'] = 10
        
        for idx in df[elite_bear].index:
            entry_price = df.loc[idx, 'close']
            sl = max(df.loc[idx, 'high'], df.get('fib_100', entry_price * 1.05)) * 1.005
            tp = entry_price - (2.5 * (sl - entry_price))
            df.at[idx, 'stop_loss'] = sl
            df.at[idx, 'take_profit'] = tp
            df.at[idx, 'rr_ratio'] = 2.5
    
    return df

# ------------------- CORE.PY İÇİN ANA FONKSİYON -------------------
def generate_ict_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> dict | None:
    """
    core.py'den çağrılan ana fonksiyon - WebSocket'e canlı sinyal gönderir
    """
    try:
        if len(df) < 100:
            return None

        # Sütun kontrolü ve düzeltme
        if not all(col in df.columns for col in ['open', 'high', 'low', 'close', 'volume']):
            if len(df.columns) >= 5:
                df.columns = ['timestamp', 'open', 'high', 'low', 'close'] if len(df.columns) == 5 else ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                if 'volume' not in df.columns:
                    df['volume'] = 1000

        # Son 200 mum
        df = df.tail(200).copy()

        # Timestamp index
        if 'timestamp' in df.columns:
            df.index = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.astype(float, errors='ignore')

        # Temel
        df['is_bullish'] = df['close'] > df['open']
        df['is_bearish'] = df['close'] < df['open']

        # Pivot
        df['pivot_high'], df['pivot_low'] = detect_pivots(df['high'], df['low'], 5)

        # Volume Profile
        _, poc_price, (va_low, va_high) = calculate_volume_profile(df, bins=50)

        # ICT Patterns
        patterns = detect_ict_patterns(df)

        # Fibonacci
        df = detect_fibonacci_levels(df, df['pivot_high'], df['pivot_low'])

        # Liquidity & Market Structure
        df = detect_liquidity_grab(df, df['pivot_high'], df['pivot_low'])
        df = detect_market_structure(df, df['pivot_high'], df['pivot_low'])

        # Skor
        signal_score = calculate_signal_score(patterns)
        normalized_score = int(np.clip((signal_score + 100), 0, 200) / 2)

        # Elite
        df = generate_elite_signals(df, patterns, va_low, va_high)

        last = df.iloc[-1]
        has_elite = last['entry_signal'] != ''

        current_price = float(last['close'])

        triggers = []
        for p in ['crt_buy', 'crt_sell', 'fvg_up', 'fvg_down', 'bullish_engulfing', 'bearish_engulfing', 'bullish_pin', 'bearish_pin', 'bull_ob', 'bear_ob']:
            if patterns.get(p, pd.Series([False])).iloc[-1]:
                triggers.append(p.replace('_', ' ').title())

        killzone = "London" if patterns.get('london_kz', pd.Series([False])).iloc[-1] else "New York" if patterns.get('ny_kz', pd.Series([False])).iloc[-1] else "Normal"

        signal_text = last['entry_signal'] if has_elite else \
                      "🚀 GÜÇLÜ ALIM" if signal_score > 30 else \
                      "🔥 GÜÇLÜ SATIM" if signal_score < -30 else "⏸️ NÖTR"

        return {
            "pair": symbol.replace("USDT", "/USDT"),
            "timeframe": timeframe.upper(),
            "current_price": round(current_price, 6 if current_price < 1 else 4),
            "signal": signal_text,
            "score": normalized_score,
            "strength": "ELITE" if has_elite else "YÜKSEK" if normalized_score >= 70 else "ORTA",
            "killzone": killzone,
            "triggers": " | ".join(triggers) if triggers else "RSI6 + Momentum",
            "last_update": datetime.utcnow().strftime("%H:%M:%S")
        }

    except Exception as e:
        logger.error(f"generate_ict_signal hatası {symbol}/{timeframe}: {e}")
        return generate_simple_signal(df, symbol, timeframe)

def generate_simple_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> dict | None:
    try:
        if len(df) < 10:
            return None
        close = df['close']
        last = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        change = (last - prev) / prev * 100 if prev != 0 else 0
        score = min(95, int(abs(change) * 20) + 30)
        signal = "🚀 ALIM" if change > 0.3 else "🔥 SATIM" if change < -0.3 else "⏸️ NÖTR"
        return {
            "pair": symbol.replace("USDT", "/USDT"),
            "timeframe": timeframe.upper(),
            "current_price": round(last, 6 if last < 1 else 4),
            "signal": signal,
            "score": score,
            "strength": "YÜKSEK" if score >= 70 else "ORTA",
            "killzone": "Normal",
            "triggers": f"Fiyat: {change:+.2f}%",
            "last_update": datetime.utcnow().strftime("%H:%M:%S")
        }
    except:
        return None
