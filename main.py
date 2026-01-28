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
QWEN_API_KEY = os.environ.get("QWEN_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

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

# ==================== MODELS ====================
class ChatRequest(BaseModel):
    message: str
    symbol: Optional[str] = None
    language: Optional[str] = "tr"

class FinanceRequest(BaseModel):
    symbol: str
    period: str = "1mo"
    interval: str = "1d"

class TradingSignal(BaseModel):
    symbol: str
    action: str  # BUY, SELL, HOLD
    confidence: float
    reasoning: str
    timestamp: str

# ==================== QWEN AI INTEGRATION ====================
class QwenAIClient:
    def __init__(self):
        self.api_key = OPENROUTER_API_KEY or QWEN_API_KEY
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://ictsmartpro.ai",
            "X-Title": "ICTSmartPro Trading AI"
        }
    
    async def analyze_trading(self, symbol: str, data: dict, language: str = "tr") -> str:
        """Qwen AI ile trading analizi yap"""
        try:
            prompt = self._create_trading_prompt(symbol, data, language)
            
            if not self.api_key:
                return self._get_fallback_response(symbol, data, language)
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.base_url,
                    headers=self.headers,
                    json={
                        "model": "qwen/qwen-2.5-32b-instruct:free",
                        "messages": [
                            {"role": "system", "content": "Sen bir profesyonel finans analistisin. Türkçe ve İngilizce analiz yapabilirsin."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 1000
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result['choices'][0]['message']['content']
                else:
                    logger.error(f"Qwen API error: {response.text}")
                    return self._get_fallback_response(symbol, data, language)
                    
        except Exception as e:
            logger.error(f"Qwen analysis error: {e}")
            return self._get_fallback_response(symbol, data, language)
    
    def _create_trading_prompt(self, symbol: str, data: dict, language: str) -> str:
        """Trading analizi için prompt oluştur"""
        if language == "tr":
            return f"""
            {symbol} için detaylı teknik analiz yap:
            
            Mevcut Fiyat: {data.get('current_price')}
            Değişim: {data.get('change_percent')}%
            Hacim: {data.get('volume')}
            Period: {data.get('period')}
            
            Lütfen şunları analiz et:
            1. Trend analizi
            2. Destek ve direnç seviyeleri
            3. Momentum göstergeleri
            4. Risk seviyesi
            5. Önerilen işlem (AL/SAT/BEKLE)
            6. Stop-loss ve take-profit seviyeleri
            
            Analizi net ve özet şekilde sun.
            """
        else:
            return f"""
            Perform detailed technical analysis for {symbol}:
            
            Current Price: {data.get('current_price')}
            Change: {data.get('change_percent')}%
            Volume: {data.get('volume')}
            Period: {data.get('period')}
            
            Please analyze:
            1. Trend analysis
            2. Support and resistance levels
            3. Momentum indicators
            4. Risk level
            5. Recommended action (BUY/SELL/HOLD)
            6. Stop-loss and take-profit levels
            
            Present the analysis in a clear and concise manner.
            """
    
    def _get_fallback_response(self, symbol: str, data: dict, language: str) -> str:
        """API olmadan fallback response"""
        change = data.get('change_percent', 0)
        
        if language == "tr":
            if change > 5:
                action = "AL (Güçlü Yükseliş)"
            elif change > 0:
                action = "AL (Hafif Yükseliş)"
            elif change < -5:
                action = "SAT (Güçlü Düşüş)"
            else:
                action = "BEKLE (Nötr)"
            
            return f"""
            {symbol} Analizi:
            
            📈 Fiyat: {data.get('current_price')} 
            📊 Değişim: {data.get('change_percent')}%
            📦 Hacim: {data.get('volume')}
            
            🎯 Öneri: {action}
            
            📝 Not: Qwen AI entegrasyonu için API anahtarı gerekli.
            """
        else:
            if change > 5:
                action = "BUY (Strong Uptrend)"
            elif change > 0:
                action = "BUY (Mild Uptrend)"
            elif change < -5:
                action = "SELL (Strong Downtrend)"
            else:
                action = "HOLD (Neutral)"
            
            return f"""
            {symbol} Analysis:
            
            📈 Price: {data.get('current_price')} 
            📊 Change: {data.get('change_percent')}%
            📦 Volume: {data.get('volume')}
            
            🎯 Recommendation: {action}
            
            📝 Note: API key required for Qwen AI integration.
            """

qwen_client = QwenAIClient()

# ==================== FINANCE FUNCTIONS ====================
async def get_finance_data(symbol: str, period: str = "1mo", interval: str = "1d") -> dict:
    """Finans verilerini al"""
    try:
        symbol = symbol.upper().strip()
        ticker = yf.Ticker(symbol)
        
        # Tarihsel veriler
        hist = ticker.history(period=period, interval=interval)
        
        if hist.empty:
            raise ValueError(f"No data found for {symbol}")
        
        # Mevcut fiyat ve değişim
        current = float(hist["Close"].iloc[-1])
        previous = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current
        change = current - previous
        change_percent = (change / previous * 100) if previous != 0 else 0
        
        # Ek bilgiler
        info = ticker.info
        currency = info.get('currency', 'USD')
        market_cap = info.get('marketCap')
        
        return {
            "symbol": symbol,
            "name": info.get('longName', symbol),
            "currency": currency,
            "current_price": round(current, 2),
            "previous_close": round(previous, 2),
            "change": round(change, 2),
            "change_percent": round(change_percent, 2),
            "volume": int(hist["Volume"].iloc[-1]),
            "market_cap": market_cap,
            "period": period,
            "data_points": len(hist),
            "historical_data": {
                "dates": hist.index.strftime('%Y-%m-%d').tolist(),
                "prices": hist["Close"].round(2).tolist()
            },
            "fetched_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Finance data error for {symbol}: {e}")
        raise

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
                            <option value="BTC-USD">BTC-USD - Bitcoin</option>
                            <option value="ETH-USD">ETH-USD - Ethereum</option>
                            <option value="BIST:THYAO">THYAO - Türk Hava Yolları</option>
                            <option value="BIST:AKBNK">AKBNK - Akbank</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Period:</label>
                        <select id="periodSelect">
                            <option value="1d">1 Gün</option>
                            <option value="5d">5 Gün</option>
                            <option value="1mo">1 Ay</option>
                            <option value="3mo">3 Ay</option>
                            <option value="6mo">6 Ay</option>
                            <option value="1y">1 Yıl</option>
                        </select>
                    </div>
                    <button onclick="analyzeStock()">🔍 Analiz Et</button>
                    <div id="financeResult" class="result"></div>
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
                            <option value="tr">Türkçe</option>
                            <option value="en">English</option>
                        </select>
                    </div>
                    <button onclick="askAI()">🚀 Qwen AI ile Analiz</button>
                    <div id="aiResult" class="result"></div>
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
                
                document.getElementById('financeResult').innerHTML = '⏳ Analiz ediliyor...';
                
                try {
                    const response = await fetch(`/api/finance/${symbol}?period=${period}`);
                    const data = await response.json();
                    
                    let resultHTML = `
                        <h3>${data.symbol} - ${data.name || ''}</h3>
                        <p><strong>💰 Mevcut Fiyat:</strong> ${data.current_price} ${data.currency}</p>
                        <p><strong>📈 Değişim:</strong> <span class="${data.change_percent >= 0 ? 'positive' : 'negative'}">${data.change_percent}% (${data.change})</span></p>
                        <p><strong>📦 İşlem Hacmi:</strong> ${data.volume.toLocaleString()}</p>
                        <p><strong>🏦 Piyasa Değeri:</strong> ${data.market_cap ? (data.market_cap/1e9).toFixed(2)+'B' : 'N/A'}</p>
                        <p><strong>⏰ Period:</strong> ${period}</p>
                    `;
                    
                    document.getElementById('financeResult').innerHTML = resultHTML;
                    
                    // Grafik çiz
                    updateChart(data.historical_data);
                    
                    // AI analizi için buton göster
                    document.getElementById('financeResult').innerHTML += `
                        <button onclick="analyzeWithAI('${symbol}', '${period}')" style="margin-top: 15px; background: linear-gradient(90deg, #8b5cf6, #ec4899);">
                            🤖 Qwen AI ile Detaylı Analiz
                        </button>
                    `;
                    
                } catch (error) {
                    document.getElementById('financeResult').innerHTML = '❌ Hata: ' + error.message;
                }
            }

            async function analyzeWithAI(symbol, period) {
                document.getElementById('aiResult').innerHTML = '🤖 Qwen AI analiz yapıyor...';
                
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
                    
                    const data = await response.json();
                    document.getElementById('aiResult').innerHTML = data.analysis.replace(/\\n/g, '<br>');
                } catch (error) {
                    document.getElementById('aiResult').innerHTML = '❌ AI analiz hatası: ' + error.message;
                }
            }

            async function askAI() {
                const query = document.getElementById('aiQuery').value;
                const language = document.getElementById('languageSelect').value;
                
                if (!query.trim()) {
                    alert('Lütfen bir soru girin!');
                    return;
                }
                
                document.getElementById('aiResult').innerHTML = '🤖 Qwen AI düşünüyor...';
                
                try {
                    const response = await fetch('/api/ai/chat', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            message: query,
                            language: language
                        })
                    });
                    
                    const data = await response.json();
                    document.getElementById('aiResult').innerHTML = data.reply.replace(/\\n/g, '<br>');
                } catch (error) {
                    document.getElementById('aiResult').innerHTML = '❌ AI hatası: ' + error.message;
                }
            }

            function updateChart(historicalData) {
                const ctx = document.getElementById('priceChart').getContext('2d');
                
                if (priceChart) {
                    priceChart.destroy();
                }
                
                priceChart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: historicalData.dates,
                        datasets: [{
                            label: 'Fiyat',
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

            // Sayfa yüklendiğinde örnek analiz
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
        "version": "3.0.0",
        "timestamp": datetime.now().isoformat(),
        "features": ["trading_analysis", "ai_chat", "finance_data", "charts"]
    }

@app.get("/api/finance/{symbol}")
async def get_finance(symbol: str, period: str = "1mo"):
    """Finans verilerini getir"""
    try:
        data = await get_finance_data(symbol, period)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/analyze")
async def analyze_with_ai(request: ChatRequest):
    """Qwen AI ile trading analizi"""
    try:
        symbol = request.symbol or "AAPL"
        
        # Finans verilerini al
        finance_data = await get_finance_data(symbol, "1mo")
        
        # Qwen AI analizi
        analysis = await qwen_client.analyze_trading(
            symbol, 
            finance_data, 
            request.language
        )
        
        return {
            "symbol": symbol,
            "analysis": analysis,
            "finance_data": finance_data,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/chat")
async def chat_with_ai(request: ChatRequest):
    """Qwen AI ile sohbet"""
    try:
        # Eğer sembol varsa, finans analizi yap
        if request.symbol:
            finance_data = await get_finance_data(request.symbol, "1mo")
            analysis = await qwen_client.analyze_trading(
                request.symbol, 
                finance_data, 
                request.language
            )
            return {
                "reply": analysis,
                "type": "trading_analysis",
                "timestamp": datetime.now().isoformat()
            }
        
        # Yoksa genel sohbet
        prompt = f"Soru: {request.message}\n\nDil: {request.language}\n\nCevap:"
        
        if request.language == "tr":
            reply = """ICTSmartPro Trading AI'ye hoş geldiniz! 🤖

Size şu konularda yardımcı olabilirim:
📈 Hisse/ETF/fon analizi
📊 Teknik analiz ve grafik yorumlama
💰 Yatırım stratejileri
📉 Risk yönetimi
🎯 Al/Sat sinyalleri

Bir sembol (AAPL, BTC-USD, THYAO vb.) söyleyin veya sorunuzu yazın!"""
        else:
            reply = """Welcome to ICTSmartPro Trading AI! 🤖

I can help you with:
📈 Stock/ETF/fund analysis
📊 Technical analysis and chart interpretation
💰 Investment strategies
📉 Risk management
🎯 Buy/Sell signals

Please provide a symbol (AAPL, BTC-USD, etc.) or ask your question!"""
        
        return {
            "reply": reply,
            "type": "general_chat",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/signals")
async def get_trading_signals():
    """Trading sinyalleri"""
    symbols = ["AAPL", "TSLA", "BTC-USD", "ETH-USD", "NVDA"]
    signals = []
    
    for symbol in symbols:
        try:
            data = await get_finance_data(symbol, "1d")
            change = data['change_percent']
            
            if change > 3:
                action = "BUY"
                confidence = min(90, 70 + change)
            elif change < -3:
                action = "SELL"
                confidence = min(90, 70 + abs(change))
            else:
                action = "HOLD"
                confidence = 50
            
            signals.append({
                "symbol": symbol,
                "action": action,
                "confidence": round(confidence, 1),
                "price": data['current_price'],
                "change_percent": change,
                "reasoning": f"Günlük değişim: {change}%",
                "timestamp": datetime.now().isoformat()
            })
        except:
            continue
    
    return {"signals": signals}

# ==================== STARTUP ====================
@app.on_event("startup")
async def startup_event():
    """Başlangıçta çalışacak"""
    logger.info(f"🚀 ICTSmartPro × Qwen AI Trading Platform başladı!")
    logger.info(f"🌐 Port: {PORT}")
    logger.info(f"🔑 Qwen API: {'✅ Available' if OPENROUTER_API_KEY else '⚠️ Not configured'}")
    logger.info("📊 Servisler: Trading Analysis, AI Chat, Charts")

# ==================== MAIN ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
