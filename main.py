from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image
import pandas as pd
import yfinance as yf
import io
import logging
import os
import json
from datetime import datetime
from typing import Optional
import sys

# ==================== KONFİGÜRASYON ====================
PORT = int(os.environ.get("PORT", 8000))
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
MODEL_DIR = os.environ.get("MODEL_DIR", "/app/models")

# Logging
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== FASTAPI APP ====================
app = FastAPI(
    title="ICTSmartPro AI API",
    description="AI Chatbot, OCR, File Processing & Finance API",
    version="2.0.0",
    docs_url="/docs" if DEBUG else None,
    redoc_url=None
)

# ==================== CORS ====================
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

# ==================== OCR SETUP ====================
OCR_AVAILABLE = False
ocr_reader = None

try:
    import easyocr
    OCR_AVAILABLE = True
    logger.info("✅ EasyOCR imported successfully")
except ImportError as e:
    logger.error(f"❌ EasyOCR import failed: {e}")
    OCR_AVAILABLE = False

def get_ocr_reader():
    """Load OCR reader (lazy loading)"""
    global ocr_reader
    if not OCR_AVAILABLE:
        return None
    
    if ocr_reader is None:
        try:
            logger.info("🔄 Loading OCR models...")
            # Model dizinini oluştur
            os.makedirs(MODEL_DIR, exist_ok=True)
            
            # Daha az bellek kullanan ayarlar
            ocr_reader = easyocr.Reader(
                ['tr', 'en'],
                gpu=False,
                model_storage_directory=MODEL_DIR,
                download_enabled=True,
                verbose=False
            )
            logger.info("✅ OCR models loaded successfully")
        except Exception as e:
            logger.error(f"❌ OCR loading failed: {e}")
            ocr_reader = None
    
    return ocr_reader

# ==================== CHAT BOT ====================
def get_chat_response(message: str, language: str = "tr") -> dict:
    """Simple chatbot response"""
    msg = message.lower().strip()
    
    if language == "tr":
        if any(word in msg for word in ["merhaba", "selam", "hey"]):
            return {"reply": "Merhaba! ICTSmartPro AI asistanına hoş geldiniz. Size nasıl yardımcı olabilirim?", "confidence": "high"}
        
        if any(word in msg for word in ["borsa", "hisse", "finans"]):
            return {"reply": "Finans verileri için /finance/{sembol} endpoint'ini kullanabilirsiniz. Örneğin: /finance/AAPL", "confidence": "high"}
        
        if any(word in msg for word in ["ocr", "metin oku", "resim"]):
            return {"reply": "Resimden metin okumak için /ocr endpoint'ine JPEG/PNG dosyası yükleyin (max 5MB).", "confidence": "high"}
        
        if any(word in msg for word in ["yardım", "help"]):
            return {"reply": """Yardım merkezi:
📊 Finance: /finance/{sembol}
🖼️ OCR: /ocr endpoint
📁 File: /upload endpoint
💬 Chat: Benimle konuşun""", "confidence": "high"}
    
    else:  # English
        if any(word in msg for word in ["hello", "hi", "hey"]):
            return {"reply": "Hello! Welcome to ICTSmartPro AI assistant. How can I help you?", "confidence": "high"}
        
        if any(word in msg for word in ["stock", "finance", "market"]):
            return {"reply": "Use /finance/{symbol} endpoint for financial data. Example: /finance/AAPL", "confidence": "high"}
        
        if any(word in msg for word in ["ocr", "text extract", "image"]):
            return {"reply": "Upload JPEG/PNG file to /ocr endpoint for text extraction (max 5MB).", "confidence": "high"}
        
        if any(word in msg for word in ["help", "what can you do"]):
            return {"reply": """Help Center:
📊 Finance: /finance/{symbol}
🖼️ OCR: /ocr endpoint
📁 File: /upload endpoint
💬 Chat: Talk to me""", "confidence": "high"}
    
    # Default response
    if language == "tr":
        return {"reply": "Anladım. Daha spesifik bir soru sorabilir misiniz?", "confidence": "medium"}
    else:
        return {"reply": "I understand. Can you ask a more specific question?", "confidence": "medium"}

# ==================== ENDPOINTS ====================
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "ICTSmartPro AI API",
        "version": "2.0.0",
        "status": "operational",
        "endpoints": {
            "chat": "POST /chat",
            "ocr": "POST /ocr",
            "finance": "GET /finance/{symbol}",
            "upload": "POST /upload",
            "health": "GET /health"
        }
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "ocr_available": OCR_AVAILABLE,
        "environment": "production"
    }

@app.post("/chat")
async def chat(request: ChatRequest):
    """Chat endpoint"""
    try:
        response = get_chat_response(request.message, request.language)
        return {
            **response,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    """OCR endpoint - extract text from images"""
    # File validation
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")
    
    # Size validation (5MB max)
    max_size = 5 * 1024 * 1024
    contents = await file.read()
    if len(contents) > max_size:
        raise HTTPException(status_code=413, detail="File too large (max 5MB)")
    
    try:
        # Load and process image
        image = Image.open(io.BytesIO(contents))
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        # Get OCR reader
        reader = get_ocr_reader()
        if reader is None:
            raise HTTPException(status_code=503, detail="OCR service is not available")
        
        # Perform OCR
        start_time = datetime.now()
        results = reader.readtext(image, detail=0, paragraph=True)
        extracted_text = " ".join(results).strip()
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return {
            "filename": file.filename,
            "text": extracted_text,
            "word_count": len(extracted_text.split()),
            "processing_time": round(processing_time, 2),
            "success": bool(extracted_text)
        }
        
    except Exception as e:
        logger.error(f"OCR processing error: {e}")
        raise HTTPException(status_code=500, detail=f"OCR processing failed: {str(e)}")

@app.get("/finance/{symbol}")
async def finance(symbol: str, period: str = "1mo"):
    """Finance data endpoint"""
    try:
        symbol = symbol.upper().strip()
        
        # Get stock data
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        
        if hist.empty:
            raise HTTPException(status_code=404, detail=f"No data found for symbol: {symbol}")
        
        # Calculate metrics
        current = float(hist["Close"].iloc[-1])
        previous = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current
        change = current - previous
        change_percent = (change / previous * 100) if previous != 0 else 0
        
        return {
            "symbol": symbol,
            "current_price": round(current, 2),
            "previous_close": round(previous, 2),
            "change": round(change, 2),
            "change_percent": round(change_percent, 2),
            "volume": int(hist["Volume"].iloc[-1]),
            "period": period,
            "data_points": len(hist),
            "fetched_at": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Finance error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch finance data: {str(e)}")

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """File upload and processing endpoint"""
    try:
        # Read file
        contents = await file.read()
        file_size = len(contents)
        
        result = {
            "filename": file.filename,
            "content_type": file.content_type or "unknown",
            "size_bytes": file_size,
            "size_mb": round(file_size / (1024 * 1024), 2),
            "processed_at": datetime.now().isoformat(),
            "analysis": {}
        }
        
        # Process based on file type
        filename_lower = file.filename.lower()
        
        # CSV files
        if filename_lower.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(contents))
                result["analysis"] = {
                    "type": "csv",
                    "rows": len(df),
                    "columns": list(df.columns),
                    "sample": df.head(2).to_dict(orient="records")
                }
            except Exception as e:
                result["analysis"] = {"type": "csv", "error": str(e)}
        
        # JSON files
        elif filename_lower.endswith(".json"):
            try:
                data = json.loads(contents.decode("utf-8"))
                if isinstance(data, dict):
                    result["analysis"] = {
                        "type": "json",
                        "keys": list(data.keys()),
                        "key_count": len(data)
                    }
                else:
                    result["analysis"] = {
                        "type": "json",
                        "list_length": len(data)
                    }
            except Exception as e:
                result["analysis"] = {"type": "json", "error": str(e)}
        
        # Text files
        elif filename_lower.endswith(".txt"):
            try:
                text = contents.decode("utf-8", errors="ignore")
                lines = text.splitlines()
                result["analysis"] = {
                    "type": "text",
                    "lines": len(lines),
                    "words": len(text.split()),
                    "sample": lines[:3] if lines else []
                }
            except Exception as e:
                result["analysis"] = {"type": "text", "error": str(e)}
        
        # Excel files
        elif filename_lower.endswith((".xlsx", ".xls")):
            try:
                df = pd.read_excel(io.BytesIO(contents))
                result["analysis"] = {
                    "type": "excel",
                    "rows": len(df),
                    "columns": list(df.columns),
                    "column_count": len(df.columns)
                }
            except Exception as e:
                result["analysis"] = {"type": "excel", "error": str(e)}
        
        # Other files
        else:
            result["analysis"] = {"type": "binary", "note": "No content analysis performed"}
        
        return result
        
    except Exception as e:
        logger.error(f"File upload error: {e}")
        raise HTTPException(status_code=500, detail=f"File processing failed: {str(e)}")

# ==================== STARTUP EVENT ====================
@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    logger.info(f"🚀 ICTSmartPro API starting on port {PORT}")
    logger.info(f"📁 Model directory: {MODEL_DIR}")
    logger.info(f"🔧 OCR available: {OCR_AVAILABLE}")
    
    # Pre-load OCR in background (optional)
    if OCR_AVAILABLE:
        import threading
        def load_ocr_background():
            try:
                get_ocr_reader()
            except Exception as e:
                logger.warning(f"Background OCR load failed: {e}")
        
        thread = threading.Thread(target=load_ocr_background, daemon=True)
        thread.start()
        logger.info("🔄 OCR pre-loading in background")

# ==================== MAIN ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        access_log=False  # Railway'de access log'ları kapat
    )
