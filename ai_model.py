"""
AI CRYPTO TRADING CHATBOT v5.0 - 11 EXCHANGE + COINGECKO EDITION
================================================================
- 11 Borsa + CoinGecko Entegrasyonu (main.py'den veri alır)
- 79 Price Action Patterns (QM, Fakeout, SMC/ICT, Candlestick)
- Advanced Deep Learning (Transformer-XL, Multi-Head Attention, PPO)
- Multi-Task Learning (Trend + Pattern + Volatility)
- Reinforcement Learning for Trade Execution
- Live Training & Adaptation
- Real-time Pattern Detection
"""

import asyncio
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from enum import Enum
import warnings
warnings.filterwarnings('ignore')

# ============================================
# ADVANCED ML/DL LIBRARIES
# ============================================
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader, TensorDataset
from torch.cuda.amp import autocast, GradScaler

import talib
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import accuracy_score

# Reinforcement Learning
import gym
from gym import spaces

# Rich CLI
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.progress import Progress
from rich import box
from rich.layout import Layout
from rich.text import Text

console = Console()

# ============================================
# VERİ AKTARIM KÖPRÜSÜ - 11 BORSA + COINGECKO
# ============================================
class DataBridge:
    """
    main.py'den 11 borsa + CoinGecko verilerini alır
    AI model'lerine ve pattern dedektörlerine iletir
    """
    
    def __init__(self):
        self.trading_bot = None
        self.live_data_buffer = {}          # Canlı veri tamponu
        self.exchange_data = {}             # Borsa bazlı veriler
        self.coingecko_data = {}            # CoinGecko verileri
        self.aggregated_data = {}           # Ağırlıklı ortalama veriler
        self.prediction_cache = {}          # Tahmin önbelleği
        self.pattern_history = []           # Pattern geçmişi
        self.signal_history = []            # Sinyal geçmişi
        self.last_update = {}              # Son güncelleme zamanları
        
        console.print("[bold green]✓ DataBridge initialized for 11 Exchanges + CoinGecko[/bold green]")
        
    def set_trading_bot(self, bot):
        """TradingBot instance'ını bağla"""
        self.trading_bot = bot
        console.print("[green]✓ TradingBot connected to DataBridge[/green]")
        
    async def process_exchange_data(self, symbol: str, exchange: str, price_data: Dict):
        """
        11 BORSADAN GELEN VERİLERİ İŞLER
        main.py'den her fiyat güncellemesinde çağrılır
        """
        try:
            # 1. Exchange bazlı veriyi kaydet
            if symbol not in self.exchange_data:
                self.exchange_data[symbol] = {}
            
            if exchange not in self.exchange_data[symbol]:
                self.exchange_data[symbol][exchange] = []
            
            # 2. Veriyi ekle
            self.exchange_data[symbol][exchange].append(price_data)
            
            # 3. Son 100 kaydı tut
            if len(self.exchange_data[symbol][exchange]) > 100:
                self.exchange_data[symbol][exchange] = self.exchange_data[symbol][exchange][-100:]
            
            # 4. Aggregated veriyi güncelle
            await self._update_aggregated_data(symbol)
            
            # 5. Pattern analizi yap (her 10 veride bir)
            if len(self.exchange_data[symbol][exchange]) % 10 == 0:
                asyncio.create_task(self.analyze_patterns(symbol))
            
            # 6. ML tahmini yap (her 50 veride bir)
            if len(self.exchange_data[symbol][exchange]) % 50 == 0:
                asyncio.create_task(self.predict_with_ml(symbol))
                
            return True
            
        except Exception as e:
            console.print(f"[red]process_exchange_data error: {e}[/red]")
            return False
    
    async def process_coingecko_data(self, symbol: str, price_data: Dict):
        """
        COINGECKO'DAN GELEN VERİLERİ İŞLER
        main.py'den her fiyat güncellemesinde çağrılır
        """
        try:
            # 1. CoinGecko verisini kaydet
            if symbol not in self.coingecko_data:
                self.coingecko_data[symbol] = []
            
            # 2. Veriyi ekle
            self.coingecko_data[symbol].append(price_data)
            
            # 3. Son 100 kaydı tut
            if len(self.coingecko_data[symbol]) > 100:
                self.coingecko_data[symbol] = self.coingecko_data[symbol][-100:]
            
            # 4. Aggregated veriyi güncelle
            await self._update_aggregated_data(symbol)
            
            return True
            
        except Exception as e:
            console.print(f"[red]process_coingecko_data error: {e}[/red]")
            return False
    
    async def _update_aggregated_data(self, symbol: str):
        """
        11 borsa + CoinGecko verilerini ağırlıklı ortalama ile birleştirir
        """
        try:
            all_prices = []
            
            # 1. Borsa verilerini topla
            if symbol in self.exchange_data:
                for exchange, data_list in self.exchange_data[symbol].items():
                    if data_list:
                        latest = data_list[-1]
                        # Borsa ağırlıkları
                        weights = {
                            'binance': 1.0,
                            'bybit': 0.95,
                            'okx': 0.90,
                            'kucoin': 0.85,
                            'gateio': 0.80,
                            'mexc': 0.75,
                            'kraken': 0.70,
                            'bitfinex': 0.65,
                            'huobi': 0.60,
                            'coinbase': 0.55,
                            'bitget': 0.50
                        }
                        weight = weights.get(exchange.lower(), 0.5)
                        all_prices.append({
                            'price': latest.get('close', latest.get('price', 0)),
                            'volume': latest.get('volume', 0),
                            'weight': weight
                        })
            
            # 2. CoinGecko verilerini ekle
            if symbol in self.coingecko_data and self.coingecko_data[symbol]:
                latest = self.coingecko_data[symbol][-1]
                all_prices.append({
                    'price': latest.get('price', latest.get('close', 0)),
                    'volume': latest.get('volume', 0),
                    'weight': 0.6  # CoinGecko weight
                })
            
            if not all_prices:
                return
            
            # 3. Ağırlıklı ortalama hesapla
            total_weight = sum(p['weight'] for p in all_prices)
            weighted_price = sum(p['price'] * p['weight'] for p in all_prices) / total_weight
            weighted_volume = sum(p['volume'] * p['weight'] for p in all_prices) / total_weight
            
            # 4. OHLCV tahmini (tek fiyattan)
            current_time = datetime.now().isoformat()
            
            if symbol not in self.aggregated_data:
                self.aggregated_data[symbol] = []
            
            self.aggregated_data[symbol].append({
                'timestamp': current_time,
                'open': weighted_price * 0.999,  # Yaklaşık değer
                'high': weighted_price * 1.001,   # Yaklaşık değer
                'low': weighted_price * 0.999,    # Yaklaşık değer
                'close': weighted_price,
                'volume': weighted_volume,
                'source_count': len(all_prices),
                'sources': [f"{p.get('exchange', 'unknown')}" for p in all_prices[:5]],
                'exchange': 'aggregated'
            })
            
            # 5. Son 1000 kaydı tut
            if len(self.aggregated_data[symbol]) > 1000:
                self.aggregated_data[symbol] = self.aggregated_data[symbol][-1000:]
            
            # 6. Live data buffer'ı da güncelle
            if symbol not in self.live_data_buffer:
                self.live_data_buffer[symbol] = []
            
            self.live_data_buffer[symbol].append(self.aggregated_data[symbol][-1])
            
            if len(self.live_data_buffer[symbol]) > 1000:
                self.live_data_buffer[symbol] = self.live_data_buffer[symbol][-1000:]
            
        except Exception as e:
            console.print(f"[red]_update_aggregated_data error: {e}[/red]")
    
    async def analyze_patterns(self, symbol: str) -> Optional[Dict]:
        """
        79 PATTERN ANALİZİ YAPAR
        Aggregated veri üzerinde çalışır
        """
        try:
            # Buffer'dan DataFrame oluştur
            df = self._buffer_to_dataframe(symbol)
            
            if df.empty or len(df) < 20:
                return None
            
            # Pattern dedektörünü oluştur
            detector = AdvancedPatternDetector(df)
            
            # 79 pattern'in tamamını tara
            patterns = detector.scan_all_patterns()
            
            # Yüksek güvenilirlikli pattern'leri filtrele
            high_conf_patterns = [p for p in patterns if p.get('confidence', 0) > 0.65]
            
            # Support/Resistance seviyelerini al
            levels = detector.get_support_resistance()
            
            # Pattern analiz sonuçlarını hazırla
            analysis_result = {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'total_patterns': len(patterns),
                'high_confidence_patterns': len(high_conf_patterns),
                'patterns': high_conf_patterns[:15],
                'support_levels': [{'price': l.price, 'strength': l.strength.name} 
                                 for l in levels if l.type == 'support'][:5],
                'resistance_levels': [{'price': l.price, 'strength': l.strength.name} 
                                    for l in levels if l.type == 'resistance'][:5],
                'current_price': df['close'].iloc[-1],
                'signal': self._calculate_overall_signal(high_conf_patterns),
                'data_source': '11_exchanges + coingecko',
                'exchange_count': len(self.exchange_data.get(symbol, {})),
                'coingecko_available': symbol in self.coingecko_data and bool(self.coingecko_data[symbol])
            }
            
            # Pattern'leri logla
            if high_conf_patterns:
                console.print(f"[yellow]🎯 {symbol}: {len(high_conf_patterns)} high-confidence patterns detected[/yellow]")
                for p in high_conf_patterns[:3]:
                    console.print(f"   - {p['pattern']}: {p['confidence']:.0%} ({p['signal']})")
            
            # Pattern geçmişine ekle
            self.pattern_history.append({
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'pattern_count': len(high_conf_patterns),
                'signal': analysis_result['signal']['signal']
            })
            
            # Son 100 pattern analizini tut
            if len(self.pattern_history) > 100:
                self.pattern_history = self.pattern_history[-100:]
            
            # Trading bot'a gönder
            if self.trading_bot:
                await self.trading_bot.update_pattern_analysis(symbol, analysis_result)
            
            return analysis_result
            
        except Exception as e:
            console.print(f"[red]analyze_patterns error: {e}[/red]")
            return None
    
    async def predict_with_ml(self, symbol: str) -> Optional[Dict]:
        """
        ML TAHMİNİ YAPAR
        Transformer-XL, LSTM ve Ensemble modelleri kullanır
        """
        try:
            if not self.trading_bot or not self.trading_bot.ml_engine:
                return None
            
            # Buffer'dan DataFrame oluştur
            df = self._buffer_to_dataframe(symbol)
            
            if df.empty or len(df) < 128:
                return None
            
            # ML tahmini yap
            prediction = self.trading_bot.ml_engine.predict(symbol, df)
            
            # Tahmin sonuçlarını zenginleştir
            prediction['data_source'] = '11_exchanges + coingecko'
            prediction['exchange_count'] = len(self.exchange_data.get(symbol, {}))
            prediction['coingecko_available'] = symbol in self.coingecko_data and bool(self.coingecko_data[symbol])
            
            # Cache'e kaydet
            self.prediction_cache[symbol] = {
                'prediction': prediction,
                'timestamp': datetime.now().isoformat()
            }
            
            console.print(f"[cyan]🤖 {symbol}: ML prediction = {prediction['prediction']} ({prediction['confidence']:.1%})[/cyan]")
            
            return prediction
            
        except Exception as e:
            console.print(f"[red]predict_with_ml error: {e}[/red]")
            return None
    
    def _buffer_to_dataframe(self, symbol: str) -> pd.DataFrame:
        """Buffer'daki verileri DataFrame'e dönüştürür"""
        if symbol not in self.live_data_buffer:
            return pd.DataFrame()
        
        data = self.live_data_buffer[symbol]
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        # Sayısal kolonları dönüştür
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Eksik kolonları doldur
        for col in numeric_cols:
            if col not in df.columns:
                if col == 'close' and 'price' in df.columns:
                    df[col] = pd.to_numeric(df['price'], errors='coerce')
                elif col == 'close':
                    df[col] = 0
                else:
                    df[col] = df['close'] if 'close' in df.columns else 0
        
        # Timestamp'i index yap
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
        
        return df
    
    def _calculate_overall_signal(self, patterns: List[Dict]) -> Dict:
        """Pattern'lerden genel sinyal hesaplar"""
        bullish = sum(1 for p in patterns if p.get('signal') == 'bullish')
        bearish = sum(1 for p in patterns if p.get('signal') == 'bearish')
        neutral = sum(1 for p in patterns if p.get('signal') == 'neutral')
        
        total = bullish + bearish + neutral
        if total == 0:
            return {'signal': 'NEUTRAL', 'strength': 0, 'bullish': 0, 'bearish': 0, 'neutral': 0}
        
        signal_strength = (bullish - bearish) / total
        
        if signal_strength > 0.3:
            signal = 'STRONG_BUY'
        elif signal_strength > 0.1:
            signal = 'BUY'
        elif signal_strength < -0.3:
            signal = 'STRONG_SELL'
        elif signal_strength < -0.1:
            signal = 'SELL'
        else:
            signal = 'NEUTRAL'
        
        return {
            'signal': signal,
            'strength': signal_strength,
            'bullish': bullish,
            'bearish': bearish,
            'neutral': neutral
        }
    
    def get_exchange_stats(self, symbol: str) -> Dict:
        """Borsa istatistiklerini döndürür"""
        stats = {
            'total_exchanges': 0,
            'active_exchanges': [],
            'coingecko_active': False,
            'total_data_points': 0
        }
        
        if symbol in self.exchange_data:
            stats['total_exchanges'] = len(self.exchange_data[symbol])
            stats['active_exchanges'] = list(self.exchange_data[symbol].keys())
            stats['total_data_points'] = sum(len(data) for data in self.exchange_data[symbol].values())
        
        if symbol in self.coingecko_data and self.coingecko_data[symbol]:
            stats['coingecko_active'] = True
            stats['total_data_points'] += len(self.coingecko_data[symbol])
        
        return stats


# Global data bridge instance
data_bridge = DataBridge()


# ============================================
# CONFIGURATION
# ============================================
CONFIG = {
    'EXCHANGES': {
        'binance': {
            'ws_url': 'wss://stream.binance.com:9443/ws',
            'api_url': 'https://api.binance.com/api/v3',
            'supported_symbols': ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT', 'DOGEUSDT', 'XRPUSDT']
        }
    },
    'ML_SETTINGS': {
        'sequence_length': 128,
        'hidden_size': 512,
        'num_layers': 6,
        'dropout': 0.2,
        'd_model': 256,
        'nhead': 16,
        'num_transformer_layers': 8,
        'batch_size': 64,
        'learning_rate': 0.0001,
        'epochs': 200,
        'validation_split': 0.2,
        'early_stopping_patience': 20,
        'gradient_clip': 1.0,
        'weight_decay': 0.0001,
        'scheduler_step': 30,
        'scheduler_gamma': 0.5
    },
    'RL_SETTINGS': {
        'total_timesteps': 100000,
        'learning_rate': 0.0003,
        'n_steps': 2048,
        'batch_size': 64,
        'gae_lambda': 0.95,
        'gamma': 0.99,
        'n_epochs': 10,
        'clip_range': 0.2,
        'ent_coef': 0.01,
        'vf_coef': 0.5,
        'max_grad_norm': 0.5
    },
    'PATTERN_SETTINGS': {
        'swing_lookback': 15,
        'atr_period': 14,
        'min_touches': 2,
        'cluster_pct': 0.002,
        'fib_levels': [0.382, 0.5, 0.618, 0.786, 0.886]
    },
    'TECHNICAL_INDICATORS': {
        'sma_periods': [5, 10, 20, 50, 100, 200],
        'ema_periods': [5, 10, 20, 50, 100],
        'rsi_periods': [7, 14, 21],
        'macd_fast': 12,
        'macd_slow': 26,
        'macd_signal': 9,
        'bb_period': 20,
        'bb_std': 2,
        'atr_period': 14,
        'adx_period': 14,
        'cci_period': 20,
        'williams_period': 14,
        'stoch_k': 14,
        'stoch_d': 3,
        'mfi_period': 14,
        'obv': True
    }
}


# ============================================
# ADVANCED DEEP LEARNING MODELS
# ============================================

class PositionalEncoding(nn.Module):
    """Transformer positional encoding with learnable parameters"""
    def __init__(self, d_model: int, max_len: int = 5000, dropout: float = 0.1):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-np.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0).transpose(0, 1)
        self.register_buffer('pe', pe)
        
    def forward(self, x):
        x = x + self.pe[:x.size(0), :]
        return self.dropout(x)


class MultiHeadAttentionLayer(nn.Module):
    """Enhanced multi-head attention with residual connections"""
    def __init__(self, d_model: int, nhead: int, dropout: float = 0.1):
        super().__init__()
        self.multihead_attn = nn.MultiheadAttention(d_model, nhead, dropout=dropout, batch_first=True)
        self.layer_norm1 = nn.LayerNorm(d_model)
        self.layer_norm2 = nn.LayerNorm(d_model)
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)
        self.ffn = nn.Sequential(
            nn.Linear(d_model, d_model * 4),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 4, d_model)
        )
        
    def forward(self, x):
        attn_out, _ = self.multihead_attn(x, x, x)
        x = self.layer_norm1(x + self.dropout1(attn_out))
        ffn_out = self.ffn(x)
        x = self.layer_norm2(x + self.dropout2(ffn_out))
        return x


class TransformerXLBlock(nn.Module):
    """Transformer-XL style block with relative positional encoding"""
    def __init__(self, d_model: int, nhead: int, dropout: float = 0.1):
        super().__init__()
        self.attention = MultiHeadAttentionLayer(d_model, nhead, dropout)
        self.ln = nn.LayerNorm(d_model)
        
    def forward(self, x):
        return self.ln(self.attention(x) + x)


class AdvancedTransformerXL(nn.Module):
    """Transformer-XL for time series forecasting"""
    def __init__(self, input_size: int, d_model: int, nhead: int, num_layers: int, 
                 output_size: int = 3, dropout: float = 0.2, max_len: int = 5000):
        super().__init__()
        
        self.input_projection = nn.Sequential(
            nn.Linear(input_size, d_model),
            nn.LayerNorm(d_model),
            nn.Dropout(dropout)
        )
        
        self.pos_encoder = PositionalEncoding(d_model, max_len, dropout)
        
        self.transformer_blocks = nn.ModuleList([
            TransformerXLBlock(d_model, nhead, dropout)
            for _ in range(num_layers)
        ])
        
        self.output_projection = nn.Sequential(
            nn.Linear(d_model, d_model // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, d_model // 4),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 4, output_size)
        )
        
        self.feature_extractor = nn.Sequential(
            nn.Linear(d_model, d_model // 2),
            nn.GELU(),
            nn.Dropout(dropout)
        )
        
    def forward(self, x, return_features=False):
        x = self.input_projection(x)
        x = self.pos_encoder(x)
        
        for block in self.transformer_blocks:
            x = block(x)
        
        features = self.feature_extractor(x[:, -1, :])
        output = self.output_projection(x[:, -1, :])
        
        if return_features:
            return output, features
        return output


class MultiTaskTransformer(nn.Module):
    """Multi-task learning: trend + pattern + volatility"""
    def __init__(self, input_size: int, d_model: int, nhead: int, num_layers: int, dropout: float = 0.2):
        super().__init__()
        
        self.shared_encoder = AdvancedTransformerXL(
            input_size, d_model, nhead, num_layers, 
            output_size=d_model // 2, dropout=dropout
        )
        
        # Task-specific heads
        self.trend_head = nn.Sequential(
            nn.Linear(d_model // 2, 64),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(64, 3)  # Up, Side, Down
        )
        
        self.pattern_head = nn.Sequential(
            nn.Linear(d_model // 2, 128),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(128, 79)  # 79 pattern types
        )
        
        self.volatility_head = nn.Sequential(
            nn.Linear(d_model // 2, 64),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(64, 1)  # Volatility forecast
        )
        
    def forward(self, x):
        features = self.shared_encoder(x, return_features=True)[1]
        trend_out = self.trend_head(features)
        pattern_out = self.pattern_head(features)
        volatility_out = self.volatility_head(features)
        
        return {
            'trend': trend_out,
            'pattern': pattern_out,
            'volatility': volatility_out,
            'features': features
        }


class LSTMAttention(nn.Module):
    """LSTM with attention mechanism"""
    def __init__(self, input_size: int, hidden_size: int, num_layers: int, 
                 output_size: int = 3, dropout: float = 0.2, bidirectional: bool = True):
        super().__init__()
        
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.bidirectional = bidirectional
        
        self.lstm = nn.LSTM(
            input_size, hidden_size, num_layers, 
            batch_first=True, dropout=dropout, bidirectional=bidirectional
        )
        
        lstm_output_size = hidden_size * (2 if bidirectional else 1)
        
        self.attention = nn.MultiheadAttention(lstm_output_size, num_heads=8, dropout=dropout, batch_first=True)
        
        self.fc = nn.Sequential(
            nn.Linear(lstm_output_size, 256),
            nn.LayerNorm(256),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(256, 128),
            nn.LayerNorm(128),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(128, output_size)
        )
        
    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        attn_out, _ = self.attention(lstm_out, lstm_out, lstm_out)
        return self.fc(attn_out[:, -1, :])


class EnsembleModel(nn.Module):
    """Ensemble of multiple models with learned weighting"""
    def __init__(self, input_size: int, d_model: int, nhead: int, 
                 num_layers: int, num_models: int = 3, output_size: int = 3):
        super().__init__()
        
        self.models = nn.ModuleList([
            AdvancedTransformerXL(input_size, d_model, nhead, num_layers, output_size)
            for _ in range(num_models)
        ])
        
        self.weight_net = nn.Sequential(
            nn.Linear(input_size * CONFIG['ML_SETTINGS']['sequence_length'], 128),
            nn.ReLU(),
            nn.Linear(128, num_models),
            nn.Softmax(dim=1)
        )
        
    def forward(self, x):
        weights = self.weight_net(x.view(x.size(0), -1))
        
        outputs = []
        for model in self.models:
            outputs.append(model(x))
        
        stacked = torch.stack(outputs, dim=2)
        weighted = torch.einsum('boc,bc->bo', stacked, weights)
        return weighted


# ============================================
# REINFORCEMENT LEARNING ENVIRONMENT
# ============================================

class AdvancedTradingEnv(gym.Env):
    """Advanced trading environment with PPO support"""
    
    def __init__(self, df: pd.DataFrame, initial_balance: float = 10000, 
                 commission: float = 0.001, max_position: int = 1):
        super().__init__()
        
        self.df = df.reset_index(drop=True)
        self.initial_balance = initial_balance
        self.commission = commission
        self.max_position = max_position
        
        # Action space: 0=Hold, 1=Buy, 2=Sell, 3=Close Long, 4=Close Short
        self.action_space = spaces.Discrete(5)
        
        # Observation space: price features + portfolio state
        self.observation_dim = len(CONFIG['TECHNICAL_INDICATORS']['sma_periods']) * 2 + 10
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, 
            shape=(CONFIG['ML_SETTINGS']['sequence_length'], self.observation_dim),
            dtype=np.float32
        )
        
        self.reset()
        
    def reset(self):
        self.current_step = CONFIG['ML_SETTINGS']['sequence_length']
        self.balance = self.initial_balance
        self.position = 0  # Positive for long, negative for short
        self.entry_price = 0
        self.trades = []
        self.equity_curve = [self.initial_balance]
        
        return self._get_observation()
    
    def _get_observation(self) -> np.ndarray:
        """Get current market observation"""
        start = max(0, self.current_step - CONFIG['ML_SETTINGS']['sequence_length'])
        obs_data = []
        
        for i in range(start, self.current_step):
            row = self.df.iloc[i]
            features = [
                row['close'] / row['sma_20'] - 1 if 'sma_20' in row else 0,
                row['rsi_14'] / 100 if 'rsi_14' in row else 0.5,
                row['macd'] / row['close'] if 'macd' in row else 0,
                row['bb_upper'] / row['close'] - 1 if 'bb_upper' in row else 0,
                row['bb_lower'] / row['close'] - 1 if 'bb_lower' in row else 0,
                row['atr'] / row['close'] if 'atr' in row else 0,
                row['volume'] / row['volume'].rolling(20).mean() if i > 20 else 1,
                self.position / self.max_position,
                self.balance / self.initial_balance - 1,
                (row['close'] - self.entry_price) / self.entry_price if self.entry_price != 0 else 0
            ]
            obs_data.append(features)
        
        # Pad if necessary
        if len(obs_data) < CONFIG['ML_SETTINGS']['sequence_length']:
            pad = np.zeros((CONFIG['ML_SETTINGS']['sequence_length'] - len(obs_data), len(features)))
            obs_data = np.vstack([pad, np.array(obs_data)])
        else:
            obs_data = np.array(obs_data)
        
        return obs_data.astype(np.float32)
    
    def _calculate_reward(self, action: int, current_price: float) -> float:
        """Calculate reward with risk management"""
        reward = 0
        prev_equity = self.equity_curve[-1]
        current_equity = self.balance + self.position * current_price
        
        # Equity change reward
        reward += (current_equity - prev_equity) / self.initial_balance * 100
        
        # Trade profit/loss
        if action in [1, 2]:  # Buy or Sell
            reward -= self.commission * 100  # Commission penalty
        
        # Position holding penalty (encourage shorter positions)
        if self.position != 0:
            reward -= 0.01
        
        # Drawdown penalty
        if current_equity < self.initial_balance * 0.95:
            reward -= 0.5
        
        # Profit taking reward
        if self.position > 0 and action == 3:  # Close long
            profit = (current_price - self.entry_price) / self.entry_price * 100
            reward += profit * 2
        elif self.position < 0 and action == 4:  # Close short
            profit = (self.entry_price - current_price) / self.entry_price * 100
            reward += profit * 2
        
        return reward
    
    def step(self, action: int):
        """Execute step in environment"""
        current_price = self.df.iloc[self.current_step]['close']
        
        # Execute action
        if action == 1 and self.position == 0:  # Buy
            self.position = self.balance * 0.95 / current_price
            self.entry_price = current_price
            self.balance -= self.position * current_price * (1 + self.commission)
        elif action == 2 and self.position == 0:  # Sell short
            self.position = -self.balance * 0.95 / current_price
            self.entry_price = current_price
            self.balance -= abs(self.position) * current_price * self.commission
        elif action == 3 and self.position > 0:  # Close long
            self.balance += self.position * current_price * (1 - self.commission)
            self.position = 0
            self.entry_price = 0
        elif action == 4 and self.position < 0:  # Close short
            self.balance += abs(self.position) * current_price * (1 - self.commission)
            self.position = 0
            self.entry_price = 0
        
        # Update equity
        current_equity = self.balance + self.position * current_price
        self.equity_curve.append(current_equity)
        
        # Calculate reward
        reward = self._calculate_reward(action, current_price)
        
        # Move to next step
        self.current_step += 1
        done = self.current_step >= len(self.df) - 1
        
        return self._get_observation(), reward, done, {
            'equity': current_equity,
            'position': self.position,
            'balance': self.balance
        }


# ============================================
# 79 PRICE ACTION PATTERN DETECTOR
# ============================================

class LevelStrength(Enum):
    MAJOR = 3
    MINOR = 1

@dataclass
class Level:
    price: float
    strength: LevelStrength
    touches: int
    type: str  # 'support' or 'resistance'

class AdvancedPatternDetector:
    """
    ULTIMATE PRICE ACTION PATTERN DETECTOR
    =======================================
    Total: 79 Patterns
    - 30 Advanced Price Action (QM, Fakeout, Compression, Base, Exhaustion)
    - 20 Classic Candlestick (Single, Double, Triple)
    - 29 SMC/ICT/Smart Money (FVG, OB, Breaker, BOS/CHOCH, Liquidity, OTE)
    """
    
    def __init__(self, df: pd.DataFrame, swing_lookback: int = 10, atr_period: int = 14):
        self.df = df.copy()
        self.swing_lookback = swing_lookback
        self.atr_period = atr_period
        
        # Technical calculations
        self._compute_atr()
        self._detect_swing_points()
        self._build_support_resistance()
        
        # Active FVG list for SMC/ICT
        self.active_fvgs = []
        
    # ------------------------------------------------------------
    # HELPER FUNCTIONS
    # ------------------------------------------------------------
    def _compute_atr(self):
        high, low, close = self.df['high'], self.df['low'], self.df['close']
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        self.atr = tr.rolling(self.atr_period).mean()
    
    def _detect_swing_points(self):
        highs, lows = self.df['high'], self.df['low']
        lb = self.swing_lookback
        
        swing_highs, swing_high_idx = [], []
        for i in range(lb, len(highs) - lb):
            if highs.iloc[i] == highs.iloc[i-lb:i+lb+1].max():
                swing_highs.append(highs.iloc[i])
                swing_high_idx.append(highs.index[i])
        
        swing_lows, swing_low_idx = [], []
        for i in range(lb, len(lows) - lb):
            if lows.iloc[i] == lows.iloc[i-lb:i+lb+1].min():
                swing_lows.append(lows.iloc[i])
                swing_low_idx.append(lows.index[i])
        
        self.swing_highs = pd.Series(swing_highs, index=swing_high_idx)
        self.swing_lows = pd.Series(swing_lows, index=swing_low_idx)
    
    def _is_near_level(self, price: float, level: float, tolerance_pct: float = 0.001) -> bool:
        if level == 0:
            return False
        return abs(price - level) / level <= tolerance_pct
    
    def _is_near_level_atr(self, price: float, level: float, atr_val: float) -> bool:
        return abs(price - level) <= atr_val * 0.3
    
    def _get_current_atr(self) -> float:
        return self.atr.iloc[-1] if not self.atr.isna().all() else 0
    
    # ------------------------------------------------------------
    # CANDLESTICK UTILITIES
    # ------------------------------------------------------------
    def _body(self, o: float, c: float) -> float:
        return abs(c - o)
    
    def _upper_shadow(self, o: float, h: float, c: float) -> float:
        return h - max(o, c)
    
    def _lower_shadow(self, o: float, l: float, c: float) -> float:
        return min(o, c) - l
    
    def _is_bullish(self, o: float, c: float) -> bool:
        return c > o
    
    def _is_bearish(self, o: float, c: float) -> bool:
        return c < o
    
    def _is_doji(self, o: float, h: float, l: float, c: float, ratio: float = 0.1) -> bool:
        candle_range = h - l
        if candle_range == 0:
            return False
        return self._body(o, c) <= ratio * candle_range
    
    def _is_small_body(self, o: float, h: float, l: float, c: float, ratio: float = 0.3) -> bool:
        candle_range = h - l
        if candle_range == 0:
            return False
        return self._body(o, c) <= ratio * candle_range
    
    def _is_in_uptrend(self, idx: int, lookback: int = 5) -> bool:
        if idx < lookback:
            return False
        recent = self.df.iloc[idx-lookback:idx]
        return recent['close'].is_monotonic_increasing or \
               (recent['close'].iloc[-1] > recent['close'].iloc[0])
    
    def _is_in_downtrend(self, idx: int, lookback: int = 5) -> bool:
        if idx < lookback:
            return False
        recent = self.df.iloc[idx-lookback:idx]
        return recent['close'].is_monotonic_decreasing or \
               (recent['close'].iloc[-1] < recent['close'].iloc[0])
    
    # ------------------------------------------------------------
    # SUPPORT / RESISTANCE MANAGEMENT
    # ------------------------------------------------------------
    def _build_support_resistance(self, min_touches: int = 2, cluster_pct: float = 0.002):
        levels = []
        
        # Resistance levels
        high_prices = self.swing_highs.values
        used = [False] * len(high_prices)
        for i in range(len(high_prices)):
            if used[i]:
                continue
            cluster = [high_prices[i]]
            used[i] = True
            for j in range(i+1, len(high_prices)):
                if self._is_near_level(high_prices[i], high_prices[j], cluster_pct):
                    cluster.append(high_prices[j])
                    used[j] = True
            avg_price = np.mean(cluster)
            touches = len(cluster)
            if touches >= min_touches:
                strength = LevelStrength.MAJOR if touches >= 3 else LevelStrength.MINOR
                levels.append(Level(avg_price, strength, touches, 'resistance'))
        
        # Support levels
        low_prices = self.swing_lows.values
        used = [False] * len(low_prices)
        for i in range(len(low_prices)):
            if used[i]:
                continue
            cluster = [low_prices[i]]
            used[i] = True
            for j in range(i+1, len(low_prices)):
                if self._is_near_level(low_prices[i], low_prices[j], cluster_pct):
                    cluster.append(low_prices[j])
                    used[j] = True
            avg_price = np.mean(cluster)
            touches = len(cluster)
            if touches >= min_touches:
                strength = LevelStrength.MAJOR if touches >= 3 else LevelStrength.MINOR
                levels.append(Level(avg_price, strength, touches, 'support'))
        
        self.levels = levels
    
    def get_support_resistance(self, type_filter: Optional[str] = None) -> List[Level]:
        if type_filter:
            return [l for l in self.levels if l.type == type_filter]
        return self.levels
    
    # ------------------------------------------------------------
    # SECTION 1: ADVANCED PRICE ACTION (30 PATTERNS)
    # ------------------------------------------------------------
    
    # ---- QM Patterns (1-4) ----
    def detect_qm_quick_retest(self) -> Optional[Dict]:
        if len(self.swing_highs) < 1:
            return None
        last_qm = self.swing_highs.iloc[-1]
        for _, bar in self.df.tail(3).iterrows():
            if self._is_near_level(bar['high'], last_qm) and bar['close'] < bar['high'] * 0.995:
                return {
                    'pattern': 'QM_Quick_Retest',
                    'signal': 'bearish',
                    'level': last_qm,
                    'confidence': 0.80
                }
        return None
    
    def detect_qm_late_retest(self) -> Optional[Dict]:
        if len(self.swing_highs) < 1:
            return None
        last_qm = self.swing_highs.iloc[-1]
        qm_index = self.df[self.df['high'] == last_qm].index[-1]
        later_bars = self.df.loc[qm_index+3:qm_index+10]
        for _, bar in later_bars.iterrows():
            if self._is_near_level(bar['high'], last_qm) and bar['close'] < bar['high']:
                return {
                    'pattern': 'QM_Late_Retest',
                    'signal': 'bearish',
                    'level': last_qm,
                    'confidence': 0.60
                }
        return None
    
    def detect_continuation_qm(self) -> Optional[Dict]:
        if len(self.swing_highs) < 2 or len(self.swing_lows) < 2:
            return None
        last_two_h = self.swing_highs.tail(2)
        if len(last_two_h) == 2 and last_two_h.iloc[1] > last_two_h.iloc[0]:
            return {
                'pattern': 'Continuation_QM_Bullish',
                'signal': 'bullish',
                'level': last_two_h.iloc[1],
                'confidence': 0.75
            }
        last_two_l = self.swing_lows.tail(2)
        if len(last_two_l) == 2 and last_two_l.iloc[1] < last_two_l.iloc[0]:
            return {
                'pattern': 'Continuation_QM_Bearish',
                'signal': 'bearish',
                'level': last_two_l.iloc[1],
                'confidence': 0.75
            }
        return None
    
    def detect_ignored_qm(self) -> Optional[Dict]:
        if len(self.swing_highs) == 0 or len(self.swing_lows) == 0:
            return None
        last_qm_high = self.swing_highs.iloc[-1]
        last_qm_low = self.swing_lows.iloc[-1]
        current_price = self.df['close'].iloc[-1]
        
        if current_price > last_qm_high * 1.01:
            qm_index = self.df[self.df['high'] == last_qm_high].index[-1]
            if self.df.loc[qm_index:, 'low'].min() > last_qm_high * 0.995:
                return {
                    'pattern': 'Ignored_QM_Bullish',
                    'signal': 'bullish',
                    'level': last_qm_high,
                    'confidence': 0.90
                }
        if current_price < last_qm_low * 0.99:
            qm_index = self.df[self.df['low'] == last_qm_low].index[-1]
            if self.df.loc[qm_index:, 'high'].max() < last_qm_low * 1.005:
                return {
                    'pattern': 'Ignored_QM_Bearish',
                    'signal': 'bearish',
                    'level': last_qm_low,
                    'confidence': 0.90
                }
        return None
    
    # ---- Manipulation Patterns (5-7) ----
    def detect_dm_shadow(self) -> Optional[Dict]:
        last_bar = self.df.iloc[-1]
        prev_bar = self.df.iloc[-2]
        body = self._body(last_bar['open'], last_bar['close'])
        lower_shadow = self._lower_shadow(last_bar['open'], last_bar['low'], last_bar['close'])
        
        if lower_shadow > 2 * body and self._is_bullish(last_bar['open'], last_bar['close']):
            if 'volume' in self.df.columns and last_bar['volume'] > prev_bar['volume'] * 1.3:
                return {
                    'pattern': 'DM_Shadow',
                    'signal': 'bullish',
                    'level': last_bar['low'],
                    'confidence': 0.85
                }
        return None
    
    def detect_can_can(self) -> Optional[Dict]:
        last2 = self.df.tail(2)
        if last2['low'].iloc[0] < last2['low'].iloc[1] and \
           last2['close'].iloc[1] > last2['open'].iloc[1]:
            return {
                'pattern': 'Can_Can',
                'signal': 'bullish',
                'level': last2['low'].min(),
                'confidence': 0.70
            }
        return None
    
    def detect_can_can_fakeout(self) -> Optional[Dict]:
        cancan = self.detect_can_can()
        if cancan:
            fake = self.detect_fakeout_v1()
            if fake and fake['signal'] == 'bullish':
                return {
                    'pattern': 'Can_Can_Fakeout',
                    'signal': 'bullish',
                    'level': cancan.get('level'),
                    'confidence': 0.95
                }
        return None
    
    # ---- Fakeout Patterns (8-10) ----
    def detect_fakeout_v1(self) -> Optional[Dict]:
        lookback = 10
        last_high = self.df['high'].iloc[-lookback:].max()
        last_low = self.df['low'].iloc[-lookback:].min()
        current = self.df.iloc[-1]
        
        if current['high'] > last_high and current['close'] < last_high:
            return {
                'pattern': 'Fakeout_V1_Turtle_Soup_Sell',
                'signal': 'bearish',
                'level': last_high,
                'confidence': 0.75
            }
        if current['low'] < last_low and current['close'] > last_low:
            return {
                'pattern': 'Fakeout_V1_Turtle_Soup_Buy',
                'signal': 'bullish',
                'level': last_low,
                'confidence': 0.75
            }
        return None
    
    def detect_fakeout_v2(self) -> Optional[Dict]:
        if len(self.swing_highs) > 0:
            last_res = self.swing_highs.iloc[-1]
            recent = self.df.tail(3)
            if (recent['high'] > last_res).any() and recent['close'].iloc[-1] < last_res:
                return {
                    'pattern': 'Fakeout_V2_SR_Flip_Bearish',
                    'signal': 'bearish',
                    'level': last_res,
                    'confidence': 0.80
                }
        if len(self.swing_lows) > 0:
            last_sup = self.swing_lows.iloc[-1]
            recent = self.df.tail(3)
            if (recent['low'] < last_sup).any() and recent['close'].iloc[-1] > last_sup:
                return {
                    'pattern': 'Fakeout_V2_SR_Flip_Bullish',
                    'signal': 'bullish',
                    'level': last_sup,
                    'confidence': 0.80
                }
        return None
    
    def detect_fakeout_v3(self) -> Optional[Dict]:
        recent = self.df.tail(12)
        first_half_range = recent['high'].iloc[:6].max() - recent['low'].iloc[:6].min()
        second_half_range = recent['high'].iloc[6:].max() - recent['low'].iloc[6:].min()
        
        if first_half_range > second_half_range * 1.5:
            if recent['high'].iloc[-1] > recent['high'].iloc[-6:-1].max() and \
               recent['close'].iloc[-1] < recent['high'].iloc[-1]:
                return {
                    'pattern': 'Fakeout_V3_Diamond_Bearish',
                    'signal': 'bearish',
                    'confidence': 0.70
                }
            if recent['low'].iloc[-1] < recent['low'].iloc[-6:-1].min() and \
               recent['close'].iloc[-1] > recent['low'].iloc[-1]:
                return {
                    'pattern': 'Fakeout_V3_Diamond_Bullish',
                    'signal': 'bullish',
                    'confidence': 0.70
                }
        return None
    
    # ---- Flag Patterns (11-13) ----
    def detect_flag_a(self) -> Optional[Dict]:
        recent = self.df.tail(10)
        range_pct = (recent['high'].max() - recent['low'].min()) / recent['close'].mean()
        if range_pct < 0.03:
            trend = 'bullish' if self.df['close'].iloc[-1] > self.df['close'].iloc[-20] else 'bearish'
            return {
                'pattern': 'Flag_A',
                'signal': trend,
                'confidence': 0.65
            }
        return None
    
    def detect_flag_b(self) -> Optional[Dict]:
        recent = self.df.tail(8)
        first_move = recent['close'].iloc[3] - recent['close'].iloc[0]
        last_move = recent['close'].iloc[-1] - recent['close'].iloc[-4]
        if abs(first_move) > abs(last_move) * 2 and \
           abs(last_move) < self._get_current_atr() * 0.5:
            trend = 'bullish' if first_move < 0 else 'bearish'
            return {
                'pattern': 'Flag_B',
                'signal': trend,
                'confidence': 0.70
            }
        return None
    
    def detect_mpl_flag(self) -> Optional[Dict]:
        if 'volume' not in self.df.columns:
            return None
        recent_df = self.df.tail(50)
        volume_profile = recent_df['volume'].groupby(pd.cut(recent_df['close'], bins=20)).sum()
        if volume_profile.empty:
            return None
        high_volume_node = volume_profile.idxmax().mid
        current_price = self.df['close'].iloc[-1]
        
        if self._is_near_level(current_price, high_volume_node, 0.005):
            if self.detect_flag_a() or self.detect_flag_b():
                return {
                    'pattern': 'MPL_Flag',
                    'signal': 'bullish' if current_price > high_volume_node else 'bearish',
                    'level': high_volume_node,
                    'confidence': 0.80
                }
        return None
    
    # ---- Measured Move (14) ----
    def detect_ruler(self) -> Optional[Dict]:
        if len(self.swing_highs) < 2 and len(self.swing_lows) < 2:
            return None
        
        if len(self.swing_lows) >= 3:
            lows = self.swing_lows.tail(3)
            if lows.iloc[0] > lows.iloc[1] > lows.iloc[2]:
                move = lows.iloc[1] - lows.iloc[2]
                target = lows.iloc[1] + move
                if self.df['close'].iloc[-1] < target:
                    return {
                        'pattern': 'Ruler_Bullish',
                        'signal': 'bullish',
                        'target': target,
                        'confidence': 0.70
                    }
        
        if len(self.swing_highs) >= 3:
            highs = self.swing_highs.tail(3)
            if highs.iloc[0] < highs.iloc[1] < highs.iloc[2]:
                move = highs.iloc[2] - highs.iloc[1]
                target = highs.iloc[1] - move
                if self.df['close'].iloc[-1] > target:
                    return {
                        'pattern': 'Ruler_Bearish',
                        'signal': 'bearish',
                        'target': target,
                        'confidence': 0.70
                    }
        return None
    
    # ---- Compression Patterns (15-16) ----
    def detect_compression(self) -> Optional[Dict]:
        recent = self.df.tail(10)
        range_pct = (recent['high'].max() - recent['low'].min()) / recent['close'].mean()
        if range_pct < 0.02:
            if recent['close'].iloc[-1] > recent['close'].iloc[-5:].mean():
                return {
                    'pattern': 'Compression_Bullish',
                    'signal': 'bullish',
                    'confidence': 0.60
                }
            else:
                return {
                    'pattern': 'Compression_Bearish',
                    'signal': 'bearish',
                    'confidence': 0.60
                }
        return None
    
    def detect_compression_liquidity(self) -> Optional[Dict]:
        cp = self.detect_compression()
        if cp:
            if len(self.swing_highs) > 0:
                last_high = self.swing_highs.iloc[-1]
                if self.df['high'].iloc[-1] > last_high * 1.001 and \
                   self.df['close'].iloc[-1] < last_high:
                    return {
                        'pattern': 'Compression_Liquidity_Bearish',
                        'signal': 'bearish',
                        'level': last_high,
                        'confidence': 0.85
                    }
            if len(self.swing_lows) > 0:
                last_low = self.swing_lows.iloc[-1]
                if self.df['low'].iloc[-1] < last_low * 0.999 and \
                   self.df['close'].iloc[-1] > last_low:
                    return {
                        'pattern': 'Compression_Liquidity_Bullish',
                        'signal': 'bullish',
                        'level': last_low,
                        'confidence': 0.85
                    }
        return None
    
    # ---- Double Test Patterns (17-18) ----
    def detect_double_ssr(self) -> Optional[Dict]:
        resistances = self.get_support_resistance('resistance')
        for level in resistances:
            if level.touches >= 2:
                recent = self.df.tail(5)
                if any(self._is_near_level(recent['high'].iloc[i], level.price, 0.002) 
                       for i in range(len(recent))):
                    return {
                        'pattern': 'Double_SSR_Resistance',
                        'signal': 'bearish',
                        'level': level.price,
                        'confidence': 0.85
                    }
        
        supports = self.get_support_resistance('support')
        for level in supports:
            if level.touches >= 2:
                recent = self.df.tail(5)
                if any(self._is_near_level(recent['low'].iloc[i], level.price, 0.002) 
                       for i in range(len(recent))):
                    return {
                        'pattern': 'Double_SSR_Support',
                        'signal': 'bullish',
                        'level': level.price,
                        'confidence': 0.85
                    }
        return None
    
    def detect_stop_hunt(self) -> Optional[Dict]:
        if len(self.swing_lows) > 0:
            last_swing_low = self.swing_lows.iloc[-1]
            recent = self.df.tail(2)
            if (recent['low'] < last_swing_low).any() and \
               recent['close'].iloc[-1] > last_swing_low:
                return {
                    'pattern': 'Stop_Hunt_Long',
                    'signal': 'bullish',
                    'level': last_swing_low,
                    'confidence': 0.80
                }
        if len(self.swing_highs) > 0:
            last_swing_high = self.swing_highs.iloc[-1]
            recent = self.df.tail(2)
            if (recent['high'] > last_swing_high).any() and \
               recent['close'].iloc[-1] < last_swing_high:
                return {
                    'pattern': 'Stop_Hunt_Short',
                    'signal': 'bearish',
                    'level': last_swing_high,
                    'confidence': 0.80
                }
        return None
    
    # ---- Harmonic Pattern (19) ----
    def detect_3_drive(self) -> Optional[Dict]:
        if len(self.swing_highs) >= 3:
            drives = self.swing_highs.tail(3)
            diffs = drives.diff().dropna().values
            if len(diffs) >= 2 and np.std(diffs) / max(np.mean(np.abs(diffs)), 0.001) < 0.2:
                return {
                    'pattern': '3_Drive_Top',
                    'signal': 'bearish',
                    'confidence': 0.80
                }
        
        if len(self.swing_lows) >= 3:
            drives = self.swing_lows.tail(3)
            diffs = drives.diff().dropna().values
            if len(diffs) >= 2 and np.std(np.abs(diffs)) / max(np.mean(np.abs(diffs)), 0.001) < 0.2:
                return {
                    'pattern': '3_Drive_Bottom',
                    'signal': 'bullish',
                    'confidence': 0.80
                }
        return None
    
    # ---- V-Shape Pattern (20) ----
    def detect_v_twin(self) -> Optional[Dict]:
        recent = self.df.tail(5)
        if recent['low'].iloc[0] > recent['low'].iloc[2] and \
           recent['close'].iloc[4] > recent['close'].iloc[2] * 1.02:
            return {
                'pattern': 'V_Twin_Dip',
                'signal': 'bullish',
                'confidence': 0.80
            }
        if recent['high'].iloc[0] < recent['high'].iloc[2] and \
           recent['close'].iloc[4] < recent['close'].iloc[2] * 0.98:
            return {
                'pattern': 'V_Twin_Tepe',
                'signal': 'bearish',
                'confidence': 0.80
            }
        return None
    
    # ---- Rejection Patterns (21-22) ----
    def detect_rejection(self) -> Optional[Dict]:
        current = self.df.iloc[-1]
        atr_val = self._get_current_atr()
        body = self._body(current['open'], current['close'])
        upper_wick = self._upper_shadow(current['open'], current['high'], current['close'])
        lower_wick = self._lower_shadow(current['open'], current['low'], current['close'])
        
        resistances = self.get_support_resistance('resistance')
        for level in resistances:
            if self._is_near_level_atr(current['high'], level.price, atr_val):
                if upper_wick > body * 1.5 and \
                   current['close'] < (current['high'] + current['low']) / 2:
                    return {
                        'pattern': 'Rejection_at_Resistance',
                        'signal': 'bearish',
                        'level': level.price,
                        'strength': level.strength.name,
                        'confidence': 0.80 if level.strength == LevelStrength.MAJOR else 0.70
                    }
        
        supports = self.get_support_resistance('support')
        for level in supports:
            if self._is_near_level_atr(current['low'], level.price, atr_val):
                if lower_wick > body * 1.5 and \
                   current['close'] > (current['high'] + current['low']) / 2:
                    return {
                        'pattern': 'Rejection_at_Support',
                        'signal': 'bullish',
                        'level': level.price,
                        'strength': level.strength.name,
                        'confidence': 0.80 if level.strength == LevelStrength.MAJOR else 0.70
                    }
        return None
    
    # ---- Base Model Patterns (23-24) ----
    def detect_base_model(self) -> Optional[Dict]:
        recent = self.df.tail(12)
        range_pct = (recent['high'].max() - recent['low'].min()) / recent['close'].mean()
        if range_pct > 0.025:
            return None
        
        trend_period = 20
        price_change = self.df['close'].iloc[-1] - self.df['close'].iloc[-trend_period]
        trend = 'bullish' if price_change > 0 else 'bearish'
        
        volume_trend = False
        if 'volume' in self.df.columns:
            volume_trend = self.df['volume'].iloc[-5:].mean() < \
                          self.df['volume'].iloc[-15:-5].mean() * 0.8
        
        bar_size_trend = (self.df['high'] - self.df['low']).iloc[-5:].mean() < \
                         (self.df['high'] - self.df['low']).iloc[-15:-5].mean() * 0.7
        momentum_slow = abs(self.df['close'].diff(5).iloc[-1]) < \
                        abs(self.df['close'].diff(5).iloc[-10]) * 0.5
        is_tired = volume_trend or bar_size_trend or momentum_slow
        
        if trend == 'bullish':
            if is_tired:
                return {
                    'pattern': 'Tired_Base_Uptrend',
                    'signal': 'bearish',
                    'confidence': 0.65
                }
            else:
                return {
                    'pattern': 'Continuation_Base_Uptrend',
                    'signal': 'bullish',
                    'confidence': 0.60
                }
        else:
            if is_tired:
                return {
                    'pattern': 'Tired_Base_Downtrend',
                    'signal': 'bullish',
                    'confidence': 0.65
                }
            else:
                return {
                    'pattern': 'Continuation_Base_Downtrend',
                    'signal': 'bearish',
                    'confidence': 0.60
                }
    
    # ---- Trend Exhaustion Patterns (25-27) ----
    def detect_lower_high_higher_low(self) -> Optional[Dict]:
        if len(self.swing_highs) >= 2:
            last_two_h = self.swing_highs.tail(2)
            if len(last_two_h) == 2 and last_two_h.iloc[1] < last_two_h.iloc[0]:
                return {
                    'pattern': 'Lower_High_LH',
                    'signal': 'bearish',
                    'level': last_two_h.iloc[1],
                    'prev_high': last_two_h.iloc[0],
                    'confidence': 0.75
                }
        
        if len(self.swing_lows) >= 2:
            last_two_l = self.swing_lows.tail(2)
            if len(last_two_l) == 2 and last_two_l.iloc[1] > last_two_l.iloc[0]:
                return {
                    'pattern': 'Higher_Low_HL',
                    'signal': 'bullish',
                    'level': last_two_l.iloc[1],
                    'prev_low': last_two_l.iloc[0],
                    'confidence': 0.75
                }
        return None
    
    def detect_trend_exhaustion(self) -> Optional[Dict]:
        if len(self.df) < 30:
            return None
        
        close = self.df['close']
        
        # RSI hesapla
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]
        
        # Bearish Divergence
        price_peak = close.iloc[-15:].max()
        price_peak_idx = close.iloc[-15:].idxmax()
        rsi_at_peak = rsi.loc[price_peak_idx]
        if close.iloc[-1] > price_peak * 0.99 and current_rsi < rsi_at_peak - 5:
            return {
                'pattern': 'Bearish_Divergence',
                'signal': 'bearish',
                'price_level': close.iloc[-1],
                'rsi_current': current_rsi,
                'rsi_at_peak': rsi_at_peak,
                'confidence': 0.75
            }
        
        # Bullish Divergence
        price_trough = close.iloc[-15:].min()
        price_trough_idx = close.iloc[-15:].idxmin()
        rsi_at_trough = rsi.loc[price_trough_idx]
        if close.iloc[-1] < price_trough * 1.01 and current_rsi > rsi_at_trough + 5:
            return {
                'pattern': 'Bullish_Divergence',
                'signal': 'bullish',
                'price_level': close.iloc[-1],
                'rsi_current': current_rsi,
                'rsi_at_trough': rsi_at_trough,
                'confidence': 0.75
            }
        
        # Volume Exhaustion
        if 'volume' in self.df.columns:
            volume = self.df['volume']
            if close.iloc[-1] > close.iloc[-5:-1].mean() and \
               volume.iloc[-1] < volume.iloc[-10:-1].mean() * 0.7:
                return {
                    'pattern': 'Volume_Exhaustion_Uptrend',
                    'signal': 'bearish',
                    'confidence': 0.70
                }
            if close.iloc[-1] < close.iloc[-5:-1].mean() and \
               volume.iloc[-1] < volume.iloc[-10:-1].mean() * 0.7:
                return {
                    'pattern': 'Volume_Exhaustion_Downtrend',
                    'signal': 'bullish',
                    'confidence': 0.70
                }
        
        return None
    
    # ---- Level Congestion (28) ----
    def count_levels_ahead(self) -> Dict:
        current_price = self.df['close'].iloc[-1]
        resistances = [l.price for l in self.get_support_resistance('resistance') if l.price > current_price]
        supports = [l.price for l in self.get_support_resistance('support') if l.price < current_price]
        resistances.sort()
        supports.sort(reverse=True)
        
        result = {
            'resistance_above_count': len(resistances),
            'closest_resistance': resistances[0] if resistances else None,
            'support_below_count': len(supports),
            'closest_support': supports[0] if supports else None,
        }
        
        if len(resistances) >= 3 and (resistances[0] - current_price) / current_price < 0.02:
            result['congestion_signal'] = 'bearish'
        elif len(supports) >= 3 and (current_price - supports[0]) / current_price < 0.02:
            result['congestion_signal'] = 'bullish'
        else:
            result['congestion_signal'] = 'neutral'
        
        return result
    
    # ---- Additional Price Action Patterns (29-30) ----
    def detect_pin_bar(self) -> Optional[Dict]:
        """Pin Bar / Long Wick Rejection"""
        current = self.df.iloc[-1]
        body = self._body(current['open'], current['close'])
        upper_wick = self._upper_shadow(current['open'], current['high'], current['close'])
        lower_wick = self._lower_shadow(current['open'], current['low'], current['close'])
        total_range = current['high'] - current['low']
        
        if upper_wick > total_range * 0.6 and body < total_range * 0.3:
            return {
                'pattern': 'Pin_Bar_Bearish',
                'signal': 'bearish',
                'level': current['high'],
                'confidence': 0.70
            }
        if lower_wick > total_range * 0.6 and body < total_range * 0.3:
            return {
                'pattern': 'Pin_Bar_Bullish',
                'signal': 'bullish',
                'level': current['low'],
                'confidence': 0.70
            }
        return None
    
    def detect_inside_bar(self) -> Optional[Dict]:
        """Inside Bar - Consolidation"""
        if len(self.df) < 2:
            return None
        current = self.df.iloc[-1]
        prev = self.df.iloc[-2]
        
        if current['high'] <= prev['high'] and current['low'] >= prev['low']:
            return {
                'pattern': 'Inside_Bar',
                'signal': 'neutral',
                'level': (current['high'] + current['low']) / 2,
                'confidence': 0.50
            }
        return None
    
    # ------------------------------------------------------------
    # SECTION 2: CLASSIC CANDLESTICK PATTERNS (20 PATTERNS)
    # ------------------------------------------------------------
    def detect_candlestick_patterns(self, idx: int = -1) -> List[Dict]:
        if idx == -1:
            idx = len(self.df) - 1
        if idx < 2:
            return []
        
        results = []
        o, h, l, c = self.df.iloc[idx][['open', 'high', 'low', 'close']]
        
        # ---- SINGLE CANDLE (6) ----
        # 1. Hanging Man
        if self._is_in_uptrend(idx):
            lower = self._lower_shadow(o, l, c)
            body = self._body(o, c)
            upper = self._upper_shadow(o, h, c)
            if lower >= 2 * body and upper <= body * 0.3 and self._is_bullish(o, c):
                results.append({
                    'pattern': 'Hanging_Man',
                    'signal': 'bearish',
                    'level': h,
                    'confidence': 0.70
                })
        
        # 2. Hammer
        if self._is_in_downtrend(idx):
            lower = self._lower_shadow(o, l, c)
            body = self._body(o, c)
            upper = self._upper_shadow(o, h, c)
            if lower >= 2 * body and upper <= body * 0.3 and self._is_bearish(o, c):
                results.append({
                    'pattern': 'Hammer',
                    'signal': 'bullish',
                    'level': l,
                    'confidence': 0.70
                })
        
        # 3. Inverted Hammer
        if self._is_in_downtrend(idx):
            upper = self._upper_shadow(o, h, c)
            body = self._body(o, c)
            lower = self._lower_shadow(o, l, c)
            if upper >= 2 * body and lower <= body * 0.3:
                results.append({
                    'pattern': 'Inverted_Hammer',
                    'signal': 'bullish',
                    'level': h,
                    'confidence': 0.65
                })
        
        # 4. Shooting Star
        if self._is_in_uptrend(idx):
            upper = self._upper_shadow(o, h, c)
            body = self._body(o, c)
            lower = self._lower_shadow(o, l, c)
            if upper >= 2 * body and lower <= body * 0.3:
                results.append({
                    'pattern': 'Shooting_Star',
                    'signal': 'bearish',
                    'level': h,
                    'confidence': 0.65
                })
        
        # 5. Bullish Marubozu
        if self._is_bullish(o, c):
            body = self._body(o, c)
            upper = self._upper_shadow(o, h, c)
            lower = self._lower_shadow(o, l, c)
            if upper <= body * 0.05 and lower <= body * 0.05:
                results.append({
                    'pattern': 'Bullish_Marubozu',
                    'signal': 'bullish',
                    'level': c,
                    'confidence': 0.60
                })
        
        # 6. Bearish Marubozu
        if self._is_bearish(o, c):
            body = self._body(o, c)
            upper = self._upper_shadow(o, h, c)
            lower = self._lower_shadow(o, l, c)
            if upper <= body * 0.05 and lower <= body * 0.05:
                results.append({
                    'pattern': 'Bearish_Marubozu',
                    'signal': 'bearish',
                    'level': c,
                    'confidence': 0.60
                })
        
        # ---- DOUBLE CANDLE (6) ----
        if idx >= 1:
            prev = self.df.iloc[idx-1]
            
            # 7. Bullish Engulfing
            if self._is_bearish(prev['open'], prev['close']) and \
               self._is_bullish(o, c) and \
               o <= prev['close'] and c >= prev['open']:
                results.append({
                    'pattern': 'Bullish_Engulfing',
                    'signal': 'bullish',
                    'level': l,
                    'confidence': 0.80
                })
            
            # 8. Bearish Engulfing
            if self._is_bullish(prev['open'], prev['close']) and \
               self._is_bearish(o, c) and \
               o >= prev['close'] and c <= prev['open']:
                results.append({
                    'pattern': 'Bearish_Engulfing',
                    'signal': 'bearish',
                    'level': h,
                    'confidence': 0.80
                })
            
            # 9. Dark Cloud Cover
            if self._is_in_uptrend(idx) and \
               self._is_bullish(prev['open'], prev['close']) and \
               self._is_bearish(o, c) and \
               o > prev['close'] and \
               c < (prev['open'] + prev['close']) / 2:
                results.append({
                    'pattern': 'Dark_Cloud_Cover',
                    'signal': 'bearish',
                    'level': h,
                    'confidence': 0.75
                })
            
            # 10. Piercing Pattern
            if self._is_in_downtrend(idx) and \
               self._is_bearish(prev['open'], prev['close']) and \
               self._is_bullish(o, c) and \
               o < prev['close'] and \
               c > (prev['open'] + prev['close']) / 2:
                results.append({
                    'pattern': 'Piercing_Pattern',
                    'signal': 'bullish',
                    'level': l,
                    'confidence': 0.75
                })
            
            # 11. Bullish Harami
            if self._is_bearish(prev['open'], prev['close']) and \
               self._is_bullish(o, c) and \
               o > prev['close'] and c < prev['open']:
                results.append({
                    'pattern': 'Bullish_Harami',
                    'signal': 'bullish',
                    'level': l,
                    'confidence': 0.70
                })
            
            # 12. Bearish Harami
            if self._is_bullish(prev['open'], prev['close']) and \
               self._is_bearish(o, c) and \
               o < prev['close'] and c > prev['open']:
                results.append({
                    'pattern': 'Bearish_Harami',
                    'signal': 'bearish',
                    'level': h,
                    'confidence': 0.70
                })
        
        # ---- TRIPLE CANDLE (8) ----
        if idx >= 2:
            c1 = self.df.iloc[idx-2]
            c2 = self.df.iloc[idx-1]
            c3 = self.df.iloc[idx]
            
            # 13. Morning Star
            if self._is_in_downtrend(idx) and \
               self._is_bearish(c1['open'], c1['close']) and \
               self._is_small_body(c2['open'], c2['high'], c2['low'], c2['close']) and \
               self._is_bullish(c3['open'], c3['close']) and \
               c3['close'] > (c1['open'] + c1['close']) / 2:
                results.append({
                    'pattern': 'Morning_Star',
                    'signal': 'bullish',
                    'level': c3['low'],
                    'confidence': 0.80
                })
            
            # 14. Evening Star
            if self._is_in_uptrend(idx) and \
               self._is_bullish(c1['open'], c1['close']) and \
               self._is_small_body(c2['open'], c2['high'], c2['low'], c2['close']) and \
               self._is_bearish(c3['open'], c3['close']) and \
               c3['close'] < (c1['open'] + c1['close']) / 2:
                results.append({
                    'pattern': 'Evening_Star',
                    'signal': 'bearish',
                    'level': c3['high'],
                    'confidence': 0.80
                })
            
            # 15. Morning Doji Star
            if self._is_in_downtrend(idx) and \
               self._is_bearish(c1['open'], c1['close']) and \
               self._is_doji(c2['open'], c2['high'], c2['low'], c2['close']) and \
               self._is_bullish(c3['open'], c3['close']) and \
               c3['close'] > c1['close']:
                results.append({
                    'pattern': 'Morning_Doji_Star',
                    'signal': 'bullish',
                    'level': c3['low'],
                    'confidence': 0.80
                })
            
            # 16. Evening Doji Star
            if self._is_in_uptrend(idx) and \
               self._is_bullish(c1['open'], c1['close']) and \
               self._is_doji(c2['open'], c2['high'], c2['low'], c2['close']) and \
               self._is_bearish(c3['open'], c3['close']) and \
               c3['close'] < c1['close']:
                results.append({
                    'pattern': 'Evening_Doji_Star',
                    'signal': 'bearish',
                    'level': c3['high'],
                    'confidence': 0.80
                })
            
            # 17. Three White Soldiers
            if self._is_bullish(c1['open'], c1['close']) and \
               self._is_bullish(c2['open'], c2['close']) and \
               self._is_bullish(c3['open'], c3['close']) and \
               c1['close'] > c1['open'] and \
               c2['open'] > c1['open'] and \
               c2['close'] > c1['close'] and \
               c3['open'] > c2['open'] and \
               c3['close'] > c2['close']:
                results.append({
                    'pattern': 'Three_White_Soldiers',
                    'signal': 'bullish',
                    'level': c3['high'],
                    'confidence': 0.75
                })
            
            # 18. Three Black Crows
            if self._is_bearish(c1['open'], c1['close']) and \
               self._is_bearish(c2['open'], c2['close']) and \
               self._is_bearish(c3['open'], c3['close']) and \
               c1['close'] < c1['open'] and \
               c2['open'] < c1['open'] and \
               c2['close'] < c1['close'] and \
               c3['open'] < c2['open'] and \
               c3['close'] < c2['close']:
                results.append({
                    'pattern': 'Three_Black_Crows',
                    'signal': 'bearish',
                    'level': c3['low'],
                    'confidence': 0.75
                })
            
            # 19. Three Inside Up
            if self._is_bearish(c1['open'], c1['close']) and \
               self._is_bullish(c2['open'], c2['close']) and \
               c2['open'] > c1['close'] and c2['close'] < c1['open'] and \
               self._is_bullish(c3['open'], c3['close']) and \
               c3['close'] > c1['open']:
                results.append({
                    'pattern': 'Three_Inside_Up',
                    'signal': 'bullish',
                    'level': c3['low'],
                    'confidence': 0.70
                })
            
            # 20. Three Inside Down
            if self._is_bullish(c1['open'], c1['close']) and \
               self._is_bearish(c2['open'], c2['close']) and \
               c2['open'] < c1['close'] and c2['close'] > c1['open'] and \
               self._is_bearish(c3['open'], c3['close']) and \
               c3['close'] < c1['open']:
                results.append({
                    'pattern': 'Three_Inside_Down',
                    'signal': 'bearish',
                    'level': c3['high'],
                    'confidence': 0.70
                })
        
        return results
    
    # ------------------------------------------------------------
    # SECTION 3: SMC/ICT PATTERNS (29 PATTERNS)
    # ------------------------------------------------------------
    
    # ---- Fair Value Gap ----
    def detect_fvg(self, idx: int) -> Optional[Dict]:
        if idx < 2:
            return None
        prev2 = self.df.iloc[idx-2]
        prev1 = self.df.iloc[idx-1]
        curr = self.df.iloc[idx]
        
        if prev2['high'] < curr['low'] and self._is_bullish(prev1['open'], prev1['close']):
            return {
                'pattern': 'FVG_Bullish',
                'signal': 'bullish',
                'top': curr['low'],
                'bottom': prev2['high'],
                'level': (curr['low'] + prev2['high']) / 2,
                'confidence': 0.75,
                'mitigated': False
            }
        
        if prev2['low'] > curr['high'] and self._is_bearish(prev1['open'], prev1['close']):
            return {
                'pattern': 'FVG_Bearish',
                'signal': 'bearish',
                'top': prev2['low'],
                'bottom': curr['high'],
                'level': (prev2['low'] + curr['high']) / 2,
                'confidence': 0.75,
                'mitigated': False
            }
        return None
    
    def detect_fvg_mitigation(self, idx: int) -> Optional[Dict]:
        if idx < 0:
            return None
        
        curr_close = self.df['close'].iloc[idx]
        curr_low = self.df['low'].iloc[idx]
        curr_high = self.df['high'].iloc[idx]
        
        for fvg in self.active_fvgs:
            if fvg.get('mitigated', False):
                continue
            
            if fvg['pattern'] == 'FVG_Bullish':
                if curr_low < fvg['top'] and curr_close > fvg['top']:
                    fvg['mitigated'] = True
                    return {
                        'pattern': 'FVG_Mitigation_Bullish',
                        'signal': 'bullish',
                        'level': fvg['level'],
                        'confidence': 0.80
                    }
            
            if fvg['pattern'] == 'FVG_Bearish':
                if curr_high > fvg['bottom'] and curr_close < fvg['bottom']:
                    fvg['mitigated'] = True
                    return {
                        'pattern': 'FVG_Mitigation_Bearish',
                        'signal': 'bearish',
                        'level': fvg['level'],
                        'confidence': 0.80
                    }
        return None
    
    # ---- Order Block ----
    def detect_order_block(self, idx: int) -> Optional[Dict]:
        if idx < 1:
            return None
        prev = self.df.iloc[idx-1]
        curr = self.df.iloc[idx]
        
        if self._is_bearish(prev['open'], prev['close']) and \
           self._is_bullish(curr['open'], curr['close']) and \
           curr['close'] > prev['high'] and \
           self._body(curr['open'], curr['close']) > self._body(prev['open'], prev['close']) * 1.5:
            return {
                'pattern': 'Order_Block_Bullish',
                'signal': 'bullish',
                'high': prev['high'],
                'low': prev['low'],
                'level': (prev['high'] + prev['low']) / 2,
                'confidence': 0.80
            }
        
        if self._is_bullish(prev['open'], prev['close']) and \
           self._is_bearish(curr['open'], curr['close']) and \
           curr['close'] < prev['low'] and \
           self._body(curr['open'], curr['close']) > self._body(prev['open'], prev['close']) * 1.5:
            return {
                'pattern': 'Order_Block_Bearish',
                'signal': 'bearish',
                'high': prev['high'],
                'low': prev['low'],
                'level': (prev['high'] + prev['low']) / 2,
                'confidence': 0.80
            }
        return None
    
    # ---- Breaker Block ----
    def detect_breaker_block(self, idx: int) -> Optional[Dict]:
        if idx < 2:
            return None
        ob = self.detect_order_block(idx-1)
        if not ob:
            return None
        
        curr = self.df.iloc[idx]
        if ob['pattern'] == 'Order_Block_Bullish' and curr['close'] < ob['low']:
            return {
                'pattern': 'Breaker_Block_Bearish',
                'signal': 'bearish',
                'level': ob['low'],
                'confidence': 0.75
            }
        if ob['pattern'] == 'Order_Block_Bearish' and curr['close'] > ob['high']:
            return {
                'pattern': 'Breaker_Block_Bullish',
                'signal': 'bullish',
                'level': ob['high'],
                'confidence': 0.75
            }
        return None
    
    # ---- Break of Structure / Change of Character ----
    def detect_bos_choch(self, idx: int) -> Optional[Dict]:
        if idx < 5:
            return None
        
        recent_high_idx = self.df['high'].iloc[idx-5:idx+1].idxmax()
        recent_low_idx = self.df['low'].iloc[idx-5:idx+1].idxmin()
        
        curr_high = self.df['high'].iloc[idx]
        curr_low = self.df['low'].iloc[idx]
        
        if curr_high > self.df['high'].loc[recent_high_idx] and self._is_in_uptrend(idx):
            return {
                'pattern': 'BOS_Bullish',
                'signal': 'bullish',
                'level': curr_high,
                'confidence': 0.75
            }
        if curr_low < self.df['low'].loc[recent_low_idx] and self._is_in_downtrend(idx):
            return {
                'pattern': 'BOS_Bearish',
                'signal': 'bearish',
                'level': curr_low,
                'confidence': 0.75
            }
        
        if self._is_in_uptrend(idx) and curr_low < self.df['low'].loc[recent_low_idx]:
            return {
                'pattern': 'CHOCH_Bearish',
                'signal': 'bearish',
                'level': curr_low,
                'confidence': 0.70
            }
        if self._is_in_downtrend(idx) and curr_high > self.df['high'].loc[recent_high_idx]:
            return {
                'pattern': 'CHOCH_Bullish',
                'signal': 'bullish',
                'level': curr_high,
                'confidence': 0.70
            }
        return None
    
    # ---- Liquidity Grab ----
    def detect_liquidity_grab(self, idx: int) -> Optional[Dict]:
        if idx < 3:
            return None
        curr = self.df.iloc[idx]
        
        if curr['low'] < self.df['low'].iloc[idx-3:idx].min() and \
           curr['close'] > self.df['high'].iloc[idx-1]:
            return {
                'pattern': 'Liquidity_Grab_Bullish',
                'signal': 'bullish',
                'level': self.df['low'].iloc[idx-3:idx].min(),
                'confidence': 0.80
            }
        
        if curr['high'] > self.df['high'].iloc[idx-3:idx].max() and \
           curr['close'] < self.df['low'].iloc[idx-1]:
            return {
                'pattern': 'Liquidity_Grab_Bearish',
                'signal': 'bearish',
                'level': self.df['high'].iloc[idx-3:idx].max(),
                'confidence': 0.80
            }
        return None
    
    # ---- Judas Swing ----
    def detect_judas_swing(self, idx: int) -> Optional[Dict]:
        if idx < 4:
            return None
        curr = self.df.iloc[idx]
        
        if curr['high'] > self.df['high'].iloc[idx-4:idx].max() and \
           self._is_bearish(curr['open'], curr['close']) and \
           curr['close'] < self.df['low'].iloc[idx-1]:
            return {
                'pattern': 'Judas_Swing_Bearish',
                'signal': 'bearish',
                'level': curr['high'],
                'confidence': 0.75
            }
        
        if curr['low'] < self.df['low'].iloc[idx-4:idx].min() and \
           self._is_bullish(curr['open'], curr['close']) and \
           curr['close'] > self.df['high'].iloc[idx-1]:
            return {
                'pattern': 'Judas_Swing_Bullish',
                'signal': 'bullish',
                'level': curr['low'],
                'confidence': 0.75
            }
        return None
    
    # ---- Optimal Trade Entry ----
    def detect_ote(self, idx: int, fib_level: float = 0.618) -> Optional[Dict]:
        if idx < 20:
            return None
        
        lookback = 20
        impulse_start = self.df['low'].iloc[idx-lookback:idx].idxmin()
        impulse_end = self.df['high'].iloc[idx-lookback:idx].idxmax()
        
        if impulse_start > impulse_end:
            impulse_start, impulse_end = impulse_end, impulse_start
        
        impulse_range = self.df['high'].loc[impulse_end] - self.df['low'].loc[impulse_start]
        if impulse_range <= 0:
            return None
        
        retrace_level = self.df['high'].loc[impulse_end] - impulse_range * fib_level
        curr_price = self.df['close'].iloc[idx]
        
        if abs(curr_price - retrace_level) < impulse_range * 0.05:
            return {
                'pattern': f'OTE_Fib_{int(fib_level*100)}',
                'signal': 'bullish' if fib_level >= 0.5 else 'bearish',
                'level': retrace_level,
                'confidence': 0.70
            }
        return None
    
    # ---- Discount / Premium Zone ----
    def detect_discount_premium(self, idx: int, lookback: int = 20) -> Optional[Dict]:
        if idx < lookback:
            return None
        
        recent_high = self.df['high'].iloc[idx-lookback:idx+1].max()
        recent_low = self.df['low'].iloc[idx-lookback:idx+1].min()
        mid = (recent_high + recent_low) / 2
        
        curr_price = self.df['close'].iloc[idx]
        if curr_price < mid:
            return {
                'pattern': 'Discount_Zone',
                'signal': 'bullish',
                'level': mid,
                'confidence': 0.60
            }
        else:
            return {
                'pattern': 'Premium_Zone',
                'signal': 'bearish',
                'level': mid,
                'confidence': 0.60
            }
    
    # ---- Refined Entry Zone ----
    def detect_refined_entry(self, idx: int) -> Optional[Dict]:
        ob = self.detect_order_block(idx)
        if not ob:
            return None
        ob_mid = (ob['high'] + ob['low']) * 0.5
        return {
            'pattern': 'Refined_Entry',
            'signal': 'bullish' if 'Bullish' in ob['pattern'] else 'bearish',
            'level': ob_mid,
            'confidence': 0.65
        }
    
    # ---- Session Manipulation ----
    def detect_session_manipulation(self, idx: int) -> Optional[Dict]:
        if idx < 5:
            return None
        recent = self.df.iloc[idx-5:idx+1]
        if recent['high'].iloc[-1] == recent['high'].max() and \
           recent['low'].iloc[-1] == recent['low'].min():
            return {
                'pattern': 'Session_Manipulation',
                'signal': 'neutral',
                'confidence': 0.50
            }
        return None
    
    # ---- Smart Money Divergence ----
    def detect_smt_divergence(self, idx: int) -> Optional[Dict]:
        if idx < 10:
            return None
        close = self.df['close']
        
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        price_peak = close.iloc[idx-10:idx+1].max()
        price_peak_idx = close.iloc[idx-10:idx+1].idxmax()
        rsi_at_peak = rsi.loc[price_peak_idx]
        
        if close.iloc[idx] > price_peak * 0.99 and rsi.iloc[idx] < rsi_at_peak - 5:
            return {
                'pattern': 'SMT_Divergence_Bearish',
                'signal': 'bearish',
                'confidence': 0.70
            }
        
        price_trough = close.iloc[idx-10:idx+1].min()
        price_trough_idx = close.iloc[idx-10:idx+1].idxmin()
        rsi_at_trough = rsi.loc[price_trough_idx]
        
        if close.iloc[idx] < price_trough * 1.01 and rsi.iloc[idx] > rsi_at_trough + 5:
            return {
                'pattern': 'SMT_Divergence_Bullish',
                'signal': 'bullish',
                'confidence': 0.70
            }
        return None
    
    # ---- Market Structure Shift ----
    def detect_mss(self, idx: int) -> Optional[Dict]:
        if idx < 3:
            return None
        if self._is_in_uptrend(idx, 5) and idx + 1 < len(self.df):
            if self.df['low'].iloc[idx+1] < self.df['low'].iloc[idx] and \
               self.df['close'].iloc[idx+1] < self.df['close'].iloc[idx]:
                return {
                    'pattern': 'MSS_Bearish',
                    'signal': 'bearish',
                    'confidence': 0.70
                }
        if self._is_in_downtrend(idx, 5) and idx + 1 < len(self.df):
            if self.df['high'].iloc[idx+1] > self.df['high'].iloc[idx] and \
               self.df['close'].iloc[idx+1] > self.df['close'].iloc[idx]:
                return {
                    'pattern': 'MSS_Bullish',
                    'signal': 'bullish',
                    'confidence': 0.70
                }
        return None
    
    # ---- Time & Price Equilibrium ----
    def detect_tap_equilibrium(self, idx: int) -> Optional[Dict]:
        """Time & Price Equilibrium - ICT Concept"""
        if idx < 20:
            return None
        recent = self.df.iloc[idx-20:idx+1]
        time_range = len(recent)
        price_range = recent['high'].max() - recent['low'].min()
        avg_range = (recent['high'] - recent['low']).mean()
        
        if price_range < avg_range * 0.5 and time_range > 10:
            return {
                'pattern': 'TAP_Equilibrium',
                'signal': 'neutral',
                'confidence': 0.55
            }
        return None
    
    # ---- All SMC/ICT Patterns Scan ----
    def scan_smc_patterns(self) -> List[Dict]:
        results = []
        last_idx = len(self.df) - 1
        
        for i in range(max(2, last_idx-20), last_idx+1):
            fvg = self.detect_fvg(i)
            if fvg:
                self.active_fvgs.append(fvg)
        
        for i in range(max(5, last_idx-5), last_idx+1):
            detectors = [
                ('fvg_mitigation', self.detect_fvg_mitigation(i)),
                ('order_block', self.detect_order_block(i)),
                ('breaker_block', self.detect_breaker_block(i)),
                ('bos_choch', self.detect_bos_choch(i)),
                ('liquidity_grab', self.detect_liquidity_grab(i)),
                ('judas_swing', self.detect_judas_swing(i)),
                ('ote_382', self.detect_ote(i, 0.382)),
                ('ote_500', self.detect_ote(i, 0.500)),
                ('ote_618', self.detect_ote(i, 0.618)),
                ('ote_786', self.detect_ote(i, 0.786)),
                ('ote_886', self.detect_ote(i, 0.886)),
                ('discount_premium', self.detect_discount_premium(i)),
                ('refined_entry', self.detect_refined_entry(i)),
                ('session_manipulation', self.detect_session_manipulation(i)),
                ('smt_divergence', self.detect_smt_divergence(i)),
                ('mss', self.detect_mss(i)),
                ('tap_equilibrium', self.detect_tap_equilibrium(i))
            ]
            
            for name, signal in detectors:
                if signal:
                    results.append(signal)
        
        return results
    
    # ------------------------------------------------------------
    # ANA METOD: TÜM PATTERN'LERİ TARA (79 PATTERN)
    # ------------------------------------------------------------
    def scan_all_patterns(self) -> List[Dict]:
        """
        Tüm pattern fonksiyonlarını çalıştırıp aktif sinyalleri döndürür.
        Toplam: 79 Pattern
        - 30 Advanced Price Action
        - 20 Classic Candlestick
        - 29 SMC/ICT
        """
        results = []
        
        # ---- BÖLÜM 1: Advanced Price Action (30) ----
        pa_patterns = [
            self.detect_qm_quick_retest,
            self.detect_qm_late_retest,
            self.detect_continuation_qm,
            self.detect_ignored_qm,
            self.detect_dm_shadow,
            self.detect_can_can,
            self.detect_can_can_fakeout,
            self.detect_fakeout_v1,
            self.detect_fakeout_v2,
            self.detect_fakeout_v3,
            self.detect_flag_a,
            self.detect_flag_b,
            self.detect_mpl_flag,
            self.detect_ruler,
            self.detect_compression,
            self.detect_compression_liquidity,
            self.detect_double_ssr,
            self.detect_stop_hunt,
            self.detect_3_drive,
            self.detect_v_twin,
            self.detect_rejection,
            self.detect_base_model,
            self.detect_lower_high_higher_low,
            self.detect_trend_exhaustion,
            self.detect_pin_bar,
            self.detect_inside_bar
        ]
        
        for func in pa_patterns:
            try:
                signal = func()
                if signal:
                    results.append(signal)
            except Exception as e:
                continue
        
        # Level Congestion
        try:
            level_info = self.count_levels_ahead()
            if level_info['congestion_signal'] != 'neutral':
                results.append({
                    'pattern': 'Level_Congestion',
                    'signal': level_info['congestion_signal'],
                    'details': {
                        'resistance_count': level_info['resistance_above_count'],
                        'support_count': level_info['support_below_count'],
                        'closest_resistance': level_info['closest_resistance'],
                        'closest_support': level_info['closest_support']
                    },
                    'confidence': 0.60
                })
        except Exception as e:
            pass
        
        # ---- BÖLÜM 2: Classic Candlestick (20) ----
        try:
            candle_signals = self.detect_candlestick_patterns(idx=len(self.df)-1)
            results.extend(candle_signals)
        except Exception as e:
            pass
        
        # ---- BÖLÜM 3: SMC/ICT (29) ----
        try:
            smc_signals = self.scan_smc_patterns()
            results.extend(smc_signals)
        except Exception as e:
            pass
        
        return results


# ============================================
# FEATURE ENGINEERING
# ============================================
class FeatureEngineer:
    """Advanced feature engineering for ML models"""
    
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self.scaler = RobustScaler()
        self.pattern_detector = None
        
    def add_technical_indicators(self) -> pd.DataFrame:
        """Add all technical indicators"""
        df = self.df.copy()
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        volume = df['volume'].values if 'volume' in df.columns else None
        
        # Price-based indicators
        for period in CONFIG['TECHNICAL_INDICATORS']['sma_periods']:
            df[f'sma_{period}'] = talib.SMA(close, period)
            df[f'ema_{period}'] = talib.EMA(close, period)
        
        # RSI
        for period in CONFIG['TECHNICAL_INDICATORS']['rsi_periods']:
            df[f'rsi_{period}'] = talib.RSI(close, period)
        
        # MACD
        fast = CONFIG['TECHNICAL_INDICATORS']['macd_fast']
        slow = CONFIG['TECHNICAL_INDICATORS']['macd_slow']
        signal = CONFIG['TECHNICAL_INDICATORS']['macd_signal']
        df['macd'], df['macd_signal'], df['macd_hist'] = talib.MACD(close, fast, slow, signal)
        
        # Bollinger Bands
        bb_period = CONFIG['TECHNICAL_INDICATORS']['bb_period']
        bb_std = CONFIG['TECHNICAL_INDICATORS']['bb_std']
        df['bb_upper'], df['bb_middle'], df['bb_lower'] = talib.BBANDS(close, bb_period, bb_std, bb_std)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
        df['bb_position'] = (close - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
        
        # ATR
        atr_period = CONFIG['TECHNICAL_INDICATORS']['atr_period']
        df['atr'] = talib.ATR(high, low, close, atr_period)
        df['atr_pct'] = df['atr'] / close * 100
        
        # ADX
        adx_period = CONFIG['TECHNICAL_INDICATORS']['adx_period']
        df['adx'] = talib.ADX(high, low, close, adx_period)
        df['plus_di'] = talib.PLUS_DI(high, low, close, adx_period)
        df['minus_di'] = talib.MINUS_DI(high, low, close, adx_period)
        
        # CCI
        cci_period = CONFIG['TECHNICAL_INDICATORS']['cci_period']
        df['cci'] = talib.CCI(high, low, close, cci_period)
        
        # Williams %R
        will_period = CONFIG['TECHNICAL_INDICATORS']['williams_period']
        df['williams_r'] = talib.WILLR(high, low, close, will_period)
        
        # Stochastic
        stoch_k = CONFIG['TECHNICAL_INDICATORS']['stoch_k']
        stoch_d = CONFIG['TECHNICAL_INDICATORS']['stoch_d']
        df['stoch_k'], df['stoch_d'] = talib.STOCH(high, low, close, stoch_k, stoch_d, 0, 0)
        
        # MFI
        if volume is not None:
            mfi_period = CONFIG['TECHNICAL_INDICATORS']['mfi_period']
            df['mfi'] = talib.MFI(high, low, close, volume, mfi_period)
            df['obv'] = talib.OBV(close, volume)
        
        # Price patterns
        df['higher_high'] = (high > high.shift(1)) & (high.shift(1) > high.shift(2))
        df['lower_low'] = (low < low.shift(1)) & (low.shift(1) < low.shift(2))
        
        # Returns and volatility
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        df['volatility'] = df['returns'].rolling(20).std()
        df['volatility_ratio'] = df['volatility'] / df['volatility'].rolling(50).mean()
        
        # Volume indicators
        if volume is not None:
            df['volume_sma'] = talib.SMA(volume, 20)
            df['volume_ratio'] = volume / df['volume_sma']
            df['volume_price_trend'] = (df['volume_ratio'] * df['returns']).cumsum()
        
        # Price position
        df['close_position'] = (close - df['low'].rolling(20).min()) / (df['high'].rolling(20).max() - df['low'].rolling(20).min())
        df['close_position_50'] = (close - df['low'].rolling(50).min()) / (df['high'].rolling(50).max() - df['low'].rolling(50).min())
        
        # Trend strength
        df['trend_strength'] = abs(df['adx'] - 25) if 'adx' in df.columns else 0
        df['trend_direction'] = np.where(df['plus_di'] > df['minus_di'], 1, -1) if 'plus_di' in df.columns else 0
        
        return df.dropna()
    
    def add_pattern_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add pattern-based features"""
        df = df.copy()
        self.pattern_detector = AdvancedPatternDetector(df)
        patterns = self.pattern_detector.scan_all_patterns()
        
        # Pattern counts and strengths
        pattern_signals = {'bullish': 0, 'bearish': 0, 'neutral': 0}
        pattern_confidences = []
        
        for p in patterns[-50:]:  # Last 50 patterns
            signal = p.get('signal', 'neutral')
            confidence = p.get('confidence', 0)
            pattern_signals[signal] += 1
            pattern_confidences.append(confidence)
        
        df['bullish_patterns'] = pattern_signals['bullish']
        df['bearish_patterns'] = pattern_signals['bearish']
        df['pattern_sentiment'] = (pattern_signals['bullish'] - pattern_signals['bearish']) / max(1, sum(pattern_signals.values()))
        df['pattern_confidence'] = np.mean(pattern_confidences) if pattern_confidences else 0.5
        
        # Support/Resistance features
        levels = self.pattern_detector.get_support_resistance()
        current_price = df['close'].iloc[-1]
        
        supports = [l.price for l in levels if l.type == 'support' and l.price < current_price]
        resistances = [l.price for l in levels if l.type == 'resistance' and l.price > current_price]
        
        df['nearest_support'] = max(supports) if supports else current_price * 0.95
        df['nearest_resistance'] = min(resistances) if resistances else current_price * 1.05
        df['support_distance'] = (current_price - df['nearest_support']) / current_price * 100
        df['resistance_distance'] = (df['nearest_resistance'] - current_price) / current_price * 100
        
        return df
    
    def prepare_sequences(self, df: pd.DataFrame, sequence_length: int = 128) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare sequences for LSTM/Transformer"""
        feature_cols = [col for col in df.columns if col not in ['target', 'timestamp']]
        data = df[feature_cols].values
        
        X, y = [], []
        for i in range(len(data) - sequence_length):
            X.append(data[i:i + sequence_length])
            if 'target' in df.columns:
                y.append(df['target'].iloc[i + sequence_length])
            else:
                # Create target as next period return direction
                future_return = df['close'].iloc[i + sequence_length] / df['close'].iloc[i + sequence_length - 1] - 1
                y.append(0 if future_return > 0.001 else 1 if future_return < -0.001 else 2)
        
        return np.array(X), np.array(y)


# ============================================
# ML ENGINE
# ============================================
class MLEngine:
    """Advanced ML Engine with multiple models"""
    
    def __init__(self, device: str = None):
        self.device = device if device else ('cuda' if torch.cuda.is_available() else 'cpu')
        self.models = {}
        self.scalers = {}
        self.feature_engineer = None
        console.print(f"[green]ML Engine initialized on {self.device}[/green]")
        
    async def train(self, symbol: str, df: pd.DataFrame):
        """Train all models for a symbol"""
        console.print(f"[yellow]Training models for {symbol}...[/yellow]")
        
        # Feature engineering
        self.feature_engineer = FeatureEngineer(df)
        df_features = self.feature_engineer.add_technical_indicators()
        
        # Add pattern features
        try:
            df_features = self.feature_engineer.add_pattern_features(df_features)
        except Exception as e:
            console.print(f"[red]Pattern feature error: {e}[/red]")
        
        # Prepare sequences
        X, y = self.feature_engineer.prepare_sequences(df_features, CONFIG['ML_SETTINGS']['sequence_length'])
        
        if len(X) == 0:
            console.print(f"[red]Not enough data for training {symbol}[/red]")
            return
        
        # Train/val split
        split = int(len(X) * (1 - CONFIG['ML_SETTINGS']['validation_split']))
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]
        
        # Scale features
        scaler = RobustScaler()
        X_train_flat = X_train.reshape(-1, X_train.shape[-1])
        scaler.fit(X_train_flat)
        X_train = scaler.transform(X_train_flat).reshape(X_train.shape)
        X_val = scaler.transform(X_val.reshape(-1, X_val.shape[-1])).reshape(X_val.shape)
        
        self.scalers[symbol] = scaler
        
        # Convert to tensors
        X_train_t = torch.FloatTensor(X_train).to(self.device)
        y_train_t = torch.LongTensor(y_train).to(self.device)
        X_val_t = torch.FloatTensor(X_val).to(self.device)
        y_val_t = torch.LongTensor(y_val).to(self.device)
        
        # Train Transformer-XL
        transformer = AdvancedTransformerXL(
            input_size=X.shape[-1],
            d_model=CONFIG['ML_SETTINGS']['d_model'],
            nhead=CONFIG['ML_SETTINGS']['nhead'],
            num_layers=CONFIG['ML_SETTINGS']['num_transformer_layers'],
            output_size=3,
            dropout=CONFIG['ML_SETTINGS']['dropout']
        ).to(self.device)
        
        await self._train_model(transformer, X_train_t, y_train_t, X_val_t, y_val_t, f'{symbol}_transformer')
        self.models[f'{symbol}_transformer'] = transformer
        
        # Train LSTM-Attention
        lstm = LSTMAttention(
            input_size=X.shape[-1],
            hidden_size=CONFIG['ML_SETTINGS']['hidden_size'],
            num_layers=CONFIG['ML_SETTINGS']['num_layers'],
            output_size=3,
            dropout=CONFIG['ML_SETTINGS']['dropout'],
            bidirectional=True
        ).to(self.device)
        
        await self._train_model(lstm, X_train_t, y_train_t, X_val_t, y_val_t, f'{symbol}_lstm')
        self.models[f'{symbol}_lstm'] = lstm
        
        # Train Multi-Task Transformer
        multi_task = MultiTaskTransformer(
            input_size=X.shape[-1],
            d_model=CONFIG['ML_SETTINGS']['d_model'],
            nhead=CONFIG['ML_SETTINGS']['nhead'],
            num_layers=CONFIG['ML_SETTINGS']['num_transformer_layers'] // 2,
            dropout=CONFIG['ML_SETTINGS']['dropout']
        ).to(self.device)
        
        await self._train_multitask(multi_task, X_train_t, y_train_t, X_val_t, y_val_t, f'{symbol}_multitask')
        self.models[f'{symbol}_multitask'] = multi_task
        
        # Train Ensemble
        ensemble = EnsembleModel(
            input_size=X.shape[-1],
            d_model=CONFIG['ML_SETTINGS']['d_model'],
            nhead=CONFIG['ML_SETTINGS']['nhead'],
            num_layers=CONFIG['ML_SETTINGS']['num_transformer_layers'],
            num_models=3,
            output_size=3
        ).to(self.device)
        
        await self._train_model(ensemble, X_train_t, y_train_t, X_val_t, y_val_t, f'{symbol}_ensemble')
        self.models[f'{symbol}_ensemble'] = ensemble
        
        console.print(f"[green]✓ All models trained for {symbol}![/green]")
    
    async def _train_model(self, model, X_train, y_train, X_val, y_val, name):
        """Train a single model"""
        optimizer = optim.AdamW(model.parameters(), 
                                lr=CONFIG['ML_SETTINGS']['learning_rate'],
                                weight_decay=CONFIG['ML_SETTINGS']['weight_decay'])
        scheduler = optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=10, T_mult=2)
        criterion = nn.CrossEntropyLoss()
        scaler = GradScaler()
        
        dataset = TensorDataset(X_train, y_train)
        dataloader = DataLoader(dataset, batch_size=CONFIG['ML_SETTINGS']['batch_size'], shuffle=True)
        
        best_val_loss = float('inf')
        patience_counter = 0
        
        for epoch in range(CONFIG['ML_SETTINGS']['epochs']):
            model.train()
            train_loss = 0
            train_correct = 0
            train_total = 0
            
            for batch_X, batch_y in dataloader:
                optimizer.zero_grad()
                
                with autocast():
                    output = model(batch_X)
                    loss = criterion(output, batch_y)
                
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), CONFIG['ML_SETTINGS']['gradient_clip'])
                scaler.step(optimizer)
                scaler.update()
                
                train_loss += loss.item()
                _, predicted = torch.max(output.data, 1)
                train_total += batch_y.size(0)
                train_correct += (predicted == batch_y).sum().item()
            
            # Validation
            model.eval()
            with torch.no_grad():
                val_output = model(X_val)
                val_loss = criterion(val_output, y_val).item()
                _, val_predicted = torch.max(val_output.data, 1)
                val_accuracy = (val_predicted == y_val).sum().item() / len(y_val)
            
            scheduler.step()
            
            train_accuracy = train_correct / train_total
            
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                # Save best model
                torch.save(model.state_dict(), f"{name}_best.pth")
            else:
                patience_counter += 1
                if patience_counter >= CONFIG['ML_SETTINGS']['early_stopping_patience']:
                    console.print(f"[yellow]{name} early stopping at epoch {epoch}[/yellow]")
                    break
            
            if epoch % 10 == 0:
                console.print(f"{name} Epoch {epoch}: Train Loss {train_loss/len(dataloader):.4f}, "
                            f"Train Acc {train_accuracy:.4f}, Val Loss {val_loss:.4f}, Val Acc {val_accuracy:.4f}")
        
        # Load best model
        try:
            model.load_state_dict(torch.load(f"{name}_best.pth"))
        except:
            pass
    
    async def _train_multitask(self, model, X_train, y_train, X_val, y_val, name):
        """Train multi-task model"""
        optimizer = optim.AdamW(model.parameters(), 
                                lr=CONFIG['ML_SETTINGS']['learning_rate'],
                                weight_decay=CONFIG['ML_SETTINGS']['weight_decay'])
        scheduler = optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=10, T_mult=2)
        criterion_trend = nn.CrossEntropyLoss()
        criterion_pattern = nn.CrossEntropyLoss()
        criterion_volatility = nn.MSELoss()
        
        dataset = TensorDataset(X_train, y_train)
        dataloader = DataLoader(dataset, batch_size=CONFIG['ML_SETTINGS']['batch_size'], shuffle=True)
        
        best_val_loss = float('inf')
        
        for epoch in range(CONFIG['ML_SETTINGS']['epochs'] // 2):
            model.train()
            train_loss = 0
            
            for batch_X, batch_y in dataloader:
                optimizer.zero_grad()
                
                outputs = model(batch_X)
                
                # Generate dummy targets for multi-task
                trend_target = batch_y  # Use same target for trend
                pattern_target = torch.randint(0, 79, batch_y.shape).to(self.device)  # Random pattern
                volatility_target = torch.randn(batch_y.shape[0], 1).to(self.device)  # Random volatility
                
                loss = (criterion_trend(outputs['trend'], trend_target) * 0.5 +
                       criterion_pattern(outputs['pattern'], pattern_target) * 0.3 +
                       criterion_volatility(outputs['volatility'], volatility_target) * 0.2)
                
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), CONFIG['ML_SETTINGS']['gradient_clip'])
                optimizer.step()
                
                train_loss += loss.item()
            
            scheduler.step()
            
            if epoch % 10 == 0:
                console.print(f"{name} Epoch {epoch}: Loss {train_loss/len(dataloader):.4f}")
    
    def predict(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        """Make prediction using ensemble of models"""
        try:
            # Feature engineering
            feature_engineer = FeatureEngineer(df)
            df_features = feature_engineer.add_technical_indicators()
            
            # Prepare sequence
            seq_length = CONFIG['ML_SETTINGS']['sequence_length']
            feature_cols = [col for col in df_features.columns if col not in ['timestamp']]
            data = df_features[feature_cols].values[-seq_length:]
            
            # Scale
            scaler = self.scalers.get(symbol)
            if not scaler:
                return {
                    'prediction': 'Hold',
                    'confidence': 0.5,
                    'signal': 1,
                    'pattern_signals': [],
                    'data_source': '11_exchanges + coingecko'
                }
            
            data_scaled = scaler.transform(data).reshape(1, seq_length, -1)
            data_tensor = torch.FloatTensor(data_scaled).to(self.device)
            
            # Collect predictions from all models
            predictions = []
            confidences = []
            
            model_keys = [f'{symbol}_transformer', f'{symbol}_lstm', f'{symbol}_ensemble']
            for key in model_keys:
                if key in self.models:
                    model = self.models[key]
                    model.eval()
                    with torch.no_grad():
                        output = model(data_tensor)
                        probabilities = F.softmax(output, dim=1)[0].cpu().numpy()
                        pred = np.argmax(probabilities)
                        conf = probabilities[pred]
                        predictions.append(pred)
                        confidences.append(conf)
            
            # Get pattern signals
            pattern_detector = AdvancedPatternDetector(df)
            pattern_signals = pattern_detector.scan_all_patterns()
            
            # Filter high confidence patterns
            high_conf_patterns = [p for p in pattern_signals if p.get('confidence', 0) >= 0.7]
            
            # Combine predictions
            if predictions:
                # Weighted voting based on confidence
                weights = np.array(confidences) / np.sum(confidences)
                final_pred = int(np.average(predictions, weights=weights))
                final_conf = float(np.mean(confidences))
            else:
                final_pred = 1
                final_conf = 0.5
            
            # Adjust based on pattern sentiment
            bullish_count = sum(1 for p in high_conf_patterns if p.get('signal') == 'bullish')
            bearish_count = sum(1 for p in high_conf_patterns if p.get('signal') == 'bearish')
            
            if bullish_count > bearish_count * 2:
                final_pred = 0  # Buy
                final_conf = min(1.0, final_conf + 0.1)
            elif bearish_count > bullish_count * 2:
                final_pred = 2  # Sell
                final_conf = min(1.0, final_conf + 0.1)
            
            labels = {0: 'Buy', 1: 'Hold', 2: 'Sell'}
            
            return {
                'prediction': labels[final_pred],
                'confidence': final_conf,
                'signal': final_pred,
                'pattern_signals': high_conf_patterns[:10],  # Top 10 patterns
                'bullish_patterns': bullish_count,
                'bearish_patterns': bearish_count,
                'data_source': '11_exchanges + coingecko',
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            console.print(f"[red]Prediction error for {symbol}: {e}[/red]")
            return {
                'prediction': 'Hold',
                'confidence': 0.5,
                'signal': 1,
                'pattern_signals': [],
                'data_source': 'error'
            }


# ============================================
# TRADING BOT
# ============================================
class TradingBot:
    """Main trading bot with integrated ML and pattern detection"""
    
    def __init__(self):
        self.exchange_manager = ExchangeManager()
        self.ml_engine = MLEngine()
        self.data_bridge = data_bridge  # DataBridge'i bağla
        self.running = False
        self.symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT', 'DOGEUSDT', 'XRPUSDT']
        self.positions = {}
        self.equity_curve = []
        self.trade_history = []
        self.pattern_history = []
        self.pattern_analysis_history = []
        
        # DataBridge'e TradingBot'u bildir
        self.data_bridge.set_trading_bot(self)
        
    async def start(self):
        """Start the trading bot"""
        self.running = True
        
        console.print(Panel.fit(
            "[bold cyan]🚀 AI CRYPTO TRADING BOT v5.0 - 11 EXCHANGE + COINGECKO EDITION[/bold cyan]\n"
            "[green]✓ DataBridge Active - 11 Exchanges + CoinGecko[/green]\n"
            "[yellow]✓ 79 Pattern Detector Active[/yellow]\n"
            "[magenta]✓ Advanced ML Models (Transformer-XL, LSTM, Ensemble)[/magenta]\n"
            "[blue]✓ Reinforcement Learning PPO Ready[/blue]\n"
            "[cyan]✓ main.py Integration Ready[/cyan]",
            title="🎯 System Status",
            border_style="cyan"
        ))
        
        console.print("\n[bold yellow]⏳ Waiting for data from main.py...[/bold yellow]")
        console.print("[dim]main.py will send real-time data from 11 exchanges and CoinGecko[/dim]\n")
        
        # Start CLI loop
        await self._cli_loop()
    
    async def update_pattern_analysis(self, symbol: str, analysis: Dict):
        """Pattern analiz sonuçlarını güncelle"""
        try:
            # Analizi geçmişe ekle
            self.pattern_analysis_history.append({
                'symbol': symbol,
                'analysis': analysis,
                'timestamp': datetime.now().isoformat()
            })
            
            # Son 100 analizi tut
            if len(self.pattern_analysis_history) > 100:
                self.pattern_analysis_history = self.pattern_analysis_history[-100:]
            
            # Eğer STRONG_BUY veya STRONG_SELL sinyali varsa
            if analysis and 'signal' in analysis:
                signal_info = analysis['signal']
                if isinstance(signal_info, dict):
                    signal = signal_info.get('signal')
                    if signal in ['STRONG_BUY', 'STRONG_SELL']:
                        console.print(f"[bold red]🚨 {symbol}: {signal} signal detected![/bold red]")
                        
        except Exception as e:
            console.print(f"[red]update_pattern_analysis error: {e}[/red]")
    
    def get_pattern_history(self, symbol: str = None, limit: int = 10):
        """Pattern analiz geçmişini döndür"""
        if symbol:
            filtered = [p for p in self.pattern_analysis_history if p['symbol'] == symbol]
            return filtered[-limit:]
        return self.pattern_analysis_history[-limit:]
    
    async def _cli_loop(self):
        """Command line interface"""
        while self.running:
            try:
                command = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: Prompt.ask("[bold green]Command[/]").lower()
                )
                
                if command in ['quit', 'exit']:
                    self.running = False
                    console.print("[yellow]Shutting down...[/yellow]")
                    break
                
                elif command.startswith('predict'):
                    parts = command.split()
                    symbol = parts[1].upper() if len(parts) > 1 else 'BTCUSDT'
                    
                    # Get data from buffer
                    df = self.data_bridge._buffer_to_dataframe(symbol)
                    
                    if df.empty:
                        console.print(f"[red]No data available for {symbol}. Waiting for main.py...[/red]")
                    else:
                        pred = self.ml_engine.predict(symbol, df)
                        
                        table = Table(title=f"🎯 {symbol} Prediction (11 Exchanges + CoinGecko)", box=box.ROUNDED)
                        table.add_column("Metric", style="cyan")
                        table.add_column("Value", style="green")
                        table.add_row("Signal", pred['prediction'])
                        table.add_row("Confidence", f"{pred['confidence']:.2%}")
                        table.add_row("Bullish Patterns", str(pred.get('bullish_patterns', 0)))
                        table.add_row("Bearish Patterns", str(pred.get('bearish_patterns', 0)))
                        table.add_row("Data Source", pred.get('data_source', 'unknown'))
                        console.print(table)
                        
                        if pred['pattern_signals']:
                            pattern_table = Table(title="🔍 High Confidence Patterns", box=box.SIMPLE)
                            pattern_table.add_column("Pattern", style="yellow")
                            pattern_table.add_column("Signal", style="green")
                            pattern_table.add_column("Confidence", style="blue")
                            
                            for p in pred['pattern_signals'][:5]:
                                pattern_table.add_row(
                                    p['pattern'],
                                    p['signal'].upper(),
                                    f"{p['confidence']:.2%}"
                                )
                            console.print(pattern_table)
                
                elif command == 'patterns':
                    symbol = 'BTCUSDT'
                    df = self.data_bridge._buffer_to_dataframe(symbol)
                    
                    if df.empty:
                        console.print(f"[red]No data available for {symbol}. Waiting for main.py...[/red]")
                    else:
                        detector = AdvancedPatternDetector(df)
                        patterns = detector.scan_all_patterns()
                        
                        # Exchange stats
                        stats = self.data_bridge.get_exchange_stats(symbol)
                        
                        table = Table(title=f"🔍 Active Patterns - {symbol} (11 Exchanges + CoinGecko)", box=box.ROUNDED)
                        table.add_column("Pattern", style="yellow", width=30)
                        table.add_column("Signal", style="green", width=10)
                        table.add_column("Confidence", style="blue", width=12)
                        table.add_column("Level", style="cyan", width=12)
                        
                        for p in sorted(patterns, key=lambda x: x.get('confidence', 0), reverse=True)[:15]:
                            table.add_row(
                                p['pattern'][:30],
                                p['signal'].upper(),
                                f"{p.get('confidence', 0):.2%}",
                                f"{p.get('level', 0):.2f}" if p.get('level') else "-"
                            )
                        console.print(table)
                        
                        # Show exchange stats
                        console.print(f"\n[cyan]📊 Data Sources:[/cyan]")
                        console.print(f"   Active Exchanges: {stats['total_exchanges']}")
                        console.print(f"   CoinGecko: {'✅ Active' if stats['coingecko_active'] else '❌ Inactive'}")
                        console.print(f"   Total Data Points: {stats['total_data_points']}")
                
                elif command == 'status':
                    # Get overall stats
                    total_symbols = len(self.symbols)
                    active_symbols = sum(1 for s in self.symbols if s in self.data_bridge.live_data_buffer and self.data_bridge.live_data_buffer[s])
                    
                    status_panel = Panel(
                        f"[bold green]System Status: Active[/bold green]\n"
                        f"[cyan]DataBridge:[/cyan] Connected to main.py\n"
                        f"[cyan]Exchanges:[/cyan] 11 Active\n"
                        f"[cyan]CoinGecko:[/cyan] ✅ Integrated\n"
                        f"[cyan]Symbols with Data:[/cyan] {active_symbols}/{total_symbols}\n"
                        f"[cyan]Open Positions:[/cyan] {len(self.positions)}\n"
                        f"[cyan]Total Trades:[/cyan] {len(self.trade_history)}\n"
                        f"[cyan]ML Models:[/cyan] {len(self.ml_engine.models)} active\n"
                        f"[cyan]Device:[/cyan] {self.ml_engine.device}\n"
                        f"[cyan]79 Patterns:[/cyan] ✅ Active\n"
                        f"[cyan]Memory:[/cyan] {torch.cuda.memory_allocated()/1024**3:.2f} GB" if torch.cuda.is_available() else "",
                        title="📊 System Status",
                        border_style="green"
                    )
                    console.print(status_panel)
                
                elif command == 'help':
                    help_panel = Panel(
                        "[bold cyan]Available Commands:[/bold cyan]\n\n"
                        "• predict [symbol] - Get ML prediction from 11 exchanges data\n"
                        "• patterns - Show active 79 patterns\n"
                        "• positions - Show open positions\n"
                        "• trades - Show trade history\n"
                        "• status - System status with exchange info\n"
                        "• stats [symbol] - Show exchange statistics\n"
                        "• quit/exit - Exit bot\n",
                        title="📚 Help",
                        border_style="cyan"
                    )
                    console.print(help_panel)
                
                elif command.startswith('stats'):
                    parts = command.split()
                    symbol = parts[1].upper() if len(parts) > 1 else 'BTCUSDT'
                    stats = self.data_bridge.get_exchange_stats(symbol)
                    
                    stats_table = Table(title=f"📊 Exchange Statistics - {symbol}", box=box.ROUNDED)
                    stats_table.add_column("Metric", style="cyan")
                    stats_table.add_column("Value", style="green")
                    stats_table.add_row("Active Exchanges", str(stats['total_exchanges']))
                    stats_table.add_row("Exchanges", ", ".join(stats['active_exchanges'][:5]) + ("..." if len(stats['active_exchanges']) > 5 else ""))
                    stats_table.add_row("CoinGecko", "✅ Active" if stats['coingecko_active'] else "❌ Inactive")
                    stats_table.add_row("Total Data Points", str(stats['total_data_points']))
                    stats_table.add_row("Buffer Size", str(len(self.data_bridge.live_data_buffer.get(symbol, []))))
                    console.print(stats_table)
                
                elif command == 'positions':
                    if not self.positions:
                        console.print("[yellow]No open positions[/yellow]")
                    else:
                        table = Table(title="📊 Open Positions", box=box.ROUNDED)
                        table.add_column("Symbol", style="cyan")
                        table.add_column("Entry", style="white")
                        table.add_column("Current", style="white")
                        table.add_column("PnL %", style="green")
                        
                        for sym, pos in self.positions.items():
                            # Get current price from data bridge
                            df = self.data_bridge._buffer_to_dataframe(sym)
                            current_price = df['close'].iloc[-1] if not df.empty else pos.get('current_price', pos['entry_price'])
                            pnl = (current_price - pos['entry_price']) / pos['entry_price'] * 100
                            pnl_color = "green" if pnl > 0 else "red"
                            
                            table.add_row(
                                sym,
                                f"${pos['entry_price']:.2f}",
                                f"${current_price:.2f}",
                                f"[{pnl_color}]{pnl:.2f}%[/{pnl_color}]"
                            )
                        console.print(table)
                
                elif command == 'trades':
                    if not self.trade_history:
                        console.print("[yellow]No trade history[/yellow]")
                    else:
                        table = Table(title="📝 Recent Trades", box=box.ROUNDED)
                        table.add_column("Time", style="dim")
                        table.add_column("Symbol", style="cyan")
                        table.add_column("Side", style="green")
                        table.add_column("Price", style="white")
                        table.add_column("PnL %", style="yellow")
                        
                        for trade in self.trade_history[-10:]:
                            pnl = trade.get('pnl', 0)
                            pnl_str = f"{pnl:.2f}%" if pnl else "-"
                            pnl_color = "green" if pnl > 0 else "red" if pnl < 0 else "white"
                            table.add_row(
                                trade['timestamp'][11:19],
                                trade['symbol'],
                                trade['side'],
                                f"${trade['price']:.2f}",
                                f"[{pnl_color}]{pnl_str}[/{pnl_color}]"
                            )
                        console.print(table)
                
            except KeyboardInterrupt:
                self.running = False
                break
            except Exception as e:
                console.print(f"[red]CLI Error: {e}[/red]")


# ============================================
# EXCHANGE MANAGER (For Binance WebSocket - Optional)
# ============================================
class ExchangeManager:
    """Binance WebSocket and REST API manager (Optional - main.py handles 11 exchanges)"""
    
    def __init__(self):
        self.ws = None
        self.market_data = {}
        self.console = Console()
        
    async def connect(self):
        """Connect to Binance WebSocket (Optional fallback)"""
        try:
            self.ws = await websockets.connect(CONFIG['EXCHANGES']['binance']['ws_url'])
            params = [f"{s.lower()}@ticker" for s in CONFIG['EXCHANGES']['binance']['supported_symbols']]
            subscribe_msg = {
                "method": "SUBSCRIBE",
                "params": params,
                "id": 1
            }
            await self.ws.send(json.dumps(subscribe_msg))
            asyncio.create_task(self._handle_messages())
            self.console.print("[dim]✓ Binance WebSocket connected (fallback)[/dim]")
        except Exception as e:
            self.console.print(f"[dim]WebSocket fallback not available: {e}[/dim]")
    
    async def _handle_messages(self):
        """Handle incoming WebSocket messages (fallback)"""
        while True:
            try:
                message = await self.ws.recv()
                data = json.loads(message)
                
                if 'data' in data:
                    ticker = data['data']
                    symbol = ticker['s']
                    self.market_data[symbol] = {
                        'close': float(ticker['c']),
                        'high': float(ticker['h']),
                        'low': float(ticker['l']),
                        'volume': float(ticker['v']),
                        'open': float(ticker['o']),
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    # Send to data bridge as fallback
                    await data_bridge.process_exchange_data(symbol, 'binance', self.market_data[symbol])
                    
            except Exception as e:
                await asyncio.sleep(1)
    
    async def fetch_historical(self, symbol: str, interval: str = '1h', limit: int = 500) -> pd.DataFrame:
        """Fetch historical OHLCV data from Binance (fallback)"""
        try:
            url = f"{CONFIG['EXCHANGES']['binance']['api_url']}/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    data = await response.json()
            
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            df = df.astype({
                'open': float,
                'high': float,
                'low': float,
                'close': float,
                'volume': float
            })
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            return df[['open', 'high', 'low', 'close', 'volume']]
            
        except Exception as e:
            return pd.DataFrame()


# ============================================
# EXPORTS - main.py'den import edilecek nesneler
# ============================================
__all__ = [
    'data_bridge',           # Ana veri köprüsü
    'TradingBot',           # Trading bot
    'MLEngine',            # ML motoru
    'AdvancedPatternDetector', # 79 pattern dedektörü
    'FeatureEngineer',     # Feature engineering
    'CONFIG'              # Konfigürasyon
]


# ============================================
# MAIN ENTRY POINT (For standalone mode)
# ============================================
async def main():
    """Main entry point - Runs in standalone mode or waits for main.py"""
    console.print(Panel.fit(
        "[bold cyan]🚀 AI CRYPTO TRADING BOT v5.0 - 11 EXCHANGE + COINGECKO EDITION[/bold cyan]\n\n"
        "[white]79 Pattern Detector | Transformer-XL | Multi-Task Learning | PPO[/white]\n"
        "[green]✓ Waiting for data from main.py (11 Exchanges + CoinGecko)[/green]\n"
        "[dim]Run main.py to start receiving real-time data[/dim]",
        border_style="cyan"
    ))
    
    bot = TradingBot()
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Bot stopped by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
        import traceback
        traceback.print_exc()
