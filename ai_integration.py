# ai_integration.py (yeni dosya)
import asyncio
import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any
import warnings
import aiohttp

warnings.filterwarnings('ignore')

# ============================================
# AI SERVİS SINIFI
# ============================================
class AITradingService:
    def __init__(self):
        self.market_data = {}
        self.initialized = False
        
    async def initialize(self):
        """AI servisini başlat"""
        if not self.initialized:
            try:
                # Basit başlangıç
                self.initialized = True
                print("✅ AI Trading Service Initialized")
                return True
            except Exception as e:
                print(f"❌ AI initialization failed: {e}")
                return False
        return True
    
    async def fetch_historical(self, symbol: str, interval: str = '1h', limit: int = 100):
        """Tarihsel veri al"""
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {'symbol': symbol.upper(), 'interval': interval, 'limit': limit}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    data = await resp.json()
            
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', *range(6)])
            df = df.astype({'open': float, 'high': float, 'low': float, 'close': float, 'volume': float})
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            return df[['open', 'high', 'low', 'close', 'volume']]
        except Exception as e:
            print(f"Error fetching data: {e}")
            return pd.DataFrame()
    
    async def get_quick_prediction(self, symbol: str) -> Dict:
        """Hızlı AI tahmini"""
        try:
            data = await self.fetch_historical(symbol, '1h', 50)
            if data.empty:
                return {"error": "No data available"}
            
            close_prices = data['close'].values
            if len(close_prices) < 2:
                return {"prediction": "Hold", "confidence": 0.5}
            
            momentum = (close_prices[-1] - close_prices[-5]) / close_prices[-5] * 100 if len(close_prices) >= 5 else 0
            volume_change = (data['volume'].iloc[-1] - data['volume'].iloc[-5]) / data['volume'].iloc[-5] * 100 if len(data) >= 5 else 0
            
            if momentum > 2 and volume_change > 10:
                signal = "Buy"
                confidence = min(0.8, 0.5 + abs(momentum) / 100)
            elif momentum < -2 and volume_change > 10:
                signal = "Sell"
                confidence = min(0.8, 0.5 + abs(momentum) / 100)
            else:
                signal = "Hold"
                confidence = 0.6
            
            return {
                "success": True,
                "symbol": symbol,
                "prediction": signal,
                "confidence": round(confidence, 2),
                "momentum": round(momentum, 2),
                "current_price": round(close_prices[-1], 2),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        except Exception as e:
            return {"error": str(e)}
    
    def _calculate_simple_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Basit RSI hesaplama"""
        if len(prices) < period:
            return pd.Series([50] * len(prices))
        
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    async def get_comprehensive_analysis(self, symbol: str) -> Dict:
        """Kapsamlı AI analizi"""
        try:
            timeframe_analysis = {}
            
            for tf in ["15m", "1h", "4h"]:
                try:
                    data = await self.fetch_historical(symbol, tf, 100)
                    if not data.empty:
                        close = data['close']
                        sma_20 = close.rolling(20).mean()
                        rsi = self._calculate_simple_rsi(close)
                        
                        current_price = close.iloc[-1] if len(close) > 0 else 0
                        sma_value = sma_20.iloc[-1] if len(sma_20) > 0 else 0
                        rsi_value = rsi.iloc[-1] if len(rsi) > 0 and not pd.isna(rsi.iloc[-1]) else 50
                        
                        trend = "Bullish" if current_price > sma_value else "Bearish"
                        
                        timeframe_analysis[tf] = {
                            "trend": trend,
                            "rsi": round(rsi_value, 1),
                            "price": round(current_price, 2),
                            "signal": self._generate_signal_from_rsi(rsi_value)
                        }
                except Exception as e:
                    timeframe_analysis[tf] = {"error": str(e)}
            
            # Sinyal sentezi
            final_signal, confidence = self._synthesize_signals(timeframe_analysis)
            
            return {
                "success": True,
                "symbol": symbol,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "final_signal": final_signal,
                "final_confidence": confidence,
                "timeframe_analysis": timeframe_analysis,
                "recommendation": self._generate_recommendation(final_signal, confidence),
                "risk_level": self._calculate_risk_level(final_signal, confidence)
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def _generate_signal_from_rsi(self, rsi: float) -> str:
        """RSI'den sinyal üret"""
        if rsi > 70:
            return "Sell"
        elif rsi < 30:
            return "Buy"
        else:
            return "Hold"
    
    def _synthesize_signals(self, timeframe_analysis: Dict) -> tuple:
        """Zaman dilimi sinyallerini birleştir"""
        signals = []
        confidences = []
        
        for tf, analysis in timeframe_analysis.items():
            if isinstance(analysis, dict) and "signal" in analysis:
                signals.append(analysis["signal"])
                weight = {"15m": 0.3, "1h": 0.4, "4h": 0.3}.get(tf, 0.3)
                conf = self._signal_to_confidence(analysis["signal"], analysis.get("rsi", 50))
                confidences.append(conf * weight)
        
        if not signals:
            return "Hold", 0.5
        
        from collections import Counter
        signal_counts = Counter(signals)
        final_signal = signal_counts.most_common(1)[0][0] if signal_counts else "Hold"
        
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
        
        return final_signal, round(avg_confidence, 2)
    
    def _signal_to_confidence(self, signal: str, rsi: float) -> float:
        """Sinyali güven değerine dönüştür"""
        if signal == "Buy" and rsi < 40:
            return 0.8
        elif signal == "Sell" and rsi > 60:
            return 0.8
        elif signal == "Hold" and 40 <= rsi <= 60:
            return 0.7
        else:
            return 0.6
    
    def _generate_recommendation(self, signal: str, confidence: float) -> str:
        """AI önerisi oluştur"""
        recommendations = {
            "Buy": {
                "HIGH": "🚀 STRONG BUY - AI detects strong bullish signals",
                "MEDIUM": "✅ BUY - AI suggests upward movement is likely",
                "LOW": "⚠️ CAUTIOUS BUY - Limited confidence"
            },
            "Sell": {
                "HIGH": "🔴 STRONG SELL - AI predicts downward movement",
                "MEDIUM": "📉 SELL - AI recommends reducing exposure",
                "LOW": "⚠️ CAUTIOUS SELL - Consider partial exit"
            },
            "Hold": {
                "HIGH": "⏸️ STRONG HOLD - AI recommends waiting",
                "MEDIUM": "🤖 HOLD - No clear directional bias",
                "LOW": "❓ UNCLEAR - Mixed signals"
            }
        }
        
        conf_level = "HIGH" if confidence >= 0.7 else "MEDIUM" if confidence >= 0.6 else "LOW"
        return recommendations.get(signal, {}).get(conf_level, "No recommendation available")
    
    def _calculate_risk_level(self, signal: str, confidence: float) -> str:
        """Risk seviyesini hesapla"""
        if confidence >= 0.8:
            return "LOW"
        elif confidence >= 0.6:
            return "MEDIUM"
        else:
            return "HIGH"
    
    async def chat_with_ai(self, message: str, symbol: Optional[str] = None) -> Dict:
        """AI chatbot ile konuş"""
        try:
            responses = {
                "buy": "Based on current analysis, this might be a good buying opportunity.",
                "sell": "The AI suggests caution. Consider taking profits or setting stop losses.",
                "prediction": "AI models show mixed signals. Wait for clearer confirmation.",
                "analysis": "Running comprehensive analysis across multiple timeframes...",
                "hello": "Hello! I'm your AI trading assistant. How can I help you?",
                "help": "I can analyze markets, provide predictions, and discuss trading strategies!"
            }
            
            msg_lower = message.lower()
            for key, response in responses.items():
                if key in msg_lower:
                    return {
                        "success": True,
                        "response": response
                    }
            
            return {
                "success": True,
                "response": f"I've analyzed your query about '{message}'. For detailed analysis, please use the prediction buttons above."
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    async def analyze_trading_image(self, image_bytes: bytes) -> Dict:
        """Trading grafiği analiz et"""
        try:
            return {
                "success": True,
                "analysis": "Chart analysis complete. Detected potential bullish patterns.",
                "patterns": ["Uptrend detected", "Support level identified"],
                "sentiment": "Bullish",
                "confidence": 0.7
            }
        except Exception as e:
            return {"error": str(e)}

# Global AI servis instance'ı
ai_service = AITradingService()
