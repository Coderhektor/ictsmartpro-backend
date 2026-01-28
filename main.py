from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import yfinance as yf
import logging
import os
import json
from datetime import datetime, timedelta
from typing import Optional, List
import httpx
import asyncio

# ==================== KONFİGÜRASYON ====================
PORT = int(os.environ.get("PORT", 8000))
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

# Logging
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)
logger = logging.getLogger(__name__)

# ==================== FASTAPI APP ====================
app = FastAPI(
    title="ICTSmartPro × Qwen AI Trading Platform",
    description="Advanced AI Trading Analysis with Qwen LLM",
    version="3.0.0",
    docs_url="/docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== FINANCE FUNCTIONS ====================
async def get_finance_data(symbol: str, period: str = "1mo") -> dict:
    """Finans verilerini al - DÜZELTİLMİŞ VERSİYON"""
    try:
        symbol = symbol.upper().strip()
        
        # BIST sembolleri için özel işlem
        if symbol.startswith("BIST:"):
            symbol = symbol.replace("BIST:", "") + ".IS"
        
        ticker = yf.Ticker(symbol)
        
        # Tarihsel veriler
        hist = ticker.history(period=period)
        
        if hist.empty:
            # Alternatif sembol deneyelim
            if not symbol.endswith(".IS"):
                symbol_with_is = symbol + ".IS"
                ticker = yf.Ticker(symbol_with_is)
                hist = ticker.history(period=period)
            
            if hist.empty:
                # Fallback veri
                return {
                    "symbol": symbol,
                    "name": symbol,
                    "currency": "USD",
                    "current_price": 100.0,
                    "change": 0.0,
                    "change_percent": 0.0,
                    "volume": 0,
                    "market_cap": None,
                    "period": period,
                    "data_points": 0,
                    "historical_data": {
                        "dates": [],
                        "prices": []
                    },
                    "fetched_at": datetime.now().isoformat(),
                    "error": "No data available, showing demo data"
                }
        
        # Mevcut fiyat ve değişim
        current = float(hist["Close"].iloc[-1]) if len(hist) > 0 else 0
        previous = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current
        change = current - previous
        change_percent = (change / previous * 100) if previous != 0 else 0
        
        # Ek bilgiler
        info = ticker.info
        currency = info.get('currency', 'USD')
        market_cap = info.get('marketCap')
        name = info.get('longName', info.get('shortName', symbol))
        
        # Tarihsel verileri hazırla
        dates = hist.index.strftime('%Y-%m-%d').tolist() if len(hist) > 0 else []
        prices = hist["Close"].round(2).tolist() if len(hist) > 0 else []
        
        return {
            "symbol": symbol.replace(".IS", ""),
            "name": name,
            "currency": currency,
            "current_price": round(current, 2),
            "previous_close": round(previous, 2),
            "change": round(change, 2),
            "change_percent": round(change_percent, 2),
            "volume": int(hist["Volume"].iloc[-1]) if len(hist) > 0 else 0,
            "market_cap": market_cap,
            "period": period,
            "data_points": len(hist),
            "historical_data": {
                "dates": dates,
                "prices": prices
            },
            "fetched_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Finance data error for {symbol}: {e}")
        # Fallback response
        return {
            "symbol": symbol,
            "name": symbol,
            "currency": "USD",
            "current_price": 150.0,
            "change": 1.5,
            "change_percent": 1.0,
            "volume": 1000000,
            "market_cap": None,
            "period": period,
            "data_points": 10,
            "historical_data": {
                "dates": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "prices": [145.0, 148.0, 150.0]
            },
            "fetched_at": datetime.now().isoformat(),
            "error": f"Error: {str(e)}"
        }

# ==================== ENDPOINTS ====================
@app.get("/")
async def home():
    """Ana sayfa - Trading Dashboard"""
    html_content = """
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ICTSmartPro × Qwen AI Trading</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #0f172a, #1e293b);
                color: #f1f5f9;
                min-height: 100vh;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
            }
            header {
                text-align: center;
                padding: 40px 20px;
                background: linear-gradient(90deg, #3b82f6, #8b5cf6);
                border-radius: 20px;
                margin-bottom: 30px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            }
            .logo {
                font-size: 3rem;
                font-weight: 900;
                background: linear-gradient(45deg, #fbbf24, #f97316);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 10px;
            }
            .tagline {
                font-size: 1.2rem;
                opacity: 0.9;
            }
            .dashboard {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 30px;
                margin-bottom: 30px;
            }
            @media (max-width: 768px) {
                .dashboard { grid-template-columns: 1fr; }
            }
            .card {
                background: rgba(30, 41, 59, 0.8);
                border-radius: 15px;
                padding: 25px;
                box-shadow: 0 8px 25px rgba(0,0,0,0.2);
                border: 1px solid rgba(255,255,255,0.1);
            }
            .card h2 {
                color: #60a5fa;
                margin-bottom: 20px;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .form-group {
                margin-bottom: 20px;
            }
            label {
                display: block;
                margin-bottom: 8px;
                color: #cbd5e1;
            }
            input, select, textarea {
                width: 100%;
                padding: 12px 15px;
                border-radius: 10px;
                border: 1px solid #475569;
                background: #1e293b;
                color: white;
                font-size: 16px;
            }
            button {
                background: linear-gradient(90deg, #10b981, #3b82f6);
                color: white;
                border: none;
                padding: 15px 30px;
                border-radius: 10px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: transform 0.2s;
                width: 100%;
            }
            button:hover {
                transform: translateY(-2px);
            }
            .result {
                margin-top: 20px;
                padding: 20px;
                background: rgba(255,255,255,0.05);
                border-radius: 10px;
                white-space: pre-wrap;
                line-height: 1.6;
            }
            .positive { color: #10b981; }
            .negative { color: #ef4444; }
            .ai-analysis {
                background: linear-gradient(135deg, #1e3a8a, #3730a3);
                color: white;
            }
            .chart-container {
                height: 300px;
                margin-top: 20px;
            }
            .footer {
                text-align: center;
                padding: 20px;
                margin-top: 40px;
                border-top: 1px solid #334155;
                color: #94a3b8;
            }
            .loading {
                color: #60a5fa;
                text-align: center;
                padding: 20px;
            }
            .error {
                color: #ef4444;
                padding: 10px;
                background: rgba(239, 68, 68, 0.1);
                border-radius: 8px;
                margin-top: 10px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <div class="logo">ICTSmartPro × Qwen AI</div>
                <div class="tagline">🤖 Akıllı Trading Analizi & Yapay Zeka Destekli Yatırım</div>
            </header>

            <div class="dashboard">
                <div class="card">
                    <h2>📈 Hisse/Fon Analizi</h2>
                    <div class="form-group">
                        <label>Sembol:</label>
                        <select id="symbolSelect">
                            <option value="AAPL">AAPL - Apple</option>
                            <option value="TSLA">TSLA - Tesla</option>
                            <option value="NVDA">NVDA - NVIDIA</option>
                            <option value="MSFT">MSFT - Microsoft</option>
                            <option value="GOOGL">GOOGL - Google</option>
                            <option value="BTC-USD">BTC-USD - Bitcoin</option>
                            <option value="ETH-USD">ETH-USD - Ethereum</option>
                            <option value="THYAO.IS">THYAO - Türk Hava Yolları</option>
                            <option value="AKBNK.IS">AKBNK - Akbank</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Period:</label>
                        <select id="periodSelect">
                            <option value="1d">1 Gün</option>
                            <option value="5d">5 Gün</option>
                            <option value="1mo" selected>1 Ay</option>
                            <option value="3mo">3 Ay</option>
                            <option value="6mo">6 Ay</option>
                            <option value="1y">1 Yıl</option>
                        </select>
                    </div>
                    <button onclick="analyzeStock()">🔍 Analiz Et</button>
                    <div id="financeResult" class="result">
                        <div class="loading">📊 Sembol seçin ve analiz et butonuna tıklayın...</div>
                    </div>
                </div>

                <div class="card ai-analysis">
                    <h2>🤖 Qwen AI Trading Analizi</h2>
                    <div class="form-group">
                        <label>Soru/Sembol:</label>
                        <input type="text" id="aiQuery" placeholder="Ör: AAPL için teknik analiz yap veya BTC trendi nedir?">
                    </div>
                    <div class="form-group">
                        <label>Dil:</label>
                        <select id="languageSelect">
                            <option value="tr" selected>Türkçe</option>
                            <option value="en">English</option>
                        </select>
                    </div>
                    <button onclick="askAI()">🚀 Qwen AI ile Analiz</button>
                    <div id="aiResult" class="result">
                        <div class="loading">🤖 Sorunuzu yazın veya sembol analizi yapın...</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <h2>📊 Fiyat Grafiği</h2>
                <div class="chart-container">
                    <canvas id="priceChart"></canvas>
                </div>
            </div>

            <div class="footer">
                <p>© 2024 ICTSmartPro AI Trading Platform | Qwen AI Entegrasyonu</p>
                <p>📊 Gerçek zamanlı finans verileri | 🤖 Yapay Zeka analizi | 📈 Teknik indikatörler</p>
            </div>
        </div>

        <script>
            let priceChart = null;

            async function analyzeStock() {
                const symbol = document.getElementById('symbolSelect').value;
                const period = document.getElementById('periodSelect').value;
                
                document.getElementById('financeResult').innerHTML = '<div class="loading">⏳ Analiz ediliyor...</div>';
                
                try {
                    // URL encode
                    const encodedSymbol = encodeURIComponent(symbol);
                    const response = await fetch(`/api/finance/${encodedSymbol}?period=${period}`);
                    
                    if (!response.ok) {
                        throw new Error(`API error: ${response.status}`);
                    }
                    
                    const data = await response.json();
                    
                    let resultHTML = `
                        <h3>${data.symbol} - ${data.name || data.symbol}</h3>
                        <p><strong>💰 Mevcut Fiyat:</strong> ${data.current_price} ${data.currency || 'USD'}</p>
                        <p><strong>📈 Değişim:</strong> <span class="${data.change_percent >= 0 ? 'positive' : 'negative'}">${data.change_percent}% (${data.change})</span></p>
                        <p><strong>📦 İşlem Hacmi:</strong> ${data.volume ? data.volume.toLocaleString() : 'N/A'}</p>
                    `;
                    
                    if (data.market_cap) {
                        resultHTML += `<p><strong>🏦 Piyasa Değeri:</strong> ${(data.market_cap/1e9).toFixed(2)}B</p>`;
                    }
                    
                    resultHTML += `<p><strong>⏰ Period:</strong> ${period}</p>`;
                    
                    if (data.error) {
                        resultHTML += `<div class="error">⚠️ ${data.error}</div>`;
                    }
                    
                    document.getElementById('financeResult').innerHTML = resultHTML;
                    
                    // Grafik çiz (veri varsa)
                    if (data.historical_data && data.historical_data.prices.length > 0) {
                        updateChart(data.historical_data, data.symbol);
                    }
                    
                    // AI analizi için buton göster
                    document.getElementById('financeResult').innerHTML += `
                        <button onclick="analyzeWithAI('${symbol}', '${period}')" style="margin-top: 15px; background: linear-gradient(90deg, #8b5cf6, #ec4899);">
                            🤖 Qwen AI ile Detaylı Analiz
                        </button>
                    `;
                    
                } catch (error) {
                    document.getElementById('financeResult').innerHTML = 
                        `<div class="error">❌ Hata: ${error.message}</div>`;
                    console.error('Analyze error:', error);
                }
            }

            async function analyzeWithAI(symbol, period) {
                document.getElementById('aiResult').innerHTML = '<div class="loading">🤖 Qwen AI analiz yapıyor...</div>';
                
                try {
                    const response = await fetch('/api/ai/analyze', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            message: `${symbol} için teknik analiz yap`,
                            symbol: symbol,
                            language: document.getElementById('languageSelect').value
                        })
                    });
                    
                    if (!response.ok) {
                        throw new Error(`AI API error: ${response.status}`);
                    }
                    
                    const data = await response.json();
                    let analysisText = data.analysis || data.reply || 'Analiz yapılamadı';
                    analysisText = analysisText.replace(/\\n/g, '<br>');
                    
                    document.getElementById('aiResult').innerHTML = analysisText;
                } catch (error) {
                    document.getElementById('aiResult').innerHTML = 
                        `<div class="error">❌ AI analiz hatası: ${error.message}</div>`;
                    console.error('AI analyze error:', error);
                }
            }

            async function askAI() {
                const query = document.getElementById('aiQuery').value;
                const language = document.getElementById('languageSelect').value;
                
                if (!query.trim()) {
                    alert('Lütfen bir soru girin!');
                    return;
                }
                
                document.getElementById('aiResult').innerHTML = '<div class="loading">🤖 Qwen AI düşünüyor...</div>';
                
                try {
                    const response = await fetch('/api/ai/chat', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            message: query,
                            language: language
                        })
                    });
                    
                    if (!response.ok) {
                        throw new Error(`Chat API error: ${response.status}`);
                    }
                    
                    const data = await response.json();
                    let replyText = data.reply || 'Cevap alınamadı';
                    replyText = replyText.replace(/\\n/g, '<br>');
                    
                    document.getElementById('aiResult').innerHTML = replyText;
                } catch (error) {
                    document.getElementById('aiResult').innerHTML = 
                        `<div class="error">❌ AI hatası: ${error.message}</div>`;
                    console.error('Chat error:', error);
                }
            }

            function updateChart(historicalData, symbol) {
                const ctx = document.getElementById('priceChart').getContext('2d');
                
                if (priceChart) {
                    priceChart.destroy();
                }
                
                // Eğer veri yoksa, boş chart göster
                if (!historicalData || !historicalData.prices || historicalData.prices.length === 0) {
                    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
                    ctx.fillStyle = '#64748b';
                    ctx.font = '16px Arial';
                    ctx.textAlign = 'center';
                    ctx.fillText('Grafik verisi yok', ctx.canvas.width/2, ctx.canvas.height/2);
                    return;
                }
                
                priceChart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: historicalData.dates,
                        datasets: [{
                            label: `${symbol} Fiyat`,
                            data: historicalData.prices,
                            borderColor: '#3b82f6',
                            backgroundColor: 'rgba(59, 130, 246, 0.1)',
                            borderWidth: 2,
                            fill: true,
                            tension: 0.1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: true },
                            tooltip: { mode: 'index', intersect: false }
                        },
                        scales: {
                            y: {
                                beginAtZero: false,
                                grid: { color: 'rgba(255,255,255,0.1)' },
                                ticks: { color: '#cbd5e1' }
                            },
                            x: {
                                grid: { color: 'rgba(255,255,255,0.1)' },
                                ticks: { color: '#cbd5e1' }
                            }
                        }
                    }
                });
            }

            // Sayfa yüklendiğinde otomatik analiz
            window.onload = function() {
                analyzeStock();
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "service": "ICTSmartPro × Qwen AI Trading",
        "version": "3.1.0",
        "timestamp": datetime.now().isoformat(),
        "features": ["trading_analysis", "finance_data", "charts"],
        "note": "Qwen AI API key not configured (using fallback responses)"
    }

@app.get("/api/finance/{symbol}")
async def get_finance(symbol: str, period: str = "1mo"):
    """Finans verilerini getir"""
    try:
        data = await get_finance_data(symbol, period)
        return data
    except Exception as e:
        logger.error(f"API error for {symbol}: {e}")
        # Fallback data
        return {
            "symbol": symbol,
            "name": symbol,
            "currency": "USD",
            "current_price": 100.0,
            "change": 0.0,
            "change_percent": 0.0,
            "volume": 0,
            "market_cap": None,
            "period": period,
            "data_points": 0,
            "historical_data": {"dates": [], "prices": []},
            "fetched_at": datetime.now().isoformat(),
            "error": str(e)
        }

@app.post("/api/ai/analyze")
async def analyze_with_ai(request: Request):
    """AI analizi - Basit versiyon"""
    try:
        data = await request.json()
        symbol = data.get('symbol', 'AAPL')
        language = data.get('language', 'tr')
        
        # Finans verilerini al
        finance_data = await get_finance_data(symbol, "1mo")
        
        if language == "tr":
            analysis = f"""
            {symbol} Teknik Analizi:
            
            📈 Mevcut Fiyat: {finance_data['current_price']} {finance_data['currency']}
            📊 Değişim: {finance_data['change_percent']}%
            📦 Hacim: {finance_data.get('volume', 0)}
            
            🔍 Analiz:
            1. Fiyat hareketi: {'Yükseliş' if finance_data['change_percent'] > 0 else 'Düşüş'}
            2. Momentum: {'Güçlü' if abs(finance_data['change_percent']) > 5 else 'Zayıf'}
            3. Öneri: {'AL' if finance_data['change_percent'] > 0 else 'SAT' if finance_data['change_percent'] < -3 else 'BEKLE'}
            
            ⚠️ Not: Qwen AI API anahtarı eklenmemiş. Gerçek AI analizi için OpenRouter API key ekleyin.
            """
        else:
            analysis = f"""
            {symbol} Technical Analysis:
            
            📈 Current Price: {finance_data['current_price']} {finance_data['currency']}
            📊 Change: {finance_data['change_percent']}%
            📦 Volume: {finance_data.get('volume', 0)}
            
            🔍 Analysis:
            1. Price action: {'Uptrend' if finance_data['change_percent'] > 0 else 'Downtrend'}
            2. Momentum: {'Strong' if abs(finance_data['change_percent']) > 5 else 'Weak'}
            3. Recommendation: {'BUY' if finance_data['change_percent'] > 0 else 'SELL' if finance_data['change_percent'] < -3 else 'HOLD'}
            
            ⚠️ Note: Qwen AI API key not configured. Add OpenRouter API key for real AI analysis.
            """
        
        return {
            "symbol": symbol,
            "analysis": analysis,
            "finance_data": finance_data,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/chat")
async def chat_with_ai(request: Request):
    """AI sohbet - Basit versiyon"""
    try:
        data = await request.json()
        message = data.get('message', '')
        language = data.get('language', 'tr')
        
        if language == "tr":
            reply = f"""
            🤖 ICTSmartPro Trading AI:
            
            Sorunuz: "{message}"
            
            Size trading analizi konusunda yardımcı olabilirim:
            
            • Sembol analizi (AAPL, BTC-USD, THYAO vb.)
            • Teknik analiz
            • Trend yorumlama
            • Risk yönetimi
            
            Bir sembol adı söyleyin veya detaylı sorunuzu yazın!
            
            ⚠️ Not: Qwen AI API anahtarı eklenmemiş. OpenRouter'dan ücretsiz API key alabilirsiniz.
            """
        else:
            reply = f"""
            🤖 ICTSmartPro Trading AI:
            
            Your question: "{message}"
            
            I can help you with trading analysis:
            
            • Symbol analysis (AAPL, BTC-USD, etc.)
            • Technical analysis
            • Trend interpretation
            • Risk management
            
            Please provide a symbol name or ask your detailed question!
            
            ⚠️ Note: Qwen AI API key not configured. Get free API key from OpenRouter.
            """
        
        return {
            "reply": reply,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== STARTUP ====================
@app.on_event("startup")
async def startup_event():
    """Başlangıçta çalışacak"""
    logger.info(f"🚀 ICTSmartPro × Qwen AI Trading Platform başladı!")
    logger.info(f"🌐 Port: {PORT}")
    logger.info("📊 Servisler: Trading Analysis, Charts")

# ==================== MAIN ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
