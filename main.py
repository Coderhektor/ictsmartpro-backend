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
import json
from pathlib import Path
import sys

# ==================== KONFİGÜRASYON ====================
PORT = int(os.environ.get("PORT", 8000))
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
MODEL_DIR = os.environ.get("MODEL_DIR", "./models")

# Logging - basit hale getir
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==================== FASTAPI APP ====================
app = FastAPI(
    title="ICTSmartPro.ai API",
    description="AI Chatbot, OCR, File Processing, Finance API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# ==================== CORS ====================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tüm origin'lere izin ver (güvenlik için daha sonra kısıtlayın)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

class FinanceResponse(BaseModel):
    symbol: str
    currency: str
    current_price: float
    previous_close: float
    day_change: float
    day_change_percent: float
    volume: int
    data_points: int
    fetched_at: str

class OCRResponse(BaseModel):
    text: str
    filename: str
    processing_time: float
    word_count: int

class FileResponse(BaseModel):
    filename: str
    size_bytes: int
    size_mb: float
    file_type: str
    processed_at: str

# ==================== OCR SERVICE ====================
try:
    import easyocr
    EASYOCR_AVAILABLE = True
    logger.info("✅ EasyOCR başarıyla import edildi")
except ImportError as e:
    EASYOCR_AVAILABLE = False
    logger.warning(f"⚠️ EasyOCR import edilemedi: {e}")

def get_ocr_reader():
    """OCR reader'ı başlat"""
    if not EASYOCR_AVAILABLE:
        raise HTTPException(status_code=503, detail="OCR servisi mevcut değil")
    
    try:
        # Model dizinini oluştur
        Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)
        
        logger.info("OCR modeli yükleniyor...")
        reader = easyocr.Reader(
            ['tr', 'en'],
            gpu=False,
            model_storage_directory=MODEL_DIR,
            download_enabled=True
        )
        logger.info("OCR modeli başarıyla yüklendi")
        return reader
    except Exception as e:
        logger.error(f"OCR model yükleme hatası: {e}")
        raise HTTPException(status_code=500, detail=f"OCR başlatılamadı: {str(e)}")

# OCR reader'ı global olarak sakla
ocr_reader = None

def ensure_ocr_loaded():
    """OCR reader'ın yüklü olduğundan emin ol"""
    global ocr_reader
    if ocr_reader is None:
        ocr_reader = get_ocr_reader()
    return ocr_reader

# ==================== CHAT ENGINE ====================
class ChatEngine:
    def get_response(self, message: str, language: str = "tr") -> dict:
        message_lower = message.lower().strip()
        
        # Basit cevaplar
        if language == "tr":
            if any(word in message_lower for word in ["merhaba", "selam", "hey"]):
                return {"reply": "Merhaba! ICTSmartPro AI asistanına hoş geldiniz. Size nasıl yardımcı olabilirim?", "confidence": "high"}
            
            if any(word in message_lower for word in ["borsa", "hisse", "finans"]):
                return {"reply": "Finans verileri için /finance/{sembol} endpoint'ini kullanabilirsiniz. Örnek: /finance/AAPL", "confidence": "high"}
            
            if any(word in message_lower for word in ["ocr", "metin oku", "resimden yazı"]):
                return {"reply": "Resimden metin okumak için /ocr endpoint'ine JPEG veya PNG dosyası yükleyin.", "confidence": "high"}
            
            if any(word in message_lower for word in ["yardım", "ne yapabilirsin"]):
                return {"reply": "Ben bir AI asistanıyım. Size şunlarda yardımcı olabilirim:\n1. Finans verileri\n2. Resimden metin okuma (OCR)\n3. Dosya işleme\n4. Genel sohbet", "confidence": "high"}
        
        else:  # English
            if any(word in message_lower for word in ["hello", "hi", "hey"]):
                return {"reply": "Hello! Welcome to ICTSmartPro AI assistant. How can I help you?", "confidence": "high"}
            
            if any(word in message_lower for word in ["stock", "finance", "market"]):
                return {"reply": "For financial data, use the /finance/{symbol} endpoint. Example: /finance/AAPL", "confidence": "high"}
            
            if any(word in message_lower for word in ["ocr", "text extract", "image to text"]):
                return {"reply": "Upload a JPEG or PNG file to the /ocr endpoint to extract text from images.", "confidence": "high"}
            
            if any(word in message_lower for word in ["help", "what can you do"]):
                return {"reply": "I'm an AI assistant. I can help you with:\n1. Financial data\n2. Text extraction from images (OCR)\n3. File processing\n4. General chat", "confidence": "high"}
        
        # Default response
        if language == "tr":
            return {"reply": "Anladım. Daha spesifik bir soru sorarsanız size yardımcı olabilirim.", "confidence": "medium"}
        else:
            return {"reply": "I understand. If you ask a more specific question, I can help you better.", "confidence": "medium"}

chat_engine = ChatEngine()

# ==================== ENDPOINTS ====================
@app.get("/")
async def root():
    return {
        "service": "ICTSmartPro.ai API",
        "status": "online",
        "version": "2.0.0",
        "endpoints": {
            "chat": "POST /chat",
            "ocr": "POST /ocr",
            "finance": "GET /finance/{symbol}",
            "file": "POST /file",
            "health": "GET /health"
        }
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "ocr_available": EASYOCR_AVAILABLE,
        "version": "2.0.0"
    }

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(chat_req: ChatRequest):
    try:
        if not chat_req.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        response = chat_engine.get_response(chat_req.message, chat_req.language)
        
        return ChatResponse(
            reply=response["reply"],
            confidence=response["confidence"],
            timestamp=datetime.now().isoformat(),
            session_id=chat_req.session_id
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

@app.post("/ocr", response_model=OCRResponse)
async def ocr_endpoint(file: UploadFile = File(...)):
    start_time = datetime.now()
    
    # Dosya türünü kontrol et
    allowed_types = ["image/jpeg", "image/png", "image/jpg"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only JPEG and PNG files are allowed")
    
    # Dosya boyutunu kontrol et (max 10MB)
    max_size = 10 * 1024 * 1024
    contents = await file.read()
    if len(contents) > max_size:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")
    
    try:
        # Resmi aç
        image = Image.open(io.BytesIO(contents))
        
        # OCR için optimize et
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # OCR'ı yükle ve çalıştır
        reader = ensure_ocr_loaded()
        
        # OCR işlemini yap
        results = reader.readtext(image, detail=0)
        extracted_text = " ".join(results)
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return OCRResponse(
            text=extracted_text,
            filename=file.filename,
            processing_time=round(processing_time, 2),
            word_count=len(extracted_text.split())
        )
        
    except Exception as e:
        logger.error(f"OCR processing error: {e}")
        raise HTTPException(status_code=500, detail=f"OCR processing failed: {str(e)}")

@app.get("/finance/{symbol}")
async def finance_endpoint(symbol: str, period: str = "1mo", interval: str = "1d"):
    try:
        # Sembolü temizle
        symbol = symbol.upper().strip()
        
        # Finans verilerini al
        ticker = yf.Ticker(symbol)
        
        # Temel bilgiler
        info = ticker.info
        
        # Geçmiş veriler
        history = ticker.history(period=period, interval=interval)
        
        if history.empty:
            raise HTTPException(status_code=404, detail=f"No data found for symbol: {symbol}")
        
        # Hesaplamalar
        current_price = float(history['Close'].iloc[-1])
        previous_close = float(history['Close'].iloc[-2]) if len(history) > 1 else current_price
        day_change = current_price - previous_close
        day_change_percent = (day_change / previous_close) * 100 if previous_close != 0 else 0
        
        response_data = {
            "symbol": symbol,
            "currency": info.get('currency', 'USD'),
            "current_price": round(current_price, 2),
            "previous_close": round(previous_close, 2),
            "day_change": round(day_change, 2),
            "day_change_percent": round(day_change_percent, 2),
            "volume": int(history['Volume'].iloc[-1]),
            "data_points": len(history),
            "fetched_at": datetime.now().isoformat()
        }
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Finance error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch finance data: {str(e)}")

@app.post("/file")
async def file_endpoint(file: UploadFile = File(...)):
    try:
        # Dosyayı oku
        content = await file.read()
        file_size = len(content)
        
        # Dosya bilgilerini hazırla
        result = {
            "filename": file.filename,
            "size_bytes": file_size,
            "size_mb": round(file_size / (1024 * 1024), 2),
            "file_type": file.content_type or "unknown",
            "processed_at": datetime.now().isoformat(),
            "info": {}
        }
        
        # Dosya uzantısına göre işle
        filename_lower = file.filename.lower()
        
        # CSV veya TXT dosyası
        if filename_lower.endswith(('.csv', '.txt')):
            try:
                text_content = content.decode('utf-8')
                lines = text_content.split('\n')
                result["info"] = {
                    "type": "text/csv",
                    "line_count": len(lines),
                    "sample": lines[:3] if lines else []
                }
            except:
                result["info"] = {"type": "text/csv", "error": "Could not decode as text"}
        
        # JSON dosyası
        elif filename_lower.endswith('.json'):
            try:
                json_content = json.loads(content.decode('utf-8'))
                if isinstance(json_content, dict):
                    result["info"] = {
                        "type": "json",
                        "keys": list(json_content.keys()),
                        "key_count": len(json_content)
                    }
                else:
                    result["info"] = {
                        "type": "json",
                        "list_length": len(json_content)
                    }
            except:
                result["info"] = {"type": "json", "error": "Invalid JSON"}
        
        # Excel dosyası
        elif filename_lower.endswith(('.xlsx', '.xls')):
            try:
                excel_data = pd.read_excel(io.BytesIO(content))
                result["info"] = {
                    "type": "excel",
                    "rows": len(excel_data),
                    "columns": list(excel_data.columns),
                    "column_count": len(excel_data.columns)
                }
            except Exception as e:
                result["info"] = {"type": "excel", "error": str(e)}
        
        # Diğer dosyalar
        else:
            result["info"] = {"type": "binary", "note": "Binary file - no content analysis"}
        
        return result
        
    except Exception as e:
        logger.error(f"File processing error: {e}")
        raise HTTPException(status_code=500, detail=f"File processing failed: {str(e)}")

# ==================== STARTUP ====================
@app.on_event("startup")
async def startup_event():
    logger.info("=" * 50)
    logger.info("🚀 ICTSmartPro.ai API Starting...")
    logger.info(f"📦 Version: 2.0.0")
    logger.info(f"🌍 Environment: {'Development' if DEBUG else 'Production'}")
    logger.info(f"🔌 Port: {PORT}")
    logger.info(f"📁 Model Directory: {MODEL_DIR}")
    logger.info(f"🔧 OCR Available: {EASYOCR_AVAILABLE}")
    logger.info("=" * 50)

# ==================== ERROR HANDLING ====================
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )

# ==================== MAIN ====================
if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="debug" if DEBUG else "info",
        reload=DEBUG
    )
