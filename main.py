"""
ICT SMART PRO - VERSION 7.0
Production Optimized - GROK TRADE ELITE PATTERN ENGINE INTEGRATED
"""

import base64
import logging
import asyncio
import json
import hashlib
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional, Dict, List, Set, Any, Tuple, Union
from collections import defaultdict, deque

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from openai import OpenAI

# Configure logging for production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Suppress noisy logs
logging.getLogger("core").setLevel(logging.WARNING)
logging.getLogger("grok_indicators").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

logger = logging.getLogger("ict_smart_pro")

# Core modülleri - Import with error handling
try:
    from core import (
        initialize, cleanup, single_subscribers, all_subscribers, pump_radar_subscribers,
        shared_signals, active_strong_signals, top_gainers, last_update, rt_ticker,
        get_binance_client, price_sources_status, price_pool, get_all_prices_snapshot
    )
    from utils import all_usdt_symbols
    logger.info("✅ Core modülleri başarıyla yüklendi")
except ImportError as e:
    logger.warning(f"⚠️ Core modülleri import hatası: {e}")
    # Fallback fonksiyonlar
    initialize = lambda: asyncio.sleep(0)
    cleanup = lambda: asyncio.sleep(0)
    single_subscribers = defaultdict(set)
    all_subscribers = defaultdict(set)
    pump_radar_subscribers = set()
    shared_signals = {}
    active_strong_signals = {}
    top_gainers = []
    last_update = ""
    rt_ticker = ""
    get_binance_client = lambda: None
    price_sources_status = {}
    price_pool = {}
    get_all_prices_snapshot = lambda: {}
    all_usdt_symbols = []

# OpenAI
openai_client = None
if os.getenv("OPENAI_API_KEY"):
    try:
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        logger.info("✅ OpenAI client başlatıldı")
    except Exception as e:
        logger.warning(f"⚠️ OpenAI başlatma hatası: {e}")

# ==================== VISITOR COUNTER ====================

class VisitorCounter:
    def __init__(self):
        self.total_visits = 0
        self.active_users = set()
        self.daily_stats = defaultdict(lambda: {"visits": 0, "unique": set()})
        self.page_views = defaultdict(int)
        self.user_agents = defaultdict(int)
        self.referrers = defaultdict(int)

    def add_visit(self, page: str, user_id: Optional[str] = None, 
                  user_agent: Optional[str] = None, referrer: Optional[str] = None) -> int:
        self.total_visits += 1
        self.page_views[page] += 1
        
        today = datetime.now().strftime("%Y-%m-%d")
        self.daily_stats[today]["visits"] += 1
        
        if user_id:
            self.active_users.add(user_id)
            self.daily_stats[today]["unique"].add(user_id)
            
        return self.total_visits

    def get_stats(self) -> Dict[str, Any]:
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = self.daily_stats.get(today, {"visits": 0, "unique": set()})
        
        # En popüler sayfalar (max 5)
        top_pages = sorted(self.page_views.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            "total_visits": self.total_visits,
            "active_users": len(self.active_users),
            "today_visits": today_stats["visits"],
            "today_unique": len(today_stats["unique"]),
            "top_pages": dict(top_pages),
            "last_updated": datetime.now().strftime("%H:%M:%S")
        }

visitor_counter = VisitorCounter()

def get_visitor_stats_html() -> str:
    stats = visitor_counter.get_stats()
    return f"""
    <div style="position:fixed;top:15px;right:15px;background:#000000cc;padding:10px 20px;border-radius:20px;color:#00ff88;font-size:clamp(0.8rem, 2vw, 1.2rem);z-index:1000;backdrop-filter:blur(10px);border:1px solid #00ff8844;">
        <div>👁️ Toplam: <strong>{stats['total_visits']}</strong></div>
        <div>🔥 Bugün: <strong>{stats['today_visits']}</strong></div>
        <div>👥 Aktif: <strong>{stats['active_users']}</strong></div>
    </div>
    """

# ==================== GLOBAL STATE ====================

price_sources_subscribers = set()
signal_history = defaultdict(list)

# ==================== GROK TRADE ELITE INDICATORS (indicators.py içeriği buraya taşındı) ====================

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
        self.SIGNAL_THRESHOLD = 40
        
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
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()
    
    @staticmethod
    def calculate_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    @staticmethod
    def calculate_bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        sma = series.rolling(window=period, min_periods=1).mean()
        std = series.rolling(window=period, min_periods=1).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, sma, lower
    
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr
    
    @staticmethod
    def calculate_stochastic(df: pd.DataFrame, period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> Tuple[pd.Series, pd.Series]:
        low_min = df['low'].rolling(window=period).min()
        high_max = df['high'].rolling(window=period).max()
        k = 100 * ((df['close'] - low_min) / (high_max - low_min + 1e-10))
        k_smooth = k.rolling(window=smooth_k).mean()
        d_smooth = k_smooth.rolling(window=smooth_d).mean()
        return k_smooth, d_smooth
    
    @staticmethod
    def calculate_obv(df: pd.DataFrame) -> pd.Series:
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
    
    def detect_all_patterns(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        patterns = {}
        
        ha = self.calculate_heikin_ashi(df)
        ha_close = ha['ha_close']
        ha_range = ha['ha_high'] - ha['ha_low']
        
        rsi6 = self.calculate_rsi(ha_close, self.RSI6_PERIOD)
        rsi14 = self.calculate_rsi(ha_close, self.RSI14_PERIOD)
        sma50_rsi = self.calculate_sma(rsi6, self.SMA50_PERIOD)
        
        patterns['rsi6_crossover'] = (rsi6 > sma50_rsi) & (rsi6.shift(1) <= sma50_rsi.shift(1))
        patterns['rsi6_crossunder'] = (rsi6 < sma50_rsi) & (rsi6.shift(1) >= sma50_rsi.shift(1))
        
        patterns['rsi_oversold_6'] = rsi6 < 30
        patterns['rsi_overbought_6'] = rsi6 > 70
        patterns['rsi_oversold_14'] = rsi14 < 30
        patterns['rsi_overbought_14'] = rsi14 > 70
        
        patterns['rsi_bullish_div'] = (df['close'] < df['close'].shift(2)) & (rsi14 > rsi14.shift(2))
        patterns['rsi_bearish_div'] = (df['close'] > df['close'].shift(2)) & (rsi14 < rsi14.shift(2))
        
        macd_line, signal_line, histogram = self.calculate_macd(df['close'])
        patterns['macd_bullish_cross'] = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))
        patterns['macd_bearish_cross'] = (macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))
        patterns['macd_above_zero'] = macd_line > 0
        patterns['macd_below_zero'] = macd_line < 0
        
        sma50 = self.calculate_sma(df['close'], 50)
        sma200 = self.calculate_sma(df['close'], 200)
        ema9 = self.calculate_ema(df['close'], 9)
        ema21 = self.calculate_ema(df['close'], 21)
        
        patterns['golden_cross'] = (sma50 > sma200) & (sma50.shift(1) <= sma200.shift(1))
        patterns['death_cross'] = (sma50 < sma200) & (sma50.shift(1) >= sma200.shift(1))
        patterns['ema_bullish_cross'] = (ema9 > ema21) & (ema9.shift(1) <= ema21.shift(1))
        patterns['ema_bearish_cross'] = (ema9 < ema21) & (ema9.shift(1) >= ema21.shift(1))
        
        bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(df['close'])
        patterns['bb_oversold'] = df['close'] < bb_lower
        patterns['bb_overbought'] = df['close'] > bb_upper
        patterns['bb_squeeze'] = (bb_upper - bb_lower) < ((bb_upper - bb_lower).rolling(20).mean() * 0.5)
        
        stoch_k, stoch_d = self.calculate_stochastic(df)
        patterns['stoch_oversold'] = stoch_k < 20
        patterns['stoch_overbought'] = stoch_k > 80
        patterns['stoch_bullish_cross'] = (stoch_k > stoch_d) & (stoch_k.shift(1) <= stoch_d.shift(1))
        patterns['stoch_bearish_cross'] = (stoch_k < stoch_d) & (stoch_k.shift(1) >= stoch_d.shift(1))
        
        obv = self.calculate_obv(df)
        patterns['volume_spike'] = df['volume'] > (df['volume'].rolling(20).mean() * 2.5)
        patterns['obv_bullish_div'] = (df['close'] < df['close'].shift(2)) & (obv > obv.shift(2))
        patterns['obv_bearish_div'] = (df['close'] > df['close'].shift(2)) & (obv < obv.shift(2))
        
        avg_range = ha_range.rolling(5).mean()
        narrow_prev = ha_range.shift(1) < (avg_range.shift(1) * 1.5)
        wide_now = ha_range > (avg_range * 1.5)
        
        patterns['crt_buy'] = narrow_prev & wide_now & (ha_close > ha['ha_open']) & (ha_close > df['high'].shift(1))
        patterns['crt_sell'] = narrow_prev & wide_now & (ha_close < ha['ha_open']) & (ha_close < df['low'].shift(1))
        
        patterns['fvg_up'] = df['low'] > df['high'].shift(2)
        patterns['fvg_down'] = df['high'] < df['low'].shift(2)
        
        patterns['bull_ob'] = (df['close'].shift(1) < df['open'].shift(1)) & (df['close'] > df['high'].shift(1)) & (df['close'] > df['open'])
        patterns['bear_ob'] = (df['close'].shift(1) > df['open'].shift(1)) & (df['close'] < df['low'].shift(1)) & (df['close'] < df['open'])
        
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
        
        patterns['double_top'] = (df['high'] < df['high'].shift(1)) & (df['high'].shift(1) > df['high'].shift(2)) & \
                                (abs(df['high'].shift(1) - df['high']) < (df['high'].shift(1) * 0.02))
        
        patterns['double_bottom'] = (df['low'] > df['low'].shift(1)) & (df['low'].shift(1) < df['low'].shift(2)) & \
                                   (abs(df['low'].shift(1) - df['low']) < (df['low'].shift(1) * 0.02))
        
        patterns['support_bounce'] = (df['low'] > df['low'].rolling(20).min().shift(1)) & (df['close'] > df['open'])
        patterns['resistance_break'] = (df['high'] > df['high'].rolling(20).max().shift(1)) & (df['close'] > df['open'])
        
        if isinstance(df.index, pd.DatetimeIndex):
            hours = df.index.hour
        else:
            hours = pd.Series([datetime.utcnow().hour] * len(df))
            
        patterns['london_kz'] = (hours >= 7) & (hours < 10)
        patterns['ny_kz'] = (hours >= 13) & (hours < 16)
        patterns['asia_kz'] = (hours >= 0) & (hours < 4)
        patterns['in_killzone'] = patterns['london_kz'] | patterns['ny_kz'] | patterns['asia_kz']
        
        patterns['uptrend'] = df['close'] > sma50
        patterns['downtrend'] = df['close'] < sma50
        patterns['strong_uptrend'] = (df['close'] > sma50) & (sma50 > sma200)
        patterns['strong_downtrend'] = (df['close'] < sma50) & (sma50 < sma200)
        
        patterns['inside_bar'] = (df['high'] < df['high'].shift(1)) & (df['low'] > df['low'].shift(1))
        patterns['outside_bar'] = (df['high'] > df['high'].shift(1)) & (df['low'] < df['low'].shift(1))
        
        patterns['gaps_up'] = df['low'] > df['high'].shift(1)
        patterns['gaps_down'] = df['high'] < df['low'].shift(1)
        
        patterns['rsi6'] = rsi6
        patterns['rsi14'] = rsi14
        patterns['macd'] = macd_line
        patterns['macd_signal'] = signal_line
        patterns['sma50'] = sma50
        patterns['sma200'] = sma200
        patterns['volume'] = df['volume']
        
        return patterns
    
    def detect_fibonacci_levels(self, df: pd.DataFrame, ph: pd.Series, pl: pd.Series) -> pd.DataFrame:
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
    
    def calculate_signal_score(self, patterns: Dict[str, pd.Series]) -> int:
        score = 0
        idx = -1
        
        try:
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
                
        except Exception as e:
            logger.debug(f"Skor hesaplama hatası: {e}")
        
        return score
    
    def analyze_market_structure(self, df: pd.DataFrame) -> Dict[str, Any]:
        close = df['close']
        high = df['high']
        low = df['low']
        
        hh = (high > high.shift(1)) & (high.shift(1) > high.shift(2))
        ll = (low < low.shift(1)) & (low.shift(1) < low.shift(2))
        
        structure_bullish = hh.any() and not ll.any()
        structure_bearish = ll.any() and not hh.any()
        
        bos_bullish = structure_bullish and (close.iloc[-1] > high.rolling(20).max().iloc[-2])
        bos_bearish = structure_bearish and (close.iloc[-1] < low.rolling(20).min().iloc[-2])
        
        choch_bullish = structure_bearish and (close.iloc[-1] > high.rolling(10).max().iloc[-2])
        choch_bearish = structure_bullish and (close.iloc[-1] < low.rolling(10).min().iloc[-2])
        
        return {
            'market_structure': 'BULLISH' if structure_bullish else 'BEARISH' if structure_bearish else 'NEUTRAL',
            'bos': 'BULLISH' if bos_bullish else 'BEARISH' if bos_bearish else 'NONE',
            'choch': 'BULLISH' if choch_bullish else 'BEARISH' if choch_bearish else 'NONE',
            'higher_highs': int(hh.iloc[-1]) if len(hh) > 0 else 0,
            'lower_lows': int(ll.iloc[-1]) if len(ll) > 0 else 0
        }

# Global instance
grok = GrokIndicators()

def generate_ict_signal(df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    try:
        if len(df) < 50:
            logger.warning(f"{symbol}: Yetersiz veri ({len(df)})")
            return generate_technical_analysis(df, symbol, timeframe)

        required = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required):
            logger.error(f"{symbol}: Eksik sütun")
            return generate_technical_analysis(df, symbol, timeframe)

        df = df.copy()
        df = df.astype(float, errors='ignore')
        
        df['pivot_high'], df['pivot_low'] = grok.detect_pivots(df['high'], df['low'])
        
        _, poc_price, (va_low, va_high) = grok.calculate_volume_profile(df)
        
        patterns = grok.detect_all_patterns(df)
        
        df = grok.detect_fibonacci_levels(df, df['pivot_high'], df['pivot_low'])
        
        market_structure = grok.analyze_market_structure(df)
        
        signal_score = grok.calculate_signal_score(patterns)
        
        normalized_score = int(np.clip((signal_score + 150) * 100 / 300, 0, 100))
        
        last = df.iloc[-1]
        current_price = float(last['close'])
        
        active_patterns = []
        for pattern_name, pattern_series in patterns.items():
            if isinstance(pattern_series, pd.Series) and not pattern_name.startswith(('rsi', 'macd', 'sma', 'ema', 'volume')):
                if pattern_series.iloc[-1] and pattern_series.dtype == bool:
                    name = pattern_name.replace('_', ' ').title()
                    active_patterns.append(name)
        
        killzone = "London" if patterns.get('london_kz', pd.Series([False])).iloc[-1] else \
                  "New York" if patterns.get('ny_kz', pd.Series([False])).iloc[-1] else \
                  "Asia" if patterns.get('asia_kz', pd.Series([False])).iloc[-1] else "Normal"
        
        signal_strength = "ELITE" if normalized_score >= 85 else \
                         "GÜÇLÜ" if normalized_score >= 70 else \
                         "ORTA" if normalized_score >= 55 else "ZAYIF"
        
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
        
        structure_info = market_structure['market_structure']
        if market_structure['bos'] != 'NONE':
            structure_info += f" | BOS: {market_structure['bos']}"
        if market_structure['choch'] != 'NONE':
            structure_info += f" | ChoCH: {market_structure['choch']}"
        
        rsi6_val = float(patterns.get('rsi6', pd.Series([50])).iloc[-1])
        rsi14_val = float(patterns.get('rsi14', pd.Series([50])).iloc[-1])
        macd_val = float(patterns.get('macd', pd.Series([0])).iloc[-1])
        
        triggers = active_patterns[:8]
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
        return generate_technical_analysis(df, symbol, timeframe)

# ==================== ESKİ BASİT TEKNİK ANALİZ (fallback) ====================

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    
    try:
        deltas = prices.diff()
        gain = (deltas.where(deltas > 0, 0)).rolling(window=period).mean()
        loss = (-deltas.where(deltas < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50
    except:
        return 50

def calculate_macd(prices, fast=12, slow=26, signal=9):
    if len(prices) < slow + signal:
        return {"trend": "NÖTR"}
    
    try:
        exp1 = prices.ewm(span=fast, adjust=False).mean()
        exp2 = prices.ewm(span=slow, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        
        hist_value = histogram.iloc[-1]
        
        if hist_value > 0:
            trend = "YÜKSELİŞ"
        elif hist_value < 0:
            trend = "DÜŞÜŞ"
        else:
            trend = "NÖTR"
        
        return {"trend": trend}
    except:
        return {"trend": "NÖTR"}

def generate_technical_analysis(df, symbol, timeframe):
    if len(df) < 20:
        return None
    
    try:
        current_price = float(df['close'].iloc[-1])
        prev_price = float(df['close'].iloc[-2])
        change_pct = ((current_price - prev_price) / prev_price * 100) if prev_price > 0 else 0
        
        rsi_value = calculate_rsi(df['close'])
        macd_data = calculate_macd(df['close'])
        
        ma20 = df['close'].rolling(window=20).mean().iloc[-1] if len(df) >= 20 else current_price
        ma50 = df['close'].rolling(window=50).mean().iloc[-1] if len(df) >= 50 else current_price
        
        if current_price > ma20 > ma50:
            trend_strength = "GÜÇLÜ YÜKSELİŞ"
            trend_score = 80
        elif current_price < ma20 < ma50:
            trend_strength = "GÜÇLÜ DÜŞÜŞ"
            trend_score = 20
        elif current_price > ma20 and ma20 > ma50:
            trend_strength = "YÜKSELİŞ"
            trend_score = 70
        elif current_price < ma20 and ma20 < ma50:
            trend_strength = "DÜŞÜŞ"
            trend_score = 30
        else:
            trend_strength = "YATAY"
            trend_score = 50
        
        score = trend_score
        
        if rsi_value > 70:
            score -= 15
        elif rsi_value < 30:
            score += 15
        
        if macd_data['trend'] == "YÜKSELİŞ":
            score += 10
        elif macd_data['trend'] == "DÜŞÜŞ":
            score -= 10
        
        score = max(10, min(95, score))
        
        if score >= 70:
            signal_type = "🚀 GÜÇLÜ ALIM"
            strength = "YÜKSEK"
            color = "green"
        elif score >= 60:
            signal_type = "📈 ALIM"
            strength = "ORTA"
            color = "lightgreen"
        elif score <= 30:
            signal_type = "🔥 GÜÇLÜ SATIM"
            strength = "YÜKSEK"
            color = "red"
        elif score <= 40:
            signal_type = "📉 SATIM"
            strength = "ORTA"
            color = "lightcoral"
        else:
            signal_type = "⏸️ NÖTR"
            strength = "DÜŞÜK"
            color = "gold"
        
        now_utc = datetime.utcnow()
        hour = now_utc.hour
        
        if 7 <= hour < 11:
            killzone = "LONDRA"
        elif 12 <= hour < 16:
            killzone = "NEW YORK"
        elif 22 <= hour or hour < 2:
            killzone = "ASYA"
        else:
            killzone = "NORMAL"
        
        result = {
            "pair": f"{symbol}/USDT",
            "timeframe": timeframe.upper(),
            "current_price": round(current_price, 6 if current_price < 1 else 4),
            "signal": signal_type,
            "score": int(score),
            "strength": strength,
            "color": color,
            "killzone": killzone,
            "change_24h": round(change_pct, 2),
            "rsi": round(rsi_value, 1),
            "macd_trend": macd_data['trend'],
            "trend": trend_strength,
            "ma20": round(ma20, 6 if ma20 < 1 else 4),
            "ma50": round(ma50, 6 if ma50 < 1 else 4),
            "analysis_time": now_utc.strftime("%H:%M:%S UTC"),
            "timestamp": datetime.now().isoformat()
        }
        
        signal_key = f"{symbol}:{timeframe}"
        signal_history[signal_key].append(result)
        if len(signal_history[signal_key]) > 5:
            signal_history[signal_key] = signal_history[signal_key][-5:]
        
        return result
        
    except Exception as e:
        logger.error(f"Teknik analiz hatası: {e}")
        return None

# ==================== LIFESPAN ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 ICT SMART PRO başlatılıyor...")
    try:
        await initialize()
        logger.info("✅ Uygulama başarıyla başlatıldı")
    except Exception as e:
        logger.error(f"❌ Başlatma hatası: {e}")
    yield
    logger.info("🛑 Uygulama kapatılıyor...")
    try:
        await cleanup()
    except Exception as e:
        logger.error(f"❌ Kapatma hatası: {e}")

# ==================== FASTAPI APP ====================

app = FastAPI(
    lifespan=lifespan,
    title="ICT SMART PRO",
    version="7.0",
    description="Production Optimized Crypto Signal Platform",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# ==================== MIDDLEWARE ====================

@app.middleware("http")
async def count_visitors_middleware(request: Request, call_next):
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        ip = request.client.host or "anonymous"
        visitor_id = hashlib.md5(f"{ip}{datetime.now().strftime('%Y%m%d')}".encode()).hexdigest()[:12]
    
    page = request.url.path
    visitor_counter.add_visit(page, visitor_id)
    
    response = await call_next(request)
    
    if not request.cookies.get("visitor_id"):
        response.set_cookie(
            key="visitor_id", 
            value=visitor_id, 
            max_age=86400 * 30,
            httponly=True, 
            samesite="lax",
            secure=request.url.scheme == "https"
        )
    
    return response

# ==================== WEBSOCKET ENDPOINTS ====================

@app.websocket("/ws/price_sources")
async def websocket_price_sources(websocket: WebSocket):
    await websocket.accept()
    price_sources_subscribers.add(websocket)
    try:
        while True:
            try:
                await websocket.send_json({
                    "sources": price_sources_status, 
                    "total_symbols": len(price_pool),
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Price sources send error: {e}")
                break
            await asyncio.sleep(10)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Price sources error: {e}")
    finally:
        price_sources_subscribers.discard(websocket)

@app.websocket("/ws/signal/{pair}/{timeframe}")
async def websocket_signal(websocket: WebSocket, pair: str, timeframe: str):
    await websocket.accept()
    symbol = pair.upper().replace("/", "").replace("-", "").strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    channel = f"{symbol}:{timeframe}"
    single_subscribers[channel].add(websocket)
    
    sig = shared_signals.get(timeframe, {}).get(symbol)
    if sig:
        await websocket.send_json(sig)
    
    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"heartbeat": True, "timestamp": datetime.now().isoformat()})
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Signal WebSocket error: {e}")
    finally:
        single_subscribers[channel].discard(websocket)

@app.websocket("/ws/all/{timeframe}")
async def websocket_all_signals(websocket: WebSocket, timeframe: str):
    supported = ["5m", "15m", "1h", "4h", "1d"]
    
    if timeframe not in supported:
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    all_subscribers[timeframe].add(websocket)
    
    initial_signals = active_strong_signals.get(timeframe, [])[:20]
    await websocket.send_json(initial_signals)
    
    try:
        while True:
            await asyncio.sleep(60)
            await websocket.send_json({
                "ping": True, 
                "timestamp": datetime.now().isoformat()
            })
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"All signals WebSocket error: {e}")
    finally:
        all_subscribers[timeframe].discard(websocket)

@app.websocket("/ws/pump_radar")
async def websocket_pump_radar(websocket: WebSocket):
    await websocket.accept()
    pump_radar_subscribers.add(websocket)
    
    await websocket.send_json({
        "top_gainers": top_gainers[:10], 
        "last_update": last_update,
        "total_coins": len(top_gainers)
    })
    
    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({
                "ping": True,
                "timestamp": datetime.now().isoformat()
            })
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Pump radar WebSocket error: {e}")
    finally:
        pump_radar_subscribers.discard(websocket)

# ==================== HTML PAGES ====================

@app.get("/")
async def home_page(request: Request):
    user = request.cookies.get("user_email") or "Misafir"
    visitor_stats = get_visitor_stats_html()
    
    system_status = "🟢"
    binance_status = "🟢" if get_binance_client() else "🔴"
    
    html = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ICT SMART PRO</title>
        <style>
            body {{background: linear-gradient(135deg, #0a0022, #1a0033, #000); color: white; font-family: Arial, sans-serif; margin: 0; padding: 20px; min-height: 100vh;}}
            .container {{max-width: 1200px; margin: 0 auto;}}
            .header {{text-align: center; padding: 40px 0;}}
            .title {{font-size: 3rem; background: linear-gradient(90deg, #00dbde, #fc00ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 20px;}}
            .system-status {{display: flex; justify-content: center; gap: 20px; margin: 30px 0; padding: 20px; background: rgba(255, 255, 255, 0.05); border-radius: 15px;}}
            .status-item {{padding: 10px 20px; background: rgba(0, 0, 0, 0.3); border-radius: 10px;}}
            .pump-radar {{background: rgba(255, 255, 255, 0.05); border-radius: 20px; padding: 30px; margin: 40px 0;}}
            table {{width: 100%; border-collapse: collapse; margin: 20px 0;}}
            th {{background: rgba(0, 219, 222, 0.2); padding: 15px; text-align: left; color: #00ffff;}}
            td {{padding: 12px 15px; border-bottom: 1px solid rgba(255, 255, 255, 0.1);}}
            .change-positive {{ color: #00ff88; font-weight: bold; }}
            .change-negative {{ color: #ff4444; font-weight: bold; }}
            .buttons {{display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 40px 0;}}
            .btn {{padding: 25px; background: linear-gradient(45deg, #fc00ff, #00dbde); color: white; text-decoration: none; border-radius: 15px; text-align: center; font-size: 1.2rem; font-weight: bold; transition: transform 0.3s;}}
            .btn:hover {{transform: scale(1.05);}}
            .user-info {{position: fixed; top: 15px; left: 15px; background: rgba(0, 0, 0, 0.7); padding: 10px 20px; border-radius: 10px; color: #00ff88;}}
        </style>
    </head>
    <body>
        <div class="user-info">👤 {user}</div>
        {visitor_stats}
        
        <div class="container">
            <div class="header">
                <h1 class="title">ICT SMART PRO</h1>
                <div class="system-status">
                    <div class="status-item">Sistem: {system_status}</div>
                    <div class="status-item">Binance: {binance_status}</div>
                </div>
            </div>
            
            <div class="pump-radar">
                <h2 style="text-align:center;margin-bottom:20px;">🚀 PUMP RADAR</h2>
                <div id="update-info" style="text-align:center;color:#00ffff;margin:15px 0;">Yükleniyor...</div>
                <table>
                    <thead>
                        <tr>
                            <th>SIRA</th>
                            <th>COİN</th>
                            <th>FİYAT</th>
                            <th>DEĞİŞİM</th>
                        </tr>
                    </thead>
                    <tbody id="pump-table">
                        <tr><td colspan="4" style="text-align:center;padding:40px;">Yükleniyor...</td></tr>
                    </tbody>
                </table>
            </div>
            
            <div class="buttons">
                <a href="/signal" class="btn">📊 Tek Coin Sinyal + AI Analiz</a>
                <a href="/signal/all" class="btn">🔥 Tüm Coinleri Tara</a>
                <a href="/debug/sources" class="btn">🔧 Sistem Durumu</a>
            </div>
        </div>
        
        <script>
            const ws = new WebSocket((window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws/pump_radar');
            
            ws.onopen = function() {{
                document.getElementById('update-info').innerHTML = '✅ Bağlantı kuruldu';
            }};
            
            ws.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    if (data.ping) return;
                    
                    if (data.last_update) {{
                        document.getElementById('update-info').innerHTML = '🔄 ' + data.last_update;
                    }}
                    
                    const table = document.getElementById('pump-table');
                    if (!data.top_gainers || data.top_gainers.length === 0) {{
                        table.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:40px;color:#ffd700;">📊 Şu anda aktif pump yok</td></tr>';
                        return;
                    }}
                    
                    let html = '';
                    data.top_gainers.forEach(function(coin, index) {{
                        const changeClass = coin.change > 0 ? 'change-positive' : 'change-negative';
                        const changeSign = coin.change > 0 ? '+' : '';
                        
                        html += `
                            <tr>
                                <td>#${{index + 1}}</td>
                                <td><strong>${{coin.symbol}}</strong></td>
                                <td>$${{(coin.price >= 1 ? coin.price.toFixed(2) : coin.price.toFixed(6))}}</td>
                                <td class="${{changeClass}}">${{changeSign}}${{coin.change.toFixed(2)}}%</td>
                            </tr>
                        `;
                    }});
                    
                    table.innerHTML = html;
                    
                }} catch (error) {{
                    console.error('Hata:', error);
                }}
            }};
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)
#=============================================================
@app.get("/signal")
async def signal_page(request: Request):
    user = request.cookies.get("user_email")
    if not user:
        return RedirectResponse("/login")
    
    visitor_stats = get_visitor_stats_html()
    
    html = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Tek Coin Sinyal - ICT SMART PRO</title>
        <style>
            body {{
                background: linear-gradient(135deg, #0a0022, #1a0033, #000);
                color: white;
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                min-height: 100vh;
            }}
            .container {{
                max-width: 1000px;
                margin: 0 auto;
            }}
            .header {{
                text-align: center;
                padding: 30px 0;
            }}
            .title {{
                font-size: 2.5rem;
                background: linear-gradient(90deg, #00dbde, #fc00ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 20px;
            }}
            .controls {{
                background: rgba(255, 255, 255, 0.05);
                padding: 20px;
                border-radius: 10px;
                margin: 20px 0;
                text-align: center;
            }}
            button {{
                background: linear-gradient(45deg, #fc00ff, #00dbde);
                font-weight: bold;
                cursor: pointer;
                margin: 10px 5px;
                display: inline-block;
                width: auto;
                min-width: 200px;
                padding: 12px;
                border: none;
                border-radius: 8px;
                color: white;
                font-size: 1rem;
            }}
            .signal-card {{
                background: rgba(0, 0, 0, 0.5);
                padding: 30px;
                border-radius: 10px;
                margin: 30px 0;
                text-align: center;
                border-left: 5px solid #ffd700;
            }}
            .signal-card.green {{ border-left-color: #00ff88; }}
            .signal-card.red {{ border-left-color: #ff4444; }}
            .signal-text {{
                font-size: 2rem;
                font-weight: bold;
                margin-bottom: 15px;
            }}
            .ai-analysis {{
                background: rgba(13, 0, 51, 0.9);
                border-radius: 10px;
                padding: 25px;
                margin: 20px 0;
                border: 2px solid #00dbde;
                display: none;
            }}
            .chart-container {{
                width: 100%;
                height: 80vh;
                min-height: 1000px;
                background: rgba(10, 0, 34, 0.9);
                border-radius: 16px;
                margin: 30px 0;
                overflow: hidden;
                box-shadow: 0 0 30px rgba(0, 219, 222, 0.2);
            }}
            .navigation {{
                text-align: center;
                margin-top: 30px;
            }}
            .nav-link {{
                color: #00dbde;
                text-decoration: none;
                margin: 0 15px;
            }}
            .user-info {{
                position: fixed;
                top: 15px;
                left: 15px;
                background: rgba(0, 0, 0, 0.7);
                padding: 10px 20px;
                border-radius: 10px;
                color: #00ff88;
            }}

            /* COIN GİRİŞ KUTUSU - RENKLİ */
            input#pair {{
                background-color: #1a0033;
                color: #00ff88;
                border: 2px solid #00dbde;
                border-radius: 12px;
                padding: 14px 18px;
                font-size: 1.2rem;
                font-weight: bold;
                width: 100%;
                max-width: 400px;
                box-sizing: border-box;
                transition: all 0.3s ease;
            }}
            input#pair::placeholder {{
                color: #00dbdeaa;
                font-weight: normal;
            }}
            input#pair:focus {{
                outline: none;
                border-color: #fc00ff;
                background-color: #2a0044;
                box-shadow: 0 0 20px rgba(252, 0, 255, 0.5);
                color: #ffffff;
            }}
            input#pair:hover {{
                border-color: #fc00ff88;
                box-shadow: 0 0 15px rgba(252, 0, 255, 0.3);
            }}

            /* TIMEFRAME SELECT - RENKLİ */
            select#timeframe {{
                background-color: #1a0033;
                color: #00ff88;
                border: 2px solid #00dbde;
                border-radius: 12px;
                padding: 14px 40px 14px 18px;
                font-size: 1.2rem;
                font-weight: bold;
                min-width: 220px;
                appearance: none;
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='10' viewBox='0 0 14 10'%3E%3Cpath fill='%2300ff88' d='M1 1l6 6 6-6' stroke='%2300ff88' stroke-width='2'/%3E%3C/svg%3E");
                background-repeat: no-repeat;
                background-position: right 18px center;
                background-size: 14px;
                cursor: pointer;
                transition: all 0.3s ease;
            }}
            select#timeframe:hover {{
                background-color: #2a0044;
                border-color: #fc00ff;
                box-shadow: 0 0 15px rgba(252, 0, 255, 0.3);
            }}
            select#timeframe:focus {{
                outline: none;
                border-color: #fc00ff;
                box-shadow: 0 0 20px rgba(252, 0, 255, 0.5);
            }}
            select#timeframe option {{
                background-color: #0f0022;
                color: #ffffff;
                padding: 12px;
            }}
            select#timeframe option:hover {{
                background-color: #fc00ff !important;
                color: #000000 !important;
            }}
        </style>
        <script src="https://s3.tradingview.com/tv.js"></script>
    </head>
    <body>
        <div class="user-info">👤 {user}</div>
        {visitor_stats}
        
        <div class="container">
            <div class="header">
                <h1 class="title">📊 TEK COİN CANLI SİNYAL</h1>
            </div>
            
            <div class="controls">
                <input type="text" id="pair" placeholder="Coin (örn: BTC)" value="BTC">
                <select id="timeframe">
                    <option value="1m">1 Dakika</option>
                    <option value="3m">3 Dakika</option>
                    <option value="5m" selected>5 Dakika</option>
                    <option value="15m">15 Dakika</option>
                    <option value="30m">30 Dakika</option>
                    <option value="1h">1 Saat</option>
                    <option value="4h">4 Saat</option>
                    <option value="1d">1 Gün</option>
                    <option value="1W">1 Hafta</option>
                    <option value="1M">1 Ay</option>
                </select>
                <div>
                    <button onclick="connectSignal()">🔴 CANLI SİNYAL BAĞLANTISI KUR</button>
                    <button onclick="analyzeChartWithAI()" style="background:linear-gradient(45deg,#00dbde,#ff00ff);">🤖 GRAFİĞİ ANALİZ ET</button>
                </div>
                <div id="connection-status" style="color:#00ffff;margin:10px 0;">Bağlantı bekleniyor...</div>
            </div>
            
            <div id="signal-card" class="signal-card">
                <div id="signal-text" class="signal-text" style="color: #ffd700;">
                    Sinyal bağlantısı kurulmadı
                </div>
                <div id="signal-details">
                    Canlı sinyal için yukarıdaki butona tıklayın.
                </div>
            </div>
            
            <div id="ai-box" class="ai-analysis">
                <h3 style="color:#00dbde;text-align:center;">🤖 TEKNİK ANALİZ RAPORU</h3>
                <p id="ai-comment">Analiz için "Grafiği Analiz Et" butonuna tıklayın.</p>
            </div>
            
            <div class="chart-container">
                <div id="tradingview_widget"></div>
            </div>
            
            <div class="navigation">
                <a href="/" class="nav-link">← Ana Sayfa</a>
                <a href="/signal/all" class="nav-link">Tüm Coinler →</a>
            </div>
        </div>
        
        <script>
            let signalWs = null;
            let tradingViewWidget = null;
            let currentSymbol = "BTC";
            let currentTimeframe = "5m";
            
            const timeframeMap = {{
                "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
                "1h": "60", "4h": "240", "1d": "D", "1W": "W", "1M": "M"
            }};
            
            function getTradingViewSymbol(pair) {{
                let symbol = pair.trim().toUpperCase();
                if (!symbol.endsWith("USDT")) symbol += "USDT";
                return "BINANCE:" + symbol;
            }}
            
            function connectSignal() {{
                currentSymbol = document.getElementById('pair').value.trim().toUpperCase();
                currentTimeframe = document.getElementById('timeframe').value;
                const tvSymbol = getTradingViewSymbol(currentSymbol);
                const interval = timeframeMap[currentTimeframe] || "5";
                
                if (signalWs) {{ signalWs.close(); signalWs = null; }}
                if (tradingViewWidget) {{ tradingViewWidget.remove(); }}
                
                tradingViewWidget = new TradingView.widget({{
                    width: "100%",
                    height: "100%",
                    symbol: tvSymbol,
                    interval: interval,
                    timezone: "Etc/UTC",
                    theme: "dark",
                    style: "1",
                    locale: "tr",
                    container_id: "tradingview_widget",
                    overrides: {{
                        "paneProperties.backgroundType": "solid",
                        "paneProperties.background": "#000000",
                        "scalesProperties.textColor": "#FFFFFF",
                        "paneProperties.vertGridProperties.color": "#333333",
                        "paneProperties.horzGridProperties.color": "#333333"
                    }}
                }});
                
                const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
                signalWs = new WebSocket(protocol + window.location.host + '/ws/signal/' + currentSymbol + '/' + currentTimeframe);
                
                signalWs.onopen = function() {{
                    document.getElementById('connection-status').innerHTML = '✅ ' + currentSymbol + ' ' + currentTimeframe.toUpperCase() + ' canlı sinyal başladı!';
                }};
                
                signalWs.onmessage = function(event) {{
                    try {{
                        if (event.data.includes('heartbeat')) return;
                        const data = JSON.parse(event.data);
                        const card = document.getElementById('signal-card');
                        const text = document.getElementById('signal-text');
                        const details = document.getElementById('signal-details');
                        
                        text.innerHTML = data.signal || "⏸️ Sinyal bekleniyor...";
                        
                        details.innerHTML = `
                            <strong>${{data.pair || currentSymbol + '/USDT'}}</strong><br>
                            💰 Fiyat: <strong>$${{(data.current_price || 0).toFixed(data.current_price < 1 ? 6 : 4)}}</strong><br>
                            📊 Skor: <strong>${{data.score || '?'}} / 100</strong> | ${{data.killzone || 'Normal'}}
                        `;
                        
                        if (data.signal && (data.signal.includes('ALIM') || data.signal.includes('YÜKSELİŞ'))) {{
                            card.className = 'signal-card green';
                            text.style.color = '#00ff88';
                        }} else if (data.signal && (data.signal.includes('SATIM') || data.signal.includes('DÜŞÜŞ'))) {{
                            card.className = 'signal-card red';
                            text.style.color = '#ff4444';
                        }} else {{
                            card.className = 'signal-card';
                            text.style.color = '#ffd700';
                        }}
                    }} catch (e) {{ console.error(e); }}
                }};
            }}
            
            async function analyzeChartWithAI() {{
                const btn = document.querySelector('button[onclick="analyzeChartWithAI()"]');
                const box = document.getElementById('ai-box');
                const comment = document.getElementById('ai-comment');
                btn.disabled = true;
                btn.innerHTML = "⏳ Analiz ediliyor...";
                box.style.display = 'block';
                comment.innerHTML = "📊 Teknik analiz oluşturuluyor...";
                try {{
                    const response = await fetch('/api/analyze-chart', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ symbol: currentSymbol, timeframe: currentTimeframe }})
                    }});
                    const data = await response.json();
                    comment.innerHTML = data.success ? data.analysis.replace(/\\n/g, '<br>') : '<strong style="color:#ff4444">❌ Hata:</strong><br>' + data.analysis;
                }} catch (err) {{
                    comment.innerHTML = '<strong style="color:#ff4444">❌ Bağlantı hatası:</strong><br>' + err.message;
                }} finally {{
                    btn.disabled = false;
                    btn.innerHTML = "🤖 GRAFİĞİ ANALİZ ET";
                }}
            }}
            
            setTimeout(connectSignal, 1000);
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)
# ... (diğer sayfalar aynı kalıyor: /signal/all, /login, vs.)
@app.post("/api/analyze-chart")
async def analyze_chart_endpoint(request: Request):
    try:
        body = await request.json()
        symbol = body.get("symbol", "BTC").upper()
        timeframe = body.get("timeframe", "5m")
        
        logger.info(f"ELITE Analiz isteği: {symbol} @ {timeframe}")
        
        binance_client = get_binance_client()
        if not binance_client:
            return JSONResponse({
                "analysis": "❌ Binance bağlantısı aktif değil.",
                "success": False
            }, status_code=503)
        
        # DÜZELTME BURADA: Slash kaldır ve USDT ekle
        if symbol.endswith("/USDT"):
            symbol = symbol.replace("/USDT", "")
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        ccxt_symbol = symbol  # Artık BNBUSDT, BTCUSDT gibi doğru format
        
        interval_map = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
        ccxt_timeframe = interval_map.get(timeframe, "5m")
        
        try:
            klines = await binance_client.fetch_ohlcv(
                ccxt_symbol, 
                timeframe=ccxt_timeframe, 
                limit=300
            )
            
            if not klines or len(klines) < 50:
                return JSONResponse({
                    "analysis": f"❌ {symbol.replace('USDT', '')} için yeterli veri yok.",
                    "success": False
                }, status_code=404)
            
            df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume'])
            df.iloc[:,1:] = df.iloc[:,1:].apply(pd.to_numeric, errors='coerce')
            df = df.dropna()
            
            analysis = generate_ict_signal(df, symbol.replace("USDT", ""), timeframe)
            
            if not analysis:
                analysis = generate_technical_analysis(df, symbol.replace("USDT", ""), timeframe)
                if not analysis:
                    return JSONResponse({
                        "analysis": "Sinyal üretilemedi.",
                        "success": False
                    }, status_code=500)
            
            report = f"""
ELITE ANALİZ - {analysis['pair']} ({analysis['timeframe']})

{analysis['signal']}  Skor: {analysis['score']}/100 ({analysis['strength']})

Fiyat: ${analysis['current_price']}
Killzone: {analysis['killzone']}
Yapı: {analysis['structure']}

Tetikleyen Paternler:
{analysis['triggers']}

RSI6: {analysis['indicators'].get('rsi6', '?')} | RSI14: {analysis['indicators'].get('rsi14', '?')}
MACD: {analysis['indicators'].get('macd', '?'):.4f}

Saat: {analysis['last_update']}
"""
            
            return JSONResponse({
                "analysis": report.strip(),
                "signal_data": analysis,
                "success": True
            })
            
        except Exception as e:
            logger.error(f"Elite veri hatası ({ccxt_symbol}): {e}")
            return JSONResponse({
                "analysis": f"❌ Veri alınamadı: {str(e)}",
                "success": False
            }, status_code=404)
            
    except Exception as e:
        logger.error(f"Elite analiz hatası: {e}")
        return JSONResponse({
            "analysis": f"❌ Hata: {str(e)}",
            "success": False
        }, status_code=500)
# Diğer endpoint'ler (gpt-analyze, visitor-stats, vs.) aynı kalıyor...

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info(f"🚀 ICT SMART PRO v7.0 başlatılıyor... (GROK ELITE ENGINE ACTIVE)")
    logger.info(f"📡 Host: {host}:{port}")
    
    uvicorn.run(
        app, 
        host=host, 
        port=port, 
        log_level="info",
        access_log=False
    )





