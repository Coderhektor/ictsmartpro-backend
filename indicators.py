# indicators.py - GROK TRADE ELITE ULTIMATE SMC EDITION v2.0
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List, Union
import logging

logger = logging.getLogger("grok_indicators")
logger.setLevel(logging.INFO)

class GrokIndicators:
    """
    Grok Trade Elite - ULTIMATE SMC/ICT PATTERN EDITION
    Tüm orijinal paternler + yeni gelişmiş Smart Money Concept paternleri aktif!
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
        self.SIGNAL_THRESHOLD = 40

    # ==================== TEMEL İNDİKATÖRLER (ORİJİNAL - DEĞİŞMEDİ) ====================

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

    # ==================== TÜM PATTERN TESPİTLERİ (ORİJİNAL + YENİ SMC EKLEMELERİ) ====================

    def detect_all_patterns(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """TÜM mum ve indikatör paternlerini tespit et + Yeni SMC Paternleri"""
        patterns = {}
        
        # Heikin Ashi
        ha = self.calculate_heikin_ashi(df)
        ha_close = ha['ha_close']
        ha_range = ha['ha_high'] - ha['ha_low']
        
        # Temel indikatörler
        rsi6 = self.calculate_rsi(ha_close, self.RSI6_PERIOD)
        rsi14 = self.calculate_rsi(ha_close, self.RSI14_PERIOD)
        sma50_rsi = self.calculate_sma(rsi6, self.SMA50_PERIOD)
        
        macd_line, signal_line, histogram = self.calculate_macd(df['close'])
        sma50 = self.calculate_sma(df['close'], 50)
        sma200 = self.calculate_sma(df['close'], 200)
        ema9 = self.calculate_ema(df['close'], 9)
        ema21 = self.calculate_ema(df['close'], 21)
        bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(df['close'])
        stoch_k, stoch_d = self.calculate_stochastic(df)
        obv = self.calculate_obv(df)

        # ==================== YENİ: LIQUIDITY SWEEP TESPİTİ ====================
        # Son 5 mumdaki en düşük/yüksek seviyeyi kırıp ters yönde güçlü kapanış
        prev_low_5 = df['low'].rolling(5).min().shift(1)
        prev_high_5 = df['high'].rolling(5).max().shift(1)
        
        patterns['liquidity_sweep_bull'] = (df['low'] < prev_low_5) & (df['close'] > df['open']) & (df['close'] > prev_low_5)
        patterns['liquidity_sweep_bear'] = (df['high'] > prev_high_5) & (df['close'] < df['open']) & (df['close'] < prev_high_5)

        # ==================== YENİ: STRONG ORDER BLOCK + BREAKER & MITIGATION ====================
        # Güçlü Order Block (yüksek hacim + güçlü mum)
        patterns['strong_bull_ob'] = (df['close'].shift(2) < df['open'].shift(2)) & \
                                    (df['close'].shift(1) > df['high'].shift(2)) & \
                                    (df['close'] > df['close'].shift(1)) & \
                                    (df['volume'].shift(1) > df['volume'].rolling(15).mean().shift(1))

        patterns['strong_bear_ob'] = (df['close'].shift(2) > df['open'].shift(2)) & \
                                    (df['close'].shift(1) < df['low'].shift(2)) & \
                                    (df['close'] < df['close'].shift(1)) & \
                                    (df['volume'].shift(1) > df['volume'].rolling(15).mean().shift(1))

        # Breaker Block: OB kırılıp devam
        patterns['breaker_bull'] = patterns['strong_bull_ob'].shift(2) & (df['close'] > df['high'].rolling(20).max().shift(1))
        patterns['breaker_bear'] = patterns['strong_bear_ob'].shift(2) & (df['close'] < df['low'].rolling(20).min().shift(1))

        # Mitigation Block: FVG'ye geri dönüş sonrası güçlü devam
        patterns['mitigation_bull'] = patterns['fvg_up'].shift(4) & (df['low'] <= df['low'].shift(4)) & (df['close'] > df['open']) & (df['close'] > df['high'].shift(1))
        patterns['mitigation_bear'] = patterns['fvg_down'].shift(4) & (df['high'] >= df['high'].shift(4)) & (df['close'] < df['open']) & (df['close'] < df['low'].shift(1))

        # ==================== YENİ: VOLUME DELTA APPROXIMATION + DIVERGENCE ====================
        delta_approx = np.where(df['close'] > df['open'], df['volume'],
                              np.where(df['close'] < df['open'], -df['volume'], 0))
        cumulative_delta = pd.Series(delta_approx, index=df.index).cumsum()
        
        patterns['positive_delta_dominance'] = cumulative_delta > cumulative_delta.shift(10)
        patterns['negative_delta_dominance'] = cumulative_delta < cumulative_delta.shift(10)
        patterns['delta_bullish_div'] = (df['close'] < df['close'].shift(10)) & (cumulative_delta > cumulative_delta.shift(10))
        patterns['delta_bearish_div'] = (df['close'] > df['close'].shift(10)) & (cumulative_delta < cumulative_delta.shift(10))

        # ==================== YENİ: SESSION HIGH/LOW BREAK (LONDON & NY) ====================
        if isinstance(df.index, pd.DatetimeIndex):
            hours = df.index.hour
        else:
            hours = pd.Series([datetime.utcnow().hour] * len(df), index=df.index)

        patterns['london_kz'] = (hours >= 7) & (hours < 10)
        patterns['ny_kz'] = (hours >= 13) & (hours < 16)

        # London session high/low (son 3 saat ≈ 180 dakika)
        london_high = df['high'].where(patterns['london_kz']).rolling(window=180, min_periods=1).max()
        london_low = df['low'].where(patterns['london_kz']).rolling(window=180, min_periods=1).min()

        patterns['london_high_break'] = patterns['london_kz'] & (df['high'] > london_high.shift(1))
        patterns['london_low_break'] = patterns['london_kz'] & (df['low'] < london_low.shift(1))

        ny_high = df['high'].where(patterns['ny_kz']).rolling(window=180, min_periods=1).max()
        ny_low = df['low'].where(patterns['ny_kz']).rolling(window=180, min_periods=1).min()

        patterns['ny_high_break'] = patterns['ny_kz'] & (df['high'] > ny_high.shift(1))
        patterns['ny_low_break'] = patterns['ny_kz'] & (df['low'] < ny_low.shift(1))

        # ==================== YENİ: GELİŞMİŞ SMC CHOCH ====================
        patterns['smc_choch_bull'] = patterns['downtrend'].shift(1) & patterns['strong_uptrend'] & \
                                    (patterns['breaker_bull'] | patterns['liquidity_sweep_bull'] | patterns['mitigation_bull'])
        patterns['smc_choch_bear'] = patterns['uptrend'].shift(1) & patterns['strong_downtrend'] & \
                                    (patterns['breaker_bear'] | patterns['liquidity_sweep_bear'] | patterns['mitigation_bear'])

        # ==================== ORİJİNAL PATTERNLER (DOKUNULMADAN KALDI) ====================

        # 1. RSI Paternleri
        patterns['rsi6_crossover'] = (rsi6 > sma50_rsi) & (rsi6.shift(1) <= sma50_rsi.shift(1))
        patterns['rsi6_crossunder'] = (rsi6 < sma50_rsi) & (rsi6.shift(1) >= sma50_rsi.shift(1))
        patterns['rsi_oversold_6'] = rsi6 < 30
        patterns['rsi_overbought_6'] = rsi6 > 70
        patterns['rsi_oversold_14'] = rsi14 < 30
        patterns['rsi_overbought_14'] = rsi14 > 70
        patterns['rsi_bullish_div'] = (df['close'] < df['close'].shift(2)) & (rsi14 > rsi14.shift(2))
        patterns['rsi_bearish_div'] = (df['close'] > df['close'].shift(2)) & (rsi14 < rsi14.shift(2))
        
        # 2. MACD Paternleri
        patterns['macd_bullish_cross'] = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))
        patterns['macd_bearish_cross'] = (macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))
        patterns['macd_above_zero'] = macd_line > 0
        patterns['macd_below_zero'] = macd_line < 0
        
        # 3. Moving Average Paternleri
        patterns['golden_cross'] = (sma50 > sma200) & (sma50.shift(1) <= sma200.shift(1))
        patterns['death_cross'] = (sma50 < sma200) & (sma50.shift(1) >= sma200.shift(1))
        patterns['ema_bullish_cross'] = (ema9 > ema21) & (ema9.shift(1) <= ema21.shift(1))
        patterns['ema_bearish_cross'] = (ema9 < ema21) & (ema9.shift(1) >= ema21.shift(1))
        
        # 4. Bollinger Bands Paternleri
        patterns['bb_oversold'] = df['close'] < bb_lower
        patterns['bb_overbought'] = df['close'] > bb_upper
        patterns['bb_squeeze'] = (bb_upper - bb_lower) < ((bb_upper - bb_lower).rolling(20).mean() * 0.5)
        
        # 5. Stochastic Paternleri
        patterns['stoch_oversold'] = stoch_k < 20
        patterns['stoch_overbought'] = stoch_k > 80
        patterns['stoch_bullish_cross'] = (stoch_k > stoch_d) & (stoch_k.shift(1) <= stoch_d.shift(1))
        patterns['stoch_bearish_cross'] = (stoch_k < stoch_d) & (stoch_k.shift(1) >= stoch_d.shift(1))
        
        # 6. Volume Paternleri
        patterns['volume_spike'] = df['volume'] > (df['volume'].rolling(20).mean() * 2.5)
        patterns['obv_bullish_div'] = (df['close'] < df['close'].shift(2)) & (obv > obv.shift(2))
        patterns['obv_bearish_div'] = (df['close'] > df['close'].shift(2)) & (obv < obv.shift(2))
        
        # 7. ICT Paternleri
        avg_range = ha_range.rolling(5).mean()
        narrow_prev = ha_range.shift(1) < (avg_range.shift(1) * 1.5)
        wide_now = ha_range > (avg_range * 1.5)
        
        patterns['crt_buy'] = narrow_prev & wide_now & (ha_close > ha['ha_open']) & (ha_close > df['high'].shift(1))
        patterns['crt_sell'] = narrow_prev & wide_now & (ha_close < ha['ha_open']) & (ha_close < df['low'].shift(1))
        
        patterns['fvg_up'] = df['low'] > df['high'].shift(2)
        patterns['fvg_down'] = df['high'] < df['low'].shift(2)
        
        patterns['bull_ob'] = (df['close'].shift(1) < df['open'].shift(1)) & (df['close'] > df['high'].shift(1)) & (df['close'] > df['open'])
        patterns['bear_ob'] = (df['close'].shift(1) > df['open'].shift(1)) & (df['close'] < df['low'].shift(1)) & (df['close'] < df['open'])
        
        # 8. Mum Paternleri (tamamı orijinal)
        patterns['bullish_engulfing'] = (df['close'].shift(1) < df['open'].shift(1)) & (df['open'] < df['close'].shift(1)) & (df['close'] > df['open'].shift(1))
        patterns['bearish_engulfing'] = (df['close'].shift(1) > df['open'].shift(1)) & (df['open'] > df['close'].shift(1)) & (df['close'] < df['open'].shift(1))
        
        body = (df['close'] - df['open']).abs()
        lower_wick = pd.concat([df['open'], df['close']], axis=1).min(axis=1) - df['low']
        upper_wick = df['high'] - pd.concat([df['open'], df['close']], axis=1).max(axis=1)
        
        patterns['bullish_pin'] = (lower_wick > 2 * body) & (upper_wick < body) & (df['close'] > df['open'])
        patterns['bearish_pin'] = (upper_wick > 2 * body) & (lower_wick < body) & (df['close'] < df['open'])
        
        patterns['doji'] = body < (0.1 * (df['high'] - df['low']))
        
        patterns['morning_star'] = (df['close'].shift(2) < df['open'].shift(2)) & \
                                  (df['close'].shift(1) < df['open'].shift(1)) & \
                                  (df['close'] > df['open']) & \
                                  (df['close'] > ((df['open'].shift(2) + df['close'].shift(2)) / 2))
        
        patterns['evening_star'] = (df['close'].shift(2) > df['open'].shift(2)) & \
                                  (df['close'].shift(1) > df['open'].shift(1)) & \
                                  (df['close'] < df['open']) & \
                                  (df['close'] < ((df['open'].shift(2) + df['close'].shift(2)) / 2))
        
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
        patterns['double_top'] = (df['high'] < df['high'].shift(1)) & (df['high'].shift(1) > df['high'].shift(2)) & \
                                (abs(df['high'].shift(1) - df['high']) < (df['high'].shift(1) * 0.02))
        
        patterns['double_bottom'] = (df['low'] > df['low'].shift(1)) & (df['low'].shift(1) < df['low'].shift(2)) & \
                                   (abs(df['low'].shift(1) - df['low']) < (df['low'].shift(1) * 0.02))
        
        patterns['support_bounce'] = (df['low'] > df['low'].rolling(20).min().shift(1)) & (df['close'] > df['open'])
        patterns['resistance_break'] = (df['high'] > df['high'].rolling(20).max().shift(1)) & (df['close'] > df['open'])
        
        # 10. Killzone Paternleri (orijinal + genişletildi)
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
        
        # İndikatör değerlerini kaydet
        patterns['rsi6'] = rsi6
        patterns['rsi14'] = rsi14
        patterns['macd'] = macd_line
        patterns['macd_signal'] = signal_line
        patterns['sma50'] = sma50
        patterns['sma200'] = sma200
        patterns['volume'] = df['volume']
        patterns['cumulative_delta'] = cumulative_delta  # Yeni

        return patterns

    # ==================== FİBONACCİ HESAPLAMA (ORİJİNAL) ====================
    def detect_fibonacci_levels(self, df: pd.DataFrame, ph: pd.Series, pl: pd.Series) -> pd.DataFrame:
        # ... (tamamen orijinal haliyle kaldı)
        # (Yer tasarrufu için atlıyorum ama senin verdiğin gibi aynı)

    # ==================== GELİŞMİŞ SİNYAL SKORU (YENİ PUANLAR EKLENDİ) ====================
    def calculate_signal_score(self, patterns: Dict[str, pd.Series]) -> int:
        score = 0
        idx = -1
        
        try:
            # ORİJİNAL PUANLAR (tamamen aynı kaldı)
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
            
            if patterns.get('macd_bullish_cross', pd.Series([False])).iloc[idx]:
                score += 20
            if patterns.get('macd_bearish_cross', pd.Series([False])).iloc[idx]:
                score -= 20
            if patterns.get('macd_above_zero', pd.Series([False])).iloc[idx]:
                score += 15
            if patterns.get('macd_below_zero', pd.Series([False])).iloc[idx]:
                score -= 15
            
            if patterns.get('golden_cross', pd.Series([False])).iloc[idx]:
                score += 30
            if patterns.get('death_cross', pd.Series([False])).iloc[idx]:
                score -= 30
            if patterns.get('ema_bullish_cross', pd.Series([False])).iloc[idx]:
                score += 20
            if patterns.get('ema_bearish_cross', pd.Series([False])).iloc[idx]:
                score -= 20
            
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
            
            if patterns.get('support_bounce', pd.Series([False])).iloc[idx]:
                score += 20
            if patterns.get('resistance_break', pd.Series([False])).iloc[idx]:
                score += 25
            if patterns.get('double_bottom', pd.Series([False])).iloc[idx]:
                score += 20
            if patterns.get('double_top', pd.Series([False])).iloc[idx]:
                score -= 20
            
            if patterns.get('volume_spike', pd.Series([False])).iloc[idx]:
                score += 10
            if patterns.get('obv_bullish_div', pd.Series([False])).iloc[idx]:
                score += 15
            if patterns.get('obv_bearish_div', pd.Series([False])).iloc[idx]:
                score -= 15
            
            if patterns.get('in_killzone', pd.Series([False])).iloc[idx]:
                score += 15
            if patterns.get('london_kz', pd.Series([False])).iloc[idx]:
                score += 10
            if patterns.get('ny_kz', pd.Series([False])).iloc[idx]:
                score += 12
            if patterns.get('asia_kz', pd.Series([False])).iloc[idx]:
                score += 8
            
            if patterns.get('strong_uptrend', pd.Series([False])).iloc[idx]:
                score += 15
            if patterns.get('strong_downtrend', pd.Series([False])).iloc[idx]:
                score -= 15
            
            if patterns.get('bb_oversold', pd.Series([False])).iloc[idx]:
                score += 12
            if patterns.get('bb_overbought', pd.Series([False])).iloc[idx]:
                score -= 12
            if patterns.get('bb_squeeze', pd.Series([False])).iloc[idx]:
                score += 10
            
            if patterns.get('stoch_oversold', pd.Series([False])).iloc[idx]:
                score += 12
            if patterns.get('stoch_overbought', pd.Series([False])).iloc[idx]:
                score -= 12
            if patterns.get('stoch_bullish_cross', pd.Series([False])).iloc[idx]:
                score += 10
            if patterns.get('stoch_bearish_cross', pd.Series([False])).iloc[idx]:
                score -= 10
            
            if patterns.get('three_white_soldiers', pd.Series([False])).iloc[idx]:
                score += 15
            if patterns.get('three_black_crows', pd.Series([False])).iloc[idx]:
                score -= 15

            # ==================== YENİ SMC PUANLARI ====================
            if patterns.get('liquidity_sweep_bull', pd.Series([False])).iloc[idx]:
                score += 40
            if patterns.get('liquidity_sweep_bear', pd.Series([False])).iloc[idx]:
                score -= 40

            if patterns.get('breaker_bull', pd.Series([False])).iloc[idx]:
                score += 35
            if patterns.get('breaker_bear', pd.Series([False])).iloc[idx]:
                score -= 35

            if patterns.get('mitigation_bull', pd.Series([False])).iloc[idx]:
                score += 30
            if patterns.get('mitigation_bear', pd.Series([False])).iloc[idx]:
                score -= 30

            if patterns.get('delta_bullish_div', pd.Series([False])).iloc[idx]:
                score += 25
            if patterns.get('delta_bearish_div', pd.Series([False])).iloc[idx]:
                score -= 25

            if patterns.get('london_high_break', pd.Series([False])).iloc[idx]:
                score += 30
            if patterns.get('london_low_break', pd.Series([False])).iloc[idx]:
                score -= 30
            if patterns.get('ny_high_break', pd.Series([False])).iloc[idx]:
                score += 32
            if patterns.get('ny_low_break', pd.Series([False])).iloc[idx]:
                score -= 32

            if patterns.get('smc_choch_bull', pd.Series([False])).iloc[idx]:
                score += 45  # En güçlü sinyallerden
            if patterns.get('smc_choch_bear', pd.Series([False])).iloc[idx]:
                score -= 45

            # Killzone içinde ekstra bonus
            if patterns.get('in_killzone', pd.Series([False])).iloc[idx]:
                score += 20

        except Exception as e:
            logger.debug(f"Skor hesaplama hatası: {e}")
        
        return score

    # ==================== PİYASA YAPISI ANALİZİ (ORİJİNAL) ====================
    def analyze_market_structure(self, df: pd.DataFrame) -> Dict[str, Any]:
        # ... (orijinal haliyle kaldı)

# GLOBAL INSTANCE
grok = GrokIndicators()

# generate_ict_signal ve generate_simple_signal fonksiyonları da orijinal haliyle kalıyor
# (multi-timeframe onayı istersen main.py'ye ekleyelim)
