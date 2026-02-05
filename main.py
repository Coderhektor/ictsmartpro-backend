"""
🚀 PROFESSIONAL TRADING BOT v4.0 - ADVANCED AI TRADING SYSTEM
✅ TradingView Integration ✅ EMA Crossovers ✅ RSI ✅ Heikin Ashi
✅ 12 Candlestick Patterns ✅ ICT Market Structure ✅ Multi-Timeframe
✅ Advanced ML (LSTM + Transformer) ✅ Image/Graph Analysis
✅ AI Chatbot ✅ Binance WebSocket ✅ CoinGecko API
✅ High-Confidence Signals ✅ Real-time Data ✅ Risk Management
"""

import os
import logging
from datetime import datetime, timedelta
import random
import json
import asyncio
from typing import Dict, List, Optional, Tuple
import aiohttp
from enum import Enum

# Machine Learning Libraries
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader, TensorDataset
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, classification_report
import lightgbm as lgb
from lightgbm import early_stopping

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('trading_bot.log')
    ]
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

# FastAPI Application
app = FastAPI(
    title="Professional AI Trading Bot v4.0",
    version="4.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== SIGNAL TYPES ==========
class SignalType(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"

class SignalConfidence(str, Enum):
    VERY_HIGH = "VERY_HIGH"  # 85%+
    HIGH = "HIGH"            # 70-85%
    MEDIUM = "MEDIUM"        # 55-70%
    LOW = "LOW"              # <55%

# ========== ADVANCED DEEP LEARNING MODELS ==========
class AdvancedLSTM(nn.Module):
    def __init__(self, input_size, hidden_size=256, num_layers=3, output_size=3, dropout=0.3):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0,
            bidirectional=True
        )
        self.attention = nn.MultiheadAttention(
            embed_dim=hidden_size * 2,
            num_heads=8,
            batch_first=True
        )
        self.fc1 = nn.Linear(hidden_size * 2, 128)
        self.fc2 = nn.Linear(128, output_size)
        self.dropout = nn.Dropout(dropout)
        self.layer_norm = nn.LayerNorm(hidden_size * 2)
        
    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        attn_out, _ = self.attention(lstm_out, lstm_out, lstm_out)
        attn_out = self.layer_norm(lstm_out + attn_out)
        x = attn_out[:, -1, :]
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        return self.fc2(x)

class AdvancedTransformer(nn.Module):
    def __init__(self, input_size, d_model=256, nhead=8, num_layers=3, output_size=3, dropout=0.3):
        super().__init__()
        self.embedding = nn.Linear(input_size, d_model)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=512,
            dropout=dropout,
            batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers)
        self.fc = nn.Linear(d_model, output_size)
        
    def forward(self, x):
        x = self.embedding(x)
        x = self.transformer(x)
        x = x[:, -1, :]
        return self.fc(x)

# ========== AI TRADING ENGINE ==========
class AITradingEngine:
    def __init__(self, device=None):
        self.device = device if device else torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.models = {}
        self.scalers = {}
        self.lgb_models = {}
        self.feature_columns = None
        logger.info(f"AI Trading Engine initialized on device: {self.device}")
    
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create comprehensive trading features"""
        try:
            df = df.copy()
            
            if len(df) < 50:
                logger.warning(f"Insufficient data for feature creation: {len(df)} rows")
                return pd.DataFrame()
            
            # Ensure required columns
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            missing = [col for col in required_cols if col not in df.columns]
            if missing:
                logger.error(f"Missing required columns: {missing}")
                return pd.DataFrame()
            
            # Price-based features
            df['returns'] = df['close'].pct_change()
            df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
            
            # Volatility features
            for window in [5, 10, 20, 50]:
                df[f'volatility_{window}'] = df['returns'].rolling(window).std()
                df[f'atr_{window}'] = (df['high'] - df['low']).rolling(window).mean()
            
            # Moving averages
            for period in [5, 9, 20, 50, 100, 200]:
                if len(df) >= period:
                    df[f'sma_{period}'] = df['close'].rolling(period).mean()
                    df[f'ema_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
                    df[f'price_sma_ratio_{period}'] = df['close'] / df[f'sma_{period}']
            
            # RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # MACD
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            df['macd'] = exp1 - exp2
            df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
            df['macd_hist'] = df['macd'] - df['macd_signal']
            
            # Bollinger Bands
            df['bb_middle'] = df['close'].rolling(20).mean()
            bb_std = df['close'].rolling(20).std()
            df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
            df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
            df['bb_width'] = df['bb_upper'] - df['bb_lower']
            df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
            
            # Volume features
            df['volume_sma_20'] = df['volume'].rolling(20).mean()
            df['volume_ratio'] = df['volume'] / df['volume_sma_20']
            df['obv'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
            
            # Price patterns
            df['high_low_pct'] = (df['high'] - df['low']) / df['close'] * 100
            df['close_open_pct'] = (df['close'] - df['open']) / df['open'] * 100
            
            # Momentum indicators
            df['momentum_5'] = df['close'].pct_change(5)
            df['momentum_10'] = df['close'].pct_change(10)
            df['roc'] = ((df['close'] - df['close'].shift(10)) / df['close'].shift(10)) * 100
            
            # Support/Resistance
            df['resistance'] = df['high'].rolling(20).max()
            df['support'] = df['low'].rolling(20).min()
            df['distance_to_resistance'] = (df['resistance'] - df['close']) / df['close'] * 100
            df['distance_to_support'] = (df['close'] - df['support']) / df['close'] * 100
            
            # Lagged features
            for lag in [1, 2, 3, 5, 10]:
                df[f'returns_lag_{lag}'] = df['returns'].shift(lag)
                df[f'close_lag_{lag}'] = df['close'].shift(lag)
            
            # Target creation (3-class classification)
            future_return = df['close'].shift(-5) / df['close'] - 1
            
            # Use dynamic percentiles
            upper_threshold = future_return.quantile(0.65)
            lower_threshold = future_return.quantile(0.35)
            
            df['target'] = np.where(
                future_return > upper_threshold, 2,  # Buy
                np.where(
                    future_return < lower_threshold, 0,  # Sell
                    1  # Hold
                )
            )
            
            # Drop NaN values
            df = df.dropna()
            
            # Store feature columns
            non_feature_cols = ['target', 'timestamp', 'datetime', 'date', 'time']
            self.feature_columns = [col for col in df.columns if col not in non_feature_cols]
            
            logger.info(f"Created {len(self.feature_columns)} features, {len(df)} samples")
            return df
            
        except Exception as e:
            logger.error(f"Error in create_features: {str(e)}")
            return pd.DataFrame()
    
    def prepare_sequences(self, df: pd.DataFrame, sequence_length: int = 60) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare sequential data for LSTM/Transformer"""
        if self.feature_columns is None or len(df) < sequence_length:
            return np.array([]), np.array([])
        
        try:
            features = df[self.feature_columns].values
            targets = df['target'].values
            
            X, y = [], []
            for i in range(len(features) - sequence_length):
                X.append(features[i:i+sequence_length])
                y.append(targets[i+sequence_length])
            
            return np.array(X), np.array(y)
        except Exception as e:
            logger.error(f"Error in prepare_sequences: {str(e)}")
            return np.array([]), np.array([])
    
    async def train_models(self, symbol: str, df: pd.DataFrame) -> bool:
        """Train all ML models for a symbol"""
        try:
            logger.info(f"Training models for {symbol} with {len(df)} data points")
            
            # Create features
            df_features = self.create_features(df)
            if len(df_features) < 100:
                logger.warning(f"Insufficient features for {symbol}: {len(df_features)} samples")
                return False
            
            # Prepare sequences
            X, y = self.prepare_sequences(df_features, sequence_length=60)
            if len(X) < 100:
                logger.warning(f"Insufficient sequences for {symbol}: {len(X)} sequences")
                return False
            
            # Split data
            split_idx = int(len(X) * 0.8)
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train, y_val = y[:split_idx], y[split_idx:]
            
            # Scale features
            scaler = StandardScaler()
            X_train_flat = X_train.reshape(-1, X_train.shape[-1])
            X_val_flat = X_val.reshape(-1, X_val.shape[-1])
            
            X_train_scaled = scaler.fit_transform(X_train_flat).reshape(X_train.shape)
            X_val_scaled = scaler.transform(X_val_flat).reshape(X_val.shape)
            
            self.scalers[symbol] = scaler
            
            # Train LightGBM (flattened features)
            await self._train_lightgbm(symbol, X_train_flat, y_train, X_val_flat, y_val)
            
            # Train LSTM
            await self._train_lstm(symbol, X_train_scaled, y_train, X_val_scaled, y_val)
            
            # Train Transformer
            await self._train_transformer(symbol, X_train_scaled, y_train, X_val_scaled, y_val)
            
            logger.info(f"✅ Successfully trained all models for {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"Error training models for {symbol}: {str(e)}", exc_info=True)
            return False
    
    async def _train_lightgbm(self, symbol: str, X_train, y_train, X_val, y_val):
        """Train LightGBM model"""
        try:
            # Convert to numpy arrays
            X_train = np.array(X_train)
            y_train = np.array(y_train)
            X_val = np.array(X_val)
            y_val = np.array(y_val)
            
            # LightGBM parameters
            params = {
                'objective': 'multiclass',
                'num_class': 3,
                'metric': 'multi_logloss',
                'boosting_type': 'gbdt',
                'num_leaves': 31,
                'learning_rate': 0.05,
                'feature_fraction': 0.9,
                'bagging_fraction': 0.8,
                'bagging_freq': 5,
                'verbose': -1,
                'seed': 42
            }
            
            # Create datasets
            train_data = lgb.Dataset(X_train, label=y_train)
            val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
            
            # Train model
            model = lgb.train(
                params,
                train_data,
                valid_sets=[val_data],
                num_boost_round=1000,
                callbacks=[early_stopping(50), lgb.log_evaluation(100)]
            )
            
            self.lgb_models[symbol] = model
            
            # Evaluate
            y_pred = model.predict(X_val)
            y_pred_class = np.argmax(y_pred, axis=1)
            accuracy = accuracy_score(y_val, y_pred_class)
            
            logger.info(f"✅ LightGBM trained for {symbol}. Validation accuracy: {accuracy:.4f}")
            
        except Exception as e:
            logger.error(f"Error training LightGBM for {symbol}: {str(e)}")
    
    async def _train_lstm(self, symbol: str, X_train, y_train, X_val, y_val):
        """Train LSTM model"""
        try:
            # Convert to tensors
            X_train_t = torch.FloatTensor(X_train).to(self.device)
            y_train_t = torch.LongTensor(y_train).to(self.device)
            X_val_t = torch.FloatTensor(X_val).to(self.device)
            y_val_t = torch.LongTensor(y_val).to(self.device)
            
            # Create model
            input_size = X_train.shape[-1]
            model = AdvancedLSTM(input_size=input_size).to(self.device)
            
            # Training setup
            criterion = nn.CrossEntropyLoss()
            optimizer = optim.Adam(model.parameters(), lr=0.001, weight_decay=1e-5)
            scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)
            
            batch_size = min(32, len(X_train_t))
            train_dataset = TensorDataset(X_train_t, y_train_t)
            train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
            
            # Training loop
            best_acc = 0
            for epoch in range(30):
                model.train()
                train_loss = 0
                
                for batch_X, batch_y in train_loader:
                    optimizer.zero_grad()
                    outputs = model(batch_X)
                    loss = criterion(outputs, batch_y)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                    optimizer.step()
                    train_loss += loss.item()
                
                # Validation
                model.eval()
                with torch.no_grad():
                    val_outputs = model(X_val_t)
                    val_loss = criterion(val_outputs, y_val_t).item()
                    val_pred = torch.argmax(val_outputs, dim=1).cpu().numpy()
                    val_acc = accuracy_score(y_val, val_pred)
                
                scheduler.step(val_loss)
                
                if val_acc > best_acc:
                    best_acc = val_acc
                    self.models[f"{symbol}_lstm"] = model
                
                if (epoch + 1) % 10 == 0:
                    logger.info(f"LSTM {symbol} Epoch {epoch+1}: Val Loss {val_loss:.4f}, Acc {val_acc:.4f}")
            
            logger.info(f"✅ LSTM trained for {symbol}. Best accuracy: {best_acc:.4f}")
            
        except Exception as e:
            logger.error(f"Error training LSTM for {symbol}: {str(e)}")
    
    async def _train_transformer(self, symbol: str, X_train, y_train, X_val, y_val):
        """Train Transformer model"""
        try:
            # Convert to tensors
            X_train_t = torch.FloatTensor(X_train).to(self.device)
            y_train_t = torch.LongTensor(y_train).to(self.device)
            X_val_t = torch.FloatTensor(X_val).to(self.device)
            y_val_t = torch.LongTensor(y_val).to(self.device)
            
            # Create model
            input_size = X_train.shape[-1]
            model = AdvancedTransformer(input_size=input_size).to(self.device)
            
            # Training setup
            criterion = nn.CrossEntropyLoss()
            optimizer = optim.Adam(model.parameters(), lr=0.0005, weight_decay=1e-5)
            scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=30)
            
            batch_size = min(32, len(X_train_t))
            train_dataset = TensorDataset(X_train_t, y_train_t)
            train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
            
            # Training loop
            best_acc = 0
            for epoch in range(30):
                model.train()
                train_loss = 0
                
                for batch_X, batch_y in train_loader:
                    optimizer.zero_grad()
                    outputs = model(batch_X)
                    loss = criterion(outputs, batch_y)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                    optimizer.step()
                    train_loss += loss.item()
                
                scheduler.step()
                
                # Validation
                model.eval()
                with torch.no_grad():
                    val_outputs = model(X_val_t)
                    val_loss = criterion(val_outputs, y_val_t).item()
                    val_pred = torch.argmax(val_outputs, dim=1).cpu().numpy()
                    val_acc = accuracy_score(y_val, val_pred)
                
                if val_acc > best_acc:
                    best_acc = val_acc
                    self.models[f"{symbol}_transformer"] = model
                
                if (epoch + 1) % 10 == 0:
                    logger.info(f"Transformer {symbol} Epoch {epoch+1}: Val Loss {val_loss:.4f}, Acc {val_acc:.4f}")
            
            logger.info(f"✅ Transformer trained for {symbol}. Best accuracy: {best_acc:.4f}")
            
        except Exception as e:
            logger.error(f"Error training Transformer for {symbol}: {str(e)}")
    
    def predict(self, symbol: str, df: pd.DataFrame) -> Dict:
        """Generate predictions from all models - daha güvenli versiyon"""
        try:
            if df.empty or len(df) < 30:
                return {
                    'prediction': 'NEUTRAL',
                    'confidence': 0.50,
                    'method': 'fallback_insufficient_data',
                    'ml_score': 0.5,
                    'model_details': {}
                }

            df_features = self.create_features(df)
            if len(df_features) < 60 or not self.feature_columns:
                return {
                    'prediction': 'NEUTRAL',
                    'confidence': 0.50,
                    'method': 'fallback_feature_creation_failed',
                    'ml_score': 0.5,
                    'model_details': {}
                }

            # Son 60 satırı al, eksikse padding yap
            features = df_features[self.feature_columns].values
            seq_len = 60
            if len(features) < seq_len:
                pad_len = seq_len - len(features)
                pad = np.zeros((pad_len, features.shape[1]))
                features = np.vstack([pad, features])

            recent_seq = features[-seq_len:].reshape(1, seq_len, -1)
            predictions = []
            confidences = []
            model_details = {}

            # LSTM tahmini
            lstm_key = f"{symbol}_lstm"
            if lstm_key in self.models and symbol in self.scalers:
                try:
                    model = self.models[lstm_key]
                    model.eval()
                    scaler = self.scalers[symbol]
                    
                    recent_flat = recent_seq.reshape(-1, recent_seq.shape[-1])
                    recent_scaled = scaler.transform(recent_flat).reshape(recent_seq.shape)
                    recent_t = torch.FloatTensor(recent_scaled).to(self.device)
                    
                    with torch.no_grad():
                        output = model(recent_t)
                        prob = F.softmax(output, dim=1)[0].cpu().numpy()
                        pred = int(np.argmax(prob))
                        confidence = float(np.max(prob))
                        
                        predictions.append(pred)
                        confidences.append(confidence)
                        model_details['lstm'] = {
                            'prediction': pred,
                            'confidence': confidence,
                            'probabilities': prob.tolist()
                        }
                except Exception as e:
                    logger.warning(f"LSTM prediction failed for {symbol}: {e}")

            # Transformer tahmini (aynı mantıkla)
            trans_key = f"{symbol}_transformer"
            if trans_key in self.models and symbol in self.scalers:
                try:
                    model = self.models[trans_key]
                    model.eval()
                    scaler = self.scalers[symbol]
                    
                    recent_flat = recent_seq.reshape(-1, recent_seq.shape[-1])
                    recent_scaled = scaler.transform(recent_flat).reshape(recent_seq.shape)
                    recent_t = torch.FloatTensor(recent_scaled).to(self.device)
                    
                    with torch.no_grad():
                        output = model(recent_t)
                        prob = F.softmax(output, dim=1)[0].cpu().numpy()
                        pred = int(np.argmax(prob))
                        confidence = float(np.max(prob))
                        
                        predictions.append(pred)
                        confidences.append(confidence)
                        model_details['transformer'] = {
                            'prediction': pred,
                            'confidence': confidence,
                            'probabilities': prob.tolist()
                        }
                except Exception as e:
                    logger.warning(f"Transformer prediction failed for {symbol}: {e}")

            # LightGBM tahmini
            if symbol in self.lgb_models and symbol in self.scalers:
                try:
                    model = self.lgb_models[symbol]
                    scaler = self.scalers[symbol]
                    
                    recent_flat = recent_seq.reshape(-1, recent_seq.shape[-1])
                    recent_scaled = scaler.transform(recent_flat)
                    recent_features = recent_scaled[-1:].reshape(1, -1)  # son satır
                    
                    prob = model.predict(recent_features)[0]
                    pred = int(np.argmax(prob))
                    confidence = float(np.max(prob))
                    
                    predictions.append(pred)
                    confidences.append(confidence)
                    model_details['lightgbm'] = {
                        'prediction': pred,
                        'confidence': confidence,
                        'probabilities': prob.tolist()
                    }
                except Exception as e:
                    logger.warning(f"LightGBM prediction failed for {symbol}: {e}")

            # Ensemble
            if not predictions:
                return {
                    'prediction': 'NEUTRAL',
                    'confidence': 0.50,
                    'method': 'no_valid_models',
                    'ml_score': 0.5,
                    'model_details': {}
                }

            # En basit ensemble: çoğunluk + ağırlıklı güven
            from collections import Counter
            weighted_votes = []
            for p, c in zip(predictions, confidences):
                weighted_votes.extend([p] * int(c * 20))  # güveni oya çevir

            if weighted_votes:
                final_pred = Counter(weighted_votes).most_common(1)[0][0]
                avg_conf = sum(confidences) / len(confidences)
            else:
                final_pred = 1  # neutral
                avg_conf = 0.5

            pred_map = {0: 'SELL', 1: 'NEUTRAL', 2: 'BUY'}
            signal_str = pred_map.get(final_pred, 'NEUTRAL')

            if avg_conf > 0.75:
                if signal_str == 'BUY':   signal_str = 'STRONG_BUY'
                if signal_str == 'SELL':  signal_str = 'STRONG_SELL'

            return {
                'prediction': signal_str,
                'confidence': float(avg_conf),
                'method': 'ensemble',
                'ml_score': float(final_pred),
                'model_details': model_details
            }

        except Exception as e:
            logger.error(f"Critical prediction error for {symbol}: {str(e)}", exc_info=True)
            return {
                'prediction': 'NEUTRAL',
                'confidence': 0.40,
                'method': 'error_fallback',
                'ml_score': 0.5,
                'error': str(e)
            }
    
    def get_feature_importance(self, symbol: str) -> Dict:
        """Get feature importance from LightGBM model"""
        if symbol not in self.lgb_models or self.feature_columns is None:
            return {}
        
        try:
            model = self.lgb_models[symbol]
            importance = model.feature_importance(importance_type='gain')
            
            # Create importance dictionary
            importance_dict = {}
            for i, imp in enumerate(importance):
                if i < len(self.feature_columns):
                    importance_dict[self.feature_columns[i]] = float(imp)
            
            # Sort by importance
            sorted_importance = dict(sorted(
                importance_dict.items(),
                key=lambda x: x[1],
                reverse=True
            )[:15])  # Top 15 features
            
            return sorted_importance
        except Exception as e:
            logger.error(f"Error getting feature importance for {symbol}: {str(e)}")
            return {}

# ========== AI CHATBOT MODULE ==========
class TradingChatBot:
    """AI Trading Assistant Chatbot"""
    
    def __init__(self, ai_engine=None, price_fetcher=None):
        self.ai_engine = ai_engine
        self.price_fetcher = price_fetcher
        self.context = []
        self.knowledge_base = {
            "patterns": {
                "hammer": "Bullish reversal pattern at support. Small body with long lower shadow.",
                "shooting star": "Bearish reversal at resistance. Small body with long upper shadow.",
                "engulfing": "Strong reversal pattern where one candle completely engulfs the previous.",
                "doji": "Indecision pattern showing market equilibrium.",
                "morning star": "Very strong bullish reversal. Three-candle pattern.",
                "evening star": "Very strong bearish reversal. Three-candle pattern."
            },
            "indicators": {
                "rsi": "Relative Strength Index (14). >70 overbought, <30 oversold.",
                "macd": "Moving Average Convergence Divergence. Bullish when MACD crosses above signal.",
                "ema": "Exponential Moving Average. Faster reaction than SMA.",
                "heikin ashi": "Smoothed candlestick chart showing trend direction clearly.",
                "bollinger bands": "Volatility indicator. Price touching upper band = overbought, lower = oversold."
            },
            "strategies": {
                "trend following": "Trade in direction of EMA crossovers and higher highs/lows.",
                "mean reversion": "Trade RSI extremes back to middle range.",
                "breakout": "Trade breakouts from consolidation with increased volume.",
                "swing trading": "Hold positions for days/weeks based on higher timeframe trends."
            },
            "ict": {
                "fair value gap": "Price gap that often gets filled. Can act as support/resistance.",
                "order block": "Area where big players entered trades. Often acts as reversal zone.",
                "market structure": "Higher highs + higher lows = bullish. Lower highs + lower lows = bearish."
            }
        }
    
    async def process_message(self, message: str, symbol: str = None) -> str:
        """Process user message and generate response"""
        try:
            # Add to context
            self.context.append(f"User: {message}")
            if len(self.context) > 20:
                self.context = self.context[-20:]
            
            lower_msg = message.lower()
            
            # Greetings
            if any(word in lower_msg for word in ["hello", "hi", "hey", "greetings"]):
                return "🤖 Hello! I'm your AI trading assistant. I can help with technical analysis, pattern recognition, and trading strategies. How can I assist you today?"
            
            # Price queries
            if "price" in lower_msg or "current" in lower_msg:
                if symbol and self.price_fetcher:
                    candles = await self.price_fetcher.get_candles(symbol, "1h", 2)
                    if candles and len(candles) >= 2:
                        current = candles[-1]["close"]
                        previous = candles[-2]["close"]
                        change = ((current - previous) / previous) * 100
                        return f"📊 {symbol}: ${current:,.2f} ({'▲' if change >= 0 else '▼'} {abs(change):.2f}%)"
            
            # Pattern explanations
            for pattern, explanation in self.knowledge_base["patterns"].items():
                if pattern in lower_msg:
                    return f"📈 **{pattern.upper()}**: {explanation}"
            
            # Indicator explanations
            for indicator, explanation in self.knowledge_base["indicators"].items():
                if indicator in lower_msg:
                    return f"📊 **{indicator.upper()}**: {explanation}"
            
            # ICT concepts
            for concept, explanation in self.knowledge_base["ict"].items():
                if concept in lower_msg:
                    return f"🎯 **{concept.upper()}**: {explanation}"
            
            # Strategy advice
            if "strategy" in lower_msg or "how to trade" in lower_msg:
                return self._get_strategy_advice(lower_msg)
            
            # Analysis request
            if "analyze" in lower_msg and symbol and self.price_fetcher:
                return await self._analyze_symbol(symbol)
            
            # ML prediction request
            if "predict" in lower_msg or "forecast" in lower_msg:
                if symbol and self.ai_engine and self.price_fetcher:
                    df = pd.DataFrame(await self.price_fetcher.get_candles(symbol, "1h", 200))
                    if not df.empty:
                        df.set_index('timestamp', inplace=True)
                        prediction = self.ai_engine.predict(symbol, df)
                        signal = prediction.get('prediction', 'NEUTRAL')
                        confidence = prediction.get('confidence', 0) * 100
                        return f"🤖 ML Prediction for {symbol}: **{signal}** ({confidence:.1f}% confidence)"
            
            # General advice
            if any(word in lower_msg for word in ["advice", "tip", "suggest"]):
                tips = [
                    "Always use stop-loss orders. Risk management is key!",
                    "Trade with the trend - it increases your probability of success.",
                    "Don't overtrade. Quality over quantity.",
                    "Keep a trading journal to track your performance.",
                    "Use multiple time frame analysis for confirmation.",
                    "Never risk more than 1-2% of your capital on a single trade."
                ]
                return f"💡 **Trading Tip**: {random.choice(tips)}"
            
            # Default response
            responses = [
                "I can help you with technical analysis, explain patterns and indicators, or analyze specific symbols. What would you like to know?",
                "Try asking about specific patterns like 'hammer' or 'engulfing', indicators like 'RSI' or 'MACD', or request an analysis of a trading symbol.",
                "You can ask me to analyze a symbol, explain trading concepts, or provide strategy advice. How can I help?"
            ]
            return random.choice(responses)
            
        except Exception as e:
            logger.error(f"Chat error: {str(e)}")
            return "I encountered an error processing your request. Please try again."
    
    def _get_strategy_advice(self, message: str) -> str:
        """Provide strategy advice"""
        if "trend" in message:
            return """**Trend Following Strategy**:
1. Identify trend using EMA crossovers (9/21)
2. Enter on pullbacks to EMA support/resistance
3. Use Heikin Ashi for trend confirmation
4. Stop loss below recent swing low (bullish) or above swing high (bearish)
5. Target: 2:1 risk/reward ratio"""
        
        elif "swing" in message:
            return """**Swing Trading Strategy**:
1. Use 4H/Daily charts for direction
2. Enter on 1H/4H chart patterns
3. Look for RSI extremes (30/70) for entries
4. Use ICT order blocks for precise entries
5. Hold for 2-10 days, target 5-15% moves"""
        
        elif "scalp" in message:
            return """**Scalping Strategy**:
1. Use 1M/5M charts
2. Trade during high volume hours
3. Use strict 0.5-1% stop loss
4. Target 1:1 or 1:1.5 risk/reward
5. Take profits quickly, never hold overnight"""
        
        else:
            return """**General Trading Principles**:
1. **Risk Management**: Never risk more than 1-2% per trade
2. **Trend is Your Friend**: Trade in direction of higher timeframe trend
3. **Confirmation**: Use multiple indicators/patterns
4. **Patience**: Wait for high-probability setups
5. **Discipline**: Stick to your trading plan"""
    
    async def _analyze_symbol(self, symbol: str) -> str:
        """Analyze a symbol and provide summary"""
        try:
            if not self.price_fetcher:
                return "Price fetcher not available"
                
            candles = await self.price_fetcher.get_candles(symbol, "1h", 100)
            if not candles:
                return f"Could not fetch data for {symbol}"
            
            # Basic analysis
            current = candles[-1]["close"]
            prev_close = candles[-2]["close"] if len(candles) > 1 else current
            change = ((current - prev_close) / prev_close) * 100
            
            # Calculate some basic metrics
            highs = [c["high"] for c in candles[-20:]]
            lows = [c["low"] for c in candles[-20:]]
            avg_volume = np.mean([c["volume"] for c in candles[-20:]])
            
            return f"""📊 **{symbol} Analysis**:
• **Price**: ${current:,.2f} ({'▲' if change >= 0 else '▼'} {abs(change):.2f}%)
• **Recent Range**: ${min(lows):,.2f} - ${max(highs):,.2f}
• **Avg Volume**: {avg_volume:,.0f}
• **Data Points**: {len(candles)} candles

For detailed technical analysis, use the `/api/analyze/{symbol}` endpoint."""
        
        except Exception as e:
            logger.error(f"Analysis error in chat: {str(e)}")
            return f"Error analyzing {symbol}. Please try again."

# ========== HEALTH ENDPOINTS ==========
@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Professional Trading Bot</title>
        <meta http-equiv="refresh" content="0;url=/dashboard">
    </head>
    <body><p>Loading Trading Dashboard...</p></body>
    </html>
    """

@app.get("/health")
def health():
    return {"status": "healthy", "version": "4.0.0"}

@app.get("/ready")
async def ready_check():
    return PlainTextResponse("READY")

@app.get("/live")
async def liveness_probe():
    return {"status": "alive", "timestamp": datetime.utcnow().isoformat()}

# ========== PRICE DATA MODULE ==========
class PriceFetcher:
    """
    Profesyonel Çoklu Borsa Veri Toplayıcı
    - Tüm timeframe'ler: 1m, 5m, 15m, 30m, 1h, 4h, 1D, 1W, 1M
    - 10+ borsa desteği + CoinGecko fallback
    - Aggregate havuz sistemi
    - Sadece gerçek veriler, sentetik veri YOK
    - Otomatik failover
    - Smart caching
    """

    # Desteklenen tüm borsalar ve API detayları
    EXCHANGES = [
        {
            "name": "Binance",
            "priority": 1,  # En yüksek öncelik
            "symbol_fmt": lambda s: s,
            "endpoint": "https://api.binance.com/api/v3/klines",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "symbol": s,
                "interval": i,
                "limit": l
            }
        },
        {
            "name": "Bybit",
            "priority": 2,
            "symbol_fmt": lambda s: s,
            "endpoint": "https://api.bybit.com/v5/market/kline",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "category": "spot",
                "symbol": s,
                "interval": i,
                "limit": l
            }
        },
        {
            "name": "OKX",
            "priority": 3,
            "symbol_fmt": lambda s: s.replace("USDT", "-USDT"),
            "endpoint": "https://www.okx.com/api/v5/market/candles",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "instId": s,
                "bar": i,
                "limit": str(l)
            }
        },
        {
            "name": "KuCoin",
            "priority": 4,
            "symbol_fmt": lambda s: s.replace("USDT", "-USDT"),
            "endpoint": "https://api.kucoin.com/api/v1/market/candles",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "symbol": s,
                "type": i
            }
        },
        {
            "name": "Gate.io",
            "priority": 5,
            "symbol_fmt": lambda s: s.replace("USDT", "_USDT"),
            "endpoint": "https://api.gateio.ws/api/v4/spot/candlesticks",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "currency_pair": s,
                "interval": i,
                "limit": l
            }
        },
        {
            "name": "MEXC",
            "priority": 6,
            "symbol_fmt": lambda s: s,
            "endpoint": "https://api.mexc.com/api/v3/klines",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "symbol": s,
                "interval": i,
                "limit": l
            }
        },
        {
            "name": "Kraken",
            "priority": 7,
            "symbol_fmt": lambda s: s.replace("USDT", "USD"),
            "endpoint": "https://api.kraken.com/0/public/OHLC",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "pair": s,
                "interval": i
            }
        },
        {
            "name": "Bitfinex",
            "priority": 8,
            "symbol_fmt": lambda s: f"t{s.replace('USDT', 'UST')}",
            "endpoint_builder": lambda s, i: f"https://api-pub.bitfinex.com/v2/candles/trade:{i}:{s}/hist",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "limit": l
            }
        },
        {
            "name": "Huobi",
            "priority": 9,
            "symbol_fmt": lambda s: s.lower(),
            "endpoint": "https://api.huobi.pro/market/history/kline",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "symbol": s,
                "period": i,
                "size": l
            }
        },
        {
            "name": "Coinbase",
            "priority": 10,
            "symbol_fmt": lambda s: s.replace("USDT", "-USD"),
            "endpoint_builder": lambda s, i: f"https://api.exchange.coinbase.com/products/{s}/candles",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "granularity": i
            }
        },
        {
            "name": "CoinGecko",
            "priority": 99,  # En son denenecek - fallback
            "symbol_fmt": lambda s: s.replace("USDT", "").lower(),
            "endpoint_builder": lambda s, i: f"https://api.coingecko.com/api/v3/coins/{s}/ohlc",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "vs_currency": "usd",
                "days": "max" if i in ["1D", "1W", "1M"] else "30"
            }
        }
    ]

    # Tüm timeframe mapping'leri - HER BORSA İÇİN
    INTERVAL_MAPPING = {
        "1m": {
            "Binance": "1m",
            "Bybit": "1",
            "OKX": "1m",
            "KuCoin": "1min",
            "Gate.io": "1m",
            "MEXC": "1m",
            "Kraken": "1",
            "Bitfinex": "1m",
            "Huobi": "1min",
            "Coinbase": "60",
            "CoinGecko": "1m"  # CoinGecko 1m desteklemez, ama mapping'de olsun
        },
        "5m": {
            "Binance": "5m",
            "Bybit": "5",
            "OKX": "5m",
            "KuCoin": "5min",
            "Gate.io": "5m",
            "MEXC": "5m",
            "Kraken": "5",
            "Bitfinex": "5m",
            "Huobi": "5min",
            "Coinbase": "300",
            "CoinGecko": "5m"  # CoinGecko 5m desteklemez
        },
        "15m": {
            "Binance": "15m",
            "Bybit": "15",
            "OKX": "15m",
            "KuCoin": "15min",
            "Gate.io": "15m",
            "MEXC": "15m",
            "Kraken": "15",
            "Bitfinex": "15m",
            "Huobi": "15min",
            "Coinbase": "900",
            "CoinGecko": "15m"  # CoinGecko 15m desteklemez
        },
        "30m": {
            "Binance": "30m",
            "Bybit": "30",
            "OKX": "30m",
            "KuCoin": "30min",
            "Gate.io": "30m",
            "MEXC": "30m",
            "Kraken": "30",
            "Bitfinex": "30m",
            "Huobi": "30min",
            "Coinbase": "1800",
            "CoinGecko": "30m"  # CoinGecko 30m desteklemez
        },
        "1h": {
            "Binance": "1h",
            "Bybit": "60",
            "OKX": "1H",
            "KuCoin": "1hour",
            "Gate.io": "1h",
            "MEXC": "1h",
            "Kraken": "60",
            "Bitfinex": "1h",
            "Huobi": "60min",
            "Coinbase": "3600",
            "CoinGecko": "1h"
        },
        "4h": {
            "Binance": "4h",
            "Bybit": "240",
            "OKX": "4H",
            "KuCoin": "4hour",
            "Gate.io": "4h",
            "MEXC": "4h",
            "Kraken": "240",
            "Bitfinex": "4h",
            "Huobi": "4hour",
            "Coinbase": "14400",
            "CoinGecko": "4h"
        },
        "1D": {
            "Binance": "1d",
            "Bybit": "D",
            "OKX": "1D",
            "KuCoin": "1day",
            "Gate.io": "1d",
            "MEXC": "1d",
            "Kraken": "1440",
            "Bitfinex": "1D",
            "Huobi": "1day",
            "Coinbase": "86400",
            "CoinGecko": "1"
        },
        "1W": {
            "Binance": "1w",
            "Bybit": "W",
            "OKX": "1W",
            "KuCoin": "1week",
            "Gate.io": "1w",
            "MEXC": "1w",
            "Kraken": "10080",
            "Bitfinex": "1W",
            "Huobi": "1week",
            "Coinbase": "604800",
            "CoinGecko": "7"
        },
        "1M": {
            "Binance": "1M",
            "Bybit": "M",
            "OKX": "1M",
            "KuCoin": "1month",
            "Gate.io": "1M",
            "MEXC": "1M",
            "Kraken": "43200",  # 30 gün
            "Bitfinex": "1M",
            "Huobi": "1mon",
            "Coinbase": "2592000",
            "CoinGecko": "30"
        }
    }

    def __init__(self, max_cache_age: int = 60):
        """
        Args:
            max_cache_age: Cache süresi (saniye), varsayılan 60s
        """
        # Havuz sistemi: {symbol}_{interval} -> {data, timestamp, sources}
        self.data_pool: Dict[str, Dict] = {}
        self.max_cache_age = max_cache_age
        
        # İstatistikler
        self.stats = {
            "total_requests": 0,
            "successful_fetches": 0,
            "failed_fetches": 0,
            "cache_hits": 0,
            "exchange_stats": defaultdict(lambda: {"success": 0, "fail": 0})
        }
        
        logger.info("PriceFetcher başlatıldı - Sadece gerçek veri modu")

    def _get_exchange_interval(self, exchange_name: str, interval: str) -> str:
        """Borsa-spesifik interval formatını al"""
        return self.INTERVAL_MAPPING.get(interval, {}).get(exchange_name, interval)

    async def _fetch_single_exchange(
        self, 
        session: aiohttp.ClientSession,
        exchange: Dict,
        symbol: str,
        interval: str,
        limit: int
    ) -> Optional[List[Dict]]:
        """Tek bir borsadan veri çek"""
        exchange_name = exchange["name"]
        
        # CoinGecko kısa timeframe desteklemiyorsa baştan atla
        if exchange_name == "CoinGecko" and interval not in ["1h", "4h", "1D", "1W", "1M"]:
            logger.info(f"{exchange_name}: {interval} desteklenmiyor → atlanıyor")
            return None
        
        try:
            # Sembol formatını düzenle
            formatted_symbol = exchange["symbol_fmt"](symbol)
            
            # Exchange-specific interval
            exchange_interval = self._get_exchange_interval(exchange_name, interval)
            
            # Endpoint oluştur
            if "endpoint_builder" in exchange:
                endpoint = exchange["endpoint_builder"](formatted_symbol, exchange_interval)
            else:
                endpoint = exchange["endpoint"]
            
            # Parametreleri oluştur
            params = exchange["params_builder"](
                formatted_symbol,
                exchange_interval,
                limit
            )
            
            # İstek gönder
            async with session.get(
                endpoint,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                
                if response.status in (400, 404):
                    logger.info(f"{exchange_name}: {symbol} çifti bulunamadı (HTTP {response.status}) → atlanıyor")
                    self.stats["exchange_stats"][exchange_name]["fail"] += 1
                    return None
                    
                if response.status != 200:
                    logger.warning(f"{exchange_name}: HTTP {response.status}")
                    self.stats["exchange_stats"][exchange_name]["fail"] += 1
                    return None
                
                data = await response.json()
                
                # Parse et
                candles = self._parse_exchange_data(exchange_name, data, symbol)
                
                if candles and len(candles) > 0:
                    logger.info(f"✅ {exchange_name}: {len(candles)} mum alındı ({symbol} {interval})")
                    self.stats["exchange_stats"][exchange_name]["success"] += 1
                    self.stats["successful_fetches"] += 1
                    return candles
                else:
                    logger.warning(f"{exchange_name}: Parse başarısız")
                    self.stats["exchange_stats"][exchange_name]["fail"] += 1
                    return None
                    
        except asyncio.TimeoutError:
            logger.warning(f"{exchange_name}: Timeout")
            self.stats["exchange_stats"][exchange_name]["fail"] += 1
        except Exception as e:
            if "not found" in str(e).lower() or "invalid" in str(e).lower():
                logger.info(f"{exchange_name}: {symbol} desteklenmiyor → atlanıyor")
            else:
                logger.debug(f"{exchange_name}: Hata - {str(e)[:100]}")
            self.stats["exchange_stats"][exchange_name]["fail"] += 1
        
        self.stats["failed_fetches"] += 1
        return None

    def _parse_exchange_data(self, exchange_name: str, data: Any, symbol: str) -> List[Dict]:
        """Borsa-spesifik veriyi ortak formata parse et"""
        candles = []
        
        try:
            if exchange_name == "Binance":
                # [[timestamp, open, high, low, close, volume, ...], ...]
                for row in data:
                    candles.append({
                        "timestamp": int(row[0]),
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5])
                    })
            
            elif exchange_name == "Bybit":
                if isinstance(data, dict) and "result" in data:
                    result = data["result"]
                    if isinstance(result, dict) and "list" in result:
                        for row in result["list"]:
                            candles.append({
                                "timestamp": int(row[0]),
                                "open": float(row[1]),
                                "high": float(row[2]),
                                "low": float(row[3]),
                                "close": float(row[4]),
                                "volume": float(row[5])
                            })
            
            elif exchange_name == "OKX":
                if isinstance(data, dict) and "data" in data:
                    for row in data["data"]:
                        candles.append({
                            "timestamp": int(row[0]),
                            "open": float(row[1]),
                            "high": float(row[2]),
                            "low": float(row[3]),
                            "close": float(row[4]),
                            "volume": float(row[5])
                        })
            
            elif exchange_name == "KuCoin":
                if isinstance(data, dict) and "data" in data:
                    for row in data["data"]:
                        candles.append({
                            "timestamp": int(row[0]) * 1000,  # Saniye -> milisaniye
                            "open": float(row[1]),
                            "close": float(row[2]),
                            "high": float(row[3]),
                            "low": float(row[4]),
                            "volume": float(row[5])
                        })
            
            elif exchange_name == "Gate.io":
                if isinstance(data, list):
                    for row in data:
                        candles.append({
                            "timestamp": int(row[0]) * 1000,  # Saniye -> milisaniye
                            "open": float(row[5]),
                            "high": float(row[3]),
                            "low": float(row[4]),
                            "close": float(row[2]),
                            "volume": float(row[1])
                        })
            
            elif exchange_name == "MEXC":
                for row in data:
                    candles.append({
                        "timestamp": int(row[0]),
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5])
                    })
            
            elif exchange_name == "Kraken":
                if isinstance(data, dict) and "result" in data:
                    # İlk anahtar pair ismi
                    pair_key = list(data["result"].keys())[0]
                    for row in data["result"][pair_key]:
                        candles.append({
                            "timestamp": int(row[0]) * 1000,
                            "open": float(row[1]),
                            "high": float(row[2]),
                            "low": float(row[3]),
                            "close": float(row[4]),
                            "volume": float(row[6])
                        })
            
            elif exchange_name == "Bitfinex":
                if isinstance(data, list):
                    for row in data:
                        candles.append({
                            "timestamp": int(row[0]),
                            "open": float(row[1]),
                            "close": float(row[2]),
                            "high": float(row[3]),
                            "low": float(row[4]),
                            "volume": float(row[5])
                        })
            
            elif exchange_name == "Huobi":
                if isinstance(data, dict) and "data" in data:
                    for row in data["data"]:
                        candles.append({
                            "timestamp": int(row["id"]) * 1000,
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "volume": float(row["vol"])
                        })
            
            elif exchange_name == "Coinbase":
                if isinstance(data, list):
                    for row in data:
                        candles.append({
                            "timestamp": int(row[0]) * 1000,
                            "low": float(row[1]),
                            "high": float(row[2]),
                            "open": float(row[3]),
                            "close": float(row[4]),
                            "volume": float(row[5])
                        })
            
            elif exchange_name == "CoinGecko":
                if isinstance(data, list):
                    for row in data:
                        # [timestamp_ms, open, high, low, close]
                        candles.append({
                            "timestamp": int(row[0]),  # zaten ms
                            "open": float(row[1]),
                            "high": float(row[2]),
                            "low": float(row[3]),
                            "close": float(row[4]),
                            "volume": 0.0  # CoinGecko OHLC endpoint volume vermiyor
                        })
            
            # Timestamp'e göre sırala (en eski -> en yeni)
            candles.sort(key=lambda x: x["timestamp"])
            
        except Exception as e:
            logger.error(f"{exchange_name} parse hatası: {e}")
            return []
        
        return candles

    def _aggregate_candles(self, all_candles: List[List[Dict]]) -> List[Dict]:
        """Farklı borsalardan gelen mumları birleştir ve ortala"""
        if not all_candles:
            return []
        
        # Tüm timestamp'leri topla
        timestamp_data = defaultdict(list)
        
        for exchange_candles in all_candles:
            for candle in exchange_candles:
                timestamp_data[candle["timestamp"]].append(candle)
        
        # Her timestamp için ortalama al
        aggregated = []
        for timestamp in sorted(timestamp_data.keys()):
            candles_at_ts = timestamp_data[timestamp]
            
            if len(candles_at_ts) == 1:
                # Tek kaynak varsa direkt kullan
                aggregated.append(candles_at_ts[0])
            else:
                # Birden fazla kaynak varsa ortala
                aggregated.append({
                    "timestamp": timestamp,
                    "open": np.mean([c["open"] for c in candles_at_ts]),
                    "high": np.max([c["high"] for c in candles_at_ts]),  # En yüksek high
                    "low": np.min([c["low"] for c in candles_at_ts]),    # En düşük low
                    "close": np.mean([c["close"] for c in candles_at_ts]),
                    "volume": np.sum([c["volume"] for c in candles_at_ts]),  # Volume topla
                    "source_count": len(candles_at_ts)  # Kaç kaynaktan geldi
                })
        
        return aggregated

    async def get_candles(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100,
        force_refresh: bool = False
    ) -> List[Dict]:
        """
        Ana fonksiyon: Mumları al (cache'den veya borsalardan)
        
        Args:
            symbol: İşlem çifti (örn: BTCUSDT)
            interval: Zaman dilimi (1m, 5m, 15m, 30m, 1h, 4h, 1D, 1W, 1M)
            limit: Kaç mum isteniyor
            force_refresh: Cache'i atla, zorla yenile
        
        Returns:
            Mum listesi, en eski -> en yeni sıralı
        """
        self.stats["total_requests"] += 1
        cache_key = f"{symbol}_{interval}"
        
        # Cache kontrolü
        if not force_refresh and cache_key in self.data_pool:
            cached = self.data_pool[cache_key]
            age = time.time() - cached["timestamp"]
            
            if age < self.max_cache_age:
                logger.info(f"📦 Cache hit: {symbol} {interval} (yaş: {age:.1f}s)")
                self.stats["cache_hits"] += 1
                return cached["data"][-limit:]
        
        # Cache yoksa veya eski, yeni veri çek
        logger.info(f"🔄 Veri çekiliyor: {symbol} {interval} ({limit} mum)")
        
        # Ekstra mum çek (cache için), minimum 200
        fetch_limit = max(limit * 2, 200)
        
        # Tüm borsalardan paralel çek
        async with aiohttp.ClientSession() as session:
            tasks = []
            for exchange in sorted(self.EXCHANGES, key=lambda x: x["priority"]):
                task = self._fetch_single_exchange(
                    session,
                    exchange,
                    symbol,
                    interval,
                    fetch_limit
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Başarılı sonuçları filtrele
        valid_results = [
            r for r in results 
            if r is not None and not isinstance(r, Exception) and len(r) > 0
        ]
        
        if not valid_results:
            logger.error(f"❌ TÜM BORSALAR BAŞARISIZ: {symbol} {interval}")
            logger.error("Sentetik veri kullanılamaz! Lütfen internet bağlantınızı kontrol edin.")
            return []
        
        # Verileri aggregate et
        aggregated = self._aggregate_candles(valid_results)
        
        if not aggregated:
            logger.error(f"❌ Aggregate başarısız: {symbol} {interval}")
            return []
        
        # Cache'e kaydet
        self.data_pool[cache_key] = {
            "data": aggregated,
            "timestamp": time.time(),
            "sources": len(valid_results),
            "symbol": symbol,
            "interval": interval
        }
        
        # Log detayları
        if aggregated:
            sources = self.data_pool[cache_key]["sources"]
            logger.info(f"✅ {symbol} {interval}: {len(aggregated)} mum, {sources} borsadan aggregate edildi")
            if "CoinGecko" in [ex["name"] for ex in self.EXCHANGES]:
                for ex in self.EXCHANGES:
                    if ex["name"] == "CoinGecko":
                        if any("CoinGecko" in str(result) for result in valid_results):
                            logger.info("  (CoinGecko'dan veri kullanıldı – bazı borsalarda coin bulunamadı)")
        
        return aggregated[-limit:]

    async def get_multiple_symbols(
        self,
        symbols: List[str],
        interval: str = "1h",
        limit: int = 100
    ) -> Dict[str, List[Dict]]:
        """Birden fazla sembol için paralel veri çek"""
        tasks = {
            symbol: self.get_candles(symbol, interval, limit)
            for symbol in symbols
        }
        
        results = await asyncio.gather(*tasks.values())
        
        return {
            symbol: result
            for symbol, result in zip(tasks.keys(), results)
        }

    def get_stats(self) -> Dict:
        """İstatistikleri döndür"""
        return {
            **self.stats,
            "cache_size": len(self.data_pool),
            "cache_symbols": list(self.data_pool.keys())
        }

    def clear_cache(self, symbol: str = None, interval: str = None):
        """Cache'i temizle"""
        if symbol and interval:
            cache_key = f"{symbol}_{interval}"
            if cache_key in self.data_pool:
                del self.data_pool[cache_key]
                logger.info(f"Cache temizlendi: {cache_key}")
        elif symbol:
            # Sembolün tüm interval'lerini temizle
            keys_to_delete = [k for k in self.data_pool.keys() if k.startswith(f"{symbol}_")]
            for key in keys_to_delete:
                del self.data_pool[key]
            logger.info(f"{len(keys_to_delete)} cache entry silindi ({symbol})")
        else:
            # Tümünü temizle
            self.data_pool.clear()
            logger.info("Tüm cache temizlendi")

    async def health_check(self) -> Dict[str, Any]:
        """Sistem sağlık kontrolü"""
        results = {}
        
        async with aiohttp.ClientSession() as session:
            for exchange in self.EXCHANGES[:3]:  # İlk 3 borsa test et
                try:
                    start = time.time()
                    candles = await self._fetch_single_exchange(
                        session,
                        exchange,
                        "BTCUSDT",
                        "1h",
                        10
                    )
                    elapsed = time.time() - start
                    
                    results[exchange["name"]] = {
                        "status": "OK" if candles else "FAIL",
                        "response_time": f"{elapsed:.2f}s",
                        "candles": len(candles) if candles else 0
                    }
                except Exception as e:
                    results[exchange["name"]] = {
                        "status": "ERROR",
                        "error": str(e)
                    }
        
        return results

# ========== TECHNICAL INDICATORS ==========
class TechnicalIndicators:
    """Calculate technical indicators"""
    
    @staticmethod
    def calculate_ema(candles: List[Dict], period: int) -> List[float]:
        """Calculate Exponential Moving Average"""
        closes = [c["close"] for c in candles]
        ema = []
        multiplier = 2 / (period + 1)
        
        # First EMA is SMA
        sma = sum(closes[:period]) / period
        ema.append(sma)
        
        # Calculate EMA for rest
        for i in range(period, len(closes)):
            ema_value = (closes[i] - ema[-1]) * multiplier + ema[-1]
            ema.append(ema_value)
        
        # Pad with None for initial values
        return [None] * (period - 1) + ema
    
    @staticmethod
    def calculate_rsi(candles: List[Dict], period: int = 14) -> List[float]:
        """Calculate Relative Strength Index"""
        closes = [c["close"] for c in candles]
        rsi_values = [None] * period
        
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        
        if len(gains) < period:
            return rsi_values
        
        # First RSI
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        for i in range(period, len(gains)):
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            
            rsi_values.append(rsi)
            
            # Smooth averages
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        return rsi_values
    
    @staticmethod
    def convert_to_heikin_ashi(candles: List[Dict]) -> List[Dict]:
        """Convert regular candles to Heikin Ashi"""
        ha_candles = []
        
        for i, candle in enumerate(candles):
            if i == 0:
                # First HA candle
                ha_close = (candle["open"] + candle["high"] + candle["low"] + candle["close"]) / 4
                ha_open = (candle["open"] + candle["close"]) / 2
                ha_high = candle["high"]
                ha_low = candle["low"]
            else:
                prev_ha = ha_candles[-1]
                ha_close = (candle["open"] + candle["high"] + candle["low"] + candle["close"]) / 4
                ha_open = (prev_ha["open"] + prev_ha["close"]) / 2
                ha_high = max(candle["high"], ha_open, ha_close)
                ha_low = min(candle["low"], ha_open, ha_close)
            
            ha_candles.append({
                "timestamp": candle["timestamp"],
                "open": ha_open,
                "high": ha_high,
                "low": ha_low,
                "close": ha_close,
                "volume": candle["volume"]
            })
        
        return ha_candles

# ========== CANDLESTICK PATTERN DETECTOR ==========
class CandlestickPatternDetector:
    """Detect 12 major candlestick patterns"""
    
    @staticmethod
    def is_bullish_engulfing(prev: Dict, curr: Dict) -> bool:
        """Bullish Engulfing Pattern"""
        prev_body = abs(prev["close"] - prev["open"])
        curr_body = abs(curr["close"] - curr["open"])
        
        return (prev["close"] < prev["open"] and  # Previous bearish
                curr["close"] > curr["open"] and  # Current bullish
                curr["open"] < prev["close"] and  # Opens below prev close
                curr["close"] > prev["open"] and  # Closes above prev open
                curr_body > prev_body * 1.2)      # Larger body
    
    @staticmethod
    def is_bearish_engulfing(prev: Dict, curr: Dict) -> bool:
        """Bearish Engulfing Pattern"""
        prev_body = abs(prev["close"] - prev["open"])
        curr_body = abs(curr["close"] - curr["open"])
        
        return (prev["close"] > prev["open"] and  # Previous bullish
                curr["close"] < curr["open"] and  # Current bearish
                curr["open"] > prev["close"] and  # Opens above prev close
                curr["close"] < prev["open"] and  # Closes below prev open
                curr_body > prev_body * 1.2)      # Larger body
    
    @staticmethod
    def is_hammer(candle: Dict) -> bool:
        """Hammer Pattern (Bullish Reversal)"""
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        
        return (lower_shadow > body * 2 and
                upper_shadow < body * 0.3 and
                body > 0)
    
    @staticmethod
    def is_hanging_man(candle: Dict) -> bool:
        """Hanging Man Pattern (Bearish Reversal)"""
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        
        return (lower_shadow > body * 2 and
                upper_shadow < body * 0.3 and
                candle["close"] < candle["open"])
    
    @staticmethod
    def is_shooting_star(candle: Dict) -> bool:
        """Shooting Star Pattern (Bearish Reversal)"""
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        
        return (upper_shadow > body * 2 and
                lower_shadow < body * 0.3 and
                body > 0)
    
    @staticmethod
    def is_doji(candle: Dict) -> bool:
        """Doji Pattern (Indecision)"""
        body = abs(candle["close"] - candle["open"])
        total_range = candle["high"] - candle["low"]
        
        return body < total_range * 0.1 and total_range > 0
    
    @staticmethod
    def is_morning_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Morning Star Pattern (Bullish Reversal)"""
        return (c1["close"] < c1["open"] and  # First bearish
                abs(c2["close"] - c2["open"]) < abs(c1["close"] - c1["open"]) * 0.3 and  # Small body
                c3["close"] > c3["open"] and  # Third bullish
                c3["close"] > (c1["open"] + c1["close"]) / 2)  # Closes above midpoint
    
    @staticmethod
    def is_evening_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Evening Star Pattern (Bearish Reversal)"""
        return (c1["close"] > c1["open"] and  # First bullish
                abs(c2["close"] - c2["open"]) < abs(c1["close"] - c1["open"]) * 0.3 and  # Small body
                c3["close"] < c3["open"] and  # Third bearish
                c3["close"] < (c1["open"] + c1["close"]) / 2)  # Closes below midpoint
    
    @staticmethod
    def is_three_white_soldiers(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Three White Soldiers (Strong Bullish)"""
        return (c1["close"] > c1["open"] and
                c2["close"] > c2["open"] and
                c3["close"] > c3["open"] and
                c2["close"] > c1["close"] and
                c3["close"] > c2["close"] and
                c2["open"] > c1["open"] and c2["open"] < c1["close"] and
                c3["open"] > c2["open"] and c3["open"] < c2["close"])
    
    @staticmethod
    def is_three_black_crows(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Three Black Crows (Strong Bearish)"""
        return (c1["close"] < c1["open"] and
                c2["close"] < c2["open"] and
                c3["close"] < c3["open"] and
                c2["close"] < c1["close"] and
                c3["close"] < c2["close"] and
                c2["open"] < c1["open"] and c2["open"] > c1["close"] and
                c3["open"] < c2["open"] and c3["open"] > c2["close"])
    
    @staticmethod
    def is_bullish_harami(prev: Dict, curr: Dict) -> bool:
        """Bullish Harami Pattern"""
        return (prev["close"] < prev["open"] and  # Previous bearish
                curr["close"] > curr["open"] and  # Current bullish
                curr["open"] > prev["close"] and
                curr["close"] < prev["open"])
    
    @staticmethod
    def is_bearish_harami(prev: Dict, curr: Dict) -> bool:
        """Bearish Harami Pattern"""
        return (prev["close"] > prev["open"] and  # Previous bullish
                curr["close"] < curr["open"] and  # Current bearish
                curr["open"] < prev["close"] and
                curr["close"] > prev["open"])
    
    @staticmethod
    def detect_all_patterns(candles: List[Dict]) -> List[Dict]:
        """Detect all patterns in the candle data"""
        patterns = []
        
        if len(candles) < 3:
            return patterns
        
        # Two-candle patterns
        for i in range(1, len(candles)):
            prev = candles[i-1]
            curr = candles[i]
            
            if CandlestickPatternDetector.is_bullish_engulfing(prev, curr):
                patterns.append({
                    "name": "Bullish Engulfing",
                    "type": "reversal",
                    "direction": "bullish",
                    "confidence": 85,
                    "position": i,
                    "description": "Strong bullish reversal signal"
                })
            
            if CandlestickPatternDetector.is_bearish_engulfing(prev, curr):
                patterns.append({
                    "name": "Bearish Engulfing",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 85,
                    "position": i,
                    "description": "Strong bearish reversal signal"
                })
            
            if CandlestickPatternDetector.is_bullish_harami(prev, curr):
                patterns.append({
                    "name": "Bullish Harami",
                    "type": "reversal",
                    "direction": "bullish",
                    "confidence": 70,
                    "position": i,
                    "description": "Bullish reversal indication"
                })
            
            if CandlestickPatternDetector.is_bearish_harami(prev, curr):
                patterns.append({
                    "name": "Bearish Harami",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 70,
                    "position": i,
                    "description": "Bearish reversal indication"
                })
        
        # Single-candle patterns
        for i in range(len(candles)):
            candle = candles[i]
            
            if CandlestickPatternDetector.is_hammer(candle):
                patterns.append({
                    "name": "Hammer",
                    "type": "reversal",
                    "direction": "bullish",
                    "confidence": 75,
                    "position": i,
                    "description": "Bullish reversal at support"
                })
            
            if CandlestickPatternDetector.is_hanging_man(candle):
                patterns.append({
                    "name": "Hanging Man",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 75,
                    "position": i,
                    "description": "Bearish reversal at resistance"
                })
            
            if CandlestickPatternDetector.is_shooting_star(candle):
                patterns.append({
                    "name": "Shooting Star",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 80,
                    "position": i,
                    "description": "Strong bearish reversal"
                })
            
            if CandlestickPatternDetector.is_doji(candle):
                patterns.append({
                    "name": "Doji",
                    "type": "indecision",
                    "direction": "neutral",
                    "confidence": 60,
                    "position": i,
                    "description": "Market indecision, potential reversal"
                })
        
        # Three-candle patterns
        for i in range(2, len(candles)):
            c1, c2, c3 = candles[i-2], candles[i-1], candles[i]
            
            if CandlestickPatternDetector.is_morning_star(c1, c2, c3):
                patterns.append({
                    "name": "Morning Star",
                    "type": "reversal",
                    "direction": "bullish",
                    "confidence": 90,
                    "position": i,
                    "description": "Very strong bullish reversal"
                })
            
            if CandlestickPatternDetector.is_evening_star(c1, c2, c3):
                patterns.append({
                    "name": "Evening Star",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 90,
                    "position": i,
                    "description": "Very strong bearish reversal"
                })
            
            if CandlestickPatternDetector.is_three_white_soldiers(c1, c2, c3):
                patterns.append({
                    "name": "Three White Soldiers",
                    "type": "continuation",
                    "direction": "bullish",
                    "confidence": 95,
                    "position": i,
                    "description": "Extremely strong bullish trend"
                })
            
            if CandlestickPatternDetector.is_three_black_crows(c1, c2, c3):
                patterns.append({
                    "name": "Three Black Crows",
                    "type": "continuation",
                    "direction": "bearish",
                    "confidence": 95,
                    "position": i,
                    "description": "Extremely strong bearish trend"
                })
        
        return patterns

# ========== ICT ANALYZER ==========
class ICTAnalyzer:
    """Inner Circle Trader Market Structure Analysis"""
    
    @staticmethod
    def detect_fair_value_gaps(candles: List[Dict]) -> List[Dict]:
        """Detect Fair Value Gaps (FVG)"""
        fvgs = []
        
        for i in range(2, len(candles)):
            prev = candles[i-2]
            curr = candles[i]
            
            # Bullish FVG
            if prev["high"] < curr["low"]:
                gap_size = curr["low"] - prev["high"]
                fvgs.append({
                    "type": "bullish",
                    "start": prev["high"],
                    "end": curr["low"],
                    "size": gap_size,
                    "position": i,
                    "strength": "strong" if gap_size > (prev["close"] * 0.01) else "moderate"
                })
            
            # Bearish FVG
            if prev["low"] > curr["high"]:
                gap_size = prev["low"] - curr["high"]
                fvgs.append({
                    "type": "bearish",
                    "start": curr["high"],
                    "end": prev["low"],
                    "size": gap_size,
                    "position": i,
                    "strength": "strong" if gap_size > (prev["close"] * 0.01) else "moderate"
                })
        
        return fvgs
    
    @staticmethod
    def detect_order_blocks(candles: List[Dict]) -> List[Dict]:
        """Detect Order Blocks"""
        order_blocks = []
        
        for i in range(3, len(candles)):
            # Bullish Order Block (last bearish candle before strong move up)
            if (candles[i-1]["close"] < candles[i-1]["open"] and
                candles[i]["close"] > candles[i]["open"] and
                candles[i]["close"] > candles[i-1]["high"]):
                
                order_blocks.append({
                    "type": "bullish",
                    "high": candles[i-1]["high"],
                    "low": candles[i-1]["low"],
                    "position": i-1,
                    "strength": "strong" if (candles[i]["close"] - candles[i-1]["low"]) > (candles[i-1]["high"] - candles[i-1]["low"]) * 2 else "moderate"
                })
            
            # Bearish Order Block (last bullish candle before strong move down)
            if (candles[i-1]["close"] > candles[i-1]["open"] and
                candles[i]["close"] < candles[i]["open"] and
                candles[i]["close"] < candles[i-1]["low"]):
                
                order_blocks.append({
                    "type": "bearish",
                    "high": candles[i-1]["high"],
                    "low": candles[i-1]["low"],
                    "position": i-1,
                    "strength": "strong" if (candles[i-1]["high"] - candles[i]["close"]) > (candles[i-1]["high"] - candles[i-1]["low"]) * 2 else "moderate"
                })
        
        return order_blocks
    
    @staticmethod
    def analyze_market_structure(candles: List[Dict]) -> Dict:
        """Analyze overall market structure"""
        if len(candles) < 20:
            return {"structure": "insufficient_data"}
        
        recent_candles = candles[-20:]
        highs = [c["high"] for c in recent_candles]
        lows = [c["low"] for c in recent_candles]
        
        # Higher highs and higher lows = bullish
        higher_highs = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i-1])
        higher_lows = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i-1])
        
        # Lower highs and lower lows = bearish
        lower_highs = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i-1])
        lower_lows = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i-1])
        
        if higher_highs > 12 and higher_lows > 12:
            structure = "bullish_trend"
            strength = "strong"
        elif lower_highs > 12 and lower_lows > 12:
            structure = "bearish_trend"
            strength = "strong"
        elif higher_highs > 8 and higher_lows > 8:
            structure = "bullish_trend"
            strength = "moderate"
        elif lower_highs > 8 and lower_lows > 8:
            structure = "bearish_trend"
            strength = "moderate"
        else:
            structure = "ranging"
            strength = "weak"
        
        return {
            "structure": structure,
            "strength": strength,
            "higher_highs": higher_highs,
            "higher_lows": higher_lows,
            "lower_highs": lower_highs,
            "lower_lows": lower_lows
        }

# ========== SIGNAL GENERATOR ==========
class SignalGenerator:
    """Generate trading signals with confidence levels"""
    
    @staticmethod
    def calculate_ema_signal(ema_fast: List[float], ema_slow: List[float]) -> Dict:
        """Calculate signal from EMA crossover"""
        if not ema_fast or not ema_slow or len(ema_fast) < 2 or len(ema_slow) < 2:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "insufficient_data"}
        
        # Current and previous values
        fast_curr = ema_fast[-1]
        fast_prev = ema_fast[-2]
        slow_curr = ema_slow[-1]
        slow_prev = ema_slow[-2]
        
        if fast_curr is None or fast_prev is None or slow_curr is None or slow_prev is None:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "insufficient_data"}
        
        # Golden Cross (bullish)
        if fast_prev <= slow_prev and fast_curr > slow_curr:
            distance = abs(fast_curr - slow_curr) / slow_curr * 100
            confidence = min(90, 70 + distance * 10)
            return {
                "signal": "BUY",
                "confidence": confidence,
                "reason": "golden_cross",
                "description": "EMA fast crossed above EMA slow (Golden Cross)"
            }
        
        # Death Cross (bearish)
        if fast_prev >= slow_prev and fast_curr < slow_curr:
            distance = abs(fast_curr - slow_curr) / slow_curr * 100
            confidence = min(90, 70 + distance * 10)
            return {
                "signal": "SELL",
                "confidence": confidence,
                "reason": "death_cross",
                "description": "EMA fast crossed below EMA slow (Death Cross)"
            }
        
        # Trending
        if fast_curr > slow_curr:
            distance = (fast_curr - slow_curr) / slow_curr * 100
            if distance > 2:
                return {
                    "signal": "BUY",
                    "confidence": min(80, 50 + distance * 5),
                    "reason": "uptrend",
                    "description": f"Strong uptrend (EMA distance: {distance:.2f}%)"
                }
            else:
                return {
                    "signal": "NEUTRAL",
                    "confidence": 40,
                    "reason": "weak_uptrend",
                    "description": "Weak uptrend"
                }
        else:
            distance = (slow_curr - fast_curr) / slow_curr * 100
            if distance > 2:
                return {
                    "signal": "SELL",
                    "confidence": min(80, 50 + distance * 5),
                    "reason": "downtrend",
                    "description": f"Strong downtrend (EMA distance: {distance:.2f}%)"
                }
            else:
                return {
                    "signal": "NEUTRAL",
                    "confidence": 40,
                    "reason": "weak_downtrend",
                    "description": "Weak downtrend"
                }
    
    @staticmethod
    def calculate_rsi_signal(rsi: List[float]) -> Dict:
        """Calculate signal from RSI"""
        if not rsi or len(rsi) < 2:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "insufficient_data"}
        
        current_rsi = rsi[-1]
        prev_rsi = rsi[-2]
        
        if current_rsi is None or prev_rsi is None:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "insufficient_data"}
        
        # Oversold (< 30)
        if current_rsi < 30:
            if prev_rsi < 30 and current_rsi > prev_rsi:
                return {
                    "signal": "STRONG_BUY",
                    "confidence": 85,
                    "reason": "oversold_reversal",
                    "description": f"Oversold reversal (RSI: {current_rsi:.1f})"
                }
            return {
                "signal": "BUY",
                "confidence": 70,
                "reason": "oversold",
                "description": f"Oversold condition (RSI: {current_rsi:.1f})"
            }
        
        # Overbought (> 70)
        if current_rsi > 70:
            if prev_rsi > 70 and current_rsi < prev_rsi:
                return {
                    "signal": "STRONG_SELL",
                    "confidence": 85,
                    "reason": "overbought_reversal",
                    "description": f"Overbought reversal (RSI: {current_rsi:.1f})"
                }
            return {
                "signal": "SELL",
                "confidence": 70,
                "reason": "overbought",
                "description": f"Overbought condition (RSI: {current_rsi:.1f})"
            }
        
        # Neutral zone
        if 40 <= current_rsi <= 60:
            return {
                "signal": "NEUTRAL",
                "confidence": 50,
                "reason": "neutral_zone",
                "description": f"Neutral RSI (RSI: {current_rsi:.1f})"
            }
        
        # Bullish
        if current_rsi > 50 and current_rsi > prev_rsi:
            return {
                "signal": "BUY",
                "confidence": 60,
                "reason": "bullish_momentum",
                "description": f"Bullish momentum (RSI: {current_rsi:.1f})"
            }
        
        # Bearish
        if current_rsi < 50 and current_rsi < prev_rsi:
            return {
                "signal": "SELL",
                "confidence": 60,
                "reason": "bearish_momentum",
                "description": f"Bearish momentum (RSI: {current_rsi:.1f})"
            }
        
        return {
            "signal": "NEUTRAL",
            "confidence": 45,
            "reason": "unclear",
            "description": f"Unclear signal (RSI: {current_rsi:.1f})"
        }
    
    @staticmethod
    def calculate_pattern_signal(patterns: List[Dict]) -> Dict:
        """Calculate signal from candlestick patterns"""
        if not patterns:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "no_patterns"}
        
        # Get recent patterns (last 5 candles)
        recent_patterns = [p for p in patterns if p["position"] >= len(patterns) - 5]
        
        if not recent_patterns:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "no_recent_patterns"}
        
        # Calculate weighted signal
        bullish_score = sum(p["confidence"] for p in recent_patterns if p["direction"] == "bullish")
        bearish_score = sum(p["confidence"] for p in recent_patterns if p["direction"] == "bearish")
        
        max_confidence = max(p["confidence"] for p in recent_patterns)
        
        if bullish_score > bearish_score * 1.5:
            return {
                "signal": "BUY" if max_confidence < 90 else "STRONG_BUY",
                "confidence": min(95, max_confidence),
                "reason": "bullish_patterns",
                "description": f"{len([p for p in recent_patterns if p['direction'] == 'bullish'])} bullish pattern(s) detected",
                "patterns": recent_patterns
            }
        elif bearish_score > bullish_score * 1.5:
            return {
                "signal": "SELL" if max_confidence < 90 else "STRONG_SELL",
                "confidence": min(95, max_confidence),
                "reason": "bearish_patterns",
                "description": f"{len([p for p in recent_patterns if p['direction'] == 'bearish'])} bearish pattern(s) detected",
                "patterns": recent_patterns
            }
        else:
            return {
                "signal": "NEUTRAL",
                "confidence": 50,
                "reason": "mixed_patterns",
                "description": "Mixed pattern signals",
                "patterns": recent_patterns
            }
    
    @staticmethod
    def calculate_ict_signal(fvgs: List[Dict], order_blocks: List[Dict], market_structure: Dict) -> Dict:
        """Calculate signal from ICT analysis"""
        score = 0
        reasons = []
        
        # Market structure
        if market_structure["structure"] == "bullish_trend":
            score += 30 if market_structure["strength"] == "strong" else 20
            reasons.append(f"Bullish market structure ({market_structure['strength']})")
        elif market_structure["structure"] == "bearish_trend":
            score -= 30 if market_structure["strength"] == "strong" else 20
            reasons.append(f"Bearish market structure ({market_structure['strength']})")
        
        # Recent FVGs
        recent_fvgs = [f for f in fvgs if f["position"] >= len(fvgs) - 3] if fvgs else []
        for fvg in recent_fvgs:
            if fvg["type"] == "bullish":
                score += 15 if fvg["strength"] == "strong" else 10
                reasons.append(f"Bullish FVG ({fvg['strength']})")
            else:
                score -= 15 if fvg["strength"] == "strong" else 10
                reasons.append(f"Bearish FVG ({fvg['strength']})")
        
        # Recent Order Blocks
        recent_obs = [ob for ob in order_blocks if ob["position"] >= len(order_blocks) - 3] if order_blocks else []
        for ob in recent_obs:
            if ob["type"] == "bullish":
                score += 20 if ob["strength"] == "strong" else 12
                reasons.append(f"Bullish Order Block ({ob['strength']})")
            else:
                score -= 20 if ob["strength"] == "strong" else 12
                reasons.append(f"Bearish Order Block ({ob['strength']})")
        
        # Determine signal
        confidence = min(95, abs(score))
        
        if score > 50:
            signal = "STRONG_BUY"
        elif score > 25:
            signal = "BUY"
        elif score < -50:
            signal = "STRONG_SELL"
        elif score < -25:
            signal = "SELL"
        else:
            signal = "NEUTRAL"
        
        return {
            "signal": signal,
            "confidence": confidence,
            "score": score,
            "reasons": reasons,
            "description": " | ".join(reasons) if reasons else "No clear ICT signal"
        }
    
    @staticmethod
    def generate_combined_signal(ema_signal: Dict, rsi_signal: Dict, pattern_signal: Dict, ict_signal: Dict, ha_trend: str, ml_signal: Dict = None) -> Dict:
        """Combine all signals into final recommendation"""
        
        # Signal weights
        weights = {
            "ema": 0.20,
            "rsi": 0.15,
            "patterns": 0.20,
            "ict": 0.20,
            "ml": 0.20,
            "ha": 0.05
        }
        
        # Convert signals to numeric scores
        signal_values = {
            "STRONG_BUY": 2,
            "BUY": 1,
            "NEUTRAL": 0,
            "SELL": -1,
            "STRONG_SELL": -2
        }
        
        # Calculate weighted score
        total_score = 0
        total_confidence = 0
        
        component_signals = {
            "ema": ema_signal,
            "rsi": rsi_signal,
            "patterns": pattern_signal,
            "ict": ict_signal
        }
        
        # Add ML signal if available
        if ml_signal:
            component_signals["ml"] = {
                "signal": ml_signal.get("prediction", "NEUTRAL"),
                "confidence": ml_signal.get("confidence", 0.5) * 100,
                "reason": "ml_prediction"
            }
        
        for name, sig in component_signals.items():
            weight = weights.get(name, 0)
            sig_value = signal_values.get(sig.get("signal", "NEUTRAL"), 0)
            sig_conf = sig.get("confidence", 0)
            
            total_score += sig_value * weight * (sig_conf / 100)
            total_confidence += sig_conf * weight
        
        # Heikin Ashi trend bonus
        if ha_trend == "strong_bullish":
            total_score += 0.3
            total_confidence += 5
        elif ha_trend == "strong_bearish":
            total_score -= 0.3
            total_confidence += 5
        
        # Determine final signal
        if total_score > 1.2:
            final_signal = SignalType.STRONG_BUY
        elif total_score > 0.5:
            final_signal = SignalType.BUY
        elif total_score < -1.2:
            final_signal = SignalType.STRONG_SELL
        elif total_score < -0.5:
            final_signal = SignalType.SELL
        else:
            final_signal = SignalType.NEUTRAL
        
        # Determine confidence level
        if total_confidence >= 85:
            conf_level = SignalConfidence.VERY_HIGH
        elif total_confidence >= 70:
            conf_level = SignalConfidence.HIGH
        elif total_confidence >= 55:
            conf_level = SignalConfidence.MEDIUM
        else:
            conf_level = SignalConfidence.LOW
        
        return {
            "signal": final_signal,
            "confidence": round(total_confidence, 1),
            "confidence_level": conf_level,
            "score": round(total_score, 2),
            "components": component_signals,
            "heikin_ashi_trend": ha_trend,
            "recommendation": SignalGenerator._generate_recommendation(final_signal, total_confidence, total_score)
        }
    
    @staticmethod
    def _generate_recommendation(signal: SignalType, confidence: float, score: float) -> str:
        """Generate human-readable recommendation"""
        if signal == SignalType.STRONG_BUY:
            if confidence >= 85:
                return "🚀 STRONG BUY - Very high confidence signal. Consider entering long position."
            else:
                return "📈 STRONG BUY - Good bullish setup. Moderate confidence."
        elif signal == SignalType.BUY:
            return "✅ BUY - Bullish signal detected. Consider buying on dips."
        elif signal == SignalType.STRONG_SELL:
            if confidence >= 85:
                return "🔴 STRONG SELL - Very high confidence bearish signal. Consider exiting or shorting."
            else:
                return "📉 STRONG SELL - Bearish setup. Moderate confidence."
        elif signal == SignalType.SELL:
            return "⚠️ SELL - Bearish signal detected. Consider taking profits or shorting."
        else:
            return "⏸️ NEUTRAL - No clear directional bias. Wait for better setup."

# ========== WEBSOCKET MANAGER ==========
class WebSocketManager:
    """Manage WebSocket connections for real-time updates"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New WebSocket connection. Total: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket disconnected. Remaining: {len(self.active_connections)}")
    
    async def send_personal_message(self, message: str, websocket: WebSocket):
        try:
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"Error sending personal message: {str(e)}")
    
    async def broadcast(self, message: str):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to connection: {str(e)}")
                disconnected.append(connection)
        
        # Remove disconnected clients
        for connection in disconnected:
            self.disconnect(connection)

# ========== GLOBAL INSTANCES ==========
ai_engine = AITradingEngine()
price_fetcher = PriceFetcher()
chatbot = TradingChatBot(ai_engine, price_fetcher)
websocket_manager = WebSocketManager()

# ========== API ENDPOINTS ==========
@app.get("/api/analyze/{symbol}")
async def analyze_symbol(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1h|4h|1d)$")
):
    """Complete technical analysis for a symbol"""
    try:
        # Fetch candle data
        candles = await price_fetcher.get_candles(symbol, interval, 100)
        
        if not candles or len(candles) < 50:
            raise HTTPException(status_code=400, detail="Insufficient data for analysis")
        
        # Calculate indicators
        ema_9 = TechnicalIndicators.calculate_ema(candles, 9)
        ema_21 = TechnicalIndicators.calculate_ema(candles, 21)
        ema_50 = TechnicalIndicators.calculate_ema(candles, 50)
        rsi = TechnicalIndicators.calculate_rsi(candles, 14)
        ha_candles = TechnicalIndicators.convert_to_heikin_ashi(candles)
        
        # Detect patterns
        patterns = CandlestickPatternDetector.detect_all_patterns(candles)
        
        # ICT Analysis
        fvgs = ICTAnalyzer.detect_fair_value_gaps(candles)
        order_blocks = ICTAnalyzer.detect_order_blocks(candles)
        market_structure = ICTAnalyzer.analyze_market_structure(candles)
        
        # Heikin Ashi trend
        ha_recent = ha_candles[-5:]
        bullish_ha = sum(1 for c in ha_recent if c["close"] > c["open"])
        if bullish_ha >= 4:
            ha_trend = "strong_bullish"
        elif bullish_ha >= 3:
            ha_trend = "bullish"
        elif bullish_ha <= 1:
            ha_trend = "strong_bearish"
        elif bullish_ha <= 2:
            ha_trend = "bearish"
        else:
            ha_trend = "neutral"
        
        # Generate signals
        ema_signal = SignalGenerator.calculate_ema_signal(ema_9, ema_21)
        rsi_signal = SignalGenerator.calculate_rsi_signal(rsi)
        pattern_signal = SignalGenerator.calculate_pattern_signal(patterns)
        ict_signal = SignalGenerator.calculate_ict_signal(fvgs, order_blocks, market_structure)
        
        # ML Prediction
        df = pd.DataFrame(candles)
        ml_prediction = None
        if not df.empty:
            try:
                df_copy = df.copy()
                if 'timestamp' in df_copy.columns:
                    df_copy.set_index('timestamp', inplace=True)
                ml_prediction = ai_engine.predict(symbol, df_copy)
            except Exception as e:
                logger.warning(f"ML prediction failed: {e}")
        
        # Combined signal
        combined_signal = SignalGenerator.generate_combined_signal(
            ema_signal, rsi_signal, pattern_signal, ict_signal, ha_trend, ml_prediction
        )
        
        # Current price data
        current_candle = candles[-1]
        prev_candle = candles[-2]
        price_change = ((current_candle["close"] - prev_candle["close"]) / prev_candle["close"]) * 100
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "interval": interval,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "price_data": {
                "current": current_candle["close"],
                "open": current_candle["open"],
                "high": current_candle["high"],
                "low": current_candle["low"],
                "change_percent": round(price_change, 2),
                "volume": current_candle["volume"]
            },
            "indicators": {
                "ema_9": round(ema_9[-1], 4) if ema_9[-1] else None,
                "ema_21": round(ema_21[-1], 4) if ema_21[-1] else None,
                "ema_50": round(ema_50[-1], 4) if ema_50[-1] else None,
                "rsi": round(rsi[-1], 2) if rsi[-1] else None,
                "heikin_ashi_trend": ha_trend
            },
            "patterns": patterns[-10:],  # Last 10 patterns
            "ict_analysis": {
                "fair_value_gaps": fvgs[-5:],  # Last 5 FVGs
                "order_blocks": order_blocks[-5:],  # Last 5 OBs
                "market_structure": market_structure
            },
            "ml_prediction": ml_prediction,
            "signal": combined_signal
        }
        
    except Exception as e:
        logger.error(f"Analysis error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@app.post("/api/train/{symbol}")
async def train_model(symbol: str):
    """Train ML models for a symbol"""
    try:
        logger.info(f"Training request for {symbol}")
        
        # Fetch historical data
        candles = await price_fetcher.get_candles(symbol, "1h", 1000)
        
        if not candles or len(candles) < 500:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient data for training. Need at least 500 candles, got {len(candles) if candles else 0}."
            )
        
        # Convert to DataFrame
        df = pd.DataFrame(candles)
        if not df.empty:
            if 'timestamp' in df.columns:
                df.set_index('timestamp', inplace=True)
        else:
            raise HTTPException(status_code=400, detail="Failed to create DataFrame from candle data")
        
        # Train models
        success = await ai_engine.train_models(symbol, df)
        
        if success:
            # Get feature importance
            feature_importance = ai_engine.get_feature_importance(symbol)
            
            return {
                "success": True,
                "message": f"Successfully trained ML models for {symbol}",
                "symbol": symbol.upper(),
                "models_trained": ["LightGBM", "LSTM", "Transformer"],
                "feature_importance": feature_importance,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        else:
            raise HTTPException(status_code=500, detail="Training failed")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Training error for {symbol}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Training failed: {str(e)}")

@app.post("/api/chat")
async def chat_endpoint(request: Request):
    """Chat with AI trading assistant"""
    try:
        data = await request.json()
        message = data.get("message", "")
        symbol = data.get("symbol", "BTCUSDT")
        
        if not message:
            raise HTTPException(status_code=400, detail="Message is required")
        
        response = await chatbot.process_message(message, symbol)
        
        return {
            "success": True,
            "response": response,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
    except Exception as e:
        logger.error(f"Chat error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time updates"""
    await websocket_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                msg_type = message.get("type")
                
                if msg_type == "subscribe":
                    symbol = message.get("symbol", "BTCUSDT")
                    candles = await price_fetcher.get_candles(symbol, "1h", 2)
                    if candles and len(candles) >= 2:
                        current = candles[-1]
                        previous = candles[-2]
                        change = ((current["close"] - previous["close"]) / previous["close"]) * 100
                        
                        await websocket_manager.send_personal_message(
                            json.dumps({
                                "type": "price_update",
                                "symbol": symbol,
                                "price": current["close"],
                                "change": change,
                                "timestamp": datetime.utcnow().isoformat() + "Z"
                            }),
                            websocket
                        )
            except json.JSONDecodeError:
                await websocket_manager.send_personal_message(
                    json.dumps({"error": "Invalid JSON format"}),
                    websocket
                )
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Main trading dashboard"""
    return """
   
# HTML Template
 
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Professional Trading Bot v4.0</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        :root {
            /* Canlı ve Modern Renkler */
            --primary-blue: #3b82f6;
            --primary-blue-light: #60a5fa;
            --success-green: #22c55e;
            --success-green-light: #4ade80;
            --danger-red: #ef4444;
            --danger-red-light: #f87171;
            --warning-yellow: #facc15;
            --warning-orange: #fb923c;
            --purple: #a855f7;
            --cyan: #06b6d4;
            
            /* Arka Plan Renkleri */
            --bg-dark: #0a0e27;
            --bg-card: #1a1f3a;
            --bg-card-hover: #252b4a;
            --bg-light: #2d3454;
            
            /* Yazı Renkleri */
            --text-white: #ffffff;
            --text-gray-light: #e2e8f0;
            --text-gray: #94a3b8;
            --text-gray-dark: #64748b;
            
            /* Gradyanlar */
            --gradient-blue: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            --gradient-green: linear-gradient(135deg, #22c55e 0%, #10b981 100%);
            --gradient-red: linear-gradient(135deg, #f43f5e 0%, #dc2626 100%);
            --gradient-yellow: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
            color: var(--text-white);
            font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
            min-height: 100vh;
        }
        
        /* Navbar Styling */
        .navbar {
            background: rgba(26, 31, 58, 0.95);
            backdrop-filter: blur(20px);
            border-bottom: 2px solid rgba(59, 130, 246, 0.3);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            padding: 1rem 0;
        }
        
        .navbar-brand {
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--text-white) !important;
            letter-spacing: -0.5px;
        }
        
        .navbar-brand i {
            color: var(--primary-blue);
            animation: rotate 3s linear infinite;
        }
        
        @keyframes rotate {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        
        /* Status Indicator */
        .status-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 8px;
            position: relative;
        }
        
        .status-online {
            background: var(--success-green);
            box-shadow: 0 0 20px var(--success-green);
            animation: pulse-glow 2s infinite;
        }
        
        @keyframes pulse-glow {
            0%, 100% {
                box-shadow: 0 0 20px var(--success-green);
            }
            50% {
                box-shadow: 0 0 30px var(--success-green), 0 0 40px var(--success-green-light);
            }
        }
        
        /* Card Styling */
        .card {
            background: var(--bg-card);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
            transition: all 0.3s ease;
            overflow: hidden;
        }
        
        .card:hover {
            transform: translateY(-4px);
            box-shadow: 0 12px 40px rgba(59, 130, 246, 0.2);
            border-color: rgba(59, 130, 246, 0.3);
        }
        
        .card-title {
            color: var(--text-white);
            font-weight: 600;
            font-size: 1.25rem;
            margin-bottom: 1.5rem;
        }
        
        .card-title i {
            color: var(--primary-blue);
            margin-right: 10px;
        }
        
        /* Form Controls */
        .form-select, .form-control {
            background: var(--bg-light) !important;
            color: var(--text-white) !important;
            border: 2px solid rgba(255, 255, 255, 0.1) !important;
            border-radius: 10px !important;
            padding: 10px 15px !important;
            font-weight: 500;
            transition: all 0.3s ease;
        }
        
        .form-select:focus, .form-control:focus {
            border-color: var(--primary-blue) !important;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2) !important;
            background: var(--bg-card) !important;
        }
        
        .form-select option {
            background: var(--bg-card);
            color: var(--text-white);
        }
        
        /* Buttons */
        .btn-primary {
            background: var(--gradient-blue) !important;
            border: none !important;
            padding: 10px 24px !important;
            border-radius: 10px !important;
            font-weight: 600 !important;
            transition: all 0.3s ease !important;
            box-shadow: 0 4px 15px rgba(59, 130, 246, 0.3);
        }
        
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(59, 130, 246, 0.4);
        }
        
        .btn-outline-success {
            border: 2px solid var(--success-green) !important;
            color: var(--success-green) !important;
            border-radius: 10px !important;
            font-weight: 600 !important;
        }
        
        .btn-outline-success:hover {
            background: var(--success-green) !important;
            color: white !important;
        }
        
        /* Signal Card - BEĞENILEN KISIM */
        #signalCard {
            background: var(--bg-card);
            border: 2px solid rgba(59, 130, 246, 0.3);
        }
        
        #currentPrice {
            color: var(--text-white);
            font-weight: 800;
            text-shadow: 0 2px 10px rgba(59, 130, 246, 0.3);
            letter-spacing: -1px;
        }
        
        #priceChange {
            font-weight: 600;
        }
        
        /* Signal Indicator */
        #signalIndicator {
            border-radius: 16px;
            border: 2px solid rgba(255, 255, 255, 0.1);
        }
        
        #signalIndicator h2 {
            font-size: 2.5rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 1px;
            text-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        }
        
        .signal-buy {
            background: var(--gradient-green) !important;
            box-shadow: 0 8px 32px rgba(34, 197, 94, 0.4);
        }
        
        .signal-sell {
            background: var(--gradient-red) !important;
            box-shadow: 0 8px 32px rgba(239, 68, 68, 0.4);
        }
        
        .signal-neutral {
            background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
            box-shadow: 0 8px 32px rgba(139, 92, 246, 0.4);
        }
        
        /* Progress Bar */
        .progress {
            background: rgba(255, 255, 255, 0.1) !important;
            border-radius: 10px;
            overflow: hidden;
            height: 24px !important;
        }
        
        .progress-bar {
            background: linear-gradient(90deg, #ef4444 0%, #facc15 50%, #22c55e 100%);
            font-weight: 700;
            font-size: 14px;
            box-shadow: 0 0 20px rgba(34, 197, 94, 0.5);
        }
        
        /* Badges */
        .badge {
            padding: 6px 14px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 0.85rem;
            border: 1px solid rgba(255, 255, 255, 0.2);
        }
        
        .badge.bg-success {
            background: var(--success-green) !important;
            box-shadow: 0 2px 10px rgba(34, 197, 94, 0.3);
        }
        
        .badge.bg-danger {
            background: var(--danger-red) !important;
            box-shadow: 0 2px 10px rgba(239, 68, 68, 0.3);
        }
        
        .badge.bg-warning {
            background: var(--warning-yellow) !important;
            color: var(--bg-dark) !important;
            box-shadow: 0 2px 10px rgba(250, 204, 21, 0.3);
        }
        
        .badge.bg-secondary {
            background: var(--bg-light) !important;
            color: var(--text-gray-light) !important;
        }
        
        .badge.bg-info {
            background: var(--cyan) !important;
            box-shadow: 0 2px 10px rgba(6, 182, 212, 0.3);
        }
        
        /* Pattern Indicators */
        .pattern-indicator {
            display: inline-block;
            padding: 8px 16px;
            border-radius: 12px;
            font-size: 13px;
            font-weight: 600;
            margin: 4px;
            transition: all 0.3s ease;
            cursor: pointer;
        }
        
        .pattern-indicator:hover {
            transform: translateY(-2px);
        }
        
        .pattern-bullish {
            background: rgba(34, 197, 94, 0.2);
            color: var(--success-green-light);
            border: 2px solid var(--success-green);
            box-shadow: 0 4px 15px rgba(34, 197, 94, 0.2);
        }
        
        .pattern-bearish {
            background: rgba(239, 68, 68, 0.2);
            color: var(--danger-red-light);
            border: 2px solid var(--danger-red);
            box-shadow: 0 4px 15px rgba(239, 68, 68, 0.2);
        }
        
        .pattern-neutral {
            background: rgba(168, 85, 247, 0.2);
            color: var(--purple);
            border: 2px solid var(--purple);
            box-shadow: 0 4px 15px rgba(168, 85, 247, 0.2);
        }
        
        /* TradingView Chart Container */
        .tradingview-widget-container {
            background: var(--bg-light);
            border-radius: 12px;
            overflow: hidden;
        }
        
        /* Chat Container */
        .chat-container {
            height: 400px;
            overflow-y: auto;
            background: var(--bg-light);
            border-radius: 12px;
            padding: 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .chat-container::-webkit-scrollbar {
            width: 8px;
        }
        
        .chat-container::-webkit-scrollbar-track {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 10px;
        }
        
        .chat-container::-webkit-scrollbar-thumb {
            background: var(--primary-blue);
            border-radius: 10px;
        }
        
        .chat-message {
            margin-bottom: 16px;
            padding: 14px 18px;
            border-radius: 14px;
            max-width: 85%;
            animation: slideIn 0.3s ease;
        }
        
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .chat-user {
            background: var(--gradient-blue);
            margin-left: auto;
            box-shadow: 0 4px 15px rgba(59, 130, 246, 0.3);
            color: white;
        }
        
        .chat-bot {
            background: var(--bg-card);
            border: 2px solid rgba(59, 130, 246, 0.3);
            color: var(--text-gray-light);
        }
        
        .chat-bot strong {
            color: var(--primary-blue-light);
        }
        
        /* Stats */
        .stats-item {
            padding: 15px;
            background: var(--bg-light);
            border-radius: 12px;
            margin-bottom: 12px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: all 0.3s ease;
        }
        
        .stats-item:hover {
            background: var(--bg-card-hover);
            border-color: var(--primary-blue);
        }
        
        .stats-value {
            font-size: 1.8rem;
            font-weight: 800;
            color: var(--primary-blue-light);
            text-shadow: 0 2px 10px rgba(59, 130, 246, 0.3);
        }
        
        /* Feature List */
        .feature-list {
            list-style: none;
            padding: 0;
        }
        
        .feature-list li {
            padding: 12px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            color: var(--text-gray-light);
            font-weight: 500;
            transition: all 0.3s ease;
        }
        
        .feature-list li:hover {
            padding-left: 10px;
            color: var(--text-white);
        }
        
        .feature-list li:last-child {
            border-bottom: none;
        }
        
        .feature-list li i {
            width: 24px;
        }
        
        /* ML Models */
        .ml-model-item {
            margin-bottom: 20px;
        }
        
        .ml-model-item h6 {
            color: var(--text-white);
            font-weight: 600;
            margin-bottom: 8px;
        }
        
        .ml-model-item .progress-bar {
            box-shadow: 0 2px 15px rgba(59, 130, 246, 0.4);
        }
        
        .ml-model-item small {
            color: var(--text-gray);
            font-weight: 600;
        }
        
        /* Animations */
        .pulse {
            animation: pulse-scale 2s infinite;
        }
        
        @keyframes pulse-scale {
            0%, 100% {
                transform: scale(1);
            }
            50% {
                transform: scale(1.05);
            }
        }
        
        /* Dropdown */
        .dropdown-menu {
            background: var(--bg-card);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            padding: 8px;
        }
        
        .dropdown-item {
            color: var(--text-gray-light);
            border-radius: 8px;
            padding: 10px 15px;
            margin-bottom: 4px;
            transition: all 0.3s ease;
        }
        
        .dropdown-item:hover {
            background: var(--bg-light);
            color: var(--text-white);
        }
        
        .dropdown-item i {
            width: 20px;
        }
        
        /* Alert Messages */
        .alert {
            border-radius: 12px;
            border: none;
            font-weight: 600;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        }
        
        /* ICT Analysis Cards */
        .ict-card {
            background: var(--bg-light);
            padding: 15px;
            border-radius: 12px;
            margin-bottom: 15px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .ict-card h6 {
            color: var(--primary-blue-light);
            font-weight: 700;
            margin-bottom: 8px;
        }
        
        .ict-card p {
            color: var(--text-white);
            font-weight: 600;
            margin-bottom: 4px;
        }
        
        .ict-card small {
            color: var(--text-gray);
        }
        
        /* Footer */
        .footer-text {
            color: var(--text-gray);
            font-size: 14px;
        }
        
        .footer-text p {
            margin-bottom: 4px;
        }
        
        /* Responsive */
        @media (max-width: 768px) {
            #signalIndicator h2 {
                font-size: 1.8rem;
            }
            
            #currentPrice {
                font-size: 2rem !important;
            }
            
            .chat-message {
                max-width: 95%;
            }
        }
        
        /* Loading Animation */
        @keyframes shimmer {
            0% {
                background-position: -1000px 0;
            }
            100% {
                background-position: 1000px 0;
            }
        }
        
        .loading {
            background: linear-gradient(90deg, var(--bg-card) 0%, var(--bg-light) 50%, var(--bg-card) 100%);
            background-size: 1000px 100%;
            animation: shimmer 2s infinite;
        }
    </style>
</head>
<body>
    <!-- Navigation -->
    <nav class="navbar navbar-expand-lg navbar-dark sticky-top">
        <div class="container-fluid">
            <a class="navbar-brand" href="#">
                <i class="fas fa-robot me-2"></i>
                <strong>Trading Bot v4.0</strong>
                <span class="badge bg-success ms-2">AI-Powered</span>
            </a>
            <div class="d-flex align-items-center">
                <span class="status-indicator status-online"></span>
                <span class="me-3" style="color: var(--success-green); font-weight: 600;">Online</span>
                <div class="dropdown">
                    <button class="btn btn-outline-light btn-sm dropdown-toggle" type="button" data-bs-toggle="dropdown">
                        <i class="fas fa-cog"></i>
                    </button>
                    <ul class="dropdown-menu dropdown-menu-end">
                        <li><a class="dropdown-item" href="#" onclick="refreshAll()"><i class="fas fa-sync-alt me-2"></i>Refresh All</a></li>
                        <li><hr class="dropdown-divider"></li>
                        <li><a class="dropdown-item" href="#" onclick="trainModels()"><i class="fas fa-brain me-2"></i>Train AI Models</a></li>
                        <li><a class="dropdown-item" href="#"><i class="fas fa-history me-2"></i>View Logs</a></li>
                    </ul>
                </div>
            </div>
        </div>
    </nav>

    <div class="container-fluid mt-4 px-4">
        <div class="row">
            <!-- Left Column - Analysis -->
            <div class="col-lg-8">
                <div class="row">
                    <!-- Symbol Selection -->
                    <div class="col-md-12 mb-4">
                        <div class="card">
                            <div class="card-body">
                                <div class="d-flex justify-content-between align-items-center flex-wrap gap-3">
                                    <h5 class="card-title mb-0"><i class="fas fa-chart-line me-2"></i>Market Analysis</h5>
                                    <div class="d-flex gap-2">
                                        <select id="symbolSelect" class="form-select" style="width: 150px;">
                                            <option value="BTCUSDT">BTC/USDT</option>
                                            <option value="ETHUSDT">ETH/USDT</option>
                                            <option value="SOLUSDT">SOL/USDT</option>
                                            <option value="XRPUSDT">XRP/USDT</option>
                                            <option value="ADAUSDT">ADA/USDT</option>
                                        </select>
                                        <select id="intervalSelect" class="form-select" style="width: 120px;">
                                            <option value="1h">1 Hour</option>
                                            <option value="4h">4 Hours</option>
                                            <option value="1d">1 Day</option>
                                        </select>
                                        <button class="btn btn-primary" onclick="analyzeSymbol()">
                                            <i class="fas fa-search me-2"></i>Analyze
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Main Signal Card - BEĞENILEN KISIM -->
                    <div class="col-md-12 mb-4">
                        <div class="card" id="signalCard">
                            <div class="card-body">
                                <div class="row align-items-center g-4">
                                    <div class="col-md-4 text-center">
                                        <h3 id="currentSymbol" style="color: var(--primary-blue-light); font-weight: 700;">BTC/USDT</h3>
                                        <h1 id="currentPrice" class="display-4 fw-bold my-3">$45,231.50</h1>
                                        <p id="priceChange" class="fs-5 mb-0">
                                            <i class="fas fa-arrow-up text-success"></i> 
                                            <span style="color: var(--success-green); font-weight: 700;">+2.34% (24h)</span>
                                        </p>
                                    </div>
                                    
                                    <div class="col-md-4">
                                        <div class="p-4 rounded text-center" id="signalIndicator">
                                            <h2 class="mb-3">NEUTRAL</h2>
                                            <div class="progress mb-3">
                                                <div class="progress-bar" id="confidenceBar" style="width: 50%">50%</div>
                                            </div>
                                            <p id="confidenceText" class="mb-2" style="color: var(--text-white); font-weight: 600; font-size: 1.1rem;">Confidence: 50%</p>
                                            <p id="signalRecommendation" class="mt-3 mb-0" style="color: var(--text-gray-light); font-size: 0.95rem;">Wait for better setup</p>
                                        </div>
                                    </div>
                                    
                                    <div class="col-md-4">
                                        <div class="text-start">
                                            <h5 style="color: var(--text-white); font-weight: 700; margin-bottom: 1rem;">
                                                <i class="fas fa-chart-bar me-2" style="color: var(--primary-blue);"></i>Indicators
                                            </h5>
                                            <ul class="list-unstyled">
                                                <li class="mb-3">
                                                    <span style="color: var(--text-gray-light); font-weight: 500;">EMA (9/21):</span>
                                                    <span id="emaSignal" class="badge bg-secondary ms-2">Neutral</span>
                                                </li>
                                                <li class="mb-3">
                                                    <span style="color: var(--text-gray-light); font-weight: 500;">RSI (14):</span>
                                                    <span id="rsiValue" class="badge bg-info ms-2">54.2</span>
                                                </li>
                                                <li class="mb-3">
                                                    <span style="color: var(--text-gray-light); font-weight: 500;">Heikin Ashi:</span>
                                                    <span id="haTrend" class="badge bg-success ms-2">Bullish</span>
                                                </li>
                                                <li class="mb-0">
                                                    <span style="color: var(--text-gray-light); font-weight: 500;">Market Structure:</span>
                                                    <span id="marketStructure" class="badge bg-success ms-2">Bullish</span>
                                                </li>
                                            </ul>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- TradingView Chart -->
                    <div class="col-md-12 mb-4">
                        <div class="card">
                            <div class="card-body p-0">
                                <div class="tradingview-widget-container" style="height: 500px; width: 100%;">
                                    <div id="tradingview_chart"></div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Pattern Detection & ICT Analysis -->
                    <div class="col-md-6 mb-4">
                        <div class="card h-100">
                            <div class="card-body">
                                <h5 class="card-title"><i class="fas fa-shapes me-2"></i>Candlestick Patterns</h5>
                                <div id="patternsContainer" class="mt-3">
                                    <div class="pattern-indicator pattern-bullish">Hammer</div>
                                    <div class="pattern-indicator pattern-bullish">Bullish Engulfing</div>
                                    <div class="pattern-indicator pattern-bearish">Shooting Star</div>
                                    <div class="pattern-indicator pattern-neutral">Doji</div>
                                </div>
                                <p class="mt-3 mb-0" id="patternCount" style="color: var(--text-gray); font-weight: 500;">
                                    4 patterns detected in last 10 candles
                                </p>
                            </div>
                        </div>
                    </div>

                    <div class="col-md-6 mb-4">
                        <div class="card h-100">
                            <div class="card-body">
                                <h5 class="card-title"><i class="fas fa-chess-board me-2"></i>ICT Analysis</h5>
                                <div class="mt-3">
                                    <div class="ict-card">
                                        <h6>Fair Value Gaps</h6>
                                        <p id="fvgCount">2 FVGs detected</p>
                                        <small>Price tends to fill these gaps</small>
                                    </div>
                                    <div class="ict-card">
                                        <h6>Order Blocks</h6>
                                        <p id="obCount">1 Order Block detected</p>
                                        <small>Institutional buying/selling zones</small>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- ML Prediction -->
                    <div class="col-md-12 mb-4">
                        <div class="card">
                            <div class="card-body">
                                <div class="d-flex justify-content-between align-items-center mb-4">
                                    <h5 class="card-title mb-0"><i class="fas fa-brain me-2"></i>AI Prediction Models</h5>
                                    <button class="btn btn-sm btn-outline-success" onclick="trainCurrentSymbol()">
                                        <i class="fas fa-graduation-cap me-1"></i>Train
                                    </button>
                                </div>
                                <div class="row g-4">
                                    <div class="col-md-4">
                                        <div class="ml-model-item">
                                            <h6>LightGBM</h6>
                                            <div class="progress mb-2" style="height: 12px;">
                                                <div class="progress-bar bg-success" style="width: 78%"></div>
                                            </div>
                                            <small>Accuracy: 78%</small>
                                        </div>
                                    </div>
                                    <div class="col-md-4">
                                        <div class="ml-model-item">
                                            <h6>LSTM</h6>
                                            <div class="progress mb-2" style="height: 12px;">
                                                <div class="progress-bar" style="width: 82%; background: var(--cyan);"></div>
                                            </div>
                                            <small>Accuracy: 82%</small>
                                        </div>
                                    </div>
                                    <div class="col-md-4">
                                        <div class="ml-model-item">
                                            <h6>Transformer</h6>
                                            <div class="progress mb-2" style="height: 12px;">
                                                <div class="progress-bar" style="width: 85%; background: var(--warning-yellow);"></div>
                                            </div>
                                            <small>Accuracy: 85%</small>
                                        </div>
                                    </div>
                                </div>
                                <p class="mt-4 mb-0" id="mlPrediction" style="color: var(--text-white); font-weight: 600; font-size: 1.05rem;">
                                    AI Ensemble: <strong style="color: var(--success-green);">BUY</strong> signal with 76% confidence
                                </p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Right Column - Chat & Stats -->
            <div class="col-lg-4">
                <!-- AI Chat Assistant -->
                <div class="card mb-4">
                    <div class="card-body">
                        <h5 class="card-title"><i class="fas fa-robot me-2"></i>AI Trading Assistant</h5>
                        <div class="chat-container mt-3" id="chatMessages">
                            <div class="chat-message chat-bot">
                                <strong>🤖 Trading Assistant:</strong><br>
                                Hello! I'm your AI trading assistant. I can help with technical analysis, pattern recognition, and trading strategies. How can I assist you today?
                            </div>
                        </div>
                        <div class="input-group mt-3">
                            <input type="text" class="form-control" id="chatInput" placeholder="Ask about patterns, strategies, or analysis...">
                            <button class="btn btn-primary" type="button" onclick="sendMessage()">
                                <i class="fas fa-paper-plane"></i>
                            </button>
                        </div>
                        <div class="mt-2">
                            <small style="color: var(--text-gray);">Try: "Explain hammer pattern", "Analyze BTC", "Trading strategy tips"</small>
                        </div>
                    </div>
                </div>

                <!-- Quick Stats -->
                <div class="card mb-4">
                    <div class="card-body">
                        <h5 class="card-title"><i class="fas fa-tachometer-alt me-2"></i>Quick Stats</h5>
                        <div class="mt-3">
                            <div class="stats-item">
                                <div class="d-flex justify-content-between align-items-center">
                                    <span style="color: var(--text-gray-light); font-weight: 500;">Analysis Requests</span>
                                    <span class="stats-value" id="requestCount">142</span>
                                </div>
                            </div>
                            <div class="stats-item">
                                <div class="d-flex justify-content-between align-items-center">
                                    <span style="color: var(--text-gray-light); font-weight: 500;">Models Trained</span>
                                    <span class="stats-value" id="trainedModels">5</span>
                                </div>
                            </div>
                            <div class="stats-item">
                                <div class="d-flex justify-content-between align-items-center">
                                    <span style="color: var(--text-gray-light); font-weight: 500;">Patterns Detected</span>
                                    <span class="stats-value" id="totalPatterns">124</span>
                                </div>
                            </div>
                            <div class="stats-item">
                                <div class="d-flex justify-content-between align-items-center">
                                    <span style="color: var(--text-gray-light); font-weight: 500;">Uptime</span>
                                    <span class="stats-value" style="color: var(--success-green);">99.8%</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Features -->
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title"><i class="fas fa-star me-2"></i>Features</h5>
                        <ul class="feature-list mt-3">
                            <li><i class="fas fa-check-circle text-success me-2"></i>Real-time Price Data</li>
                            <li><i class="fas fa-check-circle text-success me-2"></i>12 Candlestick Patterns</li>
                            <li><i class="fas fa-check-circle text-success me-2"></i>ICT Market Structure</li>
                            <li><i class="fas fa-check-circle text-success me-2"></i>Advanced ML Models</li>
                            <li><i class="fas fa-check-circle text-success me-2"></i>Multi-Timeframe Analysis</li>
                            <li><i class="fas fa-check-circle text-success me-2"></i>AI Chat Assistant</li>
                            <li><i class="fas fa-check-circle text-success me-2"></i>Risk Management</li>
                            <li><i class="fas fa-check-circle text-success me-2"></i>WebSocket Support</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>

        <!-- Footer -->
        <div class="row mt-4">
            <div class="col-12">
                <div class="text-center footer-text py-4">
                    <p class="mb-1" style="font-weight: 600; color: var(--text-gray-light);">Professional Trading Bot v4.0 • Advanced AI Trading System</p>
                    <small>© 2024 • Trading signals are for educational purposes only. Trade at your own risk.</small>
                </div>
            </div>
        </div>
    </div>

    <!-- Bootstrap JS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    
    <!-- TradingView Widget Script -->
    <script type="text/javascript">
    function loadTradingViewWidget(symbol = "BTCUSDT", interval = "60") {
        const container = document.getElementById("tradingview_chart");
        if (!container) return;

        container.innerHTML = '';

        const script = document.createElement("script");
        script.type = "text/javascript";
        script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
        script.async = true;

        const config = {
            "autosize": true,
            "symbol": `BINANCE:${symbol}`,
            "interval": interval === "1h" ? "60" : interval === "4h" ? "240" : "D",
            "timezone": "Etc/UTC",
            "theme": "dark",
            "style": "1",
            "locale": "en",
            "toolbar_bg": "#1a1f3a",
            "enable_publishing": false,
            "allow_symbol_change": true,
            "calendar": false,
            "support_host": "https://www.tradingview.com"
        };

        script.text = JSON.stringify(config);
        container.appendChild(script);
    }
    </script>
    
    <script>
        // Initialize
        document.addEventListener('DOMContentLoaded', function() {
            loadTradingViewWidget();
            analyzeSymbol();
            updateStats();
        });

        // Analyze selected symbol
        async function analyzeSymbol() {
            const symbol = document.getElementById('symbolSelect').value;
            const interval = document.getElementById('intervalSelect').value;
            
            document.getElementById('signalCard').classList.add('pulse');
            document.getElementById('currentSymbol').textContent = symbol.replace('USDT', '/USDT');
            
            // Load TradingView widget
            loadTradingViewWidget(symbol, interval === "1h" ? "60" : interval === "4h" ? "240" : "D");
            
            try {
                const response = await fetch(`/api/analyze/${symbol}?interval=${interval}`);
                
                // Check if response is ok and content-type is JSON
                if (!response.ok) {
                    console.warn('API endpoint not available, using demo mode');
                    useDemoData(symbol);
                    return;
                }
                
                const contentType = response.headers.get("content-type");
                if (!contentType || !contentType.includes("application/json")) {
                    console.warn('API returned non-JSON response, using demo mode');
                    useDemoData(symbol);
                    return;
                }
                
                const data = await response.json();
                
                if (data.success) {
                    updateDashboard(data);
                } else {
                    useDemoData(symbol);
                }
            } catch (error) {
                console.warn('API not available, using demo mode:', error);
                useDemoData(symbol);
            } finally {
                document.getElementById('signalCard').classList.remove('pulse');
            }
        }
        
        // Demo data for when API is not available
        function useDemoData(symbol) {
            const demoData = {
                success: true,
                symbol: symbol,
                price_data: {
                    current: Math.random() * 50000 + 40000,
                    change_percent: (Math.random() - 0.5) * 10
                },
                signal: {
                    signal: ['STRONG_BUY', 'BUY', 'NEUTRAL', 'SELL', 'STRONG_SELL'][Math.floor(Math.random() * 5)],
                    confidence: Math.floor(Math.random() * 40) + 60,
                    recommendation: 'Demo mode - Connect backend for real signals',
                    components: {
                        ema: { signal: 'BUY' }
                    }
                },
                indicators: {
                    rsi: Math.random() * 40 + 30,
                    heikin_ashi_trend: Math.random() > 0.5 ? 'Bullish' : 'Bearish'
                },
                ict_analysis: {
                    market_structure: {
                        structure: Math.random() > 0.5 ? 'Bullish' : 'Bearish'
                    },
                    fair_value_gaps: [1, 2],
                    order_blocks: [1]
                },
                patterns: [
                    { name: 'Hammer', direction: 'bullish' },
                    { name: 'Engulfing', direction: 'bullish' },
                    { name: 'Doji', direction: 'neutral' },
                    { name: 'Shooting Star', direction: 'bearish' }
                ],
                ml_prediction: {
                    prediction: Math.random() > 0.5 ? 'BUY' : 'SELL',
                    confidence: Math.random() * 0.3 + 0.7
                }
            };
            
            updateDashboard(demoData);
        }

        // Update dashboard with analysis data
        function updateDashboard(data) {
            // Update price data
            document.getElementById('currentPrice').textContent = `$${data.price_data.current.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            const changeElem = document.getElementById('priceChange');
            const change = data.price_data.change_percent;
            const arrow = change >= 0 ? '<i class="fas fa-arrow-up"></i>' : '<i class="fas fa-arrow-down"></i>';
            const color = change >= 0 ? 'var(--success-green)' : 'var(--danger-red)';
            changeElem.innerHTML = `${arrow} <span style="color: ${color}; font-weight: 700;">${change >= 0 ? '+' : ''}${change.toFixed(2)}% (24h)</span>`;
            
            // Update signal
            const signal = data.signal.signal;
            const confidence = data.signal.confidence;
            const signalIndicator = document.getElementById('signalIndicator');
            const confidenceBar = document.getElementById('confidenceBar');
            
            // Set signal colors and text
            if (signal.includes('BUY')) {
                signalIndicator.className = 'p-4 rounded text-center signal-buy';
                if (signal === 'STRONG_BUY') {
                    signalIndicator.classList.add('pulse');
                }
            } else if (signal.includes('SELL')) {
                signalIndicator.className = 'p-4 rounded text-center signal-sell';
                if (signal === 'STRONG_SELL') {
                    signalIndicator.classList.add('pulse');
                }
            } else {
                signalIndicator.className = 'p-4 rounded text-center signal-neutral';
            }
            
            document.querySelector('#signalIndicator h2').textContent = signal.replace('_', ' ');
            confidenceBar.style.width = `${confidence}%`;
            confidenceBar.textContent = `${confidence}%`;
            document.getElementById('confidenceText').textContent = `Confidence: ${confidence}%`;
            document.getElementById('signalRecommendation').textContent = data.signal.recommendation;
            
            // Update indicators with colors
            const emaSignal = data.signal.components.ema?.signal || 'Neutral';
            const emaElem = document.getElementById('emaSignal');
            emaElem.textContent = emaSignal;
            emaElem.className = `badge ms-2 ${emaSignal.includes('BUY') ? 'bg-success' : emaSignal.includes('SELL') ? 'bg-danger' : 'bg-secondary'}`;
            
            document.getElementById('rsiValue').textContent = data.indicators.rsi?.toFixed(1) || 'N/A';
            
            const haTrend = data.indicators.heikin_ashi_trend || 'Neutral';
            const haElem = document.getElementById('haTrend');
            haElem.textContent = haTrend;
            haElem.className = `badge ms-2 ${haTrend === 'Bullish' ? 'bg-success' : haTrend === 'Bearish' ? 'bg-danger' : 'bg-secondary'}`;
            
            const marketStruct = data.ict_analysis.market_structure?.structure || 'Unknown';
            const msElem = document.getElementById('marketStructure');
            msElem.textContent = marketStruct;
            msElem.className = `badge ms-2 ${marketStruct === 'Bullish' ? 'bg-success' : marketStruct === 'Bearish' ? 'bg-danger' : 'bg-secondary'}`;
            
            // Update patterns
            const patternsContainer = document.getElementById('patternsContainer');
            patternsContainer.innerHTML = '';
            if (data.patterns && data.patterns.length > 0) {
                const recentPatterns = data.patterns.slice(-6);
                recentPatterns.forEach(pattern => {
                    const div = document.createElement('div');
                    div.className = `pattern-indicator ${pattern.direction === 'bullish' ? 'pattern-bullish' : pattern.direction === 'bearish' ? 'pattern-bearish' : 'pattern-neutral'}`;
                    div.textContent = pattern.name;
                    patternsContainer.appendChild(div);
                });
                document.getElementById('patternCount').textContent = `${data.patterns.length} patterns detected in last 100 candles`;
            }
            
            // Update ICT analysis
            const fvgCount = data.ict_analysis.fair_value_gaps?.length || 0;
            const obCount = data.ict_analysis.order_blocks?.length || 0;
            document.getElementById('fvgCount').textContent = `${fvgCount} FVG${fvgCount !== 1 ? 's' : ''} detected`;
            document.getElementById('obCount').textContent = `${obCount} Order Block${obCount !== 1 ? 's' : ''} detected`;
            
            // Update ML prediction
            if (data.ml_prediction) {
                const mlPrediction = data.ml_prediction.prediction;
                const mlConfidence = (data.ml_prediction.confidence * 100).toFixed(1);
                const predColor = mlPrediction === 'BUY' ? 'var(--success-green)' : mlPrediction === 'SELL' ? 'var(--danger-red)' : 'var(--text-gray)';
                document.getElementById('mlPrediction').innerHTML = `AI Ensemble: <strong style="color: ${predColor};">${mlPrediction}</strong> signal with ${mlConfidence}% confidence`;
            }
            
            updateStats();
        }

        // Train ML models for current symbol
        async function trainCurrentSymbol() {
            const symbol = document.getElementById('symbolSelect').value;
            
            try {
                const response = await fetch(`/api/train/${symbol}`, {
                    method: 'POST'
                });
                
                // Check if API is available
                if (!response.ok) {
                    throw new Error('API not available');
                }
                
                const contentType = response.headers.get("content-type");
                if (!contentType || !contentType.includes("application/json")) {
                    throw new Error('Invalid response type');
                }
                
                const data = await response.json();
                
                if (data.success) {
                    showMessage(`✅ Successfully trained models for ${symbol}`);
                    updateStats();
                } else {
                    showMessage(`⚠️ Training started for ${symbol} (Demo Mode)`);
                }
            } catch (error) {
                console.warn('Training API not available:', error);
                showMessage(`⚠️ Demo Mode: Connect backend to train models`);
            }
        }

        // Chat functionality
        async function sendMessage() {
            const input = document.getElementById('chatInput');
            const message = input.value.trim();
            
            if (!message) return;
            
            addChatMessage(message, 'user');
            input.value = '';
            
            const symbol = document.getElementById('symbolSelect').value;
            
            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        message: message,
                        symbol: symbol
                    })
                });
                
                // Check if API is available
                if (!response.ok) {
                    throw new Error('API not available');
                }
                
                const contentType = response.headers.get("content-type");
                if (!contentType || !contentType.includes("application/json")) {
                    throw new Error('Invalid response type');
                }
                
                const data = await response.json();
                
                if (data.success) {
                    setTimeout(() => {
                        addChatMessage(data.response, 'bot');
                    }, 500);
                }
            } catch (error) {
                console.warn('Chat API not available:', error);
                // Demo response
                setTimeout(() => {
                    const demoResponses = [
                        "I'm running in demo mode. Connect the backend API for real-time analysis.",
                        "This is a demo response. The backend API endpoint needs to be configured.",
                        `Analyzing ${symbol}... Please set up the backend server for real data.`
                    ];
                    addChatMessage(demoResponses[Math.floor(Math.random() * demoResponses.length)], 'bot');
                }, 500);
            }
        }

        // Add message to chat container
        function addChatMessage(message, sender) {
            const chatMessages = document.getElementById('chatMessages');
            const messageDiv = document.createElement('div');
            
            messageDiv.className = `chat-message ${sender === 'user' ? 'chat-user' : 'chat-bot'}`;
            messageDiv.innerHTML = `<strong>${sender === 'user' ? '👤 You:' : '🤖 Assistant:'}</strong><br>${message}`;
            
            chatMessages.appendChild(messageDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        // Update statistics
        function updateStats() {
            const requestCount = document.getElementById('requestCount');
            requestCount.textContent = parseInt(requestCount.textContent) + 1;
            
            const patterns = document.querySelectorAll('.pattern-indicator').length;
            if (patterns > 0) {
                document.getElementById('totalPatterns').textContent = 
                    parseInt(document.getElementById('totalPatterns').textContent) + patterns;
            }
        }

        // Refresh all data
        function refreshAll() {
            analyzeSymbol();
            showMessage('🔄 Refreshing all data...');
        }

        // Train models
        function trainModels() {
            trainCurrentSymbol();
        }

        // Show message
        function showMessage(text) {
            const alertDiv = document.createElement('div');
            alertDiv.className = 'alert alert-success alert-dismissible fade show position-fixed bottom-0 end-0 m-3';
            alertDiv.style.zIndex = '9999';
            alertDiv.innerHTML = `
                ${text}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;
            document.body.appendChild(alertDiv);
            
            setTimeout(() => {
                alertDiv.remove();
            }, 3000);
        }

        // Show error
        function showError(text) {
            const alertDiv = document.createElement('div');
            alertDiv.className = 'alert alert-danger alert-dismissible fade show position-fixed bottom-0 end-0 m-3';
            alertDiv.style.zIndex = '9999';
            alertDiv.innerHTML = `
                ❌ ${text}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;
            document.body.appendChild(alertDiv);
            
            setTimeout(() => {
                alertDiv.remove();
            }, 3000);
        }

        // Enter key for chat
        document.getElementById('chatInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });

        // Auto-refresh every 60 seconds
        setInterval(analyzeSymbol, 60000);
    </script>
</body>
</html>
  """

# ========== TEST FUNCTIONS ==========
async def test_price_fetcher():
    """Test and example usage"""
    fetcher = PriceFetcher(max_cache_age=60)
    
    print("=" * 80)
    print("PROFESSIONAL PRICE FETCHER TEST")
    print("=" * 80)
    
    # Health check
    print("\n1️⃣ Health Check...")
    health = await fetcher.health_check()
    for exchange, status in health.items():
        print(f"  {exchange}: {status}")
    
    # Single symbol test
    print("\n2️⃣ BTC/USDT - 1 Hour Test...")
    candles = await fetcher.get_candles("BTCUSDT", "1h", 50)
    if candles:
        print(f"  ✅ {len(candles)} candles received")
        print(f"  First candle: {datetime.fromtimestamp(candles[0]['timestamp']/1000)}")
        print(f"  Last candle: {datetime.fromtimestamp(candles[-1]['timestamp']/1000)}")
        print(f"  Last price: ${candles[-1]['close']:.2f}")
    
    # Multiple timeframes
    print("\n3️⃣ All Timeframe Test...")
    for tf in ["1m", "5m", "15m", "30m", "1h", "4h", "1D", "1W"]:
        candles = await fetcher.get_candles("BTCUSDT", tf, 10)
        status = f"✅ {len(candles)} candles" if candles else "❌ Failed"
        print(f"  {tf:4s}: {status}")
    
    # Multiple symbols
    print("\n4️⃣ Multiple Symbol Test...")
    multi = await fetcher.get_multiple_symbols(
        ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "1h",
        20
    )
    for sym, data in multi.items():
        print(f"  {sym}: {len(data)} candles")
    
    # Statistics
    print("\n5️⃣ Statistics:")
    stats = fetcher.get_stats()
    print(f"  Total requests: {stats['total_requests']}")
    print(f"  Successful: {stats['successful_fetches']}")
    print(f"  Failed: {stats['failed_fetches']}")
    print(f"  Cache hits: {stats['cache_hits']}")
    print(f"  Cache size: {stats['cache_size']}")
    
    # Test small coin (CoinGecko fallback test)
    print("\n6️⃣ Small Coin Test (CoinGecko fallback)...")
    small_coin = await fetcher.get_candles("AVAXUSDT", "1h", 10)
    if small_coin:
        print(f"  ✅ AVAX: {len(small_coin)} candles received")
    
    print("\n" + "=" * 80)
    print("TEST COMPLETED")
    print("=" * 80)

# ========== MAIN ENTRY POINT ==========
if __name__ == "__main__":
    import uvicorn
    import signal
    import sys
    
    def signal_handler(sig, frame):
        logger.info("Shutdown signal received")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info(f"Starting Professional AI Trading Bot v4.0 on {host}:{port}")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True
    ) 
xxxxxxxxxxxxxxxxxxxxxxx
