from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles   # bunu ekle
import os

app = FastAPI(
    title="ICT Smart Pro",
    description="Akıllı Teknoloji Çözümleri",
    docs_url="/docs",
    redoc_url=None
)

# Sadece /assets klasörü gibi bir yol aç, kök yolu elleme
app.mount("/assets", StaticFiles(directory=".", html=False), name="assets")  # logo.png'yi /assets/logo.png olarak sunar

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ICT Smart Pro - Akıllı Teknoloji Çözümleri</title>
        <link rel="icon" href="/assets/logo.png" type="image/png">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&display=swap');
            body{margin:0;padding:0;height:100vh;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);
                 display:flex;flex-direction:column;justify-content:center;align-items:center;color:white;font-family:'Segoe UI',sans-serif}
            .logo{width:180px;margin-bottom:30px;animation:pulse 4s infinite;border-radius:20px}
            h1{font-family:'Orbitron',sans-serif;font-size:4.5rem;margin:0;background:linear-gradient(90deg,#00dbde,#fc00ff);
               -webkit-background-clip:text;-webkit-text-fill-color:transparent}
            p{font-size:1.5rem;opacity:0.9;margin-top:20px}
            .status{margin-top:40px;padding:12px 30px;background:rgba(0,255,136,0.15);border:1px solid #00ff88;
                    border-radius:50px;font-weight:bold;color:#00ff88}
            @keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.05)}}
        </style>
    </head>
    <body>
        <img src="/assets/logo.png" alt="ICT Smart Pro Logo" class="logo">
        <h1>ICT Smart Pro</h1>
        <p>Akıllı Teknoloji Çözümleri</p>
        <div class="status">Canlı ve Çalışır Durumda</div>
    </body>
    </html>
    """

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
