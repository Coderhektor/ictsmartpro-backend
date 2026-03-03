import sys
import json
import time
import asyncio
import logging
import os
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
from enum import Enum
from pathlib import Path

# ML Libraries
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import xgboost as xgb
import lightgbm as lgb

# FastAPI
from fastapi import FastAPI, Request, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

# Pydantic
from pydantic import BaseModel, Field

# Async HTTP
import aiohttp
from aiohttp import ClientTimeout, TCPConnector

# ========================================================================================================
# PRODUCTION LOGGING
# ========================================================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("ictsmartpro-ml")


# ========================================================================================================
# PRODUCTION CONFIGURATION
# ========================================================================================================
class Config:
    """Production config with ML settings"""
    
    # Server
    ENV = os.getenv("ENV", "production")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    PORT = int(os.getenv("PORT", "8000"))
    
    # API Settings
    API_TIMEOUT = int(os.getenv("API_TIMEOUT", "10"))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "25"))
    
    # Data Settings
    MIN_CANDLES = int(os.getenv("MIN_CANDLES", "100"))
    CACHE_TTL = int(os.getenv("CACHE_TTL", "30"))
    
    # ML Settings
    ML_MODEL_DIR = os.getenv("ML_MODEL_DIR", "/app/models")
    ML_AUTO_RETRAIN = os.getenv("ML_AUTO_RETRAIN", "true").lower() == "true"
    ML_RETRAIN_HOURS = int(os.getenv("ML_RETRAIN_HOURS", "24"))
    ML_MIN_TRAINING_SAMPLES = int(os.getenv("ML_MIN_TRAINING_SAMPLES", "500"))
    ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.6"))
    
    # Security
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")


# ========================================================================================================
# DATA MODELS
# ========================================================================================================
class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SignalType(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class Candle(BaseModel):
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    exchange: str


class MLFeatures(BaseModel):
    """ML model features"""
    # Price features
    return_1: float
    return_5: float
    return_10: float
    volatility: float
    
    # RSI features
    rsi_14: float
    rsi_14_change: float
    
    # MACD features
    macd: float
    macd_signal: float
    macd_histogram: float
    
    # Bollinger features
    bb_position: float
    bb_width: float
    
    # Moving average features
    price_to_sma20: float
    price_to_sma50: float
    sma20_above_sma50: int
    
    # Volume features
    volume_ratio: float
    volume_trend: float
    
    # ATR features
    atr_percent: float
    
    # Momentum features
    momentum_5: float
    momentum_10: float


class MLPrediction(BaseModel):
    """ML model prediction"""
    signal: SignalType
    confidence: float
    probability: float
    model_version: str
    features_used: List[str]


class AnalysisResponse(BaseModel):
    """Complete analysis response"""
    success: bool
    symbol: str
    interval: str
    timestamp: str
    price: Dict[str, float]
    ml_prediction: MLPrediction
    technical: Dict[str, float]
    patterns: List[Dict]
    data_points: int
    model_info: Dict[str, Any]
    performance_ms: float


# ========================================================================================================
# PRODUCTION ML MODEL TRAINER
# ========================================================================================================
class MLModelTrainer:
    """Production ML model trainer with persistence"""
    
    def __init__(self, model_dir: str = "models"):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        # Model registry
        self.models: Dict[str, Dict] = {}
        self.scalers: Dict[str, StandardScaler] = {}
        self.feature_importance: Dict[str, List] = {}
        
        # Load existing models
        self._load_models()
        
        logger.info(f"ML Trainer initialized with {len(self.models)} models")
    
    def _load_models(self):
        """Load all saved models from disk"""
        for model_file in self.model_dir.glob("*.joblib"):
            try:
                model_key = model_file.stem
                model_data = joblib.load(model_file)
                
                if isinstance(model_data, dict) and 'model' in model_data:
                    self.models[model_key] = model_data
                    
                    # Load scaler if exists
                    scaler_file = self.model_dir / f"{model_key}_scaler.joblib"
                    if scaler_file.exists():
                        self.scalers[model_key] = joblib.load(scaler_file)
                    
                    logger.info(f"Loaded model: {model_key}")
            except Exception as e:
                logger.error(f"Failed to load model {model_file}: {e}")
    
    def _get_model_key(self, symbol: str, interval: str) -> str:
        return f"{symbol}_{interval}".replace("/", "_")
    
    def _engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Feature engineering for ML model"""
        df = df.copy()
        
        # Price returns
        df['return_1'] = df['close'].pct_change(1)
        df['return_5'] = df['close'].pct_change(5)
        df['return_10'] = df['close'].pct_change(10)
        
        # Volatility
        df['volatility'] = df['return_1'].rolling(20).std() * np.sqrt(252)
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        df['rsi_14'] = 100 - (100 / (1 + rs))
        df['rsi_14_change'] = df['rsi_14'].diff(3)
        
        # MACD
        exp1 = df['close'].ewm(span=12).mean()
        exp2 = df['close'].ewm(span=26).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']
        
        # Bollinger Bands
        sma20 = df['close'].rolling(20).mean()
        std20 = df['close'].rolling(20).std()
        df['bb_upper'] = sma20 + (std20 * 2)
        df['bb_lower'] = sma20 - (std20 * 2)
        bb_range = (df['bb_upper'] - df['bb_lower']).replace(0, 1)
        df['bb_position'] = ((df['close'] - df['bb_lower']) / bb_range * 100).clip(0, 100)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / sma20
        
        # Moving averages
        df['sma20'] = df['close'].rolling(20).mean()
        df['sma50'] = df['close'].rolling(50).mean()
        df['price_to_sma20'] = df['close'] / df['sma20'] - 1
        df['price_to_sma50'] = df['close'] / df['sma50'] - 1
        df['sma20_above_sma50'] = (df['sma20'] > df['sma50']).astype(int)
        
        # Volume
        df['volume_sma20'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma20'].replace(0, 1)
        df['volume_trend'] = df['volume'].rolling(5).mean() / df['volume'].rolling(20).mean()
        
        # ATR
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['close'].shift()).abs()
        tr3 = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        df['atr_percent'] = df['atr'] / df['close']
        
        # Momentum
        df['momentum_5'] = df['close'].pct_change(5) * 100
        df['momentum_10'] = df['close'].pct_change(10) * 100
        
        # Fill NaN values
        df = df.ffill().bfill()
        df = df.fillna(0)
        df = df.replace([np.inf, -np.inf], 0)
        
        return df
    
    def _prepare_training_data(self, df: pd.DataFrame, horizon: int = 5, threshold: float = 0.01) -> Tuple[pd.DataFrame, pd.Series]:
        """Prepare features and labels for training"""
        # Engineer features
        df_features = self._engineer_features(df)
        
        # Define feature columns
        feature_columns = [
            'return_1', 'return_5', 'return_10', 'volatility',
            'rsi_14', 'rsi_14_change',
            'macd', 'macd_signal', 'macd_histogram',
            'bb_position', 'bb_width',
            'price_to_sma20', 'price_to_sma50', 'sma20_above_sma50',
            'volume_ratio', 'volume_trend',
            'atr_percent',
            'momentum_5', 'momentum_10'
        ]
        
        # Create target: 1 if price goes up > threshold in next horizon, 0 otherwise
        future_return = df['close'].shift(-horizon) / df['close'] - 1
        target = (future_return > threshold).astype(int)
        
        # Align features and target
        features = df_features[feature_columns].copy()
        
        # Remove rows with NaN
        valid_idx = ~(target.isna() | features.isna().any(axis=1))
        features = features[valid_idx]
        target = target[valid_idx]
        
        return features, target
    
    async def train(self, symbol: str, interval: str, df: pd.DataFrame, force: bool = False) -> Dict:
        """Train ML model on real data"""
        model_key = self._get_model_key(symbol, interval)
        model_path = self.model_dir / f"{model_key}.joblib"
        
        # Check if retraining is needed
        if not force and model_path.exists():
            model_data = joblib.load(model_path)
            last_train = datetime.fromisoformat(model_data.get('trained_at', '2000-01-01'))
            
            hours_since = (datetime.now() - last_train).total_seconds() / 3600
            if hours_since < Config.ML_RETRAIN_HOURS:
                logger.info(f"Model {model_key} is still fresh ({hours_since:.1f} hours old)")
                return model_data
        
        logger.info(f"🎯 Training ML model for {symbol} @ {interval}")
        
        try:
            # Prepare training data
            features, target = self._prepare_training_data(df)
            
            if len(features) < Config.ML_MIN_TRAINING_SAMPLES:
                raise ValueError(f"Insufficient training samples: {len(features)} < {Config.ML_MIN_TRAINING_SAMPLES}")
            
            logger.info(f"Training samples: {len(features)}, Features: {len(features.columns)}")
            
            # Train/test split (time-series split)
            split_idx = int(len(features) * 0.8)
            X_train, X_test = features.iloc[:split_idx], features.iloc[split_idx:]
            y_train, y_test = target.iloc[:split_idx], target.iloc[split_idx:]
            
            # Scale features
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            # Train multiple models
            models = {
                'xgboost': xgb.XGBClassifier(
                    n_estimators=200,
                    max_depth=8,
                    learning_rate=0.05,
                    random_state=42,
                    n_jobs=-1
                ),
                'lightgbm': lgb.LGBMClassifier(
                    n_estimators=200,
                    max_depth=10,
                    learning_rate=0.05,
                    random_state=42,
                    n_jobs=-1,
                    verbose=-1
                ),
                'random_forest': RandomForestClassifier(
                    n_estimators=200,
                    max_depth=15,
                    random_state=42,
                    n_jobs=-1
                )
            }
            
            results = {}
            trained_models = {}
            
            for name, model in models.items():
                try:
                    # Train
                    model.fit(X_train_scaled, y_train)
                    
                    # Predict
                    y_pred = model.predict(X_test_scaled)
                    y_proba = model.predict_proba(X_test_scaled)[:, 1]
                    
                    # Metrics
                    accuracy = accuracy_score(y_test, y_pred)
                    precision = precision_score(y_test, y_pred, zero_division=0)
                    recall = recall_score(y_test, y_pred, zero_division=0)
                    f1 = f1_score(y_test, y_pred, zero_division=0)
                    
                    # Cross-validation
                    cv_scores = cross_val_score(model, X_train_scaled, y_train, cv=5, scoring='accuracy')
                    
                    # Feature importance
                    if hasattr(model, 'feature_importances_'):
                        importance = dict(zip(features.columns, model.feature_importances_))
                        top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10]
                        self.feature_importance[name] = top_features
                    
                    results[name] = {
                        'accuracy': round(accuracy * 100, 2),
                        'precision': round(precision * 100, 2),
                        'recall': round(recall * 100, 2),
                        'f1_score': round(f1 * 100, 2),
                        'cv_mean': round(cv_scores.mean() * 100, 2),
                        'cv_std': round(cv_scores.std() * 100, 2)
                    }
                    
                    trained_models[name] = model
                    logger.info(f"✅ {name}: Accuracy={accuracy*100:.1f}%, CV={cv_scores.mean()*100:.1f}%")
                    
                except Exception as e:
                    logger.error(f"❌ {name} failed: {e}")
                    results[name] = {'error': str(e)}
            
            # Select best model
            best_model = max(
                [(n, r.get('accuracy', 0)) for n, r in results.items() if 'accuracy' in r],
                key=lambda x: x[1]
            )[0]
            
            # Save model
            model_data = {
                'models': trained_models,
                'best_model': best_model,
                'results': results,
                'feature_names': list(features.columns),
                'trained_at': datetime.now().isoformat(),
                'symbol': symbol,
                'interval': interval,
                'training_samples': len(features)
            }
            
            joblib.dump(model_data, model_path)
            joblib.dump(scaler, self.model_dir / f"{model_key}_scaler.joblib")
            
            # Save metadata
            metadata = {
                'symbol': symbol,
                'interval': interval,
                'trained_at': datetime.now().isoformat(),
                'results': results,
                'best_model': best_model,
                'feature_importance': self.feature_importance.get(best_model, [])
            }
            
            with open(self.model_dir / f"{model_key}_meta.json", 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Update registry
            self.models[model_key] = model_data
            self.scalers[model_key] = scaler
            
            logger.info(f"✅ Model saved: {model_key} (best: {best_model})")
            
            return metadata
            
        except Exception as e:
            logger.error(f"Training failed: {e}")
            raise
    
    async def predict(self, symbol: str, interval: str, df: pd.DataFrame) -> MLPrediction:
        """Make prediction using trained model"""
        model_key = self._get_model_key(symbol, interval)
        
        # Check if model exists
        if model_key not in self.models:
            model_path = self.model_dir / f"{model_key}.joblib"
            if model_path.exists():
                self.models[model_key] = joblib.load(model_path)
                scaler_path = self.model_dir / f"{model_key}_scaler.joblib"
                if scaler_path.exists():
                    self.scalers[model_key] = joblib.load(scaler_path)
            else:
                raise ValueError(f"No trained model found for {symbol} @ {interval}")
        
        model_data = self.models[model_key]
        scaler = self.scalers.get(model_key)
        
        # Engineer features
        df_features = self._engineer_features(df)
        feature_names = model_data['feature_names']
        
        # Get latest features
        latest_features = df_features[feature_names].iloc[-1:].fillna(0)
        
        # Scale
        if scaler:
            X_scaled = scaler.transform(latest_features)
        else:
            X_scaled = latest_features.values
        
        # Get best model
        best_model_name = model_data['best_model']
        best_model = model_data['models'][best_model_name]
        
        # Predict
        if hasattr(best_model, 'predict_proba'):
            proba = best_model.predict_proba(X_scaled)[0]
            prediction = 1 if proba[1] > 0.5 else 0
            probability = proba[1]
        else:
            prediction = best_model.predict(X_scaled)[0]
            probability = 0.5
        
        # Determine signal
        confidence = probability * 100
        
        if prediction == 1:
            if confidence > 80:
                signal = SignalType.STRONG_BUY
            elif confidence > 60:
                signal = SignalType.BUY
            else:
                signal = SignalType.NEUTRAL
        else:
            if confidence > 80:
                signal = SignalType.STRONG_SELL
            elif confidence > 60:
                signal = SignalType.SELL
            else:
                signal = SignalType.NEUTRAL
        
        return MLPrediction(
            signal=signal,
            confidence=round(confidence, 1),
            probability=round(float(probability), 3),
            model_version=best_model_name,
            features_used=feature_names[:10]  # Top 10 features
        )
    
    def get_model_info(self, symbol: str, interval: str) -> Optional[Dict]:
        """Get model information"""
        model_key = self._get_model_key(symbol, interval)
        meta_path = self.model_dir / f"{model_key}_meta.json"
        
        if meta_path.exists():
            with open(meta_path, 'r') as f:
                return json.load(f)
        return None
    
    def list_models(self) -> List[Dict]:
        """List all available models"""
        models = []
        for meta_file in self.model_dir.glob("*_meta.json"):
            try:
                with open(meta_file, 'r') as f:
                    data = json.load(f)
                    models.append({
                        'symbol': data['symbol'],
                        'interval': data['interval'],
                        'trained_at': data['trained_at'],
                        'best_model': data['best_model'],
                        'accuracy': data['results'][data['best_model']].get('accuracy', 0)
                    })
            except:
                continue
        return models


# ========================================================================================================
# PRODUCTION EXCHANGE DATA FETCHER
# ========================================================================================================
class ExchangeDataFetcher:
    """Production data fetcher with failover"""
    
    EXCHANGES = [
        {
            "name": "Binance",
            "base_url": "https://api.binance.com/api/v3/klines",
            "symbol_fmt": lambda s: s.replace("/", ""),
            "interval_map": {
                "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
            },
            "timeout": 5
        },
        {
            "name": "Kraken",
            "base_url": "https://api.kraken.com/0/public/OHLC",
            "symbol_fmt": lambda s: s.replace("USDT", "USD"),
            "interval_map": {
                "1m": "1", "5m": "5", "15m": "15", "30m": "30",
                "1h": "60", "4h": "240", "1d": "1440", "1w": "10080"
            },
            "timeout": 8
        }
    ]
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, Dict] = {}
        self.stats: Dict = defaultdict(lambda: {"success": 0, "fail": 0})
    
    async def __aenter__(self):
        timeout = ClientTimeout(total=Config.API_TIMEOUT)
        connector = TCPConnector(limit=50, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    async def get_candles(self, symbol: str, interval: str = "1h", limit: int = 500) -> List[Dict]:
        """Get candles from multiple exchanges"""
        cache_key = f"{symbol}_{interval}"
        
        # Check cache
        if cache_key in self.cache:
            if time.time() - self.cache[cache_key]['timestamp'] < Config.CACHE_TTL:
                return self.cache[cache_key]['data'][-limit:]
        
        # Try exchanges in order
        for exchange in self.EXCHANGES:
            try:
                candles = await self._fetch_exchange(exchange, symbol, interval, limit)
                if candles and len(candles) >= Config.MIN_CANDLES:
                    # Update cache
                    self.cache[cache_key] = {
                        'data': candles,
                        'timestamp': time.time()
                    }
                    self.stats[exchange['name']]['success'] += 1
                    logger.info(f"Got {len(candles)} candles from {exchange['name']}")
                    return candles[-limit:]
                else:
                    self.stats[exchange['name']]['fail'] += 1
            except Exception as e:
                logger.warning(f"{exchange['name']} failed: {e}")
                self.stats[exchange['name']]['fail'] += 1
        
        raise HTTPException(503, "No exchange data available")
    
    async def _fetch_exchange(self, exchange: Dict, symbol: str, interval: str, limit: int) -> Optional[List[Dict]]:
        """Fetch from single exchange"""
        if interval not in exchange['interval_map']:
            return None
        
        params = {
            'symbol': exchange['symbol_fmt'](symbol),
            'interval': exchange['interval_map'][interval],
            'limit': limit
        }
        
        async with self.session.get(
            exchange['base_url'],
            params=params,
            timeout=exchange['timeout']
        ) as response:
            if response.status != 200:
                return None
            
            data = await response.json()
            
            # Parse based on exchange
            candles = []
            if exchange['name'] == 'Binance':
                for item in data:
                    candles.append({
                        'timestamp': int(item[0]),
                        'open': float(item[1]),
                        'high': float(item[2]),
                        'low': float(item[3]),
                        'close': float(item[4]),
                        'volume': float(item[5]),
                        'exchange': 'Binance'
                    })
            elif exchange['name'] == 'Kraken':
                if 'result' in data:
                    for key, items in data['result'].items():
                        if isinstance(items, list):
                            for item in items:
                                candles.append({
                                    'timestamp': int(item[0]) * 1000,
                                    'open': float(item[1]),
                                    'high': float(item[2]),
                                    'low': float(item[3]),
                                    'close': float(item[4]),
                                    'volume': float(item[5]),
                                    'exchange': 'Kraken'
                                })
                            break
            
            return candles if candles else None


# ========================================================================================================
# PRODUCTION FASTAPI APPLICATION
# ========================================================================================================
app = FastAPI(
    title="ICTSMARTPRO ML - Production API",
    description="Professional Crypto Analysis with Machine Learning",
    version="2.0.0"
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware)

# Global instances
data_fetcher = ExchangeDataFetcher()
ml_trainer = MLModelTrainer(model_dir=Config.ML_MODEL_DIR)
startup_time = time.time()


# ========================================================================================================
# PRODUCTION API ENDPOINTS
# ========================================================================================================
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "models_loaded": len(ml_trainer.models),
        "uptime": str(timedelta(seconds=int(time.time() - startup_time)))
    }


@app.get("/api/analyze/{symbol}", response_model=AnalysisResponse)
async def analyze_symbol(
    symbol: str,
    interval: str = Query("1h", regex="^(1m|5m|15m|30m|1h|4h|1d|1w)$"),
    limit: int = Query(500, ge=100, le=1000),
    background_tasks: BackgroundTasks = None
):
    """Analyze symbol with ML model"""
    
    # Format symbol
    symbol = symbol.upper()
    if not symbol.endswith("USDT") and symbol not in ["BTC", "ETH"]:
        symbol = f"{symbol}USDT"
    
    logger.info(f"Analysis request: {symbol} @ {interval}")
    start_time = time.time()
    
    try:
        # Fetch data
        async with data_fetcher as fetcher:
            candles = await fetcher.get_candles(symbol, interval, limit)
        
        if not candles or len(candles) < Config.MIN_CANDLES:
            raise HTTPException(422, f"Insufficient data: {len(candles) if candles else 0} candles")
        
        # Convert to DataFrame
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp').sort_index()
        
        # Check if model exists, if not trigger training in background
        model_info = ml_trainer.get_model_info(symbol, interval)
        
        if not model_info and background_tasks and Config.ML_AUTO_RETRAIN:
            logger.info(f"No model found, scheduling training for {symbol} @ {interval}")
            background_tasks.add_task(
                ml_trainer.train,
                symbol=symbol,
                interval=interval,
                df=df,
                force=False
            )
        
        # Make prediction
        try:
            ml_prediction = await ml_trainer.predict(symbol, interval, df)
        except ValueError as e:
            # Model not found, return fallback
            logger.warning(f"Using fallback: {e}")
            ml_prediction = MLPrediction(
                signal=SignalType.NEUTRAL,
                confidence=50.0,
                probability=0.5,
                model_version="fallback",
                features_used=[]
            )
        
        # Get model info
        model_info = ml_trainer.get_model_info(symbol, interval) or {
            'best_model': 'none',
            'trained_at': 'never',
            'results': {}
        }
        
        # Technical indicators for reference
        last_candle = df.iloc[-1]
        technical = {
            'close': float(last_candle['close']),
            'volume': float(last_candle['volume']),
            'rsi_14': float(df['close'].pct_change().rolling(14).std() * 100)  # Simplified
        }
        
        # Simple patterns (for reference)
        patterns = [
            {
                'name': 'trend',
                'direction': 'bullish' if df['close'].iloc[-1] > df['close'].iloc[-5] else 'bearish',
                'confidence': 60
            }
        ]
        
        response = AnalysisResponse(
            success=True,
            symbol=symbol,
            interval=interval,
            timestamp=datetime.now(timezone.utc).isoformat(),
            price={
                'current': float(last_candle['close']),
                'open': float(last_candle['open']),
                'high': float(last_candle['high']),
                'low': float(last_candle['low']),
                'volume': float(last_candle['volume']),
                'change': float((last_candle['close'] / df.iloc[-5]['close'] - 1) * 100)
            },
            ml_prediction=ml_prediction,
            technical=technical,
            patterns=patterns,
            data_points=len(df),
            model_info={
                'best_model': model_info.get('best_model', 'none'),
                'trained_at': model_info.get('trained_at', 'never'),
                'accuracy': model_info.get('results', {}).get(model_info.get('best_model', ''), {}).get('accuracy', 0)
            },
            performance_ms=round((time.time() - start_time) * 1000, 2)
        )
        
        logger.info(f"Analysis complete: {ml_prediction.signal.value} ({ml_prediction.confidence:.1f}%)")
        return response
        
    except Exception as e:
        logger.exception(f"Analysis failed: {e}")
        raise HTTPException(500, f"Analysis failed: {str(e)[:200]}")


@app.post("/api/train/{symbol}")
async def train_model(
    symbol: str,
    interval: str = Query("1h", regex="^(1m|5m|15m|30m|1h|4h|1d|1w)$"),
    force: bool = False,
    background_tasks: BackgroundTasks = None
):
    """Train ML model for symbol"""
    
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    
    logger.info(f"Training request: {symbol} @ {interval}")
    
    try:
        # Fetch data
        async with data_fetcher as fetcher:
            candles = await fetcher.get_candles(symbol, interval, 1000)
        
        if not candles or len(candles) < Config.ML_MIN_TRAINING_SAMPLES:
            raise HTTPException(422, f"Insufficient data for training: {len(candles) if candles else 0}")
        
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp').sort_index()
        
        # Train in background if requested
        if background_tasks:
            background_tasks.add_task(
                ml_trainer.train,
                symbol=symbol,
                interval=interval,
                df=df,
                force=force
            )
            return {
                "success": True,
                "message": f"Training started for {symbol} @ {interval}",
                "symbol": symbol,
                "interval": interval
            }
        else:
            # Train synchronously
            result = await ml_trainer.train(symbol, interval, df, force=force)
            return {
                "success": True,
                "message": f"Training completed for {symbol} @ {interval}",
                "symbol": symbol,
                "interval": interval,
                "result": result
            }
            
    except Exception as e:
        logger.error(f"Training failed: {e}")
        raise HTTPException(500, f"Training failed: {str(e)[:200]}")


@app.get("/api/models")
async def list_models():
    """List all trained models"""
    models = ml_trainer.list_models()
    return {
        "success": True,
        "count": len(models),
        "models": models
    }


@app.get("/api/model/{symbol}")
async def get_model_info(
    symbol: str,
    interval: str = Query("1h", regex="^(1m|5m|15m|30m|1h|4h|1d|1w)$")
):
    """Get model information"""
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    
    model_info = ml_trainer.get_model_info(symbol, interval)
    
    if not model_info:
        raise HTTPException(404, f"No model found for {symbol} @ {interval}")
    
    return {
        "success": True,
        "symbol": symbol,
        "interval": interval,
        "model_info": model_info
    }


# ========================================================================================================
# STARTUP
# ========================================================================================================
@app.on_event("startup")
async def startup():
    logger.info("=" * 60)
    logger.info("🚀 ICTSMARTPRO ML Production API Starting")
    logger.info("=" * 60)
    logger.info(f"Environment: {Config.ENV}")
    logger.info(f"Models loaded: {len(ml_trainer.models)}")
    logger.info(f"Model directory: {Config.ML_MODEL_DIR}")
    logger.info(f"Auto-retrain: {Config.ML_AUTO_RETRAIN}")
    logger.info("=" * 60)


# ========================================================================================================
# MAIN
# ========================================================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=Config.PORT,
        reload=Config.DEBUG,
        log_level="info"
    )
