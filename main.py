from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
import os

# FastAPI uygulaması
app = FastAPI(title="ICT Smart Pro", description="Cryptocurrency trading signals & analytics")

# Static dosyalar (CSS, JS, images)
# Eğer 'static' klasörü yoksa, deployment'da hata verir — mutlaka ekle!
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except RuntimeError:
    # Geliştirme sırasında static klasörü eksikse uyarı ver, çökme
    print("⚠️  Uyarı: 'static' klasörü bulunamadı. Statik dosyalar servis edilemeyecek.")

# Template motoru (HTML render)
templates = Jinja2Templates(directory="templates")

# Ana sayfa
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "ICT Smart Pro",
            "description": "AI-powered crypto signal generation & arbitrage detection"
        }
    )

# Sağlık kontrolü (Railway bunu ZORUNLU olarak kullanır)
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "ictsmartpro-backend",
        "uptime": "running",
        "port": os.environ.get("PORT", 8000)
    }

# Uygulamayı başlat — Railway 'python main.py' çalıştırır
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0"
    print(f"🚀 Başlatılıyor: http://{host}:{port}")
    print(f"   Health check: http://{host}:{port}/health")
    uvicorn.run(
        app,
        host=host,
        port=port,
        workers=1,
        log_level="info"
    )
