"""
ICTSmartPro Trading AI Platform
Production-Ready Trading Analysis with Qwen AI + XGBoost & LSTM ML
Version: 5.4.0 - 2026 February - Dual ML Models (XGBoost + LSTM)
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import re
import joblib
import numpy as np
import pandas as pd
import pandas_ta_classic as ta
from xgboost import XGBRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_absolute_error
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.callbacks import EarlyStopping
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel, Field
import yfinance as yf
import httpx
from dotenv import load_dotenv

# ==================== KONFIGÜRASYON ====================
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen/qwen3-coder:free")

RATE_LIMIT_PER_MINUTE = 15
RATE_LIMIT_PER_HOUR = 150

SUPPORTED_INTERVALS = {
    "1m": {"yf": "1m", "label": "1 Dakika", "max_days": 7},
    "5m": {"yf": "5m", "label": "5 Dakika", "max_days": 60},
    "15m": {"yf": "15m", "label": "15 Dakika", "max_days": 60},
    "30m": {"yf": "30m", "label": "30 Dakika", "max_days": 60},
    "1h": {"yf": "1h", "label": "1 Saat", "max_days": None},
    "1d": {"yf": "1d", "label": "1 Gün", "max_days": None},
    "1wk": {"yf": "1wk", "label": "1 Hafta", "max_days": None},
}

ALLOWED_PERIODS = list(SUPPORTED_INTERVALS.keys())

# ==================== APP & LIMITER ====================
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="ICTSmartPro Trading AI", version="5.4.0")
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Çok fazla istek."})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if DEBUG else ["https://ictsmartpro.ai"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== CACHE ====================
class SimpleCache:
    def __init__(self, ttl: int = 300):
        self.data = {}
        self.ttl = ttl

    def get(self, key: str) -> Optional[Dict]:
        if key in self.data:
            v, ts = self.data[key]
            if datetime.now() - ts < timedelta(seconds=self.ttl):
                return v
            del self.data[key]
        return None

    def set(self, key: str, value: Dict):
        self.data[key] = (value, datetime.now())

finance_cache = SimpleCache(300)
ml_cache = SimpleCache(1800)

# ==================== QWEN ====================
async def call_qwen(messages: list, temperature: float = 0.65, max_tokens: int = 1400) -> str:
    if not OPENROUTER_API_KEY:
        return "❌ API anahtarı eksik."

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://ictsmartpro.ai",
        "X-Title": "ICTSmartPro Trading AI",
        "Content-Type": "application/json"
    }

    payload = {
        "model": QWEN_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }

    async with httpx.AsyncClient(timeout=75.0) as client:
        try:
            r = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Qwen error: {e}")
            return "❌ AI servisi hatası."

# ==================== FİNANS VERİ ====================
async def get_finance_data(symbol: str, interval_key: str = "1d") -> Dict:
    cache_key = f"fin_{symbol}_{interval_key}"
    if cached := finance_cache.get(cache_key):
        return cached

    try:
        cfg = SUPPORTED_INTERVALS.get(interval_key, SUPPORTED_INTERVALS["1d"])
        yf_int = cfg["yf"]
        period = "60d" if cfg.get("max_days") else "max"

        symbol = symbol.upper().strip()
        if symbol in ["THYAO", "AKBNK", "GARAN", "ISCTR", "EREGL", "SISE", "KCHOL", "ASELS"]:
            symbol += ".IS"

        ticker = yf.Ticker(symbol)
        hist = ticker.history(interval=yf_int, period=period)

        if hist.empty:
            raise ValueError("Veri bulunamadı")

        result = {
            "symbol": symbol.replace(".IS", ""),
            "name": ticker.info.get("longName") or symbol,
            "currency": ticker.info.get("currency", "TRY" if ".IS" in symbol else "USD"),
            "current_price": round(float(hist["Close"].iloc[-1]), 2),
            "change_percent": round(((hist["Close"].iloc[-1] - hist["Close"].iloc[-2]) / hist["Close"].iloc[-2] * 100) if len(hist) > 1 else 0, 2),
            "volume": int(hist["Volume"].iloc[-1]),
            "historical_data": {
                "dates": hist.index.strftime("%Y-%m-%d %H:%M").tolist(),
                "prices": hist["Close"].round(2).tolist(),
                "highs": hist["High"].round(2).tolist(),
                "lows": hist["Low"].round(2).tolist(),
                "volumes": hist["Volume"].tolist()
            }
        }

        finance_cache.set(cache_key, result)
        return result

    except Exception as e:
        logger.error(f"Finance error {symbol}: {e}")
        return {"error": str(e)}

# ==================== ML MANAGER (XGBoost + LSTM) ====================
class MLManager:
    def __init__(self):
        self.xgb_path = "xgb_model.pkl"
        self.lstm_path = "lstm_model.h5"
        self.scaler_path = "scaler.pkl"
        self.xgb_model = None
        self.lstm_model = None
        self.scaler = None
        self.trained_at = None
        self.mae_xgb = None
        self.mae_lstm = None
        self._load_models()

    def _load_models(self):
        if os.path.exists(self.xgb_path):
            self.xgb_model = joblib.load(self.xgb_path)
        if os.path.exists(self.lstm_path):
            self.lstm_model = load_model(self.lstm_path)
        if os.path.exists(self.scaler_path):
            self.scaler = joblib.load(self.scaler_path)

    async def train(self, symbol: str = "AAPL", period: str = "2y"):
        data = await get_finance_data(symbol, "1d")
        if "error" in data:
            return {"error": data["error"]}

        df = pd.DataFrame({
            "Close": data["historical_data"]["prices"]
        }, index=pd.to_datetime(data["historical_data"]["dates"]))

        # Özellikler
        df["rsi_14"] = ta.rsi(df["Close"], 14)
        df["macd"] = ta.macd(df["Close"])["MACD_12_26_9"]
        df["sma_20"] = ta.sma(df["Close"], 20)
        df["atr_14"] = ta.atr(df["High"], df["Low"], df["Close"], 14) if "High" in data["historical_data"] else 0
        df["volatility"] = df["Close"].rolling(20).std()
        df = df.dropna()

        if len(df) < 100:
            return {"error": "Yeterli veri yok"}

        df["target"] = df["Close"].shift(-5)
        df = df.dropna()

        # XGBoost
        X = df[["rsi_14", "macd", "sma_20", "atr_14", "volatility"]]
        y = df["target"]
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

        xgb = XGBRegressor(n_estimators=100, learning_rate=0.1, random_state=42)
        xgb.fit(X_train, y_train)
        self.mae_xgb = mean_absolute_error(y_test, xgb.predict(X_test))

        joblib.dump(xgb, self.xgb_path)
        self.xgb_model = xgb

        # LSTM
        scaler = MinMaxScaler()
        scaled = scaler.fit_transform(df[["Close"]])

        seq_length = 60
        X_lstm, y_lstm = [], []
        for i in range(seq_length, len(scaled)-5):
            X_lstm.append(scaled[i-seq_length:i])
            y_lstm.append(scaled[i+5-1])  # 5 gün sonrası

        X_lstm, y_lstm = np.array(X_lstm), np.array(y_lstm)

        if len(X_lstm) < 10:
            return {"error": "LSTM için yeterli veri yok"}

        split = int(0.8 * len(X_lstm))
        X_train_l, X_test_l = X_lstm[:split], X_lstm[split:]
        y_train_l, y_test_l = y_lstm[:split], y_lstm[split:]

        lstm = Sequential([
            LSTM(50, return_sequences=True, input_shape=(seq_length, 1)),
            Dropout(0.2),
            LSTM(50),
            Dropout(0.2),
            Dense(1)
        ])
        lstm.compile(optimizer='adam', loss='mse')
        lstm.fit(X_train_l, y_train_l, epochs=20, batch_size=32, validation_split=0.1, verbose=0,
                 callbacks=[EarlyStopping(patience=5)])

        preds_l = lstm.predict(X_test_l)
        self.mae_lstm = mean_absolute_error(y_test_l, preds_l)

        lstm.save(self.lstm_path)
        joblib.dump(scaler, self.scaler_path)
        self.lstm_model = lstm
        self.scaler = scaler

        self.trained_at = datetime.now().isoformat()
        logger.info(f"Modeller eğitildi - XGBoost MAE: {self.mae_xgb:.2f}, LSTM MAE: {self.mae_lstm:.4f}")

        return {"status": "eğitildi", "xgb_mae": self.mae_xgb, "lstm_mae": self.mae_lstm}

    async def predict(self, symbol: str, horizon: int = 5) -> Dict:
        cache_key = f"pred_{symbol}_{horizon}"
        if cached := ml_cache.get(cache_key):
            return cached

        data = await get_finance_data(symbol, "6mo")
        if "error" in data:
            return data

        df = pd.DataFrame({
            "Close": data["historical_data"]["prices"]
        }, index=pd.to_datetime(data["historical_data"]["dates"]))

        results = {"current_price": round(float(df["Close"].iloc[-1]), 2)}

        # XGBoost tahmini
        if self.xgb_model:
            df["rsi_14"] = ta.rsi(df["Close"], 14)
            df["macd"] = ta.macd(df["Close"])["MACD_12_26_9"]
            df["sma_20"] = ta.sma(df["Close"], 20)
            df["atr_14"] = ta.atr(df["High"], df["Low"], df["Close"], 14) if "High" in data["historical_data"] else 0
            df["volatility"] = df["Close"].rolling(20).std()
            df = df.dropna()

            if len(df) >= 20:
                last_x = df[["rsi_14", "macd", "sma_20", "atr_14", "volatility"]].iloc[-1:].values
                pred_xgb = self.xgb_model.predict(last_x)[0]
                results["xgb_pred"] = round(float(pred_xgb), 2)
                results["xgb_direction"] = "↑" if pred_xgb > results["current_price"] else "↓"

        # LSTM tahmini
        if self.lstm_model and self.scaler:
            scaled = self.scaler.transform(df[["Close"]])
            if len(scaled) >= 60:
                seq = scaled[-60:].reshape(1, 60, 1)
                pred_lstm_scaled = self.lstm_model.predict(seq, verbose=0)
                pred_lstm = self.scaler.inverse_transform(pred_lstm_scaled)[0][0]
                results["lstm_pred"] = round(float(pred_lstm), 2)
                results["lstm_direction"] = "↑" if pred_lstm > results["current_price"] else "↓"

        results["note"] = "XGBoost & LSTM tahminleri – yatırım tavsiyesi değildir"
        results["trained_at"] = self.trained_at

        ml_cache.set(cache_key, results)
        return results

ml_manager = MLManager()

# ==================== MODELS ====================
class AIRequest(BaseModel):
    message: str = Field(..., min_length=5, max_length=1200)

# ==================== ROUTES ====================
@app.get("/")
async def home():
    html_content = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ICTSmartPro Trading AI</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:1.5rem;}
        .container{max-width:1200px;margin:0 auto;}
        header{text-align:center;padding:2rem;background:linear-gradient(90deg,#6366f1,#8b5cf6);border-radius:16px;}
        .logo{font-size:3rem;font-weight:900;background:linear-gradient(45deg,#fbbf24,#f97316);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
        .dashboard{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;}
        .card{background:rgba(30,41,59,0.7);border-radius:16px;padding:1.5rem;}
        select,textarea{width:100%;padding:0.8rem;border-radius:8px;background:#1e293b;color:white;border:1px solid #475569;}
        button{background:linear-gradient(90deg,#10b981,#3b82f6);color:white;border:none;padding:0.9rem;border-radius:10px;cursor:pointer;width:100%;margin-top:1rem;}
        .result{margin-top:1rem;padding:1rem;background:rgba(255,255,255,0.04);border-radius:10px;}
        .loading{text-align:center;color:#60a5fa;}
        .error{color:#ef4444;}
        .chart-container{height:340px;margin-top:1.5rem;}
    </style>
</head>
<body>
<div class="container">
    <header>
        <div class="logo">ICTSmartPro AI</div>
    </header>
    <div class="dashboard">
        <div class="card">
            <h2>📈 Hisse Analizi</h2>
            <label>Sembol:</label>
            <select id="symbol">
                <option value="THYAO">THYAO</option>
                <option value="AKBNK">AKBNK</option>
                <option value="GARAN">GARAN</option>
                <option value="AAPL">AAPL</option>
                <option value="NVDA">NVDA</option>
            </select>

            <label>Zaman Dilimi:</label>
            <select id="interval">
                <option value="1m">1 Dakika</option>
                <option value="5m">5 Dakika</option>
                <option value="15m">15 Dakika</option>
                <option value="1d" selected>1 Gün</option>
                <option value="1wk">1 Hafta</option>
            </select>

            <button id="analyzeBtn">Analiz Et</button>
            <div id="financeResult" class="result loading">Seçip Analiz Et'e basın...</div>
        </div>

        <div class="card">
            <h2>🤖 Qwen AI</h2>
            <textarea id="aiQuery" rows="5" placeholder="Soru yazın..."></textarea>
            <button id="askBtn">Sor</button>
            <div id="aiResult" class="result loading">Bekleniyor...</div>
        </div>
    </div>

    <div class="card" style="margin-top:2rem;">
        <h2>📊 Grafik</h2>
        <div class="chart-container"><canvas id="priceChart"></canvas></div>
    </div>
</div>

<script>
    let chart = null;

    async function analyze() {
        const symbol = document.getElementById('symbol').value;
        const interval = document.getElementById('interval').value;
        const div = document.getElementById('financeResult');
        div.className = 'result loading';
        div.innerHTML = '<div class="loading">Yükleniyor...</div>';

        try {
            const r = await fetch(`/api/finance/${encodeURIComponent(symbol)}?interval=${interval}`);
            const d = await r.json();
            if (d.error) throw new Error(d.error);

            let h = `<strong>${d.symbol} - ${d.name}</strong><br>`;
            h += `Fiyat: ${d.current_price} ${d.currency}<br>`;
            h += `Değişim: <span class="${d.change_percent >= 0 ? 'positive' : 'negative'}">${d.change_percent.toFixed(2)}%</span><br>`;

            div.className = 'result';
            div.innerHTML = h;

            if (d.historical_data?.prices?.length > 0) {
                const ctx = document.getElementById('priceChart').getContext('2d');
                if (chart) chart.destroy();
                chart = new Chart(ctx, {
                    type: 'line',
                    data: {labels:d.historical_data.dates, datasets:[{label:symbol,data:d.historical_data.prices,borderColor:'#3b82f6',fill:true}]},
                    options: {responsive:true}
                });
            }
        } catch(e) {
            div.className = 'result error';
            div.innerHTML = `Hata: ${e.message}`;
        }
    }

    async function ask() {
        const q = document.getElementById('aiQuery').value.trim();
        if (!q) return;
        const div = document.getElementById('aiResult');
        div.innerHTML = '<div class="loading">Analiz...</div>';

        try {
            const r = await fetch('/api/ai/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:q})});
            const d = await r.json();
            div.innerHTML = d.reply.replace(/\n/g,'<br>');
        } catch(e) {
            div.innerHTML = `Hata: ${e.message}`;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('analyzeBtn').onclick = analyze;
        document.getElementById('askBtn').onclick = ask;
        analyze();
    });
</script>
</body>
</html>"""
    return HTMLResponse(html)

@app.get("/api/train_ml")
async def train_ml(symbol: str = "AAPL"):
    result = await ml_manager.train(symbol)
    return result

@app.get("/api/finance/{symbol}")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def finance(symbol: str, interval: str = "1d", request: Request = None):
    if interval not in ALLOWED_PERIODS:
        raise HTTPException(400, "Geçersiz interval")
    data = await get_finance_data(symbol, interval)
    if "error" in data:
        raise HTTPException(400, data["error"])
    return data

@app.get("/api/predict/{symbol}")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def predict(symbol: str, request: Request = None):
    data = await ml_manager.predict(symbol)
    if "error" in data:
        raise HTTPException(400, data["error"])
    return data

@app.post("/api/ai/ask")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def ask_ai(body: AIRequest, request: Request = None):
    msg = body.message
    symbol_match = re.search(r'\b([A-Z]{3,5}(\.[A-Z]{2})?)\b', msg.upper())
    symbol = symbol_match.group(1) if symbol_match else "THYAO"

    ml = await ml_manager.predict(symbol)
    ml_text = ""
    if "error" not in ml:
        ml_text = f"""
XGBoost Tahmini: {ml.get('xgb_pred', 'N/A')} ({ml.get('xgb_direction', '')})
LSTM Tahmini: {ml.get('lstm_pred', 'N/A')} ({ml.get('lstm_direction', '')})
Mevcut: {ml['current_price']}
"""

    system = "Deneyimli borsa analisti olarak kısa, gerçekçi Türkçe cevap ver. Teknik analiz yap, risk belirt. ML tahminlerini değerlendir."

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{msg}\n\n{ml_text}"}
    ]

    reply = await call_qwen(messages)
    return {"reply": reply}

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "5.4.0",
        "qwen_configured": bool(OPENROUTER_API_KEY),
        "ml_models_loaded": {
            "xgboost": ml_manager.xgb_model is not None,
            "lstm": ml_manager.lstm_model is not None
        },
        "trained_at": ml_manager.trained_at,
        "mae_xgb": ml_manager.mae_xgb,
        "mae_lstm": ml_manager.mae_lstm,
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=DEBUG)
