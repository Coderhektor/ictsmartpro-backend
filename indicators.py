# indicators.py - GROK TRADE ELITE (ULTIMATE PATTERN EDITION)
import pandas as pd
import numpy as np
from datetime import datetime, time
from typing import Optional, Dict, Any, Tuple, List, Union
import logging
from collections import deque

logger = logging.getLogger("grok_indicators")
logger.setLevel(logging.INFO)

class GrokIndicators:
    """
    Grok Trade Elite - Ultra Hassas Sinyal Üretimi
    Tüm paternler ve indikatörler aktif!
    """
    
    def __init__(self):
        self._fib_levels = [0.0, 0.236, 0.382, 0.5, 0.618, 0.705, 0.786, 0.886, 1.0]
        self.RSI6_PERIOD = 6
        self.RSI14_PERIOD = 14
        self.SMA50_PERIOD = 50
        self.SMA200_PERIOD = 200
        self.EMA9_PERIOD = 9
        self.EMA21_PERIOD = 21
        self.BB_PERIOD = 20
        self.SIGNAL_THRESHOLD = 40  # Düşürüldü - daha fazla sinyal!
        
    # ==================== TEMEL İNDİKATÖRLER ====================
    
    @staticmethod
    def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """RSI hesaplama"""
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
        """Simple Moving Average"""
        return series.rolling(window=period, min_periods=1).mean()
    
    @staticmethod
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average"""
        return series.ewm(span=period, adjust=False).mean()
    
    @staticmethod
    def calculate_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """MACD hesaplama"""
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    @staticmethod
    def calculate_bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Bollinger Bands"""
        sma = series.rolling(window=period, min_periods=1).mean()
        std = series.rolling(window=period, min_periods=1).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, sma, lower
    
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range"""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr
    
    @staticmethod
    def calculate_stochastic(df: pd.DataFrame, period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> Tuple[pd.Series, pd.Series]:
        """Stochastic Oscillator"""
        low_min = df['low'].rolling(window=period).min()
        high_max = df['high'].rolling(window=period).max()
        k = 100 * ((df['close'] - low_min) / (high_max - low_min + 1e-10))
        k_smooth = k.rolling(window=smooth_k).mean()
        d_smooth = k_smooth.rolling(window=smooth_d).mean()
        return k_smooth, d_smooth
    
    @staticmethod
    def calculate_obv(df: pd.DataFrame) -> pd.Series:
        """On Balance Volume"""
        obv = pd.Series(index=df.index, dtype=float)
        obv.iloc[0] = 0
        for i in range(1, len(df)):
            if df['close'].iloc[i] > df['close'].iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] + df['volume'].iloc[i]
            elif df['close'].iloc[i] < df['close'].iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] - df['volume'].iloc[i]
            else:
                obv.iloc[i] = obv.iloc[i-1]
        return obv
    
    @staticmethod
    def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
        """Heikin Ashi dönüşümü"""
        ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        ha_open = pd.Series(index=df.index, dtype=float)
        ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
        ha_open.iloc[1:] = (ha_open.shift(1).iloc[1:] + ha_close.shift(1).iloc[1:]) / 2
        ha_high = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
        ha_low = pd.concat([df['low'], ha_open, ha_close], axis=1).min(axis=1)
        return pd.DataFrame({'ha_open': ha_open, 'ha_high': ha_high, 'ha_low': ha_low, 'ha_close': ha_close})
    
    # ==================== PİVOT DETECTION ====================
    
    @staticmethod
    def detect_pivots(high: pd.Series, low: pd.Series, length: int = 5) -> Tuple[pd.Series, pd.Series]:
        """Pivot high/low tespiti"""
        ph = pd.Series(np.nan, index=high.index)
        pl = pd.Series(np.nan, index=low.index)
        
        for i in range(length, len(high) - length):
            if high.iloc[i] == high.iloc[i-length:i+length+1].max():
                ph.iloc[i] = high.iloc[i]
            if low.iloc[i] == low.iloc[i-length:i+length+1].min():
                pl.iloc[i] = low.iloc[i]
        
        return ph, pl
    
    # ==================== VOLUME PROFILE ====================
    
    def calculate_volume_profile(self, df: pd.DataFrame, bins: int = 50, lookback: Optional[int] = None) -> Tuple[pd.DataFrame, float, Tuple[float, float]]:
        """Volume Profile ve Point of Control (POC)"""
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
    
    # ==================== TÜM PATTERN TESPİTLERİ ====================
    
    def detect_all_patterns(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """TÜM mum ve indikatör paternlerini tespit et"""
        patterns = {}
        
        # Heikin Ashi
        ha = self.calculate_heikin_ashi(df)
        ha_close = ha['ha_close']
        ha_range = ha['ha_high'] - ha['ha_low']
        
        # 1. RSI Paternleri
        rsi6 = self.calculate_rsi(ha_close, self.RSI6_PERIOD)
        rsi14 = self.calculate_rsi(ha_close, self.RSI14_PERIOD)
        sma50_rsi = self.calculate_sma(rsi6, self.SMA50_PERIOD)
        
        patterns['rsi6_crossover'] = (rsi6 > sma50_rsi) & (rsi6.shift(1) <= sma50_rsi.shift(1))
        patterns['rsi6_crossunder'] = (rsi6 < sma50_rsi) & (rsi6.shift(1) >= sma50_rsi.shift(1))
        
        # RSI oversold/overbought
        patterns['rsi_oversold_6'] = rsi6 < 30
        patterns['rsi_overbought_6'] = rsi6 > 70
        patterns['rsi_oversold_14'] = rsi14 < 30
        patterns['rsi_overbought_14'] = rsi14 > 70
        
        # RSI divergence
        patterns['rsi_bullish_div'] = (df['close'] < df['close'].shift(2)) & (rsi14 > rsi14.shift(2))
        patterns['rsi_bearish_div'] = (df['close'] > df['close'].shift(2)) & (rsi14 < rsi14.shift(2))
        
        # 2. MACD Paternleri
        macd_line, signal_line, histogram = self.calculate_macd(df['close'])
        patterns['macd_bullish_cross'] = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))
        patterns['macd_bearish_cross'] = (macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))
        patterns['macd_above_zero'] = macd_line > 0
        patterns['macd_below_zero'] = macd_line < 0
        
        # 3. Moving Average Paternleri
        sma50 = self.calculate_sma(df['close'], 50)
        sma200 = self.calculate_sma(df['close'], 200)
        ema9 = self.calculate_ema(df['close'], 9)
        ema21 = self.calculate_ema(df['close'], 21)
        
        patterns['golden_cross'] = (sma50 > sma200) & (sma50.shift(1) <= sma200.shift(1))
        patterns['death_cross'] = (sma50 < sma200) & (sma50.shift(1) >= sma200.shift(1))
        patterns['ema_bullish_cross'] = (ema9 > ema21) & (ema9.shift(1) <= ema21.shift(1))
        patterns['ema_bearish_cross'] = (ema9 < ema21) & (ema9.shift(1) >= ema21.shift(1))
        
        # 4. Bollinger Bands Paternleri
        bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(df['close'])
        patterns['bb_oversold'] = df['close'] < bb_lower
        patterns['bb_overbought'] = df['close'] > bb_upper
        patterns['bb_squeeze'] = (bb_upper - bb_lower) < ((bb_upper - bb_lower).rolling(20).mean() * 0.5)
        
        # 5. Stochastic Paternleri
        stoch_k, stoch_d = self.calculate_stochastic(df)
        patterns['stoch_oversold'] = stoch_k < 20
        patterns['stoch_overbought'] = stoch_k > 80
        patterns['stoch_bullish_cross'] = (stoch_k > stoch_d) & (stoch_k.shift(1) <= stoch_d.shift(1))
        patterns['stoch_bearish_cross'] = (stoch_k < stoch_d) & (stoch_k.shift(1) >= stoch_d.shift(1))
        
        # 6. Volume Paternleri
        obv = self.calculate_obv(df)
        patterns['volume_spike'] = df['volume'] > (df['volume'].rolling(20).mean() * 2.5)
        patterns['obv_bullish_div'] = (df['close'] < df['close'].shift(2)) & (obv > obv.shift(2))
        patterns['obv_bearish_div'] = (df['close'] > df['close'].shift(2)) & (obv < obv.shift(2))
        
        # 7. ICT Paternleri
        avg_range = ha_range.rolling(5).mean()
        narrow_prev = ha_range.shift(1) < (avg_range.shift(1) * 1.5)
        wide_now = ha_range > (avg_range * 1.5)
        
        patterns['crt_buy'] = narrow_prev & wide_now & (ha_close > ha['ha_open']) & (ha_close > df['high'].shift(1))
        patterns['crt_sell'] = narrow_prev & wide_now & (ha_close < ha['ha_open']) & (ha_close < df['low'].shift(1))
        
        # FVG (Fair Value Gap)
        patterns['fvg_up'] = df['low'] > df['high'].shift(2)
        patterns['fvg_down'] = df['high'] < df['low'].shift(2)
        
        # Order Blocks
        patterns['bull_ob'] = (df['close'].shift(1) < df['open'].shift(1)) & (df['close'] > df['high'].shift(1)) & (df['close'] > df['open'])
        patterns['bear_ob'] = (df['close'].shift(1) > df['open'].shift(1)) & (df['close'] < df['low'].shift(1)) & (df['close'] < df['open'])
        
        # 8. Mum Paternleri
        patterns['bullish_engulfing'] = (df['close'].shift(1) < df['open'].shift(1)) & (df['open'] < df['close'].shift(1)) & (df['close'] > df['open'].shift(1))
        patterns['bearish_engulfing'] = (df['close'].shift(1) > df['open'].shift(1)) & (df['open'] > df['close'].shift(1)) & (df['close'] < df['open'].shift(1))
        
        # Pin Bar / Hammer / Shooting Star
        body = (df['close'] - df['open']).abs()
        lower_wick = pd.concat([df['open'], df['close']], axis=1).min(axis=1) - df['low']
        upper_wick = df['high'] - pd.concat([df['open'], df['close']], axis=1).max(axis=1)
        
        patterns['bullish_pin'] = (lower_wick > 2 * body) & (upper_wick < body) & (df['close'] > df['open'])
        patterns['bearish_pin'] = (upper_wick > 2 * body) & (lower_wick < body) & (df['close'] < df['open'])
        
        # Doji
        patterns['doji'] = body < (0.1 * (df['high'] - df['low']))
        
        # Morning Star / Evening Star
        patterns['morning_star'] = (df['close'].shift(2) < df['open'].shift(2)) & \
                                  (df['close'].shift(1) < df['open'].shift(1)) & \
                                  (df['close'] > df['open']) & \
                                  (df['close'] > ((df['open'].shift(2) + df['close'].shift(2)) / 2))
        
        patterns['evening_star'] = (df['close'].shift(2) > df['open'].shift(2)) & \
                                  (df['close'].shift(1) > df['open'].shift(1)) & \
                                  (df['close'] < df['open']) & \
                                  (df['close'] < ((df['open'].shift(2) + df['close'].shift(2)) / 2))
        
        # Three White Soldiers / Three Black Crows
        patterns['three_white_soldiers'] = (df['close'] > df['open']) & \
                                          (df['close'].shift(1) > df['open'].shift(1)) & \
                                          (df['close'].shift(2) > df['open'].shift(2)) & \
                                          (df['close'] > df['close'].shift(1)) & \
                                          (df['close'].shift(1) > df['close'].shift(2))
        
        patterns['three_black_crows'] = (df['close'] < df['open']) & \
                                       (df['close'].shift(1) < df['open'].shift(1)) & \
                                       (df['close'].shift(2) < df['open'].shift(2)) & \
                                       (df['close'] < df['close'].shift(1)) & \
                                       (df['close'].shift(1) < df['close'].shift(2))
        
        # 9. Support/Resistance Paternleri
        # Double Top/Bottom
        patterns['double_top'] = (df['high'] < df['high'].shift(1)) & (df['high'].shift(1) > df['high'].shift(2)) & \
                                (abs(df['high'].shift(1) - df['high']) < (df['high'].shift(1) * 0.02))
        
        patterns['double_bottom'] = (df['low'] > df['low'].shift(1)) & (df['low'].shift(1) < df['low'].shift(2)) & \
                                   (abs(df['low'].shift(1) - df['low']) < (df['low'].shift(1) * 0.02))
        
        # Support/Resistance Break
        patterns['support_bounce'] = (df['low'] > df['low'].rolling(20).min().shift(1)) & (df['close'] > df['open'])
        patterns['resistance_break'] = (df['high'] > df['high'].rolling(20).max().shift(1)) & (df['close'] > df['open'])
        
        # 10. Killzone Paternleri
        if isinstance(df.index, pd.DatetimeIndex):
            hours = df.index.hour
        else:
            hours = pd.Series([datetime.utcnow().hour] * len(df))
            
        patterns['london_kz'] = (hours >= 7) & (hours < 10)
        patterns['ny_kz'] = (hours >= 13) & (hours < 16)
        patterns['asia_kz'] = (hours >= 0) & (hours < 4)
        patterns['in_killzone'] = patterns['london_kz'] | patterns['ny_kz'] | patterns['asia_kz']
        
        # 11. Trend Paternleri
        patterns['uptrend'] = df['close'] > sma50
        patterns['downtrend'] = df['close'] < sma50
        patterns['strong_uptrend'] = (df['close'] > sma50) & (sma50 > sma200)
        patterns['strong_downtrend'] = (df['close'] < sma50) & (sma50 < sma200)
        
        # 12. Diğer Paternler
        patterns['inside_bar'] = (df['high'] < df['high'].shift(1)) & (df['low'] > df['low'].shift(1))
        patterns['outside_bar'] = (df['high'] > df['high'].shift(1)) & (df['low'] < df['low'].shift(1))
        
        patterns['gaps_up'] = df['low'] > df['high'].shift(1)
        patterns['gaps_down'] = df['high'] < df['low'].shift(1)
        
        # İndikatör değerlerini de kaydet
        patterns['rsi6'] = rsi6
        patterns['rsi14'] = rsi14
        patterns['macd'] = macd_line
        patterns['macd_signal'] = signal_line
        patterns['sma50'] = sma50
        patterns['sma200'] = sma200
        patterns['volume'] = df['volume']
        
        return patterns
    
    # ==================== FİBONACCİ HESAPLAMA ====================
    
    def detect_fibonacci_levels(self, df: pd.DataFrame, ph: pd.Series, pl: pd.Series) -> pd.DataFrame:
        """Fibonacci retracement seviyeleri"""
        df = df.copy()
        
        for level in self._fib_levels:
            col_name = f'fib_{str(level).replace(".", "")}'
            df[col_name] = np.nan
        
        df['fib_direction'] = ''
        df['fib_ote_zone'] = False

        ph_series = ph.dropna()
        pl_series = pl.dropna()

        if len(ph_series) < 1 or len(pl_series) < 1:
            return df

        last_ph_idx = ph_series.index[-1]
        last_pl_idx = pl_series.index[-1]

        try:
            if last_ph_idx > last_pl_idx:
                high_price = df.loc[last_ph_idx, 'high']
                low_price = df.loc[last_pl_idx, 'low']
                fib_range = high_price - low_price
                if fib_range > 0:
                    for level in self._fib_levels:
                        col_name = f'fib_{str(level).replace(".", "")}'
                        df[col_name] = high_price - (fib_range * level)
                    df['fib_direction'] = 'bearish'
                    if 'fib_618' in df.columns and 'fib_705' in df.columns:
                        df['fib_ote_zone'] = (df['close'] >= df['fib_618']) & (df['close'] <= df['fib_705'])
            else:
                low_price = df.loc[last_pl_idx, 'low']
                high_price = df.loc[last_ph_idx, 'high']
                fib_range = high_price - low_price
                if fib_range > 0:
                    for level in self._fib_levels:
                        col_name = f'fib_{str(level).replace(".", "")}'
                        df[col_name] = low_price + (fib_range * level)
                    df['fib_direction'] = 'bullish'
                    if 'fib_618' in df.columns and 'fib_705' in df.columns:
                        df['fib_ote_zone'] = (df['close'] >= df['fib_618']) & (df['close'] <= df['fib_705'])
        except Exception as e:
            logger.debug(f"Fibonacci hatası: {e}")

        return df
    
    # ==================== SİNYAL SKORU HESAPLAMA ====================
    
    def calculate_signal_score(self, patterns: Dict[str, pd.Series]) -> int:
        """Tüm paternleri değerlendirerek sinyal skoru hesapla"""
        score = 0
        idx = -1
        
        try:
            # 1. RSI Paternleri (20-30 puan)
            if patterns.get('rsi6_crossover', pd.Series([False])).iloc[idx]:
                score += 25
            if patterns.get('rsi6_crossunder', pd.Series([False])).iloc[idx]:
                score -= 25
            if patterns.get('rsi_oversold_6', pd.Series([False])).iloc[idx]:
                score += 20
            if patterns.get('rsi_overbought_6', pd.Series([False])).iloc[idx]:
                score -= 20
            if patterns.get('rsi_bullish_div', pd.Series([False])).iloc[idx]:
                score += 30
            if patterns.get('rsi_bearish_div', pd.Series([False])).iloc[idx]:
                score -= 30
            
            # 2. MACD Paternleri (15-25 puan)
            if patterns.get('macd_bullish_cross', pd.Series([False])).iloc[idx]:
                score += 20
            if patterns.get('macd_bearish_cross', pd.Series([False])).iloc[idx]:
                score -= 20
            if patterns.get('macd_above_zero', pd.Series([False])).iloc[idx]:
                score += 15
            if patterns.get('macd_below_zero', pd.Series([False])).iloc[idx]:
                score -= 15
            
            # 3. Moving Average Paternleri (20-30 puan)
            if patterns.get('golden_cross', pd.Series([False])).iloc[idx]:
                score += 30
            if patterns.get('death_cross', pd.Series([False])).iloc[idx]:
                score -= 30
            if patterns.get('ema_bullish_cross', pd.Series([False])).iloc[idx]:
                score += 20
            if patterns.get('ema_bearish_cross', pd.Series([False])).iloc[idx]:
                score -= 20
            
            # 4. ICT Paternleri (25-40 puan)
            if patterns.get('crt_buy', pd.Series([False])).iloc[idx]:
                score += 35
            if patterns.get('crt_sell', pd.Series([False])).iloc[idx]:
                score -= 35
            if patterns.get('fvg_up', pd.Series([False])).iloc[idx]:
                score += 30
            if patterns.get('fvg_down', pd.Series([False])).iloc[idx]:
                score -= 30
            if patterns.get('bull_ob', pd.Series([False])).iloc[idx]:
                score += 25
            if patterns.get('bear_ob', pd.Series([False])).iloc[idx]:
                score -= 25
            
            # 5. Mum Paternleri (15-25 puan)
            if patterns.get('bullish_engulfing', pd.Series([False])).iloc[idx]:
                score += 20
            if patterns.get('bearish_engulfing', pd.Series([False])).iloc[idx]:
                score -= 20
            if patterns.get('bullish_pin', pd.Series([False])).iloc[idx]:
                score += 15
            if patterns.get('bearish_pin', pd.Series([False])).iloc[idx]:
                score -= 15
            if patterns.get('morning_star', pd.Series([False])).iloc[idx]:
                score += 25
            if patterns.get('evening_star', pd.Series([False])).iloc[idx]:
                score -= 25
            
            # 6. Support/Resistance (20-25 puan)
            if patterns.get('support_bounce', pd.Series([False])).iloc[idx]:
                score += 20
            if patterns.get('resistance_break', pd.Series([False])).iloc[idx]:
                score += 25
            if patterns.get('double_bottom', pd.Series([False])).iloc[idx]:
                score += 20
            if patterns.get('double_top', pd.Series([False])).iloc[idx]:
                score -= 20
            
            # 7. Volume Paternleri (10-15 puan)
            if patterns.get('volume_spike', pd.Series([False])).iloc[idx]:
                score += 10
            if patterns.get('obv_bullish_div', pd.Series([False])).iloc[idx]:
                score += 15
            if patterns.get('obv_bearish_div', pd.Series([False])).iloc[idx]:
                score -= 15
            
            # 8. Killzone Bonusları (10-20 puan)
            if patterns.get('in_killzone', pd.Series([False])).iloc[idx]:
                score += 15
            if patterns.get('london_kz', pd.Series([False])).iloc[idx]:
                score += 10
            if patterns.get('ny_kz', pd.Series([False])).iloc[idx]:
                score += 12
            if patterns.get('asia_kz', pd.Series([False])).iloc[idx]:
                score += 8
            
            # 9. Trend Gücü (10-20 puan)
            if patterns.get('strong_uptrend', pd.Series([False])).iloc[idx]:
                score += 15
            if patterns.get('strong_downtrend', pd.Series([False])).iloc[idx]:
                score -= 15
            
            # 10. Bollinger Bands (10-15 puan)
            if patterns.get('bb_oversold', pd.Series([False])).iloc[idx]:
                score += 12
            if patterns.get('bb_overbought', pd.Series([False])).iloc[idx]:
                score -= 12
            if patterns.get('bb_squeeze', pd.Series([False])).iloc[idx]:
                score += 10  # Squeeze sonrası breakout beklentisi
            
            # 11. Stochastic (10-15 puan)
            if patterns.get('stoch_oversold', pd.Series([False])).iloc[idx]:
                score += 12
            if patterns.get('stoch_overbought', pd.Series([False])).iloc[idx]:
                score -= 12
            if patterns.get('stoch_bullish_cross', pd.Series([False])).iloc[idx]:
                score += 10
            if patterns.get('stoch_bearish_cross', pd.Series([False])).iloc[idx]:
                score -= 10
            
            # 12. Diğer Paternler (5-10 puan)
            if patterns.get('three_white_soldiers', pd.Series([False])).iloc[idx]:
                score += 15
            if patterns.get('three_black_crows', pd.Series([False])).iloc[idx]:
                score -= 15
            if patterns.get('outside_bar', pd.Series([False])).iloc[idx] and patterns.get('bullish_engulfing', pd.Series([False])).iloc[idx]:
                score += 10
            if patterns.get('outside_bar', pd.Series([False])).iloc[idx] and patterns.get('bearish_engulfing', pd.Series([False])).iloc[idx]:
                score -= 10
                
        except Exception as e:
            logger.debug(f"Skor hesaplama hatası: {e}")
        
        return score
    
    # ==================== SİNYAL ANALİZİ ====================
    
    def analyze_market_structure(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Piyasa yapısı analizi"""
        close = df['close']
        high = df['high']
        low = df['low']
        
        # Higher High/Lower Low analizi
        hh = (high > high.shift(1)) & (high.shift(1) > high.shift(2))
        ll = (low < low.shift(1)) & (low.shift(1) < low.shift(2))
        
        # Structure değişimleri
        structure_bullish = hh.any() and not ll.any()
        structure_bearish = ll.any() and not hh.any()
        
        # Break of Structure (BOS)
        bos_bullish = structure_bullish and (close.iloc[-1] > high.rolling(20).max().iloc[-2])
        bos_bearish = structure_bearish and (close.iloc[-1] < low.rolling(20).min().iloc[-2])
        
        # Change of Character (CHoCH)
        choch_bullish = structure_bearish and (close.iloc[-1] > high.rolling(10).max().iloc[-2])
        choch_bearish = structure_bullish and (close.iloc[-1] < low.rolling(10).min().iloc[-2])
        
        return {
            'market_structure': 'BULLISH' if structure_bullish else 'BEARISH' if structure_bearish else 'NEUTRAL',
            'bos': 'BULLISH' if bos_bullish else 'BEARISH' if bos_bearish else 'NONE',
            'choch': 'BULLISH' if choch_bullish else 'BEARISH' if choch_bearish else 'NONE',
            'higher_highs': int(hh.iloc[-1]) if len(hh) > 0 else 0,
            'lower_lows': int(ll.iloc[-1]) if len(ll) > 0 else 0
        }

# GLOBAL INSTANCE
grok = GrokIndicators()

def generate_ict_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """
    TÜM paternleri kullanarak sinyal üret - WebSocket'e gönder
    """
    try:
        if len(df) < 50:
            logger.warning(f"{symbol}: Yetersiz veri ({len(df)})")
            return generate_simple_signal(df, symbol, timeframe)

        required = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required):
            logger.error(f"{symbol}: Eksik sütun")
            return generate_simple_signal(df, symbol, timeframe)

        df = df.copy()
        df = df.astype(float, errors='ignore')
        
        # Pivot detection
        df['pivot_high'], df['pivot_low'] = grok.detect_pivots(df['high'], df['low'])
        
        # Volume profile
        _, poc_price, (va_low, va_high) = grok.calculate_volume_profile(df)
        
        # TÜM paternleri tespit et
        patterns = grok.detect_all_patterns(df)
        
        # Fibonacci
        df = grok.detect_fibonacci_levels(df, df['pivot_high'], df['pivot_low'])
        
        # Market structure
        market_structure = grok.analyze_market_structure(df)
        
        # Sinyal skoru hesapla
        signal_score = grok.calculate_signal_score(patterns)
        
        # Skoru normalize et (0-100)
        normalized_score = int(np.clip((signal_score + 150) * 100 / 300, 0, 100))
        
        # Mevcut fiyat
        last = df.iloc[-1]
        current_price = float(last['close'])
        
        # Tetikleyen paternleri listele
        active_patterns = []
        for pattern_name, pattern_series in patterns.items():
            if isinstance(pattern_series, pd.Series) and not pattern_name.startswith(('rsi', 'macd', 'sma', 'ema', 'volume')):
                if pattern_series.iloc[-1] and pattern_series.dtype == bool:
                    # Patern adını düzgün formatla
                    name = pattern_name.replace('_', ' ').title()
                    active_patterns.append(name)
        
        # Killzone belirle
        killzone = "London" if patterns.get('london_kz', pd.Series([False])).iloc[-1] else \
                  "New York" if patterns.get('ny_kz', pd.Series([False])).iloc[-1] else \
                  "Asia" if patterns.get('asia_kz', pd.Series([False])).iloc[-1] else "Normal"
        
        # Sinyal gücü
        signal_strength = "ELITE" if normalized_score >= 85 else \
                         "GÜÇLÜ" if normalized_score >= 70 else \
                         "ORTA" if normalized_score >= 55 else "ZAYIF"
        
        # Sinyal metni
        if signal_score > 0:
            signal_text = "🚀 ELITE ALIM" if normalized_score >= 85 else \
                         "📈 GÜÇLÜ ALIM" if normalized_score >= 70 else \
                         "🟢 ALIM" if normalized_score >= 55 else "⚪️ NÖTR ALIM"
        elif signal_score < 0:
            signal_text = "🔥 ELITE SATIM" if normalized_score >= 85 else \
                         "📉 GÜÇLÜ SATIM" if normalized_score >= 70 else \
                         "🔴 SATIM" if normalized_score >= 55 else "⚪️ NÖTR SATIM"
        else:
            signal_text = "⏸️ NÖTR"
        
        # Structure bilgisi ekle
        structure_info = market_structure['market_structure']
        if market_structure['bos'] != 'NONE':
            structure_info += f" | BOS: {market_structure['bos']}"
        if market_structure['choch'] != 'NONE':
            structure_info += f" | ChoCH: {market_structure['choch']}"
        
        # İndikatör değerleri
        rsi6_val = float(patterns.get('rsi6', pd.Series([50])).iloc[-1])
        rsi14_val = float(patterns.get('rsi14', pd.Series([50])).iloc[-1])
        macd_val = float(patterns.get('macd', pd.Series([0])).iloc[-1])
        
        triggers = active_patterns[:8]  # İlk 8 aktif patern
        trigger_text = " | ".join(triggers) if triggers else f"RSI6: {rsi6_val:.1f}"
        
        logger.info(f"🎯 {symbol}/{timeframe} → {signal_text} | Skor: {normalized_score} | Patern: {len(active_patterns)}")
        
        return {
            "pair": symbol.replace("USDT", "/USDT"),
            "timeframe": timeframe.upper(),
            "current_price": round(current_price, 6 if current_price < 1 else 4),
            "signal": signal_text,
            "score": normalized_score,
            "strength": signal_strength,
            "killzone": killzone,
            "triggers": trigger_text,
            "structure": structure_info,
            "indicators": {
                "rsi6": round(rsi6_val, 1),
                "rsi14": round(rsi14_val, 1),
                "macd": round(macd_val, 4)
            },
            "active_patterns": len(active_patterns),
            "last_update": datetime.utcnow().strftime("%H:%M:%S UTC")
        }

    except Exception as e:
        logger.error(f"Sinyal hatası {symbol}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return generate_simple_signal(df, symbol, timeframe)

def generate_simple_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """Basit sinyal üretimi (fallback)"""
    try:
        if len(df) < 10:
            return None
        close = df['close']
        last = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        change = (last - prev) / prev * 100 if prev != 0 else 0
        
        # RSI hesapla
        rsi = grok.calculate_rsi(close, 14)
        rsi_val = float(rsi.iloc[-1])
        
        # Sinyal belirle
        if change > 0.5 and rsi_val < 70:
            signal = "🟢 ALIM"
            score = min(90, int(change * 10 + 50))
        elif change < -0.5 and rsi_val > 30:
            signal = "🔴 SATIM"
            score = min(90, int(abs(change) * 10 + 50))
        else:
            signal = "⚪️ NÖTR"
            score = 50
        
        return {
            "pair": symbol.replace("USDT", "/USDT"),
            "timeframe": timeframe.upper(),
            "current_price": round(last, 6 if last < 1 else 4),
            "signal": signal,
            "score": score,
            "strength": "YÜKSEK" if score >= 70 else "ORTA",
            "killzone": "Normal",
            "triggers": f"Change: {change:+.2f}% | RSI: {rsi_val:.1f}",
            "structure": "BASIC",
            "indicators": {"rsi": round(rsi_val, 1)},
            "active_patterns": 0,
            "last_update": datetime.utcnow().strftime("%H:%M:%S UTC")
        }
    except Exception as e:
        logger.error(f"Basit sinyal hatası: {e}")
        return None
