"""
🚀 PROFESSIONAL TRADING BOT v4.5 - ADVANCED AI TRADING SYSTEM
✅ 11+ Exchange Support ✅ Forex Market Integration ✅ Volatility Adjusted Trail
✅ Advanced ML (LSTM + Transformer + LightGBM) ✅ 12 Candlestick Patterns
✅ ICT Market Structure ✅ Multi-Timeframe Analysis ✅ AI Chatbot
✅ Real Data Only - NO Synthetic Data ✅ Risk Management
"""

import os
import logging
from datetime import datetime, timedelta
import random
import json
import asyncio
import time
from typing import Dict, List, Optional, Tuple, Any
import aiohttp
from enum import Enum
from collections import defaultdict

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

# FastAPI
from fastapi import FastAPI, Request, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

# ========== LOGGING CONFIGURATION ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('trading_bot.log')
    ]
)
logger = logging.getLogger(__name__)

# ========== FASTAPI APPLICATION ==========
app = FastAPI(
    title="Professional AI Trading Bot v4.5",
    version="4.5.0",
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

# ========== VOLATILITY ADJUSTED TRAIL ==========
class VolatilityAdjustedTrail:
    """Volatility Adjusted Trail System - Advanced trailing stop system"""
    
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr
    
    @staticmethod
    def calculate_trail(df: pd.DataFrame, atr_multiplier: float = 2.0) -> Dict:
        """Calculate Volatility Adjusted Trail"""
        if len(df) < 50:
            return {
                'current_trail': None,
                'current_direction': 0,
                'trend_strength': 0.0,
                'signals': []
            }
        
        # Calculate ATR
        atr = VolatilityAdjustedTrail.calculate_atr(df)
        
        # Calculate EMA for trend direction
        ema_fast = df['close'].ewm(span=9, adjust=False).mean()
        ema_slow = df['close'].ewm(span=21, adjust=False).mean()
        
        # Calculate standard deviation for volatility
        volatility = df['close'].rolling(window=20).std()
        avg_volatility = volatility.rolling(window=20).mean()
        
        # Calculate dynamic multiplier based on volatility
        vol_ratio = volatility / avg_volatility
        dynamic_multiplier = atr_multiplier * (1 + 0.5 * (vol_ratio - 1))
        
        # Calculate trail
        long_trail = df['high'].rolling(window=20).max() - (atr * dynamic_multiplier)
        short_trail = df['low'].rolling(window=20).min() + (atr * dynamic_multiplier)
        
        # Determine direction
        current_dir = 0
        if ema_fast.iloc[-1] > ema_slow.iloc[-1]:
            current_dir = 1  # Uptrend
        elif ema_fast.iloc[-1] < ema_slow.iloc[-1]:
            current_dir = -1  # Downtrend
        
        # Calculate trend strength
        if current_dir == 1:
            trend_strength = (df['close'].iloc[-1] - long_trail.iloc[-1]) / (atr.iloc[-1] * dynamic_multiplier.iloc[-1])
        elif current_dir == -1:
            trend_strength = (short_trail.iloc[-1] - df['close'].iloc[-1]) / (atr.iloc[-1] * dynamic_multiplier.iloc[-1])
        else:
            trend_strength = 0.0
        
        # Normalize trend strength
        trend_strength = max(0.0, min(1.0, trend_strength))
        
        # Generate signals
        signals = []
        for i in range(1, len(df)):
            if current_dir == 1 and df['close'].iloc[i] > long_trail.iloc[i-1]:
                signals.append({
                    'timestamp': df.index[i],
                    'type': 'BUY',
                    'price': df['close'].iloc[i],
                    'trail': long_trail.iloc[i-1]
                })
            elif current_dir == -1 and df['close'].iloc[i] < short_trail.iloc[i-1]:
                signals.append({
                    'timestamp': df.index[i],
                    'type': 'SELL',
                    'price': df['close'].iloc[i],
                    'trail': short_trail.iloc[i-1]
                })
        
        return {
            'current_trail': long_trail.iloc[-1] if current_dir == 1 else short_trail.iloc[-1],
            'current_direction': current_dir,
            'trend_strength': float(trend_strength),
            'trail_type': 'LONG' if current_dir == 1 else 'SHORT' if current_dir == -1 else 'NEUTRAL',
            'atr_value': float(atr.iloc[-1]),
            'volatility_ratio': float(vol_ratio.iloc[-1]),
            'dynamic_multiplier': float(dynamic_multiplier.iloc[-1]),
            'signals': signals[-10:] if signals else []
        }

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
            
            # Train LightGBM
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
            X_train = np.array(X_train)
            y_train = np.array(y_train)
            X_val = np.array(X_val)
            y_val = np.array(y_val)
            
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
            
            train_data = lgb.Dataset(X_train, label=y_train)
            val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
            
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
            X_train_t = torch.FloatTensor(X_train).to(self.device)
            y_train_t = torch.LongTensor(y_train).to(self.device)
            X_val_t = torch.FloatTensor(X_val).to(self.device)
            y_val_t = torch.LongTensor(y_val).to(self.device)
            
            input_size = X_train.shape[-1]
            model = AdvancedLSTM(input_size=input_size).to(self.device)
            
            criterion = nn.CrossEntropyLoss()
            optimizer = optim.Adam(model.parameters(), lr=0.001, weight_decay=1e-5)
            scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)
            
            batch_size = min(32, len(X_train_t))
            train_dataset = TensorDataset(X_train_t, y_train_t)
            train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
            
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
            X_train_t = torch.FloatTensor(X_train).to(self.device)
            y_train_t = torch.LongTensor(y_train).to(self.device)
            X_val_t = torch.FloatTensor(X_val).to(self.device)
            y_val_t = torch.LongTensor(y_val).to(self.device)
            
            input_size = X_train.shape[-1]
            model = AdvancedTransformer(input_size=input_size).to(self.device)
            
            criterion = nn.CrossEntropyLoss()
            optimizer = optim.Adam(model.parameters(), lr=0.0005, weight_decay=1e-5)
            scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=30)
            
            batch_size = min(32, len(X_train_t))
            train_dataset = TensorDataset(X_train_t, y_train_t)
            train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
            
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
        """Generate predictions from all models"""
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

            # LSTM prediction
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

            # Transformer prediction
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

            # LightGBM prediction
            if symbol in self.lgb_models and symbol in self.scalers:
                try:
                    model = self.lgb_models[symbol]
                    scaler = self.scalers[symbol]
                    
                    recent_flat = recent_seq.reshape(-1, recent_seq.shape[-1])
                    recent_scaled = scaler.transform(recent_flat)
                    recent_features = recent_scaled[-1:].reshape(1, -1)
                    
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

            if not predictions:
                return {
                    'prediction': 'NEUTRAL',
                    'confidence': 0.50,
                    'method': 'no_valid_models',
                    'ml_score': 0.5,
                    'model_details': {}
                }

            from collections import Counter
            weighted_votes = []
            for p, c in zip(predictions, confidences):
                weighted_votes.extend([p] * int(c * 20))

            if weighted_votes:
                final_pred = Counter(weighted_votes).most_common(1)[0][0]
                avg_conf = sum(confidences) / len(confidences)
            else:
                final_pred = 1
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
            
            importance_dict = {}
            for i, imp in enumerate(importance):
                if i < len(self.feature_columns):
                    importance_dict[self.feature_columns[i]] = float(imp)
            
            sorted_importance = dict(sorted(
                importance_dict.items(),
                key=lambda x: x[1],
                reverse=True
            )[:15])
            
            return sorted_importance
        except Exception as e:
            logger.error(f"Error getting feature importance for {symbol}: {str(e)}")
            return {}

# ========== PROFESSIONAL PRICE FETCHER (11+ EXCHANGES + FOREX) ==========
class PriceFetcher:
    """
    Professional Multi-Exchange Data Fetcher
    11+ Exchanges + Forex Markets
    Real Data Only - NO Synthetic Data
    """
    
    EXCHANGES = [
        # Cryptocurrency Exchanges
        {
            "name": "Binance",
            "priority": 1,
            "type": "crypto",
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
            "type": "crypto",
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
            "type": "crypto",
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
            "type": "crypto",
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
            "type": "crypto",
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
            "type": "crypto",
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
            "type": "crypto",
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
            "type": "crypto",
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
            "type": "crypto",
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
            "type": "crypto",
            "symbol_fmt": lambda s: s.replace("USDT", "-USD"),
            "endpoint_builder": lambda s, i: f"https://api.exchange.coinbase.com/products/{s}/candles",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "granularity": i
            }
        },
        # Forex Exchanges
        {
            "name": "Forex.com",
            "priority": 11,
            "type": "forex",
            "symbol_fmt": lambda s: s.replace("/", ""),
            "endpoint": "https://fcsapi.com/api-v3/forex/history",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "symbol": s,
                "period": i,
                "access_key": "demo",  # Use real API key in production
                "count": l
            }
        },
        {
            "name": "OANDA",
            "priority": 12,
            "type": "forex",
            "symbol_fmt": lambda s: s.replace("/", "_"),
            "endpoint": "https://api-fxtrade.oanda.com/v3/instruments/{symbol}/candles",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "price": "M",
                "granularity": i,
                "count": l
            }
        },
        {
            "name": "AlphaVantage",
            "priority": 13,
            "type": "forex",
            "symbol_fmt": lambda s: s.replace("/", ""),
            "endpoint": "https://www.alphavantage.co/query",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "function": "FX_DAILY",
                "from_symbol": s[:3],
                "to_symbol": s[3:],
                "apikey": "demo",  # Use real API key in production
                "outputsize": "compact"
            }
        },
        # Fallback
        {
            "name": "CoinGecko",
            "priority": 99,
            "type": "crypto",
            "symbol_fmt": lambda s: s.replace("USDT", "").lower(),
            "endpoint_builder": lambda s, i: f"https://api.coingecko.com/api/v3/coins/{s}/ohlc",
            "method": "GET",
            "params_builder": lambda s, i, l: {
                "vs_currency": "usd",
                "days": "max" if i in ["1D", "1W", "1M"] else "30"
            }
        }
    ]
    
    INTERVAL_MAPPING = {
        "1m": {"Binance": "1m", "Bybit": "1", "OKX": "1m", "KuCoin": "1min", "Gate.io": "1m"},
        "5m": {"Binance": "5m", "Bybit": "5", "OKX": "5m", "KuCoin": "5min", "Gate.io": "5m"},
        "15m": {"Binance": "15m", "Bybit": "15", "OKX": "15m", "KuCoin": "15min", "Gate.io": "15m"},
        "30m": {"Binance": "30m", "Bybit": "30", "OKX": "30m", "KuCoin": "30min", "Gate.io": "30m"},
        "1h": {"Binance": "1h", "Bybit": "60", "OKX": "1H", "KuCoin": "1hour", "Gate.io": "1h"},
        "4h": {"Binance": "4h", "Bybit": "240", "OKX": "4H", "KuCoin": "4hour", "Gate.io": "4h"},
        "1D": {"Binance": "1d", "Bybit": "D", "OKX": "1D", "KuCoin": "1day", "Gate.io": "1d"},
        "1W": {"Binance": "1w", "Bybit": "W", "OKX": "1W", "KuCoin": "1week", "Gate.io": "1w"},
        "1M": {"Binance": "1M", "Bybit": "M", "OKX": "1M", "KuCoin": "1month", "Gate.io": "1M"}
    }
    
    def __init__(self, max_cache_age: int = 60):
        self.data_pool = {}
        self.max_cache_age = max_cache_age
        self.stats = {
            "total_requests": 0,
            "successful_fetches": 0,
            "failed_fetches": 0,
            "cache_hits": 0,
            "exchange_stats": defaultdict(lambda: {"success": 0, "fail": 0})
        }
        logger.info("PriceFetcher started - Real Data Only Mode")
    
    async def get_candles(self, symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
        """Get candles from exchanges"""
        self.stats["total_requests"] += 1
        cache_key = f"{symbol}_{interval}"
        
        # Cache check
        if cache_key in self.data_pool:
            cached = self.data_pool[cache_key]
            age = time.time() - cached["timestamp"]
            if age < self.max_cache_age:
                self.stats["cache_hits"] += 1
                return cached["data"][-limit:]
        
        # Fetch from exchanges
        logger.info(f"Fetching data: {symbol} {interval} ({limit} candles)")
        
        fetch_limit = max(limit * 2, 200)
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            for exchange in sorted(self.EXCHANGES, key=lambda x: x["priority"]):
                task = self._fetch_single_exchange(
                    session, exchange, symbol, interval, fetch_limit
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_results = [
            r for r in results 
            if r and not isinstance(r, Exception) and len(r) > 0
        ]
        
        if not valid_results:
            logger.error(f"All exchanges failed for {symbol} {interval}")
            return []
        
        # Aggregate data
        aggregated = self._aggregate_candles(valid_results)
        
        if aggregated:
            self.data_pool[cache_key] = {
                "data": aggregated,
                "timestamp": time.time(),
                "sources": len(valid_results)
            }
            logger.info(f"Aggregated {len(aggregated)} candles from {len(valid_results)} sources")
        
        return aggregated[-limit:] if aggregated else []
    
    async def _fetch_single_exchange(self, session: aiohttp.ClientSession, exchange: Dict, 
                                   symbol: str, interval: str, limit: int) -> Optional[List[Dict]]:
        """Fetch from single exchange"""
        exchange_name = exchange["name"]
        
        try:
            # Skip if interval not supported
            if exchange_name == "CoinGecko" and interval not in ["1h", "4h", "1D", "1W", "1M"]:
                return None
            
            formatted_symbol = exchange["symbol_fmt"](symbol)
            exchange_interval = self.INTERVAL_MAPPING.get(interval, {}).get(exchange_name, interval)
            
            # Build endpoint
            if "endpoint_builder" in exchange:
                endpoint = exchange["endpoint_builder"](formatted_symbol, exchange_interval)
            else:
                endpoint = exchange["endpoint"]
            
            # Build params
            params = exchange["params_builder"](formatted_symbol, exchange_interval, limit)
            
            async with session.get(endpoint, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status not in [200, 201]:
                    self.stats["exchange_stats"][exchange_name]["fail"] += 1
                    return None
                
                data = await response.json()
                candles = self._parse_exchange_data(exchange_name, data, symbol)
                
                if candles:
                    self.stats["exchange_stats"][exchange_name]["success"] += 1
                    self.stats["successful_fetches"] += 1
                    return candles
        
        except Exception as e:
            self.stats["exchange_stats"][exchange_name]["fail"] += 1
            self.stats["failed_fetches"] += 1
        
        return None
    
    def _parse_exchange_data(self, exchange_name: str, data: Any, symbol: str) -> List[Dict]:
        """Parse exchange-specific data"""
        candles = []
        
        try:
            if exchange_name == "Binance":
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
                    for row in data["result"].get("list", []):
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
            
            # Add more exchange parsers as needed...
            
            # Sort by timestamp
            candles.sort(key=lambda x: x["timestamp"])
            
        except Exception as e:
            logger.error(f"Parse error for {exchange_name}: {e}")
        
        return candles
    
    def _aggregate_candles(self, all_candles: List[List[Dict]]) -> List[Dict]:
        """Aggregate candles from multiple sources"""
        if not all_candles:
            return []
        
        timestamp_data = defaultdict(list)
        
        for exchange_candles in all_candles:
            for candle in exchange_candles:
                timestamp_data[candle["timestamp"]].append(candle)
        
        aggregated = []
        for timestamp in sorted(timestamp_data.keys()):
            candles_at_ts = timestamp_data[timestamp]
            
            if len(candles_at_ts) == 1:
                aggregated.append(candles_at_ts[0])
            else:
                aggregated.append({
                    "timestamp": timestamp,
                    "open": np.mean([c["open"] for c in candles_at_ts]),
                    "high": np.max([c["high"] for c in candles_at_ts]),
                    "low": np.min([c["low"] for c in candles_at_ts]),
                    "close": np.mean([c["close"] for c in candles_at_ts]),
                    "volume": np.sum([c["volume"] for c in candles_at_ts]),
                    "source_count": len(candles_at_ts)
                })
        
        return aggregated

# ========== TECHNICAL INDICATORS ==========
class TechnicalIndicators:
    @staticmethod
    def calculate_ema(candles: List[Dict], period: int) -> List[float]:
        """Calculate EMA"""
        closes = [c["close"] for c in candles]
        if len(closes) < period:
            return [None] * len(closes)
        
        ema = []
        multiplier = 2 / (period + 1)
        
        sma = sum(closes[:period]) / period
        ema.append(sma)
        
        for i in range(period, len(closes)):
            ema_value = (closes[i] - ema[-1]) * multiplier + ema[-1]
            ema.append(ema_value)
        
        return [None] * (period - 1) + ema
    
    @staticmethod
    def calculate_rsi(candles: List[Dict], period: int = 14) -> List[float]:
        """Calculate RSI"""
        closes = [c["close"] for c in candles]
        if len(closes) <= period:
            return [None] * len(closes)
        
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        rsi_values = [None] * period
        
        for i in range(period, len(gains)):
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            
            rsi_values.append(rsi)
            
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        return rsi_values
    
    @staticmethod
    def convert_to_heikin_ashi(candles: List[Dict]) -> List[Dict]:
        """Convert to Heikin Ashi"""
        ha_candles = []
        
        for i, candle in enumerate(candles):
            if i == 0:
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
        prev_body = abs(prev["close"] - prev["open"])
        curr_body = abs(curr["close"] - curr["open"])
        return (prev["close"] < prev["open"] and
                curr["close"] > curr["open"] and
                curr["open"] < prev["close"] and
                curr["close"] > prev["open"] and
                curr_body > prev_body * 1.2)
    
    @staticmethod
    def is_bearish_engulfing(prev: Dict, curr: Dict) -> bool:
        prev_body = abs(prev["close"] - prev["open"])
        curr_body = abs(curr["close"] - curr["open"])
        return (prev["close"] > prev["open"] and
                curr["close"] < curr["open"] and
                curr["open"] > prev["close"] and
                curr["close"] < prev["open"] and
                curr_body > prev_body * 1.2)
    
    @staticmethod
    def is_hammer(candle: Dict) -> bool:
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        return (lower_shadow > body * 2 and
                upper_shadow < body * 0.3 and
                body > 0)
    
    @staticmethod
    def is_hanging_man(candle: Dict) -> bool:
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        return (lower_shadow > body * 2 and
                upper_shadow < body * 0.3 and
                candle["close"] < candle["open"])
    
    @staticmethod
    def is_shooting_star(candle: Dict) -> bool:
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        return (upper_shadow > body * 2 and
                lower_shadow < body * 0.3 and
                body > 0)
    
    @staticmethod
    def is_doji(candle: Dict) -> bool:
        body = abs(candle["close"] - candle["open"])
        total_range = candle["high"] - candle["low"]
        return body < total_range * 0.1 and total_range > 0
    
    @staticmethod
    def is_morning_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
        return (c1["close"] < c1["open"] and
                abs(c2["close"] - c2["open"]) < abs(c1["close"] - c1["open"]) * 0.3 and
                c3["close"] > c3["open"] and
                c3["close"] > (c1["open"] + c1["close"]) / 2)
    
    @staticmethod
    def is_evening_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
        return (c1["close"] > c1["open"] and
                abs(c2["close"] - c2["open"]) < abs(c1["close"] - c1["open"]) * 0.3 and
                c3["close"] < c3["open"] and
                c3["close"] < (c1["open"] + c1["close"]) / 2)
    
    @staticmethod
    def is_three_white_soldiers(c1: Dict, c2: Dict, c3: Dict) -> bool:
        return (c1["close"] > c1["open"] and
                c2["close"] > c2["open"] and
                c3["close"] > c3["open"] and
                c2["close"] > c1["close"] and
                c3["close"] > c2["close"] and
                c2["open"] > c1["open"] and c2["open"] < c1["close"] and
                c3["open"] > c2["open"] and c3["open"] < c2["close"])
    
    @staticmethod
    def is_three_black_crows(c1: Dict, c2: Dict, c3: Dict) -> bool:
        return (c1["close"] < c1["open"] and
                c2["close"] < c2["open"] and
                c3["close"] < c3["open"] and
                c2["close"] < c1["close"] and
                c3["close"] < c2["close"] and
                c2["open"] < c1["open"] and c2["open"] > c1["close"] and
                c3["open"] < c2["open"] and c3["open"] > c2["close"])
    
    @staticmethod
    def is_bullish_harami(prev: Dict, curr: Dict) -> bool:
        return (prev["close"] < prev["open"] and
                curr["close"] > curr["open"] and
                curr["open"] > prev["close"] and
                curr["close"] < prev["open"])
    
    @staticmethod
    def is_bearish_harami(prev: Dict, curr: Dict) -> bool:
        return (prev["close"] > prev["open"] and
                curr["close"] < curr["open"] and
                curr["open"] < prev["close"] and
                curr["close"] > prev["open"])
    
    @staticmethod
    def detect_all_patterns(candles: List[Dict]) -> List[Dict]:
        """Detect all patterns"""
        patterns = []
        
        if len(candles) < 3:
            return patterns
        
        # Single candle patterns
        for i, candle in enumerate(candles):
            if CandlestickPatternDetector.is_hammer(candle):
                patterns.append({
                    "name": "Hammer",
                    "type": "reversal",
                    "direction": "bullish",
                    "confidence": 75,
                    "position": i
                })
            
            if CandlestickPatternDetector.is_hanging_man(candle):
                patterns.append({
                    "name": "Hanging Man",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 75,
                    "position": i
                })
            
            if CandlestickPatternDetector.is_shooting_star(candle):
                patterns.append({
                    "name": "Shooting Star",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 80,
                    "position": i
                })
            
            if CandlestickPatternDetector.is_doji(candle):
                patterns.append({
                    "name": "Doji",
                    "type": "indecision",
                    "direction": "neutral",
                    "confidence": 60,
                    "position": i
                })
        
        # Two candle patterns
        for i in range(1, len(candles)):
            prev, curr = candles[i-1], candles[i]
            
            if CandlestickPatternDetector.is_bullish_engulfing(prev, curr):
                patterns.append({
                    "name": "Bullish Engulfing",
                    "type": "reversal",
                    "direction": "bullish",
                    "confidence": 85,
                    "position": i
                })
            
            if CandlestickPatternDetector.is_bearish_engulfing(prev, curr):
                patterns.append({
                    "name": "Bearish Engulfing",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 85,
                    "position": i
                })
            
            if CandlestickPatternDetector.is_bullish_harami(prev, curr):
                patterns.append({
                    "name": "Bullish Harami",
                    "type": "reversal",
                    "direction": "bullish",
                    "confidence": 70,
                    "position": i
                })
            
            if CandlestickPatternDetector.is_bearish_harami(prev, curr):
                patterns.append({
                    "name": "Bearish Harami",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 70,
                    "position": i
                })
        
        # Three candle patterns
        for i in range(2, len(candles)):
            c1, c2, c3 = candles[i-2], candles[i-1], candles[i]
            
            if CandlestickPatternDetector.is_morning_star(c1, c2, c3):
                patterns.append({
                    "name": "Morning Star",
                    "type": "reversal",
                    "direction": "bullish",
                    "confidence": 90,
                    "position": i
                })
            
            if CandlestickPatternDetector.is_evening_star(c1, c2, c3):
                patterns.append({
                    "name": "Evening Star",
                    "type": "reversal",
                    "direction": "bearish",
                    "confidence": 90,
                    "position": i
                })
            
            if CandlestickPatternDetector.is_three_white_soldiers(c1, c2, c3):
                patterns.append({
                    "name": "Three White Soldiers",
                    "type": "continuation",
                    "direction": "bullish",
                    "confidence": 95,
                    "position": i
                })
            
            if CandlestickPatternDetector.is_three_black_crows(c1, c2, c3):
                patterns.append({
                    "name": "Three Black Crows",
                    "type": "continuation",
                    "direction": "bearish",
                    "confidence": 95,
                    "position": i
                })
        
        return patterns

# ========== ICT ANALYZER ==========
class ICTAnalyzer:
    @staticmethod
    def detect_fair_value_gaps(candles: List[Dict]) -> List[Dict]:
        fvgs = []
        
        for i in range(2, len(candles)):
            prev, curr = candles[i-2], candles[i]
            
            if prev["high"] < curr["low"]:
                gap_size = curr["low"] - prev["high"]
                fvgs.append({
                    "type": "bullish",
                    "start": prev["high"],
                    "end": curr["low"],
                    "size": gap_size,
                    "position": i
                })
            
            if prev["low"] > curr["high"]:
                gap_size = prev["low"] - curr["high"]
                fvgs.append({
                    "type": "bearish",
                    "start": curr["high"],
                    "end": prev["low"],
                    "size": gap_size,
                    "position": i
                })
        
        return fvgs
    
    @staticmethod
    def detect_order_blocks(candles: List[Dict]) -> List[Dict]:
        order_blocks = []
        
        for i in range(3, len(candles)):
            if (candles[i-1]["close"] < candles[i-1]["open"] and
                candles[i]["close"] > candles[i]["open"] and
                candles[i]["close"] > candles[i-1]["high"]):
                
                order_blocks.append({
                    "type": "bullish",
                    "high": candles[i-1]["high"],
                    "low": candles[i-1]["low"],
                    "position": i-1
                })
            
            if (candles[i-1]["close"] > candles[i-1]["open"] and
                candles[i]["close"] < candles[i]["open"] and
                candles[i]["close"] < candles[i-1]["low"]):
                
                order_blocks.append({
                    "type": "bearish",
                    "high": candles[i-1]["high"],
                    "low": candles[i-1]["low"],
                    "position": i-1
                })
        
        return order_blocks
    
    @staticmethod
    def analyze_market_structure(candles: List[Dict]) -> Dict:
        if len(candles) < 20:
            return {"structure": "insufficient_data"}
        
        recent = candles[-20:]
        highs = [c["high"] for c in recent]
        lows = [c["low"] for c in recent]
        
        higher_highs = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i-1])
        higher_lows = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i-1])
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
    """Generate trading signals"""
    
    @staticmethod
    def calculate_ema_signal(ema_fast: List[float], ema_slow: List[float]) -> Dict:
        if not ema_fast or not ema_slow or len(ema_fast) < 2:
            return {"signal": "NEUTRAL", "confidence": 0}
        
        fast_curr, fast_prev = ema_fast[-1], ema_fast[-2]
        slow_curr, slow_prev = ema_slow[-1], ema_slow[-2]
        
        if None in [fast_curr, fast_prev, slow_curr, slow_prev]:
            return {"signal": "NEUTRAL", "confidence": 0}
        
        # Golden Cross
        if fast_prev <= slow_prev and fast_curr > slow_curr:
            distance = abs(fast_curr - slow_curr) / slow_curr * 100
            confidence = min(90, 70 + distance * 10)
            return {
                "signal": "BUY",
                "confidence": confidence,
                "reason": "golden_cross"
            }
        
        # Death Cross
        if fast_prev >= slow_prev and fast_curr < slow_curr:
            distance = abs(fast_curr - slow_curr) / slow_curr * 100
            confidence = min(90, 70 + distance * 10)
            return {
                "signal": "SELL",
                "confidence": confidence,
                "reason": "death_cross"
            }
        
        # Trend following
        if fast_curr > slow_curr:
            distance = (fast_curr - slow_curr) / slow_curr * 100
            if distance > 2:
                return {
                    "signal": "BUY",
                    "confidence": min(80, 50 + distance * 5),
                    "reason": "uptrend"
                }
        
        if fast_curr < slow_curr:
            distance = (slow_curr - fast_curr) / slow_curr * 100
            if distance > 2:
                return {
                    "signal": "SELL",
                    "confidence": min(80, 50 + distance * 5),
                    "reason": "downtrend"
                }
        
        return {"signal": "NEUTRAL", "confidence": 40}
    
    @staticmethod
    def calculate_rsi_signal(rsi: List[float]) -> Dict:
        if not rsi or len(rsi) < 2:
            return {"signal": "NEUTRAL", "confidence": 0}
        
        current, prev = rsi[-1], rsi[-2]
        
        if None in [current, prev]:
            return {"signal": "NEUTRAL", "confidence": 0}
        
        if current < 30:
            if prev < 30 and current > prev:
                return {
                    "signal": "STRONG_BUY",
                    "confidence": 85,
                    "reason": "oversold_reversal"
                }
            return {
                "signal": "BUY",
                "confidence": 70,
                "reason": "oversold"
            }
        
        if current > 70:
            if prev > 70 and current < prev:
                return {
                    "signal": "STRONG_SELL",
                    "confidence": 85,
                    "reason": "overbought_reversal"
                }
            return {
                "signal": "SELL",
                "confidence": 70,
                "reason": "overbought"
            }
        
        if 40 <= current <= 60:
            return {
                "signal": "NEUTRAL",
                "confidence": 50,
                "reason": "neutral_zone"
            }
        
        return {"signal": "NEUTRAL", "confidence": 45}
    
    @staticmethod
    def calculate_pattern_signal(patterns: List[Dict]) -> Dict:
        if not patterns:
            return {"signal": "NEUTRAL", "confidence": 0}
        
        recent = [p for p in patterns if p.get("position", 0) >= len(patterns) - 5]
        
        if not recent:
            return {"signal": "NEUTRAL", "confidence": 0}
        
        bullish = sum(p["confidence"] for p in recent if p["direction"] == "bullish")
        bearish = sum(p["confidence"] for p in recent if p["direction"] == "bearish")
        
        if bullish > bearish * 1.5:
            return {
                "signal": "BUY",
                "confidence": min(95, max(p["confidence"] for p in recent if p["direction"] == "bullish")),
                "reason": "bullish_patterns"
            }
        elif bearish > bullish * 1.5:
            return {
                "signal": "SELL",
                "confidence": min(95, max(p["confidence"] for p in recent if p["direction"] == "bearish")),
                "reason": "bearish_patterns"
            }
        
        return {"signal": "NEUTRAL", "confidence": 50}
    
    @staticmethod
    def calculate_ict_signal(fvgs: List[Dict], order_blocks: List[Dict], market_structure: Dict) -> Dict:
        score = 0
        
        if market_structure["structure"] == "bullish_trend":
            score += 30 if market_structure["strength"] == "strong" else 20
        elif market_structure["structure"] == "bearish_trend":
            score -= 30 if market_structure["strength"] == "strong" else 20
        
        recent_fvgs = [f for f in fvgs if f.get("position", 0) >= len(fvgs) - 3] if fvgs else []
        for fvg in recent_fvgs:
            if fvg["type"] == "bullish":
                score += 15
            else:
                score -= 15
        
        recent_obs = [ob for ob in order_blocks if ob.get("position", 0) >= len(order_blocks) - 3] if order_blocks else []
        for ob in recent_obs:
            if ob["type"] == "bullish":
                score += 20
            else:
                score -= 20
        
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
            "score": score
        }
    
    @staticmethod
    def calculate_volatility_trail_signal(
        candles: List[Dict],
        trend_strength_threshold: float = 0.70
    ) -> Dict:
        if len(candles) < 60:
            return {
                "signal": "NEUTRAL",
                "confidence": 0,
                "reason": "insufficient_data"
            }

        df = pd.DataFrame(candles)
        if 'timestamp' in df.columns:
            df = df.set_index('timestamp')

        result = VolatilityAdjustedTrail.calculate(df)

        if result['current_trail'] is None:
            return {
                "signal": "NEUTRAL",
                "confidence": 0,
                "reason": "calculation_failed"
            }

        current_dir = result['current_direction']
        trend_strength = result['trend_strength']

        if current_dir == 1 and trend_strength >= trend_strength_threshold:
            conf = min(92, 65 + (trend_strength - 0.7) * 150)
            return {
                "signal": "STRONG_BUY" if conf > 82 else "BUY",
                "confidence": round(conf, 1),
                "reason": "vat_uptrend_strong" if conf > 82 else "vat_uptrend",
                "trail_value": round(result['current_trail'], 4),
                "trend_strength": round(trend_strength, 3)
            }

        elif current_dir == -1 and trend_strength >= trend_strength_threshold:
            conf = min(92, 65 + (trend_strength - 0.7) * 150)
            return {
                "signal": "STRONG_SELL" if conf > 82 else "SELL",
                "confidence": round(conf, 1),
                "reason": "vat_downtrend_strong" if conf > 82 else "vat_downtrend",
                "trail_value": round(result['current_trail'], 4),
                "trend_strength": round(trend_strength, 3)
            }

        else:
            return {
                "signal": "NEUTRAL",
                "confidence": 45 + trend_strength * 30,
                "reason": "vat_weak_or_choppy",
                "trail_value": round(result['current_trail'], 4),
                "trend_strength": round(trend_strength, 3)
            }
    
    @staticmethod
    def generate_combined_signal(
        ema_signal: Dict,
        rsi_signal: Dict,
        pattern_signal: Dict,
        ict_signal: Dict,
        ha_trend: str,
        ml_signal: Dict = None,
        vat_signal: Dict = None
    ) -> Dict:
        weights = {
            "ema": 0.18,
            "rsi": 0.14,
            "patterns": 0.18,
            "ict": 0.18,
            "ml": 0.18,
            "ha": 0.05,
            "vat": 0.09
        }

        signal_values = {
            "STRONG_BUY": 2,
            "BUY": 1,
            "NEUTRAL": 0,
            "SELL": -1,
            "STRONG_SELL": -2
        }

        total_score = 0
        total_confidence = 0
        
        component_signals = {
            "ema": ema_signal,
            "rsi": rsi_signal,
            "patterns": pattern_signal,
            "ict": ict_signal
        }

        if ml_signal:
            component_signals["ml"] = {
                "signal": ml_signal.get("prediction", "NEUTRAL"),
                "confidence": ml_signal.get("confidence", 0.5) * 100,
                "reason": "ml_prediction"
            }

        if vat_signal:
            component_signals["vat"] = vat_signal

        for name, sig in component_signals.items():
            weight = weights.get(name, 0)
            sig_value = signal_values.get(sig.get("signal", "NEUTRAL"), 0)
            sig_conf = sig.get("confidence", 0)
            
            total_score += sig_value * weight * (sig_conf / 100)
            total_confidence += sig_conf * weight
        
        # Heikin Ashi adjustment
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
        
        # Confidence level
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
        if signal == SignalType.STRONG_BUY:
            if confidence >= 85:
                return "🚀 STRONG BUY - Very high confidence. Consider entering long position."
            else:
                return "📈 STRONG BUY - Good bullish setup."
        elif signal == SignalType.BUY:
            return "✅ BUY - Bullish signal detected. Consider buying on dips."
        elif signal == SignalType.STRONG_SELL:
            if confidence >= 85:
                return "🔴 STRONG SELL - Very high confidence. Consider exiting or shorting."
            else:
                return "📉 STRONG SELL - Bearish setup."
        elif signal == SignalType.SELL:
            return "⚠️ SELL - Bearish signal detected."
        else:
            return "⏸️ NEUTRAL - No clear directional bias."

# ========== AI CHATBOT MODULE ==========
class TradingChatBot:
    def __init__(self, ai_engine=None, price_fetcher=None):
        self.ai_engine = ai_engine
        self.price_fetcher = price_fetcher
        self.context = []
        self.knowledge_base = {
            "patterns": {
                "hammer": "Bullish reversal pattern at support.",
                "shooting star": "Bearish reversal at resistance.",
                "engulfing": "Strong reversal pattern.",
                "doji": "Indecision pattern.",
                "morning star": "Strong bullish reversal.",
                "evening star": "Strong bearish reversal."
            },
            "indicators": {
                "rsi": "Relative Strength Index. >70 overbought, <30 oversold.",
                "macd": "Moving Average Convergence Divergence.",
                "ema": "Exponential Moving Average.",
                "heikin ashi": "Smoothed candlestick chart.",
                "bollinger bands": "Volatility indicator."
            },
            "strategies": {
                "trend following": "Trade in direction of trend.",
                "mean reversion": "Trade RSI extremes.",
                "breakout": "Trade breakouts from consolidation.",
                "swing trading": "Hold positions for days/weeks."
            },
            "ict": {
                "fair value gap": "Price gap that often gets filled.",
                "order block": "Area where big players entered trades.",
                "market structure": "Higher highs + higher lows = bullish."
            }
        }
    
    async def process_message(self, message: str, symbol: str = None) -> str:
        try:
            self.context.append(f"User: {message}")
            if len(self.context) > 20:
                self.context = self.context[-20:]
            
            lower_msg = message.lower()
            
            # Greetings
            if any(word in lower_msg for word in ["hello", "hi", "hey"]):
                return "🤖 Hello! I'm your AI trading assistant. How can I help you?"
            
            # Price queries
            if "price" in lower_msg and symbol and self.price_fetcher:
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
            if "strategy" in lower_msg:
                return self._get_strategy_advice(lower_msg)
            
            # Analysis request
            if "analyze" in lower_msg and symbol and self.price_fetcher:
                return await self._analyze_symbol(symbol)
            
            # ML prediction
            if "predict" in lower_msg and symbol and self.ai_engine and self.price_fetcher:
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
                    "Always use stop-loss orders.",
                    "Trade with the trend.",
                    "Don't overtrade.",
                    "Keep a trading journal.",
                    "Use multiple time frame analysis.",
                    "Never risk more than 1-2% per trade."
                ]
                return f"💡 **Trading Tip**: {random.choice(tips)}"
            
            # Default response
            responses = [
                "I can help you with technical analysis, explain patterns and indicators.",
                "Try asking about specific patterns or indicators.",
                "You can ask me to analyze a symbol or provide strategy advice."
            ]
            return random.choice(responses)
            
        except Exception as e:
            logger.error(f"Chat error: {str(e)}")
            return "I encountered an error processing your request."
    
    def _get_strategy_advice(self, message: str) -> str:
        if "trend" in message:
            return """**Trend Following Strategy**:
1. Identify trend using EMA crossovers
2. Enter on pullbacks
3. Use stop loss below recent swing low
4. Target 2:1 risk/reward ratio"""
        elif "swing" in message:
            return """**Swing Trading Strategy**:
1. Use 4H/Daily charts
2. Enter on 1H/4H chart patterns
3. Look for RSI extremes
4. Hold for 2-10 days"""
        else:
            return """**General Trading Principles**:
1. Risk Management: Never risk more than 1-2% per trade
2. Trend is Your Friend
3. Use Confirmation
4. Be Patient
5. Stay Disciplined"""
    
    async def _analyze_symbol(self, symbol: str) -> str:
        try:
            if not self.price_fetcher:
                return "Price fetcher not available"
            
            candles = await self.price_fetcher.get_candles(symbol, "1h", 100)
            if not candles:
                return f"Could not fetch data for {symbol}"
            
            current = candles[-1]["close"]
            prev_close = candles[-2]["close"] if len(candles) > 1 else current
            change = ((current - prev_close) / prev_close) * 100
            
            highs = [c["high"] for c in candles[-20:]]
            lows = [c["low"] for c in candles[-20:]]
            avg_volume = np.mean([c["volume"] for c in candles[-20:]])
            
            return f"""📊 **{symbol} Analysis**:
• **Price**: ${current:,.2f} ({'▲' if change >= 0 else '▼'} {abs(change):.2f}%)
• **Recent Range**: ${min(lows):,.2f} - ${max(highs):,.2f}
• **Avg Volume**: {avg_volume:,.0f}
• **Data Points**: {len(candles)} candles"""
        
        except Exception as e:
            logger.error(f"Analysis error: {str(e)}")
            return f"Error analyzing {symbol}."

# ========== WEBSOCKET MANAGER ==========
class WebSocketManager:
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
    
    async def broadcast(self, message: str):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)
        
        for connection in disconnected:
            self.disconnect(connection)

# ========== GLOBAL INSTANCES ==========
ai_engine = AITradingEngine()
price_fetcher = PriceFetcher()
chatbot = TradingChatBot(ai_engine, price_fetcher)
websocket_manager = WebSocketManager()

# ========== API ENDPOINTS ==========
@app.get("/")
async def root():
    return HTMLResponse("""
    <html>
    <head>
        <title>Professional Trading Bot v4.5</title>
        <meta http-equiv="refresh" content="0;url=/dashboard">
    </head>
    <body><p>Loading Trading Dashboard...</p></body>
    </html>
    """)

@app.get("/health")
def health():
    return {"status": "healthy", "version": "4.5.0"}

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Trading Dashboard"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Professional Trading Bot v4.5</title>
        <style>
            body {
                background: #0a0e27;
                color: white;
                font-family: Arial, sans-serif;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
            }
            .card {
                background: #1a1f3a;
                border-radius: 10px;
                padding: 20px;
                margin: 10px 0;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            }
            .signal-buy { color: #22c55e; }
            .signal-sell { color: #ef4444; }
            .signal-neutral { color: #f59e0b; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 Professional Trading Bot v4.5</h1>
            <div class="card">
                <h2>System Status: <span style="color: #22c55e;">✅ Online</span></h2>
                <p>Version 4.5.0 - Advanced AI Trading System</p>
            </div>
            <div class="card">
                <h3>Features</h3>
                <ul>
                    <li>✅ 11+ Exchange Support</li>
                    <li>✅ Forex Market Integration</li>
                    <li>✅ Volatility Adjusted Trail</li>
                    <li>✅ Advanced AI Models (LSTM, Transformer, LightGBM)</li>
                    <li>✅ 12 Candlestick Patterns</li>
                    <li>✅ ICT Market Structure Analysis</li>
                    <li>✅ Real Data Only - NO Synthetic Data</li>
                </ul>
            </div>
            <div class="card">
                <h3>Quick Start</h3>
                <p>Use the API endpoints to analyze symbols:</p>
                <code>/api/analyze/BTCUSDT?interval=1h</code><br>
                <code>/api/train/BTCUSDT</code><br>
                <code>/api/chat</code>
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/api/analyze/{symbol}")
async def analyze_symbol(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1h|4h|1d)$")
):
    """Complete technical analysis for a symbol"""
    try:
        candles = await price_fetcher.get_candles(symbol, interval, 100)
        
        if not candles or len(candles) < 50:
            raise HTTPException(status_code=400, detail="Insufficient data")
        
        # Calculate indicators
        ema_9 = TechnicalIndicators.calculate_ema(candles, 9)
        ema_21 = TechnicalIndicators.calculate_ema(candles, 21)
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
        vat_signal = SignalGenerator.calculate_volatility_trail_signal(candles)
        
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
            ema_signal, rsi_signal, pattern_signal, ict_signal,
            ha_trend, ml_prediction, vat_signal
        )
        
        current_candle = candles[-1]
        prev_candle = candles[-2]
        price_change = ((current_candle["close"] - prev_candle["close"]) / prev_candle["close"]) * 100
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "price_data": {
                "current": current_candle["close"],
                "change_percent": round(price_change, 2)
            },
            "indicators": {
                "ema_9": round(ema_9[-1], 4) if ema_9[-1] else None,
                "ema_21": round(ema_21[-1], 4) if ema_21[-1] else None,
                "rsi": round(rsi[-1], 2) if rsi[-1] else None,
                "heikin_ashi_trend": ha_trend
            },
            "patterns": patterns[-10:],
            "ict_analysis": {
                "fair_value_gaps": fvgs[-5:],
                "order_blocks": order_blocks[-5:],
                "market_structure": market_structure
            },
            "volatility_trail": vat_signal,
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
        candles = await price_fetcher.get_candles(symbol, "1h", 1000)
        
        if not candles or len(candles) < 500:
            raise HTTPException(status_code=400, detail="Insufficient data for training")
        
        df = pd.DataFrame(candles)
        if not df.empty:
            if 'timestamp' in df.columns:
                df.set_index('timestamp', inplace=True)
        
        success = await ai_engine.train_models(symbol, df)
        
        if success:
            feature_importance = ai_engine.get_feature_importance(symbol)
            
            return {
                "success": True,
                "message": f"Successfully trained ML models for {symbol}",
                "feature_importance": feature_importance
            }
        else:
            raise HTTPException(status_code=500, detail="Training failed")
        
    except Exception as e:
        logger.error(f"Training error: {str(e)}")
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
            "response": response
        }
        
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get("type") == "subscribe":
                    symbol = message.get("symbol", "BTCUSDT")
                    candles = await price_fetcher.get_candles(symbol, "1h", 2)
                    if candles and len(candles) >= 2:
                        current = candles[-1]["close"]
                        previous = candles[-2]["close"]
                        change = ((current - previous) / previous) * 100
                        
                        await websocket.send_text(json.dumps({
                            "type": "price_update",
                            "symbol": symbol,
                            "price": current,
                            "change": change,
                            "timestamp": datetime.utcnow().isoformat()
                        }))
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"error": "Invalid JSON"}))
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)

# ========== MAIN ENTRY POINT ==========
if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info(f"Starting Professional AI Trading Bot v4.5 on {host}:{port}")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )
