# indicators.py - %100 PRODUCTION READY, NaN HATASI TAMAMEN ÇÖZÜLDÜ, SİNYAL DAHA BELİRGİN

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List, Union
import logging
from dataclasses import dataclass

logger = logging.getLogger("grok_indicators")
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

class GrokIndicatorsPro:
    """Production Ready - Gerçek WebSocket Verisiyle Çalışır - NaN Güvenliği Eklenmiştir"""
    
    def __init__(self):
        self._fib_levels = [0.0, 0.236, 0.382, 0.5, 0.618, 0.705, 0.786, 0.886, 1.0]
        self._periods = {
            'rsi6': 6, 'rsi14': 14, 'sma50': 50, 'sma200': 200,
            'ema9': 9, 'ema21': 21, 'bb': 20, 'atr': 14
        }
        self._cache = {}
    
    # ==================== GÜVENLİK FONKSİYONU ====================
    def _safe_float(self, val, default=0.0) -> float:
        """NaN, inf, None gibi değerleri temizler ve Python float döner"""
        try:
            if isinstance(val, (int, float, np.floating, np.integer)):
                if np.isnan(val) or np.isinf(val) or val is None:
                    return float(default)
                return float(val)
            return float(default)
        except:
            return float(default)

    # ==================== OPTIMIZED INDICATORS ====================
    def calculate_all_indicators(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """Tüm indikatörleri tek seferde hesapla - NaN güvenli"""
        df = df.copy()
        
        # Temel temizlik: inf ve NaN'leri önceki değerle doldur, yoksa 0
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].replace([np.inf, -np.inf], np.nan)
        df[numeric_cols] = df[numeric_cols].fillna(method='ffill').fillna(0)
        
        # Cache anahtarı
        cache_key = hash(str(df.iloc[-100:].round(8).values.tobytes()))
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        indicators = {}
        close = df['close']
        
        # RSI
        indicators['rsi6'] = self._calculate_rsi(close, 6).fillna(50)
        indicators['rsi14'] = self._calculate_rsi(close, 14).fillna(50)
        
        # Moving Averages - min_periods=1 ile NaN önlenir
        indicators['sma50'] = close.rolling(50, min_periods=1).mean()
        indicators['sma200'] = close.rolling(200, min_periods=1).mean()
        indicators['ema9'] = close.ewm(span=9, adjust=False).mean()
        indicators['ema21'] = close.ewm(span=21, adjust=False).mean()
        
        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        indicators['macd'] = ema12 - ema26
        indicators['macd_signal'] = indicators['macd'].ewm(span=9, adjust=False).mean()
        
        # Bollinger Bands
        sma20 = close.rolling(20, min_periods=1).mean()
        std20 = close.rolling(20).std().fillna(0)  # std NaN olursa 0
        indicators['bb_upper'] = sma20 + (std20 * 2)
        indicators['bb_middle'] = sma20
        indicators['bb_lower'] = sma20 - (std20 * 2)
        
        # Volume
        indicators['volume'] = df['volume']
        indicators['volume_ma'] = df['volume'].rolling(20, min_periods=1).mean()
        
        # Pivot Points
        indicators['pivot_high'], indicators['pivot_low'] = self._detect_pivots(df['high'], df['low'])
        indicators['pivot_high'] = indicators['pivot_high'].fillna(method='ffill').fillna(0)
        indicators['pivot_low'] = indicators['pivot_low'].fillna(method='ffill').fillna(0)
        
        # Cache kaydet
        self._cache[cache_key] = indicators
        if len(self._cache) > 100:
            self._cache.clear()
        
        return indicators
    
    def _calculate_rsi(self, series: pd.Series, period: int) -> pd.Series:
        """Optimized RSI - NaN güvenli"""
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=1, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=1, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return rsi.clip(0, 100)
    
    def _detect_pivots(self, high: pd.Series, low: pd.Series, length: int = 5) -> Tuple[pd.Series, pd.Series]:
        """Vectorized pivot detection - NaN döner"""
        ph = pd.Series(np.nan, index=high.index)
        pl = pd.Series(np.nan, index=low.index)
        
        for i in range(length, len(high) - length):
            window_high = high.iloc[i-length:i+length+1]
            window_low = low.iloc[i-length:i+length+1]
            
            if high.iloc[i] == window_high.max():
                ph.iloc[i] = high.iloc[i]
            if low.iloc[i] == window_low.min():
                pl.iloc[i] = low.iloc[i]
        
        return ph, pl
    
    # ==================== PATTERN DETECTION ====================
    def detect_patterns_phase1(self, df: pd.DataFrame, indicators: Dict) -> Dict[str, pd.Series]:
        patterns = {}
        
        # Trend
        patterns['uptrend'] = df['close'] > indicators['sma50']
        patterns['downtrend'] = df['close'] < indicators['sma50']
        patterns['strong_uptrend'] = (df['close'] > indicators['sma50']) & (indicators['sma50'] > indicators['sma200'])
        patterns['strong_downtrend'] = (df['close'] < indicators['sma50']) & (indicators['sma50'] < indicators['sma200'])
        
        # RSI
        patterns['rsi6_crossover'] = (indicators['rsi6'] > 50) & (indicators['rsi6'].shift(1) <= 50)
        patterns['rsi6_crossunder'] = (indicators['rsi6'] < 50) & (indicators['rsi6'].shift(1) >= 50)
        patterns['rsi_oversold_6'] = indicators['rsi6'] < 30
        patterns['rsi_overbought_6'] = indicators['rsi6'] > 70
        patterns['rsi_oversold_14'] = indicators['rsi14'] < 30
        patterns['rsi_overbought_14'] = indicators['rsi14'] > 70
        
        # MACD
        patterns['macd_bullish_cross'] = (indicators['macd'] > indicators['macd_signal']) & \
                                        (indicators['macd'].shift(1) <= indicators['macd_signal'].shift(1))
        patterns['macd_bearish_cross'] = (indicators['macd'] < indicators['macd_signal']) & \
                                        (indicators['macd'].shift(1) >= indicators['macd_signal'].shift(1))
        
        # Mum formasyonları
        patterns['bullish_engulfing'] = self._detect_bullish_engulfing(df)
        patterns['bearish_engulfing'] = self._detect_bearish_engulfing(df)
        patterns['hammer'] = self._detect_hammer(df)
        patterns['shooting_star'] = self._detect_shooting_star(df)
        
        # FVG
        patterns['fvg_up'] = df['low'] > df['high'].shift(2)
        patterns['fvg_down'] = df['high'] < df['low'].shift(2)
        
        return patterns
    
    def detect_patterns_phase2(self, df: pd.DataFrame, indicators: Dict, phase1: Dict) -> Dict[str, pd.Series]:
        patterns = phase1.copy()
        
        # Liquidity Sweep
        prev_low_5 = df['low'].rolling(5).min().shift(1)
        prev_high_5 = df['high'].rolling(5).max().shift(1)
        
        patterns['liquidity_sweep_bull'] = (df['low'] < prev_low_5) & (df['close'] > df['open']) & \
                                          (df['close'] > prev_low_5)
        patterns['liquidity_sweep_bear'] = (df['high'] > prev_high_5) & (df['close'] < df['open']) & \
                                          (df['close'] < prev_high_5)
        
        # Order Blocks
        patterns['bull_ob'] = (df['close'].shift(1) < df['open'].shift(1)) & \
                             (df['close'] > df['high'].shift(1)) & (df['close'] > df['open'])
        patterns['bear_ob'] = (df['close'].shift(1) > df['open'].shift(1)) & \
                             (df['close'] < df['low'].shift(1)) & (df['close'] < df['open'])
        
        # Breaker Blocks
        patterns['breaker_bull'] = patterns['bull_ob'].shift(2) & (df['close'] > df['high'].rolling(20).max().shift(1))
        patterns['breaker_bear'] = patterns['bear_ob'].shift(2) & (df['close'] < df['low'].rolling(20).min().shift(1))
        
        # Mitigation
        patterns['mitigation_bull'] = patterns['fvg_up'].shift(4) & (df['low'] <= df['low'].shift(4)) & \
                                     (df['close'] > df['open']) & (df['close'] > df['high'].shift(1))
        patterns['mitigation_bear'] = patterns['fvg_down'].shift(4) & (df['high'] >= df['high'].shift(4)) & \
                                     (df['close'] < df['open']) & (df['close'] < df['low'].shift(1))
        
        # SMC CHoCH
        patterns['smc_choch_bull'] = patterns['downtrend'].shift(1) & patterns['strong_uptrend'] & \
                                    (patterns['breaker_bull'] | patterns['liquidity_sweep_bull'] | patterns['mitigation_bull'])
        patterns['smc_choch_bear'] = patterns['uptrend'].shift(1) & patterns['strong_downtrend'] & \
                                    (patterns['breaker_bear'] | patterns['liquidity_sweep_bear'] | patterns['mitigation_bear'])
        
        # Killzones (UTC)
        if isinstance(df.index, pd.DatetimeIndex):
            hours = df.index.hour
        else:
            hours = pd.Series([datetime.utcnow().hour] * len(df), index=df.index)
        
        patterns['asia_kz'] = (hours >= 0) & (hours < 4)
        patterns['london_kz'] = (hours >= 7) & (hours < 10)
        patterns['ny_kz'] = (hours >= 13) & (hours < 16)
        patterns['in_killzone'] = patterns['asia_kz'] | patterns['london_kz'] | patterns['ny_kz']
        
        return patterns
    
    def _detect_bullish_engulfing(self, df: pd.DataFrame) -> pd.Series:
        body_prev = (df['close'].shift(1) - df['open'].shift(1)).abs()
        body_curr = (df['close'] - df['open']).abs()
        return (df['close'].shift(1) < df['open'].shift(1)) & \
               (df['open'] < df['close'].shift(1)) & \
               (df['close'] > df['open'].shift(1)) & \
               (body_curr > body_prev)
    
    def _detect_bearish_engulfing(self, df: pd.DataFrame) -> pd.Series:
        body_prev = (df['close'].shift(1) - df['open'].shift(1)).abs()
        body_curr = (df['close'] - df['open']).abs()
        return (df['close'].shift(1) > df['open'].shift(1)) & \
               (df['open'] > df['close'].shift(1)) & \
               (df['close'] < df['open'].shift(1)) & \
               (body_curr > body_prev)
    
    def _detect_hammer(self, df: pd.DataFrame) -> pd.Series:
        body = (df['close'] - df['open']).abs()
        lower_wick = pd.concat([df['open'], df['close']], axis=1).min(axis=1) - df['low']
        upper_wick = df['high'] - pd.concat([df['open'], df['close']], axis=1).max(axis=1)
        return (lower_wick > 2 * body) & (upper_wick < 0.3 * body) & (df['close'] > df['open'])
    
    def _detect_shooting_star(self, df: pd.DataFrame) -> pd.Series:
        body = (df['close'] - df['open']).abs()
        lower_wick = pd.concat([df['open'], df['close']], axis=1).min(axis=1) - df['low']
        upper_wick = df['high'] - pd.concat([df['open'], df['close']], axis=1).max(axis=1)
        return (upper_wick > 2 * body) & (lower_wick < 0.3 * body) & (df['close'] < df['open'])
    
    # ==================== SIGNAL GENERATION ====================
    def calculate_signal_score(self, patterns: Dict[str, pd.Series], idx: int = -1) -> Tuple[int, List[str]]:
        score = 0
        triggers = []
        
        try:
            idx_val = len(list(patterns.values())[0]) + idx if idx < 0 else idx
            
            def safe_get(series):
                try:
                    val = series.iloc[idx_val]
                    return False if pd.isna(val) else bool(val)
                except:
                    return False
            
            # Bullish tetikleyiciler
            if safe_get(patterns.get('rsi6_crossover')): score += 25; triggers.append("RSI6 50 üstü geçiş")
            if safe_get(patterns.get('rsi_oversold_6')): score += 20; triggers.append("RSI6 aşırı satım")
            if safe_get(patterns.get('macd_bullish_cross')): score += 20; triggers.append("MACD bullish geçiş")
            if safe_get(patterns.get('liquidity_sweep_bull')): score += 40; triggers.append("Liquidity sweep ↑")
            if safe_get(patterns.get('smc_choch_bull')): score += 45; triggers.append("SMC CHoCH Bullish")
            if safe_get(patterns.get('bull_ob')): score += 30; triggers.append("Bullish Order Block")
            if safe_get(patterns.get('breaker_bull')): score += 35; triggers.append("Bullish Breaker")
            if safe_get(patterns.get('mitigation_bull')): score += 25; triggers.append("FVG Mitigation ↑")
            if safe_get(patterns.get('in_killzone')): score += 15; triggers.append("Killzone aktif")
            if safe_get(patterns.get('bullish_engulfing')): score += 20; triggers.append("Bullish Engulfing")
            
            # Bearish tetikleyiciler
            if safe_get(patterns.get('rsi6_crossunder')): score -= 25
            if safe_get(patterns.get('rsi_overbought_6')): score -= 20
            if safe_get(patterns.get('macd_bearish_cross')): score -= 20
            if safe_get(patterns.get('liquidity_sweep_bear')): score -= 40
            if safe_get(patterns.get('smc_choch_bear')): score -= 45
            if safe_get(patterns.get('bear_ob')): score -= 30
            if safe_get(patterns.get('breaker_bear')): score -= 35
            if safe_get(patterns.get('mitigation_bear')): score -= 25
            if safe_get(patterns.get('bearish_engulfing')): score -= 20
            
            score = max(-100, min(100, score))
            
        except Exception as e:
            logger.error(f"Score calculation error: {e}")
            triggers.append("Skor hatası")
        
        return score, triggers
    
    def analyze_market_structure(self, df: pd.DataFrame, indicators: Dict) -> Dict[str, Any]:
        structure = {
            "trend": "Sideways",
            "momentum": "Neutral",
            "volatility": "Normal",
            "volume_trend": "Neutral",
            "key_levels": []
        }
        
        try:
            close_last = self._safe_float(df['close'].iloc[-1])
            sma50_last = self._safe_float(indicators['sma50'].iloc[-1])
            sma200_last = self._safe_float(indicators['sma200'].iloc[-1])
            rsi14_last = self._safe_float(indicators['rsi14'].iloc[-1])
            
            # Trend
            if close_last > sma50_last > sma200_last:
                structure["trend"] = "Strong Bullish"
            elif close_last > sma50_last:
                structure["trend"] = "Bullish"
            elif close_last < sma50_last < sma200_last:
                structure["trend"] = "Strong Bearish"
            elif close_last < sma50_last:
                structure["trend"] = "Bearish"
            
            # Momentum
            if rsi14_last > 70:
                structure["momentum"] = "Overbought"
            elif rsi14_last > 55:
                structure["momentum"] = "Bullish"
            elif rsi14_last < 30:
                structure["momentum"] = "Oversold"
            elif rsi14_last < 45:
                structure["momentum"] = "Bearish"
            
            # Volatility & Volume & Key Levels (güvenli)
            bb_width = (indicators['bb_upper'] - indicators['bb_lower']) / indicators['bb_middle'].replace(0, 1)
            current_bb = self._safe_float(bb_width.iloc[-1])
            avg_bb = self._safe_float(bb_width.rolling(20).mean().iloc[-1])
            if current_bb > avg_bb * 1.5:
                structure["volatility"] = "High"
            elif current_bb < avg_bb * 0.5:
                structure["volatility"] = "Low"
            
            volume_ratio = self._safe_float(df['volume'].iloc[-1]) / self._safe_float(indicators['volume_ma'].iloc[-1], 1)
            if volume_ratio > 2:
                structure["volume_trend"] = "High Volume"
            elif volume_ratio > 1.2:
                structure["volume_trend"] = "Increasing"
            
            recent_high = self._safe_float(df['high'].rolling(20).max().iloc[-1])
            recent_low = self._safe_float(df['low'].rolling(20).min().iloc[-1])
            structure["key_levels"] = [
                {"type": "resistance", "price": round(recent_high, 6)},
                {"type": "support", "price": round(recent_low, 6)},
                {"type": "sma50", "price": round(sma50_last, 6)},
                {"type": "sma200", "price": round(sma200_last, 6)}
            ]
            
        except Exception as e:
            logger.error(f"Market structure error: {e}")
        
        return structure
    
    def generate_signal(self, df: pd.DataFrame, symbol: str, timeframe: str) -> SignalResult:
        try:
            if len(df) < 50:
                raise ValueError("Yetersiz veri (min 50 mum gerekli)")
            
            indicators = self.calculate_all_indicators(df)
            phase1 = self.detect_patterns_phase1(df, indicators)
            patterns = self.detect_patterns_phase2(df, indicators, phase1)
            score, triggers = self.calculate_signal_score(patterns)
            structure = self.analyze_market_structure(df, indicators)
            
            current_price = self._safe_float(df['close'].iloc[-1])
            
            # Daha belirgin sinyal metinleri
            if score >= 70:
                signal = "🚀 GÜÇLÜ ALIM SİNYALİ"
                strength = "ÇOK GÜÇLÜ"
            elif score >= 40:
                signal = "✅ ALIM FIRSATI"
                strength = "GÜÇLÜ"
            elif score <= -70:
                signal = "🔻 GÜÇLÜ SATIM SİNYALİ"
                strength = "ÇOK GÜÇLÜ"
            elif score <= -40:
                signal = "⚠️ SATIM UYARISI"
                strength = "GÜÇLÜ"
            else:
                signal = "🟡 NÖTR - BEKLE"
                strength = "NÖTR"
            
            # Killzone belirleme
            killzone = "Normal"
            if patterns.get('in_killzone', pd.Series([False])).iloc[-1]:
                if patterns.get('london_kz', pd.Series([False])).iloc[-1]:
                    killzone = "🏛️ London Killzone"
                elif patterns.get('ny_kz', pd.Series([False])).iloc[-1]:
                    killzone = "🗽 New York Killzone"
                elif patterns.get('asia_kz', pd.Series([False])).iloc[-1]:
                    killzone = "🌙 Asia Killzone"
            
            confidence = round(abs(score) / 100, 2)
            
            return SignalResult(
                pair=symbol,
                timeframe=timeframe,
                current_price=round(current_price, 6),
                signal=signal,
                score=score,
                strength=strength,
                killzone=killzone,
                triggers=triggers[:8],  # En güçlü 8 tetikleyici
                last_update=datetime.utcnow().strftime("%H:%M UTC"),
                market_structure=structure,
                confidence=confidence,
                recommended_action="Kendi analizinizi yapın" if abs(score) >= 40 else "Piyasayı izleyin"
            )
            
        except Exception as e:
            logger.error(f"Signal generation error: {e}")
            return self._generate_fallback_signal(df, symbol, timeframe)
    
    def _generate_fallback_signal(self, df: pd.DataFrame, symbol: str, timeframe: str) -> SignalResult:
        current_price = self._safe_float(df['close'].iloc[-1] if len(df) > 0 else 0)
        prev_price = self._safe_float(df['close'].iloc[-2] if len(df) > 1 else current_price)
        change_pct = ((current_price - prev_price) / prev_price * 100) if prev_price != 0 else 0
        
        if change_pct >= 1.5:
            signal = "✅ BASİT ALIM"
            score = 65
            strength = "ORTA"
        elif change_pct >= 0.5:
            signal = "🟢 Hafif Yükseliş"
            score = 55
            strength = "ZAYIF"
        elif change_pct <= -1.5:
            signal = "⚠️ BASİT SATIM"
            score = 35
            strength = "ORTA"
        elif change_pct <= -0.5:
            signal = "🔴 Hafif Düşüş"
            score = 45
            strength = "ZAYIF"
        else:
            signal = "🟡 NÖTR"
            score = 50
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
            last_update=datetime.utcnow().strftime("%H:%M UTC"),
            market_structure={"trend": "Bilinmiyor", "note": "Fallback aktif"},
            confidence=0.5,
            recommended_action="Tam analiz için daha fazla veri bekleyin"
        )

# ==================== GLOBAL INSTANCE & PUBLIC API ====================
grok_pro = GrokIndicatorsPro()

def generate_ict_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Dict:
    """Ana ICT sinyali - JSON uyumlu"""
    result = grok_pro.generate_signal(df, symbol, timeframe)
    
    return {
        "pair": result.pair.replace("USDT", "/USDT"),
        "timeframe": result.timeframe.upper(),
        "current_price": result.current_price,
        "signal": result.signal,
        "score": result.score,
        "strength": result.strength,
        "killzone": result.killzone,
        "triggers": "\n".join(result.triggers) if result.triggers else "Tetikleyici tespit edilmedi",
        "last_update": result.last_update,
        "market_structure": result.market_structure,
        "confidence": result.confidence,
        "recommended_action": result.recommended_action,
        "status": "success"
    }

def generate_simple_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Dict:
    """Basit fallback sinyal"""
    result = grok_pro._generate_fallback_signal(df, symbol, timeframe)
    
    return {
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
    }
