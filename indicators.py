import numpy as np
import pandas as pd
from typing import Tuple, Optional, Dict, Any, List, Union
import logging
from functools import lru_cache

# Logging ayarları
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("grok_indicators")


class GrokIndicators:
    """
    Grok Trade Elite için optimize edilmiş, ICT/SMC tarzı teknik göstergeler sınıfı.
    Tüm metodlar time-series güvenli, NaN korumalı ve vektörel hesaplama destekli.
    """

    def __init__(self):
        self._cache = {}
        self._fib_levels_default = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]

    # ===================== CACHE UTILS =====================
    @lru_cache(maxsize=128)
    def _hash_series(self, series: tuple, *args) -> int:
        return hash((series, args))

    # ===================== TEMEL GÖSTERGELER =====================

    @staticmethod
    def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """Relative Strength Index (RSI) — Wilder's EMA yöntemiyle"""
        if len(prices) < period:
            return pd.Series([50.0] * len(prices), index=prices.index, dtype=float)

        diff = prices.diff()
        gain = diff.where(diff > 0, 0.0)
        loss = -diff.where(diff < 0, 0.0)

        # Wilder smoothing via EMA with alpha=1/period
        avg_gain = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()

        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.clip(0, 100).fillna(50.0)

    @staticmethod
    def calculate_sma(prices: pd.Series, period: int) -> pd.Series:
        """Simple Moving Average (SMA)"""
        return prices.rolling(window=period, min_periods=1).mean()

    @staticmethod
    def calculate_ema(prices: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average (EMA)"""
        return prices.ewm(span=period, adjust=False, min_periods=period).mean()

    @staticmethod
    def calculate_bollinger_bands(prices: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Bollinger Bands (Upper, Middle, Lower)"""
        sma = prices.rolling(window=period, min_periods=1).mean()
        std = prices.rolling(window=period, min_periods=1).std()
        upper = sma + std_dev * std
        lower = sma - std_dev * std
        return upper, sma, lower

    # ===================== VOLUME GÖSTERGELERİ =====================

    @staticmethod
    def calculate_vwap(df: pd.DataFrame) -> pd.Series:
        """Volume Weighted Average Price (VWAP) — intraday için"""
        # VWAP genellikle günlük resetlenir, bu yüzden cumsum her session başı resetlenmeli (geliştirme yapılacaksa)
        typical_price = (df['high'] + df['low'] + df['close']) / 3.0
        cum_tp_vol = (typical_price * df['volume']).cumsum()
        cum_vol = df['volume'].cumsum()
        return (cum_tp_vol / (cum_vol + 1e-10)).fillna(method='ffill')

    def calculate_volume_profile(self, df: pd.DataFrame, bins: int = 50, lookback: Optional[int] = None) -> Tuple[pd.DataFrame, float, Tuple[float, float]]:
        """
        Volume Profile + Point of Control (POC) + Value Area (70%)
        """
        data = df.iloc[-lookback:] if lookback and len(df) > lookback else df.copy()
        if len(data) == 0:
            return pd.DataFrame(columns=['price_level', 'volume_profile']), 0.0, (0.0, 0.0)

        price_min, price_max = data['low'].min(), data['high'].max()
        if not (np.isfinite(price_min) and np.isfinite(price_max)) or price_max <= price_min:
            mid = data['close'].mean()
            return pd.DataFrame(), float(mid), (float(mid - 1), float(mid + 1))

        bin_edges = np.linspace(price_min, price_max, bins + 1)
        centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0
        profile = np.zeros(bins)

        vol = data['volume'].values
        low_idx = np.searchsorted(bin_edges, data['low'].values, side='right') - 1
        high_idx = np.searchsorted(bin_edges, data['high'].values, side='right') - 1

        low_idx = np.clip(low_idx, 0, bins - 1)
        high_idx = np.clip(high_idx, low_idx, bins - 1)

        for i in range(len(data)):
            li, hi = low_idx[i], high_idx[i]
            n_bins = max(1, hi - li + 1)
            profile[li:hi+1] += vol[i] / n_bins

        vp_df = pd.DataFrame({
            'price_level': centers,
            'volume_profile': profile
        })

        if profile.sum() == 0:
            poc = data['close'].mean()
            return vp_df, float(poc), (float(price_min), float(price_max))

        poc_idx = int(np.argmax(profile))
        poc = centers[poc_idx]

        # Value Area (top 70% volume)
        sorted_indices = np.argsort(profile)[::-1]
        cumsum_vol = np.cumsum(profile[sorted_indices])
        cutoff_idx = np.searchsorted(cumsum_vol, 0.7 * profile.sum())
        va_indices = sorted_indices[:cutoff_idx + 1]
        va_low = float(centers[va_indices.min()])
        va_high = float(centers[va_indices.max()])

        return vp_df, poc, (va_low, va_high)

    @staticmethod
    def calculate_volume_oscillator(volume: pd.Series, short_period: int = 5, long_period: int = 20) -> pd.Series:
        """Volume Oscillator (%)"""
        short_ma = volume.rolling(short_period, min_periods=1).mean()
        long_ma = volume.rolling(long_period, min_periods=1).mean()
        return ((short_ma - long_ma) / (long_ma + 1e-10)) * 100.0

    # ===================== MOMENTUM GÖSTERGELERİ =====================

    @staticmethod
    def calculate_macd(prices: pd.Series, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """MACD Line, Signal, Histogram"""
        fast_ema = prices.ewm(span=fast_period, adjust=False).mean()
        slow_ema = prices.ewm(span=slow_period, adjust=False).mean()
        macd = fast_ema - slow_ema
        signal = macd.ewm(span=signal_period, adjust=False).mean()
        histogram = macd - signal
        return macd, signal, histogram

    @staticmethod
    def calculate_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3, smoothing: int = 3) -> Tuple[pd.Series, pd.Series]:
        """Stochastic Oscillator (Fast/Slow)"""
        low_min = df['low'].rolling(k_period, min_periods=1).min()
        high_max = df['high'].rolling(k_period, min_periods=1).max()
        k = 100.0 * (df['close'] - low_min) / (high_max - low_min + 1e-10)
        k = k.rolling(smoothing, min_periods=1).mean()
        d = k.rolling(d_period, min_iterations=1).mean()
        return k.clip(0, 100), d.clip(0, 100)

    @staticmethod
    def calculate_momentum(prices: pd.Series, period: int = 10) -> pd.Series:
        return prices.diff(period)

    # ===================== VOLATİLİTE GÖSTERGELERİ =====================

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range (ATR) — Wilder method"""
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift()).abs(),
            (df['low'] - df['close'].shift()).abs()
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()

    @staticmethod
    def calculate_standard_deviation(prices: pd.Series, period: int = 20) -> pd.Series:
        return prices.rolling(window=period, min_periods=1).std()

    # ===================== HEIKIN-ASHI & ICT CORE =====================

    @staticmethod
    def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
        """Heikin-Ashi candlesticks — vektörize edilmiş (döngüsüzsüz)"""
        ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4.0
        ha_open = pd.Series(index=df.index, dtype=float)
        ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2.0
        ha_open.iloc[1:] = (ha_open.shift(1) + ha_close.shift(1)).iloc[1:] / 2.0
        ha_high = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
        ha_low = pd.concat([df['low'], ha_open, ha_close], axis=1).min(axis=1)

        return pd.DataFrame({
            'ha_open': ha_open,
            'ha_high': ha_high,
            'ha_low': ha_low,
            'ha_close': ha_close
        })

    @staticmethod
    def detect_pivots(high: pd.Series, low: pd.Series, length: int = 5) -> Tuple[pd.Series, pd.Series]:
        """Rolling pivot detection (vectorized)"""
        window = 2 * length + 1
        roll_high = high.rolling(window, center=True, min_periods=1).max()
        roll_low = low.rolling(window, center=True, min_periods=1).min()

        piv_high = (high == roll_high)
        piv_low = (low == roll_low)
        return piv_high.fillna(False), piv_low.fillna(False)

    def calculate_fibonacci_levels(self, high: float, low: float, levels: Optional[List[float]] = None) -> Dict[str, float]:
        if levels is None:
            levels = self._fib_levels_default
        rng = high - low
        return {f"fib_{lvl:.3f}": high - lvl * rng for lvl in levels}

    @staticmethod
    def detect_fvg(df: pd.DataFrame, gap_threshold: float = 0.0001) -> Tuple[pd.Series, pd.Series]:
        """
        Fair Value Gap (FVG) detection — modern SMC tanımı:
        FVG = üç mumlu yapı; ortadaki mum, bir önceki ve bir sonraki mumların high/low aralıklarını *tamamen* içermemeli.
        """
        # Bullish FVG: low[i] > high[i-2]
        fvg_up = (df['low'] > df['high'].shift(2) + gap_threshold)
        # Bearish FVG: high[i] < low[i-2]
        fvg_down = (df['high'] < df['low'].shift(2) - gap_threshold)
        return fvg_up.fillna(False), fvg_down.fillna(False)

    @staticmethod
    def detect_order_blocks(df: pd.DataFrame, confirmation_candles: int = 2) -> Tuple[pd.Series, pd.Series]:
        """
        Simple Order Block detection:
        - Bullish OB: bearish candle → strong bullish breakout
        - Bearish OB: bullish candle → strong bearish breakout
        """
        bearish_candle = df['close'] < df['open']
        bullish_candle = df['close'] > df['open']

        bullish_ob = bearish_candle.shift(1) & bullish_candle & (df['close'] > df['high'].shift(1))
        bearish_ob = bullish_candle.shift(1) & bearish_candle & (df['close'] < df['low'].shift(1))

        return bullish_ob.fillna(False), bearish_ob.fillna(False)

    # ===================== DESTEK/DİRENÇ =====================

    def calculate_support_resistance(self, df: pd.DataFrame, lookback: int = 100, threshold: float = 0.005) -> Dict[str, List[float]]:
        """Destek/Direnç seviyelerini peak detection + clustering ile tespit eder."""
        recent = df.tail(lookback)
        highs, lows = recent['high'], recent['low']

        # Basit pivot detection (window=5)
        high_peaks = highs[(highs > highs.shift(1)) & (highs > highs.shift(-1)) & (highs > highs.shift(2)) & (highs > highs.shift(-2))]
        low_peaks = lows[(lows < lows.shift(1)) & (lows < lows.shift(-1)) & (lows < lows.shift(2)) & (lows < lows.shift(-2))]

        def cluster_levels(vals: pd.Series, thresh: float) -> List[float]:
            if len(vals) == 0:
                return []
            vals_sorted = np.sort(vals.dropna().values)
            clusters = []
            curr_cluster = [vals_sorted[0]]
            for val in vals_sorted[1:]:
                if abs(val - curr_cluster[-1]) <= thresh * curr_cluster[-1]:
                    curr_cluster.append(val)
                else:
                    clusters.append(np.mean(curr_cluster))
                    curr_cluster = [val]
            clusters.append(np.mean(curr_cluster))
            return sorted(clusters)

        thresh_price = threshold * recent['close'].mean()
        resistances = cluster_levels(high_peaks, thresh_price)
        supports = cluster_levels(low_peaks, thresh_price)

        return {
            'resistance': sorted(resistances, reverse=True)[:5],
            'support': sorted(supports)[:5]
        }

    # ===================== ICT-SPECIFIC OSCILLATORS =====================

    def calculate_ict_rsi_oscillator(self, df: pd.DataFrame, rsi_period: int = 6, sma_period: int = 50) -> Dict[str, pd.Series]:
        """ICT RSI6 + SMA50 on RSI — Heikin-Ashi close ile"""
        ha = self.calculate_heikin_ashi(df)
        rsi6 = self.calculate_rsi(ha['ha_close'], rsi_period)
        sma50 = self.calculate_sma(rsi6, sma_period)

        crossover = (rsi6 > sma50) & (rsi6.shift(1) <= sma50.shift(1))
        crossunder = (rsi6 < sma50) & (rsi6.shift(1) >= sma50.shift(1))

        return {
            'rsi6': rsi6,
            'sma50_rsi': sma50,
            'rsi6_above_sma50': rsi6 > sma50,
            'rsi6_below_sma50': rsi6 < sma50,
            'rsi6_crossover': crossover,
            'rsi6_crossunder': crossunder
        }

    def calculate_crt_pattern(self, df: pd.DataFrame, lookback: int = 5, range_multiplier: float = 1.5) -> Tuple[pd.Series, pd.Series]:
        """Compression → Release → Thrust pattern"""
        ha = self.calculate_heikin_ashi(df)
        ha_range = ha['ha_high'] - ha['ha_low']
        avg_range = ha_range.rolling(lookback, min_periods=1).mean()

        compression = (ha_range.shift(1) < avg_range.shift(1) * range_multiplier)
        release = (ha_range > avg_range * range_multiplier)

        bullish_thrust = (ha['ha_close'] > ha['ha_open']) & (ha['ha_close'] > ha['ha_high'].shift(1))
        bearish_thrust = (ha['ha_close'] < ha['ha_open']) & (ha['ha_close'] < ha['ha_low'].shift(1))

        return compression & release & bullish_thrust, compression & release & bearish_thrust

    # ===================== CANDLE PATTERNS (VEKTÖRİZE) =====================

    @staticmethod
    def detect_candle_patterns(df: pd.DataFrame) -> Dict[str, pd.Series]:
        o, h, l, c = df['open'], df['high'], df['low'], df['close']
        body = (c - o).abs()
        lower_wick = pd.concat([o, c], axis=1).min(axis=1) - l
        upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)
        total_range = h - l + 1e-10

        return {
            'bullish_engulfing': (c.shift(1) < o.shift(1)) & (c > o) & (c > o.shift(1)) & (o < c.shift(1)),
            'bearish_engulfing': (c.shift(1) > o.shift(1)) & (c < o) & (c < o.shift(1)) & (o > c.shift(1)),
            'bullish_pin': (lower_wick > 2 * body) & (upper_wick < 0.5 * body),
            'bearish_pin': (upper_wick > 2 * body) & (lower_wick < 0.5 * body),
            'doji': (body / total_range < 0.1) & (total_range > 1e-8),
            'hammer': (lower_wick > 2 * body) & (upper_wick < 0.3 * body) & (c > o),
            'hanging_man': (lower_wick > 2 * body) & (upper_wick < 0.3 * body) & (c < o),
        }

    # ===================== ZAMAN & SEANS GÖSTERGELERİ =====================

    @staticmethod
    def detect_killzone(index: pd.DatetimeIndex) -> Dict[str, pd.Series]:
        utc_hour = index.hour
        london = (utc_hour >= 7) & (utc_hour < 10)   # ~08:00–11:00 TRT, Londra açılış
        ny = (utc_hour >= 12) & (utc_hour < 15)      # ~15:00–18:00 TRT, NY açılış
        return {
            'london_kz': london,
            'ny_kz': ny,
            'in_killzone': london | ny
        }

    @staticmethod
    def detect_market_session(index: pd.DatetimeIndex) -> pd.Series:
        hour = index.hour
        session = pd.Series('Unknown', index=index)
        session[(hour >= 0) & (hour < 8)] = 'Asia'
        session[(hour >= 8) & (hour < 16)] = 'London'
        session[(hour >= 16) & (hour < 24)] = 'NewYork'
        return session

    # ===================== TÜM GÖSTERGELERİ BİR ARAYA GETİRME =====================

    def calculate_all_indicators(self, df: pd.DataFrame, symbol: str = "UNKNOWN") -> pd.DataFrame:
        """
        Tüm göstergeleri hesaplayıp genişletilmiş bir DataFrame döndürür.
        `df` mutasyona uğramaz — yeni kopya oluşturulur.
        """
        if df.empty:
            logger.warning("Boş DataFrame alındı.")
            return df.copy()

        required_cols = {'open', 'high', 'low', 'close'}
        if not required_cols.issubset(df.columns):
            missing = required_cols - set(df.columns)
            raise ValueError(f"Eksik sütunlar: {missing}")

        result = df.copy()
        try:
            # ————— Temel Trend & Volatilite —————
            result['sma_20'] = self.calculate_sma(result['close'], 20)
            result['sma_50'] = self.calculate_sma(result['close'], 50)
            result['sma_200'] = self.calculate_sma(result['close'], 200)
            result['ema_12'] = self.calculate_ema(result['close'], 12)
            result['ema_26'] = self.calculate_ema(result['close'], 26)

            bb_up, bb_mid, bb_low = self.calculate_bollinger_bands(result['close'])
            result['bb_upper'], result['bb_middle'], result['bb_lower'] = bb_up, bb_mid, bb_low
            result['bb_width'] = (bb_up - bb_low) / (bb_mid + 1e-10)

            result['rsi_14'] = self.calculate_rsi(result['close'], 14)
            result['rsi_6'] = self.calculate_rsi(result['close'], 6)

            macd, macd_sig, macd_hist = self.calculate_macd(result['close'])
            result['macd'], result['macd_signal'], result['macd_hist'] = macd, macd_sig, macd_hist

            stoch_k, stoch_d = self.calculate_stochastic(result)
            result['stoch_k'], result['stoch_d'] = stoch_k, stoch_d

            result['atr_14'] = self.calculate_atr(result, 14)
            result['volatility_20'] = self.calculate_standard_deviation(result['close'], 20)

            # ————— Volume —————
            if 'volume' in result.columns:
                result['volume_sma_20'] = self.calculate_sma(result['volume'], 20)
                result['volume_osc'] = self.calculate_volume_oscillator(result['volume'])
                result['vwap'] = self.calculate_vwap(result)

            # ————— Pivots & Levels —————
            piv_high, piv_low = self.detect_pivots(result['high'], result['low'], 5)
            result['pivot_high'], result['pivot_low'] = piv_high, piv_low

            # ————— Heikin-Ashi —————
            ha = self.calculate_heikin_ashi(result)
            result = pd.concat([result, ha], axis=1)

            # ————— ICT Özel —————
            ict_rsi = self.calculate_ict_rsi_oscillator(result)
            for k, v in ict_rsi.items():
                result[f'ict_{k}'] = v

            crt_b, crt_s = self.calculate_crt_pattern(result)
            result['crt_buy'], result['crt_sell'] = crt_b, crt_s

            fvg_up, fvg_down = self.detect_fvg(result)
            result['fvg_up'], result['fvg_down'] = fvg_up, fvg_down

            ob_bull, ob_bear = self.detect_order_blocks(result)
            result['ob_bullish'], result['ob_bearish'] = ob_bull, ob_bear

            # ————— Candle Patterns —————
            patterns = self.detect_candle_patterns(result)
            result = result.assign(**{k: v.astype(bool) for k, v in patterns.items()})

            # ————— Zaman —————
            if isinstance(result.index, pd.DatetimeIndex):
                tz_naive = result.index.tz_localize(None) if result.index.tz else result.index
                kill = self.detect_killzone(tz_naive)
                result['in_london_kz'] = kill['london_kz']
                result['in_ny_kz'] = kill['ny_kz']
                result['in_killzone'] = kill['in_killzone']
                result['market_session'] = self.detect_market_session(tz_naive)
            else:
                result['in_london_kz'] = False
                result['in_ny_kz'] = False
                result['in_killzone'] = False
                result['market_session'] = 'Unknown'

            # ————— Trend & Sinyal —————
            result['trend'] = pd.cut(
                result['close'] - result['sma_50'],
                bins=[-np.inf, -1e-8, 1e-8, np.inf],
                labels=['Bearish', 'Neutral', 'Bullish']
            ).astype(str)

            result['momentum_10'] = self.calculate_momentum(result['close'], 10)
            result['momentum_signal'] = pd.cut(
                result['momentum_10'],
                bins=[-np.inf, -1e-8, 1e-8, np.inf],
                labels=['Bearish', 'Neutral', 'Bullish']
            ).astype(str)

            logger.info(f"✅ [{symbol}] Tüm göstergeler başarıyla hesaplandı.")
            return result

        except Exception as e:
            logger.exception(f"❌ [{symbol}] Gösterge hesaplama hatası: {e}")
            raise
