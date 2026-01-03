# indicators.py - PRODUCTION READY DÜZELTMİŞ VERSİYON
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
    """Production Ready - Optimized Version"""
    
    def __init__(self):
        self._fib_levels = [0.0, 0.236, 0.382, 0.5, 0.618, 0.705, 0.786, 0.886, 1.0]
        self._periods = {
            'rsi6': 6, 'rsi14': 14, 'sma50': 50, 'sma200': 200,
            'ema9': 9, 'ema21': 21, 'bb': 20, 'atr': 14
        }
        self._cache = {}
    
    # ==================== OPTIMIZED INDICATORS ====================
    
    def calculate_all_indicators(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """Tüm indikatörleri tek seferde hesapla (optimized)"""
        cache_key = hash(str(df.iloc[-100:].values.tobytes()))
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        indicators = {}
        
        # 1. Temel indikatörler
        indicators['rsi6'] = self._calculate_rsi(df['close'], 6)
        indicators['rsi14'] = self._calculate_rsi(df['close'], 14)
        indicators['sma50'] = df['close'].rolling(50).mean()
        indicators['sma200'] = df['close'].rolling(200).mean()
        indicators['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        indicators['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        
        # 2. MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        indicators['macd'] = ema12 - ema26
        indicators['macd_signal'] = indicators['macd'].ewm(span=9, adjust=False).mean()
        
        # 3. Bollinger Bands
        sma20 = df['close'].rolling(20).mean()
        std20 = df['close'].rolling(20).std()
        indicators['bb_upper'] = sma20 + (std20 * 2)
        indicators['bb_middle'] = sma20
        indicators['bb_lower'] = sma20 - (std20 * 2)
        
        # 4. Volume
        indicators['volume'] = df['volume']
        indicators['volume_ma'] = df['volume'].rolling(20).mean()
        
        # 5. Pivot Points
        indicators['pivot_high'], indicators['pivot_low'] = self._detect_pivots(df['high'], df['low'])
        
        # Cache'e kaydet
        self._cache[cache_key] = indicators
        if len(self._cache) > 100:  # Cache limit
            self._cache.pop(next(iter(self._cache)))
        
        return indicators
    
    def _calculate_rsi(self, series: pd.Series, period: int) -> pd.Series:
        """Optimized RSI"""
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        return 100 - (100 / (1 + rs))
    
    def _detect_pivots(self, high: pd.Series, low: pd.Series, length: int = 5) -> Tuple[pd.Series, pd.Series]:
        """Vectorized pivot detection"""
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
        """Phase 1: Basic patterns (no dependencies)"""
        patterns = {}
        
        # 1. Temel patternler
        patterns['uptrend'] = df['close'] > indicators['sma50']
        patterns['downtrend'] = df['close'] < indicators['sma50']
        patterns['strong_uptrend'] = (df['close'] > indicators['sma50']) & (indicators['sma50'] > indicators['sma200'])
        patterns['strong_downtrend'] = (df['close'] < indicators['sma50']) & (indicators['sma50'] < indicators['sma200'])
        
        # 2. RSI patterns
        patterns['rsi6_crossover'] = (indicators['rsi6'] > 50) & (indicators['rsi6'].shift(1) <= 50)
        patterns['rsi6_crossunder'] = (indicators['rsi6'] < 50) & (indicators['rsi6'].shift(1) >= 50)
        patterns['rsi_oversold_6'] = indicators['rsi6'] < 30
        patterns['rsi_overbought_6'] = indicators['rsi6'] > 70
        patterns['rsi_oversold_14'] = indicators['rsi14'] < 30
        patterns['rsi_overbought_14'] = indicators['rsi14'] > 70
        
        # 3. MACD patterns
        patterns['macd_bullish_cross'] = (indicators['macd'] > indicators['macd_signal']) & \
                                        (indicators['macd'].shift(1) <= indicators['macd_signal'].shift(1))
        patterns['macd_bearish_cross'] = (indicators['macd'] < indicators['macd_signal']) & \
                                        (indicators['macd'].shift(1) >= indicators['macd_signal'].shift(1))
        
        # 4. Candle patterns
        patterns['bullish_engulfing'] = self._detect_bullish_engulfing(df)
        patterns['bearish_engulfing'] = self._detect_bearish_engulfing(df)
        patterns['hammer'] = self._detect_hammer(df)
        patterns['shooting_star'] = self._detect_shooting_star(df)
        
        # 5. FVG (Fair Value Gap)
        patterns['fvg_up'] = df['low'] > df['high'].shift(2)
        patterns['fvg_down'] = df['high'] < df['low'].shift(2)
        
        return patterns
    
    def detect_patterns_phase2(self, df: pd.DataFrame, indicators: Dict, phase1: Dict) -> Dict[str, pd.Series]:
        """Phase 2: Advanced patterns (depends on phase1)"""
        patterns = phase1.copy()
        
        # 1. Liquidity Sweep (FVG'ye bağlı)
        prev_low_5 = df['low'].rolling(5).min().shift(1)
        prev_high_5 = df['high'].rolling(5).max().shift(1)
        
        patterns['liquidity_sweep_bull'] = (df['low'] < prev_low_5) & (df['close'] > df['open']) & \
                                          (df['close'] > prev_low_5)
        patterns['liquidity_sweep_bear'] = (df['high'] > prev_high_5) & (df['close'] < df['open']) & \
                                          (df['close'] < prev_high_5)
        
        # 2. Order Blocks
        patterns['bull_ob'] = (df['close'].shift(1) < df['open'].shift(1)) & \
                             (df['close'] > df['high'].shift(1)) & (df['close'] > df['open'])
        patterns['bear_ob'] = (df['close'].shift(1) > df['open'].shift(1)) & \
                             (df['close'] < df['low'].shift(1)) & (df['close'] < df['open'])
        
        # 3. Breaker Blocks (FVG ve OB'ye bağlı)
        patterns['breaker_bull'] = patterns['bull_ob'].shift(2) & (df['close'] > df['high'].rolling(20).max().shift(1))
        patterns['breaker_bear'] = patterns['bear_ob'].shift(2) & (df['close'] < df['low'].rolling(20).min().shift(1))
        
        # 4. Mitigation (FVG'ye bağlı)
        patterns['mitigation_bull'] = patterns['fvg_up'].shift(4) & (df['low'] <= df['low'].shift(4)) & \
                                     (df['close'] > df['open']) & (df['close'] > df['high'].shift(1))
        patterns['mitigation_bear'] = patterns['fvg_down'].shift(4) & (df['high'] >= df['high'].shift(4)) & \
                                     (df['close'] < df['open']) & (df['close'] < df['low'].shift(1))
        
        # 5. SMC CHoCH (trendlere bağlı)
        patterns['smc_choch_bull'] = patterns['downtrend'].shift(1) & patterns['strong_uptrend'] & \
                                    (patterns['breaker_bull'] | patterns['liquidity_sweep_bull'] | patterns['mitigation_bull'])
        patterns['smc_choch_bear'] = patterns['uptrend'].shift(1) & patterns['strong_downtrend'] & \
                                    (patterns['breaker_bear'] | patterns['liquidity_sweep_bear'] | patterns['mitigation_bear'])
        
        # 6. Killzones
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
        """Calculate signal score with triggers"""
        score = 0
        triggers = []
        
        try:
            idx_val = idx if idx >= 0 else len(list(patterns.values())[0]) + idx
            
            # RSI Patterns
            if patterns.get('rsi6_crossover', pd.Series([False])).iloc[idx_val]:
                score += 25
                triggers.append("RSI6 > 50 crossover")
            
            if patterns.get('rsi6_crossunder', pd.Series([False])).iloc[idx_val]:
                score -= 25
                triggers.append("RSI6 < 50 crossunder")
            
            if patterns.get('rsi_oversold_6', pd.Series([False])).iloc[idx_val]:
                score += 20
                triggers.append("RSI6 oversold (<30)")
            
            if patterns.get('rsi_overbought_6', pd.Series([False])).iloc[idx_val]:
                score -= 20
                triggers.append("RSI6 overbought (>70)")
            
            # MACD Patterns
            if patterns.get('macd_bullish_cross', pd.Series([False])).iloc[idx_val]:
                score += 20
                triggers.append("MACD bullish crossover")
            
            if patterns.get('macd_bearish_cross', pd.Series([False])).iloc[idx_val]:
                score -= 20
                triggers.append("MACD bearish crossover")
            
            # SMC Patterns
            if patterns.get('liquidity_sweep_bull', pd.Series([False])).iloc[idx_val]:
                score += 40
                triggers.append("Liquidity sweep (bull)")
            
            if patterns.get('liquidity_sweep_bear', pd.Series([False])).iloc[idx_val]:
                score -= 40
                triggers.append("Liquidity sweep (bear)")
            
            if patterns.get('smc_choch_bull', pd.Series([False])).iloc[idx_val]:
                score += 45
                triggers.append("SMC CHoCH (bull)")
            
            if patterns.get('smc_choch_bear', pd.Series([False])).iloc[idx_val]:
                score -= 45
                triggers.append("SMC CHoCH (bear)")
            
            if patterns.get('in_killzone', pd.Series([False])).iloc[idx_val]:
                score += 15
                triggers.append("In Killzone")
            
            # Candle Patterns
            if patterns.get('bullish_engulfing', pd.Series([False])).iloc[idx_val]:
                score += 20
                triggers.append("Bullish engulfing")
            
            if patterns.get('bearish_engulfing', pd.Series([False])).iloc[idx_val]:
                score -= 20
                triggers.append("Bearish engulfing")
            
            # Limit score to -100 to 100
            score = max(-100, min(100, score))
            
        except Exception as e:
            logger.error(f"Score calculation error: {e}")
            triggers.append(f"Error: {str(e)[:50]}")
        
        return score, triggers
    
    def analyze_market_structure(self, df: pd.DataFrame, indicators: Dict) -> Dict[str, Any]:
        """Market structure analysis"""
        structure = {
            "trend": "Sideways",
            "momentum": "Neutral",
            "volatility": "Normal",
            "volume_trend": "Neutral",
            "key_levels": []
        }
        
        try:
            # Trend analysis
            if df['close'].iloc[-1] > indicators['sma50'] > indicators['sma200']:
                structure["trend"] = "Strong Bullish"
            elif df['close'].iloc[-1] > indicators['sma50']:
                structure["trend"] = "Bullish"
            elif df['close'].iloc[-1] < indicators['sma50'] < indicators['sma200']:
                structure["trend"] = "Strong Bearish"
            elif df['close'].iloc[-1] < indicators['sma50']:
                structure["trend"] = "Bearish"
            
            # Momentum
            rsi = indicators['rsi14'].iloc[-1]
            if rsi > 70:
                structure["momentum"] = "Overbought"
            elif rsi > 55:
                structure["momentum"] = "Bullish"
            elif rsi < 30:
                structure["momentum"] = "Oversold"
            elif rsi < 45:
                structure["momentum"] = "Bearish"
            
            # Volatility
            bb_width = (indicators['bb_upper'] - indicators['bb_lower']) / indicators['bb_middle']
            current_bb_width = bb_width.iloc[-1]
            avg_bb_width = bb_width.rolling(20).mean().iloc[-1]
            
            if current_bb_width > avg_bb_width * 1.5:
                structure["volatility"] = "High"
            elif current_bb_width < avg_bb_width * 0.5:
                structure["volatility"] = "Low"
            
            # Volume trend
            volume_ratio = df['volume'].iloc[-1] / indicators['volume_ma'].iloc[-1]
            if volume_ratio > 2:
                structure["volume_trend"] = "High Volume"
            elif volume_ratio > 1.2:
                structure["volume_trend"] = "Increasing"
            elif volume_ratio < 0.8:
                structure["volume_trend"] = "Decreasing"
            
            # Key levels
            recent_high = df['high'].rolling(20).max().iloc[-1]
            recent_low = df['low'].rolling(20).min().iloc[-1]
            structure["key_levels"] = [
                {"type": "resistance", "price": recent_high},
                {"type": "support", "price": recent_low},
                {"type": "sma50", "price": indicators['sma50'].iloc[-1]},
                {"type": "sma200", "price": indicators['sma200'].iloc[-1]}
            ]
            
        except Exception as e:
            logger.error(f"Market structure analysis error: {e}")
        
        return structure
    
    def generate_signal(self, df: pd.DataFrame, symbol: str, timeframe: str) -> SignalResult:
        """Generate complete trading signal"""
        try:
            # 1. Calculate indicators
            indicators = self.calculate_all_indicators(df)
            
            # 2. Detect patterns in phases
            phase1 = self.detect_patterns_phase1(df, indicators)
            patterns = self.detect_patterns_phase2(df, indicators, phase1)
            
            # 3. Calculate score
            score, triggers = self.calculate_signal_score(patterns)
            
            # 4. Analyze market structure
            structure = self.analyze_market_structure(df, indicators)
            
            # 5. Determine signal
            current_price = float(df['close'].iloc[-1])
            
            if score >= 60:
                signal = "🚀 STRONG BUY"
                strength = "VERY STRONG"
                action = "Enter long with stop loss"
                confidence = min(0.9, score / 100)
            elif score >= 30:
                signal = "✅ BUY"
                strength = "STRONG"
                action = "Consider long entry"
                confidence = min(0.7, score / 100)
            elif score <= -60:
                signal = "🔻 STRONG SELL"
                strength = "VERY STRONG"
                action = "Enter short with stop loss"
                confidence = min(0.9, abs(score) / 100)
            elif score <= -30:
                signal = "⚠️ SELL"
                strength = "STRONG"
                action = "Consider short entry"
                confidence = min(0.7, abs(score) / 100)
            else:
                signal = "⏸️ NEUTRAL"
                strength = "NEUTRAL"
                action = "Wait for confirmation"
                confidence = 0.5
            
            # 6. Killzone detection
            killzone = "Normal"
            if patterns.get('in_killzone', pd.Series([False])).iloc[-1]:
                if patterns.get('asia_kz', pd.Series([False])).iloc[-1]:
                    killzone = "🌙 Asia Session"
                elif patterns.get('london_kz', pd.Series([False])).iloc[-1]:
                    killzone = "🏛️ London Session"
                elif patterns.get('ny_kz', pd.Series([False])).iloc[-1]:
                    killzone = "🗽 NY Session"
            
            return SignalResult(
                pair=symbol,
                timeframe=timeframe,
                current_price=round(current_price, 6),
                signal=signal,
                score=score,
                strength=strength,
                killzone=killzone,
                triggers=triggers[:10],  # Limit to 10 triggers
                last_update=datetime.utcnow().strftime("%H:%M:%S UTC"),
                market_structure=structure,
                confidence=round(confidence, 2),
                recommended_action=action
            )
            
        except Exception as e:
            logger.error(f"Signal generation error: {e}")
            # Fallback to simple signal
            return self._generate_fallback_signal(df, symbol, timeframe)
    
    def _generate_fallback_signal(self, df: pd.DataFrame, symbol: str, timeframe: str) -> SignalResult:
        """Fallback simple signal"""
        current_price = float(df['close'].iloc[-1])
        prev_price = float(df['close'].iloc[-2]) if len(df) > 1 else current_price
        change_pct = ((current_price - prev_price) / prev_price * 100) if prev_price != 0 else 0
        
        if change_pct > 2:
            signal = "🚀 BUY"
            score = 70
            strength = "STRONG"
        elif change_pct > 0.5:
            signal = "✅ BUY"
            score = 60
            strength = "MODERATE"
        elif change_pct < -2:
            signal = "🔻 SELL"
            score = 30
            strength = "STRONG"
        elif change_pct < -0.5:
            signal = "⚠️ SELL"
            score = 40
            strength = "MODERATE"
        else:
            signal = "⏸️ NEUTRAL"
            score = 50
            strength = "NEUTRAL"
        
        return SignalResult(
            pair=symbol,
            timeframe=timeframe,
            current_price=current_price,
            signal=signal,
            score=score,
            strength=strength,
            killzone="Normal",
            triggers=[f"Price change: {change_pct:+.2f}%"],
            last_update=datetime.utcnow().strftime("%H:%M:%S UTC"),
            market_structure={"trend": "Unknown", "note": "Fallback mode"},
            confidence=0.5,
            recommended_action="Use with caution - fallback mode"
        )

# ==================== GLOBAL INSTANCE & PUBLIC API ====================
grok_pro = GrokIndicatorsPro()

def generate_ict_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Dict:
    """Public API for ICT signal generation"""
    result = grok_pro.generate_signal(df, symbol, timeframe)
    
    return {
        "pair": result.pair,
        "timeframe": result.timeframe,
        "current_price": result.current_price,
        "signal": result.signal,
        "score": result.score,
        "strength": result.strength,
        "killzone": result.killzone,
        "triggers": "\n".join(result.triggers) if result.triggers else "No triggers",
        "last_update": result.last_update,
        "market_structure": result.market_structure,
        "confidence": result.confidence,
        "recommended_action": result.recommended_action,
        "status": "success"
    }

def generate_simple_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Dict:
    """Public API for simple signal (fallback)"""
    result = grok_pro._generate_fallback_signal(df, symbol, timeframe)
    
    return {
        "pair": result.pair,
        "timeframe": result.timeframe,
        "current_price": result.current_price,
        "signal": result.signal,
        "score": result.score,
        "strength": result.strength,
        "killzone": result.killzone,
        "triggers": "\n".join(result.triggers),
        "last_update": result.last_update,
        "status": "success"
    }

# ==================== PERFORMANCE TEST ====================
if __name__ == "__main__":
    # Test with sample data
    np.random.seed(42)
    dates = pd.date_range(start='2024-01-01', periods=500, freq='5min')
    df = pd.DataFrame({
        'open': np.random.randn(500).cumsum() + 100,
        'high': np.random.randn(500).cumsum() + 102,
        'low': np.random.randn(500).cumsum() + 98,
        'close': np.random.randn(500).cumsum() + 100,
        'volume': np.random.randint(1000, 10000, 500)
    }, index=dates)
    
    # Add some trend
    df['close'] = df['close'] + np.linspace(0, 50, 500)
    df['high'] = df['high'] + np.linspace(0, 50, 500) + 2
    df['low'] = df['low'] + np.linspace(0, 50, 500) - 2
    
    # Generate signal
    import time
    start = time.time()
    signal = generate_ict_signal(df, "BTCUSDT", "5m")
    elapsed = time.time() - start
    
    print(f"⏱️  Processing time: {elapsed:.3f}s")
    print(f"📊 Signal: {signal['signal']}")
    print(f"🎯 Score: {signal['score']}/100")
    print(f"💪 Strength: {signal['strength']}")
    print(f"🕐 Killzone: {signal['killzone']}")
    print(f"💰 Price: ${signal['current_price']:.2f}")
    print(f"🤝 Confidence: {signal['confidence']*100:.1f}%")
    print(f"📈 Trend: {signal['market_structure']['trend']}")
    print("\n🎯 Triggers:")
    for trigger in signal['triggers'].split('\n'):
        print(f"  • {trigger}")
