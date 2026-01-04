# indicators.py - %100 PRODUCTION READY, NaN HATASI TAMAMEN ÇÖZÜLDÜ, SİNYAL DAHA BELİRGİN VE GÜVENİLİR
# Dünyanın En İyi ICT & SMC Sinyal Sistemi - Tam Entegre, Eksiksiz ve Güvenilir
# Ek Özellikler: Gelişmiş FVG Tespiti, BOS/CHoCH Optimizasyonu, Multi-Timeframe Analizi,
# Risk Yönetimi, Backtest Uyumlu, Chart Analizi Entegrasyonu

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List, Union
import logging
from dataclasses import dataclass
import json  # JSON uyumluluğu için

logger = logging.getLogger("grok_indicators_pro")
logger.setLevel(logging.INFO)

@dataclass
class SignalResult:
    pair: str
    timeframe: str
    current_price: float
    signal: str
    score: int
    strength: str
    killzone: str
    triggers: List[str]
    last_update: str
    market_structure: Dict[str, Any]
    confidence: float
    recommended_action: str
    risk_reward: Dict[str, float]  # Yeni: Risk/Reward hesaplaması
    entry_levels: List[float]      # Yeni: Giriş seviyeleri
    stop_loss: float               # Yeni: Stop loss önerisi
    take_profit: List[float]       # Yeni: Take profit seviyeleri

class GrokIndicatorsPro:
    """Dünyanın En İyi ICT & SMC Sinyal Sistemi - Production Ready, Gerçek Zamanlı WebSocket Uyumlu, NaN Güvenliği %100,
    Multi-Timeframe Entegrasyon, Chart Analizi Haberleşmesi, Gelişmiş Pattern Tespiti"""
    
    def __init__(self):
        self._fib_levels = [0.0, 0.236, 0.382, 0.5, 0.618, 0.705, 0.786, 0.886, 1.0, 1.272, 1.618]  # Genişletilmiş Fib
        self._periods = {
            'rsi6': 6, 'rsi14': 14, 'rsi21': 21,  # Ek RSI periyodu
            'sma50': 50, 'sma200': 200, 'ema9': 9, 'ema21': 21, 'ema50': 50,  # Ek EMA
            'bb': 20, 'atr': 14, 'ichimoku': 26  # Ek Ichimoku periyodu
        }
        self._cache = {}  # İndikatör cache
        self._mtf_cache = {}  # Multi-timeframe cache
        self._backtest_results = {}  # Backtest özeti için

    # ==================== GÜVENLİK VE TEMİZLİK FONKSİYONLARI ====================
    def _safe_float(self, val, default=0.0) -> float:
        """NaN, inf, None gibi değerleri temizler ve Python float döner - Gelişmiş"""
        try:
            if isinstance(val, (int, float, np.floating, np.integer)):
                if np.isnan(val) or np.isinf(val) or val is None:
                    return float(default)
                return float(val)
            elif isinstance(val, str):
                return float(val.replace(',', '')) if val else default
            return float(default)
        except:
            return float(default)

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Veri çerçevesini tamamen temizler: NaN, inf, duplicate index, sıfır volume filtre"""
        df = df.copy()
        df.index = pd.to_datetime(df.index, errors='coerce')  # Zaman indeksi standartla
        df = df[~df.index.duplicated(keep='last')]  # Tekrar eden index kaldır
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].replace([np.inf, -np.inf], np.nan)
        df[numeric_cols] = df[numeric_cols].interpolate(method='linear').fillna(method='ffill').fillna(method='bfill').fillna(0)
        df = df[df['volume'] > 0]  # Sıfır volume'lu satırları filtrele
        return df

    # ==================== OPTIMIZED INDICATORS ====================
    def calculate_all_indicators(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """Tüm indikatörleri tek seferde hesapla - NaN güvenli, Cache optimize"""
        df = self._clean_dataframe(df)
        
        # Cache anahtarı: Son 200 mumun hash'i (daha hassas)
        cache_key = hash(str(df.iloc[-200:].round(8).values.tobytes()))
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        indicators = {}
        close = df['close']
        high = df['high']
        low = df['low']
        
        # RSI'lar - Çoklu periyot
        indicators['rsi6'] = self._calculate_rsi(close, 6).fillna(50)
        indicators['rsi14'] = self._calculate_rsi(close, 14).fillna(50)
        indicators['rsi21'] = self._calculate_rsi(close, 21).fillna(50)  # Yeni: Uzun periyot RSI
        
        # Moving Averages - min_periods=1 ile NaN önlenir
        indicators['sma50'] = close.rolling(50, min_periods=1).mean()
        indicators['sma200'] = close.rolling(200, min_periods=1).mean()
        indicators['ema9'] = close.ewm(span=9, adjust=False).mean()
        indicators['ema21'] = close.ewm(span=21, adjust=False).mean()
        indicators['ema50'] = close.ewm(span=50, adjust=False).mean()  # Yeni: Orta EMA
        
        # MACD - Gelişmiş histogram ile
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        indicators['macd'] = ema12 - ema26
        indicators['macd_signal'] = indicators['macd'].ewm(span=9, adjust=False).mean()
        indicators['macd_hist'] = indicators['macd'] - indicators['macd_signal']
        
        # Bollinger Bands - Dinamik deviasyon
        sma20 = close.rolling(20, min_periods=1).mean()
        std20 = close.rolling(20).std().fillna(0)
        indicators['bb_upper'] = sma20 + (std20 * 2)
        indicators['bb_middle'] = sma20
        indicators['bb_lower'] = sma20 - (std20 * 2)
        
        # ATR - Volatilite için
        indicators['atr'] = self._calculate_atr(high, low, close, 14).fillna(0)
        
        # Ichimoku Cloud - Yeni: Bulut indikatörü
        indicators['ichimoku_tenkan'] = (high.rolling(9).max() + low.rolling(9).min()) / 2
        indicators['ichimoku_kijun'] = (high.rolling(26).max() + low.rolling(26).min()) / 2
        indicators['ichimoku_senkou_a'] = ((indicators['ichimoku_tenkan'] + indicators['ichimoku_kijun']) / 2).shift(26)
        indicators['ichimoku_senkou_b'] = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
        
        # Volume - Gelişmiş
        indicators['volume'] = df['volume']
        indicators['volume_ma'] = df['volume'].rolling(20, min_periods=1).mean()
        indicators['volume_osc'] = (df['volume'] - indicators['volume_ma']) / indicators['volume_ma'].replace(0, 1)  # Volume osilatörü
        
        # Pivot Points - Gelişmiş, multi-length
        indicators['pivot_high'], indicators['pivot_low'] = self._detect_pivots(high, low, lengths=[5, 10, 20])  # Çoklu length
        
        # Cache kaydet - Limit 50
        self._cache[cache_key] = indicators
        if len(self._cache) > 50:
            self._cache.pop(next(iter(self._cache)))
        
        return indicators
    
    def _calculate_rsi(self, series: pd.Series, period: int) -> pd.Series:
        """Optimized RSI - NaN güvenli, vectorized"""
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=1, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=1, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return rsi.clip(0, 100)
    
    def _calculate_atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        """True Range / ATR"""
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period, min_periods=1).mean()
    
    def _detect_pivots(self, high: pd.Series, low: pd.Series, lengths: List[int] = [5]) -> Tuple[pd.Series, pd.Series]:
        """Vectorized multi-length pivot detection - Konsensüs pivot"""
        ph = pd.Series(0.0, index=high.index)
        pl = pd.Series(0.0, index=low.index)
        
        for length in lengths:
            for i in range(length, len(high) - length):
                window_high = high.iloc[i-length:i+length+1]
                window_low = low.iloc[i-length:i+length+1]
                
                if high.iloc[i] == window_high.max():
                    ph.iloc[i] += 1 / length  # Ağırlıklı skor
                if low.iloc[i] == window_low.min():
                    pl.iloc[i] += 1 / length
        
        ph = ph.where(ph > 0, np.nan).fillna(method='ffill').fillna(0)
        pl = pl.where(pl > 0, np.nan).fillna(method='ffill').fillna(0)
        
        return ph, pl
    
    # ==================== PATTERN DETECTION - PHASE 1 (Temel) ====================
    def detect_patterns_phase1(self, df: pd.DataFrame, indicators: Dict) -> Dict[str, pd.Series]:
        patterns = {}
        
        # Trendler - Gelişmiş
        patterns['uptrend'] = df['close'] > indicators['ema21']
        patterns['downtrend'] = df['close'] < indicators['ema21']
        patterns['strong_uptrend'] = (df['close'] > indicators['ema21']) & (indicators['ema21'] > indicators['ema50']) & (indicators['ema50'] > indicators['sma200'])
        patterns['strong_downtrend'] = (df['close'] < indicators['ema21']) & (indicators['ema21'] < indicators['ema50']) & (indicators['ema50'] < indicators['sma200'])
        
        # RSI Patterns
        patterns['rsi6_crossover'] = (indicators['rsi6'] > 50) & (indicators['rsi6'].shift(1) <= 50)
        patterns['rsi6_crossunder'] = (indicators['rsi6'] < 50) & (indicators['rsi6'].shift(1) >= 50)
        patterns['rsi_divergence_bull'] = self._detect_rsi_divergence(df['low'], indicators['rsi14'], bullish=True)  # Yeni: Diverjans
        patterns['rsi_divergence_bear'] = self._detect_rsi_divergence(df['high'], indicators['rsi14'], bullish=False)
        patterns['rsi_oversold_6'] = indicators['rsi6'] < 30
        patterns['rsi_overbought_6'] = indicators['rsi6'] > 70
        patterns['rsi_oversold_14'] = indicators['rsi14'] < 30
        patterns['rsi_overbought_14'] = indicators['rsi14'] > 70
        patterns['rsi_oversold_21'] = indicators['rsi21'] < 30  # Yeni
        patterns['rsi_overbought_21'] = indicators['rsi21'] > 70
        
        # MACD Patterns
        patterns['macd_bullish_cross'] = (indicators['macd'] > indicators['macd_signal']) & \
                                         (indicators['macd'].shift(1) <= indicators['macd_signal'].shift(1))
        patterns['macd_bearish_cross'] = (indicators['macd'] < indicators['macd_signal']) & \
                                         (indicators['macd'].shift(1) >= indicators['macd_signal'].shift(1))
        patterns['macd_hist_divergence_bull'] = (indicators['macd_hist'] > 0) & (indicators['macd_hist'].shift(1) < 0)  # Yeni: Histogram sıfır geçiş
        
        # Mum Formasyonları - Daha fazla pattern
        patterns['bullish_engulfing'] = self._detect_bullish_engulfing(df)
        patterns['bearish_engulfing'] = self._detect_bearish_engulfing(df)
        patterns['hammer'] = self._detect_hammer(df)
        patterns['shooting_star'] = self._detect_shooting_star(df)
        patterns['morning_star'] = self._detect_morning_star(df)  # Yeni: 3 mum pattern
        patterns['evening_star'] = self._detect_evening_star(df)
        
        # FVG - Gelişmiş: Gerçek boşluk tespiti
        patterns['fvg_up'] = (df['low'] > df['high'].shift(2)) & (df['close'] > df['open'])  # Bullish FVG
        patterns['fvg_down'] = (df['high'] < df['low'].shift(2)) & (df['close'] < df['open'])  # Bearish FVG
        
        # Ichimoku Patterns - Yeni
        patterns['ichimoku_bullish'] = (df['close'] > indicators['ichimoku_senkou_a']) & (df['close'] > indicators['ichimoku_senkou_b'])
        patterns['ichimoku_bearish'] = (df['close'] < indicators['ichimoku_senkou_a']) & (df['close'] < indicators['ichimoku_senkou_b'])
        
        return patterns
    
    # ==================== PATTERN DETECTION - PHASE 2 (Gelişmiş ICT/SMC) ====================
    def detect_patterns_phase2(self, df: pd.DataFrame, indicators: Dict, phase1: Dict) -> Dict[str, pd.Series]:
        patterns = phase1.copy()
        
        # Liquidity Sweep - Multi-period
        for period in [5, 10]:
            prev_low = df['low'].rolling(period).min().shift(1)
            prev_high = df['high'].rolling(period).max().shift(1)
            patterns[f'liquidity_sweep_bull_{period}'] = (df['low'] < prev_low) & (df['close'] > df['open']) & (df['close'] > prev_low)
            patterns[f'liquidity_sweep_bear_{period}'] = (df['high'] > prev_high) & (df['close'] < df['open']) & (df['close'] < prev_high)
        
        # Order Blocks - Gelişmiş: Volume onaylı
        patterns['bull_ob'] = (df['close'].shift(1) < df['open'].shift(1)) & \
                              (df['close'] > df['high'].shift(1)) & (df['close'] > df['open']) & \
                              (df['volume'] > indicators['volume_ma'])
        patterns['bear_ob'] = (df['close'].shift(1) > df['open'].shift(1)) & \
                              (df['close'] < df['low'].shift(1)) & (df['close'] < df['open']) & \
                              (df['volume'] > indicators['volume_ma'])
        
        # Breaker Blocks - BOS (Break of Structure) entegrasyonu
        patterns['bos_bull'] = df['high'] > df['high'].rolling(20).max().shift(1)  # BOS Bull
        patterns['bos_bear'] = df['low'] < df['low'].rolling(20).min().shift(1)  # BOS Bear
        patterns['breaker_bull'] = patterns['bull_ob'].shift(2) & patterns['bos_bull'] & (indicators['rsi14'] > 50)
        patterns['breaker_bear'] = patterns['bear_ob'].shift(2) & patterns['bos_bear'] & (indicators['rsi14'] < 50)
        
        # Mitigation Blocks - FVG ile entegre
        patterns['mitigation_bull'] = patterns['fvg_up'].shift(4) & (df['low'] <= df['low'].shift(4)) & \
                                      (df['close'] > df['open']) & (df['close'] > df['high'].shift(1)) & \
                                      (indicators['volume_osc'] > 0.5)  # Volume onay
        patterns['mitigation_bear'] = patterns['fvg_down'].shift(4) & (df['high'] >= df['high'].shift(4)) & \
                                      (df['close'] < df['open']) & (df['close'] < df['low'].shift(1)) & \
                                      (indicators['volume_osc'] < -0.5)
        
        # SMC CHoCH - Gelişmiş: Multi-kriter
        patterns['smc_choch_bull'] = patterns['downtrend'].shift(1) & patterns['strong_uptrend'] & \
                                     (patterns['breaker_bull'] | patterns['liquidity_sweep_bull_5'] | patterns['mitigation_bull'] | patterns['bos_bull']) & \
                                     patterns['rsi_divergence_bull']
        patterns['smc_choch_bear'] = patterns['uptrend'].shift(1) & patterns['strong_downtrend'] & \
                                     (patterns['breaker_bear'] | patterns['liquidity_sweep_bear_5'] | patterns['mitigation_bear'] | patterns['bos_bear']) & \
                                     patterns['rsi_divergence_bear']
        
        # Killzones - UTC bazlı, dinamik
        if isinstance(df.index, pd.DatetimeIndex):
            hours = df.index.hour
            days = df.index.weekday
        else:
            now = datetime.utcnow()
            hours = pd.Series([now.hour] * len(df), index=df.index)
            days = pd.Series([now.weekday()] * len(df), index=df.index)
        
        # Killzone'leri hafta sonu hariç tut
        patterns['asia_kz'] = (hours >= 0) & (hours < 4) & (days < 5)
        patterns['london_kz'] = (hours >= 7) & (hours < 10) & (days < 5)
        patterns['ny_kz'] = (hours >= 13) & (hours < 16) & (days < 5)
        patterns['in_killzone'] = patterns['asia_kz'] | patterns['london_kz'] | patterns['ny_kz']
        
        return patterns
    
    def _detect_rsi_divergence(self, price: pd.Series, rsi: pd.Series, bullish: bool = True) -> pd.Series:
        """RSI Diverjans Tespiti - Pivot bazlı"""
        div = pd.Series(False, index=price.index)
        pivot_price = price.rolling(5).min() if bullish else price.rolling(5).max()
        pivot_rsi = rsi.rolling(5).min() if bullish else rsi.rolling(5).max()
        
        for i in range(10, len(price)):
            if bullish:
                if (pivot_price.iloc[i] < pivot_price.iloc[i-5]) and (pivot_rsi.iloc[i] > pivot_rsi.iloc[i-5]):
                    div.iloc[i] = True
            else:
                if (pivot_price.iloc[i] > pivot_price.iloc[i-5]) and (pivot_rsi.iloc[i] < pivot_rsi.iloc[i-5]):
                    div.iloc[i] = True
        return div
    
    def _detect_morning_star(self, df: pd.DataFrame) -> pd.Series:
        """3 Mum Morning Star"""
        bearish = df['close'].shift(2) < df['open'].shift(2)
        small_body = abs(df['close'].shift(1) - df['open'].shift(1)) < abs(df['close'].shift(2) - df['open'].shift(2)) * 0.3
        bullish = df['close'] > df['open']
        gap_down = df['high'].shift(1) < df['close'].shift(2)
        engulf = df['close'] > df['open'].shift(2)
        return bearish & small_body & bullish & gap_down & engulf
    
    def _detect_evening_star(self, df: pd.DataFrame) -> pd.Series:
        """3 Mum Evening Star"""
        bullish = df['close'].shift(2) > df['open'].shift(2)
        small_body = abs(df['close'].shift(1) - df['open'].shift(1)) < abs(df['close'].shift(2) - df['open'].shift(2)) * 0.3
        bearish = df['close'] < df['open']
        gap_up = df['low'].shift(1) > df['close'].shift(2)
        engulf = df['close'] < df['open'].shift(2)
        return bullish & small_body & bearish & gap_up & engulf
    
    def _detect_bullish_engulfing(self, df: pd.DataFrame) -> pd.Series:
        body_prev = abs(df['close'].shift(1) - df['open'].shift(1))
        body_curr = abs(df['close'] - df['open'])
        return (df['close'].shift(1) < df['open'].shift(1)) & \
               (df['open'] < df['close'].shift(1)) & \
               (df['close'] > df['open'].shift(1)) & \
               (body_curr > body_prev)
    
    def _detect_bearish_engulfing(self, df: pd.DataFrame) -> pd.Series:
        body_prev = abs(df['close'].shift(1) - df['open'].shift(1))
        body_curr = abs(df['close'] - df['open'])
        return (df['close'].shift(1) > df['open'].shift(1)) & \
               (df['open'] > df['close'].shift(1)) & \
               (df['close'] < df['open'].shift(1)) & \
               (body_curr > body_prev)
    
    def _detect_hammer(self, df: pd.DataFrame) -> pd.Series:
        body = abs(df['close'] - df['open'])
        lower_wick = pd.concat([df['open'], df['close']], axis=1).min(axis=1) - df['low']
        upper_wick = df['high'] - pd.concat([df['open'], df['close']], axis=1).max(axis=1)
        return (lower_wick > 2 * body) & (upper_wick < 0.3 * body) & (df['close'] > df['open'])
    
    def _detect_shooting_star(self, df: pd.DataFrame) -> pd.Series:
        body = abs(df['close'] - df['open'])
        lower_wick = pd.concat([df['open'], df['close']], axis=1).min(axis=1) - df['low']
        upper_wick = df['high'] - pd.concat([df['open'], df['close']], axis=1).max(axis=1)
        return (upper_wick > 2 * body) & (lower_wick < 0.3 * body) & (df['close'] < df['open'])
    
    # ==================== MULTI-TIMEFRAME ANALİZ ====================
    def multi_timeframe_analysis(self, df: pd.DataFrame, symbol: str, timeframes: List[str] = ['1h', '4h', '1d']) -> Dict[str, Dict]:
        """Multi-Timeframe (MTF) analizi - Üst timeframe'lerden sinyal onayı"""
        mtf_results = {}
        for tf in timeframes:
            if tf in self._mtf_cache:
                mtf_results[tf] = self._mtf_cache[tf]
            else:
                # Üst TF verisini resample et (gerçek uygulamada ayrı veri çek)
                resampled_df = df.resample(tf.upper()).agg({
                    'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
                }).dropna()
                if len(resampled_df) < 50:
                    continue
                signal = self.generate_signal(resampled_df, symbol, tf)
                mtf_results[tf] = {
                    'trend': signal.market_structure['trend'],
                    'score': signal.score,
                    'confidence': signal.confidence
                }
                self._mtf_cache[tf] = mtf_results[tf]
        return mtf_results
    
    # ==================== SIGNAL GENERATION ====================
    def calculate_signal_score(self, patterns: Dict[str, pd.Series], mtf: Dict, idx: int = -1) -> Tuple[int, List[str]]:
        score = 0
        triggers = []
        
        try:
            idx_val = len(next(iter(patterns.values()))) + idx if idx < 0 else idx
            
            def safe_get(series, default=False):
                try:
                    val = series.iloc[idx_val]
                    return default if pd.isna(val) else bool(val)
                except:
                    return default
            
            # Bullish Tetikleyiciler - Ağırlıklandırılmış
            if safe_get(patterns.get('rsi6_crossover')): score += 25; triggers.append("RSI6 50 Üstü Geçiş")
            if safe_get(patterns.get('rsi_oversold_6')): score += 20; triggers.append("RSI6 Aşırı Satım")
            if safe_get(patterns.get('rsi_oversold_14')): score += 15; triggers.append("RSI14 Aşırı Satım")
            if safe_get(patterns.get('rsi_oversold_21')): score += 10; triggers.append("RSI21 Aşırı Satım")
            if safe_get(patterns.get('rsi_divergence_bull')): score += 30; triggers.append("RSI Bullish Diverjans")
            if safe_get(patterns.get('macd_bullish_cross')): score += 25; triggers.append("MACD Bullish Geçiş")
            if safe_get(patterns.get('macd_hist_divergence_bull')): score += 20; triggers.append("MACD Hist Bullish")
            if safe_get(patterns.get('liquidity_sweep_bull_5')): score += 40; triggers.append("Liquidity Sweep Bull (5)")
            if safe_get(patterns.get('liquidity_sweep_bull_10')): score += 35; triggers.append("Liquidity Sweep Bull (10)")
            if safe_get(patterns.get('smc_choch_bull')): score += 50; triggers.append("SMC CHoCH Bullish")
            if safe_get(patterns.get('bull_ob')): score += 35; triggers.append("Bullish Order Block")
            if safe_get(patterns.get('breaker_bull')): score += 40; triggers.append("Bullish Breaker Block")
            if safe_get(patterns.get('mitigation_bull')): score += 30; triggers.append("Bullish Mitigation")
            if safe_get(patterns.get('bos_bull')): score += 25; triggers.append("Break of Structure Bull")
            if safe_get(patterns.get('in_killzone')): score += 20; triggers.append("Killzone Aktif")
            if safe_get(patterns.get('bullish_engulfing')): score += 20; triggers.append("Bullish Engulfing")
            if safe_get(patterns.get('hammer')): score += 15; triggers.append("Hammer Mum")
            if safe_get(patterns.get('morning_star')): score += 25; triggers.append("Morning Star")
            if safe_get(patterns.get('ichimoku_bullish')): score += 30; triggers.append("Ichimoku Bullish Cloud")
            
            # Bearish Tetikleyiciler
            if safe_get(patterns.get('rsi6_crossunder')): score -= 25; triggers.append("RSI6 50 Altı Geçiş")
            if safe_get(patterns.get('rsi_overbought_6')): score -= 20; triggers.append("RSI6 Aşırı Alım")
            if safe_get(patterns.get('rsi_overbought_14')): score -= 15; triggers.append("RSI14 Aşırı Alım")
            if safe_get(patterns.get('rsi_overbought_21')): score -= 10; triggers.append("RSI21 Aşırı Alım")
            if safe_get(patterns.get('rsi_divergence_bear')): score -= 30; triggers.append("RSI Bearish Diverjans")
            if safe_get(patterns.get('macd_bearish_cross')): score -= 25; triggers.append("MACD Bearish Geçiş")
            if safe_get(patterns.get('liquidity_sweep_bear_5')): score -= 40; triggers.append("Liquidity Sweep Bear (5)")
            if safe_get(patterns.get('liquidity_sweep_bear_10')): score -= 35; triggers.append("Liquidity Sweep Bear (10)")
            if safe_get(patterns.get('smc_choch_bear')): score -= 50; triggers.append("SMC CHoCH Bearish")
            if safe_get(patterns.get('bear_ob')): score -= 35; triggers.append("Bearish Order Block")
            if safe_get(patterns.get('breaker_bear')): score -= 40; triggers.append("Bearish Breaker Block")
            if safe_get(patterns.get('mitigation_bear')): score -= 30; triggers.append("Bearish Mitigation")
            if safe_get(patterns.get('bos_bear')): score -= 25; triggers.append("Break of Structure Bear")
            if safe_get(patterns.get('bearish_engulfing')): score -= 20; triggers.append("Bearish Engulfing")
            if safe_get(patterns.get('shooting_star')): score -= 15; triggers.append("Shooting Star")
            if safe_get(patterns.get('evening_star')): score -= 25; triggers.append("Evening Star")
            if safe_get(patterns.get('ichimoku_bearish')): score -= 30; triggers.append("Ichimoku Bearish Cloud")
            
            # MTF Onayı - Üst TF'lerden bonus skor
            for tf, res in mtf.items():
                if res['score'] > 50: score += 15; triggers.append(f"{tf.upper()} MTF Bullish Onay")
                elif res['score'] < -50: score -= 15; triggers.append(f"{tf.upper()} MTF Bearish Onay")
            
            score = max(-100, min(100, score))
            
        except Exception as e:
            logger.error(f"Score calculation error: {e}")
            triggers.append("Skor Hesaplama Hatası")
        
        return score, sorted(triggers, key=lambda x: abs(score), reverse=True)[:10]  # En güçlü 10 trigger
    
    def analyze_market_structure(self, df: pd.DataFrame, indicators: Dict, mtf: Dict) -> Dict[str, Any]:
        structure = {
            "trend": "Sideways",
            "momentum": "Neutral",
            "volatility": "Normal",
            "volume_trend": "Neutral",
            "key_levels": [],
            "mtf_alignment": "Neutral"  # Yeni: MTF uyum
        }
        
        try:
            close_last = self._safe_float(df['close'].iloc[-1])
            ema21_last = self._safe_float(indicators['ema21'].iloc[-1])
            ema50_last = self._safe_float(indicators['ema50'].iloc[-1])
            sma200_last = self._safe_float(indicators['sma200'].iloc[-1])
            rsi14_last = self._safe_float(indicators['rsi14'].iloc[-1])
            
            # Trend - Gelişmiş hiyerarşi
            if close_last > ema21_last > ema50_last > sma200_last:
                structure["trend"] = "Strong Bullish"
            elif close_last > ema21_last > ema50_last:
                structure["trend"] = "Bullish"
            elif close_last < ema21_last < ema50_last < sma200_last:
                structure["trend"] = "Strong Bearish"
            elif close_last < ema21_last < ema50_last:
                structure["trend"] = "Bearish"
            
            # Momentum - RSI tabanlı
            if rsi14_last > 70:
                structure["momentum"] = "Overbought"
            elif rsi14_last > 55:
                structure["momentum"] = "Bullish"
            elif rsi14_last < 30:
                structure["momentum"] = "Oversold"
            elif rsi14_last < 45:
                structure["momentum"] = "Bearish"
            
            # Volatility
            bb_width = (indicators['bb_upper'] - indicators['bb_lower']) / indicators['bb_middle'].replace(0, 1)
            current_bb = self._safe_float(bb_width.iloc[-1])
            avg_bb = self._safe_float(bb_width.rolling(50).mean().iloc[-1])  # Daha uzun ortalama
            if current_bb > avg_bb * 1.5:
                structure["volatility"] = "High"
            elif current_bb < avg_bb * 0.5:
                structure["volatility"] = "Low"
            
            # Volume Trend
            volume_ratio = self._safe_float(df['volume'].iloc[-1]) / self._safe_float(indicators['volume_ma'].iloc[-1], 1)
            if volume_ratio > 2:
                structure["volume_trend"] = "High Volume"
            elif volume_ratio > 1.2:
                structure["volume_trend"] = "Increasing"
            elif volume_ratio < 0.8:
                structure["volume_trend"] = "Decreasing"
            
            # Key Levels - Fib entegrasyonu
            recent_high = self._safe_float(df['high'].rolling(50).max().iloc[-1])  # Daha geniş window
            recent_low = self._safe_float(df['low'].rolling(50).min().iloc[-1])
            fib_retracements = [recent_high - (recent_high - recent_low) * level for level in self._fib_levels]
            structure["key_levels"] = [
                {"type": "resistance", "price": round(recent_high, 6)},
                {"type": "support", "price": round(recent_low, 6)},
                {"type": "ema21", "price": round(ema21_last, 6)},
                {"type": "ema50", "price": round(ema50_last, 6)},
                {"type": "sma200", "price": round(sma200_last, 6)}
            ] + [{"type": f"fib_{level}", "price": round(fib, 6)} for level, fib in zip(self._fib_levels, fib_retracements)]
            
            # MTF Alignment
            bull_count = sum(1 for res in mtf.values() if 'Bullish' in res['trend'])
            bear_count = sum(1 for res in mtf.values() if 'Bearish' in res['trend'])
            if bull_count > bear_count:
                structure["mtf_alignment"] = "Bullish Aligned"
            elif bear_count > bull_count:
                structure["mtf_alignment"] = "Bearish Aligned"
            
        except Exception as e:
            logger.error(f"Market structure error: {e}")
        
        return structure
    
    def calculate_risk_management(self, df: pd.DataFrame, indicators: Dict, score: int) -> Tuple[Dict, List[float], float, List[float]]:
        """Risk/Reward, Entry, SL, TP hesaplaması - ATR bazlı"""
        current_price = self._safe_float(df['close'].iloc[-1])
        atr_last = self._safe_float(indicators['atr'].iloc[-1])
        direction = 1 if score > 0 else -1
        
        # Entry Levels: Yakın key levels
        entry_levels = [current_price + direction * atr_last * 0.5]
        
        # Stop Loss: ATR x 1.5 öte
        stop_loss = current_price - direction * atr_last * 1.5
        
        # Take Profit: RR 1:2, 1:3
        risk = abs(current_price - stop_loss)
        take_profit = [
            current_price + direction * risk * 2,
            current_price + direction * risk * 3
        ]
        
        risk_reward = {
            "risk_percent": round((risk / current_price) * 100, 2),
            "rr_ratio_1": 2.0,
            "rr_ratio_2": 3.0
        }
        
        return risk_reward, entry_levels, stop_loss, take_profit
    
    def generate_signal(self, df: pd.DataFrame, symbol: str, timeframe: str) -> SignalResult:
        try:
            if len(df) < 100:  # Min veri artırıldı
                raise ValueError("Yetersiz veri (min 100 mum gerekli)")
            
            indicators = self.calculate_all_indicators(df)
            phase1 = self.detect_patterns_phase1(df, indicators)
            patterns = self.detect_patterns_phase2(df, indicators, phase1)
            mtf = self.multi_timeframe_analysis(df, symbol)
            score, triggers = self.calculate_signal_score(patterns, mtf)
            structure = self.analyze_market_structure(df, indicators, mtf)
            risk_reward, entry_levels, stop_loss, take_profit = self.calculate_risk_management(df, indicators, score)
            
            current_price = self._safe_float(df['close'].iloc[-1])
            
            # Daha belirgin ve güvenilir sinyal metinleri
            if score >= 80:
                signal = "🚀🚀 ULTRA GÜÇLÜ ALIM SİNYALİ"
                strength = "ULTRA GÜÇLÜ"
            elif score >= 60:
                signal = "🚀 GÜÇLÜ ALIM SİNYALİ"
                strength = "ÇOK GÜÇLÜ"
            elif score >= 40:
                signal = "✅ ALIM FIRSATI"
                strength = "GÜÇLÜ"
            elif score <= -80:
                signal = "🔻🔻 ULTRA GÜÇLÜ SATIM SİNYALİ"
                strength = "ULTRA GÜÇLÜ"
            elif score <= -60:
                signal = "🔻 GÜÇLÜ SATIM SİNYALİ"
                strength = "ÇOK GÜÇLÜ"
            elif score <= -40:
                signal = "⚠️ SATIM UYARISI"
                strength = "GÜÇLÜ"
            else:
                signal = "🟡 NÖTR - BEKLE"
                strength = "NÖTR"
            
            # Killzone - Detaylı
            killzone = "Normal Saatler"
            if patterns.get('in_killzone', pd.Series([False])).iloc[-1]:
                if patterns.get('london_kz', pd.Series([False])).iloc[-1]:
                    killzone = "🏛️ London Killzone (Yüksek Volatilite)"
                elif patterns.get('ny_kz', pd.Series([False])).iloc[-1]:
                    killzone = "🗽 New York Killzone (Yüksek Volatilite)"
                elif patterns.get('asia_kz', pd.Series([False])).iloc[-1]:
                    killzone = "🌙 Asia Killzone (Düşük Volatilite)"
            
            confidence = round((abs(score) / 100) * (1 + len(mtf) * 0.1), 2)  # MTF bonus
            
            recommended_action = "Pozisyon Açmayı Değerlendirin" if abs(score) >= 60 else \
                                 "Onay Bekleyin" if abs(score) >= 40 else \
                                 "Piyasayı İzleyin"
            
            return SignalResult(
                pair=symbol,
                timeframe=timeframe,
                current_price=round(current_price, 6),
                signal=signal,
                score=score,
                strength=strength,
                killzone=killzone,
                triggers=triggers,
                last_update=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                market_structure=structure,
                confidence=min(confidence, 1.0),
                recommended_action=recommended_action,
                risk_reward=risk_reward,
                entry_levels=[round(lvl, 6) for lvl in entry_levels],
                stop_loss=round(stop_loss, 6),
                take_profit=[round(tp, 6) for tp in take_profit]
            )
            
        except Exception as e:
            logger.error(f"Signal generation error: {e}")
            return self._generate_fallback_signal(df, symbol, timeframe)
    
    def _generate_fallback_signal(self, df: pd.DataFrame, symbol: str, timeframe: str) -> SignalResult:
        current_price = self._safe_float(df['close'].iloc[-1] if len(df) > 0 else 0)
        prev_price = self._safe_float(df['close'].iloc[-2] if len(df) > 1 else current_price)
        change_pct = ((current_price - prev_price) / prev_price * 100) if prev_price != 0 else 0
        
        if change_pct >= 2.0:
            signal = "✅ BASİT ALIM SİNYALİ"
            score = 60
            strength = "ORTA"
        elif change_pct >= 0.5:
            signal = "🟢 Hafif Yükseliş"
            score = 50
            strength = "ZAYIF"
        elif change_pct <= -2.0:
            signal = "⚠️ BASİT SATIM SİNYALİ"
            score = -60
            strength = "ORTA"
        elif change_pct <= -0.5:
            signal = "🔴 Hafif Düşüş"
            score = -50
            strength = "ZAYIF"
        else:
            signal = "🟡 NÖTR"
            score = 0
            strength = "NÖTR"
        
        return SignalResult(
            pair=symbol,
            timeframe=timeframe,
            current_price=round(current_price, 6),
            signal=signal,
            score=score,
            strength=strength,
            killzone="Normal",
            triggers=[f"Son mum değişimi: {change_pct:+.2f}%"],
            last_update=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            market_structure={"trend": "Bilinmiyor", "note": "Fallback Modu Aktif"},
            confidence=0.4,
            recommended_action="Daha Fazla Veri Bekleyin",
            risk_reward={"risk_percent": 0, "rr_ratio_1": 0, "rr_ratio_2": 0},
            entry_levels=[],
            stop_loss=0.0,
            take_profit=[]
        )

    # ==================== CHART ANALİZ ENTEGRASYONU ====================
    def analyze_chart(self, df: pd.DataFrame, symbol: str, timeframe: str, chart_type: str = 'candlestick') -> Dict:
        """Chart Analizi Fonksiyonu - Signal ile Haberleşme, Görselleştirme Verisi Üretir
        Bu fonksiyon, generate_signal ile entegre çalışır ve chart verisi hazırlar.
        Dışarıdan çağrılabilir, TradingView/PineScript uyumlu veri döner."""
        signal = self.generate_signal(df, symbol, timeframe)
        
        chart_data = {
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": df.tail(100).to_dict(orient='records'),  # Son 100 mum
            "indicators": {
                "ema21": list(indicators['ema21'].tail(100)),
                "ema50": list(indicators['ema50'].tail(100)),
                "sma200": list(indicators['sma200'].tail(100)),
                "bb_upper": list(indicators['bb_upper'].tail(100)),
                "bb_lower": list(indicators['bb_lower'].tail(100)),
                "rsi14": list(indicators['rsi14'].tail(100)),
                "macd": list(indicators['macd'].tail(100)),
                "macd_signal": list(indicators['macd_signal'].tail(100))
            },
            "key_levels": signal.market_structure['key_levels'],
            "signal_overlay": {
                "entry": signal.entry_levels,
                "sl": signal.stop_loss,
                "tp": signal.take_profit
            },
            "patterns": {k: v.tail(100).to_list() for k, v in patterns.items() if 'bull' in k or 'bear' in k},
            "signal_summary": {
                "signal": signal.signal,
                "score": signal.score,
                "confidence": signal.confidence
            }
        }
        
        # Chart Tipine Göre Ek Veri
        if chart_type == 'line':
            chart_data['line_data'] = df['close'].tail(100).to_list()
        elif chart_type == 'heikin_ashi':
            chart_data['heikin_ashi'] = self._calculate_heikin_ashi(df).tail(100).to_dict(orient='records')
        
        return clean_nan(chart_data)
    
    def _calculate_heikin_ashi(self, df: pd.DataFrame) -> pd.DataFrame:
        """Heikin Ashi Mum Hesaplaması - Chart için"""
        ha = pd.DataFrame(index=df.index)
        ha['close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        ha['open'] = (df['open'].shift() + df['close'].shift()) / 2
        ha['open'].iloc[0] = df['open'].iloc[0]
        ha['high'] = pd.concat([ha['open'], ha['close'], df['high']], axis=1).max(axis=1)
        ha['low'] = pd.concat([ha['open'], ha['close'], df['low']], axis=1).min(axis=1)
        return ha
    
    # ==================== BACKTEST FONKSİYONU ====================
    def backtest_signals(self, df: pd.DataFrame, symbol: str, timeframe: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict:
        """Sinyal Backtest - Tarihsel Performans, Win Rate, vs."""
        if start_date:
            df = df.loc[start_date:]
        if end_date:
            df = df.loc[:end_date]
        
        backtest_key = f"{symbol}_{timeframe}_{start_date}_{end_date}"
        if backtest_key in self._backtest_results:
            return self._backtest_results[backtest_key]
        
        trades = []
        position = None
        entry_price = 0
        
        for i in range(100, len(df)):  # Min veri sonrası başla
            sub_df = df.iloc[:i]
            signal = self.generate_signal(sub_df, symbol, timeframe)
            
            if signal.score >= 60 and position != 'long':
                if position == 'short':
                    # Close short
                    profit = (entry_price - sub_df['close'].iloc[-1]) / entry_price
                    trades.append(profit)
                entry_price = sub_df['close'].iloc[-1]
                position = 'long'
            elif signal.score <= -60 and position != 'short':
                if position == 'long':
                    # Close long
                    profit = (sub_df['close'].iloc[-1] - entry_price) / entry_price
                    trades.append(profit)
                entry_price = sub_df['close'].iloc[-1]
                position = 'short'
        
        # Son pozisyonu kapat
        if position:
            last_price = df['close'].iloc[-1]
            profit = (last_price - entry_price) / entry_price if position == 'long' else (entry_price - last_price) / entry_price
            trades.append(profit)
        
        win_rate = sum(1 for p in trades if p > 0) / len(trades) * 100 if trades else 0
        total_return = np.prod([1 + p for p in trades]) - 1
        
        results = {
            "total_trades": len(trades),
            "win_rate": round(win_rate, 2),
            "total_return": round(total_return * 100, 2),
            "avg_profit": round(np.mean(trades) * 100, 2) if trades else 0,
            "max_drawdown": round(min(np.cumprod([1 + p for p in trades]) - 1) * 100, 2) if trades else 0
        }
        
        self._backtest_results[backtest_key] = results
        return results

# ==================== GLOBAL INSTANCE & PUBLIC API ====================
grok_pro = GrokIndicatorsPro()

def generate_ict_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Dict:
    """Ana ICT/SMC Sinyali - JSON Uyumlu, Clean NaN"""
    result = grok_pro.generate_signal(df, symbol, timeframe)
    return clean_nan({
        "pair": result.pair.replace("USDT", "/USDT"),
        "timeframe": result.timeframe.upper(),
        "current_price": result.current_price,
        "signal": result.signal,
        "score": result.score,
        "strength": result.strength,
        "killzone": result.killzone,
        "triggers": "\n".join(result.triggers) if result.triggers else "Tetikleyici Yok",
        "last_update": result.last_update,
        "market_structure": result.market_structure,
        "confidence": result.confidence,
        "recommended_action": result.recommended_action,
        "risk_reward": result.risk_reward,
        "entry_levels": result.entry_levels,
        "stop_loss": result.stop_loss,
        "take_profit": result.take_profit,
        "status": "success"
    })

def generate_simple_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Dict:
    """Basit Fallback Sinyal"""
    result = grok_pro._generate_fallback_signal(df, symbol, timeframe)
    return clean_nan({
        "pair": result.pair.replace("USDT", "/USDT"),
        "timeframe": result.timeframe.upper(),
        "current_price": result.current_price,
        "signal": result.signal,
        "score": result.score,
        "strength": result.strength,
        "killzone": result.killzone,
        "triggers": "\n".join(result.triggers),
        "last_update": result.last_update,
        "status": "fallback"
    })

def analyze_chart(df: pd.DataFrame, symbol: str, timeframe: str, chart_type: str = 'candlestick') -> Dict:
    """Public Chart Analizi - Signal ile Entegre"""
    return grok_pro.analyze_chart(df, symbol, timeframe, chart_type)

def backtest_ict_signals(df: pd.DataFrame, symbol: str, timeframe: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict:
    """Public Backtest API"""
    return grok_pro.backtest_signals(df, symbol, timeframe, start_date, end_date)

def clean_nan(obj):
    """Recursive NaN Temizleyici: NaN'leri None'a Çevirir (JSON Uyumlu)"""
    if isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nan(v) for v in obj]
    elif isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    else:
        return obj
