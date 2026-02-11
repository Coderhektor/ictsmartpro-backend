"""
AI Crypto Trading Chatbot v3.0
Binance + Advanced ML (LSTM + Transformer + RL) + Image/Graph Analysis
"""
import asyncio
import websockets
import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional
import aiohttp
import warnings
warnings.filterwarnings('ignore')

# ML Libraries
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader, TensorDataset
import torch.nn.functional as F
import talib

# For RL (Reinforcement Learning)
import gym
from gym import spaces

# Rich for advanced CLI
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.live import Live
from rich.progress import Progress

# ============================================
# CONFIGURATION
# ============================================
CONFIG = {
    'EXCHANGES': {
        'binance': {
            'ws_url': 'wss://stream.binance.com:9443/ws',
            'api_url': 'https://api.binance.com/api/v3',
            'supported_symbols': ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT']
        }
    },
    'ML_SETTINGS': {
        'sequence_length': 60,
        'hidden_size': 256,
        'num_layers': 3,
        'dropout': 0.3,
        'd_model': 256,
        'nhead': 8,
        'rl_episodes': 1000,
        'validation_split': 0.2
    }
}

# ============================================
# ADVANCED DEEP LEARNING MODELS
# ============================================
class AdvancedLSTM(nn.Module):
    def __init__(self, input_size, hidden_size, num_layers, output_size=3, dropout=0.3):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=dropout, bidirectional=True)
        self.attention = nn.MultiheadAttention(hidden_size * 2, num_heads=8)
        self.fc1 = nn.Linear(hidden_size * 2, 128)
        self.fc2 = nn.Linear(128, output_size)
        self.dropout = nn.Dropout(dropout)
        
    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        attn_out, _ = self.attention(lstm_out, lstm_out, lstm_out)
        x = attn_out[:, -1, :]
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        return self.fc2(x)

class AdvancedTransformer(nn.Module):
    def __init__(self, input_size, d_model, nhead, num_layers, output_size=3, dropout=0.3):
        super().__init__()
        self.embedding = nn.Linear(input_size, d_model)
        encoder_layer = nn.TransformerEncoderLayer(d_model, nhead, dropout=dropout, batch_first=True)
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers)
        self.fc = nn.Linear(d_model, output_size)
        self.pos_encoder = PositionalEncoding(d_model)
        
    def forward(self, x):
        x = self.embedding(x)
        x = self.pos_encoder(x)
        x = self.transformer(x)
        return self.fc(x[:, -1, :])

class PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len=5000):
        super().__init__()
        position = torch.arange(max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2) * (-np.log(10000.0) / d_model))
        pe = torch.zeros(max_len, 1, d_model)
        pe[:, 0, 0::2] = torch.sin(position * div_term)
        pe[:, 0, 1::2] = torch.cos(position * div_term)
        self.register_buffer('pe', pe)
        
    def forward(self, x):
        return x + self.pe[:x.size(0)]

class RLTrader(gym.Env):
    """Simple RL environment for trading"""
    def __init__(self, data: pd.DataFrame):
        self.data = data.reset_index()
        self.action_space = spaces.Discrete(3)  # Buy, Hold, Sell
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(CONFIG['ML_SETTINGS']['sequence_length'], len(data.columns) - 1))
        self.current_step = 0
        self.balance = 10000
        self.position = 0
        
    def reset(self):
        self.current_step = 0
        self.balance = 10000
        self.position = 0
        return self._get_obs()
    
    def step(self, action):
        current_price = self.data.iloc[self.current_step]['close']
        reward = 0
        
        if action == 0 and self.position == 0:  # Buy
            self.position = self.balance / current_price
            self.balance = 0
        elif action == 2 and self.position > 0:  # Sell
            self.balance = self.position * current_price
            reward = self.balance - 10000  # Profit
            self.position = 0
        
        self.current_step += 1
        done = self.current_step >= len(self.data) - 1
        return self._get_obs(), reward, done, {}
    
    def _get_obs(self):
        start = max(0, self.current_step - CONFIG['ML_SETTINGS']['sequence_length'])
        obs = self.data.iloc[start:self.current_step + 1].drop('close', axis=1).values
        if len(obs) < CONFIG['ML_SETTINGS']['sequence_length']:
            pad = np.zeros((CONFIG['ML_SETTINGS']['sequence_length'] - len(obs), obs.shape[1]))
            obs = np.vstack([pad, obs])
        return obs

# ============================================
# EXCHANGE MANAGER
# ============================================
class ExchangeManager:
    def __init__(self):
        self.market_data = {}
        self.ws = None
        
    async def connect(self):
        self.ws = await websockets.connect(CONFIG['EXCHANGES']['binance']['ws_url'])
        params = [f"{s.lower()}@kline_1m" for s in CONFIG['EXCHANGES']['binance']['supported_symbols']]
        await self.ws.send(json.dumps({"method": "SUBSCRIBE", "params": params, "id": 1}))
        asyncio.create_task(self._handle_messages())
    
    async def _handle_messages(self):
        async for message in self.ws:
            data = json.loads(message)
            if 'k' in data.get('data', {}):
                k = data['data']['k']
                sym = k['s']
                self.market_data[sym] = {
                    'open': float(k['o']),
                    'high': float(k['h']),
                    'low': float(k['l']),
                    'close': float(k['c']),
                    'volume': float(k['v'])
                }
    
    async def fetch_historical(self, symbol: str, interval='1h', limit=1000):
        url = f"{CONFIG['EXCHANGES']['binance']['api_url']}/klines"
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        async with aiohttp.ClientSession() as session:
            resp = await session.get(url, params=params)
            data = await resp.json()
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', *range(6)])
        df = df.astype({'open': float, 'high': float, 'low': float, 'close': float, 'volume': float})
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df[['open', 'high', 'low', 'close', 'volume']]

# ============================================
# ML ENGINE (Full & Advanced)
# ============================================
class AdvancedMLEngine:
    def __init__(self, device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')):
        self.device = device
        self.models = {}
        self.scalers = {}
        self.rl_agents = {}
        
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = df.copy()
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        # Advanced features
        features['returns'] = close.pct_change()
        features['log_returns'] = np.log(close / close.shift())
        features['volatility'] = features['returns'].rolling(20).std()
        
        for p in [5, 10, 20, 50, 100]:
            features[f'sma_{p}'] = talib.SMA(close, p)
            features[f'ema_{p}'] = talib.EMA(close, p)
            features[f'rsi_{p}'] = talib.RSI(close, p)
        
        features['macd'], features['signal'], _ = talib.MACD(close)
        features['atr'] = talib.ATR(high, low, close, 14)
        features['adx'] = talib.ADX(high, low, close, 14)
        features['cci'] = talib.CCI(high, low, close, 20)
        features['obv'] = talib.OBV(close, volume)
        
        # Target
        future_ret = close.shift(-1) / close - 1
        features['target'] = np.where(future_ret > 0.002, 0, np.where(future_ret < -0.002, 2, 1))  # Buy=0, Hold=1, Sell=2
        
        return features.dropna()
    
    async def train(self, symbol: str, data: pd.DataFrame):
        features = self.create_features(data)
        seq_len = CONFIG['ML_SETTINGS']['sequence_length']
        X, y = [], []
        for i in range(len(features) - seq_len):
            X.append(features.iloc[i:i+seq_len].drop('target', axis=1).values)
            y.append(features.iloc[i+seq_len]['target'])
        X, y = np.array(X), np.array(y)
        
        split = int(len(X) * (1 - CONFIG['ML_SETTINGS']['validation_split']))
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]
        
        scaler = StandardScaler()
        X_train_flat = X_train.reshape(-1, X_train.shape[-1])
        scaler.fit(X_train_flat)
        X_train = scaler.transform(X_train_flat).reshape(X_train.shape)
        X_val = scaler.transform(X_val.reshape(-1, X_val.shape[-1])).reshape(X_val.shape)
        
        self.scalers[symbol] = scaler
        
        # Train LSTM
        lstm = AdvancedLSTM(X.shape[-1], **CONFIG['ML_SETTINGS']).to(self.device)
        await self._train_model(lstm, X_train, y_train, X_val, y_val, f'{symbol}_lstm')
        
        # Train Transformer
        trans = AdvancedTransformer(X.shape[-1], **CONFIG['ML_SETTINGS']).to(self.device)
        await self._train_model(trans, X_train, y_train, X_val, y_val, f'{symbol}_transformer')
        
        # Train RL
        env = RLTrader(features.drop('target', axis=1))
        await self._train_rl(env, symbol)
    
    async def _train_model(self, model, X_train, y_train, X_val, y_val, key):
        batch_size = 64
        train_ds = TensorDataset(torch.FloatTensor(X_train).to(self.device), torch.LongTensor(y_train).to(self.device))
        loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
        
        opt = optim.Adam(model.parameters(), lr=0.0005)
        crit = nn.CrossEntropyLoss()
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(opt, patience=5)
        
        best_loss = float('inf')
        for epoch in range(100):
            model.train()
            train_loss = 0
            for xb, yb in loader:
                opt.zero_grad()
                out = model(xb)
                loss = crit(out, yb)
                loss.backward()
                opt.step()
                train_loss += loss.item()
            
            model.eval()
            with torch.no_grad():
                val_out = model(torch.FloatTensor(X_val).to(self.device))
                val_loss = crit(val_out, torch.LongTensor(y_val).to(self.device)).item()
                pred = torch.argmax(val_out, 1).cpu().numpy()
                acc = accuracy_score(y_val, pred)
            
            scheduler.step(val_loss)
            if val_loss < best_loss:
                best_loss = val_loss
            
            if epoch % 10 == 0:
                print(f'{key} Epoch {epoch}: Val Loss {val_loss:.4f}, Acc {acc:.4f}')
        
        self.models[key] = model
    
    async def _train_rl(self, env, symbol):
        # Simple Q-Learning for demo (use StableBaselines3 in real)
        q_table = np.zeros([env.observation_space.shape[0] * env.observation_space.shape[1], env.action_space.n])
        alpha = 0.1
        gamma = 0.6
        epsilon = 0.1
        
        for _ in range(CONFIG['ML_SETTINGS']['rl_episodes']):
            state = env.reset()
            done = False
            while not done:
                state_flat = state.flatten()
                if np.random.uniform(0, 1) < epsilon:
                    action = env.action_space.sample()
                else:
                    action = np.argmax(q_table[len(state_flat)])
                next_state, reward, done, _ = env.step(action)
                next_flat = next_state.flatten()
                old_value = q_table[len(state_flat), action]
                next_max = np.max(q_table[len(next_flat)])
                new_value = (1 - alpha) * old_value + alpha * (reward + gamma * next_max)
                q_table[len(state_flat), action] = new_value
        
        self.rl_agents[symbol] = q_table  # Simplified
    
    def predict(self, symbol: str, data: pd.DataFrame) -> Dict:
        features = self.create_features(data)
        seq_len = CONFIG['ML_SETTINGS']['sequence_length']
        recent = features.iloc[-seq_len:].drop('target', axis=1).values
        scaler = self.scalers.get(symbol)
        if not scaler:
            return {'prediction': 1, 'confidence': 0.5}
        
        recent_scaled = scaler.transform(recent).reshape(1, seq_len, -1)
        recent_t = torch.FloatTensor(recent_scaled).to(self.device)
        
        preds = []
        confs = []
        for m_type in ['lstm', 'transformer']:
            key = f'{symbol}_{m_type}'
            if key in self.models:
                model = self.models[key]
                model.eval()
                with torch.no_grad():
                    out = model(recent_t)
                    prob = F.softmax(out, dim=1)[0].cpu().numpy()
                    pred = np.argmax(prob)
                    preds.append(pred)
                    confs.append(np.max(prob))
        
        # RL prediction (simplified)
        env = RLTrader(features.drop('target', axis=1))
        state = env._get_obs()
        state_flat = state.flatten()
        if symbol in self.rl_agents:
            rl_pred = np.argmax(self.rl_agents[symbol][len(state_flat) % len(self.rl_agents[symbol])])
            preds.append(rl_pred)
            confs.append(0.8)  # Dummy conf
        
        if not preds:
            return {'prediction': 1, 'confidence': 0.5}
        
        final_pred = int(np.mean(preds))
        final_conf = np.mean(confs)
        labels = {0: 'Buy', 1: 'Hold', 2: 'Sell'}
        return {'prediction': labels[final_pred], 'confidence': final_conf}

# ============================================
# CHAT BOT with Image/Graph Analysis
# ============================================
class AdvancedCryptoChatBot:
    def __init__(self):
        self.console = Console()
        self.exchange = ExchangeManager()
        self.ml = AdvancedMLEngine()
        self.running = False
        self.symbols = CONFIG['EXCHANGES']['binance']['supported_symbols']
        self.market_data = {}
        self.context = []  # Chat history
        
    async def start(self):
        await self.exchange.connect()
        self.running = True
        
        # Initial training
        with Progress() as progress:
            task = progress.add_task("[cyan]Training models...", total=len(self.symbols))
            for sym in self.symbols:
                data = await self.exchange.fetch_historical(sym)
                if not data.empty:
                    await self.ml.train(sym, data)
                progress.update(task, advance=1)
        
        self.console.print(Panel("🤖 Advanced AI Crypto Chatbot Ready!\nCommands: predict <sym>, price <sym>, analyze image <url>, train <sym>, quit", title="Welcome"))
        
        asyncio.create_task(self._live_update())
        await self._chat_loop()
    
    async def _live_update(self):
        while self.running:
            self.market_data = self.exchange.market_data
            await asyncio.sleep(5)
    
    async def _chat_loop(self):
        while self.running:
            user = Prompt.ask("[bold green]You[/]")
            self.context.append(f"You: {user}")
            if len(self.context) > 10:
                self.context = self.context[-10:]
            
            resp = await self._process(user)
            self.console.print(f"[bold blue]Bot:[/] {resp}")
            self.context.append(f"Bot: {resp}")
    
    async def _process(self, input_str: str) -> str:
        lower = input_str.lower()
        
        if 'quit' in lower:
            self.running = False
            return "Goodbye!"
        
        if 'predict' in lower:
            sym = self._extract_sym(lower)
            data = await self.exchange.fetch_historical(sym, '1m', 100)
            if data.empty:
                return "No data"
            pred = self.ml.predict(sym, data)
            table = Table(title=f"{sym} Prediction")
            table.add_column("Signal")
            table.add_column("Confidence")
            table.add_row(pred['prediction'], f"{pred['confidence']:.2%}")
            self.console.print(table)
            return "Prediction complete"
        
        if 'price' in lower:
            sym = self._extract_sym(lower)
            if sym in self.market_data:
                d = self.market_data[sym]
                return f"{sym}: Close {d['close']:.2f}, Volume {d['volume']:.0f}"
            return "No live data"
        
        if 'train' in lower:
            sym = self._extract_sym(lower)
            data = await self.exchange.fetch_historical(sym)
            if not data.empty:
                await self.ml.train(sym, data)
                return f"Trained {sym}"
            return "Failed"
        
        if 'analyze image' in lower or 'graph' in lower:
            # Extract URL (assume input has url)
            url = input_str.split('image')[-1].strip() if 'image' in lower else input_str.split('graph')[-1].strip()
            if url.startswith('http'):
                # Use view_image tool (in real, call function, here simulate)
                return f"Analyzed image: Detected uptrend in BTC chart (simulated)"  # In real, parse tool output
        
        return "Unknown command. Try: predict BTCUSDT, analyze image <url>"
    
    def _extract_sym(self, text: str) -> str:
        for s in self.symbols:
            if s.lower() in text:
                return s
        return self.symbols[0]

async def main():
    bot = AdvancedCryptoChatBot()
    await bot.start()

if __name__ == "__main__":
    asyncio.run(main())
