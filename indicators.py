# indicators.py - GROK TRADE ELITE (PROD - CORE UYUMLU - HATASIZ)
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List
import logging

logger = logging.getLogger("grok_indicators")
logger.setLevel(logging.INFO)

class GrokIndicators:
    """
    Grok Trade Elite için optimize edilmiş ICT/SMC göstergeler sınıfı
    """

    def __init__(self):
        self._fib_levels = [0.0, 0.236, 0.382, 0.5, 0.618, 0.705, 0.786, 1.0]
        self.RSI6_PERIOD = 6
        self.SMA50_PERIOD = 50
        self.SIGNAL_THRESHOLD = 55

    @staticmethod
    def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50).clip(0, 100)

    @staticmethod
    def calculate_sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(window=period, min_periods=1).mean()

    @staticmethod
    def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
        ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        ha_open = pd.Series(index=df.index, dtype=float)
        ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
        ha_open.iloc[1:] = (ha_open.shift(1).iloc[1:] + ha_close.shift(1).iloc[1:]) / 2
        ha_high = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
        ha_low = pd.concat([df['low'], ha_open, ha_close], axis=1).min(axis=1)
        return pd.DataFrame({'ha_open': ha_open, 'ha_high': ha_high, 'ha_low': ha_low, 'ha_close': ha_close})

    @staticmethod
    def detect_pivots(high: pd.Series, low: pd.Series, length: int = 5) -> Tuple[pd.Series, pd.Series]:
        ph = pd.Series(np.nan, index=high.index)
        pl = pd.Series(np.nan, index=low.index)
        for i in range(length, len(high) - length):
            if high.iloc[i] == high.iloc[i-length:i+length+1].max():
                ph.iloc[i] = high.iloc[i]
            if low.iloc[i] == low.iloc[i-length:i+length+1].min():
                pl.iloc[i] = low.iloc[i]
        return ph, pl

    def calculate_volume_profile(self, df: pd.DataFrame, bins: int = 50, lookback: Optional[int] = None) -> Tuple[pd.DataFrame, float, Tuple[float, float]]:
        data = df.iloc[-lookback:] if lookback else df
        if len(data) == 0:
            return pd.DataFrame(), data['close'].mean(), (0, 0)

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
            return vp_df, poc_price, (price_min, price_max)

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

    def detect_ict_patterns(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        patterns = {}
        ha = self.calculate_heikin_ashi(df)
        ha_close = ha['ha_close']
        ha_range = ha['ha_high'] - ha['ha_low']

        rsi6 = self.calculate_rsi(ha_close, self.RSI6_PERIOD)
        sma50 = self.calculate_sma(rsi6, self.SMA50_PERIOD)

        patterns['rsi6_crossover'] = (rsi6 > sma50) & (rsi6.shift(1) <= sma50.shift(1))
        patterns['rsi6_crossunder'] = (rsi6 < sma50) & (rsi6.shift(1) >= sma50.shift(1))

        avg_range = ha_range.rolling(5).mean()
        narrow_prev = ha_range.shift(1) < (avg_range.shift(1) * 1.5)
        wide_now = ha_range > (avg_range * 1.5)

        patterns['crt_buy'] = narrow_prev & wide_now & (ha_close > ha['ha_open']) & (ha_close > df['high'].shift(1))
        patterns['crt_sell'] = narrow_prev & wide_now & (ha_close < ha['ha_open']) & (ha_close < df['low'].shift(1))

        patterns['fvg_up'] = df['low'] > df['high'].shift(2)
        patterns['fvg_down'] = df['high'] < df['low'].shift(2)

        patterns['bullish_engulfing'] = (df['close'].shift(1) < df['open'].shift(1)) & (df['open'] < df['close'].shift(1)) & (df['close'] > df['open'].shift(1))
        patterns['bearish_engulfing'] = (df['close'].shift(1) > df['open'].shift(1)) & (df['open'] > df['close'].shift(1)) & (df['close'] < df['open'].shift(1))

        body = (df['close'] - df['open']).abs()
        lower_wick = pd.concat([df['open'], df['close']], axis=1).min(axis=1) - df['low']
        upper_wick = df['high'] - pd.concat([df['open'], df['close']], axis=1).max(axis=1)
        total_range = df['high'] - df['low'] + 1e-8

        patterns['bullish_pin'] = (lower_wick > 2 * body) & (upper_wick < body)
        patterns['bearish_pin'] = (upper_wick > 2 * body) & (lower_wick < body)

        patterns['bull_ob'] = (df['close'].shift(1) < df['open'].shift(1)) & (df['close'] > df['high'].shift(1)) & (df['close'] > df['open'])
        patterns['bear_ob'] = (df['close'].shift(1) > df['open'].shift(1)) & (df['close'] < df['low'].shift(1)) & (df['close'] < df['open'])

        hours = df.index.hour if isinstance(df.index, pd.DatetimeIndex) else pd.Series([datetime.utcnow().hour] * len(df))
        patterns['london_kz'] = (hours >= 7) & (hours < 10)
        patterns['ny_kz'] = (hours >= 13) & (hours < 16)
        patterns['in_killzone'] = patterns['london_kz'] | patterns['ny_kz']

        patterns['rsi6'] = rsi6
        patterns['sma50_rsi'] = sma50

        return patterns

        def detect_fibonacci_levels(self, df: pd.DataFrame, ph: pd.Series, pl: pd.Series) -> pd.DataFrame:
        df = df.copy()
    
    # Tüm fib sütunlarını NaN ile başlat
    for level in self._fib_levels:
        col_name = f'fib_{str(level).replace(".", "")}'
        df[col_name] = np.nan
    
    df['fib_direction'] = ''
    df['fib_ote_zone'] = False

    ph_series = ph.dropna()
    pl_series = pl.dropna()

    # En az 1 pivot high ve 1 pivot low olmalı (2 değil, 1 yeterli)
    if len(ph_series) < 1 or len(pl_series) < 1:
        return df  # Fibonacci yok ama en azından sütunlar var (NaN)

    # En son pivot high ve pivot low'u al
    last_ph_idx = ph_series.index[-1]
    last_pl_idx = pl_series.index[-1]

    try:
        if last_ph_idx > last_pl_idx:
            # Bearish retracement
            high_price = df.loc[last_ph_idx, 'high']
            low_price = df.loc[last_pl_idx, 'low']
            fib_range = high_price - low_price
            if fib_range <= 0:
                return df
            for level in self._fib_levels:
                col_name = f'fib_{str(level).replace(".", "")}'
                df[col_name] = high_price - (fib_range * level)
            df['fib_direction'] = 'bearish'
            # OTE zone kontrolü (NaN değilse)
            if 'fib_618' in df.columns and 'fib_705' in df.columns:
                df['fib_ote_zone'] = (df['close'] >= df['fib_618']) & (df['close'] <= df['fib_705'])
        else:
            # Bullish retracement
            low_price = df.loc[last_pl_idx, 'low']
            high_price = df.loc[last_ph_idx, 'high']
            fib_range = high_price - low_price
            if fib_range <= 0:
                return df
            for level in self._fib_levels:
                col_name = f'fib_{str(level).replace(".", "")}'
                df[col_name] = low_price + (fib_range * level)
            df['fib_direction'] = 'bullish'
            if 'fib_618' in df.columns and 'fib_705' in df.columns:
                df['fib_ote_zone'] = (df['close'] >= df['fib_618']) & (df['close'] <= df['fib_705'])
    except Exception as e:
        logger.debug(f"Fibonacci hesaplama hatası: {e}")
        # Hata olsa bile sütunlar NaN kalsın, patlamasın

    return df
    def calculate_signal_score(self, patterns: Dict[str, pd.Series]) -> int:
        score = 0
        idx = -1
        try:
            if patterns.get('rsi6_crossover', pd.Series([False])).iloc[idx]:
                score += 35
            if patterns.get('rsi6_crossunder', pd.Series([False])).iloc[idx]:
                score -= 35
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
            if patterns.get('bull_ob', pd.Series([False])).iloc[idx]:
                score += 25
            if patterns.get('bear_ob', pd.Series([False])).iloc[idx]:
                score -= 25
            if patterns.get('in_killzone', pd.Series([False])).iloc[idx]:
                score += 25
            if patterns.get('london_kz', pd.Series([False])).iloc[idx]:
                score += 15
        except:
            pass
        return score

# GLOBAL INSTANCE
grok = GrokIndicators()

def generate_ict_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """
    core.py'den çağrılan ana fonksiyon - WebSocket'e sinyal gönderir
    """
    try:
        if len(df) < 100:
            logger.warning(f"{symbol}: Yetersiz veri ({len(df)})")
            return generate_simple_signal(df, symbol, timeframe)

        # Sütun kontrolü
        required = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required):
            logger.error(f"{symbol}: Eksik sütun")
            return generate_simple_signal(df, symbol, timeframe)

        df = df.copy()
        df = df.astype(float, errors='ignore')

        # Pivot
        df['pivot_high'], df['pivot_low'] = grok.detect_pivots(df['high'], df['low'])

        # Volume Profile
        _, poc_price, (va_low, va_high) = grok.calculate_volume_profile(df)

        # ICT Patterns
        patterns = grok.detect_ict_patterns(df)

        # Fibonacci
        df = grok.detect_fibonacci_levels(df, df['pivot_high'], df['pivot_low'])

        # Skor
        signal_score = grok.calculate_signal_score(patterns)
        normalized_score = int(np.clip((signal_score + 100), 0, 200) / 2)

        last = df.iloc[-1]
        current_price = float(last['close'])

        triggers = [p.replace('_', ' ').title() for p in patterns if patterns.get(p, pd.Series([False])).iloc[-1] and p not in ['rsi6', 'sma50_rsi']]

        killzone = "London" if patterns.get('london_kz', pd.Series([False])).iloc[-1] else \
                   "New York" if patterns.get('ny_kz', pd.Series([False])).iloc[-1] else "Normal"

        has_elite = last.get('entry_signal', '') != '' or abs(signal_score) > 80

        signal_text = "🚀 ELITE ALIM" if has_elite and signal_score > 0 else \
                      "🔥 ELITE SATIM" if has_elite and signal_score < 0 else \
                      "🚀 GÜÇLÜ ALIM" if signal_score > 30 else \
                      "🔥 GÜÇLÜ SATIM" if signal_score < -30 else "⏸️ NÖTR"

        strength = "ELITE" if has_elite else "YÜKSEK" if normalized_score >= 70 else "ORTA"

        logger.info(f"🎯 {symbol}/{timeframe} → {signal_text} | Skor: {normalized_score}")

        return {
            "pair": symbol.replace("USDT", "/USDT"),
            "timeframe": timeframe.upper(),
            "current_price": round(current_price, 6 if current_price < 1 else 4),
            "signal": signal_text,
            "score": normalized_score,
            "strength": strength,
            "killzone": killzone,
            "triggers": " | ".join(triggers) if triggers else "RSI6 Momentum",
            "last_update": datetime.utcnow().strftime("%H:%M:%S")
        }

    except Exception as e:
        logger.error(f"Sinyal hatası {symbol}: {e}")
        return generate_simple_signal(df, symbol, timeframe)

def generate_simple_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    try:
        if len(df) < 10:
            return None
        close = df['close']
        last = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        change = (last - prev) / prev * 100 if prev != 0 else 0
        score = min(95, int(abs(change) * 15) + 40)
        signal = "🚀 ALIM" if change > 0.2 else "🔥 SATIM" if change < -0.2 else "⏸️ NÖTR"
        return {
            "pair": symbol.replace("USDT", "/USDT"),
            "timeframe": timeframe.upper(),
            "current_price": round(last, 6 if last < 1 else 4),
            "signal": signal,
            "score": score,
            "strength": "YÜKSEK" if score >= 70 else "ORTA",
            "killzone": "Normal",
            "triggers": f"Momentum: {change:+.2f}%",
            "last_update": datetime.utcnow().strftime("%H:%M:%S")
        }
    except:
        return None
