# indicators.py
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
SIGNAL_STRENGTH = 85  # Daha seçici, yüksek kaliteli sinyal için

# Killzone Saatleri (UTC → EST dönüşümü: UTC-5)
LONDON_KILLZONE_START_UTC = 7   # 02:00 EST = 07:00 UTC
LONDON_KILLZONE_END_UTC = 10    # 05:00 EST = 10:00 UTC
NY_KILLZONE_START_UTC = 13      # 08:00 EST = 13:00 UTC
NY_KILLZONE_END_UTC = 16        # 11:00 EST = 16:00 UTC


def rsi(series: np.ndarray, period: int) -> np.ndarray:
    """Vectorized RSI — pandas.Series değil, raw np.array alır."""
    delta = np.diff(series, prepend=series[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)

    # Wilder smoothing (EMA equivalent: α = 1/period)
    gain = pd.Series(gain).ewm(alpha=1/period, adjust=False).mean().values
    loss = pd.Series(loss).ewm(alpha=1/period, adjust=False).mean().values

    rs = np.divide(gain, loss, out=np.full_like(gain, 100.0), where=loss != 0)
    rsi_vals = 100 - (100 / (1 + rs))
    rsi_vals[np.isinf(rsi_vals)] = 100
    rsi_vals[np.isnan(rsi_vals)] = 50
    return rsi_vals


def generate_ict_signal(df_raw: np.ndarray, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """
    Yüksek performanslı sinyal üretimi.
    df_raw: shape=(n, 6), columns = [timestamp, open, high, low, close, volume] (np.ndarray)
    """
    if len(df_raw) < 100:
        return None

    # NumPy doğrudan erişim — hız kritik!
    timestamps = df_raw[:, 0].astype('datetime64[ms]')
    o, h, l, c = df_raw[:, 1], df_raw[:, 2], df_raw[:, 3], df_raw[:, 4]

    # ----------------------------- HEIKIN-ASHI -----------------------------
    ha_close = (o + h + l + c) / 4.0
    ha_open = np.empty_like(ha_close)
    ha_open[0] = (o[0] + c[0]) / 2.0
    for i in range(1, len(ha_close)):
        ha_open[i] = (ha_open[i-1] + ha_close[i-1]) / 2.0

    ha_high = np.maximum.reduce([h, ha_open, ha_close])
    ha_low = np.minimum.reduce([l, ha_open, ha_close])

    # ----------------------------- ZAMAN DİLİMLERİ (UTC) -----------------------------
    #timestamps_utc = pd.to_datetime(timestamps, utc=True)
    hours_utc = (pd.to_datetime(timestamps, unit='ms', utc=True).hour).values

    london_kz = (hours_utc >= LONDON_KILLZONE_START_UTC) & (hours_utc < LONDON_KILLZONE_END_UTC)
    ny_kz = (hours_utc >= NY_KILLZONE_START_UTC) & (hours_utc < NY_KILLZONE_END_UTC)
    in_killzone = london_kz | ny_kz

    # ----------------------------- RSI6 & SMA50 -----------------------------
    rsi6 = rsi(ha_close, RSI6_LENGTH)
    sma50 = pd.Series(rsi6).rolling(SMA50_LENGTH).mean().values

    rsi6_crossover = (rsi6 > sma50) & (np.roll(rsi6, 1) <= np.roll(sma50, 1))
    rsi6_crossunder = (rsi6 < sma50) & (np.roll(rsi6, 1) >= np.roll(sma50, 1))
    rsi6_above_ob = rsi6 > RSI_OB_LEVEL

    # ----------------------------- CRT (Candle Range Theory) -----------------------------
    ha_range = ha_high - ha_low
    avg_range = pd.Series(ha_range).rolling(CRT_LOOKBACK).mean().values

    narrow_prev = np.roll(ha_range, 1) < (np.roll(avg_range, 1) / CRT_RANGE_MULTIPLIER)
    wide_now = ha_range > (avg_range * CRT_RANGE_MULTIPLIER)

    crt_buy = narrow_prev & wide_now & (ha_close > ha_open) & (ha_close > np.roll(ha_high, 1))
    crt_sell = narrow_prev & wide_now & (ha_close < ha_open) & (ha_close < np.roll(ha_low, 1))

    # ----------------------------- MOMENTUM (Senin İstediğin Kural!) -----------------------------
    # "Kendinden bir ve iki önceki mum kapanışından yukarı kapatırsa → buy"
    mom_buy = (c > np.roll(c, 1)) & (c > np.roll(c, 2))
    mom_sell = (c < np.roll(c, 1)) & (c < np.roll(c, 2))
    # HA onayı ile güçlendirilmiş versiyon (isteğe bağlı — şimdilik kullanmayalım, saf fiyat momentumu)
    # ha_mom_buy = mom_buy & (ha_close > ha_open)

    # ----------------------------- ICT PATERNLERİ (Vectorized) -----------------------------
    # FVG (Fair Value Gap)
    fvg_up = (np.roll(l, 1) > np.roll(h, -1)) & (c > o)
    fvg_down = (np.roll(h, 1) < np.roll(l, -1)) & (c < o)

    # Engulfing
    prev_close, prev_open = np.roll(c, 1), np.roll(o, 1)
    bullish_engulfing = (prev_close < prev_open) & (o < prev_close) & (c > prev_open)
    bearish_engulfing = (prev_close > prev_open) & (o > prev_close) & (c < prev_open)

    # Pin Bar (Wick/Body oranı > 2:1)
    body = np.abs(c - o)
    lower_wick = l - np.minimum(o, c)
    upper_wick = np.maximum(o, c) - h  # negatif çıktı — düzelt:
    upper_wick = np.maximum(o, c) - h
    upper_wick = h - np.maximum(o, c)  # ✅ düzeltildi

    total_range = h - l
    valid_bar = total_range > 1e-8  # avoid div by zero
    bullish_pin = (lower_wick > 2 * body) & (upper_wick < body) & valid_bar
    bearish_pin = (upper_wick > 2 * body) & (lower_wick < body) & valid_bar

    # Displacement (Strong candle)
    displacement_up = (c - o) > (h - l) * 0.8
    displacement_down = (o - c) > (h - l) * 0.8

    # ----------------------------- SKOR HESAPLAMASI (SON MUM) -----------------------------
    i = -1  # son indeks
    score = 0.0

    # RSI6 Momentum
    score += 35 if rsi6_crossover[i] else 0
    score -= 35 if rsi6_crossunder[i] else 0
    score += 15 if rsi6_above_ob[i] else 0

    # CRT
    score += 40 if crt_buy[i] else 0
    score -= 40 if crt_sell[i] else 0

    # FVG
    score += 30 if fvg_up[i] else 0
    score -= 30 if fvg_down[i] else 0

    # Mum Paternleri
    score += 25 if bullish_engulfing[i] else 0
    score -= 25 if bearish_engulfing[i] else 0
    score += 20 if bullish_pin[i] else 0
    score -= 20 if bearish_pin[i] else 0
    score += 25 if displacement_up[i] else 0
    score -= 25 if displacement_down[i] else 0

    # Momentum (YENİ — senin kuralın)
    score += 25 if mom_buy[i] else 0
    score -= 25 if mom_sell[i] else 0

    # Killzone Güçlendirme
    score += 25 if in_killzone[i] else 0
    score += 15 if london_kz[i] else 0  # London premium

    normalized_score = min(100.0, max(0.0, (score + 150) / 3.0))

    if normalized_score < SIGNAL_STRENGTH:
        return None

    current_price = c[i]
    last_update = datetime.utcnow().strftime("%H:%M:%S UTC")

    if score > 80:
        signal_text = "🚀 ICT GÜÇLÜ ALIM SİNYALİ"
        momentum = "up"
    elif score < -80:
        signal_text = "🔥 ICT GÜÇLÜ SATIM SİNYALİ"
        momentum = "down"
    else:
        return None

    # Tetiklenen pattern’ler
    triggers = []
    if fvg_up[i]: triggers.append("FVG↑")
    if fvg_down[i]: triggers.append("FVG↓")
    if crt_buy[i]: triggers.append("CRT Alım")
    if crt_sell[i]: triggers.append("CRT Satım")
    if bullish_engulfing[i]: triggers.append("Engulfing↑")
    if bearish_engulfing[i]: triggers.append("Engulfing↓")
    if bullish_pin[i]: triggers.append("Pin Bar↑")
    if displacement_up[i]: triggers.append("Displacement↑")
    if mom_buy[i]: triggers.append("Momentum↑")  # ✅ YENİ: Senin kuralın
    if mom_sell[i]: triggers.append("Momentum↓")

    killzone = (
        "London" if london_kz[i]
        else "New York" if ny_kz[i]
        else "Normal Saat"
    )

    # Format pair
    pair = symbol
    if symbol.endswith("USDT"):
        pair = symbol[:-4] + "/USDT"

    return {
        "pair": pair,
        "timeframe": timeframe,
        "current_price": round(current_price, 6 if current_price < 1 else 4),
        "signal": signal_text,
        "momentum": momentum,
        "last_update": last_update,
        "score": round(normalized_score, 1),
        "killzone": killzone,
        "triggers": " | ".join(triggers) if triggers else "RSI6 + Momentum",
        "strength": "ÇOK YÜKSEK" if abs(score) > 100 else "YÜKSEK"
    }
