from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from PIL import Image
import pandas as pd
import yfinance as yf
import io
import logging
import os
from typing import Optional
from datetime import datetime, timedelta
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import json
from pathlib import Path

# ==================== KONFİGÜRASYON ====================
PORT = int(os.environ.get("PORT", 8000))
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
MODEL_DIR = os.environ.get("MODEL_DIR", "/tmp/.easyocr")

# Logging
logging.basicConfig(
    level=logging.INFO if not DEBUG else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==================== FASTAPI APP ====================
app = FastAPI(
    title="ICTSmartPro.ai API",
    description="AI Chatbot, OCR, File Processing, Finance API",
    version="2.1.1",
    docs_url="/docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None
)

# ==================== RATE LIMITING ====================
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],
    storage_uri="memory://"
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ==================== CORS ====================
ALLOWED_ORIGINS = [
    "https://ictsmartpro.ai",
    "https://www.ictsmartpro.ai",
    "https://*.vercel.app",
    "http://localhost:3000",
    "http://localhost:5000",
    "http://localhost:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# ==================== MODELS ====================
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"
    language: Optional[str] = "tr"

class ChatResponse(BaseModel):
    reply: str
    confidence: str = "medium"
    timestamp: str
    session_id: Optional[str] = None

class FinanceRequest(BaseModel):
    symbol: str
    period: Optional[str] = "1mo"
    interval: Optional[str] = "1d"

class FinanceResponse(BaseModel):
    symbol: str
    currency: str
    current_price: float
    previous_close: float
    day_change: float
    day_change_percent: float
    volume: int
    market_cap: Optional[float] = None
    data_points: int
    fetched_at: str

class OCRResponse(BaseModel):
    text: str
    filename: str
    language: str
    processing_time: float
    word_count: int
    confidence: str

class HealthResponse(BaseModel):
    status: str
    version: str
    uptime: float
    timestamp: str
    services: dict

# ==================== CACHE ====================
class SimpleCache:
    def __init__(self, ttl_seconds=300):
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get(self, key):
        if key in self.cache:
            value, timestamp = self.cache[key]
            if datetime.now().timestamp() - timestamp < self.ttl:
                return value
            else:
                del self.cache[key]
        return None
    
    def set(self, key, value):
        self.cache[key] = (value, datetime.now().timestamp())
    
    def clear_old(self):
        now = datetime.now().timestamp()
        keys_to_delete = []
        for key, (_, timestamp) in self.cache.items():
            if now - timestamp > self.ttl:
                keys_to_delete.append(key)
        for key in keys_to_delete:
            del self.cache[key]

finance_cache = SimpleCache(ttl_seconds=60)
chat_cache = SimpleCache(ttl_seconds=300)

# ==================== OCR SERVICE (LAZY LOADING + FAILURE HANDLING) ====================
_easyocr_reader = None
_ocr_loading = False
_ocr_failed = False

def get_ocr_reader(languages=['tr', 'en']):
    global _easyocr_reader, _ocr_loading, _ocr_failed
    
    if _ocr_failed:
        raise HTTPException(
            status_code=503,
            detail="OCR servisi kalıcı olarak başlatılamadı (önceki denemede hata)"
        )
    
    if _easyocr_reader is not None:
        return _easyocr_reader
    
    if _ocr_loading:
        for _ in range(12):  # max 6 saniye bekle
            import time
            time.sleep(0.5)
            if _easyocr_reader is not None:
                return _easyocr_reader
            if _ocr_failed:
                raise HTTPException(status_code=503, detail="OCR yükleme başarısız")
        raise HTTPException(status_code=503, detail="OCR yükleme zaman aşımına uğradı")
    
    try:
        _ocr_loading = True
        import easyocr
        
        Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)
        
        logger.info(f"OCR model yükleniyor ({', '.join(languages)})...")
        _easyocr_reader = easyocr.Reader(
            languages,
            gpu=False,
            model_storage_directory=MODEL_DIR,
            download_enabled=True,
            verbose=False  # log kirliliğini azaltmak için
        )
        logger.info("OCR model başarıyla yüklendi")
        return _easyocr_reader
    except Exception as e:
        logger.error(f"OCR yükleme hatası: {e}", exc_info=True)
        _ocr_failed = True
        raise HTTPException(
            status_code=503,
            detail=f"OCR servisi başlatılamadı: {str(e)}"
        )
    finally:
        _ocr_loading = False

# ==================== CHAT ENGINE ====================
class ChatEngine:
    def __init__(self):
        self.context = {}
    
    def get_response(self, message: str, session_id: str = "default", language: str = "tr") -> dict:
        msg = message.lower().strip()
        
        greetings_tr = ["merhaba", "selam", "günaydın", "iyi günler", "nasılsın", "naber"]
        greetings_en = ["hello", "hi", "hey", "good morning", "how are you"]
        
        if any(greet in msg for greet in (greetings_tr if language == "tr" else greetings_en)):
            return {
                "reply": "Merhaba! ICTSmartPro AI asistanına hoş geldiniz. Size nasıl yardımcı olabilirim?" if language == "tr" else "Hello! Welcome to ICTSmartPro AI assistant. How can I help you?",
                "confidence": "high"
            }
        
        finance_keywords = {
            "tr": ["borsa", "hisse", "finans", "yatırım", "dolar", "altın", "bitcoin"],
            "en": ["stock", "finance", "investment", "market", "currency", "gold", "bitcoin"]
        }
        
        if any(keyword in msg for keyword in finance_keywords.get(language, finance_keywords["en"])):
            return {
                "reply": "Finans verileri için /finance endpoint'ini kullanabilirsiniz. Örneğin: AAPL, TSLA, BTC-USD" if language == "tr" else "Use /finance endpoint for financial data. Example: AAPL, TSLA, BTC-USD",
                "confidence": "high"
            }
        
        ocr_keywords = {
            "tr": ["ocr", "metin oku", "resimden yazı", "fotoğraf yazı"],
            "en": ["ocr", "text extract", "image to text", "read text"]
        }
        
        if any(keyword in msg for keyword in ocr_keywords.get(language, ocr_keywords["en"])):
            return {
                "reply": "Resimden metin çıkarmak için /ocr endpoint'ine JPEG/PNG/WEBP yükleyebilirsiniz (max 5MB)" if language == "tr" else "Upload JPEG/PNG/WEBP to /ocr endpoint to extract text (max 5MB)",
                "confidence": "high"
            }
        
        file_keywords = {
            "tr": ["dosya", "yükle", "upload", "işle"],
            "en": ["file", "upload", "process", "document"]
        }
        
        if any(keyword in msg for keyword in file_keywords.get(language, file_keywords["en"])):
            return {
                "reply": "Dosya işlemek için /file endpoint'ini kullanabilirsiniz (CSV, TXT, JSON, Excel)" if language == "tr" else "Use /file endpoint to process files (CSV, TXT, JSON, Excel)",
                "confidence": "high"
            }
        
        help_keywords = {
            "tr": ["yardım", "ne yapabilirsin", "özellikler", "komutlar"],
            "en": ["help", "what can you do", "features", "commands"]
        }
        
        if any(keyword in msg for keyword in help_keywords.get(language, help_keywords["en"])):
            return {
                "reply": """Yardım:
🤖 Chat: Doğrudan konuşabilirsiniz
📊 Finance: /finance/{sembol}
🖼️ OCR: /ocr ile resimden metin
📁 File: /file ile dosya işleme""",
                "confidence": "high"
            }
        
        return {
            "reply": "Daha spesifik bir soru sorarsanız daha iyi yardımcı olabilirim!" if language == "tr" else "Ask more specifically and I can help better!",
            "confidence": "medium"
        }

chat_engine = ChatEngine()

# ==================== ENDPOINTS ====================
@app.get("/")
async def root():
    return {
        "service": "ICTSmartPro.ai API",
        "status": "operational",
        "version": "2.1.1",
        "environment": "development" if DEBUG else "production",
        "endpoints": {
            "chat": "POST /chat",
            "ocr": "POST /ocr",
            "finance": "GET /finance/{symbol}",
            "file": "POST /file",
            "health": "GET /health"
        }
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    ocr_status = "ready" if _easyocr_reader is not None else "failed" if _ocr_failed else "lazy_loading"
    
    services = {
        "api": "healthy",
        "ocr": ocr_status,
        "cache": "active"
    }
    
    uptime = 0
    if hasattr(app.state, 'start_time'):
        uptime = (datetime.now() - app.state.start_time).total_seconds()
    
    return HealthResponse(
        status="healthy" if ocr_status != "failed" else "degraded",
        version="2.1.1",
        uptime=uptime,
        timestamp=datetime.utcnow().isoformat(),
        services=services
    )

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("100/minute")
async def chat_endpoint(request: Request, chat_req: ChatRequest):
    cache_key = f"chat_{chat_req.session_id}_{chat_req.message[:50]}"
    cached = chat_cache.get(cache_key)
    
    if cached and not DEBUG:
        return ChatResponse(
            reply=cached["reply"],
            confidence=cached["confidence"],
            timestamp=datetime.utcnow().isoformat(),
            session_id=chat_req.session_id
        )
    
    if not chat_req.message.strip():
        raise HTTPException(status_code=400, detail="Mesaj boş olamaz")
    
    try:
        response = chat_engine.get_response(
            chat_req.message,
            chat_req.session_id,
            chat_req.language
        )
        chat_cache.set(cache_key, response)
        
        return ChatResponse(
            reply=response["reply"],
            confidence=response["confidence"],
            timestamp=datetime.utcnow().isoformat(),
            session_id=chat_req.session_id
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail="Chat servisinde sorun oluştu")

@app.post("/ocr", response_model=OCRResponse)
@limiter.limit("10/minute")
async def ocr_endpoint(request: Request, file: UploadFile = File(...)):
    start_time = datetime.now()
    
    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/jpg"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Desteklenmeyen dosya türü: {file.content_type}")
    
    max_size = 5 * 1024 * 1024
    await file.seek(0, 2)
    file_size = await file.tell()
    await file.seek(0)
    
    if file_size > max_size:
        raise HTTPException(status_code=413, detail="Dosya çok büyük (max 5MB)")
    
    try:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        
        if image.mode in ('RGBA', 'LA', 'P'):
            image = image.convert('RGB')
        
        reader = get_ocr_reader(['tr', 'en'])
        
        result = reader.readtext(image, detail=0)
        text = " ".join(result).strip()
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return OCRResponse(
            text=text,
            filename=file.filename,
            language="tr+en",
            processing_time=round(processing_time, 2),
            word_count=len(text.split()) if text else 0,
            confidence="high" if text else "low"
        )
        
    except Exception as e:
        logger.error(f"OCR error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"OCR işlem hatası: {str(e)}")

@app.get("/finance/{symbol}", response_model=FinanceResponse)
@limiter.limit("30/minute")
async def finance_endpoint(
    request: Request,
    symbol: str,
    period: Optional[str] = "1mo",
    interval: Optional[str] = "1d"
):
    cache_key = f"finance_{symbol.upper()}_{period}_{interval}"
    cached = finance_cache.get(cache_key)
    
    if cached and not DEBUG:
        return FinanceResponse(**cached)
    
    try:
        symbol = symbol.upper().strip()
        stock = yf.Ticker(symbol)
        info = stock.info
        hist = stock.history(period=period, interval=interval)
        
        if hist.empty:
            raise HTTPException(status_code=404, detail=f"'{symbol}' için veri bulunamadı")
        
        current_price = hist['Close'].iloc[-1]
        previous_close = hist['Close'].iloc[-2] if len(hist) > 1 else current_price
        day_change = current_price - previous_close
        day_change_percent = (day_change / previous_close) * 100 if previous_close != 0 else 0
        
        response_data = {
            "symbol": symbol,
            "currency": info.get('currency', 'USD'),
            "current_price": round(float(current_price), 2),
            "previous_close": round(float(previous_close), 2),
            "day_change": round(float(day_change), 2),
            "day_change_percent": round(float(day_change_percent), 2),
            "volume": int(hist['Volume'].iloc[-1]),
            "market_cap": info.get('marketCap'),
            "data_points": len(hist),
            "fetched_at": datetime.utcnow().isoformat()
        }
        
        finance_cache.set(cache_key, response_data)
        return FinanceResponse(**response_data)
        
    except Exception as e:
        logger.error(f"Finance error {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Finans verisi alınamadı: {str(e)}")

@app.post("/file")
@limiter.limit("20/minute")
async def file_endpoint(request: Request, file: UploadFile = File(...)):
    try:
        content = await file.read()
        file_size = len(content)
        
        max_size = 10 * 1024 * 1024
        if file_size > max_size:
            raise HTTPException(status_code=413, detail="Dosya çok büyük (max 10MB)")
        
        filename = file.filename
        extension = filename.split('.')[-1].lower() if '.' in filename else ""
        file_type = file.content_type or "application/octet-stream"
        
        result = {
            "filename": filename,
            "size_bytes": file_size,
            "size_mb": round(file_size / (1024 * 1024), 2),
            "type": file_type,
            "extension": extension,
            "processed_at": datetime.utcnow().isoformat()
        }
        
        if extension in ['csv', 'txt'] or 'text' in file_type.lower():
            try:
                content_str = content.decode('utf-8', errors='ignore')
                lines = content_str.splitlines()
                result["line_count"] = len(lines)
                result["sample_lines"] = lines[:5]
            except:
                result["note"] = "Metin decode edilemedi"
        
        elif extension == 'json' or 'json' in file_type.lower():
            try:
                json_data = json.loads(content.decode('utf-8', errors='ignore'))
                result["json_valid"] = True
                result["structure"] = "dict" if isinstance(json_data, dict) else "list"
            except:
                result["json_valid"] = False
        
        elif extension in ['xlsx', 'xls'] or 'excel' in file_type.lower():
            try:
                excel_data = pd.read_excel(io.BytesIO(content))
                result["rows"] = len(excel_data)
                result["columns"] = list(excel_data.columns)
            except Exception as e:
                result["excel_error"] = str(e)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File processing error: {e}")
        raise HTTPException(status_code=500, detail=f"Dosya işlenemedi: {str(e)}")

# ==================== STARTUP & SHUTDOWN ====================
@app.on_event("startup")
async def startup_event():
    app.state.start_time = datetime.now()
    
    logger.info("🚀 API başlatılıyor...")
    logger.info(f"Version: 2.1.1 | Env: {'dev' if DEBUG else 'prod'} | Port: {PORT}")
    
    # OCR ön yüklemesi YAPILMIYOR → sadece istek geldiğinde yükleniyor

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("👋 API kapanıyor...")
    finance_cache.clear_old()
    chat_cache.clear_old()
    global _easyocr_reader
    _easyocr_reader = None  # referansı serbest bırak
    logger.info("Temizlik tamamlandı")

# ==================== ERROR HANDLERS ====================
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "path": request.url.path}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Sunucu hatası", "path": request.url.path}
    )

# ==================== MAIN ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=DEBUG,
        log_level="info" if not DEBUG else "debug"
    )
