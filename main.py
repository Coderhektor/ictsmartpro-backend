from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="ICT Smart Pro")

# Static dosyalar (css, js, resim)
app.mount("/static", StaticFiles(directory="static"), name="static")

# HTML template klasörü
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html", 
        {"request": request, "title": "ICT Smart Pro"}
    )

@app.get("/health")
async def health():
    return {"status": "ok", "message": "Sistem aktif!"}
