from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="ICT Smart Pro", docs_url="/docs", redoc_url=None)


@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <h1 style="color:#764ba2; text-align:center; margin-top:100px; font-family:system-ui">
    ICT Smart Pro çalışıyor!
    </h1>
    <p style="text-align:center; font-size:20px;">Deploy başarılı</p>
    """


@app.get("/health")
async def health():
    return {"status": "ok"}


# BU KISIM EKLENECEK (en alta)
if __name__ == "__main__":
    import uvicorn
    import os
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
