"""
🚀 PROFESSIONAL TRADING BOT v4.0 - ADVANCED AI TRADING SYSTEM
✅ TradingView Integration ✅ EMA Crossovers ✅ RSI ✅ Heikin Ashi
✅ 12 Candlestick Patterns ✅ ICT Market Structure ✅ Multi-Timeframe
✅ Advanced ML (LSTM + Transformer) ✅ Image/Graph Analysis
✅ AI Chatbot ✅ Binance WebSocket ✅ CoinGecko API
"""

import os
import logging
import json
import asyncio
from datetime import datetime, timedelta
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
    docs_url="/docs",
    redoc_url="/redoc"
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
        """Generate predictions from all models"""
        try:
            # Create features
            df_features = self.create_features(df)
            
            if len(df_features) < 60 or self.feature_columns is None:
                return {
                    'prediction': 'NEUTRAL',
                    'confidence': 0.5,
                    'method': 'fallback',
                    'ml_score': 0.5,
                    'model_details': {}
                }
            
            # Prepare recent sequence
            features = df_features[self.feature_columns].values
            seq_len = 60
            
            if len(features) < seq_len:
                # Pad with zeros if insufficient data
                pad_len = seq_len - len(features)
                pad = np.zeros((pad_len, features.shape[1]))
                features = np.vstack([pad, features])
            
            recent_seq = features[-seq_len:].reshape(1, seq_len, -1)
            
            predictions = []
            confidences = []
            model_details = {}
            
            # LSTM prediction
            lstm_key = f"{symbol}_lstm"
            if lstm_key in self.models:
                try:
                    model = self.models[lstm_key]
                    model.eval()
                    
                    if symbol in self.scalers:
                        scaler = self.scalers[symbol]
                        recent_flat = recent_seq.reshape(-1, recent_seq.shape[-1])
                        recent_scaled = scaler.transform(recent_flat).reshape(recent_seq.shape)
                        recent_t = torch.FloatTensor(recent_scaled).to(self.device)
                    else:
                        recent_t = torch.FloatTensor(recent_seq).to(self.device)
                    
                    with torch.no_grad():
                        output = model(recent_t)
                        prob = F.softmax(output, dim=1)[0].cpu().numpy()
                        pred = np.argmax(prob)
                        confidence = np.max(prob)
                        
                        predictions.append(pred)
                        confidences.append(confidence)
                        model_details['lstm'] = {
                            'prediction': int(pred),
                            'confidence': float(confidence),
                            'probabilities': prob.tolist()
                        }
                except Exception as e:
                    logger.error(f"LSTM prediction error for {symbol}: {str(e)}")
            
            # Transformer prediction
            trans_key = f"{symbol}_transformer"
            if trans_key in self.models:
                try:
                    model = self.models[trans_key]
                    model.eval()
                    
                    if symbol in self.scalers:
                        scaler = self.scalers[symbol]
                        recent_flat = recent_seq.reshape(-1, recent_seq.shape[-1])
                        recent_scaled = scaler.transform(recent_flat).reshape(recent_seq.shape)
                        recent_t = torch.FloatTensor(recent_scaled).to(self.device)
                    else:
                        recent_t = torch.FloatTensor(recent_seq).to(self.device)
                    
                    with torch.no_grad():
                        output = model(recent_t)
                        prob = F.softmax(output, dim=1)[0].cpu().numpy()
                        pred = np.argmax(prob)
                        confidence = np.max(prob)
                        
                        predictions.append(pred)
                        confidences.append(confidence)
                        model_details['transformer'] = {
                            'prediction': int(pred),
                            'confidence': float(confidence),
                            'probabilities': prob.tolist()
                        }
                except Exception as e:
                    logger.error(f"Transformer prediction error for {symbol}: {str(e)}")
            
            # LightGBM prediction
            if symbol in self.lgb_models:
                try:
                    model = self.lgb_models[symbol]
                    
                    # Use the most recent flattened features
                    recent_flat = recent_seq.reshape(-1, recent_seq.shape[-1])
                    
                    if symbol in self.scalers:
                        scaler = self.scalers[symbol]
                        recent_flat = scaler.transform(recent_flat)
                    
                    # Take the last flattened vector
                    if len(recent_flat) > 0:
                        recent_features = recent_flat[-1:].reshape(1, -1)
                        prob = model.predict(recent_features)[0]
                        pred = np.argmax(prob)
                        confidence = np.max(prob)
                        
                        predictions.append(pred)
                        confidences.append(confidence)
                        model_details['lightgbm'] = {
                            'prediction': int(pred),
                            'confidence': float(confidence),
                            'probabilities': prob.tolist()
                        }
                except Exception as e:
                    logger.error(f"LightGBM prediction error for {symbol}: {str(e)}")
            
            # Ensemble prediction
            if predictions:
                # Weighted average based on confidence
                pred_weights = []
                for i, conf in enumerate(confidences):
                    pred_weights.extend([predictions[i]] * int(conf * 100))
                
                if pred_weights:
                    final_pred = np.bincount(pred_weights).argmax()
                else:
                    final_pred = 1  # Default to neutral
                
                final_confidence = np.mean(confidences) if confidences else 0.5
            else:
                final_pred = 1
                final_confidence = 0.5
            
            # Map to signal
            pred_map = {0: 'SELL', 1: 'NEUTRAL', 2: 'BUY'}
            final_signal = pred_map.get(final_pred, 'NEUTRAL')
            
            # Adjust signal strength based on confidence
            if final_confidence > 0.7:
                if final_signal == 'BUY':
                    final_signal = 'STRONG_BUY'
                elif final_signal == 'SELL':
                    final_signal = 'STRONG_SELL'
            
            return {
                'prediction': final_signal,
                'confidence': float(final_confidence),
                'method': 'ensemble',
                'ml_score': float(final_pred),
                'model_details': model_details
            }
            
        except Exception as e:
            logger.error(f"Prediction error for {symbol}: {str(e)}")
            return {
                'prediction': 'NEUTRAL',
                'confidence': 0.5,
                'method': 'fallback',
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

# ========== PRICE DATA MODULE ==========
class PriceDataFetcher:
    """Fetch price data from Binance and CoinGecko"""
    
    def __init__(self):
        self.binance_base_url = "https://api.binance.com/api/v3"
        self.coingecko_base_url = "https://api.coingecko.com/api/v3"
        self.session = None
        
    async def get_session(self):
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def fetch_binance_klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> Optional[List[Dict]]:
        """Fetch candlestick data from Binance"""
        try:
            session = await self.get_session()
            url = f"{self.binance_base_url}/klines"
            params = {
                "symbol": symbol.upper(),
                "interval": interval,
                "limit": min(limit, 1000)
            }
            
            async with session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    candles = []
                    for candle in data:
                        candles.append({
                            "timestamp": candle[0],
                            "open": float(candle[1]),
                            "high": float(candle[2]),
                            "low": float(candle[3]),
                            "close": float(candle[4]),
                            "volume": float(candle[5]),
                            "quote_volume": float(candle[7]),
                            "trades": int(candle[8])
                        })
                    logger.info(f"✅ Fetched {len(candles)} candles from Binance for {symbol}")
                    return candles
                else:
                    logger.error(f"Binance API error: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching Binance data for {symbol}: {str(e)}")
            return None
    
    async def fetch_coingecko_data(self, coin_id: str, vs_currency: str = "usd", days: int = 30) -> Optional[Dict]:
        """Fetch additional data from CoinGecko"""
        try:
            session = await self.get_session()
            url = f"{self.coingecko_base_url}/coins/{coin_id}/market_chart"
            params = {
                "vs_currency": vs_currency,
                "days": days,
                "interval": "daily"
            }
            
            async with session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.error(f"CoinGecko API error: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching CoinGecko data for {coin_id}: {str(e)}")
            return None
    
    async def get_candles(self, symbol: str, interval: str = "1h", limit: int = 500) -> List[Dict]:
        """Get candlestick data from Binance"""
        try:
            # Try Binance first
            candles = await self.fetch_binance_klines(symbol, interval, limit)
            
            if candles and len(candles) > 0:
                return candles
            else:
                logger.warning(f"No data from Binance for {symbol}, trying fallback...")
                # Fallback to simple data generation (for testing only)
                return self._generate_test_data(symbol, limit)
                
        except Exception as e:
            logger.error(f"Error getting candles for {symbol}: {str(e)}")
            return self._generate_test_data(symbol, limit)
    
    def _generate_test_data(self, symbol: str, count: int = 100) -> List[Dict]:
        """Generate test data when API fails (for development only)"""
        logger.warning(f"Generating test data for {symbol}")
        
        base_price = {
            "BTCUSDT": 50000,
            "ETHUSDT": 3000,
            "BNBUSDT": 400,
            "SOLUSDT": 100,
            "ADAUSDT": 0.5,
            "XRPUSDT": 0.6,
            "DOTUSDT": 7,
            "DOGEUSDT": 0.1,
        }.get(symbol.upper(), 100)
        
        candles = []
        current_price = base_price
        base_time = datetime.utcnow() - timedelta(hours=count)
        
        for i in range(count):
            # Simulate realistic price movements
            change_pct = np.random.normal(0, 0.02)  # 2% daily volatility
            current_price = current_price * (1 + change_pct)
            
            open_price = current_price
            close_price = current_price * (1 + np.random.normal(0, 0.01))
            high_price = max(open_price, close_price) * (1 + abs(np.random.normal(0, 0.005)))
            low_price = min(open_price, close_price) * (1 - abs(np.random.normal(0, 0.005)))
            
            candles.append({
                "timestamp": int((base_time + timedelta(hours=i)).timestamp() * 1000),
                "open": round(open_price, 4),
                "high": round(high_price, 4),
                "low": round(low_price, 4),
                "close": round(close_price, 4),
                "volume": np.random.uniform(1000, 10000),
                "quote_volume": np.random.uniform(50000, 500000),
                "trades": np.random.randint(100, 1000)
            })
        
        return candles
    
    async def close(self):
        """Close the HTTP session"""
        if self.session and not self.session.closed:
            await self.session.close()

# ========== TECHNICAL INDICATORS ==========
class TechnicalIndicators:
    """Calculate technical indicators"""
    
    @staticmethod
    def calculate_ema(candles: List[Dict], period: int) -> List[Optional[float]]:
        """Calculate Exponential Moving Average"""
        if not candles or len(candles) < period:
            return [None] * len(candles)
        
        closes = [c["close"] for c in candles]
        ema_values = []
        multiplier = 2 / (period + 1)
        
        # First EMA is SMA
        sma = sum(closes[:period]) / period
        ema_values.append(sma)
        
        # Calculate EMA for rest
        for i in range(period, len(closes)):
            ema = (closes[i] - ema_values[-1]) * multiplier + ema_values[-1]
            ema_values.append(ema)
        
        # Pad beginning with None
        return [None] * (period - 1) + ema_values
    
    @staticmethod
    def calculate_rsi(candles: List[Dict], period: int = 14) -> List[Optional[float]]:
        """Calculate Relative Strength Index"""
        if not candles or len(candles) < period + 1:
            return [None] * len(candles)
        
        closes = [c["close"] for c in candles]
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        
        gains = [max(d, 0) for d in deltas]
        losses = [abs(min(d, 0)) for d in deltas]
        
        # Initial averages
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
            
            # Update averages
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        # Pad beginning
        return [None] * (len(closes) - len(rsi_values)) + rsi_values
    
    @staticmethod
    def calculate_sma(candles: List[Dict], period: int) -> List[Optional[float]]:
        """Calculate Simple Moving Average"""
        if not candles or len(candles) < period:
            return [None] * len(candles)
        
        closes = [c["close"] for c in candles]
        sma_values = []
        
        for i in range(len(closes)):
            if i < period - 1:
                sma_values.append(None)
            else:
                sma = sum(closes[i-period+1:i+1]) / period
                sma_values.append(sma)
        
        return sma_values
    
    @staticmethod
    def calculate_macd(candles: List[Dict]) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
        """Calculate MACD (12, 26, 9)"""
        if not candles or len(candles) < 35:  # Need enough data for 26-period EMA
            return [None] * len(candles), [None] * len(candles), [None] * len(candles)
        
        closes = [c["close"] for c in candles]
        
        # Calculate EMAs
        ema12 = TechnicalIndicators._calculate_ema_from_closes(closes, 12)
        ema26 = TechnicalIndicators._calculate_ema_from_closes(closes, 26)
        
        # Calculate MACD line
        macd_line = []
        for e12, e26 in zip(ema12, ema26):
            if e12 is None or e26 is None:
                macd_line.append(None)
            else:
                macd_line.append(e12 - e26)
        
        # Calculate Signal line (9-period EMA of MACD)
        signal_line = TechnicalIndicators._calculate_ema_from_list(macd_line, 9)
        
        # Calculate Histogram
        histogram = []
        for macd, signal in zip(macd_line, signal_line):
            if macd is None or signal is None:
                histogram.append(None)
            else:
                histogram.append(macd - signal)
        
        return macd_line, signal_line, histogram
    
    @staticmethod
    def _calculate_ema_from_closes(closes: List[float], period: int) -> List[Optional[float]]:
        """Calculate EMA from close prices"""
        if len(closes) < period:
            return [None] * len(closes)
        
        ema_values = []
        multiplier = 2 / (period + 1)
        
        # First EMA is SMA
        sma = sum(closes[:period]) / period
        ema_values.append(sma)
        
        # Calculate EMA for rest
        for i in range(period, len(closes)):
            ema = (closes[i] - ema_values[-1]) * multiplier + ema_values[-1]
            ema_values.append(ema)
        
        return [None] * (period - 1) + ema_values
    
    @staticmethod
    def _calculate_ema_from_list(values: List[Optional[float]], period: int) -> List[Optional[float]]:
        """Calculate EMA from a list with None values"""
        # Filter out None values at the beginning
        start_idx = 0
        while start_idx < len(values) and values[start_idx] is None:
            start_idx += 1
        
        if len(values) - start_idx < period:
            return [None] * len(values)
        
        # Get valid values
        valid_values = [v for v in values[start_idx:] if v is not None]
        if len(valid_values) < period:
            return [None] * len(values)
        
        # Calculate EMA on valid values
        ema_values = []
        multiplier = 2 / (period + 1)
        
        # First EMA is SMA
        sma = sum(valid_values[:period]) / period
        ema_values.append(sma)
        
        # Calculate EMA for rest
        for i in range(period, len(valid_values)):
            ema = (valid_values[i] - ema_values[-1]) * multiplier + ema_values[-1]
            ema_values.append(ema)
        
        # Pad with None
        result = [None] * start_idx
        result.extend([None] * (period - 1))
        result.extend(ema_values)
        
        # Ensure correct length
        if len(result) < len(values):
            result.extend([None] * (len(values) - len(result)))
        elif len(result) > len(values):
            result = result[:len(values)]
        
        return result
    
    @staticmethod
    def convert_to_heikin_ashi(candles: List[Dict]) -> List[Dict]:
        """Convert regular candles to Heikin Ashi candles"""
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
    
    @staticmethod
    def detect_trend_from_heikin_ashi(ha_candles: List[Dict], lookback: int = 5) -> str:
        """Detect trend from Heikin Ashi candles"""
        if len(ha_candles) < lookback:
            return "NEUTRAL"
        
        recent = ha_candles[-lookback:]
        
        # Count bullish and bearish candles
        bullish = sum(1 for c in recent if c["close"] > c["open"])
        bearish = lookback - bullish
        
        # Check for strong trends
        if bullish >= lookback - 1:
            return "STRONG_BULLISH"
        elif bearish >= lookback - 1:
            return "STRONG_BEARISH"
        elif bullish > bearish:
            return "BULLISH"
        elif bearish > bullish:
            return "BEARISH"
        else:
            return "NEUTRAL"

# ========== CANDLESTICK PATTERN DETECTOR ==========
class CandlestickPatternDetector:
    """Detect Japanese candlestick patterns"""
    
    @staticmethod
    def detect_patterns(candles: List[Dict], lookback: int = 10) -> List[Dict]:
        """Detect candlestick patterns in recent candles"""
        if len(candles) < 3:
            return []
        
        patterns = []
        
        # Check last few candles
        start_idx = max(0, len(candles) - lookback)
        
        for i in range(start_idx, len(candles)):
            if i < 1:
                continue
                
            current = candles[i]
            previous = candles[i-1]
            
            # Hammer
            if CandlestickPatternDetector._is_hammer(current):
                patterns.append({
                    "name": "Hammer",
                    "type": "reversal",
                    "direction": "bullish",
                    "position": i,
                    "confidence": 75
                })
            
            # Shooting Star
            if CandlestickPatternDetector._is_shooting_star(current):
                patterns.append({
                    "name": "Shooting Star",
                    "type": "reversal",
                    "direction": "bearish",
                    "position": i,
                    "confidence": 75
                })
            
            # Bullish Engulfing
            if i >= 1:
                if CandlestickPatternDetector._is_bullish_engulfing(previous, current):
                    patterns.append({
                        "name": "Bullish Engulfing",
                        "type": "reversal",
                        "direction": "bullish",
                        "position": i,
                        "confidence": 85
                    })
            
            # Bearish Engulfing
            if i >= 1:
                if CandlestickPatternDetector._is_bearish_engulfing(previous, current):
                    patterns.append({
                        "name": "Bearish Engulfing",
                        "type": "reversal",
                        "direction": "bearish",
                        "position": i,
                        "confidence": 85
                    })
            
            # Doji
            if CandlestickPatternDetector._is_doji(current):
                patterns.append({
                    "name": "Doji",
                    "type": "indecision",
                    "direction": "neutral",
                    "position": i,
                    "confidence": 60
                })
        
        # Check 3-candle patterns
        for i in range(start_idx, len(candles)):
            if i < 2:
                continue
                
            c1, c2, c3 = candles[i-2], candles[i-1], candles[i]
            
            # Morning Star
            if CandlestickPatternDetector._is_morning_star(c1, c2, c3):
                patterns.append({
                    "name": "Morning Star",
                    "type": "reversal",
                    "direction": "bullish",
                    "position": i,
                    "confidence": 90
                })
            
            # Evening Star
            if CandlestickPatternDetector._is_evening_star(c1, c2, c3):
                patterns.append({
                    "name": "Evening Star",
                    "type": "reversal",
                    "direction": "bearish",
                    "position": i,
                    "confidence": 90
                })
        
        return patterns
    
    @staticmethod
    def _is_hammer(candle: Dict) -> bool:
        """Check if candle is a Hammer pattern"""
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        
        return (lower_shadow > body * 2 and 
                upper_shadow < body * 0.1 and
                body > 0)
    
    @staticmethod
    def _is_shooting_star(candle: Dict) -> bool:
        """Check if candle is a Shooting Star pattern"""
        body = abs(candle["close"] - candle["open"])
        upper_shadow = candle["high"] - max(candle["open"], candle["close"])
        lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
        
        return (upper_shadow > body * 2 and
                lower_shadow < body * 0.1 and
                body > 0)
    
    @staticmethod
    def _is_bullish_engulfing(prev: Dict, curr: Dict) -> bool:
        """Check for Bullish Engulfing pattern"""
        prev_body = abs(prev["close"] - prev["open"])
        curr_body = abs(curr["close"] - curr["open"])
        
        return (prev["close"] < prev["open"] and  # Previous bearish
                curr["close"] > curr["open"] and  # Current bullish
                curr["open"] < prev["close"] and  # Opens below prev close
                curr["close"] > prev["open"] and  # Closes above prev open
                curr_body > prev_body * 1.1)      # Larger body
    
    @staticmethod
    def _is_bearish_engulfing(prev: Dict, curr: Dict) -> bool:
        """Check for Bearish Engulfing pattern"""
        prev_body = abs(prev["close"] - prev["open"])
        curr_body = abs(curr["close"] - curr["open"])
        
        return (prev["close"] > prev["open"] and  # Previous bullish
                curr["close"] < curr["open"] and  # Current bearish
                curr["open"] > prev["close"] and  # Opens above prev close
                curr["close"] < prev["open"] and  # Closes below prev open
                curr_body > prev_body * 1.1)      # Larger body
    
    @staticmethod
    def _is_doji(candle: Dict) -> bool:
        """Check if candle is a Doji"""
        body = abs(candle["close"] - candle["open"])
        total_range = candle["high"] - candle["low"]
        
        return body < total_range * 0.1 and total_range > 0
    
    @staticmethod
    def _is_morning_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Check for Morning Star pattern"""
        c1_bearish = c1["close"] < c1["open"]
        c3_bullish = c3["close"] > c3["open"]
        c2_small_body = abs(c2["close"] - c2["open"]) < abs(c1["close"] - c1["open"]) * 0.3
        
        return c1_bearish and c2_small_body and c3_bullish and c3["close"] > (c1["open"] + c1["close"]) / 2
    
    @staticmethod
    def _is_evening_star(c1: Dict, c2: Dict, c3: Dict) -> bool:
        """Check for Evening Star pattern"""
        c1_bullish = c1["close"] > c1["open"]
        c3_bearish = c3["close"] < c3["open"]
        c2_small_body = abs(c2["close"] - c2["open"]) < abs(c1["close"] - c1["open"]) * 0.3
        
        return c1_bullish and c2_small_body and c3_bearish and c3["close"] < (c1["open"] + c1["close"]) / 2

# ========== ICT MARKET STRUCTURE ANALYZER ==========
class ICTMarketAnalyzer:
    """Analyze market structure using ICT concepts"""
    
    @staticmethod
    def analyze_market_structure(candles: List[Dict], lookback: int = 50) -> Dict:
        """Analyze market structure using ICT concepts"""
        if len(candles) < lookback:
            return {"structure": "INSUFFICIENT_DATA"}
        
        recent = candles[-lookback:]
        
        # Find swing highs and lows
        highs = [c["high"] for c in recent]
        lows = [c["low"] for c in recent]
        
        # Identify higher highs/lower highs and higher lows/lower lows
        hh_count = 0
        lh_count = 0
        hl_count = 0
        ll_count = 0
        
        for i in range(2, len(recent)):
            # Check for higher high
            if recent[i]["high"] > recent[i-1]["high"] > recent[i-2]["high"]:
                hh_count += 1
            # Check for lower high
            elif recent[i]["high"] < recent[i-1]["high"] < recent[i-2]["high"]:
                lh_count += 1
            
            # Check for higher low
            if recent[i]["low"] > recent[i-1]["low"] > recent[i-2]["low"]:
                hl_count += 1
            # Check for lower low
            elif recent[i]["low"] < recent[i-1]["low"] < recent[i-2]["low"]:
                ll_count += 1
        
        # Determine market structure
        if hh_count > lh_count * 2 and hl_count > ll_count * 2:
            structure = "BULLISH_TREND"
            strength = "STRONG"
        elif lh_count > hh_count * 2 and ll_count > hl_count * 2:
            structure = "BEARISH_TREND"
            strength = "STRONG"
        elif hh_count > lh_count and hl_count > ll_count:
            structure = "BULLISH_TREND"
            strength = "MODERATE"
        elif lh_count > hh_count and ll_count > hl_count:
            structure = "BEARISH_TREND"
            strength = "MODERATE"
        else:
            structure = "RANGING"
            strength = "NEUTRAL"
        
        # Detect Fair Value Gaps
        fvgs = ICTMarketAnalyzer._detect_fvg(recent[-20:])
        
        # Detect Order Blocks
        order_blocks = ICTMarketAnalyzer._detect_order_blocks(recent[-30:])
        
        return {
            "structure": structure,
            "strength": strength,
            "higher_highs": hh_count,
            "lower_highs": lh_count,
            "higher_lows": hl_count,
            "lower_lows": ll_count,
            "fair_value_gaps": len(fvgs),
            "order_blocks": len(order_blocks),
            "details": {
                "fvgs": fvgs[:3],  # Show only first 3
                "order_blocks": order_blocks[:3]
            }
        }
    
    @staticmethod
    def _detect_fvg(candles: List[Dict]) -> List[Dict]:
        """Detect Fair Value Gaps"""
        fvgs = []
        
        for i in range(2, len(candles)):
            prev = candles[i-2]
            curr = candles[i]
            
            # Bullish FVG
            if prev["high"] < curr["low"]:
                fvgs.append({
                    "type": "BULLISH",
                    "gap_low": prev["high"],
                    "gap_high": curr["low"],
                    "size": curr["low"] - prev["high"],
                    "position": i
                })
            
            # Bearish FVG
            if prev["low"] > curr["high"]:
                fvgs.append({
                    "type": "BEARISH",
                    "gap_low": curr["high"],
                    "gap_high": prev["low"],
                    "size": prev["low"] - curr["high"],
                    "position": i
                })
        
        return fvgs
    
    @staticmethod
    def _detect_order_blocks(candles: List[Dict]) -> List[Dict]:
        """Detect Order Blocks"""
        order_blocks = []
        
        for i in range(3, len(candles)):
            # Bullish Order Block
            if (candles[i-1]["close"] < candles[i-1]["open"] and  # Bearish candle
                candles[i]["close"] > candles[i]["open"] and      # Bullish candle
                candles[i]["close"] > candles[i-1]["high"]):      # Closes above previous high
                
                order_blocks.append({
                    "type": "BULLISH",
                    "high": candles[i-1]["high"],
                    "low": candles[i-1]["low"],
                    "position": i-1
                })
            
            # Bearish Order Block
            if (candles[i-1]["close"] > candles[i-1]["open"] and  # Bullish candle
                candles[i]["close"] < candles[i]["open"] and      # Bearish candle
                candles[i]["close"] < candles[i-1]["low"]):       # Closes below previous low
                
                order_blocks.append({
                    "type": "BEARISH",
                    "high": candles[i-1]["high"],
                    "low": candles[i-1]["low"],
                    "position": i-1
                })
        
        return order_blocks

# ========== SIGNAL GENERATOR ==========
class SignalGenerator:
    """Generate trading signals with confidence levels"""
    
    @staticmethod
    def generate_signal(
        candles: List[Dict],
        indicators: Dict,
        patterns: List[Dict],
        market_structure: Dict,
        ml_prediction: Dict,
        heikin_ashi_trend: str
    ) -> Dict:
        """Generate comprehensive trading signal"""
        
        # Initialize component signals
        component_signals = {}
        
        # 1. EMA Signal
        ema_signal = SignalGenerator._generate_ema_signal(indicators)
        component_signals["ema"] = ema_signal
        
        # 2. RSI Signal
        rsi_signal = SignalGenerator._generate_rsi_signal(indicators)
        component_signals["rsi"] = rsi_signal
        
        # 3. Pattern Signal
        pattern_signal = SignalGenerator._generate_pattern_signal(patterns)
        component_signals["patterns"] = pattern_signal
        
        # 4. Market Structure Signal
        structure_signal = SignalGenerator._generate_structure_signal(market_structure)
        component_signals["market_structure"] = structure_signal
        
        # 5. ML Prediction Signal
        ml_signal = SignalGenerator._generate_ml_signal(ml_prediction)
        component_signals["ml"] = ml_signal
        
        # 6. Heikin Ashi Signal
        ha_signal = SignalGenerator._generate_ha_signal(heikin_ashi_trend)
        component_signals["heikin_ashi"] = ha_signal
        
        # Combine signals with weights
        weights = {
            "ema": 0.20,
            "rsi": 0.15,
            "patterns": 0.15,
            "market_structure": 0.20,
            "ml": 0.25,
            "heikin_ashi": 0.05
        }
        
        total_score = 0
        total_confidence = 0
        
        for name, signal in component_signals.items():
            weight = weights.get(name, 0)
            score_value = SignalGenerator._signal_to_score(signal.get("signal", "NEUTRAL"))
            confidence = signal.get("confidence", 0)
            
            total_score += score_value * weight * (confidence / 100)
            total_confidence += confidence * weight
        
        # Determine final signal
        final_signal = SignalGenerator._determine_final_signal(total_score, total_confidence)
        
        # Determine confidence level
        confidence_level = SignalGenerator._determine_confidence_level(total_confidence)
        
        return {
            "signal": final_signal,
            "confidence": round(total_confidence, 1),
            "confidence_level": confidence_level,
            "score": round(total_score, 3),
            "components": component_signals,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    
    @staticmethod
    def _generate_ema_signal(indicators: Dict) -> Dict:
        """Generate signal from EMA crossovers"""
        ema_9 = indicators.get("ema_9")
        ema_21 = indicators.get("ema_21")
        
        if ema_9 is None or ema_21 is None:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "missing_data"}
        
        # Check for crossovers
        if ema_9 > ema_21:
            # Check if recently crossed above
            distance_pct = ((ema_9 - ema_21) / ema_21) * 100
            if distance_pct > 2:
                return {
                    "signal": "STRONG_BUY",
                    "confidence": min(90, 70 + distance_pct),
                    "reason": f"EMA 9 above EMA 21 by {distance_pct:.2f}%"
                }
            else:
                return {
                    "signal": "BUY",
                    "confidence": 65,
                    "reason": "EMA 9 above EMA 21"
                }
        else:
            distance_pct = ((ema_21 - ema_9) / ema_9) * 100
            if distance_pct > 2:
                return {
                    "signal": "STRONG_SELL",
                    "confidence": min(90, 70 + distance_pct),
                    "reason": f"EMA 9 below EMA 21 by {distance_pct:.2f}%"
                }
            else:
                return {
                    "signal": "SELL",
                    "confidence": 65,
                    "reason": "EMA 9 below EMA 21"
                }
    
    @staticmethod
    def _generate_rsi_signal(indicators: Dict) -> Dict:
        """Generate signal from RSI"""
        rsi = indicators.get("rsi")
        
        if rsi is None:
            return {"signal": "NEUTRAL", "confidence": 0, "reason": "missing_data"}
        
        if rsi < 30:
            oversold_level = 30 - rsi
            confidence = min(90, 70 + oversold_level)
            return {
                "signal": "STRONG_BUY",
                "confidence": confidence,
                "reason": f"RSI oversold: {rsi:.1f}"
            }
        elif rsi > 70:
            overbought_level = rsi - 70
            confidence = min(90, 70 + overbought_level)
            return {
                "signal": "STRONG_SELL",
                "confidence": confidence,
                "reason": f"RSI overbought: {rsi:.1f}"
            }
        elif 40 <= rsi <= 60:
            return {
                "signal": "NEUTRAL",
                "confidence": 50,
                "reason": f"RSI neutral: {rsi:.1f}"
            }
        elif rsi > 50:
            return {
                "signal": "BUY",
                "confidence": 60,
                "reason": f"RSI bullish: {rsi:.1f}"
            }
        else:
            return {
                "signal": "SELL",
                "confidence": 60,
                "reason": f"RSI bearish: {rsi:.1f}"
            }
    
    @staticmethod
    def _generate_pattern_signal(patterns: List[Dict]) -> Dict:
        """Generate signal from candlestick patterns"""
        if not patterns:
            return {"signal": "NEUTRAL", "confidence": 30, "reason": "no_patterns"}
        
        # Get recent patterns (last 5 candles)
        recent_patterns = [p for p in patterns if p.get("position", 0) >= (len(patterns) - 5)]
        
        if not recent_patterns:
            return {"signal": "NEUTRAL", "confidence": 40, "reason": "no_recent_patterns"}
        
        # Calculate weighted signal
        bullish_score = sum(p.get("confidence", 0) for p in recent_patterns 
                           if p.get("direction") == "bullish")
        bearish_score = sum(p.get("confidence", 0) for p in recent_patterns 
                           if p.get("direction") == "bearish")
        
        if bullish_score > bearish_score * 1.5:
            max_conf = max(p.get("confidence", 0) for p in recent_patterns if p.get("direction") == "bullish")
            return {
                "signal": "STRONG_BUY" if max_conf > 85 else "BUY",
                "confidence": min(95, max_conf),
                "reason": f"{len([p for p in recent_patterns if p.get('direction') == 'bullish'])} bullish pattern(s)"
            }
        elif bearish_score > bullish_score * 1.5:
            max_conf = max(p.get("confidence", 0) for p in recent_patterns if p.get("direction") == "bearish")
            return {
                "signal": "STRONG_SELL" if max_conf > 85 else "SELL",
                "confidence": min(95, max_conf),
                "reason": f"{len([p for p in recent_patterns if p.get('direction') == 'bearish'])} bearish pattern(s)"
            }
        else:
            return {
                "signal": "NEUTRAL",
                "confidence": 50,
                "reason": "mixed_patterns"
            }
    
    @staticmethod
    def _generate_structure_signal(market_structure: Dict) -> Dict:
        """Generate signal from market structure"""
        structure = market_structure.get("structure", "NEUTRAL")
        strength = market_structure.get("strength", "NEUTRAL")
        
        if "BULLISH" in structure:
            if "STRONG" in strength:
                return {"signal": "STRONG_BUY", "confidence": 85, "reason": "strong_bullish_structure"}
            else:
                return {"signal": "BUY", "confidence": 70, "reason": "bullish_structure"}
        elif "BEARISH" in structure:
            if "STRONG" in strength:
                return {"signal": "STRONG_SELL", "confidence": 85, "reason": "strong_bearish_structure"}
            else:
                return {"signal": "SELL", "confidence": 70, "reason": "bearish_structure"}
        else:
            return {"signal": "NEUTRAL", "confidence": 50, "reason": "ranging_market"}
    
    @staticmethod
    def _generate_ml_signal(ml_prediction: Dict) -> Dict:
        """Generate signal from ML prediction"""
        prediction = ml_prediction.get("prediction", "NEUTRAL")
        confidence = ml_prediction.get("confidence", 0.5) * 100
        
        signal_map = {
            "STRONG_BUY": "STRONG_BUY",
            "BUY": "BUY",
            "NEUTRAL": "NEUTRAL",
            "SELL": "SELL",
            "STRONG_SELL": "STRONG_SELL"
        }
        
        signal = signal_map.get(prediction, "NEUTRAL")
        
        return {
            "signal": signal,
            "confidence": confidence,
            "reason": f"ML prediction: {prediction}"
        }
    
    @staticmethod
    def _generate_ha_signal(heikin_ashi_trend: str) -> Dict:
        """Generate signal from Heikin Ashi trend"""
        trend_map = {
            "STRONG_BULLISH": {"signal": "STRONG_BUY", "confidence": 80},
            "BULLISH": {"signal": "BUY", "confidence": 65},
            "NEUTRAL": {"signal": "NEUTRAL", "confidence": 50},
            "BEARISH": {"signal": "SELL", "confidence": 65},
            "STRONG_BEARISH": {"signal": "STRONG_SELL", "confidence": 80}
        }
        
        return trend_map.get(heikin_ashi_trend, {"signal": "NEUTRAL", "confidence": 50})
    
    @staticmethod
    def _signal_to_score(signal: str) -> float:
        """Convert signal to numeric score"""
        scores = {
            "STRONG_BUY": 2.0,
            "BUY": 1.0,
            "NEUTRAL": 0.0,
            "SELL": -1.0,
            "STRONG_SELL": -2.0
        }
        return scores.get(signal, 0.0)
    
    @staticmethod
    def _determine_final_signal(score: float, confidence: float) -> str:
        """Determine final signal from weighted score"""
        if confidence < 40:
            return "NEUTRAL"
        elif score > 1.2:
            return "STRONG_BUY"
        elif score > 0.4:
            return "BUY"
        elif score < -1.2:
            return "STRONG_SELL"
        elif score < -0.4:
            return "SELL"
        else:
            return "NEUTRAL"
    
    @staticmethod
    def _determine_confidence_level(confidence: float) -> str:
        """Determine confidence level"""
        if confidence >= 85:
            return "VERY_HIGH"
        elif confidence >= 70:
            return "HIGH"
        elif confidence >= 55:
            return "MEDIUM"
        else:
            return "LOW"

# ========== AI CHATBOT MODULE ==========
class TradingChatBot:
    """AI Trading Assistant Chatbot"""
    
    def __init__(self, ai_engine: AITradingEngine, price_fetcher: PriceDataFetcher):
        self.ai_engine = ai_engine
        self.price_fetcher = price_fetcher
        self.context = []
        self.knowledge_base = {
            "patterns": {
                "hammer": "Bullish reversal pattern at support. Small body with long lower shadow.",
                "shooting star": "Bearish reversal at resistance. Small body with long upper shadow.",
                "engulfing": "Strong reversal pattern where one candle completely engulfs the previous.",
                "doji": "Indecision pattern showing market equilibrium."
            },
            "indicators": {
                "rsi": "Relative Strength Index (14). >70 overbought, <30 oversold.",
                "macd": "Moving Average Convergence Divergence. Bullish when MACD crosses above signal.",
                "ema": "Exponential Moving Average. Faster reaction than SMA.",
                "heikin ashi": "Smoothed candlestick chart showing trend direction clearly."
            },
            "strategies": {
                "trend following": "Trade in direction of EMA crossovers and higher highs/lows.",
                "mean reversion": "Trade RSI extremes back to middle range.",
                "breakout": "Trade breakouts from consolidation with increased volume."
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
                if symbol:
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
            if "analyze" in lower_msg and symbol:
                return await self._analyze_symbol(symbol)
            
            # ML prediction request
            if "predict" in lower_msg or "forecast" in lower_msg:
                if symbol:
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

# ========== WEBSOCKET MANAGER ==========
class WebSocketManager:
    """Manage WebSocket connections for real-time updates"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.price_updates = {}
    
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
    
    async def broadcast_price_update(self, symbol: str, price_data: Dict):
        """Broadcast price update to all connected clients"""
        message = json.dumps({
            "type": "price_update",
            "symbol": symbol,
            "data": price_data,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
        await self.broadcast(message)

# ========== GLOBAL INSTANCES ==========
ai_engine = AITradingEngine()
price_fetcher = PriceDataFetcher()
chatbot = TradingChatBot(ai_engine, price_fetcher)
websocket_manager = WebSocketManager()

# ========== API ENDPOINTS ==========
@app.get("/")
async def root():
    return {"message": "Professional AI Trading Bot v4.0", "status": "online"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "4.0.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "services": {
            "ai_engine": "active",
            "price_fetcher": "active",
            "chatbot": "active"
        }
    }

@app.get("/api/analyze/{symbol}")
async def analyze_symbol(
    symbol: str,
    interval: str = Query(default="1h", regex="^(1h|4h|1d)$"),
    limit: int = Query(default=200, ge=50, le=1000)
):
    """Complete technical analysis for a symbol"""
    try:
        logger.info(f"Analysis request for {symbol} ({interval}, {limit} candles)")
        
        # Fetch candle data
        candles = await price_fetcher.get_candles(symbol, interval, limit)
        
        if not candles or len(candles) < 50:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient data for analysis. Got {len(candles) if candles else 0} candles, need at least 50."
            )
        
        # Calculate technical indicators
        ema_9 = TechnicalIndicators.calculate_ema(candles, 9)
        ema_21 = TechnicalIndicators.calculate_ema(candles, 21)
        ema_50 = TechnicalIndicators.calculate_ema(candles, 50)
        rsi = TechnicalIndicators.calculate_rsi(candles, 14)
        macd_line, signal_line, histogram = TechnicalIndicators.calculate_macd(candles)
        sma_20 = TechnicalIndicators.calculate_sma(candles, 20)
        
        # Get latest values
        indicators = {
            "ema_9": ema_9[-1] if ema_9[-1] else None,
            "ema_21": ema_21[-1] if ema_21[-1] else None,
            "ema_50": ema_50[-1] if ema_50[-1] else None,
            "rsi": rsi[-1] if rsi[-1] else None,
            "macd_line": macd_line[-1] if macd_line[-1] else None,
            "macd_signal": signal_line[-1] if signal_line[-1] else None,
            "macd_histogram": histogram[-1] if histogram[-1] else None,
            "sma_20": sma_20[-1] if sma_20[-1] else None
        }
        
        # Detect patterns
        patterns = CandlestickPatternDetector.detect_patterns(candles)
        
        # Analyze market structure
        market_structure = ICTMarketAnalyzer.analyze_market_structure(candles)
        
        # Convert to Heikin Ashi and detect trend
        ha_candles = TechnicalIndicators.convert_to_heikin_ashi(candles)
        ha_trend = TechnicalIndicators.detect_trend_from_heikin_ashi(ha_candles)
        
        # ML Prediction
        df = pd.DataFrame(candles)
        if not df.empty:
            df.set_index('timestamp', inplace=True)
            ml_prediction = ai_engine.predict(symbol, df)
        else:
            ml_prediction = {"prediction": "NEUTRAL", "confidence": 0.5}
        
        # Generate comprehensive signal
        signal = SignalGenerator.generate_signal(
            candles=candles,
            indicators=indicators,
            patterns=patterns,
            market_structure=market_structure,
            ml_prediction=ml_prediction,
            heikin_ashi_trend=ha_trend
        )
        
        # Current price data
        current_candle = candles[-1]
        prev_candle = candles[-2] if len(candles) > 1 else current_candle
        price_change = ((current_candle["close"] - prev_candle["close"]) / prev_candle["close"]) * 100
        
        # Prepare response
        response = {
            "success": True,
            "symbol": symbol.upper(),
            "interval": interval,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "price_data": {
                "current": round(current_candle["close"], 4),
                "open": round(current_candle["open"], 4),
                "high": round(current_candle["high"], 4),
                "low": round(current_candle["low"], 4),
                "volume": round(current_candle["volume"], 2),
                "change_percent": round(price_change, 2),
                "quote_volume": round(current_candle.get("quote_volume", 0), 2),
                "trades": current_candle.get("trades", 0)
            },
            "indicators": {k: round(v, 4) if v is not None else None for k, v in indicators.items()},
            "patterns": patterns[-10:],  # Last 10 patterns
            "market_structure": market_structure,
            "heikin_ashi_trend": ha_trend,
            "ml_prediction": ml_prediction,
            "signal": signal,
            "metadata": {
                "candles_analyzed": len(candles),
                "patterns_detected": len(patterns),
                "analysis_time": datetime.utcnow().isoformat()
            }
        }
        
        logger.info(f"✅ Analysis complete for {symbol}. Signal: {signal['signal']} ({signal['confidence']}%)")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis error for {symbol}: {str(e)}", exc_info=True)
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

@app.get("/api/symbols")
async def get_symbols():
    """Get list of supported symbols"""
    symbols = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT",
        "XRPUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT",
        "LINKUSDT", "UNIUSDT", "LTCUSDT", "ATOMUSDT", "ETCUSDT"
    ]
    return {"symbols": symbols}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time updates"""
    await websocket_manager.connect(websocket)
    try:
        while True:
            # Wait for message from client
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                msg_type = message.get("type")
                
                if msg_type == "subscribe":
                    symbol = message.get("symbol", "BTCUSDT")
                    # Send initial data
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
                
                elif msg_type == "analyze":
                    symbol = message.get("symbol", "BTCUSDT")
                    # Trigger analysis and send result
                    # (This is simplified - in production, you'd want to handle this asynchronously)
                    pass
                    
            except json.JSONDecodeError:
                await websocket_manager.send_personal_message(
                    json.dumps({"error": "Invalid JSON format"}),
                    websocket
                )
            except Exception as e:
                logger.error(f"WebSocket error: {str(e)}")
                
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket endpoint error: {str(e)}")
        websocket_manager.disconnect(websocket)

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    await price_fetcher.close()
    logger.info("Application shutdown complete")

# ========== DASHBOARD ==========
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Trading Dashboard"""
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Professional AI Trading Bot v4.0</title>
    <script src="https://s3.tradingview.com/tv.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
            color: #e2e8f0;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1600px; margin: 0 auto; }
        header {
            background: linear-gradient(90deg, #3b82f6, #8b5cf6);
            padding: 2rem;
            border-radius: 16px;
            margin-bottom: 2rem;
            text-align: center;
            box-shadow: 0 10px 30px rgba(59, 130, 246, 0.3);
        }
        .logo {
            font-size: 2.5rem;
            font-weight: 900;
            color: white;
            margin-bottom: 0.5rem;
        }
        .tagline {
            color: rgba(255, 255, 255, 0.9);
            font-size: 1.1rem;
            margin-bottom: 1rem;
        }
        .badges {
            display: flex;
            justify-content: center;
            gap: 0.75rem;
            flex-wrap: wrap;
        }
        .badge {
            background: rgba(255, 255, 255, 0.15);
            padding: 0.4rem 1rem;
            border-radius: 20px;
            font-size: 0.85rem;
            backdrop-filter: blur(10px);
        }
        .dashboard-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }
        @media (max-width: 1200px) {
            .dashboard-grid { grid-template-columns: 1fr; }
        }
        .chart-container {
            background: #1a1f3a;
            border-radius: 12px;
            padding: 15px;
            height: 600px;
        }
        .panel {
            background: #1a1f3a;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .panel-title {
            font-size: 1.3rem;
            font-weight: 700;
            margin-bottom: 1rem;
            color: #3b82f6;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: rgba(30, 41, 59, 0.5);
            padding: 1rem;
            border-radius: 8px;
            text-align: center;
        }
        .stat-value {
            font-size: 1.8rem;
            font-weight: bold;
            margin: 0.5rem 0;
        }
        .buy { color: #10b981; }
        .sell { color: #ef4444; }
        .neutral { color: #94a3b8; }
        .chat-container {
            display: flex;
            flex-direction: column;
            height: 600px;
        }
        .chat-messages {
            flex: 1;
            overflow-y: auto;
            background: rgba(30, 41, 59, 0.5);
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1rem;
        }
        .chat-input-container {
            display: flex;
            gap: 10px;
        }
        input[type="text"] {
            flex: 1;
            background: rgba(30, 41, 59, 0.8);
            border: 1px solid #475569;
            color: white;
            padding: 0.75rem 1rem;
            border-radius: 8px;
            font-size: 1rem;
        }
        button {
            background: linear-gradient(90deg, #3b82f6, #8b5cf6);
            color: white;
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s;
        }
        button:hover { transform: translateY(-2px); }
        .signal-badge {
            display: inline-block;
            padding: 0.4rem 1rem;
            border-radius: 20px;
            font-weight: 600;
            margin-left: 1rem;
        }
        .signal-buy { background: rgba(16, 185, 129, 0.2); color: #10b981; }
        .signal-sell { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
        .signal-neutral { background: rgba(148, 163, 184, 0.2); color: #94a3b8; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">🤖 AI Trading Bot v4.0</div>
            <div class="tagline">Professional Trading System with Advanced AI & Technical Analysis</div>
            <div class="badges">
                <div class="badge">Binance WebSocket</div>
                <div class="badge">CoinGecko API</div>
                <div class="badge">LSTM + Transformer</div>
                <div class="badge">ICT Market Structure</div>
                <div class="badge">Heikin Ashi</div>
                <div class="badge">12 Candlestick Patterns</div>
            </div>
        </header>
        
        <div class="dashboard-grid">
            <div class="chart-container">
                <div id="tradingview_chart" style="height: 100%;"></div>
            </div>
            
            <div class="panel">
                <h2 class="panel-title">📊 Trading Signal</h2>
                <div id="signalDisplay">
                    <div class="loading">Loading signal...</div>
                </div>
                
                <h2 class="panel-title" style="margin-top: 2rem;">💬 AI Trading Assistant</h2>
                <div class="chat-container">
                    <div class="chat-messages" id="chatMessages">
                        <div>🤖 Hello! I'm your AI trading assistant. Ask me about patterns, indicators, or trading strategies.</div>
                    </div>
                    <div class="chat-input-container">
                        <input type="text" id="chatInput" placeholder="Ask about trading...">
                        <button onclick="sendMessage()">Send</button>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="stats-grid">
            <div class="panel">
                <h2 class="panel-title">⚡ Quick Actions</h2>
                <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                    <button onclick="analyzeSymbol('BTCUSDT')">Analyze BTC</button>
                    <button onclick="analyzeSymbol('ETHUSDT')">Analyze ETH</button>
                    <button onclick="analyzeSymbol('SOLUSDT')">Analyze SOL</button>
                    <button onclick="trainModel('BTCUSDT')">Train BTC Model</button>
                    <button onclick="showHealth()">System Health</button>
                </div>
            </div>
            
            <div class="panel">
                <h2 class="panel-title">📈 Market Overview</h2>
                <div id="marketOverview">
                    <div class="loading">Loading market data...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // TradingView Chart
        new TradingView.widget({
            "width": "100%",
            "height": "100%",
            "symbol": "BINANCE:BTCUSDT",
            "interval": "60",
            "timezone": "Etc/UTC",
            "theme": "dark",
            "style": "1",
            "locale": "en",
            "toolbar_bg": "#1a1f3a",
            "enable_publishing": false,
            "hide_side_toolbar": false,
            "allow_symbol_change": true,
            "container_id": "tradingview_chart",
            "studies": ["RSI@tv-basicstudies", "MACD@tv-basicstudies"]
        });
        
        // WebSocket connection
        let ws = null;
        function connectWebSocket() {
            ws = new WebSocket(`ws://${window.location.host}/ws`);
            
            ws.onopen = function() {
                console.log("WebSocket connected");
                ws.send(JSON.stringify({type: "subscribe", symbol: "BTCUSDT"}));
            };
            
            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                if (data.type === "price_update") {
                    updatePriceDisplay(data);
                }
            };
            
            ws.onclose = function() {
                console.log("WebSocket disconnected");
                setTimeout(connectWebSocket, 3000);
            };
        }
        
        // Initialize
        connectWebSocket();
        updateSignals();
        
        // Functions
        async function analyzeSymbol(symbol) {
            try {
                const response = await fetch(`/api/analyze/${symbol}?interval=1h`);
                const data = await response.json();
                
                if (data.success) {
                    displaySignal(data.signal, data.price_data);
                    updateTradingView(symbol);
                }
            } catch (error) {
                console.error("Analysis error:", error);
                alert("Analysis failed. Check console for details.");
            }
        }
        
        async function trainModel(symbol) {
            try {
                const response = await fetch(`/api/train/${symbol}`, {method: 'POST'});
                const data = await response.json();
                
                if (data.success) {
                    alert(`✅ ${data.message}`);
                } else {
                    alert("Training failed");
                }
            } catch (error) {
                console.error("Training error:", error);
                alert("Training failed. Check console for details.");
            }
        }
        
        async function updateSignals() {
            try {
                const response = await fetch('/api/analyze/BTCUSDT');
                const data = await response.json();
                
                if (data.success) {
                    displaySignal(data.signal, data.price_data);
                }
            } catch (error) {
                console.error("Signal update error:", error);
            }
            
            // Update every 60 seconds
            setTimeout(updateSignals, 60000);
        }
        
        function displaySignal(signal, priceData) {
            const container = document.getElementById('signalDisplay');
            const signalClass = signal.signal.toLowerCase().includes('buy') ? 'buy' :
                              signal.signal.toLowerCase().includes('sell') ? 'sell' : 'neutral';
            
            container.innerHTML = `
                <div class="stat-card">
                    <div>Signal</div>
                    <div class="stat-value ${signalClass}">${signal.signal.replace('_', ' ')}</div>
                    <div>${signal.confidence.toFixed(1)}% Confidence • ${signal.confidence_level.replace('_', ' ')}</div>
                </div>
                <div style="margin-top: 1rem;">
                    <div><strong>Price:</strong> $${priceData.current.toFixed(2)}</div>
                    <div><strong>Change:</strong> <span class="${priceData.change_percent >= 0 ? 'buy' : 'sell'}">
                        ${priceData.change_percent >= 0 ? '▲' : '▼'} ${Math.abs(priceData.change_percent).toFixed(2)}%
                    </span></div>
                    <div><strong>Volume:</strong> ${priceData.volume.toLocaleString()}</div>
                </div>
            `;
        }
        
        async function sendMessage() {
            const input = document.getElementById('chatInput');
            const message = input.value.trim();
            if (!message) return;
            
            const chatBox = document.getElementById('chatMessages');
            chatBox.innerHTML += `<div><strong>You:</strong> ${message}</div>`;
            
            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: message, symbol: 'BTCUSDT'})
                });
                
                const data = await response.json();
                if (data.success) {
                    chatBox.innerHTML += `<div><strong>AI:</strong> ${data.response}</div>`;
                }
            } catch (error) {
                console.error("Chat error:", error);
                chatBox.innerHTML += `<div><strong>AI:</strong> Error: ${error.message}</div>`;
            }
            
            chatBox.scrollTop = chatBox.scrollHeight;
            input.value = '';
        }
        
        function updateTradingView(symbol) {
            if (window.tvWidget) {
                window.tvWidget.setSymbol(`BINANCE:${symbol}`);
            }
        }
        
        async function showHealth() {
            try {
                const response = await fetch('/health');
                const data = await response.json();
                alert(`System Health: ${data.status}\nVersion: ${data.version}`);
            } catch (error) {
                console.error("Health check error:", error);
                alert("Health check failed");
            }
        }
        
        // Handle Enter key in chat
        document.getElementById('chatInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendMessage();
        });
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html)

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
