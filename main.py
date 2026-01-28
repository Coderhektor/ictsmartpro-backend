from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import logging
import os

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI App
app = FastAPI()

# HTML Content
HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>ICTSmartPro AI</title>
    <style>
        body { font-family: Arial; background: #0f172a; color: white; padding: 40px; }
        .container { max-width: 800px; margin: auto; }
        .logo { color: #60a5fa; font-size: 2em; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">ICTSmartPro × AI Trading</div>
        <h1>🚀 Sistem Çalışıyor!</h1>
        <p>API başarıyla deploy edildi.</p>
        <p>Endpoint'ler:</p>
        <ul>
            <li><a href="/health" style="color:#60a5fa;">/health</a> - Sistem durumu</li>
            <li><a href="/docs" style="color:#60a5fa;">/docs</a> - API dokümantasyonu</li>
        </ul>
    </div>
</body>
</html>
"""

@app.get("/")
async def home():
    return HTMLResponse(content=HTML)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "ICTSmartPro"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
