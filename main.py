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

# ==================== KONFIGÜRASYON ====================
load_dotenv()  # Yerel geliştirme için .env okur (Railway'de gerek yok, ortam değişkeni kullanır)

PORT = int(os.environ.get("PORT", 8000))
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
QWEN_MODEL = "qwen/qwen3-coder:free"  # Ücretsiz model - limit olabilir

if not OPENROUTER_API_KEY:
    print("⚠️  DİKKAT: OPENROUTER_API_KEY ortam değişkeni tanımlı değil!")

# Logging
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ICTSmartPro × Qwen Trading Analiz",
    description="Qwen AI ile Hisse / Fon Teknik Analizi",
    version="3.2.0",
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
        return "❌ OpenRouter API anahtarı eksik. Railway Variables'a ekleyin veya .env dosyasına OPENROUTER_API_KEY=sk-or-v1-... yazın."

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://your-railway-app.up.railway.app",  # Railway domainini buraya yazabilirsin
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
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Qwen hatası: {e}")
            if "429" in str(e):
                return "❌ Rate limit aşıldı (ücretsiz model sınırı). Biraz bekleyin."
            return f"AI bağlantı hatası: {str(e)}"

# ==================== FİNANS VERİ ====================
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

        return {
            "symbol": symbol.replace(".IS", ""),
            "name": name,
            "currency": currency,
            "current_price": round(current, 2),
            "change": round(change, 2),
            "change_percent": round(change_pct, 2),
            "volume": int(hist["Volume"].iloc[-1]) if not hist["Volume"].empty else 0,
            "market_cap": info.get("marketCap"),
            "historical_data": {"dates": dates, "prices": prices},
            "fetched_at": datetime.now().isoformat(),
            "error": None
        }
    except Exception as e:
        logger.error(f"Finance hatası {symbol}: {e}")
        return {"symbol": symbol, "error": str(e), "historical_data": {"dates": [], "prices": []}}

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
        <div class="logo">ICTSmartPro × Qwen</div>
        <div>Yapay Zeka Destekli Hisse Analizi</div>
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
            <div id="financeResult" class="result"><div class="loading">Sembol seçip Analiz Et'e basın...</div></div>
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

    async function askQwen() {
        const query = document.getElementById('aiQuery').value.trim();
        if (!query) {
            alert('Lütfen bir soru yazın!');
            return;
        }

        const resDiv = document.getElementById('aiResult');
        resDiv.innerHTML = '<div class="loading">Qwen analiz yapıyor...</div>';

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
        document.getElementById('askBtn').addEventListener('click', askQwen);
        analyzeStock();
    });
</script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)

@app.get("/api/finance/{symbol}")
async def get_finance(symbol: str, period: str = "1mo"):
    return await get_finance_data(symbol, period)

@app.post("/api/ai/ask")
async def ask_ai(request: Request):
    try:
        body = await request.json()
        user_msg = body.get("message", "").strip()
        if not user_msg:
            raise HTTPException(400, "Mesaj boş olamaz")

        system_prompt = """Sen deneyimli bir Türk borsası ve global hisse analisti olarak cevap ver.
Kısa, net, gerçekçi ol. Teknik analiz, trend, destek-direnç seviyeleri, riskler hakkında konuş.
Spekülasyon yapma, veriye dayalı ol. Türkçe cevap ver."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
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
        "environment": "Railway" if "RAILWAY_ENVIRONMENT" in os.environ else "Local"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")xxxx
