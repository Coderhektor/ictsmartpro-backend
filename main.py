
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import yfinance as yf
import logging
import os
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

# ==================== KONFİGÜRASYON ====================
PORT = int(os.environ.get("PORT", 8000))
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== FASTAPI APP ====================
app = FastAPI(
    title="ICTSmartPro AI API",
    description="AI Trading Analysis Platform",
    version="2.0.0",
    docs_url="/docs" if DEBUG else None
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
    language: Optional[str] = "tr"

# ==================== HTML CONTENT ====================
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>ICTSmartPro - Qwen AI Trading Analizi</title>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; }
    body {
      font-family: system-ui, sans-serif;
      background: #0a0e27;
      color: #e0e3f0;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: linear-gradient(135deg, #1a1f3a, #2d1b4e);
      padding: 16px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid #334;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    }
    .logo {
      font-size: 1.7rem;
      font-weight: bold;
      background: linear-gradient(90deg, #667eea, #a78bfa);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .controls {
      display: flex;
      gap: 12px;
    }
    select, input, button {
      padding: 10px 16px;
      border-radius: 8px;
      border: 1px solid rgba(100,200,255,0.25);
      background: rgba(255,255,255,0.06);
      color: white;
      font-size: 1rem;
    }
    button { 
      background: linear-gradient(135deg, #667eea, #764ba2);
      border: none;
      cursor: pointer;
    }
    main {
      flex: 1;
      padding: 16px;
      display: flex;
      flex-direction: column;
    }
    iframe {
      flex: 1;
      border: none;
      border-radius: 12px;
      background: #111827;
      box-shadow: 0 8px 32px rgba(0,0,0,0.5);
    }
    .prompt-area {
      margin-top: 12px;
      display: flex;
      gap: 8px;
    }
    .prompt-area input { flex: 1; }
  </style>
</head>
<body>

  <header>
    <div class="logo">ICTSmartPro × Qwen AI</div>
    <div class="controls">
      <select id="symbol">
        <option value="BTC/USD">BTC/USD</option>
        <option value="ETH/USD">ETH/USD</option>
        <option value="SOL/USD">SOL/USD</option>
        <option value="AAPL">AAPL</option>
        <option value="TSLA">TSLA</option>
      </select>
      <select id="timeframe">
        <option value="1 aylık">1 Aylık</option>
        <option value="3 aylık">3 Aylık</option>
        <option value="6 aylık">6 Aylık</option>
        <option value="1 yıllık">1 Yıllık</option>
      </select>
    </div>
  </header>

  <main>
    <iframe id="qwen" src="https://chat.qwen.ai/"></iframe>

    <div class="prompt-area">
      <input id="custom" placeholder="Kendi sorunuzu yazın ve Enter'a basın..." />
      <button onclick="sendPrompt()">Gönder</button>
    </div>
  </main>

  <script>
    const iframe = document.getElementById('qwen');
    const symbolSelect = document.getElementById('symbol');
    const timeframeSelect = document.getElementById('timeframe');
    const customInput = document.getElementById('custom');

    function buildPrompt() {
      const symbol = symbolSelect.value;
      const tf = timeframeSelect.value;
      return `${symbol} için ${tf} mum grafiği çiz ve detaylı teknik analiz yap.`;
    }

    function updateIframe() {
      const prompt = encodeURIComponent(buildPrompt());
      iframe.src = `https://chat.qwen.ai/?prompt=${prompt}`;
    }

    function sendPrompt() {
      const text = customInput.value.trim();
      if (!text) {
        updateIframe();
        return;
      }
      const prompt = encodeURIComponent(text);
      iframe.src = `https://chat.qwen.ai/?prompt=${prompt}`;
      customInput.value = '';
    }

    // Select değişince otomatik prompt ile yenile
    symbolSelect.onchange = updateIframe;
    timeframeSelect.onchange = updateIframe;

    // İlk açılışta varsayılan prompt ile başla
    updateIframe();

    // Enter tuşu ile de gönderme
    customInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') sendPrompt();
    });
  </script>

</body>
</html>
"""

# ==================== ENDPOINTS ====================
@app.get("/")
async def home():
    """Ana sayfa - Qwen AI trading arayüzü"""
    return HTMLResponse(content=HTML_CONTENT, status_code=200)

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "ICTSmartPro AI",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0"
    }

@app.get("/api/finance/{symbol}")
async def get_finance(symbol: str, period: str = "1mo"):
    """Finans verileri endpoint'i"""
    try:
        symbol = symbol.upper().strip()
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        
        if hist.empty:
            raise HTTPException(status_code=404, detail=f"Symbol not found: {symbol}")
        
        current = float(hist["Close"].iloc[-1])
        previous = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current
        change = current - previous
        change_percent = (change / previous * 100) if previous != 0 else 0
        
        return {
            "symbol": symbol,
            "current_price": round(current, 2),
            "change": round(change, 2),
            "change_percent": round(change_percent, 2),
            "volume": int(hist["Volume"].iloc[-1]),
            "period": period,
            "data_points": len(hist)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Chat endpoint"""
    try:
        msg = request.message.lower()
        
        if request.language == "tr":
            if any(word in msg for word in ["merhaba", "selam"]):
                reply = "Merhaba! ICTSmartPro Trading AI'ye hoş geldiniz."
            elif any(word in msg for word in ["borsa", "hisse", "finans"]):
                reply = "Finans analizi için /api/finance/{sembol} kullanabilirsiniz."
            else:
                reply = "Trading analizi konusunda size nasıl yardımcı olabilirim?"
        else:
            if any(word in msg for word in ["hello", "hi"]):
                reply = "Hello! Welcome to ICTSmartPro Trading AI."
            elif any(word in msg for word in ["stock", "finance"]):
                reply = "Use /api/finance/{symbol} for financial analysis."
            else:
                reply = "How can I help you with trading analysis?"
        
        return {
            "reply": reply,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== STARTUP ====================
@app.on_event("startup")
async def startup_event():
    logger.info(f"🚀 ICTSmartPro API started on port {PORT}")
    logger.info("📊 Trading Analysis Platform Ready")

# ==================== MAIN ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
