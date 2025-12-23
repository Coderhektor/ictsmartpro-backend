
# indicators.py
import pandas as pd
import numpy as np
from datetime import datetime

# ----------------------------- PARAMETRELER -----------------------------
RSI6_LENGTH = 6
SMA50_LENGTH = 50
RSI_OB_LEVEL = 70
CRT_RANGE_MULTIPLIER = 1.5
CRT_LOOKBACK = 5
SIGNAL_STRENGTH = 85  # Daha seçici olması için 90 → 85 yaptım

# Killzone Saatleri (EST)
LONDON_KILLZONE_START = 2
LONDON_KILLZONE_END = 5
NY_KILLZONE_START = 8
NY_KILLZONE_END = 11

# FVG Hassasiyeti
FVG_MIN_GAP = 0.0005  # %0.05 fiyat farkı (küçük coinler için dinamik yapabiliriz ama şimdilik sabit)


def rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = -delta.clip(upper=0).rolling(window=period).mean()
    rs = gain / loss
    rs = rs.replace([np.inf, -np.inf], 100)
    return 100 - (100 / (1 + rs))


def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_open = (df['open'].shift(1) + df['close'].shift(1)) / 2
    ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    ha_open = ha_open.fillna(method='bfill')

    ha_high = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([df['low'], ha_open, ha_close], axis=1).min(axis=1)

    df['ha_open'] = ha_open
    df['ha_high'] = ha_high
    df['ha_low'] = ha_low
    df['ha_close'] = ha_close
    return df


def add_killzone_flags(df: pd.DataFrame) -> pd.DataFrame:
    df['hour_est'] = (df.index.hour - 5) % 24
    df['london_killzone'] = df['hour_est'].between(LONDON_KILLZONE_START, LONDON_KILLZONE_END - 1)
    df['ny_killzone'] = df['hour_est'].between(NY_KILLZONE_START, NY_KILLZONE_END - 1)
    df['in_killzone'] = df['london_killzone'] | df['ny_killzone']
    return df


def detect_ict_patterns(df: pd.DataFrame) -> pd.DataFrame:
    # Fair Value Gap (FVG) - 3 mum formasyonu
    df['fvg_up'] = (df['low'].shift(1) > df['high'].shift(-1)) & (df['close'] > df['open'])
    df['fvg_down'] = (df['high'].shift(1) < df['low'].shift(-1)) & (df['close'] < df['open'])

    # Bullish/Bearish Engulfing
    df['bullish_engulfing'] = (df['close'].shift(1) < df['open'].shift(1)) & \
                              (df['open'] < df['close'].shift(1)) & \
                              (df['close'] > df['open'].shift(1))
    df['bearish_engulfing'] = (df['close'].shift(1) > df['open'].shift(1)) & \
                              (df['open'] > df['close'].shift(1)) & \
                              (df['close'] < df['open'].shift(1))

    # Pin Bar (Hammer / Shooting Star)
    body = abs(df['close'] - df['open'])
    lower_wick = df['low'] - body.min(axis=0)
    upper_wick = df['high'] - body.max(axis=0)
    total_range = df['high'] - df['low']

    df['bullish_pin'] = (lower_wick > 2 * body) & (upper_wick < body) & (total_range > 0)
    df['bearish_pin'] = (upper_wick > 2 * body) & (lower_wick < body) & (total_range > 0)

    # Inside Bar
    df['inside_bar'] = (df['high'] < df['high'].shift(1)) & (df['low'] > df['low'].shift(1))

    # Displacement (Güçlü momentum mumu)
    df['displacement_up'] = (df['close'] - df['open']) > (df['high'] - df['low']) * 0.8
    df['displacement_down'] = (df['open'] - df['close']) > (df['high'] - df['low']) * 0.8

    return df


def generate_ict_signal(df_raw: pd.DataFrame, symbol: str, timeframe: str) -> dict | None:
    """
    Gelişmiş ICT + Mum Paternleri ile sinyal üretir.
    df_raw: Binance OHLCV formatında (timestamp, o, h, l, c, v)
    """
    if len(df_raw) < 100:
        return None

    df = df_raw.copy()
    df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)

    # Heikin Ashi
    df = calculate_heikin_ashi(df)

    # Killzone
    df = add_killzone_flags(df)

    # ICT + Mum Paternleri
    df = detect_ict_patterns(df)

    # RSI6 + SMA50
    df['rsi6'] = rsi(df['ha_close'], RSI6_LENGTH)
    df['sma50'] = df['rsi6'].rolling(SMA50_LENGTH).mean()
    df['rsi6_crossover'] = (df['rsi6'] > df['sma50']) & (df['rsi6'].shift(1) <= df['sma50'].shift(1))
    df['rsi6_crossunder'] = (df['rsi6'] < df['sma50']) & (df['rsi6'].shift(1) >= df['sma50'].shift(1))

    # CRT
    df['ha_range'] = df['ha_high'] - df['ha_low']
    df['ha_avg_range'] = df['ha_range'].rolling(CRT_LOOKBACK).mean()
    df['crt_buy'] = (df['ha_range'].shift(1) < df['ha_avg_range'].shift(1) / CRT_RANGE_MULTIPLIER) & \
                    (df['ha_range'] > df['ha_avg_range'] * CRT_RANGE_MULTIPLIER) & \
                    (df['ha_close'] > df['ha_open']) & (df['ha_close'] > df['ha_high'].shift(1))
    df['crt_sell'] = (df['ha_range'].shift(1) < df['ha_avg_range'].shift(1) / CRT_RANGE_MULTIPLIER) & \
                     (df['ha_range'] > df['ha_avg_range'] * CRT_RANGE_MULTIPLIER) & \
                     (df['ha_close'] < df['ha_open']) & (df['ha_close'] < df['ha_low'].shift(1))

    # SKOR SİSTEMİ (Mevcut + Yeni Katmanlar)
    score = pd.Series(0.0, index=df.index)

    # RSI6 Momentum
    score += df['rsi6_crossover'] * 35
    score -= df['rsi6_crossunder'] * 35
    score += (df['rsi6'] > RSI_OB_LEVEL) * 15

    # CRT
    score += df['crt_buy'] * 40
    score -= df['crt_sell'] * 40

    # FVG
    score += df['fvg_up'] * 30
    score -= df['fvg_down'] * 30

    # Mum Paternleri
    score += df['bullish_engulfing'] * 25
    score -= df['bearish_engulfing'] * 25
    score += df['bullish_pin'] * 20
    score -= df['bearish_pin'] * 20
    score += df['displacement_up'] * 25
    score -= df['displacement_down'] * 25

    # Killzone Güçlendirme
    score += df['in_killzone'] * 25
    score += df['london_killzone'] * 15  # London daha güçlü

    df['score'] = score
    df['normalized_score'] = np.clip((score + 150) / 3.0, 0, 100)  # 0-100 arası

    latest = df.iloc[-1]
    current_price = latest['close']

    if latest['normalized_score'] < SIGNAL_STRENGTH:
        return None

    if latest['score'] > 80:
        signal_text = "🚀 ICT GÜÇLÜ ALIM SİNYALİ"
        momentum = "up"
    elif latest['score'] < -80:
        signal_text = "🔥 ICT GÜÇLÜ SATIM SİNYALİ"
        momentum = "down"
    else:
        return None

    # Hangi pattern'ler tetiklendi?
    triggers = []
    if latest['fvg_up']: triggers.append("FVG↑")
    if latest['fvg_down']: triggers.append("FVG↓")
    if latest['crt_buy']: triggers.append("CRT Alım")
    if latest['crt_sell']: triggers.append("CRT Satım")
    if latest['bullish_engulfing']: triggers.append("Engulfing↑")
    if latest['bearish_engulfing']: triggers.append("Engulfing↓")
    if latest['bullish_pin']: triggers.append("Pin Bar↑")
    if latest['displacement_up']: triggers.append("Displacement↑")

    killzone_text = "London" if latest['london_killzone'] else "New York" if latest['ny_killzone'] else "Normal Saat"

    return {
        "pair": f"{symbol[:-4]}/USDT" if symbol.endswith("USDT") else symbol,
        "timeframe": timeframe,
        "current_price": round(current_price, 6 if current_price < 1 else 4),
        "signal": signal_text,
        "momentum": momentum,
        "last_update": datetime.now().strftime("%H:%M:%S"),
        "score": round(latest['normalized_score'], 1),
        "killzone": killzone_text,
        "triggers": " | ".join(triggers) if triggers else "RSI6 + Momentum",
        "strength": "ÇOK YÜKSEK" if abs(latest['score']) > 100 else "YÜKSEK"
    }
