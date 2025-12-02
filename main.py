# backend/main.py
from fastapi import FastAPI, WebSocket, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import ccxt
import pandas as pd
import asyncio
from datetime import datetime
from typing import Optional
import os

app = FastAPI(title="ICT SMART PRO v11", version="11.0")

# CORS (frontend erişsin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # üretimde kendi domainini yaz
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

exchange = ccxt.binance({'enableRateLimit': True})

# WebSocket bağlantıları
connected_clients = set()

# ================= SENİN SİNYAL MOTORUN (tamamen aynı) =================
def trend_yönü(symbol: str, timeframe: str) -> str:
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        ema20 = df['c'].ewm(span=20).mean()
        return "UP" if ema20.iloc[-1] > ema20.iloc[-10] else "DOWN"
    except:
        return "NEUTRAL"

def destek_direnç_kontrol(df: pd.DataFrame):
    price = df['c'].iloc[-1]
    son_20_yuksek = df['h'].rolling(20).max().iloc[-1]
    son_20_dusuk = df['l'].rolling(20).min().iloc[-1]
    destekte = abs(price - son_20_dusuk) / price < 0.007
    dirençte = abs(price - son_20_yuksek) / price < 0.007
    return destekte, dirençte

def sinyal_üretici(symbol: str, tf: str, mode: str = "serbest"):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=300)
        df = pd.DataFrame(ohlcv, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        if len(df) < 10: return None

        c0, c1, c2 = df['c'].iloc[-1], df['c'].iloc[-2], df['c'].iloc[-3]

        # Mod filtresi
        if mode != "serbest":
            if mode == "daytrade":
                t1, t2 = trend_yönü(symbol, "1d"), trend_yönü(symbol, "4h")
            else:  # scalp
                t1, t2 = trend_yönü(symbol, "1h"), trend_yönü(symbol, "15m")
            if t1 != t2 or t1 == "NEUTRAL":
                return None
            yön_zorunlu = t1
        else:
            yön_zorunlu = None

        # Kapanış kuralı
        if (yön_zorunlu in [None, "UP"]) and c0 > c1 > c2:
            direction = "BUY"
        elif (yön_zorunlu in [None, "DOWN"]) and c0 < c1 < c2:
            direction = "SELL"
        else:
            return None

        destekte, dirençte = destek_direnç_kontrol(df)
        strength = "ULTRA GÜÇLÜ" if (direction == "BUY" and destekte) or (direction == "SELL" and dirençte) else "GÜÇLÜ"

        reasons = []
        if destekte and direction == "BUY": reasons.append("DESTEKTE!")
        if dirençte and direction == "SELL": reasons.append("DİRENÇTE!")
        if len(df) > 3 and df['l'].shift(2).iloc[-1] > df['h'].iloc[-1]: reasons.append("FVG VAR")

        return {
            "symbol": symbol,
            "tf": tf,
            "direction": direction,
            "price": round(c0, 8),
            "strength": strength,
            "reasons": " | ".join(reasons) if reasons else "Temiz kapanış",
            "time": datetime.now().strftime("%d.%m %H:%M")
        }
    except Exception as e:
        print(e)
        return None

# WebSocket
@app.websocket("/ws/signals")
async def websocket_signals(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive
    except:
        connected_clients.remove(websocket)

# Arka plan görevi – her 15 saniyede tüm sembolleri tara
async def background_signal_scanner():
    izlenenler = [
        ("BTC/USDT", "15m", "serbest"),
        ("ETH/USDT", "15m", "serbest"),
        ("XRP/USDT", "5m", "scalp"),
        ("SOL/USDT", "15m", "daytrade"),
        # İstediğin kadar ekle!
    ]
    while True:
        for symbol, tf, mode in izlenenler:
            sinyal = sinyal_üretici(symbol, tf, mode)
            if sinyal:
                data = {**sinyal, "id": datetime.now().timestamp()}
                # WebSocket ile canlı yayınla
                for client in list(connected_clients):
                    try:
                        await client.send_json(data)
                    except:
                        connected_clients.remove(client)
                # Konsola da yaz (log)
                print(f"ALİŞ" if sinyal["direction"]=="BUY" else "SATIŞ", sinyal['symbol'], sinyal['price'])
        await asyncio.sleep(15)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_signal_scanner())

@app.get("/")
def ana_sayfa():
    return {"message": "ICT SMART PRO v11 çalışıyor!", "status": "pump it!"}

@app.get("/health")
def health():
    return {"status": "healthy"}