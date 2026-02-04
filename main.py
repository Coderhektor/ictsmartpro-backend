"""
🎯 PROFESSIONAL SUPPORT/RESISTANCE & TREND REVERSAL ANALYZER
✅ Major/Minor Support & Resistance Levels
✅ Swing High/Low Detection
✅ Higher Highs (HH) & Higher Lows (HL) - Uptrend
✅ Lower Highs (LH) & Lower Lows (LL) - Downtrend
✅ Trend Change Detection (Break of Structure - BOS)
✅ Smart Entry/Exit Zones
✅ Buy at Support / Sell at Resistance Strategy
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import numpy as np

class TrendDirection(str, Enum):
    """Trend yönü"""
    UPTREND = "UPTREND"
    DOWNTREND = "DOWNTREND"
    SIDEWAYS = "SIDEWAYS"
    REVERSAL_TO_UP = "REVERSAL_TO_UP"  # Yükseliş trendine dönüş
    REVERSAL_TO_DOWN = "REVERSAL_TO_DOWN"  # Düşüş trendine dönüş

class LevelStrength(str, Enum):
    """Seviye gücü"""
    MAJOR = "MAJOR"  # Çok güçlü, birden fazla test edilmiş
    MINOR = "MINOR"  # Orta güçte
    WEAK = "WEAK"    # Zayıf

@dataclass
class SwingPoint:
    """Swing High/Low noktası"""
    index: int
    price: float
    is_high: bool  # True = Swing High, False = Swing Low
    strength: int  # Kaç mum ile confirm edildi
    timestamp: Optional[int] = None

@dataclass
class SupportResistanceLevel:
    """Destek/Direnç seviyesi"""
    price: float
    level_type: str  # "support" veya "resistance"
    strength: LevelStrength
    touch_count: int  # Kaç kez test edildi
    first_touch_index: int
    last_touch_index: int
    zone_high: float  # Bölge üst sınırı
    zone_low: float   # Bölge alt sınırı
    confidence: float  # 0-100 arası güven skoru

@dataclass
class TrendStructure:
    """Trend yapısı analizi"""
    direction: TrendDirection
    swing_highs: List[SwingPoint]
    swing_lows: List[SwingPoint]
    higher_highs_count: int
    higher_lows_count: int
    lower_highs_count: int
    lower_lows_count: int
    trend_strength: float  # 0-100
    bos_detected: bool  # Break of Structure
    bos_price: Optional[float] = None
    bos_index: Optional[int] = None

@dataclass
class TradingSignal:
    """Trading sinyali"""
    signal_type: str  # "BUY" veya "SELL"
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    target_3: float
    confidence: float
    reason: str
    risk_reward: float

class SupportResistanceAnalyzer:
    """Destek/Direnç ve Trend Analiz Motoru"""
    
    def __init__(self, swing_window: int = 5, zone_threshold: float = 0.002):
        """
        Args:
            swing_window: Swing point tespiti için bakılacak mum sayısı (her iki yön)
            zone_threshold: Fiyat seviyelerini birleştirme eşiği (% olarak, 0.002 = %0.2)
        """
        self.swing_window = swing_window
        self.zone_threshold = zone_threshold
    
    def detect_swing_points(self, candles: List[Dict]) -> Tuple[List[SwingPoint], List[SwingPoint]]:
        """
        Swing High ve Swing Low noktalarını tespit et
        
        Swing High: Sağında ve solunda en az swing_window kadar mum var ve hepsi daha düşük
        Swing Low: Sağında ve solunda en az swing_window kadar mum var ve hepsi daha yüksek
        """
        swing_highs = []
        swing_lows = []
        
        for i in range(self.swing_window, len(candles) - self.swing_window):
            candle = candles[i]
            
            # Swing High kontrolü
            is_swing_high = True
            for j in range(1, self.swing_window + 1):
                # Sol taraf
                if candles[i - j]["high"] >= candle["high"]:
                    is_swing_high = False
                    break
                # Sağ taraf
                if candles[i + j]["high"] >= candle["high"]:
                    is_swing_high = False
                    break
            
            if is_swing_high:
                swing_highs.append(SwingPoint(
                    index=i,
                    price=candle["high"],
                    is_high=True,
                    strength=self.swing_window,
                    timestamp=candle.get("timestamp")
                ))
            
            # Swing Low kontrolü
            is_swing_low = True
            for j in range(1, self.swing_window + 1):
                # Sol taraf
                if candles[i - j]["low"] <= candle["low"]:
                    is_swing_low = False
                    break
                # Sağ taraf
                if candles[i + j]["low"] <= candle["low"]:
                    is_swing_low = False
                    break
            
            if is_swing_low:
                swing_lows.append(SwingPoint(
                    index=i,
                    price=candle["low"],
                    is_high=False,
                    strength=self.swing_window,
                    timestamp=candle.get("timestamp")
                ))
        
        return swing_highs, swing_lows
    
    def analyze_trend_structure(self, swing_highs: List[SwingPoint], 
                                swing_lows: List[SwingPoint]) -> TrendStructure:
        """
        Trend yapısını analiz et (HH, HL, LH, LL)
        
        Uptrend: Higher Highs (HH) + Higher Lows (HL)
        Downtrend: Lower Highs (LH) + Lower Lows (LL)
        Trend Change: HH/HL dizisi LH/LL'ye dönüşür veya tersi
        """
        # Higher Highs / Lower Highs
        hh_count = 0
        lh_count = 0
        for i in range(1, len(swing_highs)):
            if swing_highs[i].price > swing_highs[i-1].price:
                hh_count += 1
            elif swing_highs[i].price < swing_highs[i-1].price:
                lh_count += 1
        
        # Higher Lows / Lower Lows
        hl_count = 0
        ll_count = 0
        for i in range(1, len(swing_lows)):
            if swing_lows[i].price > swing_lows[i-1].price:
                hl_count += 1
            elif swing_lows[i].price < swing_lows[i-1].price:
                ll_count += 1
        
        # Trend direction belirleme
        total_highs = hh_count + lh_count
        total_lows = hl_count + ll_count
        
        # Break of Structure (BOS) tespiti
        bos_detected = False
        bos_price = None
        bos_index = None
        
        # Trend değişimi: Son 3 swing point'e bak
        if len(swing_highs) >= 3 and len(swing_lows) >= 3:
            recent_highs = swing_highs[-3:]
            recent_lows = swing_lows[-3:]
            
            # Uptrend'den Downtrend'e dönüş: Son HH kırıldı mı?
            if (len(recent_highs) >= 2 and 
                recent_highs[-1].price < recent_highs[-2].price and
                len(recent_lows) >= 2 and
                recent_lows[-1].price < recent_lows[-2].price):
                
                # Önceki HL kırıldıysa BOS
                if len(swing_lows) >= 2:
                    prev_hl = swing_lows[-2].price
                    if recent_lows[-1].price < prev_hl:
                        bos_detected = True
                        bos_price = prev_hl
                        bos_index = recent_lows[-1].index
            
            # Downtrend'den Uptrend'e dönüş: Son LL kırıldı mı?
            if (len(recent_lows) >= 2 and 
                recent_lows[-1].price > recent_lows[-2].price and
                len(recent_highs) >= 2 and
                recent_highs[-1].price > recent_highs[-2].price):
                
                # Önceki LH kırıldıysa BOS
                if len(swing_highs) >= 2:
                    prev_lh = swing_highs[-2].price
                    if recent_highs[-1].price > prev_lh:
                        bos_detected = True
                        bos_price = prev_lh
                        bos_index = recent_highs[-1].index
        
        # Trend direction
        if hh_count > lh_count and hl_count > ll_count:
            # Güçlü uptrend
            if bos_detected and bos_index and len(swing_lows) > 0:
                if swing_lows[-1].index < bos_index:
                    direction = TrendDirection.UPTREND
                else:
                    direction = TrendDirection.REVERSAL_TO_DOWN
            else:
                direction = TrendDirection.UPTREND
        elif lh_count > hh_count and ll_count > hl_count:
            # Güçlü downtrend
            if bos_detected and bos_index and len(swing_highs) > 0:
                if swing_highs[-1].index < bos_index:
                    direction = TrendDirection.DOWNTREND
                else:
                    direction = TrendDirection.REVERSAL_TO_UP
            else:
                direction = TrendDirection.DOWNTREND
        elif bos_detected:
            # BOS var ama net trend yok - reversal
            if hh_count >= lh_count:
                direction = TrendDirection.REVERSAL_TO_UP
            else:
                direction = TrendDirection.REVERSAL_TO_DOWN
        else:
            direction = TrendDirection.SIDEWAYS
        
        # Trend strength hesapla
        if total_highs > 0 and total_lows > 0:
            high_consistency = max(hh_count, lh_count) / total_highs
            low_consistency = max(hl_count, ll_count) / total_lows
            trend_strength = ((high_consistency + low_consistency) / 2) * 100
        else:
            trend_strength = 0.0
        
        return TrendStructure(
            direction=direction,
            swing_highs=swing_highs,
            swing_lows=swing_lows,
            higher_highs_count=hh_count,
            higher_lows_count=hl_count,
            lower_highs_count=lh_count,
            lower_lows_count=ll_count,
            trend_strength=trend_strength,
            bos_detected=bos_detected,
            bos_price=bos_price,
            bos_index=bos_index
        )
    
    def identify_support_resistance_levels(self, candles: List[Dict], 
                                          swing_highs: List[SwingPoint],
                                          swing_lows: List[SwingPoint]) -> Tuple[List[SupportResistanceLevel], List[SupportResistanceLevel]]:
        """
        Destek ve direnç seviyelerini tespit et ve sınıflandır
        """
        # Tüm swing point'leri fiyata göre grupla
        all_points = []
        
        # Swing lows = potential support
        for sl in swing_lows:
            all_points.append({
                "price": sl.price,
                "type": "support",
                "index": sl.index
            })
        
        # Swing highs = potential resistance
        for sh in swing_highs:
            all_points.append({
                "price": sh.price,
                "type": "resistance",
                "index": sh.index
            })
        
        # Fiyata göre sırala
        all_points.sort(key=lambda x: x["price"])
        
        # Yakın fiyatları birleştir (zone oluştur)
        zones = []
        current_zone = None
        
        for point in all_points:
            if current_zone is None:
                current_zone = {
                    "prices": [point["price"]],
                    "types": [point["type"]],
                    "indices": [point["index"]]
                }
            else:
                # Son fiyatla karşılaştır
                last_price = current_zone["prices"][-1]
                price_diff = abs(point["price"] - last_price) / last_price
                
                if price_diff <= self.zone_threshold:
                    # Aynı zone'a ekle
                    current_zone["prices"].append(point["price"])
                    current_zone["types"].append(point["type"])
                    current_zone["indices"].append(point["index"])
                else:
                    # Yeni zone başlat
                    zones.append(current_zone)
                    current_zone = {
                        "prices": [point["price"]],
                        "types": [point["type"]],
                        "indices": [point["index"]]
                    }
        
        if current_zone:
            zones.append(current_zone)
        
        # Zone'ları destek/direnç seviyelerine dönüştür
        support_levels = []
        resistance_levels = []
        
        current_price = candles[-1]["close"]
        
        for zone in zones:
            avg_price = np.mean(zone["prices"])
            touch_count = len(zone["prices"])
            zone_high = max(zone["prices"])
            zone_low = min(zone["prices"])
            
            # Tip belirleme (çoğunluk)
            support_count = zone["types"].count("support")
            resistance_count = zone["types"].count("resistance")
            
            # Strength belirleme
            if touch_count >= 4:
                strength = LevelStrength.MAJOR
                confidence = 90
            elif touch_count >= 2:
                strength = LevelStrength.MINOR
                confidence = 70
            else:
                strength = LevelStrength.WEAK
                confidence = 50
            
            # Fiyat yakınlığı bonusu
            price_distance = abs(avg_price - current_price) / current_price
            if price_distance < 0.01:  # %1 içinde
                confidence += 10
            
            confidence = min(100, confidence)
            
            level = SupportResistanceLevel(
                price=avg_price,
                level_type="support" if support_count >= resistance_count else "resistance",
                strength=strength,
                touch_count=touch_count,
                first_touch_index=min(zone["indices"]),
                last_touch_index=max(zone["indices"]),
                zone_high=zone_high,
                zone_low=zone_low,
                confidence=confidence
            )
            
            # Current price'a göre ayır
            if avg_price < current_price:
                # Aşağıda = Support
                level.level_type = "support"
                support_levels.append(level)
            else:
                # Yukarıda = Resistance
                level.level_type = "resistance"
                resistance_levels.append(level)
        
        # En yakın ve en güçlü seviyeleri tut
        support_levels.sort(key=lambda x: (x.confidence, current_price - x.price), reverse=True)
        resistance_levels.sort(key=lambda x: (x.confidence, x.price - current_price))
        
        # En fazla 5'er seviye
        return support_levels[:5], resistance_levels[:5]
    
    def generate_trading_signals(self, candles: List[Dict],
                                trend_structure: TrendStructure,
                                support_levels: List[SupportResistanceLevel],
                                resistance_levels: List[SupportResistanceLevel]) -> List[TradingSignal]:
        """
        Destek/direnç ve trend yapısına göre trading sinyalleri üret
        
        Stratejiler:
        1. Destekte Alış (Buy at Support in Uptrend)
        2. Dirençte Satış (Sell at Resistance in Downtrend)
        3. Breakout (Direnç kırılımı = Buy, Destek kırılımı = Sell)
        4. Trend Reversal (BOS sonrası ilk pullback)
        """
        signals = []
        current_price = candles[-1]["close"]
        atr = self._calculate_atr(candles, period=14)
        
        # Strategy 1: Buy at Support (Uptrend)
        if trend_structure.direction in [TrendDirection.UPTREND, TrendDirection.REVERSAL_TO_UP]:
            for support in support_levels[:3]:  # En iyi 3 destek
                distance_pct = abs(current_price - support.price) / current_price
                
                # Fiyat desteğe yakınsa (%1 içinde)
                if distance_pct < 0.01 and support.confidence >= 70:
                    entry = support.zone_high
                    stop_loss = support.zone_low - atr
                    
                    # Risk/Reward 1:2, 1:3, 1:4
                    risk = entry - stop_loss
                    target_1 = entry + (risk * 2)
                    target_2 = entry + (risk * 3)
                    target_3 = entry + (risk * 4)
                    
                    # Dirençlere göre ayarla
                    if resistance_levels:
                        nearest_resistance = resistance_levels[0].price
                        if target_1 > nearest_resistance:
                            target_1 = nearest_resistance * 0.98
                        if target_2 > nearest_resistance:
                            target_2 = nearest_resistance * 0.99
                    
                    confidence = support.confidence * (trend_structure.trend_strength / 100)
                    
                    signals.append(TradingSignal(
                        signal_type="BUY",
                        entry_price=entry,
                        stop_loss=stop_loss,
                        target_1=target_1,
                        target_2=target_2,
                        target_3=target_3,
                        confidence=confidence,
                        reason=f"Buy at {support.strength.value} Support in {trend_structure.direction.value}",
                        risk_reward=2.0
                    ))
        
        # Strategy 2: Sell at Resistance (Downtrend)
        if trend_structure.direction in [TrendDirection.DOWNTREND, TrendDirection.REVERSAL_TO_DOWN]:
            for resistance in resistance_levels[:3]:  # En iyi 3 direnç
                distance_pct = abs(current_price - resistance.price) / current_price
                
                # Fiyat dirence yakınsa (%1 içinde)
                if distance_pct < 0.01 and resistance.confidence >= 70:
                    entry = resistance.zone_low
                    stop_loss = resistance.zone_high + atr
                    
                    # Risk/Reward 1:2, 1:3, 1:4
                    risk = stop_loss - entry
                    target_1 = entry - (risk * 2)
                    target_2 = entry - (risk * 3)
                    target_3 = entry - (risk * 4)
                    
                    # Desteklere göre ayarla
                    if support_levels:
                        nearest_support = support_levels[0].price
                        if target_1 < nearest_support:
                            target_1 = nearest_support * 1.02
                        if target_2 < nearest_support:
                            target_2 = nearest_support * 1.01
                    
                    confidence = resistance.confidence * (trend_structure.trend_strength / 100)
                    
                    signals.append(TradingSignal(
                        signal_type="SELL",
                        entry_price=entry,
                        stop_loss=stop_loss,
                        target_1=target_1,
                        target_2=target_2,
                        target_3=target_3,
                        confidence=confidence,
                        reason=f"Sell at {resistance.strength.value} Resistance in {trend_structure.direction.value}",
                        risk_reward=2.0
                    ))
        
        # Strategy 3: Break of Structure (BOS) Trades
        if trend_structure.bos_detected and trend_structure.bos_price:
            bos_price = trend_structure.bos_price
            
            if trend_structure.direction == TrendDirection.REVERSAL_TO_UP:
                # Downtrend kırıldı, uptrend başlıyor
                # Pullback bekle ve al
                if current_price > bos_price * 1.005:  # BOS'un üzerinde
                    entry = bos_price * 1.002
                    stop_loss = bos_price * 0.995
                    risk = entry - stop_loss
                    
                    target_1 = entry + (risk * 2.5)
                    target_2 = entry + (risk * 4)
                    target_3 = entry + (risk * 6)
                    
                    signals.append(TradingSignal(
                        signal_type="BUY",
                        entry_price=entry,
                        stop_loss=stop_loss,
                        target_1=target_1,
                        target_2=target_2,
                        target_3=target_3,
                        confidence=85,
                        reason="BUY on Break of Structure - Trend Reversal to Uptrend",
                        risk_reward=2.5
                    ))
            
            elif trend_structure.direction == TrendDirection.REVERSAL_TO_DOWN:
                # Uptrend kırıldı, downtrend başlıyor
                if current_price < bos_price * 0.995:  # BOS'un altında
                    entry = bos_price * 0.998
                    stop_loss = bos_price * 1.005
                    risk = stop_loss - entry
                    
                    target_1 = entry - (risk * 2.5)
                    target_2 = entry - (risk * 4)
                    target_3 = entry - (risk * 6)
                    
                    signals.append(TradingSignal(
                        signal_type="SELL",
                        entry_price=entry,
                        stop_loss=stop_loss,
                        target_1=target_1,
                        target_2=target_2,
                        target_3=target_3,
                        confidence=85,
                        reason="SELL on Break of Structure - Trend Reversal to Downtrend",
                        risk_reward=2.5
                    ))
        
        # Strategy 4: Breakout Trades
        if resistance_levels and trend_structure.direction == TrendDirection.UPTREND:
            nearest_resistance = resistance_levels[0]
            distance_pct = (nearest_resistance.price - current_price) / current_price
            
            # Dirence çok yakınsa (%0.5 içinde) breakout beklentisi
            if 0 < distance_pct < 0.005 and nearest_resistance.confidence >= 70:
                entry = nearest_resistance.zone_high * 1.002  # Kırılım confirmasyonu
                stop_loss = nearest_resistance.zone_low - atr
                risk = entry - stop_loss
                
                target_1 = entry + (risk * 2)
                target_2 = entry + (risk * 3.5)
                target_3 = entry + (risk * 5)
                
                signals.append(TradingSignal(
                    signal_type="BUY",
                    entry_price=entry,
                    stop_loss=stop_loss,
                    target_1=target_1,
                    target_2=target_2,
                    target_3=target_3,
                    confidence=nearest_resistance.confidence * 0.9,
                    reason=f"Resistance Breakout - {nearest_resistance.strength.value} level",
                    risk_reward=2.0
                ))
        
        if support_levels and trend_structure.direction == TrendDirection.DOWNTREND:
            nearest_support = support_levels[0]
            distance_pct = (current_price - nearest_support.price) / current_price
            
            # Desteğe çok yakınsa (%0.5 içinde) breakdown beklentisi
            if 0 < distance_pct < 0.005 and nearest_support.confidence >= 70:
                entry = nearest_support.zone_low * 0.998  # Kırılım confirmasyonu
                stop_loss = nearest_support.zone_high + atr
                risk = stop_loss - entry
                
                target_1 = entry - (risk * 2)
                target_2 = entry - (risk * 3.5)
                target_3 = entry - (risk * 5)
                
                signals.append(TradingSignal(
                    signal_type="SELL",
                    entry_price=entry,
                    stop_loss=stop_loss,
                    target_1=target_1,
                    target_2=target_2,
                    target_3=target_3,
                    confidence=nearest_support.confidence * 0.9,
                    reason=f"Support Breakdown - {nearest_support.strength.value} level",
                    risk_reward=2.0
                ))
        
        # Confidence'a göre sırala
        signals.sort(key=lambda x: x.confidence, reverse=True)
        
        return signals[:3]  # En iyi 3 sinyal
    
    def _calculate_atr(self, candles: List[Dict], period: int = 14) -> float:
        """Average True Range hesapla"""
        if len(candles) < period + 1:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(candles)):
            high = candles[i]["high"]
            low = candles[i]["low"]
            prev_close = candles[i-1]["close"]
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        if len(true_ranges) < period:
            return 0.0
        
        return np.mean(true_ranges[-period:])
    
    def full_analysis(self, candles: List[Dict]) -> Dict:
        """Tam analiz - Tüm fonksiyonları çalıştır"""
        # 1. Swing points tespit et
        swing_highs, swing_lows = self.detect_swing_points(candles)
        
        # 2. Trend yapısını analiz et
        trend_structure = self.analyze_trend_structure(swing_highs, swing_lows)
        
        # 3. Destek/direnç seviyelerini tespit et
        support_levels, resistance_levels = self.identify_support_resistance_levels(
            candles, swing_highs, swing_lows
        )
        
        # 4. Trading sinyalleri üret
        signals = self.generate_trading_signals(
            candles, trend_structure, support_levels, resistance_levels
        )
        
        current_price = candles[-1]["close"]
        
        return {
            "current_price": current_price,
            "trend_structure": {
                "direction": trend_structure.direction.value,
                "strength": round(trend_structure.trend_strength, 1),
                "higher_highs": trend_structure.higher_highs_count,
                "higher_lows": trend_structure.higher_lows_count,
                "lower_highs": trend_structure.lower_highs_count,
                "lower_lows": trend_structure.lower_lows_count,
                "break_of_structure": trend_structure.bos_detected,
                "bos_price": trend_structure.bos_price,
                "total_swing_highs": len(swing_highs),
                "total_swing_lows": len(swing_lows)
            },
            "support_levels": [
                {
                    "price": round(s.price, 4),
                    "strength": s.strength.value,
                    "touches": s.touch_count,
                    "confidence": round(s.confidence, 1),
                    "zone_high": round(s.zone_high, 4),
                    "zone_low": round(s.zone_low, 4),
                    "distance_from_price_pct": round(((s.price - current_price) / current_price) * 100, 2)
                }
                for s in support_levels
            ],
            "resistance_levels": [
                {
                    "price": round(r.price, 4),
                    "strength": r.strength.value,
                    "touches": r.touch_count,
                    "confidence": round(r.confidence, 1),
                    "zone_high": round(r.zone_high, 4),
                    "zone_low": round(r.zone_low, 4),
                    "distance_from_price_pct": round(((r.price - current_price) / current_price) * 100, 2)
                }
                for r in resistance_levels
            ],
            "trading_signals": [
                {
                    "type": sig.signal_type,
                    "entry": round(sig.entry_price, 4),
                    "stop_loss": round(sig.stop_loss, 4),
                    "target_1": round(sig.target_1, 4),
                    "target_2": round(sig.target_2, 4),
                    "target_3": round(sig.target_3, 4),
                    "confidence": round(sig.confidence, 1),
                    "risk_reward": sig.risk_reward,
                    "reason": sig.reason
                }
                for sig in signals
            ],
            "swing_points": {
                "recent_highs": [
                    {
                        "index": sh.index,
                        "price": round(sh.price, 4),
                        "strength": sh.strength
                    }
                    for sh in swing_highs[-5:]  # Son 5 swing high
                ],
                "recent_lows": [
                    {
                        "index": sl.index,
                        "price": round(sl.price, 4),
                        "strength": sl.strength
                    }
                    for sl in swing_lows[-5:]  # Son 5 swing low
                ]
            }
        }


# ========== TEST FONKSİYONU ==========
def test_analyzer():
    """Test verisi ile analyzer'ı çalıştır"""
    import random
    
    # Simüle edilmiş mum verisi oluştur
    candles = []
    base_price = 50000.0
    
    # Uptrend simülasyonu
    for i in range(50):
        trend = i * 100  # Yavaş artış
        volatility = random.uniform(-500, 500)
        
        open_price = base_price + trend + volatility
        close_price = open_price + random.uniform(-300, 400)
        high_price = max(open_price, close_price) + random.uniform(0, 200)
        low_price = min(open_price, close_price) - random.uniform(0, 200)
        
        candles.append({
            "timestamp": i * 3600000,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": random.uniform(1000, 5000)
        })
    
    # Downtrend simülasyonu
    for i in range(50, 100):
        trend = -(i - 50) * 80  # Düşüş
        volatility = random.uniform(-500, 500)
        
        open_price = base_price + 5000 + trend + volatility
        close_price = open_price + random.uniform(-400, 300)
        high_price = max(open_price, close_price) + random.uniform(0, 200)
        low_price = min(open_price, close_price) - random.uniform(0, 200)
        
        candles.append({
            "timestamp": i * 3600000,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": random.uniform(1000, 5000)
        })
    
    # Analyzer'ı çalıştır
    analyzer = SupportResistanceAnalyzer(swing_window=4, zone_threshold=0.003)
    result = analyzer.full_analysis(candles)
    
    # Sonuçları yazdır
    print("=" * 80)
    print("📊 SUPPORT/RESISTANCE & TREND ANALYSIS RESULTS")
    print("=" * 80)
    
    print(f"\n💰 Current Price: ${result['current_price']:.2f}")
    
    print(f"\n📈 TREND STRUCTURE:")
    ts = result['trend_structure']
    print(f"   Direction: {ts['direction']}")
    print(f"   Strength: {ts['strength']}%")
    print(f"   Higher Highs: {ts['higher_highs']} | Higher Lows: {ts['higher_lows']}")
    print(f"   Lower Highs: {ts['lower_highs']} | Lower Lows: {ts['lower_lows']}")
    print(f"   Break of Structure: {'YES ⚠️' if ts['break_of_structure'] else 'NO'}")
    if ts['bos_price']:
        print(f"   BOS Price: ${ts['bos_price']:.2f}")
    
    print(f"\n🟢 SUPPORT LEVELS ({len(result['support_levels'])} found):")
    for i, sup in enumerate(result['support_levels'][:3], 1):
        print(f"   {i}. ${sup['price']:.2f} | {sup['strength']} | "
              f"{sup['touches']} touches | Conf: {sup['confidence']}% | "
              f"Distance: {sup['distance_from_price_pct']:.2f}%")
    
    print(f"\n🔴 RESISTANCE LEVELS ({len(result['resistance_levels'])} found):")
    for i, res in enumerate(result['resistance_levels'][:3], 1):
        print(f"   {i}. ${res['price']:.2f} | {res['strength']} | "
              f"{res['touches']} touches | Conf: {res['confidence']}% | "
              f"Distance: {res['distance_from_price_pct']:.2f}%")
    
    print(f"\n🎯 TRADING SIGNALS ({len(result['trading_signals'])} found):")
    for i, sig in enumerate(result['trading_signals'], 1):
        print(f"\n   Signal #{i}: {sig['type']} ({'🟢' if sig['type'] == 'BUY' else '🔴'})")
        print(f"   Reason: {sig['reason']}")
        print(f"   Entry: ${sig['entry']:.2f}")
        print(f"   Stop Loss: ${sig['stop_loss']:.2f}")
        print(f"   Target 1: ${sig['target_1']:.2f} (R:R 2:1)")
        print(f"   Target 2: ${sig['target_2']:.2f} (R:R 3:1)")
        print(f"   Target 3: ${sig['target_3']:.2f} (R:R 4:1)")
        print(f"   Confidence: {sig['confidence']:.1f}%")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    print("🚀 Support/Resistance Analyzer Test")
    test_analyzer()  
