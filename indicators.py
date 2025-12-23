# indicators.py — DÜZELTİLMİŞ VE CANLI SİNYAL ÜRETECEK VERSİYON

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any

# ----------------------------- PARAMETRELER -----------------------------
RSI6_LENGTH = 6
SMA50_LENGTH = 50
RSI_OB_LEVEL = 70
CRT_RANGE_MULTIPLIER = 1.5
CRT_LOOKBACK = 5
SIGNAL_STRENGTH = 60  # Biraz düşürdük ki sinyal gelsin

LONDON_KILLZONE_START_UTC = 7
LONDON_KILLZONE_END_UTC = 10
NY_KILLZONE_START_UTC = 13
NY_KILLZONE_END_UTC = 16

def rsi(series: pd.Series, period: int) -> pd.Series:
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
    if len(df) < 100:
        return None

    # Timestamp'i datetime index yap
    if 'timestamp' in df.columns:
        df = df.set_index('timestamp')
        df.index = pd.to_datetime(df.index, unit='ms', utc=True)
    else:
        df.index = pd.to_datetime(df.index, utc=True)

    df = df[['open', 'high', 'low', 'close', 'volume']].copy()

    # Heikin-Ashi hesapla (pandas Series ile)
    ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_open = (df['open'].shift(1) + df['close'].shift(1)) / 2
    ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    ha_open = ha_open.fillna(method='bfill')

    ha_high = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([df['low'], ha_open, ha_close], axis=1).min(axis=1)

    # Killzone (UTC saat)
    hours = df.index.hour
    london_kz = (hours >= LONDON_KILLZONE_START_UTC) & (hours < LONDON_KILLZONE_END_UTC)
    ny_kz = (hours >= NY_KILLZONE_START_UTC) & (hours < NY_KILLZONE_END_UTC)
    in_killzone = london_kz | ny_kz

    # RSI6 ve SMA50
    rsi6 = rsi(ha_close, RSI6_LENGTH)
    sma50 = rsi6.rolling(SMA50_LENGTH).mean()

    rsi6_crossover = (rsi6 > sma50) & (rsi6.shift(1) <= sma50.shift(1))
    rsi6_crossunder = (rsi6 < sma50) & (rsi6.shift(1) >= sma50.shift(1))

    # CRT
    ha_range = ha_high - ha_low
    avg_range = ha_range.rolling(CRT_LOOKBACK).mean()
    narrow_prev = ha_range.shift(1) < (avg_range.shift(1) * CRT_RANGE_MULTIPLIER)
    wide_now = ha_range > (avg_range * CRT_RANGE_MULTIPLIER)

    crt_buy = narrow_prev & wide_now & (ha_close > ha_open) & (ha_close > df['high'].shift(1))
    crt_sell = narrow_prev & wide_now & (ha_close < ha_open) & (ha_close < df['low'].shift(1))

    # Diğer patternler
    mom_buy = (df['close'] > df['close'].shift(1)) & (df['close'] > df['close'].shift(2))
    mom_sell = (df['close'] < df['close'].shift(1)) & (df['close'] < df['close'].shift(2))

    fvg_up = (df['low'].shift(1) > df['high'].shift(-1)) & (df['close'] > df['open'])
    fvg_down = (df['high'].shift(1) < df['low'].shift(-1)) & (df['close'] < df['open'])

    bullish_engulfing = (df['close'].shift(1) < df['open'].shift(1)) & (df['open'] < df['close'].shift(1)) & (df['close'] > df['open'].shift(1))
    bearish_engulfing = (df['close'].shift(1) > df['open'].shift(1)) & (df['open'] > df['close'].shift(1)) & (df['close'] < df['open'].shift(1))

    body = (df['close'] - df['open']).abs()
    lower_wick = df[['open', 'close']].min(axis=1) - df['low']
    upper_wick = df['high'] - df[['open', 'close']].max(axis=1)
    total_range = df['high'] - df['low'] + 1e-8

    bullish_pin = (lower_wick > 2 * body) & (upper_wick < body)
    bearish_pin = (upper_wick > 2 * body) & (lower_wick < body)

    displacement_up = (df['close'] - df['open']) > (total_range * 0.8)
    displacement_down = (df['open'] - df['close']) > (total_range * 0.8)

    # Son mum için skor
    score = 0
    last = -1

    if rsi6_crossover.iloc[last]: score += 35
    if rsi6_crossunder.iloc[last]: score -= 35
    if rsi6.iloc[last] > RSI_OB_LEVEL: score += 15

    if crt_buy.iloc[last]: score += 40
    if crt_sell.iloc[last]: score -= 40

    if fvg_up.iloc[last]: score += 30
    if fvg_down.iloc[last]: score -= 30

    if bullish_engulfing.iloc[last]: score += 25
    if bearish_engulfing.iloc[last]: score -= 25

    if bullish_pin.iloc[last]: score += 20
    if bearish_pin.iloc[last]: score -= 20

    if displacement_up.iloc[last]: score += 25
    if displacement_down.iloc[last]: score -= 25

    if mom_buy.iloc[last]: score += 25
    if mom_sell.iloc[last]: score -= 25

    if in_killzone.iloc[last]: score += 25
    if london_kz.iloc[last]: score += 15

    # Daha dengeli skor
    normalized_score = min(100, max(0, score + 100))  # 0-200 arası skoru 0-100 yap

    if normalized_score < SIGNAL_STRENGTH:
        return None

    current_price = float(df['close'].iloc[-1])
    signal_text = "🚀 ICT GÜÇLÜ ALIM SİNYALİ" if score > 0 else "🔥 ICT GÜÇLÜ SATIM SİNYALİ"

    triggers = []
    if crt_buy.iloc[last]: triggers.append("CRT Alım")
    if crt_sell.iloc[last]: triggers.append("CRT Satım")
    if fvg_up.iloc[last]: triggers.append("FVG↑")
    if fvg_down.iloc[last]: triggers.append("FVG↓")
    if bullish_engulfing.iloc[last]: triggers.append("Engulfing↑")
    if bearish_engulfing.iloc[last]: triggers.append("Engulfing↓")
    if bullish_pin.iloc[last]: triggers.append("Pin Bar↑")
    if bearish_pin.iloc[last]: triggers.append("Pin Bar↓")
    if displacement_up.iloc[last]: triggers.append("Displacement↑")
    if displacement_down.iloc[last]: triggers.append("Displacement↓")
    if mom_buy.iloc[last]: triggers.append("Momentum↑")
    if mom_sell.iloc[last]: triggers.append("Momentum↓")

    killzone_name = "London" if london_kz.iloc[last] else "New York" if ny_kz.iloc[last] else "Normal"

    pair = symbol.replace("USDT", "/USDT")

    return {
        "pair": pair,
        "timeframe": timeframe.upper(),
        "current_price": round(current_price, 6 if current_price < 1 else 4),
        "signal": signal_text,
        "score": round(normalized_score, 1),
        "last_update": datetime.utcnow().strftime("%H:%M:%S UTC"),
        "killzone": killzone_name,
        "triggers": " | ".join(triggers) if triggers else "RSI6 + SMA50",
        "strength": "ÇOK YÜKSEK" if normalized_score >= 85 else "YÜKSEK"
    }
