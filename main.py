from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import yfinance as yf
import logging
import os
from datetime import datetime
from typing import Dict, List
import httpx
from dotenv import load_dotenv
import pandas as pd
import pandas_ta as ta
from xgboost import XGBRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
import re  # sembol çıkarma için

# ==================== KONFIGÜRASYON ====================
load_dotenv()

PORT = int(os.environ.get("PORT", 8000))
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
QWEN_MODEL = "qwen/qwen3-coder:free"

if not OPENROUTER_API_KEY:
    print("⚠️ OPENROUTER_API_KEY tanımlı değil!")

logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ICTSmartPro × Qwen Trading Analiz",
    description="Qwen AI + ML ile Hisse Analizi",
    version="3.3.0",
    docs_url="/docs" if DEBUG else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== QWEN ÇAĞIRMA ====================
async def call_qwen(messages: List[Dict[str, str]], temperature: float = 0.65, max_tokens: int = 1400) -> str:
    if not OPENROUTER_API_KEY:
        return "❌ OpenRouter API anahtarı eksik."

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://your-railway-app.up.railway.app",
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

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=90.0
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Qwen hatası: {e}")
            if "429" in str(e):
                return "❌ Rate limit aşıldı. Biraz bekleyin."
            return f"AI hatası: {str(e)}"

# ==================== FİNANS VERİ (High/Low/Volume eklendi) ====================
async def get_finance_data(symbol: str, period: str = "1mo") -> Dict:
    try:
        symbol = symbol.upper().strip()
        if symbol.startswith("BIST:"):
            symbol = symbol.replace("BIST:", "") + ".IS"

        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)

        if hist.empty and not symbol.endswith(".IS"):
            symbol += ".IS"
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period)

        if hist.empty:
            raise ValueError("Veri bulunamadı")

        current = float(hist["Close"].iloc[-1])
        previous = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current
        change = current - previous
        change_pct = (change / previous * 100) if previous != 0 else 0

        info = ticker.info
        name = info.get("longName") or info.get("shortName") or symbol.replace(".IS", "")
        currency = info.get("currency", "TRY" if ".IS" in symbol else "USD")

        dates = hist.index.strftime("%Y-%m-%d").tolist()
        prices = hist["Close"].round(2).tolist()
        highs = hist["High"].round(2).tolist()
        lows = hist["Low"].round(2).tolist()
        volumes = hist["Volume"].tolist()

        return {
            "symbol": symbol.replace(".IS", ""),
            "name": name,
            "currency": currency,
            "current_price": round(current, 2),
            "change": round(change, 2),
            "change_percent": round(change_pct, 2),
            "volume": int(hist["Volume"].iloc[-1]) if not hist["Volume"].empty else 0,
            "market_cap": info.get("marketCap"),
            "historical_data": {"dates": dates, "prices": prices, "highs": highs, "lows": lows, "volumes": volumes},
            "fetched_at": datetime.now().isoformat(),
            "error": None
        }
    except Exception as e:
        logger.error(f"Finance hatası {symbol}: {e}")
        return {"symbol": symbol, "error": str(e), "historical_data": {"dates": [], "prices": [], "highs": [], "lows": [], "volumes": []}}

# ==================== ML + İNDİKATÖRLER ====================
async def enrich_with_indicators_and_predict(symbol: str, period: str = "6mo", forecast_horizon: int = 5) -> Dict:
    data = await get_finance_data(symbol, period)
    if data.get("error"):
        return {"error": data["error"]}

    df = pd.DataFrame({
        "Date": data["historical_data"]["dates"],
        "Close": data["historical_data"]["prices"],
        "High": data["historical_data"]["highs"],
        "Low": data["historical_data"]["lows"],
        "Volume": data["historical_data"]["volumes"]
    }).set_index("Date")
    df.index = pd.to_datetime(df.index)

    # Hafif indikatör seti
    df["sma_20"] = ta.sma(df["Close"], length=20)
    df["ema_50"] = ta.ema(df["Close"], length=50)
    df["rsi_14"] = ta.rsi(df["Close"], length=14)
    macd = ta.macd(df["Close"])
    df["macd"] = macd["MACD_12_26_9"]
    df["macd_sig"] = macd["MACDs_12_26_9"]
    df["macd_hist"] = macd["MACDh_12_26_9"]
    bb = ta.bbands(df["Close"], length=20)
    df["bb_upper"] = bb["BBU_20_2.0"]
    df["bb_lower"] = bb["BBL_20_2.0"]
    df["bb_percent"] = bb["BBP_20_2.0"]
    df["atr_14"] = ta.atr(df["High"], df["Low"], df["Close"], length=14)
    stoch = ta.stoch(df["High"], df["Low"], df["Close"])
    df["stoch_k"] = stoch["STOCHk_14_3_3"]
    adx = ta.adx(df["High"], df["Low"], df["Close"], length=14)
    df["adx_14"] = adx["ADX_14"]
    df["obv"] = ta.obv(df["Close"], df["Volume"])

    df = df.dropna()

    if len(df) < 60:
        return {"error": "Yeterli veri yok (indikatörler için ≥60 satır lazım)"}

    df["target"] = df["Close"].shift(-forecast_horizon)
    df = df.dropna()

    features = [c for c in df.columns if c not in ["Close", "target", "Date", "High", "Low", "Volume"]]
    X = df[features]
    y = df["target"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    model = XGBRegressor(n_estimators=100, learning_rate=0.1, random_state=42)
    model.fit(X_train, y_train)

    last_features = X.iloc[-1:].values
    pred = model.predict(last_features)[0]
    mae = mean_absolute_error(y_test, model.predict(X_test))

    return {
        "predicted_price": round(float(pred), 2),
        "current_price": round(df["Close"].iloc[-1], 2),
        "horizon": forecast_horizon,
        "direction": "↑ YUKARI" if pred > df["Close"].iloc[-1] else "↓ AŞAĞI",
        "mae": round(float(mae), 2),
        "features_count": len(features),
        "note": "İstatistiksel tahmin – yatırım tavsiyesi değildir"
    }

# ==================== ROUTES ====================
@app.get("/")
async def home():
    html_content = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ICTSmartPro × Qwen Trading</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {font-family:system-ui, sans-serif; background:#0f172a; color:#e2e8f0; margin:0; padding:1.5rem;}
        .container {max-width:1200px; margin:0 auto;}
        header {text-align:center; padding:2rem; background:linear-gradient(90deg,#3b82f6,#8b5cf6); border-radius:16px; margin-bottom:2rem;}
        .logo {font-size:2.8rem; font-weight:900; background:linear-gradient(45deg,#fbbf24,#f97316); -webkit-background-clip:text; -webkit-text-fill-color:transparent;}
        .dashboard {display:grid; grid-template-columns:1fr 1fr; gap:1.5rem;}
        @media (max-width:768px) {.dashboard {grid-template-columns:1fr;}}
        .card {background:rgba(30,41,59,0.7); border-radius:16px; padding:1.5rem; border:1px solid rgba(255,255,255,0.08);}
        label {display:block; margin:0.8rem 0 0.4rem; color:#cbd5e1;}
        select, textarea {width:100%; padding:0.8rem; border-radius:8px; border:1px solid #475569; background:#1e293b; color:white; font-size:1rem;}
        button {background:linear-gradient(90deg,#10b981,#3b82f6); color:white; border:none; padding:0.9rem; border-radius:10px; font-weight:600; cursor:pointer; width:100%; margin-top:1rem;}
        button:hover {opacity:0.92;}
        .result {margin-top:1.2rem; padding:1rem; background:rgba(255,255,255,0.04); border-radius:10px; white-space:pre-wrap; line-height:1.5;}
        .positive {color:#10b981;} .negative {color:#ef4444;}
        .chart-container {height:340px; margin-top:1.5rem;}
        .loading {text-align:center; color:#60a5fa; padding:1.5rem;}
        .error {color:#ef4444; background:rgba(239,68,68,0.12); padding:0.8rem; border-radius:8px;}
    </style>
</head>
<body>
<div class="container">
    <header>
        <div class="logo">ICTSmartPro × Qwen + ML</div>
        <div>Yapay Zeka + Makine Öğrenmesi Destekli Hisse Analizi</div>
    </header>

    <div class="dashboard">
        <div class="card">
            <h2>📈 Hisse Analizi</h2>
            <label>Sembol:</label>
            <select id="symbol">
                <option value="THYAO.IS">THYAO - Türk Hava Yolları</option>
                <option value="AKBNK.IS">AKBNK - Akbank</option>
                <option value="GARAN.IS">GARAN - Garanti</option>
                <option value="ISCTR.IS">ISCTR - İş Bankası</option>
                <option value="EREGL.IS">EREGL - Ereğli Demir Çelik</option>
                <option value="SISE.IS">SISE - Şişecam</option>
                <option value="KCHOL.IS">KCHOL - Koç Holding</option>
                <option value="ASELS.IS">ASELS - Aselsan</option>
                <option value="AAPL">AAPL - Apple</option>
                <option value="MSFT">MSFT - Microsoft</option>
                <option value="NVDA">NVDA - NVIDIA</option>
            </select>

            <label>Dönem:</label>
            <select id="period">
                <option value="5d">5 Gün</option>
                <option value="1mo" selected>1 Ay</option>
                <option value="3mo">3 Ay</option>
                <option value="6mo">6 Ay</option>
                <option value="1y">1 Yıl</option>
            </select>

            <button id="analyzeBtn">Analiz Et</button>
            <button id="predictBtn" style="margin-top:0.8rem; background:linear-gradient(90deg,#8b5cf6,#d946ef);">ML Tahmin Al (5 gün)</button>
            <div id="financeResult" class="result"><div class="loading">Sembol seçip Analiz Et'e basın...</div></div>
            <div id="mlResult" class="result" style="margin-top:1rem;"><div class="loading">ML tahmini burada görünecek...</div></div>
        </div>

        <div class="card">
            <h2>🤖 Qwen AI Analizi</h2>
            <label>Soru / Talimat:</label>
            <textarea id="aiQuery" rows="5" placeholder="Örnek:\nTHYAO son 1 ay teknik görünümü nasıl?\nAKBNK için alım-satım önerisi ver"></textarea>
            <button id="askBtn">Qwen'e Sor</button>
            <div id="aiResult" class="result"><div class="loading">Soru bekleniyor...</div></div>
        </div>
    </div>

    <div class="card" style="margin-top:2rem;">
        <h2>📊 Fiyat Grafiği</h2>
        <div class="chart-container"><canvas id="priceChart"></canvas></div>
    </div>
</div>

<script>
    let chartInstance = null;

    async function analyzeStock() {
        const symbol = document.getElementById('symbol').value;
        const period = document.getElementById('period').value;
        const resDiv = document.getElementById('financeResult');
        resDiv.innerHTML = '<div class="loading">Veriler çekiliyor...</div>';

        try {
            const resp = await fetch(`/api/finance/${encodeURIComponent(symbol)}?period=${period}`);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const data = await resp.json();

            if (data.error) {
                resDiv.innerHTML = `<div class="error">Hata: ${data.error}</div>`;
                return;
            }

            let html = `<strong>${data.symbol} - ${data.name}</strong><br>`;
            html += `Fiyat: ${data.current_price} ${data.currency}<br>`;
            html += `Değişim: <span class="${data.change_percent >= 0 ? 'positive' : 'negative'}">${data.change_percent.toFixed(2)}% (${data.change.toFixed(2)})</span><br>`;
            if (data.market_cap) html += `Piyasa Değeri: ~${(data.market_cap / 1e9).toFixed(1)} milyar<br>`;

            resDiv.innerHTML = html;

            if (data.historical_data?.prices?.length > 0) {
                drawChart(data.historical_data, data.symbol);
            }
        } catch (err) {
            resDiv.innerHTML = `<div class="error">Bağlantı hatası: ${err.message}</div>`;
            console.error(err);
        }
    }

    async function getMLPrediction() {
        const symbol = document.getElementById('symbol').value;
        const mlDiv = document.getElementById('mlResult');
        mlDiv.innerHTML = '<div class="loading">ML tahmin hesaplanıyor (XGBoost + indikatörler)...</div>';

        try {
            const resp = await fetch(`/api/predict/${encodeURIComponent(symbol)}?period=6mo&horizon=5`);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const data = await resp.json();

            if (data.error) {
                mlDiv.innerHTML = `<div class="error">Hata: ${data.error}</div>`;
                return;
            }

            let html = `<strong>5 Gün Sonrası ML Tahmini</strong><br>`;
            html += `Tahmini fiyat: ${data.predicted_price} ${data.current_price > data.predicted_price ? '↓' : '↑'}<br>`;
            html += `Mevcut fiyat: ${data.current_price}<br>`;
            html += `Yön: <span class="${data.direction.includes('YUKARI') ? 'positive' : 'negative'}">${data.direction}</span><br>`;
            html += `Hata (MAE): ${data.mae}<br>`;
            html += `<small>${data.note}</small>`;

            mlDiv.innerHTML = html;
        } catch (err) {
            mlDiv.innerHTML = `<div class="error">ML hatası: ${err.message}</div>`;
            console.error(err);
        }
    }

    async function askQwen() {
        const query = document.getElementById('aiQuery').value.trim();
        if (!query) {
            alert('Lütfen bir soru yazın!');
            return;
        }

        const resDiv = document.getElementById('aiResult');
        resDiv.innerHTML = '<div class="loading">Qwen analiz yapıyor (ML bilgisi eklendi)...</div>';

        try {
            const resp = await fetch('/api/ai/ask', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: query})
            });

            if (!resp.ok) {
                const errText = await resp.text();
                throw new Error(`HTTP ${resp.status}: ${errText}`);
            }

            const data = await resp.json();
            resDiv.innerHTML = (data.reply || 'Cevap alınamadı').replace(/\\n/g, '<br>');
        } catch (err) {
            resDiv.innerHTML = `<div class="error">AI hatası: ${err.message}</div>`;
            console.error(err);
        }
    }

    function drawChart(hdata, sym) {
        const ctx = document.getElementById('priceChart').getContext('2d');
        if (chartInstance) chartInstance.destroy();

        chartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: hdata.dates,
                datasets: [{
                    label: sym,
                    data: hdata.prices,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59,130,246,0.1)',
                    tension: 0.15,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {grid: {color: 'rgba(255,255,255,0.08)'}, ticks: {color: '#94a3b8'}},
                    x: {grid: {color: 'rgba(255,255,255,0.08)'}, ticks: {color: '#94a3b8'}}
                }
            }
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('analyzeBtn').addEventListener('click', analyzeStock);
        document.getElementById('predictBtn').addEventListener('click', getMLPrediction);
        document.getElementById('askBtn').addEventListener('click', askQwen);
        analyzeStock();  // Sayfa açıldığında otomatik çalışsın
    });
</script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)

@app.get("/api/finance/{symbol}")
async def get_finance(symbol: str, period: str = "1mo"):
    return await get_finance_data(symbol, period)

@app.get("/api/predict/{symbol}")
async def predict(symbol: str, period: str = "6mo", horizon: int = 5):
    return await enrich_with_indicators_and_predict(symbol, period, horizon)

@app.post("/api/ai/ask")
async def ask_ai(request: Request):
    try:
        body = await request.json()
        user_msg = body.get("message", "").strip()
        if not user_msg:
            raise HTTPException(400, "Mesaj boş olamaz")

        # Mesajdan sembol çıkar (ör: THYAO, AAPL, AKBNK.IS vb.)
        symbol_match = re.search(r'\b([A-Z]{3,5}(?:\.[A-Z]{2})?)\b', user_msg.upper())
        symbol = symbol_match.group(1) if symbol_match else "THYAO"

        ml_result = await enrich_with_indicators_and_predict(symbol, "6mo", 5)

        ml_info = ""
        if not ml_result.get("error"):
            ml_info = f"""
ML Tahmini (XGBoost + indikatörler, {ml_result['horizon']} gün sonrası):
Tahmini fiyat: {ml_result['predicted_price']}
Mevcut: {ml_result['current_price']}
Yön: {ml_result['direction']}
Hata (MAE): {ml_result['mae']}
Özellik sayısı: {ml_result['features_count']}
{ml_result['note']}
"""

        system_prompt = """Sen deneyimli bir Türk borsası ve global hisse analisti olarak cevap ver.
Kısa, net, gerçekçi ol. Teknik analiz, trend, destek-direnç seviyeleri, riskler hakkında konuş.
ML tahminlerini de değerlendirerek yorum yap. Spekülasyon yapma, veriye dayalı ol. Türkçe cevap ver."""

        enhanced_msg = f"{user_msg}\n\n{ml_info}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": enhanced_msg}
        ]

        reply = await call_qwen(messages)
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "qwen_model": QWEN_MODEL,
        "api_key_set": bool(OPENROUTER_API_KEY),
        "ml_enabled": True,
        "environment": "Railway" if "RAILWAY_ENVIRONMENT" in os.environ else "Local"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
