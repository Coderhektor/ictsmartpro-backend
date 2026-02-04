from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime
import numpy as np
import pandas as pd
import asyncio
import aiohttp
import json
import time

# ========== CONFIGURATION ==========
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
LIMIT = 500
POLL_INTERVAL = 60  # Seconds for continuous data update (simulates real-time without websocket for all)

# ========== EXCHANGE ENUM ==========
class Exchange(Enum):
    BINANCE = "binance"
    OKX = "okx"
    KRAKEN = "kraken"

# ========== MANUAL INDICATORS ==========
def manual_ema(series: pd.Series, period: int) -> pd.Series:
    alpha = 2 / (period + 1)
    ema = pd.Series(np.nan, index=series.index)
    ema.iloc[0] = series.iloc[0]
    for i in range(1, len(series)):
        ema.iloc[i] = alpha * series.iloc[i] + (1 - alpha) * ema.iloc[i-1]
    return ema

def manual_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def manual_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr = tr.rolling(window=period).mean()
    return atr

def manual_supertrend(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 10, multiplier: float = 3.0) -> Tuple[pd.Series, pd.Series]:
    atr = manual_atr(high, low, close, period)
    hl2 = (high + low) / 2
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    st = pd.Series(np.nan, index=high.index)
    trend = pd.Series(0, index=high.index)  # 1 up, -1 down
    for i in range(1, len(high)):
        if trend.iloc[i-1] == 1:
            st.iloc[i] = max(lower.iloc[i], st.iloc[i-1])
            if close.iloc[i] < st.iloc[i]:
                trend.iloc[i] = -1
            else:
                trend.iloc[i] = 1
        else:
            st.iloc[i] = min(upper.iloc[i], st.iloc[i-1] if pd.notna(st.iloc[i-1]) else upper.iloc[i])
            if close.iloc[i] > st.iloc[i]:
                trend.iloc[i] = 1
            else:
                trend.iloc[i] = -1
    return st, trend

def manual_heikin_ashi(open_p: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> Dict[str, pd.Series]:
    ha_close = (open_p + high + low + close) / 4
    ha_open = (open_p.shift(1) + close.shift(1)) / 2
    ha_open.iloc[0] = (open_p.iloc[0] + close.iloc[0]) / 2
    ha_high = pd.DataFrame({'high': high, 'ha_open': ha_open, 'ha_close': ha_close}).max(axis=1)
    ha_low = pd.DataFrame({'low': low, 'ha_open': ha_open, 'ha_close': ha_close}).min(axis=1)
    return {'HA_Open': ha_open, 'HA_High': ha_high, 'HA_Low': ha_low, 'HA_Close': ha_close}

def manual_ict_concepts(df: pd.DataFrame) -> pd.DataFrame:
    df['MSS_Bullish'] = (df['high'] > df['high'].shift(1)) & (df['low'] > df['low'].shift(1)) & (df['close'] > df['open'])
    df['MSS_Bearish'] = (df['high'] < df['high'].shift(1)) & (df['low'] < df['low'].shift(1)) & (df['close'] < df['open'])
    bear_candle = (df['close'] < df['open']) & ((df['open'] - df['close']) > (df['high'] - df['low']) * 0.7)
    bullish_rejection = df['close'].shift(-1) > df['high']
    df['Bullish_OB'] = bear_candle & bullish_rejection.shift(1)
    bull_candle = (df['close'] > df['open']) & ((df['close'] - df['open']) > (df['high'] - df['low']) * 0.7)
    bearish_rejection = df['close'].shift(-1) < df['low']
    df['Bearish_OB'] = bull_candle & bearish_rejection.shift(1)
    df['FVG_Bullish'] = (df['low'].shift(1) > df['high'].shift(2)) & (df['low'] > df['high'].shift(2))
    df['FVG_Bearish'] = (df['high'].shift(1) < df['low'].shift(2)) & (df['high'] < df['low'].shift(2))
    return df

def manual_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
    ema_fast = manual_ema(close, fast)
    ema_slow = manual_ema(close, slow)
    macd = ema_fast - ema_slow
    macd_signal = manual_ema(macd, signal)
    return {'MACD': macd, 'MACD_Signal': macd_signal}

def manual_bbands(close: pd.Series, period: int = 20, std: float = 2.0) -> Dict[str, pd.Series]:
    rolling_mean = close.rolling(window=period).mean()
    rolling_std = close.rolling(window=period).std()
    upper = rolling_mean + (rolling_std * std)
    lower = rolling_mean - (rolling_std * std)
    return {'BB_Lower': lower, 'BB_Mid': rolling_mean, 'BB_Upper': upper}

def manual_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up = high - high.shift(1)
    down = low.shift(1) - low
    dm_up = up.where(up > down, 0).where(up > 0, 0)
    dm_down = down.where(down > up, 0).where(down > 0, 0)
    atr_val = manual_atr(high, low, close, period)
    di_up = 100 * (dm_up.rolling(period).mean() / atr_val)
    di_down = 100 * (dm_down.rolling(period).mean() / atr_val)
    dx = 100 * ((di_up - di_down).abs() / (di_up + di_down))
    adx = dx.rolling(period).mean()
    return adx

def manual_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    obv = pd.Series(0.0, index=close.index)
    obv.iloc[1:] = np.cumsum(np.sign(close.diff(1)) * volume.iloc[1:])
    return obv

def manual_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    typical_price = (high + low + close) / 3
    return (typical_price * volume).cumsum() / volume.cumsum()

# ========== DATA PROVIDER ==========
class DataProvider:
    def __init__(self, exchanges: List[Exchange] = [Exchange.BINANCE, Exchange.OKX, Exchange.KRAKEN]):
        self.exchanges = exchanges
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def fetch_from_exchange(self, exchange: Exchange, symbol: str, interval: str, limit: int) -> Optional[pd.DataFrame]:
        try:
            if exchange == Exchange.BINANCE:
                url = "https://api.binance.com/api/v3/klines"
                params = {'symbol': symbol.upper(), 'interval': interval, 'limit': limit}
            elif exchange == Exchange.OKX:
                sym = symbol.upper().replace('USDT', 'USDT') + '-SWAP'
                interval_map = {'1m': '1m', '5m': '5m', '15m': '15m', '1h': '1H', '4h': '4H', '1d': '1D'}
                bar = interval_map.get(interval, '1H')
                url = "https://www.okx.com/api/v5/market/candles"
                params = {'instId': sym, 'bar': bar, 'limit': str(limit)}
            elif exchange == Exchange.KRAKEN:
                sym = symbol.upper().replace('USDT', 'USD')
                interval_map = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240, '1d': 1440}
                inter = interval_map.get(interval, 60)
                url = "https://api.kraken.com/0/public/OHLC"
                params = {'pair': sym, 'interval': inter}
            else:
                return None

            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if exchange == Exchange.OKX:
                        if data.get('code') == '0':
                            data = data['data']
                            candles = [{'timestamp': int(d[0]), 'open': float(d[1]), 'high': float(d[2]), 'low': float(d[3]), 'close': float(d[4]), 'volume': float(d[5])} for d in data]
                    elif exchange == Exchange.KRAKEN:
                        if not data.get('error'):
                            key = list(data['result'].keys())[0]
                            ohlc = data['result'][key]
                            candles = [{'timestamp': int(d[0])*1000, 'open': float(d[1]), 'high': float(d[2]), 'low': float(d[3]), 'close': float(d[4]), 'volume': float(d[6])} for d in ohlc]
                    else:
                        candles = [{'timestamp': d[0], 'open': float(d[1]), 'high': float(d[2]), 'low': float(d[3]), 'close': float(d[4]), 'volume': float(d[5])} for d in data]
                    df = pd.DataFrame(candles).set_index('timestamp')
                    return df
        except Exception as e:
            print(f"Error fetching from {exchange.value}: {e}")
        return None

    async def fetch_ohlc(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        tasks = [self.fetch_from_exchange(ex, symbol, interval, limit) for ex in self.exchanges]
        results = await asyncio.gather(*tasks)
        valid_dfs = [df for df in results if df is not None and not df.empty]
        if not valid_dfs:
            raise ValueError("No data fetched from any exchange")
        # Align indices and aggregate
        combined = pd.concat(valid_dfs, axis=1, keys=[f'ex_{i}' for i in range(len(valid_dfs))])
        agg_df = pd.DataFrame(index=combined.index)
        agg_df['open'] = combined.filter(like='open').mean(axis=1)
        agg_df['high'] = combined.filter(like='high').max(axis=1)
        agg_df['low'] = combined.filter(like='low').min(axis=1)
        agg_df['close'] = combined.filter(like='close').mean(axis=1)
        agg_df['volume'] = combined.filter(like='volume').sum(axis=1)
        return agg_df.sort_index().tail(limit)

# ========== CORE ANALYZER CLASSES ==========
class TrendDirection(str, Enum):
    UPTREND = "UPTREND"
    DOWNTREND = "DOWNTREND"
    SIDEWAYS = "SIDEWAYS"
    REVERSAL_TO_UP = "REVERSAL_TO_UP"
    REVERSAL_TO_DOWN = "REVERSAL_TO_DOWN"

class LevelStrength(str, Enum):
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    WEAK = "WEAK"

@dataclass
class SwingPoint:
    index: int
    price: float
    is_high: bool
    strength: int
    timestamp: Optional[int] = None
    pattern: Optional[str] = None

@dataclass
class SupportResistanceLevel:
    price: float
    level_type: str
    strength: LevelStrength
    touch_count: int
    zone_high: float
    zone_low: float
    confidence: float

@dataclass
class TrendStructure:
    direction: TrendDirection
    swing_highs: List[SwingPoint]
    swing_lows: List[SwingPoint]
    bos_detected: bool = False
    mss_detected: bool = False
    fvg_zones: List[Tuple[float, float]] = None
    order_blocks: List[Dict] = None

@dataclass
class TradingSignal:
    signal_type: str
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    target_3: float
    confidence: float
    reason: str

# ========== ENHANCED ANALYZER ==========
class EnhancedSupportResistanceAnalyzer:
    def __init__(self, swing_window: int = 5, zone_threshold: float = 0.002, use_heikin_ashi: bool = True, use_ict: bool = True):
        self.swing_window = swing_window
        self.zone_threshold = zone_threshold
        self.use_heikin_ashi = use_heikin_ashi
        self.use_ict = use_ict

    def calculate_all_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['EMA_20'] = manual_ema(df['close'], 20)
        df['EMA_50'] = manual_ema(df['close'], 50)
        df['EMA_200'] = manual_ema(df['close'], 200)
        df['RSI_14'] = manual_rsi(df['close'], 14)
        df['ATR_14'] = manual_atr(df['high'], df['low'], df['close'], 14)
        macd_dict = manual_macd(df['close'])
        df['MACD_12_26_9'] = macd_dict['MACD']
        df['MACDs_12_26_9'] = macd_dict['MACD_Signal']
        bbands_dict = manual_bbands(df['close'])
        df['BBL_20_2.0'] = bbands_dict['BB_Lower']
        df['BBM_20_2.0'] = bbands_dict['BB_Mid']
        df['BBU_20_2.0'] = bbands_dict['BB_Upper']
        df['OBV'] = manual_obv(df['close'], df['volume'])
        df['VWAP'] = manual_vwap(df['high'], df['low'], df['close'], df['volume'])
        st, trend = manual_supertrend(df['high'], df['low'], df['close'])
        df['SuperTrend'] = st
        df['Trend'] = trend
        ha = manual_heikin_ashi(df['open'], df['high'], df['low'], df['close'])
        df = pd.concat([df, pd.DataFrame(ha)], axis=1)
        df = manual_ict_concepts(df)
        df['ADX_14'] = manual_adx(df['high'], df['low'], df['close'], 14)
        return df.fillna(method='ffill').fillna(0)  # Handle NaNs

    def detect_swing_points_enhanced(self, df: pd.DataFrame) -> Tuple[List[SwingPoint], List[SwingPoint]]:
        price_high = df['HA_High'] if self.use_heikin_ashi else df['high']
        price_low = df['HA_Low'] if self.use_heikin_ashi else df['low']
        swing_highs = []
        swing_lows = []
        for i in range(self.swing_window, len(df) - self.swing_window):
            curr_high = price_high.iloc[i]
            curr_low = price_low.iloc[i]
            if curr_high > price_high.iloc[i-self.swing_window:i].max() and curr_high > price_high.iloc[i+1:i+self.swing_window+1].max():
                pattern = self._identify_candle_pattern(df, i, True)
                swing_highs.append(SwingPoint(i, curr_high, True, self.swing_window, int(df.index[i].timestamp() * 1000), pattern=pattern))
            if curr_low < price_low.iloc[i-self.swing_window:i].min() and curr_low < price_low.iloc[i+1:i+self.swing_window+1].min():
                pattern = self._identify_candle_pattern(df, i, False)
                swing_lows.append(SwingPoint(i, curr_low, False, self.swing_window, int(df.index[i].timestamp() * 1000), pattern=pattern))
        return swing_highs, swing_lows

    def _identify_candle_pattern(self, df: pd.DataFrame, i: int, is_high: bool) -> Optional[str]:
        if i < 1 or i >= len(df) - 1:
            return None
        o, c, h, l = df['open'].iloc[i], df['close'].iloc[i], df['high'].iloc[i], df['low'].iloc[i]
        prev_o, prev_c = df['open'].iloc[i-1], df['close'].iloc[i-1]
        body = abs(c - o)
        range_val = h - l
        if range_val == 0:
            return None
        if not is_high and c > o:  # Hammer
            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l
            if lower_wick > 2 * body and upper_wick < 0.3 * body:
                return "HAMMER"
            if prev_c < prev_o and c > prev_o and o < prev_c:
                return "BULLISH_ENGULFING"
        elif is_high and c < o:  # Shooting Star
            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l
            if upper_wick > 2 * body and lower_wick < 0.3 * body:
                return "SHOOTING_STAR"
            if prev_c > prev_o and c < prev_o and o > prev_c:
                return "BEARISH_ENGULFING"
        return None

    def analyze_trend_structure_enhanced(self, df: pd.DataFrame, swing_highs: List[SwingPoint], swing_lows: List[SwingPoint]) -> TrendStructure:
        hh_count = sum(1 for i in range(1, len(swing_highs)) if swing_highs[i].price > swing_highs[i-1].price)
        lh_count = sum(1 for i in range(1, len(swing_highs)) if swing_highs[i].price < swing_highs[i-1].price)
        hl_count = sum(1 for i in range(1, len(swing_lows)) if swing_lows[i].price > swing_lows[i-1].price)
        ll_count = sum(1 for i in range(1, len(swing_lows)) if swing_lows[i].price < swing_lows[i-1].price)
        trend_strength = df['ADX_14'].iloc[-1] if pd.notna(df['ADX_14'].iloc[-1]) else 50.0
        mss_detected = df['MSS_Bullish'].iloc[-5:].any() or df['MSS_Bearish'].iloc[-5:].any() if self.use_ict else False
        bos_detected = False
        if len(swing_highs) >= 2 and swing_highs[-1].price > swing_highs[-2].price and len(swing_lows) >= 2 and swing_lows[-1].price > swing_lows[-2].price:
            direction = TrendDirection.UPTREND
        elif len(swing_highs) >= 2 and swing_highs[-1].price < swing_highs[-2].price and len(swing_lows) >= 2 and swing_lows[-1].price < swing_lows[-2].price:
            direction = TrendDirection.DOWNTREND
        else:
            direction = TrendDirection.SIDEWAYS
        if direction == TrendDirection.UPTREND and len(swing_lows) >= 2 and swing_lows[-1].price < swing_lows[-2].price:
            bos_detected = True
        elif direction == TrendDirection.DOWNTREND and len(swing_highs) >= 2 and swing_highs[-1].price > swing_highs[-2].price:
            bos_detected = True
        fvg_zones = []
        order_blocks = []
        if self.use_ict:
            for i in range(2, len(df)):
                if df['FVG_Bullish'].iloc[i]:
                    low = df['high'].iloc[i-2]
                    high = df['low'].iloc[i-1]
                    if high > low:
                        fvg_zones.append((low, high))
                if df['FVG_Bearish'].iloc[i]:
                    low = df['high'].iloc[i-1]
                    high = df['low'].iloc[i-2]
                    if high > low:
                        fvg_zones.append((low, high))
            for i in range(1, len(df)):
                if df['Bullish_OB'].iloc[i]:
                    order_blocks.append({'type': 'bullish', 'zone': (df['low'].iloc[i], df['high'].iloc[i])})
                if df['Bearish_OB'].iloc[i]:
                    order_blocks.append({'type': 'bearish', 'zone': (df['low'].iloc[i], df['high'].iloc[i])})
        return TrendStructure(direction, swing_highs, swing_lows, bos_detected, mss_detected, fvg_zones, order_blocks)

    def identify_support_resistance_enhanced(self, df: pd.DataFrame, swing_highs: List[SwingPoint], swing_lows: List[SwingPoint]) -> Tuple[List[SupportResistanceLevel], List[SupportResistanceLevel]]:
        current_price = df['close'].iloc[-1]
        supports = []
        resistances = []
        for sl in swing_lows[-5:]:
            supports.append(SupportResistanceLevel(sl.price, "support", LevelStrength.MINOR, 1, sl.price - 0.002 * sl.price, sl.price + 0.002 * sl.price, 70.0))
        for sh in swing_highs[-5:]:
            resistances.append(SupportResistanceLevel(sh.price, "resistance", LevelStrength.MINOR, 1, sh.price - 0.002 * sh.price, sh.price + 0.002 * sh.price, 70.0))
        return supports, resistances

    def generate_enhanced_signals(self, df: pd.DataFrame, trend_structure: TrendStructure, support_levels: List[SupportResistanceLevel], resistance_levels: List[SupportResistanceLevel]) -> List[TradingSignal]:
        signals = []
        current_price = df['close'].iloc[-1]
        atr = df['ATR_14'].iloc[-1]
        if trend_structure.bos_detected and trend_structure.direction == TrendDirection.UPTREND:
            entry = current_price
            sl = current_price - atr * 1.5
            tp1 = entry + atr * 2
            tp2 = entry + atr * 3
            tp3 = entry + atr * 4
            signals.append(TradingSignal("BUY", entry, sl, tp1, tp2, tp3, 80.0, "BOS in Uptrend"))
        return signals

    async def full_enhanced_analysis(self, symbol: str, interval: str = '1h', limit: int = 500) -> Dict:
        provider = DataProvider()
        async with provider:
            df = await provider.fetch_ohlc(symbol, interval, limit)
        if df.empty:
            raise ValueError("No data fetched")
        df = self.calculate_all_indicators(df)
        swing_highs, swing_lows = self.detect_swing_points_enhanced(df)
        trend_structure = self.analyze_trend_structure_enhanced(df, swing_highs, swing_lows)
        support_levels, resistance_levels = self.identify_support_resistance_enhanced(df, swing_highs, swing_lows)
        signals = self.generate_enhanced_signals(df, trend_structure, support_levels, resistance_levels)
        current_price = df['close'].iloc[-1] if not df.empty else 0
        result = {
            "metadata": {
                "symbol": symbol,
                "interval": interval,
                "candles": len(df),
                "time": datetime.now().isoformat(),
                "current_price": current_price
            },
            "trend_analysis": asdict(trend_structure),
            "support_levels": [asdict(s) for s in support_levels],
            "resistance_levels": [asdict(r) for r in resistance_levels],
            "trading_signals": [asdict(sig) for sig in signals]
        }
        return result

# ========== MAIN APPLICATION ==========
async def continuous_poll(analyzer, symbol, interval, limit):
    while True:
        try:
            result = await analyzer.full_enhanced_analysis(symbol, interval, limit)
            print("\nAnalysis Update:")
            print(result)
        except Exception as e:
            print(f"Error: {e}")
        await asyncio.sleep(POLL_INTERVAL)

async def main():
    analyzer = EnhancedSupportResistanceAnalyzer()
    asyncio.create_task(continuous_poll(analyzer, SYMBOL, INTERVAL, LIMIT))
    await asyncio.sleep(float('inf'))  # Keep running

if __name__ == "__main__":
    asyncio.run(main())
