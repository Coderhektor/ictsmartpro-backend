# indicators.py — GÜNCEL VERSİYON (pd.DataFrame kabul etsin + hata önleme)

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
SIGNAL_STRENGTH = 50

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
    """
    df: pandas DataFrame with columns: ['open', 'high', 'low', 'close', 'volume'] and datetime index (or 'timestamp')
    """
    if len(df) < 100:
        return None

    # Sütun isimlerini garantiye al
    df = df[['open', 'high', 'low', 'close', 'volume']].copy()
    o, h, l, c = df['open'].values, df['high'].values, df['low'].values, df['close'].values

    # Heikin-Ashi
    ha_close = (o + h + l + c) / 4
    ha_open = np.empty_like(ha_close)
    ha_open[0] = (o[0] + c[0]) / 2
    for i in range(1, len(ha_open)):
        ha_open[i] = (ha_open[i-1] + ha_close[i-1]) / 2

    ha_high = np.maximum.reduce([h, ha_open, ha_close])
    ha_low = np.minimum.reduce([l, ha_open, ha_close])

    # Zaman (UTC saat)
    if df.index.name == 'timestamp' or 'timestamp' in df.columns:
        hours = pd.to_datetime(df.index if df.index.name else df['timestamp'], unit='ms', utc=True).hour
    else:
        hours = pd.to_datetime(df.index, utc=True).hour

    london_kz = (hours >= LONDON_KILLZONE_START_UTC) & (hours < LONDON_KILLZONE_END_UTC)
    ny_kz = (hours >= NY_KILLZONE_START_UTC) & (hours < NY_KILLZONE_END_UTC)
    in_killzone = london_kz | ny_kz

    # RSI6 & SMA50
    rsi6 = rsi(pd.Series(ha_close), RSI6_LENGTH)
    sma50 = rsi6.rolling(SMA50_LENGTH).mean()

    rsi6_crossover = (rsi6 > sma50) & (rsi6.shift(1) <= sma50.shift(1))
    rsi6_crossunder = (rsi6 < sma50) & (rsi6.shift(1) >= sma50.shift(1))

    # CRT
    ha_range = ha_high - ha_low
    avg_range = pd.Series(ha_range).rolling(CRT_LOOKBACK).mean()
    narrow_prev = ha_range.shift(1) < (avg_range.shift(1) / CRT_RANGE_MULTIPLIER)
    wide_now = ha_range > (avg_range * CRT_RANGE_MULTIPLIER)

    crt_buy = narrow_prev & wide_now & (ha_close > ha_open) & (ha_close > np.roll(ha_high, 1))
    crt_sell = narrow_prev & wide_now & (ha_close < ha_open) & (ha_close < np.roll(ha_low, 1))

    # Momentum (senin kuralın)
    mom_buy = (c > np.roll(c, 1)) & (c > np.roll(c, 2))
    mom_sell = (c < np.roll(c, 1)) & (c < np.roll(c, 2))

    # FVG, Engulfing, Pin Bar vs.
    fvg_up = (np.roll(l, 1) > np.roll(h, -1)) & (c > o)
    fvg_down = (np.roll(h, 1) < np.roll(l, -1)) & (c < o)

    bullish_engulfing = (np.roll(c, 1) < np.roll(o, 1)) & (o < np.roll(c, 1)) & (c > np.roll(o, 1))
    bearish_engulfing = (np.roll(c, 1) > np.roll(o, 1)) & (o > np.roll(c, 1)) & (c < np.roll(o, 1))

    body = np.abs(c - o)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)
    total_range = h - l + 1e-8

    bullish_pin = (lower_wick > 2 * body) & (upper_wick < body)
    bearish_pin = (upper_wick > 2 * body) & (lower_wick < body)

    displacement_up = (c - o) > total_range * 0.8
    displacement_down = (o - c) > total_range * 0.8

    # Skor (son mum)
    i = -1
    score = 0

    score += 35 if rsi6_crossover.iloc[i] else 0
    score -= 35 if rsi6_crossunder.iloc[i] else 0
    score += 15 if rsi6.iloc[i] > RSI_OB_LEVEL else 0

    score += 40 if crt_buy[i] else 0
    score -= 40 if crt_sell[i] else 0

    score += 30 if fvg_up[i] else 0
    score -= 30 if fvg_down[i] else 0

    score += 25 if bullish_engulfing[i] else 0
    score -= 25 if bearish_engulfing[i] else 0
    score += 20 if bullish_pin[i] else 0
    score -= 20 if bearish_pin[i] else 0
    score += 25 if displacement_up[i] else 0
    score -= 25 if displacement_down[i] else 0
    score += 25 if mom_buy[i] else 0
    score -= 25 if mom_sell[i] else 0

    score += 25 if in_killzone.iloc[i] else 0
    score += 15 if london_kz.iloc[i] else 0

    normalized_score = min(100, max(0, (score + 150) / 3))

    if normalized_score < SIGNAL_STRENGTH:
        return None

    current_price = float(c[i])
    signal_text = "🚀 ICT GÜÇLÜ ALIM SİNYALİ" if score > 80 else "🔥 ICT GÜÇLÜ SATIM SİNYALİ"
    momentum = "up" if score > 0 else "down"

    triggers = []
    if fvg_up[i]: triggers.append("FVG↑")
    if crt_buy[i]: triggers.append("CRT Alım")
    if bullish_engulfing[i]: triggers.append("Engulfing↑")
    if bullish_pin[i]: triggers.append("Pin Bar↑")
    if displacement_up[i]: triggers.append("Displacement↑")
    if mom_buy[i]: triggers.append("Momentum↑")
    if crt_sell[i]: triggers.append("CRT Satım")
    if fvg_down[i]: triggers.append("FVG↓")

    killzone_name = "London" if london_kz.iloc[i] else "New York" if ny_kz.iloc[i] else "Normal"

    pair = symbol.replace("USDT", "/USDT") if symbol.endswith("USDT") else symbol
return {
    "pair": pair,
    "timeframe": timeframe,
    "current_price": round(current_price, 6 if current_price < 1 else 4),
    "signal": signal_text,
    "momentum": momentum,
    "last_update": datetime.utcnow().strftime("%H:%M:%S UTC"),
    "score": round(normalized_score, 1),
    "killzone": killzone_name,
    "triggers": " | ".join(triggers) if triggers else "RSI6 + Momentum",
    "strength": "ÇOK YÜKSEK" if abs(score) > 100 else "YÜKSEK",
    "volume_spike": False  # <--- TAM BURAYA EKLE
}
