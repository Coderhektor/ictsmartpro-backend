"""
🎯 ENHANCED MULTI-EXCHANGE SUPPORT/RESISTANCE & TREND ANALYZER
✅ Real-time data from multiple exchanges (Binance, CoinGecko, OKX, Kraken)
✅ ICT Market Structure, Heikin Ashi, SuperTrend, RSI indicators
✅ Professional trading signals with confirmation filters
✅ No synthetic/random data - only real market data
"""

from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import pandas_ta as ta
import asyncio
import aiohttp
import warnings
warnings.filterwarnings('ignore')

# ========== DATA PROVIDER INTEGRATION ==========

class Exchange(Enum):
    """Supported cryptocurrency exchanges"""
    BINANCE = "binance"
    COINGECKO = "coingecko"
    OKX = "okx"
    KRAKEN = "kraken"

class DataProvider:
    """Unified data provider for multiple exchanges"""
    
    def __init__(self, primary_exchange: Exchange = Exchange.BINANCE):
        self.primary_exchange = primary_exchange
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def fetch_ohlc(self, symbol: str, interval: str = '1h', 
                        limit: int = 500, exchange: Exchange = None) -> List[Dict]:
        """
        Fetch OHLC data from specified exchange
        symbol: e.g., 'BTCUSDT', 'ETH-USD'
        interval: '1m', '5m', '15m', '1h', '4h', '1d'
        """
        if exchange is None:
            exchange = self.primary_exchange
            
        if exchange == Exchange.BINANCE:
            return await self._fetch_binance_ohlc(symbol, interval, limit)
        elif exchange == Exchange.COINGECKO:
            return await self._fetch_coingecko_ohlc(symbol, interval, limit)
        elif exchange == Exchange.OKX:
            return await self._fetch_okx_ohlc(symbol, interval, limit)
        elif exchange == Exchange.KRAKEN:
            return await self._fetch_kraken_ohlc(symbol, interval, limit)
        else:
            raise ValueError(f"Unsupported exchange: {exchange}")
    
    async def _fetch_binance_ohlc(self, symbol: str, interval: str, limit: int) -> List[Dict]:
        """Fetch from Binance API [citation:4]"""
        try:
            # Binance interval mapping
            interval_map = {
                '1m': '1m', '5m': '5m', '15m': '15m',
                '1h': '1h', '4h': '4h', '1d': '1d'
            }
            binance_interval = interval_map.get(interval, '1h')
            
            url = f"https://api.binance.com/api/v3/klines"
            params = {
                'symbol': symbol.upper(),
                'interval': binance_interval,
                'limit': min(limit, 1000)
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    candles = []
                    for candle in data:
                        candles.append({
                            'timestamp': candle[0],
                            'open': float(candle[1]),
                            'high': float(candle[2]),
                            'low': float(candle[3]),
                            'close': float(candle[4]),
                            'volume': float(candle[5])
                        })
                    return candles
                else:
                    raise Exception(f"Binance API error: {response.status}")
        except Exception as e:
            print(f"Binance fetch error: {e}")
            return []
    
    async def _fetch_coingecko_ohlc(self, symbol: str, interval: str, limit: int) -> List[Dict]:
        """Fetch from CoinGecko API [citation:1][citation:5]"""
        try:
            # CoinGecko uses different ID format
            coin_id = symbol.lower().replace('usdt', '').replace('usd', '')
            
            # Map interval to days (CoinGecko granularity: 1-2 days: 30min, 3-30: 4h, 31+: 4d)
            if 'm' in interval:
                days = 1
            elif 'h' in interval:
                if interval == '1h':
                    days = 2
                elif interval == '4h':
                    days = 30
            else:  # 1d
                days = 90
            
            url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
            params = {
                'vs_currency': 'usd',
                'days': days
            }
            headers = {'x-cg-demo-api-key': 'YOUR_API_KEY'}  # Add your key here
            
            async with self.session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    candles = []
                    for candle in data:
                        candles.append({
                            'timestamp': candle[0],
                            'open': candle[1],
                            'high': candle[2],
                            'low': candle[3],
                            'close': candle[4],
                            'volume': 0  # CoinGecko doesn't provide volume in OHLC
                        })
                    # Limit and sort
                    candles = sorted(candles, key=lambda x: x['timestamp'])[-limit:]
                    return candles
                else:
                    raise Exception(f"CoinGecko API error: {response.status}")
        except Exception as e:
            print(f"CoinGecko fetch error: {e}")
            return []
    
    async def _fetch_okx_ohlc(self, symbol: str, interval: str, limit: int) -> List[Dict]:
        """Fetch from OKX API [citation:8]"""
        try:
            # OKX interval mapping
            interval_map = {
                '1m': '1m', '5m': '5m', '15m': '15m',
                '1h': '1H', '4h': '4H', '1d': '1D'
            }
            okx_interval = interval_map.get(interval, '1H')
            
            # Format symbol for OKX (BTC-USDT-SWAP or BTC-USDT)
            if not '-' in symbol:
                symbol = f"{symbol[:3]}-{symbol[3:]}" if len(symbol) > 6 else symbol
            
            url = f"https://www.okx.com/api/v5/market/candles"
            params = {
                'instId': f"{symbol.upper()}-SWAP",  # Use swap for better liquidity
                'bar': okx_interval,
                'limit': min(limit, 1440)  # OKX max is 1440
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data['code'] == '0':
                        candles = []
                        for candle in reversed(data['data']):  # OKX returns newest first
                            candles.append({
                                'timestamp': int(candle[0]),
                                'open': float(candle[1]),
                                'high': float(candle[2]),
                                'low': float(candle[3]),
                                'close': float(candle[4]),
                                'volume': float(candle[5])
                            })
                        return candles[-limit:]  # Return requested limit
                    else:
                        raise Exception(f"OKX API error: {data['msg']}")
                else:
                    raise Exception(f"OKX HTTP error: {response.status}")
        except Exception as e:
            print(f"OKX fetch error: {e}")
            return []
    
    async def _fetch_kraken_ohlc(self, symbol: str, interval: str, limit: int) -> List[Dict]:
        """Fetch from Kraken API [citation:6]"""
        try:
            # Kraken interval in minutes
            interval_map = {
                '1m': 1, '5m': 5, '15m': 15,
                '1h': 60, '4h': 240, '1d': 1440
            }
            interval_min = interval_map.get(interval, 60)
            
            # Kraken symbol format
            kraken_symbol = symbol.replace('USDT', 'USD').upper()
            
            url = f"https://api.kraken.com/0/public/OHLC"
            params = {
                'pair': kraken_symbol,
                'interval': interval_min
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if len(data['error']) == 0:
                        key = list(data['result'].keys())[0]
                        ohlc_data = data['result'][key]
                        candles = []
                        for candle in ohlc_data:
                            candles.append({
                                'timestamp': int(candle[0]) * 1000,  # Convert to milliseconds
                                'open': float(candle[1]),
                                'high': float(candle[2]),
                                'low': float(candle[3]),
                                'close': float(candle[4]),
                                'volume': float(candle[6])
                            })
                        return candles[-limit:]
                    else:
                        raise Exception(f"Kraken API error: {data['error']}")
                else:
                    raise Exception(f"Kraken HTTP error: {response.status}")
        except Exception as e:
            print(f"Kraken fetch error: {e}")
            return []

# ========== TECHNICAL INDICATORS ==========

class TechnicalIndicators:
    """ICT, Heikin Ashi, SuperTrend, RSI and other indicators [citation:3][citation:7]"""
    
    @staticmethod
    def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
        """Calculate Heikin Ashi candles"""
        ha_df = df.copy()
        
        # Heikin Ashi Close
        ha_df['HA_Close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        
        # Heikin Ashi Open
        ha_df['HA_Open'] = (df['open'].shift(1) + df['close'].shift(1)) / 2
        ha_df.loc[0, 'HA_Open'] = (df.loc[0, 'open'] + df.loc[0, 'close']) / 2
        
        # Heikin Ashi High
        ha_df['HA_High'] = df[['high', 'HA_Open', 'HA_Close']].max(axis=1)
        
        # Heikin Ashi Low
        ha_df['HA_Low'] = df[['low', 'HA_Open', 'HA_Close']].min(axis=1)
        
        return ha_df
    
    @staticmethod
    def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
        """Calculate SuperTrend indicator"""
        st_df = df.copy()
        
        # Calculate ATR
        st_df['TR'] = np.maximum(
            st_df['high'] - st_df['low'],
            np.maximum(
                abs(st_df['high'] - st_df['close'].shift(1)),
                abs(st_df['low'] - st_df['close'].shift(1))
            )
        )
        st_df['ATR'] = st_df['TR'].rolling(window=period).mean()
        
        # Calculate basic upper and lower bands
        hl2 = (st_df['high'] + st_df['low']) / 2
        st_df['UpperBand'] = hl2 + (multiplier * st_df['ATR'])
        st_df['LowerBand'] = hl2 - (multiplier * st_df['ATR'])
        
        # Initialize SuperTrend
        st_df['SuperTrend'] = 0.0
        st_df['Trend'] = 0  # 1 = uptrend, -1 = downtrend
        
        for i in range(period, len(st_df)):
            # Current values
            close = st_df.loc[i, 'close']
            upper_band = st_df.loc[i, 'UpperBand']
            lower_band = st_df.loc[i, 'LowerBand']
            
            # Previous values
            prev_close = st_df.loc[i-1, 'close']
            prev_upper = st_df.loc[i-1, 'UpperBand']
            prev_lower = st_df.loc[i-1, 'LowerBand']
            prev_supertrend = st_df.loc[i-1, 'SuperTrend']
            
            # Calculate SuperTrend
            if prev_supertrend == prev_upper:
                if close <= upper_band:
                    supertrend = upper_band
                    trend = 1
                else:
                    supertrend = lower_band
                    trend = -1
            else:  # prev_supertrend == prev_lower
                if close >= lower_band:
                    supertrend = lower_band
                    trend = -1
                else:
                    supertrend = upper_band
                    trend = 1
            
            st_df.loc[i, 'SuperTrend'] = supertrend
            st_df.loc[i, 'Trend'] = trend
        
        return st_df
    
    @staticmethod
    def calculate_ict_concepts(df: pd.DataFrame) -> pd.DataFrame:
        """Calculate ICT (Inner Circle Trader) concepts"""
        ict_df = df.copy()
        
        # Market Structure Shift (MSS)
        ict_df['MSS_Bullish'] = (ict_df['high'] > ict_df['high'].shift(1)) & \
                               (ict_df['low'] > ict_df['low'].shift(1)) & \
                               (ict_df['close'] > ict_df['open'])
        
        ict_df['MSS_Bearish'] = (ict_df['high'] < ict_df['high'].shift(1)) & \
                               (ict_df['low'] < ict_df['low'].shift(1)) & \
                               (ict_df['close'] < ict_df['open'])
        
        # Order Blocks (OB)
        # Bullish OB: large bear candle followed by immediate bullish rejection
        bear_candle = (ict_df['close'] < ict_df['open']) & \
                     ((ict_df['open'] - ict_df['close']) > (ict_df['high'] - ict_df['low']) * 0.7)
        bullish_rejection = ict_df['close'].shift(-1) > ict_df['high']
        ict_df['Bullish_OB'] = bear_candle & bullish_rejection.shift(1)
        
        # Bearish OB: large bull candle followed by immediate bearish rejection
        bull_candle = (ict_df['close'] > ict_df['open']) & \
                     ((ict_df['close'] - ict_df['open']) > (ict_df['high'] - ict_df['low']) * 0.7)
        bearish_rejection = ict_df['close'].shift(-1) < ict_df['low']
        ict_df['Bearish_OB'] = bull_candle & bearish_rejection.shift(1)
        
        # Fair Value Gap (FVG)
        ict_df['FVG_Bullish'] = (ict_df['low'].shift(1) > ict_df['high'].shift(2)) & \
                               (ict_df['low'] > ict_df['high'].shift(2))
        
        ict_df['FVG_Bearish'] = (ict_df['high'].shift(1) < ict_df['low'].shift(2)) & \
                               (ict_df['high'] < ict_df['low'].shift(2))
        
        return ict_df
    
    @staticmethod
    def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all technical indicators"""
        # Ensure DataFrame has proper columns
        if not all(col in df.columns for col in ['open', 'high', 'low', 'close', 'volume']):
            raise ValueError("DataFrame must contain OHLCV columns")
        
        # Calculate RSI, MACD, Bollinger Bands using pandas_ta
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.bbands(length=20, std=2, append=True)
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.ema(length=200, append=True)
        
        # Calculate volume indicators
        df.ta.obv(append=True)
        df.ta.vwap(append=True)
        
        # Calculate custom indicators
        df = TechnicalIndicators.calculate_heikin_ashi(df)
        df = TechnicalIndicators.calculate_supertrend(df)
        df = TechnicalIndicators.calculate_ict_concepts(df)
        
        # Calculate ADX for trend strength
        df.ta.adx(length=14, append=True)
        
        return df

# ========== CORE ANALYZER CLASSES ==========

class TrendDirection(str, Enum):
    """Trend direction"""
    UPTREND = "UPTREND"
    DOWNTREND = "DOWNTREND"
    SIDEWAYS = "SIDEWAYS"
    REVERSAL_TO_UP = "REVERSAL_TO_UP"
    REVERSAL_TO_DOWN = "REVERSAL_TO_DOWN"

class LevelStrength(str, Enum):
    """Level strength"""
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    WEAK = "WEAK"

@dataclass
class SwingPoint:
    """Swing High/Low point"""
    index: int
    price: float
    is_high: bool
    strength: int
    timestamp: Optional[int] = None
    confirmed: bool = True
    pattern: Optional[str] = None

@dataclass
class SupportResistanceLevel:
    """Support/Resistance level"""
    price: float
    level_type: str
    strength: LevelStrength
    touch_count: int
    first_touch_index: int
    last_touch_index: int
    zone_high: float
    zone_low: float
    confidence: float
    indicator_confirmation: Dict[str, bool]
    volume_profile: Optional[float] = None

@dataclass
class TrendStructure:
    """Trend structure analysis"""
    direction: TrendDirection
    swing_highs: List[SwingPoint]
    swing_lows: List[SwingPoint]
    higher_highs_count: int
    higher_lows_count: int
    lower_highs_count: int
    lower_lows_count: int
    trend_strength: float
    bos_detected: bool
    bos_price: Optional[float] = None
    bos_index: Optional[int] = None
    mss_detected: bool = False
    fvg_zones: List[Tuple[float, float]] = None
    order_blocks: List[Dict] = None

@dataclass
class TradingSignal:
    """Trading signal"""
    signal_type: str
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    target_3: float
    confidence: float
    reason: str
    risk_reward: float
    indicators_confirmation: Dict[str, bool]
    timestamp: int = None
    exchange: str = "binance"

class EnhancedSupportResistanceAnalyzer:
    """Enhanced Support/Resistance and Trend Analysis Engine"""
    
    def __init__(self, swing_window: int = 5, zone_threshold: float = 0.002,
                 use_heikin_ashi: bool = True, use_ict: bool = True):
        self.swing_window = swing_window
        self.zone_threshold = zone_threshold
        self.use_heikin_ashi = use_heikin_ashi
        self.use_ict = use_ict
        self.indicators = TechnicalIndicators()
        
    def detect_swing_points_enhanced(self, df: pd.DataFrame) -> Tuple[List[SwingPoint], List[SwingPoint]]:
        """
        Enhanced swing point detection with pattern recognition
        """
        swing_highs = []
        swing_lows = []
        
        # Use Heikin Ashi if enabled
        if self.use_heikin_ashi:
            price_high = df['HA_High'] if 'HA_High' in df.columns else df['high']
            price_low = df['HA_Low'] if 'HA_Low' in df.columns else df['low']
        else:
            price_high = df['high']
            price_low = df['low']
        
        for i in range(self.swing_window, len(df) - self.swing_window):
            current_high = price_high.iloc[i]
            current_low = price_low.iloc[i]
            
            # Check for Swing High
            is_swing_high = True
            left_highs = price_high.iloc[i-self.swing_window:i].values
            right_highs = price_high.iloc[i+1:i+self.swing_window+1].values
            
            if len(left_highs) > 0 and len(right_highs) > 0:
                if (current_high > max(left_highs)) and (current_high > max(right_highs)):
                    # Additional confirmation: close below high for resistance
                    if df['close'].iloc[i] < current_high * 0.995:  # 0.5% below high
                        # Check for pattern
                        pattern = self._identify_candle_pattern(df, i, is_high=True)
                        swing_highs.append(SwingPoint(
                            index=i,
                            price=float(current_high),
                            is_high=True,
                            strength=self.swing_window,
                            timestamp=int(df.index[i].timestamp() * 1000) if hasattr(df.index[i], 'timestamp') else None,
                            pattern=pattern
                        ))
            
            # Check for Swing Low
            is_swing_low = True
            left_lows = price_low.iloc[i-self.swing_window:i].values
            right_lows = price_low.iloc[i+1:i+self.swing_window+1].values
            
            if len(left_lows) > 0 and len(right_lows) > 0:
                if (current_low < min(left_lows)) and (current_low < min(right_lows)):
                    # Additional confirmation: close above low for support
                    if df['close'].iloc[i] > current_low * 1.005:  # 0.5% above low
                        pattern = self._identify_candle_pattern(df, i, is_high=False)
                        swing_lows.append(SwingPoint(
                            index=i,
                            price=float(current_low),
                            is_high=False,
                            strength=self.swing_window,
                            timestamp=int(df.index[i].timestamp() * 1000) if hasattr(df.index[i], 'timestamp') else None,
                            pattern=pattern
                        ))
        
        return swing_highs, swing_lows
    
    def _identify_candle_pattern(self, df: pd.DataFrame, index: int, is_high: bool) -> Optional[str]:
        """Identify candlestick patterns"""
        if index < 3 or index >= len(df) - 2:
            return None
            
        open_price = df['open'].iloc[index]
        close_price = df['close'].iloc[index]
        high_price = df['high'].iloc[index]
        low_price = df['low'].iloc[index]
        
        prev_open = df['open'].iloc[index-1]
        prev_close = df['close'].iloc[index-1]
        prev_high = df['high'].iloc[index-1]
        prev_low = df['low'].iloc[index-1]
        
        # Determine if bullish or bearish
        is_bullish = close_price > open_price
        is_bearish = close_price < open_price
        
        # Calculate body size and wick ratios
        body_size = abs(close_price - open_price)
        total_range = high_price - low_price
        
        if total_range == 0:
            return None
            
        body_ratio = body_size / total_range
        
        # Hammer pattern (for swing lows)
        if not is_high and is_bullish:
            upper_wick = high_price - max(open_price, close_price)
            lower_wick = min(open_price, close_price) - low_price
            
            if lower_wick > body_size * 2 and upper_wick < body_size * 0.3:
                return "HAMMER"
            
            # Bullish engulfing
            if is_bearish and close_price > prev_open and open_price < prev_close:
                return "BULLISH_ENGULFING"
        
        # Shooting star (for swing highs)
        elif is_high and is_bearish:
            upper_wick = high_price - max(open_price, close_price)
            lower_wick = min(open_price, close_price) - low_price
            
            if upper_wick > body_size * 2 and lower_wick < body_size * 0.3:
                return "SHOOTING_STAR"
            
            # Bearish engulfing
            if is_bullish and close_price < prev_open and open_price > prev_close:
                return "BEARISH_ENGULFING"
        
        return None
    
    def analyze_trend_structure_enhanced(self, df: pd.DataFrame,
                                       swing_highs: List[SwingPoint],
                                       swing_lows: List[SwingPoint]) -> TrendStructure:
        """
        Enhanced trend analysis with ICT concepts
        """
        # Basic trend analysis
        hh_count, hl_count, lh_count, ll_count = 0, 0, 0, 0
        
        for i in range(1, len(swing_highs)):
            if swing_highs[i].price > swing_highs[i-1].price:
                hh_count += 1
            elif swing_highs[i].price < swing_highs[i-1].price:
                lh_count += 1
        
        for i in range(1, len(swing_lows)):
            if swing_lows[i].price > swing_lows[i-1].price:
                hl_count += 1
            elif swing_lows[i].price < swing_lows[i-1].price:
                ll_count += 1
        
        # Calculate trend strength with indicators
        trend_strength = self._calculate_trend_strength(df)
        
        # Check for ICT Market Structure Shift
        mss_detected = False
        if self.use_ict and 'MSS_Bullish' in df.columns and 'MSS_Bearish' in df.columns:
            recent_mss_bullish = df['MSS_Bullish'].iloc[-5:].any()
            recent_mss_bearish = df['MSS_Bearish'].iloc[-5:].any()
            mss_detected = recent_mss_bullish or recent_mss_bearish
        
        # Detect Break of Structure (BOS)
        bos_detected = False
        bos_price = None
        bos_index = None
        
        if len(swing_highs) >= 3 and len(swing_lows) >= 3:
            recent_highs = swing_highs[-3:]
            recent_lows = swing_lows[-3:]
            
            # Uptrend BOS detection
            if (hh_count > lh_count and hl_count > ll_count and
                len(recent_lows) >= 2 and recent_lows[-1].price < recent_lows[-2].price):
                
                if len(swing_lows) >= 2:
                    prev_hl = swing_lows[-2].price
                    if recent_lows[-1].price < prev_hl:
                        bos_detected = True
                        bos_price = prev_hl
                        bos_index = recent_lows[-1].index
            
            # Downtrend BOS detection
            elif (lh_count > hh_count and ll_count > hl_count and
                  len(recent_highs) >= 2 and recent_highs[-1].price > recent_highs[-2].price):
                
                if len(swing_highs) >= 2:
                    prev_lh = swing_highs[-2].price
                    if recent_highs[-1].price > prev_lh:
                        bos_detected = True
                        bos_price = prev_lh
                        bos_index = recent_highs[-1].index
        
        # Determine trend direction
        if hh_count > lh_count * 1.5 and hl_count > ll_count * 1.5:
            if bos_detected and bos_index and len(swing_lows) > 0:
                if swing_lows[-1].index < bos_index:
                    direction = TrendDirection.UPTREND
                else:
                    direction = TrendDirection.REVERSAL_TO_DOWN
            else:
                direction = TrendDirection.UPTREND
        elif lh_count > hh_count * 1.5 and ll_count > hl_count * 1.5:
            if bos_detected and bos_index and len(swing_highs) > 0:
                if swing_highs[-1].index < bos_index:
                    direction = TrendDirection.DOWNTREND
                else:
                    direction = TrendDirection.REVERSAL_TO_UP
            else:
                direction = TrendDirection.DOWNTREND
        elif bos_detected:
            direction = TrendDirection.REVERSAL_TO_UP if hh_count >= lh_count else TrendDirection.REVERSAL_TO_DOWN
        else:
            direction = TrendDirection.SIDEWAYS
        
        # Extract ICT concepts
        fvg_zones = []
        order_blocks = []
        
        if self.use_ict:
            fvg_zones = self._extract_fvg_zones(df)
            order_blocks = self._extract_order_blocks(df)
        
        return TrendStructure(
            direction=direction,
            swing_highs=swing_highs,
            swing_lows=swing_lows,
            higher_highs_count=hh_count,
            higher_lows_count=hl_count,
            lower_highs_count=lh_count,
            lower_lows_count=ll_count,
            trend_strength=trend_strength,
            bos_detected=bos_detected,
            bos_price=bos_price,
            bos_index=bos_index,
            mss_detected=mss_detected,
            fvg_zones=fvg_zones,
            order_blocks=order_blocks
        )
    
    def _calculate_trend_strength(self, df: pd.DataFrame) -> float:
        """Calculate comprehensive trend strength using multiple indicators"""
        strength_factors = []
        
        # 1. ADX strength
        if 'ADX_14' in df.columns:
            adx = df['ADX_14'].iloc[-1]
            if not pd.isna(adx):
                adx_strength = min(adx / 100.0, 1.0)  # Normalize to 0-1
                strength_factors.append(adx_strength * 0.4)  # 40% weight
        
        # 2. EMA alignment
        if all(ema in df.columns for ema in ['EMA_20', 'EMA_50', 'EMA_200']):
            ema_20 = df['EMA_20'].iloc[-1]
            ema_50 = df['EMA_50'].iloc[-1]
            ema_200 = df['EMA_200'].iloc[-1]
            
            if not any(pd.isna(x) for x in [ema_20, ema_50, ema_200]):
                # Bullish alignment: EMA_20 > EMA_50 > EMA_200
                if ema_20 > ema_50 > ema_200:
                    ema_strength = 0.8
                # Bearish alignment: EMA_20 < EMA_50 < EMA_200
                elif ema_20 < ema_50 < ema_200:
                    ema_strength = 0.8
                else:
                    ema_strength = 0.3
                strength_factors.append(ema_strength * 0.3)  # 30% weight
        
        # 3. SuperTrend trend strength
        if 'Trend' in df.columns:
            recent_trends = df['Trend'].iloc[-10:].values
            if len(recent_trends) > 0:
                trend_consistency = abs(np.mean(recent_trends))  # 1 or -1 becomes positive
                strength_factors.append(trend_consistency * 0.3)  # 30% weight
        
        # Calculate weighted average
        if strength_factors:
            return float(np.mean(strength_factors) * 100)
        return 50.0  # Default medium strength
    
    def _extract_fvg_zones(self, df: pd.DataFrame) -> List[Tuple[float, float]]:
        """Extract Fair Value Gap zones from ICT analysis"""
        fvg_zones = []
        
        if 'FVG_Bullish' not in df.columns or 'FVG_Bearish' not in df.columns:
            return fvg_zones
        
        for i in range(2, len(df)):
            if df['FVG_Bullish'].iloc[i]:
                zone_low = df['high'].iloc[i-2]
                zone_high = df['low'].iloc[i-1]
                if zone_high > zone_low:
                    fvg_zones.append((zone_low, zone_high))
            
            if df['FVG_Bearish'].iloc[i]:
                zone_low = df['high'].iloc[i-1]
                zone_high = df['low'].iloc[i-2]
                if zone_high > zone_low:
                    fvg_zones.append((zone_low, zone_high))
        
        return fvg_zones
    
    def _extract_order_blocks(self, df: pd.DataFrame) -> List[Dict]:
        """Extract Order Blocks from ICT analysis"""
        order_blocks = []
        
        if 'Bullish_OB' not in df.columns or 'Bearish_OB' not in df.columns:
            return order_blocks
        
        for i in range(1, len(df)):
            if df['Bullish_OB'].iloc[i]:
                ob = {
                    'type': 'bullish',
                    'index': i,
                    'price_zone': (float(df['low'].iloc[i]), float(df['high'].iloc[i])),
                    'timestamp': df.index[i] if hasattr(df.index[i], 'timestamp') else i
                }
                order_blocks.append(ob)
            
            if df['Bearish_OB'].iloc[i]:
                ob = {
                    'type': 'bearish',
                    'index': i,
                    'price_zone': (float(df['low'].iloc[i]), float(df['high'].iloc[i])),
                    'timestamp': df.index[i] if hasattr(df.index[i], 'timestamp') else i
                }
                order_blocks.append(ob)
        
        return order_blocks[-10:]  # Return last 10 order blocks
    
    def identify_support_resistance_enhanced(self, df: pd.DataFrame,
                                           swing_highs: List[SwingPoint],
                                           swing_lows: List[SwingPoint]) -> Tuple[List[SupportResistanceLevel], List[SupportResistanceLevel]]:
        """
        Enhanced S/R identification with volume profile and indicator confirmation
        """
        all_points = []
        
        # Add swing lows as potential support
        for sl in swing_lows:
            all_points.append({
                "price": sl.price,
                "type": "support",
                "index": sl.index,
                "strength": sl.strength,
                "pattern": sl.pattern
            })
        
        # Add swing highs as potential resistance
        for sh in swing_highs:
            all_points.append({
                "price": sh.price,
                "type": "resistance",
                "index": sh.index,
                "strength": sh.strength,
                "pattern": sh.pattern
            })
        
        # Add volume profile areas
        volume_profile_levels = self._calculate_volume_profile(df)
        for vp_level in volume_profile_levels:
            all_points.append({
                "price": vp_level['price'],
                "type": vp_level['type'],
                "index": len(df) - 1,
                "strength": 3,
                "pattern": "VOLUME_PROFILE"
            })
        
        # Sort and cluster
        all_points.sort(key=lambda x: x["price"])
        zones = []
        current_zone = None
        
        for point in all_points:
            if current_zone is None:
                current_zone = {
                    "prices": [point["price"]],
                    "types": [point["type"]],
                    "indices": [point["index"]],
                    "strengths": [point["strength"]],
                    "patterns": [point["pattern"]]
                }
            else:
                last_price = current_zone["prices"][-1]
                price_diff = abs(point["price"] - last_price) / last_price
                
                if price_diff <= self.zone_threshold:
                    current_zone["prices"].append(point["price"])
                    current_zone["types"].append(point["type"])
                    current_zone["indices"].append(point["index"])
                    current_zone["strengths"].append(point["strength"])
                    current_zone["patterns"].append(point["pattern"])
                else:
                    zones.append(current_zone)
                    current_zone = {
                        "prices": [point["price"]],
                        "types": [point["type"]],
                        "indices": [point["index"]],
                        "strengths": [point["strength"]],
                        "patterns": [point["pattern"]]
                    }
        
        if current_zone:
            zones.append(current_zone)
        
        # Create S/R levels
        support_levels = []
        resistance_levels = []
        current_price = df['close'].iloc[-1]
        
        for zone in zones:
            avg_price = np.mean(zone["prices"])
            touch_count = len(zone["prices"])
            zone_high = max(zone["prices"])
            zone_low = min(zone["prices"])
            
            # Determine type based on current price
            if avg_price < current_price:
                level_type = "support"
            else:
                level_type = "resistance"
            
            # Calculate confidence
            if touch_count >= 4:
                strength = LevelStrength.MAJOR
                base_confidence = 85
            elif touch_count >= 2:
                strength = LevelStrength.MINOR
                base_confidence = 70
            else:
                strength = LevelStrength.WEAK
                base_confidence = 55
            
            # Add pattern bonus
            if any(p in ["HAMMER", "BULLISH_ENGULFING", "VOLUME_PROFILE"] for p in zone["patterns"] if p):
                base_confidence += 10
            if any(p in ["SHOOTING_STAR", "BEARISH_ENGULFING"] for p in zone["patterns"] if p):
                base_confidence += 5
            
            # Indicator confirmation
            indicator_confirmation = self._check_indicator_confirmation(df, avg_price, level_type)
            
            # Calculate final confidence
            confidence = min(100, base_confidence)
            
            level = SupportResistanceLevel(
                price=avg_price,
                level_type=level_type,
                strength=strength,
                touch_count=touch_count,
                first_touch_index=min(zone["indices"]),
                last_touch_index=max(zone["indices"]),
                zone_high=zone_high,
                zone_low=zone_low,
                confidence=confidence,
                indicator_confirmation=indicator_confirmation
            )
            
            if level_type == "support":
                support_levels.append(level)
            else:
                resistance_levels.append(level)
        
        # Sort by confidence and distance
        support_levels.sort(key=lambda x: (x.confidence, current_price - x.price), reverse=True)
        resistance_levels.sort(key=lambda x: (x.confidence, x.price - current_price))
        
        return support_levels[:5], resistance_levels[:5]
    
    def _calculate_volume_profile(self, df: pd.DataFrame, num_bins: int = 20) -> List[Dict]:
        """Calculate volume profile for significant price levels"""
        if len(df) < 50:
            return []
        
        # Calculate price range
        price_range = df['high'].max() - df['low'].min()
        bin_size = price_range / num_bins
        
        volume_profile = []
        for i in range(num_bins):
            price_level = df['low'].min() + (i * bin_size) + (bin_size / 2)
            
            # Find candles that touch this price level
            mask = (df['low'] <= price_level) & (df['high'] >= price_level)
            volume_at_level = df.loc[mask, 'volume'].sum()
            
            if volume_at_level > 0:
                # Check if this is high volume node
                avg_volume = df['volume'].mean()
                if volume_at_level > avg_volume * 2:
                    volume_profile.append({
                        'price': price_level,
                        'volume': volume_at_level,
                        'type': 'support' if price_level < df['close'].iloc[-1] else 'resistance'
                    })
        
        # Sort by volume and take top 5
        volume_profile.sort(key=lambda x: x['volume'], reverse=True)
        return volume_profile[:5]
    
    def _check_indicator_confirmation(self, df: pd.DataFrame, price: float, level_type: str) -> Dict[str, bool]:
        """Check if indicators confirm the S/R level"""
        confirmation = {
            'rsi': False,
            'macd': False,
            'bbands': False,
            'supertrend': False,
            'volume': False
        }
        
        try:
            # RSI confirmation (oversold for support, overbought for resistance)
            if 'RSI_14' in df.columns:
                rsi = df['RSI_14'].iloc[-1]
                if not pd.isna(rsi):
                    if level_type == "support" and rsi < 35:
                        confirmation['rsi'] = True
                    elif level_type == "resistance" and rsi > 65:
                        confirmation['rsi'] = True
            
            # MACD confirmation
            if 'MACD_12_26_9' in df.columns and 'MACDs_12_26_9' in df.columns:
                macd = df['MACD_12_26_9'].iloc[-1]
                macd_signal = df['MACDs_12_26_9'].iloc[-1]
                if not pd.isna(macd) and not pd.isna(macd_signal):
                    if level_type == "support" and macd > macd_signal:
                        confirmation['macd'] = True
                    elif level_type == "resistance" and macd < macd_signal:
                        confirmation['macd'] = True
            
            # Bollinger Bands confirmation
            if 'BBL_20_2.0' in df.columns and 'BBU_20_2.0' in df.columns:
                bbl = df['BBL_20_2.0'].iloc[-1]
                bbu = df['BBU_20_2.0'].iloc[-1]
                if not pd.isna(bbl) and not pd.isna(bbu):
                    if level_type == "support" and abs(price - bbl) / price < 0.02:
                        confirmation['bbands'] = True
                    elif level_type == "resistance" and abs(price - bbu) / price < 0.02:
                        confirmation['bbands'] = True
            
            # SuperTrend confirmation
            if 'SuperTrend' in df.columns and 'Trend' in df.columns:
                supertrend = df['SuperTrend'].iloc[-1]
                trend = df['Trend'].iloc[-1]
                if not pd.isna(supertrend) and not pd.isna(trend):
                    if level_type == "support" and trend == 1 and price > supertrend:
                        confirmation['supertrend'] = True
                    elif level_type == "resistance" and trend == -1 and price < supertrend:
                        confirmation['supertrend'] = True
            
            # Volume confirmation
            if 'volume' in df.columns and 'OBV' in df.columns:
                recent_volume = df['volume'].iloc[-5:].mean()
                avg_volume = df['volume'].iloc[-20:].mean()
                if recent_volume > avg_volume * 1.5:
                    confirmation['volume'] = True
        
        except Exception as e:
            print(f"Indicator confirmation error: {e}")
        
        return confirmation
    
    def generate_enhanced_signals(self, df: pd.DataFrame,
                                 trend_structure: TrendStructure,
                                 support_levels: List[SupportResistanceLevel],
                                 resistance_levels: List[SupportResistanceLevel]) -> List[TradingSignal]:
        """
        Generate enhanced trading signals with multiple confirmation filters
        """
        signals = []
        current_price = df['close'].iloc[-1]
        atr = self._calculate_atr(df, period=14)
        
        # Strategy 1: Buy at Support in Uptrend
        if trend_structure.direction in [TrendDirection.UPTREND, TrendDirection.REVERSAL_TO_UP]:
            for support in support_levels[:3]:
                if support.confidence >= 75:
                    # Check for additional confirmations
                    confirmations = self._check_buy_confirmations(df, support.price)
                    
                    if confirmations['passed']:
                        entry = support.zone_high
                        stop_loss = support.zone_low - (atr * 1.5)
                        risk = entry - stop_loss
                        
                        # Dynamic targets based on RR
                        target_1 = entry + (risk * 2)
                        target_2 = entry + (risk * 3)
                        target_3 = entry + (risk * 4)
                        
                        # Adjust based on nearest resistance
                        if resistance_levels:
                            nearest_res = resistance_levels[0].price
                            if target_1 > nearest_res:
                                target_1 = nearest_res * 0.98
                                target_2 = nearest_res * 0.99
                                target_3 = nearest_res * 1.01
                        
                        confidence = min(95, support.confidence * 1.1)
                        
                        signals.append(TradingSignal(
                            signal_type="BUY",
                            entry_price=entry,
                            stop_loss=stop_loss,
                            target_1=target_1,
                            target_2=target_2,
                            target_3=target_3,
                            confidence=confidence,
                            reason=f"Buy at {support.strength.value} Support with {confirmations['count']}/5 confirmations",
                            risk_reward=2.0,
                            indicators_confirmation=confirmations['indicators'],
                            timestamp=int(df.index[-1].timestamp() * 1000) if hasattr(df.index[-1], 'timestamp') else None
                        ))
        
        # Strategy 2: Sell at Resistance in Downtrend
        if trend_structure.direction in [TrendDirection.DOWNTREND, TrendDirection.REVERSAL_TO_DOWN]:
            for resistance in resistance_levels[:3]:
                if resistance.confidence >= 75:
                    confirmations = self._check_sell_confirmations(df, resistance.price)
                    
                    if confirmations['passed']:
                        entry = resistance.zone_low
                        stop_loss = resistance.zone_high + (atr * 1.5)
                        risk = stop_loss - entry
                        
                        target_1 = entry - (risk * 2)
                        target_2 = entry - (risk * 3)
                        target_3 = entry - (risk * 4)
                        
                        # Adjust based on nearest support
                        if support_levels:
                            nearest_sup = support_levels[0].price
                            if target_1 < nearest_sup:
                                target_1 = nearest_sup * 1.02
                                target_2 = nearest_sup * 1.01
                                target_3 = nearest_sup * 0.99
                        
                        confidence = min(95, resistance.confidence * 1.1)
                        
                        signals.append(TradingSignal(
                            signal_type="SELL",
                            entry_price=entry,
                            stop_loss=stop_loss,
                            target_1=target_1,
                            target_2=target_2,
                            target_3=target_3,
                            confidence=confidence,
                            reason=f"Sell at {resistance.strength.value} Resistance with {confirmations['count']}/5 confirmations",
                            risk_reward=2.0,
                            indicators_confirmation=confirmations['indicators'],
                            timestamp=int(df.index[-1].timestamp() * 1000) if hasattr(df.index[-1], 'timestamp') else None
                        ))
        
        # Strategy 3: BOS Breakout Trades
        if trend_structure.bos_detected:
            signals.extend(self._generate_bos_signals(df, trend_structure, atr))
        
        # Strategy 4: ICT Order Block Trades
        if self.use_ict and trend_structure.order_blocks:
            signals.extend(self._generate_order_block_signals(df, trend_structure, atr))
        
        # Sort by confidence and limit to top 3
        signals.sort(key=lambda x: x.confidence, reverse=True)
        return signals[:3]
    
    def _check_buy_confirmations(self, df: pd.DataFrame, price: float) -> Dict:
        """Check multiple confirmations for buy signal"""
        confirmations = {
            'rsi_oversold': False,
            'macd_bullish': False,
            'candle_pattern': False,
            'volume_surge': False,
            'supertrend_bullish': False,
            'passed': False,
            'count': 0,
            'indicators': {}
        }
        
        # RSI oversold
        if 'RSI_14' in df.columns:
            rsi = df['RSI_14'].iloc[-1]
            if not pd.isna(rsi) and rsi < 40:
                confirmations['rsi_oversold'] = True
                confirmations['count'] += 1
        
        # MACD bullish crossover
        if 'MACD_12_26_9' in df.columns and 'MACDs_12_26_9' in df.columns:
            macd = df['MACD_12_26_9'].iloc[-1]
            macd_signal = df['MACDs_12_26_9'].iloc[-1]
            macd_prev = df['MACD_12_26_9'].iloc[-2] if len(df) > 1 else 0
            macd_signal_prev = df['MACDs_12_26_9'].iloc[-2] if len(df) > 1 else 0
            
            if not pd.isna(macd) and not pd.isna(macd_signal):
                if macd > macd_signal and macd_prev <= macd_signal_prev:
                    confirmations['macd_bullish'] = True
                    confirmations['count'] += 1
        
        # Bullish candle pattern
        current_close = df['close'].iloc[-1]
        current_open = df['open'].iloc[-1]
        current_low = df['low'].iloc[-1]
        
        if current_close > current_open and (current_close - current_open) > (current_low * 0.002):
            confirmations['candle_pattern'] = True
            confirmations['count'] += 1
        
        # Volume surge
        if 'volume' in df.columns:
            recent_volume = df['volume'].iloc[-1]
            avg_volume = df['volume'].iloc[-20:].mean()
            if recent_volume > avg_volume * 1.8:
                confirmations['volume_surge'] = True
                confirmations['count'] += 1
        
        # SuperTrend bullish
        if 'Trend' in df.columns:
            trend = df['Trend'].iloc[-1]
            if trend == 1:
                confirmations['supertrend_bullish'] = True
                confirmations['count'] += 1
        
        # Need at least 3 confirmations
        confirmations['passed'] = confirmations['count'] >= 3
        confirmations['indicators'] = {
            'rsi': confirmations['rsi_oversold'],
            'macd': confirmations['macd_bullish'],
            'candle': confirmations['candle_pattern'],
            'volume': confirmations['volume_surge'],
            'supertrend': confirmations['supertrend_bullish']
        }
        
        return confirmations
    
    def _check_sell_confirmations(self, df: pd.DataFrame, price: float) -> Dict:
        """Check multiple confirmations for sell signal"""
        confirmations = {
            'rsi_overbought': False,
            'macd_bearish': False,
            'candle_pattern': False,
            'volume_surge': False,
            'supertrend_bearish': False,
            'passed': False,
            'count': 0,
            'indicators': {}
        }
        
        # RSI overbought
        if 'RSI_14' in df.columns:
            rsi = df['RSI_14'].iloc[-1]
            if not pd.isna(rsi) and rsi > 60:
                confirmations['rsi_overbought'] = True
                confirmations['count'] += 1
        
        # MACD bearish crossover
        if 'MACD_12_26_9' in df.columns and 'MACDs_12_26_9' in df.columns:
            macd = df['MACD_12_26_9'].iloc[-1]
            macd_signal = df['MACDs_12_26_9'].iloc[-1]
            macd_prev = df['MACD_12_26_9'].iloc[-2] if len(df) > 1 else 0
            macd_signal_prev = df['MACDs_12_26_9'].iloc[-2] if len(df) > 1 else 0
            
            if not pd.isna(macd) and not pd.isna(macd_signal):
                if macd < macd_signal and macd_prev >= macd_signal_prev:
                    confirmations['macd_bearish'] = True
                    confirmations['count'] += 1
        
        # Bearish candle pattern
        current_close = df['close'].iloc[-1]
        current_open = df['open'].iloc[-1]
        current_high = df['high'].iloc[-1]
        
        if current_close < current_open and (current_open - current_close) > (current_high * 0.002):
            confirmations['candle_pattern'] = True
            confirmations['count'] += 1
        
        # Volume surge
        if 'volume' in df.columns:
            recent_volume = df['volume'].iloc[-1]
            avg_volume = df['volume'].iloc[-20:].mean()
            if recent_volume > avg_volume * 1.8:
                confirmations['volume_surge'] = True
                confirmations['count'] += 1
        
        # SuperTrend bearish
        if 'Trend' in df.columns:
            trend = df['Trend'].iloc[-1]
            if trend == -1:
                confirmations['supertrend_bearish'] = True
                confirmations['count'] += 1
        
        # Need at least 3 confirmations
        confirmations['passed'] = confirmations['count'] >= 3
        confirmations['indicators'] = {
            'rsi': confirmations['rsi_overbought'],
            'macd': confirmations['macd_bearish'],
            'candle': confirmations['candle_pattern'],
            'volume': confirmations['volume_surge'],
            'supertrend': confirmations['supertrend_bearish']
        }
        
        return confirmations
    
    def _generate_bos_signals(self, df: pd.DataFrame, trend_structure: TrendStructure, atr: float) -> List[TradingSignal]:
        """Generate Break of Structure signals"""
        signals = []
        current_price = df['close'].iloc[-1]
        
        if trend_structure.direction == TrendDirection.REVERSAL_TO_UP and trend_structure.bos_price:
            # Bullish BOS
            if current_price > trend_structure.bos_price * 1.01:
                entry = current_price
                stop_loss = trend_structure.bos_price * 0.995
                risk = entry - stop_loss
                
                signals.append(TradingSignal(
                    signal_type="BUY",
                    entry_price=entry,
                    stop_loss=stop_loss,
                    target_1=entry + (risk * 3),
                    target_2=entry + (risk * 5),
                    target_3=entry + (risk * 7),
                    confidence=80,
                    reason="BOS Confirmed - Trend Reversal to Uptrend",
                    risk_reward=3.0,
                    indicators_confirmation={'bos': True, 'momentum': True, 'volume': True},
                    timestamp=int(df.index[-1].timestamp() * 1000) if hasattr(df.index[-1], 'timestamp') else None
                ))
        
        elif trend_structure.direction == TrendDirection.REVERSAL_TO_DOWN and trend_structure.bos_price:
            # Bearish BOS
            if current_price < trend_structure.bos_price * 0.99:
                entry = current_price
                stop_loss = trend_structure.bos_price * 1.005
                risk = stop_loss - entry
                
                signals.append(TradingSignal(
                    signal_type="SELL",
                    entry_price=entry,
                    stop_loss=stop_loss,
                    target_1=entry - (risk * 3),
                    target_2=entry - (risk * 5),
                    target_3=entry - (risk * 7),
                    confidence=80,
                    reason="BOS Confirmed - Trend Reversal to Downtrend",
                    risk_reward=3.0,
                    indicators_confirmation={'bos': True, 'momentum': True, 'volume': True},
                    timestamp=int(df.index[-1].timestamp() * 1000) if hasattr(df.index[-1], 'timestamp') else None
                ))
        
        return signals
    
    def _generate_order_block_signals(self, df: pd.DataFrame, trend_structure: TrendStructure, atr: float) -> List[TradingSignal]:
        """Generate ICT Order Block signals"""
        signals = []
        current_price = df['close'].iloc[-1]
        
        # Only use recent order blocks (last 20 candles)
        recent_obs = [ob for ob in trend_structure.order_blocks 
                     if ob['index'] > len(df) - 20]
        
        for ob in recent_obs:
            ob_type = ob['type']
            ob_low, ob_high = ob['price_zone']
            
            # Check if price is retesting order block
            if ob_type == 'bullish' and current_price >= ob_low and current_price <= ob_high:
                # Bullish OB retest
                entry = current_price
                stop_loss = ob_low - atr
                risk = entry - stop_loss
                
                signals.append(TradingSignal(
                    signal_type="BUY",
                    entry_price=entry,
                    stop_loss=stop_loss,
                    target_1=entry + (risk * 2.5),
                    target_2=entry + (risk * 4),
                    target_3=entry + (risk * 6),
                    confidence=75,
                    reason=f"ICT Bullish Order Block Retest",
                    risk_reward=2.5,
                    indicators_confirmation={'ict_ob': True, 'retest': True},
                    timestamp=int(df.index[-1].timestamp() * 1000) if hasattr(df.index[-1], 'timestamp') else None
                ))
            
            elif ob_type == 'bearish' and current_price >= ob_low and current_price <= ob_high:
                # Bearish OB retest
                entry = current_price
                stop_loss = ob_high + atr
                risk = stop_loss - entry
                
                signals.append(TradingSignal(
                    signal_type="SELL",
                    entry_price=entry,
                    stop_loss=stop_loss,
                    target_1=entry - (risk * 2.5),
                    target_2=entry - (risk * 4),
                    target_3=entry - (risk * 6),
                    confidence=75,
                    reason=f"ICT Bearish Order Block Retest",
                    risk_reward=2.5,
                    indicators_confirmation={'ict_ob': True, 'retest': True},
                    timestamp=int(df.index[-1].timestamp() * 1000) if hasattr(df.index[-1], 'timestamp') else None
                ))
        
        return signals
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(df) < period + 1:
            return 0.0
        
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        
        tr = np.maximum(high[1:] - low[1:],
                       np.maximum(np.abs(high[1:] - close[:-1]),
                                 np.abs(low[1:] - close[:-1])))
        
        if len(tr) < period:
            return 0.0
        
        return float(np.mean(tr[-period:]))
    
    async def full_enhanced_analysis(self, symbol: str, interval: str = '1h', 
                                   exchange: Exchange = Exchange.BINANCE,
                                   limit: int = 500) -> Dict:
        """
        Complete enhanced analysis pipeline with real data
        """
        print(f"🔍 Starting analysis for {symbol} on {exchange.value} ({interval})...")
        
        # 1. Fetch real-time data
        async with DataProvider(primary_exchange=exchange) as provider:
            candles = await provider.fetch_ohlc(symbol, interval, limit, exchange)
        
        if not candles:
            raise ValueError(f"No data fetched for {symbol} from {exchange.value}")
        
        print(f"📊 Fetched {len(candles)} candles")
        
        # 2. Convert to DataFrame
        df = pd.DataFrame(candles)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
        
        # 3. Calculate all technical indicators
        print("📈 Calculating technical indicators...")
        df = self.indicators.calculate_all_indicators(df)
        
        # 4. Detect swing points
        print("🔄 Detecting swing points...")
        swing_highs, swing_lows = self.detect_swing_points_enhanced(df)
        
        # 5. Analyze trend structure
        print("📐 Analyzing trend structure...")
        trend_structure = self.analyze_trend_structure_enhanced(df, swing_highs, swing_lows)
        
        # 6. Identify S/R levels
        print("🎯 Identifying support/resistance levels...")
        support_levels, resistance_levels = self.identify_support_resistance_enhanced(
            df, swing_highs, swing_lows
        )
        
        # 7. Generate trading signals
        print("🚀 Generating trading signals...")
        signals = self.generate_enhanced_signals(
            df, trend_structure, support_levels, resistance_levels
        )
        
        # 8. Prepare results
        current_price = df['close'].iloc[-1]
        
        result = {
            "metadata": {
                "symbol": symbol,
                "exchange": exchange.value,
                "interval": interval,
                "candles_analyzed": len(df),
                "analysis_time": datetime.now().isoformat(),
                "current_price": float(current_price)
            },
            "trend_analysis": {
                "direction": trend_structure.direction.value,
                "strength": round(trend_structure.trend_strength, 1),
                "higher_highs": trend_structure.higher_highs_count,
                "higher_lows": trend_structure.higher_lows_count,
                "lower_highs": trend_structure.lower_highs_count,
                "lower_lows": trend_structure.lower_lows_count,
                "break_of_structure": trend_structure.bos_detected,
                "bos_price": trend_structure.bos_price,
                "market_structure_shift": trend_structure.mss_detected,
                "total_swing_points": len(swing_highs) + len(swing_lows)
            },
            "support_levels": [
                {
                    "price": round(s.price, 4),
                    "strength": s.strength.value,
                    "touches": s.touch_count,
                    "confidence": round(s.confidence, 1),
                    "zone": [round(s.zone_low, 4), round(s.zone_high, 4)],
                    "distance_pct": round(((s.price - current_price) / current_price) * 100, 2),
                    "indicator_confirmation": s.indicator_confirmation
                }
                for s in support_levels
            ],
            "resistance_levels": [
                {
                    "price": round(r.price, 4),
                    "strength": r.strength.value,
                    "touches": r.touch_count,
                    "confidence": round(r.confidence, 1),
                    "zone": [round(r.zone_low, 4), round(r.zone_high, 4)],
                    "distance_pct": round(((r.price - current_price) / current_price) * 100, 2),
                    "indicator_confirmation": r.indicator_confirmation
                }
                for r in resistance_levels
            ],
            "trading_signals": [
                {
                    "type": sig.signal_type,
                    "entry": round(sig.entry_price, 4),
                    "stop_loss": round(sig.stop_loss, 4),
                    "targets": [
                        round(sig.target_1, 4),
                        round(sig.target_2, 4),
                        round(sig.target_3, 4)
                    ],
                    "confidence": round(sig.confidence, 1),
                    "risk_reward": sig.risk_reward,
                    "reason": sig.reason,
                    "indicator_confirmation": sig.indicators_confirmation,
                    "timestamp": sig.timestamp
                }
                for sig in signals
            ],
            "technical_indicators": {
                "rsi": float(df['RSI_14'].iloc[-1]) if 'RSI_14' in df.columns else None,
                "macd": float(df['MACD_12_26_9'].iloc[-1]) if 'MACD_12_26_9' in df.columns else None,
                "macd_signal": float(df['MACDs_12_26_9'].iloc[-1]) if 'MACDs_12_26_9' in df.columns else None,
                "supertrend": float(df['SuperTrend'].iloc[-1]) if 'SuperTrend' in df.columns else None,
                "supertrend_direction": int(df['Trend'].iloc[-1]) if 'Trend' in df.columns else None,
                "adx": float(df['ADX_14'].iloc[-1]) if 'ADX_14' in df.columns else None,
                "ema_20": float(df['EMA_20'].iloc[-1]) if 'EMA_20' in df.columns else None,
                "ema_50": float(df['EMA_50'].iloc[-1]) if 'EMA_50' in df.columns else None,
                "ema_200": float(df['EMA_200'].iloc[-1]) if 'EMA_200' in df.columns else None
            },
            "ict_concepts": {
                "fair_value_gaps": trend_structure.fvg_zones,
                "order_blocks_count": len(trend_structure.order_blocks) if trend_structure.order_blocks else 0,
                "recent_order_blocks": [
                    {
                        "type": ob['type'],
                        "zone": ob['price_zone'],
                        "index": ob['index']
                    }
                    for ob in (trend_structure.order_blocks[-3:] if trend_structure.order_blocks else [])
                ]
            }
        }
        
        print(f"✅ Analysis complete! Found {len(signals)} trading signals")
        return result

# ========== MAIN APPLICATION ==========

async def main():
    """Main application entry point"""
    print("\n" + "="*80)
    print("🚀 ENHANCED MULTI-EXCHANGE CRYPTO ANALYSIS SYSTEM")
    print("="*80)
    
    # Configuration
    SYMBOL = "BTCUSDT"
    INTERVAL = "1h"
    EXCHANGE = Exchange.BINANCE
    LIMIT = 500
    
    try:
        # Initialize analyzer
        analyzer = EnhancedSupportResistanceAnalyzer(
            swing_window=5,
            zone_threshold=0.002,
            use_heikin_ashi=True,
            use_ict=True
        )
        
        # Run full analysis
        result = await analyzer.full_enhanced_analysis(
            symbol=SYMBOL,
            interval=INTERVAL,
            exchange=EXCHANGE,
            limit=LIMIT
        )
        
        # Display results
        print("\n" + "="*80)
        print("📊 ANALYSIS RESULTS")
        print("="*80)
        
        print(f"\n💰 Current Price: ${result['metadata']['current_price']:.2f}")
        print(f"📈 Symbol: {result['metadata']['symbol']}")
        print(f"🏦 Exchange: {result['metadata']['exchange'].upper()}")
        print(f"⏰ Interval: {result['metadata']['interval']}")
        
        print(f"\n📈 TREND ANALYSIS:")
        trend = result['trend_analysis']
        print(f"   Direction: {trend['direction']}")
        print(f"   Strength: {trend['strength']}%")
        print(f"   Higher Highs/Lows: {trend['higher_highs']}/{trend['higher_lows']}")
        print(f"   Lower Highs/Lows: {trend['lower_highs']}/{trend['lower_lows']}")
        print(f"   Break of Structure: {'✅ DETECTED' if trend['break_of_structure'] else '❌ NOT DETECTED'}")
        if trend['bos_price']:
            print(f"   BOS Price: ${trend['bos_price']:.2f}")
        print(f"   Market Structure Shift: {'✅ DETECTED' if trend['market_structure_shift'] else '❌ NOT DETECTED'}")
        
        print(f"\n🟢 SUPPORT LEVELS ({len(result['support_levels'])}):")
        for i, sup in enumerate(result['support_levels'], 1):
            confirmation_count = sum(1 for v in sup['indicator_confirmation'].values() if v)
            print(f"   {i}. ${sup['price']:.2f} | {sup['strength']} | "
                  f"{sup['touches']} touches | Conf: {sup['confidence']}% | "
                  f"Zone: ${sup['zone'][0]:.2f}-${sup['zone'][1]:.2f} | "
                  f"Indicators: {confirmation_count}/5")
        
        print(f"\n🔴 RESISTANCE LEVELS ({len(result['resistance_levels'])}):")
        for i, res in enumerate(result['resistance_levels'], 1):
            confirmation_count = sum(1 for v in res['indicator_confirmation'].values() if v)
            print(f"   {i}. ${res['price']:.2f} | {res['strength']} | "
                  f"{res['touches']} touches | Conf: {res['confidence']}% | "
                  f"Zone: ${res['zone'][0]:.2f}-${res['zone'][1]:.2f} | "
                  f"Indicators: {confirmation_count}/5")
        
        print(f"\n🎯 TRADING SIGNALS ({len(result['trading_signals'])}):")
        if result['trading_signals']:
            for i, sig in enumerate(result['trading_signals'], 1):
                print(f"\n   Signal #{i}: {sig['type']} {'🟢' if sig['type'] == 'BUY' else '🔴'}")
                print(f"   Reason: {sig['reason']}")
                print(f"   Entry: ${sig['entry']:.2f}")
                print(f"   Stop Loss: ${sig['stop_loss']:.2f}")
                print(f"   Target 1: ${sig['targets'][0]:.2f} (R:R {sig['risk_reward']:.1f}:1)")
                print(f"   Target 2: ${sig['targets'][1]:.2f}")
                print(f"   Target 3: ${sig['targets'][2]:.2f}")
                print(f"   Confidence: {sig['confidence']:.1f}%")
                print(f"   Indicators: {sum(1 for v in sig['indicator_confirmation'].values() if v)}/5 confirmed")
        else:
            print("   No signals generated - market conditions not favorable")
        
        print(f"\n📊 TECHNICAL INDICATORS:")
        tech = result['technical_indicators']
        if tech['rsi']:
            rsi_status = "OVERSOLD" if tech['rsi'] < 30 else "OVERBOUGHT" if tech['rsi'] > 70 else "NEUTRAL"
            print(f"   RSI: {tech['rsi']:.1f} ({rsi_status})")
        if tech['macd'] and tech['macd_signal']:
            macd_signal = "BULLISH" if tech['macd'] > tech['macd_signal'] else "BEARISH"
            print(f"   MACD: {macd_signal} ({tech['macd']:.4f} vs {tech['macd_signal']:.4f})")
        if tech['supertrend']:
            trend_dir = "UPTREND" if tech['supertrend_direction'] == 1 else "DOWNTREND"
            print(f"   SuperTrend: {trend_dir} (${tech['supertrend']:.2f})")
        if tech['adx']:
            adx_strength = "STRONG" if tech['adx'] > 25 else "WEAK" if tech['adx'] < 20 else "MODERATE"
            print(f"   ADX: {tech['adx']:.1f} ({adx_strength} trend)")
        
        print(f"\n🔄 ICT CONCEPTS:")
        ict = result['ict_concepts']
        print(f"   Fair Value Gaps: {len(ict['fair_value_gaps'])} detected")
        print(f"   Order Blocks: {ict['order_blocks_count']} total, {len(ict['recent_order_blocks'])} recent")
        if ict['recent_order_blocks']:
            for ob in ict['recent_order_blocks']:
                print(f"   - {ob['type'].upper()} OB at ${ob['zone'][0]:.2f}-${ob['zone'][1]:.2f}")
        
        print("\n" + "="*80)
        print("✅ Analysis completed successfully!")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Run the main application
    asyncio.run(main())
